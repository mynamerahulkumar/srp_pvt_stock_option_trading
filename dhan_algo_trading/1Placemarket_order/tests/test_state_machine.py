from __future__ import annotations

import pytest

from trading.models import OrderSnapshot, SessionState
from tests.fakes import FakeDhanClient, make_session


def _fill_entry(client: FakeDhanClient, price: float = 1000.0, qty: int = 1) -> None:
    client.entry_order = OrderSnapshot(
        order_id="E1",
        status="FILLED",
        average_traded_price=price,
        filled_quantity=qty,
        quantity=qty,
        transaction_type="BUY",
        raw_status="TRADED",
    )


def test_order_pending_then_filled():
    client = FakeDhanClient(ltp=1000.0)
    session = make_session(client)
    session.submit_entry()
    assert session.session_state == SessionState.ORDER_PENDING
    _fill_entry(client)
    state = session.tick()
    assert state.session_state in {SessionState.ORDER_FILLED, SessionState.POSITION_OPEN}
    assert session.session_state == SessionState.POSITION_OPEN
    assert session.entry_price == 1000.0


def test_tp_triggers_single_exit_then_closes():
    client = FakeDhanClient(ltp=1000.0)
    session = make_session(client)
    session.submit_entry()
    _fill_entry(client)
    session.tick()
    assert session.session_state == SessionState.POSITION_OPEN

    client.ltp = 1020.0
    session.tick()
    sell_calls = [call for call in client.place_calls if call["transaction_type"] == "SELL"]
    assert len(sell_calls) == 1
    assert session.session_state == SessionState.EXIT_ORDER_SUBMITTED

    client.ltp = 1030.0
    session.tick()
    sell_calls = [call for call in client.place_calls if call["transaction_type"] == "SELL"]
    assert len(sell_calls) == 1

    client.exit_order = OrderSnapshot(
        order_id="X1",
        status="FILLED",
        average_traded_price=1020.0,
        filled_quantity=1,
        quantity=1,
        transaction_type="SELL",
        raw_status="TRADED",
    )
    session.tick()
    assert session.session_state == SessionState.POSITION_CLOSED
    assert session.realized_pnl == 20.0


def test_sl_triggered():
    client = FakeDhanClient(ltp=1000.0)
    session = make_session(client)
    session.submit_entry()
    _fill_entry(client)
    session.tick()
    client.ltp = 990.0
    session.tick()
    assert session.session_state in {
        SessionState.SL_TRIGGERED,
        SessionState.EXIT_TRIGGERED,
        SessionState.EXIT_ORDER_SUBMITTED,
        SessionState.EXIT_FILLED,
        SessionState.POSITION_CLOSED,
    }
    assert any(call["transaction_type"] == "SELL" for call in client.place_calls)


def test_dry_run_fills_and_exits_without_live_orders():
    client = FakeDhanClient(ltp=1000.0)
    session = make_session(client, dry_run=True)
    session.submit_entry()
    assert session.session_state == SessionState.POSITION_OPEN
    assert session.entry_price == 1000.0
    assert client.place_calls == []
    client.ltp = 1020.0
    session.tick()
    assert session.session_state == SessionState.POSITION_CLOSED
    assert client.place_calls == []
    session.tick()
    assert session.orders.exit_submitted
    assert client.place_calls == []


def test_uses_average_traded_price_not_ltp_as_entry():
    client = FakeDhanClient(ltp=1005.0)
    session = make_session(client)
    session.submit_entry()
    _fill_entry(client, price=997.5)
    session.tick()
    assert session.entry_price == 997.5
    assert session.risk_snapshot.take_profit_price == pytest.approx(1017.45)
