"""MCP server 统一启动入口:双传输模式。

- stdio(默认):Claude Desktop / Cursor 及 Agent 本地子进程模式
- http:docker-compose 容器模式(MCP_SERVER_TRANSPORT=http,MCP_SERVER_PORT=指定端口)
"""
from __future__ import annotations

import os


def run_server(mcp, default_port: int) -> None:
    transport = os.environ.get("MCP_SERVER_TRANSPORT", "stdio")
    if transport == "http":
        port = int(os.environ.get("MCP_SERVER_PORT", str(default_port)))
        mcp.run(transport="http", host="0.0.0.0", port=port)
    else:
        mcp.run()
