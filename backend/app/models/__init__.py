"""聚合全部模型：alembic autogenerate 依赖此处的完整元数据。"""

from app.db import Base
from app.models.artifact import (
    ARTIFACT_DATA,
    ARTIFACT_DOCUMENT,
    ARTIFACT_POSTER,
    ARTIFACT_SLIDES,
    ARTIFACT_TABLE,
    FMT_HTML,
    FMT_HTML_SLIDES,
    FMT_HTML_TABLE,
    FMT_MARKDOWN,
    Artifact,
    ArtifactVersion,
)
from app.models.chat import (
    MODE_CHAT,
    MODE_WORK,
    ROLE_ASSISTANT,
    ROLE_SYSTEM,
    ROLE_USER,
    SESSION_MODES,
    ChatSession,
    Message,
)
from app.models.task import (
    TASK_DELIVERED,
    TASK_FAILED,
    TASK_PENDING,
    TASK_PREVIEW_READY,
    TASK_RUNNING,
    TASK_STATUSES,
    Task,
)
from app.models.usage import USAGE_LLM_CALL, USAGE_TASK_STATS, UsageEvent

__all__ = [
    "Base",
    "ChatSession",
    "Message",
    "Task",
    "Artifact",
    "ArtifactVersion",
    "UsageEvent",
    "MODE_CHAT",
    "MODE_WORK",
    "SESSION_MODES",
    "ROLE_USER",
    "ROLE_ASSISTANT",
    "ROLE_SYSTEM",
    "TASK_PENDING",
    "TASK_RUNNING",
    "TASK_PREVIEW_READY",
    "TASK_DELIVERED",
    "TASK_FAILED",
    "TASK_STATUSES",
    "ARTIFACT_DOCUMENT",
    "ARTIFACT_POSTER",
    "ARTIFACT_TABLE",
    "ARTIFACT_SLIDES",
    "ARTIFACT_DATA",
    "FMT_MARKDOWN",
    "FMT_HTML",
    "FMT_HTML_TABLE",
    "FMT_HTML_SLIDES",
    "USAGE_LLM_CALL",
    "USAGE_TASK_STATS",
]
