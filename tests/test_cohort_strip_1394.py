"""tests/test_cohort_strip_1394.py — The Cohort Strip behavior (#1394, epic #1366).

Proves the load-bearing contract of the anonymous weekly distribution strip, all
offline (no S3, no DynamoDB), by monkeypatching the module's config loader, the
shared rate limiter, and the DynamoDB `table`:

  1. K-ANONYMITY IS A HARD GATE: below n=5 the read handler emits `visible: False`
     with NO distribution at all — never bins, never quartiles (no fabricated chart).
  2. AGGREGATE-ONLY ABOVE THE FLOOR: at/above n=5 it returns a histogram + quartiles
     + Matthew's percentile, and NEVER the individual submitted values.
  3. SUBMISSION reuses the check-in write class: one number, no free text; writes to
     the COHORT#<metric>#<week> partition; rejects out-of-range / non-numeric; honors
     the DDB-backed rate limit (429).
  4. PROVENANCE: n and the week ride on the payload.
"""

import json
import os
import sys
from decimal import Decimal

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "web"))

import site_api_social as se  # noqa: E402

_CFG = {
    "metric_id": "resting_heart_rate",
    "label": "Resting heart rate",
    "unit": "bpm",
    "week": "2026-W30",
    "matthew_value": 52,
    "axis_min": 40,
    "axis_max": 90,
    "lower_is_better": True,
}


def _bodyjson(resp):
    return json.loads(resp["body"])


def _query_returning(values):
    """A fake table.query that yields one COHORT SUBMIT row per value."""

    def _query(**kwargs):
        return {"Items": [{"pk": "COHORT#x", "sk": f"SUBMIT#{i}", "value": Decimal(str(v))} for i, v in enumerate(values)]}

    return _query


# ── 1. K-anonymity HARD gate ────────────────────────────────────────────────────
def test_strip_hidden_below_floor(monkeypatch):
    monkeypatch.setattr(se, "_load_cohort_config", lambda: dict(_CFG))
    monkeypatch.setattr(se.table, "query", _query_returning([48, 55, 60, 62]))  # n=4 < 5
    body = _bodyjson(se.handle_cohort_strip())
    assert body["active"] is True
    assert body["visible"] is False
    assert body["n"] == 4
    assert body["floor"] == 5
    # No fabricated distribution below the floor.
    for forbidden in ("bins", "median", "p25", "p75", "matthew_percentile"):
        assert forbidden not in body, f"{forbidden} leaked below the k-anonymity floor"


def test_strip_inactive_when_no_config(monkeypatch):
    monkeypatch.setattr(se, "_load_cohort_config", lambda: None)
    body = _bodyjson(se.handle_cohort_strip())
    assert body.get("active") is False
    assert "visible" not in body and "n" not in body and "bins" not in body


# ── 2. Aggregate-only above the floor + provenance ──────────────────────────────
def test_strip_visible_at_floor_is_aggregate_only(monkeypatch):
    vals = [45, 48, 50, 52, 55, 58, 62]  # n=7 ≥ 5
    monkeypatch.setattr(se, "_load_cohort_config", lambda: dict(_CFG))
    monkeypatch.setattr(se.table, "query", _query_returning(vals))
    body = _bodyjson(se.handle_cohort_strip())
    assert body["visible"] is True
    assert body["n"] == 7
    assert isinstance(body["bins"], list) and sum(body["bins"]) == 7
    assert body["min"] == 45 and body["max"] == 62
    assert body["median"] == 52
    # Matthew (52) is above 3 of 7 values (45,48,50) → 42/43%-ish; assert it's computed.
    assert 40 <= body["matthew_percentile"] <= 50
    # PROVENANCE: n and week present.
    assert body["n"] == 7 and body["week"] == "2026-W30"
    # AGGREGATE-ONLY: the raw individual values never appear in the payload.
    raw = json.dumps(body)
    assert '"values"' not in raw and "submissions" not in raw
    # A stringified full list of the inputs must not be echoed.
    assert json.dumps(vals) not in raw


# ── 3. Submission: reuse, one-number, isolation, validation, rate limit ─────────
def _submit_event(value):
    return {"body": json.dumps({"value": value}), "requestContext": {"http": {"method": "POST"}}}


def _wire_submit(monkeypatch, captured, allowed=True):
    monkeypatch.setattr(se, "_load_cohort_config", lambda: dict(_CFG))
    monkeypatch.setattr(se, "_RATE_LIMITER_READY", True)
    monkeypatch.setattr(se, "_ddb_rate_check", lambda *a, **k: (allowed, 0, 0))
    monkeypatch.setattr(se, "extract_client_ip", lambda event: "203.0.113.7")
    monkeypatch.setattr(se.table, "put_item", lambda **kw: captured.update(kw))


def test_submit_writes_to_cohort_partition(monkeypatch):
    captured = {}
    _wire_submit(monkeypatch, captured)
    resp = se._handle_cohort_submit(_submit_event(58))
    assert resp["statusCode"] == 200
    item = captured["Item"]
    # Structural isolation: the write lands in the COHORT family, NEVER a USER partition.
    assert item["pk"].startswith(se.COHORT_PK_PREFIX)
    assert item["pk"] == "COHORT#resting_heart_rate#2026-W30"
    assert "USER#" not in item["pk"]
    assert item["sk"].startswith("SUBMIT#")
    assert isinstance(item["value"], Decimal) and float(item["value"]) == 58


def test_submit_rejects_out_of_range(monkeypatch):
    captured = {}
    _wire_submit(monkeypatch, captured)
    resp = se._handle_cohort_submit(_submit_event(500))
    assert resp["statusCode"] == 400
    assert captured == {}, "an out-of-range number must never be written"


def test_submit_rejects_non_numeric(monkeypatch):
    captured = {}
    _wire_submit(monkeypatch, captured)
    for bad in ("fifty", None, True, [1, 2]):
        resp = se._handle_cohort_submit(_submit_event(bad))
        assert resp["statusCode"] == 400
    assert captured == {}


def test_submit_rate_limited_returns_429(monkeypatch):
    captured = {}
    _wire_submit(monkeypatch, captured, allowed=False)
    resp = se._handle_cohort_submit(_submit_event(58))
    assert resp["statusCode"] == 429
    assert captured == {}, "a rate-limited submission must not write"


def test_submit_404_when_no_active_week(monkeypatch):
    monkeypatch.setattr(se, "_load_cohort_config", lambda: None)
    resp = se._handle_cohort_submit(_submit_event(58))
    assert resp["statusCode"] == 404


# ── 5. Config cache invalidation (#1821) ─────────────────────────────────────────
# The bug: `_load_cohort_config` cached into a module global with `if cache is None`
# and stored `... or {}` on failure, so a MISS (or a transient S3 error) was cached
# identically to a hit for the container's entire remaining lifetime — the one config
# designed to rotate weekly. These tests exercise the real `_load_cohort_config`
# (not monkeypatched away) against a fake `_load_s3_json`.
def _reset_cohort_cache(monkeypatch):
    monkeypatch.setattr(se, "_cohort_config_cache", {})
    monkeypatch.setattr(se, "_cohort_config_cache_ts", 0.0)


def test_cached_miss_is_not_sticky(monkeypatch):
    """A miss (no S3 object / malformed config) must NEVER be cached — the very next
    call re-fetches, so publishing a week's config takes effect immediately rather
    than waiting out a TTL or a container recycle."""
    _reset_cohort_cache(monkeypatch)
    calls = {"n": 0}

    def _fake_load(key, cache_name):
        calls["n"] += 1
        return {}  # simulates "no object yet" / S3 error — _load_s3_json's own contract

    monkeypatch.setattr(se, "_load_s3_json", _fake_load)
    assert se._load_cohort_config() is None
    assert se._load_cohort_config() is None
    assert calls["n"] == 2, "a miss must re-fetch on every call, never cache"


def test_hit_is_cached_within_ttl_then_refetched_after(monkeypatch):
    """A successful load IS cached (avoids hammering S3 on every request), but only
    for STATUS_CACHE_TTL seconds — bounding how long a warm container can serve a
    stale/rolled-over week after a new cohort_week.json is published."""
    _reset_cohort_cache(monkeypatch)
    calls = {"n": 0}

    def _fake_load(key, cache_name):
        calls["n"] += 1
        return dict(_CFG)

    monkeypatch.setattr(se, "_load_s3_json", _fake_load)

    import time as _time

    t0 = 1_000_000.0
    monkeypatch.setattr(_time, "time", lambda: t0)
    assert se._load_cohort_config() is not None
    assert calls["n"] == 1

    # Still within TTL — served from cache, no re-fetch.
    monkeypatch.setattr(_time, "time", lambda: t0 + se.STATUS_CACHE_TTL - 1)
    assert se._load_cohort_config() is not None
    assert calls["n"] == 1

    # TTL elapsed — re-fetches, so a rolled-over week is picked up bounded by TTL.
    monkeypatch.setattr(_time, "time", lambda: t0 + se.STATUS_CACHE_TTL + 1)
    assert se._load_cohort_config() is not None
    assert calls["n"] == 2
