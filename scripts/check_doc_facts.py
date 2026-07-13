#!/usr/bin/env python3
"""scripts/check_doc_facts.py — generalized stale-number gate for the wiki.

THE PROBLEM THIS SOLVES
  `deploy/sync_doc_metadata.py` reconciles facts only in the *exact phrasings* its
  ~60 regex RULES target. A number in any un-ruled phrasing is unguarded. That is
  precisely how "**Tools:** 127" drifted while the same file's header (ruled) said
  64 — a self-contradiction that passed CI — and how "1,217 tests" (2.9x stale) and
  "$75 ceiling" survived. Adding a RULE per phrasing is whack-a-mole; a new sentence
  drifts again.

THE FIX
  This gate inverts it: it knows the GROUND-TRUTH values (imported from the same
  discoverers sync_doc_metadata uses — the single source) and scans the live doc
  surface for ANY number sitting next to a known fact token ("N MCP tools",
  "N CDK stacks", "$N/month", ...). If the number disagrees with truth and the line
  is not marked historical, it fails. A brand-new phrasing can't silently drift.

  This is a SAFETY NET, complementary to sync_doc_metadata (which still auto-fixes
  the canonical phrasings). Precision is the whole game: soft counts use a percentage
  tolerance and honor "~"/"+" approximation markers, hard counts (registry-exact) use
  zero tolerance, and any line that frames a number as history is exempt.

EXEMPTING A LINE
  Put the number in a clearly historical frame ("was 75", "raised 75->85", "as of
  2026-05", "formerly"), or add an inline `<!-- drift-ok: reason -->` (any comment
  syntax) on the line. Ledgers (CHANGELOG, COST_TRACKER, ...) and archives are
  skipped wholesale — history is allowed to state history.

USAGE
  python3 scripts/check_doc_facts.py           # exit 1 on any stale current claim
  python3 scripts/check_doc_facts.py --list     # print the ground-truth values and exit
"""

import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


# ── ground truth (imported from the sync tool's discoverers — ONE source) ──────
def _ground_truth() -> dict:
    spec = importlib.util.spec_from_file_location("_syncmeta", ROOT / "deploy" / "sync_doc_metadata.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    facts = m._apply_auto_discovered(dict(m.PLATFORM_FACTS))
    return {
        "tool_count": facts.get("tool_count"),
        "lambda_count": facts.get("lambda_count"),
        "cdk_stacks": facts.get("cdk_stacks"),
        "module_count": facts.get("module_count"),
        "adr_count": facts.get("adr_count"),
        "alarm_count": facts.get("alarm_count"),
        "data_sources": facts.get("data_sources"),
        "test_count": facts.get("test_count") or m._count_test_functions(),
    }


# ── the facts we police, with the phrasings that quote them ────────────────────
# Each entry: (truth_key, [context regexes with ONE numeric capture group], tol).
# tol: 0 = exact (registry-derived, drift is always wrong); a float = fractional
# tolerance for counts cited approximately in prose.
#
# PRECISION over recall — a CI gate with false positives gets disabled, so this is
# deliberately narrow (FORWARD phrasings only, "number then fact-token"):
#   • `NG` (below) refuses any number glued to letters/version/decimal — kills the
#     "python3 tests/" == "3 tests" class and "s3", "v8", "ADR-135" glue.
#   • lambda_count is intentionally NOT policed: "N Lambdas" is ambiguous with the
#     dozens of legit SUBSET counts (14 ingestion, 5 coach, 24 on ai-keys, …). The
#     sync RULES own the canonical total; a prose safety-net can't tell subset from
#     total without false-flagging. (sync_doc_metadata still guards the real total.)
#   • test_count requires an explicit counting qualifier (passing/unit/total/suite),
#     so a bare "tests/" path never trips it.
NG = r"(?<![A-Za-z0-9.])"  # left-guard: the number must not be glued to a word/version
FACT_SPECS = [
    # tool_count — registry-exact. "64 MCP tools", "~125 MCP tools".
    (
        "tool_count",
        [
            NG + r"(\d+)\s+MCP tools?\b",
        ],
        0.0,
    ),
    # cdk_stacks — exact. "9 CDK stacks".
    (
        "cdk_stacks",
        [
            NG + r"(\d+)\s+CDK stacks?\b",
        ],
        0.0,
    ),
    # test_count — moves every session; prose should say "~3,600". ±18% catches the
    # 1,217-vs-3,644 class (66% off) while allowing an honest "~3,600". Requires a
    # counting qualifier so a bare "tests/" directory path is never matched.
    (
        "test_count",
        [
            NG + r"([\d,]+)\s+(?:passing|unit|total)\s+tests?\b",
            NG + r"([\d,]+)\s+tests?\s+(?:passing|pass\b|green|total|run\b)",
            r"\btests?:\s*" + NG + r"([\d,]+)\b",
            r"\btest suite of\s+" + NG + r"([\d,]+)\b",
        ],
        0.18,
    ),
]

# Budget ceiling is special: a small allowed SET (base + surge, ADR-133), not a point.
# The $ amount must sit right next to a ceiling word — NOT merely share a line with
# "month" (else a per-user cost projection like "$405/month" false-flags). Two
# alternations (word→amount, amount→word); whichever group matched is the amount.
BUDGET_OK = {85, 100}
BUDGET_NEAR = re.compile(
    r"(?:budget|ceiling|\bcap\b|guardrail)[^\n$]{0,20}\$(\d{2,3})\b(?!\.\d)"
    r"|\$(\d{2,3})\b(?!\.\d)[^\n$]{0,20}(?:budget|ceiling|\bcap\b|guardrail)",
    re.I,
)

# A line framing a number as history is allowed to state the old value.
HISTORICAL = re.compile(
    r"\bwas\b|\bwere\b|->|→|raised|lowered|formerly|previously|used to|as of\s*\d"
    r"|grew from|up from|down from|pre-#|earlier|drift-ok|no longer|retired|superseded",
    re.I,
)
APPROX = ("~", "≈", "+", "about ", "around ", "roughly ")

# Same skip surface as the tombstone scanner + the cost ledger.
EXEMPT_FILES = {
    "docs/CHANGELOG.md",
    "docs/DECISIONS.md",
    "docs/INCIDENT_LOG.md",
    "docs/BACKLOG.md",
    "docs/MCP_TOOL_AUDIT.md",
    "docs/COST_TRACKER.md",
}
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


def _scan_files() -> list[Path]:
    cands = [ROOT / "README.md", ROOT / "CLAUDE.md"]
    cands += sorted((ROOT / ".claude" / "commands").glob("*.md"))
    cands += sorted((ROOT / "docs").rglob("*.md"))
    out = []
    for p in cands:
        if not p.exists():
            continue
        rel = str(p.relative_to(ROOT))
        if rel in EXEMPT_FILES or any(rel.startswith(d) for d in EXEMPT_DIRS):
            continue
        out.append(p)
    return out


def _to_int(s: str):
    try:
        return int(s.replace(",", ""))
    except ValueError:
        return None


def _off(claim: int, truth: int, tol: float, approx: bool) -> bool:
    """True if `claim` is out of tolerance from `truth`."""
    eff = max(tol, 0.15) if approx else tol
    if eff == 0.0:
        return claim != truth
    return abs(claim - truth) > round(truth * eff)


def main():
    truth = _ground_truth()
    if "--list" in sys.argv:
        for k, v in truth.items():
            print(f"  {k} = {v}")
        print(f"  budget_ceiling ∈ {sorted(BUDGET_OK)} (ADR-133)")
        sys.exit(0)

    missing = [k for k, v in truth.items() if v is None]
    if missing:
        print(f"error: could not discover ground truth for {missing}", file=sys.stderr)
        sys.exit(2)

    hits = []
    for doc in _scan_files():
        rel = doc.relative_to(ROOT)
        for lineno, line in enumerate(doc.read_text(encoding="utf-8").splitlines(), 1):
            if HISTORICAL.search(line):
                continue
            approx = any(a in line for a in APPROX)
            for key, patterns, tol in FACT_SPECS:
                for pat in patterns:
                    for mo in re.finditer(pat, line):
                        claim = _to_int(mo.group(1))
                        if claim is None:
                            continue
                        if _off(claim, truth[key], tol, approx):
                            hits.append(
                                f"{rel}:{lineno}: {key} claims {claim}, truth is {truth[key]}"
                                f"{' (±%d%%)' % round(tol*100) if tol else ''}\n"
                                f"      | {line.strip()[:120]}"
                            )
            # budget: a $NN sitting next to a ceiling word that isn't an allowed value
            for mo in BUDGET_NEAR.finditer(line):
                amt = int(mo.group(1) or mo.group(2))
                if amt not in BUDGET_OK and amt >= 50:  # >=50 avoids cents/small figures
                    hits.append(
                        f"{rel}:{lineno}: budget ceiling claims ${amt}, truth is $85 base / $100 surge (ADR-133)\n"
                        f"      | {line.strip()[:120]}"
                    )

    # de-dupe (multiple patterns can flag the same number on one line)
    seen, uniq = set(), []
    for h in hits:
        k = h.split("\n")[0]
        if k not in seen:
            seen.add(k)
            uniq.append(h)

    if uniq:
        print(f"❌ {len(uniq)} live doc line(s) state a stale platform number as current fact:")
        for h in uniq:
            print(f"   {h}")
        print("\nFix the number (ground truth: `python3 scripts/check_doc_facts.py --list`).")
        print('If the line legitimately states history, frame it so ("was N", "N->M", "as of 2026-…")')
        print("or add an inline `<!-- drift-ok: reason -->` marker.")
        sys.exit(1)
    print(f"✅ doc facts OK — no live doc states a stale count/budget ({len(_scan_files())} files scanned).")


if __name__ == "__main__":
    main()
