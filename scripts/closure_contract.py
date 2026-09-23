#!/usr/bin/env python3
"""scripts/closure_contract.py — the closure contract: what a valid issue close requires (#3318).

THE PROBLEM
  The backlog's OPENING side has a contract (ADR-099: filer, score line, body shape,
  liveness floors — `scripts/check_backlog_hygiene.py`). The CLOSING side had none. Session
  K's closure audit (2026-08-30, every closure since 08-16) found 5 escapes in ~60 closes:

    * #2848 — falsely closed by a stray `Fixes` in PR #3253; its author wrote "this issue
      stays OPEN" ~15 minutes AFTER `closedAt`, and nobody noticed for three days.
    * #2670 — a scope assertion posted 2.5 hours after the close, and a correction to the
      closing comment two minutes after it.
    * #2938, #2921, #3208 — closing comments naming a residual in prose with no carrier:
      the #2845 shape, which left the week plan's core work with no open issue (#3314).

  The handover's residual section — which HAS a rule, `not-work — <home>` (#1340) — audited
  clean the same night. The contract shape works; it was only ever applied to one surface.

THIS FILE IS THE REGISTRY (charter primitive 1)
  One executable statement of the definition-of-done for a close, plus the vocabulary both
  detectors and the rendered doc section derive from:

    CLOSURE_CONTRACT          the requirements — id, rule, which detector/gate owns it
    CLOSING_REF_RE            GitHub's closing-keyword grammar, defined ONCE (detector B)
    VERDICT_MARKER / …        the ADR-099 closing-comment shape (detector A's structural key)
    POST_CLOSE_GRACE_MINUTES  the structural window after `closedAt` (detector A)
    DISPOSITIONED_ESCAPES     the dated exemption ledger (charter primitive 3, the ratchet)
    DEFAULT_MODE / mode()     the arming posture — `warn` today, `block` after the bar below

  The `not-work —` tag and the issue-ref grammar are IMPORTED from
  `scripts/check_residual_queue.py` (#1340), never re-typed: the handover rule and the
  closure rule are the same rule on two surfaces, and a second regex is how they drift.

CONSUMERS (each derives, none copies — tests/test_closure_contract_3318.py proves it)
  scripts/closure_sweep.py            detector A — comments after `closedAt`, unhomed
                                      residuals, silent closes, epics closed over open children
  scripts/check_pr_closing_set.py     detector B — the PR's closing set vs the lane's declared
                                      target, epics in the set, GitHub's own linked set
  deploy/wait_pr_green.sh             runs detector B on every merge-eligible verdict
  scripts/wrap_gates.py + /wrap (e8)  runs detector A over THIS session's closures
  docs/CONVENTIONS.md §4a2            the rendered block (`--render`), byte-equal by test

ARMING POSTURE (ADR-108 / #1872 discipline: flip on a measurement, never the calendar)
  `warn` — every finding is printed, exit 0. `block` — findings exit 1; detector B fails
  the watcher's verdict. Flip by editing DEFAULT_MODE with a dated note, once BOTH hold and
  are re-measured at flip time:
    * detector A: FLIP_BAR["consecutive_clean_wraps"] consecutive wraps whose session sweep
      reported zero undispositioned hits (a hit dispositioned in the same session counts as
      clean — that is the contract working, not failing);
    * detector B: FLIP_BAR["real_merges_observed"] real merges watched with ZERO findings
      the driver had to override (an override with a reason is a false positive; log it on
      #3318 so the count is auditable).
  `CLOSURE_CONTRACT_MODE=block` arms a single run without editing this file (the hook
  layer's HOOK_MODE shape, scripts/hooks/_hooklib.py).

  ONE code is exempt from that bar and armed BLOCK from day one: `no-live-proof` (#3595,
  the forensic RCA's class 3). It lives in `BLOCK_CODES`; `arming_for()` returns `block`
  for it whatever the ambient mode says, so `CLOSURE_CONTRACT_MODE=warn` cannot disarm it.
  A code whose false positive is a REOPENED issue does not need a 25-merge flip bar, and
  what warn-mode bought was four instruments reading CLOSED while dead (INT-1 49 days,
  G-3 28, OBS-1 30+, CPO-2 21 runs).

  A SECOND code joined on 2026-09-23: `unhomed-residual` (#3597, the forensic RCA's class 7
  — a deferral with no carrier). Flipped on a measurement (19 of 263 closures since the
  cycle-17 genesis, see `BLOCK_CODES`), and its cue vocabulary now includes the obligation
  words owned by `scripts/obligation_carriers.py` (`revisit`, `fast-follow`, `owner decides`).
  Its false positive is an edited closing comment. The other requirements are unchanged.

USAGE
  python3 scripts/closure_contract.py --render   # the docs/CONVENTIONS.md block, verbatim
  python3 scripts/closure_contract.py --mode     # the effective arming posture
"""

from __future__ import annotations

import ast
import importlib.util
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _residual_queue_module():
    """scripts/check_residual_queue.py — the ONE home of the `not-work —` / `#N` grammar (#1340)."""
    path = Path(__file__).resolve().parent / "check_residual_queue.py"
    spec = importlib.util.spec_from_file_location("_check_residual_queue_1340", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _obligation_carriers_module():
    """scripts/obligation_carriers.py — the one home of the obligation vocabulary (#3597)."""
    name = "_obligation_carriers_3597"
    if name not in sys.modules:
        path = Path(__file__).resolve().parent / "obligation_carriers.py"
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    return sys.modules[name]


_RQ = _residual_queue_module()
ISSUE_REF = _RQ.ISSUE_REF  # `#NNNN` — imported, not copied
NOT_WORK_TAG = _RQ.NOT_WORK_TAG  # `not-work —` (hyphen / en-dash / em-dash) — imported, not copied

# ── arming posture ───────────────────────────────────────────────────────────────────────
MODE_ENV = "CLOSURE_CONTRACT_MODE"
DEFAULT_MODE = "warn"  # flip to "block" with a dated note once FLIP_BAR is met AND re-measured at flip time
MODES = ("warn", "block")
FLIP_BAR = {
    "consecutive_clean_wraps": 10,  # detector A — the ADR-129 re-promotion shape (10 consecutive clean runs)
    "real_merges_observed": 25,  # detector B — watched merges with zero overridden findings
    "overrides_allowed": 0,
}


# Codes armed BLOCK from day one, independent of DEFAULT_MODE and of the env override
# (#3595). See the docstring: the flip bar governs the six rules whose false positive is
# noise; it does not govern the one rule whose false positive is a reopened issue.
#
# 2026-09-23 (#3597): `unhomed-residual` joins, per the issue's own shape ("the closure
# contract's `residual-homed` code flips to block"). Measured at flip time, read-only, over
# every issue closed since the cycle-17 genesis: `closure_sweep.py --since 2026-09-06` scanned
# 263 closures → 19 `unhomed-residual` findings (7%). Its false positive costs an EDIT to a
# closing comment (add the `#N` or the `not-work —` tag), not a reopen — and warn-mode is
# exactly how #2877's "fast-follow, not done here" went unticketed until a review re-found it.
BLOCK_CODES = frozenset({"no-live-proof", "unhomed-residual"})


def mode() -> str:
    """The effective posture: the env override if it names a known mode, else DEFAULT_MODE."""
    value = os.environ.get(MODE_ENV, "").strip().lower()
    return value if value in MODES else DEFAULT_MODE


def arming_for(code: str, ambient: str | None = None) -> str:
    """The posture for ONE finding code. `BLOCK_CODES` always block; everything else rides
    the ambient posture (the caller's mode, or `mode()`)."""
    if code in BLOCK_CODES:
        return "block"
    return ambient if ambient in MODES else mode()


# ── the requirements ─────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Requirement:
    id: str
    rule: str
    detector: str  # which script/gate makes this requirement fail
    finding_codes: tuple  # the finding codes that script emits for it (the wire vocabulary)
    also_detected_by: tuple = ()  # a second detector emitting the SAME codes on a different surface

    @property
    def detectors(self) -> tuple:
        return (self.detector, *self.also_detected_by)


CLOSURE_CONTRACT: tuple = (
    Requirement(
        id="outcome-verdict",
        rule=(
            "Every close carries the ADR-099 closing comment — `**Shipped:** …` + "
            "`**Outcome:** <realized|partial|not-realized> — …` — written by the session that merged "
            "(wrap step (e8)). A close with no verdict is a silent close. EXEMPT: an instrument's own "
            "ledger row (`is_instrument_ledger`) — a bot filed it, no human ever commented, and it "
            "carries no `type:` taxonomy, so there is no human closure for a verdict to describe."
        ),
        detector="scripts/closure_sweep.py",
        finding_codes=("no-outcome-verdict",),
    ),
    Requirement(
        id="residual-homed",
        rule=(
            "A closing comment that names a residual disposes it to EXACTLY one home: a carrier issue "
            "`#N`, a fold onto a named open issue `#N`, or an explicit `not-work — <home>`. This is the "
            "handover's residual-queue rule (#1340, wrap (e4)) applied symmetrically to the close — a "
            "`partial`/`not-realized` verdict with no home is the #2845/#3208 shape."
        ),
        detector="scripts/closure_sweep.py",
        finding_codes=("unhomed-residual",),
    ),
    Requirement(
        id="no-post-close-assertion",
        rule=(
            "Nothing substantive is said on an issue after it closes. A non-bot comment later than "
            "`closedAt` + the grace window that is not the closing verdict is a structural event — the "
            "issue was still being worked, or the close was wrong (#2848, #2670). A post-close comment "
            "saying the issue stays open / must reopen / is not met is a contradiction on record."
        ),
        detector="scripts/closure_sweep.py",
        finding_codes=("post-close-comment", "post-close-assertion"),
    ),
    Requirement(
        id="epic-after-children",
        rule=(
            "An epic closes only after its child set is reconciled — no open issue still declares "
            "`**Epic:** #N` — and is judged by its Outcome sentence, never by child count "
            "(`docs/OPERATING_DISCIPLINE.md` §2.2)."
        ),
        detector="scripts/closure_sweep.py",
        finding_codes=("epic-children-open",),
    ),
    Requirement(
        id="closing-set-declared",
        rule=(
            "A PR's closing set — every `Fixes/Closes/Resolves #N` in the body AND in every commit "
            "message — equals the lane's declared target (the `issue-N-*` branch, or `--target`), the "
            "body and the commits agree, GitHub's own linked set agrees with the parse, and no member is "
            "a `type:epic`. The stray-`Fixes` class: #3222 (PR #3226), #2848 (PR #3253)."
        ),
        detector="scripts/check_pr_closing_set.py",
        finding_codes=(
            "declared-target-mismatch",
            "body-commits-disagree",
            "github-parse-disagree",
            "epic-in-closing-set",
        ),
    ),
    Requirement(
        id="live-proof-before-close",
        rule=(
            "An INSTRUMENT — an alarm, gate, sweep, judge, ledger, scheduled job or fail-soft write — "
            "closes on its first non-degraded LIVE output, never on the merge. Its PR carries `Refs #N`, "
            "not `Fixes #N`, and names the output it will be closed on; the closing comment carries "
            "`**Live proof:** <UTC instant> — <where>`. `Fixes #N` is for product/config/doc fixes a live "
            "curl can prove after deploy. Class 3 of the 2026-09-05 forensic RCA: INT-1 (49 days), G-3 (28), "
            "OBS-1 (30+), CPO-2 (21 runs) all read CLOSED while non-functional."
        ),
        detector="scripts/closure_sweep.py",
        also_detected_by=("scripts/check_pr_closing_set.py",),
        finding_codes=("no-live-proof",),
    ),
    Requirement(
        id="close-the-shipped",
        rule=(
            "A merged commit that names an open issue in its SUBJECT has either closed it or said why not. "
            "Detector B catches a PR closing too MUCH; this is the other direction — the fix ships, the keyword "
            "is forgotten, and the issue sits open until a human re-reads it. Session AF swept 40 open issues by "
            "hand and found 11 already fixed by a merged PR (open 7-17 days); TEN named the issue in the merge "
            "subject with no closing keyword (#3812). An instrument held for its live proof "
            "(`closure:live-proof`, or `**Closure class:** instrument`) and a `type:epic` are correctly unlinked "
            "and are NOT findings. A finding is a question for a human, never a closure."
        ),
        detector="scripts/check_unlinked_closures.py",
        finding_codes=("shipped-unlinked",),
    ),
    Requirement(
        id="partial-is-not-a-close",
        rule=(
            "A PR body that still carries an unchecked acceptance box (`- [ ]`) does not carry a closing "
            "keyword; and a closing keyword closes regardless of negation or tense "
            "(`docs/OPERATING_DISCIPLINE.md` §2.1, §2.5 — #2921 closed itself twice by writing "
            '"does NOT close #2921").'
        ),
        detector="scripts/check_pr_closing_set.py",
        finding_codes=("partial-acceptance-close", "negated-closing-keyword"),
    ),
    Requirement(
        id="validated-merge-text",
        rule=(
            "The closing set of the text that is ACTUALLY COMMITTED is validated, not only the PR body and "
            "branch commits. Detector B's three texts are all pre-merge; `gh pr merge --squash --body-file` "
            "(or `--subject`, or the web UI's editable squash box) supplies a fourth that no pre-merge guard "
            "has seen. On 2026-09-17 that path retired an owner-gated issue because the custom body's note "
            "explaining a removed closing phrase QUOTED the phrase. Two legs: guard_bash.py refuses a supplied "
            "message on the sanctioned path, and detector D compares the merge commit's closing set against "
            "the PR BODY plus GitHub's computed set — deliberately NOT the branch commits, since a commit-only "
            "ref disagreeing with the body is the exact warn that was reasoned past. Each finding carries its "
            "MEASURED effect (did this commit actually retire that issue), so a keyword written at an "
            "already-closed issue is visibly not the same event as a live retirement."
        ),
        detector="scripts/check_merge_commit_closures.py",
        finding_codes=("unvalidated-merge-closure",),
        also_detected_by=("scripts/hooks/guard_bash.py",),
    ),
)

ALL_FINDING_CODES: frozenset = frozenset(code for r in CLOSURE_CONTRACT for code in r.finding_codes)


# ── finding codes must not END in a GitHub closing keyword (#3812) ────────────────────────
# Found the hard way: detector C shipped as `unlinked-shipped-fix`, so its own printed line
#
#     unlinked-shipped-fix  #3830  1 merged commit(s) name #3830 ...
#
# parses as `fix #3830` under CLOSING_REF_RE — GitHub's own grammar. A detector whose REPORT
# is a closing-keyword injection is a live footgun: pasting the sweep output into a PR body
# or a commit message would close every issue it names, which is the exact class detector B
# exists to catch. Renamed to `shipped-unlinked` before it ever ran in anger; detector B is
# what caught it, on this file's own PR.
#
# Dated, shrink-only exemption ledger (charter primitive 3). An entry comes OUT when the code
# is renamed; nothing may be ADDED without renaming being considered first.
CODE_KEYWORD_EXEMPTIONS: dict = {
    "partial-acceptance-close": (
        "2026-09-16 — PRE-EXISTING (#3318). Same defect: `partial-acceptance-close #2848` in a PR "
        "body parses as `close #2848`. NOT renamed here because the code is cited as a historical "
        "record in docs/PROPORTIONALITY.md's rent row (naming the live run that found PR #3253) and "
        "in .claude/skills/land/SKILL.md; rewriting a past run's record to fix a forward-looking "
        "naming rule is the wrong trade at the wrong time. Carried as its own issue."
    ),
}


def codes_ending_in_a_closing_keyword(codes=None) -> dict:
    """Pure. → {code: keyword} for every finding code whose trailing token is a closing keyword.

    Excludes the dated ledger above. The check is on the TRAILING token because that is the
    position CLOSING_REF_RE reads: `<kw>` immediately followed by whitespace and `#N`.
    """
    offenders = {}
    for code in sorted(ALL_FINDING_CODES if codes is None else codes):
        if code in CODE_KEYWORD_EXEMPTIONS:
            continue
        tail = code.rsplit("-", 1)[-1].lower()
        if tail in CLOSING_KEYWORDS:
            offenders[code] = tail
    return offenders


# ── the vocabulary detectors derive from ────────────────────────────────────────────────

# GitHub's closing-keyword grammar (docs: "Linking a pull request to an issue"): one of the
# nine keywords, an optional colon, whitespace, then `#N`, `owner/repo#N`, or an issue URL.
# The keyword must sit IMMEDIATELY before the reference — `fixes the bug in #12` does not link.
CLOSING_KEYWORDS = ("close", "closes", "closed", "fix", "fixes", "fixed", "resolve", "resolves", "resolved")
# GitHub does NOT link a closing reference inside a code span or a code block — a
# backticked `close #123` renders as literal text and closes nothing. The parser here did
# not know that, and the consequence was a FALSE BLOCK: a PR whose commit messages
# *explain* the closing-keyword grammar (quoting `close #2848` and `fix #3830` as examples)
# had its whole closing set read as real, while GitHub's own `closingIssuesReferences`
# correctly returned {} (#3812). Prose ABOUT a closing keyword was indistinguishable from
# a closing keyword — which is a bad property for a detector whose whole job is to be read
# and written about.
#
# The three code forms GitHub honours, stripped in this order (longest fence first, so a
# ``` block containing backticks is not shredded by the span rule):
#   ``` fenced blocks ```      · ~~~ fenced blocks ~~~
#   indented blocks            · a line starting with 4 spaces or a tab
#   `inline spans`             · one or more backticks, matched by run length
#
# Deliberately NOT a markdown parser: it strips more aggressively than GitHub in exotic
# cases, and the failure direction of over-stripping is a MISSED finding rather than a
# false close — detector B reads GitHub's own linked set alongside this parse and reports
# any disagreement in both directions, so a miss here surfaces as `github-parse-disagree`
# rather than sliding through.
_FENCED_RE = re.compile(r"(?ms)^[ \t]*(`{3,}|~{3,}).*?(?:^[ \t]*\1[ \t]*$|\Z)")
_INDENTED_RE = re.compile(r"(?m)^(?: {4,}|\t).*$")
_SPAN_RE = re.compile(r"(`+)(?:.|\n)*?\1")


def strip_code(text: str) -> str:
    """Blank out code fences, indented blocks and inline spans, preserving newlines.

    Newlines are kept so any position-based reporting a caller layers on top still lines
    up with the original text.
    """

    def _blank(m):
        return re.sub(r"[^\n]", " ", m.group(0))

    out = _FENCED_RE.sub(_blank, text or "")
    out = _INDENTED_RE.sub(_blank, out)
    return _SPAN_RE.sub(_blank, out)


CLOSING_REF_RE = re.compile(
    r"\b(?P<kw>" + "|".join(CLOSING_KEYWORDS) + r")\b:?\s+"
    r"(?:https?://github\.com/(?P<url_repo>[\w.-]+/[\w.-]+)/issues/(?P<url_num>\d+)"
    r"|(?P<repo>[\w.-]+/[\w.-]+)?#(?P<num>\d+))",
    re.I,
)
# A negation within a few words before the keyword — the parser above still LINKS these
# (GitHub sees neither the negation nor the tense); this only lets a detector name the trap.
NEGATED_CLOSING_RE = re.compile(
    r"\b(?:not|never|n't|doesn't|does\s+not|won't|will\s+not)\s+(?:\w+\s+){0,2}"
    r"(?:" + "|".join(CLOSING_KEYWORDS) + r")\b:?\s+(?:[\w.-]+/[\w.-]+)?#\d+",
    re.I,
)
UNCHECKED_BOX_RE = re.compile(r"^\s*[-*]\s+\[ \]\s+\S", re.M)
DECLARED_TARGET_RE = re.compile(r"^issue-(\d+)(?:-|$)")  # the lane naming rule: issue-<N>-<slug>
EPIC_LABEL = "type:epic"
EPIC_LINE_RE = re.compile(r"^\s*\*\*Epic:\*\*\s*#(\d+)", re.I | re.M)  # a story's declared parent

# The ADR-099 closing-comment shape (amendment 2026-07-27 ¶3). `**Outcome:**` is the
# structural key: it is the contract's own marker, not a sentiment phrase.
VERDICT_MARKER = re.compile(r"\*\*Outcome:\*\*", re.I)
VERDICT_KIND_RE = re.compile(r"\*\*Outcome:\*\*\s*\**\s*(realized|partial|not-realized)\b", re.I)
SHIPPED_MARKER = re.compile(r"\*\*Shipped:\*\*", re.I)
CONTRACT_SINCE = "2026-07-27"  # closes before the amendment carry no verdict obligation (going-forward-only, ADR-099)

# Detector A's structural window. Measured on the Session K corpus: benign post-close notes
# arrive within seconds to ~2 minutes (#3222's correction at +20s, #2670's at +2m24s); the
# first ESCAPE arrived at +14m59s (#2848 "stays OPEN"). The verdict comment itself is sanctioned
# by SHAPE (VERDICT_MARKER), never by time — (e8) verdicts land 30s to 8h after the close.
POST_CLOSE_GRACE_MINUTES = 10

# The lexical leg (secondary, named as lexical): a post-close comment that says the close
# was wrong. Any hit here is ALSO a hit on the structural leg unless it fell inside the grace.
REOPEN_PHRASES = (
    "stays open",
    "stay open",
    "remains open",
    "reopen",
    "re-open",
    "not met",
    "false auto-close",
    "closed by accident",
    "closed accidentally",
    "partially shipped",
    "not a resolution",
)
REOPEN_PHRASE_RE = re.compile("|".join(re.escape(p) for p in REOPEN_PHRASES), re.I)

# A residual is NAMED lexically (there is no structure for "the thing I did not do"); its
# DISPOSITION is checked structurally (ISSUE_REF / NOT_WORK_TAG on the same line or bullet).
#
# #3597: the OBLIGATION vocabulary (`revisit`, `fast-follow`, `owner decides`, a deferral to
# later/step N) is composed in from `scripts/obligation_carriers.py` — the one home of that
# grammar, shared with the ADR/PROPORTIONALITY/alarm-citation rule — never re-typed here.
# #2877's closing-time "Fast-follow, not done here" for whoop/habitify is the specimen.
RESIDUAL_CUE_RE = re.compile(
    r"\b(residual|left open|leaves? open|remains? (?:open|untouched|unfixed)|not (?:done|satisfied|shipped|observed)|"
    r"unsatisfied|unmet|deferred|follow-?up|out of (?:this )?(?:scope|lane)|still needs|not mine to do)\b|"
    + _obligation_carriers_module().OBLIGATION_CUE_PATTERN,
    re.I,
)
# A cue negated just before it names the ABSENCE of a residual ("none deferred", "no follow-up").
RESIDUAL_NEGATION_RE = re.compile(r"\b(?:none|nothing|no|zero|without|not|never)\b(?:\s+\w+){0,2}\s*$", re.I)
# `PR #2940` / `(#3210)` sha-context cites are not homes — strip before looking for a carrier.
PR_REF_RE = re.compile(r"\bPRs?\s*#\d+", re.I)
BOT_LOGIN_RE = re.compile(r"\[bot\]$|^github-actions$|^dependabot", re.I)


# ── the instrument class + its live proof (#3595) ────────────────────────────────────────
# The class is derived from STRUCTURE, never from a title phrase (the #2959/#3003/#3199
# family: every phrase-matched suppressor in this repo has failed in the field). Three legs,
# in precedence order, each with its own arming:
#   1. DECLARED   `**Closure class:** instrument|product — <reason>` in the PR body. An
#      explicit act by the author; `instrument` BLOCKS a closing keyword, `product` (with a
#      reason of at least PRODUCT_REASON_MIN chars) overrides the label + AST legs.
#   2. LABELLED   the issue carries `closure:live-proof`. Also decisive → BLOCK. This is the
#      leg detector A (the close itself) has: a sweep sees labels, never a diff.
#   3. DERIVED    AST instrument sites in the PR's changed files. ADVISORY (warn): the
#      inference is sound about the code and silent about intent — a product fix that
#      happens to touch a fail-soft write is a real false positive, and its answer is one
#      declaration line, not a blocked merge.
INSTRUMENT_LABEL = "closure:live-proof"
CLOSURE_CLASS_NAMES = ("instrument", "product")
CLOSURE_CLASS_RE = re.compile(r"^\s*\*\*Closure class:\*\*\s*(?P<kind>instrument|product)\b(?P<rest>.*)$", re.I | re.M)
PRODUCT_REASON_MIN = 20  # a `product` override says WHY in the body, or it does not override

# The closing comment's live-proof line. Structural: the marker, an instant, and a where.
LIVE_PROOF_MARKER = re.compile(r"\*\*\s*(?:Live proof|First live output)\s*:?\s*\*\*:?", re.I)
LIVE_PROOF_INSTANT = re.compile(
    r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2})?"
)  # date AND time: "shipped on the 6th" is not an observation
LIVE_PROOF_WHERE_MIN = 8  # chars of "where" after the instant — a bare timestamp names nothing
# Going-forward-only, the CONTRACT_SINCE shape (ADR-099): closes before this date carry no
# live-proof obligation. Reconstructing one for an older close would be AI guesswork on record.
LIVE_PROOF_SINCE = "2026-09-06"

# ── the REHEARSAL-proof leg (owner ruling 2026-09-21: no further resets) ─────────────────
# An instrument whose proof event the owner has ruled will never run live again (the reset
# pipeline and everything gated on "the next reset") cannot produce a live output — waiting
# for one leaves the issue open forever. The owner's ruling (ADR-077 amendment 2026-09-21):
# such a box closes on REHEARSAL proof — a `--dry-run` or a fixture run against scratch data,
# never the live table — recorded structurally as `**Rehearsal proof:** <instant> — <command>
# — <output>`. The leg is OPT-IN by a second label so it can never quietly widen the live-proof
# contract: an issue must carry BOTH `closure:live-proof` and `closure:rehearsal-proof` for a
# rehearsal line to satisfy the sweep; `closure:live-proof` alone still demands a live output.
REHEARSAL_LABEL = "closure:rehearsal-proof"
REHEARSAL_PROOF_MARKER = re.compile(r"\*\*\s*Rehearsal proof\s*:?\s*\*\*:?", re.I)
REHEARSAL_PROOF_COMMAND_MIN = 8  # chars naming the command/fixture after the instant


def names_rehearsal_proof(text: str) -> bool:
    """True when a closing comment carries `**Rehearsal proof:** <instant> — <command> — <output>`.

    Structural like `names_live_proof`: the marker, a date-and-time instant, and at least two
    named parts after it (the command or fixture that ran, and what it printed). A rehearsal
    with no command is an assertion; one with no output is a promise."""
    for line in (text or "").splitlines():
        if not REHEARSAL_PROOF_MARKER.search(line):
            continue
        m = LIVE_PROOF_INSTANT.search(line)
        if not m:
            continue
        # the instant regex stops before a zone token ("Z", "+00:00", " PT") — drop it before splitting
        rest = re.sub(r"^(?:Z|[+-]\d{2}:?\d{2}|\s?(?:UTC|PT|PDT|PST))?", "", line[m.end() :]).strip(" -—–:·")
        parts = [s.strip() for s in re.split(r"\s+[—–-]{1,2}\s+", rest) if s.strip()]
        if len(parts) >= 2 and len(parts[0]) >= REHEARSAL_PROOF_COMMAND_MIN:
            return True
    return False


def rehearsal_proof_accepted(labels) -> bool:
    """The rehearsal leg applies only when the issue carries BOTH labels (opt-in, never a widening)."""
    labels = set(labels or ())
    return INSTRUMENT_LABEL in labels and REHEARSAL_LABEL in labels


# ── the PROOF PROBE (#4022): the live read an instrument issue closes on ─────────────────
# The grammar lives in ONE place — `lambdas/operational/proof_probe.py` — because its
# consumer is a Lambda (the qa-smoke nightly leg `closure_probe_qa`), and nothing under
# scripts/ is ever staged into a Lambda bundle. This registry loads that file by path and
# re-exports it, so the hygiene linter and any session parse a `## Proof probe` block with
# the byte-identical parser the nightly closes on. Never re-typed here.
def _proof_probe_module():
    path = ROOT / "lambdas" / "operational" / "proof_probe.py"
    spec = importlib.util.spec_from_file_location("_proof_probe_4022", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules.setdefault("_proof_probe_4022", mod)  # dataclasses resolve their module by name
    spec.loader.exec_module(mod)
    return mod


PROOF_PROBE = _proof_probe_module()


def parse_proof_probe(body: str):
    """The issue body's `## Proof probe` block (None when absent; `.errors` when malformed)."""
    return PROOF_PROBE.parse_block(body or "")


def proof_probe_problem(body: str, labels) -> str | None:
    """None when the issue needs no probe or declares a valid one; else the advisory text.

    Scope: open `closure:live-proof` issues WITHOUT the rehearsal opt-in — a rehearsal-only
    path (the owner's no-further-resets ruling) has no live output for a probe to read."""
    labels = set(labels or ())
    if INSTRUMENT_LABEL not in labels or REHEARSAL_LABEL in labels:
        return None
    block = parse_proof_probe(body)
    if block is None:
        return "no `## Proof probe` section — the nightly leg cannot close it on its first live output (#4022)"
    if not block.valid:
        return "`## Proof probe` does not parse: " + "; ".join(block.errors)
    return None


# The DERIVED leg's vocabulary — what makes a changed file an instrument, by AST.
INSTRUMENT_WRITE_CALLS = ("put_item", "update_item", "delete_item", "put_object", "publish", "send_email", "send_raw_email")
INSTRUMENT_EMF_CALLS = ("put_metric_data", "emit_skip_metric")


def declared_closure_class(body: str) -> tuple:
    """(kind, reason) from the PR body's `**Closure class:**` marker, or (None, "")."""
    m = CLOSURE_CLASS_RE.search(body or "")
    if not m:
        return (None, "")
    return (m.group("kind").lower(), (m.group("rest") or "").strip(" -—–:"))


def product_class_declared(body: str) -> bool:
    """A `product` declaration only overrides when it says WHY (PRODUCT_REASON_MIN chars)."""
    kind, reason = declared_closure_class(body)
    return kind == "product" and len(reason) >= PRODUCT_REASON_MIN


def names_live_proof(text: str) -> bool:
    """True when a closing comment carries `**Live proof:** <instant> — <where>`.

    Structural on all three parts. A marker with no instant is a promise; an instant with
    nothing after it names no output. Neither is the thing the four dead instruments lacked."""
    for line in (text or "").splitlines():
        if not LIVE_PROOF_MARKER.search(line):
            continue
        m = LIVE_PROOF_INSTANT.search(line)
        if m and len(line[m.end() :].strip(" -—–:·")) >= LIVE_PROOF_WHERE_MIN:
            return True
    return False


def _handler_swallows(handler: ast.ExceptHandler) -> bool:
    """An `except` body that logs and continues — no `raise`, no `sys.exit`, anywhere in it."""
    for n in ast.walk(handler):
        if isinstance(n, ast.Raise):
            return False
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "exit":
            return False
    return True


def _call_name(node: ast.Call) -> str:
    f = node.func
    if isinstance(f, ast.Attribute):
        return f.attr
    if isinstance(f, ast.Name):
        return f.id
    return ""


def instrument_sites(source: str, path: str = "") -> list:
    """[(kind, lineno, detail)] — the AST evidence that a changed file IS an instrument.

    The four shapes the RCA names as detectable (report Part 2): a boto3 write inside a
    try/except that logs and continues; a chronic/skip-class check result; an EMF emitter;
    a CloudWatch alarm construct. Plus the scheduled job, whose first output is by
    definition not the merge. Syntactic and therefore wrong in both directions — which is
    exactly why this leg advises and the declared/labelled legs block."""
    try:
        tree = ast.parse(source or "")
    except SyntaxError:
        return []
    sites: list = []
    swallowed: set = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Try) and any(_handler_swallows(h) for h in node.handlers):
            for stmt in node.body:
                for n in ast.walk(stmt):
                    if isinstance(n, ast.Call) and _call_name(n) in INSTRUMENT_WRITE_CALLS:
                        swallowed.add((n.lineno, _call_name(n)))
    for lineno, name in sorted(swallowed):
        sites.append(("fail-soft-write", lineno, f"{name}() inside a try/except that logs and continues"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = _call_name(node)
            if name in INSTRUMENT_EMF_CALLS:
                sites.append(("emf-emitter", node.lineno, f"{name}()"))
            elif name.endswith("Alarm"):
                sites.append(("cw-alarm", node.lineno, f"{name}(...)"))
            for kw in node.keywords:
                if kw.arg == "schedule" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                    sites.append(("scheduled-job", node.lineno, f"schedule={kw.value.value!r}"))
                elif kw.arg == "chronic" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                    sites.append(("chronic-check", node.lineno, "chronic=True check result"))
    if path:
        sites = [(k, ln, f"{path}:{ln} {d}") for (k, ln, d) in sites]
    return sorted(sites, key=lambda t: (t[1], t[0]))


@dataclass(frozen=True)
class Disposition:
    date: str  # YYYY-MM-DD — the day a human dispositioned the escape
    reason: str  # long enough to prove someone looked (≥ 40 chars, asserted by test)


# THE RATCHET (charter primitive 3). Escapes the sweep would otherwise keep reporting, each
# with the DATED disposition a human gave it. Undated or terse entries fail the test; an entry
# whose issue is later reopened and properly closed can be dropped (the count moves down).
DISPOSITIONED_ESCAPES: dict = {
    3413: Disposition(
        "2026-09-01",
        "Auto-closed by `Fixes #3413` at merge (18:51Z) while its own acceptance still required "
        "post-DEPLOY live proof, which cannot exist until after the merge. The two post-close comments "
        "ARE that evidence (probe 33.9s->12.8s; ai-canary-overall ALARM->OK 12:20:36 PT), not continued "
        "work. Outcome verified realized, no reopen. Structural to `Fixes #N` + deploy-after-merge on any "
        "issue whose acceptance demands a live probe -- not sloppiness, and not fixable by commenting sooner.",
    ),
    2848: Disposition(
        "2026-08-30", "Session K audit: REOPENED — falsely closed by a stray Fixes in PR #3253; author had written 'stays OPEN' post-close"
    ),
    2670: Disposition(
        "2026-08-30",
        "Session K audit: post-closure scope assertion (+2.5h) and a correction (+2m) — outcome held (realized, verified live), no reopen",
    ),
    3208: Disposition(
        "2026-08-30", "Session K audit: closing comment named the #2959 family's residual with no carrier — folded onto #3251"
    ),
    2938: Disposition(
        "2026-08-30", "Session K audit: 'partial — post-fix RED not observed end-to-end' with no carrier — carrier #3315 filed"
    ),
    2921: Disposition(
        "2026-08-30", "Session K audit: closed twice by negated/past-tense keywords before the real close — carrier #3316 filed"
    ),
    3222: Disposition(
        "2026-08-27", "reopened the same night (false auto-close by PR #3226's clobbered body); re-closed by #3227 with a verdict at 13:43Z"
    ),
}


# ── pure predicates shared by the detectors ─────────────────────────────────────────────
def normalize_login(login: str | None) -> str:
    """One spelling for a login that GitHub hands back in two (#3853).

    A GitHub App appears as `github-actions` through the GraphQL `author { login }` field
    (what `closure_sweep.py` reads) and as **`app/github-actions`** through
    `gh issue list --json author` (what `check_backlog_hygiene.py` reads). `BOT_LOGIN_RE`
    is anchored (`^github-actions$`), so the `app/` form did not match and the SAME issue
    read as bot-filed to one caller and human-filed to the other.

    Stripping the prefix is unambiguous rather than a guess: `/` is not a legal character
    in a GitHub login, so nothing that reaches here with one is a username.
    """
    s = (login or "").strip()
    return s.split("/", 1)[1] if s.startswith("app/") else s


def is_bot(login: str | None) -> bool:
    return bool(login) and bool(BOT_LOGIN_RE.search(normalize_login(login)))


def is_instrument_ledger(author: str | None, labels, comment_logins) -> bool:
    """True for an instrument's own alert row — NOT a backlog issue ADR-099 binds.

    Three conditions, all required. A bot FILED it (nobody chose to open it); no human ever
    COMMENTED (nobody engaged, so no one authored the closure a verdict would describe); and it
    carries no `type:` taxonomy (a bot-filed `type:bug` is real backlog, and a silent close of
    one is exactly what `no-outcome-verdict` exists to catch).

    Measured on the live corpus 2026-09-16: of 25 bot-filed issues, the 22 self-closing alert
    rows (`deploy-wedge-alert`, the `area:infra,auto-filed` site-deploy rows) can never satisfy
    the verdict requirement, because the only participant is the instrument. The 3 that carry
    backlog taxonomy already pass it — a human wrote the verdict (#3394, #3724). A gate that
    fires on a class it cannot be satisfied for teaches its readers to skip it.

    The alternative — have the alerter emit a formulaic `**Outcome:**` line — was rejected: a
    generated verdict string minted to clear a proof bar is a synthetic signal, not evidence.
    """
    if not is_bot(author):
        return False
    if any(str(lbl).lower().startswith("type:") for lbl in labels or ()):
        return False
    return not any(not is_bot(login) for login in comment_logins or ())


def has_verdict(text: str) -> bool:
    return bool(VERDICT_MARKER.search(text or ""))


def verdict_kind(text: str) -> str | None:
    m = VERDICT_KIND_RE.search(text or "")
    return m.group(1).lower() if m else None


def homes_in(text: str) -> list:
    """Issue refs that can serve as a residual's home — PR cites stripped — plus `not-work` tags."""
    stripped = PR_REF_RE.sub(" ", text or "")
    homes = ISSUE_REF.findall(stripped)
    if NOT_WORK_TAG.search(stripped):
        homes.append("not-work")
    return homes


def _blocks(text: str) -> list:
    """Top-level bullets (with their continuation lines) or plain lines — the unit a residual is named in."""
    blocks: list = []
    for line in (text or "").splitlines():
        if re.match(r"^\s*(?:[-*]|\d+\.)\s+", line) or not blocks or not line.startswith((" ", "\t")):
            blocks.append(line)
        else:
            blocks[-1] += "\n" + line
    return [b for b in blocks if b.strip()]


def names_residual(block: str) -> bool:
    """True when a block names a residual — a cue word NOT negated within two words before it
    ("none deferred", "nothing left open", "no follow-up needed" name the absence of one)."""
    for m in RESIDUAL_CUE_RE.finditer(block or ""):
        if not RESIDUAL_NEGATION_RE.search(block[max(0, m.start() - 40) : m.start()]):
            return True
    return False


def unhomed_residuals(text: str) -> list:
    """Blocks of a closing comment that NAME a residual and dispose it nowhere.

    A `partial` / `not-realized` verdict line is itself a named residual (the verdict says the
    Outcome was not reached); for that line the home may sit anywhere in the same comment —
    the verdict comment as a whole is the disposition. A cue-bearing bullet must carry its own."""
    hits: list = []
    kind = verdict_kind(text)
    comment_homes = homes_in(text)
    for block in _blocks(text):
        is_verdict_line = bool(VERDICT_MARKER.search(block))
        if is_verdict_line and kind in ("partial", "not-realized"):
            if not comment_homes:
                hits.append(block.strip())
            continue
        if names_residual(block) and not homes_in(block):
            hits.append(block.strip())
    return hits


def closing_refs(text: str, repo: str | None = None) -> list:
    """Every (issue_number, keyword) a closing keyword in `text` would link — GitHub's grammar.

    Same-repo refs (bare `#N`, or `owner/repo` equal to `repo`) come back as ints; cross-repo
    refs (`owner/other#N`, or a URL into another repo) come back as "owner/other#N" strings so
    a caller can name them without mistaking them for a local issue."""
    out: list = []
    for m in CLOSING_REF_RE.finditer(strip_code(text or "")):
        num = m.group("num") or m.group("url_num")
        ref_repo = m.group("repo") or m.group("url_repo")
        if ref_repo and repo and ref_repo.lower() != repo.lower():
            out.append((f"{ref_repo}#{num}", m.group("kw").lower()))
        else:
            out.append((int(num), m.group("kw").lower()))
    return out


def declared_target(branch: str | None) -> int | None:
    """The lane's declared issue from an `issue-<N>-<slug>` branch name, else None."""
    m = DECLARED_TARGET_RE.match(branch or "")
    return int(m.group(1)) if m else None


def epic_parent(body: str) -> int | None:
    m = EPIC_LINE_RE.search(body or "")
    return int(m.group(1)) if m else None


# ── the rendered doc block ───────────────────────────────────────────────────────────────
RENDER_BEGIN = "<!-- BEGIN GENERATED: closure-contract — scripts/closure_contract.py --render (#3318); do not hand-edit -->"
RENDER_END = "<!-- END GENERATED: closure-contract -->"


def render_conventions_block() -> str:
    """The docs/CONVENTIONS.md §4a2 body — derived from CLOSURE_CONTRACT, never a second copy."""
    lines = [RENDER_BEGIN, ""]
    blocked = ", ".join(f"`{c}`" for c in sorted(BLOCK_CODES))
    lines.append(
        "A close is valid when ALL of these hold (registry: `scripts/closure_contract.py`; "
        f"posture: **{DEFAULT_MODE}** — see the flip bar in the registry docstring — except "
        f"{blocked}, armed **block** whatever the posture and not disarmable by the env override):"
    )
    lines.append("")
    for i, r in enumerate(CLOSURE_CONTRACT, 1):
        codes = ", ".join(f"`{c}`" for c in r.finding_codes)
        detectors = " + ".join(f"`{d}`" for d in r.detectors)
        lines.append(f"{i}. **`{r.id}`** — {r.rule} *Detector:* {detectors} → {codes}.")
    lines.append("")
    lines.append(
        f"Structural window: a non-verdict comment more than **{POST_CLOSE_GRACE_MINUTES} min** after `closedAt` is a finding; "
        f"the verdict comment is recognised by its `**Outcome:**` marker, never by timing. "
        f"Dispositioned escapes are the dated ledger `DISPOSITIONED_ESCAPES` ({len(DISPOSITIONED_ESCAPES)} entries) — "
        "an entry needs a date and a reason, and comes OUT when the issue is properly re-closed."
    )
    lines.append("")
    lines.append(
        f"The instrument class is derived STRUCTURALLY, never from a title phrase: a `**Closure class:** "
        f"instrument|product — <reason>` line in the PR body, or the `{INSTRUMENT_LABEL}` label on the issue "
        "(both decisive → block), or AST instrument sites in the PR's changed files — a fail-soft write, an "
        "EMF emitter, a CloudWatch alarm, a scheduled job, a `chronic=True` check result — which advise only. "
        f"Live-proof obligations are going-forward-only from **{LIVE_PROOF_SINCE}**, the ADR-099 CONTRACT_SINCE shape."
    )
    lines.append("")
    lines.append(RENDER_END)
    return "\n".join(lines)


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "--render" in args:
        print(render_conventions_block())
        return 0
    if "--mode" in args:
        print(f"{mode()} (default {DEFAULT_MODE}; override via {MODE_ENV}={'|'.join(MODES)})")
        return 0
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main())
