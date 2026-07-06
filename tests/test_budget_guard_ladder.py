"""
ADR-100 + ADR-125 — the degradation ladder sacrifices by AUDIENCE, readers last.

Simulated budget-tier escalation pins the three-band order (ADR-125):
  band 1 INTERNAL/dev AI          (ensemble, coherence_semantic, chronicle_editor)
  band 2 reader NARRATIVE content (coach_narrative, state_of_matthew, chronicle)
  band 3 irreducible reader       (website_ai = /api/ask+board_ask, daily_brief_ai)

The teeth: internal AI must pause a full tier before any reader-facing surface,
and the PUBLIC ask endpoints (+ the daily brief) degrade LAST — so a future edit
can't quietly make the reader product the first casualty of growth again (the
pre-ADR-125 defect, where coach_narrative paused at tier 1 while dev re-runs, the
actual June breach cause, kept spending).
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

import budget_guard  # noqa: E402

# The audience bands, as the ladder intends them (pause-tier per feature).
_INTERNAL = ("ensemble", "coherence_semantic", "chronicle_editor")
_READER_NARRATIVE = ("coach_narrative", "state_of_matthew", "chronicle")
_IRREDUCIBLE_READER = ("website_ai", "daily_brief_ai")


def _at_tier(monkeypatch, tier):
    monkeypatch.setattr(budget_guard, "current_tier", lambda: tier)


def test_tier0_everything_runs(monkeypatch):
    _at_tier(monkeypatch, 0)
    for f in budget_guard._FEATURE_CUTOFF:
        assert budget_guard.allow(f), f


def test_tier1_internal_ai_pauses_first(monkeypatch):
    """Band 1: internal/dev AI is off, but NOTHING a reader reads pauses yet."""
    _at_tier(monkeypatch, 1)
    for f in _INTERNAL:
        assert not budget_guard.allow(f), f"{f} (internal) must pause at tier 1"
    for f in _READER_NARRATIVE + _IRREDUCIBLE_READER:
        assert budget_guard.allow(f), f"{f} (reader) must still run at tier 1"


def test_tier2_reader_narrative_pauses_but_readers_still_answered(monkeypatch):
    """Band 2: narrative content is off, yet the ADR-100 teeth hold — the ask
    endpoints (where the budget defense previously went dark) STILL answer."""
    _at_tier(monkeypatch, 2)
    for f in _INTERNAL + _READER_NARRATIVE:
        assert not budget_guard.allow(f), f"{f} must be paused by tier 2"
    for f in _IRREDUCIBLE_READER:
        assert budget_guard.allow(f), f"{f} must degrade last (ADR-100)"


def test_tier3_hard_stop_blocks_everything(monkeypatch):
    _at_tier(monkeypatch, 3)
    for f in budget_guard._FEATURE_CUTOFF:
        assert not budget_guard.allow(f), f


def test_band_ordering_is_strict_internal_lt_narrative_lt_reader():
    """Structural: every internal feature pauses strictly before every reader
    narrative feature, which pauses before every irreducible reader promise."""
    cut = budget_guard._FEATURE_CUTOFF
    hardest_internal = max(cut[f] for f in _INTERNAL)
    softest_narrative = min(cut[f] for f in _READER_NARRATIVE)
    hardest_narrative = max(cut[f] for f in _READER_NARRATIVE)
    softest_reader = min(cut[f] for f in _IRREDUCIBLE_READER)
    assert hardest_internal < softest_narrative, "internal AI must pause before reader narrative"
    assert hardest_narrative < softest_reader, "reader narrative must pause before the irreducible reader surface"


def test_all_gated_features_are_classified():
    """No feature may drift back into the default (cutoff 3) bucket unclassified —
    the coherence_semantic bug (internal QA silently outliving readers) recurs
    exactly that way."""
    classified = set(_INTERNAL + _READER_NARRATIVE + _IRREDUCIBLE_READER)
    assert set(budget_guard._FEATURE_CUTOFF) == classified


def test_ask_endpoint_and_daily_brief_are_the_last_to_go():
    cut = budget_guard._FEATURE_CUTOFF
    assert cut["website_ai"] == budget_guard._HARD_STOP_TIER
    assert cut["daily_brief_ai"] == budget_guard._HARD_STOP_TIER
    for f in _INTERNAL + _READER_NARRATIVE:
        assert cut[f] < budget_guard._HARD_STOP_TIER, f"{f} must not survive to the hard stop"
