"""消息端点：POST 即 SSE 流式直答（普通对话模式）。"""

import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.api.deps import CurrentUserId, DbSession, LlmClient, SessionFactory
from app.schemas.chat import MessageCreate
from app.services.chat_service import stream_direct_answer
from app.services.session_service import get_owned_session

router = APIRouter(prefix="/api/sessions/{session_id}/messages", tags=["chat"])


@router.post("")
def send_message(
    session_id: str,
    payload: MessageCreate,
    user: CurrentUserId,
    db: DbSession,
    llm: LlmClient,
    db_factory: SessionFactory,
) -> StreamingResponse:
    session = get_owned_session(db, user, session_id)

    def event_stream():
        for event in stream_direct_answer(
            session=session,
            user_id=user,
            content=payload.content,
            llm=llm,
            db_factory=db_factory,
        ):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
