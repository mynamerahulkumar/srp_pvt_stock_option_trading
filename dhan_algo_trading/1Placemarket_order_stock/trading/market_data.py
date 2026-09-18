from __future__ import annotations

from typing import Optional, Protocol

from trading.dhan_client import DhanClientError
from utils.logging import get_logger

logger = get_logger("market_data")


class PriceClient(Protocol):
    def get_ltp(self, security_id: str, exchange_segment: str) -> Optional[float]:
        ...


class MarketDataService:
    def __init__(self, client: PriceClient):
        self.client = client
        self.last_good_price: Optional[float] = None
        self.last_error: Optional[str] = None

    def get_latest_price(self, security_id: str, exchange_segment: str) -> Optional[float]:
        try:
            price = self.client.get_ltp(security_id, exchange_segment)
            if price is None:
                raise DhanClientError("Missing market price")
            self.last_good_price = price
            self.last_error = None
            return price
        except Exception as exc:
            self.last_error = str(exc)
            logger.warning("API request failed; retrying: %s", exc)
            return self.last_good_price
