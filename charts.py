"""Renderer grafik — kurva ekuitas P&L (PNG, via matplotlib).

matplotlib bersifat opsional: bila tidak terpasang, return None dan handler
membalas pesan ramah. Import matplotlib TIDAK boleh gagal mematikan bot.
"""

from __future__ import annotations

import io
import logging

from config import Settings, get_tz
from db import Trade
import calc

log = logging.getLogger(__name__)

MATPLOTLIB_AVAILABLE: bool | None = None  # None = belum dicek


def _load_matplotlib():
    """Coba import matplotlib sekali; cache hasilnya."""
    global MATPLOTLIB_AVAILABLE
    if MATPLOTLIB_AVAILABLE is not None:
        return MATPLOTLIB_AVAILABLE
    try:
        import matplotlib
        matplotlib.use("Agg")  # wajib headless (Termux)
        MATPLOTLIB_AVAILABLE = True
        log.info("matplotlib tersedia — /chart aktif")
    except ImportError:
        MATPLOTLIB_AVAILABLE = False
        log.warning("matplotlib tidak terpasang — /chart nonaktif")
    return MATPLOTLIB_AVAILABLE


def try_render_equity_chart(trades: list[Trade], settings: Settings) -> bytes | None:
    """Render kurva ekuitas → PNG bytes; None bila matplotlib tidak tersedia / gagal."""
    if not trades:
        return None
    if not _load_matplotlib():
        return None
    try:
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates

        ordered = sorted(trades, key=lambda t: t.open_time)
        dates = [t.open_time.astimezone(get_tz(settings)) for t in ordered]
        cum = 0.0
        equity: list[float] = []
        for t in ordered:
            cum += calc.pnl(t.pair, t.direction, t.entry, t.exit, t.lot, settings.usdjpy_rate)
            equity.append(cum)

        fig, ax = plt.subplots(figsize=(9, 5), dpi=110)
        ax.plot(dates, equity, marker="o", markersize=4, linewidth=1.8,
                color="#2e7d32" if equity[-1] >= 0 else "#c62828")
        ax.axhline(0, color="#9e9e9e", linewidth=0.8, linestyle="--")
        ax.fill_between(dates, equity, 0, alpha=0.10, color="#2e7d32")
        ax.set_title(f"Kurva Ekuitas Trading Journal ({settings.currency})")
        ax.set_xlabel("Waktu (zona " + settings.timezone + ")")
        ax.set_ylabel("P&L Kumulatif (" + settings.currency + ")")
        ax.grid(True, alpha=0.3)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
        fig.tight_layout()

        buf = io.BytesIO()
        fig.savefig(buf, format="png")
        buf.seek(0)
        png = buf.getvalue()
        buf.close()
        return png
    except ImportError:
        return None
    except Exception:  # noqa: BLE001 — kegagalan render tidak boleh mematikan bot
        log.exception("Gagal render chart")
        return None
    finally:
        try:
            import matplotlib.pyplot as plt
            plt.close("all")
        except Exception:  # noqa: BLE001
            pass