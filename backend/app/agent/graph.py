"""Agent 执行图：agent（LLM+工具调用）⇄ tools（执行+插话注入）→ preview（interrupt）。

形态与验证结论见 design.md「Spike 结论」。
"""

import asyncio
import operator
from typing import Annotated, Any, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from app.tools.base import ToolError, ToolRegistry

MAX_ITERATIONS = 12  # 工具循环轮数上限（防死循环）
STEERING_PREFIX = "[用户补充指令] "
REVISION_PREFIX = "[修改要求] "


class AgentState(TypedDict):
    messages: Annotated[list, _concat]
    iterations: Annotated[int, operator.add]


def _concat(current: list, update: list) -> list:
    return [*current, *update]


def build_agent_graph(*, llm, registry: ToolRegistry, inbox: asyncio.Queue, checkpointer):
    """llm: 已 bind_tools 的 chat model；inbox: 执行中插话队列（runner 持有）。"""

    async def agent_node(state: AgentState) -> dict:
        ai = await llm.ainvoke(state["messages"])
        return {"messages": [ai], "iterations": 1}

    async def tools_node(state: AgentState) -> dict:
        last = state["messages"][-1]
        out: list[Any] = []
        for tc in last.tool_calls:
            try:
                result = await registry.execute(tc["name"], dict(tc["args"]))
            except ToolError as exc:
                result = f"工具执行失败: {exc}"
            out.append(
                ToolMessage(content=result, name=tc["name"], tool_call_id=tc["id"])
            )
        # 循环间隙注入：工具执行完 → 下一轮 LLM 前
        while not inbox.empty():
            text = inbox.get_nowait()
            out.append(HumanMessage(content=f"{STEERING_PREFIX}{text}"))
        return {"messages": out}

    def after_agent(state: AgentState) -> str:
        last = state["messages"][-1]
        has_calls = bool(getattr(last, "tool_calls", None))
        if has_calls and state["iterations"] < MAX_ITERATIONS:
            return "tools"
        return "preview"

    async def preview_node(state: AgentState) -> dict:
        draft = state["messages"][-1].content
        # interrupt 前不得有副作用（恢复时节点从头重执行）
        feedback = interrupt({"preview": draft})
        action = feedback.get("action")
        if action == "approve":
            return {"messages": [AIMessage(content="用户已确认，交付。")]}
        return {
            "messages": [HumanMessage(content=f"{REVISION_PREFIX}{feedback.get('instruction', '')}")]
        }

    def after_preview(state: AgentState) -> str:
        last = state["messages"][-1]
        if isinstance(last, AIMessage):
            return END
        return "agent"

    g = StateGraph(AgentState)
    g.add_node("agent", agent_node)
    g.add_node("tools", tools_node)
    g.add_node("preview", preview_node)
    g.add_edge(START, "agent")
    g.add_conditional_edges("agent", after_agent, ["tools", "preview"])
    g.add_edge("tools", "agent")
    g.add_conditional_edges("preview", after_preview, [END, "agent"])
    return g.compile(checkpointer=checkpointer)
