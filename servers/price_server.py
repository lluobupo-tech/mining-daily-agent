"""lme-price-mcp —— 金属价格行情(国内期货真实行情 + LME 官方结算)。

数据源降级链:
- 最新价:新浪 nf_ 国内实时(¥)→ 新浪 hf_ LME 实时($)→ westmetall LME 官方结算 → 确定性模拟
- 历史价:新浪日K(国内品种,真实)→ westmetall 官方结算快照(LME)→ 确定性模拟
- 走势:新浪日K → westmetall 快照累积(≥5 点)→ 确定性模拟

局限(如实标注):LME 无免费历史 K 线接口,其历史走势依赖 westmetall 每日快照的本地累积,
首次运行仅有当日结算价,不足时以模拟数据补全并在结果中标注。
"""
from __future__ import annotations

import sys
from pathlib import Path

# stdio 子进程模式下 fastmcp 以脚本方式拉起本文件,需把项目根加入 sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datetime import datetime

from fastmcp import FastMCP

from shared.server_runner import run_server
from shared.sources import sina_kline, sina_quote, simulate, westmetall

mcp = FastMCP("lme-price-mcp")

SUPPORTED = "copper(铜) / nickel(镍) / zinc(锌) / lithium(碳酸锂) / aluminum(铝)"


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _lme_metal(key: str) -> str:
    return "aluminium" if key == "aluminum" else key


def _sim_fallback(key: str, date: str, errors: list[str], market_note: str) -> dict:
    sim_key = key if sina_quote.COMMODITIES[key]["nf"] else f"lme_{_lme_metal(key)}"
    try:
        q = simulate.price_on(sim_key, date)
        return {
            **q,
            "note": f"真实源不可用({'; '.join(errors[:2]) or '网络异常'}),返回确定性模拟数据({market_note})",
        }
    except Exception as e:  # noqa: BLE001
        return {
            "commodity": key,
            "error": f"价格获取失败: {'; '.join(errors)}; 模拟失败: {e}",
            "source": "simulated",
            "data_ts": datetime.now().isoformat(timespec="seconds"),
        }


@mcp.tool
def get_price(commodity: str, date: str = "") -> dict:
    """查询金属价格。

    Args:
        commodity: 品种,支持 copper / nickel / zinc / lithium / aluminum(或中文名:铜/镍/锌/锂/碳酸锂/铝)。
        date: 日期 YYYY-MM-DD。留空或为今天 → 最新价;过去日期 → 历史收盘价(非交易日自动回退最近交易日)。

    Returns:
        dict: {commodity, name, market, price, unit, date, source, data_ts, note?}
        source: real=真实行情; simulated=确定性模拟兜底。market: SHFE/GFEX(国内,¥)/ LME(美元)。
    """
    key = sina_quote.resolve(commodity)
    if not key:
        return {
            "error": f"不支持的品种: {commodity}",
            "supported": SUPPORTED,
            "data_ts": datetime.now().isoformat(timespec="seconds"),
        }
    info = sina_quote.COMMODITIES[key]
    target = (date or "").strip()
    is_latest = not target or target >= _today()
    errors: list[str] = []

    # 1) 国内品种:实时 / 历史日K(真实)
    if info["nf"]:
        if is_latest:
            try:
                return sina_quote.quote(key, "domestic")
            except Exception as e:  # noqa: BLE001
                errors.append(f"新浪国内实时: {e}")
        else:
            try:
                bars = sina_kline.get_daily(key)
                p = sina_kline.price_on(bars, target)
                return {
                    "commodity": key,
                    "name": info["name"],
                    "market": "SHFE/GFEX",
                    "price": p["price"],
                    "unit": "CNY/t",
                    "date": p["date"],
                    "is_trading_day": p["is_trading_day"],
                    "source": "real",
                    "source_url": sina_kline.URL.format(code=sina_kline.KLINE_CODES[key]),
                    "data_ts": datetime.now().isoformat(timespec="seconds"),
                    "note": "" if p["is_trading_day"] else f"{target} 非交易日,回退最近交易日 {p['date']}",
                }
            except Exception as e:  # noqa: BLE001
                errors.append(f"新浪日K: {e}")

    # 2) LME:实时 / westmetall 官方结算快照
    if info["hf"]:
        if is_latest:
            try:
                return sina_quote.quote(key, "lme")
            except Exception as e:  # noqa: BLE001
                errors.append(f"新浪LME实时: {e}")
        try:
            w = westmetall.fetch()
            if is_latest:
                p = w["prices"].get(_lme_metal(key), {}).get("cash")
                if p is not None:
                    return {
                        "commodity": key,
                        "name": info["name"],
                        "market": "LME(官方结算)",
                        "price": p,
                        "unit": "USD/t",
                        "date": w["date"],
                        "source": "real",
                        "source_url": westmetall.URL,
                        "data_ts": datetime.now().isoformat(timespec="seconds"),
                        "note": "LME 官方结算价(westmetall 转载)",
                    }
                errors.append("westmetall: 无该品种结算价")
            else:
                # 指定历史日期:只接受快照中的精确命中,否则降级模拟
                matched = None
                for s in westmetall.lme_history(_lme_metal(key), 300):
                    if s["date"] == target:
                        matched = s
                        break
                if matched is not None:
                    return {
                        "commodity": key,
                        "name": info["name"],
                        "market": "LME(官方结算)",
                        "price": matched["price"],
                        "unit": "USD/t",
                        "date": matched["date"],
                        "source": "real",
                        "source_url": westmetall.URL,
                        "data_ts": datetime.now().isoformat(timespec="seconds"),
                        "note": "LME 官方结算价(westmetall 快照)",
                    }
                errors.append(f"westmetall 快照中无 {target} 的记录(首次运行仅有当日快照)")
        except Exception as e:  # noqa: BLE001
            errors.append(f"westmetall: {e}")

    # 3) 确定性模拟兜底
    return _sim_fallback(key, target or _today(), errors, "LME" if info["hf"] and not info["nf"] else "国内")


@mcp.tool
def get_trend(commodity: str, days: int = 30) -> dict:
    """查询金属最近 N 天价格走势(按交易日)。

    Args:
        commodity: 品种,同 get_price。
        days: 交易日数量,默认 30(上限 250)。

    Returns:
        dict: {commodity, name, market, unit, points: [{date, price}], source, data_ts, note?}
        source: real=真实走势(国内期货日K / LME 官方结算快照累积);
        simulated=模拟走势(真实源不可用或 LME 快照不足 5 点时的兜底)。
    """
    key = sina_quote.resolve(commodity)
    if not key:
        return {
            "error": f"不支持的品种: {commodity}",
            "supported": SUPPORTED,
            "data_ts": datetime.now().isoformat(timespec="seconds"),
        }
    info = sina_quote.COMMODITIES[key]
    days = max(1, min(days, 250))
    errors: list[str] = []

    # 1) 国内品种:真实日K
    if info["nf"]:
        try:
            bars = sina_kline.get_daily(key)
            pts = sina_kline.trend(bars, days)
            return {
                "commodity": key,
                "name": info["name"],
                "market": "SHFE/GFEX",
                "unit": "CNY/t",
                "points": [{"date": b["date"], "price": b["close"]} for b in pts],
                "source": "real",
                "source_url": sina_kline.URL.format(code=sina_kline.KLINE_CODES[key]),
                "data_ts": datetime.now().isoformat(timespec="seconds"),
            }
        except Exception as e:  # noqa: BLE001
            errors.append(f"新浪日K: {e}")

    # 2) LME:westmetall 官方结算快照累积(≥5 点才算可用)
    if info["hf"]:
        try:
            hist = westmetall.lme_history(_lme_metal(key), limit=days + 30)
            if len(hist) >= 5:
                return {
                    "commodity": key,
                    "name": info["name"],
                    "market": "LME(官方结算)",
                    "unit": "USD/t",
                    "points": [{"date": s["date"], "price": s["price"]} for s in hist][-days:],
                    "source": "real",
                    "source_url": westmetall.URL,
                    "data_ts": datetime.now().isoformat(timespec="seconds"),
                    "note": "LME 官方结算价每日快照累积(免费源无 LME 历史 K 线,首次运行点数较少)",
                }
            errors.append(f"westmetall 快照仅 {len(hist)} 点(不足 5 点)")
        except Exception as e:  # noqa: BLE001
            errors.append(f"westmetall: {e}")

    # 3) 模拟兜底
    sim_key = key if info["nf"] else f"lme_{_lme_metal(key)}"
    try:
        pts = simulate.trend(sim_key, days)
        return {
            "commodity": key,
            "name": info["name"],
            "market": "simulated",
            "unit": pts[0]["unit"] if pts else "",
            "points": pts,
            "source": "simulated",
            "data_ts": datetime.now().isoformat(timespec="seconds"),
            "note": f"真实源不可用({'; '.join(errors[:2]) or '网络异常'}),返回确定性模拟走势",
        }
    except Exception as e:  # noqa: BLE001
        return {
            "commodity": key,
            "error": f"走势获取失败: {'; '.join(errors)}; 模拟失败: {e}",
            "points": [],
            "source": "simulated",
            "data_ts": datetime.now().isoformat(timespec="seconds"),
        }


if __name__ == "__main__":
    run_server(mcp, default_port=8103)
