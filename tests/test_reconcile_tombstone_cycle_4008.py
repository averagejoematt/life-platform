"""#4008 — the opening-cycle tombstone re-stamp: the planner touches exactly the
`stamp_is_a_later_cycle` class and nothing else, and the census's own predicate decides.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


rec = _load("reconcile_tombstone_cycle_4008", ROOT / "deploy" / "reconcile_tombstone_cycle_4008.py")
rv = _load("restart_verify_for_4008", ROOT / "deploy" / "restart_verify.py")

# cycle 15 opened 2026-08-22, 16 opened 2026-09-05, 17 opened 2026-09-06 (the shape of the live registry;
# the values are a fixture, not a claim about the live map)
GENESES = {15: "2026-08-22", 16: "2026-09-05", 17: "2026-09-06"}
ABANDONED: dict = {}


def _row(pk, sk, reason, cycle):
    return {"pk": pk, "sk": sk, "tombstoned_reason": reason, "cycle": cycle}


def test_an_opening_stamp_is_planned_to_the_closing_cycle():
    plan = rec.plan_corrections(
        [_row("USER#matthew#SOURCE#insights", "DATE#2026-09-01", "experiment_restart_2026-09-05", 16)], GENESES, ABANDONED, rv=rv
    )
    assert plan == [
        {
            "pk": "USER#matthew#SOURCE#insights",
            "sk": "DATE#2026-09-01",
            "family": "SOURCE#insights",
            "reason": "experiment_restart_2026-09-05",
            "genesis": "2026-09-05",
            "from_cycle": 16,
            "to_cycle": 15,
        }
    ]


@pytest.mark.parametrize(
    "row",
    [
        _row("USER#matthew#SOURCE#insights", "DATE#a", "experiment_restart_2026-09-05", 15),  # matched: closing cycle
        _row("USER#matthew#SOURCE#insights", "DATE#b", "experiment_restart_2026-09-05", 12),  # earlier: birth cycle kept (#1202)
        _row("USER#matthew#SOURCE#insights", "DATE#c", "experiment_restart_2026-09-05", None),  # no stamp: never invented
        _row("USER#matthew#SOURCE#insights", "DATE#d", "legacy_daily_aggregate_superseded_by_per_workout", 16),  # undated reason
        _row("USER#matthew#SOURCE#insights", "DATE#e", "experiment_restart_2031-01-01", 16),  # unresolved genesis: not ours to guess
        _row("USER#matthew#SOURCE#insights", "DATE#f", None, 16),  # not a tombstone
    ],
)
def test_every_other_census_class_is_left_alone(row):
    assert rec.plan_corrections([row], GENESES, ABANDONED, rv=rv) == []


def test_the_planner_agrees_with_check_22s_own_classification():
    """Every row the planner corrects is exactly a row check 22 files under TOMB_LATER, and no other."""
    rows = [
        _row("COACH#mind_coach", "PREDICTION#x", "experiment_restart_2026-09-05", 16),
        _row("USER#matthew#SOURCE#chronicle", "DATE#2026-08-01", "experiment_restart_2026-09-05", 15),
        _row("USER#matthew#SOURCE#chronicle", "DATE#2026-07-01", "experiment_restart_2026-08-22", 12),
    ]
    counts, _examples, scanned = rv.tombstone_provenance_census([rows], GENESES, ABANDONED)
    plan = rec.plan_corrections(rows, GENESES, ABANDONED, rv=rv)
    assert scanned == 3 and counts.get(rv.TOMB_LATER) == 1 == len(plan)
    assert plan[0]["pk"] == "COACH#mind_coach" and plan[0]["family"] == "COACH#mind_coach"


def test_the_writer_census_groups_by_family_with_the_stamp_pair():
    rows = [
        _row("USER#matthew#SOURCE#insights", "DATE#a", "experiment_restart_2026-09-05", 16),
        _row("USER#matthew#SOURCE#insights", "DATE#b", "experiment_restart_2026-09-05", 16),
        _row("COACH#mind_coach", "PREDICTION#x", "experiment_restart_2026-09-06", 17),
    ]
    census = rec.writer_census(rec.plan_corrections(rows, GENESES, ABANDONED, rv=rv))
    assert census["SOURCE#insights"]["rows"] == 2 and census["SOURCE#insights"]["stamps"] == {"16->15": 2}
    assert census["COACH#mind_coach"]["rows"] == 1 and census["COACH#mind_coach"]["geneses"] == {"2026-09-06": 1}


def test_MUTATION_the_later_cycle_comparison_is_load_bearing(monkeypatch):
    """Point the planner at the wrong side of the comparison and the opening row must stop being planned."""
    src = (ROOT / "deploy" / "reconcile_tombstone_cycle_4008.py").read_text()
    assert src.count("if stamp > closing:") == 1, "the one comparison this repair hangs on"
    mutated = src.replace("if stamp > closing:", "if stamp < closing:")
    ns: dict = {"__file__": str(ROOT / "deploy" / "reconcile_tombstone_cycle_4008.py"), "__name__": "mutated_4008"}
    exec(compile(mutated, "mutated_4008", "exec"), ns)  # noqa: S102 — the mutation control, in-process
    plan = ns["plan_corrections"](
        [_row("USER#matthew#SOURCE#insights", "DATE#a", "experiment_restart_2026-09-05", 16)], GENESES, ABANDONED, rv=rv
    )
    assert plan == [], "with the comparison inverted the opening row is no longer corrected — so the real line is load-bearing"
