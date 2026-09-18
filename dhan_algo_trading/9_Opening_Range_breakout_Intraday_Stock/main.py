#!/usr/bin/env python3
"""Dhan Opening Range Breakout Algo for NSE equity.

Run (from this directory, after ``pip install -r requirements.txt``):

    python3 main.py
    python3 main.py --config config.yaml

Stop safely from another shell (does not kill the process):

    python3 stop.py

``stop.py`` creates a local ``.stop`` file. This process polls that file and
then shuts down: no new entries, optional close-all, then a clean exit.
SIGINT (Ctrl+C) and SIGTERM do the same.

This file is self-contained. It does not import anything from ``docs/``.
Credentials come from ``.env``. Strategy and risk settings come from
``config.yaml``.

Any verified TP or SL exit stops the process. That is intentional: the bot
does not hunt for a second trade after take-profit or stop-loss.
"""

# ============================================================
# IMPORTS
# ============================================================

from __future__ import annotations

import argparse
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
QUOTE_MIN_INTERVAL_SECONDS = 1.05
CLOSE_VERIFY_ATTEMPTS = 5

VALID_ORDER_TYPES = {"MARKET", "LIMIT"}
VALID_LIMIT_MODES = {"OFFSET_PERCENT", "ABSOLUTE"}
VALID_PRODUCT_TYPES = {"CNC", "INTRADAY", "INTRA", "MARGIN", "MTF"}
EQUITY_PRODUCTS = {"CNC", "INTRADAY", "INTRA", "MARGIN", "MTF"}
DERIVATIVE_PRODUCTS = {"INTRADAY", "INTRA", "MARGIN"}
VALID_TP_SL_TYPES = {"PERCENT", "POINTS", "PERCENTAGE"}

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
    "WAITING_FOR_SESSION": "Waiting for the trading session",
    "BUILDING_OPENING_RANGE": "Opening range is still forming — no entries",
    "ORB_INCOMPLETE": "Opening range is not frozen yet",
    "NO_BREAKOUT": "No confirmed breakout yet",
    "LONG_DISABLED": "Long entries are disabled in config",
    "SHORT_DISABLED": "Short entries are disabled in config",
    "POSITION_ALREADY_OPEN": "A position is already open",
    "MAX_TRADES_REACHED": "Maximum trades for today have been reached",
    "SESSION_NOT_STARTED": "Session has not started yet",
    "SESSION_ENDED": "Session has ended",
    "ENTRY_CUTOFF": "Entry cutoff has passed — no new trades",
    "WEEKEND": "Weekend — market is expected to be closed",
    "RISK_LIMIT_REACHED": "A daily risk limit has been reached",
    "PENDING_ORDER_EXISTS": "An order is already in flight",
    "STOP_REQUESTED": "A stop has been requested",
    "API_UNAVAILABLE": "Dhan API data is currently unavailable",
    "CONFIGURATION_ERROR": "Configuration is invalid",
    "BOT_DISABLED": "strategy.enabled is false",
    "SCANNING": "Flat — scanning for an ORB breakout",
    "MONITORING_TP_SL": "Position open — monitoring take-profit / stop-loss",
    "BLOCKED_UNEXPECTED_POSITION": "Unexpected broker position blocked new entries",
    "ENTRY_EXECUTED": "Entry executed — switching to monitoring",
    "EXIT_EXECUTED": "Exit executed",
    "LONG_ALREADY_FIRED": "A long breakout was already consumed today",
    "SHORT_ALREADY_FIRED": "A short breakout was already consumed today",
    "WAITING_FOR_CONFIRMATION": "Waiting for confirmation candles",
    "NONE": "No block",
}

_shutdown_requested = False
_manual_stop_announced = False
_last_good_ltp: Optional[float] = None
_last_quote_monotonic: float = 0.0
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
    engine_state: str = "NO_POSITION"
    entry_price: Optional[float] = None
    current_position: str = "FLAT"
    position_quantity: int = 0
    trade_direction: Optional[str] = None
    take_profit_price: Optional[float] = None
    stop_loss_price: Optional[float] = None
    highest_price: Optional[float] = None
    lowest_price: Optional[float] = None
    last_processed_candle: Optional[datetime] = None
    last_signal: str = "HOLD"
    confirmation_status: str = "—"
    strategy_condition: str = "INITIALIZING"
    last_entry_signal: Optional[str] = None
    next_action: str = "STARTING"
    why_no_trade: str = "WAITING_FOR_MARKET_DATA"
    shutdown_reason: Optional[str] = None
    pending_order_id: Optional[str] = None
    pending_order_tag: Optional[str] = None
    pending_order_intent: Optional[str] = None
    pending_order_side: Optional[str] = None
    pending_order_quantity: int = 0
    last_order_id: Optional[str] = None
    last_order_status: str = "NOT_SUBMITTED"
    last_error: str = "—"
    order_in_flight: bool = False
    adopted_existing: bool = False
    loop_cycle: int = 0
    opening_range_complete: bool = False
    opening_range_high: Optional[float] = None
    opening_range_low: Optional[float] = None
    long_breakout_level: Optional[float] = None
    short_breakout_level: Optional[float] = None
    long_breakout_fired: bool = False
    short_breakout_fired: bool = False
    consecutive_long_closes: int = 0
    consecutive_short_closes: int = 0
    last_confirm_candle: Optional[datetime] = None
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
# ENVIRONMENT / CONFIG LOADING
# ============================================================

def load_environment() -> None:
    """
    Load Dhan credentials from BASE_DIR/.env or the process environment.

    Why this function exists:
        The Dhan client cannot be created without a client id and access token.
        Loading them here means the rest of the program never hard-codes secrets.

    Side effects:
        Populates os.environ. Never prints token values.
    """
    load_dotenv(ENV_FILE)
    load_dotenv()


def parse_cli_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Dhan Opening Range Breakout Algo")
    parser.add_argument("--config", default=str(CONFIG_FILE), help="Path to config.yaml")
    return parser.parse_args(argv)


def load_config(path: Optional[Path] = None) -> dict:
    """
    Read YAML configuration from disk.

    Returns:
        Parsed mapping.

    Raises:
        ConfigError: File missing or not a mapping.
    """
    config_path = path or CONFIG_FILE
    if not config_path.exists():
        raise ConfigError(f"ERROR: Configuration file not found: {config_path}\nThe bot did not start.")
    try:
        with config_path.open("r", encoding="utf-8") as handle:
            loaded = yaml.safe_load(handle)
    except yaml.YAMLError as exc:
        raise ConfigError(f"ERROR: config.yaml is not valid YAML: {exc}\nThe bot did not start.") from exc
    if not isinstance(loaded, dict):
        raise ConfigError("ERROR: config.yaml must contain a mapping.\nThe bot did not start.")
    return loaded


def _require_section(config: dict, name: str) -> dict:
    section = config.get(name)
    if not isinstance(section, dict):
        raise ConfigError(f"ERROR: {name} must be a mapping in config.yaml.\nThe bot did not start.")
    return section


def _as_positive_number(value: Any, field_name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"ERROR: {field_name} must be a number.\nThe bot did not start.") from exc
    if number <= 0:
        raise ConfigError(f"ERROR: {field_name} must be > 0.\nThe bot did not start.")
    return number


def _as_non_negative_number(value: Any, field_name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"ERROR: {field_name} must be a number.\nThe bot did not start.") from exc
    if number < 0:
        raise ConfigError(f"ERROR: {field_name} must be >= 0.\nThe bot did not start.")
    return number


def _parse_hhmm(value: Any, field_name: str) -> tuple[int, int]:
    text = str(value or "").strip()
    try:
        hour_s, minute_s = text.split(":")
        hour = int(hour_s)
        minute = int(minute_s)
    except (TypeError, ValueError) as exc:
        raise ConfigError(
            f"ERROR: {field_name} must be HH:MM (got {value!r}).\nThe bot did not start."
        ) from exc
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ConfigError(f"ERROR: {field_name} is not a valid clock time.\nThe bot did not start.")
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


def _normalize_level_type(raw: Any, field_name: str) -> str:
    text = str(raw or "PERCENT").strip().upper()
    if text == "PERCENTAGE":
        text = "PERCENT"
    if text not in {"PERCENT", "POINTS"}:
        raise ConfigError(
            f"ERROR: {field_name} must be PERCENT or POINTS.\nThe bot did not start."
        )
    return text


def validate_config(config: dict) -> None:
    """
    Fail fast if any required setting is missing or inconsistent.

    Why this function exists:
        A live Dhan account will accept orders that a bad config would send.
        Validation happens before authentication and always before the first order.

    Side effects:
        Mutates config in place with normalized types and convenience aliases
        (bot / instrument / trading_hours / shutdown) derived from the spec
        sections so the rest of the engine can read one shape.
    """
    app = _require_section(config, "app")
    market = _require_section(config, "market")
    strategy = _require_section(config, "strategy")
    risk = _require_section(config, "risk")
    day_trading = _require_section(config, "day_trading")
    trading_session = _require_section(config, "trading_session")
    execution = _require_section(config, "execution")
    safety = _require_section(config, "safety")
    logging_cfg = _require_section(config, "logging")
    cli = _require_section(config, "cli")

    if not str(app.get("name") or "").strip():
        app["name"] = "Dhan ORB Algo"
    app["environment"] = str(app.get("environment") or "paper").strip().lower() or "paper"
    app["log_level"] = str(app.get("log_level") or logging_cfg.get("level") or "INFO").strip().upper()
    app["polling_seconds"] = _as_positive_number(app.get("polling_seconds", 5), "app.polling_seconds")

    security_id = str(market.get("security_id") or "").strip()
    symbol = str(market.get("trading_symbol") or market.get("symbol") or "").strip()
    if not security_id:
        raise ConfigError("ERROR: market.security_id is required.\nThe bot did not start.")
    if not symbol:
        raise ConfigError("ERROR: market.trading_symbol is required.\nThe bot did not start.")
    market["security_id"] = security_id
    market["trading_symbol"] = symbol
    exchange_segment = str(market.get("exchange_segment") or "").strip().upper()
    if not exchange_segment:
        raise ConfigError("ERROR: market.exchange_segment is required.\nThe bot did not start.")
    market["exchange_segment"] = exchange_segment
    market["instrument_type"] = str(market.get("instrument_type") or "EQUITY").strip().upper()
    market["tick_size"] = _as_positive_number(market.get("tick_size", 0.05), "market.tick_size")

    strategy["enabled"] = _as_bool(strategy.get("enabled"), True)
    opening_range = strategy.get("opening_range")
    if not isinstance(opening_range, dict):
        raise ConfigError("ERROR: strategy.opening_range must be a mapping.\nThe bot did not start.")
    or_start = _parse_hhmm(opening_range.get("start_time", "09:15"), "strategy.opening_range.start_time")
    or_end = _parse_hhmm(opening_range.get("end_time", "09:30"), "strategy.opening_range.end_time")
    if or_start >= or_end:
        raise ConfigError(
            "ERROR: strategy.opening_range.start_time must be before end_time.\nThe bot did not start."
        )
    opening_range["start_time"] = f"{or_start[0]:02d}:{or_start[1]:02d}"
    opening_range["end_time"] = f"{or_end[0]:02d}:{or_end[1]:02d}"
    strategy["opening_range"] = opening_range

    breakout = strategy.get("breakout")
    if not isinstance(breakout, dict):
        raise ConfigError("ERROR: strategy.breakout must be a mapping.\nThe bot did not start.")
    breakout["buffer_points"] = _as_non_negative_number(
        breakout.get("buffer_points", 0), "strategy.breakout.buffer_points"
    )
    breakout["buffer_percent"] = _as_non_negative_number(
        breakout.get("buffer_percent", 0), "strategy.breakout.buffer_percent"
    )
    breakout["apply_both"] = _as_bool(breakout.get("apply_both"), False)
    breakout["confirmation_candles"] = int(
        _as_non_negative_number(
            breakout.get("confirmation_candles", 1), "strategy.breakout.confirmation_candles"
        )
    )
    strategy["breakout"] = breakout

    direction = strategy.get("direction")
    if not isinstance(direction, dict):
        raise ConfigError("ERROR: strategy.direction must be a mapping.\nThe bot did not start.")
    direction["allow_long"] = _as_bool(direction.get("allow_long"), True)
    direction["allow_short"] = _as_bool(direction.get("allow_short"), True)
    if not direction["allow_long"] and not direction["allow_short"]:
        raise ConfigError(
            "ERROR: at least one of strategy.direction.allow_long or allow_short must be true.\n"
            "The bot did not start."
        )
    strategy["direction"] = direction

    entry = strategy.get("entry")
    if not isinstance(entry, dict):
        raise ConfigError("ERROR: strategy.entry must be a mapping.\nThe bot did not start.")
    order_type = str(entry.get("order_type") or "MARKET").strip().upper()
    if order_type not in VALID_ORDER_TYPES:
        raise ConfigError("ERROR: strategy.entry.order_type must be MARKET or LIMIT.\nThe bot did not start.")
    product_type = str(entry.get("product_type") or "INTRADAY").strip().upper()
    if product_type not in VALID_PRODUCT_TYPES:
        raise ConfigError(
            f"ERROR: strategy.entry.product_type must be one of {sorted(VALID_PRODUCT_TYPES)}.\n"
            "The bot did not start."
        )
    if exchange_segment in {"NSE_FNO", "BSE_FNO", "MCX_COMM", "NSE_CURRENCY", "BSE_CURRENCY"}:
        if product_type not in DERIVATIVE_PRODUCTS:
            raise ConfigError(
                "ERROR: F&O / commodity product_type must be INTRADAY or MARGIN.\nThe bot did not start."
            )
    elif product_type not in EQUITY_PRODUCTS:
        raise ConfigError("ERROR: equity product_type is invalid.\nThe bot did not start.")
    entry["order_type"] = order_type
    entry["product_type"] = product_type
    strategy["entry"] = entry

    quantity = int(_as_positive_number(risk.get("quantity"), "risk.quantity"))
    if quantity != float(risk.get("quantity")):
        raise ConfigError("ERROR: risk.quantity must be a whole number.\nThe bot did not start.")
    risk["quantity"] = quantity

    stop_loss = risk.get("stop_loss")
    if not isinstance(stop_loss, dict):
        raise ConfigError("ERROR: risk.stop_loss must be a mapping.\nThe bot did not start.")
    stop_loss["enabled"] = _as_bool(stop_loss.get("enabled"), True)
    stop_loss["type"] = _normalize_level_type(stop_loss.get("type", "PERCENT"), "risk.stop_loss.type")
    if stop_loss["enabled"]:
        stop_loss["value"] = _as_positive_number(stop_loss.get("value"), "risk.stop_loss.value")
    else:
        stop_loss["value"] = _as_non_negative_number(stop_loss.get("value", 0), "risk.stop_loss.value")
    risk["stop_loss"] = stop_loss

    take_profit = risk.get("take_profit")
    if not isinstance(take_profit, dict):
        raise ConfigError("ERROR: risk.take_profit must be a mapping.\nThe bot did not start.")
    take_profit["enabled"] = _as_bool(take_profit.get("enabled"), True)
    take_profit["type"] = _normalize_level_type(take_profit.get("type", "PERCENT"), "risk.take_profit.type")
    if take_profit["enabled"]:
        take_profit["value"] = _as_positive_number(take_profit.get("value"), "risk.take_profit.value")
    else:
        take_profit["value"] = _as_non_negative_number(take_profit.get("value", 0), "risk.take_profit.value")
    risk["take_profit"] = take_profit

    risk["max_trades_per_day"] = int(
        _as_non_negative_number(risk.get("max_trades_per_day", 1), "risk.max_trades_per_day")
    )
    max_daily_loss = risk.get("max_daily_loss")
    if not isinstance(max_daily_loss, dict):
        raise ConfigError("ERROR: risk.max_daily_loss must be a mapping.\nThe bot did not start.")
    max_daily_loss["enabled"] = _as_bool(max_daily_loss.get("enabled"), False)
    max_daily_loss["value"] = _as_non_negative_number(
        max_daily_loss.get("value", 0), "risk.max_daily_loss.value"
    )
    risk["max_daily_loss"] = max_daily_loss
    risk["close_on_risk_limit"] = _as_bool(risk.get("close_on_risk_limit"), False)
    risk["estimated_cost_per_trade"] = _as_non_negative_number(
        risk.get("estimated_cost_per_trade", 0), "risk.estimated_cost_per_trade"
    )

    day_trading["enabled"] = _as_bool(day_trading.get("enabled"), True)
    day_trading["force_exit_enabled"] = _as_bool(day_trading.get("force_exit_enabled"), True)
    force_h, force_m = _parse_hhmm(day_trading.get("force_exit_time", "15:15"), "day_trading.force_exit_time")
    day_trading["force_exit_time"] = f"{force_h:02d}:{force_m:02d}"
    day_trading["timezone"] = str(day_trading.get("timezone") or "Asia/Kolkata").strip()

    start_h, start_m = _parse_hhmm(
        trading_session.get("start_time", "09:15"), "trading_session.start_time"
    )
    stop_h, stop_m = _parse_hhmm(
        trading_session.get("stop_new_entries_time", "15:00"),
        "trading_session.stop_new_entries_time",
    )
    trading_session["start_time"] = f"{start_h:02d}:{start_m:02d}"
    trading_session["stop_new_entries_time"] = f"{stop_h:02d}:{stop_m:02d}"
    trading_session["timezone"] = str(
        trading_session.get("timezone") or day_trading["timezone"] or "Asia/Kolkata"
    ).strip()
    if (start_h, start_m) >= (stop_h, stop_m):
        raise ConfigError(
            "ERROR: trading_session.start_time must be before stop_new_entries_time.\n"
            "The bot did not start."
        )
    if day_trading["enabled"] and day_trading["force_exit_enabled"]:
        if (stop_h, stop_m) > (force_h, force_m):
            raise ConfigError(
                "ERROR: trading_session.stop_new_entries_time must be at or before "
                "day_trading.force_exit_time.\nThe bot did not start."
            )

    execution["order_timeout_seconds"] = _as_positive_number(
        execution.get("order_timeout_seconds", 15), "execution.order_timeout_seconds"
    )
    execution["order_status_poll_seconds"] = _as_positive_number(
        execution.get("order_status_poll_seconds", 2), "execution.order_status_poll_seconds"
    )
    execution["retry_attempts"] = max(
        1,
        int(_as_positive_number(execution.get("retry_attempts", 3), "execution.retry_attempts")),
    )
    execution["retry_delay_seconds"] = _as_positive_number(
        execution.get("retry_delay_seconds", 2), "execution.retry_delay_seconds"
    )
    execution["validity"] = str(execution.get("validity") or "DAY").strip().upper() or "DAY"
    execution["reconcile_every_cycles"] = max(
        1,
        int(
            _as_positive_number(
                execution.get("reconcile_every_cycles", 6), "execution.reconcile_every_cycles"
            )
        ),
    )
    limit_mode = str(execution.get("limit_price_mode") or "OFFSET_PERCENT").strip().upper()
    if limit_mode not in VALID_LIMIT_MODES:
        raise ConfigError(
            "ERROR: execution.limit_price_mode must be OFFSET_PERCENT or ABSOLUTE.\nThe bot did not start."
        )
    execution["limit_price_mode"] = limit_mode
    execution["limit_offset_percent"] = _as_non_negative_number(
        execution.get("limit_offset_percent", 0), "execution.limit_offset_percent"
    )
    execution["limit_price"] = _as_non_negative_number(
        execution.get("limit_price", 0), "execution.limit_price"
    )
    if limit_mode == "ABSOLUTE" and order_type == "LIMIT" and execution["limit_price"] <= 0:
        raise ConfigError(
            "ERROR: execution.limit_price must be > 0 when limit_price_mode is ABSOLUTE.\n"
            "The bot did not start."
        )
    execution["order_type"] = order_type
    execution["enable_long"] = direction["allow_long"]
    execution["enable_short"] = direction["allow_short"]
    execution["prevent_duplicate_orders"] = _as_bool(
        safety.get("prevent_duplicate_orders", True), True
    )

    safety["dry_run"] = _as_bool(safety.get("dry_run"), True)
    safety["allow_live_trading"] = _as_bool(safety.get("allow_live_trading"), False)
    safety["prevent_duplicate_orders"] = execution["prevent_duplicate_orders"]
    safety["require_market_hours"] = _as_bool(safety.get("require_market_hours"), True)
    safety["close_positions_on_stop"] = _as_bool(safety.get("close_positions_on_stop"), False)
    safety["close_positions_on_session_end"] = _as_bool(
        safety.get("close_positions_on_session_end"), True
    )
    safety["close_positions_on_tp_sl"] = _as_bool(safety.get("close_positions_on_tp_sl"), True)
    safety["close_positions_on_error"] = _as_bool(safety.get("close_positions_on_error"), False)
    safety["cancel_pending_orders"] = _as_bool(safety.get("cancel_pending_orders"), True)
    safety["manage_only_configured_symbol"] = _as_bool(
        safety.get("manage_only_configured_symbol"), True
    )
    safety["require_flat_before_entry"] = _as_bool(safety.get("require_flat_before_entry"), True)
    safety["block_if_unexpected_position"] = _as_bool(
        safety.get("block_if_unexpected_position"), True
    )

    logging_cfg["file_enabled"] = _as_bool(logging_cfg.get("file_enabled"), True)
    logging_cfg["file_name"] = str(logging_cfg.get("file_name") or "orb_algo.log").strip()
    logging_cfg["level"] = str(logging_cfg.get("level") or app["log_level"] or "INFO").strip().upper()
    app["log_level"] = logging_cfg["level"]

    cli["enabled"] = _as_bool(cli.get("enabled"), True)
    cli["refresh_seconds"] = _as_positive_number(cli.get("refresh_seconds", 1), "cli.refresh_seconds")
    cli["show_indicators"] = _as_bool(cli.get("show_indicators"), True)
    cli["show_signal"] = _as_bool(cli.get("show_signal"), True)
    cli["show_orders"] = _as_bool(cli.get("show_orders"), True)
    cli["event_history_size"] = int(
        _as_positive_number(cli.get("event_history_size", 8), "cli.event_history_size")
    )

    # Convenience aliases used by the broker / order engine.
    config["bot"] = {
        "name": app["name"],
        "enabled": strategy["enabled"],
        "dry_run": safety["dry_run"],
        "allow_live_trading": safety["allow_live_trading"],
        "polling_seconds": app["polling_seconds"],
        "order_wait_seconds": execution["order_timeout_seconds"],
        "reconcile_every_cycles": execution["reconcile_every_cycles"],
    }
    config["instrument"] = {
        "exchange_segment": market["exchange_segment"],
        "symbol": market["trading_symbol"],
        "security_id": market["security_id"],
        "instrument_type": market["instrument_type"],
        "tick_size": market["tick_size"],
        "product_type": entry["product_type"],
        "quantity": risk["quantity"],
    }
    config["trading_hours"] = {
        "enabled": safety["require_market_hours"],
        "start_time": trading_session["start_time"],
        "stop_entry_time": trading_session["stop_new_entries_time"],
        "close_positions_time": day_trading["force_exit_time"],
        "timezone": trading_session["timezone"],
        "day_trading_enabled": day_trading["enabled"],
        "force_exit_enabled": day_trading["force_exit_enabled"],
    }
    config["shutdown"] = {
        "close_positions_on_manual_stop": safety["close_positions_on_stop"],
        "close_positions_on_session_end": safety["close_positions_on_session_end"],
        "close_positions_on_tp_sl": safety["close_positions_on_tp_sl"],
        "close_positions_on_error": safety["close_positions_on_error"],
        "cancel_pending_orders": safety["cancel_pending_orders"],
    }
    config["startup"] = {
        "behavior": "WAIT_FOR_SIGNAL",
        "wait_for_start_time": True,
        "reconcile_existing_positions": True,
        "manage_existing_position": True,
    }


def is_dry_run(config: dict) -> bool:
    """True when live place_order must never be called."""
    return not is_live_mode(config)


def is_live_mode(config: dict) -> bool:
    safety = config.get("safety", {})
    return (not bool(safety.get("dry_run", True))) and bool(safety.get("allow_live_trading", False))


def validate_safety_config(config: dict) -> None:
    """
    Live trading requires dry_run=false AND allow_live_trading=true.

    Why this function exists:
        A single flag is too easy to flip by accident on a 1 GB VM that can
        place real orders. The second lock must be set deliberately.
    """
    safety = config.get("safety", {})
    if bool(safety.get("dry_run", True)):
        return
    if not safety.get("allow_live_trading"):
        raise SafetyError(
            "ERROR: Live trading is not fully unlocked.\n"
            "Set safety.dry_run: false and safety.allow_live_trading: true.\n"
            "The bot did not start."
        )


# ============================================================
# LOGGING
# ============================================================

class EventHistoryHandler(logging.Handler):
    """Copy log lines into the in-memory dashboard ring. Never stores secrets."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record)
        except Exception:
            return
        lowered = message.lower()
        if "access_token" in lowered or "client_id" in lowered:
            return
        _event_history.append(message)


def setup_logging(config: dict) -> None:
    """
    Configure console (and optional file) logging.

    Why this function exists:
        The CLI dashboard must stay clean while events still go to a file
        on a headless AWS VM.
    """
    logging_cfg = config.get("logging", {})
    level_name = str(logging_cfg.get("level") or "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    root = logging.getLogger()
    root.setLevel(level)
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    if not any(isinstance(handler, logging.StreamHandler) for handler in root.handlers):
        stream = logging.StreamHandler(sys.stderr)
        stream.setFormatter(formatter)
        root.addHandler(stream)
    if logging_cfg.get("file_enabled"):
        log_path = BASE_DIR / str(logging_cfg.get("file_name") or "orb_algo.log")
        already = any(
            isinstance(handler, logging.FileHandler)
            and getattr(handler, "baseFilename", "") == str(log_path)
            for handler in root.handlers
        )
        if not already:
            file_handler = logging.FileHandler(log_path, encoding="utf-8")
            file_handler.setFormatter(formatter)
            root.addHandler(file_handler)
    root.addHandler(EventHistoryHandler())
    global _event_history
    _event_history = deque(maxlen=int(config["cli"]["event_history_size"]))


def push_event(kind: str, detail: str) -> None:
    _event_history.append(f"{kind}: {detail}")


def record_error(state: BotState, message: str) -> None:
    state.last_error = message
    state.api_status = "DEGRADED"


# ============================================================
# STOP SIGNAL
# ============================================================

def consume_leftover_stop_file() -> None:
    """Delete a leftover .stop from a previous run so a new start is not halted."""
    if STOP_FILE.exists():
        try:
            STOP_FILE.unlink()
            logging.info("Removed leftover stop file from a previous run.")
        except OSError as exc:
            logging.warning("Could not remove leftover stop file: %s", exc)


def check_stop_signal() -> bool:
    """True when stop.py wrote .stop or a process signal arrived."""
    return _shutdown_requested or STOP_FILE.exists()


def stop_requested() -> bool:
    return check_stop_signal()


def _handle_shutdown_signal(signum, _frame) -> None:
    global _shutdown_requested
    _shutdown_requested = True
    logging.info("Received signal %s. Shutdown requested.", signum)


def install_signal_handlers() -> None:
    signal.signal(signal.SIGINT, _handle_shutdown_signal)
    signal.signal(signal.SIGTERM, _handle_shutdown_signal)


def announce_manual_stop_if_needed() -> None:
    """Print the spec-required message once when stop.py is detected."""
    global _manual_stop_announced
    if STOP_FILE.exists() and not _manual_stop_announced:
        _manual_stop_announced = True
        logging.info("MANUAL STOP REQUEST RECEIVED")
        CONSOLE.print("[bold yellow]MANUAL STOP REQUEST RECEIVED[/bold yellow]")


# ============================================================
# TIME AND SESSION
# ============================================================

def session_timezone(config: dict):
    name = str(
        config.get("trading_hours", {}).get("timezone")
        or config.get("trading_session", {}).get("timezone")
        or config.get("day_trading", {}).get("timezone")
        or "Asia/Kolkata"
    )
    if ZoneInfo is not None:
        try:
            return ZoneInfo(name)
        except Exception:
            logging.warning("Unknown timezone %s. Falling back to UTC.", name)
    return timezone.utc


def now_in_session_tz(config: dict) -> datetime:
    return datetime.now(session_timezone(config))


def epoch_to_local(ts: Any, tzinfo) -> Optional[datetime]:
    try:
        value = float(ts)
    except (TypeError, ValueError):
        return None
    if value > 1e12:
        value /= 1000.0
    try:
        return datetime.fromtimestamp(value, tz=timezone.utc).astimezone(tzinfo)
    except (OverflowError, OSError, ValueError):
        return None


def _clock_on(now: datetime, hhmm: str) -> datetime:
    hour, minute = _parse_hhmm(hhmm, "session clock")
    return now.replace(hour=hour, minute=minute, second=0, microsecond=0)


def is_session_enabled(config: dict) -> bool:
    return bool(config.get("trading_hours", {}).get("enabled"))


def is_weekend(config: dict, now: Optional[datetime] = None) -> bool:
    current = now or now_in_session_tz(config)
    return current.weekday() >= 5


def is_before_session_start(config: dict, now: Optional[datetime] = None) -> bool:
    if not is_session_enabled(config):
        return False
    current = now or now_in_session_tz(config)
    if is_weekend(config, current):
        return True
    return current < _clock_on(current, config["trading_hours"]["start_time"])


def is_after_stop_entry(config: dict, now: Optional[datetime] = None) -> bool:
    if not is_session_enabled(config):
        return False
    current = now or now_in_session_tz(config)
    if is_weekend(config, current):
        return True
    return current >= _clock_on(current, config["trading_hours"]["stop_entry_time"])


def is_after_close_positions(config: dict, now: Optional[datetime] = None) -> bool:
    """True on a weekday at or after force-exit when day-trading flatten is on."""
    hours = config.get("trading_hours", {})
    if not hours.get("day_trading_enabled") or not hours.get("force_exit_enabled"):
        return False
    current = now or now_in_session_tz(config)
    if is_weekend(config, current):
        return False
    return current >= _clock_on(current, hours["close_positions_time"])


def check_force_exit(config: dict, now: Optional[datetime] = None) -> bool:
    """True when the configured day-trading flatten clock has been reached."""
    return is_after_close_positions(config, now)


def check_trading_window(config: dict, now: Optional[datetime] = None) -> tuple[bool, str]:
    """
    Decide whether new entries are allowed right now.

    Returns:
        (allowed, reason_code). Never places an order.
    """
    if not config.get("strategy", {}).get("enabled", True):
        return False, "BOT_DISABLED"
    current = now or now_in_session_tz(config)
    if is_weekend(config, current) and is_session_enabled(config):
        return False, "WEEKEND"
    if is_before_session_start(config, current):
        return False, "SESSION_NOT_STARTED"
    if is_after_close_positions(config, current):
        return False, "SESSION_ENDED"
    if is_after_stop_entry(config, current):
        return False, "ENTRY_CUTOFF"
    return True, "NONE"


def is_market_expected_open(config: dict, now: Optional[datetime] = None) -> bool:
    current = now or now_in_session_tz(config)
    if current.weekday() >= 5:
        return False
    if not is_session_enabled(config):
        return True
    return not is_before_session_start(config, current) and not is_after_close_positions(
        config, current
    )


def interruptible_sleep(seconds: float) -> bool:
    """Sleep in small slices so .stop / SIGINT can interrupt. True if stop requested."""
    deadline = time.monotonic() + max(0.0, seconds)
    while time.monotonic() < deadline:
        if stop_requested():
            return True
        time.sleep(min(0.25, deadline - time.monotonic()))
    return stop_requested()


def format_runtime(started_at: Optional[datetime], now: datetime) -> str:
    if started_at is None:
        return "—"
    total = max(0, int((now - started_at).total_seconds()))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def format_inr(value: Optional[float]) -> str:
    if value is None:
        return "—"
    return f"₹{value:,.2f}"


def _retry_attempts(config: Optional[dict] = None) -> int:
    if not config:
        return 3
    return int(config.get("execution", {}).get("retry_attempts") or 3)


def _retry_delay(config: Optional[dict] = None) -> float:
    if not config:
        return 2.0
    return float(config.get("execution", {}).get("retry_delay_seconds") or 2.0)


# ============================================================
# DHAN CLIENT
# ============================================================

def initialize_dhan_client():
    """Alias required by the spec for create_dhan_client()."""
    return create_dhan_client()


def create_dhan_client():
    """
    Build an authenticated Dhan SDK client.

    Why this function exists:
        Newer SDKs want DhanContext; older ones take client_id and token
        directly. This wrapper supports both without exposing secrets.
    """
    client_id = (os.environ.get("DHAN_CLIENT_ID") or "").strip()
    access_token = (os.environ.get("DHAN_ACCESS_TOKEN") or "").strip()
    if not client_id or not access_token:
        raise CredentialError(
            "ERROR: Dhan credentials are missing. The bot did not start."
        )
    if DhanContext is not None:
        context = DhanContext(client_id, access_token)
        return dhanhq(context)
    return dhanhq(client_id, access_token)


def _sdk_value(name: str, fallback: str) -> str:
    return str(getattr(dhanhq, name, fallback))


def _map_exchange_segment(exchange_segment: str) -> str:
    text = str(exchange_segment or "").strip().upper()
    mapping = {
        "NSE": _sdk_value("NSE", "NSE_EQ"),
        "NSE_EQ": _sdk_value("NSE", "NSE_EQ"),
        "BSE": _sdk_value("BSE", "BSE_EQ"),
        "BSE_EQ": _sdk_value("BSE", "BSE_EQ"),
        "NSE_FNO": _sdk_value("NSE_FNO", "NSE_FNO"),
        "BSE_FNO": _sdk_value("BSE_FNO", "BSE_FNO"),
        "MCX": _sdk_value("MCX", "MCX_COMM"),
        "MCX_COMM": _sdk_value("MCX", "MCX_COMM"),
        "IDX_I": _sdk_value("INDEX", "IDX_I"),
        "INDEX": _sdk_value("INDEX", "IDX_I"),
    }
    return mapping.get(text, text)


def _map_transaction_type(transaction_type: str) -> str:
    text = str(transaction_type or "").strip().upper()
    if text == "BUY":
        return _sdk_value("BUY", "BUY")
    if text == "SELL":
        return _sdk_value("SELL", "SELL")
    return text


def _map_order_type(order_type: str) -> str:
    text = str(order_type or "").strip().upper()
    if text == "MARKET":
        return _sdk_value("MARKET", "MARKET")
    if text == "LIMIT":
        return _sdk_value("LIMIT", "LIMIT")
    return text


def _map_product_type(product_type: str) -> str:
    text = str(product_type or "").strip().upper()
    if text in {"INTRA", "INTRADAY"}:
        return _sdk_value("INTRA", "INTRADAY")
    if text == "CNC":
        return _sdk_value("CNC", "CNC")
    if text == "MARGIN":
        return _sdk_value("MARGIN", "MARGIN")
    if text == "MTF":
        return _sdk_value("MTF", "MTF")
    return text


def _map_validity(validity: str) -> str:
    text = str(validity or "DAY").strip().upper()
    if text == "IOC":
        return _sdk_value("IOC", "IOC")
    return _sdk_value("DAY", "DAY")


def _unwrap_dhan_data(response: Any) -> Any:
    if isinstance(response, dict) and "data" in response:
        return response.get("data")
    return response


def _first_dict(payload: Any) -> Optional[dict]:
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict):
                return item
    return None


def _dhan_error_text(response: Any) -> str:
    if not isinstance(response, dict):
        return str(response)
    remarks = response.get("remarks")
    if isinstance(remarks, dict):
        return str(remarks.get("error_message") or remarks.get("message") or remarks)
    if remarks:
        return str(remarks)
    return str(response.get("message") or "Dhan request failed")


def _dhan_ok(response: Any) -> bool:
    if not isinstance(response, dict):
        return False
    status = str(response.get("status") or "").strip().lower()
    return status in {"success", "ok", ""}


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
    if tick_size <= 0:
        return price
    quant = Decimal(str(tick_size))
    rounded = Decimal(str(price)).quantize(quant, rounding=ROUND_HALF_UP)
    return float(rounded)


# ============================================================
# MARKET DATA
# ============================================================

def _rows_from_ohlc_payload(data: Any) -> list[dict]:
    if data is None:
        return []
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if not isinstance(data, dict):
        return []
    if any(isinstance(data.get(key), list) for key in ("open", "high", "low", "close", "timestamp")):
        size = max(
            len(data.get("open") or []),
            len(data.get("close") or []),
            len(data.get("timestamp") or []),
        )
        rows: list[dict] = []
        for index in range(size):
            rows.append(
                {
                    "timestamp": (data.get("timestamp") or [None] * size)[index]
                    if index < len(data.get("timestamp") or [])
                    else None,
                    "open": (data.get("open") or [None] * size)[index]
                    if index < len(data.get("open") or [])
                    else None,
                    "high": (data.get("high") or [None] * size)[index]
                    if index < len(data.get("high") or [])
                    else None,
                    "low": (data.get("low") or [None] * size)[index]
                    if index < len(data.get("low") or [])
                    else None,
                    "close": (data.get("close") or [None] * size)[index]
                    if index < len(data.get("close") or [])
                    else None,
                    "volume": (data.get("volume") or [0] * size)[index]
                    if index < len(data.get("volume") or [])
                    else 0,
                }
            )
        return rows
    inner = data.get("candles") or data.get("data")
    if isinstance(inner, list):
        return [row for row in inner if isinstance(row, dict)]
    return []


def _is_candle_complete(candle: Candle, minutes: int, now: datetime) -> bool:
    close_at = candle.timestamp + timedelta(minutes=minutes)
    return now >= close_at


def validate_candles(candles: list[Candle]) -> list[Candle]:
    """Drop obviously corrupted bars before ORB math."""
    clean: list[Candle] = []
    for candle in candles:
        if candle.close <= 0 or candle.high <= 0 or candle.low <= 0 or candle.open <= 0:
            continue
        if candle.high < max(candle.open, candle.close):
            continue
        if candle.low > min(candle.open, candle.close):
            continue
        if candle.timestamp is None:
            continue
        clean.append(candle)
    return clean


def get_market_data(dhan, config: dict) -> list[Candle]:
    """
    Fetch today's 1-minute candles for the configured equity.

    Why this function exists:
        ORB high/low and confirmation closes must come from the same
        completed-bar series. Only today is retained so a 1 GB VM does
        not accumulate history.

    Returns:
        Today's 1-minute candles, oldest-first. Empty list on failure.
    """
    instrument = config["instrument"]
    tzinfo = session_timezone(config)
    now = now_in_session_tz(config)
    from_date = now.date().strftime("%Y-%m-%d")
    to_date = from_date
    security_id = str(instrument["security_id"])
    exchange_segment = _map_exchange_segment(instrument["exchange_segment"])
    instrument_type = instrument["instrument_type"]
    attempts = _retry_attempts(config)
    delay = _retry_delay(config)
    last_error: Any = None

    for attempt in range(1, attempts + 1):
        try:
            response = dhan.intraday_minute_data(
                security_id=security_id,
                exchange_segment=exchange_segment,
                instrument_type=instrument_type,
                from_date=from_date,
                to_date=to_date,
                interval=1,
            )
            if not _dhan_ok(response):
                raise RuntimeError(_dhan_error_text(response))
            rows = _rows_from_ohlc_payload(_unwrap_dhan_data(response))
            candles: list[Candle] = []
            for row in rows:
                stamp = epoch_to_local(
                    row.get("timestamp") or row.get("start_Time") or row.get("time"),
                    tzinfo,
                )
                close = _safe_float(row.get("close") or row.get("Close"), 0.0)
                if stamp is None or close <= 0:
                    continue
                if stamp.date() != now.date():
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
            return validate_candles(candles)
        except Exception as exc:
            last_error = exc
            logging.warning("Candle fetch failed (attempt %s/%s): %s", attempt, attempts, exc)
            if attempt < attempts:
                time.sleep(delay)
    logging.error("Candle fetch exhausted retries: %s", last_error)
    return []


def get_opening_range_data(candles: list[Candle], config: dict, now: Optional[datetime] = None) -> list[Candle]:
    """Return candles whose IST timestamp sits inside the opening-range window."""
    current = now or now_in_session_tz(config)
    start = _clock_on(current, config["strategy"]["opening_range"]["start_time"])
    end = _clock_on(current, config["strategy"]["opening_range"]["end_time"])
    selected: list[Candle] = []
    for candle in candles:
        stamp = candle.timestamp
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=current.tzinfo)
        if start <= stamp < end:
            selected.append(candle)
    return selected


# ============================================================
# ORB CALCULATION
# ============================================================

def calculate_opening_range(
    candles: list[Candle],
    config: dict,
    ltp: Optional[float] = None,
    now: Optional[datetime] = None,
    frozen: bool = False,
) -> tuple[Optional[float], Optional[float]]:
    """
    Compute opening-range high and low.

    Why this function exists:
        The breakout levels are only as good as the frozen range. While the
        window is still open the live LTP is folded in so the dashboard
        moves; after freeze the values must not change.

    Returns:
        (high, low) or (None, None) if no usable bars exist yet.
    """
    current = now or now_in_session_tz(config)
    window = get_opening_range_data(candles, config, current)
    if not window and (ltp is None or ltp <= 0):
        return None, None
    highs = [candle.high for candle in window]
    lows = [candle.low for candle in window]
    if not frozen and ltp is not None and ltp > 0:
        start = _clock_on(current, config["strategy"]["opening_range"]["start_time"])
        end = _clock_on(current, config["strategy"]["opening_range"]["end_time"])
        if start <= current < end:
            highs.append(ltp)
            lows.append(ltp)
    if not highs or not lows:
        return None, None
    return max(highs), min(lows)


def calculate_breakout_levels(
    opening_range_high: float,
    opening_range_low: float,
    config: dict,
) -> tuple[float, float]:
    """
    Apply the configured buffer to the frozen opening range.

    Points and percent are not stacked unless breakout.apply_both is true.

    Returns:
        (long_level, short_level)
    """
    breakout = config["strategy"]["breakout"]
    points = float(breakout.get("buffer_points") or 0)
    percent = float(breakout.get("buffer_percent") or 0)
    apply_both = bool(breakout.get("apply_both"))
    tick = float(config["instrument"]["tick_size"])

    long_level = opening_range_high
    short_level = opening_range_low
    if apply_both:
        if percent > 0:
            long_level = opening_range_high * (1.0 + percent / 100.0)
            short_level = opening_range_low * (1.0 - percent / 100.0)
        if points > 0:
            long_level += points
            short_level -= points
    elif points > 0:
        long_level = opening_range_high + points
        short_level = opening_range_low - points
    elif percent > 0:
        long_level = opening_range_high * (1.0 + percent / 100.0)
        short_level = opening_range_low * (1.0 - percent / 100.0)

    return round_to_tick(long_level, tick), round_to_tick(short_level, tick)


def _completed_after_orb(candles: list[Candle], config: dict, now: datetime) -> list[Candle]:
    end = _clock_on(now, config["strategy"]["opening_range"]["end_time"])
    completed: list[Candle] = []
    for candle in candles:
        stamp = candle.timestamp
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=now.tzinfo)
        if stamp < end:
            continue
        if _is_candle_complete(candle, 1, now):
            completed.append(candle)
    return completed


def check_long_breakout(
    state: BotState,
    candles: list[Candle],
    ltp: Optional[float],
    config: dict,
    now: Optional[datetime] = None,
) -> bool:
    """
    Detect a long breakout event.

    confirmation_candles == 0 uses LTP. N >= 1 requires N consecutive
    completed 1-minute closes at or above the long breakout level.
    Once fired, the event will not fire again today.
    """
    if state.long_breakout_fired or state.long_breakout_level is None:
        return False
    if not config["strategy"]["direction"]["allow_long"]:
        return False
    needed = int(config["strategy"]["breakout"]["confirmation_candles"])
    current = now or now_in_session_tz(config)
    level = state.long_breakout_level
    if needed <= 0:
        return ltp is not None and ltp > level
    completed = _completed_after_orb(candles, config, current)
    if len(completed) < needed:
        state.consecutive_long_closes = len(
            [candle for candle in completed if candle.close > level]
        )
        state.confirmation_status = f"LONG {state.consecutive_long_closes}/{needed}"
        return False
    streak = completed[-needed:]
    ok = all(candle.close > level for candle in streak)
    state.consecutive_long_closes = sum(1 for candle in reversed(completed) if candle.close > level)
    if not ok:
        # Reset consecutive count at the first close that fails.
        count = 0
        for candle in reversed(completed):
            if candle.close > level:
                count += 1
            else:
                break
        state.consecutive_long_closes = count
        state.confirmation_status = f"LONG {count}/{needed}"
        return False
    last = streak[-1]
    if state.last_confirm_candle is not None and last.timestamp <= state.last_confirm_candle:
        return False
    state.confirmation_status = f"LONG {needed}/{needed}"
    return True


def check_short_breakout(
    state: BotState,
    candles: list[Candle],
    ltp: Optional[float],
    config: dict,
    now: Optional[datetime] = None,
) -> bool:
    """Detect a short breakdown event. See check_long_breakout for rules."""
    if state.short_breakout_fired or state.short_breakout_level is None:
        return False
    if not config["strategy"]["direction"]["allow_short"]:
        return False
    needed = int(config["strategy"]["breakout"]["confirmation_candles"])
    current = now or now_in_session_tz(config)
    level = state.short_breakout_level
    if needed <= 0:
        return ltp is not None and ltp < level
    completed = _completed_after_orb(candles, config, current)
    if len(completed) < needed:
        count = len([candle for candle in completed if candle.close < level])
        state.consecutive_short_closes = count
        state.confirmation_status = f"SHORT {count}/{needed}"
        return False
    streak = completed[-needed:]
    ok = all(candle.close < level for candle in streak)
    if not ok:
        count = 0
        for candle in reversed(completed):
            if candle.close < level:
                count += 1
            else:
                break
        state.consecutive_short_closes = count
        state.confirmation_status = f"SHORT {count}/{needed}"
        return False
    last = streak[-1]
    if state.last_confirm_candle is not None and last.timestamp <= state.last_confirm_candle:
        return False
    state.confirmation_status = f"SHORT {needed}/{needed}"
    return True


def update_runtime_state(
    state: BotState,
    config: dict,
    candles: list[Candle],
    ltp: Optional[float],
    now: Optional[datetime] = None,
) -> None:
    """
    Advance ORB construction or freeze it.

    Why this function exists:
        High/low must keep updating during the window and must never
        change after the window ends. Breakout levels are computed once
        at freeze time.
    """
    current = now or now_in_session_tz(config)
    start = _clock_on(current, config["strategy"]["opening_range"]["start_time"])
    end = _clock_on(current, config["strategy"]["opening_range"]["end_time"])

    if current < start:
        state.engine_state = "WAITING"
        state.strategy_condition = "WAITING FOR OPENING RANGE"
        state.why_no_trade = "WAITING_FOR_SESSION"
        return

    if current < end:
        high, low = calculate_opening_range(candles, config, ltp, current, frozen=False)
        state.opening_range_complete = False
        state.opening_range_high = high
        state.opening_range_low = low
        state.long_breakout_level = None
        state.short_breakout_level = None
        state.engine_state = "BUILDING_ORB"
        state.strategy_condition = "BUILDING OPENING RANGE"
        state.why_no_trade = "BUILDING_OPENING_RANGE"
        return

    if not state.opening_range_complete:
        high, low = calculate_opening_range(candles, config, ltp, current, frozen=True)
        if high is None or low is None:
            state.strategy_condition = "ORB DATA MISSING"
            state.why_no_trade = "ORB_INCOMPLETE"
            return
        long_level, short_level = calculate_breakout_levels(high, low, config)
        state.opening_range_high = high
        state.opening_range_low = low
        state.long_breakout_level = long_level
        state.short_breakout_level = short_level
        state.opening_range_complete = True
        logging.info(
            "ORB completed. HIGH=%.2f LOW=%.2f LONG_LEVEL=%.2f SHORT_LEVEL=%.2f",
            high,
            low,
            long_level,
            short_level,
        )
        push_event("ORB", f"FROZEN H={high:.2f} L={low:.2f}")

    if state.current_position == "FLAT" and state.engine_state not in {
        "ENTRY_PENDING",
        "EXIT_PENDING",
        "TRADE_COMPLETED",
        "BOT_STOPPED",
    }:
        state.engine_state = "NO_POSITION"
        state.strategy_condition = "SCANNING FOR BREAKOUT"


# ============================================================
# POSITION / P&L
# ============================================================

def get_positions(dhan, config: Optional[dict] = None) -> Optional[list[dict]]:
    """Fetch the Dhan position book. None means the read failed."""
    last_error: Any = None
    attempts = _retry_attempts(config)
    delay = _retry_delay(config)
    for attempt in range(1, attempts + 1):
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
                inner = data.get("positions") or data.get("data")
                if isinstance(inner, list):
                    return [row for row in inner if isinstance(row, dict)]
                return [data]
            return []
        except Exception as exc:
            last_error = exc
            if attempt < attempts:
                time.sleep(delay)
    logging.warning("Position book read failed: %s", last_error)
    return None


def _position_net_qty(row: dict) -> int:
    return _safe_int(row.get("netQty") or row.get("net_qty") or row.get("quantity"), 0)


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
        return _safe_float(row.get("buyAvg") or row.get("averagePrice") or row.get("avgPrice"), 0.0)
    if side == "SHORT":
        return _safe_float(row.get("sellAvg") or row.get("averagePrice") or row.get("avgPrice"), 0.0)
    return 0.0


def get_open_positions(dhan, config: Optional[dict] = None) -> Optional[list[dict]]:
    positions = get_positions(dhan, config)
    if positions is None:
        return None
    return [row for row in positions if _position_net_qty(row) != 0]


def get_current_position(dhan, config: dict) -> tuple[bool, Optional[dict]]:
    """Return (read_ok, matching open row). read_ok False means do not assume flat."""
    positions = get_positions(dhan, config)
    if positions is None:
        return False, None
    target = str(config["instrument"]["security_id"])
    product = str(config["instrument"]["product_type"]).upper()
    for row in positions:
        if _position_security_id(row) != target:
            continue
        row_product = _position_product(row)
        if row_product and row_product not in {product, "INTRA" if product == "INTRADAY" else product}:
            if row_product != product and not ({row_product, product} <= {"INTRA", "INTRADAY"}):
                continue
        if _position_net_qty(row) != 0:
            return True, row
    return True, None


def get_open_position(dhan, config: dict) -> tuple[bool, Optional[dict]]:
    return get_current_position(dhan, config)


def broker_side_from_row(row: Optional[dict]) -> tuple[str, int, float]:
    if row is None:
        return "FLAT", 0, 0.0
    qty = _position_net_qty(row)
    side = _position_side(qty)
    return side, abs(qty), _position_avg_price(row, side)


def apply_broker_position(state: BotState, config: dict, row: Optional[dict]) -> None:
    """Overwrite local position fields from the broker. Does not place orders."""
    side, quantity, avg_price = broker_side_from_row(row)
    was_flat = state.current_position == "FLAT"
    state.current_position = side
    state.position_quantity = quantity
    state.trade_direction = None if side == "FLAT" else side
    if side == "FLAT":
        _mark_flat(state)
        return
    if was_flat or state.position_opened_at is None:
        state.position_opened_at = now_in_session_tz(config)
    if avg_price > 0:
        state.entry_price = avg_price
        arm_risk_levels(state, config, avg_price, side)
    state.engine_state = "POSITION_OPEN"


def log_existing_positions(dhan, config: dict) -> tuple[Optional[dict], list[dict]]:
    """Log the full position book and return our instrument row plus other opens."""
    positions = get_positions(dhan, config)
    if positions is None:
        logging.error("Could not read positions at startup. Continuing without a snapshot.")
        return None, []
    if not positions:
        logging.info("No positions returned (flat or empty book).")
        return None, []
    ours = None
    others: list[dict] = []
    target = str(config["instrument"]["security_id"])
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


def calculate_pnl(
    side: str,
    quantity: int,
    entry_price: Optional[float],
    ltp: Optional[float],
) -> tuple[float, float]:
    """
    Direction-aware unrealized (or just-closed) gross P&L.

    LONG:  (exit/current - entry) * quantity
    SHORT: (entry - exit/current) * quantity
    """
    if side == "FLAT" or not quantity or not entry_price or not ltp or entry_price <= 0:
        return 0.0, 0.0
    if side == "LONG":
        pnl = (ltp - entry_price) * quantity
    else:
        pnl = (entry_price - ltp) * quantity
    percent = (pnl / (entry_price * quantity)) * 100.0
    return pnl, percent


def estimated_net_pnl(config: dict, gross: float) -> tuple[float, bool]:
    cost = float(config.get("risk", {}).get("estimated_cost_per_trade") or 0)
    if cost <= 0:
        return gross, False
    return gross - cost, True


def monitor_position(
    dhan,
    config: dict,
    state: BotState,
    ltp: Optional[float],
) -> dict[str, Any]:
    """Refresh LTP-derived P&L for the open position."""
    if ltp and ltp > 0:
        state.last_ltp = ltp
    current = state.last_ltp
    if state.current_position != "FLAT" and current:
        if state.highest_price is None or current > state.highest_price:
            state.highest_price = current
        if state.lowest_price is None or current < state.lowest_price:
            state.lowest_price = current
        pnl, percent = calculate_pnl(
            state.current_position,
            state.position_quantity,
            state.entry_price,
            current,
        )
        state.last_pnl = pnl
        state.last_pnl_percent = percent
    elif state.current_position == "FLAT":
        state.last_pnl = 0.0
        state.last_pnl_percent = 0.0
    return {
        "side": state.current_position,
        "quantity": state.position_quantity,
        "entry": state.entry_price,
        "ltp": current,
        "pnl": state.last_pnl,
    }


# ============================================================
# LTP
# ============================================================

def _extract_ltp(ticker_response: Any, security_id: str) -> Optional[float]:
    data = _unwrap_dhan_data(ticker_response)
    if data is None:
        return None
    if isinstance(data, dict):
        if str(data.get("securityId") or data.get("security_id") or "") == str(security_id):
            last = data.get("LTP") or data.get("ltp") or data.get("last_price")
            if last:
                return _safe_float(last, 0.0) or None
        for _key, value in data.items():
            if isinstance(value, dict):
                last = value.get("LTP") or value.get("ltp") or value.get("last_price")
                sid = str(value.get("securityId") or value.get("security_id") or _key)
                if last and (sid == str(security_id) or _key == str(security_id)):
                    return _safe_float(last, 0.0) or None
            if isinstance(value, list):
                for item in value:
                    if not isinstance(item, dict):
                        continue
                    sid = str(item.get("securityId") or item.get("security_id") or "")
                    last = item.get("LTP") or item.get("ltp") or item.get("last_price")
                    if last and (not sid or sid == str(security_id)):
                        return _safe_float(last, 0.0) or None
    if isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            sid = str(item.get("securityId") or item.get("security_id") or "")
            last = item.get("LTP") or item.get("ltp") or item.get("last_price")
            if last and (not sid or sid == str(security_id)):
                return _safe_float(last, 0.0) or None
    return None


def get_ltp(dhan, security_id: str, exchange_segment: str) -> Optional[float]:
    """
    Fetch last traded price. Quote APIs are rate-limited to about 1 request/sec.

    Returns the last good LTP when a transient read fails so TP/SL is not
    blindly skipped on a single blip.
    """
    global _last_good_ltp, _last_quote_monotonic
    elapsed = time.monotonic() - _last_quote_monotonic
    if elapsed < QUOTE_MIN_INTERVAL_SECONDS:
        time.sleep(QUOTE_MIN_INTERVAL_SECONDS - elapsed)
    segment = _map_exchange_segment(exchange_segment)
    try:
        response = dhan.ticker_data(
            {segment: [int(security_id) if str(security_id).isdigit() else security_id]}
        )
    except Exception:
        try:
            response = dhan.ticker_data({segment: [str(security_id)]})
        except Exception as exc:
            logging.warning("LTP fetch failed: %s", exc)
            return _last_good_ltp
    _last_quote_monotonic = time.monotonic()
    if not _dhan_ok(response):
        logging.warning("LTP fetch rejected: %s", _dhan_error_text(response))
        return _last_good_ltp
    price = _extract_ltp(response, security_id)
    if price and price > 0:
        _last_good_ltp = price
        return price
    return _last_good_ltp


def get_current_price(dhan, config: dict) -> Optional[float]:
    """Spec-named wrapper around get_ltp()."""
    return get_ltp(
        dhan,
        str(config["instrument"]["security_id"]),
        str(config["instrument"]["exchange_segment"]),
    )


# ============================================================
# RISK — TP / SL
# ============================================================

def _distance(entry_price: float, value: float, level_type: str) -> float:
    if level_type == "POINTS":
        return value
    return entry_price * (value / 100.0)


def calculate_stop_loss(entry_price: float, direction: str, config: dict) -> Optional[float]:
    """
    Calculate the stop-loss price for the active position.

    Supports percentage-based and point-based stop-loss configurations.

    Args:
        entry_price: Filled entry price.
        direction: LONG or SHORT.
        config: Loaded strategy/risk configuration.

    Returns:
        Calculated stop-loss price, or None when SL is disabled.

    Raises:
        ValueError: If the SL configuration is invalid.
    """
    block = config["risk"]["stop_loss"]
    if not block.get("enabled"):
        return None
    if entry_price <= 0:
        raise ValueError("entry_price must be positive to calculate stop-loss")
    distance = _distance(entry_price, float(block["value"]), str(block["type"]))
    tick = float(config["instrument"]["tick_size"])
    if direction == "LONG":
        return round_to_tick(entry_price - distance, tick)
    if direction == "SHORT":
        return round_to_tick(entry_price + distance, tick)
    raise ValueError(f"Unknown direction {direction!r}")


def calculate_take_profit(entry_price: float, direction: str, config: dict) -> Optional[float]:
    """
    Calculate the take-profit price for the active position.

    Supports percentage-based and point-based take-profit configurations.

    Args:
        entry_price: Filled entry price.
        direction: LONG or SHORT.
        config: Loaded strategy/risk configuration.

    Returns:
        Calculated take-profit price, or None when TP is disabled.

    Raises:
        ValueError: If the TP configuration is invalid.
    """
    block = config["risk"]["take_profit"]
    if not block.get("enabled"):
        return None
    if entry_price <= 0:
        raise ValueError("entry_price must be positive to calculate take-profit")
    distance = _distance(entry_price, float(block["value"]), str(block["type"]))
    tick = float(config["instrument"]["tick_size"])
    if direction == "LONG":
        return round_to_tick(entry_price + distance, tick)
    if direction == "SHORT":
        return round_to_tick(entry_price - distance, tick)
    raise ValueError(f"Unknown direction {direction!r}")


def arm_risk_levels(state: BotState, config: dict, entry_price: float, side: str) -> None:
    """Attach TP/SL prices to state from the actual fill."""
    state.entry_price = entry_price
    try:
        state.stop_loss_price = calculate_stop_loss(entry_price, side, config)
        state.take_profit_price = calculate_take_profit(entry_price, side, config)
    except ValueError as exc:
        logging.error("Could not arm TP/SL: %s", exc)
        state.stop_loss_price = None
        state.take_profit_price = None


def should_trigger_tp(current_price: Optional[float], take_profit_price: Optional[float], side: str) -> bool:
    if current_price is None or take_profit_price is None or current_price <= 0:
        return False
    if side == "LONG":
        return current_price >= take_profit_price
    if side == "SHORT":
        return current_price <= take_profit_price
    return False


def should_trigger_sl(current_price: Optional[float], stop_loss_price: Optional[float], side: str) -> bool:
    if current_price is None or stop_loss_price is None or current_price <= 0:
        return False
    if side == "LONG":
        return current_price <= stop_loss_price
    if side == "SHORT":
        return current_price >= stop_loss_price
    return False


def check_take_profit(state: BotState, ltp: Optional[float]) -> bool:
    return should_trigger_tp(ltp, state.take_profit_price, state.current_position)


def check_stop_loss(state: BotState, ltp: Optional[float]) -> bool:
    return should_trigger_sl(ltp, state.stop_loss_price, state.current_position)


def resolve_limit_price(
    config: dict,
    transaction_type: str,
    ltp: Optional[float],
) -> Optional[float]:
    """Compute a LIMIT price. Never converts LIMIT into MARKET."""
    execution = config["execution"]
    tick = float(config["instrument"]["tick_size"])
    mode = execution["limit_price_mode"]
    side = transaction_type.upper()
    if mode == "ABSOLUTE":
        price = float(execution["limit_price"])
        if price <= 0:
            return None
        return round_to_tick(price, tick)
    if ltp is None or ltp <= 0:
        return None
    offset = float(execution["limit_offset_percent"]) / 100.0
    if side == "BUY":
        return round_to_tick(ltp * (1.0 + offset), tick)
    return round_to_tick(ltp * (1.0 - offset), tick)


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


def get_order_status(dhan, order_id: str, requested_quantity: int, config: Optional[dict] = None) -> dict:
    """Fetch current broker status. Read-only retries are allowed."""
    last_error = None
    attempts = _retry_attempts(config)
    delay = _retry_delay(config)
    for attempt in range(1, attempts + 1):
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
            attempts,
            last_error,
        )
        if attempt < attempts:
            time.sleep(delay)
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


def get_order_list(dhan, config: Optional[dict] = None) -> Optional[list[dict]]:
    last_error = None
    attempts = _retry_attempts(config)
    delay = _retry_delay(config)
    for attempt in range(1, attempts + 1):
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
            if attempt < attempts:
                time.sleep(delay)
    logging.warning("Order list read failed: %s", last_error)
    return None


def pending_orders_for_symbol(dhan, config: dict) -> list[dict]:
    orders = get_order_list(dhan, config)
    if orders is None:
        return []
    target = str(config["instrument"]["security_id"])
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
    """Count filled orders on this security for the session calendar date."""
    orders = get_order_list(dhan, config)
    if orders is None:
        return None
    target = str(config["instrument"]["security_id"])
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
    state.highest_price = None
    state.lowest_price = None
    state.position_opened_at = None
    state.last_pnl = 0.0
    state.last_pnl_percent = 0.0


def record_trade(state: BotState, pnl: float, reason: str) -> None:
    """Record a completed trade result in memory. No database is used."""
    state.daily_realized_pnl += pnl
    state.last_exit_reason = reason
    logging.info("TRADE RECORDED reason=%s realized_pnl=%.2f daily=%.2f", reason, pnl, state.daily_realized_pnl)


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
        record_trade(state, pnl, state.last_exit_reason or intent)
        _mark_flat(state)
        logging.info("POSITION CLOSED. Local state is FLAT. Realized P&L this exit ≈ %.2f", pnl)
        return
    position_side = "LONG" if side.upper() == "BUY" else "SHORT"
    state.current_position = position_side
    state.position_quantity = quantity
    state.trade_direction = position_side
    state.last_entry_signal = "BUY" if position_side == "LONG" else "SELL"
    state.engine_state = "POSITION_OPEN"
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
    instrument = config["instrument"]
    execution = config["execution"]
    return {
        "security_id": str(security_id or instrument["security_id"]).strip(),
        "exchange_segment": _map_exchange_segment(
            exchange_segment or instrument["exchange_segment"]
        ),
        "transaction_type": _map_transaction_type(transaction_type),
        "quantity": int(quantity),
        "order_type": _map_order_type(order_type),
        "product_type": _map_product_type(product_type or instrument["product_type"]),
        "price": float(price),
        "trigger_price": 0,
        "disclosed_quantity": 0,
        "after_market_order": False,
        "validity": _map_validity(execution.get("validity", "DAY")),
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
        f"DRY RUN would place {intent} {order_type} {transaction_type} qty={quantity} "
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

    Why this function exists:
        Duplicate-order bugs happen when every caller talks to the API
        directly. One function owns in-flight flags, LIMIT price math,
        notional warnings, and uncertain-response recovery.

    Returns:
        Order ID string, ``DRYRUN`` in dry-run mode, or None on failure.
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

    if is_dry_run(config):
        logging.info(
            "%s",
            describe_would_be_order(transaction_type, quantity, order_type, price, intent),
        )
        fill_price = ltp or price or state.entry_price or 0.0
        state.last_order_status = "FILLED"
        state.last_order_id = "DRYRUN"
        _apply_fill(state, config, intent, transaction_type, quantity, fill_price)
        push_event("ORDER", f"DRYRUN {intent} {transaction_type} {quantity} @ {fill_price:.2f}")
        return "DRYRUN"

    tag = f"M{uuid.uuid4().hex[:12]}"
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
    logging.info("ENTRY ORDER SUBMITTED" if intent == "ENTRY" else "EXIT ORDER SUBMITTED")
    logging.info(
        "Submitting %s %s: symbol=%s security_id=%s side=%s qty=%s price=%s tag=%s intent=%s",
        order_type,
        intent,
        config["instrument"]["symbol"],
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
            state.last_order_id = recovered
            state.last_order_status = "PENDING"
            return recovered
        logging.error(
            "Could not confirm whether Dhan accepted the order. "
            "Not submitting another order."
        )
        state.last_order_status = "UNKNOWN"
        record_error(state, "Uncertain place_order response")
        return None

    if not isinstance(response, dict):
        logging.error("Unexpected place-order response. Checking broker state.")
        recovered = find_order_id_after_uncertain_place(dhan, tag, request["security_id"])
        if recovered:
            state.pending_order_id = recovered
            state.last_order_id = recovered
            return recovered
        state.last_order_status = "UNKNOWN"
        return None

    if not _dhan_ok(response):
        logging.error("Dhan rejected the order: %s", _dhan_error_text(response))
        state.last_order_status = "REJECTED"
        record_error(state, _dhan_error_text(response))
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
            state.last_order_id = recovered
            return recovered
        state.last_order_status = "UNKNOWN"
        return None

    order_id = str(order_id)
    state.pending_order_id = order_id
    state.last_order_id = order_id
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
    """Poll one order until a terminal state, timeout, or stop signal."""
    if order_id == "DRYRUN":
        return {
            "status": "FILLED",
            "filled_quantity": requested_quantity,
            "fill_price": state.entry_price or state.last_ltp or 0.0,
            "raw_status": "DRYRUN",
        }

    poll_interval = float(config["execution"]["order_status_poll_seconds"])
    max_wait = float(config["execution"]["order_timeout_seconds"])
    started_at = time.time()
    last_status: Optional[dict] = None
    logging.info("Waiting for order %s to complete.", order_id)

    while True:
        if stop_requested() and state.pending_order_intent not in {"EXIT", "CLOSE_ALL"}:
            logging.info("Stop requested while waiting for order %s.", order_id)
            break
        try:
            last_status = get_order_status(dhan, order_id, requested_quantity, config)
        except Exception as exc:
            logging.error("Order status poll failed: %s", exc)
            if interruptible_sleep(poll_interval):
                break
            if time.time() - started_at >= max_wait:
                break
            continue
        state.last_order_status = last_status["status"]
        logging.info(
            "Order %s status=%s filled=%s",
            order_id,
            last_status["status"],
            last_status["filled_quantity"],
        )
        if last_status["status"] in TERMINAL_STATES:
            return last_status
        if time.time() - started_at >= max_wait:
            logging.warning("Order %s wait timed out after %s seconds.", order_id, max_wait)
            return last_status
        if interruptible_sleep(poll_interval):
            break
    return last_status


def confirm_position_after_fill(dhan, config: dict, state: BotState, intent: str, side: str) -> None:
    """Trust the broker position book over the order-fill payload when they differ."""
    if is_dry_run(config):
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
    if order_id == "DRYRUN":
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
    """If a previous order is still working, poll it and skip new signals."""
    if is_dry_run(config):
        return False
    if state.order_in_flight and not state.pending_order_id and state.pending_order_tag:
        recovered = find_order_id_after_uncertain_place(
            dhan,
            state.pending_order_tag,
            str(config["instrument"]["security_id"]),
        )
        if recovered:
            logging.info("Recovered in-flight order ID %s from tag %s.", recovered, state.pending_order_tag)
            state.pending_order_id = recovered
            state.last_order_id = recovered
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
            dhan, state.pending_order_id, state.pending_order_quantity or 1, config
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
        quantity=int(config["instrument"]["quantity"]),
        order_type=config["execution"]["order_type"],
        intent="ENTRY",
        ltp=ltp,
    )
    return finalize_submitted_order(
        dhan,
        config,
        state,
        order_id,
        transaction_type,
        int(config["instrument"]["quantity"]),
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
        order_type=config["execution"]["order_type"],
        intent="EXIT",
        ltp=ltp,
    )
    return finalize_submitted_order(dhan, config, state, order_id, side, qty, "EXIT")


def exit_position(
    dhan,
    config: dict,
    state: BotState,
    reason: str,
    ltp: Optional[float] = None,
) -> bool:
    """
    Close the open position for a named reason.

    Why this function exists:
        Every exit path (TP, SL, force-exit, manual, risk) must share
        one function so the CLI always shows the same reason codes.
    """
    logging.info("exit_position(reason=%s)", reason)
    state.last_exit_reason = reason
    state.engine_state = "EXIT_PENDING"
    return place_exit_order(dhan, config, state, ltp)


def cancel_pending_orders(dhan, config: dict, state: BotState) -> None:
    """Cancel working orders for the configured symbol when shutdown asks for it."""
    if not config["shutdown"].get("cancel_pending_orders"):
        return
    if is_dry_run(config) or dhan is None:
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

    Safety:
        Does not blindly close unrelated positions. Does not retry
        place_order on an uncertain submit; it retries the position read.
    """
    global _close_all_submitted
    logging.info("close_all_positions() starting.")
    state.close_all_attempted = True
    only_ours = bool(config["safety"].get("manage_only_configured_symbol", True))
    target = str(config["instrument"]["security_id"])

    if is_dry_run(config):
        if state.current_position != "FLAT":
            logging.info(
                "DRY RUN would close local %s qty=%s (no live order sent)",
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
        logging.info("close_all_positions() dry-run complete.")
        return True

    ltp = get_current_price(dhan, config)

    for _attempt in range(1, CLOSE_VERIFY_ATTEMPTS + 1):
        open_rows = get_open_positions(dhan, config)
        if open_rows is None:
            logging.error("Could not read positions while flattening. Will retry the read.")
            if interruptible_sleep(float(config["app"]["polling_seconds"])):
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
            product = _position_product(row) or config["instrument"]["product_type"]
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
                config["execution"]["order_type"],
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
                order_type=config["execution"]["order_type"],
                intent="CLOSE_ALL",
                product_type=product,
                security_id=security_id,
                exchange_segment=exchange or None,
                ltp=ltp,
            )
            if order_id or state.order_in_flight:
                _close_all_submitted.add(key)
            finalize_submitted_order(dhan, config, state, order_id, side, quantity, "CLOSE_ALL")

        remaining = get_open_positions(dhan, config)
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
        if interruptible_sleep(float(config["app"]["polling_seconds"])):
            break

    leftover = get_open_positions(dhan, config)
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
    if is_dry_run(config):
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

    Safety:
        Never places a new entry because the process restarted.
    """
    logging.info("RECOVERY MODE")
    if is_dry_run(config):
        logging.info("Dry-run: broker positions are displayed but not adopted for simulated trading.")
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
    if not config["startup"].get("reconcile_existing_positions") or not config["startup"].get(
        "manage_existing_position"
    ):
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
    if side == "LONG":
        state.long_breakout_fired = True
    elif side == "SHORT":
        state.short_breakout_fired = True
    state.engine_state = "POSITION_OPEN"


# ============================================================
# RISK / TRADE VALIDATION
# ============================================================

def daily_risk_blocked(config: dict, state: BotState) -> Optional[str]:
    risk = config["risk"]
    max_loss = risk.get("max_daily_loss") or {}
    if max_loss.get("enabled") and float(max_loss.get("value") or 0) > 0:
        if state.daily_realized_pnl <= -float(max_loss["value"]):
            return "RISK_LIMIT_REACHED"
    max_trades = int(risk.get("max_trades_per_day") or 0)
    if max_trades > 0 and state.trades_today >= max_trades:
        return "MAX_TRADES_REACHED"
    return None


def check_risk_conditions(config: dict, state: BotState) -> Optional[str]:
    """Pure daily-risk check used by validate_trade and the loop."""
    return daily_risk_blocked(config, state)


def check_risk_limits(config: dict, state: BotState) -> Optional[str]:
    return check_risk_conditions(config, state)


def check_entry_conditions(config: dict, state: BotState, signal: str) -> tuple[bool, str]:
    """
    Verify that an ORB BUY/SELL signal is allowed to become an entry.

    Why this function exists:
        Session, direction flags, open position, pending orders, daily
        limits, freeze state, and stop requests must all be able to veto
        a signal without the signal function knowing about Dhan.
    """
    if stop_requested():
        return False, "STOP_REQUESTED"
    if signal not in {"BUY", "SELL"}:
        return False, state.why_no_trade or "SCANNING"
    if not config["strategy"].get("enabled", True):
        return False, "BOT_DISABLED"
    if not state.opening_range_complete:
        return False, "ORB_INCOMPLETE"
    allowed, window_reason = check_trading_window(config)
    if not allowed:
        return False, window_reason
    if config["safety"].get("require_market_hours") and not is_market_expected_open(config):
        return False, "WEEKEND" if is_weekend(config) else "SESSION_NOT_STARTED"
    if state.order_in_flight or state.pending_order_id:
        return False, "PENDING_ORDER_EXISTS"
    if config["safety"].get("prevent_duplicate_orders", True):
        if state.current_position != "FLAT":
            return False, "POSITION_ALREADY_OPEN"
    if state.extra.get("unmanaged_existing") or state.extra.get("unexpected_other_position"):
        return False, "BLOCKED_UNEXPECTED_POSITION"
    if state.current_position != "FLAT":
        return False, "POSITION_ALREADY_OPEN"
    if config["safety"].get("require_flat_before_entry") and state.current_position != "FLAT":
        return False, "POSITION_ALREADY_OPEN"
    if signal == "BUY" and not config["strategy"]["direction"]["allow_long"]:
        return False, "LONG_DISABLED"
    if signal == "SELL" and not config["strategy"]["direction"]["allow_short"]:
        return False, "SHORT_DISABLED"
    blocked = check_risk_conditions(config, state)
    if blocked:
        return False, blocked
    quantity = int(config["instrument"]["quantity"])
    if quantity <= 0:
        return False, "CONFIGURATION_ERROR"
    return True, "NONE"


def validate_trade(config: dict, state: BotState, signal: str) -> tuple[bool, str]:
    return check_entry_conditions(config, state, signal)


def compute_next_action(config: dict, state: BotState) -> None:
    """Set the human-readable NEXT ACTION and WHY-NO-TRADE fields."""
    if stop_requested() or state.engine_state in {"STOPPING", "BOT_STOPPED", "STOPPED"}:
        state.next_action = "STOPPING"
        state.why_no_trade = "STOP_REQUESTED"
        return
    if state.engine_state == "ERROR":
        state.next_action = "ERROR — SEE EVENT STREAM"
        state.why_no_trade = "API_UNAVAILABLE"
        return
    allowed, window_reason = check_trading_window(config)
    if not allowed and window_reason == "WEEKEND":
        state.engine_state = "WAITING"
        state.next_action = "WEEKEND — MARKET CLOSED"
        state.why_no_trade = "WEEKEND"
        return
    if not allowed and window_reason == "SESSION_NOT_STARTED":
        state.engine_state = "WAITING"
        state.next_action = "WAITING FOR MARKET SESSION"
        state.why_no_trade = "SESSION_NOT_STARTED"
        return
    if not allowed and window_reason == "SESSION_ENDED":
        state.next_action = "FORCE EXIT"
        state.why_no_trade = "SESSION_ENDED"
        return
    if not allowed and window_reason == "ENTRY_CUTOFF":
        if state.current_position == "FLAT":
            state.next_action = "ENTRY DISABLED"
            state.why_no_trade = "ENTRY_CUTOFF"
            return
    if state.order_in_flight or state.pending_order_id:
        state.next_action = "ORDER IN FLIGHT — WAITING FOR FILL"
        state.why_no_trade = "PENDING_ORDER_EXISTS"
        return
    if state.current_position != "FLAT":
        state.engine_state = "POSITION_OPEN"
        state.next_action = "MONITOR"
        state.why_no_trade = "MONITORING_TP_SL"
        return
    if not state.opening_range_complete:
        if state.engine_state == "BUILDING_ORB":
            state.next_action = "BUILDING OPENING RANGE"
            state.why_no_trade = "BUILDING_OPENING_RANGE"
            return
        state.next_action = "WAITING FOR OPENING RANGE"
        return
    blocked = check_risk_conditions(config, state)
    if blocked == "MAX_TRADES_REACHED":
        state.next_action = "NEW ENTRIES DISABLED"
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
        "ENTRY_CUTOFF",
        "WEEKEND",
        "BOT_DISABLED",
        "BUILDING_OPENING_RANGE",
        "ORB_INCOMPLETE",
        "LONG_ALREADY_FIRED",
        "SHORT_ALREADY_FIRED",
        "WAITING_FOR_CONFIRMATION",
    }
    if state.why_no_trade in blocking:
        state.next_action = WHY_NO_TRADE_LABELS.get(
            state.why_no_trade, state.why_no_trade
        ).upper()
        return
    state.next_action = "SCANNING FOR BREAKOUT"
    state.why_no_trade = "SCANNING"


def monitor_tpsl(dhan, config: dict, state: BotState, ltp: Optional[float]) -> Optional[str]:
    """
    Check live LTP against armed TP/SL.

    Returns:
        TAKE_PROFIT or STOP_LOSS when a level is reached.

    SL is evaluated first so a gap through both levels prefers capital
    protection. Software polling can overshoot the exact price.
    """
    if state.current_position == "FLAT":
        return None
    if ltp is None or ltp <= 0:
        logging.warning("No valid LTP available for TP/SL. Waiting.")
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

    if check_stop_loss(state, ltp):
        return "STOP_LOSS"
    if check_take_profit(state, ltp):
        return "TAKE_PROFIT"
    return None


# ============================================================
# SCI-FI CLI
# ============================================================

def render_startup_banner(config: dict) -> None:
    """Print the spec-required futuristic startup banner and checklist."""
    CONSOLE.print(
        Panel(
            Text(
                "DHAN // ORB TRADING ENGINE\n\nOPENING RANGE BREAKOUT CORE",
                justify="center",
                style="bold cyan",
            ),
            border_style="cyan",
            padding=(1, 4),
        )
    )
    if is_dry_run(config):
        CONSOLE.print("[bold yellow]MODE: PAPER / DRY RUN — NO REAL ORDERS[/bold yellow]")
        CONSOLE.print("[bold yellow]DRY RUN[/bold yellow]")
    else:
        CONSOLE.print("[bold red]MODE: LIVE TRADING[/bold red]")

    instrument = config["instrument"]
    strategy = config["strategy"]
    hours = config["trading_hours"]
    risk = config["risk"]
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="bold cyan", min_width=16)
    grid.add_column(style="white")
    grid.add_row("BOT", str(config["app"].get("name") or "Dhan ORB Algo"))
    grid.add_row("ENVIRONMENT", str(config["app"].get("environment") or "paper").upper())
    grid.add_row("MODE", "DRY RUN" if is_dry_run(config) else "LIVE")
    grid.add_row("SYMBOL", str(instrument.get("symbol")))
    grid.add_row("SECURITY ID", str(instrument.get("security_id")))
    grid.add_row(
        "ORB WINDOW",
        f"{strategy['opening_range']['start_time']} → {strategy['opening_range']['end_time']}",
    )
    grid.add_row(
        "BUFFER",
        f"{strategy['breakout']['buffer_points']} pts / {strategy['breakout']['buffer_percent']}%",
    )
    grid.add_row("CONFIRM", str(strategy["breakout"]["confirmation_candles"]))
    grid.add_row("LONG", "on" if strategy["direction"]["allow_long"] else "off")
    grid.add_row("SHORT", "on" if strategy["direction"]["allow_short"] else "off")
    sl = risk["stop_loss"]
    tp = risk["take_profit"]
    grid.add_row("SL", f"{sl['value']} {sl['type']}" if sl["enabled"] else "off")
    grid.add_row("TP", f"{tp['value']} {tp['type']}" if tp["enabled"] else "off")
    grid.add_row("POLLING", f"{config['app']['polling_seconds']} SEC")
    grid.add_row(
        "SESSION",
        f"{hours.get('start_time')} → {hours.get('stop_entry_time')} / {hours.get('close_positions_time')}",
    )
    CONSOLE.print(Panel(grid, title="[bold cyan]CONFIGURATION[/bold cyan]", border_style="cyan"))
    if is_live_mode(config):
        CONSOLE.print(
            Panel(
                "[bold red]LIVE TRADING ENABLED\nREAL ORDERS MAY BE PLACED\n"
                "REAL MONEY MAY BE AT RISK[/bold red]",
                border_style="red",
            )
        )
        logging.info("LIVE TRADING ENABLED. REAL ORDERS MAY BE PLACED.")
    else:
        logging.info("DRY RUN. Real market data will be fetched. No live orders will be sent.")


def render_exit_banner(
    config: dict,
    state: BotState,
    reason: str,
    entry: Optional[float],
    exit_price: Optional[float],
    quantity: int,
    pnl: float,
) -> None:
    """Boxed TP/SL (or other) exit summary. Bot is then stopped."""
    titles = {
        "TAKE_PROFIT": "TAKE PROFIT ACTIVATED",
        "STOP_LOSS": "STOP LOSS ACTIVATED",
        "TRADING_DAY_END": "FORCE EXIT",
        "MANUAL_STOP": "MANUAL STOP",
        "RISK_LIMIT": "RISK LIMIT",
    }
    title = titles.get(reason, reason.replace("_", " "))
    display_pnl, estimated = estimated_net_pnl(config, pnl)
    pnl_text = f"{display_pnl:+,.2f}"
    if estimated:
        pnl_text += " (estimate after configured cost)"
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="bold")
    grid.add_column()
    grid.add_row("Entry", format_inr(entry))
    grid.add_row("Exit", format_inr(exit_price))
    grid.add_row("Qty", str(quantity))
    grid.add_row("P&L", f"₹{pnl_text}")
    grid.add_row("Reason", reason)
    grid.add_row("BOT", "STOPPED")
    CONSOLE.print(Panel(grid, title=f"[bold]{title}[/bold]", border_style="yellow"))


def render_dashboard(config: dict, state: BotState) -> Panel:
    """Build the sci-fi command-center panel from in-memory state."""
    now = now_in_session_tz(config)
    instrument = config["instrument"]
    strategy = config["strategy"]
    cli = config["cli"]
    mode = "PAPER / DRY RUN" if is_dry_run(config) else "LIVE"
    day_mode = "DAY TRADE" if config["trading_hours"].get("day_trading_enabled") else "CONTINUOUS"
    market = "OPEN" if is_market_expected_open(config, now) else "CLOSED"
    status = "ONLINE" if state.bot_running else "STOPPING"
    pnl_style = "green" if state.last_pnl > 0 else "red" if state.last_pnl < 0 else "white"
    display_pnl, estimated = estimated_net_pnl(config, state.last_pnl)
    pnl_text = format_inr(display_pnl)
    if display_pnl > 0:
        pnl_text = "+" + pnl_text
    if estimated:
        pnl_text += " est."
    why = WHY_NO_TRADE_LABELS.get(state.why_no_trade, state.why_no_trade)
    poll_in = "—"
    if state.next_poll_at:
        remaining = (state.next_poll_at - now).total_seconds()
        poll_in = f"{max(0, int(remaining))}s"

    system = Table.grid(padding=(0, 2))
    system.add_column(min_width=14, style="bold dim")
    system.add_column(min_width=22)
    system.add_column(min_width=14, style="bold dim")
    system.add_column(min_width=22)
    system.add_row("STATUS", status, "MODE", f"{mode} / {day_mode}")
    system.add_row("MARKET", market, "ENGINE", state.engine_state)
    system.add_row("POLL", f"{config['app']['polling_seconds']}s", "STRATEGY", "OPENING RANGE BREAKOUT")
    system.add_row("API", state.api_status, "STOP FILE", "YES" if STOP_FILE.exists() else "NO")

    market_tbl = Table.grid(padding=(0, 2))
    market_tbl.add_column(min_width=14, style="bold dim")
    market_tbl.add_column(min_width=22)
    market_tbl.add_column(min_width=14, style="bold dim")
    market_tbl.add_column(min_width=22)
    market_tbl.add_row("SYMBOL", str(instrument["symbol"]), "PRICE", format_inr(state.last_ltp))
    if cli.get("show_indicators", True):
        market_tbl.add_row(
            "ORB HIGH",
            format_inr(state.opening_range_high),
            "ORB LOW",
            format_inr(state.opening_range_low),
        )
        market_tbl.add_row(
            "LONG LVL",
            format_inr(state.long_breakout_level),
            "SHORT LVL",
            format_inr(state.short_breakout_level),
        )
        market_tbl.add_row(
            "ORB STATE",
            "FROZEN" if state.opening_range_complete else "FORMING",
            "CONFIRM",
            state.confirmation_status,
        )

    sections = [
        Text("SYSTEM", style="bold magenta"),
        system,
        Text(""),
        Text("MARKET DATA", style="bold magenta"),
        market_tbl,
    ]

    if cli.get("show_signal", True):
        strat = Table.grid(padding=(0, 2))
        strat.add_column(min_width=14, style="bold dim")
        strat.add_column(min_width=50)
        strat.add_row("LAST SIGNAL", state.last_signal)
        strat.add_row("CONDITION", state.strategy_condition)
        strat.add_row("NEXT ACTION", Text(state.next_action, style="bold yellow"))
        strat.add_row("WHY NO TRADE", why)
        sections.extend([Text(""), Text("SIGNAL", style="bold magenta"), strat])

    position = Table.grid(padding=(0, 2))
    position.add_column(min_width=14, style="bold dim")
    position.add_column(min_width=22)
    position.add_column(min_width=14, style="bold dim")
    position.add_column(min_width=22)
    position.add_row("POSITION", state.current_position, "QTY", str(state.position_quantity))
    position.add_row("ENTRY", format_inr(state.entry_price), "CURRENT", format_inr(state.last_ltp))
    position.add_row("SL", format_inr(state.stop_loss_price), "TP", format_inr(state.take_profit_price))
    position.add_row("P&L", Text(pnl_text, style=pnl_style), "DAILY P&L", format_inr(state.daily_realized_pnl))
    sections.extend([Text(""), Text("POSITION", style="bold magenta"), position])

    if cli.get("show_orders", True):
        trading_tbl = Table.grid(padding=(0, 2))
        trading_tbl.add_column(min_width=14, style="bold dim")
        trading_tbl.add_column(min_width=22)
        trading_tbl.add_column(min_width=14, style="bold dim")
        trading_tbl.add_column(min_width=22)
        last_trade = state.last_trade_time.strftime("%H:%M:%S") if state.last_trade_time else "—"
        trading_tbl.add_row("LAST TRADE", last_trade, "LAST ORDER", str(state.last_order_id or "—"))
        trading_tbl.add_row("ORDER STATUS", state.last_order_status, "EXIT REASON", state.last_exit_reason)
        trading_tbl.add_row("TRADES TODAY", str(state.trades_today), "LAST ERROR", state.last_error)
        trading_tbl.add_row(
            "LAST UPDATE",
            now.strftime("%H:%M:%S"),
            "NEXT POLL",
            poll_in,
        )
        sections.extend([Text(""), Text("ORDERS / RISK", style="bold magenta"), trading_tbl])

    runtime_tbl = Table.grid(padding=(0, 2))
    runtime_tbl.add_column(min_width=14, style="bold dim")
    runtime_tbl.add_column(min_width=22)
    runtime_tbl.add_column(min_width=14, style="bold dim")
    runtime_tbl.add_column(min_width=22)
    runtime_tbl.add_row("RUNTIME", format_runtime(state.started_at, now), "CLI REFRESH", f"{cli['refresh_seconds']}s")
    runtime_tbl.add_row(
        "WINDOW",
        f"{strategy['opening_range']['start_time']}-{strategy['opening_range']['end_time']}",
        "STOP",
        "YES" if stop_requested() else "NO",
    )
    sections.extend([Text(""), Text("RUNTIME", style="bold magenta"), runtime_tbl])

    events = Table.grid()
    events.add_column(overflow="fold")
    if _event_history:
        for line in list(_event_history)[-int(cli["event_history_size"])]:
            events.add_row(Text(line, style="dim"))
    else:
        events.add_row(Text("waiting for events…", style="dim"))
    sections.extend([Text(""), Text("EVENT STREAM", style="bold magenta"), events])

    return Panel(
        Group(*sections),
        title="[bold cyan]◈ DHAN // ORB TRADING ENGINE ◈[/bold cyan]",
        subtitle=f"[dim]{now.strftime('%Y-%m-%d %H:%M:%S %Z')}[/dim]",
        border_style="cyan",
        padding=(0, 1),
    )


def dashboard_enabled(config: dict) -> bool:
    return bool(config.get("cli", {}).get("enabled", True)) and sys.stdout.isatty()


# ============================================================
# TRADING LOOP
# ============================================================

def detect_breakout_signal(
    state: BotState,
    candles: list[Candle],
    ltp: Optional[float],
    config: dict,
) -> str:
    """
    Return BUY, SELL, or HOLD.

    Same-poll both-sides (data glitch): LONG wins when allow_long is true,
    otherwise SHORT. A fired side is locked for the rest of the day.
    """
    long_hit = check_long_breakout(state, candles, ltp, config)
    short_hit = check_short_breakout(state, candles, ltp, config)
    if long_hit and short_hit:
        if config["strategy"]["direction"]["allow_long"]:
            return "BUY"
        return "SELL"
    if long_hit:
        return "BUY"
    if short_hit:
        return "SELL"
    return "HOLD"


def process_breakout(
    dhan,
    config: dict,
    state: BotState,
    candles: list[Candle],
    ltp: Optional[float],
    allow_entries: bool,
) -> None:
    """Evaluate breakout events after the opening range is frozen."""
    if not state.opening_range_complete:
        compute_next_action(config, state)
        return
    if candles:
        state.last_candle_time = candles[-1].timestamp

    signal = detect_breakout_signal(state, candles, ltp, config)
    if signal == "HOLD":
        if state.confirmation_status and state.confirmation_status != "—":
            state.why_no_trade = "WAITING_FOR_CONFIRMATION"
            state.next_action = "WAITING FOR CONFIRMATION"
        else:
            state.last_signal = "HOLD"
            state.why_no_trade = "NO_BREAKOUT"
        compute_next_action(config, state)
        return

    state.last_signal = "LONG BREAKOUT" if signal == "BUY" else "SHORT BREAKOUT"
    if signal == "BUY":
        state.long_breakout_fired = True
    else:
        state.short_breakout_fired = True
    if candles:
        completed = _completed_after_orb(candles, config, now_in_session_tz(config))
        if completed:
            state.last_confirm_candle = completed[-1].timestamp

    logging.info("SIGNAL DETECTED: %s", state.last_signal)
    push_event("SIGNAL", state.last_signal)

    if not allow_entries:
        compute_next_action(config, state)
        return
    if state.current_position != "FLAT":
        compute_next_action(config, state)
        return

    allowed, reason = check_entry_conditions(config, state, signal)
    if not allowed:
        logging.info("Trade blocked: %s", WHY_NO_TRADE_LABELS.get(reason, reason))
        state.why_no_trade = reason
        compute_next_action(config, state)
        return
    logging.info("RISK CHECK PASSED")
    if is_live_mode(config):
        logging.info(
            "LIVE pre-trade chain: config → session → ORB freeze → position → "
            "pending → risk → signal → safety → order → verify"
        )
    state.next_action = f"{signal} SIGNAL — EXECUTING"
    if place_entry_order(dhan, config, state, signal, ltp):
        state.why_no_trade = "ENTRY_EXECUTED"
        state.engine_state = "POSITION_OPEN"
        push_event(
            "POSITION",
            f"{state.current_position} {state.position_quantity} @ {state.entry_price}",
        )
    else:
        logging.error("Entry was not confirmed. Not retrying blindly.")
        record_error(state, "Entry was not confirmed")
        state.engine_state = "NO_POSITION"
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
    interval = float(config["app"]["polling_seconds"])
    state.next_poll_at = now + timedelta(seconds=interval)

    announce_manual_stop_if_needed()
    if stop_requested():
        return cached_candles, "MANUAL_STOP"
    if check_force_exit(config, now):
        return cached_candles, "TRADING_DAY_END"

    window_ok, window_reason = check_trading_window(config, now)
    allow_entries = window_ok
    if not allow_entries:
        compute_next_action(config, state)

    if sync_pending_order(dhan, config, state):
        compute_next_action(config, state)
        return cached_candles, None

    reconcile_every = int(config["execution"]["reconcile_every_cycles"])
    if state.loop_cycle == 1 or state.loop_cycle % reconcile_every == 0:
        reconcile_state(dhan, config, state)

    ltp = get_current_price(dhan, config)
    if ltp:
        state.last_ltp = ltp
        state.api_status = "CONNECTED"
    monitor_position(dhan, config, state, ltp)

    if state.current_position != "FLAT":
        hit = monitor_tpsl(dhan, config, state, ltp)
        if hit:
            logging.info("%s HIT", hit.replace("_", " "))
            push_event("EXIT", hit)
            entry = state.entry_price
            qty = state.position_quantity
            side = state.current_position
            trade_pnl, _pct = calculate_pnl(side, qty, entry, ltp)
            state.last_exit_reason = hit
            if config["shutdown"].get("close_positions_on_tp_sl"):
                exit_position(dhan, config, state, hit, ltp)
                cancel_pending_orders(dhan, config, state)
            render_exit_banner(
                config,
                state,
                hit,
                entry,
                state.last_trade_price or ltp,
                qty,
                trade_pnl,
            )
            state.engine_state = "TRADE_COMPLETED"
            return cached_candles, hit

    if state.current_position == "FLAT":
        blocked = check_risk_conditions(config, state)
        if blocked:
            state.why_no_trade = blocked
            compute_next_action(config, state)
            if blocked == "RISK_LIMIT_REACHED" and config["risk"].get("close_on_risk_limit"):
                return cached_candles, "RISK_LIMIT"
            return cached_candles, None

    candles = get_market_data(dhan, config)
    state.last_market_data_at = now_in_session_tz(config)
    if not candles:
        logging.warning("No usable candles this cycle. Waiting.")
        state.why_no_trade = "WAITING_FOR_MARKET_DATA"
        state.api_status = "DEGRADED"
        if cached_candles:
            candles = cached_candles
        else:
            compute_next_action(config, state)
            return cached_candles, None

    cached_candles = candles
    update_runtime_state(state, config, cached_candles, ltp, now)
    if allow_entries or state.opening_range_complete:
        process_breakout(dhan, config, state, cached_candles, ltp, allow_entries)
    else:
        compute_next_action(config, state)
    return cached_candles, None


def run_trading_loop(dhan, config: dict, state: BotState) -> None:
    """
    Poll market data, signals, positions, and TP/SL until a shutdown reason.

    CLI refresh and API polling are independent: the dashboard may redraw
    every second from memory while Dhan is contacted only on the trading
    interval.
    """
    interval = float(config["app"]["polling_seconds"])
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
                    announce_manual_stop_if_needed()
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
                announce_manual_stop_if_needed()
                break

    if stop_requested() and not state.shutdown_reason:
        announce_manual_stop_if_needed()
        state.shutdown_reason = "MANUAL_STOP"


def safe_shutdown(dhan, config: dict, state: BotState, reason: str) -> None:
    """
    Stop entries, optionally flatten, verify, log, and exit the loop.

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
    if reason in {"TRADING_DAY_END", "SESSION_END"}:
        close_positions = bool(config["shutdown"].get("close_positions_on_session_end"))
    elif reason in {"TAKE_PROFIT", "STOP_LOSS"}:
        close_positions = bool(config["shutdown"].get("close_positions_on_tp_sl")) and (
            state.current_position != "FLAT"
        )
    elif reason in {"MANUAL_STOP", "SIGINT", "SIGTERM"}:
        close_positions = bool(config["shutdown"].get("close_positions_on_manual_stop"))
        logging.info(
            "Manual stop: close_positions_on_stop=%s",
            close_positions,
        )
    elif reason == "RISK_LIMIT":
        close_positions = bool(config["risk"].get("close_on_risk_limit"))
    elif reason == "ERROR":
        close_positions = bool(config["shutdown"].get("close_positions_on_error"))

    if close_positions and dhan is not None:
        if reason == "TRADING_DAY_END" and state.current_position != "FLAT":
            exit_position(dhan, config, state, "TRADING_DAY_END", state.last_ltp)
        close_all_positions(dhan, config, state)
    elif state.current_position != "FLAT":
        logging.info(
            "Positions were left open by configuration. Local side=%s qty=%s",
            state.current_position,
            state.position_quantity,
        )
        CONSOLE.print(
            f"[yellow]Open position left untouched: {state.current_position} "
            f"qty={state.position_quantity}[/yellow]"
        )

    if dhan is not None:
        cancel_pending_orders(dhan, config, state)

    if dhan is not None and not is_dry_run(config):
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
            state.engine_state = "TRADE_COMPLETED"

    display_pnl, estimated = estimated_net_pnl(config, state.daily_realized_pnl)
    label = "estimated net" if estimated else "gross"
    logging.info("Final daily %s P&L: %.2f", label, display_pnl)
    CONSOLE.print(f"Final daily {label} P&L: {format_inr(display_pnl)}")

    state.engine_state = "BOT_STOPPED"
    logging.info("STOP_REASON = %s", state.shutdown_reason)
    logging.info("BOT STOPPED")


def graceful_shutdown(dhan, config: dict, state: BotState, reason: str) -> None:
    safe_shutdown(dhan, config, state, reason)


# ============================================================
# MAIN
# ============================================================

def _print_checklist(ok: bool, label: str) -> None:
    mark = "[OK]" if ok else "[FAIL]"
    style = "green" if ok else "red"
    CONSOLE.print(f"[{style}]{mark} {label}[/{style}]")
    if ok:
        logging.info("%s %s", mark, label)
    else:
        logging.error("%s %s", mark, label)


def main(argv: Optional[list[str]] = None) -> int:
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
        args = parse_cli_args(argv)
        config_path = Path(args.config).expanduser()
        if not config_path.is_absolute():
            config_path = (Path.cwd() / config_path).resolve()
        config = load_config(config_path)
        _print_checklist(True, "Configuration loaded")
        load_environment()
        _print_checklist(True, "Environment loaded")
        validate_config(config)
        validate_safety_config(config)
        setup_logging(config)
        _print_checklist(True, "Symbol validated")
        _print_checklist(True, "Trading session configured")
        _print_checklist(True, "Risk controls loaded")
        _print_checklist(True, "Dry-run mode enabled" if is_dry_run(config) else "Live trading unlocked")
        _print_checklist(True, "ORB strategy ready")
        logging.info("CONFIGURATION LOADED")
        logging.info("CONFIGURATION VALIDATED")
        logging.info("%s MODE", "DRY RUN" if is_dry_run(config) else "LIVE")

        consume_leftover_stop_file()
        if stop_requested():
            logging.info("Stop requested at startup. No orders were placed.")
            return 0

        state.started_at = now_in_session_tz(config)
        render_startup_banner(config)
        logging.info("BOT STARTED")

        dhan = initialize_dhan_client()
        state.api_status = "CONNECTED"
        _print_checklist(True, "Dhan client initialized")
        logging.info("DHAN CONNECTED")

        if config["startup"].get("reconcile_existing_positions"):
            recover_existing_state(dhan, config, state)

        if stop_requested():
            safe_shutdown(dhan, config, state, "MANUAL_STOP")
            return 0

        compute_next_action(config, state)
        run_trading_loop(dhan, config, state)

        reason = state.shutdown_reason or (
            "MANUAL_STOP" if stop_requested() else "TRADING_DAY_END"
        )
        safe_shutdown(dhan, config, state, reason)
        return 0

    except (ConfigError, SafetyError, CredentialError) as exc:
        _print_checklist(False, str(exc).splitlines()[0])
        logging.error("%s", exc)
        CONSOLE.print(f"[bold red]{exc}[/bold red]")
        return 1
    except KeyboardInterrupt:
        safe_shutdown(dhan, config, state, "SIGINT")
        return 0
    except Exception:
        logging.exception("Unexpected error. No additional order will be placed.")
        state.engine_state = "ERROR"
        try:
            if config and dhan is not None:
                safe_shutdown(dhan, config, state, "ERROR")
        except Exception:
            logging.exception("Shutdown after error also failed.")
        return 1


if __name__ == "__main__":
    sys.exit(main())

