"""联网搜索工具：后端代查智谱 web-search-pro，结果喂给模型。

沙箱保持无网络隔离；需要外部资料（新闻/数据/政策）时由后端出网检索，
模型拿到的是结构化的标题/链接/摘要，写作时可注明出处。
"""

import json

import httpx

from app.config import get_settings
from app.tools.base import ToolError, ToolRegistry, ToolSpec

DEFAULT_COUNT = 5
MAX_COUNT = 8
SNIPPET_MAX_CHARS = 500  # 摘要截断，控制上下文体量
REQUEST_TIMEOUT_SECONDS = 20.0


async def _web_search(args: dict) -> str:
    query = str(args.get("query", "")).strip()
    if not query:
        raise ToolError("搜索关键词为空，请提供 query")
    settings = get_settings()
    if not settings.glm_api_key:
        raise ToolError("未配置 GLM_API_KEY，联网搜索不可用")

    count = min(int(args.get("count", DEFAULT_COUNT)), MAX_COUNT)
    payload = {
        "model": "web-search-pro",
        "messages": [{"role": "user", "content": query}],
        "stream": False,
    }
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                f"{settings.glm_base_url}/tools",
                headers={"Authorization": f"Bearer {settings.glm_api_key}"},
                json=payload,
            )
    except httpx.HTTPError as exc:
        raise ToolError(f"搜索服务网络异常: {exc}") from exc

    if resp.status_code == 401:
        raise ToolError("搜索服务鉴权失败（API Key 无效或未开通 web-search-pro）")
    if resp.status_code == 429:
        raise ToolError("搜索服务限流，请稍后重试")
    if resp.status_code != 200:
        raise ToolError(f"搜索服务返回 {resp.status_code}: {resp.text[:200]}")

    # 响应形态: choices[0].message.tool_calls[] 里一个条目带 search_intent，
    # 另一个带 search_result（含 title/link/content/media）；按键取，不赌下标。
    results: list[dict] = []
    try:
        tool_calls = resp.json()["choices"][0]["message"]["tool_calls"]
        for call in tool_calls:
            if isinstance(call.get("search_result"), list):
                results = call["search_result"]
                break
    except (KeyError, IndexError, ValueError) as exc:
        raise ToolError(f"搜索服务响应格式异常: {exc}") from exc

    if not results:
        return json.dumps(
            {"query": query, "results": [], "note": "无搜索结果，建议更换关键词重试"},
            ensure_ascii=False,
        )

    trimmed = [
        {
            "title": str(r.get("title", "")).strip(),
            "url": str(r.get("link", "")).strip(),
            "source": str(r.get("media", "")).strip(),
            "snippet": str(r.get("content", "")).strip()[:SNIPPET_MAX_CHARS],
        }
        for r in results[:count]
    ]
    return json.dumps({"query": query, "results": trimmed}, ensure_ascii=False)


def register_search_tools(registry: ToolRegistry) -> None:
    registry.register(
        ToolSpec(
            name="web_search",
            description=(
                "联网搜索最新资料。适用于需要外部信息的情况：新闻时事、公开数据、"
                "政策法规、行业动态、价格行情等。返回若干条结果的标题、链接、"
                "来源媒体与内容摘要。写文档/报告需要引用真实数据时先用本工具检索，"
                "并在产出中注明数据来源。"
            ),
            parameters={
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索关键词，用中文或目标资料语言，具体明确",
                    },
                    "count": {
                        "type": "integer",
                        "description": "返回结果条数，默认 5，最多 8",
                        "minimum": 1,
                        "maximum": MAX_COUNT,
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
            func=_web_search,
        )
    )
