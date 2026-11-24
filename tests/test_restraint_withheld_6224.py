"""tests/test_restraint_withheld_6224.py — no public route serves a restraint figure (#6224).

Owner ruling 2026-11-23 on /data/vices/: "Check those disclosures against my explicit public-content approvals ...
Where authorization is absent, withhold the data rather than silently grandfathering it into the public site." No
explicit approval was found for naming any restraint category, for any restraint streak or relapse count, or for the
count of the private categories — and the unlabelled aggregates let a reader count the private categories by
subtraction and read their behaviour (his boundary covers "paraphrases and inferences"). So nothing is served:

  * /api/vice_streaks -> {"published": false} only;
  * /api/mind_overview -> vice_streaks [] and vice_timeline [] (the stored daily total also counted the
    never-public categories, so the timeline revealed how many of those exist);
  * /api/habits, /api/habit_registry -> no restraint row, no `restraints_unnamed`, no restraint-only group.

The walk (tests/restraint_route_walk.py — every public GET route, a table planted with synthetic restraint habits)
reports every restraint-figure key on any route; the set must be empty. The names are covered by
tests/test_restraint_labels_5948.py on the same walk.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lambdas"))
sys.path.insert(0, str(ROOT / "tests"))

import restraint_route_walk as RW  # noqa: E402
from common import restraint_publication as RP  # noqa: E402
from test_restraint_labels_5948 import _walk  # noqa: E402


@pytest.fixture(scope="module")
def walk() -> dict:
    return _walk()


def test_no_public_route_serves_a_restraint_figure(walk):
    assert walk["answered"] >= 140, walk["answered"]
    assert walk["figures"] == {}, f"public routes serving a restraint figure: {walk['figures']}"
    assert {k: v for k, v in walk["bodies"]["/api/vice_streaks"].items() if k != "_meta"} == {"published": False}
    assert RP.RESTRAINT_DATA_PUBLISHED is False and RP.NAMED_CATEGORIES == {}


def test_must_fail_control_the_figure_scan_sees_the_pre_6224_shapes():
    """The scan is not vacuous: each body the routes served before #6224 is reported by it."""
    old_vices = {"vices": [{"name": "x", "current_streak": 3}], "unnamed": {"tracked": 4}, "total_held": 4, "total_tracked": 6}
    old_mind = {"vice_streaks": [{"current_streak": 3, "holding": True}], "vice_timeline": [{"date": "d", "held": 5, "total": 8}]}
    old_habits = {"per_habit": [], "restraints_unnamed": {"count": 4}}
    assert RW.restraint_figures(old_vices) == [".total_held", ".total_tracked", ".unnamed", ".vices"]
    assert RW.restraint_figures(old_mind) == [".vice_streaks", ".vice_timeline"]
    assert RW.restraint_figures(old_habits) == [".restraints_unnamed"]
    assert RW.restraint_figures({"vice_streaks": [], "vice_timeline": [], "published": False}) == []
