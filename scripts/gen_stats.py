"""Generator snapshot statistik untuk webapp (webapp/stats.json).

Jalankan dari root proyek:
    python3 -m scripts.gen_stats > webapp/stats.json

Menghasilkan JSON dengan bucket per periode:"all", "month", "week", "today"
plus meta (currency). Webapp membaca file ini untuk beranda & statistik.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

sys.path.insert(0, ".")  # pastikan import modul proyek

import calc
import db
from config import get_tz
from handlers.common import build_settings


def _sub(agg: dict) -> dict:
    """Subset agregat yang ringkas untuk webapp."""
    return {
        "trades": agg["trades"],
        "wins": agg["wins"],
        "losses": agg["losses"],
        "win_rate": round(agg["win_rate"], 1) if agg["trades"] else 0.0,
        "net_pnl": round(agg["net_pnl"], 2),
        "net_pips": round(agg["net_pips"], 1),
        "profit_factor": round(agg["profit_factor"], 2) if agg["profit_factor"] else None,
        "avg_r": agg["avg_r"],
        "by_pair": {
            k: {"net_pnl": round(v["net_pnl"], 2), "trades": v["trades"]}
            for k, v in agg["by_pair"].items()
        },
    }


def main() -> None:
    db.init_db()
    s = build_settings()
    now = datetime.now(timezone.utc)
    with db.get_conn() as conn:
        all_trades = db.list_trades(conn)
        month_trades = db.list_trades(
            conn, **{"start": calc.period_to_window("month", now, get_tz(s))[0]}
        )
        week_trades = db.list_trades(
            conn, **{"start": calc.period_to_window("week", now, get_tz(s))[0]}
        )
        today_trades = db.list_trades(
            conn, **{"start": calc.period_to_window("today", now, get_tz(s))[0]}
        )

    payload = {
        "generated": now.astimezone(get_tz(s)).isoformat(),
        "meta": {"currency": s.currency},
        "all": _sub(calc.aggregate(all_trades, s)),
        "month": _sub(calc.aggregate(month_trades, s)),
        "week": _sub(calc.aggregate(week_trades, s)),
        "today": _sub(calc.aggregate(today_trades, s)),
    }
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()