#!/usr/bin/env python3
"""Create a local stop signal for the LIMIT order bot.

This script uses only the Python standard library.
It does not import the Dhan SDK, load configuration, or touch the network.
"""

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
STOP_FILE = BASE_DIR / ".stop"

STOP_FILE.touch()

print("Stop signal created.")
print("The trading bot will stop safely.")
