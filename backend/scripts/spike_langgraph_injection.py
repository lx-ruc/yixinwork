"""Spike 5.1：验证 LangGraph 两项关键机制的可行性（结论回写 design.md）。

1. 执行中插话：工具循环间隙（工具执行完 → 下一轮 LLM 调用前）注入用户新消息
2. 预览中断与增量修改：interrupt() 暂停 → Command(resume=修改指令) 恢复续跑

用脚本化 Fake 模型 + Event 门控模拟"执行中"并发到达的插话；生产形态见 app/agent/。
"""

import asyncio
import operator
from typing import Annotated, TypedDict

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt


class AgentState(TypedDict):
    messages: Annotated[list, lambda cur, upd: cur + upd]
    iterations: Annotated[int, operator.add]


class FakeToolChatModel(GenericFakeChatModel):
    """支持 bind_tools 的脚本化假模型（按队列依次回放 + 记录输入）。"""

    def bind_tools(self, tools, **kwargs):  # noqa: ANN001
        return self

    async def ainvoke(self, messages, *a, **kw):  # type: ignore[override]
        CALLS.append(list(messages))
        return await super().ainvoke(messages, *a, **kw)


def build_graph(llm, tool_fn, inbox: asyncio.Queue, gate: asyncio.Event):
    async def agent_node(state: AgentState):
        ai = await llm.ainvoke(state["messages"])
        return {"messages": [ai], "iterations": 1}

    async def tools_node(state: AgentState):
        last = state["messages"][-1]
        out = []
        for tc in last.tool_calls:
            result = await tool_fn(tc)  # 工具执行期间事件循环让出 → 插话可入队
            out.append(ToolMessage(content=result, tool_call_id=tc["id"]))
        # ★ 循环间隙注入：工具执行完毕、下一轮 LLM 之前
        while not inbox.empty():
            text = inbox.get_nowait()
            out.append(HumanMessage(content=f"[用户补充指令] {text}"))
        return {"messages": out}

    def after_agent(state: AgentState) -> str:
        return "tools" if state["messages"][-1].tool_calls else "preview"

    async def preview_node(state: AgentState):
        draft = state["messages"][-1].content
        # ★ interrupt：暂停等人工反馈；恢复时从断点拿到 resume 值
        feedback = interrupt({"preview": draft})
        if feedback["action"] == "approve":
            return {"messages": [AIMessage(content="已交付")]}
        return {"messages": [HumanMessage(content=f"[修改要求] {feedback['instruction']}")]}

    def after_preview(state: AgentState) -> str:
        return END if state["messages"][-1].content == "已交付" else "agent"

    g = StateGraph(AgentState)
    g.add_node("agent", agent_node)
    g.add_node("tools", tools_node)
    g.add_node("preview", preview_node)
    g.add_edge(START, "agent")
    g.add_conditional_edges("agent", after_agent, ["tools", "preview"])
    g.add_edge("tools", "agent")
    g.add_conditional_edges("preview", after_preview, [END, "agent"])
    return g.compile(checkpointer=InMemorySaver())


CALLS: list[list] = []  # 每次真实进入模型的输入消息
TOOL_CALLS: list[dict] = []


async def main() -> None:
    script = iter(
        [
            AIMessage(  # 第1轮：要求调工具
                content="",
                tool_calls=[
                    {"name": "write_draft", "args": {"topic": "Q3销售"}, "id": "c1"}
                ],
            ),
            AIMessage(content="初稿：Q3销售报告完成"),  # 第2轮：出稿 → 预览中断
            AIMessage(content="修订版完成"),  # 第3轮：按修改要求改后 → 再预览
        ]
    )
    llm = FakeToolChatModel(messages=script)

    inbox: asyncio.Queue = asyncio.Queue()
    gate = asyncio.Event()

    async def tool_fn(tc: dict) -> str:
        TOOL_CALLS.append(tc)
        await gate.wait()  # 阻在工具执行处，等主协程注入插话
        return "草稿已写出"

    graph = build_graph(llm.bind_tools([]), tool_fn, inbox, gate)
    config = {"configurable": {"thread_id": "spike-1"}}

    # 图在后台跑；主协程在工具执行中入队插话（模拟执行中到达的 HTTP 消息）
    bg = asyncio.create_task(
        graph.ainvoke(
            {"messages": [HumanMessage(content="帮我写Q3销售报告")], "iterations": 0},
            config,
        )
    )
    await asyncio.sleep(0)  # 让后台跑到工具节点挂起
    inbox.put_nowait("加上华南区的数据")
    gate.set()
    await bg  # 运行至 preview 的 interrupt 处返回

    state = await graph.aget_state(config)
    print("== 中断点:", state.next, "| LLM 调用数:", len(CALLS))
    for i, c in enumerate(CALLS):
        print(f"-- call {i}:")
        for m in c:
            print(f"   {m.type:9s} {str(m.content)[:40]!r} tools={getattr(m,'tool_calls',None)}")

    steering_seen = any(
        "[用户补充指令] 加上华南区的数据" in m.content
        for c in CALLS
        for m in c
        if m.type == "human"
    )
    print("★ 插话已在循环间隙注入下一轮 LLM:", steering_seen)
    print("★ 工具已按参数执行:", TOOL_CALLS)

    # ★ 恢复1：修改指令 → agent 收到 [修改要求]
    await graph.ainvoke(
        Command(resume={"action": "revise", "instruction": "加个图表"}), config
    )
    revise_seen = any(
        "[修改要求] 加个图表" in m.content for m in CALLS[-1] if m.type == "human"
    )
    print("★ 修改指令进入新一轮 LLM:", revise_seen, "| 调用数:", len(CALLS))

    # ★ 恢复2：确认交付 → 图走到 END
    await graph.ainvoke(Command(resume={"action": "approve"}), config)
    final = await graph.aget_state(config)
    print("★ 确认后图终止:", final.next == ())


if __name__ == "__main__":
    asyncio.run(main())
