#!/usr/bin/env python3
"""scripts/review_anchors.py — derive the review rituals' quantitative anchors (#3250).

WHY THIS EXISTS
---------------
A grading rubric's magnitude anchors were hand-typed into the skill file and then rotted
in place. Measured 2026-08-27: `/sdlc-review` graded "suite runtime/flake economics at
~380 test files" against a real 1,015, and "the `deploy/` script surface (~85 scripts)"
against a real 152 top-level / 347 recursive. A denominator that is 2.7x off does not
grade — it flatters, and every letter derived from it means nothing. This is the same
class as every other stale-literal incident on this platform (#2986's month-stale catalog
behind a daily-bumped timestamp, #973/#2619's date-compared `Verified` stamps): the number
was a HUMAN CLAIM sitting where a MEASUREMENT belonged.

So the rubric no longer carries numbers. It carries anchor KEYS, and this script produces
the values at run time, from the tree, on the day of the run. A rubric with no numbers in
it cannot go stale; a script that reads the tree cannot be 2.7x off.

WHAT IT IS NOT
--------------
Not a gate. It always exits 0 and asserts nothing — it is an instrument the ritual reads
in Phase 0. The gate half lives in `tests/test_operating_calendar_2832.py`
(`test_review_skills_carry_no_hand_typed_magnitudes`), which fails if a magnitude is typed
back into a calendared review skill.

Not a second truth for facts that already have one. Counts that are owned elsewhere are
printed as POINTERS, never re-derived here — a second derivation of the same fact is how
two numbers start disagreeing:
  * the gate estate      -> `python3 scripts/gate_census.py`
  * the MCP tool count   -> `deploy/sync_doc_metadata.py::_auto_discover_tool_count`
  * lambda/test/alarm doc literals -> the generated `lambdas/web/platform_counts.py` (#3101)

USAGE
-----
    python3 scripts/review_anchors.py          # the anchor block, for the Phase-0 context
    python3 scripts/review_anchors.py --json   # same, machine-readable

v1.0.0 — 2026-08-27 (#3250)
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)


# ── derivations ───────────────────────────────────────────────────────────────
def _glob_count(repo: str, rel_dir: str, predicate) -> int:
    d = os.path.join(repo, rel_dir)
    if not os.path.isdir(d):
        return 0
    return sum(1 for n in os.listdir(d) if predicate(n) and os.path.isfile(os.path.join(d, n)))


def _walk_count(repo: str, rel_dir: str, predicate) -> int:
    d = os.path.join(repo, rel_dir)
    total = 0
    for root, dirs, files in os.walk(d):
        dirs[:] = [x for x in dirs if x not in {"__pycache__", ".pytest_cache"}]
        total += sum(1 for n in files if predicate(os.path.join(root, n)))
    return total


def _adr_records(repo: str) -> int:
    """Reuse the ADR index generator's own parser — never a second regex for the same fact."""
    path = os.path.join(repo, "scripts", "generate_adr_index.py")
    src_doc = os.path.join(repo, "docs", "DECISIONS.md")
    if not (os.path.isfile(path) and os.path.isfile(src_doc)):
        return 0
    spec = importlib.util.spec_from_file_location("_adr_index_for_anchors", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    with open(src_doc, encoding="utf-8") as fh:
        return len(mod._records(fh.read()))


def _py(name: str) -> bool:
    return name.endswith(".py")


def _md(name: str) -> bool:
    return name.endswith(".md")


# key -> (label, how it is derived — printed so a reader can re-run the measurement)
DERIVATIONS: dict[str, tuple[str, str]] = {
    "test_modules": ("python modules under tests/", "tests/*.py"),
    "test_suite_files": ("pytest-collected suite files", "tests/test_*.py"),
    "deploy_entrypoints": ("scripts directly in deploy/", "files at the top of deploy/"),
    "deploy_surface": ("every file under deploy/", "find deploy -type f"),
    "adr_records": ("ADR records in docs/DECISIONS.md", "scripts/generate_adr_index.py::_records"),
    "process_docs": ("top-level process docs", "docs/*.md"),
    "docs_surface": ("every markdown file under docs/", "find docs -name '*.md'"),
    "ci_workflows": ("GitHub Actions workflows", ".github/workflows/*.yml"),
    "lambda_modules": ("python modules under lambdas/", "find lambdas -name '*.py'"),
    "mcp_modules": ("python modules under mcp/", "mcp/*.py"),
    "claude_commands": ("skill/command definitions", ".claude/commands/*.md"),
    "claude_agents": ("subagent definitions", ".claude/agents/*.md"),
    "cdk_stacks": ("CDK stack modules", "cdk/stacks/*.py"),
}

POINTERS: dict[str, str] = {
    "gate estate (total / unproven)": "python3 scripts/gate_census.py",
    "MCP tool count": "deploy/sync_doc_metadata.py::_auto_discover_tool_count",
    "lambda / test / alarm doc literals": "lambdas/web/platform_counts.py (generated, #3101)",
    "ingestion cadence + staleness per source": "lambdas/ingestion/source_registry.py facets",
    "review-ritual cadences + due state": "python3 scripts/operating_calendar.py",
}


def anchors(repo: str = REPO) -> dict[str, int]:
    """Every hand-typeable magnitude a review rubric might want, measured now."""
    return {
        "test_modules": _glob_count(repo, "tests", _py),
        "test_suite_files": _glob_count(repo, "tests", lambda n: n.startswith("test_") and _py(n)),
        "deploy_entrypoints": _glob_count(repo, "deploy", lambda n: True),
        "deploy_surface": _walk_count(repo, "deploy", lambda p: True),
        "adr_records": _adr_records(repo),
        "process_docs": _glob_count(repo, "docs", _md),
        "docs_surface": _walk_count(repo, "docs", _md),
        "ci_workflows": _glob_count(repo, ".github/workflows", lambda n: n.endswith((".yml", ".yaml"))),
        "lambda_modules": _walk_count(repo, "lambdas", _py),
        "mcp_modules": _glob_count(repo, "mcp", _py),
        "claude_commands": _glob_count(repo, ".claude/commands", _md),
        "claude_agents": _glob_count(repo, ".claude/agents", _md),
        "cdk_stacks": _glob_count(repo, "cdk/stacks", _py),
    }


def render(values: dict[str, int], today: date) -> str:
    width = max(len(k) for k in values)
    out = [
        f"REVIEW ANCHORS — derived {today} by scripts/review_anchors.py (#3250)",
        "",
        "Paste this block verbatim into the Phase-0 shared context. Every magnitude claim in",
        "a lens brief cites one of these KEYS; a number typed into a rubric file is a defect",
        "(the anchors were 2.7x stale when this was measured on 2026-08-27).",
        "",
    ]
    for key, val in values.items():
        label, how = DERIVATIONS[key]
        out.append(f"  {key:<{width}}  {val:>6}   {label}  [{how}]")
    out += ["", "Owned elsewhere — cite the source, do NOT re-derive:"]
    for label, where in POINTERS.items():
        out.append(f"  {label:<38} {where}")
    out += [
        "",
        "Anchors are magnitudes, not judgments: the number tells a lens how big the surface is,",
        "it never tells it what grade the surface deserves.",
        "",
    ]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args(argv)
    values = anchors()
    if args.json:
        print(json.dumps({"derived": date.today().isoformat(), "anchors": values, "pointers": POINTERS}, indent=2))
    else:
        print(render(values, date.today()))
    return 0  # an instrument, never a gate


if __name__ == "__main__":
    sys.exit(main())
