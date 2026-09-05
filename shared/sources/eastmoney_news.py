"""东方财富文章搜索 API —— 新闻 MCP 的中文主源。

免费、无需 key、国内直连,支持关键词搜索(实测:"Pilbara" 命中 18 篇、"锂矿" 命中 2909 篇)。
返回标题/摘要/媒体/日期/链接,日期为字符串可直接比较。
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta

from shared.cache import kv_get, kv_set
from shared.http_client import get_text

URL = "https://search-api-web.eastmoney.com/search/jsonp"

CACHE_TTL = 1800  # 搜索结果缓存 30 分钟


def _build_param(keyword: str, page_size: int) -> dict:
    return {
        "uid": "",
        "keyword": keyword,
        "type": ["cmsArticleWebOld"],
        "client": "web",
        "clientType": "web",
        "clientVersion": "curr",
        "param": {
            "cmsArticleWebOld": {
                "searchScope": "default",
                # 必须按时间排序:default 为相关性排序,近 N 天新闻排在首页之外,会被日期窗口全滤掉
                "sort": "time",
                "pageIndex": 1,
                "pageSize": page_size,
                "preTag": "",
                "postTag": "",
            }
        },
    }


def cached_search(keyword: str, limit: int) -> dict | None:
    """读取最近一次成功搜索的缓存(忽略 TTL)。

    供新闻 MCP 在实时请求失败时兜底:旧数据优于示例数据。
    """
    return kv_get(f"em_news:{keyword}:{limit}")


def _clean(html: str) -> str:
    return re.sub(r"<[^>]+>", "", html or "").strip()


def search(keyword: str, days: int = 7, limit: int = 10) -> dict:
    """搜索新闻。失败抛异常,由调用方降级。"""
    cache_key = f"em_news:{keyword}:{limit}"
    cached = kv_get(cache_key, ttl=CACHE_TTL)
    if cached is not None:
        return cached

    param = _build_param(keyword, max(limit, 10))
    text = get_text(URL, params={"cb": "x", "param": json.dumps(param, ensure_ascii=False)}, timeout=8.0)
    m = re.search(r"^[^(]*\((.*)\)\s*$", text, re.S)
    if not m:
        raise ValueError("东方财富返回格式异常")
    data = json.loads(m.group(1))
    arts = data.get("result", {}).get("cmsArticleWebOld", [])

    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    items = []
    for a in arts:
        date = (a.get("date") or "")[:10]
        if days > 0 and date and date < cutoff:
            continue
        items.append(
            {
                "title": _clean(a.get("title")),
                "summary": _clean(a.get("content")),
                "media": a.get("mediaName", ""),
                "url": a.get("url", ""),
                "published": date,
            }
        )
        if len(items) >= limit:
            break

    result = {
        "items": items,
        "total": data.get("hitsTotal", len(items)),
        "source": "real",
        "data_ts": datetime.now().isoformat(timespec="seconds"),
    }
    if items:
        kv_set(cache_key, result)
    return result
