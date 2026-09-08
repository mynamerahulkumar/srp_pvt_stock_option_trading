#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils.env import EnvError, load_project_env
from utils.logging import get_logger, setup_logging
from utils.process import is_running, pid_path, read_pid, remove_pid, write_pid


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Start the Dhan trading bot (live by default)")
    parser.add_argument("--symbol", help="Trading symbol (defaults to config trading.default_symbol)")
    parser.add_argument("--config", default=str(ROOT / "config.yaml"), help="Path to config.yaml")
    parser.add_argument("--dry-run", action="store_true", help="Simulate orders; still poll live market data")
    return parser.parse_args(argv)


def build_main_command(args: argparse.Namespace, root: Path, python_exe: str | None = None) -> list[str]:
    command = [python_exe or sys.executable, str(root / "main.py"), "--config", str(args.config)]
    if args.symbol:
        command.extend(["--symbol", args.symbol])
    if args.dry_run:
        command.append("--dry-run")
    return command


def start_bot(
    argv: list[str] | None = None,
    root: Path | None = None,
    popen: Callable[..., subprocess.Popen] = subprocess.Popen,
) -> int:
    root = Path(root) if root is not None else ROOT
    setup_logging()
    logger = get_logger("start")
    args = parse_args(argv)
    try:
        load_project_env(root)
    except EnvError as exc:
        logger.error("%s", exc)
        return 1

    path = pid_path(root)
    existing = read_pid(path)
    if existing and is_running(existing):
        logger.error("Bot already running with PID %s", existing)
        return 1
    if existing:
        remove_pid(path)

    command = build_main_command(args, root)
    logger.info("Starting bot%s", " in dry-run" if args.dry_run else " (LIVE)")
    proc = popen(command)
    write_pid(proc.pid, path)
    logger.info("Bot PID %s written to %s", proc.pid, path.name)
    try:
        return int(proc.wait())
    finally:
        if read_pid(path) == proc.pid:
            remove_pid(path)


def main(argv: list[str] | None = None) -> int:
    return start_bot(argv=argv)


if __name__ == "__main__":
    raise SystemExit(main())
