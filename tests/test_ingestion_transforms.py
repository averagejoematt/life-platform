"""
tests/test_ingestion_transforms.py — unit tests for the ingestion normalize layer.

Blind-spot audit (2026-06-09): the ingestion `transform()`/`_extract_*`/`_normalize`
functions map raw upstream-API payloads → the DynamoDB item schema, and had ZERO
unit tests — a schema regression (an API renames a field, a unit conversion drifts,
a value mis-maps) only surfaced LIVE at the next scheduled run, not at dev time.

These tests pin the raw-payload → normalized-field contract for the four
highest-churn sources (whoop, withings, strava, garmin) using representative
sample payloads. They are pure-function tests — no AWS, no network — so they run
in the offline suite and catch upstream/our-side breakage before deploy.

(The full `transform()` for whoop/withings does a cross-day DDB query for
deltas/consistency; that I/O path is integration-tested live. Here we cover the
pure extraction/normalization core, which is where the schema mapping lives.)
"""

import os
from datetime import datetime, timezone
from decimal import Decimal

# The ingestion modules build an IngestionConfig at import time, which reads
# S3_BUCKET/TABLE_NAME from the environment. Set harmless dummies before import.
for _k, _v in {
    "S3_BUCKET": "test-bucket",
    "TABLE_NAME": "life-platform",
    "USER_ID": "matthew",
    "AWS_DEFAULT_REGION": "us-west-2",
    "AWS_REGION": "us-west-2",
}.items():
    os.environ.setdefault(_k, _v)

from ingestion.garmin_lambda import transform as garmin_transform  # noqa: E402
from ingestion import strava_lambda as strava  # noqa: E402
from ingestion.strava_lambda import _normalize as strava_normalize  # noqa: E402
from ingestion.whoop_lambda import (  # noqa: E402
    _extract_cycle,
    _extract_recovery,
    _extract_sleep,
    _extract_workout,
)
from ingestion.withings_lambda import _parse_measurements  # noqa: E402


def _f(v):
    """Coerce a possibly-Decimal field to float for numeric comparison."""
    return float(v) if isinstance(v, Decimal) else v


# ══════════════════════════════════════════════════════════════════════════
# Whoop — recovery
# ══════════════════════════════════════════════════════════════════════════
def test_whoop_recovery_scored_maps_all_fields():
    raw = {
        "records": [
            {
                "score_state": "SCORED",
                "score": {
                    "recovery_score": 66,
                    "resting_heart_rate": 52,
                    "hrv_rmssd_milli": 45.678,  # rounds to 2dp
                    "spo2_percentage": 95.513,
                    "skin_temp_celsius": 33.21,
                },
            }
        ]
    }
    out = _extract_recovery(raw)
    assert _f(out["recovery_score"]) == 66
    assert _f(out["resting_heart_rate"]) == 52
    assert _f(out["hrv"]) == 45.68  # rounded
    assert _f(out["spo2_percentage"]) == 95.51
    assert _f(out["skin_temp_celsius"]) == 33.21


def test_whoop_recovery_empty_and_unscored_return_empty():
    assert _extract_recovery({"records": []}) == {}
    assert _extract_recovery({}) == {}
    assert _extract_recovery({"records": [{"score_state": "PENDING_SCORE"}]}) == {}


# ══════════════════════════════════════════════════════════════════════════
# Whoop — sleep (the most complex extractor)
# ══════════════════════════════════════════════════════════════════════════
def test_whoop_sleep_duration_and_aliases():
    raw = {
        "records": [
            {
                "nap": False,
                "score_state": "SCORED",
                "start": "2026-06-08T05:00:00.000Z",
                "end": "2026-06-08T13:00:00.000Z",
                "score": {
                    "stage_summary": {
                        "total_in_bed_time_milli": 28_800_000,  # 8h
                        "total_awake_time_milli": 1_800_000,  # 0.5h → sleep = 7.5h
                        "total_rem_sleep_time_milli": 5_400_000,  # 1.5h
                        "total_slow_wave_sleep_time_milli": 7_200_000,  # 2h
                        "total_light_sleep_time_milli": 10_800_000,  # 3h
                        "disturbance_count": 4,
                    },
                    "respiratory_rate": 15.2,
                    "sleep_performance_percentage": 88,
                },
            }
        ]
    }
    out = _extract_sleep(raw)
    assert _f(out["sleep_duration_hours"]) == 7.5  # (28.8M - 1.8M) / 3.6M
    assert _f(out["rem_sleep_hours"]) == 1.5
    assert _f(out["slow_wave_sleep_hours"]) == 2.0
    assert _f(out["light_sleep_hours"]) == 3.0
    assert _f(out["time_awake_hours"]) == 0.5
    assert out["disturbance_count"] == 4
    assert _f(out["respiratory_rate"]) == 15.2
    # sleep_performance is exposed under both the new name and the legacy alias
    assert _f(out["sleep_performance_percentage"]) == 88
    assert _f(out["sleep_quality_score"]) == 88
    assert out["sleep_start"] == "2026-06-08T05:00:00.000Z"
    assert out["sleep_end"] == "2026-06-08T13:00:00.000Z"


def test_whoop_sleep_picks_main_over_nap_and_counts_naps():
    raw = {
        "records": [
            {
                "nap": True,
                "score_state": "SCORED",
                "score": {"stage_summary": {"total_in_bed_time_milli": 1_800_000, "total_awake_time_milli": 0}},
            },
            {
                "nap": False,
                "score_state": "SCORED",
                "score": {"stage_summary": {"total_in_bed_time_milli": 28_800_000, "total_awake_time_milli": 1_800_000}},
            },
        ]
    }
    out = _extract_sleep(raw)
    assert _f(out["sleep_duration_hours"]) == 7.5  # from the MAIN (non-nap) record
    assert out["nap_count"] == 1
    assert _f(out["nap_duration_hours"]) == 0.5  # the nap's 1.8M ms


def test_whoop_sleep_empty_and_unscored_return_empty():
    assert _extract_sleep({"records": []}) == {}
    assert _extract_sleep({"records": [{"nap": False, "score_state": "PENDING_SCORE"}]}) == {}


# ══════════════════════════════════════════════════════════════════════════
# Whoop — cycle (strain) + workout (sport mapping)
# ══════════════════════════════════════════════════════════════════════════
def test_whoop_cycle_scored():
    raw = {
        "records": [
            {"score_state": "SCORED", "score": {"strain": 12.345, "kilojoule": 8000.6, "average_heart_rate": 70, "max_heart_rate": 160}}
        ]
    }
    out = _extract_cycle(raw)
    assert _f(out["strain"]) == 12.35  # _round(x, 2)
    assert _f(out["kilojoule"]) == 8000.6
    assert _f(out["average_heart_rate"]) == 70
    assert _f(out["max_heart_rate"]) == 160


def test_whoop_workout_maps_known_and_unknown_sport():
    known = _extract_workout({"sport_id": 1, "start": "s", "end": "e", "score_state": "SCORED", "score": {"strain": 8.5}})
    assert known["sport_id"] == 1
    assert known["sport_name"] == "Cycling"  # WHOOP_SPORT_NAMES[1]
    assert known["start_time"] == "s" and known["end_time"] == "e"
    assert _f(known["strain"]) == 8.5

    unknown = _extract_workout({"sport_id": 999, "score_state": "PENDING_SCORE"})
    assert unknown["sport_name"] == "Sport_999"  # fallback label
    assert "strain" not in unknown  # unscored → no score fields


# ══════════════════════════════════════════════════════════════════════════
# Withings — measurement flattening + kg→lbs conversion
# ══════════════════════════════════════════════════════════════════════════
def test_withings_weight_value_scaling_and_lbs():
    # value * 10**unit  →  70000 * 10**-3 = 70.0 kg ; lbs = 70 * 2.20462
    raw = {"measuregrps": [{"date": 1_700_000_000, "measures": [{"type": 1, "value": 70000, "unit": -3}]}]}
    out = _parse_measurements(raw)
    assert _f(out["weight_kg"]) == 70.0
    assert _f(out["weight_lbs"]) == 154.32  # round(70 * 2.20462, 2)
    assert out["measurement_timestamp"] == 1_700_000_000


def test_withings_most_recent_group_wins():
    raw = {
        "measuregrps": [
            {"date": 1_700_000_000, "measures": [{"type": 1, "value": 70000, "unit": -3}]},
            {"date": 1_700_100_000, "measures": [{"type": 1, "value": 68000, "unit": -3}]},  # newer
        ]
    }
    out = _parse_measurements(raw)
    assert _f(out["weight_kg"]) == 68.0  # newest date wins
    assert out["measurement_timestamp"] == 1_700_100_000


def test_withings_empty_and_unknown_type():
    assert _parse_measurements({"measuregrps": []}) == {}
    # unknown measure type is skipped, but the timestamp scaffold still returns
    out = _parse_measurements({"measuregrps": [{"date": 1_700_000_000, "measures": [{"type": 99999, "value": 1, "unit": 0}]}]})
    assert "weight_kg" not in out
    assert out["measurement_timestamp"] == 1_700_000_000


# ══════════════════════════════════════════════════════════════════════════
# Strava — activity normalization + unit conversions
# ══════════════════════════════════════════════════════════════════════════
def test_strava_normalize_core_and_conversions():
    out = strava_normalize(
        {
            "id": 123,
            "name": "Morning Ride",
            "type": "Ride",
            "distance": 5000,  # m → 3.11 miles
            "total_elevation_gain": 100,  # m → 328.1 feet
            "average_heartrate": 150,
            "has_heartrate": True,
            "map": {"summary_polyline": "abc"},
        }
    )
    assert out["strava_id"] == "123"  # coerced to str
    assert out["name"] == "Morning Ride"
    assert out["distance_miles"] == 3.11  # round(5000 * 0.000621371, 2)
    assert out["total_elevation_gain_feet"] == 328.1  # round(100 * 3.28084, 1)
    assert out["average_heartrate"] == 150
    assert out["has_heartrate"] is True
    assert out["summary_polyline"] == "abc"


def test_strava_none_distance_yields_none_miles():
    out = strava_normalize({"id": 9, "name": "Walk"})
    assert out["distance_miles"] is None
    assert out["total_elevation_gain_feet"] is None
    assert out["strava_id"] == "9"


def test_strava_merges_zone_and_hr_recovery():
    out = strava_normalize({"id": 1}, zone_data={"zone2_minutes": 30}, hr_recovery={"bpm_drop_60s": 22})
    assert out["zone2_minutes"] == 30
    assert out["hr_recovery"] == {"bpm_drop_60s": 22}


# ══════════════════════════════════════════════════════════════════════════
# Strava — fetch_day local-date windowing (the Jun 2026 evening-walk gap)
# ══════════════════════════════════════════════════════════════════════════
#
# Records are keyed by the activity's LOCAL date, but the Strava /athlete/
# activities window is expressed in UTC instants. An evening-PT activity has a
# UTC start on the *next* calendar day, so a naive same-day UTC window dropped
# it both ways (past its own day's window; wrong local date on the next). The
# fix brackets the window by ±1 day and lets the start_date_local filter assign
# each activity to exactly one local date. These tests pin that contract — with
# the old single-day window the first test fetches None and fails.

# Evening-PT walk: 17:07 LOCAL on Jun 15 → 00:07 UTC on Jun 16.
_EVENING_WALK = {
    "id": 18936960658,
    "type": "Walk",
    "sport_type": "Walk",
    "start_date": "2026-06-16T00:07:44Z",
    "start_date_local": "2026-06-15T17:07:44Z",
    "distance": 4023.0,
    "has_heartrate": False,
}
# Midday lift the next local day: 05:02 LOCAL Jun 16 → 12:02 UTC Jun 16.
_MIDDAY_LIFT = {
    "id": 18943560629,
    "type": "WeightTraining",
    "sport_type": "WeightTraining",
    "start_date": "2026-06-16T12:02:25Z",
    "start_date_local": "2026-06-16T05:02:25Z",
    "distance": 0.0,
    "has_heartrate": False,
}
_FIXTURE = [_EVENING_WALK, _MIDDAY_LIFT]


def _patch_strava_api(monkeypatch):
    """Mock the Strava list endpoint with a UTC-window-accurate fixture (returns
    only activities whose UTC start falls in [after, before), matching the real
    API), and no-op the per-activity HR enrichment so the test needs no network."""

    def _window_aware(secret, after_ts, before_ts):
        out = [
            a
            for a in _FIXTURE
            if after_ts <= datetime.strptime(a["start_date"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp() < before_ts
        ]
        return out, secret

    monkeypatch.setattr(strava, "_fetch_activities_in_range", _window_aware)
    monkeypatch.setattr(strava, "_fetch_activity_zones", lambda sid, secret: ({}, secret))
    monkeypatch.setattr(strava, "_fetch_activity_streams", lambda sid, secret: ({}, secret))
    strava._secret_cache["secret"] = {"access_token": "x", "expires_at": 9_999_999_999}


def test_strava_fetch_day_captures_evening_pt_activity(monkeypatch):
    _patch_strava_api(monkeypatch)
    # The walk's LOCAL date is Jun 15 even though its UTC start is Jun 16.
    day = strava.fetch_day({}, "2026-06-15")
    assert day is not None, "evening-PT walk dropped — UTC window did not bracket the local day"
    assert [a["strava_id"] for a in day["activities"]] == ["18936960658"]


def test_strava_fetch_day_assigns_each_activity_to_one_local_date(monkeypatch):
    _patch_strava_api(monkeypatch)
    # Jun 16 holds the midday lift but NOT the Jun-15-local walk (no double-count).
    day = strava.fetch_day({}, "2026-06-16")
    assert day is not None
    ids = sorted(a["strava_id"] for a in day["activities"])
    assert ids == ["18943560629"]


# ══════════════════════════════════════════════════════════════════════════
# Garmin — transform is a pass-through wrapper (the mapping is upstream)
# ══════════════════════════════════════════════════════════════════════════
def test_garmin_transform_passthrough_and_empty():
    out = garmin_transform({"steps": 5000, "body_battery": 60}, "2026-06-09")
    assert out == [{"source": "garmin", "date": "2026-06-09", "steps": 5000, "body_battery": 60}]
    assert garmin_transform({}, "2026-06-09") == []
    assert garmin_transform(None, "2026-06-09") == []


# ══════════════════════════════════════════════════════════════════════════
# Strava — reconciliation diff (DI-2: catch a silent drop vs the source of truth)
# ══════════════════════════════════════════════════════════════════════════
#
# _activities_missing_from_store(api, stored) returns the API activities with no
# stored counterpart. It is the one check that compares against Strava itself, so
# it must (a) flag a genuinely-dropped activity and (b) NOT false-positive on a
# deduped GPS-drop twin (collapsed by the ingestion _dedup into its sibling).


# API shape (raw Strava): uses "id" + "start_date".
def _api(id_, start_utc, type_="Walk"):
    return {"id": id_, "type": type_, "start_date": start_utc, "start_date_local": start_utc}


# Stored shape (DDB record): uses "strava_id" + "start_date".
def _stored(sid, start_utc):
    return {"strava_id": str(sid), "start_date": start_utc}


def test_reconcile_flags_dropped_activity():
    api = [_api(111, "2026-06-16T00:07:44Z"), _api(222, "2026-06-16T12:02:25Z", "WeightTraining")]
    stored = [_stored(222, "2026-06-16T12:02:25Z")]  # the walk (111) was dropped
    missing = strava._activities_missing_from_store(api, stored)
    assert [str(a["id"]) for a in missing] == ["111"]


def test_reconcile_clean_when_all_present_by_id():
    api = [_api(111, "2026-06-16T00:07:44Z"), _api(222, "2026-06-16T12:02:25Z")]
    stored = [_stored(111, "2026-06-16T00:07:44Z"), _stored(222, "2026-06-16T12:02:25Z")]
    assert strava._activities_missing_from_store(api, stored) == []


def test_reconcile_does_not_flag_deduped_gps_drop_twin():
    # The real 3mi walk (id 111) is stored; the 0-mi GPS-drop twin (id 999) is 17s
    # later and was intentionally collapsed by _dedup. It must NOT read as missing.
    api = [_api(111, "2026-06-17T00:05:43Z"), _api(999, "2026-06-17T00:06:00Z")]
    stored = [_stored(111, "2026-06-17T00:05:43Z")]
    assert strava._activities_missing_from_store(api, stored) == []
