"""tests/test_habit_causality.py — #422 EVR-01/02/03 pure-logic contract.

Covers the deterministic note parse (no inference beyond the literal trigger:/reward:
convention, ADR-104) and the cross-page completion merge (one signal per page, explicit
double-count prevention against the habit tracker's own records). No AWS — pure functions.
"""

import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

import habit_causality as hc  # noqa: E402


# ── parse_note (EVR-01/02) ─────────────────────────────────────────────────────
def test_parse_note_lifts_trigger_and_reward_prefixes():
    out = hc.parse_note("trigger: morning coffee\nreward: felt clear-headed")
    assert out["trigger"] == "morning coffee"
    assert out["reward"] == "felt clear-headed"


def test_parse_note_is_case_insensitive_and_keeps_extra_prefixes():
    assert hc.parse_note("Cue: alarm")["trigger"] == "alarm"
    assert hc.parse_note("Payoff: calmer")["reward"] == "calmer"


def test_parse_note_never_infers_a_cause():
    # A plain note has no trigger/reward — it is context, not a guessed cause.
    out = hc.parse_note("was traveling, hotel gym was closed")
    assert out["trigger"] is None
    assert out["reward"] is None
    assert out["raw"] == "was traveling, hotel gym was closed"


def test_parse_note_empty_is_empty():
    out = hc.parse_note("   ")
    assert out == {"trigger": None, "reward": None, "raw": ""}


def test_clip_note_bounds_length():
    long = "x" * 800
    clipped = hc.clip_note(long)
    assert len(clipped) <= 501 and clipped.endswith("…")


def test_slugify_is_key_safe_and_stable():
    assert hc.slugify_habit("Out Of Bed Before 5am!") == "out-of-bed-before-5am"
    assert hc.slugify_habit("") == "habit"


# ── cross-page signals (EVR-03) ────────────────────────────────────────────────
def test_one_signal_per_page():
    # Exactly one entry per evidence page, each pointing at one habit group.
    pages = list(hc.CROSS_PAGE_SIGNALS)
    assert len(pages) == len(set(pages))
    groups = [s["group"] for s in hc.CROSS_PAGE_SIGNALS.values()]
    assert len(groups) == len(set(groups)), "one page per group — no two doors to one group"


def test_derive_only_emits_present_components_above_floor():
    scores = {"movement": 80, "nutrition": 20, "journal": None}
    sig = hc.derive_cross_page_signals(scores)
    assert sig == {"Performance": 80}  # nutrition below floor, journal absent → dropped


def test_derive_handles_missing_component_scores():
    assert hc.derive_cross_page_signals(None) == {}
    assert hc.derive_cross_page_signals({}) == {}


# ── merge / double-count prevention (EVR-03, the heart of the AC) ───────────────
def test_cross_page_fills_only_empty_group_days():
    tracker = {"2026-07-01": {"Nutrition": 90}}
    cross = {"2026-07-01": {"Performance": 75}}
    merged = hc.merge_cross_page_group_scores(tracker, cross)
    # Tracker's Nutrition untouched; Performance filled from cross-page.
    assert merged["2026-07-01"]["groups"] == {"Nutrition": 90, "Performance": 75}
    assert merged["2026-07-01"]["cross_page"] == {"Performance": 75}


def test_cross_page_never_double_counts_a_tracked_group():
    # The tracker already scored Performance that day → the cross-page signal is DROPPED,
    # never summed or overwritten. This is the explicit double-count prevention.
    tracker = {"2026-07-01": {"Performance": 40}}
    cross = {"2026-07-01": {"Performance": 95}}
    merged = hc.merge_cross_page_group_scores(tracker, cross)
    assert merged["2026-07-01"]["groups"] == {"Performance": 40}
    assert merged["2026-07-01"]["cross_page"] == {}


def test_cross_page_covers_days_absent_from_tracker():
    merged = hc.merge_cross_page_group_scores({}, {"2026-07-02": {"Recovery": 60}})
    assert merged["2026-07-02"]["groups"] == {"Recovery": 60}
    assert merged["2026-07-02"]["cross_page"] == {"Recovery": 60}
