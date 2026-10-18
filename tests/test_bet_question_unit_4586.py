"""Red team 2026-10-17 (#4586): a bet's line is printed with its unit ("26% or higher"), never as a
bare number beside a coach's "27.6%". A measure with no registered unit gets no question at all."""

from web.prediction_reason import METRIC_UNITS, METRIC_WORDS, metric_unit, metric_words
from web.site_api_edition import bet_question


def test_every_measure_with_reader_words_has_a_unit():
    assert set(METRIC_UNITS) == set(METRIC_WORDS)


def test_the_bet_line_carries_its_unit():
    q = bet_question({"metric": "deep_pct_7day_avg", "condition": "gte", "threshold": 26.0}, "2026-10-16", metric_words)
    assert q == "Will the deep-sleep share (7-day average) be 26% or higher on Friday, October 16?"
    q = bet_question({"metric": "recovery_score", "condition": "lt", "threshold": 70}, "2026-09-30", metric_words)
    assert q == "Will the morning recovery score be under 70 out of 100 on Wednesday, September 30?"
    q = bet_question({"metric": "recovery_score_7day_avg", "condition": "gte", "threshold": 81.6}, "2026-10-05", metric_words)
    assert q == "Will the morning recovery score (7-day average) be 81.6 out of 100 or higher on Monday, October 5?"
    assert metric_unit("recovery_score") == metric_unit("sleep_score") == " out of 100"
    assert metric_unit("weight_lbs") == " lb"


def test_no_unit_no_question():
    words = lambda m: "a measure with words" if m == "mystery" else None  # noqa: E731
    assert bet_question({"metric": "mystery", "condition": "gte", "threshold": 3}, "2026-10-16", words) is None
