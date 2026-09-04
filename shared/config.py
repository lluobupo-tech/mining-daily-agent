"""配置加载:从项目根目录 .env 读取环境变量(零第三方依赖)。"""
from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SAMPLE_DATA_DIR = Path(__file__).resolve().parent / "sample_data"
CACHE_DIR = PROJECT_ROOT / "data" / "cache"
OUTPUT_DIR = PROJECT_ROOT / "output"


def load_env(path: Path | None = None) -> None:
    env_file = path or PROJECT_ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


load_env()


def get(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


# LLM 配置(OpenAI 兼容协议)
DEEPSEEK_API_KEY = get("DEEPSEEK_API_KEY")
DEEPSEEK_BASE_URL = get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = get("DEEPSEEK_MODEL", "deepseek-chat")

# Agent 模式:auto = 先 LLM,失败自动降级模板;llm = 强制 LLM;template = 强制确定性模板
AGENT_MODE = get("AGENT_MODE", "auto")

# MCP 传输模式:stdio = Agent 拉起子进程;http = 连接已启动的 HTTP server(docker 场景)
MCP_TRANSPORT = get("MCP_TRANSPORT", "stdio")
