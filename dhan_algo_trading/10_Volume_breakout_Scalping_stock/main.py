#!/usr/bin/env python3
"""Dhan Volume Breakout Scalper for NSE equity.

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

The primary signal is price breakout plus abnormal volume. After a verified
TP or SL the process stops only when the matching flag is true.
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
VALID_TP_SL_MODES = {"PERCENT", "PERCENTAGE", "POINTS", "ABSOLUTE"}
VALID_DHAN_INTERVALS = {"1", "5", "15", "25", "60", "DAY"}

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
    "NO_BREAKOUT": "Breakout not confirmed",
    "VOLUME_BELOW_THRESHOLD": "Volume below threshold",
    "BREAKOUT_TOO_SMALL": "Breakout distance is below the minimum",
    "BREAKOUT_TOO_LARGE": "Breakout distance is above the maximum",
    "CANDLE_BODY_TOO_SMALL": "Candle body is too small",
    "CANDLE_RANGE_TOO_WIDE": "Candle range is too wide",
    "TREND_FILTER": "EMA trend filter rejected the side",
    "SAME_CANDLE": "This candle already generated an entry",
    "SAME_BREAKOUT": "This breakout level was already consumed",
    "COOLDOWN": "Cooldown between trades is still active",
    "LONG_DISABLED": "Long entries are disabled in config",
    "SHORT_DISABLED": "Short entries are disabled in config",
    "POSITION_ALREADY_OPEN": "A position is already open",
    "MAX_TRADES_REACHED": "Maximum trades for today have been reached",
    "MAX_CONSECUTIVE_LOSSES": "Maximum consecutive losses have been reached",
    "DAILY_PROFIT_TARGET": "Daily profit target has been reached",
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
    "SCANNING": "Flat — scanning for a volume breakout",
    "MONITORING_TP_SL": "Position open — monitoring take-profit / stop-loss",
    "BLOCKED_UNEXPECTED_POSITION": "Unexpected broker position blocked new entries",
    "ENTRY_EXECUTED": "Entry executed — switching to monitoring",
    "EXIT_EXECUTED": "Exit executed",
    "WARMUP": "Not enough completed candles for the lookback",
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
class SignalResult:
    """Pure strategy output. No Dhan calls."""

    signal: str
    reason: str
    close: Optional[float] = None
    volume: Optional[float] = None
    average_volume: Optional[float] = None
    volume_ratio: Optional[float] = None
    breakout_high: Optional[float] = None
    breakout_low: Optional[float] = None
    breakout_percent: Optional[float] = None
    ema_fast: Optional[float] = None
    ema_slow: Optional[float] = None
    candle_time: Optional[datetime] = None
    body_percent: Optional[float] = None
    range_percent: Optional[float] = None


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
    trailing_stop_price: Optional[float] = None
    trailing_armed: bool = False
    highest_price: Optional[float] = None
    lowest_price: Optional[float] = None
    last_processed_candle: Optional[datetime] = None
    last_signal: str = "NONE"
    last_signal_candle: Optional[datetime] = None
    last_consumed_side: Optional[str] = None
    last_consumed_level: Optional[float] = None
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
    current_volume: Optional[float] = None
    current_avg_volume: Optional[float] = None
    current_volume_ratio: Optional[float] = None
    breakout_high: Optional[float] = None
    breakout_low: Optional[float] = None
    ema_fast: Optional[float] = None
    ema_slow: Optional[float] = None
    last_candle_time: Optional[datetime] = None
    last_ltp: Optional[float] = None
    last_pnl: float = 0.0
    last_pnl_percent: float = 0.0
    last_market_data_at: Optional[datetime] = None
    last_position_sync_at: Optional[datetime] = None
    last_trade_time: Optional[datetime] = None
    last_trade_price: Optional[float] = None
    last_exit_reason: str = "—"
    last_exit_time: Optional[datetime] = None
    trades_today: int = 0
    long_trades: int = 0
    short_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    consecutive_losses: int = 0
    gross_profit: float = 0.0
    gross_loss: float = 0.0
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
    parser = argparse.ArgumentParser(description="Dhan Volume Breakout Scalper")
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


def _require_mapping(parent: dict, name: str, field_name: str) -> dict:
    value = parent.get(name)
    if not isinstance(value, dict):
        raise ConfigError(f"ERROR: {field_name} must be a mapping.\nThe bot did not start.")
    return value


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


def _normalize_level_mode(raw: Any, field_name: str) -> str:
    text = str(raw or "PERCENTAGE").strip().upper()
    if text == "PERCENTAGE":
        text = "PERCENT"
    if text not in {"PERCENT", "POINTS", "ABSOLUTE"}:
        raise ConfigError(
            f"ERROR: {field_name} must be percentage, points, or absolute.\nThe bot did not start."
        )
    return text


def normalize_timeframe(raw: Any) -> str:
    """Map '5m' / '15' / '1D' style values onto Dhan interval codes."""
    text = str(raw or "").strip().upper().replace(" ", "")
    aliases = {
        "1M": "1",
        "1MIN": "1",
        "1MINUTE": "1",
        "5M": "5",
        "5MIN": "5",
        "5MINUTE": "5",
        "15M": "15",
        "15MIN": "15",
        "25M": "25",
        "25MIN": "25",
        "30M": "25",
        "60M": "60",
        "1H": "60",
        "HOUR": "60",
        "1D": "DAY",
        "D": "DAY",
        "DAILY": "DAY",
    }
    return aliases.get(text, text)


def interval_minutes(timeframe: str) -> Optional[int]:
    if timeframe == "DAY":
        return None
    return int(timeframe)


def validate_config(config: dict) -> None:
    """
    Fail fast if any required setting is missing or inconsistent.

    Why this function exists:
        A live Dhan account will accept orders that a bad config would send.
        Validation happens before authentication and always before the first order.

    Side effects:
        Mutates config in place with normalized types and convenience aliases
        (bot / trading_hours / shutdown / safety) so the broker layer can
        read one shape.
    """
    strategy = _require_section(config, "strategy")
    instrument = _require_section(config, "instrument")
    candles = _require_section(config, "candles")
    volume_breakout = _require_section(config, "volume_breakout")
    trend_filter = _require_section(config, "trend_filter")
    risk = _require_section(config, "risk")
    trading = _require_section(config, "trading")
    system = _require_section(config, "system")
    execution = _require_section(config, "execution")
    safety = _require_section(config, "safety")
    logging_cfg = _require_section(config, "logging")
    cli = _require_section(config, "cli")

    strategy["name"] = str(strategy.get("name") or "Volume Breakout Scalper").strip()
    strategy["enabled"] = _as_bool(strategy.get("enabled"), True)

    security_id = str(instrument.get("security_id") or "").strip()
    symbol = str(instrument.get("trading_symbol") or instrument.get("symbol") or "").strip()
    if not security_id:
        raise ConfigError("ERROR: instrument.security_id is required.\nThe bot did not start.")
    if not symbol:
        raise ConfigError("ERROR: instrument.trading_symbol is required.\nThe bot did not start.")
    instrument["security_id"] = security_id
    instrument["trading_symbol"] = symbol
    instrument["symbol"] = symbol
    exchange_segment = str(instrument.get("exchange_segment") or "").strip().upper()
    if not exchange_segment:
        raise ConfigError("ERROR: instrument.exchange_segment is required.\nThe bot did not start.")
    instrument["exchange_segment"] = exchange_segment
    instrument["instrument_type"] = str(instrument.get("instrument_type") or "EQUITY").strip().upper()
    instrument["tick_size"] = _as_positive_number(instrument.get("tick_size", 0.05), "instrument.tick_size")

    quantity = int(_as_positive_number(instrument.get("quantity"), "instrument.quantity"))
    if quantity != float(instrument.get("quantity")):
        raise ConfigError("ERROR: instrument.quantity must be a whole number.\nThe bot did not start.")
    instrument["quantity"] = quantity

    product_type = str(instrument.get("product_type") or "INTRADAY").strip().upper()
    if product_type not in VALID_PRODUCT_TYPES:
        raise ConfigError(
            f"ERROR: instrument.product_type must be one of {sorted(VALID_PRODUCT_TYPES)}.\n"
            "The bot did not start."
        )
    if exchange_segment in {"NSE_FNO", "BSE_FNO", "MCX_COMM", "NSE_CURRENCY", "BSE_CURRENCY"}:
        if product_type not in DERIVATIVE_PRODUCTS:
            raise ConfigError(
                "ERROR: F&O / commodity product_type must be INTRADAY or MARGIN.\nThe bot did not start."
            )
    elif product_type not in EQUITY_PRODUCTS:
        raise ConfigError("ERROR: equity product_type is invalid.\nThe bot did not start.")
    instrument["product_type"] = product_type

    interval = normalize_timeframe(candles.get("interval", "5"))
    if interval not in VALID_DHAN_INTERVALS:
        raise ConfigError(
            "ERROR: candles.interval must be one of 1, 5, 15, 25, 60, DAY.\nThe bot did not start."
        )
    candles["interval"] = interval
    candles["lookback"] = int(_as_positive_number(candles.get("lookback", 50), "candles.lookback"))

    volume_breakout["volume_ma_period"] = int(
        _as_positive_number(volume_breakout.get("volume_ma_period", 20), "volume_breakout.volume_ma_period")
    )
    volume_breakout["volume_multiplier"] = _as_positive_number(
        volume_breakout.get("volume_multiplier", 2.0), "volume_breakout.volume_multiplier"
    )
    volume_breakout["min_volume_ratio"] = _as_positive_number(
        volume_breakout.get("min_volume_ratio", volume_breakout["volume_multiplier"]),
        "volume_breakout.min_volume_ratio",
    )
    volume_breakout["breakout_lookback"] = int(
        _as_positive_number(volume_breakout.get("breakout_lookback", 20), "volume_breakout.breakout_lookback")
    )
    volume_breakout["min_breakout_percent"] = _as_non_negative_number(
        volume_breakout.get("min_breakout_percent", 0), "volume_breakout.min_breakout_percent"
    )
    volume_breakout["max_breakout_percent"] = _as_non_negative_number(
        volume_breakout.get("max_breakout_percent", 0), "volume_breakout.max_breakout_percent"
    )
    if (
        volume_breakout["max_breakout_percent"] > 0
        and volume_breakout["max_breakout_percent"] < volume_breakout["min_breakout_percent"]
    ):
        raise ConfigError(
            "ERROR: volume_breakout.max_breakout_percent must be >= min_breakout_percent.\n"
            "The bot did not start."
        )
    volume_breakout["require_volume_confirmation"] = _as_bool(
        volume_breakout.get("require_volume_confirmation"), True
    )
    volume_breakout["require_candle_confirmation"] = _as_bool(
        volume_breakout.get("require_candle_confirmation"), True
    )
    volume_breakout["use_previous_candle_high_low"] = _as_bool(
        volume_breakout.get("use_previous_candle_high_low"), False
    )
    volume_breakout["use_rolling_high_low"] = _as_bool(
        volume_breakout.get("use_rolling_high_low"), True
    )
    if not volume_breakout["use_previous_candle_high_low"] and not volume_breakout["use_rolling_high_low"]:
        volume_breakout["use_rolling_high_low"] = True
    volume_breakout["min_candle_body_percent"] = _as_non_negative_number(
        volume_breakout.get("min_candle_body_percent", 0), "volume_breakout.min_candle_body_percent"
    )
    volume_breakout["max_candle_range_percent"] = _as_non_negative_number(
        volume_breakout.get("max_candle_range_percent", 0), "volume_breakout.max_candle_range_percent"
    )

    needed = max(
        volume_breakout["volume_ma_period"] + 1,
        volume_breakout["breakout_lookback"] + 1,
        int(trend_filter.get("ema_slow") or 21) + 1,
    )
    if candles["lookback"] < needed:
        raise ConfigError(
            f"ERROR: candles.lookback must be at least {needed} to cover volume, "
            "breakout, and EMA windows.\nThe bot did not start."
        )

    trend_filter["enabled"] = _as_bool(trend_filter.get("enabled"), False)
    trend_filter["ema_fast"] = int(
        _as_positive_number(trend_filter.get("ema_fast", 9), "trend_filter.ema_fast")
    )
    trend_filter["ema_slow"] = int(
        _as_positive_number(trend_filter.get("ema_slow", 21), "trend_filter.ema_slow")
    )
    if trend_filter["ema_fast"] >= trend_filter["ema_slow"]:
        raise ConfigError(
            "ERROR: trend_filter.ema_fast must be smaller than ema_slow.\nThe bot did not start."
        )
    trend_filter["long_only_above_ema"] = _as_bool(trend_filter.get("long_only_above_ema"), True)
    trend_filter["short_only_below_ema"] = _as_bool(trend_filter.get("short_only_below_ema"), True)

    take_profit = _require_mapping(risk, "take_profit", "risk.take_profit")
    take_profit["enabled"] = _as_bool(take_profit.get("enabled"), True)
    take_profit["mode"] = _normalize_level_mode(take_profit.get("mode", "percentage"), "risk.take_profit.mode")
    if take_profit["enabled"]:
        take_profit["value"] = _as_positive_number(take_profit.get("value"), "risk.take_profit.value")
    else:
        take_profit["value"] = _as_non_negative_number(take_profit.get("value", 0), "risk.take_profit.value")
    risk["take_profit"] = take_profit

    stop_loss = _require_mapping(risk, "stop_loss", "risk.stop_loss")
    stop_loss["enabled"] = _as_bool(stop_loss.get("enabled"), True)
    stop_loss["mode"] = _normalize_level_mode(stop_loss.get("mode", "percentage"), "risk.stop_loss.mode")
    if stop_loss["enabled"]:
        stop_loss["value"] = _as_positive_number(stop_loss.get("value"), "risk.stop_loss.value")
    else:
        stop_loss["value"] = _as_non_negative_number(stop_loss.get("value", 0), "risk.stop_loss.value")
    risk["stop_loss"] = stop_loss

    trailing = risk.get("trailing_stop")
    if not isinstance(trailing, dict):
        trailing = {}
    trailing["enabled"] = _as_bool(trailing.get("enabled"), False)
    trailing["activation_percent"] = _as_non_negative_number(
        trailing.get("activation_percent", 0), "risk.trailing_stop.activation_percent"
    )
    trailing["distance_percent"] = _as_non_negative_number(
        trailing.get("distance_percent", 0), "risk.trailing_stop.distance_percent"
    )
    if trailing["enabled"] and trailing["distance_percent"] <= 0:
        raise ConfigError(
            "ERROR: risk.trailing_stop.distance_percent must be > 0 when enabled.\nThe bot did not start."
        )
    risk["trailing_stop"] = trailing

    risk["max_holding_seconds"] = int(
        _as_non_negative_number(risk.get("max_holding_seconds", 0), "risk.max_holding_seconds")
    )
    risk["max_trades_per_day"] = int(
        _as_non_negative_number(risk.get("max_trades_per_day", 5), "risk.max_trades_per_day")
    )
    risk["max_consecutive_losses"] = int(
        _as_non_negative_number(risk.get("max_consecutive_losses", 0), "risk.max_consecutive_losses")
    )
    risk["max_daily_loss"] = _as_non_negative_number(
        risk.get("max_daily_loss", 0), "risk.max_daily_loss"
    )
    risk["daily_profit_target"] = _as_non_negative_number(
        risk.get("daily_profit_target", 0), "risk.daily_profit_target"
    )
    risk["one_position_at_a_time"] = _as_bool(risk.get("one_position_at_a_time"), True)
    risk["cooldown_seconds"] = _as_non_negative_number(
        risk.get("cooldown_seconds", 0), "risk.cooldown_seconds"
    )
    risk["close_on_risk_limit"] = _as_bool(risk.get("close_on_risk_limit"), False)
    risk["estimated_cost_per_trade"] = _as_non_negative_number(
        risk.get("estimated_cost_per_trade", 0), "risk.estimated_cost_per_trade"
    )

    trading["long_enabled"] = _as_bool(trading.get("long_enabled"), True)
    trading["short_enabled"] = _as_bool(trading.get("short_enabled"), True)
    if not trading["long_enabled"] and not trading["short_enabled"]:
        raise ConfigError(
            "ERROR: at least one of trading.long_enabled or short_enabled must be true.\n"
            "The bot did not start."
        )
    order_type = str(trading.get("order_type") or "MARKET").strip().upper()
    if order_type not in VALID_ORDER_TYPES:
        raise ConfigError("ERROR: trading.order_type must be MARKET or LIMIT.\nThe bot did not start.")
    trading["order_type"] = order_type
    trading["stop_bot_after_tp"] = _as_bool(trading.get("stop_bot_after_tp"), True)
    trading["stop_bot_after_sl"] = _as_bool(trading.get("stop_bot_after_sl"), True)
    trading["live_trading_confirmation"] = _as_bool(trading.get("live_trading_confirmation"), False)
    trading["close_positions_on_stop"] = _as_bool(trading.get("close_positions_on_stop"), False)

    day_trading = _require_mapping(trading, "day_trading", "trading.day_trading")
    day_trading["enabled"] = _as_bool(day_trading.get("enabled"), True)
    start_h, start_m = _parse_hhmm(day_trading.get("start_time", "09:20"), "trading.day_trading.start_time")
    stop_h, stop_m = _parse_hhmm(
        day_trading.get("stop_entry_time", "15:15"), "trading.day_trading.stop_entry_time"
    )
    force_h, force_m = _parse_hhmm(
        day_trading.get("force_exit_time", "15:20"), "trading.day_trading.force_exit_time"
    )
    day_trading["start_time"] = f"{start_h:02d}:{start_m:02d}"
    day_trading["stop_entry_time"] = f"{stop_h:02d}:{stop_m:02d}"
    day_trading["force_exit_time"] = f"{force_h:02d}:{force_m:02d}"
    day_trading["close_all_positions_at_end"] = _as_bool(
        day_trading.get("close_all_positions_at_end"), True
    )
    if day_trading["enabled"] and (start_h, start_m) >= (stop_h, stop_m):
        raise ConfigError(
            "ERROR: trading.day_trading.start_time must be before stop_entry_time.\n"
            "The bot did not start."
        )
    if day_trading["enabled"] and (stop_h, stop_m) > (force_h, force_m):
        raise ConfigError(
            "ERROR: trading.day_trading.stop_entry_time must be at or before force_exit_time.\n"
            "The bot did not start."
        )
    trading["day_trading"] = day_trading

    system["polling_seconds"] = _as_positive_number(
        system.get("polling_seconds", 5), "system.polling_seconds"
    )
    system["timezone"] = str(system.get("timezone") or "Asia/Kolkata").strip()
    system["dry_run"] = _as_bool(system.get("dry_run"), True)
    system["allow_live_trading"] = _as_bool(system.get("allow_live_trading"), False)

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
    execution["enable_long"] = trading["long_enabled"]
    execution["enable_short"] = trading["short_enabled"]
    execution["prevent_duplicate_orders"] = _as_bool(
        safety.get("prevent_duplicate_orders", True), True
    )

    safety["dry_run"] = system["dry_run"]
    safety["allow_live_trading"] = system["allow_live_trading"]
    safety["prevent_duplicate_orders"] = execution["prevent_duplicate_orders"]
    safety["require_market_hours"] = _as_bool(safety.get("require_market_hours"), True)
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
    logging_cfg["file_name"] = str(logging_cfg.get("file_name") or "volume_breakout_algo.log").strip()
    logging_cfg["level"] = str(logging_cfg.get("level") or "INFO").strip().upper()

    cli["enabled"] = _as_bool(cli.get("enabled"), True)
    cli["refresh_seconds"] = _as_positive_number(cli.get("refresh_seconds", 1), "cli.refresh_seconds")
    cli["show_indicators"] = _as_bool(cli.get("show_indicators"), True)
    cli["show_signal"] = _as_bool(cli.get("show_signal"), True)
    cli["show_orders"] = _as_bool(cli.get("show_orders"), True)
    cli["event_history_size"] = int(
        _as_positive_number(cli.get("event_history_size", 8), "cli.event_history_size")
    )

    config["app"] = {
        "name": strategy["name"],
        "environment": "paper" if system["dry_run"] else "live",
        "log_level": logging_cfg["level"],
        "polling_seconds": system["polling_seconds"],
    }
    config["bot"] = {
        "name": strategy["name"],
        "enabled": strategy["enabled"],
        "dry_run": system["dry_run"],
        "allow_live_trading": system["allow_live_trading"],
        "polling_seconds": system["polling_seconds"],
        "order_wait_seconds": execution["order_timeout_seconds"],
        "reconcile_every_cycles": execution["reconcile_every_cycles"],
        "candle_lookback": candles["lookback"],
    }
    config["trading_hours"] = {
        "enabled": day_trading["enabled"],
        "start_time": day_trading["start_time"],
        "stop_entry_time": day_trading["stop_entry_time"],
        "close_positions_time": day_trading["force_exit_time"],
        "timezone": system["timezone"],
        "day_trading_enabled": day_trading["enabled"],
        "force_exit_enabled": day_trading["enabled"],
        "close_all_positions_at_end": day_trading["close_all_positions_at_end"],
    }
    config["shutdown"] = {
        "close_positions_on_manual_stop": trading["close_positions_on_stop"],
        "close_positions_on_session_end": day_trading["close_all_positions_at_end"],
        "close_positions_on_tp_sl": True,
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
            "Set system.dry_run: false and system.allow_live_trading: true.\n"
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
        log_path = BASE_DIR / str(logging_cfg.get("file_name") or "volume_breakout_algo.log")
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


def process_stop_signal() -> bool:
    """Spec-named wrapper. Announce a manual stop when the file appears."""
    announce_manual_stop_if_needed()
    return stop_requested()


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
        or config.get("system", {}).get("timezone")
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


def check_trading_window(config: dict, now: Optional[datetime] = None) -> tuple[bool, str]:
    """
    Decide whether new entries are allowed right now.

    When day-trading mode is disabled, the clock gates are skipped.
    Risk / TP / SL still operate.

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
            "ERROR: Dhan credentials are missing. Set "
            "DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN in .env.\nThe bot did not start."
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

def _lookback_calendar_days(timeframe: str, lookback: int) -> int:
    if timeframe == "DAY":
        return max(lookback + 5, 10)
    minutes = interval_minutes(timeframe) or 5
    bars_per_day = max(1, int(375 / minutes))
    return max(2, int((lookback / bars_per_day) + 3))


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


def _is_candle_complete(candle: Candle, timeframe: str, now: datetime) -> bool:
    """True when this bar's interval has already closed."""
    if timeframe == "DAY":
        return candle.timestamp.date() < now.date()
    minutes = interval_minutes(timeframe) or 5
    close_at = candle.timestamp + timedelta(minutes=minutes)
    return now >= close_at


def validate_candles(candles: list[Candle]) -> list[Candle]:
    """
    Drop obviously corrupted bars before indicator math.

    Why this function exists:
        A bad OHLC row can invent a fake volume breakout. Unreliable data
        must never become a trade.
    """
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
        if candle.volume < 0:
            continue
        clean.append(candle)
    return clean


def load_market_data(dhan, config: dict) -> list[Candle]:
    """Spec-named wrapper around get_market_data()."""
    return get_market_data(dhan, config)


def get_market_data(dhan, config: dict) -> list[Candle]:
    """
    Fetch required candle history for volume, breakout, and EMA.

    Why this function exists:
        Signals must be computed on closed candles. Fetching unbounded
        history would waste RAM on a 1 GB VM.

    Dhan considerations:
        Use ``intraday_minute_data`` for minute intervals and
        ``historical_daily_data`` for DAY. Timestamps are epoch values.

    Returns:
        Completed candles only, oldest-first. Empty list on failure so the
        loop can wait without placing an order.
    """
    instrument = config["instrument"]
    timeframe = config["candles"]["interval"]
    lookback = int(config["candles"]["lookback"])
    tzinfo = session_timezone(config)
    now = now_in_session_tz(config)
    days = _lookback_calendar_days(timeframe, lookback)
    from_date = (now.date() - timedelta(days=days)).strftime("%Y-%m-%d")
    to_date = now.date().strftime("%Y-%m-%d")
    security_id = str(instrument["security_id"])
    exchange_segment = _map_exchange_segment(instrument["exchange_segment"])
    instrument_type = instrument["instrument_type"]
    attempts = _retry_attempts(config)
    delay = _retry_delay(config)
    last_error: Any = None

    for attempt in range(1, attempts + 1):
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
            cleaned = validate_candles(candles)
            completed = [
                item for item in cleaned if _is_candle_complete(item, timeframe, now)
            ]
            if config["volume_breakout"].get("require_candle_confirmation", True):
                selected = completed
            else:
                forming = [
                    item
                    for item in cleaned
                    if not _is_candle_complete(item, timeframe, now)
                ]
                selected = completed + forming[-1:]
            if lookback > 0:
                selected = selected[-lookback:]
            return selected
        except Exception as exc:
            last_error = exc
            logging.warning("Candle fetch failed (attempt %s/%s): %s", attempt, attempts, exc)
            if attempt < attempts:
                time.sleep(delay)
    logging.error("Candle fetch exhausted retries: %s", last_error)
    return []


# ============================================================
# VOLUME BREAKOUT STRATEGY
# ============================================================

def calculate_ema(values: list[float], period: int) -> list[Optional[float]]:
    """
    Exponential moving average seeded with an SMA of the first ``period`` values.

    Mathematics:
        multiplier k = 2 / (period + 1)
        EMA[t] = value[t] * k + EMA[t-1] * (1 - k)

    Trading note:
        Use completed-bar values only. An in-progress bar would keep
        rewriting the latest EMA and invent fake trend flips.
    """
    result: list[Optional[float]] = [None] * len(values)
    if period <= 0 or len(values) < period:
        return result
    seed = sum(values[:period]) / period
    result[period - 1] = seed
    multiplier = 2.0 / (period + 1.0)
    previous = seed
    for index in range(period, len(values)):
        current = (values[index] * multiplier) + (previous * (1.0 - multiplier))
        result[index] = current
        previous = current
    return result


def calculate_volume_ratio(current_volume: float, average_volume: Optional[float]) -> Optional[float]:
    """
    Calculate how unusual the current trading volume is.

    Use case:
        The strategy uses this value to determine whether a breakout
        is supported by unusually high market participation.

    A value of 2.0 means current volume is approximately twice
    the configured average volume.
    """
    if average_volume is None or average_volume <= 0:
        return None
    return current_volume / average_volume


def calculate_volume_metrics(candles: list[Candle], period: int) -> tuple[Optional[float], Optional[float], Optional[float]]:
    """
    Current volume versus the simple average of the previous ``period`` bars.

    We compare the current confirmed candle's volume against the
    rolling average of previous candles. This helps identify
    breakouts occurring with abnormal market participation.

    Returns:
        (current_volume, average_volume, ratio). Average excludes the
        evaluation bar so a spike is compared against recent history.
    """
    if period <= 0 or len(candles) < period + 1:
        current = candles[-1].volume if candles else None
        return current, None, None
    current = candles[-1].volume
    window = [item.volume for item in candles[-(period + 1) : -1]]
    if not window:
        return current, None, None
    average = sum(window) / len(window)
    return current, average, calculate_volume_ratio(current, average)


def calculate_breakout_levels(candles: list[Candle], config: dict) -> tuple[Optional[float], Optional[float]]:
    """
    Prior high/low used as the breakout range.

    Why this function exists:
        A breakout is only meaningful against prices that were already
        known. The evaluation candle is excluded so we never use its
        own high/low as the level it is supposed to break.

    Inputs:
        Completed candles, oldest-first. The last bar is the evaluation bar.

    Returns:
        (breakout_high, breakout_low) or (None, None) when warmup is incomplete.
    """
    settings = config["volume_breakout"]
    if len(candles) < 2:
        return None, None
    prior = candles[:-1]
    if settings.get("use_previous_candle_high_low") and not settings.get("use_rolling_high_low"):
        lookback = 1
    else:
        lookback = int(settings["breakout_lookback"])
        if settings.get("use_previous_candle_high_low"):
            lookback = 1
    if len(prior) < lookback:
        return None, None
    window = prior[-lookback:]
    return max(item.high for item in window), min(item.low for item in window)


def calculate_trend_filter(closes: list[float], config: dict) -> tuple[Optional[float], Optional[float]]:
    """
    Compute fast and slow EMA on completed closes.

    Trading use case:
        Optional confirmation that a long breakout is occurring in an
        uptrend (price above slow EMA, fast above slow) or the inverse
        for shorts. Disabled filters return the values for display only.
    """
    trend = config["trend_filter"]
    fast_series = calculate_ema(closes, int(trend["ema_fast"]))
    slow_series = calculate_ema(closes, int(trend["ema_slow"]))
    return fast_series[-1] if fast_series else None, slow_series[-1] if slow_series else None


def _candle_body_percent(candle: Candle) -> Optional[float]:
    if candle.open <= 0:
        return None
    return abs(candle.close - candle.open) / candle.open * 100.0


def _candle_range_percent(candle: Candle) -> Optional[float]:
    if candle.open <= 0:
        return None
    return (candle.high - candle.low) / candle.open * 100.0


def generate_signal(candles: list[Candle], config: dict, state: BotState) -> SignalResult:
    """
    Detect a volume-confirmed price breakout on the evaluation candle.

    Why this function exists:
        Strategy math must stay separate from Dhan order placement so a
        data glitch cannot silently become a live order.

    Look-ahead rule:
        Only completed candles are passed in. The last bar is the
        evaluation candle. Breakout levels and volume average use
        strictly earlier bars.

    Returns:
        SignalResult with BUY, SELL, or NONE plus the no-trade reason.
    """
    empty = SignalResult(signal="NONE", reason="WAITING_FOR_MARKET_DATA")
    if not candles:
        return empty

    settings = config["volume_breakout"]
    eval_candle = candles[-1]
    needed = max(int(settings["volume_ma_period"]) + 1, int(settings["breakout_lookback"]) + 1)
    if len(candles) < needed:
        return SignalResult(signal="NONE", reason="WARMUP", candle_time=eval_candle.timestamp)

    current_vol, avg_vol, ratio = calculate_volume_metrics(candles, int(settings["volume_ma_period"]))
    high, low = calculate_breakout_levels(candles, config)
    closes = [item.close for item in candles]
    ema_fast, ema_slow = calculate_trend_filter(closes, config)
    body_pct = _candle_body_percent(eval_candle)
    range_pct = _candle_range_percent(eval_candle)

    result = SignalResult(
        signal="NONE",
        reason="NO_BREAKOUT",
        close=eval_candle.close,
        volume=current_vol,
        average_volume=avg_vol,
        volume_ratio=ratio,
        breakout_high=high,
        breakout_low=low,
        ema_fast=ema_fast,
        ema_slow=ema_slow,
        candle_time=eval_candle.timestamp,
        body_percent=body_pct,
        range_percent=range_pct,
    )

    if high is None or low is None or high <= 0 or low <= 0:
        result.reason = "WARMUP"
        return result

    long_break = eval_candle.close > high
    short_break = eval_candle.close < low
    if not long_break and not short_break:
        result.reason = "NO_BREAKOUT"
        return result

    side = "BUY" if long_break else "SELL"
    if long_break and short_break:
        side = "BUY" if config["trading"]["long_enabled"] else "SELL"
    level = high if side == "BUY" else low
    distance_pct = abs(eval_candle.close - level) / level * 100.0
    result.breakout_percent = distance_pct

    if distance_pct < float(settings["min_breakout_percent"]):
        result.reason = "BREAKOUT_TOO_SMALL"
        return result
    max_break = float(settings["max_breakout_percent"])
    if max_break > 0 and distance_pct > max_break:
        result.reason = "BREAKOUT_TOO_LARGE"
        return result

    if settings.get("require_volume_confirmation", True):
        if ratio is None:
            result.reason = "WARMUP"
            return result
        threshold = max(float(settings["volume_multiplier"]), float(settings["min_volume_ratio"]))
        if ratio < threshold:
            result.reason = "VOLUME_BELOW_THRESHOLD"
            return result

    min_body = float(settings["min_candle_body_percent"])
    if min_body > 0 and (body_pct is None or body_pct < min_body):
        result.reason = "CANDLE_BODY_TOO_SMALL"
        return result
    max_range = float(settings["max_candle_range_percent"])
    if max_range > 0 and (range_pct is None or range_pct > max_range):
        result.reason = "CANDLE_RANGE_TOO_WIDE"
        return result

    trend = config["trend_filter"]
    if trend.get("enabled"):
        reference = ema_slow
        if reference is None:
            result.reason = "WARMUP"
            return result
        if side == "BUY" and trend.get("long_only_above_ema") and eval_candle.close <= reference:
            result.reason = "TREND_FILTER"
            return result
        if side == "SELL" and trend.get("short_only_below_ema") and eval_candle.close >= reference:
            result.reason = "TREND_FILTER"
            return result
        if ema_fast is not None:
            if side == "BUY" and ema_fast <= reference:
                result.reason = "TREND_FILTER"
                return result
            if side == "SELL" and ema_fast >= reference:
                result.reason = "TREND_FILTER"
                return result

    if state.last_signal_candle == eval_candle.timestamp:
        result.reason = "SAME_CANDLE"
        return result
    if (
        state.last_consumed_side == side
        and state.last_consumed_level is not None
        and abs(state.last_consumed_level - level) < float(config["instrument"]["tick_size"])
    ):
        result.reason = "SAME_BREAKOUT"
        return result

    result.signal = side
    result.reason = "VOLUME_BREAKOUT"
    return result


def apply_signal_to_state(state: BotState, result: SignalResult) -> None:
    """Copy indicator values onto the dashboard state. Does not place orders."""
    state.current_volume = result.volume
    state.current_avg_volume = result.average_volume
    state.current_volume_ratio = result.volume_ratio
    state.breakout_high = result.breakout_high
    state.breakout_low = result.breakout_low
    state.ema_fast = result.ema_fast
    state.ema_slow = result.ema_slow
    if result.candle_time:
        state.last_candle_time = result.candle_time
    if result.signal == "BUY":
        state.last_signal = "LONG BREAKOUT"
        state.confirmation_status = "CONFIRMED"
        state.strategy_condition = "VOLUME BREAKOUT LONG"
    elif result.signal == "SELL":
        state.last_signal = "SHORT BREAKOUT"
        state.confirmation_status = "CONFIRMED"
        state.strategy_condition = "VOLUME BREAKOUT SHORT"
    else:
        state.last_signal = "NONE"
        state.confirmation_status = "WATCHING"
        state.strategy_condition = WHY_NO_TRADE_LABELS.get(result.reason, result.reason)
        state.why_no_trade = result.reason


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
    """Refresh LTP-derived P&L and trailing extremes for the open position."""
    if ltp and ltp > 0:
        state.last_ltp = ltp
    current = state.last_ltp
    if state.current_position != "FLAT" and current:
        if state.highest_price is None or current > state.highest_price:
            state.highest_price = current
        if state.lowest_price is None or current < state.lowest_price:
            state.lowest_price = current
        update_trailing_stop(state, config)
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
# RISK — TP / SL / TRAIL / HOLD
# ============================================================

def _level_distance(entry_price: float, value: float, mode: str) -> Optional[float]:
    """Convert a configured TP/SL value into a rupee distance, or None for ABSOLUTE."""
    if mode == "ABSOLUTE":
        return None
    if mode == "POINTS":
        return value
    return entry_price * (value / 100.0)


def calculate_trade_levels(entry_price: float, direction: str, config: dict) -> tuple[Optional[float], Optional[float]]:
    """Return (take_profit_price, stop_loss_price) from the actual fill."""
    return (
        calculate_take_profit(entry_price, direction, config),
        calculate_stop_loss(entry_price, direction, config),
    )


def calculate_stop_loss(entry_price: float, direction: str, config: dict) -> Optional[float]:
    """
    Calculate the stop-loss price for the active position.

    Modes:
        percentage — value 0.20 means 0.20 percent of fill
        points — value is a rupee distance
        absolute — value is the exact SL price

    Long: SL = entry - distance. Short: SL = entry + distance.
    """
    block = config["risk"]["stop_loss"]
    if not block.get("enabled"):
        return None
    if entry_price <= 0:
        raise ValueError("entry_price must be positive to calculate stop-loss")
    tick = float(config["instrument"]["tick_size"])
    mode = str(block["mode"])
    if mode == "ABSOLUTE":
        return round_to_tick(float(block["value"]), tick)
    distance = _level_distance(entry_price, float(block["value"]), mode)
    if distance is None:
        return None
    if direction == "LONG":
        return round_to_tick(entry_price - distance, tick)
    if direction == "SHORT":
        return round_to_tick(entry_price + distance, tick)
    raise ValueError(f"Unknown direction {direction!r}")


def calculate_take_profit(entry_price: float, direction: str, config: dict) -> Optional[float]:
    """
    Calculate the take-profit price for the active position.

    Modes match calculate_stop_loss. Long: TP = entry + distance.
    Short: TP = entry - distance. Absolute mode uses the configured price.
    """
    block = config["risk"]["take_profit"]
    if not block.get("enabled"):
        return None
    if entry_price <= 0:
        raise ValueError("entry_price must be positive to calculate take-profit")
    tick = float(config["instrument"]["tick_size"])
    mode = str(block["mode"])
    if mode == "ABSOLUTE":
        return round_to_tick(float(block["value"]), tick)
    distance = _level_distance(entry_price, float(block["value"]), mode)
    if distance is None:
        return None
    if direction == "LONG":
        return round_to_tick(entry_price + distance, tick)
    if direction == "SHORT":
        return round_to_tick(entry_price - distance, tick)
    raise ValueError(f"Unknown direction {direction!r}")


def arm_risk_levels(state: BotState, config: dict, entry_price: float, side: str) -> None:
    """Attach TP/SL prices to state from the actual fill."""
    state.entry_price = entry_price
    try:
        state.take_profit_price, state.stop_loss_price = calculate_trade_levels(
            entry_price, side, config
        )
    except ValueError as exc:
        logging.error("Could not arm TP/SL: %s", exc)
        state.stop_loss_price = None
        state.take_profit_price = None


def update_trailing_stop(state: BotState, config: dict) -> None:
    """
    Arm a trailing stop only after activation_percent is reached.

    LONG: after highest >= entry * (1 + activation%), trail = highest * (1 - distance%)
    SHORT: after lowest <= entry * (1 - activation%), trail = lowest * (1 + distance%)

    Percentage values are percent units (0.20 means 0.20%).
    """
    trail_cfg = config["risk"].get("trailing_stop") or {}
    if not trail_cfg.get("enabled"):
        state.trailing_stop_price = None
        state.trailing_armed = False
        return
    if state.current_position == "FLAT" or not state.entry_price:
        state.trailing_stop_price = None
        state.trailing_armed = False
        return
    activation = float(trail_cfg.get("activation_percent") or 0)
    trail = float(trail_cfg.get("distance_percent") or 0)
    if trail <= 0:
        state.trailing_stop_price = None
        return
    tick = float(config["instrument"]["tick_size"])
    entry = state.entry_price
    if state.current_position == "LONG" and state.highest_price:
        move = ((state.highest_price - entry) / entry) * 100.0
        if move >= activation:
            state.trailing_armed = True
            raw = state.highest_price * (1.0 - trail / 100.0)
            candidate = round_to_tick(raw, tick)
            if state.trailing_stop_price is None or candidate > state.trailing_stop_price:
                state.trailing_stop_price = candidate
        return
    if state.current_position == "SHORT" and state.lowest_price:
        move = ((entry - state.lowest_price) / entry) * 100.0
        if move >= activation:
            state.trailing_armed = True
            raw = state.lowest_price * (1.0 + trail / 100.0)
            candidate = round_to_tick(raw, tick)
            if state.trailing_stop_price is None or candidate < state.trailing_stop_price:
                state.trailing_stop_price = candidate


def effective_stop_loss(state: BotState) -> Optional[float]:
    """More protective of fixed SL and trailing SL."""
    fixed = state.stop_loss_price
    trail = state.trailing_stop_price
    if state.current_position == "LONG":
        candidates = [value for value in (fixed, trail) if value is not None]
        return max(candidates) if candidates else None
    if state.current_position == "SHORT":
        candidates = [value for value in (fixed, trail) if value is not None]
        return min(candidates) if candidates else None
    return None


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
    return should_trigger_sl(ltp, effective_stop_loss(state), state.current_position)


def check_trailing_stop(state: BotState, ltp: Optional[float]) -> bool:
    if not state.trailing_armed or state.trailing_stop_price is None:
        return False
    return should_trigger_sl(ltp, state.trailing_stop_price, state.current_position)


def check_max_holding_time(config: dict, state: BotState) -> bool:
    """True when the open position has exceeded risk.max_holding_seconds."""
    limit = int(config["risk"].get("max_holding_seconds") or 0)
    if limit <= 0 or state.current_position == "FLAT" or state.position_opened_at is None:
        return False
    now = now_in_session_tz(config)
    return (now - state.position_opened_at).total_seconds() >= limit


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
    state.trailing_stop_price = None
    state.trailing_armed = False
    state.highest_price = None
    state.lowest_price = None
    state.position_opened_at = None
    state.last_pnl = 0.0
    state.last_pnl_percent = 0.0


def update_trade_statistics(state: BotState, pnl: float, reason: str, side: Optional[str] = None) -> None:
    """Record a completed trade result in memory. No database is used."""
    state.daily_realized_pnl += pnl
    state.last_exit_reason = reason
    state.last_exit_time = datetime.now(timezone.utc)
    if side == "LONG":
        state.long_trades += 1
    elif side == "SHORT":
        state.short_trades += 1
    if pnl > 0:
        state.winning_trades += 1
        state.gross_profit += pnl
        state.consecutive_losses = 0
    elif pnl < 0:
        state.losing_trades += 1
        state.gross_loss += abs(pnl)
        state.consecutive_losses += 1
    logging.info(
        "TRADE RECORDED reason=%s realized_pnl=%.2f daily=%.2f wins=%s losses=%s",
        reason,
        pnl,
        state.daily_realized_pnl,
        state.winning_trades,
        state.losing_trades,
    )


def record_trade(state: BotState, pnl: float, reason: str) -> None:
    update_trade_statistics(state, pnl, reason)


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
        closed_side = state.current_position
        pnl, _percent = calculate_pnl(
            closed_side,
            state.position_quantity or quantity,
            state.entry_price,
            fill_price or state.last_ltp,
        )
        update_trade_statistics(state, pnl, state.last_exit_reason or intent, closed_side)
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
    if state.take_profit_price:
        logging.info("TP: %.2f", state.take_profit_price)
    if state.stop_loss_price:
        logging.info("SL: %.2f", state.stop_loss_price)


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


def monitor_order(dhan, config: dict, state: BotState, order_id: str, requested_quantity: int) -> Optional[dict]:
    """Spec-named wrapper around wait_for_order_completion()."""
    return wait_for_order_completion(dhan, config, state, order_id, requested_quantity)


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
            if fill_price > 0:
                logging.info("ENTRY: %.2f", fill_price)
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
        Every exit path (TP, SL, trail, hold, force-exit, manual, risk)
        must share one function so the CLI always shows the same reason codes.
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
    CONSOLE.print("[bold yellow]CLOSE-ALL POSITIONS STARTED[/bold yellow]")
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
        CONSOLE.print("[bold yellow]CLOSE-ALL POSITIONS FINISHED[/bold yellow]")
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
            CONSOLE.print("[bold yellow]CLOSE-ALL POSITIONS FINISHED[/bold yellow]")
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
                CONSOLE.print("[bold yellow]CLOSE-ALL POSITIONS FINISHED[/bold yellow]")
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
            CONSOLE.print("[bold red]CLOSE-ALL POSITIONS FINISHED WITH LEFTOVERS[/bold red]")
            return False
    if leftover is None:
        logging.error("close_all_positions() finished but the position book could not be verified.")
        CONSOLE.print("[bold red]CLOSE-ALL POSITIONS UNVERIFIED[/bold red]")
        return False
    _mark_flat(state)
    CONSOLE.print("[bold yellow]CLOSE-ALL POSITIONS FINISHED[/bold yellow]")
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
        Reconstructs TP/SL from the broker average fill when possible.
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
    state.engine_state = "POSITION_OPEN"


# ============================================================
# RISK / TRADE VALIDATION
# ============================================================

def cooldown_active(config: dict, state: BotState) -> bool:
    seconds = float(config["risk"].get("cooldown_seconds") or 0)
    if seconds <= 0 or state.last_exit_time is None:
        return False
    elapsed = (datetime.now(timezone.utc) - state.last_exit_time).total_seconds()
    return elapsed < seconds


def daily_risk_blocked(config: dict, state: BotState) -> Optional[str]:
    risk = config["risk"]
    max_loss = float(risk.get("max_daily_loss") or 0)
    if max_loss > 0 and state.daily_realized_pnl <= -max_loss:
        return "RISK_LIMIT_REACHED"
    profit_target = float(risk.get("daily_profit_target") or 0)
    if profit_target > 0 and state.daily_realized_pnl >= profit_target:
        return "DAILY_PROFIT_TARGET"
    max_losses = int(risk.get("max_consecutive_losses") or 0)
    if max_losses > 0 and state.consecutive_losses >= max_losses:
        return "MAX_CONSECUTIVE_LOSSES"
    max_trades = int(risk.get("max_trades_per_day") or 0)
    if max_trades > 0 and state.trades_today >= max_trades:
        return "MAX_TRADES_REACHED"
    return None


def check_risk_limits(config: dict, state: BotState) -> Optional[str]:
    """Pure daily-risk check used by validate_trade and the loop."""
    return daily_risk_blocked(config, state)


def check_entry_conditions(config: dict, state: BotState, signal: str) -> tuple[bool, str]:
    """
    Verify that a BUY/SELL signal is allowed to become an entry.

    Why this function exists:
        Session, direction flags, open position, pending orders, daily
        limits, cooldown, same-breakout lock, and stop requests must
        all be able to veto a signal without the signal function
        knowing about Dhan.
    """
    if stop_requested():
        return False, "STOP_REQUESTED"
    if signal not in {"BUY", "SELL"}:
        return False, state.why_no_trade or "SCANNING"
    if not config["strategy"].get("enabled", True):
        return False, "BOT_DISABLED"
    allowed, window_reason = check_trading_window(config)
    if not allowed:
        return False, window_reason
    if config["safety"].get("require_market_hours") and not is_market_expected_open(config):
        return False, "WEEKEND" if is_weekend(config) else "SESSION_NOT_STARTED"
    if state.order_in_flight or state.pending_order_id:
        return False, "PENDING_ORDER_EXISTS"
    if config["risk"].get("one_position_at_a_time") and state.current_position != "FLAT":
        return False, "POSITION_ALREADY_OPEN"
    if config["safety"].get("prevent_duplicate_orders", True) and state.current_position != "FLAT":
        return False, "POSITION_ALREADY_OPEN"
    if state.extra.get("unmanaged_existing") or state.extra.get("unexpected_other_position"):
        return False, "BLOCKED_UNEXPECTED_POSITION"
    if config["safety"].get("require_flat_before_entry") and state.current_position != "FLAT":
        return False, "POSITION_ALREADY_OPEN"
    if signal == "BUY" and not config["trading"]["long_enabled"]:
        return False, "LONG_DISABLED"
    if signal == "SELL" and not config["trading"]["short_enabled"]:
        return False, "SHORT_DISABLED"
    if cooldown_active(config, state):
        return False, "COOLDOWN"
    blocked = check_risk_limits(config, state)
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
    blocked = check_risk_limits(config, state)
    if blocked == "MAX_TRADES_REACHED":
        state.next_action = "NEW ENTRIES DISABLED"
        state.why_no_trade = blocked
        return
    if blocked:
        state.next_action = "RISK BLOCKED"
        state.why_no_trade = blocked
        return
    if cooldown_active(config, state):
        state.next_action = "COOLDOWN"
        state.why_no_trade = "COOLDOWN"
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
        "MAX_CONSECUTIVE_LOSSES",
        "DAILY_PROFIT_TARGET",
        "RISK_LIMIT_REACHED",
        "STOP_REQUESTED",
        "SESSION_NOT_STARTED",
        "SESSION_ENDED",
        "ENTRY_CUTOFF",
        "WEEKEND",
        "BOT_DISABLED",
        "VOLUME_BELOW_THRESHOLD",
        "NO_BREAKOUT",
        "WARMUP",
        "SAME_CANDLE",
        "SAME_BREAKOUT",
        "COOLDOWN",
        "TREND_FILTER",
        "BREAKOUT_TOO_SMALL",
        "BREAKOUT_TOO_LARGE",
        "CANDLE_BODY_TOO_SMALL",
        "CANDLE_RANGE_TOO_WIDE",
    }
    if state.why_no_trade in blocking:
        state.next_action = WHY_NO_TRADE_LABELS.get(
            state.why_no_trade, state.why_no_trade
        ).upper()
        return
    state.next_action = "SCANNING FOR VOLUME BREAKOUT"
    state.why_no_trade = "SCANNING"


def monitor_tpsl(dhan, config: dict, state: BotState, ltp: Optional[float]) -> Optional[str]:
    """
    Check live LTP against armed TP/SL/trail/max-hold.

    Returns:
        TAKE_PROFIT, STOP_LOSS, TRAILING_STOP, or MAX_HOLDING_TIME.

    SL is evaluated first so a gap through both levels prefers capital
    protection. Software polling can overshoot the exact price.
    """
    if state.current_position == "FLAT":
        return None
    if check_max_holding_time(config, state):
        return "MAX_HOLDING_TIME"
    if ltp is None or ltp <= 0:
        logging.warning("No valid LTP available for TP/SL. Waiting.")
        return None

    side = state.current_position
    effective_sl = effective_stop_loss(state)
    logging.info(
        "POSITION MONITORING | LTP=%.2f | entry=%s | TP=%s | SL=%s | trail=%s | side=%s | pnl=%.2f",
        ltp,
        f"{state.entry_price:.2f}" if state.entry_price else "n/a",
        f"{state.take_profit_price:.2f}" if state.take_profit_price else "off",
        f"{effective_sl:.2f}" if effective_sl else "off",
        f"{state.trailing_stop_price:.2f}" if state.trailing_armed and state.trailing_stop_price else "off",
        side,
        state.last_pnl,
    )

    if check_stop_loss(state, ltp):
        if state.trailing_armed and check_trailing_stop(state, ltp):
            return "TRAILING_STOP"
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
                "◈ VOLUME BREAKOUT SCALPER ◈\n\nDHAN TRADING CORE",
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
    vb = config["volume_breakout"]
    hours = config["trading_hours"]
    risk = config["risk"]
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="bold cyan", min_width=16)
    grid.add_column(style="white")
    grid.add_row("BOT", str(config["app"].get("name") or "Volume Breakout Scalper"))
    grid.add_row("ENVIRONMENT", str(config["app"].get("environment") or "paper").upper())
    grid.add_row("MODE", "DRY RUN" if is_dry_run(config) else "LIVE")
    grid.add_row("SYMBOL", str(instrument.get("symbol")))
    grid.add_row("SECURITY ID", str(instrument.get("security_id")))
    grid.add_row("CANDLE", f"{config['candles']['interval']}m lookback {config['candles']['lookback']}")
    grid.add_row("VOL MA / MULT", f"{vb['volume_ma_period']} / {vb['volume_multiplier']}x")
    grid.add_row("BREAKOUT N", str(vb["breakout_lookback"]))
    grid.add_row("LONG", "on" if config["trading"]["long_enabled"] else "off")
    grid.add_row("SHORT", "on" if config["trading"]["short_enabled"] else "off")
    sl = risk["stop_loss"]
    tp = risk["take_profit"]
    grid.add_row("SL", f"{sl['value']} {sl['mode']}" if sl["enabled"] else "off")
    grid.add_row("TP", f"{tp['value']} {tp['mode']}" if tp["enabled"] else "off")
    grid.add_row("POLLING", f"{config['app']['polling_seconds']} SEC")
    if hours.get("day_trading_enabled"):
        grid.add_row(
            "SESSION",
            f"{hours.get('start_time')} → {hours.get('stop_entry_time')} / {hours.get('close_positions_time')}",
        )
    else:
        grid.add_row("SESSION", "DAY-TRADING WINDOW OFF")
    CONSOLE.print(Panel(grid, title="[bold cyan]CONFIGURATION[/bold cyan]", border_style="cyan"))
    if is_live_mode(config):
        CONSOLE.print(
            Panel(
                "[bold red]⚠ LIVE TRADING ENABLED\nReal orders may be submitted to Dhan.\n"
                "REAL MONEY MAY BE AT RISK[/bold red]",
                border_style="red",
            )
        )
        logging.info("LIVE TRADING ENABLED. REAL ORDERS MAY BE PLACED.")
    else:
        logging.info("DRY RUN. Real market data will be fetched. No live orders will be sent.")


def render_cli(config: dict, state: BotState) -> Panel:
    """Spec-named wrapper around render_dashboard()."""
    return render_dashboard(config, state)


def render_exit_banner(
    config: dict,
    state: BotState,
    reason: str,
    entry: Optional[float],
    exit_price: Optional[float],
    quantity: int,
    pnl: float,
) -> None:
    """Boxed TP/SL (or other) exit summary."""
    titles = {
        "TAKE_PROFIT": "TAKE PROFIT ACTIVATED",
        "STOP_LOSS": "STOP LOSS ACTIVATED",
        "TRAILING_STOP": "TRAILING STOP ACTIVATED",
        "MAX_HOLDING_TIME": "MAX HOLDING TIME",
        "TRADING_DAY_END": "FORCE EXIT",
        "MANUAL_STOP": "MANUAL STOP",
        "RISK_LIMIT": "RISK LIMIT",
    }
    title = titles.get(reason, reason.replace("_", " "))
    display_pnl, estimated = estimated_net_pnl(config, pnl)
    pnl_text = f"{display_pnl:+,.2f}"
    if estimated:
        pnl_text += " (estimate after configured cost)"
    stop_after = False
    if reason == "TAKE_PROFIT":
        stop_after = bool(config["trading"].get("stop_bot_after_tp"))
    elif reason in {"STOP_LOSS", "TRAILING_STOP"}:
        stop_after = bool(config["trading"].get("stop_bot_after_sl"))
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="bold")
    grid.add_column()
    grid.add_row("Entry", format_inr(entry))
    grid.add_row("Exit", format_inr(exit_price))
    grid.add_row("Qty", str(quantity))
    grid.add_row("P&L", f"₹{pnl_text}")
    grid.add_row("Reason", reason)
    grid.add_row("BOT", "STOPPED" if stop_after else "CONTINUING")
    CONSOLE.print(Panel(grid, title=f"[bold]{title}[/bold]", border_style="yellow"))


def render_dashboard(config: dict, state: BotState) -> Panel:
    """Build the sci-fi command-center panel from in-memory state."""
    now = now_in_session_tz(config)
    instrument = config["instrument"]
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
    ratio_text = f"{state.current_volume_ratio:.2f}x" if state.current_volume_ratio else "—"

    system = Table.grid(padding=(0, 2))
    system.add_column(min_width=14, style="bold dim")
    system.add_column(min_width=22)
    system.add_column(min_width=14, style="bold dim")
    system.add_column(min_width=22)
    system.add_row("STATUS", status, "MODE", f"{mode} / {day_mode}")
    system.add_row("MARKET", market, "ENGINE", state.engine_state)
    system.add_row("POLL", f"{config['app']['polling_seconds']}s", "STRATEGY", "VOLUME BREAKOUT")
    system.add_row("API", state.api_status, "STOP FILE", "YES" if STOP_FILE.exists() else "NO")

    market_tbl = Table.grid(padding=(0, 2))
    market_tbl.add_column(min_width=14, style="bold dim")
    market_tbl.add_column(min_width=22)
    market_tbl.add_column(min_width=14, style="bold dim")
    market_tbl.add_column(min_width=22)
    market_tbl.add_row("SYMBOL", str(instrument["symbol"]), "PRICE", format_inr(state.last_ltp))
    if cli.get("show_indicators", True):
        market_tbl.add_row(
            "VOLUME",
            f"{state.current_volume:,.0f}" if state.current_volume is not None else "—",
            "AVG VOL",
            f"{state.current_avg_volume:,.0f}" if state.current_avg_volume is not None else "—",
        )
        market_tbl.add_row(
            "VOL RATIO",
            ratio_text,
            "BREAKOUT HI",
            format_inr(state.breakout_high),
        )
        market_tbl.add_row(
            "BREAKOUT LO",
            format_inr(state.breakout_low),
            "EMA F/S",
            f"{state.ema_fast:.2f}/{state.ema_slow:.2f}"
            if state.ema_fast is not None and state.ema_slow is not None
            else "—",
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
    sl_display = effective_stop_loss(state)
    position.add_row("POSITION", state.current_position, "QTY", str(state.position_quantity))
    position.add_row("ENTRY", format_inr(state.entry_price), "CURRENT", format_inr(state.last_ltp))
    position.add_row("SL", format_inr(sl_display), "TP", format_inr(state.take_profit_price))
    position.add_row(
        "UNREAL P&L",
        Text(pnl_text, style=pnl_style),
        "REALIZED",
        format_inr(state.daily_realized_pnl),
    )
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
        trading_tbl.add_row(
            "TRADES",
            f"{state.trades_today} / {config['risk']['max_trades_per_day']}",
            "W / L",
            f"{state.winning_trades} / {state.losing_trades}",
        )
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
        "DAY TRADING",
        "ON" if config["trading_hours"].get("day_trading_enabled") else "OFF",
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
        title="[bold cyan]◈ VOLUME BREAKOUT SCALPER ◈[/bold cyan]",
        subtitle=f"[dim]{now.strftime('%Y-%m-%d %H:%M:%S %Z')}[/dim]",
        border_style="cyan",
        padding=(0, 1),
    )


def dashboard_enabled(config: dict) -> bool:
    return bool(config.get("cli", {}).get("enabled", True)) and sys.stdout.isatty()


# ============================================================
# TRADING LOOP
# ============================================================

def process_volume_breakout(
    dhan,
    config: dict,
    state: BotState,
    candles: list[Candle],
    ltp: Optional[float],
    allow_entries: bool,
) -> None:
    """Evaluate volume-breakout signals when the account is flat."""
    result = generate_signal(candles, config, state)
    apply_signal_to_state(state, result)

    if result.volume_ratio is not None:
        logging.info("VOLUME RATIO: %.2fx", result.volume_ratio)
        push_event("VOLUME", f"{result.volume_ratio:.2f}x")
    if result.breakout_high is not None:
        logging.info("BREAKOUT LEVEL: %.2f / %.2f", result.breakout_high, result.breakout_low or 0.0)
        push_event("BREAKOUT", f"HI {result.breakout_high:.2f} LO {result.breakout_low or 0:.2f}")

    if result.signal not in {"BUY", "SELL"}:
        logging.info("SIGNAL: NONE")
        logging.info("REASON: %s", WHY_NO_TRADE_LABELS.get(result.reason, result.reason))
        push_event("SIGNAL", f"NONE / {WHY_NO_TRADE_LABELS.get(result.reason, result.reason)}")
        compute_next_action(config, state)
        return

    logging.info("SIGNAL: %s BREAKOUT", "LONG" if result.signal == "BUY" else "SHORT")
    push_event("SIGNAL", state.last_signal)

    if not allow_entries:
        compute_next_action(config, state)
        return
    if state.current_position != "FLAT":
        compute_next_action(config, state)
        return

    allowed, reason = check_entry_conditions(config, state, result.signal)
    if not allowed:
        logging.info("RISK CHECK: FAILED (%s)", WHY_NO_TRADE_LABELS.get(reason, reason))
        state.why_no_trade = reason
        compute_next_action(config, state)
        return
    logging.info("RISK CHECK: PASSED")
    push_event("RISK", "PASSED")
    if is_live_mode(config):
        logging.info(
            "LIVE pre-trade chain: config → session → volume/breakout → position → "
            "pending → risk → signal → safety → order → verify"
        )
    state.next_action = f"{result.signal} SIGNAL — EXECUTING"
    if place_entry_order(dhan, config, state, result.signal, ltp):
        state.why_no_trade = "ENTRY_EXECUTED"
        state.engine_state = "POSITION_OPEN"
        state.last_signal_candle = result.candle_time
        state.last_consumed_side = result.signal
        state.last_consumed_level = (
            result.breakout_high if result.signal == "BUY" else result.breakout_low
        )
        push_event(
            "POSITION",
            f"{state.current_position} {state.position_quantity} @ {state.entry_price}",
        )
    else:
        logging.error("Entry was not confirmed. Not retrying blindly.")
        record_error(state, "Entry was not confirmed")
        state.engine_state = "NO_POSITION"
    compute_next_action(config, state)


def _handle_exit_hit(
    dhan,
    config: dict,
    state: BotState,
    hit: str,
    ltp: Optional[float],
) -> Optional[str]:
    """Exit on TP/SL/trail/hold and decide whether the process should stop."""
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
    stop_after_tp = bool(config["trading"].get("stop_bot_after_tp"))
    stop_after_sl = bool(config["trading"].get("stop_bot_after_sl"))
    if hit == "TAKE_PROFIT" and stop_after_tp:
        state.engine_state = "TRADE_COMPLETED"
        return hit
    if hit in {"STOP_LOSS", "TRAILING_STOP"} and stop_after_sl:
        state.engine_state = "TRADE_COMPLETED"
        return hit
    if hit == "MAX_HOLDING_TIME":
        state.engine_state = "NO_POSITION"
        return None
    state.engine_state = "NO_POSITION"
    return None


def run_strategy_cycle(
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
    if is_after_close_positions(config, now):
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
        logging.info("MARKET DATA UPDATED")
    monitor_position(dhan, config, state, ltp)

    if state.current_position != "FLAT":
        hit = monitor_tpsl(dhan, config, state, ltp)
        if hit:
            terminal = _handle_exit_hit(dhan, config, state, hit, ltp)
            if terminal:
                return cached_candles, terminal

    if state.current_position == "FLAT":
        blocked = check_risk_limits(config, state)
        if blocked:
            state.why_no_trade = blocked
            compute_next_action(config, state)
            if blocked in {"RISK_LIMIT_REACHED", "DAILY_PROFIT_TARGET", "MAX_CONSECUTIVE_LOSSES"}:
                if config["risk"].get("close_on_risk_limit"):
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
    if state.current_position == "FLAT" and allow_entries:
        process_volume_breakout(dhan, config, state, cached_candles, ltp, allow_entries)
    else:
        if cached_candles:
            preview = generate_signal(cached_candles, config, state)
            apply_signal_to_state(state, preview)
        compute_next_action(config, state)
    return cached_candles, None


def run_one_poll_cycle(
    dhan,
    config: dict,
    state: BotState,
    cached_candles: list[Candle],
) -> tuple[list[Candle], Optional[str]]:
    return run_strategy_cycle(dhan, config, state, cached_candles)


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
        cached_candles, reason = run_strategy_cycle(dhan, config, state, cached_candles)
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


def run_bot(dhan, config: dict, state: BotState) -> None:
    """Spec-named wrapper around the trading loop."""
    run_trading_loop(dhan, config, state)


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
    if reason in {"TAKE_PROFIT", "STOP_LOSS", "TRAILING_STOP", "MAX_HOLDING_TIME"}:
        state.last_exit_reason = reason

    close_positions = False
    if reason in {"TRADING_DAY_END", "SESSION_END"}:
        close_positions = bool(config["shutdown"].get("close_positions_on_session_end"))
    elif reason in {"TAKE_PROFIT", "STOP_LOSS", "TRAILING_STOP", "MAX_HOLDING_TIME"}:
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


def _confirm_live_if_requested(config: dict) -> None:
    if is_dry_run(config):
        return
    if not config["trading"].get("live_trading_confirmation"):
        return
    answer = input("Type YES to confirm live trading: ").strip()
    if answer != "YES":
        raise SafetyError("ERROR: Live trading confirmation was not YES.\nThe bot did not start.")


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
        _print_checklist(True, "Volume breakout strategy ready")
        logging.info("CONFIGURATION LOADED")
        logging.info("CONFIGURATION VALIDATED")
        logging.info("%s MODE", "DRY RUN" if is_dry_run(config) else "LIVE")

        consume_leftover_stop_file()
        if stop_requested():
            logging.info("Stop requested at startup. No orders were placed.")
            return 0

        _confirm_live_if_requested(config)
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
        run_bot(dhan, config, state)

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
