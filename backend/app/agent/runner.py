"""任务执行器：驱动 LangGraph 图 → SSE 事件流 + 任务状态机持久化。

事件类型（SSE data）：
  task_started / agent_message / tool_call / tool_result / reasoning_delta /
  steering_injected / preview_ready / task_completed / task_failed
"""

import asyncio
import logging
import time
from typing import Any, AsyncIterator

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.types import Command
from sqlalchemy.orm import sessionmaker

from app.agent.graph import STEERING_PREFIX, build_agent_graph
from app.skills import skills_hint
from app.models import (
    TASK_DELIVERED,
    TASK_FAILED,
    TASK_PENDING,
    TASK_PREVIEW_READY,
    TASK_RUNNING,
    Task,
)
from app.services.usage_service import (
    merge_task_stats,
    record_llm_call,
    record_task_stats,
)
from app.storage import get_storage
from app.tools.base import ToolRegistry
from app.tools.context import ToolContext, set_tool_context

logger = logging.getLogger(__name__)

SANDBOX_TOOL = "run_python_code"  # 沙箱执行次数按此工具名单独统计


def _zero_counts() -> dict[str, int]:
    """单轮执行（一次 _stream）的用量计数器清零。"""
    return {
        "llm_calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "tool_calls": 0,
        "sandbox_runs": 0,
    }


class TaskRunner:
    """一个任务一个 runner：inbox 收执行中插话，stream() 产出事件供 SSE 转发。"""

    def __init__(
        self,
        *,
        task_id: str,
        thread_id: str,
        session_id: str,
        user_id: str,
        llm,
        registry: ToolRegistry,
        checkpointer,
        db_factory: sessionmaker,
    ) -> None:
        self.task_id = task_id
        self.thread_id = thread_id
        self.inbox: asyncio.Queue[str] = asyncio.Queue()
        self._config = {"configurable": {"thread_id": thread_id}}
        self._run_counts = _zero_counts()  # 单轮执行用量（run 结束累进 Task.stats）
        self._graph = build_agent_graph(
            llm=llm,
            registry=registry,
            inbox=self.inbox,
            checkpointer=checkpointer,
            on_llm_usage=self._on_llm_usage,
            system_prompt_extra=skills_hint(),
        )
        self._db_factory = db_factory
        self._session_id = session_id
        self._user_id = user_id
        # 产物工具落盘上下文（版本号跨 start/resume 连续 → v1/v2/… 版本链）
        self._tool_ctx = ToolContext(
            user_id=user_id,
            task_id=task_id,
            storage=get_storage(),
            db_factory=db_factory,
        )
        self._seed_tool_version()

    def _seed_tool_version(self) -> None:
        """重建 runner（预览反馈续跑）时按库中版本链对齐存储版本计数器。

        preview_ready 后 runner 从注册表移除，反馈时重建；若计数器归零，
        续跑的保存会覆写 v1 目录而库里记为 v2，导致存储/库版本错位。
        """
        from sqlalchemy import func, select

        from app.models import Artifact, ArtifactVersion

        if self._db_factory is None:
            return
        with self._db_factory() as db:
            max_v = db.execute(
                select(func.max(ArtifactVersion.version))
                .join(Artifact, Artifact.id == ArtifactVersion.artifact_id)
                .where(Artifact.task_id == self.task_id)
            ).scalar_one_or_none()
        if max_v:
            self._tool_ctx.seed_version(int(max_v))

    def steer(self, content: str) -> None:
        """执行中插话入队（tools 节点循环间隙取出注入）。"""
        self.inbox.put_nowait(content)

    async def _on_llm_usage(self, ai, duration_ms: int) -> None:
        """每轮 LLM 调用后记 llm_call 流水；任何异常不得影响执行流。"""
        try:
            meta = getattr(ai, "usage_metadata", None) or {}
            in_tok = int(meta.get("input_tokens") or 0)
            out_tok = int(meta.get("output_tokens") or 0)
            model = (getattr(ai, "response_metadata", None) or {}).get("model_name")
            self._run_counts = {
                **self._run_counts,
                "llm_calls": self._run_counts["llm_calls"] + 1,
                "input_tokens": self._run_counts["input_tokens"] + in_tok,
                "output_tokens": self._run_counts["output_tokens"] + out_tok,
            }
            # 同步小写入（与 _set_status 等既有模式一致，单事件循环线程串行；
            # 不走 to_thread：避免与主线程在数据库连接上真并发）
            record_llm_call(
                self._db_factory,
                user_id=self._user_id,
                session_id=self._session_id,
                task_id=self.task_id,
                model=model,
                input_tokens=in_tok or None,
                output_tokens=out_tok or None,
                duration_ms=duration_ms,
            )
        except Exception:  # noqa: BLE001 埋点旁路
            logger.warning("llm 用量记录失败 task=%s", self.task_id, exc_info=True)

    def start(self, instruction: str) -> AsyncIterator[dict]:
        """首轮执行：用户指令进入图，流到 preview 中断或异常。"""
        return self._stream({"messages": [HumanMessage(content=instruction)], "iterations": 0})

    def resume(self, action: str, instruction: str | None = None) -> AsyncIterator[dict]:
        """预览反馈：approve=交付终止；revise=注入修改要求继续执行。"""
        payload = {"action": action}
        if instruction:
            payload["instruction"] = instruction
        return self._stream(Command(resume=payload))

    async def _stream(self, graph_input) -> AsyncIterator[dict]:
        set_tool_context(self._tool_ctx)  # 工具经 ContextVar 拿到 user/task/版本
        self._run_counts = _zero_counts()
        terminal: str | None = None
        started = time.monotonic()
        try:
            await self._set_status(TASK_RUNNING)
            yield {"type": "task_started", "task_id": self.task_id}
            # updates: 节点级事件；custom: agent 节点内实时推送的思考分片
            async for mode, update in self._graph.astream(
                graph_input, self._config, stream_mode=["updates", "custom"]
            ):
                if mode == "custom":
                    reasoning = (
                        update.get("reasoning") if isinstance(update, dict) else None
                    )
                    if reasoning:
                        yield {"type": "reasoning_delta", "content": reasoning}
                    continue
                for event in self._translate(update):
                    yield event
            snapshot = await self._graph.aget_state(self._config)
            if snapshot.next:  # preview 节点挂起等反馈
                preview = self._interrupt_payload(snapshot)
                await self._set_status(TASK_PREVIEW_READY)
                await self._persist_milestone(
                    str(preview.get("preview", "")), kind="preview"
                )
                yield {"type": "preview_ready", "task_id": self.task_id, "preview": preview}
                return
            terminal = TASK_DELIVERED
            await self._set_status(TASK_DELIVERED)
            await self._finalize_artifacts()
            await self._persist_milestone("任务已交付 ✅", kind="delivered")
            yield {"type": "task_completed", "task_id": self.task_id, "status": TASK_DELIVERED}
        except (asyncio.CancelledError, GeneratorExit):
            # 客户端断开 / 流被关闭：两者是 BaseException，except Exception 接不住；
            # 若不落终态，finally 已把 runner 移出注册表而库里任务永远停在
            # running —— 之后该会话每条消息都误报"任务执行器不可用"。
            self._mark_interrupted()
            raise
        except Exception as exc:  # noqa: BLE001 统一转失败事件，不让 SSE 半途崩掉
            logger.exception("task %s failed", self.task_id)
            terminal = TASK_FAILED
            await self._set_status(TASK_FAILED, error=str(exc))
            await self._persist_milestone(f"任务失败: {exc}", kind="failed")
            yield {"type": "task_failed", "task_id": self.task_id, "detail": str(exc)}
        finally:
            await self._finish_run_stats(
                terminal, int((time.monotonic() - started) * 1000)
            )
            runner_registry.remove(self.task_id)  # 终态/挂起均移除；反馈时按需重建

    def _mark_interrupted(self, detail: str = "连接中断，任务已停止；请重新发起") -> None:
        """流被取消时同步落终态（禁止 await，CancelledError/GeneratorExit 下要能安全跑完）。"""
        try:
            with self._db_factory() as db:
                task = db.get(Task, self.task_id)
                if task is None or task.status not in (TASK_PENDING, TASK_RUNNING):
                    return  # 已到终态/预览态，不覆盖
                task.status = TASK_FAILED
                task.error = detail
                db.commit()
        except Exception:  # noqa: BLE001 清理旁路，不影响异常传播
            logger.warning("标记中断任务失败 task=%s", self.task_id, exc_info=True)

    async def _finish_run_stats(self, terminal: str | None, elapsed_ms: int) -> None:
        """本轮统计累进 Task.stats；终态（交付/失败）再落一条 task_stats 用量事件。"""
        delta = {**self._run_counts, "active_ms": elapsed_ms, "runs": 1}

        def _sync() -> None:
            merged = merge_task_stats(self._db_factory, self.task_id, delta)
            if terminal and merged:
                record_task_stats(
                    self._db_factory,
                    user_id=self._user_id,
                    session_id=self._session_id,
                    task_id=self.task_id,
                    duration_ms=merged.get("active_ms"),
                    detail={
                        "status": terminal,
                        "llm_calls": merged.get("llm_calls", 0),
                        "tool_calls": merged.get("tool_calls", 0),
                        "sandbox_runs": merged.get("sandbox_runs", 0),
                    },
                )

        try:
            _sync()  # 同步小写入，与既有 async 内 DB 访问模式一致
        except Exception:  # noqa: BLE001 统计旁路
            logger.warning("任务统计记录失败 task=%s", self.task_id, exc_info=True)

    def _translate(self, update: dict) -> list[dict]:
        """LangGraph updates → 前端事件（顺带累计工具/沙箱执行计数）。"""
        events: list[dict] = []
        for node, payload in (update or {}).items():
            if node == "__metadata__" or not isinstance(payload, dict):
                continue
            for msg in payload.get("messages", []):
                if isinstance(msg, AIMessage):
                    for tc in msg.tool_calls or []:
                        self._bump_counts("tool_calls")
                        if tc["name"] == SANDBOX_TOOL:
                            self._bump_counts("sandbox_runs")
                        events.append(
                            {"type": "tool_call", "name": tc["name"], "args": tc["args"]}
                        )
                    if msg.content:
                        events.append(
                            {"type": "agent_message", "content": str(msg.content)}
                        )
                elif isinstance(msg, ToolMessage):
                    events.append(
                        {
                            "type": "tool_result",
                            "name": msg.name or "",
                            "content": str(msg.content)[:2000],
                        }
                    )
                elif isinstance(msg, HumanMessage) and str(msg.content).startswith(
                    STEERING_PREFIX
                ):
                    events.append(
                        {
                            "type": "steering_injected",
                            "content": str(msg.content)[len(STEERING_PREFIX):],
                        }
                    )
        return events

    def _bump_counts(self, key: str) -> None:
        """不可变自增单轮计数器（run 结束统一累进 Task.stats）。"""
        self._run_counts = {**self._run_counts, key: self._run_counts[key] + 1}

    @staticmethod
    def _interrupt_payload(snapshot) -> dict:
        tasks = snapshot.tasks.values() if isinstance(snapshot.tasks, dict) else snapshot.tasks
        for task in tasks or ():
            for intr in getattr(task, "interrupts", None) or ():
                if isinstance(intr.value, dict):
                    return intr.value
        return {}

    async def _set_status(self, status: str, *, error: str | None = None) -> None:
        with self._db_factory() as db:
            task = db.get(Task, self.task_id)
            if task is None:
                return
            task.status = status
            task.error = error
            db.commit()

    async def _persist_milestone(self, content: str, *, kind: str) -> None:
        """关键节点落为助手消息（会话历史回放可见；细粒度过程事件只在实时流）。"""
        from app.models import ChatSession
        from app.services.chat_service import persist_message

        with self._db_factory() as db:
            session = db.get(ChatSession, self._session_id)
            if session is None:
                return
            persist_message(
                db,
                session,
                self._user_id,
                "assistant",
                content,
                extra={"task_id": self.task_id, "kind": kind},
            )

    async def _finalize_artifacts(self) -> None:
        """满意交付：补齐各产物最新版本的最终下载文件（伴随文件缺失才现算）。"""
        from sqlalchemy import select

        from app.models import Artifact, ArtifactVersion
        from app.services.artifact_service import ensure_final

        def _sync() -> None:
            with self._db_factory() as db:
                rows = db.execute(
                    select(Artifact.kind, ArtifactVersion)
                    .join(ArtifactVersion, ArtifactVersion.artifact_id == Artifact.id)
                    .where(Artifact.task_id == self.task_id)
                    .order_by(ArtifactVersion.version.desc())
                ).all()
                seen: set[str] = set()
                for kind, ver in rows:
                    if ver.artifact_id in seen:  # 每个产物只处理最新版本
                        continue
                    seen.add(ver.artifact_id)
                    try:
                        ensure_final(db, ver, kind=kind)
                    except Exception:  # noqa: BLE001 转换失败不阻塞交付
                        logger.warning(
                            "产物最终格式转换失败 task=%s kind=%s", self.task_id, kind
                        )

        await asyncio.to_thread(_sync)


class RunnerRegistry:
    """活动 runner 注册表：task_id → TaskRunner（进程内）。"""

    def __init__(self) -> None:
        self._runners: dict[str, TaskRunner] = {}

    def add(self, runner: TaskRunner) -> TaskRunner:
        self._runners[runner.task_id] = runner
        return runner

    def get(self, task_id: str) -> TaskRunner | None:
        return self._runners.get(task_id)

    def remove(self, task_id: str) -> None:
        self._runners.pop(task_id, None)

    def active(self) -> dict[str, TaskRunner]:
        return dict(self._runners)


runner_registry = RunnerRegistry()


def recover_interrupted_tasks(db_factory: sessionmaker) -> int:
    """重启恢复：执行中任务随进程消失，标记失败（预览就绪任务经检查点仍可反馈续跑）。"""
    with db_factory() as db:
        running = db.query(Task).filter(Task.status == TASK_RUNNING).all()
        for task in running:
            task.status = TASK_FAILED
            task.error = "服务重启，任务中断；请重新发起"
        db.commit()
        return len(running)
