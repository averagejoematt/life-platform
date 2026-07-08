"""#735 — /verify/ page: GET /api/device_agreement (Whoop vs Garmin cross-device
agreement on HRV + RHR — the "two devices disagreeing slightly" credibility signal).

Pins: agree/minor/flag thresholds match the private mcp/tools_habits.py
tool_get_device_agreement exactly (RHR <=3/6bpm, HRV <=10/20ms), workout sub-items
never corrupt the day-summary comparison (no resting_heart_rate field), an empty
overlap returns a shaped "unavailable" 200 (ADR-104 honest-gaps semantics, never a
500 or a silently-empty table), and a live Garmin pause is surfaced honestly.

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
    monkeypatch.setattr(sad, "_query_source", _fake_query_source({"whoop": [], "garmin": []}))
    resp = sad.handle_device_agreement()
    assert resp["statusCode"] == 200  # never a 500, never a silent empty table
    body = json.loads(resp["body"])
    assert body["status"] == "unavailable"
    assert body["reason"]
    assert body["garmin_last_date"] is None


def test_rhr_agreement_thresholds_and_flagging(monkeypatch):
    monkeypatch.setattr(
        sad,
        "_query_source",
        _fake_query_source(
            {
                "whoop": [
                    {"date": "2026-06-13", "resting_heart_rate": 60},  # |60-61|=1 -> agree
                    {"date": "2026-06-14", "resting_heart_rate": 65},  # |65-78|=13 -> flag
                    {"date": "2026-06-15", "resting_heart_rate": 61},  # |61-56|=5 -> minor
                ],
                "garmin": [
                    {"date": "2026-06-13", "resting_heart_rate": 61},
                    {"date": "2026-06-14", "resting_heart_rate": 78},
                    {"date": "2026-06-15", "resting_heart_rate": 56},
                ],
            }
        ),
    )
    body = json.loads(sad.handle_device_agreement()["body"])
    assert body["status"] == "ok"
    assert body["period"] == {"start": "2026-06-13", "end": "2026-06-15", "overlapping_days": 3}
    rhr = body["rhr_agreement"]
    assert (rhr["agree_days"], rhr["minor_days"], rhr["flagged_days"]) == (1, 1, 1)
    assert rhr["agreement_rate_pct"] == round(1 / 3 * 100, 1)
    flagged = body["flagged_disagreement_days"]
    assert flagged and flagged[0]["date"] == "2026-06-14"
    # newest-first ordering
    assert [r["date"] for r in body["daily"]] == ["2026-06-15", "2026-06-14", "2026-06-13"]
    # HRV never present in this fixture -> null, not a fabricated zero
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
                    {"date": "2026-06-15", "resting_heart_rate": 61, "hrv": 42.34},
                    {"date": "2026-06-15", "sport_name": "run", "average_heart_rate": 140},  # workout sub-item
                ],
                "garmin": [{"date": "2026-06-15", "resting_heart_rate": 56}],
            }
        ),
    )
    body = json.loads(sad.handle_device_agreement()["body"])
    assert body["status"] == "ok"
    assert body["daily"][0]["whoop_rhr_bpm"] == 61.0


def test_hrv_agreement_when_both_devices_report_it(monkeypatch):
    monkeypatch.setattr(
        sad,
        "_query_source",
        _fake_query_source(
            {
                "whoop": [{"date": "2026-06-15", "resting_heart_rate": 61, "hrv": 42.0}],
                "garmin": [{"date": "2026-06-15", "resting_heart_rate": 56, "hrv_last_night": 30.0}],  # |42-30|=12 -> minor
            }
        ),
    )
    body = json.loads(sad.handle_device_agreement()["body"])
    hrv = body["hrv_agreement"]
    assert hrv is not None
    assert hrv["minor_days"] == 1 and hrv["agree_days"] == 0 and hrv["flagged_days"] == 0


def test_garmin_paused_flag_reflects_real_last_date(monkeypatch):
    monkeypatch.setattr(
        sad,
        "_query_source",
        _fake_query_source(
            {
                "whoop": [{"date": "2026-06-15", "resting_heart_rate": 61}, {"date": "2026-07-05", "resting_heart_rate": 60}],
                "garmin": [{"date": "2026-06-15", "resting_heart_rate": 56}],
            }
        ),
    )
    body = json.loads(sad.handle_device_agreement()["body"])
    assert body["garmin_last_date"] == "2026-06-15"
    assert body["garmin_paused"] is True


def test_route_wired_into_site_api_lambda():
    """The endpoint must actually be reachable — registered in ROUTES, not just defined."""
    src_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas", "web", "site_api_lambda.py")
    with open(src_path, encoding="utf-8") as f:
        src = f.read()
    assert '"/api/device_agreement": handle_device_agreement' in src
    assert "handle_device_agreement" in src.split("from web.site_api_data import")[1].split(")")[0]
