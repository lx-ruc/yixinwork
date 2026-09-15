"""工作模式任务表：状态机见 design.md 决策 1。"""

from sqlalchemy import JSON, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import TimestampMixin, UUIDMixin

# 任务状态机：待命→执行中→预览就绪→（修改→执行中）*→已交付 / 失败
TASK_PENDING = "pending"
TASK_RUNNING = "running"
TASK_PREVIEW_READY = "preview_ready"
TASK_DELIVERED = "delivered"
TASK_FAILED = "failed"
TASK_STATUSES = (
    TASK_PENDING,
    TASK_RUNNING,
    TASK_PREVIEW_READY,
    TASK_DELIVERED,
    TASK_FAILED,
)


class Task(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "tasks"

    user_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sessions.id"), index=True, nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=TASK_PENDING)
    # 原始任务指令
    instruction: Mapped[str] = mapped_column(Text, nullable=False)
    # 失败时的用户可读原因
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # LangGraph thread id（版本链=同 thread 检查点历史）
    thread_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    # 执行统计（工具调用数、沙箱执行数等，见 usage-tracking）
    stats: Mapped[dict | None] = mapped_column(JSON, nullable=True)
