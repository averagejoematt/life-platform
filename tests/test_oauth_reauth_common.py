"""Tests for setup/oauth_reauth_common.py (#2085).

The shared helper every oauth-facet re-auth script calls, right after a
VERIFIED token write, to clear the `AUTH_FAILURE` breaker marker
(`common.auth_breaker`) so the next scheduled ingestion run doesn't
short-circuit on a now-stale latch for up to 24h.
"""

import importlib.util
import os
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_LAMBDAS = _REPO / "lambdas"
_SETUP_DIR = _REPO / "setup"

for _p in (str(_LAMBDAS), str(_SETUP_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

os.environ.setdefault("TABLE_NAME", "life-platform")

from common import auth_breaker as ab  # noqa: E402


def _load_orc():
    spec = importlib.util.spec_from_file_location("oauth_reauth_common", _SETUP_DIR / "oauth_reauth_common.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture
def orc():
    return _load_orc()


class _FakeTable:
    """Minimal in-memory stand-in for a boto3 DynamoDB Table resource,
    reproducing exactly the get_item/put_item/delete_item shapes
    `common.auth_breaker` uses."""

    def __init__(self):
        self.items = {}

    def _key(self, key):
        return (key["pk"], key["sk"])

    def get_item(self, Key):
        item = self.items.get(self._key(Key))
        return {"Item": item} if item else {}

    def put_item(self, Item):
        self.items[(Item["pk"], Item["sk"])] = Item

    def delete_item(self, Key):
        self.items.pop(self._key(Key), None)


class _FakeDynamoResource:
    def __init__(self, table):
        self._table = table

    def Table(self, _name):
        return self._table


# ── validation: the SET, not a hand-typed string ───────────────────────────────


def test_rejects_a_source_name_not_in_the_registry(orc):
    with pytest.raises(ValueError, match="not a registered oauth-facet source"):
        orc.clear_breaker_after_reauth("not-a-real-source")


def test_accepts_every_registered_oauth_facet_source(orc, monkeypatch):
    """Sanity: the validation gate itself derives from the registry set, not a
    hand-typed allowlist — every current oauth-facet source must pass it."""
    from ingestion.source_registry import oauth_source_ids

    fake_table = _FakeTable()
    monkeypatch.setattr(orc.boto3, "resource", lambda *a, **k: _FakeDynamoResource(fake_table))
    for source in oauth_source_ids():
        orc.clear_breaker_after_reauth(source)  # must not raise


# ── the actual clear, proven against the real auth_breaker module ─────────────


def test_clear_breaker_after_reauth_removes_an_active_marker(orc, monkeypatch):
    """Acceptance box 4 (#2085): after mark_failure() has tripped the breaker
    (simulating the original 401/403 that stranded the source),
    clear_breaker_after_reauth() must make check_breaker() return None —
    exactly the check every ingestion Lambda makes before short-circuiting.
    A None result means the NEXT scheduled run proceeds instead of skipping."""
    fake_table = _FakeTable()
    monkeypatch.setattr(orc.boto3, "resource", lambda *a, **k: _FakeDynamoResource(fake_table))

    ab.mark_failure(fake_table, source_name="whoop", user_id="matthew", error_msg="401 unauthorized", logger=None)
    assert (
        ab.check_breaker(fake_table, source_name="whoop", user_id="matthew", logger=None) is not None
    ), "setup precondition: the breaker must be active before the clear"

    result = orc.clear_breaker_after_reauth("whoop")

    assert result is True
    assert (
        ab.check_breaker(fake_table, source_name="whoop", user_id="matthew", logger=None) is None
    ), "the next scheduled run must no longer see an active breaker"


def test_clear_breaker_after_reauth_is_a_noop_when_no_marker_was_set(orc, monkeypatch):
    """A verified re-auth after a source that was never latched must not
    error — DELETE on an absent key is a no-op both in DynamoDB and here."""
    fake_table = _FakeTable()
    monkeypatch.setattr(orc.boto3, "resource", lambda *a, **k: _FakeDynamoResource(fake_table))

    result = orc.clear_breaker_after_reauth("whoop")

    assert result is True
    assert ab.check_breaker(fake_table, source_name="whoop", user_id="matthew", logger=None) is None


def test_clear_breaker_after_reauth_survives_a_dynamo_failure(orc, monkeypatch):
    """Best-effort per auth_breaker's own convention (#2085): a DDB hiccup
    while clearing the marker must not raise out of an otherwise-successful
    re-auth — the operator already has a working credential."""

    class _BrokenResource:
        def Table(self, _name):
            raise RuntimeError("simulated DDB outage")

    monkeypatch.setattr(orc.boto3, "resource", lambda *a, **k: _BrokenResource())

    result = orc.clear_breaker_after_reauth("whoop")  # must not raise
    assert result is False
