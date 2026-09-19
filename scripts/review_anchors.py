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

THE OTHER HALF: THE ANCHORS THAT ARE TEXT, FROZEN FOR THE RUN (#3603)
---------------------------------------------------------------------
The magnitudes above rot because they are typed. The *qualitative* anchors — what an A
means for a lens — rotted the opposite way: every one of the 17 anchors on the 2026-09-05
baseline was EXTENDED during the run that graded against it, which the spine explicitly
sanctioned. A bar raised inside the run it grades makes decay and a raised bar impossible
to separate afterwards, so the trend line — the only reason to grade at all — means
nothing.

So a run now FREEZES its anchor text at start and says so in its own artifact:
``frozen_anchor_header()`` fingerprints the rubric files the run graded against (the spine
plus the lens rubric) at the commit it graded, and the run pastes that block into its
grades JSON. ``anchor_drift()`` is the read-back: given a run's header and the rubric text
**at that run's own commit**, it names every anchor file whose text is not what the header
recorded. A run whose anchor text differs from the versioned rubric at its own sha did not
grade against what it says it graded against, and its grades are not comparable to the
previous run's. Extending an anchor is still allowed and still wanted — between runs, by
PR, where the diff is reviewable and dated.

USAGE
-----
    python3 scripts/review_anchors.py          # the anchor block, for the Phase-0 context
    python3 scripts/review_anchors.py --json   # same, machine-readable
    python3 scripts/review_anchors.py --freeze --lens full   # the anchor-freeze header for the artifact

v1.1.0 — 2026-09-19 (#3603, the anchor-freeze header) · v1.0.0 — 2026-08-27 (#3250)
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import subprocess
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


# ── The anchor freeze (#3603) ────────────────────────────────────────────────
#: The review spine — the phases, the evidence rule, the grade-calibration paragraph. Part
#: of every lens's anchor text, so a change to it is a change to every lens's bar.
REVIEW_SPINE_PATH = ".claude/skills/review/SKILL.md"
REVIEW_RUBRIC_DIR = ".claude/skills/review/references"


def rubric_paths(lens: str) -> tuple[str, ...]:
    """The files that ARE the anchor text for one lens: the spine plus its own rubric.
    Enumerated, never globbed — the frozen set has to be the same two files on the run that
    freezes it and the read-back that checks it."""
    return (REVIEW_SPINE_PATH, f"{REVIEW_RUBRIC_DIR}/{lens}.md")


def read_from_tree(repo: str = REPO):
    """A reader over the working tree (what a run freezes against at Phase 0)."""

    def _read(rel: str) -> str | None:
        path = os.path.join(repo, rel)
        try:
            with open(path, encoding="utf-8") as fh:
                return fh.read()
        except OSError:
            return None

    return _read


def read_at_sha(sha: str, repo: str = REPO):
    """A reader over the rubric AS IT WAS at a given commit — the read-back's source of
    truth, because the header's claim is about that run's commit, not about HEAD. A rubric
    legitimately extended by a later PR must not red an old run's header."""

    def _read(rel: str) -> str | None:
        try:
            out = subprocess.run(["git", "show", f"{sha}:{rel}"], cwd=repo, capture_output=True, text=True, timeout=30, check=False)
        except (OSError, subprocess.SubprocessError):
            return None
        return out.stdout if out.returncode == 0 else None

    return _read


def rubric_fingerprint(lens: str, read_text) -> dict[str, str]:
    """{rubric path: sha256 of its bytes} — the anchor text, addressed by content. A path
    the reader cannot produce is recorded as MISSING rather than dropped: a rubric that
    vanished is a fact about the run, and a silently shorter dict would read as agreement."""
    out: dict[str, str] = {}
    for rel in rubric_paths(lens):
        text = read_text(rel)
        out[rel] = "MISSING" if text is None else "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    return out


def frozen_anchor_header(lens: str, graded_sha: str, today: date, read_text=None, repo: str = REPO) -> dict:
    """The block a run pastes into its own grades JSON, at START, before any grading.

    It records what the run is about to grade against: the commit, the anchor text by
    content hash, and the carry-forward cap in force. A later run that grades against
    different anchors produces a different fingerprint, so 'the anchors moved' becomes a
    diff instead of a thing a reader has to remember.
    """
    cap = None
    try:
        cap = _operating_calendar().CARRY_FORWARD_MAX_DAYS  # one home for the number, never a second copy
    except Exception:  # pragma: no cover — the cap is informational in the header
        cap = None
    return {
        "lens": lens,
        "frozen_at": today.isoformat(),
        "graded_sha": graded_sha,
        "rubric": rubric_fingerprint(lens, read_text or read_from_tree(repo)),
        "carry_forward_cap_days": cap,
        "rule": (
            "Anchors are FROZEN for this run: the A/C/F criteria are the text of the files fingerprinted above, "
            "at graded_sha. They may not be extended, narrowed or reworded during the run — an anchor moved inside "
            "the run that grades against it makes decay and a raised bar inseparable (#3603). Extensions land "
            "between runs, by PR."
        ),
    }


def anchor_drift(header: dict, read_text) -> list[str]:
    """Every anchor file whose text is not what the header recorded — empty means this run's
    grades were derived from the rubric as committed at its own sha."""
    recorded = (header or {}).get("rubric") or {}
    if not recorded:
        return ["anchor_freeze.rubric is absent or empty — this run recorded no anchor text, so nothing can be checked"]
    lens = header.get("lens") or ""
    actual = rubric_fingerprint(lens, read_text)
    drift = []
    for rel in sorted(set(recorded) | set(actual)):
        was, now = recorded.get(rel), actual.get(rel)
        if was is None:
            drift.append(f"{rel}: graded but never fingerprinted — the freeze omitted an anchor file")
        elif now is None:
            drift.append(f"{rel}: fingerprinted but not part of this lens's anchor set")
        elif was != now:
            drift.append(f"{rel}: header recorded {was}, the rubric at this run's commit is {now} — the anchors moved")
    return drift


def _operating_calendar():
    """The carry-forward cap has exactly one home (scripts/operating_calendar.py)."""
    path = os.path.join(HERE, "operating_calendar.py")
    spec = importlib.util.spec_from_file_location("_operating_calendar_for_anchors", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def head_sha(repo: str = REPO) -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError):
        return "UNKNOWN"
    return out.stdout.strip() or "UNKNOWN"


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
        "The QUALITATIVE anchors (what an A means) are frozen separately and recorded in the run's",
        "own artifact: python3 scripts/review_anchors.py --freeze --lens <lens>  (#3603). Freeze them",
        "at Phase 0, before grading; extend them between runs by PR, never inside the run that grades.",
        "",
    ]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--freeze", action="store_true", help="emit the anchor-freeze header for a run's artifact (#3603)")
    ap.add_argument("--lens", default="full", help="which lens's rubric to freeze (default: full)")
    ap.add_argument("--sha", default=None, help="the commit being graded (default: HEAD)")
    args = ap.parse_args(argv)
    if args.freeze:
        header = frozen_anchor_header(args.lens, args.sha or head_sha(), date.today())
        print(json.dumps({"anchor_freeze": header}, indent=2))
        return 0  # an instrument, never a gate
    values = anchors()
    if args.json:
        print(json.dumps({"derived": date.today().isoformat(), "anchors": values, "pointers": POINTERS}, indent=2))
    else:
        print(render(values, date.today()))
    return 0  # an instrument, never a gate


if __name__ == "__main__":
    sys.exit(main())
