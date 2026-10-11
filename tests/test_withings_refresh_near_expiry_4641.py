"""#4641: Withings exchanges its rotating refresh token only near access-token expiry."""

import os
import time

os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("TABLE_NAME", "test-table")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from ingestion import withings_lambda as wl


def _secret(expires_in_s):
    return {
        "client_id": "c",
        "client_secret": "s",
        "access_token": "AT",
        "refresh_token": "RT",
        "access_token_expires_at": int(time.time()) + expires_in_s,
    }


def _count_refreshes(monkeypatch):
    calls = []

    def fake(secret):
        calls.append(1)
        secret["access_token"] = "AT2"
        secret["refresh_token"] = "RT2"
        secret["access_token_expires_at"] = int(time.time()) + 10800
        return secret

    monkeypatch.setattr(wl, "_refresh_access_token", fake)
    return calls


def test_fresh_token_is_reused_and_dict_unchanged(monkeypatch):
    calls = _count_refreshes(monkeypatch)
    stored = _secret(7200)
    out = wl.authenticate(stored)
    assert calls == [], "a token with 2h left must not trigger a rotating-token exchange"
    assert out == stored, "unchanged credentials -> the framework writes nothing back"


def test_near_expiry_token_is_refreshed_and_rotated(monkeypatch):
    calls = _count_refreshes(monkeypatch)
    out = wl.authenticate(_secret(wl.REFRESH_MARGIN_SECONDS - 60))
    assert calls == [1]
    assert out["refresh_token"] == "RT2" and out["access_token"] == "AT2"


def test_missing_stamp_forces_refresh(monkeypatch):
    calls = _count_refreshes(monkeypatch)
    s = _secret(7200)
    del s["access_token_expires_at"]
    wl.authenticate(s)
    assert calls == [1], "first run after deploy has no stamp: refresh once, then stamp"


def test_refresh_stamps_expiry(monkeypatch):
    monkeypatch.setattr(wl, "_get_nonce", lambda *a: "n")
    monkeypatch.setattr(
        wl, "_post_form", lambda url, data: {"status": 0, "body": {"access_token": "A", "refresh_token": "R", "expires_in": 10800}}
    )
    out = wl._refresh_access_token({"client_id": "c", "client_secret": "s", "refresh_token": "x"})
    assert out["access_token_expires_at"] > time.time() + 10000
