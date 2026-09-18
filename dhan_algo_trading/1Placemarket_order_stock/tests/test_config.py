from __future__ import annotations

from copy import deepcopy

import pytest
import yaml

from tests.fakes import sample_raw_config
from utils.config import ConfigError, load_config, validate_and_build


def test_valid_hdfcbank_configuration(tmp_path):
    raw = sample_raw_config()
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    config = load_config(path)
    assert config.instrument.symbol == "HDFCBANK"
    assert config.instrument.security_id == "1333"
    assert config.instrument.instrument_id == "1333"
    assert config.quantity == 1
    assert config.polling_interval_seconds == 5
    assert config.risk.take_profit_percent == 2.0
    assert config.risk.stop_loss_percent == 1.0


def test_missing_security_id():
    raw = deepcopy(sample_raw_config())
    raw["instruments"]["HDFCBANK"]["security_id"] = "<SECURITY_ID>"
    with pytest.raises(ConfigError, match="security_id"):
        validate_and_build(raw)


def test_missing_instrument_id():
    raw = deepcopy(sample_raw_config())
    del raw["instruments"]["HDFCBANK"]["instrument_id"]
    with pytest.raises(ConfigError, match="instrument_id"):
        validate_and_build(raw)


def test_invalid_quantity():
    raw = deepcopy(sample_raw_config())
    raw["trading"]["quantity"] = 0
    with pytest.raises(ConfigError, match="quantity"):
        validate_and_build(raw)


def test_invalid_polling_interval():
    raw = deepcopy(sample_raw_config())
    raw["trading"]["polling"]["interval_seconds"] = -1
    with pytest.raises(ConfigError, match="interval"):
        validate_and_build(raw)


def test_live_flag_places_without_dry_run():
    raw = deepcopy(sample_raw_config())
    raw["trading"]["live"] = True
    config = validate_and_build(raw)
    assert config.live is True
    assert config.dry_run is False
    assert config.instrument.security_id == "1333"


def test_live_false_is_dry_run():
    raw = deepcopy(sample_raw_config())
    raw["trading"]["live"] = False
    config = validate_and_build(raw)
    assert config.live is False
    assert config.dry_run is True


def test_cli_dry_run_overrides_live():
    raw = deepcopy(sample_raw_config())
    raw["trading"]["live"] = True
    config = validate_and_build(raw, dry_run=True)
    assert config.dry_run is True
    assert config.live is False


def test_unknown_symbol():
    with pytest.raises(ConfigError, match="RELIANCE"):
        validate_and_build(sample_raw_config(), symbol="RELIANCE")
