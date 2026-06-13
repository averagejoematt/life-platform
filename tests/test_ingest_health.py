"""
tests/test_ingest_health.py — ER-01 infra-liveness decision core (offline).

Covers the pure functions in lambdas/ingest_health.py that decide whether an
ingestion source is healthy, running-but-erroring, or has silently stopped — the
signal the 44-day Garmin outage lacked. No AWS, no I/O: the framework writes the
sentinel and the heartbeat reads it, but the *decision* lives here and is tested
in isolation against all four error classes + the streak buffer + the acceptance
scenarios from the ER-01 spec.
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

from ingest_health import (  # noqa: E402
    DEFAULT_FAILURE_STREAK_THRESHOLD,
    classify_error,
    emf_metric_line,
    evaluate_source_health,
    ingest_health_sk,
    update_outcome,
)

NOW = datetime(2026, 6, 9, 18, 0, 0, tzinfo=timezone.utc)


def _iso(dt):
    return dt.isoformat()


def _outcome(prev, succeeded, error_class, ts, source):
    """Compact wrapper around update_outcome for the table-heavy tests below."""
    return update_outcome(prev, attempted=True, succeeded=succeeded, error_class=error_class, now_iso=_iso(ts), source=source)


class _FakeHTTPError(Exception):
    """Mimics urllib.error.HTTPError exposing a .code attribute."""

    def __init__(self, code, msg=""):
        super().__init__(msg or f"HTTP {code}")
        self.code = code


# ── classify_error — all four classes ─────────────────────────────────────────
@pytest.mark.parametrize(
    "exc,expected",
    [
        (_FakeHTTPError(401, "Unauthorized"), "auth"),
        (_FakeHTTPError(403, "Forbidden"), "auth"),
        (Exception("invalid_grant: refresh token expired"), "auth"),
        (Exception("401 Client Error: Unauthorized"), "auth"),
        (_FakeHTTPError(429, "Too Many Requests"), "throttle"),
        (Exception("rate limit exceeded, retry later"), "throttle"),
        (Exception("API quota exhausted"), "throttle"),
        (_FakeHTTPError(503, "Service Unavailable"), "transport"),
        (Exception("Connection reset by peer"), "transport"),
        (Exception("urlopen error timed out"), "transport"),
        (json.JSONDecodeError("Expecting value", "doc", 0), "parse"),
        (KeyError("score"), "parse"),
        (Exception("no records after transform"), "parse"),
        (Exception("some totally novel error"), "transport"),  # safe default
        (None, "transport"),
    ],
)
def test_classify_error(exc, expected):
    assert classify_error(exc) == expected


# ── update_outcome — streak math ──────────────────────────────────────────────
def test_update_outcome_first_success_from_empty():
    out = update_outcome(None, attempted=True, succeeded=True, error_class="none", now_iso=_iso(NOW), source="whoop")
    assert out["consecutive_failures"] == 0
    assert out["last_success_ts"] == _iso(NOW)
    assert out["last_attempt_ts"] == _iso(NOW)
    assert out["last_error_class"] == "none"
    assert out["source"] == "whoop"


def test_update_outcome_failure_increments_and_records_class():
    out = update_outcome(None, attempted=True, succeeded=False, error_class="auth", now_iso=_iso(NOW), source="garmin")
    assert out["consecutive_failures"] == 1
    assert out["last_error_class"] == "auth"
    assert out["last_attempt_ts"] == _iso(NOW)
    assert out["last_success_ts"] is None  # never succeeded


def test_update_outcome_streak_accumulates_then_resets():
    s = None
    for _ in range(3):
        s = _outcome(s, False, "auth", NOW, "garmin")
    assert s["consecutive_failures"] == 3
    # A clean run resets the streak and stamps success, keeping last_attempt fresh.
    later = NOW + timedelta(hours=1)
    s = _outcome(s, True, "none", later, "garmin")
    assert s["consecutive_failures"] == 0
    assert s["last_success_ts"] == _iso(later)
    assert s["last_error_class"] == "none"


def test_update_outcome_attempted_false_keeps_prior_attempt_ts():
    prev = _outcome(None, True, "none", NOW, "whoop")
    later = NOW + timedelta(hours=2)
    out = update_outcome(prev, attempted=False, succeeded=False, error_class="transport", now_iso=_iso(later), source="whoop")
    assert out["last_attempt_ts"] == _iso(NOW)  # unchanged — this run didn't attempt
    assert out["consecutive_failures"] == 1


# ── evaluate_source_health — the verdict ──────────────────────────────────────
def test_evaluate_unknown_when_no_sentinel():
    v = evaluate_source_health(None, now=NOW, source="whoop")
    assert v["status"] == "unknown"
    assert v["alert"] is False


def test_evaluate_ok_recent_success():
    sentinel = _outcome(None, True, "none", NOW - timedelta(hours=1), "whoop")
    v = evaluate_source_health(sentinel, now=NOW)
    assert v["status"] == "ok"
    assert v["alert"] is False


def test_evaluate_unfed_but_healthy_does_not_alert():
    # The user genuinely didn't log: the Lambda ran + 200'd, no new data, streak 0.
    sentinel = _outcome(None, True, "none", NOW - timedelta(hours=3), "withings")
    v = evaluate_source_health(sentinel, now=NOW)
    assert v["status"] == "ok"
    assert v["alert"] is False


def test_evaluate_below_buffer_stays_silent():
    # 2 consecutive failures, threshold 3 → a blip, not yet an alert.
    s = None
    for _ in range(DEFAULT_FAILURE_STREAK_THRESHOLD - 1):
        s = _outcome(s, False, "auth", NOW - timedelta(minutes=30), "garmin")
    v = evaluate_source_health(s, now=NOW)
    assert v["consecutive_failures"] == DEFAULT_FAILURE_STREAK_THRESHOLD - 1
    assert v["status"] == "ok"
    assert v["alert"] is False


def test_evaluate_failing_streak_alerts_critical_for_auth():
    s = None
    for _ in range(DEFAULT_FAILURE_STREAK_THRESHOLD):
        s = _outcome(s, False, "auth", NOW - timedelta(minutes=10), "garmin")
    v = evaluate_source_health(s, now=NOW)
    assert v["status"] == "failing"
    assert v["alert"] is True
    assert v["severity"] == "critical"


def test_evaluate_failing_streak_non_auth_is_warning():
    s = None
    for _ in range(DEFAULT_FAILURE_STREAK_THRESHOLD):
        s = _outcome(s, False, "transport", NOW - timedelta(minutes=10), "strava")
    v = evaluate_source_health(s, now=NOW)
    assert v["status"] == "failing"
    assert v["severity"] == "warning"


def test_evaluate_stale_attempt_alerts_even_with_zero_failures():
    # De-scheduled / dead cron: last attempt 30h ago, streak 0. Caught by the
    # attempt-staleness arm — the thing that notices a silently-removed schedule.
    sentinel = _outcome(None, True, "none", NOW - timedelta(hours=30), "weather")
    v = evaluate_source_health(sentinel, now=NOW)
    assert v["status"] == "stale"
    assert v["alert"] is True


def test_evaluate_recent_attempt_not_stale():
    sentinel = _outcome(None, True, "none", NOW - timedelta(hours=20), "weather")
    v = evaluate_source_health(sentinel, now=NOW)
    assert v["status"] == "ok"
    assert v["alert"] is False


# ── Acceptance scenario (ER-01 spec) ──────────────────────────────────────────
def test_acceptance_source_erroring_every_run_alerts_with_zero_new_data():
    """A source whose ingestion 401s on every run flips to a failure streak and
    alerts — with zero new DATE# data required to trigger it."""
    s = None
    # Three consecutive hourly runs all hit 401 (the auth-breaker path records
    # attempted=True/succeeded=False/auth each time).
    for i in range(3):
        s = _outcome(s, False, "auth", NOW - timedelta(hours=3 - i), "garmin")
    v = evaluate_source_health(s, now=NOW)
    assert v["alert"] is True and v["status"] == "failing"
    assert s["last_success_ts"] is None  # no data ever came back — irrelevant to the alert


def test_acceptance_genuinely_unfed_source_does_not_alert():
    """A source the user simply didn't feed (Lambda ran + 200'd, no new data) does
    NOT alert — the false-positive class that made the old freshness signal noisy."""
    sentinel = _outcome(None, True, "none", NOW - timedelta(hours=2), "strava")
    v = evaluate_source_health(sentinel, now=NOW)
    assert v["alert"] is False


# ── EMF line ──────────────────────────────────────────────────────────────────
def test_emf_metric_line_shape():
    line = emf_metric_line(source="whoop", succeeded=False, consecutive_failures=3, error_class="auth", timestamp_ms=1749492000000)
    doc = json.loads(line)
    assert doc["Source"] == "whoop"
    assert doc["RunSuccess"] == 0
    assert doc["ConsecutiveFailures"] == 3
    assert doc["ErrorClass"] == "auth"
    cwm = doc["_aws"]["CloudWatchMetrics"][0]
    assert cwm["Namespace"] == "LifePlatform/IngestLiveness"
    metric_names = {m["Name"] for m in cwm["Metrics"]}
    assert metric_names == {"RunSuccess", "ConsecutiveFailures"}
    assert cwm["Dimensions"] == [["Source"]]


def test_ingest_health_sk():
    assert ingest_health_sk("whoop") == "INGEST_HEALTH#whoop"
