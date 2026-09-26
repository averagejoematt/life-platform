"""tests/test_cross_surface_vitals_trend_classifier_4180.py — #4180: a coach's
honest recovery/HRV TREND sentence is not a claim about the current reading.

THE LIVE FAILURE, 2026-09-25 18:30Z qa-smoke (`qa-smoke-failures` ALARM since):
`cross_surface:vitals` failed on "Dr. Nathan Reeves cites recovery 71.7% vs
cockpit 99%". The served coach text (`/api/coaching-dashboard`) reads:

    "His recovery EWMA has climbed from 71.7% to 82.2% over seven days."

71.7 is the trend's own START value — a smoothed history's past point, not a
claim about last night's reading (99%). The pre-#4180 extractor had no notion
of "trend/aggregate" language and read the first number near "recovery" as a
bare current claim.

THE FIX: `classify_claims` (shared with #4186) splits every cited figure into
`current` / `trend_end` / `trend_start`. Only `current` is compared against the
cockpit's raw reading. A trend's END value is compared against a served
`{metric}_ewma` cockpit field IF ONE EXISTS, else skipped. A trend's START value
is ALWAYS skipped. Every skip is named in the check's detail line — a skip is
visible, never silent.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

from operational import weight_truth_qa as wq  # noqa: E402

# ── The 2026-09-25 specimen, as measured ────────────────────────────────────────

COCKPIT_09_25 = {
    "recovery_pct": 99.0,
    "hrv_ms": 60.0,
    "rhr_bpm": 55.0,
    "sleep_hours": 7.5,
    "recovery_as_of": "2026-09-25",
    "sleep_as_of": "2026-09-25",
}

_NATHAN_REEVES_TREND = {
    "name": "Dr. Nathan Reeves",
    "position_summary": "His recovery EWMA has climbed from 71.7% to 82.2% over seven days.",
}


def test_the_09_25_trend_specimen_passes():
    ok, msg = wq.assess_cross_surface_vitals(COCKPIT_09_25, [_NATHAN_REEVES_TREND])
    assert ok, msg


def test_the_trend_start_is_named_as_skipped():
    ok, msg = wq.assess_cross_surface_vitals(COCKPIT_09_25, [_NATHAN_REEVES_TREND])
    assert ok, msg
    assert "71.7" in msg and "trend's START point" in msg, msg


def test_the_trend_end_is_named_as_skipped_when_no_ewma_is_served():
    ok, msg = wq.assess_cross_surface_vitals(COCKPIT_09_25, [_NATHAN_REEVES_TREND])
    assert ok, msg
    assert "82.2" in msg and "no served EWMA figure to compare against" in msg, msg


def test_mutation_control_the_same_figure_stated_as_current_still_fails():
    """The #4180 regression control: strip the trend language, keep the number,
    and the pre-#4180 FAIL must still fire — the fix narrows what counts as a
    trend, it never widens what counts as agreement."""
    coach = {"name": "Dr. Nathan Reeves", "position_summary": "last night's recovery was 71.7%"}
    ok, msg = wq.assess_cross_surface_vitals(COCKPIT_09_25, [coach])
    assert not ok
    assert "recovery 71.7" in msg and "vs cockpit 99" in msg, msg


def test_a_bare_aggregate_without_a_from_to_range_is_also_treated_as_trend_end():
    """'7-day average recovery' with no explicit from/to range still isn't a
    claim about tonight."""
    coach = {"name": "Dr. Sarah Chen", "position_summary": "Your 7-day average recovery has been running at 84%."}
    ok, msg = wq.assess_cross_surface_vitals(COCKPIT_09_25, [coach])
    assert ok, msg
    assert "84" in msg, msg


def test_a_served_ewma_field_the_trend_end_disagrees_with_still_fails():
    """Forward-compatible: no `{metric}_ewma` field is served today, but if one
    ever is, a trend's END value is judged against IT, not skipped."""
    cockpit = dict(COCKPIT_09_25, recovery_ewma=95.0)
    ok, msg = wq.assess_cross_surface_vitals(cockpit, [_NATHAN_REEVES_TREND])
    assert not ok, msg
    assert "82.2" in msg and "served EWMA 95" in msg, msg


def test_a_served_ewma_field_the_trend_end_agrees_with_passes_without_a_skip_note_for_that_figure():
    cockpit = dict(COCKPIT_09_25, recovery_ewma=82.5)
    ok, msg = wq.assess_cross_surface_vitals(cockpit, [_NATHAN_REEVES_TREND])
    assert ok, msg
    # the trend-END figure is no longer named as a skip once a served EWMA exists and agrees —
    # only the trend-START figure (always skipped, unconditionally) remains in the note.
    assert "82.2" not in msg.split("skipped (trend/aggregate):", 1)[-1]


def test_vitals_cited_in_backward_compatibility_is_unaffected_by_trend_detection():
    """`vitals_cited_in`'s pre-#4180 contract (current-only, dict of lists) must
    be byte-identical for prose that carries no trend language — the existing
    #2113/#2738/#3793/#4025 fixtures already prove this via the full suite; this
    is the trend-specific complement: a trend sentence's figures must be ABSENT
    from `vitals_cited_in`'s current-only view."""
    assert wq.vitals_cited_in(_NATHAN_REEVES_TREND["position_summary"]) == {}
    assert wq.vitals_cited_in("last night's recovery was 71.7%") == {"recovery": [71.7]}


def test_a_dated_sentence_still_wins_over_a_trend_sentence():
    """If a sentence is BOTH dated and trend-shaped, the existing dated-sentence
    exemption still applies (it is checked first) — no new precedence question."""
    coach = {"name": "c", "position_summary": "On September 18th his rolling recovery average was 71.7%."}
    current, trend_end, trend_start = wq.classify_claims(coach["position_summary"], wq._VITALS_PATTERNS, wq._VITALS_DOMAIN)
    assert current == {} and trend_end == {} and trend_start == []


# ── mutation control: disabling trend detection reds the specimen again ───────


def test_mutation_disabling_trend_sentence_detection_reds_the_specimen(monkeypatch):
    import re

    monkeypatch.setattr(wq, "_TREND_SENTENCE", re.compile(r"(?!x)x"))  # a pattern that can never match
    ok, msg = wq.assess_cross_surface_vitals(COCKPIT_09_25, [_NATHAN_REEVES_TREND])
    assert not ok, "disabling trend detection must fail the 09-25 specimen again: " + msg
