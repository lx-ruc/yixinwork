"""SSE 流式直答测试：事件序、持久化、错误路径。"""

import json

from app.llm import get_llm
from tests.conftest import FailingLLM

HEADERS = {"X-User-Id": "user-a"}


def _parse_sse(text: str) -> list[dict]:
    events = []
    for line in text.splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line[len("data: ") :]))
    return events


async def _create_session(app_client) -> str:
    resp = await app_client.post("/api/sessions", json={}, headers=HEADERS)
    return resp.json()["id"]


async def test_stream_direct_answer_events_and_persistence(
    app_client, fake_llm
):
    from app.main import app

    app.dependency_overrides[get_llm] = lambda: fake_llm
    sid = await _create_session(app_client)

    resp = await app_client.post(
        f"/api/sessions/{sid}/messages",
        json={"content": "你好"},
        headers=HEADERS,
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")

    events = _parse_sse(resp.text)
    types = [e["type"] for e in events]
    assert types[0] == "user_message"
    assert "delta" in types
    assert types[-1] == "done"
    assert events[-1]["usage"]["input_tokens"] == 10

    # LLM 收到 system + 历史(空) + 用户消息
    llm_messages = fake_llm.calls[0]
    assert llm_messages[0]["role"] == "system"
    assert llm_messages[-1] == {"role": "user", "content": "你好"}

    # 持久化：用户 + 助手两条
    msgs = await app_client.get(f"/api/sessions/{sid}/messages", headers=HEADERS)
    roles = [m["role"] for m in msgs.json()]
    assert roles == ["user", "assistant"]
    assert msgs.json()[1]["content"] == "你好，这里是智能体"


async def test_stream_llm_error_yields_error_event(app_client):
    from app.main import app

    app.dependency_overrides[get_llm] = lambda: FailingLLM()
    sid = await _create_session(app_client)

    resp = await app_client.post(
        f"/api/sessions/{sid}/messages",
        json={"content": "你好"},
        headers=HEADERS,
    )
    events = _parse_sse(resp.text)
    assert events[-1]["type"] == "error"

    # 失败时不落助手消息
    msgs = await app_client.get(f"/api/sessions/{sid}/messages", headers=HEADERS)
    assert [m["role"] for m in msgs.json()] == ["user"]


async def test_history_feeds_next_round(app_client, fake_llm):
    from app.main import app

    app.dependency_overrides[get_llm] = lambda: fake_llm
    sid = await _create_session(app_client)

    for content in ("第一句", "第二句"):
        await app_client.post(
            f"/api/sessions/{sid}/messages",
            json={"content": content},
            headers=HEADERS,
        )

    second_call = fake_llm.calls[1]
    roles = [m["role"] for m in second_call]
    assert roles == ["system", "user", "assistant", "user"]
    assert second_call[-1]["content"] == "第二句"
