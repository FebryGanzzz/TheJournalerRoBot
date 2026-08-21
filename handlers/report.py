"""Handler laporan & ekspor — /export, /report, /chart."""

from __future__ import annotations

import csv
import io
import logging
from datetime import datetime, timezone

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import CommandHandler, ContextTypes

import calc
import db
import formatters
import charts
from config import get_tz
from handlers.common import build_settings, check_allowed, extract_user_id

log = logging.getLogger(__name__)

CSV_COLUMNS = ["id", "pair", "direction", "entry", "exit", "lot", "stop_loss", "notes", "open_time", "pnl", "r"]


def _csv_bytes(trades: list, s) -> bytes:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(CSV_COLUMNS)
    for t in trades:
        p = calc.pnl(t.pair, t.direction, t.entry, t.exit, t.lot, s.usdjpy_rate)
        r = calc.r_multiple(t.pair, t.direction, t.entry, t.exit, t.lot, t.stop_loss, s.usdjpy_rate)
        dec = calc.decimal_places(t.pair)
        writer.writerow(
            [
                t.id, t.pair, t.direction,
                f"{t.entry:.{dec}f}", f"{t.exit:.{dec}f}", f"{t.lot:.2f}",
                "" if t.stop_loss is None else f"{t.stop_loss:.{dec}f}",
                t.notes, t.open_time.astimezone(get_tz(s)).strftime("%Y-%m-%d %H:%M:%S"),
                f"{p:.2f}", "" if r is None else f"{r:.2f}",
            ]
        )
    return out.getvalue().encode("utf-8")


async def cmd_export(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await check_allowed(update, context):
        return
    uid = extract_user_id(update)
    s = build_settings(uid)
    with db.get_conn() as conn:
        trades = db.list_trades(conn, uid)
    if not trades:
        await update.effective_message.reply_text(
            "Belum ada trade untuk diekspor."
        )
        return
    data = _csv_bytes(trades, s)
    filename = f"trading-journal-{datetime.now(timezone.utc).strftime('%Y%m%d')}.csv"
    await update.effective_message.reply_document(
        document=io.BytesIO(data),
        filename=filename,
        caption=f"📄 {len(trades)} trade diekspor ({filename})",
    )


async def cmd_report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await check_allowed(update, context):
        return
    uid = extract_user_id(update)
    s = build_settings(uid)
    arg = context.args[0].strip().lower() if context.args else "month"
    mapping = {
        "week": ("week", "Minggu Ini"), "minggu": ("week", "Minggu Ini"),
        "month": ("month", "Bulan Ini"), "bulan": ("month", "Bulan Ini"),
        "all": ("all", "Semua Waktu"),
    }
    period, label = mapping.get(arg, ("month", "Bulan Ini"))
    now = datetime.now(timezone.utc)
    with db.get_conn() as conn:
        if period == "all":
            trades = db.list_trades(conn, uid)
        else:
            start, end = calc.period_to_window(period, now, get_tz(s))
            trades = db.list_trades(conn, uid, start=start, end=end)
    if not trades:
        await update.effective_message.reply_text(
            f"Belum ada trade pada periode <b>{label}</b>."
        )
        return
    agg = calc.aggregate(trades, s)
    recent = trades[:5]
    await update.effective_message.reply_text(
        formatters.fmt_report_summary(agg, label, s, recent),
        parse_mode=ParseMode.HTML,
    )


async def cmd_chart(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await check_allowed(update, context):
        return
    uid = extract_user_id(update)
    s = build_settings(uid)
    with db.get_conn() as conn:
        trades = db.list_trades(conn, uid)
    if not trades:
        await update.effective_message.reply_text(
            "Belum ada trade untuk chart."
        )
        return
    png = charts.try_render_equity_chart(trades, s)
    if png is None:
        await update.effective_message.reply_text(
            "📉 Chart belum bisa dibuat — matplotlib belum terpasang."
        )
        return
    caption = (f"📈 Kurva Ekuitas ({len(trades)} trade)\n"
               f"P&L bersih: {formatters.fmt_money(calc.aggregate(trades, s)['net_pnl'], s)}")
    await update.effective_message.reply_photo(
        photo=io.BytesIO(png), caption=caption, parse_mode=ParseMode.HTML
    )


async def cmd_summary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Auto-generated daily summary with insights."""
    if not await check_allowed(update, context):
        return
    uid = extract_user_id(update)
    s = build_settings(uid)
    now = datetime.now(timezone.utc)
    tz = get_tz(s)

    with db.get_conn() as conn:
        # Today
        t_start, _ = calc.period_to_window("today", now, tz)
        today_trades = db.list_trades(conn, uid, start=t_start)
        # This week
        w_start, _ = calc.period_to_window("week", now, tz)
        week_trades = db.list_trades(conn, uid, start=w_start)
        # All time
        all_trades = db.list_trades(conn, uid)

    if not today_trades:
        local_now = now.astimezone(tz)
        await update.effective_message.reply_text(
            f"📋 <b>Ringkasan Hari Ini — {local_now.strftime('%d %b %Y')}</b>\n\n"
            "Belum ada trade hari ini."
        )
        return

    today_agg = calc.aggregate(today_trades, s)
    week_agg = calc.aggregate(week_trades, s)

    local_now = now.astimezone(tz)

    # Best & worst trade today
    best_today = max(today_trades, key=lambda t: calc.pnl(
        t.pair, t.direction, t.entry, t.exit, t.lot, s.usdjpy_rate))
    worst_today = min(today_trades, key=lambda t: calc.pnl(
        t.pair, t.direction, t.entry, t.exit, t.lot, s.usdjpy_rate))

    # Pairs traded today
    pairs_today = list(set(t.pair for t in today_trades))

    # Session distribution
    from handlers.sessions import detect_session
    session_counts: dict[str, int] = {}
    for t in today_trades:
        sess = detect_session(t.open_time)
        session_counts[sess] = session_counts.get(sess, 0) + 1
    top_session = max(session_counts, key=session_counts.get) if session_counts else "-"

    # Win streak today
    streak = 0
    streak_type = "-"
    for t in sorted(today_trades, key=lambda t: t.open_time):
        p = calc.pnl(t.pair, t.direction, t.entry, t.exit, t.lot, s.usdjpy_rate)
        t_type = "win" if p > 0 else "loss"
        if t_type == streak_type:
            streak += 1
        else:
            streak = 1
            streak_type = t_type

    lines = [
        f"📋 <b>Ringkasan Hari Ini — {local_now.strftime('%d %b %Y')}</b>",
        "",
        f"📊 {today_agg['trades']} trade | Win Rate: {today_agg['win_rate']:.0f}%",
        f"💰 P&L: {formatters.fmt_money(today_agg['net_pnl'], s)} ({today_agg['net_pips']:+.1f} pip)",
        "📈 Profit Factor: " + ("∞" if today_agg.get('profit_factor') is None else f"{today_agg['profit_factor']:.2f}"),
        "",
        f"🏆 Terbaik: #{best_today.id} {best_today.pair} → {formatters.fmt_money(calc.pnl(best_today.pair, best_today.direction, best_today.entry, best_today.exit, best_today.lot, s.usdjpy_rate), s)}",
        f"🐻 Terburuk: #{worst_today.id} {worst_today.pair} → {formatters.fmt_money(calc.pnl(worst_today.pair, worst_today.direction, worst_today.entry, worst_today.exit, worst_today.lot, s.usdjpy_rate), s)}",
        "",
        f"💱 Pair: {', '.join(pairs_today)}",
        f"🕐 Sesi dominan: {top_session}",
        f"🔥 Streak terakhir: {streak}x {streak_type.upper()}",
        "",
        f"📅 <b>Minggu ini:</b> {week_agg['trades']} trade | P&L: {formatters.fmt_money(week_agg['net_pnl'], s)}",
    ]

    # Risk warnings
    warnings = calc.compute_daily_risk(today_agg, s)
    if warnings:
        lines += [""] + warnings

    # Insights
    if today_agg["win_rate"] >= 70:
        lines.append("\n💡 <i>Win rate bagus hari ini! Pertahankan disiplin.</i>")
    elif today_agg["win_rate"] <= 30 and today_agg["trades"] >= 3:
        lines.append("\n⚠️ <i>Win rate rendah. Pertimbangkan istirahat.</i>")

    await update.effective_message.reply_text(
        "\n".join(lines), parse_mode=ParseMode.HTML
    )


def handlers() -> list[object]:
    return [
        CommandHandler("export", cmd_export),
        CommandHandler("report", cmd_report),
        CommandHandler("chart", cmd_chart),
        CommandHandler("summary", cmd_summary),
    ]
