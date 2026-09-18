#!/usr/bin/env python3
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cli.styles import SHUTDOWN_MESSAGE
from utils.logging import get_logger, setup_logging
from utils.process import is_running, pid_path, read_pid, remove_pid, send_sigint


def stop_bot(root: Path | None = None, timeout_seconds: float = 5.0) -> int:
    root = Path(root) if root is not None else ROOT
    setup_logging()
    logger = get_logger("stop")
    path = pid_path(root)
    pid = read_pid(path)
    if pid is None:
        logger.error("No bot.pid found. Bot is not running.")
        return 1
    if not is_running(pid):
        remove_pid(path)
        logger.error("Stale PID %s. Removed bot.pid.", pid)
        return 1

    logger.warning("Sending SIGINT to PID %s", pid)
    try:
        send_sigint(pid)
    except ProcessLookupError:
        remove_pid(path)
        logger.error("Process %s exited before SIGINT.", pid)
        return 1
    except PermissionError as exc:
        logger.error("Unable to signal PID %s: %s", pid, exc)
        return 1

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if not is_running(pid):
            break
        time.sleep(0.1)

    if is_running(pid):
        logger.warning("Process %s is still running (in-flight order may be finishing). PID file kept.", pid)
        print(SHUTDOWN_MESSAGE)
        return 0

    remove_pid(path)
    print(SHUTDOWN_MESSAGE)
    return 0


def main() -> int:
    return stop_bot()


if __name__ == "__main__":
    raise SystemExit(main())
