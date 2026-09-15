"""智能路由流程测试：卡片事件、确认入工作模式、拒绝直答、越权与重复确认。"""

import json

from app.llm import get_llm
from app.models import Task
from tests.conftest import FakeLLM

HEADERS = {"X-User-Id": "user-a"}

TASK_MSG = "帮我做一份Q3销售数据报告"


def _parse_sse(text: str) -> list[dict]:
    events = []
    for line in text.splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line[len("data: ") :]))
    return events


async def _create_session(app_client) -> str:
    resp = await app_client.post("/api/sessions", json={}, headers=HEADERS)
    return resp.json()["id"]


async def _send_task_message(app_client, fake_llm) -> tuple[str, str]:
    """普通对话模式发任务型消息，返回 (session_id, message_id)。"""
    from app.main import app

    app.dependency_overrides[get_llm] = lambda: fake_llm
    sid = await _create_session(app_client)
    resp = await app_client.post(
        f"/api/sessions/{sid}/messages", json={"content": TASK_MSG}, headers=HEADERS
    )
    events = _parse_sse(resp.text)
    assert events[1]["type"] == "route_card"
    return sid, events[0]["message"]["id"]


async def test_task_message_yields_route_card_without_llm(app_client, fake_llm):
    sid, msg_id = await _send_task_message(app_client, fake_llm)

    # 卡片流程不调用 LLM
    assert fake_llm.calls == []
    # 消息落库且带路由元数据
    msgs = (await app_client.get(f"/api/sessions/{sid}/messages", headers=HEADERS)).json()
    assert [m["role"] for m in msgs] == ["user"]  # 无助手消息
    assert msgs[0]["extra"]["route"]["status"] == "pending"
    assert msgs[0]["id"] == msg_id


async def test_chat_message_has_no_card(app_client, fake_llm):
    from app.main import app

    app.dependency_overrides[get_llm] = lambda: fake_llm
    sid = await _create_session(app_client)
    resp = await app_client.post(
        f"/api/sessions/{sid}/messages", json={"content": "你好"}, headers=HEADERS
    )
    types = [e["type"] for e in _parse_sse(resp.text)]
    assert "route_card" not in types
    assert "delta" in types


async def test_decline_answers_original_message(app_client):
    fake_llm = FakeLLM(["好的，", "这里直接回答"])
    sid, msg_id = await _send_task_message(app_client, fake_llm)

    resp = await app_client.post(
        f"/api/sessions/{sid}/route-confirm",
        json={"message_id": msg_id, "action": "decline"},
        headers=HEADERS,
    )
    events = _parse_sse(resp.text)
    assert "delta" in [e["type"] for e in events]
    assert events[-1]["message"]["role"] == "assistant"

    # 直答回复基于已落库的原消息：system + user 各一条
    llm_messages = fake_llm.calls[0]
    assert [m["role"] for m in llm_messages] == ["system", "user"]
    assert llm_messages[-1]["content"] == TASK_MSG

    # 状态回写 declined；用户消息不重复
    msgs = (await app_client.get(f"/api/sessions/{sid}/messages", headers=HEADERS)).json()
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[0]["extra"]["route"]["status"] == "declined"


async def test_confirm_switches_to_work_and_creates_task(
    app_client, fake_llm, db_sessionmaker
):
    sid, msg_id = await _send_task_message(app_client, fake_llm)

    resp = await app_client.post(
        f"/api/sessions/{sid}/route-confirm",
        json={"message_id": msg_id, "action": "confirm"},
        headers=HEADERS,
    )
    events = _parse_sse(resp.text)
    types = [e["type"] for e in events]
    assert types == ["mode_switched", "task_created", "done"]
    assert events[0]["mode"] == "work"
    assert events[1]["task"]["status"] == "pending"

    # 会话切到工作模式
    session = (await app_client.get("/api/sessions", headers=HEADERS)).json()
    assert next(s for s in session if s["id"] == sid)["mode"] == "work"

    # 任务指令 = 原消息
    with db_sessionmaker() as db:
        task = db.query(Task).one()
        assert task.instruction == TASK_MSG
        assert task.user_id == "user-a"
        assert task.session_id == sid


async def test_route_confirm_only_once(app_client, fake_llm):
    sid, msg_id = await _send_task_message(app_client, fake_llm)
    body = {"message_id": msg_id, "action": "confirm"}

    first = await app_client.post(
        f"/api/sessions/{sid}/route-confirm", json=body, headers=HEADERS
    )
    assert first.status_code == 200
    second = await app_client.post(
        f"/api/sessions/{sid}/route-confirm", json=body, headers=HEADERS
    )
    assert second.status_code == 409


async def test_other_users_message_not_visible(app_client, fake_llm):
    sid, msg_id = await _send_task_message(app_client, fake_llm)
    resp = await app_client.post(
        f"/api/sessions/{sid}/route-confirm",
        json={"message_id": msg_id, "action": "decline"},
        headers={"X-User-Id": "user-b"},
    )
    assert resp.status_code == 404  # 会话本身即不可见


async def test_work_mode_message_creates_task_directly(app_client, db_sessionmaker):
    sid = await _create_session(app_client)
    await app_client.patch(
        f"/api/sessions/{sid}", json={"mode": "work"}, headers=HEADERS
    )

    resp = await app_client.post(
        f"/api/sessions/{sid}/messages",
        json={"content": "随便说句话"},
        headers=HEADERS,
    )
    types = [e["type"] for e in _parse_sse(resp.text)]
    # 工作模式不做路由判断：无 route_card，消息直接成为任务
    assert types == ["user_message", "task_created", "done"]
    with db_sessionmaker() as db:
        assert db.query(Task).count() == 1
