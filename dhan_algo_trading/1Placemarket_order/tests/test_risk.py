from __future__ import annotations

import pytest

from trading.risk_manager import (
    calculate_stop_loss,
    calculate_take_profit,
    should_trigger_sl,
    should_trigger_tp,
)
from trading.models import RiskConfig
from trading.risk_manager import evaluate_risk


def test_correct_tp_calculation():
    assert calculate_take_profit(1000.0, take_profit_percent=2.0, side="BUY") == pytest.approx(1020.0)


def test_correct_sl_calculation():
    assert calculate_stop_loss(1000.0, stop_loss_percent=1.0, side="BUY") == pytest.approx(990.0)


def test_absolute_tp_sl_prices_override_percent():
    assert calculate_take_profit(1000.0, take_profit_percent=2.0, take_profit_price=1100.0) == 1100.0
    assert calculate_stop_loss(1000.0, stop_loss_percent=1.0, stop_loss_price=950.0) == 950.0


def test_tp_trigger():
    assert should_trigger_tp(1020.0, 1020.0, side="BUY")
    assert should_trigger_tp(1021.0, 1020.0, side="BUY")
    assert not should_trigger_tp(1019.0, 1020.0, side="BUY")


def test_sl_trigger():
    assert should_trigger_sl(990.0, 990.0, side="BUY")
    assert should_trigger_sl(989.0, 990.0, side="BUY")
    assert not should_trigger_sl(991.0, 990.0, side="BUY")


def test_evaluate_risk_sets_trigger():
    risk = RiskConfig(take_profit_percent=2.0, stop_loss_percent=1.0)
    snapshot, _pnl = evaluate_risk(1000.0, 1025.0, 1, "BUY", risk)
    assert snapshot.trigger == "TP"
    snapshot, _pnl = evaluate_risk(1000.0, 980.0, 1, "BUY", risk)
    assert snapshot.trigger == "SL"
    snapshot, _pnl = evaluate_risk(1000.0, 1005.0, 1, "BUY", risk)
    assert snapshot.trigger is None
