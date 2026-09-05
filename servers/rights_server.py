"""mining-rights-mcp —— 矿业权出让公示(第 4 个 server,补全官方矿权数据源)。

数据源降级链:
① 自然资源部矿业权市场(ky.mnr.gov.cn)官方公告列表:探矿权/采矿权出让公告、出让结果
② 内置样例(断网兜底,source="demo")
国际矿权动态经新闻 MCP(英文 RSS/东财)间接覆盖。

传输:stdio(默认)/ http(docker,MCP_SERVER_TRANSPORT=http)
"""
from __future__ import annotations

import sys
from pathlib import Path

# stdio 子进程模式下 fastmcp 以脚本方式拉起本文件,需把项目根加入 sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datetime import datetime

from fastmcp import FastMCP

from shared.server_runner import run_server
from shared.sources import eastmoney_news, mnr_rights
from shared.sources.simulate import load_sample

mcp = FastMCP("mining-rights-mcp")

# 媒体矿权动态的标题相关性过滤词(东方财富搜索为宽松匹配,需客户端二次过滤)
_RIGHTS_TITLE_TERMS = ("矿权", "矿业权", "探矿权", "采矿权", "出让")


def _news_backup(keyword: str, days: int, limit: int) -> dict:
    """二级真实源:媒体矿权动态(东方财富搜索 + 标题相关性过滤)。

    官方公示无匹配/不可用时的备份,避免单一来源;标题不相关的结果直接剔除。
    """
    kw = f"{keyword} 矿业权" if keyword else "矿业权 出让"
    try:
        r = eastmoney_news.search(kw, days=days, limit=max(limit * 2, 20))
        items = [
            {
                "title": it["title"],
                "channel": it.get("media") or "媒体",
                "date": it.get("published", ""),
                "url": it.get("url", ""),
            }
            for it in r["items"]
            if any(t in it["title"] for t in _RIGHTS_TITLE_TERMS)
        ]
        return {
            "items": items[:limit],
            "total": len(items),
            "source": "real",
            "data_ts": datetime.now().isoformat(timespec="seconds"),
        }
    except Exception:  # noqa: BLE001
        return {"items": [], "total": 0, "source": "real", "data_ts": datetime.now().isoformat(timespec="seconds")}


@mcp.tool
def search_mining_rights(keyword: str = "", days: int = 30, limit: int = 10) -> dict:
    """搜索国内矿业权(探矿权/采矿权)出让、转让官方公示公告。

    降级链:官方公示(ky.mnr.gov.cn)→ 媒体矿权动态(东方财富,标题过滤)→ 内置样例(demo)。
    官方源可用但无匹配公告时,如实返回空结果+说明,不再用示例数据冒充。

    Args:
        keyword: 关键词(矿种或地名),如 "铜矿"、"锂"、"新疆"。空串返回全部最新公告。
        days: 只返回最近 N 天内的公告(公告日期按月归档,按 YYYY-MM 比较)。
        limit: 返回条数上限,默认 10。

    Returns:
        dict: {items: [{title, channel, date, url}], total, source, data_ts, note?}
        source="real" 为官方/媒体真实数据;"demo" 为内置样例兜底。
    """
    try:
        r = mnr_rights.search(keyword, days=days, limit=limit)
        if r["items"]:
            return r
        if not r.get("error"):
            # 官方源可用但无匹配公告:先试媒体备份,再如实返回空
            backup = _news_backup(keyword, days, limit)
            if backup["items"]:
                backup["note"] = "官方公示无匹配公告,以下为媒体矿权动态(真实,东方财富)"
                return backup
            return {**r, "note": "官方源今日无匹配公告(真实源可用)"}
        note = f"官方源不可用({r['error']})"
    except Exception as e:  # noqa: BLE001
        note = f"官方源不可用: {e}"

    # 官方源失败 → 媒体备份
    backup = _news_backup(keyword, days, limit)
    if backup["items"]:
        backup["note"] = f"{note},以下为媒体矿权动态(真实,东方财富)"
        return backup

    # 全部真实源失败 → 内置样例(有关键词时只返回标题命中的样例,避免无关内容)
    try:
        sample = load_sample("rights")["items"]
        filtered = [x for x in sample if not keyword or keyword in x["title"]]
        return {
            "items": filtered[:limit],
            "total": len(filtered),
            "source": "demo",
            "data_ts": datetime.now().isoformat(timespec="seconds"),
            "note": f"{note},返回内置样例数据(仅标题命中关键词)",
        }
    except Exception as e:  # noqa: BLE001
        return {
            "items": [],
            "total": 0,
            "source": "demo",
            "error": f"矿权公告获取失败: {note}; 样例缺失: {e}",
            "data_ts": datetime.now().isoformat(timespec="seconds"),
        }


if __name__ == "__main__":
    run_server(mcp, default_port=8104)
