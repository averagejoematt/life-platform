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

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

from web import site_api_data as sad  # noqa: E402


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


def test_rhr_agreement_thresholds_and_flagging(monkeypatch):
    monkeypatch.setattr(
        sad,
        "_query_source",
        _fake_query_source(
            {
                "whoop": [
                    {"date": "2026-10-13", "resting_heart_rate": 60},  # |60-61|=1 -> agree
                    {"date": "2026-10-14", "resting_heart_rate": 65},  # |65-78|=13 -> flag
                    {"date": "2026-10-15", "resting_heart_rate": 61},  # |61-56|=5 -> minor
                ],
                "apple_health": [
                    {"date": "2026-10-13", "resting_heart_rate_apple": 61},
                    {"date": "2026-10-14", "resting_heart_rate_apple": 78},
                    {"date": "2026-10-15", "resting_heart_rate_apple": 56},
                ],
            }
        ),
    )
    body = json.loads(sad.handle_device_agreement()["body"])
    assert body["status"] == "ok"
    assert body["devices"] == ["Whoop", "Apple Watch"]
    assert body["period"] == {"start": "2026-10-13", "end": "2026-10-15", "overlapping_days": 3}
    rhr = body["rhr_agreement"]
    assert (rhr["agree_days"], rhr["minor_days"], rhr["flagged_days"]) == (1, 1, 1)
    assert rhr["agreement_rate_pct"] == round(1 / 3 * 100, 1)
    flagged = body["flagged_disagreement_days"]
    assert flagged and flagged[0]["date"] == "2026-10-14"
    # newest-first ordering
    assert [r["date"] for r in body["daily"]] == ["2026-10-15", "2026-10-14", "2026-10-13"]
    assert body["daily"][0]["apple_rhr_bpm"] == 56.0
    assert body["hrv_agreement"] is None


def test_workout_subitems_never_corrupt_the_comparison(monkeypatch):
    """Whoop workout sub-records (sk DATE#...#WORKOUT#...) share a `date` with the
    day-summary record but never carry resting_heart_rate — they must not shadow
    the real day-summary row when building the per-date lookup."""
    monkeypatch.setattr(
        sad,
        "_query_source",
        _fake_query_source(
            {
                "whoop": [
                    {"date": "2026-10-15", "resting_heart_rate": 61, "hrv": 42.34},
                    {"date": "2026-10-15", "sport_name": "run", "average_heart_rate": 140},  # workout sub-item
                ],
                "apple_health": [{"date": "2026-10-15", "resting_heart_rate_apple": 56}],
            }
        ),
    )
    body = json.loads(sad.handle_device_agreement()["body"])
    assert body["status"] == "ok"
    assert body["daily"][0]["whoop_rhr_bpm"] == 61.0


def test_hrv_is_never_compared_across_rmssd_and_sdnn(monkeypatch):
    """Whoop's `hrv` is RMSSD, Apple's `hrv_sdnn_apple` is SDNN — a delta between them
    is a unit error. Even with both present, no HRV agreement is computed, and the
    payload says why."""
    monkeypatch.setattr(
        sad,
        "_query_source",
        _fake_query_source(
            {
                "whoop": [{"date": "2026-10-15", "resting_heart_rate": 61, "hrv": 42.0}],
                "apple_health": [{"date": "2026-10-15", "resting_heart_rate_apple": 56, "hrv_sdnn_apple": 30.0}],
            }
        ),
    )
    body = json.loads(sad.handle_device_agreement()["body"])
    assert body["hrv_agreement"] is None
    assert "RMSSD" in body["hrv_note"] and "SDNN" in body["hrv_note"]
    assert "hrv_abs_diff_ms" not in body["daily"][0]


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
