"""消息端点：POST 即 SSE 流。

- 普通对话模式：智能路由（任务型弹确认卡片，闲聊型直答）
- 工作模式：消息即任务指令，直达 Agent 流程（不做路由判断）
- route-confirm：确认卡片动作（confirm→工作模式；decline→原消息直答）
"""

import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.api.deps import CurrentUserId, DbSession, LlmClient, SessionFactory
from app.models import MODE_WORK
from app.schemas.chat import MessageCreate
from app.schemas.task import RouteConfirm
from app.services.chat_service import (
    get_owned_message,
    stream_declined_answer,
    stream_route_gate,
    update_route_status,
)
from app.services.session_service import get_owned_session
from app.services.work_service import stream_confirmed_task, stream_work_message

router = APIRouter(prefix="/api/sessions/{session_id}", tags=["chat"])

SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


def _sse(events) -> StreamingResponse:
    def event_stream():
        for event in events:
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(), media_type="text/event-stream", headers=SSE_HEADERS
    )


@router.post("/messages")
def send_message(
    session_id: str,
    payload: MessageCreate,
    user: CurrentUserId,
    db: DbSession,
    llm: LlmClient,
    db_factory: SessionFactory,
) -> StreamingResponse:
    session = get_owned_session(db, user, session_id)

    if session.mode == MODE_WORK:
        return _sse(
            stream_work_message(
                session=session,
                user_id=user,
                content=payload.content,
                db_factory=db_factory,
            )
        )
    return _sse(
        stream_route_gate(
            session=session,
            user_id=user,
            content=payload.content,
            llm=llm,
            db_factory=db_factory,
        )
    )


@router.post("/route-confirm")
def route_confirm(
    session_id: str,
    payload: RouteConfirm,
    user: CurrentUserId,
    db: DbSession,
    llm: LlmClient,
    db_factory: SessionFactory,
) -> StreamingResponse:
    session = get_owned_session(db, user, session_id)
    msg = get_owned_message(db, user, session_id, payload.message_id)
    if msg is None:
        raise HTTPException(status_code=404, detail="消息不存在")

    route = (msg.extra or {}).get("route")
    if not isinstance(route, dict) or route.get("status") != "pending":
        raise HTTPException(status_code=409, detail="该消息没有待处理的确认卡片")

    if payload.action == "confirm":
        session.mode = MODE_WORK
        update_route_status(msg, "confirmed")
        db.commit()
        return _sse(
            stream_confirmed_task(
                session=session, user_id=user, message=msg, db_factory=db_factory
            )
        )

    update_route_status(msg, "declined")
    db.commit()
    return _sse(
        stream_declined_answer(
            session=session, user_id=user, message=msg, llm=llm, db_factory=db_factory
        )
    )
