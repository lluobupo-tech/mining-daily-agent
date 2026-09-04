"""westmetall —— LME 官方结算价转载页(免费、国内直连,已实测)。

页面含 "Official LME-Prices in US Dollar" 表(各金属结算价/3 个月价)
与 "LME Stocks" 表(官方库存及变化量,风险提示的事实依据)。
解析 HTML 表格;每次抓取把结算价快照写入本地 sqlite,累积出 LME 历史序列。
"""
from __future__ import annotations

import re
from datetime import datetime

from shared.cache import kv_get, kv_set, snapshot_add
from shared.http_client import get_text

URL = "https://www.westmetall.com/en/markdaten.php?action=show_table&table_id=1"
CACHE_TTL = 21600  # 页面缓存 6 小时

_METALS = {"copper", "tin", "lead", "zinc", "aluminium", "nickel"}

_MONTHS = {
    "January": "01", "February": "02", "March": "03", "April": "04",
    "May": "05", "June": "06", "July": "07", "August": "08",
    "September": "09", "October": "10", "November": "11", "December": "12",
}


def _iso_date(date_str: str) -> str:
    """'03. September 2026' → '2026-09-03'(解析失败返回原文)。"""
    m = re.match(r"(\d{2})\.\s*([A-Za-z]+)\s*(\d{4})", date_str.strip())
    if not m:
        return date_str
    month = _MONTHS.get(m.group(2).capitalize())
    if not month:
        return date_str
    return f"{m.group(3)}-{month}-{m.group(1)}"


def _f(s: str) -> float | None:
    """'14,359.00' → 14359.0;空/非数字 → None。"""
    s = (s or "").replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def _rows(text: str) -> list[list[str]]:
    out = []
    for r in re.findall(r"<tr[^>]*>(.*?)</tr>", text, re.S):
        cells = [re.sub(r"<[^>]+>", "", c).strip() for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", r, re.S)]
        if any(cells):
            out.append(cells)
    return out


def fetch() -> dict:
    """抓取 LME 官方结算价与库存。失败抛异常。"""
    cached = kv_get("westmetall:lme", ttl=CACHE_TTL)
    if cached is not None:
        return cached

    text = get_text(URL, timeout=10.0)
    m = re.search(r"Official LME-Prices[^<]*</[^>]*>.*?(\d{2}\.\s*[A-Za-z]+\s*\d{4})", text, re.S)
    date = m.group(1) if m else ""

    prices: dict[str, dict] = {}
    stocks: dict[str, dict] = {}
    section = ""
    for cells in _rows(text):
        joined = " ".join(cells)
        if "LME-Prices" in joined or "Settlement" in joined:
            section = "prices"
            continue
        if "Stocks" in joined:
            section = "stocks"
            continue
        metal = cells[0].lower() if cells else ""
        if metal in _METALS and len(cells) >= 3:
            if section == "prices":
                prices[metal] = {"cash": _f(cells[1]), "m3": _f(cells[2])}
            elif section == "stocks":
                stocks[metal] = {"tons": _f(cells[1]), "change": _f(cells[2])}

    result = {
        "date": date,
        "prices": prices,
        "stocks": stocks,
        "source": "real",
        "data_ts": datetime.now().isoformat(timespec="seconds"),
    }
    if prices:
        kv_set("westmetall:lme", result)
        # 快照累积:LME 历史走势的数据来源(只存 cash 结算价,日期归一化为 ISO)
        iso = _iso_date(date) if date else ""
        for metal, p in prices.items():
            if p["cash"] is not None:
                snapshot_add(f"lme_{metal}", iso or date, p["cash"], "USD/t", "westmetall")
    return result


def lme_history(metal: str, limit: int = 30) -> list[dict]:
    """本地累积的 LME 结算价序列(先确保快照已写入)。"""
    from shared.cache import snapshot_series

    try:
        fetch()
    except Exception:
        pass
    return snapshot_series(f"lme_{metal}", limit)
