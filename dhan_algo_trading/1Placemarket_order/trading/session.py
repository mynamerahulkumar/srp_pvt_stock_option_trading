from __future__ import annotations

import signal
import time
from datetime import datetime
from typing import Any, Callable, Optional

from trading.dhan_client import DhanClient, DhanClientError
from trading.market_data import MarketDataService
from trading.models import (
    EXIT_GUARD_STATES,
    TERMINAL_STATES,
    DashboardState,
    OrderSnapshot,
    PositionSnapshot,
    PnLSnapshot,
    RiskSnapshot,
    SessionState,
    TradingConfig,
)
from trading.order_manager import OrderManager
from trading.position_manager import PositionManager
from trading.risk_manager import calculate_pnl, evaluate_risk
from utils.logging import get_logger

logger = get_logger("session")


class TradingSession:
    def __init__(
        self,
        config: TradingConfig,
        client: Optional[Any] = None,
        confirm_fn: Optional[Callable[[], bool]] = None,
        dashboard: Optional[Any] = None,
    ):
        self.config = config
        self._client = client
        self.confirm_fn = confirm_fn
        self._dashboard = dashboard
        self.session_state = SessionState.IDLE
        self.market_price: Optional[float] = None
        self.entry_price: Optional[float] = None
        self.filled_qty: int = 0
        self.entry_order = OrderSnapshot()
        self.exit_order = OrderSnapshot()
        self.position = PositionSnapshot()
        self.risk_snapshot = RiskSnapshot()
        self.pnl_snapshot = PnLSnapshot()
        self.warning: Optional[str] = None
        self.last_update: Optional[datetime] = None
        self.next_poll_seconds: float = config.polling_interval_seconds
        self.realized_pnl: Optional[float] = None
        self._shutdown = False
        self._shutdown_announced = False
        self._submitting = False
        self._prev_sigint = None
        self.market: Optional[MarketDataService] = None
        self.orders: Optional[OrderManager] = None
        self.positions: Optional[PositionManager] = None

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = DhanClient()
        return self._client

    @property
    def dashboard(self) -> Any:
        if self._dashboard is None:
            from cli.dashboard import TradingDashboard

            self._dashboard = TradingDashboard()
        return self._dashboard

    def _ensure_services(self) -> None:
        if self.market is None:
            self.market = MarketDataService(self.client)
        if self.orders is None:
            self.orders = OrderManager(self.client)
        if self.positions is None:
            self.positions = PositionManager(self.client)

    def build_dashboard_state(self) -> DashboardState:
        inst = self.config.instrument
        live = self.session_state not in TERMINAL_STATES and not self._shutdown
        position_status = "FLAT"
        if self.session_state == SessionState.POSITION_OPEN:
            position_status = "OPEN"
        elif self.session_state in EXIT_GUARD_STATES and self.session_state != SessionState.POSITION_CLOSED:
            position_status = "EXITING"
        elif self.session_state == SessionState.POSITION_CLOSED:
            position_status = "CLOSED"
        elif self.session_state == SessionState.ORDER_PENDING:
            position_status = "PENDING"
        return DashboardState(
            symbol=inst.symbol,
            security_id=inst.security_id,
            instrument_id=inst.instrument_id,
            mode="DRY-RUN" if self.config.dry_run else "LIVE",
            session_state=self.session_state,
            market_price=self.market_price,
            entry_price=self.entry_price,
            quantity=self.config.quantity,
            position_qty=self.position.net_qty or (self.filled_qty if self.session_state not in {SessionState.IDLE, SessionState.ORDER_PENDING, SessionState.ORDER_REJECTED} else 0),
            pnl=self.pnl_snapshot,
            risk=self.risk_snapshot,
            order_status=self.entry_order.status if self.session_state not in EXIT_GUARD_STATES else (self.exit_order.status or self.entry_order.status),
            position_status=position_status,
            last_update=self.last_update,
            next_poll_seconds=self.next_poll_seconds,
            warning=self.warning,
            realized_pnl=self.realized_pnl,
            live=live,
        )

    def _refresh_market(self) -> None:
        assert self.market is not None
        inst = self.config.instrument
        price = self.market.get_latest_price(inst.security_id, inst.exchange_segment)
        if price is not None:
            self.market_price = price
        if self.market.last_error:
            self.warning = self.market.last_error
        elif self.warning and self.warning == self.market.last_error:
            self.warning = None

    def _simulated_position(self) -> PositionSnapshot:
        qty = self.filled_qty if self.session_state != SessionState.POSITION_CLOSED else 0
        return PositionSnapshot(
            net_qty=qty,
            average_price=self.entry_price,
            last_price=self.market_price,
            realized_pnl=self.realized_pnl,
        )

    def _refresh_position(self) -> None:
        assert self.positions is not None
        self.position = self.positions.get_position(
            self.config.instrument.security_id,
            dry_run=self.config.dry_run,
            simulated=self._simulated_position() if self.config.dry_run else None,
        )
        if not self.config.dry_run and self.position.net_qty:
            self.filled_qty = abs(self.position.net_qty)
            if self.position.average_price and self.entry_price is None:
                self.entry_price = self.position.average_price

    def _apply_entry_fill(self, order: OrderSnapshot) -> bool:
        avg = order.average_traded_price
        filled = order.filled_quantity or 0
        if order.status == "REJECTED":
            self.session_state = SessionState.ORDER_REJECTED
            self.entry_order = order
            self.warning = "Order rejected"
            logger.info("Order rejected")
            return True
        if order.status not in {"FILLED", "PARTIAL"} or filled <= 0 or not avg or avg <= 0:
            return False
        self.entry_order = order
        self.entry_price = avg
        self.filled_qty = filled
        self.session_state = SessionState.ORDER_FILLED
        logger.info("Order filled")
        logger.info("Entry price: ₹%.2f", avg)
        side = self.config.transaction_type
        self.risk_snapshot, self.pnl_snapshot = evaluate_risk(
            avg,
            self.market_price,
            filled,
            side,
            self.config.risk,
        )
        logger.info("TP calculated")
        logger.info("SL calculated")
        self.session_state = SessionState.POSITION_OPEN
        return True

    def submit_entry(self) -> OrderSnapshot:
        self._ensure_services()
        self._refresh_market()
        self._submitting = True
        try:
            order = self.orders.place_entry(
                symbol=self.config.instrument.symbol,
                security_id=self.config.instrument.security_id,
                exchange_segment=self.config.instrument.exchange_segment,
                transaction_type=self.config.transaction_type,
                quantity=self.config.quantity,
                product_type=self.config.product_type,
                dry_run=self.config.dry_run,
                simulated_price=self.market_price,
            )
        finally:
            self._submitting = False
        self.entry_order = order
        if order.status in {"FILLED", "PARTIAL"}:
            self._apply_entry_fill(order)
        else:
            self.session_state = SessionState.ORDER_PENDING
        self.last_update = datetime.now()
        return order

    def _track_entry(self) -> None:
        assert self.orders is not None
        order = self.orders.refresh(self.entry_order.order_id, self.config.dry_run, self.entry_order)
        self.entry_order = order
        self._apply_entry_fill(order)

    def _submit_exit(self) -> None:
        assert self.orders is not None
        if self.orders.exit_submitted:
            return
        self.session_state = SessionState.EXIT_TRIGGERED
        exit_side = "SELL" if self.config.transaction_type.upper() == "BUY" else "BUY"
        qty = abs(self.filled_qty or self.config.quantity)
        self._submitting = True
        try:
            snapshot = self.orders.place_exit(
                symbol=self.config.instrument.symbol,
                security_id=self.config.instrument.security_id,
                exchange_segment=self.config.instrument.exchange_segment,
                exit_side=exit_side,
                quantity=qty,
                product_type=self.config.product_type,
                dry_run=self.config.dry_run,
                simulated_price=self.market_price,
            )
        except Exception as exc:
            self.warning = str(exc)
            logger.warning("API request failed; retrying: %s", exc)
            self.orders.exit_submitted = False
            return
        finally:
            self._submitting = False
        if snapshot is None:
            return
        self.exit_order = snapshot
        if snapshot.status == "FILLED":
            self._complete_exit(snapshot)
        else:
            self.session_state = SessionState.EXIT_ORDER_SUBMITTED

    def _complete_exit(self, order: OrderSnapshot) -> None:
        exit_price = order.average_traded_price or self.market_price
        qty = abs(self.filled_qty or self.config.quantity)
        if self.entry_price is not None and exit_price is not None:
            self.realized_pnl = calculate_pnl(self.entry_price, exit_price, qty, self.config.transaction_type)
        self.exit_order = order
        self.session_state = SessionState.EXIT_FILLED
        self.filled_qty = 0
        self.position = PositionSnapshot(net_qty=0, realized_pnl=self.realized_pnl)
        logger.info("Position closed")
        self.session_state = SessionState.POSITION_CLOSED

    def _track_exit(self) -> None:
        assert self.orders is not None
        order = self.orders.refresh(self.exit_order.order_id, self.config.dry_run, self.exit_order)
        self.exit_order = order
        if order.status in {"FILLED", "PARTIAL"} and order.average_traded_price:
            self._complete_exit(order)
        elif order.status == "REJECTED":
            self.warning = "Exit order rejected"
            self.session_state = SessionState.ERROR

    def _evaluate_exit(self) -> None:
        if self.session_state in EXIT_GUARD_STATES:
            return
        qty = abs(self.filled_qty or self.position.net_qty or self.config.quantity)
        self.risk_snapshot, self.pnl_snapshot = evaluate_risk(
            self.entry_price,
            self.market_price,
            qty,
            self.config.transaction_type,
            self.config.risk,
            broker_unrealized=self.position.unrealized_pnl,
            broker_realized=self.position.realized_pnl,
        )
        if self.risk_snapshot.trigger == "TP":
            logger.info("TP triggered")
            self.session_state = SessionState.TP_TRIGGERED
            self._submit_exit()
        elif self.risk_snapshot.trigger == "SL":
            logger.info("SL triggered")
            self.session_state = SessionState.SL_TRIGGERED
            self._submit_exit()

    def tick(self) -> DashboardState:
        self._ensure_services()
        try:
            self._refresh_market()
            if self.session_state == SessionState.ORDER_PENDING:
                self._track_entry()
            if self.session_state == SessionState.POSITION_OPEN:
                self._refresh_position()
                self._evaluate_exit()
            elif self.session_state in {
                SessionState.EXIT_ORDER_SUBMITTED,
                SessionState.EXIT_TRIGGERED,
            }:
                self._track_exit()
            if self.session_state == SessionState.POSITION_OPEN:
                qty = abs(self.filled_qty or self.position.net_qty or self.config.quantity)
                self.risk_snapshot, self.pnl_snapshot = evaluate_risk(
                    self.entry_price,
                    self.market_price,
                    qty,
                    self.config.transaction_type,
                    self.config.risk,
                    broker_unrealized=self.position.unrealized_pnl,
                    broker_realized=self.position.realized_pnl,
                )
            self.last_update = datetime.now()
        except Exception as exc:
            logger.warning("API request failed; retrying: %s", exc)
            self.warning = str(exc)
        return self.build_dashboard_state()

    def _install_sigint(self) -> None:
        def handler(signum, frame):
            self._shutdown = True
            if not self._submitting:
                raise KeyboardInterrupt

        self._prev_sigint = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGINT, handler)

    def _restore_sigint(self) -> None:
        if self._prev_sigint is not None:
            signal.signal(signal.SIGINT, self._prev_sigint)

    def _confirm(self) -> bool:
        from cli.dashboard import prompt_confirmation

        return prompt_confirmation(
            symbol=self.config.instrument.symbol,
            security_id=self.config.instrument.security_id,
            instrument_id=self.config.instrument.instrument_id,
            side=self.config.transaction_type,
            order_type=self.config.order_type,
            quantity=self.config.quantity,
            market_price=self.market_price,
            dry_run=self.config.dry_run,
            confirm_fn=self.confirm_fn,
        )

    def _print_shutdown(self) -> None:
        if self._shutdown_announced:
            return
        self._shutdown_announced = True
        from cli.styles import SHUTDOWN_MESSAGE, THEME
        from rich.console import Console

        logger.warning("Shutdown requested.")
        Console(theme=THEME).print(SHUTDOWN_MESSAGE, style="term.warn")

    def run(self, interactive: bool = True) -> DashboardState:
        self._ensure_services()
        logger.info("Configuration loaded")
        logger.info("%s selected", self.config.instrument.symbol)
        try:
            resolved = self.client.resolve_symbol(
                self.config.instrument.symbol, self.config.instrument.exchange_segment
            )
            if resolved and str(resolved.get("security_id")) != str(self.config.instrument.security_id):
                logger.warning(
                    "Configured security_id %s differs from security master %s",
                    self.config.instrument.security_id,
                    resolved.get("security_id"),
                )
        except Exception as exc:
            logger.warning("Instrument lookup skipped: %s", exc)

        self._refresh_market()
        if interactive:
            if not self._confirm():
                logger.info("Order cancelled by user")
                return self.build_dashboard_state()

        try:
            self.submit_entry()
        except DhanClientError as exc:
            self.session_state = SessionState.ERROR
            self.warning = str(exc)
            logger.warning("%s", exc)
            return self.build_dashboard_state()

        if not interactive:
            return self.build_dashboard_state()

        from rich.live import Live
        from cli.styles import THEME
        from rich.console import Console

        console = getattr(self.dashboard, "console", None) or Console(theme=THEME)
        interval = float(self.config.polling_interval_seconds)
        self._install_sigint()
        try:
            with Live(self.dashboard.render(self.build_dashboard_state()), console=console, refresh_per_second=4) as live:
                next_poll = time.monotonic()
                while self.session_state not in TERMINAL_STATES and not self._shutdown:
                    now = time.monotonic()
                    if now >= next_poll:
                        self.tick()
                        next_poll = time.monotonic() + interval
                    self.next_poll_seconds = max(0.0, next_poll - time.monotonic())
                    live.update(self.dashboard.render(self.build_dashboard_state()))
                    time.sleep(0.25)
                live.update(self.dashboard.render(self.build_dashboard_state()))
        except KeyboardInterrupt:
            self._shutdown = True
            self._print_shutdown()
        finally:
            self._restore_sigint()
        if self._shutdown and self.session_state not in TERMINAL_STATES:
            self._print_shutdown()
        return self.build_dashboard_state()
