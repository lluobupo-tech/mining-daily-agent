"""新浪财经行情 API —— 价格 MCP 的实时行情源(免费、无 key、国内直连)。

- 国内期货(nf_ 代码):沪铜/沪镍/沪锌/广期所碳酸锂,人民币元/吨
- 国际 LME(hf_ 代码):伦铜/伦镍/伦锌/伦铝,美元/吨
实测:沪铜 ¥108,780、碳酸锂 ¥150,500、伦铜 $14,363.45(2026-09-04)。
"""
from __future__ import annotations

import re
from datetime import datetime

from shared.http_client import get_bytes

QUOTE_URL = "https://hq.sinajs.cn/list={codes}"
REFERER = {"Referer": "https://finance.sina.com.cn"}

# 品种 → (国内代码, LME 代码, 中文名, 单位)
COMMODITIES: dict[str, dict] = {
    "copper":   {"nf": "nf_CU0", "hf": "hf_CAD", "name": "铜",     "unit": "CNY/t"},
    "nickel":   {"nf": "nf_NI0", "hf": "hf_NID", "name": "镍",     "unit": "CNY/t"},
    "zinc":     {"nf": "nf_ZN0", "hf": "hf_ZSD", "name": "锌",     "unit": "CNY/t"},
    "lithium":  {"nf": "nf_LC0", "hf": None,     "name": "碳酸锂", "unit": "CNY/t"},
    "aluminum": {"nf": None,     "hf": "hf_AHD", "name": "铝",     "unit": "USD/t"},
}

ALIASES = {
    "铜": "copper", "铜价": "copper", "lme铜": "copper", "伦铜": "copper",
    "镍": "nickel", "lme镍": "nickel", "伦镍": "nickel",
    "锌": "zinc", "lme锌": "zinc", "伦锌": "zinc",
    "锂": "lithium", "锂价": "lithium", "碳酸锂": "lithium", "lithium": "lithium",
    "铝": "aluminum", "lme铝": "aluminum", "伦铝": "aluminum",
    "copper": "copper", "nickel": "nickel", "zinc": "zinc", "aluminum": "aluminum",
}


def resolve(commodity: str) -> str:
    key = commodity.strip().lower()
    return ALIASES.get(key, ALIASES.get(commodity.strip(), ""))


def _fetch(codes: str) -> dict[str, list[str]]:
    """抓取并解析,返回 {code: fields}。响应为 GBK 编码。"""
    raw = get_bytes(QUOTE_URL.format(codes=codes), headers=REFERER, timeout=8.0)
    text = raw.decode("gbk", errors="ignore")
    out: dict[str, list[str]] = {}
    for line in text.splitlines():
        if "=" not in line or not line.startswith("var hq_str_"):
            continue
        code = line.split("=")[0].replace("var hq_str_", "").strip()
        payload = line.split('"', 2)[1] if '"' in line else ""
        out[code] = payload.split(",")
    return out


def _is_float(s: str) -> bool:
    try:
        float(s)
        return True
    except (TypeError, ValueError):
        return False


def _find_date(fields: list[str]) -> str:
    """日期字段位置不固定,按 YYYY-MM-DD 模式扫描。"""
    for f in fields:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", f):
            return f
    return ""


def quote(commodity: str, market: str = "domestic") -> dict:
    """实时报价。market: domestic(国内期货,¥)/ lme(伦敦金属,USD)。

    新浪 hf_ 外盘接口在不同时段返回两种字段布局(名称在前 或 最新价在前),
    此处做格式自适应解析;仍解析不出时抛异常,由调用方降级(westmetall/模拟)。
    """
    key = resolve(commodity)
    if not key:
        raise ValueError(f"不支持的品种: {commodity}")
    info = COMMODITIES[key]
    code = info["nf"] if market == "domestic" else info["hf"]
    if not code:
        raise ValueError(f"{info['name']} 无 {'国内' if market == 'domestic' else 'LME'} 行情代码")
    fields = _fetch(code)[code]

    if market == "domestic":
        # nf_ 国内期货:字段 8 = 最新价,名称在字段 0
        if len(fields) <= 8 or not _is_float(fields[8]):
            raise ValueError("国内行情暂不可用")
        price = float(fields[8])
        name = fields[0]
    else:
        # hf_ LME 外盘:两种布局自适应
        if _is_float(fields[0]):
            price = float(fields[0])
            name = fields[13] if len(fields) > 13 and fields[13] else info["name"]
        elif len(fields) > 1 and _is_float(fields[1]):
            price = float(fields[1])
            name = fields[0]
        elif len(fields) > 8 and _is_float(fields[8]):
            price = float(fields[8])  # 昨收兜底
            name = info["name"]
        else:
            raise ValueError("LME 行情暂不可用")

    return {
        "commodity": key,
        "name": name or info["name"],
        "market": "SHFE/GFEX" if market == "domestic" else "LME",
        "price": price,
        "unit": "CNY/t" if market == "domestic" else "USD/t",
        "date": _find_date(fields),
        "source": "real",
        "source_url": f"https://hq.sinajs.cn/list={code}",
        "data_ts": datetime.now().isoformat(timespec="seconds"),
    }
