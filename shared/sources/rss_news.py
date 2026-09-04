"""英文矿业媒体 RSS —— 新闻 MCP 的英文补充源。

northernminer(加拿大矿业报)/ im-mining(国际矿业),国内直连(已实测 200)。
RSS 无搜索接口,采用"拉全量 + 客户端关键词过滤";纯中文查询(无英文词)时自动跳过。
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from shared.cache import kv_get, kv_set
from shared.http_client import get_text

FEEDS = {
    "northernminer": "https://www.northernminer.com/feed/",
    "im-mining": "https://im-mining.com/feed/",
}

CACHE_TTL = 1800


def _parse_date(pubdate: str) -> datetime | None:
    try:
        dt = parsedate_to_datetime(pubdate)
        return dt.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _feed_items(name: str, url: str) -> list[dict]:
    cached = kv_get(f"rss:{name}", ttl=CACHE_TTL)
    if cached is not None:
        return cached
    text = get_text(url, timeout=8.0)
    root = ET.fromstring(text)
    items = []
    for it in root.findall(".//item"):
        raw_date = (it.findtext("pubDate") or "").strip()
        parsed = _parse_date(raw_date)
        items.append(
            {
                "title": (it.findtext("title") or "").strip(),
                "url": (it.findtext("link") or "").strip(),
                "summary": re.sub(r"<[^>]+>", "", it.findtext("description") or "").strip()[:300],
                # 统一为 YYYY-MM-DD,便于与中文源合并排序
                "published": parsed.strftime("%Y-%m-%d") if parsed else raw_date,
                "media": name,
            }
        )
    kv_set(f"rss:{name}", items)
    return items


def search(query: str, days: int = 7, limit: int = 10) -> dict:
    """英文 RSS 关键词过滤。查询不含英文词时返回空(英文源无法覆盖中文查询)。"""
    terms = re.findall(r"[A-Za-z0-9]+", query)
    if not terms:
        return {"items": [], "total": 0, "source": "real", "data_ts": datetime.now().isoformat(timespec="seconds")}

    items = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    for name, url in FEEDS.items():
        try:
            for it in _feed_items(name, url):
                hay = f"{it['title']} {it['summary']}".lower()
                if not any(t.lower() in hay for t in terms):
                    continue
                pub = _parse_date(it["published"])
                if days > 0 and pub is not None and pub < cutoff:
                    continue
                items.append(it)
        except Exception:  # 单源失败不影响另一源
            continue

    items.sort(key=lambda x: x.get("published", ""), reverse=True)
    return {"items": items[:limit], "total": len(items), "source": "real", "data_ts": datetime.now().isoformat(timespec="seconds")}
