"""聊天消息 pydantic 模型。"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class AttachmentRef(BaseModel):
    """消息引用的暂存附件（上传接口返回的 id）。"""

    id: str = Field(min_length=8, max_length=64)


class MessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=8000)
    attachments: list[AttachmentRef] = Field(default_factory=list, max_length=5)


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    role: str
    content: str
    extra: dict | None = None
    created_at: datetime | None = None
