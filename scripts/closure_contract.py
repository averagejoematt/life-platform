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

USAGE
  python3 scripts/closure_contract.py --render   # the docs/CONVENTIONS.md block, verbatim
  python3 scripts/closure_contract.py --mode     # the effective arming posture
"""

from __future__ import annotations

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


def mode() -> str:
    """The effective posture: the env override if it names a known mode, else DEFAULT_MODE."""
    value = os.environ.get(MODE_ENV, "").strip().lower()
    return value if value in MODES else DEFAULT_MODE


# ── the requirements ─────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Requirement:
    id: str
    rule: str
    detector: str  # which script/gate makes this requirement fail
    finding_codes: tuple  # the finding codes that script emits for it (the wire vocabulary)


CLOSURE_CONTRACT: tuple = (
    Requirement(
        id="outcome-verdict",
        rule=(
            "Every close carries the ADR-099 closing comment — `**Shipped:** …` + "
            "`**Outcome:** <realized|partial|not-realized> — …` — written by the session that merged "
            "(wrap step (e8)). A close with no verdict is a silent close."
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
)

ALL_FINDING_CODES: frozenset = frozenset(code for r in CLOSURE_CONTRACT for code in r.finding_codes)

# ── the vocabulary detectors derive from ────────────────────────────────────────────────

# GitHub's closing-keyword grammar (docs: "Linking a pull request to an issue"): one of the
# nine keywords, an optional colon, whitespace, then `#N`, `owner/repo#N`, or an issue URL.
# The keyword must sit IMMEDIATELY before the reference — `fixes the bug in #12` does not link.
CLOSING_KEYWORDS = ("close", "closes", "closed", "fix", "fixes", "fixed", "resolve", "resolves", "resolved")
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
RESIDUAL_CUE_RE = re.compile(
    r"\b(residual|left open|leaves? open|remains? (?:open|untouched|unfixed)|not (?:done|satisfied|shipped|observed)|"
    r"unsatisfied|unmet|deferred|follow-?up|out of (?:this )?(?:scope|lane)|still needs|not mine to do)\b",
    re.I,
)
# A cue negated just before it names the ABSENCE of a residual ("none deferred", "no follow-up").
RESIDUAL_NEGATION_RE = re.compile(r"\b(?:none|nothing|no|zero|without|not|never)\b(?:\s+\w+){0,2}\s*$", re.I)
# `PR #2940` / `(#3210)` sha-context cites are not homes — strip before looking for a carrier.
PR_REF_RE = re.compile(r"\bPRs?\s*#\d+", re.I)
BOT_LOGIN_RE = re.compile(r"\[bot\]$|^github-actions$|^dependabot", re.I)


@dataclass(frozen=True)
class Disposition:
    date: str  # YYYY-MM-DD — the day a human dispositioned the escape
    reason: str  # long enough to prove someone looked (≥ 40 chars, asserted by test)


# THE RATCHET (charter primitive 3). Escapes the sweep would otherwise keep reporting, each
# with the DATED disposition a human gave it. Undated or terse entries fail the test; an entry
# whose issue is later reopened and properly closed can be dropped (the count moves down).
DISPOSITIONED_ESCAPES: dict = {
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
def is_bot(login: str | None) -> bool:
    return bool(login) and bool(BOT_LOGIN_RE.search(login or ""))


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
    for m in CLOSING_REF_RE.finditer(text or ""):
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
    lines.append(
        "A close is valid when ALL of these hold (registry: `scripts/closure_contract.py`; "
        f"posture: **{DEFAULT_MODE}** — see the flip bar in the registry docstring):"
    )
    lines.append("")
    for i, r in enumerate(CLOSURE_CONTRACT, 1):
        codes = ", ".join(f"`{c}`" for c in r.finding_codes)
        lines.append(f"{i}. **`{r.id}`** — {r.rule} *Detector:* `{r.detector}` → {codes}.")
    lines.append("")
    lines.append(
        f"Structural window: a non-verdict comment more than **{POST_CLOSE_GRACE_MINUTES} min** after `closedAt` is a finding; "
        f"the verdict comment is recognised by its `**Outcome:**` marker, never by timing. "
        f"Dispositioned escapes are the dated ledger `DISPOSITIONED_ESCAPES` ({len(DISPOSITIONED_ESCAPES)} entries) — "
        "an entry needs a date and a reason, and comes OUT when the issue is properly re-closed."
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
