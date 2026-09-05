"""简报渲染:引用源自动聚合 + 落盘 output/。"""
from __future__ import annotations

from datetime import datetime
from urllib.parse import urlsplit

from shared.config import OUTPUT_DIR

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def collect_refs(call_log: list[dict]) -> list[str]:
    """从工具调用记录中提取引用源链接(新闻链接/公告链接/报告来源),去重保序。

    只保留真实来源的链接:source=demo/simulated 的结果(内置样例、模拟数据)
    以及 example.com 等占位链接一律剔除,避免污染引用源清单。
    """
    urls: list[str] = []
    seen: set[str] = set()

    def add(url: str):
        if not url or not url.startswith("http") or url in seen:
            return
        host = urlsplit(url).netloc.lower()
        if host in ("example.com", "example.org", "example.net") or host.endswith(".example.com"):
            return
        seen.add(url)
        urls.append(url)

    for entry in call_log:
        data = entry.get("data")
        if not isinstance(data, dict):
            continue
        if data.get("source") in ("demo", "simulated"):
            continue
        if isinstance(data.get("items"), list):
            for it in data["items"]:
                if isinstance(it, dict):
                    add(it.get("url", ""))
        add(data.get("source_url", ""))
    return urls[:30]


def strip_preamble(body: str) -> str:
    """去掉 LLM 在正式简报前输出的思考过程(以第一个 # 标题为简报起点)。"""
    lines = body.splitlines()
    for i, ln in enumerate(lines):
        if ln.lstrip().startswith("#"):
            return "\n".join(lines[i:])
    return body


def build_document(query: str, body: str, refs: list[str], mode: str, meta: str = "") -> str:
    """主体 + 引用源清单 + 页脚。"""
    parts = [strip_preamble(body).rstrip()]
    parts.append("\n---\n\n## 引用源")
    if refs:
        parts.extend(f"{i}. {u}" for i, u in enumerate(refs, 1))
    else:
        parts.append("(本次无外部链接)")
    parts.append(
        f"\n---\n\n*生成时间:{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | "
        f"模式:{mode}{(' | ' + meta) if meta else ''} | "
        "数据标注:真实/示例/模拟以正文标注为准*"
    )
    return "\n".join(parts)


def save_briefing(query: str, body: str, refs: list[str], mode: str, meta: str = "") -> str:
    """写 output/简报-YYYYMMDD-HHMMSS.md,返回文件路径。"""
    doc = build_document(query, body, refs, mode, meta)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = OUTPUT_DIR / f"简报-{ts}.md"
    path.write_text(doc, encoding="utf-8")
    return str(path)
