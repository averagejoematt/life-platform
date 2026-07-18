"""tests/test_stats_refresh_recovery.py — recovery honesty + finalized-selection.

Guards the public_stats recovery semantics. Since #1369 the derivation lives in
the canonical resolver (web/vitals_resolver.py) — site_stats_refresh_lambda
consumes it instead of carrying its own `_recovery_status`/`_get_latest_finalized`
copies. Same invariants, one home:
  * recovery_status pairs status with the % — never a color without a number
    behind it (the public_stats `recovery_pct: null` + `recovery_status: "red"`
    honesty bug, where a *missing* reading read as a *bad* one).
  * resolve_vitals picks the most recent record whose recovery_score is
    populated, so today's not-yet-scored Whoop record can't blank a real value.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

from fakes import FakeDdbTable  # noqa: E402
from web import (
    site_stats_refresh_lambda as srl,  # noqa: E402
    vitals_resolver,  # noqa: E402
)


def test_recovery_status_pairs_with_value():
    # a real % gets a color
    assert vitals_resolver.recovery_status(80) == "green"
    assert vitals_resolver.recovery_status(50) == "yellow"
    assert vitals_resolver.recovery_status(30) == "red"
    # boundaries
    assert vitals_resolver.recovery_status(67) == "green"
    assert vitals_resolver.recovery_status(34) == "yellow"
    assert vitals_resolver.recovery_status(33.9) == "red"


def test_recovery_status_never_colors_a_missing_reading():
    # THE honesty invariant: no number -> no color (so the UI never shows a stale dot)
    assert vitals_resolver.recovery_status(None) is None


def test_refresh_consumes_the_canonical_resolver():
    """#1369 wiring guard: the refresh lambda must not regrow a private
    derivation — it imports resolve_vitals and its old local copies are gone."""
    assert srl.resolve_vitals is vitals_resolver.resolve_vitals
    assert not hasattr(srl, "_recovery_status")
    assert not hasattr(srl, "_get_latest_finalized")


def test_resolver_skips_unscored_today():
    # newest-first: today's record exists but recovery_score is unscored (null),
    # yesterday's is finalized at 30.
    table = FakeDdbTable(
        rows=[
            {"sk": "DATE#2026-06-28", "recovery_score": None},
            {"sk": "DATE#2026-06-27", "recovery_score": 30},
        ]
    )
    out = vitals_resolver.resolve_vitals(table, "USER#matthew#SOURCE#")
    assert out["recovery_pct"] == 30
    assert out["recovery_as_of"] == "2026-06-27"
    # and the paired status is honest
    assert out["recovery_status"] == "red"


def test_resolver_honest_empty_when_none_scored():
    table = FakeDdbTable(rows=[{"sk": "DATE#2026-06-28", "recovery_score": None}])
    out = vitals_resolver.resolve_vitals(table, "USER#matthew#SOURCE#")
    assert out["recovery_pct"] is None
    assert out["recovery_status"] is None
