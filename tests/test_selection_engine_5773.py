"""#5773 — the selection engine: per slot, rank the exercise library by QUALITY tier (S-D, the library's rubric tier,
#5857), then N=1 fit, then variety, evidence confidence a tie-break; C/D only with a recorded reason; absent equipment never served; pain-excluded never served; a novelty budget; SHADOW while the library is
`proposed`, LIVE only once it is `approved`; `library_version` on every plan; the pure `selection_critic.evaluate`.

Every must-fail control flips one input and asserts the outcome flips with it. Real library + real catalog, deep-copied
per test; no overlay on disk (N=1 fit unknown unless a test injects one); nothing reads the clock.
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

from training import (
    exercise_library as xl,  # noqa: E402
    routine_repo,  # noqa: E402
    selection_critic as critic,  # noqa: E402
    selection_engine as se,  # noqa: E402
    training_charter as tc,  # noqa: E402
    variant_rotation as vr,  # noqa: E402
)
from training.routine_ir import ExerciseBlock, RoutineSpec  # noqa: E402

LIB0 = json.loads((REPO / "config" / "exercise_library.json").read_text())
CAT0 = json.loads((REPO / "config" / "movement_catalog.json").read_text())["movements"]
WEEK7 = {"week": 7, "block": 2, "session_role": "upper_heavy", "date": "2026-11-12"}  # block 2, phase 1 (rotation step 2)


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


def _lib(status: str = "proposed") -> dict:
    lib = copy.deepcopy(LIB0)
    lib["status"] = status
    return lib


def _cat() -> dict:
    return copy.deepcopy(CAT0)


def _pos() -> dict:
    return vr.position(WEEK7)


def _week(lib=None, cat=None, overlay=None, **kw) -> dict:
    return se.select_week(_pos(), cat or _cat(), lib or _lib(), overlay, missing=[], **kw)


def _slot(sel: dict, slot_id: str) -> dict:
    return next(s for s in sel["slots"] if s["slot_id"] == slot_id)


def _picks(sel: dict) -> set:
    return {(s.get("pick") or {}).get("movement_id") for s in sel["slots"]}


def _served_anywhere(sel: dict) -> set:
    out = set()
    for s in sel["slots"]:
        out.add((s.get("pick") or {}).get("movement_id"))
        out.update(f["movement_id"] for f in s.get("fallbacks") or [])
    return out


# ── tier order (must-fail controls) ──────────────────────────────────────────
def test_the_best_quality_tier_wins_for_the_slot_muscle():
    s = _slot(_week(), "lower_heavy.calf_raise_machine")
    assert s["pick"]["tier"] == "S"
    assert s["pick"]["c_reason"] is None
    # control: strip every S row in the library -> the pick drops to A, never stays on a now-D movement
    lib = _lib()
    for e in xl.movements(lib).values():
        for r in e["hypertrophy"]:
            if r["tier"] == "S":
                r["tier"] = "D"
    s2 = _slot(_week(lib=lib), "lower_heavy.calf_raise_machine")
    assert s2["pick"]["tier"] == "A"


def test_evidence_confidence_breaks_a_tie_and_never_outranks_the_tier():
    """#5857: evidence is a tie-break only — after tier, N=1 fit and variety."""
    a = {"tier": "S", "n1": {"score": 0}, "novel": False, "exposures": 5, "movement_id": "a", "catalog_key": "a"}
    direct = a | {"evidence": "rct_direct", "movement_id": "z", "catalog_key": "z"}
    plain = a | {"evidence": "none_reviewed"}
    assert sorted([plain, direct], key=lambda c: se.rank_key(c, set()))[0] is direct
    # control: a higher tier with no evidence still beats a lower tier with a direct trial
    assert sorted([direct | {"tier": "A"}, plain], key=lambda c: se.rank_key(c, set()))[0] is plain
    # control: variety outranks evidence
    assert sorted([direct, plain], key=lambda c: se.rank_key(c, {"z"}))[0] is plain


def test_the_overhead_triceps_extension_wins_now_the_catalog_writes_it():
    """The owner's specimen: the S-tier overhead extension (rubric S, a direct trial recorded beside it) outranks every
    triceps movement the pool held — for real, on the shipped catalog, since the 2026-11-11 split gave it its own entry."""
    assert CAT0["overhead_triceps_extension_cable"]["hevy_template_id_hint"] == "B5EFBF9C"
    s = _slot(_week(), "upper_heavy.cable_tricep_pushdown")
    assert s["pick"]["movement_id"] == "overhead_triceps_extension_cable" and s["pick"]["tier"] == "S"
    assert s["pick"]["evidence"] == "rct_direct" and s["pick"]["c_reason"] is None
    # control: without the catalog entry it is ranked but never served (the pre-split state); the next band serves
    cat = _cat()
    del cat["overhead_triceps_extension_cable"]
    s2 = _slot(_week(cat=cat), "upper_heavy.cable_tricep_pushdown")
    assert s2["pick"]["movement_id"] != "overhead_triceps_extension_cable" and s2["pick"]["tier"] != "S"
    hit = next(x for x in s2["above_pick"] if x["movement_id"] == "overhead_triceps_extension_cable")
    assert hit["code"] == "not_prescribable"
    # control: demote it to D -> it no longer wins on tier
    lib = _lib()
    for r in lib["movements"]["overhead_triceps_extension_cable"]["hypertrophy"]:
        r["tier"] = "D"
    assert _slot(_week(lib=lib), "upper_heavy.cable_tricep_pushdown")["pick"]["movement_id"] != "overhead_triceps_extension_cable"


def test_tier_for_reads_the_slot_muscle_and_its_sub_targets():
    e = LIB0["movements"]["overhead_triceps_extension_cable"]
    assert se.tier_for(e, "triceps") == "S" and se.evidence_for(e, "triceps") == "rct_direct"
    assert se.tier_for(e, "biceps") == se.UNRATED_TIER == "D" and se.evidence_for(e, "biceps") == "none_reviewed"
    assert se.tier_for(LIB0["movements"]["standing_calf_raise_machine"], "calves") == "S"


# ── C only with a recorded reason ────────────────────────────────────────────
def test_every_c_pick_in_the_week_carries_a_recorded_reason():
    sel = _week()
    c_picks = [s for s in sel["slots"] if s.get("pick") and s["pick"]["tier"] == "C"]
    assert c_picks, "the live library has C-only slots; this test must see them"
    for s in c_picks:
        assert s["pick"]["c_reason"] and s["pick"]["c_reason"]["code"] in se.C_REASONS, s["slot_id"]
    for s in sel["slots"]:
        if s.get("pick") and s["pick"]["tier"] != "C":
            assert s["pick"]["c_reason"] is None


def test_c_reason_names_the_blocked_higher_tier_or_the_gap():
    pick = {"tier": "C", "movement_id": "x"}
    assert se.c_reason(pick, [])["code"] == "library_gap"
    blocked = [{"tier": "B", "movement_id": "b", "title": "B one", "code": "equipment", "why": "x unavailable"}]
    assert se.c_reason(pick, blocked)["code"] == "equipment"
    assert se.c_reason(pick, [], pinned=True)["code"] == "owner_pin"
    assert se.c_reason({"tier": "B", "movement_id": "y"}, blocked) is None


def test_critic_changes_a_c_pick_served_where_an_a_is_selectable():
    cat = _cat()
    lib = _lib()
    sel = _week(lib=lib, cat=cat)
    rot = vr.plan(WEEK7, cat, role="upper_heavy", rows=[], ledger_state="injected")
    rot["slots"] = [
        s | {"variant": "triceps_rope_pushdown"} if s["slot_id"] == "upper_heavy.cable_tricep_pushdown" else s for s in rot["slots"]
    ]
    ir = RoutineSpec(
        routine_id="r", target_date="2026-11-12", archetype="x", exercises=[ExerciseBlock(movement_key="triceps_rope_pushdown")]
    )
    ir.inputs_snapshot = {"rotation": rot, "selection_shadow": sel}
    out = critic.evaluate(ir, lib, None, None)
    v = out["verdicts"][0]
    assert v["verdict"] == "change" and v["to"] == "overhead_triceps_extension_cable", v
    assert out["verdict"] == "change"
    # control: serve the A -> pass
    rot["slots"] = [
        s | {"variant": "overhead_triceps_extension_cable"} if s["slot_id"] == "upper_heavy.cable_tricep_pushdown" else s
        for s in rot["slots"]
    ]
    ir.exercises = [ExerciseBlock(movement_key="overhead_triceps_extension_cable")]
    assert critic.evaluate(ir, lib, None, None, catalog=cat)["verdicts"][0]["verdict"] == "pass"


# ── absent equipment never served ────────────────────────────────────────────
def test_absent_equipment_is_never_picked_nor_a_fallback():
    sel = _week()
    assert "preacher_curl_machine" not in _served_anywhere(sel)  # seeded gap: no preacher curl machine
    # control: mark the machine available -> the B-tier preacher machine becomes selectable
    lib = _lib()
    lib["gym_inventory"]["items"]["preacher_machine"]["home_gym"]["state"] = "available"
    lib["movements"]["preacher_curl_machine"]["availability"]["home_gym"]["state"] = "available"
    assert "preacher_curl_machine" in _served_anywhere(_week(lib=lib))


def test_learned_unavailability_excludes_and_contention_does_not():
    learned = {"availability_learned": {"cable_stack": {"home_gym": {"state": "unavailable", "source": "owner note"}}}}
    sel = _week(overlay=learned)
    cable = {k for k, e in LIB0["movements"].items() if "cable_stack" in e["equipment"]}
    assert not (_served_anywhere(sel) & cable)
    contention = {"availability_learned": {"cable_stack": {"home_gym": {"state": None, "signals": {"contention": 4}}}}}
    assert _served_anywhere(_week(overlay=contention)) & cable


def test_critic_changes_an_absent_equipment_movement():
    lib = _lib()
    ir = {"exercises": [{"movement_key": "preacher_curl_machine"}], "inputs_snapshot": {}}
    v = critic.evaluate(ir, lib, None, None, catalog=_cat())["verdicts"][0]
    assert v["verdict"] == "change" and "preacher_machine" in v["why"]


# ── pain exclusion ───────────────────────────────────────────────────────────
def _pain_overlay(tid: str, signals: dict, *, classed: bool = True) -> dict:
    ov = {"per_template": {tid: {"best_set_by_band": {}, "note_signals": signals}}}
    return ov | ({"pain_source": xl.PAIN_SOURCE_ID} if classed else {})


def test_a_pain_class_movement_is_never_served():
    base = _slot(_week(), "upper_heavy.db_curl")["pick"]["movement_id"]
    tid = LIB0["movements"][base]["template_id"]
    sel = _week(overlay=_pain_overlay(tid, {"pain_flag": 1}))
    assert base not in _served_anywhere(sel) and sel["pain_source_state"] == "classed"
    assert _slot(sel, "upper_heavy.db_curl")["excluded_counts"].get("pain_swap") == 1
    # control: the same overlay without the flag -> served again
    assert _slot(_week(overlay=_pain_overlay(tid, {"sentiment_positive": 1})), "upper_heavy.db_curl")["pick"]["movement_id"] == base


def test_discomfort_and_form_notes_never_exclude():
    base = _slot(_week(), "upper_heavy.db_curl")["pick"]["movement_id"]
    tid = LIB0["movements"][base]["template_id"]
    # #5806's classes through the library's tagger: only `pain` sets pain_flag
    assert "pain_flag" in xl.note_signal_tags("sharp pain in my elbow on these")
    discomfort = xl.note_signal_tags("my elbow felt a bit achy today")
    form = xl.note_signal_tags("need to check my form, the cable height was off")
    assert "pain_flag" not in discomfort and "joint_discomfort" in discomfort
    assert "pain_flag" not in form
    for tags in (discomfort, form):
        sig = {t: 1 for t in tags}
        assert base in _served_anywhere(_week(overlay=_pain_overlay(tid, sig))), tags


def test_a_stale_overlay_pain_tag_is_not_trusted_to_exclude():
    base = _slot(_week(), "upper_heavy.db_curl")["pick"]["movement_id"]
    tid = LIB0["movements"][base]["template_id"]
    sel = _week(overlay=_pain_overlay(tid, {"pain_flag": 1}, classed=False))
    assert sel["pain_source_state"] == "stale_overlay" and _slot(sel, "upper_heavy.db_curl")["pick"]["movement_id"] == base


def test_not_for_you_now_excludes_as_its_own_verdict():
    lib = _lib()
    e = lib["movements"]["preacher_curl_dumbbell"]
    e["not_for_you_now"] = {"reason_code": "planted", "unlock_condition": "a test"}
    assert se.not_for_you_now(e) and se.pain_exclusion(e, None) is None
    assert "preacher_curl_dumbbell" not in _served_anywhere(_week(lib=lib))
    assert "preacher_curl_dumbbell" in _served_anywhere(_week())  # control: unplanted, it serves


def test_preacher_curl_barbell_is_unlocked_by_the_owner_ruling():
    """Owner ruling 2026-11-11: the library's only not_for_you_now is lifted; a real pain-class note still excludes it."""
    e = LIB0["movements"]["preacher_curl_barbell"]
    assert e["not_for_you_now"] is None and any(x["by"].startswith("owner ruling 2026-11-11") for x in LIB0["change_log"])
    assert se.not_for_you_now(e) is None
    # first logged 2026-10-26; the 2026-11-12 catalog rebuild (history through 2026-11-11) writes it under its own id.
    # Like every barbell movement it is skill tier 3, so the week grid's skill ceiling 2 (program_conflicts: tier-3
    # barbell accessories wait on the Sports Medicine seat) keeps it off drafts, as it does the barbell and EZ-bar curls.
    assert CAT0["preacher_curl_barbell"]["hevy_template_id_hint"] == e["template_id"]
    assert CAT0["preacher_curl_barbell"]["skill_tier"] == 3
    cat = _cat()
    assert "preacher_curl_barbell" not in _served_anywhere(_week(cat=cat))  # ceiling 2: held by the tier rule, not the library
    sel = _week(cat=cat, skill_ceiling=3)
    assert "preacher_curl_barbell" in _served_anywhere(sel)  # the library and catalog no longer block it
    ov = _pain_overlay(e["template_id"], {"pain_flag": 1})
    assert "preacher_curl_barbell" not in _served_anywhere(_week(cat=cat, overlay=ov, skill_ceiling=3))  # a real pain note still excludes


# ── gates: unknown = locked ──────────────────────────────────────────────────
def test_every_gated_movement_is_locked_until_5772():
    sel = _week()
    gated = {k for k, e in LIB0["movements"].items() if se.locked_gates(e, LIB0)}
    # #5774 (owner ruling 2026-11-11): an OWNER-pinned slot is the owner's word, not the engine's pick — the kettlebell slot
    # serves the KB swing (gated `chain_kb_swing` until #5772 evaluates gates) after its KB-deadlift entry; the engine
    # never selects a gated movement for a slot it chooses
    chosen = {"slots": [s for s in sel["slots"] if not s.get("pinned")]}
    assert gated and not (_served_anywhere(chosen) & gated)
    assert {s["slot_id"] for s in sel["slots"] if s.get("pinned")} == set(vr.PINNED_SLOTS)
    assert se.locked_gates(LIB0["movements"]["squat_barbell"], LIB0) == []  # a clinical cue never locks


# ── N=1 fit ──────────────────────────────────────────────────────────────────
def test_overlay_missing_is_unknown_never_an_error():
    sel = _week(overlay=None)
    assert all(s["pick"]["n1"]["fit"] == "unknown" for s in sel["slots"] if s.get("pick"))
    assert se.n1_fit(LIB0["movements"]["farmers_walk"], {"per_template": "garbage"})["fit"] == "unknown"


def test_n1_fit_breaks_a_tier_tie_and_swap_outs_demote():
    s = _slot(_week(), "upper_heavy.db_curl")
    first, second = s["ranked_top"][0], s["ranked_top"][1]
    mv = LIB0["movements"]
    assert se.tier_for(mv[first], "biceps") == se.tier_for(mv[second], "biceps"), "the specimen must be a tier tie"
    tid1, tid2 = LIB0["movements"][first]["template_id"], LIB0["movements"][second]["template_id"]
    overlay = {
        "per_template": {
            tid1: {"note_signals": {"swap": 3}},
            tid2: {"note_signals": {"sentiment_positive": 2}},
        }
    }
    s2 = _slot(_week(overlay=overlay), "upper_heavy.db_curl")
    assert s2["pick"]["movement_id"] == second
    assert se.n1_fit(LIB0["movements"][first], overlay)["components"]["swap_out"] == -1


# ── variety ──────────────────────────────────────────────────────────────────
def test_variety_demotes_a_movement_served_in_the_lookback():
    s = _slot(_week(), "upper_heavy.db_curl")
    pick = s["pick"]["catalog_key"]
    rows = [{"sk": vr.ledger_sk(1, "upper_heavy.db_curl"), "block": 1, "phase_2": {"variant": pick}}]
    s2 = _slot(_week(rows=rows), "upper_heavy.db_curl")
    assert s2["pick"]["catalog_key"] != pick and s2["pick"]["tier"] == s["pick"]["tier"]
    # the current phase's own row is this draft's held pick, never a "recent use"
    assert se.recent_uses([{"block": 2, "phase_1": {"variant": pick}}], _pos()) == set()


def test_variety_rotates_a_slot_within_its_band_by_its_own_history():
    """#5857: slots sharing one band (three curl slots, one S curl band) each served one member last phase, so a global
    `recent` ranks every member alike. The slot's OWN least-recently-served member leads, so each slot rotates."""
    s = _slot(_week(), "upper_heavy.db_curl")
    band = [m for m in s["ranked_top"] if se.tier_for(LIB0["movements"][m], "biceps") == s["pick"]["tier"]]
    assert len(band) >= 3, band
    keys = {m: se.key_index(LIB0, CAT0)["to_cat"][m] for m in band}
    # this slot served band[0] last phase and band[1] the phase before; other slots served band[1] and band[2] last phase
    rows = [
        {
            "sk": vr.ledger_sk(1, "upper_heavy.db_curl"),
            "block": 1,
            "phase_1": {"variant": keys[band[1]]},
            "phase_2": {"variant": keys[band[0]]},
        },
        {"sk": vr.ledger_sk(1, "shoulders_arms.db_curl"), "block": 1, "phase_2": {"variant": keys[band[1]]}},
        {"sk": vr.ledger_sk(1, "upper_volume.db_curl"), "block": 1, "phase_2": {"variant": keys[band[2]]}},
    ]
    assert se.slot_last_served(rows, _pos(), "upper_heavy.db_curl") == {keys[band[1]]: 101, keys[band[0]]: 102}
    s2 = _slot(_week(rows=rows), "upper_heavy.db_curl")
    assert s2["pick"]["movement_id"] == band[2], "the member this slot never served leads"
    # control: without the slot term (global recency only) every member is `recent` and the slot holds band[0]
    real = se.rank_key
    try:
        se.rank_key = lambda c, recent, slot_last=None: real(c, recent)  # type: ignore[assignment]
        assert _slot(_week(rows=rows), "upper_heavy.db_curl")["pick"]["movement_id"] == band[0]
    finally:
        se.rank_key = real


def test_each_muscle_gets_a_lengthened_movement_or_says_why():
    sel = _week()
    rows = {r["muscle"]: r for r in sel["lengthened"]}
    assert rows["triceps"]["state"] in ("met", "adjusted") and rows["calves"]["state"] == "met"
    for r in sel["lengthened"]:
        assert r["state"] in ("met", "adjusted") or r.get("why")


# ── novelty budget ───────────────────────────────────────────────────────────
def _novel_curl_lib() -> dict:
    """The dumbbell preacher curl as new to him AND the slot's only S-tier curl (the other S curls planted down to A)."""
    lib = _lib()
    e = lib["movements"]["preacher_curl_dumbbell"]
    e["source"], e["history"] = "expansion", None
    for k, other in lib["movements"].items():
        if k != "preacher_curl_dumbbell" and other["target"]["primary"] == "biceps":
            for r in other["hypertrophy"]:
                r["tier"] = "A" if r["tier"] == "S" else r["tier"]
    return lib


def test_a_new_pick_carries_the_novel_again_caps_and_a_cue_sheet():
    cat = _cat()
    cat["preacher_curl_dumbbell"]["sessions"] = 0
    s = _slot(_week(lib=_novel_curl_lib(), cat=cat), "upper_heavy.db_curl")
    assert s["pick"]["movement_id"] == "preacher_curl_dumbbell" and s["pick"]["novel"]
    terms = s["pick"]["novel_terms"]
    assert terms["caps"] == {"exposures": 3, "rpe_max": 7, "reps_max": 8}
    assert terms["cue_sheet"] and terms["cue_sheet"]["pattern"] == "biceps_curl"
    assert not any(f["novel"] for f in s["fallbacks"]), "a slot spends its novelty budget once"


def test_novelty_budget_caps_fallbacks():
    pick = {"movement_id": "p", "equipment": ["x"], "novel": True}
    ranked = [{"movement_id": m, "catalog_key": m, "title": m, "tier": "C", "novel": True, "equipment": ["y"]} for m in ("a", "b")]
    assert se.fallbacks(pick, ranked, novel_budget=0) == []
    assert [f["movement_id"] for f in se.fallbacks(pick | {"novel": False}, ranked, novel_budget=1)] == ["a"]
    # control: a wider budget would admit both — the budget is what holds it to one
    assert len(se.fallbacks(pick, ranked, novel_budget=2)) == 2


def test_a_new_movement_without_a_cue_sheet_is_not_a_candidate():
    lib = _lib()
    e = lib["movements"]["standing_calf_raise_machine"]
    e["source"], e["history"] = "expansion", None
    cat = _cat()
    cat["standing_calf_raise_machine"]["sessions"] = 0
    s = _slot(_week(lib=lib, cat=cat), "lower_heavy.calf_raise_machine")
    assert s["pick"]["movement_id"] != "standing_calf_raise_machine"


# ── fallbacks, skill track, anchors ──────────────────────────────────────────
def test_every_pick_carries_ranked_fallbacks_that_are_themselves_selectable():
    sel = _week()
    for s in sel["slots"]:
        if not s.get("pick") or s.get("pinned"):
            continue
        assert s["fallbacks"], s["slot_id"]
        for f in s["fallbacks"]:
            e = LIB0["movements"][f["movement_id"]]
            assert se.availability(e, LIB0, None) is None and not se.locked_gates(e, LIB0)
    line = se.fallback_note_line(sel["slots"][0]["pick"], sel["slots"][0]["fallbacks"])
    assert line and line.startswith("If taken: ") and sel["slots"][0]["fallback_note"] == line
    assert se.fallback_note_line(sel["slots"][0]["pick"], []) is None


def test_skill_track_never_fills_a_hypertrophy_slot():
    sel = _week()
    assert not any(LIB0["movements"].get(m or "", {}).get("family") == "skill_athletic" for m in _picks(sel))
    assert sel["skill_track"]["optional"] and sel["skill_track"]["volume"]["sets_max"] <= 2
    assert sel["skill_track"]["ladders"], "the library's chain gates make at least one ladder"
    # control: a curl relabelled skill/athletic leaves the curl slot's candidates
    lib = _lib()
    pick = _slot(_week(), "upper_heavy.db_curl")["pick"]["movement_id"]
    lib["movements"][pick]["family"] = "skill_athletic"
    assert pick not in _served_anywhere(_week(lib=lib))


def test_only_accessory_slots_are_selected_anchors_stay_fixed():
    assert {s["slot_id"] for s in _week()["slots"]} == {s["slot_id"] for s in vr.slots()}
    pinned = _slot(_week(), "shoulders_arms.farmers_walk")
    assert pinned["pick"]["catalog_key"] == "farmers_walk" and pinned["pick"]["c_reason"]["code"] == "owner_pin"


def test_selection_is_deterministic():
    assert json.dumps(_week(), sort_keys=True) == json.dumps(_week(), sort_keys=True)


# ── variety: best per slot, no repeats per week (owner ruling 2026-11-11) ──
CURL_SLOTS = ("upper_heavy.db_curl", "shoulders_arms.db_curl", "upper_volume.db_curl")


def test_three_curl_slots_get_three_different_curls():
    sel = _week()
    picks = [_slot(sel, sid)["pick"] for sid in CURL_SLOTS]
    assert len({p["catalog_key"] for p in picks}) == 3, [p["title"] for p in picks]
    # evidence still ranks each slot: the first curl slot takes the slot's best, the later ones the next-best
    assert picks[0]["week_repeat"] is None
    for p in picks[1:]:
        assert p["week_repeat"]["code"] == "week_repeat" and picks[0]["movement_id"] in p["week_repeat"]["skipped"]
    assert se.TIER_RANK[picks[0]["tier"]] <= min(se.TIER_RANK[p["tier"]] for p in picks[1:])


def test_no_movement_fills_two_unpinned_slots_in_one_week():
    sel = _week()
    keys = [s["pick"]["catalog_key"] for s in sel["slots"] if s.get("pick") and not s.get("pinned")]
    assert len(keys) == len(set(keys))


def _slot_ctx(slot_id: str) -> tuple[dict, dict]:
    lib, cat = _lib(), _cat()
    env = {"lib": lib, "catalog": cat, "overlay": None, "inventory": None, "idx": se.key_index(lib, cat), "ceiling": 2, "missing": []}
    slot = next(s for s in vr.slots() if s["slot_id"] == slot_id)
    return slot, se._ctx(slot, env, 2)


def test_a_taken_best_passes_to_the_next_best_and_a_repeat_only_when_none_is_left():
    slot, ctx = _slot_ctx("upper_heavy.db_curl")
    free = se.select_slot(slot, ctx, set(), set())
    best = free["pick"]["catalog_key"]
    nxt = se.select_slot(slot, ctx, set(), {best})
    assert nxt["pick"]["catalog_key"] != best and nxt["pick"]["week_repeat"]["code"] == "week_repeat"
    every = {c for c in (se.key_index(ctx["lib"], ctx["catalog"])["to_cat"].values())}
    stuck = se.select_slot(slot, ctx, set(), every)
    assert stuck["pick"]["catalog_key"] == best and stuck["pick"]["week_repeat"]["code"] == "week_repeat_unavoidable"


def test_a_c_pick_below_a_taken_a_or_b_names_week_repeat():
    pick = {"tier": "C", "movement_id": "c"}
    skipped = [{"tier": "B", "movement_id": "b", "title": "B one"}]
    assert se.c_reason(pick, [], skipped=skipped)["code"] == "week_repeat"
    assert se.c_reason(pick, [])["code"] == "library_gap"  # control: nothing skipped


def test_the_lengthened_swap_never_makes_a_week_repeat():
    def c(mid, bias):
        return {
            "movement_id": mid,
            "catalog_key": mid,
            "title": mid,
            "tier": "C",
            "n1": {"score": 0},
            "length_bias": bias,
            "novel": False,
            "equipment": [],
            "exposures": 1,
        }

    spec = {"muscle": "biceps"}
    a = {"slot_id": "s1", "spec": spec, "pick": c("mid_a", "mid") | {"c_reason": None, "week_repeat": None}}
    b = {"slot_id": "s2", "spec": spec, "pick": c("long_b", "lengthened") | {"c_reason": None, "week_repeat": None}}
    b["pick"]["length_bias"] = "mid"  # neither pick lengthened; s1's only lengthened alternative is s2's own pick
    full = {"s1": [c("mid_a", "mid"), c("long_b", "lengthened")], "s2": [c("long_b", "lengthened")]}
    rows = se._lengthened_pass([a, b], full)
    assert a["pick"]["movement_id"] == "mid_a"  # s1 did not take s2's movement
    assert {r["muscle"]: r["state"] for r in rows}["biceps"] in ("adjusted", "unmet")


def test_owner_pinned_slots_are_exempt():
    pinned = _slot(_week(), "shoulders_arms.farmers_walk")
    assert pinned["pick"]["catalog_key"] == "farmers_walk" and pinned["pick"]["week_repeat"] is None


# ── the switch: shadow while proposed, live only when approved ───────────────
def test_proposed_library_runs_in_shadow_and_serves_the_pools():
    cat = _cat()
    rot = vr.plan(WEEK7, cat, role="upper_heavy", rows=[], ledger_state="injected")
    before = copy.deepcopy(rot["variants"])
    out = se.apply(copy.deepcopy(rot), cat, rows=[], lib=_lib("proposed"), overlay=None)
    assert out["variants"] == before and out["ledger_writes"] == rot["ledger_writes"]
    fields = se.snapshot_fields(out)
    assert set(fields) == {"selection_shadow"} and fields["selection_shadow"]["mode"] == "shadow"
    assert "selection" not in out
    assert {c["slot_id"] for c in fields["selection_shadow"]["compare"]} == {s["slot_id"] for s in vr.slots()}


def test_approved_library_serves_the_selection_live():
    cat = _cat()
    rot = vr.plan(WEEK7, cat, role="upper_heavy", rows=[], ledger_state="injected")
    sel = _week(lib=_lib("approved"))
    out = se.apply(copy.deepcopy(rot), cat, rows=[], lib=_lib("approved"), overlay=None, target_date="2026-11-12")
    want = sel["variants_by_role"]["upper_heavy"]
    assert out["variants"] == want != rot["variants"]
    assert out["volume_check"]["unchanged"]
    assert {w["variant"] for w in out["ledger_writes"]} <= set(want.values())
    assert set(se.snapshot_fields(out)) == {"selection"}
    # control: the same inputs at status proposed never touch the served variants
    assert se.apply(copy.deepcopy(rot), cat, rows=[], lib=_lib("proposed"), overlay=None)["variants"] == rot["variants"]


def test_live_keeps_the_ledgers_held_variant_when_still_eligible():
    cat = _cat()
    sel = _week(lib=_lib("approved"))
    s = _slot(sel, "upper_heavy.reverse_pec_deck")
    held = s["fallbacks"][0]["catalog_key"]
    rows = [{"sk": vr.ledger_sk(2, "upper_heavy.reverse_pec_deck"), "block": 2, "phase_1": {"variant": held}}]
    rot = vr.plan(WEEK7, cat, role="upper_heavy", rows=rows, ledger_state="injected")
    out = se.apply(rot, cat, rows=rows, lib=_lib("approved"), overlay=None)
    assert out["variants"]["reverse_pec_deck"] == held


def test_no_library_serves_the_pools_and_says_so():
    cat = _cat()
    rot = vr.plan(WEEK7, cat, role="upper_heavy", rows=[], ledger_state="injected")
    out = se.apply(copy.deepcopy(rot), cat, lib=None)
    assert out["variants"] == rot["variants"] and out["selection"]["mode"] == "no_library"
    assert se.mode(None) == "no_library" and se.mode({"status": "retired"}) == "shadow"


def test_a_failing_selection_never_blocks_the_draft(monkeypatch):
    cat = _cat()
    rot = vr.plan(WEEK7, cat, role="upper_heavy", rows=[], ledger_state="injected")
    monkeypatch.setattr(se, "select_week", lambda *a, **k: 1 / 0)
    out = se.apply(copy.deepcopy(rot), cat, lib=_lib("approved"), overlay=None)
    assert out["variants"] == rot["variants"] and out["selection"]["state"] == "failed"


def test_for_session_select_attaches_the_shadow_record():
    cat = _cat()
    se._LIB_CACHE.update(lib=_lib("proposed"), at=float("inf"))
    out = vr.for_session(WEEK7, cat, rows=[], select=True)
    assert out["selection"]["mode"] == "shadow"
    assert "selection" not in vr.for_session(WEEK7, cat, rows=[])


# ── library_version on every plan ────────────────────────────────────────────
def test_library_version_is_stamped_on_every_draft(monkeypatch):
    ir = RoutineSpec(routine_id="r", target_date="2026-11-12", archetype="x")
    routine_repo.stamp_library_version(ir)
    assert ir.inputs_snapshot["library_version"] == LIB0["version"]
    monkeypatch.setattr(se, "load_library_failsoft", lambda: None)
    routine_repo.stamp_library_version(ir)
    assert ir.inputs_snapshot["library_version"] is None
    src = (REPO / "lambdas" / "training" / "routine_repo.py").read_text()
    body = src[src.index("def draft_versioned") :]
    assert "stamp_library_version(ir)" in body[: body.index("existing = get_current")]


# ── the critic is a pure training function (#5784) ───────────────────────────
def test_selection_critic_never_imports_lambdas_coach():
    for name in ("selection_critic.py", "selection_engine.py"):
        tree = ast.parse((REPO / "lambdas" / "training" / name).read_text())
        mods = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
        mods += [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
        assert not [m for m in mods if m == "coach" or m.startswith("coach.")], name


def test_critic_fails_the_week_on_a_blocking_concession_miss():
    ir = {"exercises": [], "inputs_snapshot": {"rotation": {"kettlebell_weekly": {"blocking": True, "note": "no kettlebell"}}}}
    assert critic.evaluate(ir, _lib(), None, None)["verdict"] == "fail"
    ir["inputs_snapshot"]["rotation"]["kettlebell_weekly"]["blocking"] = False
    assert critic.evaluate(ir, _lib(), None, None)["verdict"] == "pass"


def test_critic_without_a_record_or_catalog_says_not_evaluated():
    out = critic.evaluate({"exercises": [{"movement_key": "farmers_walk"}], "inputs_snapshot": {}}, _lib(), None, None)
    assert out["ranking_source"] == "not_evaluated"


# ── end to end: the generated draft ──────────────────────────────────────────
def _done(n: int) -> list[dict]:
    from common.pacific_time import shift_day_key

    return [
        {
            "date": shift_day_key("2026-09-24", i),
            "source_workout_id": f"w{i}",
            "exercises": [
                {"name": "Linear Leg Press", "sets": [{"type": "normal", "weight_kg": 90, "reps": 5}]},
                {"name": "Bench Press (Barbell)", "sets": [{"type": "normal", "weight_kg": 60, "reps": 5}]},
                {"name": "Lateral Raise (Dumbbell)", "sets": [{"type": "normal", "weight_kg": 10, "reps": 12}]},
            ],
        }
        for i in range(n)
    ]


def _draft(status: str):
    from unittest.mock import patch

    from training import routine_generator

    se._LIB_CACHE.update(lib=_lib(status), at=float("inf"))
    with (
        patch.object(routine_generator, "_load_note_indexes", return_value=({}, {}, {}, {})),
        patch("training.deload_word.load_records_failsoft", return_value=[]),
        patch("training.disruption.load_records_failsoft", return_value=[]),
    ):
        inputs = routine_generator.GeneratorInputs(target_date="2026-11-20", block_workouts=_done(40), rotation_rows=[])
        return routine_generator.generate_routines(inputs)[0]


def test_a_generated_draft_records_the_shadow_and_serves_the_pools():
    ideal = _draft("proposed")
    snap = ideal.inputs_snapshot
    assert snap["selection_shadow"]["mode"] == "shadow" and "selection" not in snap and "selection" not in snap["rotation"]
    role = snap["calendar"]["session_role"]
    pools = vr.plan({**snap["calendar"], "date": "2026-11-20"}, CAT0, rows=[], ledger_state="injected")["variants"]
    keys = [b.movement_key for b in ideal.exercises]
    assert snap["rotation"]["variants"] == pools and all(v in keys for v in pools.values()), role


def test_a_generated_draft_serves_the_selection_once_approved():
    ideal = _draft("approved")
    snap = ideal.inputs_snapshot
    assert snap["selection"]["mode"] == "live" and "selection_shadow" not in snap
    assert snap["rotation"]["position"]["step"] > 0 and snap["rotation"].get("source") == "selection"
    role = snap["calendar"]["session_role"]
    want = snap["selection"]["variants_by_role"][role]
    keys = [b.movement_key for b in ideal.exercises]
    assert snap["rotation"]["variants"] == want and all(v in keys for v in want.values())
