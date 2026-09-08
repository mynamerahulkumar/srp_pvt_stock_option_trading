from __future__ import annotations

import pytest

from trading.risk_manager import calculate_pnl, calculate_pnl_percent


def test_positive_pnl():
    assert calculate_pnl(1950.25, 1967.80, 10, "BUY") == pytest.approx(175.50)
    assert calculate_pnl_percent(1950.25, 1967.80, "BUY") == pytest.approx(0.90, abs=0.01)


def test_negative_pnl():
    assert calculate_pnl(1000.0, 990.0, 10, "BUY") == pytest.approx(-100.0)
    assert calculate_pnl_percent(1000.0, 990.0, "BUY") == pytest.approx(-1.0)


def test_zero_pnl():
    assert calculate_pnl(1000.0, 1000.0, 10, "BUY") == 0
    assert calculate_pnl_percent(1000.0, 1000.0, "BUY") == 0
