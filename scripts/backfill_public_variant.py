#!/usr/bin/env python3
"""scripts/backfill_public_variant.py — recompute the PUBLIC variant of every stored character sheet, progression
receipt and day grade from the experiment's genesis (owner ruling 2026-11-05).

THE RULING. "Recompute affected historical public values using the corrected methodology. Preserve the original method
1 scores privately, with original timestamps and a complete correction trail ... show the affected-date and
before/after manifest, plus dry-run and rollback evidence, before production writes."

WHAT IT DOES. It replays the public method (``health.character_public`` / ``health.day_grade_public``) over the STORED
inputs, oldest first, so the public state chain (EMA, levels, XP, streaks, buffers, the headline level) is built from
public inputs only and never from a method-1 state:

  * character_sheet  — per date, the method-1 record's public-eligible pillars and component scores feed the engine's
                       own chain (``compute_character_sheet`` with precomputed pillars), from the previous date's
                       PUBLIC variant. A sick-day record copies the previous public variant, as the live compute
                       copies the previous record. The method-1 chain is replayed the same way as a FIDELITY CONTROL:
                       a date whose method-1 replay does not reproduce the stored method-1 values is reported.
  * character_receipt — the public variant's own receipt (digest + self-replay against the public config).
  * day_grade        — the stored components without the journal, renormalised; a tier-weighted (pre-core-set)
                       day's habits component re-scored over public habits by the scorer, after a fidelity check
                       that the same replay over ALL habits reproduces the stored method-1 habits score.

It writes ONLY the ``public`` attribute of each existing item (never a method-1 field, never a new item).

RUN:
  python3 scripts/backfill_public_variant.py --out DIR                  # DRY RUN (default): read-only; the manifest
  python3 scripts/backfill_public_variant.py --out DIR --apply          # writes the export (pre-image) FIRST, then
                                                                        #   SETs `public` on each planned item
  python3 scripts/backfill_public_variant.py --rollback EXPORT.json     # restore DRY RUN: what would be restored
  python3 scripts/backfill_public_variant.py --rollback EXPORT.json --apply   # restores exactly the pre-image

--apply is a DynamoDB WRITE — an owner act, refused unless passed explicitly. The dry run reads DynamoDB and the S3
engine config only.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
from datetime import date, timedelta
from typing import Any, Callable, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from common.constants import EXPERIMENT_PHASE_CURRENT, EXPERIMENT_START_DATE  # noqa: E402,F401 — the CLI reads B.EXPERIMENT_START_DATE
from common.numeric import decimals_to_float, floats_to_decimal  # noqa: E402
from health import character_engine, character_privacy, character_public, day_grade_public, scoring_engine  # noqa: E402

USER = os.environ["USER_ID"]
PFX = f"USER#{USER}#SOURCE#"
PUBLIC = character_privacy.PUBLIC_KEY
SHEET_PK, RECEIPT_PK, GRADE_PK = PFX + "character_sheet", PFX + "character_receipt", PFX + "day_grade"
EXPORT_VERSION = "public-variant-export-v1"
CHAIN_FIELDS = ("level", "level_score", "raw_score", "xp_total", "xp_debt", "xp_buffer", "streak_above", "streak_below", "tier")


# ── small pure helpers ─────────────────────────────────────────────────────────────────────


def day_of(item: dict) -> str:
    return str(item.get("date") or str(item.get("sk", "")).replace("DATE#", ""))[:10]


def visible(item: Any) -> bool:
    """The lambda's fetch semantics: no tombstone, and the current phase or no phase (ADR-058)."""
    return isinstance(item, dict) and not item.get("tombstone") and item.get("phase", EXPERIMENT_PHASE_CURRENT) == EXPERIMENT_PHASE_CURRENT


def as_stored(obj: Any, precision: Optional[int] = 4) -> Any:
    """``obj`` exactly as it reads back after a DynamoDB round trip at the store's precision."""
    return decimals_to_float(floats_to_decimal(obj, precision=precision))


def shift(d: str, days: int) -> str:
    return (date.fromisoformat(d) + timedelta(days=days)).isoformat()


def previous_record(records: dict, d: str) -> Optional[dict]:
    """``load_previous_state``: the most recent record 1..7 days back that carries a character level."""
    for back in range(1, 8):
        rec = records.get(shift(d, -back))
        if rec and rec.get("character_level") is not None:
            return rec
    return None


def window_records(records: dict, d: str, window: int = 21) -> list:
    """``load_raw_score_histories``' records: every stored date in [d - window, d - 1], oldest first."""
    lo, hi = shift(d, -window), shift(d, -1)
    return [records[k] for k in sorted(records) if lo <= k <= hi]


def raw_histories(recs: list) -> dict:
    return character_public.public_histories(recs)


def item_digest(item: dict, exclude: tuple = (PUBLIC,)) -> str:
    """sha256 over an item's canonical JSON, the ``public`` attribute excluded: the method-1 fields' fingerprint."""
    body = {k: v for k, v in (item or {}).items() if k not in exclude}
    return hashlib.sha256(json.dumps(decimals_to_float(body), sort_keys=True, default=str).encode()).hexdigest()


# ── the character replay ───────────────────────────────────────────────────────────────────


def _engine_inputs(m1: dict, habit_scores: dict) -> tuple:
    """(habit_method, vice_streaks) as the day's compute saw them: the stored Mind details say whether the habit score
    existed then (an absent t1 = no habit_scores record at compute time); when it did, its stored record names the
    method and the vice streaks."""
    comps = (m1.get("pillar_mind") or {}).get("components") or {}
    hs = habit_scores.get(day_of(m1)) or {}
    t1 = comps.get("t1_habit_compliance") or {}
    habit_method = hs.get("scoring_method") if (t1 and not t1.get("absent")) else None
    vice = hs.get("vice_streaks") if (comps.get("vice_control") or {}).get("score") is not None else None
    return habit_method, vice


def method1_replay(m1: dict, records: dict, engagement: dict, habit_scores: dict, config: dict) -> list:
    """FIDELITY CONTROL: the stored method-1 pillars through the same chain from the stored method-1 state. Returns
    the fields where the replay does not reproduce the stored record ([] = the replay machinery is faithful)."""
    d = day_of(m1)
    pre = {
        p: ((m1.get(f"pillar_{p}") or {}).get("raw_score"), (m1.get(f"pillar_{p}") or {}).get("components") or {})
        for p in character_public.PILLARS
    }
    _hm, vice = _engine_inputs(m1, habit_scores)
    data = {"date": d, "precomputed_pillars": pre, "engagement_state": engagement.get(d), "vice_streaks": vice}
    if m1.get("challenge_bonus_xp"):
        data["challenge_bonus_xp"] = dict(m1["challenge_bonus_xp"])
    out = character_engine.compute_character_sheet(data, previous_record(records, d), raw_histories(window_records(records, d)), config)
    out = as_stored({k: v for k, v in out.items() if k != "progression_transitions"})
    diffs = []
    for key in ("character_level", "character_xp", "character_xp_debt", "character_mood"):
        if out.get(key) != m1.get(key):
            diffs.append({"field": key, "stored": m1.get(key), "replayed": out.get(key)})
    for p in character_public.PILLARS:
        a, b = m1.get(f"pillar_{p}") or {}, out.get(f"pillar_{p}") or {}
        diffs += [{"field": f"{p}.{f}", "stored": a.get(f), "replayed": b.get(f)} for f in CHAIN_FIELDS if a.get(f) != b.get(f)]
    return diffs


def replay_character(records: dict, engagement: dict, habit_scores: dict, config: dict, run_ts: str) -> dict:
    """{date: {"public": block-as-stored, "transitions": ..., "presence": ..., "fidelity": [...]}} oldest first.

    ``records`` holds every VISIBLE stored method-1 record by date (floats). The public chain lives in its own map: a
    date's previous state and history are the PUBLIC views of the same records method 1's chain read."""
    public_records: dict[str, dict] = {}  # date -> a stored-shape record carrying only the public block
    out: dict[str, dict] = {}
    for d in sorted(records):
        m1 = records[d]
        if m1.get("sick_day"):
            prev = previous_record(records, d)
            block = copy.deepcopy((public_records.get(day_of(prev)) or {}).get(PUBLIC)) if prev else None
            if block is not None:
                public_records[d] = {"date": d, "sk": f"DATE#{d}", "character_level": block.get("character_level"), PUBLIC: block}
            out[d] = {
                "public": block,
                "transitions": None,
                "presence": None,
                "fidelity": [],
                "sick_day_frozen_from": day_of(prev) if prev else None,
            }
            continue
        prev = previous_record(records, d)
        prev_public = character_privacy.public_view(public_records.get(day_of(prev))) if prev else None
        hist = [character_privacy.public_view(public_records.get(day_of(r))) for r in window_records(records, d)]
        presence, exact, why = character_public.public_presence(engagement.get(d))
        habit_method, vice = _engine_inputs(m1, habit_scores)
        block, transitions = character_public.compute_public_variant(
            m1,
            prev_public,
            [h for h in hist if h],
            config,
            engagement=presence,
            habit_method=habit_method,
            vice_streaks=vice,
            origin="recomputed",
            computed_at=run_ts,
        )
        block = as_stored(block)
        public_records[d] = {"date": d, "sk": f"DATE#{d}", "character_level": block.get("character_level"), PUBLIC: block}
        out[d] = {
            "public": block,
            "transitions": transitions,
            "presence": {"exact": exact, "reason": why, "class": (presence or {}).get("presence_class")},
            "fidelity": method1_replay(m1, records, engagement, habit_scores, config),
            "chain_gaps": len(hist) - len([h for h in hist if h]),
        }
    return out


# ── the day-grade replay ───────────────────────────────────────────────────────────────────


def grade_components(item: dict) -> dict:
    return {k[len("component_") :]: v for k, v in item.items() if k.startswith("component_")}


TIER_ERA_POLICIES = ("hold_out", "replay")  # see replay_day_grade; the owner picks (default: hold_out)


def replay_day_grade(
    item: dict, composite_method: Optional[str], habit_inputs: Optional[dict], profile: dict, run_ts: str, tier_era_policy: str = "hold_out"
) -> dict:
    """{"public": block, "habits": {...}, "notes": [...]} for one stored day_grade record.

    ``composite_method`` is the day's habits composite method (computed_metrics.component_details.habits_mvp);
    ``habit_inputs`` the scorer's inputs for a tier-weighted day ({date, habitify, habitify_7d, strava}).

    A TIER-WEIGHTED day (before the core twelve were armed) scored every active habit, the two journal habits
    among them. Its habits component cannot be re-scored exactly from what is stored: the registry has changed since
    (renames, retired supplements, re-tiering) and so has some Habitify data, so a replay over ALL habits with today's
    registry reproduces the stored method-1 score on only some days (``fidelity``). Two policies, both invariant to
    private inputs: ``hold_out`` (default) leaves the habits component out of that day's public grade (the mean
    renormalises); ``replay`` takes today's-registry replay over public habits. Both values are always reported."""
    comps = grade_components(item)
    weights = item.get("weights_snapshot") or profile.get("day_grade_weights") or {}
    notes, habits = [], {"method": composite_method, "stored": comps.get("habits_mvp"), "public": comps.get("habits_mvp"), "policy": None}
    if comps.get("habits_mvp") is not None and composite_method != "core_set":
        habits.update({"policy": tier_era_policy, "public": None, "public_replay": None})
        if habit_inputs and habit_inputs.get("habitify"):
            # Re-scored unarmed (no `core` flag), as the day was scored.
            reg = {n: {k: v for k, v in (m or {}).items() if k != "core"} for n, m in (profile.get("habit_registry") or {}).items()}
            tier_era = dict(profile, habit_registry=reg)
            full, _ = scoring_engine.score_habits_registry(habit_inputs, tier_era)
            pub, _ = scoring_engine.score_habits_registry(habit_inputs, day_grade_public.public_profile(tier_era, habit_inputs["habitify"]))
            habits.update({"replayed_full": full, "public_replay": pub, "fidelity": full == comps.get("habits_mvp")})
        if tier_era_policy == "replay":
            habits["public"] = habits["public_replay"]
            notes.append("tier-weighted day: habits re-scored over public habits with today's registry")
        else:
            notes.append("tier-weighted day: habits held out (its share counted private habits and is not exactly re-scorable)")
    pcomps = dict(comps, habits_mvp=habits["public"])
    score, letter = day_grade_public.total_from_components(pcomps, weights)
    if habits["policy"]:  # the other policy's grade, for the owner's choice
        other = habits["public_replay"] if tier_era_policy == "hold_out" else None
        habits["day_grade_other_policy"] = day_grade_public.total_from_components(dict(comps, habits_mvp=other), weights)
    block = day_grade_public.block(score, letter, pcomps, weights, origin="recomputed", notes=notes)
    block["computed_at"] = run_ts
    return {"public": as_stored(block), "habits": habits, "notes": notes}


# ── the plan, the export, the writes ──────────────────────────────────────────────────────


def plan_writes(char: dict, grades: dict, receipts_present: set, receipt_blocks: dict) -> list:
    """Every write the apply would make: ``{pk, sk, value, precision}`` — one SET of the ``public`` attribute each."""
    plan = []
    for d, r in sorted(char.items()):
        if r.get("public") is not None:
            plan.append({"pk": SHEET_PK, "sk": f"DATE#{d}", "value": r["public"], "precision": 4})
        if d in receipts_present and receipt_blocks.get(d) is not None:
            plan.append({"pk": RECEIPT_PK, "sk": f"DATE#{d}", "value": receipt_blocks[d], "precision": None})
    for d, g in sorted(grades.items()):
        plan.append({"pk": GRADE_PK, "sk": f"DATE#{d}", "value": g["public"], "precision": 4})
    return plan


_VOLATILE = ("computed_at", "origin")  # differ between runs by construction, never by method


def differs_from_stored(plan: list, stored: dict) -> dict:
    """{"items_with_public": n, "differing": [...keys]} — the planned values against a public variant already stored
    (stamps that move every run excluded). After an apply, a re-run of the dry run must list nothing here."""

    def norm(v):
        v = as_stored(decimals_to_float(v), precision=None) if v is not None else None
        return json.dumps({k: x for k, x in (v or {}).items() if k not in _VOLATILE}, sort_keys=True, default=str)

    have = [(w, stored.get((w["pk"], w["sk"])) or {}) for w in plan]
    have = [(w, item) for w, item in have if PUBLIC in item]
    differing = [
        f"{w['pk'].split('#SOURCE#')[-1]} {w['sk']}"
        for w, item in have
        if norm(item[PUBLIC]) != norm(as_stored(w["value"], w["precision"]))
    ]
    return {"items_with_public": len(have), "differing": differing}


def build_export(get_item: Callable[[dict], Optional[dict]], plan: list, run_ts: str) -> dict:
    """The pre-image of exactly what the apply touches: per item, whether it had a ``public`` attribute, that value,
    and a fingerprint of its method-1 fields (the rollback and the post-apply check both verify it)."""
    entries = []
    for w in plan:
        item = get_item({"pk": w["pk"], "sk": w["sk"]})
        if item is None:
            raise RuntimeError(f"planned item {w['pk']} / {w['sk']} does not exist — refusing (the backfill never creates items)")
        entries.append(
            {
                "pk": w["pk"],
                "sk": w["sk"],
                "had_public": PUBLIC in item,
                "previous_public": decimals_to_float(item.get(PUBLIC)) if PUBLIC in item else None,
                "method1_digest": item_digest(item),
            }
        )
    return {"export_version": EXPORT_VERSION, "taken_at": run_ts, "attribute": PUBLIC, "entries": entries}


def apply_plan(table: Any, plan: list, export: dict) -> dict:
    """SET ``public`` on each planned item — conditional on the item existing and its method-1 fingerprint matching the
    export (an item that changed since the export is skipped and reported, never written)."""
    by_key = {(e["pk"], e["sk"]): e for e in export["entries"]}
    done, skipped = 0, []
    for w in plan:
        e = by_key[(w["pk"], w["sk"])]
        item = (table.get_item(Key={"pk": w["pk"], "sk": w["sk"]}) or {}).get("Item")
        if item is None or item_digest(item) != e["method1_digest"]:
            skipped.append({"pk": w["pk"], "sk": w["sk"], "reason": "item missing or its method-1 fields changed since the export"})
            continue
        table.update_item(
            Key={"pk": w["pk"], "sk": w["sk"]},
            UpdateExpression="SET #p = :p",
            ConditionExpression="attribute_exists(pk)",
            ExpressionAttributeNames={"#p": PUBLIC},
            ExpressionAttributeValues={":p": floats_to_decimal(w["value"], precision=w["precision"])},
        )
        done += 1
    return {"written": done, "skipped": skipped}


def rollback(table: Any, export: dict, *, apply: bool) -> dict:
    """Restore exactly the export's pre-image of the ``public`` attribute: REMOVE it where the item had none, SET the
    previous value where it had one. Refuses an item whose method-1 fields no longer match the export. Dry run unless
    ``apply``."""
    if export.get("export_version") != EXPORT_VERSION or export.get("attribute") != PUBLIC:
        raise RuntimeError("not a public-variant export")
    ops, refused = [], []
    for e in export["entries"]:
        item = (table.get_item(Key={"pk": e["pk"], "sk": e["sk"]}) or {}).get("Item")
        if item is None or item_digest(item) != e["method1_digest"]:
            refused.append({"pk": e["pk"], "sk": e["sk"], "reason": "item missing or its method-1 fields changed since the export"})
            continue
        op = {"pk": e["pk"], "sk": e["sk"], "op": "SET" if e["had_public"] else "REMOVE", "present_now": PUBLIC in item}
        ops.append(op)
        if not apply:
            continue
        if e["had_public"]:
            table.update_item(
                Key={"pk": e["pk"], "sk": e["sk"]},
                UpdateExpression="SET #p = :p",
                ExpressionAttributeNames={"#p": PUBLIC},
                ExpressionAttributeValues={":p": floats_to_decimal(e["previous_public"])},
            )
        else:
            table.update_item(Key={"pk": e["pk"], "sk": e["sk"]}, UpdateExpression="REMOVE #p", ExpressionAttributeNames={"#p": PUBLIC})
    return {"applied": apply, "operations": ops, "refused": refused}


if __name__ == "__main__":  # pragma: no cover — the CLI lives in backfill_public_variant_cli
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    from backfill_public_variant_cli import main

    sys.exit(main(sys.argv[1:]))
