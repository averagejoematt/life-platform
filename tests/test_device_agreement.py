"""#735 — /verify/ page: GET /api/device_agreement (Whoop vs Apple Watch cross-device
agreement on resting HR — the "two devices disagreeing slightly" credibility signal).

#4976: re-pointed from Garmin (feed retired, #4640) to the Apple Watch. HRV is never
compared — Whoop RMSSD vs Apple SDNN are different statistics.

Pins: agree/minor/flag thresholds (RHR <=3/6bpm — inherited from the former mcp
tool_get_device_agreement, pruned by #395), workout sub-items never corrupt the
day-summary comparison (no resting_heart_rate field), an empty overlap returns a
shaped "unavailable" 200 (ADR-104 honest-gaps semantics, never a 500 or a
silently-empty table), and garmin rows are never read.

Offline — `_query_source` (the shared DDB helper handle_device_agreement calls) is
monkeypatched directly, same pattern as tests/test_historical_window.py.
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

from web import (
    instruments,  # noqa: E402
    site_api_data as sad,  # noqa: E402
    site_api_freshness as saf,  # noqa: E402
)

WATCH_FIRST_DAY = "2026-10-17"  # the registry's apple_health.watch_first_day facet (#5042)


@pytest.fixture
def low_floor(monkeypatch):
    """Threshold tests run 1-3 nights; lift the 30-night study floor and mark the study ruled
    (#4980: no agreement figure is published before the owner's ruling) so the verdict path runs."""
    monkeypatch.setattr(saf, "_DEVICE_AGREEMENT_MIN_NIGHTS", 1)
    monkeypatch.setattr(instruments, "study_ruled", lambda metric=None: True)


def _fake_query_source(per_source):
    def fn(source, start, end, include_pilot=False):
        return per_source.get(source, [])

    return fn


def test_no_overlap_returns_shaped_unavailable_200(monkeypatch):
    monkeypatch.setattr(sad, "_query_source", _fake_query_source({"whoop": [], "apple_health": []}))
    resp = sad.handle_device_agreement()
    assert resp["statusCode"] == 200  # never a 500, never a silent empty table
    body = json.loads(resp["body"])
    assert body["status"] == "unavailable"
    assert body["reason"] and "Apple Watch" in body["reason"]
    assert body["apple_first_date"] is None


def test_rhr_agreement_thresholds_and_flagging(monkeypatch, low_floor):
    monkeypatch.setattr(
        sad,
        "_query_source",
        _fake_query_source(
            {
                "whoop": [
                    {"date": "2026-10-17", "resting_heart_rate": 60},  # |60-61|=1 -> agree
                    {"date": "2026-10-18", "resting_heart_rate": 65},  # |65-78|=13 -> flag
                    {"date": "2026-10-19", "resting_heart_rate": 61},  # |61-56|=5 -> minor
                ],
                "apple_health": [
                    {"date": "2026-10-17", "resting_heart_rate_apple": 61},
                    {"date": "2026-10-18", "resting_heart_rate_apple": 78},
                    {"date": "2026-10-19", "resting_heart_rate_apple": 56},
                ],
            }
        ),
    )
    body = json.loads(sad.handle_device_agreement()["body"])
    assert body["status"] == "ok"
    assert body["devices"] == ["Whoop", "Apple Watch"]
    assert body["period"] == {"start": "2026-10-17", "end": "2026-10-19", "overlapping_days": 3}
    rhr = body["rhr_agreement"]
    assert (rhr["agree_days"], rhr["minor_days"], rhr["flagged_days"]) == (1, 1, 1)
    assert rhr["agreement_rate_pct"] == round(1 / 3 * 100, 1)
    flagged = body["flagged_disagreement_days"]
    assert flagged and flagged[0]["date"] == "2026-10-18"
    # newest-first ordering
    assert [r["date"] for r in body["daily"]] == ["2026-10-19", "2026-10-18", "2026-10-17"]
    # #4980: a night carries its band, never a heart-rate value (the watch's RHR is TIER_INTERNAL)
    assert body["daily"][0] == {"date": "2026-10-19", "rhr_agreement": "minor_variance"}
    assert body["hrv_agreement"] is None


def test_workout_subitems_never_corrupt_the_comparison(monkeypatch, low_floor):
    """Whoop workout sub-records (sk DATE#...#WORKOUT#...) share a `date` with the
    day-summary record but never carry resting_heart_rate — they must not shadow
    the real day-summary row when building the per-date lookup."""
    monkeypatch.setattr(
        sad,
        "_query_source",
        _fake_query_source(
            {
                "whoop": [
                    {"date": "2026-10-19", "resting_heart_rate": 61, "hrv": 42.34},
                    {"date": "2026-10-19", "sport_name": "run", "average_heart_rate": 140},  # workout sub-item
                ],
                "apple_health": [{"date": "2026-10-19", "resting_heart_rate_apple": 56}],
            }
        ),
    )
    body = json.loads(sad.handle_device_agreement()["body"])
    assert body["status"] == "ok"
    assert body["daily"][0] == {"date": "2026-10-19", "rhr_agreement": "minor_variance"}


def test_hrv_is_never_compared_across_rmssd_and_sdnn(monkeypatch):
    """Whoop's `hrv` is RMSSD, Apple's `hrv_sdnn_apple` is SDNN — a delta between them
    is a unit error. Even with both present, no HRV agreement is computed, and the
    payload says why."""
    monkeypatch.setattr(
        sad,
        "_query_source",
        _fake_query_source(
            {
                "whoop": [{"date": "2026-10-19", "resting_heart_rate": 61, "hrv": 42.0}],
                "apple_health": [{"date": "2026-10-19", "resting_heart_rate_apple": 56, "hrv_sdnn_apple": 30.0}],
            }
        ),
    )
    body = json.loads(sad.handle_device_agreement()["body"])
    assert body["hrv_agreement"] is None
    assert "RMSSD" in body["hrv_note"] and "SDNN" in body["hrv_note"]
    assert body["daily"] == []  # #4980: before the study rules no per-night row is served at all


def test_garmin_rows_are_never_read(monkeypatch):
    """#4976: garmin rows stay in the table but are not the second wrist any more. A
    Garmin-only overlap is no overlap, and the garmin partition is never queried.
    (Mutation control: point the endpoint back at garmin and both assertions move.)"""
    asked = []

    def fn(source, start, end, include_pilot=False):
        asked.append(source)
        return {
            "whoop": [{"date": "2026-06-15", "resting_heart_rate": 61}],
            "garmin": [{"date": "2026-06-15", "resting_heart_rate": 56, "hrv_last_night": 40}],
        }.get(source, [])

    monkeypatch.setattr(sad, "_query_source", fn)
    body = json.loads(sad.handle_device_agreement()["body"])
    assert "garmin" not in asked
    assert body["status"] == "unavailable"


def test_route_wired_into_site_api_lambda():
    """The endpoint must actually be reachable — registered in ROUTES, not just defined."""
    src_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas", "web", "site_api_lambda.py")
    with open(src_path, encoding="utf-8") as f:
        src = f.read()
    assert '"/api/device_agreement": handle_device_agreement' in src
    assert "handle_device_agreement" in src.split("from web.site_api_data import")[1].split(")")[0]


# ── #5042: the comparison is the Apple WATCH era only ────────────────────────


def _mixed_era_rows():
    """Phone/other-writer era (before the watch) + watch era, both with an RHR value."""
    whoop, apple = [], []
    for d in ("2025-12-07", "2026-01-15", "2026-03-07", "2026-10-16"):  # pre-watch: Whoop's own app wrote these
        whoop.append({"date": d, "resting_heart_rate": 58})
        apple.append({"date": d, "resting_heart_rate_apple": 58})
    for d in ("2026-10-17", "2026-10-18"):
        whoop.append({"date": d, "resting_heart_rate": 51})
        apple.append({"date": d, "resting_heart_rate_apple": 48})
    return {"whoop": whoop, "apple_health": apple}


def test_registry_carries_the_watch_era_start():
    from ingestion.source_registry import SOURCE_REGISTRY

    era = SOURCE_REGISTRY["apple_health"]["watch_first_day"]
    assert era["date"] == WATCH_FIRST_DAY
    assert "Apple Watch" in era["determined_by"]


def test_phone_era_nights_never_enter_the_comparison(monkeypatch):
    """The live finding: 83 'overlapping' nights from 2025-12-07 when the watch's first RHR is
    2026-10-17. Even when the reader hands back pre-watch rows, only watch-era nights count —
    and the query itself is floored at the era start. (Mutation control: drop the in-memory
    `>= watch_start` floor and n becomes 6, period.start 2025-12-07.)"""
    asked = []
    rows = _mixed_era_rows()

    def fn(source, start, end, include_pilot=False):
        asked.append((source, start))
        return rows.get(source, [])

    monkeypatch.setattr(sad, "_query_source", fn)
    body = json.loads(sad.handle_device_agreement()["body"])
    assert body["n_nights"] == 2
    assert body["period"] == {"start": WATCH_FIRST_DAY, "end": "2026-10-18", "overlapping_days": 2}
    assert body["watch_era"]["start"] == WATCH_FIRST_DAY and body["watch_era"]["determined_by"]
    assert all(start == WATCH_FIRST_DAY for _, start in asked), asked


def test_fewer_than_thirty_nights_is_too_few_not_a_verdict(monkeypatch):
    monkeypatch.setattr(sad, "_query_source", _fake_query_source(_mixed_era_rows()))
    body = json.loads(sad.handle_device_agreement()["body"])
    assert body["status"] == "too_few_nights"
    assert body["min_nights"] == 30
    assert body["combined_agreement_rate_pct"] is None
    assert body["rhr_agreement"] is None
    assert body["device_confidence"] is None
    assert "Too few nights to compare yet" in body["too_few_reason"] and WATCH_FIRST_DAY in body["too_few_reason"]


def _thirty_nights():
    from datetime import date, timedelta

    start = date.fromisoformat(WATCH_FIRST_DAY)
    days = [(start + timedelta(days=i)).isoformat() for i in range(30)]
    return {
        "whoop": [{"date": d, "resting_heart_rate": 55} for d in days],
        "apple_health": [{"date": d, "resting_heart_rate_apple": 54} for d in days],
    }


def test_thirty_nights_without_a_ruling_state_no_agreement(monkeypatch):
    """#4980: 30 nights is the study's floor, not its verdict. Until the owner rules a
    combination in METRIC_TRUTH (#4975, after #4974) the payload says the nights are in and
    the result waits on the ruling — no rate, no confidence words, no per-night band.
    (Mutation control: drop the `state == "ruled"` gate and the rate reappears here.)"""
    monkeypatch.setattr(sad, "_query_source", _fake_query_source(_thirty_nights()))
    body = json.loads(sad.handle_device_agreement()["body"])
    assert body["status"] == "awaiting_ruling" and body["n_nights"] == 30
    assert body["study"] == {"state": "awaiting_ruling", "n_nights": 30, "min_nights": 30, "verdict_published": False}
    assert body["combined_agreement_rate_pct"] is None and body["rhr_agreement"] is None
    assert body["device_confidence"] is None and body["daily"] == []
    assert "ruled on" in body["study_reason"]


def test_thirty_watch_nights_earn_a_verdict_once_ruled(monkeypatch):
    monkeypatch.setattr(instruments, "study_ruled", lambda metric=None: True)
    monkeypatch.setattr(sad, "_query_source", _fake_query_source(_thirty_nights()))
    body = json.loads(sad.handle_device_agreement()["body"])
    assert body["status"] == "ok" and body["n_nights"] == 30
    assert body["combined_agreement_rate_pct"] == 100.0
    assert body["device_confidence"].startswith("HIGH")
