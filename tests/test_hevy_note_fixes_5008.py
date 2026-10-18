"""#5008 — four Hevy note / draft-rationale defects (owner brief 2026-10-18, C1-C4).

C1 a `change` that applied nothing prints FLAG, not CHANGE (live: muscle-defense 'hold: nothing to trim', 10-18).
C2 the cardio-HR join exists (#4412); this pins that its HR is RAW DATA ONLY — never a gate input (2026-10-10 AF constraint).
C3 the floor correction line names the rule that set the load (live: held from the 10-15 performance, printed '(the floor)').
C4 adherence counts WORKING sets on both sides (live 10-16: routine 4 warm-ups + 3 working = 'programmed 7') and the
   self-added-volume row names a `tmpl:` movement by its catalog key, not the Hevy title.
"""

from __future__ import annotations

from types import SimpleNamespace

from coach import critics, critics_aerobic
from health.adherence_calc import calculate_adherence
from training import routine_generator, self_added_volume
from training.routine_ir import ExerciseBlock, RoutineSpec, Set


# ── C1 ────────────────────────────────────────────────────────────────────────────────
def _ir_with(changes):
    verdicts = [
        {"critic": "muscle_defense", "verdict": "change", "metric": "protein_days_missed_7d", "value": 3, "reason": "hold"},
        {"critic": "joints_tendons", "verdict": "approve", "reason": "ok"},
    ]
    rec = {"engine": critics.CRITICS_VERSION, "ran_at": "2026-10-18T10:00:00+00:00", "verdicts": verdicts, "changes": changes}
    return SimpleNamespace(inputs_snapshot={"critics": rec})


_HOLD = {
    "critic": "muscle_defense",
    "field": "session.total_sets",
    "to": "hold",
    "applied": False,
    "why": "hold: no growth this week — the draft is not enlarged, nothing to trim automatically",
}


def test_c1_a_change_that_applied_nothing_prints_flag():
    ir = _ir_with([_HOLD])
    assert "- muscle-defense FLAG:" in critics.notes_block(ir)
    assert "muscle-defense CHANGE" not in critics.notes_block(ir)
    assert "muscle-defense flag" in critics.commit_status(ir)


def test_c1_control_an_applied_change_still_prints_change():
    ir = _ir_with([{**_HOLD, "applied": True, "why": None}])
    assert "- muscle-defense CHANGE:" in critics.notes_block(ir)
    assert "muscle-defense change" in critics.commit_status(ir)


def test_c1_control_no_change_record_keeps_the_stored_verdict():
    assert "- muscle-defense CHANGE:" in critics.notes_block(_ir_with([]))


def test_c1_any_applied_record_for_the_critic_keeps_change():
    ir = _ir_with([_HOLD, {**_HOLD, "field": "exercises[0].reps", "to": 8, "applied": True}])
    assert "- muscle-defense CHANGE:" in critics.notes_block(ir)


# ── C2 ────────────────────────────────────────────────────────────────────────────────
def _block(avg_hr):
    row = {"date": "2026-10-15", "source": "hevy", "modality": "cycling", "hr_state": "joined", "avg_hr": avg_hr, "hr_coverage": 0.9}
    return {"state": "read", "rows": [row], "totals": {"weight_bearing_hr_48h": 0.0, "walks_over_75_min_48h": 0}}


def test_c2_joined_cardio_hr_is_raw_data_never_a_gate():
    draft = {
        "archetype": "lower",
        "exercises": [{"idx": 0, "label": "Treadmill", "movement_key": "treadmill_incline", "duration_seconds": 1800}],
    }
    out = {}
    for hr in (95.0, 190.0):  # far under and far over the 120 cap
        numbers, flags, unknown = {}, [], []
        critics_aerobic.aerobic_flags(draft, _block(hr), numbers, flags, unknown)
        out[hr] = (flags, unknown)
        assert numbers["last_cardio_block_avg_hr"] == hr  # carried as a number...
    assert out[95.0] == out[190.0] and out[190.0][0] == []  # ...and the verdict inputs do not move with it


def test_c2_the_firing_swap_flag_is_identical_whatever_the_joined_hr_reads():
    """Mutation control: legs ARE loaded here, so the flag fires — and it must fire identically at 95 and 190 bpm."""
    draft = {
        "archetype": "lower",
        "exercises": [{"idx": 0, "label": "Treadmill", "movement_key": "treadmill_incline", "duration_seconds": 1800}],
    }
    seen = []
    for hr in (95.0, 190.0):
        block = _block(hr)
        block["totals"] = {"weight_bearing_hr_48h": 5.0, "walks_over_75_min_48h": 0}
        flags: list = []
        critics_aerobic.aerobic_flags(draft, block, {}, flags, [])
        seen.append([{k: v for k, v in f.items() if k != "reason"} for f in flags])
    assert seen[0] and seen[0] == seen[1]


# ── C3 ────────────────────────────────────────────────────────────────────────────────
def _sets():
    return [{"type": "normal", "weight_kg": None, "reps": 5}]


def test_c3_a_held_load_names_the_performance_it_was_held_from():
    floor = {
        "floor_kg": 83.9,
        "basis": {"date": "2026-10-15", "weight_kg": 83.9},
        "ramp": {"week": 6, "hold": {"applies": True, "achieved": {"date": "2026-10-15", "weight_kg": 83.9}}},
    }
    (line,) = routine_generator.apply_prescription_floor(_sets(), floor)
    assert "held from the 2026-10-15 performance" in line and line != "set 1: no load prescribed -> 185 lb (the floor)"


def test_c3_each_rule_names_itself():
    base = {"floor_kg": 83.9, "basis": {"date": "2026-10-01"}}
    ramp = {**base, "ramp": {"week": 6, "hold": {"applies": False}}}
    layoff = {**base, "layoff_reason": "x", "discount_pct": 15}
    labels = [routine_generator.floor_rule_label(f) for f in (ramp, layoff, base)]
    assert labels == [
        "week 6 ramp from the 2026-10-01 anchor",
        "best achieved load (2026-10-01) less the 15% layoff discount",
        "best achieved load, 2026-10-01",
    ]
    assert "below the floor: best achieved load" in routine_generator.apply_prescription_floor([{"weight_kg": 10.0}], base)[0]


def test_c3_the_load_itself_is_unchanged_by_the_wording():
    sets = _sets()
    routine_generator.apply_prescription_floor(sets, {"floor_kg": 83.9, "basis": {"date": "2026-10-15"}})
    assert sets[0]["weight_kg"] == 83.9


# ── C4 ────────────────────────────────────────────────────────────────────────────────
SQUAT_TID = "D04AC939"


def _squat_ir():
    sets = [Set(type="warmup") for _ in range(4)] + [Set() for _ in range(3)]
    return RoutineSpec(
        routine_id="r-5008", target_date="2026-10-16", archetype="lower", exercises=[ExerciseBlock(f"tmpl:{SQUAT_TID}", sets=sets)]
    )


def _performed(warm, working):
    sets = [{"type": "warmup"}] * warm + [{"type": "normal"}] * working
    return {"exercises": [{"exercise_" "template_id": SQUAT_TID, "sets": sets}]}


def test_c4_the_10_16_squat_stores_working_sets_beside_the_inclusive_counts():
    """The live row: routine 4 warm-up + 3 working, performed 4 warm-up + 5 working = programmed 7 / performed 9."""
    (m,) = calculate_adherence(_squat_ir(), _performed(4, 5))["movements"]
    assert (m["programmed_sets"], m["performed_sets"]) == (7, 9)  # #3714's inclusive counts, unchanged
    assert (m["programmed_working_sets"], m["performed_working_sets"]) == (3, 5)


def _week_of(movement):
    row = {
        "date": "2026-10-16",
        "title": "Foundation - Lower",
        "exercises": [],
        "adherence": {"status": "matched", "movements": [movement]},
    }
    return row


def test_c4_the_report_reads_working_sets_so_unprogrammed_warmups_are_not_added_volume():
    bucket = {"programmed_sets": 0, "performed_sets": 0, "added_sets": 0, "added": []}
    from datetime import date

    inclusive = {"movement_key": "barbell_bench_press", "programmed_sets": 3, "performed_sets": 9}  # the 10-15 bench, pre-#5008 row
    working = {**inclusive, "programmed_working_sets": 3, "performed_working_sets": 6}  # 3 warm-ups + 6 working
    self_added_volume._movement_adds({"movements": [inclusive]}, {}, date(2026, 10, 15), bucket)
    assert bucket["added_sets"] == 6  # control: the old row reads as it always did
    bucket2 = {"programmed_sets": 0, "performed_sets": 0, "added_sets": 0, "added": []}
    self_added_volume._movement_adds({"movements": [working]}, {}, date(2026, 10, 15), bucket2)
    assert (bucket2["programmed_sets"], bucket2["performed_sets"], bucket2["added_sets"]) == (3, 6, 3)


def test_c4_control_extra_working_sets_still_show_as_added():
    (m,) = calculate_adherence(_squat_ir(), _performed(0, 6))["movements"]
    assert m["performed_working_sets"] - m["programmed_working_sets"] == 3


def test_c4_a_row_names_every_movement_by_title_not_a_title_beside_a_key():
    row = {"exercises": [{"template_id": SQUAT_TID, "name": "Squat (Barbell)"}]}
    assert self_added_volume._label(f"tmpl:{SQUAT_TID}", row) == "Squat (Barbell)"
    assert self_added_volume._label("leg_press", row) == "Leg Press (Machine)"  # was the raw key beside the title
    assert self_added_volume._label(f"tmpl:{SQUAT_TID}", {}) == "Squat (Barbell)"  # catalog hint when the row lacks the exercise
    assert self_added_volume._label("not_a_catalog_key", row) == "not_a_catalog_key"
    assert self_added_volume._label("tmpl:ZZZZZZZZ", {}) == "tmpl:ZZZZZZZZ"
