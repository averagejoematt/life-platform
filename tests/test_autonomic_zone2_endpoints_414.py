"""
/api/autonomic_balance + /api/zone2 — the two computed views ported from the private
MCP tools to the data door (#414, RQA-06/07).

Pins both the honest empty state (below the day threshold / no qualifying activity ⇒
explicit "not available", never a fabricated value) and a real payload. All offline —
the pure `_compute_*` functions are exercised directly, and the handlers with
_query_source monkeypatched. #4627: Zone 2 is minutes in each device's own Zone 2 from the
stored time-in-zone (`zone2_seconds`), never a whole activity by its average HR.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

import json  # noqa: E402

from web import site_api_autonomic as az  # noqa: E402

# ── fixtures ──────────────────────────────────────────────────────────────────


def _whoop_days(n, base_hrv=60.0):
    """n synthetic Whoop day records with a mild upward HRV drift so the quadrant
    classification has real spread."""
    out = []
    for i in range(n):
        out.append(
            {
                "sk": f"DATE#2026-06-{i + 1:02d}",
                "date": f"2026-06-{i + 1:02d}",
                "recovery_score": 55 + (i % 5),
                "hrv": base_hrv + (i - n / 2) * 1.5,
                "resting_heart_rate": 58 - (i % 3),
                "respiratory_rate": 15.0 + (i % 2) * 0.5,
                "sleep_efficiency_percentage": 88.0 + (i % 4),
            }
        )
    return out


def _strava_days_with_z2(dates=("2026-06-01", "2026-06-03", "2026-06-08", "2026-06-10")):
    """Two weeks of Strava days, one Zone-2 run each — 45 min in Strava's own Zone 2."""
    days = []
    for d in dates:
        days.append(
            {
                "sk": f"DATE#{d}",
                "date": d,
                "activities": [
                    {
                        "name": "Zone 2 base run",
                        "sport_type": "Run",
                        "moving_time_seconds": 45 * 60,
                        "average_heartrate": 124.0,
                        "zone2_seconds": 45 * 60,  # the strava writer's time-in-zone field
                    }
                ],
            }
        )
    return days


# ── autonomic balance ─────────────────────────────────────────────────────────


def test_autonomic_thin_data_is_honest_not_fabricated():
    out = az._compute_autonomic_balance(_whoop_days(4))
    assert out["available"] is False
    assert "days" in out["reason"].lower()
    assert out["days_with_data"] == 4
    # No fabricated quadrant / score leaks through the empty state.
    assert "current_state" not in out


def test_autonomic_real_payload_places_current_state():
    out = az._compute_autonomic_balance(_whoop_days(20))
    assert out["available"] is True
    assert out["period"]["days_with_data"] == 20
    cur = out["current_state"]
    assert cur["quadrant"] in ("FLOW", "STRESS", "RECOVERY", "BURNOUT")
    assert 0 <= cur["balance_score"] <= 100
    assert cur["days_in_state"] >= 1
    # 7-day distribution never invents days it doesn't have
    assert sum(out["seven_day_trend"]["state_distribution"].values()) == min(7, 20)
    # every daily state is a real classified day
    assert len(out["daily_states"]) == 20
    for ds in out["daily_states"]:
        assert ds["quadrant"] in ("FLOW", "STRESS", "RECOVERY", "BURNOUT")


def test_autonomic_reads_real_efficiency_field():
    """The valence axis must read `sleep_efficiency_percentage` (the populated key), so a
    record missing it doesn't silently zero the axis for every day."""
    days = _whoop_days(10)
    # bump efficiency hard on the last day; its z-score should be non-zero
    days[-1]["sleep_efficiency_percentage"] = 99.0
    out = az._compute_autonomic_balance(days)
    assert out["available"] is True


def test_autonomic_handler_empty_state(monkeypatch):
    monkeypatch.setattr(az, "_query_source", lambda *a, **k: _whoop_days(3))
    resp = az.handle_autonomic_balance()
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["available"] is False


def test_autonomic_handler_real_payload(monkeypatch):
    monkeypatch.setattr(az, "_query_source", lambda *a, **k: _whoop_days(20))
    resp = az.handle_autonomic_balance()
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["available"] is True
    assert body["current_state"]["quadrant"] in ("FLOW", "STRESS", "RECOVERY", "BURNOUT")


# ── zone 2 ────────────────────────────────────────────────────────────────────


def test_zone2_no_activity_is_honest():
    out = az._compute_zone2_breakdown([])
    assert out["available"] is False
    assert out["weekly_target_min"] == 150
    assert "weeks" not in out  # nothing fabricated


def test_zone2_an_average_hr_alone_is_never_zone2_minutes():
    """#4627: an activity whose average HR sits in the old 60–70% band but carries no stored
    time-in-zone adds NOTHING to Zone 2 — it is an unmeasured session, not 45 Zone 2 minutes."""
    days = [{"date": "2026-06-01", "activities": [{"name": "no zones", "moving_time_seconds": 45 * 60, "average_heartrate": 124}]}]
    out = az._compute_zone2_breakdown(days, today="2026-06-02")
    assert out["available"] is True
    assert out["summary"]["total_zone_2_min"] == 0
    assert out["summary"]["unmeasured_sessions"] == 1


def test_zone2_real_payload_against_150_reference():
    out = az._compute_zone2_breakdown(_strava_days_with_z2(), today="2026-06-14")
    assert out["available"] is True
    assert out["weekly_target_min"] == 150
    assert out["period"]["weeks_analyzed"] == 2
    # each week has two 45-min zone-2 runs (06-01+06-03, 06-08+06-10) → 90 min
    for w in out["weeks"]:
        assert w["zone_2_minutes"] == 90.0
        assert w["target_pct"] == 60  # 90/150
        assert w["target_met"] is False
    # distribution attributes all the time to zone_2
    z2 = next(z for z in out["zone_distribution"] if z["zone"] == "zone_2")
    assert z2["total_minutes"] == 180.0
    assert out["summary"]["total_zone_2_min"] == 180.0
    assert out["summary"]["max_hr_used"] is None  # #4627: no maximum assumed — each device's own band
    assert out["sport_breakdown"][0]["sport_type"] == "Run"


def test_zone2_handler_real_payload(monkeypatch):
    from datetime import datetime, timedelta

    now = datetime.now(az.PT)  # the handler reads 90 days back from its own Pacific today
    recent = tuple((now - timedelta(days=n)).strftime("%Y-%m-%d") for n in (2, 4, 9, 11))
    monkeypatch.setattr(az, "_query_source", lambda src, *a, **k: _strava_days_with_z2(recent) if src == "strava" else [])
    resp = az.handle_zone2_breakdown()
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["available"] is True
    assert body["summary"]["total_zone_2_min"] == 180.0


def test_zone2_handler_empty_state(monkeypatch):
    monkeypatch.setattr(az, "_query_source", lambda *a, **k: [])
    resp = az.handle_zone2_breakdown()
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["available"] is False
