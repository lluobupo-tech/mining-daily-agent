"""MCP ↔ LangChain 桥接(自写薄层,~100 行)。

职责:
1. 按传输模式连接 4 个 MCP server(stdio 拉起子进程 / http 连接容器)
2. 用 list_tools() 动态发现工具,把 MCP 工具的 JSON Schema 转成 pydantic
   模型,包装为 LangChain StructuredTool —— LLM 即可直接 function-calling
3. 记录每次工具调用结果(call_log),供简报"引用源清单"自动聚合
4. 工具调用异常转结构化 error,绝不静默失败
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from fastmcp import Client
from langchain_core.tools import StructuredTool
from pydantic import create_model

# (server 名, 脚本相对路径, HTTP 默认端口)
SERVERS = [
    ("mining-news-mcp", "servers/news_server.py", 8101),
    ("mineral-pdf-mcp", "servers/pdf_server.py", 8102),
    ("lme-price-mcp", "servers/price_server.py", 8103),
    ("mining-rights-mcp", "servers/rights_server.py", 8104),
]

_TYPE_MAP = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "object": dict,
    "array": list,
}


def _schema_to_model(name: str, schema: dict):
    """JSON Schema(properties) → pydantic 模型,供 StructuredTool 校验参数。"""
    props = schema.get("properties") or {}
    fields: dict[str, Any] = {}
    for key, spec in props.items():
        t = _TYPE_MAP.get(spec.get("type"), Any)
        if "default" in spec:
            fields[key] = (t, spec["default"])
        else:
            fields[key] = (t, ...)
    return create_model(f"{name}_args", **fields)


class McpToolset:
    def __init__(self, transport: str = "stdio", project_root: Path | None = None):
        self.transport = transport
        self.root = project_root or Path(__file__).resolve().parent.parent
        self.clients: list[Client] = []
        self.tools: list[StructuredTool] = []
        self.call_log: list[dict] = []  # 每次工具调用的结果记录

    async def start(self) -> list[StructuredTool]:
        # docker 网络模式下,服务地址由 MCP_HTTP_URLS 显式给出(逗号分隔,按 SERVERS 顺序)
        http_urls = [
            u.strip() for u in os.environ.get("MCP_HTTP_URLS", "").split(",") if u.strip()
        ]
        for i, (name, rel_path, port) in enumerate(SERVERS):
            if self.transport == "http":
                target: Any = (
                    http_urls[i] if i < len(http_urls) else f"http://127.0.0.1:{port}/mcp"
                )
            else:
                target = self.root / rel_path
            client = Client(target)
            await client.__aenter__()
            self.clients.append(client)
            for t in await client.list_tools():
                self.tools.append(self._wrap(name, client, t))
        return self.tools

    async def close(self) -> None:
        for c in reversed(self.clients):
            await c.__aexit__(None, None, None)

    def _wrap(self, server: str, client: Client, t) -> StructuredTool:
        model = _schema_to_model(f"{server}_{t.name}", t.input_schema or {})

        async def fn(**kwargs):
            try:
                result = await client.call_tool(t.name, kwargs)
                data = result.data if result.data is not None else {}
                if result.is_error:
                    data = {"error": str(result.content)[:500]}
                print(f"  🔨 {server}.{t.name}({json.dumps(kwargs, ensure_ascii=False)}) → "
                      f"source={data.get('source', '?')}")
                self.call_log.append({"server": server, "tool": t.name, "data": data})
                return json.dumps(data, ensure_ascii=False)
            except Exception as e:  # noqa: BLE001
                print(f"  🔨 {server}.{t.name} 调用失败: {e}")
                self.call_log.append({"server": server, "tool": t.name, "error": str(e)})
                return json.dumps({"error": f"{t.name} 调用失败: {e}"}, ensure_ascii=False)

        return StructuredTool.from_function(
            coroutine=fn,
            name=t.name,
            description=t.description or "",
            args_schema=model,
        )
