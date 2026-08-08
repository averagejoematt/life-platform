"""tests/test_nutrition_review_behavior.py — behavioural contracts for the
Saturday nutrition review email (`lambdas/emails/nutrition_review_lambda.py`).

The only pre-existing coverage of this module is the `build_email_html` golden
snapshot in tests/test_email_render_goldens.py, which pins the chrome but
asserts nothing about the *numbers* a reader sees or about what the panel
prompt is told. This file covers the contracts a caller — ultimately Matthew
reading the email on a Saturday morning — actually depends on:

  * the extract_* family and compute_weekly_summary, pinned to hand-derived
    arithmetic (never "whatever the code returns");
  * ADR-104 honest numbers: a day with no logged food must not surface as
    0 kcal / 0 g protein, and an absent CGM/DEXA/weight section must be
    visibly absent rather than fabricated;
  * the reader-visible claims of build_summary_table / build_email_html
    (which values appear, which rows exist) — not the exact HTML/CSS;
  * the AI path: the prompt must carry the data it claims to summarise, and a
    failed or blocked AI call must degrade honestly;
  * lambda_handler, which never sends mail here — `ses` is always a fake.

Clock discipline: every test that touches "now" freezes it via `_FrozenDatetime`
monkeypatched onto the module (fixture-date + real `datetime.now()` is a time
bomb). Fakes are hand-rolled and bounded — no MagicMock inside a pagination
loop.

Tests that document a DEFECT in current behaviour are marked xfail with a
`DEFECT (tranche-2 discovery)` reason; they assert the behaviour the reader
should get, and will flip green when the defect is fixed.
"""

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lambdas"))
sys.path.insert(0, str(ROOT / "lambdas" / "emails"))

# The module reads these at import time (RECIPIENT/SENDER/S3_BUCKET are
# os.environ[...] lookups, not .get) and builds boto3 clients at module level.
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("EMAIL_RECIPIENT", "test@example.com")
os.environ.setdefault("EMAIL_SENDER", "noreply@example.com")

import nutrition_review_lambda as m  # noqa: E402
from ai import ai_output_validator as aiv  # noqa: E402
from experiment.phase_filter import with_phase_filter  # noqa: E402

# ──────────────────────────────────────────────────────────────────────────────
# Frozen clock — Saturday 2026-06-13 17:00 UTC (the lambda's real fire slot)
# ──────────────────────────────────────────────────────────────────────────────

FROZEN_NOW = datetime(2026, 6, 13, 17, 0, 0, tzinfo=timezone.utc)


class _FrozenDatetime(datetime):
    """`datetime` subclass with a pinned `now()`/`utcnow()`.

    A subclass (rather than a Mock) keeps `strptime`, arithmetic and `.date()`
    working, which the module uses on the same name.
    """

    @classmethod
    def now(cls, tz=None):
        return FROZEN_NOW if tz else FROZEN_NOW.replace(tzinfo=None)

    @classmethod
    def utcnow(cls):
        return FROZEN_NOW.replace(tzinfo=None)


@pytest.fixture
def frozen_clock(monkeypatch):
    monkeypatch.setattr(m, "datetime", _FrozenDatetime)
    return FROZEN_NOW


# Windows the module derives from the frozen clock (hand-derived):
#   this week  = today-7 .. today-1  = 2026-06-06 .. 2026-06-12
#   prior week = today-14 .. today-8 = 2026-05-30 .. 2026-06-05
#   weight     = today-30            = 2026-05-14
W1_START, W1_END = "2026-06-06", "2026-06-12"
W2_START, W2_END = "2026-05-30", "2026-06-05"
WEIGHT_START = "2026-05-14"

DATES = {"this_start": W1_START, "this_end": W1_END, "prior_start": W2_START, "prior_end": W2_END}


# ──────────────────────────────────────────────────────────────────────────────
# Hand-rolled bounded fakes
# ──────────────────────────────────────────────────────────────────────────────


class FakeTable:
    """Bounded DynamoDB Table stand-in.

    `items_by_pk` maps a partition key to its rows (sk-ordered ascending, the
    way DynamoDB serves them). `pages_by_pk` maps a pk to an explicit list of
    pages so pagination can be exercised without an unbounded mock.
    """

    def __init__(self, items_by_pk=None, pages_by_pk=None):
        self.items_by_pk = {k: list(v) for k, v in (items_by_pk or {}).items()}
        self.pages_by_pk = {k: [list(p) for p in v] for k, v in (pages_by_pk or {}).items()}
        self.queries = []
        self.puts = []
        self.put_error = None
        self.query_errors = set()  # pks whose query raises

    def query(self, **kwargs):
        self.queries.append(kwargs)
        pk = kwargs["ExpressionAttributeValues"][":pk"]
        if pk in self.query_errors:
            raise RuntimeError(f"boom: {pk}")
        if pk in self.pages_by_pk:
            pages = self.pages_by_pk[pk]
            idx = kwargs.get("ExclusiveStartKey", {}).get("_page", 0)
            resp = {"Items": list(pages[idx])}
            if idx + 1 < len(pages):
                resp["LastEvaluatedKey"] = {"_page": idx + 1}
            return resp
        items = list(self.items_by_pk.get(pk, []))
        vals = kwargs["ExpressionAttributeValues"]
        if ":s" in vals and ":e" in vals:
            items = [i for i in items if vals[":s"] <= i.get("sk", "") <= vals[":e"]]
        if kwargs.get("ScanIndexForward") is False:
            items = list(reversed(items))
        if "Limit" in kwargs:
            items = items[: kwargs["Limit"]]
        return {"Items": items}

    def put_item(self, Item=None, **kwargs):
        if self.put_error:
            raise self.put_error
        self.puts.append(Item)


class FakeSES:
    def __init__(self):
        self.sent = []

    def send_email(self, **kwargs):
        self.sent.append(kwargs)
        return {"MessageId": "fake"}


class FakeInsightWriter:
    def __init__(self, context=""):
        self.context = context
        self.written = []

    def build_insights_context(self, **kwargs):
        return self.context

    def write_insight(self, **kwargs):
        self.written.append(kwargs)


class FakeS3:
    """Bounded S3 stand-in serving one JSON body for the board config key."""

    def __init__(self, config=None, error=None):
        self.config = config
        self.error = error
        self.calls = []

    def get_object(self, Bucket=None, Key=None):
        self.calls.append((Bucket, Key))
        if self.error:
            raise self.error

        class _Body:
            def __init__(self, payload):
                self._payload = payload

            def read(self):
                return json.dumps(self._payload).encode("utf-8")

        return {"Body": _Body(self.config)}


# ──────────────────────────────────────────────────────────────────────────────
# HTML readers — assert what a reader sees, not the CSS
# ──────────────────────────────────────────────────────────────────────────────


def _rows(html):
    """Return the table as a list of rows, each a list of stripped cell texts."""
    out = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S):
        cells = [re.sub(r"\s+", " ", c).strip() for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S)]
        out.append(cells)
    return out


def _cell_colors(html, row_index):
    """Colors of each cell in a row — the reader's green/amber/red signal."""
    tr = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S)[row_index]
    return [
        (re.search(r"color:(#[0-9a-fA-F]{6})", c).group(1) if re.search(r"color:(#[0-9a-fA-F]{6})", c) else None)
        for c in re.findall(r"<td[^>]*>", tr)
    ]


def _day_row(html, label):
    for row in _rows(html):
        if row and row[0] == label:
            return row
    return None


def _avg_row(html):
    return _day_row(html, "AVG")


# ──────────────────────────────────────────────────────────────────────────────
# Fixture builders
# ──────────────────────────────────────────────────────────────────────────────


def _mf_day(cal=None, protein=None, carbs=None, fat=None, fiber=None, micro=None, food_log=None, **extra):
    rec = {}
    if cal is not None:
        rec["total_calories_kcal"] = cal
    if protein is not None:
        rec["total_protein_g"] = protein
    if carbs is not None:
        rec["total_carbs_g"] = carbs
    if fat is not None:
        rec["total_fat_g"] = fat
    if fiber is not None:
        rec["total_fiber_g"] = fiber
    if micro is not None:
        rec["micronutrient_avg_pct"] = micro
    if food_log is not None:
        rec["food_log"] = food_log
    rec.update(extra)
    return rec


PROFILE = {
    "calorie_target": 1800,
    "protein_target_g": 190,
    "goal_weight_lbs": 185,
    "journey_start_date": "2026-06-01",
    "journey_start_weight_lbs": 321.6,
}


def _gathered(**over):
    data = {
        "macrofactor_this": {
            "2026-06-06": _mf_day(cal=1700, protein=180, carbs=140, fat=60, fiber=32, micro=74),
            "2026-06-07": _mf_day(cal=1900, protein=200, carbs=160, fat=70, fiber=28, micro=66),
        },
        "macrofactor_prior": {"2026-05-30": _mf_day(cal=2100, protein=150, carbs=200, fat=80, fiber=20, micro=55)},
        "withings": {"2026-05-14": {"weight_lbs": 315.0}, "2026-06-12": {"weight_lbs": 309.4}},
        "strava": {},
        "cgm": {},
        "genome_snps": [],
        "latest_lab": None,
        "latest_dexa": None,
        "supplements": {},
        "prev_review": None,
        "profile": dict(PROFILE),
        "dates": dict(DATES),
    }
    data.update(over)
    return data


@pytest.fixture
def handler_env(monkeypatch, frozen_clock):
    """Wire lambda_handler to fakes. Mail is NEVER sent."""
    ses = FakeSES()
    table = FakeTable()
    writer = FakeInsightWriter()
    calls = {"anthropic": [], "validate": []}

    monkeypatch.setattr(m, "ses", ses)
    monkeypatch.setattr(m, "table", table)
    monkeypatch.setattr(m, "insight_writer", writer)
    monkeypatch.setattr(m, "_HAS_INSIGHT_WRITER", True)
    monkeypatch.setattr(m, "_HAS_AI_VALIDATOR", True)
    # Default: no S3 board config -> the hardcoded fallback panel prompt.
    monkeypatch.setattr(m, "_build_nutrition_prompt_from_config", lambda cal, pro: None)

    state = {"ai": "<p>Panel commentary about the week.</p>", "ai_error": None, "data": _gathered()}

    def _fake_call(system, user_message):
        calls["anthropic"].append((system, user_message))
        if state["ai_error"]:
            raise state["ai_error"]
        return state["ai"]

    monkeypatch.setattr(m, "call_anthropic", _fake_call)
    monkeypatch.setattr(m, "gather_nutrition_data", lambda: state["data"])

    return {
        "ses": ses,
        "table": table,
        "writer": writer,
        "calls": calls,
        "state": state,
        "monkeypatch": monkeypatch,
    }


def _sent_html(env):
    return env["ses"].sent[0]["Content"]["Simple"]["Body"]["Html"]["Data"]


def _sent_subject(env):
    return env["ses"].sent[0]["Content"]["Simple"]["Subject"]["Data"]


# ══════════════════════════════════════════════════════════════════════════════
# extract_daily_nutrition
# ══════════════════════════════════════════════════════════════════════════════


def test_daily_nutrition_returns_one_entry_per_day_in_date_order():
    days = m.extract_daily_nutrition(
        {
            "2026-06-08": _mf_day(cal=1800),
            "2026-06-06": _mf_day(cal=1600),
            "2026-06-07": _mf_day(cal=1700),
        }
    )
    assert [d["date"] for d in days] == ["2026-06-06", "2026-06-07", "2026-06-08"]


def test_daily_nutrition_carries_the_logged_totals_verbatim():
    days = m.extract_daily_nutrition({"2026-06-06": _mf_day(cal=1743, protein=187, carbs=142, fat=61, fiber=33.5, micro=71.2)})
    d = days[0]
    assert (d["total_calories"], d["total_protein_g"], d["total_carbs_g"]) == (1743.0, 187.0, 61.0 * 0 + 142.0)
    assert (d["total_fat_g"], d["total_fiber_g"], d["micronutrient_avg_pct"]) == (61.0, 33.5, 71.2)


def test_a_day_with_no_logged_food_reports_absence_not_zero():
    """ADR-104: nothing logged is not the same claim as 'ate 0 g protein'."""
    days = m.extract_daily_nutrition({"2026-06-06": {"food_log": []}})
    d = days[0]
    assert d["total_calories"] is None
    assert d["total_protein_g"] is None
    assert d["micronutrient_avg_pct"] is None
    assert d["foods"] == []


def test_daily_nutrition_tolerates_a_record_with_no_food_log_key():
    days = m.extract_daily_nutrition({"2026-06-06": _mf_day(cal=1800, protein=190)})
    assert days[0]["foods"] == []
    assert days[0]["total_protein_g"] == 190.0


def test_supplement_entries_are_excluded_from_the_meal_list():
    """Panel rule 2: supplements count toward micros but are not meals."""
    days = m.extract_daily_nutrition(
        {
            "2026-06-06": _mf_day(
                cal=1800,
                food_log=[
                    {"food_name": "Chicken thighs", "calories_kcal": 400, "protein_g": 45},
                    {"food_name": "Magnesium supplement", "calories_kcal": 0, "protein_g": 0},
                ],
            )
        }
    )
    names = [f["name"] for f in days[0]["foods"]]
    assert names == ["Chicken thighs"]


def test_supplement_exclusion_is_case_insensitive():
    days = m.extract_daily_nutrition({"2026-06-06": _mf_day(food_log=[{"food_name": "Vitamin D SUPPLEMENT"}])})
    assert days[0]["foods"] == []


def test_excluding_a_supplement_does_not_change_the_day_totals():
    rec = _mf_day(cal=1800, protein=190, food_log=[{"food_name": "Creatine supplement", "protein_g": 0}])
    day = m.extract_daily_nutrition({"2026-06-06": rec})[0]
    assert day["total_calories"] == 1800.0 and day["total_protein_g"] == 190.0
    assert day["foods"] == []


def test_a_food_item_keeps_its_name_time_and_macros():
    day = m.extract_daily_nutrition(
        {
            "2026-06-06": _mf_day(
                food_log=[
                    {"food_name": "Carnitas bowl", "time": "12:40", "calories_kcal": 720, "protein_g": 52, "carbs_g": 60, "fat_g": 24}
                ]
            )
        }
    )[0]
    food = day["foods"][0]
    assert food["name"] == "Carnitas bowl"
    assert food["time"] == "12:40"
    assert (food["cal"], food["protein_g"], food["carbs_g"], food["fat_g"]) == (720.0, 52.0, 60.0, 24.0)


def test_an_unnamed_untimed_food_item_says_so_rather_than_guessing():
    day = m.extract_daily_nutrition({"2026-06-06": _mf_day(food_log=[{"calories_kcal": 100}])})[0]
    assert day["foods"][0]["name"] == "unknown"
    assert day["foods"][0]["time"] == "?"


def test_a_food_item_with_no_fiber_figure_reports_absence_not_zero():
    day = m.extract_daily_nutrition({"2026-06-06": _mf_day(food_log=[{"food_name": "Rice", "calories_kcal": 200}])})[0]
    assert day["foods"][0]["fiber_g"] is None


def test_numeric_strings_in_a_record_are_parsed_as_numbers():
    day = m.extract_daily_nutrition({"2026-06-06": {"total_calories_kcal": "1750", "total_protein_g": "188.5"}})[0]
    assert day["total_calories"] == 1750.0
    assert day["total_protein_g"] == 188.5


def test_an_unparseable_total_degrades_to_absence_rather_than_crashing():
    day = m.extract_daily_nutrition({"2026-06-06": {"total_calories_kcal": "n/a", "total_protein_g": 180}})[0]
    assert day["total_calories"] is None
    assert day["total_protein_g"] == 180.0


def test_micronutrient_sufficiency_detail_is_passed_through_untouched():
    suff = {"vitamin_d": 41, "choline": 33}
    day = m.extract_daily_nutrition({"2026-06-06": {"micronutrient_sufficiency": suff}})[0]
    assert day["micronutrient_sufficiency"] == suff


def test_no_macrofactor_days_yields_an_empty_list():
    assert m.extract_daily_nutrition({}) == []


# ══════════════════════════════════════════════════════════════════════════════
# extract_weight_trend
# ══════════════════════════════════════════════════════════════════════════════


def test_weight_change_is_latest_minus_earliest_over_the_window():
    trend = m.extract_weight_trend({"2026-05-14": {"weight_lbs": 315.0}, "2026-06-12": {"weight_lbs": 309.4}})
    assert trend["earliest_weight_lbs"] == 315.0
    assert trend["latest_weight_lbs"] == 309.4
    assert trend["change_30d_lbs"] == -5.6  # 309.4 - 315.0, 1 dp


def test_weight_endpoints_follow_date_order_not_insertion_order():
    trend = m.extract_weight_trend({"2026-06-12": {"weight_lbs": 309.4}, "2026-05-14": {"weight_lbs": 315.0}})
    assert trend["earliest_weight_lbs"] == 315.0 and trend["latest_weight_lbs"] == 309.4


def test_weight_gain_reports_a_positive_change():
    trend = m.extract_weight_trend({"2026-05-14": {"weight_lbs": 300.0}, "2026-06-12": {"weight_lbs": 302.2}})
    assert trend["change_30d_lbs"] == 2.2


def test_only_the_last_seven_weigh_ins_are_carried_into_the_prompt():
    data = {f"2026-06-{d:02d}": {"weight_lbs": 320.0 - d} for d in range(1, 13)}
    trend = m.extract_weight_trend(data)
    assert trend["measurements"] == 12
    assert len(trend["readings"]) == 7
    assert [r["date"] for r in trend["readings"]] == [f"2026-06-{d:02d}" for d in range(6, 13)]


def test_days_without_a_weigh_in_are_not_counted_as_measurements():
    trend = m.extract_weight_trend(
        {"2026-06-10": {"weight_lbs": 310.0}, "2026-06-11": {"body_fat_pct": 31.0}, "2026-06-12": {"weight_lbs": 309.0}}
    )
    assert trend["measurements"] == 2


def test_the_alternate_weight_lb_field_name_is_accepted():
    trend = m.extract_weight_trend({"2026-06-12": {"weight_lb": 308.8}})
    assert trend["latest_weight_lbs"] == 308.8


def test_no_weigh_ins_at_all_returns_absence_not_a_zero_change():
    assert m.extract_weight_trend({}) is None
    assert m.extract_weight_trend({"2026-06-12": {"body_fat_pct": 31.0}}) is None


def test_a_single_weigh_in_reports_zero_change_over_one_measurement():
    trend = m.extract_weight_trend({"2026-06-12": {"weight_lbs": 309.4}})
    assert trend["change_30d_lbs"] == 0.0
    assert trend["measurements"] == 1


# ══════════════════════════════════════════════════════════════════════════════
# extract_training
# ══════════════════════════════════════════════════════════════════════════════


def test_every_activity_across_the_week_is_carried_with_its_date():
    acts = m.extract_training(
        {
            "2026-06-06": {"activities": [{"sport_type": "Run", "name": "AM"}, {"sport_type": "WeightTraining", "name": "PM"}]},
            "2026-06-08": {"activities": [{"sport_type": "Walk", "name": "Dog"}]},
        }
    )
    assert [(a["date"], a["type"]) for a in acts] == [
        ("2026-06-06", "Run"),
        ("2026-06-06", "WeightTraining"),
        ("2026-06-08", "Walk"),
    ]


def test_duration_is_elapsed_seconds_converted_to_minutes():
    acts = m.extract_training({"2026-06-06": {"activities": [{"elapsed_time_seconds": 3720}]}})
    assert acts[0]["duration_min"] == 62.0  # 3720 / 60


def test_duration_falls_back_to_the_precomputed_minutes_field():
    acts = m.extract_training({"2026-06-06": {"activities": [{"moving_time_minutes": 47.5}]}})
    assert acts[0]["duration_min"] == 47.5


def test_distance_is_metres_converted_to_miles_at_two_decimals():
    acts = m.extract_training({"2026-06-06": {"activities": [{"distance_meters": 5000}]}})
    assert acts[0]["distance_miles"] == 3.11  # 5000 / 1609.34


def test_distance_falls_back_to_a_precomputed_miles_field():
    acts = m.extract_training({"2026-06-06": {"activities": [{"distance_miles": 2.4}]}})
    assert acts[0]["distance_miles"] == 2.4


def test_activity_type_prefers_sport_type_then_type_then_says_unknown():
    acts = m.extract_training(
        {
            "2026-06-06": {
                "activities": [
                    {"sport_type": "TrailRun", "type": "Run"},
                    {"type": "Ride"},
                    {},
                ]
            }
        }
    )
    assert [a["type"] for a in acts] == ["TrailRun", "Ride", "?"]


def test_heart_rate_and_calories_are_absent_when_the_device_did_not_record_them():
    acts = m.extract_training({"2026-06-06": {"activities": [{"sport_type": "Walk"}]}})
    assert acts[0]["avg_hr"] is None
    assert acts[0]["calories"] is None


def test_a_malformed_activities_value_is_skipped_without_crashing():
    acts = m.extract_training({"2026-06-06": {"activities": "none"}, "2026-06-07": {"activities": [{"sport_type": "Run"}]}})
    assert [a["type"] for a in acts] == ["Run"]


def test_a_week_with_no_training_yields_an_empty_activity_list():
    assert m.extract_training({}) == []
    assert m.extract_training({"2026-06-06": {}}) == []


# ══════════════════════════════════════════════════════════════════════════════
# extract_cgm  (#486/D-2 regression guard: the blood_glucose_* field names)
# ══════════════════════════════════════════════════════════════════════════════


def test_cgm_reads_the_blood_glucose_fields_the_aggregator_actually_writes():
    days = m.extract_cgm(
        {
            "2026-06-06": {
                "blood_glucose_avg": 104.2,
                "blood_glucose_std_dev": 17.5,
                "blood_glucose_time_in_range_pct": 88.0,
                "blood_glucose_time_above_140_pct": 4.5,
                "blood_glucose_readings_count": 288,
            }
        }
    )
    assert days[0] == {
        "date": "2026-06-06",
        "mean_mg_dl": 104.2,
        "std_dev": 17.5,
        "time_in_range_pct": 88.0,
        "time_above_140_pct": 4.5,
        "readings_count": 288.0,
    }


def test_cgm_ignores_the_legacy_glucose_field_names():
    """The pre-#486 glucose_* names matched nothing; reading them again would
    silently resurrect the bug, so a record carrying ONLY those is no data."""
    assert m.extract_cgm({"2026-06-06": {"glucose_avg": 105, "glucose_mean": 105}}) is None


def test_days_without_a_glucose_average_are_omitted():
    days = m.extract_cgm({"2026-06-06": {"blood_glucose_avg": 100.0}, "2026-06-07": {"steps": 8000}})
    assert [d["date"] for d in days] == ["2026-06-06"]


def test_no_cgm_data_at_all_is_reported_as_absent():
    assert m.extract_cgm({}) is None
    assert m.extract_cgm({"2026-06-06": {}}) is None


def test_a_cgm_day_missing_variability_reports_absence_not_zero():
    day = m.extract_cgm({"2026-06-06": {"blood_glucose_avg": 99.0}})[0]
    assert day["std_dev"] is None
    assert day["time_in_range_pct"] is None


def test_cgm_days_come_back_in_date_order():
    days = m.extract_cgm({"2026-06-08": {"blood_glucose_avg": 101}, "2026-06-06": {"blood_glucose_avg": 99}})
    assert [d["date"] for d in days] == ["2026-06-06", "2026-06-08"]


# ══════════════════════════════════════════════════════════════════════════════
# extract_genome_context
# ══════════════════════════════════════════════════════════════════════════════


def test_genome_context_carries_gene_risk_summary_and_category():
    ctx = m.extract_genome_context([{"gene": "MTHFR", "risk_level": "elevated", "summary": "reduced folate", "category": "metabolism"}])
    assert ctx == [{"gene": "MTHFR", "risk": "elevated", "summary": "reduced folate", "category": "metabolism"}]


def test_a_snp_missing_a_field_reports_absence_rather_than_a_placeholder():
    ctx = m.extract_genome_context([{"gene": "FADS2"}])
    assert ctx[0]["gene"] == "FADS2"
    assert ctx[0]["risk"] is None and ctx[0]["summary"] is None


def test_no_relevant_snps_yields_an_empty_genome_section():
    assert m.extract_genome_context([]) == []


# ══════════════════════════════════════════════════════════════════════════════
# extract_dexa_context
# ══════════════════════════════════════════════════════════════════════════════


def test_no_dexa_scan_is_reported_as_absent():
    assert m.extract_dexa_context(None) is None
    assert m.extract_dexa_context({}) is None


def test_dexa_age_in_months_is_measured_from_today(frozen_clock):
    ctx = m.extract_dexa_context({"scan_date": "2025-12-15", "body_composition": {}})
    assert ctx["months_ago"] == 6  # 180 days / 30.44, rounded


def test_dexa_body_composition_fields_are_pulled_from_the_nested_block(frozen_clock):
    ctx = m.extract_dexa_context(
        {
            "scan_date": "2026-01-10",
            "body_composition": {
                "weight_lb": 331.0,
                "body_fat_pct": 38.4,
                "lean_mass_lb": 194.2,
                "fat_mass_lb": 127.1,
                "visceral_fat_g": 1450,
                "bmd_t_score": 1.2,
                "ag_ratio": 1.08,
            },
        }
    )
    assert ctx["weight_at_scan_lbs"] == 331.0
    assert ctx["body_fat_pct"] == 38.4
    assert ctx["lean_mass_lbs"] == 194.2
    assert ctx["fat_mass_lbs"] == 127.1
    assert ctx["visceral_fat_g"] == 1450.0
    assert ctx["bmd_t_score"] == 1.2
    assert ctx["ag_ratio"] == 1.08


def test_a_dexa_record_with_no_body_composition_block_reports_absence(frozen_clock):
    ctx = m.extract_dexa_context({"scan_date": "2026-01-10"})
    assert ctx["scan_date"] == "2026-01-10"
    assert ctx["body_fat_pct"] is None and ctx["lean_mass_lbs"] is None


def test_an_unparseable_scan_date_leaves_the_age_unknown(frozen_clock):
    ctx = m.extract_dexa_context({"scan_date": "unknown", "body_composition": {}})
    assert ctx["months_ago"] is None
    assert ctx["scan_date"] == "unknown"


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (tranche-2 discovery): extract_dexa_context builds its caveat with an f-string on months_ago "
        "without checking it resolved. A DEXA record with a missing/unparseable scan_date feeds the panel prompt "
        "the literal sentence 'Scan is None months old.' — a nonsense claim handed to the AI as fact."
    ),
)
def test_an_unparseable_scan_date_does_not_produce_a_none_months_old_caveat(frozen_clock):
    ctx = m.extract_dexa_context({"scan_date": "unknown", "body_composition": {}})
    assert "None months" not in ctx["caveat"]


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (tranche-2 discovery): the DEXA caveat string is unconditional — a scan taken THIS WEEK is "
        "described to the panel as 'Scan is 0 months old. Weight has changed significantly since.' The module "
        "asserts a weight change it has not measured (ADR-104: no fabricated claims)."
    ),
)
def test_a_fresh_dexa_scan_is_not_described_as_stale(frozen_clock):
    ctx = m.extract_dexa_context({"scan_date": "2026-06-10", "body_composition": {}})
    assert ctx["months_ago"] == 0
    assert "changed significantly" not in ctx["caveat"]


# ══════════════════════════════════════════════════════════════════════════════
# compute_weekly_summary
# ══════════════════════════════════════════════════════════════════════════════


def test_weekly_summary_of_no_days_is_empty():
    assert m.compute_weekly_summary([]) == {}


def test_weekly_summary_counts_the_days_it_summarised():
    days = m.extract_daily_nutrition({f"2026-06-{d:02d}": _mf_day(cal=1800) for d in range(6, 11)})
    assert m.compute_weekly_summary(days)["days_logged"] == 5


def test_weekly_averages_are_the_mean_of_the_logged_days():
    days = m.extract_daily_nutrition(
        {
            "2026-06-06": _mf_day(cal=1700, protein=180, fiber=30),
            "2026-06-07": _mf_day(cal=1900, protein=200, fiber=34),
            "2026-06-08": _mf_day(cal=1800, protein=190, fiber=29),
        }
    )
    s = m.compute_weekly_summary(days)
    assert s["avg_calories"] == 1800.0  # (1700+1900+1800)/3
    assert s["avg_protein_g"] == 190.0  # (180+200+190)/3
    assert s["avg_fiber_g"] == 31.0  # (30+34+29)/3


def test_weekly_averages_round_to_one_decimal():
    days = m.extract_daily_nutrition({"2026-06-06": _mf_day(cal=1701), "2026-06-07": _mf_day(cal=1900)})
    assert m.compute_weekly_summary(days)["avg_calories"] == 1800.5


def test_a_day_with_nothing_logged_does_not_drag_the_average_toward_zero():
    """ADR-104: an unlogged day is missing data, not a 0-calorie day."""
    days = m.extract_daily_nutrition(
        {
            "2026-06-06": _mf_day(cal=1800, protein=190),
            "2026-06-07": {"food_log": []},
        }
    )
    s = m.compute_weekly_summary(days)
    assert s["avg_calories"] == 1800.0
    assert s["avg_protein_g"] == 190.0


def test_a_field_no_day_logged_is_reported_absent_not_zero():
    days = m.extract_daily_nutrition({"2026-06-06": _mf_day(cal=1800), "2026-06-07": _mf_day(cal=1750)})
    s = m.compute_weekly_summary(days)
    assert s["avg_calories"] == 1775.0
    assert s["avg_choline_mg"] is None
    assert s["avg_vitamin_d_mcg"] is None


def test_weekly_summary_averages_micronutrient_sufficiency():
    days = m.extract_daily_nutrition({"2026-06-06": _mf_day(micro=60), "2026-06-07": _mf_day(micro=80)})
    assert m.compute_weekly_summary(days)["avg_micronutrient_pct"] == 70.0


def test_a_single_logged_day_averages_to_itself():
    days = m.extract_daily_nutrition({"2026-06-06": _mf_day(cal=1650, protein=205)})
    s = m.compute_weekly_summary(days)
    assert (s["days_logged"], s["avg_calories"], s["avg_protein_g"]) == (1, 1650.0, 205.0)


# ══════════════════════════════════════════════════════════════════════════════
# build_summary_table — what the reader sees in the snapshot
# ══════════════════════════════════════════════════════════════════════════════


def _table(days_dict, profile=None):
    days = m.extract_daily_nutrition(days_dict)
    return m.build_summary_table(days, profile if profile is not None else dict(PROFILE))


def test_no_logged_days_renders_no_snapshot_table_at_all():
    assert m.build_summary_table([], dict(PROFILE)) == ""


def test_the_snapshot_has_one_row_per_day_plus_an_average_row():
    html = _table({f"2026-06-{d:02d}": _mf_day(cal=1800, protein=190) for d in range(6, 13)})
    labels = [r[0] for r in _rows(html) if r]
    assert labels.count("AVG") == 1
    assert sum(1 for label in labels if re.match(r"^[A-Z][a-z]{2} \d{2}/\d{2}$", label)) == 7


def test_each_day_is_labelled_with_its_weekday_and_date():
    html = _table({"2026-06-06": _mf_day(cal=1800), "2026-06-12": _mf_day(cal=1800)})
    labels = [r[0] for r in _rows(html) if r]
    assert "Sat 06/06" in labels  # 2026-06-06 is a Saturday
    assert "Fri 06/12" in labels


def test_a_day_whose_date_cannot_be_parsed_still_appears_labelled_by_its_key():
    html = m.build_summary_table([{"date": "week-24", "total_calories": 1800}], dict(PROFILE))
    assert _day_row(html, "week-24") is not None


def test_the_snapshot_shows_each_days_actual_numbers():
    html = _table({"2026-06-06": _mf_day(cal=1743, protein=187, carbs=142, fat=61, fiber=33, micro=71)})
    row = _day_row(html, "Sat 06/06")
    assert row[1:] == ["1743", "187g", "142g", "61g", "33g", "71%"]


def test_the_average_row_is_the_mean_of_the_shown_days():
    html = _table(
        {
            "2026-06-06": _mf_day(cal=1700, protein=180, carbs=140, fat=60, fiber=30, micro=70),
            "2026-06-07": _mf_day(cal=1900, protein=200, carbs=160, fat=70, fiber=34, micro=80),
        }
    )
    assert _avg_row(html)[1:] == ["1800", "190g", "150g", "65g", "32g", "75%"]


def test_the_snapshot_states_the_targets_it_is_grading_against():
    html = _table({"2026-06-06": _mf_day(cal=1800)}, {"calorie_target": 2000, "protein_target_g": 175})
    footer = [r for r in _rows(html) if r and "Targets" in r[0]][0][0]
    assert "2000 kcal" in footer
    assert "175g protein" in footer


def test_a_profile_with_no_targets_falls_back_to_the_documented_defaults():
    html = _table({"2026-06-06": _mf_day(cal=1800)}, {})
    footer = [r for r in _rows(html) if r and "Targets" in r[0]][0][0]
    assert "1800 kcal" in footer and "190g protein" in footer


def test_calories_over_target_are_flagged_differently_from_calories_on_target():
    on_target = _table({"2026-06-06": _mf_day(cal=1750, protein=190)})
    way_over = _table({"2026-06-06": _mf_day(cal=3000, protein=190)})
    assert _cell_colors(on_target, 1)[1] != _cell_colors(way_over, 1)[1]


def test_protein_well_below_target_is_flagged_differently_from_protein_at_target():
    at_target = _table({"2026-06-06": _mf_day(cal=1800, protein=190)})
    far_below = _table({"2026-06-06": _mf_day(cal=1800, protein=90)})
    assert _cell_colors(at_target, 1)[2] != _cell_colors(far_below, 1)[2]


def test_two_days_with_the_same_standing_get_the_same_flag():
    a = _table({"2026-06-06": _mf_day(cal=1750, protein=190, fiber=35)})
    b = _table({"2026-06-07": _mf_day(cal=1760, protein=192, fiber=36)})
    assert _cell_colors(a, 1)[1:4] == _cell_colors(b, 1)[1:4]


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (tranche-2 discovery, ADR-104): build_summary_table coerces every missing total with `or 0`, so a "
        "day Matthew logged NO food on renders as a real row reading '0 kcal / 0g protein / 0% micro' in red — a "
        "fabricated measurement. Absence must be visibly absent (em-dash / omitted row), not a zero."
    ),
)
def test_an_unlogged_day_does_not_render_as_zero_calories():
    html = _table({"2026-06-06": _mf_day(cal=1800, protein=190), "2026-06-07": {"food_log": []}})
    unlogged = _day_row(html, "Sun 06/07")
    assert unlogged is None or unlogged[1] != "0"


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (tranche-2 discovery): the snapshot's AVG row divides by len(days) after coercing missing totals to "
        "0, while compute_weekly_summary (which feeds the SUBJECT LINE) averages only the days that have data. One "
        "unlogged day makes the email's subject and its own table disagree about the week's average."
    ),
)
def test_the_average_row_agrees_with_the_average_in_the_subject_line():
    days = m.extract_daily_nutrition({"2026-06-06": _mf_day(cal=1800, protein=190), "2026-06-07": {"food_log": []}})
    html = m.build_summary_table(days, dict(PROFILE))
    summary = m.compute_weekly_summary(days)
    assert _avg_row(html)[1] == str(int(summary["avg_calories"]))


# ══════════════════════════════════════════════════════════════════════════════
# build_email_html
# ══════════════════════════════════════════════════════════════════════════════


def test_the_email_names_the_week_it_covers():
    html = m.build_email_html("", "", dict(DATES), None)
    assert "Jun 6 - Jun 12, 2026" in html


def test_an_unparseable_week_range_still_shows_the_raw_dates():
    html = m.build_email_html("", "", {"this_start": "week-23", "this_end": "week-24"}, None)
    assert "week-23 - week-24" in html


def test_the_header_reports_the_latest_weight_and_its_direction():
    html = m.build_email_html("", "", dict(DATES), {"latest_weight_lbs": 309.4, "change_30d_lbs": -5.6})
    assert "309.4 lbs" in html
    assert "down 5.6" in html
    assert "-5.6" not in html  # the sign is spelled out, not doubled up


def test_a_weight_gain_is_reported_as_up():
    html = m.build_email_html("", "", dict(DATES), {"latest_weight_lbs": 311.0, "change_30d_lbs": 1.4})
    assert "up 1.4" in html


def test_an_unchanged_weight_is_reported_as_flat():
    html = m.build_email_html("", "", dict(DATES), {"latest_weight_lbs": 311.0, "change_30d_lbs": 0.0})
    assert "flat 0.0" in html


def test_no_weigh_ins_means_no_weight_line_rather_than_a_zero():
    html = m.build_email_html("", "", dict(DATES), None)
    assert "Weight:" not in html


def test_the_panel_commentary_is_delivered_verbatim():
    ai = '<div style="border-left:3px solid #10b981;">Dr. Webb: protein held at 190g.</div>'
    html = m.build_email_html("", ai, dict(DATES), None)
    assert ai in html


def test_the_snapshot_table_is_delivered_inside_the_email():
    table_html = "<table><tr><td>Sat 06/06</td></tr></table>"
    html = m.build_email_html(table_html, "", dict(DATES), None)
    assert table_html in html


def test_every_nutrition_email_carries_the_not_medical_advice_disclaimer():
    html = m.build_email_html("", "", dict(DATES), None)
    assert "not medical advice" in html


# ══════════════════════════════════════════════════════════════════════════════
# build_user_message — the prompt must carry the data it claims to summarise
# ══════════════════════════════════════════════════════════════════════════════


def _payload(**over):
    return json.loads(m.build_user_message(_gathered(**over)))


def test_the_prompt_payload_is_valid_json():
    raw = m.build_user_message(_gathered())
    assert isinstance(json.loads(raw), dict)


def test_the_prompt_carries_this_weeks_summary_and_every_logged_day():
    p = _payload()
    assert p["this_week"]["summary"]["days_logged"] == 2
    assert p["this_week"]["summary"]["avg_calories"] == 1800.0  # (1700+1900)/2
    assert [d["date"] for d in p["this_week"]["daily_detail"]] == ["2026-06-06", "2026-06-07"]


def test_the_prompt_carries_the_prior_week_for_trend_comparison():
    p = _payload()
    assert p["prior_week_summary"]["avg_calories"] == 2100.0
    assert p["prior_week_summary"]["days_logged"] == 1


def test_the_prompt_carries_the_weight_trend_it_asks_the_panel_to_discuss():
    p = _payload()
    assert p["weight"]["latest_weight_lbs"] == 309.4
    assert p["weight"]["change_30d_lbs"] == -5.6


def test_the_prompt_carries_the_weeks_training_load():
    p = _payload(strava={"2026-06-06": {"activities": [{"sport_type": "Run", "elapsed_time_seconds": 1800}]}})
    assert p["training"][0]["type"] == "Run"
    assert p["training"][0]["duration_min"] == 30.0


def test_the_prompt_carries_cgm_days_when_the_sensor_was_worn():
    p = _payload(cgm={"2026-06-06": {"blood_glucose_avg": 103.0}})
    assert p["cgm"][0]["mean_mg_dl"] == 103.0


def test_a_week_without_cgm_says_so_rather_than_omitting_the_key():
    p = _payload()
    assert "cgm" in p and p["cgm"] is None


def test_the_prompt_carries_the_nutrient_relevant_genome_variants():
    p = _payload(genome_snps=[{"gene": "MTHFR", "risk_level": "elevated", "category": "metabolism"}])
    assert p["genome_nutrient_snps"][0]["gene"] == "MTHFR"


def test_a_week_without_a_dexa_scan_reports_dexa_as_absent(frozen_clock):
    assert _payload()["dexa"] is None


def test_the_prompt_carries_the_profile_targets_the_panel_grades_against():
    p = _payload(profile={"calorie_target": 2000, "protein_target_g": 175, "goal_weight_lbs": 250})
    assert p["profile_targets"] == {"calorie_target": 2000, "protein_target_g": 175, "goal_weight_lbs": 250}


def test_missing_profile_targets_fall_back_to_the_documented_defaults():
    p = _payload(profile={})
    assert p["profile_targets"] == {"calorie_target": 1800, "protein_target_g": 190, "goal_weight_lbs": 185}


def test_last_weeks_review_is_included_when_one_exists():
    p = _payload(prev_review={"date": "2026-06-05", "avg_calories": 1850, "avg_protein_g": 175, "avg_fiber_g": 25})
    assert p["prev_week_review"]["date"] == "2026-06-05"
    assert p["prev_week_review"]["avg_protein_g"] == 175


def test_no_previous_review_means_no_trend_block_is_invented():
    assert "prev_week_review" not in _payload()


# ══════════════════════════════════════════════════════════════════════════════
# _build_nutrition_prompt_from_config
# ══════════════════════════════════════════════════════════════════════════════


BOARD = {
    "members": {
        "webb": {
            "name": "Dr. Marcus Webb",
            "active": True,
            "color": "#10b981",
            "voice": {"tone": "Direct, evidence-based", "catchphrase": "Build from what's working."},
            "features": {
                "nutrition_review": {
                    "section_header": "### Dr. Marcus Webb - Macros",
                    "prompt_focus": "Weekly calorie avg vs target ({calorie_target} kcal) and protein vs {protein_target_g}g.",
                }
            },
        },
        "patel": {
            "name": "Dr. Amara Patel",
            "active": True,
            "color": "#8b5cf6",
            "voice": {"tone": "Scientific but accessible"},
            "features": {"nutrition_review": {"section_header": "### Dr. Amara Patel - Micros", "prompt_focus": "Micronutrients."}},
        },
    }
}


def _with_board(monkeypatch, config):
    monkeypatch.setattr(m, "_HAS_BOARD_LOADER", True)
    monkeypatch.setattr(m.board_loader, "_board_cache", {"data": None, "ts": 0})
    monkeypatch.setattr(m, "s3_client", FakeS3(config))


def test_the_panel_prompt_names_every_configured_expert(monkeypatch):
    _with_board(monkeypatch, BOARD)
    prompt = m._build_nutrition_prompt_from_config(1800, 190)
    assert "Dr. Marcus Webb" in prompt
    assert "Dr. Amara Patel" in prompt


def test_the_panel_prompt_renders_the_targets_into_the_expert_briefs(monkeypatch):
    _with_board(monkeypatch, BOARD)
    prompt = m._build_nutrition_prompt_from_config(1650, 205)
    assert "1650 kcal" in prompt
    assert "205g" in prompt


def test_the_panel_prompt_leaves_no_unrendered_placeholders(monkeypatch):
    _with_board(monkeypatch, BOARD)
    prompt = m._build_nutrition_prompt_from_config(1800, 190)
    assert "{calorie_target}" not in prompt
    assert "{protein_target_g}" not in prompt


def test_each_experts_voice_and_principle_reach_the_prompt(monkeypatch):
    _with_board(monkeypatch, BOARD)
    prompt = m._build_nutrition_prompt_from_config(1800, 190)
    assert "Direct, evidence-based" in prompt
    assert "Build from what's working." in prompt


def test_the_panel_prompt_binds_each_experts_card_colour(monkeypatch):
    _with_board(monkeypatch, BOARD)
    prompt = m._build_nutrition_prompt_from_config(1800, 190)
    assert "Webb card: left border #10b981" in prompt
    assert "Patel card: left border #8b5cf6" in prompt


def test_an_inactive_board_member_is_left_off_the_panel(monkeypatch):
    config = json.loads(json.dumps(BOARD))
    config["members"]["patel"]["active"] = False
    _with_board(monkeypatch, config)
    prompt = m._build_nutrition_prompt_from_config(1800, 190)
    assert "Dr. Marcus Webb" in prompt
    assert "Dr. Amara Patel" not in prompt


def test_an_unavailable_board_config_falls_back_rather_than_guessing(monkeypatch):
    monkeypatch.setattr(m, "_HAS_BOARD_LOADER", True)
    monkeypatch.setattr(m.board_loader, "_board_cache", {"data": None, "ts": 0})
    monkeypatch.setattr(m, "s3_client", FakeS3(None, error=RuntimeError("no such key")))
    assert m._build_nutrition_prompt_from_config(1800, 190) is None


def test_a_board_with_nobody_assigned_to_this_email_falls_back(monkeypatch):
    config = {"members": {"webb": {"name": "Dr. Marcus Webb", "active": True, "features": {"weekly_digest": {}}}}}
    _with_board(monkeypatch, config)
    assert m._build_nutrition_prompt_from_config(1800, 190) is None


def test_no_board_loader_in_the_bundle_falls_back(monkeypatch):
    monkeypatch.setattr(m, "_HAS_BOARD_LOADER", False)
    assert m._build_nutrition_prompt_from_config(1800, 190) is None


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (tranche-2 discovery): _build_nutrition_prompt_from_config indexes member['name'] directly and is "
        "called UNGUARDED from lambda_handler. A board member saved without a name (or any other config shape "
        "error) raises KeyError out of the handler, so the whole nutrition email fails to send — the module's "
        "documented contract is to fall back to the hardcoded prompt when the config is unusable."
    ),
)
def test_a_malformed_board_member_degrades_to_the_fallback_prompt(monkeypatch):
    config = {"members": {"webb": {"active": True, "features": {"nutrition_review": {"prompt_focus": "Macros."}}}}}
    _with_board(monkeypatch, config)
    result = m._build_nutrition_prompt_from_config(1800, 190)
    assert result is None or isinstance(result, str)


def test_the_hardcoded_fallback_prompt_renders_the_live_targets():
    rendered = m._FALLBACK_SYSTEM_PROMPT.format(calorie_target=1650, protein_target_g=205)
    assert "1650 kcal" in rendered
    assert "205g" in rendered
    assert "{" not in rendered.replace("{calorie_target}", "").replace("{protein_target_g}", "")


# ══════════════════════════════════════════════════════════════════════════════
# call_anthropic
# ══════════════════════════════════════════════════════════════════════════════


def test_call_anthropic_hands_the_panel_prompt_and_data_to_the_shared_client(monkeypatch):
    from common import retry_utils

    seen = {}

    def _fake(**kwargs):
        seen.update(kwargs)
        return "  panel text  "

    monkeypatch.setattr(retry_utils, "call_anthropic_api", _fake)
    out = m.call_anthropic("SYSTEM PROMPT", "USER DATA")
    assert out == "  panel text  "
    assert seen["system"] == "SYSTEM PROMPT"
    assert seen["prompt"] == "USER DATA"


def test_call_anthropic_asks_for_enough_tokens_for_a_full_review(monkeypatch):
    """The prompt asks for ~1500-2000 words; a small max_tokens silently truncates."""
    from common import retry_utils

    seen = {}
    monkeypatch.setattr(retry_utils, "call_anthropic_api", lambda **kw: seen.update(kw) or "x")
    m.call_anthropic("s", "u")
    assert seen["max_tokens"] >= 2048
    assert seen["timeout"] >= 60


def test_call_anthropic_propagates_failure_so_the_caller_can_degrade(monkeypatch):
    from common import retry_utils

    def _boom(**kwargs):
        raise RuntimeError("bedrock throttled")

    monkeypatch.setattr(retry_utils, "call_anthropic_api", _boom)
    with pytest.raises(RuntimeError):
        m.call_anthropic("s", "u")


# ══════════════════════════════════════════════════════════════════════════════
# query_all / gather_nutrition_data
# ══════════════════════════════════════════════════════════════════════════════


def test_query_all_returns_every_page_not_just_the_first(monkeypatch):
    pk = f"USER#{m.USER_ID}#SOURCE#genome"
    table = FakeTable(pages_by_pk={pk: [[{"gene": "MTHFR"}], [{"gene": "FADS2"}], [{"gene": "VKORC1"}]]})
    monkeypatch.setattr(m, "table", table)
    assert [i["gene"] for i in m.query_all("genome")] == ["MTHFR", "FADS2", "VKORC1"]


def test_query_all_converts_dynamodb_decimals_to_numbers(monkeypatch):
    pk = f"USER#{m.USER_ID}#SOURCE#dexa"
    table = FakeTable(items_by_pk={pk: [{"body_composition": {"body_fat_pct": Decimal("38.4")}}]})
    monkeypatch.setattr(m, "table", table)
    got = m.query_all("dexa")[0]["body_composition"]["body_fat_pct"]
    assert got == 38.4 and isinstance(got, float)


def test_query_all_applies_the_experiment_phase_filter(monkeypatch):
    """ADR-058: pilot-phase rows must not leak into the current cycle's review."""
    table = FakeTable()
    monkeypatch.setattr(m, "table", table)
    m.query_all("genome")
    expected = with_phase_filter({"KeyConditionExpression": "pk = :pk", "ExpressionAttributeValues": {":pk": "x"}})
    issued = table.queries[0]
    assert issued.get("FilterExpression") == expected.get("FilterExpression")
    assert issued.get("ExpressionAttributeNames") == expected.get("ExpressionAttributeNames")


def test_gather_reads_the_seven_days_ending_yesterday(monkeypatch, frozen_clock):
    table = FakeTable()
    monkeypatch.setattr(m, "table", table)
    monkeypatch.setattr(m, "fetch_profile", lambda: dict(PROFILE))
    data = m.gather_nutrition_data()
    assert data["dates"] == DATES
    mf = [q for q in table.queries if q["ExpressionAttributeValues"][":pk"].endswith("macrofactor")]
    assert mf[0]["ExpressionAttributeValues"][":s"] == f"DATE#{W1_START}"
    assert mf[0]["ExpressionAttributeValues"][":e"] == f"DATE#{W1_END}"
    assert mf[1]["ExpressionAttributeValues"][":s"] == f"DATE#{W2_START}"
    assert mf[1]["ExpressionAttributeValues"][":e"] == f"DATE#{W2_END}"


def test_gather_reads_thirty_days_of_weight(monkeypatch, frozen_clock):
    table = FakeTable()
    monkeypatch.setattr(m, "table", table)
    monkeypatch.setattr(m, "fetch_profile", lambda: dict(PROFILE))
    m.gather_nutrition_data()
    wq = [q for q in table.queries if q["ExpressionAttributeValues"][":pk"].endswith("withings")][0]
    assert wq["ExpressionAttributeValues"][":s"] == f"DATE#{WEIGHT_START}"


def test_gather_gives_up_when_there_is_no_profile(monkeypatch, frozen_clock):
    table = FakeTable()
    monkeypatch.setattr(m, "table", table)
    monkeypatch.setattr(m, "fetch_profile", lambda: None)
    assert m.gather_nutrition_data() is None
    assert table.queries == []


def test_gather_keeps_only_the_nutrition_relevant_genome_variants(monkeypatch, frozen_clock):
    pk = f"USER#{m.USER_ID}#SOURCE#genome"
    table = FakeTable(
        items_by_pk={
            pk: [
                {"gene": "MTHFR", "category": "nutrient_metabolism"},
                {"gene": "APOE", "category": "neuro"},
                {"gene": "LPA", "category": "lipids"},
                {"gene": "SLC30A8", "category": "metabolism"},
            ]
        }
    )
    monkeypatch.setattr(m, "table", table)
    monkeypatch.setattr(m, "fetch_profile", lambda: dict(PROFILE))
    genes = [g["gene"] for g in m.gather_nutrition_data()["genome_snps"]]
    assert genes == ["MTHFR", "LPA", "SLC30A8"]


def test_gather_picks_the_most_recent_lab_draw(monkeypatch, frozen_clock):
    pk = f"USER#{m.USER_ID}#SOURCE#labs"
    table = FakeTable(
        items_by_pk={
            pk: [
                {"draw_date": "2026-01-04", "panel": "old"},
                {"draw_date": "2026-05-20", "panel": "newest"},
                {"draw_date": "2026-03-11", "panel": "middle"},
            ]
        }
    )
    monkeypatch.setattr(m, "table", table)
    monkeypatch.setattr(m, "fetch_profile", lambda: dict(PROFILE))
    assert m.gather_nutrition_data()["latest_lab"]["panel"] == "newest"


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (tranche-2 discovery): gather_nutrition_data sorts labs by draw_date before taking [0] but takes "
        "dexa_items[0] unsorted — DynamoDB serves the partition in ascending sk order, so `latest_dexa` is the "
        "OLDEST scan on file. The panel benchmarks body composition (and its 'months ago' caveat) against a stale "
        "scan whenever more than one DEXA exists."
    ),
)
def test_gather_picks_the_most_recent_dexa_scan(monkeypatch, frozen_clock):
    pk = f"USER#{m.USER_ID}#SOURCE#dexa"
    table = FakeTable(
        items_by_pk={
            pk: [
                {"sk": "DATE#2025-02-10", "scan_date": "2025-02-10", "body_composition": {"body_fat_pct": 41.0}},
                {"sk": "DATE#2026-05-01", "scan_date": "2026-05-01", "body_composition": {"body_fat_pct": 36.0}},
            ]
        }
    )
    monkeypatch.setattr(m, "table", table)
    monkeypatch.setattr(m, "fetch_profile", lambda: dict(PROFILE))
    assert m.gather_nutrition_data()["latest_dexa"]["scan_date"] == "2026-05-01"


def test_gather_carries_last_weeks_review_for_trending(monkeypatch, frozen_clock):
    pk = f"USER#{m.USER_ID}#SOURCE#nutrition_review"
    table = FakeTable(
        items_by_pk={
            pk: [
                {"sk": "DATE#2026-05-29", "date": "2026-05-29", "avg_calories": Decimal("1900")},
                {"sk": "DATE#2026-06-05", "date": "2026-06-05", "avg_calories": Decimal("1850")},
            ]
        }
    )
    monkeypatch.setattr(m, "table", table)
    monkeypatch.setattr(m, "fetch_profile", lambda: dict(PROFILE))
    prev = m.gather_nutrition_data()["prev_review"]
    assert prev["date"] == "2026-06-05"
    assert prev["avg_calories"] == 1850.0


def test_a_failure_reading_last_weeks_review_does_not_lose_this_weeks_data(monkeypatch, frozen_clock):
    table = FakeTable(items_by_pk={f"USER#{m.USER_ID}#SOURCE#macrofactor": [{"sk": f"DATE#{W1_START}", "total_calories_kcal": 1800}]})
    table.query_errors.add(f"USER#{m.USER_ID}#SOURCE#nutrition_review")
    monkeypatch.setattr(m, "table", table)
    monkeypatch.setattr(m, "fetch_profile", lambda: dict(PROFILE))
    data = m.gather_nutrition_data()
    assert data["prev_review"] is None
    assert W1_START in data["macrofactor_this"]


# ══════════════════════════════════════════════════════════════════════════════
# store_weekly_summary / record_email_send
# ══════════════════════════════════════════════════════════════════════════════


def test_the_weekly_summary_is_stored_under_the_weeks_end_date(monkeypatch, frozen_clock):
    table = FakeTable()
    monkeypatch.setattr(m, "table", table)
    m.store_weekly_summary(dict(DATES), {"days_logged": 7, "avg_calories": 1812.5})
    item = table.puts[0]
    assert item["pk"] == f"USER#{m.USER_ID}#SOURCE#nutrition_review"
    assert item["sk"] == f"DATE#{W1_END}"
    assert item["date"] == W1_END
    assert item["source"] == "nutrition_review"


def test_stored_numbers_are_decimals_because_dynamodb_rejects_floats(monkeypatch, frozen_clock):
    table = FakeTable()
    monkeypatch.setattr(m, "table", table)
    m.store_weekly_summary(dict(DATES), {"days_logged": 7, "avg_calories": 1812.5, "avg_protein_g": 190.0})
    item = table.puts[0]
    assert item["avg_calories"] == Decimal("1812.5")
    assert not any(isinstance(v, float) for v in item.values())


def test_a_metric_no_day_logged_is_not_stored_as_zero(monkeypatch, frozen_clock):
    """ADR-104: the stored week must not claim 0 mg choline when none was logged."""
    table = FakeTable()
    monkeypatch.setattr(m, "table", table)
    m.store_weekly_summary(dict(DATES), {"avg_calories": 1800.0, "avg_choline_mg": None})
    assert "avg_choline_mg" not in table.puts[0]


def test_a_storage_failure_never_takes_down_the_email(monkeypatch, frozen_clock):
    table = FakeTable()
    table.put_error = RuntimeError("throughput exceeded")
    monkeypatch.setattr(m, "table", table)
    m.store_weekly_summary(dict(DATES), {"avg_calories": 1800.0})  # must not raise


def test_a_successful_send_is_recorded_for_the_status_page(monkeypatch, frozen_clock):
    table = FakeTable()
    m.record_email_send(table, "nutrition_review")
    item = table.puts[0]
    assert item["sk"] == f"DATE#{FROZEN_NOW.date().isoformat()}"
    assert item["status"] == "success"
    assert "nutrition_review" in item["pk"]


def test_the_send_record_expires_after_about_ninety_days(monkeypatch, frozen_clock):
    table = FakeTable()
    m.record_email_send(table, "nutrition_review")
    ttl_days = (table.puts[0]["ttl"] - time.time()) / 86400
    assert 89 < ttl_days <= 90


def test_a_failed_status_write_never_takes_down_the_email(frozen_clock):
    table = FakeTable()
    table.put_error = RuntimeError("no")
    m.record_email_send(table, "nutrition_review")  # must not raise


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (tranche-2 discovery, minor): record_email_send hard-codes 'USER#matthew' in the partition key "
        "instead of using the module's USER_ID (which every other write in this lambda derives from the env var). "
        "Under any non-default USER_ID the send record lands in the wrong user's partition."
    ),
)
def test_the_send_record_is_keyed_to_the_configured_user(monkeypatch, frozen_clock):
    monkeypatch.setattr(m, "USER_ID", "someone_else")
    table = FakeTable()
    m.record_email_send(table, "nutrition_review")
    assert table.puts[0]["pk"].startswith("USER#someone_else#")


# ══════════════════════════════════════════════════════════════════════════════
# lambda_handler
# ══════════════════════════════════════════════════════════════════════════════


def test_no_gathered_data_reports_failure_and_sends_nothing(handler_env):
    handler_env["monkeypatch"].setattr(m, "gather_nutrition_data", lambda: None)
    resp = m.lambda_handler({}, None)
    assert resp["statusCode"] == 500
    assert handler_env["ses"].sent == []


def test_a_week_with_no_food_logged_at_all_sends_nothing(handler_env):
    handler_env["state"]["data"] = _gathered(macrofactor_this={})
    resp = m.lambda_handler({}, None)
    assert resp["statusCode"] == 500
    assert "No nutrition data" in resp["body"]
    assert handler_env["ses"].sent == []


def test_the_happy_path_sends_exactly_one_email_to_the_configured_recipient(handler_env):
    resp = m.lambda_handler({}, None)
    assert resp["statusCode"] == 200
    assert len(handler_env["ses"].sent) == 1
    sent = handler_env["ses"].sent[0]
    assert sent["FromEmailAddress"] == m.SENDER
    assert sent["Destination"]["ToAddresses"] == [m.RECIPIENT]


def test_the_subject_line_carries_the_week_and_its_headline_averages(handler_env):
    m.lambda_handler({}, None)
    subject = _sent_subject(handler_env)
    assert W1_END in subject
    assert "1800 kcal" in subject  # (1700+1900)/2
    assert "190g protein" in subject  # (180+200)/2


def test_the_email_body_carries_the_days_the_reader_logged(handler_env):
    m.lambda_handler({}, None)
    html = _sent_html(handler_env)
    assert _day_row(html, "Sat 06/06")[1] == "1700"
    assert _day_row(html, "Sun 06/07")[1] == "1900"


def test_the_email_body_carries_the_panel_commentary(handler_env):
    handler_env["state"]["ai"] = "<p>Protein held at 190 g across the week.</p>"
    m.lambda_handler({}, None)
    assert "Protein held at 190 g across the week." in _sent_html(handler_env)


def test_the_panel_prompt_receives_the_weeks_real_numbers(handler_env):
    m.lambda_handler({}, None)
    system, user_message = handler_env["calls"]["anthropic"][0]
    assert "1700" in user_message and "1900" in user_message
    assert '"days_logged": 2' in user_message
    assert "309.4" in user_message  # the latest weigh-in


def test_the_panel_prompt_states_the_targets_being_graded(handler_env):
    m.lambda_handler({}, None)
    system, _ = handler_env["calls"]["anthropic"][0]
    assert "1800 kcal" in system
    assert "190g" in system


def test_the_panel_is_told_which_week_of_the_journey_this_is(handler_env, frozen_clock):
    """journey_start 2026-06-01, today 2026-06-13 -> day 13 -> week 2."""
    m.lambda_handler({}, None)
    _, user_message = handler_env["calls"]["anthropic"][0]
    assert "JOURNEY CONTEXT: Week 2 (13 days in)" in user_message
    assert "Foundation Stage" in user_message


def test_a_later_journey_week_gets_the_momentum_stage_brief(handler_env, frozen_clock):
    data = _gathered()
    data["profile"]["journey_start_date"] = "2026-04-01"  # 74 days in -> week 11
    handler_env["state"]["data"] = data
    m.lambda_handler({}, None)
    _, user_message = handler_env["calls"]["anthropic"][0]
    assert "Week 11 (74 days in)" in user_message
    assert "Momentum Stage" in user_message


def test_prior_nutrition_insights_are_prepended_to_the_prompt(handler_env):
    handler_env["writer"].context = "PREVIOUS NUTRITION INSIGHTS: fiber trending up."
    m.lambda_handler({}, None)
    _, user_message = handler_env["calls"]["anthropic"][0]
    assert user_message.startswith("PREVIOUS NUTRITION INSIGHTS: fiber trending up.")


def test_an_ai_failure_still_ships_the_email_and_says_the_analysis_is_missing(handler_env):
    handler_env["state"]["ai_error"] = RuntimeError("bedrock throttled")
    resp = m.lambda_handler({}, None)
    assert resp["statusCode"] == 200
    html = _sent_html(handler_env)
    assert "AI analysis unavailable" in html
    assert _day_row(html, "Sat 06/06")[1] == "1700"  # the data table still stands on its own


def test_an_ai_failure_is_not_written_into_the_insight_ledger(handler_env):
    handler_env["state"]["ai_error"] = RuntimeError("bedrock throttled")
    m.lambda_handler({}, None)
    assert handler_env["writer"].written == []


def test_blocked_ai_output_is_replaced_by_the_validators_safe_fallback(handler_env):
    """Exercises the REAL validator, so the handler's attribute reads on the
    result object are proved against the live AIValidationResult shape."""
    handler_env["state"]["ai"] = "ok"  # too short -> BLOCK
    m.lambda_handler({}, None)
    expected = aiv._fallback_for_type(aiv.AIOutputType.NUTRITION_COACH)
    assert expected in _sent_html(handler_env)
    assert "ok" not in _sent_html(handler_env).replace("Life Platform", "")


def test_ai_output_with_warnings_is_still_delivered_to_the_reader(handler_env):
    result = aiv.AIValidationResult(
        original_text="<p>Panel commentary with a caveat.</p>",
        output_type=aiv.AIOutputType.NUTRITION_COACH,
        warnings=["generic phrasing"],
    )
    handler_env["monkeypatch"].setattr(m, "validate_ai_output", lambda *a, **k: result)
    handler_env["state"]["ai"] = "<p>Panel commentary with a caveat.</p>"
    m.lambda_handler({}, None)
    assert "Panel commentary with a caveat." in _sent_html(handler_env)


def test_the_weekly_summary_is_persisted_after_a_successful_send(handler_env):
    m.lambda_handler({}, None)
    stored = [p for p in handler_env["table"].puts if p["pk"].endswith("SOURCE#nutrition_review")]
    assert stored and stored[0]["avg_calories"] == Decimal("1800.0")


def test_the_send_is_logged_for_the_status_page(handler_env):
    m.lambda_handler({}, None)
    logged = [p for p in handler_env["table"].puts if "email_log" in p["pk"]]
    assert logged and logged[0]["status"] == "success"


def test_a_broken_insight_ledger_never_blocks_the_email(handler_env):
    class Exploding(FakeInsightWriter):
        def build_insights_context(self, **kwargs):
            raise RuntimeError("ddb down")

        def write_insight(self, **kwargs):
            raise RuntimeError("ddb down")

    handler_env["monkeypatch"].setattr(m, "insight_writer", Exploding())
    assert m.lambda_handler({}, None)["statusCode"] == 200
    assert len(handler_env["ses"].sent) == 1


def test_a_config_driven_panel_prompt_is_used_when_the_board_config_loads(handler_env):
    handler_env["monkeypatch"].setattr(m, "_build_nutrition_prompt_from_config", lambda cal, pro: f"BOARD PROMPT {cal}/{pro}")
    m.lambda_handler({}, None)
    system, _ = handler_env["calls"]["anthropic"][0]
    assert system == "BOARD PROMPT 1800/190"


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (tranche-2 discovery): the AI-3 validation gate is structurally DARK on this lambda. It runs only "
        "`if ai_content and not ai_content.startswith('<div')` — a sentinel meant to detect the hardcoded failure "
        "stub. But the system prompt orders the panel to 'Write clean HTML ... Each expert section in a div with "
        "border-left', so real output starts with '<div' and skips validation entirely. Nothing the panel actually "
        "produces is ever safety-checked."
    ),
)
def test_real_panel_html_output_is_still_safety_validated(handler_env):
    seen = []
    handler_env["monkeypatch"].setattr(
        m,
        "validate_ai_output",
        lambda text, *a, **k: seen.append(text) or aiv.AIValidationResult(original_text=text, output_type=aiv.AIOutputType.NUTRITION_COACH),
    )
    handler_env["state"]["ai"] = '<div style="border-left:3px solid #10b981;padding:12px;">Dr. Webb: eat 600 calories.</div>'
    m.lambda_handler({}, None)
    assert len(seen) == 1


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (tranche-2 discovery): the same `startswith('<div')` sentinel gates IC-15 insight persistence, so "
        "every real (HTML) panel review is dropped from the insight ledger. IC-16 then feeds the next week's prompt "
        "'PREVIOUS NUTRITION INSIGHTS' that never accumulate — the progressive-context loop is permanently empty."
    ),
)
def test_a_delivered_panel_review_is_recorded_in_the_insight_ledger(handler_env):
    handler_env["state"]["ai"] = '<div style="border-left:3px solid #10b981;">Dr. Webb: protein held.</div>'
    m.lambda_handler({}, None)
    assert len(handler_env["writer"].written) == 1


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (tranche-2 discovery, #2111 class): nutrition_review_lambda has NO dry_run gate — several sibling "
        "email lambdas (between_chronicle, chronicle_email_sender, chronicle_approve, coach_panel_podcast) accept "
        "{'dry_run': true}. Any manual/regeneration invoke of this function mails Matthew a real review."
    ),
)
def test_a_dry_run_invocation_builds_the_review_without_mailing_it(handler_env):
    resp = m.lambda_handler({"dry_run": True}, None)
    assert resp["statusCode"] == 200
    assert handler_env["ses"].sent == []


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (tranche-2 discovery): the subject line does int(avg_cal)/int(avg_pro) on compute_weekly_summary "
        "values that are None whenever no day in the week carried that total (records present, totals absent — the "
        "partial-record case). int(None) raises TypeError BEFORE ses.send_email, so the whole weekly review is lost "
        "rather than degrading to a subject without the number."
    ),
)
def test_a_week_of_records_without_totals_still_sends_a_review(handler_env):
    handler_env["state"]["data"] = _gathered(
        macrofactor_this={
            "2026-06-06": {"food_log": [], "micronutrient_avg_pct": 40},
            "2026-06-07": {"food_log": []},
        }
    )
    resp = m.lambda_handler({}, None)
    assert resp["statusCode"] == 200
    assert len(handler_env["ses"].sent) == 1
