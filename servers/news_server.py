"""mining-news-mcp —— 矿业新闻聚合。

数据源降级链:
① 东方财富文章搜索 API(中文主源,关键词搜索)
② northernminer / im-mining RSS(英文补充,客户端过滤)
③ 内置样例数据(断网兜底,source="demo")

传输:stdio(默认)/ http(docker,MCP_SERVER_TRANSPORT=http)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# stdio 子进程模式下 fastmcp 以脚本方式拉起本文件,需把项目根加入 sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datetime import datetime

from fastmcp import FastMCP

from shared.server_runner import run_server
from shared.sources import eastmoney_news, rss_news
from shared.sources.simulate import load_sample

mcp = FastMCP("mining-news-mcp")


# 纯英文查询 → 中文源补查关键词(覆盖本项目主题矿种;LLM 只用英文查询时也能命中中文源)
_ZH_FALLBACK_TERMS = {
    "pilbara": "Pilbara 锂矿", "pilgangoora": "Pilbara 锂矿", "wodgina": "锂矿",
    "lithium": "锂矿", "spodumene": "锂精矿",
    "copper": "铜矿", "nickel": "镍矿", "zinc": "锌矿", "aluminum": "铝矿", "aluminium": "铝矿",
}


def _merge(primary: list[dict], secondary: list[dict], limit: int) -> list[dict]:
    """按 url 去重合并,再按发布日期倒序。published 均为 YYYY-MM-DD 格式。"""
    seen = set()
    out = []
    for it in primary + secondary:
        if it.get("url") and it["url"] in seen:
            continue
        if it.get("url"):
            seen.add(it["url"])
        out.append(it)
    out.sort(key=lambda x: x.get("published", ""), reverse=True)
    return out[:limit]


@mcp.tool
def search(query: str, days: int = 7, limit: int = 10) -> dict:
    """搜索矿业新闻(中英双语)。

    Args:
        query: 关键词,如 "Pilbara 锂矿"、"copper mine"。中文走东方财富搜索,英文词额外匹配国际矿业媒体 RSS。
        days: 只返回最近 N 天内的新闻(0 表示不限时间)。
        limit: 返回条数上限,默认 10。

    Returns:
        dict: {items: [{title, summary, media, url, published}], total, source, data_ts}
        source="real" 为真实数据;"demo" 为全部真实源失败后的内置样例兜底(内容与查询可能不完全匹配)。
    """
    items: list[dict] = []
    zh_items: list[dict] = []
    errors: list[str] = []

    # 中文源检索:纯英文查询命中率低,自动补一条中文主题词查询(东方财富对中文覆盖远好于英文词组)
    zh_queries = [query]
    if not re.search(r"[一-鿿]", query):
        for token, zh in _ZH_FALLBACK_TERMS.items():
            if token in query.lower():
                zh_queries.append(zh)
                break
    for q in zh_queries:
        try:
            r = eastmoney_news.search(q, days=days, limit=limit)
            zh_items = _merge(zh_items, r["items"], limit)
        except Exception as e:  # noqa: BLE001
            errors.append(f"东方财富: {e}")
            # 实时请求失败时回退上次成功搜索的缓存(旧数据优于示例数据)
            cached = eastmoney_news.cached_search(q, limit)
            if cached:
                zh_items = _merge(zh_items, cached.get("items", []), limit)
                errors.append("已回退东方财富缓存(可能稍旧)")

    try:
        r2 = rss_news.search(query, days=days, limit=limit)
        items = _merge(zh_items, r2["items"], limit)
    except Exception as e:  # noqa: BLE001
        errors.append(f"RSS: {e}")
        items = zh_items[:limit]

    if items:
        result = {
            "items": items,
            "total": len(items),
            "source": "real",
            "data_ts": datetime.now().isoformat(timespec="seconds"),
        }
        if errors:
            result["note"] = f"部分数据源异常({'; '.join(errors[:2])}),已用缓存/其余源兜底"
        return result

    # 全部真实源失败 → 内置样例兜底(明确标注 demo)
    try:
        sample = load_sample("news")["items"]
        kw = query.lower()
        filtered = [
            x for x in sample if kw and kw in f"{x['title']} {x['summary']}".lower()
        ] or sample
        reason = f"真实源异常({'; '.join(errors[:2])})" if errors else "真实源可用,但未检索到与查询匹配的新闻"
        return {
            "items": filtered[:limit],
            "total": len(filtered),
            "source": "demo",
            "data_ts": datetime.now().isoformat(timespec="seconds"),
            "note": f"{reason},返回内置样例数据",
        }
    except Exception as e:  # noqa: BLE001
        return {
            "items": [],
            "total": 0,
            "source": "demo",
            "error": f"新闻获取失败: {errors}; 样例缺失: {e}",
            "data_ts": datetime.now().isoformat(timespec="seconds"),
        }


@mcp.tool
def fetch_article(url: str, max_chars: int = 5000) -> dict:
    """抓取指定新闻链接的正文(供深入摘要)。

    Args:
        url: 新闻文章链接(http/https)。
        max_chars: 返回正文的最大字符数,默认 5000。

    Returns:
        dict: {title, text, url, source, data_ts};抓取失败时 text 为空并附 error 字段。
    """
    from shared.http_client import extract_article, get_text

    try:
        html = get_text(url, timeout=10.0)
        art = extract_article(html, max_chars)
        return {
            "title": art["title"],
            "text": art["text"],
            "url": url,
            "source": "real",
            "data_ts": datetime.now().isoformat(timespec="seconds"),
        }
    except Exception as e:  # noqa: BLE001
        return {
            "title": "",
            "text": "",
            "url": url,
            "source": "real",
            "error": f"正文抓取失败: {type(e).__name__}: {e}",
            "data_ts": datetime.now().isoformat(timespec="seconds"),
        }


if __name__ == "__main__":
    run_server(mcp, default_port=8101)
