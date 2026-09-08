from __future__ import annotations

import os
import signal
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PID_FILENAME = "bot.pid"


def pid_path(root: Path | None = None) -> Path:
    return (Path(root) if root is not None else PROJECT_ROOT) / PID_FILENAME


def read_pid(path: Path | None = None) -> Optional[int]:
    target = path or pid_path()
    if not target.exists():
        return None
    text = target.read_text(encoding="utf-8").strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def write_pid(pid: int, path: Path | None = None) -> None:
    target = path or pid_path()
    target.write_text(f"{int(pid)}\n", encoding="utf-8")


def remove_pid(path: Path | None = None) -> None:
    target = path or pid_path()
    try:
        target.unlink()
    except FileNotFoundError:
        return


def is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def send_sigint(pid: int) -> None:
    os.kill(pid, signal.SIGINT)
