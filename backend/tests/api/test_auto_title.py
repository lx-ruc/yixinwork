"""会话自动命名：占位标题在首条用户消息落库时按内容改写，之后不再变。"""

import json

from app.llm import get_llm
from app.services.chat_service import AUTO_TITLE_MAX, auto_title
from tests.conftest import FakeLLM

HEADERS = {"X-User-Id": "user-a"}


def _parse_sse(text: str) -> list[dict]:
    return [
        json.loads(line[len("data: ") :])
        for line in text.splitlines()
        if line.startswith("data: ")
    ]


async def _create_session(app_client, mode: str = "chat") -> str:
    resp = await app_client.post(
        "/api/sessions", json={"mode": mode}, headers=HEADERS
    )
    return resp.json()["id"]


async def _title_of(app_client, sid: str) -> str:
    resp = await app_client.get(f"/api/sessions/{sid}", headers=HEADERS)
    return resp.json()["title"]


# ── 纯函数 ──────────────────────────────────────────────
def test_auto_title_short_passthrough():
    assert auto_title("帮我写一份周报") == "帮我写一份周报"


def test_auto_title_truncates_with_ellipsis():
    long = "帮我整理一份关于二季度销售数据的详细分析报告"
    title = auto_title(long)
    assert len(title) == AUTO_TITLE_MAX + 1  # 截断 + 省略号
    assert title.startswith(long[:AUTO_TITLE_MAX])
    assert title.endswith("…")


def test_auto_title_collapses_whitespace():
    assert auto_title("帮我写  \n\n 一份   周报") == "帮我写 一份 周报"


def test_auto_title_empty_falls_back_to_default():
    assert auto_title("   ") == "新会话"


# ── 集成：chat / work 两条路径 ───────────────────────────
async def test_first_chat_message_renames_session(app_client, fake_llm):
    from app.main import app

    app.dependency_overrides[get_llm] = lambda: fake_llm
    sid = await _create_session(app_client)

    resp = await app_client.post(
        f"/api/sessions/{sid}/messages",
        json={"content": "帮我写一份项目周报"},
        headers=HEADERS,
    )
    assert resp.status_code == 200
    assert await _title_of(app_client, sid) == "帮我写一份项目周报"


async def test_second_message_keeps_first_title(app_client, fake_llm):
    from app.main import app

    app.dependency_overrides[get_llm] = lambda: fake_llm
    sid = await _create_session(app_client)

    for content in ("第一句：介绍项目背景", "第二句：换个话题聊"):
        resp = await app_client.post(
            f"/api/sessions/{sid}/messages",
            json={"content": content},
            headers=HEADERS,
        )
        assert resp.status_code == 200

    assert await _title_of(app_client, sid) == "第一句：介绍项目背景"


async def test_work_mode_first_message_renames_session(app_client):
    """工作模式（无路由卡片直连任务流）同样触发首条命名。"""
    sid = await _create_session(app_client, mode="work")
    resp = await app_client.post(
        f"/api/sessions/{sid}/messages",
        json={"content": "把这份资料做成幻灯片"},
        headers=HEADERS,
    )
    assert resp.status_code == 200
    assert _parse_sse(resp.text)[-1]["type"] != "error"
    assert await _title_of(app_client, sid) == "把这份资料做成幻灯片"


async def test_user_titled_session_not_overwritten(app_client, fake_llm):
    """用户创建时显式起过名的会话不被自动命名覆盖。"""
    from app.main import app

    app.dependency_overrides[get_llm] = lambda: FakeLLM(["好"])
    resp = await app_client.post(
        "/api/sessions", json={"title": "我的专用会话"}, headers=HEADERS
    )
    sid = resp.json()["id"]
    await app_client.post(
        f"/api/sessions/{sid}/messages",
        json={"content": "随便聊点什么"},
        headers=HEADERS,
    )
    assert await _title_of(app_client, sid) == "我的专用会话"
