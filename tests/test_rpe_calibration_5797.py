"""tests/test_rpe_calibration_5797.py — the RPE calibration set (#5797, owner ruling 2026-11-11).

The ruling: calibration sets ONLY on non-barbell anchors (lat pulldown, one-arm DB row, machine press), and the set stops
at the FIRST SLOW REP, never failure (his standing no-grinding rule). Each guarantee below has a must-fail control:

  * never a barbell — a barbell lift LISTED in the charter's `eligible` is still refused (the refusal is not config);
  * never to failure — the note line names no failure / AMRAP and the calibration set stays a NORMAL Hevy set;
  * every 3rd exposure only, and never on a deload, a red day, a capped exposure, a lift with no PREVIOUS or a one-set lift;
  * the e1RM moves only once n >= the charter's minimum AND the interval excludes zero (n 5 moves nothing);
  * the line passes the Hevy note linter (L1–L15) on a freshly rendered routine, with the session block intact.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from training import hevy_note_grammar, load_ramp, rpe_calibration
from training.routine_ir import ExerciseBlock, Set

LINE = rpe_calibration.NOTE_LINE
CATALOG = {
    "lat_pulldown": {"equipment": "cable", "hevy_template_id_hint": "PULLDOWN"},
    "one_arm_db_row": {"equipment": "dumbbell", "hevy_template_id_hint": "DBROW"},
    "barbell_bench_press": {"equipment": "barbell", "hevy_template_id_hint": "BENCH"},
}
DAY = "2026-11-20"


def _p(**over):
    p = dict(rpe_calibration.params())
    p.update(over)
    return p


def _block(key: str, n_sets: int = 2) -> ExerciseBlock:
    return ExerciseBlock(
        movement_key=key,
        sets=[Set(type="normal", weight_kg=50.0, rep_range_start=8, rep_range_end=12) for _ in range(n_sets)],
        notes="RPE 8–9",
    )


def _history(tid: str, days: list[str]) -> dict:
    return {tid: [{"date": d, "sets": [{"weight_kg": 50.0, "reps": 10, "rpe": 8.0}]} for d in days]}


def _mark(blocks, *, history=None, deload=False, red_day=False, caps=False, previous=True, layoff=False, p=None):
    keys = [b.movement_key for b in blocks]
    record = {
        "lift_notes": {k: {"note": "RPE 8–9", "layoff_return": layoff} for k in keys},
        "previous_loads": {k: {"date": "2026-11-15"} for k in keys} if previous else {},
    }
    floors = {"movements": {k: {"ramp": {"exposure_caps": {"exposure": 2}}} for k in keys} if caps else {}}
    ctx = {"deload": deload, "red_day": red_day, "load_floors": floors, "history_index": history or {}, "target_date": DAY}
    with patch.object(rpe_calibration, "params", return_value=p or _p()):
        return rpe_calibration.mark_session(blocks, CATALOG, note_record=record, context=ctx)


# third exposure since 2026-11-11: two prior days on file
DUE = ["2026-11-12", "2026-11-16"]


# ── the charter and the line ─────────────────────────────────────────────────────────────────────────────────────


def test_the_charter_lists_the_owners_non_barbell_anchors_and_no_barbell():
    from training.logging_conventions import catalog_movements

    p = rpe_calibration.params()
    assert p["every_nth_exposure"] == 3 and p["stop_rule"] == "first_slow_rep"
    assert {"lat_pulldown", "one_arm_db_row"} <= set(p["eligible"]) and any("machine" in k and "press" in k for k in p["eligible"])
    cat = catalog_movements()
    for key in p["eligible"]:
        assert key in cat, key
        assert cat[key]["equipment"] != "barbell", key
        assert rpe_calibration.eligible(key, cat[key])[0], key
    assert "barbell" in p["never_equipment"] and "no grinding" in p["standing_rule"]


def test_the_line_is_one_phone_line_never_says_failure_and_lints_clean():
    assert hevy_note_grammar.phone_lines(LINE) == 1
    low = LINE.lower()
    for word in ("failure", "fail", "amrap", "max", "grind", "rir", "until you can"):
        assert word not in low, word
    assert "first slow rep" in low and "rpe" in low
    import re

    for pat, label, case in hevy_note_grammar.BANNED:
        assert not re.search(pat, LINE, 0 if case else re.I), label
    assert not hevy_note_grammar.REASON_RE.match(LINE)  # not read as a reason for a load move (lint L4)


# ── never a barbell: the must-fail control ───────────────────────────────────────────────────────────────────────


def test_a_barbell_lift_is_refused_even_when_the_charter_lists_it():
    p = _p(eligible=["barbell_bench_press", "lat_pulldown"], never_equipment=[])
    ok, why = rpe_calibration.eligible("barbell_bench_press", CATALOG["barbell_bench_press"], p)
    assert not ok and "barbell" in why
    out = _mark(
        [_block("barbell_bench_press"), _block("lat_pulldown")], history={**_history("BENCH", DUE), **_history("PULLDOWN", DUE)}, p=p
    )
    assert [m["movement_key"] for m in out["marks"]] == ["lat_pulldown"]
    assert "barbell" in out["skipped"]["barbell_bench_press"]


def test_mutation_control_without_the_hard_refusal_the_listed_barbell_would_be_marked():
    """Proves the test above can fail: drop ALWAYS_REFUSED and a charter that lists the bench calibrates it."""
    p = _p(eligible=["barbell_bench_press"], never_equipment=[])
    with patch.object(rpe_calibration, "ALWAYS_REFUSED", frozenset()):
        out = _mark([_block("barbell_bench_press")], history=_history("BENCH", DUE), p=p)
    assert [m["movement_key"] for m in out["marks"]] == ["barbell_bench_press"]


# ── the schedule and its exclusions ──────────────────────────────────────────────────────────────────────────────


def test_the_third_exposure_carries_the_line_on_its_last_set_and_the_set_stays_normal():
    block = _block("lat_pulldown")
    out = _mark([block], history=_history("PULLDOWN", DUE))
    assert out["marks"] == [{"movement_key": "lat_pulldown", "template_id": "PULLDOWN", "exposure": 3, "target_reps": 12, "set": 2}]
    assert block.notes.splitlines() == ["RPE 8–9", LINE]
    assert [s.type for s in block.sets] == ["normal", "normal"]  # never Hevy's `failure` set type


@pytest.mark.parametrize("days", [["2026-11-12"], ["2026-11-12", "2026-11-14", "2026-11-16"], ["2026-11-01", "2026-11-12"]])
def test_exposures_that_are_not_a_multiple_of_three_carry_nothing(days):
    """Exposure 2, exposure 4, and exposure 2 when a pre-ruling day is not counted."""
    block = _block("lat_pulldown")
    out = _mark([block], history=_history("PULLDOWN", days))
    assert out["marks"] == [] and LINE not in block.notes


@pytest.mark.parametrize(
    "kwargs, why",
    [
        ({"deload": True}, "deload"),
        ({"red_day": True}, "red day"),
        ({"caps": True}, "capped"),
        ({"layoff": True}, "first session back"),
        ({"previous": False}, "no PREVIOUS"),
    ],
)
def test_negative_controls_carry_no_calibration_set(kwargs, why):
    block = _block("lat_pulldown")
    out = _mark([block], history=_history("PULLDOWN", DUE), **kwargs)
    assert out["marks"] == [] and LINE not in block.notes
    assert why in out["skipped"]["lat_pulldown"]


def test_a_one_set_exposure_is_never_calibrated_so_the_top_set_stays_a_rating():
    block = _block("lat_pulldown", n_sets=1)
    out = _mark([block], history=_history("PULLDOWN", DUE))
    assert out["marks"] == [] and "working sets" in out["skipped"]["lat_pulldown"]


def test_an_ineligible_movement_carries_nothing():
    block = ExerciseBlock(movement_key="db_curl", sets=[Set(type="normal", rep_range_end=12)] * 2, notes="RPE 8–9")
    out = _mark([block], history=_history("CURL", DUE))
    assert out["marks"] == [] and LINE not in block.notes


def test_a_full_note_defers_the_set_rather_than_overrun_the_budget():
    block = _block("one_arm_db_row")
    block.notes = "RPE 8–9\nVolume day: chase 12.\nBreathe out on the pull, brace before each rep."  # 4 phone lines
    out = _mark([ExerciseBlock(movement_key="cardio_first"), block], history=_history("DBROW", DUE))
    assert out["marks"] == [] and "deferred" in out["skipped"]["one_arm_db_row"]


# ── the pair, the join, the report ───────────────────────────────────────────────────────────────────────────────


def test_the_pair_reads_the_last_set_as_prediction_and_reps_to_the_first_slow_rep():
    p = _p(rir_at_first_slow_rep=2)
    mark = {"target_reps": 12, "exposure": 3}
    sets = [{"weight_kg": 50.0, "reps": 12, "rpe": 8.0}, {"weight_kg": 50.0, "reps": 13, "rpe": 8.0}]
    got = rpe_calibration.pair(mark, sets, p)
    # predicted RIR 10 - 8 = 2; actual 13 + 2 - 12 = 3; error +1 (more in reserve than he predicted)
    assert (got["status"], got["predicted_rir"], got["actual_rir"], got["error"], got["set_index"]) == ("paired", 2.0, 3.0, 1.0, 1)
    assert rpe_calibration.pair(mark, [{"weight_kg": 50.0, "reps": 13, "rpe": None}], p)["status"] == "no_prediction"


def test_the_history_join_is_by_hevy_routine_id_and_template():
    rows = [
        {"pk": "x", "hevy_routine_id": "H1", "rpe_calibration": [{"template_id": "PULLDOWN", "target_reps": 12, "exposure": 3}]},
        {"hevy_routine_id": "", "rpe_calibration": [{"template_id": "PULLDOWN", "target_reps": 12}]},  # never pushed
    ]
    marks = rpe_calibration.marks_from_index_rows(rows)
    assert list(marks) == ["H1"]
    index = {
        "PULLDOWN": [
            {"date": "2026-11-16", "hevy_routine_id": "H1", "sets": [{"weight_kg": 50.0, "reps": 13, "rpe": 8.0}]},
            {"date": "2026-11-12", "hevy_routine_id": "H0", "sets": [{"weight_kg": 50.0, "reps": 10, "rpe": 8.0}]},
        ],
        "DBROW": [{"date": "2026-11-16", "hevy_routine_id": "H1", "sets": [{"weight_kg": 30.0, "reps": 10, "rpe": 8.0}]}],
    }
    assert rpe_calibration.annotate(index, marks) == 1
    assert index["PULLDOWN"][0]["calibration"]["status"] == "paired" and "calibration" not in index["PULLDOWN"][1]
    assert "calibration" not in index["DBROW"][0]


def test_a_failed_routine_index_read_is_no_pairs_never_an_error():
    class Broken:
        def query(self, **_kw):
            raise RuntimeError("no table")

    assert rpe_calibration.load_marks_failsoft(Broken(), "2026-01-01") == {}


def test_the_t_quantile_matches_the_table():
    # Student's t, 0.90 quantile (the 80 % two-sided interval): df 5 = 1.476, df 10 = 1.372, df 30 = 1.310
    for df, want in ((5, 1.476), (10, 1.372), (30, 1.310)):
        assert rpe_calibration._t_quantile(0.9, df) == pytest.approx(want, abs=0.01)


def test_descriptive_until_n_reaches_the_minimum_then_an_interval():
    p = _p(min_n=6, interval_pct=80)
    five = rpe_calibration.summarize([1.0, 1.5, 1.0, 2.0, 1.0], p)
    assert five["state"] == "descriptive" and five["interval"] is None and not five["adjusts"] and five["n"] == 5
    six = rpe_calibration.summarize([1.0, 1.5, 1.0, 2.0, 1.0, 1.5], p)
    assert six["state"] == "estimated" and six["adjusts"] and six["interval"][0] > 0 and six["n"] == 6
    noise = rpe_calibration.summarize([2.0, -2.0, 1.0, -1.0, 0.5, -0.5], p)
    assert noise["state"] == "estimated" and not noise["adjusts"] and noise["interval"][0] < 0 < noise["interval"][1]
    assert rpe_calibration.summarize([], p)["state"] == "absent"


def test_the_report_is_per_movement_and_pooled_with_n_stated():
    index = {
        "PULLDOWN": [{"date": "2026-11-16", "calibration": {"status": "paired", "error": 1.0}}],
        "DBROW": [{"date": "2026-11-16", "calibration": {"status": "paired", "error": -1.0}}],
    }
    rep = rpe_calibration.report(index, CATALOG, _p(eligible=["lat_pulldown", "one_arm_db_row"]))
    assert rep["by_movement"]["lat_pulldown"]["n"] == 1 and rep["by_movement"]["one_arm_db_row"]["mean_error_rir"] == -1.0
    assert rep["pooled"]["n"] == 2 and rep["pooled"]["state"] == "descriptive"


# ── the e1RM adjustment (load_ramp.achieved_hold) ────────────────────────────────────────────────────────────────


def _hold_history(errors: list[float], rpe: float = 8.0) -> dict:
    """One normal session he holds from (60 kg x 8 @ `rpe`) plus `errors` paired calibration sessions at the same load,
    whose last set (the calibration set: 12 reps, RPE 7 = a PREDICTION) would hold the full 60 kg if it were read."""
    rows = [{"date": "2026-11-10", "sets": [{"weight_kg": 60.0, "reps": 8, "rpe": rpe}]}]
    for i, e in enumerate(errors):
        rows.append(
            {
                "date": f"2026-11-{12 + i:02d}",
                "sets": [{"weight_kg": 60.0, "reps": 8, "rpe": rpe}, {"weight_kg": 60.0, "reps": 12, "rpe": 7.0}],
                "calibration": {"status": "paired", "error": e, "set_index": 1},
            }
        )
    return {"PULLDOWN": rows}


def _hold(history: dict) -> dict:
    slot = {"min_reps": 6, "target_reps": 8, "rpe_ceiling": 9, "intensity": "moderate"}
    weights = {d: 300.0 for d in (f"2026-11-{x:02d}" for x in range(1, 30))}
    with patch.object(load_ramp, "anchor_discount", return_value=(0, {"applies": False})):
        return load_ramp.achieved_hold("PULLDOWN", history, weights, 300.0, slot=slot, as_of="2026-11-30")


def test_the_hold_never_reads_the_calibration_set_itself():
    """60 x 8 @ RPE 10 holds under 60 kg for an 8-rep slot at RPE <= 9; the calibration set (60 x 12, its RPE 7 a
    prediction) would hold the full 60 if it were read as a rating."""
    best = _hold(_hold_history([0.0], rpe=10.0))
    assert best["held_kg"] < 60.0 and best["rpe"] == 10.0 and best["rpe_basis"] == "rpe_adjusted"


def test_the_e1rm_moves_only_past_n_min_with_an_interval_excluding_zero():
    p = rpe_calibration.params()
    under = _hold(_hold_history([-1.0] * (int(p["min_n"]) - 1)))
    assert under["rpe_basis"] == "rpe_adjusted" and under["rpe_calibration"]["rir_offset"] == 0.0
    assert under["rpe_calibration"]["state"] == "descriptive"
    at = _hold(_hold_history([-1.0, -1.5, -1.0, -1.5, -1.0, -1.5][: max(int(p["min_n"]), 2)]))
    assert at["rpe_basis"] == "rpe_adjusted_calibrated" and at["rpe_calibration"]["rir_offset"] < 0
    # he had LESS in reserve than he predicted: the corrected e1RM is lower, so the hold is no higher
    assert at["e1rm_rpe_adjusted"] < under["e1rm_rpe_adjusted"] and at["held_kg"] <= under["held_kg"]
    noisy = _hold(_hold_history([2.0, -2.0, 1.0, -1.0, 0.5, -0.5]))
    assert noisy["rpe_basis"] == "rpe_adjusted" and noisy["rpe_calibration"]["rir_offset"] == 0.0


# ── the routine index row carries the marks; the rendered routine lints clean ────────────────────────────────────


def test_the_index_row_carries_int_marks_even_from_a_deserialized_ir():
    from training import routine_repo
    from training.routine_ir import RoutineSpec

    ir = RoutineSpec(routine_id="r1", target_date=DAY, archetype="upper", variant="ideal", version=1)
    ir.inputs_snapshot = {
        "rpe_calibration": {
            "marks": [{"movement_key": "lat_pulldown", "template_id": "P", "exposure": 3.0, "target_reps": 12.0, "set": 2.0}]
        }
    }
    index_item = routine_repo.versioned_items(ir)[2]
    assert index_item["rpe_calibration"] == [
        {"movement_key": "lat_pulldown", "template_id": "P", "exposure": 3, "target_reps": 12, "set": 2}
    ]
    assert all(type(v) is int for v in index_item["rpe_calibration"][0].values() if not isinstance(v, str))


def test_a_rendered_routine_with_calibration_lines_lints_clean_with_one_session_block():
    """The 10-18 upper re-draft (the golden e2e render) with every exposure due: the pulldown and the one-arm row carry the
    line, the bench (barbell) does not, and the compiled wire body passes the linter with exactly one session block."""
    from test_hevy_notes_golden_e2e_5428 import _block_count, _compile, _with_cardio
    from test_warmup_sets_5049 import _redraft
    from training import hevy_note_lint, session_block

    with patch.object(rpe_calibration, "params", return_value=_p(every_nth_exposure=1, exposures_counted_from=None)):
        ir = _redraft()
    marked = {m["movement_key"] for m in ir.inputs_snapshot["rpe_calibration"]["marks"]}
    assert {"lat_pulldown", "one_arm_db_row"} <= marked and "barbell_bench_press" not in marked
    for b in ir.exercises:
        assert (LINE in (b.notes or "")) == (b.movement_key in marked), b.movement_key
    _with_cardio(ir)
    session_block.place_on_first(ir)
    body = _compile(ir)
    res = hevy_note_lint.lint_wire(body, ir)
    assert res.ok, res.lines()
    assert _block_count(body) == 1
    assert ir.inputs_snapshot["rpe_calibration"]["report"]["pooled"]["n"] == 0  # nothing performed yet: n stated, absent
