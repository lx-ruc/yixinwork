"""思考过程流测试：直答 reasoning_delta 事件与落库；Agent 每轮推理事件（不落库）。"""

import json

from langchain_core.messages import AIMessage

from app.api.deps import get_agent_model
from app.llm import get_llm
from app.llm.glm import ChatChunk
from app.main import app
from tests.conftest import FakeAgentModel

HEADERS = {"X-User-Id": "think-user"}


def _parse_sse(text: str) -> list[dict]:
    return [
        json.loads(line[len("data: "):])
        for line in text.splitlines()
        if line.startswith("data: ")
    ]


async def _create_session(app_client) -> str:
    return (await app_client.post("/api/sessions", json={}, headers=HEADERS)).json()["id"]


class ReasoningLLM:
    """先回放思考分片，再回放正文分片（模拟 GLM reasoning_content 前置）。"""

    def __init__(self, reasoning: list[str], deltas: list[str]):
        self.reasoning = reasoning
        self.deltas = deltas

    def stream_chat(self, messages):
        for r in self.reasoning:
            yield ChatChunk(reasoning=r)
        for d in self.deltas:
            yield ChatChunk(delta=d)
        yield ChatChunk(usage={"input_tokens": 5, "output_tokens": 7})


async def test_direct_answer_emits_reasoning_delta_and_persists(app_client):
    llm = ReasoningLLM(["用户在打招呼，", "应当简洁友好。"], ["你好", "！"])
    app.dependency_overrides[get_llm] = lambda: llm
    sid = await _create_session(app_client)

    resp = await app_client.post(
        f"/api/sessions/{sid}/messages", json={"content": "你好"}, headers=HEADERS
    )
    events = _parse_sse(resp.text)
    types = [e["type"] for e in events]

    # 思考事件在用户消息后、正文前，逐分片下发
    assert types[0] == "user_message"
    assert types[1] == "reasoning_delta"
    assert types.count("reasoning_delta") == 2
    assert types.index("reasoning_delta") < types.index("delta")
    assert events[1]["content"] == "用户在打招呼，"

    # 思考全文随助手消息落库（历史回放可见）
    msgs = (await app_client.get(f"/api/sessions/{sid}/messages", headers=HEADERS)).json()
    assistant = msgs[-1]
    assert assistant["content"] == "你好！"
    assert assistant["extra"]["reasoning"] == "用户在打招呼，应当简洁友好。"


async def test_direct_answer_without_reasoning_has_no_events(app_client, fake_llm):
    app.dependency_overrides[get_llm] = lambda: fake_llm
    sid = await _create_session(app_client)

    resp = await app_client.post(
        f"/api/sessions/{sid}/messages", json={"content": "你好"}, headers=HEADERS
    )
    types = [e["type"] for e in _parse_sse(resp.text)]
    assert "reasoning_delta" not in types


async def test_agent_round_streams_reasoning_before_tool(app_client):
    """Agent 每轮推理经 custom 流下发，先于该轮工具调用事件；过程不落库。"""
    model = FakeAgentModel(
        messages=iter(
            [
                AIMessage(
                    content="",
                    additional_kwargs={"reasoning_content": "先保存文档，再汇报。"},
                    tool_calls=[
                        {
                            "name": "save_document",
                            "args": {"title": "思考测试", "content_md": "内容"},
                            "id": "c1",
                        }
                    ],
                ),
                AIMessage(content="初稿完成"),
            ]
        )
    )
    app.dependency_overrides[get_agent_model] = lambda: model
    sid = await _create_session(app_client)
    await app_client.patch(
        f"/api/sessions/{sid}", json={"mode": "work"}, headers=HEADERS
    )

    resp = await app_client.post(
        f"/api/sessions/{sid}/messages",
        json={"content": "写一份思考测试文档"},
        headers=HEADERS,
    )
    events = _parse_sse(resp.text)
    types = [e["type"] for e in events]

    assert "reasoning_delta" in types
    assert types.index("reasoning_delta") < types.index("tool_call")
    reasoning = next(e for e in events if e["type"] == "reasoning_delta")
    assert reasoning["content"] == "先保存文档，再汇报。"

    # 思考为过程事件：不写入消息表
    msgs = (await app_client.get(f"/api/sessions/{sid}/messages", headers=HEADERS)).json()
    assert all("reasoning" not in (m["extra"] or {}) for m in msgs)

    # 流式聚合不破坏既有循环（调用记录仍在）
    assert len(model.calls) == 2
