"""Tests for engagement_core — presence / quiet-stretch detection.

Pure-core tests: no AWS, no clock. Anchors on the real trigger scenario (last
food log Friday, silent since, wearables still flowing) and its return.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))

from engagement_core import (  # noqa: E402
    DARK,
    LIGHT,
    PRESENT,
    QUIET,
    compute_presence,
)

TODAY = "2026-06-30"  # the reference "now"


def _fresh():
    """Channel dates where everything logged today/yesterday → present."""
    return {
        "macrofactor": ["2026-06-30", "2026-06-29", "2026-06-28"],
        "hevy": ["2026-06-29", "2026-06-27"],
        "habitify": ["2026-06-30", "2026-06-29"],
        "notion": ["2026-06-28"],
    }


def _wearables_flowing():
    return {"whoop": "2026-06-30", "apple_health": "2026-06-29", "eightsleep": "2026-06-30"}


def test_present_when_logging():
    sig = compute_presence(TODAY, _fresh(), wearable_latest=_wearables_flowing())
    assert sig["presence_class"] == PRESENT
    assert sig["gap_days"] == 0
    assert sig["returned"] is False
    assert sig["planned_pause"] is False


def test_lag_grace_yesterday_is_present():
    # Logged yesterday only (24h nutrition lag) — must read as present, not a gap.
    cd = {"macrofactor": ["2026-06-29"], "habitify": ["2026-06-29"], "hevy": [], "notion": []}
    sig = compute_presence(TODAY, cd, wearable_latest=_wearables_flowing())
    assert sig["gap_days"] == 0
    assert sig["presence_class"] == PRESENT


def test_the_trigger_scenario_quiet():
    # Last food log Friday 06-26; silent since; today Tuesday 06-30 → eff gap 3.
    cd = {
        "macrofactor": ["2026-06-26", "2026-06-25", "2026-06-24"],
        "hevy": ["2026-06-25"],
        "habitify": ["2026-06-26"],
        "notion": ["2026-06-24"],
    }
    sig = compute_presence(TODAY, cd, wearable_latest=_wearables_flowing())
    assert sig["presence_class"] == QUIET
    assert sig["gap_days"] == 3
    assert sig["last_food_log_date"] == "2026-06-26"
    assert sig["passive_still_flowing"] is True
    # food + training + habits + journal all beyond tolerance
    assert "food" in sig["channels_quiet"]


def test_extended_silence_is_dark():
    cd = {
        "macrofactor": ["2026-06-22"],  # 8 days ago → eff gap 7
        "hevy": ["2026-06-20"],
        "habitify": ["2026-06-22"],
        "notion": [],
    }
    sig = compute_presence(TODAY, cd, wearable_latest=_wearables_flowing())
    assert sig["presence_class"] == DARK
    assert sig["gap_days"] >= 5


def test_no_data_in_window_is_dark():
    cd = {"macrofactor": [], "hevy": [], "habitify": [], "notion": []}
    sig = compute_presence(TODAY, cd, wearable_latest=_wearables_flowing())
    assert sig["presence_class"] == DARK
    assert sig["gap_days"] is None


def test_return_detection_and_weight_regain():
    # Came back today after a 5-day silence (last engaged 06-24).
    cd = {
        "macrofactor": ["2026-06-30", "2026-06-24", "2026-06-23"],
        "hevy": ["2026-06-24"],
        "habitify": ["2026-06-30"],
        "notion": [],
    }
    weight = [("2026-06-20", 300.0), ("2026-06-24", 301.0), ("2026-06-30", 304.2)]
    sig = compute_presence(TODAY, cd, wearable_latest=_wearables_flowing(), weight_series=weight)
    assert sig["returned"] is True
    assert sig["resumed_after_days"] == 5
    assert sig["presence_class"] == PRESENT  # fresh again
    assert sig["weight_delta_over_gap"] == 3.2  # 304.2 - 301.0


def test_short_gap_is_not_a_return():
    # Only 1 missed day — below LULL_MIN, not a "welcome back".
    cd = {"macrofactor": ["2026-06-30", "2026-06-28"], "hevy": [], "habitify": [], "notion": []}
    sig = compute_presence(TODAY, cd, wearable_latest=_wearables_flowing())
    assert sig["returned"] is False


def test_travel_suppresses_to_planned_pause():
    # Silent since 06-26, but 06-27..06-29 are logged travel days → planned pause.
    cd = {
        "macrofactor": ["2026-06-26"],
        "hevy": ["2026-06-25"],
        "habitify": ["2026-06-26"],
        "notion": [],
    }
    travel = {"2026-06-27", "2026-06-28", "2026-06-29"}
    sig = compute_presence(TODAY, cd, wearable_latest=_wearables_flowing(), travel_days=travel)
    assert sig["planned_pause"] is True
    assert sig["planned_pause_reason"] == "travel"
    assert sig["presence_class"] in (PRESENT, LIGHT)  # never escalates to quiet/dark


def test_sick_suppresses_to_planned_pause():
    cd = {"macrofactor": ["2026-06-26"], "hevy": [], "habitify": ["2026-06-26"], "notion": []}
    sick = {"2026-06-27", "2026-06-28", "2026-06-29"}
    sig = compute_presence(TODAY, cd, wearable_latest=_wearables_flowing(), sick_days=sick)
    assert sig["planned_pause"] is True
    assert sig["planned_pause_reason"] == "sick"
    assert sig["presence_class"] in (PRESENT, LIGHT)


def test_wearables_dark_when_not_flowing():
    cd = _fresh()
    stale_wear = {"whoop": "2026-06-20", "apple_health": "2026-06-19", "eightsleep": "2026-06-18"}
    sig = compute_presence(TODAY, cd, wearable_latest=stale_wear)
    assert sig["passive_still_flowing"] is False


def test_passive_metrics_carried_verbatim():
    metrics = {"recovery_trend": "red all weekend", "rhr": 64}
    sig = compute_presence(TODAY, _fresh(), passive_metrics=metrics)
    assert sig["passive_read"] == metrics


def test_no_internal_keys_leak():
    sig = compute_presence(TODAY, _fresh())
    # _dates is internal scratch and must not survive into the record.
    assert "_dates" not in sig
    for detail in sig["channel_detail"].values():
        assert "_dates" not in detail
