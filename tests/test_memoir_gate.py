"""tests/test_memoir_gate.py — the "misses must outnumber humblebrags" check (#553).

Pure functions, no AWS. Pins the deterministic rule: a memoir may only skip
naming a specific miss when there genuinely was no refuted call this quarter.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

import memoir_gate  # noqa: E402

_CONFIRMED = {"date": "2026-08-01", "status": "confirmed", "subdomain": "sleep_quality", "metric": "deep_sleep_pct", "reason": "held"}
_REFUTED = {"date": "2026-08-10", "status": "refuted", "subdomain": "recovery", "metric": "hrv_ms", "reason": "reversed"}


def test_no_refuted_learnings_needs_no_citation():
    ok, reason = memoir_gate.cites_a_miss("A quiet quarter, mostly confirmations.", [_CONFIRMED])
    assert ok is True
    assert reason == "no_refuted_learnings_this_quarter"


def test_pure_highlight_reel_fails_when_a_miss_exists():
    # Deliberately avoids the refuted record's own subdomain/metric words
    # ("recovery"/"hrv_ms") — a memoir that never even brushes up against
    # what it got wrong must fail, not just one that avoids the jargon.
    text = "This quarter went well overall, and I'm proud of the streak I've built."
    ok, reason = memoir_gate.cites_a_miss(text, [_CONFIRMED, _REFUTED])
    assert ok is False
    assert reason == "no_miss_cited_despite_refuted_learnings"


def test_citing_the_specific_metric_passes():
    text = "My hrv_ms call this quarter didn't hold up, and I've had to rethink the mechanism."
    ok, reason = memoir_gate.cites_a_miss(text, [_CONFIRMED, _REFUTED])
    assert ok is True
    assert "cites_specific_miss" in reason


def test_generic_honest_language_passes_without_naming_the_metric():
    text = "I was wrong about one of my calls this quarter, and I want to own that plainly."
    ok, reason = memoir_gate.cites_a_miss(text, [_CONFIRMED, _REFUTED])
    assert ok is True
    assert reason == "cites_generic_miss_language"


def test_refuted_markers_ignores_confirmed_records():
    markers = memoir_gate.refuted_markers([_CONFIRMED, _REFUTED])
    assert markers == ["recovery", "hrv_ms"]  # subdomain, then metric


def test_empty_learnings_list_needs_no_citation():
    ok, reason = memoir_gate.cites_a_miss("Nothing to reckon with here.", [])
    assert ok is True
    assert reason == "no_refuted_learnings_this_quarter"
