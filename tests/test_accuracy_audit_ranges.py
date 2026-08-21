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


# ── the scan reaches the whole payload, not two top-level blocks (2026-08-21) ──
#
# The rubric above was always right; its DENOMINATOR was wrong. `impossible_values`
# read exactly two blocks (`journey`, `vitals`) of exactly one document
# (`public_stats.json`), so `/api/sleep_detail` served
#
#     sleep_trend[3].light_pct = 106.7
#
# to the public site and nothing looked — the bad value sat inside a LIST, on an
# endpoint this scan never fetched. A correct rule with a denominator narrower than
# the live surface is #2652's defect wearing the numeric gate's clothes.
#
# The risk of widening is the one this file already documents: the 2026-07-17
# spurious rollback. More surface swept = more chances to false-red a healthy deploy
# (#2841's class). Two things bound it — the signed-field semantics are preserved
# exactly (tested above and below), and the widened sweep was MEASURED against live
# before arming: 59 of 59 endpoints fetched, one finding, the known defect.

from accuracy_audit import scan_impossible_pcts  # noqa: E402


def test_scan_finds_an_impossible_pct_nested_in_a_list():
    """THE regression. The live defect was inside `sleep_trend[3]` — a list element,
    two levels down. A scanner that only reads top-level blocks cannot see it."""
    payload = {"sleep_trend": [{"date": "2026-08-19", "light_pct": 49.9}, {"date": "2026-08-20", "light_pct": 106.7}]}
    findings = scan_impossible_pcts(payload, source="/api/sleep_detail")
    assert len(findings) == 1, f"expected exactly the one impossible value, got {findings}"
    assert findings[0]["field"] == "sleep_trend[1].light_pct", "the finding must name a locatable path, not just the field"
    assert findings[0]["value"] == 106.7
    assert findings[0]["severity"] == "high"


def test_scan_keeps_the_signed_field_exemption_at_any_depth():
    """The 2026-07-17 rollback must not come back through the new recursion — a signed
    progress_pct is honest wherever it appears, not only at the top level."""
    payload = {"pages": [{"journey": {"progress_pct": -1.2}}]}
    assert scan_impossible_pcts(payload) == []


def test_scan_ignores_non_numeric_and_boolean_pcts():
    """`True` is an int in Python. A boolean flag whose name ends in _pct must not be
    graded as a percentage of 1%."""
    assert scan_impossible_pcts({"has_pct": True, "label_pct": "n/a", "empty_pct": None}) == []


def test_scan_is_not_vacuous_on_a_deeply_nested_breach():
    """Mutation proof for the recursion itself: a value buried several levels down must
    still be found, or 'zero findings' means 'the walk stopped early'."""
    payload = {"a": {"b": [{"c": {"d": [{"deep_pct": 250.0}]}}]}}
    findings = scan_impossible_pcts(payload)
    assert len(findings) == 1 and findings[0]["value"] == 250.0, "the walk did not reach a nested breach"


def test_impossible_values_still_grades_public_stats_the_same_way():
    """Back-compat: `impossible_values` is the entry point tests/pr_render_gate.py uses.
    Delegating its percentage half to the shared scanner must not change its verdicts."""
    assert _fields(impossible_values({"vitals": {"sleep_pct": 140}})) == {"vitals.sleep_pct"}
    assert impossible_values({"journey": {"progress_pct": -1.2}}) == []
