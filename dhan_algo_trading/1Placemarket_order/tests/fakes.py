from __future__ import annotations

from typing import Optional

from trading.models import OrderSnapshot, PositionSnapshot, TradingConfig
from trading.session import TradingSession
from utils.config import validate_and_build


def sample_raw_config() -> dict:
    return {
        "trading": {
            "default_symbol": "HDFCBANK",
            "quantity": 1,
            "transaction_type": "BUY",
            "order_type": "MARKET",
            "product_type": "CNC",
            "polling": {"interval_seconds": 5},
            "risk": {"take_profit_percent": 2.0, "stop_loss_percent": 1.0},
        },
        "instruments": {
            "HDFCBANK": {
                "exchange_segment": "NSE_EQ",
                "security_id": "1333",
                "instrument_id": "1333",
            }
        },
    }


def make_config(**overrides) -> TradingConfig:
    raw = sample_raw_config()
    trading_overrides = overrides.pop("trading", None)
    if trading_overrides:
        raw["trading"].update(trading_overrides)
    dry_run = overrides.pop("dry_run", False)
    symbol = overrides.pop("symbol", None)
    config = validate_and_build(raw, symbol=symbol, dry_run=dry_run)
    return config


class FakeDhanClient:
    def __init__(self, ltp: float = 1000.0):
        self.ltp = ltp
        self.entry_order = OrderSnapshot(order_id="E1", status="PENDING", quantity=1, transaction_type="BUY")
        self.exit_order = OrderSnapshot(order_id="X1", status="PENDING", quantity=1, transaction_type="SELL")
        self.position = PositionSnapshot()
        self.place_calls: list[dict] = []
        self.resolve = {"security_id": "1333", "trading_symbol": "HDFCBANK"}
        self.fail_ltp: Optional[str] = None

    def get_ltp(self, security_id: str, exchange_segment: str) -> float:
        if self.fail_ltp:
            raise RuntimeError(self.fail_ltp)
        return self.ltp

    def place_market_order(
        self,
        symbol: str,
        security_id: str,
        exchange_segment: str,
        transaction_type: str,
        quantity: int,
        product_type: str,
        dry_run: bool = False,
    ) -> dict:
        self.place_calls.append(
            {
                "symbol": symbol,
                "security_id": security_id,
                "exchange_segment": exchange_segment,
                "transaction_type": transaction_type,
                "quantity": quantity,
                "product_type": product_type,
                "dry_run": dry_run,
            }
        )
        order_id = "E1" if transaction_type == "BUY" else "X1"
        return {"status": "success", "response": {"status": "success", "data": {"orderId": order_id, "orderStatus": "PENDING"}}}

    def get_order(self, order_id: str) -> OrderSnapshot:
        if str(order_id) == "X1":
            return self.exit_order
        return self.entry_order

    def get_position(self, security_id: str) -> PositionSnapshot:
        return self.position

    def resolve_symbol(self, symbol: str, exchange_segment: str) -> dict:
        return self.resolve


def make_session(client: FakeDhanClient | None = None, dry_run: bool = False, **kwargs) -> TradingSession:
    config = make_config(dry_run=dry_run, **kwargs)
    client = client or FakeDhanClient()
    return TradingSession(config, client=client, confirm_fn=lambda: True)
