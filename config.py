"""Konfigurasi bot — membaca .env dan environment variables."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Settings:
    """Semua pengaturan bot yang bisa dikonfigurasi via .env."""

    bot_token: str
    timezone: str = "Asia/Jakarta"
    default_balance: float = 1000.0
    default_risk_percent: float = 1.0
    currency: str = "USD"
    daily_loss_r: float = -2.0
    daily_loss_percent: float = -3.0
    usdjpy_rate: float = 150.0
    webapp_url: str = ""
    allowed_user_ids: tuple[int, ...] = field(default_factory=tuple)


def _parse_float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw.replace(",", "."))
    except ValueError:
        log.warning("Nilai env %s tidak valid: %r — pakai default %s", name, raw, default)
        return default


def _parse_ids(name: str) -> tuple[int, ...]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return ()
    ids: list[int] = []
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if part:
            try:
                ids.append(int(part))
            except ValueError:
                log.warning("ID user tidak valid di %s: %r", name, part)
    return tuple(ids)


def load_settings() -> Settings:
    """Bangun Settings dari .env / environment variables."""
    return Settings(
        bot_token=os.getenv("BOT_TOKEN", "").strip(),
        timezone=os.getenv("TIMEZONE", "Asia/Jakarta").strip() or "Asia/Jakarta",
        default_balance=_parse_float("DEFAULT_BALANCE", 1000.0),
        default_risk_percent=_parse_float("DEFAULT_RISK_PERCENT", 1.0),
        currency=os.getenv("CURRENCY", "USD").strip().upper() or "USD",
        daily_loss_r=_parse_float("DAILY_LOSS_R", -2.0),
        daily_loss_percent=_parse_float("DAILY_LOSS_PERCENT", -3.0),
        usdjpy_rate=_parse_float("USDJPY_RATE", 150.0),
        webapp_url=os.getenv("WEBAPP_URL", "").strip(),
        allowed_user_ids=_parse_ids("ALLOWED_USER_IDS"),
    )


@lru_cache(maxsize=None)
def get_tz(settings: Settings) -> ZoneInfo:
    """Zona waktu bot, fallback ke UTC bila tz tidak dikenal."""
    try:
        return ZoneInfo(settings.timezone)
    except ZoneInfoNotFoundError:
        log.warning("Zona waktu %r tidak ditemukan — fallback ke UTC", settings.timezone)
        return ZoneInfo("UTC")