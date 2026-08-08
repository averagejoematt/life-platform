"""tests/test_macrofactor_ingestion_behavior.py — behavioural contracts for the
MacroFactor ingester (`lambdas/ingestion/macrofactor_lambda.py`).

MacroFactor is the source of truth for nutrition: a normalisation defect here
corrupts the stored day and every downstream reader (daily-metrics-compute, the
deficit chain, the coach, the site). These tests pin the contracts that matter:

  * **What is dropped vs. kept** — malformed rows, blank cells, placeholder
    strings, unparseable dates.
  * **ADR-104 honest numbers** — an unlogged nutrient must stay ABSENT, never
    materialise as 0; a genuinely-logged 0 must stay 0.
  * **Date partitioning** — the day a row lands on, and the shape of the `sk`.
    A partition-key mismatch across sources has bitten this repo before (TD-19).
  * **Decimal before DynamoDB** — boto3 rejects native floats, so no bare float
    may reach `put_item`, at any nesting depth.
  * **Idempotency** — re-ingesting the same export must not double-count.
  * **Set-derived expectations** — every assertion about a growable set
    (nutrient columns, micronutrient targets, validator fields) DERIVES its
    expectation from the module constant, never a hard-coded literal list.

Complements `tests/test_macrofactor_unknown_csv.py` (#469 — the unknown-format
archive-and-raise contract), which is not re-tested here.

Tests marked xfail record defects discovered by this tranche; they are not
fixed here (test-only change).
"""

import csv
import io
import os
import re
import sys
from datetime import datetime, timedelta, timezone

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))
sys.path.insert(0, os.path.join(ROOT, "lambdas", "ingestion"))

os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")

import macrofactor_lambda as mf  # noqa: E402
from common.constants import EXPERIMENT_PHASE_CURRENT, EXPERIMENT_START_DATE  # noqa: E402
from ingestion import ingestion_validator  # noqa: E402
from ingestion.ingestion_validator import _SCHEMAS  # noqa: E402
from ingestion.source_registry import SOURCE_REGISTRY  # noqa: E402

# ──────────────────────────────────────────────────────────────────────────────
# Frozen clock — never mix a fixture date with the real wall clock.
# ──────────────────────────────────────────────────────────────────────────────

FROZEN_NOW = datetime(2026, 8, 6, 17, 30, 5, tzinfo=timezone.utc)
FROZEN_STAMP = "2026-08-06T17:30:05Z"


class _FrozenDatetime(datetime):
    """`datetime` subclass with a pinned `now()`.

    A subclass (not a Mock) keeps `strptime`, arithmetic and `.strftime()`
    working — the module uses all three off the same name.
    """

    @classmethod
    def now(cls, tz=None):
        return FROZEN_NOW if tz else FROZEN_NOW.replace(tzinfo=None)

    @classmethod
    def utcnow(cls):
        return FROZEN_NOW.replace(tzinfo=None)


@pytest.fixture
def frozen_clock(monkeypatch):
    monkeypatch.setattr(mf, "datetime", _FrozenDatetime)
    return FROZEN_NOW


# ──────────────────────────────────────────────────────────────────────────────
# Hand-rolled bounded test doubles (never a MagicMock — see the OOM incident).
# ──────────────────────────────────────────────────────────────────────────────


class FakeTable:
    """DynamoDB Table stand-in keyed the way this module keys the real table."""

    def __init__(self):
        self.items = {}
        self.puts = []

    def put_item(self, Item):  # noqa: N803 — boto3's kwarg name
        self.puts.append(Item)
        self.items[(Item.get("pk"), Item.get("sk"))] = Item


class _Body:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return self._payload


class FakeS3:
    def __init__(self, payload=b""):
        self.payload = payload
        self.gets = []
        self.puts = []

    def get_object(self, Bucket, Key):  # noqa: N803
        self.gets.append((Bucket, Key))
        return {"Body": _Body(self.payload)}

    def put_object(self, **kwargs):
        self.puts.append(kwargs)
        return {}


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

NUTRITION_HEADERS = ["Date", "Time", "Food Name", "Serving Size", "Serving Qty", "Serving Weight (g)"] + list(mf.NUTRIENT_COLUMNS)
WORKOUT_HEADERS = [
    "Date",
    "Workout",
    "Workout Duration",
    "Exercise",
    "Set Type",
    "Weight (lbs)",
    "Reps",
    "RIR",
    "Duration",
    "Exercise Base Weight (lbs)",
]
SUMMARY_HEADERS = [
    "Date",
    "Calories (kcal)",
    "Protein (g)",
    "Fat (g)",
    "Carbs (g)",
    "Weight (lbs)",
    "Trend Weight (lbs)",
    "Expenditure",
    "Target Calories (kcal)",
    "Target Protein (g)",
]


def csv_bytes(headers, rows, bom=False):
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=headers, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({h: row.get(h, "") for h in headers})
    payload = buf.getvalue().encode("utf-8")
    return (b"\xef\xbb\xbf" + payload) if bom else payload


def food_row(date="2026-08-05", name="Eggs", time="07:30", **cells):
    row = {"Date": date, "Food Name": name, "Time": time}
    row.update(cells)
    return row


def invoke(monkeypatch, payload, key="uploads/macrofactor/export.csv", table=None, s3=None):
    """Drive lambda_handler against bounded fakes. Returns (response, table, s3)."""
    table = table or FakeTable()
    s3 = s3 or FakeS3(payload)
    s3.payload = payload
    monkeypatch.setattr(mf, "s3_client", s3)
    monkeypatch.setattr(mf, "table", table)
    monkeypatch.setattr(mf, "datetime", _FrozenDatetime)
    response = mf.lambda_handler({"bucket": "test-bucket", "key": key}, None)
    return response, table, s3


def find_floats(obj, path="item"):
    """Every path in `obj` holding a native Python float (which boto3 rejects)."""
    if isinstance(obj, bool):
        return []
    if isinstance(obj, float):
        return [path]
    if isinstance(obj, dict):
        out = []
        for k, v in obj.items():
            out += find_floats(v, f"{path}.{k}")
        return out
    if isinstance(obj, (list, tuple)):
        out = []
        for i, v in enumerate(obj):
            out += find_floats(v, f"{path}[{i}]")
        return out
    return []


# ══════════════════════════════════════════════════════════════════════════════
# safe_float — the CSV cell coercion contract
# ══════════════════════════════════════════════════════════════════════════════


def test_a_blank_cell_is_absence_not_zero():
    assert mf.safe_float("") is None
    assert mf.safe_float("   ") is None
    assert mf.safe_float(None) is None


def test_macrofactors_placeholder_strings_read_as_absence():
    for placeholder in ("-", "N/A", "n/a"):
        assert mf.safe_float(placeholder) is None, placeholder


def test_a_thousands_separator_does_not_truncate_the_value():
    assert mf.safe_float("1,234.5") == 1234.5
    assert mf.safe_float("2,000") == 2000.0


def test_surrounding_whitespace_never_invalidates_a_number():
    assert mf.safe_float("  42.5\t") == 42.5


def test_unparseable_text_is_dropped_rather_than_raising():
    assert mf.safe_float("about a cup") is None
    assert mf.safe_float("12g") is None


def test_an_explicitly_logged_zero_is_a_value_not_absence():
    """ADR-104: 0 g alcohol logged is a fact; it must not collapse to None."""
    value = mf.safe_float("0")
    assert value is not None and value == 0.0


def test_a_negative_cell_is_preserved_not_clamped():
    assert mf.safe_float("-15.5") == -15.5


def test_non_finite_placeholder_cells_read_as_absence():
    import math

    for cell in ("nan", "NaN", "inf", "-inf"):
        value = mf.safe_float(cell)
        assert value is None or math.isfinite(value), cell


# ══════════════════════════════════════════════════════════════════════════════
# safe_int
# ══════════════════════════════════════════════════════════════════════════════


def test_safe_int_truncates_toward_zero_rather_than_rounding():
    assert mf.safe_int("12.9") == 12
    assert mf.safe_int("-3.7") == -3


def test_safe_int_propagates_absence():
    assert mf.safe_int("") is None
    assert mf.safe_int("N/A") is None


def test_safe_int_keeps_a_logged_zero():
    """RIR 0 means "taken to failure" — dropping it would erase real intent."""
    assert mf.safe_int("0") == 0


# ══════════════════════════════════════════════════════════════════════════════
# parse_duration_min
# ══════════════════════════════════════════════════════════════════════════════


def test_duration_hours_and_minutes_sum_to_minutes():
    assert mf.parse_duration_min("1h 30m") == 90.0
    assert mf.parse_duration_min("1h30m") == 90.0


def test_duration_minutes_only():
    assert mf.parse_duration_min("45m") == 45.0


def test_duration_hours_only():
    assert mf.parse_duration_min("2h") == 120.0


def test_two_part_colon_duration_reads_as_minutes_and_seconds():
    assert mf.parse_duration_min("1:30") == 1.5


def test_three_part_colon_duration_reads_as_hours_minutes_seconds():
    assert mf.parse_duration_min("1:30:00") == 90.0


def test_a_bare_number_is_already_minutes():
    assert mf.parse_duration_min("90") == 90.0
    assert mf.parse_duration_min("47.5") == 47.5


def test_a_missing_duration_is_absent_not_zero():
    assert mf.parse_duration_min("") is None
    assert mf.parse_duration_min(None) is None
    assert mf.parse_duration_min("   ") is None


def test_unparseable_duration_text_is_absent_not_a_crash():
    assert mf.parse_duration_min("unknown") is None


def test_a_malformed_unit_suffix_duration_degrades_to_absence():
    assert mf.parse_duration_min("45 mins") is None
    assert mf.parse_duration_min("90 min") is None


def test_a_malformed_colon_duration_degrades_to_absence():
    assert mf.parse_duration_min("1:ab") is None


# ══════════════════════════════════════════════════════════════════════════════
# parse_entry — row-level parsing + date partitioning
# ══════════════════════════════════════════════════════════════════════════════


def test_a_row_with_no_date_is_dropped():
    assert mf.parse_entry({"Date": "", "Food Name": "Eggs"}) is None


def test_a_row_with_no_food_name_is_dropped():
    assert mf.parse_entry({"Date": "2026-08-05", "Food Name": "  "}) is None


def test_a_row_whose_date_matches_no_known_format_is_dropped():
    assert mf.parse_entry({"Date": "August 5, 2026", "Food Name": "Eggs"}) is None


def test_an_iso_date_lands_on_that_same_calendar_day():
    date_str, _ = mf.parse_entry({"Date": "2026-08-05", "Food Name": "Eggs"})
    assert date_str == "2026-08-05"


def test_a_us_slash_date_normalises_to_iso():
    date_str, _ = mf.parse_entry({"Date": "08/05/2026", "Food Name": "Eggs"})
    assert date_str == "2026-08-05"


def test_a_day_greater_than_twelve_falls_back_to_day_first_parsing():
    date_str, _ = mf.parse_entry({"Date": "13/04/2026", "Food Name": "Eggs"})
    assert date_str == "2026-04-13"


def test_an_ambiguous_slash_date_resolves_month_first():
    """03/04 is March 4th, not April 3rd — US-first is the declared order."""
    date_str, _ = mf.parse_entry({"Date": "03/04/2026", "Food Name": "Eggs"})
    assert date_str == "2026-03-04"


def test_the_partition_day_is_taken_verbatim_with_no_timezone_shift():
    """A cross-source partition shift is the TD-19 class — a year-boundary row
    must not slide a day either way."""
    for raw in ("2026-01-01", "2026-12-31"):
        date_str, _ = mf.parse_entry({"Date": raw, "Food Name": "Eggs"})
        assert date_str == raw


def test_an_unlogged_nutrient_is_absent_from_the_entry_not_zero():
    """ADR-104: a meal with no protein figure must not claim protein = 0."""
    _, entry = mf.parse_entry(food_row(**{"Calories (kcal)": "200", "Protein (g)": ""}))
    assert "protein_g" not in entry
    assert entry["calories_kcal"] == 200.0


def test_a_logged_zero_nutrient_survives_into_the_entry():
    _, entry = mf.parse_entry(food_row(**{"Alcohol (g)": "0"}))
    assert entry["alcohol_g"] == 0.0


def test_every_nutrient_column_in_the_registry_is_mapped_onto_the_entry():
    """Guard the SET: derived from NUTRIENT_COLUMNS, so a new column that is
    added to the registry but not parsed fails here."""
    row = food_row()
    for i, column in enumerate(mf.NUTRIENT_COLUMNS, start=1):
        row[column] = str(i)
    _, entry = mf.parse_entry(row)
    missing = [field for field in mf.NUTRIENT_COLUMNS.values() if field not in entry]
    assert missing == []


def test_nutrient_field_names_are_unique_across_the_registry():
    """Two columns mapping onto one field would silently overwrite each other."""
    fields = list(mf.NUTRIENT_COLUMNS.values())
    assert len(fields) == len(set(fields))
    assert mf.NUTRIENT_FIELD_NAMES == set(fields)
    assert set(mf.COL_TO_FIELD) == set(mf.NUTRIENT_COLUMNS)


def test_columns_outside_the_registry_are_ignored_not_stored():
    _, entry = mf.parse_entry(food_row(**{"Some New Vendor Column": "99"}))
    assert "Some New Vendor Column" not in entry
    assert not any(str(v) == "99" for v in entry.values())


def test_serving_fields_are_carried_through_when_present():
    _, entry = mf.parse_entry(food_row(**{"Serving Size": "large", "Serving Qty": "2", "Serving Weight (g)": "112.5"}))
    assert entry["serving_size"] == "large"
    assert entry["serving_qty"] == 2.0
    assert entry["serving_wt_g"] == 112.5


def test_a_blank_time_leaves_the_entry_untimed_rather_than_midnight():
    _, entry = mf.parse_entry(food_row(time=""))
    assert "time" not in entry


def test_food_names_are_trimmed_but_otherwise_preserved():
    _, entry = mf.parse_entry(food_row(name="  Chicken, grilled  "))
    assert entry["food_name"] == "Chicken, grilled"


# ══════════════════════════════════════════════════════════════════════════════
# build_day_items — day aggregation
# ══════════════════════════════════════════════════════════════════════════════


def test_entries_on_the_same_day_sum_into_one_day_item(frozen_clock):
    rows = [
        food_row(time="07:00", **{"Calories (kcal)": "300", "Protein (g)": "25"}),
        food_row(time="12:00", name="Chicken", **{"Calories (kcal)": "500", "Protein (g)": "45"}),
    ]
    items = mf.build_day_items(rows)
    assert list(items) == ["2026-08-05"]
    day = items["2026-08-05"]
    assert day["total_calories_kcal"] == 800.0
    assert day["total_protein_g"] == 70.0


def test_entries_on_different_days_never_bleed_into_one_partition(frozen_clock):
    rows = [
        food_row(date="2026-08-04", **{"Calories (kcal)": "300"}),
        food_row(date="2026-08-05", **{"Calories (kcal)": "500"}),
    ]
    items = mf.build_day_items(rows)
    assert items["2026-08-04"]["total_calories_kcal"] == 300.0
    assert items["2026-08-05"]["total_calories_kcal"] == 500.0


def test_unparseable_rows_are_skipped_without_killing_the_good_ones(frozen_clock):
    rows = [
        {"Date": "", "Food Name": "orphan"},
        {"Date": "not-a-date", "Food Name": "orphan2"},
        food_row(**{"Calories (kcal)": "400"}),
    ]
    items = mf.build_day_items(rows)
    assert list(items) == ["2026-08-05"]
    assert items["2026-08-05"]["entries_count"] == 1


def test_entries_count_matches_the_stored_food_log_length(frozen_clock):
    rows = [food_row(time=f"0{i}:00", name=f"Food{i}") for i in range(1, 5)]
    day = mf.build_day_items(rows)["2026-08-05"]
    assert day["entries_count"] == len(day["food_log"]) == 4


def test_the_food_log_is_time_ordered_with_untimed_entries_first(frozen_clock):
    rows = [
        food_row(time="19:00", name="Dinner"),
        food_row(time="07:00", name="Breakfast"),
        food_row(time="", name="Unknown time"),
    ]
    day = mf.build_day_items(rows)["2026-08-05"]
    assert [e["food_name"] for e in day["food_log"]] == ["Unknown time", "Breakfast", "Dinner"]


def test_a_nutrient_never_logged_has_no_total_field_at_all(frozen_clock):
    """ADR-104: absence stays absent — a reader must be able to tell "not
    tracked" from "tracked and zero"."""
    day = mf.build_day_items([food_row(**{"Calories (kcal)": "400"})])["2026-08-05"]
    assert "total_selenium_mcg" not in day
    assert "total_caffeine_mg" not in day


def test_a_day_whose_logged_alcohol_is_zero_still_reports_zero(frozen_clock):
    day = mf.build_day_items([food_row(**{"Calories (kcal)": "400", "Alcohol (g)": "0"})])["2026-08-05"]
    assert day.get("total_alcohol_g") == 0


def test_day_totals_are_rounded_to_two_decimal_places(frozen_clock):
    rows = [food_row(time=f"0{i}:00", **{"Protein (g)": "0.333"}) for i in range(1, 4)]
    day = mf.build_day_items(rows)["2026-08-05"]
    assert day["total_protein_g"] == 1.0


def test_every_registry_nutrient_can_reach_a_day_total(frozen_clock):
    """Guard the SET: a column that parses but never totals is a silent hole."""
    row = food_row()
    for column in mf.NUTRIENT_COLUMNS:
        row[column] = "5"
    day = mf.build_day_items([row])["2026-08-05"]
    missing = [f"total_{field}" for field in mf.NUTRIENT_FIELD_NAMES if f"total_{field}" not in day]
    assert missing == []


def test_the_day_item_is_keyed_on_the_macrofactor_partition(frozen_clock):
    day = mf.build_day_items([food_row()])["2026-08-05"]
    assert day["pk"] == mf.PK == f"USER#{mf.USER_ID}#SOURCE#macrofactor"
    assert day["sk"] == "DATE#2026-08-05"
    assert day["date"] == "2026-08-05"


def test_the_day_item_declares_its_source_and_schema_version(frozen_clock):
    day = mf.build_day_items([food_row()])["2026-08-05"]
    assert day["source"] == "macrofactor"
    assert day["schema_version"] == 1


def test_the_ingest_stamp_is_utc_and_second_precision(frozen_clock):
    day = mf.build_day_items([food_row()])["2026-08-05"]
    assert day["ingested_at"] == FROZEN_STAMP


def test_rebuilding_the_same_export_produces_an_identical_day_item(frozen_clock):
    """Idempotency at the builder: parsing is pure, so a re-upload cannot drift."""
    rows = [food_row(time="07:00", **{"Calories (kcal)": "300", "Protein (g)": "25"})]
    assert mf.build_day_items(rows) == mf.build_day_items(list(rows))


def test_two_identical_rows_in_one_export_count_as_two_servings(frozen_clock):
    """Within a single export, a repeated row is a second helping, not a dupe —
    dedup happens at the day level on re-upload, not at the row level."""
    rows = [food_row(time="07:00", **{"Calories (kcal)": "300"}), food_row(time="07:00", **{"Calories (kcal)": "300"})]
    day = mf.build_day_items(rows)["2026-08-05"]
    assert day["entries_count"] == 2
    assert day["total_calories_kcal"] == 600.0


def test_a_nan_cell_cannot_null_out_a_real_days_calories(frozen_clock):
    from common.numeric import floats_to_decimal

    rows = [
        food_row(time="07:00", **{"Calories (kcal)": "nan", "Protein (g)": "20"}),
        food_row(time="12:00", name="Chicken", **{"Calories (kcal)": "500", "Protein (g)": "45"}),
    ]
    stored = floats_to_decimal(mf.build_day_items(rows)["2026-08-05"])
    assert stored.get("total_calories_kcal") is not None


# ══════════════════════════════════════════════════════════════════════════════
# compute_protein_distribution
# ══════════════════════════════════════════════════════════════════════════════


def test_an_empty_food_log_scores_nothing_rather_than_zero():
    """ADR-104: no meals is not a 0% distribution score."""
    assert mf.compute_protein_distribution([]) == (None, 0, 0, 0)


def test_a_food_log_with_no_usable_times_scores_nothing():
    log = [{"food_name": "x", "protein_g": 40, "calories_kcal": 600}]
    assert mf.compute_protein_distribution(log) == (None, 0, 0, 0)


def test_entries_without_a_protein_figure_are_excluded_from_scoring():
    log = [
        {"time": "07:00", "calories_kcal": 600},
        {"time": "12:00", "protein_g": 40, "calories_kcal": 600},
    ]
    score, above, meals, _ = mf.compute_protein_distribution(log)
    assert (score, above, meals) == (100.0, 1, 1)


def test_entries_with_an_unparseable_time_are_excluded_from_scoring():
    log = [
        {"time": "lunchtime", "protein_g": 40, "calories_kcal": 600},
        {"time": "7", "protein_g": 40, "calories_kcal": 600},
        {"time": "12:00", "protein_g": 40, "calories_kcal": 600},
    ]
    _, _, meals, _ = mf.compute_protein_distribution(log)
    assert meals == 1


def test_entries_within_thirty_minutes_are_one_eating_occasion():
    log = [
        {"time": "12:00", "protein_g": 20, "calories_kcal": 300},
        {"time": "12:25", "protein_g": 20, "calories_kcal": 300},
    ]
    score, above, meals, snacks = mf.compute_protein_distribution(log)
    assert (meals, snacks, above, score) == (1, 0, 1, 100.0)


def test_an_entry_exactly_thirty_minutes_later_still_joins_the_occasion():
    log = [
        {"time": "12:00", "protein_g": 20, "calories_kcal": 300},
        {"time": "12:30", "protein_g": 20, "calories_kcal": 300},
    ]
    _, _, meals, _ = mf.compute_protein_distribution(log)
    assert meals == 1


def test_an_entry_thirty_one_minutes_later_starts_a_new_occasion():
    log = [
        {"time": "12:00", "protein_g": 35, "calories_kcal": 600},
        {"time": "12:31", "protein_g": 35, "calories_kcal": 600},
    ]
    _, _, meals, _ = mf.compute_protein_distribution(log)
    assert meals == 2


def test_the_thirty_minute_window_is_anchored_to_the_occasion_start_not_the_previous_bite():
    """A grazing chain 25 min apart must not fuse into one endless occasion: the
    third bite is 50 min past the occasion START, so it opens a new one even
    though it is only 25 min past the previous bite."""
    log = [
        {"time": "12:00", "protein_g": 20, "calories_kcal": 400},
        {"time": "12:25", "protein_g": 20, "calories_kcal": 400},
        {"time": "12:50", "protein_g": 40, "calories_kcal": 400},
    ]
    _, above, meals, snacks = mf.compute_protein_distribution(log)
    assert (meals, snacks) == (2, 0)
    assert above == 2  # 40 g in the first occasion, 40 g in the second


def test_a_low_calorie_occasion_is_a_snack_and_leaves_the_denominator():
    log = [
        {"time": "10:00", "protein_g": 5, "calories_kcal": 150},
        {"time": "12:00", "protein_g": 40, "calories_kcal": 700},
    ]
    score, above, meals, snacks = mf.compute_protein_distribution(log)
    assert (meals, snacks, above, score) == (1, 1, 1, 100.0)


def test_an_occasion_exactly_at_the_meal_threshold_counts_as_a_meal():
    log = [{"time": "12:00", "protein_g": 40, "calories_kcal": mf.MEAL_CALORIE_THRESHOLD}]
    _, _, meals, snacks = mf.compute_protein_distribution(log)
    assert (meals, snacks) == (1, 0)


def test_protein_exactly_at_the_mps_threshold_counts_as_sufficient():
    log = [{"time": "12:00", "protein_g": mf.PROTEIN_MPS_THRESHOLD, "calories_kcal": 700}]
    score, above, _, _ = mf.compute_protein_distribution(log)
    assert (above, score) == (1, 100.0)


def test_protein_just_under_the_mps_threshold_does_not_count():
    log = [{"time": "12:00", "protein_g": mf.PROTEIN_MPS_THRESHOLD - 0.1, "calories_kcal": 700}]
    score, above, _, _ = mf.compute_protein_distribution(log)
    assert (above, score) == (0, 0.0)


def test_a_day_of_only_snacks_scores_zero_and_reports_the_snack_count():
    log = [
        {"time": "10:00", "protein_g": 5, "calories_kcal": 150},
        {"time": "15:00", "protein_g": 5, "calories_kcal": 150},
    ]
    score, above, meals, snacks = mf.compute_protein_distribution(log)
    assert (score, above, meals, snacks) == (0.0, 0, 0, 2)


def test_the_score_is_the_percentage_of_meals_hitting_the_threshold():
    log = [
        {"time": "07:00", "protein_g": 40, "calories_kcal": 600},
        {"time": "12:00", "protein_g": 10, "calories_kcal": 600},
        {"time": "18:00", "protein_g": 40, "calories_kcal": 600},
    ]
    score, above, meals, _ = mf.compute_protein_distribution(log)
    assert (above, meals, score) == (2, 3, 66.7)


def test_an_entry_with_no_calorie_figure_does_not_inflate_the_occasion():
    """Absent calories contribute nothing — they cannot promote a snack to a meal."""
    log = [{"time": "12:00", "protein_g": 40}]
    _, _, meals, snacks = mf.compute_protein_distribution(log)
    assert (meals, snacks) == (0, 1)


def test_protein_distribution_is_only_attached_when_it_could_be_computed(frozen_clock):
    """A day with no timed protein must carry no score field at all (ADR-104)."""
    untimed = mf.build_day_items([food_row(time="", **{"Protein (g)": "40"})])["2026-08-05"]
    assert "protein_distribution_score" not in untimed
    timed = mf.build_day_items([food_row(time="12:00", **{"Protein (g)": "40", "Calories (kcal)": "700"})])["2026-08-05"]
    assert timed["protein_distribution_score"] == 100.0
    assert timed["total_meals"] == 1


# ══════════════════════════════════════════════════════════════════════════════
# compute_micronutrient_sufficiency
# ══════════════════════════════════════════════════════════════════════════════


def test_sufficiency_is_unreported_when_no_target_nutrient_was_logged():
    assert mf.compute_micronutrient_sufficiency({"total_calories_kcal": 2000}) == (None, None)


def test_every_target_in_the_registry_is_scored_when_present():
    """Guard the SET: derived from MICRONUTRIENT_TARGETS."""
    totals = {f"total_{key}": cfg["target"] for key, cfg in mf.MICRONUTRIENT_TARGETS.items()}
    sufficiency, avg = mf.compute_micronutrient_sufficiency(totals)
    assert set(sufficiency) == set(mf.MICRONUTRIENT_TARGETS)
    assert avg == 100.0


def test_every_micronutrient_target_names_a_real_nutrient_field():
    """A target keyed on a field the parser never produces can never score."""
    unknown = set(mf.MICRONUTRIENT_TARGETS) - mf.NUTRIENT_FIELD_NAMES
    assert unknown == set()


def test_every_micronutrient_target_has_a_positive_goal_and_a_label():
    for key, cfg in mf.MICRONUTRIENT_TARGETS.items():
        assert cfg["target"] > 0, key
        assert isinstance(cfg["label"], str) and cfg["label"].strip(), key


def test_exceeding_a_target_is_capped_at_one_hundred_percent():
    key = next(iter(mf.MICRONUTRIENT_TARGETS))
    target = mf.MICRONUTRIENT_TARGETS[key]["target"]
    sufficiency, avg = mf.compute_micronutrient_sufficiency({f"total_{key}": target * 10})
    assert sufficiency[key]["pct"] == 100.0
    assert avg == 100.0


def test_a_nutrient_that_was_never_logged_is_omitted_not_scored_zero():
    """ADR-104: a missing micronutrient is unknown, not a 0% failure."""
    key = next(iter(mf.MICRONUTRIENT_TARGETS))
    sufficiency, _ = mf.compute_micronutrient_sufficiency({f"total_{key}": 1})
    assert set(sufficiency) == {key}


def test_the_average_covers_only_the_nutrients_actually_logged():
    keys = list(mf.MICRONUTRIENT_TARGETS)[:2]
    totals = {
        f"total_{keys[0]}": mf.MICRONUTRIENT_TARGETS[keys[0]]["target"],
        f"total_{keys[1]}": mf.MICRONUTRIENT_TARGETS[keys[1]]["target"] / 2,
    }
    _, avg = mf.compute_micronutrient_sufficiency(totals)
    assert avg == 75.0


def test_sufficiency_reports_the_actual_intake_alongside_the_target():
    key = "fiber_g"
    target = mf.MICRONUTRIENT_TARGETS[key]["target"]
    sufficiency, _ = mf.compute_micronutrient_sufficiency({f"total_{key}": 19.04})
    assert sufficiency[key]["actual"] == 19.0
    assert sufficiency[key]["target"] == target


# ══════════════════════════════════════════════════════════════════════════════
# detect_csv_type
# ══════════════════════════════════════════════════════════════════════════════


def test_a_food_name_column_identifies_the_nutrition_diary():
    assert mf.detect_csv_type(NUTRITION_HEADERS) == "nutrition"


def test_exercise_plus_set_type_identifies_the_workout_export():
    assert mf.detect_csv_type(WORKOUT_HEADERS) == "workout"


def test_an_exercise_column_alone_is_not_a_workout_export():
    assert mf.detect_csv_type(["Date", "Exercise"]) == "unknown"


def test_expenditure_plus_date_plus_calories_identifies_the_daily_summary():
    assert mf.detect_csv_type(SUMMARY_HEADERS) == "daily_summary"


def test_a_summary_export_missing_expenditure_is_not_a_summary():
    assert mf.detect_csv_type(["Date", "Calories (kcal)"]) == "unknown"


def test_the_nutrition_diary_wins_when_a_file_carries_both_markers():
    assert mf.detect_csv_type(["Date", "Food Name", "Exercise", "Set Type"]) == "nutrition"


def test_detection_accepts_the_dict_keys_view_the_handler_passes():
    row = {h: "" for h in SUMMARY_HEADERS}
    assert mf.detect_csv_type(row.keys()) == "daily_summary"


# ══════════════════════════════════════════════════════════════════════════════
# build_workout_day_items
# ══════════════════════════════════════════════════════════════════════════════


def workout_row(date="2026-08-05", exercise="Bench Press", workout="Push A", duration="45m", **cells):
    row = {"Date": date, "Exercise": exercise, "Workout": workout, "Workout Duration": duration}
    row.update(cells)
    return row


def test_workout_rows_without_a_date_or_exercise_are_dropped(frozen_clock):
    assert mf.build_workout_day_items([{"Date": "", "Exercise": "Bench"}]) == {}
    assert mf.build_workout_day_items([{"Date": "2026-08-05", "Exercise": " "}]) == {}
    assert mf.build_workout_day_items([]) == {}


def test_sets_of_one_exercise_are_grouped_and_indexed_from_one(frozen_clock):
    rows = [workout_row(**{"Weight (lbs)": "135", "Reps": "5"}) for _ in range(3)]
    day = mf.build_workout_day_items(rows)["2026-08-05"]
    sets = day["workouts"][0]["exercises"][0]["sets"]
    assert [s["set_index"] for s in sets] == [1, 2, 3]
    assert day["total_sets"] == 3


def test_a_blank_set_type_defaults_to_a_normal_working_set(frozen_clock):
    day = mf.build_workout_day_items([workout_row(**{"Set Type": ""})])["2026-08-05"]
    assert day["workouts"][0]["exercises"][0]["sets"][0]["set_type"] == "normal"


def test_an_unrecorded_rep_count_stays_absent_from_the_set(frozen_clock):
    """ADR-104: a set with no reps logged must not read as 0 reps."""
    day = mf.build_workout_day_items([workout_row(**{"Weight (lbs)": "135", "Reps": ""})])["2026-08-05"]
    first_set = day["workouts"][0]["exercises"][0]["sets"][0]
    assert "reps" not in first_set
    assert first_set["weight_lbs"] == 135.0


def test_a_bodyweight_set_keeps_its_zero_load(frozen_clock):
    day = mf.build_workout_day_items([workout_row(exercise="Pull-up", **{"Weight (lbs)": "0", "Reps": "10"})])["2026-08-05"]
    assert day["workouts"][0]["exercises"][0]["sets"][0]["weight_lbs"] == 0.0


def test_total_volume_is_load_times_reps_summed_over_every_set(frozen_clock):
    rows = [
        workout_row(**{"Weight (lbs)": "135", "Reps": "5"}),
        workout_row(**{"Weight (lbs)": "185", "Reps": "3"}),
    ]
    day = mf.build_workout_day_items(rows)["2026-08-05"]
    assert day["total_volume_lbs"] == 135 * 5 + 185 * 3


def test_a_set_with_no_load_contributes_no_volume(frozen_clock):
    rows = [
        workout_row(**{"Weight (lbs)": "135", "Reps": "5"}),
        workout_row(exercise="Plank", **{"Duration": "60"}),
    ]
    day = mf.build_workout_day_items(rows)["2026-08-05"]
    assert day["total_volume_lbs"] == 675.0
    assert day["total_sets"] == 2


def test_unique_exercises_counts_distinct_names_across_the_whole_day(frozen_clock):
    rows = [
        workout_row(exercise="Bench Press", **{"Reps": "5"}),
        workout_row(exercise="Bench Press", **{"Reps": "5"}),
        workout_row(exercise="Row", workout="Pull B", **{"Reps": "8"}),
    ]
    day = mf.build_workout_day_items(rows)["2026-08-05"]
    assert day["unique_exercises"] == 2
    assert day["workouts_count"] == 2


def test_the_workout_duration_is_normalised_to_minutes(frozen_clock):
    day = mf.build_workout_day_items([workout_row(duration="1h 15m")])["2026-08-05"]
    assert day["workouts"][0]["workout_duration_min"] == 75.0


def test_an_unnamed_workout_gets_a_neutral_label_not_an_empty_string(frozen_clock):
    day = mf.build_workout_day_items([workout_row(workout="")])["2026-08-05"]
    assert day["workouts"][0]["workout_name"] == "Workout"


def test_the_exercise_base_weight_is_read_from_the_first_set_row(frozen_clock):
    rows = [
        workout_row(**{"Exercise Base Weight (lbs)": "45", "Reps": "5"}),
        workout_row(**{"Exercise Base Weight (lbs)": "", "Reps": "5"}),
    ]
    exercise = mf.build_workout_day_items(rows)["2026-08-05"]["workouts"][0]["exercises"][0]
    assert exercise["base_weight_lbs"] == 45.0


def test_workouts_are_written_to_their_own_partition_not_the_nutrition_one(frozen_clock):
    day = mf.build_workout_day_items([workout_row()])["2026-08-05"]
    assert day["pk"] == mf.PK_WORKOUTS == f"USER#{mf.USER_ID}#SOURCE#macrofactor_workouts"
    assert day["pk"] != mf.PK
    assert day["sk"] == "DATE#2026-08-05"
    assert day["source"] == "macrofactor_workouts"


def test_a_slash_dated_workout_row_normalises_to_iso(frozen_clock):
    day_items = mf.build_workout_day_items([workout_row(date="08/05/2026")])
    assert list(day_items) == ["2026-08-05"]


def test_rebuilding_the_same_workout_export_is_idempotent(frozen_clock):
    rows = [workout_row(**{"Weight (lbs)": "135", "Reps": "5"})]
    assert mf.build_workout_day_items(rows) == mf.build_workout_day_items(list(rows))


def test_a_workout_row_with_an_unparseable_date_is_dropped_not_mis_partitioned(frozen_clock):
    day_items = mf.build_workout_day_items([workout_row(date="April 4, 2026")])
    assert all(re.fullmatch(r"DATE#\d{4}-\d{2}-\d{2}", item["sk"]) for item in day_items.values())


def test_one_malformed_duration_cell_cannot_abort_the_whole_workout_import(frozen_clock):
    rows = [
        workout_row(duration="45 mins", **{"Reps": "5"}),
        workout_row(date="2026-08-06", duration="30m", **{"Reps": "5"}),
    ]
    assert "2026-08-06" in mf.build_workout_day_items(rows)


# ══════════════════════════════════════════════════════════════════════════════
# build_summary_day_items — the daily-summary export format
# ══════════════════════════════════════════════════════════════════════════════


def summary_row(date="2026-08-05", cal="2000", prot="150", fat="70", carbs="180", **cells):
    row = {
        "Date": date,
        "Calories (kcal)": cal,
        "Protein (g)": prot,
        "Fat (g)": fat,
        "Carbs (g)": carbs,
    }
    row.update(cells)
    return row


def test_an_excel_serial_date_converts_to_the_right_calendar_day(frozen_clock):
    """44927 is 2023-01-01 in Excel's 1900 system — an external anchor, not a
    restatement of the module's own epoch arithmetic."""
    items = mf.build_summary_day_items([summary_row(date="44927")])
    assert list(items) == ["2023-01-01"]


def test_a_second_excel_serial_anchor_confirms_the_epoch(frozen_clock):
    items = mf.build_summary_day_items([summary_row(date="43831")])
    assert list(items) == ["2020-01-01"]


def test_a_number_outside_the_excel_serial_range_is_rejected_not_converted(frozen_clock):
    assert mf.build_summary_day_items([summary_row(date="100")]) == {}


def test_a_us_slash_date_in_the_summary_export_normalises_to_iso(frozen_clock):
    items = mf.build_summary_day_items([summary_row(date="8/5/2026")])
    assert list(items) == ["2026-08-05"]


def test_a_slash_date_with_non_numeric_parts_is_skipped_not_stored(frozen_clock):
    assert mf.build_summary_day_items([summary_row(date="Aug/5th/2026")]) == {}


def test_an_iso_date_in_the_summary_export_passes_through(frozen_clock):
    items = mf.build_summary_day_items([summary_row(date="2026-08-05")])
    assert list(items) == ["2026-08-05"]


def test_a_summary_row_with_no_date_is_skipped(frozen_clock):
    assert mf.build_summary_day_items([summary_row(date="")]) == {}


def test_a_summary_row_with_no_macros_is_skipped_as_an_empty_future_day(frozen_clock):
    rows = [summary_row(date="2026-08-09", cal="", prot="", fat="", carbs="", **{"Expenditure": "2800"})]
    assert mf.build_summary_day_items(rows) == {}


def test_a_summary_day_declares_the_summary_schema_and_format(frozen_clock):
    day = mf.build_summary_day_items([summary_row()])["2026-08-05"]
    assert day["schema_version"] == 2
    assert day["_format"] == "daily_summary"
    assert day["source"] == "macrofactor"
    assert day["pk"] == mf.PK


def test_the_summary_format_emits_the_empty_food_log_the_validator_requires(frozen_clock):
    """DATA-2 requires entries_count + food_log; the summary export has neither,
    so it must emit honest empty placeholders rather than omit the fields."""
    day = mf.build_summary_day_items([summary_row()])["2026-08-05"]
    assert day["entries_count"] == 0
    assert day["food_log"] == []


def test_summary_macros_land_on_the_same_total_field_names_as_the_diary(frozen_clock):
    day = mf.build_summary_day_items([summary_row()])["2026-08-05"]
    assert day["total_calories_kcal"] == 2000.0
    assert day["total_protein_g"] == 150.0
    assert day["total_fat_g"] == 70.0
    assert day["total_carbs_g"] == 180.0


def test_an_unlogged_summary_weight_is_absent_rather_than_zero(frozen_clock):
    day = mf.build_summary_day_items([summary_row(**{"Weight (lbs)": ""})])["2026-08-05"]
    assert "weight_lbs_macrofactor" not in day


def test_a_zero_weight_reading_is_treated_as_no_weigh_in(frozen_clock):
    day = mf.build_summary_day_items([summary_row(**{"Weight (lbs)": "0"})])["2026-08-05"]
    assert "weight_lbs_macrofactor" not in day


def test_a_real_weigh_in_and_trend_weight_are_both_carried(frozen_clock):
    day = mf.build_summary_day_items([summary_row(**{"Weight (lbs)": "321.6", "Trend Weight (lbs)": "322.4"})])["2026-08-05"]
    assert day["weight_lbs_macrofactor"] == 321.6
    assert day["trend_weight_lbs"] == 322.4


def test_expenditure_is_mirrored_onto_the_canonical_tdee_field(frozen_clock):
    """#484: the deficit chain and every AI reader key off tdee_kcal."""
    day = mf.build_summary_day_items([summary_row(**{"Expenditure": "3100"})])["2026-08-05"]
    assert day["expenditure_kcal"] == 3100.0
    assert day["tdee_kcal"] == day["expenditure_kcal"]


def test_a_missing_expenditure_leaves_tdee_absent(frozen_clock):
    day = mf.build_summary_day_items([summary_row()])["2026-08-05"]
    assert "tdee_kcal" not in day and "expenditure_kcal" not in day


def test_coaching_targets_are_stored_only_when_actually_set(frozen_clock):
    with_targets = mf.build_summary_day_items([summary_row(**{"Target Calories (kcal)": "2400", "Target Protein (g)": "200"})])[
        "2026-08-05"
    ]
    assert with_targets["target_calories_kcal"] == 2400.0
    assert with_targets["target_protein_g"] == 200.0
    without = mf.build_summary_day_items([summary_row(**{"Target Calories (kcal)": "0"})])["2026-08-05"]
    assert "target_calories_kcal" not in without


def test_a_repeated_date_in_one_summary_export_yields_one_day_not_two(frozen_clock):
    rows = [summary_row(cal="2000"), summary_row(cal="2200")]
    items = mf.build_summary_day_items(rows)
    assert list(items) == ["2026-08-05"]
    assert items["2026-08-05"]["total_calories_kcal"] == 2200.0


def test_summary_days_are_independent_partitions(frozen_clock):
    rows = [summary_row(date="2026-08-04", cal="1800"), summary_row(date="2026-08-05", cal="2200")]
    items = mf.build_summary_day_items(rows)
    assert items["2026-08-04"]["total_calories_kcal"] == 1800.0
    assert items["2026-08-05"]["total_calories_kcal"] == 2200.0


def test_a_summary_date_carrying_a_time_component_still_lands_on_the_right_partition(frozen_clock):
    items = mf.build_summary_day_items([summary_row(date="2026-08-05 00:00:00")])
    for item in items.values():
        assert re.fullmatch(r"DATE#\d{4}-\d{2}-\d{2}", item["sk"]), item["sk"]


# ══════════════════════════════════════════════════════════════════════════════
# archive_raw — the S3 raw/ layout
# ══════════════════════════════════════════════════════════════════════════════


def test_the_raw_archive_key_is_user_scoped_and_date_partitioned(monkeypatch):
    s3 = FakeS3()
    monkeypatch.setattr(mf, "s3_client", s3)
    mf.archive_raw("test-bucket", "uploads/macrofactor/export.csv", b"a,b\n1,2\n")
    key = s3.puts[0]["Key"]
    assert re.fullmatch(rf"raw/{mf.USER_ID}/macrofactor/\d{{4}}/\d{{2}}/export\.csv", key), key


def test_a_subfolder_separates_the_workout_and_summary_archives(monkeypatch):
    s3 = FakeS3()
    monkeypatch.setattr(mf, "s3_client", s3)
    mf.archive_raw("test-bucket", "uploads/macrofactor/w.csv", b"x", subfolder="workouts")
    mf.archive_raw("test-bucket", "uploads/macrofactor/s.csv", b"x", subfolder="daily_summary")
    keys = [p["Key"] for p in s3.puts]
    assert "/macrofactor/workouts/" in keys[0]
    assert "/macrofactor/daily_summary/" in keys[1]


def test_the_archive_stores_the_bytes_verbatim_as_csv(monkeypatch):
    s3 = FakeS3()
    monkeypatch.setattr(mf, "s3_client", s3)
    payload = b"\xef\xbb\xbfDate,Food Name\n2026-08-05,Eggs\n"
    mf.archive_raw("test-bucket", "uploads/macrofactor/export.csv", payload)
    put = s3.puts[0]
    assert put["Body"] == payload
    assert put["ContentType"] == "text/csv"
    assert put["Bucket"] == "test-bucket"


def test_the_archive_keeps_only_the_basename_of_a_nested_upload_key(monkeypatch):
    s3 = FakeS3()
    monkeypatch.setattr(mf, "s3_client", s3)
    mf.archive_raw("test-bucket", "uploads/macrofactor/2026/08/nested-export.csv", b"x")
    assert s3.puts[0]["Key"].endswith("/nested-export.csv")
    assert "uploads/" not in s3.puts[0]["Key"]


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (tranche-2 discovery): SOURCE_REGISTRY['macrofactor']['raw_layout'] is "
        "None, commented 'CSVs land via the dropbox transport, not a raw/ archive' — "
        "but archive_raw() writes raw/<user>/macrofactor[/<subfolder>]/YYYY/MM/<file> "
        "on EVERY ingest, including the unknown-format forensic path. X-9 says replay "
        "tooling must read the layout from the registry instead of guessing; for this "
        "source the registry hides an archive that exists."
    ),
)
def test_the_registry_describes_the_raw_archive_this_lambda_actually_writes(monkeypatch):
    s3 = FakeS3()
    monkeypatch.setattr(mf, "s3_client", s3)
    mf.archive_raw("test-bucket", "uploads/macrofactor/export.csv", b"x")
    written_prefix = "/".join(s3.puts[0]["Key"].split("/")[:3])
    layout = SOURCE_REGISTRY["macrofactor"]["raw_layout"]
    assert layout is not None, "registry claims macrofactor has no raw/ archive"
    assert layout["prefix"] == written_prefix


# ══════════════════════════════════════════════════════════════════════════════
# lambda_handler — event handling, routing, and the write path
# ══════════════════════════════════════════════════════════════════════════════


def test_an_s3_notification_event_is_read_from_the_record(monkeypatch):
    payload = csv_bytes(NUTRITION_HEADERS, [food_row(**{"Calories (kcal)": "500"})])
    table, s3 = FakeTable(), FakeS3(payload)
    monkeypatch.setattr(mf, "s3_client", s3)
    monkeypatch.setattr(mf, "table", table)
    monkeypatch.setattr(mf, "datetime", _FrozenDatetime)
    event = {"Records": [{"s3": {"bucket": {"name": "notify-bucket"}, "object": {"key": "uploads/macrofactor/a.csv"}}}]}
    response = mf.lambda_handler(event, None)
    assert response["statusCode"] == 200
    assert s3.gets == [("notify-bucket", "uploads/macrofactor/a.csv")]


def test_a_direct_bucket_and_key_invocation_is_supported(monkeypatch):
    payload = csv_bytes(NUTRITION_HEADERS, [food_row(**{"Calories (kcal)": "500"})])
    response, _, s3 = invoke(monkeypatch, payload, key="uploads/macrofactor/manual.csv")
    assert response["statusCode"] == 200
    assert s3.gets == [("test-bucket", "uploads/macrofactor/manual.csv")]


def test_an_event_with_no_object_reference_is_rejected_without_reading_s3(monkeypatch):
    s3 = FakeS3(b"")
    monkeypatch.setattr(mf, "s3_client", s3)
    response = mf.lambda_handler({"detail": "something else"}, None)
    assert response["statusCode"] == 400
    assert s3.gets == []


def test_an_empty_csv_writes_nothing_and_does_not_raise(monkeypatch):
    response, table, _ = invoke(monkeypatch, b"")
    assert response["statusCode"] == 200
    assert table.puts == []


def test_a_header_only_csv_writes_nothing(monkeypatch):
    response, table, _ = invoke(monkeypatch, csv_bytes(NUTRITION_HEADERS, []))
    assert response["statusCode"] == 200
    assert table.puts == []


def test_a_utf8_bom_does_not_hide_the_first_column(monkeypatch):
    """Excel-exported CSVs carry a BOM; without utf-8-sig the 'Date' header
    becomes '﻿Date' and every row silently fails to parse."""
    payload = csv_bytes(NUTRITION_HEADERS, [food_row(**{"Calories (kcal)": "500"})], bom=True)
    response, table, _ = invoke(monkeypatch, payload)
    assert len(table.puts) == 1
    assert table.puts[0]["sk"] == "DATE#2026-08-05"


def test_a_quoted_comma_in_a_food_name_survives_the_round_trip(monkeypatch):
    payload = csv_bytes(NUTRITION_HEADERS, [food_row(name="Chicken, grilled, skinless", **{"Calories (kcal)": "300"})])
    _, table, _ = invoke(monkeypatch, payload)
    stored = table.items[(mf.PK, "DATE#2026-08-05")]
    assert stored["food_log"][0]["food_name"] == "Chicken, grilled, skinless"


def test_a_nutrition_upload_writes_one_item_per_logged_day(monkeypatch):
    rows = [
        food_row(date="2026-08-04", **{"Calories (kcal)": "1800"}),
        food_row(date="2026-08-05", **{"Calories (kcal)": "2000"}),
        food_row(date="2026-08-05", time="12:00", name="Lunch", **{"Calories (kcal)": "600"}),
    ]
    response, table, _ = invoke(monkeypatch, csv_bytes(NUTRITION_HEADERS, rows))
    assert len(table.items) == 2
    assert table.items[(mf.PK, "DATE#2026-08-05")]["total_calories_kcal"] == 2600
    assert response["statusCode"] == 200


def test_no_native_float_ever_reaches_the_dynamodb_write(monkeypatch):
    """boto3 rejects Python floats — the whole nested item must be Decimal."""
    row = food_row(time="12:00", **{"Serving Qty": "1.5", "Serving Weight (g)": "112.5"})
    for column in mf.NUTRIENT_COLUMNS:
        row[column] = "12.5"
    _, table, _ = invoke(monkeypatch, csv_bytes(NUTRITION_HEADERS, [row]))
    assert table.puts, "expected a write"
    offenders = find_floats(table.puts[0])
    assert offenders == [], offenders


def test_no_native_float_reaches_the_write_on_the_workout_path(monkeypatch):
    rows = [workout_row(**{"Weight (lbs)": "137.5", "Reps": "5", "RIR": "2"})]
    _, table, _ = invoke(monkeypatch, csv_bytes(WORKOUT_HEADERS, rows))
    assert table.puts and find_floats(table.puts[0]) == []


def test_no_native_float_reaches_the_write_on_the_summary_path(monkeypatch):
    rows = [summary_row(cal="2000.5", **{"Weight (lbs)": "321.6", "Expenditure": "3100.4"})]
    _, table, _ = invoke(monkeypatch, csv_bytes(SUMMARY_HEADERS, rows))
    assert table.puts and find_floats(table.puts[0]) == []


def test_a_pre_genesis_day_is_stamped_as_pilot_data(monkeypatch):
    """#482/X-6: an unstamped backfill would surface pre-genesis data as current."""
    before = (datetime.fromisoformat(EXPERIMENT_START_DATE) - timedelta(days=1)).strftime("%Y-%m-%d")
    payload = csv_bytes(NUTRITION_HEADERS, [food_row(date=before, **{"Calories (kcal)": "2000"})])
    _, table, _ = invoke(monkeypatch, payload)
    assert table.items[(mf.PK, f"DATE#{before}")]["phase"] == "pilot"


def test_a_genesis_day_is_stamped_with_the_current_experiment_phase(monkeypatch):
    payload = csv_bytes(NUTRITION_HEADERS, [food_row(date=EXPERIMENT_START_DATE, **{"Calories (kcal)": "2000"})])
    _, table, _ = invoke(monkeypatch, payload)
    assert table.items[(mf.PK, f"DATE#{EXPERIMENT_START_DATE}")]["phase"] == EXPERIMENT_PHASE_CURRENT


def test_re_ingesting_the_same_export_does_not_double_count_the_day(monkeypatch):
    """Idempotency: the day is fully recomputed from the file and overwritten."""
    payload = csv_bytes(NUTRITION_HEADERS, [food_row(**{"Calories (kcal)": "2000", "Protein (g)": "150"})])
    table = FakeTable()
    invoke(monkeypatch, payload, table=table)
    invoke(monkeypatch, payload, table=table)
    assert len(table.items) == 1
    stored = table.items[(mf.PK, "DATE#2026-08-05")]
    assert stored["total_calories_kcal"] == 2000
    assert stored["entries_count"] == 1
    assert len(table.puts) == 2  # written twice, but the day never accumulates


def test_a_later_export_replaces_rather_than_merges_the_overlapping_day(monkeypatch):
    table = FakeTable()
    invoke(monkeypatch, csv_bytes(NUTRITION_HEADERS, [food_row(**{"Calories (kcal)": "2000"})]), table=table)
    corrected = [food_row(name="Eggs (corrected)", **{"Calories (kcal)": "1600"})]
    invoke(monkeypatch, csv_bytes(NUTRITION_HEADERS, corrected), table=table)
    stored = table.items[(mf.PK, "DATE#2026-08-05")]
    assert stored["total_calories_kcal"] == 1600
    assert stored["food_log"][0]["food_name"] == "Eggs (corrected)"


def test_a_workout_upload_routes_to_the_workout_partition_and_archive(monkeypatch):
    rows = [workout_row(**{"Weight (lbs)": "135", "Reps": "5"})]
    response, table, s3 = invoke(monkeypatch, csv_bytes(WORKOUT_HEADERS, rows))
    assert list(table.items) == [(mf.PK_WORKOUTS, "DATE#2026-08-05")]
    assert "/macrofactor/workouts/" in s3.puts[0]["Key"]
    import json

    assert json.loads(response["body"])["csv_type"] == "workout"


def test_a_summary_upload_routes_to_the_summary_archive_folder(monkeypatch):
    response, table, s3 = invoke(monkeypatch, csv_bytes(SUMMARY_HEADERS, [summary_row()]))
    assert list(table.items) == [(mf.PK, "DATE#2026-08-05")]
    assert "/macrofactor/daily_summary/" in s3.puts[0]["Key"]
    import json

    assert json.loads(response["body"])["csv_type"] == "daily_summary"


def test_a_nutrition_upload_archives_at_the_source_root_with_no_subfolder(monkeypatch):
    payload = csv_bytes(NUTRITION_HEADERS, [food_row(**{"Calories (kcal)": "500"})])
    _, _, s3 = invoke(monkeypatch, payload)
    assert re.fullmatch(rf"raw/{mf.USER_ID}/macrofactor/\d{{4}}/\d{{2}}/export\.csv", s3.puts[0]["Key"])


def test_the_response_reports_what_was_parsed_and_what_was_written(monkeypatch):
    import json

    rows = [
        food_row(date="2026-08-04", **{"Calories (kcal)": "1800"}),
        food_row(date="2026-08-05", **{"Calories (kcal)": "2000"}),
        {"Date": "", "Food Name": ""},
    ]
    response, _, _ = invoke(monkeypatch, csv_bytes(NUTRITION_HEADERS, rows), key="uploads/macrofactor/aug.csv")
    body = json.loads(response["body"])
    assert body["source_file"] == "uploads/macrofactor/aug.csv"
    assert body["csv_type"] == "nutrition"
    assert body["rows_parsed"] == 3
    assert body["days_written"] == 2


def test_a_validator_veto_blocks_the_write_and_archives_the_rejected_item(monkeypatch):
    """DATA-2: a CRITICAL validation failure must never reach DynamoDB — it goes
    to the validation-errors/ audit prefix instead."""
    archived = []

    class _Rejection:
        should_skip_ddb = True
        errors = ["Required field missing: 'entries_count'"]
        warnings = []

        def archive_to_s3(self, s3_client, bucket, item):
            archived.append((bucket, item["sk"]))

    monkeypatch.setattr(ingestion_validator, "validate_item", lambda *a, **k: _Rejection())
    payload = csv_bytes(NUTRITION_HEADERS, [food_row(**{"Calories (kcal)": "2000"})])
    response, table, _ = invoke(monkeypatch, payload)
    assert table.puts == []
    assert archived == [("test-bucket", "DATE#2026-08-05")]
    import json

    assert json.loads(response["body"])["days_written"] == 0


def test_a_validation_warning_does_not_block_the_write(monkeypatch):
    class _Warned:
        should_skip_ddb = False
        errors = []
        warnings = ["Value out of expected range 'total_calories_kcal'"]

    monkeypatch.setattr(ingestion_validator, "validate_item", lambda *a, **k: _Warned())
    payload = csv_bytes(NUTRITION_HEADERS, [food_row(**{"Calories (kcal)": "2000"})])
    _, table, _ = invoke(monkeypatch, payload)
    assert len(table.puts) == 1


def test_a_missing_size_guard_falls_back_to_a_direct_put_rather_than_failing(monkeypatch):
    """REL-3's import is optional; losing it must degrade, not drop the day."""
    real_import = __import__

    def _blocked(name, *args, **kwargs):
        if name == "common.item_size_guard":
            raise ImportError("simulated: size guard unavailable")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", _blocked)
    payload = csv_bytes(NUTRITION_HEADERS, [food_row(**{"Calories (kcal)": "2000"})])
    _, table, _ = invoke(monkeypatch, payload)
    assert len(table.puts) == 1


def test_the_written_item_carries_the_frozen_ingest_stamp(monkeypatch):
    payload = csv_bytes(NUTRITION_HEADERS, [food_row(**{"Calories (kcal)": "2000"})])
    _, table, _ = invoke(monkeypatch, payload)
    assert table.puts[0]["ingested_at"] == FROZEN_STAMP


# ══════════════════════════════════════════════════════════════════════════════
# Cross-module set guards — the writer and its validator must not drift apart
# ══════════════════════════════════════════════════════════════════════════════


def test_every_macrofactor_total_the_validator_checks_is_a_real_nutrient_field():
    """Guard the SET (both sides derived): a nutrient rename that misses the
    DATA-2 schema would silently disable that field's range check."""
    schema = _SCHEMAS["macrofactor"]
    checked = set(schema.get("typed_fields", {})) | set(schema.get("range_checks", {})) | set(schema.get("at_least_one_of", []))
    totals = {f for f in checked if f.startswith("total_")}
    unknown = {f for f in totals if f[len("total_") :] not in mf.NUTRIENT_FIELD_NAMES}
    assert unknown == set()


def test_the_nutrition_writer_emits_every_field_the_validator_requires(monkeypatch):
    schema = _SCHEMAS["macrofactor"]
    payload = csv_bytes(NUTRITION_HEADERS, [food_row(**{"Calories (kcal)": "2000", "Protein (g)": "150"})])
    _, table, _ = invoke(monkeypatch, payload)
    written = table.puts[0]
    missing = [f for f in schema["required_fields"] if written.get(f) is None]
    assert missing == []


def test_the_summary_writer_emits_every_field_the_validator_requires(monkeypatch):
    schema = _SCHEMAS["macrofactor"]
    _, table, _ = invoke(monkeypatch, csv_bytes(SUMMARY_HEADERS, [summary_row()]))
    written = table.puts[0]
    missing = [f for f in schema["required_fields"] if f not in written]
    assert missing == []


def test_the_workout_writer_emits_every_field_its_validator_requires(monkeypatch):
    schema = _SCHEMAS["macrofactor_workouts"]
    rows = [workout_row(**{"Weight (lbs)": "135", "Reps": "5"})]
    _, table, _ = invoke(monkeypatch, csv_bytes(WORKOUT_HEADERS, rows))
    written = table.puts[0]
    missing = [f for f in schema["required_fields"] if written.get(f) is None]
    assert missing == []
    assert all(written.get(f) is not None for f in schema["at_least_one_of"])


def test_both_macrofactor_partitions_are_registered_sources_with_their_own_schemas():
    """The workout export writes a SECOND partition; a source the DATA-2 layer
    does not know falls back to the permissive default schema silently."""
    assert "macrofactor" in SOURCE_REGISTRY
    assert set(_SCHEMAS) >= {"macrofactor", "macrofactor_workouts"}
    assert mf.PK != mf.PK_WORKOUTS
