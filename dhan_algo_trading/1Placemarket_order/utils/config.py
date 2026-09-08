from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import yaml

from trading.models import (
    PLACEHOLDER_IDS,
    InstrumentConfig,
    RiskConfig,
    TradingConfig,
)


class ConfigError(ValueError):
    """Raised when trading configuration is missing or invalid."""


def load_yaml(path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    if not config_path.exists():
        raise ConfigError(f"Configuration file not found: {config_path}")
    with config_path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ConfigError("Configuration root must be a mapping")
    return data


def _require(mapping: dict[str, Any], key: str, context: str) -> Any:
    if key not in mapping or mapping[key] is None:
        raise ConfigError(f"Missing {context}.{key}")
    return mapping[key]


def _as_positive_number(value: Any, field_name: str, integer: bool = False) -> float | int:
    try:
        number = int(value) if integer else float(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{field_name} must be a number") from exc
    if number <= 0:
        raise ConfigError(f"{field_name} must be greater than 0")
    return number


def _as_non_empty_id(value: Any, field_name: str) -> str:
    text = str(value).strip() if value is not None else ""
    if text in PLACEHOLDER_IDS:
        raise ConfigError(f"{field_name} is missing or still a placeholder")
    return text


def validate_and_build(
    raw: dict[str, Any],
    symbol: Optional[str] = None,
    dry_run: bool = False,
) -> TradingConfig:
    trading = raw.get("trading")
    instruments = raw.get("instruments")
    if not isinstance(trading, dict):
        raise ConfigError("Missing trading section")
    if not isinstance(instruments, dict) or not instruments:
        raise ConfigError("Missing instruments section")

    default_symbol = str(_require(trading, "default_symbol", "trading")).upper().strip()
    selected = (symbol or default_symbol).upper().strip()
    if selected not in instruments:
        raise ConfigError(f"Symbol {selected} is not defined in instruments")

    instrument_raw = instruments[selected]
    if not isinstance(instrument_raw, dict):
        raise ConfigError(f"Instrument {selected} must be a mapping")

    exchange_segment = str(_require(instrument_raw, "exchange_segment", selected)).upper().strip()
    security_id = _as_non_empty_id(instrument_raw.get("security_id"), f"{selected}.security_id")
    instrument_id = _as_non_empty_id(instrument_raw.get("instrument_id"), f"{selected}.instrument_id")

    quantity = int(_as_positive_number(_require(trading, "quantity", "trading"), "quantity", integer=True))
    polling = trading.get("polling") or {}
    if not isinstance(polling, dict):
        raise ConfigError("trading.polling must be a mapping")
    interval = float(
        _as_positive_number(
            _require(polling, "interval_seconds", "trading.polling"),
            "polling.interval_seconds",
        )
    )

    risk_raw = trading.get("risk") or {}
    if not isinstance(risk_raw, dict):
        raise ConfigError("trading.risk must be a mapping")

    tp_price = risk_raw.get("take_profit_price")
    sl_price = risk_raw.get("stop_loss_price")
    tp_percent = risk_raw.get("take_profit_percent")
    sl_percent = risk_raw.get("stop_loss_percent")

    if tp_price is None and tp_percent is None:
        raise ConfigError("Provide take_profit_percent or take_profit_price")
    if sl_price is None and sl_percent is None:
        raise ConfigError("Provide stop_loss_percent or stop_loss_price")

    if tp_percent is not None:
        tp_percent = float(_as_positive_number(tp_percent, "take_profit_percent"))
    if sl_percent is not None:
        sl_percent = float(_as_positive_number(sl_percent, "stop_loss_percent"))
    if tp_price is not None:
        tp_price = float(_as_positive_number(tp_price, "take_profit_price"))
    if sl_price is not None:
        sl_price = float(_as_positive_number(sl_price, "stop_loss_price"))

    transaction_type = str(trading.get("transaction_type", "BUY")).upper().strip()
    order_type = str(trading.get("order_type", "MARKET")).upper().strip()
    product_type = str(trading.get("product_type", "CNC")).upper().strip()
    if transaction_type not in {"BUY", "SELL"}:
        raise ConfigError(f"Invalid transaction_type: {transaction_type}")
    if order_type not in {"MARKET", "LIMIT"}:
        raise ConfigError(f"Invalid order_type: {order_type}")

    return TradingConfig(
        default_symbol=default_symbol,
        quantity=quantity,
        transaction_type=transaction_type,
        order_type=order_type,
        product_type=product_type,
        polling_interval_seconds=interval,
        risk=RiskConfig(
            take_profit_percent=tp_percent if tp_percent is not None else 0.0,
            stop_loss_percent=sl_percent if sl_percent is not None else 0.0,
            take_profit_price=tp_price,
            stop_loss_price=sl_price,
        ),
        instrument=InstrumentConfig(
            symbol=selected,
            exchange_segment=exchange_segment,
            security_id=security_id,
            instrument_id=instrument_id,
        ),
        dry_run=bool(dry_run),
    )


def load_config(
    path: str | Path,
    symbol: Optional[str] = None,
    dry_run: bool = False,
) -> TradingConfig:
    return validate_and_build(load_yaml(path), symbol=symbol, dry_run=dry_run)
