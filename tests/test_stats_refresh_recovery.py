"""tests/test_stats_refresh_recovery.py — recovery honesty + finalized-selection.

Guards two fixes in site_stats_refresh_lambda:
  * _recovery_status pairs status with the % — never a color without a number
    behind it (the public_stats `recovery_pct: null` + `recovery_status: "red"`
    honesty bug, where a *missing* reading read as a *bad* one).
  * _get_latest_finalized picks the most recent record whose field is populated,
    so today's not-yet-scored Whoop record can't blank a real recovery value.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

from fakes import FakeDdbTable  # noqa: E402
from web import site_stats_refresh_lambda as srl  # noqa: E402


def test_recovery_status_pairs_with_value():
    # a real % gets a color
    assert srl._recovery_status(80) == "green"
    assert srl._recovery_status(50) == "yellow"
    assert srl._recovery_status(30) == "red"
    # boundaries
    assert srl._recovery_status(67) == "green"
    assert srl._recovery_status(34) == "yellow"
    assert srl._recovery_status(33.9) == "red"


def test_recovery_status_never_colors_a_missing_reading():
    # THE honesty invariant: no number -> no color (so the UI never shows a stale dot)
    assert srl._recovery_status(None) is None


def test_get_latest_finalized_skips_unscored_today(monkeypatch):
    # phase_filter.with_phase_filter is imported inside the function; stub it to passthrough
    import types

    monkeypatch.setitem(sys.modules, "phase_filter", types.SimpleNamespace(with_phase_filter=lambda kw: kw))
    # newest-first: today's record exists but recovery_score is unscored (null),
    # yesterday's is finalized at 30.
    table = FakeDdbTable(
        rows=[
            {"sk": "DATE#2026-06-28", "recovery_score": None},
            {"sk": "DATE#2026-06-27", "recovery_score": 30},
        ]
    )
    rec = srl._get_latest_finalized(table, "whoop", "recovery_score")
    assert rec.get("sk") == "DATE#2026-06-27"
    assert srl._safe_float(rec, "recovery_score") == 30
    # and the paired status is honest
    assert srl._recovery_status(srl._safe_float(rec, "recovery_score")) == "red"


def test_get_latest_finalized_empty_when_none_scored(monkeypatch):
    import types

    monkeypatch.setitem(sys.modules, "phase_filter", types.SimpleNamespace(with_phase_filter=lambda kw: kw))
    table = FakeDdbTable(rows=[{"sk": "DATE#2026-06-28", "recovery_score": None}])
    assert srl._get_latest_finalized(table, "whoop", "recovery_score") == {}
