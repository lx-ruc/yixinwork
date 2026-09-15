"""会话相关 pydantic 模型。"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models import MODE_CHAT, SESSION_MODES


def validate_mode(mode: str) -> str:
    if mode not in SESSION_MODES:
        raise ValueError(f"mode 必须是 {'/'.join(SESSION_MODES)}")
    return mode


class SessionCreate(BaseModel):
    title: str = Field(default="新会话", max_length=128)
    mode: str = Field(default=MODE_CHAT)

    @field_validator("mode")
    @classmethod
    def _check_mode(cls, v: str) -> str:
        return validate_mode(v)


class SessionModeUpdate(BaseModel):
    mode: str
    title: str | None = Field(default=None, max_length=128)

    @field_validator("mode")
    @classmethod
    def _check_mode(cls, v: str) -> str:
        return validate_mode(v)


class SessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    mode: str
    created_at: datetime | None = None
    updated_at: datetime | None = None
