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
        out = tp.tool_plan_next_session({"target_date": WINDOW_END})
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
    assert walking["state"] == "unknown"
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
