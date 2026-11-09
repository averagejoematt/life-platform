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
* ``#5611:o+owner-2026-11-03`` / ``#5611:u+owner-2026-11-03`` — the owner's sibling rulings (2026-11-03): an opinion
  filed as a prediction becomes an observation (o, never graded) or, once graded, could not be checked (u: no measurable
  outcome; m: graded on criteria that measure something else)
* ``#5611:<r|a|n|d|u|h|m|p|x|v>+owner-2026-11-09`` — the owner's classification rulings of 2026-11-09 (manifest v4,
  rules OR-1 to OR-8): a call kept on the record, outside the accuracy count, with its words, criteria and any grade
  it carried — r not a forecast, a a look back at days already past, n a condition no record measures, d no checkable
  direction, u an opinion, h a hedge, m a stored test of a different claim, p a stand-in measure, x either outcome
  fits, v a measured condition that did not happen
* ``#5533:g+owner-2026-11-09`` / ``#5533:l+owner-2026-11-09`` — the same ruling's re-grades: under the current rules
  on the call's own window (OR-10), and with readings that arrived after the first grade (OR-9)
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
    "#5611:o+owner-2026-11-03": (
        "The call was filed as a graded prediction, but its sentence is an opinion: its outcome names nothing that can be "
        "measured. By the owner's ruling it stays on the record as an observation — never graded and outside the accuracy "
        "count. Its original wording and the criteria it was filed under are kept."
    ),
    "#5611:u+owner-2026-11-03": (
        "The call was graded, but its sentence names no outcome that can be measured, so the grade measured something the "
        "sentence does not say. By the owner's ruling it is recorded as could not be checked: kept on the record with its "
        "original grade preserved, and outside the accuracy count."
    ),
    "#5611:m+owner-2026-11-03": (
        "The call was graded, but on criteria that measured something other than what its sentence predicts. Grading its own "
        "outcome would need criteria written after the fact, so by the owner's ruling it is recorded as could not be checked: "
        "kept on the record with its original grade preserved, and outside the accuracy count."
    ),
    "#5533:d": (
        "The call's average included readings from on or before the day it was made. It was graded again on readings after that day only."
    ),
    "#5533:e": (
        "Heart-rate measures changed baseline on 10 October 2026, so a window that crosses that day compares two different "
        "baselines. It was graded again against the readings after that day."
    ),
    "#5611:r+owner-2026-11-09": (
        "The call reported something that was already on the record when it was made, so it was not a forecast. By the "
        "owner's ruling it is kept on the record outside the accuracy count, with its original wording, its criteria and "
        "any grade it carried."
    ),
    "#5611:a+owner-2026-11-09": (
        "The call was a judgement about days that had already passed when it was made, while their records were still "
        "coming in. It is a look back, not a forecast. By the owner's ruling it is kept on the record outside the "
        "accuracy count, with its original wording, its criteria and any grade it carried."
    ),
    "#5611:n+owner-2026-11-09": (
        "The call depends on a condition that no record measures, such as a disrupted dinner or carbs eaten in the "
        "evening. Checking it would mean inventing that measurement after the fact. By the owner's ruling it is kept on "
        "the record outside the accuracy count, with its original wording, its criteria and any grade it carried."
    ),
    "#5611:d+owner-2026-11-09": (
        "The call names no direction or level that can be checked, so grading it would need a threshold or a measure "
        "chosen after the fact. By the owner's ruling it is kept on the record outside the accuracy count, with its "
        "original wording, its criteria and any grade it carried."
    ),
    "#5611:u+owner-2026-11-09": (
        "The call's sentence is an opinion or an explanation: its outcome names nothing that can be measured, so no "
        "reading can show it right or wrong. By the owner's ruling it is kept on the record outside the accuracy count, "
        "with its original wording, its criteria and any grade it carried."
    ),
    "#5611:h+owner-2026-11-09": (
        "The call hedged: it said something may happen, and no outcome could show that wrong. By the owner's ruling it is "
        "kept on the record outside the accuracy count, with its original wording, its criteria and any grade it carried."
    ),
    "#5611:m+owner-2026-11-09": (
        "The call's stored test checks something different from what its sentence says. Testing the sentence itself would "
        "need criteria written after the fact. By the owner's ruling it is kept on the record outside the accuracy count, "
        "with its original wording, its criteria and any grade it carried."
    ),
    "#5611:p+owner-2026-11-09": (
        "The call is about overnight glucose dips and the stress hormone cortisol, which were never measured, and it was "
        "graded on a sleep or recovery reading that cannot show them. By the owner's ruling it is kept on the record "
        "outside the accuracy count, with its original wording, its criteria and any grade it carried."
    ),
    "#5611:x+owner-2026-11-09": (
        "Either outcome would have fitted the call's sentence, so no reading could show it wrong. By the owner's ruling "
        "it is kept on the record outside the accuracy count, with its original wording, its criteria and any grade it "
        "carried."
    ),
    "#5611:v+owner-2026-11-09": (
        "The call said what would happen if a condition was met. The condition was measured over the call's own window "
        "and did not happen, so the forecast was never tested. By the owner's ruling it is kept on the record outside the "
        "accuracy count, with its original wording, its criteria and any grade it carried."
    ),
    "#5533:g+owner-2026-11-09": (
        "The call was graded again under the current grading rules, on its own original window and criteria, from the "
        "readings in the record. The result changed. By the owner's ruling the new result stands and the first grade is "
        "kept."
    ),
    "#5533:l+owner-2026-11-09": (
        "Readings for the call's window arrived after it was first graded. It was graded again with them, on its original "
        "window and criteria. By the owner's ruling the new result stands and the first grade is kept."
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
