"""会话与消息表：普通对话/工作模式共用，按 user_id 隔离。"""

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import TimestampMixin, UUIDMixin

# 会话当前模式
MODE_CHAT = "chat"
MODE_WORK = "work"
SESSION_MODES = (MODE_CHAT, MODE_WORK)

# 消息角色
ROLE_USER = "user"
ROLE_ASSISTANT = "assistant"
ROLE_SYSTEM = "system"
MESSAGE_ROLES = (ROLE_USER, ROLE_ASSISTANT, ROLE_SYSTEM)


class ChatSession(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "sessions"

    # 身份由宿主系统注入（可信头），模块不拥有用户表，故无外键
    user_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(128), nullable=False, default="新会话")
    mode: Mapped[str] = mapped_column(String(8), nullable=False, default=MODE_CHAT)


class Message(UUIDMixin, Base):
    __tablename__ = "messages"

    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sessions.id"), index=True, nullable=False
    )
    # 冗余 user_id：越权过滤与审计直接走本表
    user_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # 路由/工具等附加信息（如确认卡片元数据）
    extra: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime, server_default=func.now()
    )
