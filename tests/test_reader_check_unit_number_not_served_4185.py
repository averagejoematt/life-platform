"""#4185 §2.5 — the `unit_number_not_served` reader CHECK class, proven against the frozen live corpus.

A figure written WITH a unit (g, kcal, lb, %, ms, bpm, days, hours) that is not on the
generation's own allow-list. A unit voids the benign-small-count exemption in
`grounded_generation.fabricated_numbers` (`unit_voids_benign=True`): "6 days" is a claim,
"6 meals" is a count. Eli's 106.9 g / 316.9 lb, Okafor's 171 days, Reyes's 33 g / 36 %.

Fixture-driven (tests/grounding_corpus/reader_checks/), never a tree sweep. The shared
contract (`reader_checks_corpus.assert_class_contract`) asserts: every live specimen
that names this class fails it; every fixture that does not name it passes it; and the
MUTATION CONTROL — this class replaced by a no-op — lets every specimen through, so
the test cannot be satisfied by some other class firing.
"""

import reader_checks_corpus as corpus
from coach import reader_checks

CHECK = "unit_number_not_served"


def test_live_specimens_fail_controls_pass_and_the_mutation_control_is_red(monkeypatch):
    corpus.assert_class_contract(CHECK, monkeypatch)


from ai import grounded_generation  # noqa: E402


def test_unarmed_without_an_allow_list():
    assert reader_checks.unit_number_not_served("33g below target", allowed=None) == []


def test_a_unit_voids_the_small_count_exemption_but_a_bare_count_keeps_it():
    assert [f["claimed"] for f in reader_checks.unit_number_not_served("6 days without logs", allowed=set())] == [6.0]
    assert reader_checks.unit_number_not_served("three meals, 6 of them logged", allowed=set()) == []


def test_the_grounded_generation_default_is_unchanged_for_every_existing_caller():
    assert grounded_generation.fabricated_numbers("6 days without logs", set()) == []
    assert grounded_generation.fabricated_numbers("6 days without logs", set(), unit_voids_benign=True) == [6.0]
    findings = grounded_generation.grounding_findings("6 days without logs", allowed=set(), unit_voids_benign=True)
    assert [f["type"] for f in findings] == ["fabricated_number"]


def test_a_rounding_of_a_served_figure_is_a_restatement():
    assert reader_checks.unit_number_not_served("153 g a day", allowed={153.3}) == []
