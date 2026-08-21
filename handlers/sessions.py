"""Handler session — /session: performa per sesi trading (Asian/London/New York)."""

from __future__ import annotations

from datetime import datetime, timezone

import calc
import db
import formatters
from config import get_tz
from handlers.common import build_settings, check_allowed, extract_user_id
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import CommandHandler, ContextTypes

# Trading session boundaries (UTC hours)
SESSIONS = {
    "🌏 Asian": (0, 8),       # 00:00–08:00 UTC (Tokyo/Sydney)
    "🌍 London": (7, 16),     # 07:00–16:00 UTC
    "🌎 New York": (12, 21),  # 12:00–21:00 UTC
}


def detect_session(dt: datetime) -> str:
    """Deteksi sesi trading berdasarkan waktu UTC.
    Jam overlap (London+NY) dianggap New York karena lebih aktif."""
    utc = dt.astimezone(timezone.utc)
    hour = utc.hour
    # Cek dari yang paling spesifik ke umum
    if 12 <= hour < 16:
        return "🌎 New York + 🌍 London"  # overlap
    if 12 <= hour < 21:
        return "🌎 New York"
    if 7 <= hour < 16:
        return "🌍 London"
    if 0 <= hour < 8:
        return "🌏 Asian"
    return "🌙 Off-hours"


def _session_stats(trades: list[db.Trade], settings) -> dict[str, dict]:
    """Hitung statistik per sesi."""
    groups: dict[str, list[db.Trade]] = {}
    for t in trades:
        session = detect_session(t.open_time)
        groups.setdefault(session, []).append(t)

    result = {}
    for session_name, session_trades in sorted(groups.items()):
        wins = 0
        losses = 0
        net_pnl = 0.0
        net_pips = 0.0
        for t in session_trades:
            p = calc.pnl(t.pair, t.direction, t.entry, t.exit, t.lot, settings.usdjpy_rate)
            if p > 0:
                wins += 1
            elif p < 0:
                losses += 1
            net_pnl += p
            raw = (t.exit - t.entry) / calc.pip_size(t.pair)
            pips = raw if t.direction == "LONG" else -raw
            net_pips += pips
        total = wins + losses
        result[session_name] = {
            "trades": len(session_trades),
            "wins": wins,
            "losses": losses,
            "win_rate": (wins / total * 100) if total else 0,
            "net_pnl": round(net_pnl, 2),
            "net_pips": round(net_pips, 1),
        }
    return result


async def cmd_session(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await check_allowed(update, context):
        return
    uid = extract_user_id(update)
    s = build_settings(uid)

    with db.get_conn() as conn:
        trades = db.list_trades(conn, uid)

    if not trades:
        await update.effective_message.reply_text(
            "Belum ada trade. Tambahkan dengan /add atau /trade."
        )
        return

    stats = _session_stats(trades, s)

    lines = [
        "🕐 <b>Performa per Sesi Trading</b>",
        "",
    ]

    for session_name, st in stats.items():
        emoji = "🟢" if st["net_pnl"] > 0 else ("🔴" if st["net_pnl"] < 0 else "⚪")
        lines.append(f"<b>{session_name}</b>")
        lines.append(f"  {emoji} {st['trades']} trade | WR {st['win_rate']:.0f}% | "
                     f"{formatters.fmt_money(st['net_pnl'], s)} ({st['net_pips']:+.1f} pip)")
        lines.append("")

    # Best session
    if stats:
        best = max(stats.items(), key=lambda x: x[1]["net_pnl"])
        worst = min(stats.items(), key=lambda x: x[1]["net_pnl"])
        lines.append(f"🏆 Sesi terbaik: <b>{best[0]}</b> ({formatters.fmt_money(best[1]['net_pnl'], s)})")
        if worst[1]["net_pnl"] < 0:
            lines.append(f"⚠️ Sesi terlemah: <b>{worst[0]}</b> ({formatters.fmt_money(worst[1]['net_pnl'], s)})")

    # Current session
    now = datetime.now(timezone.utc)
    current = detect_session(now)
    lines.append(f"\n⏰ Sesi sekarang: <b>{current}</b>")

    await update.effective_message.reply_text(
        "\n".join(lines), parse_mode=ParseMode.HTML
    )


def handlers() -> list[object]:
    return [CommandHandler("session", cmd_session)]
