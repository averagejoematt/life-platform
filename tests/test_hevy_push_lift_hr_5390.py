"""tests/test_hevy_push_lift_hr_5390.py — Hevy's own Strava push is the lift's heart-rate member (#5390).

Since #5369 the resolver dropped Hevy's Strava push (device `Hevy`) as an echo of the Hevy session in hand.
From 2026-10-18 every push carries its own heart rate (Hevy's watch app — the recorder the owner's
2026-10-26 protocol names for the lift), and it is the one record whose heart rate spans the whole lift:
the Hevy-origin HealthKit workout and WHOOP's pieces cover parts of it. The rule decided here
(`training.workout_identity`, module docstring "THE LIFT'S HEART-RATE MEMBER"):

  * a push that carries its own heart rate, over a Hevy session that holds a lift, is KEPT as that lift's
    heart-rate member — source `strava/hevy`, placed in the lift's identity by id;
  * it adds no part, no minute and no session anywhere (the identity's duration stays Hevy's), and its
    zone time is claimed once against the ride and the mobility block inside its span;
  * a push with no heart rate of its own, a push over a session holding no lift, and a push whose sport
    is not a lift's are still dropped as echoes.

THE FIXTURE is the 2026-10-25 wire's STRUCTURE (the #5369 shared module, synthetic numbers — no real
time, heart rate or zone): one Hevy session holding a lift, a Cycling block and a Stretching block; Hevy's
push + WHOOP's two lift pieces + WHOOP's ride in Strava (the pre-2026-10-26 wire), or Hevy's push + the
watch's ride (the post wire); the watch's ride, the Hevy-origin lift and the pliability session in
HealthKit; WHOOP's own workout rows.

Mutation controls: `test_mutation_control_dropping_the_push_is_the_under_read` (the #5369 rule reproduced
reads the lift's heart rate as the partial HealthKit workout's leftover), and
`test_mutation_control_keying_the_push_as_plain_strava_splits_the_lift` (why the push is its own source).
"""

from __future__ import annotations

import copy
import os
import sys

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (_REPO, os.path.join(_REPO, "lambdas"), os.path.join(_REPO, "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import test_gym_visit_one_source_5369 as gym  # noqa: E402 — THE shared fixture (the 2026-10-25 wire's structure)
from training import session_count, workout_identity as wi, zone2_minutes as z2m  # noqa: E402

DAY = gym.DAY
LIFT = "hv-synth-5369#strength"
PUSH = "90000001"
WATCH_RIDE = gym._act("90000010", "Ride", "Apple Watch Ultra", "18:00:00", 3600, (1800, 1800, 0, 0, 0), avg_hr=115.0)
WIRES = {
    "pre": gym.ALL_STRAVA,  # Hevy's push + WHOOP's two lift pieces + WHOOP's ride
    "post": (gym.STRAVA_HEVY_PUSH, WATCH_RIDE),  # from 2026-10-26: Hevy's push + the watch's own ride
}
APPLE = (gym.APPLE_CYCLING, gym.APPLE_LIFT, gym.APPLE_FLEX)


def _identities(strava, hevy=(gym.HEVY,), whoop=()):
    return wi.resolve_workout_identities(
        strava=[gym._strava_row(*strava)], hevy=list(hevy), apple=[gym._apple_row(*APPLE)], whoop=list(whoop)
    )


def _lift(identities):
    (lift,) = [i for i in identities if i["family"] == "strength"]
    return lift


def _hr_less(act):
    out = {k: v for k, v in act.items() if not k.startswith("zone")}
    out["average_heartrate"] = None
    return out


# ── the rule ─────────────────────────────────────────────────────────────────────────


def test_a_push_carrying_its_own_heart_rate_is_the_lifts_heart_rate_member_on_both_wires():
    for wire, strava in WIRES.items():
        for whoop in ((), gym.WHOOP_ROWS):
            lift = _lift(_identities(strava, whoop=whoop))
            assert lift["members"].get(wi.HEVY_PUSH_SOURCE) == [PUSH], (wire, lift["members"])
            assert lift["members"]["hevy"] == [LIFT]
            assert lift["seconds_source"] == "hevy" and lift["seconds"] == (160 - 60 - 18) * 60.0, "the lift's minutes stay Hevy's"


def test_the_kept_push_is_counted_once_identities_and_minutes_unchanged():
    """The member adds no identity and no minute: the totals equal the #5369 rule's (push dropped)."""
    for wire, strava in WIRES.items():
        kept = wi.identity_totals(_identities(strava))
        dropped = wi.identity_totals(_identities(tuple(_hr_less(a) if a["strava_id"] == PUSH else a for a in strava)))
        assert (kept["sessions"], kept["minutes"], kept["by_family"]) == (
            dropped["sessions"],
            dropped["minutes"],
            dropped["by_family"],
        ), wire
        assert kept["sessions"] == 3 and kept["minutes"] == 160.0, wire


def test_the_session_count_is_one_visit_and_the_push_is_no_parts_activity():
    """#5387's count: still one visit of 160 minutes in three parts; the member is not a part's activity."""
    for wire, strava in WIRES.items():
        (visit,) = session_count.visits(strava=[gym._strava_row(*strava)], hevy=[copy.deepcopy(gym.HEVY)])
        assert visit["minutes"] == 160.0 and len(visit["parts"]) == 3, wire
        assert PUSH not in [a.get("strava_id") for a in session_count.activities([visit])], wire
        assert sorted(p["sport"] for p in visit["parts"]) == ["Mobility", "Ride", "WeightTraining"], wire


def test_zone2_reads_the_lifts_heart_rate_from_the_push_and_claims_time_once():
    for wire, strava in WIRES.items():
        sessions = z2m.counted_sessions([gym._strava_row(*strava)], [], [gym._apple_row(*APPLE)], hevy_rows=[gym.HEVY])
        fams = {s["family"]: s for s in sessions}
        assert sorted(fams) == ["cycling", "mobility", "strength"], wire
        assert fams["strength"]["used_ids"] == [f"{wi.HEVY_PUSH_SOURCE}:{PUSH}"], wire
        assert fams["strength"]["duration_minutes"] == 82.0 and sum(s["duration_minutes"] for s in sessions) == 160.0, wire
        # the push spans the ride and 18 minutes of the pliability session: those keep their own minutes
        assert fams["cycling"]["measured_minutes"] == 60.0 and fams["mobility"]["measured_minutes"] == 20.0, wire
        assert fams["strength"]["measured_minutes"] == pytest.approx(9000 * (9600 - 3600 - 1080) / 9600 / 60.0, abs=0.01), wire
        assert sum(s["measured_minutes"] for s in sessions) <= 162.0, wire  # the recordings' union: never twice


def test_whoops_own_lift_pieces_do_not_outrank_a_push_that_measured_the_whole_lift():
    sessions = z2m.counted_sessions([gym._strava_row(*WIRES["pre"])], gym.WHOOP_ROWS, [gym._apple_row(*APPLE)], hevy_rows=[gym.HEVY])
    lift = {s["family"]: s for s in sessions}["strength"]
    assert {"whoop:wh-lift-a", "whoop:wh-lift-b", f"{wi.HEVY_PUSH_SOURCE}:{PUSH}"} <= set(lift["ids"])
    assert lift["source"] == "strava", "WHOOP measured well under CONTAINMENT_SHARE of what the push measured"


# ── the pushes still dropped, each with its reason ──────────────────────────────────────


def test_a_push_with_no_heart_rate_of_its_own_is_still_an_echo():
    """The 10-11 → 10-16 wire: nothing to lose — the Hevy session is the record."""
    kept = wi.strava_without_echoes([gym._strava_row(_hr_less(gym.STRAVA_HEVY_PUSH), WATCH_RIDE)], [gym.HEVY])
    assert [a["strava_id"] for a in kept[0]["activities"]] == ["90000010"]
    assert not wi.carries_own_hr(_hr_less(gym.STRAVA_HEVY_PUSH))
    assert wi.carries_own_hr(gym.STRAVA_HEVY_PUSH)


def test_a_grafted_push_keeps_the_5369_rule_plain_strava():
    grafted = {**gym.STRAVA_HEVY_PUSH, "hr_from_strava_id": "90000002"}
    assert not wi.carries_own_hr(grafted)
    kept = wi.strava_without_echoes([gym._strava_row(grafted)], [gym.HEVY])
    (act,) = kept[0]["activities"]
    assert wi.LIFT_HR_OF not in act and wi.strava_identity_source(act) == "strava"


def test_a_push_over_a_session_holding_no_lift_is_still_an_echo():
    """A cardio/mobility-only session: those blocks' heart rate is the watch's / the pliability app's."""
    blocks_only = {**copy.deepcopy(gym.HEVY), "exercises": copy.deepcopy(gym.HEVY["exercises"][2:])}
    kept = wi.strava_without_echoes([gym._strava_row(*WIRES["post"])], [blocks_only])
    assert [a["strava_id"] for a in kept[0]["activities"]] == ["90000010"]


def test_a_push_whose_sport_is_not_a_lifts_is_still_an_echo():
    ride_push = {**gym.STRAVA_HEVY_PUSH, "sport_type": "Ride", "type": "Ride"}
    assert wi.lift_hr_member_of(ride_push, wi._hevy_lifts([gym.HEVY])) is None
    kept = wi.strava_without_echoes([gym._strava_row(ride_push)], [gym.HEVY])
    assert kept[0]["activities"] == []


def test_without_the_hevy_rows_nothing_is_stamped():
    rows = wi.strava_without_echoes([gym._strava_row(*WIRES["post"])], [])
    assert all(wi.LIFT_HR_OF not in a for a in rows[0]["activities"])


def test_the_stamp_is_idempotent_and_never_mutates_the_callers_rows():
    row = gym._strava_row(*WIRES["pre"])
    snapshot = copy.deepcopy(row)
    once = wi.strava_without_echoes([row], [gym.HEVY])
    twice = wi.strava_without_echoes(once, [gym.HEVY])
    assert once == twice and row == snapshot


# ── mutation controls ───────────────────────────────────────────────────────────────────


def test_mutation_control_dropping_the_push_is_the_under_read(monkeypatch):
    """The #5369 rule reproduced: the lift's heart rate falls to the Hevy-origin HealthKit workout's
    21 minutes, 19 of them already the pliability session's — the under-read the issue names."""

    def lift_measured():
        sessions = z2m.counted_sessions([gym._strava_row(*WIRES["post"])], [], [gym._apple_row(*APPLE)], hevy_rows=[gym.HEVY])
        return {s["family"]: s for s in sessions}["strength"]["measured_minutes"]

    assert lift_measured() > 70.0
    monkeypatch.setattr(wi, "lift_hr_member_of", lambda activity, lifts: None)
    assert lift_measured() == pytest.approx(2.0, abs=0.01)


def test_mutation_control_keying_the_push_as_plain_strava_splits_the_lift(monkeypatch):
    """A WHOOP lift piece the seam cannot fold (another sport label) joins the lift beside the push only
    because the push is its own source; keyed as plain `strava` it would be the same source overlapping
    the piece, and the piece would stand as a second lift."""
    piece = gym._act("90000020", "Workout", "WHOOP", "17:00:00", 1200, (1200, 0, 0, 0, 0), avg_hr=90.0)
    strava = (gym.STRAVA_HEVY_PUSH, piece, WATCH_RIDE)

    def lifts():
        return [i for i in _identities(strava) if i["family"] == "strength"]

    assert len(lifts()) == 1 and {PUSH} == set(lifts()[0]["members"][wi.HEVY_PUSH_SOURCE])
    monkeypatch.setattr(wi, "strava_identity_source", lambda activity: "strava")
    assert len(lifts()) == 2
