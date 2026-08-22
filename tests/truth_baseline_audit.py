#!/usr/bin/env python3
"""
truth_baseline_audit.py — the reader-truth debt ledger (#2956, the #2941 aftermath).

WHY THIS EXISTS. #2940 armed the reader-truth gate (dark since 2026-06-05) in one
step, with no baseline of the 93-page surface. Its first armed run caught a real
bug (#2941, the day-stamp clock); the run that shipped that fix then failed on
**16 standing findings about content and API data that predate the deploy** —
so every future `site/**` merge deploys → fails → auto-rolls-back, regardless of
its own diff. The gate conflates "this deploy broke truth" with "the site
carries standing truth debt". This module separates them, on the exact contract
`tests/a11y_audit.py` (#1433) established:

  - NEW high-severity finding (page + category not in the committed baseline)
      → GATES: the page FAILs the sweep, same as before this module existed.
  - Baselined finding (page + category in tests/truth_baseline.json)
      → recorded honestly as a warning naming its tracking issue — visible on
        every run, never hidden, never gating. The baseline is the triaged
        debt ledger, not an excuse file: every entry MUST carry an issue ref
        (test_truth_baseline_audit.py reds the committed file otherwise).
  - Baselined entry no longer observed ("fixed")
      → reported so the ledger can SHRINK — same #1990 explicit-consumer
        lesson as a11y's shrink_candidates.

GATE KEY: (page path, category) — deliberately NOT the finding note. The notes
are LLM prose and rephrase across runs (#2613 measured one finding wearing
three phrasings on consecutive nights); keying on them would make the ledger
rot on every run exactly the way pixel-diffing did (#1428). The coarseness is
the same trade a11y made with rule ids: a genuinely NEW contradiction on a page
already carrying one is masked until the ledger entry drains — which is why
every entry carries an issue ref and the shrink report keeps the pressure on.

Baseline update path (DELIBERATE, REVIEWED — never auto-regenerated):
    python3 tests/visual_qa.py --reader-truth --update-truth-baseline
rewrites entries for the pages the sweep drove (a --page run touches only that
page; the rest is preserved). Fresh entries land as issue="UNTRIAGED", and the
unit suite REDS the committed file on any UNTRIAGED entry — so the update can
never be committed without a human (or driver session) filing/naming the issue.
Added entries are newly accepted debt (rare, argued for in the PR); removed
entries are fixes shrinking the ledger.

Pure logic, no Playwright/Bedrock imports — test_truth_baseline_audit.py runs
it offline.
"""

import json
import os
from datetime import datetime, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
BASELINE_PATH = os.path.join(_HERE, "truth_baseline.json")

# Only "high" reader-truth findings gate (visual_ai_qa.assess_reader_truth),
# so only high findings enter the ledger; med/low were never gating.
GATING_SEVERITIES = ("high",)

UNTRIAGED = "UNTRIAGED"


def load_baseline(path=None):
    """Load the committed ledger; a missing file is an empty baseline."""
    path = path or BASELINE_PATH
    if not os.path.exists(path):
        return {"_meta": {}, "pages": {}}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    data.setdefault("pages", {})
    return data


def _entry_for(baseline, page_path, category):
    for row in baseline.get("pages", {}).get(page_path, []):
        if row.get("category") == category:
            return row
    return None


def gate_finding(finding, baseline):
    """Classify ONE reader-truth finding against the ledger. Pure.

    Returns "new" (gates — high severity, not baselined), "baselined"
    (recorded, never gates; caller renders the issue ref), or "advisory"
    (med/low — never gated, unchanged by this module).
    """
    if finding.get("severity") not in GATING_SEVERITIES:
        return "advisory"
    if _entry_for(baseline, finding.get("page", ""), finding.get("category", "")):
        return "baselined"
    return "new"


def baselined_issue(finding, baseline):
    """The tracking-issue ref for a baselined finding ('' when not baselined)."""
    row = _entry_for(baseline, finding.get("page", ""), finding.get("category", ""))
    return (row or {}).get("issue", "")


def shrink_candidates(observed_findings, baseline):
    """{page: [category, …]} baselined but NOT observed this run — drainable.

    Only meaningful for a full-surface sweep; callers doing a --page subset
    should pass swept_pages so unswept pages are never reported as fixed.
    """
    observed = {(f.get("page", ""), f.get("category", "")) for f in observed_findings}
    out = {}
    for page, rows in baseline.get("pages", {}).items():
        gone = [r["category"] for r in rows if (page, r["category"]) not in observed]
        if gone:
            out[page] = sorted(gone)
    return out


def untriaged_entries(baseline):
    """[(page, category), …] whose issue ref is missing/UNTRIAGED — commit-blockers."""
    bad = []
    for page, rows in baseline.get("pages", {}).items():
        for r in rows:
            if not r.get("issue") or r.get("issue") == UNTRIAGED:
                bad.append((page, r.get("category", "")))
    return sorted(bad)


def update_baseline(observed_by_path, path=None):
    """Rewrite ledger entries for the swept pages — the DELIBERATE path.

    observed_by_path: {page_path: [finding, …]} for pages the sweep actually
    drove (findings of any severity; only GATING_SEVERITIES are written).
    Pages observed clean are removed; unswept pages are preserved untouched.
    Existing entries keep their issue ref; fresh ones land UNTRIAGED (and the
    unit suite reds the committed file until they are triaged).
    """
    path = path or BASELINE_PATH
    baseline = load_baseline(path)
    for page_path, findings in observed_by_path.items():
        keep = {}
        for f in findings:
            if f.get("severity") not in GATING_SEVERITIES:
                continue
            cat = f.get("category", "")
            prior = _entry_for(baseline, page_path, cat)
            keep[cat] = {
                "category": cat,
                "issue": (prior or {}).get("issue", UNTRIAGED),
                "added": (prior or {}).get("added") or datetime.now(timezone.utc).date().isoformat(),
                # Context only — NEVER part of the gate key (notes rephrase per run, #2613).
                "note_sample": (f.get("note") or "")[:200],
            }
        if keep:
            baseline["pages"][page_path] = [keep[c] for c in sorted(keep)]
        else:
            baseline["pages"].pop(page_path, None)
    baseline["pages"] = {k: baseline["pages"][k] for k in sorted(baseline["pages"])}
    baseline["_meta"] = {
        "captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "note": (
            "Committed reader-truth debt ledger — honest capture of standing high findings per page. "
            "The gate reds only on NEW (page, category) high findings vs this file; baselined entries "
            "surface as warnings naming their issue every run. Update DELIBERATELY via "
            "`python3 tests/visual_qa.py --reader-truth --update-truth-baseline` and review the diff; "
            "every entry must carry a real issue ref (UNTRIAGED reds the unit suite). "
            "Never hand-grow, never auto-regenerate; hand-SHRINKING (deleting a fixed entry) is fine."
        ),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(baseline, f, indent=2)
        f.write("\n")
    return baseline
