"""regen_keep_predicate.py — #3217: WHICH of {original, rewrite} `regen_once` keeps.

The one decision `grounded_generation.regen_once` makes, lifted out of it so it can be
exercised directly on adversarial inputs instead of only through a model call.

## The defect this exists to fix

Until #3217 the decision was one line — ``len(after) < len(before)`` — a comparison of
two UNDIFFERENTIATED finding counts across a dozen heterogeneous classes. That total is a
composite, and a composite can veto a correctness fix: on the 2026-08-26 17:00Z brief
`nutrition_coach`'s draft cited ``326.3`` (the upper bound of a weight-prediction interval
that appears nowhere in the data it was given), the corrective rewrite REMOVED that
figure, the rewrite's total finding count did not fall, and the rewrite was discarded.
The draft carrying the invented number is the one that reached the blocking gate, with no
``grounding self-corrected`` line anywhere in the log.

ADR-104/105 make a deterministic grounding finding non-overrulable at the BLOCKING gate
precisely because "the narrative states a figure the data does not contain" is categorical,
not a matter of degree. Letting an aggregate count veto the removal of one at generation
time inverts that ordering in the one place where a cheap fix was still in hand.

## The predicate

Two independent arms; the rewrite is kept if EITHER fires.

* ``strictly_fewer`` — ``len(after) < len(before)``. The pre-#3217 rule, unchanged. Every
  caller that was already correcting keeps correcting exactly as it did.
* ``figure_grounding_removed`` — the rewrite's FIGURE findings (`FIGURE_TYPES` below) are a
  strict sub-multiset of the original's: it removed at least one and introduced none. This
  fires independently of the total, which is the whole point — a rewrite that trades an
  invented figure for two framing-scope findings is kept.

Otherwise the rewrite is discarded, under one of two named arms so the log says which
predicate dropped it (the ``326.3`` case was invisible except by replaying the draft):

* ``figure_grounding_introduced`` — the rewrite invented a figure the original did not
  have. See the ruling below.
* ``not_strictly_better`` — neither arm fired. The pre-#3217 arm name, preserved so the
  existing `RegenDiscarded` CloudWatch series is continuous across this change.

## The ruling on removes-one-introduces-another: DISCARD

A rewrite that drops ``326.3`` and invents ``312.8`` in its place has not improved
correctness — the reader still meets a figure nothing backs, and WHICH unbacked figure it
is carries no information. Keeping it would license an endless swap and would slide the
predicate toward "always keep the rewrite", the exact degeneration the second half of
#3217's acceptance guards against. So the dispositive arm requires a strict SUB-MULTISET,
not merely a smaller count: introduce any new figure finding and the arm does not fire.
Such a rewrite can still be kept — but only by the ordinary `strictly_fewer` arm, on the
composite, which is where a like-for-like trade belongs.

Findings of the FRAMING classes may increase without blocking the dispositive arm. That
asymmetry is deliberate and is the issue's thesis: a framing/scope finding says the
narrative located a true fact wrongly; a figure finding says the number is not real. Only
the second is the categorical class ADR-104 refuses to let a score overrule.

## Log hygiene, and the arm names

`keep_rewrite` returns only a bool and one of four module-constant arm names, and the
census `describe_delta` renders is four INTEGERS. Nothing derived from a finding's text
can reach a log line through either. A findings list is derived from an AI draft about
Matthew's health, so a census that could ever carry a finding's `detail` into CloudWatch
is a real hazard, not a notional one.

**Do not rename the arm constants back to `DISCARD_*`.** They were `DISCARD_FIGURE_
INTRODUCED` / `DISCARD_NOT_BETTER` for one commit, and CodeQL flagged both log sinks
`py/clear-text-logging-sensitive-data` at HIGH severity. The SARIF data-flow path named
the source precisely: the string literal on the `DISCARD_NOT_BETTER = ...` line itself.
`DIS-CARD-...` contains `card`, which CodeQL's sensitive-name heuristic reads as a
payment-card field, so the arm string was classified private at birth and every log line
carrying it became a cleartext-logging alert. Nothing about the DATA was ever sensitive —
it is a substring collision — but the honest fix is to stop naming a variable something
the scanner reads as a credit-card field, not to suppress a whole rule on those lines and
go dark on the real thing it watches for.

Pure functions — no AWS, no HTTP, no I/O. Fail-soft on malformed findings (a non-dict
entry is ignored rather than raising into a generation path).
"""

from collections import Counter
from typing import Any, Dict, Iterable, List, Optional, Tuple

# ── the figure classes ────────────────────────────────────────────────────────────────
# "The narrative asserts a figure or datum that the supplied data does not back." These
# are the classes where the defect is the VALUE itself, so removing one is categorically
# an improvement no aggregate may veto.
#
# The first four are `coach_quality_gate._NUMERIC_FINDING_TYPES` — #3202's own split of the
# finding registry into "ungrounded number" vs "grounding violation" for the corrective
# note's label. This set is deliberately a SUPERSET of it: a fabricated calendar date, a
# guessed weekday and a stale baseline weight are the same defect wearing a different token
# class (the number gate simply cannot see a date — #1242). `tests/
# test_regen_keep_predicate_3217.py::test_numeric_finding_types_are_a_subset` pins the
# containment so the two cannot drift apart silently.
FIGURE_TYPES = frozenset(
    {
        "fabricated_number",
        "contradiction",
        "band_contradiction",
        "night_value_mismatch",
        "fabricated_date",
        "weekday_mismatch",
        "stale_baseline",
    }
)

# Keep arms (rewrite wins) and drop arms (original wins). Exported so the tests and any
# future dashboard read the same names the telemetry emits, rather than string literals.
# The VALUES are the CloudWatch `Arm` dimension and are load-bearing — `not_strictly_better`
# in particular predates #3217 and keeps that series continuous. The PYTHON NAMES say DROP_,
# not DISCARD_, on purpose: see "Log hygiene, and the arm names" in the module docstring.
KEEP_STRICTLY_FEWER = "strictly_fewer"
KEEP_FIGURE_REMOVED = "figure_grounding_removed"
DROP_FIGURE_INTRODUCED = "figure_grounding_introduced"
DROP_NOT_BETTER = "not_strictly_better"


def _identity(finding: Dict[str, Any]) -> str:
    """The stable identity of one finding, so a Counter can tell 'the SAME invented number
    survived' from 'a DIFFERENT one replaced it'.

    `detail` is the right key: every class in `grounded_generation` renders the offending
    value into it deterministically ("the number 326.3 appears in the narrative but nowhere
    in the data provided"), so equal details mean the same complaint about the same value.
    `claimed` is preferred when present because it is the raw value with no prose around it.
    """
    claimed = finding.get("claimed")
    if claimed is not None:
        return f"{finding.get('type')}|{claimed}"
    return f"{finding.get('type')}|{finding.get('detail', '')}"


def figure_census(findings: Optional[Iterable[Any]]) -> "Counter[str]":
    """Multiset of FIGURE-class finding identities. Non-dict entries are ignored."""
    census: "Counter[str]" = Counter()
    for f in findings or []:
        if isinstance(f, dict) and f.get("type") in FIGURE_TYPES:
            census[_identity(f)] += 1
    return census


def figure_count(findings: Optional[Iterable[Any]]) -> int:
    """How many FIGURE-class findings, as a plain accumulated int.

    Deliberately NOT ``sum(figure_census(...).values())``: this number is the only thing
    about a finding that is ever allowed to reach a log line, and it must be impossible for
    narrative text to ride along with it. A findings list is derived from an AI draft about
    Matthew's health — logging any part of one in clear text is a real hazard. An integer
    accumulated in a local cannot carry text; a string built over a findings-derived
    container is one careless edit from doing so. See `describe_delta` below.
    """
    n = 0
    for f in findings or []:
        if isinstance(f, dict) and f.get("type") in FIGURE_TYPES:
            n += 1
    return n


def describe_delta(before: Optional[List[Any]], after: Optional[List[Any]]) -> str:
    """The compact census for the log line: FOUR INTEGERS and nothing else.

    Built with `%d` over `int` values on purpose — no f-string over finding-derived
    objects, no excerpt, no detail text. The observability #3217 asks for is "which
    predicate dropped it and by how much", which needs counts, not content.
    """
    return "figures %d->%d total %d->%d" % (
        figure_count(before),
        figure_count(after),
        len(before or []),
        len(after or []),
    )


def keep_rewrite(before: Optional[List[Any]], after: Optional[List[Any]]) -> Tuple[bool, str]:
    """Decide whether `regen_once` keeps the rewrite. Returns ``(keep, arm)``.

    `before` -- findings on the original draft. `after` -- findings on the rewrite.

    The arm is one of the four module constants above — never a value derived from a
    finding, so nothing a caller logs from this return can carry draft text. The
    human-readable census is `describe_delta`, computed separately and only from counts.
    """
    n_before = len(before or [])
    n_after = len(after or [])
    fig_before = figure_census(before)
    fig_after = figure_census(after)
    introduced = fig_after - fig_before  # positive counts only: what the rewrite ADDED

    if n_after < n_before:
        return True, KEEP_STRICTLY_FEWER
    # #3217: dispositive. A strict sub-multiset means it removed a figure finding and
    # introduced none — kept regardless of what the composite total did.
    if not introduced and fig_after != fig_before:
        return True, KEEP_FIGURE_REMOVED
    if introduced:
        return False, DROP_FIGURE_INTRODUCED
    return False, DROP_NOT_BETTER
