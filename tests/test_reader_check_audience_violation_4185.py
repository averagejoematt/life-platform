"""#4185 §2.5 — the `audience_violation` reader CHECK class, proven against the frozen live corpus.

A reader slot (public_summary / public_ask / headline_read / daily) that addresses Matthew
directly. The class is a thin call into `audience_guard.is_owner_directed` — the guard is
not reimplemented, so the two can never disagree.

Fixture-driven (tests/grounding_corpus/reader_checks/), never a tree sweep. The shared
contract (`reader_checks_corpus.assert_class_contract`) asserts: every live specimen
that names this class fails it; every fixture that does not name it passes it; and the
MUTATION CONTROL — this class replaced by a no-op — lets every specimen through, so
the test cannot be satisfied by some other class firing.
"""

import reader_checks_corpus as corpus
from coach import reader_checks

CHECK = "audience_violation"


def test_live_specimens_fail_controls_pass_and_the_mutation_control_is_red(monkeypatch):
    corpus.assert_class_contract(CHECK, monkeypatch)


def test_is_a_call_into_the_audience_guard_not_a_second_definition(monkeypatch):
    monkeypatch.setattr(reader_checks, "is_owner_directed", lambda text: True)
    assert [f["check"] for f in reader_checks.audience_violation("Matthew logged food on Friday.")] == [CHECK]


def test_runs_only_on_a_reader_slot_never_on_the_owner_narrative():
    text = "You logged every day this week, Friday included."
    assert CHECK not in {f["check"] for f in reader_checks.reader_findings(text)}
    assert CHECK in {f["check"] for f in reader_checks.reader_findings(text, slot="headline_read")}
