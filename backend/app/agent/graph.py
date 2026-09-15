"""Agent 执行图：agent（LLM+工具调用）⇄ tools（执行+插话注入）→ preview（interrupt）。

形态与验证结论见 design.md「Spike 结论」。
"""

import asyncio
import operator
from typing import Annotated, Any, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from app.tools.base import ToolError, ToolRegistry

MAX_ITERATIONS = 12  # 工具循环轮数上限（防死循环）
STEERING_PREFIX = "[用户补充指令] "
REVISION_PREFIX = "[修改要求] "

SYSTEM_PROMPT = """你是「亿心工作」工作模式的执行智能体，负责完成用户的交付类任务（文档/海报/表格/幻灯片等）。
执行要求：
1. 产出必须通过工具保存，不要只在回复文字里给内容：
   - 文档 → save_document；海报 → save_poster；表格 → save_table；幻灯片 → save_slides
   - 数据处理/计算 → run_python_code（沙箱内可用 numpy/pandas/openpyxl，需要保留的结果写 out/ 目录）
2. 内容质量优先：结构完整、信息具体，不写占位文字。
3. 收到以 [修改要求] 或 [用户补充指令] 开头的消息时，按其调整后重新保存（会形成新版本）。
4. 工具保存完成后，用一两句话说明产出了什么即可，不必复述全部内容。"""


class AgentState(TypedDict):
    messages: Annotated[list, _concat]
    iterations: Annotated[int, operator.add]


def _concat(current: list, update: list) -> list:
    return [*current, *update]


def build_agent_graph(*, llm, registry: ToolRegistry, inbox: asyncio.Queue, checkpointer):
    """llm: chat model（此处统一 bind_tools）；inbox: 执行中插话队列（runner 持有）。"""
    llm = llm.bind_tools(registry.openai_schemas())
    async def agent_node(state: AgentState) -> dict:
        # 系统提示不入 state（每次调用前置；检查点保持纯对话史）
        ai = await llm.ainvoke([SystemMessage(content=SYSTEM_PROMPT), *state["messages"]])
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
