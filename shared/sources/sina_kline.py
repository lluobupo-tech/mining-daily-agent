"""新浪期货日 K 线 —— 价格 MCP 的国内历史数据源(免费、无 key)。

实测:碳酸锂(LC0)自 2023-07 上市至今、沪铜(CU0)自 2005 年至今,逐交易日完整。
注:LME 外盘代码(hf_*)此接口返回 null,国际历史走势走 westmetall 快照累积。
"""
from __future__ import annotations

import json
import re
from datetime import datetime

from shared.cache import kv_get, kv_set
from shared.http_client import get_text

URL = (
    "https://stock2.finance.sina.com.cn/futures/api/jsonp.php/"
    "var%20t=/InnerFuturesNewService.getDailyKLine?symbol={code}"
)

# 品种 → 日 K 代码(与 sina_quote.COMMODITIES 的 nf 代码对应,去前缀)
KLINE_CODES = {"copper": "CU0", "nickel": "NI0", "zinc": "ZN0", "lithium": "LC0"}

CACHE_TTL = 21600  # 日 K 缓存 6 小时


def get_daily(commodity: str) -> list[dict]:
    """返回 [{date, open, high, low, close, volume}] 升序。失败抛异常。"""
    code = KLINE_CODES.get(commodity)
    if not code:
        raise ValueError(f"{commodity} 无国内日 K 代码")
    cached = kv_get(f"kline:{code}", ttl=CACHE_TTL)
    if cached is not None:
        return cached
    text = get_text(URL.format(code=code), timeout=10.0)
    m = re.search(r"var t=\((.*)\);?\s*$", text, re.S)
    if not m:
        raise ValueError(f"K线接口返回异常: {text[:80]}")
    data = json.loads(m.group(1))
    if not isinstance(data, list) or not data:
        raise ValueError("K线数据为空")
    bars = [
        {
            "date": b["d"],
            "open": float(b["o"]),
            "high": float(b["h"]),
            "low": float(b["l"]),
            "close": float(b["c"]),
            "volume": int(b.get("v") or 0),
        }
        for b in data
    ]
    kv_set(f"kline:{code}", bars)
    return bars


def price_on(bars: list[dict], date: str) -> dict | None:
    """取指定日期的收盘价;非交易日返回最近的前一交易日,并标注实际日期。"""
    if not bars:
        return None
    prev = None
    for b in bars:
        if b["date"] > date:
            break
        prev = b
    if prev is None:
        prev = bars[0]
    return {
        "price": prev["close"],
        "date": prev["date"],
        "is_trading_day": prev["date"] == date,
    }


def trend(bars: list[dict], days: int) -> list[dict]:
    """最近 N 个交易日的收盘序列(按交易日计,非自然日)。"""
    return bars[-days:] if days > 0 else bars


def now_ts() -> str:
    return datetime.now().isoformat(timespec="seconds")
