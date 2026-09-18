from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REQUIRED_KEYS = ("DHAN_CLIENT_ID", "DHAN_ACCESS_TOKEN")


class EnvError(ValueError):
    """Raised when required Dhan credentials are missing."""


def load_project_env(root: Path | None = None, override: bool = False) -> Path:
    root = Path(root) if root is not None else PROJECT_ROOT
    env_path = root / ".env"
    if env_path.exists():
        load_dotenv(env_path, override=override)
    else:
        example = root / ".env.example"
        if example.exists():
            load_dotenv(example, override=override)

    missing = [key for key in REQUIRED_KEYS if not (os.environ.get(key) or "").strip()]
    if missing:
        raise EnvError(
            "Missing required environment keys: "
            + ", ".join(missing)
            + ". Set them in .env (see .env.example)."
        )
    return env_path
