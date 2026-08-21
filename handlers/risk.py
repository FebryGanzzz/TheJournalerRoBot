"""Handler manajemen risiko — /settings & /size."""

from __future__ import annotations

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import CommandHandler, ContextTypes

import calc
import db
import formatters
from handlers.common import (
    DB_SETTING_KEYS,
    _FLOAT_KEYS,
    _KEY_RANGES,
    build_settings,
    check_allowed,
    extract_user_id,
)

# Nama key yang bisa diubah user
_KEY_LABELS = {
    "balance": "Saldo akun",
    "risk_percent": "Risiko per trade (%)",
    "currency": "Mata uang akun",
    "usdjpy_rate": "Kurs USD/JPY",
    "daily_loss_r": "Batas kerugian harian (R)",
    "daily_loss_percent": "Batas kerugian harian (% saldo)",
}


async def cmd_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await check_allowed(update, context):
        return
    uid = extract_user_id(update)
    s = build_settings(uid)
    # mode "set"
    if context.args and context.args[0].lower() == "set":
        if len(context.args) < 3:
            await update.effective_message.reply_text(
                "Format: <code>/settings set &lt;key&gt; &lt;value&gt;</code>\n"
                "Contoh: <code>/settings set balance 2000</code>\n\n"
                "Key yang bisa diubah:\n"
                + "\n".join(f"• <code>{k}</code> — {v}" for k, v in _KEY_LABELS.items())
            )
            return
        key = context.args[1].strip().lower()
        if key not in DB_SETTING_KEYS:
            await update.effective_message.reply_text(
                f"❌ Key tidak dikenal: <code>{key}</code>.\n"
                f"Key valid: {', '.join(sorted(DB_SETTING_KEYS))}"
            )
            return
        raw_value = " ".join(context.args[2:]).strip()
        try:
            if key in _FLOAT_KEYS:
                val_float = float(raw_value.replace(",", "."))
                lo, hi = _KEY_RANGES[key]
                if not (lo <= val_float <= hi):
                    raise ValueError
                db_val: str = str(val_float)
            else:
                db_val = raw_value
        except ValueError:
            await update.effective_message.reply_text(
                f"❌ Nilai tidak valid untuk <code>{key}</code>."
            )
            return
        with db.get_conn() as conn:
            db.set_setting(conn, uid, key, db_val)
        s2 = build_settings(uid)
        await update.effective_message.reply_text(
            f"✅ <code>{key}</code> diset ke <code>{db_val}</code>.\n\n" + formatters.fmt_settings(s2),
            parse_mode=ParseMode.HTML,
        )
        return
    # mode tampil
    await update.effective_message.reply_text(
        formatters.fmt_settings(s) + "\n\n"
        "Ubah dengan: <code>/settings set &lt;key&gt; &lt;value&gt;</code>\n"
        "Contoh: <code>/settings set balance 2000</code>",
        parse_mode=ParseMode.HTML,
    )


async def cmd_size(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await check_allowed(update, context):
        return
    uid = extract_user_id(update)
    s = build_settings(uid)
    if len(context.args) < 3:
        await update.effective_message.reply_text(
            "📏 <b>Kalkulator Ukuran Posisi</b>\n\n"
            "Hitung lot yang aman sesuai risiko.\n\n"
            "Format: <code>/size PAIR entry stop</code>\n"
            "Contoh: <code>/size EURUSD 1.0850 1.0800</code>\n"
            "Contoh JPY: <code>/size USDJPY 150.25 149.95</code>\n\n"
            "Rumus: lot = (saldo × risiko%) ÷ (jarak stop pip × nilai pip per lot)",
            parse_mode=ParseMode.HTML,
        )
        return
    pair = calc.normalize_pair(context.args[0])
    if pair is None:
        await update.effective_message.reply_text(
            f"❌ Format pasangan tidak valid: <code>{context.args[0]}</code>"
        )
        return
    try:
        entry = float(context.args[1].replace(",", "."))
        stop = float(context.args[2].replace(",", "."))
    except ValueError:
        await update.effective_message.reply_text(
            "❌ Harga tidak valid. Contoh: <code>/size EURUSD 1.0850 1.0800</code>"
        )
        return
    if not calc.validate_price(pair, entry) or not calc.validate_price(pair, stop):
        await update.effective_message.reply_text(
            f"❌ Harga harus > 0 dan presisinya sesuai {pair}."
        )
        return
    try:
        lots = calc.position_lots(s.default_balance, s.default_risk_percent,
                                  calc.stop_distance_pips(pair, entry, stop), pair)
        pips = calc.stop_distance_pips(pair, entry, stop)
    except ValueError as exc:
        await update.effective_message.reply_text(f"❌ {exc}")
        return
    risk_amount = s.default_balance * s.default_risk_percent / 100.0
    pip_val_per_lot = calc.pip_value_per_lot(pair)
    await update.effective_message.reply_text(
        "📏 <b>Ukuran Posisi</b>\n\n"
        f"• Pair        : {pair}\n"
        f"• Entry       : {entry}\n"
        f"• Stop        : {stop}\n"
        f"• Jarak stop  : {pips:.1f} pips\n"
        f"• Risiko      : {s.default_risk_percent:g}% = {risk_amount:.2f} {s.currency}\n"
        f"• Nilai pip   : {pip_val_per_lot:.2f} {s.currency}/pip/lot\n\n"
        f"💡 <b>Lot aman: {lots:.2f}</b> (bulatkan ke bawah)\n\n"
        f"Saldo {formatters.fmt_money(s.default_balance, s)} · "
        f"risiko {s.default_risk_percent:g}%. Ubah via /settings.",
        parse_mode=ParseMode.HTML,
    )


async def cmd_rr(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Risk/Reward calculator: /rr entry stop target"""
    if not await check_allowed(update, context):
        return
    uid = extract_user_id(update)
    s = build_settings(uid)
    if len(context.args) < 3:
        await update.effective_message.reply_text(
            "⚖️ <b>Kalkulator Risk/Reward</b>\n\n"
            "Format: <code>/rr entry stop target</code>\n"
            "Contoh: <code>/rr 1.0850 1.0800 1.0950</code>\n\n"
            "Menghitung rasio R:R dan potensi profit/loss.",
            parse_mode=ParseMode.HTML,
        )
        return
    pair_raw = context.args[0] if len(context.args) == 4 else None
    if pair_raw and calc.normalize_pair(pair_raw):
        pair = calc.normalize_pair(pair_raw)
        entry = float(context.args[1].replace(",", "."))
        stop = float(context.args[2].replace(",", "."))
        target = float(context.args[3].replace(",", "."))
    else:
        pair = "EURUSD"
        try:
            entry = float(context.args[0].replace(",", "."))
            stop = float(context.args[1].replace(",", "."))
            target = float(context.args[2].replace(",", "."))
        except ValueError:
            await update.effective_message.reply_text("❌ Harga tidak valid.")
            return

    risk_pips = calc.stop_distance_pips(pair, entry, stop)
    reward_pips = calc.price_pips(pair, entry, target)

    if risk_pips <= 0:
        await update.effective_message.reply_text(
            "❌ Stop loss harus berbeda dari entry dan mengarah ke kerugian."
        )
        return

    rr_ratio = reward_pips / risk_pips
    pip_val = calc.pip_value_per_lot(pair)
    risk_amount = risk_pips * pip_val
    reward_amount = reward_pips * pip_val

    # Evaluate
    if rr_ratio >= 3:
        verdict = "🟢 Sangat bagus!"
    elif rr_ratio >= 2:
        verdict = "🟢 Bagus"
    elif rr_ratio >= 1.5:
        verdict = "🟡 Cukup"
    elif rr_ratio >= 1:
            verdict = "🟠 Marginal"
    else:
        verdict = "🔴 Risk lebih besar dari reward!"

    await update.effective_message.reply_text(
        f"⚖️ <b>Risk/Reward — {pair}</b>\n\n"
        f"• Entry    : {entry}\n"
        f"• Stop     : {stop} ({risk_pips:.1f} pip risk)\n"
        f"• Target   : {target} ({reward_pips:.1f} pip reward)\n\n"
        f"📊 Rasio R:R = <b>1 : {rr_ratio:.2f}</b>\n"
        f"{verdict}\n\n"
        f"💰 Risk: {risk_amount:.2f} {s.currency}/lot\n"
        f"💰 Reward: {reward_amount:.2f} {s.currency}/lot",
        parse_mode=ParseMode.HTML,
    )


def handlers() -> list[object]:
    return [
        CommandHandler("settings", cmd_settings),
        CommandHandler("size", cmd_size),
        CommandHandler("rr", cmd_rr),
    ]
