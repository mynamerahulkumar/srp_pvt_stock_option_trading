#!/usr/bin/env python3
"""Dhan VWAP Intraday Momentum Algo for NSE equity.

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

The strategy is long-only by default. A BUY is issued only when a
configurable number of VWAP / momentum / volume / trend / breakout
conditions pass on a completed candle. TP and SL are armed from the
actual fill price. A verified exit can stop the process when
``risk.stop_bot_after_exit`` is true.
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
READ_RETRY_ATTEMPTS = 3
READ_RETRY_SLEEP_SECONDS = 1.0
QUOTE_MIN_INTERVAL_SECONDS = 1.05
CLOSE_VERIFY_ATTEMPTS = 5

VALID_TIMEFRAMES = {"1", "5", "15", "25", "60", "DAY"}
VALID_ORDER_TYPES = {"MARKET", "LIMIT"}
VALID_LIMIT_MODES = {"OFFSET_PERCENT", "ABSOLUTE"}
VALID_PRODUCT_TYPES = {"CNC", "INTRADAY", "INTRA", "MARGIN", "MTF"}
EQUITY_PRODUCTS = {"CNC", "INTRADAY", "INTRA", "MARGIN", "MTF"}
DERIVATIVE_PRODUCTS = {"INTRADAY", "INTRA", "MARGIN"}
VALID_STARTUP_BEHAVIORS = {"WAIT_FOR_SIGNAL"}

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
    "INSUFFICIENT_CANDLES": "Not enough completed candles",
    "INVALID_MARKET_DATA": "Market data failed validation",
    "VWAP_UNAVAILABLE": "Session VWAP is not available yet",
    "SCORE_BELOW_MINIMUM": "Confirmation score is below the minimum",
    "PRICE_BELOW_VWAP": "Close is not above session VWAP",
    "VWAP_NOT_RISING": "VWAP is not flat-to-rising",
    "MOMENTUM_INSUFFICIENT": "Price momentum is below the threshold",
    "VOLUME_INSUFFICIENT": "Volume confirmation failed",
    "TREND_FAILED": "EMA trend confirmation failed",
    "BREAKOUT_FAILED": "VWAP breakout buffer was not cleared",
    "LONG_DISABLED": "Long entries are disabled in config",
    "SHORT_DISABLED": "Short entries are disabled in config",
    "POSITION_ALREADY_OPEN": "A position is already open",
    "MAX_TRADES_REACHED": "Maximum trades for today have been reached",
    "SESSION_NOT_STARTED": "Session has not started yet",
    "SESSION_ENDED": "Session has ended",
    "ENTRY_CUTOFF": "Entry cutoff has passed — no new trades",
    "WEEKEND": "Weekend — market is expected to be closed",
    "RISK_LIMIT_REACHED": "A daily risk limit has been reached",
    "COOLDOWN": "Cooldown between trades is still active",
    "PENDING_ORDER_EXISTS": "An order is already in flight",
    "STOP_REQUESTED": "A stop has been requested",
    "API_UNAVAILABLE": "Dhan API data is currently unavailable",
    "CONFIGURATION_ERROR": "Configuration is invalid",
    "BOT_DISABLED": "bot.enabled is false",
    "SCANNING": "Flat — scanning for VWAP momentum confirmation",
    "MONITORING_TP_SL": "Position open — monitoring take-profit / stop-loss",
    "BLOCKED_UNEXPECTED_POSITION": "Unexpected broker position blocked new entries",
    "ENTRY_EXECUTED": "Entry executed — switching to monitoring",
    "EXIT_EXECUTED": "Exit executed",
    "NONE": "No block",
}

# Set by signal handlers. Combined with the ``.stop`` file.
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
class ConditionResult:
    """One scored strategy condition."""

    name: str
    enabled: bool
    passed: bool
    detail: str = ""


@dataclass
class SignalResult:
    """Pure strategy output. No Dhan calls."""

    signal: str
    score: int
    total: int
    minimum: int
    reason: str
    conditions: list[ConditionResult] = field(default_factory=list)
    vwap: Optional[float] = None
    ema: Optional[float] = None
    momentum_percent: Optional[float] = None
    volume: Optional[float] = None
    average_volume: Optional[float] = None
    volume_ratio: Optional[float] = None
    close: Optional[float] = None


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
    trailing_stop_price: Optional[float] = None
    trailing_armed: bool = False
    highest_price: Optional[float] = None
    lowest_price: Optional[float] = None
    last_processed_candle: Optional[datetime] = None
    last_signal: str = "NO_TRADE"
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
    current_vwap: Optional[float] = None
    current_ema: Optional[float] = None
    current_momentum_percent: Optional[float] = None
    current_volume: Optional[float] = None
    current_avg_volume: Optional[float] = None
    current_volume_ratio: Optional[float] = None
    signal_score: int = 0
    signal_total: int = 0
    signal_minimum: int = 0
    condition_ticks: dict[str, str] = field(default_factory=dict)
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

def load_environment() -> None:
    """
    Load Dhan credentials from BASE_DIR/.env or the process environment.

    Why this function exists:
        The Dhan client cannot be created without a client id and access token.
        Loading them here means the rest of the program never hard-codes secrets.

    Safety:
        Never logs token values.
    """
    if ENV_FILE.exists():
        load_dotenv(ENV_FILE)
    else:
        logging.warning("No .env file found at %s. Checking process environment.", ENV_FILE)

    client_id = (os.environ.get("DHAN_CLIENT_ID") or "").strip()
    access_token = (os.environ.get("DHAN_ACCESS_TOKEN") or "").strip()
    if not client_id or not access_token:
        raise CredentialError(
            "ERROR: Dhan credentials are missing. Set "
            "DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN in .env.\nThe bot did not start."
        )


# ============================================================
# CONFIGURATION
# ============================================================

def parse_cli_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    """Parse lightweight CLI arguments. The only extra flag is --config."""
    parser = argparse.ArgumentParser(description="VWAP Intraday Momentum Algo for Dhan")
    parser.add_argument(
        "--config",
        default=str(BASE_DIR / "config.yaml"),
        help="Path to config.yaml (default: ./config.yaml)",
    )
    return parser.parse_args(argv)


def load_config(path: Optional[Path] = None) -> dict:
    """
    Load config.yaml.

    Purpose:
        Read every user-tunable setting from one YAML file.

    Returns:
        A dict. Raises ConfigError for a missing or invalid file.

    Safety:
        Does not contact Dhan. Does not place orders.
    """
    config_path = path or CONFIG_FILE
    if not config_path.exists():
        raise ConfigError(
            f"ERROR: config.yaml was not found at {config_path}.\nThe bot did not start."
        )
    try:
        with config_path.open("r", encoding="utf-8") as handle:
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


def _require_mapping(parent: dict, name: str, field_name: str) -> dict:
    value = parent.get(name)
    if not isinstance(value, dict):
        raise ConfigError(f"ERROR: {field_name} must be a mapping.\nThe bot did not start.")
    return value


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


def count_enabled_conditions(strategy: dict) -> int:
    """How many independently scored conditions are turned on."""
    flags = [
        bool(strategy["vwap"].get("enabled")),
        bool(strategy["momentum"].get("enabled")),
        bool(strategy["volume"].get("enabled")),
        bool(strategy["trend"].get("enabled")),
        bool(strategy["breakout"].get("enabled")),
    ]
    return sum(1 for flag in flags if flag)


def validate_config(config: dict) -> None:
    """
    Fail fast if any required setting is missing or inconsistent.

    Why this function exists:
        A live Dhan account will accept orders that a bad config would send.
        Validation happens before authentication and always before the first order.

    Returns:
        None. Mutates config in place with normalized types.
        Raises ConfigError on the first fatal problem.
    """
    bot = _require_section(config, "bot")
    instrument = _require_section(config, "instrument")
    strategy = _require_section(config, "strategy")
    risk = _require_section(config, "risk")
    execution = _require_section(config, "execution")
    hours = _require_section(config, "trading_hours")
    startup = _require_section(config, "startup")
    shutdown = _require_section(config, "shutdown")
    safety = _require_section(config, "safety")
    logging_cfg = _require_section(config, "logging")
    cli = _require_section(config, "cli")
    exit_cfg = config.get("exit")
    if not isinstance(exit_cfg, dict):
        exit_cfg = {}
        config["exit"] = exit_cfg

    if not str(bot.get("name") or "").strip():
        bot["name"] = "VWAP Intraday Momentum"
    bot["enabled"] = _as_bool(bot.get("enabled"), True)
    bot["dry_run"] = _as_bool(bot.get("dry_run"), True)
    bot["allow_live_trading"] = _as_bool(bot.get("allow_live_trading"), False)
    bot["polling_seconds"] = _as_positive_number(
        bot.get("polling_seconds", 5), "bot.polling_seconds"
    )
    bot["candle_lookback"] = int(
        _as_positive_number(bot.get("candle_lookback", 100), "bot.candle_lookback")
    )
    bot["order_wait_seconds"] = _as_positive_number(
        bot.get("order_wait_seconds", 90), "bot.order_wait_seconds"
    )
    bot["reconcile_every_cycles"] = max(
        1,
        int(
            _as_positive_number(
                bot.get("reconcile_every_cycles", 6),
                "bot.reconcile_every_cycles",
            )
        ),
    )

    security_id = str(instrument.get("security_id") or "").strip()
    symbol = str(instrument.get("symbol") or instrument.get("trading_symbol") or "").strip()
    if not security_id:
        raise ConfigError("ERROR: instrument.security_id is required.\nThe bot did not start.")
    if not symbol:
        raise ConfigError("ERROR: instrument.symbol is required.\nThe bot did not start.")
    instrument["security_id"] = security_id
    instrument["symbol"] = symbol

    exchange_segment = str(instrument.get("exchange_segment") or "").strip().upper()
    if not exchange_segment:
        raise ConfigError(
            "ERROR: instrument.exchange_segment is required.\nThe bot did not start."
        )
    instrument["exchange_segment"] = exchange_segment

    quantity = int(_as_positive_number(instrument.get("quantity"), "instrument.quantity"))
    if quantity != float(instrument.get("quantity")):
        raise ConfigError(
            "ERROR: instrument.quantity must be a whole number.\nThe bot did not start."
        )
    instrument["quantity"] = quantity

    product_type = str(
        instrument.get("product_type") or execution.get("product_type") or ""
    ).strip().upper()
    if product_type not in VALID_PRODUCT_TYPES:
        raise ConfigError(
            f"ERROR: instrument.product_type must be one of {sorted(VALID_PRODUCT_TYPES)}.\n"
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
    instrument["product_type"] = product_type
    execution["product_type"] = product_type
    instrument["tick_size"] = _as_positive_number(
        instrument.get("tick_size", 0.05), "instrument.tick_size"
    )
    instrument["instrument_type"] = str(
        instrument.get("instrument_type") or "EQUITY"
    ).strip().upper()

    timeframe = normalize_timeframe(strategy.get("timeframe", "5"))
    if timeframe not in VALID_TIMEFRAMES:
        raise ConfigError(
            "ERROR: strategy.timeframe must be one of "
            f"{sorted(VALID_TIMEFRAMES)} (or 5m / 15m / DAY).\nThe bot did not start."
        )
    strategy["timeframe"] = timeframe
    strategy["signal_on_closed_candle"] = _as_bool(
        strategy.get("signal_on_closed_candle"), True
    )

    vwap = _require_mapping(strategy, "vwap", "strategy.vwap")
    vwap["enabled"] = _as_bool(vwap.get("enabled"), True)
    vwap["slope_lookback"] = int(
        _as_positive_number(vwap.get("slope_lookback", 2), "strategy.vwap.slope_lookback")
    )
    strategy["vwap"] = vwap

    momentum = _require_mapping(strategy, "momentum", "strategy.momentum")
    momentum["enabled"] = _as_bool(momentum.get("enabled"), True)
    momentum["lookback_bars"] = int(
        _as_positive_number(momentum.get("lookback_bars", 3), "strategy.momentum.lookback_bars")
    )
    momentum["minimum_price_change_percent"] = _as_non_negative_number(
        momentum.get("minimum_price_change_percent", 0.20),
        "strategy.momentum.minimum_price_change_percent",
    )
    strategy["momentum"] = momentum

    volume = _require_mapping(strategy, "volume", "strategy.volume")
    volume["enabled"] = _as_bool(volume.get("enabled"), True)
    volume["volume_lookback"] = int(
        _as_positive_number(volume.get("volume_lookback", 20), "strategy.volume.volume_lookback")
    )
    volume["minimum_volume_multiplier"] = _as_positive_number(
        volume.get("minimum_volume_multiplier", 1.20),
        "strategy.volume.minimum_volume_multiplier",
    )
    strategy["volume"] = volume

    breakout = _require_mapping(strategy, "breakout", "strategy.breakout")
    breakout["enabled"] = _as_bool(breakout.get("enabled"), True)
    breakout["breakout_buffer_percent"] = _as_non_negative_number(
        breakout.get("breakout_buffer_percent", 0.05),
        "strategy.breakout.breakout_buffer_percent",
    )
    strategy["breakout"] = breakout

    trend = _require_mapping(strategy, "trend", "strategy.trend")
    trend["enabled"] = _as_bool(trend.get("enabled"), True)
    trend["ema_period"] = int(
        _as_positive_number(trend.get("ema_period", 20), "strategy.trend.ema_period")
    )
    trend["require_rising_ema"] = _as_bool(trend.get("require_rising_ema"), True)
    strategy["trend"] = trend

    confirmation = _require_mapping(strategy, "confirmation", "strategy.confirmation")
    confirmation["minimum_conditions"] = int(
        _as_positive_number(
            confirmation.get("minimum_conditions", 3),
            "strategy.confirmation.minimum_conditions",
        )
    )
    strategy["confirmation"] = confirmation

    enabled_count = count_enabled_conditions(strategy)
    if enabled_count < 1:
        raise ConfigError(
            "ERROR: at least one strategy condition must be enabled.\nThe bot did not start."
        )
    if confirmation["minimum_conditions"] > enabled_count:
        raise ConfigError(
            "ERROR: strategy.confirmation.minimum_conditions "
            f"({confirmation['minimum_conditions']}) is greater than the number of "
            f"enabled conditions ({enabled_count}).\nThe bot did not start."
        )

    needed = max(
        trend["ema_period"] + 2,
        volume["volume_lookback"] + 1,
        momentum["lookback_bars"] + 1,
        vwap["slope_lookback"] + 1,
        10,
    )
    if bot["candle_lookback"] < needed:
        raise ConfigError(
            f"ERROR: bot.candle_lookback ({bot['candle_lookback']}) is too small "
            f"for the configured indicators (need at least {needed}).\n"
            "The bot did not start."
        )

    vwap_fail = exit_cfg.get("vwap_failure_exit")
    if not isinstance(vwap_fail, dict):
        vwap_fail = {"enabled": False}
        exit_cfg["vwap_failure_exit"] = vwap_fail
    vwap_fail["enabled"] = _as_bool(vwap_fail.get("enabled"), False)

    mom_fail = exit_cfg.get("momentum_failure_exit")
    if not isinstance(mom_fail, dict):
        mom_fail = {"enabled": False}
        exit_cfg["momentum_failure_exit"] = mom_fail
    mom_fail["enabled"] = _as_bool(mom_fail.get("enabled"), False)

    risk["take_profit_percent"] = _as_positive_number(
        risk.get("take_profit_percent", risk.get("take_profit", 1.0)),
        "risk.take_profit_percent",
    )
    risk["stop_loss_percent"] = _as_positive_number(
        risk.get("stop_loss_percent", risk.get("stop_loss", 0.50)),
        "risk.stop_loss_percent",
    )
    risk["take_profit"] = risk["take_profit_percent"]
    risk["stop_loss"] = risk["stop_loss_percent"]
    risk["stop_loss_type"] = "PERCENT"
    risk["take_profit_type"] = "PERCENT"
    risk["tp_sl_mode"] = "PERCENT"

    trail = risk.get("trailing_stop")
    if not isinstance(trail, dict):
        trail = {
            "enabled": _as_bool(risk.get("trailing_stop_enabled"), False),
            "activation_percent": risk.get("trailing_stop_activation", 0.50),
            "trail_percent": risk.get("trailing_stop", 0.25),
        }
        risk["trailing_stop"] = trail
    trail["enabled"] = _as_bool(trail.get("enabled"), False)
    trail["activation_percent"] = _as_non_negative_number(
        trail.get("activation_percent", 0.50), "risk.trailing_stop.activation_percent"
    )
    trail["trail_percent"] = _as_non_negative_number(
        trail.get("trail_percent", 0.25), "risk.trailing_stop.trail_percent"
    )
    if trail["enabled"] and trail["trail_percent"] <= 0:
        raise ConfigError(
            "ERROR: risk.trailing_stop.trail_percent must be > 0 when trailing is enabled.\n"
            "The bot did not start."
        )
    risk["trailing_stop_enabled"] = trail["enabled"]
    risk["trailing_stop_activation"] = trail["activation_percent"]
    risk["trailing_stop_percent"] = trail["trail_percent"]

    risk["max_daily_trades"] = int(
        _as_non_negative_number(
            risk.get("max_daily_trades", risk.get("max_trades_per_day", 5)),
            "risk.max_daily_trades",
        )
    )
    risk["max_trades_per_day"] = risk["max_daily_trades"]
    risk["max_open_positions"] = int(
        _as_positive_number(risk.get("max_open_positions", 1), "risk.max_open_positions")
    )
    risk["max_daily_loss"] = _as_non_negative_number(
        risk.get("max_daily_loss", 0), "risk.max_daily_loss"
    )
    risk["max_daily_profit"] = _as_non_negative_number(
        risk.get("max_daily_profit", 0), "risk.max_daily_profit"
    )
    risk["estimated_cost_per_trade"] = _as_non_negative_number(
        risk.get("estimated_cost_per_trade", 0), "risk.estimated_cost_per_trade"
    )
    risk["close_on_risk_limit"] = _as_bool(risk.get("close_on_risk_limit"), False)
    risk["stop_bot_after_exit"] = _as_bool(risk.get("stop_bot_after_exit"), True)

    order_type = str(execution.get("order_type") or "MARKET").strip().upper()
    if order_type not in VALID_ORDER_TYPES:
        raise ConfigError(
            "ERROR: execution.order_type must be MARKET or LIMIT.\nThe bot did not start."
        )
    execution["order_type"] = order_type
    execution["validity"] = str(execution.get("validity") or "DAY").strip().upper() or "DAY"
    enable_long = execution.get("enable_long", execution.get("allow_long", True))
    enable_short = execution.get("enable_short", execution.get("allow_short", False))
    execution["enable_long"] = _as_bool(enable_long, True)
    execution["enable_short"] = _as_bool(enable_short, False)
    execution["allow_long"] = execution["enable_long"]
    execution["allow_short"] = execution["enable_short"]
    if not execution["enable_long"] and not execution["enable_short"]:
        raise ConfigError(
            "ERROR: at least one of execution.enable_long or enable_short must be true.\n"
            "The bot did not start."
        )
    execution["prevent_duplicate_orders"] = _as_bool(
        execution.get("prevent_duplicate_orders"), True
    )
    execution["cooldown_seconds"] = _as_non_negative_number(
        execution.get("cooldown_seconds", 0), "execution.cooldown_seconds"
    )
    limit_mode = str(execution.get("limit_price_mode") or "OFFSET_PERCENT").strip().upper()
    if limit_mode not in VALID_LIMIT_MODES:
        raise ConfigError(
            "ERROR: execution.limit_price_mode must be OFFSET_PERCENT or ABSOLUTE.\n"
            "The bot did not start."
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

    hours["enabled"] = _as_bool(hours.get("enabled"), False)
    hours["timezone"] = str(hours.get("timezone") or "Asia/Kolkata").strip()
    start_h, start_m = _parse_hhmm(hours.get("start_time", "09:20"), "trading_hours.start_time")
    entry_h, entry_m = _parse_hhmm(
        hours.get("stop_entry_time", "15:00"), "trading_hours.stop_entry_time"
    )
    close_h, close_m = _parse_hhmm(
        hours.get("close_positions_time", "15:15"), "trading_hours.close_positions_time"
    )
    if hours["enabled"]:
        if (start_h, start_m) >= (entry_h, entry_m):
            raise ConfigError(
                "ERROR: trading_hours.start_time must be before stop_entry_time.\n"
                "The bot did not start."
            )
        if (entry_h, entry_m) > (close_h, close_m):
            raise ConfigError(
                "ERROR: trading_hours.stop_entry_time must be at or before close_positions_time.\n"
                "The bot did not start."
            )

    behavior = str(startup.get("behavior") or "WAIT_FOR_SIGNAL").strip().upper()
    if behavior not in VALID_STARTUP_BEHAVIORS:
        raise ConfigError(
            "ERROR: startup.behavior must be WAIT_FOR_SIGNAL.\nThe bot did not start."
        )
    startup["behavior"] = behavior
    startup["wait_for_start_time"] = _as_bool(startup.get("wait_for_start_time"), True)
    startup["reconcile_existing_positions"] = _as_bool(
        startup.get("reconcile_existing_positions"), True
    )
    startup["manage_existing_position"] = _as_bool(
        startup.get("manage_existing_position"), True
    )

    position_management = config.get("position_management")
    if not isinstance(position_management, dict):
        position_management = {}
        config["position_management"] = position_management
    position_management["manage_only_bot_positions"] = _as_bool(
        position_management.get("manage_only_bot_positions"), True
    )

    shutdown["close_positions_on_manual_stop"] = _as_bool(
        shutdown.get("close_positions_on_manual_stop"), True
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
    shutdown["closed_market_confirm_polls"] = int(
        _as_non_negative_number(
            shutdown.get("closed_market_confirm_polls", 3),
            "shutdown.closed_market_confirm_polls",
        )
    )

    safety["manage_only_configured_symbol"] = _as_bool(
        safety.get(
            "manage_only_configured_symbol",
            position_management.get("manage_only_bot_positions", True),
        ),
        True,
    )
    safety["require_flat_before_entry"] = _as_bool(
        safety.get("require_flat_before_entry"), True
    )
    safety["block_if_unexpected_position"] = _as_bool(
        safety.get("block_if_unexpected_position"), True
    )
    safety["require_confirmation_for_live_trading"] = _as_bool(
        safety.get("require_confirmation_for_live_trading"), False
    )

    logging_cfg["level"] = str(logging_cfg.get("level") or "INFO").strip().upper()
    cli["enabled"] = _as_bool(cli.get("enabled"), True)
    cli["refresh_seconds"] = _as_positive_number(
        cli.get("refresh_seconds", 1), "cli.refresh_seconds"
    )
    cli["show_indicators"] = _as_bool(cli.get("show_indicators"), True)
    cli["show_signal"] = _as_bool(cli.get("show_signal"), True)
    cli["show_orders"] = _as_bool(cli.get("show_orders"), True)
    cli["event_history_size"] = int(
        _as_positive_number(cli.get("event_history_size", 8), "cli.event_history_size")
    )


def is_dry_run(config: dict) -> bool:
    """True when live place_order must never be called."""
    return not is_live_mode(config)


def is_live_mode(config: dict) -> bool:
    bot = config.get("bot", {})
    return (not bool(bot.get("dry_run", True))) and bool(bot.get("allow_live_trading", False))


def validate_safety_config(config: dict) -> None:
    """
    Live trading requires dry_run=false AND allow_live_trading=true.

    Why this function exists:
        A single flag is too easy to flip by accident on a 1 GB VM that can
        place real orders. The second lock must be set deliberately.
    """
    bot = config.get("bot", {})
    dry_run = bool(bot.get("dry_run", True))
    if dry_run:
        return
    if not bot.get("allow_live_trading"):
        raise SafetyError(
            "ERROR: Live trading is not fully unlocked.\n"
            "Set bot.dry_run: false and bot.allow_live_trading: true.\n"
            "The bot did not start."
        )
    if config.get("safety", {}).get("require_confirmation_for_live_trading"):
        CONSOLE.print(
            "[bold red]LIVE TRADING is unlocked. Type YES to continue.[/bold red]"
        )
        try:
            answer = input("Confirm live trading (YES): ").strip()
        except EOFError:
            answer = ""
        if answer != "YES":
            raise SafetyError(
                "ERROR: Live trading confirmation was not YES.\nThe bot did not start."
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
    level_name = str(config.get("logging", {}).get("level") or "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    root = logging.getLogger()
    root.setLevel(level)
    if not any(isinstance(handler, logging.StreamHandler) for handler in root.handlers):
        stream = logging.StreamHandler(sys.stderr)
        stream.setFormatter(
            logging.Formatter(
                "%(asctime)s | %(levelname)s | %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        root.addHandler(stream)
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


def stop_requested() -> bool:
    return _shutdown_requested or STOP_FILE.exists()


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
    name = str(config.get("trading_hours", {}).get("timezone") or "Asia/Kolkata")
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


def interval_minutes(timeframe: str) -> Optional[int]:
    if timeframe == "DAY":
        return None
    return int(timeframe)


def _session_clock(config: dict, now: datetime, field_name: str) -> datetime:
    hour, minute = _parse_hhmm(
        config["trading_hours"].get(field_name), f"trading_hours.{field_name}"
    )
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
    return current < _session_clock(config, current, "start_time")


def is_after_stop_entry(config: dict, now: Optional[datetime] = None) -> bool:
    if not is_session_enabled(config):
        return False
    current = now or now_in_session_tz(config)
    if is_weekend(config, current):
        return True
    return current >= _session_clock(config, current, "stop_entry_time")


def is_after_close_positions(config: dict, now: Optional[datetime] = None) -> bool:
    """True on a weekday at or after flatten time. Weekends do not auto-flatten."""
    if not is_session_enabled(config):
        return False
    current = now or now_in_session_tz(config)
    if is_weekend(config, current):
        return False
    return current >= _session_clock(config, current, "close_positions_time")


def closed_market_confirm_polls(config: dict) -> int:
    """How many post-close LTP/indicator polls to run before TRADING_DAY_END."""
    return int(config.get("shutdown", {}).get("closed_market_confirm_polls") or 0)


def check_trading_window(config: dict, now: Optional[datetime] = None) -> tuple[bool, str]:
    """
    Decide whether new entries are allowed right now.

    Returns:
        (allowed, reason_code). Never places an order.
    """
    if not config.get("bot", {}).get("enabled", True):
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
    """Sleep in short slices so stop.py / signals are noticed quickly.

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
        return "—"
    seconds = max(0, int((now - started_at).total_seconds()))
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def format_inr(value: Optional[float]) -> str:
    if value is None:
        return "—"
    return f"₹{value:,.2f}"


# ============================================================
# DHAN CLIENT AND RESPONSE HELPERS
# ============================================================

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
        A bad OHLC row can invent a fake VWAP breakout. Unreliable data
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


def get_market_data(dhan, config: dict) -> list[Candle]:
    """
    Fetch required candle history for VWAP, EMA, momentum, and volume.

    Why this function exists:
        Signals must be computed on closed candles. Fetching unbounded
        history would waste RAM on a 1 GB VM.

    Returns:
        Completed candles only, oldest-first. Empty list on failure so the
        loop can wait without placing an order.
    """
    instrument = config["instrument"]
    strategy = config["strategy"]
    bot = config["bot"]
    timeframe = strategy["timeframe"]
    lookback = int(bot["candle_lookback"])
    tzinfo = session_timezone(config)
    now = now_in_session_tz(config)
    days = _lookback_calendar_days(timeframe, lookback)
    from_date = (now.date() - timedelta(days=days)).strftime("%Y-%m-%d")
    to_date = now.date().strftime("%Y-%m-%d")
    security_id = str(instrument["security_id"])
    exchange_segment = _map_exchange_segment(instrument["exchange_segment"])
    instrument_type = instrument["instrument_type"]

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
    completed = validate_candles(
        [item for item in candles if _is_candle_complete(item, timeframe, now)]
    )
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
# INDICATORS — SESSION VWAP, EMA, MOMENTUM, VOLUME
# ============================================================

def typical_price(candle: Candle) -> float:
    """(High + Low + Close) / 3. Standard representative price for VWAP."""
    return (candle.high + candle.low + candle.close) / 3.0


def calculate_vwap(
    candles: list[Candle],
    session_date,
) -> list[Optional[float]]:
    """
    Session VWAP from completed candles. Resets on a new calendar date.

    Mathematics:
        typical = (high + low + close) / 3
        VWAP[t] = sum(typical * volume) / sum(volume)  for bars on session_date

    Why this function exists:
        Intraday VWAP is the volume-weighted average traded price of the
        current session. Using yesterday's bars would turn it into a
        multi-day average and break the strategy.

    Returns:
        One value per input candle. Non-session bars are None. If
        cumulative session volume is 0, the value stays None.
    """
    result: list[Optional[float]] = [None] * len(candles)
    cumulative_pv = 0.0
    cumulative_volume = 0.0
    for index, candle in enumerate(candles):
        if candle.timestamp.date() != session_date:
            continue
        typical = typical_price(candle)
        volume = candle.volume if candle.volume > 0 else 0.0
        cumulative_pv += typical * volume
        cumulative_volume += volume
        if cumulative_volume > 0:
            result[index] = cumulative_pv / cumulative_volume
    return result


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


def calculate_momentum(closes: list[float], lookback: int) -> Optional[float]:
    """
    Percent change from close N bars ago to the latest close.

    Mathematics:
        momentum % = (close[t] - close[t-N]) / close[t-N] * 100

    Returns:
        Percent, or None if there are not enough bars or the reference
        close is not positive.
    """
    if lookback <= 0 or len(closes) <= lookback:
        return None
    previous = closes[-(lookback + 1)]
    current = closes[-1]
    if previous <= 0:
        return None
    return ((current - previous) / previous) * 100.0


def calculate_volume_ratio(
    volumes: list[float],
    lookback: int,
) -> tuple[Optional[float], Optional[float], Optional[float]]:
    """
    Current volume versus the simple average of the previous ``lookback`` bars.

    Returns:
        (current_volume, average_volume, ratio). Average excludes the
        current bar so a spike is compared against recent history, not
        against itself.
    """
    if lookback <= 0 or len(volumes) < lookback + 1:
        return (volumes[-1] if volumes else None), None, None
    current = volumes[-1]
    window = volumes[-(lookback + 1) : -1]
    if not window:
        return current, None, None
    average = sum(window) / len(window)
    if average <= 0:
        return current, average, None
    return current, average, current / average


def evaluate_vwap_condition(
    close: float,
    vwap: Optional[float],
    vwap_series: list[Optional[float]],
    slope_lookback: int,
) -> ConditionResult:
    """
    Price above session VWAP and VWAP flat-to-rising.

    Why this function exists:
        The strategy only wants longs when buyers are accepting prices
        above the session's volume-weighted mean and that mean is not
        rolling over.
    """
    if vwap is None or vwap <= 0 or close <= 0:
        return ConditionResult("VWAP", True, False, "VWAP unavailable")
    above = close > vwap
    rising = True
    if slope_lookback > 0:
        session_values = [value for value in vwap_series if value is not None]
        if len(session_values) <= slope_lookback:
            return ConditionResult("VWAP", True, False, "VWAP slope warmup")
        previous = session_values[-(slope_lookback + 1)]
        rising = vwap >= previous
    passed = above and rising
    detail = f"close {close:.2f} vs VWAP {vwap:.2f}; rising={rising}"
    return ConditionResult("VWAP", True, passed, detail)


def evaluate_momentum_condition(
    momentum_percent: Optional[float],
    minimum_percent: float,
) -> ConditionResult:
    """Positive price change over the configured lookback must clear the floor."""
    if momentum_percent is None:
        return ConditionResult("Momentum", True, False, "momentum unavailable")
    passed = momentum_percent >= minimum_percent
    return ConditionResult(
        "Momentum",
        True,
        passed,
        f"{momentum_percent:+.3f}% vs min {minimum_percent:.3f}%",
    )


def evaluate_volume_condition(
    volume_ratio: Optional[float],
    minimum_multiplier: float,
) -> ConditionResult:
    """Current volume must exceed average volume times the multiplier."""
    if volume_ratio is None:
        return ConditionResult("Volume", True, False, "volume ratio unavailable")
    passed = volume_ratio > minimum_multiplier
    return ConditionResult(
        "Volume",
        True,
        passed,
        f"ratio {volume_ratio:.2f} vs min {minimum_multiplier:.2f}",
    )


def evaluate_trend_condition(
    close: float,
    ema: Optional[float],
    previous_ema: Optional[float],
    require_rising: bool,
) -> ConditionResult:
    """Close above EMA, optionally with a rising EMA slope."""
    if ema is None or ema <= 0 or close <= 0:
        return ConditionResult("EMA Trend", True, False, "EMA unavailable")
    above = close > ema
    rising = True
    if require_rising:
        if previous_ema is None:
            return ConditionResult("EMA Trend", True, False, "EMA slope warmup")
        rising = ema > previous_ema
    passed = above and rising
    return ConditionResult(
        "EMA Trend",
        True,
        passed,
        f"close {close:.2f} vs EMA {ema:.2f}; rising={rising}",
    )


def evaluate_breakout_condition(
    close: float,
    vwap: Optional[float],
    buffer_percent: float,
) -> ConditionResult:
    """Close must clear VWAP by the configured buffer percent."""
    if vwap is None or vwap <= 0 or close <= 0:
        return ConditionResult("Breakout", True, False, "VWAP unavailable")
    threshold = vwap * (1.0 + buffer_percent / 100.0)
    passed = close > threshold
    return ConditionResult(
        "Breakout",
        True,
        passed,
        f"close {close:.2f} vs {threshold:.2f} (VWAP+{buffer_percent:.3f}%)",
    )


def apply_signal_to_state(state: BotState, result: SignalResult) -> None:
    """Copy pure indicator output into the dashboard/runtime state."""
    state.last_signal = result.signal
    state.signal_score = result.score
    state.signal_total = result.total
    state.signal_minimum = result.minimum
    state.current_vwap = result.vwap
    state.current_ema = result.ema
    state.current_momentum_percent = result.momentum_percent
    state.current_volume = result.volume
    state.current_avg_volume = result.average_volume
    state.current_volume_ratio = result.volume_ratio
    state.confirmation_status = f"{result.score}/{result.total}"
    state.condition_ticks = {
        item.name: ("✓" if item.passed else "✗") if item.enabled else "—"
        for item in result.conditions
    }
    ticks = "  ".join(
        f"{item.name} {'✓' if item.passed else '✗'}"
        for item in result.conditions
        if item.enabled
    )
    state.strategy_condition = ticks or result.reason
    if result.signal == "BUY":
        state.why_no_trade = "NONE"
    else:
        state.why_no_trade = result.reason


def generate_signal(candles: list[Candle], config: dict, state: BotState) -> SignalResult:
    """
    Score enabled VWAP-momentum conditions on the last completed candle.

    Why this function exists:
        Entry decisions must be explainable: every poll shows which
        conditions passed and whether the score met the minimum.
        This function never talks to Dhan.

    Returns:
        SignalResult with BUY or NO_TRADE plus a reason code.
    """
    strategy = config["strategy"]
    session_date = now_in_session_tz(config).date()
    empty = SignalResult(
        signal="NO_TRADE",
        score=0,
        total=0,
        minimum=int(strategy["confirmation"]["minimum_conditions"]),
        reason="WAITING_FOR_MARKET_DATA",
    )
    if not candles:
        apply_signal_to_state(state, empty)
        return empty

    latest = candles[-1]
    if latest.close <= 0:
        empty.reason = "INVALID_MARKET_DATA"
        apply_signal_to_state(state, empty)
        return empty

    vwap_series = calculate_vwap(candles, session_date)
    closes = [item.close for item in candles]
    volumes = [item.volume for item in candles]
    ema_period = int(strategy["trend"]["ema_period"])
    ema_series = calculate_ema(closes, ema_period)
    momentum_percent = calculate_momentum(closes, int(strategy["momentum"]["lookback_bars"]))
    current_volume, average_volume, volume_ratio = calculate_volume_ratio(
        volumes, int(strategy["volume"]["volume_lookback"])
    )
    current_vwap = vwap_series[-1]
    current_ema = ema_series[-1]
    previous_ema = ema_series[-2] if len(ema_series) >= 2 else None

    conditions: list[ConditionResult] = []
    if strategy["vwap"]["enabled"]:
        conditions.append(
            evaluate_vwap_condition(
                latest.close,
                current_vwap,
                vwap_series,
                int(strategy["vwap"]["slope_lookback"]),
            )
        )
    if strategy["momentum"]["enabled"]:
        conditions.append(
            evaluate_momentum_condition(
                momentum_percent,
                float(strategy["momentum"]["minimum_price_change_percent"]),
            )
        )
    if strategy["volume"]["enabled"]:
        conditions.append(
            evaluate_volume_condition(
                volume_ratio,
                float(strategy["volume"]["minimum_volume_multiplier"]),
            )
        )
    if strategy["trend"]["enabled"]:
        conditions.append(
            evaluate_trend_condition(
                latest.close,
                current_ema,
                previous_ema,
                bool(strategy["trend"]["require_rising_ema"]),
            )
        )
    if strategy["breakout"]["enabled"]:
        conditions.append(
            evaluate_breakout_condition(
                latest.close,
                current_vwap,
                float(strategy["breakout"]["breakout_buffer_percent"]),
            )
        )

    score = sum(1 for item in conditions if item.passed)
    total = len(conditions)
    minimum = int(strategy["confirmation"]["minimum_conditions"])

    reason = "SCORE_BELOW_MINIMUM"
    failed = [item for item in conditions if not item.passed]
    if current_vwap is None:
        reason = "VWAP_UNAVAILABLE"
    elif failed:
        name_to_reason = {
            "VWAP": "PRICE_BELOW_VWAP"
            if "above" in failed[0].detail or "vs VWAP" in failed[0].detail
            else "VWAP_NOT_RISING",
            "Momentum": "MOMENTUM_INSUFFICIENT",
            "Volume": "VOLUME_INSUFFICIENT",
            "EMA Trend": "TREND_FAILED",
            "Breakout": "BREAKOUT_FAILED",
        }
        if score < minimum:
            reason = name_to_reason.get(failed[0].name, "SCORE_BELOW_MINIMUM")
        else:
            reason = "NONE"
    elif score < minimum:
        reason = "SCORE_BELOW_MINIMUM"
    else:
        reason = "NONE"

    signal = "BUY" if score >= minimum and reason in {"NONE"} and current_vwap is not None else "NO_TRADE"
    if signal == "NO_TRADE" and reason == "NONE":
        reason = "SCORE_BELOW_MINIMUM"

    result = SignalResult(
        signal=signal,
        score=score,
        total=total,
        minimum=minimum,
        reason=reason if signal == "NO_TRADE" else "NONE",
        conditions=conditions,
        vwap=current_vwap,
        ema=current_ema,
        momentum_percent=momentum_percent,
        volume=current_volume,
        average_volume=average_volume,
        volume_ratio=volume_ratio,
        close=latest.close,
    )
    apply_signal_to_state(state, result)
    logging.info("Strategy evaluation started")
    if current_vwap is not None:
        logging.info("VWAP = %.2f", current_vwap)
    logging.info("Price = %.2f", latest.close)
    if momentum_percent is not None:
        logging.info("Momentum = %+.2f%%", momentum_percent)
    if volume_ratio is not None:
        logging.info("Volume ratio = %.2f", volume_ratio)
    if current_ema is not None:
        logging.info("EMA trend = %s", "bullish" if latest.close > current_ema else "bearish")
    logging.info("Signal score = %s/%s (minimum %s)", score, total, minimum)
    for item in conditions:
        mark = "PASS" if item.passed else "FAIL"
        logging.info("Condition %s = %s (%s)", item.name, mark, item.detail)
    if signal == "BUY":
        logging.info("BUY signal generated")
    else:
        logging.info("NO TRADE (%s)", WHY_NO_TRADE_LABELS.get(result.reason, result.reason))
    return result


# ============================================================
# POSITIONS
# ============================================================

def get_positions(dhan) -> Optional[list[dict]]:
    last_error = None
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
                inner = data.get("positions") or data.get("data")
                if isinstance(inner, list):
                    return [row for row in inner if isinstance(row, dict)]
                return [data]
            return []
        except Exception as exc:
            last_error = exc
            if attempt < READ_RETRY_ATTEMPTS:
                time.sleep(READ_RETRY_SLEEP_SECONDS)
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


def get_open_positions(dhan) -> Optional[list[dict]]:
    positions = get_positions(dhan)
    if positions is None:
        return None
    return [row for row in positions if _position_net_qty(row) != 0]


def get_open_position(dhan, config: dict) -> tuple[bool, Optional[dict]]:
    """Return (read_ok, matching open row). read_ok False means do not assume flat."""
    positions = get_positions(dhan)
    if positions is None:
        return False, None
    target = str(config["instrument"]["security_id"])
    product = str(config["instrument"]["product_type"]).upper()
    for row in positions:
        if _position_security_id(row) != target:
            continue
        row_product = _position_product(row)
        if row_product and row_product not in {product, "INTRA" if product == "INTRADAY" else product}:
            if row_product != product and not (
                {row_product, product} <= {"INTRA", "INTRADAY"}
            ):
                continue
        if _position_net_qty(row) != 0:
            return True, row
    return True, None


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
    """Refresh LTP-derived P&L and trailing extrema for the open position."""
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
        response = dhan.ticker_data({segment: [int(security_id) if str(security_id).isdigit() else security_id]})
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
    ltp = _extract_ltp(response, str(security_id))
    if ltp and ltp > 0:
        _last_good_ltp = ltp
        return ltp
    return _last_good_ltp


# ============================================================
# TAKE PROFIT / STOP LOSS / TRAILING
# ============================================================

def calculate_stop_loss(entry_price: float, side: str, percent: float) -> float:
    """
    Fixed stop-loss from the actual fill.

    LONG:  E * (1 - SL% / 100)
    SHORT: E * (1 + SL% / 100)
    """
    if side.upper() == "LONG":
        return entry_price * (1.0 - percent / 100.0)
    return entry_price * (1.0 + percent / 100.0)


def calculate_take_profit(entry_price: float, side: str, percent: float) -> float:
    """
    Fixed take-profit from the actual fill.

    LONG:  E * (1 + TP% / 100)
    SHORT: E * (1 - TP% / 100)
    """
    if side.upper() == "LONG":
        return entry_price * (1.0 + percent / 100.0)
    return entry_price * (1.0 - percent / 100.0)


def calculate_exit_levels(
    entry_price: float,
    side: str,
    config: dict,
) -> tuple[float, float]:
    """Reusable TP/SL pair rounded to tick size."""
    risk = config["risk"]
    tick = float(config["instrument"]["tick_size"])
    sl = calculate_stop_loss(entry_price, side, float(risk["stop_loss_percent"]))
    tp = calculate_take_profit(entry_price, side, float(risk["take_profit_percent"]))
    return round_to_tick(sl, tick), round_to_tick(tp, tick)


def arm_risk_levels(state: BotState, config: dict, entry_price: float, side: str) -> None:
    """
    Compute and store TP/SL from the actual fill price.

    Software-polled TP/SL is not a guaranteed fill at the exact price.
    """
    sl, tp = calculate_exit_levels(entry_price, side, config)
    state.entry_price = entry_price
    state.stop_loss_price = sl
    state.take_profit_price = tp
    state.highest_price = entry_price
    state.lowest_price = entry_price
    state.trailing_stop_price = None
    state.trailing_armed = False
    update_trailing_stop(state, config)
    logging.info("TP = %.2f", tp)
    logging.info("SL = %.2f", sl)
    logging.info(
        "TP ARMED / SL ARMED | entry=%.2f side=%s TP=%.2f SL=%.2f",
        entry_price,
        side,
        tp,
        sl,
    )


def update_trailing_stop(state: BotState, config: dict) -> None:
    """
    Arm a trailing stop only after activation_percent is reached.

    LONG: after highest >= entry * (1 + activation%), trail = highest * (1 - trail%)
    SHORT: after lowest <= entry * (1 - activation%), trail = lowest * (1 + trail%)
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
    trail = float(trail_cfg.get("trail_percent") or 0)
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
            state.trailing_stop_price = round_to_tick(raw, tick)
        return
    if state.current_position == "SHORT" and state.lowest_price:
        move = ((entry - state.lowest_price) / entry) * 100.0
        if move >= activation:
            state.trailing_armed = True
            raw = state.lowest_price * (1.0 + trail / 100.0)
            state.trailing_stop_price = round_to_tick(raw, tick)


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
            payload = _first_dict(_unwrap_dhan_data(response)) or {}
            return _status_from_payload(payload, requested_quantity)
        except Exception as exc:
            last_error = exc
            if attempt < READ_RETRY_ATTEMPTS:
                time.sleep(READ_RETRY_SLEEP_SECONDS)
    raise RuntimeError(f"Order status read failed: {last_error}")


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
    orders = get_order_list(dhan)
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
        logging.info(
            "Trade record | ts=%s symbol=%s side=%s qty=%s entry=%s exit=%s "
            "tp=%s sl=%s reason=%s gross_pnl=%.2f",
            now.isoformat(),
            config["instrument"]["symbol"],
            state.current_position,
            state.position_quantity or quantity,
            state.entry_price,
            fill_price or state.last_ltp,
            state.take_profit_price,
            state.stop_loss_price,
            state.last_exit_reason,
            pnl,
        )
        _mark_flat(state)
        logging.info("POSITION CLOSED. Local state is FLAT. Realized P&L this exit ≈ %.2f", pnl)
        return
    position_side = "LONG" if side.upper() == "BUY" else "SHORT"
    state.current_position = position_side
    state.position_quantity = quantity
    state.trade_direction = position_side
    state.last_entry_signal = "BUY" if position_side == "LONG" else "SELL"
    state.position_opened_at = now
    state.trades_today += 1
    price = fill_price if fill_price > 0 else state.entry_price or state.last_ltp or 0.0
    if price > 0:
        arm_risk_levels(state, config, price, position_side)
        logging.info("Entry filled at ₹%.2f", price)
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

    tag = f"V{uuid.uuid4().hex[:12]}"
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

    poll_interval = float(config["bot"]["polling_seconds"])
    max_wait = float(config["bot"]["order_wait_seconds"])
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
    logging.info("Entry order submitted")
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
    """Close the open position for a named reason."""
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
    only_ours = bool(config["safety"].get("manage_only_configured_symbol", True)) or bool(
        config.get("position_management", {}).get("manage_only_bot_positions", True)
    )
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

    ltp = get_ltp(
        dhan,
        str(config["instrument"]["security_id"]),
        str(config["instrument"]["exchange_segment"]),
    )

    for _attempt in range(1, CLOSE_VERIFY_ATTEMPTS + 1):
        open_rows = get_open_positions(dhan)
        if open_rows is None:
            logging.error("Could not read positions while flattening. Will retry the read.")
            if interruptible_sleep(float(config["bot"]["polling_seconds"])):
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
        if interruptible_sleep(float(config["bot"]["polling_seconds"])):
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
    if avg <= 0:
        logging.error(
            "Existing position found but average price is missing. "
            "Failing safe — no new entry will be placed. Manage it manually."
        )
        state.extra["unmanaged_existing"] = True
        state.why_no_trade = "BLOCKED_UNEXPECTED_POSITION"
        return
    logging.info("Adopting existing %s qty=%s avg=%.2f for TP/SL monitoring.", side, qty, avg)
    apply_broker_position(state, config, ours)
    state.adopted_existing = True
    if state.trades_today < 1:
        state.trades_today = 1
    state.engine_state = "POSITION_OPEN"


# ============================================================
# RISK / TRADE VALIDATION
# ============================================================

def daily_risk_blocked(config: dict, state: BotState) -> Optional[str]:
    risk = config["risk"]
    max_loss = float(risk.get("max_daily_loss") or 0)
    max_profit = float(risk.get("max_daily_profit") or 0)
    if max_loss > 0 and state.daily_realized_pnl <= -max_loss:
        return "RISK_LIMIT_REACHED"
    if max_profit > 0 and state.daily_realized_pnl >= max_profit:
        return "RISK_LIMIT_REACHED"
    max_trades = int(risk.get("max_daily_trades") or 0)
    if max_trades > 0 and state.trades_today >= max_trades:
        return "MAX_TRADES_REACHED"
    return None


def check_risk_limits(config: dict, state: BotState) -> Optional[str]:
    """Pure daily-risk check used by validate_trade and the loop."""
    return daily_risk_blocked(config, state)


def cooldown_active(config: dict, state: BotState) -> bool:
    seconds = float(config["execution"].get("cooldown_seconds") or 0)
    if seconds <= 0 or state.last_trade_time is None:
        return False
    elapsed = (now_in_session_tz(config) - state.last_trade_time).total_seconds()
    return elapsed < seconds


def validate_trade(
    config: dict,
    state: BotState,
    signal: str,
) -> tuple[bool, str]:
    """
    Verify that a BUY signal is allowed to become an entry.

    Session, direction flags, open position, pending orders, daily
    limits, and stop requests can all veto a signal without the
    signal function knowing about Dhan.
    """
    if stop_requested():
        return False, "STOP_REQUESTED"
    if signal != "BUY":
        return False, state.why_no_trade or "SCANNING"
    allowed, window_reason = check_trading_window(config)
    if not allowed:
        return False, window_reason
    if not is_market_expected_open(config):
        return False, "WEEKEND" if is_weekend(config) else "SESSION_NOT_STARTED"
    if state.order_in_flight or state.pending_order_id:
        return False, "PENDING_ORDER_EXISTS"
    if config["execution"].get("prevent_duplicate_orders", True):
        if state.current_position != "FLAT":
            return False, "POSITION_ALREADY_OPEN"
        if state.extra.get("traded_candle") == state.last_processed_candle:
            return False, "POSITION_ALREADY_OPEN"
    if state.extra.get("unmanaged_existing") or state.extra.get("unexpected_other_position"):
        return False, "BLOCKED_UNEXPECTED_POSITION"
    if state.current_position != "FLAT":
        return False, "POSITION_ALREADY_OPEN"
    if config["safety"].get("require_flat_before_entry") and state.current_position != "FLAT":
        return False, "POSITION_ALREADY_OPEN"
    if int(config["risk"].get("max_open_positions") or 1) <= 0:
        return False, "CONFIGURATION_ERROR"
    if not config["execution"].get("enable_long"):
        return False, "LONG_DISABLED"
    if cooldown_active(config, state):
        return False, "COOLDOWN"
    blocked = check_risk_limits(config, state)
    if blocked:
        return False, blocked
    quantity = int(config["instrument"]["quantity"])
    if quantity <= 0:
        return False, "CONFIGURATION_ERROR"
    return True, "NONE"


def compute_next_action(config: dict, state: BotState) -> None:
    """Set the human-readable NEXT ACTION and WHY-NO-TRADE fields."""
    if stop_requested() or state.engine_state in {"SHUTTING_DOWN", "STOPPED", "STOP_REQUESTED"}:
        state.next_action = "STOPPING"
        state.why_no_trade = "STOP_REQUESTED"
        return
    if state.engine_state == "ERROR":
        state.next_action = "ERROR — SEE EVENT STREAM"
        state.why_no_trade = "API_UNAVAILABLE"
        return
    allowed, window_reason = check_trading_window(config)
    if not allowed and window_reason == "WEEKEND":
        state.engine_state = "WAITING_FOR_SESSION"
        state.next_action = "WEEKEND — MARKET CLOSED"
        state.why_no_trade = "WEEKEND"
        return
    if not allowed and window_reason == "SESSION_NOT_STARTED":
        state.engine_state = "WAITING_FOR_SESSION"
        state.next_action = "SESSION NOT STARTED"
        state.why_no_trade = "SESSION_NOT_STARTED"
        return
    if not allowed and window_reason == "SESSION_ENDED":
        required = closed_market_confirm_polls(config)
        polls = int(state.extra.get("closed_market_polls") or 0)
        if required > 0:
            state.next_action = f"SESSION ENDED — LAST PRICES {polls}/{required}"
        else:
            state.next_action = "SESSION ENDED"
        state.why_no_trade = "SESSION_ENDED"
        return
    if not allowed and window_reason == "ENTRY_CUTOFF":
        if state.current_position == "FLAT":
            state.next_action = "ENTRY CUTOFF — NO NEW TRADES"
            state.why_no_trade = "ENTRY_CUTOFF"
            return
    if state.order_in_flight or state.pending_order_id:
        state.next_action = "ORDER IN FLIGHT — WAITING FOR FILL"
        state.why_no_trade = "PENDING_ORDER_EXISTS"
        return
    if state.current_position != "FLAT":
        state.engine_state = "POSITION_OPEN"
        state.next_action = "POSITION OPEN — MONITORING TP/SL"
        state.why_no_trade = "MONITORING_TP_SL"
        return
    blocked = check_risk_limits(config, state)
    if blocked == "MAX_TRADES_REACHED":
        state.engine_state = "DAILY_LIMIT_REACHED"
        state.next_action = "MAX TRADES REACHED"
        state.why_no_trade = blocked
        return
    if blocked:
        state.engine_state = "DAILY_LIMIT_REACHED"
        state.next_action = "RISK BLOCKED"
        state.why_no_trade = blocked
        return
    if cooldown_active(config, state):
        state.next_action = "COOLDOWN ACTIVE"
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
        "RISK_LIMIT_REACHED",
        "STOP_REQUESTED",
        "SESSION_NOT_STARTED",
        "SESSION_ENDED",
        "ENTRY_CUTOFF",
        "WEEKEND",
        "BOT_DISABLED",
        "COOLDOWN",
        "INSUFFICIENT_CANDLES",
        "INVALID_MARKET_DATA",
        "VWAP_UNAVAILABLE",
    }
    if state.why_no_trade in blocking:
        state.next_action = WHY_NO_TRADE_LABELS.get(
            state.why_no_trade, state.why_no_trade
        ).upper()
        return
    if state.last_signal == "BUY" and state.why_no_trade in {"NONE", "SCANNING", "ENTRY_EXECUTED"}:
        state.next_action = "BUY SIGNAL — RISK CHECK PENDING"
        return
    if state.why_no_trade in {
        "SCORE_BELOW_MINIMUM",
        "PRICE_BELOW_VWAP",
        "VWAP_NOT_RISING",
        "MOMENTUM_INSUFFICIENT",
        "VOLUME_INSUFFICIENT",
        "TREND_FAILED",
        "BREAKOUT_FAILED",
        "WAITING_FOR_NEW_CLOSED_CANDLE",
        "WAITING_FOR_MARKET_DATA",
    }:
        state.engine_state = "WAITING_FOR_SIGNAL"
        state.next_action = WHY_NO_TRADE_LABELS.get(state.why_no_trade, state.why_no_trade)
        return
    state.engine_state = "WAITING_FOR_SIGNAL"
    state.next_action = "POSITION FLAT — SCANNING"
    state.why_no_trade = "SCANNING"


# ============================================================
# TP/SL AND STRATEGY-EXIT MONITORING
# ============================================================

def monitor_tpsl(dhan, config: dict, state: BotState, ltp: Optional[float]) -> Optional[str]:
    """
    Check live LTP against armed TP/SL/trailing.

    Returns:
        TAKE_PROFIT, STOP_LOSS, or TRAILING_STOP when a level is reached.

    SL is evaluated first so a gap through both levels prefers capital
    protection. Software polling can overshoot the exact price.
    """
    if state.current_position == "FLAT":
        return None
    if ltp is None or ltp <= 0:
        logging.warning("No valid LTP available for TP/SL. Waiting.")
        return None

    side = state.current_position
    stop = effective_stop_loss(state)
    logging.info(
        "POSITION MONITORING | LTP=%.2f | entry=%s | TP=%s | SL=%s | TRAIL=%s | side=%s | pnl=%.2f",
        ltp,
        f"{state.entry_price:.2f}" if state.entry_price else "n/a",
        f"{state.take_profit_price:.2f}" if state.take_profit_price else "off",
        f"{state.stop_loss_price:.2f}" if state.stop_loss_price else "off",
        f"{state.trailing_stop_price:.2f}" if state.trailing_stop_price else "off",
        side,
        state.last_pnl,
    )

    if should_trigger_sl(ltp, stop, side):
        if state.trailing_armed and state.trailing_stop_price is not None:
            fixed = state.stop_loss_price
            trail = state.trailing_stop_price
            if (
                fixed is not None
                and (
                    (side == "LONG" and trail > fixed)
                    or (side == "SHORT" and trail < fixed)
                )
            ):
                return "TRAILING_STOP"
        return "STOP_LOSS"
    if should_trigger_tp(ltp, state.take_profit_price, side):
        return "TAKE_PROFIT"
    return None


def check_strategy_exits(config: dict, state: BotState, result: SignalResult) -> Optional[str]:
    """
    Optional VWAP / momentum failure exits. Disabled by default.

    Evaluated on a newly completed candle while a long is open.
    """
    if state.current_position != "LONG":
        return None
    exit_cfg = config.get("exit") or {}
    vwap_fail = exit_cfg.get("vwap_failure_exit") or {}
    if vwap_fail.get("enabled") and result.vwap is not None and result.close is not None:
        if result.close < result.vwap:
            return "VWAP_FAILURE_EXIT"
    mom_fail = exit_cfg.get("momentum_failure_exit") or {}
    if mom_fail.get("enabled") and result.momentum_percent is not None:
        minimum = float(config["strategy"]["momentum"]["minimum_price_change_percent"])
        if result.momentum_percent < minimum:
            return "MOMENTUM_FAILURE_EXIT"
    return None


# ============================================================
# SCI-FI CLI
# ============================================================

def render_startup_banner(config: dict) -> None:
    """Print the spec-required futuristic startup banner."""
    CONSOLE.print(
        Panel(
            Text(
                "VWAP MOMENTUM ENGINE v1.0\n\nDHAN EXECUTION CORE",
                justify="center",
                style="bold cyan",
            ),
            border_style="cyan",
            padding=(1, 4),
        )
    )
    if is_dry_run(config):
        CONSOLE.print("[bold yellow]MODE: PAPER — NO REAL ORDERS[/bold yellow]")
    else:
        CONSOLE.print("[bold red]⚠ LIVE TRADING ENABLED ⚠[/bold red]")

    instrument = config["instrument"]
    strategy = config["strategy"]
    hours = config["trading_hours"]
    risk = config["risk"]
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="bold cyan", min_width=14)
    grid.add_column(style="white")
    grid.add_row("BOT", str(config["bot"].get("name") or "VWAP Intraday Momentum"))
    grid.add_row("MODE", "PAPER" if is_dry_run(config) else "LIVE")
    grid.add_row("SYMBOL", str(instrument.get("symbol")))
    grid.add_row("SECURITY ID", str(instrument.get("security_id")))
    grid.add_row("STRATEGY", "VWAP MOMENTUM")
    grid.add_row("TIMEFRAME", str(strategy.get("timeframe")))
    grid.add_row("MIN SCORE", str(strategy["confirmation"]["minimum_conditions"]))
    grid.add_row("EMA", str(strategy["trend"]["ema_period"]))
    grid.add_row("LONG", "on" if config["execution"]["enable_long"] else "off")
    grid.add_row("SHORT", "on" if config["execution"]["enable_short"] else "off")
    grid.add_row("SL", f"{risk['stop_loss_percent']}%")
    grid.add_row("TP", f"{risk['take_profit_percent']}%")
    grid.add_row("TRAIL", "on" if risk["trailing_stop"]["enabled"] else "off")
    grid.add_row("POLLING", f"{config['bot']['polling_seconds']} SEC")
    grid.add_row(
        "SESSION",
        f"{hours.get('start_time')} → {hours.get('stop_entry_time')} / {hours.get('close_positions_time')}"
        if hours.get("enabled")
        else "DISABLED",
    )
    grid.add_row(
        "POST CLOSE",
        f"{int(config['shutdown'].get('closed_market_confirm_polls') or 0)} POLLS",
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
        logging.info("PAPER / DRY RUN. Real market data will be fetched. No live orders will be sent.")


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
        "VWAP_FAILURE_EXIT": "VWAP FAILURE EXIT",
        "MOMENTUM_FAILURE_EXIT": "MOMENTUM FAILURE EXIT",
        "TRADING_DAY_END": "TRADING DAY END",
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
    if config["risk"].get("stop_bot_after_exit") and reason in {
        "TAKE_PROFIT",
        "STOP_LOSS",
        "TRAILING_STOP",
        "VWAP_FAILURE_EXIT",
        "MOMENTUM_FAILURE_EXIT",
    }:
        grid.add_row("BOT", "STOPPED")
    CONSOLE.print(Panel(grid, title=f"[bold]{title}[/bold]", border_style="yellow"))


def render_dashboard(config: dict, state: BotState) -> Panel:
    """Build the sci-fi command-center panel from in-memory state."""
    now = now_in_session_tz(config)
    instrument = config["instrument"]
    strategy = config["strategy"]
    bot = config["bot"]
    cli = config["cli"]
    mode = "PAPER" if is_dry_run(config) else "LIVE"
    day_mode = "DAY TRADE" if is_session_enabled(config) else "CONTINUOUS"
    market = "OPEN" if is_market_expected_open(config, now) else "CLOSED"
    status = "RUNNING" if state.bot_running else "STOPPING"
    ema_text = f"{state.current_ema:.2f}" if state.current_ema is not None else "—"
    mom_text = (
        f"{state.current_momentum_percent:+.2f}%"
        if state.current_momentum_percent is not None
        else "—"
    )
    vol_text = f"{state.current_volume:,.0f}" if state.current_volume is not None else "—"
    avg_vol_text = (
        f"{state.current_avg_volume:,.0f}" if state.current_avg_volume is not None else "—"
    )
    ratio_text = (
        f"{state.current_volume_ratio:.2f}x" if state.current_volume_ratio is not None else "—"
    )
    candle_text = (
        state.last_candle_time.strftime("%H:%M:%S") if state.last_candle_time else "—"
    )
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
    score_text = f"{state.signal_score} / {state.signal_total}" if state.signal_total else "—"
    ticks = "   ".join(
        f"{name} {mark}" for name, mark in state.condition_ticks.items() if mark != "—"
    ) or "—"

    system = Table.grid(padding=(0, 2))
    system.add_column(min_width=14, style="bold dim")
    system.add_column(min_width=20)
    system.add_column(min_width=14, style="bold dim")
    system.add_column(min_width=20)
    system.add_row("STATUS", status, "MODE", f"{mode} / {day_mode}")
    system.add_row("MARKET", market, "ENGINE", state.engine_state)
    system.add_row("SYMBOL", str(instrument["symbol"]), "SECURITY ID", str(instrument["security_id"]))
    system.add_row("STRATEGY", "VWAP Momentum", "TIMEFRAME", str(strategy["timeframe"]))
    system.add_row("API", state.api_status, "STOP FILE", "YES" if STOP_FILE.exists() else "NO")

    market_tbl = Table.grid(padding=(0, 2))
    market_tbl.add_column(min_width=14, style="bold dim")
    market_tbl.add_column(min_width=20)
    market_tbl.add_column(min_width=14, style="bold dim")
    market_tbl.add_column(min_width=20)
    market_tbl.add_row("LTP", format_inr(state.last_ltp), "VWAP", format_inr(state.current_vwap))
    if cli.get("show_indicators", True):
        market_tbl.add_row("EMA", ema_text, "MOMENTUM", mom_text)
        market_tbl.add_row("VOLUME", vol_text, "AVG VOL", avg_vol_text)
        market_tbl.add_row("VOL RATIO", ratio_text, "CANDLE", candle_text)
        market_tbl.add_row(
            "DATA AT",
            state.last_market_data_at.strftime("%H:%M:%S") if state.last_market_data_at else "—",
            "POLL",
            f"{bot['polling_seconds']}s",
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
        strat.add_row("SIGNAL", state.last_signal)
        strat.add_row("SCORE", f"{score_text}   min {state.signal_minimum or strategy['confirmation']['minimum_conditions']}")
        strat.add_row("CHECKS", ticks)
        strat.add_row("CONDITION", state.strategy_condition)
        strat.add_row("NEXT ACTION", Text(state.next_action, style="bold yellow"))
        strat.add_row("WHY NO TRADE", why)
        sections.extend([Text(""), Text("SIGNAL", style="bold magenta"), strat])

    position = Table.grid(padding=(0, 2))
    position.add_column(min_width=14, style="bold dim")
    position.add_column(min_width=20)
    position.add_column(min_width=14, style="bold dim")
    position.add_column(min_width=20)
    position.add_row("STATUS", state.current_position, "QTY", str(state.position_quantity))
    position.add_row("ENTRY", format_inr(state.entry_price), "CURRENT", format_inr(state.last_ltp))
    position.add_row("TARGET", format_inr(state.take_profit_price), "STOP LOSS", format_inr(state.stop_loss_price))
    position.add_row(
        "TRAIL SL",
        format_inr(state.trailing_stop_price),
        "UNREALIZED",
        Text(pnl_text, style=pnl_style),
    )
    sections.extend([Text(""), Text("POSITION", style="bold magenta"), position])

    if cli.get("show_orders", True):
        trading_tbl = Table.grid(padding=(0, 2))
        trading_tbl.add_column(min_width=14, style="bold dim")
        trading_tbl.add_column(min_width=20)
        trading_tbl.add_column(min_width=14, style="bold dim")
        trading_tbl.add_column(min_width=20)
        last_trade = state.last_trade_time.strftime("%H:%M:%S") if state.last_trade_time else "—"
        daily_text = format_inr(state.daily_realized_pnl)
        trading_tbl.add_row("LAST TRADE", last_trade, "LAST ORDER", str(state.last_order_id or "—"))
        trading_tbl.add_row("ORDER STATUS", state.last_order_status, "EXIT REASON", state.last_exit_reason)
        trading_tbl.add_row("TRADES TODAY", str(state.trades_today), "DAILY P&L", daily_text)
        trading_tbl.add_row("LAST ERROR", state.last_error, "LAST EVAL", now.strftime("%H:%M:%S"))
        sections.extend([Text(""), Text("ORDERS / RISK", style="bold magenta"), trading_tbl])

    runtime_tbl = Table.grid(padding=(0, 2))
    runtime_tbl.add_column(min_width=14, style="bold dim")
    runtime_tbl.add_column(min_width=20)
    runtime_tbl.add_column(min_width=14, style="bold dim")
    runtime_tbl.add_column(min_width=20)
    runtime_tbl.add_row("RUNTIME", format_runtime(state.started_at, now), "NEXT POLL", poll_in)
    runtime_tbl.add_row("CLI REFRESH", f"{cli['refresh_seconds']}s", "STOP", "YES" if stop_requested() else "NO")
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
        title="[bold cyan]◈ VWAP MOMENTUM ENGINE ◈[/bold cyan]",
        subtitle=f"[dim]{now.strftime('%Y-%m-%d %H:%M:%S %Z')}[/dim]",
        border_style="cyan" if is_dry_run(config) else "red",
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
) -> Optional[str]:
    """
    Evaluate one newly completed candle. Never double-fires the same bar.

    Returns:
        A terminal exit reason if a strategy exit should stop the bot.
    """
    if not candles:
        state.why_no_trade = "WAITING_FOR_MARKET_DATA"
        return None
    latest = candles[-1]
    if state.last_processed_candle is not None and latest.timestamp <= state.last_processed_candle:
        state.why_no_trade = "WAITING_FOR_NEW_CLOSED_CANDLE"
        state.next_action = "WAITING FOR NEW CANDLE"
        generate_signal(candles, config, state)
        state.last_candle_time = latest.timestamp
        return None

    result = generate_signal(candles, config, state)
    state.last_processed_candle = latest.timestamp
    state.last_candle_time = latest.timestamp

    if state.current_position != "FLAT":
        strategy_exit = check_strategy_exits(config, state, result)
        if strategy_exit:
            logging.info("%s HIT", strategy_exit.replace("_", " "))
            push_event("EXIT", strategy_exit)
            entry = state.entry_price
            qty = state.position_quantity
            side = state.current_position
            trade_pnl, _pct = calculate_pnl(side, qty, entry, ltp or result.close)
            state.last_exit_reason = strategy_exit
            exit_position(dhan, config, state, strategy_exit, ltp)
            render_exit_banner(
                config,
                state,
                strategy_exit,
                entry,
                state.last_trade_price or ltp,
                qty,
                trade_pnl,
            )
            if config["risk"].get("stop_bot_after_exit"):
                return strategy_exit
            state.engine_state = "TRADE_COMPLETED"
            compute_next_action(config, state)
            return None
        compute_next_action(config, state)
        return None

    if not allow_entries:
        compute_next_action(config, state)
        return None

    if result.signal == "BUY":
        state.engine_state = "WAITING_FOR_SIGNAL"
        logging.info("SIGNAL DETECTED: VWAP MOMENTUM BUY")
        push_event("SIGNAL", f"BUY {result.score}/{result.total}")
        allowed, reason = validate_trade(config, state, "BUY")
        if not allowed:
            logging.info("Trade blocked: %s", WHY_NO_TRADE_LABELS.get(reason, reason))
            state.why_no_trade = reason
            compute_next_action(config, state)
            return None
        logging.info("RISK CHECK PASSED")
        if is_live_mode(config):
            logging.info(
                "LIVE pre-trade chain: config → session → position → pending → "
                "risk → signal → safety → order → verify"
            )
        state.next_action = "BUY SIGNAL — EXECUTING"
        if place_entry_order(dhan, config, state, "BUY", ltp):
            state.why_no_trade = "ENTRY_EXECUTED"
            state.engine_state = "POSITION_OPEN"
            state.extra["traded_candle"] = latest.timestamp
            push_event(
                "POSITION",
                f"{state.current_position} {state.position_quantity} @ {state.entry_price}",
            )
        else:
            logging.error("Entry was not confirmed. Not retrying blindly.")
            record_error(state, "Entry was not confirmed")
            state.engine_state = "WAITING_FOR_SIGNAL"
    compute_next_action(config, state)
    return None


def _finish_closed_market_poll(
    config: dict,
    state: BotState,
    cached_candles: list[Candle],
) -> tuple[list[Candle], Optional[str]]:
    """Count one post-close LTP/indicator poll. Exit after the configured count."""
    required = closed_market_confirm_polls(config)
    polls = int(state.extra.get("closed_market_polls") or 0) + 1
    state.extra["closed_market_polls"] = polls
    logging.info(
        "Closed-market confirm poll %s/%s (looking for last prices).",
        polls,
        required,
    )
    compute_next_action(config, state)
    if polls >= required:
        return cached_candles, "TRADING_DAY_END"
    return cached_candles, None


def run_one_poll_cycle(
    dhan,
    config: dict,
    state: BotState,
    cached_candles: list[Candle],
) -> tuple[list[Candle], Optional[str]]:
    """One trading API cycle. Returns (candles, terminal_reason)."""
    now = now_in_session_tz(config)
    state.loop_cycle += 1
    interval = float(config["bot"]["polling_seconds"])
    state.next_poll_at = now + timedelta(seconds=interval)

    announce_manual_stop_if_needed()
    if stop_requested():
        return cached_candles, "MANUAL_STOP"

    after_close = is_after_close_positions(config, now)
    confirm_polls = closed_market_confirm_polls(config)
    if after_close and confirm_polls <= 0:
        return cached_candles, "TRADING_DAY_END"

    window_ok, _window_reason = check_trading_window(config, now)
    allow_entries = window_ok
    if not allow_entries:
        compute_next_action(config, state)

    if sync_pending_order(dhan, config, state):
        compute_next_action(config, state)
        if not after_close:
            return cached_candles, None

    reconcile_every = int(config["bot"]["reconcile_every_cycles"])
    if state.loop_cycle == 1 or state.loop_cycle % reconcile_every == 0:
        reconcile_state(dhan, config, state)

    ltp = get_ltp(
        dhan,
        str(config["instrument"]["security_id"]),
        str(config["instrument"]["exchange_segment"]),
    )
    if ltp:
        state.last_ltp = ltp
        state.api_status = "CONNECTED"
    monitor_position(dhan, config, state, ltp)

    if after_close and not state.extra.get("post_close_flattened"):
        if config["shutdown"].get("close_positions_on_session_end") and dhan is not None:
            logging.info("Session ended: flattening if needed, then confirming last prices.")
            if state.current_position != "FLAT":
                exit_position(dhan, config, state, "TRADING_DAY_END", state.last_ltp)
            close_all_positions(dhan, config, state)
        state.extra["post_close_flattened"] = True

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
            if config["risk"].get("stop_bot_after_exit"):
                return cached_candles, hit
            state.engine_state = "TRADE_COMPLETED"
            compute_next_action(config, state)
            if after_close:
                return _finish_closed_market_poll(config, state, cached_candles)
            return cached_candles, None

    if state.current_position == "FLAT" and not after_close:
        blocked = check_risk_limits(config, state)
        if blocked:
            state.why_no_trade = blocked
            compute_next_action(config, state)
            if blocked == "RISK_LIMIT_REACHED" and config["risk"].get("close_on_risk_limit"):
                return cached_candles, "RISK_LIMIT"
            if allow_entries:
                return cached_candles, None

    candles = get_market_data(dhan, config)
    state.last_market_data_at = now_in_session_tz(config)
    if not candles:
        logging.warning("No usable candles this cycle. Waiting.")
        state.why_no_trade = "WAITING_FOR_MARKET_DATA"
        state.api_status = "DEGRADED"
        compute_next_action(config, state)
        if after_close:
            return _finish_closed_market_poll(config, state, cached_candles)
        return cached_candles, None

    cached_candles = candles
    terminal = process_new_candle(dhan, config, state, cached_candles, ltp, allow_entries)
    if terminal:
        return cached_candles, terminal
    if after_close:
        return _finish_closed_market_poll(config, state, cached_candles)
    return cached_candles, None


def run_trading_loop(dhan, config: dict, state: BotState) -> None:
    """
    Poll market data, signals, positions, and TP/SL until a shutdown reason.

    CLI refresh and API polling are independent: the dashboard may redraw
    every second from memory while Dhan is contacted only on the trading
    interval.
    """
    interval = float(config["bot"]["polling_seconds"])
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


def graceful_shutdown(dhan, config: dict, state: BotState, reason: str) -> None:
    """
    Stop entries, optionally flatten, verify, log, and exit the loop.

    Safety:
        Local flags are set even when the broker flatten fails.
    """
    logging.info("Shutdown requested (%s).", reason)
    state.engine_state = "SHUTTING_DOWN"
    state.bot_running = False
    if not state.shutdown_reason:
        state.shutdown_reason = reason
    if reason in {
        "TAKE_PROFIT",
        "STOP_LOSS",
        "TRAILING_STOP",
        "VWAP_FAILURE_EXIT",
        "MOMENTUM_FAILURE_EXIT",
    }:
        state.last_exit_reason = reason

    close_positions = False
    if reason in {"TRADING_DAY_END", "SESSION_END"}:
        close_positions = bool(config["shutdown"].get("close_positions_on_session_end"))
    elif reason in {
        "TAKE_PROFIT",
        "STOP_LOSS",
        "TRAILING_STOP",
        "VWAP_FAILURE_EXIT",
        "MOMENTUM_FAILURE_EXIT",
    }:
        close_positions = bool(config["shutdown"].get("close_positions_on_tp_sl")) and (
            state.current_position != "FLAT"
        )
    elif reason in {"MANUAL_STOP", "SIGINT", "SIGTERM"}:
        close_positions = bool(config["shutdown"].get("close_positions_on_manual_stop"))
    elif reason == "RISK_LIMIT":
        close_positions = bool(config["risk"].get("close_on_risk_limit"))
    elif reason == "ERROR":
        close_positions = bool(config["shutdown"].get("close_positions_on_error"))

    if close_positions and dhan is not None:
        if reason == "TRADING_DAY_END":
            exit_position(dhan, config, state, "TRADING_DAY_END", state.last_ltp)
        close_all_positions(dhan, config, state)
    elif state.current_position != "FLAT":
        logging.info(
            "Positions were left open by configuration. Local side=%s qty=%s",
            state.current_position,
            state.position_quantity,
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

    state.engine_state = "STOPPED"
    logging.info("STOP_REASON = %s", state.shutdown_reason)
    logging.info("BOT STOPPED")


# ============================================================
# MAIN
# ============================================================

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
        setup_logging(config)
        load_environment()
        validate_config(config)
        validate_safety_config(config)
        logging.info("CONFIGURATION LOADED")
        logging.info("CONFIGURATION VALIDATED")
        logging.info("STARTUP BEHAVIOR = %s", config["startup"]["behavior"])
        logging.info("%s MODE", "PAPER" if is_dry_run(config) else "LIVE")

        consume_leftover_stop_file()
        if stop_requested():
            logging.info("Stop requested at startup. No orders were placed.")
            return 0

        state.started_at = now_in_session_tz(config)
        render_startup_banner(config)
        logging.info("BOT STARTED")

        dhan = create_dhan_client()
        state.api_status = "CONNECTED"
        logging.info("DHAN CONNECTED")

        if config["startup"].get("reconcile_existing_positions"):
            recover_existing_state(dhan, config, state)

        if stop_requested():
            graceful_shutdown(dhan, config, state, "MANUAL_STOP")
            return 0

        compute_next_action(config, state)
        run_trading_loop(dhan, config, state)

        reason = state.shutdown_reason or (
            "MANUAL_STOP" if stop_requested() else "TRADING_DAY_END"
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
    sys.exit(main())
