from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from start import build_main_command, start_bot
from stop import stop_bot
from utils.process import is_running, pid_path, write_pid


class _FakeProc:
    def __init__(self, pid: int = 4242, returncode: int = 0):
        self.pid = pid
        self.returncode = returncode
        self.waited = False

    def wait(self) -> int:
        self.waited = True
        return self.returncode


def _write_valid_env(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("DHAN_CLIENT_ID", raising=False)
    monkeypatch.delenv("DHAN_ACCESS_TOKEN", raising=False)
    (tmp_path / ".env").write_text(
        "DHAN_CLIENT_ID=test-client\nDHAN_ACCESS_TOKEN=test-token\n",
        encoding="utf-8",
    )


def test_refuse_double_start_when_pid_alive(tmp_path, monkeypatch):
    _write_valid_env(tmp_path, monkeypatch)
    write_pid(os.getpid(), pid_path(tmp_path))
    spawned = []

    def _popen(command):
        spawned.append(command)
        return _FakeProc()

    assert start_bot(argv=[], root=tmp_path, popen=_popen) == 1
    assert spawned == []


def test_start_writes_pid_and_waits(tmp_path, monkeypatch):
    _write_valid_env(tmp_path, monkeypatch)
    proc = _FakeProc(pid=7777)

    def _popen(command):
        return proc

    assert start_bot(argv=["--dry-run"], root=tmp_path, popen=_popen) == 0
    assert proc.waited
    assert not pid_path(tmp_path).exists()


def test_stop_missing_pid_is_clean_error(tmp_path):
    assert stop_bot(root=tmp_path) == 1


def test_stop_stale_pid_is_clean_error(tmp_path):
    write_pid(999_999_999, pid_path(tmp_path))
    assert is_running(999_999_999) is False
    assert stop_bot(root=tmp_path) == 1
    assert not pid_path(tmp_path).exists()


def test_build_main_command_live_by_default(tmp_path):
    args = SimpleNamespace(symbol=None, config=str(tmp_path / "config.yaml"), dry_run=False)
    command = build_main_command(args, tmp_path, python_exe="python")
    assert command[:2] == ["python", str(tmp_path / "main.py")]
    assert "--dry-run" not in command


def test_stop_sends_sigint(tmp_path, monkeypatch):
    write_pid(os.getpid(), pid_path(tmp_path))
    sent = []

    def _fake_sigint(pid):
        sent.append(pid)

    monkeypatch.setattr("stop.send_sigint", _fake_sigint)
    monkeypatch.setattr("stop.is_running", lambda pid: pid == os.getpid() and not sent)
    assert stop_bot(root=tmp_path, timeout_seconds=0.2) == 0
    assert sent == [os.getpid()]
    assert not pid_path(tmp_path).exists()
