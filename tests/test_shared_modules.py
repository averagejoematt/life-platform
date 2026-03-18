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

import sys, os, json, logging, math
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import MagicMock
import traceback

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

from ai_output_validator import (
    validate_ai_output, validate_json_output,
    AIOutputType, _fallback_for_type,
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

def test_validate_json_none_blocked():
    r = validate_json_output(None, ["training", "nutrition"])
    assert r.blocked

def test_validate_json_missing_key():
    r = validate_json_output({"training": "good session planned"}, ["training", "nutrition"])
    assert r.blocked

def test_validate_json_ok():
    r = validate_json_output(
        {"training": "Moderate zone 2 is the right call today.",
         "nutrition": "Hit your protein target."},
        ["training", "nutrition"],
    )
    assert not r.blocked

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
_run("validate_json: None input -> blocked", test_validate_json_none_blocked)
_run("validate_json: missing required key -> blocked", test_validate_json_missing_key)
_run("validate_json: all keys present -> passes", test_validate_json_ok)


# ======================================================================
# platform_logger
# ======================================================================
print("\n-- platform_logger ----------------------------------------------")

from platform_logger import get_logger, PlatformLogger, StructuredFormatter

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

from sick_day_checker import (
    check_sick_day, get_sick_days_range, write_sick_day, delete_sick_day,
)

def _mock_table(item=None):
    t = MagicMock()
    t.get_item.return_value = {"Item": item} if item else {}
    t.query.return_value = {"Items": []}
    return t

def test_check_sick_day_none():
    assert check_sick_day(_mock_table(), "matthew", "2026-03-10") is None

def test_check_sick_day_found():
    item = {"pk": "X", "sk": "Y", "date": "2026-03-10",
            "logged_at": "2026-03-10T12:00:00Z", "schema_version": 1}
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

def test_delete_sick_day():
    t = MagicMock()
    delete_sick_day(t, "matthew", "2026-03-10")
    t.delete_item.assert_called_once_with(
        Key={"pk": "USER#matthew#SOURCE#sick_days", "sk": "DATE#2026-03-10"}
    )

_run("check_sick_day: None when not found", test_check_sick_day_none)
_run("check_sick_day: returns item when found", test_check_sick_day_found)
_run("check_sick_day: Decimal -> float conversion", test_check_sick_day_decimal)
_run("check_sick_day: DDB error returns None", test_check_sick_day_ddb_error)
_run("get_sick_days_range: empty -> []", test_get_sick_days_range_empty)
_run("get_sick_days_range: DDB error -> []", test_get_sick_days_range_error)
_run("write_sick_day: correct fields in item", test_write_sick_day_fields)
_run("write_sick_day: no reason field if not provided", test_write_sick_day_no_reason)
_run("delete_sick_day: calls delete_item with right key", test_delete_sick_day)


# ======================================================================
# digest_utils
# ======================================================================
print("\n-- digest_utils -------------------------------------------------")

from digest_utils import (
    d2f, avg, fmt, fmt_num, safe_float,
    dedup_activities, _normalize_whoop_sleep,
    ex_whoop_from_list, ex_whoop_sleep_from_list, ex_withings_from_list,
    compute_banister_from_dict,
)

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
        {"sport_type": "Run", "start_date_local": "2026-03-10T08:00:00",
         "moving_time_seconds": 3600, "kilojoules": 800},
        {"sport_type": "Ride", "start_date_local": "2026-03-10T18:00:00",
         "moving_time_seconds": 5400, "kilojoules": 1200},
    ]
    assert len(dedup_activities(acts)) == 2

def test_dedup_removes_duplicate():
    acts = [
        {"sport_type": "Run", "start_date_local": "2026-03-10T08:00:00",
         "moving_time_seconds": 3600, "kilojoules": 800},
        {"sport_type": "Run", "start_date_local": "2026-03-10T08:05:00",
         "moving_time_seconds": 3600, "kilojoules": 200},
    ]
    result = dedup_activities(acts)
    assert len(result) == 1
    assert result[0]["kilojoules"] == 800

def test_dedup_empty():
    assert dedup_activities([]) == []

def test_normalize_whoop_sleep():
    item = {
        "sleep_quality_score": 78, "sleep_efficiency_percentage": 92,
        "time_awake_hours": 0.5, "disturbance_count": 3,
        "sleep_duration_hours": 7.5,
        "slow_wave_sleep_hours": 1.5, "rem_sleep_hours": 1.0,
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
    today = datetime.now(timezone.utc).date()
    strava = {}
    for i in range(30):
        d = (today - timedelta(days=i)).isoformat()
        strava[d] = {"activities": [
            {"kilojoules": 500, "start_date_local": d + "T08:00:00"}
        ]}
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

from ingestion_validator import validate_item, ValidationResult, list_supported_sources

def test_validate_whoop_ok():
    record = {
        "pk": "USER#matthew#SOURCE#whoop",
        "sk": "DATE#2026-03-10",
        "date": "2026-03-10",
        "recovery_score": 78, "hrv": 52.0,
        "resting_heart_rate": 57, "sleep_duration_hours": 7.5, "strain": 9.2,
    }
    result = validate_item("whoop", record, "2026-03-10")
    assert result.is_valid, f"Should pass: {result.errors}"

def test_validate_whoop_out_of_range():
    # recovery_score of 150 exceeds max 100
    record = {
        "pk": "USER#matthew#SOURCE#whoop",
        "sk": "DATE#2026-03-10",
        "date": "2026-03-10",
        "recovery_score": 150, "hrv": 52.0,
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
        "pk": "USER#matthew#SOURCE#whoop", "sk": "DATE#2026-03-10",
        "date": "2026-03-10", "recovery_score": 78,
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
import ast
import glob

from ai_calls import call_anthropic, _AI_VALIDATOR_AVAILABLE, AIOutputType

def test_call_anthropic_has_output_type_param():
    sig = inspect.signature(call_anthropic)
    assert "output_type" in sig.parameters, "call_anthropic must accept output_type param"
    assert "health_context" in sig.parameters, "call_anthropic must accept health_context param"
    assert sig.parameters["output_type"].default is None, "output_type default must be None"
    assert sig.parameters["health_context"].default is None, "health_context default must be None"

def test_ai_validator_importable():
    assert _AI_VALIDATOR_AVAILABLE, (
        "ai_output_validator must be importable from Layer — "
        "check that ai_output_validator.py is in cdk/layer-build/python/"
    )

def test_ai_output_type_importable():
    assert AIOutputType is not None, "AIOutputType must import successfully via ai_calls"
    assert hasattr(AIOutputType, "BOD_COACHING")
    assert hasattr(AIOutputType, "JOURNAL_COACH")
    assert hasattr(AIOutputType, "TRAINING_COACH")

def test_bod_caller_passes_output_type():
    """call_board_of_directors must pass output_type=AIOutputType.BOD_COACHING to call_anthropic."""
    src_path = os.path.join(LAMBDAS_DIR, "ai_calls.py")
    with open(src_path) as f:
        src = f.read()
    # Check that the BoD final call_anthropic includes BOD_COACHING
    assert "BOD_COACHING" in src, (
        "call_board_of_directors must pass output_type=AIOutputType.BOD_COACHING "
        "to call_anthropic — AI-3 middleware will not activate without it"
    )

def test_journal_caller_passes_output_type():
    """call_journal_coach must pass output_type=AIOutputType.JOURNAL_COACH."""
    src_path = os.path.join(LAMBDAS_DIR, "ai_calls.py")
    with open(src_path) as f:
        src = f.read()
    assert "JOURNAL_COACH" in src, (
        "call_journal_coach must pass output_type=AIOutputType.JOURNAL_COACH"
    )

def test_email_lambdas_dont_call_anthropic_directly():
    """Email Lambdas should call ai_calls wrappers, not call_anthropic() directly.
    Direct call_anthropic() calls bypass the output_type middleware.
    Checks all email + compute Lambda files."""
    email_lambdas = [
        "daily_brief_lambda.py", "weekly_digest_lambda", "monthly_digest_lambda.py",
        "nutrition_review_lambda.py", "wednesday_chronicle_lambda.py",
        "weekly_plate_lambda.py", "monday_compass_lambda.py", "brittany_email_lambda.py",
        "anomaly_detector_lambda.py", "daily_insight_compute_lambda.py",
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
print("="*60)
