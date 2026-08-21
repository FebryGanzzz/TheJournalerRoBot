"""Panel sapa — tombol sentuh untuk mulai/melihat data tanpa mengetik perintah."""

from __future__ import annotations

import logging
from io import BytesIO

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    MenuButtonWebApp,
    Update,
    WebAppInfo,
)
from telegram.constants import ParseMode
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes

import calc
import charts
import db
import formatters
from config import load_settings
from handlers.common import build_settings, check_allowed, extract_user_id
from handlers.report import _csv_bytes

log = logging.getLogger(__name__)

PANEL_CMD = "panel"


def _panel_kb(webapp_url: str) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton("📊 Statistik", callback_data=f"{PANEL_CMD}:stats"),
            InlineKeyboardButton("📒 Riwayat", callback_data=f"{PANEL_CMD}:list"),
        ],
        [
            InlineKeyboardButton("📈 Chart", callback_data=f"{PANEL_CMD}:chart"),
            InlineKeyboardButton("📤 Export CSV", callback_data=f"{PANEL_CMD}:export"),
        ],
    ]
    if webapp_url:
        rows.append([InlineKeyboardButton("🌐 Buka Aplikasi", web_app=WebAppInfo(url=webapp_url))])
    rows.append([InlineKeyboardButton("⚙️ Pengaturan", callback_data=f"{PANEL_CMD}:settings")])
    return InlineKeyboardMarkup(rows)


async def send_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = extract_user_id(update)
    s = build_settings(uid)
    text = (
        "👋 <b>Trading Journal</b>\n"
        "Semua bisa dikerjakan dari sini — tanpa perlu mengetik perintah.\n\n"
        "🗂️ <b>Pilih aksi:</b>"
    )
    kb = _panel_kb(s.webapp_url)
    await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)


async def cmd_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await check_allowed(update, context):
        return
    await send_panel(update, context)


async def set_panel_menu(application) -> None:
    settings = load_settings()
    if not settings.webapp_url:
        return
    try:
        button = MenuButtonWebApp(
            text="📒 Journal",
            web_app=WebAppInfo(url=settings.webapp_url),
        )
        for chat_id in (None,):
            await application.bot.set_chat_menu_button(chat_id=chat_id, menu_button=button)
        log.info("Menu webapp diset: %s", settings.webapp_url)
    except Exception:
        log.warning("Gagal set chat menu button (butuh izin / mungkin bot tanpa percakapan).")


async def panel_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = extract_user_id(update)
    q = update.callback_query
    await q.answer()
    data: str = q.data
    if not data.startswith(f"{PANEL_CMD}:"):
        return
    action = data.split(":", 1)[1]
    s = build_settings(uid)

    if action == "stats":
        with db.get_conn() as conn:
            trades = db.list_trades(conn, uid)
        if not trades:
            await q.edit_message_text(
                "Belum ada trade. Tambahkan lewat tombol 🌐 Buka Aplikasi, "
                "/add, atau /trade."
            )
            return
        agg = calc.aggregate(trades, s)
        label = "Semua Waktu"
        text = formatters.fmt_stats(agg, label, s)
        warnings = calc.compute_daily_risk(agg, s)
        if warnings:
            text += "\n\n" + "\n".join(warnings)
        await q.edit_message_text(text, parse_mode=ParseMode.HTML)

    elif action == "list":
        with db.get_conn() as conn:
            trades = db.list_trades(conn, uid)
        if not trades:
            await q.edit_message_text("Belum ada trade.")
            return
        recent = trades[:10]
        text = f"📒 <b>10 Trade Terakhir</b>\n\n" + formatters.fmt_trade_list(recent, s)
        text += "\n\nLihat lengkap: <code>/list</code> · detail: <code>/detail &lt;id&gt;</code>"
        await q.edit_message_text(text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

    elif action == "chart":
        with db.get_conn() as conn:
            trades = db.list_trades(conn, uid)
        if not trades:
            await q.edit_message_text("Belum ada trade untuk chart.")
            return
        png = charts.try_render_equity_chart(trades, s)
        if png is None:
            await q.edit_message_text(
                "📉 Chart belum tersedia — matplotlib belum terpasang."
            )
            return
        agg = calc.aggregate(trades, s)
        caption = f"📈 Kurva Ekuitas ({len(trades)} trade)\nP&L: {formatters.fmt_money(agg['net_pnl'], s)}"
        await q.edit_message_caption(
            caption=caption,
            parse_mode=ParseMode.HTML,
            photo=BytesIO(png),
        )

    elif action == "export":
        with db.get_conn() as conn:
            trades = db.list_trades(conn, uid)
        if not trades:
            await q.edit_message_text("Belum ada trade untuk diekspor.")
            return
        data = _csv_bytes(trades, s)
        await q.edit_message_text("📤 Mengirim file CSV…")
        await q.message.reply_document(
            document=BytesIO(data),
            filename="trading-journal.csv",
            caption=f"{len(trades)} trade — Trading Journal",
        )

    elif action == "settings":
        await q.edit_message_text(
            formatters.fmt_settings(s) + "\n\nUbah: <code>/settings set &lt;key&gt; &lt;value&gt;</code>",
            parse_mode=ParseMode.HTML,
        )

    else:
        await q.edit_message_text("Aksi tidak dikenal.")


def handlers() -> list[object]:
    return [
        CommandHandler("panel", cmd_panel),
        CallbackQueryHandler(panel_cb, pattern=f"^{PANEL_CMD}:"),
    ]
