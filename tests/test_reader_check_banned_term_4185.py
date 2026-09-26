"""#4185 §2.5 — the `banned_term` reader CHECK class, proven against the frozen live corpus.

The §2.1A READER RULES ban list + §2.1F per-coach additions, as a regex in code (moved out of
the Haiku judge): EWMA, autocorrelation, etiology, gate, Mifflin/BMR, logging gap, …

Fixture-driven (tests/grounding_corpus/reader_checks/), never a tree sweep. The shared
contract (`reader_checks_corpus.assert_class_contract`) asserts: every live specimen
that names this class fails it; every fixture that does not name it passes it; and the
MUTATION CONTROL — this class replaced by a no-op — lets every specimen through, so
the test cannot be satisfied by some other class firing.
"""

import reader_checks_corpus as corpus
from coach import reader_checks

CHECK = "banned_term"


def test_live_specimens_fail_controls_pass_and_the_mutation_control_is_red(monkeypatch):
    corpus.assert_class_contract(CHECK, monkeypatch)


def test_one_finding_per_distinct_term_case_insensitive():
    found = [f["claimed"].lower() for f in reader_checks.banned_term("EWMA, ewma, and the Mifflin BMR; n=21.")]
    assert found == ["ewma", "n=21", "bmr", "mifflin"]


def test_plain_words_pass():
    assert reader_checks.banned_term("His running average is rising; easy cardio starts next week.") == []


def test_every_listed_term_carries_a_plain_replacement():
    assert all(plain for _, plain in reader_checks.READER_BANNED_TERMS)
