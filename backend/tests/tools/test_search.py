"""联网搜索工具单测：结果解析、条数截断、错误映射、参数校验（HTTP 层 mock）。"""

import json

import pytest

from app.tools.base import ToolError, ToolRegistry
from app.tools.search import register_search_tools, SNIPPET_MAX_CHARS


class _Resp:
    def __init__(self, status_code: int = 200, payload: dict | None = None, text: str = ""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self) -> dict:
        return self._payload


def _api_payload(results: list[dict] | None) -> dict:
    calls = [{"type": "search_intent", "search_intent": []}]
    if results is not None:
        calls.append({"type": "search_result", "search_result": results})
    return {"choices": [{"message": {"tool_calls": calls}}]}


def _install(monkeypatch, resp: _Resp, calls: list | None = None, exc: Exception | None = None):
    class _Client:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, **kw):
            if calls is not None:
                calls.append({"url": url, **kw})
            if exc is not None:
                raise exc
            return resp

    import app.tools.search as search_mod

    monkeypatch.setattr(search_mod.httpx, "AsyncClient", _Client)

    class _Settings:
        glm_api_key = "test-key"
        glm_base_url = "https://open.bigmodel.cn/api/paas/v4"

    monkeypatch.setattr(search_mod, "get_settings", lambda: _Settings())


@pytest.fixture
def registry() -> ToolRegistry:
    reg = ToolRegistry()
    register_search_tools(reg)
    return reg


async def test_web_search_formats_results(registry, monkeypatch):
    results = [
        {
            "title": f"结果{i}",
            "link": f"https://example.com/{i}",
            "media": "示例网",
            "content": "摘要" * 400,
        }
        for i in range(1, 11)
    ]
    _install(monkeypatch, _Resp(payload=_api_payload(results)))
    raw = await registry.execute("web_search", {"query": "测试", "count": 3})
    parsed = json.loads(raw)
    assert parsed["query"] == "测试"
    assert len(parsed["results"]) == 3  # count 截断
    first = parsed["results"][0]
    assert first["title"] == "结果1"
    assert first["url"] == "https://example.com/1"
    assert first["source"] == "示例网"
    assert len(first["snippet"]) == SNIPPET_MAX_CHARS  # 摘要截断


async def test_web_search_no_results_gives_note(registry, monkeypatch):
    _install(monkeypatch, _Resp(payload=_api_payload(None)))
    parsed = json.loads(await registry.execute("web_search", {"query": "冷门词"}))
    assert parsed["results"] == []
    assert "更换关键词" in parsed["note"]


async def test_web_search_maps_auth_error(registry, monkeypatch):
    _install(monkeypatch, _Resp(status_code=401, text="unauthorized"))
    with pytest.raises(ToolError, match="鉴权失败"):
        await registry.execute("web_search", {"query": "x"})


async def test_web_search_maps_network_error(registry, monkeypatch):
    import httpx

    _install(monkeypatch, None, exc=httpx.ConnectTimeout("boom"))
    with pytest.raises(ToolError, match="网络异常"):
        await registry.execute("web_search", {"query": "x"})


async def test_web_search_rejects_empty_query(registry):
    with pytest.raises(ToolError, match="关键词为空"):
        await registry.execute("web_search", {"query": "   "})


async def test_web_search_requires_api_key(registry, monkeypatch):
    import app.tools.search as search_mod

    class _NoKey:
        glm_api_key = ""
        glm_base_url = "https://open.bigmodel.cn/api/paas/v4"

    monkeypatch.setattr(search_mod, "get_settings", lambda: _NoKey())
    with pytest.raises(ToolError, match="GLM_API_KEY"):
        await registry.execute("web_search", {"query": "x"})


def test_registered_in_global_registry():
    from app.tools import get_tool_registry

    assert get_tool_registry().execute  # 注册表可执行
    names = [s.name for s in get_tool_registry().specs()]
    assert "web_search" in names
