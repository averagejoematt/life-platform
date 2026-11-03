"""correction_rules.py — the ONE registry of grade-correction rules in reader words (#5610, decision D).

WHY. A corrected grade carries the reason its writer stored, and every writer stored it as
engineering text ("#5533 (e): an HR-metric window spanning the 2026-10-10 regime marker
(health.hr_regime); …"). The owner's ruling (2026-11-02, decision D) is that a reader sees
every historical correction with an explanation in plain words and dates in words. The stored
reason is the audit record and is never rewritten — it travels beside the explanation as
``reason``; this module only supplies the words a page prints above it.

THE IDS. A rule id names the writer that made the correction and, where one writer had several
outcomes, which outcome. They are derived from what the row stores (``lambdas/web/correction_history.py``):

* ``#3551:point``  — ``scripts/regrade_level_claims_3551.py`` (``verdict_correction.regraded_as``)
* ``#4541:count``  — ``scripts/regrade_count_claims_4541.py``
* ``#4617:<action>`` — ``scripts/regrade_direction_calls_4617.py`` (``verdict_correction.action``)
* ``#4618:<action>`` — ``scripts/regrade_tomorrow_calls_4618.py``; ``#4618:respecify`` is the
  ``respecified_at`` / ``respecified_from`` trail it left on a call that was still open
* ``#5533:<a-e>`` — ``deploy/regrade_predictions.py`` (``corrections[]``, the reason's ``#5533 (x):`` prefix)
* ``#5533:c+owner-2026-11-02`` — the owner-ruled retirement of the protein if-then (2026-11-02)
* ``revert`` — ``deploy/revert_regrade.py`` (a reason starting ``REVERT``)

AN UNKNOWN ID IS AN ERROR, NOT A FALLBACK. ``explain`` raises ``UnknownCorrectionRule`` — the
export prints no engineering text in place of an explanation. A new correction writer adds its
id here in the same PR (``tests/test_correction_history_5610.py`` pins every id the production
rows carried on 2026-11-02).

Words only, no ISO dates (the page prints dates from their own fields, in words); the 10 October
heart-rate change is named as a day in words because it IS the rule.
"""

from __future__ import annotations


class UnknownCorrectionRule(ValueError):
    """A correction whose rule id has no reader explanation — the export must stop, not improvise."""


#: rule id → the explanation a reader sees. One sentence or two; no ISO dates; no issue numbers.
RULES: dict[str, str] = {
    "#3551:point": ("The call named a level, but it was stored and graded as a two-week trend. It was graded again as the level it named."),
    "#4541:count": (
        "The call was a count — how many days would reach a mark — but another rule graded it. It was graded again by counting the days."
    ),
    "#4617:restate": (
        "The call was graded again across its own window, from the first reading to the last. The grade did not change; "
        "the record now shows the window's first and last readings."
    ),
    "#4617:regrade": (
        "The first grade compared only the most recent readings with the few before them. It was graded again on the change "
        "from the first to the last reading of the call's own window, measured against the normal day-to-day swing."
    ),
    "#4618:regrade": (
        "The sentence named its own day, but the call was stored with a different target and graded on a day the sentence "
        "does not name. It was graded again on the reading for the day it named."
    ),
    "#4618:withdraw:no-reading": (
        "The sentence named its own day and that day has no reading. The earlier grade measured a different day, so it was "
        "withdrawn; no reading was borrowed from another day."
    ),
    "#4618:withdraw:not-a-forecast": (
        "The number was stated for a day on or before the day the call was made, so the reading already existed. It was a "
        "recollection rather than a forecast, so it is kept as an observation that nothing can settle."
    ),
    "#4618:respecify": (
        "The target day or window the call was stored with was not the one its sentence states. The target was taken again "
        "from the sentence before the call was graded."
    ),
    "#5533:a": "The grader now marks the quality of each grade; this grade was stamped with those marks.",
    "#5533:b": "The call belonged to a coach who had left, and the grader had stopped looking at it. It was graded for the first time.",
    "#5533:c": (
        "The grading window held a day with no food logged, which the grader had read as a day of almost no eating. It was "
        "graded again with such days treated as missing."
    ),
    "#5533:c+owner-2026-11-02": (
        "The first grade counted a day with no food logged as a day of almost no eating. Read again, the call is an if-then "
        "about two days that had already happened, and its outcome names nothing that can be measured, so it was retired "
        "ungraded rather than graded again."
    ),
    "#5533:d": (
        "The call's average included readings from on or before the day it was made. It was graded again on readings after that day only."
    ),
    "#5533:e": (
        "Heart-rate measures changed baseline on 10 October 2026, so a window that crosses that day compares two different "
        "baselines. It was graded again against the readings after that day."
    ),
    "revert": "A correction was reversed and the grade before it was restored.",
}


def explain(rule_ids: list[str]) -> str:
    """The explanation for one correction's rules, in order. Raises on an unknown id."""
    if not rule_ids:
        raise UnknownCorrectionRule("a correction with no rule id")
    missing = [r for r in rule_ids if r not in RULES]
    if missing:
        raise UnknownCorrectionRule(f"no reader explanation for correction rule(s) {missing}")
    return " ".join(RULES[r] for r in dict.fromkeys(rule_ids))
