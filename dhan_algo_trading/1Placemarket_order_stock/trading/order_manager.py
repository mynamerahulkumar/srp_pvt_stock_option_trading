from __future__ import annotations

from typing import Optional, Protocol

from trading.dhan_client import DhanClientError, extract_order_id, format_dhan_error, parse_order_payload
from trading.models import OrderSnapshot
from utils.logging import get_logger

logger = get_logger("order_manager")

FILLED_STATUSES = {"FILLED"}
REJECTED_STATUSES = {"REJECTED"}


class OrderClient(Protocol):
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
        ...

    def get_order(self, order_id: str) -> OrderSnapshot:
        ...


class OrderManager:
    def __init__(self, client: OrderClient):
        self.client = client
        self.exit_submitted = False
        self.entry_order_id: Optional[str] = None
        self.exit_order_id: Optional[str] = None

    def place_entry(
        self,
        symbol: str,
        security_id: str,
        exchange_segment: str,
        transaction_type: str,
        quantity: int,
        product_type: str,
        dry_run: bool,
        simulated_price: Optional[float] = None,
    ) -> OrderSnapshot:
        logger.info("Order submitted")
        if dry_run:
            snapshot = self._simulated_fill(
                order_id="DRY-RUN-ENTRY",
                transaction_type=transaction_type,
                quantity=quantity,
                price=simulated_price,
            )
            self.entry_order_id = snapshot.order_id
            logger.info("Order ID: %s", snapshot.order_id)
            logger.info("Order filled")
            return snapshot

        result = self.client.place_market_order(
            symbol=symbol,
            security_id=security_id,
            exchange_segment=exchange_segment,
            transaction_type=transaction_type,
            quantity=quantity,
            product_type=product_type,
            dry_run=False,
        )
        validation = result.get("validation") or {}
        if validation and not validation.get("valid", True):
            errors = "; ".join(validation.get("errors") or ["validation failed"])
            raise DhanClientError(errors)
        inner = result.get("response") if isinstance(result.get("response"), dict) else result
        if str((inner or {}).get("status", result.get("status", ""))).lower() == "failure":
            raise DhanClientError(format_dhan_error(inner or result))

        order_id = extract_order_id(result)
        response = result.get("response") or {}
        data = response.get("data") if isinstance(response, dict) else None
        snapshot = OrderSnapshot(
            order_id=order_id,
            status="PENDING",
            quantity=quantity,
            transaction_type=transaction_type,
        )
        if data:
            try:
                snapshot = parse_order_payload(data, fallback_qty=quantity)
                snapshot.order_id = snapshot.order_id or order_id
            except DhanClientError:
                pass
        if snapshot.status == "NONE":
            snapshot.status = "PENDING"
        self.entry_order_id = snapshot.order_id
        logger.info("Order ID: %s", snapshot.order_id or "unknown")
        return snapshot

    def place_exit(
        self,
        symbol: str,
        security_id: str,
        exchange_segment: str,
        exit_side: str,
        quantity: int,
        product_type: str,
        dry_run: bool,
        simulated_price: Optional[float] = None,
    ) -> Optional[OrderSnapshot]:
        if self.exit_submitted:
            logger.warning("Duplicate exit suppressed")
            return None
        self.exit_submitted = True
        logger.info("Exit order submitted")
        if dry_run:
            snapshot = self._simulated_fill(
                order_id="DRY-RUN-EXIT",
                transaction_type=exit_side,
                quantity=quantity,
                price=simulated_price,
            )
            self.exit_order_id = snapshot.order_id
            return snapshot

        result = self.client.place_market_order(
            symbol=symbol,
            security_id=security_id,
            exchange_segment=exchange_segment,
            transaction_type=exit_side,
            quantity=quantity,
            product_type=product_type,
            dry_run=False,
        )
        validation = result.get("validation") or {}
        if validation and not validation.get("valid", True):
            self.exit_submitted = False
            errors = "; ".join(validation.get("errors") or ["validation failed"])
            raise DhanClientError(errors)
        inner = result.get("response") if isinstance(result.get("response"), dict) else result
        if str((inner or {}).get("status", result.get("status", ""))).lower() == "failure":
            self.exit_submitted = False
            raise DhanClientError(format_dhan_error(inner or result))
        snapshot = OrderSnapshot(
            order_id=extract_order_id(result),
            status="PENDING",
            quantity=quantity,
            transaction_type=exit_side,
        )
        self.exit_order_id = snapshot.order_id
        logger.info("Order ID: %s", snapshot.order_id or "unknown")
        return snapshot

    def refresh(self, order_id: Optional[str], dry_run: bool, current: OrderSnapshot) -> OrderSnapshot:
        if dry_run or not order_id or str(order_id).startswith("DRY-RUN"):
            return current
        try:
            return self.client.get_order(order_id)
        except Exception as exc:
            logger.warning("API request failed; retrying: %s", exc)
            current.error = str(exc)
            return current

    @staticmethod
    def _simulated_fill(order_id: str, transaction_type: str, quantity: int, price: Optional[float]) -> OrderSnapshot:
        return OrderSnapshot(
            order_id=order_id,
            status="FILLED",
            average_traded_price=price,
            filled_quantity=quantity,
            quantity=quantity,
            transaction_type=transaction_type,
            raw_status="TRADED",
        )
