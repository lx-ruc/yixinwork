"""任务与路由确认 pydantic 模型。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class RouteConfirm(BaseModel):
    """确认卡片动作：confirm=进入工作模式；decline=原消息走直答。"""

    message_id: str = Field(min_length=1)
    action: Literal["confirm", "decline"]


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: str
    instruction: str
    error: str | None = None
    created_at: datetime | None = None
