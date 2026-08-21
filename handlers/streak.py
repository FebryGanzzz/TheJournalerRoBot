"""Handler streak — /streak: win/loss streaks & performance stats."""

from __future__ import annotations

import calc
import db
import formatters
from handlers.common import build_settings, check_allowed, extract_user_id
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import CommandHandler, ContextTypes


def _compute_streaks(trades: list[db.Trade], settings) -> dict:
    """Hitung streak dari list trades (sudah diurutkan open_time ASC)."""
    if not trades:
        return {
            "current_streak": 0, "current_type": "-",
            "longest_win": 0, "longest_loss": 0,
            "total_wins": 0, "total_losses": 0,
            "avg_win_pnl": 0.0, "avg_loss_pnl": 0.0,
        }

    ordered = sorted(trades, key=lambda t: t.open_time)
    streaks: list[tuple[str, int]] = []  # (type, count)
    cur_type = None
    cur_count = 0

    for t in ordered:
        p = calc.pnl(t.pair, t.direction, t.entry, t.exit, t.lot, settings.usdjpy_rate)
        t_type = "win" if p > 0 else ("loss" if p < 0 else "be")
        if t_type == "be":
            continue  # skip breakeven dari streak
        if t_type == cur_type:
            cur_count += 1
        else:
            if cur_type is not None:
                streaks.append((cur_type, cur_count))
            cur_type = t_type
            cur_count = 1
    if cur_type is not None:
        streaks.append((cur_type, cur_count))

    # Current streak (dari trade terakhir)
    current_streak = cur_count if streaks else 0
    current_type = cur_type or "-"

    # Longest streaks
    win_streaks = [c for t, c in streaks if t == "win"]
    loss_streaks = [c for t, c in streaks if t == "loss"]
    longest_win = max(win_streaks) if win_streaks else 0
    longest_loss = max(loss_streaks) if loss_streaks else 0

    # Win/loss P&L averages
    wins_pnl = []
    losses_pnl = []
    for t in ordered:
        p = calc.pnl(t.pair, t.direction, t.entry, t.exit, t.lot, settings.usdjpy_rate)
        if p > 0:
            wins_pnl.append(p)
        elif p < 0:
            losses_pnl.append(p)

    from statistics import mean as _mean
    return {
        "current_streak": current_streak,
        "current_type": current_type,
        "longest_win": longest_win,
        "longest_loss": longest_loss,
        "total_wins": len(wins_pnl),
        "total_losses": len(losses_pnl),
        "avg_win_pnl": round(_mean(wins_pnl), 2) if wins_pnl else 0.0,
        "avg_loss_pnl": round(_mean(losses_pnl), 2) if losses_pnl else 0.0,
    }


async def cmd_streak(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await check_allowed(update, context):
        return
    uid = extract_user_id(update)
    s = build_settings(uid)

    with db.get_conn() as conn:
        trades = db.list_trades(conn, uid)

    if not trades:
        await update.effective_message.reply_text(
            "Belum ada trade. Tambahkan dengan /add atau /trade."
        )
        return

    streaks = _compute_streaks(trades, s)

    # Current streak emoji
    if streaks["current_type"] == "win":
        cur_emoji = "🟢"
        cur_label = "WIN"
    elif streaks["current_type"] == "loss":
        cur_emoji = "🔴"
        cur_label = "LOSS"
    else:
        cur_emoji = "⚪"
        cur_label = "-"

    lines = [
        "🔥 <b>Streak & Konsistensi</b>",
        "",
        f"Sebentar: {cur_emoji} <b>{streaks['current_streak']}x {cur_label}</b>",
        f"🏆 Win streak terpanjang: <b>{streaks['longest_win']}x</b>",
        f"🐻 Loss streak terpanjang: <b>{streaks['longest_loss']}x</b>",
        "",
        f"📊 Total: {streaks['total_wins']}W / {streaks['total_losses']}L",
        f"💰 Rata-rata win: {formatters.fmt_money(streaks['avg_win_pnl'], s)}",
        f"💸 Rata-rata loss: {formatters.fmt_money(streaks['avg_loss_pnl'], s)}",
    ]

    # Consistency score: % of wins in last 10 trades
    ordered = sorted(trades, key=lambda t: t.open_time)
    last_10 = ordered[-10:]
    if last_10:
        wins_last10 = sum(
            1 for t in last_10
            if calc.pnl(t.pair, t.direction, t.entry, t.exit, t.lot, s.usdjpy_rate) > 0
        )
        consistency = wins_last10 / len(last_10) * 100
        bar_len = 10
        filled = round(wins_last10 / len(last_10) * bar_len)
        bar = "█" * filled + "░" * (bar_len - filled)
        lines += [
            "",
            f"📈 Konsistensi (10 trade terakhir):",
            f"   {bar} {wins_last10}/{len(last_10)} ({consistency:.0f}%)",
        ]

    await update.effective_message.reply_text(
        "\n".join(lines), parse_mode=ParseMode.HTML
    )


def handlers() -> list[object]:
    return [CommandHandler(["streak", "streaks"], cmd_streak)]
