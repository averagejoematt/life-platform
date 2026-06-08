"""tests/test_cost_governor.py — tier decision logic (N-08).

Pure unit tests of the projection→tier policy: the projection may escalate at
most ONE tier above what ACTUAL month-to-date spend justifies (none at all in
the early-month window). No AWS calls.
"""

from __future__ import annotations

import importlib

import pytest


@pytest.fixture(scope="module")
def gov():
    return importlib.import_module("operational.cost_governor_lambda")


# ── _tier_for: threshold mapping ─────────────────────────────────────────────


@pytest.mark.parametrize(
    "projected,expected",
    [
        (0, 0),
        (54.99, 0),
        (55, 1),
        (64.99, 1),
        (65, 2),
        (72.99, 2),
        (73, 3),
        (500, 3),
    ],
)
def test_tier_thresholds(gov, projected, expected):
    assert gov._tier_for(projected) == expected


# ── _decide_tier: actual-spend cap ───────────────────────────────────────────


def test_n08_regression_projection_overshoot_capped_to_tier1(gov):
    """The 2026-06-05/06 incident: $28.86 actual, $157 projected, day 6.
    Old behavior: tier 3 (all AI off). New: tier 1 (heaviest spender paused)."""
    assert gov._decide_tier(projected=157.0, mtd=28.86, elapsed_days=5.8) == 1


def test_early_month_projection_fully_ignored(gov):
    """Day 2, front-loaded fixed charges: $15 actual → $233 projected.
    Inside EARLY_MONTH_DAYS the projection gets no benefit of the doubt."""
    assert gov._decide_tier(projected=233.0, mtd=15.56, elapsed_days=1.5) == 0


def test_genuine_runaway_unlocks_higher_tiers(gov):
    """Real dollars unlock the harsh tiers: actual already past tier 2 ($65),
    projection past tier 3 → escalate the full way."""
    assert gov._decide_tier(projected=120.0, mtd=66.0, elapsed_days=20.0) == 3


def test_actual_at_ceiling_is_tier3_regardless_of_projection(gov):
    assert gov._decide_tier(projected=74.0, mtd=74.0, elapsed_days=28.0) == 3


def test_projection_below_actual_never_inflated_by_cap(gov):
    """min(), not max(): a calm projection with high-ish actual stays at the
    projection tier (late month, spend tapering)."""
    assert gov._decide_tier(projected=54.0, mtd=56.0, elapsed_days=29.0) == 0


def test_post_pause_stuck_projection_de_escalates(gov):
    """Failure mode 2: AI paused, projection frozen high for weeks. Tier must
    track actual spend (+1), not the stale projection — so it recovers."""
    # mid-month, actual well under tier 1, projection still screaming tier 3
    assert gov._decide_tier(projected=150.0, mtd=40.0, elapsed_days=12.0) == 1


def test_all_quiet_is_tier0(gov):
    assert gov._decide_tier(projected=30.0, mtd=10.0, elapsed_days=10.0) == 0
