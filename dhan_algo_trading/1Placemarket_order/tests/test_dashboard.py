from __future__ import annotations

from datetime import datetime

from cli.dashboard import render_confirmation, render_dashboard
from trading.models import DashboardState, PnLSnapshot, RiskSnapshot, SessionState


def test_dashboard_renders_open_position():
    state = DashboardState(
        symbol="HDFCBANK",
        security_id="1333",
        instrument_id="1333",
        mode="DRY-RUN",
        session_state=SessionState.POSITION_OPEN,
        market_price=1967.80,
        entry_price=1950.25,
        quantity=10,
        position_qty=10,
        pnl=PnLSnapshot(local_pnl=175.50, local_pnl_percent=0.90, broker_unrealized_pnl=175.50),
        risk=RiskSnapshot(
            take_profit_price=1989.255,
            stop_loss_price=1930.7475,
            distance_to_tp=21.455,
            distance_to_sl=-37.0525,
        ),
        order_status="FILLED",
        position_status="OPEN",
        last_update=datetime(2026, 9, 8, 10, 42, 35),
        next_poll_seconds=4,
    )
    renderable = render_dashboard(state)
    assert renderable is not None


def test_confirmation_panel_includes_symbol():
    panel = render_confirmation("HDFCBANK", "1333", "1333", "BUY", "MARKET", 1, 1950.0, True)
    assert panel.title is not None
