from __future__ import annotations

import sys


class DhanhqCompatError(RuntimeError):
    """Raised when the installed dhanhq package cannot run on this Python."""


def _compat_message() -> str:
    py = sys.version.split()[0]
    return (
        f"dhanhq cannot be imported on Python {py}. "
        "dhanhq 2.2+ uses match/case and requires Python 3.10+. "
        "On Python 3.9 run: pip install 'dhanhq==2.0.2' "
        "Or upgrade the interpreter to Python 3.10+."
    )


def ensure_dhanhq_importable() -> None:
    try:
        import dhanhq  # noqa: F401
    except SyntaxError as exc:
        raise DhanhqCompatError(_compat_message()) from exc
