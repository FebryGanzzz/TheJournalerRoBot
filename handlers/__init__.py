"""Paket handler — registrasi semua perintah Telegram."""

from __future__ import annotations


def all_handlers() -> list[object]:
    """Kumpulkan semua handler dari sub-modul."""
    from handlers.trade import handlers as trade_handlers
    from handlers.stats import handlers as stats_handlers
    from handlers.report import handlers as report_handlers
    from handlers.risk import handlers as risk_handlers
    from handlers.panel import handlers as panel_handlers
    from handlers.webapp import handlers as webapp_handlers
    from handlers.streak import handlers as streak_handlers
    from handlers.sessions import handlers as session_handlers

    return (
        trade_handlers()
        + stats_handlers()
        + report_handlers()
        + risk_handlers()
        + panel_handlers()
        + webapp_handlers()
        + streak_handlers()
        + session_handlers()
    )
