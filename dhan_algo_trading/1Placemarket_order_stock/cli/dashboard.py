from __future__ import annotations

from datetime import datetime
from typing import Callable, Optional

from rich.align import Align
from rich.console import Console, Group, RenderableType
from rich.panel import Panel
from rich.prompt import Confirm
from rich.table import Table
from rich.text import Text

from cli.styles import (
    BORDER_STYLE,
    HEADER_SUBTITLE,
    HEADER_TITLE,
    THEME,
    format_inr,
    format_percent,
    pnl_style,
)
from trading.models import DashboardState, NOTIONAL_WARNING_THRESHOLD, SessionState


def _status_dot(live: bool, mode: str) -> Text:
    text = Text()
    if mode == "DRY-RUN":
        text.append("● DRY-RUN", style="term.dry")
    elif live:
        text.append("● LIVE", style="term.live")
    else:
        text.append("● IDLE", style="term.muted")
    return text


def _kv_table() -> Table:
    table = Table.grid(padding=(0, 2))
    table.add_column(style="term.label", min_width=16)
    table.add_column(style="term.value", min_width=22)
    table.add_column(style="term.label", min_width=14)
    table.add_column(style="term.value", min_width=18)
    return table


def render_confirmation(
    symbol: str,
    security_id: str,
    instrument_id: str,
    side: str,
    order_type: str,
    quantity: int,
    market_price: Optional[float],
    dry_run: bool,
) -> Panel:
    notional = (market_price or 0) * quantity if market_price else None
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="term.label", min_width=16)
    grid.add_column(style="term.value")
    grid.add_row("Symbol", symbol)
    grid.add_row("Security ID", security_id)
    grid.add_row("Instrument ID", instrument_id)
    grid.add_row("Side", side)
    grid.add_row("Order Type", order_type)
    grid.add_row("Quantity", str(quantity))
    grid.add_row("Market Price", format_inr(market_price))
    grid.add_row("Est. Notional", format_inr(notional))
    if notional and notional > NOTIONAL_WARNING_THRESHOLD:
        grid.add_row("Warning", Text(f"Notional exceeds ₹{NOTIONAL_WARNING_THRESHOLD:,.0f}", style="term.warn"))
    if dry_run:
        grid.add_row("Mode", Text("DRY-RUN — no live order will be sent", style="term.dry"))
    title = "⚠ ORDER EXECUTION REQUEST ⚠"
    return Panel(
        grid,
        title=title,
        subtitle="Default is NO. Live orders require explicit confirmation.",
        border_style="yellow",
        padding=(1, 2),
    )


def prompt_confirmation(
    symbol: str,
    security_id: str,
    instrument_id: str,
    side: str,
    order_type: str,
    quantity: int,
    market_price: Optional[float],
    dry_run: bool,
    console: Optional[Console] = None,
    confirm_fn: Optional[Callable[[], bool]] = None,
) -> bool:
    console = console or Console(theme=THEME)
    console.print(
        render_confirmation(
            symbol, security_id, instrument_id, side, order_type, quantity, market_price, dry_run
        )
    )
    if confirm_fn is not None:
        return bool(confirm_fn())
    question = "Simulate MARKET order?" if dry_run else f"Execute {order_type} {side} order?"
    return Confirm.ask(question, default=False, console=console)


def render_dashboard(state: DashboardState) -> RenderableType:
    header = Text()
    header.append(HEADER_TITLE + "\n", style="term.header")
    header.append(HEADER_SUBTITLE, style="term.muted")
    header.justify = "center"

    top = _kv_table()
    top.add_row(
        "ASSET",
        state.symbol,
        "STATUS",
        _status_dot(state.live, state.mode),
    )
    top.add_row("SECURITY ID", state.security_id, "MODE", state.mode)
    top.add_row("INSTRUMENT ID", state.instrument_id, "ENGINE", state.session_state.value)
    top.add_row("MARKET PRICE", format_inr(state.market_price), "ENTRY PRICE", format_inr(state.entry_price))
    top.add_row("QUANTITY", str(state.quantity), "POSITION QTY", str(state.position_qty))

    side_label = "LONG" if state.position_qty > 0 else ("SHORT" if state.position_qty < 0 else "FLAT")
    position = Table.grid(padding=(0, 2))
    position.add_column(style="term.label", min_width=22)
    position.add_column(min_width=24)
    position.add_row("SIDE", Text(side_label, style="term.accent"))
    position.add_row(
        "Unrealized P&L",
        Text(format_inr(state.pnl.local_pnl, signed=True), style=pnl_style(state.pnl.local_pnl)),
    )
    position.add_row(
        "P&L %",
        Text(format_percent(state.pnl.local_pnl_percent), style=pnl_style(state.pnl.local_pnl_percent)),
    )
    if state.pnl.broker_unrealized_pnl is not None:
        position.add_row(
            "Broker unrealized",
            Text(
                format_inr(state.pnl.broker_unrealized_pnl, signed=True),
                style=pnl_style(state.pnl.broker_unrealized_pnl),
            ),
        )
    if state.realized_pnl is not None or state.pnl.broker_realized_pnl is not None:
        realized = state.realized_pnl if state.realized_pnl is not None else state.pnl.broker_realized_pnl
        position.add_row(
            "Realized P&L",
            Text(format_inr(realized, signed=True), style=pnl_style(realized)),
        )

    risk = Table.grid(padding=(0, 2))
    risk.add_column(style="term.label", min_width=18)
    risk.add_column(style="term.value", min_width=16)
    risk.add_column(style="term.value", min_width=16)
    risk.add_row(
        "TAKE PROFIT",
        format_inr(state.risk.take_profit_price),
        Text(format_inr(state.risk.distance_to_tp, signed=True), style="term.profit"),
    )
    risk.add_row(
        "STOP LOSS",
        format_inr(state.risk.stop_loss_price),
        Text(format_inr(state.risk.distance_to_sl, signed=True), style="term.loss"),
    )
    risk.add_row("TP DISTANCE", format_inr(state.risk.distance_to_tp, signed=True), "")
    risk.add_row("SL DISTANCE", format_inr(state.risk.distance_to_sl, signed=True), "")
    if state.risk.trigger:
        risk.add_row("TRIGGER", Text(state.risk.trigger, style="term.warn"), "")

    footer = _kv_table()
    last_update = state.last_update.strftime("%H:%M:%S") if isinstance(state.last_update, datetime) else "—"
    footer.add_row("ORDER STATUS", state.order_status, "POSITION STATUS", state.position_status)
    footer.add_row("LAST UPDATE", last_update, "NEXT POLL", f"{max(0, int(round(state.next_poll_seconds)))}s")

    sections = [Align.center(header), top, Panel(position, title="POSITION", border_style=BORDER_STYLE), Panel(risk, title="RISK MATRIX", border_style=BORDER_STYLE), footer]
    if state.warning:
        sections.append(Text(f"⚠ {state.warning}", style="term.warn"))
    if state.session_state == SessionState.POSITION_CLOSED:
        sections.append(Text("Session complete. Automatic trading stopped.", style="term.live"))

    return Panel(
        Group(*sections),
        title="QUANT TERMINAL",
        border_style=BORDER_STYLE,
        padding=(1, 2),
    )


class TradingDashboard:
    def __init__(self, console: Optional[Console] = None):
        self.console = console or Console(theme=THEME)

    def render(self, state: DashboardState) -> RenderableType:
        return render_dashboard(state)
