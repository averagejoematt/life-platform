"""tests/test_subtract_only_autoregulation_behavior.py — subtract-only autoregulation (#3927).

THE DEFECT, verbatim off the wire. `USER#matthew#ROUTINE#a5980a24…` VERSION#current,
target 2026-09-19, `incline_db_press`:

    sets:  3 x 34.01946820767298 kg (75 lb) x 8
    notes: "Ceiling RPE 9. If set 1 is <=7.5 go 80 - you had 80x8 on 09-11 leading with incline."

He had put 36.28743275485118 kg (80 lb) x 8 @ RPE9 on the board on 09-11, at a bodyweight
inside the same 10-lb band. The routine prescribed less, and put the number it already
knew he could lift behind a condition he had to evaluate himself, mid-set, at 5am. The
owner's ruling (2026-09-19, §7 of the owner-private TRAINING_CALIBRATION.md): autoregulation
is SUBTRACT-ONLY — down on the day, never up, and progression is never his job to trigger.

EVERY number, load, weigh-in and prose sample in this file comes from
`tests/fixtures/subtract_only_3927/`, which was copied off live DynamoDB on 2026-09-19 —
not off the issue body, and not off a comment. The fixture files name their own source.

THE MUTATION PROOFS. Four properties are what this file exists to hold:
  • the floor is the BAND-MATCHED best (`test_band_*`) — a floor drawn from a different
    bodyweight era is a different claim;
  • absence stays absence (`test_*_unweighed*`, `test_*_no_history*`) — a session whose
    bodyweight cannot be resolved does not raise the floor, and a movement with no
    band-matched history gets NO floor rather than a guessed one;
  • the detector fires on the real specimen AND stays silent on the real down-branches
    (`test_down_branches_*`) — a detector that flags every conditional would be deleted
    within a week;
  • the two specimens replayed produce 80 lb or more, and the RAW specimens do not
    (`test_specimen_*`) — the control that keeps the replay from passing vacuously.
"""

from __future__ import annotations

import json
import os

import pytest
from training.routine_generator import (
    DETRAINING_DISCOUNT_PCT_RANGE,
    apply_prescription_floor,
    band_matched_best,
    prescription_floor,
    render_floor_cue,
)

from mcp.recovery_authoring import (
    SUBTRACT_ONLY_RULE,
    audit_prescription,
    derive_training_context,
    find_conditional_up,
    render_session_block,
)

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "subtract_only_3927")
TEMPLATE_ID = "07B38369"  # Incline Bench Press (Dumbbell)

# The two loads at the centre of the specimen, exactly as DynamoDB holds them.
EIGHTY_LB_KG = 36.28743275485118
SEVENTY_FIVE_LB_KG = 34.01946820767298
# What the ROUTINE record actually holds for the same 75 lb: the IR serializer rounds
# floats to 4 dp on the way into DynamoDB (`common.numeric.floats_to_decimal`), so the
# PRESCRIPTION and the PERFORMANCE of one dumbbell are not the same float. Comparisons
# are against the value each side really carries, never a tidied-up one.
SPECIMEN_PRESCRIBED_KG = 34.0194
# cable_tricep_pushdown's band-matched best (72.5 lb on 2026-09-11) — the generator path.
PUSHDOWN_FLOOR_KG = 32.88548593408388


def _load(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
        return json.load(f)


def _history_index():
    """The fixture projected into the EXACT shape `exercise_history.load_recent_history`
    returns: {template_id: [{date, sets:[{weight_kg, reps}], top_weight_kg}]}, most recent
    first, `reps` coerced to int the way its `_to_int` does and the `rpe`/`type` keys the
    real loader does not carry dropped. The fake has to behave like the live loader or the
    test proves nothing about the live path.
    """
    raw = _load("hevy_sessions_by_template_2026-09.json")
    index = {}
    for tid, sessions in raw["by_template_id"].items():
        rows = [
            {
                "date": s["date"],
                "sets": [{"weight_kg": float(x["weight_kg"]), "reps": int(x["reps"])} for x in s["sets"]],
                "top_weight_kg": float(s["top_weight_kg"]),
            }
            for s in sessions
        ]
        rows.sort(key=lambda s: s["date"], reverse=True)
        index[tid] = rows
    return index


def _weight_index():
    """`load_bodyweight_index`'s shape: {YYYY-MM-DD: weight_lbs}."""
    return dict(_load("withings_weighins_2026-09.json")["weigh_ins"])


def _specimen(name):
    return _load(name)


def _incline_block(spec):
    return next(ex for ex in spec["exercises"] if ex["movement_key"] == "incline_db_press")


# ══════════════════════════════════════════════════════════════════════════════
# The fixture is the wire
# ══════════════════════════════════════════════════════════════════════════════
def test_the_fixture_carries_the_loader_shape_not_a_convenient_one():
    idx = _history_index()[TEMPLATE_ID]
    assert {k for s in idx for k in s} == {"date", "sets", "top_weight_kg"}
    assert all(isinstance(x["reps"], int) for s in idx for x in s["sets"])
    assert [s["date"] for s in idx] == sorted((s["date"] for s in idx), reverse=True)
    # The two loads this issue is about are really in there.
    by_date = {s["date"]: s["top_weight_kg"] for s in idx}
    assert by_date["2026-09-11"] == EIGHTY_LB_KG
    assert by_date["2026-09-14"] == SEVENTY_FIVE_LB_KG


# ══════════════════════════════════════════════════════════════════════════════
# Box 1 — the load derivation reads the band-matched best from the Hevy partition
# ══════════════════════════════════════════════════════════════════════════════
def test_band_matched_best_is_the_eighty_he_already_did():
    best = band_matched_best(TEMPLATE_ID, _history_index(), _weight_index(), 315.63, as_of="2026-09-19")
    assert best["status"] == "ok"
    assert best["band"] == "310-319"
    assert best["best_kg"] == EIGHTY_LB_KG
    assert best["basis"]["date"] == "2026-09-11"
    assert best["basis"]["reps"] == [8, 8]  # the two 80-lb sets of that session
    assert best["basis"]["bodyweight_lb"] == 319.7  # the 09-12 weigh-in, one day out


def test_a_session_in_a_different_bodyweight_band_is_a_different_claim():
    """At 327.34 lb the band is 320-329, and only the 09-07 session sits in it. The 80 lb
    of 09-11 is NOT available as a floor there — it was lifted 8 lb lighter."""
    best = band_matched_best(TEMPLATE_ID, _history_index(), _weight_index(), 327.34, as_of="2026-09-19")
    assert best["band"] == "320-329"
    assert best["basis"]["date"] == "2026-09-07"
    assert best["best_kg"] == pytest.approx(29.483539113316585)
    assert best["sessions_in_band"] == 1
    assert best["sessions_other_band"] == 2  # 09-11 and 09-14; 09-19 is excluded by as_of


def test_a_session_with_no_weigh_in_in_tolerance_does_not_raise_the_floor():
    """ADR-104. No bodyweight is interpolated to make a session countable; the sessions
    that could not be placed are counted and reported by name."""
    best = band_matched_best(TEMPLATE_ID, _history_index(), {}, 315.63, as_of="2026-09-19")
    assert best["status"] == "no_band_matched_history"
    assert best["best_kg"] is None
    assert best["sessions_unweighed"] == 3  # every session as_of 09-19, none of them placeable


def test_no_current_bodyweight_yields_no_floor_rather_than_a_guess():
    best = band_matched_best(TEMPLATE_ID, _history_index(), _weight_index(), None)
    assert best["status"] == "no_current_bodyweight"
    assert best["best_kg"] is None


def test_a_movement_with_no_history_gets_no_floor():
    best = band_matched_best("NOT-A-TEMPLATE", _history_index(), _weight_index(), 315.63)
    assert best["status"] == "no_history"
    assert best["best_kg"] is None


def test_a_routine_cannot_cite_a_session_that_has_not_happened_yet():
    """`as_of` is the target date. Authoring on the night of 09-13 for 09-15 may not reach
    the 09-14 or 09-19 sessions — the floor has to be derivable at authoring time."""
    best = band_matched_best(TEMPLATE_ID, _history_index(), _weight_index(), 318.91, as_of="2026-09-12")
    assert best["basis"]["date"] == "2026-09-11"
    assert best["sessions_in_band"] == 1


# ══════════════════════════════════════════════════════════════════════════════
# Box 1 — "never emits a lower prescription without a documented layoff reason"
# ══════════════════════════════════════════════════════════════════════════════
def test_with_no_layoff_the_floor_is_exactly_the_achieved_load():
    floor = prescription_floor(TEMPLATE_ID, _history_index(), _weight_index(), 315.63, days_since_last_workout=1, as_of="2026-09-19")
    assert floor["floor_kg"] == EIGHTY_LB_KG  # exact, not rounded — 36.0 would be 79.4 lb
    assert floor["discount_pct"] == 0
    assert floor["layoff_reason"] is None


def test_a_layoff_is_the_only_path_below_an_achieved_load_and_it_says_so():
    floor = prescription_floor(
        TEMPLATE_ID, _history_index(), _weight_index(), 315.63, days_since_last_workout=9, layoff_days=7, as_of="2026-09-19"
    )
    deepest = DETRAINING_DISCOUNT_PCT_RANGE[1]
    assert floor["discount_pct"] == deepest
    assert floor["floor_kg"] < EIGHTY_LB_KG
    assert floor["floor_kg"] == pytest.approx(int(EIGHTY_LB_KG * (100 - deepest) / 100.0 * 2) / 2)
    assert "detraining" in floor["layoff_reason"]
    assert "9d since the last logged session" in floor["layoff_reason"]


def test_one_day_short_of_the_layoff_threshold_gets_no_discount():
    """The mutation proof for the threshold itself: 6d is not a layoff, 7d is."""
    six = prescription_floor(TEMPLATE_ID, _history_index(), _weight_index(), 315.63, days_since_last_workout=6, layoff_days=7)
    seven = prescription_floor(TEMPLATE_ID, _history_index(), _weight_index(), 315.63, days_since_last_workout=7, layoff_days=7)
    assert six["discount_pct"] == 0 and six["floor_kg"] == EIGHTY_LB_KG
    assert seven["discount_pct"] == DETRAINING_DISCOUNT_PCT_RANGE[1]


def test_the_floor_cue_is_factual_and_carries_no_condition():
    floor = prescription_floor(TEMPLATE_ID, _history_index(), _weight_index(), 315.63, as_of="2026-09-19")
    cue = render_floor_cue(floor)
    assert "Floor 80 lb" in cue
    assert "2026-09-11" in cue and "319.7 lb" in cue
    assert find_conditional_up(cue) == []


# ══════════════════════════════════════════════════════════════════════════════
# Box 2 — the structural detector for the conditional-UP pattern
# ══════════════════════════════════════════════════════════════════════════════
# Every string below is transcribed from a live routine or a committed routine spec.
_LIVE_CONDITIONAL_UPS = [
    # ROUTINE#a5980a24 (2026-09-19) incline_db_press — the specimen this issue names
    "Ceiling RPE 9. If set 1 is <=7.5 go 80 - you had 80x8 on 09-11 leading with incline.",
    # ROUTINE#a5980a24 (2026-09-19) barbell_bench_press
    "Ceiling RPE 9. 205x5 read 9.5 on 09-14. If 205 lands <=8.5, add one more set at 205. Do not chase 215.",
    # ROUTINE#2db74166 (authored 2026-09-14, target 09-15) barbell_bench_press
    "Warm-ups then 3 working. HOLD 185x5 — do not add load. GREEN only: a 2nd set at 185. If set 3 is RPE9+, that's the session.",
    # docs/coaching/routines/push/foundation_push_w1.md
    "PERFORMANCE-GATED: if set 1 moves at 4+ RIR, climb to 165-175 for the rest.",
    "GREEN 67-100: climb bench toward 175 if set 1 is 4+ RIR, last set of incline + pushdown to 1-2 RIR.",
    # docs/coaching/routines/pull/foundation_pull_w4.md — the condition and the payload
    # are the same phrase, so it needs its own pattern
    "65 only if set 1 was <=8 (GREEN). Pause, external rotation at the end.",
]


@pytest.mark.parametrize("text", _LIVE_CONDITIONAL_UPS)
def test_the_detector_fires_on_every_live_conditional_up(text):
    hits = find_conditional_up(text)
    assert hits, f"conditional-UP went undetected: {text!r}"
    assert hits[0]["clause"] and hits[0]["pattern"]


def test_the_specimen_clause_is_matched_on_its_own_terms():
    """The decimal in '<=7.5' is why clauses split on sentence boundaries and not on a
    bare period: splitting there tore 'if' off 'go 80' and made the detector blind to the
    one sentence it exists for."""
    hits = find_conditional_up(_LIVE_CONDITIONAL_UPS[0])
    assert hits[0]["pattern"] == "go_to_number"
    assert hits[0]["match"] == "go 80"
    assert "If set 1 is <=7.5" in hits[0]["clause"]


# Live prose that is NOT a violation. A detector that reds on these would take the
# sanctioned down-branch with it.
_LIVE_CLEAN = [
    "Drop to 40x10 if set 1 exceeds it.",  # ROUTINE#a5980a24, db_shoulder_press
    "HOLD 185x5 — do not add load.",  # a prohibition, not a branch
    "If set 3 is RPE9+, that's the session.",  # a stop condition
    "75lb because you're second in the queue now. RPE 8 cap. RED: drop.",  # 'second in the queue'
    "RPE 8 cap. 120 lb anchored on 3 Sept (120x12,12,10).",
    "Seated, back supported. 40lb — RPE fell 8.5>7.0 across four sets at 35lb on 11 Sep. RED: 2x10 @35lb.",
    "Level 10 flat, 40 min, hold 115-120 bpm. Bike not treadmill today - toe.",
    "Last: 36.5kg 8/8/7 (11 Sep)",  # exercise_history's rendered cue
]


@pytest.mark.parametrize("text", _LIVE_CLEAN)
def test_down_branches_and_prohibitions_are_not_flagged(text):
    assert find_conditional_up(text) == [], f"false positive on sanctioned prose: {text!r}"


def test_the_emitted_session_block_carries_the_rule_and_no_conditional_up():
    """The block this module writes into every adaptive routine is itself emitted prose,
    so it is held to the same bar it enforces."""
    block = render_session_block(derive_training_context(["2026-09-18"], "moderate", "2026-09-19"))
    assert SUBTRACT_ONLY_RULE in block
    assert find_conditional_up(block) == []


# ══════════════════════════════════════════════════════════════════════════════
# Box 3 — the two specimens replayed produce 80 lb or higher
# ══════════════════════════════════════════════════════════════════════════════
_SPECIMENS = [
    # (fixture, the weigh-in nearest its target date, the date authoring could see up to)
    ("routine_2026-09-14_push_target_09-15.json", 318.91, "2026-09-15"),
    ("routine_2026-09-19_push.json", 315.63, "2026-09-19"),
]


@pytest.mark.parametrize("fixture,current_lb,target_date", _SPECIMENS)
def test_the_raw_specimen_prescribes_below_the_achieved_load(fixture, current_lb, target_date):
    """The control. Without it the replay below could pass because the specimen was
    already compliant, and the test would prove nothing."""
    block = _incline_block(_specimen(fixture))
    assert [s["weight_kg"] for s in block["sets"]] == [SPECIMEN_PRESCRIBED_KG] * len(block["sets"])
    assert SPECIMEN_PRESCRIBED_KG < EIGHTY_LB_KG


@pytest.mark.parametrize("fixture,current_lb,target_date", _SPECIMENS)
def test_the_specimens_replayed_produce_eighty_or_higher(fixture, current_lb, target_date):
    block = _incline_block(_specimen(fixture))
    floor = prescription_floor(
        TEMPLATE_ID,
        _history_index(),
        _weight_index(),
        current_lb,
        days_since_last_workout=1,  # both specimens sit inside a training streak
        as_of=target_date,
    )
    corrections = apply_prescription_floor(block["sets"], floor)
    assert corrections, "the replay corrected nothing — the floor did not reach the sets"
    for s in block["sets"]:
        assert s["weight_kg"] >= EIGHTY_LB_KG, f"{fixture}: {s['weight_kg']}kg is still under 80 lb"


@pytest.mark.parametrize("fixture,current_lb,target_date", _SPECIMENS)
def test_the_auditor_reds_on_the_raw_specimen(fixture, current_lb, target_date):
    spec = _specimen(fixture)
    floor = prescription_floor(TEMPLATE_ID, _history_index(), _weight_index(), current_lb, as_of=target_date)
    result = audit_prescription(spec["exercises"], spec.get("notes", ""), floors={"incline_db_press": floor})
    assert result["ok"] is False
    assert result["floors_checked"] is True
    kinds = {v["kind"] for v in result["violations"]}
    assert "below_floor" in kinds
    below = [v for v in result["violations"] if v["kind"] == "below_floor"]
    assert all(v["where"] == "incline_db_press" for v in below)
    assert all(v["prescribed_kg"] == SPECIMEN_PRESCRIBED_KG for v in below)


def test_the_auditor_names_the_conditional_up_in_the_09_19_specimen():
    spec = _specimen("routine_2026-09-19_push.json")
    result = audit_prescription(spec["exercises"], spec.get("notes", ""))
    conds = [v for v in result["violations"] if v["kind"] == "conditional_up"]
    assert {v["where"] for v in conds} >= {"incline_db_press", "barbell_bench_press"}
    assert result["floors_checked"] is False  # an audit that could not see the floors says so


def test_a_clean_routine_passes_the_auditor():
    """The must-pass control: the auditor is not simply always red."""
    spec = _specimen("routine_2026-09-19_push.json")
    floor = prescription_floor(TEMPLATE_ID, _history_index(), _weight_index(), 315.63, as_of="2026-09-19")
    for ex in spec["exercises"]:
        ex["notes"] = "Ceiling RPE 9."
        apply_prescription_floor(ex["sets"], floor if ex["movement_key"] == "incline_db_press" else {})
    result = audit_prescription(
        spec["exercises"], "Push 4. Bike not treadmill: toe-off is what the ingrown nail hates.", floors={"incline_db_press": floor}
    )
    assert result["ok"] is True, result["violations"]


# ══════════════════════════════════════════════════════════════════════════════
# Box 2 — the same grep, over the IR the generator actually emits
# ══════════════════════════════════════════════════════════════════════════════
def _emitted_prose(ir):
    out = [ir.notes, *(ir.rationale or [])]
    for ex in ir.exercises:
        out.append(ex.notes)
    for br in ir.branches or []:
        out.append(br.cue)
        for ex in br.exercises:
            out.append(ex.notes)
    return [t for t in out if t]


@pytest.fixture()
def _generated(monkeypatch):
    """Drive the real generator with the live history/bodyweight fixtures in place of the
    two DynamoDB queries. Nothing else is stubbed — configs, selection and the caps are
    the production ones."""
    from training import exercise_history, routine_generator as rg

    monkeypatch.setattr(rg, "CONFIG_DIR", os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "config")))
    # #3700: one Query now returns (weighted, cardio); this fixture carries no cardio blocks.
    monkeypatch.setattr(exercise_history, "load_history_indexes", lambda **kw: (_history_index(), {}))
    monkeypatch.setattr(exercise_history, "load_bodyweight_index", lambda **kw: _weight_index())
    return rg.generate_routines(
        rg.GeneratorInputs(
            # A real day of the live week whose archetype ('upper') selects movements the
            # fixture holds history for — cable_tricep_pushdown has band-matched sessions,
            # db_curl has history only OUTSIDE the band, and the machine movements have
            # none. All three absence states are exercised by one generation.
            target_date="2026-09-14",
            recovery_tier="green",
            acwr_flag="safe",
            volume_7d={},
            z2_minutes_7d=120,
            days_since_last_workout=1,
        )
    )


def test_the_generated_ir_carries_no_conditional_up_anywhere(_generated):
    """Box 2's grep, aimed where the box aims it: the EMITTED notes and IR. Deliberately
    not at docs — `.claude/skills/daily-debrief/SKILL.md` quotes the banned sentences as
    examples of what never to write, and a grep that could not tell the two apart would
    red on the rule that forbids them."""
    for ir in _generated:
        for text in _emitted_prose(ir):
            assert find_conditional_up(text) == [], f"{ir.variant}: {text!r}"


def test_the_generator_records_what_the_floor_pass_did(_generated):
    ideal = next(ir for ir in _generated if ir.variant == "ideal")
    floors = ideal.inputs_snapshot["load_floors"]
    assert floors["status"] == "applied"
    assert floors["current_bodyweight_lb"] == 318.9  # the 09-15 weigh-in, one day out
    assert floors["band"] == "310-319"
    assert floors["rule"] == SUBTRACT_ONLY_RULE
    # Every block is accounted for, including the ones with no floor and WHY.
    assert set(floors["movements"]) == {ex.movement_key for ex in ideal.exercises}
    assert all(m["status"] for m in floors["movements"].values())


def test_a_generated_block_with_band_matched_history_is_prescribed_at_the_floor(_generated):
    """cable_tricep_pushdown: 32.88548593408388 kg (72.5 lb) on 09-11 at 319.7 lb, inside
    the band. The generator emits that load rather than leaving the number to him."""
    ideal = next(ir for ir in _generated if ir.variant == "ideal")
    priced = {k: m for k, m in ideal.inputs_snapshot["load_floors"]["movements"].items() if m["status"] == "ok"}
    assert set(priced) == {"cable_tricep_pushdown"}
    for key, m in priced.items():
        block = next(ex for ex in ideal.exercises if ex.movement_key == key)
        assert m["floor_kg"] == PUSHDOWN_FLOOR_KG
        assert m["basis"]["date"] == "2026-09-11"
        assert all(s.weight_kg == PUSHDOWN_FLOOR_KG for s in block.sets)
        assert "Floor 72.5 lb" in block.notes


def test_a_block_with_no_band_matched_history_is_left_unloaded_not_guessed(_generated):
    """db_curl's only logged session (09-08) sits at 327.3 lb — a band he has left. The
    generator prescribes NO load rather than carrying a heavier-bodyweight number forward,
    and the snapshot says which absence it was."""
    ideal = next(ir for ir in _generated if ir.variant == "ideal")
    movements = ideal.inputs_snapshot["load_floors"]["movements"]
    assert movements["db_curl"]["status"] == "no_band_matched_history"
    assert {m["status"] for k, m in movements.items() if k != "cable_tricep_pushdown"} <= {
        "no_band_matched_history",
        "no_history",
        "no_template_id",
    }
    for key, m in movements.items():
        if m["status"] == "ok":
            continue
        block = next(ex for ex in ideal.exercises if ex.movement_key == key)
        assert m["floor_kg"] is None
        assert all(s.weight_kg is None for s in block.sets), f"{key} got a load with status {m['status']}"


def test_warmups_and_non_load_sets_are_never_stamped_with_a_floor():
    from training.routine_ir import Set

    sets = [
        Set(type="warmup", reps=10),
        Set(type="normal", duration_seconds=2400),
        Set(type="normal", reps=8, weight_kg=SPECIMEN_PRESCRIBED_KG),
    ]
    floor = prescription_floor(TEMPLATE_ID, _history_index(), _weight_index(), 315.63, as_of="2026-09-19")
    apply_prescription_floor(sets, floor)
    assert sets[0].weight_kg is None
    assert sets[1].weight_kg is None
    assert sets[2].weight_kg == EIGHTY_LB_KG


def test_a_set_already_at_or_above_the_floor_is_untouched():
    from training.routine_ir import Set

    sets = [Set(type="normal", reps=8, weight_kg=EIGHTY_LB_KG), Set(type="normal", reps=5, weight_kg=45.0)]
    floor = prescription_floor(TEMPLATE_ID, _history_index(), _weight_index(), 315.63, as_of="2026-09-19")
    corrections = apply_prescription_floor(sets, floor)
    assert corrections == []
    assert [s.weight_kg for s in sets] == [EIGHTY_LB_KG, 45.0]


# ══════════════════════════════════════════════════════════════════════════════
# Box 4 — the daily-debrief skill carries the rule verbatim
# ══════════════════════════════════════════════════════════════════════════════
def test_the_daily_debrief_skill_carries_the_subtract_only_rule_verbatim():
    """Verbatim modulo whitespace only — the doc wraps the sentence across markdown
    blockquote lines, so both sides are whitespace-collapsed before comparing. Any change
    to the wording in `routine_generator.SUBTRACT_ONLY_RULE` reds this until the skill the
    night-before authoring session actually reads has been updated with it."""
    path = os.path.join(os.path.dirname(__file__), "..", ".claude", "skills", "daily-debrief", "SKILL.md")
    with open(path, encoding="utf-8") as f:
        body = f.read()
    flat = " ".join(body.replace(">", " ").split())
    assert " ".join(SUBTRACT_ONLY_RULE.split()) in flat
