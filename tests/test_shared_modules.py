"""
tests/test_shared_modules.py — Unit tests for Life Platform shared Lambda modules.

Covers:
  - ingestion_validator.py   (DATA-2 wiring module)
  - ai_output_validator.py   (AI-3 safety module)
  - platform_logger.py       (OBS-1 structured logger)
  - sick_day_checker.py      (shared utility)
  - digest_utils.py          (shared digest helpers)

Run with:   python3 -m pytest tests/test_shared_modules.py -v
Or directly: python3 tests/test_shared_modules.py

v1.0.0 — 2026-03-10 (Item 4, sprint v3.5.0)
"""

import json
import logging
import os
import sys
import traceback
from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock

# ── Add lambdas/ to import path ───────────────────────────────────────────────
LAMBDAS_DIR = os.path.join(os.path.dirname(__file__), "..", "lambdas")
sys.path.insert(0, os.path.abspath(LAMBDAS_DIR))

PASS = "PASS"
FAIL = "FAIL"
results = []


def _run(name, fn):
    """Run a named test case and record result. Not named 'test' to avoid pytest collection."""
    try:
        fn()
        results.append((PASS, name))
        print(f"  [PASS]  {name}")
    except Exception as e:
        results.append((FAIL, name))
        print(f"  [FAIL]  {name}")
        print(f"       {type(e).__name__}: {e}")
        if os.environ.get("VERBOSE"):
            traceback.print_exc()


def approx(v, rel=1e-3):
    class A:
        def __eq__(self, other):
            return abs(other - v) <= rel * abs(v) + 1e-9

        def __repr__(self):
            return f"approx({v})"

    return A()


# ======================================================================
# ai_output_validator
# ======================================================================
print("\n-- ai_output_validator ------------------------------------------")

from ai.ai_output_validator import (
    AIOutputType,
    _fallback_for_type,
    validate_ai_output,
)


def test_empty_blocked():
    r = validate_ai_output("", AIOutputType.BOD_COACHING)
    assert r.blocked, "Empty string should be blocked"
    assert r.safe_fallback


def test_none_blocked():
    r = validate_ai_output(None, AIOutputType.BOD_COACHING)
    assert r.blocked
    assert "Empty" in r.block_reason


def test_too_short_blocked():
    r = validate_ai_output("Hi", AIOutputType.BOD_COACHING, min_length=10)
    assert r.blocked
    assert "short" in r.block_reason


def test_truncated_blocked():
    r = validate_ai_output("Recovery looks good and", AIOutputType.BOD_COACHING)
    assert r.blocked, "Should be blocked — ends with 'and'"


def test_good_text_passes():
    r = validate_ai_output(
        "Recovery is in a strong position today. Focus on quality over quantity in training.",
        AIOutputType.BOD_COACHING,
    )
    assert not r.blocked, f"Should not be blocked; reason={r.block_reason}"


def test_dangerous_training_red_recovery():
    r = validate_ai_output(
        "You should do HIIT and high-intensity intervals today to push your limits.",
        AIOutputType.BOD_COACHING,
        health_context={"recovery_score": 20},
    )
    assert r.blocked, "HIIT with recovery=20 should be blocked"
    assert "recovery" in r.block_reason.lower()


def test_aggressive_borderline_warns():
    r = validate_ai_output(
        "Consider adding more volume and high-intensity work this week.",
        AIOutputType.BOD_COACHING,
        health_context={"recovery_score": 42},
    )
    assert not r.blocked, "Borderline recovery should warn, not block"
    assert r.warnings


def test_low_cal_blocked():
    r = validate_ai_output(
        "Aim for 600 kcal today to maximize fat loss.",
        AIOutputType.NUTRITION_COACH,
    )
    assert r.blocked, "600 kcal recommendation should be blocked"


def test_causation_warns():
    r = validate_ai_output(
        "This data clearly causing your fatigue proves the pattern.",
        AIOutputType.GENERIC,
    )
    assert r.warnings


def test_generic_phrases_warn():
    r = validate_ai_output(
        "Stay hydrated and drink plenty of water. Get enough sleep and exercise regularly.",
        AIOutputType.BOD_COACHING,
    )
    assert r.warnings


def test_sanitized_text_fallback():
    r = validate_ai_output("", AIOutputType.TLDR)
    assert r.sanitized_text == r.safe_fallback


def test_sanitized_text_original():
    good = "Strong recovery day — lean into Zone 2 training this afternoon."
    r = validate_ai_output(good, AIOutputType.TRAINING_COACH)
    assert r.sanitized_text == good


def test_fallbacks_all_types():
    for t in AIOutputType:
        fb = _fallback_for_type(t)
        assert fb and len(fb) > 5, f"Fallback for {t} must be non-empty"


_run("empty string blocked", test_empty_blocked)
_run("None blocked", test_none_blocked)
_run("too short blocked", test_too_short_blocked)
_run("truncated mid-sentence blocked", test_truncated_blocked)
_run("good coaching text passes", test_good_text_passes)
_run("HIIT + red recovery -> blocked", test_dangerous_training_red_recovery)
_run("aggressive + borderline recovery -> warn only", test_aggressive_borderline_warns)
_run("dangerously low calories -> blocked", test_low_cal_blocked)
_run("causation language -> warn", test_causation_warns)
_run("2+ generic phrases -> warn", test_generic_phrases_warn)
_run("sanitized_text returns fallback when blocked", test_sanitized_text_fallback)
_run("sanitized_text returns original when passing", test_sanitized_text_original)
_run("all output types have non-empty fallbacks", test_fallbacks_all_types)


# ======================================================================
# platform_logger
# ======================================================================
print("\n-- platform_logger ----------------------------------------------")

from common.platform_logger import PlatformLogger, StructuredFormatter, get_logger


def test_get_logger_type():
    assert isinstance(get_logger("test-source"), PlatformLogger)


def test_get_logger_singleton():
    a = get_logger("singleton-test")
    b = get_logger("singleton-test")
    assert a is b


def test_set_date():
    logger = get_logger("date-test")
    logger.set_date("2026-03-10")
    assert logger._correlation_id == "date-test#2026-03-10"


def test_set_correlation_id():
    logger = get_logger("corr-test")
    logger.set_correlation_id("custom-id-abc")
    assert logger._correlation_id == "custom-id-abc"


def test_info_json_output():
    import io

    logger = get_logger("json-test-src")
    logger.set_date("2026-03-10")
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(StructuredFormatter())
    logger.addHandler(handler)
    logger.info("Test message", foo="bar", count=42)
    logger.removeHandler(handler)
    doc = json.loads(buf.getvalue().strip())
    assert doc["message"] == "Test message"
    assert doc["foo"] == "bar"
    assert doc["count"] == 42
    assert doc["level"] == "INFO"
    assert doc["source"] == "json-test-src"
    assert doc["correlation_id"] == "json-test-src#2026-03-10"


def test_positional_args():
    import io

    logger = get_logger("posargs-test")
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(StructuredFormatter())
    logger.addHandler(handler)
    logger.info("Value is %s and %s", "hello", "world")
    logger.removeHandler(handler)
    doc = json.loads(buf.getvalue().strip())
    assert "hello" in doc["message"] and "world" in doc["message"]


def test_helpers_no_raise():
    logger = get_logger("helper-test")
    logger.set_date("2026-03-10")
    logger.ingestion_start("2026-03-10", lookback_days=7)
    logger.ingestion_complete("2026-03-10", records_written=5)
    logger.source_missing("garmin", "2026-03-10")
    logger.ai_call_start("bod", "claude-haiku", 300)
    logger.ai_call_complete("bod", 500, 280, latency_ms=1200.5)
    logger.ai_call_failed("bod", "timeout", attempt=2)
    logger.email_sent("test@example.com", "Subject")
    logger.ddb_write("whoop", "2026-03-10", size_bytes=1024)
    logger.s3_write("dashboard/data.json", size_bytes=4096)


_run("get_logger returns PlatformLogger", test_get_logger_type)
_run("get_logger is singleton per source", test_get_logger_singleton)
_run("set_date updates correlation_id", test_set_date)
_run("set_correlation_id works", test_set_correlation_id)
_run("info() produces valid structured JSON", test_info_json_output)
_run("positional %s args interpolated into message", test_positional_args)
_run("convenience helpers don't raise", test_helpers_no_raise)


# ======================================================================
# sick_day_checker
# ======================================================================
print("\n-- sick_day_checker ---------------------------------------------")

from health.sick_day_checker import (
    check_sick_day,
    clear_sick_day,
    get_sick_days_range,
    write_sick_day,
)


def _mock_table(item=None):
    t = MagicMock()
    t.get_item.return_value = {"Item": item} if item else {}
    t.query.return_value = {"Items": []}
    return t


def test_check_sick_day_none():
    assert check_sick_day(_mock_table(), "matthew", "2026-03-10") is None


def test_check_sick_day_found():
    item = {"pk": "X", "sk": "Y", "date": "2026-03-10", "logged_at": "2026-03-10T12:00:00Z", "schema_version": 1}
    result = check_sick_day(_mock_table(item), "matthew", "2026-03-10")
    assert result is not None
    assert result["date"] == "2026-03-10"


def test_check_sick_day_decimal():
    item = {"pk": "X", "sk": "Y", "schema_version": Decimal("1")}
    result = check_sick_day(_mock_table(item), "matthew", "2026-03-10")
    assert isinstance(result["schema_version"], float)


def test_check_sick_day_ddb_error():
    t = MagicMock()
    t.get_item.side_effect = Exception("DDB timeout")
    assert check_sick_day(t, "matthew", "2026-03-10") is None


def test_get_sick_days_range_empty():
    assert get_sick_days_range(_mock_table(), "matthew", "2026-03-01", "2026-03-10") == []


def test_get_sick_days_range_error():
    t = MagicMock()
    t.query.side_effect = Exception("DDB error")
    assert get_sick_days_range(t, "matthew", "2026-03-01", "2026-03-10") == []


def test_write_sick_day_fields():
    t = MagicMock()
    item = write_sick_day(t, "matthew", "2026-03-10", reason="flu")
    t.put_item.assert_called_once()
    assert item["date"] == "2026-03-10"
    assert item["reason"] == "flu"
    assert "logged_at" in item
    assert item["schema_version"] == 1


def test_write_sick_day_no_reason():
    t = MagicMock()
    item = write_sick_day(t, "matthew", "2026-03-10")
    assert "reason" not in item


def test_clear_sick_day_tombstones_via_update_never_delete():
    """#4378: the MCP role has no dynamodb:DeleteItem on sick_days — clear is a
    conditional UpdateItem tombstone."""
    t = MagicMock()
    cleared_at = clear_sick_day(t, "matthew", "2026-03-10", reason="logged in error")
    assert cleared_at
    t.delete_item.assert_not_called()
    kw = t.update_item.call_args.kwargs
    assert kw["Key"] == {"pk": "USER#matthew#SOURCE#sick_days", "sk": "DATE#2026-03-10"}
    assert kw["ConditionExpression"] == "attribute_exists(sk) AND attribute_not_exists(cleared_at)"
    assert kw["ExpressionAttributeValues"] == {":ca": cleared_at, ":cr": "logged in error"}


def test_clear_sick_day_lost_condition_is_none_other_errors_raise():
    t = MagicMock()
    t.update_item.side_effect = Exception("ConditionalCheckFailedException: The conditional request failed")
    assert clear_sick_day(t, "matthew", "2026-03-10") is None
    t.update_item.side_effect = Exception("AccessDeniedException")
    try:
        clear_sick_day(t, "matthew", "2026-03-10")
    except Exception as e:  # noqa: BLE001
        assert "AccessDenied" in str(e)
    else:
        raise AssertionError("a non-conditional failure must propagate, never read as 'nothing to clear'")


def test_check_sick_day_cleared_row_is_not_sick():
    item = {"pk": "X", "sk": "Y", "date": "2026-03-10", "cleared_at": "2026-03-11T00:00:00+00:00"}
    assert check_sick_day(_mock_table(item), "matthew", "2026-03-10") is None


def test_get_sick_days_range_skips_cleared_rows():
    t = _mock_table()
    t.query.return_value = {
        "Items": [
            {"date": "2026-03-09"},
            {"date": "2026-03-10", "cleared_at": "2026-03-11T00:00:00+00:00", "cleared_reason": "logged_in_error"},
        ]
    }
    assert [r["date"] for r in get_sick_days_range(t, "matthew", "2026-03-01", "2026-03-10")] == ["2026-03-09"]


_run("check_sick_day: None when not found", test_check_sick_day_none)
_run("check_sick_day: returns item when found", test_check_sick_day_found)
_run("check_sick_day: Decimal -> float conversion", test_check_sick_day_decimal)
_run("check_sick_day: DDB error returns None", test_check_sick_day_ddb_error)
_run("get_sick_days_range: empty -> []", test_get_sick_days_range_empty)
_run("get_sick_days_range: DDB error -> []", test_get_sick_days_range_error)
_run("write_sick_day: correct fields in item", test_write_sick_day_fields)
_run("write_sick_day: no reason field if not provided", test_write_sick_day_no_reason)
_run("clear_sick_day: tombstones via update_item, never delete_item", test_clear_sick_day_tombstones_via_update_never_delete)
_run("clear_sick_day: lost condition -> None, other errors raise", test_clear_sick_day_lost_condition_is_none_other_errors_raise)
_run("check_sick_day: a cleared row is not a sick day", test_check_sick_day_cleared_row_is_not_sick)
_run("get_sick_days_range: skips cleared rows", test_get_sick_days_range_skips_cleared_rows)


# ======================================================================
# digest_utils
# ======================================================================
print("\n-- digest_utils -------------------------------------------------")

from common.digest_utils import (
    _normalize_whoop_sleep,
    avg,
    compute_banister_from_dict,
    d2f,
    dedup_activities,
    ex_whoop_from_list,
    ex_withings_from_list,
    fmt,
    fmt_num,
    safe_float,
)
from common.pacific_time import pacific_now  # #3222: the frame digest_utils' Banister loop reads


def test_d2f_decimal():
    assert d2f(Decimal("3.14")) == approx(3.14)


def test_d2f_nested():
    result = d2f({"a": Decimal("1"), "b": [Decimal("2"), 3]})
    assert result == {"a": 1.0, "b": [2.0, 3]}


def test_avg_basic():
    assert avg([1, 2, 3]) == 2.0


def test_avg_none_ignored():
    assert avg([1, None, 3]) == 2.0


def test_avg_empty():
    assert avg([]) is None


def test_avg_all_none():
    assert avg([None, None]) is None


def test_fmt_value():
    assert fmt(3.14) == "3.1"


def test_fmt_none():
    assert fmt(None) == "\u2014"


def test_fmt_with_unit():
    assert fmt(7.5, " hrs") == "7.5 hrs"


def test_fmt_num():
    assert fmt_num(1234) == "1,234"


def test_fmt_num_none():
    assert fmt_num(None) == "\u2014"


def test_safe_float_present():
    assert safe_float({"weight_lbs": "185.5"}, "weight_lbs") == 185.5


def test_safe_float_missing():
    assert safe_float({}, "weight_lbs") is None


def test_safe_float_default():
    assert safe_float({}, "weight_lbs", default=0.0) == 0.0


def test_dedup_different_sports():
    acts = [
        {"sport_type": "Run", "start_date_local": "2026-03-10T08:00:00", "moving_time_seconds": 3600, "kilojoules": 800},
        {"sport_type": "Ride", "start_date_local": "2026-03-10T18:00:00", "moving_time_seconds": 5400, "kilojoules": 1200},
    ]
    assert len(dedup_activities(acts)) == 2


def test_dedup_removes_duplicate():
    acts = [
        {"sport_type": "Run", "start_date_local": "2026-03-10T08:00:00", "moving_time_seconds": 3600, "kilojoules": 800},
        {"sport_type": "Run", "start_date_local": "2026-03-10T08:05:00", "moving_time_seconds": 3600, "kilojoules": 200},
    ]
    result = dedup_activities(acts)
    assert len(result) == 1
    assert result[0]["kilojoules"] == 800


def test_dedup_empty():
    assert dedup_activities([]) == []


# ── #4419: the ONE multi-device dedupe, applied at the strava read seam ──────────────────
#
# Fixture = two REAL days read from DDB 2026-09-28 (`USER#matthew#SOURCE#strava`,
# DATE#2024-10-01 and DATE#2024-10-05), trimmed to the fields the rule reads; the GPS
# polyline is replaced by a stub (only its presence is scored). WHOOP + Garmin both pushed
# each walk to Strava; the Garmin copies carry a 49–54 bpm "walk" average.


def _act(sid, sport, device, start, moving, elapsed=None, dist_m=0.0, miles=None, hr=None, hr_max=None, poly=False, kj=None, elev=None):
    return {
        "strava_id": sid,
        "sport_type": sport,
        "device_name": device,
        "start_date_local": start,
        "moving_time_seconds": moving,
        "elapsed_time_seconds": elapsed if elapsed is not None else moving,
        "distance_meters": dist_m,
        "distance_miles": miles,
        "average_heartrate": hr,
        "max_heartrate": hr_max,
        "has_heartrate": hr is not None,
        "kilojoules": kj,
        "total_elevation_gain_feet": elev,
        "summary_polyline": "<stub>" if poly else "",
    }


def _real_day_2024_10_01():
    acts = [
        _act("12553313491", "Ride", "WHOOP", "2024-10-01T17:58:39Z", 1992.0, hr=121.2, hr_max=145.0),
        _act(
            "12553030728",
            "VirtualRide",
            "Zwift",
            "2024-10-01T17:58:39Z",
            1992.0,
            dist_m=11524.4,
            miles=7.16,
            hr=53.0,
            hr_max=146.0,
            poly=True,
            kj=200.3,
            elev=210.0,
        ),
        _act("12553059781", "WeightTraining", "WHOOP", "2024-10-01T16:38:19Z", 3772.0, hr=107.6, hr_max=139.0),
        _act("12552802174", "WeightTraining", "Hevy", "2024-10-01T16:38:19Z", 3772.0),
        _act("12551326552", "Walk", "WHOOP", "2024-10-01T12:13:30Z", 3599.0, hr=103.5, hr_max=121.0),
        _act(
            "12551278752",
            "Walk",
            "Garmin Epix Gen2",
            "2024-10-01T12:12:43Z",
            3656.0,
            dist_m=4825.2,
            miles=3.0,
            hr=49.3,
            hr_max=124.0,
            poly=True,
            elev=39.4,
        ),
    ]
    # the stored totals, as written (they sum BOTH copies of every session)
    return {
        "pk": "USER#matthew#SOURCE#strava",
        "sk": "DATE#2024-10-01",
        "date": "2024-10-01",
        "activities": acts,
        "activity_count": 6,
        "total_moving_time_seconds": 18783.0,
        "total_distance_miles": 10.16,
        "total_elevation_gain_feet": 249.4,
        "sport_types": ["Ride", "VirtualRide", "Walk", "WeightTraining"],
    }


def _real_day_2024_10_05():
    acts = [
        _act("12584142709", "Walk", "WHOOP", "2024-10-05T11:51:00Z", 6389.0, hr=116.4, hr_max=145.0),
        _act("12582923905", "Walk", "WHOOP", "2024-10-05T08:46:30Z", 6749.0, hr=114.5, hr_max=153.0),
        _act(
            "12583986726",
            "Walk",
            "Garmin Epix Gen2",
            "2024-10-05T08:45:58Z",
            12605.0,
            elapsed=17194.0,
            dist_m=16588.5,
            miles=10.31,
            hr=54.1,
            hr_max=156.0,
            poly=True,
            elev=744.8,
        ),
        _act("12581225231", "WeightTraining", "WHOOP", "2024-10-05T06:39:42Z", 3149.0, hr=85.5, hr_max=124.0),
        _act("12581011274", "WeightTraining", "Hevy", "2024-10-05T06:39:42Z", 3149.0),
    ]
    return {
        "pk": "USER#matthew#SOURCE#strava",
        "sk": "DATE#2024-10-05",
        "date": "2024-10-05",
        "activities": acts,
        "activity_count": 5,
        "total_moving_time_seconds": 32041.0,
        "total_distance_miles": 10.31,
        "total_elevation_gain_feet": 744.8,
        "sport_types": ["Walk", "WeightTraining"],
    }


def test_dedup_real_2024_walk_pair_keeps_the_measured_distance_and_the_plausible_hr():
    """The WHOOP + Garmin copies of the 2024-10-01 walk are ONE walk: Garmin's distance, WHOOP's HR."""
    walks = [a for a in _real_day_2024_10_01()["activities"] if a["sport_type"] == "Walk"]
    out = dedup_activities(walks)
    assert len(out) == 1, out
    (walk,) = out
    assert walk["strava_id"] == "12551278752" and walk["distance_meters"] == 4825.2  # the device that measured distance
    assert walk["average_heartrate"] == 103.5 and walk["max_heartrate"] == 121.0  # not the 49.3 bpm "walk"
    assert walk["hr_from_strava_id"] == "12551326552"


def test_dedup_real_2024_day_row_through_the_read_seam():
    """The whole stored day: 6 activities -> 3 sessions, and the day totals follow."""
    from common.strava_read_seam import strava_read_seam

    day = _real_day_2024_10_01()
    before = json.dumps(day, sort_keys=True)
    (out,) = strava_read_seam("strava", [day])
    assert json.dumps(day, sort_keys=True) == before, "the seam must not mutate the row it was handed"
    assert [a["strava_id"] for a in out["activities"]] == ["12553030728", "12553059781", "12551278752"]  # writer order kept
    assert out["activity_count"] == 3 and out["duplicate_activity_count"] == 3
    assert out["total_moving_time_seconds"] == 1992.0 + 3772.0 + 3656.0
    assert out["total_distance_miles"] == 10.16 and out["total_elevation_gain_feet"] == 249.4
    assert out["sport_types"] == ["VirtualRide", "Walk", "WeightTraining"]
    assert all(a["average_heartrate"] >= 70 for a in out["activities"]), "no implausible-HR copy survives"
    assert "total_kilojoules" not in out, "a total the stored row never carried is not invented"
    # idempotent: the seam, and every pre-seam per-consumer dedup_activities call, are no-ops on its output
    assert strava_read_seam("strava", [out]) == [out]
    assert dedup_activities(out["activities"]) == sorted(out["activities"], key=lambda a: a["start_date_local"])


def test_dedup_real_2024_containment_chunk_is_the_same_walk():
    """2024-10-05: Garmin logged one 4.8 h walk; WHOOP auto-detected it as two chunks, the second
    starting 3 h after the Garmin's start — the 15-minute start window alone kept that chunk."""
    from common.strava_read_seam import strava_read_seam

    out = strava_read_seam("strava", {"2024-10-05": _real_day_2024_10_05()})["2024-10-05"]
    assert [a["strava_id"] for a in out["activities"]] == ["12583986726", "12581225231"]
    assert out["activities"][0]["average_heartrate"] == 114.5
    assert out["activity_count"] == 2 and out["total_moving_time_seconds"] == 12605.0 + 3149.0
    assert out["total_distance_miles"] == 10.31


def test_dedup_keeps_two_real_sessions_apart():
    """Rule (b) needs different devices AND real containment; one device's back-to-back walks stay two."""
    a = _act("A", "Walk", "WHOOP", "2024-10-06T12:04:30Z", 2789.0, hr=104.7)
    b = _act("B", "Walk", "WHOOP", "2024-10-06T15:54:00Z", 2429.0, hr=103.9)
    c = _act("C", "Walk", "Garmin Epix Gen2", "2024-10-06T13:10:00Z", 600.0, dist_m=800.0, hr=98.0)  # 20 min after A ended
    assert len(dedup_activities([a, b, c])) == 3


def test_strava_read_seam_passes_other_sources_and_the_named_opt_out():
    from common.strava_read_seam import strava_read_seam

    day = _real_day_2024_10_01()
    assert strava_read_seam("hevy", [day]) == [day]
    assert strava_read_seam("strava", [day], keep_duplicates="verbatim export") == [day]
    assert strava_read_seam("strava", None) is None and strava_read_seam("strava", []) == []
    bare = {"pk": "x", "sk": "DATE#2024-10-01"}  # a row with no activities list passes through as-is
    assert strava_read_seam("strava", bare) == bare


def test_query_range_is_the_seam_for_every_digest_reader():
    from common import digest_utils

    table = _FakePagingTable([{"Items": [_real_day_2024_10_01()]}])
    out = digest_utils.query_range(table, "strava", "2024-10-01", "2024-10-01")
    assert out["2024-10-01"]["activity_count"] == 3


def test_the_ingest_writer_and_the_seam_share_one_totals_formula(monkeypatch):
    for k, v in (("S3_BUCKET", "test-bucket"), ("TABLE_NAME", "test-table"), ("USER_ID", "matthew")):
        monkeypatch.setenv(k, os.environ.get(k, v))
    from common.strava_read_seam import day_totals
    from ingestion import strava_lambda

    acts = _real_day_2024_10_01()["activities"]
    (row,) = strava_lambda.transform({"activities": acts}, "2024-10-01")
    writer_totals = {k: v for k, v in row.items() if k not in ("source", "date", "activities")}
    assert writer_totals == day_totals(acts), "the seam's day_totals drifted from strava_lambda.transform — one formula, two copies"


# The SET guard (#4419). A "strava-capable reader" is any function under lambdas/ (ingestion
# excluded — it is the writer) or mcp/ that reads DynamoDB (`.query`/`.get_item`/
# `.batch_get_item`/`.scan`, directly or through a same-module helper) and EITHER builds its
# partition key from a source parameter (`source`/`src`/`partition`/`source_name`) OR names
# the strava partition literally. Each must call `strava_read_seam` — or read structurally
# blind to `activities` (a ProjectionExpression that does not name it, or `Select: COUNT`).
# The one sanctioned opt-out is IN the call: `strava_read_seam(..., keep_duplicates="<why>")`.
_SEAM_READ_ATTRS = {"query", "get_item", "batch_get_item", "scan"}
_SEAM_SOURCE_PARAMS = {"source", "src", "partition", "source_name"}


def _seam_names(node):
    import ast

    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)}


def _seam_strs(node):
    import ast

    return [n.value for n in ast.walk(node) if isinstance(n, ast.Constant) and isinstance(n.value, str)]


def _strava_capable_readers(root):
    import ast
    import re

    key_name = re.compile(r"(?i)prefix|_pk$|^pk$")
    out = []
    for top in ("lambdas", "mcp"):
        for d, _dirs, files in os.walk(os.path.join(root, top)):
            rel_d = os.path.relpath(d, root)
            if rel_d.startswith(os.path.join("lambdas", "ingestion")) or "__pycache__" in rel_d:
                continue
            for f in sorted(files):
                if not f.endswith(".py"):
                    continue
                path = os.path.join(d, f)
                tree = ast.parse(open(path, encoding="utf-8").read())
                fns = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
                raw = {
                    fn.name
                    for fn in fns
                    if any(
                        isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in _SEAM_READ_ATTRS
                        for n in ast.walk(fn)
                    )
                }
                for fn in fns:
                    local = {n.func.id for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
                    if fn.name not in raw and not (local & raw):
                        continue
                    params = {a.arg for a in fn.args.args + fn.args.kwonlyargs} & _SEAM_SOURCE_PARAMS
                    keys = [
                        n
                        for n in ast.walk(fn)
                        if isinstance(n, (ast.JoinedStr, ast.BinOp))
                        or (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "format")
                    ]
                    generic = any(
                        (_seam_names(k) & params)
                        and (any("SOURCE#" in s for s in _seam_strs(k)) or any(key_name.search(x) for x in _seam_names(k)))
                        for k in keys
                    )
                    literal = any("SOURCE#strava" in s for s in _seam_strs(fn)) or any(
                        "strava" in _seam_strs(k) and any(key_name.search(x) for x in _seam_names(k)) for k in keys
                    )
                    if not (generic or literal):
                        continue
                    blind = []
                    for n in ast.walk(fn):
                        pairs = [(k.arg, k.value) for k in n.keywords] if isinstance(n, ast.Call) else []
                        if isinstance(n, ast.Dict):
                            pairs = [(k.value, v) for k, v in zip(n.keys, n.values) if isinstance(k, ast.Constant)]
                        for k, v in pairs:
                            if k == "ProjectionExpression":
                                blind.append(not any("activities" in s for s in _seam_strs(v)))
                            elif k == "Select" and isinstance(v, ast.Constant) and v.value == "COUNT":
                                blind.append(True)
                    if blind and all(blind):
                        continue
                    seamed = any(
                        isinstance(n, ast.Call) and "strava_read_seam" in {getattr(n.func, "id", None), getattr(n.func, "attr", None)}
                        for n in ast.walk(fn)
                    )
                    out.append((os.path.relpath(path, root), fn.name, fn.lineno, seamed))
    return out


def test_every_strava_capable_reader_goes_through_the_read_seam():
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    readers = _strava_capable_readers(root)
    found = {(p, n) for p, n, _, _ in readers}
    # non-vacuity: the three chokepoints the issue names, and the set's measured size (55 on 2026-09-28)
    for must in (
        ("mcp/core.py", "query_source"),
        ("lambdas/common/digest_utils.py", "query_range"),
        ("lambdas/web/site_api_common.py", "_query_source"),
    ):
        assert must in found, f"the sweep no longer sees {must} — the detector is broken, not the tree"
    assert len(readers) >= 50, f"only {len(readers)} strava-capable readers found — the AST walk is not seeing the tree"
    bypass = [f"{p}:{ln} {n}()" for p, n, ln, seamed in readers if not seamed]
    assert not bypass, (
        "a DynamoDB reader that can be handed the strava partition skips the #4419 read seam — its callers would "
        "count every WHOOP+Garmin duplicate twice. Return `strava_read_seam(source, rows)` (a no-op for other sources), "
        "or project the read so it cannot see `activities`:\n  " + "\n  ".join(bypass)
    )


def test_normalize_whoop_sleep():
    item = {
        "sleep_quality_score": 78,
        "sleep_efficiency_percentage": 92,
        "time_awake_hours": 0.5,
        "disturbance_count": 3,
        "sleep_duration_hours": 7.5,
        "slow_wave_sleep_hours": 1.5,
        "rem_sleep_hours": 1.0,
    }
    out = _normalize_whoop_sleep(item)
    assert out["sleep_score"] == 78
    assert out["sleep_efficiency_pct"] == 92
    assert out["waso_hours"] == 0.5
    assert out["toss_and_turns"] == 3
    assert abs(out["deep_pct"] - 20.0) < 0.1
    assert abs(out["rem_pct"] - 13.3) < 0.2


def test_ex_whoop_from_list():
    recs = [
        {"hrv": 45.0, "recovery_score": 72.0, "resting_heart_rate": 58.0, "strain": 8.5},
        {"hrv": 55.0, "recovery_score": 85.0, "resting_heart_rate": 56.0, "strain": 12.0},
    ]
    out = ex_whoop_from_list(recs)
    assert out["hrv_avg"] == 50.0
    assert out["recovery_avg"] == 78.5
    assert out["days"] == 2


def test_ex_whoop_empty():
    assert ex_whoop_from_list([]) is None


def test_ex_withings_latest():
    recs = [
        {"weight_lbs": 225.0, "sk": "DATE#2026-03-09"},
        {"weight_lbs": 224.5, "sk": "DATE#2026-03-10"},
    ]
    out = ex_withings_from_list(recs)
    assert out["weight_latest"] == 224.5
    assert out["measurements"] == 2


def test_banister_zero_input():
    result = compute_banister_from_dict({})
    assert result["ctl"] == 0.0
    assert result["atl"] == 0.0
    assert result["tsb"] == 0.0


def test_banister_with_training():
    # #3222: `compute_banister_from_dict` walks backwards from `pacific_now().date()`
    # over Pacific-keyed DATE# days (#2811). Seeding the dict from a UTC "today" put the
    # newest row on tomorrow-Pacific every evening 17:00 PT → midnight, so the decay
    # loop's first step read a day this fixture never wrote. Same helper the handler calls.
    today = pacific_now().date()
    strava = {}
    for i in range(30):
        d = (today - timedelta(days=i)).isoformat()
        strava[d] = {"activities": [{"kilojoules": 500, "start_date_local": d + "T08:00:00"}]}
    result = compute_banister_from_dict(strava)
    assert result["ctl"] > 0
    assert result["atl"] > 0


_run("d2f: Decimal to float", test_d2f_decimal)
_run("d2f: nested dict/list", test_d2f_nested)
_run("avg: basic mean", test_avg_basic)
_run("avg: None values ignored", test_avg_none_ignored)
_run("avg: empty list -> None", test_avg_empty)
_run("avg: all None -> None", test_avg_all_none)
_run("fmt: formats number", test_fmt_value)
_run("fmt: None -> em dash", test_fmt_none)
_run("fmt: appends unit", test_fmt_with_unit)
_run("fmt_num: thousands separator", test_fmt_num)
_run("fmt_num: None -> em dash", test_fmt_num_none)
_run("safe_float: extracts value", test_safe_float_present)
_run("safe_float: missing key -> None", test_safe_float_missing)
_run("safe_float: missing key -> default", test_safe_float_default)
_run("dedup: different sports kept", test_dedup_different_sports)
_run("dedup: near-duplicate removed, richer kept", test_dedup_removes_duplicate)
_run("dedup: empty list", test_dedup_empty)
_run("_normalize_whoop_sleep: all aliases", test_normalize_whoop_sleep)
_run("ex_whoop_from_list: avgs and count", test_ex_whoop_from_list)
_run("ex_whoop_from_list: empty -> None", test_ex_whoop_empty)
_run("ex_withings_from_list: latest by sk", test_ex_withings_latest)
_run("banister: zero input -> all zeros", test_banister_zero_input)
_run("banister: 30 days training -> CTL > 0", test_banister_with_training)


# ======================================================================
# ingestion_validator (interface-level only, no DDB)
# ======================================================================
print("\n-- ingestion_validator ------------------------------------------")

from ingestion.ingestion_validator import ValidationResult, list_supported_sources, validate_item


def test_validate_whoop_ok():
    record = {
        "pk": "USER#matthew#SOURCE#whoop",
        "sk": "DATE#2026-03-10",
        "date": "2026-03-10",
        "recovery_score": 78,
        "hrv": 52.0,
        "resting_heart_rate": 57,
        "sleep_duration_hours": 7.5,
        "strain": 9.2,
    }
    result = validate_item("whoop", record, "2026-03-10")
    assert result.is_valid, f"Should pass: {result.errors}"


def test_validate_whoop_out_of_range():
    # recovery_score of 150 exceeds max 100
    record = {
        "pk": "USER#matthew#SOURCE#whoop",
        "sk": "DATE#2026-03-10",
        "date": "2026-03-10",
        "recovery_score": 150,
        "hrv": 52.0,
    }
    result = validate_item("whoop", record, "2026-03-10")
    assert result.errors or result.warnings, "Out-of-range should produce error or warning"


def test_validate_empty_record():
    # Missing pk/sk/date → critical errors (should_skip_ddb=True)
    result = validate_item("whoop", {}, "2026-03-10")
    assert not result.is_valid, "Empty record missing pk/sk/date should fail"
    assert result.should_skip_ddb, "should_skip_ddb should be True for critical errors"


def test_validation_result_structure():
    assert hasattr(ValidationResult, "__dataclass_fields__")
    record = {
        "pk": "USER#matthew#SOURCE#whoop",
        "sk": "DATE#2026-03-10",
        "date": "2026-03-10",
        "recovery_score": 78,
    }
    vr = validate_item("whoop", record, "2026-03-10")
    assert hasattr(vr, "errors")
    assert hasattr(vr, "warnings")
    assert hasattr(vr, "is_valid")
    assert hasattr(vr, "should_skip_ddb")


def test_list_supported_sources():
    sources = list_supported_sources()
    assert isinstance(sources, list)
    assert "whoop" in sources
    assert "withings" in sources


_run("validate_item: valid Whoop passes", test_validate_whoop_ok)
_run("validate_item: out-of-range -> error/warning", test_validate_whoop_out_of_range)
_run("validate_item: empty -> soft warn, no hard block", test_validate_empty_record)
_run("ValidationResult: has correct fields", test_validation_result_structure)
_run("list_supported_sources: returns list with whoop, withings", test_list_supported_sources)


# ======================================================================
# call_anthropic middleware — signature + output_type wiring
# ======================================================================
print("\n-- call_anthropic middleware -------------------------------------")

import inspect

from ai.ai_calls import _AI_VALIDATOR_AVAILABLE, call_anthropic


def test_call_anthropic_has_output_type_param():
    sig = inspect.signature(call_anthropic)
    assert "output_type" in sig.parameters, "call_anthropic must accept output_type param"
    assert "health_context" in sig.parameters, "call_anthropic must accept health_context param"
    assert sig.parameters["output_type"].default is None, "output_type default must be None"
    assert sig.parameters["health_context"].default is None, "health_context default must be None"


def test_ai_validator_importable():
    assert _AI_VALIDATOR_AVAILABLE, (
        "ai_output_validator must be importable from Layer — " "check that ai_output_validator.py is in cdk/layer-build/python/"
    )


def test_ai_output_type_importable():
    assert AIOutputType is not None, "AIOutputType must import successfully via ai_calls"
    assert hasattr(AIOutputType, "BOD_COACHING")
    assert hasattr(AIOutputType, "JOURNAL_COACH")
    assert hasattr(AIOutputType, "TRAINING_COACH")


def test_bod_caller_passes_output_type():
    """call_board_of_directors must pass output_type=AIOutputType.BOD_COACHING to call_anthropic."""
    src_path = os.path.join(LAMBDAS_DIR, "ai", "ai_calls.py")
    with open(src_path) as f:
        src = f.read()
    # Check that the BoD final call_anthropic includes BOD_COACHING
    assert "BOD_COACHING" in src, (
        "call_board_of_directors must pass output_type=AIOutputType.BOD_COACHING "
        "to call_anthropic — AI-3 middleware will not activate without it"
    )


def test_journal_caller_passes_output_type():
    """call_journal_coach must pass output_type=AIOutputType.JOURNAL_COACH."""
    src_path = os.path.join(LAMBDAS_DIR, "ai", "ai_calls.py")
    with open(src_path) as f:
        src = f.read()
    assert "JOURNAL_COACH" in src, "call_journal_coach must pass output_type=AIOutputType.JOURNAL_COACH"


def test_email_lambdas_dont_call_anthropic_directly():
    """Email Lambdas should call ai_calls wrappers, not call_anthropic() directly.
    Direct call_anthropic() calls bypass the output_type middleware.
    Checks all email + compute Lambda files."""
    email_lambdas = [
        "daily_brief_lambda.py",
        "weekly_digest_lambda",
        "monthly_digest_lambda.py",
        "nutrition_review_lambda.py",
        "wednesday_chronicle_lambda.py",
        "weekly_plate_lambda.py",
        "monday_compass_lambda.py",
        "partner_email_lambda.py",
        "anomaly_detector_lambda.py",
        "daily_insight_compute_lambda.py",
        "hypothesis_engine_lambda.py",
    ]
    violations = []
    for fname in email_lambdas:
        fpath = os.path.join(LAMBDAS_DIR, fname)
        if not os.path.exists(fpath):
            continue
        with open(fpath) as f:
            src = f.read()
        # Valid wiring patterns:
        #   (a) uses ai_calls module wrappers: "from ai_calls import" present
        #   (b) standalone Lambda with its own local call_anthropic() guarded by _HAS_AI_VALIDATOR
        #       These Lambdas import ai_output_validator directly and call validate_ai_output
        #       post-hoc at the call site — a legitimate alternative pattern.
        # Violation: has call_anthropic( but neither pattern is present.
        has_ai_calls_import = "from ai_calls" in src
        has_standalone_validator = "_HAS_AI_VALIDATOR" in src and "validate_ai_output" in src
        if "call_anthropic(" in src and not has_ai_calls_import and not has_standalone_validator:
            violations.append(fname)
    assert not violations, (
        f"These Lambdas call call_anthropic() directly (bypassing AI-3 middleware): {violations}. "
        "Import and use ai_calls wrappers instead."
    )


_run("call_anthropic: has output_type + health_context params", test_call_anthropic_has_output_type_param)
_run("ai_output_validator: importable (_AI_VALIDATOR_AVAILABLE=True)", test_ai_validator_importable)
_run("AIOutputType: importable with correct members", test_ai_output_type_importable)
_run("call_board_of_directors: passes BOD_COACHING output_type", test_bod_caller_passes_output_type)
_run("call_journal_coach: passes JOURNAL_COACH output_type", test_journal_caller_passes_output_type)
_run("email Lambdas: no direct call_anthropic() bypass", test_email_lambdas_dont_call_anthropic_directly)


# ======================================================================
# digest_utils.query_range / query_range_list (#970 consolidation)
# ======================================================================


class _FakePagingTable:
    """Fake DDB table returning two pages via LastEvaluatedKey."""

    def __init__(self, pages):
        self.pages = list(pages)
        self.calls = []

    def query(self, **kwargs):
        self.calls.append(kwargs)
        page = dict(self.pages[len(self.calls) - 1])
        return page


def test_query_range_paginates_and_returns_dict_by_date():
    """query_range must follow LastEvaluatedKey — the pre-#970 hypothesis_engine
    copy silently truncated at DynamoDB's 1MB page."""
    from common import digest_utils

    pages = [
        {
            "Items": [
                {"pk": "USER#matthew#SOURCE#whoop", "sk": "DATE#2026-01-01", "hrv": Decimal("55.5")},
                {"pk": "USER#matthew#SOURCE#whoop", "sk": "DATE#2026-01-02", "date": "2026-01-02", "hrv": Decimal("60")},
            ],
            "LastEvaluatedKey": {"pk": "USER#matthew#SOURCE#whoop", "sk": "DATE#2026-01-02"},
        },
        {
            "Items": [
                {"pk": "USER#matthew#SOURCE#whoop", "sk": "DATE#2026-01-03", "hrv": Decimal("47")},
            ],
        },
    ]
    table = _FakePagingTable(pages)
    out = digest_utils.query_range(table, "whoop", "2026-01-01", "2026-01-03")
    assert len(table.calls) == 2, "did not paginate via LastEvaluatedKey"
    assert table.calls[1].get("ExclusiveStartKey") == pages[0]["LastEvaluatedKey"]
    assert sorted(out.keys()) == ["2026-01-01", "2026-01-02", "2026-01-03"]
    assert out["2026-01-01"]["hrv"] == 55.5 and isinstance(out["2026-01-01"]["hrv"], float), "Decimals must be d2f-converted"


def test_query_range_applies_phase_filter_and_bounds():
    """Every platform DDB read is phase-scoped (ADR-058); both forms end the range with the
    '~' suffix. The list form needs it for per-workout sks (#485); the dict form drops
    sub-records anyway (#3442), so for it the suffix admits nothing it keeps — it carries
    the suffix because it is a caller-supplied-partition helper and the #4129 census
    (scripts/date_range_read_census.py) holds every such helper to one rule."""
    from common import digest_utils

    table = _FakePagingTable([{"Items": []}])
    digest_utils.query_range(table, "whoop", "2026-01-01", "2026-01-07")
    kwargs = table.calls[0]
    assert "FilterExpression" in kwargs and ":phase_experiment" in kwargs["ExpressionAttributeValues"]
    assert kwargs["ExpressionAttributeValues"][":e"] == "DATE#2026-01-07~"

    table2 = _FakePagingTable([{"Items": []}])
    digest_utils.query_range_list(table2, "hevy", "2026-01-01", "2026-01-07")
    kwargs2 = table2.calls[0]
    assert "FilterExpression" in kwargs2
    assert kwargs2["ExpressionAttributeValues"][":e"] == "DATE#2026-01-07~"


def test_query_range_list_paginates_and_preserves_duplicates():
    """List form keeps two records sharing one date (two-a-day workouts) and paginates."""
    from common import digest_utils

    pages = [
        {
            "Items": [
                {"pk": "USER#matthew#SOURCE#hevy", "sk": "DATE#2026-01-01#WORKOUT#a", "date": "2026-01-01", "volume": Decimal("1000")},
            ],
            "LastEvaluatedKey": {"pk": "USER#matthew#SOURCE#hevy", "sk": "DATE#2026-01-01#WORKOUT#a"},
        },
        {
            "Items": [
                {"pk": "USER#matthew#SOURCE#hevy", "sk": "DATE#2026-01-01#WORKOUT#b", "date": "2026-01-01", "volume": Decimal("500")},
            ],
        },
    ]
    table = _FakePagingTable(pages)
    out = digest_utils.query_range_list(table, "hevy", "2026-01-01", "2026-01-01")
    assert len(out) == 2, "duplicates on one date must be preserved (and pagination followed)"
    assert [r["volume"] for r in out] == [1000.0, 500.0]


_run("digest_utils.query_range: paginates + dict-by-date + d2f", test_query_range_paginates_and_returns_dict_by_date)
_run("digest_utils.query_range: phase filter + range bounds", test_query_range_applies_phase_filter_and_bounds)
_run("digest_utils.query_range_list: paginates + preserves duplicates", test_query_range_list_paginates_and_preserves_duplicates)


# ======================================================================
# Summary
# ======================================================================
passed = sum(1 for s, _ in results if s == PASS)
failed = sum(1 for s, _ in results if s == FAIL)
total = len(results)
print(f"\n{'='*60}")
print(f"  Results: {passed}/{total} passed", end="")
if failed:
    print(f"  ({failed} FAILED)")
    print("\nFailed tests:")
    for s, name in results:
        if s == FAIL:
            print(f"  [FAIL] {name}")
    sys.exit(1)
else:
    print(" -- ALL PASSED")
print("=" * 60)
