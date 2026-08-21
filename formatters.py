"""Renderer teks — semua output bot dalam Bahasa Indonesia, ramah Telegram.

Catatan Telegram: tag <code> monospace membutuhkan sel tabel diberi padding
spasi ke lebar sama agar kolom sejajar. Tabel memakai blok <pre>.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from config import Settings, get_tz
from db import Trade
import calc

# ---------------------------------------------------------------- dasar

def fmt_money(value: float, settings: Settings) -> str:
    return f"{value:,.2f} {settings.currency}"


def fmt_number(value: float, digits: int = 2) -> str:
    return f"{value:,.{digits}f}"


def fmt_percent(x: float) -> str:
    return f"{x:.1f}%"


def fmt_pips(x: float) -> str:
    return f"{x:+.1f} pips"


def fmt_opt(value: Any, formatter, dash: str = "—") -> str:
    """None → dash, selainnya pakai formatter."""
    return formatter(value) if value is not None else dash


def local_str(dt: datetime, settings: Settings) -> str:
    """datetime UTC → string zona waktu lokal."""
    return dt.astimezone(get_tz(settings)).strftime("%d %b %Y %H:%M")


def direction_emoji(direction: str) -> str:
    return "🔺 LONG" if direction == "LONG" else "🔻 SHORT"


def pnl_emoji(p: float) -> str:
    if p > 0:
        return "🟢"
    if p < 0:
        return "🔴"
    return "⚪"


# ---------------------------------------------------------------- kartu trade

def fmt_trade_card(t: Trade, settings: Settings) -> str:
    p = calc.pnl(t.pair, t.direction, t.entry, t.exit, t.lot, settings.usdjpy_rate)
    r = calc.r_multiple(t.pair, t.direction, t.entry, t.exit, t.lot, t.stop_loss, settings.usdjpy_rate)
    lines = [
        f"{pnl_emoji(p)} <b>#{t.id}</b> {t.pair} {direction_emoji(t.direction)}",
        f"    Entry : {fmt_number(t.entry, calc.decimal_places(t.pair))}",
        f"    Exit  : {fmt_number(t.exit, calc.decimal_places(t.pair))}",
        f"    Lot   : {t.lot:g}",
        f"    Stop  : {fmt_opt(t.stop_loss, lambda v: fmt_number(v, calc.decimal_places(t.pair)))}",
        f"    Pips  : {calc.price_pips(t.pair, t.entry, t.exit) * (1 if (t.exit - t.entry) * (1 if t.direction=='LONG' else -1) > 0 else -1):+g}",
        f"    P&L   : {fmt_money(p, settings)} ({fmt_opt(r, lambda v: f'{v:+.1f}R')})",
        f"    Waktu : {local_str(t.open_time, settings)}",
    ]
    if t.notes:
        lines.append(f"    <i>Catatan:</i> {t.notes}")
    if t.tags:
        tag_display = " ".join(f"#{tag.strip()}" for tag in t.tags.split(",") if tag.strip())
        lines.append(f"    🏷️ Tags: {tag_display}")
    return "\n".join(lines)


def pip_flow(t: Trade) -> float:
    """Pergerakan trade dalam pip, bertanda sesuai arah (positif = untung)."""
    raw = (t.exit - t.entry) / calc.pip_size(t.pair)
    return raw if t.direction == "LONG" else -raw


def fmt_trade_list(trades: list[Trade], settings: Settings) -> str:
    if not trades:
        return "Belum ada trade yang cocok."
    header = (
        f"<pre>{'#':>4} {'PAIR':<7} {'DIR':<5} {'PIP':>7} {'P&L':>12} {'LOT':>5}  {'WAKTU'}</pre>"
    )
    rows: list[str] = []
    for t in trades:
        p = calc.pnl(t.pair, t.direction, t.entry, t.exit, t.lot, settings.usdjpy_rate)
        rows.append(
            f"<pre>{t.id:>4} {t.pair:<7} {t.direction:<5} {pip_flow(t):+7.1f} "
            f"{p:>12,.2f} {t.lot:>5.2f}  {local_str(t.open_time, settings)}</pre>"
        )
    return header + "\n" + "\n".join(rows)


# ---------------------------------------------------------------- statistik

def _fmt_rr(value: float | None) -> str:
    return "—" if value is None else f"{value:.2f}"


def _fmt_pf(value: float | None) -> str:
    if value is None:
        return "∞"
    return f"{value:.2f}"


def fmt_stats(agg: dict, period_label: str, settings: Settings) -> str:
    n = agg["trades"]
    if n == 0:
        return (
            f"📊 <b>Statistik — {period_label}</b>\n\n"
            "Belum ada trade di periode ini. Tambahkan dengan /add atau /trade."
        )
    lines = [
        f"📊 <b>Statistik — {period_label}</b>",
        "",
        f"💰 P&L Bersih : {fmt_money(agg['net_pnl'], settings)} ({agg['net_pips']:+,.1f} pips)",
        f"🎯 Win Rate   : {fmt_percent(agg['win_rate'])} ({agg['wins']}W / {agg['losses']}L / {agg['breakeven']}BE)",
        f"📈 Profit Factor : {_fmt_pf(agg['profit_factor'])}",
        f"⚖️ Avg R     : {_fmt_rr(agg['avg_r'])}  |  Avg RR : {_fmt_rr(agg['avg_rr'])}",
    ]
    if agg["best"] is not None and agg["worst"] is not None:
        lines += [
            f"🏆 Terbaik  : #{agg['best'].id} {agg['best'].pair} {direction_emoji(agg['best'].direction)} "
            f"{fmt_money(calc.pnl(agg['best'].pair, agg['best'].direction, agg['best'].entry, agg['best'].exit, agg['best'].lot, settings.usdjpy_rate), settings)}",
            f"🐻 Terburuk : #{agg['worst'].id} {agg['worst'].pair} {direction_emoji(agg['worst'].direction)} "
            f"{fmt_money(calc.pnl(agg['worst'].pair, agg['worst'].direction, agg['worst'].entry, agg['worst'].exit, agg['worst'].lot, settings.usdjpy_rate), settings)}",
        ]
    lines += ["", "📊 <b>Per Pasangan</b>"]
    lines.append(_fmt_group_table(agg["by_pair"], settings))
    lines.append("")
    lines.append("📊 <b>Per Arah</b>")
    lines.append(_fmt_group_table(agg["by_direction"], settings))
    return "\n".join(lines)


def _fmt_group_table(groups: dict[str, dict], settings: Settings) -> str:
    if not groups:
        return "<pre>Belum ada data.</pre>"
    header = "<pre>{:>8} {:>4} {:>8} {:>10} {:>9}</pre>".format("GRUP", "TRD", "WIN%", "P&L", "PIP")
    rows = [
        "<pre>{:>8} {:>4} {:>7.0f}% {:>10,.2f} {:>+8.1f}</pre>".format(
            name, g["trades"], g["win_rate"], g["net_pnl"], g["net_pips"]
        )
        for name, g in groups.items()
    ]
    return header + "\n" + "\n".join(rows)


# ---------------------------------------------------------------- report

def fmt_report_summary(agg: dict, period_label: str, settings: Settings, recent: list[Trade]) -> str:
    lines = [
        f"🗓️ <b>Laporan — {period_label}</b>",
        "",
        f"Jumlah trade : {agg['trades']}",
        f"Win Rate     : {fmt_percent(agg['win_rate'])}",
        f"Profit Factor: {_fmt_pf(agg['profit_factor'])}",
        f"P&L Bersih   : {fmt_money(agg['net_pnl'], settings)}",
        f"Total Pips   : {agg['net_pips']:+,.1f}",
    ]
    if recent:
        lines.append("")
        lines.append("📒 Trade terakhir periode ini:")
        lines.extend(
            f"  #{t.id} {t.pair} {direction_emoji(t.direction)} → "
            f"{fmt_money(calc.pnl(t.pair, t.direction, t.entry, t.exit, t.lot, settings.usdjpy_rate), settings)}"
            for t in recent[:5]
        )
    return "\n".join(lines)


def fmt_settings(settings: Settings) -> str:
    return "\n".join(
        [
            "⚙️ <b>Pengaturan</b>",
            f"· Saldo akun      : {fmt_money(settings.default_balance, settings)}",
            f"· Risiko per trade: {settings.default_risk_percent:g}%",
            f"· Mata uang       : {settings.currency}",
            f"· Kurs USD/JPY    : {settings.usdjpy_rate:g}",
            f"· Batas daily R   : {settings.daily_loss_r:.1f}R",
            f"· Batas daily %   : {settings.daily_loss_percent:.1f}% saldo",
            f"· Zona waktu      : {settings.timezone}",
        ]
    )