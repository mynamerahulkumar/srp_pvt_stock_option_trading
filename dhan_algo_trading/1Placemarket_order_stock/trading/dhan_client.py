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


def format_dhan_error(response: Any) -> str:
    if not isinstance(response, dict):
        return str(response)
    remarks = response.get("remarks")
    if isinstance(remarks, dict):
        code = remarks.get("error_code")
        message = remarks.get("error_message") or remarks.get("error_type")
        if code or message:
            return f"{code or 'DHAN'}: {message or 'request failed'}"
        return (
            "Dhan API returned failure with no error details. "
            "Check access token, static IP whitelist, Data API plan, and market hours."
        )
    if remarks:
        return str(remarks)
    return str(response)


def unwrap_sdk(response: Any) -> Any:
    if not isinstance(response, dict):
        return response
    status = str(response.get("status", "")).lower()
    if status == "failure":
        raise DhanClientError(format_dhan_error(response))
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
    payload = ticker_response
    if isinstance(payload, dict) and payload.get("status") != "failure":
        if "data" in payload:
            payload = payload.get("data")
    elif isinstance(payload, dict) and "data" in payload:
        payload = payload.get("data")
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
                price = _as_float(
                    values.get("last_price")
                    or values.get("ltp")
                    or values.get("lastPrice")
                    or (values.get("ohlc") or {}).get("close")
                )
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
                self.instrument_df = pd.DataFrame(
                    columns=[
                        "SEM_TRADING_SYMBOL",
                        "SEM_CUSTOM_SYMBOL",
                        "SEM_EXM_EXCH_ID",
                        "SEM_SMST_SECURITY_ID",
                        "SEM_INSTRUMENT_NAME",
                        "SEM_EXPIRY_CODE",
                        "SEM_LOT_UNITS",
                        "SEM_TICK_SIZE",
                        "SEM_EXPIRY_DATE",
                        "SEM_STRIKE_PRICE",
                        "SEM_OPTION_TYPE",
                        "SM_SYMBOL_NAME",
                    ]
                )
                return self.instrument_df

            def get_start_date(self):
                import datetime as dt

                to_date = dt.datetime.now().strftime("%Y-%m-%d")
                start_date = (dt.datetime.now() - dt.timedelta(days=5)).strftime("%Y-%m-%d")
                return start_date, to_date

        logger.info("Market data connection established")
        return ConfigDrivenDhansrp()

    def get_ltp(self, security_id: str, exchange_segment: str) -> Optional[float]:
        instruments = {exchange_segment: [int(security_id)]}
        last_error = None
        for method_name in ("ticker_data", "ohlc_data", "quote_data"):
            method = getattr(self.broker.Dhan, method_name, None)
            if method is None:
                continue
            try:
                response = method(instruments)
            except Exception as exc:
                last_error = str(exc)
                continue
            price = extract_ltp(response, security_id)
            if price is not None:
                return price
            if isinstance(response, dict) and str(response.get("status", "")).lower() == "failure":
                last_error = format_dhan_error(response)
        raise DhanClientError(last_error or f"Missing market price for security_id {security_id}")

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
        if dry_run:
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
                dry_run=True,
            )
        dhan = self.broker.Dhan
        payload = {
            "security_id": str(security_id),
            "exchange_segment": self.broker._sdk_exchange_segment(exchange_segment),
            "transaction_type": self.broker._sdk_transaction_type(transaction_type),
            "quantity": int(quantity),
            "order_type": self.broker._sdk_order_type("MARKET"),
            "product_type": self.broker._sdk_product_type(product_type),
            "price": 0,
            "trigger_price": 0,
        }
        logger.info("Placing MARKET %s %s security_id=%s qty=%s", transaction_type, symbol, security_id, quantity)
        try:
            response = dhan.place_order(**payload)
        except TypeError:
            response = dhan.place_order(
                payload["security_id"],
                payload["exchange_segment"],
                payload["transaction_type"],
                payload["quantity"],
                payload["order_type"],
                payload["product_type"],
                payload["price"],
            )
        if not isinstance(response, dict):
            raise DhanClientError(f"Unexpected place_order response: {response}")
        return {
            "status": response.get("status") if isinstance(response, dict) else "unknown",
            "instrument": {"security_id": str(security_id), "trading_symbol": symbol, "exchange_segment": exchange_segment},
            "validation": {"valid": True, "errors": [], "warnings": []},
            "response": response,
        }

    def get_order(self, order_id: str) -> OrderSnapshot:
        getter = self.broker.Dhan.get_order_by_id
        try:
            response = getter(order_id=order_id)
        except TypeError:
            response = getter(order_id)
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
