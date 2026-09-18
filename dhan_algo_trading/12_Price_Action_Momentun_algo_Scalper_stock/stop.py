#!/usr/bin/env python3
"""Create a local stop signal for the Price Action Momentum Scalper.

How this communicates with main.py
----------------------------------
This script uses only the Python standard library. It does not import the
Dhan SDK, load configuration, or touch the network.

It creates an empty file named ``STOP`` under ``state/`` in the same
directory as this script. ``main.py`` polls for that file on every loop
iteration (and while waiting for session start or order completion).
When the file is found, ``main.py``:

1. Prints MANUAL STOP REQUEST RECEIVED.
2. Stops generating new signals and entry orders.
3. Closes the current strategy position if
   ``emergency_stop.close_position`` is true in config.yaml.
4. Exits cleanly.

This script never sends SIGKILL. ``main.py`` deletes a leftover ``STOP``
file once at startup so a previous stop does not immediately halt a new run.

Run from another terminal, in this directory:

    python3 stop.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
STATE_DIR = BASE_DIR / "state"
STOP_FILE = STATE_DIR / "STOP"
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
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    running = _bot_seems_running()
    STOP_FILE.touch()
    if running:
        print("Stop signal created.")
        print("The trading bot will stop safely.")
        return 0
    print("No running Price Action Momentum Scalper was detected.")
    print("A stop file was created anyway. The next start will ignore it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
