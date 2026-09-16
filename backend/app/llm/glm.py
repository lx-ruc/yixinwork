"""GLM 聊天客户端：OpenAI 兼容协议，流式输出；Agent 侧提供可绑定工具的 chat model。"""

from collections.abc import Iterator
from dataclasses import dataclass
from functools import lru_cache

from openai import OpenAI


class LLMError(Exception):
    """LLM 调用错误（配置缺失、上游失败等）。"""


@dataclass(frozen=True)
class ChatChunk:
    """一次流式分片：文本增量、思考增量或用量统计（最后一个分片）。"""

    delta: str = ""
    reasoning: str = ""  # GLM 思考流（reasoning_content），先于正文下发
    usage: dict | None = None  # {"input_tokens": int, "output_tokens": int}


class GLMChatClient:
    def __init__(self, api_key: str, base_url: str, model: str) -> None:
        if not api_key:
            raise LLMError("GLM_API_KEY 未配置")
        self.model = model
        self._client = OpenAI(api_key=api_key, base_url=base_url)

    def stream_chat(self, messages: list[dict]) -> Iterator[ChatChunk]:
        """流式对话；发生上游错误时抛 LLMError，由调用方转为用户可读事件。"""
        try:
            stream = self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                stream=True,
                stream_options={"include_usage": True},
            )
            for chunk in stream:
                yield from _parse_chunk(chunk)
        except LLMError:
            raise
        except Exception as exc:  # openai SDK 各类异常统一包装
            raise LLMError(f"模型调用失败: {exc}") from exc


def _parse_chunk(chunk) -> Iterator[ChatChunk]:
    delta = ""
    reasoning = ""
    choices = getattr(chunk, "choices", None)
    if choices:
        d = getattr(choices[0], "delta", None)
        content = getattr(d, "content", None) if d else None
        if content:
            delta = content
        # GLM 思考流字段（DeepSeek 方言）；不支持的模型此字段恒空
        rc = getattr(d, "reasoning_content", None) if d else None
        if rc:
            reasoning = rc
    usage = None
    u = getattr(chunk, "usage", None)
    if u is not None:
        usage = {
            "input_tokens": getattr(u, "prompt_tokens", 0) or 0,
            "output_tokens": getattr(u, "completion_tokens", 0) or 0,
        }
    if delta or reasoning or usage:
        yield ChatChunk(delta=delta, reasoning=reasoning, usage=usage)


@lru_cache
def get_chat_model():
    """Agent 循环用的 chat model（可 bind_tools，graph 内流式聚合逐轮调用）。

    与 GLMChatClient 同一份配置。用 ChatDeepSeek 而非 ChatOpenAI：
    langchain-openai 基类不提取 reasoning_content 思考流字段（GLM 同方言），
    ChatDeepSeek 子类在流式路径把它放进 additional_kwargs。
    stream_usage=True：流式聚合下仍取回 usage_metadata 供用量埋点。
    """
    from langchain_deepseek import ChatDeepSeek

    from app.config import get_settings

    settings = get_settings()
    if not settings.glm_api_key:
        raise LLMError("GLM_API_KEY 未配置")
    return ChatDeepSeek(
        api_key=settings.glm_api_key,
        base_url=settings.glm_base_url,
        model=settings.glm_model,
        temperature=0.3,
        stream_usage=True,
    )
