#!/usr/bin/env python3
"""scripts/backlog_contract.py — the ADR-099 filing-contract parsers (#1866, epic #1863).

ONE CONTRACT, TWO CONSUMERS
  The PM backlog review (2026-07-27, epic #1863) found the scoring apparatus
  "written and never consumed": every issue carries a score line, nothing reads
  it at selection time. Two scripts now do, and they must agree on what the
  contract *is* — so the grammar lives here, once, and both import it:

    - scripts/backlog_next.py        (#1866) — the ranked selector
    - scripts/check_backlog_hygiene.py (#1867) — the filing-contract linter

  If the linter and the ranker ever disagree about what a valid score line
  looks like, the backlog silently splits into "passes lint" and "is
  rankable". Sharing this module is what prevents that.

  The rule holds for every grammar the contract has, not just the score line:
  #1867 needed the `**Epic:**` link and the epic `## Stories` roster parsed, and
  they were added HERE (parse_epic_link / story_refs) rather than compiled inside
  the linter — one contract surface, no second copy to drift.

THE CANONICAL SCORE LINE (ADR-099 amendment 2026-07-27, #1865)

    **Score:** P2 · Impact 3 × Confidence 1.0 / Effort S(1) = 3.00 → Now

  prio token P0–P3 · Impact <int> × Confidence <float> / Effort <S|M|L>(<int>)
  = <float> → <Now|Next|Later>, optionally followed by a free-text
  parenthetical rationale (the sanctioned "(severity→milestone disposition,
  PM-set)" override lives there). The separators are U+00B7 MIDDLE DOT, U+00D7
  MULTIPLICATION SIGN and U+2192 RIGHTWARDS ARROW — not ASCII lookalikes.

  Deliberately one notch wider than the amendment's prose in two places, because
  a *ranker* that drops a well-formed line over a value check is worse than one
  that ranks it: the amendment enumerates P1–P3 (this accepts P0–P3) and pins the
  value to two decimal places (this accepts any decimal). Those are value rules,
  not grammar, and #1867's linter is where they are enforced and reported.

LEGACY GRAMMARS ARE NOT PARSED, THEY ARE REPORTED
  Finding 3 of the epic measured four grammars in the wild (`T4×W4/M`,
  `P2*1.0/L=4 = 0.75`, `P3 → Impact …`, `Impact … (Next)`). `parse_score_line`
  targets ONLY the canonical form and returns None for the rest;
  `find_score_line` still surfaces the raw text so a consumer can say
  "unparseable legacy grammar" out loud instead of dropping the issue. The
  #1868 backfill retires them; until then, honest visibility beats a lenient
  parser that pretends four contracts are one.

Stdlib only — this is imported by wrap-time scripts that must run with no deps.
"""

import re
from typing import Any, Dict, List, NamedTuple, Optional, Tuple

# ── the canonical score line ────────────────────────────────────────────────────
# Anchored, whole-line: a body that merely *quotes* the grammar (as #1865's own
# acceptance criteria do) does not match, because the quote sits inside a
# checkbox item rather than opening the line.
SCORE_LINE_RE = re.compile(
    r"^\*\*Score:\*\*[ \t]+"
    r"(?P<prio>P[0-3])[ \t]+·[ \t]+"
    r"Impact[ \t]+(?P<impact>\d+)[ \t]+×[ \t]+"
    r"Confidence[ \t]+(?P<confidence>\d+(?:\.\d+)?)[ \t]+/[ \t]+"
    r"Effort[ \t]+(?P<effort>[SML])\((?P<effort_points>\d+)\)[ \t]+=[ \t]+"
    r"(?P<value>\d+(?:\.\d+)?)[ \t]+→[ \t]+"
    r"(?P<milestone>Now|Next|Later)"
    r"(?:[ \t].*)?$"
)

# Any line that *claims* to be a score line, canonical or not. Used to tell
# "filed with a legacy grammar" apart from "never scored at all".
SCORE_LINE_PREFIX_RE = re.compile(r"^\*\*(?:Score|Priority score):\*\*", re.IGNORECASE)

# The canonical value section. `## Outcome if fixed` / `## outcome_if_fixed` /
# `## Outcome hypothesis` are the pre-amendment variants and deliberately do NOT
# match — see legacy_outcome_line().
OUTCOME_HEADING_RE = re.compile(r"^#{2,}[ \t]*Outcome[ \t]*$")
LEGACY_OUTCOME_HEADING_RE = re.compile(r"^#{2,}[ \t]*(?:outcome_if_fixed|Outcome if fixed|Outcome hypothesis)\b", re.IGNORECASE)
LEGACY_OUTCOME_INLINE_RE = re.compile(r"^\*\*outcome_if_fixed[:.]?\*\*[:.]?[ \t]*(?P<text>.+)$", re.IGNORECASE)

ACCEPTANCE_HEADING_RE = re.compile(r"^#{2,}[ \t]*Acceptance\b", re.IGNORECASE)
CHECKBOX_RE = re.compile(r"^[ \t]*[-*][ \t]+\[(?P<mark>[ xX])\][ \t]*(?P<text>.*)$")

STORIES_HEADING_RE = re.compile(r"^#{2,}[ \t]*Stories\b", re.IGNORECASE)
ISSUE_REF_RE = re.compile(r"#(?P<number>\d+)")

# The epic-link line, required on every story/bug/chore by the amendment:
#   **Epic:** #1863            — or —   **Epic:** none — stands alone because …
# A silently absent line is a contract violation; an explicit `none` is not, which
# is why the "none" arm parses rather than failing. The reason text is captured but
# NOT required here: "did the author actually give a reason" is a value rule, and
# #1867's linter is where value rules are enforced and reported.
EPIC_LINE_RE = re.compile(
    r"^\*\*Epic:\*\*[ \t]+" r"(?:#(?P<number>\d+)|(?P<none>none)\b[ \t]*(?:[—–:-][ \t]*(?P<reason>.*))?)" r"(?:[ \t].*)?$",
    re.IGNORECASE,
)
EPIC_LINE_PREFIX_RE = re.compile(r"^\*\*Epic:\*\*", re.IGNORECASE)

ANY_HEADING_RE = re.compile(r"^#{1,6}[ \t]")

# Now first — the tiebreak direction, and the fall-through order.
MILESTONE_ORDER: Tuple[str, ...] = ("Now", "Next", "Later")

BLOCKED_LABELS = ("gate:owner",)
BLOCKED_LABEL_PREFIXES = ("blocked:",)

MODEL_LANES = ("sonnet", "opus", "fable")


class Score(NamedTuple):
    """A parsed canonical score line."""

    prio: str  # "P0".."P3"
    impact: int
    confidence: float
    effort: str  # "S" | "M" | "L"
    effort_points: int
    value: float  # the stored rank — impact * confidence / effort_points
    milestone: str  # "Now" | "Next" | "Later"
    raw: str  # the source line, verbatim


class EpicLink(NamedTuple):
    """A parsed `**Epic:**` line. Exactly one of `number` / `is_none` is meaningful."""

    number: Optional[int]  # the epic issue number, for the `#N` form
    is_none: bool  # True for the explicit `none — <reason>` form
    reason: Optional[str]  # the stated reason, for the `none` form
    raw: str  # the source line, verbatim


def normalize(body: Optional[str]) -> str:
    """Body text with CRLF folded and a guaranteed str.

    GitHub happily round-trips CRLF bodies; every regex here is line-anchored,
    so a stray \\r would silently defeat the `$` anchors.
    """
    return (body or "").replace("\r\n", "\n").replace("\r", "\n")


def find_score_line(body: Optional[str]) -> Optional[str]:
    """The first line claiming to be a score line — canonical grammar or not.

    Returning legacy lines is the point: it lets a consumer report "scored with
    a retired grammar" instead of "unscored", which are different facts.
    """
    for line in normalize(body).splitlines():
        stripped = line.strip()
        if SCORE_LINE_PREFIX_RE.match(stripped):
            return stripped
    return None


def parse_score_line(body: Optional[str]) -> Optional[Score]:
    """Parse the canonical ADR-099 score line out of an issue body, or None.

    None means "not the canonical grammar" — which covers both "no score line at
    all" and "a legacy grammar". Use find_score_line() to tell those apart.
    """
    for line in normalize(body).splitlines():
        stripped = line.strip()
        m = SCORE_LINE_RE.match(stripped)
        if not m:
            continue
        return Score(
            prio=m.group("prio"),
            impact=int(m.group("impact")),
            confidence=float(m.group("confidence")),
            effort=m.group("effort"),
            effort_points=int(m.group("effort_points")),
            value=float(m.group("value")),
            milestone=m.group("milestone"),
            raw=stripped,
        )
    return None


def _section_lines(body: Optional[str], heading_re: "re.Pattern[str]") -> List[str]:
    """Lines under the first heading matching `heading_re`, up to the next heading."""
    out: List[str] = []
    in_section = False
    for line in normalize(body).splitlines():
        if heading_re.match(line.strip()):
            in_section = True
            continue
        if in_section:
            if ANY_HEADING_RE.match(line):
                break
            out.append(line)
    return out


def outcome_line(body: Optional[str]) -> Optional[str]:
    """The first non-empty line under the canonical `## Outcome` heading.

    The contract wants one audience-named sentence ("**operator** — …"), so the
    selector can put value in front of the reader rather than one `gh issue
    view` away. Returns None when the canonical section is absent — callers must
    say so out loud rather than printing an empty string (finding 4 visibility).
    """
    for line in _section_lines(body, OUTCOME_HEADING_RE):
        if line.strip():
            return line.strip()
    return None


def legacy_outcome_line(body: Optional[str]) -> Optional[str]:
    """The pre-amendment value statement, if the issue has one.

    Variants measured in the live corpus: `## outcome_if_fixed`,
    `## Outcome if fixed`, `## Outcome hypothesis` headings, and an inline
    `**outcome_if_fixed:** …` line. Reported as legacy, never as canonical —
    #1868 backfills them.
    """
    for line in _section_lines(body, LEGACY_OUTCOME_HEADING_RE):
        if line.strip():
            return line.strip()
    for line in normalize(body).splitlines():
        m = LEGACY_OUTCOME_INLINE_RE.match(line.strip())
        if m and m.group("text").strip():
            return m.group("text").strip()
    return None


def acceptance_items(body: Optional[str]) -> List[Tuple[bool, str]]:
    """(checked, text) for every checkbox under the `## Acceptance` heading.

    Scoped to the section on purpose: bodies legitimately quote checkbox syntax
    elsewhere (epic #1863's `## Stories` list is a task list of its own), so a
    whole-body checkbox count reads an epic's story roster as acceptance
    criteria. Only the section counts.
    """
    items: List[Tuple[bool, str]] = []
    for line in _section_lines(body, ACCEPTANCE_HEADING_RE):
        m = CHECKBOX_RE.match(line)
        if m:
            items.append((m.group("mark").lower() == "x", m.group("text").strip()))
    return items


def find_epic_line(body: Optional[str]) -> Optional[str]:
    """The first line claiming to be the epic link — well-formed or not.

    Same split as find_score_line/parse_score_line: "absent" and "present but
    malformed" are different facts, and a linter has to be able to say which.
    """
    for line in normalize(body).splitlines():
        stripped = line.strip()
        if EPIC_LINE_PREFIX_RE.match(stripped):
            return stripped
    return None


def parse_epic_link(body: Optional[str]) -> Optional[EpicLink]:
    """Parse the canonical `**Epic:** #N` / `**Epic:** none — <reason>` line, or None."""
    for line in normalize(body).splitlines():
        stripped = line.strip()
        m = EPIC_LINE_RE.match(stripped)
        if not m:
            continue
        number = m.group("number")
        reason = (m.group("reason") or "").strip() or None
        return EpicLink(
            number=int(number) if number else None,
            is_none=bool(m.group("none")),
            reason=reason,
            raw=stripped,
        )
    return None


def story_refs(body: Optional[str]) -> List[int]:
    """Issue numbers listed as checkboxes under an epic's `## Stories` heading.

    Section-scoped for the same reason acceptance_items() is: an epic body cites
    plenty of issue numbers in prose (the evidence table, the design constraints),
    and only the task list is the roster that makes epic progress computable.
    """
    refs: List[int] = []
    for line in _section_lines(body, STORIES_HEADING_RE):
        m = CHECKBOX_RE.match(line)
        if not m:
            continue
        ref = ISSUE_REF_RE.search(m.group("text"))
        if ref:
            refs.append(int(ref.group("number")))
    return refs


def label_names(issue: Dict[str, Any]) -> List[str]:
    """Label names from a `gh issue list --json labels` record.

    Tolerates a plain list-of-strings fixture too, matching
    check_story_labels.unlabeled_stories' house style.
    """
    return [lbl.get("name", "") if isinstance(lbl, dict) else str(lbl) for lbl in (issue.get("labels") or [])]


def milestone_title(issue: Dict[str, Any]) -> Optional[str]:
    """The milestone title, or None for an unmilestoned issue."""
    ms = issue.get("milestone")
    if isinstance(ms, dict):
        title = ms.get("title")
        return title or None
    if isinstance(ms, str) and ms:
        return ms
    return None


def blocking_labels(labels: List[str]) -> List[str]:
    """The labels that make an issue un-startable by a session: gate:owner, blocked:*."""
    return [name for name in labels if name in BLOCKED_LABELS or any(name.startswith(p) for p in BLOCKED_LABEL_PREFIXES)]


def is_blocked(labels: List[str]) -> bool:
    return bool(blocking_labels(labels))


def model_lane(labels: List[str]) -> Optional[str]:
    """The fan-out lane (`model:sonnet` -> "sonnet"), or None if unlabeled."""
    for name in labels:
        if name.startswith("model:"):
            lane = name.split(":", 1)[1]
            if lane:
                return lane
    return None


def milestone_rank(milestone: Optional[str]) -> int:
    """Sort rank for a milestone — Now first, unmilestoned last."""
    if milestone in MILESTONE_ORDER:
        return MILESTONE_ORDER.index(milestone)
    return len(MILESTONE_ORDER)
