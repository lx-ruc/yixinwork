"""工作模式入口：消息即任务指令。

G4：创建任务（pending）并通知前端；G5 将在此接入 LangGraph 执行图，
把"任务创建"替换为真实的 Agent 执行事件流（工具调用/步骤/预览就绪）。
"""

from collections.abc import Iterator

from sqlalchemy.orm import Session, sessionmaker

from app.models import (
    ChatSession,
    Message,
    ROLE_USER,
    TASK_PENDING,
    Task,
)
from app.services.chat_service import message_dict, persist_message

MsgFactory = sessionmaker


def stream_work_message(
    *,
    session: ChatSession,
    user_id: str,
    content: str,
    db_factory: sessionmaker,
) -> Iterator[dict]:
    """工作模式下用户主动发消息：落消息 + 建任务（G5 起接入 Agent 执行）。"""
    with db_factory() as db:
        msg = _persist_user_message(db, session, user_id, content)
        yield {"type": "user_message", "message": message_dict(msg)}
        task = _create_task(db, session, user_id, instruction=content)
        yield {"type": "task_created", "task": _task_dict(task)}
        yield {"type": "done", "message": None, "usage": None}


def stream_confirmed_task(
    *,
    session: ChatSession,
    user_id: str,
    message: Message,
    db_factory: sessionmaker,
) -> Iterator[dict]:
    """确认卡片后携带原消息进入工作模式：原消息不重复落库，直接成为任务指令。"""
    with db_factory() as db:
        task = _create_task(db, session, user_id, instruction=message.content)
        yield {"type": "mode_switched", "mode": "work"}
        yield {"type": "task_created", "task": _task_dict(task)}
        yield {"type": "done", "message": None, "usage": None}


def _create_task(db: Session, session: ChatSession, user_id: str, *, instruction: str) -> Task:
    task = Task(
        user_id=user_id,
        session_id=session.id,
        status=TASK_PENDING,
        instruction=instruction,
    )
    db.add(task)
    db.commit()
    return task


def _persist_user_message(
    db: Session, session: ChatSession, user_id: str, content: str
) -> Message:
    return persist_message(db, session, user_id, ROLE_USER, content)


def _task_dict(t: Task) -> dict:
    return {
        "id": t.id,
        "status": t.status,
        "instruction": t.instruction,
        "error": t.error,
        "created_at": t.created_at.isoformat() if t.created_at else None,
    }


def _message_dict(m: Message) -> dict:
    return {
        "id": m.id,
        "role": m.role,
        "content": m.content,
        "extra": m.extra,
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }
