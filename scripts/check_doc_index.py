#!/usr/bin/env python3
"""scripts/check_doc_index.py — wiki index-coverage + status-header + freshness check.

Three assertions over the engineering wiki (docs/README.md is the home page):

1. COVERAGE — every top-level docs/*.md is either linked from docs/README.md or
   explicitly allowlisted below. A page nobody can navigate to is a page nobody
   maintains. (Subdirectories are covered as directories, not per-file.)

2. HEADERS — every top-level docs/*.md carries the standard status header
   (`> **Status:** … · **Verified:** YYYY-MM-DD`) with a recognized status.

3. FRESHNESS (advisory, never fails) — lists canonical pages whose Verified date
   is older than FRESHNESS_DAYS, as the re-verification worklist.

USAGE:
  python3 scripts/check_doc_index.py            # gates 1+2, prints 3; exit 1 on fail
  python3 scripts/check_doc_index.py --fresh    # only the freshness report, exit 0
"""

import re
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


def main():
    fresh_only = "--fresh" in sys.argv
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


if __name__ == "__main__":
    main()
