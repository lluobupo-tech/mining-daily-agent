"""确定性价格模拟 —— 价格 MCP 的最后兜底与 LME 历史走势补全。

按 (品种, 日期) 播种伪随机数,同一日期结果固定(可复现)。
以实测真实行情为基准价,做 ±1%~2% 日波动的随机游走。
用途与局限在输出中明确标注 source="simulated"(模拟)。
"""
from __future__ import annotations

import hashlib
import json
import random
from datetime import datetime, timedelta

from shared.config import SAMPLE_DATA_DIR

# 基准价来自实测真实行情(2026-09-04)
BASELINES: dict[str, dict] = {
    "lithium":   {"price": 150500.0, "unit": "CNY/t", "name": "碳酸锂", "vol": 0.020},
    "copper":    {"price": 108780.0, "unit": "CNY/t", "name": "铜",     "vol": 0.012},
    "nickel":    {"price": 127780.0, "unit": "CNY/t", "name": "镍",     "vol": 0.015},
    "zinc":      {"price": 28400.0,  "unit": "CNY/t", "name": "锌",     "vol": 0.015},
    "aluminum":  {"price": 20500.0,  "unit": "CNY/t", "name": "铝",     "vol": 0.010},
    "lme_copper":   {"price": 14363.0, "unit": "USD/t", "name": "伦铜", "vol": 0.012},
    "lme_nickel":   {"price": 16779.0, "unit": "USD/t", "name": "伦镍", "vol": 0.015},
    "lme_zinc":     {"price": 3937.0,  "unit": "USD/t", "name": "伦锌", "vol": 0.015},
    "lme_aluminium": {"price": 3285.0, "unit": "USD/t", "name": "伦铝", "vol": 0.012},
}

_ANCHOR = datetime(2026, 9, 4)


def _seed(commodity: str, date_str: str) -> int:
    return int(hashlib.md5(f"{commodity}:{date_str}".encode()).hexdigest()[:8], 16)


def _day_price(commodity: str, date: datetime) -> float:
    info = BASELINES[commodity]
    # 从锚点日基准价出发,按天数游走(锚点前向负方向)
    rng = random.Random(_seed(commodity, date.strftime("%Y-%m-%d")))
    price = info["price"]
    offset = (date - _ANCHOR).days
    step = rng.uniform(-info["vol"], info["vol"])
    price = price * (1 + step * max(1, abs(offset)) * 0.7)
    # 叠加小幅日间噪声,保证同向漂移但有波动
    noise = rng.uniform(-info["vol"] * 0.5, info["vol"] * 0.5)
    return round(price * (1 + noise), 2)


def price_on(commodity: str, date_str: str) -> dict:
    if commodity not in BASELINES:
        raise ValueError(f"模拟数据不支持的品种: {commodity}")
    info = BASELINES[commodity]
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        raise ValueError("日期格式应为 YYYY-MM-DD") from None
    return {
        "commodity": commodity,
        "name": info["name"],
        "price": _day_price(commodity, d),
        "unit": info["unit"],
        "date": date_str,
        "market": "simulated",
        "source": "simulated",
        "data_ts": datetime.now().isoformat(timespec="seconds"),
    }


def trend(commodity: str, days: int = 30) -> list[dict]:
    if commodity not in BASELINES:
        raise ValueError(f"模拟数据不支持的品种: {commodity}")
    info = BASELINES[commodity]
    out = []
    for i in range(days, 0, -1):
        d = _ANCHOR - timedelta(days=i)
        out.append(
            {
                "date": d.strftime("%Y-%m-%d"),
                "price": _day_price(commodity, d),
                "unit": info["unit"],
            }
        )
    return out


def load_sample(key: str) -> dict | list:
    """读取内置样例数据(新闻/储量),与模拟价格共用 sample_data 目录。"""
    path = SAMPLE_DATA_DIR / f"{key}.json"
    if not path.exists():
        raise FileNotFoundError(f"内置样例缺失: {path.name}")
    return json.loads(path.read_text(encoding="utf-8"))
