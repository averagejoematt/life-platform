"""#4185 §2.5 — the `ask_cardinality` reader CHECK class, proven against the frozen live corpus.

A `public_ask` carrying more than one imperative clause — "Restart logging tomorrow …, and
add a vegetable serving at lunch …". Exactly one ask, stated once.

Fixture-driven (tests/grounding_corpus/reader_checks/), never a tree sweep. The shared
contract (`reader_checks_corpus.assert_class_contract`) asserts: every live specimen
that names this class fails it; every fixture that does not name it passes it; and the
MUTATION CONTROL — this class replaced by a no-op — lets every specimen through, so
the test cannot be satisfied by some other class firing.
"""

import reader_checks_corpus as corpus
from coach import reader_checks

CHECK = "ask_cardinality"


def test_live_specimens_fail_controls_pass_and_the_mutation_control_is_red(monkeypatch):
    corpus.assert_class_contract(CHECK, monkeypatch)


def test_one_ask_passes_two_fail():
    assert reader_checks.ask_cardinality("I\x27ve asked him to add a vegetable serving at lunch this week.") == []
    assert reader_checks.ask_cardinality("I\x27ve asked him to add a vegetable serving at lunch and restart logging tomorrow.")
    assert reader_checks.ask_cardinality("I\x27ve asked him to log dinner. I\x27ve asked him to walk.")


def test_runs_only_on_public_ask():
    text = "Restart logging tomorrow, and add a vegetable serving."
    assert "ask_cardinality" not in {f["check"] for f in reader_checks.reader_findings(text, slot="headline_read")}
    assert "ask_cardinality" in {f["check"] for f in reader_checks.reader_findings(text, slot="public_ask")}
