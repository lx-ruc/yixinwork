"""会话 CRUD 与模式切换。"""

from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import CurrentUserId, DbSession
from app.models import DEFAULT_TITLE, ChatSession, Message
from app.schemas.chat import MessageOut
from app.schemas.session import SessionCreate, SessionModeUpdate, SessionOut
from app.services.session_service import get_owned_session

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


@router.post("", response_model=SessionOut)
def create_session(
    payload: SessionCreate, user: CurrentUserId, db: DbSession
) -> ChatSession:
    session = ChatSession(
        user_id=user, title=payload.title.strip() or DEFAULT_TITLE, mode=payload.mode
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


@router.get("", response_model=list[SessionOut])
def list_sessions(user: CurrentUserId, db: DbSession) -> list[ChatSession]:
    stmt = (
        select(ChatSession)
        .where(ChatSession.user_id == user)
        .order_by(ChatSession.updated_at.desc())
    )
    return list(db.scalars(stmt).all())


@router.get("/{session_id}", response_model=SessionOut)
def get_session(session_id: str, user: CurrentUserId, db: DbSession) -> ChatSession:
    return get_owned_session(db, user, session_id)


@router.patch("/{session_id}", response_model=SessionOut)
def update_session(
    session_id: str,
    payload: SessionModeUpdate,
    user: CurrentUserId,
    db: DbSession,
) -> ChatSession:
    session = get_owned_session(db, user, session_id)
    session.mode = payload.mode
    if payload.title is not None and payload.title.strip():
        session.title = payload.title.strip()
    db.commit()
    db.refresh(session)
    return session


@router.get("/{session_id}/messages", response_model=list[MessageOut])
def list_messages(
    session_id: str, user: CurrentUserId, db: DbSession
) -> list[Message]:
    get_owned_session(db, user, session_id)
    stmt = (
        select(Message)
        .where(Message.session_id == session_id, Message.user_id == user)
        .order_by(Message.created_at.asc(), Message.id.asc())
    )
    return list(db.scalars(stmt).all())
