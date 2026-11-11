"""#5759 — exercise selection (block-1 retro, #5496): the accessory slots rotate on the charter's cadence and the drafted
routine names the slot and the variant; every program week serves a single-leg movement and a loaded carry from the
charter's `rotation.pool` unless a recorded gate excludes it (the reason named); the weekly panel grade scores the
rotation, single-leg and carry criteria from the DRAFTS, and the block retro's row reads those criteria unchanged.

Every date here is a fixed literal; nothing reads the clock.
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
    block_retro,
    panel_rubric,
    program_structure,
    training_charter as tc,
    variant_rotation as vr,
    week_floors as wf,
)  # noqa: E402
from training.block_model import block_weeks  # noqa: E402
from training.training_charter import charter_value  # noqa: E402

CATALOG = json.loads((REPO / "config" / "movement_catalog.json").read_text())["movements"]
FIX = REPO / "tests" / "fixtures" / "panel_golden_5072"
ROLES = program_structure.SPLIT_ROLES
SINGLE_LEG, CARRIES = "single_leg_progression", "carries"


@pytest.fixture(autouse=True)
def _bundled_charter_only(monkeypatch):
    monkeypatch.delenv(tc.PRIVATE_ENV_VAR, raising=False)
    monkeypatch.setattr(tc, "_from_s3", lambda key: None)
    tc.reset_cache()
    yield
    tc.reset_cache()


def _entry(week: int, role: str = "lower_heavy", date: str = "2026-11-12") -> dict:
    return {"week": week, "block": (week - 1) // block_weeks() + 1, "session_role": role, "date": date}


def _week_keys(plan: dict) -> set[str]:
    """Every movement the week's five drafts prescribe with this rotation applied."""
    return {
        e["movement_key"]
        for r in ROLES
        for e in program_structure.session_prescription_for_role(
            r, catalog_movements=CATALOG, accessory_variants=plan["variants_by_role"].get(r)
        )["exposures"]
    }


def _weeks_missing_a_family(weeks: range) -> list[str]:
    out = []
    for week in weeks:
        keys = _week_keys(vr.plan(_entry(week), CATALOG, role="*", rows=[], missing=[]))
        for family in (SINGLE_LEG, CARRIES):
            if not keys & set(wf.family_members(family)):
                out.append(f"week {week}: no {family} member in {sorted(keys)}")
    return out


# ── box 2: a single-leg movement and a carry every week ─────────────────────
def test_the_floored_families_are_the_charters_own_names():
    pool = charter_value("rotation.pool")
    problems = [f"{fam}: not a charter rotation.pool family" for fam in wf.WEEKLY_FAMILY_FLOORS if fam not in pool]
    for fam in wf.WEEKLY_FAMILY_FLOORS:
        if set(wf.CHARTER_FAMILY_KEYS.get(fam) or {}) != set(pool.get(fam) or []):
            problems.append(f"{fam}: mapped names {sorted(wf.CHARTER_FAMILY_KEYS.get(fam) or {})} != charter {sorted(pool.get(fam))}")
        for key in wf.family_members(fam):
            if key not in CATALOG or not int(CATALOG[key].get("sessions") or 0):
                problems.append(f"{fam}: {key} is not a logged catalog movement")
    assert not problems, "\n".join(problems)


FIRST_ROTATED_WEEK = vr.rotate_every_weeks() + 1  # block 1's first phase (weeks 1-3) serves the committed template as written


def test_every_program_week_of_four_blocks_serves_a_single_leg_movement_and_a_carry():
    weeks = range(FIRST_ROTATED_WEEK, 4 * block_weeks() + 1)
    assert _weeks_missing_a_family(weeks) == []
    for week in weeks:
        floors = {f["family"]: f for f in vr.plan(_entry(week), CATALOG, role="*", rows=[], missing=[])["family_floors"]}
        assert set(floors) == set(wf.WEEKLY_FAMILY_FLOORS) and all(f["met"] and f["gate"] is None for f in floors.values()), week
        assert [s["slot_id"] for s in floors[SINGLE_LEG]["served"]] == ["lower_heavy.leg_press"], week
        assert [s["slot_id"] for s in floors[CARRIES]["served"]] == ["shoulders_arms.farmers_walk"], week


def test_control_without_the_floor_a_week_goes_without_single_leg_work():
    """Must-fail control: the pre-#5759 rotation (no floor) leaves weeks with no single-leg movement — the gate above
    can fail, and it fails on exactly the defect the retro named."""
    with patch.object(vr, "WEEKLY_FAMILY_FLOORS", {}):
        missing = _weeks_missing_a_family(range(FIRST_ROTATED_WEEK, 4 * block_weeks() + 1))
    assert missing and all(SINGLE_LEG in m for m in missing), missing


def test_the_single_leg_slot_serves_its_pools_single_leg_member_every_phase_and_keeps_the_week_at_75_sets():
    """The pools are NOT re-curated (the exercise library epic supersedes them): the leg-press slot's pool holds one
    single-leg member, so the floor serves it every phase, and the rationale says why it is held."""
    template = vr.week_volume(CATALOG, {})
    for week in range(FIRST_ROTATED_WEEK, 4 * block_weeks() + 1, vr.rotate_every_weeks()):
        plan = vr.plan(_entry(week), CATALOG, role="*", rows=[], missing=[])
        assert plan["volume_check"]["unchanged"] and vr.week_volume(CATALOG, plan["variants_by_role"]) == template, week
        assert plan["variants_by_role"]["lower_heavy"]["leg_press"] == "bulgarian_split_squat_dumbbell", week


def test_block_one_first_phase_keeps_the_committed_session_and_names_why_the_floor_is_not_met():
    """The owner-committed lower-heavy (tests/test_program_session_4064_4147.py) is served as written in weeks 1-3; the
    floor does not move it, and the week's record names that as the gate rather than passing silently."""
    for week in range(1, FIRST_ROTATED_WEEK):
        plan = vr.plan(_entry(week), CATALOG, role="*", rows=[], missing=[])
        assert plan["variants_by_role"]["lower_heavy"]["leg_press"] == "leg_press", week
        sl = next(f for f in plan["family_floors"] if f["family"] == SINGLE_LEG)
        assert not sl["met"] and "first phase serves the template as written" in sl["gate"], (week, sl)
        assert next(f for f in plan["family_floors"] if f["family"] == CARRIES)["met"], week
    assert vr.seed_pool("leg_press", CATALOG, missing=[])["pool"] == ["leg_press"] + vr.VETTED_POOLS["leg_press"]["candidates"]


def test_the_draft_names_the_slot_and_the_variant_it_serves():
    """The live specimen: block 1's phase 2 ledger row served the Bulgarian split squat on lower_heavy.leg_press; block 2's
    first lower-heavy draft names the slot and the variant on every accessory line, and the week's floor lines."""
    rows = [{"pk": vr.LEDGER_PK, "sk": "ROTATION#B001#lower_heavy.leg_curl", "phase_2": {"variant": "lying_leg_curl_machine"}}]
    out = vr.plan(_entry(7), CATALOG, rows=rows, missing=[])
    acc = program_structure.SESSION_TEMPLATES["lower_heavy"]["accessories"]
    for a in acc:
        line = next(x for x in out["rationale"] if f"[lower_heavy.{a}" in x)
        assert CATALOG[out["variants"][a]]["title"] in line, line
    curl = next(x for x in out["rationale"] if "[lower_heavy.leg_curl" in x)
    assert curl.startswith("rotated: Lying Leg Curl (Machine) → Seated Leg Curl (Machine), week 1 of block 2"), curl
    held = next(x for x in out["rationale"] if "[lower_heavy.leg_press" in x)
    assert held.startswith("held: Bulgarian Split Squat (Dumbbell)") and "weekly floor" in held, held
    assert "weekly floor met: single_leg_progression — Bulgarian Split Squat (Dumbbell) [lower_heavy.leg_press]" in out["rationale"]
    assert "weekly floor met: carries — Farmers Walk [shoulders_arms.farmers_walk]" in out["rationale"]


def test_the_week_check_is_standalone_for_any_selection_engine():
    """`week_floors.check_week` reads only served keys and refusals — a later engine calls it without the rotation."""
    served = [{"key": "reverse_lunge_dumbbell"}, {"key": "suitcase_carry"}, {"key": "kettlebell_swing"}]
    out = wf.check_week(served, [], CATALOG, on="2026-11-12", status=None)
    assert all(f["met"] for f in out["family_floors"]) and out["kettlebell"]["met"]
    none = wf.check_week([{"key": "leg_press"}], [{"key": "farmers_walk", "reason": "a gate"}], CATALOG, status=None)
    gates = {f["family"]: f["gate"] for f in none["family_floors"]}
    assert gates == {SINGLE_LEG: "nothing in the week hosts a single_leg_progression member", CARRIES: "farmers_walk: a gate"}


# ── the kettlebell verdict (owner ruling 2026-11-11): WARN now, BLOCK from library approval or program week 13 ──
# His completed program sessions as the Hevy record held them on 2026-11-11 (session_sequence.completed_positions, a
# read-only DDB read) — fixed literals, so the week-13 derivation below never reads the clock or AWS.
COMPLETED_2026_11_11 = (
    "2026-09-24 2026-09-25 2026-09-28 2026-09-29 2026-10-01 2026-10-02 2026-10-06 2026-10-07 2026-10-09 2026-10-11 2026-10-13 "
    "2026-10-15 2026-10-16 2026-10-18 2026-10-19 2026-10-21 2026-10-23 2026-10-25 2026-10-26 2026-10-28 2026-10-29 2026-10-30 "
    "2026-11-01 2026-11-02 2026-11-03 2026-11-05 2026-11-06 2026-11-08 2026-11-09 2026-11-10"
).split()


def _kb(date: str, status=None) -> dict:
    with patch.object(wf, "library_status", return_value=status):
        return vr.plan(_entry(7, date=date), CATALOG, rows=[], missing=[])


def test_the_week_13_date_is_the_ledgers_own_earliest_opening_of_program_week_13():
    from common.pacific_time import shift_day_key
    from training import session_sequence

    led = session_sequence.ledger(COMPLETED_2026_11_11)
    assert (led[-1]["week"], led[-1]["block"], led[-1]["week_basis"]["week_opened_on"]) == (7, 2, "2026-11-08")
    daily = [shift_day_key("2026-11-11", i) for i in range(80)]  # a session every day: the 7-day floor alone sets the pace
    first_13 = next(p for p in session_sequence.ledger(COMPLETED_2026_11_11 + daily) if p["week"] == 13)
    assert (first_13["date"], first_13["block"]) == (wf.KETTLEBELL_BLOCK_FROM, 3)
    assert shift_day_key("2026-11-08", 6 * session_sequence.WEEK_RULE["floor_days"]) == wf.KETTLEBELL_BLOCK_FROM


def test_kettlebell_warns_before_the_date_with_no_approved_library_and_never_edits_the_draft():
    for status in (None, "proposed"):
        out = _kb("2026-12-19", status)
        kb = out["kettlebell_weekly"]
        assert (kb["verdict"], kb["blocking"], kb["met"]) == ("warn", False, False), kb
        assert "dan_john" in kb["provenance"] and any(x.startswith("kettlebell weekly NOT met (warning)") for x in out["rationale"])
    with patch.object(wf, "kettlebell_weekly", return_value={"met": True, "served": [], "blocking": False}):
        assert vr.plan(_entry(7, date="2026-12-19"), CATALOG, rows=[], missing=[])["variants"] == _kb("2026-12-19")["variants"]


def test_kettlebell_blocks_on_and_after_program_week_13():
    for day in (wf.KETTLEBELL_BLOCK_FROM, "2027-01-04"):
        out = _kb(day)
        kb = out["kettlebell_weekly"]
        assert (kb["verdict"], kb["blocking"]) == ("block", True) and "program week 13" in kb["note"], (day, kb)
        assert any(x.startswith("kettlebell weekly BLOCKED") for x in out["rationale"]), day


def test_kettlebell_blocks_before_the_date_once_the_library_is_approved(tmp_path):
    kb = _kb("2026-11-12", "approved")["kettlebell_weekly"]
    assert (kb["verdict"], kb["blocking"]) == ("block", True) and "library is approved" in kb["note"], kb
    # the library file is the switch: absent reads not approved; its status field is read as written
    assert wf.library_status(str(tmp_path / "absent.json")) is None
    lib = tmp_path / "exercise_library.json"
    lib.write_text(json.dumps({"status": "approved"}), encoding="utf-8")
    assert wf.library_status(str(lib)) == "approved"
    lib.write_text(json.dumps({"status": "proposed"}), encoding="utf-8")
    assert wf.library_status(str(lib)) == "proposed"


def test_a_served_kettlebell_movement_meets_it_and_nothing_blocks():
    kb = wf.kettlebell_weekly([{"key": "kettlebell_swing", "slot_id": "x"}], CATALOG, on="2027-01-04", status="approved")
    assert (kb["verdict"], kb["blocking"], kb["served"][0]["title"]) == ("met", False, "Kettlebell Swing")


def test_control_a_moved_date_or_an_ignored_library_fails_the_ruling():
    """Must-fail controls: a block date one day late warns on week 13's first day, and a check that ignores the library's
    approval warns before the date — each would fail the tests above."""
    with patch.object(wf, "KETTLEBELL_BLOCK_FROM", "2026-12-21"):
        assert _kb("2026-12-20")["kettlebell_weekly"]["verdict"] == "warn"
    with patch.object(wf, "LIBRARY_APPROVED", "never"):
        assert _kb("2026-11-12", "approved")["kettlebell_weekly"]["verdict"] == "warn"


def test_a_recorded_gate_excludes_a_family_and_the_draft_names_the_reason():
    gated = vr.plan(_entry(4), CATALOG, rows=[], missing=["dumbbell", "farmers walk"])
    floors = {f["family"]: f for f in gated["family_floors"]}
    assert not floors[SINGLE_LEG]["met"] and "not_available" in floors[SINGLE_LEG]["gate"], floors[SINGLE_LEG]
    assert "bulgarian_split_squat_dumbbell" in floors[SINGLE_LEG]["gate"]
    assert not floors[CARRIES]["met"] and "farmers_walk: on the charter's equipment.not_available list" in floors[CARRIES]["gate"]
    assert any(x.startswith("weekly floor NOT met: single_leg_progression — excluded by a recorded gate:") for x in gated["rationale"])
    # a refused rotation serves the template, so the floor is checked against the template (and named)
    with patch.object(vr, "volume_check", return_value={"unchanged": False, "moved": ["sets_by_muscle"]}):
        refused = vr.plan(_entry(4), CATALOG, rows=[], missing=[])
    sl = next(f for f in refused["family_floors"] if f["family"] == SINGLE_LEG)
    assert not sl["met"] and sl["gate"] and any(x.startswith("weekly floor NOT met: single_leg_progression") for x in refused["rationale"])


# ── box 3: the weekly grade reads the drafts; the retro reads the grade unchanged ──
def _case(name: str) -> dict:
    return json.loads((FIX / f"{name}.json").read_text(encoding="utf-8"))


def _scores(case: dict) -> dict[str, tuple[float, str]]:
    rubric = panel_rubric.load_rubric()
    pre = panel_rubric.prescore(case, rubric)
    return {f"{s}.{c}": (v["score"], v["evidence"]) for s, seat in pre.items() for c, v in seat.items()}


def test_the_rotation_criterion_is_scored_from_the_drafts_not_the_performed_drift_verdict():
    good = _case("good_charter_plan")
    good["constraint_block"]["accessory_rotation_ok"] = False  # the performed-drift verdict at a rotation week
    score, evidence = _scores(good)["nippard.accessory_rotation"]
    assert score == 10.0 and "5 of 5 lifting drafts rotate on the charter cadence (every 3 wk)" in evidence, evidence
    assert "lower_heavy.leg_curl → lying_leg_curl_machine" in evidence
    frozen_score, frozen_ev = _scores(_case("neg_frozen_no_progression"))["nippard.accessory_rotation"]
    assert frozen_score == 0.0 and "held at a phase boundary" in frozen_ev, frozen_ev
    bare = copy.deepcopy(good)
    for r in bare["routines"]:
        r["inputs_snapshot"].pop("rotation")
    bare_score, bare_ev = _scores(bare)["nippard.accessory_rotation"]
    assert bare_score == 0.0 and "no rotation record on the draft" in bare_ev  # absence is not credit


def test_block_one_first_phase_and_a_refused_rotation_read_as_the_rule_says():
    rot = {
        "position": {"step": 0},
        "volume_check": {"unchanged": True},
        "slots": [{"slot_id": "a.b", "pool": ["x", "y"], "variant": "x", "previous": "x"}],
    }
    assert panel_rubric.rotation_problem(rot) is None
    assert "refused" in panel_rubric.rotation_problem({**rot, "position": {"step": 1}, "volume_check": {"unchanged": False}})
    assert "unknown" in panel_rubric.rotation_problem({**rot, "position": None})
    pinned = {
        **rot,
        "position": {"step": 3},
        "slots": [{"slot_id": "s.f", "source": "pinned", "pool": ["f", "g"], "variant": "f", "previous": "f"}],
    }
    assert panel_rubric.rotation_problem(pinned) is None


def test_single_leg_and_carry_evidence_names_the_drafted_movements_or_the_drafts_gate():
    good = _case("good_charter_plan")
    scores = _scores(good)
    assert "Bulgarian Split Squat (Dumbbell)" in scores["athlean_x.single_leg"][1]
    assert "Farmers Walk" in scores["athlean_x.carries"][1]
    no_carry = copy.deepcopy(good)
    for r in no_carry["routines"]:
        r["exercises"] = [e for e in r["exercises"] if e["movement_key"] not in ("farmers_walk", "suitcase_carry")]
        for fl in r["inputs_snapshot"]["rotation"]["family_floors"]:
            if fl["family"] == CARRIES:
                fl.update(met=False, served=[], gate="farmers_walk: on the charter's equipment.not_available list ('farmers walk')")
    score, evidence = _scores(no_carry)["athlean_x.carries"]
    assert score == 0.0 and "the drafts name the gate: farmers_walk" in evidence, evidence


def test_the_retros_exercise_selection_row_reads_the_three_criteria_from_the_weekly_grade_unchanged():
    scorecard = block_retro.load_scorecard()
    row = next(r for r in scorecard["rows"] if r["id"] == "exercise_selection_variety")
    criteria = next(rule["criteria"] for rule in row["code_rules"] if rule["kind"] == "panel_mean")
    rubric_ids = {f"{s}.{c['id']}" for s, seat in panel_rubric.load_rubric()["seats"].items() for c in seat["criteria"]}
    named = {"nippard.accessory_rotation", "athlean_x.single_leg", "athlean_x.carries", "dan_john.carries_or_kb"}
    assert named <= set(criteria) and set(criteria) <= rubric_ids, set(criteria) - rubric_ids
    # a PANEL# row's per-criterion scores reach the row's code score unchanged (the mean of what the grade stored)
    graded = panel_rubric.combine(
        panel_rubric.prescore(_case("good_charter_plan"), panel_rubric.load_rubric()), None, panel_rubric.load_rubric()
    )
    evidence = {"panel": block_retro._panel_evidence([{"week_end": "2026-10-25", **graded}])}
    means = evidence["panel"]["criteria_means"]["value"]
    for c in named:
        seat, crit = c.split(".")
        assert means[c] == graded["seats"][seat]["criteria"][crit]["score"], c
