"""矿权日报 Agent 入口。

两种使用方式:
- 交互模式:uv run python -m agent.main → 预设菜单(猜你想搜),输入序号或自然语言
- 参数模式:uv run python -m agent.main --query "给我生成一份关于 Pilbara 锂矿的今日简报"

模式:auto(默认,LLM 失败自动降级模板)/ llm / template(环境变量 AGENT_MODE 或 --mode)
传输:stdio(默认,Agent 拉起 4 个 server 子进程)/ http(连 docker 起的 4 个容器,MCP_TRANSPORT=http)
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.bridge import McpToolset
from agent.prompts import SYSTEM_PROMPT
from agent.render import collect_refs, save_briefing
from agent.template_agent import run as run_template
from shared.config import (
    AGENT_MODE,
    DEEPSEEK_API_KEY,
    DEEPSEEK_BASE_URL,
    DEEPSEEK_MODEL,
    MCP_TRANSPORT,
)

MENU = [
    "给我生成一份关于 Pilbara 锂矿的今日简报",
    "碳酸锂最近 30 天价格走势如何?",
    "解析这份储量报告:sample://pilgangoora",
    "最近有哪些铜矿的矿权出让公告?",
]

BANNER = """
╔═══════════════════════════════════════════════════╗
║  矿权日报 Agent · 4×MCP + LangGraph + DeepSeek    ║
║  新闻聚合 · 储量解析(PDF)· 价格行情 · 矿权公示     ║
╚═══════════════════════════════════════════════════╝
猜你想搜:
"""


async def _run_llm(query: str, toolset: McpToolset) -> str:
    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_openai import ChatOpenAI

    from agent.graph import build_agent

    llm = ChatOpenAI(
        model=DEEPSEEK_MODEL,
        base_url=DEEPSEEK_BASE_URL,
        api_key=DEEPSEEK_API_KEY,
        temperature=0.3,
        request_timeout=180,
    )
    graph = build_agent(llm, toolset.tools)
    result = await graph.ainvoke(
        {
            "messages": [
                SystemMessage(content=SYSTEM_PROMPT),
                HumanMessage(content=query),
            ],
            "round": 0,
        }
    )
    return str(result["messages"][-1].content)


async def _run(query: str, mode: str) -> tuple[str, str]:
    """返回 (简报路径, 实际模式)。"""
    if mode == "auto":
        mode = "llm" if DEEPSEEK_API_KEY else "template"

    if mode == "llm":
        toolset = McpToolset(transport=MCP_TRANSPORT)
        try:
            await toolset.start()
            try:
                body = await _run_llm(query, toolset)
                if not body.strip():
                    raise ValueError("LLM 输出为空")
            finally:
                await toolset.close()
            refs = collect_refs(toolset.call_log)
            # 只保留 LLM 在简报正文中实际引用的链接(避免把搜索中间结果全列进来)
            cited = [u for u in refs if u in body]
            refs = cited if cited else refs
            path = save_briefing(query, body, refs, "llm")
            return path, "llm"
        except Exception as e:  # noqa: BLE001
            print(f"[降级] LLM 模式失败({type(e).__name__}: {str(e)[:150]}),自动切换模板模式")
            return await _run(query, "template")

    body, _, call_log = run_template(query)
    refs = collect_refs(call_log)
    path = save_briefing(query, body, refs, "template")
    return path, "template"


def interactive_menu() -> str:
    print(BANNER)
    for i, item in enumerate(MENU, 1):
        print(f"  {i}️⃣  {item}")
    print()
    try:
        choice = input("请输入序号或直接输入问题(回车=1):").strip()
    except EOFError:
        choice = ""
    if choice.isdigit() and 1 <= int(choice) <= len(MENU):
        return MENU[int(choice) - 1]
    if not choice:
        return MENU[0]
    return choice


def main() -> None:
    parser = argparse.ArgumentParser(description="矿权日报 Agent")
    parser.add_argument("--query", "-q", help="直接提问(跳过交互菜单)")
    parser.add_argument("--mode", choices=["auto", "llm", "template"], default=None,
                        help=f"运行模式(默认环境变量 AGENT_MODE={AGENT_MODE})")
    args = parser.parse_args()

    query = args.query or interactive_menu()
    mode = args.mode or AGENT_MODE
    print(f"\n📝 查询: {query}\n")

    path, used_mode = asyncio.run(_run(query, mode))
    print(f"\n✅ 简报已生成: {path}(模式: {used_mode})")


if __name__ == "__main__":
    main()
