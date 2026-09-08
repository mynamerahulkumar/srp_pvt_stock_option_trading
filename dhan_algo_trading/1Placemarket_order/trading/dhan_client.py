from __future__ import annotations

from typing import Any, Optional

from trading.models import OrderSnapshot, PositionSnapshot
from utils.logging import get_logger

logger = get_logger("dhan_client")


class DhanClientError(RuntimeError):
    """Raised when a Dhan API call fails or returns an unexpected payload."""


def _as_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def unwrap_sdk(response: Any) -> Any:
    if not isinstance(response, dict):
        return response
    status = str(response.get("status", "")).lower()
    if status == "failure":
        remarks = response.get("remarks") or response
        raise DhanClientError(f"Dhan API failure: {remarks}")
    if "data" in response:
        return response["data"]
    return response


def extract_order_id(place_result: dict[str, Any]) -> Optional[str]:
    response = place_result.get("response", place_result)
    data = response.get("data") if isinstance(response, dict) else None
    if isinstance(data, dict):
        order_id = data.get("orderId") or data.get("order_id")
        return str(order_id) if order_id is not None else None
    if isinstance(data, list) and data:
        order_id = data[0].get("orderId") or data[0].get("order_id")
        return str(order_id) if order_id is not None else None
    return None


def parse_order_payload(data: Any, fallback_qty: int = 0) -> OrderSnapshot:
    if isinstance(data, list):
        data = data[0] if data else {}
    if not isinstance(data, dict):
        raise DhanClientError("Unexpected order payload")
    raw_status = str(
        data.get("orderStatus") or data.get("order_status") or data.get("status") or ""
    ).upper()
    filled = _as_int(data.get("filledQty") or data.get("filled_qty") or data.get("tradedQuantity") or 0)
    quantity = _as_int(data.get("quantity") or fallback_qty)
    avg = _as_float(data.get("averageTradedPrice") or data.get("average_traded_price") or data.get("price"))
    mapped = _map_order_status(raw_status, filled, quantity)
    return OrderSnapshot(
        order_id=str(data.get("orderId") or data.get("order_id") or "") or None,
        status=mapped,
        average_traded_price=avg if avg and avg > 0 else None,
        filled_quantity=filled,
        quantity=quantity,
        transaction_type=str(data.get("transactionType") or data.get("transaction_type") or "BUY").upper(),
        raw_status=raw_status,
    )


def _map_order_status(raw_status: str, filled: int, quantity: int) -> str:
    if raw_status in {"TRADED", "FILLED", "COMPLETE", "COMPLETED"}:
        return "FILLED"
    if raw_status in {"REJECTED", "CANCELLED", "CANCELED", "EXPIRED", "FAILED"}:
        return "REJECTED"
    if filled > 0 and quantity and filled < quantity:
        return "PARTIAL"
    if raw_status in {"PENDING", "TRANSIT", "OPEN", "TRIGGER_PENDING", "PART_TRADED"}:
        return "PENDING"
    if filled > 0:
        return "FILLED" if not quantity or filled >= quantity else "PARTIAL"
    return raw_status or "PENDING"


def parse_position_payload(data: Any, security_id: str) -> PositionSnapshot:
    rows = data
    if isinstance(data, dict):
        rows = data.get("positions") or data.get("data") or []
        if isinstance(rows, dict):
            rows = [rows]
    if rows is None:
        rows = []
    if not isinstance(rows, list):
        raise DhanClientError("Unexpected positions payload")

    target = str(security_id)
    for row in rows:
        if not isinstance(row, dict):
            continue
        row_id = str(row.get("securityId") or row.get("security_id") or "")
        if row_id != target:
            continue
        return PositionSnapshot(
            net_qty=_as_int(row.get("netQty") or row.get("net_qty") or 0),
            average_price=_as_float(row.get("averagePrice") or row.get("costPrice") or row.get("buyAvg")),
            unrealized_pnl=_as_float(row.get("unrealizedProfit") or row.get("unrealized_pnl")),
            realized_pnl=_as_float(row.get("realizedProfit") or row.get("realized_pnl")),
            last_price=_as_float(row.get("ltp") or row.get("last_price")),
        )
    return PositionSnapshot()


def extract_ltp(ticker_response: Any, security_id: str) -> Optional[float]:
    payload = unwrap_sdk(ticker_response)
    if isinstance(payload, dict) and "data" in payload and isinstance(payload["data"], dict):
        payload = payload["data"]
    if not isinstance(payload, dict):
        return None
    target = str(security_id)
    for _exchange, contracts in payload.items():
        if not isinstance(contracts, dict):
            continue
        for key, values in contracts.items():
            if str(key) != target:
                continue
            if isinstance(values, dict):
                price = _as_float(values.get("last_price") or values.get("ltp") or values.get("lastPrice"))
                if price is not None:
                    return price
            else:
                return _as_float(values)
    return None


class DhanClient:
    """Thin adapter over Dhansrp. Instantiates the broker lazily so tests can inject fakes."""

    def __init__(self, broker: Any = None):
        self.broker = broker if broker is not None else self._build_broker()

    def _build_broker(self) -> Any:
        from utils.compat import ensure_dhanhq_importable

        ensure_dhanhq_importable()
        from Dhan_SRP import Dhansrp
        import pandas as pd

        class ConfigDrivenDhansrp(Dhansrp):
            def get_instrument_file(self):
                logger.info("Using security_id from config.yaml; skipping security master CSV")
                self.instrument_df = pd.DataFrame()
                return self.instrument_df

        logger.info("Market data connection established")
        return ConfigDrivenDhansrp()

    def get_ltp(self, security_id: str, exchange_segment: str) -> Optional[float]:
        instruments = {
            "NSE_EQ": [],
            "IDX_I": [],
            "NSE_FNO": [],
            "NSE_CURRENCY": [],
            "BSE_EQ": [],
            "BSE_FNO": [],
            "BSE_CURRENCY": [],
            "MCX_COMM": [],
        }
        instruments.setdefault(exchange_segment, [])
        instruments[exchange_segment].append(int(security_id))
        response = self.broker.Dhan.ticker_data(instruments)
        price = extract_ltp(response, security_id)
        if price is None:
            raise DhanClientError(f"Missing market price for security_id {security_id}")
        return price

    def place_market_order(
        self,
        symbol: str,
        security_id: str,
        exchange_segment: str,
        transaction_type: str,
        quantity: int,
        product_type: str,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        return self.broker.place_order(
            symbol=symbol,
            security_id=str(security_id),
            exchange_segment=exchange_segment,
            transaction_type=transaction_type,
            quantity=quantity,
            order_type="MARKET",
            product_type=product_type,
            price=0,
            lot_size=1,
            dry_run=dry_run,
        )

    def get_order(self, order_id: str) -> OrderSnapshot:
        response = self.broker.Dhan.get_order_by_id(order_id=order_id)
        data = unwrap_sdk(response)
        return parse_order_payload(data)

    def get_position(self, security_id: str) -> PositionSnapshot:
        response = self.broker.Dhan.get_positions()
        data = unwrap_sdk(response)
        return parse_position_payload(data, security_id)

    def resolve_symbol(self, symbol: str, exchange_segment: str) -> Optional[dict[str, Any]]:
        resolver = getattr(self.broker, "resolve_symbol", None)
        if resolver is None:
            return None
        return resolver(symbol, exchange_segment=exchange_segment, instrument_name="EQUITY")
