"""G9 用量记录测试：LLM 埋点（直答/Agent）、任务统计、内部汇总接口。"""

import json
from datetime import datetime, timedelta, timezone

from langchain_core.messages import AIMessage
from sqlalchemy import select

from app.api.deps import get_agent_model, get_llm
from app.config import get_settings
from app.main import app
from app.models import USAGE_LLM_CALL, USAGE_TASK_STATS, Task, UsageEvent
from tests.conftest import FakeAgentModel, FakeLLM

HEADERS = {"X-User-Id": "usage-user"}


def _parse_sse(text: str) -> list[dict]:
    return [
        json.loads(line[len("data: "):])
        for line in text.splitlines()
        if line.startswith("data: ")
    ]


def _events(db, kind: str) -> list[UsageEvent]:
    return list(db.execute(select(UsageEvent).where(UsageEvent.kind == kind)).scalars())


def _naive_utc_now() -> datetime:
    """与库中 created_at（无时区）对齐的当前时间。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def test_direct_answer_records_llm_call(app_client, db_sessionmaker):
    """直答：tokens/耗时/模型落 llm_call 流水，会话归属正确。"""
    app.dependency_overrides[get_llm] = lambda: FakeLLM(["你好", "呀"])
    sid = (await app_client.post("/api/sessions", json={}, headers=HEADERS)).json()["id"]

    resp = await app_client.post(
        f"/api/sessions/{sid}/messages", json={"content": "嗨"}, headers=HEADERS
    )
    assert resp.status_code == 200

    with db_sessionmaker() as db:
        calls = _events(db, USAGE_LLM_CALL)
        assert len(calls) == 1
        call = calls[0]
        assert call.user_id == "usage-user"
        assert call.session_id == sid
        assert call.task_id is None
        assert call.input_tokens == 10 and call.output_tokens == 2
        assert call.duration_ms is not None and call.duration_ms >= 0


async def test_agent_task_records_usage_and_stats(app_client, db_sessionmaker):
    """Agent：每轮 LLM 记流水（含 tokens）；Task.stats 累计工具数；终态落 task_stats。"""
    app.dependency_overrides[get_agent_model] = lambda: FakeAgentModel(
        messages=iter(
            [
                AIMessage(
                    content="",
                    usage_metadata={
                        "input_tokens": 5,
                        "output_tokens": 7,
                        "total_tokens": 12,
                    },
                    tool_calls=[
                        {
                            "name": "save_document",
                            "args": {"title": "用量说明", "content_md": "内容"},
                            "id": "c1",
                        }
                    ],
                ),
                AIMessage(content="完成"),
            ]
        )
    )
    sid = (await app_client.post("/api/sessions", json={}, headers=HEADERS)).json()["id"]
    await app_client.patch(f"/api/sessions/{sid}", json={"mode": "work"}, headers=HEADERS)

    resp = await app_client.post(
        f"/api/sessions/{sid}/messages",
        json={"content": "写一份用量说明"},
        headers=HEADERS,
    )
    task_id = next(e for e in _parse_sse(resp.text) if e["type"] == "task_created")["task"]["id"]

    with db_sessionmaker() as db:
        # 首轮挂起（预览就绪）：LLM 两轮已各记一条 llm_call，tokens 逐条可见
        calls = _events(db, USAGE_LLM_CALL)
        assert len(calls) == 2
        assert {c.task_id for c in calls} == {task_id}
        assert calls[0].input_tokens == 5 and calls[0].output_tokens == 7

    approve = await app_client.post(
        f"/api/tasks/{task_id}/feedback", json={"action": "approve"}, headers=HEADERS
    )
    assert _parse_sse(approve.text)[-1]["type"] == "task_completed"

    with db_sessionmaker() as db:
        task = db.get(Task, task_id)
        assert task.stats["tool_calls"] == 1
        assert task.stats["sandbox_runs"] == 0
        assert task.stats["llm_calls"] == 2
        assert task.stats["runs"] == 2  # 初稿 run + 交付 run
        assert task.stats["active_ms"] >= 0

        stats_events = _events(db, USAGE_TASK_STATS)
        assert len(stats_events) == 1  # 终态才记，交付一次
        ev = stats_events[0]
        assert ev.duration_ms == task.stats["active_ms"]
        assert ev.detail["status"] == "delivered"
        assert ev.detail["tool_calls"] == 1


async def test_summary_endpoint_auth_and_range(
    app_client, db_sessionmaker, monkeypatch
):
    """内部汇总接口：令牌校验（未配/错 token 403）+ 时间范围过滤。"""
    sid = (await app_client.post("/api/sessions", json={}, headers=HEADERS)).json()["id"]
    app.dependency_overrides[get_llm] = lambda: FakeLLM(["好"])
    await app_client.post(
        f"/api/sessions/{sid}/messages", json={"content": "嗨"}, headers=HEADERS
    )

    now = _naive_utc_now()
    # 事件在 now 之前落库：since 需留余量才能覆盖
    q = (
        f"?user_id=usage-user&since={(now - timedelta(minutes=1)).isoformat()}"
        f"&until={(now + timedelta(hours=1)).isoformat()}"
    )

    # 未配置令牌 → 403
    assert (await app_client.get(f"/api/internal/usage/summary{q}")).status_code == 403

    monkeypatch.setenv("INTERNAL_API_TOKEN", "secret-token")
    get_settings.cache_clear()
    try:
        bad = await app_client.get(
            f"/api/internal/usage/summary{q}", headers={"X-Internal-Token": "wrong"}
        )
        assert bad.status_code == 403

        ok = await app_client.get(
            f"/api/internal/usage/summary{q}", headers={"X-Internal-Token": "secret-token"}
        )
        assert ok.status_code == 200
        data = ok.json()
        assert data["llm_calls"] == 1
        assert data["input_tokens"] == 10
        assert data["delivered_tasks"] == 0

        # 时间范围不含任何事件 → 全零
        past = (
            f"?user_id=usage-user"
            f"&since={(now - timedelta(hours=3)).isoformat()}"
            f"&until={(now - timedelta(hours=2)).isoformat()}"
        )
        empty = await app_client.get(
            f"/api/internal/usage/summary{past}", headers={"X-Internal-Token": "secret-token"}
        )
        assert empty.status_code == 200
        assert empty.json()["llm_calls"] == 0

        # 范围非法 → 422
        backwards = (
            f"?user_id=usage-user"
            f"&since={(now + timedelta(hours=1)).isoformat()}"
            f"&until={now.isoformat()}"
        )
        assert (
            await app_client.get(
                f"/api/internal/usage/summary{backwards}",
                headers={"X-Internal-Token": "secret-token"},
            )
        ).status_code == 422
    finally:
        monkeypatch.delenv("INTERNAL_API_TOKEN", raising=False)
        get_settings.cache_clear()


async def test_usage_isolated_per_user(app_client, db_sessionmaker):
    """数据隔离：用量流水按用户归属，汇总只统计本人事件。"""
    app.dependency_overrides[get_llm] = lambda: FakeLLM(["好"])
    sid = (await app_client.post("/api/sessions", json={}, headers=HEADERS)).json()["id"]
    await app_client.post(
        f"/api/sessions/{sid}/messages", json={"content": "嗨"}, headers=HEADERS
    )

    from app.services.usage_service import summarize_usage

    now = _naive_utc_now()
    with db_sessionmaker() as db:
        mine = summarize_usage(
            db,
            user_id="usage-user",
            since=now - timedelta(hours=1),
            until=now + timedelta(hours=1),
        )
        other = summarize_usage(
            db,
            user_id="someone-else",
            since=now - timedelta(hours=1),
            until=now + timedelta(hours=1),
        )
    assert mine["llm_calls"] == 1
    assert other["llm_calls"] == 0
