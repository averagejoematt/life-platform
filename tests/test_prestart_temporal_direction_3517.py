"""tests/test_prestart_temporal_direction_3517.py — #3517: nothing happens "since" a future reset.

THE DEFECT (live, Day 0 of cycle 16). `/api/coaching-dashboard`'s physical
`position_summary` read "…No weight reading has arrived since the September 5th reset, so
I'm treating baseline as unestablished" — generated 2026-09-04, with genesis 2026-09-05
still a day away. Every deterministic instrument was green on it:

  * `baseline_freshness` handled only "Day N" claims pre-start (#1691), and the sentence
    names no day number;
  * the genesis date is in the #1242 dates ALLOW-list — it is a real, grounded date;
  * `grounding_wiring.GATE_CLASSES` has no temporal-direction rule at all;
  * the coach quality gate scored the draft 92.

The reader-truth judge flagged it advisory, ~5h after readers had it. It recurs on every
reset's Day 0.

WHAT THE RULE IS. Not a phrase list: a DIRECTION. Before genesis, no clause may place an
event after the genesis instant. `since|after|following|post` governing a genesis
reference inside one clause is that placement, and there is no honest pre-start sentence
of that shape. The controls below are the live sentence (positive) and "the reset lands
tomorrow" (negative) — the exact pair the issue asked for — plus the two ways the rule
could go wrong: firing after genesis, and sweeping in an unrelated `since`.

The rule lives INSIDE `baseline_freshness_findings`, which `grounding_wiring.GATE_CLASSES`
already registers as the freshness class's `direct` entrypoint, so every surface that arms
freshness gets it with no wiring change.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

from ai.baseline_freshness import baseline_freshness_findings  # noqa: E402

GENESIS = "2026-09-06"
PRE_START = "2026-09-05"
IN_CYCLE = "2026-09-12"

LIVE_SENTENCE = "No weight reading has arrived since the September 6th reset, so I'm treating baseline as unestablished."


def _phase(text, gen_date):
    return [
        f for f in baseline_freshness_findings(text, generation_date_iso=gen_date, start_date_iso=GENESIS) if f["type"] == "stale_phase"
    ]


# ── the positive control: the sentence that shipped ──────────────────────────


def test_the_live_sentence_is_a_stale_phase_finding():
    found = _phase(LIVE_SENTENCE, PRE_START)
    assert found, "the sentence that shipped to readers must be caught"
    assert "AFTER genesis" in found[0]["detail"]
    assert GENESIS in found[0]["detail"]


@pytest.mark.parametrize(
    "text",
    [
        "Nothing has landed since the 2026-09-06 reset.",
        "Since the September 6th restart he has logged nothing.",
        "After the reset, his weight held steady.",
        "Following the September 6 restart we will see the first weigh-in.",
        "Post-reset the numbers have been flat.",
        "since the 9/6 reset there is no data",
    ],
)
def test_every_direction_word_over_a_genesis_reference_fires(text):
    assert _phase(text, PRE_START), f"must be caught pre-start: {text!r}"


# ── the negative controls: the rule must be able to stay silent ──────────────


@pytest.mark.parametrize(
    "text",
    [
        "The reset lands tomorrow.",
        "Genesis is tomorrow; the first numbers arrive after that.",
        "Since March he has been consistent, and the reset lands tomorrow.",
        "He has logged steadily since August, which is encouraging.",
        "The cycle begins 2026-09-06 — nothing exists yet.",
        "",
    ],
)
def test_honest_pre_start_sentences_do_not_fire(text):
    assert _phase(text, PRE_START) == [], f"false positive on: {text!r}"


def test_the_rule_is_INERT_once_genesis_has_passed():
    """The direction claim becomes TRUE in-cycle — a rule that kept firing would make
    every honest 'since the reset' sentence unpublishable."""
    assert _phase(LIVE_SENTENCE, IN_CYCLE) == []
    assert _phase("Since the reset his weight is down four pounds.", IN_CYCLE) == []


def test_a_bad_start_date_does_not_raise():
    # A weekly cron must never die on a malformed constant.
    assert baseline_freshness_findings(LIVE_SENTENCE, generation_date_iso=PRE_START, start_date_iso="not-a-date") == []


# ── the analyzer's own prompt: the clamp is gone ─────────────────────────────


def test_the_analyzer_frame_does_not_clamp_day_zero_to_day_one():
    """`ai_expert_analyzer_lambda` clamped `days_in_experiment` to 1 in three places, so
    on a pre-start day the PROMPT ITSELF asserted 'started <genesis>, now day 1'. The
    impossible tense was the prompt's, not only the model's."""
    from intelligence import analyzer_grounding as ag

    frame = ag._fallback_frame(GENESIS, PRE_START)
    assert frame.pre_start is True
    assert frame.days_in == 0, "pre-start must be day 0, never clamped to 1"
    assert frame.week_num == 0
    assert "now day 1" not in frame.phase_block
    assert "PRE-START" in frame.phase_block
    assert "past tense" in frame.phase_block


def test_an_explicit_day_override_cannot_resurrect_day_one_pre_start():
    """`build_prompt(expert_key, data, days_in, week_num)` takes an override, and
    `generate_and_cache` passes one. The pre-start branch must not be overridable."""
    from intelligence import analyzer_grounding as ag

    frame = ag._fallback_frame(GENESIS, PRE_START, days_in=1, week_number=1)
    # The caller asked for day 1; the clock says pre-start, and the clock wins.
    assert frame.pre_start is True
    assert frame.days_in == 0


def test_in_cycle_the_frame_still_renders_the_week_line():
    from intelligence import analyzer_grounding as ag

    frame = ag._fallback_frame(GENESIS, IN_CYCLE)
    assert frame.pre_start is False
    assert frame.days_in == 7
    assert "This is Week" in frame.phase_block
    assert frame.period == "experiment days 1-7"
