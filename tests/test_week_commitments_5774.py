"""#5774 (epic #5770) — the charter concession ledger's weekly commitments are HARD stage-1 checks.

carries + kettlebell (dan_john), single-leg + corrective (athlean_x), stretch-position + rotation (nippard), the side/rear-delt
band (rp_israetel). A draft whose program week misses a blocking commitment fails stage 1 with the ledger line named and is
refused at commit. The week is what is SERVED: departures (draft_custom, the tired-day floor) count toward and
against it. The pools serve a kettlebell slot (the KB swing, entered via two KB-deadlift exposures). Kettlebell warns until the earlier of exercise-library approval or 2026-12-20 (owner ruling 2026-11-11);
stretch-position is report-only (no retirement named). Every test has a must-fail control beside it: the mutation that
removes the commitment from the week, and the verdict that names it.

Every date here is a fixed literal; nothing reads the clock, AWS or the library file (`week_floors.library` is pinned).
"""

from __future__ import annotations

import copy
import json
import os
import pathlib
import sys
from unittest.mock import patch

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "lambdas"))
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from training import (
    kb_entry as kb,
    panel_rubric,
    training_charter as tc,
    variant_rotation as vr,
    week_commitments as wc,
    week_floors as wf,
)  # noqa: E402
from training.block_model import block_weeks  # noqa: E402
from training.training_charter import charter_value  # noqa: E402

CATALOG = json.loads((REPO / "config" / "movement_catalog.json").read_text())["movements"]
BEFORE, ON = "2026-12-19", wf.KETTLEBELL_BLOCK_FROM
OWNER_NAMED = {
    "carries": {"dan_john", "athlean_x"},
    "kettlebell": {"dan_john"},
    "single_leg": {"athlean_x"},
    "corrective": {"athlean_x"},
    "stretch_position": {"nippard"},
    "rotation": {"nippard"},
    "side_rear_delt_band": {"rp_israetel"},
    "free_weight_compounds": {"dan_john"},  # owner ruling 2026-11-12 on #5857 (board rec 4)
}


@pytest.fixture(autouse=True)
def _bundled_charter_and_no_library(monkeypatch):
    monkeypatch.delenv(tc.PRIVATE_ENV_VAR, raising=False)
    monkeypatch.setattr(tc, "_from_s3", lambda key: None)
    monkeypatch.setattr(wf, "library", lambda path=None: None)  # no library on main: not approved
    tc.reset_cache()
    yield
    tc.reset_cache()


def _week(week: int = 7, date: str = "2026-11-12") -> dict:
    entry = {"week": week, "block": (week - 1) // block_weeks() + 1, "session_role": "lower_heavy", "date": date}
    return vr.plan(entry, CATALOG, rows=[], missing=[])


def _verdicts(out: dict) -> dict:
    return {r["id"]: r["verdict"] for r in out["rows"]}


def _ir(role, keys, *, rid="r", date="2026-11-12", action="draft_custom", status="active", variant="ideal", week=7, block=2, rot=None):
    """A routine IR: `keys` its exercises (3 working sets each); a floor draft carries no calendar (only session_role)."""
    from training.routine_ir import ExerciseBlock, RoutineSpec, Set

    snap = {"session_role": role} if variant == "floor" else {"calendar": {"block": block, "week": week, "session_role": role}}
    if rot is not None:
        snap["rotation"] = rot
    return RoutineSpec(
        routine_id=rid,
        target_date=date,
        archetype="lower",
        variant=variant,
        source_action=action,
        status=status,
        created_at=f"{date}T00:00:00Z",
        exercises=[ExerciseBlock(movement_key=k, sets=[Set(reps=8), Set(reps=8), Set(reps=8)]) for k in keys],
        inputs_snapshot=snap,
    )


def _days(*irs) -> dict:
    return {r.inputs_snapshot["calendar"]["session_role"]: {"keys": wc.routine_day(r, CATALOG), "source": r.routine_id} for r in irs}


# a lower_volume departure: the RDL and squat, no kettlebell slot
NO_KB_LOWER_VOLUME = ["romanian_deadlift_barbell", "squat_barbell", "calf_raise_machine", "machine_crunch"]


# ── the commitments are the ledger's own, and each blocking one names what it merges ─────────────────────────────────
def test_the_commitments_are_the_owner_named_set_and_each_phrase_is_the_charters_own():
    ledger = charter_value("concession_ledger")
    assert {c["id"]: set(c["seats"]) for c in wc.COMMITMENTS} == OWNER_NAMED
    problems = [
        f"{c['id']}: {phrase!r} not in {seat}'s in_return {ledger[seat]['in_return']!r}"
        for c in wc.COMMITMENTS
        for seat, phrase in c["seats"].items()
        if phrase not in ledger[seat]["in_return"]
    ]
    assert not problems, problems
    band = next(c for c in wc.COMMITMENTS if c["id"] == "side_rear_delt_band")["band"]
    assert charter_value(band) and len(charter_value(band)) == 2, band


def test_every_blocking_commitment_names_the_check_it_merges_and_report_only_says_why():
    for c in wc.COMMITMENTS:
        if c["enforce"]:
            assert c.get("merges") and "::" in c["merges"], c["id"]
        else:
            assert c.get("report_only"), c["id"]
    assert [c["id"] for c in wc.COMMITMENTS if not c["enforce"]] == ["stretch_position"]


# ── the current pools fill every commitment, kettlebell included (owner ruling 2026-11-11, item 1) ──────────────────
def test_every_program_week_on_the_current_pools_passes_on_and_after_the_kettlebell_date():
    fails = []
    for week in range(1, 19):
        for day in (BEFORE, ON):
            out = wc.evaluate(_week(week), CATALOG, on=day, library=None)
            if out["verdict"] != "pass":
                fails.append((week, day, out["blocking"]))
            v = _verdicts(out)
            assert v["kettlebell"] == "met" and v["stretch_position"] == "not_evaluated", (week, v)
            # block 1's first phase serves the committed template: the recorded gate makes single-leg a WARNING
            assert v["single_leg"] == ("warn" if week <= 3 else "met"), (week, v)
            assert all(v[k] == "met" for k in ("carries", "corrective", "rotation", "side_rear_delt_band")), (week, v)
    assert not fails, fails


# ── the kettlebell slot: KB deadlift x2, then the swing; set-neutral; measured exposures ─────────────────────────────
def _row(day, keys, template_id=kb.ENTRY_TEMPLATE_ID, tombstone=False):
    return {
        "date": day,
        "tombstone": tombstone,
        "exercises": [{"template_id": template_id, "name": kb.ENTRY_TITLE, "sets": [{"reps": 8, "weight_kg": 16}]}] if keys else [],
    }


def test_the_kettlebell_slot_serves_the_deadlift_for_two_logged_exposures_then_the_swing():
    entry = {"week": 7, "block": 2, "session_role": "lower_volume", "date": "2026-11-20"}
    rows = [_row("2025-04-13", True), _row("2026-11-10", True)]  # rows before the ruling never count
    assert kb.exposures(rows, "2026-11-20") == 0 and kb.exposures(None, "2026-11-20") is None
    assert vr.for_session(entry, CATALOG, read=False, block_workouts=rows)["variants"]["kettlebell_swing"] == kb.ENTRY
    one = rows + [_row("2026-11-12", True), _row("2026-11-13", True, tombstone=True), _row("2026-11-14", True, template_id="X")]
    assert kb.exposures(one, "2026-11-20") == 1
    two = one + [_row("2026-11-17", True), _row("2026-11-17", True)]  # one day counts once
    assert kb.exposures(two, "2026-11-20") == 2 and kb.exposures(two, "2026-11-17") == 1  # before the day only
    assert vr.for_session(entry, CATALOG, read=False, block_workouts=two)["variants"]["kettlebell_swing"] == kb.TARGET
    assert vr.for_session(entry, CATALOG, read=False, block_workouts=None)["variants"]["kettlebell_swing"] == kb.ENTRY  # never assumed
    # the planned session carries its own measured count (program_structure.planned_session stamps `kb_entry_exposures`)
    assert vr.for_session({**entry, "kb_entry_exposures": 2}, CATALOG, read=False)["variants"]["kettlebell_swing"] == kb.TARGET


def test_control_counting_rows_before_the_ruling_would_skip_the_entry():
    rows = [_row("2025-04-13", True), _row("2025-03-01", True)]
    with patch.object(kb, "COUNT_FROM", "2000-01-01"):
        assert kb.served(kb.exposures(rows, "2026-11-20")) == kb.TARGET  # the bug the date guard prevents
    assert kb.served(kb.exposures(rows, "2026-11-20")) == kb.ENTRY


def test_the_slot_is_set_neutral_capped_and_logs_under_a_real_template():
    from training import program_structure as ps

    cov = ps.volume_floor_coverage(CATALOG)
    assert (
        sum(len(e["sets"]) for r in ps.SPLIT_ROLES for e in ps.session_prescription_for_role(r, catalog_movements=CATALOG)["exposures"])
        == 75
    )
    assert cov["floors"]["core"]["sets"] == cov["floors"]["core"]["mev"] and all(f["meets_mev"] for f in cov["floors"].values())
    for n in (0, 2):
        p = vr.plan(
            {"week": 7, "block": 2, "session_role": "lower_volume", "date": "2026-11-12"}, CATALOG, rows=[], missing=[], kb_exposures=n
        )
        assert p["volume_check"]["unchanged"], p["volume_check"]
        rx = ps.session_prescription_for_role("lower_volume", catalog_movements=CATALOG, accessory_variants=p["variants"])
        kb_row = next(e for e in rx["exposures"] if e.get("slot") == "kettlebell_swing")
        assert kb_row["movement_key"] == kb.served(n) and all(st["reps"][1] <= 8 for st in kb_row["sets"]), kb_row  # OD1 reps <= 8
        assert not rx["time_trim"] or "kettlebell" not in str(rx["time_trim"])
    entry = CATALOG[kb.ENTRY]
    assert (entry["hevy_template_id_hint"], entry["title"]) == (kb.ENTRY_TEMPLATE_ID, kb.ENTRY_TITLE) and entry["anchor_family"] is None
    assert wf.is_kettlebell(kb.ENTRY, CATALOG) and wf.is_kettlebell(kb.TARGET, CATALOG)


# ── kettlebell: a week with none fails on the date, the same week with one passes; the date / approval switch ─────────
def test_a_week_with_no_kettlebell_fails_on_the_date_and_the_same_week_with_one_passes():
    rot = _week(13, date=ON)
    no_kb = wc.evaluate(rot, CATALOG, on=ON, library=None, days=_days(_ir("lower_volume", NO_KB_LOWER_VOLUME)))
    assert no_kb["verdict"] == "fail" and no_kb["blocking"] == ["kettlebell"], no_kb["blocking"]
    assert any("dan_john: 'carries and kettlebell work weekly" in x for x in no_kb["lines"]), no_kb["lines"]
    with_kb = wc.evaluate(rot, CATALOG, on=ON, library=None, days=_days(_ir("lower_volume", NO_KB_LOWER_VOLUME + ["kettlebell_swing"])))
    assert with_kb["verdict"] == "pass" and _verdicts(with_kb)["kettlebell"] == "met", with_kb["lines"]


def test_the_kettlebell_switch_warns_the_day_before_blocks_on_the_date_and_on_approval():
    rot, days = _week(7), _days(_ir("lower_volume", NO_KB_LOWER_VOLUME))
    assert _verdicts(wc.evaluate(rot, CATALOG, on=BEFORE, library=None, days=days))["kettlebell"] == "warn"
    assert _verdicts(wc.evaluate(rot, CATALOG, on=ON, library=None, days=days))["kettlebell"] == "block"
    assert _verdicts(wc.evaluate(rot, CATALOG, on="2026-11-12", library={"status": "approved"}, days=days))["kettlebell"] == "block"
    assert _verdicts(wc.evaluate(rot, CATALOG, on="2026-11-12", library={"status": "proposed"}, days=days))["kettlebell"] == "warn"


def test_control_a_moved_date_or_an_ignored_approval_breaks_the_switch():
    rot, days = _week(7), _days(_ir("lower_volume", NO_KB_LOWER_VOLUME))
    with patch.object(wf, "KETTLEBELL_BLOCK_FROM", "2026-12-21"):
        assert _verdicts(wc.evaluate(rot, CATALOG, on=ON, library=None, days=days))["kettlebell"] == "warn"
    with patch.object(wf, "LIBRARY_APPROVED", "never"):
        assert _verdicts(wc.evaluate(rot, CATALOG, on="2026-11-12", library={"status": "approved"}, days=days))["kettlebell"] == "warn"


# ── departures count toward AND against (owner ruling 2026-11-11, item 2) ─────────────────────────────────────────────
SA_NO_CARRY = ["db_shoulder_press", "db_lateral_raise", "face_pull", "db_curl", "cable_tricep_pushdown"]
LH_NO_SINGLE_LEG = ["squat_barbell", "deadlift_barbell", "leg_press", "leg_curl", "calf_raise_machine"]


def test_a_custom_day_that_displaces_the_only_carry_fails_and_one_that_carries_it_satisfies():
    rot = _week(7)
    displaced = wc.evaluate(rot, CATALOG, on=BEFORE, library=None, days=_days(_ir("shoulders_arms", SA_NO_CARRY)))
    assert displaced["blocking"] == ["carries"], displaced["lines"]
    assert any("athlean_x" in x and "dan_john" in x for x in displaced["lines"]), displaced["lines"]
    moved = _days(_ir("shoulders_arms", SA_NO_CARRY), _ir("lower_volume", NO_KB_LOWER_VOLUME + ["kettlebell_swing", "farmers_walk"]))
    assert wc.evaluate(rot, CATALOG, on=BEFORE, library=None, days=moved)["verdict"] == "pass"


def test_a_custom_day_removing_the_only_single_leg_fails_the_week():
    out = wc.evaluate(_week(7), CATALOG, on=BEFORE, library=None, days=_days(_ir("lower_heavy", LH_NO_SINGLE_LEG)))
    assert out["blocking"] == ["single_leg"] and any("single_leg_progression" in x for x in out["lines"]), out["lines"]
    kept = _days(_ir("lower_heavy", LH_NO_SINGLE_LEG + ["reverse_lunge_dumbbell"]))
    assert wc.evaluate(_week(7), CATALOG, on=BEFORE, library=None, days=kept)["verdict"] == "pass"


def test_a_custom_day_resolved_by_template_id_counts_as_its_catalog_movement():
    ir = _ir("shoulders_arms", SA_NO_CARRY + ["tmpl:" + CATALOG["farmers_walk"]["hevy_template_id_hint"]])
    assert ("farmers_walk", 3) in wc.routine_day(ir, CATALOG)
    assert wc.evaluate(_week(7), CATALOG, on=BEFORE, library=None, days=_days(ir))["verdict"] == "pass"


def test_week_days_reads_the_drafts_in_hand_and_the_routines_committed_this_program_week():
    hand = _ir("lower_volume", NO_KB_LOWER_VOLUME, rid="hand", action="cron_generated", status="draft", date="2026-11-14")
    routines = [
        _ir("shoulders_arms", SA_NO_CARRY, rid="sa-old", date="2026-11-08"),
        _ir("shoulders_arms", SA_NO_CARRY + ["farmers_walk"], rid="sa-new", date="2026-11-09"),  # newest commit wins
        _ir("lower_heavy", LH_NO_SINGLE_LEG, rid="lh-draft", status="draft"),  # a draft not committed is not served
        _ir("upper_heavy", ["barbell_bench_press"], rid="uh-archived", status="archived"),
        _ir("upper_volume", ["machine_row"], rid="uv-week6", week=6),  # another program week
        _ir("lower_volume", NO_KB_LOWER_VOLUME, rid="lv-committed", date="2026-11-10"),  # the draft in hand wins its role
        _ir("lower_heavy", ["machine_hip_thrust", "leg_press"], rid="floor-11", variant="floor", action="floor", date="2026-11-11"),
        _ir("upper_heavy", ["bench"], rid="anchor-11", action="cron_generated", status="draft", date="2026-11-11"),
    ]
    days = wc.week_days(hand, routines, CATALOG, (2, 7))
    assert {r: d["source"].split()[1] for r, d in days.items()} == {
        "shoulders_arms": "sa-new",
        "lower_volume": "hand",
        "lower_heavy": "floor-11",
    }
    # the floor draft (no calendar) joined week 7 by its day's other routine; it now serves lower_heavy, so single-leg fails
    out = wc.evaluate(_week(7), CATALOG, on=BEFORE, library=None, days=days)
    assert "single_leg" in out["blocking"] and "kettlebell" not in out["blocking"], out["lines"]


# ── must-fail controls on the remaining blocking rows ─────────────────────────────────────────────────────────────────
def test_a_week_with_no_corrective_movement_fails():
    days = _days(
        _ir("upper_heavy", ["barbell_bench_press", "machine_row", "lat_pulldown", "db_lateral_raise", "db_curl"]),
        _ir("shoulders_arms", ["db_shoulder_press", "db_lateral_raise", "db_curl", "farmers_walk"]),
        _ir("upper_volume", ["incline_db_press", "machine_row", "lat_pulldown", "cable_chest_fly"]),
    )
    out = wc.evaluate(_week(7), CATALOG, on=BEFORE, library=None, days=days)
    assert "corrective" in out["blocking"] and any("athlean_x" in x for x in out["lines"]), out["lines"]


def test_a_week_holding_an_accessory_at_a_phase_boundary_fails_rotation():
    rot = copy.deepcopy(_week(7))
    slot = next(s for s in rot["slots"] if len(s["pool"]) >= 2)
    slot["variant"] = slot["previous"]
    out = wc.evaluate(rot, CATALOG, on=BEFORE, library=None)
    assert out["blocking"] == ["rotation"] and any("nippard" in x and slot["slot_id"] in x for x in out["lines"]), out["lines"]


def test_a_week_below_the_side_rear_delt_band_fails():
    rot = copy.deepcopy(_week(7))
    rot["variants_by_role"].setdefault("upper_heavy", {})["db_lateral_raise"] = "db_curl"  # 3 lateral sets -> curls
    out = wc.evaluate(rot, CATALOG, on=BEFORE, library=None)
    assert "side_rear_delt_band" in out["blocking"] and any("rp_israetel" in x for x in out["lines"]), out["lines"]


@pytest.mark.parametrize("family,cid", [("carries", "carries"), ("single_leg_progression", "single_leg")])
def test_a_recorded_gate_on_a_family_only_warns(family, cid):
    rot = copy.deepcopy(_week(7))
    for f in rot["family_floors"]:
        if f["family"] == family:
            f.update(met=False, gate="x: on the charter's equipment.not_available list")
    role, keys = ("shoulders_arms", SA_NO_CARRY) if cid == "carries" else ("lower_heavy", LH_NO_SINGLE_LEG)
    out = wc.evaluate(rot, CATALOG, on=BEFORE, library=None, days=_days(_ir(role, keys)))
    assert _verdicts(out)[cid] == "warn" and out["verdict"] == "pass", out["lines"]


# ── stretch-position: measured from the library, report-only ────────────────────────────────────────────────────────
def test_stretch_position_reads_the_library_and_never_blocks():
    rot = _week(7)
    lengthened = {"status": "approved", "movements": {"bulgarian_split_squat_dumbbell": {"title": "BSS", "length_bias": "lengthened"}}}
    none = {"status": "approved", "movements": {"bulgarian_split_squat_dumbbell": {"title": "BSS", "length_bias": "mid"}}}
    assert _verdicts(wc.evaluate(rot, CATALOG, on=BEFORE, library=lengthened))["stretch_position"] == "met"
    missed = wc.evaluate(rot, CATALOG, on=BEFORE, library=none)
    assert _verdicts(missed)["stretch_position"] == "warn" and "stretch_position" not in missed["blocking"], missed["lines"]


def _fw_lib(status: str, *, pull_profile: str = "free_weight") -> dict:
    """A synthetic library: the week's anchors as free-weight compounds, its machine row as the only pull."""
    mv = {
        "barbell_bench_press": {"title": "Bench", "job": "compound", "pattern": "horizontal_press", "resistance_profile": "free_weight"},
        "squat_barbell": {"title": "Squat", "job": "compound", "pattern": "squat", "resistance_profile": "free_weight"},
        "deadlift_barbell": {"title": "Deadlift", "job": "compound", "pattern": "hinge", "resistance_profile": "free_weight"},
        "machine_row": {"title": "Row", "job": "compound", "pattern": "horizontal_pull", "resistance_profile": pull_profile},
    }
    targets = {"barbell_bench_press": "chest", "squat_barbell": "quadriceps", "deadlift_barbell": "glutes", "machine_row": "back"}
    return {"status": status, "movements": {k: e | {"target": {"primary": targets[k]}} for k, e in mv.items()}}


def test_free_weight_compound_floor_needs_a_press_pull_squat_and_hinge_and_arms_on_approval():
    """Owner ruling 2026-11-12 on #5857 (board rec 4): every program week serves a free-weight compound press, pull, squat
    and hinge; anchors count. It BLOCKS once the library is approved and WARNS before."""
    rot = _week(7)
    assert _verdicts(wc.evaluate(rot, CATALOG, on=BEFORE, library=_fw_lib("approved")))["free_weight_compounds"] == "met"
    # control: the only pull is a machine -> blocks when approved, warns while proposed
    no_pull = wc.evaluate(rot, CATALOG, on=BEFORE, library=_fw_lib("approved", pull_profile="machine_selectorized"))
    assert _verdicts(no_pull)["free_weight_compounds"] == "block" and "free_weight_compounds" in no_pull["blocking"]
    assert "pull" in next(r["detail"] for r in no_pull["rows"] if r["id"] == "free_weight_compounds")
    proposed = wc.evaluate(rot, CATALOG, on=BEFORE, library=_fw_lib("proposed", pull_profile="machine_selectorized"))
    assert _verdicts(proposed)["free_weight_compounds"] == "warn" and "free_weight_compounds" not in proposed["blocking"]


# ── no week, the stage-1 surface, the commit refusal ──────────────────────────────────────────────────────────────
def test_no_week_to_read_is_not_evaluated_never_a_pass():
    out = wc.evaluate(None, CATALOG, on=ON, library=None)
    assert out["verdict"] == "not_evaluated" and not out["blocking"] and len(out["warnings"]) == len(wc.COMMITMENTS)


def _err(msg, error_code="INTERNAL", suggestions=None, detail=None):
    return {"error": msg, "error_code": error_code, "suggestions": suggestions, "detail": detail}


def test_commit_refuses_any_draft_whose_week_fails_and_reads_the_committed_departures():
    rot = _week(13, date=BEFORE)
    no_kb_committed = [_ir("lower_volume", NO_KB_LOWER_VOLUME, rid="lv", date="2026-12-18", week=13, block=3)]
    hand = _ir(
        "upper_heavy",
        ["barbell_bench_press", "machine_row", "db_lateral_raise", "reverse_pec_deck"],
        rid="hand",
        action="cron_generated",
        status="draft",
        date=ON,
        week=13,
        block=3,
        rot=rot,
    )
    with patch.object(wc, "_catalog", lambda: CATALOG), patch.object(wf, "library", lambda path=None: None):
        refused = wc.commit_refusal(hand, _err, lister=lambda a, b: no_kb_committed)
        assert refused and refused["error_code"] == wc.ERROR_CODE and "kettlebell" in refused["error"], refused
        assert wc.commit_refusal(hand, _err, lister=lambda a, b: []) is None  # the engine's lower_volume serves the KB slot
        # a draft_custom with no rotation record is planned from its calendar, and refused the same way
        custom = _ir("shoulders_arms", SA_NO_CARRY, rid="custom", status="draft", date=ON, week=13, block=3)
        assert "carries" in wc.commit_refusal(custom, _err, lister=lambda a, b: [])["error"]
        # an unreadable routine read is named and the week is this draft + the plan; a broken check fails CLOSED
        ok = wc.commit_refusal(hand, _err, lister=lambda a, b: (_ for _ in ()).throw(OSError("ddb down")))
        assert ok is None
        with patch.object(wc, "_catalog", side_effect=OSError("catalog unreadable")):
            assert wc.commit_refusal(hand, _err, lister=lambda a, b: [])["error_code"] == wc.ERROR_CODE
        # a floor draft with no calendar and no same-day routine: no week to plan — not evaluated, never refused
        floor = _ir("lower_volume", ["machine_hip_thrust"], rid="floor", variant="floor", action="floor", status="draft", date=ON)
        assert wc.commit_refusal(floor, _err, lister=lambda a, b: []) is None


def test_stage_1_attaches_the_verdict_and_names_a_failure_on_honesty():
    displaced = [_ir("shoulders_arms", SA_NO_CARRY, rid="sa", date="2026-11-08")]
    block = {"session": {"rotation": _week(7)}, "honesty": []}
    wc.attach(block, None, BEFORE, CATALOG, lister=lambda a, b: displaced)
    assert block["week_commitments"]["verdict"] == "fail" and block["week_commitments"]["blocking"] == ["carries"]
    assert any(h.startswith("STAGE 1 FAILS") and "carries" in h for h in block["honesty"]), block["honesty"]
    clean = {"session": {"rotation": _week(7)}, "honesty": []}
    wc.attach(clean, None, BEFORE, CATALOG, lister=lambda a, b: (_ for _ in ()).throw(OSError("ddb down")))
    assert clean["week_commitments"]["verdict"] == "pass" and "OSError" in clean["week_commitments"]["routines_read_error"]
    with patch.object(wc, "evaluate", side_effect=KeyError("x")):
        broken = {"session": {}}
        wc.attach(broken, None, ON, CATALOG, lister=lambda a, b: [])  # stage 1 still answers; the failure is named
    assert broken["week_commitments"]["verdict"] == "read_failed" and "KeyError" in broken["week_commitments"]["error"]


def _source_of(rel: str, name: str) -> str:
    """One function's source, read off the file (importing the MCP modules needs the Lambda's environment)."""
    import ast

    text = (REPO / rel).read_text(encoding="utf-8")
    node = next(n for n in ast.walk(ast.parse(text)) if isinstance(n, ast.FunctionDef) and n.name == name)
    return ast.get_source_segment(text, node) or ""


def test_the_commit_and_stage_1_are_wired():
    commit = _source_of("mcp/tools_hevy_routine.py", "_action_commit")
    assert "week_commitments.commit_refusal(ir, mcp_error)" in commit
    assert commit.index("week_commitments.commit_refusal") < commit.index("commit_binding.preflight")
    stage_1 = _source_of("mcp/tools_plan.py", "tool_plan_next_session")
    assert "week_commitments.attach(block, ir, target_date, catalog_movements)" in stage_1


def test_the_rubric_and_the_gate_share_one_definition():
    assert panel_rubric._CORRECTIVE is wc.CORRECTIVE and panel_rubric.rotation_problem is wc.rotation_problem
    assert not hasattr(panel_rubric, "_KETTLEBELL")
