"""mining-rights-mcp —— 矿权公示(第 4 个 server,题目要求"至少 3 个")。

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
from shared.sources import mnr_rights
from shared.sources.simulate import load_sample

mcp = FastMCP("mining-rights-mcp")


@mcp.tool
def search_mining_rights(keyword: str = "", days: int = 30, limit: int = 10) -> dict:
    """搜索国内矿业权(探矿权/采矿权)出让、转让官方公示公告(来源:自然资源部矿业权市场)。

    Args:
        keyword: 关键词(矿种或地名),如 "铜矿"、"锂"、"新疆"。空串返回全部最新公告。
        days: 只返回最近 N 天内的公告(公告日期按月归档,按 YYYY-MM 比较)。
        limit: 返回条数上限,默认 10。

    Returns:
        dict: {items: [{title, channel, date, url}], total, source, data_ts}
        source="real" 为官方真实数据;"demo" 为内置样例兜底。
    """
    try:
        r = mnr_rights.search(keyword, days=days, limit=limit)
        if r["items"]:
            return r
        note = "官方源无匹配公告"
    except Exception as e:  # noqa: BLE001
        note = f"官方源不可用: {e}"

    # 兜底:内置样例(有关键词时只返回标题命中的样例,避免无关内容)
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
