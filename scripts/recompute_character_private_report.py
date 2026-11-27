#!/usr/bin/env python3
"""scripts/recompute_character_private_report.py — the REPORTS of ``recompute_character_private.py`` (#6311).

The served baseline, the event comparison, the consumed-challenge XP check, the stress-day set, the counts, and the
output files (plan.json, per_date.csv, SUMMARY.md). Read-only and pure over a computed plan; split from the dry-run half
by the module-size ceiling (#1665).
"""

from __future__ import annotations

import csv
import json
import os
import sys
from typing import Any, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from recompute_character_private import (  # noqa: E402
    ROOT,
    SHEET_PK,
    WRITTEN_PARTITIONS,
    as_float,
    canonical,
    digest,
    refuse_in_repo,
)

# ── reports: served baseline, events, challenge XP, stress days ─────────────────────────────────────────────────────


def served_baselines(rows: list) -> dict:
    """Per date: what the public routes serve from the STORED row (its ``public`` block), and the proof that the
    planned private row serves the same (the private apply changes nothing a reader sees)."""
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    from backfill_public_variant_cli import served_today

    out = {}
    for r in rows:
        if r["pk"] != SHEET_PK or r["planned_item"] is None:
            continue
        before = served_today(as_float(r_stored(r)))
        after = served_today(as_float(r["planned_item"]))
        out[r["date"]] = {
            "served": (
                None
                if before is None
                else {"character_level": before.get("character_level"), "digest": digest(json.loads(json.dumps(before, default=str)))}
            ),
            "unchanged_by_private_apply": canonical(json.loads(json.dumps(before, default=str)))
            == canonical(json.loads(json.dumps(after, default=str))),
        }
    return out


def r_stored(r: dict) -> dict:
    """The row's stored pre-image (typed); kept in memory only — ``public_rows`` strips it (and ``_owned``) from the file."""
    return r["_stored"]


def public_rows(rows: list) -> list:
    return [{k: v for k, v in r.items() if not k.startswith("_")} for r in rows]


def _flat_events(by_date: dict) -> list:
    out = []
    for d in sorted(by_date):
        for ev in (by_date[d] or {}).get("level_events") or []:
            if not isinstance(ev, dict):
                continue
            who = str(ev.get("pillar") or "character").lower()
            tier = "tier" in str(ev.get("type"))
            new = ev.get("new_tier") if tier else _lv(ev.get("new_level"))
            old = ev.get("old_tier") if tier else _lv(ev.get("old_level"))
            out.append({"date": d, "who": who, "type": ev.get("type"), "old": old, "new": new, "key": [who, ev.get("type"), str(new)]})
    return out


def _lv(v: Any) -> Any:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return v
    return int(f) if f == int(f) else round(f, 4)


def event_report(stored_f: dict, planned_f: dict, ladder_f: list) -> dict:
    """KEPT / MOVED / REMOVED / ADDED for every private level event, the level badges' and level milestones' first
    crossing dates (the #6283 rules' rungs), and the events each ladder step emits. Reported only, never written."""
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import backfill_public_variant_events as EV
    from health import achievement_rules, milestone_ledger

    values = {d: {"character": _lv((r or {}).get("character_level"))} for d, r in planned_f.items()}
    for d, r in planned_f.items():
        for k, p in (r or {}).items():
            if k.startswith("pillar_") and isinstance(p, dict) and p.get("level") is not None:
                values[d][k[7:]] = _lv(p["level"])
    comp = EV.compare(_flat_events(stored_f), _flat_events(planned_f), values)
    badges = {r.id: r.threshold for r in achievement_rules.BADGE_RULES if r.signal == "current_level"}
    ladder_rungs = sorted(r.threshold for r in milestone_ledger.MILESTONE_RULES if r.signal == "character_level")

    def first(series: dict, n: Any) -> Optional[str]:
        return next(
            (
                d
                for d in sorted(series)
                if _lv((series[d] or {}).get("character_level")) is not None and float((series[d] or {}).get("character_level")) >= float(n)
            ),
            None,
        )

    crossings = {}
    for label, n in [*((f"badge:{k}", v) for k, v in badges.items()), *((f"milestone:level_{n}", n) for n in ladder_rungs)]:
        pair = [first(stored_f, n), first(planned_f, n)]
        status = "KEPT" if pair[0] == pair[1] else "MOVED" if pair[0] and pair[1] else "REMOVED" if pair[0] else "ADDED"
        crossings[label] = {"before": pair[0], "after": pair[1], "status": status}
    per_step = {}
    for cause, recs in ladder_f:
        evs = _flat_events(recs)
        per_step[cause] = {
            "level_up": sum(1 for e in evs if str(e["type"]).endswith("level_up")),
            "level_down": sum(1 for e in evs if str(e["type"]).endswith("level_down")),
        }
    return {"events": comp, "rung_crossings": crossings, "events_by_step": per_step, "writes_events": False}


def challenge_report(snap: dict, rows: list) -> dict:
    """Consumed challenge XP: the stored sheets' ``challenge_bonus_xp`` against the consumed challenges, and the proof
    that every planned sheet carries it unchanged (never recomputed away — the compute skips consumed challenges)."""
    domain_to_pillar = lambda_constant("CHALLENGE_DOMAIN_TO_PILLAR")
    expected: dict = {}
    for ch in snap.get("challenges") or []:
        if not ch.get("xp_consumed_at") or ch.get("status") not in ("completed", "failed"):
            continue
        xp = int(float(ch.get("character_xp_awarded", 0) or 0))
        if xp <= 0:
            continue
        d = str(ch.get("completed_at", ""))[:10]
        pillar = domain_to_pillar.get(ch.get("domain", "general"), "consistency")
        expected.setdefault(d, {})
        expected[d][pillar] = expected[d].get(pillar, 0) + xp
    out = {
        "dates_with_consumed_xp": 0,
        "stored_matches_consumed": 0,
        "stored_differs": [],
        "planned_carries_stored": True,
        "missing_rows": [],
    }
    by_date = {r["date"]: r for r in rows if r["pk"] == SHEET_PK}
    for d in sorted(set(expected) | {d for d, r in by_date.items() if as_float(r_stored(r)).get("challenge_bonus_xp")}):
        if not (snap["start"] <= d <= snap["end"]):
            continue
        out["dates_with_consumed_xp"] += 1
        r = by_date.get(d)
        if r is None:
            out["missing_rows"].append(d)
            continue
        s = {k: int(v) for k, v in (as_float(r_stored(r)).get("challenge_bonus_xp") or {}).items()}
        p = {k: int(v) for k, v in (as_float(r["planned_item"] or {}).get("challenge_bonus_xp") or {}).items()}
        if s == expected.get(d, {}):
            out["stored_matches_consumed"] += 1
        else:
            out["stored_differs"].append(d)
        if p != s:
            out["planned_carries_stored"] = False
    return out


def lambda_constant(name: str) -> Any:
    """A literal constant of the compute Lambda, read from its source (importing it would build boto3 resources)."""
    import ast

    path = os.path.join(ROOT, "lambdas", "compute", "character_sheet_lambda.py")
    for node in ast.parse(open(path, encoding="utf-8").read()).body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise RuntimeError(f"{name} not found in the compute Lambda")


def stress_days(snap: dict) -> list:
    """Dates whose stored Mind carried a stress contribution (a stress score not held out) — the #5129 stale set."""
    out = []
    for d, s in sorted(snap["sheets"].items()):
        comp = (((s.get("pillar_mind") or {}).get("components") or {}).get("stress_management")) or {}
        if comp.get("score") is not None and not comp.get("held_out"):
            out.append(d)
    return out


def preserved_attributes(rows: list) -> dict:
    """{partition: {attribute: rows}} — the stored attributes the plan keeps exactly as stored (not engine-owned)."""
    out: dict = {}
    for r in rows:
        if r["planned_item"] is None:
            continue
        for k in sorted(set(r["_stored"]) - set(r["_owned"]) - {"pk", "sk"}):
            out.setdefault(r["partition"], {}).setdefault(k, 0)
            out[r["partition"]][k] += 1
    return out


def counts(rows: list, snap: dict) -> dict:
    out: dict = {}
    for pk in WRITTEN_PARTITIONS:
        rs = [r for r in rows if r["pk"] == pk]
        name = pk.split("#SOURCE#")[-1]
        out[name] = {
            "rows_read": len(rs),
            "rows_to_write": sum(1 for r in rs if r["action"] == "write"),
            "rows_unchanged": sum(1 for r in rs if r["action"] == "unchanged"),
            "rows_not_planned": sum(1 for r in rs if r["action"] == "not_planned"),
            "attributes_changed": sum(len(r["changed_attributes"]) for r in rs if r["action"] == "write"),
            "attributes_removed": sum(len(r["removed_attributes"]) for r in rs if r["action"] == "write"),
        }
    out["dates_affected"] = len({r["date"] for r in rows if r["action"] == "write"})
    return out


# ── outputs ─────────────────────────────────────────────────────────────────────────────────────────────────────────


def write_outputs(plan: dict, out_dir: str, plan_out: Optional[str] = None, preliminary: bool = False) -> dict:
    plan_path = refuse_in_repo(plan_out or os.path.join(out_dir, "plan.json"))
    with open(plan_path, "w", encoding="utf-8") as fh:
        json.dump(dict(plan, rows=public_rows(plan["rows"])), fh, indent=1, sort_keys=True)
    csv_path = os.path.join(out_dir, "per_date.csv")
    write_csv(csv_path, per_date_rows(plan))
    md_path = os.path.join(out_dir, "SUMMARY.md")
    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write(summary_md(plan, preliminary=preliminary))
    return {"plan": plan_path, "csv": csv_path, "summary": md_path}


def per_date_rows(plan: dict) -> list:
    out = []
    by = {}
    for r in plan["rows"]:
        by.setdefault(r["date"], {})[r["partition"]] = r
    for d in sorted(by):
        s, rc = by[d].get("character_sheet"), by[d].get("character_receipt")
        row: dict = {"date": d}
        if s:
            st, pl = as_float(r_stored(s)), as_float(s["planned_item"] or {})
            row.update(
                {
                    "sheet_action": s["action"],
                    "sheet_attributes_changed": len(s["changed_attributes"]),
                    "sheet_leaves_changed": s.get("leaf_changes"),
                    "sheet_causes": "|".join(s["causes"]),
                    "character_level": f"{st.get('character_level')}->{pl.get('character_level')}",
                    "character_xp": f"{st.get('character_xp')}->{pl.get('character_xp')}",
                    "character_xp_debt": f"{st.get('character_xp_debt')}->{pl.get('character_xp_debt')}",
                }
            )
            for p in ("sleep", "movement", "nutrition", "metabolic", "mind", "relationships", "consistency"):
                a, b = st.get(f"pillar_{p}") or {}, pl.get(f"pillar_{p}") or {}
                row[f"{p}_level"] = f"{a.get('level')}->{b.get('level')}"
                row[f"{p}_raw"] = f"{a.get('raw_score')}->{b.get('raw_score')}"
            for c in plan["ladder"]:
                row[f"step_{c['cause']}"] = "|".join(plan["attribution"].get(d, {}).get("by_step", {}).get(c["cause"], []))
        if rc:
            row.update({"receipt_action": rc["action"], "receipt_attributes_changed": len(rc["changed_attributes"])})
        out.append(row)
    return out


def write_csv(path: str, rows: list) -> None:
    keys = []
    for r in rows:
        keys += [k for k in r if k not in keys]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow(r)


PRELIMINARY_BANNER = (
    "**PRELIMINARY — not the dry run for approval.** The final dry run is the COMBINED one: the public projection's dry "
    "run (#6283) over this file's planned private rows, presented together. Nothing was written: every DynamoDB and S3 "
    "call went through a proxy that refuses each write verb."
)
OWNER_GATE = (
    "1. the public dry run over this plan (its --plan-in) · 2. the owner approves the exact combined plan ids · 3. the "
    "method PR (#6299) merges and deploys · 4. a re-run of this dry run on the deployed tree reproduces the approved plan "
    "id (--apply refuses otherwise) · 5. --apply --plan-in plan.json --phase sheets, then --phase receipts · 6. the public "
    "apply · 7. both --verify runs report 0 planned writes"
)


def summary_md(plan: dict, preliminary: bool = False) -> str:
    c, a, ev = plan["counts"], plan["accounting"], plan["events"]
    lines = [
        f"# Private character recompute — dry run ({plan['plan_id']})",
        "",
        *([PRELIMINARY_BANNER, ""] if preliminary else []),
        f"Generated {plan['generated_at']} · engine {plan['method']['engine_version']} · config {plan['method']['config_version']} · "
        f"tree {plan['method']['tree']['head'][:12]}{' (dirty)' if plan['method']['tree']['dirty'] else ''} · window "
        f"{plan['window']['start']}..{plan['window']['end']} ({plan['window']['sheet_dates']} stored sheets)",
        "",
        "## Rows",
    ]
    for name in ("character_sheet", "character_receipt"):
        x = c[name]
        lines.append(
            f"- {name}: read {x['rows_read']} · to write {x['rows_to_write']} · unchanged {x['rows_unchanged']} · not planned "
            f"{x['rows_not_planned']} · attributes changed {x['attributes_changed']} · removed {x['attributes_removed']}"
        )
    lines += [f"- dates affected: {c['dates_affected']}", "", "## Ladder (cumulative; dates / attributes / leaves changed by each step)"]
    for step in plan["ladder"]:
        t = a["ladder_totals"][step["cause"]]
        lines.append(
            f"- {step['cause']}: {t['dates']} / {t['attributes']} / {t['leaves']} (changed then restored later: {a['changed_then_restored'][step['cause']]})"
        )
    sd = plan["stress_days"]
    lines += [
        "",
        f"## Stress days: stored with a counted stress score {len(sd['stored_with_stress'])}; Mind raw changed by the stress "
        f"step {len(sd['mind_raw_changed_by_stress_step'])} (same set: {sd['same_set']}); later dates moved only through the "
        f"chain {len(sd['changed_only_through_the_chain'])}",
        f"## Receipts whose planned self-replay verifies: {plan['receipts_self_replay_verified']} of {c['character_receipt']['rows_read']}",
        "",
        "## Events (reported only; the #6283 reconciliation writes them)",
    ]
    for who, t in sorted(ev["events"]["totals"].items()):
        lines.append(f"- {who}: KEPT {t['KEPT']} · MOVED {t['MOVED']} · REMOVED {t['REMOVED']} · ADDED {t['ADDED']}")
    lines.append(
        "- events by step: " + "; ".join(f"{k} up {v['level_up']} down {v['level_down']}" for k, v in ev["events_by_step"].items())
    )
    ch = plan["challenge_xp"]
    served = plan["served_baseline"]
    lines += [
        "",
        f"## Consumed challenge XP: {ch['dates_with_consumed_xp']} dates; stored matches consumed on {ch['stored_matches_consumed']}; "
        f"planned carries stored: {ch['planned_carries_stored']}",
        f"## Served baseline unchanged by the private apply on {sum(1 for v in served.values() if v['unchanged_by_private_apply'])} of {len(served)} dates",
        "",
        "## Controls",
        f"- tree_switch_residual (must be 0): {a['ladder_totals'].get('tree_switch_residual', {}).get('attributes', 'n/a')} attributes",
        "- replay_residual: what the stored method's own replay does not reproduce — never a method change; read its "
        "attributes in plan.json `attribution` before approving",
        f"- method tree {'DIRTY: re-run from the committed, deployed tree' if plan['method']['tree']['dirty'] else 'clean'}",
        "",
        "## Before any write (owner gate)",
        OWNER_GATE,
        "",
    ]
    return "\n".join(lines)
