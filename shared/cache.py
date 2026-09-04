"""SQLite 缓存(标准库 sqlite3,零外部服务):
- kv 通用 TTL 缓存(新闻搜索结果、RSS、行情快照、矿权公告列表)
- price_snapshots:westmetall 每日官方结算价快照累积(LME 历史走势的数据来源)
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from typing import Any

from shared.config import CACHE_DIR

DB_PATH = CACHE_DIR / "cache.db"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

_local = threading.local()


def _conn() -> sqlite3.Connection:
    if not hasattr(_local, "conn"):
        _local.conn = sqlite3.connect(DB_PATH)
        _local.conn.execute("PRAGMA journal_mode=WAL")
    return _local.conn


def init_db() -> None:
    c = _conn()
    c.execute(
        """CREATE TABLE IF NOT EXISTS kv(
            key TEXT PRIMARY KEY, value TEXT, ts REAL)"""
    )
    c.execute(
        """CREATE TABLE IF NOT EXISTS price_snapshots(
            commodity TEXT, date TEXT, price REAL, unit TEXT, source TEXT,
            PRIMARY KEY(commodity, date))"""
    )
    c.commit()


def kv_get(key: str, ttl: float | None = None) -> Any | None:
    init_db()
    row = _conn().execute("SELECT value, ts FROM kv WHERE key=?", (key,)).fetchone()
    if not row:
        return None
    value, ts = row
    if ttl is not None and time.time() - ts > ttl:
        return None
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return None


def kv_set(key: str, value: Any) -> None:
    init_db()
    c = _conn()
    c.execute(
        "INSERT OR REPLACE INTO kv(key, value, ts) VALUES(?,?,?)",
        (key, json.dumps(value, ensure_ascii=False), time.time()),
    )
    c.commit()


def snapshot_add(commodity: str, date: str, price: float, unit: str, source: str) -> None:
    """累积一条价格快照(同日同品种覆盖,幂等)。"""
    init_db()
    c = _conn()
    c.execute(
        "INSERT OR REPLACE INTO price_snapshots(commodity, date, price, unit, source) "
        "VALUES(?,?,?,?,?)",
        (commodity, date, price, unit, source),
    )
    c.commit()


def snapshot_series(commodity: str, limit: int = 60) -> list[dict]:
    init_db()
    rows = _conn().execute(
        "SELECT date, price, unit, source FROM price_snapshots "
        "WHERE commodity=? ORDER BY date DESC LIMIT ?",
        (commodity, limit),
    ).fetchall()
    return [
        {"date": d, "price": p, "unit": u, "source": s} for d, p, u, s in reversed(rows)
    ]
