"""G10 端到端场景验收：完整用户旅程（脚本化模型 + 真实工具链/存储/签名下载）。

覆盖 tasks.md 10.2：闲聊直答、路由卡片切换、报告任务（数据→文档）、海报任务、
执行中转向、两轮增量修改、满意下载、越权与 XSS 负向用例。
"""

import asyncio
import json

from langchain_core.messages import AIMessage

from app.api.deps import get_agent_model, get_llm
from app.main import app
from app.tools import base as tool_base
from tests.conftest import FakeAgentModel, FakeLLM

HEADERS = {"X-User-Id": "e2e-user"}
INTRUDER = {"X-User-Id": "e2e-intruder"}


def _parse_sse(text: str) -> list[dict]:
    return [
        json.loads(line[len("data: "):])
        for line in text.splitlines()
        if line.startswith("data: ")
    ]


def _types(events: list[dict]) -> list[str]:
    return [e["type"] for e in events]


def _use_model(messages: list[AIMessage]) -> FakeAgentModel:
    model = FakeAgentModel(messages=iter(messages))
    app.dependency_overrides[get_agent_model] = lambda: model
    return model


def _doc_tool(title: str, body: str, call_id: str) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[
            {
                "name": "save_document",
                "args": {"title": title, "content_md": body},
                "id": call_id,
            }
        ],
    )


async def _make_session(app_client, mode: str = "chat") -> str:
    sid = (await app_client.post("/api/sessions", json={}, headers=HEADERS)).json()["id"]
    if mode != "chat":
        await app_client.patch(
            f"/api/sessions/{sid}", json={"mode": mode}, headers=HEADERS
        )
    return sid


async def _latest_task_id(app_client, sid: str) -> str:
    tasks = (await app_client.get(f"/api/sessions/{sid}/tasks", headers=HEADERS)).json()
    return tasks[0]["id"]


# ---- 场景 1：闲聊直答 ----


async def test_chat_direct_answer_journey(app_client):
    app.dependency_overrides[get_llm] = lambda: FakeLLM(["你好", "，很高兴", "帮你"])
    sid = await _make_session(app_client)

    resp = await app_client.post(
        f"/api/sessions/{sid}/messages", json={"content": "你好"}, headers=HEADERS
    )
    events = _parse_sse(resp.text)
    assert "delta" in _types(events)
    done = next(e for e in events if e["type"] == "done")
    assert done["message"]["content"] == "你好，很高兴帮你"

    # 历史回放可见
    msgs = (await app_client.get(f"/api/sessions/{sid}/messages", headers=HEADERS)).json()
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[1]["content"] == "你好，很高兴帮你"


# ---- 场景 2：路由卡片 → 确认切换工作模式 ----


async def test_route_card_confirm_switches_to_work(app_client):
    sid = await _make_session(app_client)  # 普通对话模式
    _use_model([AIMessage(content="报告初稿完成，请预览。")])

    resp = await app_client.post(
        f"/api/sessions/{sid}/messages",
        json={"content": "帮我写一份季度销售报告"},
        headers=HEADERS,
    )
    events = _parse_sse(resp.text)
    card = next(e for e in events if e["type"] == "route_card")
    assert card["reason"]
    message_id = card["message"]["id"]

    confirm = await app_client.post(
        f"/api/sessions/{sid}/route-confirm",
        json={"message_id": message_id, "action": "confirm"},
        headers=HEADERS,
    )
    confirm_events = _parse_sse(confirm.text)
    types = _types(confirm_events)
    assert "mode_switched" in types and "task_created" in types
    assert types[-1] == "preview_ready"

    # 会话模式已切到工作模式
    session = (await app_client.get(f"/api/sessions/{sid}", headers=HEADERS)).json()
    assert session["mode"] == "work"


# ---- 场景 3：报告任务（数据 → 文档）----


async def test_report_task_data_to_document(app_client, monkeypatch):
    """沙箱数据处理 → 汇总写入文档：真实 save_document 落版本链。"""
    # 沙箱执行打桩（不依赖 Docker）：其余工具走真实实现
    async def _fake_sandbox(name: str, args: dict) -> str:
        if name != "run_python_code":
            from app.tools import get_tool_registry

            spec = next(s for s in get_tool_registry().specs() if s.name == name)
            return await spec.func(args)
        return "stdout:\n总计 3 类产品，销售额 42.7 万"

    monkeypatch.setattr(tool_base, "EXECUTE_HOOK", _fake_sandbox)
    _use_model(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "run_python_code",
                        "args": {"code": "print('总计 3 类产品，销售额 42.7 万')"},
                        "id": "c1",
                    }
                ],
            ),
            _doc_tool("销售汇总报告", "## 汇总\n总计 3 类产品，销售额 42.7 万", "c2"),
            AIMessage(content="报告已生成"),
        ]
    )
    sid = await _make_session(app_client, mode="work")

    resp = await app_client.post(
        f"/api/sessions/{sid}/messages",
        json={"content": "分析销售数据并写一份汇总报告"},
        headers=HEADERS,
    )
    events = _parse_sse(resp.text)
    tool_names = [e["name"] for e in events if e["type"] == "tool_call"]
    assert tool_names == ["run_python_code", "save_document"]
    assert events[-1]["type"] == "preview_ready"

    tid = await _latest_task_id(app_client, sid)
    arts = (await app_client.get(f"/api/tasks/{tid}/artifacts", headers=HEADERS)).json()
    assert [a["kind"] for a in arts] == ["document"]
    preview = (
        await app_client.get(f"/api/artifacts/{arts[0]['id']}/preview", headers=HEADERS)
    ).json()
    assert preview["render"] == "markdown"
    assert "42.7 万" in preview["content"]


# ---- 场景 4：海报任务 + 两轮增量修改 + XSS 负向 ----


async def test_poster_two_rounds_revision_and_xss(app_client):
    _use_model(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "save_poster",
                        "args": {
                            "title": "促销海报<script>alert(1)</script>",
                            "slogan": "第一版",
                        },
                        "id": "c1",
                    }
                ],
            ),
            AIMessage(content="v1 完成"),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "save_poster",
                        "args": {
                            "title": "促销海报<script>alert(1)</script>",
                            "slogan": "第二版-加大折扣",
                        },
                        "id": "c2",
                    }
                ],
            ),
            AIMessage(content="v2 完成"),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "save_poster",
                        "args": {
                            "title": "促销海报<script>alert(1)</script>",
                            "slogan": "第三版-加联系方式",
                        },
                        "id": "c3",
                    }
                ],
            ),
            AIMessage(content="v3 完成"),
        ]
    )
    sid = await _make_session(app_client, mode="work")

    await app_client.post(
        f"/api/sessions/{sid}/messages", json={"content": "做一张促销海报"}, headers=HEADERS
    )
    tid = await _latest_task_id(app_client, sid)

    # 两轮增量修改
    for tip in ("加大折扣力度", "加上联系方式"):
        revise = await app_client.post(
            f"/api/sessions/{sid}/messages", json={"content": tip}, headers=HEADERS
        )
        assert _parse_sse(revise.text)[-1]["type"] == "preview_ready"

    arts = (await app_client.get(f"/api/tasks/{tid}/artifacts", headers=HEADERS)).json()
    versions = [v["version"] for v in arts[0]["versions"]]
    assert versions == [1, 2, 3]

    # 最新版预览：XSS 转义 + 内容随版本演进
    art_id = arts[0]["id"]
    v3 = (
        await app_client.get(
            f"/api/artifacts/{art_id}/preview", headers=HEADERS
        )
    ).json()
    assert v3["render"] == "html"
    assert "<script>" not in v3["content"]
    assert "第三版-加联系方式" in v3["content"]
    v1 = (
        await app_client.get(
            f"/api/artifacts/{art_id}/preview?version=1", headers=HEADERS
        )
    ).json()
    assert "第一版" in v1["content"]


# ---- 场景 5：执行中转向 ----


async def test_steering_changes_direction(app_client):
    gate = _SteerGate()
    try:
        _use_model(
            [
                _doc_tool("初稿", "原始内容", "c1"),
                AIMessage(content="已按补充要求重写"),
            ]
        )
        sid = await _make_session(app_client, mode="work")
        bg = asyncio.ensure_future(
            app_client.post(
                f"/api/sessions/{sid}/messages",
                json={"content": "写一篇文章"},
                headers=HEADERS,
            )
        )
        await gate.running.wait()  # 首个工具执行中
        steer = await app_client.post(
            f"/api/sessions/{sid}/messages",
            json={"content": "改成正式书面语"},
            headers=HEADERS,
        )
        assert _parse_sse(steer.text)[-1]["type"] == "steering_queued"
        gate.release.set()
        resp = await bg
        events = _parse_sse(resp.text)
        assert "steering_injected" in _types(events)
        assert events[-1]["type"] == "preview_ready"
    finally:
        gate.close()


class _SteerGate:
    """首个工具调用挂起，等插话入队后放行。"""

    def __init__(self):
        self.release = asyncio.Event()
        self.running = asyncio.Event()
        tool_base.EXECUTE_HOOK = self._gated

    async def _gated(self, name: str, args: dict) -> str:
        from app.tools import get_tool_registry

        self.running.set()
        await self.release.wait()
        spec = next(s for s in get_tool_registry().specs() if s.name == name)
        return await spec.func(args)

    def close(self):
        tool_base.EXECUTE_HOOK = None


# ---- 场景 6：满意下载 + 越权负向 ----


async def test_approve_download_and_intruder_blocked(app_client):
    _use_model(
        [
            _doc_tool("验收文档", "## 内容\n端到端验收通过", "c1"),
            AIMessage(content="文档完成"),
        ]
    )
    sid = await _make_session(app_client, mode="work")
    await app_client.post(
        f"/api/sessions/{sid}/messages", json={"content": "写验收文档"}, headers=HEADERS
    )
    tid = await _latest_task_id(app_client, sid)

    approve = await app_client.post(
        f"/api/tasks/{tid}/feedback", json={"action": "approve"}, headers=HEADERS
    )
    assert _parse_sse(approve.text)[-1]["type"] == "task_completed"

    arts = (await app_client.get(f"/api/tasks/{tid}/artifacts", headers=HEADERS)).json()
    art_id = arts[0]["id"]

    # 越权：他人查列表/预览/换下载链接一律 404（不泄露存在性）
    assert (
        await app_client.get(f"/api/tasks/{tid}/artifacts", headers=INTRUDER)
    ).status_code == 404
    assert (
        await app_client.get(f"/api/artifacts/{art_id}/preview", headers=INTRUDER)
    ).status_code == 404
    assert (
        await app_client.post(
            f"/api/artifacts/{art_id}/versions/1/download", headers=INTRUDER
        )
    ).status_code == 404

    # 本人下载：docx 二进制
    link = (
        await app_client.post(
            f"/api/artifacts/{art_id}/versions/1/download", headers=HEADERS
        )
    ).json()
    assert link["format"] == "docx"
    file = await app_client.get(link["url"], headers=HEADERS)
    assert file.status_code == 200
    assert file.content[:2] == b"PK"
    assert file.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument"
    )

    # 篡改签名 → 403（签名 URL 负向）
    tampered = link["url"][:-2] + ("AA" if link["url"][-2:] != "AA" else "BB")
    assert (
        await app_client.get(tampered, headers=HEADERS)
    ).status_code == 403
