"""Helper bersama antar handler: otorisasi + settings dinamis dari DB per-user."""

from __future__ import annotations

import logging
from dataclasses import replace

from telegram import Update
from telegram.ext import ContextTypes

import calc
import db
from config import Settings, load_settings

log = logging.getLogger(__name__)

# Key di DB yang meng-override default di Settings (dari .env).
DB_SETTING_KEYS = frozenset(
    {"balance", "risk_percent", "currency", "usdjpy_rate", "daily_loss_r", "daily_loss_percent"}
)

_FLOAT_KEYS = frozenset(
    {"balance", "risk_percent", "usdjpy_rate", "daily_loss_r", "daily_loss_percent"}
)

_KEY_RANGES: dict[str, tuple[float, float]] = {
    "balance": (0.01, 1e12),
    "risk_percent": (0.01, 100.0),
    "usdjpy_rate": (1.0, 1e6),
    "daily_loss_r": (-1e6, 0.0),
    "daily_loss_percent": (-100.0, 0.0),
}


def build_settings(user_id: int = 0) -> Settings:
    """Settings dari .env, di-override nilai yang tersimpan di DB per-user."""
    base = load_settings()
    with db.get_conn() as conn:
        stored = db.get_settings_dict(conn, user_id)
    fields: dict[str, object] = {}
    for key in DB_SETTING_KEYS:
        if key in stored:
            try:
                val: object = float(stored[key]) if key in _FLOAT_KEYS else stored[key]
                fields[key] = val
            except ValueError:
                log.warning("Nilai settings DB tidak valid untuk %s: %r", key, stored[key])
    field_map = {
        "balance": "default_balance",
        "risk_percent": "default_risk_percent",
        "currency": "currency",
        "usdjpy_rate": "usdjpy_rate",
        "daily_loss_r": "daily_loss_r",
        "daily_loss_percent": "daily_loss_percent",
    }
    kwargs = {field_map[k]: v for k, v in fields.items() if k in field_map}
    return replace(base, **kwargs)


class TradeDataError(ValueError):
    """Data trade tidak valid."""


def build_trade_from_dict(data: dict, user_id: int = 0) -> db.Trade:
    """Bangun objek Trade dari dict dengan validasi terpusat."""
    pair_raw = str(data.get("pair", "")).strip()
    pair = calc.normalize_pair(pair_raw)
    if pair is None:
        raise TradeDataError("Format pasangan tidak valid. Contoh: EURUSD")

    direction = str(data.get("direction", "")).strip().upper()
    if direction not in ("LONG", "SHORT"):
        raise TradeDataError("Arah harus LONG atau SHORT")

    def _price(key: str) -> float:
        try:
            v = float(data[key])
        except (KeyError, TypeError, ValueError):
            raise TradeDataError(f"Kolom {key} harus angka.") from None
        if not calc.validate_price(pair, v) or v <= 0:
            raise TradeDataError(f"Nilai {key} tidak valid untuk {pair} (desimal {calc.decimal_places(pair)}).")
        return v

    try:
        entry = _price("entry")
        exit_ = _price("exit")
    except TradeDataError:
        raise

    try:
        lot = float(data["lot"])
    except (KeyError, TypeError, ValueError):
        raise TradeDataError("Kolom lot harus angka.") from None
    if lot <= 0:
        raise TradeDataError("Lot harus lebih dari 0.")

    sl = None
    if data.get("sl") not in (None, ""):
        try:
            sl = float(data["sl"])
        except (TypeError, ValueError):
            raise TradeDataError("Stop loss harus angka atau kosong.") from None
        if sl <= 0 or not calc.validate_price(pair, sl):
            raise TradeDataError(
                f"Stop loss tidak valid untuk {pair} (desimal {calc.decimal_places(pair)})."
            )

    notes_raw = data.get("notes", "")
    notes = "" if notes_raw is None else str(notes_raw).strip()

    # Tags: comma-separated, lowercase, trimmed
    tags_raw = data.get("tags", "") or ""
    if isinstance(tags_raw, str):
        tags = ",".join(
            t.strip().lower() for t in tags_raw.split(",") if t.strip()
        )
    else:
        tags = ""

    return db.Trade(
        user_id=user_id,
        pair=pair,
        direction=direction,
        entry=entry,
        exit=exit_,
        lot=lot,
        stop_loss=sl,
        notes=notes,
        tags=tags,
    )


async def check_allowed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Return False bila user tidak diizinkan."""
    user = update.effective_user
    if user is None:
        return False
    base = load_settings()
    if base.allowed_user_ids and user.id not in base.allowed_user_ids:
        try:
            await update.effective_message.reply_text(
                "⛔ Anda tidak diizinkan memakai bot ini."
            )
        except Exception:
            pass
        return False
    return True


def extract_user_id(update: Update) -> int:
    """Ambil user_id dari update. Return 0 jika tidak ada."""
    user = update.effective_user
    return user.id if user else 0


async def notify_errors(update: Update, context: ContextTypes.DEFAULT_TYPE | None = None) -> None:
    """Log error dari update tanpa crash handler."""
    log.error("Terjadi kesalahan: %s", context.error, exc_info=context.error)
