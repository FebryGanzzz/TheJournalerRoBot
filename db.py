"""Lapisan data: PostgreSQL via psycopg2 (or SQLite fallback).

DATABASE_URL env var diutamakan. Bila tidak ada, fallback ke SQLite.
Setiap user Telegram punya data sendiri (trades & settings).
"""

from __future__ import annotations

import logging
import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

log = logging.getLogger(__name__)

# =====================================================================
# Detect backend: PostgreSQL or SQLite
# =====================================================================

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
USE_POSTGRES = bool(DATABASE_URL)

SCHEMA_VERSION = 3
_TIME_FMT = "%Y-%m-%d %H:%M:%S"

EDITABLE_COLUMNS = frozenset(
    {"pair", "direction", "entry", "exit", "lot", "stop_loss", "notes", "tags"}
)


@dataclass
class Trade:
    id: int | None = None
    user_id: int = 0
    pair: str = ""
    direction: str = "LONG"
    entry: float = 0.0
    exit: float = 0.0
    lot: float = 0.0
    stop_loss: float | None = None
    notes: str = ""
    tags: str = ""
    open_time: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


# =====================================================================
# PostgreSQL backend
# =====================================================================

_pg_pool = None

if USE_POSTGRES:
    import psycopg2
    import psycopg2.extras
    import psycopg2.pool

    class Conn:
        def __init__(self, raw):
            self._raw = raw

        def execute(self, sql: str, params: tuple | list = ()):
            cur = self._raw.cursor()
            cur.execute(sql, params)
            return cur

        @property
        def raw(self):
            return self._raw

    def _get_pool():
        global _pg_pool
        if _pg_pool is not None:
            return _pg_pool

        dsn = DATABASE_URL
        if dsn.startswith("postgres://"):
            dsn = dsn.replace("postgres://", "postgresql://", 1)

        log.info("Menghubungkan ke PostgreSQL...")
        _pg_pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=1, maxconn=10, dsn=dsn,
            cursor_factory=psycopg2.extras.RealDictCursor,
            connect_timeout=10, options="-c statement_timeout=30000",
        )
        log.info("Koneksi PostgreSQL berhasil.")
        return _pg_pool

    @contextmanager
    def get_conn() -> Iterator[Conn]:
        pool = _get_pool()
        raw = pool.getconn()
        raw.autocommit = False
        conn = Conn(raw)
        try:
            yield conn
            raw.commit()
        except Exception:
            raw.rollback()
            raise
        finally:
            pool.putconn(raw)

else:
    # SQLite fallback
    DB_PATH = Path(__file__).parent / "bot.db"

    class Conn:
        def __init__(self, raw: sqlite3.Connection):
            self._raw = raw

        def execute(self, sql: str, params: tuple | list = ()):
            return self._raw.execute(sql, params)

        @property
        def raw(self):
            return self._raw

    @contextmanager
    def get_conn() -> Iterator[Conn]:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        wrapper = Conn(conn)
        try:
            yield wrapper
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


# =====================================================================
# Skema
# =====================================================================

_SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS trades (
    id          SERIAL PRIMARY KEY,
    pair        VARCHAR(6) NOT NULL,
    direction   VARCHAR(5) NOT NULL CHECK (direction IN ('LONG','SHORT')),
    entry       DOUBLE PRECISION NOT NULL,
    exit        DOUBLE PRECISION NOT NULL,
    lot         DOUBLE PRECISION NOT NULL,
    stop_loss   DOUBLE PRECISION,
    notes       TEXT,
    tags        TEXT NOT NULL DEFAULT '',
    open_time   TEXT NOT NULL,
    user_id     BIGINT NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_trades_open_time ON trades(open_time);
CREATE INDEX IF NOT EXISTS idx_trades_pair      ON trades(pair);
CREATE INDEX IF NOT EXISTS idx_trades_user_id   ON trades(user_id);
CREATE INDEX IF NOT EXISTS idx_trades_user_time ON trades(user_id, open_time);

CREATE TABLE IF NOT EXISTS settings (
    key     VARCHAR(64) NOT NULL,
    value   TEXT NOT NULL,
    user_id BIGINT NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, key)
);

CREATE TABLE IF NOT EXISTS _meta (
    key   VARCHAR(64) PRIMARY KEY,
    value TEXT NOT NULL
);
"""

_SQLITE_SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS trades (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL DEFAULT 0,
    pair        TEXT NOT NULL,
    direction   TEXT NOT NULL CHECK (direction IN ('LONG','SHORT')),
    entry       REAL NOT NULL,
    exit        REAL NOT NULL,
    lot         REAL NOT NULL,
    stop_loss   REAL,
    notes       TEXT,
    tags        TEXT NOT NULL DEFAULT '',
    open_time   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_trades_open_time ON trades(open_time);
CREATE INDEX IF NOT EXISTS idx_trades_pair      ON trades(pair);
CREATE INDEX IF NOT EXISTS idx_trades_user_id   ON trades(user_id);

CREATE TABLE IF NOT EXISTS settings (
    user_id INTEGER NOT NULL DEFAULT 0,
    key     TEXT NOT NULL,
    value   TEXT NOT NULL,
    PRIMARY KEY (user_id, key)
);

CREATE TABLE IF NOT EXISTS _meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def init_db() -> None:
    """Buat skema bila belum ada."""
    with get_conn() as conn:
        if USE_POSTGRES:
            conn.execute(_SCHEMA_V1)
        else:
            conn.raw.executescript(_SQLITE_SCHEMA_V1)
        log.info("Database siap (%s)", "PostgreSQL" if USE_POSTGRES else "SQLite")


# =====================================================================
# Helpers
# =====================================================================


def _to_str(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime(_TIME_FMT)


def _to_dt(raw: str) -> datetime:
    return datetime.strptime(raw, _TIME_FMT).replace(tzinfo=timezone.utc)


def _row_to_trade(row) -> Trade:
    d = dict(row) if not isinstance(row, dict) else row
    return Trade(
        id=d["id"],
        user_id=d["user_id"],
        pair=d["pair"],
        direction=d["direction"],
        entry=d["entry"],
        exit=d["exit"],
        lot=d["lot"],
        stop_loss=d["stop_loss"],
        notes=d.get("notes") or "",
        tags=d.get("tags") or "",
        open_time=_to_dt(d["open_time"]),
    )


# =====================================================================
# Trades CRUD (per-user)
# =====================================================================


def insert_trade(conn: Conn, trade: Trade) -> int:
    cur = conn.execute(
        """INSERT INTO trades (user_id, pair, direction, entry, exit, lot, stop_loss, notes, tags, open_time)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""" if not USE_POSTGRES else
        """INSERT INTO trades (user_id, pair, direction, entry, exit, lot, stop_loss, notes, tags, open_time)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
           RETURNING id""",
        (
            trade.user_id, trade.pair, trade.direction,
            trade.entry, trade.exit, trade.lot,
            trade.stop_loss, trade.notes or None,
            trade.tags or "", _to_str(trade.open_time),
        ),
    )
    if USE_POSTGRES:
        return cur.fetchone()["id"]
    return cur.lastrowid


def get_trade(conn: Conn, trade_id: int, user_id: int) -> Trade | None:
    ph = "%s" if USE_POSTGRES else "?"
    cur = conn.execute(
        f"SELECT * FROM trades WHERE id = {ph} AND user_id = {ph}",
        (trade_id, user_id),
    )
    row = cur.fetchone()
    return _row_to_trade(row) if row else None


def list_trades(
    conn: Conn, user_id: int, *,
    start: datetime | None = None,
    end: datetime | None = None,
    pair: str | None = None,
) -> list[Trade]:
    ph = "%s" if USE_POSTGRES else "?"
    where: list[str] = [f"user_id = {ph}"]
    params: list[object] = [user_id]
    if start is not None:
        where.append(f"open_time >= {ph}")
        params.append(_to_str(start))
    if end is not None:
        where.append(f"open_time <= {ph}")
        params.append(_to_str(end))
    if pair is not None:
        where.append(f"pair = {ph}")
        params.append(pair)
    sql = "SELECT * FROM trades"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY open_time DESC, id DESC"
    cur = conn.execute(sql, params)
    return [_row_to_trade(r) for r in cur.fetchall()]


def list_trades_by_tag(conn: Conn, user_id: int, tag: str) -> list[Trade]:
    ph = "%s" if USE_POSTGRES else "?"
    like_op = "ILIKE" if USE_POSTGRES else "LIKE"
    cur = conn.execute(
        f"SELECT * FROM trades WHERE user_id = {ph} AND tags {like_op} {ph} ORDER BY open_time DESC",
        (user_id, f"%{tag}%"),
    )
    return [_row_to_trade(r) for r in cur.fetchall()]


def count_trades(
    conn: Conn, user_id: int, *,
    start: datetime | None = None,
    end: datetime | None = None,
) -> int:
    ph = "%s" if USE_POSTGRES else "?"
    where: list[str] = [f"user_id = {ph}"]
    params: list[object] = [user_id]
    if start is not None:
        where.append(f"open_time >= {ph}")
        params.append(_to_str(start))
    if end is not None:
        where.append(f"open_time <= {ph}")
        params.append(_to_str(end))
    sql = f"SELECT COUNT(*) AS cnt FROM trades"
    if where:
        sql += " WHERE " + " AND ".join(where)
    cur = conn.execute(sql, params)
    row = cur.fetchone()
    return row["cnt"] if isinstance(row, dict) else row[0]


def update_trade_fields(
    conn: Conn, trade_id: int, user_id: int, fields: dict[str, object]
) -> None:
    allowed = {k: v for k, v in fields.items() if k in EDITABLE_COLUMNS}
    if not allowed:
        return
    ph = "%s" if USE_POSTGRES else "?"
    sets = ", ".join(f"{k} = {ph}" for k in allowed)
    conn.execute(
        f"UPDATE trades SET {sets} WHERE id = {ph} AND user_id = {ph}",
        (*allowed.values(), trade_id, user_id),
    )


def delete_trade(conn: Conn, trade_id: int, user_id: int) -> bool:
    ph = "%s" if USE_POSTGRES else "?"
    cur = conn.execute(
        f"DELETE FROM trades WHERE id = {ph} AND user_id = {ph}",
        (trade_id, user_id),
    )
    return cur.rowcount > 0


# =====================================================================
# Settings CRUD (per-user)
# =====================================================================


def get_setting(conn: Conn, user_id: int, key: str, default: str | None = None) -> str | None:
    ph = "%s" if USE_POSTGRES else "?"
    cur = conn.execute(
        f"SELECT value FROM settings WHERE user_id = {ph} AND key = {ph}",
        (user_id, key),
    )
    row = cur.fetchone()
    if row is None:
        return default
    return row["value"] if isinstance(row, dict) else row[0]


def set_setting(conn: Conn, user_id: int, key: str, value: str) -> None:
    if USE_POSTGRES:
        conn.execute(
            "INSERT INTO settings (user_id, key, value) VALUES (%s, %s, %s) "
            "ON CONFLICT (user_id, key) DO UPDATE SET value = EXCLUDED.value",
            (user_id, key, value),
        )
    else:
        conn.execute(
            "INSERT OR REPLACE INTO settings (user_id, key, value) VALUES (?, ?, ?)",
            (user_id, key, value),
        )


def get_settings_dict(conn: Conn, user_id: int) -> dict[str, str]:
    ph = "%s" if USE_POSTGRES else "?"
    cur = conn.execute(
        f"SELECT key, value FROM settings WHERE user_id = {ph}",
        (user_id,),
    )
    return {r["key"]: r["value"] for r in cur.fetchall()}
