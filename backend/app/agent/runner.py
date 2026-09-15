"""任务执行器：驱动 LangGraph 图 → SSE 事件流 + 任务状态机持久化。

事件类型（SSE data）：
  task_started / agent_message / tool_call / tool_result /
  steering_injected / preview_ready / task_completed / task_failed
"""

import asyncio
import logging
from typing import Any, AsyncIterator

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.types import Command
from sqlalchemy.orm import sessionmaker

from app.agent.graph import STEERING_PREFIX, build_agent_graph
from app.models import (
    TASK_DELIVERED,
    TASK_FAILED,
    TASK_PREVIEW_READY,
    TASK_RUNNING,
    Task,
)
from app.storage import get_storage
from app.tools.base import ToolRegistry
from app.tools.context import ToolContext, set_tool_context

logger = logging.getLogger(__name__)


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
        self._graph = build_agent_graph(
            llm=llm,
            registry=registry,
            inbox=self.inbox,
            checkpointer=checkpointer,
        )
        self._db_factory = db_factory
        self._session_id = session_id
        self._user_id = user_id
        # 产物工具落盘上下文（版本号跨 start/resume 连续 → v1/v2/… 版本链）
        self._tool_ctx = ToolContext(
            user_id=user_id, task_id=task_id, storage=get_storage()
        )

    def steer(self, content: str) -> None:
        """执行中插话入队（tools 节点循环间隙取出注入）。"""
        self.inbox.put_nowait(content)

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
        await self._set_status(TASK_RUNNING)
        yield {"type": "task_started", "task_id": self.task_id}
        try:
            async for update in self._graph.astream(
                graph_input, self._config, stream_mode="updates"
            ):
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
            await self._set_status(TASK_DELIVERED)
            await self._persist_milestone("任务已交付 ✅", kind="delivered")
            yield {"type": "task_completed", "task_id": self.task_id, "status": TASK_DELIVERED}
        except Exception as exc:  # noqa: BLE001 统一转失败事件，不让 SSE 半途崩掉
            logger.exception("task %s failed", self.task_id)
            await self._set_status(TASK_FAILED, error=str(exc))
            await self._persist_milestone(f"任务失败: {exc}", kind="failed")
            yield {"type": "task_failed", "task_id": self.task_id, "detail": str(exc)}
        finally:
            runner_registry.remove(self.task_id)  # 终态/挂起均移除；反馈时按需重建

    def _translate(self, update: dict) -> list[dict]:
        """LangGraph updates → 前端事件。"""
        events: list[dict] = []
        for node, payload in (update or {}).items():
            if node == "__metadata__" or not isinstance(payload, dict):
                continue
            for msg in payload.get("messages", []):
                if isinstance(msg, AIMessage):
                    for tc in msg.tool_calls or []:
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
