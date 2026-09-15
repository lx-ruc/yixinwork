"""LLM 客户端入口。"""

from functools import lru_cache

from app.config import get_settings
from app.llm.glm import ChatChunk, GLMChatClient, LLMError


@lru_cache
def get_llm() -> GLMChatClient:
    s = get_settings()
    return GLMChatClient(s.glm_api_key, s.glm_base_url, s.glm_model)
