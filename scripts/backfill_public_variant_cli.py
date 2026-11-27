#!/usr/bin/env python3
"""scripts/backfill_public_variant_cli.py — the I/O half of ``backfill_public_variant.py`` (owner ruling 2026-11-05).

Loads the stored inputs (read-only), runs the replays, writes the manifest; ``--apply`` / ``--rollback`` are the only
writing paths, each refused unless passed explicitly. The pure replay logic is ``backfill_public_variant``.
"""

from __future__ import annotations

import argparse
import copy
import csv
import json
import os
import statistics
import sys
from datetime import date, datetime, timezone
from typing import Any, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backfill_public_variant as B  # noqa: E402
import backfill_public_variant_report as R  # noqa: E402
from common.numeric import decimals_to_float  # noqa: E402
from health import character_privacy, character_public  # noqa: E402

ROUTE_PILLARS = ("sleep", "movement", "nutrition", "metabolic", "mind", "relationships", "consistency")
VERBATIM_CHECK = ("raw_score", "level", "level_score", "xp_total", "xp_debt", "xp_buffer", "streak_above", "streak_below", "tier")


# ── reads ──────────────────────────────────────────────────────────────────────────────────


def query_all(table, pk: str, lo: str = "DATE#0000", hi: str = "DATE#9999") -> list:
    from boto3.dynamodb.conditions import Key

    out, kw = [], {"KeyConditionExpression": Key("pk").eq(pk) & Key("sk").between(lo, hi)}
    while True:
        resp = table.query(**kw)
        out += resp.get("Items", [])
        if "LastEvaluatedKey" not in resp:
            return out
        kw["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def _dated(items: list, keep=lambda i: True) -> dict:
    return {B.day_of(i): decimals_to_float(i) for i in items if keep(i) and "#" not in str(i.get("sk", ""))[5:]}


def load_snapshot(table, to: str) -> dict:
    """Every stored input the replay reads, by date — the same partitions the two computes read."""
    hi = f"DATE#{to}~"
    genesis = B.EXPERIMENT_START_DATE
    snap = {
        "sheets": _dated(query_all(table, B.SHEET_PK, hi=hi), B.visible),
        "receipts": _dated(query_all(table, B.RECEIPT_PK, hi=hi), B.visible),
        "grades": {d: v for d, v in _dated(query_all(table, B.GRADE_PK, hi=hi)).items() if d >= genesis},
        "engagement": _dated(query_all(table, B.PFX + "engagement_state", hi=hi), B.visible),
        "habit_scores": _dated(query_all(table, B.PFX + "habit_scores", hi=hi)),
        "computed": _dated(query_all(table, B.PFX + "computed_metrics", f"DATE#{genesis}", hi)),
        "habitify": _dated(query_all(table, B.PFX + "habitify", f"DATE#{B.shift(genesis, -7)}", hi)),
        "strava": _dated(query_all(table, B.PFX + "strava", f"DATE#{genesis}", hi)),
    }
    snap["profile"] = decimals_to_float(table.get_item(Key={"pk": f"USER#{B.USER}", "sk": "PROFILE#v1"}).get("Item") or {})
    return snap


def load_config(table, s3) -> dict:
    """The effective engine config, built exactly as the compute builds it (S3 config + baselines + effect fit)."""
    from experiment import effect_fitter
    from health import character_engine, personal_baselines

    cfg = character_engine.load_character_config(s3, os.environ["S3_BUCKET"], force_refresh=True)
    cfg = personal_baselines.effective_character_config(cfg, table, B.PFX)
    effect_fitter.merge_fit_into_config(cfg, effect_fitter.load_latest_fit(table, B.USER))
    return cfg


# ── the replays over a snapshot ───────────────────────────────────────────────────────────


def habit_inputs(snap: dict, d: str) -> dict:
    """The scorer's inputs as the day's compute assembled them (window anchored at the morning after, #4637)."""
    anchor = B.shift(d, 1)
    days = [snap["habitify"][k] for k in sorted(snap["habitify"]) if B.shift(anchor, -7) <= k <= d]
    return {"date": d, "habitify": snap["habitify"].get(d), "habitify_7d": days, "strava": snap["strava"].get(d)}


def composite_method(snap: dict, d: str) -> Optional[str]:
    hm = ((snap["computed"].get(d) or {}).get("component_details") or {}).get("habits_mvp") or {}
    return hm.get("composite_method")


def run_replays(snap: dict, config: dict, run_ts: str, order_fix: bool = True) -> tuple:
    """#6224: ``order_fix=False`` is the PRIVACY-ONLY recompute — the stored habit inputs as the compute saw them, no
    timing ("order") correction — so the owner can approve the privacy change on its own."""
    char = B.replay_character(snap["sheets"], snap["engagement"], snap["habit_scores"], config, run_ts, order_fix=order_fix)
    receipts = {}
    for d, r in char.items():
        if r.get("transitions") and d in snap["receipts"]:
            rec_like = {"date": d, B.PUBLIC: r["public"], "public_progression_transitions": r["transitions"]}
            receipts[d] = character_public.public_receipt(rec_like, config, snap["receipts"][d].get("input_rows"))
    grades = {}
    for d, item in sorted(snap["grades"].items()):
        cm = composite_method(snap, d)
        hi = habit_inputs(snap, d) if cm != "core_set" else None
        grades[d] = B.replay_day_grade(item, cm, hi, snap["profile"], run_ts, tier_era_policy=B.day_grade_public.TIER_WEIGHTED_HABITS)
    return char, receipts, grades


# ── the manifest ──────────────────────────────────────────────────────────────────────────


def served_today(stored: dict) -> Optional[dict]:
    """#6224: what readers are served from a record TODAY, before the recompute — the stored ``public`` block (the
    variant every public route reads), with the private-source pillar held, exactly as the deployed routes serve it. Its
    Mind is the stored one: the code that serves Mind as not scored is the change this run's "after" side shows. None
    when the record carries no servable public variant (no route serves anything for it)."""
    view = character_privacy.public_view(stored)
    if view is None:
        return None
    for name in character_privacy.PRIVATE_SOURCE_PILLARS:
        if f"pillar_{name}" in view:
            view[f"pillar_{name}"] = character_privacy.public_pillar(name, view[f"pillar_{name}"])
    return view


def served_view(stored: dict, public_block: Optional[dict]) -> Optional[dict]:
    """What /api/character serves from a record: TODAY's serving (``public_block`` None: the stored public block,
    ``served_today``) or the serving after the recompute (the recomputed public variant through ``public_sheet``)."""
    if public_block is None:
        return served_today(stored)
    # after a verified recompute the owner flips PUBLIC_CHARACTER_SCORES_PENDING_RECOMPUTE off: the "after" is that serving
    return character_privacy.public_sheet(dict(stored, **{B.PUBLIC: public_block}), pending=False)


def route_composite(view: Optional[dict]) -> Optional[float]:
    """/api/character's composite_score: the mean raw over the pillars that are not not-instrumented."""
    if not view:
        return None
    raws = [
        float((view.get(f"pillar_{p}") or {}).get("raw_score", 0))
        for p in ROUTE_PILLARS
        if not (view.get(f"pillar_{p}") or {}).get("not_instrumented")
    ]
    return round(sum(raws) / len(raws), 1) if raws else None


def _num(x):
    return None if x is None else round(float(x), 4)


def _pv(view: Optional[dict], *path):
    node: Any = view or {}
    for k in path:
        node = node.get(k) if isinstance(node, dict) else None
    return node


def character_rows(snap: dict, char: dict) -> list:
    """Per date, every value a reader sees, BEFORE (``served_today``: the stored public block the routes serve now) and
    AFTER (the recomputed public variant as ``public_sheet`` serves it) — #6224: the owner approves the exact public
    change. ``method1`` keeps the private method-1 values for the private correction trail (``R.ledger_rows``)."""
    rows = []
    for d in sorted(char):
        m1 = snap["sheets"][d]
        pub = char[d]["public"]
        cur, new = served_view(m1, None), served_view(m1, pub) if pub else None
        unchanged = all(
            (m1.get(f"pillar_{p}") or {}).get(f) == ((pub or {}).get(f"pillar_{p}") or {}).get(f)
            for p in character_public.VERBATIM_PILLARS
            for f in VERBATIM_CHECK
        )
        row: dict[str, Any] = {
            "date": d,
            "before_basis": "stored public block (served today)" if cur else "no public variant stored (nothing served)",
            "character_level": [_num(_pv(cur, "character_level")), _num(_pv(new, "character_level"))],
            "character_tier": [_pv(cur, "character_tier"), _pv(new, "character_tier")],
            "character_xp": [_num(_pv(cur, "character_xp")), _num(_pv(new, "character_xp"))],
            "character_xp_debt": [_num(_pv(cur, "character_xp_debt")), _num(_pv(new, "character_xp_debt"))],
            "composite": [route_composite(cur), route_composite(new)],
            "character_mood": [_pv(cur, "character_mood"), _pv(new, "character_mood")],
            "level_events": [_events(cur or {}), _events(new or {})],
        }
        for p in ROUTE_PILLARS:
            row[f"{p}_level"] = [_num(_pv(cur, f"pillar_{p}", "level")), _num(_pv(new, f"pillar_{p}", "level"))]
            row[f"{p}_score"] = [_num(_pv(cur, f"pillar_{p}", "raw_score")), _num(_pv(new, f"pillar_{p}", "raw_score"))]
        row["level_changed"] = row["character_level"][0] != row["character_level"][1]
        mp, pp = m1.get("pillar_mind") or {}, (pub or {}).get("pillar_mind") or {}
        held = dict(m1)
        for name in character_privacy.PRIVATE_SOURCE_PILLARS:
            if f"pillar_{name}" in held:
                held[f"pillar_{name}"] = character_privacy.public_pillar(name, held[f"pillar_{name}"])
        row["method1"] = {  # private trail: method 1 -> the recomputed public value
            "mind_raw": [_num(mp.get("raw_score")), _num(pp.get("raw_score"))],
            "mind_level": [_num(mp.get("level")), _num(pp.get("level"))],
            "composite": [route_composite(held), route_composite(new)],
            "character_xp": [_num(m1.get("character_xp")), _num((pub or {}).get("character_xp"))],
            "character_level": [_num(m1.get("character_level")), _num((pub or {}).get("character_level"))],
            "consistency_level": [
                _num((m1.get("pillar_consistency") or {}).get("level")),
                _num(((pub or {}).get("pillar_consistency") or {}).get("level")),
            ],
        }
        row.update(
            {
                "verbatim_pillars_unchanged": unchanged,
                "presence": char[d].get("presence"),
                "method1_replay_mismatches": char[d].get("fidelity"),
                "sick_day_frozen_from": char[d].get("sick_day_frozen_from"),
                "order_fix": char[d].get("order_fix"),
            }
        )
        changed = any(_changed(row[f]) for f in ("character_level", "character_xp", "mind_level", "consistency_level"))
        row["reasons"] = R.character_reasons(m1, pub, char[d].get("order_fix"), changed)
        rows.append(row)
    return rows


def _events(rec: dict) -> list:
    return [
        f"{e.get('pillar') or 'character'}:{e.get('type')}:{e.get('old_level')}->{e.get('new_level')}"
        for e in rec.get("level_events") or []
    ]


def grade_rows(snap: dict, grades: dict) -> list:
    rows = []
    for d, g in sorted(grades.items()):
        item, pub = snap["grades"][d], g["public"]
        rows.append(
            {
                "date": d,
                "day_grade": [_num(item.get("total_score")), _num(pub.get("total_score"))],
                "letter": [item.get("letter_grade"), pub.get("letter_grade")],
                "journal_component": _num(item.get("component_journal")),
                "habits_mvp": [_num(g["habits"].get("stored")), _num(g["habits"].get("public"))],
                "habits_method": g["habits"].get("method"),
                "habits_policy": g["habits"].get("policy"),
                "habits_public_if_replay": _num(g["habits"].get("public_replay")),
                "day_grade_other_policy": (
                    list(g["habits"]["day_grade_other_policy"]) if g["habits"].get("day_grade_other_policy") else None
                ),
                "habits_replay_fidelity": g["habits"].get("fidelity"),
                "recap_card_letter": [
                    (snap["computed"].get(d) or {}).get("day_grade_letter"),
                    pub.get("letter_grade") if pub.get("total_score") is not None else None,
                ],
                "notes": g["notes"],
                "reasons": R.grade_reasons(item, g["habits"]),
            }
        )
    return rows


# ── #6224: the owner's review — privacy vs timing, levels, badges, the one-page summary ─────────────────────────────


def _num_norm(x: Any) -> Any:
    if isinstance(x, bool) or x is None:
        return x
    if isinstance(x, (int, float)):
        return round(float(x), 4)
    if isinstance(x, dict):
        return {k: _num_norm(v) for k, v in x.items() if k not in ("computed_at", "origin", "basis")}
    if isinstance(x, list):
        return [_num_norm(v) for v in x]
    return x


def same_public(stored_public: Any, planned: Any) -> bool:
    """A planned ``public`` value equal to the stored one, numerically (int/float formatting and the run stamps aside)."""
    return json.dumps(_num_norm(decimals_to_float(stored_public)), sort_keys=True, default=str) == json.dumps(
        _num_norm(planned), sort_keys=True, default=str
    )


def narrow_plan(plan: list, stored: dict) -> tuple:
    """(writes, skipped): F(8) — a planned write whose value equals the stored public projection is not made (it would
    only re-stamp ``origin``/``computed_at``). Nothing canonical is ever in the plan: only ``public`` attributes."""
    keep, skipped = [], []
    for w in plan:
        item = stored.get((w["pk"], w["sk"])) or {}
        if B.PUBLIC in item and same_public(item[B.PUBLIC], w["value"]):
            skipped.append(f"{w['pk'].split('#SOURCE#')[-1]} {w['sk']}")
        else:
            keep.append(w)
    return keep, skipped


def privacy_vs_timing(snap: dict, privacy_only: dict, full: dict) -> dict:
    """Per date, the public values BEFORE (served today), after the PRIVACY-ONLY recompute, and after the FULL one
    (privacy + the timing fix): the two changes reported apart, so each can be approved or declined on its own."""
    rows, timing_dates = [], []
    for d in sorted(full):
        cur = served_today(snap["sheets"][d])
        p = served_view(snap["sheets"][d], privacy_only[d]["public"]) if privacy_only.get(d, {}).get("public") else None
        f = served_view(snap["sheets"][d], full[d]["public"]) if full[d].get("public") else None
        row = {"date": d}
        for key, path in (("level", ("character_level",)), ("xp", ("character_xp",)), ("xp_debt", ("character_xp_debt",))):
            row[key] = [_num(_pv(cur, *path)), _num(_pv(p, *path)), _num(_pv(f, *path))]
        row["composite"] = [route_composite(cur), route_composite(p), route_composite(f)]
        row["privacy_changed"] = any(row[k][0] != row[k][1] for k in ("level", "xp", "xp_debt", "composite"))
        row["timing_changed"] = any(row[k][1] != row[k][2] for k in ("level", "xp", "xp_debt", "composite"))
        if row["timing_changed"]:
            timing_dates.append(d)
        rows.append(row)
    return {
        "columns": ["served today", "privacy-only recompute", "privacy + timing fix"],
        "rows": rows,
        "privacy_changed_dates": [r["date"] for r in rows if r["privacy_changed"]],
        "timing_changed_dates": timing_dates,
    }


def level_credit_changes(snap: dict, char: dict) -> dict:
    """F(4) + the owner's 2026-11-26 correction: the EVENT COMPARISON (``backfill_public_variant_events``) — every event
    served before vs after (KEPT / MOVED / REMOVED / ADDED, with reasons and the per-date values that prove each), the level
    badges' and the level milestone ladder's first-crossing dates, and the zero-loss check for the public-input pillars."""
    import backfill_public_variant_events as EV
    from health import achievement_rules, milestone_ledger

    dates = sorted(snap["sheets"])
    before_recs = [snap["sheets"][d] for d in dates]
    after_recs = [
        dict(snap["sheets"][d], **{B.PUBLIC: char[d]["public"]}) if char.get(d, {}).get("public") else snap["sheets"][d] for d in dates
    ]
    badges = {r.id: r.threshold for r in achievement_rules.BADGE_RULES if r.signal == "current_level"}
    ladder = sorted(r.threshold for r in milestone_ledger.MILESTONE_RULES if r.signal == "character_level")
    return EV.event_comparison(before_recs, after_recs, badges, ladder)


def _event_lines(lv: dict) -> list:
    """The SUMMARY.md lines of the event comparison (totals by kind, the zero-loss check, badges and milestones)."""
    totals, out = lv["events"]["totals"], []
    for who in sorted(totals):
        t = totals[who]
        out.append(f"- {who}: KEPT {t['KEPT']} · MOVED {t['MOVED']} · REMOVED {t['REMOVED']} · ADDED {t['ADDED']}")
    for r in lv["events"]["rows"]:
        if r["status"] != "KEPT":
            tail = f" → {r['new_date']}" if r["status"] == "MOVED" else f" ({r.get('reason')})" if r["status"] == "REMOVED" else ""
            proof = r.get("corrected_values") or {}
            vals = (
                f" [corrected: {proof.get('previous_day')} {proof.get('level_before')} → {r['date']} {proof.get('level_on_date')}]"
                if proof
                else ""
            )
            prov = (
                " · provenance: reconstructed" + (f", redated_from {r['date']}" if r["status"] == "MOVED" else "")
                if r["status"] in ("ADDED", "MOVED")
                else ""
            )
            out.append(f"  - {r['status']} {r['date']} {r['who']} {r['type']} {r['old']}→{r['new']}{tail}{vals}{prov}")
    out.append(
        f"- Events stored with INTERNAL provenance `reconstructed` (reconstructed_at, reconstructed_method; redated_from when "
        f"moved): {lv.get('reconstructed_events_marked', 0)}. Never served publicly, never an outbound event (no digest, coach "
        "trigger, chronicle, buddy, character_stats.json or email); level badges / milestones MOVED or ADDED below are "
        "reconstructed too (internal records only)."
    )
    lost, mism = lv["verbatim_losses"], lv["stored_verbatim_mismatches"]
    out.append(
        f"- Public-input pillar (sleep/movement/nutrition/metabolic) events LOST: {len(lost)}"
        + (" — none." if not lost else f": {', '.join(r['date'] + ' ' + r['who'] for r in lost)}")
        + f" Stored per-date pillar events differing: {len(mism)}."
    )
    for name, group in (("Level badges", lv["level_badges"]), ("Level milestones", lv["level_milestones"])):
        out.append(f"- {name}: " + "; ".join(f"{k} {v['before']} → {v['after']} ({v['status']})" for k, v in group.items()))
    return out


def summary_md(manifest: dict, notice: str, out_dir: str) -> str:
    """F: the one-page human-readable summary the owner reviews before any write (written beside the manifest)."""
    s, pvt, lv, plan = manifest["summary"], manifest["privacy_vs_timing"], manifest["level_credit"], manifest["plan"]
    lines = [
        "# Public character recompute — dry run (#6224)",
        "",
        f"Generated {manifest['generated_at']} · method {manifest['public_method_version']} · mode {manifest['mode']}",
        f"Public plan id `{plan.get('public_plan_id')}` · private plan id `{plan.get('private_plan_id')}` · method-1 basis: "
        f"{plan.get('method1_basis')}",
        "",
        "## What changes for readers (before = what the public routes serve today, the stored `public` block)",
        f"- Character dates: {s['character_dates']}. Overall level changes on {len(s['level_changed_dates'])} dates "
        f"(max change {s['character_level']['max_abs_delta']}). XP changes on {s['character_xp']['dates_changed']}; "
        f"composite on {s['composite']['dates_changed']}.",
        "- Mind: not scored in public on every date (no score, level, tier or XP).",
        f"- Dates whose level changes: {', '.join(s['level_changed_dates']) or 'none'}",
        "",
        "## Privacy change vs the timing (order) fix — approve each on its own",
        f"- Dates changed by the PRIVACY-ONLY recompute: {len(pvt['privacy_changed_dates'])}.",
        f"- Dates changed FURTHER by the timing fix: {len(pvt['timing_changed_dates'])}"
        + (
            f" ({', '.join(pvt['timing_changed_dates'])})"
            if pvt["timing_changed_dates"]
            else " — none: with Mind unscored the fix moves no public value"
        )
        + ".",
        "- A privacy-only apply: `--no-order-fix` (the per-date table is `manifest.json` → `privacy_vs_timing`).",
        "",
        "## Event comparison (before = what the public routes served before the containment switch)",
        *_event_lines(lv),
        "",
        "## The correction notice readers will see",
        *(f"> {ln}" if ln else ">" for ln in notice.split("\n")),
        "",
        "## What the write touches",
        f"- Planned writes: {plan['writes']} ({', '.join(f'{k.split(chr(35) + 'SOURCE' + chr(35))[-1]} {v}' for k, v in plan['by_partition'].items())}); "
        f"unchanged and NOT written: {len(plan['skipped_unchanged'])}.",
        "- Each write SETs only the item's `public` attribute (the derived public projection) on an existing "
        "character_sheet / character_receipt / day_grade item, conditional on its method-1 fingerprint; plus ONE new item, "
        "`public_corrections` / `CORRECTION#<method>`. Never a method-1 field, raw data, or any other item.",
        "",
        "## Backup, apply, verify, rollback",
        f"1. Dry run (this): `python3 scripts/backfill_public_variant.py --out {out_dir}` (add `--no-order-fix` for privacy-only).",
        "2. Apply (owner): `--apply --phase pre-merge`, then `--apply --phase post-merge` (receipts). Each writes the "
        "pre-image export (`export_<phase>_<ts>.json`) to --out BEFORE the first write.",
        "3. Verify: re-run the dry run — `plan.writes` must be 0 and `differs_from_stored_public.differing` empty; run "
        "`python3 -m pytest tests/test_public_mind_unscored_6224.py tests/test_restraint_public_figures_6224.py`; curl "
        "`/api/character` and `/api/character_config`. Only then flip `PUBLIC_CHARACTER_SCORES_PENDING_RECOMPUTE` off.",
        "4. Rollback: `python3 scripts/backfill_public_variant.py --rollback <export.json>` (dry run), then add `--apply`.",
        "",
    ]
    return "\n".join(lines)


def _changed(pair) -> bool:
    return isinstance(pair, list) and len(pair) == 2 and pair[0] != pair[1]


def summary(char_rows: list, g_rows: list) -> dict:
    fields = (
        "character_level",
        "character_tier",
        "character_xp",
        "character_xp_debt",
        "composite",
        "character_mood",
        "level_events",
        *(f"{p}_{k}" for p in ROUTE_PILLARS for k in ("level", "score")),
    )
    out: dict[str, Any] = {
        "character_dates": len(char_rows),
        "day_grade_dates": len(g_rows),
        # #6224: "before" is what readers are served today (the stored public block), never method 1
        "before_basis": "stored public block (served today)",
        "level_changed_dates": [r["date"] for r in char_rows if r["level_changed"]],
    }
    for f in fields:
        changed = [r["date"] for r in char_rows if _changed(r[f])]
        deltas = [abs(r[f][1] - r[f][0]) for r in char_rows if _changed(r[f]) and all(isinstance(x, (int, float)) for x in r[f])]
        out[f] = {
            "dates_changed": len(changed),
            "max_abs_delta": round(max(deltas), 4) if deltas else None,
            "first": changed[0] if changed else None,
            "last": changed[-1] if changed else None,
        }
    for f in ("day_grade", "letter", "habits_mvp", "recap_card_letter"):
        changed = [r["date"] for r in g_rows if _changed(r[f])]
        deltas = [abs(r[f][1] - r[f][0]) for r in g_rows if _changed(r[f]) and all(isinstance(x, (int, float)) for x in r[f])]
        out[f] = {"dates_changed": len(changed), "max_abs_delta": round(max(deltas), 4) if deltas else None}
    out["affected_dates"] = sorted(
        {r["date"] for r in char_rows if any(_changed(r[f]) for f in fields)}
        | {r["date"] for r in g_rows if _changed(r["day_grade"]) or _changed(r["letter"])}
    )
    out["verbatim_pillars_changed_dates"] = [r["date"] for r in char_rows if not r["verbatim_pillars_unchanged"]]
    out["method1_replay_mismatch_dates"] = [r["date"] for r in char_rows if r["method1_replay_mismatches"]]
    out["presence_inexact_dates"] = [r["date"] for r in char_rows if r["presence"] and not r["presence"]["exact"]]
    out["habits_replay_unfaithful_dates"] = [r["date"] for r in g_rows if r["habits_replay_fidelity"] is False]
    return out


# ── downstream aggregates ─────────────────────────────────────────────────────────────────


def weekly_means(g_rows: list, genesis: str) -> list:
    """story_dossier's day_grade_mean per experiment week (seven days from genesis), before/after."""
    weeks: dict[int, list] = {}
    for r in g_rows:
        n = (date.fromisoformat(r["date"]) - date.fromisoformat(genesis)).days // 7 + 1
        weeks.setdefault(n, []).append(r)
    out = []
    for n, rs in sorted(weeks.items()):
        a = [x["day_grade"][0] for x in rs if x["day_grade"][0] is not None]
        b = [x["day_grade"][1] for x in rs if x["day_grade"][1] is not None]
        out.append(
            {"week": n, "day_grade_mean": [round(statistics.fmean(a), 1) if a else None, round(statistics.fmean(b), 1) if b else None]}
        )
    return out


def _with_public_grades(series: dict, grades: dict) -> dict:
    """The weekly compute's series with each day's day_grade set to the RECOMPUTED public variant (the stored records
    carry none until the apply; the compute reads ``day_grade_public.public_score`` off them)."""
    for d, m in series.items():
        g = grades.get(d)
        m["day_grade"] = B.day_grade_public.public_score({B.PUBLIC: g["public"]}) if g else None
    return series


def _as_method1(series: dict, snap: dict, habitify: dict) -> dict:
    """The series as method 1 computed it: the stored method-1 day grade and the all-habits habit_pct."""
    from health import habit_pct_public

    for d, m in series.items():
        cm = snap["computed"].get(d) or {}
        m["day_grade"] = float(cm["day_grade_score"]) if cm.get("day_grade_score") is not None else None
        m["habit_pct"] = habit_pct_public.method1_habit_pct(habitify.get(d)) if habitify.get(d) else None
    return series


def correlation_aggregates(table, snap: dict, grades: dict) -> dict:
    """/api/correlations' day-grade pairs and /api/what_changed's day-grade monthly delta, recomputed over the stored
    window both ways (method-1 series vs public series), beside the stored (served) values."""
    from compute import weekly_correlation_compute_lambda as wcc

    stored = sorted(query_all(table, B.PFX + "weekly_correlations", "WEEK#0000", "WEEK#9999"), key=lambda i: i["sk"])
    latest = decimals_to_float(stored[-1]) if stored else {}
    start, end = latest.get("start_date"), latest.get("end_date")
    out: dict[str, Any] = {
        "weekly_correlations_week": latest.get("week") or str(latest.get("sk", "")).replace("WEEK#", ""),
        "window": [start, end],
    }
    if not (start and end):
        return out
    habitify = _dated(query_all(table, B.PFX + "habitify", f"DATE#{B.shift(end, -150)}", f"DATE#{end}~"))
    series_pub = _with_public_grades(wcc.assemble_daily_series(start, end), grades)
    series_m1 = _as_method1(copy.deepcopy(series_pub), snap, habitify)
    pairs = [p for p in wcc.CORRELATION_PAIRS if {"day_grade", "habit_pct"} & {p[0], p[1]}]
    a, b = wcc.compute_correlations(series_m1), wcc.compute_correlations(series_pub)
    served = latest.get("correlations") or {}
    out["pairs"] = {
        p[2]: {
            "served": {k: (served.get(p[2]) or {}).get(k) for k in ("pearson_r", "n_days", "fdr_significant")},
            "recomputed_method1": {k: (a.get(p[2]) or {}).get(k) for k in ("pearson_r", "n_days", "fdr_significant")},
            "recomputed_public": {k: (b.get(p[2]) or {}).get(k) for k in ("pearson_r", "n_days", "fdr_significant")},
        }
        for p in pairs
    }
    wc = decimals_to_float(table.get_item(Key={"pk": B.PFX + "what_changed", "sk": "SNAPSHOT#current"}).get("Item") or {})
    wc_end = wc.get("window_end") or end
    metric = [m for m in wcc._MONTH_DELTA_METRICS if m[0] in ("day_grade", "habit_pct")]
    lo = B.shift(wc_end, -60)
    s_pub = _with_public_grades(wcc.assemble_daily_series(lo, wc_end), grades)
    s_m1 = _as_method1(copy.deepcopy(s_pub), snap, habitify)
    out["what_changed_day_grade"] = {
        "window_end": wc_end,
        "served": [x for x in wc.get("deltas") or [] if x.get("metric") in ("day_grade", "habit_pct")],
        "recomputed_method1": wcc.compute_month_deltas(s_m1, wc_end, metrics=metric),
        "recomputed_public": wcc.compute_month_deltas(s_pub, wc_end, metrics=metric),
    }
    return out


class InjectingTable:
    """The real table (read-only use) with the ``public`` attribute of the character sheets and receipts replaced
    per sort key — how the route handlers are evaluated BEFORE (no injection: main's serving is simulated by a
    method-1 copy) and AFTER (the recomputed public variant), on the same stored records."""

    def __init__(self, real, inject: dict):
        self.real, self.inject = real, inject

    def _fix(self, item):
        if isinstance(item, dict) and item.get("pk") in self.inject:
            v = self.inject[item["pk"]].get(item.get("sk"))
            item = dict(item)
            item.pop(B.PUBLIC, None)
            if v is not None:
                item[B.PUBLIC] = v
        return item

    def query(self, **kw):
        resp = dict(self.real.query(**kw))
        resp["Items"] = [self._fix(i) for i in resp.get("Items", [])]
        return resp

    def get_item(self, **kw):
        resp = dict(self.real.get_item(**kw))
        if "Item" in resp:
            resp["Item"] = self._fix(resp["Item"])
        return resp

    def __getattr__(self, name):  # anything else (put/update/delete) is refused: this evaluation is read-only
        raise AttributeError(f"InjectingTable is read-only ({name})")


def latest_surfaces(snap: dict, char: dict) -> dict:
    """The latest-record surfaces (character_stats.json, /api/character_stats, /api/mind_overview's mind_pillar, the
    buddy page's character block), before (method 1, private pillar held) and after (the public variant)."""
    d = max(char)
    m1, pub = snap["sheets"][d], char[d]["public"]
    out: dict[str, Any] = {"as_of": d}
    for tag, view in (("before", served_view(m1, None)), ("after", served_view(m1, pub))):
        v = view or {}
        pillars = {
            p: {
                k: _num((v.get(f"pillar_{p}") or {}).get(k)) if k != "tier" else (v.get(f"pillar_{p}") or {}).get(k)
                for k in ("level", "raw_score", "tier", "xp_delta")
            }
            for p in ROUTE_PILLARS
        }
        out[tag] = {
            "character_stats": {
                "level": _num(v.get("character_level")),
                "tier": v.get("character_tier"),
                "xp_total": _num(v.get("character_xp")),
                "pillars": pillars,
            },
            "mind_pillar": {k: pillars["mind"][k] for k in ("level", "raw_score", "tier")},
            "buddy_character": {
                "level": _num(v.get("character_level")),
                "tier": v.get("character_tier"),
                "xp": _num(v.get("character_xp")),
                "events": _events(v),
            },
            "pillar_history_weekly_last7": _weekly_levels(snap, char, tag),
        }
    return out


def _weekly_levels(snap: dict, char: dict, tag: str) -> list:
    """character_stats.json's pillar_history: the last record of each ISO week (49 days), level_score per pillar."""
    end = max(char)
    lo = B.shift(end, -49)
    weeks: dict[str, tuple] = {}
    for d in sorted(char):
        if d < lo:
            continue
        view = served_view(snap["sheets"][d], None if tag == "before" else char[d]["public"]) or {}
        weeks[date.fromisoformat(d).strftime("%G-W%V")] = (d, view)
    return [
        {
            "week_end": d,
            "pillars": {
                p: round(float((v.get(f"pillar_{p}") or {}).get("level_score") or (v.get(f"pillar_{p}") or {}).get("raw_score") or 0), 1)
                for p in ROUTE_PILLARS
            },
        }
        for _w, (d, v) in sorted(weeks.items())
    ]


def route_outputs(table, snap: dict, char: dict, receipts: dict) -> dict:
    """The served bodies of the character routes, before and after, evaluated by the routes' own handlers."""
    from web import site_api_character, site_api_discovery, site_api_journey, site_api_vitals

    def _body(resp, before):
        body = json.loads(resp["body"])
        body.pop("_meta", None)
        return body

    def _bodies(inject, before):
        if before:  # today's serving: the stored public blocks, Mind as stored (the not-scored serving is the change)
            keep = (character_privacy.scrub_unscored, character_privacy.public_pillar)
            keep_switch = character_privacy.PUBLIC_CHARACTER_SCORES_PENDING_RECOMPUTE
            character_privacy.scrub_unscored = lambda view: view
            character_privacy.public_pillar = lambda name, pillar: pillar if name == "mind" else keep[1](name, pillar)
            character_privacy.PUBLIC_CHARACTER_SCORES_PENDING_RECOMPUTE = False  # today's deployed code serves the numbers
            try:
                return _bodies_now(inject, before)
            finally:
                character_privacy.scrub_unscored, character_privacy.public_pillar = keep
                character_privacy.PUBLIC_CHARACTER_SCORES_PENDING_RECOMPUTE = keep_switch
        keep_switch = character_privacy.PUBLIC_CHARACTER_SCORES_PENDING_RECOMPUTE
        character_privacy.PUBLIC_CHARACTER_SCORES_PENDING_RECOMPUTE = False  # "after": the serving once the switch flips
        try:
            return _bodies_now(inject, before)
        finally:
            character_privacy.PUBLIC_CHARACTER_SCORES_PENDING_RECOMPUTE = keep_switch

    def _bodies_now(inject, before):
        g = dict(vars(site_api_vitals))
        g["table"] = InjectingTable(table, inject)
        out = {"character_latest": _body(site_api_character.character(None, _g=g), before)}
        out["timeline"] = _body(site_api_journey.timeline(_g=g), before)
        out["journey_timeline"] = _body(site_api_journey.journey_timeline(_g=g), before)
        out["pillar_coupling"] = _body(site_api_discovery.pillar_coupling(_g=g), before)
        if not before:
            out["character_receipt_latest"] = _body(site_api_character.character_receipt(max(char), False, _g=g), before)
        out["character_by_date"] = {}
        for d in sorted(char):
            body = _body(site_api_character.character(d, _g=g), before)
            out["character_by_date"][d] = {
                "level": body["character"].get("level"),
                "composite_score": body["character"].get("composite_score"),
                "xp_total": body["character"].get("xp_total"),
                "mind": next((p for p in body["pillars"] if p["name"] == "mind"), {}).get("raw_score"),
                "method": (body["character"].get("method") or {}).get("origin"),
            }
        return out

    before_inject: dict = {}  # #6224: the stored records as they are — their public block is what readers are served today
    after_inject = {
        B.SHEET_PK: {f"DATE#{d}": r["public"] for d, r in char.items()},
        B.RECEIPT_PK: {f"DATE#{d}": v for d, v in receipts.items()},
    }
    return {"before": _bodies(before_inject, True), "after": _bodies(after_inject, False)}


# ── the CLI ───────────────────────────────────────────────────────────────────────────────


def _write(path: str, obj: Any) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=1, sort_keys=True, default=str)


def write_csv(path: str, rows: list) -> None:
    keys = sorted({k for r in rows for k in r})
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow({k: json.dumps(v, default=str) if isinstance(v, (list, dict)) else v for k, v in r.items()})


def main(argv: list) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", help="directory for the manifest / export (OUTSIDE the repo: it carries real values)")
    ap.add_argument("--to", default=(datetime.now(timezone.utc).date()).isoformat())
    ap.add_argument("--apply", action="store_true", help="WRITE: export the pre-image, then SET `public` (owner act)")
    ap.add_argument("--rollback", help="an export file: restore its pre-image (dry run unless --apply)")
    ap.add_argument("--skip-routes", action="store_true", help="skip the route-handler before/after evaluation")
    ap.add_argument(
        "--no-order-fix",
        action="store_true",
        help="#6224: the PRIVACY-ONLY recompute — leave out the timing (order) fix, so the privacy change can be applied alone",
    )
    ap.add_argument(
        "--phase",
        choices=sorted(B.PHASE_PARTITIONS),
        default="all",  # dry runs plan everything; an --apply must name its phase (below)
        help="pre-merge: sheets + day grades + the ledger (inert on the old code); post-merge: the receipts (after the deploy)",
    )
    ap.add_argument(
        "--plan-in",
        help="#6224/#6311: a private recompute plan (character-private-recompute-plan-v1) — the public dry run reads its "
        "PLANNED character rows instead of the stored ones, and the public apply requires exactly those rows live",
    )
    ap.add_argument("--approved-public-plan-id", help="with --plan-in --apply: the public_plan_id the owner approved (must reproduce)")
    args = ap.parse_args(argv)
    if args.apply and not args.rollback and args.phase == "all":
        ap.error("--apply needs --phase pre-merge or post-merge: a receipt written before the merge is served early by the old code")

    import boto3

    region = os.environ["AWS_DEFAULT_REGION"]
    table = boto3.resource("dynamodb", region_name=region).Table(os.environ["TABLE_NAME"])
    run_ts = datetime.now(timezone.utc).isoformat()

    if args.rollback:
        with open(args.rollback, encoding="utf-8") as fh:
            export = json.load(fh)
        result = B.rollback(table, export, apply=args.apply)
        print(json.dumps({k: (len(v) if isinstance(v, list) else v) for k, v in result.items()}, indent=1))
        if args.out:
            _write(os.path.join(args.out, "rollback_result.json"), result)
        return 0 if not result["refused"] else 2

    if not args.out:
        ap.error("--out is required (a directory outside the repo)")
    os.makedirs(args.out, exist_ok=True)
    snap = load_snapshot(table, args.to)
    import backfill_public_variant_planin as PI

    try:
        private_plan, expected = PI.load_into_snapshot(args.plan_in, snap)
    except PI.PlanInError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 3
    config = load_config(table, boto3.client("s3", region_name=region))
    char, receipts, grades = run_replays(snap, config, run_ts, order_fix=not args.no_order_fix)
    privacy_only = char if args.no_order_fix else run_replays(snap, config, run_ts, order_fix=False)[0]
    full = char if not args.no_order_fix else run_replays(snap, config, run_ts, order_fix=True)[0]
    c_rows, g_rows = character_rows(snap, char), grade_rows(snap, grades)
    manifest = {
        "generated_at": run_ts,
        "mode": "apply" if args.apply else "dry-run",
        "public_method_version": character_privacy.PUBLIC_METHOD_VERSION,
        "day_grade_public_method_version": B.day_grade_public.METHOD_VERSION,
        "summary": summary(c_rows, g_rows),
        "character": c_rows,
        "day_grade": g_rows,
        "story_dossier_day_grade_mean": weekly_means(g_rows, B.EXPERIMENT_START_DATE),
        "receipts": {"planned": len(receipts), "replay_verified": sum(1 for r in receipts.values() if r and r.get("replay_verified"))},
        "order_fix_applied": not args.no_order_fix,
    }
    manifest["privacy_vs_timing"] = privacy_vs_timing(snap, privacy_only, full)
    manifest["level_credit"] = level_credit_changes(snap, char)
    # #6224 (owner ruling 2026-11-26 23:50Z): the INTERNAL provenance of every reconstructed event, stored in the
    # recomputed public projection (never served — character_privacy.public_sheet strips it and serves no reconstructed
    # event as an event); idempotent against an already-applied block
    import backfill_public_variant_events as EV

    manifest["level_credit"]["reconstructed_events_marked"] = EV.annotate_provenance(
        {d: r["public"] for d, r in char.items() if r.get("public")},
        snap["sheets"],
        manifest["level_credit"]["events"],
        run_ts[:10],
        character_privacy.PUBLIC_METHOD_VERSION,
    )
    import recompute_character_verify as VF

    manifest["verification"] = VF.manifest_checks(snap, char, c_rows, manifest["level_credit"])  # #6224 owner conditions A/B
    if private_plan is not None:  # #6224: which named change moves each public number (order-dependent, stated)
        import recompute_character_attribution as ATT

        manifest["attribution"] = ATT.public_attribution(sys.modules[__name__], snap, config, run_ts, args.plan_in, char)
    manifest["correlations_and_what_changed"] = correlation_aggregates(table, snap, grades)
    manifest["latest_surfaces"] = latest_surfaces(snap, char)
    h_rows = R.habit_pct_rows(snap["habitify"], snap["profile"].get("habit_registry") or {})
    manifest["habit_pct"] = {"method_version": R.habit_pct_public.METHOD_VERSION, "rows": h_rows}
    manifest["reasons_legend"] = R.REASONS
    manifest["historical_invariance"] = R.historical_invariance(snap, config, run_ts)
    manifest["public_habit_evidence"] = R.habit_evidence(snap, char, config)
    ledger = R.ledger_rows(c_rows, g_rows, h_rows, snap, run_ts)
    with open(os.path.join(args.out, "correction_ledger.jsonl"), "w", encoding="utf-8") as fh:
        fh.writelines(json.dumps(row, sort_keys=True, default=str) + "\n" for row in ledger)
    manifest["correction_ledger"] = {"rows": len(ledger), "file": "correction_ledger.jsonl", "format": R.LEDGER_VERSION}
    if not args.skip_routes:
        manifest["routes"] = route_outputs(table, snap, char, receipts)
    plan_all = B.plan_writes(char, grades, set(snap["receipts"]), receipts)
    # #6224: the v2 ledger carries the range, the count and the reasons — no per-date before/after (a v1 "before"
    # included Mind, whose inputs are private; public_corrections.build_ledger).
    ledger_item = B.public_corrections.build_ledger({d: r["public"] for d, r in char.items()}, run_ts[:10])
    _write(os.path.join(args.out, "public_correction_ledger.json"), ledger_item)
    stored = {(B.SHEET_PK, f"DATE#{d}"): r for d, r in snap["sheets"].items()}
    stored.update({(B.RECEIPT_PK, f"DATE#{d}"): r for d, r in snap["receipts"].items()})
    stored.update({(B.GRADE_PK, f"DATE#{d}"): r for d, r in snap["grades"].items()})
    plan, skipped_unchanged = narrow_plan(plan_all, stored)  # #6224 F(8): only the projections that change are written
    plan = PI.attach_expected(plan, expected)  # #6311: each write requires the PLANNED private row's fingerprint
    private_plan_id = (private_plan or {}).get("plan_id")
    manifest["plan"] = {
        "private_plan_id": private_plan_id,
        "public_plan_id": PI.public_plan_id(private_plan_id, character_privacy.PUBLIC_METHOD_VERSION, plan),
        "method1_basis": "the private plan's PLANNED rows (--plan-in)" if private_plan else "the stored rows",
        "writes": len(plan),
        "skipped_unchanged": skipped_unchanged,
        "touches": "only the `public` attribute of existing character_sheet / character_receipt / day_grade items, plus the "
        "one public_corrections ledger item — never a method-1 field, raw data or any other item",
        "by_partition": {pk: sum(1 for w in plan if w["pk"] == pk) for pk in {w["pk"] for w in plan}},
        # idempotency: planned values that differ from a public variant already stored (0 after an apply + re-run)
        "differs_from_stored_public": B.differs_from_stored(plan, stored),
    }
    phase_plan = B.plan_for_phase(plan, args.phase)
    manifest["plan"]["phase"] = {
        "name": args.phase,
        "writes": len(phase_plan),
        "writes_ledger": B.PHASE_WRITES_LEDGER[args.phase],
    }
    _write(os.path.join(args.out, "manifest.json"), manifest)
    with open(os.path.join(args.out, "SUMMARY.md"), "w", encoding="utf-8") as fh:
        fh.write(summary_md(manifest, ledger_item.get("notice") or "", args.out))
    write_csv(os.path.join(args.out, "manifest_character.csv"), c_rows)
    write_csv(os.path.join(args.out, "manifest_day_grade.csv"), g_rows)
    _write(os.path.join(args.out, "plan.json"), plan)
    print(json.dumps(manifest["summary"], indent=1, default=str))
    if not args.apply:
        print(f"DRY RUN — nothing written. {len(plan)} planned writes, {len(phase_plan)} in phase {args.phase}; manifest in {args.out}")
        return 0
    refusal = PI.apply_refusal(private_plan, args.approved_public_plan_id, manifest["plan"]["public_plan_id"], table, phase_plan)
    if refusal:
        print(f"REFUSED: {refusal}", file=sys.stderr)
        return 3
    export = B.build_export(lambda key: table.get_item(Key=key).get("Item"), phase_plan, run_ts)
    export["phase"] = args.phase
    export_path = os.path.join(args.out, f"export_{args.phase}_{run_ts.replace(':', '')}.json")
    if B.PHASE_WRITES_LEDGER[args.phase]:
        B.record_ledger_preimage(table, export)
    _write(export_path, export)  # the pre-image exists on disk BEFORE the first write
    result = B.apply_plan(table, phase_plan, export)
    if B.PHASE_WRITES_LEDGER[args.phase]:
        B.put_public_ledger(table, ledger_item)
    _write(os.path.join(args.out, "apply_result.json"), result)
    print(json.dumps({"written": result["written"], "skipped": len(result["skipped"]), "export": export_path}, indent=1))
    return 0 if not result["skipped"] else 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv[1:]))
