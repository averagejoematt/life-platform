"""
ADR-100 — the degradation ladder protects readers (#351).

Simulated budget-tier escalation: the PUBLIC ask endpoints (`website_ai`) must
still answer at tier 2 — where they previously went dark — and every internal
narrative/ensemble feature must be off at or before tier 2. Tier 3 blocks
everything. Pins the sacrifice order so a future edit can't quietly make the
reader-facing hook the first casualty again.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

import budget_guard  # noqa: E402


def _at_tier(monkeypatch, tier):
    monkeypatch.setattr(budget_guard, "current_tier", lambda: tier)


def test_tier0_everything_runs(monkeypatch):
    _at_tier(monkeypatch, 0)
    for f in budget_guard._FEATURE_CUTOFF:
        assert budget_guard.allow(f), f


def test_tier1_internal_daily_ai_pauses_first(monkeypatch):
    _at_tier(monkeypatch, 1)
    assert not budget_guard.allow("coach_narrative")
    assert not budget_guard.allow("ensemble")
    assert budget_guard.allow("website_ai")
    assert budget_guard.allow("chronicle")


def test_tier2_readers_still_answered(monkeypatch):
    """The ADR-100 teeth: at tier 2 (where the ask endpoints previously went
    dark) readers are STILL answered while internal content is paused."""
    _at_tier(monkeypatch, 2)
    assert budget_guard.allow("website_ai"), "readers must degrade last (ADR-100)"
    assert not budget_guard.allow("chronicle")
    assert not budget_guard.allow("coach_narrative")
    assert not budget_guard.allow("ensemble")


def test_tier3_hard_stop_blocks_everything(monkeypatch):
    _at_tier(monkeypatch, 3)
    for f in budget_guard._FEATURE_CUTOFF:
        assert not budget_guard.allow(f), f


def test_sacrifice_order_is_readers_last():
    """Structural: no internal narrative feature may outlive website_ai."""
    cut = budget_guard._FEATURE_CUTOFF
    for internal in ("coach_narrative", "ensemble", "chronicle"):
        assert cut[internal] <= cut["website_ai"], f"{internal} must degrade at or before the reader surface"
    assert cut["website_ai"] == budget_guard._HARD_STOP_TIER
