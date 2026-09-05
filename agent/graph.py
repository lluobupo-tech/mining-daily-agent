"""LangGraph 编排:agent(LLM+绑定工具)⇄ tools(异步执行 MCP 工具)循环,无工具调用即结束。

round 计数限制工具调用轮次,防止 LLM 循环失控(成本/时间上限)。
tools 节点手写实现(不用 ToolNode):异步调用 MCP 工具,支持并行 tool_calls,
每个调用生成带 tool_call_id 的 ToolMessage 回填给 LLM。
"""
from __future__ import annotations

import asyncio
import json
from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

MAX_TOOL_ROUNDS = 8


class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    round: int


def build_agent(llm, tools: list):
    tools_by_name = {t.name: t for t in tools}

    def agent(state: AgentState) -> dict:
        bound = llm.bind_tools(tools)
        return {"messages": [bound.invoke(state["messages"])]}

    async def tools_node(state: AgentState) -> dict:
        last = state["messages"][-1]

        async def run_one(tc: dict) -> ToolMessage:
            name = tc.get("name", "")
            args = tc.get("args", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            tool = tools_by_name.get(name)
            if tool is None:
                content = json.dumps({"error": f"未知工具: {name}"}, ensure_ascii=False)
            else:
                try:
                    content = await tool.ainvoke(args)
                except Exception as e:  # noqa: BLE001
                    content = json.dumps({"error": f"{name} 执行失败: {e}"}, ensure_ascii=False)
            return ToolMessage(content=str(content), tool_call_id=tc["id"], name=name)

        # 同一轮多个 tool_calls 并行执行(asyncio.gather),单个失败不影响其余调用
        out_msgs = await asyncio.gather(*(run_one(tc) for tc in last.tool_calls))
        return {"messages": list(out_msgs), "round": state["round"] + 1}

    def route(state: AgentState) -> str:
        last = state["messages"][-1]
        if getattr(last, "tool_calls", None) and state.get("round", 0) < MAX_TOOL_ROUNDS:
            return "tools"
        return END

    g = StateGraph(AgentState)
    g.add_node("agent", agent)
    g.add_node("tools", tools_node)
    g.add_edge(START, "agent")
    g.add_conditional_edges("agent", route, {"tools": "tools", END: END})
    g.add_edge("tools", "agent")
    return g.compile()
