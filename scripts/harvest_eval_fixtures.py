#!/usr/bin/env python3
"""harvest_eval_fixtures.py — the monthly harvest loop for the golden-surface packs (#812, consumes #744 retention).

The runtime ADR-104 gates now RETAIN every fired verdict/regeneration pair
(`lambdas/eval_retention.py`, DDB `EVALRET#<surface>`). This script turns that
live stream into new eval fixtures, deterministically (ADR-105: no LLM anywhere
in the loop — cost $0, well inside the issue's ~$2/mo envelope):

  - a flagged DRAFT  → a CANARY candidate: a real fault the live gate caught,
    with `expect_checks` derived from the recorded finding types. Replayed
    through the harness in generic mode; a candidate the gate would no longer
    catch is REJECTED (it would poison the pack with an uncatchable canary).
  - a CORRECTED final (verdict flagged_corrected) → a GOLDEN candidate: a real
    output that passed the gate after one rewrite. Replayed; a candidate that
    now draws findings is rejected.

Candidates are written to a JSON file for HUMAN review — they are NOT committed
automatically. Live drafts can contain reader questions and unpublished
narrative, and this repo is public, so a person (or an attended session) reviews
for privacy/quality and then promotes with `--promote <file>`, which appends the
accepted candidates to `tests/fixtures/golden_surfaces/<surface>/{golden,canaries}.json`
(re-validating the whole pack afterwards).

Runs monthly via `.github/workflows/eval-harvest.yml` (read-only OIDC role:
dynamodb:Query LeadingKeys EVALRET#*), or locally with any read credentials:

    python3 scripts/harvest_eval_fixtures.py --days 35 --out /tmp/candidates.json
    python3 scripts/harvest_eval_fixtures.py --promote /tmp/candidates.json
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "tests"))

import golden_surface_eval as harness  # noqa: E402  (also sets the hermetic env defaults)

# finding type → the harness check label a canary must expect
_CHECK_BY_TYPE = {
    "contradiction": "grounding_contradiction",
    "fabricated_number": "evidence_ceiling",
    "causal_language": "causal_language",
    "memoir_gate": "evidence_ceiling",  # refined below from the detail text
}


def _expect_checks(surface, findings):
    checks = set()
    for f in findings or []:
        ftype = f.get("type")
        if ftype == "memoir_gate":
            detail = f.get("detail") or ""
            if detail == "empty":
                checks.add("empty_output")
            elif detail.startswith("fabricated numbers"):
                checks.add("evidence_ceiling")
            else:
                checks.add("miss_dodged")
        elif ftype in _CHECK_BY_TYPE:
            checks.add(_CHECK_BY_TYPE[ftype])
    return sorted(checks)


def _candidate_id(kind, surface, created_at, i):
    stamp = (created_at or "")[:10].replace("-", "")
    return f"harvest_{kind}_{surface}_{stamp}_{i}"


def build_candidates(records_by_surface):
    """Deterministically convert retention records into validated candidates.

    Returns {"canaries": [...], "golden": [...], "rejected": [...]} — every
    candidate already replayed through the harness's generic mode."""
    out = {"canaries": [], "golden": [], "rejected": []}
    for surface, records in records_by_surface.items():
        for i, rec in enumerate(records):
            base_inputs = {"allowed": rec.get("allowed") or [], "facts": rec.get("facts")}
            created = rec.get("_created_at")
            prov = f"HARVESTED from live gate event: DDB pk=EVALRET#{surface} sk={rec.get('_sk')} ({rec.get('verdict')})."

            # canary candidate from the flagged draft
            draft = (rec.get("draft") or "").strip()
            checks = _expect_checks(surface, rec.get("findings"))
            if draft and checks and checks != ["empty_output"]:
                cand = {
                    "id": _candidate_id("canary", surface, created, i),
                    "surface": surface,
                    "mode": "generic",
                    "mutation": "HARVESTED REAL FAULT (live gate flag, retained via #744): "
                    + "; ".join(str(f.get("detail")) for f in (rec.get("findings") or [])[:3]),
                    "provenance": prov,
                    "inputs": base_inputs,
                    "mutated_output": draft,
                    "expect_checks": checks,
                }
                caught = {f["check"] for f in harness.evaluate_fixture(surface, cand, draft)}
                if set(checks).issubset(caught):
                    out["canaries"].append(cand)
                else:
                    out["rejected"].append({"id": cand["id"], "reason": f"replay caught {sorted(caught)}, expected {checks}"})

            # golden candidate from a corrected final
            final = (rec.get("final") or "").strip()
            if final and rec.get("verdict") == "flagged_corrected":
                cand = {
                    "id": _candidate_id("golden", surface, created, i),
                    "surface": surface,
                    "mode": "generic",
                    "provenance": prov + " Corrected output that passed the live gate after one rewrite.",
                    "inputs": base_inputs,
                    "reference_output": final,
                }
                findings = harness.evaluate_fixture(surface, cand, final)
                if not findings:
                    out["golden"].append(cand)
                else:
                    out["rejected"].append({"id": cand["id"], "reason": f"replay drew findings: {[f.get('detail') for f in findings][:3]}"})
    return out


def harvest(days, out_path):
    import eval_retention

    records_by_surface = {s: eval_retention.fetch(s, since_days=days) for s in eval_retention.SURFACES}
    n_records = sum(len(v) for v in records_by_surface.values())
    result = build_candidates(records_by_surface)
    doc = {
        "harvested_at": datetime.now(timezone.utc).isoformat(),
        "window_days": days,
        "records_seen": n_records,
        "per_surface_records": {s: len(v) for s, v in records_by_surface.items()},
        **result,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=1, ensure_ascii=False)
    print(
        f"harvest: {n_records} retained event(s) over {days}d → "
        f"{len(result['canaries'])} canary + {len(result['golden'])} golden candidate(s), "
        f"{len(result['rejected'])} rejected → {out_path}"
    )
    print("NEXT: human privacy/quality review, then: python3 scripts/harvest_eval_fixtures.py --promote " + out_path)
    return doc


def promote(candidates_path):
    """Append reviewed candidates to the fixture packs, then re-validate everything."""
    with open(candidates_path, encoding="utf-8") as f:
        doc = json.load(f)
    added = 0
    for kind, filename in (("golden", "golden.json"), ("canaries", "canaries.json")):
        for cand in doc.get(kind) or []:
            path = os.path.join(harness.FIXTURE_ROOT, cand["surface"], filename)
            with open(path, encoding="utf-8") as f:
                pack = json.load(f)
            if any(fx["id"] == cand["id"] for fx in pack):
                print(f"skip (already present): {cand['id']}")
                continue
            pack.append(cand)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(pack, f, indent=1, ensure_ascii=False)
            added += 1
            print(f"promoted {cand['id']} → {os.path.relpath(path, _REPO)}")
    report = harness.run()
    print(harness.ops_line(report))
    if report["verdict"] != harness.OK:
        print("PROMOTION BROKE THE PACKS — revert or fix before committing.", file=sys.stderr)
        return 1
    print(f"{added} candidate(s) promoted; packs re-validated {report['verdict']}.")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Harvest live ADR-104 gate events into golden/canary candidates (#812)")
    ap.add_argument("--days", type=int, default=35, help="lookback window (default 35 — monthly cadence + slack)")
    ap.add_argument("--out", default="/tmp/eval_fixture_candidates.json", help="candidate file to write")
    ap.add_argument("--promote", metavar="FILE", help="append reviewed candidates from FILE to the fixture packs")
    args = ap.parse_args(argv)

    if args.promote:
        return promote(args.promote)
    harvest(args.days, args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
