#!/usr/bin/env python3
"""scripts/recompute_character_combined.py — the ONE combined dry run of the character recompute (#6224, #6311).

Owner rulings 2026-11-26/27: one final recompute, shown as one combined dry run before any write. This runner is thin
and DRY-RUN ONLY. It has no write path of its own. It runs the two tools in their documented order:

  1. the PRIVATE dry run  — ``scripts/recompute_character_private.py --out OUT/private --plan-out OUT/private/plan.json``
  2. the PUBLIC dry run on the planned private rows — ``scripts/backfill_public_variant.py --out OUT/public
     --plan-in OUT/private/plan.json``
  3. the end-to-end backup/rollback test on fake storage (``tests/test_recompute_combined_6224.py``)

and writes ONE ``OUT/COMBINED_SUMMARY.md`` (plus ``OUT/combined.json``) with what the owner asked to see before
approving any write. Every per-date value stays in the two private manifests. The summary gives counts, ranges and date
lists. The run FAILS (exit 2) when a public change cannot be traced to a named cause.

    python3 scripts/recompute_character_combined.py --out DIR [--preliminary] [--skip-tests]

The apply is NOT here: it is each tool's own ``--apply``, in the order this summary states, by the owner.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from typing import Any, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))

E2E_TEST = "tests/test_recompute_combined_6224.py"
import recompute_character_combined_sections as S  # noqa: E402

LOCAL_RUNS = (
    "black / ruff / flake8 on every changed file",
    "the targeted character, public-copies, restraint, private-recompute and combined tests",
    "the guard / size / mypy / attribution tests",
    "the eight structural pre-merge gates (CLAUDE lane rule 6a)",
)
PUBLIC_FIELDS = ("character_level", "character_tier", "character_xp", "character_xp_debt", "composite", "character_mood", "level_events")


def _outside_repo(path: str) -> str:
    real = os.path.realpath(path)
    if real == os.path.realpath(ROOT) or real.startswith(os.path.realpath(ROOT) + os.sep):
        raise SystemExit(f"REFUSED: --out {path} is inside the repo — the outputs carry real values")
    return real


def _run(cmd: list) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, *cmd], cwd=ROOT, capture_output=True, text=True)


# ── attribution and the method events (computed by the public dry run: recompute_character_attribution) ────────────


def _att_failures(att: dict) -> list:
    import recompute_character_attribution as ATT

    return ATT.failures(att) if att else ["the public dry run carries no attribution"]


def _method_events(att: dict) -> list:
    return ((att or {}).get("method") or {}).get("events") or []


def protected_breaches(att: dict, events: dict) -> list:
    """Sleep or movement events the recompute loses or moves (the owner's standing condition) — method or privacy."""
    out = [
        f"{r['date']} {r['who']} {r['event']} L{r['level']} {r['change']} (method)" for r in _method_events(att) if r["protected_pillar"]
    ]
    out += [
        f"{r['date']} {r['who']} {r['key'][2]} {r['status']} (public)"
        for r in events.get("rows") or []
        if r["who"] in ("sleep", "movement") and r["status"] in ("MOVED", "REMOVED")
    ]
    return out


def event_deltas(old_manifest: Optional[dict], new_events: dict, method_events: list) -> list:
    """Each public event whose status differs from a previous dry run's (e.g. #6283's), with the method cause that
    explains it where a method event matches (same date, pillar and level)."""
    if not old_manifest:
        return []
    old = {(r["date"], r["who"], r["key"][2]): r["status"] for r in old_manifest["level_credit"]["events"]["rows"]}
    new = {(r["date"], r["who"], r["key"][2]): r["status"] for r in new_events.get("rows") or []}
    why = {(m["date"], m["who"], str(m["level"])): f"private chain {m['change']} by {m['first_cause']}" for m in method_events}
    out = []
    for k in sorted(set(old) | set(new)):
        if old.get(k) != new.get(k):
            cause = why.get(k) or (
                "the public chain on the PLANNED rows (method part); no private event at the same level, because the public "
                "level differs from the private one"
            )
            out.append(f"{k[0]} {k[1]} {k[2]}: {old.get(k, 'absent')} → {new.get(k, 'absent')} — {cause}")
    return out


def _totals_delta(old_manifest: Optional[dict], new_lc: dict) -> list:
    if not old_manifest:
        return []
    o, n = old_manifest["level_credit"]["events"]["totals"], new_lc["events"]["totals"]
    out = []
    for who in sorted(set(o) | set(n)):
        for k in ("KEPT", "MOVED", "REMOVED", "ADDED"):
            a, b = (o.get(who) or {}).get(k, 0), (n.get(who) or {}).get(k, 0)
            if a != b:
                out.append(f"{who} {k} {a} → {b}")
    a, b = old_manifest["level_credit"].get("reconstructed_events_marked"), new_lc.get("reconstructed_events_marked", 0)
    if a is None:
        out.append(f"reconstructed: not recorded in the previous manifest, {b} now")
    elif a != b:
        out.append(f"reconstructed {a} → {b}")
    return out


# ── the parts of the summary ─────────────────────────────────────────────────────────────────────────────────────


def _changed(pair: Any) -> bool:
    return isinstance(pair, list) and len(pair) == 2 and pair[0] != pair[1]


def score_changes(public_manifest: dict) -> dict:
    rows = public_manifest.get("character") or []

    def deltas(field: str) -> list:
        return [
            round(r[field][1] - r[field][0], 4)
            for r in rows
            if _changed(r.get(field)) and all(isinstance(x, (int, float)) for x in r[field])
        ]

    out: dict = {"dates": len(rows), "level_changed_dates": [r["date"] for r in rows if r.get("level_changed")]}
    for f in ("character_level", "character_xp", "composite"):
        dl = deltas(f)
        out[f] = {"dates_changed": sum(1 for r in rows if _changed(r.get(f))), "delta_range": [min(dl), max(dl)] if dl else None}
    debt = [r.get("character_xp_debt") or [None, None] for r in rows]
    out["xp_debt"] = {
        "dates_with_debt_before": sum(1 for b, _a in debt if isinstance(b, (int, float)) and b > 0),
        "after_zero_on_every_date": all(a in (0, 0.0, None) for _b, a in debt),
    }
    return out


def privacy_checks(public_dir: str) -> dict:
    """Every planned public block, as a public reader would serve it once the switch flips: no provenance key, no
    withheld word, no Mind or Relationships number. The notice, and no per-date difference table in the public ledger."""
    from health import character_privacy as CP

    plan = json.load(open(os.path.join(public_dir, "plan.json"), encoding="utf-8"))
    ledger = json.load(open(os.path.join(public_dir, "public_correction_ledger.json"), encoding="utf-8"))
    with open(os.path.join(ROOT, "config", "character_sheet.json"), encoding="utf-8") as fh:
        tokens = [t.lower() for t in CP.withheld_public_tokens(json.load(fh))] + [
            k.lower() for k in CP.PROVENANCE_KEYS + CP.PLANNED_REST_KEYS
        ]
    leaks, numbers, served = [], [], 0
    for w in plan:
        if not w["pk"].endswith("#SOURCE#character_sheet"):
            continue
        view = CP.public_sheet({"sk": w["sk"], "date": w["sk"][5:], CP.PUBLIC_KEY: w["value"]}, pending=False)
        if view is None:
            continue
        served += 1
        blob = json.dumps(view, default=str).lower()
        leaks += [f"{w['sk']}: {t}" for t in tokens if t in blob]
        for name in CP.UNSCORED_PUBLIC_PILLARS:
            p = view.get(f"pillar_{name}") or {}
            if any(p.get(k) is not None for k in ("level", "raw_score", "level_score", "tier", "xp_total")):
                numbers.append(f"{w['sk']}: {name}")
    return {
        "planned_blocks_served": served,
        "withheld_or_provenance_tokens": leaks,
        "unscored_pillar_numbers": numbers,
        "ledger_rows": len(ledger.get("rows") or []),
        "notice": ledger.get("notice"),
    }


def synthetic_route_walk() -> dict:
    """The route walk over every public GET route, offline, on its SYNTHETIC rows with a corrected-chain variant planted
    (``--provenance --scores-live``). The live planned state cannot be walked offline; the planned blocks themselves are
    checked by ``privacy_checks``."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    cp = _run(["tests/restraint_route_walk.py", "--state", "low", "--now", now, "--provenance", "--scores-live"])
    if cp.returncode != 0:
        return {"ran": False, "error": cp.stderr[-500:]}
    out = json.loads(cp.stdout.strip().splitlines()[-1])
    return {
        "ran": True,
        "answered": out["answered"],
        "raised": len(out["raised"]),
        "leaks": out["leaks"],
        "unscored_numbers": out.get("mind"),
    }


def e2e_test() -> dict:
    cp = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", E2E_TEST], cwd=ROOT, capture_output=True, text=True
    )
    tail = (cp.stdout.strip().splitlines() or [""])[-1]
    return {"passed": cp.returncode == 0, "result": tail}


def _rng(v: Optional[dict]) -> str:
    return f"{v['dates']}, {v['range']}" if v and v.get("dates") else "0"


def _attribution_lines(att: dict) -> list:
    m, p = att.get("method") or {}, att.get("public") or {}
    lines = [
        "Two layers. The private plan's per-row cause tags name nearly every cause on every date and are not used.",
        "",
        "**Layer 1 — the METHOD, on the private (method-1) chain** (the private tool's `ladder_states`). Each date's change is "
        "credited to the FIRST ladder step whose value differs from the step before (for replay_residual: from the stored "
        f"row). Attribution is ORDER-DEPENDENT; the order is: {' → '.join(m.get('order') or [])}.",
        "",
        "| cause | private level: dates first changed, step-delta range (min / median / max) | private XP | private composite |",
        "|---|---|---|---|",
    ]
    causes = []
    for q in ("character_level", "character_xp", "composite"):
        causes += [c for c in (m.get("first_cause") or {}).get(q, {}) if c not in causes]
    for c in [c for c in (m.get("order") or []) if c in causes]:
        cells = []
        for q in ("character_level", "character_xp", "composite"):
            n = ((m.get("first_cause") or {}).get(q) or {}).get(c, 0)
            cells.append(f"{n}, {((m.get('first_cause_range') or {}).get(q) or {}).get(c)}" if n else "0")
        lines.append(f"| {c} | " + " | ".join(cells) + " |")
    lines += [
        *(
            f"- Control step `{ctl}` (from `causes_legend`) equal to its predecessor on every date: {not ds} (differs on {len(ds)})."
            for ctl, ds in (m.get("control_differs") or {}).items()
        ),
        f"- Last step equal to the planned sheets on every date (level, XP, each pillar's raw score and level): "
        f"{not m.get('last_step_differs_from_plan')} (differs on {len(m.get('last_step_differs_from_plan') or [])}).",
        "- Stored states vs the replay_residual step (level / XP / composite; a presentation residual, expected empty, "
        "reported not failed): "
        + "; ".join(
            f"{q} differs on {len(v)}" + (f" ({', '.join(v)})" if v else "") for q, v in (m.get("stored_vs_replay_residual") or {}).items()
        )
        + ".",
        "",
        "**Layer 2 — the PUBLIC delta (stored public → v3 public)**, cumulative: `privacy` = the v3 projection of the STORED "
        "private rows (restraint inputs removed, Mind and Relationships unscored in public, the food-delivery multiplier not "
        "applied), without the habit-timing fix; `habit_timing` = the same with the public habit-order fix; `method` = the "
        "projection of the PLANNED private rows (layer 1's change).",
        "",
        "| part | public level: dates, delta range (min / median / max) | XP | XP debt | composite |",
        "|---|---|---|---|---|",
    ]
    for part in p.get("parts") or []:
        b = (p.get("by_part") or {}).get(part) or {}
        lines.append(
            f"| {part} | {_rng(b.get('character_level'))} | {_rng(b.get('character_xp'))} | {_rng(b.get('character_xp_debt'))} | {_rng(b.get('composite'))} |"
        )
    lines += [
        f"- Residual (the parts telescope, so they add up exactly by construction): {p.get('residual') or 'none'}.",
        "- A date counts once per part it moves; a date can move in several parts (privacy and method both), so the part "
        "counts do not add up to the date count.",
        f"- UNATTRIBUTED (a method-part public change on a date where no ladder step changed the private chain on that date "
        f"or before): {len(p.get('unattributed') or [])}.",
    ]
    fails = _att_failures(att)
    lines.append(f"- **RUN FAILED: {'; '.join(fails)}.**" if fails else "- Checks: passed.")
    return lines


def _method_event_lines(att: dict) -> list:
    evs = _method_events(att)
    lines = [
        "The private method-1 chain's own level events, stored rows vs the plan, from the ladder's per-step `events`. The "
        "privacy fix does not touch the private rows, so every row here is the METHOD revision. Mind is not public under any "
        "method and is left out.",
        "",
        "| date | who | event | level | change | first ladder step | served publicly before |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in evs:
        lines.append(
            f"| {r['date']} | {r['who']} | {r['event']} | {r['level']} | {r['change']} | {r['first_cause']} | "
            f"{'yes' if r['served_before'] else 'no'} |"
        )
    return lines if evs else ["- none"]


def summary_md(c: dict, preliminary: bool) -> str:
    p, pub, sc, ev, pr, att = c["private"], c["public"], c["scores"], c["events"], c["privacy"], c["attribution"]
    sd = p["stress_days"]
    freeze = sd.get("sick_day_frozen_copies") or []
    stored = sd.get("stored_with_stress")
    total = len(stored) if isinstance(stored, list) else int(stored or 0)
    breaches = c["protected_breaches"]
    lines = [
        "# Character recompute — COMBINED dry run" + (" (PRELIMINARY — not the dry run for approval)" if preliminary else ""),
        "",
        (
            f"**SLEEP / MOVEMENT EVENTS LOST OR MOVED: {len(breaches)} — this breaches the owner's condition; he must decide: "
            + "; ".join(breaches)
            + ".**"
            if breaches
            else "Sleep and movement events lost or moved: none (method or privacy)."
        ),
        "",
        (
            "**Run checks: FAILED — " + "; ".join(_att_failures(att) + S.failures(c, preliminary)) + ".**"
            if _att_failures(att) + S.failures(c, preliminary)
            else "Run checks: passed (attribution, reconciliation, duplicates, served-event dispositions, public composite, "
            "silent paths"
            + (
                "; the PRIVATE final-state check is PENDING — `planned_states` has not landed — which only a preliminary run " "allows)."
                if (c.get("final_state") or {}).get("status") == "pending"
                else ", private final state)."
            )
        ),
        "",
        f"Generated {c['generated_at']}. Nothing written. Private plan id `{p['plan_id']}` · public plan id `{pub['public_plan_id']}`.",
        "",
        "**CI:** the full CI suite has NOT run on this stack (the CI workflows trigger only on PRs to main). Ran locally: "
        + "; ".join(LOCAL_RUNS)
        + ".",
        "",
        "## Write counts and affected dates",
    ]
    for part, n in sorted(p["counts"].items()):
        if isinstance(n, dict):
            lines.append(
                f"- PRIVATE `{part}`: {n.get('rows_to_write')} writes of {n.get('rows_read')} rows ({n.get('attributes_changed')} attributes)"
            )
    lines.append(f"- PRIVATE affected dates: {p['counts'].get('dates_affected')} ({p['window']['start']} → {p['window']['end']})")
    for part, n in sorted(pub["by_partition"].items()):
        lines.append(f"- PUBLIC `{part.split('#SOURCE#')[-1]}`: {n} writes (only its `public` attribute)")
    lines += [
        f"- PUBLIC: plus the one correction-ledger item; {pub['skipped_unchanged']} unchanged projections not written.",
        "",
        "## Public score changes (before = served before the containment switch, the stored `public`; after = v3)",
        f"- Dates: {sc['dates']}. Overall level changes on {len(sc['level_changed_dates'])} "
        f"(change range {sc['character_level']['delta_range']}); XP on {sc['character_xp']['dates_changed']} "
        f"(range {sc['character_xp']['delta_range']}); composite on {sc['composite']['dates_changed']} (range {sc['composite']['delta_range']}).",
        f"- Dates whose level changes: {', '.join(sc['level_changed_dates']) or 'none'}.",
        f"- XP debt (a METHOD change, apart from the privacy change): {sc['xp_debt']['dates_with_debt_before']} dates carried debt "
        f"before; after, it is 0 on every date: {sc['xp_debt']['after_zero_on_every_date']}.",
        "- Per-date level / XP / composite are in the private manifests only (public/manifest.json, private/plan.json).",
        "",
        "## Attribution — which named change moves each public number",
        *_attribution_lines(att),
        "",
        "## Achievement events kept, moved, removed and reconstructed (public, on v3 — privacy and method together)",
    ]
    for who, t in sorted(ev["totals"].items()):
        lines.append(f"- {who}: KEPT {t['KEPT']} · MOVED {t['MOVED']} · REMOVED {t['REMOVED']} · ADDED {t['ADDED']}")
    lines += [
        f"- Sleep / movement / nutrition / metabolic events LOST: {ev['verbatim_losses']}; stored public per-date pillar events "
        f"differing from the recompute: {ev['stored_verbatim_mismatches']} (each is in the method table below).",
        f"- Events stored with internal provenance `reconstructed`: {ev['reconstructed']} (never served publicly, never an outbound event).",
    ]
    if c["since_previous"]["totals"]:
        lines += [
            f"- Changed since the previous dry run ({c['since_previous']['label']}): that run projected the STORED private "
            "rows and predates v3's public Relationships exclusion, so every difference is the method revision (the planned "
            "rows) or v3; an event matching a private-chain event names its first ladder step: "
            + "; ".join(c["since_previous"]["totals"])
            + ".",
            *(f"  - {x}" for x in c["since_previous"]["events"]),
        ]
    lines += [
        "",
        "## Pillar events that change because of the METHOD (not privacy)",
        *_method_event_lines(att),
        "",
        "## Privacy and provenance verification",
        f"- Planned public blocks checked as served: {pr['planned_blocks_served']}; withheld, provenance or planned-rest tokens: "
        f"{len(pr['withheld_or_provenance_tokens'])}; Mind / Relationships numbers: {len(pr['unscored_pillar_numbers'])}.",
        f"- Route walk (offline, synthetic rows, corrected-chain variant planted): {c['route_walk']}.",
        f"- Public correction ledger per-date rows: {pr['ledger_rows']} (no difference table is public).",
        "- The notice readers will see (owner-approved, exactly):",
        *(f"  > {ln}" if ln else "  >" for ln in (pr["notice"] or "").split("\n")),
        "",
        "## Final-state verification (the complete planned state, composite included)",
        *S.final_state_lines(c),
        "",
        "## Event reconciliation (57 added vs 58 reconstructed; duplicates; every served event accounted for)",
        *S.reconciliation_lines(c),
        "",
        "## What still responds to a poor measured day (XP debt is 0)",
        *S.responsiveness_lines(c),
        "",
        "## Planned rest: the public trade-off (the owner's pending decision)",
        *S.tradeoff_lines(c),
        "",
        "## The mood label",
        *S.mood_lines(c),
        "",
        "## Interrupted apply, side by side",
        *S.interrupted_apply_lines(),
        "",
        "## Write counts, baselines, backups, rollback, notification suppression and the approval commands",
        *S.operations_lines(c),
        "",
        "## Backup and rollback evidence",
        "- Both tools back up to S3 under `backups/` and re-read and hash it before their first write (details above).",
        "- Apply order: private `--apply --plan-in <plan> --phase sheets`, then `--phase receipts`; then public `--apply --plan-in "
        "<plan> --approved-public-plan-id <id> --phase pre-merge`, then `--phase post-merge`. Both `--verify` at 0.",
        "- Rollback order, from the S3 copies (each verifies its recorded sha256 first): PUBLIC first, phase by phase — "
        f"`backfill_public_variant.py --out <dir> --rollback s3://<bucket>/backups/character-public-recompute/{pub['public_plan_id']}/export_post-merge.json --apply`, "
        "then `…/export_pre-merge.json`; then PRIVATE — `recompute_character_private.py --out <dir> --rollback <its export> --apply` "
        "(its local export; the S3 copy is the same bytes).",
        f"- End-to-end fake-storage test ({E2E_TEST}: private apply → public apply → both verify 0 → rollback public → rollback "
        f"private → every item byte-identical): {'PASSED' if c['e2e']['passed'] else 'FAILED'} — {c['e2e']['result']}.",
        "",
        "## Open items the owner must know",
        f"- Stress days (the private tool's own accounting, `stress_days.accounting`): {sd.get('accounting')}.",
        f"- Stress days: {total} = {total - len(freeze)} independently computed day(s) whose stored Mind includes a "
        f"stress contribution the revised method holds out, plus {len(freeze)} sick-day freeze row(s) "
        f"({', '.join(freeze) or 'none'}) that copy the previous day's record verbatim and are rewritten from the recomputed "
        f"previous day. Definition: {sd.get('definition')}",
        "- Approval and apply must fall in ONE nightly cycle: both tools refuse once a newer stored sheet exists.",
        "- #6096 landing first would change the plan (re-run, re-approve).",
        "- Unexercised without a production write (stated by the private preflight, verbatim in the backup section): the "
        "conditional put itself and write permission at request time.",
        "",
    ]
    return "\n".join(lines)


def build(
    out: str,
    preliminary: bool,
    generated_at: str,
    e2e: dict,
    route_walk: Optional[dict],
    previous: Optional[str] = None,
    silent: Optional[dict] = None,
) -> dict:
    priv = json.load(open(os.path.join(out, "private", "plan.json"), encoding="utf-8"))
    pman = json.load(open(os.path.join(out, "public", "manifest.json"), encoding="utf-8"))
    old = json.load(open(previous, encoding="utf-8")) if previous else None
    lc = pman["level_credit"]
    att = pman.get("attribution") or {}
    return {
        "generated_at": generated_at,
        "private": {k: priv[k] for k in ("plan_id", "counts", "window", "stress_days")},
        "public": {
            "public_plan_id": pman["plan"]["public_plan_id"],
            "private_plan_id": pman["plan"]["private_plan_id"],
            "by_partition": pman["plan"]["by_partition"],
            "skipped_unchanged": len(pman["plan"]["skipped_unchanged"]),
        },
        "scores": score_changes(pman),
        "attribution": att,
        "protected_breaches": protected_breaches(att, lc["events"]),
        "events": {
            "totals": lc["events"]["totals"],
            "verbatim_losses": len(lc["verbatim_losses"]),
            "stored_verbatim_mismatches": len(lc["stored_verbatim_mismatches"]),
            "reconstructed": lc.get("reconstructed_events_marked", 0),
        },
        "since_previous": {
            "label": os.path.basename(os.path.dirname(previous)) if previous else None,
            "totals": _totals_delta(old, lc),
            "events": event_deltas(old, lc["events"], _method_events(att)),
        },
        "privacy": privacy_checks(os.path.join(out, "public")),
        "verification": pman.get("verification") or {},
        "final_state": S.final_state(pman),
        "baselines": S.baselines(pman),
        "silent_tests": silent,
        "route_walk": route_walk,
        "e2e": e2e,
    }


def main(argv: list) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", required=True, help="directory OUTSIDE the repo")
    ap.add_argument("--preliminary", action="store_true")
    ap.add_argument("--skip-tests", action="store_true", help="skip the end-to-end fake-storage test and the route walk")
    ap.add_argument("--previous", help="a previous public dry run's manifest.json (e.g. #6283's) — the event deltas since it")
    args = ap.parse_args(argv)
    out = _outside_repo(args.out)
    os.makedirs(os.path.join(out, "private"), exist_ok=True)
    os.makedirs(os.path.join(out, "public"), exist_ok=True)
    plan_path = os.path.join(out, "private", "plan.json")
    step = ["scripts/recompute_character_private.py", "--out", os.path.join(out, "private"), "--plan-out", plan_path]
    cp = _run(step + (["--preliminary"] if args.preliminary else []))
    if cp.returncode != 0:
        print(f"private dry run failed:\n{cp.stderr[-2000:]}", file=sys.stderr)
        return 1
    cp = _run(["scripts/backfill_public_variant.py", "--out", os.path.join(out, "public"), "--plan-in", plan_path, "--skip-routes"])
    if cp.returncode != 0:
        print(f"public dry run failed:\n{cp.stderr[-2000:]}", file=sys.stderr)
        return 1
    e2e = {"passed": False, "result": "skipped (--skip-tests)"} if args.skip_tests else e2e_test()
    walk = None if args.skip_tests else synthetic_route_walk()
    generated = json.load(open(os.path.join(out, "public", "manifest.json"), encoding="utf-8"))["generated_at"]
    silent = None if args.skip_tests else S.run_silent_tests()
    combined = build(out, args.preliminary, generated, e2e, walk, args.previous, silent)
    combined["preflight"] = S.preflights(out, plan_path, combined["public"]["public_plan_id"])
    with open(os.path.join(out, "combined.json"), "w", encoding="utf-8") as fh:
        json.dump(combined, fh, indent=1, sort_keys=True, default=str)
    with open(os.path.join(out, "COMBINED_SUMMARY.md"), "w", encoding="utf-8") as fh:
        fh.write(summary_md(combined, args.preliminary))
    fails = _att_failures(combined["attribution"]) + S.failures(combined, args.preliminary)
    state = "FAILED: " + "; ".join(fails) if fails else "checks passed"
    print(
        f"COMBINED DRY RUN — nothing written. private {combined['private']['plan_id']} · public {combined['public']['public_plan_id']} · {state}"
    )
    return 2 if fails else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv[1:]))
