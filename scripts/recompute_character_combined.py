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
STAMPS = frozenset({"method_version_stamp", "recompute_provenance"})
METHOD_CAUSES = (
    "relationships_exclusion",
    "journal_frequency",
    "model_values",
    "xp_debt",
    "rest_decay",
    "missing_data",
    "stress_days",
    "tree_switch_residual",
    "replay_residual",
)
PRIVACY_CAUSES = {
    "mind_unscored": "Mind is not scored in public (its inputs are private)",
    "restraint_inputs_removed": "restraint-habit inputs removed (the component and the effect that read them)",
    "food_delivery_modifier": "the food-delivery multiplier on Nutrition not applied",
}
PUBLIC_FIELDS = ("character_level", "character_tier", "character_xp", "character_xp_debt", "composite", "character_mood", "level_events")


def _outside_repo(path: str) -> str:
    real = os.path.realpath(path)
    if real == os.path.realpath(ROOT) or real.startswith(os.path.realpath(ROOT) + os.sep):
        raise SystemExit(f"REFUSED: --out {path} is inside the repo — the outputs carry real values")
    return real


def _run(cmd: list) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, *cmd], cwd=ROOT, capture_output=True, text=True)


# ── attribution ───────────────────────────────────────────────────────────────────────────────────────────────────


def privacy_causes(stored_public: Any) -> list:
    """The privacy causes a date's stored (served-before) public block carries: a scored Mind, a restraint input, the
    food-delivery multiplier."""
    from health import character_privacy as CP

    pv = stored_public if isinstance(stored_public, dict) else {}
    out = []
    mind = pv.get("pillar_mind") or {}
    if isinstance(mind, dict) and (mind.get("level") is not None or mind.get("raw_score") is not None):
        out.append("mind_unscored")
    comps = mind.get("components") if isinstance(mind, dict) else None
    if (isinstance(comps, dict) and any(k in CP.RESTRAINT_COMPONENTS for k in comps)) or any(
        CP.effect_reads_restraint(e) for e in pv.get("active_effects") or []
    ):
        out.append("restraint_inputs_removed")
    nut = pv.get("pillar_nutrition") or {}
    mod = (nut.get("raw_modifier") or (nut.get("components") or {}).get("_modifier")) if isinstance(nut, dict) else None
    if isinstance(mod, dict) and mod.get("source") == "food_delivery":
        out.append("food_delivery_modifier")
    return out


def _changed(pair: Any) -> bool:
    return isinstance(pair, list) and len(pair) == 2 and pair[0] != pair[1]


def attribute(plan: dict, public_manifest: dict) -> dict:
    """Every date whose public served values change, with its named causes: privacy (from the stored public block the
    plan carries unchanged) and method (the private plan's own per-row causes, its stamps aside)."""
    import recompute_character_private_apply as A
    from health import character_privacy as CP

    sheet_rows = {r["date"]: r for r in plan["rows"] if r["pk"].endswith("#SOURCE#character_sheet")}
    pillar_fields = [
        k for k in (public_manifest["character"][0] if public_manifest.get("character") else {}) if k.endswith(("_level", "_score"))
    ]
    by_cause: dict = {}
    dates, unattributed = [], []
    for row in public_manifest.get("character") or []:
        d = row["date"]
        if not any(_changed(row.get(f)) for f in PUBLIC_FIELDS + tuple(pillar_fields)):
            continue
        dates.append(d)
        prow = sheet_rows.get(d) or {}
        stored_public = (A.as_float(prow["planned_item"]) if prow.get("planned_item") else {}).get(CP.PUBLIC_KEY)
        causes = privacy_causes(stored_public) + sorted(c for c in prow.get("causes") or [] if c not in STAMPS)
        if not causes:
            unattributed.append(d)
        for c in causes:
            by_cause.setdefault(c, []).append(d)
    return {"changed_dates": dates, "by_cause": {c: len(v) for c, v in sorted(by_cause.items())}, "unattributed": unattributed}


# ── the parts of the summary ─────────────────────────────────────────────────────────────────────────────────────


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
        tokens = [t.lower() for t in CP.withheld_public_tokens(json.load(fh))] + [k.lower() for k in CP.PROVENANCE_KEYS]
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


def summary_md(c: dict, preliminary: bool) -> str:
    p, pub, sc, at, ev, pr = c["private"], c["public"], c["scores"], c["attribution"], c["events"], c["privacy"]
    sd = p["stress_days"]
    freeze = sd.get("sick_day_frozen_copies") or []
    stored = sd.get("stored_with_stress")
    total = len(stored) if isinstance(stored, list) else int(stored or 0)
    computed = total - len(freeze)
    lines = [
        "# Character recompute — COMBINED dry run" + (" (PRELIMINARY — not the dry run for approval)" if preliminary else ""),
        "",
        f"Generated {c['generated_at']}. Nothing written. Private plan id `{p['plan_id']}` · public plan id `{pub['public_plan_id']}`.",
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
        "## Attribution — every public change traced to named causes",
        f"- Dates with a public change: {len(at['changed_dates'])}; UNATTRIBUTED: {len(at['unattributed'])}"
        + (f" ({', '.join(at['unattributed'])}) — RUN FAILED" if at["unattributed"] else " — none."),
    ]
    for cause, n in at["by_cause"].items():
        kind = "privacy" if cause in PRIVACY_CAUSES else "method"
        lines.append(f"  - {cause} ({kind}): {n} dates")
    lines += ["", "## Achievement events kept, moved, removed and reconstructed (on v3)"]
    for who, t in sorted(ev["totals"].items()):
        lines.append(f"- {who}: KEPT {t['KEPT']} · MOVED {t['MOVED']} · REMOVED {t['REMOVED']} · ADDED {t['ADDED']}")
    lines += [
        f"- Sleep / movement / nutrition / metabolic events LOST: {ev['verbatim_losses']}; stored per-date pillar events "
        f"differing: {ev['stored_verbatim_mismatches']}.",
        f"- Events stored with internal provenance `reconstructed`: {ev['reconstructed']} (never served publicly, never an outbound event).",
        "",
        "## Privacy and provenance verification",
        f"- Planned public blocks checked as served: {pr['planned_blocks_served']}; withheld or provenance tokens: "
        f"{len(pr['withheld_or_provenance_tokens'])}; Mind / Relationships numbers: {len(pr['unscored_pillar_numbers'])}.",
        f"- Route walk (offline, synthetic rows, corrected-chain variant planted): {c['route_walk']}.",
        f"- Public correction ledger per-date rows: {pr['ledger_rows']} (no difference table is public).",
        "- The notice readers will see (owner-approved, exactly):",
        *(f"  > {ln}" if ln else "  >" for ln in (pr["notice"] or "").split("\n")),
        "",
        "## Backup and rollback evidence",
        "- PRIVATE pre-image: a local export (+ `.sha256`) and `s3://…/backups/character-private-recompute/<plan_id>/<phase>-<ts>/export.json`, "
        "both re-read and hashed before the first write.",
        "- PUBLIC pre-image: `export_<phase>_<ts>.json` in the public --out, written before the first write.",
        "- Apply order: private `--apply --plan-in <plan> --phase sheets`, then `--phase receipts`; then public `--apply --plan-in "
        "<plan> --approved-public-plan-id <id> --phase pre-merge`, then `--phase post-merge`. Both `--verify` at 0.",
        "- Rollback order: PUBLIC first (`backfill_public_variant.py --rollback <export> --apply`), then PRIVATE "
        "(`recompute_character_private.py --rollback <export> --apply`).",
        f"- End-to-end fake-storage test ({E2E_TEST}: private apply → public apply → both verify 0 → rollback public → rollback "
        f"private → every item byte-identical): {'PASSED' if c['e2e']['passed'] else 'FAILED'} — {c['e2e']['result']}.",
        "",
        "## Open items the owner must know",
        f"- Stress days: {total} = {computed} independently computed day(s) whose stored Mind includes a "
        f"stress contribution the revised method holds out, plus {len(freeze)} sick-day freeze row(s) "
        f"({', '.join(freeze) or 'none'}) that copy the previous day's record verbatim and are rewritten from the recomputed "
        f"previous day. Definition: {sd.get('definition')}",
        "- Approval and apply must fall in ONE nightly cycle: both tools refuse once a newer stored sheet exists.",
        "- #6096 landing first would change the plan (re-run, re-approve).",
        "- The one remaining unexercised safeguard: the private backup's conditional S3 put (`IfNoneMatch`) has not run against real AWS.",
        "",
    ]
    return "\n".join(lines)


def build(out: str, preliminary: bool, generated_at: str, e2e: dict, route_walk: Optional[dict]) -> dict:
    priv = json.load(open(os.path.join(out, "private", "plan.json"), encoding="utf-8"))
    pman = json.load(open(os.path.join(out, "public", "manifest.json"), encoding="utf-8"))
    lc = pman["level_credit"]
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
        "attribution": attribute(priv, pman),
        "events": {
            "totals": lc["events"]["totals"],
            "verbatim_losses": len(lc["verbatim_losses"]),
            "stored_verbatim_mismatches": len(lc["stored_verbatim_mismatches"]),
            "reconstructed": lc.get("reconstructed_events_marked", 0),
        },
        "privacy": privacy_checks(os.path.join(out, "public")),
        "route_walk": route_walk,
        "e2e": e2e,
    }


def main(argv: list) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", required=True, help="directory OUTSIDE the repo")
    ap.add_argument("--preliminary", action="store_true")
    ap.add_argument("--skip-tests", action="store_true", help="skip the end-to-end fake-storage test and the route walk")
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
    combined = build(out, args.preliminary, generated, e2e, walk)
    with open(os.path.join(out, "combined.json"), "w", encoding="utf-8") as fh:
        json.dump(combined, fh, indent=1, sort_keys=True, default=str)
    with open(os.path.join(out, "COMBINED_SUMMARY.md"), "w", encoding="utf-8") as fh:
        fh.write(summary_md(combined, args.preliminary))
    print(f"COMBINED DRY RUN — nothing written. private {combined['private']['plan_id']} · public {combined['public']['public_plan_id']}")
    return 2 if combined["attribution"]["unattributed"] else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv[1:]))
