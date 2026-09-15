"""工作模式入口：按当前任务状态分发。

- 无任务 / 终态任务 → 消息成为新任务指令，启动 Agent 执行流
- 执行中(running) → 消息为插话，入 runner 队列（循环间隙注入）
- 预览就绪(preview_ready) → 消息为修改指令，恢复 thread 续跑（版本链）

注意：跨 db 会话只传纯数据（id/status/thread_id），不传 ORM 实例
（生产 SessionLocal expire_on_commit=True，脱管实例访问属性会抛错）。
"""

import uuid
from collections.abc import AsyncIterator

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.agent.runner import TaskRunner, runner_registry
from app.models import (
    ChatSession,
    Message,
    ROLE_USER,
    TASK_DELIVERED,
    TASK_FAILED,
    TASK_PENDING,
    TASK_PREVIEW_READY,
    TASK_RUNNING,
    Task,
)
from app.services.chat_service import message_dict, persist_message
from app.tools import get_tool_registry

TERMINAL_STATUSES = (TASK_DELIVERED, TASK_FAILED)


def get_latest_task(db: Session, session_id: str, user_id: str) -> Task | None:
    stmt = (
        select(Task)
        .where(Task.session_id == session_id, Task.user_id == user_id)
        .order_by(Task.created_at.desc(), Task.id.desc())
        .limit(1)
    )
    return db.scalars(stmt).first()


def get_owned_task(db: Session, user_id: str, task_id: str) -> Task | None:
    stmt = select(Task).where(Task.id == task_id, Task.user_id == user_id)
    return db.scalars(stmt).first()


def task_dict(t: Task) -> dict:
    return {
        "id": t.id,
        "session_id": t.session_id,
        "status": t.status,
        "instruction": t.instruction,
        "error": t.error,
        "thread_id": t.thread_id,
        "created_at": t.created_at.isoformat() if t.created_at else None,
    }


def list_tasks(db: Session, session_id: str, user_id: str) -> list[dict]:
    stmt = (
        select(Task)
        .where(Task.session_id == session_id, Task.user_id == user_id)
        .order_by(Task.created_at.desc(), Task.id.desc())
    )
    return [task_dict(t) for t in db.scalars(stmt).all()]


def _make_runner(
    *,
    task_id: str,
    thread_id: str,
    session_id: str,
    user_id: str,
    llm,
    checkpointer,
    db_factory: sessionmaker,
) -> TaskRunner:
    runner = TaskRunner(
        task_id=task_id,
        thread_id=thread_id,
        session_id=session_id,
        user_id=user_id,
        llm=llm,
        registry=get_tool_registry(),
        checkpointer=checkpointer,
        db_factory=db_factory,
    )
    return runner_registry.add(runner)


async def stream_work_message(
    *,
    session: ChatSession,
    user_id: str,
    content: str,
    llm,
    checkpointer,
    db_factory: sessionmaker,
) -> AsyncIterator[dict]:
    """工作模式消息总入口（消息语义由当前任务状态决定）。"""
    session_id = session.id
    with db_factory() as db:
        latest = get_latest_task(db, session_id, user_id)
        latest_info = task_dict(latest) if latest else None
        user_msg = persist_message(db, session, user_id, ROLE_USER, content)
        yield {"type": "user_message", "message": message_dict(user_msg)}

    if latest_info is None or latest_info["status"] in TERMINAL_STATUSES:
        new_task = _create_task(db_factory, session_id, user_id, instruction=content)
        yield {"type": "task_created", "task": new_task}
        runner = _make_runner(
            task_id=new_task["id"],
            thread_id=new_task["thread_id"],
            session_id=session_id,
            user_id=user_id,
            llm=llm,
            checkpointer=checkpointer,
            db_factory=db_factory,
        )
        async for event in runner.start(content):
            yield event
        return

    if latest_info["status"] == TASK_RUNNING:
        runner = runner_registry.get(latest_info["id"])
        if runner is None:  # 进程内 runner 丢失（重启场景已由启动恢复标失败）
            yield {"type": "error", "detail": "任务执行器不可用，请稍后重试"}
            return
        runner.steer(content)
        yield {"type": "steering_queued", "task_id": latest_info["id"], "content": content}
        return

    if latest_info["status"] == TASK_PREVIEW_READY:
        runner = runner_registry.get(latest_info["id"]) or _make_runner(
            task_id=latest_info["id"],
            thread_id=latest_info["thread_id"],
            session_id=session_id,
            user_id=user_id,
            llm=llm,
            checkpointer=checkpointer,
            db_factory=db_factory,
        )
        yield {"type": "task_revising", "task_id": latest_info["id"]}
        async for event in runner.resume("revise", instruction=content):
            yield event
        return

    yield {"type": "error", "detail": f"任务状态异常: {latest_info['status']}"}


async def stream_confirmed_task(
    *,
    session: ChatSession,
    user_id: str,
    message: Message,
    llm,
    checkpointer,
    db_factory: sessionmaker,
) -> AsyncIterator[dict]:
    """确认卡片后携带原消息进入工作模式：原消息不重复落库，直接成为任务指令。"""
    new_task = _create_task(
        db_factory, session.id, user_id, instruction=message.content
    )
    yield {"type": "mode_switched", "mode": "work"}
    yield {"type": "task_created", "task": new_task}
    runner = _make_runner(
        task_id=new_task["id"],
        thread_id=new_task["thread_id"],
        session_id=session.id,
        user_id=user_id,
        llm=llm,
        checkpointer=checkpointer,
        db_factory=db_factory,
    )
    async for event in runner.start(message.content):
        yield event


async def stream_task_feedback(
    *,
    task: Task,
    user_id: str,
    action: str,
    instruction: str | None,
    llm,
    checkpointer,
    db_factory: sessionmaker,
) -> AsyncIterator[dict]:
    """预览反馈端点：approve=交付；revise=修改指令续跑（无则视为 approve）。"""
    task_info = task_dict(task)
    runner = runner_registry.get(task_info["id"]) or _make_runner(
        task_id=task_info["id"],
        thread_id=task_info["thread_id"],
        session_id=task_info["session_id"],
        user_id=user_id,
        llm=llm,
        checkpointer=checkpointer,
        db_factory=db_factory,
    )
    async for event in runner.resume(action, instruction=instruction):
        yield event


def _create_task(
    db_factory: sessionmaker, session_id: str, user_id: str, *, instruction: str
) -> dict:
    with db_factory() as db:
        task = Task(
            user_id=user_id,
            session_id=session_id,
            status=TASK_PENDING,
            instruction=instruction,
            thread_id=uuid.uuid4().hex,
        )
        db.add(task)
        db.commit()
        return task_dict(task)  # 会话关闭前取纯数据
