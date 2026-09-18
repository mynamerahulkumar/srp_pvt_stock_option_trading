#!/usr/bin/env python3
"""Create a local stop signal for the Volume Breakout Scalper.

How this communicates with main.py
----------------------------------
This script uses only the Python standard library. It does not import the
Dhan SDK, load configuration, or touch the network.

It creates an empty file named ``.stop`` in the same directory as this
script. ``main.py`` polls for that file on every loop iteration (and while
waiting for session start or order completion). When the file is found,
``main.py``:

1. Prints MANUAL STOP REQUEST RECEIVED.
2. Stops generating new signals and entry orders.
3. Runs graceful shutdown.
4. Closes positions only if ``trading.close_positions_on_stop``
   is true in config.yaml.
5. Exits cleanly.

This script never sends SIGKILL. ``main.py`` deletes a leftover ``.stop``
once at startup so a previous stop does not immediately halt a new run.

Run from another terminal, in this directory:

    python3 stop.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
STOP_FILE = BASE_DIR / ".stop"
MAIN_FILE = BASE_DIR / "main.py"


def _bot_seems_running() -> bool:
    """Best-effort check for a live main.py in this folder."""
    try:
        result = subprocess.run(
            ["pgrep", "-f", str(MAIN_FILE)],
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, FileNotFoundError):
        return False
    pids = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return bool(pids)


def main() -> int:
    running = _bot_seems_running()
    STOP_FILE.touch()
    if running:
        print("Stop signal created.")
        print("The trading bot will stop safely.")
        return 0
    print("No running Volume Breakout bot was detected.")
    print("A stop file was created anyway. The next start will ignore it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
