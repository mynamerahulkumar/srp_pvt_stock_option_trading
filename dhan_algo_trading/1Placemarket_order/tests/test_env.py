from __future__ import annotations

import os

import pytest

from utils.env import EnvError, load_project_env


def test_env_fails_when_keys_blank(tmp_path, monkeypatch):
    monkeypatch.delenv("DHAN_CLIENT_ID", raising=False)
    monkeypatch.delenv("DHAN_ACCESS_TOKEN", raising=False)
    (tmp_path / ".env").write_text("DHAN_CLIENT_ID=\nDHAN_ACCESS_TOKEN=\n", encoding="utf-8")
    with pytest.raises(EnvError, match="Missing required environment keys"):
        load_project_env(tmp_path, override=True)


def test_env_fails_when_file_missing(tmp_path, monkeypatch):
    monkeypatch.delenv("DHAN_CLIENT_ID", raising=False)
    monkeypatch.delenv("DHAN_ACCESS_TOKEN", raising=False)
    with pytest.raises(EnvError, match="Missing required environment keys"):
        load_project_env(tmp_path, override=True)


def test_env_loads_keys(tmp_path, monkeypatch):
    monkeypatch.delenv("DHAN_CLIENT_ID", raising=False)
    monkeypatch.delenv("DHAN_ACCESS_TOKEN", raising=False)
    (tmp_path / ".env").write_text(
        "DHAN_CLIENT_ID=client-from-env\nDHAN_ACCESS_TOKEN=token-from-env\n",
        encoding="utf-8",
    )
    load_project_env(tmp_path, override=True)
    assert os.environ["DHAN_CLIENT_ID"] == "client-from-env"
    assert os.environ["DHAN_ACCESS_TOKEN"] == "token-from-env"
