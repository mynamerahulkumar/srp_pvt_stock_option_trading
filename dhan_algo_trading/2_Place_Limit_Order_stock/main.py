#!/usr/bin/env python3
"""Dhan LIMIT Order Algo for NSE equity.

Places at most one LIMIT order per run, then monitors it. Optional
modification, cancellation, and software TP/SL are config-driven.
Stop the process with stop.py; that does not cancel the broker order
or close an open position.
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
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Optional

import yaml
from dotenv import load_dotenv

try:
    from dhanhq import DhanContext, dhanhq
except ImportError:
    from dhanhq import dhanhq

    DhanContext = None


# ============================================================
# PROJECT PATHS
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "config.yaml"
STOP_FILE = BASE_DIR / ".stop"
ENV_FILE = BASE_DIR / ".env"

NOTIONAL_WARN_RUPEES = 50000
READ_RETRY_ATTEMPTS = 3
READ_RETRY_SLEEP_SECONDS = 1.0

TERMINAL_STATES = {
    "FILLED",
    "CANCELLED",
    "REJECTED",
    "EXPIRED",
    "FAILED",
}

# Dhan returns these names. We keep the raw value in logs and normalize
# only for control flow.
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

MODIFIABLE_STATES = {"PENDING", "OPEN", "PARTIALLY_FILLED"}
CANCELLABLE_STATES = {"PENDING", "OPEN", "PARTIALLY_FILLED"}

# Set True immediately before the single place_order call.
# A network timeout is not proof that Dhan rejected the order.
_placement_attempted = False
_exit_attempted = False
_shutdown_requested = False
_last_good_ltp: Optional[float] = None


class ConfigError(Exception):
    """Invalid or incomplete configuration."""


class SafetyError(Exception):
    """Live-trading safety check failed."""


class CredentialError(Exception):
    """Missing or invalid credentials."""


# ============================================================
# ENVIRONMENT
# ============================================================

def load_environment() -> None:
    """Load DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN from BASE_DIR/.env."""
    if ENV_FILE.exists():
        load_dotenv(ENV_FILE)
    else:
        logging.warning("No .env file found at %s. Checking process environment.", ENV_FILE)

    client_id = (os.environ.get("DHAN_CLIENT_ID") or "").strip()
    access_token = (os.environ.get("DHAN_ACCESS_TOKEN") or "").strip()
    if not client_id or not access_token:
        raise CredentialError(
            "ERROR: Dhan credentials are missing.\nNo order was placed."
        )


# ============================================================
# CONFIGURATION
# ============================================================

def load_config() -> dict:
    """Load config.yaml from BASE_DIR."""
    if not CONFIG_FILE.exists():
        raise ConfigError(
            f"ERROR: config.yaml was not found at {CONFIG_FILE}.\nNo order was placed."
        )
    try:
        with CONFIG_FILE.open("r", encoding="utf-8") as handle:
            config = yaml.safe_load(handle)
    except yaml.YAMLError as exc:
        raise ConfigError(
            f"ERROR: config.yaml is invalid YAML.\n{exc}\nNo order was placed."
        ) from exc
    if not isinstance(config, dict):
        raise ConfigError("ERROR: config.yaml must contain a mapping.\nNo order was placed.")
    return config


def _require_section(config: dict, name: str) -> dict:
    section = config.get(name)
    if not isinstance(section, dict):
        raise ConfigError(
            f"ERROR: config.yaml is missing the '{name}' section.\nNo order was placed."
        )
    return section


def _as_positive_number(value: Any, field_name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(
            f"ERROR: {field_name} must be a number.\nNo order was placed."
        ) from exc
    if number <= 0:
        raise ConfigError(
            f"ERROR: {field_name} must be greater than 0.\nNo order was placed."
        )
    return number


def _as_positive_int(value: Any, field_name: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(
            f"ERROR: {field_name} must be an integer.\nNo order was placed."
        ) from exc
    if number <= 0:
        raise ConfigError(
            f"ERROR: {field_name} must be greater than 0.\nNo order was placed."
        )
    return number


def _optional_positive_number(value: Any, field_name: str) -> Optional[float]:
    if value in (None, ""):
        return None
    return _as_positive_number(value, field_name)


def _as_non_negative_int(value: Any, field_name: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(
            f"ERROR: {field_name} must be an integer.\nNo order was placed."
        ) from exc
    if number < 0:
        raise ConfigError(
            f"ERROR: {field_name} must be 0 or greater.\nNo order was placed."
        )
    return number


def _is_tick_multiple(price: float, tick_size: float) -> bool:
    try:
        price_dec = Decimal(str(price))
        tick_dec = Decimal(str(tick_size))
    except InvalidOperation:
        return False
    if tick_dec <= 0:
        return False
    quotient = price_dec / tick_dec
    return quotient == quotient.to_integral_value()


# ============================================================
# VALIDATION
# ============================================================

def validate_config(config: dict) -> None:
    """Fail early if trading configuration is incomplete or invalid."""
    strategy = _require_section(config, "strategy")
    instrument = _require_section(config, "instrument")
    order = _require_section(config, "order")
    management = _require_section(config, "management")
    runtime = _require_section(config, "runtime")
    safety = _require_section(config, "safety")
    _require_section(config, "logging")

    if not strategy.get("enabled", True):
        raise ConfigError("ERROR: strategy.enabled is false.\nNo order was placed.")

    symbol = str(instrument.get("symbol") or "").strip()
    if not symbol:
        raise ConfigError("ERROR: instrument.symbol is missing.\nNo order was placed.")

    security_id = str(instrument.get("security_id") or "").strip()
    if not security_id or security_id in {"0", "None"}:
        raise ConfigError(
            f"ERROR: security_id is not configured for {symbol}.\nNo order was placed."
        )

    exchange_segment = str(instrument.get("exchange_segment") or "").strip().upper()
    if not exchange_segment:
        raise ConfigError(
            "ERROR: instrument.exchange_segment is missing.\nNo order was placed."
        )

    transaction_type = str(order.get("transaction_type") or "").strip().upper()
    if transaction_type not in {"BUY", "SELL"}:
        raise ConfigError(
            "ERROR: order.transaction_type must be BUY or SELL.\nNo order was placed."
        )

    order_type = str(order.get("order_type") or "").strip().upper()
    if order_type != "LIMIT":
        raise ConfigError(
            "ERROR: This algo only supports LIMIT orders.\nNo order was placed."
        )

    product_type = str(order.get("product_type") or "").strip().upper()
    if not product_type:
        raise ConfigError("ERROR: order.product_type is missing.\nNo order was placed.")

    validity = str(order.get("validity") or "").strip().upper()
    if validity not in {"DAY", "IOC"}:
        raise ConfigError(
            "ERROR: order.validity must be DAY or IOC.\nNo order was placed."
        )

    quantity = _as_positive_int(order.get("quantity"), "order.quantity")
    max_quantity = _as_positive_int(safety.get("max_quantity"), "safety.max_quantity")
    if quantity > max_quantity:
        raise ConfigError(
            "ERROR: order.quantity exceeds safety.max_quantity.\nNo order was placed."
        )

    entry_price = _as_positive_number(order.get("entry_price"), "order.entry_price")
    limit_price = _as_positive_number(order.get("limit_price"), "order.limit_price")

    tick_size = instrument.get("tick_size")
    if tick_size not in (None, ""):
        tick_value = _as_positive_number(tick_size, "instrument.tick_size")
        if not _is_tick_multiple(limit_price, tick_value):
            raise ConfigError(
                "ERROR: Invalid LIMIT price.\nNo order was placed."
            )
        if not _is_tick_multiple(entry_price, tick_value):
            raise ConfigError(
                "ERROR: Invalid entry price.\nNo order was placed."
            )

    modification = management.get("modification")
    if not isinstance(modification, dict):
        raise ConfigError(
            "ERROR: management.modification is missing.\nNo order was placed."
        )
    if modification.get("enabled"):
        _as_positive_number(
            modification.get("new_limit_price"),
            "management.modification.new_limit_price",
        )
        _as_non_negative_int(
            modification.get("max_modifications", 0),
            "management.modification.max_modifications",
        )
        new_limit_price = float(modification["new_limit_price"])
        if tick_size not in (None, ""):
            if not _is_tick_multiple(new_limit_price, float(tick_size)):
                raise ConfigError(
                    "ERROR: Invalid LIMIT price.\nNo order was placed."
                )

    cancellation = management.get("cancellation")
    if not isinstance(cancellation, dict):
        raise ConfigError(
            "ERROR: management.cancellation is missing.\nNo order was placed."
        )
    if cancellation.get("enabled"):
        _as_positive_int(
            cancellation.get("cancel_after_seconds"),
            "management.cancellation.cancel_after_seconds",
        )

    _validate_risk_config(
        management,
        transaction_type=transaction_type,
        limit_price=limit_price,
        tick_size=tick_size,
    )

    _as_positive_number(runtime.get("poll_interval_seconds"), "runtime.poll_interval_seconds")
    _as_positive_number(
        runtime.get("max_order_wait_seconds"),
        "runtime.max_order_wait_seconds",
    )
    if float(runtime["poll_interval_seconds"]) < 1:
        raise ConfigError(
            "ERROR: runtime.poll_interval_seconds must be at least 1.\nNo order was placed."
        )


def _validate_risk_config(
    management: dict,
    transaction_type: str,
    limit_price: float,
    tick_size: Any,
) -> None:
    risk = management.get("risk")
    if risk in (None, ""):
        return
    if not isinstance(risk, dict):
        raise ConfigError(
            "ERROR: management.risk must be a mapping.\nNo order was placed."
        )
    if not risk.get("enabled"):
        return

    tp_percent = _optional_positive_number(
        risk.get("take_profit_percent"),
        "management.risk.take_profit_percent",
    )
    sl_percent = _optional_positive_number(
        risk.get("stop_loss_percent"),
        "management.risk.stop_loss_percent",
    )
    tp_price = _optional_positive_number(
        risk.get("take_profit_price"),
        "management.risk.take_profit_price",
    )
    sl_price = _optional_positive_number(
        risk.get("stop_loss_price"),
        "management.risk.stop_loss_price",
    )
    if tp_percent is None and tp_price is None:
        raise ConfigError(
            "ERROR: Provide take_profit_percent or take_profit_price.\nNo order was placed."
        )
    if sl_percent is None and sl_price is None:
        raise ConfigError(
            "ERROR: Provide stop_loss_percent or stop_loss_price.\nNo order was placed."
        )

    if tick_size not in (None, ""):
        tick_value = float(tick_size)
        if tp_price is not None and not _is_tick_multiple(tp_price, tick_value):
            raise ConfigError("ERROR: Invalid take-profit price.\nNo order was placed.")
        if sl_price is not None and not _is_tick_multiple(sl_price, tick_value):
            raise ConfigError("ERROR: Invalid stop-loss price.\nNo order was placed.")

    side = transaction_type.upper()
    if tp_price is not None:
        if side == "BUY" and tp_price <= limit_price:
            raise ConfigError(
                "ERROR: BUY take-profit price must be above limit_price.\nNo order was placed."
            )
        if side == "SELL" and tp_price >= limit_price:
            raise ConfigError(
                "ERROR: SELL take-profit price must be below limit_price.\nNo order was placed."
            )
    if sl_price is not None:
        if side == "BUY" and sl_price >= limit_price:
            raise ConfigError(
                "ERROR: BUY stop-loss price must be below limit_price.\nNo order was placed."
            )
        if side == "SELL" and sl_price <= limit_price:
            raise ConfigError(
                "ERROR: SELL stop-loss price must be above limit_price.\nNo order was placed."
            )


def validate_safety_config(config: dict) -> None:
    """Live trading requires dry_run=false AND allow_live_trading=true."""
    safety = _require_section(config, "safety")
    dry_run = bool(safety.get("dry_run", True))
    allow_live_trading = bool(safety.get("allow_live_trading", False))
    if dry_run:
        return
    if not allow_live_trading:
        raise SafetyError(
            "ERROR: Live trading is not allowed. "
            "Set safety.dry_run: false and safety.allow_live_trading: true.\n"
            "No order was placed."
        )


def setup_logging(config: dict) -> None:
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


# ============================================================
# STOP SIGNAL
# ============================================================

def consume_leftover_stop_file() -> None:
    """Allow a new run after a previous stop.py.

    .stop is deleted once at startup only. It is never deleted while
    trading, so a stop requested during monitoring cannot be lost.
    """
    if STOP_FILE.exists():
        STOP_FILE.unlink()
        logging.info(
            "Cleared leftover .stop from a previous run. Starting fresh."
        )


def stop_requested() -> bool:
    return STOP_FILE.exists() or _shutdown_requested


def _handle_shutdown_signal(signum, _frame) -> None:
    global _shutdown_requested
    _shutdown_requested = True
    logging.info("Received signal %s. Stop requested.", signum)


def install_signal_handlers() -> None:
    signal.signal(signal.SIGINT, _handle_shutdown_signal)
    signal.signal(signal.SIGTERM, _handle_shutdown_signal)


# ============================================================
# DHAN CLIENT
# ============================================================

def create_dhan_client():
    """Build a Dhan SDK client from environment credentials."""
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
            "ERROR: Dhan authentication failed.\nNo order was placed."
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


def _unwrap_dhan_data(response: Any) -> Optional[dict]:
    """Dhan payloads are sometimes a dict and sometimes a one-item list."""
    if not isinstance(response, dict):
        return None
    data = response.get("data")
    if isinstance(data, list):
        if not data:
            return None
        first = data[0]
        return first if isinstance(first, dict) else None
    if isinstance(data, dict):
        return data
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


def risk_enabled(config: dict) -> bool:
    risk = (config.get("management") or {}).get("risk") or {}
    return bool(isinstance(risk, dict) and risk.get("enabled"))


def _risk_optional_price(risk: dict, key: str) -> Optional[float]:
    value = risk.get(key)
    if value in (None, ""):
        return None
    return float(value)


def calculate_take_profit(
    fill_price: float,
    take_profit_percent: Optional[float] = None,
    take_profit_price: Optional[float] = None,
    side: str = "BUY",
) -> float:
    if take_profit_price is not None:
        return float(take_profit_price)
    if take_profit_percent is None:
        raise ConfigError("ERROR: take_profit_percent or take_profit_price is required.")
    if side.upper() == "BUY":
        return fill_price * (1.0 + take_profit_percent / 100.0)
    return fill_price * (1.0 - take_profit_percent / 100.0)


def calculate_stop_loss(
    fill_price: float,
    stop_loss_percent: Optional[float] = None,
    stop_loss_price: Optional[float] = None,
    side: str = "BUY",
) -> float:
    if stop_loss_price is not None:
        return float(stop_loss_price)
    if stop_loss_percent is None:
        raise ConfigError("ERROR: stop_loss_percent or stop_loss_price is required.")
    if side.upper() == "BUY":
        return fill_price * (1.0 - stop_loss_percent / 100.0)
    return fill_price * (1.0 + stop_loss_percent / 100.0)


def resolve_risk_levels(config: dict, fill_price: float) -> tuple[float, float]:
    """Compute TP/SL from fill price. Absolute config prices override percent."""
    risk = (config.get("management") or {}).get("risk") or {}
    side = str(config["order"]["transaction_type"]).upper()
    tp_price = _risk_optional_price(risk, "take_profit_price")
    sl_price = _risk_optional_price(risk, "stop_loss_price")
    tp_percent = _risk_optional_price(risk, "take_profit_percent")
    sl_percent = _risk_optional_price(risk, "stop_loss_percent")
    take_profit = calculate_take_profit(
        fill_price,
        take_profit_percent=None if tp_price is not None else tp_percent,
        take_profit_price=tp_price,
        side=side,
    )
    stop_loss = calculate_stop_loss(
        fill_price,
        stop_loss_percent=None if sl_price is not None else sl_percent,
        stop_loss_price=sl_price,
        side=side,
    )
    return take_profit, stop_loss


def should_trigger_tp(current_price: Optional[float], take_profit_price: float, side: str) -> bool:
    if current_price is None:
        return False
    if side.upper() == "BUY":
        return current_price >= take_profit_price
    return current_price <= take_profit_price


def should_trigger_sl(current_price: Optional[float], stop_loss_price: float, side: str) -> bool:
    if current_price is None:
        return False
    if side.upper() == "BUY":
        return current_price <= stop_loss_price
    return current_price >= stop_loss_price


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
    """Read last traded price. Quote APIs are limited to 1 request/sec."""
    global _last_good_ltp
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
# ORDER CREATION
# ============================================================

def build_order_request(config: dict) -> dict:
    """Convert config.yaml into Dhan place_order keyword arguments."""
    instrument = config["instrument"]
    order = config["order"]
    tag = f"L{uuid.uuid4().hex[:12]}"
    return {
        "security_id": str(instrument["security_id"]).strip(),
        "exchange_segment": _map_exchange_segment(instrument["exchange_segment"]),
        "transaction_type": _map_transaction_type(order["transaction_type"]),
        "quantity": int(order["quantity"]),
        "order_type": _map_order_type(order["order_type"]),
        "product_type": _map_product_type(order["product_type"]),
        "price": float(order["limit_price"]),
        "trigger_price": 0,
        "disclosed_quantity": 0,
        "after_market_order": False,
        "validity": _map_validity(order["validity"]),
        "tag": tag,
    }


def print_order_summary(config: dict) -> None:
    instrument = config["instrument"]
    order = config["order"]
    safety = config["safety"]
    mode = "DRY RUN" if safety.get("dry_run", True) else "LIVE"
    logging.info("Application started")
    logging.info("Mode: %s", mode)
    logging.info("Symbol: %s", instrument.get("symbol"))
    logging.info("Security ID: %s", instrument.get("security_id"))
    logging.info("Exchange: %s", instrument.get("exchange_segment"))
    logging.info("Transaction: %s", order.get("transaction_type"))
    logging.info("Quantity: %s", order.get("quantity"))
    logging.info("Order Type: %s", order.get("order_type"))
    logging.info("Product Type: %s", order.get("product_type"))
    logging.info("Validity: %s", order.get("validity"))
    logging.info("Entry Price: %.2f", float(order["entry_price"]))
    logging.info("Limit Price: %.2f", float(order["limit_price"]))
    if risk_enabled(config):
        take_profit, stop_loss = resolve_risk_levels(config, float(order["limit_price"]))
        logging.info("Take Profit: %.2f (preview from limit_price)", take_profit)
        logging.info("Stop Loss: %.2f (preview from limit_price)", stop_loss)
        logging.info("Exit Type: MARKET")

    notional = float(order["limit_price"]) * int(order["quantity"])
    if notional > NOTIONAL_WARN_RUPEES:
        logging.warning(
            "Order notional is Rs. %.2f, which exceeds Rs. %s.",
            notional,
            NOTIONAL_WARN_RUPEES,
        )


def _format_order_box(config: dict, heading: str) -> str:
    instrument = config["instrument"]
    order = config["order"]
    lines = [
        "============================================================",
        heading,
        "============================================================",
        "",
        f"Symbol          : {instrument.get('symbol')}",
        f"Security ID     : {instrument.get('security_id')}",
        f"Exchange        : {instrument.get('exchange_segment')}",
        f"Transaction     : {order.get('transaction_type')}",
        f"Quantity        : {order.get('quantity')}",
        f"Order Type      : {order.get('order_type')}",
        f"Product Type    : {order.get('product_type')}",
        f"Validity        : {order.get('validity')}",
        f"Entry Price     : {float(order['entry_price']):.2f}",
        f"Limit Price     : {float(order['limit_price']):.2f}",
    ]
    if risk_enabled(config):
        take_profit, stop_loss = resolve_risk_levels(config, float(order["limit_price"]))
        lines.extend(
            [
                f"Take Profit     : {take_profit:.2f}",
                f"Stop Loss       : {stop_loss:.2f}",
                "Exit Type       : MARKET",
            ]
        )
    lines.append("")
    return "\n".join(lines)


# ============================================================
# DRY RUN
# ============================================================

def run_dry_run(config: dict) -> None:
    """Show the order that would be sent. Never call Dhan place_order."""
    box = _format_order_box(config, "DRY RUN MODE")
    box += "\nNO REAL ORDER HAS BEEN PLACED.\n"
    box += "\n============================================================"
    print(box)
    logging.info("Dry run complete. No Dhan order-placement API was called.")


def confirm_live_order(config: dict) -> bool:
    """Require the exact word YES before a live order."""
    if not sys.stdin.isatty():
        logging.error(
            "ERROR: Live confirmation is required, but stdin is not a TTY. "
            "For nohup/background runs set safety.require_confirmation: false "
            "after reviewing the order.\nNo order was placed."
        )
        return False
    print(_format_order_box(config, "LIVE ORDER CONFIRMATION"))
    print("Type YES to place this LIVE order:")
    try:
        answer = input().strip()
    except EOFError:
        logging.error("ERROR: Confirmation aborted.\nNo order was placed.")
        return False
    if answer != "YES":
        logging.info("Confirmation was not YES. Aborting. No order was placed.")
        return False
    return True


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
    filled_quantity = _safe_int(
        payload.get("filledQty", payload.get("filled_qty", 0)),
        0,
    )
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
            response = dhan.get_order_by_id(order_id=order_id)
            if not isinstance(response, dict):
                raise RuntimeError("Unexpected order-status response.")
            if str(response.get("status", "")).lower() != "success":
                raise RuntimeError(_dhan_error_text(response))
            payload = _unwrap_dhan_data(response)
            if not payload:
                raise RuntimeError("Order status payload was empty.")
            return _status_from_payload(payload, requested_quantity)
        except TypeError:
            try:
                response = dhan.get_order_by_id(order_id)
                if str(response.get("status", "")).lower() != "success":
                    raise RuntimeError(_dhan_error_text(response))
                payload = _unwrap_dhan_data(response)
                if not payload:
                    raise RuntimeError("Order status payload was empty.")
                return _status_from_payload(payload, requested_quantity)
            except Exception as exc:
                last_error = exc
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
        response = dhan.get_order_by_correlationID(tag)
        if isinstance(response, dict) and str(response.get("status", "")).lower() == "success":
            payload = _unwrap_dhan_data(response)
            if payload and payload.get("orderId"):
                return str(payload["orderId"])
            data = response.get("data")
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and str(item.get("correlationId") or item.get("tag") or "") == tag:
                        if item.get("orderId"):
                            return str(item["orderId"])
    except Exception:
        logging.warning("Could not look up the order by correlation ID.")

    try:
        response = dhan.get_order_list()
        if not isinstance(response, dict) or str(response.get("status", "")).lower() != "success":
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
            if item_tag == tag or (item_security == str(security_id) and item_tag == tag):
                if item.get("orderId"):
                    return str(item["orderId"])
    except Exception:
        logging.warning("Could not look up the order from the order book.")
    return None


# ============================================================
# ORDER PLACEMENT
# ============================================================

def place_limit_order(dhan, config: dict) -> Optional[str]:
    """Submit exactly one LIMIT order. Never retry placement blindly."""
    global _placement_attempted

    if stop_requested():
        logging.info("Stop requested before order placement. No order was placed.")
        return None

    request = build_order_request(config)
    tag = request["tag"]
    logging.info(
        "Submitting LIMIT order: symbol=%s security_id=%s exchange=%s "
        "transaction=%s quantity=%s entry_price=%.2f limit_price=%.2f tag=%s",
        config["instrument"]["symbol"],
        request["security_id"],
        request["exchange_segment"],
        request["transaction_type"],
        request["quantity"],
        float(config["order"]["entry_price"]),
        request["price"],
        tag,
    )

    # Do not blindly retry order placement.
    # A network timeout does not prove that Dhan rejected the order.
    # The broker may already have accepted the order.
    if _placement_attempted:
        logging.error("Order placement was already attempted this run. Refusing to submit again.")
        return None
    _placement_attempted = True

    response = None
    try:
        response = dhan.place_order(**request)
    except Exception as exc:
        logging.error("Order placement returned an uncertain result: %s", exc)
        recovered = find_order_id_after_uncertain_place(
            dhan, tag, request["security_id"]
        )
        if recovered:
            logging.info("Recovered order ID from broker state: %s", recovered)
            return recovered
        logging.error(
            "Could not confirm whether Dhan accepted the order. "
            "Not submitting another order."
        )
        return None

    if not isinstance(response, dict):
        logging.error("Unexpected place-order response. Checking broker state.")
        return find_order_id_after_uncertain_place(dhan, tag, request["security_id"])

    if str(response.get("status", "")).lower() != "success":
        logging.error("Dhan rejected the order: %s", _dhan_error_text(response))
        return None

    payload = _unwrap_dhan_data(response)
    order_id = None
    if payload:
        order_id = payload.get("orderId") or payload.get("order_id")
    if not order_id and isinstance(response.get("data"), dict):
        order_id = response["data"].get("orderId")
    if not order_id:
        logging.error("Order was accepted but no order ID was returned. Checking broker state.")
        return find_order_id_after_uncertain_place(dhan, tag, request["security_id"])

    logging.info("Order submitted. Order ID: %s", order_id)
    return str(order_id)


# ============================================================
# ORDER MODIFICATION
# ============================================================

def modify_order(dhan, config: dict, order_id: str, new_limit_price: float) -> bool:
    """Modify an open LIMIT order. Uses full original quantity."""
    if stop_requested():
        logging.info("Stop requested. Skipping modification.")
        return False

    quantity = int(config["order"]["quantity"])
    order_type = _map_order_type(config["order"]["order_type"])
    validity = _map_validity(config["order"]["validity"])

    try:
        status = get_order_status(dhan, order_id, quantity)
    except Exception as exc:
        logging.error("Could not read status before modification: %s", exc)
        return False

    if status["status"] not in MODIFIABLE_STATES:
        logging.info(
            "Order is not modifiable. raw_status=%s normalized=%s",
            status["raw_status"],
            status["status"],
        )
        return False

    logging.info(
        "Modifying order %s to new limit price %.2f (requested qty %s)",
        order_id,
        new_limit_price,
        quantity,
    )
    try:
        response = dhan.modify_order(
            order_id=order_id,
            order_type=order_type,
            leg_name=None,
            quantity=quantity,
            price=float(new_limit_price),
            trigger_price=0,
            disclosed_quantity=0,
            validity=validity,
        )
    except Exception as exc:
        logging.error("Modification failed: %s", exc)
        return False

    if not isinstance(response, dict) or str(response.get("status", "")).lower() != "success":
        logging.error("Modification was not accepted: %s", _dhan_error_text(response))
        return False

    logging.info("Modification request accepted for order %s.", order_id)
    return True


# ============================================================
# ORDER CANCELLATION
# ============================================================

def cancel_order(dhan, order_id: str, requested_quantity: int) -> bool:
    """Cancel an open Dhan order using its order ID."""
    if stop_requested():
        logging.info("Stop requested. Skipping cancellation.")
        return False

    try:
        status = get_order_status(dhan, order_id, requested_quantity)
    except Exception as exc:
        logging.error("Could not read status before cancellation: %s", exc)
        return False

    if status["status"] == "FILLED":
        logging.info("Order is FILLED. Not cancelling.")
        return False
    if status["status"] not in CANCELLABLE_STATES:
        logging.info(
            "Order is not cancellable. raw_status=%s normalized=%s",
            status["raw_status"],
            status["status"],
        )
        return False

    logging.info("Cancelling order %s.", order_id)
    try:
        response = dhan.cancel_order(order_id=order_id)
    except Exception as exc:
        logging.error("Cancellation failed: %s", exc)
        return False

    if not isinstance(response, dict) or str(response.get("status", "")).lower() != "success":
        logging.error("Cancellation was not accepted: %s", _dhan_error_text(response))
        return False

    logging.info("Cancellation request accepted for order %s.", order_id)
    return True


# ============================================================
# EXIT ORDER
# ============================================================

def _opposite_side(transaction_type: str) -> str:
    if str(transaction_type).strip().upper() == "BUY":
        return "SELL"
    return "BUY"


def place_exit_order(dhan, config: dict, filled_quantity: int) -> Optional[str]:
    """Submit exactly one opposite MARKET exit for the filled quantity."""
    global _exit_attempted

    if stop_requested():
        logging.info("Stop requested. Not placing a TP/SL exit order.")
        return None
    if filled_quantity <= 0:
        logging.info("No filled quantity. Not placing an exit order.")
        return None
    if _exit_attempted:
        logging.error("Exit placement was already attempted this run. Refusing to submit again.")
        return None

    instrument = config["instrument"]
    order = config["order"]
    tag = f"X{uuid.uuid4().hex[:12]}"
    request = {
        "security_id": str(instrument["security_id"]).strip(),
        "exchange_segment": _map_exchange_segment(instrument["exchange_segment"]),
        "transaction_type": _map_transaction_type(_opposite_side(order["transaction_type"])),
        "quantity": int(filled_quantity),
        "order_type": _map_order_type("MARKET"),
        "product_type": _map_product_type(order["product_type"]),
        "price": 0,
        "trigger_price": 0,
        "disclosed_quantity": 0,
        "after_market_order": False,
        "validity": _map_validity(order["validity"]),
        "tag": tag,
    }
    logging.info(
        "Submitting MARKET exit: symbol=%s security_id=%s side=%s quantity=%s tag=%s",
        instrument.get("symbol"),
        request["security_id"],
        request["transaction_type"],
        request["quantity"],
        tag,
    )

    # Do not blindly retry exit placement.
    _exit_attempted = True
    response = None
    try:
        response = dhan.place_order(**request)
    except Exception as exc:
        logging.error("Exit placement returned an uncertain result: %s", exc)
        recovered = find_order_id_after_uncertain_place(
            dhan, tag, request["security_id"]
        )
        if recovered:
            logging.info("Recovered exit order ID from broker state: %s", recovered)
            return recovered
        logging.error(
            "Could not confirm whether Dhan accepted the exit. "
            "Not submitting another exit."
        )
        return None

    if not isinstance(response, dict):
        logging.error("Unexpected exit response. Checking broker state.")
        return find_order_id_after_uncertain_place(dhan, tag, request["security_id"])

    if str(response.get("status", "")).lower() != "success":
        logging.error("Dhan rejected the exit: %s", _dhan_error_text(response))
        return None

    payload = _unwrap_dhan_data(response)
    order_id = None
    if payload:
        order_id = payload.get("orderId") or payload.get("order_id")
    if not order_id and isinstance(response.get("data"), dict):
        order_id = response["data"].get("orderId")
    if not order_id:
        logging.error("Exit was accepted but no order ID was returned. Checking broker state.")
        return find_order_id_after_uncertain_place(dhan, tag, request["security_id"])

    logging.info("Exit submitted. Order ID: %s", order_id)
    return str(order_id)


def _monitor_exit_until_terminal(dhan, config: dict, exit_order_id: str, filled_quantity: int) -> None:
    poll_interval = float(config["runtime"]["poll_interval_seconds"])
    logging.info("Monitoring exit order %s", exit_order_id)
    while True:
        if stop_requested():
            graceful_shutdown(
                dhan,
                exit_order_id,
                "stop signal",
                position_open=True,
                extra_message="An exit order may already be working at the broker. It was not cancelled.",
            )
            return
        try:
            status = get_order_status(dhan, exit_order_id, filled_quantity)
        except Exception as exc:
            logging.error("Exit status poll failed: %s", exc)
            time.sleep(poll_interval)
            continue
        logging.info(
            "Exit %s | raw=%s | status=%s | filled=%s | remaining=%s",
            exit_order_id,
            status["raw_status"],
            status["status"],
            status["filled_quantity"],
            status["remaining_quantity"],
        )
        if status["status"] in TERMINAL_STATES:
            logging.info("Exit reached terminal state: %s", status["status"])
            return
        time.sleep(poll_interval)


# ============================================================
# TAKE PROFIT / STOP LOSS
# ============================================================

def monitor_risk(
    dhan,
    config: dict,
    fill_price: float,
    filled_quantity: int,
    entry_order_id: str,
) -> None:
    """Poll LTP after fill and place one MARKET exit if TP or SL is hit."""
    side = str(config["order"]["transaction_type"]).upper()
    take_profit, stop_loss = resolve_risk_levels(config, fill_price)
    poll_interval = max(float(config["runtime"]["poll_interval_seconds"]), 1.0)
    instrument = config["instrument"]

    logging.info(
        "Software TP/SL armed | fill=%.2f qty=%s tp=%.2f sl=%.2f side=%s",
        fill_price,
        filled_quantity,
        take_profit,
        stop_loss,
        side,
    )

    while True:
        if stop_requested():
            graceful_shutdown(
                dhan,
                entry_order_id,
                "stop signal",
                position_open=True,
                extra_message="No TP/SL exit order was placed. The position may still be open.",
            )
            return

        ltp = get_ltp(
            dhan,
            str(instrument["security_id"]).strip(),
            str(instrument["exchange_segment"]),
        )
        if ltp is None:
            logging.warning("No LTP available yet. Waiting.")
            time.sleep(poll_interval)
            continue

        logging.info(
            "LTP=%.2f | fill=%.2f | TP=%.2f | SL=%.2f",
            ltp,
            fill_price,
            take_profit,
            stop_loss,
        )

        # Check SL first so a gap through both levels prefers capital protection.
        reason = None
        if should_trigger_sl(ltp, stop_loss, side):
            reason = "SL"
        elif should_trigger_tp(ltp, take_profit, side):
            reason = "TP"

        if reason:
            if stop_requested():
                graceful_shutdown(
                    dhan,
                    entry_order_id,
                    "stop signal",
                    position_open=True,
                    extra_message="No TP/SL exit order was placed. The position may still be open.",
                )
                return
            logging.info("%s hit at LTP %.2f. Placing one MARKET exit.", reason, ltp)
            exit_order_id = place_exit_order(dhan, config, filled_quantity)
            if not exit_order_id:
                logging.error(
                    "Exit was not confirmed. Not retrying. The position may still be open."
                )
                return
            _monitor_exit_until_terminal(dhan, config, exit_order_id, filled_quantity)
            return

        time.sleep(poll_interval)


def _maybe_start_risk(dhan, config: dict, status: dict, entry_order_id: str) -> None:
    filled_quantity = int(status.get("filled_quantity") or 0)
    if filled_quantity <= 0:
        logging.info("No fill. TP/SL will not be armed.")
        return
    if not risk_enabled(config):
        logging.info("Risk management is disabled. Not monitoring TP/SL.")
        return
    if stop_requested():
        graceful_shutdown(
            dhan,
            entry_order_id,
            "stop signal",
            position_open=True,
            extra_message="No TP/SL exit order was placed. The position may still be open.",
        )
        return
    fill_price = _safe_float(status.get("fill_price"), 0.0)
    if fill_price <= 0:
        fill_price = _safe_float(status.get("current_price"), 0.0)
    if fill_price <= 0:
        fill_price = float(config["order"]["limit_price"])
    logging.info("Entry produced a fill. Starting software TP/SL monitoring.")
    monitor_risk(dhan, config, fill_price, filled_quantity, entry_order_id)


# ============================================================
# ORDER MONITORING
# ============================================================

def monitor_order(dhan, config: dict, order_id: str) -> None:
    """Poll one order until a terminal state, timeout, or stop signal."""
    runtime = config["runtime"]
    management = config["management"]
    order = config["order"]
    poll_interval = float(runtime["poll_interval_seconds"])
    max_wait = float(runtime["max_order_wait_seconds"])
    modification_cfg = management["modification"]
    cancellation_cfg = management["cancellation"]

    requested_quantity = int(order["quantity"])
    current_limit_price = float(order["limit_price"])
    modification_count = 0
    started_at = time.time()
    cancel_attempted = False

    logging.info("Monitoring order %s", order_id)

    while True:
        if stop_requested():
            graceful_shutdown(dhan, order_id, "stop signal")
            return

        elapsed = time.time() - started_at
        try:
            status = get_order_status(dhan, order_id, requested_quantity)
        except Exception as exc:
            logging.error("Status poll failed: %s", exc)
            if stop_requested():
                graceful_shutdown(dhan, order_id, "stop signal")
                return
            time.sleep(poll_interval)
            continue

        logging.info(
            "Order %s | raw=%s | status=%s | requested=%s | filled=%s | remaining=%s | price=%.2f",
            order_id,
            status["raw_status"],
            status["status"],
            status["requested_quantity"],
            status["filled_quantity"],
            status["remaining_quantity"],
            status["current_price"],
        )

        if status["status"] in TERMINAL_STATES:
            logging.info("Terminal state reached: %s", status["status"])
            _maybe_start_risk(dhan, config, status, order_id)
            return

        cancel_due = bool(cancellation_cfg.get("enabled")) and elapsed >= float(
            cancellation_cfg.get("cancel_after_seconds", 0)
        )
        max_wait_reached = elapsed >= max_wait

        # Never modify and cancel in the same cycle. Cancellation wins
        # once its timeout is due.
        if cancel_due or (max_wait_reached and cancellation_cfg.get("enabled")):
            if not cancel_attempted:
                cancel_order(dhan, order_id, requested_quantity)
                cancel_attempted = True
            time.sleep(poll_interval)
            continue

        if max_wait_reached:
            logging.warning(
                "Maximum wait of %s seconds reached. Cancellation is disabled. "
                "Stopping local monitoring. Broker order %s may still be %s.",
                int(max_wait),
                order_id,
                status["raw_status"] or status["status"],
            )
            logging.warning("No replacement order will be created.")
            return

        if (
            modification_cfg.get("enabled")
            and modification_count < int(modification_cfg.get("max_modifications", 0))
            and status["status"] in MODIFIABLE_STATES
        ):
            new_limit_price = float(modification_cfg["new_limit_price"])
            if abs(current_limit_price - new_limit_price) > 1e-9:
                if modify_order(dhan, config, order_id, new_limit_price):
                    modification_count += 1
                    current_limit_price = new_limit_price
                    logging.info(
                        "modification_count=%s current_limit_price=%.2f",
                        modification_count,
                        current_limit_price,
                    )

        if stop_requested():
            graceful_shutdown(dhan, order_id, "stop signal")
            return

        time.sleep(poll_interval)


# ============================================================
# SHUTDOWN
# ============================================================

def graceful_shutdown(
    dhan=None,
    order_id: Optional[str] = None,
    reason: str = "shutdown",
    position_open: bool = False,
    extra_message: Optional[str] = None,
) -> None:
    """Stop the local process. Do not cancel the broker order or auto-exit."""
    logging.info("Bot stop requested (%s).", reason)
    if order_id:
        logging.info("Existing Dhan order:")
        logging.info("Order ID: %s", order_id)
        if dhan is not None:
            try:
                quantity = 0
                status = get_order_status(dhan, order_id, quantity)
                logging.info("Status: %s", status["raw_status"] or status["status"])
                logging.info("Filled quantity: %s", status["filled_quantity"])
                logging.info("Remaining quantity: %s", status["remaining_quantity"])
            except Exception:
                logging.info("Current broker status could not be retrieved.")
        logging.info("The bot has stopped monitoring.")
        logging.info("The broker order was not automatically cancelled.")
    else:
        logging.info("No Dhan order ID is available.")
    if position_open:
        logging.info("The position may still be open.")
    if extra_message:
        logging.info("%s", extra_message)
    logging.info("Shutdown complete.")


# ============================================================
# MAIN
# ============================================================

def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    install_signal_handlers()

    dhan = None
    order_id = None
    try:
        config = load_config()
        setup_logging(config)
        load_environment()
        validate_config(config)
        validate_safety_config(config)

        consume_leftover_stop_file()
        if stop_requested():
            logging.info("Stop requested at startup. No order was placed.")
            return 0

        print_order_summary(config)

        if config["safety"].get("dry_run", True):
            run_dry_run(config)
            return 0

        if config["safety"].get("require_confirmation", True):
            if not confirm_live_order(config):
                return 1

        if stop_requested():
            logging.info("Stop requested before creating the Dhan client. No order was placed.")
            return 0

        dhan = create_dhan_client()
        logging.info("Dhan client initialized.")

        if stop_requested():
            logging.info("Stop requested before order placement. No order was placed.")
            return 0

        order_id = place_limit_order(dhan, config)
        if not order_id:
            return 1

        monitor_order(dhan, config, order_id)
        return 0

    except (ConfigError, SafetyError, CredentialError) as exc:
        logging.error("%s", exc)
        return 1
    except KeyboardInterrupt:
        graceful_shutdown(dhan, order_id, "CTRL+C")
        return 0
    except Exception:
        logging.exception("Unexpected error. No additional order will be placed.")
        if order_id:
            graceful_shutdown(dhan, order_id, "unexpected error")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
