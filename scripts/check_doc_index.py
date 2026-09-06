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

4. DEPLOY-SURFACE DOCS (#1322 — blocking) — every live deploy/*.md carries the
   standard status header, and canonical ones respect the same freshness ceiling
   as docs/ (advisory at FRESHNESS_DAYS, BLOCKING at FRESHNESS_HARD_DAYS).
   deploy/README.md sat "Last updated: 2026-05-24" with no header while steering
   operators onto the retired boot-broken manual MCP zip — a deploy-surface doc
   must not be able to sit unverified for months again.

5. SOURCE-NEWER-THAN-VERIFY (#973 — BLOCKING by default since #1965; advisory only
   under --advisory) — for each
   engine doc (docs/engines/*.md), the last-CHANGE date of every declared
   `Sources of truth` file is compared against the doc's Verified date. Last-change is
   the UNION of the git last-commit date and the working tree (#3534): a source with
   uncommitted changes is dated today, so the gate can judge the tree it is about to
   commit and not only the tree already committed — which is what made the reset's own
   rewrite of `config/character_sheet.json` structurally invisible to it. Calendar
   freshness alone (gate 3) misses the real staleness signal: a doc verified
   yesterday against an engine rewritten today stays "fresh" for months. A source
   committed strictly AFTER the verify date flags the doc for re-verification.
   Missing/unparseable metadata is skipped with a note, never a crash.

6. ENGINE-DOC COVERAGE (#2619 — BLOCKING) — gate 5 used to be escapable by being
   incomplete: a docs/engines/*.md with no `**Sources of truth:**` line (or no
   `**Verified:**` stamp) was silently SKIPPED, so the least-maintained doc got the
   least scrutiny. Now an incomplete engine doc FAILS unless it is on the
   ENGINE_DOC_EXEMPT allowlist below with a written reason, and every exemption is
   printed on every run. Silence is no longer an exit.

HEADROOM (#2619, advisory) — every run also reports which gated docs sit at zero
headroom (Verified date == newest declared source's commit date), so the standing
condition is visible BEFORE it reds someone's unrelated PR rather than only when it
does. It is a report, not a failure: see the decision note on HEADROOM_WARN_DAYS.

USAGE:
  python3 scripts/check_doc_index.py             # STRICT — the default since #1965: gate 5 drift FAILS, identical to Docs CI
  python3 scripts/check_doc_index.py --strict    # same as the default (kept so docs-ci.yml's explicit invocation stays valid)
  python3 scripts/check_doc_index.py --advisory  # gate 5 drift reports ("N would RED CI under --strict") instead of failing
  python3 scripts/check_doc_index.py --fresh     # only the freshness + source-drift reports, exit 0

Local == CI (#1965): Docs CI runs `--strict`, which is now the bare command's behavior,
so a locally-green run cannot red CI on engine-doc source drift (the 2026-07-27 incident:
two main pushes redded on drift the flagless local run never surfaced). Caveat: gate 5
reads per-file git dates, so it SKIPS (loudly) on a shallow clone — a full local clone
behaves exactly like Docs CI's fetch-depth: 0 checkout. The #3534 working-tree leg rides
INSIDE that skip deliberately: CI's checkout is never dirty, so the leg only ever adds
signal locally, and preserving the shallow-clone skip keeps local == CI.
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

# ── Gate 6 (#2619): exemption-by-omission is closed ───────────────────────────
# An engine doc missing the `**Sources of truth:**` line or the `**Verified:**` stamp
# is UNGATED — gate 5 structurally cannot see it. That used to be a silent skip, which
# made incompleteness the cheapest way out of the gate: the least-maintained doc got the
# least scrutiny. Exemption is now explicit, written down here, and printed on every
# run. Shrink this map, never grow it silently.
ENGINE_DOC_EXEMPT: dict[str, str] = {
    "CHARACTER_MATH_AUDIT_2026-07.md": (
        "frozen point-in-time audit record (2026-07-11 sweep, engine v1.5.0 / config v1.4.0), not a living doc. "
        "It records what the character math WAS on that date and how each verdict was resolved; re-verifying it "
        "against today's source would destroy the record it exists to keep. Its living companion — the formulas as "
        "they stand today — is docs/engines/CHARACTER.md, which IS gated."
    ),
}

# Zero headroom = a gated doc's Verified stamp lands on the SAME day as its newest
# declared source's last commit, so the next commit to any source reds this gate on
# whoever happens to touch the engine next (#2614 cost a session that way).
#
# DECISION (#2619, option (d) — accept the condition, make it legible):
#   Rejected (a) "re-verify all of them now": buys one day of headroom, and the stamp is
#     a substantive claim rather than a date field — pre-bumping one you have not read
#     the source for is the exact falsehood #2614 was filed to prevent.
#   Rejected (b) "grace window before failing": gate 5 exists precisely because calendar
#     freshness misses source change. A 7-day grace re-opens that hole for 7 days on
#     every engine doc — that is the failure mode, not the fix.
#   Rejected (c) "fail only on material change": materiality is a semantic judgement
#     about formulas, thresholds and line citations. A checker guessing it would either
#     miss real drift or manufacture it; the human read IS the verification.
#   Chosen (d): the drift failure now says what verification means and how to clear it,
#     and the headroom report below surfaces the standing condition on every green run,
#     so it is a known cost rather than an ambush. Same shape as #2610 in the
#     module-size gate — fixed there separately, deliberately not here.
HEADROOM_WARN_DAYS = 0

_DRIFT_REMEDIATION = """
🔧 Clearing engine-doc source drift (#973) — the `Verified:` stamp is a CLAIM, not a date field:
   1. READ the change:  git log --since=<verified-date> -p -- <drifted source>
      (if the line above says "uncommitted working-tree change", the change is not in the
      log yet — read it with `git diff -- <drifted source>`. This is the reset's own case:
      #3534 made the pre-commit tree visible to this gate so the CHARACTER.md re-verify
      reds here instead of being a hand-remembered step carried in the handover.)
   2. DECIDE material or not: did any formula, weight, threshold, roster, state machine
      or contract the doc DOCUMENTS actually move? Say which, either way.
   3. RE-DERIVE every line citation the doc makes into the drifted files — spans shift
      from insertions above them, so a citation can be wrong even when nothing moved.
   4. UPDATE the doc: rewrite the affected sections if material; then bump
      `**Verified:** YYYY-MM-DD` and append a one-line note saying what changed and what
      you re-checked, demoting the previous note to `Prior verify <date>: ...`.
   NEVER bump the date alone — that is a false claim about the doc matching live source
   (#2614). If you cannot verify it honestly, say so on the PR instead of stamping it.
   Convention: docs/CONVENTIONS.md section 8."""

_COVERAGE_REMEDIATION = """
🔧 Clearing an ungated engine doc (#2619): give it the two header lines every other engine
   doc carries — `> **Status:** ... · **Verified:** YYYY-MM-DD`, and a `**Sources of truth:**`
   line whose backticked tokens resolve to real repo files — OR add the filename to
   ENGINE_DOC_EXEMPT in scripts/check_doc_index.py with a written reason.
   Being incomplete is no longer an exemption."""


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


def _working_tree_changed_paths(root=None) -> frozenset:
    """Repo-relative paths with UNCOMMITTED changes, from `git status --porcelain` (#3534).

    WHY THIS EXISTS
      Gate 5 dated every declared source by `git log -1` — COMMIT dates only. The reset
      pipeline (`deploy/restart_pipeline.py`) never commits: it leaves that to the operator
      (:1184) and runs its gate sweep LAST, on a tree full of uncommitted rewrites. So
      `config/character_sheet.json` — git-tracked, rewritten by every reset — was
      structurally invisible to this gate at the exact moment the gate was being asked
      whether the tree was safe to commit. The consequence was a standing lesson instead of
      a gate: HANDOVER_LATEST.md carried "re-verify docs/engines/CHARACTER.md by hand" for
      the NEXT reset, every reset.

      A gate must be able to judge the tree it is about to commit, not only the tree
      already committed.

    Renames are recorded under BOTH names (`R  old -> new`), untracked files count, and a
    git failure returns the empty set rather than raising — this widens the gate, so being
    unable to read it must never NARROW a verdict silently... which is why the caller still
    has the commit-date leg underneath it.
    """
    try:
        out = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=root or ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except Exception:
        return frozenset()
    if out.returncode != 0:
        return frozenset()
    paths = set()
    for line in out.stdout.splitlines():
        if len(line) < 4:
            continue
        rest = line[3:].strip()
        for part in rest.split(" -> "):
            part = part.strip().strip('"')
            if part:
                paths.add(part)
    return frozenset(paths)


def _source_change_date(rel_path: str) -> date | None:
    """The date a declared source LAST CHANGED — committed OR still in the working tree.

    #3534: the union is the whole point. `git log -1` answers "when was this last
    committed"; the question gate 5 actually asks is "has this moved since the doc was
    verified", and an uncommitted rewrite has moved it. A dirty source is dated TODAY (or
    its commit date, if that is somehow later), so a reset's own pre-commit sweep reds on
    the engine doc whose source it just rewrote.
    """
    committed = _git_last_commit_date(rel_path)
    if rel_path not in _working_tree_changed_paths():
        return committed
    today = date.today()
    return today if committed is None or today > committed else committed


def _is_shallow_repository() -> bool:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--is-shallow-repository"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return out.stdout.strip() == "true"
    except Exception:
        return False


def check_engine_source_freshness(git_date_fn=_source_change_date):
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
    if _is_shallow_repository():
        # A shallow clone reports HEAD's date as every file's last commit, which
        # false-drifts every engine doc the day after its Verified stamp. The date
        # is meaningless here — skip loudly rather than flag garbage.
        notes.append("skip drift gate: shallow git clone — per-file commit dates are unreliable (checkout with fetch-depth: 0)")
        return flagged, notes
    for d in _scan_engine_docs():
        rel, sources, verified = d["rel"], d["sources"], d["verified"]
        if d["exempt"]:
            # Not a bare "skip" any more (#2619): an exemption is a written decision and
            # main() prints its reason in full. Gate 6 owns whether it is allowed at all.
            notes.append(f"exempt {rel}: see ENGINE_DOC_EXEMPT")
            continue
        # The next three stay notes HERE, but gate 6 (check_engine_doc_coverage) turns the
        # same three conditions into BLOCKING problems — an ungated engine doc used to
        # escape on this skip alone (#2619).
        if sources is None:
            notes.append(f"skip {rel}: no '**Sources of truth:**' line")
            continue
        if verified is None:
            notes.append(f"skip {rel}: no '**Verified:** YYYY-MM-DD' in header")
            continue
        if not sources:
            notes.append(f"skip {rel}: no source token resolves to a repo file")
            continue
        for source in sources:
            committed = git_date_fn(source)
            if committed is None:
                notes.append(f"skip {rel} ← {source}: git last-commit date unavailable")
                continue
            if committed > verified:
                flagged.append((rel, source, committed.isoformat(), verified.isoformat()))
    return flagged, notes


def _scan_engine_docs() -> list[dict]:
    """Parsed metadata for every docs/engines/*.md — the one place the corpus is read.

    Each entry: {rel, name, sources (list | None), verified (date | None), exempt (str | None)}.
    `sources is None` means the doc has no `**Sources of truth:**` line at all; an empty
    list means it has one but no token on it resolves to a repo file. Both are UNGATED
    states, which is why gate 6 exists.
    """
    out: list[dict] = []
    if not ENGINES.is_dir():
        return out
    for p in sorted(ENGINES.glob("*.md")):
        src = p.read_text(encoding="utf-8")
        v = _VERIFIED_RE.search(src[:600])
        out.append(
            {
                "rel": f"docs/engines/{p.name}",
                "name": p.name,
                "sources": _extract_source_paths(src),
                "verified": date.fromisoformat(v.group(1)) if v else None,
                "exempt": ENGINE_DOC_EXEMPT.get(p.name),
            }
        )
    return out


def check_engine_doc_coverage():
    """Gate 6 (#2619): every docs/engines/*.md is either gated or explicitly exempt.

    Returns (problems, exemptions):
      problems   — BLOCKING. A doc gate 5 structurally cannot see, that nobody wrote a
                   reason for. Being incomplete is no longer a way out of the gate.
      exemptions — [(doc_rel, reason)], printed on every run so an exemption is a
                   visible decision rather than a silent skip.
    """
    problems, exemptions = [], []
    for d in _scan_engine_docs():
        if d["exempt"]:
            exemptions.append((d["rel"], d["exempt"]))
            continue
        missing = []
        if d["sources"] is None:
            missing.append("a `**Sources of truth:**` line")
        elif not d["sources"]:
            missing.append("a `**Sources of truth:**` token that resolves to a repo file")
        if d["verified"] is None:
            missing.append("a `**Verified:** YYYY-MM-DD` stamp in its header")
        if missing:
            problems.append(
                f"engine doc is not gated (#2619): {d['rel']} is missing " + " and ".join(missing) + " — see the remediation note below"
            )
    return problems, exemptions


def engine_doc_headroom(git_date_fn=_source_change_date):
    """Days of headroom each GATED engine doc has before gate 5 reds (#2619).

    headroom = Verified date − newest declared source's last-commit date. ≤0 means the
    NEXT commit to that source fails the gate on whoever makes it. Enumerated from the
    live corpus, never hand-listed — the set moves every time a doc is re-verified.
    Returns rows sorted tightest-first: [(days, doc_rel, source, committed, verified)].
    """
    rows = []
    for d in _scan_engine_docs():
        if d["exempt"] or d["verified"] is None or not d["sources"]:
            continue
        dated = [(git_date_fn(s), s) for s in d["sources"]]
        dated = [(c, s) for c, s in dated if c is not None]
        if not dated:
            continue
        committed, source = max(dated)
        rows.append(((d["verified"] - committed).days, d["rel"], source, committed.isoformat(), d["verified"].isoformat()))
    return sorted(rows)


def check_deploy_docs(deploy_dir=None, today=None):
    """Gate 4 (#1322): the deploy directory's own docs are header-stamped and fresh.

    Every top-level deploy/*.md must carry the standard status header; canonical
    pages must carry a **Verified:** date and respect the freshness ceiling
    (BLOCKING past FRESHNESS_HARD_DAYS). Non-canonical statuses (superseded,
    archive, …) are honest about their age and are freshness-exempt, matching
    gate 3's semantics. deploy/archive/ is not scanned (top-level glob only).

    Returns (problems, stale) mirroring gates 2+3 so main() can merge them.
    """
    deploy_dir = Path(deploy_dir) if deploy_dir else ROOT / "deploy"
    today = today or date.today()
    problems, stale = [], []
    for p in sorted(deploy_dir.glob("*.md")):
        rel = f"deploy/{p.name}"
        src = p.read_text(encoding="utf-8")
        m = _STATUS_RE.search(src[:600])
        if not m:
            problems.append(f"missing status header (> **Status:** …): {rel}")
            continue
        if m.group(1) not in VALID_STATUSES:
            problems.append(f"unrecognized status {m.group(1)!r}: {rel}")
            continue
        if m.group(1) != "canonical":
            continue
        v = _VERIFIED_RE.search(src[:600])
        if not v:
            problems.append(f"canonical deploy doc missing '**Verified:** YYYY-MM-DD': {rel}")
            continue
        d = date.fromisoformat(v.group(1))
        if today - d > timedelta(days=FRESHNESS_DAYS):
            stale.append((str(today - d).split(",")[0], rel, v.group(1)))
        if today - d > timedelta(days=FRESHNESS_HARD_DAYS):
            problems.append(f"deploy-surface doc unverified > {FRESHNESS_HARD_DAYS}d (re-verify + bump the header): {rel} ({v.group(1)})")
    return problems, stale


def main():
    fresh_only = "--fresh" in sys.argv
    # #1965: strict is the DEFAULT — Docs CI and every documented local path run the
    # same gate, so local green == CI green by construction. `--advisory` opts out
    # (drift prints a loud would-RED-CI banner instead of failing); `--strict` is
    # still accepted as an explicit no-op (docs-ci.yml passes it).
    advisory = "--advisory" in sys.argv
    strict = not advisory
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

    # 4. deploy-surface docs (#1322) — headers required, canonical freshness BLOCKING
    dep_problems, dep_stale = check_deploy_docs(today=today)
    if not fresh_only:
        problems += dep_problems
    stale += dep_stale

    # 5. source-newer-than-verify (#973) — BLOCKING by default (#1965), advisory under --advisory
    flagged, notes = check_engine_source_freshness()
    if flagged and strict and not fresh_only:
        # Grouped per doc (#2619): one line naming the doc, its stamp and EVERY source
        # that moved. The old per-source lines made one two-source drift read as two
        # separate docs in need of verification.
        by_doc: dict[tuple[str, str], list[tuple[str, str]]] = {}
        for doc_rel, source_rel, committed, verified in flagged:
            by_doc.setdefault((doc_rel, verified), []).append((source_rel, committed))
        dirty = _working_tree_changed_paths()
        for (doc_rel, verified), srcs in sorted(by_doc.items()):
            # #3534: say WHICH leg flagged it. "committed 2026-09-05" on a file that is
            # still sitting uncommitted in the tree reads as a lie and sends the operator
            # to `git log`; "uncommitted working-tree change" sends them to `git status`,
            # which is where the change actually is.
            detail = ", ".join(
                f"{s} ({'uncommitted working-tree change, ' + c if s in dirty else 'committed ' + c})" for s, c in sorted(srcs)
            )
            problems.append(
                f"engine-doc source drift (strict): {doc_rel} — verified {verified}, but {len(srcs)} declared source(s) moved since: {detail}"
            )

    # 6. engine-doc coverage (#2619) — an incomplete engine doc FAILS rather than skips
    cov_problems, exemptions = check_engine_doc_coverage()
    if not fresh_only:
        problems += cov_problems

    if problems:
        print(f"❌ {len(problems)} wiki index/header problem(s):")
        for pr in problems:
            print(f"   {pr}")
        # #2619 (d): a gate that reds without saying how to clear it costs a session
        # every time it fires. Print the remediation for whichever engine gate spoke.
        if any(pr.startswith("engine-doc source drift") for pr in problems):
            print(_DRIFT_REMEDIATION)
        if any(pr.startswith("engine doc is not gated") for pr in problems):
            print(_COVERAGE_REMEDIATION)
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
        # Only reachable in --advisory / --fresh runs (the strict default exits above).
        # The banner names the CI consequence so an advisory green can't be mistaken
        # for a CI green (#1965 regression guard — asserted by unit test).
        print(f"\n🔴 {len(flagged)} advisory item(s) would RED CI under --strict (#973 engine-doc source drift):")
        for doc_rel, source_rel, committed, verified in flagged:
            print(f"   {doc_rel} (verified {verified}) ← {source_rel} committed {committed} — re-verify the doc + bump its header")
    else:
        print("\n✅ engine-doc sources (#973): no 'Sources of truth' file newer than its doc's Verified date.")
    for note in notes:
        print(f"   (note) {note}")

    # Headroom report (#2619) — the standing condition, enumerated from the live corpus
    # on every run so it is visible BEFORE it reds an unrelated PR. Advisory by decision (d).
    tight = [row for row in engine_doc_headroom() if row[0] <= HEADROOM_WARN_DAYS]
    if tight:
        print(
            f"\n⚠️  engine-doc headroom (#2619): {len(tight)} gated doc(s) at ≤{HEADROOM_WARN_DAYS}d — the NEXT commit to a listed source reds this gate:"
        )
        for days, doc_rel, source, committed, verified in tight:
            print(f"   {doc_rel} (verified {verified}) ← newest source {source} committed {committed} — {days}d headroom")
        print(
            "   Accepted, not a failure (#2619 decision (d)). Re-verify when it actually reds; never pre-bump a stamp you have not checked."
        )

    # Exemptions print on every run — an exempt doc must never be a silent skip (#2619).
    for rel, reason in exemptions:
        print(f"\n🛈 engine-doc gate EXEMPT (#2619): {rel}\n   reason: {reason}")


if __name__ == "__main__":
    main()
