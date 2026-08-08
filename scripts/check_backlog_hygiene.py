#!/usr/bin/env python3
"""scripts/check_backlog_hygiene.py — the ADR-099 filing-contract linter (#1867, epic #1863).

THE PROBLEM
  Exactly one rule validated a filed issue: `scripts/check_story_labels.py` checks
  that an open `type:story` carries a `model:*` label. Nothing checked the
  milestone, the score line, the acceptance criteria, the epic link, or the
  outcome statement — so a filing that skipped the contract was invisible until
  the next review sweep happened to measure it.

  Not hypothetical: #1858 and #1859, filed 2026-07-27 by a session mid-flight,
  carried no milestone, no score line and no outcome section — invisible to every
  ranked query. Across the corpus the one field that states value was present on
  27 of 68 open issues, and epic→story linkage was prose, so epic progress could
  not be computed.

  `.github/ISSUE_TEMPLATE/` is tombstoned (#1324) and stays that way — agent
  filing via `gh issue create` IS the intake. So the enforcement point has to be a
  linter over the LIVE issue corpus, never a GitHub form.

THE FIX
  Every rule the ADR-099 amendment (2026-07-27, #1865) states, as a pure function
  over the fetched corpus, reported per issue with the rule name attached. The
  grammar itself is never re-implemented here: `scripts/backlog_contract.py` is
  the single parse surface, shared with `scripts/backlog_next.py` (#1866) — this
  module compiles no regex of its own, and a test asserts that.

  This script ABSORBED `check_story_labels.py`'s single `model:*` rule (see
  `rule_one_model_label`) and tightened it (exactly one, not merely "some"). #1872
  deleted that script once this linter was blocking — net script budget for the
  whole program is +1, per ADR-103/144.

BLOCKING BY DEFAULT (the ADR-108 promotion pattern — promoted on measured evidence)
  #1867 landed `--advisory` deliberately: the corpus was known-dirty, and a
  blocking gate on day one would have red the wrap for work nobody had done yet.
  #1868 backfilled it to zero violations; #1872 measured that clean state held
  (56 open issues, 0 violations, re-verified immediately before the flip — see the
  dated ADR-099 amendment in `docs/DECISIONS.md`) and promoted the default from
  print-and-exit-0 to print-and-exit-1. `--advisory` stays available as an
  explicit opt-out (a session that wants the report without the exit code).
  Staleness stays advisory in BOTH modes — an old `Later` issue is a triage
  signal, not a defect.

USAGE
  python3 scripts/check_backlog_hygiene.py                 # blocking (default): exit 1 on any violation
  python3 scripts/check_backlog_hygiene.py --advisory      # explicit opt-out: print, always exit 0
  python3 scripts/check_backlog_hygiene.py --rule score_line_canonical   # one rule at a time
  python3 scripts/check_backlog_hygiene.py --summary       # counts only, no per-issue lines
  python3 scripts/check_backlog_hygiene.py --issues-json FIXTURE.json --now 2026-07-27T00:00:00Z

EXIT CODE: 1 by default when any severity=violation finding exists. 0 with
`--advisory`, always. A live-fetch failure (no network/gh auth) is ALWAYS
fail-open — prints a skip note and exits 0, in EITHER mode, blocking included —
a missing `gh` auth or a network blip must never wedge a wrap.
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any, Callable, Dict, List, NamedTuple, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import backlog_contract as bc  # noqa: E402

REPO = "averagejoematt/life-platform"

# The five sanctioned `## Outcome` audiences. The first four are the north star's,
# verbatim from docs/PLATFORM_NORTH_STAR.md:48 ("Who it's for (four audiences)");
# `operator` is the fifth, made first-class by the ADR-099 amendment (#1865)
# because much of this backlog serves the person or agent running the platform and
# having no honest slot for that is part of what produced audience-free bodies.
# Each value is the set of tokens accepted in the outcome line's lead-in.
AUDIENCES: Dict[str, tuple] = {
    "Reddit newcomers": ("reddit newcomer", "reddit newcomers", "newcomer"),
    "Matthew (the N=1 subject)": ("matthew", "the n=1 subject"),
    "Friends & family": ("friends & family", "friends and family", "family"),
    "Health / quantified-self enthusiasts": ("quantified-self", "quantified self", "qs enthusiast", "health enthusiast"),
    "operator": ("operator",),
}

# The body shape in ADR-099 amendment ¶2 is specified for story/bug/chore. The
# issue's acceptance criteria name story/bug; `type:chore` is the same shape by the
# ADR and is included so a chore cannot be filed as the one exempt type.
WORK_TYPES = ("type:story", "type:bug", "type:chore")

ACCEPTANCE_MIN, ACCEPTANCE_MAX = 3, 5
NOW_LIVENESS_MIN = 3  # ≥3 non-blocked stories on `Now`, or the queue is not live
LATER_STALE_DAYS = 60

VIOLATION = "violation"
ADVISORY = "advisory"


class Finding(NamedTuple):
    """One rule firing on one issue (or on the queue, when `number` is None)."""

    rule: str
    number: Optional[int]
    message: str
    severity: str = VIOLATION


# ── the per-issue context ───────────────────────────────────────────────────────


def build_ctx(issue: Dict[str, Any]) -> Dict[str, Any]:
    """Everything the rules need about one issue, parsed once via the shared contract.

    A plain dict (not a class) so fixtures read as data and every rule below stays
    a trivially testable pure function — the check_story_labels.py house style.
    """
    labels = bc.label_names(issue)
    body = issue.get("body") or ""
    return {
        "number": issue.get("number"),
        "title": issue.get("title") or "",
        "labels": labels,
        "types": [n for n in labels if n.startswith("type:")],
        "areas": [n for n in labels if n.startswith("area:")],
        "models": [n for n in labels if n.startswith("model:")],
        "prios": [n for n in labels if n.startswith("prio:")],
        "milestone": bc.milestone_title(issue),
        "is_epic": "type:epic" in labels,
        "is_work": any(n in WORK_TYPES for n in labels),
        "blocking": bc.blocking_labels(labels),
        "score": bc.parse_score_line(body),
        "raw_score_line": bc.find_score_line(body),
        "outcome": bc.outcome_line(body),
        "legacy_outcome": bc.legacy_outcome_line(body),
        "acceptance": bc.acceptance_items(body),
        "epic_link": bc.parse_epic_link(body),
        "raw_epic_line": bc.find_epic_line(body),
        "story_refs": bc.story_refs(body),
        "updated_at": issue.get("updatedAt") or issue.get("updated_at"),
    }


# ── rule helpers (string ops only — the grammar lives in backlog_contract) ──────


def _audience_lead(outcome: str) -> str:
    """The part of the `## Outcome` line that names the audience.

    The contract shape is `**operator** — <what changes>`, so the audience is the
    bolded lead. Falling back to "text before the first dash" keeps an unbolded
    but well-formed line passing; falling back to the WHOLE line would not, because
    "Matthew" appears in half the outcome sentences on the platform and would
    hand every issue a phantom audience.
    """
    text = outcome.strip()
    if text.startswith("**"):
        end = text.find("**", 2)
        if end != -1:
            return text[2:end]
    for sep in ("—", "–", " - ", ":"):
        if sep in text:
            return text.split(sep, 1)[0]
    return text


def outcome_audience(outcome: Optional[str]) -> Optional[str]:
    """The sanctioned audience named by an outcome line, or None."""
    if not outcome:
        return None
    lead = _audience_lead(outcome).lower()
    for canonical, tokens in AUDIENCES.items():
        if any(token in lead for token in tokens):
            return canonical
    return None


def _score_value_text(raw: str) -> Optional[str]:
    """The rendered value token out of a canonical score line ("3.00"), or None.

    Read off the raw text rather than the parsed float, because "3.0" and "3.00"
    are the same float and only one of them is the contract.
    """
    if "=" not in raw or "→" not in raw:
        return None
    return raw.split("=", 1)[1].split("→", 1)[0].strip() or None


def _parse_iso(stamp: Optional[str]) -> Optional[datetime]:
    """GitHub's `updatedAt` ("2026-07-27T15:04:05Z") as an aware datetime, or None."""
    if not stamp:
        return None
    try:
        parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


# ── per-issue rules ─────────────────────────────────────────────────────────────


def rule_one_type_label(ctx: Dict[str, Any]) -> List[Finding]:
    """Exactly one `type:*`. Zero makes the issue typeless; two make it unfilterable."""
    if len(ctx["types"]) != 1:
        found = ", ".join(ctx["types"]) or "none"
        return [Finding("one_type_label", ctx["number"], f"expected exactly one type:* label, found {len(ctx['types'])} ({found})")]
    return []


def rule_one_area_label(ctx: Dict[str, Any]) -> List[Finding]:
    """Exactly one `area:*` — the routing dimension a session filters on."""
    if len(ctx["areas"]) != 1:
        found = ", ".join(ctx["areas"]) or "none"
        return [Finding("one_area_label", ctx["number"], f"expected exactly one area:* label, found {len(ctx['areas'])} ({found})")]
    return []


def rule_one_model_label(ctx: Dict[str, Any]) -> List[Finding]:
    """Exactly one `model:*` — absorbed scripts/check_story_labels.py's rule (#1349).

    That script's rule was "an open type:story has SOME model:* label"; this one
    tightens it to exactly one and applies it corpus-wide, which is why #1872 could
    delete it — the older script's contract is a strict subset of this rule's.
    """
    if len(ctx["models"]) != 1:
        found = ", ".join(ctx["models"]) or "none"
        return [
            Finding(
                "one_model_label",
                ctx["number"],
                f"expected exactly one model:* label (sonnet|opus|fable), found {len(ctx['models'])} ({found})",
            )
        ]
    return []


def rule_prio_label(ctx: Dict[str, Any]) -> List[Finding]:
    """A `prio:*` label on work issues — priority filterable without parsing a body (#1864)."""
    if not ctx["is_work"]:
        return []
    if len(ctx["prios"]) != 1:
        found = ", ".join(ctx["prios"]) or "none"
        kind = ", ".join(ctx["types"]) or "type-less"
        return [Finding("prio_label", ctx["number"], f"expected exactly one prio:* label on a {kind} issue, found {found}")]
    return []


def rule_milestone(ctx: Dict[str, Any]) -> List[Finding]:
    """A milestone on work issues — without one the issue is invisible to every ranked query."""
    if not ctx["is_work"]:
        return []
    if not ctx["milestone"]:
        return [Finding("milestone", ctx["number"], "no milestone — invisible to every ranked query (Now/Next/Later)")]
    return []


def rule_outcome_audience(ctx: Dict[str, Any]) -> List[Finding]:
    """A `## Outcome` section naming one of the five sanctioned audiences.

    Applies to epics too: the amendment gives both body shapes the same first
    section and the same audience rule.
    """
    if not ctx["outcome"]:
        if ctx["legacy_outcome"]:
            return [
                Finding(
                    "outcome_audience",
                    ctx["number"],
                    "value stated in the retired `outcome_if_fixed` form, not a `## Outcome` section — #1868 converts it",
                )
            ]
        return [Finding("outcome_audience", ctx["number"], "no `## Outcome` section — the issue never states what changes for whom")]
    if not outcome_audience(ctx["outcome"]):
        names = " · ".join(AUDIENCES)
        return [
            Finding(
                "outcome_audience",
                ctx["number"],
                f"`## Outcome` names no sanctioned audience ({names}): {ctx['outcome'][:90]}",
            )
        ]
    return []


def rule_acceptance_count(ctx: Dict[str, Any]) -> List[Finding]:
    """3–5 checkboxes under `## Acceptance` on work issues.

    Section-scoped by backlog_contract.acceptance_items — a whole-body `- [ ]`
    count over-counts, because bodies legitimately quote the token when describing
    the rule (that exact false positive fired on #1867 itself during filing).
    """
    if not ctx["is_work"]:
        return []
    count = len(ctx["acceptance"])
    if count == 0:
        return [Finding("acceptance_count", ctx["number"], "no `## Acceptance` checkboxes — readiness is unstated")]
    if not (ACCEPTANCE_MIN <= count <= ACCEPTANCE_MAX):
        return [
            Finding(
                "acceptance_count",
                ctx["number"],
                f"`## Acceptance` has {count} checkbox(es); the contract is {ACCEPTANCE_MIN}–{ACCEPTANCE_MAX}",
            )
        ]
    return []


def rule_score_line_canonical(ctx: Dict[str, Any]) -> List[Finding]:
    """The canonical score line, whose `→ <milestone>` EQUALS the actual milestone.

    The milestone-agreement half is the one that matters most in practice: a body
    that says `→ Now` on an issue sitting in `Later` reads as ranked work to a
    human and is unreachable to the selector, and neither of them notices.

    The two value checks below are the ones backlog_contract's grammar
    deliberately does not enforce (it accepts P0 and any decimal, so a ranker
    never drops a well-formed line over a value question) — they land here, as
    ADVISORY, because they are cosmetic against an unreachable-work defect.
    """
    if not ctx["is_work"]:
        return []
    score = ctx["score"]
    if not score:
        if ctx["raw_score_line"]:
            return [
                Finding(
                    "score_line_canonical",
                    ctx["number"],
                    f"score line is a retired grammar, not the ADR-099 canonical form: {ctx['raw_score_line'][:110]}",
                )
            ]
        return [Finding("score_line_canonical", ctx["number"], "no `**Score:**` line — the issue carries no stored rank")]

    out: List[Finding] = []
    if ctx["milestone"] and score.milestone != ctx["milestone"]:
        out.append(
            Finding(
                "score_line_canonical",
                ctx["number"],
                f"score line says `→ {score.milestone}` but the issue is on milestone `{ctx['milestone']}`",
            )
        )
    if score.prio == "P0":
        out.append(Finding("score_line_canonical", ctx["number"], "score line uses P0; the amendment enumerates P1–P3", ADVISORY))
    value_text = _score_value_text(score.raw)
    if value_text and (("." not in value_text) or len(value_text.split(".", 1)[1]) != 2):
        out.append(
            Finding(
                "score_line_canonical",
                ctx["number"],
                f"score value `{value_text}` is not two decimal places (`{score.value:.2f}`)",
                ADVISORY,
            )
        )
    if score.effort_points:
        expected = score.impact * score.confidence / score.effort_points
        # Score lines are written by hand at two decimal places, rounded half UP (0.375 → 0.38,
        # 1.125 → 1.13). Agreement means "equal once both sides are rendered that way" — a
        # float-epsilon compare (and float's own half-even `.2f`) false-fires on every exact
        # half boundary, which real Impact × Confidence / Effort combinations hit routinely.
        if _two_dp(expected) != _two_dp(score.value):
            out.append(
                Finding(
                    "score_line_canonical",
                    ctx["number"],
                    f"score value {_two_dp(score.value)} disagrees with its own arithmetic ({score.impact} × {score.confidence} / "
                    f"{score.effort_points} = {_two_dp(expected)})",
                    ADVISORY,
                )
            )
    return out


def _two_dp(value: float) -> str:
    return str(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def rule_epic_link(ctx: Dict[str, Any]) -> List[Finding]:
    """`**Epic:** #N`, or an explicit `**Epic:** none — <reason>`.

    A silently absent line is the violation; an explicit `none` with a reason is
    not — standing alone is a legitimate answer, being unable to tell "standalone"
    from "the author forgot" is not.
    """
    if not ctx["is_work"]:
        return []
    link = ctx["epic_link"]
    if not link:
        if ctx["raw_epic_line"]:
            return [Finding("epic_link", ctx["number"], f"`**Epic:**` line is malformed: {ctx['raw_epic_line'][:110]}")]
        return [Finding("epic_link", ctx["number"], "no `**Epic:**` line — use `**Epic:** #N` or an explicit `**Epic:** none — <reason>`")]
    if link.is_none and not link.reason:
        return [Finding("epic_link", ctx["number"], "`**Epic:** none` carries no reason — the contract is `none — <reason>`")]
    return []


PER_ISSUE_RULES: List[Callable[[Dict[str, Any]], List[Finding]]] = [
    rule_one_type_label,
    rule_one_area_label,
    rule_one_model_label,
    rule_prio_label,
    rule_milestone,
    rule_outcome_audience,
    rule_acceptance_count,
    rule_score_line_canonical,
    rule_epic_link,
]


# ── corpus + queue rules ────────────────────────────────────────────────────────


def rule_epic_story_coverage(ctxs: List[Dict[str, Any]]) -> List[Finding]:
    """An epic's `## Stories` task list covers every open issue naming that epic.

    This is what makes epic progress computable at all (the epic finding: prose
    linkage, `subIssues.totalCount = 0`). Reported against the EPIC, because the
    epic body is where the fix goes. Issues pointing at an epic outside the fetched
    corpus (a closed epic) are skipped rather than guessed at.
    """
    epics = {ctx["number"]: ctx for ctx in ctxs if ctx["is_epic"]}
    out: List[Finding] = []
    for epic_number, epic in sorted(epics.items(), key=lambda kv: kv[0] or 0):
        listed = set(epic["story_refs"])
        claimants = [ctx["number"] for ctx in ctxs if ctx["epic_link"] and ctx["epic_link"].number == epic_number]
        missing = sorted(n for n in claimants if n not in listed)
        if missing:
            refs = ", ".join(f"#{n}" for n in missing)
            out.append(
                Finding(
                    "epic_story_coverage",
                    epic_number,
                    f"`## Stories` omits {len(missing)} issue(s) that name this epic: {refs}",
                )
            )
    return out


def rule_now_liveness(ctxs: List[Dict[str, Any]]) -> List[Finding]:
    """`Now` holds at least 3 stories a session can actually start.

    The measured failure: all three open `Now` stories carried `gate:owner`, so the
    documented seed query returned zero actionable work and the queue was dead
    without anyone being told.
    """
    live = [ctx for ctx in ctxs if ctx["milestone"] == "Now" and "type:story" in ctx["labels"] and not ctx["blocking"]]
    if len(live) >= NOW_LIVENESS_MIN:
        return []
    gated = [ctx for ctx in ctxs if ctx["milestone"] == "Now" and "type:story" in ctx["labels"] and ctx["blocking"]]
    detail = f"{len(live)} non-blocked story(ies) on `Now` (want ≥{NOW_LIVENESS_MIN})"
    if gated:
        detail += f"; {len(gated)} more are gate:owner/blocked:*"
    return [Finding("now_liveness", None, f"Now queue is not live: {detail} — refill it (#1870's wrap step)")]


def rule_later_staleness(ctxs: List[Dict[str, Any]], now: datetime) -> List[Finding]:
    """`Later` issues untouched for >60d — ADVISORY in both modes.

    ADR-099's own maintenance rule (3) — a monthly triage sweep that closes or
    demotes stale issues — has never had an implementation. This is the measurement
    half of it: an old `Later` issue is a triage signal, never a defect, so it can
    never fail the gate even after #1872 flips the default to blocking.

    `now` is injected (never `datetime.now()` inside a rule) so a fixture-driven
    test is deterministic — the golden-tests wall-clock lesson.
    """
    cutoff = now - timedelta(days=LATER_STALE_DAYS)
    stale: List[Finding] = []
    for ctx in ctxs:
        if ctx["milestone"] != "Later":
            continue
        updated = _parse_iso(ctx["updated_at"])
        if updated and updated < cutoff:
            age = (now - updated).days
            stale.append(Finding("later_staleness", ctx["number"], f"on `Later`, untouched for {age}d — close it or promote it", ADVISORY))
    return stale


# ── the whole check ─────────────────────────────────────────────────────────────


def check(issues: List[Dict[str, Any]], now: Optional[datetime] = None) -> List[Finding]:
    """Every rule over the whole fetched corpus, in a stable order."""
    now = now or datetime.now(timezone.utc)
    ctxs = [build_ctx(issue) for issue in issues]
    findings: List[Finding] = []
    for ctx in ctxs:
        for rule in PER_ISSUE_RULES:
            findings.extend(rule(ctx))
    findings.extend(rule_epic_story_coverage(ctxs))
    findings.extend(rule_now_liveness(ctxs))
    findings.extend(rule_later_staleness(ctxs, now))
    return findings


def render(findings: List[Finding], issue_count: int, mode: str, summary_only: bool = False) -> List[str]:
    """The whole report, as lines. Pure, so tests assert on text without capsys."""
    violations = [f for f in findings if f.severity == VIOLATION]
    advisories = [f for f in findings if f.severity == ADVISORY]
    out: List[str] = []

    if not findings:
        out.append(f"OK — {issue_count} open issue(s) satisfy the ADR-099 filing contract.")
        return out

    by_issue: Dict[Any, List[Finding]] = {}
    for finding in findings:
        by_issue.setdefault(finding.number, []).append(finding)

    if not summary_only:
        for number in sorted(by_issue, key=lambda n: (n is not None, n or 0)):
            header = f"#{number}" if number is not None else "QUEUE"
            out.append(f"{header}:")
            for finding in by_issue[number]:
                mark = "!" if finding.severity == VIOLATION else "~"
                out.append(f"  {mark} [{finding.rule}] {finding.message}")
        out.append("")

    counts: Dict[str, int] = {}
    for finding in findings:
        counts[finding.rule] = counts.get(finding.rule, 0) + 1
    out.append(f"BACKLOG HYGIENE — {len(violations)} violation(s) + {len(advisories)} advisory(ies) over {issue_count} open issue(s):")
    for rule, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        out.append(f"  {count:>4}  {rule}")
    out.append("  (~ = advisory, never blocking; ! = violation, blocking by default since #1872)")
    if mode == ADVISORY:
        out.append("ADVISORY MODE (explicit --advisory opt-out) — exiting 0 regardless of violations.")
    return out


# ── I/O ─────────────────────────────────────────────────────────────────────────


def _fetch_live_issues() -> Optional[List[Dict[str, Any]]]:
    try:
        result = subprocess.run(
            [
                "gh",
                "issue",
                "list",
                "-R",
                REPO,
                "--state",
                "open",
                "--json",
                "number,title,labels,milestone,body,updatedAt",
                "--limit",
                "500",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            print(f"check_backlog_hygiene: gh issue list exited {result.returncode}: {result.stderr[:300]}; skipping (advisory).")
            return None
        return json.loads(result.stdout or "[]")
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as e:
        print(f"check_backlog_hygiene: could not fetch live issues via gh ({e}); skipping (advisory).")
        return None


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Lint the open GitHub issue corpus against the ADR-099 filing contract.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--advisory", action="store_true", help="Print violations and always exit 0 — an explicit opt-out (blocking is the default)."
    )
    mode.add_argument(
        "--blocking", action="store_true", help="Exit 1 on any violation. This is already the default; the flag stays for explicit callers."
    )
    parser.add_argument("--rule", action="append", help="Report only these rule name(s); repeatable.")
    parser.add_argument("--summary", action="store_true", help="Counts per rule only, no per-issue lines.")
    parser.add_argument("--now", help="ISO timestamp for the staleness rule (default: now). Injected so tests are deterministic.")
    parser.add_argument(
        "--issues-json", help="Offline fixture path (gh issue list --json number,title,labels,milestone,body,updatedAt output)."
    )
    args = parser.parse_args(argv)

    if args.issues_json:
        issues = json.loads(Path(args.issues_json).read_text(encoding="utf-8"))
    else:
        issues = _fetch_live_issues()
        if issues is None:
            return 0  # fail-open: no gh/network/auth available in this context — ALWAYS, blocking mode included

    now = _parse_iso(args.now) if args.now else None
    findings = check(issues, now=now)
    if args.rule:
        findings = [f for f in findings if f.rule in set(args.rule)]

    mode_name = ADVISORY if args.advisory else "blocking"
    print("\n".join(render(findings, len(issues), mode_name, summary_only=args.summary)))

    if not args.advisory and any(f.severity == VIOLATION for f in findings):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
