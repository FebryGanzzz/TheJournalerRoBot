"""Handler trade: input langsung, wizard /add, list, detail, edit, delete."""

from __future__ import annotations

import logging
import re

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from datetime import datetime, timezone

from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

import calc
import db
import formatters
from config import get_tz
from handlers.common import build_settings, check_allowed, extract_user_id

log = logging.getLogger(__name__)

# -- state ConversationHandler /add ---------------------------------------
(PAIR, DIRECTION, ENTRY, EXIT, LOT, STOP_LOSS, NOTES, TAGS) = range(8)

EDIT_FIELD_MAP = {
    "pair": "pair",
    "direction": "direction",
    "entry": "entry",
    "exit": "exit",
    "lot": "lot",
    "stop_loss": "stop_loss",
    "notes": "notes",
    "tags": "tags",
}


# ---------------------------------------------------------------- /start /help

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await check_allowed(update, context):
        return
    uid = extract_user_id(update)
    s = build_settings(uid)

    # Try to set menu button on first interaction
    if s.webapp_url and context.bot:
        try:
            from telegram import MenuButtonWebApp, WebAppInfo
            btn = MenuButtonWebApp(text="📒 Journal", web_app=WebAppInfo(url=s.webapp_url))
            await context.bot.set_chat_menu_button(
                chat_id=update.effective_chat.id, menu_button=btn
            )
        except Exception:
            pass  # non-fatal

    webapp_line = "\n🌐 <b>WebApp:</b> /webapp\n" if s.webapp_url else ""
    await update.effective_message.reply_text(
        "👋 <b>Selamat datang di Trading Journal!</b>\n\n"
        "Bot untuk mencatat & menganalisis trading Forex Anda.\n\n"
        "📝 <b>Mulai cepat:</b>\n"
        "• <code>/trade EURUSD LONG entry=1.0850 exit=1.0950 lot=0.10</code> — catat sekaligus\n"
        "• <code>/add</code> — input bertahap (wizard)\n\n"
        "📊 <b>Lihat data:</b>\n"
        "• <code>/list [today|week|month|PAIR]</code> — riwayat trade\n"
        "• <code>/stats [today|week|month]</code> — statistik\n\n"
        "📉 <b>Analisis & laporan:</b>\n"
        "• <code>/report [week|month]</code> — laporan kinerja\n"
        "• <code>/chart</code> — kurva ekuitas\n"
        "• <code>/export</code> — unduh CSV\n\n"
        "⚙️ <b>Pengaturan:</b>\n"
        "• <code>/settings</code> dan <code>/size</code>\n"
        "• <code>/panel</code> — panel tombol sentuh\n"
        "• <code>/streak</code> — win/loss streak\n"
        "• <code>/session</code> — performa per sesi\n"
        "• <code>/rr</code> — kalkulator R:R\n"
        "• <code>/summary</code> — ringkasan hari ini\n\n"
        "Ketik <code>/help</code> untuk bantuan lengkap."
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await check_allowed(update, context):
        return
    await update.effective_message.reply_text(
        "📚 <b>Bantuan — Trading Journal</b>\n\n"
        "<b>Mencatat trade</b>\n"
        "• <code>/trade PAIR DIR entry=... exit=... lot=... [sl=...] [notes=...]</code>\n"
        "   Contoh: <code>/trade EURUSD LONG entry=1.0850 exit=1.0950 lot=0.10 sl=1.0800</code>\n"
        "• <code>/add</code> — wizard bertahap (pair → arah → entry → exit → lot → SL → catatan)\n\n"
        "<b>Melihat trade</b>\n"
        "• <code>/list [today|week|month|PAIR]</code>\n"
        "• <code>/detail &lt;id&gt;</code> — lihat detail trade\n"
        "• <code>/edit &lt;id&gt;</code> — ubah trade\n"
        "• <code>/delete &lt;id&gt;</code> — hapus trade\n\n"
        "<b>Analisis</b>\n"
        "• <code>/stats [today|week|month|all]</code>\n"
        "• <code>/report [week|month]</code>\n"
        "• <code>/chart</code> — kurva ekuitas (PNG)\n"
        "• <code>/export</code> — CSV semua trade\n\n"
        "<b>Manajemen risiko</b>\n"
        "• <code>/size PAIR entry stop</code> — hitung lot sesuai risiko\n"
        "• <code>/rr entry stop target</code> — kalkulator Risk/Reward\n"
        "• <code>/settings</code> — lihat & ubah pengaturan\n\n"
        "<b>Fitur baru</b>\n"
        "• <code>/streak</b> — streak menang/kalah & konsistensi\n"
        "• <code>/session</b> — performa per sesi trading (Asian/London/NY)\n"
        "• <code>/summary</b> — ringkasan hari ini dengan insight\n\n"
        "<i>Setiap user punya data sendiri-sendiri. Trade bisa ditambah tags:</i>\n"
        "<code>/trade EURUSD LONG entry=.. exit=.. lot=.. tags=breakout,scalping</code>"
    )


# ---------------------------------------------------------------- /trade inline

_FLAG_RE = re.compile(r"(\w+)=([+-]?[\d.]+)")
_FREE_RE = re.compile(r"notes=(.+)", re.IGNORECASE)
_TAGS_RE = re.compile(r"tags=(.+)", re.IGNORECASE)

def _parse_trade_args(args: list[str]) -> tuple[dict, str | None]:
    if not args:
        return {}, "Gunakan format:\n<code>/trade EURUSD LONG entry=1.0850 exit=1.0950 lot=0.10</code>"
    text = " ".join(args)

    m = _FREE_RE.search(text)
    notes = m.group(1).strip() if m else ""
    rest = _FREE_RE.sub("", text).strip()

    m_tags = _TAGS_RE.search(rest)
    tags = m_tags.group(1).strip() if m_tags else ""
    rest = _TAGS_RE.sub("", rest).strip()

    tokens = rest.split()
    fields: dict[str, object] = {}
    stop: str | None = None
    pair_tok: str | None = None
    dir_tok: str | None = None
    for tok in tokens:
        if "=" not in tok:
            if pair_tok is None:
                pair_tok = tok
            elif dir_tok is None:
                dir_tok = tok.upper()
            else:
                stop = f"Tidak bisa menafsirkan argumen tanpa '=' ({tok!r})."
                break
            continue
        key, _, val = tok.partition("=")
        key_l = key.lower()
        if key_l in ("entry", "exit", "lot", "sl", "stop"):
            try:
                fields[key_l] = float(val)
            except ValueError:
                stop = f"Nilai {key} tidak valid: {val!r}"
                break
        else:
            stop = f"Flag tidak dikenal: {key!r}"
            break

    if stop:
        return {}, stop
    if not pair_tok or not dir_tok:
        return {}, "Format: <code>/trade PAIR DIR [entry=..] [exit=..] [lot=..] [sl=..]</code>"

    pair = calc.normalize_pair(pair_tok)
    if pair is None:
        return {}, f"Format pasangan tidak valid: <code>{pair_tok}</code>. Contoh: <code>EURUSD</code>"
    if dir_tok not in ("LONG", "SHORT"):
        return {}, f"Arah tidak valid: <code>{dir_tok}</code>. Pakai LONG atau SHORT"
    fields["pair"] = pair
    fields["direction"] = dir_tok
    fields["notes"] = notes
    fields["tags"] = tags
    return fields, None


async def cmd_trade(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await check_allowed(update, context):
        return
    uid = extract_user_id(update)
    s = build_settings(uid)
    fields, err = _parse_trade_args(context.args or [])
    if err:
        await update.effective_message.reply_text(f"❌ {err}")
        return
    pair: str = fields["pair"]
    for key in ("entry", "exit", "lot"):
        if key not in fields:
            await update.effective_message.reply_text(f"❌ Kolom <code>{key}</code> wajib diisi.")
            return
    try:
        entry = float(fields["entry"])
        exit_ = float(fields["exit"])
        lot = float(fields["lot"])
        if not calc.validate_price(pair, entry) or not calc.validate_price(pair, exit_):
            raise ValueError
        if lot <= 0:
            raise ValueError
    except (TypeError, ValueError):
        await update.effective_message.reply_text(f"❌ Nilai entry/exit/lot tidak valid untuk {pair}.")
        return
    sl = None
    if "sl" in fields or "stop" in fields:
        try:
            sl = float(fields.get("sl", fields.get("stop")))
            if sl <= 0 or not calc.validate_price(pair, sl):
                raise ValueError
        except (TypeError, ValueError):
            await update.effective_message.reply_text(
                f"❌ Stop loss tidak valid untuk {pair} (harus {calc.decimal_places(pair)} desimal)."
            )
            return
    notes = str(fields.get("notes", "")).strip()
    tags = str(fields.get("tags", "")).strip().lower()
    trade = db.Trade(
        user_id=uid,
        pair=pair,
        direction=fields["direction"],
        entry=entry,
        exit=exit_,
        lot=lot,
        stop_loss=sl,
        notes=notes,
    )
    with db.get_conn() as conn:
        tid = db.insert_trade(conn, trade)
        trade.id = tid
    await update.effective_message.reply_text(
        f"✅ Trade tersimpan sebagai #{tid}.\n\n" + formatters.fmt_trade_card(trade, s),
        parse_mode=ParseMode.HTML,
    )


# ---------------------------------------------------------------- /add wizard
ADD_ENTRY_HELP = (
    "📝 <b>/add — Entri baru</b>\n"
    "Ikuti langkah berikut. Ketik <code>/batal</code> kapan saja untuk membatalkan.\n\n"
)

ADD_ENTRY_HELP = (
    "📝 <b>/add — Entri baru</b>\n"
    "Ikuti langkah berikut. Ketik <code>/batal</code> kapan saja untuk membatalkan.\n\n"
)


async def add_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await check_allowed(update, context):
        return ConversationHandler.END
    await update.effective_message.reply_text(
        ADD_ENTRY_HELP + "Langkah 1/8: Apa pasangan mata uangnya?\n"
        "Contoh: <code>EURUSD</code>, <code>GBPJPY</code>, <code>USDCHF</code>"
    )
    return PAIR


async def add_pair(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = (update.effective_message.text or "").strip()
    pair = calc.normalize_pair(text)
    if pair is None:
        await update.effective_message.reply_text(
            "❌ Format pasangan tidak valid. Contoh: <code>EURUSD</code>"
        )
        return PAIR
    context.user_data["trade_draft"] = {"pair": pair}
    await update.effective_message.reply_text(
        "Langkah 2/8: Arah posisi? <code>LONG</code> atau <code>SHORT</code>"
    )
    return DIRECTION


async def add_direction(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    d = (update.effective_message.text or "").strip().upper()
    if d not in ("LONG", "SHORT"):
        await update.effective_message.reply_text(
            "❌ Arah tidak valid. Ketik <code>LONG</code> atau <code>SHORT</code>"
        )
        return DIRECTION
    context.user_data["trade_draft"]["direction"] = d
    pair = context.user_data["trade_draft"]["pair"]
    dec = calc.decimal_places(pair)
    example = "1.0850" if dec == 4 else "150.25"
    await update.effective_message.reply_text(
        f"Langkah 3/8: Harga <b>entry</b> untuk {pair} "
        f"(desimal {dec}, mis. <code>{example}</code>)"
    )
    return ENTRY


async def add_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    draft = context.user_data["trade_draft"]
    pair = draft["pair"]
    raw = (update.effective_message.text or "").strip()
    try:
        val = float(raw.replace(",", "."))
    except ValueError:
        await update.effective_message.reply_text(f"❌ Nilai tidak valid: <code>{raw}</code>")
        return ENTRY
    if not calc.validate_price(pair, val):
        await update.effective_message.reply_text(
            f"❌ Entry tidak valid untuk {pair} (maks {calc.decimal_places(pair)} desimal, > 0)."
        )
        return ENTRY
    draft["entry"] = val
    await update.effective_message.reply_text(
        f"Langkah 4/8: Harga <b>exit</b> (target / SL) untuk {pair}"
    )
    return EXIT


async def add_exit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    draft = context.user_data["trade_draft"]
    pair = draft["pair"]
    raw = (update.effective_message.text or "").strip()
    try:
        val = float(raw.replace(",", "."))
    except ValueError:
        await update.effective_message.reply_text(f"❌ Nilai tidak valid: <code>{raw}</code>")
        return EXIT
    if not calc.validate_price(pair, val):
        await update.effective_message.reply_text(
            f"❌ Exit tidak valid untuk {pair} (maks {calc.decimal_places(pair)} desimal, > 0)."
        )
        return EXIT
    draft["exit"] = val
    await update.effective_message.reply_text(
        "Langkah 5/8: Ukuran <b>lot</b> (mis. 0.10)"
    )
    return LOT


async def add_lot(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    raw = (update.effective_message.text or "").strip().replace(",", ".")
    try:
        lot = float(raw)
    except ValueError:
        await update.effective_message.reply_text(f"❌ Nilai tidak valid: <code>{raw}</code>")
        return LOT
    if lot <= 0:
        await update.effective_message.reply_text("❌ Lot harus lebih dari 0.")
        return LOT
    context.user_data["trade_draft"]["lot"] = lot
    await update.effective_message.reply_text(
        "Langkah 6/8: Harga <b>stop loss</b> (opsional). Ketik <code>-</code> untuk skip."
    )
    return STOP_LOSS


async def add_stop_loss(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    draft = context.user_data["trade_draft"]
    pair = draft["pair"]
    raw = (update.effective_message.text or "").strip()
    if raw in ("-", "skip", ""):
        draft["stop_loss"] = None
    else:
        try:
            val = float(raw.replace(",", "."))
        except ValueError:
            await update.effective_message.reply_text(
                f"❌ Nilai tidak valid: <code>{raw}</code>. Ketik <code>-</code> untuk skip."
            )
            return STOP_LOSS
        if not calc.validate_price(pair, val) or val <= 0:
            await update.effective_message.reply_text(
                f"❌ Stop loss tidak valid untuk {pair}."
            )
            return STOP_LOSS
        draft["stop_loss"] = val
    await update.effective_message.reply_text(
        "Langkah 7/8: <b>Catatan</b> (opsional). Ketik <code>-</code> untuk skip."
    )
    return NOTES


async def add_notes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    raw = (update.effective_message.text or "").strip()
    draft = context.user_data["trade_draft"]
    draft["notes"] = "" if raw in ("-", "skip") else raw
    await update.effective_message.reply_text(
        "Langkah 8/8: <b>Tags</b> (opsional).\n"
        "Pisahkan dengan koma. Contoh: <code>breakout,scalping,london</code>\n"
        "Ketik <code>-</code> untuk skip."
    )
    return TAGS


async def add_tags(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    uid = extract_user_id(update)
    raw = (update.effective_message.text or "").strip()
    draft = context.user_data["trade_draft"]
    tags = "" if raw in ("-", "skip") else ",".join(t.strip().lower() for t in raw.split(",") if t.strip())
    try:
        trade = db.Trade(
            user_id=uid,
            pair=draft["pair"],
            direction=draft["direction"],
            entry=draft["entry"],
            exit=draft["exit"],
            lot=draft["lot"],
            stop_loss=draft.get("stop_loss"),
            notes=draft.get("notes", ""),
            tags=tags,
        )
        with db.get_conn() as conn:
            tid = db.insert_trade(conn, trade)
            trade.id = tid
    except KeyError as exc:
        log.error("Draft /add tidak lengkap: %r", draft)
        await update.effective_message.reply_text(
            f"❌ Ada data yang hilang ({exc}). Mulai ulang dengan /add."
        )
        return ConversationHandler.END
    s = build_settings(uid)
    await update.effective_message.reply_text(
        f"✅ Trade tersimpan sebagai #{tid}.\n\n" + formatters.fmt_trade_card(trade, s),
        parse_mode=ParseMode.HTML,
    )
    return ConversationHandler.END


async def add_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.effective_message.reply_text("🚫 Wizard dibatalkan.")
    return ConversationHandler.END


# ---------------------------------------------------------------- /list /detail

_PERIOD_ALIASES = {
    "today": "today", "hari": "today", "harini": "today",
    "week": "week", "minggu": "week",
    "month": "month", "bulan": "month",
}


async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await check_allowed(update, context):
        return
    uid = extract_user_id(update)
    s = build_settings(uid)
    arg = (context.args[0] if context.args else None)
    with db.get_conn() as conn:
        if arg and arg.upper() in _PERIOD_ALIASES:
            period = _PERIOD_ALIASES[arg.upper()]
            start, end = calc.period_to_window(period, datetime.now(timezone.utc), get_tz(s))
            trades = db.list_trades(conn, uid, start=start, end=end)
            label = {"today": "Hari Ini", "week": "Minggu Ini", "month": "Bulan Ini"}[period]
        elif arg:
            pair = calc.normalize_pair(arg)
            if pair is None:
                await update.effective_message.reply_text(
                    f"❌ Filter tidak dikenal: <code>{arg}</code>."
                )
                return
            trades = db.list_trades(conn, uid, pair=pair)
            label = pair
        else:
            trades = db.list_trades(conn, uid)
            label = "Semua"
    if not trades:
        await update.effective_message.reply_text(
            f"Belum ada trade periode <b>{label}</b>."
        )
        return
    await update.effective_message.reply_text(
        f"📒 <b>Riwayat — {label}</b> ({len(trades)} trade)\n\n" + formatters.fmt_trade_list(trades[:20], s),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


async def cmd_detail(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await check_allowed(update, context):
        return
    uid = extract_user_id(update)
    s = build_settings(uid)
    if not context.args:
        await update.effective_message.reply_text("Pakai: <code>/detail &lt;id&gt;</code>")
        return
    try:
        trade_id = int(context.args[0])
    except ValueError:
        await update.effective_message.reply_text(f"❌ ID tidak valid: <code>{context.args[0]}</code>")
        return
    with db.get_conn() as conn:
        trade = db.get_trade(conn, trade_id, uid)
    if trade is None:
        await update.effective_message.reply_text(f"❌ Trade #{trade_id} tidak ditemukan.")
        return
    await update.effective_message.reply_text(
        formatters.fmt_trade_card(trade, s), parse_mode=ParseMode.HTML,
    )


# ---------------------------------------------------------------- /edit

_EDIT_PROMPTS = {
    "pair": "✏️ Pasangan baru (mis. <code>EURUSD</code>):",
    "direction": "✏️ Arah baru (<code>LONG</code> / <code>SHORT</code>):",
    "entry": "✏️ Entry baru:",
    "exit": "✏️ Exit baru:",
    "lot": "✏️ Lot baru (mis. <code>0.10</code>):",
    "stop_loss": "✏️ Stop loss baru (ketik <code>-</code> untuk hapus):",
    "notes": "✏️ Catatan baru (ketik <code>-</code> untuk hapus):",
    "tags": "✏️ Tags baru (koma-pisah, ketik <code>-</code> untuk hapus):",
}


def _validate_edit_value(trade: db.Trade, field: str, raw: str) -> tuple[object, str | None]:
    raw = raw.strip()
    if field == "pair":
        pair = calc.normalize_pair(raw)
        return pair, None if pair else "Format pasangan tidak valid. Contoh: EURUSD"
    if field == "direction":
        d = raw.upper()
        return d, None if d in ("LONG", "SHORT") else "Arah harus LONG atau SHORT"
    if field in ("entry", "exit", "stop_loss", "lot"):
        try:
            fl = float(raw.replace(",", "."))
        except ValueError:
            return None, "Nilai harus angka."
        pair = trade.pair
        if field == "lot":
            if fl <= 0:
                return None, "Lot harus lebih dari 0."
        else:
            if fl <= 0 or not calc.validate_price(pair, fl):
                return None, (
                    f"Nilai harus > 0 dan presisinya sesuai {pair} "
                    f"(maks {calc.decimal_places(pair)} desimal)."
                )
        return fl, None
    return ("" if raw in ("-",) else raw), None


def _edit_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Pasangan", callback_data="edit-pick:pair"),
             InlineKeyboardButton("Arah", callback_data="edit-pick:direction")],
            [InlineKeyboardButton("Entry", callback_data="edit-pick:entry"),
             InlineKeyboardButton("Exit", callback_data="edit-pick:exit"),
             InlineKeyboardButton("Lot", callback_data="edit-pick:lot")],
            [InlineKeyboardButton("Stop Loss", callback_data="edit-pick:stop_loss"),
             InlineKeyboardButton("Catatan", callback_data="edit-pick:notes")],
            [InlineKeyboardButton("🔁 Selesai", callback_data="edit-pick:cancel")],
        ]
    )


def _edit_confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ Simpan", callback_data="edit-save:yes"),
             InlineKeyboardButton("❌ Batal", callback_data="edit-save:no")],
        ]
    )


def _clear_edit(user_data: dict) -> None:
    user_data.pop("edit_trade_id", None)
    user_data.pop("edit_field", None)
    user_data.pop("edit_val", None)


async def _send_edit_confirm(update, field: str, val: object) -> None:
    await update.effective_message.reply_text(
        f"Konfirmasi ubah <b>{field}</b> → <code>{val}</code>\n\n"
        "Simpan atau batalkan perubahan ini?",
        reply_markup=_edit_confirm_kb(),
    )


async def cmd_edit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await check_allowed(update, context):
        return
    uid = extract_user_id(update)
    args = context.args or []
    if not args:
        await update.effective_message.reply_text("Pakai: <code>/edit &lt;id&gt;</code>")
        return
    try:
        trade_id = int(args[0])
    except ValueError:
        await update.effective_message.reply_text(f"❌ ID tidak valid: <code>{args[0]}</code>")
        return
    with db.get_conn() as conn:
        trade = db.get_trade(conn, trade_id, uid)
    if trade is None:
        await update.effective_message.reply_text(f"❌ Trade #{trade_id} tidak ditemukan.")
        return
    _clear_edit(context.user_data)
    context.user_data["edit_trade_id"] = trade_id

    # mode cepat: /edit <id> field=value
    if len(args) >= 2 and "=" in args[1]:
        key, _, raw = args[1].partition("=")
        if key not in EDIT_FIELD_MAP:
            await update.effective_message.reply_text(
                f"❌ Field tidak dikenal: <code>{key}</code>.\n"
                "Pilihan: pair, direction, entry, exit, lot, stop_loss, notes"
            )
            return
        ok, err = _validate_edit_value(trade, key, raw)
        if err:
            await update.effective_message.reply_text(f"❌ {err}")
            return
        context.user_data["edit_field"] = key
        context.user_data["edit_val"] = ok
        await _send_edit_confirm(update, key, ok)
        return

    await update.effective_message.reply_text(
        f"✏️ <b>Edit trade #{trade.id}</b>\n\n" + formatters.fmt_trade_card(trade, build_settings(uid)),
        parse_mode=ParseMode.HTML,
        reply_markup=_edit_kb(),
    )


async def edit_pick_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    data: str = q.data
    if not data.startswith("edit-pick:"):
        return
    field = data.split(":", 1)[1]
    trade_id = context.user_data.get("edit_trade_id")
    if field == "cancel":
        _clear_edit(context.user_data)
        await q.edit_message_text("🚫 Edit selesai.")
        return
    if trade_id is None:
        _clear_edit(context.user_data)
        await q.edit_message_text("❌ Sesi edit sudah berakhir. Mulai lagi dengan /edit &lt;id&gt;.")
        return
    context.user_data["edit_field"] = field
    await q.edit_message_text(
        _EDIT_PROMPTS[field] + "\n\nKetik <code>/batal</code> untuk membatalkan."
    )


async def edit_value_msg(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = extract_user_id(update)
    field = context.user_data.get("edit_field")
    trade_id = context.user_data.get("edit_trade_id")
    if field is None or trade_id is None:
        return
    with db.get_conn() as conn:
        trade = db.get_trade(conn, trade_id, uid)
    if trade is None:
        await update.effective_message.reply_text("❌ Trade tidak ditemukan. Edit dibatalkan.")
        _clear_edit(context.user_data)
        return
    raw = (update.effective_message.text or "").strip()
    ok, err = _validate_edit_value(trade, field, raw)
    if err:
        await update.effective_message.reply_text(f"❌ {err}\n\n{_EDIT_PROMPTS[field]}")
        return
    context.user_data["edit_val"] = ok
    await _send_edit_confirm(update, field, ok)


async def edit_save_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = extract_user_id(update)
    q = update.callback_query
    await q.answer()
    data: str = q.data
    if not data.startswith("edit-save:"):
        return
    choice = data.split(":", 1)[1]
    trade_id = context.user_data.get("edit_trade_id")
    field = context.user_data.get("edit_field")
    val = context.user_data.get("edit_val")
    if choice == "no":
        _clear_edit(context.user_data)
        await q.edit_message_text("🚫 Perubahan dibatalkan.")
        return
    if trade_id is None or field is None or val is None:
        _clear_edit(context.user_data)
        await q.edit_message_text("❌ Sesi berakhir. Mulai lagi dengan /edit &lt;id&gt;.")
        return
    col = EDIT_FIELD_MAP.get(field)
    if col is None:
        _clear_edit(context.user_data)
        await q.edit_message_text("❌ Field tidak dikenal.")
        return
    with db.get_conn() as conn:
        db.update_trade_fields(conn, trade_id, uid, {col: val})
        updated = db.get_trade(conn, trade_id, uid)
    _clear_edit(context.user_data)
    await q.edit_message_text(
        f"✅ Trade #{trade_id} berhasil diubah.\n\n"
        + formatters.fmt_trade_card(updated, build_settings(uid)),
        parse_mode=ParseMode.HTML,
    )


async def edit_cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    active = context.user_data.get("edit_trade_id") is not None or context.user_data.get("edit_field") is not None
    _clear_edit(context.user_data)
    await update.effective_message.reply_text("🚫 Edit dibatalkan." if active else "Tidak ada sesi edit aktif.")


# ---------------------------------------------------------------- /delete

async def cmd_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await check_allowed(update, context):
        return
    uid = extract_user_id(update)
    if not context.args:
        await update.effective_message.reply_text("Pakai: <code>/delete &lt;id&gt;</code>")
        return
    try:
        trade_id = int(context.args[0])
    except ValueError:
        await update.effective_message.reply_text(f"❌ ID tidak valid: <code>{context.args[0]}</code>")
        return
    with db.get_conn() as conn:
        trade = db.get_trade(conn, trade_id, uid)
    if trade is None:
        await update.effective_message.reply_text(f"❌ Trade #{trade_id} tidak ditemukan.")
        return
    kb = [
        [InlineKeyboardButton("✅ Ya, hapus", callback_data=f"del:yes:{trade.id}"),
         InlineKeyboardButton("❌ Tidak", callback_data="del:no")],
    ]
    await update.effective_message.reply_text(
        f"🗑️ Hapus trade #{trade.id}? ({trade.pair} {trade.direction})\n\n"
        "Aksi ini tidak bisa dibatalkan.",
        reply_markup=InlineKeyboardMarkup(kb),
    )


async def delete_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = extract_user_id(update)
    q = update.callback_query
    await q.answer()
    data: str = q.data
    if not data.startswith("del:"):
        return
    action = data.split(":", 1)[1]
    if action == "no":
        await q.edit_message_text("🗑️ Penghapusan dibatalkan.")
        return
    try:
        trade_id = int(action.split(":")[1])
    except (IndexError, ValueError):
        await q.edit_message_text("❌ Data tidak valid.")
        return
    with db.get_conn() as conn:
        deleted = db.delete_trade(conn, trade_id, uid)
    if deleted:
        await q.edit_message_text(f"🗑️ Trade #{trade_id} telah dihapus.")
    else:
        await q.edit_message_text(f"❌ Trade #{trade_id} tidak ditemukan (mungkin sudah dihapus).")


# ---------------------------------------------------------------- handler factory

def handlers() -> list[object]:
    add_conv = ConversationHandler(
        entry_points=[CommandHandler("add", add_start)],
        states={
            PAIR: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_pair)],
            DIRECTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_direction)],
            ENTRY: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_entry)],
            EXIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_exit)],
            LOT: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_lot)],
            STOP_LOSS: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_stop_loss)],
            NOTES: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_notes)],
            TAGS: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_tags)],
        },
        fallbacks=[CommandHandler("batal", add_cancel), CommandHandler("cancel", add_cancel)],
        name="add_trade",
        persistent=False,
    )

    return [
        CommandHandler("start", cmd_start),
        CommandHandler("help", cmd_help),
        CommandHandler("trade", cmd_trade),
        add_conv,
        CommandHandler("edit", cmd_edit),
        CallbackQueryHandler(edit_pick_cb, pattern=r"^edit-pick:"),
        CallbackQueryHandler(edit_save_cb, pattern=r"^edit-save:"),
        MessageHandler(filters.TEXT & ~filters.COMMAND, edit_value_msg),
        CommandHandler("batal", edit_cancel_cmd),
        CommandHandler("list", cmd_list),
        CommandHandler("detail", cmd_detail),
        CommandHandler("delete", cmd_delete),
        CallbackQueryHandler(delete_cb, pattern=r"^del:"),
    ]
