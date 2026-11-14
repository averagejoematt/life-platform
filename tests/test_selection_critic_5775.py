"""#5775 (S6) — the deterministic stage-2 `selection` critic.

Per slot: a movement served below the best AVAILABLE tier with no exclusion is flipped to it, the movement named; each
exclusion kind (gate, pain, equipment, owner pin/approval, week repeat) keeps the pick standing with its reason; an unmet
weekly concession check (#5774) FAILS the critic. Pure: no model call, no clock, deterministic.

Real library + real catalog, deep-copied per test; overlays are synthetic (a fake `pain_flag` tag, no note text, no loads);
nothing reads the clock (every date is a literal passed in).
"""

from __future__ import annotations

import ast
import copy
import json
import os
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "lambdas"))
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from training import (  # noqa: E402
    exercise_library as xl,
    program_structure as ps,
    selection_critic as critic,
    selection_engine as se,
    training_charter as tc,
    variant_rotation as vr,
    week_commitments as wc,
)
from training.routine_ir import ExerciseBlock, RoutineSpec, Set  # noqa: E402

_REAL_FREE_WEIGHT = wc._free_weight  # the unpinned row, for the finding's own test
LIB0 = json.loads((REPO / "config" / "exercise_library.json").read_text())
CAT0 = json.loads((REPO / "config" / "movement_catalog.json").read_text())["movements"]
WEEK7 = {"week": 7, "block": 2, "session_role": "upper_heavy", "date": "2026-11-12"}  # block 2, phase 1 (rotation step 2)
TRI = "upper_heavy.cable_tricep_pushdown"
CURL = "upper_heavy.db_curl"
OHE = "overhead_triceps_extension_cable"  # the S-tier triceps movement the owner named (2026-11-11; quality tiers #5857)
NEXT_TRI = "triceps_extension_cable"  # the A band below it: with OHE held off, nothing else ranks above this one
# #5857: the upper_heavy week served at its best available quality tier, slot by slot (the critic's own flips)
BEST = {
    "cable_tricep_pushdown": OHE,
    "db_curl": "preacher_curl_dumbbell",
    "db_lateral_raise": "lateral_raise_machine",
    "reverse_pec_deck": "reverse_pec_deck",
}


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    monkeypatch.delenv(tc.PRIVATE_ENV_VAR, raising=False)
    monkeypatch.delenv(xl.PRIVATE_ENV_VAR, raising=False)
    monkeypatch.setattr(tc, "_from_s3", lambda key: None)
    monkeypatch.setattr(xl, "_overlay_from_local", lambda: None)
    monkeypatch.setattr(xl, "_overlay_from_s3", lambda: None)
    tc.reset_cache()
    se._LIB_CACHE.clear()
    # #5857 FINDING, pinned here so the slot tests read the slot: the approved program serves no free-weight PULL (its rows
    # are machine/cable anchors), so the free-weight compound floor blocks every approved week until the owner rules on it
    # (test_the_free_weight_pull_finding_blocks_the_approved_week names it). Every other commitment is evaluated for real.
    monkeypatch.setattr(wc, "_free_weight", lambda c, *a: wc._row(c, wc.MET, "pinned for the slot tests (#5857 finding)"))
    yield
    tc.reset_cache()
    se._LIB_CACHE.clear()


def _lib(status: str = "approved") -> dict:
    lib = copy.deepcopy(LIB0)
    lib["status"] = status
    lib["approved_on"] = "2026-01-02"  # #5861 fix round 11: live needs the approval day
    return lib


def _ohe_alone(lib: dict | None = None) -> dict:
    """The library with OHE the slot's ONLY S-tier triceps movement (any other S triceps row planted down to A), so the
    one movement above NEXT_TRI is OHE and each exclusion test reads OHE's own reason."""
    lib = lib or _lib()
    for k, e in lib["movements"].items():
        if k != OHE and e["target"]["primary"] == "triceps":
            for r in e["hypertrophy"]:
                r["tier"] = "A" if r["tier"] == "S" else r["tier"]
    return lib


def _rot() -> dict:
    return vr.plan(WEEK7, copy.deepcopy(CAT0), role="upper_heavy", rows=[], ledger_state="injected")


def _ir(rot: dict | None = None, **swap: str) -> RoutineSpec:
    """The upper_heavy session the plan serves (synthetic sets: reps only), `swap` = {slot incumbent: served key}."""
    rot = rot or _rot()
    for s in rot["slots"]:
        if s["incumbent"] in swap:
            s["variant"] = swap[s["incumbent"]]
            rot["variants_by_role"]["upper_heavy"][s["incumbent"]] = swap[s["incumbent"]]
    rx = ps.session_prescription_for_role(
        "upper_heavy", catalog_movements=CAT0, skill_ceiling=2, accessory_variants=rot["variants_by_role"]["upper_heavy"]
    )
    ex = [
        ExerciseBlock(movement_key=e["movement_key"], sets=[Set(reps=10) for _ in e["sets"]])
        for e in rx["exposures"]
        if e.get("movement_key")
    ]
    ir = RoutineSpec(routine_id="r5775", target_date="2026-11-12", archetype="x", exercises=ex)
    ir.inputs_snapshot = {"rotation": rot}
    return ir


def _best_ir() -> RoutineSpec:
    """The week at its best available tier. The machine lateral raise is its slot's only A-band member and the plan
    served it the phase before, so the live selection records that band (`selection_engine.top_band`) and owner ruling B
    (#5856, 2026-11-12) accepts the hold — what `selection_engine._live` writes onto the rotation slot."""
    rot = _rot()
    for s in rot["slots"]:
        if s["incumbent"] == "db_lateral_raise":
            s["top_band"] = {"tier": "A", "members": [BEST["db_lateral_raise"]]}
    return _ir(rot, **BEST)


def _run(ir=None, lib=None, overlay=None, **kw) -> dict:
    return critic.evaluate(ir or _ir(), lib or _lib(), None, overlay, catalog=copy.deepcopy(CAT0), missing=[], **kw)


def _slot(out: dict, slot_id: str) -> dict:
    return next(v for v in out["verdicts"] if v.get("slot_id") == slot_id)


def _pain(lid: str, *, classed: bool = True) -> dict:
    tid = LIB0["movements"][lid]["template_id"]
    ov = {"per_template": {tid: {"best_set_by_band": {}, "note_signals": {"pain_flag": 1}}}}
    return ov | ({"pain_source": xl.PAIN_SOURCE_ID} if classed else {})


# ── the flip ────────────────────────────────────────────────────────────────
def test_a_slot_below_the_best_available_tier_is_flipped_naming_the_movement():
    out = _run()
    v = _slot(out, TRI)
    assert se.TIER_RANK[v["served_tier"]] > se.TIER_RANK["S"] and v["verdict"] == "change", v
    assert v["to"] == OHE and v["to_tier"] == "S" and "Overhead Triceps Extension" in v["why"]
    assert out["verdict"] == "change"
    # biceps: an S curl is open; the preacher MACHINE is never the target (no machine at home_gym)
    c = _slot(out, CURL)
    assert (c.get("to_tier") or c["served_tier"]) == "S" and c.get("to") != "preacher_curl_machine", c
    # control: serve the A -> it stands as the best available, nothing to flip
    v2 = _slot(_run(_ir(cable_tricep_pushdown=OHE)), TRI)
    assert v2["verdict"] == "pass" and v2["stands"] == "best_available"


def test_the_flip_is_a_stage2_change_on_the_exercise_index():
    ir = _ir()
    out = _run(ir)
    cv = critic.as_critic_verdict(out)
    assert out["stage2"] == cv  # evaluate carries the stage-2 verdict the registry appends (#5784)
    idx = [e.movement_key for e in ir.exercises].index("triceps_rope_pushdown")
    fields = {cv["field"]: cv["to"]} | {a["field"]: a["to"] for a in cv.get("additional_changes") or []}
    assert cv["critic"] == "selection" and cv["verdict"] == "change"
    assert fields[f"exercises[{idx}].movement_key"] == OHE


def test_a_proposed_library_records_the_flip_and_applies_nothing():
    """THE SWITCH (owner, 2026-11-11): a proposed library changes no live draft — the flip rides as shadow_changes."""
    out = _run(lib=_lib("proposed"))
    assert _slot(out, TRI)["verdict"] == "change" and out["mode"] == se.MODE_SHADOW
    cv = critic.as_critic_verdict(out)
    assert cv["verdict"] == "approve" and cv["field"] is None
    assert OHE in {f["to"] for f in cv["shadow_changes"]}


# ── each exclusion kind keeps the pick standing ─────────────────────────────
def test_a_locked_gate_keeps_the_pick():
    lib = _ohe_alone()
    lib.setdefault("gates", {})["synthetic_gate_5775"] = {"locks": True, "kind": "synthetic"}
    lib["movements"][OHE]["gates"] = list(lib["movements"][OHE].get("gates") or []) + ["synthetic_gate_5775"]
    v = _slot(_run(_ir(cable_tricep_pushdown=NEXT_TRI), lib=lib), TRI)
    assert v["verdict"] == "pass" and v["stands"] == "gate_locked" and v["blocked"] == OHE, v


def test_a_pain_flag_keeps_the_pick():
    v = _slot(_run(_ir(cable_tricep_pushdown=NEXT_TRI), lib=_ohe_alone(), overlay=_pain(OHE)), TRI)
    assert v["verdict"] == "pass" and v["stands"] == "pain_swap" and v["blocked"] == OHE, v
    # control: a stale overlay (written before #5806's pain_class) is not trusted to exclude -> OHE is an open S peer again;
    # the A pick stands inside the S∪A pool (owner ruling 2026-11-12), naming OHE as its peer, never as pain-excluded
    v2 = _slot(_run(_ir(cable_tricep_pushdown=NEXT_TRI), lib=_ohe_alone(), overlay=_pain(OHE, classed=False)), TRI)
    assert v2["stands"] == "pool_fit" and v2["blocked"] == OHE, v2


def test_absent_equipment_keeps_the_pick():
    lib = _ohe_alone()
    lib["movements"][OHE]["availability"]["home_gym"]["state"] = "unavailable"
    v = _slot(_run(_ir(cable_tricep_pushdown=NEXT_TRI), lib=lib), TRI)
    assert v["verdict"] == "pass" and v["stands"] == "equipment" and v["blocked"] == OHE, v


def test_an_owner_pin_or_approval_keeps_the_pick():
    rot = _rot()
    for s in rot["slots"]:
        if s["slot_id"] == TRI:
            s["source"] = "owner_approved"
    v = _slot(_run(_ir(rot)), TRI)
    assert v["verdict"] == "pass" and v["stands"] == "owner_pin", v
    pins = {TRI: {"catalog_key": "triceps_rope_pushdown", "source": "block_design_review", "approved_block": 2}}
    assert _slot(_run(owner_pins=pins), TRI)["stands"] == "owner_pin"
    # control: an approval for a DIFFERENT movement does not hold this one
    other = {TRI: pins[TRI] | {"catalog_key": "triceps_kickback_dumbbell"}}
    assert _slot(_run(owner_pins=other), TRI)["to"] == OHE


def test_a_movement_served_elsewhere_this_week_keeps_the_pick():
    rot = _rot()
    rot["variants_by_role"]["shoulders_arms"]["cable_tricep_pushdown"] = OHE  # another session this week serves it
    v = _slot(_run(_ir(rot, cable_tricep_pushdown=NEXT_TRI), lib=_ohe_alone()), TRI)
    assert v["verdict"] == "pass" and v["stands"] == "week_repeat" and v["blocked"] == OHE, v


def test_a_pain_flagged_served_movement_is_changed_away_never_into_another():
    v = _slot(_run(_ir(cable_tricep_pushdown=OHE), overlay=_pain(OHE)), TRI)
    assert v["verdict"] == "change" and "pain_swap" in v["why"] and v["to"] not in (OHE, None), v


# ── the must-fail mutation ──────────────────────────────────────────────────
def test_dropping_the_pain_exclusion_flips_into_the_pain_flagged_movement(monkeypatch):
    """The control that proves the pain test can fail: with `pain_swap` no longer honoured the critic flips INTO the
    pain-flagged movement — exactly the outcome test_a_pain_flag_keeps_the_pick forbids."""
    monkeypatch.setattr(critic, "HONORED_EXCLUSIONS", tuple(c for c in critic.HONORED_EXCLUSIONS if c != "pain_swap"))
    v = _slot(_run(_ir(cable_tricep_pushdown=NEXT_TRI), lib=_ohe_alone(), overlay=_pain(OHE)), TRI)
    assert v["stands"] == "pool_fit" and v["blocked"] == OHE, v  # OHE read as an available peer, not as pain-excluded
    # and with a pick OUTSIDE the pool the same mutation flips INTO the pain-flagged movement
    v = _slot(_run(_ir(cable_tricep_pushdown="triceps_rope_pushdown"), lib=_ohe_alone(), overlay=_pain(OHE)), TRI)
    assert v["verdict"] == "change" and v["to"] == OHE


# ── the week ────────────────────────────────────────────────────────────────
def _stage1(rows: list[dict]) -> dict:
    return {"verdict": "fail" if any(r["blocking"] for r in rows) else "pass", "rows": rows}


def test_an_unmet_weekly_commitment_fails_the_critic():
    miss = [{"id": "kettlebell", "verdict": "block", "blocking": True, "detail": "no kettlebell movement this week"}]
    out = _run(_ir(cable_tricep_pushdown=OHE), week_commitments=_stage1(miss))
    assert out["verdict"] == "fail" and out["week"][0]["check"] == "kettlebell"
    cv = critic.as_critic_verdict(out)
    assert cv["verdict"] == "veto" and cv["metric"] == "week_commitments.kettlebell"
    # control: the same row as a WARN (the kettlebell switch before its date) is reported, never a fail
    warn = [{"id": "kettlebell", "verdict": "warn", "blocking": False, "detail": "a warning until the switch"}]
    out2 = _run(_best_ir(), week_commitments=_stage1(warn))
    assert out2["verdict"] != "fail" and out2["week_rows"][0]["verdict"] == "warn"


def test_the_week_is_computed_from_the_draft_when_stage1_is_not_passed():
    out = _run(_best_ir())
    assert out["week_source"].startswith("week_commitments.evaluate") and out["verdict"] == "pass", out["week"]
    # control: drop the draft's rear-delt work -> the rp_israetel side/rear-delt band is unmet -> fail
    ir = _best_ir()
    ir.exercises = [e for e in ir.exercises if "reverse_fly" not in e.movement_key and "reverse_pec_deck" not in e.movement_key]
    out2 = _run(ir)
    assert out2["verdict"] == "fail" and "side_rear_delt_band" in {r["check"] for r in out2["week"]}


def test_an_unread_week_is_named_never_a_pass_by_silence():
    out = _run(_ir(cable_tricep_pushdown=OHE), week_commitments={"verdict": "read_failed", "error": "synthetic"})
    assert out["week_rows"] == [{"check": "week_commitments", "verdict": "not_evaluated", "why": "synthetic"}]


# ── pure and deterministic ──────────────────────────────────────────────────
def test_the_critic_is_deterministic_and_never_mutates_its_inputs():
    ir, lib = _ir(), _lib()
    before = (copy.deepcopy(ir), copy.deepcopy(lib))
    assert _run(ir, lib) == _run(ir, lib)
    assert (ir, lib) == before


def test_the_critic_makes_no_model_call_and_reads_no_clock():
    tree = ast.parse((REPO / "lambdas" / "training" / "selection_critic.py").read_text())
    mods = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    mods += [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
    assert not [m for m in mods if m.split(".")[0] in ("ai", "coach", "boto3", "datetime", "time")], mods


def test_the_free_weight_pull_finding_blocks_the_approved_week(monkeypatch):
    """#5857 finding (owner ruling 2026-11-12, board rec 4): the program's pulls are machine/cable anchors, so the approved
    week misses the free-weight compound floor on PULL only, and the critic fails on it. Press, squat and hinge are met."""
    monkeypatch.setattr(wc, "_free_weight", _REAL_FREE_WEIGHT)
    out = _run(_best_ir())
    assert out["verdict"] == "fail" and [r["check"] for r in out["week"]] == ["free_weight_compounds"], out["week"]
    assert out["week"][0]["why"] == "no free-weight compound pull this week"
