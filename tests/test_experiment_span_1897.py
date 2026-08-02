"""tests/test_experiment_span_1897.py — an experiment-age claim spelled out in words.

THE DEFECT (#1897). On Day 1 of cycle 11, `/api/ai_analysis?expert=nutrition`
published "Zero food logs in seven days of an experiment". Every gate was blind:

  * `_NUM_RE` is digits-only, so "seven" is invisible;
  * 7 is in `_BENIGN_NUMBERS` anyway, so even "7" would have passed;
  * `_DAY_N_RE` matches "Day N" tokens, not "N days OF the experiment";
  * and the analyzer's `findings_fn` omitted `generation_date_iso` /
    `start_date_iso` entirely, so every phase-aware class no-opped.

A span claim is the same arithmetic as a Day-N claim wearing different clothes.
This is deliberately the parser #1922 deferred: that change moved NUMERIC
phase-bound claims to deterministic code and left word-numbers with the LLM
*because* "seven" is not arithmetic until something parses it. This parses it.

The lower bound matters as much as the upper one: a span SHORTER than the
elapsed days is correct (ADR-077 "clamped, not hidden") — the same rule #1917
had to teach the LLM rubric after it flagged 5-on-Day-6 three times running.
"""

import os
import sys

_LAMBDAS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas")
if _LAMBDAS not in sys.path:
    sys.path.insert(0, _LAMBDAS)

from ai import grounded_generation as gg  # noqa: E402

GENESIS = "2026-07-27"


def _claims(text, gen_date, start=GENESIS):
    return [f["claim"] for f in gg.experiment_span_findings(text, generation_date_iso=gen_date, start_date_iso=start)]


# ── replay: the live Day-1 fabrication ──────────────────────────────────────


def test_replays_the_day_1_word_number_span():
    """The exact published sentence. A digit-only gate cannot see this."""
    assert _claims("Zero food logs in seven days of an experiment.", "2026-07-27") == ["seven days of an experiment"]


def test_the_same_claim_in_digits_is_caught_identically():
    assert _claims("Zero food logs in 7 days of the experiment.", "2026-07-27") == ["7 days of the experiment"]


def test_weeks_and_months_convert_to_days():
    assert _claims("Three weeks into this experiment, the pattern is clear.", "2026-07-27")
    assert _claims("Two months into the cycle we can say something.", "2026-08-01")
    # ...and a week IS sayable once seven days have actually elapsed.
    assert _claims("One week into the experiment, protein is steady.", "2026-08-02") == []


# ── the lower bound: a short span is honest, not a defect ───────────────────


def test_a_span_shorter_than_elapsed_days_never_flags():
    """Trailing windows clamp to genesis. Flagging these is the #1917 rubric
    failure — and would make this gate noise on every reset."""
    for text in (
        "Zero food logs across six days of the experiment.",
        "Four days into the experiment and nothing has resolved.",
        "One day of the cycle is not a trend.",
    ):
        assert _claims(text, "2026-08-01") == [], text  # Day 6


def test_a_span_exactly_equal_to_elapsed_days_is_fine():
    assert _claims("Six days of the experiment, six days of wearable data.", "2026-08-01") == []


# ── pre-start: zero days of the current experiment exist ────────────────────


def test_pre_start_flags_any_positive_span():
    assert _claims("Two days of the experiment already logged.", "2026-07-20") == ["Two days of the experiment"]


# ── scoping: only EXPERIMENT-framed spans ───────────────────────────────────


def test_a_bare_span_with_no_experiment_framing_is_not_checked():
    """ "six days" may be about a training block, a sleep streak, a supplement
    protocol window. Only a claim about the EXPERIMENT's age is checkable
    against genesis, and flagging the rest would drown the signal."""
    for text in (
        "He held a six days in a row streak at the gym.",
        "Sleep averaged 7.4 hours over the last ten days.",
        "Twelve days of consistent creatine dosing before the washout.",
    ):
        assert _claims(text, "2026-07-27") == [], text


def test_unparseable_dates_disable_the_check():
    assert gg.experiment_span_findings("seven days of the experiment", generation_date_iso="", start_date_iso=GENESIS) == []
    assert gg.experiment_span_findings("seven days of the experiment", generation_date_iso="2026-07-27", start_date_iso="nope") == []


def test_a_repeated_claim_reports_once():
    text = "Seven days of the experiment. Again: seven days of the experiment."
    assert len(_claims(text, "2026-07-27")) == 1


# ── composition + the wiring that was missing ───────────────────────────────


def test_findings_compose_with_grounding_findings_and_correction_prompt():
    findings = gg.grounding_findings(
        "Zero food logs in seven days of an experiment.",
        allowed=set(),
        generation_date_iso="2026-07-27",
        start_date_iso=GENESIS,
    )
    spans = [f for f in findings if f["type"] == "experiment_span"]
    assert spans, "grounding_findings must route the span class when the anchors are supplied"
    assert "does not exist" in gg.correction_prompt(spans)


def test_grounding_findings_skips_the_class_without_the_anchors():
    """The exact reason nothing caught this live: no anchors, no phase classes."""
    findings = gg.grounding_findings("Zero food logs in seven days of an experiment.", allowed=set())
    assert not [f for f in findings if f["type"] == "experiment_span"]


def test_the_analyzer_now_passes_the_cycle_anchors():
    """The gate exists only if its caller feeds it. The analyzer's findings_fn
    omitted both anchors, which is why every phase-aware class no-opped there."""
    src = open(os.path.join(_LAMBDAS, "intelligence", "ai_expert_analyzer_lambda.py"), encoding="utf-8").read()
    assert "generation_date_iso=_gen_date_iso" in src
    assert "start_date_iso=EXPERIMENT_START" in src
