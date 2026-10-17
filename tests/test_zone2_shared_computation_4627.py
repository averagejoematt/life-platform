"""tests/test_zone2_shared_computation_4627.py — ONE Zone 2 number on three surfaces (#4627 box 2).

Built on the RECOMMENDED answer to #4644 Q1 (held until the owner rules): "devices' own Zone 2 ·
minutes in zone · Hevy bike/elliptical/treadmill = cardio minutes, not Zone 2".

THE FIXTURE IS THE WIRE. Every row below is a real stored row of the week the issue quotes
(2026-09-28 → 10-04), read with a read-only DynamoDB query / S3 GetObject while building the PR
(ids shortened, values as stored):

  * Strava 09-28 — the stored PAIR the read seam folds: Hevy's 6962 s push of the lifting session
    (no HR) and WHOOP's 2099 s push of part of it (zones 1084 / 986 / 29 s). The fake reader runs
    the real `strava_read_seam` over it, as `_query_source` / `query_source` do.
  * Strava 09-29 — the seam's stored output for that day: Hevy's 8236 s copy carrying the grafted
    WHOOP zone family (4548 / 611 s), `average_heartrate` None.
  * Strava 09-30 — a Garmin epix walk, 6655 s, zones 5511 / 865 / 187 s.
  * Whoop workout sub-rows in the post-#4922 shape (zone fields from `zone_durations`, plus
    `vendor_sport_name`): the 09-28 weightlifting session, the 09-28 "activity" stored under TWO
    UTC date keys (it crosses 00:00 UTC), a null-score stretching row (no zone fields at all), the
    09-29 cross-training row as the pre-#4922 writer stored it (six zeros), and the 09-30 walk under
    two keys.
  * Hevy 09-28 / 09-29 — Cycling 2400 s + Stretching 900 s each.

HAND-DERIVED EXPECTATION (minutes in Zone 2, each session once):
  09-28 lifting session: Whoop measured 35.0 + 40.98 min of it vs Strava's 2099 s → Whoop's own
        zone 2, 8.27 + 10.15 = 18.42 (the duplicate key adds nothing)
  09-28 stretching: no stored time-in-zone → unmeasured, 0
  09-29 lifting session: the Whoop row is the pre-#4922 six zeros (unmeasured) → Strava's 611 s
        = 10.18
  09-30 walk: Whoop measured 109.0 min, Garmin 109.4 → within the 80 % share, Whoop's own 4.68
  Hevy cycling 2 x 40 min → `hevy_cardio_minutes` 80, NOT Zone 2
  TOTAL 18.42 + 10.18 + 4.68 = 33.28 → served 33.3 (1 dp)

The pre-#4627 surfaces served this week as 940 (training_overview, 30-day average) / 517.8
(/api/zone2): whole sessions by average HR, plus every Hevy block.
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
for _k, _v in {
    "S3_BUCKET": "matthew-life-platform",
    "TABLE_NAME": "life-platform",
    "USER_ID": "matthew",
    "AWS_REGION": "us-west-2",
    "AWS_DEFAULT_REGION": "us-west-2",
    "AWS_ACCESS_KEY_ID": "FAKE",
    "AWS_SECRET_ACCESS_KEY": "FAKE",
}.items():
    os.environ.setdefault(_k, _v)

from common.strava_read_seam import strava_read_seam  # noqa: E402
from training import zone2_minutes as z2m  # noqa: E402
from web import (
    site_api_autonomic as az,  # noqa: E402
    site_api_observatory as obs,  # noqa: E402
)

from mcp import tools_correlation as tc  # noqa: E402

# Pacific today = Sunday 2026-10-04, so "trailing 7 days" is exactly the issue's week.
_NOW = datetime(2026, 10, 4, 19, 0, tzinfo=timezone.utc)
TODAY, WEEK_START = "2026-10-04", "2026-09-28"
EXPECTED_Z2 = 33.3
EXPECTED_HEVY_CARDIO = 80.0


class _Frozen(datetime):
    @classmethod
    def now(cls, tz=None):
        return _NOW.astimezone(tz) if tz else _NOW.replace(tzinfo=None)


def _whoop(key_day, wid, start, end, sport, zones=None):
    row = {
        "pk": "USER#matthew#SOURCE#whoop",
        "sk": f"DATE#{key_day}#WORKOUT#{wid}",
        "date": key_day,
        "workout_id": wid,
        "start_time": start,
        "end_time": end,
        "sport_name": "Activity",
        "vendor_sport_name": sport,
    }
    if zones is not None:
        row.update({f"zone_{i}_minutes": m for i, m in enumerate(zones)})
    return row


def _strava_pair_0928():
    hevy = {
        "strava_id": "20372005966",
        "device_name": "Hevy",
        "sport_type": "WeightTraining",
        "type": "WeightTraining",
        "start_date": "2026-09-28T22:53:34Z",
        "start_date_local": "2026-09-28T15:53:34Z",
        "moving_time_seconds": 6962,
        "elapsed_time_seconds": 6962,
        "distance_meters": 0,
        "has_heartrate": False,
        "summary_polyline": "",
    }
    whoop = {
        "strava_id": "20371262252",
        "device_name": "WHOOP",
        "sport_type": "WeightTraining",
        "type": "WeightTraining",
        "start_date": "2026-09-28T22:58:00Z",
        "start_date_local": "2026-09-28T15:58:00Z",
        "moving_time_seconds": 2099,
        "elapsed_time_seconds": 2099,
        "distance_meters": 0,
        "average_heartrate": 125.7,
        "max_heartrate": 165,
        "has_heartrate": True,
        "summary_polyline": "",
        "zone1_seconds": 1084,
        "zone2_seconds": 986,
        "zone3_seconds": 29,
        "zone4_seconds": 0,
        "zone5_seconds": 0,
    }
    return {"pk": "USER#matthew#SOURCE#strava", "sk": "DATE#2026-09-28", "date": "2026-09-28", "activities": [hevy, whoop]}


def _strava_rows():
    seamed_0929 = {
        "strava_id": "20386713837",
        "device_name": "Hevy",
        "sport_type": "WeightTraining",
        "start_date": "2026-09-29T22:44:41Z",
        "elapsed_time_seconds": 8236,
        "moving_time_seconds": 8236,
        "average_heartrate": None,
        "partial_average_heartrate": 111.8,
        "hr_from_strava_id": "20386563442",
        "hr_coverage_share": 0.63,
        "zone1_seconds": 4548,
        "zone2_seconds": 611,
        "zone3_seconds": 0,
        "zone4_seconds": 0,
        "zone5_seconds": 0,
    }
    garmin_walk = {
        "strava_id": "20401105828",
        "device_name": "Garmin epix (Gen2)",
        "sport_type": "Walk",
        "start_date": "2026-09-30T23:10:11Z",
        "elapsed_time_seconds": 6655,
        "moving_time_seconds": 6563,
        "average_heartrate": 116.4,
        "zone1_seconds": 5511,
        "zone2_seconds": 865,
        "zone3_seconds": 187,
        "zone4_seconds": 0,
        "zone5_seconds": 0,
    }
    return [
        _strava_pair_0928(),
        {"pk": "USER#matthew#SOURCE#strava", "sk": "DATE#2026-09-29", "date": "2026-09-29", "activities": [seamed_0929]},
        {"pk": "USER#matthew#SOURCE#strava", "sk": "DATE#2026-09-30", "date": "2026-09-30", "activities": [garmin_walk]},
    ]


def _whoop_rows():
    act = ("60f4ac11", "2026-09-28T23:53:00.240Z", "2026-09-29T00:33:59.230Z", "activity", (0.0, 30.78, 10.15, 0.05, 0.0, 0.0))
    walk = ("bc816278", "2026-09-30T23:14:00.000Z", "2026-10-01T01:02:59.990Z", "walking", (27.37, 72.9, 4.68, 2.4, 1.65, 0.0))
    return [
        {"pk": "USER#matthew#SOURCE#whoop", "sk": "DATE#2026-09-28", "date": "2026-09-28", "strain": 10.5},  # a DAY row
        _whoop(
            "2026-09-28",
            "462944ab",
            "2026-09-28T22:58:00.250Z",
            "2026-09-28T23:32:59.250Z",
            "weightlifting",
            (9.03, 15.83, 8.27, 1.85, 0.0, 0.0),
        ),
        _whoop("2026-09-28", *act),
        _whoop("2026-09-29", *act),  # the same workout id under the next UTC day (#4629 defect 3)
        _whoop("2026-09-29", "4c59b95f", "2026-09-29T00:46:34.034Z", "2026-09-29T01:04:12.980Z", "stretching"),  # null score
        _whoop("2026-09-29", "d49d8bac", "2026-09-29T23:03:00.710Z", "2026-09-30T00:28:59.690Z", "Cross Training", (0, 0, 0, 0, 0, 0)),
        _whoop("2026-09-30", *walk),
        _whoop("2026-10-01", *walk),
    ]


def _hevy_rows():
    def row(day, wid):
        return {
            "pk": "USER#matthew#SOURCE#hevy",
            "sk": f"DATE#{day}#WORKOUT#{wid}",
            "date": day,
            "workout_uid": wid,
            "exercises": [
                {"name": "Dumbbell Row", "sets": [{"reps": 5, "weight_kg": 43.1, "duration_sec": None, "distance_m": None}]},
                {"name": "Cycling", "sets": [{"duration_sec": 2400, "distance_m": 15450}]},
                {"name": "Stretching", "sets": [{"duration_sec": 900}]},
            ],
        }

    return [row("2026-09-28", "e7eb6103"), row("2026-09-29", "ef89d610")]


def _reader(source, start, end, *_a, **_k):
    """The stored partitions, filtered to the key range like `sk BETWEEN DATE#start AND DATE#end~`,
    with the real read seam over Strava — what `_query_source` / `query_source` hand back."""
    rows = {"strava": _strava_rows(), "whoop": _whoop_rows(), "hevy": _hevy_rows()}.get(source, [])
    rows = [dict(r) for r in rows if start <= str(r["sk"])[5:15] <= end]
    return strava_read_seam(source, rows)


class _Table:
    def query(self, **_kw):
        return {"Items": []}


@pytest.fixture
def served(monkeypatch):
    """The three surfaces over the same stored rows and the same frozen Pacific day."""
    monkeypatch.setattr(obs._training, "datetime", _Frozen)
    monkeypatch.setattr(az, "datetime", _Frozen)
    monkeypatch.setattr(obs, "EXPERIMENT_START", "2026-09-06")
    monkeypatch.setattr(obs, "_experiment_date", lambda n=30: max((_NOW - timedelta(days=n)).strftime("%Y-%m-%d"), "2026-09-06"))
    monkeypatch.setattr(obs, "_query_source", _reader)
    monkeypatch.setattr(obs, "table", _Table())
    monkeypatch.setattr(az, "_query_source", _reader)
    monkeypatch.setattr(tc, "query_source", _reader)

    training = json.loads(obs.handle_training_overview()["body"])["training"]
    zone2 = json.loads(az.handle_zone2_breakdown()["body"])
    start, end = z2m.trailing_window(TODAY)
    tool = tc.tool_get_zone2_breakdown({"start_date": start, "end_date": end})
    return training, zone2, tool


def test_the_two_endpoints_and_the_tool_serve_one_zone2_number(served):
    """Box 2's parity: `/api/training_overview`, `/api/zone2` and MCP `get_zone2_breakdown`
    return the SAME Zone 2 minutes for the same trailing window — and it is the hand-derived
    minutes-in-zone figure, not a whole-session or Hevy-inflated one."""
    training, zone2, tool = served
    values = {
        "training_overview.z2_trailing_7d_window.zone_2_minutes": training["z2_trailing_7d_window"]["zone_2_minutes"],
        "zone2.trailing_7d.zone_2_minutes": zone2["trailing_7d"]["zone_2_minutes"],
        "zone2.current_week.zone_2_minutes": zone2["current_week"]["zone_2_minutes"],
        "get_zone2_breakdown.summary.total_zone_2_min": tool["summary"]["total_zone_2_min"],
    }
    assert set(values.values()) == {EXPECTED_Z2}, values
    assert training["z2_trailing_7d_min"] == round(EXPECTED_Z2)
    assert training["z2_trailing_7d_window"]["by_source"] == zone2["trailing_7d"]["by_source"] == tool["summary"]["zone_2_by_source"]


def test_the_trailing_window_covers_exactly_seven_dates(served):
    training, zone2, _tool = served
    for win in (training["z2_trailing_7d_window"], zone2["trailing_7d"]):
        assert (win["start_date"], win["end_date"], win["dates"]) == (WEEK_START, TODAY, 7), win
    assert len(z2m.window_dates(*z2m.trailing_window(TODAY))) == 7


def test_hevy_cardio_is_reported_as_cardio_minutes_never_zone2(served):
    training, zone2, tool = served
    assert zone2["trailing_7d"]["hevy_cardio_minutes"] == tool["summary"]["hevy_cardio_min"] == EXPECTED_HEVY_CARDIO
    assert training["hevy_cardio_minutes_30d"] == EXPECTED_HEVY_CARDIO
    assert EXPECTED_Z2 + EXPECTED_HEVY_CARDIO not in {zone2["trailing_7d"]["zone_2_minutes"], tool["summary"]["total_zone_2_min"]}


def test_each_session_is_counted_once_from_one_source():
    sessions = [s for s in z2m.counted_sessions(_reader("strava", "2026-09-28", TODAY), _reader("whoop", "2026-09-28", "2026-10-05"))]
    by_day = {}
    for s in sessions:
        by_day.setdefault(s["date"], []).append(s)
    lift_0928 = next(s for s in by_day["2026-09-28"] if s["source"])
    assert lift_0928["source"] == "whoop" and lift_0928["zone_2_minutes"] == pytest.approx(18.42)
    assert sorted(u.split(":")[0] for u in lift_0928["used_ids"]) == ["whoop", "whoop"]  # two workouts, the duplicate key not a third
    assert [s["source"] for s in by_day["2026-09-29"]] == ["strava"]  # the six-zero Whoop row is unmeasured
    assert by_day["2026-09-29"][0]["zone_2_minutes"] == pytest.approx(10.18)
    (walk,) = by_day["2026-09-30"]
    assert walk["source"] == "whoop" and walk["zone_2_minutes"] == pytest.approx(4.68)
    unmeasured = [s for s in sessions if not s["source"]]
    assert len(unmeasured) == 1 and unmeasured[0]["zone_2_minutes"] is None  # the null-score stretch: a gap, not a 0


def test_an_all_zero_whoop_row_is_unmeasured_not_a_measured_zero():
    (rec,) = z2m.whoop_recordings([_whoop("2026-09-29", "d49d8bac", "2026-09-29T23:03:00Z", "2026-09-30T00:28:59Z", "x", (0,) * 6)])
    assert rec["zones"] is None


def test_no_average_heart_rate_is_read():
    """A Strava activity with an in-band average HR and no stored zones adds no Zone 2 time."""
    row = {
        "sk": "DATE#2026-09-30",
        "date": "2026-09-30",
        "activities": [{"strava_id": "x", "average_heartrate": 120, "moving_time_seconds": 3600}],
    }
    win = z2m.zone2_window([row], [], [], "2026-09-28", TODAY)
    assert win["zone_2_minutes"] == 0.0 and win["unmeasured_sessions"] == 1
