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
