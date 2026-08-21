"""Rumus trading Forex — murni (tanpa I/O, tanpa state) agar mudah diuji.

Konvensi:
- pip size   : 0.01 untuk pair berakhiran JPY, selainnya 0.0001
- pip value  : nilai 1 pip per lot = contract size (100_000) × pip size, dalam mata uang quote
- P&L        : dihitung dalam mata uang quote; pair berakhiran JPY dikonversi
               ke mata uang akun memakai kurs USD/JPY dari settings
- R-multiple : P&L dibagi (pip_value_per_lot × jarak stop dalam pip)
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta, time
from statistics import mean
from zoneinfo import ZoneInfo

from db import Trade
from config import Settings

log = logging.getLogger(__name__)

CONTRACT_SIZE = 100_000

# ---------------------------------------------------------------- pasangan

def normalize_pair(raw: str) -> str | None:
    """'eurusd' → 'EURUSD'; None bila format tidak valid (6 huruf)."""
    s = raw.strip().upper()
    if len(s) == 6 and s.isalpha():
        return s
    return None


def is_jpy_pair(pair: str) -> bool:
    return pair.endswith("JPY")


def pip_size(pair: str) -> float:
    return 0.01 if is_jpy_pair(pair) else 0.0001


def decimal_places(pair: str) -> int:
    return 2 if is_jpy_pair(pair) else 4


def validate_price(pair: str, value: float) -> bool:
    """Harga harus > 0 dan presisinya masuk akal untuk pair (2 desimal JPY, 4 lainnya)."""
    if value <= 0:
        return False
    places = decimal_places(pair)
    # Terima harga dengan desimal ≤ batas pair (atau 1 desimal ekstra untuk harga 5-digit)
    return round(value, places + 1) == value


def pip_value(pair: str, lot: float) -> float:
    """Nilai 1 pip untuk lot tertentu, dalam mata uang quote."""
    return CONTRACT_SIZE * lot * pip_size(pair)


def pip_value_per_lot(pair: str) -> float:
    return CONTRACT_SIZE * pip_size(pair)


def to_account_currency(pair: str, amount_in_quote: float, usdjpy_rate: float) -> float:
    """Konversi dari mata uang quote ke mata uang akun (USD).

    Pair berakhiran JPY → nilai dalam JPY, dibagi kurs USD/JPY.
    Pair berakhiran USD → sudah dalam USD.
    Pair silang lain (EURGBP, EURJPY, dst.) → dikonversi lewat USD,
    asumsi kurs quote/USD = 1 (aproksimasi sederhana untuk journal pribadi).
    """
    if is_jpy_pair(pair):
        if usdjpy_rate <= 0:
            log.warning("USDJPY_RATE tidak valid (%s) — pakai 150", usdjpy_rate)
            usdjpy_rate = 150.0
        return amount_in_quote / usdjpy_rate
    if pair.endswith("USD"):
        return amount_in_quote
    # Pair silang selain JPY: asumsi kuote ~ USD untuk penyederhanaan
    return amount_in_quote


# ---------------------------------------------------------------- P&L

def pnl(
    pair: str,
    direction: str,
    entry: float,
    exit_: float,
    lot: float,
    usdjpy_rate: float = 150.0,
) -> float:
    """P&L trade dalam mata uang akun (USD). Entry == exit → 0.0."""
    if entry == exit_:
        return 0.0
    move = exit_ - entry if direction == "LONG" else entry - exit_
    quote = move / pip_size(pair) * pip_value(pair, lot)
    return to_account_currency(pair, quote, usdjpy_rate)


def price_pips(pair: str, from_price: float, to_price: float) -> float:
    """Jarak antar harga dalam pip (selalu positif)."""
    return abs(to_price - from_price) / pip_size(pair)


def stop_distance_pips(pair: str, entry: float, stop_loss: float) -> float:
    return price_pips(pair, entry, stop_loss)


def r_multiple(
    pair: str,
    direction: str,
    entry: float,
    exit_: float,
    lot: float,
    stop_loss: float | None,
    usdjpy_rate: float = 150.0,
) -> float | None:
    """R-multiple (R) trade; None bila stop loss tidak dicatat / stop di entry."""
    if stop_loss is None or stop_loss == entry:
        return None
    dist = stop_distance_pips(pair, entry, stop_loss)
    if dist <= 0:
        return None
    value = CONTRACT_SIZE * lot * dist * pip_size(pair)
    r = pnl(pair, direction, entry, exit_, lot, usdjpy_rate) / to_account_currency(
        pair, value, usdjpy_rate
    )
    return round(r, 2)


def position_lots(
    balance: float,
    risk_percent: float,
    stop_pips: float,
    pair: str,
) -> float:
    """Ukuran posisi yang disarankan (lot, dibulatkan ke bawah 2 desimal).

    lots = (balance × risk%) / (stop_pips × pip_value_per_lot)
    """
    if balance <= 0:
        raise ValueError("Saldo harus lebih dari 0.")
    if risk_percent <= 0:
        raise ValueError("Persentase risiko harus lebih dari 0.")
    if stop_pips <= 0:
        raise ValueError("Jarak stop loss harus lebih dari 0 pips.")
    risk_amount = balance * risk_percent / 100.0
    lots = risk_amount / (stop_pips * pip_value_per_lot(pair))
    return math.floor(lots * 100) / 100.0  # floor ke micro-lot


# ---------------------------------------------------------------- statistik

def _base_agg() -> dict:
    return {
        "trades": 0,
        "wins": 0,
        "losses": 0,
        "breakeven": 0,
        "win_rate": 0.0,
        "profit_factor": None,
        "gross_profit": 0.0,
        "gross_loss": 0.0,
        "net_pnl": 0.0,
        "net_pips": 0.0,
        "avg_rr": None,
        "avg_r": None,
        "best": None,
        "worst": None,
        "risk_r": 0.0,
        "count_with_sl": 0,
        "count_with_r": 0,
    }


def _stats_core(trades: list[Trade], settings: Settings) -> dict:
    """Statistik inti satu set trade (tanpa by_pair/by_direction)."""
    agg = _base_agg()
    r_values: list[float] = []
    rr_values: list[float] = []

    for t in trades:
        p = pnl(t.pair, t.direction, t.entry, t.exit, t.lot, settings.usdjpy_rate)
        agg["trades"] += 1
        if p > 0:
            agg["wins"] += 1
        elif p < 0:
            agg["losses"] += 1
        else:
            agg["breakeven"] += 1
        agg["gross_profit"] += max(p, 0.0)
        agg["gross_loss"] += min(p, 0.0)
        agg["net_pnl"] += p
        agg["net_pips"] += (
            (t.exit - t.entry) / pip_size(t.pair)
            if t.direction == "LONG"
            else (t.entry - t.exit) / pip_size(t.pair)
        )

        r = r_multiple(t.pair, t.direction, t.entry, t.exit, t.lot, t.stop_loss, settings.usdjpy_rate)
        if t.stop_loss is not None:
            agg["count_with_sl"] += 1
            dist = stop_distance_pips(t.pair, t.entry, t.stop_loss)
            reward = price_pips(t.pair, t.entry, t.exit)
            if dist > 0:
                rr_values.append(reward / dist)
            if r is not None:
                agg["count_with_r"] += 1
                r_values.append(r)
                agg["risk_r"] += r
        elif r is not None:
            r_values.append(r)

    if agg["trades"]:
        agg["win_rate"] = agg["wins"] / agg["trades"] * 100.0
        agg["avg_rr"] = round(mean(rr_values), 2) if rr_values else None
        agg["avg_r"] = round(mean(r_values), 2) if r_values else None
        agg["best"] = max(trades, key=lambda t: pnl(t.pair, t.direction, t.entry, t.exit, t.lot, settings.usdjpy_rate))
        agg["worst"] = min(trades, key=lambda t: pnl(t.pair, t.direction, t.entry, t.exit, t.lot, settings.usdjpy_rate))
    if agg["gross_loss"] < 0:
        agg["profit_factor"] = agg["gross_profit"] / abs(agg["gross_loss"])
    return agg


def _sub_aggregate(trades: list[Trade], settings: Settings, key) -> dict[str, dict]:
    """Agregat per-kelompok (pair / direction). Memakai _stats_core, tanpa nesting."""
    groups: dict[str, list[Trade]] = {}
    for t in trades:
        groups.setdefault(key(t), []).append(t)
    result: dict[str, dict] = {}
    for name, group in sorted(groups.items()):
        a = _stats_core(group, settings)
        result[name] = {
            "trades": a["trades"],
            "wins": a["wins"],
            "losses": a["losses"],
            "win_rate": a["win_rate"],
            "net_pnl": a["net_pnl"],
            "net_pips": round(a["net_pips"], 2),
            "avg_rr": a["avg_rr"],
            "avg_r": a["avg_r"],
        }
    return result


def aggregate(trades: list[Trade], settings: Settings) -> dict:
    """Agregat statistik lengkap dari daftar trade. Struktur dict, bukan string."""
    agg = _stats_core(trades, settings)
    agg["by_pair"] = _sub_aggregate(trades, settings, key=lambda t: t.pair)
    agg["by_direction"] = _sub_aggregate(trades, settings, key=lambda t: t.direction)
    return agg


# ---------------------------------------------------------------- risk harian

def compute_daily_risk(agg: dict, settings: Settings) -> list[str]:
    """Peringatan ketika P&L hari ini ≤ batas harian (dalam R atau % saldo)."""
    warnings: list[str] = []
    if agg["trades"] == 0:
        return warnings
    if agg["risk_r"] <= settings.daily_loss_r:
        warnings.append(
            f"⚠️ Peringatan: kerugian hari ini {agg['risk_r']:.2f}R "
            f"(batas {settings.daily_loss_r:.1f}R). Pertimbangkan berhenti trading."
        )
    if agg["net_pnl"] <= settings.daily_loss_percent / 100.0 * settings.default_balance:
        warnings.append(
            f"⚠️ Peringatan: P&L hari ini {agg['net_pnl']:.2f} {settings.currency} "
            f"≤ {settings.daily_loss_percent:.0f}% saldo. Batasi risiko Anda!"
        )
    return warnings


# ---------------------------------------------------------------- periode

def period_to_window(
    period: str, now_utc: datetime, tz: ZoneInfo
) -> tuple[datetime | None, datetime]:
    """Jendela waktu UTC untuk filter periode.

    period: "today" | "week" | "month" | "all" (kasus tidak dikenal → "all")
    """
    local_now = now_utc.astimezone(tz)
    if period == "today":
        start_local = datetime.combine(local_now.date(), time.min, tzinfo=tz)
    elif period == "week":
        monday = local_now.date() - timedelta(days=local_now.weekday())
        start_local = datetime.combine(monday, time.min, tzinfo=tz)
    elif period == "month":
        start_local = datetime.combine(local_now.date().replace(day=1), time.min, tzinfo=tz)
    else:
        return None, now_utc
    return start_local.astimezone(ZoneInfo("UTC")), now_utc