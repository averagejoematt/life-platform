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
        # #1235: the experiment anchor — genesis date (str) + cycle number (int). Same
        # single-source discovery: EXPERIMENT_START_DATE in lambdas/constants.py and
        # max(CYCLE_GENESES) in lambdas/web/site_api_data.py, surfaced through the sync tool.
        "experiment_genesis": facts.get("experiment_genesis"),
        "experiment_cycle": facts.get("experiment_cycle"),
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
# #1230: `original`/`reference`/`calibrat` cover the source scan's one legitimate $75 —
# cost_governor's `_THRESHOLD_REFERENCE_CEILING = 75.0`, the ORIGINAL ADR-063 anchor the
# tier bands scale from (documented as such); that $75 is a real constant, not a stale claim.
HISTORICAL = re.compile(
    r"\bwas\b|\bwere\b|->|→|raised|lowered|formerly|previously|used to|as of\s*\d"
    r"|grew from|up from|down from|pre-#|earlier|drift-ok|no longer|retired|superseded"
    r"|\boriginal\b|\breference\b|calibrat",
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


# ── #1230: SOURCE-literal ceiling scan (lambdas/) ─────────────────────────────
# The doc gate above polices prose; this polices CODE. A hardcoded ceiling dollar
# amount baked into a value literal or a user-facing string — the exact defect #1230
# fixed: `"budget_ceiling_usd": 75` in the public inference receipt + `"the $75 ceiling
# ..."` in its note — is a lie the moment the ceiling moves, and ADR-133 moved it ($85
# base / $100 surge). The live ceiling must be READ from the governor's
# /life-platform/budget-breakdown param, never hardcoded.
#
# PRECISION: we scan CODE/STRING/DATA literals but SKIP full-line `#` comments and any
# HISTORICAL-framed line. $75 legitimately survives in this tree as the ORIGINAL
# calibration reference (cost_governor._THRESHOLD_REFERENCE_CEILING = 75.0 + the comments
# that explain it) — policing comments would false-flag that real constant. The defect
# class that ever reaches a reader is always a literal/string, never an inline comment.
SRC_ROOTS = (ROOT / "lambdas",)
# a ceiling-named dict/JSON key assigned a bare integer, e.g. `"budget_ceiling_usd": 75`.
# `(?!\.\d)` skips floats like `"ceiling": 100.0` so a real breakdown dict never trips.
CEILING_LITERAL = re.compile(r"""["']?[A-Za-z_]*ceiling[A-Za-z_]*["']?\s*:\s*(\d{2,3})\b(?!\.\d)""")


def _scan_source_files() -> list[Path]:
    out = []
    for root in SRC_ROOTS:
        if root.exists():
            out += sorted(root.rglob("*.py"))
    return out


def _source_hits(files) -> list[str]:
    """Stale hardcoded ceiling literals in `files`.

    Two shapes: a ceiling-named dict key with a bare-int value (`"budget_ceiling_usd": 75`)
    and a `$NN` figure glued to a ceiling word inside a source string. Skips full-line `#`
    comments and any HISTORICAL-framed line (see the SRC scan note above). Exposed so the
    regression test can plant a violation in a scratch file and prove the rule bites.
    """
    hits = []
    for src in files:
        try:
            rel = src.relative_to(ROOT)
        except ValueError:
            rel = src  # scratch file outside the repo (the non-vacuous test)
        for lineno, line in enumerate(src.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.lstrip()
            if stripped.startswith("#") or HISTORICAL.search(line):
                continue
            flagged = set()
            for mo in CEILING_LITERAL.finditer(line):
                amt = _to_int(mo.group(1))
                if amt is not None and amt not in BUDGET_OK and amt >= 50:
                    flagged.add(amt)
            for mo in BUDGET_NEAR.finditer(line):
                amt = int(mo.group(1) or mo.group(2))
                if amt not in BUDGET_OK and amt >= 50:
                    flagged.add(amt)
            for amt in sorted(flagged):
                hits.append(
                    f"{rel}:{lineno}: hardcoded ${amt} budget ceiling, truth is $85 base / $100 surge (ADR-133)\n"
                    f"      | {stripped[:120]}"
                )
    return hits


# ── #1235: experiment genesis + cycle anchor scan (docs) ──────────────────────
# The current experiment anchor is stated in prose as the "currently <genesis>, cycle N"
# frame (CLAUDE.md restart section) and "EXPERIMENT_START_DATE (currently <genesis>)"
# (SCHEMA.md phase taxonomy). Both drift the instant a reset re-anchors the experiment —
# exactly this defect: CLAUDE.md said cycle 5 / 2026-07-12 three days into cycle 6 /
# 2026-07-13, with no gate targeting the line. Ground truth: EXPERIMENT_START_DATE
# (lambdas/constants.py) + max(CYCLE_GENESES) (lambdas/web/site_api_data.py), both surfaced
# through sync_doc_metadata's discoverers (the ONE source, same as every fact above).
#
# PRECISION: the date/cycle are bound to the word "currently" (the current-anchor frame),
# NEVER a bare "genesis <date>" or "cycle N" — those legitimately name synthetic drill dates
# ("synthetic genesis 2026-08-02" in a RUNBOOK dry-run record) and historical cycles ("the
# tombstoned cycle-5 brief"). HISTORICAL-framed lines are exempt as everywhere else.
GENESIS_ANCHOR = re.compile(r"currently[ *]{1,4}(\d{4}-\d{2}-\d{2})", re.I)
CYCLE_ANCHOR = re.compile(r"currently[ *]{1,4}\d{4}-\d{2}-\d{2}[ *]*,?\s*cycle\s+(\d+)", re.I)


def _anchor_hits(files, genesis: str, cycle: int) -> list[str]:
    """Live doc lines stating a stale experiment genesis/cycle as the CURRENT anchor.

    Scans each doc Path for the "currently <genesis>[, cycle N]" frame and flags any date
    != `genesis` or cycle != `cycle`. Skips HISTORICAL-framed lines. Exposed so the
    regression test can plant a stale anchor in a scratch file and prove the rule bites
    (the #1189 non-vacuous-scan lesson).
    """
    hits = []
    for doc in files:
        try:
            rel = doc.relative_to(ROOT)
        except ValueError:
            rel = doc  # scratch file outside the repo (the non-vacuous test)
        for lineno, line in enumerate(doc.read_text(encoding="utf-8").splitlines(), 1):
            if HISTORICAL.search(line):
                continue
            for mo in GENESIS_ANCHOR.finditer(line):
                if mo.group(1) != genesis:
                    hits.append(
                        f"{rel}:{lineno}: experiment genesis claims {mo.group(1)}, truth is {genesis} (#1235)\n"
                        f"      | {line.strip()[:120]}"
                    )
            for mo in CYCLE_ANCHOR.finditer(line):
                if _to_int(mo.group(1)) != cycle:
                    hits.append(
                        f"{rel}:{lineno}: experiment cycle claims {mo.group(1)}, truth is {cycle} (#1235)\n" f"      | {line.strip()[:120]}"
                    )
    return hits


# ── #1205: cron-table drift scan (docs vs cdk/stacks/*.py) ────────────────────
# The highest-stakes operational claim in the wiki is the compute/email cron table
# in ARCHITECTURE.md: an incident responder reads it to reason about run order (do the
# computes finish BEFORE the 17:00 brief?). It drifted 2 months stale — the doc said the
# computes run 17:20-17:35 UTC (AFTER the brief) while compute_stack.py had moved them to
# 16:30-16:45 (BEFORE it, Phase 3.1) — and NO gate caught it. This rule makes every
# `cron(...)` a reader quotes next to a Lambda function name a synced fact: it is diffed
# against that function's `schedule=`/`Schedule.expression("cron(...)")` string in the CDK.
#
# PRECISION (the whole game — a false-positive gate gets disabled):
#   • Ground truth is the CDK: function_name -> cron, parsed per-function-block so a
#     schedule never leaks to the wrong function. Templated crons (`cron(0 {INGEST_HOURLY}
#     ...)`) are dropped — a resolved doc value can't be diffed against a template.
#   • A doc line is compared ONLY when it names EXACTLY ONE known CDK function (matched
#     hyphen-aware, so `wednesday-chronicle` never matches inside `wednesday-chronicle-
#     schedule`) AND quotes EXACTLY ONE cron — the unambiguous "one row, one function,
#     one cron" shape of the table. Multi-cron / multi-function lines are skipped.
#   • HISTORICAL-framed lines are exempt as everywhere else. Frozen snapshots
#     (docs/reviews/, docs/archive/) and ledgers (CHANGELOG) are already out of scope via
#     _scan_files()'s EXEMPT_DIRS/EXEMPT_FILES, so stale review-bundle tables don't trip it.
CDK_STACKS_DIR = ROOT / "cdk" / "stacks"
CRON_RE = re.compile(r"cron\([^)]*\)")
_CDK_FUNC_RE = re.compile(r'function_name\s*=\s*"([^"]+)"')
_CDK_SCHED_RE = re.compile(r'schedule\s*=\s*(?:events\.Schedule\.expression\(\s*)?"(cron\([^"]*\))"')


def _cdk_cron_map() -> dict:
    """function_name -> cron expression, parsed from cdk/stacks/*.py.

    Each function's schedule is searched only within its own block (up to the next
    `function_name=`), so an unscheduled function can't inherit a neighbour's cron.
    Templated crons (containing `{`) are dropped — they can't be diffed against a
    resolved doc value.
    """
    cmap: dict = {}
    if not CDK_STACKS_DIR.exists():
        return cmap
    for f in sorted(CDK_STACKS_DIR.glob("*.py")):
        txt = f.read_text(encoding="utf-8")
        funcs = list(_CDK_FUNC_RE.finditer(txt))
        for i, fm in enumerate(funcs):
            name = fm.group(1)
            end = funcs[i + 1].start() if i + 1 < len(funcs) else len(txt)
            sm = _CDK_SCHED_RE.search(txt, fm.end(), end)
            if not sm:
                continue
            cron = sm.group(1)
            if "{" in cron:  # templated (e.g. INGEST_HOURLY) — unresolvable, skip
                continue
            cmap.setdefault(name, cron)
    return cmap


def _cron_hits(files, cdk_map: dict) -> list[str]:
    """Live doc lines quoting a cron that disagrees with the CDK schedule for the same
    function. Exposed so the regression test can plant a stale cron in a scratch file and
    prove the rule bites (the #1189 non-vacuous-scan lesson)."""
    if not cdk_map:
        return []
    name_res = {n: re.compile(r"(?<![\w-])" + re.escape(n) + r"(?![\w-])") for n in cdk_map}
    hits = []
    for doc in files:
        try:
            rel = doc.relative_to(ROOT)
        except ValueError:
            rel = doc  # scratch file outside the repo (the non-vacuous test)
        for lineno, line in enumerate(doc.read_text(encoding="utf-8").splitlines(), 1):
            if HISTORICAL.search(line):
                continue
            crons = CRON_RE.findall(line)
            if len(crons) != 1:
                continue  # 0 crons, or ambiguous multi-cron line — can't pair reliably
            named = [n for n, rx in name_res.items() if rx.search(line)]
            if len(named) != 1:
                continue  # no CDK function named, or ambiguous multi-function line
            name, doc_cron, cdk_cron = named[0], crons[0], cdk_map[named[0]]
            if doc_cron != cdk_cron:
                hits.append(
                    f"{rel}:{lineno}: cron for `{name}` claims {doc_cron}, CDK schedules {cdk_cron} (#1205)\n"
                    f"      | {line.strip()[:120]}"
                )
    return hits


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

    # #1230: same ground truth, now over the SOURCE tree — no hardcoded ceiling in code.
    hits += _source_hits(_scan_source_files())

    # #1235: no live doc states a stale experiment genesis/cycle as the current anchor.
    hits += _anchor_hits(_scan_files(), truth["experiment_genesis"], truth["experiment_cycle"])

    # #1205: no live doc quotes a cron that disagrees with the CDK schedule (the compute
    # cron table is the highest-stakes operational claim — it drifted 2 months stale).
    hits += _cron_hits(_scan_files(), _cdk_cron_map())

    # de-dupe (multiple patterns can flag the same number on one line)
    seen, uniq = set(), []
    for h in hits:
        k = h.split("\n")[0]
        if k not in seen:
            seen.add(k)
            uniq.append(h)

    if uniq:
        print(f"❌ {len(uniq)} live doc/source line(s) state a stale platform number as current fact:")
        for h in uniq:
            print(f"   {h}")
        print("\nFix the number (ground truth: `python3 scripts/check_doc_facts.py --list`).")
        print('If the line legitimately states history, frame it so ("was N", "N->M", "as of 2026-…")')
        print("or add an inline `<!-- drift-ok: reason -->` marker.")
        sys.exit(1)
    print(
        f"✅ doc + source facts OK — no live doc/source states a stale count/budget "
        f"({len(_scan_files())} docs + {len(_scan_source_files())} source files scanned)."
    )


if __name__ == "__main__":
    main()
