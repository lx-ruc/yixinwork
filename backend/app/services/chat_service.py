"""普通对话直答与智能路由：装配历史 → 分类 → 直答/确认卡片 → 事件流 + 持久化。

事件为 dict：{"type": "user_message"|"delta"|"route_card"|"done"|"error", ...}
"""

from collections.abc import Iterator
from datetime import datetime, timezone
import time

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.llm.glm import ChatChunk, LLMError
from app.models import (
    DEFAULT_TITLE,
    ChatSession,
    Message,
    ROLE_ASSISTANT,
    ROLE_USER,
)
from app.services.routing import RouteDecision, get_classifier
from app.services.usage_service import record_llm_call

HISTORY_WINDOW = 20  # 送入 LLM 的最近消息条数

AUTO_TITLE_MAX = 18  # 自动标题截断长度（侧栏单行可读）


def auto_title(content: str) -> str:
    """按首条用户消息生成会话标题：压空白 + 截断，不用 LLM（零成本、即时）。"""
    text = " ".join(content.split())
    if len(text) <= AUTO_TITLE_MAX:
        return text or DEFAULT_TITLE
    return text[:AUTO_TITLE_MAX] + "…"

SYSTEM_PROMPT = (
    "你是亿心智能体助手，回答简洁、准确、友好。"
    "当用户的请求看起来是一项具体工作（如制作文档/表格/PPT/海报、数据处理）时，"
    "提示用户可以切换到工作模式让智能体代为完成。"
    "思考过程与回复都使用中文。"
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
        user_msg = persist_message(db, session, user_id, ROLE_USER, content)
        yield {"type": "user_message", "message": message_dict(user_msg)}
        yield from _answer_stream(
            db=db,
            session=session,
            user_id=user_id,
            llm=llm,
            messages=messages,
            db_factory=db_factory,
        )


def stream_route_gate(
    *,
    session: ChatSession,
    user_id: str,
    content: str,
    llm,
    db_factory: sessionmaker,
) -> Iterator[dict]:
    """普通对话模式入口：先分类，任务型弹确认卡片，闲聊型直答。"""
    decision = get_classifier().classify(content)
    if not decision.is_task:
        yield from stream_direct_answer(
            session=session, user_id=user_id, content=content, llm=llm,
            db_factory=db_factory,
        )
        return

    with db_factory() as db:
        user_msg = persist_message(
            db, session, user_id, ROLE_USER, content, extra=_route_extra(decision)
        )
        yield {"type": "user_message", "message": message_dict(user_msg)}
        yield {
            "type": "route_card",
            "message": message_dict(user_msg),
            "reason": decision.reason,
        }
        yield {"type": "done", "message": None, "usage": None}


def stream_declined_answer(
    *,
    session: ChatSession,
    user_id: str,
    message: Message,
    llm,
    db_factory: sessionmaker,
) -> Iterator[dict]:
    """拒绝卡片：原消息已在历史中，按历史直答（不重复落用户消息）。"""
    with db_factory() as db:
        messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
        for m in get_history(db, session.id, user_id):
            if m.role in ("user", "assistant"):
                messages.append({"role": m.role, "content": m.content})
        yield from _answer_stream(
            db=db,
            session=session,
            user_id=user_id,
            llm=llm,
            messages=messages,
            db_factory=db_factory,
        )


def _answer_stream(
    *,
    db: Session,
    session: ChatSession,
    user_id: str,
    llm,
    messages: list[dict],
    db_factory: sessionmaker,
) -> Iterator[dict]:
    """LLM 流式调用 + 助手消息持久化 + llm_call 用量埋点（user_message 由调用方负责）。

    思考分片（reasoning）先于正文下发 reasoning_delta；全文随助手消息
    存入 extra.reasoning（历史回放时前端可折叠展示）。
    """
    accumulated: list[str] = []
    reasoning_acc: list[str] = []
    usage: dict | None = None
    started = time.monotonic()
    try:
        chunk: ChatChunk
        for chunk in llm.stream_chat(messages):
            if chunk.reasoning:
                reasoning_acc.append(chunk.reasoning)
                yield {"type": "reasoning_delta", "content": chunk.reasoning}
            if chunk.delta:
                accumulated.append(chunk.delta)
                yield {"type": "delta", "content": chunk.delta}
            if chunk.usage:
                usage = chunk.usage
    except LLMError as exc:
        record_llm_call(
            db_factory,
            user_id=user_id,
            session_id=session.id,
            model=getattr(llm, "model", None),
            duration_ms=int((time.monotonic() - started) * 1000),
            detail={"error": str(exc)},
        )
        yield {"type": "error", "detail": str(exc)}
        return

    record_llm_call(
        db_factory,
        user_id=user_id,
        session_id=session.id,
        model=getattr(llm, "model", None),
        input_tokens=(usage or {}).get("input_tokens"),
        output_tokens=(usage or {}).get("output_tokens"),
        duration_ms=int((time.monotonic() - started) * 1000),
    )
    full = "".join(accumulated)
    extra = {"reasoning": "".join(reasoning_acc)} if reasoning_acc else None
    assistant_msg = persist_message(db, session, user_id, ROLE_ASSISTANT, full, extra=extra)
    yield {
        "type": "done",
        "message": message_dict(assistant_msg),
        "usage": usage,
    }


def _route_extra(decision: RouteDecision, status: str = "pending") -> dict:
    return {
        "route": {
            "kind": decision.kind,
            "confidence": decision.confidence,
            "reason": decision.reason,
            "status": status,
        }
    }


def persist_message(
    db: Session,
    session: ChatSession,
    user_id: str,
    role: str,
    content: str,
    extra: dict | None = None,
) -> Message:
    # 会话仍持占位标题时，首条用户消息按内容改写（与消息同事务提交）
    if role == ROLE_USER and session.title == DEFAULT_TITLE:
        session.title = auto_title(content)
    msg = Message(
        session_id=session.id,
        user_id=user_id,
        role=role,
        content=content,
        extra=extra,
        created_at=datetime.now(timezone.utc),
    )
    db.add(msg)
    db.commit()
    return msg


def update_route_status(msg: Message, status: str) -> None:
    """更新确认卡片的处理状态（不可变更新 extra 后整体替换）。"""
    route = dict(msg.extra or {}).get("route", {})
    msg.extra = {**(msg.extra or {}), "route": {**route, "status": status}}


def get_owned_message(db: Session, user_id: str, session_id: str, message_id: str) -> Message | None:
    stmt = select(Message).where(
        Message.id == message_id,
        Message.session_id == session_id,
        Message.user_id == user_id,
    )
    return db.scalars(stmt).first()


def message_dict(m: Message) -> dict:
    return {
        "id": m.id,
        "role": m.role,
        "content": m.content,
        "extra": m.extra,
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }
