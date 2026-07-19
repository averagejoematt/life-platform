#!/usr/bin/env python3
"""scripts/check_doc_tombstones.py — retired-concept scanner for the engineering wiki.

THE PROBLEM THIS SOLVES:
  When something load-bearing is retired (the shared layer, WAF, a script), the
  retirement propagates to 2 of 10 docs and the rest keep teaching the dead path
  (#781 reached only CONVENTIONS + deploy/README for a month; QUICKSTART/RUNBOOK/
  DEPLOYMENT still taught build_layer.sh — found in the 2026-07-10 wiki audit).

  This makes retirement a ONE-LINE act: add a rule to docs/_lint/tombstones.txt
  and CI fails on every live doc still describing the retired thing.

SCOPE:
  Scans the LIVE docs surface: docs/*.md (top level), docs/design/, docs/coaching/,
  docs/content/, docs/design-review/, docs/engines/, plus README.md, CLAUDE.md,
  Makefile (#1323 — the Makefile is a second, un-audited entry-point system that
  can route an operator onto a retired script exactly like a stale doc can),
  .claude/commands/*.md, deploy/*.md (#1322 — the deploy directory's own runbooks
  steered operators onto the retired boot-broken manual MCP zip; MANIFEST.md and
  V2_ROLLBACK.md are exempt as dated/deprecated records).
  ALSO scans SOURCE docstrings/comments: lambdas/**/*.py + mcp/**/*.py (#781 taught
  us the shared-layer retirement reached tests + 2 docs but left 35+ stale "part of
  the shared layer" claims in code — the docs-only scan never opened lambdas/).
  EXEMPT (history may mention history): CHANGELOG, DECISIONS, INCIDENT_LOG, BACKLOG,
  MCP_TOOL_AUDIT, and docs/{archive,specs,reviews,audits,v2-audits,rca,restart,
  briefs,site-reviews}/, handovers/, docs/_lint/ itself.

USAGE:
  python3 scripts/check_doc_tombstones.py          # exit 1 on any live hit
  python3 scripts/check_doc_tombstones.py --all    # include exempt files (advisory)
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RULES_FILE = ROOT / "docs" / "_lint" / "tombstones.txt"

EXEMPT_FILES = {
    "docs/CHANGELOG.md",
    "docs/DECISIONS.md",
    "docs/INCIDENT_LOG.md",
    "docs/BACKLOG.md",
    "docs/MCP_TOOL_AUDIT.md",
    "deploy/MANIFEST.md",  # deprecated inventory (superseded) — history may mention history
    "deploy/V2_ROLLBACK.md",  # dated completed-operation record (2026-05-31)
}

# A line that itself explains the retirement is allowed to name the corpse.
# Includes the "NOT/no/without the shared layer" and "X it replaces" framings
# that source docstrings use to say a concept is gone (#781). Module-level so
# tests can prove a planted stale line is NOT exempted (#1322 non-vacuity).
RETIREMENT_LINE_RE = re.compile(
    r"retired|removed|superseded|no longer|banned|do (?:NOT|not)|never hand-roll|tombstone|was deleted"
    r"|replaces?|replaced|no shared layer|without the shared layer|not the (?:retired )?shared layer",
    re.I,
)
EXEMPT_DIRS = (
    "docs/archive/",
    "docs/specs/",
    "docs/reviews/",
    "docs/audits/",
    "docs/v2-audits/",
    "docs/rca/",
    "docs/restart/",
    "docs/briefs/",
    "docs/site-reviews/",
    "docs/_lint/",
    "handovers/",
)


def _rules() -> list[tuple[re.Pattern, str]]:
    rules = []
    for line in RULES_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        pattern, _, hint = line.partition("\t")
        rules.append((re.compile(pattern.strip()), hint.strip() or "(no hint)"))
    return rules


# Source trees scanned for stale retired-concept claims in docstrings/comments.
SOURCE_DIRS = ("lambdas", "mcp")


def _scan_files(include_exempt: bool) -> list[Path]:
    candidates: list[Path] = [ROOT / "README.md", ROOT / "CLAUDE.md", ROOT / "Makefile"]
    candidates += sorted((ROOT / "deploy").glob("*.md"))  # #1322: the whole live deploy-doc surface, not just README
    candidates += sorted((ROOT / ".claude" / "commands").glob("*.md"))
    candidates += sorted((ROOT / "docs").rglob("*.md"))
    for d in SOURCE_DIRS:
        candidates += sorted((ROOT / d).rglob("*.py"))
    out = []
    for p in candidates:
        if not p.exists():
            continue
        rel = str(p.relative_to(ROOT))
        if not include_exempt and (rel in EXEMPT_FILES or any(rel.startswith(d) for d in EXEMPT_DIRS)):
            continue
        out.append(p)
    return out


def main():
    include_exempt = "--all" in sys.argv
    rules = _rules()
    if not rules:
        print(f"error: no rules parsed from {RULES_FILE}", file=sys.stderr)
        sys.exit(2)

    hits = []
    for doc in _scan_files(include_exempt):
        rel = doc.relative_to(ROOT)
        for lineno, line in enumerate(doc.read_text(encoding="utf-8").splitlines(), 1):
            if RETIREMENT_LINE_RE.search(line):
                continue
            for rx, hint in rules:
                if rx.search(line):
                    hits.append(f"{rel}:{lineno}: [{rx.pattern}] → {hint}\n      | {line.strip()[:120]}")

    if hits:
        print(f"❌ {len(hits)} live doc line(s) reference retired concepts:")
        for h in hits:
            print(f"   {h}")
        print("\nFix the doc (point at the replacement), or if the line legitimately describes")
        print("the retirement itself, phrase it so ('retired', 'removed', 'superseded', …).")
        sys.exit(1)
    print(f"✅ tombstones OK — no live doc references a retired concept ({len(rules)} rules).")


if __name__ == "__main__":
    main()
