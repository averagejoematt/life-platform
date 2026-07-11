"""tests/test_historical_window.py — Phase 4 historical-window APIs (2026-06-29).

`/api/observatory_week?date=` and `/api/vitals?date=` let a walk-backwards reader see
the platform AS OF a past date — the same time-travel pattern handle_character already
uses. These tests pin the as-of semantics: records served verbatim, future dates clamp
to today, pre-genesis honest-nulls (never 503), pilot/prior-cycle records included only
when time-travelling, and the immutable past caches a full day.

All offline — DynamoDB reads are monkeypatched.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

from fakes import FakeDdbTable  # noqa: E402
from web import (
    site_api_data as data,  # noqa: E402
    site_api_vitals as vitals,  # noqa: E402
)


def _whoop(date, dur=7.4):
    return {"sk": f"DATE#{date}", "recovery_score": 66, "hrv": 61, "resting_heart_rate": 52, "sleep_duration_hours": dur}


# ── observatory_week?date= ────────────────────────────────────────────────────


def test_observatory_week_dated_window_and_flags(monkeypatch):
    seen = {}

    def fake_qs(source, start, end, include_pilot=False):
        seen["window"] = (start, end)
        seen["include_pilot"] = include_pilot
        if source == "whoop":
            return [_whoop("2026-06-18"), _whoop("2026-06-20", 8.1)]
        return []

    monkeypatch.setattr(data, "_query_source", fake_qs)
    resp = data.handle_observatory_week({"domain": "sleep", "date": "2026-06-20"})
    body = json.loads(resp["body"])
    assert resp["statusCode"] == 200
    assert body["time_travel"] is True
    assert body["period"]["end"] == "2026-06-20"  # window anchored to the date
    assert body["as_of_date"] == "2026-06-20"
    assert seen["include_pilot"] is True  # cross-cycle history visible when time-travelling
    # immutable past caches a full day
    assert "max-age=86400" in (resp.get("headers", {}).get("Cache-Control", "") or resp.get("headers", {}).get("cache-control", ""))


def test_observatory_week_dateless_is_live(monkeypatch):
    def fake_qs(source, start, end, include_pilot=False):
        assert include_pilot is False  # live view stays phase-clean
        return [_whoop("2026-06-28"), _whoop("2026-06-27")]

    monkeypatch.setattr(data, "_query_source", fake_qs)
    resp = data.handle_observatory_week({"domain": "sleep"})
    body = json.loads(resp["body"])
    assert body["time_travel"] is False
    assert "max-age=900" in (resp.get("headers", {}).get("Cache-Control", "") or resp.get("headers", {}).get("cache-control", ""))


def test_observatory_week_bad_date(monkeypatch):
    resp = data.handle_observatory_week({"domain": "sleep", "date": "06/20/2026"})
    assert resp["statusCode"] == 400


def test_observatory_week_future_clamps_to_today(monkeypatch):
    # Running-experiment case: genesis is PINNED in the past. Reading the live
    # constant made this test fail during a staged-future-genesis window: the
    # prev window's genesis lower-bound (max(anchor-8d, EXPERIMENT_START))
    # legitimately exceeds today when genesis is tomorrow, so "max end == today"
    # only holds once the experiment is running.
    import datetime as _dt

    today = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")
    monkeypatch.setattr(data, "EXPERIMENT_START", "2026-06-08")
    seen = {"ends": []}

    def fake_qs(source, start, end, include_pilot=False):
        seen["ends"].append(end)
        return []

    monkeypatch.setattr(data, "_query_source", fake_qs)
    resp = data.handle_observatory_week({"domain": "sleep", "date": "2099-01-01"})
    body = json.loads(resp["body"])
    assert resp["statusCode"] == 200
    # the primary window end (the max across the current+prev queries) is clamped to today
    assert max(seen["ends"]) == today
    assert body["as_of_date"] == today


def test_observatory_week_pre_start_future_genesis_is_honest_200(monkeypatch):
    # The pre-genesis window, explicitly (#931 → #948): a reset stages
    # EXPERIMENT_START in the FUTURE. The old behavior served an inverted window
    # (start > end) with fabricated-zero summaries; the #948 contract early-outs
    # to the honest empty shape (null summary + the countdown fields). Genesis
    # pinned far future so the case can't quietly expire (no wall-clock math).
    from web import site_api_common as common

    monkeypatch.setattr(common, "EXPERIMENT_START", "2099-06-01")
    monkeypatch.setattr(data, "EXPERIMENT_START", "2099-06-01")
    monkeypatch.setattr(data, "_query_source", lambda source, start, end, include_pilot=False: [])
    resp = data.handle_observatory_week({"domain": "sleep"})
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["pre_start"] is True
    assert body["start_date"] == "2099-06-01"
    assert body["summary"] is None
    assert body["notable"] is None
    assert body["period"] is None  # never an inverted start>end window
    assert body["as_of_date"] is None


def test_observatory_week_empty_is_honest_200(monkeypatch):
    monkeypatch.setattr(data, "_query_source", lambda *a, **k: [])
    resp = data.handle_observatory_week({"domain": "physical", "date": "2026-04-01"})
    assert resp["statusCode"] == 200  # honest-empty, never 503


# ── vitals?date= ──────────────────────────────────────────────────────────────


def test_vitals_dated_window_anchors(monkeypatch):
    captured = {}

    def fake_qs(source, start, end, include_pilot=False):
        captured.setdefault("calls", []).append((source, start, end, include_pilot))
        if source == "whoop":
            return [_whoop("2026-06-19")]
        return []

    asof_calls = {}

    def fake_asof(source, date, include_pilot=False):
        asof_calls[source] = (date, include_pilot)
        if source == "withings":
            return {"sk": "DATE#2026-06-18", "weight_lbs": 250.0}
        return None

    monkeypatch.setattr(vitals, "_query_source", fake_qs)
    monkeypatch.setattr(vitals, "_latest_item_asof", fake_asof)
    monkeypatch.setattr(vitals, "_latest_item", lambda *a, **k: {})

    resp = vitals.handle_vitals(date="2026-06-20")
    body = json.loads(resp["body"])
    v = body["vitals"]
    assert v["time_travel"] is True
    assert v["weight_lbs"] == 250  # the latest weigh-in on-or-before the anchor
    # the as-of lookups were date-bounded with include_pilot=True
    assert asof_calls["withings"][1] is True
    # whoop window ends at the anchor, include_pilot=True
    whoop_calls = [c for c in captured["calls"] if c[0] == "whoop"]
    assert all(c[2] == "2026-06-20" and c[3] is True for c in whoop_calls)
    assert "max-age=86400" in (resp.get("headers", {}).get("Cache-Control", "") or resp.get("headers", {}).get("cache-control", ""))


def test_vitals_dateless_unchanged(monkeypatch):
    # The live path must keep using _latest_item (absolute latest), include_pilot False.
    used = {}

    def fake_qs(source, start, end, include_pilot=False):
        used["ip"] = include_pilot
        return [_whoop("2026-06-28")] if source == "whoop" else []

    monkeypatch.setattr(vitals, "_query_source", fake_qs)
    monkeypatch.setattr(vitals, "_latest_item", lambda *a, **k: {"sk": "DATE#2026-06-28", "weight_lbs": 248.0})

    def _boom(*a, **k):
        raise AssertionError("dateless path must not call _latest_item_asof")

    monkeypatch.setattr(vitals, "_latest_item_asof", _boom)
    resp = vitals.handle_vitals()
    body = json.loads(resp["body"])
    assert body["vitals"]["time_travel"] is False
    assert used["ip"] is False


def test_vitals_honest_null_when_absent(monkeypatch):
    monkeypatch.setattr(vitals, "_query_source", lambda *a, **k: [])
    monkeypatch.setattr(vitals, "_latest_item_asof", lambda *a, **k: None)
    monkeypatch.setattr(vitals, "_latest_item", lambda *a, **k: None)
    resp = vitals.handle_vitals(date="2026-06-20")
    body = json.loads(resp["body"])
    assert resp["statusCode"] == 200
    assert body["vitals"]["weight_lbs"] is None
    assert body["vitals"]["time_travel"] is True


def test_vitals_bad_date():
    assert vitals.handle_vitals(date="nope")["statusCode"] == 400


# ── the date-bounded latest helper ────────────────────────────────────────────


def test_latest_item_asof_queries_on_or_before(monkeypatch):
    from web import site_api_common as common

    table = FakeDdbTable(rows=[{"sk": "DATE#2026-06-18", "weight_lbs": 250}])
    monkeypatch.setattr(common, "table", table)
    out = common._latest_item_asof("withings", "2026-06-20", include_pilot=True)
    assert out["weight_lbs"] == 250
    # the key condition bounds the upper SK at DATE#{date} and scans newest-first
    captured_kwargs = table.query_calls[-1]
    assert captured_kwargs["ScanIndexForward"] is False
    assert captured_kwargs["Limit"] == 1
