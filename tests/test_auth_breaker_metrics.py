"""tests/test_auth_breaker_metrics.py — elite review (2026-06-15) batch 3.

The standalone auth_breaker (used by the non-framework ingestion lambdas — notion
+ dropbox-poll) returns a healthy-looking 200 "skip" when tripped, so a dead
credential silently suppressed those sources for 24h with no signal (the same
class that hid the Garmin/Strava deaths). auth_breaker now emits
LifePlatform/OAuth IngestAuthHealthy (0 = broken / short-circuited, 1 = healthy)
so a fleet-wide alarm (Min < 1) catches it.

(SIMP-2 framework sources already record health on breaker-trip via ER-01's
_record_ingest_health, so they're covered separately — these tests cover the
previously-blind standalone path.)
"""

import os
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

import auth_breaker as ab  # noqa: E402
import boto3  # noqa: E402


class _CW:
    def __init__(self):
        self.calls = []

    def put_metric_data(self, **kw):
        self.calls.append(kw)


def _patch_cw(monkeypatch):
    cw = _CW()
    monkeypatch.setattr(boto3, "client", lambda *a, **k: cw)
    return cw


def _last_value(cw):
    return cw.calls[-1]["MetricData"][0]["Value"]


def test_mark_failure_emits_zero(monkeypatch):
    cw = _patch_cw(monkeypatch)
    ab.mark_failure(MagicMock(), "notion", "matthew", "401 Unauthorized", None)
    assert cw.calls, "mark_failure must emit a metric"
    last = cw.calls[-1]
    assert last["Namespace"] == "LifePlatform/OAuth"
    assert last["MetricData"][0]["MetricName"] == "IngestAuthHealthy"
    assert _last_value(cw) == 0


def test_clear_failure_emits_one(monkeypatch):
    cw = _patch_cw(monkeypatch)
    ab.clear_failure(MagicMock(), "notion", "matthew", None)
    assert _last_value(cw) == 1


def test_check_breaker_fresh_emits_zero_and_returns_item(monkeypatch):
    cw = _patch_cw(monkeypatch)
    table = MagicMock()
    table.get_item.return_value = {
        "Item": {
            "pk": "USER#matthew#SOURCE#notion",
            "sk": "AUTH_FAILURE",
            "marked_at": datetime.now(timezone.utc).isoformat(),
            "error": "401 Unauthorized",
        }
    }
    result = ab.check_breaker(table, "notion", "matthew", None)
    assert result is not None, "fresh marker must short-circuit"
    assert _last_value(cw) == 0, "a short-circuited (suppressed) run must emit 0"


def test_check_breaker_absent_emits_nothing(monkeypatch):
    cw = _patch_cw(monkeypatch)
    table = MagicMock()
    table.get_item.return_value = {}
    assert ab.check_breaker(table, "notion", "matthew", None) is None
    assert cw.calls == [], "no metric when the breaker isn't tripped (only 0/1 on real state)"


def test_check_breaker_expired_emits_nothing(monkeypatch):
    cw = _patch_cw(monkeypatch)
    table = MagicMock()
    old = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    table.get_item.return_value = {"Item": {"sk": "AUTH_FAILURE", "marked_at": old}}
    assert ab.check_breaker(table, "notion", "matthew", None) is None
    assert cw.calls == [], "an expired marker is treated as recovered — no 0 emitted"


def test_emit_never_raises(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("no creds in this env")

    monkeypatch.setattr(boto3, "client", boom)
    # Observability is best-effort: a metric failure must never break ingestion.
    ab.mark_failure(MagicMock(), "notion", "matthew", "401", None)
    ab.clear_failure(MagicMock(), "notion", "matthew", None)
