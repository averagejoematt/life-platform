"""Tests for engagement_core — presence / quiet-stretch detection.

Pure-core tests: no AWS, no clock. Anchors on the real trigger scenario (last
food log Friday, silent since, wearables still flowing) and its return.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))

from content.engagement_core import (  # noqa: E402
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


# ── #955: the genesis clamp (decision option (a)) ────────────────────────────
# Presence is measured WITHIN the current experiment window: pre-genesis logs
# are out-of-window, the gap accrues from genesis (never from the prior cycle's
# stall), and a first log after genesis is a fresh start, not a "return".

GENESIS = "2026-07-12"  # the cycle-5 genesis the live bug is anchored on

# The live launch-eve scenario: cycle 4's last food log was 2026-06-24, then
# ~2.5 weeks of silence across the reset boundary.
_CYCLE4_TAIL = {
    "macrofactor": ["2026-06-24", "2026-06-23", "2026-06-22"],
    "hevy": ["2026-06-20"],
    "habitify": ["2026-06-24"],
    "notion": [],
}


def test_genesis_day1_without_a_log_reads_present():
    # Day 1, nothing logged yet — the gap starts at genesis (0), not at 06-24
    # (which unclamped reads as an 18-day dark/alarm stall).
    sig = compute_presence("2026-07-12", _CYCLE4_TAIL, wearable_latest=_wearables_flowing(), experiment_start=GENESIS)
    assert sig["presence_class"] == PRESENT
    assert sig["gap_days"] == 0
    assert sig["severity"] == "none"
    assert sig["channels_quiet"] == []
    assert sig["last_food_log_date"] is None  # honest: nothing logged THIS cycle
    assert sig["experiment_window_start"] == GENESIS
    # ...whereas unclamped, the same inputs foreground the archived stall.
    unclamped = compute_presence("2026-07-12", _CYCLE4_TAIL, wearable_latest=_wearables_flowing())
    assert unclamped["presence_class"] == DARK
    assert unclamped["severity"] == "alarm"


def test_genesis_day1_with_a_log_reads_present():
    cd = {k: list(v) for k, v in _CYCLE4_TAIL.items()}
    cd["macrofactor"] = ["2026-07-12"] + cd["macrofactor"]
    sig = compute_presence("2026-07-12", cd, wearable_latest=_wearables_flowing(), experiment_start=GENESIS)
    assert sig["presence_class"] == PRESENT
    assert sig["gap_days"] == 0
    assert sig["last_food_log_date"] == "2026-07-12"


def test_no_cross_genesis_return_beat():
    # First log after genesis, previous log pre-genesis: a fresh start — never
    # "just returned after ~17 days quiet" on cycle-5 Day 1.
    from content.engagement_core import presence_prompt_block

    cd = {k: list(v) for k, v in _CYCLE4_TAIL.items()}
    cd["macrofactor"] = ["2026-07-12"] + cd["macrofactor"]
    sig = compute_presence("2026-07-12", cd, wearable_latest=_wearables_flowing(), experiment_start=GENESIS)
    assert sig["returned"] is False
    assert sig["resumed_after_days"] is None
    assert "JUST RETURNED" not in presence_prompt_block(sig)
    # The exact regression the clamp kills: unclamped, this fires as a ~17-day return.
    unclamped = compute_presence("2026-07-12", cd, wearable_latest=_wearables_flowing())
    assert unclamped["returned"] is True
    assert "JUST RETURNED" in presence_prompt_block(unclamped)


def test_gap_accrues_from_genesis_not_prior_cycle():
    # 8 days into cycle 5 with still nothing logged: the silence is real and must
    # escalate — but counted from genesis (effective 7), never from 06-24 (~25).
    sig = compute_presence("2026-07-20", _CYCLE4_TAIL, wearable_latest=_wearables_flowing(), experiment_start=GENESIS)
    assert sig["gap_days"] == 7  # (07-20 − 07-12) − 1 lag day
    assert sig["presence_class"] == DARK
    for detail in sig["channel_detail"].values():
        assert detail["gap_days"] == 7


def test_pre_genesis_compute_day_is_quiet_about_the_archive():
    # Launch eve (T−1): the countdown, not the wiped cycle's stall — present/none,
    # so the ack gate never arms off cycle-4 silence.
    from content.engagement_core import presence_ack_required, presence_prompt_block

    sig = compute_presence("2026-07-11", _CYCLE4_TAIL, wearable_latest=_wearables_flowing(), experiment_start=GENESIS)
    assert sig["presence_class"] == PRESENT
    assert sig["gap_days"] == 0
    assert sig["severity"] == "none"
    assert presence_ack_required(sig) is False
    assert presence_prompt_block(sig) == ""


def test_post_genesis_lull_and_return_still_detected():
    # The clamp must not lobotomise the feature: a real post-genesis lull still
    # classifies, and a return from it still fires — with post-genesis facts only.
    cd = {
        "macrofactor": ["2026-07-20", "2026-07-13", "2026-07-12", "2026-06-24"],
        "hevy": ["2026-07-12"],
        "habitify": ["2026-07-13"],
        "notion": [],
    }
    sig = compute_presence("2026-07-20", cd, wearable_latest=_wearables_flowing(), experiment_start=GENESIS)
    assert sig["returned"] is True
    assert sig["resumed_after_days"] == 6  # 07-13 → 07-20, both endpoints exclusive
    assert sig["presence_class"] == PRESENT


def test_unclamped_callers_unchanged():
    # experiment_start=None keeps the legacy semantics byte-for-byte.
    sig = compute_presence(TODAY, _fresh(), wearable_latest=_wearables_flowing())
    assert sig["presence_class"] == PRESENT
    assert sig["experiment_window_start"] is None
    empty = compute_presence(TODAY, {"macrofactor": [], "hevy": [], "habitify": [], "notion": []})
    assert empty["presence_class"] == DARK
    assert empty["gap_days"] is None


# ── #2382: never-logged-this-cycle must not read as a pause ───────────────────
# The live defect: with MacroFactor quiet since before genesis, the genesis clamp
# (#955) supplies gap_days=4 with last_food_log_date=None, and the prompt block
# rendered "it has been ~4 days since his last food log" — handing every coach a
# transition that never happened. Six of eight live cards narrated it ("your food
# logs paused four days ago", "dark since around August 2nd") while the cockpit
# one door away said the source was 44 days quiet.


def _never_logged_sig(gap=4):
    """A clamped signal: real silence, but nothing EVER logged this cycle."""
    return {
        "presence_class": "dark",
        "severity": "loud",
        "gap_days": gap,
        "last_food_log_date": None,
        "experiment_window_start": "2026-08-03",
        "channels_quiet": ["food"],
        "returned": False,
    }


def test_never_logged_this_cycle_is_stated_as_absence_not_a_pause():
    from content.engagement_core import presence_prompt_block

    block = presence_prompt_block(_never_logged_sig())
    # #3294: the sentence is scoped to FOOD — the only category this branch's fact
    # covers. The old "NOTHING has been logged" wording asserted a platform-wide
    # absence off a single-source derivation, and the board published it widened to
    # four channels, two of which had records in the window.
    assert "NO FOOD has been logged this cycle" in block
    assert "NOTHING has been logged" not in block, "the unscoped form is the #3294 defect"
    assert "predates this cycle" in block
    assert "since his last food log" not in block, "there is no last food log this cycle to count from"


def test_never_logged_block_forbids_the_false_transition_phrasings():
    from content.engagement_core import presence_prompt_block

    block = presence_prompt_block(_never_logged_sig())
    for forbidden in ("'paused'", "'went silent N days ago'", "date a transition"):
        assert forbidden in block, f"the block must explicitly forbid {forbidden} phrasing"


def test_a_real_in_window_gap_still_gets_the_day_count_phrasing():
    """The negative control: when a real log exists this cycle, the pause framing is
    TRUE and must survive — the fix must not lobotomise the honest case."""
    from content.engagement_core import presence_prompt_block

    sig = dict(_never_logged_sig(), last_food_log_date="2026-08-04")
    block = presence_prompt_block(sig)
    assert "since his last food log" in block
    assert "last logged 2026-08-04" in block
    assert "NOTHING has been logged this cycle" not in block


def test_the_ai_calls_prompt_contract_no_longer_prescribes_the_fabrication():
    """ai_calls' ENGAGEMENT bullet used to instruct the exact false phrasing by
    example, unconditionally: 'e.g. "it's been four days since you logged a meal"'.
    The exemplar is only honest when last_food_log_date is present; the NULL case
    must mandate never-logged phrasing and forbid the pause framing. Source-level
    pin, same idiom as the cast-roster and privacy literal guards."""
    import os

    src = open(os.path.join(os.path.dirname(__file__), "..", "lambdas", "ai", "ai_calls.py"), encoding="utf-8").read()
    assert "If `last_food_log_date` is PRESENT" in src
    assert "If `last_food_log_date` is NULL" in src
    assert "nothing logged yet this cycle" in src
    assert "NOT a pause" in src
