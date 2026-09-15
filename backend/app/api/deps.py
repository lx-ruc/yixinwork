"""FastAPI 公共依赖：数据库会话 + 身份上下文。

鉴权由宿主系统负责；模块信任网关注入的 X-User-Id 头并以此做数据隔离。
"""

from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.db import SessionLocal, get_db
from app.llm.glm import GLMChatClient
from app.llm import get_llm

DbSession = Annotated[Session, Depends(get_db)]


def get_session_factory() -> sessionmaker:
    """SSE 流的独立数据库会话工厂（流生命周期长于请求依赖）。"""
    return SessionLocal


SessionFactory = Annotated[sessionmaker, Depends(get_session_factory)]

LlmClient = Annotated[GLMChatClient, Depends(get_llm)]


def get_current_user_id(
    x_user_id: Annotated[str | None, Header(alias="X-User-Id")] = None,
) -> str:
    """从可信头解析用户身份；生产缺失则 401，开发回退默认用户。"""
    settings = get_settings()
    uid = (x_user_id or "").strip()
    if uid:
        return uid
    if settings.require_user_header:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="缺少 X-User-Id 身份头",
        )
    return settings.dev_default_user_id


CurrentUserId = Annotated[str, Depends(get_current_user_id)]
