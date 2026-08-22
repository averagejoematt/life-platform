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

WRITE SEVERITY IS SEVERITY-FREE (#2981). The write path records a (page,
category) pair observed at ANY severity; gating stays high-only at READ time
(gate_finding). It used to write only `high`, which made baselining a coin flip
on the oracle's grade for that run: the oracle's finding population is
non-stationary (#2613 measured one finding wearing three phrasings on
consecutive nights, and the 2026-08-21 rounds went 77 → 16 → 3 → 2 → 0), so a
deliberate `--update-truth-baseline` pass on a finding graded `med` that night
recorded NOTHING and printed "rewritten" anyway. The gate key was already
severity-free; now the ledger is too. A sub-gating entry is a pre-authorization:
when that pair next grades `high`, it is known standing debt, not a regression.

REPORT, NEVER A BARE SUCCESS LINE (#2981). update_baseline returns a report and
update_summary renders it — what was recorded, what was already there, what was
DROPPED. The drop line matters: the oracle is fail-soft (a page whose batch
errors yields no findings, #2973), and an errored page reads identically to a
clean one, so a baselining run after a partial oracle failure would silently
shrink the ledger. The summary makes that visible instead.

Pure logic, no Playwright/Bedrock imports — test_truth_baseline_audit.py runs
it offline.
"""

import json
import os
from datetime import datetime, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
BASELINE_PATH = os.path.join(_HERE, "truth_baseline.json")

# Only "high" reader-truth findings GATE (visual_ai_qa.assess_reader_truth).
# This is a READ-time property — the write path is severity-free (#2981).
GATING_SEVERITIES = ("high",)

# reader_truth_qa normalizes anything unrecognized to "low" before it gets here.
SEVERITY_ORDER = ("low", "med", "high")

UNTRIAGED = "UNTRIAGED"


def _severity_rank(severity):
    try:
        return SEVERITY_ORDER.index(severity)
    except ValueError:
        return 0


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
    drove. EVERY observed (page, category) pair is recorded regardless of
    severity (#2981) — gating stays high-only at read time, so a sub-gating
    entry is a pre-authorization, not a widened gate. Pages observed clean are
    removed; unswept pages are preserved untouched. Existing entries keep their
    issue ref and `added` date; fresh ones land UNTRIAGED (and the unit suite
    reds the committed file until they are triaged).

    Returns a REPORT (not the bare baseline) — render it with update_summary.
    Callers must not print a success line of their own: printing "rewritten"
    over a no-op is the #2981 defect this signature exists to make impossible.
    """
    path = path or BASELINE_PATH
    baseline = load_baseline(path)
    before = json.dumps(baseline.get("pages", {}), sort_keys=True)
    report = {"pages_swept": len(observed_by_path), "added": [], "kept": [], "dropped": []}
    if not observed_by_path:
        # Nothing was swept — do not even restamp `captured_at`, which would
        # dress a no-op as a fresh capture. update_summary says so out loud.
        report.update({"changed": False, "untriaged": untriaged_entries(baseline), "baseline": baseline, "path": path})
        return report

    for page_path, findings in observed_by_path.items():
        # One row per category: the highest severity observed for that pair this
        # run is what gets recorded as context (the pair itself is the key).
        worst = {}
        for f in findings:
            cat = f.get("category", "")
            prev = worst.get(cat)
            if prev is None or _severity_rank(f.get("severity", "low")) > _severity_rank(prev.get("severity", "low")):
                worst[cat] = f
        prior_cats = {r.get("category", "") for r in baseline.get("pages", {}).get(page_path, [])}
        rows = []
        for cat in sorted(worst):
            f = worst[cat]
            prior = _entry_for(baseline, page_path, cat)
            rows.append(
                {
                    "category": cat,
                    "issue": (prior or {}).get("issue", UNTRIAGED),
                    "added": (prior or {}).get("added") or datetime.now(timezone.utc).date().isoformat(),
                    # Context only — NEVER part of the gate key (severity is
                    # non-stationary, #2981; notes rephrase per run, #2613).
                    "severity_observed": f.get("severity", "low"),
                    "note_sample": (f.get("note") or "")[:200],
                }
            )
            (report["kept"] if prior else report["added"]).append(f"{page_path} [{cat}]")
        for cat in sorted(prior_cats - set(worst)):
            report["dropped"].append(f"{page_path} [{cat}]")
        if rows:
            baseline["pages"][page_path] = rows
        else:
            baseline["pages"].pop(page_path, None)

    baseline["pages"] = {k: baseline["pages"][k] for k in sorted(baseline["pages"])}
    baseline["_meta"] = {
        "captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "note": (
            "Committed reader-truth debt ledger — honest capture of standing findings per page. "
            "The gate reds only on NEW (page, category) HIGH findings vs this file; baselined entries "
            "surface as warnings naming their issue every run. Entries are recorded at any observed "
            "severity (#2981) — `severity_observed` is context, never part of the key. Update DELIBERATELY "
            "via `python3 tests/visual_qa.py --reader-truth --update-truth-baseline` and review the diff; "
            "every entry must carry a real issue ref (UNTRIAGED reds the unit suite). "
            "Never hand-grow, never auto-regenerate; hand-SHRINKING (deleting a fixed entry) is fine."
        ),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(baseline, f, indent=2)
        f.write("\n")

    report["changed"] = json.dumps(baseline["pages"], sort_keys=True) != before
    report["untriaged"] = untriaged_entries(baseline)
    report["baseline"] = baseline
    report["path"] = path
    return report


def update_summary(report):
    """Operator-visible lines for an --update-truth-baseline run (#2981).

    NEVER a bare success line. A run that recorded nothing says so, in those
    words — the old path printed "truth baseline rewritten" whether or not a
    single entry was written, which is what let a deliberate baselining attempt
    fail silently and hold the site publish path on debt already acknowledged.
    """
    rel, root = report.get("path") or BASELINE_PATH, os.path.dirname(_HERE)
    if rel.startswith(root + os.sep):
        rel = os.path.relpath(rel, root)
    if not report.get("pages_swept"):
        return ["⚠ truth baseline NOT updated — the sweep captured prose for 0 page(s), so nothing was recorded (#2981)"]

    lines = [f"truth baseline: {report['pages_swept']} page(s) swept → {rel}"]
    added, kept, dropped = report.get("added", []), report.get("kept", []), report.get("dropped", [])
    if added:
        lines.append(f"  + recorded {len(added)} new entr{'y' if len(added) == 1 else 'ies'}: {', '.join(sorted(added))}")
    if kept:
        lines.append(f"  = {len(kept)} entr{'y' if len(kept) == 1 else 'ies'} already present (issue ref + added-date preserved)")
    if dropped:
        # Fail-soft oracle (#2973): an errored page yields no findings and reads
        # exactly like a clean one, so a drop is never self-evidently a fix.
        lines.append(
            f"  − dropped {len(dropped)} entr{'y' if len(dropped) == 1 else 'ies'} (observed clean this run): "
            f"{', '.join(sorted(dropped))} — confirm the page's assessment actually RAN before committing"
        )
    if not report.get("changed"):
        lines.append("  no change — the ledger already matched what this run observed; NOTHING was recorded")
    if report.get("untriaged"):
        n = len(report["untriaged"])
        lines.append(
            f"  ⚠ {n} UNTRIAGED entr{'y' if n == 1 else 'ies'} — name the tracking issue for each before committing "
            "(test_truth_baseline_audit.py reds the file until you do)"
        )
    return lines
