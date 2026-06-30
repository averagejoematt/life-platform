"""tests/test_vitals_frame.py — temporal-frame honesty (2026-06-17).

/api/vitals must tell the front-end which temporal frame its readings belong to:
recovery/sleep/HRV/RHR are wake-date-keyed (about LAST NIGHT, setting up the
as_of_date morning), while weight is same-day. These tests pin the additive
`frame` + `night_of` fields so a reader can be told "the night of <date>"
precisely even when the latest record lags a day or two.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

from web import site_api_vitals as vitals  # noqa: E402


def _whoop_record(date):
    return {
        "sk": f"DATE#{date}",
        "recovery_score": 66,
        "hrv": 61,
        "resting_heart_rate": 52,
        "sleep_duration_hours": 7.4,
    }


def test_vitals_frame_and_night_of(monkeypatch):
    def fake_query_source(source, start, end, include_pilot=False):
        if source == "whoop":
            return [_whoop_record("2026-06-17")]
        return []  # no withings/weight series

    monkeypatch.setattr(vitals, "_query_source", fake_query_source)
    monkeypatch.setattr(vitals, "_latest_item", lambda *_a, **_k: {})

    resp = vitals.handle_vitals()
    assert resp["statusCode"] == 200
    v = json.loads(resp["body"])["vitals"]

    assert v["as_of_date"] == "2026-06-17"
    # the reading came from the night before the wake date
    assert v["frame"] == "last_night"
    assert v["night_of"] == "2026-06-16"
    # the actual readings still surface
    assert v["recovery_pct"] == 66
    assert v["sleep_hours"] == 7.4


def test_vitals_trends_are_chronological_regardless_of_query_order(monkeypatch):
    """AUDIT BUG-04: hrv/rhr trends must be computed oldest→newest by an EXPLICIT
    sort, not by accidental query-return order. Feed records SHUFFLED and assert the
    trend still reflects the real chronology (rising HRV + falling RHR = improving)."""
    # 8 days, oldest→newest: HRV climbs (higher = better), RHR falls (lower = better).
    days = [
        ("2026-06-01", 50, 60),
        ("2026-06-02", 52, 59),
        ("2026-06-03", 54, 58),
        ("2026-06-04", 56, 57),
        ("2026-06-05", 58, 54),
        ("2026-06-06", 60, 53),
        ("2026-06-07", 62, 52),
        ("2026-06-08", 64, 50),
    ]
    records = [{"sk": f"DATE#{d}", "recovery_score": 70, "hrv": hrv, "resting_heart_rate": rhr} for (d, hrv, rhr) in days]
    # Deterministically shuffle (no Math.random / time): reverse + interleave halves.
    shuffled = records[::-1]
    shuffled = shuffled[1::2] + shuffled[0::2]

    monkeypatch.setattr(vitals, "_query_source", lambda *a, **k: list(shuffled))
    monkeypatch.setattr(vitals, "_latest_item", lambda *_a, **_k: {})

    v = json.loads(vitals.handle_vitals()["body"])["vitals"]
    assert v["hrv_trend"] == "improving"  # HRV rose over the window
    assert v["rhr_trend"] == "improving"  # RHR fell over the window (lower is better)


def test_vitals_no_op_sort_is_gone():
    """Source-regression: the misleading `key=lambda _: 0` no-op sorts and the dead
    discarded comprehension must not return. See AUDIT BUG-04."""
    src = open(
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas", "web", "site_api_vitals.py"),
        encoding="utf-8",
    ).read()
    assert "key=lambda _: 0" not in src
    assert "whoop_30d_sorted" in src


def test_vitals_night_of_handles_missing_record(monkeypatch):
    # No whoop data at all → as_of falls back to today, night_of computes off it.
    monkeypatch.setattr(vitals, "_query_source", lambda *_a, **_k: [])
    monkeypatch.setattr(vitals, "_latest_item", lambda *_a, **_k: {})

    resp = vitals.handle_vitals()
    assert resp["statusCode"] == 200
    v = json.loads(resp["body"])["vitals"]
    # frame is always declared; night_of is a valid date string (today - 1)
    assert v["frame"] == "last_night"
    assert isinstance(v["night_of"], str) and len(v["night_of"]) == 10
