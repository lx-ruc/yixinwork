"""任务端点：会话任务列表 + 预览反馈（满意交付 / 修改续跑）。"""

import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import Literal

from app.api.deps import AgentModel, Checkpointer, CurrentUserId, DbSession, SessionFactory
from app.services.work_service import get_owned_task, list_tasks, stream_task_feedback, task_dict

router = APIRouter(prefix="/api", tags=["tasks"])


@router.get("/sessions/{session_id}/tasks")
def get_session_tasks(
    session_id: str, user: CurrentUserId, db: DbSession
) -> list[dict]:
    return list_tasks(db, session_id, user)


class TaskFeedback(BaseModel):
    action: Literal["approve", "revise"]
    instruction: str | None = Field(default=None, max_length=8000)


@router.post("/tasks/{task_id}/feedback")
def task_feedback(
    task_id: str,
    payload: TaskFeedback,
    user: CurrentUserId,
    db: DbSession,
    llm: AgentModel,
    checkpointer: Checkpointer,
    db_factory: SessionFactory,
) -> StreamingResponse:
    task = get_owned_task(db, user, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.status != "preview_ready":
        raise HTTPException(status_code=409, detail="任务不在预览就绪状态")

    async def event_stream():
        async for event in stream_task_feedback(
            task=task,
            user_id=user,
            action=payload.action,
            instruction=payload.instruction,
            llm=llm,
            checkpointer=checkpointer,
            db_factory=db_factory,
        ):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
