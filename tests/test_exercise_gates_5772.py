"""tests/test_exercise_gates_5772.py — the exercise library's gates, evaluated from measured inputs (#5772).

The owner's rules (epic #5770, 2026-11-11), each with a must-fail control:
  * an unknown input reads LOCKED, and says so (`input: "unknown"`) — never a third state a consumer could pass;
  * a bodyweight gate whose owner-set value is null is LOCKED, reason "threshold not set by owner";
  * chain order — a later step logged without the earlier one opens nothing;
  * a newly unlocked movement is announced to the coach exactly ONCE (claim-once row; a second read is silent);
  * a clinical cue never locks anything and is never an intensity gate.
Plus: every gate in the committed library has an evaluator (a gate kind the evaluator cannot compute reds the build),
the leg's log/summary carries ids + states + counts only (no bodyweight), a PROPOSED library announces nothing, and the
panel-grade wiring is fail-soft. Every date is a literal — nothing here reads the clock.
"""

from __future__ import annotations

import copy
import json
import os
import pathlib
import sys
from typing import Any

_REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "lambdas"))
sys.path.insert(0, str(_REPO))
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from training import exercise_gates as eg  # noqa: E402

_LIB = json.loads((_REPO / "config" / "exercise_library.json").read_text())
_CHARTER = json.loads((_REPO / "config" / "training_charter.json").read_text())
AS_OF = "2026-11-15"  # a Sunday


# ── a small synthetic library: one chain (assisted -> negative -> pull-up), a bodyweight gate, a cue ──────────────────
def _lib(status: str = "approved") -> dict[str, Any]:
    std_assist = {"sets": 3, "reps_min": 6, "sessions_min": 2}
    return {
        "version": "0.1.0",
        "status": status,
        "approved_on": "2026-01-02",  # #5861 fix round 11: live needs the approval day
        "gym_inventory": {"items": {"bar": {"home_gym": {"state": "available"}}, "odd": {"home_gym": {"state": "unknown"}}}},
        "gates": {
            "pain_flag_exclusion": {"kind": "pain_flag_exclusion", "locks": True, "applies_to": "all", "unlock_condition": "no pain"},
            "equipment_available": {"kind": "equipment_available", "locks": True, "applies_to": "all", "unlock_condition": "kit"},
            "cue_breathing": {"kind": "clinical_cue", "locks": False, "cue": "Breathe through every rep.", "unlock_condition": "cue"},
            "bw_pull": {
                "kind": "bodyweight_threshold",
                "locks": True,
                "threshold": {"ref": "overlay:gate_thresholds.bw_pull", "comparison": "at_or_under"},
                "unlock_condition": "under the private threshold",
            },
            "chain_negative": {
                "kind": "chain_prerequisite",
                "locks": True,
                "standard": std_assist,
                "chain_prerequisites": ["assisted"],
                "unlock_condition": "assisted 3x6 twice",
            },
            "chain_pull": {
                "kind": "chain_prerequisite",
                "locks": True,
                "standard": {"sets": 3, "reps_min": 3, "sessions_min": 2},
                "chain_prerequisites": ["negative"],
                "unlock_condition": "negatives 3x3 twice",
            },
        },
        "movements": {
            "assisted": {"title": "Assisted Pull Up", "template_id": "AAAA0001", "equipment": ["bar"], "gates": ["cue_breathing"]},
            "negative": {"title": "Pull Up Negative", "template_id": "AAAA0002", "equipment": ["bar"], "gates": ["chain_negative"]},
            "pull_up": {
                "title": "Pull Up",
                "template_id": "AAAA0003",
                "equipment": ["bar"],
                "gates": ["bw_pull", "chain_pull", "cue_breathing"],
            },
            "odd_machine": {"title": "Odd Machine", "template_id": "AAAA0004", "equipment": ["odd"], "gates": []},
        },
    }


def _overlay(value: float | None) -> dict[str, Any]:
    return {"gates": {"bw_pull": {"kind": "bodyweight_threshold", "value": value}}, "availability_learned": {}}


def _sets(n: int, reps: int, rpe: float = 7) -> list[dict[str, Any]]:
    return [{"reps": reps, "weight_kg": 10, "rpe": rpe, "type": "normal"} for _ in range(n)]


def _workout(day: str, tid: str, sets, notes: str = "") -> dict[str, Any]:
    return {"date": day, "exercises": [{"template_id": tid, "sets": sets, "notes": notes}]}


def _measured(workouts=None, mean_lb=None, **kw) -> dict[str, Any]:
    return {
        "as_of": AS_OF,
        "bodyweight": {"mean_lb": mean_lb, "state": "measured" if mean_lb else "unread"},
        "hevy_workouts": workouts,
        **kw,
    }


# ── unknown => locked, said so ───────────────────────────────────────────────────────────────────────────────────────
def test_every_unknown_input_reads_locked_and_says_so():
    gates = eg.evaluate_gates(_lib(), None, _measured(workouts=None, mean_lb=None))
    for gid, row in gates.items():
        if row["kind"] == "clinical_cue":
            continue
        assert row["state"] == eg.LOCKED, gid
        assert row["input"] == eg.UNKNOWN, gid
        assert "unknown" in row["reason"] or row.get("by_movement"), gid
    assert set(eg.STATES) == {"unlocked", "locked"}  # no third state a consumer could treat as a pass


def test_unknown_control_the_same_gates_open_once_measured():
    """The positive control: without it, a gate that never opens would pass the test above."""
    wk = [_workout(d, t, _sets(3, 8)) for d in ("2026-11-03", "2026-11-10") for t in ("AAAA0001", "AAAA0002")]
    gates = eg.evaluate_gates(_lib(), _overlay(300), _measured(workouts=wk, mean_lb=250))
    assert gates["chain_negative"]["state"] == eg.UNLOCKED
    assert gates["chain_pull"]["state"] == eg.UNLOCKED
    assert gates["bw_pull"]["state"] == eg.UNLOCKED
    assert gates["pain_flag_exclusion"]["state"] == eg.UNLOCKED


def test_unlogged_rpe_and_unmeasured_assistance_are_not_evidence():
    lib = _lib()
    lib["gates"]["chain_negative"]["standard"] = {
        "sets": 1,
        "reps_min": 6,
        "sessions_min": 1,
        "assistance_fraction_max": 0.25,
        "rpe_max": 8,
    }
    no_rpe = [_workout("2026-11-10", "AAAA0001", [{"reps": 8, "weight_kg": 10, "rpe": None}])]
    assert eg.evaluate_gates(lib, None, _measured(no_rpe, mean_lb=250))["chain_negative"]["state"] == eg.LOCKED
    with_rpe = [_workout("2026-11-10", "AAAA0001", [{"reps": 8, "weight_kg": 10, "rpe": 7}])]
    unknown_bw = eg.evaluate_gates(lib, None, _measured(with_rpe, mean_lb=None))["chain_negative"]
    assert unknown_bw["state"] == eg.LOCKED and unknown_bw["input"] == eg.UNKNOWN
    assert eg.evaluate_gates(lib, None, _measured(with_rpe, mean_lb=250))["chain_negative"]["state"] == eg.UNLOCKED


# ── null owner value => locked "threshold not set by owner" ──────────────────────────────────────────────────────────
def test_a_null_owner_threshold_locks_with_its_reason():
    row = eg.evaluate_gates(_lib(), _overlay(None), _measured(workouts=[], mean_lb=150))["bw_pull"]
    assert row["state"] == eg.LOCKED and row["input"] == eg.NOT_SET
    assert row["reason"] == "threshold not set by owner"
    assert row["value_seen"] is None  # no bodyweight on a gate it could not compare


def test_a_set_owner_threshold_compares_the_7d_mean():
    under = eg.evaluate_gates(_lib(), _overlay(200), _measured(workouts=[], mean_lb=199.9))["bw_pull"]
    over = eg.evaluate_gates(_lib(), _overlay(200), _measured(workouts=[], mean_lb=200.1))["bw_pull"]
    assert under["state"] == eg.UNLOCKED and over["state"] == eg.LOCKED and over["input"] == eg.MEASURED


def test_the_charter_owns_the_power_clean_number():
    g = {"kind": "bodyweight_threshold", "threshold": {"charter_ref": "gated_movements.power_clean.revisit_at_lb"}}
    revisit = _CHARTER["gated_movements"]["power_clean"]["revisit_at_lb"]
    m = {"charter": _CHARTER, "bodyweight": {"mean_lb": revisit - 1}}
    assert eg.bodyweight_verdict("bw_power_clean", g, None, m)["state"] == eg.UNLOCKED
    assert eg.bodyweight_verdict("bw_power_clean", g, None, {**m, "bodyweight": {"mean_lb": revisit + 1}})["state"] == eg.LOCKED
    assert eg.bodyweight_verdict("bw_power_clean", g, None, {"bodyweight": {"mean_lb": 1}})["input"] == eg.UNKNOWN


# ── chain order ─────────────────────────────────────────────────────────────────────────────────────────────────────
def test_chain_order_a_later_step_alone_opens_nothing():
    negatives_only = [_workout(d, "AAAA0002", _sets(3, 5)) for d in ("2026-11-03", "2026-11-10")]
    gates = eg.evaluate_gates(_lib(), _overlay(300), _measured(negatives_only, mean_lb=250))
    assert gates["chain_negative"]["state"] == eg.LOCKED
    assert gates["chain_pull"]["state"] == eg.LOCKED
    assert "chain order" in gates["chain_pull"]["reason"]
    both = negatives_only + [_workout(d, "AAAA0001", _sets(3, 6)) for d in ("2026-11-04", "2026-11-11")]
    assert eg.evaluate_gates(_lib(), _overlay(300), _measured(both, mean_lb=250))["chain_pull"]["state"] == eg.UNLOCKED


def test_a_chain_step_outside_the_lookback_does_not_count():
    old = [_workout(d, t, _sets(3, 8)) for d in ("2026-06-01", "2026-06-08") for t in ("AAAA0001", "AAAA0002")]
    assert eg.evaluate_gates(_lib(), None, _measured(old, mean_lb=250))["chain_negative"]["state"] == eg.LOCKED


def test_a_pain_flag_locks_until_a_pain_free_trial_set():
    flagged = [_workout("2026-11-05", "AAAA0004", _sets(2, 10), notes="sharp pain in my elbow")]
    gates = eg.evaluate_gates(_lib(), None, _measured(flagged, mean_lb=250))
    assert "odd_machine" in gates["pain_flag_exclusion"]["by_movement"]
    trial = flagged + [_workout("2026-11-12", "AAAA0004", _sets(1, 10, rpe=5))]
    assert "odd_machine" not in eg.evaluate_gates(_lib(), None, _measured(trial, mean_lb=250))["pain_flag_exclusion"]["by_movement"]


def test_unknown_equipment_locks_the_movement():
    gates = eg.evaluate_gates(_lib(), None, _measured([], mean_lb=250))
    states = eg.movement_states(_lib(), gates)
    assert states["odd_machine"]["state"] == eg.LOCKED and "equipment_available" in states["odd_machine"]["locked_by"]
    assert gates["equipment_available"]["by_movement"]["odd_machine"]["input"] == eg.UNKNOWN


# ── clinical cue: never a lock ──────────────────────────────────────────────────────────────────────────────────────
def test_a_clinical_cue_never_locks_even_with_every_input_unknown():
    lib = _lib()
    lib["gates"]["cue_breathing"]["locks"] = True  # a mis-set flag must not turn a cue into a lock
    gates = eg.evaluate_gates(lib, None, {})
    assert gates["cue_breathing"]["state"] == eg.UNLOCKED and gates["cue_breathing"]["input"] == eg.CUE
    states = eg.movement_states(lib, gates)
    assert all("cue_breathing" not in s["locked_by"] for s in states.values())
    assert states["assisted"]["cues"] == ["Breathe through every rep."]
    live = eg.evaluate_gates(_LIB, None, {})
    for gid, g in _LIB["gates"].items():
        if g["kind"] == "clinical_cue":
            assert live[gid]["state"] == eg.UNLOCKED
            assert all(gid not in s["locked_by"] for s in eg.movement_states(_LIB, live).values())


# ── the committed library: every gate has an evaluator ──────────────────────────────────────────────────────────────
def test_every_committed_gate_kind_is_evaluated():
    wk = [_workout("2026-11-10", "4F5866F8", _sets(3, 12))]
    m = {**_measured(wk, mean_lb=250), "charter": _CHARTER, "run_gate": {"gate_state": "closed"}}
    gates = eg.evaluate_gates(_LIB, {"gates": {}, "availability_learned": {}}, m)
    assert set(gates) == set(_LIB["gates"])
    no_evaluator = [gid for gid, r in gates.items() if "no evaluator" in str(r["reason"]) or "names no movement" in str(r["reason"])]
    assert no_evaluator == []
    assert {r["state"] for r in gates.values()} <= set(eg.STATES)
    assert all(r["unlock_condition"] for r in gates.values())


def test_newly_unlocked_has_a_baseline_and_compares_own_gates():
    states = {"pull_up": {"own_gates": ["bw_pull"], "own_gates_open": True, "state": "unlocked"}}
    assert eg.newly_unlocked(None, states) == []  # the first evaluation is the baseline
    assert eg.newly_unlocked({"pull_up": {"own_gates_open": False}}, states) == [{"movement_id": "pull_up", "gates": ["bw_pull"]}]
    assert eg.newly_unlocked({"pull_up": {"own_gates_open": True}}, states) == []


# ── the leg: announce once, proposed holds, logs carry no body number ─────────────────────────────────────────────────
def _client_error():
    from botocore.exceptions import ClientError

    return ClientError({"Error": {"Code": "ConditionalCheckFailedException"}}, "Op")


def _match(cond, item) -> bool:
    ex = cond.get_expression()
    op, vals = ex["operator"], ex["values"]
    if op == "AND":
        return _match(vals[0], item) and _match(vals[1], item)
    name = vals[0].name
    v = item.get(name)
    if op == "=":
        return v == vals[1]
    if op == "begins_with":
        return str(v).startswith(vals[1])
    if op == "BETWEEN":
        return vals[1] <= str(v) <= vals[2]
    raise AssertionError(op)


class _Table:
    def __init__(self):
        self.items: dict[tuple[str, str], dict[str, Any]] = {}
        self.puts: list[str] = []

    def put_item(self, Item, ConditionExpression=None):
        key = (Item["pk"], Item["sk"])
        if ConditionExpression == "attribute_not_exists(sk)" and key in self.items:
            raise _client_error()
        self.items[key] = Item
        self.puts.append(Item["sk"])

    def update_item(self, Key, ConditionExpression, ExpressionAttributeValues, **_kw):
        it = self.items.get((Key["pk"], Key["sk"]))
        if it is None or it.get("status") != ExpressionAttributeValues[":p"]:
            raise _client_error()
        it["status"] = ExpressionAttributeValues[":a"]
        it["announced_at"] = ExpressionAttributeValues[":t"]

    def query(self, KeyConditionExpression, ScanIndexForward=True, Limit=None, **_kw):
        rows = sorted(
            (i for i in self.items.values() if _match(KeyConditionExpression, i)), key=lambda i: i["sk"], reverse=not ScanIndexForward
        )
        return {"Items": rows[:Limit] if Limit else rows}


def _patch_gather(monkeypatch, lib, measured, overlay):
    from mcp import exercise_gates_leg as leg

    monkeypatch.setattr(leg, "gather", lambda ws, we: (copy.deepcopy(lib), measured, overlay, {"hevy": "ok", "withings": "ok"}))
    import experiment.phase_taxonomy as tax

    monkeypatch.setattr(tax, "experiment_stamp_for", lambda pk, sk="", **kw: {})
    return leg


_OPEN_WK = [_workout(d, t, _sets(3, 8)) for d in ("2026-11-03", "2026-11-10") for t in ("AAAA0001", "AAAA0002")]


def test_a_newly_unlocked_movement_is_announced_exactly_once(monkeypatch):
    t = _Table()
    leg = _patch_gather(monkeypatch, _lib(), _measured([], mean_lb=250), _overlay(300))
    first = leg.evaluate_week("2026-11-08", today="2026-11-09", table=t)  # baseline: pull_up locked (no chain)
    assert first["announce"].startswith("baseline") and first["newly_unlocked"] == []
    _patch_gather(monkeypatch, _lib(), _measured(_OPEN_WK, mean_lb=250), _overlay(300))
    second = leg.evaluate_week(AS_OF, today="2026-11-16", table=t)
    assert second["newly_unlocked"] == ["negative", "pull_up"]
    assert t.puts[-1] == "EXGATE#EVAL#2026-11-09"  # the EVAL row is written LAST
    sk = leg.announce_sk("pull_up", ["bw_pull", "chain_pull"])
    assert t.items[(leg._pk(), sk)]["status"] == leg.PENDING

    dry = leg.unlock_announcements_field(claim_rows=False, table=t)
    assert len(dry["lines"]) == 2 and t.items[(leg._pk(), sk)]["status"] == leg.PENDING  # a dry read claims nothing
    said = leg.unlock_announcements_field(claim_rows=True, table=t)
    assert sorted(said["movements"]) == ["negative", "pull_up"] and said["state"] == "measured"
    assert any("Pull Up" in line and "Breathe" in line for line in said["lines"])
    again = leg.unlock_announcements_field(claim_rows=True, table=t)
    assert again["lines"] == [] and again["state"] == "absent"  # ONCE

    # a re-run of the same week (or the next) never re-creates a claimed record
    leg.evaluate_week(AS_OF, today="2026-11-16", table=t)
    assert leg.unlock_announcements_field(claim_rows=True, table=t)["lines"] == []
    assert t.items[(leg._pk(), sk)]["status"] == leg.ANNOUNCED


def test_announce_once_control_a_racing_second_claim_loses():
    from mcp import exercise_gates_leg as leg

    t = _Table()
    t.items[(leg._pk(), "EXGATE#ANNOUNCE#x#g")] = {"pk": leg._pk(), "sk": "EXGATE#ANNOUNCE#x#g", "status": "pending", "line": "L"}
    assert leg.claim(t, "EXGATE#ANNOUNCE#x#g") is True
    assert leg.claim(t, "EXGATE#ANNOUNCE#x#g") is False


def test_a_proposed_library_announces_nothing(monkeypatch):
    t = _Table()
    leg = _patch_gather(monkeypatch, _lib("proposed"), _measured([], mean_lb=250), _overlay(300))
    leg.evaluate_week("2026-11-08", today="2026-11-09", table=t)
    _patch_gather(monkeypatch, _lib("proposed"), _measured(_OPEN_WK, mean_lb=250), _overlay(300))
    out = leg.evaluate_week(AS_OF, today="2026-11-16", table=t)
    assert out["newly_unlocked"] and out["announce"].startswith("held: library status proposed")
    assert not any(sk.startswith(leg.SK_ANNOUNCE) for _pk, sk in t.items)


def test_the_leg_summary_and_log_carry_no_body_number(monkeypatch, caplog):
    t = _Table()
    leg = _patch_gather(monkeypatch, _lib(), _measured(_OPEN_WK, mean_lb=247.3), _overlay(251.7))
    monkeypatch.setattr(leg, "_table", lambda table: t)
    from common import pacific_time

    monkeypatch.setattr(pacific_time, "pacific_today", lambda: "2026-11-16")
    with caplog.at_level("INFO", logger="exercise_gates"):
        out = leg.weekly_leg()
    assert out["outcome"] == "written" and out["sk"] == "EXGATE#EVAL#2026-11-09"
    text = json.dumps(out) + caplog.text
    assert "247.3" not in text and "251.7" not in text  # must-fail: a value_seen in the summary or log reds this
    assert "bw_pull" in caplog.text  # ids and states ARE logged
    stored = t.items[(leg._pk(), "EXGATE#EVAL#2026-11-09")]
    assert stored["tier"] == "owner_only" and stored["counts"]["unlocked"] >= 1


def test_the_panel_grade_leg_is_fail_soft(monkeypatch):
    from mcp import exercise_gates_leg as leg, panel_weekly_grade as pwg

    def boom(*a, **k):
        raise RuntimeError("no table")

    monkeypatch.setattr(leg, "evaluate_week", boom)
    out = pwg._exercise_gates_leg("2026-11-15")
    assert out["outcome"] == "failed" and out["error"] == "RuntimeError"


def test_plan_stage_two_never_claims(monkeypatch):
    from mcp import exercise_gates_leg as leg, tools_plan

    seen = {}
    monkeypatch.setattr(leg, "unlock_announcements_field", lambda claim_rows: seen.setdefault("claim", claim_rows) or {"lines": []})
    monkeypatch.setattr(tools_plan, "_training_phase_field", lambda: {"state": "absent"})
    tools_plan._training_fields(stage_1=False, dry_run=False)
    assert seen["claim"] is False
    seen.clear()
    tools_plan._training_fields(stage_1=True, dry_run=True)
    assert seen["claim"] is False
    seen.clear()
    tools_plan._training_fields(stage_1=True, dry_run=False)
    assert seen["claim"] is True


def test_evaluate_gates_never_raises_on_missing_inputs():
    for bad in (None, {}, {"as_of": AS_OF}):
        gates = eg.evaluate_gates(_LIB, None, bad)
        assert all(r["state"] == eg.LOCKED for r in gates.values() if r["kind"] != "clinical_cue"), bad


# ── owner ruling 2026-11-11 (#5810): the KB swing opens on exactly 2 logged KB-deadlift sessions ─────────────────────
def _kb_dl(day: str, name: str = "Kettlebell Deadlift") -> dict[str, Any]:
    return {"date": day, "exercises": [{"template_id": "C0FFEE01", "name": name, "sets": _sets(2, 10), "notes": ""}]}


def test_kb_swing_opens_on_two_kb_deadlift_sessions_and_not_one():
    assert _LIB["gates"]["chain_kb_swing"]["standard"] == {"sessions_min": 2}
    one = eg.evaluate_gates(_LIB, None, _measured([_kb_dl("2026-11-10")], mean_lb=250))["chain_kb_swing"]
    assert one["state"] == eg.LOCKED and one["input"] == eg.MEASURED
    two = eg.evaluate_gates(
        _LIB, None, _measured([_kb_dl("2026-11-03"), _kb_dl("2026-11-10", "KB Romanian Deadlift (Kettlebell)")], mean_lb=250)
    )
    assert two["chain_kb_swing"]["state"] == eg.UNLOCKED
    swing = eg.movement_states(_LIB, two)["kettlebell_swing"]
    assert "chain_kb_swing" not in swing["locked_by"]


def test_the_kb_title_rule_needs_both_words():
    dumbbell = [_kb_dl("2026-11-03", "Deadlift (Dumbbell)"), _kb_dl("2026-11-10", "Kettlebell Swing")]
    assert eg.evaluate_gates(_LIB, None, _measured(dumbbell, mean_lb=250))["chain_kb_swing"]["state"] == eg.LOCKED


def test_only_a_pain_class_note_locks_a_movement():
    sore = [_workout("2026-11-05", "AAAA0004", _sets(2, 10), notes="my elbow aches a little")]  # the #5800 class: discomfort
    assert eg.evaluate_gates(_lib(), None, _measured(sore, mean_lb=250))["pain_flag_exclusion"]["by_movement"] == {}
    pain = [_workout("2026-11-05", "AAAA0004", _sets(2, 10), notes="sharp pain in my elbow")]
    assert "odd_machine" in eg.evaluate_gates(_lib(), None, _measured(pain, mean_lb=250))["pain_flag_exclusion"]["by_movement"]


# ── owner rulings 2026-11-11 on PR #5824: clean technique confirmed; progression standards approved ─────────────────
def test_the_owners_clean_confirmation_meets_its_gate_and_nothing_else():
    sys.path.insert(0, str(_REPO / "deploy"))
    import write_exercise_library_overlay as w

    conf = w.technique_confirmations(_LIB, None)
    assert set(conf) == {"clean", "hang_power_clean"}
    assert all(v == {"confirmed_on": "2026-11-11", "source": "owner ruling 2026-11-11"} for v in conf.values())
    kept = w.technique_confirmations(_LIB, {"technique_confirmations": {"snatch": {"confirmed_on": "2026-12-01"}, "ghost": {}}})
    assert "snatch" in kept and "ghost" not in kept  # an existing one is kept; a non-library id is dropped

    overlay = {"gates": {}, "availability_learned": {}, "technique_confirmations": conf}
    gates = eg.evaluate_gates(_LIB, overlay, {**_measured([], mean_lb=250), "charter": _CHARTER})
    locked = gates["owner_confirmation_skill"]["by_movement"]
    assert "clean" not in locked and "hang_power_clean" not in locked
    assert "snatch" in locked and locked["snatch"]["input"] == eg.UNKNOWN  # unconfirmed skills stay locked
    states = eg.movement_states(_LIB, gates)
    assert "owner_confirmation_skill" not in states["clean"]["locked_by"]
    assert "chain_full_clean" in states["clean"]["locked_by"]  # the chain still applies
    assert "chain_hang_power_clean" in states["hang_power_clean"]["locked_by"]


def test_progression_standards_are_owner_approved_and_bodyweight_values_stay_unset():
    for gid, g in _LIB["gates"].items():
        if g["kind"] in ("chain_prerequisite", "performance_threshold"):
            assert g["provenance"].startswith("owner"), gid
            assert "pending owner ruling" not in g["provenance"], gid
        if g["kind"] == "bodyweight_threshold" and "ref" in (g.get("threshold") or {}):
            assert "value" not in g["threshold"], gid  # the number is the owner's, in the private overlay
    assert _LIB["status"] == "proposed"
