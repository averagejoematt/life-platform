"""#5774 (epic #5770) — the charter concession ledger's weekly commitments are HARD stage-1 checks.

carries + kettlebell (dan_john), single-leg + corrective (athlean_x), stretch-position + rotation (nippard), the side/rear-delt
band (rp_israetel). A draft whose program week misses a blocking commitment fails stage 1 with the ledger line named and is
refused at commit. Kettlebell warns until the earlier of exercise-library approval or 2026-12-20 (owner ruling 2026-11-11);
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

from training import panel_rubric, training_charter as tc, variant_rotation as vr, week_commitments as wc, week_floors as wf  # noqa: E402
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


def _with_kettlebell(rot: dict, date: str) -> dict:
    rot = copy.deepcopy(rot)
    rot["kettlebell_weekly"] = wf.kettlebell_weekly([{"key": "kettlebell_swing", "slot_id": "fixture"}], CATALOG, on=date, status=None)
    return rot


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


# ── the current pools fill every blocking commitment (they block NOW) ───────────────────────────────────────────────
def test_every_program_week_on_the_current_pools_passes_until_the_kettlebell_date():
    fails = []
    for week in range(1, 19):
        out = wc.evaluate(_week(week), CATALOG, on=BEFORE, library=None)
        if out["verdict"] != "pass":
            fails.append((week, out["blocking"]))
        v = _verdicts(out)
        assert v["kettlebell"] == "warn" and v["stretch_position"] == "not_evaluated", (week, v)
        # block 1's first phase serves the committed template: the recorded gate makes single-leg a WARNING, never a pass
        assert v["single_leg"] == ("warn" if week <= 3 else "met"), (week, v)
        assert all(v[k] == "met" for k in ("carries", "corrective", "rotation", "side_rear_delt_band")), (week, v)
    assert not fails, fails


# ── kettlebell: a fixture week with none fails, the same week with one passes; the date / approval switch ──────────────
def test_a_week_with_no_kettlebell_fails_on_the_date_and_the_same_week_with_one_passes():
    rot = _week(13, date=ON)
    out = wc.evaluate(rot, CATALOG, on=ON, library=None)
    assert out["verdict"] == "fail" and out["blocking"] == ["kettlebell"], out["blocking"]
    assert any("dan_john: 'carries and kettlebell work weekly'" in x for x in out["lines"]), out["lines"]
    passed = wc.evaluate(_with_kettlebell(rot, ON), CATALOG, on=ON, library=None)
    assert passed["verdict"] == "pass" and _verdicts(passed)["kettlebell"] == "met", passed["lines"]


def test_the_kettlebell_switch_warns_the_day_before_blocks_on_the_date_and_on_approval():
    rot = _week(7)
    assert _verdicts(wc.evaluate(rot, CATALOG, on=BEFORE, library=None))["kettlebell"] == "warn"
    assert _verdicts(wc.evaluate(rot, CATALOG, on=ON, library=None))["kettlebell"] == "block"
    assert _verdicts(wc.evaluate(rot, CATALOG, on="2026-11-12", library={"status": "approved"}))["kettlebell"] == "block"
    assert _verdicts(wc.evaluate(rot, CATALOG, on="2026-11-12", library={"status": "proposed"}))["kettlebell"] == "warn"


def test_the_kettlebell_verdict_is_re_dated_on_the_drafts_day_not_the_stamp():
    """A draft stamped `warn` when it was drafted still FAILS when its own day is on/after the date."""
    rot = _week(7, date=BEFORE)
    assert rot["kettlebell_weekly"]["verdict"] == "warn"
    assert wc.evaluate(rot, CATALOG, on=ON, library=None)["blocking"] == ["kettlebell"]


def test_control_a_moved_date_or_an_ignored_approval_breaks_the_switch():
    rot = _week(7)
    with patch.object(wf, "KETTLEBELL_BLOCK_FROM", "2026-12-21"):
        assert _verdicts(wc.evaluate(rot, CATALOG, on=ON, library=None))["kettlebell"] == "warn"
    with patch.object(wf, "LIBRARY_APPROVED", "never"):
        assert _verdicts(wc.evaluate(rot, CATALOG, on="2026-11-12", library={"status": "approved"}))["kettlebell"] == "warn"


# ── must-fail controls: remove each blocking commitment from the week, and stage 1 names it ────────────────────────────
def _floor_missing(rot: dict, family: str, gate: str) -> dict:
    rot = copy.deepcopy(rot)
    for f in rot["family_floors"]:
        if f["family"] == family:
            f.update(met=False, served=[], gate=gate)
    return rot


@pytest.mark.parametrize("cid,family", [("carries", "carries"), ("single_leg", "single_leg_progression")])
def test_a_week_missing_a_floored_family_fails_and_a_recorded_gate_only_warns(cid, family):
    rot = _week(7)
    out = wc.evaluate(_floor_missing(rot, family, f"nothing in the week hosts a {family} member"), CATALOG, on=BEFORE, library=None)
    assert out["verdict"] == "fail" and out["blocking"] == [cid], out["blocking"]
    ledger = charter_value("concession_ledger")
    assert any(ledger["athlean_x"]["in_return"] in x for x in out["lines"]), out["lines"]
    gated = wc.evaluate(
        _floor_missing(rot, family, "farmers_walk: on the charter's equipment.not_available list"), CATALOG, on=BEFORE, library=None
    )
    assert gated["verdict"] == "pass" and _verdicts(gated)[cid] == "warn", gated["lines"]


def test_a_week_with_no_corrective_movement_fails():
    with patch.object(wc, "week_keys", lambda rot, catalog: ["squat_barbell", "db_lateral_raise", "farmers_walk"]):
        out = wc.evaluate(_week(7), CATALOG, on=BEFORE, library=None)
    assert out["blocking"] == ["corrective"] and any("athlean_x" in x for x in out["lines"]), out["lines"]


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


# ── stretch-position: measured from the library, report-only ────────────────────────────────────────────────────────
def test_stretch_position_reads_the_library_and_never_blocks():
    rot = _week(7)
    lengthened = {"status": "approved", "movements": {"bulgarian_split_squat_dumbbell": {"title": "BSS", "length_bias": "lengthened"}}}
    none = {"status": "approved", "movements": {"bulgarian_split_squat_dumbbell": {"title": "BSS", "length_bias": "mid"}}}
    assert _verdicts(wc.evaluate(rot, CATALOG, on=BEFORE, library=lengthened))["stretch_position"] == "met"
    missed = wc.evaluate(_with_kettlebell(rot, BEFORE), CATALOG, on=BEFORE, library=none)
    assert _verdicts(missed)["stretch_position"] == "warn" and missed["verdict"] == "pass", missed["lines"]


# ── no record, the stage-1 surface, the commit refusal ─────────────────────────────────────────────────────────────
def test_no_rotation_record_is_not_evaluated_never_a_pass():
    out = wc.evaluate(None, CATALOG, on=ON, library=None)
    assert out["verdict"] == "not_evaluated" and not out["blocking"] and len(out["warnings"]) == len(wc.COMMITMENTS)


class _IR:
    def __init__(self, rot, day):
        self.inputs_snapshot, self.target_date, self.routine_id = {"rotation": rot}, day, "fixture"


def _err(msg, error_code="INTERNAL", suggestions=None, detail=None):
    return {"error": msg, "error_code": error_code, "suggestions": suggestions, "detail": detail}


def test_commit_refuses_a_draft_whose_week_fails_stage_1_and_passes_the_day_before():
    rot = _week(13, date=BEFORE)
    with patch.object(wc, "_catalog", lambda: CATALOG):
        refused = wc.commit_refusal(_IR(rot, ON), _err)
        assert refused and refused["error_code"] == wc.ERROR_CODE and "kettlebell" in refused["error"], refused
        assert wc.commit_refusal(_IR(rot, BEFORE), _err) is None
        assert wc.commit_refusal(_IR(_with_kettlebell(rot, ON), ON), _err) is None
        assert wc.commit_refusal(_IR(None, ON), _err) is None  # draft_custom / floor: no week record to read
    with patch.object(wc, "_catalog", side_effect=OSError("catalog unreadable")):
        assert wc.commit_refusal(_IR(rot, BEFORE), _err)["error_code"] == wc.ERROR_CODE  # fails closed, named


def test_stage_1_attaches_the_verdict_and_names_a_failure_on_honesty():
    block = {"session": {"rotation": _week(7)}, "honesty": []}
    wc.attach(block, None, ON, CATALOG)
    assert block["week_commitments"]["verdict"] == "fail" and "planned session" in block["week_commitments"]["evaluated_from"]
    assert any(h.startswith("STAGE 1 FAILS") and "kettlebell" in h for h in block["honesty"]), block["honesty"]
    draft = {"session": {"rotation": None}, "honesty": []}
    wc.attach(draft, _IR(_with_kettlebell(_week(7), ON), ON), ON, CATALOG)
    assert draft["week_commitments"]["verdict"] == "pass" and draft["honesty"] == []
    with patch.object(wc, "evaluate", side_effect=KeyError("x")):
        broken = {"session": {}}
        wc.attach(broken, None, ON, CATALOG)  # stage 1 still answers; the failure is named, never a pass
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
