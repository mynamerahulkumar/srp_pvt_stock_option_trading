from __future__ import annotations

import builtins

import pytest

from utils.compat import DhanhqCompatError, ensure_dhanhq_importable


def test_compat_wraps_match_syntax_error(monkeypatch):
    real_import = builtins.__import__

    def _import(name, *args, **kwargs):
        if name == "dhanhq":
            raise SyntaxError("invalid syntax")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _import)
    with pytest.raises(DhanhqCompatError, match="dhanhq==2.0.2"):
        ensure_dhanhq_importable()
