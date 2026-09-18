from __future__ import annotations

from typing import Optional

from trading.models import PnLSnapshot, RiskConfig, RiskSnapshot


def calculate_take_profit(
    entry_price: float,
    take_profit_percent: Optional[float] = None,
    take_profit_price: Optional[float] = None,
    side: str = "BUY",
) -> float:
    if entry_price <= 0:
        raise ValueError("entry_price must be greater than 0")
    if take_profit_price is not None:
        return float(take_profit_price)
    if take_profit_percent is None:
        raise ValueError("Either take_profit_percent or take_profit_price is required")
    if side.upper() == "BUY":
        return entry_price * (1.0 + take_profit_percent / 100.0)
    return entry_price * (1.0 - take_profit_percent / 100.0)


def calculate_stop_loss(
    entry_price: float,
    stop_loss_percent: Optional[float] = None,
    stop_loss_price: Optional[float] = None,
    side: str = "BUY",
) -> float:
    if entry_price <= 0:
        raise ValueError("entry_price must be greater than 0")
    if stop_loss_price is not None:
        return float(stop_loss_price)
    if stop_loss_percent is None:
        raise ValueError("Either stop_loss_percent or stop_loss_price is required")
    if side.upper() == "BUY":
        return entry_price * (1.0 - stop_loss_percent / 100.0)
    return entry_price * (1.0 + stop_loss_percent / 100.0)


def calculate_pnl(entry_price: float, current_price: float, quantity: int, side: str = "BUY") -> float:
    if side.upper() == "BUY":
        return (current_price - entry_price) * quantity
    return (entry_price - current_price) * quantity


def calculate_pnl_percent(entry_price: float, current_price: float, side: str = "BUY") -> float:
    if entry_price == 0:
        return 0.0
    if side.upper() == "BUY":
        return ((current_price - entry_price) / entry_price) * 100.0
    return ((entry_price - current_price) / entry_price) * 100.0


def should_trigger_tp(current_price: Optional[float], take_profit_price: Optional[float], side: str = "BUY") -> bool:
    if current_price is None or take_profit_price is None:
        return False
    if side.upper() == "BUY":
        return current_price >= take_profit_price
    return current_price <= take_profit_price


def should_trigger_sl(current_price: Optional[float], stop_loss_price: Optional[float], side: str = "BUY") -> bool:
    if current_price is None or stop_loss_price is None:
        return False
    if side.upper() == "BUY":
        return current_price <= stop_loss_price
    return current_price >= stop_loss_price


def evaluate_risk(
    entry_price: Optional[float],
    current_price: Optional[float],
    quantity: int,
    side: str,
    risk: RiskConfig,
    broker_unrealized: Optional[float] = None,
    broker_realized: Optional[float] = None,
) -> tuple[RiskSnapshot, PnLSnapshot]:
    risk_snapshot = RiskSnapshot()
    pnl_snapshot = PnLSnapshot(
        broker_unrealized_pnl=broker_unrealized,
        broker_realized_pnl=broker_realized,
    )
    if entry_price is None or entry_price <= 0:
        return risk_snapshot, pnl_snapshot

    tp = calculate_take_profit(
        entry_price,
        take_profit_percent=risk.take_profit_percent if risk.take_profit_price is None else None,
        take_profit_price=risk.take_profit_price,
        side=side,
    )
    sl = calculate_stop_loss(
        entry_price,
        stop_loss_percent=risk.stop_loss_percent if risk.stop_loss_price is None else None,
        stop_loss_price=risk.stop_loss_price,
        side=side,
    )
    risk_snapshot.take_profit_price = tp
    risk_snapshot.stop_loss_price = sl

    if current_price is not None:
        if side.upper() == "BUY":
            risk_snapshot.distance_to_tp = tp - current_price
            risk_snapshot.distance_to_sl = sl - current_price
        else:
            risk_snapshot.distance_to_tp = current_price - tp
            risk_snapshot.distance_to_sl = current_price - sl
        pnl_snapshot.local_pnl = calculate_pnl(entry_price, current_price, quantity, side)
        pnl_snapshot.local_pnl_percent = calculate_pnl_percent(entry_price, current_price, side)
        if should_trigger_tp(current_price, tp, side):
            risk_snapshot.trigger = "TP"
        elif should_trigger_sl(current_price, sl, side):
            risk_snapshot.trigger = "SL"
    return risk_snapshot, pnl_snapshot
