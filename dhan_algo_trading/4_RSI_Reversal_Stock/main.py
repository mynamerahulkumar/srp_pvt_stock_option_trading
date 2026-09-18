#!/usr/bin/env python3
"""Dhan RSI Reversal Algo for NSE equity.

Run (from this directory, after ``pip install -r requirements.txt``):

    python3 main.py

Stop safely from another shell (does not kill the process):

    python3 stop.py

``stop.py`` creates a local ``.stop`` file. This process polls that file and
then shuts down: no new entries, optional close-all, then a clean exit.
SIGINT (Ctrl+C) and SIGTERM do the same.

This file is self-contained. It does not import anything from ``docs/``.
Credentials come from ``.env``. Strategy and risk settings come from
``config.yaml``.
"""

# ============================================================
# IMPORTS
# ============================================================

from __future__ import annotations

import logging
import os
import signal
import sys
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Optional

import yaml
from dotenv import load_dotenv
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python < 3.9
    ZoneInfo = None  # type: ignore

try:
    from dhanhq import DhanContext, dhanhq
except ImportError:
    from dhanhq import dhanhq

    DhanContext = None


# ============================================================
# PROJECT PATHS AND CONSTANTS
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "config.yaml"
STOP_FILE = BASE_DIR / ".stop"
ENV_FILE = BASE_DIR / ".env"

NOTIONAL_WARN_RUPEES = 50000
READ_RETRY_ATTEMPTS = 3
READ_RETRY_SLEEP_SECONDS = 1.0
QUOTE_MIN_INTERVAL_SECONDS = 1.05
CLOSE_VERIFY_ATTEMPTS = 5

VALID_TIMEFRAMES = {"1", "5", "15", "25", "60", "DAY"}
VALID_MODES = {"PAPER", "LIVE"}
VALID_ORDER_TYPES = {"MARKET", "LIMIT"}
VALID_LIMIT_MODES = {"OFFSET_PERCENT", "ABSOLUTE"}
VALID_PRODUCT_TYPES = {"CNC", "INTRADAY", "INTRA", "MARGIN", "MTF"}
EQUITY_PRODUCTS = {"CNC", "INTRADAY", "INTRA", "MARGIN", "MTF"}
DERIVATIVE_PRODUCTS = {"INTRADAY", "INTRA", "MARGIN"}
VALID_TP_SL_TYPES = {"PERCENT", "POINTS"}
VALID_ENGINE_STATES = {
    "STARTING",
    "WAITING_FOR_SESSION",
    "READY",
    "SIGNAL_DETECTED",
    "ENTRY_PENDING",
    "POSITION_OPEN",
    "MONITORING",
    "EXIT_PENDING",
    "POSITION_CLOSED",
    "STOPPING",
    "STOPPED",
    "ERROR",
}

TERMINAL_STATES = {
    "FILLED",
    "CANCELLED",
    "REJECTED",
    "EXPIRED",
    "FAILED",
}

DHAN_STATUS_MAP = {
    "TRANSIT": "PENDING",
    "PENDING": "PENDING",
    "OPEN": "OPEN",
    "PART_TRADED": "PARTIALLY_FILLED",
    "PARTIALLY_FILLED": "PARTIALLY_FILLED",
    "TRADED": "FILLED",
    "FILLED": "FILLED",
    "CANCELLED": "CANCELLED",
    "CANCELED": "CANCELLED",
    "REJECTED": "REJECTED",
    "EXPIRED": "EXPIRED",
    "FAILED": "FAILED",
    "TRIGGER_PENDING": "PENDING",
}

WHY_NO_TRADE_LABELS = {
    "WAITING_FOR_MARKET_DATA": "Waiting for market data",
    "WAITING_FOR_NEW_CLOSED_CANDLE": "Waiting for a new completed candle",
    "RSI_NOT_OVERSOLD": "RSI has not reached oversold",
    "RSI_NOT_OVERBOUGHT": "RSI has not reached overbought",
    "WAITING_FOR_RSI_REVERSAL": "RSI is in an extreme — waiting for reversal",
    "WAITING_FOR_CANDLE_CONFIRMATION": "Reversal seen — waiting for candle confirmation",
    "LONG_DISABLED": "Long entries are disabled in config",
    "SHORT_DISABLED": "Short entries are disabled in config",
    "POSITION_ALREADY_OPEN": "A position is already open",
    "MAX_TRADES_REACHED": "Maximum trades for today have been reached",
    "SESSION_NOT_STARTED": "Session has not started yet",
    "SESSION_ENDED": "Session has ended",
    "RISK_LIMIT_REACHED": "A daily risk limit has been reached",
    "PENDING_ORDER_EXISTS": "An order is already in flight",
    "STOP_REQUESTED": "A stop has been requested",
    "API_UNAVAILABLE": "Dhan API data is currently unavailable",
    "CONFIGURATION_ERROR": "Configuration is invalid",
    "SCANNING": "Flat — scanning for an RSI reversal",
    "MONITORING_TP_SL": "Position open — monitoring take-profit / stop-loss",
    "BLOCKED_UNEXPECTED_POSITION": "Unexpected broker position blocked new entries",
    "ENTRY_EXECUTED": "Entry executed — switching to monitoring",
    "NONE": "No block",
}

# Set by signal handlers. Combined with the ``.stop`` file.
_shutdown_requested = False
_last_good_ltp: Optional[float] = None
_last_quote_monotonic: float = 0.0
# Security+product keys for which an exit was already submitted in close-all.
_close_all_submitted: set[tuple[str, str]] = set()
_event_history: deque[str] = deque(maxlen=8)

CONSOLE = Console(highlight=False)


class ConfigError(Exception):
    """Invalid or incomplete configuration."""


class SafetyError(Exception):
    """Live-trading safety check failed."""


class CredentialError(Exception):
    """Missing or invalid credentials."""


@dataclass
class Candle:
    """One completed or in-progress OHLC bar."""

    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


@dataclass
class BotState:
    """In-memory runtime state. Nothing is persisted to disk or a database."""

    bot_running: bool = True
    engine_state: str = "STARTING"
    entry_price: Optional[float] = None
    current_position: str = "FLAT"
    position_quantity: int = 0
    trade_direction: Optional[str] = None
    take_profit_price: Optional[float] = None
    stop_loss_price: Optional[float] = None
    last_processed_candle: Optional[datetime] = None
    last_signal: str = "NONE"
    confirmation_status: str = "—"
    strategy_condition: str = "INITIALIZING"
    next_action: str = "STARTING"
    why_no_trade: str = "WAITING_FOR_MARKET_DATA"
    shutdown_reason: Optional[str] = None
    pending_order_id: Optional[str] = None
    pending_order_tag: Optional[str] = None
    pending_order_intent: Optional[str] = None
    pending_order_side: Optional[str] = None
    pending_order_quantity: int = 0
    last_order_status: str = "NOT_SUBMITTED"
    order_in_flight: bool = False
    adopted_existing: bool = False
    loop_cycle: int = 0
    current_rsi: Optional[float] = None
    previous_rsi: Optional[float] = None
    last_candle_time: Optional[datetime] = None
    last_ltp: Optional[float] = None
    last_pnl: float = 0.0
    last_pnl_percent: float = 0.0
    last_market_data_at: Optional[datetime] = None
    last_position_sync_at: Optional[datetime] = None
    last_trade_time: Optional[datetime] = None
    last_trade_price: Optional[float] = None
    last_exit_reason: str = "—"
    trades_today: int = 0
    daily_realized_pnl: float = 0.0
    position_opened_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    next_poll_at: Optional[datetime] = None
    api_status: str = "DISCONNECTED"
    close_all_attempted: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


# ============================================================
# ENVIRONMENT
# ============================================================

def load_environment(config: dict) -> None:
    """
    Load Dhan credentials from BASE_DIR/.env or the process environment.

    Purpose:
        Keep secrets out of YAML and source code.

    Why this function exists:
        The Dhan client cannot be created without a client id and access token.
        Loading them here means the rest of the program never hard-codes secrets.

    Inputs:
        config:
            Validated configuration. Uses api.dhan_client_id_env and
            api.dhan_access_token_env as the environment-variable names.

    Returns:
        None. Raises CredentialError if either value is missing.

    Safety:
        Never logs token values.
    """
    if ENV_FILE.exists():
        load_dotenv(ENV_FILE)
    else:
        logging.warning("No .env file found at %s. Checking process environment.", ENV_FILE)

    client_key = str(config["api"]["dhan_client_id_env"])
    token_key = str(config["api"]["dhan_access_token_env"])
    client_id = (os.environ.get(client_key) or "").strip()
    access_token = (os.environ.get(token_key) or "").strip()
    if not client_id or not access_token:
        raise CredentialError(
            "ERROR: Dhan credentials are missing. Set "
            f"{client_key} and {token_key} in .env.\nThe bot did not start."
        )


# ============================================================
# CONFIGURATION
# ============================================================

def load_config() -> dict:
    """
    Load config.yaml from BASE_DIR.

    Purpose:
        Read every user-tunable setting from one YAML file.

    Returns:
        A dict. Raises ConfigError for a missing or invalid file.

    Safety:
        Does not contact Dhan. Does not place orders.
    """
    if not CONFIG_FILE.exists():
        raise ConfigError(
            f"ERROR: config.yaml was not found at {CONFIG_FILE}.\nThe bot did not start."
        )
    try:
        with CONFIG_FILE.open("r", encoding="utf-8") as handle:
            config = yaml.safe_load(handle)
    except yaml.YAMLError as exc:
        raise ConfigError(
            f"ERROR: config.yaml is invalid YAML.\n{exc}\nThe bot did not start."
        ) from exc
    if not isinstance(config, dict):
        raise ConfigError("ERROR: config.yaml must contain a mapping.\nThe bot did not start.")
    return config


def _require_section(config: dict, name: str) -> dict:
    section = config.get(name)
    if not isinstance(section, dict):
        raise ConfigError(
            f"ERROR: config.yaml is missing the '{name}' section.\nThe bot did not start."
        )
    return section


def _as_positive_number(value: Any, field_name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(
            f"ERROR: {field_name} must be a number.\nThe bot did not start."
        ) from exc
    if number <= 0:
        raise ConfigError(
            f"ERROR: {field_name} must be greater than 0.\nThe bot did not start."
        )
    return number


def _as_non_negative_number(value: Any, field_name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(
            f"ERROR: {field_name} must be a number.\nThe bot did not start."
        ) from exc
    if number < 0:
        raise ConfigError(
            f"ERROR: {field_name} must be >= 0.\nThe bot did not start."
        )
    return number


def _parse_hhmm(value: Any, field_name: str) -> tuple[int, int]:
    text = str(value or "").strip()
    try:
        hour_text, minute_text = text.split(":")
        hour = int(hour_text)
        minute = int(minute_text)
    except (TypeError, ValueError) as exc:
        raise ConfigError(
            f"ERROR: {field_name} must be HH:MM.\nThe bot did not start."
        ) from exc
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ConfigError(
            f"ERROR: {field_name} is not a valid clock time.\nThe bot did not start."
        )
    return hour, minute


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def _normalize_level_block(section: dict, key: str) -> dict:
    block = section.get(key)
    if not isinstance(block, dict):
        raise ConfigError(
            f"ERROR: risk_management.{key} must be a mapping.\nThe bot did not start."
        )
    enabled = _as_bool(block.get("enabled"), False)
    level_type = str(block.get("type") or "PERCENT").strip().upper()
    if level_type not in VALID_TP_SL_TYPES:
        raise ConfigError(
            f"ERROR: risk_management.{key}.type must be PERCENT or POINTS.\n"
            "The bot did not start."
        )
    value = _as_non_negative_number(block.get("value", 0), f"risk_management.{key}.value")
    if enabled and value <= 0:
        raise ConfigError(
            f"ERROR: risk_management.{key}.value must be > 0 when enabled.\n"
            "The bot did not start."
        )
    normalized = {"enabled": enabled, "type": level_type, "value": value}
    section[key] = normalized
    return normalized


def validate_config(config: dict) -> None:
    """
    Fail fast if any required setting is missing or inconsistent.

    Purpose:
        Prevent the bot from starting with a configuration that cannot trade
        safely (bad RSI levels, missing security id, inverted session times).

    Why this function exists:
        A live Dhan account will accept orders that a bad config would send.
        Validation happens before authentication work that might already be
        expensive, and always before the first order.

    Inputs:
        config:
            Raw YAML mapping.

    Returns:
        None. Mutates config in place with normalized types.
        Raises ConfigError on the first fatal problem.

    Safety:
        Does not contact Dhan. Does not place orders.
    """
    environment = _require_section(config, "environment")
    _require_section(config, "api")
    strategy = _require_section(config, "strategy")
    trading = _require_section(config, "trading")
    runtime = _require_section(config, "runtime")
    session = _require_section(config, "session")
    risk = _require_section(config, "risk_management")
    shutdown = _require_section(config, "shutdown")
    recovery = _require_section(config, "recovery")
    safety = _require_section(config, "safety")
    cli = _require_section(config, "cli")

    mode = str(environment.get("mode") or "").strip().upper()
    if mode not in VALID_MODES:
        raise ConfigError(
            "ERROR: environment.mode must be PAPER or LIVE.\nThe bot did not start."
        )
    environment["mode"] = mode
    environment["allow_live_trading"] = _as_bool(
        environment.get("allow_live_trading"), False
    )

    if not str(strategy.get("name") or "").strip():
        strategy["name"] = "RSI Reversal"

    timeframe = str(strategy.get("timeframe") or "").strip().upper()
    if timeframe not in VALID_TIMEFRAMES:
        raise ConfigError(
            "ERROR: strategy.timeframe must be one of "
            f"{sorted(VALID_TIMEFRAMES)}.\nThe bot did not start."
        )
    strategy["timeframe"] = timeframe
    strategy["rsi_period"] = int(
        _as_positive_number(strategy.get("rsi_period"), "strategy.rsi_period")
    )
    strategy["oversold"] = _as_non_negative_number(
        strategy.get("oversold"), "strategy.oversold"
    )
    strategy["overbought"] = _as_non_negative_number(
        strategy.get("overbought"), "strategy.overbought"
    )
    if strategy["oversold"] >= strategy["overbought"]:
        raise ConfigError(
            "ERROR: strategy.oversold must be less than strategy.overbought.\n"
            "The bot did not start."
        )
    if strategy["overbought"] > 100:
        raise ConfigError(
            "ERROR: strategy.overbought cannot exceed 100.\nThe bot did not start."
        )
    strategy["use_reversal_confirmation"] = _as_bool(
        strategy.get("use_reversal_confirmation"), True
    )
    strategy["use_candle_confirmation"] = _as_bool(
        strategy.get("use_candle_confirmation"), True
    )

    security_id = str(trading.get("security_id") or "").strip()
    trading_symbol = str(
        trading.get("trading_symbol") or trading.get("symbol") or ""
    ).strip()
    if not security_id:
        raise ConfigError("ERROR: trading.security_id is required.\nThe bot did not start.")
    if not trading_symbol:
        raise ConfigError(
            "ERROR: trading.trading_symbol is required.\nThe bot did not start."
        )
    trading["security_id"] = security_id
    trading["trading_symbol"] = trading_symbol

    exchange_segment = str(trading.get("exchange_segment") or "").strip().upper()
    if not exchange_segment:
        raise ConfigError(
            "ERROR: trading.exchange_segment is required.\nThe bot did not start."
        )
    trading["exchange_segment"] = exchange_segment

    quantity = int(_as_positive_number(trading.get("quantity"), "trading.quantity"))
    if quantity != float(trading.get("quantity")):
        raise ConfigError(
            "ERROR: trading.quantity must be a whole number.\nThe bot did not start."
        )
    trading["quantity"] = quantity

    product_type = str(trading.get("product_type") or "").strip().upper()
    if product_type not in VALID_PRODUCT_TYPES:
        raise ConfigError(
            f"ERROR: trading.product_type must be one of {sorted(VALID_PRODUCT_TYPES)}.\n"
            "The bot did not start."
        )
    if exchange_segment in {"NSE_FNO", "BSE_FNO", "MCX_COMM", "NSE_CURRENCY", "BSE_CURRENCY"}:
        if product_type not in DERIVATIVE_PRODUCTS:
            raise ConfigError(
                "ERROR: F&O / commodity product_type must be INTRADAY or MARGIN.\n"
                "The bot did not start."
            )
    elif product_type not in EQUITY_PRODUCTS:
        raise ConfigError("ERROR: equity product_type is invalid.\nThe bot did not start.")
    trading["product_type"] = product_type
    trading["tick_size"] = _as_positive_number(
        trading.get("tick_size", 0.05), "trading.tick_size"
    )
    trading["instrument_type"] = str(
        trading.get("instrument_type") or "EQUITY"
    ).strip().upper()

    order_type = str(trading.get("order_type") or "MARKET").strip().upper()
    if order_type not in VALID_ORDER_TYPES:
        raise ConfigError(
            "ERROR: trading.order_type must be MARKET or LIMIT.\nThe bot did not start."
        )
    trading["order_type"] = order_type
    trading["validity"] = str(trading.get("validity") or "DAY").strip().upper() or "DAY"

    limit_mode = str(trading.get("limit_price_mode") or "OFFSET_PERCENT").strip().upper()
    if limit_mode not in VALID_LIMIT_MODES:
        raise ConfigError(
            "ERROR: trading.limit_price_mode must be OFFSET_PERCENT or ABSOLUTE.\n"
            "The bot did not start."
        )
    trading["limit_price_mode"] = limit_mode
    trading["limit_offset_percent"] = _as_non_negative_number(
        trading.get("limit_offset_percent", 0), "trading.limit_offset_percent"
    )
    trading["limit_price"] = _as_non_negative_number(
        trading.get("limit_price", 0), "trading.limit_price"
    )
    if limit_mode == "ABSOLUTE" and order_type == "LIMIT" and trading["limit_price"] <= 0:
        raise ConfigError(
            "ERROR: trading.limit_price must be > 0 when limit_price_mode is ABSOLUTE.\n"
            "The bot did not start."
        )

    trading["allow_long"] = _as_bool(trading.get("allow_long"), True)
    trading["allow_short"] = _as_bool(trading.get("allow_short"), True)
    if not trading["allow_long"] and not trading["allow_short"]:
        raise ConfigError(
            "ERROR: at least one of trading.allow_long or allow_short must be true.\n"
            "The bot did not start."
        )
    trading["max_open_positions"] = int(
        _as_positive_number(
            trading.get("max_open_positions", 1), "trading.max_open_positions"
        )
    )
    trading["one_trade_at_a_time"] = _as_bool(trading.get("one_trade_at_a_time"), True)

    runtime["polling_interval_seconds"] = _as_positive_number(
        runtime.get("polling_interval_seconds", 5), "runtime.polling_interval_seconds"
    )
    runtime["log_level"] = str(runtime.get("log_level") or "INFO").strip().upper()
    runtime["candle_lookback"] = int(
        _as_positive_number(runtime.get("candle_lookback", 100), "runtime.candle_lookback")
    )
    runtime["order_wait_seconds"] = _as_positive_number(
        runtime.get("order_wait_seconds", 90), "runtime.order_wait_seconds"
    )
    runtime["reconcile_every_cycles"] = max(
        1,
        int(
            _as_positive_number(
                runtime.get("reconcile_every_cycles", 6),
                "runtime.reconcile_every_cycles",
            )
        ),
    )

    session["enabled"] = _as_bool(session.get("enabled"), False)
    session["timezone"] = str(session.get("timezone") or "Asia/Kolkata").strip()
    start_h, start_m = _parse_hhmm(session.get("start_time", "09:20"), "session.start_time")
    stop_h, stop_m = _parse_hhmm(session.get("stop_time", "15:15"), "session.stop_time")
    if session["enabled"] and (start_h, start_m) >= (stop_h, stop_m):
        raise ConfigError(
            "ERROR: session.start_time must be before stop_time.\nThe bot did not start."
        )
    session["close_all_positions_at_stop_time"] = _as_bool(
        session.get("close_all_positions_at_stop_time"), True
    )

    risk["enabled"] = _as_bool(risk.get("enabled"), True)
    _normalize_level_block(risk, "take_profit")
    _normalize_level_block(risk, "stop_loss")
    risk["max_trades_per_day"] = int(
        _as_non_negative_number(
            risk.get("max_trades_per_day", 1), "risk_management.max_trades_per_day"
        )
    )
    risk["max_daily_loss"] = _as_non_negative_number(
        risk.get("max_daily_loss", 0), "risk_management.max_daily_loss"
    )
    risk["max_daily_profit"] = _as_non_negative_number(
        risk.get("max_daily_profit", 0), "risk_management.max_daily_profit"
    )

    shutdown["close_positions_on_manual_stop"] = _as_bool(
        shutdown.get("close_positions_on_manual_stop"), False
    )
    shutdown["close_positions_on_session_end"] = _as_bool(
        shutdown.get("close_positions_on_session_end"), True
    )
    shutdown["close_positions_on_tp_sl"] = _as_bool(
        shutdown.get("close_positions_on_tp_sl"), True
    )
    shutdown["close_positions_on_error"] = _as_bool(
        shutdown.get("close_positions_on_error"), False
    )
    shutdown["cancel_pending_orders"] = _as_bool(
        shutdown.get("cancel_pending_orders"), True
    )

    recovery["enabled"] = _as_bool(recovery.get("enabled"), True)
    recovery["manage_existing_position"] = _as_bool(
        recovery.get("manage_existing_position"), True
    )
    recovery["prevent_duplicate_entry"] = _as_bool(
        recovery.get("prevent_duplicate_entry"), True
    )

    safety["manage_only_configured_symbol"] = _as_bool(
        safety.get("manage_only_configured_symbol"), True
    )
    safety["require_flat_before_entry"] = _as_bool(
        safety.get("require_flat_before_entry"), True
    )
    safety["block_if_unexpected_position"] = _as_bool(
        safety.get("block_if_unexpected_position"), True
    )

    cli["enabled"] = _as_bool(cli.get("enabled"), True)
    cli["refresh_seconds"] = _as_positive_number(
        cli.get("refresh_seconds", 1), "cli.refresh_seconds"
    )
    cli["event_history_size"] = int(
        _as_positive_number(cli.get("event_history_size", 8), "cli.event_history_size")
    )


def is_paper_mode(config: dict) -> bool:
    """True when live place_order must never be called."""
    return str(config.get("environment", {}).get("mode", "PAPER")).upper() != "LIVE"


def is_live_mode(config: dict) -> bool:
    return not is_paper_mode(config)


def validate_safety_config(config: dict) -> None:
    """
    Live trading requires mode=LIVE AND allow_live_trading=true.

    Purpose:
        A single flag is too easy to flip by accident on a 1 GB VM that can
        place real orders. The second lock must be set deliberately.

    Safety:
        PAPER mode always returns without raising.
    """
    environment = _require_section(config, "environment")
    if is_paper_mode(config):
        return
    if not environment.get("allow_live_trading"):
        raise SafetyError(
            "ERROR: Live trading is not allowed. "
            "Set environment.mode: LIVE and environment.allow_live_trading: true.\n"
            "The bot did not start."
        )


# ============================================================
# LOGGING
# ============================================================

class EventHistoryHandler(logging.Handler):
    """Copy log lines into the in-memory CLI event ring. Never stores secrets."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record)
        except Exception:
            return
        lowered = message.lower()
        if "access_token" in lowered or "client_id" in lowered:
            return
        stamp = datetime.now().strftime("%H:%M:%S")
        _event_history.append(f"{stamp}  {record.levelname:<7}  {record.getMessage()}")


def setup_logging(config: dict) -> None:
    """Configure the standard library logger from config.yaml."""
    global _event_history
    level_name = str(config.get("runtime", {}).get("log_level") or "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    history_size = int(config.get("cli", {}).get("event_history_size") or 8)
    _event_history = deque(maxlen=max(1, history_size))

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    stream = logging.StreamHandler(sys.stderr)
    stream.setLevel(level)
    stream.setFormatter(formatter)
    root.addHandler(stream)
    events = EventHistoryHandler()
    events.setLevel(level)
    events.setFormatter(formatter)
    root.addHandler(events)


def push_event(kind: str, detail: str) -> None:
    """Append a short dashboard event without going through logging."""
    stamp = datetime.now().strftime("%H:%M:%S")
    _event_history.append(f"{stamp}  {kind:<9}  {detail}")


# ============================================================
# STOP SIGNAL
# ============================================================

def consume_leftover_stop_file() -> None:
    """Allow a new run after a previous stop.py.

    .stop is deleted once at startup only. It is never deleted while
    trading, so a stop requested during a wait cannot be lost.
    """
    if STOP_FILE.exists():
        STOP_FILE.unlink()
        logging.info("Cleared leftover .stop from a previous run. Starting fresh.")


def stop_requested() -> bool:
    """True if stop.py ran, Ctrl+C was pressed, or SIGTERM arrived."""
    return STOP_FILE.exists() or _shutdown_requested


def _handle_shutdown_signal(signum, _frame) -> None:
    global _shutdown_requested
    _shutdown_requested = True
    logging.info("Received signal %s. Stop requested.", signum)


def install_signal_handlers() -> None:
    """Catch SIGINT and SIGTERM so the loop can shut down without a kill -9."""
    signal.signal(signal.SIGINT, _handle_shutdown_signal)
    signal.signal(signal.SIGTERM, _handle_shutdown_signal)


# ============================================================
# TIME HELPERS
# ============================================================

def session_timezone(config: dict):
    """Return the configured zone. Falls back to a fixed IST offset."""
    name = str(config.get("session", {}).get("timezone") or "Asia/Kolkata")
    if ZoneInfo is not None:
        try:
            return ZoneInfo(name)
        except Exception:
            logging.warning("Unknown timezone %s. Using IST (UTC+05:30).", name)
    return timezone(timedelta(hours=5, minutes=30))


def now_in_session_tz(config: dict) -> datetime:
    return datetime.now(tz=session_timezone(config))


def epoch_to_local(ts: Any, tzinfo) -> Optional[datetime]:
    """Convert a Dhan epoch (seconds or milliseconds) to the session timezone."""
    try:
        value = float(ts)
    except (TypeError, ValueError):
        return None
    if value > 1e12:
        value /= 1000.0
    return datetime.fromtimestamp(value, tz=timezone.utc).astimezone(tzinfo)


def interval_minutes(timeframe: str) -> Optional[int]:
    if timeframe == "DAY":
        return None
    return int(timeframe)


def _session_clock(config: dict, now: datetime, field_name: str) -> datetime:
    hour, minute = _parse_hhmm(config["session"][field_name], field_name)
    return now.replace(hour=hour, minute=minute, second=0, microsecond=0)


def session_window(config: dict, now: Optional[datetime] = None) -> tuple[datetime, datetime]:
    current = now or now_in_session_tz(config)
    return (
        _session_clock(config, current, "start_time"),
        _session_clock(config, current, "stop_time"),
    )


def is_session_enabled(config: dict) -> bool:
    return bool(config.get("session", {}).get("enabled"))


def is_before_session_start(config: dict, now: Optional[datetime] = None) -> bool:
    if not is_session_enabled(config):
        return False
    current = now or now_in_session_tz(config)
    start, _stop = session_window(config, current)
    return current < start


def is_after_session_stop(config: dict, now: Optional[datetime] = None) -> bool:
    if not is_session_enabled(config):
        return False
    current = now or now_in_session_tz(config)
    _start, stop = session_window(config, current)
    return current >= stop


def interruptible_sleep(seconds: float) -> bool:
    """Sleep in short slices so stop.py is noticed quickly.

    Returns True if a stop was requested during the wait.
    """
    deadline = time.monotonic() + max(0.0, seconds)
    while time.monotonic() < deadline:
        if stop_requested():
            return True
        time.sleep(min(0.25, max(0.0, deadline - time.monotonic())))
    return stop_requested()


def format_runtime(started_at: Optional[datetime], now: datetime) -> str:
    if started_at is None:
        return "00:00:00"
    delta = now - started_at
    total = int(max(0, delta.total_seconds()))
    hours, rem = divmod(total, 3600)
    minutes, seconds = divmod(rem, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def format_inr(value: Optional[float]) -> str:
    if value is None:
        return "—"
    return f"₹{value:,.2f}"


# ============================================================
# DHAN CLIENT
# ============================================================

def create_dhan_client(config: dict):
    """
    Build a Dhan SDK client from environment credentials.

    Purpose:
        One authenticated client is reused for candles, quotes, positions,
        and orders.

    Why this function exists:
        The SDK constructor changed between versions (DhanContext vs
        positional client id / token). This wrapper supports both.

    Safety:
        Does not log the access token. Does not place an order.
    """
    client_key = str(config["api"]["dhan_client_id_env"])
    token_key = str(config["api"]["dhan_access_token_env"])
    client_id = os.environ[client_key].strip()
    access_token = os.environ[token_key].strip()
    try:
        if DhanContext is not None:
            try:
                context = DhanContext(client_id, access_token)
                return dhanhq(context)
            except TypeError:
                pass
        return dhanhq(client_id, access_token)
    except Exception as exc:
        raise CredentialError(
            "ERROR: Dhan authentication failed.\nThe bot did not start."
        ) from exc


def _sdk_value(name: str, fallback: str) -> str:
    return str(getattr(dhanhq, name, fallback))


def _map_exchange_segment(exchange_segment: str) -> str:
    raw = exchange_segment.strip().upper()
    mapping = {
        "NSE_EQ": _sdk_value("NSE", "NSE_EQ"),
        "NSE": _sdk_value("NSE", "NSE_EQ"),
        "BSE_EQ": _sdk_value("BSE", "BSE_EQ"),
        "BSE": _sdk_value("BSE", "BSE_EQ"),
        "NSE_FNO": _sdk_value("NSE_FNO", "NSE_FNO"),
        "BSE_FNO": _sdk_value("BSE_FNO", "BSE_FNO"),
        "MCX_COMM": _sdk_value("MCX", "MCX_COMM"),
        "IDX_I": _sdk_value("INDEX", "IDX_I"),
    }
    return mapping.get(raw, raw)


def _map_transaction_type(transaction_type: str) -> str:
    raw = transaction_type.strip().upper()
    if raw == "BUY":
        return _sdk_value("BUY", "BUY")
    if raw == "SELL":
        return _sdk_value("SELL", "SELL")
    return raw


def _map_order_type(order_type: str) -> str:
    raw = order_type.strip().upper()
    mapping = {
        "LIMIT": _sdk_value("LIMIT", "LIMIT"),
        "MARKET": _sdk_value("MARKET", "MARKET"),
    }
    return mapping.get(raw, raw)


def _map_product_type(product_type: str) -> str:
    raw = product_type.strip().upper()
    mapping = {
        "CNC": _sdk_value("CNC", "CNC"),
        "INTRADAY": _sdk_value("INTRA", "INTRADAY"),
        "INTRA": _sdk_value("INTRA", "INTRADAY"),
        "MARGIN": _sdk_value("MARGIN", "MARGIN"),
        "MTF": _sdk_value("MTF", "MTF"),
    }
    return mapping.get(raw, raw)


def _map_validity(validity: str) -> str:
    raw = validity.strip().upper()
    mapping = {
        "DAY": _sdk_value("DAY", "DAY"),
        "IOC": _sdk_value("IOC", "IOC"),
    }
    return mapping.get(raw, raw)


def _unwrap_dhan_data(response: Any) -> Any:
    """Return the ``data`` payload. Shape varies by Dhan endpoint."""
    if not isinstance(response, dict):
        return None
    return response.get("data")


def _first_dict(payload: Any) -> Optional[dict]:
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, list) and payload:
        first = payload[0]
        return first if isinstance(first, dict) else None
    return None


def _dhan_error_text(response: Any) -> str:
    if not isinstance(response, dict):
        return "Unexpected Dhan response."
    remarks = response.get("remarks")
    if isinstance(remarks, dict):
        return str(
            remarks.get("error_message")
            or remarks.get("message")
            or remarks
        )
    if remarks:
        return str(remarks)
    return "Dhan request failed."


def _dhan_ok(response: Any) -> bool:
    return isinstance(response, dict) and str(response.get("status", "")).lower() == "success"


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def round_to_tick(price: float, tick_size: float) -> float:
    """Round a price to the instrument tick size using half-up rounding."""
    if tick_size <= 0:
        return price
    tick = Decimal(str(tick_size))
    quantized = (Decimal(str(price)) / tick).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * tick
    return float(quantized)


# ============================================================
# MARKET DATA / CANDLES
# ============================================================

def _lookback_calendar_days(timeframe: str, lookback: int) -> int:
    """Extra calendar days so lookback bars still cover weekends and holidays."""
    if timeframe == "DAY":
        return max(lookback + 10, 20)
    minutes = int(timeframe) * lookback
    trading_days = max(3, (minutes // 375) + 4)
    return max(7, trading_days * 2)


def _rows_from_ohlc_payload(data: Any) -> list[dict]:
    """Normalize columnar or row-wise Dhan OHLC payloads into a list of dicts."""
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if not isinstance(data, dict):
        return []
    if "close" not in data:
        nested = data.get("data")
        if nested is not None and nested is not data:
            return _rows_from_ohlc_payload(nested)
        return []
    closes = data.get("close") or []
    count = len(closes) if isinstance(closes, list) else 0
    rows: list[dict] = []
    for index in range(count):
        row = {}
        for key, values in data.items():
            if isinstance(values, list) and index < len(values):
                row[key] = values[index]
        rows.append(row)
    return rows


def _is_candle_complete(candle: Candle, timeframe: str, now: datetime) -> bool:
    """Treat a bar as complete only after its interval has finished.

    Dhan minute timestamps are candle start times. A 5-minute bar that
    starts at 10:00 is complete at 10:05. Today's daily bar is incomplete
    until 15:30 IST.
    """
    if timeframe == "DAY":
        if candle.timestamp.date() < now.date():
            return True
        if candle.timestamp.date() > now.date():
            return False
        return now.hour > 15 or (now.hour == 15 and now.minute >= 30)
    minutes = interval_minutes(timeframe) or 1
    close_time = candle.timestamp + timedelta(minutes=minutes)
    return now >= close_time


def get_market_data(dhan, config: dict) -> list[Candle]:
    """
    Fetch required candle history for RSI.

    Purpose:
        Download a bounded window of OHLC bars, drop the in-progress candle,
        and return completed bars oldest-first.

    Why this function exists:
        RSI must be computed on closed candles. Fetching unbounded history
        would waste RAM on a 1 GB VM.

    Inputs:
        dhan:
            Authenticated Dhan SDK client.
        config:
            Validated configuration.

    Returns:
        Completed candles only. Empty list on failure so the loop can wait
        without placing an order.

    Safety:
        Read-only. Logs and returns [] when the payload is unusable.
    """
    trading = config["trading"]
    strategy = config["strategy"]
    runtime = config["runtime"]
    timeframe = strategy["timeframe"]
    lookback = int(runtime["candle_lookback"])
    tzinfo = session_timezone(config)
    now = now_in_session_tz(config)
    days = _lookback_calendar_days(timeframe, lookback)
    from_date = (now.date() - timedelta(days=days)).strftime("%Y-%m-%d")
    to_date = now.date().strftime("%Y-%m-%d")
    security_id = str(trading["security_id"])
    exchange_segment = _map_exchange_segment(trading["exchange_segment"])
    instrument_type = trading["instrument_type"]

    try:
        if timeframe == "DAY":
            response = dhan.historical_daily_data(
                security_id=security_id,
                exchange_segment=exchange_segment,
                instrument_type=instrument_type,
                from_date=from_date,
                to_date=to_date,
            )
        else:
            response = dhan.intraday_minute_data(
                security_id=security_id,
                exchange_segment=exchange_segment,
                instrument_type=instrument_type,
                from_date=from_date,
                to_date=to_date,
                interval=int(timeframe),
            )
    except Exception as exc:
        logging.error("Candle fetch failed: %s", exc)
        return []

    if not _dhan_ok(response):
        logging.error("Candle fetch was rejected: %s", _dhan_error_text(response))
        return []

    rows = _rows_from_ohlc_payload(_unwrap_dhan_data(response))
    if not rows:
        logging.warning("No candle data was returned.")
        return []

    candles: list[Candle] = []
    for row in rows:
        stamp = epoch_to_local(
            row.get("timestamp") or row.get("start_Time") or row.get("time"),
            tzinfo,
        )
        close = _safe_float(row.get("close") or row.get("Close"), 0.0)
        if stamp is None or close <= 0:
            continue
        candles.append(
            Candle(
                timestamp=stamp,
                open=_safe_float(row.get("open") or row.get("Open"), close),
                high=_safe_float(row.get("high") or row.get("High"), close),
                low=_safe_float(row.get("low") or row.get("Low"), close),
                close=close,
                volume=_safe_float(row.get("volume") or row.get("Volume"), 0.0),
            )
        )
    candles.sort(key=lambda item: item.timestamp)
    completed = [item for item in candles if _is_candle_complete(item, timeframe, now)]
    if lookback > 0:
        completed = completed[-lookback:]
    logging.info(
        "Market data fetched: %s completed %s candles (lookback=%s).",
        len(completed),
        timeframe,
        lookback,
    )
    return completed


# ============================================================
# RSI — WILDER
# ============================================================

def calculate_rsi(closes: list[float], period: int) -> list[Optional[float]]:
    """
    Calculate Wilder's Relative Strength Index.

    Purpose:
        Convert a series of closes into RSI values used by the reversal rules.

    Why this function exists:
        RSI is the only indicator in this strategy. Using Wilder's smoothing
        (not a simple moving average of gains) matches the original 1978
        definition that most charting platforms still use.

    Mathematics:
        1. Change[i] = close[i] - close[i-1]
        2. Gain = max(change, 0), Loss = max(-change, 0)
        3. First average gain/loss = arithmetic mean of the first ``period``
           gains/losses (this needs ``period + 1`` closes).
        4. Later averages use Wilder smoothing:
           avg = (prev_avg * (period - 1) + current) / period
        5. RS = avg_gain / avg_loss
        6. RSI = 100 - (100 / (1 + RS))
           If avg_loss is 0, RSI is 100. If avg_gain is 0, RSI is 0.

    Inputs:
        closes:
            Chronological closing prices.
        period:
            RSI lookback, typically 14.

    Returns:
        A list the same length as closes. Early values are None until the
        first RSI can be computed.

    Safety:
        Never places an order. Returns an all-None list when data is insufficient.
    """
    size = len(closes)
    values: list[Optional[float]] = [None] * size
    if period <= 0 or size < period + 1:
        return values

    gains: list[float] = []
    losses: list[float] = []
    for index in range(1, size):
        change = closes[index] - closes[index - 1]
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    values[period] = _rsi_from_averages(avg_gain, avg_loss)

    for index in range(period, len(gains)):
        avg_gain = ((avg_gain * (period - 1)) + gains[index]) / period
        avg_loss = ((avg_loss * (period - 1)) + losses[index]) / period
        values[index + 1] = _rsi_from_averages(avg_gain, avg_loss)
    return values


def _rsi_from_averages(avg_gain: float, avg_loss: float) -> float:
    if avg_loss == 0 and avg_gain == 0:
        return 50.0
    if avg_loss == 0:
        return 100.0
    if avg_gain == 0:
        return 0.0
    relative_strength = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + relative_strength))


def confirm_reversal(
    previous_rsi: Optional[float],
    current_rsi: Optional[float],
    oversold: float,
    overbought: float,
    side: str,
) -> bool:
    """
    Determine whether RSI has reversed out of an extreme zone.

    Purpose:
        An RSI reading of 28 (oversold) does not mean price will rise. The
        reversal confirmation waits until RSI crosses back above the oversold
        line (or back below overbought for shorts). That cross is the signal
        that selling (or buying) pressure may have exhausted.

    Why this function exists:
        Strategy logic must stay independent from broker execution so the
        same rule can be paper-tested and live-traded.

    Inputs:
        previous_rsi / current_rsi:
            Consecutive completed-bar RSI values.
        oversold / overbought:
            Configured thresholds.
        side:
            "LONG" or "SHORT".

    Returns:
        True when the configured reversal cross is present.

    Safety:
        Never places an order.
    """
    if previous_rsi is None or current_rsi is None:
        return False
    if side == "LONG":
        return previous_rsi <= oversold and current_rsi > oversold
    if side == "SHORT":
        return previous_rsi >= overbought and current_rsi < overbought
    return False


def confirm_candle(candle: Candle, side: str) -> bool:
    """
    Confirm a simple directional candle on the latest completed bar.

    Purpose:
        Filter RSI reversals that print against the candle's own body.

    Why this function exists:
        A green close after an oversold reversal is weak confirmation, not
        a second indicator. Keep the rule obvious: close > open for LONG,
        close < open for SHORT.

    Inputs:
        candle:
            Latest completed OHLC bar.
        side:
            "LONG" or "SHORT".

    Returns:
        True when the candle body agrees with the intended direction.

    Safety:
        Never places an order. Doji (close == open) is not confirmation.
    """
    if side == "LONG":
        return candle.close > candle.open
    if side == "SHORT":
        return candle.close < candle.open
    return False


def generate_signal(
    candles: list[Candle],
    rsi_values: list[Optional[float]],
    config: dict,
    state: BotState,
) -> str:
    """
    Generate an RSI reversal signal.

    Purpose:
        Converts RSI and candle information into a LONG, SHORT, or NONE
        strategy decision.

    Why this function exists:
        Strategy logic should remain independent from broker execution.
        This makes the strategy easier to understand, test, tune, and
        maintain.

    Inputs:
        candles:
            Completed candles, oldest first.
        rsi_values:
            Wilder RSI aligned with candles.
        config:
            Strategy configuration.
        state:
            Mutable bot state (updated with RSI and confirmation text).

    Returns:
        LONG, SHORT, or NONE.

    Safety:
        This function never places an order.
    """
    strategy = config["strategy"]
    oversold = float(strategy["oversold"])
    overbought = float(strategy["overbought"])
    use_reversal = bool(strategy["use_reversal_confirmation"])
    use_candle = bool(strategy["use_candle_confirmation"])

    state.last_signal = "NONE"
    state.confirmation_status = "—"
    if len(candles) < 2 or len(rsi_values) < 2:
        state.strategy_condition = "INSUFFICIENT_DATA"
        return "NONE"

    current_rsi = rsi_values[-1]
    previous_rsi = rsi_values[-2]
    last_candle = candles[-1]
    state.current_rsi = current_rsi
    state.previous_rsi = previous_rsi
    state.last_candle_time = last_candle.timestamp

    if current_rsi is None or previous_rsi is None:
        state.strategy_condition = "RSI_WARMUP"
        state.why_no_trade = "WAITING_FOR_MARKET_DATA"
        return "NONE"

    long_reversal = confirm_reversal(previous_rsi, current_rsi, oversold, overbought, "LONG")
    short_reversal = confirm_reversal(previous_rsi, current_rsi, oversold, overbought, "SHORT")
    long_zone = current_rsi <= oversold
    short_zone = current_rsi >= overbought

    long_ok = long_reversal if use_reversal else long_zone
    short_ok = short_reversal if use_reversal else short_zone

    if long_ok:
        if use_candle and not confirm_candle(last_candle, "LONG"):
            state.strategy_condition = "LONG_REVERSAL_NO_CANDLE"
            state.confirmation_status = "WAITING CANDLE"
            state.why_no_trade = "WAITING_FOR_CANDLE_CONFIRMATION"
            state.next_action = "RSI REVERSAL DETECTED — WAITING FOR CANDLE CONFIRMATION"
            return "NONE"
        state.last_signal = "LONG"
        state.confirmation_status = "CONFIRMED"
        state.strategy_condition = "LONG_SIGNAL"
        return "LONG"

    if short_ok:
        if use_candle and not confirm_candle(last_candle, "SHORT"):
            state.strategy_condition = "SHORT_REVERSAL_NO_CANDLE"
            state.confirmation_status = "WAITING CANDLE"
            state.why_no_trade = "WAITING_FOR_CANDLE_CONFIRMATION"
            state.next_action = "RSI REVERSAL DETECTED — WAITING FOR CANDLE CONFIRMATION"
            return "NONE"
        state.last_signal = "SHORT"
        state.confirmation_status = "CONFIRMED"
        state.strategy_condition = "SHORT_SIGNAL"
        return "SHORT"

    if long_zone and use_reversal:
        state.strategy_condition = "OVERSOLD_WAITING_REVERSAL"
        state.why_no_trade = "WAITING_FOR_RSI_REVERSAL"
        state.next_action = "RSI OVERSOLD — WAITING FOR REVERSAL"
        return "NONE"
    if short_zone and use_reversal:
        state.strategy_condition = "OVERBOUGHT_WAITING_REVERSAL"
        state.why_no_trade = "WAITING_FOR_RSI_REVERSAL"
        state.next_action = "RSI OVERBOUGHT — WAITING FOR REVERSAL"
        return "NONE"

    if current_rsi > oversold and current_rsi < overbought:
        nearer_long = current_rsi - oversold
        nearer_short = overbought - current_rsi
        if nearer_long <= nearer_short:
            state.why_no_trade = "RSI_NOT_OVERSOLD"
            state.next_action = "WAITING FOR RSI TO ENTER OVERSOLD"
        else:
            state.why_no_trade = "RSI_NOT_OVERBOUGHT"
            state.next_action = "WAITING FOR RSI TO ENTER OVERBOUGHT"
        state.strategy_condition = "NEUTRAL"
        return "NONE"

    state.strategy_condition = "NO_SIGNAL"
    state.why_no_trade = "SCANNING"
    return "NONE"


# ============================================================
# POSITIONS AND P&L
# ============================================================

def get_positions(dhan) -> Optional[list[dict]]:
    """Fetch the Dhan position book.

    Returns a list on success (possibly empty). Returns None when the read
    failed so callers do not treat an API error as "flat".
    """
    last_error: Any = None
    for attempt in range(1, READ_RETRY_ATTEMPTS + 1):
        try:
            response = dhan.get_positions()
            if not _dhan_ok(response):
                raise RuntimeError(_dhan_error_text(response))
            data = _unwrap_dhan_data(response)
            if data is None:
                return []
            if isinstance(data, list):
                return [row for row in data if isinstance(row, dict)]
            if isinstance(data, dict):
                return [data]
            return []
        except Exception as exc:
            last_error = exc
            logging.warning(
                "Position read failed (attempt %s/%s): %s",
                attempt,
                READ_RETRY_ATTEMPTS,
                exc,
            )
            if attempt < READ_RETRY_ATTEMPTS:
                time.sleep(READ_RETRY_SLEEP_SECONDS)
    logging.error("Could not retrieve positions: %s", last_error)
    return None


def _position_net_qty(row: dict) -> int:
    return _safe_int(row.get("netQty", row.get("net_qty", 0)), 0)


def _position_security_id(row: dict) -> str:
    return str(row.get("securityId") or row.get("security_id") or "").strip()


def _position_product(row: dict) -> str:
    return str(row.get("productType") or row.get("product_type") or "").strip().upper()


def _position_side(net_qty: int) -> str:
    if net_qty > 0:
        return "LONG"
    if net_qty < 0:
        return "SHORT"
    return "FLAT"


def _position_avg_price(row: dict, side: str) -> float:
    if side == "LONG":
        return _safe_float(row.get("buyAvg") or row.get("buy_avg") or row.get("costPrice"), 0.0)
    if side == "SHORT":
        return _safe_float(row.get("sellAvg") or row.get("sell_avg") or row.get("costPrice"), 0.0)
    return 0.0


def get_open_positions(dhan) -> Optional[list[dict]]:
    """Open positions only (net quantity not zero). None if the book could not be read."""
    positions = get_positions(dhan)
    if positions is None:
        return None
    return [row for row in positions if _position_net_qty(row) != 0]


def get_open_position(dhan, config: dict) -> tuple[bool, Optional[dict]]:
    """Return (read_ok, row) for the configured instrument."""
    target = str(config["trading"]["security_id"])
    open_rows = get_open_positions(dhan)
    if open_rows is None:
        return False, None
    for row in open_rows:
        if _position_security_id(row) == target:
            return True, row
    return True, None


def broker_side_from_row(row: Optional[dict]) -> tuple[str, int, float]:
    """Return (side, abs_qty, avg_price) from a Dhan position row."""
    if row is None:
        return "FLAT", 0, 0.0
    net_qty = _position_net_qty(row)
    side = _position_side(net_qty)
    return side, abs(net_qty), _position_avg_price(row, side)


def apply_broker_position(state: BotState, config: dict, row: Optional[dict]) -> None:
    """Overwrite local position fields from the broker. Does not place orders."""
    side, quantity, avg_price = broker_side_from_row(row)
    was_flat = state.current_position == "FLAT"
    state.current_position = side
    state.position_quantity = quantity
    state.trade_direction = None if side == "FLAT" else side
    if side == "FLAT":
        state.entry_price = None
        state.take_profit_price = None
        state.stop_loss_price = None
        state.position_opened_at = None
        return
    if was_flat or state.position_opened_at is None:
        state.position_opened_at = now_in_session_tz(config)
    if avg_price > 0:
        state.entry_price = avg_price
        arm_risk_levels(state, config, avg_price, side)


def log_existing_positions(dhan, config: dict) -> tuple[Optional[dict], list[dict]]:
    """Log the full position book and return our instrument row plus other opens."""
    positions = get_positions(dhan)
    if positions is None:
        logging.error("Could not read positions at startup. Continuing without a snapshot.")
        return None, []
    if not positions:
        logging.info("No positions returned (flat or empty book).")
        return None, []
    ours = None
    others: list[dict] = []
    target = str(config["trading"]["security_id"])
    for row in positions:
        net_qty = _position_net_qty(row)
        security_id = _position_security_id(row)
        symbol = row.get("tradingSymbol") or row.get("trading_symbol") or ""
        logging.info(
            "Existing position: symbol=%s security_id=%s netQty=%s product=%s",
            symbol,
            security_id,
            net_qty,
            _position_product(row),
        )
        if net_qty == 0:
            continue
        if security_id == target:
            ours = row
        else:
            others.append(row)
    if ours is None:
        logging.info("Configured instrument is flat at the broker.")
    return ours, others


def calculate_pnl(side: str, quantity: int, entry_price: Optional[float], ltp: Optional[float]) -> tuple[float, float]:
    """Direction-aware unrealized P&L and P&L percent."""
    if side == "FLAT" or not quantity or not entry_price or not ltp or entry_price <= 0:
        return 0.0, 0.0
    if side == "LONG":
        pnl = (ltp - entry_price) * quantity
    else:
        pnl = (entry_price - ltp) * quantity
    percent = (pnl / (entry_price * quantity)) * 100.0
    return pnl, percent


def monitor_position(
    dhan,
    config: dict,
    state: BotState,
    ltp: Optional[float],
) -> dict[str, Any]:
    """
    Build a live snapshot of the open (or flat) position.

    Purpose:
        Centralize side, quantity, entry, LTP, P&L, TP, SL, age, and TP/SL
        state so the CLI and the exit logic read the same numbers.

    Why this function exists:
        Displaying P&L from stale local fields while the broker has a
        different fill is misleading. In LIVE mode this function prefers
        the broker book when it can be read.

    Inputs:
        dhan, config, state, ltp

    Returns:
        A dict used by the dashboard and TP/SL check.

    Safety:
        Read-only except for updating in-memory state fields.
    """
    now = now_in_session_tz(config)
    if not is_paper_mode(config) and dhan is not None:
        read_ok, row = get_open_position(dhan, config)
        if read_ok:
            apply_broker_position(state, config, row)
            state.last_position_sync_at = now
        else:
            logging.warning("Position monitor could not refresh the broker book.")

    if ltp is not None and ltp > 0:
        state.last_ltp = ltp
    pnl, percent = calculate_pnl(
        state.current_position,
        state.position_quantity,
        state.entry_price,
        state.last_ltp,
    )
    state.last_pnl = pnl
    state.last_pnl_percent = percent
    age = "—"
    if state.position_opened_at is not None and state.current_position != "FLAT":
        age = format_runtime(state.position_opened_at, now)

    tp_state = "OFF"
    sl_state = "OFF"
    if state.current_position != "FLAT":
        if state.take_profit_price is not None:
            tp_state = (
                "HIT"
                if should_trigger_tp(state.last_ltp, state.take_profit_price, state.current_position)
                else "ARMED"
            )
        if state.stop_loss_price is not None:
            sl_state = (
                "HIT"
                if should_trigger_sl(state.last_ltp, state.stop_loss_price, state.current_position)
                else "ARMED"
            )

    return {
        "side": state.current_position,
        "quantity": state.position_quantity,
        "entry_price": state.entry_price,
        "current_price": state.last_ltp,
        "pnl": pnl,
        "pnl_percent": percent,
        "take_profit": state.take_profit_price,
        "stop_loss": state.stop_loss_price,
        "age": age,
        "tp_state": tp_state,
        "sl_state": sl_state,
    }


# ============================================================
# LAST TRADED PRICE
# ============================================================

def _extract_ltp(ticker_response: Any, security_id: str) -> Optional[float]:
    payload = ticker_response
    if isinstance(payload, dict) and "data" in payload:
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
                return _safe_float(
                    values.get("last_price")
                    or values.get("ltp")
                    or values.get("lastPrice")
                    or (values.get("ohlc") or {}).get("close"),
                    0.0,
                ) or None
            price = _safe_float(values, 0.0)
            return price or None
    return None


def get_ltp(dhan, security_id: str, exchange_segment: str) -> Optional[float]:
    """Read last traded price. Quote APIs are limited to 1 request/sec.

    Falls back to the last good LTP on a transient failure so TP/SL is not
    disarmed by a single bad tick.
    """
    global _last_good_ltp, _last_quote_monotonic
    elapsed = time.monotonic() - _last_quote_monotonic
    if elapsed < QUOTE_MIN_INTERVAL_SECONDS:
        time.sleep(QUOTE_MIN_INTERVAL_SECONDS - elapsed)

    segment = _map_exchange_segment(exchange_segment)
    try:
        security_key: Any = int(security_id)
    except (TypeError, ValueError):
        security_key = security_id
    last_error = None
    method = getattr(dhan, "ticker_data", None)
    if method is None:
        logging.warning("ticker_data is not available on this Dhan SDK.")
        return _last_good_ltp
    try:
        _last_quote_monotonic = time.monotonic()
        response = method({segment: [security_key]})
        if isinstance(response, dict) and str(response.get("status", "")).lower() == "failure":
            last_error = _dhan_error_text(response)
        else:
            price = _extract_ltp(response, str(security_id))
            if price is not None and price > 0:
                _last_good_ltp = price
                return price
    except Exception as exc:
        last_error = exc
    if last_error:
        logging.warning("LTP read failed; using last good price if available: %s", last_error)
    return _last_good_ltp


# ============================================================
# TAKE PROFIT / STOP LOSS MATH
# ============================================================

def _distance_from_level(entry_price: float, level: dict) -> float:
    if level["type"] == "POINTS":
        return float(level["value"])
    return entry_price * (float(level["value"]) / 100.0)


def arm_risk_levels(state: BotState, config: dict, entry_price: float, side: str) -> None:
    """
    Compute and store TP/SL prices for the open position.

    LONG:  TP = entry + distance, SL = entry - distance
    SHORT: TP = entry - distance, SL = entry + distance

    Distance comes from PERCENT or POINTS. Results are rounded to tick size.
    Software-polled TP/SL is not a guaranteed fill at the exact price.
    """
    risk = config["risk_management"]
    tick = float(config["trading"]["tick_size"])
    state.entry_price = entry_price
    state.take_profit_price = None
    state.stop_loss_price = None
    direction = side.upper()

    tp = risk.get("take_profit") or {}
    sl = risk.get("stop_loss") or {}
    if risk.get("enabled") and tp.get("enabled"):
        distance = _distance_from_level(entry_price, tp)
        raw = entry_price + distance if direction == "LONG" else entry_price - distance
        state.take_profit_price = round_to_tick(raw, tick)
    if risk.get("enabled") and sl.get("enabled"):
        distance = _distance_from_level(entry_price, sl)
        raw = entry_price - distance if direction == "LONG" else entry_price + distance
        state.stop_loss_price = round_to_tick(raw, tick)

    logging.info(
        "TP ARMED / SL ARMED | entry=%.2f side=%s TP=%s SL=%s",
        entry_price,
        direction,
        f"{state.take_profit_price:.2f}" if state.take_profit_price else "off",
        f"{state.stop_loss_price:.2f}" if state.stop_loss_price else "off",
    )


def should_trigger_tp(current_price: Optional[float], take_profit_price: Optional[float], side: str) -> bool:
    if current_price is None or take_profit_price is None:
        return False
    if side.upper() == "LONG":
        return current_price >= take_profit_price
    return current_price <= take_profit_price


def should_trigger_sl(current_price: Optional[float], stop_loss_price: Optional[float], side: str) -> bool:
    if current_price is None or stop_loss_price is None:
        return False
    if side.upper() == "LONG":
        return current_price <= stop_loss_price
    return current_price >= stop_loss_price


# ============================================================
# LIMIT PRICE
# ============================================================

def resolve_limit_price(
    config: dict,
    transaction_type: str,
    ltp: Optional[float],
) -> Optional[float]:
    """Compute a LIMIT price. Never converts LIMIT into MARKET."""
    trading = config["trading"]
    tick = float(trading["tick_size"])
    mode = trading["limit_price_mode"]
    side = transaction_type.upper()
    if mode == "ABSOLUTE":
        price = float(trading["limit_price"])
        if price <= 0:
            return None
        return round_to_tick(price, tick)
    if ltp is None or ltp <= 0:
        return None
    offset = float(trading["limit_offset_percent"]) / 100.0
    raw = ltp * (1.0 + offset) if side == "BUY" else ltp * (1.0 - offset)
    price = round_to_tick(raw, tick)
    if price <= 0:
        return None
    return price


# ============================================================
# ORDER STATUS
# ============================================================

def normalize_status(raw_status: Any) -> str:
    text = str(raw_status or "").strip().upper()
    if not text:
        return "UNKNOWN"
    return DHAN_STATUS_MAP.get(text, text)


def _status_from_payload(payload: dict, requested_quantity: int) -> dict:
    raw_status = payload.get("orderStatus") or payload.get("status") or ""
    filled_quantity = _safe_int(payload.get("filledQty", payload.get("filled_qty", 0)), 0)
    quantity = _safe_int(payload.get("quantity", requested_quantity), requested_quantity)
    remaining_quantity = max(quantity - filled_quantity, 0)
    current_price = _safe_float(payload.get("price"), 0.0)
    fill_price = _safe_float(
        payload.get("averageTradedPrice", payload.get("average_traded_price", 0.0)),
        0.0,
    )
    return {
        "order_id": str(payload.get("orderId") or payload.get("order_id") or ""),
        "raw_status": str(raw_status),
        "status": normalize_status(raw_status),
        "filled_quantity": filled_quantity,
        "remaining_quantity": remaining_quantity,
        "requested_quantity": quantity,
        "current_price": current_price,
        "fill_price": fill_price,
        "payload": payload,
    }


def get_order_status(dhan, order_id: str, requested_quantity: int) -> dict:
    """Fetch current broker status. Read-only retries are allowed."""
    last_error = None
    for attempt in range(1, READ_RETRY_ATTEMPTS + 1):
        try:
            try:
                response = dhan.get_order_by_id(order_id=order_id)
            except TypeError:
                response = dhan.get_order_by_id(order_id)
            if not _dhan_ok(response):
                raise RuntimeError(_dhan_error_text(response))
            payload = _first_dict(_unwrap_dhan_data(response))
            if not payload:
                raise RuntimeError("Order status payload was empty.")
            return _status_from_payload(payload, requested_quantity)
        except Exception as exc:
            last_error = exc
        logging.warning(
            "Order status read failed (attempt %s/%s): %s",
            attempt,
            READ_RETRY_ATTEMPTS,
            last_error,
        )
        if attempt < READ_RETRY_ATTEMPTS:
            time.sleep(READ_RETRY_SLEEP_SECONDS)
    raise RuntimeError(f"Could not retrieve order status: {last_error}")


def find_order_id_after_uncertain_place(dhan, tag: str, security_id: str) -> Optional[str]:
    """Recover an order ID after a timeout without placing again."""
    try:
        method = getattr(dhan, "get_order_by_correlationID", None)
        if method is not None:
            response = method(tag)
            if _dhan_ok(response):
                payload = _first_dict(_unwrap_dhan_data(response))
                if payload and payload.get("orderId"):
                    return str(payload["orderId"])
                data = response.get("data")
                if isinstance(data, list):
                    for item in data:
                        if not isinstance(item, dict):
                            continue
                        item_tag = str(item.get("correlationId") or item.get("tag") or "")
                        if item_tag == tag and item.get("orderId"):
                            return str(item["orderId"])
    except Exception:
        logging.warning("Could not look up the order by correlation ID.")

    try:
        response = dhan.get_order_list()
        if not _dhan_ok(response):
            return None
        data = response.get("data")
        orders = data if isinstance(data, list) else []
        if isinstance(data, dict):
            orders = [data]
        for item in orders:
            if not isinstance(item, dict):
                continue
            item_tag = str(item.get("correlationId") or item.get("tag") or "")
            item_security = str(item.get("securityId") or item.get("security_id") or "")
            if item_tag == tag and (not item_security or item_security == str(security_id)):
                if item.get("orderId"):
                    return str(item["orderId"])
    except Exception:
        logging.warning("Could not look up the order from the order book.")
    return None


def get_order_list(dhan) -> Optional[list[dict]]:
    last_error = None
    for attempt in range(1, READ_RETRY_ATTEMPTS + 1):
        try:
            response = dhan.get_order_list()
            if not _dhan_ok(response):
                raise RuntimeError(_dhan_error_text(response))
            data = _unwrap_dhan_data(response)
            if data is None:
                return []
            if isinstance(data, list):
                return [row for row in data if isinstance(row, dict)]
            if isinstance(data, dict):
                return [data]
            return []
        except Exception as exc:
            last_error = exc
            if attempt < READ_RETRY_ATTEMPTS:
                time.sleep(READ_RETRY_SLEEP_SECONDS)
    logging.warning("Order list read failed: %s", last_error)
    return None


def pending_orders_for_symbol(dhan, config: dict) -> list[dict]:
    orders = get_order_list(dhan)
    if orders is None:
        return []
    target = str(config["trading"]["security_id"])
    pending: list[dict] = []
    for row in orders:
        security_id = str(row.get("securityId") or row.get("security_id") or "")
        if security_id != target:
            continue
        status = normalize_status(row.get("orderStatus") or row.get("status"))
        if status in {"PENDING", "OPEN", "PARTIALLY_FILLED", "UNKNOWN"}:
            pending.append(row)
    return pending


def count_todays_broker_entries(dhan, config: dict) -> Optional[int]:
    """Count filled orders on this security for the session calendar date.

    Used so max_trades_per_day survives a process restart. An entry and its
    later exit both appear as fills; we count unique order IDs that traded
    today and treat any fill on a previously flat book as consuming a slot
    when combined with recovery of an open position. Conservative: if any
    filled order exists today for this security, report at least 1.
    """
    orders = get_order_list(dhan)
    if orders is None:
        return None
    target = str(config["trading"]["security_id"])
    today = now_in_session_tz(config).date()
    tzinfo = session_timezone(config)
    filled_ids: set[str] = set()
    for row in orders:
        security_id = str(row.get("securityId") or row.get("security_id") or "")
        if security_id != target:
            continue
        status = normalize_status(row.get("orderStatus") or row.get("status"))
        filled_qty = _safe_int(row.get("filledQty") or row.get("filled_qty"), 0)
        if status not in {"FILLED", "PARTIALLY_FILLED"} and filled_qty <= 0:
            continue
        stamp = (
            row.get("createTime")
            or row.get("exchangeTime")
            or row.get("updateTime")
            or row.get("orderTime")
        )
        when = None
        if stamp is not None:
            when = epoch_to_local(stamp, tzinfo)
            if when is None:
                try:
                    text = str(stamp)
                    when = datetime.fromisoformat(text.replace("Z", "+00:00"))
                    if when.tzinfo is None:
                        when = when.replace(tzinfo=tzinfo)
                    else:
                        when = when.astimezone(tzinfo)
                except ValueError:
                    when = None
        if when is not None and when.date() != today:
            continue
        order_id = str(row.get("orderId") or row.get("order_id") or "")
        if order_id:
            filled_ids.add(order_id)
        else:
            filled_ids.add(str(len(filled_ids)))
    if not filled_ids:
        return 0
    return max(1, (len(filled_ids) + 1) // 2)


# ============================================================
# ORDER EXECUTION
# ============================================================

def _warn_notional(quantity: int, price: float) -> None:
    if price <= 0:
        return
    notional = quantity * price
    if notional > NOTIONAL_WARN_RUPEES:
        logging.warning(
            "Order notional is Rs. %.2f, which exceeds Rs. %s.",
            notional,
            NOTIONAL_WARN_RUPEES,
        )


def _clear_pending(state: BotState) -> None:
    state.pending_order_id = None
    state.pending_order_tag = None
    state.pending_order_intent = None
    state.pending_order_side = None
    state.pending_order_quantity = 0
    state.order_in_flight = False


def _mark_flat(state: BotState) -> None:
    state.current_position = "FLAT"
    state.position_quantity = 0
    state.trade_direction = None
    state.entry_price = None
    state.take_profit_price = None
    state.stop_loss_price = None
    state.position_opened_at = None
    state.last_pnl = 0.0
    state.last_pnl_percent = 0.0


def _apply_fill(
    state: BotState,
    config: dict,
    intent: str,
    side: str,
    quantity: int,
    fill_price: float,
) -> None:
    """Update local position after a confirmed fill. Does not place orders."""
    now = now_in_session_tz(config)
    state.last_trade_time = now
    state.last_trade_price = fill_price if fill_price > 0 else state.last_ltp
    if intent in {"EXIT", "CLOSE_ALL"}:
        pnl, _percent = calculate_pnl(
            state.current_position,
            state.position_quantity or quantity,
            state.entry_price,
            fill_price or state.last_ltp,
        )
        state.daily_realized_pnl += pnl
        _mark_flat(state)
        logging.info("POSITION CLOSED. Local state is FLAT. Realized P&L this exit ≈ %.2f", pnl)
        return
    position_side = "LONG" if side.upper() == "BUY" else "SHORT"
    state.current_position = position_side
    state.position_quantity = quantity
    state.trade_direction = position_side
    state.position_opened_at = now
    state.trades_today += 1
    price = fill_price if fill_price > 0 else state.entry_price or state.last_ltp or 0.0
    if price > 0:
        arm_risk_levels(state, config, price, position_side)
    logging.info("POSITION OPEN %s qty=%s entry=%.2f", position_side, quantity, price)


def build_order_request(
    config: dict,
    transaction_type: str,
    quantity: int,
    order_type: str,
    price: float,
    tag: str,
    product_type: Optional[str] = None,
    security_id: Optional[str] = None,
    exchange_segment: Optional[str] = None,
) -> dict:
    """Convert config + intent into Dhan place_order keyword arguments."""
    trading = config["trading"]
    return {
        "security_id": str(security_id or trading["security_id"]).strip(),
        "exchange_segment": _map_exchange_segment(
            exchange_segment or trading["exchange_segment"]
        ),
        "transaction_type": _map_transaction_type(transaction_type),
        "quantity": int(quantity),
        "order_type": _map_order_type(order_type),
        "product_type": _map_product_type(product_type or trading["product_type"]),
        "price": float(price),
        "trigger_price": 0,
        "disclosed_quantity": 0,
        "after_market_order": False,
        "validity": _map_validity(trading.get("validity", "DAY")),
        "tag": tag,
    }


def describe_would_be_order(
    transaction_type: str,
    quantity: int,
    order_type: str,
    price: float,
    intent: str,
) -> str:
    price_text = "MARKET" if order_type == "MARKET" else f"{price:.2f}"
    return (
        f"PAPER would place {intent} {order_type} {transaction_type} qty={quantity} "
        f"price={price_text} (no live order sent)"
    )


def submit_order(
    dhan,
    config: dict,
    state: BotState,
    transaction_type: str,
    quantity: int,
    order_type: str,
    intent: str,
    product_type: Optional[str] = None,
    security_id: Optional[str] = None,
    exchange_segment: Optional[str] = None,
    ltp: Optional[float] = None,
) -> Optional[str]:
    """
    Place exactly one order. Never retries place_order on timeout.

    Purpose:
        Single choke point for Dhan place_order and paper fills.

    Why this function exists:
        Duplicate-order bugs happen when every caller talks to the API
        directly. One function owns in-flight flags, LIMIT price math,
        notional warnings, and uncertain-response recovery.

    Returns:
        Order ID string, ``PAPER`` in paper mode, or None on failure.

    Safety:
        * Refuses if a previous order is still in flight.
        * LIMIT is never rewritten to MARKET.
        * After an uncertain API error, recovers by correlation tag.
        * Does not place a second order just because confirmation failed.
        * PAPER mode never calls place_order.
    """
    if quantity <= 0:
        logging.info("Quantity is 0. No order was placed.")
        return None
    if state.order_in_flight or state.pending_order_id:
        logging.error(
            "An order is already in flight (id=%s). Refusing to submit another.",
            state.pending_order_id,
        )
        state.why_no_trade = "PENDING_ORDER_EXISTS"
        return None
    if stop_requested() and intent not in {"EXIT", "CLOSE_ALL"}:
        logging.info("Stop requested. Not placing a new entry.")
        return None

    order_type = str(order_type).upper()
    transaction_type = str(transaction_type).upper()
    price = 0.0
    if order_type == "LIMIT":
        price_value = resolve_limit_price(config, transaction_type, ltp)
        if price_value is None:
            logging.error(
                "LIMIT price could not be computed (need LTP or a positive "
                "absolute limit_price). Not converting to MARKET. No order sent."
            )
            return None
        price = price_value
    elif order_type != "MARKET":
        logging.error("Unsupported order type %s. No order sent.", order_type)
        return None

    reference = ltp or price
    _warn_notional(quantity, reference)

    if is_paper_mode(config):
        logging.info(
            "%s",
            describe_would_be_order(transaction_type, quantity, order_type, price, intent),
        )
        fill_price = ltp or price or state.entry_price or 0.0
        state.last_order_status = "FILLED"
        _apply_fill(state, config, intent, transaction_type, quantity, fill_price)
        push_event("ORDER", f"PAPER {intent} {transaction_type} {quantity} @ {fill_price:.2f}")
        return "PAPER"

    tag = f"R{uuid.uuid4().hex[:12]}"
    request = build_order_request(
        config,
        transaction_type=transaction_type,
        quantity=quantity,
        order_type=order_type,
        price=price,
        tag=tag,
        product_type=product_type,
        security_id=security_id,
        exchange_segment=exchange_segment,
    )
    logging.info(
        "ENTRY ORDER SUBMITTED" if intent == "ENTRY" else "EXIT ORDER SUBMITTED"
    )
    logging.info(
        "Submitting %s %s: symbol=%s security_id=%s side=%s qty=%s price=%s tag=%s intent=%s",
        order_type,
        intent,
        config["trading"]["trading_symbol"],
        request["security_id"],
        request["transaction_type"],
        request["quantity"],
        price if order_type == "LIMIT" else "MARKET",
        tag,
        intent,
    )

    state.engine_state = "ENTRY_PENDING" if intent == "ENTRY" else "EXIT_PENDING"
    state.order_in_flight = True
    state.pending_order_tag = tag
    state.pending_order_intent = intent
    state.pending_order_side = transaction_type
    state.pending_order_quantity = quantity
    state.last_order_status = "SUBMITTED"

    response = None
    try:
        response = dhan.place_order(**request)
    except Exception as exc:
        logging.error("Order placement returned an uncertain result: %s", exc)
        recovered = find_order_id_after_uncertain_place(dhan, tag, request["security_id"])
        if recovered:
            logging.info("Recovered order ID from broker state: %s", recovered)
            state.pending_order_id = recovered
            state.last_order_status = "PENDING"
            return recovered
        logging.error(
            "Could not confirm whether Dhan accepted the order. "
            "Not submitting another order."
        )
        state.last_order_status = "UNKNOWN"
        return None

    if not isinstance(response, dict):
        logging.error("Unexpected place-order response. Checking broker state.")
        recovered = find_order_id_after_uncertain_place(dhan, tag, request["security_id"])
        if recovered:
            state.pending_order_id = recovered
            return recovered
        state.last_order_status = "UNKNOWN"
        return None

    if not _dhan_ok(response):
        logging.error("Dhan rejected the order: %s", _dhan_error_text(response))
        state.last_order_status = "REJECTED"
        _clear_pending(state)
        return None

    payload = _first_dict(_unwrap_dhan_data(response))
    order_id = None
    if payload:
        order_id = payload.get("orderId") or payload.get("order_id")
    if not order_id and isinstance(response.get("data"), dict):
        order_id = response["data"].get("orderId")
    if not order_id:
        logging.error("Order was accepted but no order ID was returned. Checking broker state.")
        recovered = find_order_id_after_uncertain_place(dhan, tag, request["security_id"])
        if recovered:
            state.pending_order_id = recovered
            return recovered
        state.last_order_status = "UNKNOWN"
        return None

    order_id = str(order_id)
    state.pending_order_id = order_id
    state.last_order_status = "PENDING"
    logging.info("Order submitted. Order ID: %s", order_id)
    push_event("ORDER", f"{intent} {transaction_type} qty={quantity} id={order_id}")
    raw_status = ""
    if payload:
        raw_status = str(payload.get("orderStatus") or payload.get("status") or "")
        logging.info("Order status from place response: %s", raw_status or "unknown")
        if raw_status:
            state.last_order_status = normalize_status(raw_status)
    return order_id


def wait_for_order_completion(
    dhan,
    config: dict,
    state: BotState,
    order_id: str,
    requested_quantity: int,
) -> Optional[dict]:
    """Poll one order until a terminal state, timeout, or stop signal.

    Partial fills at timeout are kept as-is; the remainder is not re-sent.
    """
    if order_id == "PAPER":
        return {
            "status": "FILLED",
            "filled_quantity": requested_quantity,
            "fill_price": state.entry_price or state.last_ltp or 0.0,
            "raw_status": "PAPER",
        }

    poll_interval = float(config["runtime"]["polling_interval_seconds"])
    max_wait = float(config["runtime"]["order_wait_seconds"])
    started_at = time.time()
    last_status: Optional[dict] = None
    logging.info("Waiting for order %s to complete.", order_id)

    while True:
        if stop_requested() and state.pending_order_intent not in {"EXIT", "CLOSE_ALL"}:
            logging.info("Stop requested while waiting for order %s.", order_id)
            break
        try:
            last_status = get_order_status(dhan, order_id, requested_quantity)
        except Exception as exc:
            logging.error("Order status poll failed: %s", exc)
            if interruptible_sleep(poll_interval):
                break
            continue

        state.last_order_status = last_status["status"]
        logging.info(
            "Order %s | raw=%s | status=%s | filled=%s | remaining=%s",
            order_id,
            last_status["raw_status"],
            last_status["status"],
            last_status["filled_quantity"],
            last_status["remaining_quantity"],
        )
        if last_status["status"] in TERMINAL_STATES:
            return last_status
        if time.time() - started_at >= max_wait:
            logging.warning(
                "Order wait timeout after %s seconds. Broker order %s may still be %s. "
                "Not placing a replacement.",
                int(max_wait),
                order_id,
                last_status["raw_status"] or last_status["status"],
            )
            return last_status
        if interruptible_sleep(poll_interval):
            break
    return last_status


def confirm_position_after_fill(dhan, config: dict, state: BotState, intent: str, side: str) -> None:
    """Trust the broker position book over the order-fill payload when they differ."""
    if is_paper_mode(config):
        return
    read_ok, row = get_open_position(dhan, config)
    if not read_ok:
        logging.warning("Skipping fill confirmation because the position book could not be read.")
        return
    broker_side, qty, avg = broker_side_from_row(row)
    if intent in {"EXIT", "CLOSE_ALL"}:
        if broker_side == "FLAT":
            _mark_flat(state)
            logging.info("Broker confirmed the position is closed.")
            return
        logging.warning(
            "Exit reported, but broker still shows %s qty=%s. Local state follows broker.",
            broker_side,
            qty,
        )
        apply_broker_position(state, config, row)
        return
    expected = "LONG" if side.upper() == "BUY" else "SHORT"
    if broker_side == expected:
        apply_broker_position(state, config, row)
        logging.info("Broker confirmed %s qty=%s avg=%.2f", broker_side, qty, avg)
        return
    logging.warning(
        "Fill expected %s but broker shows %s qty=%s. Local state follows broker. "
        "No corrective order will be placed.",
        expected,
        broker_side,
        qty,
    )
    apply_broker_position(state, config, row)


def finalize_submitted_order(
    dhan,
    config: dict,
    state: BotState,
    order_id: Optional[str],
    transaction_type: str,
    quantity: int,
    intent: str,
) -> bool:
    """Wait, interpret fill vs reject, update state. True if the intent succeeded."""
    if not order_id:
        return False
    if order_id == "PAPER":
        return True

    status = wait_for_order_completion(dhan, config, state, order_id, quantity)
    if status is None:
        logging.error("Could not confirm order %s. Treating as uncertain. No retry.", order_id)
        state.last_order_status = "UNKNOWN"
        return False

    normalized = status["status"]
    filled = int(status.get("filled_quantity") or 0)
    fill_price = _safe_float(status.get("fill_price"), 0.0)
    state.last_order_status = normalized

    if normalized == "REJECTED":
        logging.error("Order rejected: %s", status.get("raw_status"))
        _clear_pending(state)
        return False
    if normalized in {"CANCELLED", "EXPIRED", "FAILED"} and filled <= 0:
        logging.warning("Order ended as %s with no fill.", normalized)
        _clear_pending(state)
        return False

    if filled > 0:
        _apply_fill(state, config, intent, transaction_type, filled, fill_price)
        confirm_position_after_fill(dhan, config, state, intent, transaction_type)
        if normalized == "FILLED" or intent in {"EXIT", "CLOSE_ALL"}:
            _clear_pending(state)
        elif filled < quantity:
            logging.warning(
                "Partial fill %s/%s. Remaining quantity will not be re-sent automatically.",
                filled,
                quantity,
            )
        if intent == "ENTRY":
            logging.info("ENTRY ORDER FILLED")
        return True

    if normalized == "FILLED":
        confirm_position_after_fill(dhan, config, state, intent, transaction_type)
        _clear_pending(state)
        return True

    logging.warning("Order %s is still %s. Keeping it in-flight; no new orders.", order_id, normalized)
    return False


def sync_pending_order(dhan, config: dict, state: BotState) -> bool:
    """If a previous order is still working, poll it and skip new signals.

    Returns True when the caller must not place a new order this cycle.
    """
    if is_paper_mode(config):
        return False
    if state.order_in_flight and not state.pending_order_id and state.pending_order_tag:
        recovered = find_order_id_after_uncertain_place(
            dhan,
            state.pending_order_tag,
            str(config["trading"]["security_id"]),
        )
        if recovered:
            logging.info("Recovered in-flight order ID %s from tag %s.", recovered, state.pending_order_tag)
            state.pending_order_id = recovered
        else:
            logging.error(
                "An order may already exist (tag=%s) but the ID is unknown. "
                "Not placing another order.",
                state.pending_order_tag,
            )
            state.why_no_trade = "PENDING_ORDER_EXISTS"
            return True
    if not state.pending_order_id:
        return False
    try:
        status = get_order_status(
            dhan, state.pending_order_id, state.pending_order_quantity or 1
        )
    except Exception as exc:
        logging.error("Pending-order sync failed: %s", exc)
        state.why_no_trade = "PENDING_ORDER_EXISTS"
        return True

    logging.info(
        "Pending order %s | raw=%s | status=%s | filled=%s",
        state.pending_order_id,
        status["raw_status"],
        status["status"],
        status["filled_quantity"],
    )
    state.last_order_status = status["status"]
    if status["status"] in TERMINAL_STATES:
        finalize_submitted_order(
            dhan,
            config,
            state,
            state.pending_order_id,
            state.pending_order_side or "BUY",
            state.pending_order_quantity,
            state.pending_order_intent or "ENTRY",
        )
        return bool(state.pending_order_id)
    state.why_no_trade = "PENDING_ORDER_EXISTS"
    return True


def place_entry_order(
    dhan,
    config: dict,
    state: BotState,
    transaction_type: str,
    ltp: Optional[float],
) -> bool:
    """Enter a new position for the configured quantity."""
    order_id = submit_order(
        dhan,
        config,
        state,
        transaction_type=transaction_type,
        quantity=int(config["trading"]["quantity"]),
        order_type=config["trading"]["order_type"],
        intent="ENTRY",
        ltp=ltp,
    )
    return finalize_submitted_order(
        dhan,
        config,
        state,
        order_id,
        transaction_type,
        int(config["trading"]["quantity"]),
        "ENTRY",
    )


def place_exit_order(
    dhan,
    config: dict,
    state: BotState,
    ltp: Optional[float],
    quantity: Optional[int] = None,
) -> bool:
    """Exit the current local position with the configured order type."""
    if state.current_position == "FLAT" and quantity is None:
        logging.info("No open position to exit.")
        return True
    qty = int(quantity if quantity is not None else state.position_quantity)
    if qty <= 0:
        logging.info("Exit quantity is 0.")
        return True
    side = "SELL" if state.current_position == "LONG" else "BUY"
    order_id = submit_order(
        dhan,
        config,
        state,
        transaction_type=side,
        quantity=qty,
        order_type=config["trading"]["order_type"],
        intent="EXIT",
        ltp=ltp,
    )
    return finalize_submitted_order(dhan, config, state, order_id, side, qty, "EXIT")


def cancel_pending_orders(dhan, config: dict, state: BotState) -> None:
    """Cancel working orders for the configured symbol when shutdown asks for it."""
    if not config["shutdown"].get("cancel_pending_orders"):
        return
    if is_paper_mode(config) or dhan is None:
        _clear_pending(state)
        return
    pending = pending_orders_for_symbol(dhan, config)
    for row in pending:
        order_id = str(row.get("orderId") or row.get("order_id") or "")
        if not order_id:
            continue
        try:
            logging.info("Cancelling pending order %s", order_id)
            try:
                dhan.cancel_order(order_id=order_id)
            except TypeError:
                dhan.cancel_order(order_id)
        except Exception as exc:
            logging.warning("Cancel of %s failed: %s", order_id, exc)
    _clear_pending(state)


def close_all_positions(dhan, config: dict, state: BotState) -> bool:
    """
    Flatten positions this bot is allowed to manage.

    Purpose:
        Exit at session end, TP/SL halt, or configured manual stop.

    Why this function exists:
        Closing "everything" can flatten an unrelated holding. With
        safety.manage_only_configured_symbol the bot only exits the
        configured security id.

    Safety:
        Does not blindly close unrelated positions. Does not retry
        place_order on an uncertain submit; it retries the position read.
    """
    global _close_all_submitted
    logging.info("close_all_positions() starting.")
    state.close_all_attempted = True
    only_ours = bool(config["safety"].get("manage_only_configured_symbol", True))
    target = str(config["trading"]["security_id"])

    if is_paper_mode(config):
        if state.current_position != "FLAT":
            logging.info(
                "PAPER would close local %s qty=%s (no live order sent)",
                state.current_position,
                state.position_quantity,
            )
            _apply_fill(
                state,
                config,
                "CLOSE_ALL",
                "SELL" if state.current_position == "LONG" else "BUY",
                state.position_quantity,
                state.last_ltp or state.entry_price or 0.0,
            )
        logging.info("close_all_positions() paper complete.")
        return True

    ltp = get_ltp(
        dhan,
        str(config["trading"]["security_id"]),
        str(config["trading"]["exchange_segment"]),
    )

    for _attempt in range(1, CLOSE_VERIFY_ATTEMPTS + 1):
        open_rows = get_open_positions(dhan)
        if open_rows is None:
            logging.error("Could not read positions while flattening. Will retry the read.")
            if interruptible_sleep(float(config["runtime"]["polling_interval_seconds"])):
                break
            continue
        managed = [
            row
            for row in open_rows
            if (not only_ours) or _position_security_id(row) == target
        ]
        if not managed:
            logging.info("No managed positions are open.")
            if only_ours:
                _mark_flat(state)
            return True

        for row in managed:
            net_qty = _position_net_qty(row)
            if net_qty == 0:
                continue
            security_id = _position_security_id(row)
            product = _position_product(row) or config["trading"]["product_type"]
            key = (security_id, product)
            if key in _close_all_submitted:
                logging.info(
                    "Exit already submitted for security_id=%s product=%s. Not duplicating.",
                    security_id,
                    product,
                )
                continue
            side = "SELL" if net_qty > 0 else "BUY"
            quantity = abs(net_qty)
            exchange = str(row.get("exchangeSegment") or row.get("exchange_segment") or "")
            logging.info(
                "Closing position security_id=%s qty=%s with %s %s",
                security_id,
                quantity,
                config["trading"]["order_type"],
                side,
            )
            state.order_in_flight = False
            state.pending_order_id = None
            order_id = submit_order(
                dhan,
                config,
                state,
                transaction_type=side,
                quantity=quantity,
                order_type=config["trading"]["order_type"],
                intent="CLOSE_ALL",
                product_type=product,
                security_id=security_id,
                exchange_segment=exchange or None,
                ltp=ltp,
            )
            if order_id or state.order_in_flight:
                _close_all_submitted.add(key)
            finalize_submitted_order(dhan, config, state, order_id, side, quantity, "CLOSE_ALL")

        remaining = get_open_positions(dhan)
        if remaining is None:
            logging.error("Could not verify flatten. Will retry the read, not a new place.")
        else:
            leftover_managed = [
                row
                for row in remaining
                if (not only_ours) or _position_security_id(row) == target
            ]
            if not leftover_managed:
                logging.info("Managed positions closed.")
                _mark_flat(state)
                return True
            logging.warning(
                "Positions still open after close attempt: %s. Rechecking.",
                [(_position_security_id(row), _position_net_qty(row)) for row in leftover_managed],
            )
        if interruptible_sleep(float(config["runtime"]["polling_interval_seconds"])):
            break

    leftover = get_open_positions(dhan)
    if leftover:
        managed = [
            row
            for row in leftover
            if (not only_ours) or _position_security_id(row) == target
        ]
        if managed:
            logging.error(
                "close_all_positions() finished with leftover managed positions: %s",
                [(_position_security_id(row), _position_net_qty(row)) for row in managed],
            )
            read_ok, ours = get_open_position(dhan, config)
            if read_ok:
                apply_broker_position(state, config, ours)
            return False
    if leftover is None:
        logging.error("close_all_positions() finished but the position book could not be verified.")
        return False
    _mark_flat(state)
    return True


# ============================================================
# RECONCILIATION AND RECOVERY
# ============================================================

def reconcile_state(dhan, config: dict, state: BotState) -> None:
    """Compare local position with Dhan. Trust the broker. Never 'fix' with a new trade."""
    if is_paper_mode(config):
        return
    read_ok, row = get_open_position(dhan, config)
    if not read_ok:
        logging.warning("Skipping reconciliation because the position book could not be read.")
        return
    state.last_position_sync_at = now_in_session_tz(config)
    broker_side, qty, avg = broker_side_from_row(row)
    if state.extra.get("unmanaged_existing"):
        if broker_side == "FLAT":
            logging.info("Unmanaged broker position is now flat. Strategy may resume.")
            state.extra["unmanaged_existing"] = False
        else:
            logging.info(
                "Unmanaged broker position still open (%s qty=%s). Not adopting it.",
                broker_side,
                qty,
            )
        return
    local = state.current_position
    if broker_side == local:
        if broker_side != "FLAT" and qty != state.position_quantity:
            logging.warning(
                "Quantity mismatch: local=%s broker=%s. Following broker.",
                state.position_quantity,
                qty,
            )
            apply_broker_position(state, config, row)
        return
    logging.warning(
        "State mismatch: bot thinks %s, Dhan says %s qty=%s avg=%.2f. "
        "Following broker. No corrective order will be placed.",
        local,
        broker_side,
        qty,
        avg,
    )
    apply_broker_position(state, config, row)


def recover_existing_state(dhan, config: dict, state: BotState) -> None:
    """
    At startup, recover a broker position and today's trade count.

    Purpose:
        A process restart must not place a second entry into an already
        open RSI trade.

    Safety:
        Never places a new entry because the process restarted.
    """
    logging.info("RECOVERY MODE")
    if is_paper_mode(config):
        logging.info("Paper mode: broker positions are displayed but not adopted for simulated trading.")
        if dhan is not None:
            log_existing_positions(dhan, config)
        return

    ours, others = log_existing_positions(dhan, config)
    if others and config["safety"].get("block_if_unexpected_position"):
        logging.warning(
            "Unexpected open position(s) on other symbols. New entries will be blocked."
        )
        state.extra["unexpected_other_position"] = True
        state.why_no_trade = "BLOCKED_UNEXPECTED_POSITION"

    counted = count_todays_broker_entries(dhan, config)
    if counted is not None:
        state.trades_today = max(state.trades_today, counted)
        logging.info("Reconciled trades today from broker orders: %s", state.trades_today)

    if ours is None:
        return
    if not config["recovery"].get("enabled") or not config["recovery"].get("manage_existing_position"):
        logging.warning(
            "Existing position will not be managed. The bot will not add to it or close it."
        )
        state.extra["unmanaged_existing"] = True
        return
    side, qty, avg = broker_side_from_row(ours)
    logging.info("Adopting existing %s qty=%s avg=%.2f for TP/SL monitoring.", side, qty, avg)
    apply_broker_position(state, config, ours)
    state.adopted_existing = True
    if state.trades_today < 1:
        state.trades_today = 1
    state.engine_state = "MONITORING"


# ============================================================
# RISK / TRADE VALIDATION
# ============================================================

def daily_risk_blocked(config: dict, state: BotState) -> Optional[str]:
    risk = config["risk_management"]
    if not risk.get("enabled"):
        return None
    max_loss = float(risk.get("max_daily_loss") or 0)
    max_profit = float(risk.get("max_daily_profit") or 0)
    if max_loss > 0 and state.daily_realized_pnl <= -max_loss:
        return "RISK_LIMIT_REACHED"
    if max_profit > 0 and state.daily_realized_pnl >= max_profit:
        return "RISK_LIMIT_REACHED"
    max_trades = int(risk.get("max_trades_per_day") or 0)
    if max_trades > 0 and state.trades_today >= max_trades:
        return "MAX_TRADES_REACHED"
    return None


def validate_trade(config: dict, state: BotState, signal: str) -> tuple[bool, str]:
    """
    Verify that an RSI signal is allowed to become an order.

    Purpose:
        Separate "the strategy likes this bar" from "the account is allowed
        to trade right now".

    Why this function exists:
        Session, direction flags, open position, pending orders, daily
        limits, and stop requests must all be able to veto a signal without
        the signal function knowing about Dhan.

    Inputs:
        config, state, signal (LONG / SHORT / NONE)

    Returns:
        (allowed, reason_code). The reason is displayed in the CLI.

    Safety:
        Never places an order.
    """
    if stop_requested():
        return False, "STOP_REQUESTED"
    if signal not in {"LONG", "SHORT"}:
        return False, state.why_no_trade or "SCANNING"
    if is_before_session_start(config):
        return False, "SESSION_NOT_STARTED"
    if is_after_session_stop(config):
        return False, "SESSION_ENDED"
    if state.order_in_flight or state.pending_order_id:
        return False, "PENDING_ORDER_EXISTS"
    if state.extra.get("unmanaged_existing") or state.extra.get("unexpected_other_position"):
        return False, "BLOCKED_UNEXPECTED_POSITION"
    if state.current_position != "FLAT":
        return False, "POSITION_ALREADY_OPEN"
    if config["safety"].get("require_flat_before_entry") and state.current_position != "FLAT":
        return False, "POSITION_ALREADY_OPEN"
    if config["trading"].get("one_trade_at_a_time") and state.current_position != "FLAT":
        return False, "POSITION_ALREADY_OPEN"
    if signal == "LONG" and not config["trading"].get("allow_long"):
        return False, "LONG_DISABLED"
    if signal == "SHORT" and not config["trading"].get("allow_short"):
        return False, "SHORT_DISABLED"
    blocked = daily_risk_blocked(config, state)
    if blocked:
        return False, blocked
    quantity = int(config["trading"]["quantity"])
    if quantity <= 0:
        return False, "CONFIGURATION_ERROR"
    return True, "NONE"


def compute_next_action(config: dict, state: BotState) -> None:
    """
    Set the human-readable NEXT ACTION and WHY-NO-TRADE fields.

    Purpose:
        The operator should understand why the algorithm is not trading by
        looking at the dashboard, without reading logs.
    """
    if stop_requested() or state.engine_state in {"STOPPING", "STOPPED"}:
        state.next_action = "STOPPING"
        state.why_no_trade = "STOP_REQUESTED"
        return
    if state.engine_state == "ERROR":
        state.next_action = "ERROR — SEE EVENT STREAM"
        state.why_no_trade = "API_UNAVAILABLE"
        return
    if is_before_session_start(config):
        state.engine_state = "WAITING_FOR_SESSION"
        state.next_action = "SESSION NOT STARTED"
        state.why_no_trade = "SESSION_NOT_STARTED"
        return
    if is_after_session_stop(config):
        state.next_action = "SESSION ENDED"
        state.why_no_trade = "SESSION_ENDED"
        return
    if state.order_in_flight or state.pending_order_id:
        state.next_action = "ORDER IN FLIGHT — WAITING FOR FILL"
        state.why_no_trade = "PENDING_ORDER_EXISTS"
        return
    if state.current_position != "FLAT":
        state.engine_state = "MONITORING"
        state.next_action = "POSITION OPEN — MONITORING TP/SL"
        state.why_no_trade = "MONITORING_TP_SL"
        return
    blocked = daily_risk_blocked(config, state)
    if blocked == "MAX_TRADES_REACHED":
        state.next_action = "MAX TRADES REACHED"
        state.why_no_trade = blocked
        return
    if blocked:
        state.next_action = "RISK BLOCKED"
        state.why_no_trade = blocked
        return
    if state.extra.get("unmanaged_existing") or state.extra.get("unexpected_other_position"):
        state.next_action = "BLOCKED — UNEXPECTED POSITION"
        state.why_no_trade = "BLOCKED_UNEXPECTED_POSITION"
        return
    blocking = {
        "LONG_DISABLED",
        "SHORT_DISABLED",
        "POSITION_ALREADY_OPEN",
        "CONFIGURATION_ERROR",
        "BLOCKED_UNEXPECTED_POSITION",
        "PENDING_ORDER_EXISTS",
        "MAX_TRADES_REACHED",
        "RISK_LIMIT_REACHED",
        "STOP_REQUESTED",
        "SESSION_NOT_STARTED",
        "SESSION_ENDED",
    }
    if state.why_no_trade in blocking:
        state.next_action = WHY_NO_TRADE_LABELS.get(
            state.why_no_trade, state.why_no_trade
        ).upper()
        return
    if state.last_signal == "LONG" and state.why_no_trade in {"NONE", "SCANNING", "ENTRY_EXECUTED"}:
        state.next_action = "LONG SIGNAL — RISK CHECK PENDING"
        return
    if state.last_signal == "SHORT" and state.why_no_trade in {"NONE", "SCANNING", "ENTRY_EXECUTED"}:
        state.next_action = "SHORT SIGNAL — RISK CHECK PENDING"
        return
    if state.why_no_trade in {
        "WAITING_FOR_RSI_REVERSAL",
        "WAITING_FOR_CANDLE_CONFIRMATION",
        "RSI_NOT_OVERSOLD",
        "RSI_NOT_OVERBOUGHT",
        "WAITING_FOR_NEW_CLOSED_CANDLE",
        "WAITING_FOR_MARKET_DATA",
    }:
        return
    state.engine_state = "READY"
    state.next_action = "POSITION FLAT — SCANNING"
    state.why_no_trade = "SCANNING"


# ============================================================
# TP/SL MONITORING
# ============================================================

def monitor_tpsl(dhan, config: dict, state: BotState, ltp: Optional[float]) -> Optional[str]:
    """
    Check live LTP against armed TP/SL.

    Returns:
        "TAKE_PROFIT" or "STOP_LOSS" when a level is reached, else None.

    SL is evaluated first so a gap through both levels prefers capital
    protection. Software polling can overshoot the exact price because of
    interval, API latency, slippage, and gaps.
    """
    if state.current_position == "FLAT":
        return None
    risk = config["risk_management"]
    if not risk.get("enabled"):
        return None
    tp = risk.get("take_profit") or {}
    sl = risk.get("stop_loss") or {}
    if not tp.get("enabled") and not sl.get("enabled"):
        return None
    if ltp is None:
        logging.warning("No LTP available for TP/SL. Waiting.")
        return None

    side = state.current_position
    logging.info(
        "POSITION MONITORING | LTP=%.2f | entry=%s | TP=%s | SL=%s | side=%s | pnl=%.2f",
        ltp,
        f"{state.entry_price:.2f}" if state.entry_price else "n/a",
        f"{state.take_profit_price:.2f}" if state.take_profit_price else "off",
        f"{state.stop_loss_price:.2f}" if state.stop_loss_price else "off",
        side,
        state.last_pnl,
    )

    reason = None
    if sl.get("enabled") and should_trigger_sl(ltp, state.stop_loss_price, side):
        reason = "STOP_LOSS"
    elif tp.get("enabled") and should_trigger_tp(ltp, state.take_profit_price, side):
        reason = "TAKE_PROFIT"
    return reason


# ============================================================
# SCI-FI CLI
# ============================================================

def _kv(table: Table, label: str, value: str, style: str = "cyan") -> None:
    table.add_row(Text(label, style="bold dim"), Text(str(value), style=style))


def render_startup_banner(config: dict) -> None:
    """Print a one-time futuristic configuration summary."""
    trading = config["trading"]
    strategy = config["strategy"]
    session = config["session"]
    risk = config["risk_management"]
    mode = config["environment"]["mode"]
    tp = risk["take_profit"]
    sl = risk["stop_loss"]
    tp_text = f"{tp['value']}{'%' if tp['type'] == 'PERCENT' else ' pts'}" if tp["enabled"] else "off"
    sl_text = f"{sl['value']}{'%' if sl['type'] == 'PERCENT' else ' pts'}" if sl["enabled"] else "off"
    session_text = (
        f"{session.get('start_time')} → {session.get('stop_time')}"
        if session.get("enabled")
        else "DISABLED"
    )
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="bold cyan", min_width=14)
    grid.add_column(style="white")
    grid.add_row("MODE", mode)
    grid.add_row("SYMBOL", str(trading.get("trading_symbol")))
    grid.add_row("SECURITY ID", str(trading.get("security_id")))
    grid.add_row("TIMEFRAME", f"{strategy.get('timeframe')} MIN")
    grid.add_row("RSI", str(strategy.get("rsi_period")))
    grid.add_row("OVERSOLD", str(strategy.get("oversold")))
    grid.add_row("OVERBOUGHT", str(strategy.get("overbought")))
    grid.add_row("TP", tp_text)
    grid.add_row("SL", sl_text)
    grid.add_row("POLLING", f"{config['runtime']['polling_interval_seconds']} SEC")
    grid.add_row("SESSION", session_text)
    grid.add_row("TIMEZONE", str(session.get("timezone")))
    CONSOLE.print(
        Panel(
            grid,
            title="[bold cyan]RSI REVERSAL // ALGO CORE INITIALIZING[/bold cyan]",
            border_style="cyan",
            padding=(1, 2),
        )
    )
    if is_live_mode(config):
        CONSOLE.print(
            Panel(
                "[bold red]⚠ LIVE TRADING ENABLED ⚠\nREAL ORDERS MAY BE PLACED\n"
                "REAL MONEY MAY BE AT RISK[/bold red]",
                border_style="red",
            )
        )
        logging.info("LIVE TRADING ENABLED. REAL ORDERS MAY BE PLACED.")
    else:
        logging.info("PAPER MODE. Real market data will be fetched. No live orders will be sent.")


def render_dashboard(config: dict, state: BotState) -> Panel:
    """Build the sci-fi command-center panel from in-memory state."""
    now = now_in_session_tz(config)
    trading = config["trading"]
    strategy = config["strategy"]
    runtime = config["runtime"]
    mode = config["environment"]["mode"]
    status = "ONLINE" if state.bot_running else "STOPPING"
    engine = state.engine_state
    api = state.api_status
    rsi_text = f"{state.current_rsi:.2f}" if state.current_rsi is not None else "—"
    prev_text = f"{state.previous_rsi:.2f}" if state.previous_rsi is not None else "—"
    candle_text = (
        state.last_candle_time.strftime("%H:%M:%S") if state.last_candle_time else "—"
    )
    pnl_style = "green" if state.last_pnl > 0 else "red" if state.last_pnl < 0 else "white"
    pnl_text = format_inr(state.last_pnl)
    if state.last_pnl > 0:
        pnl_text = "+" + pnl_text
    pnl_pct = f"{state.last_pnl_percent:+.2f}%" if state.current_position != "FLAT" else "0.00%"
    age = "—"
    if state.position_opened_at and state.current_position != "FLAT":
        age = format_runtime(state.position_opened_at, now)
    why = WHY_NO_TRADE_LABELS.get(state.why_no_trade, state.why_no_trade)
    poll_in = "—"
    if state.next_poll_at:
        remaining = (state.next_poll_at - now).total_seconds()
        poll_in = f"{max(0, int(remaining))} SEC"

    system = Table.grid(padding=(0, 2))
    system.add_column(min_width=16, style="bold dim")
    system.add_column(min_width=22)
    system.add_column(min_width=16, style="bold dim")
    system.add_column(min_width=22)
    system.add_row("STATUS", f"● {status}", "MODE", mode)
    system.add_row("ENGINE", engine, "API", api)
    system.add_row("RUNTIME", format_runtime(state.started_at, now), "STOP FILE", "YES" if STOP_FILE.exists() else "NO")

    market = Table.grid(padding=(0, 2))
    market.add_column(min_width=16, style="bold dim")
    market.add_column(min_width=22)
    market.add_column(min_width=16, style="bold dim")
    market.add_column(min_width=22)
    market.add_row("SYMBOL", str(trading["trading_symbol"]), "SECURITY ID", str(trading["security_id"]))
    market.add_row("TIMEFRAME", f"{strategy['timeframe']} MIN", "LTP", format_inr(state.last_ltp))
    market.add_row("RSI", rsi_text, "PREV RSI", prev_text)
    market.add_row("OVERSOLD", str(strategy["oversold"]), "OVERBOUGHT", str(strategy["overbought"]))
    market.add_row("CANDLE", candle_text, "DATA AT", state.last_market_data_at.strftime("%H:%M:%S") if state.last_market_data_at else "—")

    strat = Table.grid(padding=(0, 2))
    strat.add_column(min_width=16, style="bold dim")
    strat.add_column(min_width=54)
    strat.add_row("SIGNAL", state.last_signal)
    strat.add_row("CONFIRMATION", state.confirmation_status)
    strat.add_row("CONDITION", state.strategy_condition)
    strat.add_row("NEXT ACTION", Text(state.next_action, style="bold yellow"))
    strat.add_row("WHY NO TRADE", why)

    position = Table.grid(padding=(0, 2))
    position.add_column(min_width=16, style="bold dim")
    position.add_column(min_width=22)
    position.add_column(min_width=16, style="bold dim")
    position.add_column(min_width=22)
    position.add_row("SIDE", state.current_position, "QUANTITY", str(state.position_quantity))
    position.add_row("ENTRY", format_inr(state.entry_price), "LTP", format_inr(state.last_ltp))
    position.add_row("TP", format_inr(state.take_profit_price), "SL", format_inr(state.stop_loss_price))
    position.add_row("P&L", Text(pnl_text, style=pnl_style), "P&L %", Text(pnl_pct, style=pnl_style))
    position.add_row("AGE", age, "SYNC", state.last_position_sync_at.strftime("%H:%M:%S") if state.last_position_sync_at else "—")

    trading_tbl = Table.grid(padding=(0, 2))
    trading_tbl.add_column(min_width=16, style="bold dim")
    trading_tbl.add_column(min_width=22)
    trading_tbl.add_column(min_width=16, style="bold dim")
    trading_tbl.add_column(min_width=22)
    last_trade = state.last_trade_time.strftime("%H:%M:%S") if state.last_trade_time else "—"
    trading_tbl.add_row("LAST TRADE", last_trade, "LAST PRICE", format_inr(state.last_trade_price))
    trading_tbl.add_row("ORDER STATUS", state.last_order_status, "EXIT REASON", state.last_exit_reason)
    trading_tbl.add_row(
        "TRADES TODAY",
        str(state.trades_today),
        "MAX TRADES",
        str(config["risk_management"]["max_trades_per_day"]),
    )

    runtime_tbl = Table.grid(padding=(0, 2))
    runtime_tbl.add_column(min_width=16, style="bold dim")
    runtime_tbl.add_column(min_width=22)
    runtime_tbl.add_column(min_width=16, style="bold dim")
    runtime_tbl.add_column(min_width=22)
    runtime_tbl.add_row("POLL EVERY", f"{runtime['polling_interval_seconds']} SEC", "NEXT POLL", poll_in)
    runtime_tbl.add_row("CLI REFRESH", f"{config['cli']['refresh_seconds']} SEC", "STOP", "YES" if stop_requested() else "NO")

    events = Table.grid()
    events.add_column(overflow="fold")
    if _event_history:
        for line in list(_event_history)[-int(config["cli"]["event_history_size"]):]:
            events.add_row(Text(line, style="dim"))
    else:
        events.add_row(Text("waiting for events…", style="dim"))

    body = Group(
        Text("SYSTEM", style="bold magenta"),
        system,
        Text(""),
        Text("MARKET", style="bold magenta"),
        market,
        Text(""),
        Text("STRATEGY", style="bold magenta"),
        strat,
        Text(""),
        Text("POSITION", style="bold magenta"),
        position,
        Text(""),
        Text("TRADING", style="bold magenta"),
        trading_tbl,
        Text(""),
        Text("RUNTIME", style="bold magenta"),
        runtime_tbl,
        Text(""),
        Text("EVENT STREAM", style="bold magenta"),
        events,
    )
    return Panel(
        body,
        title="[bold cyan]⚡ RSI REVERSAL // TRADING CORE ⚡[/bold cyan]",
        subtitle=f"[dim]{now.strftime('%Y-%m-%d %H:%M:%S %Z')}[/dim]",
        border_style="cyan",
        padding=(0, 1),
    )


def dashboard_enabled(config: dict) -> bool:
    return bool(config.get("cli", {}).get("enabled", True)) and sys.stdout.isatty()


# ============================================================
# TRADING LOOP
# ============================================================

def process_new_candle(
    dhan,
    config: dict,
    state: BotState,
    candles: list[Candle],
    ltp: Optional[float],
    allow_entries: bool,
) -> None:
    """Evaluate one newly completed candle. Never double-fires the same bar."""
    if not candles:
        state.why_no_trade = "WAITING_FOR_MARKET_DATA"
        return
    latest = candles[-1]
    if state.last_processed_candle is not None and latest.timestamp <= state.last_processed_candle:
        state.why_no_trade = "WAITING_FOR_NEW_CLOSED_CANDLE"
        state.next_action = "WAITING FOR NEW CANDLE"
        rsi_values = calculate_rsi(
            [item.close for item in candles], int(config["strategy"]["rsi_period"])
        )
        if rsi_values:
            state.current_rsi = rsi_values[-1]
            state.previous_rsi = rsi_values[-2] if len(rsi_values) > 1 else None
        state.last_candle_time = latest.timestamp
        return

    rsi_values = calculate_rsi(
        [item.close for item in candles], int(config["strategy"]["rsi_period"])
    )
    logging.info("RSI CALCULATED")
    if rsi_values[-1] is not None:
        push_event("RSI", f"{rsi_values[-1]:.2f}")
        logging.info(
            "RSI current=%s previous=%s",
            f"{rsi_values[-1]:.2f}",
            f"{rsi_values[-2]:.2f}" if rsi_values[-2] is not None else "n/a",
        )

    signal = generate_signal(candles, rsi_values, config, state)
    state.last_processed_candle = latest.timestamp
    state.last_candle_time = latest.timestamp

    if not allow_entries:
        compute_next_action(config, state)
        return
    if state.current_position != "FLAT":
        compute_next_action(config, state)
        return

    if signal in {"LONG", "SHORT"}:
        state.engine_state = "SIGNAL_DETECTED"
        logging.info("SIGNAL DETECTED: RSI REVERSAL %s", signal)
        push_event("SIGNAL", f"RSI REVERSAL {signal}")
        allowed, reason = validate_trade(config, state, signal)
        if not allowed:
            logging.info("Trade blocked: %s", WHY_NO_TRADE_LABELS.get(reason, reason))
            state.why_no_trade = reason
            compute_next_action(config, state)
            return
        logging.info("RISK CHECK PASSED")
        if is_live_mode(config):
            logging.info(
                "LIVE pre-trade chain: config → session → position → pending → "
                "risk → signal → safety → order → verify"
            )
        state.next_action = f"{signal} SIGNAL — EXECUTING"
        side = "BUY" if signal == "LONG" else "SELL"
        if place_entry_order(dhan, config, state, side, ltp):
            state.why_no_trade = "ENTRY_EXECUTED"
            state.engine_state = "MONITORING"
            push_event(
                "POSITION",
                f"{state.current_position} {state.position_quantity} @ {state.entry_price}",
            )
        else:
            logging.error("Entry was not confirmed. Not retrying blindly.")
            state.engine_state = "READY"
    compute_next_action(config, state)


def run_one_poll_cycle(
    dhan,
    config: dict,
    state: BotState,
    cached_candles: list[Candle],
) -> tuple[list[Candle], Optional[str]]:
    """One trading API cycle. Returns (candles, terminal_reason)."""
    now = now_in_session_tz(config)
    state.loop_cycle += 1
    interval = float(config["runtime"]["polling_interval_seconds"])
    state.next_poll_at = now + timedelta(seconds=interval)

    if stop_requested():
        return cached_candles, "MANUAL_STOP"
    if is_after_session_stop(config, now):
        return cached_candles, "SESSION_END"

    allow_entries = not is_before_session_start(config, now)
    if not allow_entries:
        compute_next_action(config, state)

    if sync_pending_order(dhan, config, state):
        compute_next_action(config, state)
        return cached_candles, None

    reconcile_every = int(config["runtime"]["reconcile_every_cycles"])
    if state.loop_cycle == 1 or state.loop_cycle % reconcile_every == 0:
        reconcile_state(dhan, config, state)

    ltp = get_ltp(
        dhan,
        str(config["trading"]["security_id"]),
        str(config["trading"]["exchange_segment"]),
    )
    if ltp:
        state.last_ltp = ltp
        state.api_status = "CONNECTED"
    monitor_position(dhan, config, state, ltp)

    if state.current_position != "FLAT":
        hit = monitor_tpsl(dhan, config, state, ltp)
        if hit:
            logging.info("%s HIT", hit.replace("_", " "))
            push_event("EXIT", hit)
            state.last_exit_reason = hit
            if config["shutdown"].get("close_positions_on_tp_sl"):
                place_exit_order(dhan, config, state, ltp)
                cancel_pending_orders(dhan, config, state)
            return cached_candles, hit
        compute_next_action(config, state)
        return cached_candles, None

    if not allow_entries:
        return cached_candles, None

    blocked = daily_risk_blocked(config, state)
    if blocked:
        state.why_no_trade = blocked
        compute_next_action(config, state)
        return cached_candles, None

    candles = get_market_data(dhan, config)
    state.last_market_data_at = now_in_session_tz(config)
    if not candles:
        logging.warning("No usable candles this cycle. Waiting.")
        state.why_no_trade = "WAITING_FOR_MARKET_DATA"
        state.api_status = "DEGRADED"
        compute_next_action(config, state)
        return cached_candles, None

    cached_candles = candles
    process_new_candle(dhan, config, state, cached_candles, ltp, allow_entries)
    return cached_candles, None


def run_trading_loop(dhan, config: dict, state: BotState) -> None:
    """
    Poll market data, signals, positions, and TP/SL until a shutdown reason.

    CLI refresh and API polling are independent: the dashboard may redraw
    every second from memory while Dhan is contacted only on the trading
    interval.
    """
    interval = float(config["runtime"]["polling_interval_seconds"])
    refresh = float(config["cli"]["refresh_seconds"])
    cached_candles: list[Candle] = []
    last_poll = 0.0
    logging.info("Entering trading loop (poll every %s seconds).", interval)
    use_live = dashboard_enabled(config)

    def maybe_poll() -> Optional[str]:
        nonlocal cached_candles, last_poll
        now_mono = time.monotonic()
        if last_poll != 0.0 and (now_mono - last_poll) < interval:
            compute_next_action(config, state)
            return None
        cached_candles, reason = run_one_poll_cycle(dhan, config, state, cached_candles)
        last_poll = time.monotonic()
        return reason

    if use_live:
        with Live(
            render_dashboard(config, state),
            console=CONSOLE,
            refresh_per_second=max(1, int(1 / max(refresh, 0.2))),
            screen=False,
        ) as live:
            while state.bot_running and not stop_requested():
                reason = maybe_poll()
                live.update(render_dashboard(config, state))
                if reason:
                    state.shutdown_reason = reason
                    break
                if interruptible_sleep(refresh):
                    break
                live.update(render_dashboard(config, state))
    else:
        logging.info("CLI Live dashboard disabled (no TTY or cli.enabled=false). Logging only.")
        while state.bot_running and not stop_requested():
            reason = maybe_poll()
            if reason:
                state.shutdown_reason = reason
                break
            sleep_for = interval
            if last_poll:
                sleep_for = max(0.2, interval - (time.monotonic() - last_poll))
            if interruptible_sleep(min(sleep_for, interval)):
                break

    if stop_requested() and not state.shutdown_reason:
        state.shutdown_reason = "MANUAL_STOP"


def graceful_shutdown(dhan, config: dict, state: BotState, reason: str) -> None:
    """
    Stop entries, optionally flatten, verify, log, and exit the loop.

    Purpose:
        Leave the account in a known state: no new signals, optional
        flatten, optional cancel, then a clean process exit.

    Safety:
        Local flags are set even when the broker flatten fails.
    """
    logging.info("Shutdown requested (%s).", reason)
    state.engine_state = "STOPPING"
    state.bot_running = False
    if not state.shutdown_reason:
        state.shutdown_reason = reason
    if reason in {"TAKE_PROFIT", "STOP_LOSS"}:
        state.last_exit_reason = reason

    close_positions = False
    if reason in {"SESSION_END"}:
        close_positions = bool(
            config["session"].get("close_all_positions_at_stop_time")
            and config["shutdown"].get("close_positions_on_session_end")
        )
    elif reason in {"TAKE_PROFIT", "STOP_LOSS"}:
        close_positions = bool(config["shutdown"].get("close_positions_on_tp_sl")) and (
            state.current_position != "FLAT"
        )
    elif reason in {"MANUAL_STOP", "SIGINT", "SIGTERM"}:
        close_positions = bool(config["shutdown"].get("close_positions_on_manual_stop"))
    elif reason == "ERROR":
        close_positions = bool(config["shutdown"].get("close_positions_on_error"))

    if close_positions and dhan is not None:
        close_all_positions(dhan, config, state)
    elif state.current_position != "FLAT":
        logging.info(
            "Positions were left open by configuration. Local side=%s qty=%s",
            state.current_position,
            state.position_quantity,
        )

    if dhan is not None:
        cancel_pending_orders(dhan, config, state)

    if dhan is not None and not is_paper_mode(config):
        read_ok, leftover = get_open_position(dhan, config)
        if not read_ok:
            logging.info("Final broker position could not be retrieved.")
        elif leftover is not None:
            logging.info(
                "Final broker position: security_id=%s netQty=%s",
                _position_security_id(leftover),
                _position_net_qty(leftover),
            )
        else:
            logging.info("Final broker position: FLAT")
            state.engine_state = "POSITION_CLOSED"

    state.engine_state = "STOPPED"
    logging.info("STOP_REASON = %s", state.shutdown_reason)
    logging.info("BOT STOPPED")


# ============================================================
# MAIN
# ============================================================

def main() -> int:
    """Load configuration, authenticate, recover, then run the trading loop."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stderr,
    )
    install_signal_handlers()
    dhan = None
    config: dict = {}
    state = BotState()

    try:
        config = load_config()
        setup_logging(config)
        load_environment(config)
        validate_config(config)
        validate_safety_config(config)
        logging.info("CONFIGURATION LOADED")
        logging.info("CONFIGURATION VALIDATED")
        logging.info("%s MODE", config["environment"]["mode"])

        consume_leftover_stop_file()
        if stop_requested():
            logging.info("Stop requested at startup. No orders were placed.")
            return 0

        state.started_at = now_in_session_tz(config)
        render_startup_banner(config)
        logging.info("BOT STARTED")

        dhan = create_dhan_client(config)
        state.api_status = "CONNECTED"
        logging.info("DHAN CONNECTED")

        if config["recovery"].get("enabled"):
            recover_existing_state(dhan, config, state)

        if stop_requested():
            graceful_shutdown(dhan, config, state, "MANUAL_STOP")
            return 0

        compute_next_action(config, state)
        run_trading_loop(dhan, config, state)

        reason = state.shutdown_reason or (
            "MANUAL_STOP" if stop_requested() else "SESSION_END"
        )
        graceful_shutdown(dhan, config, state, reason)
        return 0

    except (ConfigError, SafetyError, CredentialError) as exc:
        logging.error("%s", exc)
        CONSOLE.print(f"[bold red]{exc}[/bold red]")
        return 1
    except KeyboardInterrupt:
        graceful_shutdown(dhan, config, state, "SIGINT")
        return 0
    except Exception:
        logging.exception("Unexpected error. No additional order will be placed.")
        state.engine_state = "ERROR"
        try:
            if config and dhan is not None:
                graceful_shutdown(dhan, config, state, "ERROR")
        except Exception:
            logging.exception("Shutdown after error also failed.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
