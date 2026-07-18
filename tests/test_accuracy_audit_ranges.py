"""Range semantics of accuracy_audit.impossible_values.

Regression for the 2026-07-17 spurious rollback: journey.progress_pct = -1.2 (weight
above the cycle-6 baseline on Day 5 — honest per ADR-104) was flagged "impossible",
which failed post-deploy visual QA and auto-rolled-back a healthy site deploy.
progress_pct is signed and valid down to -100; every other _pct stays [0,100].
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from accuracy_audit import impossible_values


def _fields(findings):
    return {f["field"] for f in findings}


def test_negative_progress_pct_is_honest_not_impossible():
    ps = {"journey": {"progress_pct": -1.2, "lost_lbs": -1.6}}
    assert impossible_values(ps) == []


def test_progress_pct_bounded_at_minus_100():
    ps = {"journey": {"progress_pct": -100.5}}
    assert _fields(impossible_values(ps)) == {"journey.progress_pct"}


def test_progress_pct_over_100_still_impossible():
    ps = {"journey": {"progress_pct": 101}}
    assert _fields(impossible_values(ps)) == {"journey.progress_pct"}


def test_other_pct_fields_stay_strictly_non_negative():
    ps = {"vitals": {"recovery_pct": -1}, "journey": {"body_fat_pct": -0.1}}
    assert _fields(impossible_values(ps)) == {"vitals.recovery_pct", "journey.body_fat_pct"}


def test_negative_ctl_still_impossible():
    ps = {"training": {"ctl_fitness": -955}}
    assert _fields(impossible_values(ps)) == {"training.ctl_fitness"}
