from __future__ import annotations

from typing import Optional, Protocol

from trading.models import PositionSnapshot
from utils.logging import get_logger

logger = get_logger("position_manager")


class PositionClient(Protocol):
    def get_position(self, security_id: str) -> PositionSnapshot:
        ...


class PositionManager:
    def __init__(self, client: PositionClient):
        self.client = client
        self.last_good = PositionSnapshot()

    def get_position(self, security_id: str, dry_run: bool = False, simulated: Optional[PositionSnapshot] = None) -> PositionSnapshot:
        if dry_run:
            snapshot = simulated or PositionSnapshot()
            self.last_good = snapshot
            return snapshot
        try:
            snapshot = self.client.get_position(security_id)
            self.last_good = snapshot
            return snapshot
        except Exception as exc:
            logger.warning("API request failed; retrying: %s", exc)
            self.last_good.error = str(exc)
            return self.last_good
