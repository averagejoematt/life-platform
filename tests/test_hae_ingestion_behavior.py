#!/usr/bin/env python3
"""tests/test_hae_ingestion_behavior.py — behavioral contracts of the Health Auto
Export webhook ingest (`lambdas/ingestion/health_auto_export_lambda.py`).

Part of #1658 tranche 2. `tests/test_health_auto_export.py` already covers the
source-priority resolver and the weight-name aliases; this file covers the rest
of the module — the parts where a defect either **corrupts a stored day** or
**puts a fabricated number in front of a reader**:

  * timestamp → UTC partition-date conversion (TD-19: the whole cross-source
    aggregation depends on it),
  * CGM daily aggregation + the continuous-vs-fingerstick classifier (#483/D-3),
  * unit honoring for water / weight / distance (#483/D-9),
  * the DynamoDB merge: the monotonic activity guard, the reading-timestamp
    dedup map, and the validator gate,
  * the S3 archive writers' idempotent merge/dedup,
  * State of Mind + workout normalization,
  * the handler's auth ladder and its routing of a payload to those writers.

Every assertion is a caller-visible contract (a stored field value, a returned
count, a status code), never an implementation detail. No wall-clock arithmetic:
the one place `datetime.now` matters (the raw-archive S3 key, the
`webhook_ingested_at` stamp) is asserted structurally, not against "now".
"""

import json
import math
import os
import re
import sys
from decimal import Decimal

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LAMBDAS = os.path.join(ROOT, "lambdas")
if LAMBDAS not in sys.path:
    sys.path.insert(0, LAMBDAS)

os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("DYNAMODB_TABLE", "life-platform")
os.environ.setdefault("SECRET_NAME", "life-platform/ingestion-keys")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

_import_err = None
try:
    import health_auto_export_lambda as hae
except ImportError as _e:  # pragma: no cover — only when the bundle layout changes
    _import_err = _e
    hae = None  # type: ignore

if _import_err is not None:  # pragma: no cover
    pytestmark = pytest.mark.skip(reason=f"health_auto_export_lambda unavailable: {_import_err}")  # type: ignore


# ──────────────────────────────────────────────────────────────────────────────
# Test doubles
# ──────────────────────────────────────────────────────────────────────────────


class _NoSuchKey(Exception):
    """Stand-in for botocore's generated S3 NoSuchKey error class."""


class _S3Exceptions:
    NoSuchKey = _NoSuchKey


class FakeS3:
    """Minimal in-memory S3 with the one exception attribute the module catches.

    `objects` is keyed by S3 key and holds the decoded JSON body, so a test can
    seed "what is already archived" and then read back what the writer merged.
    """

    exceptions = _S3Exceptions()

    def __init__(self, objects=None, get_error=None):
        self.objects = dict(objects or {})
        self.puts = []
        self.get_error = get_error

    def get_object(self, Bucket=None, Key=None, **kwargs):
        if self.get_error is not None:
            raise self.get_error
        if Key not in self.objects:
            raise _NoSuchKey(f"no such key {Key}")
        return {"Body": _Body(json.dumps(self.objects[Key]))}

    def put_object(self, Bucket=None, Key=None, Body=None, ContentType=None, **kwargs):
        self.puts.append({"Bucket": Bucket, "Key": Key, "Body": Body, "ContentType": ContentType})
        self.objects[Key] = json.loads(Body)
        return {}


class _Body:
    def __init__(self, text):
        self._text = text

    def read(self):
        return self._text.encode("utf-8")


class FakeTable:
    """DynamoDB Table stand-in that records update_item calls and serves get_item.

    `stored` is the (already-merged) item the code reads back for the monotonic
    guard / dedup-map projections; `updates` is the raw kwargs log.
    """

    def __init__(self, stored=None, get_item_error=None):
        self.stored = dict(stored or {})
        self.updates = []
        self.get_item_error = get_item_error
        self.get_item_calls = []

    def get_item(self, Key=None, **kwargs):
        self.get_item_calls.append({"Key": Key, **kwargs})
        if self.get_item_error is not None:
            raise self.get_item_error
        return {"Item": dict(self.stored)} if self.stored else {}

    def update_item(self, **kwargs):
        self.updates.append(kwargs)
        return {}


def written_fields(update_kwargs):
    """Decode one update_item call into {attribute_name: written_value}.

    The module builds `SET #f0 = :v0, ...` with parallel name/value maps; a
    caller-visible contract is "field X ends up with value Y", so tests assert
    on this decoded view rather than on the placeholder numbering.
    """
    names = update_kwargs["ExpressionAttributeNames"]
    values = update_kwargs["ExpressionAttributeValues"]
    expr = update_kwargs["UpdateExpression"]
    assert expr.startswith("SET ")
    out = {}
    # Two clause shapes: `#f0 = :v0` and `#src = if_not_exists(#src, :src)`.
    # Splitting the whole expression on ", " would cut the latter in half, so
    # match clauses instead of splitting.
    for name_ph, plain_val, guarded_val in re.findall(
        r"(#[A-Za-z0-9]+) = (?:if_not_exists\(#[A-Za-z0-9]+, (:[A-Za-z0-9]+)\)|(:[A-Za-z0-9]+))", expr
    ):
        out[names[name_ph]] = values[plain_val or guarded_val]
    return out


def only_update(table):
    assert len(table.updates) == 1, f"expected exactly one update_item, got {len(table.updates)}"
    return written_fields(table.updates[0])


@pytest.fixture
def wired(monkeypatch):
    """Patch the module's AWS globals and hand back the doubles.

    Patched on the module object the tests themselves imported, so the code
    under test and the assertions look the name up in the same namespace.
    """
    s3 = FakeS3()
    table = FakeTable()
    monkeypatch.setattr(hae, "s3_client", s3)
    monkeypatch.setattr(hae, "table", table)
    return s3, table


# ──────────────────────────────────────────────────────────────────────────────
# floats_to_decimal — the DynamoDB write contract
# ──────────────────────────────────────────────────────────────────────────────


class TestFloatsToDecimal:
    def test_nan_and_inf_become_none_not_decimal_nan(self):
        """DynamoDB rejects Decimal('NaN'); a sensor NaN must become an absent
        value, never a stored one."""
        assert hae.floats_to_decimal(float("nan")) is None
        assert hae.floats_to_decimal(float("inf")) is None
        assert hae.floats_to_decimal(float("-inf")) is None

    def test_float_becomes_decimal_rounded_to_four_places(self):
        out = hae.floats_to_decimal(1.23456789)
        assert isinstance(out, Decimal)
        assert out == Decimal("1.2346")

    def test_decimal_is_exact_not_binary_float_repr(self):
        """Decimal(str(...)) not Decimal(float) — the latter stores 0.1 as
        0.1000000000000000055511151231257827."""
        assert hae.floats_to_decimal(0.1) == Decimal("0.1")

    def test_ints_bools_and_strings_pass_through_untouched(self):
        assert hae.floats_to_decimal(7) == 7
        assert hae.floats_to_decimal("dexcom_stelo") == "dexcom_stelo"
        assert hae.floats_to_decimal(None) is None

    def test_nested_dicts_and_lists_are_converted_recursively(self):
        out = hae.floats_to_decimal({"a": [1.5, {"b": 2.25}], "c": float("nan")})
        assert out == {"a": [Decimal("1.5"), {"b": Decimal("2.25")}], "c": None}


# ──────────────────────────────────────────────────────────────────────────────
# parse_date_str — TD-19: the partition key must be the UTC date
# ──────────────────────────────────────────────────────────────────────────────


class TestParseDateStr:
    def test_evening_pacific_timestamp_lands_on_the_next_utc_day(self):
        """TD-19: a 9pm PT event is the following UTC day. Every other source
        partitions by UTC; stripping the first 10 chars would silently split the
        same day across two partitions."""
        assert hae.parse_date_str("2026-05-02 21:00:00 -0700") == "2026-05-03"

    def test_morning_pacific_timestamp_stays_on_the_same_utc_day(self):
        assert hae.parse_date_str("2026-05-02 09:00:00 -0700") == "2026-05-02"

    def test_positive_offset_can_move_the_date_backwards(self):
        assert hae.parse_date_str("2026-05-03 06:00:00 +0900") == "2026-05-02"

    def test_colon_form_offset_is_accepted(self):
        assert hae.parse_date_str("2026-05-02 21:00:00 -07:00") == "2026-05-03"

    def test_date_only_string_is_returned_verbatim(self):
        assert hae.parse_date_str("2026-05-02") == "2026-05-02"

    def test_naive_timestamp_is_treated_as_utc(self):
        assert hae.parse_date_str("2026-05-02 23:30:00") == "2026-05-02"

    def test_empty_and_none_return_none_so_the_reading_is_dropped(self):
        assert hae.parse_date_str("") is None
        assert hae.parse_date_str(None) is None

    def test_unparseable_string_falls_back_to_the_first_ten_characters(self):
        """Deliberate fail-soft: a partial date beats dropping the reading."""
        assert hae.parse_date_str("2026-13-45 99:99:99 ZZZZ") == "2026-13-45"


# ──────────────────────────────────────────────────────────────────────────────
# CGM — classifier + daily aggregation
# ──────────────────────────────────────────────────────────────────────────────


def _cgm_reading(time_str, value):
    return {"time": time_str, "value": value}


class TestClassifyCgmSource:
    def test_five_minute_cadence_is_a_continuous_monitor(self):
        readings = [_cgm_reading(f"2026-05-02 08:{m:02d}:00 -0700", 100) for m in (0, 5, 10, 15)]
        assert hae._classify_cgm_source(readings, len(readings)) == "dexcom_stelo"

    def test_hours_apart_readings_are_manual_fingersticks(self):
        readings = [_cgm_reading(f"2026-05-02 {h:02d}:00:00 -0700", 100) for h in (8, 12, 18, 22)]
        assert hae._classify_cgm_source(readings, len(readings)) == "manual"

    def test_partial_stelo_day_under_twenty_readings_is_not_mislabeled_manual(self):
        """#483/D-3 regression: a UTC-truncated Stelo day carries <20 readings.
        The old count heuristic called that 'manual'; cadence must win."""
        readings = [_cgm_reading(f"2026-05-02 08:{m:02d}:00 -0700", 100) for m in range(0, 25, 5)]
        assert len(readings) < 20
        assert hae._classify_cgm_source(readings, len(readings)) == "dexcom_stelo"

    def test_boundary_median_gap_of_exactly_ten_minutes_is_continuous(self):
        readings = [_cgm_reading(f"2026-05-02 08:{m:02d}:00 -0700", 100) for m in (0, 10, 20, 30)]
        assert hae._classify_cgm_source(readings, len(readings)) == "dexcom_stelo"

    def test_too_few_timestamps_falls_back_to_the_count_heuristic(self):
        untimed = [{"time": None, "value": 100} for _ in range(30)]
        assert hae._classify_cgm_source(untimed, 30) == "dexcom_stelo"
        assert hae._classify_cgm_source(untimed[:2], 2) == "manual"

    def test_unparseable_timestamps_are_skipped_not_fatal(self):
        readings = [_cgm_reading("not-a-timestamp", 100) for _ in range(3)]
        assert hae._classify_cgm_source(readings, 3) == "manual"


class TestProcessBloodGlucose:
    def test_daily_aggregates_match_hand_computed_statistics(self):
        data = [{"date": f"2026-05-02 0{i}:00:00 +0000", "qty": v} for i, v in enumerate([90, 110, 130, 170])]
        agg, readings = hae.process_blood_glucose(data, "mg/dL")
        day = agg["2026-05-02"]
        assert day["blood_glucose_avg"] == 125.0  # (90+110+130+170)/4
        assert day["blood_glucose_min"] == 90.0
        assert day["blood_glucose_max"] == 170.0
        # population SD about mean 125: deviations -35/-15/+5/+45 → 3500/4
        assert day["blood_glucose_std_dev"] == round(math.sqrt(3500 / 4), 1)
        assert day["blood_glucose_readings_count"] == 4
        assert len(readings["2026-05-02"]) == 4

    def test_time_in_range_bands_use_the_documented_thresholds(self):
        """70-180 = ADA TIR, 70-120 = Attia optimal, <70 low, >140 high."""
        values = [65, 75, 125, 150, 190]
        data = [{"date": f"2026-05-02 0{i}:00:00 +0000", "qty": v} for i, v in enumerate(values)]
        day = hae.process_blood_glucose(data, "mg/dL")[0]["2026-05-02"]
        assert day["blood_glucose_time_in_range_pct"] == 60.0  # 75,125,150
        assert day["blood_glucose_time_in_optimal_pct"] == 20.0  # 75 only (125 > 120)
        assert day["blood_glucose_time_below_70_pct"] == 20.0  # 65
        assert day["blood_glucose_time_above_140_pct"] == 40.0  # 150,190

    def test_mmol_units_are_converted_to_mg_dl(self):
        data = [{"date": "2026-05-02 08:00:00 +0000", "qty": 5.5}]
        day = hae.process_blood_glucose(data, "mmol/L")[0]["2026-05-02"]
        assert day["blood_glucose_avg"] == round(5.5 * 18.0182, 1)

    def test_readings_without_a_date_or_quantity_are_dropped(self):
        data = [
            {"date": "2026-05-02 08:00:00 +0000", "qty": 100},
            {"date": "", "qty": 500},
            {"date": "2026-05-02 09:00:00 +0000", "qty": None},
        ]
        day = hae.process_blood_glucose(data, "mg/dL")[0]["2026-05-02"]
        assert day["blood_glucose_readings_count"] == 1
        assert day["blood_glucose_avg"] == 100.0

    def test_single_reading_reports_zero_standard_deviation(self):
        data = [{"date": "2026-05-02 08:00:00 +0000", "qty": 100}]
        assert hae.process_blood_glucose(data, "mg/dL")[0]["2026-05-02"]["blood_glucose_std_dev"] == 0

    def test_readings_split_across_utc_days_produce_two_partitions(self):
        data = [
            {"date": "2026-05-02 21:00:00 -0700", "qty": 100},  # → 05-03 UTC
            {"date": "2026-05-02 09:00:00 -0700", "qty": 120},  # → 05-02 UTC
        ]
        agg = hae.process_blood_glucose(data, "mg/dL")[0]
        assert set(agg) == {"2026-05-02", "2026-05-03"}

    def test_meal_time_defaults_to_unspecified_and_is_preserved_when_present(self):
        data = [
            {"date": "2026-05-02 08:00:00 +0000", "qty": 100},
            {"date": "2026-05-02 09:00:00 +0000", "qty": 100, "mealTime": "Before Meal"},
        ]
        readings = hae.process_blood_glucose(data, "mg/dL")[1]["2026-05-02"]
        assert [r["meal_time"] for r in readings] == ["Unspecified", "Before Meal"]

    def test_empty_input_returns_no_days(self):
        agg, readings = hae.process_blood_glucose([], "mg/dL")
        assert agg == {}
        assert dict(readings) == {}

    def test_flat_day_omits_variability_fields_rather_than_reporting_zero(self):
        """ADR-104: a day with no glycemic swing must not carry a fabricated
        MAGE. `glycemic.mage` returns None there and the field is omitted."""
        data = [{"date": f"2026-05-02 0{i}:00:00 +0000", "qty": 100} for i in range(5)]
        day = hae.process_blood_glucose(data, "mg/dL")[0]["2026-05-02"]
        assert "blood_glucose_mage" not in day
        assert day.get("blood_glucose_cv") in (0, 0.0, None) or "blood_glucose_cv" not in day


# ──────────────────────────────────────────────────────────────────────────────
# Unit honoring (#483/D-9)
# ──────────────────────────────────────────────────────────────────────────────


class TestWaterUnitFactor:
    @pytest.mark.parametrize("units", ["mL", "ml", "milliliters", "MILLILITRE"])
    def test_millilitre_variants_are_identity(self, units):
        assert hae._water_ml_factor(units) == 1.0

    @pytest.mark.parametrize("units", ["L", "liters", "litre"])
    def test_litre_variants_scale_by_one_thousand(self, units):
        assert hae._water_ml_factor(units) == 1000.0

    @pytest.mark.parametrize("units", ["fl_oz_us", "fl oz", "ounces", "oz"])
    def test_fluid_ounce_variants_use_the_us_fluid_ounce(self, units):
        assert hae._water_ml_factor(units) == 29.5735

    def test_missing_units_keep_the_historical_fluid_ounce_default(self):
        assert hae._water_ml_factor("") == 29.5735
        assert hae._water_ml_factor(None) == 29.5735

    def test_unknown_unit_falls_back_to_fluid_ounces(self):
        assert hae._water_ml_factor("cups") == 29.5735


class TestGenericMetricUnitConversion:
    def _metric(self, name, units, readings):
        return {"name": name, "units": units, "data": readings}

    def test_water_in_millilitres_is_not_multiplied_by_the_ounce_factor(self):
        """#483/D-9 regression: a mL-reporting app used to be ×29.5735'd."""
        metrics = [self._metric("dietary_water", "mL", [{"date": "2026-05-02", "qty": 500, "source": "My Water"}])]
        daily = hae.process_generic_metrics(metrics)[0]
        assert daily["2026-05-02"]["water_intake_ml"] == 500

    def test_water_in_fluid_ounces_is_converted_to_millilitres(self):
        metrics = [self._metric("dietary_water", "fl_oz_us", [{"date": "2026-05-02", "qty": 8, "source": "My Water"}])]
        daily = hae.process_generic_metrics(metrics)[0]
        assert daily["2026-05-02"]["water_intake_ml"] == round(8 * 29.5735)

    def test_water_raw_field_is_never_persisted_only_the_millilitre_field(self):
        metrics = [self._metric("dietary_water", "mL", [{"date": "2026-05-02", "qty": 500, "source": "My Water"}])]
        fields = hae.process_generic_metrics(metrics)[0]["2026-05-02"]
        assert "water_intake_raw" not in fields

    def test_water_dedup_timestamps_are_carried_onto_the_millilitre_field(self):
        metrics = [
            self._metric(
                "dietary_water",
                "fl_oz_us",
                [
                    {"date": "2026-05-02 08:00:00 +0000", "qty": 8, "source": "My Water"},
                    {"date": "2026-05-02 09:00:00 +0000", "qty": 8, "source": "My Water"},
                ],
            )
        ]
        _, timestamps, _ = hae.process_generic_metrics(metrics)
        day_ts = timestamps["2026-05-02"]
        assert "water_intake_raw" not in day_ts
        assert set(day_ts["water_intake_ml"].values()) == {round(8 * 29.5735)}

    def test_weight_tagged_kilograms_is_converted_to_pounds(self):
        metrics = [self._metric("body_mass", "kg", [{"date": "2026-05-02", "qty": 100, "source": "Withings"}])]
        daily = hae.process_generic_metrics(metrics)[0]
        assert daily["2026-05-02"]["weight_lbs"] == round(100 * 2.20462, 2)

    def test_weight_tagged_pounds_is_left_alone(self):
        metrics = [self._metric("body_mass", "lb", [{"date": "2026-05-02", "qty": 220, "source": "Withings"}])]
        assert hae.process_generic_metrics(metrics)[0]["2026-05-02"]["weight_lbs"] == 220

    def test_distance_tagged_kilometres_is_converted_to_miles(self):
        metrics = [self._metric("cycling_distance", "km", [{"date": "2026-05-02", "qty": 10, "source": "Matt 17"}])]
        daily = hae.process_generic_metrics(metrics)[0]
        assert daily["2026-05-02"]["distance_cycling_miles"] == round(10 * 0.621371, 4)

    def test_distance_tagged_metres_is_converted_to_miles(self):
        metrics = [self._metric("swimming_distance", "m", [{"date": "2026-05-02", "qty": 1500, "source": "Matt 17"}])]
        daily = hae.process_generic_metrics(metrics)[0]
        assert daily["2026-05-02"]["distance_swimming_miles"] == round(1500 * 0.000621371, 4)


class TestGenericMetricAggregation:
    def test_total_calories_burned_is_derived_only_when_both_halves_exist(self):
        both = [
            {"name": "active_energy", "units": "kcal", "data": [{"date": "2026-05-02", "qty": 500, "source": "Matt 17"}]},
            {"name": "basal_energy_burned", "units": "kcal", "data": [{"date": "2026-05-02", "qty": 1800, "source": "Matt 17"}]},
        ]
        assert hae.process_generic_metrics(both)[0]["2026-05-02"]["total_calories_burned"] == 2300

        active_only = both[:1]
        assert "total_calories_burned" not in hae.process_generic_metrics(active_only)[0]["2026-05-02"]

    def test_tier_two_metric_drops_non_apple_sources(self):
        """Whoop mirrors HRV into HealthKit; keeping it would pollute the
        Apple cross-reference field with the SOT's own numbers."""
        metrics = [
            {
                "name": "heart_rate_variability",
                "units": "ms",
                "data": [
                    {"date": "2026-05-02", "qty": 40, "source": "Apple Watch"},
                    {"date": "2026-05-02", "qty": 999, "source": "Whoop"},
                ],
            }
        ]
        assert hae.process_generic_metrics(metrics)[0]["2026-05-02"]["hrv_sdnn_apple"] == 40

    def test_heart_rate_uses_the_avg_field_of_the_min_avg_max_triple(self):
        metrics = [
            {
                "name": "heart_rate",
                "units": "bpm",
                "data": [{"date": "2026-05-02", "Min": 50, "Avg": 72, "Max": 160, "source": "Apple Watch"}],
            }
        ]
        assert hae.process_generic_metrics(metrics)[0]["2026-05-02"]["heart_rate_apple"] == 72

    def test_skip_metrics_never_produce_a_field(self):
        """Nutrition/sleep have their own SOT pipeline; ingesting the HealthKit
        mirror would double-count."""
        metrics = [{"name": "protein", "units": "g", "data": [{"date": "2026-05-02", "qty": 200, "source": "MacroFactor"}]}]
        assert hae.process_generic_metrics(metrics)[0] == {}

    def test_unmapped_metric_names_are_ignored_without_raising(self):
        metrics = [{"name": "Some Future HealthKit Metric", "units": "x", "data": [{"date": "2026-05-02", "qty": 1}]}]
        assert hae.process_generic_metrics(metrics)[0] == {}

    def test_non_numeric_quantities_are_skipped_not_fatal(self):
        metrics = [
            {
                "name": "step_count",
                "units": "count",
                "data": [
                    {"date": "2026-05-02", "qty": "not-a-number", "source": "Matt 17"},
                    {"date": "2026-05-02", "qty": 1000, "source": "Matt 17"},
                ],
            }
        ]
        assert hae.process_generic_metrics(metrics)[0]["2026-05-02"]["steps"] == 1000

    def test_activity_max_rule_keeps_the_fuller_device_and_audits_the_rejection(self):
        """The "402 steps when the app shows 6,500" bug: watch-without-phone days
        must keep the larger per-source total, and neither sum nor priority."""
        metrics = [
            {
                "name": "step_count",
                "units": "count",
                "data": [
                    {"date": "2026-05-02", "qty": 402, "source": "Matt 17"},
                    {"date": "2026-05-02", "qty": 6500, "source": "Apple Watch"},
                ],
            }
        ]
        daily, _, audit = hae.process_generic_metrics(metrics)
        assert daily["2026-05-02"]["steps"] == 6500
        assert audit["2026-05-02"]["steps"]["chosen"] == "Apple Watch"
        assert audit["2026-05-02"]["steps"]["rejected"] == ["Matt 17"]
        assert audit["2026-05-02"]["steps"]["rule"] == "max_sum"

    def test_activity_max_rule_sums_within_a_source_before_comparing(self):
        metrics = [
            {
                "name": "step_count",
                "units": "count",
                "data": [
                    {"date": "2026-05-02", "qty": 3000, "source": "Matt 17"},
                    {"date": "2026-05-02", "qty": 3000, "source": "Matt 17"},
                    {"date": "2026-05-02", "qty": 5000, "source": "Apple Watch"},
                ],
            }
        ]
        assert hae.process_generic_metrics(metrics)[0]["2026-05-02"]["steps"] == 6000

    def test_a_single_source_day_records_no_dedup_audit_entry(self):
        metrics = [{"name": "step_count", "units": "count", "data": [{"date": "2026-05-02", "qty": 5000, "source": "Matt 17"}]}]
        assert hae.process_generic_metrics(metrics)[0]["2026-05-02"]["steps"] == 5000
        assert hae.process_generic_metrics(metrics)[2] == {}

    def test_readings_with_no_source_are_bucketed_not_dropped(self):
        metrics = [{"name": "flights_climbed", "units": "count", "data": [{"date": "2026-05-02", "qty": 12}]}]
        assert hae.process_generic_metrics(metrics)[0]["2026-05-02"]["flights_climbed"] == 12

    def test_avg_metrics_average_rather_than_sum(self):
        metrics = [
            {
                "name": "walking_speed",
                "units": "mph",
                "data": [
                    {"date": "2026-05-02", "qty": 3.0, "source": "Apple Watch"},
                    {"date": "2026-05-02", "qty": 4.0, "source": "Apple Watch"},
                ],
            }
        ]
        assert hae.process_generic_metrics(metrics)[0]["2026-05-02"]["walking_speed_mph"] == 3.5


# ──────────────────────────────────────────────────────────────────────────────
# merge_day_to_dynamo — the single write gate
# ──────────────────────────────────────────────────────────────────────────────


class TestMergeDayToDynamo:
    def test_empty_field_dict_writes_nothing(self, wired):
        _, table = wired
        hae.merge_day_to_dynamo("2026-05-02", {})
        assert table.updates == []

    def test_fields_are_written_under_the_apple_health_partition_and_date_sort_key(self, wired):
        _, table = wired
        hae.merge_day_to_dynamo("2026-05-02", {"steps": 5000}, monotonic_guard=False)
        assert table.updates[0]["Key"] == {"pk": hae.PK, "sk": "DATE#2026-05-02"}
        assert hae.PK.endswith("SOURCE#apple_health")

    def test_none_valued_fields_are_omitted_rather_than_written_as_null(self, wired):
        _, table = wired
        hae.merge_day_to_dynamo("2026-05-02", {"steps": 5000, "vo2max": None}, monotonic_guard=False)
        assert "vo2max" not in only_update(table)

    def test_a_write_of_only_none_values_is_suppressed_entirely(self, wired):
        _, table = wired
        hae.merge_day_to_dynamo("2026-05-02", {"vo2max": None}, monotonic_guard=False)
        assert table.updates == []

    def test_every_write_stamps_source_date_and_ingested_at(self, wired):
        _, table = wired
        hae.merge_day_to_dynamo("2026-05-02", {"steps": 5000}, monotonic_guard=False)
        w = only_update(table)
        assert w["source"] == "apple_health"
        assert w["date"] == "2026-05-02"
        assert w["webhook_ingested_at"].startswith("20") and w["webhook_ingested_at"].endswith("+00:00")

    def test_identity_fields_use_if_not_exists_so_a_backfill_tag_survives(self, wired):
        _, table = wired
        hae.merge_day_to_dynamo("2026-05-02", {"steps": 5000}, monotonic_guard=False)
        expr = table.updates[0]["UpdateExpression"]
        assert "if_not_exists(#src, :src)" in expr
        assert "if_not_exists(#dt, :dt)" in expr

    def test_floats_are_decimalised_before_reaching_dynamodb(self, wired):
        _, table = wired
        hae.merge_day_to_dynamo("2026-05-02", {"walking_speed_mph": 3.25}, monotonic_guard=False)
        assert only_update(table)["walking_speed_mph"] == Decimal("3.25")

    def test_water_ounces_are_derived_from_the_deduped_millilitre_total(self, wired):
        _, table = wired
        hae.merge_day_to_dynamo("2026-05-02", {"water_intake_ml": 2000}, monotonic_guard=False)
        assert only_update(table)["water_intake_oz"] == Decimal(str(round(2000 / 29.5735, 1)))

    # ── monotonic guard ──

    def test_monotonic_guard_keeps_the_larger_stored_activity_total(self, wired):
        """A later PARTIAL export must never lower a fuller stored count."""
        _, table = wired
        table.stored = {"steps": Decimal("9000")}
        hae.merge_day_to_dynamo("2026-05-02", {"steps": 402}, monotonic_guard=True)
        assert only_update(table)["steps"] == Decimal("9000")

    def test_monotonic_guard_accepts_a_larger_new_activity_total(self, wired):
        _, table = wired
        table.stored = {"steps": Decimal("400")}
        hae.merge_day_to_dynamo("2026-05-02", {"steps": 9000}, monotonic_guard=True)
        assert only_update(table)["steps"] == Decimal("9000")

    def test_monotonic_guard_only_projects_the_activity_fields_it_guards(self, wired):
        _, table = wired
        table.stored = {"steps": Decimal("100")}
        hae.merge_day_to_dynamo("2026-05-02", {"steps": 1, "vo2max": 50}, monotonic_guard=True)
        projected = set(table.get_item_calls[0]["ExpressionAttributeNames"].values())
        assert projected == {"steps"}

    def test_monotonic_guard_does_not_protect_non_activity_fields(self, wired):
        """Weight and VO2max legitimately go down; only additive counters are
        guarded."""
        _, table = wired
        table.stored = {"weight_lbs": Decimal("330")}
        hae.merge_day_to_dynamo("2026-05-02", {"weight_lbs": 320}, monotonic_guard=True)
        assert only_update(table)["weight_lbs"] == Decimal("320")

    def test_backfill_path_disables_the_guard_and_writes_authoritatively(self, wired):
        _, table = wired
        table.stored = {"steps": Decimal("9000")}
        hae.merge_day_to_dynamo("2026-05-02", {"steps": 402}, monotonic_guard=False)
        assert table.get_item_calls == []
        assert only_update(table)["steps"] == Decimal("402")

    def test_a_failed_guard_read_still_writes_the_new_value(self, wired):
        """Fail-soft: a throttled projection read must not drop the ingest."""
        _, table = wired
        table.get_item_error = RuntimeError("throttled")
        hae.merge_day_to_dynamo("2026-05-02", {"steps": 402}, monotonic_guard=True)
        assert only_update(table)["steps"] == Decimal("402")

    def test_guard_read_is_skipped_when_no_guarded_field_is_present(self, wired):
        _, table = wired
        hae.merge_day_to_dynamo("2026-05-02", {"vo2max": 50}, monotonic_guard=True)
        assert table.get_item_calls == []

    # ── reading-timestamp dedup ──

    def test_resent_readings_are_not_double_counted(self, wired):
        """The dedup map is keyed by reading timestamp, so a full-day re-send
        after an incremental sync recomputes the same total."""
        _, table = wired
        table.stored = {"_rd_water_intake_ml": {"08:00": Decimal("240"), "09:00": Decimal("240")}}
        ts = {"water_intake_ml": {"08:00": 240, "09:00": 240, "10:00": 240}}
        hae.merge_day_to_dynamo("2026-05-02", {"water_intake_ml": 240}, reading_timestamps=ts, monotonic_guard=False)
        assert only_update(table)["water_intake_ml"] == Decimal("720")

    def test_the_stored_reading_map_wins_on_a_timestamp_collision(self, wired):
        """Existing keys are never overwritten — a re-send with a different
        quantity at the same timestamp must not silently rewrite history."""
        _, table = wired
        table.stored = {"_rd_water_intake_ml": {"08:00": Decimal("240")}}
        ts = {"water_intake_ml": {"08:00": 999}}
        hae.merge_day_to_dynamo("2026-05-02", {"water_intake_ml": 999}, reading_timestamps=ts, monotonic_guard=False)
        assert only_update(table)["water_intake_ml"] == Decimal("240")

    def test_the_merged_reading_map_is_persisted_for_the_next_sync(self, wired):
        _, table = wired
        table.stored = {"_rd_caffeine_mg": {"08:00": Decimal("95")}}
        ts = {"caffeine_mg": {"12:00": 95}}
        hae.merge_day_to_dynamo("2026-05-02", {"caffeine_mg": 95}, reading_timestamps=ts, monotonic_guard=False)
        stored_map = only_update(table)["_rd_caffeine_mg"]
        assert set(stored_map) == {"08:00", "12:00"}
        # boto3 rejects Python floats outright — every value in the persisted map
        # must already be Decimal (or int), never float.
        assert not any(isinstance(v, float) for v in stored_map.values())
        assert stored_map["08:00"] == Decimal("95")

    def test_first_ever_sync_with_no_stored_map_totals_the_new_readings(self, wired):
        _, table = wired
        ts = {"water_intake_ml": {"08:00": 240, "09:00": 500}}
        hae.merge_day_to_dynamo("2026-05-02", {"water_intake_ml": 0}, reading_timestamps=ts, monotonic_guard=False)
        assert only_update(table)["water_intake_ml"] == Decimal("740")

    def test_a_failed_dedup_read_falls_back_to_the_full_write(self, wired):
        _, table = wired
        table.get_item_error = RuntimeError("throttled")
        ts = {"water_intake_ml": {"08:00": 240}}
        hae.merge_day_to_dynamo("2026-05-02", {"water_intake_ml": 240}, reading_timestamps=ts, monotonic_guard=False)
        assert only_update(table)["water_intake_ml"] == Decimal("240")

    # ── the validator gate (#483/X-3) ──

    def test_a_hard_bound_violation_drops_the_whole_day_merge(self, wired):
        _, table = wired
        hae.merge_day_to_dynamo("2026-05-02", {"blood_glucose_avg": 5000, "steps": 5000}, monotonic_guard=False)
        assert table.updates == []

    def test_a_merely_unusual_value_is_warned_about_but_still_written(self, wired):
        _, table = wired
        hae.merge_day_to_dynamo("2026-05-02", {"blood_pressure_diastolic": 210}, monotonic_guard=False)
        assert only_update(table)["blood_pressure_diastolic"] == 210


# ──────────────────────────────────────────────────────────────────────────────
# S3 archive writers — idempotent merge
# ──────────────────────────────────────────────────────────────────────────────


class TestS3ArchiveWriters:
    def test_cgm_readings_land_on_the_registered_raw_layout(self, wired):
        s3, _ = wired
        hae.save_cgm_readings_to_s3("2026-05-02", [{"time": "t1", "value": 100}])
        assert s3.puts[0]["Key"] == f"raw/{hae.USER_ID}/cgm_readings/2026/05/02.json"
        assert s3.puts[0]["ContentType"] == "application/json"

    def test_cgm_writer_returns_the_count_of_genuinely_new_readings(self, wired):
        s3, _ = wired
        s3.objects[f"raw/{hae.USER_ID}/cgm_readings/2026/05/02.json"] = [{"time": "t1", "value": 100}]
        n = hae.save_cgm_readings_to_s3("2026-05-02", [{"time": "t1", "value": 100}, {"time": "t2", "value": 110}])
        assert n == 1

    def test_cgm_writer_merges_rather_than_replacing_the_stored_day(self, wired):
        s3, _ = wired
        key = f"raw/{hae.USER_ID}/cgm_readings/2026/05/02.json"
        s3.objects[key] = [{"time": "t2", "value": 110}]
        hae.save_cgm_readings_to_s3("2026-05-02", [{"time": "t1", "value": 100}])
        assert [r["time"] for r in s3.objects[key]] == ["t1", "t2"]

    def test_a_fully_duplicate_resend_writes_nothing(self, wired):
        s3, _ = wired
        key = f"raw/{hae.USER_ID}/cgm_readings/2026/05/02.json"
        s3.objects[key] = [{"time": "t1", "value": 100}]
        assert hae.save_cgm_readings_to_s3("2026-05-02", [{"time": "t1", "value": 100}]) == 0
        assert s3.puts == []

    def test_an_unreadable_existing_object_does_not_lose_the_new_readings(self, wired):
        """Fail-soft on a transient S3 error — the ingest still archives."""
        s3, _ = wired
        s3.get_error = RuntimeError("500 from S3")
        assert hae.save_cgm_readings_to_s3("2026-05-02", [{"time": "t1", "value": 100}]) == 1

    def test_bp_readings_land_on_the_blood_pressure_prefix_and_dedup_by_time(self, wired):
        s3, _ = wired
        key = f"raw/{hae.USER_ID}/blood_pressure/2026/05/02.json"
        s3.objects[key] = [{"time": "t1", "systolic": 120}]
        n = hae.save_bp_readings_to_s3("2026-05-02", [{"time": "t1", "systolic": 120}, {"time": "t2", "systolic": 118}])
        assert n == 1
        assert [r["time"] for r in s3.objects[key]] == ["t1", "t2"]

    def test_state_of_mind_entries_land_on_their_own_prefix_and_dedup_by_time(self, wired):
        s3, _ = wired
        key = f"raw/{hae.USER_ID}/state_of_mind/2026/05/02.json"
        s3.objects[key] = [{"time": "t1", "valence": 0.5}]
        n = hae.save_state_of_mind_to_s3("2026-05-02", [{"time": "t1", "valence": 0.5}, {"time": "t2", "valence": -0.2}])
        assert n == 1
        assert len(s3.objects[key]) == 2

    def test_workouts_dedup_by_id_not_by_timestamp(self, wired):
        s3, _ = wired
        key = f"raw/{hae.USER_ID}/workouts/2026/05/02.json"
        s3.objects[key] = [{"id": "w1", "start": "2026-05-02 08:00:00 +0000"}]
        n = hae.save_workouts_to_s3(
            "2026-05-02",
            [{"id": "w1", "start": "2026-05-02 08:00:00 +0000"}, {"id": "w2", "start": "2026-05-02 07:00:00 +0000"}],
        )
        assert n == 1
        assert [w["id"] for w in s3.objects[key]] == ["w2", "w1"]  # re-sorted by start

    def test_raw_payload_archive_key_carries_the_user_segment_and_hae_prefix(self, wired):
        s3, _ = wired
        key = hae.save_raw_payload({"data": {"metrics": []}})
        assert key.startswith(f"raw/{hae.USER_ID}/health_auto_export/")
        assert key.endswith(".json")
        assert s3.puts[0]["Key"] == key

    def test_raw_payload_is_archived_verbatim(self, wired):
        s3, _ = wired
        payload = {"data": {"metrics": [{"name": "step_count"}]}}
        key = hae.save_raw_payload(payload)
        assert s3.objects[key] == payload


# ──────────────────────────────────────────────────────────────────────────────
# State of Mind
# ──────────────────────────────────────────────────────────────────────────────


class TestProcessStateOfMind:
    def test_a_normal_metrics_payload_is_not_mistaken_for_state_of_mind(self):
        entries, agg = hae.process_state_of_mind({"data": {"metrics": [{"name": "step_count", "data": []}]}})
        assert entries == {} and agg == {}

    @pytest.mark.parametrize("key", ["stateOfMind", "state_of_mind", "entries", "samples"])
    def test_each_supported_container_key_is_detected(self, key):
        payload = {"data": {key: [{"date": "2026-05-02 08:00:00 +0000", "valence": 0.5}]}}
        entries, _ = hae.process_state_of_mind(payload)
        assert len(entries["2026-05-02"]) == 1

    def test_a_bare_list_payload_is_accepted(self):
        entries, _ = hae.process_state_of_mind([{"date": "2026-05-02 08:00:00 +0000", "valence": 0.5}])
        assert len(entries["2026-05-02"]) == 1

    def test_an_entry_with_no_mood_value_is_dropped(self):
        entries, _ = hae.process_state_of_mind([{"date": "2026-05-02 08:00:00 +0000", "labels": ["Happy"]}])
        assert entries == {}

    def test_healthkit_seven_point_classification_maps_onto_the_valence_axis(self):
        """1 → -1.0, 4 → 0.0, 7 → +1.0."""
        for vc, expected in ((1, -1.0), (4, 0.0), (7, 1.0)):
            entries, _ = hae.process_state_of_mind([{"date": "2026-05-02 08:00:00 +0000", "valenceClassification": vc}])
            assert entries["2026-05-02"][0]["valence"] == expected

    def test_an_integer_classification_is_rendered_as_its_healthkit_name(self):
        entries, _ = hae.process_state_of_mind([{"date": "2026-05-02 08:00:00 +0000", "valenceClassification": 6}])
        assert entries["2026-05-02"][0]["valence_classification"] == "pleasant"

    def test_a_string_classification_is_preserved_verbatim(self):
        entries, _ = hae.process_state_of_mind(
            [{"date": "2026-05-02 08:00:00 +0000", "valence": 0.9, "valenceClassification": "veryPleasant"}]
        )
        assert entries["2026-05-02"][0]["valence_classification"] == "veryPleasant"

    @pytest.mark.parametrize(
        "valence,expected",
        [
            (-0.9, "veryUnpleasant"),
            (-0.5, "unpleasant"),
            (-0.2, "slightlyUnpleasant"),
            (0.0, "neutral"),
            (0.2, "slightlyPleasant"),
            (0.5, "pleasant"),
            (0.9, "veryPleasant"),
        ],
    )
    def test_classification_is_derived_from_valence_when_absent(self, valence, expected):
        entries, _ = hae.process_state_of_mind([{"date": "2026-05-02 08:00:00 +0000", "valence": valence}])
        assert entries["2026-05-02"][0]["valence_classification"] == expected

    @pytest.mark.parametrize("kind,normalized", [("dailyMood", "dailyMood"), ("momentary_emotion", "momentaryEmotion")])
    def test_kind_is_normalized_to_the_two_healthkit_forms(self, kind, normalized):
        entries, _ = hae.process_state_of_mind([{"date": "2026-05-02 08:00:00 +0000", "valence": 0.1, "kind": kind}])
        assert entries["2026-05-02"][0]["kind"] == normalized

    def test_a_scalar_label_is_normalized_to_a_list(self):
        entries, _ = hae.process_state_of_mind(
            [{"date": "2026-05-02 08:00:00 +0000", "valence": 0.1, "labels": "Happy", "associations": "Work"}]
        )
        entry = entries["2026-05-02"][0]
        assert entry["labels"] == ["Happy"]
        assert entry["associations"] == ["Work"]

    def test_daily_aggregate_reports_valence_spread_and_check_in_split(self):
        payload = [
            {"date": "2026-05-02 08:00:00 +0000", "valence": 0.6, "kind": "dailyMood", "labels": ["Calm"]},
            {"date": "2026-05-02 12:00:00 +0000", "valence": -0.2, "kind": "momentaryEmotion", "labels": ["Stressed", "Calm"]},
        ]
        agg = hae.process_state_of_mind(payload)[1]["2026-05-02"]
        assert agg["som_avg_valence"] == 0.2
        assert agg["som_min_valence"] == -0.2
        assert agg["som_max_valence"] == 0.6
        assert agg["som_check_in_count"] == 2
        assert agg["som_mood_count"] == 1
        assert agg["som_emotion_count"] == 1
        assert agg["som_top_labels"].split(", ")[0] == "Calm"

    def test_top_labels_are_capped_at_three(self):
        payload = [
            {"date": "2026-05-02 08:00:00 +0000", "valence": 0.1, "labels": ["A", "B", "C", "D", "E"]},
        ]
        agg = hae.process_state_of_mind(payload)[1]["2026-05-02"]
        assert len(agg["som_top_labels"].split(", ")) == 3

    def test_absent_labels_are_reported_as_none_not_an_empty_string(self):
        """ADR-104: no labels logged is an absence, not an empty label set."""
        agg = hae.process_state_of_mind([{"date": "2026-05-02 08:00:00 +0000", "valence": 0.1}])[1]["2026-05-02"]
        assert agg["som_top_labels"] is None
        assert agg["som_top_associations"] is None

    def test_entries_are_partitioned_by_utc_date_like_every_other_source(self):
        entries, _ = hae.process_state_of_mind(
            [
                {"date": "2026-05-02 21:00:00 -0700", "valence": 0.1},
                {"date": "2026-05-02 09:00:00 -0700", "valence": 0.1},
            ]
        )
        assert set(entries) == {"2026-05-02", "2026-05-03"}

    def test_non_dict_members_are_skipped(self):
        entries, _ = hae.process_state_of_mind(["junk", {"date": "2026-05-02 08:00:00 +0000", "valence": 0.1}])
        assert len(entries["2026-05-02"]) == 1


# ──────────────────────────────────────────────────────────────────────────────
# Workouts
# ──────────────────────────────────────────────────────────────────────────────


def _workout(name, minutes, wid="w1", date="2026-05-02 08:00:00 +0000"):
    return {"id": wid, "name": name, "start": date, "end": date, "duration": minutes * 60}


class TestProcessWorkouts:
    def test_recovery_categories_come_from_the_registry_not_a_literal(self):
        """Guard the SET: every name registered in RECOVERY_WORKOUT_TYPES must
        classify to its registered category, so adding a modality to the map
        cannot silently leave the classifier behind."""
        workouts = [_workout(name, 10, wid=f"w{i}") for i, name in enumerate(hae.RECOVERY_WORKOUT_TYPES)]
        daily, _ = hae.process_workouts(workouts)
        got = {w["name"]: w["category"] for w in daily["2026-05-02"]}
        assert got == dict(hae.RECOVERY_WORKOUT_TYPES)
        assert all(w["is_recovery_type"] for w in daily["2026-05-02"])

    def test_an_unregistered_workout_type_is_other_and_not_a_recovery_type(self):
        daily, agg = hae.process_workouts([_workout("Traditional Strength Training", 45)])
        assert daily["2026-05-02"][0]["category"] == "other"
        assert daily["2026-05-02"][0]["is_recovery_type"] is False
        assert agg == {}

    def test_non_recovery_workouts_are_archived_but_never_aggregated_to_dynamo(self):
        """Strava is SOT for strength/cardio; aggregating here double-counts."""
        daily, agg = hae.process_workouts([_workout("Running", 30, wid="w1"), _workout("Yoga", 20, wid="w2")])
        assert len(daily["2026-05-02"]) == 2
        assert agg["2026-05-02"]["recovery_workout_minutes"] == 20
        assert agg["2026-05-02"]["recovery_workout_sessions"] == 1

    def test_duration_is_converted_from_seconds_to_minutes(self):
        daily, _ = hae.process_workouts([{"id": "w1", "name": "Yoga", "start": "2026-05-02", "duration": 930}])
        assert daily["2026-05-02"][0]["duration_min"] == 15.5

    def test_a_non_numeric_duration_degrades_to_zero_rather_than_raising(self):
        daily, _ = hae.process_workouts([{"id": "w1", "name": "Yoga", "start": "2026-05-02", "duration": "n/a"}])
        assert daily["2026-05-02"][0]["duration_min"] == 0.0

    def test_active_energy_prefers_the_summary_quantity(self):
        w = _workout("Yoga", 20)
        w["activeEnergyBurned"] = {"qty": 88.25, "units": "kcal"}
        w["activeEnergy"] = [{"qty": 1}, {"qty": 1}]
        daily, _ = hae.process_workouts([w])
        assert daily["2026-05-02"][0]["active_energy_kcal"] == 88.2

    def test_active_energy_falls_back_to_summing_the_reading_series(self):
        w = _workout("Yoga", 20)
        w["activeEnergy"] = [{"qty": 10.5}, {"qty": 4.25}]
        daily, _ = hae.process_workouts([w])
        assert daily["2026-05-02"][0]["active_energy_kcal"] == 14.8

    def test_missing_energy_reports_zero_kcal(self):
        daily, _ = hae.process_workouts([_workout("Yoga", 20)])
        assert daily["2026-05-02"][0]["active_energy_kcal"] == 0

    def test_same_category_sessions_are_summed_and_counted(self):
        workouts = [_workout("Flexibility", 10, wid="w1"), _workout("Flexibility", 15, wid="w2")]
        agg = hae.process_workouts(workouts)[1]["2026-05-02"]
        assert agg["flexibility_minutes"] == 25
        assert agg["flexibility_sessions"] == 2

    def test_breathwork_aliases_collapse_onto_one_category(self):
        workouts = [_workout("Breathing", 5, wid="w1"), _workout("Mind and Body", 7, wid="w2")]
        agg = hae.process_workouts(workouts)[1]["2026-05-02"]
        assert agg["breathwork_minutes"] == 12
        assert agg["breathwork_sessions"] == 2

    def test_recovery_types_string_is_deduplicated_and_sorted(self):
        workouts = [_workout("Yoga", 10, wid="w1"), _workout("Flexibility", 10, wid="w2"), _workout("Yoga", 10, wid="w3")]
        agg = hae.process_workouts(workouts)[1]["2026-05-02"]
        assert agg["recovery_workout_types"] == "flexibility, yoga"

    def test_recovery_total_spans_every_category(self):
        workouts = [_workout("Yoga", 10, wid="w1"), _workout("Breathing", 5, wid="w2"), _workout("Pilates", 20, wid="w3")]
        agg = hae.process_workouts(workouts)[1]["2026-05-02"]
        assert agg["recovery_workout_minutes"] == 35
        assert agg["recovery_workout_sessions"] == 3

    def test_a_workout_with_no_start_is_dropped(self):
        daily, _ = hae.process_workouts([{"id": "w1", "name": "Yoga", "duration": 600}])
        assert dict(daily) == {}

    def test_workouts_are_partitioned_by_utc_start_date(self):
        workouts = [
            _workout("Yoga", 10, wid="w1", date="2026-05-02 21:00:00 -0700"),
            _workout("Yoga", 10, wid="w2", date="2026-05-02 09:00:00 -0700"),
        ]
        daily, agg = hae.process_workouts(workouts)
        assert set(daily) == {"2026-05-02", "2026-05-03"}
        assert set(agg) == {"2026-05-02", "2026-05-03"}


# ──────────────────────────────────────────────────────────────────────────────
# lambda_handler — auth ladder + routing
# ──────────────────────────────────────────────────────────────────────────────


# The bearer the fake secret store hands back; not a real credential.
_VALID_BEARER = "test-bearer-value"


class _Ctx:
    aws_request_id = "req-123"


def _event(payload, bearer=_VALID_BEARER, is_b64=False, raw_body=None):
    body = raw_body if raw_body is not None else json.dumps(payload)
    return {
        "headers": {"authorization": f"Bearer {bearer}"} if bearer is not None else {},
        "body": body,
        "isBase64Encoded": is_b64,
    }


@pytest.fixture
def handler_env(wired, monkeypatch):
    monkeypatch.setattr(hae, "get_api_key", lambda: _VALID_BEARER)
    return wired


class TestHandlerAuth:
    def test_healthcheck_short_circuits_before_auth(self, handler_env):
        assert hae.lambda_handler({"healthcheck": True}, _Ctx())["statusCode"] == 200

    def test_missing_authorization_header_is_401(self, handler_env):
        resp = hae.lambda_handler({"headers": {}, "body": "{}"}, _Ctx())
        assert resp["statusCode"] == 401

    def test_wrong_token_is_403_not_401(self, handler_env):
        resp = hae.lambda_handler(_event({"data": {"metrics": []}}, bearer="wrong"), _Ctx())
        assert resp["statusCode"] == 403

    def test_a_token_only_in_the_query_string_is_rejected(self, handler_env):
        """#500: a query-string token would leak into the API Gateway access log."""
        resp = hae.lambda_handler({"queryStringParameters": {"key": _VALID_BEARER}, "headers": {}, "body": "{}"}, _Ctx())
        assert resp["statusCode"] == 401

    def test_a_secret_lookup_failure_is_500_and_never_admits_the_request(self, handler_env, monkeypatch):
        def _boom():
            raise RuntimeError("secrets manager down")

        monkeypatch.setattr(hae, "get_api_key", _boom)
        resp = hae.lambda_handler(_event({"data": {"metrics": []}}), _Ctx())
        assert resp["statusCode"] == 500

    def test_a_prefix_of_the_real_token_is_rejected(self, handler_env):
        resp = hae.lambda_handler(_event({"data": {"metrics": []}}, bearer="secret"), _Ctx())
        assert resp["statusCode"] == 403

    def test_malformed_json_body_is_400_after_a_successful_auth(self, handler_env):
        resp = hae.lambda_handler(_event(None, raw_body="{not json"), _Ctx())
        assert resp["statusCode"] == 400

    def test_a_base64_encoded_body_is_decoded_before_parsing(self, handler_env):
        import base64

        payload = {"data": {"metrics": [], "workouts": []}}
        encoded = base64.b64encode(json.dumps(payload).encode()).decode()
        resp = hae.lambda_handler(_event(None, is_b64=True, raw_body=encoded), _Ctx())
        assert resp["statusCode"] == 200


class TestHandlerRouting:
    def test_an_empty_payload_still_archives_the_raw_body_and_reports_zeros(self, handler_env):
        s3, table = handler_env
        resp = hae.lambda_handler(_event({"data": {"metrics": [], "workouts": []}}), _Ctx())
        body = json.loads(resp["body"])
        assert body["status"] == "ok"
        assert body["glucose_days_updated"] == 0
        assert body["other_metric_days"] == 0
        assert body["raw_archive"].startswith(f"raw/{hae.USER_ID}/health_auto_export/")
        assert len(s3.puts) == 1
        assert table.updates == []

    def test_a_glucose_payload_writes_one_day_and_archives_the_readings(self, handler_env):
        s3, table = handler_env
        payload = {
            "data": {
                "metrics": [
                    {
                        "name": "blood_glucose",
                        "units": "mg/dL",
                        "data": [{"date": f"2026-05-02 08:{m:02d}:00 +0000", "qty": 100 + m} for m in (0, 5, 10)],
                    }
                ],
                "workouts": [],
            }
        }
        body = json.loads(hae.lambda_handler(_event(payload), _Ctx())["body"])
        assert body["glucose_days_updated"] == 1
        assert body["glucose_new_readings"] == 3
        assert body["metrics_received"] == ["blood_glucose"]
        written = written_fields(table.updates[0])
        assert written["blood_glucose_readings_count"] == 3
        assert written["cgm_source"] == "dexcom_stelo"
        assert any("cgm_readings" in p["Key"] for p in s3.puts)

    def test_a_generic_metric_payload_writes_the_mapped_field(self, handler_env):
        _, table = handler_env
        payload = {
            "data": {
                "metrics": [{"name": "step_count", "units": "count", "data": [{"date": "2026-05-02", "qty": 8000, "source": "Matt 17"}]}],
                "workouts": [],
            }
        }
        body = json.loads(hae.lambda_handler(_event(payload), _Ctx())["body"])
        assert body["other_metric_days"] == 1
        assert written_fields(table.updates[0])["steps"] == 8000

    def test_a_workout_payload_archives_all_and_aggregates_only_recovery(self, handler_env):
        s3, table = handler_env
        payload = {
            "data": {
                "metrics": [],
                "workouts": [_workout("Yoga", 20, wid="w1"), _workout("Running", 40, wid="w2")],
            }
        }
        body = json.loads(hae.lambda_handler(_event(payload), _Ctx())["body"])
        assert body["workouts_received"] == 2
        assert body["workout_new"] == 2
        assert body["recovery_days"] == 1
        assert written_fields(table.updates[0])["recovery_workout_sessions"] == 1
        assert any("workouts" in p["Key"] for p in s3.puts)

    def test_a_state_of_mind_payload_writes_the_mood_aggregate_and_archives_entries(self, handler_env):
        s3, table = handler_env
        payload = {"data": {"stateOfMind": [{"date": "2026-05-02 08:00:00 +0000", "valence": 0.5, "kind": "dailyMood"}]}}
        body = json.loads(hae.lambda_handler(_event(payload), _Ctx())["body"])
        assert body["som_entries_new"] == 1
        assert body["som_days_updated"] == 1
        assert written_fields(table.updates[0])["som_check_in_count"] == 1
        assert any("state_of_mind" in p["Key"] for p in s3.puts)

    def test_combined_format_blood_pressure_averages_the_day(self, handler_env):
        _, table = handler_env
        payload = {
            "data": {
                "metrics": [
                    {
                        "name": "blood_pressure",
                        "units": "mmHg",
                        "data": [
                            {"date": "2026-05-02 08:00:00 +0000", "systolic": 120, "diastolic": 80},
                            {"date": "2026-05-02 20:00:00 +0000", "systolic": 130, "diastolic": 84},
                        ],
                    }
                ],
                "workouts": [],
            }
        }
        hae.lambda_handler(_event(payload), _Ctx())
        bp = [written_fields(u) for u in table.updates if "blood_pressure_readings_count" in written_fields(u)]
        assert bp, "expected a blood-pressure merge"
        assert bp[0]["bp_systolic"] == 125
        assert bp[0]["bp_diastolic"] == 82
        assert bp[0]["blood_pressure_readings_count"] == 2

    def test_split_format_blood_pressure_pairs_systolic_and_diastolic_by_timestamp(self, handler_env):
        s3, _ = handler_env
        payload = {
            "data": {
                "metrics": [
                    {"name": "blood_pressure_systolic", "units": "mmHg", "data": [{"date": "2026-05-02 08:00:00 +0000", "qty": 122}]},
                    {"name": "blood_pressure_diastolic", "units": "mmHg", "data": [{"date": "2026-05-02 08:00:00 +0000", "qty": 78}]},
                    {"name": "blood_pressure_pulse", "units": "bpm", "data": [{"date": "2026-05-02 08:00:00 +0000", "qty": 62}]},
                ],
                "workouts": [],
            }
        }
        hae.lambda_handler(_event(payload), _Ctx())
        archived = [json.loads(p["Body"]) for p in s3.puts if "blood_pressure" in p["Key"]]
        assert archived, "expected the BP readings to be archived"
        reading = archived[0][0]
        assert (reading["systolic"], reading["diastolic"], reading["pulse"]) == (122, 78, 62)

    def test_split_format_scan_does_not_stop_at_the_first_unrelated_metric(self, handler_env):
        """#483/D-1: the `break` used to sit one level out, so any leading
        non-BP metric aborted the whole BP scan."""
        s3, _ = handler_env
        payload = {
            "data": {
                "metrics": [
                    {"name": "step_count", "units": "count", "data": [{"date": "2026-05-02", "qty": 100, "source": "Matt 17"}]},
                    {"name": "blood_pressure_systolic", "units": "mmHg", "data": [{"date": "2026-05-02 08:00:00 +0000", "qty": 122}]},
                    {"name": "blood_pressure_diastolic", "units": "mmHg", "data": [{"date": "2026-05-02 08:00:00 +0000", "qty": 78}]},
                ],
                "workouts": [],
            }
        }
        hae.lambda_handler(_event(payload), _Ctx())
        assert any("blood_pressure" in p["Key"] for p in s3.puts)

    def test_blood_pressure_with_no_diastolic_must_not_fabricate_a_zero(self, handler_env):
        """FIXED (#2221, ADR-104): `sum(...) / max(1, 0)` used to write a fabricated
        0 mmHg diastolic for a cuff reading that carried systolic only. The zero is
        a clinical number: `daily_brief_lambda` renders it as "120/0" and runs the
        AHA classification on it. Absence is now an absent key, not a zero."""
        _, table = handler_env
        payload = {
            "data": {
                "metrics": [
                    {
                        "name": "blood_pressure",
                        "units": "mmHg",
                        "data": [{"date": "2026-05-02 08:00:00 +0000", "systolic": 120}],
                    }
                ],
                "workouts": [],
            }
        }
        hae.lambda_handler(_event(payload), _Ctx())
        bp = [written_fields(u) for u in table.updates if "blood_pressure_readings_count" in written_fields(u)]
        assert bp, "expected the systolic-only reading to still be merged"
        assert "bp_diastolic" not in bp[0]
        assert "blood_pressure_diastolic" not in bp[0]
        assert bp[0]["bp_systolic"] == 120  # the measured half is NOT dropped

    def test_a_measured_diastolic_is_averaged_even_alongside_a_reading_that_lacks_one(self, handler_env):
        """The other direction of the same ADR-104 rule: a genuinely measured value
        must not be discarded. The filter is `is not None`, not truthiness."""
        _, table = handler_env
        payload = {
            "data": {
                "metrics": [
                    {
                        "name": "blood_pressure",
                        "units": "mmHg",
                        "data": [
                            {"date": "2026-05-02 08:00:00 +0000", "systolic": 120, "diastolic": 80},
                            {"date": "2026-05-02 20:00:00 +0000", "systolic": 130},
                        ],
                    }
                ],
                "workouts": [],
            }
        }
        hae.lambda_handler(_event(payload), _Ctx())
        bp = [written_fields(u) for u in table.updates if "blood_pressure_readings_count" in written_fields(u)]
        assert bp, "expected a blood-pressure merge"
        # 80 is the mean of the diastolic readings that exist — not (80 + 0) / 2.
        assert bp[0]["bp_diastolic"] == 80
        assert bp[0]["blood_pressure_diastolic"] == 80
        assert bp[0]["bp_systolic"] == 125

    def test_the_response_echoes_the_metric_names_it_received(self, handler_env):
        payload = {
            "data": {
                "metrics": [
                    {"name": "step_count", "units": "count", "data": []},
                    {"name": "protein", "units": "g", "data": []},
                ],
                "workouts": [],
            }
        }
        body = json.loads(hae.lambda_handler(_event(payload), _Ctx())["body"])
        assert body["metrics_received"] == ["step_count", "protein"]

    def test_a_payload_without_the_data_wrapper_is_still_processed(self, handler_env):
        _, table = handler_env
        payload = {
            "metrics": [{"name": "step_count", "units": "count", "data": [{"date": "2026-05-02", "qty": 1000, "source": "Matt 17"}]}]
        }
        body = json.loads(hae.lambda_handler(_event(payload), _Ctx())["body"])
        assert body["other_metric_days"] == 1
        assert written_fields(table.updates[0])["steps"] == 1000
