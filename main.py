"""Trading Journal Bot + WebApp Server for Railway.

Runs both the Telegram Bot and aiohttp Web Server in the same asyncio event loop.
All logic lives in modular files — this file only wires them together.

Usage:
    python main.py           # direct run
    gunicorn main:app -k aiohttp.GunicornWebWorker  # production (Railway)
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

from aiohttp import web
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("tj")


# =====================================================================
# 1. WEB SERVER (hosting WebApp + JSON API)
# =====================================================================


async def api_stats(request: web.Request) -> web.Response:
    """Live stats endpoint — aggregate data across all users for WebApp."""
    from datetime import datetime, timezone

    import calc
    import db
    from config import get_tz
    from handlers.common import build_settings

    # WebApp tidak punya user_id, jadi kita aggregate semua user
    # (settings default dipakai untuk perhitungan)
    s = build_settings(0)
    now = datetime.now(timezone.utc)
    tz = get_tz(s)

    def _sub(agg: dict) -> dict:
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

    with db.get_conn() as conn:
        # Ambil semua trade (tanpa filter user_id) untuk WebApp global view
        all_t = _list_all_trades(conn)
        m_st, _ = calc.period_to_window("month", now, tz)
        w_st, _ = calc.period_to_window("week", now, tz)
        t_st, _ = calc.period_to_window("today", now, tz)
        m_t = [t for t in all_t if t.open_time >= m_st] if m_st else all_t
        w_t = [t for t in all_t if t.open_time >= w_st] if w_st else all_t
        today_t = [t for t in all_t if t.open_time >= t_st] if t_st else all_t

    payload = {
        "generated": now.astimezone(tz).isoformat(),
        "meta": {"currency": s.currency},
        "all": _sub(calc.aggregate(all_t, s)),
        "month": _sub(calc.aggregate(m_t, s)),
        "week": _sub(calc.aggregate(w_t, s)),
        "today": _sub(calc.aggregate(today_t, s)),
    }
    return web.json_response(payload, headers={"Access-Control-Allow-Origin": "*"})


async def api_settings(request: web.Request) -> web.Response:
    """Live settings endpoint for WebApp."""
    from handlers.common import build_settings

    s = build_settings(0)
    return web.json_response(
        {
            "balance": s.default_balance,
            "risk_percent": s.default_risk_percent,
            "currency": s.currency,
            "usdjpy_rate": s.usdjpy_rate,
        },
        headers={"Access-Control-Allow-Origin": "*"},
    )


async def api_trades(request: web.Request) -> web.Response:
    """Trade history endpoint for WebApp — returns last 50 trades."""
    import calc
    import db
    from handlers.common import build_settings
    from config import get_tz

    s = build_settings(0)
    tz = get_tz(s)

    with db.get_conn() as conn:
        trades = _list_all_trades(conn)[:50]

    def _t(t):
        p = calc.pnl(t.pair, t.direction, t.entry, t.exit, t.lot, s.usdjpy_rate)
        r = calc.r_multiple(t.pair, t.direction, t.entry, t.exit, t.lot, t.stop_loss, s.usdjpy_rate)
        raw = (t.exit - t.entry) / calc.pip_size(t.pair)
        pips = raw if t.direction == "LONG" else -raw
        return {
            "id": t.id, "pair": t.pair, "dir": t.direction,
            "entry": t.entry, "exit": t.exit, "lot": t.lot,
            "sl": t.stop_loss, "notes": t.notes, "tags": t.tags or "",
            "pnl": round(p, 2), "pips": round(pips, 1),
            "r": round(r, 2) if r is not None else None,
            "time": t.open_time.astimezone(tz).strftime("%d %b %H:%M"),
        }

    return web.json_response(
        {"trades": [_t(t) for t in trades], "currency": s.currency},
        headers={"Access-Control-Allow-Origin": "*"},
    )


async def health(request: web.Request) -> web.Response:
    return web.Response(text="OK — Trading Journal Bot is running.")


def _list_all_trades(conn) -> list:
    """Helper: list ALL trades (all users) for WebApp global stats."""
    cur = conn.execute("SELECT * FROM trades ORDER BY open_time DESC, id DESC")
    from db import _row_to_trade
    return [_row_to_trade(r) for r in cur.fetchall()]


def create_web_app(webapp_dir: Path) -> web.Application:
    """Build the aiohttp application: API routes + static file serving."""
    app = web.Application()
    # API routes
    app.router.add_get("/api/stats", api_stats)
    app.router.add_get("/stats.json", api_stats)
    app.router.add_get("/api/settings", api_settings)
    app.router.add_get("/settings.json", api_settings)
    app.router.add_get("/api/trades", api_trades)
    app.router.add_get("/trades.json", api_trades)
    app.router.add_get("/health", health)
    # Static webapp files
    if webapp_dir.exists():
        app.router.add_static("/", path=str(webapp_dir), show_index=True)
    return app


# =====================================================================
# 2. TELEGRAM BOT
# =====================================================================


def build_bot_application(token: str):
    """Build the python-telegram-bot Application with all handlers."""
    from telegram import MenuButtonWebApp, WebAppInfo
    from telegram.constants import ParseMode
    from telegram.ext import Application, Defaults

    import handlers
    from config import load_settings

    async def post_init(application: Application) -> None:
        s = load_settings()
        if not s.webapp_url:
            return
        try:
            button = MenuButtonWebApp(text="📒 Journal", web_app=WebAppInfo(url=s.webapp_url))
            await application.bot.set_chat_menu_button(menu_button=button)
            log.info("Menu WebApp diaktifkan: %s", s.webapp_url)
        except Exception:
            log.warning("Gagal mengeset chat menu button.")

    app = (
        Application.builder()
        .token(token)
        .defaults(Defaults(parse_mode=ParseMode.HTML))
        .post_init(post_init)
        .build()
    )

    for handler in handlers.all_handlers():
        app.add_handler(handler)

    return app


# =====================================================================
# 3. MAIN
# =====================================================================


async def _run_forever() -> None:
    import db
    from config import load_settings

    settings = load_settings()

    if not settings.bot_token:
        log.error("BOT_TOKEN tidak ditemukan!")
        sys.exit(1)

    db.init_db()

    webapp_dir = Path(__file__).parent / "webapp"
    web_app = create_web_app(webapp_dir)
    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=settings.port)
    await site.start()
    log.info("HTTP server aktif di port %s", settings.port)

    bot_app = build_bot_application(settings.bot_token)
    await bot_app.initialize()
    await bot_app.start()
    await bot_app.updater.start_polling(allowed_updates=["message", "callback_query"], poll_interval=1.0)
    log.info("Telegram bot aktif — siap menerima pesan.")

    stop_event = asyncio.Event()
    try:
        await stop_event.wait()
    except (asyncio.CancelledError, KeyboardInterrupt):
        pass
    finally:
        log.info("Mematikan bot dan web server...")
        await bot_app.updater.stop()
        await bot_app.stop()
        await bot_app.shutdown()
        await runner.cleanup()
        log.info("Selesai.")


def main() -> None:
    try:
        asyncio.run(_run_forever())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
