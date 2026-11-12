"""#5780 (S11, epic #5770) — the exercise library's guarantees, held over the SHIPPED config and a real selection run.

The guarantees (the issue's acceptance boxes), each checked by one offender-collecting helper over EVERY rotation position
of the program (one per phase, genesis to the charter's target date — the selection only changes at a phase boundary),
and each beside a must-fail control that mutates the config or the engine and shows the helper names the offender:

  G1  every slot candidate the engine considers (template accessory, vetted pool, pinned entry, served variant, pick,
      fallback) joins a library entry through the engine's own join (`selection_engine.key_index`);
  G2  no slot pick sits below the best available tier without a recorded reason — every better-tier candidate of the
      slot is either an exclusion recorded on `above_pick` with a `C_REASONS` code, or a `week_repeat` skip; a C/D pick
      carries `c_reason`; `library_gap` only where the slot truly has no higher-tier candidate. Owner pins are exempt.
      Tiers are the library's QUALITY tiers, S-D, derived by its rubric (#5857);
  G3  no prescription (the served week, anchors included; every pick and fallback) names equipment that is not
      `available` at home_gym in the library's `gym_inventory`, nor anything on the charter's `equipment.not_available`;
  G4  every concession-ledger weekly commitment (`week_commitments`, #5774) is met by the served week — once the library
      is approved too, a hold at a phase boundary accepted only under owner ruling B (#5856, 2026-11-12);
  G5  gates (`exercise_gates`, #5772) evaluate from measured inputs only: an unmeasured input reads `locked` with input
      `unknown` / `not_set`, never a guessed value — the six overlay-referenced bw_* thresholds are null in the public
      file (owner-owed) and read locked.

Inputs: the shipped `config/exercise_library.json`, `config/movement_catalog.json`, `config/training_charter.json`; the
default skill ceiling (2); NO private overlay (the N=1 fit is unknown) except where a test injects a SYNTHETIC one. The
ledger is simulated in memory phase by phase (what `variant_rotation.record` would write). No AWS, no network, no clock:
every date is a literal.
"""

from __future__ import annotations

import copy
import datetime as dt
import json
import os
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "lambdas"))
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from common import constants  # noqa: E402
from training import (  # noqa: E402
    exercise_gates as eg,
    exercise_library as xl,
    kb_entry,
    selection_engine as se,
    training_charter as tc,
    variant_rotation as vr,
    week_commitments as wc,
    week_floors as wf,
)
from training.block_model import block_weeks  # noqa: E402

LIB0 = json.loads((REPO / "config" / "exercise_library.json").read_text())
CAT0 = json.loads((REPO / "config" / "movement_catalog.json").read_text())["movements"]
CHARTER0 = json.loads((REPO / "config" / "training_charter.json").read_text())
CEILING = 2  # the generator's default skill ceiling (`select_week`'s default)
KB_EXPOSURES = (0, kb_entry.ENTRY_EXPOSURES)  # the KB slot before (the KB deadlift) and after (the swing) its entry
WARN_DAY, BLOCK_DAY = "2026-11-12", wf.KETTLEBELL_BLOCK_FROM  # the kettlebell commitment warns, then blocks
BW_OVERLAY_IDS = ("bw_pull", "bw_dip", "bw_pushup", "bw_nordic", "bw_hanging", "bw_advanced")


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    monkeypatch.delenv(tc.PRIVATE_ENV_VAR, raising=False)
    monkeypatch.delenv(xl.PRIVATE_ENV_VAR, raising=False)
    monkeypatch.setattr(tc, "_from_s3", lambda key: None)
    monkeypatch.setattr(xl, "_overlay_from_local", lambda: None)
    monkeypatch.setattr(xl, "_overlay_from_s3", lambda: None)
    monkeypatch.setattr(wf, "library", lambda path=None: copy.deepcopy(LIB0))
    tc.reset_cache()
    se._LIB_CACHE.clear()
    yield
    tc.reset_cache()
    se._LIB_CACHE.clear()


# ── the program: one rotation position per phase, genesis -> the charter's target date ─────────────────────────────
def _program_entries(day: str = WARN_DAY) -> list[dict]:
    start = dt.date.fromisoformat(constants.EXPERIMENT_START_DATE)
    target = dt.date.fromisoformat(CHARTER0["governing_goal"]["target_date"])
    weeks = -(-((target - start).days + 1) // 7)
    blocks = -(-weeks // block_weeks())
    every = vr.rotate_every_weeks()
    out = []
    for block in range(1, blocks + 1):
        for phase in range(1, vr.phases_per_block() + 1):
            week = (block - 1) * block_weeks() + (phase - 1) * every + 1
            out.append({"week": week, "block": block, "session_role": "lower_heavy", "date": day})
    return out


def _lib(status: str | None = None) -> dict:
    lib = copy.deepcopy(LIB0)
    if status:
        lib["status"] = status
    return lib


def _record(ledger: dict, writes: list[dict]) -> None:
    """What `variant_rotation.record` writes: `if_not_exists` per phase, so the first draft of a phase wins."""
    for w in writes or []:
        sk = vr.ledger_sk(int(w["block"]), w["slot_id"])
        ledger.setdefault(sk, {"sk": sk, "block": int(w["block"])}).setdefault(f"phase_{int(w['phase'])}", {"variant": w["variant"]})


def _serve_program(lib: dict, cat: dict, *, kb: int, day: str = WARN_DAY, overlay=None) -> list[tuple[dict, dict]]:
    """[(position, the drafted rotation)] for every phase in order: the pools plan (`variant_rotation.plan`, every role),
    then the selection engine (`selection_engine.apply`: SHADOW for a proposed library, LIVE for an approved one), the
    ledger carried forward from each phase's writes."""
    ledger: dict = {}
    out = []
    for entry in _program_entries(day):
        rows = [r for r in ledger.values() if r["block"] in (entry["block"], entry["block"] - 1)]
        rot = vr.plan(entry, cat, rows=rows, role="*", kb_exposures=kb, skill_ceiling=CEILING)
        served = se.apply(rot, cat, rows=rows, skill_ceiling=CEILING, target_date=day, lib=lib, overlay=overlay)
        _record(ledger, served.get("ledger_writes"))
        out.append((vr.position(entry), served))
    return out


_SHIPPED: dict = {}


def _shipped(kb: int) -> list[tuple[dict, dict]]:
    """The shipped program (proposed library, no overlay), computed once per KB exposure count — read-only to callers."""
    if kb not in _SHIPPED:
        _SHIPPED[kb] = _serve_program(_lib(), CAT0, kb=kb)
    return _SHIPPED[kb]


def _selections(lib: dict, cat: dict, overlay=None, missing=None) -> list[tuple[dict, dict]]:
    """[(position, select_week)] over every phase of the program: no ledger (recency only reorders within a tier)."""
    return [
        (vr.position(e), se.select_week(vr.position(e), cat, lib, overlay, missing=missing, skill_ceiling=CEILING))
        for e in _program_entries()
    ]


def _env(lib: dict, cat: dict, overlay=None, missing=None) -> dict:
    return {
        "lib": lib,
        "catalog": cat,
        "overlay": overlay,
        "inventory": None,
        "idx": se.key_index(lib, cat),
        "ceiling": CEILING,
        "missing": vr.not_available() if missing is None else missing,
    }


def _served_keys(rotation: dict, cat: dict) -> set[str]:
    return {s["key"] for s in wc.served_week(rotation, cat, skill_ceiling=CEILING)}


# ── G1: every slot candidate has a library entry ─────────────────────────────────────────────────────────────────
def _slot_candidate_keys(cat: dict, programs: list[list[tuple[dict, dict]]]) -> set[str]:
    keys: set[str] = set()
    for slot in vr.slots():
        keys.add(slot["incumbent"])
        keys |= set((vr.VETTED_POOLS.get(slot["incumbent"]) or {}).get("candidates") or [])
        keys |= set(vr.seed_pool(slot["incumbent"], cat, skill_ceiling=CEILING)["pool"])
    keys |= {kb_entry.ENTRY, kb_entry.TARGET}
    for program in programs:
        for _pos, rot in program:
            for s in rot.get("slots") or []:
                keys |= {k for k in [s.get("variant")] + list(s.get("pool") or []) if k}
            for s in (rot.get("selection") or {}).get("slots") or []:
                keys |= {
                    k for k in [(s.get("pick") or {}).get("catalog_key")] + [f.get("catalog_key") for f in s.get("fallbacks") or []] if k
                }
    return keys


def _unjoined(lib: dict, cat: dict, keys: set[str]) -> list[str]:
    to_lib = se.key_index(lib, cat)["to_lib"]
    return sorted(k for k in keys if to_lib.get(k) not in xl.movements(lib))


def test_g1_every_slot_candidate_has_a_library_entry():
    programs = [_shipped(kb) for kb in KB_EXPOSURES]
    keys = _slot_candidate_keys(CAT0, programs)
    assert len(keys) > 30, "the candidate set must be the real one"
    assert _unjoined(LIB0, CAT0, keys) == []
    # every library id the selection names is a library movement (ranked, excluded, picked, fallback)
    for program in programs:
        for _pos, rot in program:
            for s in rot["selection"]["slots"]:
                ids = [(s.get("pick") or {}).get("movement_id")] + [f["movement_id"] for f in s.get("fallbacks") or []]
                ids += list(s.get("ranked_top") or []) + [x["movement_id"] for x in s.get("above_pick") or []]
                assert set(i for i in ids if i) <= set(xl.movements(LIB0)), s["slot_id"]


def test_g1_control_a_candidate_without_a_library_entry_is_named():
    keys = _slot_candidate_keys(CAT0, [_shipped(0)])
    # control 1: the title-joined incumbent (no Hevy hint, ADR-069) loses its library entry
    lib = _lib()
    del lib["movements"]["rear_delt_reverse_fly_machine"]
    assert _unjoined(lib, CAT0, keys) == ["reverse_pec_deck"]
    # control 2: a hinted candidate whose hint stops matching any library template
    cat = copy.deepcopy(CAT0)
    assert "leg_curl" not in xl.movements(LIB0)  # joined by its hint (the seated leg curl), not by an equal key
    cat["leg_curl"]["hevy_template_id_hint"] = "00000000"
    assert _unjoined(LIB0, cat, keys) == ["leg_curl"]


def test_g1_a_hintless_catalog_entry_joins_its_one_same_titled_library_entry():
    """The #5780 finding: `reverse_pec_deck` (a template accessory, resolved by title at commit — ADR-069) had no library
    entry through `key_index`, so its slot's own incumbent was never a candidate and its equipment was never checked."""
    assert not CAT0["reverse_pec_deck"].get("hevy_template_id_hint")
    idx = se.key_index(LIB0, CAT0)
    assert idx["to_lib"]["reverse_pec_deck"] == "rear_delt_reverse_fly_machine"
    # control: a second library entry with the same title makes the title ambiguous -> no join (never a guess)
    lib = _lib()
    lib["movements"]["planted_twin"] = copy.deepcopy(lib["movements"]["rear_delt_reverse_fly_machine"]) | {"template_id": "PLANTED1"}
    assert "reverse_pec_deck" not in se.key_index(lib, CAT0)["to_lib"]
    # control: a hinted entry never joins by title (its hint is the contract)
    cat = copy.deepcopy(CAT0)
    cat["reverse_pec_deck"]["hevy_template_id_hint"] = "00000000"
    assert "reverse_pec_deck" not in se.key_index(LIB0, cat)["to_lib"]


# ── G2: no unexplained sub-tier pick ─────────────────────────────────────────────────────────────────────────────
def _unexplained(sel: dict, step: int, env: dict) -> list[str]:
    """Offenders: a better-tier candidate of the slot that is neither a recorded exclusion nor a week-repeat skip; a C/D
    pick with no `C_REASONS` code; a `library_gap` that is false; a named blocker that is not a better-tier candidate."""
    by_id = {s["slot_id"]: s for s in sel["slots"]}
    out = []
    for slot in vr.slots():
        s = by_id[slot["slot_id"]]
        pick = s.get("pick")
        if not pick:
            continue
        reason = pick.get("c_reason") or {}
        if s.get("pinned") or (s.get("owner_pin") or {}).get("state") == "held":
            if pick["tier"] in se.REASONED_TIERS and reason.get("code") != "owner_pin":
                out.append(f"{slot['slot_id']}: an owner pin's {pick['tier']} pick without the owner_pin reason")
            continue
        eligible, excluded = se.candidates(se._ctx(slot, env, step))
        rank = se.TIER_RANK[pick["tier"]]
        better = {c["movement_id"]: c for c in eligible + excluded if se.TIER_RANK[c["tier"]] < rank}
        recorded = {x["movement_id"]: x["code"] for x in s.get("above_pick") or [] if x.get("code") in se.C_REASONS}
        skipped = set((pick.get("week_repeat") or {}).get("skipped") or [])
        for mid in sorted(better):
            if mid not in recorded and mid not in skipped:
                out.append(
                    f"{slot['slot_id']}: {pick['movement_id']} (tier {pick['tier']}) sits below {mid} (tier {better[mid]['tier']}) unexplained"
                )
        if pick["tier"] in se.REASONED_TIERS:
            code = reason.get("code")
            if code not in se.C_REASONS:
                out.append(f"{slot['slot_id']}: {pick['tier']} pick {pick['movement_id']} with no recorded reason ({code!r})")
            elif code == "library_gap" and better:
                out.append(f"{slot['slot_id']}: library_gap recorded but {sorted(better)} are higher-tier candidates")
            elif code not in ("library_gap", "owner_pin") and reason.get("blocked") not in better:
                out.append(f"{slot['slot_id']}: c_reason names {reason.get('blocked')!r}, not a better-tier candidate")
    return out


def _synthetic_overlay() -> dict:
    """A SYNTHETIC owner overlay (no real values): a pain-class note on the slot's S-tier overhead extension, a learned
    'gym doesn't have it' on the rear-delt machine, and swap-outs on a curl — so pain, equipment and N=1 all move picks."""
    m = xl.movements(LIB0)
    return {
        "pain_source": xl.PAIN_SOURCE_ID,
        "per_template": {
            m["overhead_triceps_extension_cable"]["template_id"]: {"note_signals": {"pain_flag": 1}},
            m["preacher_curl_dumbbell"]["template_id"]: {"note_signals": {"swap": 3}},
        },
        "availability_learned": {"rear_delt_machine": {"home_gym": {"state": "unavailable", "source": "synthetic"}}},
    }


def test_g2_no_slot_pick_sits_below_the_best_available_tier_without_a_reason():
    lib, cat = _lib(), CAT0
    seen_codes: set[str] = set()
    for overlay in (None, _synthetic_overlay()):
        env = _env(lib, cat, overlay)
        for pos, sel in _selections(lib, cat, overlay):
            assert _unexplained(sel, pos["step"], env) == [], (pos, overlay is not None)
            seen_codes |= {(s["pick"].get("c_reason") or {}).get("code") for s in sel["slots"] if s.get("pick")}
            seen_codes |= {(s["pick"].get("week_repeat") or {}).get("code") for s in sel["slots"] if s.get("pick")}
            seen_codes |= {x["code"] for s in sel["slots"] for x in s.get("above_pick") or []}
    for pos, rot in _shipped(0):  # the drafted (shadow) record, with the ledger carried forward, holds too
        assert _unexplained(rot["selection"], pos["step"], _env(lib, cat)) == [], pos
    # the run exercised the reasons it guards: the guard is not vacuous. `library_gap` is no longer reached by the shipped
    # library — every slot's job holds a higher-tier movement now that the tiers grade quality (#5857); control 3 of the
    # test below plants one and the guard names it.
    assert {"week_repeat", "not_prescribable", "equipment", "owner_pin", "weekly_floor", "pain_swap"} <= seen_codes


def _plant_top(lib: dict, keep: str, muscle: str, to: str) -> dict:
    """Every OTHER `muscle` movement's rows above `to` planted down to it, so `keep` is the slot's best-tier movement."""
    for k, e in xl.movements(lib).items():
        if k != keep and (e.get("target") or {}).get("primary") == muscle:
            for r in e["hypertrophy"]:
                r["tier"] = to if se.TIER_RANK[r["tier"]] < se.TIER_RANK[to] else r["tier"]
    return lib


def test_g2_a_skill_ceiling_exclusion_is_recorded_not_silent():
    """Barbell movements sit at skill tier 3 and the generator's accessory ceiling is 2: a better-tier barbell candidate is
    excluded as `not_prescribable`, naming the ceiling, on the slot's `above_pick` — never an unexplained sub-tier pick.
    The shipped library's S bands sit above every barbell candidate (#5857), so the specimens are planted to lead."""
    pos = vr.position(_program_entries()[1])
    calf = _plant_top(_lib(), "standing_calf_raise_barbell", "calves", "B")
    sel = se.select_week(pos, CAT0, calf, None, skill_ceiling=CEILING)
    s = next(x for x in sel["slots"] if x["slot_id"] == "lower_volume.calf_raise_machine")
    hit = next(x for x in s["above_pick"] if x["movement_id"] == "standing_calf_raise_barbell")
    assert hit["code"] == "not_prescribable" and f"skill ceiling {CEILING}" in hit["why"]
    assert int(CAT0["standing_calf_raise_barbell"]["skill_tier"]) > CEILING
    # the owner's specimen: the barbell preacher curl (catalog entry since the 2026-11-11 rebuild) above a lower-tier curl
    curls = _plant_top(_lib(), "preacher_curl_barbell", "biceps", "C")
    sel_c = se.select_week(pos, CAT0, curls, None, skill_ceiling=CEILING)
    for sid in ("shoulders_arms.db_curl", "upper_volume.db_curl"):
        curl = next(x for x in sel_c["slots"] if x["slot_id"] == sid)
        hit = next(x for x in curl["above_pick"] if x["movement_id"] == "preacher_curl_barbell")
        assert hit["code"] == "not_prescribable" and f"skill ceiling {CEILING}" in hit["why"], sid
        assert curl["pick"]["tier"] in se.REASONED_TIERS and curl["pick"]["c_reason"]["code"] in se.C_REASONS, sid
    # control: at ceiling 3 the same movement is no longer excluded for the ceiling
    sel3 = se.select_week(pos, CAT0, calf, None, skill_ceiling=3)
    s3 = next(x for x in sel3["slots"] if x["slot_id"] == "lower_volume.calf_raise_machine")
    assert not any(x["movement_id"] == "standing_calf_raise_barbell" and "skill ceiling" in x["why"] for x in s3.get("above_pick") or [])


def test_g2_control_a_dropped_reason_or_a_misranked_pick_goes_red(monkeypatch):
    lib = _lib()
    env = _env(lib, CAT0)
    pos = vr.position(_program_entries()[1])
    sel = se.select_week(pos, CAT0, lib, None, skill_ceiling=CEILING)
    assert _unexplained(sel, pos["step"], env) == []
    # control 1: strip the recorded S exclusions above an A pick
    bad = copy.deepcopy(sel)
    next(s for s in bad["slots"] if s["slot_id"] == "lower_heavy.leg_press")["above_pick"] = []
    assert any("lower_heavy.leg_press" in o and "unexplained" in o for o in _unexplained(bad, pos["step"], env))
    # control 2: a C/D pick loses its reason
    bad = copy.deepcopy(sel)
    c_slot = next(s for s in bad["slots"] if s.get("pick") and s["pick"]["tier"] in se.REASONED_TIERS and not s.get("pinned"))
    c_slot["pick"]["c_reason"] = None
    assert any("no recorded reason" in o for o in _unexplained(bad, pos["step"], env))
    # control 3: a false library_gap where a higher-tier candidate exists
    bad = copy.deepcopy(sel)
    s = next(s for s in bad["slots"] if s["slot_id"] == "shoulders_arms.db_lateral_raise")
    assert s["pick"]["tier"] in se.REASONED_TIERS
    s["pick"]["c_reason"] = {"code": "library_gap", "why": "planted"}
    assert any("library_gap recorded but" in o for o in _unexplained(bad, pos["step"], env))
    # control 4: the ENGINE regresses — rank ignores tier — and the guard names the sub-tier picks
    real = se.rank_key
    monkeypatch.setattr(se, "rank_key", lambda c, recent, slot_last=None: (-se.TIER_RANK[c["tier"]],) + real(c, recent, slot_last)[1:])
    worse = se.select_week(pos, CAT0, lib, None, skill_ceiling=CEILING)
    assert any("unexplained" in o for o in _unexplained(worse, pos["step"], env))


# ── G3: no prescription names absent equipment ───────────────────────────────────────────────────────────────────
def _absent_equipment(keys: set[str], lib: dict, cat: dict, missing: list[str]) -> list[str]:
    """Offenders: a served catalog key with no library entry (its equipment is unknowable), whose library entry is not
    available at home_gym, that needs an inventory item not `available` there, or that is on the charter's list."""
    to_lib = se.key_index(lib, cat)["to_lib"]
    items = (lib.get("gym_inventory") or {}).get("items") or {}
    out = []
    for k in sorted(keys):
        hit = vr._unavailable(k, cat.get(k) or {}, missing)
        if hit:
            out.append(f"{k}: on the charter's equipment.not_available ({hit!r})")
        e = xl.movements(lib).get(to_lib.get(k) or "")
        if e is None:
            out.append(f"{k}: no library entry — its equipment cannot be checked")
            continue
        if ((e.get("availability") or {}).get(xl.LOCATION_ID) or {}).get("state") != "available":
            out.append(f"{k}: library availability at {xl.LOCATION_ID} is not available")
        for eid in e.get("equipment") or []:
            st = ((items.get(eid) or {}).get(xl.LOCATION_ID) or {}).get("state")
            if st != "available":
                out.append(f"{k}: equipment {eid} is {st or 'absent from gym_inventory'} at {xl.LOCATION_ID}")
            if hit is None and vr._unavailable(eid, {}, missing):
                out.append(f"{k}: equipment {eid} on the charter's equipment.not_available")
    return out


def _selection_keys(sel: dict) -> set[str]:
    out = set()
    for s in sel.get("slots") or []:
        out |= {k for k in [(s.get("pick") or {}).get("catalog_key")] + [f.get("catalog_key") for f in s.get("fallbacks") or []] if k}
    return out


def test_g3_no_prescription_names_equipment_absent_from_the_inventory():
    missing = vr.not_available()
    assert "preacher_curl_machine" in missing  # the shipped charter's list
    for kb in KB_EXPOSURES:
        for pos, rot in _shipped(kb):
            served = _served_keys(rot, CAT0)
            assert served and _absent_equipment(served, LIB0, CAT0, missing) == [], pos
            assert _absent_equipment(_selection_keys(rot["selection"]), LIB0, CAT0, missing) == [], pos
    for pos, rot in _serve_program(_lib("approved"), CAT0, kb=kb_entry.ENTRY_EXPOSURES):  # what serves once approved
        assert rot.get("source") == "selection" or pos["step"] == 0
        assert _absent_equipment(_served_keys(rot, CAT0), LIB0, CAT0, missing) == [], pos
    ov = _synthetic_overlay()  # learned unavailability: the rear-delt machine is never named
    for pos, sel in _selections(_lib(), CAT0, ov):
        assert "reverse_pec_deck" not in _selection_keys(sel), pos


def test_g3_control_absent_equipment_or_a_charter_listed_movement_goes_red():
    missing = vr.not_available()
    pos, rot = _shipped(0)[1]
    served = _served_keys(rot, CAT0)
    assert _absent_equipment(served, LIB0, CAT0, missing) == []
    # control 1: the inventory loses an item the served week needs (the pools do not read the inventory — this guard does)
    lib = _lib()
    lib["gym_inventory"]["items"]["cable_stack"]["home_gym"]["state"] = "unavailable"
    assert any("cable_stack is unavailable" in o for o in _absent_equipment(served, lib, CAT0, missing))
    # control 2: the inventory item is deleted outright
    lib = _lib()
    del lib["gym_inventory"]["items"]["dumbbell"]
    assert any("dumbbell is absent from gym_inventory" in o for o in _absent_equipment(served, lib, CAT0, missing))
    # control 3: the preacher curl machine (not available, on the charter's list) is planted into the served week
    offenders = _absent_equipment(served | {"preacher_curl_machine"}, LIB0, CAT0, missing)
    assert any("preacher_curl_machine: on the charter's equipment.not_available" in o for o in offenders)
    assert any("preacher_machine is unavailable" in o for o in offenders)
    # control 4: the charter lists a served movement
    key = sorted(served)[0]
    assert any(o.startswith(f"{key}: on the charter's") for o in _absent_equipment(served, LIB0, CAT0, missing + [key]))


# ── G4: every concession-ledger weekly commitment is met by the served week ──────────────────────────────────────
def _commitment_offenders(rot: dict, pos: dict, *, on: str, lib: dict) -> list[str]:
    """Offenders: any commitment row not `met`. The ONE allowed exception is #5774's own recorded gate: block 1's first
    phase serves the committed template (`TEMPLATE_PHASE`), so the single-leg floor WARNS there with the gate named."""
    ev = wc.evaluate(rot, CAT0, on=on, library=lib)
    out = [f"stage 1 verdict {ev['verdict']}"] if ev["verdict"] != "pass" else []
    for r in ev["rows"]:
        if r["verdict"] == wc.MET:
            continue
        if r["id"] == "single_leg" and r["verdict"] == wc.WARN and pos["step"] == 0 and wc.TEMPLATE_PHASE in r["detail"]:
            continue
        out.append(f"{r['id']}: {r['verdict']} — {r['detail'][:160]}")
    return out


def test_g4_every_weekly_commitment_is_met_by_the_served_week():
    rows_seen = 0
    for kb in KB_EXPOSURES:
        for day in (WARN_DAY, BLOCK_DAY):
            program = _shipped(kb) if day == WARN_DAY else _serve_program(_lib(), CAT0, kb=kb, day=day)
            for pos, rot in program:
                assert rot["selection"]["mode"] == se.MODE_SHADOW  # the library is proposed: the pools serve
                assert _commitment_offenders(rot, pos, on=day, lib=LIB0) == [], (kb, day, pos)
                rows_seen += 1
    assert rows_seen == 4 * len(_program_entries())
    assert {c["id"] for c in wc.COMMITMENTS} == {
        "carries",
        "kettlebell",
        "single_leg",
        "corrective",
        "stretch_position",
        "rotation",
        "side_rear_delt_band",
    }


def test_g4_control_a_week_missing_a_commitment_goes_red():
    pos, rot = _shipped(kb_entry.ENTRY_EXPOSURES)[2]
    assert _commitment_offenders(rot, pos, on=BLOCK_DAY, lib=LIB0) == []
    # control 1: the carry slot serves a non-carry -> the carries floor blocks
    bad = copy.deepcopy(rot)
    served = _served_keys(rot, CAT0)
    other = next(k for k in ("seated_calf_raise", "chest_fly_machine", "bicep_curl_machine", "leg_extension_machine") if k not in served)
    bad["variants_by_role"]["shoulders_arms"]["farmers_walk"] = other  # a non-carry the week does not already serve
    assert any(o.startswith("carries: block") for o in _commitment_offenders(bad, pos, on=BLOCK_DAY, lib=LIB0))
    # control 2: the kettlebell slot serves a non-kettlebell movement after the enforcement date -> blocks
    bad = copy.deepcopy(rot)
    bad["variants_by_role"]["lower_volume"]["kettlebell_swing"] = "machine_crunch"
    assert any(o.startswith("kettlebell: block") for o in _commitment_offenders(bad, pos, on=BLOCK_DAY, lib=LIB0))
    # control 3: a slot held at a phase boundary -> the rotation commitment blocks
    bad = copy.deepcopy(rot)
    s = next(x for x in bad["slots"] if x.get("source") != "pinned" and len(x.get("pool") or []) >= 2)
    s["variant"] = s["previous"]
    assert any(o.startswith("rotation: block") for o in _commitment_offenders(bad, pos, on=BLOCK_DAY, lib=LIB0))


_APPROVED: list = []


def _approved_offenders() -> list[str]:
    """The commitment offenders of the program served LIVE (an approved library), computed once. `stage 1 verdict`
    lines are dropped: the rows name the cause."""
    if not _APPROVED:
        lib = _lib("approved")
        out = []
        for pos, rot in _serve_program(lib, CAT0, kb=kb_entry.ENTRY_EXPOSURES, day=BLOCK_DAY):
            assert rot.get("source") == "selection" or pos["step"] == 0, pos
            out += [
                f"step {pos['step']}: {o}" for o in _commitment_offenders(rot, pos, on=BLOCK_DAY, lib=lib) if not o.startswith("stage 1")
            ]
        _APPROVED.append(out)
    return _APPROVED[0]


def test_g4_once_approved_every_commitment_but_rotation_is_met_by_the_served_week():
    """The live selection (an APPROVED library) keeps carries, kettlebell, single-leg, corrective, stretch and the
    side/rear-delt band (rotation has its own test below)."""
    assert [o for o in _approved_offenders() if not o.split(": ", 1)[1].startswith("rotation:")] == []


def test_g4_the_served_week_still_meets_rotation_once_the_library_is_approved():
    """#5780's finding, closed by #5857 + owner ruling B on #5856 (2026-11-12). Once approved the selection serves live and
    ranks tier before variety. Quality bands now hold several members and each slot rotates within its band by its own
    history (`selection_engine.slot_last_served`); a held pick is accepted ONLY when it is its band's single servable
    member, and the hold is recorded on the rotation row."""
    assert [o for o in _approved_offenders() if o.split(": ", 1)[1].startswith("rotation:")] == []


def test_g4_control_rotation_without_ruling_b_or_with_a_wider_band_goes_red(monkeypatch):
    lib = _lib("approved")
    program = _serve_program(lib, CAT0, kb=kb_entry.ENTRY_EXPOSURES, day=BLOCK_DAY)
    held = [(pos, rot) for pos, rot in program if wc.rotation_holds(rot)]
    assert held, "the approved program exercises ruling B (a band with one servable member held at a boundary)"
    pos, rot = held[0]
    row = next(r for r in wc.evaluate(rot, CAT0, on=BLOCK_DAY, library=lib)["rows"] if r["id"] == "rotation")
    assert row["verdict"] == wc.MET and "owner ruling B" in row["detail"], "the accepted hold is recorded, not silent"
    # control 1: a held slot whose band has a SECOND member is not accepted — it must rotate
    bad = copy.deepcopy(rot)
    s = next(x for x in bad["slots"] if x.get("top_band") and x["variant"] == x.get("previous"))
    s["top_band"]["members"] = list(s["top_band"]["members"]) + ["a_second_member"]
    assert any(o.startswith("rotation: block") for o in _commitment_offenders(bad, pos, on=BLOCK_DAY, lib=lib))
    # control 2: the rotation check without ruling B -> the same approved program blocks stage 1 again
    monkeypatch.setattr(wc, "_sole_best", lambda slot: False)
    assert any(o.startswith("rotation: block") for o in _commitment_offenders(rot, pos, on=BLOCK_DAY, lib=lib))


def _guessed(gates: dict) -> list[str]:
    """Offenders: a locking gate open on an unmeasured input, an unknown/not-set input not reading locked, or an unknown
    bodyweight gate carrying a value it did not measure."""
    out = []
    for gid, row in sorted(gates.items()):
        if row.get("input") == eg.CUE:
            if row.get("kind") != "clinical_cue" and (LIB0["gates"].get(gid) or {}).get("locks") is not False:
                out.append(f"{gid}: a locking gate read as a cue")
            continue
        if row.get("input") in (eg.UNKNOWN, eg.NOT_SET) and row.get("state") != eg.LOCKED:
            out.append(f"{gid}: input {row['input']} but state {row.get('state')}")
        if row.get("input") not in (eg.MEASURED, eg.UNKNOWN, eg.NOT_SET):
            out.append(f"{gid}: input {row.get('input')!r} is not one of measured/unknown/not_set")
        if row.get("kind") == "bodyweight_threshold" and row.get("input") != eg.MEASURED and row.get("value_seen") is not None:
            out.append(f"{gid}: a value_seen on an unmeasured bodyweight gate")
    return out


def _synthetic_world() -> tuple[dict, dict]:
    """(overlay, measured) — every input the gates read, SYNTHETIC: thresholds far above a synthetic 7-day mean, the run
    gate open, a technique confirmation, the shipped (public) charter, an empty but READ Hevy record."""
    overlay = {
        "gate_thresholds": {g: {"value": 999} for g in BW_OVERLAY_IDS},
        "technique_confirmations": {m: True for m in xl.movements(LIB0)},
    }
    measured = {
        "as_of": "2026-11-08",
        "bodyweight": {"mean_lb": 100.0, "state": "synthetic"},
        "run_gate": {"gate_state": "open", "running_unlocked": True},
        "charter": copy.deepcopy(CHARTER0),
        "hevy_workouts": [],
    }
    return overlay, measured


def test_g5_unmeasured_inputs_read_locked_and_unknown():
    for measured in ({}, {"as_of": "2026-11-08"}):
        gates = eg.evaluate_gates(_lib(), None, measured)
        assert _guessed(gates) == []
        for gid, row in gates.items():
            if row["input"] != eg.CUE:
                assert (row["state"], row["input"]) == (eg.LOCKED, eg.UNKNOWN), gid
    # every movement that carries a locking gate of its own is locked when nothing is measured
    states = eg.movement_states(_lib(), eg.evaluate_gates(_lib(), None, {"as_of": "2026-11-08"}))
    assert all(s["state"] == eg.LOCKED for s in eg.gated_movements(states).values())


def _public_threshold_values(lib: dict) -> list[str]:
    """Offenders: a bodyweight gate in the PUBLIC library that carries a number (the owner sets it in the private overlay
    or the charter owns it — the library never does), or a gate whose unknown input is not `locked`."""
    out = []
    for gid, g in sorted((lib.get("gates") or {}).items()):
        if g.get("unknown_input") != xl.UNKNOWN_INPUT:
            out.append(f"{gid}: unknown_input {g.get('unknown_input')!r}")
        if g.get("kind") != "bodyweight_threshold":
            continue
        thr = g.get("threshold") or {}
        if any(k not in ("ref", "charter_ref", "comparison") for k in thr):
            out.append(f"{gid}: the public threshold carries {sorted(k for k in thr if k not in ('ref', 'charter_ref', 'comparison'))}")
        if not (str(thr.get("ref") or "").startswith("overlay:gate_thresholds.") or thr.get("charter_ref")):
            out.append(f"{gid}: the threshold names neither the overlay nor the charter")
    return out


def test_g5_the_six_bw_thresholds_are_null_in_public_and_read_locked():
    assert _public_threshold_values(LIB0) == []
    assert sorted(g for g, v in LIB0["gates"].items() if v["kind"] == "bodyweight_threshold" and "ref" in v["threshold"]) == sorted(
        BW_OVERLAY_IDS
    )
    # control: a number planted in the public file, or an unknown input that is not locked, is named
    lib = _lib()
    lib["gates"]["bw_pull"]["threshold"]["value"] = 999
    lib["gates"]["bw_dip"]["unknown_input"] = "unlocked"
    assert _public_threshold_values(lib) == ["bw_dip: unknown_input 'unlocked'", "bw_pull: the public threshold carries ['value']"]
    _ov, measured = _synthetic_world()
    no_overlay = eg.evaluate_gates(_lib(), None, measured)
    not_set = eg.evaluate_gates(_lib(), {"gate_thresholds": {}}, measured)
    for gid in BW_OVERLAY_IDS:
        assert (no_overlay[gid]["state"], no_overlay[gid]["input"]) == (eg.LOCKED, eg.UNKNOWN), gid
        assert (not_set[gid]["state"], not_set[gid]["input"], not_set[gid]["reason"]) == (eg.LOCKED, eg.NOT_SET, eg.THRESHOLD_NOT_SET)
        assert not_set[gid]["value_seen"] is None
    # control: a SYNTHETIC owner threshold plus a measured mean opens them — the lock is the missing input, not a constant
    opened = eg.evaluate_gates(_lib(), _synthetic_world()[0], measured)
    assert all((opened[g]["state"], opened[g]["input"]) == (eg.UNLOCKED, eg.MEASURED) for g in BW_OVERLAY_IDS)


def _drop_offenders(drop: str) -> list[str]:
    """Drop ONE measured input from the synthetic world: every gate whose verdict moved must now read locked with input
    unknown/not_set (never opened, never a guess); a drop that moves nothing is an offender too (a vacuous sweep)."""
    overlay, measured = _synthetic_world()
    full = eg.evaluate_gates(_lib(), overlay, measured)
    if drop == "overlay":
        overlay = None
    else:
        measured.pop(drop)
    less = eg.evaluate_gates(_lib(), overlay, measured)
    out = [f"{drop}: {o}" for o in _guessed(less)]
    changed = [g for g in full if (full[g]["state"], full[g]["input"]) != (less[g]["state"], less[g]["input"])]
    if not changed:
        out.append(f"{drop}: dropping it changed no gate")
    for g in changed:
        if less[g]["state"] != eg.LOCKED or less[g]["input"] not in (eg.UNKNOWN, eg.NOT_SET):
            out.append(f"{drop}: {g} reads {less[g]['state']}/{less[g]['input']} without it")
    return out


def test_g5_dropping_any_measured_input_never_opens_a_gate_and_reads_unknown():
    overlay, measured = _synthetic_world()
    assert any(r["state"] == eg.UNLOCKED and r["input"] == eg.MEASURED for r in eg.evaluate_gates(_lib(), overlay, measured).values())
    offenders = []
    for drop in ("bodyweight", "run_gate", "charter", "hevy_workouts", "overlay", "as_of"):
        offenders += _drop_offenders(drop)
    assert offenders == []


def test_g5_control_an_evaluator_that_guesses_goes_red(monkeypatch):
    _ov, measured = _synthetic_world()
    # control 1: an unknown input that reads open
    monkeypatch.setattr(eg, "_unknown", lambda reason: eg._verdict(eg.UNLOCKED, eg.UNKNOWN, reason))
    assert any("input unknown but state unlocked" in o for o in _guessed(eg.evaluate_gates(_lib(), None, {"as_of": "2026-11-08"})))
    monkeypatch.undo()
    # control 2: a bodyweight gate that guesses a threshold the owner never set
    real = eg.bodyweight_verdict

    def _guess(gid, g, overlay, m):
        return eg._verdict(eg.UNLOCKED, eg.NOT_SET, "guessed", {"threshold_lb": 999}) if not overlay else real(gid, g, overlay, m)

    monkeypatch.setattr(eg, "bodyweight_verdict", _guess)
    offenders = _guessed(eg.evaluate_gates(_lib(), None, measured))
    assert any("bw_pull: input not_set but state unlocked" in o for o in offenders)
    assert any("bw_pull: a value_seen on an unmeasured bodyweight gate" in o for o in offenders)
    monkeypatch.undo()
    # control 3: the run gate defaults to open when its reading is missing -> the drop sweep names it
    real_run = eg.running_verdict
    monkeypatch.setattr(
        eg,
        "running_verdict",
        lambda m: eg._verdict(eg.UNLOCKED, eg.MEASURED, "assumed open") if not isinstance(m.get("run_gate"), dict) else real_run(m),
    )
    assert any(o.startswith("run_gate:") for o in _drop_offenders("run_gate"))
