"""Lapisan data: PostgreSQL via psycopg2, skema, helper CRUD.

Setiap user Telegram punya data sendiri (trades & settings).
user_id dari Telegram dijadikan foreign key di semua tabel.

DATABASE_URL env var wajib diisi. Contoh:
    postgres://user:pass@host:port/dbname?sslmode=require
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterator

import psycopg2
import psycopg2.extras
import psycopg2.pool

log = logging.getLogger(__name__)

# =====================================================================
# Connection wrapper
# =====================================================================

SCHEMA_VERSION = 3  # v3: tambah tags
_TIME_FMT = "%Y-%m-%d %H:%M:%S"

EDITABLE_COLUMNS = frozenset(
    {"pair", "direction", "entry", "exit", "lot", "stop_loss", "notes", "tags"}
)


class Conn:
    def __init__(self, raw: psycopg2.extensions.connection) -> None:
        self._raw = raw

    def execute(self, sql: str, params: tuple | list = ()) -> psycopg2.extensions.cursor:
        cur = self._raw.cursor()
        cur.execute(sql, params)
        return cur

    @property
    def raw(self) -> psycopg2.extensions.connection:
        return self._raw


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
    tags: str = ""  # comma-separated: "breakout,scalping,london"
    open_time: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


# =====================================================================
# Connection pool
# =====================================================================

_pool: psycopg2.pool.ThreadedConnectionPool | None = None


def _get_pool() -> psycopg2.pool.ThreadedConnectionPool:
    global _pool
    if _pool is not None:
        return _pool

    dsn = os.getenv("DATABASE_URL", "").strip()
    if not dsn:
        raise RuntimeError("DATABASE_URL tidak ditemukan!")

    if dsn.startswith("postgres://"):
        dsn = dsn.replace("postgres://", "postgresql://", 1)

    log.info("Menghubungkan ke PostgreSQL...")
    _pool = psycopg2.pool.ThreadedConnectionPool(
        minconn=1, maxconn=10, dsn=dsn,
        cursor_factory=psycopg2.extras.RealDictCursor,
        connect_timeout=10, options="-c statement_timeout=30000",
    )
    log.info("Koneksi PostgreSQL berhasil.")
    return _pool


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
    open_time   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_trades_open_time ON trades(open_time);
CREATE INDEX IF NOT EXISTS idx_trades_pair      ON trades(pair);

CREATE TABLE IF NOT EXISTS settings (
    key   VARCHAR(64) PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS _meta (
    key   VARCHAR(64) PRIMARY KEY,
    value TEXT NOT NULL
);
"""

_MIGRATE_V2 = """
ALTER TABLE trades ADD COLUMN IF NOT EXISTS user_id BIGINT NOT NULL DEFAULT 0;
CREATE INDEX IF NOT EXISTS idx_trades_user_id ON trades(user_id);
CREATE INDEX IF NOT EXISTS idx_trades_user_time ON trades(user_id, open_time);

ALTER TABLE settings DROP CONSTRAINT IF EXISTS settings_pkey;
ALTER TABLE settings ADD COLUMN IF NOT EXISTS user_id BIGINT NOT NULL DEFAULT 0;
ALTER TABLE settings ADD PRIMARY KEY (user_id, key);
"""

_MIGRATE_V3 = """
-- Tags: comma-separated labels per trade
ALTER TABLE trades ADD COLUMN IF NOT EXISTS tags TEXT NOT NULL DEFAULT '';
"""


def init_db() -> None:
    with get_conn() as conn:
        conn.execute(_SCHEMA_V1)

        cur = conn.execute("SELECT value FROM _meta WHERE key = 'schema_version'")
        row = cur.fetchone()
        version = int(row["value"]) if row else 0

        if version < 1:
            conn.execute(
                "INSERT INTO _meta (key, value) VALUES ('schema_version', '1') "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
            )
            log.info("Database skema v1 siap")

        if version < 2:
            conn.execute(_MIGRATE_V2)
            conn.execute(
                "INSERT INTO _meta (key, value) VALUES ('schema_version', '2') "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
            )
            log.info("Database upgraded to v2 (per-user data)")

        if version < 3:
            conn.execute(_MIGRATE_V3)
            conn.execute(
                "INSERT INTO _meta (key, value) VALUES ('schema_version', '3') "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
            )
            log.info("Database upgraded to v3 (tags)")


# =====================================================================
# Helpers
# =====================================================================


def _to_str(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime(_TIME_FMT)


def _to_dt(raw: str) -> datetime:
    return datetime.strptime(raw, _TIME_FMT).replace(tzinfo=timezone.utc)


def _row_to_trade(row: dict) -> Trade:
    return Trade(
        id=row["id"],
        user_id=row["user_id"],
        pair=row["pair"],
        direction=row["direction"],
        entry=row["entry"],
        exit=row["exit"],
        lot=row["lot"],
        stop_loss=row["stop_loss"],
        notes=row["notes"] or "",
        tags=row.get("tags", "") or "",
        open_time=_to_dt(row["open_time"]),
    )


# =====================================================================
# Trades CRUD (per-user)
# =====================================================================


def insert_trade(conn: Conn, trade: Trade) -> int:
    cur = conn.execute(
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
    return cur.fetchone()["id"]


def get_trade(conn: Conn, trade_id: int, user_id: int) -> Trade | None:
    cur = conn.execute(
        "SELECT * FROM trades WHERE id = %s AND user_id = %s",
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
    where: list[str] = ["user_id = %s"]
    params: list[object] = [user_id]
    if start is not None:
        where.append("open_time >= %s")
        params.append(_to_str(start))
    if end is not None:
        where.append("open_time <= %s")
        params.append(_to_str(end))
    if pair is not None:
        where.append("pair = %s")
        params.append(pair)
    sql = "SELECT * FROM trades"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY open_time DESC, id DESC"
    cur = conn.execute(sql, params)
    return [_row_to_trade(r) for r in cur.fetchall()]


def list_trades_by_tag(conn: Conn, user_id: int, tag: str) -> list[Trade]:
    cur = conn.execute(
        "SELECT * FROM trades WHERE user_id = %s AND tags ILIKE %s ORDER BY open_time DESC",
        (user_id, f"%{tag}%"),
    )
    return [_row_to_trade(r) for r in cur.fetchall()]


def count_trades(
    conn: Conn, user_id: int, *,
    start: datetime | None = None,
    end: datetime | None = None,
) -> int:
    where: list[str] = ["user_id = %s"]
    params: list[object] = [user_id]
    if start is not None:
        where.append("open_time >= %s")
        params.append(_to_str(start))
    if end is not None:
        where.append("open_time <= %s")
        params.append(_to_str(end))
    sql = "SELECT COUNT(*) AS cnt FROM trades"
    if where:
        sql += " WHERE " + " AND ".join(where)
    cur = conn.execute(sql, params)
    return cur.fetchone()["cnt"]


def update_trade_fields(
    conn: Conn, trade_id: int, user_id: int, fields: dict[str, object]
) -> None:
    allowed = {k: v for k, v in fields.items() if k in EDITABLE_COLUMNS}
    if not allowed:
        return
    sets = ", ".join(f"{k} = %s" for k in allowed)
    conn.execute(
        f"UPDATE trades SET {sets} WHERE id = %s AND user_id = %s",
        (*allowed.values(), trade_id, user_id),
    )


def delete_trade(conn: Conn, trade_id: int, user_id: int) -> bool:
    cur = conn.execute(
        "DELETE FROM trades WHERE id = %s AND user_id = %s",
        (trade_id, user_id),
    )
    return cur.rowcount > 0


# =====================================================================
# Settings CRUD (per-user)
# =====================================================================


def get_setting(conn: Conn, user_id: int, key: str, default: str | None = None) -> str | None:
    cur = conn.execute(
        "SELECT value FROM settings WHERE user_id = %s AND key = %s",
        (user_id, key),
    )
    row = cur.fetchone()
    return row["value"] if row else default


def set_setting(conn: Conn, user_id: int, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO settings (user_id, key, value) VALUES (%s, %s, %s) "
        "ON CONFLICT (user_id, key) DO UPDATE SET value = EXCLUDED.value",
        (user_id, key, value),
    )


def get_settings_dict(conn: Conn, user_id: int) -> dict[str, str]:
    cur = conn.execute(
        "SELECT key, value FROM settings WHERE user_id = %s",
        (user_id,),
    )
    return {r["key"]: r["value"] for r in cur.fetchall()}
