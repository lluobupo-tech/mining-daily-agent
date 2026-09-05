"""自然资源部矿业权市场 —— 矿权 MCP 的官方公告源(国内矿权公示)。

官方站点 ky.mnr.gov.cn(已实测:列表页每页 50 条当日公告)。
官网全文搜索为 JS 动态构造,故采用"爬各频道列表页 + 客户端关键词过滤"方案。
公告日期取自 URL 目录结构(/202609/t20260904_xxx.htm → 2026-09)。
"""
from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urljoin

from shared.cache import kv_get, kv_set
from shared.http_client import get_text

BASE = "https://ky.mnr.gov.cn"

# 频道 → 路径(出让公告/出让结果/转让公示)
# 注:原"采矿权出让结果"频道 /jggs/cjgs/ 已 404(网站改版下线),由其余频道覆盖
CHANNELS = {
    "探矿权出让公告": "/kyqcrgg/tkq/",
    "采矿权出让公告": "/kyqcrgg/ckq/",
    "探矿权出让结果": "/jggs/jjgs/",
}

CACHE_TTL = 3600  # 公告列表缓存 1 小时


def _channel_items(path: str) -> list[dict]:
    cached = kv_get(f"mnr:{path}", ttl=CACHE_TTL)
    if cached is not None:
        return cached
    text = get_text(urljoin(BASE, path), timeout=8.0)
    items = []
    for m in re.finditer(r'<a[^>]*href="([^"]+\.htm[^"]*)"[^>]*>(.*?)</a>', text, re.S):
        href, title = m.group(1), re.sub(r"<[^>]+>", "", m.group(2)).strip()
        if not title or len(title) < 6:
            continue
        d = re.search(r"/(\d{4})(\d{2})/", href)
        items.append(
            {
                "title": title,
                "url": urljoin(BASE, href),
                "date": f"{d.group(1)}-{d.group(2)}" if d else "",
            }
        )
    kv_set(f"mnr:{path}", items)
    return items


def search(keyword: str, days: int = 30, limit: int = 10) -> dict:
    """跨频道抓取并按关键词/时间过滤。单频道失败不影响其余;全部失败时带 error 字段。

    与"官方源可用但无匹配公告"区分开,供上层决定降级策略。
    """
    items = []
    failed = 0
    for ch, path in CHANNELS.items():
        try:
            for it in _channel_items(path):
                if keyword and keyword not in it["title"]:
                    continue
                if days > 0 and it["date"] and it["date"] < _months_ago(days):
                    continue
                items.append({**it, "channel": ch})
        except Exception:
            failed += 1
            continue
    items.sort(key=lambda x: x.get("date", ""), reverse=True)
    # 跨频道按 url 去重(部分公告会同时在出让/结果频道出现)
    seen: set[str] = set()
    unique = [it for it in items if not (it["url"] in seen or seen.add(it["url"]))]
    result = {
        "items": unique[:limit],
        "total": len(unique),
        "source": "real",
        "data_ts": datetime.now().isoformat(timespec="seconds"),
    }
    if failed and failed == len(CHANNELS):
        result["error"] = "全部频道抓取失败"
    return result


def _months_ago(days: int) -> str:
    from datetime import timedelta

    return (datetime.now() - timedelta(days=days)).strftime("%Y-%m")
