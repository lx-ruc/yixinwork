"""附件端到端：上传暂存 → 随消息发送 → extra 持久化 + LLM 收到富化内容。"""

import json

from app.llm import get_llm
from tests.conftest import FakeAgentModel

HEADERS = {"X-User-Id": "user-att"}


def _parse_sse(text: str) -> list[dict]:
    events = []
    for line in text.splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line[len("data: "):]))
    return events


async def _create_session(app_client, mode: str = "chat") -> str:
    resp = await app_client.post(
        "/api/sessions", json={"mode": mode}, headers=HEADERS
    )
    return resp.json()["id"]


class RecordingLLM:
    """直答假模型：记录收到的 messages，回一段固定输出。"""

    def __init__(self):
        self.seen: list[list[dict]] = []

    def stream_chat(self, messages):
        self.seen.append([dict(m) for m in messages])
        chunk = lambda delta, usage=None: type(  # noqa: E731
            "C", (), {"reasoning": None, "delta": delta, "usage": usage}
        )()
        yield chunk("收到")
        yield chunk("", {"input_tokens": 1, "output_tokens": 1})


async def test_chat_message_with_attachment_enriches_llm_context(app_client):
    from app.main import app

    llm = RecordingLLM()
    app.dependency_overrides[get_llm] = lambda: llm

    up = await app_client.post(
        "/api/uploads",
        files=[("files", ("纪要.txt", "会议决定：Q4 预算追加 80 万".encode(), "text/plain"))],
        headers=HEADERS,
    )
    assert up.status_code == 200
    att_id = up.json()["attachments"][0]["id"]
    assert "text" not in up.json()["attachments"][0]  # 文本不回传前端

    sid = await _create_session(app_client)
    resp = await app_client.post(
        f"/api/sessions/{sid}/messages",
        json={"content": "附件里说了啥，简单讲讲", "attachments": [{"id": att_id}]},
        headers=HEADERS,
    )
    events = _parse_sse(resp.text)
    assert events[0]["type"] == "user_message"
    stored = events[0]["message"]["extra"]["attachments"]
    assert stored[0]["name"] == "纪要.txt" and "Q4 预算" in stored[0]["text"]

    last_user = [m for m in llm.seen[-1] if m["role"] == "user"][-1]
    assert "Q4 预算追加 80 万" in last_user["content"]
    assert events[-1]["type"] == "done"


async def test_work_message_with_attachment_injects_instruction(app_client):
    from app.main import app

    agent_model = FakeAgentModel(messages=iter([]))
    agent_model.messages = iter([])  # 占位；真正的回复流由 graph 驱动到 preview
    up = await app_client.post(
        "/api/uploads",
        files=[("files", ("数据.csv", "月份,销量\n1月,120".encode(), "text/csv"))],
        headers=HEADERS,
    )
    att_id = up.json()["attachments"][0]["id"]

    sid = await _create_session(app_client, mode="work")
    resp = await app_client.post(
        f"/api/sessions/{sid}/messages",
        json={"content": "按附件数据做分析", "attachments": [{"id": att_id}]},
        headers=HEADERS,
    )
    events = _parse_sse(resp.text)
    types = [e["type"] for e in events]
    assert "user_message" in types and "task_created" in types
    assert events[0]["message"]["extra"]["attachments"][0]["kind"] == "csv"
    # 任务指令展示用原文（不带附件块）
    task = next(e for e in events if e["type"] == "task_created")["task"]
    assert task["instruction"] == "按附件数据做分析"


async def test_upload_rejects_bad_type_and_missing_ref(app_client):
    bad = await app_client.post(
        "/api/uploads",
        files=[("files", ("virus.exe", b"MZ", "application/octet-stream"))],
        headers=HEADERS,
    )
    assert bad.status_code == 415

    sid = await _create_session(app_client)
    resp = await app_client.post(
        f"/api/sessions/{sid}/messages",
        json={"content": "你好", "attachments": [{"id": "0" * 32}]},
        headers=HEADERS,
    )
    assert resp.status_code == 415
