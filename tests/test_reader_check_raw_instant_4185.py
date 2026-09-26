"""#4185 §2.5 — the `raw_instant` reader CHECK class, proven against the frozen live corpus.

A raw machine instant or ISO date in reader text (`05:05Z`, `T05:05`, `2026-09-24`), or a
clock time that IS a served UTC instant read as local time — Park's "median ~4:45 AM" onset
when `sleep_start` medians ~04:53Z (~9:53 PM PT) and the served avg_bedtime is 10:31 PM.

Fixture-driven (tests/grounding_corpus/reader_checks/), never a tree sweep. The shared
contract (`reader_checks_corpus.assert_class_contract`) asserts: every live specimen
that names this class fails it; every fixture that does not name it passes it; and the
MUTATION CONTROL — this class replaced by a no-op — lets every specimen through, so
the test cannot be satisfied by some other class firing.
"""

import reader_checks_corpus as corpus
from coach import reader_checks

CHECK = "raw_instant"


def test_live_specimens_fail_controls_pass_and_the_mutation_control_is_red(monkeypatch):
    corpus.assert_class_contract(CHECK, monkeypatch)


def test_literal_instants():
    for text in ("slept at 05:05Z", "onset 2026-09-24T05:05", "on 2026-09-24"):
        assert reader_checks.raw_instant(text), text


def test_the_clock_arm_is_unarmed_without_served_instants():
    assert reader_checks.raw_instant("median onset ~4:45 AM", facts={}) == []


def test_the_pacific_rendering_of_the_same_instant_passes():
    facts = {"utc_instants": ["2026-09-24T04:47:49Z"]}  # 9:47 PM PT
    assert reader_checks.raw_instant("his bedtime was 9:47 PM", facts=facts) == []
    assert reader_checks.raw_instant("his bedtime was 4:47 AM", facts=facts)


def test_winter_offset_is_pst():
    facts = {"utc_instants": ["2026-12-10T05:30:00Z"]}  # 9:30 PM PST
    assert reader_checks.raw_instant("bedtime 9:30 PM", facts=facts) == []
    assert reader_checks.raw_instant("bedtime 5:30 AM", facts=facts)
