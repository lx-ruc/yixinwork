"""会话服务：归属校验（数据隔离的强制点）。"""

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ChatSession


def get_owned_session(db: Session, user_id: str, session_id: str) -> ChatSession:
    """按 user_id 过滤查询；不存在或不属于该用户一律 404（不泄露他人数据）。"""
    session = db.scalar(
        select(ChatSession).where(
            ChatSession.id == session_id, ChatSession.user_id == user_id
        )
    )
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在"
        )
    return session
