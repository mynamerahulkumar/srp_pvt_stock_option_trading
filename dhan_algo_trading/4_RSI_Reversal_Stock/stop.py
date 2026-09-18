#!/usr/bin/env python3
"""Create a local stop signal for the RSI reversal bot.

How this communicates with main.py
----------------------------------
This script uses only the Python standard library. It does not import the
Dhan SDK, load configuration, or touch the network.

It creates an empty file named ``.stop`` in the same directory as this
script. ``main.py`` polls for that file on every loop iteration (and while
waiting for session start or order completion). When the file is found,
``main.py``:

1. Stops generating new signals and entry orders.
2. Runs graceful shutdown.
3. Closes positions only if ``shutdown.close_positions_on_manual_stop``
   is true in config.yaml.
4. Exits cleanly.

``main.py`` deletes a leftover ``.stop`` once at startup so a previous
stop does not immediately halt a new run. It never deletes ``.stop``
while trading, so a stop requested during a wait cannot be lost.

Run from another terminal, in this directory:

    python3 stop.py
"""

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
STOP_FILE = BASE_DIR / ".stop"

STOP_FILE.touch()

print("Stop signal created.")
print("The trading bot will stop safely.")
