"""
ADR-100 + ADR-125 — the degradation ladder sacrifices by AUDIENCE, readers last.

Simulated budget-tier escalation pins the three-band order (ADR-125):
  band 1 INTERNAL/dev AI          (ensemble, coherence_semantic, chronicle_editor, reader_truth_qa)
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

_LAMBDAS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas")
sys.path.insert(0, _LAMBDAS)
sys.path.insert(0, os.path.join(_LAMBDAS, "operational"))

import budget_guard  # noqa: E402
import cost_governor_lambda  # noqa: E402

# The audience bands, as the ladder intends them (pause-tier per feature).
_INTERNAL = ("ensemble", "coherence_semantic", "chronicle_editor", "reader_truth_qa", "visual_ai_qa")
_READER_NARRATIVE = ("coach_narrative", "state_of_matthew", "daily_debrief", "chronicle")
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


# ── #1231: the cost_governor tier-change ALERT copy must mirror _FEATURE_CUTOFF ──
# _alert() emails Matthew _TIER_LABELS[new]; when those labels describe the
# pre-ADR-125 ladder (tier-2 "public website AI paused (/api/ask)"), the on-call
# is told the ask endpoint is down when it is not, and never hears which reader
# narrative actually paused. These derive the expected band from _FEATURE_CUTOFF
# so a future re-band of budget_guard forces the labels to move in lockstep.


def _tier_of(feature):
    return budget_guard._FEATURE_CUTOFF[feature]


def test_alert_labels_do_not_claim_ask_paused_before_its_real_cutoff():
    """The ask endpoints pause at cut['website_ai'] (tier 3). No LOWER tier's alert
    label may claim the ask endpoint is paused — the exact pre-ADR-125 defect where
    the tier-2 email said '/api/ask' was down while it still answered."""
    ask_tier = _tier_of("website_ai")
    labels = cost_governor_lambda._TIER_LABELS
    for tier, label in labels.items():
        mentions_ask = "/api/ask" in label or "board_ask" in label
        if tier < ask_tier:
            assert not mentions_ask, f"tier-{tier} label falsely names the ask endpoint (real cutoff is tier {ask_tier}): {label!r}"


def test_reader_narrative_tier_label_names_the_narrative_pause():
    """coach_narrative pauses at tier 2 (_FEATURE_CUTOFF); the tier-2 label must
    say a reader narrative paused, not omit it (the stale label named only the ask
    endpoint)."""
    narr_tier = _tier_of("coach_narrative")
    assert narr_tier == _tier_of("state_of_matthew") == _tier_of("chronicle")
    label = cost_governor_lambda._TIER_LABELS[narr_tier].lower()
    assert any(
        k in label for k in ("reader narrative", "coach commentary", "coach", "state of matthew", "chronicle")
    ), f"tier-{narr_tier} label must name the reader-narrative pause: {label!r}"
    assert "/api/ask" not in label and "board_ask" not in label, f"tier-{narr_tier} label must NOT claim the ask endpoint paused: {label!r}"


def test_hard_stop_tier_label_is_the_one_that_names_the_ask_endpoints():
    """The label for the tier where website_ai actually pauses is the one that must
    name the ask endpoints."""
    ask_tier = _tier_of("website_ai")
    label = cost_governor_lambda._TIER_LABELS[ask_tier]
    assert "/api/ask" in label, f"tier-{ask_tier} label must name the ask endpoint that pauses there: {label!r}"


def test_internal_tier_label_names_internal_ai():
    """Band 1 (internal/dev AI) pauses first; its alert label should say so, not
    describe heavy coach AI (the stale copy)."""
    internal_tier = max(_tier_of(f) for f in _INTERNAL)
    label = cost_governor_lambda._TIER_LABELS[internal_tier].lower()
    assert any(
        k in label for k in ("internal", "dev ai", "ensemble", "coherence")
    ), f"tier-{internal_tier} label must name the internal/dev AI pause: {label!r}"
