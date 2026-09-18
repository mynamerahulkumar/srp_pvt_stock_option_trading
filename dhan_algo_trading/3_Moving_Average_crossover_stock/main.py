#!/usr/bin/env python3
"""Dhan Moving Average Crossover Algo for NSE equity.

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
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Optional

import yaml
from dotenv import load_dotenv

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
VALID_MA_TYPES = {"SMA", "EMA"}
VALID_TRADING_MODES = {"LONG_ONLY", "SHORT_ONLY", "LONG_SHORT"}
VALID_ORDER_TYPES = {"MARKET", "LIMIT"}
VALID_LIMIT_MODES = {"OFFSET_PERCENT", "ABSOLUTE"}
VALID_PRODUCT_TYPES = {"CNC", "INTRADAY", "INTRA", "MARGIN", "MTF"}
EQUITY_PRODUCTS = {"CNC", "INTRADAY", "INTRA", "MARGIN", "MTF"}
DERIVATIVE_PRODUCTS = {"INTRADAY", "INTRA", "MARGIN"}

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

# Set by signal handlers. Combined with the ``.stop`` file.
_shutdown_requested = False
_last_good_ltp: Optional[float] = None
_last_quote_monotonic: float = 0.0
# Security+product keys for which an exit was already submitted in close-all.
_close_all_submitted: set[tuple[str, str]] = set()


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
    entry_price: Optional[float] = None
    current_position: str = "FLAT"
    position_quantity: int = 0
    trade_direction: Optional[str] = None
    take_profit_price: Optional[float] = None
    stop_loss_price: Optional[float] = None
    last_processed_candle: Optional[datetime] = None
    last_signal: str = "HOLD"
    shutdown_reason: Optional[str] = None
    pending_order_id: Optional[str] = None
    pending_order_tag: Optional[str] = None
    pending_order_intent: Optional[str] = None
    pending_order_side: Optional[str] = None
    pending_order_quantity: int = 0
    order_in_flight: bool = False
    adopted_existing: bool = False
    loop_cycle: int = 0
    last_fast_ma: Optional[float] = None
    last_slow_ma: Optional[float] = None
    close_all_attempted: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


# ============================================================
# ENVIRONMENT
# ============================================================

def load_environment() -> None:
    """Load DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN from BASE_DIR/.env.

    Inputs: none (reads ENV_FILE and the process environment).
    Outputs: none. Raises CredentialError if either value is missing.

    Safety: never logs token values.
    """
    if ENV_FILE.exists():
        load_dotenv(ENV_FILE)
    else:
        logging.warning("No .env file found at %s. Checking process environment.", ENV_FILE)

    client_id = (os.environ.get("DHAN_CLIENT_ID") or "").strip()
    access_token = (os.environ.get("DHAN_ACCESS_TOKEN") or "").strip()
    if not client_id or not access_token:
        raise CredentialError(
            "ERROR: Dhan credentials are missing. Set DHAN_CLIENT_ID and "
            "DHAN_ACCESS_TOKEN in .env.\nThe bot did not start."
        )


# ============================================================
# CONFIGURATION
# ============================================================

def load_config() -> dict:
    """Load config.yaml from BASE_DIR.

    Returns a dict. Raises ConfigError for missing or invalid YAML.
    Used once at startup before any Dhan call.
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


def _optional_positive_price(section: dict, key: str) -> Optional[float]:
    value = section.get(key)
    if value in (None, "", 0, 0.0):
        return None
    return _as_positive_number(value, key)


def validate_config(config: dict) -> None:
    """Fail fast if any required setting is missing or inconsistent.

    Assumes config.yaml is a mapping of sections. Does not contact Dhan.
    """
    bot = _require_section(config, "bot")
    strategy = _require_section(config, "strategy")
    instrument = _require_section(config, "instrument")
    order = _require_section(config, "order")
    risk = _require_section(config, "risk")
    session = _require_section(config, "trading_session")
    polling = _require_section(config, "polling")
    shutdown = _require_section(config, "shutdown")
    _require_section(config, "logging")

    if not str(bot.get("name") or "").strip():
        raise ConfigError("ERROR: bot.name is required.\nThe bot did not start.")

    fast = int(_as_positive_number(strategy.get("fast_ma_period"), "strategy.fast_ma_period"))
    slow = int(_as_positive_number(strategy.get("slow_ma_period"), "strategy.slow_ma_period"))
    if fast >= slow:
        raise ConfigError(
            "ERROR: strategy.fast_ma_period must be less than slow_ma_period.\n"
            "The bot did not start."
        )
    strategy["fast_ma_period"] = fast
    strategy["slow_ma_period"] = slow

    timeframe = str(strategy.get("timeframe") or "").strip().upper()
    if timeframe not in VALID_TIMEFRAMES:
        raise ConfigError(
            "ERROR: strategy.timeframe must be one of "
            f"{sorted(VALID_TIMEFRAMES)}.\nThe bot did not start."
        )
    strategy["timeframe"] = timeframe

    ma_type = str(strategy.get("ma_type") or "").strip().upper()
    if ma_type not in VALID_MA_TYPES:
        raise ConfigError(
            f"ERROR: strategy.ma_type must be one of {sorted(VALID_MA_TYPES)}.\n"
            "The bot did not start."
        )
    strategy["ma_type"] = ma_type

    trading_mode = str(strategy.get("trading_mode") or "").strip().upper()
    if trading_mode not in VALID_TRADING_MODES:
        raise ConfigError(
            "ERROR: strategy.trading_mode must be LONG_ONLY, SHORT_ONLY, or LONG_SHORT.\n"
            "The bot did not start."
        )
    strategy["trading_mode"] = trading_mode

    security_id = str(instrument.get("security_id") or "").strip()
    trading_symbol = str(instrument.get("trading_symbol") or instrument.get("symbol") or "").strip()
    if not security_id:
        raise ConfigError("ERROR: instrument.security_id is required.\nThe bot did not start.")
    if not trading_symbol:
        raise ConfigError("ERROR: instrument.trading_symbol is required.\nThe bot did not start.")
    instrument["security_id"] = security_id
    instrument["trading_symbol"] = trading_symbol

    exchange_segment = str(instrument.get("exchange_segment") or "").strip().upper()
    if not exchange_segment:
        raise ConfigError("ERROR: instrument.exchange_segment is required.\nThe bot did not start.")
    instrument["exchange_segment"] = exchange_segment

    quantity = int(_as_positive_number(instrument.get("quantity"), "instrument.quantity"))
    if quantity != float(instrument.get("quantity")):
        raise ConfigError("ERROR: instrument.quantity must be a whole number.\nThe bot did not start.")
    instrument["quantity"] = quantity

    product_type = str(instrument.get("product_type") or "").strip().upper()
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
        raise ConfigError(
            "ERROR: equity product_type is invalid.\nThe bot did not start."
        )
    instrument["product_type"] = product_type
    instrument["tick_size"] = _as_positive_number(
        instrument.get("tick_size", 0.05), "instrument.tick_size"
    )
    instrument["instrument_type"] = str(
        instrument.get("instrument_type") or "EQUITY"
    ).strip().upper()

    for key in ("entry_order_type", "exit_order_type"):
        value = str(order.get(key) or "").strip().upper()
        if value not in VALID_ORDER_TYPES:
            raise ConfigError(
                f"ERROR: order.{key} must be MARKET or LIMIT.\nThe bot did not start."
            )
        order[key] = value

    limit_mode = str(order.get("limit_price_mode") or "OFFSET_PERCENT").strip().upper()
    if limit_mode not in VALID_LIMIT_MODES:
        raise ConfigError(
            "ERROR: order.limit_price_mode must be OFFSET_PERCENT or ABSOLUTE.\n"
            "The bot did not start."
        )
    order["limit_price_mode"] = limit_mode
    order["limit_offset_percent"] = _as_non_negative_number(
        order.get("limit_offset_percent", 0), "order.limit_offset_percent"
    )
    order["limit_price"] = _as_non_negative_number(
        order.get("limit_price", 0), "order.limit_price"
    )
    if limit_mode == "ABSOLUTE" and (
        order["entry_order_type"] == "LIMIT" or order["exit_order_type"] == "LIMIT"
    ):
        if order["limit_price"] <= 0:
            raise ConfigError(
                "ERROR: order.limit_price must be > 0 when limit_price_mode is ABSOLUTE.\n"
                "The bot did not start."
            )
    order["validity"] = str(order.get("validity") or "DAY").strip().upper() or "DAY"

    tp_enabled = bool(risk.get("take_profit_enabled", False))
    sl_enabled = bool(risk.get("stop_loss_enabled", False))
    risk["take_profit_enabled"] = tp_enabled
    risk["stop_loss_enabled"] = sl_enabled
    tp_price = _optional_positive_price(risk, "take_profit_price")
    sl_price = _optional_positive_price(risk, "stop_loss_price")
    if tp_enabled and tp_price is None:
        risk["take_profit_percent"] = _as_positive_number(
            risk.get("take_profit_percent"), "risk.take_profit_percent"
        )
    if sl_enabled and sl_price is None:
        risk["stop_loss_percent"] = _as_positive_number(
            risk.get("stop_loss_percent"), "risk.stop_loss_percent"
        )
    risk["stop_bot_on_tp"] = bool(risk.get("stop_bot_on_tp", True))
    risk["stop_bot_on_sl"] = bool(risk.get("stop_bot_on_sl", True))

    session["enabled"] = bool(session.get("enabled", False))
    session["timezone"] = str(session.get("timezone") or "Asia/Kolkata").strip()
    start_h, start_m = _parse_hhmm(session.get("start_time", "09:20"), "trading_session.start_time")
    stop_h, stop_m = _parse_hhmm(session.get("stop_time", "15:15"), "trading_session.stop_time")
    if session["enabled"] and (start_h, start_m) >= (stop_h, stop_m):
        raise ConfigError(
            "ERROR: trading_session.start_time must be before stop_time.\n"
            "The bot did not start."
        )
    session["close_all_positions_at_stop"] = bool(
        session.get("close_all_positions_at_stop", True)
    )

    polling["interval_seconds"] = _as_positive_number(
        polling.get("interval_seconds", 10), "polling.interval_seconds"
    )
    polling["candle_lookback"] = int(
        _as_positive_number(polling.get("candle_lookback", 100), "polling.candle_lookback")
    )
    polling["order_wait_seconds"] = _as_positive_number(
        polling.get("order_wait_seconds", 90), "polling.order_wait_seconds"
    )
    polling["reconcile_every_cycles"] = max(
        1,
        int(_as_positive_number(polling.get("reconcile_every_cycles", 6), "polling.reconcile_every_cycles")),
    )

    shutdown["close_positions_on_manual_stop"] = bool(
        shutdown.get("close_positions_on_manual_stop", True)
    )
    shutdown["close_positions_on_error"] = bool(
        shutdown.get("close_positions_on_error", False)
    )
    shutdown["manage_existing_positions"] = bool(
        shutdown.get("manage_existing_positions", True)
    )


def is_dry_run(config: dict) -> bool:
    """True when live place_order must never be called."""
    return bool(config.get("bot", {}).get("dry_run", True))


def validate_safety_config(config: dict) -> None:
    """Live trading requires dry_run=false AND allow_live_trading=true.

    This double lock is intentional. A single flag is too easy to flip by
    accident on a 1 GB VM that can place real orders.
    """
    bot = _require_section(config, "bot")
    dry_run = bool(bot.get("dry_run", True))
    allow_live_trading = bool(bot.get("allow_live_trading", False))
    if dry_run:
        return
    if not allow_live_trading:
        raise SafetyError(
            "ERROR: Live trading is not allowed. "
            "Set bot.dry_run: false and bot.allow_live_trading: true.\n"
            "The bot did not start."
        )


# ============================================================
# LOGGING AND BANNER
# ============================================================

def setup_logging(config: dict) -> None:
    """Configure the standard library logger from config.yaml."""
    level_name = str(config.get("logging", {}).get("level") or "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(
            level=level,
            format="%(asctime)s | %(levelname)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    root.setLevel(level)
    for handler in root.handlers:
        handler.setLevel(level)


def print_startup_banner(config: dict) -> None:
    """Print a one-time summary so the operator can see mode and instrument."""
    bot = config["bot"]
    strategy = config["strategy"]
    instrument = config["instrument"]
    mode = "DRY RUN" if is_dry_run(config) else "LIVE"
    lines = [
        "==================================================",
        str(bot.get("name") or "Dhan Moving Average Crossover Algo"),
        f"Mode: {mode}",
        f"Trading Symbol: {instrument.get('trading_symbol')}",
        f"Security ID: {instrument.get('security_id')}",
        f"Exchange: {instrument.get('exchange_segment')}",
        f"Timeframe: {strategy.get('timeframe')}",
        f"Fast MA: {strategy.get('fast_ma_period')} {strategy.get('ma_type')}",
        f"Slow MA: {strategy.get('slow_ma_period')} {strategy.get('ma_type')}",
        f"Trading Mode: {strategy.get('trading_mode')}",
        f"Quantity: {instrument.get('quantity')}",
        f"Product: {instrument.get('product_type')}",
        "==================================================",
    ]
    banner = "\n".join(lines)
    print(banner)
    for line in lines:
        logging.info("%s", line)
    if is_dry_run(config):
        logging.info("DRY RUN is on. Real market data will be fetched. No live orders will be sent.")
    else:
        logging.info("LIVE mode. Real Dhan orders will be sent.")


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
    name = str(config.get("trading_session", {}).get("timezone") or "Asia/Kolkata")
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
    hour, minute = _parse_hhmm(config["trading_session"][field_name], field_name)
    return now.replace(hour=hour, minute=minute, second=0, microsecond=0)


def session_window(config: dict, now: Optional[datetime] = None) -> tuple[datetime, datetime]:
    current = now or now_in_session_tz(config)
    return (
        _session_clock(config, current, "start_time"),
        _session_clock(config, current, "stop_time"),
    )


def is_session_enabled(config: dict) -> bool:
    return bool(config.get("trading_session", {}).get("enabled"))


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
        time.sleep(min(0.5, deadline - time.monotonic()))
    return stop_requested()


# ============================================================
# DHAN CLIENT
# ============================================================

def create_dhan_client():
    """Build a Dhan SDK client from environment credentials.

    Supports both DhanContext (current SDK) and the older constructor.
    Does not log the access token.
    """
    client_id = os.environ["DHAN_CLIENT_ID"].strip()
    access_token = os.environ["DHAN_ACCESS_TOKEN"].strip()
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
    until the session stop time (or 15:30 IST if session timing is off).
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


def latest_possible_completed_start(now: datetime, timeframe: str) -> datetime:
    """Start time of the newest bar that is already complete as of ``now``.

    Matches ``_is_candle_complete``: a minute bar that starts at 10:00 and
    lasts 5 minutes is complete at 10:05, so at 10:04 the latest complete
    start is 09:55. Daily bars complete after 15:30 on that calendar day.
    """
    if timeframe == "DAY":
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        if now.hour > 15 or (now.hour == 15 and now.minute >= 30):
            return today_start
        return today_start - timedelta(days=1)
    minutes = interval_minutes(timeframe) or 1
    elapsed = now.hour * 60 + now.minute
    current_start_minutes = (elapsed // minutes) * minutes
    current_start = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(
        minutes=current_start_minutes
    )
    return current_start - timedelta(minutes=minutes)


def fetch_candles(dhan, config: dict) -> list[Candle]:
    """Download enough OHLC bars to compute the slow moving average.

    Inputs: live Dhan client and validated config.
    Returns: completed candles only, oldest first. Empty list on failure.

    Safety: does not trade. Logs and returns [] when the payload is unusable
    so the loop can continue without placing an order.
    """
    instrument = config["instrument"]
    strategy = config["strategy"]
    polling = config["polling"]
    timeframe = strategy["timeframe"]
    lookback = int(polling["candle_lookback"])
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
    completed = [item for item in candles if _is_candle_complete(item, timeframe, now)]
    if lookback > 0:
        completed = completed[-lookback:]
    logging.info(
        "Market data fetched: %s completed %s-minute/day candles (lookback=%s).",
        len(completed),
        timeframe,
        lookback,
    )
    return completed


# ============================================================
# MOVING AVERAGES
# ============================================================

def calculate_sma(closes: list[float], period: int) -> list[Optional[float]]:
    """Simple moving average of the close.

    Inputs: closes in chronological order, period > 0.
    Returns: a list the same length as closes. Early values are None until
    ``period`` closes exist. Each later value is the mean of the previous
    ``period`` closes, inclusive of the current bar.

    Used by calculate_moving_average when ma_type is SMA.
    """
    result: list[Optional[float]] = [None] * len(closes)
    if period <= 0 or len(closes) < period:
        return result
    running = 0.0
    for index, price in enumerate(closes):
        running += price
        if index >= period:
            running -= closes[index - period]
        if index >= period - 1:
            result[index] = running / period
    return result


def calculate_ema(closes: list[float], period: int) -> list[Optional[float]]:
    """Exponential moving average of the close.

    Seeded with the SMA of the first ``period`` closes, then updated with
    multiplier 2 / (period + 1). Early values are None.

    Used by calculate_moving_average when ma_type is EMA.
    """
    result: list[Optional[float]] = [None] * len(closes)
    if period <= 0 or len(closes) < period:
        return result
    seed = sum(closes[:period]) / period
    result[period - 1] = seed
    multiplier = 2.0 / (period + 1.0)
    previous = seed
    for index in range(period, len(closes)):
        current = (closes[index] * multiplier) + (previous * (1.0 - multiplier))
        result[index] = current
        previous = current
    return result


MA_CALCULATORS = {
    "SMA": calculate_sma,
    "EMA": calculate_ema,
}


def calculate_moving_average(
    closes: list[float], period: int, ma_type: str
) -> list[Optional[float]]:
    """Dispatch to the configured MA calculator.

    Add a new type by implementing a function with the same signature as
    calculate_sma and registering it in MA_CALCULATORS.
    """
    calculator = MA_CALCULATORS.get(str(ma_type).upper())
    if calculator is None:
        raise ConfigError(f"ERROR: unsupported ma_type {ma_type}.")
    return calculator(closes, period)


# ============================================================
# SIGNAL GENERATION
# ============================================================

def generate_signal(
    candles: list[Candle], config: dict
) -> tuple[str, Optional[float], Optional[float], Optional[float], Optional[float]]:
    """Generate a trading signal from a moving-average crossover.

    The function compares the previous completed candle's fast and slow
    moving averages with the latest completed candle's values.

    Returns:
        (signal, previous_fast_ma, previous_slow_ma, fast_ma, slow_ma)
        BUY  - bullish crossover
        SELL - bearish crossover
        HOLD - no new crossover

    Important:
        This function detects a crossover event. It does not simply
        check whether the fast MA is currently above or below the
        slow MA. A persistent "fast > slow" state after an already
        handled crossover must return HOLD.
    """
    strategy = config["strategy"]
    fast_period = int(strategy["fast_ma_period"])
    slow_period = int(strategy["slow_ma_period"])
    ma_type = strategy["ma_type"]
    closes = [candle.close for candle in candles]
    if len(closes) < slow_period + 2:
        return "HOLD", None, None, None, None

    fast_series = calculate_moving_average(closes, fast_period, ma_type)
    slow_series = calculate_moving_average(closes, slow_period, ma_type)
    fast_ma = fast_series[-1]
    slow_ma = slow_series[-1]
    previous_fast_ma = fast_series[-2]
    previous_slow_ma = slow_series[-2]
    if None in (fast_ma, slow_ma, previous_fast_ma, previous_slow_ma):
        return "HOLD", previous_fast_ma, previous_slow_ma, fast_ma, slow_ma

    if previous_fast_ma <= previous_slow_ma and fast_ma > slow_ma:
        return "BUY", previous_fast_ma, previous_slow_ma, fast_ma, slow_ma
    if previous_fast_ma >= previous_slow_ma and fast_ma < slow_ma:
        return "SELL", previous_fast_ma, previous_slow_ma, fast_ma, slow_ma
    return "HOLD", previous_fast_ma, previous_slow_ma, fast_ma, slow_ma


def action_for_signal(signal: str, position_side: str, trading_mode: str) -> Optional[str]:
    """Map a crossover plus current side into one strategy action.

    Returns:
        ENTER_LONG, EXIT_LONG, ENTER_SHORT, EXIT_SHORT, REVERSE_TO_LONG,
        REVERSE_TO_SHORT, or None (do nothing).

    LONG_ONLY never opens a short. SHORT_ONLY never opens a long.
    """
    side = (position_side or "FLAT").upper()
    mode = trading_mode.upper()
    if signal == "HOLD":
        return None

    if mode == "LONG_ONLY":
        if signal == "BUY" and side == "FLAT":
            return "ENTER_LONG"
        if signal == "SELL" and side == "LONG":
            return "EXIT_LONG"
        if signal == "BUY" and side == "SHORT":
            return "EXIT_SHORT"
        return None

    if mode == "SHORT_ONLY":
        if signal == "SELL" and side == "FLAT":
            return "ENTER_SHORT"
        if signal == "BUY" and side == "SHORT":
            return "EXIT_SHORT"
        if signal == "SELL" and side == "LONG":
            return "EXIT_LONG"
        return None

    # LONG_SHORT
    if signal == "BUY":
        if side == "FLAT":
            return "ENTER_LONG"
        if side == "SHORT":
            return "REVERSE_TO_LONG"
        return None
    if signal == "SELL":
        if side == "FLAT":
            return "ENTER_SHORT"
        if side == "LONG":
            return "REVERSE_TO_SHORT"
        return None
    return None


# ============================================================
# POSITIONS
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
    """Return (read_ok, row) for the configured instrument.

    read_ok is False when the position API failed. row is None when the
    instrument is flat (or the read failed).
    """
    target = str(config["instrument"]["security_id"])
    open_rows = get_open_positions(dhan)
    if open_rows is None:
        return False, None
    for row in open_rows:
        if _position_security_id(row) == target:
            return True, row
    return True, None


def has_open_position(dhan, config: dict) -> bool:
    read_ok, row = get_open_position(dhan, config)
    return bool(read_ok and row is not None)


def get_position_side(dhan, config: dict) -> str:
    read_ok, row = get_open_position(dhan, config)
    if not read_ok or row is None:
        return "FLAT"
    return _position_side(_position_net_qty(row))


def get_position_quantity(dhan, config: dict) -> int:
    read_ok, row = get_open_position(dhan, config)
    if not read_ok or row is None:
        return 0
    return abs(_position_net_qty(row))


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
    state.current_position = side
    state.position_quantity = quantity
    state.trade_direction = None if side == "FLAT" else side
    if side == "FLAT":
        state.entry_price = None
        state.take_profit_price = None
        state.stop_loss_price = None
        return
    if avg_price > 0:
        state.entry_price = avg_price
        arm_risk_levels(state, config, avg_price, side)


def log_existing_positions(dhan, config: dict) -> Optional[dict]:
    """Log the full position book and return our instrument row if open."""
    positions = get_positions(dhan)
    if positions is None:
        logging.error("Could not read positions at startup. Continuing without a snapshot.")
        return None
    if not positions:
        logging.info("No positions returned (flat or empty book).")
        return None
    ours = None
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
        if security_id == target and net_qty != 0:
            ours = row
    if ours is None:
        logging.info("Configured instrument is flat at the broker.")
    return ours


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

def arm_risk_levels(state: BotState, config: dict, entry_price: float, side: str) -> None:
    """Compute and store TP/SL prices for the open position.

    LONG:  TP = P + configured, SL = P - configured
    SHORT: TP = P - configured, SL = P + configured

    Absolute config prices override percent when set. Results are rounded
    to tick size.
    """
    risk = config["risk"]
    tick = float(config["instrument"]["tick_size"])
    state.entry_price = entry_price
    state.take_profit_price = None
    state.stop_loss_price = None
    direction = side.upper()

    if risk.get("take_profit_enabled"):
        absolute = _optional_positive_price(risk, "take_profit_price")
        if absolute is not None:
            state.take_profit_price = round_to_tick(absolute, tick)
        else:
            percent = float(risk["take_profit_percent"])
            if direction == "LONG":
                raw = entry_price * (1.0 + percent / 100.0)
            else:
                raw = entry_price * (1.0 - percent / 100.0)
            state.take_profit_price = round_to_tick(raw, tick)

    if risk.get("stop_loss_enabled"):
        absolute = _optional_positive_price(risk, "stop_loss_price")
        if absolute is not None:
            state.stop_loss_price = round_to_tick(absolute, tick)
        else:
            percent = float(risk["stop_loss_percent"])
            if direction == "LONG":
                raw = entry_price * (1.0 - percent / 100.0)
            else:
                raw = entry_price * (1.0 + percent / 100.0)
            state.stop_loss_price = round_to_tick(raw, tick)

    logging.info(
        "Entry price=%.2f side=%s TP=%s SL=%s",
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
    """Compute a LIMIT price. Never converts LIMIT into MARKET.

    OFFSET_PERCENT: buy above LTP, sell below LTP so the order is marketable.
    ABSOLUTE: use order.limit_price from config.
    Returns None when the price cannot be computed; the caller must skip.
    """
    order = config["order"]
    tick = float(config["instrument"]["tick_size"])
    mode = order["limit_price_mode"]
    side = transaction_type.upper()
    if mode == "ABSOLUTE":
        price = float(order["limit_price"])
        if price <= 0:
            return None
        return round_to_tick(price, tick)
    if ltp is None or ltp <= 0:
        return None
    offset = float(order["limit_offset_percent"]) / 100.0
    if side == "BUY":
        raw = ltp * (1.0 + offset)
    else:
        raw = ltp * (1.0 - offset)
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
        return "FAILED"
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


# ============================================================
# ORDER EXECUTION
# ============================================================

def _opposite_side(transaction_type: str) -> str:
    if str(transaction_type).strip().upper() == "BUY":
        return "SELL"
    return "BUY"


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


def _apply_fill(state: BotState, config: dict, intent: str, side: str, quantity: int, fill_price: float) -> None:
    """Update local position after a confirmed fill. Does not place orders."""
    if intent == "EXIT" or intent == "CLOSE_ALL":
        _mark_flat(state)
        logging.info("Position closed. Local state is FLAT.")
        return
    position_side = "LONG" if side.upper() == "BUY" else "SHORT"
    state.current_position = position_side
    state.position_quantity = quantity
    state.trade_direction = position_side
    price = fill_price if fill_price > 0 else state.entry_price or 0.0
    if price > 0:
        arm_risk_levels(state, config, price, position_side)


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
        "validity": _map_validity(config["order"].get("validity", "DAY")),
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
        f"WOULD place {intent} {order_type} {transaction_type} qty={quantity} "
        f"price={price_text} (dry run — no live order sent)"
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
    """Place exactly one order. Never retries place_order on timeout.

    Inputs: Dhan client, config, mutable BotState, side, qty, type, intent.
    Returns: order ID string, ``DRY_RUN`` in dry-run, or None on failure.

    Safety:
        * Refuses if a previous order is still in flight.
        * LIMIT is never rewritten to MARKET.
        * After an uncertain API error, recovers by correlation tag.
        * Does not place a second order just because confirmation failed.
    """
    if quantity <= 0:
        logging.info("Quantity is 0. No order was placed.")
        return None
    if state.order_in_flight or state.pending_order_id:
        logging.error(
            "An order is already in flight (id=%s). Refusing to submit another.",
            state.pending_order_id,
        )
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
        _apply_fill(state, config, intent, transaction_type, quantity, fill_price)
        return "DRY_RUN"

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
    logging.info(
        "Submitting %s %s: symbol=%s security_id=%s side=%s qty=%s price=%s tag=%s intent=%s",
        order_type,
        intent,
        config["instrument"]["trading_symbol"],
        request["security_id"],
        request["transaction_type"],
        request["quantity"],
        price if order_type == "LIMIT" else "MARKET",
        tag,
        intent,
    )

    state.order_in_flight = True
    state.pending_order_tag = tag
    state.pending_order_intent = intent
    state.pending_order_side = transaction_type
    state.pending_order_quantity = quantity

    response = None
    try:
        response = dhan.place_order(**request)
    except Exception as exc:
        logging.error("Order placement returned an uncertain result: %s", exc)
        recovered = find_order_id_after_uncertain_place(dhan, tag, request["security_id"])
        if recovered:
            logging.info("Recovered order ID from broker state: %s", recovered)
            state.pending_order_id = recovered
            return recovered
        logging.error(
            "Could not confirm whether Dhan accepted the order. "
            "Not submitting another order."
        )
        return None

    if not isinstance(response, dict):
        logging.error("Unexpected place-order response. Checking broker state.")
        recovered = find_order_id_after_uncertain_place(dhan, tag, request["security_id"])
        if recovered:
            state.pending_order_id = recovered
            return recovered
        return None

    if not _dhan_ok(response):
        logging.error("Dhan rejected the order: %s", _dhan_error_text(response))
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
        return None

    order_id = str(order_id)
    state.pending_order_id = order_id
    logging.info("Order submitted. Order ID: %s", order_id)
    raw_status = ""
    if payload:
        raw_status = str(payload.get("orderStatus") or payload.get("status") or "")
        logging.info("Order status from place response: %s", raw_status or "unknown")
    return order_id


def wait_for_order_completion(
    dhan,
    config: dict,
    state: BotState,
    order_id: str,
    requested_quantity: int,
) -> Optional[dict]:
    """Poll one order until a terminal state, timeout, or stop signal.

    Returns the last status dict, or None if status could not be read.
    Partial fills at timeout are kept as-is; the remainder is not re-sent.
    """
    if order_id == "DRY_RUN":
        return {
            "status": "FILLED",
            "filled_quantity": requested_quantity,
            "fill_price": state.entry_price or 0.0,
            "raw_status": "DRY_RUN",
        }

    poll_interval = float(config["polling"]["interval_seconds"])
    max_wait = float(config["polling"]["order_wait_seconds"])
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
    if order_id == "DRY_RUN":
        return True

    status = wait_for_order_completion(dhan, config, state, order_id, quantity)
    if status is None:
        logging.error("Could not confirm order %s. Treating as uncertain. No retry.", order_id)
        return False

    normalized = status["status"]
    filled = int(status.get("filled_quantity") or 0)
    fill_price = _safe_float(status.get("fill_price"), 0.0)

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
        else:
            logging.error(
                "An order may already exist (tag=%s) but the ID is unknown. "
                "Not placing another order.",
                state.pending_order_tag,
            )
            return True
    if not state.pending_order_id:
        return False
    try:
        status = get_order_status(
            dhan, state.pending_order_id, state.pending_order_quantity or 1
        )
    except Exception as exc:
        logging.error("Pending-order sync failed: %s", exc)
        return True

    logging.info(
        "Pending order %s | raw=%s | status=%s | filled=%s",
        state.pending_order_id,
        status["raw_status"],
        status["status"],
        status["filled_quantity"],
    )
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
        order_type=config["order"]["entry_order_type"],
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
    """Exit the current local position with the configured exit order type."""
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
        order_type=config["order"]["exit_order_type"],
        intent="EXIT",
        ltp=ltp,
    )
    return finalize_submitted_order(dhan, config, state, order_id, side, qty, "EXIT")


def reverse_position(
    dhan,
    config: dict,
    state: BotState,
    target_side: str,
    ltp: Optional[float],
) -> bool:
    """Exit the current position, wait for fill, then enter the opposite side.

    If the exit is not confirmed, the entry is not sent.
    """
    logging.info("Reversing position to %s.", target_side)
    if not place_exit_order(dhan, config, state, ltp):
        logging.error("Reverse aborted because the exit was not confirmed.")
        return False
    if state.current_position != "FLAT":
        logging.error("Reverse aborted because the position is not flat after exit.")
        return False
    entry_side = "BUY" if target_side == "LONG" else "SELL"
    return place_entry_order(dhan, config, state, entry_side, ltp)


# ============================================================
# CLOSE ALL POSITIONS
# ============================================================

def close_all_positions(dhan, config: dict, state: BotState) -> bool:
    """Flatten every open Dhan position.

    1. Fetch current positions.
    2. Identify open rows (netQty != 0).
    3. Place the opposite transaction once per security+product.
    4. Verify the book is flat.
    5. Retry the *read*, not a second place, if the book is still open.

    Used for end-of-day, manual stop, emergency shutdown, and TP/SL halt.
    Duplicate exits are avoided with ``_close_all_submitted``.
    """
    global _close_all_submitted
    logging.info("close_all_positions() starting.")
    state.close_all_attempted = True

    if is_dry_run(config):
        if state.current_position != "FLAT":
            logging.info(
                "WOULD close local %s qty=%s (dry run — no live order sent)",
                state.current_position,
                state.position_quantity,
            )
            _mark_flat(state)
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
            if interruptible_sleep(float(config["polling"]["interval_seconds"])):
                break
            continue
        if not open_rows:
            logging.info("Broker position book is flat.")
            _mark_flat(state)
            return True

        for row in open_rows:
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
                config["order"]["exit_order_type"],
                side,
            )
            saved_pending = state.pending_order_id
            if saved_pending:
                logging.info(
                    "Pending order %s exists; still placing a flatten for the open position.",
                    saved_pending,
                )
            state.order_in_flight = False
            state.pending_order_id = None
            order_id = submit_order(
                dhan,
                config,
                state,
                transaction_type=side,
                quantity=quantity,
                order_type=config["order"]["exit_order_type"],
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
        elif not remaining:
            logging.info("All positions closed.")
            _mark_flat(state)
            return True
        else:
            logging.warning(
                "Positions still open after close attempt: %s. Rechecking.",
                [(_position_security_id(row), _position_net_qty(row)) for row in remaining],
            )
        if interruptible_sleep(float(config["polling"]["interval_seconds"])):
            break

    leftover = get_open_positions(dhan)
    if leftover:
        logging.error(
            "close_all_positions() finished with leftover positions: %s",
            [(_position_security_id(row), _position_net_qty(row)) for row in leftover],
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
# RECONCILIATION
# ============================================================

def reconcile_state(dhan, config: dict, state: BotState) -> None:
    """Compare local position with Dhan. Trust the broker. Never 'fix' with a new trade."""
    if is_dry_run(config):
        return
    read_ok, row = get_open_position(dhan, config)
    if not read_ok:
        logging.warning("Skipping reconciliation because the position book could not be read.")
        return
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


# ============================================================
# TP/SL MONITORING
# ============================================================

def monitor_tpsl(dhan, config: dict, state: BotState, ltp: Optional[float]) -> bool:
    """Check live LTP against armed TP/SL. Returns True if the bot should halt.

    SL is evaluated first so a gap through both levels prefers capital protection.
    Uses last traded price, not candle close.
    """
    if state.current_position == "FLAT":
        return False
    risk = config["risk"]
    if not risk.get("take_profit_enabled") and not risk.get("stop_loss_enabled"):
        return False
    if ltp is None:
        logging.warning("No LTP available for TP/SL. Waiting.")
        return False

    side = state.current_position
    logging.info(
        "LTP=%.2f | entry=%s | TP=%s | SL=%s | side=%s",
        ltp,
        f"{state.entry_price:.2f}" if state.entry_price else "n/a",
        f"{state.take_profit_price:.2f}" if state.take_profit_price else "off",
        f"{state.stop_loss_price:.2f}" if state.stop_loss_price else "off",
        side,
    )

    reason = None
    if risk.get("stop_loss_enabled") and should_trigger_sl(ltp, state.stop_loss_price, side):
        reason = "STOP_LOSS"
    elif risk.get("take_profit_enabled") and should_trigger_tp(ltp, state.take_profit_price, side):
        reason = "TAKE_PROFIT"
    if reason is None:
        return False

    logging.info("%s triggered at LTP %.2f. Exiting position.", reason, ltp)
    closed = place_exit_order(dhan, config, state, ltp)
    if not closed and not is_dry_run(config):
        closed = close_all_positions(dhan, config, state)
    if state.current_position != "FLAT" and not is_dry_run(config):
        logging.error("TP/SL exit could not be confirmed. Position may still be open.")

    stop_bot = (
        (reason == "TAKE_PROFIT" and risk.get("stop_bot_on_tp", True))
        or (reason == "STOP_LOSS" and risk.get("stop_bot_on_sl", True))
    )
    if stop_bot:
        state.shutdown_reason = reason
        logging.info("STOP_REASON = %s", reason)
        logging.info("Bot will stop for this trading session after TP/SL.")
        return True
    logging.info("TP/SL stop-bot flag is false. Strategy may continue.")
    return False


# ============================================================
# TRADING SESSION
# ============================================================

def wait_for_session_start(config: dict) -> bool:
    """Block until start_time if session timing is enabled.

    Returns False if a stop was requested while waiting.
    """
    if not is_session_enabled(config):
        logging.info("Trading session timing is disabled. No start/stop window.")
        return True
    last_log = 0.0
    while is_before_session_start(config):
        if stop_requested():
            return False
        now = now_in_session_tz(config)
        start, _stop = session_window(config, now)
        remaining = (start - now).total_seconds()
        if time.monotonic() - last_log >= 60:
            logging.info(
                "Waiting for trading session start at %s (now %s).",
                start.strftime("%H:%M"),
                now.strftime("%H:%M:%S"),
            )
            last_log = time.monotonic()
        if interruptible_sleep(min(30.0, max(1.0, remaining))):
            return False
    logging.info("Trading session started.")
    return True


def handle_session_end(dhan, config: dict, state: BotState) -> None:
    """Stop new entries at stop_time. Optionally flatten, then halt."""
    logging.info("Trading session ended.")
    state.shutdown_reason = "SESSION_END"
    if config["trading_session"].get("close_all_positions_at_stop"):
        close_all_positions(dhan, config, state)
    else:
        logging.info("close_all_positions_at_stop is false. Positions were left open.")
    state.bot_running = False


# ============================================================
# STRATEGY CYCLE
# ============================================================

def maybe_fetch_new_candle(
    dhan,
    config: dict,
    state: BotState,
    cached: list[Candle],
) -> list[Candle]:
    """Fetch candles when a new bar may have closed; otherwise reuse cache."""
    timeframe = config["strategy"]["timeframe"]
    now = now_in_session_tz(config)
    watermark = latest_possible_completed_start(now, timeframe)
    last_watermark = state.extra.get("candle_fetch_watermark")
    if cached and last_watermark is not None and last_watermark == watermark:
        return cached
    candles = fetch_candles(dhan, config)
    if candles:
        state.extra["candle_fetch_watermark"] = watermark
    return candles


def log_loop_status(state: BotState, ltp: Optional[float]) -> None:
    """One compact heartbeat so the CLI still shows position between new bars."""
    ltp_text = f"{ltp:.2f}" if ltp is not None else "n/a"
    candle = (
        state.last_processed_candle.isoformat()
        if state.last_processed_candle is not None
        else "n/a"
    )
    fast = f"{state.last_fast_ma:.4f}" if state.last_fast_ma is not None else "n/a"
    slow = f"{state.last_slow_ma:.4f}" if state.last_slow_ma is not None else "n/a"
    parts = [
        f"position={state.current_position}",
        f"qty={state.position_quantity}",
        f"ltp={ltp_text}",
        f"last_candle={candle}",
        f"signal={state.last_signal}",
        f"fast={fast}",
        f"slow={slow}",
    ]
    if state.current_position != "FLAT":
        parts.append(
            f"entry={state.entry_price:.2f}" if state.entry_price else "entry=n/a"
        )
        parts.append(
            f"TP={state.take_profit_price:.2f}"
            if state.take_profit_price
            else "TP=off"
        )
        parts.append(
            f"SL={state.stop_loss_price:.2f}" if state.stop_loss_price else "SL=off"
        )
    logging.info("Status: %s", " ".join(parts))


def process_new_candle(
    dhan,
    config: dict,
    state: BotState,
    candles: list[Candle],
    ltp: Optional[float],
    allow_new_entries: bool,
) -> None:
    """Run MA + crossover once per completed candle timestamp."""
    slow = int(config["strategy"]["slow_ma_period"])
    if len(candles) < slow + 2:
        logging.warning(
            "Insufficient candles (%s). Need at least %s. Not trading.",
            len(candles),
            slow + 2,
        )
        return

    latest = candles[-1]
    if state.last_processed_candle is not None and latest.timestamp <= state.last_processed_candle:
        return

    signal, prev_fast, prev_slow, fast_ma, slow_ma = generate_signal(candles, config)
    state.last_fast_ma = fast_ma
    state.last_slow_ma = slow_ma
    logging.info(
        "Candle processed %s close=%.2f prev_fast=%s prev_slow=%s fast=%s slow=%s signal=%s",
        latest.timestamp.isoformat(),
        latest.close,
        f"{prev_fast:.4f}" if prev_fast is not None else "n/a",
        f"{prev_slow:.4f}" if prev_slow is not None else "n/a",
        f"{fast_ma:.4f}" if fast_ma is not None else "n/a",
        f"{slow_ma:.4f}" if slow_ma is not None else "n/a",
        signal,
    )
    state.last_processed_candle = latest.timestamp
    state.last_signal = signal

    if signal == "HOLD":
        return
    logging.info("Signal generated: %s", signal)

    if state.extra.get("unmanaged_existing"):
        logging.info(
            "Signal ignored because an unmanaged broker position exists "
            "(manage_existing_positions=false)."
        )
        return
    if state.pending_order_id or state.order_in_flight:
        logging.info("Signal ignored because an order is still pending.")
        return
    if not allow_new_entries and signal:
        # Exits are still allowed after session stop only via close_all, not here.
        logging.info("New entries are not allowed in this phase. Signal stored only.")
        return

    action = action_for_signal(
        signal, state.current_position, config["strategy"]["trading_mode"]
    )
    if action is None:
        logging.info(
            "No action for signal=%s position=%s mode=%s (duplicate or disallowed side).",
            signal,
            state.current_position,
            config["strategy"]["trading_mode"],
        )
        return

    logging.info("Strategy action: %s", action)
    if action == "ENTER_LONG":
        place_entry_order(dhan, config, state, "BUY", ltp)
    elif action == "ENTER_SHORT":
        place_entry_order(dhan, config, state, "SELL", ltp)
    elif action == "EXIT_LONG" or action == "EXIT_SHORT":
        place_exit_order(dhan, config, state, ltp)
    elif action == "REVERSE_TO_LONG":
        reverse_position(dhan, config, state, "LONG", ltp)
    elif action == "REVERSE_TO_SHORT":
        reverse_position(dhan, config, state, "SHORT", ltp)


# ============================================================
# MAIN LOOP
# ============================================================

def run_trading_loop(dhan, config: dict, state: BotState) -> None:
    """Poll candles, signals, positions, and TP/SL until a shutdown reason."""
    interval = float(config["polling"]["interval_seconds"])
    reconcile_every = int(config["polling"]["reconcile_every_cycles"])
    cached_candles: list[Candle] = []
    logging.info("Entering trading loop (poll every %s seconds).", interval)

    while state.bot_running and not stop_requested():
        state.loop_cycle += 1
        now = now_in_session_tz(config)

        if is_after_session_stop(config, now):
            handle_session_end(dhan, config, state)
            break

        allow_entries = True
        if is_before_session_start(config, now):
            allow_entries = False

        if sync_pending_order(dhan, config, state):
            if interruptible_sleep(interval):
                break
            continue

        if state.loop_cycle == 1 or state.loop_cycle % reconcile_every == 0:
            reconcile_state(dhan, config, state)

        ltp = get_ltp(
            dhan,
            str(config["instrument"]["security_id"]),
            str(config["instrument"]["exchange_segment"]),
        )

        if monitor_tpsl(dhan, config, state, ltp):
            if config["risk"].get("stop_bot_on_tp") or config["risk"].get("stop_bot_on_sl"):
                if state.current_position != "FLAT":
                    close_all_positions(dhan, config, state)
            state.bot_running = False
            break

        cached_candles = maybe_fetch_new_candle(dhan, config, state, cached_candles)
        if not cached_candles:
            logging.warning("No usable candles this cycle. Waiting.")
            if interruptible_sleep(interval):
                break
            continue

        process_new_candle(dhan, config, state, cached_candles, ltp, allow_entries)
        log_loop_status(state, ltp)

        if stop_requested():
            break
        if interruptible_sleep(interval):
            break

    if stop_requested() and not state.shutdown_reason:
        state.shutdown_reason = "MANUAL_STOP"


def adopt_or_respect_existing(dhan, config: dict, state: BotState) -> None:
    """At startup, either adopt a broker position or leave it completely alone."""
    if is_dry_run(config):
        logging.info("Dry run: broker positions are displayed but not adopted for simulated trading.")
        return
    read_ok, row = get_open_position(dhan, config)
    if not read_ok:
        logging.error("Could not read positions while deciding whether to adopt an existing trade.")
        return
    if row is None:
        return
    side, qty, avg = broker_side_from_row(row)
    if not config["shutdown"].get("manage_existing_positions"):
        logging.warning(
            "Existing %s qty=%s will not be managed (manage_existing_positions=false). "
            "The bot will not add to it or close it.",
            side,
            qty,
        )
        state.extra["unmanaged_existing"] = True
        return
    logging.info("Adopting existing %s qty=%s avg=%.2f for TP/SL and strategy exits.", side, qty, avg)
    apply_broker_position(state, config, row)
    state.adopted_existing = True


def graceful_shutdown(dhan, config: dict, state: BotState, reason: str) -> None:
    """Stop entries, optionally flatten, verify, log, and exit the loop.

    Does not leave the bot in an undefined state: local flags are set even
    when the broker flatten fails, and the failure is logged clearly.
    """
    logging.info("Shutdown requested (%s).", reason)
    state.bot_running = False
    if not state.shutdown_reason:
        state.shutdown_reason = reason

    close_positions = False
    if reason in {"SESSION_END"}:
        close_positions = bool(config["trading_session"].get("close_all_positions_at_stop"))
    elif reason in {"TAKE_PROFIT", "STOP_LOSS"}:
        close_positions = state.current_position != "FLAT"
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

    logging.info("STOP_REASON = %s", state.shutdown_reason)
    logging.info("Bot stopped.")


# ============================================================
# MAIN
# ============================================================

def main() -> int:
    """Load configuration, authenticate, then run the trading loop."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    install_signal_handlers()
    dhan = None
    config: dict = {}
    state = BotState()

    try:
        config = load_config()
        setup_logging(config)
        load_environment()
        validate_config(config)
        validate_safety_config(config)
        logging.info("Configuration loaded and validated.")

        consume_leftover_stop_file()
        if stop_requested():
            logging.info("Stop requested at startup. No orders were placed.")
            return 0

        print_startup_banner(config)

        dhan = create_dhan_client()
        logging.info("Authentication successful. Dhan client initialized.")

        existing = log_existing_positions(dhan, config)
        if existing is not None:
            adopt_or_respect_existing(dhan, config, state)

        if not wait_for_session_start(config):
            graceful_shutdown(dhan, config, state, "MANUAL_STOP")
            return 0

        if stop_requested():
            graceful_shutdown(dhan, config, state, "MANUAL_STOP")
            return 0

        run_trading_loop(dhan, config, state)

        reason = state.shutdown_reason or ("MANUAL_STOP" if stop_requested() else "SESSION_END")
        graceful_shutdown(dhan, config, state, reason)
        return 0

    except (ConfigError, SafetyError, CredentialError) as exc:
        logging.error("%s", exc)
        return 1
    except KeyboardInterrupt:
        graceful_shutdown(dhan, config, state, "SIGINT")
        return 0
    except Exception:
        logging.exception("Unexpected error. No additional order will be placed.")
        try:
            if config and dhan is not None:
                graceful_shutdown(dhan, config, state, "ERROR")
        except Exception:
            logging.exception("Shutdown after error also failed.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
