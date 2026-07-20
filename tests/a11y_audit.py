#!/usr/bin/env python3
"""
a11y_audit.py — axe-core accessibility audit for the Playwright sweep (#1433).

Runs the vendored axe-core bundle (tests/vendor/axe.min.js, pinned — see its
header for version/provenance/license) against each page tests/visual_qa.py
drives, and gates on NEW serious/critical violations versus a committed
baseline (tests/a11y_baseline.json):

  - NEW serious/critical violation (rule id not baselined for that page)
      → a GATING issue: the page FAILs the sweep, same as any render break.
  - Baselined violation (any impact)
      → recorded honestly in the result + a per-page warning — visible on
        every run, never hidden, never gating. The baseline is the triaged
        debt ledger, not an excuse file.
  - New minor/moderate violation
      → advisory warning only (recorded; the gate is scoped to the
        serious/critical impacts by the issue's acceptance criteria).
  - Baselined rule no longer observed ("fixed")
      → reported so the baseline can SHRINK — see the update path below.

Granularity is (page path, axe rule id): node counts and CSS targets are
recorded for context but deliberately NOT part of the gate key — daily data
changes move node counts around, and gating on them would make the sweep
flaky in exactly the way pixel-diffing was (#1428's lesson).

Baseline update path (DELIBERATE, REVIEWED — never auto-regenerated):
    python3 tests/visual_qa.py --update-baseline
rewrites tests/a11y_baseline.json from what the sweep just observed, for the
pages it swept (a --page/--max-tier run touches only those pages' entries;
the rest of the baseline is preserved). The run still reports NEW violations
red so nothing is silently absorbed — the committed baseline diff is the
review surface: added entries are new accepted debt (should be rare and
argued for in the PR), removed entries are fixes shrinking the ledger.

This module has NO Playwright import — run_axe() takes an already-open page
object, and the gate/baseline logic is pure so tests/test_a11y_audit.py can
exercise it offline (a Playwright import at module scope would red the whole
unit suite at collection — memory: reference_test_layer_dep_import_collection_red).
"""

import json
import os
from datetime import datetime, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
AXE_JS_PATH = os.path.join(_HERE, "vendor", "axe.min.js")
BASELINE_PATH = os.path.join(_HERE, "a11y_baseline.json")

# Pinned vendored version — must match the /*! axe vX.Y.Z */ header in
# AXE_JS_PATH (test_a11y_audit asserts this so a bump can't be half-done).
AXE_VERSION = "4.12.1"

# The gate is scoped to these axe impact levels (#1433 acceptance criteria).
GATING_IMPACTS = ("critical", "serious")

_RUN_AXE_JS = """async () => {
    const r = await axe.run(document, {resultTypes: ['violations']});
    return r.violations.map(v => ({
        id: v.id,
        impact: v.impact,
        help: v.help,
        helpUrl: v.helpUrl,
        nodes: v.nodes.length,
        targets: v.nodes.slice(0, 3).map(n => (n.target || []).join(' ')),
    }));
}"""


def run_axe(page):
    """Inject the vendored axe bundle (once per page) and return its violations.

    Returns a list of {id, impact, help, helpUrl, nodes, targets} dicts.
    Injection is add_script_tag(content=…) — the live site's CSP carries
    script-src 'unsafe-inline' so this works today; if the CSP ever tightens,
    the raised exception surfaces as an explicit "audit did not run" warning
    in visual_qa (never a silent pass). Raises on injection/run failure.
    """
    if not page.evaluate("() => typeof window.axe !== 'undefined'"):
        with open(AXE_JS_PATH, encoding="utf-8") as f:
            page.add_script_tag(content=f.read())
    return page.evaluate(_RUN_AXE_JS)


def load_baseline(path=None):
    """Load the committed baseline; a missing file is an empty baseline."""
    path = path or BASELINE_PATH
    if not os.path.exists(path):
        return {"_meta": {}, "pages": {}}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    data.setdefault("pages", {})
    return data


def gate_findings(page_path, violations, baseline):
    """Classify one page's observed violations against the baseline.

    Pure (no I/O). Returns:
        {"new":       [violation, …]   # serious/critical, NOT baselined → GATES
         "baselined": [violation, …]   # rule id in the baseline (any impact)
         "advisory":  [violation, …]   # new minor/moderate — recorded, no gate
         "fixed":     [rule_id, …]     # baselined but no longer observed
         "observed":  [violation, …]}  # everything found, for --update-baseline
    """
    base_ids = {v["id"] for v in baseline.get("pages", {}).get(page_path, [])}
    observed_ids = {v["id"] for v in violations}
    return {
        "new": [v for v in violations if v.get("impact") in GATING_IMPACTS and v["id"] not in base_ids],
        "baselined": [v for v in violations if v["id"] in base_ids],
        "advisory": [v for v in violations if v.get("impact") not in GATING_IMPACTS and v["id"] not in base_ids],
        "fixed": sorted(base_ids - observed_ids),
        "observed": violations,
    }


def update_baseline(observed_by_path, path=None):
    """Rewrite the baseline from a sweep's observations — the DELIBERATE path.

    observed_by_path: {page_path: [violation, …]} for the pages the sweep
    actually drove. Only those pages' entries are replaced (a page observed
    clean is removed); pages the run did not sweep are preserved untouched,
    so a --page or --max-tier run can never silently wipe the rest of the
    ledger. Entries are trimmed to the stable gate-relevant fields and sorted
    for reviewable diffs. Returns the written baseline dict.
    """
    path = path or BASELINE_PATH
    baseline = load_baseline(path)
    for page_path, violations in observed_by_path.items():
        rows = sorted(
            (
                {
                    "id": v["id"],
                    "impact": v.get("impact"),
                    "help": v.get("help", ""),
                    "nodes": v.get("nodes", 0),
                }
                for v in violations
            ),
            key=lambda r: r["id"],
        )
        if rows:
            baseline["pages"][page_path] = rows
        else:
            baseline["pages"].pop(page_path, None)
    baseline["pages"] = {k: baseline["pages"][k] for k in sorted(baseline["pages"])}
    baseline["_meta"] = {
        "axe_version": AXE_VERSION,
        "captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "note": (
            "Committed a11y debt ledger (#1433) — honest capture of current axe violations per page. "
            "The visual-qa gate reds only on NEW serious/critical violations vs this file. "
            "Update DELIBERATELY via `python3 tests/visual_qa.py --update-baseline` and review the diff in the PR; "
            "added entries are newly accepted debt, removed entries are fixes. Never hand-edit, never auto-regenerate."
        ),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(baseline, f, indent=2, sort_keys=False)
        f.write("\n")
    return baseline


def summarize(baseline):
    """{impact: total violation entries} across the baseline — honest numbers."""
    counts = {}
    for rows in baseline.get("pages", {}).values():
        for r in rows:
            counts[r.get("impact") or "unknown"] = counts.get(r.get("impact") or "unknown", 0) + 1
    return counts
