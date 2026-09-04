"""确定性模板流水线 —— 无 LLM / LLM 失败时的兜底。

直接(同进程)调用四个 server 的工具函数,按固定模板拼装简报。
任何网络源失败都会走各 server 内置的降级链,因此本流水线"永远能出简报"。
"""
from __future__ import annotations

from datetime import datetime

from servers import news_server, pdf_server, price_server, rights_server

# 查询意图 → 数据参数(粗粒度关键词匹配)
_INTENTS = [
    # (关键词集合, 项目样例, 品种, 新闻关键词, 矿权关键词)
    (("pilbara", "锂", "lithium", "pilgangoora"), "pilgangoora", "lithium", "Pilbara 锂矿", "锂"),
    (("铜", "copper"), "pilgangoora", "copper", "铜矿 copper mine", "铜"),
    (("镍", "nickel"), "pilgangoora", "nickel", "镍 nickel mining", "镍"),
    (("锌", "zinc"), "pilgangoora", "zinc", "锌 zinc mining", "锌"),
    (("铝", "aluminum", "aluminium"), "pilgangoora", "aluminum", "铝 aluminum mining", "铝"),
]
_DEFAULT_INTENT = ("pilgangoora", "lithium", "Pilbara 锂矿", "锂")


def _intent(query: str) -> tuple:
    q = query.lower()
    for kws, project, commodity, news_q, rights_q in _INTENTS:
        if any(k in q for k in kws):
            return project, commodity, news_q, rights_q
    return _DEFAULT_INTENT


def _fmt_price(price: dict) -> str:
    if "error" in price:
        return f"获取失败({price['error'][:60]})"
    note = f"({price.get('note', '')})" if price.get("note") else ""
    return f"{price.get('price')} {price.get('unit', '')} @ {price.get('date', '')} {note}"


def run(query: str) -> tuple[str, str, list[dict]]:
    """返回 (简报 Markdown 主体, 模式说明, 工具调用记录)。"""
    project, commodity, news_q, rights_q = _intent(query)

    news = news_server.search(news_q, days=30, limit=6)
    res = pdf_server.extract_resources(f"sample://{project}")
    price = price_server.get_price(commodity)
    trend = price_server.get_trend(commodity, 30)
    rights = rights_server.search_mining_rights(rights_q, days=90, limit=5)

    call_log = [
        {"server": "mining-news-mcp", "tool": "search", "data": news},
        {"server": "mineral-pdf-mcp", "tool": "extract_resources", "data": res},
        {"server": "lme-price-mcp", "tool": "get_price", "data": price},
        {"server": "lme-price-mcp", "tool": "get_trend", "data": trend},
        {"server": "mining-rights-mcp", "tool": "search_mining_rights", "data": rights},
    ]

    tag = lambda s: "⚠️示例" if s == "demo" else ("⚠️模拟" if s == "simulated" else "✅真实")  # noqa: E731
    lines = [
        f"# 矿权日报简报(模板模式)",
        f"> 查询:{query}",
        "",
        "## ① 今日要闻摘要",
    ]
    if news.get("items"):
        for it in news["items"]:
            media = it.get("media", "")
            pub = it.get("published", "")
            url = it.get("url", "")
            link = f" [链接]({url})" if url.startswith("http") else ""
            lines.append(
                f"- **{it['title']}**({media},{pub})[{tag(news.get('source'))}]{link}"
            )
    else:
        lines.append(f"- 暂无新闻 {news.get('error', '') or news.get('note', '')}")
    if news.get("note"):
        lines.append(f"> {news['note']}")

    lines += ["", "## ② 储量数据"]
    if "categories" in res and res["categories"]:
        lines.append(f"- **{res.get('project') or '(报告未命名)'}**({res.get('company', '')}){tag(res.get('source'))}")
        for cat, v in res["categories"].items():
            lines.append(f"  - {cat}:{v.get('tonnage_mt')} Mt @ {v.get('grade', '')}")
        if res.get("note"):
            lines.append(f"> {res['note']}")
    else:
        lines.append(f"- {res.get('note') or res.get('error') or '未识别到储量数据'}")

    lines += ["", "## ③ 价格走势"]
    lines.append(f"- 最新价:{_fmt_price(price)} {tag(price.get('source', ''))}")
    pts = trend.get("points", [])
    if pts:
        first, last = pts[0]["price"], pts[-1]["price"]
        chg = (last - first) / first * 100 if first else 0
        hi = max(p["price"] for p in pts)
        lo = min(p["price"] for p in pts)
        unit = trend.get("unit", "")
        lines.append(f"- 近 {len(pts)} 个交易日:{(trend.get('name') or commodity)} {first} → {last} {unit},"
                     f"涨跌幅 {chg:+.2f}%,区间最高 {hi}、最低 {lo}")
        lines.append(f"- 走势(收盘价序列):")
        step = max(1, len(pts) // 10)
        sampled = [f"{p['date']}:{p['price']}" for p in pts[::step]]
        if len(pts) % step != 1 or pts[-1] not in pts[::step]:
            sampled.append(f"{pts[-1]['date']}:{pts[-1]['price']}")
        lines.append(f"  `{', '.join(sampled)}`")
    if trend.get("note"):
        lines.append(f"> {trend['note']}")

    lines += ["", "## ④ 风险提示"]
    lines.append("- 价格波动:近月走势振幅显著,锂价与供需预期高度相关,需关注库存与下游排产变化")
    lines.append("- 储量估算:NI 43-101/JORC 分级资源量非经济储量,含推断资源(Inferred)部分经济转化存在不确定性")
    lines.append("- 政策与许可:矿业权出让、环保许可与社区审批进度可能影响项目开发节奏")
    if rights.get("items"):
        lines.append("- 近期矿权动态:")
        for it in rights["items"][:3]:
            lines.append(f"  - {it['date']} {it['title']}({it['channel']})")

    return "\n".join(lines), "template", call_log
