"""G5 Agent 执行核心 API 测试：工具循环事件流、执行中插话、预览反馈链。"""

import json

from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver

from app.api.deps import get_agent_model, get_checkpointer
from app.main import app
from app.models import Task
from tests.conftest import FakeAgentModel

HEADERS = {"X-User-Id": "agent-user"}


def _parse_sse(text: str) -> list[dict]:
    return [
        json.loads(line[len("data: "):])
        for line in text.splitlines()
        if line.startswith("data: ")
    ]


async def _work_session(app_client) -> str:
    sid = (await app_client.post("/api/sessions", json={}, headers=HEADERS)).json()["id"]
    await app_client.patch(f"/api/sessions/{sid}", json={"mode": "work"}, headers=HEADERS)
    return sid


def _use_model(model) -> FakeAgentModel:
    app.dependency_overrides[get_agent_model] = lambda: model
    return model


async def test_tool_loop_events_and_preview(app_client, db_sessionmaker):
    """工具调用 → 结果回传 → 出稿 → 预览就绪。"""
    model = _use_model(
        FakeAgentModel(
            messages=iter(
                [
                    AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "name": "save_document",
                                "args": {
                                    "title": "Q3销售报告",
                                    "content_md": "## 概况\n三季度销售额环比增长。",
                                },
                                "id": "c1",
                            }
                        ],
                    ),
                    AIMessage(content="报告初稿完成"),
                ]
            )
        )
    )
    sid = await _work_session(app_client)

    resp = await app_client.post(
        f"/api/sessions/{sid}/messages",
        json={"content": "帮我写Q3销售报告"},
        headers=HEADERS,
    )
    events = _parse_sse(resp.text)
    types = [e["type"] for e in events]

    assert "task_created" in types
    assert "tool_call" in types and "tool_result" in types
    assert types[-1] == "preview_ready"
    tool_call = next(e for e in events if e["type"] == "tool_call")
    assert tool_call["name"] == "save_document"
    tool_result = next(e for e in events if e["type"] == "tool_result")
    assert "document.md" in tool_result["content"]

    # 任务状态落到预览就绪；里程碑助手消息已持久化
    with db_sessionmaker() as db:
        task = db.query(Task).one()
        assert task.status == "preview_ready"
    msgs = (await app_client.get(f"/api/sessions/{sid}/messages", headers=HEADERS)).json()
    kinds = [m["extra"]["kind"] for m in msgs if m["extra"]]
    assert "preview" in kinds

    # LLM 第二轮输入包含工具结果；每轮均前置系统提示（工具使用规范）
    assert any(m.type == "tool" for m in model.calls[1])
    assert model.calls[0][0].type == "system"


async def test_steering_injected_during_run(app_client):
    """执行中消息作为插话注入（tools 节点间隙），语义跟随当前任务。"""
    gate = _SteerGate()
    model = _use_model(
        FakeAgentModel(
            messages=iter(
                [
                    AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "name": "save_poster",
                                "args": {"title": "双11海报", "slogan": "全场五折"},
                                "id": "c1",
                            }
                        ],
                    ),
                    AIMessage(content="已按补充要求完成"),
                ]
            )
        )
    )
    sid = await _work_session(app_client)

    import asyncio

    try:
        bg = asyncio.ensure_future(
            app_client.post(
                f"/api/sessions/{sid}/messages",
                json={"content": "做一张海报"},
                headers=HEADERS,
            )
        )
        await gate.running.wait()  # 等工具执行中
        steer = await app_client.post(
            f"/api/sessions/{sid}/messages",
            json={"content": "加上双11主题"},
            headers=HEADERS,
        )
        steer_events = _parse_sse(steer.text)
        assert steer_events[-1]["type"] == "steering_queued"
        gate.release.set()
        resp = await bg
    finally:
        gate.close()
    events = _parse_sse(resp.text)

    assert "steering_injected" in [e["type"] for e in events]
    injected = next(e for e in events if e["type"] == "steering_injected")
    assert injected["content"] == "加上双11主题"
    # 下一轮 LLM 输入可见插话
    assert any(
        "加上双11主题" in str(getattr(m, "content", ""))
        for m in model.calls[1]
        if m.type == "human"
    )


async def test_feedback_revise_then_approve(app_client, db_sessionmaker):
    """预览反馈链：修改指令恢复 thread 续跑（版本链）→ 满意交付终止。"""
    model = _use_model(
        FakeAgentModel(
            messages=iter(
                [
                    AIMessage(content="第一版"),  # 初稿 → 预览
                    AIMessage(content="第二版（按修改要求）"),  # 修订 → 预览
                ]
            )
        )
    )
    sid = await _work_session(app_client)

    resp = await app_client.post(
        f"/api/sessions/{sid}/messages",
        json={"content": "写个方案"},
        headers=HEADERS,
    )
    task_id = next(e for e in _parse_sse(resp.text) if e["type"] == "task_created")["task"]["id"]

    # 修改指令（经会话消息入口 = preview_ready 分支）
    revise = await app_client.post(
        f"/api/sessions/{sid}/messages",
        json={"content": "篇幅压缩到一页"},
        headers=HEADERS,
    )
    revise_events = _parse_sse(revise.text)
    assert "task_revising" in [e["type"] for e in revise_events]
    assert revise_events[-1]["type"] == "preview_ready"

    # 修改要求进入新一轮 LLM
    assert any(
        "篇幅压缩到一页" in str(getattr(m, "content", "")) for m in model.calls[1]
    )

    # 满意 → 交付终态
    approve = await app_client.post(
        f"/api/tasks/{task_id}/feedback",
        json={"action": "approve"},
        headers=HEADERS,
    )
    approve_events = _parse_sse(approve.text)
    assert approve_events[-1]["type"] == "task_completed"
    with db_sessionmaker() as db:
        assert db.query(Task).one().status == "delivered"

    # 交付后不能再反馈
    again = await app_client.post(
        f"/api/tasks/{task_id}/feedback",
        json={"action": "approve"},
        headers=HEADERS,
    )
    assert again.status_code == 409


async def test_feedback_cross_user_404(app_client):
    sid = await _work_session(app_client)
    _use_model(FakeAgentModel(messages=iter([AIMessage(content="初稿")])))
    resp = await app_client.post(
        f"/api/sessions/{sid}/messages",
        json={"content": "写个方案"},
        headers=HEADERS,
    )
    task_id = next(e for e in _parse_sse(resp.text) if e["type"] == "task_created")["task"]["id"]
    other = await app_client.post(
        f"/api/tasks/{task_id}/feedback",
        json={"action": "approve"},
        headers={"X-User-Id": "intruder"},
    )
    assert other.status_code == 404


class _SteerGate:
    """经注册表测试钩子让工具执行挂起，等插话入队后放行（复刻执行中时序）。"""

    def __init__(self):
        import asyncio

        from app.tools import base

        self.release = asyncio.Event()
        self.running = asyncio.Event()
        base.EXECUTE_HOOK = self._gated

    async def _gated(self, name: str, args: dict) -> str:
        self.running.set()
        await self.release.wait()
        return f"{name} 已执行（{args.get('title', '')}）"

    def close(self):
        from app.tools import base

        base.EXECUTE_HOOK = None
