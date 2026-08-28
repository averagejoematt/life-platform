# gate-entrypoint: the #3252 box-2 absence-sourcing verdict.
# `unsourced_absence_findings` returns the hits, and `sourced_availability` is the
# fail-closed half that removes the unlicensed answer BEFORE a model ever sees it.
# A list of hits IS the verdict, so there is no raise and no exit for the AST to
# see: if either function silently returned its input unchanged, every consumer
# would keep publishing and every check would stay green — the dark-gate shape
# #2578 exists to count. Nothing else in the census reports it.
"""absence_sourcing.py — "name every source you consulted" for absence claims (#3252).

THE RULING THIS ENCODES (owner, 2026-08-28 — ADR-104 amendment)
---------------------------------------------------------------
**An auto-synced source counts as logging.** If the data arrived, it was logged,
regardless of whether Matthew typed it. A narrative that says "you didn't log a run" is
WRONG when Strava synced one.

So the rule is *name every source you consulted*, not *name the manual ones*. An absence
claim must be grounded against the FULL set of sources that could have supplied the fact,
and that set must be named. An auto-synced source cannot be silently excluded from the
denominator.

THE LIVE DEFECT (#3252)
-----------------------
`/method/board/`'s weekly priority asserted "no active logging (food, training, or
journal entries since August 17th)" while DynamoDB held two Strava activities inside that
exact window. Nothing was lying: the training-absence answer was derived from Hevy alone,
because Hevy is the `engagement_channel` for training and Strava is not. The denominator
was short by one auto-synced source and no instrument could see that it was.

WHAT IS STRUCTURAL HERE, AND WHAT IS NOT
----------------------------------------
This module does NOT read narrative text, and that is deliberate: every phrase-matched
member of the #2959/#3003/#3199 family has failed in the field, and "an absence claim"
has no reliable surface form ("no active logging", "quiet since", "nothing on the board",
"he hasn't"). The structural signal is the GROUNDING FACT that licensed the sentence:

  * an `ai.behavior_logs.AbsenceTransition` whose `kind` is `never_logged` or `paused` —
    those two kinds ARE the assertion "this category produced nothing / stopped"; a
    narrative can only say it because the derivation handed it over. `logged` has no
    absence in it and `unknown` licenses nothing, so neither is checked.
  * a `LogAvailability` category that is `covered` and not `present` — the set-shaped
    form of the same assertion.

Both are produced in code before any model runs (ADR-105), so the check runs on the
platform's own claim rather than on a guess about English.

STALE IS NOT ABSENT (#3268)
---------------------------
An absence claim made against a source whose last data predates the window is a DIFFERENT
statement from one made against a source that reported and had nothing to say. Garmin is
the standing case: it is `paused` (ADR-074), so it cannot report — "no steps" grounded on
a paused Garmin is a hole in the record, not a fact about Matthew. `KIND_STALE` is that
answer, and like `KIND_UNSOURCED` it does not license the claim.

Which silence is which is the registry's `behavioral` facet, not a judgement call here:

  * behavioral (Strava, Hevy, MacroFactor, Notion) — "a record exists only when Matthew
    DOES something". Its silence IS the absence; a quiet Strava is a week without a run,
    and grading that `stale` would delete the one true absence claim the platform has.
  * infrastructure (Apple Health, Garmin) — "the pipe runs without his participation".
    Its silence is a broken pipe, and an absence claim resting on it is unfounded.

So only a PAUSED source, or an INFRASTRUCTURE source with nothing in the window, grades
`stale`. That asymmetry is the whole distinction #3268 asked for, and it is read from the
registry rather than restated.

Pure: zero I/O. The caller owns every lookup. The DENOMINATOR is derived from
`ingestion.source_registry`'s `evidence_for` facet — never hand-listed here, because a
hand-typed "sources that count" list is the same defect one layer up.
"""

from typing import Iterable, Mapping, NamedTuple, Optional

from ingestion.source_registry import SOURCE_REGISTRY, evidence_sources_by_category

from ai.behavior_logs import (
    LOG_CATEGORIES,
    TRANSITION_NEVER_LOGGED,
    TRANSITION_PAUSED,
    TRANSITION_UNKNOWN,
    AbsenceTransition,
    LogAvailability,
    as_availability,
)

# The four verdicts. Exhaustive and mutually exclusive; only the first licenses a claim.
KIND_SOURCED = "sourced"  # every source that could have known was consulted, and reported nothing
KIND_STALE = "stale"  # a source in the denominator is paused or has not reported into the window
KIND_UNSOURCED = "unsourced"  # a source in the denominator was never consulted at all
KIND_UNSOURCEABLE = "unsourceable"  # the registry names NO source for this category
SOURCING_KINDS = (KIND_SOURCED, KIND_STALE, KIND_UNSOURCED, KIND_UNSOURCEABLE)


def evidence_sources(category) -> tuple:
    """The registry-derived denominator for one log category. () when nothing records it."""
    cat = str(category or "").strip().lower()
    return evidence_sources_by_category().get(cat, ())


def _facet(source: str, name: str, default=None):
    row = SOURCE_REGISTRY.get(source)
    return row.get(name, default) if isinstance(row, Mapping) else default


def _cannot_speak(source: str, last_date: Optional[str], window_start: Optional[str]) -> bool:
    """True when this source is structurally unable to answer for the window (see above).

    A paused source can never report. An infrastructure source with nothing in the window
    is a dark pipe. A BEHAVIORAL source's silence is the answer itself and is never graded
    stale — that is the load-bearing half of the asymmetry.
    """
    if _facet(source, "paused"):
        return True
    if _facet(source, "behavioral"):
        return False
    if window_start is None:
        return False  # nothing to measure the vintage against — do not guess
    return last_date is None or last_date < window_start


def _iso(value) -> Optional[str]:
    s = str(value or "")[:10]
    return s if len(s) == 10 and s[4] == "-" and s[7] == "-" else None


class AbsenceSourcing(NamedTuple):
    """Whether an absence claim about `category` is grounded, and in WHOSE data.

    `checked` is the naming the box asks for: the sources actually consulted, in
    registry order. `unchecked` and `stale` are the two ways the denominator can be
    short, kept apart because they are different sentences (#3268).
    """

    category: str
    kind: str
    denominator: tuple
    checked: tuple
    unchecked: tuple
    stale: tuple

    @property
    def licenses_absence(self) -> bool:
        """True ⇔ "nothing was logged" is a claim this grounding can carry."""
        return self.kind == KIND_SOURCED

    def narrative_input(self) -> str:
        """One deterministic sentence of ground truth that NAMES the sources checked.

        This is the string a prompt/renderer is meant to carry so the assertion travels
        with its denominator instead of arriving bare.
        """
        checked = ", ".join(self.checked) if self.checked else "nothing"
        if self.kind == KIND_SOURCED:
            return f"{self.category}: checked {checked} — every source that could have recorded it, and none did."
        if self.kind == KIND_STALE:
            return (
                f"{self.category}: checked {checked}, but {', '.join(self.stale)} has not reported into this window "
                f"(paused or stale) — this is a gap in the record, NOT a confirmed absence. Do not say he did not do it."
            )
        if self.kind == KIND_UNSOURCED:
            return (
                f"{self.category}: checked {checked}; {', '.join(self.unchecked)} was never consulted and could have "
                f"recorded it — no absence claim is licensed. Say nothing about whether it happened."
            )
        return f"{self.category}: no source records it at all, so its absence cannot be established. Say nothing about it."


def absence_sourcing(
    category,
    *,
    sources_observed: Iterable = (),
    source_last_dates: Optional[Mapping] = None,
    window_start=None,
) -> AbsenceSourcing:
    """Grade one absence claim against the registry denominator. Pure, total, never raises.

    ``sources_observed`` — the registry source ids the caller actually consulted.
    ``source_last_dates`` — optional {source_id: "YYYY-MM-DD"|None}. An INFRASTRUCTURE
    source whose last data is missing or predates ``window_start`` cannot speak for the
    window and grades `stale`; a BEHAVIORAL source is never graded on its vintage, because
    its silence is the very thing being claimed. Withhold the map (or ``window_start``)
    and staleness is decided by the registry `paused` facet alone — the conservative
    floor, never a guess.
    """
    cat = str(category or "").strip().lower()
    denominator = evidence_sources(cat)
    observed = {str(s).strip().lower() for s in (sources_observed or ())}
    if not denominator:
        return AbsenceSourcing(cat, KIND_UNSOURCEABLE, (), (), (), ())

    checked, unchecked, stale = [], [], []
    win = _iso(window_start)
    last_dates = source_last_dates if isinstance(source_last_dates, Mapping) else {}
    for src in denominator:
        if src not in observed:
            unchecked.append(src)
            continue
        checked.append(src)
        # An unobserved date stays None: for a behavioral source that changes nothing
        # (its silence is the answer), and for an infrastructure source the honest read
        # of "I have no vintage for the pipe that must always report" is that it cannot
        # speak. Neither branch guesses a date.
        if _cannot_speak(src, _iso(last_dates.get(src)) if src in last_dates else None, win):
            stale.append(src)

    if unchecked:
        kind = KIND_UNSOURCED
    elif stale:
        kind = KIND_STALE
    else:
        kind = KIND_SOURCED
    return AbsenceSourcing(cat, kind, denominator, tuple(checked), tuple(unchecked), tuple(stale))


def sourced_availability(
    availability,
    *,
    sources_observed: Iterable = (),
    source_last_dates: Optional[Mapping] = None,
    window_start=None,
) -> Optional[LogAvailability]:
    """The FAIL-CLOSED half: drop every covered-but-unlicensed category (#3252).

    A category the caller declares `covered` while a source in its registry denominator
    was never consulted (or is paused/stale) becomes UNCOVERED — i.e. unknown, which
    never licenses an absence and never flags (the #2056 semantics). The unlicensed
    answer stops existing rather than being discouraged, so no prompt rule and no
    reviewer stands between the defect and a reader.

    A `present` category is never demoted: a real log is positive evidence and does not
    depend on the denominator being complete. A category the registry has NO opinion
    about (`KIND_UNSOURCEABLE`) is left exactly as the caller declared it — this
    function narrows claims the registry can adjudicate, it never invents coverage gaps
    for categories the registry does not model.
    """
    avail = as_availability(availability)
    if avail is None:
        return None
    keep = set()
    for cat in avail.covered:
        if cat in avail.present:
            keep.add(cat)
            continue
        grading = absence_sourcing(
            cat,
            sources_observed=sources_observed,
            source_last_dates=source_last_dates,
            window_start=window_start,
        )
        if grading.kind == KIND_UNSOURCEABLE or grading.licenses_absence:
            keep.add(cat)
    if keep == set(avail.covered):
        return avail
    dropped = set(avail.covered) - keep
    return LogAvailability(
        frozenset(avail.present),
        frozenset(keep),
        frozenset((c, d) for c, d in avail.last_dates if c not in dropped),
    )


def sourced_transitions(
    transitions,
    *,
    sources_observed: Iterable = (),
    source_last_dates: Optional[Mapping] = None,
    window_start=None,
) -> dict:
    """The FAIL-CLOSED half for the transition path: demote what the denominator cannot carry.

    Every `never_logged` / `paused` transition whose grading does not license the claim
    becomes `unknown` — the kind that says nothing and flags nothing. Same discipline as
    #2382's `never_logged`-carries-no-day-count: the unsayable thing becomes unbuildable
    rather than merely discouraged, so a prompt rule is not what stands between a short
    denominator and a reader.

    `logged` and `unknown` pass through untouched; a `logged` transition is positive
    evidence and does not need the denominator to be complete.
    """
    if isinstance(transitions, AbsenceTransition):
        transitions = {transitions.category: transitions}
    if not isinstance(transitions, dict):
        return {}
    out = {}
    for cat, tr in transitions.items():
        if not isinstance(tr, AbsenceTransition) or tr.kind not in (TRANSITION_NEVER_LOGGED, TRANSITION_PAUSED):
            out[cat] = tr
            continue
        grading = absence_sourcing(
            cat,
            sources_observed=sources_observed,
            source_last_dates=source_last_dates,
            window_start=window_start,
        )
        if grading.kind == KIND_UNSOURCEABLE or grading.licenses_absence:
            out[cat] = tr
            continue
        out[cat] = AbsenceTransition(tr.category, TRANSITION_UNKNOWN, None, None, tr.window_start)
    return out


def unsourced_absence_findings(
    transitions,
    *,
    sources_observed: Iterable = (),
    source_last_dates: Optional[Mapping] = None,
    window_start=None,
) -> list:
    """THE CHECK: an absence assertion whose denominator is short becomes a finding.

    `transitions` is what `behavior_logs.absence_transitions()` /
    `transition_from_presence_signal()` return — a category→`AbsenceTransition` map (a
    single `AbsenceTransition` is accepted too). The structural trigger is the transition
    KIND: `never_logged` and `paused` are the two that assert something did not happen.
    `logged` and `unknown` are never checked, because neither is an absence claim.

    Each hit is the shared ``{"type": ..., "detail": ...}`` shape (type
    ``"unsourced_absence"``) so it composes with `grounded_generation.grounding_findings()`
    / `correction_prompt()`. The detail NAMES both what was checked and what was not —
    the "names the sources it checked" half of the acceptance box.
    """
    if isinstance(transitions, AbsenceTransition):
        transitions = {transitions.category: transitions}
    if not isinstance(transitions, dict):
        return []
    findings = []
    for cat in LOG_CATEGORIES:  # registry order, so the finding list is deterministic
        tr = transitions.get(cat)
        if not isinstance(tr, AbsenceTransition):
            continue
        if tr.kind not in (TRANSITION_NEVER_LOGGED, TRANSITION_PAUSED):
            continue
        grading = absence_sourcing(
            cat,
            sources_observed=sources_observed,
            source_last_dates=source_last_dates,
            window_start=window_start,
        )
        if grading.licenses_absence:
            continue
        findings.append(
            {
                "type": "unsourced_absence",
                "category": cat,
                "claim": tr.kind,
                "kind": grading.kind,
                "checked": list(grading.checked),
                "unchecked": list(grading.unchecked),
                "stale": list(grading.stale),
                "detail": (
                    f'the narrative is grounded on a "{cat}" absence ({tr.kind}), but that claim was checked against '
                    f"{', '.join(grading.checked) or 'no source'} while "
                    f"{', '.join(grading.unchecked + grading.stale) or 'nothing'} could also have recorded it — "
                    f"{grading.narrative_input()}"
                ),
            }
        )
    return findings
