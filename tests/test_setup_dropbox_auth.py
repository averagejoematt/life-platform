"""Tests for setup/setup_dropbox_auth.py's #2085 breaker-clear wiring.

Dropbox is the one existing re-auth script whose verification step
(`verify_access`) does NOT already gate the secret write (unlike whoop's
verify-then-save ordering) — `main()` calls `verify_access()` and
`store_secret()` unconditionally, one after the other. #2085 only adds a NEW
gate: the auth-breaker clear must fire on `verify_access() is True` and must
NOT fire when it returns False. That pre-existing store-regardless-of-verify
behavior is untouched here — out of this issue's scope.
"""

import importlib.util
import sys
from pathlib import Path
from unittest import mock

import pytest

_MOD_PATH = Path(__file__).resolve().parents[1] / "setup" / "setup_dropbox_auth.py"

_SETUP_DIR = str(_MOD_PATH.parent)
if _SETUP_DIR not in sys.path:
    sys.path.insert(0, _SETUP_DIR)


def _load():
    spec = importlib.util.spec_from_file_location("setup_dropbox_auth", _MOD_PATH)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture
def da():
    return _load()


def _drive_main(da, monkeypatch, *, verified: bool):
    inputs = iter(["app-key-1", "app-secret-1", "the-auth-code"])
    monkeypatch.setattr("builtins.input", lambda *_a, **_k: next(inputs))
    monkeypatch.setattr(da, "exchange_code", lambda *a, **k: {"access_token": "at-new", "refresh_token": "rt-new"})
    monkeypatch.setattr(da, "verify_access", lambda *_a, **_k: verified)
    store_mock = mock.MagicMock()
    monkeypatch.setattr(da, "store_secret", store_mock)
    clear_mock = mock.MagicMock()
    monkeypatch.setattr(da, "clear_breaker_after_reauth", clear_mock)

    da.main()
    return clear_mock, store_mock


def test_main_clears_the_breaker_after_a_verified_reauth(da, monkeypatch):
    clear_mock, store_mock = _drive_main(da, monkeypatch, verified=True)
    store_mock.assert_called_once()
    clear_mock.assert_called_once_with("dropbox")


def test_main_leaves_the_breaker_alone_on_failed_verification(da, monkeypatch):
    """Negative test (#2085 acceptance box 2): verify_access() returning False
    must not clear the breaker, even though (pre-existing, out of scope)
    store_secret() still runs regardless of verification."""
    clear_mock, _store_mock = _drive_main(da, monkeypatch, verified=False)
    clear_mock.assert_not_called()
