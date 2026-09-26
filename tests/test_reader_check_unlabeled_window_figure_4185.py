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
