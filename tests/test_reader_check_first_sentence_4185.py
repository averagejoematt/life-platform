"""#4185 §2.5 — the `first_sentence` reader CHECK class, proven against the frozen live corpus.

Sentence 1 of a reader slot: ≤ 25 words, ≤ 160 chars, carrying a weekday/month word or
"asked him". The §2.6 illustrations themselves break it (each opening sentence is over 25
words) — recorded on their fixtures as a spec inconsistency, not relaxed here.

Fixture-driven (tests/grounding_corpus/reader_checks/), never a tree sweep. The shared
contract (`reader_checks_corpus.assert_class_contract`) asserts: every live specimen
that names this class fails it; every fixture that does not name it passes it; and the
MUTATION CONTROL — this class replaced by a no-op — lets every specimen through, so
the test cannot be satisfied by some other class firing.
"""

import reader_checks_corpus as corpus
from coach import reader_checks

CHECK = "first_sentence"


def test_live_specimens_fail_controls_pass_and_the_mutation_control_is_red(monkeypatch):
    corpus.assert_class_contract(CHECK, monkeypatch)


def test_a_short_dated_opening_passes_and_each_arm_fires_alone():
    assert reader_checks.first_sentence("On Friday, September 25 he logged 182 g of protein.") == []
    assert reader_checks.first_sentence("He logged 182 g of protein.")  # no date word
    assert reader_checks.first_sentence("On Friday " + "word " * 30 + ".")  # too long


def test_runs_only_on_a_reader_slot():
    assert "first_sentence" not in {f["check"] for f in reader_checks.reader_findings("He logged protein.")}
