"""tests/test_library_integrity_5861.py — the exercise library's integrity rules, each with a must-fail control
(#5861 fix round 13, owner rulings 2026-11-14).

`training.library_integrity` states four rules and `exercise_library.validate` runs them on every build:

  1. FALLBACKS  — one equivalence rule; every link in the committed library passes it; an empty list is valid.
  2. GATES      — every readiness chain is acyclic, reachable and measurable; nothing is unlocked.
  3. LOGGABLE   — a movement with no Hevy template id (or verified canonical mapping) is never selectable.
  4. AVAILABILITY — five evidence states; only owner-confirmed or recently logged equipment is served.

Plus the approval path (an unset bodyweight threshold is LOCKED and VALID; a gate that could open is never
under-specified) and the builder's template facts. Every control mutates a COPY and expects red. Synthetic data only.
"""

from __future__ import annotations

import copy
import json
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
for _p in (REPO, REPO / "lambdas", REPO / "deploy", REPO / "scripts"):
    sys.path.insert(0, str(_p))

import build_exercise_library as builder  # noqa: E402
import exercise_library_curation as cur  # noqa: E402
import exercise_library_integrity as inputs  # noqa: E402
from training import (  # noqa: E402
    exercise_gates as eg,
    exercise_library as xl,
    library_integrity as li,
    selection_engine as se,
)

LIB = json.loads((REPO / "config" / "exercise_library.json").read_text())
MV = LIB["movements"]
CHARTER = json.loads((REPO / "config" / "training_charter.json").read_text())
LINKS = [(k, f["movement_id"]) for k, e in MV.items() for f in e["fallbacks"]]


def _errors(lib: dict) -> list[str]:
    return li.problems(lib)


# ── 1. fallbacks: the one equivalence rule ───────────────────────────────────────────────────────────────────────────
def test_every_fallback_link_passes_the_equivalence_rule():
    broken = {(a, b): li.fallback_problems(LIB, a, b) for a, b in LINKS}
    assert {k: v for k, v in broken.items() if v} == {}
    assert len(LINKS) == LIB["_provenance"]["integrity"]["fallback_links"]


def _muscles(e: dict) -> set[str]:
    return {e["target"]["primary"], *e["target"].get("secondary", [])}


def test_no_fallback_lacks_a_declared_muscle_overlap():
    """The owner's audit measure (68 such links in v0.3.7): a fallback shares the primary target, so it always overlaps."""
    assert [(a, b) for a, b in LINKS if not _muscles(MV[a]) & _muscles(MV[b])] == []


@pytest.mark.parametrize(
    "movement,was",
    [
        ("tibialis_raise", ("shrug_barbell", "lateral_raise_dumbbell", "triceps_pushdown")),
        ("cable_serratus_punch", ("stretching", "scarecrow", "angels_and_devils")),
        ("standing_cable_knee_drive", ("shrug_barbell", "lateral_raise_dumbbell", "glute_kickback_machine")),
        ("hip_airplane", ("rotator_cuff_external_rotation",)),
    ],
)
def test_the_owners_named_examples_are_gone_and_would_be_refused(movement, was):
    assert not {f["movement_id"] for f in MV[movement]["fallbacks"]} & set(was)
    for old in was:
        assert li.fallback_problems(LIB, movement, old), f"{movement} -> {old} must break the rule"
        bad = copy.deepcopy(LIB)
        bad["movements"][movement]["fallbacks"] = [{"movement_id": old, "reason": "same_stimulus"}]
        assert any(f"movements.{movement}: fallback {old} breaks the equivalence rule" in e for e in xl.validate(bad))


def test_an_empty_fallback_list_is_valid_and_lists_are_never_padded():
    none = [k for k, e in MV.items() if not e["fallbacks"]]
    assert len(none) == LIB["_provenance"]["integrity"]["movements_without_fallbacks"] > 0
    for k in none:
        assert li.fallback_candidates(LIB, k) == [], f"{k} has a valid candidate the builder did not list"
    assert all(len(e["fallbacks"]) <= li.MAX_FALLBACKS for e in MV.values())


def _valid_link(pred) -> tuple[str, str]:
    """A real, valid link whose two ends satisfy `pred(a, b)` — the base every clause control mutates."""
    return next((a, b) for a, b in LINKS if pred(MV[a], MV[b]))


def _mutated(a: str, b: str, change) -> dict:
    lib = copy.deepcopy(LIB)
    change(lib["movements"][a], lib["movements"][b], lib)
    return lib


_LOADED = lambda a, b: a["category"] == b["category"] == "hypertrophy" and a["pattern"] == b["pattern"] != "other"  # noqa: E731
_CARDIO = lambda a, b: a["category"] == "conditioning"  # noqa: E731

CLAUSE_CONTROLS = {
    # clause -> (which link to start from, the mutation that breaks exactly that clause)
    "purpose": (_LOADED, lambda a, b, lib: b.update(category="mobility")),
    "function": (_LOADED, lambda a, b, lib: b.update(pattern="shrug", canonical=None)),
    "stimulus": (_LOADED, lambda a, b, lib: b["target"].update(primary="neck")),
    "unavailable": (_LOADED, lambda a, b, lib: b["availability"]["home_gym"].update(state="unknown", evidence="historical_only")),
    "gated": (_LOADED, lambda a, b, lib: b.update(gates=["owner_confirmation_skill"])),
    "not_for_you_now": (_LOADED, lambda a, b, lib: b.update(not_for_you_now={"reason_code": "x", "unlock_condition": "y"})),
    "unloggable": (_LOADED, lambda a, b, lib: b.update(template_id=None)),
    "skill": (_LOADED, lambda a, b, lib: (a.update(skill_complexity="low"), b.update(skill_complexity="high"))),
    "joint_stress": (_LOADED, lambda a, b, lib: (a["joint_stress"].update(shoulder="low"), b["joint_stress"].update(shoulder="high"))),
    "impact": (
        _CARDIO,
        lambda a, b, lib: (
            a["objective_inputs"]["conditioning"].update(impact="low"),
            b["objective_inputs"]["conditioning"].update(impact="high"),
        ),
    ),
    "control": (
        _CARDIO,
        lambda a, b, lib: (
            a["objective_inputs"]["conditioning"].update(control="high"),
            b["objective_inputs"]["conditioning"].update(control="low"),
        ),
    ),
    "ballistic": (_LOADED, lambda a, b, lib: b["objective_inputs"].update(functional=["power"])),
}


def test_every_clause_of_the_rule_has_a_control():
    assert set(CLAUSE_CONTROLS) == set(li.FALLBACK_CLAUSES)


@pytest.mark.parametrize("clause", sorted(CLAUSE_CONTROLS))
def test_must_fail_each_clause_of_the_equivalence_rule(clause):
    pick, change = CLAUSE_CONTROLS[clause]
    a, b = _valid_link(pick)
    assert li.fallback_problems(LIB, a, b) == []
    bad = _mutated(a, b, change)
    assert clause in li.fallback_problems(bad, a, b), f"{a} -> {b}: the {clause} clause did not fire"
    assert any(f"movements.{a}: fallback {b} breaks the equivalence rule" in e and clause in e for e in _errors(bad))


def test_a_shared_family_label_or_a_shared_muscle_alone_is_not_equivalence():
    """The two shortcuts the old generator took. Same `family` label, nothing else in common; and the same primary muscle
    through a different movement function (a curl for a row's biceps; a stretch for a loaded lift)."""
    assert MV["stretching"]["family"] == MV["rotator_cuff_external_rotation"]["family"]
    assert "function" in li.fallback_problems(LIB, "stretching", "rotator_cuff_external_rotation")
    a = next(k for k, e in MV.items() if e["pattern"] == "curl" and e["target"]["primary"] == "biceps" and e["fallbacks"])
    same_muscle = copy.deepcopy(LIB)
    b = next(k for k, e in MV.items() if e["pattern"] == "horizontal_pull" and e["category"] == "hypertrophy")
    same_muscle["movements"][b]["target"]["primary"] = "biceps"
    assert li.fallback_problems(same_muscle, a, b)[:1] == ["function"]


def test_a_strength_lift_may_fall_back_to_a_strength_rated_hypertrophy_lift_never_the_reverse():
    crossings = [(a, b) for a, b in LINKS if MV[a]["category"] != MV[b]["category"]]
    assert crossings and all((MV[a]["category"], MV[b]["category"]) == li.LOADED_CROSSING for a, b in crossings)
    assert all(MV[b]["ratings"]["strength"]["tier"] is not None for _a, b in crossings)
    a, b = crossings[0]
    assert "purpose" in li.fallback_problems(LIB, b, a), "an anchor is never an accessory's fallback"


# ── 2. gates: acyclic, reachable, measurable ─────────────────────────────────────────────────────────────────────────
AUDIT = li.gate_audit(LIB)


def test_every_gate_and_chain_passes_the_audit():
    assert {g: r["errors"] for g, r in AUDIT.items() if r["errors"]} == {}
    chains = [g for g, r in AUDIT.items() if LIB["gates"][g]["kind"] in li.CHAIN_KINDS]
    assert chains and all(AUDIT[g]["entry"] for g in chains), "every chain starts from an entry movement"
    for g in chains:
        for entry in AUDIT[g]["entry"]:
            assert not li._chain_steps(LIB, entry), f"{g}: entry {entry} carries a chain step of its own"


def test_the_hanging_chain_is_three_ordered_steps_from_an_ungated_entry():
    g = LIB["gates"]
    assert "chain_hanging" not in g
    assert g["chain_dead_hang"]["chain_prerequisites"] == ["pull_up_assisted"] and not li.locking_gates(LIB, MV["pull_up_assisted"])
    assert g["chain_hanging_knee_raise"]["chain_prerequisites"] == ["dead_hang"]
    assert g["chain_hanging_leg_raise"]["chain_prerequisites"] == ["hanging_knee_raise"]
    assert "chain_dead_hang" in MV["dead_hang"]["gates"]
    assert "chain_hanging_knee_raise" in MV["hanging_knee_raise"]["gates"] and "chain_hanging_leg_raise" in MV["hanging_leg_raise"]["gates"]
    for step, movement in (("chain_dead_hang", "dead_hang"), ("chain_hanging_knee_raise", "hanging_knee_raise")):
        assert movement not in g[step]["chain_prerequisites"], "a movement is never its own gate's prerequisite"
    assert AUDIT["chain_hanging_leg_raise"]["entry"] == ["pull_up_assisted"]
    for k in ("dead_hang", "hanging_knee_raise", "hanging_leg_raise", "dead_arm_hang", "dead_arm_switch_grip_hang"):
        assert "bw_hanging" in MV[k]["gates"], f"{k}: every hanging movement stays behind the locked bodyweight gate"


def _hang_record(*steps: str) -> list[dict]:
    """Synthetic sessions that meet the named hanging steps' standards (two sessions each, a week apart)."""
    sets = {
        "entry": ("2C37EC5E", [{"reps": 6, "weight_kg": 40.0, "rpe": 8}] * 3),
        "dead_hang": ("B9380898", [{"duration_sec": 30}] * 3),
        "knee_raise": ("08590920", [{"reps": 10, "rpe": 8}] * 3),
    }
    out = []
    for day in ("2026-11-03", "2026-11-10"):
        out.append({"date": day, "exercises": [{"template_id": sets[s][0], "sets": [dict(x) for x in sets[s][1]]} for s in steps]})
    return out


def test_the_hanging_chain_opens_in_order_and_never_past_the_bodyweight_lock():
    def states(*steps):
        gates = eg.evaluate_gates(LIB, None, {"as_of": "2026-11-15", "hevy_workouts": _hang_record(*steps)})
        return {g: gates[g]["state"] for g in ("chain_dead_hang", "chain_hanging_knee_raise", "chain_hanging_leg_raise")}, gates

    locked, _ = states()
    assert set(locked.values()) == {eg.LOCKED}
    one, _ = states("entry")
    assert one == {"chain_dead_hang": eg.UNLOCKED, "chain_hanging_knee_raise": eg.LOCKED, "chain_hanging_leg_raise": eg.LOCKED}
    skipped, _ = states("entry", "knee_raise")  # the knee raise logged without the dead hang opens nothing more
    assert skipped["chain_hanging_leg_raise"] == eg.LOCKED, "chain order: step 3 without step 2"
    every, gates = states("entry", "dead_hang", "knee_raise")
    assert set(every.values()) == {eg.UNLOCKED}
    by_movement = eg.movement_states(LIB, gates)
    for k in ("dead_hang", "hanging_knee_raise", "hanging_leg_raise"):
        assert by_movement[k]["state"] == eg.LOCKED and "bw_hanging" in by_movement[k]["locked_by"], k


def test_nothing_opens_with_no_measured_input():
    gates = eg.evaluate_gates(LIB, None, {"as_of": "2026-11-15"})
    assert [g for g, row in gates.items() if LIB["gates"][g]["locks"] and row["state"] != eg.LOCKED] == []


def _gate_lib(change) -> dict:
    lib = copy.deepcopy(LIB)
    change(lib)
    return lib


def _old_cycle(lib):
    lib["gates"]["chain_hanging_knee_raise"]["chain_prerequisites"] = ["dead_hang", "hanging_knee_raise"]


def _indirect_cycle(lib):
    lib["gates"]["chain_dead_hang"]["chain_prerequisites"] = ["hanging_leg_raise"]  # leg raise -> knee raise -> dead hang -> leg raise


CHAIN_DEFECT_CASES = {
    "a gate that requires the movement it gates (the v0.3.7 defect)": (_old_cycle, "cycle"),
    "an indirect cycle through three gates": (_indirect_cycle, "cycle"),
    "a prerequisite the Hevy record cannot measure": (
        lambda lib: lib["movements"]["tall_high_pull"].pop("template_match"),
        "no Hevy template and no title rule",
    ),
    "a prerequisite that needs equipment confirmed unavailable": (
        lambda lib: lib["movements"]["pull_up_assisted"]["availability"]["home_gym"].update(
            evidence="confirmed_unavailable", state="unavailable"
        ),
        "confirmed unavailable",
    ),
    "a standard no Hevy set can show (the pull-up negative's tempo)": (
        lambda lib: lib["gates"]["chain_pull"]["standard"].update(eccentric_seconds_min=5),
        "no Hevy set records",
    ),
    "a chain gate with no prerequisite": (lambda lib: lib["gates"]["chain_dip"].update(chain_prerequisites=[]), "names no prerequisite"),
    "a prerequisite that is not a library movement": (
        lambda lib: lib["gates"]["chain_dip"].update(chain_prerequisites=["not_a_movement"]),
        "not a library movement",
    ),
    "a gate no movement carries": (
        lambda lib: lib["gates"].update(perf_unused={"kind": "performance_threshold", "locks": True, "chain_prerequisites": []}),
        "no movement carries this gate",
    ),
}


@pytest.mark.parametrize("name", sorted(CHAIN_DEFECT_CASES))
def test_must_fail_each_gate_defect(name):
    change, words = CHAIN_DEFECT_CASES[name]
    errors = li._gate_errors(_gate_lib(change))
    assert any(words in e for e in errors), f"{name}: {errors}"
    assert any(words in e for e in xl.validate(_gate_lib(change))), "the build refuses it"


def test_a_locked_movements_other_names_carry_its_gates():
    """A dead hang or a kettlebell swing logged under another template is the same movement: it carries the same lock, so
    a locked movement is never served — or offered as a fallback — under another name."""
    for other, head in (
        ("dead_arm_hang", "dead_hang"),
        ("dead_arm_switch_grip_hang", "dead_hang"),
        ("swing", "kettlebell_swing"),
        ("double_swings", "kettlebell_swing"),
    ):
        assert set(li.locking_gates(LIB, MV[head])) <= set(li.locking_gates(LIB, MV[other])), other
    assert MV["kettlebell_swing"]["fallbacks"] == [] and MV["dead_hang"]["fallbacks"] == []
    assert "chain_kb_swing" in MV["kettlebell_swing"]["gates"], "the swing stays locked"


def test_bodyweight_gates_say_unset_is_locked_and_state_the_accepted_standard():
    bw = {g: row for g, row in LIB["gates"].items() if row["kind"] == "bodyweight_threshold" and "ref" in row["threshold"]}
    assert set(bw) == set(cur.READINESS_STANDARDS) and len(bw) == 6
    for gid, row in bw.items():
        assert row["threshold_unset"] == "locked" and set(row["threshold"]) == {"ref", "comparison"}, gid
        std = row["readiness_standard"]
        assert std["demonstrate"] and std["confirm"] and "not yet evaluated" in std["status"], gid
        verdict = eg.bodyweight_verdict(gid, row, {"gates": {gid: {"value": None}}}, {"bodyweight": {"mean_lb": 1.0}})
        assert (verdict["state"], verdict["input"]) == (eg.LOCKED, eg.NOT_SET), f"{gid}: an unset threshold must read locked"


# ── 3. loggable ──────────────────────────────────────────────────────────────────────────────────────────────────────
NO_TEMPLATE = sorted(k for k, e in MV.items() if not e.get("template_id"))


def test_every_template_less_movement_has_a_disposition():
    counts = LIB["_provenance"]["integrity"]
    assert len(NO_TEMPLATE) == counts["template_id_null"]
    mapped = [k for k in NO_TEMPLATE if MV[k].get("logs_as")]
    waiting = [k for k in NO_TEMPLATE if not MV[k].get("logs_as")]
    assert len(waiting) == counts["not_loggable"] and len(mapped) + len(waiting) == len(NO_TEMPLATE)
    assert mapped == ["kettlebell_suitcase_carry"]
    for k in waiting:
        assert MV[k]["not_for_you_now"]["reason_code"] == li.UNLOGGABLE_CODE and MV[k]["template_note"], k
    assert {"landmine_squat", "tall_high_pull", "kettlebell_deadlift"} <= set(waiting)


def test_no_unloggable_movement_is_selectable_whatever_its_flags_say():
    """The eligibility function over every movement — and the control: the flag stripped, the engine still refuses."""
    for k, e in MV.items():
        verdict = se.not_for_you_now(e)
        assert (verdict is not None) == bool(e.get("not_for_you_now")), k
        if not li.log_template(e):
            assert verdict is not None, f"{k}: no template, yet selectable"
            stripped = {x: v for x, v in e.items() if x != "not_for_you_now"} | {"needs_custom_template": False}
            assert "not loggable" in str(se.not_for_you_now(stripped)), f"{k}: selectable once its flag is gone"
    bare = copy.deepcopy(LIB)
    bare["movements"]["landmine_squat"]["not_for_you_now"] = None
    assert any("landmine_squat: not loggable" in e for e in xl.validate(bare)), "the build refuses an unflagged unloggable row"


def test_must_fail_the_engine_without_the_structural_check_would_select_it(monkeypatch):
    """The control on the rule itself: with `unloggable` blinded, a template-less row whose flag is gone reads selectable."""
    stripped = {x: v for x, v in MV["landmine_squat"].items() if x != "not_for_you_now"}
    assert se.not_for_you_now(stripped) is not None
    monkeypatch.setattr(li, "unloggable", lambda entry: None)
    assert se.not_for_you_now(stripped) is None


def test_the_kettlebell_deadlift_left_the_sumo_deadlift_template():
    kb = MV["kettlebell_deadlift"]
    assert kb["template_id"] is None and li.unloggable(kb) and se.not_for_you_now(kb)
    assert not [k for k, e in MV.items() if str(e.get("template_id") or "").upper() == "D20D7BBE"], "no row logs under Sumo Deadlift"
    assert kb["template_match"] == {"title_all": ["kettlebell", "deadlift"]}, "its own template, once created, is measured by title"
    assert "D20D7BBE" in inputs.released_ids(inputs.load_templates())


def test_a_canonical_mapping_is_verified_inside_one_family_only():
    row = MV["kettlebell_suitcase_carry"]
    assert row["logs_as"]["movement_id"] == "suitcase_carry" == row["canonical"]
    assert li.log_template(row) == str(MV["suitcase_carry"]["template_id"]).upper() and se.not_for_you_now(row) is None
    bad = copy.deepcopy(LIB)
    bad["movements"]["kettlebell_suitcase_carry"]["logs_as"] = {
        "movement_id": "squat_barbell",
        "template_id": MV["squat_barbell"]["template_id"],
        "why": "x",
    }
    assert any("kettlebell_suitcase_carry: logs_as is verified only inside one canonical family" in e for e in _errors(bad))
    wrong_id = copy.deepcopy(LIB)
    wrong_id["movements"]["kettlebell_suitcase_carry"]["logs_as"]["template_id"] = "AAAAAAAA"
    assert any("logs_as must name a library movement and carry that movement's template_id" in e for e in _errors(wrong_id))


def test_a_created_template_is_a_data_only_change():
    """`deploy/exercise_library_templates.json` `created`: one row makes the movement loggable on the next rebuild."""
    mv = {
        "landmine_squat": {"template_id": None, "not_for_you_now": {"reason_code": li.UNLOGGABLE_CODE, "unlock_condition": "x"}},
        "other": {"template_id": None},
    }
    tids: dict[str, str] = {}
    facts = {"created": {"landmine_squat": {"template_id": "0f0f0f0f-aaaa-bbbb-cccc-121212121212", "title": "Landmine Squat"}}}
    inputs.apply_templates(mv, tids, facts | {"canonical_mappings": {}, "released": {}, "hevy_titles": {}})
    assert mv["landmine_squat"]["template_id"] and mv["landmine_squat"]["not_for_you_now"] is None
    assert tids == {"0F0F0F0F-AAAA-BBBB-CCCC-121212121212": "landmine_squat"}
    assert mv["other"]["not_for_you_now"]["reason_code"] == li.UNLOGGABLE_CODE, "the row with no template is stamped"
    with pytest.raises(SystemExit):
        inputs.apply_templates({}, {}, facts | {"canonical_mappings": {}, "released": {}, "hevy_titles": {}})


def test_every_candidate_records_its_hevy_title_and_a_mismatch_is_refused():
    facts = inputs.load_templates()
    candidates = builder._expansion_list()
    assert inputs.candidate_title_errors(candidates, facts) == []
    assert (
        facts["hevy_titles"]["D5CA687B-C387-4F5B-A5B5-EA7A4BF8E8D6"]["title"] == MV["barbell_high_pulls"]["title"] == "Barbell High Pulls"
    )
    # the v0.3.7 defect: the hang high pull pointed at a near-identical custom id that is a different exercise in Hevy
    wrong = [dict(x, template_id="d5ac3808-b3a8-4044-ba20-53ddb08702d5") if x["key"] == "barbell_high_pulls" else x for x in candidates]
    assert any("barbell_high_pulls" in e and "180 Squat Jumps" in e for e in inputs.candidate_title_errors(wrong, facts))
    unknown = [dict(x, template_id="0a0a0a0a-1111-2222-3333-444444444444") if x["key"] == "barbell_high_pulls" else x for x in candidates]
    assert any("no recorded Hevy title" in e for e in inputs.candidate_title_errors(unknown, facts))
    released = [dict(x, template_id="D20D7BBE") if x["key"] == "kettlebell_deadlift" else x for x in candidates]
    assert any("is released" in e for e in inputs.candidate_title_errors(released, facts))


# ── 4. availability: five evidence states ────────────────────────────────────────────────────────────────────────────
INV = LIB["gym_inventory"]["items"]
DEFERRED = (
    "hip_abduction_machine",
    "hip_adduction_machine",
    "stair_climber",
    "belt_squat_machine",
    "pendulum_squat_machine",
    "incline_press_machine",
)
CARDIO_KIT = ("treadmill", "stationary_bike", "elliptical", "rower", "stair_climber", "ski_erg")


def test_every_equipment_id_and_movement_carries_one_of_the_five_states():
    counts = LIB["_provenance"]["integrity"]
    by_eq = {s: sum(1 for r in INV.values() if r["home_gym"]["evidence"] == s) for s in li.AVAILABILITY_EVIDENCE}
    by_mv = {s: sum(1 for e in MV.values() if e["availability"]["home_gym"]["evidence"] == s) for s in li.AVAILABILITY_EVIDENCE}
    assert by_eq == counts["equipment_by_availability_evidence"] and sum(by_eq.values()) == len(INV)
    assert by_mv == counts["movements_by_availability_evidence"] and sum(by_mv.values()) == len(MV)
    for k, e in MV.items():
        av = e["availability"]["home_gym"]
        assert av["evidence"] == li.worst_evidence([INV[x]["home_gym"]["evidence"] for x in e["equipment"]]), k
        assert av["state"] == li.EVIDENCE_STATE[av["evidence"]] and av["source"], k


def test_cardio_machines_and_conditioning_movements_carry_the_same_states_as_lifts():
    for eid in CARDIO_KIT:
        assert INV[eid]["home_gym"]["evidence"] in li.AVAILABILITY_EVIDENCE and "basic" not in INV[eid]["home_gym"], eid
    cardio = [k for k, e in MV.items() if e["category"] == "conditioning"]
    assert len(cardio) >= 10
    for k in cardio:
        av = MV[k]["availability"]["home_gym"]
        assert av["evidence"] in li.AVAILABILITY_EVIDENCE and av["state"] == li.EVIDENCE_STATE[av["evidence"]], k
    assert MV["stair_machine"]["availability"]["home_gym"]["state"] == "unknown", "the deferred stair machine is never served"


def test_only_confirmed_or_recent_equipment_is_available_and_deferrals_hold():
    assert {li.EVIDENCE_STATE[s] for s in ("historical_only", "unknown")} == {"unknown"}
    for eid in DEFERRED:
        row = INV[eid]["home_gym"]
        assert (row["state"], row["evidence"]) == ("unknown", "unknown") and "deferred" in row["source"], eid
    assert INV["preacher_machine"]["home_gym"]["evidence"] == "confirmed_unavailable"
    for k, e in MV.items():
        if set(e["equipment"]) & set(DEFERRED):
            assert e["availability"]["home_gym"]["state"] != "available", f"{k}: deferred equipment is never assumed"
            assert se.availability(e, LIB, None) is not None, k
    for eid, row in INV.items():
        if row["home_gym"].get("basic"):
            assert eid in li.BASIC_EQUIPMENT and row["home_gym"]["evidence"] in (
                "recent_inferred",
                "owner_confirmed",
                "confirmed_unavailable",
            )


def test_no_log_date_rides_the_availability_data():
    import re

    day = re.compile(r"\d{4}-\d{2}-\d{2}")
    assert [x for x, r in INV.items() if day.search(r["home_gym"]["source"]) and "owner" not in r["home_gym"]["source"]] == []
    assert [k for k, e in MV.items() if day.search(e["availability"]["home_gym"]["source"])] == []


def test_the_builder_derives_the_five_states_from_the_history_window():
    mv = {
        "recent": {"equipment": ["leg_curl_seated"], "history": {"last_done": "2026-10-01"}},
        "old": {"equipment": ["hack_squat_machine"], "history": {"last_done": "2024-01-01"}},
        "edge": {"equipment": ["smith_machine"], "history": {"last_done": "2025-11-11"}},
        "never": {"equipment": ["ski_erg"]},
        "basic_old": {"equipment": ["weight_plate"], "history": {"last_done": "2022-01-01"}},
        "seeded": {"equipment": ["preacher_machine"], "history": {"last_done": "2026-10-01"}},
        "confirmed": {"equipment": ["pullover_machine"]},
    }
    seeds = dict(cur.SEEDED_AVAILABILITY) | {
        "pullover_machine": {"evidence": "owner_confirmed", "source": "owner confirmation (synthetic)"}
    }
    inv = inputs.home_gym_inventory(mv, {"last": "2026-11-11"}, seeds)
    got = {x: (r["home_gym"]["evidence"], r["home_gym"]["state"]) for x, r in inv.items()}
    assert got == {
        "leg_curl_seated": ("recent_inferred", "available"),
        "hack_squat_machine": ("historical_only", "unknown"),
        "smith_machine": ("recent_inferred", "available"),  # the window's first day counts
        "ski_erg": ("unknown", "unknown"),
        "weight_plate": ("recent_inferred", "available"),  # a basic class is inferred as a class
        "preacher_machine": ("confirmed_unavailable", "unavailable"),  # an owner note wins over a recent log
        "pullover_machine": ("owner_confirmed", "available"),
    }
    assert inputs.movement_availability({"equipment": ["leg_curl_seated", "hack_squat_machine"]}, inv)["evidence"] == "historical_only"
    assert inputs.movement_availability({"equipment": ["leg_curl_seated", "weight_plate"]}, inv)["state"] == "available"


def test_must_fail_a_historical_machine_marked_available():
    eid = next(x for x, r in INV.items() if r["home_gym"]["evidence"] == "historical_only")
    bad = copy.deepcopy(LIB)
    bad["gym_inventory"]["items"][eid]["home_gym"]["state"] = "available"
    assert any(f"gym_inventory.{eid}: state 'available' does not follow" in e for e in xl.validate(bad))
    key = next(k for k, e in MV.items() if e["availability"]["home_gym"]["evidence"] == "historical_only")
    worse = copy.deepcopy(LIB)
    worse["movements"][key]["availability"]["home_gym"].update(evidence="recent_inferred", state="available")
    assert any(f"movements.{key}: availability evidence" in e for e in xl.validate(worse))


# ── the approval path: an unset bodyweight threshold is locked AND valid ─────────────────────────────────────────────
def _overlay(bodyweight_value=None) -> dict:
    """The overlay the writer builds for the committed library: every bodyweight threshold unset (the real state)."""
    import write_exercise_library_overlay as w

    gates = w.gate_rows(LIB, CHARTER, None)
    for gid, row in gates.items():
        if row["value"] is None and gid in cur.READINESS_STANDARDS:
            row["value"] = bodyweight_value
        elif row["value"] is None:
            row["value"], row["source"] = 1.0, "fixture"  # the charter-owned number, synthetic
    return {"gates": gates}


def test_the_private_check_accepts_every_bodyweight_gate_locked_with_no_threshold():
    ov = _overlay()
    assert sorted(g for g, r in ov["gates"].items() if r["value"] is None) == sorted(cur.READINESS_STANDARDS)
    assert xl.private_gate_gaps(LIB, ov) == []
    assert xl.unset_thresholds(LIB, ov) == sorted(cur.READINESS_STANDARDS)
    for gid in cur.READINESS_STANDARDS:  # and each still READS locked
        assert eg.bodyweight_verdict(gid, LIB["gates"][gid], ov, {"bodyweight": {"mean_lb": 1.0}})["state"] == eg.LOCKED


@pytest.mark.parametrize(
    "name,change",
    [
        ("a threshold that is set but not a number", lambda ov: ov["gates"]["bw_dip"].update(value="soon")),
        ("a set threshold with no comparator", lambda ov: ov["gates"]["bw_pull"].update(value=1.0, comparator=None)),
        ("an unset threshold with no measured input", lambda ov: ov["gates"]["bw_nordic"].update(measured_input="")),
        ("a chain gate with no standard", lambda ov: ov["gates"]["chain_dead_hang"].update(value=None)),
        ("the charter-owned threshold unread", lambda ov: ov["gates"]["bw_power_clean"].update(value=None)),
        ("a gate with no private row", lambda ov: ov["gates"].pop("chain_hanging_knee_raise")),
    ],
)
def test_must_fail_a_gate_that_could_open_is_never_under_specified(name, change):
    ov = _overlay()
    change(ov)
    assert xl.private_gate_gaps(LIB, ov), name


def test_approval_succeeds_with_every_readiness_gate_locked_on_a_copy(tmp_path):
    """The sanctioned approval step, run on a COPY (the committed library is never touched): it succeeds with the six
    bodyweight thresholds unset, and refuses the same copy once a gate that could open is under-specified."""
    import approve_exercise_library as appr

    lib_path, ov_path, bad_path = tmp_path / "lib.json", tmp_path / "overlay.json", tmp_path / "bad.json"
    lib_path.write_text(json.dumps(LIB))
    ov_path.write_text(json.dumps(_overlay()))
    bad = _overlay()
    bad["gates"]["bw_pull"].update(value="soon")
    bad_path.write_text(json.dumps(bad))
    before = lib_path.read_text()
    lines: list[str] = []
    assert appr.approve("test", str(lib_path), str(bad_path), today="2026-11-14", out=lines.append) == 1
    assert lib_path.read_text() == before and any("REFUSED" in x for x in lines)
    lines.clear()
    assert appr.approve("owner ruling (test)", str(lib_path), str(ov_path), today="2026-11-14", out=lines.append) == 0
    assert any("LOCKED with no threshold set" in x and "bw_pull" in x for x in lines)
    after = json.loads(lib_path.read_text())
    assert (after["status"], after["approved_on"]) == ("approved", "2026-11-14")
    assert json.loads((REPO / "config" / "exercise_library.json").read_text())["status"] == "proposed"
    gates = eg.evaluate_gates(after, _overlay(), {"as_of": "2026-11-15", "bodyweight": {"mean_lb": 1.0}})
    assert all(gates[g]["state"] == eg.LOCKED for g in cur.READINESS_STANDARDS), "approved, and every bodyweight gate still locked"


# ── served weeks: nothing unloggable, unavailable, deferred or gated is ever served ───────────────────────────────────
def _week(name: str, cap: bool, mutate=None, gym: str | None = "full_club"):
    """One synthetic profile's LIVE week (an in-memory approved copy; the committed library is never touched). `gym`: the
    fixture's synthetic full club (the historical machines present), or None for the library's own states, as the owner's
    week reads them."""
    import sample_weeks_5861 as sw

    kept = dict(sw.SETTINGS)
    sw.SETTINGS.clear()
    sw.SETTINGS["session_cap_includes_cardio"] = cap
    try:
        profile = sw.load_profiles()[name] | {"gym": gym}
        world = sw.build_world(profile, "approved")
        if mutate:
            mutate(world)
        return world, sw.generate_week(profile, "approved", world)
    finally:
        sw.SETTINGS.clear()
        sw.SETTINGS.update(kept)


def _served(world: dict, week: dict) -> list[tuple[str, str, dict | None]]:
    to_lib = se.key_index(world["lib"], world["catalog"]["movements"])["to_lib"]
    return [(s["role"], x["key"], world["lib"]["movements"].get(to_lib.get(x["key"]) or "")) for s in week["sessions"] for x in s["lifts"]]


def _unservable(world: dict, week: dict) -> list[str]:
    """Offenders in a served week: a lift the library cannot place, that is not loggable, whose equipment is not
    `available` in this world, that sits behind a locked gate, or that needs equipment the owner deferred."""
    out = []
    for role, key, e in _served(world, week):
        if e is None:
            out.append(f"{role}/{key}: no library entry")
            continue
        if li.unloggable(e):
            out.append(f"{role}/{key}: not loggable")
        why = se.availability(e, world["lib"], world["overlay"])
        if why:
            out.append(f"{role}/{key}: {why}")
        if li.locking_gates(world["lib"], e):
            out.append(f"{role}/{key}: behind a locked gate")
        if set(e.get("equipment") or []) & set(DEFERRED):
            out.append(f"{role}/{key}: deferred equipment")
    return out


PROFILES = (
    "a_large_deficit_experienced",
    "b_shoulder_flag_low_recovery",
    "c_equipment_limited",
    "d_stalled_anchor_adherence_dip",
    "e_short_week",
    "f_high_fatigue_poor_sleep",
)


@pytest.mark.parametrize("name", PROFILES)
def test_no_served_week_names_an_unloggable_unavailable_deferred_or_gated_movement(name):
    for cap in (True, False):
        world, week = _week(name, cap)
        assert sum(len(s["lifts"]) for s in week["sessions"]) > 0
        assert _unservable(world, week) == [], f"{name} cap={cap}"


HISTORICAL_IN_TODAYS_PROGRAM = {"machine_row", "machine_shoulder_press", "standing_calf_raise_machine"}


def test_a_machine_known_only_from_old_logs_is_swapped_out_of_the_live_week():
    """Owner ruling 2026-11-14: availability fails SAFE. With the library's own states (no synthetic club), the machines
    today's program names but the logs only show as historical are never served: the live fit swaps each for an available
    lift and says so. Control: the same week in a full club (the machines confirmed) serves them."""
    world, week = _week("a_large_deficit_experienced", True, gym=None)
    served = {k for _r, k, _e in _served(world, week)}
    assert not served & HISTORICAL_IN_TODAYS_PROGRAM and _unservable(world, week) == []
    lines = [ln for s in week["sessions"] for ln in s["live_fit"] or [] if ln.startswith("swapped (live)")]
    assert any("Seated Row (Machine) ->" in ln and "unknown" in ln for ln in lines), lines
    assert any("Seated Shoulder Press (Machine) ->" in ln and "unknown" in ln for ln in lines), lines
    club, confirmed = _week("a_large_deficit_experienced", True)
    assert {k for _r, k, _e in _served(club, confirmed)} & HISTORICAL_IN_TODAYS_PROGRAM, "control: confirmed machines are served"


def test_a_served_movement_that_loses_its_template_is_no_longer_served():
    """The unavailable-template case, end to end. An accessory the baseline week serves has its Hevy template taken away
    with NO flag set (no `not_for_you_now`, no `needs_custom_template`): the structural rule alone must keep it out of the
    week, and whatever takes its slot is itself servable. Control: with the rule blinded, the template-less row is served."""
    name = "a_large_deficit_experienced"
    world0, week0 = _week(name, True)
    slots = {x["key"] for s in week0["sessions"] for x in s["lifts"] if str(x["tag"] or "").startswith(("slot", "accessory", "selection"))}
    picked = sorted(k for _r, k, e in _served(world0, week0) if e is not None and k in slots and e.get("family") != "strength_anchor")
    assert picked, "the baseline week serves at least one selected accessory"
    victim = picked[0]

    def strip(world):
        to_lib = se.key_index(world["lib"], world["catalog"]["movements"])["to_lib"]
        e = world["lib"]["movements"][to_lib[victim]]
        e["template_id"], e["not_for_you_now"] = None, None
        e.pop("logs_as", None)

    world1, week1 = _week(name, True, strip)
    assert victim not in {k for _r, k, _e in _served(world1, week1)}, f"{victim} is still served without a Hevy template"
    assert _unservable(world1, week1) == []
    from unittest.mock import patch

    with patch.object(li, "unloggable", lambda entry: None):  # must-fail control: the structural rule switched off
        world2, week2 = _week(name, True, strip)
    assert victim in {k for _r, k, _e in _served(world2, week2)}, "control: without the rule the template-less row is served"
