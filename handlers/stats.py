"""Handler statistik — /stats."""

from __future__ import annotations

from datetime import datetime, timezone

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import CommandHandler, ContextTypes

import calc
import db
import formatters
from config import get_tz
from handlers.common import build_settings, check_allowed, extract_user_id

_PERIOD_ALIASES = {
    "today": "today", "hari": "today", "harini": "today",
    "week": "week", "minggu": "week",
    "month": "month", "bulan": "month",
    "all": "all", "semua": "all",
}

_LABELS = {
    "today": "Hari Ini",
    "week": "Minggu Ini",
    "month": "Bulan Ini",
    "all": "Semua Waktu",
}


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await check_allowed(update, context):
        return
    uid = extract_user_id(update)
    s = build_settings(uid)
    arg = context.args[0] if context.args else "all"
    period = _PERIOD_ALIASES.get(arg.strip().lower(), "all")
    now = datetime.now(timezone.utc)
    with db.get_conn() as conn:
        if period == "all":
            trades = db.list_trades(conn, uid)
        else:
            start, end = calc.period_to_window(period, now, get_tz(s))
            trades = db.list_trades(conn, uid, start=start, end=end)
    agg = calc.aggregate(trades, s)
    label = _LABELS[period]
    text = formatters.fmt_stats(agg, label, s)
    if period == "today":
        warnings = calc.compute_daily_risk(agg, s)
        if warnings:
            text += "\n\n" + "\n".join(warnings)
    await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML)


def handlers() -> list[object]:
    return [CommandHandler("stats", cmd_stats)]
