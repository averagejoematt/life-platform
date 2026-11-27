#!/usr/bin/env python3
"""scripts/recompute_character_private_replay.py — ONE step of the private character recompute, against ONE engine tree.

The pure, version-agnostic half of ``recompute_character_private.py`` (#6311). That tool runs this file as a child
process once per method step, each time with a different engine tree on ``sys.path`` (the pre-amendment tree is
materialised from git, the amended tree is the checkout itself), so two engine versions never share a process. The
child never reaches AWS: it reads one inputs file the parent wrote (stored rows, already fetched read-only) and writes
one result file. Its environment carries no AWS configuration (the parent points every AWS config path at /dev/null).

    python3 scripts/recompute_character_private_replay.py --spec SPEC.json --inputs INPUTS.json --result OUT.json

THE STEP SPEC (JSON):
  tree          the engine tree: a directory with ``lambdas/`` and ``config/character_sheet.json``
  new_tree      the amended tree (functions grafted INTO an old tree come from here, verbatim)
  old_tree      the pre-amendment tree (functions grafted into the new tree come from here, verbatim)
  rebuild       pillars re-scored from their STORED component scores under the step's config
  mind_drop     Mind components removed from the step's config, the remaining weights renormalised to the same total
  mind_config   "new": Mind's components exactly as the amended config carries them (both removals, renormalised)
  patches       any of: xp_net (old tree: the amended XP rules, grafted), no_neglect (old tree: the #913/#959 dark rules
                off), legacy_missing (new tree: the pre-amendment missing-data functions, grafted), rel_in_chain (new tree:
                Relationships back in the chain, taken verbatim from the stored row)
  loader        "legacy" (every stored day, a missing raw filled 40.0, the pre-amendment loader) or "held_skip" (the
                amended ``load_raw_score_histories`` rule: a held pillar-day is left out)
  relationships "verbatim" (the stored pillar through the chain) or "engine" (the tree's own rule)
  emit          "records" (the step's sheet records) or "items" (the planned DynamoDB items + receipts, the plan step)
  switches      the final #6293 module switches turned ON for the step (PLANNED_REST_PRORATES, LAB_AGE_TAPERS_WEIGHT,
                REST_DAY_COMPLETENESS, MOOD_NOT_OBSERVED); every other one of the four is OFF. A tree without them ignores it
  effects       which raw-input effects the step applies: planned_rest, lab_ageing, rest_day_completeness (below)

THE THREE RAW-DEPENDENT STEPS. planned_rest, lab_ageing and rest_day_completeness read inputs the stored component scores
do not carry (the planned-pause days, the lab draw, which sources arrived). The parent runs the compute Lambda's own
``assemble_data`` once per date (read-only) and records each switch's ON and OFF output on the SAME assembled inputs
(``inputs["raw_effects"]``). A step applies only that on/off DIFFERENCE to the stored-derived chain — never the raw value:
a raw recompute with the switches off does not reproduce the stored rows (late-arriving rows, earlier rule changes), and
that drift is not a method change. Movement's window components scale by the on/off ratio (the proration is linear in
the target below the cap); the lab score and the completeness shift by on minus off. A date whose on and off agree is
untouched. A stored row already computed by this engine version carries the effects natively and is never adjusted
again (idempotence after an apply).

WHAT A DAY REPLAYS FROM. Never a raw wearable, nutrition, habit or journal partition: each pillar's day is taken from the
stored sheet's own per-component measurements (the compute's record of what the sources said that night), re-weighted
under the step's config. That is the only reading that changes the METHOD and nothing else: a re-read of the raw
partitions today would also change the measurements (late data, backfills, the food-delivery modifier reads the
current streak), and those are not method changes. Chain state (EMA history, levels, XP, streaks, the shield, the
headline) is carried day to day from the step's OWN previous replayed record, from the experiment genesis.
"""

from __future__ import annotations

import argparse
import ast
import copy
import json
import os
import sys
from datetime import date, timedelta
from typing import Any, Optional

STEP_PATCHES = ("xp_net", "no_neglect", "legacy_missing", "rel_in_chain")
FINAL_SWITCHES = ("PLANNED_REST_PRORATES", "LAB_AGE_TAPERS_WEIGHT", "REST_DAY_COMPLETENESS", "MOOD_NOT_OBSERVED")
STEP_EFFECTS = ("planned_rest", "lab_ageing", "rest_day_completeness")
PILLAR_ORDER = ("sleep", "movement", "nutrition", "metabolic", "mind", "relationships", "consistency")
PRIMARY = ("sleep", "movement", "nutrition", "metabolic", "mind", "relationships")
LEGACY_FILL = 40.0  # the pre-amendment loader's stand-in for a missing raw score (removed by #6293)
XP_GRAFT = ("DEFAULT_XP_BANDS", "xp_day_verdict", "_compute_xp", "pillar_xp_transition", "xp_shield_delta")
MISSING_GRAFT = ("_weighted_pillar_score", "derive_consistency_inputs", "compute_consistency_raw")


# ── grafting a function verbatim from another tree (never a re-implementation) ─────────────────────────────────────


def graft(module: Any, source_file: str, names: tuple) -> None:
    """Define ``names`` from ``source_file`` INSIDE ``module``'s namespace, verbatim (their globals are the module's)."""
    with open(source_file, encoding="utf-8") as fh:
        src = fh.read()
    tree = ast.parse(src)
    found = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names:
            found[node.name] = ast.get_source_segment(src, node)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                if isinstance(t, ast.Name) and t.id in names:
                    found[t.id] = ast.get_source_segment(src, node)
    missing = [n for n in names if n not in found]
    if missing:
        raise RuntimeError(f"graft: {missing} not defined in {source_file}")
    for n in names:
        exec(compile(found[n], f"{source_file}::{n}", "exec"), module.__dict__)  # noqa: S102 — trusted repo source


# ── a stub table the config overlay reads from (the child never reaches AWS) ──────────────────────────────────────


class SnapshotTable:
    """The two reads the effective config makes: the personal-baselines snapshot (get_item) and the latest effect fit
    (the one query, newest first, limit 1). Anything else is refused."""

    def __init__(self, items: dict, fit_items: list):
        self._items = items
        self._fits = sorted(fit_items, key=lambda i: str(i.get("sk", "")), reverse=True)

    def get_item(self, Key: dict, **_kw: Any) -> dict:  # noqa: N803 — boto3's keyword
        item = self._items.get(f"{Key['pk']}|{Key['sk']}")
        return {"Item": copy.deepcopy(item)} if item is not None else {}

    def query(self, **kw: Any) -> dict:
        if kw.get("ScanIndexForward") is False and kw.get("Limit") == 1:
            return {"Items": copy.deepcopy(self._fits[:1])}
        raise RuntimeError("SnapshotTable: only the effect-fit query is served")

    def __getattr__(self, name: str) -> Any:
        raise RuntimeError(f"SnapshotTable is read-only and serves two reads only ({name} refused)")


# ── the step ───────────────────────────────────────────────────────────────────────────────────────────────────────


def shift(d: str, days: int) -> str:
    return (date.fromisoformat(d) + timedelta(days=days)).isoformat()


def load_tree(spec: dict) -> dict:
    """Import the step's engine modules from its tree and apply its patches. Returns the handles the replay uses."""
    tree = os.path.abspath(spec["tree"])
    sys.path.insert(0, os.path.join(tree, "lambdas"))
    os.environ.setdefault("S3_BUCKET", "unused-by-the-replay")
    from experiment import effect_fitter  # noqa: E402
    from health import (
        character_engine as ce,  # noqa: E402
        character_public as cpub,  # noqa: E402
        personal_baselines,  # noqa: E402
    )

    with open(os.path.join(tree, "config", "character_sheet.json"), encoding="utf-8") as fh:
        config = json.load(fh)
    patches = set(spec.get("patches") or ())
    unknown = patches - set(STEP_PATCHES)
    if unknown:
        raise RuntimeError(f"unknown patches {sorted(unknown)}")
    if "xp_net" in patches:
        graft(ce, os.path.join(spec["new_tree"], "lambdas", "health", "character_engine.py"), XP_GRAFT)
        with open(os.path.join(spec["new_tree"], "config", "character_sheet.json"), encoding="utf-8") as fh:
            new_cfg = json.load(fh)
        config["xp_bands"] = copy.deepcopy(new_cfg["xp_bands"])
        for k in ("daily_xp_decay", "xp_debt_cap"):
            (config.get("leveling") or {}).pop(k, None)
        last = {"shield": 0}
        transition, roll = ce.pillar_xp_transition, ce._roll_xp_buffer

        def _transition(raw, prev_xp, prev_debt, bonus, hold, cfg, day_number=None):
            last["shield"] = ce.xp_shield_delta(raw, hold, bonus, cfg)
            return transition(raw, prev_xp, prev_debt, bonus, hold, cfg, day_number=day_number)

        def _roll(prev_buffer, prev_xp, _new_xp, per, buffer_cap=None):  # the amended roll: by the measured verdict
            return roll(prev_buffer, prev_xp, (prev_xp or 0) + last["shield"], per, buffer_cap=buffer_cap)

        ce.pillar_xp_transition, ce._roll_xp_buffer = _transition, _roll
    if "no_neglect" in patches:
        ce.neglect_decay_state = lambda *_a, **_k: None  # also disarms the #959 dark persistence (it needs a decay)
        (config.get("leveling") or {}).pop("neglect_decay", None)
    if "legacy_missing" in patches:
        graft(ce, os.path.join(spec["old_tree"], "lambdas", "health", "character_engine.py"), MISSING_GRAFT)
        ce.day_is_held = lambda *_a, **_k: False  # pre-amendment: a no-evidence day entered every aggregate
    if "rel_in_chain" in patches:
        ce.UNINSTRUMENTED_PILLARS = ()
    on = set(spec.get("switches") or ())
    if on - set(FINAL_SWITCHES) or set(spec.get("effects") or ()) - set(STEP_EFFECTS):
        raise RuntimeError(f"unknown switches/effects in {spec.get('switches')} / {spec.get('effects')}")
    for name in FINAL_SWITCHES:
        if hasattr(ce, name):
            setattr(ce, name, name in on)
        elif name in on:
            raise RuntimeError(f"{name} is not in this engine tree")
    if "rel_in_chain" in patches:  # Relationships as the pre-amendment method configured it (its components and note)
        with open(os.path.join(spec["old_tree"], "config", "character_sheet.json"), encoding="utf-8") as fh:
            config["pillars"]["relationships"] = copy.deepcopy(json.load(fh)["pillars"]["relationships"])
    mind = ((config.get("pillars") or {}).get("mind") or {}).get("components") or {}
    if spec.get("mind_config") == "new":  # the amended Mind exactly (both components out, weights renormalised by 1/0.8)
        with open(os.path.join(spec["new_tree"], "config", "character_sheet.json"), encoding="utf-8") as fh:
            config["pillars"]["mind"]["components"] = copy.deepcopy(json.load(fh)["pillars"]["mind"]["components"])
    else:
        before = sum(float((c or {}).get("weight", 0)) for c in mind.values() if isinstance(c, dict))
        for name in spec.get("mind_drop") or ():
            mind.pop(name, None)
        after = sum(float((c or {}).get("weight", 0)) for c in mind.values() if isinstance(c, dict))
        if spec.get("mind_drop") and after > 0:  # the remaining weights renormalised, as the amended config does
            for c in mind.values():
                if isinstance(c, dict) and "weight" in c:
                    c["weight"] = c["weight"] * before / after
    return {"ce": ce, "cpub": cpub, "pb": personal_baselines, "fit": effect_fitter, "config": config}


def effective_config(h: dict, inputs: dict) -> dict:
    table = SnapshotTable(inputs.get("config_items") or {}, inputs.get("fit_items") or [])
    cfg = h["pb"].effective_character_config(h["config"], table, inputs["user_prefix"])
    h["fit"].merge_fit_into_config(cfg, h["fit"].load_latest_fit(table, inputs["user_id"]))
    return cfg


def rebuild_pillar(ce: Any, pillar: str, stored_pd: dict, config: dict) -> tuple:
    """(raw, details) from the stored component scores under ``config`` (an absent component re-enters as None, so the
    tree's own absent-input rule decides it)."""
    comps_cfg = (config["pillars"].get(pillar) or {}).get("components") or {}
    stored_comps = stored_pd.get("components") or {}
    scores = {}
    for name in comps_cfg:
        det = stored_comps.get(name)
        if not isinstance(det, dict):
            continue
        scores[name] = None if det.get("absent") else det.get("score")
    raw, details = ce._weighted_pillar_score(scores, comps_cfg)
    for name in scores:  # the stored measurement's target provenance, not today's baselines (the score is the stored one)
        det, out = stored_comps.get(name) or {}, details.get(name)
        if isinstance(out, dict):
            out.pop("target_provenance", None)
            if "target_provenance" in det:
                out["target_provenance"] = copy.deepcopy(det["target_provenance"])
    return raw, details


def shifted(stored: Any, off: Any, on: Any) -> Any:
    """``stored`` moved by on - off (clamped 0..100); the raw value only where there is no stored or off value to shift."""
    if on is None:
        return None
    if stored is None or off is None:
        return on
    return round(max(0.0, min(100.0, float(stored) + float(on) - float(off))), 1)


def planned_rest_movement(ce: Any, stored_pd: dict, config: dict, eff: dict, applied: list) -> tuple:
    """Movement with the planned-rest proration applied to the STORED window scores (each scaled by the raw recompute's
    on/off ratio; unknown where "on" is unknown; the raw value only where the stored or off score is missing), carrying
    ``_planned_rest`` with the un-prorated stored-derived values exactly as ``compute_movement_raw`` records them (the
    public method restores the day from it)."""
    pre_raw, pre_det = rebuild_pillar(ce, "movement", stored_pd, config)
    offc, onc = eff.get("off") or {}, eff.get("on") or {}
    days = int(eff.get("days") or 0)
    if not days or all(onc.get(c) == offc.get(c) for c in onc):
        return pre_raw, pre_det
    pd = copy.deepcopy(stored_pd)
    comps = pd.setdefault("components", {})
    for c, sc in onc.items():
        det = comps.get(c)
        if not isinstance(det, dict) or sc == offc.get(c):
            continue
        stored_sc = None if det.get("absent") else det.get("score")
        if sc is None:
            new = None
        elif stored_sc is None or not offc.get(c):
            new = sc
        else:
            new = round(min(100.0, float(stored_sc) * float(sc) / float(offc[c])), 1)
        comps[c] = {k: v for k, v in det.items() if k not in ("score", "absent")}
        comps[c]["score"] = new
    raw, det = rebuild_pillar(ce, "movement", pd, config)
    det["_planned_rest"] = {
        "days": days,
        "pre_rest_raw": pre_raw,
        "pre_rest_raw_unblended": pre_det.get("_raw_unblended"),
        "pre_rest_details": pre_det,
    }
    applied.append("planned_rest")
    return raw, det


def lab_aged_metabolic(ce: Any, stored_pd: dict, config: dict, eff: dict, applied: list) -> tuple:
    """Metabolic with lab ageing applied: when the raw recompute's lab score or evidence weight differs between the switch
    states, the stored lab score shifts by on - off and the component carries the "on" evidence weight; else verbatim."""
    off, on = eff.get("off") or {}, eff.get("on") or {}
    if (off.get("lab_score"), off.get("evidence_weight")) == (on.get("lab_score"), on.get("evidence_weight")):
        return stored_pd.get("raw_score"), copy.deepcopy(stored_pd.get("components") or {})
    pd = copy.deepcopy(stored_pd)
    comps = pd.setdefault("components", {})
    det = comps.get("lab_biomarkers") or {}
    stored_sc = None if det.get("absent") else det.get("score")
    comps["lab_biomarkers"] = dict(det, score=shifted(stored_sc, off.get("lab_score"), on.get("lab_score")))
    cfg = copy.deepcopy(config)
    lab_cfg = cfg["pillars"]["metabolic"]["components"].get("lab_biomarkers")
    if isinstance(lab_cfg, dict) and on.get("evidence_weight") is not None:
        lab_cfg["evidence_weight"] = on["evidence_weight"]
    applied.append("lab_ageing")
    return rebuild_pillar(ce, "metabolic", pd, cfg)


def histories(ce: Any, window: list, loader: str) -> dict:
    out: dict = {p: [] for p in PILLAR_ORDER}
    for w in window:
        for p in PILLAR_ORDER:
            pd = w.get(f"pillar_{p}") or {}
            raw = pd.get("raw_score")
            if loader == "legacy":
                out[p].append(float(raw) if raw is not None else LEGACY_FILL)
            elif raw is not None and not ce.day_is_held(pd):
                out[p].append(float(raw))
    return out


def engine_inputs(stored: dict, habit_scores: Optional[dict]) -> Optional[dict]:
    """The day's vice streaks as the compute saw them: only when the stored Mind scored vice control from a record."""
    comps = (stored.get("pillar_mind") or {}).get("components") or {}
    if (comps.get("vice_control") or {}).get("score") is None:
        return None
    return (habit_scores or {}).get("vice_streaks") or None


def replay(spec: dict, inputs: dict) -> dict:
    h = load_tree(spec)
    ce, cpub = h["ce"], h["cpub"]
    config = effective_config(h, inputs)
    stored: dict = inputs["sheets"]
    start, end = inputs["start"], inputs["end"]
    rebuild = tuple(spec.get("rebuild") or ())
    loader = spec.get("loader", "legacy")
    rel_mode = spec.get("relationships", "verbatim")
    replayed: dict = {}
    transitions: dict = {}  # the receipt is built from the in-memory record (full precision), as the compute builds it
    applied: dict = {}  # date -> the raw-input effects this step applied
    notes: list = []

    def view(d: str) -> Optional[dict]:
        return replayed.get(d) if d >= start else None  # pre-genesis rows are pilot-phase: invisible to the chain

    d = start
    while d <= end:
        s = stored.get(d)
        prev = next((v for v in (view(shift(d, -b)) for b in range(1, 8)) if v and v.get("character_level") is not None), None)
        if not s:
            notes.append({"date": d, "note": "no stored sheet: no row, the chain continues from the previous one"})
            d = shift(d, 1)
            continue
        if s.get("sick_day"):
            if prev:
                rec = {k: copy.deepcopy(v) for k, v in prev.items() if k != "progression_transitions"}
                rec["date"] = d
                rec["computed_at"] = s.get("computed_at")
                replayed[d] = rec
            notes.append({"date": d, "note": "sick day: the previous replayed record carried forward (the compute's freeze)"})
            d = shift(d, 1)
            continue
        window = [w for w in (view(shift(d, -b)) for b in range(21, 0, -1)) if w]
        effects = set(spec.get("effects") or ())
        eff = (inputs.get("raw_effects") or {}).get(d) or {}
        if s.get("engine_version") == ce.ENGINE_VERSION:
            eff = {}  # already computed by this method: the effects are in the stored values
        pre: dict = {}
        mods: dict = {}
        for p in PRIMARY:
            pd = s.get(f"pillar_{p}") or {}
            if p == "relationships":
                if rel_mode == "verbatim":
                    pre[p] = (pd.get("raw_score"), copy.deepcopy(pd.get("components") or {}))
                continue
            if p in rebuild and p == "movement" and "planned_rest" in effects and eff.get("movement"):
                pre[p] = planned_rest_movement(ce, pd, config, eff["movement"], applied.setdefault(d, []))
            elif p == "metabolic" and "lab_ageing" in effects and eff.get("metabolic"):
                pre[p] = lab_aged_metabolic(ce, pd, config, eff["metabolic"], applied.setdefault(d, []))
            elif p in rebuild:
                pre[p] = rebuild_pillar(ce, p, pd, config)
                kept = (pd.get("components") or {}).get("_planned_rest")
                if p == "movement" and isinstance(kept, dict):  # a row the final method wrote: its proration record stays
                    pre[p][1]["_planned_rest"] = copy.deepcopy(kept)
                mod = pd.get("raw_modifier")
                if isinstance(mod, dict) and mod.get("multiplier") not in (None, 1, 1.0):
                    mods[p] = {"multiplier": mod["multiplier"], "source": mod.get("source")}
            else:
                pre[p] = (pd.get("raw_score"), copy.deepcopy(pd.get("components") or {}))
        data: dict = {"date": d, "precomputed_pillars": pre}
        if mods:
            data["raw_score_modifiers"] = mods
        data.update(cpub.consistency_inputs((s.get("pillar_consistency") or {}).get("components"), window, d))
        comp = eff.get("completeness") or {}
        if "rest_day_completeness" in effects and comp.get("on") != comp.get("off"):
            data["data_completeness_pct"] = shifted(data.get("data_completeness_pct"), comp.get("off"), comp.get("on"))
            applied.setdefault(d, []).append("rest_day_completeness")
        data["engagement_state"] = copy.deepcopy((inputs.get("engagement") or {}).get(d))
        data["vice_streaks"] = engine_inputs(s, (inputs.get("habit_scores") or {}).get(d))
        if s.get("challenge_bonus_xp"):  # carried forward as stored: consumed challenge XP is never recomputed away
            data["challenge_bonus_xp"] = copy.deepcopy(s["challenge_bonus_xp"])
        rec = ce.compute_character_sheet(data, prev, histories(ce, window, loader), config)
        rec["computed_at"] = s.get("computed_at")  # the original timestamp; the recompute stamps its own provenance
        transitions[d] = json.loads(json.dumps(rec.get("progression_transitions"), default=float))
        # The next day reads this one back from DynamoDB at the store's precision (store_character_sheet: 4 places),
        # exactly as the nightly compute's load_previous_state does — never the in-memory floats.
        replayed[d] = as_stored(strip_transitions(rec))
        d = shift(d, 1)

    meta = {
        "engine_version": ce.ENGINE_VERSION,
        "config_version": (h["config"].get("_meta") or {}).get("version"),
        "uninstrumented_pillars": list(getattr(ce, "UNINSTRUMENTED_PILLARS", ())),
    }
    applied = {d: v for d, v in applied.items() if v}
    if spec.get("emit") != "items":
        return {"meta": meta, "notes": notes, "effects_applied": applied, "records": {k: strip_transitions(v) for k, v in replayed.items()}}
    return {"meta": meta, "notes": notes, "effects_applied": applied, **emit_items(ce, config, replayed, transitions, inputs)}


def strip_transitions(rec: dict) -> dict:
    return {k: v for k, v in rec.items() if k not in ("progression_transitions", "public_progression_transitions")}


def as_stored(rec: dict) -> dict:
    """``rec`` as it reads back after the store's DynamoDB round trip (floats_to_decimal at 4 places, then d2f)."""
    from common.numeric import decimals_to_float, floats_to_decimal

    return decimals_to_float(floats_to_decimal(json.loads(json.dumps(rec, default=float)), precision=4))


def emit_items(ce: Any, config: dict, replayed: dict, transitions: dict, inputs: dict) -> dict:
    """The planned engine-owned attributes of every sheet item, exactly as ``store_character_sheet`` converts them
    (precision 4), and the planned receipts exactly as ``store_receipt`` converts them (full precision) — typed JSON."""
    from common.numeric import floats_to_decimal
    from health import progression_receipts as pr

    sheets, receipts = {}, {}
    for d, rec in sorted(replayed.items()):
        body = {k: v for k, v in rec.items() if k not in getattr(ce, "_UNSTORED_KEYS", ("progression_transitions",))}
        sheets[d] = to_typed(floats_to_decimal(body, precision=4))
        stored_r = (inputs.get("receipts") or {}).get(d)
        if stored_r is None or not transitions.get(d):
            continue
        receipt = pr.build_receipt(dict(rec, progression_transitions=transitions[d]), config, input_rows=stored_r.get("input_rows"))
        if receipt is None:
            continue
        receipt["computed_at"] = stored_r.get("computed_at")
        receipt["replay_verified"] = bool(pr.replay(receipt, config).get("verified"))
        receipts[d] = to_typed(floats_to_decimal(pr._norm(receipt)))
    return {"sheet_attrs": sheets, "receipt_attrs": receipts, "config_hash": pr.config_hash(config)}


def to_typed(obj: Any) -> Any:
    """A Decimal-carrying structure as JSON: a Decimal becomes {"$N": "<its canonical number string>"}."""
    from decimal import Decimal

    if isinstance(obj, bool) or obj is None:
        return obj
    if isinstance(obj, Decimal):
        return {"$N": canon_number(obj)}
    if isinstance(obj, int):  # an int is a DynamoDB number too (floats_to_decimal passes ints through)
        return {"$N": str(obj)}
    if isinstance(obj, float):
        raise TypeError("a float survived floats_to_decimal")
    if isinstance(obj, dict):
        return {k: to_typed(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_typed(v) for v in obj]
    return obj


def canon_number(d: Any) -> str:
    """A number as DynamoDB stores it: 80, 80.0 and 8E+1 are one number (trailing zeros and the exponent go)."""
    s = format(d.normalize(), "f")
    return "0" if s in ("-0", "0") else s


def main(argv: list) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--spec", required=True)
    ap.add_argument("--inputs", required=True)
    ap.add_argument("--result", required=True)
    args = ap.parse_args(argv)
    with open(args.spec, encoding="utf-8") as fh:
        spec = json.load(fh)
    with open(args.inputs, encoding="utf-8") as fh:
        inputs = json.load(fh)
    out = replay(spec, inputs)
    with open(args.result, "w", encoding="utf-8") as fh:
        json.dump(out, fh, sort_keys=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
