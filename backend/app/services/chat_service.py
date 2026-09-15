"""普通对话直答：装配历史 → LLM 流式 → 事件流 + 持久化。

事件为 dict：{"type": "user_message"|"delta"|"done"|"error", ...}
"""

from collections.abc import Iterator
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.llm.glm import ChatChunk, LLMError
from app.models import ChatSession, Message, ROLE_ASSISTANT, ROLE_USER

HISTORY_WINDOW = 20  # 送入 LLM 的最近消息条数

SYSTEM_PROMPT = (
    "你是亿心智能体助手，回答简洁、准确、友好。"
    "当用户的请求看起来是一项具体工作（如制作文档/表格/PPT/海报、数据处理）时，"
    "提示用户可以切换到工作模式让智能体代为完成。"
)

MsgFactory = sessionmaker


def get_history(db: Session, session_id: str, user_id: str) -> list[Message]:
    stmt = (
        select(Message)
        .where(Message.session_id == session_id, Message.user_id == user_id)
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(HISTORY_WINDOW)
    )
    return list(reversed(db.scalars(stmt).all()))


def build_llm_messages(history: list[Message], user_content: str) -> list[dict]:
    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
    for m in history:
        if m.role in ("user", "assistant"):
            messages.append({"role": m.role, "content": m.content})
    messages.append({"role": "user", "content": user_content})
    return messages


def stream_direct_answer(
    *,
    session: ChatSession,
    user_id: str,
    content: str,
    llm,
    db_factory: sessionmaker,
) -> Iterator[dict]:
    """流式直答主流程：独立数据库会话（SSE 生命周期长于请求依赖）。"""
    with db_factory() as db:
        # 先装配历史（不含本条），再落用户消息，顺序清晰
        messages = build_llm_messages(get_history(db, session.id, user_id), content)
        user_msg = _persist_message(db, session, user_id, ROLE_USER, content)
        yield {"type": "user_message", "message": _message_dict(user_msg)}

        accumulated: list[str] = []
        usage: dict | None = None
        try:
            chunk: ChatChunk
            for chunk in llm.stream_chat(messages):
                if chunk.delta:
                    accumulated.append(chunk.delta)
                    yield {"type": "delta", "content": chunk.delta}
                if chunk.usage:
                    usage = chunk.usage
        except LLMError as exc:
            yield {"type": "error", "detail": str(exc)}
            return

        full = "".join(accumulated)
        assistant_msg = _persist_message(db, session, user_id, ROLE_ASSISTANT, full)
        yield {
            "type": "done",
            "message": _message_dict(assistant_msg),
            "usage": usage,
        }


def _persist_message(
    db: Session, session: ChatSession, user_id: str, role: str, content: str
) -> Message:
    msg = Message(
        session_id=session.id,
        user_id=user_id,
        role=role,
        content=content,
        created_at=datetime.now(timezone.utc),
    )
    db.add(msg)
    db.commit()
    return msg


def _message_dict(m: Message) -> dict:
    return {
        "id": m.id,
        "role": m.role,
        "content": m.content,
        "extra": m.extra,
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }
