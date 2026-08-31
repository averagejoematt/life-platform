"""tests/test_grounding_duration_phantoms_3327.py — the blocking grounding gate must not
bind a duration number as a metric value.

#3327: `grounding_guard.hard_canonical_contradictions` (the SS-10 tight detector that
`ai_expert_analyzer_lambda` block-and-regens on and `field_notes_lambda` HOLDS on —
ADR-108 regenerate-or-hold) phantom-flagged 7 of 10 ordinary phrases: RHR and HRV had
no unit lookahead at all, and recovery's lookahead sat after a backtracking `(\\d{1,3})`,
so "12 weeks" retreated to "1" and "7.5 hours" to "7" and passed it. A phantom costs a
discarded fresh narrative and a stale record served to readers, and a model cannot
rewrite its way out — any sentence naming a window re-trips it.

The issue's exact 10-phrase set is pinned row by row (each row is its own test case, not
an aggregate count) against the facts the reproduction used (rhr 64 / recovery 30 /
hrv 25.2). Reverting any one of the three regexes to its pre-#3327 form turns the rows
for that metric red — the per-metric mutation assertions at the bottom are the ones the
PR body cites.
"""

import os
import sys

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "intelligence"))

from grounding_guard import hard_canonical_contradictions  # noqa: E402

# The reproduction's facts: rhr 64 / recovery 30 / hrv 25.2 (Session L, 2026-08-30).
FACTS = {"rhr_bpm": 64.0, "recovery_pct": 30.0, "hrv_ms": 25.2}


def _hits(text):
    return [(h["metric"], h["claimed"]) for h in hard_canonical_contradictions(text, FACTS)]


# ── the issue's 10-phrase set, one row per case ──────────────────────────────────────
# (phrase, expected hits). Seven phantoms must return NOTHING; the true positive must
# still bind 53; the two clean controls stay clean.
ISSUE_ROWS = [
    ("Recovery over 12 weeks", []),  # was [('Whoop recovery', 1.0)] — retreated "12"→"1"
    ("Recovery over 120 days", []),  # was [('Whoop recovery', 12.0)] — retreated "120"→"12"
    ("Recovery on 7.5 hours of sleep", []),  # was [('Whoop recovery', 7.0)] — decimal split
    ("RHR over 12 weeks", []),  # was [('resting HR', 12.0)] — no lookahead
    ("RHR over 120 days", []),  # was [('resting HR', 120.0)] — no lookahead
    ("HRV over 12 weeks", []),  # was [('HRV', 12.0)] — no lookahead
    ("HRV over the 120 days", []),  # was [('HRV', 120.0)] — no lookahead
    ("Recovery has been steady.", []),  # clean control
    ("Your HRV trend is encouraging.", []),  # clean control
    ("Your RHR dropped to 53", [("resting HR", 53.0)]),  # true positive — MUST still flag
]


@pytest.mark.parametrize("phrase,expected", ISSUE_ROWS, ids=[r[0] for r in ISSUE_ROWS])
def test_issue_3327_phrase(phrase, expected):
    assert _hits(phrase) == expected


# ── the structural properties the fix rests on ──────────────────────────────────────


@pytest.mark.parametrize(
    "phrase",
    [
        "a 12-week recovery block",  # hyphenated unit
        "recovery across the last 120-day window",
        "recovery on the 12th day",  # ordinal is a count
        "RHR down 8% this month",  # a percent on RHR is a change, not a reading
        "HRV up 15% over the block",
        "recovery up 12 points",  # delta idiom
        "HRV after 3 sessions this week",
        "RHR measured over 90 minutes",
    ],
)
def test_units_that_make_a_number_a_count_never_bind(phrase):
    assert _hits(phrase) == []


def test_decimal_is_consumed_whole_never_split():
    # "7.5" is bound as 7.5 (a real, if wrong, recovery claim) — never as "7" with ".5 hours"
    # left over for the lookahead to wave through.
    assert _hits("recovery at 7.5") == [("Whoop recovery", 7.5)]
    assert _hits("recovery at 7.5 hours") == []


def test_value_units_and_true_positives_still_bind():
    # The precision fix must not open a recall hole: the metric's OWN unit still binds.
    assert _hits("Your resting heart rate is 52 bpm now.") == [("resting HR", 52.0)]
    assert _hits("recovery of 12%") == [("Whoop recovery", 12.0)]
    assert _hits("86% recovery today") == [("Whoop recovery", 86.0)]
    assert _hits("Your HRV is holding in the 50-52 range this week.") == [("HRV", 50.0)]
    assert _hits("Recovery sat at twelve percent.") == [("Whoop recovery", 12.0)]  # spelled numbers still normalise
    # A value followed by a LATER duration is still the value.
    assert _hits("RHR held at 53 for 12 weeks") == [("resting HR", 53.0)]


def test_thresholds_and_grounded_anywhere_unchanged():
    # #3327 touches matching only: the _mentions early-exit and the per-metric tolerances
    # (RHR >4 bpm AND >7%; recovery >10 pt; HRV >8 ms AND >40%) are exactly as before.
    assert _hits("Your RHR climbed from 64 to 66 over the week.") == []  # cites canonical → grounded
    assert _hits("Your RHR is around 61 these days.") == []  # 3 bpm / 5% — inside tolerance
    assert _hits("HRV ticked up to 30 ms overnight.") == []  # 19% swing — inside HRV tolerance
    assert _hits("Recovery fell from 55 to 30 this week.") == []  # cites canonical 30
    assert _hits("With recovery up at 86 you're primed to push.") == [("Whoop recovery", 86.0)]


# ── mutation proof: one assertion per metric ────────────────────────────────────────
# Each of these goes red on its own if THAT metric's regex is reverted to its pre-#3327
# form (the PR body shows the run). They are deliberately the plainest phantom per metric.


def test_mutation_rhr_regex_rejects_duration():
    assert _hits("RHR over 120 days") == []


def test_mutation_recovery_regex_rejects_duration_without_retreat():
    assert _hits("Recovery over 12 weeks") == []
    assert _hits("Recovery on 7.5 hours of sleep") == []


def test_mutation_hrv_regex_rejects_duration():
    assert _hits("HRV over the 120 days") == []
