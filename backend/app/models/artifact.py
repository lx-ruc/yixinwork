"""产物与版本表：版本链 v1→v2→…，中间格式存储、下载时转最终格式。"""

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import TimestampMixin, UUIDMixin

# 产物类型（预览策略 C，见 design.md 决策 6）
ARTIFACT_DOCUMENT = "document"
ARTIFACT_POSTER = "poster"
ARTIFACT_TABLE = "table"
ARTIFACT_SLIDES = "slides"
ARTIFACT_DATA = "data"
ARTIFACT_KINDS = (
    ARTIFACT_DOCUMENT,
    ARTIFACT_POSTER,
    ARTIFACT_TABLE,
    ARTIFACT_SLIDES,
    ARTIFACT_DATA,
)

# 中间格式
FMT_MARKDOWN = "markdown"
FMT_HTML = "html"
FMT_HTML_TABLE = "html_table"
FMT_HTML_SLIDES = "html_slides"
INTERMEDIATE_FORMATS = (FMT_MARKDOWN, FMT_HTML, FMT_HTML_TABLE, FMT_HTML_SLIDES)


class Artifact(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "artifacts"

    user_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    task_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tasks.id"), index=True, nullable=False
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    title: Mapped[str] = mapped_column(String(128), nullable=False, default="")


class ArtifactVersion(UUIDMixin, Base):
    __tablename__ = "artifact_versions"

    artifact_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("artifacts.id"), index=True, nullable=False
    )
    user_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    intermediate_format: Mapped[str] = mapped_column(String(16), nullable=False)
    # StorageService 中的 key：{user_id}/{task_id}/v{n}/...
    file_key: Mapped[str] = mapped_column(String(512), nullable=False)
    # 预览辅助数据（如表格结构化数据）
    preview_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # 满意确认后转换出的最终格式文件与格式名（docx/xlsx/png/pdf…）
    final_file_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    final_format: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime, server_default=func.now()
    )
