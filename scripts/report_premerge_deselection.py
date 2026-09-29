#!/usr/bin/env python3
"""scripts/report_premerge_deselection.py — #2692: state what a green PR check
did NOT run.

#4251: the required lane now selects `deploy_critical`, not `premerge`; the report
reads the same two captures and states the same arithmetic.

THE PROBLEM: pr-checks.yml's `premerge` marker lane is a deliberate SUBSET of the
full suite (tests/conftest.py's docstring on `_PREMERGE_EXTRA_FILES` spells out
why: affordability against a 10-minute lane budget). That subset is invisible on
the PR itself — the check just reports green. PR #2884 merged 7/7 green on this
lane and red-mained main TWICE on tests the lane never selected
(test_drift_sentinel.py, test_gate_registry_1349.py — since added to
`_PREMERGE_EXTRA_FILES`, #2692). Pulling every structural gate into the fast lane
is not the fix on its own: the lane will always be a subset of something (that is
the entire reason it is fast), so the honest fix is a green check that SAYS what
it skipped, not a green check that implies it ran everything.

WHAT THIS DOES: parses the captured stdout of the "premerge and not integration"
pytest run (pr-checks.yml tees it to a file) for pytest's own short summary line
— which already reports a "deselected" count for free whenever a marker excludes
items, no second collection pass needed — and emits one Markdown line for the
job's $GITHUB_STEP_SUMMARY stating how many of the lane-visible tests ran and how
many did not.

FAIL-OPEN BY DESIGN: this is instrumentation, not a gate. A missing file or an
unparseable summary line prints a note and exits 0 — it must never turn a real
green PR red because of a parsing regression here. tests/test_deploy_critical_
lane.py-style enforcement (marker membership itself) is conftest.py's job; this
script only reports on top of it.

#4251 — THE LANE RUNS UNDER XDIST NOW, AND XDIST DROPS THE DESELECTED COUNT. The
parallel pass (`-n auto --dist loadfile`) deselects on the workers, so the controller's
summary line reads "12174 passed ... in 405s" with NO "deselected" term — fed that
alone, this report would claim the lane "ran all" of the suite, the exact false
reassurance #2692 exists to remove. The lane also runs TWO passes now (parallel +
the `serial` complement), so their summaries are summed. The universe comes from the
collection gate's own capture ("30653 tests collected in 86s", the step that already
runs a whole-tree `--collect-only`): when that line is present, deselected is
`collected - selected`, and any per-pass "deselected" term is ignored (the serial
pass's own term counts the parallel pass's tests as deselected — summing it would
double-count). Without it the old single-summary arithmetic applies unchanged.

USAGE:
  python3 scripts/report_premerge_deselection.py [/tmp/premerge_collect_output.txt] /tmp/premerge_lane_output.txt >> "$GITHUB_STEP_SUMMARY"
"""

from __future__ import annotations

import re
import sys
from typing import Optional

# Categories pytest's short summary line uses that represent an actually-selected
# test outcome (i.e. NOT deselected, and NOT the non-test "warning(s)" count).
_SELECTED_CATEGORIES = ("passed", "failed", "error", "errors", "skipped", "xfailed", "xpassed")

_SUMMARY_LINE_RE = re.compile(r"(\d+)\s+(passed|failed|errors?|skipped|xfailed|xpassed|deselected)\b")

# The collection gate's whole-tree `--collect-only -q` tail: "30653 tests collected in 86.52s".
# Anchored at line start with no "N/M" form, so a marker-filtered collect
# ("46/30653 tests collected (30607 deselected)") is never mistaken for the universe.
_COLLECTED_LINE_RE = re.compile(r"^(\d+)\s+tests?\s+collected\b", re.M)


def parse_counts(summary_text: str) -> Optional[dict]:
    """Parse pytest's terminal summary line(s) for selected/deselected counts.

    Returns a dict with `selected`, `deselected`, `total` (ints), or None if no
    recognizable pytest summary line is present (fail-open — see module docstring).
    """
    matches = _SUMMARY_LINE_RE.findall(summary_text)
    if not matches:
        return None

    selected = 0
    deselected = 0
    seen_any = False
    for count_str, category in matches:
        count = int(count_str)
        seen_any = True
        if category == "deselected":
            deselected += count
        elif category in _SELECTED_CATEGORIES:
            selected += count

    if not seen_any:
        return None

    collected = _COLLECTED_LINE_RE.findall(summary_text)
    if collected:
        # #4251: the universe is known, so deselected is derived, never summed.
        universe = int(collected[-1])
        return {"selected": selected, "deselected": max(universe - selected, 0), "total": max(universe, selected)}

    return {"selected": selected, "deselected": deselected, "total": selected + deselected}


def format_summary_line(counts: dict) -> str:
    selected = counts["selected"]
    deselected = counts["deselected"]
    total = counts["total"]
    if total == 0:
        return "**Pre-merge lane (#2692):** no tests were collected — nothing to report."
    pct = (selected / total) * 100.0
    if deselected == 0:
        return f"**Pre-merge lane (#2692):** ran all {selected} lane-visible tests (0 deselected)."
    return (
        f"**Pre-merge lane (#2692):** ran {selected}/{total} tests ({pct:.0f}%) — "
        f"**{deselected} deselected** from this required check. They run in this PR's "
        f"`Full unit suite` job, a separate required check (#4251), and post-merge in `Unit Tests` "
        f"(ci-test.yml). A test that must gate every merge carries `deploy_critical` (#4251)."
    )


def main(argv: list) -> int:
    if len(argv) < 2:
        print("**Pre-merge lane (#2692):** usage error — no output file given, skipping report.")
        return 0

    texts = []
    for path in argv[1:]:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                texts.append(f.read())
        except OSError as exc:
            # Fail-open (module docstring): a report that can't read its own input
            # must never fail the PR check over it.
            print(f"**Pre-merge lane (#2692):** could not read '{path}' ({exc}) — skipping report.")
            return 0
    text = "\n".join(texts)
    path = ", ".join(argv[1:])

    counts = parse_counts(text)
    if counts is None:
        print(f"**Pre-merge lane (#2692):** no pytest summary line found in '{path}' — skipping report.")
        return 0

    print(format_summary_line(counts))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
