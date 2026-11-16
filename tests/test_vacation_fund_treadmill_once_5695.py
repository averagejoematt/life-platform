"""#5695 — the vacation fund counts each treadmill session's miles ONCE.

`vacation_fund` added Strava's `total_distance_miles` to Hevy's `distance_m`. From the owner's
2026-10-26 recording protocol the watch records the treadmill Walk INSIDE the Hevy session whose
Treadmill set logs the same distance, so those miles were summed twice. The fix joins the two with
`training.workout_identity.resolve_workout_identities` (the time-overlap rule `session_count`,
`walking_volume` and the brief's cardio list #5697 use) and counts a joined block at Hevy's distance.

The replay is the live wire: `tests/fixtures/vacation_fund_treadmill_once_5695/` is a read-only copy
of the `strava` and `hevy` partitions DATE#2026-10-20 → 11-10, stripped to the fields these readers
use, loaded with Decimal numbers as boto3 returns them. Every window is passed explicitly — no clock.
"""

import json
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from common.strava_read_seam import strava_read_seam
from content import vacation_fund as vf

FIXTURE = Path(__file__).parent / "fixtures" / "vacation_fund_treadmill_once_5695" / "wire_2026_10_20_to_11_10.json"
FIRST, LAST = "2026-10-26", "2026-11-10"
WATCH = "Apple Watch Ultra 4"
_CFG = {"rate_per_mile": 1.0, "start_date": None, "included_sport_types": "all", "extra_sources": ["hevy"], "manual_adjustment_usd": 0.0}

#: The treadmill days on the wire: a Hevy Treadmill set with a distance AND the watch's Walk inside that session.
TREADMILL_DAYS = ("2026-10-26", "2026-10-28", "2026-10-29", "2026-11-02", "2026-11-03", "2026-11-05", "2026-11-09")


@pytest.fixture(scope="module")
def wire():
    return json.loads(FIXTURE.read_text(), parse_float=Decimal, parse_int=Decimal)


@pytest.fixture
def live(wire, monkeypatch):
    """`_query_range` over the fixture, through the read seam exactly as the DDB reader applies it."""

    def query(partition, start, end):
        rows = [r for r in wire.get(partition, []) if f"DATE#{start}" <= r["sk"] <= f"DATE#{end}￿"]
        return strava_read_seam(partition, rows)

    monkeypatch.setattr(vf, "_query_range", query)
    monkeypatch.setattr(vf, "load_config", lambda: dict(_CFG))
    return wire


def _days():
    d, last = date.fromisoformat(FIRST), date.fromisoformat(LAST)
    while d <= last:
        yield d.isoformat()
        d += timedelta(days=1)


def _old_rule(day):
    """The pre-#5695 sum: the Strava day total plus every Hevy distance of the day."""
    strava = vf._query_range("strava", day, day)
    hevy = vf._query_range("hevy", day, day)
    return round(sum(vf._f(r.get("total_distance_miles")) for r in strava) + vf._hevy_miles(hevy), 2)


def _watch_walk_miles(wire, day):
    return sum(
        float(a["distance_miles"])
        for r in wire["strava"]
        if r["date"] == day
        for a in r["activities"]
        if a.get("device_name") == WATCH and a.get("sport_type") == "Walk"
    )


def test_the_wire_holds_the_specimen_the_old_rule_counted_twice(live):
    """Before the fix, each treadmill day's total is Hevy's treadmill miles PLUS the watch's walk of it."""
    for day in TREADMILL_DAYS:
        hevy = vf._hevy_miles(vf._query_range("hevy", day, day))
        assert hevy > 1.0 and _watch_walk_miles(live, day) > 1.0, day
        assert _old_rule(day) == pytest.approx(hevy + _watch_walk_miles(live, day), abs=0.02), day


def test_each_treadmill_session_counts_once_at_hevys_distance(live):
    """Replay 10-26 → 11-10 one day at a time: on a treadmill day the watch's walk adds nothing to Hevy's
    miles; on every other day the fund is the old sum unchanged."""
    affected = {}
    for day in _days():
        out = vf.compute_vacation_fund(start_date=day, end_date=day)
        old = _old_rule(day)
        if day in TREADMILL_DAYS:
            assert out["total_miles"] == out["per_source"]["hevy"], day  # the watch walk is the same miles
            assert out["per_source"]["strava"] == 0.0, day
            assert old - out["total_miles"] == pytest.approx(_watch_walk_miles(live, day), abs=0.02), day
            affected[day] = (old, out["total_miles"])
        else:
            assert out["total_miles"] == old, day
    assert sorted(affected) == list(TREADMILL_DAYS)


def test_the_window_total_drops_by_exactly_the_watch_treadmill_miles(live):
    out = vf.compute_vacation_fund(start_date=FIRST, end_date=LAST)
    old = round(sum(_old_rule(d) for d in _days()), 2)
    watch = round(sum(_watch_walk_miles(live, d) for d in TREADMILL_DAYS), 2)
    assert watch == pytest.approx(16.92, abs=0.001)
    assert out["total_miles"] == pytest.approx(old - watch, abs=0.02)
    assert any("7 Strava activities (16.92 mi)" in w and "counted once" in w for w in out["warnings"])


def test_outdoor_walks_and_distance_less_gym_rides_are_untouched(live):
    """A watch walk with no Hevy session around it is the only record of those miles; a watch gym Ride
    carries no distance, so Hevy's Cycling distance is the one count either way."""
    for day in ("2026-10-27", "2026-10-31", "2026-11-04", "2026-11-07"):
        out = vf.compute_vacation_fund(start_date=day, end_date=day)
        assert out["per_source"]["strava"] == pytest.approx(_watch_walk_miles(live, day), abs=0.01), day
    for day in ("2026-10-30", "2026-11-01", "2026-11-06", "2026-11-08"):
        out = vf.compute_vacation_fund(start_date=day, end_date=day)
        assert out["total_miles"] == _old_rule(day) and out["per_source"]["hevy"] > 0, day


def test_mutation_without_the_shared_join_the_double_count_returns(live, monkeypatch):
    """Mutation check: replace the workout-identity join with one that joins nothing and the replay's
    claim fails — the treadmill days are summed twice again (the assertion above would red)."""
    monkeypatch.setattr(vf, "resolve_workout_identities", lambda **_kw: [])
    for day in TREADMILL_DAYS:
        out = vf.compute_vacation_fund(start_date=day, end_date=day)
        assert out["total_miles"] == _old_rule(day)
        assert out["total_miles"] > out["per_source"]["hevy"]


def _row(day, start, end, exercises):
    return {"sk": f"DATE#{day}#WORKOUT#w1", "date": day, "start_time": start, "end_time": end, "exercises": exercises}


def _walk(sid, start, secs, miles):
    return {
        "strava_id": sid,
        "sport_type": "Walk",
        "device_name": WATCH,
        "start_date": start,
        "elapsed_time_seconds": secs,
        "distance_miles": miles,
    }


def test_a_hevy_block_with_no_distance_keeps_the_watchs_miles():
    """Counted once either way: when Hevy logged the treadmill block's time but no distance, the watch's
    miles are the only measurement and stay."""
    hevy = [
        _row(
            "2026-11-01",
            "2026-11-01T18:00:00+00:00",
            "2026-11-01T20:00:00+00:00",
            [{"name": "Treadmill", "sets": [{"duration_sec": 2700}]}],
        )
    ]
    strava = [{"date": "2026-11-01", "activities": [_walk("s1", "2026-11-01T19:00:00Z", 2700, 2.4)]}]
    assert vf.logged_by_hevy(strava, hevy) == {}
    hevy[0]["exercises"][0]["sets"][0]["distance_m"] = 3900
    assert vf.logged_by_hevy(strava, hevy) == {"s1": 2.4}


def test_a_walk_outside_the_session_is_never_joined():
    hevy = [
        _row(
            "2026-11-01",
            "2026-11-01T18:00:00+00:00",
            "2026-11-01T20:00:00+00:00",
            [{"name": "Treadmill", "sets": [{"duration_sec": 2700, "distance_m": 3900}]}],
        )
    ]
    strava = [{"date": "2026-11-01", "activities": [_walk("s2", "2026-11-01T22:00:00Z", 2700, 2.4)]}]
    assert vf.logged_by_hevy(strava, hevy) == {}
