"""#4185 §2.5 — the `absence_premise` reader CHECK class, proven against the frozen live corpus.

A gap / silence / "went dark" premise that the served gap fact refutes: served gap ≤ 1 day,
a stated day-count that is not the served one, or "since <date>" that is not the served
last log. Webb's "six-day logging gap since September 19th" on 20 of 20 logged days.

Fixture-driven (tests/grounding_corpus/reader_checks/), never a tree sweep. The shared
contract (`reader_checks_corpus.assert_class_contract`) asserts: every live specimen
that names this class fails it; every fixture that does not name it passes it; and the
MUTATION CONTROL — this class replaced by a no-op — lets every specimen through, so
the test cannot be satisfied by some other class firing.
"""

import reader_checks_corpus as corpus
from coach import reader_checks

CHECK = "absence_premise"


def test_live_specimens_fail_controls_pass_and_the_mutation_control_is_red(monkeypatch):
    corpus.assert_class_contract(CHECK, monkeypatch)


FACTS = {"lag_days": 1, "last_food_log_date": "2026-09-25", "days_logged": 20}


def test_unarmed_without_a_served_gap_fact():
    assert reader_checks.absence_premise("Six days without logs.", facts={}) == []


def test_word_and_digit_counts_both_parse():
    for text in ("Six days without logs.", "a 6-day logging gap", "The food log went dark."):
        assert [f["check"] for f in reader_checks.absence_premise(text, facts=FACTS)], text


def test_a_true_gap_of_the_served_length_passes():
    facts = {"gap_days": 6}
    assert reader_checks.absence_premise("Six days without logs.", facts=facts) == []
    assert reader_checks.absence_premise("Five days without logs.", facts=facts), "a wrong count is still refuted"


def test_journal_sentences_read_the_journal_gap_not_the_food_gap():
    facts = {"lag_days": 1, "journal_gap_days": 6}
    assert reader_checks.absence_premise("A six-day journaling silence.", facts=facts) == []
