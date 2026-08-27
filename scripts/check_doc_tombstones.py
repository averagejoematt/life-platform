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
  ALSO scans deploy/*.sh + .github/workflows/*.yml (#2007 — the operator-facing
  deploy scripts and the pipeline's own prose comments are exactly the same class
  of surface as deploy/*.md and lambdas/**/*.py, and #781 left affirmative "comes
  from the shared layer" / "shared-layer rollback" claims live there — found by a
  2026-07-28 fullreview pass because the scan stopped at *.py and never opened a
  single *.sh or workflow YAML).
  EXEMPT (history may mention history): CHANGELOG, DECISIONS, INCIDENT_LOG, BACKLOG,
  MCP_TOOL_AUDIT, and docs/{archive,specs,reviews,audits,v2-audits,rca,restart,
  briefs,site-reviews}/, handovers/, docs/_lint/ itself.

VARIANT FORMS (#1347): a retired concept doesn't stay on one spelling. #781's
"shared layer" survived as "shared-layer" (hyphen, no space) and "Shared-layer"
(capitalized, sentence-initial in docstrings) — both slipped through the prior
space-only, case-sensitive rule (RUNBOOK.md:1364, and 8 lambdas/ docstrings, found
by the corpus-wide grep this issue codifies below). Rules now compile with
re.IGNORECASE, and docs/_lint/tombstones.txt uses `[- ]` wherever a retired
compound could plausibly be written with a hyphen instead of a space. When you
retire a NEW concept: grep every phrasing (hyphen, space, and squashed — see
docs/CONVENTIONS.md's "eradicating a wrong fact" ritual) before trusting the rule
non-vacuous; a regex that matches only the one spelling you tested is not done.

USAGE:
  python3 scripts/check_doc_tombstones.py          # exit 1 on any live hit
  python3 scripts/check_doc_tombstones.py --all    # include exempt files (advisory)
"""

import re
import sys
from pathlib import Path


def _skill_registry():
    """The ONE registry for Claude Code skills + agents (scripts/skill_registry.py)."""
    import importlib.util
    import os as _os

    _here = _os.path.dirname(_os.path.abspath(__file__))
    _cands = [_os.path.join(_here, "skill_registry.py"), _os.path.join(_here, "..", "scripts", "skill_registry.py")]
    for _p in _cands:
        if _os.path.isfile(_p):
            spec = importlib.util.spec_from_file_location("_skill_registry", _p)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
    raise FileNotFoundError("scripts/skill_registry.py not found")


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
# #1347: the shared-layer negation framings are hyphen-tolerant (`shared[- ]layer`)
# so "imports no shared-layer modules" is exempted exactly like "imports no shared
# layer modules" always was — the negation is legitimate history either spelling;
# only the RULES below (also hyphen-tolerant now) decide what's a stale claim.
#
# #2007 tightening (decision, not a restatement of #1347): deploy_reading_mcp.sh:10
# pre-fix read "...already come from the shared layer, so there is **NO shared-
# layer bump and NO fleet redeploy**" — a genuinely stale affirmative claim ("comes
# from the shared layer") sitting right next to a negation that ALSO happened to
# contain "no shared-layer", so the negation exempted the whole line and hid the
# claim beside it. The obvious fix — scope the exemption to the clause containing
# the match instead of the whole line — was tried and reverted: splitting on comma/
# sentence punctuation broke two live, legitimate multi-clause lines in THIS repo
# (docs/ARCHITECTURE.md:129's "`tools_calendar.py` DELETED (ADR-030 retired,
# Google Calendar). ... `email_framework.py` DELETED from shared layer." and
# docs/CONVENTIONS.md:627's "#781 hit the identical shape... the retired shared
# layer's old name survived as `shared-layer`..." — both say "retired" in an
# earlier clause of the SAME sentence/paragraph as a later bare "shared layer"
# mention, exactly the shape #1189's non-vacuity lesson says a rule must stay
# quiet on). A clause boundary is not a reliable proxy for "different claim" in
# this corpus's prose. Narrower and safe: the shadowing negation is specifically
# "shared-layer" used as a HYPHENATED COMPOUND MODIFIER on a following noun (a
# "shared-layer bump/version/rebuild/rollback/redeploy/update" — a claim about
# THAT noun, not about the layer's existence) — unlike the legitimate negations
# ("no shared layer to attach", "not the shared layer", "there is no shared
# layer"), which use "shared layer" as the bare head noun of the negated clause.
# The negative lookahead below excludes exactly that compound-modifier shape, so
# it can't launder an adjacent stale claim, while every legitimate negation in
# this repo (checked corpus-wide, see the #2007 PR) still matches. Pinned by
# test_shadowed_negation_no_longer_exempts_an_adjacent_stale_claim (plants the
# exact pre-fix string) and test_legitimate_negations_still_exempt (the corpus
# lines above), per the "prove it flags AND stays quiet" pattern this file's
# other rules already follow (test_mcp_manual_zip_tombstones_fire_on_the_prefix_recipe).
_LAYER_MODIFIER_SHADOW = r"(?!\s+(?:bump|version|rebuild|rollback|redeploy|update)\b)"
RETIREMENT_LINE_RE = re.compile(
    r"retired|removed|superseded|no longer|banned|do (?:NOT|not)|never hand-roll|tombstone|was deleted"
    r"|replaces?|replaced"
    rf"|no shared[- ]layer{_LAYER_MODIFIER_SHADOW}"
    rf"|without the shared[- ]layer{_LAYER_MODIFIER_SHADOW}"
    rf"|not the (?:retired )?shared[- ]layer{_LAYER_MODIFIER_SHADOW}",
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
    """Parse docs/_lint/tombstones.txt into (compiled-regex, hint) pairs.

    #1347: compiled case-insensitively — a retired concept is named the same
    regardless of sentence-initial capitalization ("Shared-layer module" vs
    "shared-layer module"), and a rules-file author writing a new pattern
    shouldn't have to hand-roll a `[Ss]hared` character class to catch both.
    """
    rules = []
    for line in RULES_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        pattern, _, hint = line.partition("\t")
        rules.append((re.compile(pattern.strip(), re.IGNORECASE), hint.strip() or "(no hint)"))
    return rules


# Source trees scanned for stale retired-concept claims in docstrings/comments.
SOURCE_DIRS = ("lambdas", "mcp")


def _scan_files(include_exempt: bool) -> list[Path]:
    candidates: list[Path] = [ROOT / "README.md", ROOT / "CLAUDE.md", ROOT / "Makefile"]
    candidates += sorted((ROOT / "deploy").glob("*.md"))  # #1322: the whole live deploy-doc surface, not just README
    candidates += sorted((ROOT / "deploy").glob("*.sh"))  # #2007: the operator-facing deploy SCRIPTS, not just docs
    candidates += sorted((ROOT / ".github" / "workflows").glob("*.yml"))  # #2007: the pipeline's own prose comments
    candidates += _skill_registry().prompt_files()  # skills AND agents, layout-agnostic
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
