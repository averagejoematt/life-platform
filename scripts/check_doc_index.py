#!/usr/bin/env python3
"""scripts/check_doc_index.py — wiki index-coverage + status-header + freshness check.

Four assertions over the engineering wiki (docs/README.md is the home page):

1. COVERAGE — every top-level docs/*.md is either linked from docs/README.md or
   explicitly allowlisted below. A page nobody can navigate to is a page nobody
   maintains. (Subdirectories are covered as directories, not per-file.)

2. HEADERS — every top-level docs/*.md carries the standard status header
   (`> **Status:** … · **Verified:** YYYY-MM-DD`) with a recognized status.

3. FRESHNESS (advisory at FRESHNESS_DAYS, blocking at FRESHNESS_HARD_DAYS) —
   lists canonical pages whose Verified date is older than FRESHNESS_DAYS, as
   the re-verification worklist.

4. SOURCE-NEWER-THAN-VERIFY (#973 — advisory; blocking under --strict) — for each
   engine doc (docs/engines/*.md), the git last-commit date of every declared
   `Sources of truth` file is compared against the doc's Verified date. Calendar
   freshness alone (gate 3) misses the real staleness signal: a doc verified
   yesterday against an engine rewritten today stays "fresh" for months. A source
   committed strictly AFTER the verify date flags the doc for re-verification.
   Missing/unparseable metadata is skipped with a note, never a crash.

USAGE:
  python3 scripts/check_doc_index.py            # gates 1+2(+3 hard), prints 3+4; exit 1 on fail
  python3 scripts/check_doc_index.py --strict   # gate 4 drift also FAILS (promotion path for docs-ci)
  python3 scripts/check_doc_index.py --fresh    # only the freshness + source-drift reports, exit 0
"""

import re
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
INDEX = DOCS / "README.md"

FRESHNESS_DAYS = 90  # advisory report threshold
FRESHNESS_HARD_DAYS = 180  # BLOCKING — a canonical page unverified this long fails CI (CTO-grader rec, 2026-07-10)

VALID_STATUSES = ("canonical", "generated", "log", "superseded", "archive")

# Pages that intentionally aren't in the wiki index (mirrors the KNOWN_GAPS
# allowlist pattern from tests/test_wiring_coverage.py). Shrink, never grow silently.
INDEX_ALLOWLIST: set[str] = set()

_STATUS_RE = re.compile(r"^> \*\*Status:\*\* (\w+)", re.MULTILINE)
_VERIFIED_RE = re.compile(r"\*\*Verified:\*\* (\d{4}-\d{2}-\d{2})")

# ── Gate 4 (#973): engine-doc source freshness ────────────────────────────────
ENGINES = DOCS / "engines"
_SOURCES_RE = re.compile(r"\*\*Sources of truth:\*\*(.+)$", re.MULTILINE)
_BACKTICK_RE = re.compile(r"`([^`]+)`")


def _extract_source_paths(src: str) -> list[str] | None:
    """Backticked repo paths on the `**Sources of truth:**` line, or None if absent.

    Only tokens that resolve to an existing repo file count as sources — the line
    also carries backticked annotations that are NOT paths (symbol names like
    `_enforce_quality_gate`, deploy targets like `s3://…`, DDB keys). Those are
    silently ignored rather than flagged, so the gate never crashes on prose.
    """
    m = _SOURCES_RE.search(src)
    if m is None:
        return None
    paths = []
    for token in _BACKTICK_RE.findall(m.group(1)):
        candidate = token.strip()
        if "/" in candidate and (ROOT / candidate).is_file():
            paths.append(candidate)
    return paths


def _git_last_commit_date(rel_path: str) -> date | None:
    """Date (committer date, %cs) of the last commit touching rel_path, else None."""
    try:
        out = subprocess.run(
            ["git", "log", "-1", "--format=%cs", "--", rel_path],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        s = out.stdout.strip().splitlines()[0].strip() if out.stdout.strip() else ""
        return date.fromisoformat(s) if s else None
    except Exception:
        return None


def check_engine_source_freshness(git_date_fn=_git_last_commit_date):
    """The source-newer-than-verify gate (#973).

    For each docs/engines/*.md: parse its `Sources of truth` paths and `Verified:`
    date, and flag any source file whose last git commit is strictly AFTER the
    verify date — the doc may describe code that no longer says what it said.

    Returns (flagged, notes):
      flagged — [(doc_rel, source_rel, committed_iso, verified_iso)], the drift.
      notes   — skip reasons (missing/unparseable metadata); informational only.
    """
    flagged, notes = [], []
    if not ENGINES.is_dir():
        return flagged, notes
    for p in sorted(ENGINES.glob("*.md")):
        rel = f"docs/engines/{p.name}"
        src = p.read_text(encoding="utf-8")
        sources = _extract_source_paths(src)
        if sources is None:
            notes.append(f"skip {rel}: no '**Sources of truth:**' line")
            continue
        v = _VERIFIED_RE.search(src[:600])
        if v is None:
            notes.append(f"skip {rel}: no '**Verified:** YYYY-MM-DD' in header")
            continue
        if not sources:
            notes.append(f"skip {rel}: no source token resolves to a repo file")
            continue
        verified = date.fromisoformat(v.group(1))
        for source in sources:
            committed = git_date_fn(source)
            if committed is None:
                notes.append(f"skip {rel} ← {source}: git last-commit date unavailable")
                continue
            if committed > verified:
                flagged.append((rel, source, committed.isoformat(), verified.isoformat()))
    return flagged, notes


def main():
    fresh_only = "--fresh" in sys.argv
    strict = "--strict" in sys.argv
    problems = []

    index_src = INDEX.read_text(encoding="utf-8")
    linked = set(re.findall(r"\]\(([A-Za-z0-9_\-./]+\.md)\)", index_src))

    stale = []
    today = date.today()
    for p in sorted(DOCS.glob("*.md")):
        rel = p.name
        src = p.read_text(encoding="utf-8")

        if not fresh_only:
            # 1. coverage
            if rel != "README.md" and rel not in linked and rel not in INDEX_ALLOWLIST:
                problems.append(f"not in the wiki index (docs/README.md): docs/{rel}")
            # 2. header
            m = _STATUS_RE.search(src[:600])
            if not m:
                problems.append(f"missing status header (> **Status:** …): docs/{rel}")
                continue
            if m.group(1) not in VALID_STATUSES:
                problems.append(f"unrecognized status {m.group(1)!r}: docs/{rel}")

        # 3. freshness (canonical pages only)
        m = _STATUS_RE.search(src[:600])
        v = _VERIFIED_RE.search(src[:600])
        if m and m.group(1) == "canonical" and v:
            d = date.fromisoformat(v.group(1))
            if today - d > timedelta(days=FRESHNESS_DAYS):
                stale.append((str(today - d).split(",")[0], f"docs/{rel}", v.group(1)))
            if not fresh_only and today - d > timedelta(days=FRESHNESS_HARD_DAYS):
                problems.append(
                    f"canonical page unverified > {FRESHNESS_HARD_DAYS}d (re-verify + bump the header): docs/{rel} ({v.group(1)})"
                )

    # 4. source-newer-than-verify (#973) — advisory unless --strict
    flagged, notes = check_engine_source_freshness()
    if flagged and strict and not fresh_only:
        for doc_rel, source_rel, committed, verified in flagged:
            problems.append(f"engine-doc source drift (--strict): {doc_rel} verified {verified} but {source_rel} committed {committed}")

    if problems:
        print(f"❌ {len(problems)} wiki index/header problem(s):")
        for pr in problems:
            print(f"   {pr}")
        sys.exit(1)

    if not fresh_only:
        print("✅ wiki index coverage + status headers OK.")
    if stale:
        print(f"\n📋 freshness report (advisory) — canonical pages unverified > {FRESHNESS_DAYS}d:")
        for age, path, when in sorted(stale, reverse=True):
            print(f"   {path} (verified {when}, {age} ago)")
    else:
        print(f"📋 freshness: all canonical pages verified within {FRESHNESS_DAYS}d.")

    if flagged:
        print(
            f"\n⚠️  engine-doc source drift (#973 — ADVISORY; fails under --strict) — "
            f"{len(flagged)} source(s) committed after the doc's Verified date:"
        )
        for doc_rel, source_rel, committed, verified in flagged:
            print(f"   {doc_rel} (verified {verified}) ← {source_rel} committed {committed} — re-verify the doc + bump its header")
    else:
        print("\n✅ engine-doc sources (#973): no 'Sources of truth' file newer than its doc's Verified date.")
    for note in notes:
        print(f"   (note) {note}")


if __name__ == "__main__":
    main()
