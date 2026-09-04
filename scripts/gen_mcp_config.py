"""自动生成 mcp-config.local.json:探测本机 Python 路径与项目根,免手工替换占位符。

用法:
    python scripts/gen_mcp_config.py
生成后,把 mcp-config.local.json 的 mcpServers 内容复制到:
- Claude Desktop: %APPDATA%\\Claude\\claude_desktop_config.json(Windows)/ ~/Library/.../claude_desktop_config.json(macOS)
- Cursor:项目根 .cursor/mcp.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = PROJECT_ROOT / "mcp-config.json"


def detect_python() -> str:
    """优先项目 .venv 的 python(依赖都装在里面),否则当前解释器。"""
    if sys.platform == "win32":
        venv_py = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
    else:
        venv_py = PROJECT_ROOT / ".venv" / "bin" / "python"
    if venv_py.exists():
        return str(venv_py)
    return sys.executable


def main() -> None:
    cfg = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    python_path = detect_python()
    root = str(PROJECT_ROOT)
    for server in cfg["mcpServers"].values():
        server["command"] = python_path
        server["cwd"] = root
    out = PROJECT_ROOT / "mcp-config.local.json"
    out.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已生成 {out}")
    print(f"  Python  : {python_path}")
    print(f"  项目根  : {root}")
    print("下一步:把该文件的 mcpServers 内容复制进 Claude Desktop / Cursor 配置(见 RUN.md)。")


if __name__ == "__main__":
    main()
