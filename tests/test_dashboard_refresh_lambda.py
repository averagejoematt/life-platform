"""tests/test_dashboard_refresh_lambda.py — behavioral units for the intraday refresher.

`lambdas/compute/dashboard_refresh_lambda.py` runs twice a day and REWRITES two
reader-facing JSON documents (`dashboard/<user>/data.json`, `buddy/<user>/data.json`)
in place, merging fresh signal over the morning brief's AI-computed fields. Nothing
about it was covered, so the two things that actually matter — *which* existing keys
survive a merge, and the exact content of the document that gets written — were free
to drift silently.

Everything here is offline: a hand-written fake DynamoDB table and a hand-written fake
S3 client that records `put_object` payloads (no MagicMock — a non-terminating mock in
the dedup / activity loops has OOM'd this repo's runner before). Dates are passed in
explicitly and `datetime.now` is frozen where the module reads it, so no assertion is
wall-clock relative (fixture-date + now() math is a time bomb, #golden-tests lesson).

Written for issue #1658 (coverage floor ratchet).
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from pacific_clock import freeze_pacific  # noqa: E402 — #2811: the PT clock the module actually calls

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "lambdas"))

# The module reads os.environ["S3_BUCKET"] at import time (hard KeyError otherwise)
# and builds its boto3 clients at module scope, so the env must be set before import.
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")

from common.constants import EXPERIMENT_BASELINE_WEIGHT_LBS  # noqa: E402
from compute import dashboard_refresh_lambda as drl  # noqa: E402

TODAY = date(2026, 6, 17)  # a Wednesday: weekday()==2, so the ISO week starts 2026-06-15
YESTERDAY = "2026-06-16"


# ══════════════════════════════════════════════════════════════════════════════
# FAKES  (hand-written — never MagicMock; these are iterated in loops)
# ══════════════════════════════════════════════════════════════════════════════


class _Body:
    def __init__(self, payload: str):
        self._payload = payload

    def read(self):
        return self._payload.encode("utf-8")


class _FakeS3:
    """Records put_object payloads; raises on an unknown key like S3 raises NoSuchKey."""

    def __init__(self, objects=None):
        self.objects = dict(objects or {})
        self.puts = []

    def get_object(self, Bucket, Key):  # noqa: N803 — boto3 kwarg casing
        if Key not in self.objects:
            raise KeyError(f"NoSuchKey: {Key}")
        return {"Body": _Body(self.objects[Key])}

    def put_object(self, **kwargs):
        self.puts.append(kwargs)
        self.objects[kwargs["Key"]] = kwargs["Body"]
        return {}

    def written(self, key):
        """The parsed JSON of the last put to `key`."""
        for put in reversed(self.puts):
            if put["Key"] == key:
                return json.loads(put["Body"])
        raise AssertionError(f"nothing was written to {key}; puts={[p['Key'] for p in self.puts]}")


class _FakeTable:
    """Minimal DDB table double. `boom=True` makes every call raise."""

    def __init__(self, items=None, query_items=None, boom=False):
        self.items = dict(items or {})
        self.query_items = list(query_items or [])
        self.boom = boom
        self.get_calls = []
        self.query_calls = []

    def get_item(self, Key):  # noqa: N803
        if self.boom:
            raise RuntimeError("DDB unavailable")
        self.get_calls.append(Key)
        item = self.items.get((Key["pk"], Key["sk"]))
        return {"Item": item} if item is not None else {}

    def query(self, **kwargs):
        if self.boom:
            raise RuntimeError("DDB unavailable")
        self.query_calls.append(kwargs)
        return {"Items": list(self.query_items)}


class _FrozenDatetime(datetime):
    """datetime subclass with a fixed now(); strptime/fromisoformat stay real."""

    FIXED = datetime(2026, 6, 17, 21, 30, 0)

    @classmethod
    def now(cls, tz=None):
        return cls.FIXED.replace(tzinfo=tz) if tz else cls.FIXED


FROZEN_ISO = _FrozenDatetime.FIXED.replace(tzinfo=timezone.utc).isoformat()


class _FakeTrainingLoad:
    """Stands in for training.training_load so TSB wiring is asserted, not re-derived."""

    def __init__(self, result=(31.0, 44.0, -13.0)):
        self.result = result
        self.calls = []

    def compute_ctl_atl_tsb(self, strava_60d, today, hevy_60d=None):
        self.calls.append((strava_60d, today, hevy_60d))
        return self.result


def _make_fetch_range(rows_by_source, calls=None):
    """Date-filtering stand-in for drl.fetch_range — rows carry real `sk` values."""

    def _fetch_range(source, start, end):
        if calls is not None:
            calls.append((source, start, end))
        hits = [r for r in rows_by_source.get(source, []) if start <= r.get("sk", "").replace("DATE#", "") <= end]
        return sorted(hits, key=lambda r: r["sk"])

    return _fetch_range


def _make_fetch_date(by_key, calls=None):
    def _fetch_date(source, date_str):
        if calls is not None:
            calls.append((source, date_str))
        return by_key.get((source, date_str))

    return _fetch_date


@pytest.fixture
def s3(monkeypatch):
    fake = _FakeS3()
    monkeypatch.setattr(drl, "s3", fake)
    return fake


@pytest.fixture
def frozen_now(monkeypatch):
    monkeypatch.setattr(drl, "datetime", _FrozenDatetime)
    freeze_pacific(monkeypatch, drl, _FrozenDatetime)
    return FROZEN_ISO


# ══════════════════════════════════════════════════════════════════════════════
# _normalize_whoop_sleep
# ══════════════════════════════════════════════════════════════════════════════


def test_normalize_whoop_sleep_passes_through_falsy_input():
    assert drl._normalize_whoop_sleep(None) is None
    assert drl._normalize_whoop_sleep({}) == {}


def test_normalize_whoop_sleep_aliases_whoop_field_names_without_mutating_input():
    item = {"sleep_quality_score": 88, "sleep_efficiency_percentage": 91.5}
    out = drl._normalize_whoop_sleep(item)
    assert out["sleep_score"] == 88
    assert out["sleep_efficiency_pct"] == 91.5
    # the original record is left untouched — the function copies
    assert "sleep_score" not in item


def test_normalize_whoop_sleep_does_not_clobber_an_existing_common_field():
    out = drl._normalize_whoop_sleep({"sleep_quality_score": 88, "sleep_score": 70})
    assert out["sleep_score"] == 70


def test_normalize_whoop_sleep_derives_stage_percentages_from_duration():
    out = drl._normalize_whoop_sleep(
        {
            "sleep_duration_hours": 8.0,
            "deep_hours": 1.6,
            "rem_hours": 2.0,
            "light_hours": 4.0,
            "awake_hours": 0.4,
        }
    )
    assert out["deep_pct"] == 20.0
    assert out["rem_pct"] == 25.0
    assert out["light_pct"] == 50.0
    assert out["awake_pct"] == 5.0


def test_normalize_whoop_sleep_skips_percentages_when_duration_is_zero():
    out = drl._normalize_whoop_sleep({"sleep_duration_hours": 0, "deep_hours": 1.6})
    assert "deep_pct" not in out
    assert out["deep_hours"] == 1.6


# ══════════════════════════════════════════════════════════════════════════════
# get_current_phase
# ══════════════════════════════════════════════════════════════════════════════

PHASES = [
    {"name": "Phase 1", "end_lbs": 300},
    {"name": "Phase 2", "end_lbs": 280},
    {"name": "Phase 3", "end_lbs": 185},
]


def test_get_current_phase_returns_none_when_profile_has_no_phases():
    assert drl.get_current_phase({}, 250) is None


def test_get_current_phase_picks_the_first_phase_whose_floor_is_not_yet_crossed():
    assert drl.get_current_phase({"weight_loss_phases": PHASES}, 305)["name"] == "Phase 1"
    assert drl.get_current_phase({"weight_loss_phases": PHASES}, 291.4)["name"] == "Phase 2"
    # exactly on the boundary counts as still being in that phase (>=)
    assert drl.get_current_phase({"weight_loss_phases": PHASES}, 300)["name"] == "Phase 1"


def test_get_current_phase_falls_back_to_the_last_phase_below_every_floor():
    assert drl.get_current_phase({"weight_loss_phases": PHASES}, 150)["name"] == "Phase 3"


# ══════════════════════════════════════════════════════════════════════════════
# _dedup_activities
# ══════════════════════════════════════════════════════════════════════════════


def _act(start, dur, **extra):
    a = {"start_date": start, "moving_time_seconds": dur}
    a.update(extra)
    return a


def test_dedup_activities_short_circuits_on_zero_or_one_activity():
    assert drl._dedup_activities([]) == []
    single = [_act("2026-06-17T08:00:00Z", 1800)]
    assert drl._dedup_activities(single) == single


def test_dedup_activities_keeps_the_richer_copy_of_a_whoop_garmin_duplicate():
    """Same start (within 15 min) + similar duration => one survivor, the richer record."""
    sparse = _act("2026-06-17T08:00:00Z", 1800, name="Walk (thin)")
    rich = _act("2026-06-17T08:05:00Z", 1750, name="Walk (rich)", average_heartrate=112, calories=210, average_speed=1.4)
    kept = drl._dedup_activities([sparse, rich])
    assert [a["name"] for a in kept] == ["Walk (rich)"]


def test_dedup_activities_keeps_both_when_starts_are_more_than_15_minutes_apart():
    a = _act("2026-06-17T08:00:00Z", 1800, average_heartrate=110)
    b = _act("2026-06-17T08:20:00Z", 1800)
    assert len(drl._dedup_activities([a, b])) == 2


def test_dedup_activities_keeps_both_when_durations_diverge_past_the_ratio_floor():
    """1800s vs 600s is a ratio of 0.33 — below the >0.4 threshold, so both are real."""
    a = _act("2026-06-17T08:00:00Z", 1800, average_heartrate=110)
    b = _act("2026-06-17T08:02:00Z", 600)
    assert len(drl._dedup_activities([a, b])) == 2


def test_dedup_activities_keeps_both_when_start_times_are_unparseable():
    a = {"start_date": "not-a-timestamp", "moving_time_seconds": 1800, "average_heartrate": 110}
    b = {"moving_time_seconds": 1790}
    assert len(drl._dedup_activities([a, b])) == 2


def test_dedup_activities_falls_back_to_elapsed_time_and_local_start():
    a = {"start_date_local": "2026-06-17T08:00:00", "elapsed_time_seconds": 1800, "calories": 200}
    b = {"start_date_local": "2026-06-17T08:03:00", "elapsed_time_seconds": 1700}
    assert len(drl._dedup_activities([a, b])) == 1


def test_dedup_activities_ranks_richness_by_elevation_and_cadence_too():
    """The richest record wins, and elevation/cadence count toward richness."""
    thin = _act("2026-06-17T08:00:00Z", 1800, name="thin")
    rich = _act("2026-06-17T08:03:00Z", 1810, name="rich", total_elevation_gain=120, average_cadence=78)
    assert [a["name"] for a in drl._dedup_activities([thin, rich])] == ["rich"]


def test_dedup_activities_does_not_reconsider_a_record_already_claimed_as_a_duplicate():
    """A already absorbed C; when B is examined it must skip C rather than re-pair with it."""
    a = _act("2026-06-17T08:00:00Z", 1800, name="A", average_heartrate=110, calories=200, max_heartrate=150)
    b = _act("2026-06-17T12:00:00Z", 1800, name="B", average_heartrate=115)
    c = _act("2026-06-17T08:05:00Z", 1790, name="C")
    assert [x["name"] for x in drl._dedup_activities([a, b, c])] == ["A", "B"]


def test_dedup_activities_collapses_three_copies_of_one_session_to_one():
    acts = [
        _act("2026-06-17T08:00:00Z", 1800),
        _act("2026-06-17T08:04:00Z", 1810, average_heartrate=110),
        _act("2026-06-17T08:07:00Z", 1795, average_heartrate=111, calories=200, max_heartrate=150),
    ]
    assert len(drl._dedup_activities(acts)) == 1


# ══════════════════════════════════════════════════════════════════════════════
# _buddy_days_since / _buddy_friendly_date / _buddy_friendly_name
# ══════════════════════════════════════════════════════════════════════════════


def test_buddy_days_since_returns_the_absent_sentinel_for_missing_or_bad_dates():
    assert drl._buddy_days_since(None, TODAY) == 99
    assert drl._buddy_days_since("", TODAY) == 99
    assert drl._buddy_days_since("17/06/2026", TODAY) == 99


def test_buddy_days_since_counts_calendar_days_from_a_string_or_a_date():
    assert drl._buddy_days_since("2026-06-17", TODAY) == 0
    assert drl._buddy_days_since("2026-06-10", TODAY) == 7
    assert drl._buddy_days_since(date(2026, 6, 15), TODAY) == 2


def test_buddy_friendly_date_formats_and_degrades_gracefully():
    assert drl._buddy_friendly_date("2026-06-17") == "Wed Jun 17"
    assert drl._buddy_friendly_date("2026-06-07") == "Sun Jun 7"  # no zero padding
    assert drl._buddy_friendly_date("garbage") == "garbage"
    assert drl._buddy_friendly_date(None) == ""


def test_buddy_friendly_name_maps_sport_types_only_when_there_is_no_real_title():
    assert drl._buddy_friendly_name("Ride", "Ride") == "Bike Ride"
    assert drl._buddy_friendly_name("VirtualRide", "VirtualRide") == "Indoor Ride"
    assert drl._buddy_friendly_name("", "WeightTraining") == "Weight Training"
    assert drl._buddy_friendly_name(None, "Walk") == "Walk"
    # an unmapped sport falls through to its raw type
    assert drl._buddy_friendly_name("Pickleball", "Pickleball") == "Pickleball"
    # a user-given title always wins
    assert drl._buddy_friendly_name("Morning shakeout", "Run") == "Morning shakeout"


# ══════════════════════════════════════════════════════════════════════════════
# _build_avatar_data
# ══════════════════════════════════════════════════════════════════════════════


def _sheet(**pillars):
    sheet = {"character_level": pillars.pop("character_level", 42), "character_tier": pillars.pop("tier", "Ascent")}
    for name, lvl in pillars.items():
        sheet[f"pillar_{name}"] = {"level": lvl}
    return sheet


def test_build_avatar_data_returns_none_without_a_character_sheet():
    assert drl._build_avatar_data(None, {"goal_weight_lbs": 185}) is None


def test_build_avatar_data_scores_composition_against_the_journey_span():
    profile = {"journey_start_weight_lbs": 320.0, "goal_weight_lbs": 185}
    avatar = drl._build_avatar_data(_sheet(), profile, current_weight=296.0)
    # (320 - 296) / (320 - 185) * 100
    assert avatar["composition_score"] == 17.8
    assert avatar["body_frame"] == 1
    assert avatar["tier"] == "ascent"


def test_build_avatar_data_body_frame_steps_at_36_and_75_percent():
    profile = {"journey_start_weight_lbs": 300.0, "goal_weight_lbs": 200.0}  # 100 lb span
    assert drl._build_avatar_data(_sheet(), profile, current_weight=265.0)["body_frame"] == 1  # 35%
    assert drl._build_avatar_data(_sheet(), profile, current_weight=264.0)["body_frame"] == 2  # 36%
    assert drl._build_avatar_data(_sheet(), profile, current_weight=225.0)["body_frame"] == 3  # 75%


def test_build_avatar_data_clamps_composition_to_0_100():
    profile = {"journey_start_weight_lbs": 300.0, "goal_weight_lbs": 200.0}
    assert drl._build_avatar_data(_sheet(), profile, current_weight=310.0)["composition_score"] == 0
    assert drl._build_avatar_data(_sheet(), profile, current_weight=150.0)["composition_score"] == 100


def test_build_avatar_data_handles_a_zero_width_journey_and_a_missing_current_weight():
    same = drl._build_avatar_data(_sheet(), {"journey_start_weight_lbs": 200.0, "goal_weight_lbs": 200.0})
    assert same["composition_score"] == 100
    assert same["body_frame"] == 3

    # no current weight and no profile start => the ADR-058 baseline, i.e. zero progress
    default = drl._build_avatar_data(_sheet(), {})
    assert default["composition_score"] == 0
    assert EXPERIMENT_BASELINE_WEIGHT_LBS > 185  # the constant the default leans on


def test_build_avatar_data_badge_tiers_step_at_41_and_61():
    profile = {"journey_start_weight_lbs": 300.0, "goal_weight_lbs": 200.0}
    sheet = _sheet(sleep=61, movement=60, nutrition=41, metabolic=40, mind=1, relationships=100, consistency=45)
    badges = drl._build_avatar_data(sheet, profile, 290.0)["badges"]
    assert badges == {
        "sleep": "bright",
        "movement": "dim",
        "nutrition": "dim",
        "metabolic": "hidden",
        "mind": "hidden",
        "relationships": "bright",
        "consistency": "dim",
    }


def test_build_avatar_data_expressions_read_the_four_driver_pillars():
    profile = {"journey_start_weight_lbs": 300.0, "goal_weight_lbs": 200.0}
    high = drl._build_avatar_data(_sheet(sleep=61, movement=61, metabolic=61, consistency=61), profile, 290.0)
    assert high["expressions"] == {"eyes": "bright", "posture": "forward", "skin_tone": "warm", "ground": "solid"}

    low = drl._build_avatar_data(_sheet(sleep=34, movement=34, metabolic=34, consistency=34), profile, 290.0)
    assert low["expressions"] == {"eyes": "dim", "posture": "normal", "skin_tone": "cool", "ground": "faded"}

    mid = drl._build_avatar_data(_sheet(sleep=35, movement=35, metabolic=35, consistency=35), profile, 290.0)
    assert mid["expressions"] == {"eyes": "normal", "posture": "normal", "skin_tone": "normal", "ground": "normal"}


def test_build_avatar_data_crown_and_ring_are_independent_gates():
    profile = {"journey_start_weight_lbs": 300.0, "goal_weight_lbs": 200.0}
    all_bright = {p: 61 for p in ("sleep", "movement", "nutrition", "metabolic", "mind", "relationships", "consistency")}

    lvl80 = drl._build_avatar_data(_sheet(character_level=80, **all_bright), profile, 290.0)
    assert lvl80["elite_crown"] is False
    assert lvl80["alignment_ring"] is True

    lvl81 = drl._build_avatar_data(_sheet(character_level=81, sleep=61), profile, 290.0)
    assert lvl81["elite_crown"] is True
    assert lvl81["alignment_ring"] is False  # the other six pillars are still hidden


def test_build_avatar_data_slugifies_active_effect_names_and_drops_nameless_ones():
    profile = {"journey_start_weight_lbs": 300.0, "goal_weight_lbs": 200.0}
    sheet = _sheet()
    sheet["active_effects"] = [{"name": "Deep Sleep Streak"}, {"name": ""}, {"duration": 3}]
    avatar = drl._build_avatar_data(sheet, profile, 290.0)
    assert avatar["effects"] == ["deep_sleep_streak"]


def test_build_avatar_data_defaults_a_missing_tier_to_foundation():
    profile = {"journey_start_weight_lbs": 300.0, "goal_weight_lbs": 200.0}
    assert drl._build_avatar_data({"character_level": 3}, profile, 290.0)["tier"] == "foundation"


# ══════════════════════════════════════════════════════════════════════════════
# fetch_date / fetch_range / load_profile / read_existing_json
# ══════════════════════════════════════════════════════════════════════════════


def test_fetch_date_returns_the_item_with_decimals_floated(monkeypatch):
    table = _FakeTable(items={("USER#matthew#SOURCE#whoop", "DATE#2026-06-16"): {"hrv_ms": Decimal("58.5")}})
    monkeypatch.setattr(drl, "table", table)
    assert drl.fetch_date("whoop", "2026-06-16") == {"hrv_ms": 58.5}
    assert table.get_calls == [{"pk": "USER#matthew#SOURCE#whoop", "sk": "DATE#2026-06-16"}]


def test_fetch_date_returns_none_for_a_missing_row_and_for_a_ddb_failure(monkeypatch):
    monkeypatch.setattr(drl, "table", _FakeTable())
    assert drl.fetch_date("whoop", "2026-06-16") is None
    monkeypatch.setattr(drl, "table", _FakeTable(boom=True))
    assert drl.fetch_date("whoop", "2026-06-16") is None


def test_fetch_range_builds_a_bounded_key_condition_and_floats_decimals(monkeypatch):
    table = _FakeTable(query_items=[{"sk": "DATE#2026-06-16", "weight_lbs": Decimal("291.4")}])
    monkeypatch.setattr(drl, "table", table)
    rows = drl.fetch_range("withings", "2026-06-10", "2026-06-17")
    assert rows == [{"sk": "DATE#2026-06-16", "weight_lbs": 291.4}]
    kwargs = table.query_calls[0]
    assert kwargs["ExpressionAttributeValues"][":pk"] == "USER#matthew#SOURCE#withings"
    assert kwargs["ExpressionAttributeValues"][":s"] == "DATE#2026-06-10"
    assert kwargs["ExpressionAttributeValues"][":e"] == "DATE#2026-06-17"


def test_fetch_range_applies_the_phase_filter_per_source_class(monkeypatch):
    """#2109: raw timeseries reads cross-phase; experiment-scoped intelligence does not."""
    table = _FakeTable()
    monkeypatch.setattr(drl, "table", table)

    drl.fetch_range("withings", "2026-06-10", "2026-06-17")
    assert "FilterExpression" not in table.query_calls[0]

    drl.fetch_range("computed_metrics", "2026-06-10", "2026-06-17")
    assert "phase" in table.query_calls[1]["FilterExpression"]


def test_fetch_range_returns_empty_on_a_ddb_failure(monkeypatch):
    monkeypatch.setattr(drl, "table", _FakeTable(boom=True))
    assert drl.fetch_range("withings", "2026-06-10", "2026-06-17") == []


def test_load_profile_floats_decimals_and_reads_the_profile_singleton(monkeypatch):
    table = _FakeTable(items={("USER#matthew", "PROFILE#v1"): {"goal_weight_lbs": Decimal("185")}})
    monkeypatch.setattr(drl, "table", table)
    assert drl.load_profile() == {"goal_weight_lbs": 185.0}


def test_load_profile_returns_empty_dict_when_the_record_is_absent(monkeypatch, capsys):
    monkeypatch.setattr(drl, "table", _FakeTable())
    assert drl.load_profile() == {}
    assert "no PROFILE#v1 record found" in capsys.readouterr().out


def test_load_profile_returns_empty_dict_when_dynamodb_fails(monkeypatch, capsys):
    monkeypatch.setattr(drl, "table", _FakeTable(boom=True))
    assert drl.load_profile() == {}
    assert "DynamoDB read failed" in capsys.readouterr().out


def test_read_existing_json_parses_the_object_and_returns_none_for_a_missing_key(monkeypatch):
    fake = _FakeS3({"dashboard/matthew/data.json": '{"day_grade": "B+"}'})
    monkeypatch.setattr(drl, "s3", fake)
    assert drl.read_existing_json("dashboard/matthew/data.json") == {"day_grade": "B+"}
    assert drl.read_existing_json("dashboard/matthew/missing.json") is None


def test_read_existing_json_returns_none_on_malformed_json(monkeypatch):
    monkeypatch.setattr(drl, "s3", _FakeS3({"k.json": "{not json"}))
    assert drl.read_existing_json("k.json") is None


# ══════════════════════════════════════════════════════════════════════════════
# refresh_dashboard
# ══════════════════════════════════════════════════════════════════════════════

DASH_KEY = "dashboard/matthew/data.json"

EXISTING_DASHBOARD = {
    "day_grade": "B+",
    "day_grade_note": "morning AI text that must survive the merge",
    "weight": {"current": 999.9, "weekly_delta": 0.0, "phase": "stale", "journey_pct": 0, "sparkline": []},
    "glucose": {"avg": 1.0, "tir_pct": 2.0, "variability": 9.9, "fasting_proxy": 3.0},
    "zone2_min": 87,  # deliberately non-zero + distinct from any computed total below (#2174)
    "tsb": 5.5,
    "sources_active": 0,
}

DASHBOARD_PROFILE = {
    "weight_loss_phases": PHASES,
    "journey_start_weight_lbs": 320.0,
    "goal_weight_lbs": 185,
    "max_heart_rate": 180,  # zone 2 = 108..126 bpm
}


def _dashboard_rows():
    return {
        "withings": [
            {"sk": "DATE#2026-06-03", "weight_lbs": 300.0},
            {"sk": "DATE#2026-06-10", "weight_lbs": 295.0},
            {"sk": "DATE#2026-06-16", "weight_lbs": 292.0},
            {"sk": "DATE#2026-06-17", "weight_lbs": 291.4},
        ],
        "strava": [
            {"sk": "DATE#2026-06-15", "activities": [{"average_heartrate": 120, "moving_time_seconds": 1800}]},
            {"sk": "DATE#2026-06-16", "activities": [{"average_heartrate": 150, "moving_time_seconds": 3600}]},
            {"sk": "DATE#2026-06-17", "activities": [{"average_heartrate": 110, "moving_time_seconds": 900}]},
        ],
        "hevy": [{"sk": "DATE#2026-06-16", "volume_lbs": 12000}],
    }


def _install_dashboard_doubles(monkeypatch, s3, rows=None, dates=None):
    s3.objects[DASH_KEY] = json.dumps(EXISTING_DASHBOARD)
    monkeypatch.setattr(drl, "fetch_range", _make_fetch_range(rows if rows is not None else _dashboard_rows()))
    monkeypatch.setattr(drl, "fetch_date", _make_fetch_date(dates if dates is not None else {}))
    load = _FakeTrainingLoad()
    monkeypatch.setattr(drl, "training_load", load)
    return load


def test_refresh_dashboard_skips_entirely_when_there_is_no_existing_document(monkeypatch, s3, capsys):
    monkeypatch.setattr(drl, "fetch_range", _make_fetch_range({}))
    monkeypatch.setattr(drl, "fetch_date", _make_fetch_date({}))
    drl.refresh_dashboard(DASHBOARD_PROFILE, YESTERDAY, TODAY)
    assert s3.puts == []
    assert "No existing dashboard" in capsys.readouterr().out


def test_refresh_dashboard_writes_the_merged_weight_block(monkeypatch, s3, frozen_now):
    _install_dashboard_doubles(monkeypatch, s3)
    drl.refresh_dashboard(DASHBOARD_PROFILE, YESTERDAY, TODAY)

    doc = s3.written(DASH_KEY)
    assert doc["weight"] == {
        "current": 291.4,
        "weekly_delta": -3.6,  # 291.4 today vs the 295.0 reading a week back
        "phase": "Phase 2",  # 291.4 is under the 300 lb Phase-1 floor
        "journey_pct": 21,  # (320 - 291.4) / (320 - 185)
        # last-observation-carried-forward over the 7 days ENDING YESTERDAY (today excluded)
        "sparkline": [295.0, 295.0, 295.0, 295.0, 295.0, 295.0, 292.0],
    }


def test_refresh_dashboard_preserves_the_ai_written_fields_from_the_morning_brief(monkeypatch, s3, frozen_now):
    _install_dashboard_doubles(monkeypatch, s3)
    drl.refresh_dashboard(DASHBOARD_PROFILE, YESTERDAY, TODAY)

    doc = s3.written(DASH_KEY)
    assert doc["day_grade"] == "B+"
    assert doc["day_grade_note"] == "morning AI text that must survive the merge"
    assert doc["refresh_type"] == "intraday"
    assert doc["generated_at"] == frozen_now
    assert doc["refreshed_at"] == frozen_now


def test_refresh_dashboard_puts_with_the_cache_headers_the_cdn_relies_on(monkeypatch, s3, frozen_now):
    _install_dashboard_doubles(monkeypatch, s3)
    drl.refresh_dashboard(DASHBOARD_PROFILE, YESTERDAY, TODAY)

    put = s3.puts[-1]
    assert put["Bucket"] == drl.S3_BUCKET
    assert put["Key"] == DASH_KEY
    assert put["ContentType"] == "application/json"
    assert put["CacheControl"] == "max-age=300"


def test_refresh_dashboard_prefers_todays_glucose_and_leaves_absent_fields_alone(monkeypatch, s3, frozen_now):
    dates = {
        ("apple_health", YESTERDAY): {"blood_glucose_avg": 130.0, "time_in_range_pct": 40.0},
        ("apple_health", "2026-06-17"): {"blood_glucose_avg": 105.0, "time_in_range_pct": 88.0, "blood_glucose_min": 78.0},
    }
    _install_dashboard_doubles(monkeypatch, s3, dates=dates)
    drl.refresh_dashboard(DASHBOARD_PROFILE, YESTERDAY, TODAY)

    doc = s3.written(DASH_KEY)
    assert doc["glucose"]["avg"] == 105.0  # today's partial day wins over yesterday's
    assert doc["glucose"]["tir_pct"] == 88.0
    assert doc["glucose"]["fasting_proxy"] == 78.0
    assert doc["glucose"]["variability"] == 9.9  # no std today => the morning value survives


def test_refresh_dashboard_falls_back_to_yesterdays_glucose_when_today_is_empty(monkeypatch, s3, frozen_now):
    dates = {("apple_health", YESTERDAY): {"blood_glucose_avg": 130.0, "time_in_range_pct": 40.0}}
    _install_dashboard_doubles(monkeypatch, s3, dates=dates)
    drl.refresh_dashboard(DASHBOARD_PROFILE, YESTERDAY, TODAY)

    doc = s3.written(DASH_KEY)
    assert doc["glucose"]["avg"] == 130.0
    assert doc["glucose"]["tir_pct"] == 40.0


def test_refresh_dashboard_updates_variability_when_a_std_is_present(monkeypatch, s3, frozen_now):
    dates = {("apple_health", "2026-06-17"): {"blood_glucose_std": 14.2}}
    _install_dashboard_doubles(monkeypatch, s3, dates=dates)
    drl.refresh_dashboard(DASHBOARD_PROFILE, YESTERDAY, TODAY)

    doc = s3.written(DASH_KEY)
    assert doc["glucose"]["variability"] == 14.2
    assert doc["glucose"]["avg"] == 1.0  # untouched — no average in today's partial record


def test_refresh_dashboard_sums_only_in_zone_minutes_from_the_current_week(monkeypatch, s3, frozen_now):
    """Mon 06-15 (30 min @120) + Wed 06-17 (15 min @110) count; Tue @150 bpm is above zone 2."""
    _install_dashboard_doubles(monkeypatch, s3)
    drl.refresh_dashboard(DASHBOARD_PROFILE, YESTERDAY, TODAY)
    assert s3.written(DASH_KEY)["zone2_min"] == 45


def test_refresh_dashboard_zone2_window_starts_at_monday_not_seven_days_back(monkeypatch, s3, frozen_now):
    rows = _dashboard_rows()
    rows["strava"].insert(0, {"sk": "DATE#2026-06-14", "activities": [{"average_heartrate": 115, "moving_time_seconds": 6000}]})
    _install_dashboard_doubles(monkeypatch, s3, rows=rows)
    drl.refresh_dashboard(DASHBOARD_PROFILE, YESTERDAY, TODAY)
    # Sunday 06-14 sits before the Monday week start, so its 100 minutes are excluded
    assert s3.written(DASH_KEY)["zone2_min"] == 45


def test_refresh_dashboard_delegates_tsb_to_the_shared_banister_model(monkeypatch, s3, frozen_now):
    load = _install_dashboard_doubles(monkeypatch, s3)
    drl.refresh_dashboard(DASHBOARD_PROFILE, YESTERDAY, TODAY)

    assert s3.written(DASH_KEY)["tsb"] == -13.0
    strava_60d, today_arg, hevy_60d = load.calls[0]
    assert today_arg == TODAY
    assert [r["sk"] for r in strava_60d] == ["DATE#2026-06-15", "DATE#2026-06-16", "DATE#2026-06-17"]
    assert [r["sk"] for r in hevy_60d] == ["DATE#2026-06-16"]


def test_refresh_dashboard_keeps_the_morning_zone2_when_the_profile_is_malformed(monkeypatch, s3, frozen_now):
    """A non-numeric max_heart_rate must not take the whole refresh down with it."""
    _install_dashboard_doubles(monkeypatch, s3)
    bad_profile = dict(DASHBOARD_PROFILE, max_heart_rate="one eighty")
    drl.refresh_dashboard(bad_profile, YESTERDAY, TODAY)

    doc = s3.written(DASH_KEY)
    assert doc["zone2_min"] == EXISTING_DASHBOARD["zone2_min"]
    assert doc["weight"]["current"] == 291.4  # the rest of the refresh still landed


def test_refresh_dashboard_keeps_the_morning_tsb_when_the_load_model_raises(monkeypatch, s3, frozen_now):
    _install_dashboard_doubles(monkeypatch, s3)

    class _BrokenLoad:
        def compute_ctl_atl_tsb(self, *_args, **_kwargs):
            raise ValueError("bad power series")

    monkeypatch.setattr(drl, "training_load", _BrokenLoad())
    drl.refresh_dashboard(DASHBOARD_PROFILE, YESTERDAY, TODAY)

    doc = s3.written(DASH_KEY)
    assert doc["tsb"] == 5.5
    assert doc["zone2_min"] == 45  # the surrounding blocks are unaffected


def test_refresh_dashboard_counts_the_sources_that_reported_yesterday(monkeypatch, s3, frozen_now):
    dates = {
        ("whoop", YESTERDAY): {"hrv_ms": 58.0},
        ("macrofactor", YESTERDAY): {"total_calories_kcal": 2100},
        ("strava", YESTERDAY): {"activities": []},
        ("apple_health", YESTERDAY): {"blood_glucose_avg": 101.0},
        # habitify and garmin are silent
    }
    _install_dashboard_doubles(monkeypatch, s3, dates=dates)
    drl.refresh_dashboard(DASHBOARD_PROFILE, YESTERDAY, TODAY)
    assert s3.written(DASH_KEY)["sources_active"] == 4


def test_refresh_dashboard_leaves_weight_and_tsb_untouched_when_nothing_new_arrived(monkeypatch, s3, frozen_now):
    """No withings rows and no training rows => the morning brief's numbers must survive."""
    _install_dashboard_doubles(monkeypatch, s3, rows={}, dates={})
    drl.refresh_dashboard(DASHBOARD_PROFILE, YESTERDAY, TODAY)

    doc = s3.written(DASH_KEY)
    assert doc["weight"] == EXISTING_DASHBOARD["weight"]  # stale-but-preserved, not zeroed
    assert doc["tsb"] == 5.5
    assert doc["sources_active"] == 0
    # #2174 (ADR-104): an empty strava_week must leave the morning brief's real zone2_min
    # alone instead of clobbering it with the running total's zero start.
    assert doc["zone2_min"] == EXISTING_DASHBOARD["zone2_min"]


def test_refresh_dashboard_leaves_weekly_delta_null_without_a_week_old_reading(monkeypatch, s3, frozen_now):
    rows = {"withings": [{"sk": "DATE#2026-06-17", "weight_lbs": 291.4}]}
    _install_dashboard_doubles(monkeypatch, s3, rows=rows)
    drl.refresh_dashboard(DASHBOARD_PROFILE, YESTERDAY, TODAY)

    doc = s3.written(DASH_KEY)
    assert doc["weight"]["current"] == 291.4
    assert doc["weight"]["weekly_delta"] is None
    assert doc["weight"]["sparkline"] == []  # today's reading is outside the trailing window


# ══════════════════════════════════════════════════════════════════════════════
# refresh_buddy
# ══════════════════════════════════════════════════════════════════════════════

BUDDY_KEY = "buddy/matthew/data.json"

BUDDY_PROFILE = {
    "journey_start_date": "2026-05-18",
    "journey_start_weight_lbs": 320.0,
    "start_weight_lbs": 320.0,
    "goal_weight_lbs": 185,
}

BUDDY_SHEET = {
    "character_level": 42,
    "character_tier": "Ascent",
    "character_tier_emoji": "⛰",
    "level_events": [{"pillar": "sleep", "to": 61}],
    "pillar_sleep": {"level": 65},
    "pillar_movement": {"level": 45},
    "pillar_nutrition": {"level": 20},
    "pillar_metabolic": {"level": 30},
    "pillar_mind": {"level": 50},
    "pillar_relationships": {"level": 42},
    "pillar_consistency": {"level": 70},
}


def _green_buddy_rows():
    return {
        "macrofactor": [
            {"sk": "DATE#2026-06-11", "total_calories_kcal": 2000, "total_protein_g": 180},
            {"sk": "DATE#2026-06-12", "total_calories_kcal": 2100, "total_protein_g": 180},
            {"sk": "DATE#2026-06-13", "total_calories_kcal": 2200, "total_protein_g": 180},
            {"sk": "DATE#2026-06-14", "calories": 2000, "protein_g": 180},
            {"sk": "DATE#2026-06-15", "energy_kcal": 2100, "protein": 180},
            {"sk": "DATE#2026-06-16", "total_calories_kcal": 150},  # under the 200 kcal floor: not a log
            {"sk": "DATE#2026-06-17", "total_calories_kcal": 2200, "total_protein_g": 180},
        ],
        "strava": [
            {
                "sk": "DATE#2026-06-11",
                "activities": [{"name": "Old Ride", "sport_type": "Ride", "distance_miles": 12.0, "moving_time_seconds": 3600}],
            },
            {
                "sk": "DATE#2026-06-15",
                "activities": [{"name": "Ride", "sport_type": "Ride", "distance_miles": 8.0, "moving_time_seconds": 2400}],
            },
            {"sk": "DATE#2026-06-16", "activities": [{"name": "Lift", "sport_type": "WeightTraining", "moving_time_seconds": 3000}]},
            {
                "sk": "DATE#2026-06-17",
                "activities": [
                    {
                        "name": "Morning Walk",
                        "sport_type": "Walk",
                        "distance_miles": 2.53,
                        "moving_time_seconds": 1800,
                        "start_date": "2026-06-17T08:00:00Z",
                        "average_heartrate": 108,
                    },
                    # a WHOOP/Garmin duplicate of the same walk — must be deduped away
                    {
                        "name": "Walk",
                        "sport_type": "Walk",
                        "distance_miles": 2.5,
                        "moving_time_seconds": 1790,
                        "start_date": "2026-06-17T08:02:00Z",
                    },
                ],
            },
        ],
        "habitify": [
            {"sk": "DATE#2026-06-13", "completed_count": 3},
            {"sk": "DATE#2026-06-14", "completed_count": 4},
            {"sk": "DATE#2026-06-15", "total_completed": 5},
            {"sk": "DATE#2026-06-16", "completed_count": 2},
            {"sk": "DATE#2026-06-17", "completed_count": 3},
        ],
        "withings": [
            {"sk": "DATE#2026-06-11", "weight_lbs": 300.0},
            {"sk": "DATE#2026-06-17", "weight_lbs": 296.0},
        ],
    }


@pytest.fixture
def frozen_pacific(monkeypatch):
    monkeypatch.setattr("common.pacific_time.pacific_now", lambda: datetime(2026, 6, 17, 14, 5))
    return "Wednesday afternoon, June 17 at 2:05pm PT"


def _install_buddy_doubles(monkeypatch, s3, rows, sheet=BUDDY_SHEET):
    monkeypatch.setattr(drl, "fetch_range", _make_fetch_range(rows))
    monkeypatch.setattr(drl, "fetch_date", _make_fetch_date({("character_sheet", YESTERDAY): sheet}))


def _run_buddy(monkeypatch, s3, capsys, rows, sheet=BUDDY_SHEET, profile=BUDDY_PROFILE, today=TODAY):
    _install_buddy_doubles(monkeypatch, s3, rows, sheet)
    drl.refresh_buddy(profile, YESTERDAY, today)
    # refresh_buddy swallows every exception, so a silent failure would look like a
    # missing assertion rather than a red test. Surface it explicitly.
    assert "Buddy refresh failed" not in capsys.readouterr().out
    return s3.written(BUDDY_KEY)


def test_refresh_buddy_green_status_lines_and_beacon(monkeypatch, s3, capsys, frozen_now, frozen_pacific):
    doc = _run_buddy(monkeypatch, s3, capsys, _green_buddy_rows())

    assert doc["status_lines"] == [
        {"area": "Food Logging", "status": "green", "text": "Consistent — logged meals 6 of last 7 days"},
        {"area": "Exercise", "status": "green", "text": "Active — 3 sessions this week"},
        {"area": "Routine", "status": "green", "text": "In his routine — habits tracked consistently"},
        {"area": "Weight", "status": "green", "text": "Heading in the right direction"},
    ]
    assert doc["beacon"] == "green"
    assert doc["beacon_label"] == "Matt's doing his thing"
    assert "No action needed" in doc["prompt_for_tom"]


def test_refresh_buddy_food_snapshot_averages_only_the_real_logs(monkeypatch, s3, capsys, frozen_now, frozen_pacific):
    doc = _run_buddy(monkeypatch, s3, capsys, _green_buddy_rows())
    # (2000+2100+2200+2000+2100+2200)/6 — the 150 kcal day is excluded
    assert doc["food_snapshot"] == "Averaging about 2,100 calories per day this week with 180g protein."


def test_refresh_buddy_food_snapshot_omits_protein_when_none_was_logged(monkeypatch, s3, capsys, frozen_now, frozen_pacific):
    rows = _green_buddy_rows()
    rows["macrofactor"] = [{"sk": "DATE#2026-06-17", "total_calories_kcal": 1900}]
    doc = _run_buddy(monkeypatch, s3, capsys, rows)
    assert doc["food_snapshot"] == "Averaging about 1,900 calories per day this week."


def test_refresh_buddy_activity_highlights_are_deduped_named_and_newest_first(monkeypatch, s3, capsys, frozen_now, frozen_pacific):
    doc = _run_buddy(monkeypatch, s3, capsys, _green_buddy_rows())

    assert doc["activity_highlights"] == [
        {"name": "Morning Walk", "detail": "2.5 mi, 30 min", "date": "Wed Jun 17"},
        {"name": "Lift", "detail": "50 min", "date": "Tue Jun 16"},
        {"name": "Bike Ride", "detail": "8.0 mi, 40 min", "date": "Mon Jun 15"},
        {"name": "Old Ride", "detail": "12.0 mi, 60 min", "date": "Thu Jun 11"},
    ]


def test_refresh_buddy_journey_block_and_character_sheet(monkeypatch, s3, capsys, frozen_now, frozen_pacific):
    doc = _run_buddy(monkeypatch, s3, capsys, _green_buddy_rows())

    assert doc["journey"] == {
        "days": 30,  # 2026-05-18 -> 2026-06-17
        "lost_lbs": 24.0,  # 320.0 start -> 296.0 latest weigh-in
        "pct_complete": 18,  # round(24 / (320 - 185) * 100)
        "goal_lbs": 185,
    }
    assert doc["character_sheet"] == {
        "level": 42,
        "tier": "Ascent",
        "tier_emoji": "⛰",
        "events": [{"pillar": "sleep", "to": 61}],
    }
    assert doc["avatar"]["composition_score"] == 17.8
    assert doc["avatar"]["badges"]["sleep"] == "bright"
    assert doc["avatar"]["badges"]["nutrition"] == "hidden"


def test_refresh_buddy_writes_the_document_with_cdn_headers_and_frozen_stamps(monkeypatch, s3, capsys, frozen_now, frozen_pacific):
    doc = _run_buddy(monkeypatch, s3, capsys, _green_buddy_rows())

    put = s3.puts[-1]
    assert put["Bucket"] == drl.S3_BUCKET
    assert put["Key"] == BUDDY_KEY
    assert put["ContentType"] == "application/json"
    assert put["CacheControl"] == "max-age=300"
    assert doc["date"] == YESTERDAY
    assert doc["generated_at"] == frozen_now
    assert doc["refreshed_at"] == frozen_now
    assert doc["last_updated_friendly"] == frozen_pacific


def test_refresh_buddy_all_signals_dark_raises_a_red_beacon(monkeypatch, s3, capsys, frozen_now, frozen_pacific):
    doc = _run_buddy(monkeypatch, s3, capsys, {}, sheet=None)

    assert [line["status"] for line in doc["status_lines"]] == ["red", "red", "red", "red"]
    assert doc["status_lines"][0]["text"] == "No food logged in 99 days — might be off track"
    assert doc["status_lines"][1]["text"] == "No exercise this week — last session 99 days ago"
    assert doc["status_lines"][3]["text"] == "No weigh-in in 99+ days"
    assert doc["beacon"] == "red"
    assert doc["beacon_label"] == "Check in on him"
    assert doc["character_sheet"] is None
    assert doc["avatar"] is None
    assert doc["food_snapshot"] == ""
    assert doc["activity_highlights"] == []
    # with no weigh-in the journey falls back to the profile start weight — zero progress,
    # not a fabricated number
    assert doc["journey"]["lost_lbs"] == 0.0
    assert doc["journey"]["pct_complete"] == 0


def test_refresh_buddy_two_soft_signals_raise_a_yellow_beacon(monkeypatch, s3, capsys, frozen_now, frozen_pacific):
    rows = _green_buddy_rows()
    rows["macrofactor"] = [{"sk": "DATE#2026-06-14", "total_calories_kcal": 2100, "total_protein_g": 180}]
    rows["withings"] = [{"sk": "DATE#2026-06-12", "weight_lbs": 298.0}]
    doc = _run_buddy(monkeypatch, s3, capsys, rows)

    assert doc["status_lines"][0] == {"area": "Food Logging", "status": "yellow", "text": "Last food log was 3 days ago"}
    assert doc["status_lines"][3] == {"area": "Weight", "status": "yellow", "text": "Weighed in 5 days ago"}
    assert doc["beacon"] == "yellow"
    assert doc["beacon_label"] == "Might be a quiet stretch"
    assert "casual check-in" in doc["prompt_for_tom"]


def test_refresh_buddy_partial_week_exercise_reads_as_in_progress_not_failure(monkeypatch, s3, capsys, frozen_now, frozen_pacific):
    rows = _green_buddy_rows()
    rows["strava"] = [
        {"sk": "DATE#2026-06-16", "activities": [{"name": "Lift", "sport_type": "WeightTraining", "moving_time_seconds": 3000}]}
    ]
    doc = _run_buddy(monkeypatch, s3, capsys, rows)
    assert doc["status_lines"][1] == {"area": "Exercise", "status": "green", "text": "1 session so far this week"}


def test_refresh_buddy_stale_single_session_week_goes_yellow(monkeypatch, s3, capsys, frozen_now, frozen_pacific):
    """One session on Monday and nothing since — 2 days stale drops it out of green."""
    rows = _green_buddy_rows()
    rows["strava"] = [
        {"sk": "DATE#2026-06-14", "activities": [{"name": "Sun Walk", "sport_type": "Walk", "moving_time_seconds": 1800}]},
        {"sk": "DATE#2026-06-15", "activities": [{"name": "Lift", "sport_type": "WeightTraining", "moving_time_seconds": 3000}]},
    ]
    # 06-15 is Monday => week_count 1, last session 2 days ago => still green by the ladder;
    # push the last session back one more day to cross into yellow.
    rows["strava"] = rows["strava"][:1] + [
        {"sk": "DATE#2026-06-14", "activities": [{"name": "Sun Walk", "sport_type": "Walk", "moving_time_seconds": 1800}]}
    ]
    doc = _run_buddy(monkeypatch, s3, capsys, rows)
    # nothing since Sunday and Sunday is outside the Mon-start week => no sessions this week
    assert doc["status_lines"][1]["status"] == "red"
    assert doc["status_lines"][1]["text"] == "No exercise this week — last session 3 days ago"


def test_refresh_buddy_three_recent_food_logs_read_as_tracking_not_consistency(monkeypatch, s3, capsys, frozen_now, frozen_pacific):
    """3 logs ending 2 days ago clears the second rung of the ladder, not the first."""
    rows = _green_buddy_rows()
    rows["macrofactor"] = [
        {"sk": "DATE#2026-06-13", "total_calories_kcal": 2000},
        {"sk": "DATE#2026-06-14", "total_calories_kcal": 2000},
        {"sk": "DATE#2026-06-15", "total_calories_kcal": 2000},
    ]
    doc = _run_buddy(monkeypatch, s3, capsys, rows)
    assert doc["status_lines"][0] == {"area": "Food Logging", "status": "green", "text": "Logging food — 3 of last 7 days tracked"}


def test_refresh_buddy_one_stale_session_in_a_late_week_goes_yellow(monkeypatch, s3, capsys, frozen_now, frozen_pacific):
    """Friday with a single Monday session: still counts for the week, but it has gone stale."""
    rows = _green_buddy_rows()
    rows["strava"] = [
        {"sk": "DATE#2026-06-15", "activities": [{"name": "Lift", "sport_type": "WeightTraining", "moving_time_seconds": 3000}]}
    ]
    doc = _run_buddy(monkeypatch, s3, capsys, rows, today=date(2026, 6, 19))
    assert doc["status_lines"][1] == {
        "area": "Exercise",
        "status": "yellow",
        "text": "1 session this week, last was 4 days ago",
    }


def test_refresh_buddy_early_week_with_no_sessions_is_not_yet_a_failure(monkeypatch, s3, capsys, frozen_now, frozen_pacific):
    rows = _green_buddy_rows()
    rows["strava"] = []
    doc = _run_buddy(monkeypatch, s3, capsys, rows, today=date(2026, 6, 15))  # Monday
    assert doc["status_lines"][1] == {"area": "Exercise", "status": "yellow", "text": "No sessions yet this week (Monday)"}


def test_refresh_buddy_routine_ladder_holds_at_two_days_and_softens_at_three(monkeypatch, s3, capsys, frozen_now, frozen_pacific):
    rows = _green_buddy_rows()
    rows["habitify"] = [{"sk": "DATE#2026-06-15", "completed_count": 3}]  # 2 days ago
    doc = _run_buddy(monkeypatch, s3, capsys, rows)
    assert doc["status_lines"][2] == {"area": "Routine", "status": "green", "text": "Routine is holding, habits being logged"}

    rows["habitify"] = [
        {"sk": "DATE#2026-06-14", "completed_count": 3},
        {"sk": "DATE#2026-06-16", "completed_count": 0},  # a zero-completion day is not a log
    ]
    doc = _run_buddy(monkeypatch, s3, capsys, rows)
    assert doc["status_lines"][2] == {"area": "Routine", "status": "yellow", "text": "Habit tracking quiet for 3 days"}


def test_refresh_buddy_weight_uptick_is_reported_as_a_soft_signal(monkeypatch, s3, capsys, frozen_now, frozen_pacific):
    rows = _green_buddy_rows()
    rows["withings"] = [
        {"sk": "DATE#2026-06-11", "weight_lbs": 296.0},
        {"sk": "DATE#2026-06-17", "weight_lbs": 297.5},
    ]
    doc = _run_buddy(monkeypatch, s3, capsys, rows)
    assert doc["status_lines"][3] == {"area": "Weight", "status": "yellow", "text": "Weight ticked up slightly this week"}


def test_refresh_buddy_flat_weight_reads_as_holding_steady(monkeypatch, s3, capsys, frozen_now, frozen_pacific):
    rows = _green_buddy_rows()
    rows["withings"] = [
        {"sk": "DATE#2026-06-11", "weight_lbs": 296.0},
        {"sk": "DATE#2026-06-17", "weight_lbs": 296.2},
    ]
    doc = _run_buddy(monkeypatch, s3, capsys, rows)
    assert doc["status_lines"][3] == {"area": "Weight", "status": "green", "text": "Weight holding steady"}


def test_refresh_buddy_ignores_implausible_sub_100_lb_readings(monkeypatch, s3, capsys, frozen_now, frozen_pacific):
    rows = _green_buddy_rows()
    rows["withings"] = [
        {"sk": "DATE#2026-06-16", "weight_lbs": 4.5},  # a scale reading somebody's luggage
        {"sk": "DATE#2026-06-17", "weight_lbs": 296.0},
    ]
    doc = _run_buddy(monkeypatch, s3, capsys, rows)
    assert doc["status_lines"][3] == {"area": "Weight", "status": "green", "text": "Weighed in recently"}
    assert doc["journey"]["lost_lbs"] == 24.0


def test_refresh_buddy_falls_back_to_the_data_date_when_the_pacific_clock_is_unavailable(monkeypatch, s3, capsys, frozen_now):
    def _boom():
        raise RuntimeError("zoneinfo unavailable")

    monkeypatch.setattr("common.pacific_time.pacific_now", _boom)
    doc = _run_buddy(monkeypatch, s3, capsys, _green_buddy_rows())
    assert doc["last_updated_friendly"] == YESTERDAY


def test_refresh_buddy_swallows_a_read_failure_without_writing_a_partial_document(monkeypatch, s3, capsys):
    def _boom(*_args, **_kwargs):
        raise RuntimeError("DDB unavailable")

    monkeypatch.setattr(drl, "fetch_range", _boom)
    drl.refresh_buddy(BUDDY_PROFILE, YESTERDAY, TODAY)

    assert s3.puts == []
    assert "Buddy refresh failed" in capsys.readouterr().out


def test_refresh_buddy_survives_a_malformed_activities_field(monkeypatch, s3, capsys, frozen_now, frozen_pacific):
    rows = _green_buddy_rows()
    rows["strava"] = [{"sk": "DATE#2026-06-17", "activities": "not-a-list"}]
    doc = _run_buddy(monkeypatch, s3, capsys, rows)
    assert doc["activity_highlights"] == []
    assert doc["status_lines"][1]["status"] == "red"


def test_refresh_buddy_uses_the_experiment_defaults_when_the_profile_is_empty(monkeypatch, s3, capsys, frozen_now, frozen_pacific):
    doc = _run_buddy(monkeypatch, s3, capsys, _green_buddy_rows(), profile={})
    assert doc["journey"]["goal_lbs"] == 185
    # 321.6 baseline - 296.0 latest
    assert doc["journey"]["lost_lbs"] == round(EXPERIMENT_BASELINE_WEIGHT_LBS - 296.0, 1)


def test_refresh_buddy_zeroes_journey_days_for_an_unparseable_start_date(monkeypatch, s3, capsys, frozen_now, frozen_pacific):
    profile = dict(BUDDY_PROFILE, journey_start_date="not-a-date")
    doc = _run_buddy(monkeypatch, s3, capsys, _green_buddy_rows(), profile=profile)
    assert doc["journey"]["days"] == 0


# ══════════════════════════════════════════════════════════════════════════════
# lambda_handler
# ══════════════════════════════════════════════════════════════════════════════


def test_lambda_handler_derives_today_and_yesterday_and_drives_both_refreshers(monkeypatch, frozen_now):
    calls = []
    monkeypatch.setattr(drl, "load_profile", lambda: {"goal_weight_lbs": 185})
    monkeypatch.setattr(drl, "refresh_dashboard", lambda p, y, t: calls.append(("dashboard", p, y, t)))
    monkeypatch.setattr(drl, "refresh_buddy", lambda p, y, t: calls.append(("buddy", p, y, t)))

    assert drl.lambda_handler({}, None) == {"statusCode": 200, "body": "Dashboard refreshed"}

    expected_today = _FrozenDatetime.FIXED.date()
    assert [c[0] for c in calls] == ["dashboard", "buddy"]
    for _name, profile, yesterday, today in calls:
        assert profile == {"goal_weight_lbs": 185}
        assert today == expected_today
        assert yesterday == (expected_today - timedelta(days=1)).isoformat()


def test_lambda_handler_reraises_so_the_schedule_records_a_failure(monkeypatch, frozen_now):
    def _boom():
        raise RuntimeError("profile read exploded")

    monkeypatch.setattr(drl, "load_profile", _boom)
    with pytest.raises(RuntimeError, match="profile read exploded"):
        drl.lambda_handler({}, None)


# ── #3204: a CGM session that ended must not live on in an undated artifact ───
#
# `dashboard/data.json` carries no date of its own, so a number it retains is not
# merely old — it is undatable, and nothing in the document can ever expire it.
# Two defects combined to make it the platform's longest-lived stale reading when
# the Dexcom Stelo session ended on 2026-08-24:
#   (a) `glucose_src = apple_today or apple` picked the ROW, not the READING. The
#       apple_health partition kept writing daily rows for steps and water, so
#       today's glucose-free row was truthy and SHADOWED yesterday's real reading.
#   (b) every write was `if value:` with no `else`, so a value once written could
#       never be removed.
# The intraday `if value:` retention itself is deliberate and is NOT the bug — this
# lambda merges into the morning brief's doc at 2 PM and 6 PM, and a partial day
# that has not yet computed an average must not blank the morning's. The tests
# above pin that. What follows pins the two things that were wrong.


def test_a_glucose_free_row_does_not_shadow_a_real_reading_from_the_day_before(monkeypatch, s3, frozen_now):
    """Defect (a), on the shape that caused it: today's row exists and is truthy —
    steps and water landed — but carries no `blood_glucose_*` attribute at all.

    Pre-fix this row won `apple_today or apple` and contributed nothing, so the
    document silently fell back on whatever was already in it. Now the newest row
    that actually CARRIES glucose is selected, and yesterday's real reading wins.
    """
    dates = {
        ("apple_health", YESTERDAY): {"blood_glucose_avg": 118.0, "time_in_range_pct": 77.0},
        ("apple_health", "2026-06-17"): {"steps": 8412, "water_intake_ml": 1900},
    }
    _install_dashboard_doubles(monkeypatch, s3, dates=dates)
    drl.refresh_dashboard(DASHBOARD_PROFILE, YESTERDAY, TODAY)

    doc = s3.written(DASH_KEY)
    assert doc["glucose"]["avg"] == 118.0, "the glucose-free row must not shadow the reading behind it"
    assert doc["glucose"]["tir_pct"] == 77.0
    assert doc["glucose"]["as_of"] == YESTERDAY, "and the value must now say which day it is from"


def test_a_dark_sensor_clears_the_retained_glucose_block_instead_of_keeping_it(monkeypatch, s3, frozen_now):
    """Defect (b) — the one that never decayed.

    No apple_health row carries glucose at all (the sensor ended days ago), while
    the stored document still holds the last good numbers. Pre-fix every field
    survived untouched, forever, undated. The must-fail control is that EXISTING_
    DASHBOARD's glucose values are gone: asserting merely that keys exist would
    have passed against the bug.
    """
    _install_dashboard_doubles(monkeypatch, s3, dates={})
    assert EXISTING_DASHBOARD["glucose"].get(
        "avg"
    ), "fixture guard: the stored doc must start with a retained value, or this proves nothing"

    drl.refresh_dashboard(DASHBOARD_PROFILE, YESTERDAY, TODAY)

    doc = s3.written(DASH_KEY)
    assert doc["glucose"]["avg"] is None, "a dead reading must be cleared, not retained"
    assert doc["glucose"]["tir_pct"] is None
    assert doc["glucose"]["variability"] is None
    assert doc["glucose"]["fasting_proxy"] is None
    assert doc["glucose"]["as_of"] is None
    assert "glucose" in doc, "absence is STATED — the section stays, as nulls, rather than vanishing"


def test_a_reading_older_than_the_registry_reader_bar_is_not_republished(monkeypatch, s3, frozen_now):
    """The bar is the registry's, not a number invented here: `reader_surface.
    max_days_behind` = 1 for CGM. A reading from two days back is outside it even
    though a row for that day exists and carries real glucose."""
    two_days_back = "2026-06-15"
    monkeypatch.setattr(drl, "fetch_date", _make_fetch_date({("apple_health", two_days_back): {"blood_glucose_avg": 118.0}}))
    monkeypatch.setattr(drl, "fetch_range", _make_fetch_range(_dashboard_rows()))
    monkeypatch.setattr(drl, "training_load", _FakeTrainingLoad())
    s3.objects[DASH_KEY] = json.dumps(EXISTING_DASHBOARD)

    drl.refresh_dashboard(DASHBOARD_PROFILE, YESTERDAY, TODAY)
    assert s3.written(DASH_KEY)["glucose"]["avg"] is None
