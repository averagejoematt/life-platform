"""#5697 — the physical coach's weekly cardio list shows each gym cardio block ONCE.

`brief_domain_inputs._strava_activities` dropped only Hevy's own Strava push, so from the owner's
2026-10-26 recording protocol on, the watch's gym Ride / treadmill Walk — recorded INSIDE the Hevy
session that already logs that block — was listed in `cardio_activities_7d` as extra cardio beside
it. The fix reads Strava through `common.strava_read_seam` and joins each activity to a Hevy session
by `training.workout_identity`'s overlap rule (the same one `session_count` / `walking_volume`
count with): a held block rides on its session as `wearable_blocks`.

The replay is the live wire: `tests/fixtures/brief_strava_read_seam_5697/` is a read-only copy of
the `strava` (DATE#2026-10-20 → 11-08) and `hevy` (DATE#2026-10-19 → 11-08) partitions, stripped to
the fields these readers use, loaded with Decimal numbers as boto3 returns them. Each subject day
10-26 → 11-08 is replayed through `training_block` with the brief's own windows (Strava 7 days,
Hevy 14 days, ending at the subject day). No clock is read: the subject day is the input.
"""

import json
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from intelligence import brief_domain_inputs as bdi

FIXTURE = Path(__file__).parent / "fixtures" / "brief_strava_read_seam_5697" / "wire_2026_10_20_to_11_08.json"
FIRST, LAST = date(2026, 10, 26), date(2026, 11, 8)
WATCH = "Apple Watch Ultra 4"


@pytest.fixture(scope="module")
def wire():
    return json.loads(FIXTURE.read_text(), parse_float=Decimal, parse_int=Decimal)


def _gym_days(wire):
    return sorted({r["date"] for r in wire["hevy"] if FIRST.isoformat() <= r["date"] <= LAST.isoformat()})


def _watch_gym_blocks(wire):
    """(date, sport) of the watch's activity on each gym day — the specimen the issue names."""
    gym = set(_gym_days(wire))
    return {
        (a["start_date_local"][:10], a["sport_type"])
        for r in wire["strava"]
        for a in r["activities"]
        if a["device_name"] == WATCH and a["start_date_local"][:10] in gym and a["sport_type"] in ("Ride", "Walk")
    }


def _replay(wire):
    """One `training_block` per subject day, with the brief's windows (`daily_brief_lambda` slices
    `strava_7d` from today-7; `brief_domain_inputs.gather` reads Hevy from today-14)."""
    d = FIRST
    while d <= LAST:
        today = d + timedelta(days=1)
        strava_7d = [r for r in wire["strava"] if (today - timedelta(days=7)).isoformat() <= r["date"] <= d.isoformat()]
        hevy = [r for r in wire["hevy"] if (today - timedelta(days=bdi.HEVY_WINDOW_DAYS)).isoformat() <= r["date"] <= d.isoformat()]
        yield d.isoformat(), bdi.training_block({"date": d.isoformat(), "hevy_recent": hevy, "strava_7d": strava_7d})
        d += timedelta(days=1)


def test_the_fixture_holds_the_specimen_the_old_rule_listed_as_extra_cardio(wire):
    """Before the fix: the old rule (drop device Hevy, keep everything else) lists the watch's gym
    block on every gym day 10-26 → 11-08 — 10 of 10 on the stored wire (the issue counted 9 of 10)."""
    gym = _gym_days(wire)
    assert len(gym) == 10
    old_rule = {
        (a["start_date_local"][:10], a["sport_type"])
        for r in wire["strava"]
        for a in r["activities"]
        if str(a.get("device_name") or "").strip().lower() != "hevy"
    }
    assert len(_watch_gym_blocks(wire) & old_rule) == 10


def test_each_gym_cardio_block_is_shown_once_beside_its_hevy_session(wire):
    blocks = _watch_gym_blocks(wire)
    attached = set()
    for subject_day, built in _replay(wire):
        listed = [(a["date"], a["type"]) for a in built["cardio_activities_7d"] if "in_strength_session" not in a]
        assert not set(listed) & blocks, f"{subject_day}: a gym block listed as extra cardio: {sorted(set(listed) & blocks)}"
        seen = []
        for s in built["strength_sessions_14d"]:
            for b in s.get("wearable_blocks", []):
                assert b["date"] == s["date"], f"{subject_day}: a block rides on the wrong session"
                seen.append((b["date"], b["type"]))
        seen += [(a["date"], a["type"]) for a in built["cardio_activities_7d"] if "in_strength_session" in a]
        assert len(seen) == len(set(seen)), f"{subject_day}: a block shown twice: {seen}"
        attached |= {k for k in seen if k in blocks}
        for s in built["strength_sessions_14d"]:
            assert len(s.get("wearable_blocks", [])) <= 1, f"{subject_day}: {s['date']} holds one cardio block"
    assert attached == blocks, f"never shown beside a session: {sorted(blocks - attached)}"


def test_a_block_whose_session_is_past_the_shown_sessions_stays_one_labelled_entry(wire):
    """11-03: six gym days in the 7-day window, five sessions shown — 10-28's treadmill walk is
    kept once, labelled with its session's date, so it is never read as cardio outside the lifts."""
    built = dict(_replay(wire))["2026-11-03"]
    assert [s["date"] for s in built["strength_sessions_14d"]] == ["2026-11-03", "2026-11-02", "2026-11-01", "2026-10-30", "2026-10-29"]
    labelled = [a for a in built["cardio_activities_7d"] if "in_strength_session" in a]
    assert [(a["date"], a["type"], a["in_strength_session"]) for a in labelled] == [("2026-10-28", "Walk", "2026-10-28")]


def test_outdoor_walks_stay_cardio_and_no_hevy_push_is_listed(wire):
    listed = set()
    for _, built in _replay(wire):
        listed |= {(a["date"], a["type"]) for a in built["cardio_activities_7d"] if "in_strength_session" not in a}
        assert all(a["type"] != "WeightTraining" for a in built["cardio_activities_7d"])
    for outdoor in (("2026-10-27", "Walk"), ("2026-10-31", "Walk"), ("2026-11-04", "Walk"), ("2026-11-07", "Walk")):
        assert outdoor in listed, f"an outdoor walk with no Hevy session lost from the cardio list: {outdoor}"


def test_the_flatten_reads_through_the_strava_read_seam(wire, monkeypatch):
    calls = []
    real = bdi.strava_read_seam

    def spy(source, rows, *a, **k):
        calls.append(source)
        return real(source, rows, *a, **k)

    monkeypatch.setattr(bdi, "strava_read_seam", spy)
    bdi._strava_activities(wire["strava"], wire["hevy"])
    assert calls == ["strava"]


def test_the_seam_folds_a_same_sport_wearable_copy_before_the_list():
    """One rule: two devices' copies of one walk (the seam's pair rule) list once."""
    acts = [
        {
            "strava_id": "1",
            "start_date": "2026-11-04T23:15:06Z",
            "start_date_local": "2026-11-04T16:15:06Z",
            "sport_type": "Walk",
            "device_name": WATCH,
            "moving_time_seconds": Decimal(6561),
            "elapsed_time_seconds": Decimal(6590),
            "distance_meters": Decimal("8775.8"),
        },
        {
            "strava_id": "2",
            "start_date": "2026-11-04T23:16:00Z",
            "start_date_local": "2026-11-04T16:16:00Z",
            "sport_type": "Walk",
            "device_name": "WHOOP",
            "moving_time_seconds": Decimal(6400),
            "elapsed_time_seconds": Decimal(6400),
            "distance_meters": Decimal(0),
        },
    ]
    out, blocks = bdi._strava_activities([{"sk": "DATE#2026-11-04", "date": "2026-11-04", "activities": acts}], [])
    assert [(a["date"], a["type"], a["distance_miles"]) for a in out] == [("2026-11-04", "Walk", 5.45)] and blocks == {}
