from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


NOTIONAL_WARNING_THRESHOLD = 50_000.0
PLACEHOLDER_IDS = {"", "<SECURITY_ID>", "<INSTRUMENT_ID>"}


class SessionState(str, Enum):
    IDLE = "IDLE"
    ORDER_PENDING = "ORDER_PENDING"
    ORDER_FILLED = "ORDER_FILLED"
    ORDER_REJECTED = "ORDER_REJECTED"
    POSITION_OPEN = "POSITION_OPEN"
    TP_TRIGGERED = "TP_TRIGGERED"
    SL_TRIGGERED = "SL_TRIGGERED"
    EXIT_TRIGGERED = "EXIT_TRIGGERED"
    EXIT_ORDER_SUBMITTED = "EXIT_ORDER_SUBMITTED"
    EXIT_FILLED = "EXIT_FILLED"
    POSITION_CLOSED = "POSITION_CLOSED"
    ERROR = "ERROR"


EXIT_GUARD_STATES = frozenset(
    {
        SessionState.TP_TRIGGERED,
        SessionState.SL_TRIGGERED,
        SessionState.EXIT_TRIGGERED,
        SessionState.EXIT_ORDER_SUBMITTED,
        SessionState.EXIT_FILLED,
        SessionState.POSITION_CLOSED,
    }
)

TERMINAL_STATES = frozenset(
    {
        SessionState.POSITION_CLOSED,
        SessionState.ORDER_REJECTED,
        SessionState.ERROR,
    }
)


@dataclass(frozen=True)
class InstrumentConfig:
    symbol: str
    exchange_segment: str
    security_id: str
    instrument_id: str


@dataclass(frozen=True)
class RiskConfig:
    take_profit_percent: float
    stop_loss_percent: float
    take_profit_price: Optional[float] = None
    stop_loss_price: Optional[float] = None


@dataclass(frozen=True)
class TradingConfig:
    default_symbol: str
    quantity: int
    transaction_type: str
    order_type: str
    product_type: str
    polling_interval_seconds: float
    risk: RiskConfig
    instrument: InstrumentConfig
    dry_run: bool = False


@dataclass
class OrderSnapshot:
    order_id: Optional[str] = None
    status: str = "NONE"
    average_traded_price: Optional[float] = None
    filled_quantity: int = 0
    quantity: int = 0
    transaction_type: str = "BUY"
    raw_status: str = ""
    error: Optional[str] = None


@dataclass
class PositionSnapshot:
    net_qty: int = 0
    average_price: Optional[float] = None
    unrealized_pnl: Optional[float] = None
    realized_pnl: Optional[float] = None
    last_price: Optional[float] = None
    error: Optional[str] = None


@dataclass
class PnLSnapshot:
    local_pnl: Optional[float] = None
    local_pnl_percent: Optional[float] = None
    broker_unrealized_pnl: Optional[float] = None
    broker_realized_pnl: Optional[float] = None


@dataclass
class RiskSnapshot:
    take_profit_price: Optional[float] = None
    stop_loss_price: Optional[float] = None
    distance_to_tp: Optional[float] = None
    distance_to_sl: Optional[float] = None
    trigger: Optional[str] = None


@dataclass
class DashboardState:
    symbol: str
    security_id: str
    instrument_id: str
    mode: str
    session_state: SessionState = SessionState.IDLE
    market_price: Optional[float] = None
    entry_price: Optional[float] = None
    quantity: int = 0
    position_qty: int = 0
    pnl: PnLSnapshot = field(default_factory=PnLSnapshot)
    risk: RiskSnapshot = field(default_factory=RiskSnapshot)
    order_status: str = "NONE"
    position_status: str = "FLAT"
    last_update: Optional[datetime] = None
    next_poll_seconds: float = 0.0
    warning: Optional[str] = None
    realized_pnl: Optional[float] = None
    live: bool = True
