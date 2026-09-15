"""用量记录：每次 LLM 调用与任务执行统计落 usage_events 流水（只记不扣）。

写入失败绝不影响主流程——用量是旁路观测，记不上只告警。
"""

import logging
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.models import (
    TASK_DELIVERED,
    USAGE_LLM_CALL,
    USAGE_TASK_STATS,
    Task,
    UsageEvent,
)

logger = logging.getLogger(__name__)


def record_llm_call(
    db_factory: sessionmaker,
    *,
    user_id: str,
    session_id: str | None = None,
    task_id: str | None = None,
    model: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    duration_ms: int | None = None,
    detail: dict | None = None,
) -> None:
    """记一条 llm_call 用量（直答与 Agent 循环共用）。"""
    _safe_write(
        db_factory,
        UsageEvent(
            user_id=user_id,
            session_id=session_id,
            task_id=task_id,
            kind=USAGE_LLM_CALL,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            duration_ms=duration_ms,
            detail=detail,
        ),
    )


def record_task_stats(
    db_factory: sessionmaker,
    *,
    user_id: str,
    session_id: str,
    task_id: str,
    duration_ms: int | None,
    detail: dict,
) -> None:
    """任务到达终态（交付/失败）时记一条 task_stats 汇总事件。"""
    _safe_write(
        db_factory,
        UsageEvent(
            user_id=user_id,
            session_id=session_id,
            task_id=task_id,
            kind=USAGE_TASK_STATS,
            duration_ms=duration_ms,
            detail=detail,
        ),
    )


def _safe_write(db_factory: sessionmaker, event: UsageEvent) -> None:
    try:
        with db_factory() as db:
            db.add(event)
            db.commit()
    except Exception:  # noqa: BLE001 用量旁路：写失败不抛出
        logger.warning("用量事件写入失败 kind=%s", event.kind, exc_info=True)


def merge_task_stats(db_factory: sessionmaker, task_id: str, run_delta: dict) -> dict:
    """把本轮执行的增量统计累加进 Task.stats（JSON 列整体替换），返回合并结果。

    runner 在预览反馈续跑时会重建，计数器归零；以库中 stats 为准累加才能跨轮连续。
    """
    with db_factory() as db:
        task = db.get(Task, task_id)
        if task is None:
            return {}
        current = dict(task.stats or {})
        merged = {**current}
        for key, value in run_delta.items():
            merged[key] = (current.get(key) or 0) + (value or 0)
        task.stats = merged
        db.commit()
        return merged


def summarize_usage(
    db: Session, *, user_id: str, since: datetime, until: datetime
) -> dict:
    """按用户+时间范围汇总：LLM 调用/tokens、交付任务数、任务活跃时长、分模型明细。"""
    llm_filter = (
        UsageEvent.user_id == user_id,
        UsageEvent.kind == USAGE_LLM_CALL,
        UsageEvent.created_at >= since,
        UsageEvent.created_at <= until,
    )
    calls, in_tok, out_tok = db.execute(
        select(
            func.count(UsageEvent.id),
            func.coalesce(func.sum(UsageEvent.input_tokens), 0),
            func.coalesce(func.sum(UsageEvent.output_tokens), 0),
        ).where(*llm_filter)
    ).one()

    by_model = [
        {
            "model": model or "unknown",
            "calls": n,
            "input_tokens": int(i or 0),
            "output_tokens": int(o or 0),
        }
        for model, n, i, o in db.execute(
            select(
                UsageEvent.model,
                func.count(UsageEvent.id),
                func.coalesce(func.sum(UsageEvent.input_tokens), 0),
                func.coalesce(func.sum(UsageEvent.output_tokens), 0),
            )
            .where(*llm_filter)
            .group_by(UsageEvent.model)
        ).all()
    ]
    by_model.sort(key=lambda m: -m["calls"])

    active_ms = db.execute(
        select(func.coalesce(func.sum(UsageEvent.duration_ms), 0)).where(
            UsageEvent.user_id == user_id,
            UsageEvent.kind == USAGE_TASK_STATS,
            UsageEvent.created_at >= since,
            UsageEvent.created_at <= until,
        )
    ).scalar() or 0
    delivered = db.execute(
        select(func.count(Task.id)).where(
            Task.user_id == user_id,
            Task.status == TASK_DELIVERED,
            Task.created_at >= since,
            Task.created_at <= until,
        )
    ).scalar() or 0

    return {
        "user_id": user_id,
        "since": since.isoformat(),
        "until": until.isoformat(),
        "llm_calls": int(calls or 0),
        "input_tokens": int(in_tok or 0),
        "output_tokens": int(out_tok or 0),
        "delivered_tasks": int(delivered),
        "task_active_ms": int(active_ms),
        "by_model": by_model,
    }
