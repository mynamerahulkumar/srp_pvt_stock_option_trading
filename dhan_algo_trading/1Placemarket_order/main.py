#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from trading.session import TradingSession
from utils.compat import DhanhqCompatError, ensure_dhanhq_importable
from utils.config import ConfigError, load_config
from utils.env import EnvError, load_project_env
from utils.logging import get_logger, setup_logging


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Dhan sci-fi CLI trading terminal")
    parser.add_argument("--symbol", help="Trading symbol (defaults to config trading.default_symbol)")
    parser.add_argument("--config", default=str(ROOT / "config.yaml"), help="Path to config.yaml")
    parser.add_argument("--dry-run", action="store_true", help="Simulate orders; still poll live market data")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    setup_logging()
    logger = get_logger()
    try:
        load_project_env(ROOT)
        ensure_dhanhq_importable()
        config = load_config(args.config, symbol=args.symbol, dry_run=args.dry_run)
    except (ConfigError, EnvError, DhanhqCompatError) as exc:
        logger.error("%s", exc)
        return 1
    logger.info("Configuration loaded")
    logger.info("%s selected", config.instrument.symbol)
    logger.info("Mode: %s | security_id=%s", "LIVE" if config.live else "DRY-RUN", config.instrument.security_id)
    session = TradingSession(config)
    session.run(interactive=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
