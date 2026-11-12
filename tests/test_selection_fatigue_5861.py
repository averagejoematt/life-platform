"""#5861 L3 — the selection engine's LIVE policy (`selection_live`), its wiring, and the stress cases.

LIVE = an approved library (`selection_engine.mode() == "live"`). Every live behaviour here has a must-fail control, and the
shadow path is proven unchanged separately (tests/test_no_live_change_5861_l3.py). Real library + real catalog, the library
status flipped IN MEMORY only (the repo's library stays `proposed`); no overlay on disk; nothing reads the clock or AWS.

STRESS CASES — the mathematically top-ranked movement is the wrong practical choice, and the engine picks correctly:
pain flag, equipment, fatigue stacking, the time ceiling, stalled vs progressing, adherence history, joint discomfort,
stimulus-to-fatigue (machine vs free weight) and the block-end review.
"""

from __future__ import annotations

import copy
import json
import os
import pathlib
import sys
from collections import Counter

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "lambdas"))
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from training import (  # noqa: E402
    block_design_review as bdr,
    exercise_library as xl,
    fatigue_model as fm,
    program_structure,
    selection_critic as critic,
    selection_engine as se,
    selection_live as sl,
    training_charter as tc,
    variant_rotation as vr,
    week_commitments as wc,
    week_floors,
)

LIB0 = json.loads((REPO / "config" / "exercise_library.json").read_text())
CAT0 = json.loads((REPO / "config" / "movement_catalog.json").read_text())["movements"]
WEEK7 = {"week": 7, "block": 2, "session_role": "upper_heavy", "date": "2026-11-12"}  # block 2, phase 1
AS_OF = "2026-11-12"
SID = "upper_heavy.cable_tricep_pushdown"
PREV = "overhead_triceps_extension_cable"  # the slot's live top pick (tier S, cable)
PREV_TID = "B5EFBF9C"


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    monkeypatch.delenv(tc.PRIVATE_ENV_VAR, raising=False)
    monkeypatch.delenv(xl.PRIVATE_ENV_VAR, raising=False)
    monkeypatch.setattr(tc, "_from_s3", lambda key: None)
    monkeypatch.setattr(xl, "_overlay_from_local", lambda: None)
    monkeypatch.setattr(xl, "_overlay_from_s3", lambda: None)
    tc.reset_cache()
    se._LIB_CACHE.clear()
    yield
    tc.reset_cache()
    se._LIB_CACHE.clear()


def _lib(status: str = "approved") -> dict:
    lib = copy.deepcopy(LIB0)
    lib["status"] = status
    return lib


def _pos(entry: dict | None = None) -> dict:
    return vr.position(entry or WEEK7)


def _ledger(slot_id: str, variant: str, block: int = 1, phase: int = 2, weeks=(4, 6)) -> dict:
    return {"sk": vr.ledger_sk(block, slot_id), "block": block, f"phase_{phase}": {"variant": variant, "weeks": list(weeks)}}


def _live(rows=None, workouts=None, overlay=None, gate_eval=None, lib=None, pos=None, **kw) -> dict:
    lib = lib or _lib()
    pos = pos or _pos()
    policy = sl.build_policy(lib, position=pos, rows=rows or [], block_workouts=workouts, as_of=AS_OF, gate_eval=gate_eval)
    policy.update(kw.pop("policy_extra", {}))
    return se.select_week(pos, copy.deepcopy(CAT0), lib, overlay, rows=rows or [], missing=[], policy=policy, **kw)


def _slot(sel: dict, slot_id: str = SID) -> dict:
    return next(s for s in sel["slots"] if s["slot_id"] == slot_id)


def _pick(sel: dict, slot_id: str = SID) -> str:
    return (_slot(sel, slot_id).get("pick") or {}).get("catalog_key")


def _w(day: str, tid: str, load: float, reps: int = 10, rpe: float | None = 9.0, notes: str = "") -> dict:
    return {
        "date": day,
        "exercises": [{"template_id": tid, "notes": notes, "sets": [{"type": "normal", "weight_kg": load, "reps": reps, "rpe": rpe}] * 2}],
    }


DAYS = ["2026-10-22", "2026-10-29", "2026-11-05", "2026-11-11"]
HELD = [_ledger(SID, PREV)]


# ── 1. gates are read (fail-closed) ──────────────────────────────────────────
NORDIC = "nordic_hamstring_curl"
OPEN_ALL = {"gates": {g: {"state": "unlocked", "input": "measured"} for g in LIB0["gates"]}}


def test_live_gate_reads_the_evaluation_and_fails_closed():
    e = LIB0["movements"][NORDIC]
    locked = se.locked_gates(e, LIB0)
    assert locked and sl.gate_locked(e, LIB0, NORDIC, None) == locked  # no evaluation: every locking gate locked
    assert sl.gate_locked(e, LIB0, NORDIC, OPEN_ALL) == []
    one_shut = {"gates": dict(OPEN_ALL["gates"]) | {locked[0]: {"state": "locked", "input": "not_set"}}}
    assert sl.gate_locked(e, LIB0, NORDIC, one_shut) == [locked[0]]
    per_movement = {"gates": dict(OPEN_ALL["gates"]) | {locked[0]: {"state": "locked", "by_movement": {NORDIC: {"state": "locked"}}}}}
    assert sl.gate_locked(e, LIB0, NORDIC, per_movement) == [locked[0]]


def test_live_selection_opens_a_gated_movement_only_with_a_fresh_evaluation():
    def code(sel):
        s = _slot(sel, "lower_heavy.leg_curl")
        return "gate_locked" if any(x["movement_id"] == NORDIC for x in s.get("locked_next", [])) else "open"

    assert code(_live(gate_eval={"state": "read", "row": OPEN_ALL})) == "open"
    for state in ("stale", "none", "read_failed: ClientError", "not_read"):  # control: anything but a fresh read is locked
        assert code(_live(gate_eval={"state": state, "row": OPEN_ALL})) == "gate_locked", state


class _Table:
    def __init__(self, items=None, boom=False):
        self.items, self.boom = items or [], boom

    def query(self, **kw):
        if self.boom:
            raise RuntimeError("ddb down")
        return {"Items": self.items}


def test_load_gate_eval_failsoft_states():
    fresh = {"sk": "EXGATE#EVAL#2026-11-02", "week_end": "2026-11-08", "gates": {}}
    assert bdr.load_gate_eval_failsoft(AS_OF, _Table([fresh]))["state"] == "read"
    assert bdr.load_gate_eval_failsoft(AS_OF, _Table([fresh | {"week_end": "2026-10-20"}]))["state"] == "stale"
    assert bdr.load_gate_eval_failsoft(AS_OF, _Table([]))["state"] == "none"
    assert bdr.load_gate_eval_failsoft(AS_OF, _Table(boom=True))["state"].startswith("read_failed")


def test_apply_reads_no_gate_evaluation_for_an_injected_ledger(monkeypatch):
    monkeypatch.setattr(bdr, "load_gate_eval_failsoft", lambda *a, **k: pytest.fail("no read for an injected ledger"))
    rot = vr.plan(WEEK7, copy.deepcopy(CAT0), role="upper_heavy", rows=[], ledger_state="injected")
    out = se.apply(rot, copy.deepcopy(CAT0), rows=[], lib=_lib(), overlay=None, target_date=AS_OF)
    assert "not_read" in out["selection"]["live_policy"]["gates"]


# ── 2. objective-aware slots (L1's contract, local fallback) ─────────────────
def test_every_slot_names_an_objective_default_hypertrophy_and_the_library_can_override():
    assert sl.objective_of(SID, LIB0) == "hypertrophy"
    assert sl.objective_of("shoulders_arms.farmers_walk", LIB0) == "functional"
    lib = _lib() | {"selection_policy": {"slot_objectives": {SID: "strength"}}}
    assert sl.objective_of(SID, lib) == "strength"
    assert sl.objective_of(SID, _lib() | {"selection_policy": {"slot_objectives": {SID: "bogus"}}}) == "hypertrophy"


def test_objective_tier_fallback_and_not_applicable():
    e = LIB0["movements"][PREV]
    assert sl.objective_tier(e, "hypertrophy", "triceps") == se.tier_for(e, "triceps")
    assert sl.objective_tier(e | {"ratings": {"strength": {"tier": "B"}}}, "strength", "triceps") == "B"
    assert sl.objective_tier(e | {"ratings": {"strength": {"tier": None}}}, "strength", "triceps") is None


def test_objective_tier_uses_the_l1_contract_when_it_lands(monkeypatch):
    from training import quality_rubric

    monkeypatch.setattr(quality_rubric, "objective_tier", lambda entry, objective, target=None: "C", raising=False)
    assert sl.objective_tier(LIB0["movements"][PREV], "hypertrophy", "triceps") == "C"


def test_a_movement_not_applicable_to_the_slot_objective_is_never_a_candidate():
    lib = _lib() | {"selection_policy": {"slot_objectives": {SID: "conditioning"}}}
    s = _slot(_live(lib=lib))
    assert s.get("pick") is None  # no triceps movement is rated for conditioning: nothing is forced into the objective
    lib["movements"][PREV]["ratings"] = {"conditioning": {"tier": "B"}}
    assert _pick(_live(lib=lib)) == PREV  # control: rate it and it is the slot's only candidate


# ── 3. hold while it progresses, rotate for a named trigger ──────────────────
def _rot(sel: dict, slot_id: str = SID) -> dict:
    return (_slot(sel, slot_id).get("pick") or {}).get("rotation") or {}


def test_a_held_slot_with_no_trigger_holds_and_says_why():
    sel = _live(rows=HELD)
    assert _pick(sel) == PREV and _rot(sel)["action"] == "hold"


def test_without_a_ledger_the_pick_is_initial():
    assert _rot(_live())["action"] == "initial"


def test_stress_progressing_holds_stalled_rotates():
    progressing = [_w(d, PREV_TID, 25 + 2 * i) for i, d in enumerate(DAYS[:3])]
    stalled = [_w(d, PREV_TID, x) for d, x in zip(DAYS, (30, 29, 29.5))]
    held = _live(rows=HELD, workouts=progressing)
    assert _pick(held) == PREV and _rot(held)["trend"] == "progressing"
    moved = _live(rows=HELD, workouts=stalled)
    assert _pick(moved) != PREV and _rot(moved)["trigger"] == "stall"


def test_stress_a_step_due_series_holds_the_movement():
    easy = [_w(d, PREV_TID, 30, rpe=7.0) for d in DAYS[:3]]  # same load x reps at RPE 7: the prescription's failure (#5057)
    sel = _live(rows=HELD, workouts=easy)
    assert _pick(sel) == PREV and _rot(sel)["trend"] == "step_due"


def _overlay(signals: dict, *, classed: bool = True, learned: dict | None = None) -> dict:
    ov = {"per_template": {PREV_TID: {"best_set_by_band": {}, "note_signals": signals}}}
    if learned:
        ov["availability_learned"] = learned
    return ov | ({"pain_source": xl.PAIN_SOURCE_ID} if classed else {})


def test_stress_pain_flag_rotates_the_held_top_pick():
    sel = _live(rows=HELD, overlay=_overlay({"pain_flag": 1}))
    assert _pick(sel) != PREV and _rot(sel)["trigger"] == "pain"
    assert _pick(_live(rows=HELD, overlay=_overlay({"pain_flag": 1}, classed=False))) == PREV  # control: a stale overlay never excludes


def test_stress_equipment_rotates_the_held_top_pick():
    gone = {"cable_stack": {"home_gym": {"state": "unavailable"}}}
    sel = _live(rows=HELD, overlay=_overlay({}, learned=gone))
    assert _pick(sel) != PREV and _rot(sel)["trigger"] == "equipment"
    assert "cable_stack" not in LIB0["movements"][_slot(sel)["pick"]["movement_id"]]["equipment"]
    assert _pick(_live(rows=HELD, overlay=_overlay({}))) == PREV  # control


def test_stress_adherence_history_rotates():
    sel = _live(rows=HELD, overlay=_overlay({"swap": 2}))
    assert _pick(sel) != PREV and _rot(sel)["trigger"] == "adherence"
    assert _pick(_live(rows=HELD, overlay=_overlay({"swap": 1}))) == PREV  # control: one swap note is not a pattern


def test_stress_joint_discomfort_rotates_and_ranks_last():
    two = [_w(DAYS[2], PREV_TID, 30, notes="left elbow achy today"), _w(DAYS[3], PREV_TID, 30, notes="left elbow achy")]
    sel = _live(rows=HELD, workouts=two)
    assert _pick(sel) != PREV and _rot(sel)["trigger"] == "discomfort"
    assert _pick(_live()) == PREV  # with no ledger and no notes PREV is the slot's top-ranked movement ...
    assert _pick(_live(workouts=two)) != PREV  # ... and with two discomfort notes it is the wrong practical choice
    assert _pick(_live(rows=HELD, workouts=two[1:])) == PREV  # control: one note holds


def test_stress_fatigue_swap_rotates_a_named_movement():
    sel = _live(rows=HELD, policy_extra={"fatigue_swaps": [{"movement_id": PREV, "why": "axial_stacking"}]})
    assert _pick(sel) != PREV and _rot(sel)["trigger"] == "fatigue"


def test_stress_block_end_review_rotates_a_long_held_non_progressing_accessory():
    pos = _pos({"week": 13, "block": 3, "session_role": "upper_heavy", "date": AS_OF})  # block 3, phase 1
    rows = [_ledger(SID, PREV, block=2, phase=1, weeks=(1, 3)), _ledger(SID, PREV, block=2, phase=2, weeks=(4, 6))]
    rows[1]["phase_1"] = rows[0]["phase_1"]
    rows = [rows[1]]  # one row per block and slot: block 2 held PREV for both phases (6 weeks)
    assert sl.held_weeks(rows, pos, SID, PREV) == 6
    assert _rot(_live(rows=rows, pos=pos))["action"] == "hold"  # 6 weeks: under the 12-week review line
    long_rows = rows + [
        {
            "sk": vr.ledger_sk(1, SID),
            "block": 1,
            "phase_1": {"variant": PREV, "weeks": [1, 3]},
            "phase_2": {"variant": PREV, "weeks": [4, 6]},
        }
    ]
    assert sl.held_weeks(long_rows, pos, SID, PREV) == 12
    sel = _live(rows=long_rows, pos=pos)
    assert _rot(sel)["trigger"] == "block_end_review" and _pick(sel) != PREV
    progressing = [_w(d, PREV_TID, 25 + 2 * i) for i, d in enumerate(DAYS[:3])]
    assert _rot(_live(rows=long_rows, pos=pos, workouts=progressing))["action"] == "hold"  # control: progressing stays


def test_owner_request_is_a_recorded_trigger():
    pins = {SID: {"catalog_key": "triceps_extension_cable", "source": "approved", "approved_block": 2, "experiment": None}}
    sel = _live(rows=HELD, owner_pins=pins)
    assert _pick(sel) == "triceps_extension_cable" and _rot(sel)["trigger"] == "owner_request"
    same = {SID: pins[SID] | {"catalog_key": PREV}}
    assert _rot(_live(rows=HELD, owner_pins=same))["action"] == "hold"


def test_every_rotation_names_a_trigger_from_the_list():
    sel = _live(rows=HELD, overlay=_overlay({"swap": 2}))
    for s in sel["slots"]:
        r = (s.get("pick") or {}).get("rotation") or {}
        if r.get("action") == "rotate":
            assert r["trigger"] in set(sl.ROTATION_TRIGGERS) | {"week_repeat_cap"}


# ── 4. within-week repetition ────────────────────────────────────────────────
def test_live_repeats_only_with_a_recorded_reason_and_at_most_twice():
    sel = _live()
    counts = Counter((s.get("pick") or {}).get("catalog_key") for s in sel["slots"] if not s.get("pinned"))
    assert max(counts.values()) <= sl.MAX_WEEKLY_EXPOSURES
    for s in sel["slots"]:
        p = s.get("pick") or {}
        if not s.get("pinned") and counts[p.get("catalog_key")] > 1:
            assert (p.get("repeat") or {}).get("code") in ("repeat_beneficial", None) or p.get("rotation")
    assert any((s.get("pick") or {}).get("repeat", {}) and s["pick"]["repeat"]["code"] == "repeat_beneficial" for s in sel["slots"])


def test_shadow_keeps_no_repeats_per_week_control():
    shadow = se.select_week(_pos(), copy.deepcopy(CAT0), _lib("proposed"), None, rows=[], missing=[])
    keys = [(s.get("pick") or {}).get("catalog_key") for s in shadow["slots"] if not s.get("pinned")]
    assert len(keys) == len(set(keys))


def test_choose_takes_a_same_band_peer_before_repeating():
    def c(k, t):
        return {"catalog_key": k, "title": k, "tier": t, "movement_id": k}

    ranked = [c("a", "S"), c("b", "S"), c("x", "B")]
    assert sl._choose(ranked, Counter({"a": 1}), None)[0]["catalog_key"] == "b"  # a peer is open: no pointless repeat
    pick, why = sl._choose(ranked, Counter({"a": 1, "b": 1}), None)
    assert pick["catalog_key"] == "a" and why["code"] == "repeat_beneficial"  # a second exposure beats dropping a band
    pick, why = sl._choose(ranked, Counter({"a": 2, "b": 2}), None)
    assert pick["catalog_key"] == "x" and why["code"] == "week_repeat_cap"


# ── 5. stimulus-to-fatigue: machine vs free weight ──────────────────────────
def test_stress_equal_fit_prefers_the_lower_fatigue_variant_and_n1_fit_overrides_it():
    slot = "upper_heavy.db_curl"
    free, machine = "seated_incline_curl_dumbbell", "bicep_curl_machine"
    e_free = LIB0["movements"][free]
    assert sl.fatigue_cost(e_free) > sl.fatigue_cost(LIB0["movements"][machine])
    assert _pick(_live(), slot) == machine
    # control: his own response — the free-weight variant progressing in the overlay — outranks the fatigue cost
    tid = e_free["template_id"]
    ov = {
        "per_template": {
            tid: {
                "best_set_by_band": {
                    "a": {"weight_kg": 10, "reps": 8, "date": "2026-10-01"},
                    "b": {"weight_kg": 12, "reps": 8, "date": "2026-11-01"},
                },
                "note_signals": {"sentiment_positive": 1},
            }
        }
    }
    assert _pick(_live(overlay=ov), slot) == free


def test_stacking_makes_a_high_spinal_load_movement_cost_more():
    e = {"job": "compound", "resistance_profile": "free_weight", "joint_stress": {"spinal_load": "high"}}
    assert sl.fatigue_cost(e, stacking=True) == sl.fatigue_cost(e) + 2
    low = e | {"joint_stress": {"spinal_load": "low"}}
    assert sl.fatigue_cost(low, stacking=True) == sl.fatigue_cost(low)


def test_policy_reads_stacking_from_the_record():
    lib = _lib()
    mv = lib["movements"]
    tids = {k: mv[k]["template_id"] for k in ("squat_barbell", "deadlift_barbell", "romanian_deadlift_barbell") if k in mv}
    if len(tids) < 3:
        pytest.skip("the library carries no barbell squat / deadlift / RDL trio")
    rows = [_w(d, t, 80, reps=5) for d, t in zip(("2026-11-10", "2026-11-11", "2026-11-12"), tids.values())]
    assert sl.build_policy(lib, position=_pos(), rows=[], block_workouts=rows, as_of=AS_OF, gate_eval=None)["stacking"] is True
    spread = [_w(d, t, 80, reps=5) for d, t in zip(("2026-11-01", "2026-11-05", "2026-11-12"), tids.values())]
    assert sl.build_policy(lib, position=_pos(), rows=[], block_workouts=spread, as_of=AS_OF, gate_eval=None)["stacking"] is False


# ── 6. the time ceiling and the live draft reduction ────────────────────────
def test_stress_a_strained_day_takes_accessory_sets_never_anchors_and_stays_under_the_ceiling():
    rx = program_structure.session_prescription_for_role("lower_heavy", catalog_movements=copy.deepcopy(CAT0))
    strained = fm.assess(workouts=[], lib=LIB0, as_of=AS_OF, readiness="red", sleep_hours=4.0)
    out = fm.apply_to_session(rx, {"selection": {"mode": "live"}}, strained)
    anchors = lambda r: [len(e["sets"]) for e in r["exposures"] if e["kind"] == "anchor"]  # noqa: E731
    assert anchors(out) == anchors(rx) and out["total_sets"] == rx["total_sets"] - strained["reduce_sets"]
    assert out["session_minutes"]["lifting_minutes"] < rx["session_minutes"]["lifting_minutes"] <= 75
    assert fm.apply_to_session(rx, {"selection": {"mode": "shadow"}}, strained) is rx  # control: shadow is the same object


# ── 7. week commitments under live ──────────────────────────────────────────
def _held_rotation(decision: dict | None) -> dict:
    slot = {"slot_id": SID, "source": "selection", "pool": [PREV, "triceps_extension_cable"], "variant": PREV, "previous": PREV}
    if decision:
        slot["rotation_decision"] = decision
    return {"position": _pos(), "volume_check": {"unchanged": True}, "slots": [slot]}


def test_a_live_hold_with_a_reason_meets_the_rotation_commitment_control_blocks_without():
    assert wc.rotation_problem(_held_rotation({"action": "hold", "reason": "progressing"})) is None
    assert wc.rotation_problem(_held_rotation(None)).startswith("held at a phase boundary")
    assert wc.rotation_problem(_held_rotation({"action": "rotate", "trigger": "stall"})).startswith("held at a phase boundary")


def test_the_competence_floor_counts_a_pull_up_only_when_live():
    served = [{"key": "pull_up", "slot_id": "x", "role": "upper_heavy"}]
    lib = _lib()
    groups = week_floors.free_weight_compounds(served, lib, CAT0)
    assert groups["pull"] == []  # the free-weight floor alone never counts a bodyweight pull (audit §2e)
    assert wc._with_bodyweight_pull(groups, served, lib, CAT0)["pull"] == [LIB0["movements"]["pull_up"]["title"]]
    c = next(x for x in wc.COMMITMENTS if x["id"] == "free_weight_compounds")
    proposed = wc._free_weight(c, served, _lib("proposed"), CAT0, "proposed")
    approved = wc._free_weight(c, served, lib, CAT0, "approved")
    assert "pull" in proposed["detail"] and "pull" not in approved["detail"].split("this week")[0]


# ── 8. the critic under live ────────────────────────────────────────────────
def test_the_critic_builds_the_live_policy_only_for_an_approved_library():
    rot = {"position": _pos()}

    class _Ir:
        target_date = AS_OF

    assert critic._live_policy(_lib("proposed"), rot, _Ir(), None) is None
    pol = critic._live_policy(_lib(), rot, _Ir(), OPEN_ALL)
    assert pol["gate_eval"] == OPEN_ALL and pol["gate_eval_state"] == "read"
    assert critic._live_policy(_lib(), rot, _Ir(), None)["gate_eval"] is None  # fail-closed


# ── 9. the cron's live inputs (gap 4) ────────────────────────────────────────
def _cron():
    sys.path.insert(0, str(REPO / "lambdas" / "operational"))
    import hevy_routine_cron_lambda as cron

    return cron


def test_cron_live_inputs_are_empty_and_read_nothing_while_proposed(monkeypatch):
    cron = _cron()
    monkeypatch.setattr(se, "load_library_failsoft", lambda: _lib("proposed"))
    assert cron._live_inputs(AS_OF, read=lambda *a: pytest.fail("no read while proposed")) == {}


def test_cron_live_inputs_feed_real_values_and_map_danger_to_high(monkeypatch):
    cron = _cron()
    from health import hr_regime

    monkeypatch.setattr(se, "load_library_failsoft", lambda: _lib())
    monkeypatch.setattr(hr_regime, "is_rebaselining", lambda *a, **k: False)
    tid = LIB0["movements"][PREV]["template_id"]
    data = {
        "whoop": [{"sk": "DATE#2026-11-12", "recovery_score": 20, "sleep_duration_hours": 5.5}],
        "computed_metrics": [{"sk": "DATE#2026-11-11", "acwr_zone": "danger"}],
        "hevy": [_w("2026-11-10", tid, 20)],
    }
    out = cron._live_inputs(AS_OF, read=lambda source, start, end: data[source])
    assert out["recovery_tier"] == "red" and out["acwr_flag"] == "high" and out["sleep_hours"] == 5.5
    assert out["volume_7d"] == {"triceps": 2}
    from training.routine_generator import _autoreg_multiplier

    assert _autoreg_multiplier("green", out["acwr_flag"]) == 0.6  # the mismatch closed: danger now reaches 0.6
    assert _autoreg_multiplier("green", "danger") == 1.0  # control: the raw zone never matched


def test_cron_live_inputs_respect_the_hr_regime_window_and_fail_soft(monkeypatch):
    cron = _cron()
    from health import hr_regime

    monkeypatch.setattr(se, "load_library_failsoft", lambda: _lib())
    monkeypatch.setattr(hr_regime, "is_rebaselining", lambda *a, **k: True)
    out = cron._live_inputs(
        AS_OF, read=lambda source, start, end: [{"sk": "DATE#2026-11-12", "recovery_score": 20}] if source == "whoop" else []
    )
    assert "recovery_tier" not in out  # inside the window an HR-derived tier is not evidence: the default stays

    def boom(*a):
        raise RuntimeError("ddb down")

    assert cron._live_inputs(AS_OF, read=boom) == {"sleep_hours": None, "acwr_flag": None}
    monkeypatch.setattr(cron, "_live_inputs", lambda d: {})
    monkeypatch.setattr(cron, "_z2_minutes_7d", lambda d: 100.0)
    inputs = cron._gather_inputs(AS_OF, False)
    assert (inputs.recovery_tier, inputs.acwr_flag, inputs.volume_7d) == ("yellow", "safe", {})
