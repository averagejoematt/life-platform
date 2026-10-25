"""tests/test_program_session_4064_4147.py — the program's session for each role: v0.4 Upper/Lower, then the five-day split.

WHY THIS FILE EXISTS

#4064 made the generator build the PROGRAM's session (top set, back-offs, rep ranges, fixed
accessories) instead of a muscle-budget session with a role label on it — then for v0.3
full body. On 2026-09-23 the owner switched to v0.4 Upper/Lower, served in ORDER (#4147;
`DECISION#2026-09-24T03:10:59`). This file (formerly test_fullbody_block_calendar_4064.py)
holds the same guarantees for v0.4; the order itself is tests/test_session_sequence_4110.py.

#5069 — owner rulings 2026-10-18 (epic #5067), quoted: (5) "Sessions: 5 lifting days, 60-75 min of
lifting. Sequence Upper-heavy, Lower-heavy, Shoulders+arms, Upper-volume, Lower-volume. Delts
3x/week." (6) "Structure lock: the v0.4 lock to 2026-11-04 is lifted now." The split is now the
charter's five roles (v0.4's four unchanged + `shoulders_arms`), each major muscle 2x/wk and delts
3x/wk, every session's lifting estimate inside the charter's cap (accessories trimmed first), one
cardio block and the stretching inside their caps, and the lock is history (`program_v04`).

  1. v0.4 IS DATA, ONE HOME. Four roles, archetypes upper/lower, every anchor pattern
     exactly twice a week, each redline muscle group inside its (moved) band, heavy = top
     4–6 @ RPE 7–8 + two back-offs at −10 %, volume = 8–12, the hinge's trap bar / RDL rule,
     no plyometrics and no max-effort singles, the block lock date, v0.3 kept as history.
  2. THE GENERATOR BUILDS IT: the first v0.4 session is Lower-heavy (the committed routine's
     shape), filed in the Lower folder, back-offs −10 % under the floored top set, the
     Minimum Viable Session machine-only, a deload that holds loads.
  3. v0.2 / INACTIVE IS UNTOUCHED — the sequence is never consulted.
  4. plan_next_session THROUGH THE MCP HANDLER serves the v0.4 session in order.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
from contextlib import ExitStack
from unittest.mock import patch

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "lambdas"))

os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from training import effort_ceilings, owner_redlines, program_structure, program_v03, program_v04, routine_generator  # noqa: E402
from training.training_charter import charter_value  # noqa: E402

CATALOG = json.loads((REPO / "config" / "movement_catalog.json").read_text())
UH, LH, SA, UV, LV = "upper_heavy", "lower_heavy", "shoulders_arms", "upper_volume", "lower_volume"

# The committed first v0.4 session (owner, from chat, 2026-09-23): routine
# b1b9960468f374e30dcdeca8630dd18f / Hevy 4b743f67, target 2026-09-25 — read back read-only from
# its ROUTINE# partition on 2026-09-24 and written out here by hand: squat_barbell 3 x 4–6,
# Romanian Deadlift (Barbell) 3 x 6–8, Linear Leg Press 2 x 8–10, Seated Leg Curl 2 x 10–12,
# Calf Press 2 x 12–15. The catalog's reviewed keys stand in for the three chat-authored
# `tmpl:` machines (leg_press / leg_curl / calf_raise_machine).
COMMITTED_LOWER_HEAVY = [
    ("squat_barbell", 3),
    ("romanian_deadlift_barbell", 3),
    ("leg_press", 2),
    ("leg_curl", 2),
    ("calf_raise_machine", 4),  # #5053: calves at their MEV floor (8/wk) across the two lower days
]


def _ws(block):
    """The block's WORKING sets — #5049 prepends `warmup` sets to a qualifying compound."""
    return [s for s in block.sets if s.type != "warmup"]


def _rx(role, **kw):
    return program_structure.session_prescription_for_role(role, catalog_movements=CATALOG["movements"], **kw)


# ── 1. v0.4 is data ──────────────────────────────────────────────────────────
def test_the_split_is_the_charters_five_sessions_in_the_owners_order():
    """Ruling 5: "5 lifting days ... Sequence Upper-heavy, Lower-heavy, Shoulders+arms, Upper-volume, Lower-volume" —
    read from the charter, never restated: the role ids are the charter's names, spelled by `role_id`."""
    seq = program_structure.SESSION_SEQUENCE
    assert program_structure.SPLIT == "five_day" and program_structure.PROGRAM_VERSION == "1.0"
    assert seq["session_roles"] == [program_structure.role_id(n) for n in charter_value("split.sequence")] == [UH, LH, SA, UV, LV]
    assert seq["sessions_per_week"] == charter_value("split.lifting_days_per_wk") == 5
    from training import session_sequence  # #5077: the block length is added from the charter by `_seq()`, never copied

    assert session_sequence._seq()["weeks_per_block"] == charter_value("rotation.anchors_fixed_weeks")
    assert seq["charter_version"] == charter_value("version")
    assert {r: program_structure.SESSION_TEMPLATES[r]["archetype"] for r in seq["session_roles"]} == {
        UH: "upper",
        LH: "lower",
        SA: "upper",
        UV: "upper",
        LV: "lower",
    }
    assert program_structure._ROLE_LABEL[SA] == "SHOULDERS+ARMS"
    # v0.4's four roles are kept, unchanged, inside the five; its order is history
    assert set(program_v04.SESSION_SEQUENCE["session_roles"]) < set(seq["session_roles"])
    assert program_structure.SUPERSEDED_PROGRAMS["0.4"] is program_v04.SUPERSEDED


def test_every_anchor_pattern_meets_its_charter_frequency_and_the_press_runs_once():
    """#5162 (owner ruling 2026-10-23, "trade inside 75"): the overhead press anchors shoulders+arms only, 1 set — its other
    8 weekly sets are lateral raises and face pulls, so delts are still trained 3x/wk (ruling 5) by direct work. Every other
    pattern stays at the charter's each-major-muscle 2x/wk."""
    counts: dict[str, int] = {}
    for role in program_structure.SESSION_SEQUENCE["session_roles"]:
        for pattern, _ in program_structure.SESSION_TEMPLATES[role]["anchors"]:
            counts[pattern] = counts.get(pattern, 0) + 1
    assert counts == {p: a["frequency_per_week"]["low"] for p, a in program_structure.ANCHORS.items()}
    assert counts["overhead_press"] == charter_value("split.frequency.overhead_press_per_wk") == 1
    assert [r for r, t in program_structure.SESSION_TEMPLATES.items() if any(p == "overhead_press" for p, _ in t["anchors"])] == [SA]
    assert _rx(SA)["exposures"][0]["pattern"] == "overhead_press" and len(_rx(SA)["exposures"][0]["sets"]) == 1
    delts = program_structure.weekly_sets_by_muscle(CATALOG["movements"])["delts"]
    assert delts["frequency_per_wk"] >= charter_value("split.frequency.delts_per_wk") == 3
    assert {p: n for p, n in counts.items() if p != "overhead_press"} == {
        p: charter_value("split.frequency.each_major_muscle_per_wk") for p in program_structure.ANCHORS if p != "overhead_press"
    }


def test_heavy_days_are_a_top_set_plus_two_back_offs_and_volume_days_are_8_to_12():
    for role in (UH, LH):
        heavy = [e for e in _rx(role)["exposures"] if e["intensity"] == "heavy"]
        assert heavy, role
        for e in heavy:
            assert [s["kind"] for s in e["sets"]] == ["top", "back_off", "back_off"]
            # #5058: the top set's RPE band is the charter's ruled compounds band (7–8 before the charter)
            assert e["sets"][0]["reps"] == [4, 6] and e["sets"][0]["rpe"] == effort_ceilings.class_bands()[effort_ceilings.COMPOUNDS]
            assert all(s["pct_of_top"] == 90 for s in e["sets"][1:])
    for role in (UV, LV):
        anchors = [e for e in _rx(role)["exposures"] if e["kind"] == "anchor"]
        assert anchors and all(e["intensity"] == "volume" for e in anchors), role
        assert all(s["reps"] == [8, 12] for e in anchors for s in e["sets"]), role


def test_exposure_numbers_match_the_redline_rep_scheme_prose():
    prose = owner_redlines.REDLINES["lifting_sessions_per_wk"]["rep_scheme"]
    e = program_structure.EXPOSURES
    assert f"{e['heavy']['reps'][0]}–{e['heavy']['reps'][1]}" in prose
    assert f"−{abs(e['heavy']['back_off_pct'])} %" in prose
    assert f"moderate {e['moderate']['reps'][0]}–{e['moderate']['reps'][1]}" in prose
    assert f"volume {e['volume']['reps'][0]}–{e['volume']['reps'][1]}" in prose
    assert f"accessories {e['accessory']['reps'][0]}–{e['accessory']['reps'][1]}" in prose
    # #5058: the RPE lives only in the charter — the prose names it, EXPOSURES names the class band, neither types a number
    assert "the charter compound ceiling" in prose and "the charter isolation ceiling" in prose
    assert not any(k in spec for spec in e.values() for k in ("top_rpe", "rir"))
    bands = effort_ceilings.class_bands()
    assert {spec["effort"] for spec in e.values()} == {effort_ceilings.COMPOUNDS} and all(spec["effort"] in bands for spec in e.values())
    assert e["accessory"]["last_set_effort"] == effort_ceilings.LAST_ISOLATION_SET
    assert "back_off_effort" not in e["heavy"]  # #5058 review: back-offs are prescribed by % of the top set only


def test_sets_per_muscle_per_week_sit_in_the_band_and_the_aesthetic_day_lifts_delts_and_arms():
    """Owner 2026-09-23: ~10 hard sets/muscle/wk -> [8, 12] for the big groups (one home, owner_redlines); the
    volume_ceiling tripwire is the band's top. #5069: the shoulders+arms day lifts delts and arms ABOVE v0.4's 4–6 by
    ruling 5, so for them that band is a floor (`band_top_binds: False`); their charter bands are #5053's."""
    lift = owner_redlines.REDLINES["lifting_sessions_per_wk"]
    assert lift["sets_per_muscle_wk"] == [8, 12]
    ceiling = next(t for t in owner_redlines.TRIPWIRES if t["id"] == "volume_ceiling")
    assert ceiling["threshold"]["sets_per_muscle_wk"] == lift["sets_per_muscle_wk"][1]
    got = program_structure.weekly_sets_by_muscle(CATALOG["movements"])
    assert {g: v["sets"] for g, v in got.items()} == {
        "quads": 8,
        "hams_glutes": 8,  # #5053: the lower-volume second leg curl traded for the calves/core floors (the 75-set week is full)
        "chest": 8,
        "back": 10,  # #5318 (ruling B3): the shrug's 2 catalog-'back' sets became the farmer's carry (Hevy files it `other`)
        "delts": 15,  # #5053: + the rear-delt pec deck on the upper heavy day
        "biceps": 6,
        "triceps": 6,
    }
    for group, row in got.items():
        lo, hi = row["range"]
        assert lo <= row["sets"], (group, row)
        if row["band_top_binds"]:
            assert row["sets"] <= hi, (group, row)
    assert {g for g, v in got.items() if not v["band_top_binds"]} == {"delts", "biceps", "triceps"}


def test_each_major_muscle_twice_and_delts_three_times_a_week():
    """Ruling 5 + the #5069 acceptance: 'each major muscle 2x/wk, delts 3x/wk' — counted as the sessions whose
    exposures train the group directly, held against the charter's `split.frequency`."""
    got = program_structure.weekly_sets_by_muscle(CATALOG["movements"])
    short = {g: (v["frequency_per_wk"], v["frequency_target"]) for g, v in got.items() if v["frequency_per_wk"] < v["frequency_target"]}
    assert not short, f"groups under their charter frequency: {short}"
    assert got["delts"]["frequency_target"] == 3 and got["delts"]["sessions"] == [UH, SA, UV]
    assert all(v["frequency_target"] == 2 for g, v in got.items() if g != "delts")


def test_mutation_control_without_the_aesthetic_days_press_and_raises_delts_fall_to_twice_a_week():
    """The frequency check can fail: strip the shoulders+arms day of its press, lateral raise and face pull and the delts
    are trained on two sessions only — under the charter's 3."""
    sa = program_structure.SESSION_TEMPLATES[SA]
    with patch.dict(sa, {"anchors": [], "accessories": ["db_curl", "cable_tricep_pushdown", "farmers_carry"]}):
        delts = program_structure.weekly_sets_by_muscle(CATALOG["movements"])["delts"]
    assert delts["frequency_per_wk"] == 2 < delts["frequency_target"]


def test_mutation_control_three_more_pulldown_sets_push_back_over_the_band_top():
    """The band check can fail: the same week with vertical pull at 5 sets on upper-volume puts
    back at 13 (15 before #5318 moved the shrug to a carry), over the 8–12 top — the per-group assertion above would red on it."""
    with patch.dict(program_structure.SESSION_TEMPLATES[UV]["anchor_sets"], {"vertical_pull": 5}):
        back = program_structure.weekly_sets_by_muscle(CATALOG["movements"])["back"]
    assert back["sets"] == 13 and back["sets"] > back["range"][1] and back["band_top_binds"]


def test_sessions_fit_the_ceiling_and_the_week_total_sits_in_the_redline_band():
    ceiling = program_structure.week_grid()["session_set_ceiling"]
    totals = {r: _rx(r)["total_sets"] for r in program_structure.SESSION_TEMPLATES}
    assert totals == {UH: 17, LH: 14, SA: 13, UV: 17, LV: 14}  # #5053: floors
    assert all(t <= ceiling for t in totals.values()), totals
    # #4503 OD4: v0.5's base 60–75 hard sets/wk — the five-day week (69) sits inside it with no 🟢 tail
    lo, hi = owner_redlines.REDLINES["lifting_sessions_per_wk"]["total_hard_sets_wk"]
    assert lo <= sum(totals.values()) == 75 <= hi
    for role, tmpl in program_structure.SESSION_TEMPLATES.items():
        assert set(tmpl["accessories"]) <= set(program_structure.ACCESSORY_POOL[tmpl["archetype"]]), role
        if role == SA:
            # ruling 5: the aesthetic day's accessories ARE the session — stated on the template, not silently exempt
            assert len(tmpl["accessories"]) == 5 and "ruling 5" in tmpl["accessory_rule"]
        elif role in (UH, UV):
            # #5162: the press left these days for a delt accessory — four, stated on the template, never silently exempt
            assert len(tmpl["accessories"]) == 4 and "#5162" in tmpl["accessory_rule"], role
        else:
            assert 2 <= len(tmpl["accessories"]) <= 3, role


def test_the_hinge_is_the_trap_bar_and_the_rdl_only_as_the_moderate_hinge():
    lh = {e["pattern"]: e for e in _rx(LH)["exposures"] if e["kind"] == "anchor"}
    lv = {e["pattern"]: e for e in _rx(LV)["exposures"] if e["kind"] == "anchor"}
    assert (lh["hinge"]["intensity"], lh["hinge"]["movement_key"]) == ("moderate", "romanian_deadlift_barbell")
    assert (lv["hinge"]["intensity"], lv["hinge"]["movement_key"]) == ("volume", "deadlift_trap_bar")
    assert owner_redlines.REDLINES["load_anchoring"]["trap_bar_until_lb"] == 275
    assert program_structure.ANCHORS["hinge"]["catalog_keys"][0] == "deadlift_trap_bar"
    # the RDL is never a non-moderate hinge: it is not in the family's general keys
    assert not any("romanian" in k for k in program_structure.ANCHORS["hinge"]["catalog_keys"])


def test_no_plyometrics_and_no_max_effort_singles():
    excl = program_structure.EXCLUDED_METHODS
    assert set(excl["methods"]) >= {"plyometrics", "max_effort_singles"} and excl["provenance"] == "owner"
    for role in program_structure.SESSION_TEMPLATES:
        for e in _rx(role)["exposures"]:
            # #5318: a carry is timed, not a rep range — it carries a duration instead, and no rep floor applies
            assert all(
                s["reps"][0] >= excl["min_reps_any_exposure"] if e["intensity"] != "carry" else s["duration_seconds"] > 0 for s in e["sets"]
            ), (role, e["movement_key"])
            assert not any(w in (e["movement_key"] or "") for w in ("jump", "plyo", "box", "bound")), (role, e["movement_key"])


def test_the_v04_lock_is_lifted_and_kept_only_as_history():
    """Ruling 6: "the v0.4 lock to 2026-11-04 is lifted now". The lock is a dated record (`program_v04.BLOCK_LOCK`),
    the guard functions are gone, and the served session carries the fingerprint as a MEASUREMENT."""
    from training import session_sequence

    # #5077: the block length is the charter's `rotation.anchors_fixed_weeks`, added by session_sequence._seq() — no copy
    # on the sequence; the lifted v0.4 lock's six weeks are the same number, kept as history
    assert "weeks_per_block" not in program_structure.SESSION_SEQUENCE
    assert session_sequence._seq()["weeks_per_block"] == program_v04.BLOCK_LOCK["weeks"] == 6

    assert not hasattr(program_structure, "BLOCK_LOCK")
    assert not hasattr(session_sequence, "block_lock_state") and not hasattr(session_sequence, "fingerprint_record_problems")
    lock = program_structure.BLOCK_LOCK_HISTORY
    assert lock is program_v04.BLOCK_LOCK and lock["locked_until"] == "2026-11-04"
    assert lock["lifted"]["on"] == "2026-10-18" and "#5069" == lock["lifted"]["issue"]
    # the live block was NOT re-anchored
    assert program_structure.SESSION_SEQUENCE["block_start"] == program_v04.SESSION_SEQUENCE["block_start"] == "2026-09-24"
    state = session_sequence.next_session("2026-10-20", [])["structure"]
    assert state["lock"] == "lifted" and state["structure_fingerprint"] == session_sequence.structure_fingerprint()


def test_a_structural_edit_moves_the_fingerprint_and_refuses_nothing():
    """Mutation control for the lifted lock: an accessory swap changes the measured fingerprint, and the served session
    still serves — no `violated`, no `refusal` (the #4161 guard would have refused it before 2026-11-04)."""
    from training import session_sequence

    before = session_sequence.structure_fingerprint()
    with patch.dict(program_structure.SESSION_TEMPLATES[LH], {"accessories": ["leg_curl", "calf_raise_machine"]}):
        after = session_sequence.structure_fingerprint()
        served = session_sequence.next_session("2026-10-10", [])
    assert after != before
    assert served["source"] == "session_sequence" and "refusal" not in served and served["structure"]["lock"] == "lifted"


def test_v03_is_marked_superseded_and_kept_readable():
    sup = program_structure.SUPERSEDED_PROGRAMS["0.3"]
    assert sup is program_v03.SUPERSEDED
    assert (sup["superseded_on"], sup["decision_sk"], sup["superseded_by"]) == ("2026-09-24", "DECISION#2026-09-24T03:10:59", "0.4")
    # the definitions are still there, verbatim
    assert list(program_v03.SESSION_TEMPLATES) == ["heavy", "moderate", "heavy_moderate", "optional_fourth"]
    assert program_v03.HEVY_FOLDER == "Full Body" and program_v03.BLOCK_CALENDAR["steady_weekdays"] == [0, 2, 4]
    assert program_v03.BLOCK_CALENDAR["superseded"] is sup
    # load_ramp still measures the detraining-discount age to this date; it must equal the live block's start (not re-anchored)
    assert program_structure.BLOCK_CALENDAR["block_1_start"] == program_structure.SESSION_SEQUENCE["block_start"]
    # #5069: v0.4 is superseded the same way — its order and its lock kept, readable
    v04 = program_structure.SUPERSEDED_PROGRAMS["0.4"]
    assert (v04["superseded_on"], v04["superseded_by"], v04["issue"]) == ("2026-10-18", "1.0", "#5069")
    assert program_v04.SESSION_SEQUENCE["session_roles"] == [UH, LH, UV, LV] and program_v04.SESSION_SEQUENCE["first_role"] == LH


def test_deload_cuts_about_40_percent_of_sets_and_keeps_every_top_set_and_anchor():
    """#4161 (v3.3): −40 % sets, loads held (Coleman 2024) — was −30 %."""
    for role in program_structure.SESSION_TEMPLATES:
        full = program_structure.session_prescription_for_role(role)
        dl = program_structure.session_prescription_for_role(role, deload=True)
        assert dl["deload_trim"]["sets_after"] == full["total_sets"] - round(full["total_sets"] * 0.40)
        assert dl["deload_trim"]["pct"] == -40 and dl["deload_trim"]["loads"] == "held"
        assert [e["pattern"] for e in dl["exposures"]] == [e["pattern"] for e in full["exposures"]]
        for e in dl["exposures"]:
            assert len(e["sets"]) >= 1
            if e["intensity"] == "heavy":
                assert e["sets"][0]["kind"] == "top"


# ── #5069: the session's LENGTH (ruling 5: "60-75 min of lifting"; #5318 A4: a 75-min ceiling, no floor) and its shape ──
def test_every_session_fits_the_charters_lifting_minutes_untrimmed():
    """Each role's estimate (working + assumed warm-up sets x (set time + the exposure's rest)) is inside the charter's
    cap with nothing trimmed. Upper-heavy by hand before #5162: bench 3+3 warm-up and row 3+1 at 180 s rest, the press 3+1 and
    the pulldown 2 at 120 s, two accessories x 2 at 90 s, set time 45 s -> (6+4)x225 + 4x165 + 2x165 + 4x135 = 3780 s = 63.0 min.
    #5162 traded the press (3 sets + a warm-up at 120 s) for a 3-set lateral raise at 90 s: 67.5 -> 63.2 min."""
    cap = charter_value("split.session_minutes.lifting_ceiling")
    assert program_structure.lifting_minutes_cap() == cap == 75
    got = {r: _rx(r)["session_minutes"]["lifting_minutes"] for r in program_structure.SESSION_TEMPLATES}
    # #5162: were 67.5 / 51.5 / 39 / 57.5 / 45.5 (#5053: 63 / 47 / 39 / 57.5 / 41)
    assert got == {UH: 63.2, LH: 51.5, SA: 38.0, UV: 53.2, LV: 45.5}
    for role in program_structure.SESSION_TEMPLATES:
        rx = _rx(role)
        assert rx["time_trim"] is None and rx["session_minutes"]["within_cap"] and rx["session_minutes"]["cap"] == cap, role
        assert rx["session_minutes"]["charter_version"] == rx["charter_version"] == charter_value("version")
    # the side caps ride on every estimate, read from the charter
    est = _rx(UH)["session_minutes"]
    assert (
        (est["cardio_block_max_minutes"], est["stretching_max_minutes"])
        == (
            charter_value("split.session_minutes.cardio_block_max"),
            charter_value("split.session_minutes.stretching_max"),
        )
        == (30, 10)
    )


def test_mutation_control_a_session_over_the_cap_trims_accessories_first_and_records_it():
    """Rest at 300 s on every accessory puts upper-volume over 75 min: the trim drops accessories, last-listed first,
    until it fits, and says what it dropped; the anchors are untouched."""
    with patch.dict(program_structure.EXPOSURES["accessory"], {"rest_seconds": 300}):
        rx = _rx(UV)
    t = rx["time_trim"]
    assert t["estimate_before_min"] > t["cap_minutes"] == 75 >= t["estimate_after_min"] == rx["session_minutes"]["lifting_minutes"]
    assert t["dropped_accessories"] == ["db_curl"] and t["over_cap_after_trim"] is False
    assert [e["kind"] for e in rx["exposures"]].count("anchor") == 3 and [e["movement_key"] for e in rx["exposures"]][
        -1
    ] == "cable_tricep_pushdown"


def test_anchors_are_never_cut_for_time_an_anchors_only_overrun_is_flagged():
    with patch.dict(program_structure.EXPOSURES["heavy"], {"rest_seconds": 900}):
        rx = _rx(UH)
    t = rx["time_trim"]
    assert t["over_cap_after_trim"] is True and t["dropped_accessories"] == [
        "reverse_pec_deck",
        "db_curl",
        "cable_tricep_pushdown",
        "db_lateral_raise",
    ]
    assert [e["pattern"] for e in rx["exposures"]] == ["bench", "row", "vertical_pull"]  # #5162: the press is on shoulders+arms


def _timed(key: str, minutes: float, rest: int | None = None):
    from training.routine_ir import ExerciseBlock, Set

    return ExerciseBlock(movement_key=key, sets=[Set(duration_seconds=int(minutes * 60))], rest_seconds=rest)


def test_the_session_shape_keeps_one_cardio_block_and_cuts_cardio_and_stretching_to_their_caps():
    """Ruling 5's caps on a routine's blocks: one deliberate cardio block <= 30 min, stretching <= 10 min. The chat path
    reports (`session_shape_problems`); the generator enforces (`enforce_session_shape`) and records each action."""
    from training.routine_ir import ExerciseBlock, Set

    movements = CATALOG["movements"]
    lunge = ExerciseBlock(
        movement_key="walking_lunge_dumbbell", sets=[Set(weight_kg=20, rep_range_start=8, rep_range_end=12)] * 2, rest_seconds=90
    )
    blocks = [lunge, _timed("treadmill", 40), _timed("air_bike", 10), _timed("stretching", 8), _timed("90_90_hip_stretch", 6)]
    problems = program_structure.session_shape_problems(blocks, movements)
    assert any("2 cardio blocks" in p for p in problems) and any("treadmill is 40.0 min, over the 30-min cap" in p for p in problems)
    assert any("stretching 14.0 min is over the 10-min cap" in p for p in problems)
    shape = program_structure.enforce_session_shape(blocks, movements)
    assert [b.movement_key for b in blocks] == ["walking_lunge_dumbbell", "treadmill", "stretching", "90_90_hip_stretch"]
    assert shape["cardio_blocks"] == [{"movement_key": "treadmill", "minutes": 30.0}] and shape["stretching_minutes"] == 10.0
    assert len(shape["actions"]) == 3 and program_structure.session_shape_problems(blocks, movements) == []
    # a weighted walking lunge is a LIFT (by its set shape), never the session's cardio block
    assert shape["lifting_minutes"] == round(2 * (45 + 90) / 60.0, 1)


def test_mutation_control_a_routine_inside_the_shape_reports_nothing_and_is_left_alone():
    blocks = [_timed("treadmill", 30), _timed("stretching", 10)]
    assert program_structure.session_shape_problems(blocks, CATALOG["movements"]) == []
    assert program_structure.enforce_session_shape(blocks, CATALOG["movements"])["actions"] == []
    assert [b.sets[0].duration_seconds for b in blocks] == [1800, 600]


def test_the_chat_path_flags_the_shape_and_the_lower_predicate_reads_the_charters_names():
    """The chat path (`draft_custom`) flags a break of the session shape and never edits his routine; the cardio pick's
    lower-session predicate reads the charter's names (no hand list of sequence names)."""
    from training import recent_aerobic

    from mcp.plan_cardio_pick import draft_cardio_warnings

    warnings = draft_cardio_warnings([_timed("air_bike", 40), _timed("air_bike", 10)], "upper", "2026-10-20")
    assert any("2 cardio blocks" in w for w in warnings) and any("over the 30-min cap" in w for w in warnings)
    assert all("just flagging" in w for w in warnings)
    assert recent_aerobic.is_lower("lower-heavy") and recent_aerobic.is_lower("Lower-volume") and recent_aerobic.is_lower("legs")
    assert not recent_aerobic.is_lower("shoulders+arms") and not recent_aerobic.is_lower("upper-heavy")


def test_without_the_catalog_anchors_are_patterns_not_guesses():
    rx = program_structure.session_prescription_for_role(LH)
    anchors = [e for e in rx["exposures"] if e["kind"] == "anchor"]
    assert all(e["movement_key"] is None and "not read" in e["resolution_note"] for e in anchors)


# ── 2. the generator builds it ───────────────────────────────────────────────
def _done(n: int) -> list[dict]:
    """`n` completed loaded sessions from the block start, one a day (the sequence's input)."""
    from common.pacific_time import shift_day_key

    return [
        {
            "date": shift_day_key("2026-09-24", i),
            "source_workout_id": f"w{i}",
            # #4312: a lower, an upper and (#5069) a shoulder set, so each generic session matches the role it takes
            "exercises": [
                {"name": "Linear Leg Press", "sets": [{"type": "normal", "weight_kg": 90, "reps": 5}]},
                {"name": "Bench Press (Barbell)", "sets": [{"type": "normal", "weight_kg": 60, "reps": 5}]},
                {"name": "Lateral Raise (Dumbbell)", "sets": [{"type": "normal", "weight_kg": 10, "reps": 12}]},
            ],
        }
        for i in range(n)
    ]


def _generate(day: str, **kw):
    kw.setdefault("block_workouts", [])
    with patch.object(routine_generator, "_load_note_indexes", return_value=({}, {}, {}, {})):
        return routine_generator.generate_routines(routine_generator.GeneratorInputs(target_date=day, **kw))


def test_generator_builds_the_committed_lower_heavy_as_the_first_v04_session():
    ideal, floor = _generate("2026-09-25")
    assert ideal.archetype == "lower" and ideal.variant == "ideal"
    assert ideal.title.startswith("LOWER-HEAVY — W1")
    assert [(b.movement_key, len(b.sets)) for b in ideal.exercises] == COMMITTED_LOWER_HEAVY
    assert ideal.exercises[0].sets[0].rep_range_start == 4 and ideal.exercises[0].sets[0].rep_range_end == 6
    assert ideal.inputs_snapshot["calendar"]["week"] == 1 and ideal.inputs_snapshot["calendar"]["session_role"] == LH
    assert ideal.inputs_snapshot["session_prescription"]["hevy_folder"] == "Lower"
    # the Minimum Viable Session: anchors only, top set + one back-off, machine-only (no bar on a
    # tired day — the #4080 exemption is OFF at skill_ceiling 1): leg press, hip thrust
    assert floor.variant == "floor" and [(b.movement_key, len(b.sets)) for b in floor.exercises] == [
        ("leg_press", 2),
        ("machine_hip_thrust", 2),
    ]


def test_generator_builds_each_role_in_order():
    """Before the cut-over (2026-10-19) the v0.4 order, from lower-heavy (history — #4147)."""
    got = [_generate("2026-10-10", block_workouts=_done(n))[0] for n in range(4)]
    assert [(r.archetype, r.inputs_snapshot["calendar"]["session_role"]) for r in got] == [
        ("lower", LH),
        ("upper", UV),
        ("lower", LV),
        ("upper", UH),
    ]
    assert [b.movement_key for b in got[3].exercises][:3] == [  # #5162: no press on upper-heavy
        "barbell_bench_press",
        "machine_row",
        "lat_pulldown",
    ]
    assert "machine_shoulder_press" not in [b.movement_key for b in got[3].exercises]


def test_generator_builds_the_five_day_order_after_the_cut_over_and_the_fifth_role():
    """From the cut-over the charter's order continues from the role after the last v0.4 session: 25 daily sessions
    09-24..10-18 end on lower-heavy (v0.4 index 24), so the next five are shoulders+arms, upper-volume, lower-volume,
    upper-heavy, lower-heavy — and the fifth role is built from its own template, filed in the Upper folder."""
    from common.pacific_time import shift_day_key

    def rows(n_after: int) -> list[dict]:
        out = _done(25)
        for i in range(n_after):
            out.append({**_done(1)[0], "date": shift_day_key("2026-10-19", i), "source_workout_id": f"post{i}"})
        return out

    got = [_generate("2026-10-30", block_workouts=rows(k))[0] for k in range(5)]
    assert [r.inputs_snapshot["calendar"]["session_role"] for r in got] == [SA, UV, LV, UH, LH]
    sa = got[0]
    assert sa.archetype == "upper" and sa.title.startswith("SHOULDERS+ARMS — W")
    assert sa.inputs_snapshot["session_prescription"]["hevy_folder"] == "Upper"
    assert [b.movement_key for b in sa.exercises] == [
        "machine_shoulder_press",
        "db_lateral_raise",
        "face_pull",
        "db_curl",
        "cable_tricep_pushdown",
        "farmers_carry",  # #5318 (owner ruling B3): the farmer's carry replaced the dumbbell shrug
    ]
    shape = sa.inputs_snapshot["session_shape"]
    assert shape["lifting_minutes"] <= shape["lifting_cap_minutes"] == 75 and shape["cardio_blocks"] == []


def test_mutation_control_without_the_sequence_the_nominal_grid_answers():
    from training import session_sequence

    with patch.object(session_sequence, "next_session", return_value=None):
        routines = _generate("2026-09-25")  # a Friday: the five-day nominal grid's upper-volume
    assert routines[0].inputs_snapshot["calendar"]["session_role"] == UV, "the weekday answers only when the sequence does not"


def test_generator_back_offs_sit_10_percent_under_the_ramped_top_set():
    lb = 0.45359237
    tid = CATALOG["movements"]["squat_barbell"]["hevy_template_id_hint"]
    history = {tid: [{"date": "2026-09-20", "top_weight_kg": 200 * lb, "sets": [{"weight_kg": 200 * lb, "reps": 8}]}]}
    weights = {"2026-09-20": 316.0, "2026-09-25": 315.0}
    with patch.object(routine_generator, "_load_note_indexes", return_value=(history, weights, {}, {})):
        ideal = routine_generator.generate_routines(routine_generator.GeneratorInputs(target_date="2026-09-25", block_workouts=[]))[0]
    squat = ideal.exercises[0]
    assert squat.movement_key == "squat_barbell"
    top = _ws(squat)[0].weight_kg
    # week 1 of the entry ramp would be 60 % of the band e1RM (#4388): 200 lb x (1 + 8/30) x 0.60 -> 150 lb.
    # #4408: 200 lb x 8 five days earlier, at this band, this cycle, no layoff, clears the 4–6 top set's rep
    # floor — nothing to re-enter from, so the achieved load is HELD and the ramp never goes under it
    assert top == pytest.approx(200 * 0.45359237)
    assert ideal.inputs_snapshot["load_floors"]["movements"]["squat_barbell"]["ramp"]["hold"]["applies"] is True
    assert [s.weight_kg for s in _ws(squat)[1:]] == [routine_generator._floor_half_kg(top * 0.9)] * 2
    assert any("back-offs at 90%" in r for r in ideal.rationale)
    lo, hi = effort_ceilings.class_bands()[effort_ceilings.COMPOUNDS]
    assert f"HEAVY: 1 top set of 4–6 @ RPE {lo:g}–{hi:g}" in squat.notes  # #5058: the charter's band in the cue


def test_generator_deload_week_holds_loads_and_cuts_sets():
    # #5070 (owner ruling 2026-10-18): no scheduled deload — it applies only on a record of his word. A word starting
    # 11-04 covers 7 days; index 44 (11-07, week 7) is lower-heavy inside it. Without the record the same day is whole.
    word = [{"start_date": "2026-11-04", "days": 7, "sets_pct": -40, "words": "deload this week"}]
    with patch("training.deload_word.load_records_failsoft", return_value=[]):
        whole = _generate("2026-11-07", block_workouts=_done(44))[0]
    assert "DELOAD" not in whole.title and sum(len(b.sets) for b in whole.exercises) == 14
    with patch("training.deload_word.load_records_failsoft", return_value=word):
        ideal = _generate("2026-11-07", block_workouts=_done(44))[0]
    assert "DELOAD" in ideal.title and ideal.title.startswith("LOWER-HEAVY — W7")
    assert any("deload: sets 14 -> 8" in r for r in ideal.rationale)
    assert sum(len(b.sets) for b in ideal.exercises) == 8


def test_red_recovery_drops_accessories_not_anchors():
    ideal = _generate("2026-09-25", recovery_tier="red")[0]
    assert [b.movement_key for b in ideal.exercises] == ["squat_barbell", "romanian_deadlift_barbell"]


@pytest.mark.parametrize("archetype, folder", [("upper", "Upper"), ("lower", "Lower")])
def test_hevy_folders_are_upper_and_lower(archetype, folder):
    from mcp.hevy_routine_commit_report import FOLDER_BY_ARCHETYPE, folder_title_for

    assert FOLDER_BY_ARCHETYPE[archetype] == program_structure.HEVY_FOLDERS[archetype] == folder
    n = 0 if archetype == "lower" else 1  # the sequence starts at lower-heavy; one done -> upper-volume
    ideal = _generate("2026-09-26", block_workouts=_done(n))[0]
    assert ideal.archetype == archetype and folder_title_for(ideal) == folder
    # v0.3 history still files where it always did
    assert FOLDER_BY_ARCHETYPE["full"] == program_v03.HEVY_FOLDER == "Full Body"


def test_folder_is_created_if_absent_at_first_commit_never_before():
    """The folder is find-or-create at commit (`ensure_folder`). No live write happens here —
    the write client is mocked — and nothing in the generator or the planner creates one."""
    from mcp import hevy_routine_commit_report as rep

    created: list[str] = []
    with (
        patch("training.hevy_write_client.list_all_folders", return_value=([{"id": 1, "title": "Legs"}], False)),
        patch("training.hevy_write_client.create_folder", side_effect=lambda t: created.append(t) or {"routine_folder": {"id": 9}}),
    ):
        fid, miss = rep.ensure_folder("Lower")
    assert (fid, miss, created) == (9, None, ["Lower"])
    with (
        patch("training.hevy_write_client.list_all_folders", return_value=([{"id": 7, "title": "Lower"}], False)),
        patch("training.hevy_write_client.create_folder", side_effect=AssertionError("must not create a duplicate")),
    ):
        assert rep.ensure_folder("Lower") == (7, None)


def test_title_type_label_and_why_note():
    from training.routine_title import format_title, format_why_note

    ideal = _generate("2026-09-25")[0]
    assert format_title(ideal, {"phase": "Foundation", "type_count_in_phase": 1, "all_time_count": 5}) == "Foundation - Lower - 1 - 5"
    assert format_why_note(ideal).startswith("Lower heavy")


# ── 3. v0.2 / inactive is untouched ──────────────────────────────────────────
def test_inactive_program_never_consults_the_sequence():
    from training import session_sequence

    live = json.loads((REPO / "config" / "training_week.json").read_text())
    thursday = live["schedule"]["3"]["archetype"]
    with (
        patch.object(program_structure, "ACTIVE", False),
        patch.object(session_sequence, "next_session", side_effect=AssertionError("sequence read under an inactive program")),
    ):
        routines = _generate("2026-09-24")
    assert routines[0].archetype == thursday
    assert all("session_role" not in r for r in routines[0].rationale)


def test_inactive_program_plan_session_says_the_json_grid_decides():
    from training import plan_engine

    with patch.object(program_structure, "ACTIVE", False):
        block = plan_engine.constraint_block(date="2026-09-24")
    assert block["session"]["source"] == "json" and block["session"]["archetype"] is None


# ── 4. plan_next_session through the MCP handler ─────────────────────────────
def _stage1_patches():
    return [
        patch("mcp.tools_benchmark.tool_get_benchmark", return_value={"applicable": False, "reason": "offline"}),
        patch("mcp.tools_health.tool_get_readiness_score", return_value={"score": 60}),
        patch("mcp.tools_training.tool_get_acwr_status", return_value={"zone": "safe"}),
        patch("mcp.tools_strength.tool_get_muscle_volume", return_value={"muscle_volume": {}}),
        patch("mcp.tools_plan._walking_volume_last_7d", return_value=None),
        patch("mcp.tools_plan._protein_days_7d", return_value=(None, None)),
        patch("mcp.tools_plan._gather_performed_evidence", return_value=None),
        patch("mcp.tools_plan._rotation_window", return_value=None),
        patch("mcp.tools_plan._block_workouts", return_value=[]),  # #4110: no session completed yet
        patch("mcp.tools_plan._pain_dismissals", return_value=[]),
        patch("mcp.tools_plan._nutrition_critics_block", return_value={"verdicts": []}),
        patch("mcp.tools_plan._load_anchor_indexes", return_value=({}, {})),
        patch("training.training_notes.training_notes_health", side_effect=RuntimeError("offline")),
        patch("ai.bedrock_client.invoke", side_effect=AssertionError("no model in stage 1")),
    ]


def test_plan_next_session_through_the_mcp_handler_serves_lower_heavy_first():
    from mcp import handler as h

    with ExitStack() as st:
        for cm in _stage1_patches():
            st.enter_context(cm)
        st.enter_context(patch.object(h, "_emit_tool_metric"))
        st.enter_context(patch.object(h, "_audit_tool_call"))
        resp = h.handle_tools_call({"name": "plan_next_session", "arguments": {"target_date": "2026-09-25"}})
    out = json.loads(resp["content"][0]["text"])
    assert out["target_date"] == "2026-09-25", out
    session = out["constraint_block"]["session"]
    assert session["source"] == "session_sequence" and session["position_label"] == "week 1 · session 1 of 4 · lower-heavy"
    assert (session["archetype"], session["session_role"], session["week"], session["block"], session["deload"]) == (
        "lower",
        LH,
        1,
        1,
        False,
    )
    assert session["program_version"] == "0.4"  # a pre-cut-over session is a v0.4 session (#5069)
    rx = session["prescription"]
    assert rx["hevy_folder"] == "Lower"
    assert [(e["pattern"], e["intensity"], e["movement_key"]) for e in rx["exposures"] if e["kind"] == "anchor"] == [
        ("squat", "heavy", "squat_barbell"),
        ("hinge", "moderate", "romanian_deadlift_barbell"),
    ]
    assert rx["total_sets"] == 14
    assert out["constraint_block"]["program"]["program_version"] == "1.0"


# ── 5. #4409: within a block a slot keeps the variant he performed in it ────────
# The block-1 Hevy record as it sits in DynamoDB (the raw per-workout rows `load_block_workouts`
# returns, read-only 2026-09-28): 09-24 lower-heavy (squat, RDL), 09-25 upper-volume (barbell bench,
# DB row 90 lb x 8, DB shoulder press 52.5 lb x 10, pulldown), 09-26 a Flex complement, 09-28
# lower-volume (trap bar, squat). The 09-23 row is pre-block. Next in order on 09-29: upper-heavy.
def _wire_rows() -> list[dict]:
    from decimal import Decimal

    path = REPO / "tests" / "fixtures" / "training_block1_wire_4408_4409" / "hevy_rows.json"
    return json.loads(path.read_text(), parse_float=Decimal, parse_int=Decimal)["items"]


def _performed(day="2026-09-29"):
    from training import in_block_variant

    return in_block_variant.performed_in_block(_wire_rows(), CATALOG["movements"], day)


# #5162 (owner ruling 2026-10-23) moved the overhead press off upper-heavy. The 09-29 replays below are of the session that
# was served WITH it, and what they hold is the in-block variant resolver (#4409) and the one template resolver (#4431), not
# the week's design — so they run against upper-heavy's template as it stood then (`served_templates_5162`). The current
# template is held above.
@pytest.fixture
def pre_5162_upper_heavy():
    from served_templates_5162 import pre_5162_upper_days

    with pre_5162_upper_days():
        yield


def test_5162_the_current_upper_heavy_carries_no_press_and_the_press_keeps_its_in_block_variant_on_shoulders_arms():
    """The live counterpart of the replays below: upper-heavy has no press slot, and the shoulders+arms press keeps the
    DB press he pressed in-block (09-25), through the performed record's template id."""
    assert "overhead_press" not in {e["pattern"] for e in _rx(UH, in_block=_performed())["exposures"]}
    press = next(e for e in _rx(SA, in_block=_performed())["exposures"] if e["pattern"] == "overhead_press")
    assert press["movement_key"] == "db_shoulder_press" and press["in_block"]["kept"] is True
    assert press["template_id"] == "878CD1D0" and len(press["sets"]) == 1


@pytest.mark.usefixtures("pre_5162_upper_heavy")
def test_4409_the_0929_upper_heavy_keeps_the_in_block_db_row_and_db_press():
    """The reported swap: the 09-29 pre-draft served `machine_row` (last done May 2025) and
    `machine_shoulder_press` (2023) although the block's own sessions rowed and pressed the DB
    versions. The planner's session (the seam the nightly pre-draft and stage 1 read) keeps them."""
    out = program_structure.planned_session("2026-09-29", block_workouts=_wire_rows(), catalog_movements=CATALOG["movements"])
    assert out["session_role"] == UH and out["week"] == 1
    ex = {e["pattern"]: e for e in out["prescription"]["exposures"] if e["kind"] == "anchor"}
    assert ex["row"]["movement_key"] == "one_arm_db_row"
    assert ex["overhead_press"]["movement_key"] == "db_shoulder_press"
    for pattern in ("row", "overhead_press"):
        ib = ex[pattern]["in_block"]
        assert ib["kept"] is True and ib["date"] == "2026-09-25" and ib["role"] == UV and ib["basis"] == "same_pattern"
    # the title-only catalog entry (ADR-069) takes its template id from the performed WIRE record
    assert ex["overhead_press"]["template_id"] == "878CD1D0" and not CATALOG["movements"]["db_shoulder_press"].get("hevy_template_id_hint")
    # slots whose in-block variant IS the catalog default are unchanged
    assert ex["bench"]["movement_key"] == "barbell_bench_press" and ex["vertical_pull"]["movement_key"] == "lat_pulldown"


@pytest.mark.usefixtures("pre_5162_upper_heavy")
def test_4409_mutation_control_without_the_block_record_the_catalog_default_swaps_them_back():
    """What the 09-29 draft did: the resolver without the in-block record picks the first listed
    key — the machines with years-old anchors. So the assertion above reds without the fix."""
    ex = {e["pattern"]: e["movement_key"] for e in _rx(UH)["exposures"] if e["kind"] == "anchor"}
    assert ex["row"] == "machine_row" and ex["overhead_press"] == "machine_shoulder_press"
    assert "in_block" not in next(e for e in _rx(UH)["exposures"] if e["pattern"] == "row")


def test_4409_the_same_role_slot_wins_over_the_pattern_most_recently_performed():
    """Rule 1 before rule 2: lower-heavy's moderate hinge stays the RDL it was on 09-24 although
    the trap bar was pulled more recently (09-28, lower-volume) — and lower-volume keeps the trap
    bar. A heavy pull never takes the owner's RDL-as-moderate-hinge slot (#4147)."""
    perf = _performed()
    lh = {e["pattern"]: e for e in _rx(LH, in_block=perf)["exposures"] if e["kind"] == "anchor"}
    assert lh["hinge"]["movement_key"] == "romanian_deadlift_barbell" and lh["hinge"]["in_block"]["basis"] == "same_role"
    lv = {e["pattern"]: e for e in _rx(LV, in_block=perf)["exposures"] if e["kind"] == "anchor"}
    assert lv["hinge"]["movement_key"] == "deadlift_trap_bar" and lv["hinge"]["in_block"]["role"] == LV


def test_4409_a_variant_change_inside_the_block_is_only_the_listed_swap_and_says_so():
    """Block lock: when the in-block variant is unreachable for THIS session (the Minimum Viable
    Session's tier-1 ceiling, no anchor exemption) the slot takes the pattern's next LISTED key and
    the exposure records the change — never a silent swap, never a key outside the pattern."""
    rx = _rx(UH, in_block=_performed(), skill_ceiling=1, anchor_exempt=False)
    row = next(e for e in rx["exposures"] if e["pattern"] == "row")
    assert row["movement_key"] == "machine_row" and row["movement_key"] in program_structure.ANCHORS["row"]["catalog_keys"]
    assert row["in_block"]["performed"] == "one_arm_db_row" and row["in_block"]["kept"] is False
    assert "skill_tier 2 > ceiling 1" in row["resolution_note"]
    # no in-block performance at all -> the catalog order, unchanged
    assert _rx(UH, in_block=[]) == _rx(UH)


@pytest.mark.usefixtures("pre_5162_upper_heavy")
def test_4409_the_generator_draft_keeps_the_db_row_and_press_with_a_current_load():
    """End to end through `generate_routines` on the wire record: the 09-29 upper-heavy draft
    carries the DB row at 90 lb (the 09-25 load, held by #4408 at the 4–6 top set's rep floor) and
    the DB press at 52.5 lb (09-25, 10 reps >= the 6–10 floor) — loaded through the performed
    record's template id, where the catalog entry carries none."""
    from training import exercise_history

    class _Table:
        def query(self, **_kw):
            return {"Items": _wire_rows()}

    with patch.object(exercise_history, "_table", return_value=_Table()):
        history, _cardio = exercise_history.load_history_indexes(lookback_days=30, today=__import__("datetime").date(2026, 9, 28))
    weights = {"2026-09-23": 315.4, "2026-09-24": 313.7, "2026-09-25": 313.1, "2026-09-28": 313.7}
    with patch.object(routine_generator, "_load_note_indexes", return_value=(history, weights, {}, {})):
        ideal = routine_generator.generate_routines(
            routine_generator.GeneratorInputs(target_date="2026-09-29", block_workouts=_wire_rows())
        )[0]
    assert ideal.title.startswith("UPPER-HEAVY — W1")
    blocks = {b.movement_key: b for b in ideal.exercises}
    assert "machine_row" not in blocks and "machine_shoulder_press" not in blocks
    lb = 0.45359237
    assert blocks["one_arm_db_row"].sets[0].weight_kg == pytest.approx(90 * lb, abs=0.01)
    assert blocks["db_shoulder_press"].sets[0].weight_kg == pytest.approx(52.5 * lb, abs=0.01)
    floors = ideal.inputs_snapshot["load_floors"]["movements"]
    assert floors["db_shoulder_press"]["template_id"] == "878CD1D0" and floors["db_shoulder_press"]["fallback"] is None
    # the snapshot's catalog hash is the catalog's own — the wire id is an overlay, not an edit
    assert ideal.inputs_snapshot["catalog_hash"] == routine_generator._config_hash(CATALOG)


# ── 6. #4431: generator, planner and chat gate resolve a slot's template through ONE resolver ──
# Before #4431 the chat commit gate read the catalog hint only, so `db_shoulder_press` (title-only on
# purpose, ADR-069) — which the generator floors from its in-block performed record since #4409 —
# reached the gate as `no_template_id`: no floor, nothing refused, two numbers for one set.
def _wire_history_4431():
    import datetime

    from training import exercise_history

    class _Table:
        def query(self, **_kw):
            return {"Items": _wire_rows()}

    with patch.object(exercise_history, "_table", return_value=_Table()):
        history, _cardio = exercise_history.load_history_indexes(lookback_days=30, today=datetime.date(2026, 9, 28))
    return history, {"2026-09-23": 315.4, "2026-09-24": 313.7, "2026-09-25": 313.1, "2026-09-28": 313.7}


def _three_resolutions_4431(day="2026-09-29"):
    """{role: {movement_key: (generator, planner, gate)}} for every movement of every week-1 session
    on the wire record — each path read exactly where it loads from."""
    from training import in_block_variant

    from mcp import hevy_prescription_gate as gate

    movements = CATALOG["movements"]
    perf = _performed(day)
    with patch("mcp.plan_hevy_windows._block_workouts", return_value=_wire_rows()):
        gate_perf, status = gate._in_block_performed(day, movements)
    assert status["status"] == "read" and gate_perf == perf
    out: dict[str, dict[str, tuple]] = {}
    for role in program_structure.SESSION_SEQUENCE["session_roles"]:
        rx = _rx(role, in_block=perf)
        load_movements = in_block_variant.with_performed_template_ids(CATALOG, rx, perf)["movements"]  # the generator's floor pass
        out[role] = {}
        for e in rx["exposures"]:
            key = e["movement_key"]
            if not key:
                continue
            generator = (load_movements.get(key) or {}).get("hevy_template_id_hint")
            planner = (movements.get(key) or {}).get("hevy_template_id_hint") or e.get("template_id")  # annotate_prescription's order
            out[role][key] = (generator, planner, gate._template_id_for(key, movements, gate_perf)[0])
    return out


@pytest.mark.usefixtures("pre_5162_upper_heavy")
def test_4431_generator_planner_and_gate_resolve_every_week1_movement_identically():
    res = _three_resolutions_4431()
    disagree = {f"{role}/{k}": v for role, rows in res.items() for k, v in rows.items() if len(set(v)) != 1}
    assert not disagree, f"the three paths disagree on a slot's template: {disagree}"
    assert sum(len(r) for r in res.values()) >= 16  # the whole week, not a sample
    assert res[UH]["db_shoulder_press"] == ("878CD1D0",) * 3


@pytest.mark.usefixtures("pre_5162_upper_heavy")
def test_4431_db_shoulder_press_generator_floor_equals_gate_floor_and_the_mutation_reds():
    """The chat gate derives the same floor the generator wrote for the in-block DB press — and the
    pre-#4431 catalog-only resolver (the mutation) leaves the gate with `no_template_id`."""
    import types

    from mcp import hevy_prescription_gate as gate

    history, weights = _wire_history_4431()
    rows = _wire_rows()
    with patch.object(routine_generator, "_load_note_indexes", return_value=(history, weights, {}, {})):
        ideal = routine_generator.generate_routines(routine_generator.GeneratorInputs(target_date="2026-09-29", block_workouts=rows))[0]
    gen = ideal.inputs_snapshot["load_floors"]["movements"]["db_shoulder_press"]
    assert gen["floor_kg"] and gen["template_id"] == "878CD1D0"
    custom = types.SimpleNamespace(
        variant="ideal", target_date="2026-09-29", notes="", inputs_snapshot={"authored": "custom"}, exercises=ideal.exercises
    )

    def _gate_row():
        with patch("mcp.plan_hevy_windows._block_workouts", return_value=rows):
            g = gate.prescription_gate(custom, movements=CATALOG["movements"], history_index=history, weight_index=weights)
        return g, g["load_floors"]["movements"]["db_shoulder_press"]

    g, row = _gate_row()
    assert g["verdict"] == "clean", g["audit"]
    assert row["floor_kg"] == gen["floor_kg"] and row["template_id"] == gen["template_id"]
    assert row["template_id_source"].startswith("in-block performed record 2026-09-25")
    # mutation control: the gate's pre-#4431 resolver (catalog hint only) — no template id, no floor
    catalog_only = lambda key, movements, performed=None: (  # noqa: E731
        ((movements or {}).get(key) or {}).get("hevy_template_id_hint"),
        "catalog_hint",
    )
    with patch.object(gate, "_template_id_for", side_effect=catalog_only):
        _g, mutated = _gate_row()
    assert mutated["status"] == "no_template_id" and not mutated["floor_kg"]


# ── #4503 OD4 + OD5 + OD8a (owner rulings 2026-09-30): the 20/24 ceiling, the `bonus` role, the gain rule ──
def _blocks(base: int, bonus: int = 0) -> list:
    from training.routine_ir import ExerciseBlock, Set

    out = [ExerciseBlock(movement_key=f"m{i}", sets=[Set()] * 2, rationale_tag="anchor:row:heavy") for i in range(base // 2)]
    return out + [ExerciseBlock(movement_key=f"b{i}", sets=[Set()], rationale_tag="bonus:fly:accessory") for i in range(bonus)]


def test_4503_od4_the_ceiling_is_20_base_24_with_green_and_the_bonus_role_is_graded_apart():
    from training import green_block

    assert program_structure.week_grid()["session_set_ceiling"] == green_block.BASE_SESSION_SET_CEILING == 20
    assert green_block.GREEN_SESSION_SET_CEILING == 24 and green_block.GREEN_BONUS_SETS_PER_SESSION == {"upper": 4, "lower": 3}
    assert green_block.GREEN_BONUS_SETS_PER_WEEK == 12
    assert owner_redlines.REDLINES["lifting_sessions_per_wk"]["total_hard_sets_wk"] == [60, 75]
    assert green_block.session_set_check(_blocks(20), "upper") == []
    assert green_block.session_set_check(_blocks(20, 4), "upper") == []  # 24 with 🟢
    assert green_block.session_set_check(_blocks(20, 4), "lower") == ["🟢 sets 4 exceed the lower session's +3 (OD4)"]
    assert green_block.session_set_check(_blocks(22), "upper")[0].startswith("base sets 22 exceed the session ceiling 20")
    over = green_block.session_set_check(_blocks(18, 7), "upper")
    assert any("total sets 25 exceed the 🟢 session ceiling 24" in w for w in over)


def test_4503_od4_mutation_control_without_the_bonus_role_a_green_session_reads_over_the_base_ceiling():
    from training import green_block

    with patch.object(green_block, "BONUS_KIND", "not-bonus"):
        assert green_block.session_set_check(_blocks(20, 4), "upper")[0].startswith("base sets 24 exceed")


def test_4503_od8a_no_template_carries_a_green_tail_so_the_ceiling_adds_no_set():
    """The ceiling is a bound, not a target: no template carries a `bonus` exposure. OD8a's LOCK clause is gone — ruling 6
    (2026-10-18, #5069) lifted the v0.4 lock — so the constant that named it is retired, and the fact stays tested."""
    from training import green_block

    assert not hasattr(green_block, "GREEN_TAIL_ON_LOCKED_TEMPLATES")
    for role in program_structure.SESSION_TEMPLATES:
        rx = _rx(role)
        assert not [e for e in rx["exposures"] if e["kind"] == green_block.BONUS_KIND], role
    assert {r: _rx(r)["total_sets"] for r in program_structure.SESSION_TEMPLATES} == {UH: 17, LH: 14, SA: 13, UV: 17, LV: 14}


def test_4503_od5_gains_are_rep_triggered_with_no_nutrition_clause_and_protein_gates_only_green():
    from training import load_progression  # #5052: the gain rule moved to the charter; the redline is a pointer

    assert owner_redlines.REDLINES["lifting_sessions_per_wk"]["gain_rule"]["source"].endswith("progression.gain_rule")
    g = load_progression.gain_rule()
    assert g["kind"] == "double_progression" and g["consecutive_same_type_exposures"] == 2 and g["nutrition_clause"] is None
    assert "veto only" in g["rpe_role"] and "offered_when" not in g
    assert not any("kcal" in c or "intake" in c for c in g["refused_when"])
    from training import green_block

    prot = next(t for t in owner_redlines.TRIPWIRES if t["id"] == "protein_floor_missed")
    assert green_block.GREEN_BLOCKED_BY == (prot["id"],)
    assert "🟢 block is withheld" in prot["action"] and "NOT blocked" in prot["action"] and "does not grow" not in prot["action"]


def test_4503_od4_the_volume_ceiling_tripwire_reads_the_v05_session_ceiling_not_v04s_18():
    """The `volume_ceiling` tripwire the planner embeds still said `sets_per_session: 18` and "the generator's own
    `session_set_ceiling` (18)" after OD4 moved the generator to 20 base / 24 with 🟢 — a leftover v0.4 number. It now
    reads `green_block`'s constants, so the tripwire and the generator cannot disagree again."""
    from training import green_block

    ceiling = next(t for t in owner_redlines.TRIPWIRES if t["id"] == "volume_ceiling")
    grid_ceiling = program_structure.week_grid()["session_set_ceiling"]
    assert ceiling["threshold"]["sets_per_session"] == green_block.BASE_SESSION_SET_CEILING == grid_ceiling == 20
    assert ceiling["threshold"]["sets_per_session_with_green"] == green_block.GREEN_SESSION_SET_CEILING == 24
    assert "(18)" not in ceiling["note"] and "green_block" in ceiling["note"]
