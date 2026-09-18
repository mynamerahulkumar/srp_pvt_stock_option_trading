from __future__ import annotations

from rich.theme import Theme

THEME = Theme(
    {
        "term.header": "bold cyan",
        "term.muted": "dim cyan",
        "term.label": "bold bright_black",
        "term.value": "bold white",
        "term.live": "bold green",
        "term.dry": "bold magenta",
        "term.warn": "bold yellow",
        "term.error": "bold red",
        "term.profit": "bold green",
        "term.loss": "bold red",
        "term.border": "cyan",
        "term.accent": "bold bright_cyan",
    }
)

BORDER_STYLE = "cyan"
HEADER_TITLE = "◈ DHAN // QUANT TERMINAL ◈"
HEADER_SUBTITLE = "LIVE EXECUTION ENGINE"
SHUTDOWN_MESSAGE = (
    "⚠ Shutdown requested.\n"
    "Monitoring stopped.\n"
    "Existing broker position was NOT automatically closed."
)


def format_inr(value: float | None, signed: bool = False) -> str:
    if value is None:
        return "—"
    amount = f"₹{abs(value):,.2f}"
    if not signed:
        return f"₹{value:,.2f}"
    if value > 0:
        return f"+{amount}"
    if value < 0:
        return f"-{amount}"
    return amount


def format_percent(value: float | None) -> str:
    if value is None:
        return "—"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.2f}%"


def pnl_style(value: float | None) -> str:
    if value is None or value == 0:
        return "term.value"
    return "term.profit" if value > 0 else "term.loss"
