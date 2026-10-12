"""#4848 -- no test on main pins a literal that the wall clock moves.

Incident 2026-10-12T00:00Z: ``test_energy_budget_cross_phase_4032`` asserted ``tdee == 2426``
through ``health.tdee.resolve_age`` (fractional age from ``datetime.utcnow()``); the rounded BMR
stepped one kcal at midnight UTC and main went red with no code change.  The sweep lives in
``scripts/check_test_clock_literals.py`` (AST walk; see its docstring for the class and its stated
recall bound).  This file holds the gate (sweep == 0) and the controls that prove it can fail.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import check_test_clock_literals as g  # noqa: E402


@pytest.fixture(scope="module")
def world():
    return g.build_producers(REPO)


def _scan(src, world, name="test_synthetic_4848.py"):
    producers, inj, base = world
    return g.scan_source(src, name, producers, inj, base)


PINNED = """
from health import tdee as tdee_core

def test_age():
    age, _basis, _err = tdee_core.resolve_age("1990-01-01")
    assert age == 36.2
"""


def test_the_sweep_is_empty(world):
    members = g.sweep(REPO, world)
    assert members == {}, (
        "tests pin a literal through an unfrozen clock-scaled producer (freeze the clock, derive the expectation "
        f"from the same call, or add '# clock-literal-ok: <reason>'): {members}"
    )


def test_the_producer_set_reaches_the_incident_chain(world):
    producers, _inj, base = world
    assert ("tdee", "resolve_age") in producers
    for key in (("tools_health", "_get_energy_expenditure"), ("tools_nutrition", "_energy_budget")):
        assert key in producers, f"one-hop callers of resolve_age must be producers: {key}"
    assert "resolve_age" in base


def test_negative_control_an_unfrozen_pin_is_flagged(world):
    assert _scan(PINNED, world) == [("tdee", "resolve_age")]


def test_control_an_injected_clock_clears(world):
    ok = PINNED.replace('resolve_age("1990-01-01")', 'resolve_age("1990-01-01", now=__import__("datetime").datetime(2026, 1, 1))')
    assert _scan(ok, world) is None


def test_control_a_monkeypatched_clock_clears(world):
    ok = PINNED.replace(
        "def test_age():",
        "def test_age(monkeypatch):\n    monkeypatch.setattr(tdee_core, 'resolve_age', lambda d, now=None: (36.2, 'x', None))",
    )
    assert _scan(ok, world) is None


def test_control_a_reasoned_marker_clears_but_a_bare_one_does_not(world):
    assert _scan(PINNED + "\n# clock-literal-ok: the literal is the unrelated fixture constant, not the age\n", world) is None
    assert _scan(PINNED + "\n# clock-literal-ok:\n", world) == [("tdee", "resolve_age")]


def test_control_a_count_assertion_is_not_a_clock_literal(world):
    src = PINNED.replace("assert age == 36.2", "assert len([age]) == 1")
    assert _scan(src, world) is None


def test_mutation_the_4032_file_with_its_freeze_removed_fails_the_guard(world):
    """The real file, minus the one patch of ``resolve_age`` that holds its literals, is a member."""
    path = REPO / "tests" / "test_energy_budget_cross_phase_4032.py"
    src = path.read_text()
    assert _scan(src, world, path.name) is None, "the shipped file must be clean"
    needle = 'monkeypatch.setattr(tdee_core, "resolve_age"'
    assert needle in src, "the freeze this mutation removes has moved -- re-point the control"
    mutated = src.replace(needle, 'monkeypatch.setattr(tdee_core, "noop_4848"')
    found = _scan(mutated, world, path.name)
    assert found and ("tools_health", "_get_energy_expenditure") in found, found


def test_control_an_unrelated_patch_with_a_date_value_does_not_clear(world):
    src = PINNED + "\n\ndef _x(monkeypatch):\n    monkeypatch.setattr('other.mod.thing', lambda: {'date': 1})\n"
    assert _scan(src, world) == [("tdee", "resolve_age")]


def test_control_a_dotted_string_patch_of_the_clock_clears(world):
    """The positive twin: the same dotted-string form, but the TARGET names the clock, does clear."""
    src = PINNED + "\n\ndef _x(monkeypatch):\n    monkeypatch.setattr('health.tdee.datetime', lambda: 1)\n"
    assert _scan(src, world) is None
