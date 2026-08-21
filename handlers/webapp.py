"""Handler Telegram Mini App (WebApp) — terima hasil form sentuh, simpan trade."""

from __future__ import annotations

import json
import logging

from telegram import Update
from telegram.ext import ContextTypes, MessageHandler
from telegram.ext.filters import StatusUpdate

import db
import formatters
from handlers.common import TradeDataError, build_settings, build_trade_from_dict, check_allowed, extract_user_id

log = logging.getLogger(__name__)


async def webapp_data(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await check_allowed(update, context):
        return
    uid = extract_user_id(update)
    msg = update.effective_message
    data = update.effective_message.web_app_data
    if data is None:
        return

    try:
        payload = json.loads(data.data)
    except (json.JSONDecodeError, TypeError):
        await msg.reply_text("❌ Data webapp tidak valid (bukan JSON).")
        return

    action = str(payload.get("action", "")).strip()
    if action != "add_trade":
        await msg.reply_text(f"❌ Aksi webapp tidak dikenal: <code>{action}</code>")
        return

    s = build_settings(uid)
    try:
        trade = build_trade_from_dict(payload, user_id=uid)
        with db.get_conn() as conn:
            tid = db.insert_trade(conn, trade)
            trade.id = tid
    except TradeDataError as exc:
        await msg.reply_text(f"❌ {exc}")
        return

    await msg.reply_text(
        f"✅ <b>Trade dari webapp tersimpan</b> sebagai #{tid}.\n\n"
        + formatters.fmt_trade_card(trade, s),
        parse_mode="HTML",
    )


def handlers() -> list[object]:
    return [
        MessageHandler(StatusUpdate.WEB_APP_DATA, webapp_data),
    ]
