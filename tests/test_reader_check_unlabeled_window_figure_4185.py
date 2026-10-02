"""#4185 §2.5 — the `unlabeled_window_figure` reader CHECK class, proven against the frozen live corpus.

An average / running average / EWMA / trend figure whose sentence names no window —
"1,596 kcal EWMA", "the EWMA has moved from 152.9g to 157.3g". The #1968 night-class
shape, generalised. A date alone is not a window.

Fixture-driven (tests/grounding_corpus/reader_checks/), never a tree sweep. The shared
contract (`reader_checks_corpus.assert_class_contract`) asserts: every live specimen
that names this class fails it; every fixture that does not name it passes it; and the
MUTATION CONTROL — this class replaced by a no-op — lets every specimen through, so
the test cannot be satisfied by some other class firing.
"""

import re

import reader_checks_corpus as corpus
from coach import reader_checks

CHECK = "unlabeled_window_figure"


def test_live_specimens_fail_controls_pass_and_the_mutation_control_is_red(monkeypatch):
    corpus.assert_class_contract(CHECK, monkeypatch)


def test_a_window_in_the_same_sentence_labels_the_figure():
    for text in (
        "He averages 153 g a day over the last 20 logged days.",
        "Protein averaged 106.9 grams across 14 logged days.",
        "His 7-day average is 159.8 g.",
        "Recovery averaged 74 % since Monday.",
    ):
        assert reader_checks.unlabeled_window_figure(text) == [], text


def test_a_denied_trend_is_not_an_average_figure():
    assert reader_checks.unlabeled_window_figure("Treat the 99% reading as a data point, not a trend.") == []


def test_a_decimal_does_not_end_the_sentence():
    assert len(reader_checks.unlabeled_window_figure("The EWMA is 81.6% and rising.")) == 1


# #4343: verbatim from the glucose coach's held 2026-09-27 final — the 77 belongs to a
# dated reading in the second clause, not to the average in the first.
GLUCOSE_0927_TWO_CLAUSES = (
    "The deep sleep running average has moved modestly, and the recovery reading on the night of "
    "September 25th was 77% with HRV at 46.5 ms."
)
LABS_0927_UNLABELED = "Your running average protein intake is 157.1 g per day — well short of the 190 g daily target, but climbing."


def test_the_average_and_the_figure_must_share_a_clause():
    assert reader_checks.unlabeled_window_figure(GLUCOSE_0927_TWO_CLAUSES) == []
    # a dash is parenthetical, not a clause join: the labs coach's figure still fails
    assert len(reader_checks.unlabeled_window_figure(LABS_0927_UNLABELED)) == 1
    assert len(reader_checks.unlabeled_window_figure("The running average — 157 g — is up.")) == 1
    assert len(reader_checks.unlabeled_window_figure("Sleep was short, and the running average is 81.6%.")) == 1


def test_mutation_control_a_sentence_wide_pairing_fires_on_the_two_clause_sentence(monkeypatch):
    monkeypatch.setattr(reader_checks, "_CLAUSE_JOIN_RE", re.compile(r"(?!x)x"))
    assert len(reader_checks.unlabeled_window_figure(GLUCOSE_0927_TWO_CLAUSES)) == 1


# Ruling 8 (owner, 2026-10-01, #4343): a stated date range, or "based on N logged days",
# COUNTS as a labelled window. The first two are verbatim from the held 2026-10-01 17:00Z
# finals (EVALRET#coach_brief physical_coach 17:05:23Z, labs_coach 17:06:29Z).
PHYSICAL_1001_RANGE = (
    "Average heart rate across those five walks, each logged between September 24th and September 30th, held right "
    "around 116 bpm — exactly where I want it for easy aerobic base work."
)
LABS_1001_COUNT = (
    "In practical terms, I cannot tell you whether the wearable rebound after the September 10th trough represents real "
    "physiological adaptation or is simply the number bouncing back toward its own average — a pattern with 26 nights "
    "behind it but no lab to anchor it."
)
RULING_8 = (
    PHYSICAL_1001_RANGE,
    LABS_1001_COUNT,
    "The running average for deep sleep is 19.4%, based on 21 logged days.",
    "His average was 150 g from September 24 to 30.",
    "Protein averaged 150 g, September 24–30.",
    "Recovery averaged 74% between Monday and Friday.",
)


def test_ruling_8_a_date_range_or_a_day_count_is_a_window():
    for text in RULING_8:
        assert reader_checks.unlabeled_window_figure(text) == [], text
    # still held: a date alone, and no window at all
    assert len(reader_checks.unlabeled_window_figure("Average 2,000 kcal on Friday, September 25.")) == 1
    assert len(reader_checks.unlabeled_window_figure("The running average for deep sleep is 19.4%.")) == 1


def test_mutation_control_the_pre_ruling_window_forms_hold_the_live_finals(monkeypatch):
    # origin/main's window regex before ruling 8, verbatim
    n = "|".join(reader_checks._NUMBER_WORDS)
    pre = re.compile(
        r"\b(?:over|across)\s+(?:the\s+)?(?:last\s+|past\s+|those\s+|these\s+)?(?:\d+|" + n + r"|twenty\S*)\s+(?:\w+\s+)?"
        r"(?:days?|nights?|weeks?|sessions?|weigh-ins?)\b"
        r"|\bsince\s+\w+|\bthrough\s+\w+"
        r"|\b(?:\d+|" + n + r")[- ](?:day|night|week)\b"
        r"|\b(?:this|last|past)\s+(?:week|month)\b",
        re.IGNORECASE,
    )
    monkeypatch.setattr(reader_checks, "_WINDOW_RE", pre)
    for text in (PHYSICAL_1001_RANGE, LABS_1001_COUNT, RULING_8[2]):
        assert len(reader_checks.unlabeled_window_figure(text)) == 1, text


def test_ruling_8_extension_one_sessions_average_with_its_date_is_labelled():
    # Owner, 2026-10-02 (answer a): the 10-01 dry run held physical (judge 87) on this sentence.
    live = "The heart rate on those walks — 116.4 bpm average on September 30 and 116.1 bpm on October 1 — sat inside the cap."
    assert reader_checks.unlabeled_window_figure(live) == []
    assert reader_checks.unlabeled_window_figure("He averaged 116 bpm on Wednesday, September 30.") == []
    # Controls: a RUNNING average or an EWMA on a date still hides its span.
    assert len(reader_checks.unlabeled_window_figure("The running average on September 30 was 310.2 lb.")) == 1
    assert len(reader_checks.unlabeled_window_figure("1,596 kcal EWMA on the night of September 24.")) == 1
    assert "116 bpm average on September 30" in reader_checks.prompt_reader_rules()
