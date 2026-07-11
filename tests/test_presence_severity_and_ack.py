"""#914 presence/stall-signal hardening.

Covers the four pure pieces engagement_core gained:
  1. the habitify "counts as logged" predicate (a record every day at
     total_completed=0 must NOT read as presence) — including the adaptive_mode
     _log_dates plumbing that applies it;
  2. the severity ladder (none | soft | loud | alarm) + per-channel
     dropout_streak_days;
  3. the ONE shared prompt block (presence_prompt_block), incl. the
     severity=alarm opening-paragraph mandate;
  4. the acknowledgment gate (deterministic anchor check + ADR-108
     regenerate-or-hold).
"""

import os
import sys
from decimal import Decimal

os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))

import engagement_core as ec  # noqa: E402

TODAY = "2026-06-30"


def _wearables_flowing():
    return {"whoop": "2026-06-30", "apple_health": "2026-06-29", "eightsleep": "2026-06-30"}


def _fresh():
    return {
        "macrofactor": ["2026-06-30", "2026-06-29"],
        "hevy": ["2026-06-29"],
        "habitify": ["2026-06-30"],
        "notion": ["2026-06-28"],
        "withings": ["2026-06-29"],
    }


# ── 1. the habitify presence predicate ───────────────────────────────────────


def test_habitify_zero_completion_does_not_count_as_logged():
    assert ec.channel_counts_as_logged("habitify", {"total_completed": 0}) is False
    assert ec.channel_counts_as_logged("habitify", {"total_completed": Decimal("0")}) is False
    assert ec.channel_counts_as_logged("habitify", {}) is False
    assert ec.channel_counts_as_logged("habitify", {"total_completed": 3}) is True
    assert ec.channel_counts_as_logged("habitify", {"total_completed": Decimal("1")}) is True


def test_other_channels_count_any_record():
    for src in ("macrofactor", "hevy", "notion", "withings"):
        assert ec.channel_counts_as_logged(src, {}) is True


def test_habitify_predicate_needs_total_completed_projected():
    assert "total_completed" in ec.channel_presence_fields("habitify")
    assert ec.channel_presence_fields("macrofactor") == ()


class _StubTable:
    """Minimal DDB table stub for adaptive_mode._log_dates."""

    def __init__(self, items):
        self._items = items
        self.last_projection = None
        self.last_kwargs = None
        self.put_items = []

    def query(self, **kwargs):
        self.last_projection = kwargs.get("ProjectionExpression")
        self.last_kwargs = kwargs
        return {"Items": self._items}

    def put_item(self, Item=None, **kwargs):
        self.put_items.append(Item)
        return {}


def _adaptive_mode(monkeypatch, items):
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas", "compute"))
    import adaptive_mode_lambda as am

    stub = _StubTable(items)
    monkeypatch.setattr(am, "table", stub)
    return am, stub


def test_log_dates_filters_zero_completion_habitify_days(monkeypatch):
    # 10 days of records, every one total_completed=0 — the live bug read this
    # as gap_days=0 because a record-day existed daily.
    items = [{"sk": f"DATE#2026-06-{20 + i:02d}", "total_completed": Decimal("0")} for i in range(10)]
    am, stub = _adaptive_mode(monkeypatch, items)
    dates = am._log_dates(
        "habitify",
        TODAY,
        attrs=ec.channel_presence_fields("habitify"),
        predicate=lambda it: ec.channel_counts_as_logged("habitify", it),
    )
    assert dates == []
    assert "total_completed" in stub.last_projection


def test_log_dates_keeps_completed_habitify_days(monkeypatch):
    items = [
        {"sk": "DATE#2026-06-28", "total_completed": Decimal("0")},
        {"sk": "DATE#2026-06-29", "total_completed": Decimal("4")},
    ]
    am, _ = _adaptive_mode(monkeypatch, items)
    dates = am._log_dates(
        "habitify",
        TODAY,
        attrs=ec.channel_presence_fields("habitify"),
        predicate=lambda it: ec.channel_counts_as_logged("habitify", it),
    )
    assert dates == ["2026-06-29"]


def test_log_dates_floor_clamps_window_start(monkeypatch):
    # #955: the genesis floor clamps the query's window start, so the prior
    # cycle's kept raw_timeseries can't reach the presence computation at all.
    am, stub = _adaptive_mode(monkeypatch, [])
    am._log_dates("macrofactor", "2026-07-14", floor="2026-07-12")
    assert stub.last_kwargs["ExpressionAttributeValues"][":lo"] == "DATE#2026-07-12"


def test_log_dates_without_floor_keeps_trailing_window(monkeypatch):
    am, stub = _adaptive_mode(monkeypatch, [])
    am._log_dates("macrofactor", "2026-07-14")
    assert stub.last_kwargs["ExpressionAttributeValues"][":lo"] == "DATE#2026-06-09"  # today − 35d


def test_log_dates_floor_before_window_start_is_inert(monkeypatch):
    # A genesis older than the trailing window must not WIDEN the query.
    am, stub = _adaptive_mode(monkeypatch, [])
    am._log_dates("macrofactor", "2026-07-14", floor="2026-01-01")
    assert stub.last_kwargs["ExpressionAttributeValues"][":lo"] == "DATE#2026-06-09"


def test_compute_and_store_engagement_is_genesis_clamped(monkeypatch):
    # End-to-end through the lambda plumbing on cycle-5 Day 1 (the live #955
    # scenario): the table only holds the prior cycle's records, yet the stored
    # STATE#current must read present/none with no cross-cycle return beat —
    # even if a query somehow returned pre-genesis rows (core filter as
    # defense-in-depth behind the query floor).
    from datetime import date as _date, timedelta as _td

    from constants import EXPERIMENT_START_DATE

    # Anchor everything to the live genesis so future resets can't time-bomb this.
    day1 = EXPERIMENT_START_DATE
    prior = _date.fromisoformat(day1) - _td(days=18)
    items = [{"sk": f"DATE#{prior.isoformat()}"}, {"sk": f"DATE#{(prior - _td(days=1)).isoformat()}"}]
    am, stub = _adaptive_mode(monkeypatch, items)
    monkeypatch.setattr(am, "_engagement_reference_today", lambda: day1)

    signal = am.compute_and_store_engagement()
    assert signal["experiment_window_start"] == day1
    assert signal["presence_class"] == "present"
    assert signal["severity"] == "none"
    assert signal["returned"] is False
    assert signal["last_food_log_date"] is None
    assert ec.presence_ack_required(signal) is False
    # Both the DATE# history row and STATE#current were written.
    sks = {it.get("sk") for it in stub.put_items}
    assert sks == {f"DATE#{day1}", "STATE#current"}


def test_ten_zero_completion_days_make_habits_channel_quiet():
    # The predicate leaves habitify's window EMPTY even though records exist —
    # compute_presence must then report the habits channel quiet.
    cd = _fresh()
    cd["habitify"] = []  # what _log_dates returns after the predicate
    sig = ec.compute_presence(TODAY, cd, wearable_latest=_wearables_flowing())
    assert "habits" in sig["channels_quiet"]
    assert sig["channel_detail"]["habitify"]["gap_days"] is None
    assert sig["channel_detail"]["habitify"]["dropout_streak_days"] is None


# ── 2. the severity ladder ───────────────────────────────────────────────────


def test_present_is_severity_none():
    sig = ec.compute_presence(TODAY, _fresh(), wearable_latest=_wearables_flowing())
    assert sig["severity"] == ec.SEVERITY_NONE


def test_quiet_is_soft():
    cd = _fresh()
    cd["macrofactor"] = ["2026-06-26"]  # eff gap 3 → quiet
    sig = ec.compute_presence(TODAY, cd, wearable_latest=_wearables_flowing())
    assert sig["presence_class"] == ec.QUIET
    assert sig["severity"] == ec.SEVERITY_SOFT


def test_dark_5_to_9_days_is_loud():
    cd = {
        "macrofactor": ["2026-06-23"],  # eff gap 6 → dark
        "hevy": ["2026-06-29"],
        "habitify": ["2026-06-29"],
        "notion": ["2026-06-28"],
        "withings": ["2026-06-29"],
    }
    sig = ec.compute_presence(TODAY, cd, wearable_latest=_wearables_flowing())
    assert sig["presence_class"] == ec.DARK
    assert sig["severity"] == ec.SEVERITY_LOUD


def test_dark_10_days_is_alarm():
    cd = {
        "macrofactor": ["2026-06-19"],  # eff gap 10
        "hevy": ["2026-06-29"],
        "habitify": ["2026-06-29"],
        "notion": ["2026-06-28"],
        "withings": ["2026-06-29"],
    }
    sig = ec.compute_presence(TODAY, cd, wearable_latest=_wearables_flowing())
    assert sig["severity"] == ec.SEVERITY_ALARM


def test_nothing_in_window_is_alarm():
    cd = {k: [] for k in ec.MANUAL_CHANNELS}
    sig = ec.compute_presence(TODAY, cd, wearable_latest=_wearables_flowing())
    assert sig["presence_class"] == ec.DARK
    assert sig["severity"] == ec.SEVERITY_ALARM


def test_three_channels_quiet_seven_days_is_alarm_even_at_shorter_food_gap():
    # Food only 6 days dark (loud on its own), but training/habits/journal have
    # all been out ≥7d — the multi-channel dropout escalates to alarm.
    cd = {
        "macrofactor": ["2026-06-23"],  # eff gap 6 → dark/loud alone
        "hevy": ["2026-06-20"],  # eff gap 9
        "habitify": ["2026-06-21"],  # eff gap 8
        "notion": ["2026-06-19"],  # eff gap 10
        "withings": ["2026-06-29"],
    }
    sig = ec.compute_presence(TODAY, cd, wearable_latest=_wearables_flowing())
    assert sig["severity"] == ec.SEVERITY_ALARM


def test_planned_pause_deescalates_to_none():
    cd = {
        "macrofactor": ["2026-06-23"],
        "hevy": [],
        "habitify": ["2026-06-23"],
        "notion": [],
        "withings": [],
    }
    travel = {"2026-06-24", "2026-06-25", "2026-06-26", "2026-06-27", "2026-06-28", "2026-06-29"}
    sig = ec.compute_presence(TODAY, cd, wearable_latest=_wearables_flowing(), travel_days=travel)
    assert sig["planned_pause"] is True
    assert sig["severity"] == ec.SEVERITY_NONE


def test_dropout_streak_days_per_channel():
    cd = _fresh()
    cd["hevy"] = ["2026-06-22"]  # eff gap 7
    sig = ec.compute_presence(TODAY, cd, wearable_latest=_wearables_flowing())
    assert sig["channel_detail"]["hevy"]["dropout_streak_days"] == 7


def test_severity_of_derives_for_pre_ladder_records():
    # Records written before #914 carry no severity field.
    assert ec.severity_of({"presence_class": "dark", "gap_days": 15}) == ec.SEVERITY_ALARM
    assert ec.severity_of({"presence_class": "dark", "gap_days": 6}) == ec.SEVERITY_LOUD
    assert ec.severity_of({"presence_class": "quiet", "gap_days": 3}) == ec.SEVERITY_SOFT
    assert ec.severity_of({"presence_class": "present", "gap_days": 0}) == ec.SEVERITY_NONE
    assert ec.severity_of({"presence_class": "dark", "gap_days": 15, "planned_pause": True}) == ec.SEVERITY_NONE
    assert ec.severity_of({}) == ec.SEVERITY_NONE
    # An explicit stored severity wins.
    assert ec.severity_of({"presence_class": "dark", "gap_days": 6, "severity": "alarm"}) == ec.SEVERITY_ALARM


# ── 3. the shared prompt block ───────────────────────────────────────────────


def _sig(**kw):
    base = {
        "presence_class": "dark",
        "gap_days": 15,
        "severity": "alarm",
        "last_food_log_date": "2026-06-15",
        "channels_quiet": ["food", "training", "habits", "journal"],
        "passive_still_flowing": True,
        "planned_pause": False,
        "planned_pause_reason": "",
        "returned": False,
    }
    base.update(kw)
    return base


def test_prompt_block_empty_when_present():
    assert ec.presence_prompt_block({"presence_class": "present", "returned": False}) == ""
    assert ec.presence_prompt_block({}) == ""
    assert ec.presence_prompt_block(None) == ""


def test_prompt_block_alarm_appends_opening_mandate():
    blk = ec.presence_prompt_block(_sig())
    assert "15 days" in blk and "2026-06-15" in blk
    assert "single most important fact" in blk
    assert "opening paragraph" in blk
    assert "Do not narrate a normal week" in blk
    # the alarm mandate replaces the don't-open-on-it placement rule
    assert "must NOT be your OPENING line" not in blk


def test_prompt_block_loud_keeps_placement_guard():
    blk = ec.presence_prompt_block(_sig(gap_days=6, severity="loud"))
    assert "~6 days" in blk
    assert "must NOT be your OPENING line" in blk
    assert "single most important fact" not in blk


def test_prompt_block_never_states_a_reason():
    blk = ec.presence_prompt_block(_sig())
    assert "invent" in blk.lower() and "invite the story" in blk.lower()


# ── 4. the acknowledgment gate ───────────────────────────────────────────────


def test_ack_required_only_at_loud_or_alarm():
    assert ec.presence_ack_required(_sig()) is True
    assert ec.presence_ack_required(_sig(severity="loud", gap_days=6)) is True
    assert ec.presence_ack_required(_sig(severity="soft", presence_class="quiet", gap_days=3)) is False
    assert ec.presence_ack_required(_sig(planned_pause=True)) is False
    assert ec.presence_ack_required(_sig(returned=True)) is False
    assert ec.presence_ack_required({}) is False


def test_ack_finding_fires_on_a_normal_week_narrative():
    text = "Recovery held steady this week and training volume looks sustainable. Keep the protein at target."
    finding = ec.presence_ack_finding(text, _sig())
    assert finding is not None
    assert finding["type"] == "presence_unacknowledged"
    assert finding["severity"] == "alarm"
    assert finding["gap_days"] == 15


def test_ack_finding_passes_on_gap_day_count():
    assert ec.presence_ack_finding("It has been 15 days since the last logged meal.", _sig()) is None
    assert ec.presence_ack_finding("A 15-day silence sits under all of this.", _sig()) is None


def test_ack_finding_passes_on_anchor_phrases():
    assert ec.presence_ack_finding("The logs went quiet in mid-June.", _sig()) is None
    assert ec.presence_ack_finding("He stopped logging and the platform noticed.", _sig()) is None
    assert ec.presence_ack_finding("The silence in the food log is the story.", _sig()) is None


def test_ack_finding_none_when_not_required():
    text = "A perfectly normal week."
    assert ec.presence_ack_finding(text, _sig(severity="soft", presence_class="quiet", gap_days=3)) is None


def test_enforce_regenerates_then_keeps_acknowledging_draft():
    calls = []

    def regen(note):
        calls.append(note)
        return "It has been 15 days since Matthew last logged a meal — that gap frames everything else."

    text, finding = ec.enforce_presence_acknowledgment("A normal week of steady progress.", _sig(), regen)
    assert finding is not None  # the gate fired on the original draft
    assert "15 days" in text
    assert len(calls) == 1
    assert "ACKNOWLEDGMENT REQUIRED" in calls[0]
    assert "opening paragraph" in calls[0]  # alarm escalation in the correction note


def test_enforce_holds_when_regen_still_unacknowledging():
    text, finding = ec.enforce_presence_acknowledgment(
        "A normal week.", _sig(), lambda note: "Still narrating a lovely ordinary week of training."
    )
    assert text is None  # regenerate-or-HOLD, the ADR-108 shape
    assert finding is not None


def test_enforce_holds_on_regen_exception():
    def regen(note):
        raise RuntimeError("bedrock down")

    text, finding = ec.enforce_presence_acknowledgment("A normal week.", _sig(), regen)
    assert text is None
    assert finding is not None


def test_enforce_noop_when_ack_not_required():
    text, finding = ec.enforce_presence_acknowledgment(
        "A normal week.", _sig(severity="soft", presence_class="quiet", gap_days=3), lambda note: "unused"
    )
    assert text == "A normal week."
    assert finding is None


# ── 5. expert snapshot recency (anti aggregate-dilution) ─────────────────────


def _analyzer():
    os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas", "intelligence"))
    import ai_expert_analyzer_lambda as az

    return az


def test_expert_recency_stats_kill_aggregate_dilution():
    az = _analyzer()

    # "9 sessions across 4 weeks" — but all of them ended 15 days ago.
    days = [f"2026-06-{d:02d}" for d in range(7, 16)]
    since, last_14 = az._recency_stats(days, "2026-06-30")
    assert since == 15
    assert last_14 == 0
    # fresh activity reads fresh
    since, last_14 = az._recency_stats(["2026-06-29", "2026-06-27", "2026-06-10"], "2026-06-30")
    assert since == 1
    assert last_14 == 2
    # empty → honest defaults
    assert az._recency_stats([], "2026-06-30") == (None, 0)
    assert az._recency_stats(None, "2026-06-30") == (None, 0)


# ── 6. #914-A: the experiment arc's deterministic per-week presence ──────────


def test_week_behavioral_presence_flags_a_fully_dark_week(monkeypatch):
    az = _analyzer()

    # every behavioral stream dead — habitify records exist but all zero-completion
    def _fake_query(source, start, end):
        assert start == "2026-06-22" and end == "2026-06-28"  # ISO week 2026-W26
        if source == "habitify":
            return [{"sk": f"DATE#2026-06-{22 + i}", "total_completed": 0} for i in range(7)]
        return []

    monkeypatch.setattr(az, "_query_source", _fake_query)
    pres = az._week_behavioral_presence("2026-W26")
    assert pres["absence_week"] is True
    assert pres["lift_days"] == 0 and pres["weigh_ins"] == 0
    assert pres["habit_completion_days"] == 0  # the zero-completion records don't count
    assert pres["food_log_days"] == 0


def test_week_behavioral_presence_counts_real_behavior(monkeypatch):
    az = _analyzer()

    def _fake_query(source, start, end):
        if source == "hevy":
            return [{"sk": "DATE#2026-06-23#WORKOUT#abc"}, {"sk": "DATE#2026-06-25#WORKOUT#def"}]
        if source == "withings":
            return [{"sk": "DATE#2026-06-24", "weight_lbs": 300}]
        if source == "habitify":
            return [{"sk": "DATE#2026-06-22", "total_completed": 3}, {"sk": "DATE#2026-06-23", "total_completed": 0}]
        if source == "macrofactor":
            return [{"sk": f"DATE#2026-06-{d}"} for d in (22, 23, 24, 25)]
        return []

    monkeypatch.setattr(az, "_query_source", _fake_query)
    pres = az._week_behavioral_presence("2026-W26")
    assert pres["absence_week"] is False
    assert pres["lift_days"] == 2
    assert pres["weigh_ins"] == 1
    assert pres["habit_completion_days"] == 1
    assert pres["food_log_days"] == 4


def test_week_behavioral_presence_bad_week_key():
    az = _analyzer()
    assert az._week_behavioral_presence(None) is None
    assert az._week_behavioral_presence("garbage") is None


# ── 7. #914-B: weight-rate honesty riders in the authoritative facts block ───


def test_facts_block_scale_dark_forces_past_tense_rate():
    import grounded_generation as gg

    facts = {
        "latest_weight": 296.2,
        "weekly_rate_lbs": -7.3,
        "last_weighin_date": "2026-06-26",
        "days_since_weighin": 14,
    }
    blk = gg.authoritative_facts_block(facts)
    assert "Last weigh-in: 2026-06-26 (14 days ago)" in blk
    assert "SCALE DARK" in blk
    assert "PAST-TENSE" in blk
    assert "through 2026-06-26" in blk
    assert "never 'maintained'" in blk


def test_facts_block_fresh_scale_has_no_dark_warning():
    import grounded_generation as gg

    facts = {"latest_weight": 296.2, "weekly_rate_lbs": -1.8, "last_weighin_date": "2026-06-29", "days_since_weighin": 1}
    blk = gg.authoritative_facts_block(facts)
    assert "Last weigh-in: 2026-06-29 (1 days ago)" in blk
    assert "SCALE DARK" not in blk


def test_facts_block_provisional_rate_is_labeled():
    import grounded_generation as gg

    blk = gg.authoritative_facts_block({"weekly_rate_lbs": -7.3, "rate_provisional": True})
    assert "PROVISIONAL" in blk
    blk2 = gg.authoritative_facts_block({"weekly_rate_lbs": -1.8, "rate_provisional": False})
    assert "PROVISIONAL" not in blk2


def test_facts_block_unchanged_without_recency_keys():
    import grounded_generation as gg

    blk = gg.authoritative_facts_block({"latest_weight": 296.2, "weekly_rate_lbs": -1.8})
    assert "Last weigh-in" not in blk and "SCALE DARK" not in blk and "PROVISIONAL" not in blk
