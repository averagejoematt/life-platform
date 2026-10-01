"""tests/test_walking_volume_3930.py — the walking read counts everything he actually walked (#3930).

WHAT WENT WRONG

`plan_next_session` computed the walking floor from Strava alone. For 13–19 Sep 2026 that
read returned 5.09 hr/wk against the owner's 8.5 hr/wk floor and printed the walking gap as
"the largest gap on the board" — FIRST in the constraint block, by design, so the wrongest
number in the block was also the loudest one. It was wrong because Matthew logs treadmill
and cycling blocks INSIDE his Hevy sessions, and those carry 8.33 hr of measured duration in
the same window. Nothing in the read was broken; the read was one-sourced.

THE FIXTURES ARE THE WIRE

`tests/fixtures/walking_volume_3930/*.json` are a field-projected copy of the LIVE DynamoDB
records for that exact window (`USER#matthew#SOURCE#hevy` and `#strava`, read 2026-09-19),
not a shape written from a comment. They carry the noise that matters: the barbell sets whose
`duration_sec` is null, the `Stretching` block that is duration-bearing but not walking, and
the mirrored `WeightTraining`/`Workout` activities Strava receives when a Hevy session
finishes — the exact rows a union has to decline before it can be trusted.

EACH TEST NAMES THE MUTATION THAT REDS IT.
"""

from __future__ import annotations

import json
import os
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import pytest

# mcp.config reads these at import time; the MCP Lambda has them, a unit test must supply them.
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from coach import critics  # noqa: E402
from training import owner_redlines, plan_engine, walking_volume as wv  # noqa: E402

from mcp import tools_plan as tp  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures" / "walking_volume_3930"
WINDOW_START = "2026-09-13"
WINDOW_END = "2026-09-19"

# The floor the week is graded against, read from the redline rather than retyped.
FLOOR_HR_WK = owner_redlines.REDLINES["walking_floor_hr_wk"]["value"]

# The issue's own acceptance number for the 13–19 Sep replay.
ACCEPTANCE_HR = 8.79


def _live(name: str) -> list[dict]:
    return json.loads((FIXTURES / f"{name}_2026-09-13_19.json").read_text())


@pytest.fixture
def live_week():
    return {"strava_items": _live("strava"), "hevy_workouts": _live("hevy")}


def _build(**kw):
    return wv.build(window_start=WINDOW_START, window_end=WINDOW_END, **kw)


# ── acceptance box 4: a planted Hevy treadmill block counts ──────────────────────────
def test_a_planted_hevy_treadmill_block_counts_toward_the_walking_total():
    """Mutation control: drop `("treadmill", "walking")` from `HEVY_COUNTED_NAMES` — the
    total falls to 0.0 and this reds on the first assertion."""
    workout = {
        "date": "2026-09-14",
        "title": "Foundation - Push - 3 - 8",
        "exercises": [
            {"name": "Bench Press (Barbell)", "sets": [{"reps": 8, "weight_kg": 60.0, "duration_sec": None, "distance_m": None}]},
            {"name": "Treadmill", "sets": [{"reps": None, "weight_kg": None, "duration_sec": 3600, "distance_m": 4812}]},
        ],
    }
    layer = _build(strava_items=[], hevy_workouts=[workout])
    assert layer["total_hr"] == 1.0
    assert layer["by_source"]["hevy"]["hours"] == 1.0
    assert layer["by_source"]["hevy"]["sessions"] == 1
    assert layer["by_modality"] == {"walking": 1.0}
    # the barbell work is not silently swallowed and not counted: it has no duration at all,
    # so it is neither a counted block nor a "not counted" one worth naming
    assert layer["by_source"]["hevy"]["not_counted"] == []


def test_a_hevy_cycling_block_counts_and_lands_under_its_own_modality():
    """Mutation control: drop `("cycling", "cycling")` — `by_modality` loses its cycling row."""
    workout = {"date": "2026-09-15", "exercises": [{"name": "Cycling", "sets": [{"duration_sec": 2700, "distance_m": 13921}]}]}
    layer = _build(strava_items=[], hevy_workouts=[workout])
    assert layer["by_modality"] == {"cycling": 0.75}
    assert layer["total_hr"] == 0.75


def test_a_duration_bearing_block_that_is_not_walking_or_cycling_is_named_not_swallowed():
    """Stretching carries 15 real minutes every session and is NOT walking volume. It must be
    declined AND listed, because a silent decline is how the next reader re-litigates it.
    Mutation control: append `("stretching", "walking")` to `HEVY_COUNTED_NAMES` — the total
    moves to 0.25 and `not_counted` empties."""
    workout = {"date": "2026-09-15", "exercises": [{"name": "Stretching", "sets": [{"duration_sec": 900}]}]}
    layer = _build(strava_items=[], hevy_workouts=[workout])
    assert layer["total_hr"] == 0.0
    assert layer["by_source"]["hevy"]["not_counted"] == ["Stretching"]


# ── acceptance box 2: the 13–19 Sep week replays >= 8.79 hr and reads at_or_above_floor ──
def test_the_13_19_sep_week_replays_at_or_above_the_floor(live_week):
    """The issue's own replay, on the live records. Mutation control: pass
    `hevy_workouts=[]` — the total falls to the Strava-only 6.04 and the state flips to
    below_floor, which is the bug this test exists to keep out."""
    layer = _build(**live_week)
    assert layer["total_hr"] >= ACCEPTANCE_HR, layer["by_source"]
    assert layer["by_source"]["strava"]["hours"] == 6.04
    assert layer["by_source"]["hevy"]["hours"] == 8.33
    assert layer["total_hr"] == 14.38  # 6.04 + 8.33, and 0.01 of rounding across 16 blocks
    assert layer["total_is_floor"] is False

    block = plan_engine.constraint_block(date=WINDOW_END, walk_hr_wk_now=layer["total_hr"])
    assert block["walking"]["state"] == "at_or_above_floor"
    assert block["walking"]["gap_hr_wk"] == 0


def test_the_strava_only_read_is_the_regression_this_week_pins(live_week):
    """The counterfactual, stated as a test so the two numbers sit side by side: the read that
    shipped reported this week BELOW the floor. Mutation control: none needed — this is the
    old behaviour, asserted as wrong."""
    strava_only = _build(strava_items=live_week["strava_items"], hevy_workouts=[])
    assert strava_only["by_source"]["hevy"]["status"] == "no_records"
    block = plan_engine.constraint_block(date=WINDOW_END, walk_hr_wk_now=strava_only["total_hr"])
    assert strava_only["total_hr"] < FLOOR_HR_WK and block["walking"]["state"] == "below_floor"


def test_a_mirrored_hevy_session_arriving_in_strava_is_not_counted_twice(live_week):
    """Strava receives a finished Hevy session as ONE `WeightTraining`/`Workout` activity
    carrying the session title — 9,535 s on 13 Sep, the same seconds the Hevy record spans.
    Counting it would double the week. Mutation control: add `"weighttraining": "walking"` to
    `STRAVA_COUNTED_TYPES` — the Strava hours jump past the whole-week total and this reds."""
    mirrored = [
        a for item in live_week["strava_items"] for a in item["activities"] if (a.get("type") or "") in ("WeightTraining", "Workout")
    ]
    assert mirrored, "the fixture must contain the mirrored sessions or this proves nothing"
    layer = _build(**live_week)
    assert sorted(layer["by_source"]["strava"]["not_counted"]) == ["WeightTraining", "Workout"]
    mirrored_hours = round(sum(a["moving_time_seconds"] for a in mirrored) / 3600.0, 2)
    assert mirrored_hours > 0
    assert layer["by_source"]["strava"]["hours"] + mirrored_hours != layer["by_source"]["strava"]["hours"]
    assert "double-count" in layer["overlap_rule"]


# ── acceptance box 3: steps are excluded, with the reason in the output ──────────────
def test_apple_health_steps_are_excluded_from_the_proxy_with_the_reason_in_the_output(live_week):
    """Mutation control: empty `STEPS_EXCLUSION` — the reason disappears from the payload and
    this reds. The exclusion has to travel IN the output; one that lives only in a docstring
    is invisible to every consumer of the layer."""
    layer = _build(**live_week)
    (excl,) = layer["excluded_proxies"]
    assert excl["source"] == "apple_health" and excl["field"] == "steps"
    assert excl["used_as_proxy"] is False
    assert "NOT a walking proxy" in excl["reason"] and "1,869" in excl["reason"]
    # and no step count ever becomes a measured field of this layer
    assert "steps" not in layer


# ── acceptance box 5: a steps estimate is DERIVED, labelled, and never merged ────────
def test_a_steps_estimate_is_labelled_derived_and_never_merges_into_the_measured_field():
    """Mutation control: rename `derived_steps_estimate` to `steps` in `build()` — the last
    assertion reds. The estimate is duration x an ASSUMED cadence; its value may be useful,
    its provenance may never be lost."""
    est = wv.derived_steps_estimate(5.0)
    assert est["label"] == "DERIVED"
    assert est["measured"] is False
    assert est["never_merge_into"] == "steps"
    assert est["assumed_cadence_spm"] == wv.ASSUMED_CADENCE_SPM
    assert est["value"] == 5 * 60 * wv.ASSUMED_CADENCE_SPM
    assert "assumed cadence" in est["method"]
    assert wv.derived_steps_estimate(None) is None


def test_the_derived_estimate_is_built_from_walking_only_never_from_cycling_hours(live_week):
    """An hour on a bike produces no steps. Mutation control: feed `total_hr` instead of the
    walking modality into `derived_steps_estimate` — the value rises by the cycling hours."""
    layer = _build(**live_week)
    assert layer["by_modality"]["cycling"] > 0
    assert layer["derived_steps_estimate"]["value"] == int(round(layer["by_modality"]["walking"] * 60 * wv.ASSUMED_CADENCE_SPM))
    assert layer["derived_steps_estimate"]["value"] < int(round(layer["total_hr"] * 60 * wv.ASSUMED_CADENCE_SPM))


# ── honesty: a source that could not be read is never zero hours ─────────────────────
def test_an_unreadable_source_makes_the_total_a_floor_and_says_so(live_week):
    """Mutation control: change `strava_items=None` handling to `or []` — the layer reports a
    confident 8.33 hr total with `total_is_floor` False, which is the read that says "he
    walked 8.33 hours" when what happened is "one partition did not answer"."""
    layer = _build(strava_items=None, hevy_workouts=live_week["hevy_workouts"])
    assert layer["by_source"]["strava"]["status"] == "unreadable"
    assert layer["by_source"]["strava"]["hours"] is None
    assert layer["total_hr"] == 8.33
    assert layer["total_is_floor"] is True
    assert any("floor, not the week's volume" in h for h in layer["honesty"])


def test_both_sources_silent_is_unknown_not_zero():
    """Mutation control: return `0.0` instead of None for `total_hr` when nothing contributed —
    the engine then reads a confident `below_floor, 0.0 hr/wk` on a window it could not see."""
    layer = _build(strava_items=None, hevy_workouts=None)
    assert layer["total_hr"] is None
    assert layer["total_is_floor"] is False  # a floor of nothing is not a floor, it is unknown
    assert any("UNKNOWN" in h for h in layer["honesty"])
    block = plan_engine.constraint_block(date=WINDOW_END, walk_hr_wk_now=layer["total_hr"])
    assert block["walking"]["state"] == "unknown"


# ── the wiring: the breakdown reaches the constraint block the coach reads ────────────
def _stage1_patches(rows_by_source):
    def _query(source, start, end, **kw):
        return rows_by_source.get(source, [])

    return [
        patch("mcp.core.query_source_range", side_effect=_query),
        patch("mcp.tools_benchmark.tool_get_benchmark", return_value={"applicable": False, "reason": "offline"}),
        patch("mcp.tools_health.tool_get_readiness_score", return_value={"readiness_score": 80.1}),
        patch("mcp.tools_training.tool_get_acwr_status", return_value={"zone": "safe"}),
        patch("mcp.tools_strength.tool_get_muscle_volume", return_value={}),
        patch("mcp.tools_nutrition.tool_get_nutrition", return_value={}),
        patch("training.training_notes.training_notes_health", side_effect=RuntimeError("offline")),
    ]


def test_the_union_and_its_breakdown_reach_the_constraint_block(live_week):
    """End to end through the tool, with BOTH partitions stubbed at `mcp.core`. Mutation
    control: drop the `_merge_walking_volume(block, walk_layer)` call in `tool_plan_next_session`
    — the total still moves but `sources` vanishes and the coach is back to a bare number."""
    rows = {"strava": live_week["strava_items"], "hevy": live_week["hevy_workouts"]}
    with ExitStack() as st:
        for cm in _stage1_patches(rows):
            st.enter_context(cm)
        # #4068: the session's week is the 7 COMPLETED days BEFORE it — a plan for 09-20 reads 13..19
        out = tp.tool_plan_next_session({"target_date": "2026-09-20"})
    walking = out["constraint_block"]["walking"]
    assert walking["state"] == "at_or_above_floor"
    assert walking["now_hr_wk"] >= ACCEPTANCE_HR
    assert walking["sources"]["strava"]["hours"] == 6.04
    assert walking["sources"]["hevy"]["hours"] == 8.33
    assert walking["window"] == {"start": WINDOW_START, "end": WINDOW_END, "days": 7}
    assert walking["volume_layer"] == wv.WALKING_VOLUME_VERSION
    assert walking["excluded_proxies"][0]["field"] == "steps"
    assert walking["derived_steps_estimate"]["label"] == "DERIVED"


def test_a_raising_partition_read_degrades_to_unknown_and_never_to_zero():
    """Mutation control: drop the `_safe` wrapper around either `query_source_range` call —
    `tool_plan_next_session` raises instead of reporting the window unread."""
    with ExitStack() as st:
        for cm in _stage1_patches({}):
            st.enter_context(cm)
        st.enter_context(patch("mcp.core.query_source_range", side_effect=RuntimeError("DDB down")))
        out = tp.tool_plan_next_session({"target_date": WINDOW_END})
    walking = out["constraint_block"]["walking"]
    # #4072: both sources raised, so the read FAILED — reported as such, never as unknown or zero.
    assert walking["state"] == "read_failed"
    assert "gap_hr_wk" not in walking
    assert walking["sources"]["strava"]["status"] == "unreadable"


# ── the critic that argued the wrong number now argues the union ─────────────────────
def _advocate(walking):
    return critics.build_rate_advocate_packet(
        {"total_sets": 20},
        tripwires=[],
        walking=walking,
        rate_target={"low_lb_wk": 1.0, "high_lb_wk": 2.0, "provenance": "owner"},
        current_rate_lb_wk=1.5,
        lifting_sessions_7d=4,
    )


def test_the_rate_advocate_carries_the_per_source_split_and_stops_calling_a_met_floor_a_gap(live_week):
    """The advocate's loudest sentence — "the largest lever is not in this routine" — was built
    on the Strava-only number. Mutation control: delete the `at_or_above_floor` branch in
    `build_rate_advocate_packet` — the met floor becomes unsayable again and this reds."""
    layer = _build(**live_week)
    block = plan_engine.constraint_block(date=WINDOW_END, walk_hr_wk_now=layer["total_hr"])
    tp._merge_walking_volume(block, layer)
    packet = _advocate(block["walking"])

    assert packet["numbers"]["walking_hr_wk_strava"] == 6.04
    assert packet["numbers"]["walking_hr_wk_hevy"] == 8.33
    sentences = [f["reason"] for f in packet["flags"]]
    assert any("AT OR ABOVE" in s for s in sentences)
    assert not any("largest lever" in s for s in sentences)
    assert any("strava 6.04 + hevy 8.33" in s for s in sentences)


def test_a_genuinely_short_week_still_reads_below_floor_with_the_split_named():
    """The fix must not make the flag unreachable — a week that really is short still flags.
    Mutation control: make `build()` count `Stretching` too; the short week clears the floor
    and this reds."""
    layer = _build(
        strava_items=[{"date": WINDOW_END, "activities": [{"type": "Walk", "moving_time_seconds": 3600}]}],
        hevy_workouts=[{"date": WINDOW_END, "exercises": [{"name": "Treadmill", "sets": [{"duration_sec": 1800}]}]}],
    )
    block = plan_engine.constraint_block(date=WINDOW_END, walk_hr_wk_now=layer["total_hr"])
    tp._merge_walking_volume(block, layer)
    packet = _advocate(block["walking"])
    assert block["walking"]["state"] == "below_floor"
    assert any("largest lever" in f["reason"] and "strava 1.0 + hevy 0.5" in f["reason"] for f in packet["flags"])


def test_an_unreadable_source_reaches_the_critic_as_unknown_never_as_zero_hours():
    """Mutation control: default the missing source's hours to 0.0 in the packet — the critic
    argues a confident number built on a partition that did not answer."""
    layer = _build(strava_items=None, hevy_workouts=[{"date": WINDOW_END, "exercises": []}])
    block = plan_engine.constraint_block(date=WINDOW_END, walk_hr_wk_now=layer["total_hr"])
    tp._merge_walking_volume(block, layer)
    packet = _advocate(block["walking"])
    assert packet["numbers"]["walking_hr_wk_strava"] is None
    assert "walking_hr_wk_strava" in packet["unknown"]
    assert any("strava unreadable" in f["reason"] and "a FLOOR" in f["reason"] for f in packet["flags"])


# ── #4387: what his legs did in the last three days, per activity ────────────────────
# `tests/fixtures/recent_aerobic_4387/*.json` are field-projected copies of the LIVE rows
# (`USER#matthew#SOURCE#strava` / `#hevy`, DATE#2026-09-14..27, read 2026-09-27): only the
# fields the code reads — no polylines, no names, no notes. The weekend walks are the Garmin
# 102- and 165-min walks of 09-26 and 09-27; the 09-25 treadmill sits inside its Hevy session
# with a WHOOP walk recorded over the same minutes (#4068).
RA_FIX = Path(__file__).parent / "fixtures" / "recent_aerobic_4387"
RA_TARGET, RA_TODAY = "2026-09-28", "2026-09-27"  # planned the night of 09-27 for Mon 09-28


def _ra_rows(name: str, drop_weekend_walks: bool = False) -> list[dict]:
    rows = json.loads((RA_FIX / f"{name}_2026-09-14_27.json").read_text())
    if drop_weekend_walks:
        rows = [
            {
                **r,
                "activities": [
                    a for a in r.get("activities") or [] if a.get("device_name", "").split()[0] != "Garmin" or r["date"] < "2026-09-26"
                ],
            }
            for r in rows
        ]
    return rows


def _ra_block(drop_weekend_walks: bool = False) -> dict:
    """The block exactly as stage 1 builds it: through `shared_quantities.recent_aerobic_layer`, with
    the fixture as the partition reader (the wire), so the window arithmetic is the shipped one."""
    from mcp import shared_quantities

    data = {"strava": _ra_rows("strava", drop_weekend_walks), "hevy": _ra_rows("hevy")}

    def read(source: str, start: str, end: str) -> list[dict]:
        return [r for r in data[source] if start <= r["date"] <= end]

    return shared_quantities.recent_aerobic_layer(RA_TARGET, today=RA_TODAY, read=read)


def _lower_volume_draft(trap_bar_sets: int = 2):
    """The 2026-09-28 lower-volume draft the coach built (routine 30e24cca, v2): trap bar, squat, leg curl,
    calf raise, machine crunch — and the 60-min treadmill copied from the last session."""
    from training.routine_ir import ExerciseBlock, RoutineSpec, Set

    def lift(key, n, kg):
        return ExerciseBlock(movement_key=key, rationale_tag="custom", sets=[Set(weight_kg=kg, reps=8) for _ in range(n)])

    return RoutineSpec(
        routine_id="r4387",
        target_date=RA_TARGET,
        archetype="lower",
        exercises=[
            lift("deadlift_trap_bar", trap_bar_sets, 55.5),
            lift("squat_barbell", 3, 61.235),
            lift("leg_curl", 2, 34.02),
            lift("calf_raise_machine", 2, 131.54),
            ExerciseBlock(movement_key="machine_crunch", rationale_tag="custom", sets=[Set(reps=12), Set(reps=12)]),
            ExerciseBlock(movement_key="treadmill", rationale_tag="custom", sets=[Set(duration_seconds=3600)]),
        ],
    )


def _joints(draft: dict, block: dict | None, days_since: dict | None = None) -> dict:
    return critics.build_joints_packet(
        draft,
        pain_by_idx={},
        days_since_by_idx=days_since or {e["idx"]: 3 for e in draft["exercises"]},
        loaded_lifting_streak=2,
        pain_layer_status="ok",
        recent_aerobic=block,
    )


def test_recent_aerobic_shows_the_weekend_walks_flagged_and_joints_swaps_the_treadmill_to_cycling():
    """The incident, replayed on the wire rows: the plan for 09-28 sees Saturday's and Sunday's walks,
    both over 75 min — and, since OD2 (#4503, cap 120 avg, 105 the target), UNDER the HR cap at ~116 bpm —
    and the joints critic CHANGEs the lower draft's treadmill to cycling — same 60 min, HR avg ≤ 120. Mutation controls: drop `aerobic_flags` from
    `build_joints_packet`, or make `recent_aerobic.window` end at target − 2 — this reds."""
    block = _ra_block()
    walks = [r for r in block["rows"] if r["modality"] == "walk"]
    assert [(r["date"], r["moving_min"], r["device"]) for r in walks] == [
        ("2026-09-26", 101.8, "Garmin epix (Gen2)"),
        ("2026-09-27", 164.8, "Garmin epix (Gen2)"),
    ]
    assert all(r["flags"] == {"over_75_min": True, "avg_hr_over_ceiling": False} for r in walks)
    assert [(r["avg_hr"], r["max_hr"]) for r in walks] == [(116.8, 171.0), (116.1, 176.0)]
    # the Hevy treadmill Strava cannot see is a row; the WHOOP walk over its minutes is not a second one (#4068)
    (tread,) = [r for r in block["rows"] if r["modality"] == "treadmill"]
    assert tread["date"] == "2026-09-25" and tread["source"] == "hevy" and tread["moving_min"] == 60.0 and "WHOOP" in tread["hr_source"]
    assert block["window"] == {"start": "2026-09-25", "end": "2026-09-27", "days": 3, "end_in_progress": True}
    assert block["totals"]["weight_bearing_hr_48h"] == 4.44 and block["totals"]["weight_bearing_hr_72h"] == 5.44
    assert block["totals"]["walks_over_75_min_48h"] == 2

    ir = _lower_volume_draft()
    draft = critics.draft_summary(ir)
    verdict = critics.deterministic_verdict(_joints(draft, block))
    assert verdict["verdict"] == "change" and verdict["field"] == "exercises[5].movement_key" and verdict["to"] == "cycling"
    assert "POPULATION-DERIVED" in verdict["reason"] and "HR avg ≤ 120 bpm (target 105)" in verdict["reason"]
    (rec,) = critics.apply_changes(ir, [{**verdict, "critic": "joints_tendons"}])
    assert rec["applied"] is True
    assert ir.exercises[5].movement_key == "cycling" and ir.exercises[5].sets[0].duration_seconds == 3600
    assert "HR avg ≤ 120 bpm (target 105)" in ir.exercises[5].notes
    # re-evaluated, the revised draft carries nothing left to swap
    assert critics.deterministic_verdict(_joints(critics.draft_summary(ir), block))["verdict"] == "approve"


def test_without_the_weekend_walks_the_treadmill_stands():
    """The same wire rows minus the two Garmin walks: 1.0 h weight-bearing in 48 h, no walk over 75 min —
    no change, and the treadmill stands. Mutation control: drop the `loaded` condition — this reds."""
    block = _ra_block(drop_weekend_walks=True)
    assert not [r for r in block["rows"] if r["modality"] == "walk"]
    assert block["totals"]["weight_bearing_hr_48h"] < 3.0 and block["totals"]["walks_over_75_min_48h"] == 0
    ir = _lower_volume_draft()
    verdict = critics.deterministic_verdict(_joints(critics.draft_summary(ir), block))
    assert verdict["verdict"] == "approve"
    critics.apply_changes(ir, [{**verdict, "critic": "joints_tendons"}])
    assert ir.exercises[5].movement_key == "treadmill"


def test_the_swap_rides_beside_a_first_change_and_never_displaces_it():
    """A critic returns ONE verdict. With a novel-again set cap on the trap bar (the packet's first change)
    the treadmill swap rides as an `additional_changes` entry, and both are applied. Mutation control:
    drop `additional_changes` from `deterministic_verdict` — the treadmill survives and this reds."""
    ir = _lower_volume_draft(trap_bar_sets=4)
    draft = critics.draft_summary(ir)
    verdict = critics.deterministic_verdict(
        _joints(draft, _ra_block(), days_since={e["idx"]: (60 if e["idx"] == 0 else 3) for e in draft["exercises"]})
    )
    assert verdict["field"] == "exercises[0].set_count"
    assert [a["field"] for a in verdict["additional_changes"]] == ["exercises[5].movement_key"]
    recs = critics.apply_changes(ir, [{**verdict, "critic": "joints_tendons"}])
    assert [r["applied"] for r in recs] == [True, True]
    assert len(ir.exercises[0].sets) == critics.NOVEL_AGAIN_MAX_WORKING_SETS and ir.exercises[5].movement_key == "cycling"


def test_an_unread_recent_block_changes_nothing_and_is_named_unknown():
    draft = critics.draft_summary(_lower_volume_draft())
    p = _joints(draft, None)
    assert "weight_bearing_hr_48h" in p["unknown"] and critics.deterministic_verdict(p)["verdict"] == "approve"


def test_the_swap_refuses_a_block_that_is_not_timed_cardio():
    ir = _lower_volume_draft()
    (rec,) = critics.apply_changes(
        ir, [{"critic": "joints_tendons", "verdict": "change", "field": "exercises[1].movement_key", "to": "cycling"}]
    )
    assert rec["applied"] is False and ir.exercises[1].movement_key == "squat_barbell"


def test_the_cardio_pick_is_derived_from_the_rows_never_from_the_last_session():
    from training import recent_aerobic

    heavy, fresh = _ra_block(), _ra_block(drop_weekend_walks=True)
    assert recent_aerobic.cardio_pick(heavy, "lower")["movement_key"] == "cycling"
    assert recent_aerobic.cardio_pick(fresh, "lower")["movement_key"] == "cycling"  # a lower session always
    assert recent_aerobic.cardio_pick(heavy, "upper")["movement_key"] == "cycling"  # a heavy walking weekend
    assert recent_aerobic.cardio_pick(fresh, "upper")["movement_key"] == "treadmill"  # the legs are fresh
    assert recent_aerobic.cardio_pick(None, "upper")["movement_key"] == "cycling"  # unread is never fresh
    # the redline numbers are read, not retyped
    assert f"none over {recent_aerobic.WALK_MAX_MIN} min" in owner_redlines.REDLINES["walking_floor_hr_wk"]["walks"]
    assert recent_aerobic.HR_CEILING_BPM == owner_redlines.REDLINES["walking_floor_hr_wk"]["hr_ceiling_bpm"]


def test_walking_collapse_and_overshoot_are_report_only_rows_on_the_block():
    """#4387: both evaluated, both report-only — a row, never a veto or a change. Mutation control:
    drop the `weekly_reports` loop in `_tripwire_states` — the rows vanish and this reds."""
    block = _ra_block()
    big = json.loads(json.dumps(block))
    big["totals"]["week_to_date"].update(hours=14.0, over_target=True, over_ramp=True)
    cb = plan_engine.constraint_block(date=RA_TARGET, recent_aerobic=big)
    rows = {t["id"]: t for t in cb["tripwires"]}
    assert rows["walking_overshoot"]["state"] == "tripped" and rows["walking_overshoot"]["report_only"] is True
    assert "above the 12 h target" in rows["walking_overshoot"]["detail"]  # #4503 OD2: 13 -> 12
    # #4503 OD7: the hours half is clear (-0.4 %), but the live week holds only 2 standalone walks (the
    # 09-26 and 09-27 Garmin walks) — every WHOOP walk sits inside a Hevy session — so the walks half trips it
    wc = rows["walking_collapse"]
    assert wc["state"] == "tripped" and wc["report_only"] is True and wc["observed"] == -0.4
    assert "2 standalone walk(s) ≥ 20 min outside a gym window" in wc["detail"] and "report under 3" in wc["detail"]
    assert wc["actuator"]["designation"] == "not_read" and wc["actuator"]["sends"] is False  # the engine never reads the config
    assert cb["recent_aerobic"]["rows"] == big["rows"] and cb["recent_aerobic"]["cardio_pick"]["movement_key"] in ("cycling", "treadmill")
    none = plan_engine.constraint_block(date=RA_TARGET)
    assert {t["id"]: t["state"] for t in none["tripwires"]}["walking_overshoot"] == "unknown"
    assert none["recent_aerobic"]["cardio_pick"]["movement_key"] == "cycling"


def test_standalone_walks_count_only_the_minutes_outside_every_gym_window():
    """#4503 OD7 on the live wire rows: 09-21..27 holds seven Strava walks, and five are WHOOP walks recorded
    INSIDE a Hevy session (the treadmill block seen by the wrist, or a walk inside a lifting session) — the
    vital sign counts 2. Mutation controls: pass no gym windows to `dedup_strava` — the in-session walks
    count and this reds; drop the min_minutes filter — the 09-16 14.5-min walk counts and the prior week
    reads 2. (Every live session here carries a cardio block, so cardio-only intervals are caught by the
    synthetic test below, not this one.)"""
    sw = _ra_block()["totals"]["standalone_walks"]
    t, p = sw["trailing_7d"], sw["prior_7d"]
    assert (sw["min_per_wk"], sw["min_minutes"]) == (3, 20)
    assert (t["start"], t["end"], t["count"], t["untimed"]) == ("2026-09-21", "2026-09-27", 2, 0)
    assert [(w["date"], w["minutes_outside_gym"]) for w in t["walks"]] == [("2026-09-26", 101.8), ("2026-09-27", 164.8)]
    assert (p["count"], [w["date"] for w in p["walks"]]) == (1, ["2026-09-14"])


def test_standalone_walk_rule_on_synthetic_sessions():
    """A walk straddling a session counts only its minutes outside it; an untimed walk is never standalone
    and makes a short count UNKNOWN, not tripped; three timed walks clear the half. The session carries NO
    cardio block: mutation control — use `walking_volume.hevy_cardio_intervals` (cardio sessions only) as
    the gym window — the in-session walks count and this reds."""
    from training import recent_aerobic

    def walk(day, hhmm, minutes, start=True):
        a = {"type": "Walk", "moving_time_seconds": minutes * 60, "elapsed_time_seconds": minutes * 60, "device_name": "Garmin"}
        if start:
            a["start_date"] = f"{day}T{hhmm}:00Z"
        return {"date": day, "activities": [a]}

    gym = [{"date": "2026-09-21", "start_time": "2026-09-21T10:00:00Z", "end_time": "2026-09-21T11:00:00Z", "exercises": []}]

    def count(item):
        return recent_aerobic.standalone_walks(recent_aerobic._strava_rows([item]), gym, "2026-09-21", "2026-09-27")["count"]

    assert count(walk("2026-09-21", "09:30", 40)) == 1  # 30 of its 40 min fall before the 10:00 session
    assert count(walk("2026-09-21", "09:50", 25)) == 0  # only 10 min outside it
    assert count(walk("2026-09-21", "10:10", 30)) == 0  # wholly inside the session

    def block(items):
        return recent_aerobic.build(target_date="2026-09-28", today="2026-09-28", strava_items=items, hevy_workouts=gym)

    two_and_untimed = block(
        [walk("2026-09-22", "15:00", 30), walk("2026-09-23", "15:00", 30), walk("2026-09-24", "15:00", 30, start=False)]
    )
    state, _, detail = recent_aerobic.weekly_reports(two_and_untimed, 30.0)["walking_collapse"]
    assert state == "unknown" and "1 untimed walk(s)" in detail
    three = block([walk(d, "15:00", 30) for d in ("2026-09-22", "2026-09-23", "2026-09-24")])
    assert three["totals"]["standalone_walks"]["trailing_7d"]["count"] == 3
    assert "3 standalone walk(s)" in recent_aerobic.weekly_reports(three, 30.0)["walking_collapse"][2]


def test_the_collapse_actuator_is_a_mark_read_only_on_a_tripped_row():
    """#4503 OD7: the named human is the actuator — a MARK that sends nothing. Stage 1 reads the private
    config's designation ONLY on a tripped row, and never carries the identity. Mutation controls: drop
    the `state != "tripped"` early return in `_attach_collapse_actuator` — the clear block reads the
    config and this reds; make `would_actuate` ignore the designation — the not-designated case reds."""
    from training import recent_aerobic

    calls = []

    def reader(answer):
        def _r():
            calls.append(answer)
            return answer

        return _r

    cb = plan_engine.constraint_block(date=RA_TARGET, recent_aerobic=_ra_block())
    tp._attach_collapse_actuator(cb, status_reader=reader({"designation": "designated", "armed": False}))
    act = {t["id"]: t for t in cb["tripwires"]}["walking_collapse"]["actuator"]
    assert act["designation"] == "designated" and act["would_actuate"] is True and act["sends"] is False
    assert (act["role"], act["config_key"], act["when"]) == ("named_human", "config/coaching/named_human.json", "same day")
    assert len(calls) == 1

    clear = json.loads(json.dumps(cb))
    row = {t["id"]: t for t in clear["tripwires"]}["walking_collapse"]
    row.update(state="clear", actuator=recent_aerobic.collapse_actuator("clear", None))
    tp._attach_collapse_actuator(clear, status_reader=reader({"designation": "designated", "armed": True}))
    assert len(calls) == 1 and row["actuator"]["designation"] == "not_read" and row["actuator"]["would_actuate"] is False

    assert (
        recent_aerobic.collapse_actuator("tripped", {"designation": "not_designated_or_invalid", "armed": None})["would_actuate"] is False
    )

    def boom():
        raise RuntimeError("AccessDenied")

    tp._attach_collapse_actuator(cb, status_reader=boom)
    act = {t["id"]: t for t in cb["tripwires"]}["walking_collapse"]["actuator"]
    assert act["designation"] == "unreadable" and act["would_actuate"] is False


def test_draft_custom_names_a_copied_treadmill_the_pick_would_not_draft():
    """The 09-28 treadmill came through `draft_custom` (the coach copied the last session's block). The
    draft now says so by name — a warning, never a rewrite; the swap is stage 2's. Mutation control:
    make `draft_cardio_warnings` return [] — this reds."""
    from mcp import plan_cardio_pick, shared_quantities

    ir = _lower_volume_draft()
    with patch.object(shared_quantities, "recent_aerobic_layer", return_value=_ra_block()):
        (w,) = plan_cardio_pick.draft_cardio_warnings(ir.exercises, "lower", RA_TARGET)
    assert w.startswith("cardio: treadmill drafted") and "cycling (recumbent)" in w
    with patch.object(shared_quantities, "recent_aerobic_layer", return_value=_ra_block(drop_weekend_walks=True)):
        assert plan_cardio_pick.draft_cardio_warnings(ir.exercises, "upper", RA_TARGET) == []  # fresh legs, upper day
    with patch.object(shared_quantities, "recent_aerobic_layer", side_effect=RuntimeError("boom")):
        (w,) = plan_cardio_pick.draft_cardio_warnings(ir.exercises, "lower", RA_TARGET)
    assert "could not be computed (RuntimeError)" in w


# ── #4410: every draft path reads the aerobic minutes; an unread week is unknown, never 0 ────
# The cron passed `z2_minutes_7d=0.0` and the chat / nightly pre-draft path passed the caller's
# value or 0, so `full_body_session` wrote "z2 7d=0 < floor 90 … walk more" into the note of a
# week the recent-aerobic block read at 9+ h. The fixture week (09-21..09-27, the wire above)
# reads 10.19 h of walking + cycling.
RA_MINUTES = 611.4  # 10.19 h × 60 — the trailing 7 days through target − 1 of the fixture block


def _fixture_read(source: str, start: str, end: str) -> list[dict]:
    data = {"strava": _ra_rows("strava"), "hevy": _ra_rows("hevy")}
    return [r for r in data[source] if start <= r["date"] <= end]


def _full_body_rationale(monkeypatch, z2: float | None) -> list[str]:
    """The ideal §3 session for 09-28 (two lifts done → week 1's lower-volume), as the generator
    builds it — the same stubs as `test_a_full_body_week_generates_through_the_module_grid`."""
    from training import exercise_history, routine_generator as rg

    monkeypatch.setattr(rg, "CONFIG_DIR", str(Path(__file__).resolve().parents[1] / "config"))
    monkeypatch.setattr(exercise_history, "load_history_indexes", lambda **kw: ({}, {}))
    monkeypatch.setattr(exercise_history, "load_bodyweight_index", lambda **kw: {})
    monkeypatch.setattr(exercise_history, "load_whoop_workout_index", lambda **kw: {})
    lift = [{"name": "Leg Press", "sets": [{"weight_kg": 90, "reps": 5}]}, {"name": "Bench Press", "sets": [{"weight_kg": 60, "reps": 5}]}]
    done = [{"date": d, "exercises": lift} for d in ("2026-09-24", "2026-09-26")]
    inputs = rg.GeneratorInputs(
        target_date=RA_TARGET, volume_7d={}, recovery_tier="green", acwr_flag="safe", z2_minutes_7d=z2, block_workouts=done
    )
    ideal = next(r for r in rg.generate_routines(inputs) if r.variant == "ideal")
    assert ideal.inputs_snapshot["z2_minutes_7d"] == z2  # the record the live proof reads
    return ideal.rationale


def test_the_draft_path_reads_the_real_aerobic_minutes_and_writes_no_walk_more_note(monkeypatch):
    """The nightly pre-draft's path (`_action_draft` → `_generator_inputs`) over the fixture partitions.
    Mutation control: restore `z2_minutes_7d=float(args.get("z2_minutes_7d") or 0)` in
    `tools_hevy_routine._generator_inputs` — the inputs read 0 and the note says walk more."""
    from mcp import shared_quantities, tools_hevy_routine as thr

    with patch.object(shared_quantities._core, "query_source_range", side_effect=_fixture_read):
        inputs = thr._generator_inputs({"target_date": RA_TARGET})
    assert inputs.z2_minutes_7d == RA_MINUTES
    assert not any("walk more" in r for r in _full_body_rationale(monkeypatch, inputs.z2_minutes_7d))
    # the in-test control: the old literal 0 is exactly what wrote the note
    assert any("walk more" in r for r in _full_body_rationale(monkeypatch, 0.0))


def test_the_cron_reads_the_same_quantity_as_the_mcp_path():
    """Two draft paths, one number. Mutation control: put `z2_minutes_7d=0.0` back in the cron's
    `_gather_inputs` — this reds."""
    import importlib

    cron = importlib.import_module("operational.hevy_routine_cron_lambda")
    assert cron._z2_minutes_7d(RA_TARGET, read=_fixture_read) == RA_MINUTES
    with patch.object(cron, "_read_partition", side_effect=_fixture_read):
        assert cron._gather_inputs(RA_TARGET, False).z2_minutes_7d == RA_MINUTES


def test_an_unreadable_aerobic_read_is_unknown_and_writes_no_walk_more_note(monkeypatch):
    """ADR-104: both sources raising → None, and a floor (one source unreadable) → None too — a floor
    below 90 min cannot say he is below it. None writes the unknown line, never the walk-more note.
    Mutation control: make `_portfolio_guard` return `(z2_minutes_7d or 0) >= z2_floor` — this reds."""
    import importlib

    from training import recent_aerobic, routine_generator as rg

    from mcp import shared_quantities, tools_hevy_routine as thr

    with patch.object(shared_quantities._core, "query_source_range", side_effect=RuntimeError("ddb down")):
        assert thr._generator_inputs({"target_date": RA_TARGET}).z2_minutes_7d is None
    cron = importlib.import_module("operational.hevy_routine_cron_lambda")

    def strava_down(source: str, start: str, end: str) -> list[dict]:
        if source == "strava":
            raise RuntimeError("strava down")
        return _fixture_read(source, start, end)

    assert cron._z2_minutes_7d(RA_TARGET, read=strava_down) is None
    assert recent_aerobic.aerobic_minutes_7d(None) is None
    rationale = _full_body_rationale(monkeypatch, None)
    assert rg.Z2_UNKNOWN_NOTE in rationale and not any("walk more" in r for r in rationale)


# ── #4412: a Hevy cardio block joined to the wearable HR over its OWN minutes ─────────────
# Wire SHAPES of the live rows (the driver's 2026-09-29 read of the 09-28 session): a lower session
# whose tail is Cycling (the recumbent — Hevy's template is named "Cycling") then Stretching, and the
# WHOOP activity as it reaches the platform, a Strava row with `device_name: WHOOP`. Values are
# PERTURBED and rounded (public repo). Hevy sets carry no timestamps: the block's minutes are the
# session end minus the Stretching after it.
def _j_session(tail_first: str = "Cycling") -> dict:
    return {
        "pk": "USER#matthew#SOURCE#hevy",
        "sk": "DATE#2026-09-28#WORKOUT#w4412",
        "date": "2026-09-28",
        "start_time": "2026-09-28T23:00:00+00:00",
        "end_time": "2026-09-29T00:50:00+00:00",
        "exercises": [
            {"name": "Squat (Barbell)", "template_id": "T-SQ", "sets": [{"reps": 8, "weight_kg": 60.0}, {"reps": 8, "weight_kg": 60.0}]},
            {"name": tail_first, "template_id": "T-CY", "sets": [{"duration_sec": 2400, "distance_m": 15000}]},
            {"name": "Stretching", "template_id": "T-ST", "sets": [{"duration_sec": 900, "distance_m": None}]},
        ],
    }


def _whoop(start: str, secs: int, avg: float = 101.0, sport: str = "Ride", device: str = "WHOOP") -> dict:
    return {
        "type": sport,
        "sport_type": sport,
        "device_name": device,
        "start_date": start,
        "elapsed_time_seconds": secs,
        "moving_time_seconds": secs,
        "has_heartrate": True,
        "average_heartrate": avg,
        "max_heartrate": avg + 20,
        "zone1_seconds": secs // 2,
        "zone2_seconds": secs - secs // 2,
    }


# block = 23:55:00 → 00:35:00 (session end 00:50 − 15 min stretching − 40 min cycling)
_HEVY_ECHO = {
    "type": "WeightTraining",
    "sport_type": "WeightTraining",
    "device_name": "Hevy",
    "start_date": "2026-09-28T23:00:00Z",
    "elapsed_time_seconds": 6600,
    "average_heartrate": True,
}  # a flattened DDB NULL — absent, never 1 bpm
_LIFT_WHOOP = _whoop("2026-09-28T23:02:00Z", 2100, avg=126.0, sport="WeightTraining")


def test_a_recumbent_block_joins_the_whoop_hr_over_its_inferred_minutes():
    """Joined: WHOOP covered 36 of the block's 40 min → coverage 0.9, the block's avg/max from that
    activity, zone seconds prorated by overlap. The lift-labelled WHOOP row and the Hevy echo never
    lend their HR (the de-dup's own `hr_intervals` filter). Mutation control: make `join_workout` join
    the SESSION's minutes instead of `block_windows`'s — coverage of the 110-min session drops under
    HR_COVERAGE_MIN and the block reads unknown (run: red)."""
    from training import cardio_hr

    acts = [_HEVY_ECHO, _LIFT_WHOOP, _whoop("2026-09-28T23:59:00Z", 2400)]
    (b,) = cardio_hr.join_workout(_j_session(), acts)["blocks"]
    assert b["window"] == {"start_utc": "2026-09-28T23:55:00+00:00", "end_utc": "2026-09-29T00:35:00+00:00", "timing": "inferred_tail"}
    assert b["state"] == "joined" and b["hr_source"] == "WHOOP" and b["hr_coverage"] == 0.9
    assert (b["avg_hr"], b["max_hr"]) == (101.0, 121.0)
    assert b["zone_seconds"]["zone1_seconds"] == 1080 and b["zone_basis"] == "prorated_by_overlap"
    assert b["hr_drift"] is None and b["hr_recovery_60s"] is None  # no per-second series on the wire — said, not faked


def test_no_overlap_or_thin_coverage_is_unknown_never_zero():
    """The live 09-28 shape: the only WHOOP row is the lift, which ended before the bike began →
    unknown, coverage 0.0, every HR field None. And a WHOOP row covering 19 of 40 min (0.475) sits
    under HR_COVERAGE_MIN → unknown too. Mutation control: set HR_COVERAGE_MIN = 0 — the thin case
    joins at 0.475 and this reds; drop the `not used` guard — the avg divides by zero."""
    from training import cardio_hr

    (b,) = cardio_hr.join_workout(_j_session(), [_HEVY_ECHO, _LIFT_WHOOP])["blocks"]
    assert (b["state"], b["hr_coverage"], b["avg_hr"], b["max_hr"], b["zone_seconds"]) == ("unknown", 0.0, None, None, None)
    (thin,) = cardio_hr.join_workout(_j_session(), [_whoop("2026-09-29T00:16:00Z", 1800)])["blocks"]
    assert thin["hr_coverage"] == 0.475 and thin["state"] == "unknown" and thin["avg_hr"] is None
    assert cardio_hr.COVERAGE_PROVENANCE["provenance"] == "convention"  # ADR-105: the threshold says what it is
    (unread,) = cardio_hr.join_workout(_j_session(), None)["blocks"]
    assert unread["state"] == "unknown" and unread["hr_coverage"] is None and "could not be read" in unread["reason"]
    # a cardio block with a lift on BOTH sides cannot be placed — unknown, never a guessed window
    s = _j_session()
    s["exercises"].append({"name": "Leg Curl", "sets": [{"reps": 10, "weight_kg": 30.0}]})
    (mid,) = cardio_hr.join_workout(s, [_whoop("2026-09-28T23:59:00Z", 2400)])["blocks"]
    assert mid["window"] is None and mid["state"] == "unknown" and mid["avg_hr"] is None


def test_the_0925_treadmill_replays_joined_on_the_live_fixture():
    """The 09-25 treadmill (RA_FIX, the live rows): its inferred minutes 23:40:31 → 00:40:31 sit 3088 s
    inside the WHOOP walk → coverage 0.858, 116.9 bpm — and recent_aerobic's row carries the block's
    own verdict, which the joints critic reads as `last_cardio_block_avg_hr`."""
    from training import cardio_hr, recent_aerobic

    (w,) = [r for r in _ra_rows("hevy") if r["date"] == "2026-09-25"]
    acts = [a for r in _ra_rows("strava") if r["date"] in ("2026-09-25", "2026-09-26") for a in r.get("activities") or []]
    (b,) = cardio_hr.join_workout(w, acts)["blocks"]
    assert (b["state"], b["hr_coverage"], b["avg_hr"], b["hr_source"]) == ("joined", 0.858, 116.9, "WHOOP")
    block = _ra_block()
    (tread,) = [r for r in block["rows"] if r["modality"] == "treadmill"]
    assert (tread["hr_state"], tread["hr_coverage"], tread["avg_hr"]) == ("joined", 0.858, 116.9) and "#4412" in tread["hr_source"]
    last = recent_aerobic.last_cardio_block_hr(block)
    assert last == {
        "date": "2026-09-25",
        "modality": "treadmill",
        "avg_hr": 116.9,
        "max_hr": 150.0,
        "hr_coverage": 0.858,
        "over_ceiling": False,  # #4503 OD2: 116.9 is under the 120 avg cap (105 is the target, not the cap)
    }
    packet = _joints(critics.draft_summary(_lower_volume_draft()), block)
    assert packet["numbers"]["last_cardio_block_avg_hr"] == 116.9 and packet["numbers"]["last_cardio_block_over_hr_ceiling"] is False
    verdict = critics.deterministic_verdict(packet)
    assert "116.9 bpm avg" in verdict["reason"] and "coverage 0.858" in verdict["reason"]


def _key_values(cond) -> list:
    """The literal values inside a boto3 key condition (pk value, sk bound/prefix)."""
    out = []
    for v in cond.get_expression()["values"]:
        out.extend(_key_values(v) if hasattr(v, "get_expression") else [] if hasattr(v, "name") else [v])
    return out


class _FakeTable:
    """The DDB calls the store makes, over dicts — the wire shapes, no boto3 I/O. Queries route by pk:
    the Hevy partition returns `workouts`, the WHOOP partition the `whoop` rows whose sk starts with
    the queried prefix."""

    def __init__(self, workouts: list[dict], strava: dict[str, dict], whoop: list[dict] | None = None):
        self.workouts, self.strava, self.whoop, self.updates = workouts, strava, whoop or [], []

    def get_item(self, Key):
        if "#SOURCE#hevy" in Key["pk"]:
            return next(({"Item": w} for w in self.workouts if w["sk"] == Key["sk"]), {})
        return {"Item": self.strava[Key["sk"]]} if Key["sk"] in self.strava else {}

    def query(self, **kw):
        pk, *rest = _key_values(kw["KeyConditionExpression"])
        if "#SOURCE#whoop" in pk:
            return {"Items": [r for r in self.whoop if r["sk"].startswith(rest[0])]}
        return {"Items": self.workouts}

    def update_item(self, Key, UpdateExpression, ConditionExpression, ExpressionAttributeValues):
        assert UpdateExpression == "SET cardio_hr = :c" and set(ExpressionAttributeValues) == {":c"}  # ONLY cardio_hr
        self.updates.append((Key["sk"], ExpressionAttributeValues[":c"]))
        for w in self.workouts:
            if w["sk"] == Key["sk"]:
                w["cardio_hr"] = ExpressionAttributeValues[":c"]


def test_the_hourly_rejoin_heals_an_unknown_block_once_the_wearable_lands_and_then_writes_nothing():
    """At ingest the WHOOP ride has not reached Strava: the record is stored `unknown`. The next poll
    finds it and UpdateItems once; the poll after writes NOTHING (a Decimal-stored record compares
    equal to its re-derivation). Mutation control: drop the `_same` short-circuit — the third run
    writes again and `len(updates) == 1` reds."""
    from training import cardio_hr_store as store

    rec = _j_session()
    t = _FakeTable([rec], {"DATE#2026-09-28": {"activities": [_HEVY_ECHO, _LIFT_WHOOP]}})
    store.attach(t, "matthew", rec)
    assert rec["cardio_hr"]["blocks"][0]["state"] == "unknown"
    t.strava["DATE#2026-09-28"]["activities"].append(_whoop("2026-09-28T23:59:00Z", 2400))
    first = store.rejoin_recent(t, "matthew", "2026-09-29")
    assert first == {"considered": 1, "updated": 1, "joined": 1, "errors": 0}
    assert rec["cardio_hr"]["blocks"][0]["state"] == "joined"
    second = store.rejoin_recent(t, "matthew", "2026-09-29")
    assert second["updated"] == 0 and len(t.updates) == 1


# ── #4412 proof read (2026-10-01): the join ran and attached NOTHING on the two live rides ─────────
# The REAL rows, read read-only from DDB and stored as the wire shape (tests/fixtures/walking_volume_3930/
# cardio_hr_4412_live.json — location/polyline/notes keys redacted, named in its `_source`). Two causes:
#   (1) the 09-29 WHOOP gym session (Cross Training, 23:03 → 00:28:59Z, avg 109) reaches Strava as
#       `WeightTraining`, and 1.0.0 reused the de-dup's filter, which treats every lift-labelled
#       activity as a Hevy echo — so the one record that measured the bike minutes was dropped;
#   (2) the 09-28 WHOOP 'Activity' (23:53 → 00:33:59Z, avg 135) never reached Strava at all, and
#       1.0.0 read only Strava.
_LIVE_4412 = json.loads((FIXTURES / "cardio_hr_4412_live.json").read_text())


def _live_4412_table() -> "_FakeTable":
    hevy = [dict(w) for w in _LIVE_4412["hevy"]]
    return _FakeTable(hevy, _LIVE_4412["strava"], _LIVE_4412["whoop"])


def _live_hevy(day: str) -> dict:
    (w,) = [w for w in _LIVE_4412["hevy"] if w["date"] == day]
    return dict(w)


def test_the_live_0929_ride_joins_the_whoop_gym_session_its_strava_copy_calls_weighttraining():
    """Strava ONLY (cause 1 in isolation): the block's inferred minutes 00:06:57 → 00:46:57Z sit
    1322 s inside WHOOP's `WeightTraining` row → coverage 0.551 ≥ 0.5, joined at the row's 111.8.
    The Hevy echo (device Hevy, average_heartrate a flattened NULL) still lends nothing.
    Mutation control: `lift_is_echo=True` in `cardio_hr._hr_activities`/`join_block` (1.0.0's
    filter) — the block reads `unknown`, coverage 0.0, and this reds (run: red, then green)."""
    from training import cardio_hr

    w = _live_hevy("2026-09-29")
    acts = [a for sk in ("DATE#2026-09-29", "DATE#2026-09-30") for a in _LIVE_4412["strava"][sk]["activities"]]
    (b,) = cardio_hr.join_workout(w, acts)["blocks"]
    assert b["window"] == {"start_utc": "2026-09-30T00:06:57+00:00", "end_utc": "2026-09-30T00:46:57+00:00", "timing": "inferred_tail"}
    assert (b["state"], b["hr_coverage"], b["avg_hr"], b["hr_source"]) == ("joined", 0.551, 111.8, "WHOOP")
    assert [a["device"] for a in b["hr_activities"]] == ["WHOOP"]  # never the Hevy echo


def test_the_live_rides_join_through_the_store_and_the_0928_ride_needs_the_whoop_partition():
    """The full store path on the real rows (Strava day items + WHOOP workout rows, day and day+1):
      09-29 → joined from the direct WHOOP row (Cross Training, avg 109, max 139), coverage 0.551 —
              its Strava twin (same start) is dropped, and the row in BOTH the 09-29 and 09-30
              partitions is counted once;
      09-28 → joined from WHOOP 'Activity' (avg 135, max 153), coverage 0.985 — a record Strava
              never had.
    Mutation control: make `_whoop_workouts` return [] (1.0.0's Strava-only read) — 09-28 reads
    `unknown` with coverage 0.0 and this reds (run: red, then green)."""
    from training import cardio_hr_store as store

    t = _live_4412_table()
    j29 = store.derive(t, "matthew", _live_hevy("2026-09-29"))
    (b29,) = j29["blocks"]
    assert j29["version"] == "cardio-hr@1.1.0"
    assert (b29["state"], b29["hr_coverage"], b29["avg_hr"], b29["max_hr"], b29["hr_source"]) == ("joined", 0.551, 109.0, 139, "WHOOP")
    assert [a["whoop_workout_id"] for a in b29["hr_activities"]] == ["d49d8bac-e0f4-4d80-9828-29840bc361cf"]
    assert b29["zone_seconds"] is None  # WHOOP's zone minutes read 0 at avg 109 — not used, never prorated
    (b28,) = store.derive(t, "matthew", _live_hevy("2026-09-28"))["blocks"]
    assert (b28["state"], b28["hr_coverage"], b28["avg_hr"], b28["max_hr"]) == ("joined", 0.985, 135.0, 153)
    assert [a["whoop_workout_id"] for a in b28["hr_activities"]] == ["60f4ac11-c50b-41ee-b071-8631c802d571"]


def test_rejoin_one_rewrites_only_cardio_hr_once_and_then_nothing():
    """The re-derive path the driver runs after the deploy (hevy-backfill
    `{"rejoin_workout": "<id>", "date": "YYYY-MM-DD"}`): the stored 1.0.0 `unknown` record becomes
    `joined` in ONE UpdateItem that SETs only `cardio_hr` (the fake asserts the expression); the
    second invoke writes nothing. A missing workout or a malformed id writes nothing.
    Mutation control: drop the `_same` short-circuit in `_rejoin_item` — the second invoke writes
    again and `len(t.updates) == 1` reds."""
    from training import cardio_hr_store as store

    t = _live_4412_table()
    wid = "ef89d610-dc29-469e-b08e-2e4263264a58"
    assert t.workouts[1]["cardio_hr"]["blocks"][0]["state"] == "unknown"  # the stored 1.0.0 verdict
    first = store.rejoin_one(t, "matthew", "2026-09-29", wid)
    assert (first["found"], first["updated"], first["joined"]) == (True, 1, 1)
    assert first["blocks"][0]["state"] == "joined" and first["blocks"][0]["avg_hr"] == 109.0
    second = store.rejoin_one(t, "matthew", "2026-09-29", wid)
    assert second["updated"] == 0 and len(t.updates) == 1
    assert store.rejoin_one(t, "matthew", "2026-09-29", "nope")["found"] is False
    assert store.rejoin_one(t, "matthew", "2026-09-29", "x#WORKOUT#y")["errors"] == 1 and len(t.updates) == 1


def test_the_hevy_backfill_routes_the_rejoin_workout_event_and_polls_nothing(monkeypatch):
    """`{"rejoin_workout", "date"}` calls `rejoin_one` with exactly those values and returns before
    the events poll (no cursor read)."""
    from ingestion import hevy_backfill_lambda as hbl

    seen = []
    monkeypatch.setattr(hbl.cardio_hr_store, "rejoin_one", lambda _t, u, d, w: seen.append((u, d, w)) or {"updated": 1})
    monkeypatch.setattr(hbl, "load_since", lambda: (_ for _ in ()).throw(AssertionError("polled")))
    out = hbl.lambda_handler({"rejoin_workout": "abc", "date": "2026-09-29"}, None)
    assert seen == [(hbl.USER_ID, "2026-09-29", "abc")] and json.loads(out["body"]) == {"updated": 1}
