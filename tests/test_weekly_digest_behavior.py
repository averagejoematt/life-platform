#!/usr/bin/env python3
"""tests/test_weekly_digest_behavior.py — behavioral contracts of
`lambdas/emails/weekly_digest_lambda.py` (the Sunday Weekly Report).

Part of #1658 tranche 3. The caller is Matthew reading one email a week, so the
contracts under test are the ones that reach him:

  * the extractors — every field name this module READS is checked against the
    field name the corresponding writer actually STORES (the tranche-2 dark-
    feature class), and every aggregate is hand-derived in the test body;
  * honest numbers (ADR-104) — an unlogged day, an unworn strap or an
    un-ingested source must never surface as a factual 0, and an average must
    never be silently replaced by a different measurement because the real one
    happened to be zero;
  * window-name honesty (#1917) — a row labelled "7-Day" or "4-week" must be
    computed over that window, and a rate quoted "per week" must divide by the
    weeks that actually elapsed;
  * phase semantics (ADR-058/#2109) — a trailing physiological window
    (the 60-day Banister load) must not truncate to the age of the current
    experiment cycle;
  * the reader-visible HTML — the numbers and labels a reader sees, never the
    exact markup;
  * the handler — which branches send and which do not.

No test in this file can reach a real SES / DynamoDB / S3 / Bedrock call: every
client the module holds is replaced with a hand-rolled bounded fake (never a
MagicMock inside a paginated read). Time is frozen module-wide by an autouse
fixture — no fixture date is ever combined with the real clock.

Tests that document a DEFECT in current behaviour are marked
`@pytest.mark.xfail(strict=False)` with a reason naming the module, function,
line, current behaviour, correct behaviour and who it hurts. Nothing in this
file edits production code.
"""

import os
import re
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LAMBDAS = os.path.join(ROOT, "lambdas")
if LAMBDAS not in sys.path:
    sys.path.insert(0, LAMBDAS)

# The module reads these at import time (os.environ[...] — no defaults).
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("EMAIL_RECIPIENT", "matthew@example.invalid")
os.environ.setdefault("EMAIL_SENDER", "digest@example.invalid")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("AI_VALIDATOR_AUTOLOAD", "off")

_import_err = None
try:
    from common.constants import EXPERIMENT_BASELINE_WEIGHT_LBS, EXPERIMENT_PHASE_CURRENT
    from emails import weekly_digest_lambda as wd  # same module identity as tests/test_weekly_digest_gate_telemetry.py
    from experiment.phase_filter import PHASE_FILTER_EXPRESSION
    from health import character_engine, scoring_engine
except ImportError as _e:  # pragma: no cover — only when the bundle layout changes
    _import_err = _e
    wd = None  # type: ignore

if _import_err is not None:  # pragma: no cover
    pytestmark = pytest.mark.skip(reason=f"weekly_digest_lambda unavailable: {_import_err}")  # type: ignore


# ──────────────────────────────────────────────────────────────────────────────
# Frozen clock
# ──────────────────────────────────────────────────────────────────────────────

# The Lambda fires Sunday 08:30 PT == Sunday 15:30 UTC.
FROZEN_NOW = datetime(2026, 8, 9, 15, 30, 0, tzinfo=timezone.utc)

TODAY = "2026-08-09"  # now().date()
W1_END = "2026-08-08"  # today - 1
W1_START = "2026-08-02"  # today - 7   → 7 inclusive days
W2_END = "2026-08-01"  # today - 8
W2_START = "2026-07-26"  # today - 14
W3_END = "2026-07-25"  # today - 15
W3_START = "2026-07-19"  # today - 21
W4_END = "2026-07-18"  # today - 22
W4_START = "2026-07-12"  # today - 28
W1_DATES = ["2026-08-02", "2026-08-03", "2026-08-04", "2026-08-05", "2026-08-06", "2026-08-07", "2026-08-08"]


class _FrozenDatetime(datetime):
    """`datetime` subclass with a pinned `now()`.

    A subclass (not a Mock) keeps `strptime`, `fromisoformat`, arithmetic and
    `.date()` working — the module uses all four off the same name.
    """

    @classmethod
    def now(cls, tz=None):
        return FROZEN_NOW if tz else FROZEN_NOW.replace(tzinfo=None)

    @classmethod
    def utcnow(cls):
        return FROZEN_NOW.replace(tzinfo=None)


@pytest.fixture(autouse=True)
def frozen_clock(monkeypatch):
    monkeypatch.setattr(wd, "datetime", _FrozenDatetime)
    # digest_utils carries its own `datetime` import and is what dates the
    # Banister decay window — freezing only the handler's copy would leave a
    # fixture date being differenced against the real clock.
    from common import digest_utils

    monkeypatch.setattr(digest_utils, "datetime", _FrozenDatetime)
    return FROZEN_NOW


# ──────────────────────────────────────────────────────────────────────────────
# Test doubles — hand-rolled and bounded (never a MagicMock in a read loop)
# ──────────────────────────────────────────────────────────────────────────────


class FakeTable:
    """DynamoDB Table stand-in keyed the way this module keys the real table.

    Bespoke rather than `tests/fakes.py::FakeDdbTable` because three behaviours
    are load-bearing here and that shared fake serves canned rows regardless of
    kwargs: (a) the `pk = :pk AND sk BETWEEN :s AND :e` window, (b) the ADR-058
    phase FilterExpression evaluated against each row's own `phase` attribute
    (the whole point of the Banister-window test), and (c) `Select="COUNT"` plus
    the subscriber status/source filter that `_count_real_subscribers` issues.
    """

    def __init__(self, items=None):
        self.items = {(i["pk"], i["sk"]): i for i in (items or [])}
        self.puts = []
        self.queries = []
        self.gets = []
        self.query_error = None
        self.get_error = None
        self.pages = None  # optional list of pre-baked responses (pagination)

    # -- writes ---------------------------------------------------------------
    def put_item(self, Item=None, **kwargs):
        self.puts.append(Item)
        self.items[(Item["pk"], Item["sk"])] = Item
        return {}

    # -- reads ----------------------------------------------------------------
    def get_item(self, Key=None, **kwargs):
        self.gets.append(Key)
        if self.get_error is not None:
            raise self.get_error
        item = self.items.get((Key["pk"], Key["sk"]))
        return {"Item": item} if item is not None else {}

    def add(self, item):
        self.items[(item["pk"], item["sk"])] = item
        return item

    def query(self, **kwargs):
        self.queries.append(kwargs)
        if self.query_error is not None:
            raise self.query_error
        if self.pages:
            return self.pages.pop(0)
        vals = kwargs.get("ExpressionAttributeValues") or {}
        rows = [v for (p, _s), v in self.items.items() if p == vals.get(":pk")]
        if ":s" in vals and ":e" in vals:
            rows = [r for r in rows if vals[":s"] <= r["sk"] <= vals[":e"]]
        filt = kwargs.get("FilterExpression") or ""
        if PHASE_FILTER_EXPRESSION in filt:
            rows = [r for r in rows if r.get("phase") in (None, EXPERIMENT_PHASE_CURRENT)]
        names = kwargs.get("ExpressionAttributeNames") or {}
        if "#st" in names:  # the subscribers filter (_count_real_subscribers / _attribution_breakdown)
            rows = [r for r in rows if r.get("status") == "confirmed" and r.get("source") != "canary"]
        rows.sort(key=lambda r: r["sk"])
        limit = kwargs.get("Limit")
        if limit is not None:
            rows = rows[:limit]
        if kwargs.get("Select") == "COUNT":
            return {"Count": len(rows)}
        return {"Items": rows}


class FakeSes:
    """SESv2 stand-in. Nothing in this file can reach a real send path."""

    def __init__(self):
        self.sent = []
        self.error = None

    def send_email(self, **kwargs):
        if self.error is not None:
            raise self.error
        self.sent.append(kwargs)
        return {"MessageId": "fake"}


class FakeS3:
    """`list_objects_v2` stand-in with bounded, explicit pagination.

    Hand-rolled: a MagicMock here would return a truthy NextContinuationToken
    forever and spin `get_mcp_mutations_digest_line`'s inner loop.
    """

    def __init__(self, keys_by_prefix=None, error=None):
        self.keys_by_prefix = keys_by_prefix or {}
        self.error = error
        self.calls = []

    def list_objects_v2(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        keys = list(self.keys_by_prefix.get(kwargs["Prefix"], []))
        token = kwargs.get("ContinuationToken")
        if token is None and len(keys) > 1:
            # First page holds one key, second page the rest — exercises the loop.
            return {"Contents": [{"Key": keys[0]}], "NextContinuationToken": "page2"}
        if token == "page2":
            return {"Contents": [{"Key": k} for k in keys[1:]]}
        return {"Contents": [{"Key": k} for k in keys]}


class FakeBoto3:
    """Stands in for the module-level `boto3` name so `boto3.client("s3")`
    inside `get_mcp_mutations_digest_line` cannot reach AWS."""

    def __init__(self, s3):
        self._s3 = s3

    def client(self, name, **kwargs):
        assert name == "s3", f"unexpected boto3 client in a test: {name}"
        return self._s3


class FakeInsightWriter:
    def __init__(self, context=""):
        self.context = context
        self.written = []

    def build_insights_context(self, **kwargs):
        return self.context

    def write_insights_batch(self, insights):
        self.written.extend(insights)
        return len(insights)


@pytest.fixture
def table(monkeypatch):
    t = FakeTable()
    monkeypatch.setattr(wd, "table", t)
    return t


@pytest.fixture
def delivery_public(monkeypatch):
    """Opt IN to the ungated food-delivery reader.

    `get_food_delivery_{brief_signal,digest_line}` ship PRIVATE-by-default
    (#2209/#2210, this door #2233): with `NUTRITION_DELIVERY_PUBLIC` unset they
    return None and never query the partition. Every test below that asserts on
    delivery *content* — streak text, bonus multipliers, the ordered-today
    override — is exercising the flag-ON path and must say so.

    Tests asserting *absence* need it too, for a subtler reason: with the flag
    off they pass vacuously, and would keep passing against a function stubbed to
    `return None`. Taking the fixture is what makes them test their own claim.

    The gate reads the env var at CALL time (`nutrition_delivery_public()`), not
    at import, so setting the environment is correct here — unlike the sibling
    `site_api_meals._DELIVERY_PUBLIC`, which is import-frozen and must be patched
    as a module attribute.
    """
    monkeypatch.setenv("NUTRITION_DELIVERY_PUBLIC", "true")


@pytest.fixture
def ses(monkeypatch):
    s = FakeSes()
    monkeypatch.setattr(wd, "ses", s)
    return s


# ──────────────────────────────────────────────────────────────────────────────
# Row / record builders
# ──────────────────────────────────────────────────────────────────────────────


def rec(source, date_str, **fields):
    """A DDB item as the writers store it (pk/sk/date + fields)."""
    return {"pk": f"USER#matthew#SOURCE#{source}", "sk": f"DATE#{date_str}", "date": date_str, **fields}


def as_range(source, by_date):
    """{date: record} exactly as `query_range` hands it back (already d2f'd)."""
    return {d: rec(source, d, **f) for d, f in by_date.items()}


def profile_row(**fields):
    base = {
        "pk": "USER#matthew",
        "sk": "PROFILE#v1",
        "max_heart_rate": 186,
        "calorie_target": 1800,
        "protein_target_g": 190,
        "goal_weight_lbs": 185,
        "journey_start_weight_lbs": EXPERIMENT_BASELINE_WEIGHT_LBS,
        "sleep_target_hours_ideal": Decimal("7.5"),
        "mvp_habits": ["Sleep 7h", "Walk 8k", "Protein 190g", "Journal"],
    }
    base.update(fields)
    return base


def sub_row(sk, **fields):
    return {"pk": wd._SUBSCRIBERS_PK, "sk": sk, "status": "confirmed", **fields}


# A realistic Board commentary: six advisor sections then the pattern block.
BOARD_TEXT = (
    "🏋️ DR. SARAH CHEN — SPORTS SCIENTIST\nTraining load is climbing steadily.\n"
    "🥗 DR. MARCUS WEBB — NUTRITIONIST\nProtein adherence held.\n"
    "😴 DR. LISA PARK — SLEEP & CIRCADIAN SPECIALIST\nEfficiency slipped.\n"
    "🩺 DR. JAMES OKAFOR — LONGEVITY & PREVENTIVE MEDICINE\nThe 4-week line is flat.\n"
    "🧠 COACH MAYA RODRIGUEZ — BEHAVIOURAL PERFORMANCE\nThe gap is on weekends.\n"
    "🎯 THE CHAIR — VERDICT & PRIORITY\nOne priority: protect sleep.\n"
    "💡 PATTERN OF THE WEEK\nEfficiency fell as strain rose two days earlier."
)


def digest_data(**over):
    """The `data` dict `build_html` consumes, with every required key present."""
    base = {
        "this": {},
        "prior": {},
        "training_load": {"ctl": 40.0, "atl": 35.0, "tsb": 5.0},
        "trends": {"weight": "↓", "hrv": "↑", "recovery": "→", "sleep": "→", "rhr": "→", "day_grade": "↑"},
        "sleep_debt": None,
        "projection": None,
        "open_insights": [],
        "character_sheet": None,
        "character_sheet_prior": None,
        "acwr_data": None,
        "mcp_mutations_line": None,
        "dates": {"this_start": W1_START, "this_end": W1_END, "prior_start": W2_START, "prior_end": W2_END},
    }
    base.update(over)
    return base


def scorecard_value(html, label):
    """The number the reader sees in one scorecard cell (or '—')."""
    m = re.search(
        r'font-weight:700;color:#[0-9a-fA-F]{6};">([^<]*)</div>' r'<div style="font-size:9px;color:#6b7280;">' + re.escape(label) + "<",
        html,
    )
    assert m, f"scorecard cell {label!r} not found"
    return m.group(1)


def _nested_str_tuples(code):
    """Every all-strings tuple constant reachable from a function's code object.

    Used to DERIVE the growable literal lists the module restates inline
    (component names, pillar names, tier names) instead of re-typing them here.
    """
    out = []
    for c in code.co_consts:
        if isinstance(c, tuple) and c and all(isinstance(x, str) for x in c):
            out.append(c)
        if hasattr(c, "co_consts"):
            out.extend(_nested_str_tuples(c))
    return out


# ══════════════════════════════════════════════════════════════════════════════
# Day grades — the headline number and the subject line
# ══════════════════════════════════════════════════════════════════════════════


class TestExDayGrades:
    def test_no_records_is_absence_not_a_zero_week(self):
        assert wd.ex_day_grades({}) is None
        assert wd.ex_day_grades(None) is None

    def test_records_with_no_parseable_score_are_absence_not_zero(self):
        """A day_grade row written without total_score must not average in as 0."""
        grades = as_range("day_grade", {"2026-08-02": {"letter_grade": "B"}})
        assert wd.ex_day_grades(grades) is None

    def test_the_weekly_average_is_the_mean_of_the_graded_days_only(self):
        grades = as_range(
            "day_grade",
            {
                "2026-08-02": {"total_score": Decimal("80"), "letter_grade": "B+"},
                "2026-08-03": {"total_score": Decimal("60"), "letter_grade": "C"},
                "2026-08-04": {"total_score": Decimal("100"), "letter_grade": "A+"},
            },
        )
        out = wd.ex_day_grades(grades)
        # (80 + 60 + 100) / 3 = 240 / 3 = 80.0
        assert out["avg_score"] == 80.0
        assert out["min_score"] == 60.0
        assert out["max_score"] == 100.0
        assert out["days_graded"] == 3

    def test_days_come_back_in_calendar_order_so_the_bar_chart_reads_left_to_right(self):
        grades = as_range(
            "day_grade",
            {
                "2026-08-04": {"total_score": Decimal("70"), "letter_grade": "B-"},
                "2026-08-02": {"total_score": Decimal("90"), "letter_grade": "A"},
                "2026-08-03": {"total_score": Decimal("80"), "letter_grade": "B+"},
            },
        )
        assert [d["date"] for d in wd.ex_day_grades(grades)["days"]] == ["2026-08-02", "2026-08-03", "2026-08-04"]

    def test_every_letter_the_scoring_engine_can_emit_lands_in_a_distribution_bucket(self):
        """DERIVED from scoring_engine.letter_grade — the digest's chip counter
        buckets on prefixes, so a new letter (say 'D+') would silently vanish
        from the distribution chips. This pins the whole emittable set."""
        letters = sorted({scoring_engine.letter_grade(s) for s in range(0, 101)})
        grades = {}
        for i, letter in enumerate(letters):
            d = f"2026-08-{2 + i:02d}"
            grades[d] = rec("day_grade", d, total_score=Decimal("70"), letter_grade=letter)
        counted = sum(wd.ex_day_grades(grades)["grade_counts"].values())
        assert counted == len(letters), f"letters dropped from the distribution: {letters}"

    def test_a_row_with_no_letter_grade_still_counts_as_a_graded_day(self):
        grades = as_range("day_grade", {"2026-08-02": {"total_score": Decimal("70")}})
        out = wd.ex_day_grades(grades)
        assert out["days_graded"] == 1
        assert out["days"][0]["grade"] == "—"


# ══════════════════════════════════════════════════════════════════════════════
# Whoop — recovery, HRV, sleep
# ══════════════════════════════════════════════════════════════════════════════


class TestExWhoop:
    def test_no_records_is_absence(self):
        assert wd.ex_whoop({}) is None

    def test_every_field_read_is_a_field_whoop_actually_writes(self):
        """Reader/writer parity: whoop_lambda stores recovery_score /
        resting_heart_rate / hrv / strain under exactly these names."""
        w = as_range(
            "whoop",
            {
                "2026-08-02": {"hrv": Decimal("40"), "recovery_score": Decimal("30"), "resting_heart_rate": Decimal("60"), "strain": 10},
                "2026-08-03": {"hrv": Decimal("60"), "recovery_score": Decimal("60"), "resting_heart_rate": Decimal("58"), "strain": 14},
            },
        )
        out = wd.ex_whoop(w)
        # hrv (40 + 60)/2 = 50.0 ; recovery (30 + 60)/2 = 45.0 ; rhr (60 + 58)/2 = 59.0
        assert out["hrv_avg"] == 50.0
        assert out["hrv_min"] == 40.0
        assert out["hrv_max"] == 60.0
        assert out["recovery_avg"] == 45.0
        assert out["rhr_avg"] == 59.0
        assert out["strain_avg"] == 12.0

    def test_a_day_missing_hrv_is_skipped_rather_than_averaged_in_as_zero(self):
        w = as_range("whoop", {"2026-08-02": {"hrv": Decimal("40")}, "2026-08-03": {"recovery_score": Decimal("50")}})
        out = wd.ex_whoop(w)
        # Only one HRV reading exists, so the average is that reading — not 20.0.
        assert out["hrv_avg"] == 40.0

    @pytest.mark.xfail(
        strict=False,
        reason=(
            "DEFECT (tranche-3): weekly_digest_lambda.py:242 `ex_whoop` reports `days` as "
            "len(recs) — every Whoop day record in the window — while every average beside it "
            "is computed over only the days that carried that field. A week where the strap "
            "logged recovery on 6 days but HRV on 2 reports hrv_avg over n=2 alongside "
            "days=6. That dict is serialised straight into the Board prompt (call_haiku's "
            "data_json), so the six advisors are told the sample size is 6. ADR-105 requires "
            "n to be the n of the statistic. Hurts: the AI narrates a 2-reading average as a "
            "week's trend."
        ),
    )
    def test_the_reported_day_count_is_the_n_of_the_averages_it_sits_beside(self):
        w = as_range(
            "whoop",
            {
                "2026-08-02": {"hrv": Decimal("40"), "recovery_score": Decimal("30")},
                "2026-08-03": {"hrv": Decimal("60"), "recovery_score": Decimal("40")},
                "2026-08-04": {"recovery_score": Decimal("50")},
                "2026-08-05": {"recovery_score": Decimal("50")},
            },
        )
        out = wd.ex_whoop(w)
        assert out["days"] == 2, "days must describe the HRV sample it is printed next to"


class TestExWhoopSleep:
    def test_no_records_is_absence(self):
        assert wd.ex_whoop_sleep({}) is None

    def test_legacy_whoop_field_names_are_normalised_before_extraction(self):
        """whoop_lambda writes sleep_quality_score / sleep_efficiency_percentage /
        slow_wave_sleep_hours / rem_sleep_hours; the digest reads the canonical
        names via digest_utils._normalize_whoop_sleep."""
        w = as_range(
            "whoop",
            {
                "2026-08-02": {
                    "sleep_quality_score": Decimal("80"),
                    "sleep_duration_hours": Decimal("7.0"),
                    "sleep_efficiency_percentage": Decimal("90"),
                    "slow_wave_sleep_hours": Decimal("1.4"),
                    "rem_sleep_hours": Decimal("1.75"),
                },
            },
        )
        out = wd.ex_whoop_sleep(w)
        assert out["score_avg"] == 80.0
        assert out["duration_avg_hrs"] == 7.0
        assert out["efficiency_avg"] == 90.0
        # deep% = 1.4 / 7.0 * 100 = 20.0 ; rem% = 1.75 / 7.0 * 100 = 25.0
        assert out["deep_pct"] == 20.0
        assert out["rem_pct"] == 25.0

    def test_a_night_with_no_duration_does_not_drag_the_average_to_zero(self):
        w = as_range(
            "whoop",
            {
                "2026-08-02": {"sleep_duration_hours": Decimal("8.0")},
                "2026-08-03": {"recovery_score": Decimal("50")},
            },
        )
        # One measured night at 8.0 → 8.0, not 4.0.
        assert wd.ex_whoop_sleep(w)["duration_avg_hrs"] == 8.0

    def test_worst_night_is_the_minimum_of_the_recorded_scores(self):
        w = as_range(
            "whoop",
            {
                "2026-08-02": {"sleep_score": Decimal("88")},
                "2026-08-03": {"sleep_score": Decimal("54")},
            },
        )
        out = wd.ex_whoop_sleep(w)
        assert out["score_min"] == 54.0
        # (88 + 54)/2 = 71.0
        assert out["score_avg"] == 71.0


class TestComputeSleepDebt:
    def test_no_whoop_data_is_absence_not_zero_debt(self):
        assert wd.compute_sleep_debt({}) is None
        assert wd.compute_sleep_debt(as_range("whoop", {"2026-08-02": {"recovery_score": Decimal("50")}})) is None

    def test_debt_is_the_shortfall_against_target_across_the_measured_nights(self):
        w = as_range(
            "whoop",
            {
                "2026-08-02": {"sleep_duration_hours": Decimal("7.0")},
                "2026-08-03": {"sleep_duration_hours": Decimal("6.0")},
                "2026-08-04": {"sleep_duration_hours": Decimal("5.0")},
            },
        )
        out = wd.compute_sleep_debt(w, 7.5)
        # target 7.5 × 3 nights = 22.5 ; slept 7 + 6 + 5 = 18 ; debt = 4.5
        assert out["debt_hrs"] == 4.5
        assert out["nights"] == 3
        assert out["avg_hrs"] == 6.0

    def test_sleeping_more_than_target_floors_the_debt_at_zero_not_a_credit(self):
        w = as_range("whoop", {"2026-08-02": {"sleep_duration_hours": Decimal("9.0")}})
        # 7.5 - 9.0 = -1.5 → clamped to 0
        assert wd.compute_sleep_debt(w, 7.5)["debt_hrs"] == 0


# ══════════════════════════════════════════════════════════════════════════════
# Withings — weight
# ══════════════════════════════════════════════════════════════════════════════


class TestExWithings:
    def test_no_records_is_absence(self):
        assert wd.ex_withings({}) is None

    def test_latest_weight_is_the_newest_weigh_in_not_an_arbitrary_dict_entry(self):
        """`weight_latest` sorts on the DDB sort key, so insertion order of the
        {date: record} dict must not decide which number the reader sees."""
        w = {
            "2026-08-02": rec("withings", "2026-08-02", weight_lbs=Decimal("310.0")),
            "2026-08-08": rec("withings", "2026-08-08", weight_lbs=Decimal("303.5")),
            "2026-08-05": rec("withings", "2026-08-05", weight_lbs=Decimal("306.0")),
        }
        out = wd.ex_withings(w)
        assert out["weight_latest"] == 303.5
        # (310.0 + 303.5 + 306.0)/3 = 919.5/3 = 306.5
        assert out["weight_avg"] == 306.5
        assert out["weight_min"] == 303.5
        assert out["weight_max"] == 310.0
        assert out["measurements"] == 3

    def test_a_scale_reading_with_no_body_fat_leaves_body_fat_absent(self):
        w = as_range("withings", {"2026-08-02": {"weight_lbs": Decimal("300")}})
        assert wd.ex_withings(w)["body_fat_avg"] is None


class TestWeightProjection:
    def test_fewer_than_two_weekly_averages_yields_no_projection(self):
        assert wd.weight_projection([300.0, None, None, None], 185, 300.0) is None

    def test_a_missing_current_or_goal_weight_yields_no_projection(self):
        assert wd.weight_projection([300.0, 306.0], 185, None) is None
        assert wd.weight_projection([300.0, 306.0], None, 300.0) is None

    def test_a_flat_month_reports_insufficient_data_rather_than_a_fake_eta(self):
        assert wd.weight_projection([300.0, 300.2, 300.1, 300.3], 185, 300.0) == {"status": "insufficient_data"}

    def test_weight_going_up_reports_not_losing_rather_than_a_negative_eta(self):
        assert wd.weight_projection([306.0, 304.0, 302.0, 300.0], 185, 306.0) == {"status": "not_losing"}

    def test_four_consecutive_weeks_give_the_per_week_rate_and_an_eta(self):
        # newest-first: [300, 302, 304, 306] over 3 week-to-week intervals
        # total delta = 300 - 306 = -6 lbs ; rate = -6 / 3 = -2.0 lbs/week
        # weeks to goal = (300 - 285) / 2.0 = 7.5 → round → 8
        out = wd.weight_projection([300.0, 302.0, 304.0, 306.0], 285, 300.0)
        assert out["status"] == "ok"
        assert out["rate_per_week"] == 2.0
        assert out["weeks"] == 8
        # ETA is frozen-clock derived: 2026-08-09 + 7.5 weeks = 2026-09-30
        eta_date = FROZEN_NOW.date() + timedelta(weeks=7.5)
        assert out["eta"] == eta_date.strftime("%B %Y")

    @pytest.mark.xfail(
        strict=False,
        reason=(
            "DEFECT (tranche-3, P1): weekly_digest_lambda.py:696 `weight_projection` computes "
            "`rate_per_week = total_delta / (len(vals) - 1)` AFTER dropping the None weeks — so "
            "the divisor is the count of weeks that HAD a weigh-in, not the weeks that elapsed. "
            "Two weigh-in weeks three weeks apart (301.0 now, 307.0 four weeks ago, nothing in "
            "between) give -6/1 = 6.0 lbs/week instead of the true 2.0 lbs/week, and the '📅 "
            "Projection' row in the Weight section then quotes a goal ETA three times too soon "
            "(and paints it green, since rate >= 0.5). Hurts: Matthew plans around a fabricated "
            "loss rate exactly in the weeks he weighed in least."
        ),
    )
    def test_gaps_between_weigh_in_weeks_do_not_inflate_the_per_week_rate(self):
        # newest-first with weeks 2 and 3 unmeasured: 301.0 this week, 307.0 four weeks ago.
        # Elapsed weeks between the two observations = 3 → true rate = 6.0 / 3 = 2.0 lbs/week.
        out = wd.weight_projection([301.0, None, None, 307.0], 285, 301.0)
        assert out["status"] == "ok"
        assert out["rate_per_week"] == 2.0


# ══════════════════════════════════════════════════════════════════════════════
# Strava
# ══════════════════════════════════════════════════════════════════════════════


def act(name="Morning Walk", sport="Walk", miles=2.0, elev=100.0, hr=None, secs=3600.0, kj=0.0, start="2026-08-02T08:00:00"):
    a = {
        "name": name,
        "sport_type": sport,
        "distance_miles": Decimal(str(miles)),
        "total_elevation_gain_feet": Decimal(str(elev)),
        "moving_time_seconds": Decimal(str(secs)),
        "kilojoules": Decimal(str(kj)),
        "start_date_local": start,
        "distance_meters": Decimal(str(miles * 1609.34)),
    }
    if hr is not None:
        a["average_heartrate"] = Decimal(str(hr))
    return a


class TestExStrava:
    def test_no_records_is_absence(self):
        assert wd.ex_strava({}, profile_row()) is None

    def test_totals_are_summed_across_the_weeks_activities(self):
        recs = {
            "2026-08-02": rec("strava", "2026-08-02", activities=[act(miles=3.0, elev=120.0, secs=3600.0)]),
            "2026-08-04": rec("strava", "2026-08-04", activities=[act(miles=2.5, elev=80.0, secs=1800.0, start="2026-08-04T08:00:00")]),
        }
        out = wd.ex_strava(recs, profile_row())
        # miles 3.0 + 2.5 = 5.5 ; elevation 120 + 80 = 200 ; minutes 60 + 30 = 90
        assert out["total_miles"] == 5.5
        assert out["total_elevation_feet"] == 200
        assert out["total_minutes"] == 90
        assert out["activity_count"] == 2

    def test_the_zone_two_band_is_derived_from_the_profile_max_heart_rate(self):
        out = wd.ex_strava(
            {"2026-08-02": rec("strava", "2026-08-02", activities=[act(hr=120.0)])},
            profile_row(max_heart_rate=200),
        )
        # 200 × 0.60 = 120 ; 200 × 0.70 = 140
        assert out["zone2_hr_range"] == "120-140"
        assert out["zone2_minutes"] == 60  # 120 bpm sits on the band's floor

    def test_a_heart_rate_outside_the_band_earns_no_zone_two_minutes(self):
        out = wd.ex_strava(
            {"2026-08-02": rec("strava", "2026-08-02", activities=[act(hr=150.0)])},
            profile_row(max_heart_rate=186),
        )
        # band is 111.6–130.2 bpm; 150 is above it
        assert out["zone2_minutes"] == 0
        assert out["zone2_pct"] == 0

    def test_the_zone_two_percentage_divides_by_every_logged_activity_minute(self):
        """Characterisation, not endorsement: the row is labelled '% of cardio'
        but the denominator is total moving time across ALL sports, strength
        sessions logged to Strava included."""
        recs = {
            "2026-08-02": rec("strava", "2026-08-02", activities=[act(hr=120.0, secs=3600.0)]),
            "2026-08-03": rec(
                "strava",
                "2026-08-03",
                activities=[act(name="Lift", sport="WeightTraining", hr=150.0, secs=1800.0, start="2026-08-03T18:00:00")],
            ),
        }
        out = wd.ex_strava(recs, profile_row())
        # zone2 60 min ; total 60 + 30 = 90 min → round(60/90*100) = 67
        assert out["zone2_pct"] == 67

    def test_activities_with_no_heart_rate_render_as_absence_not_zero_bpm(self):
        out = wd.ex_strava({"2026-08-02": rec("strava", "2026-08-02", activities=[act(hr=None)])}, profile_row())
        assert out["activities"][0]["hr"] is None

    def test_training_monotony_needs_at_least_three_loaded_days(self):
        recs = {
            "2026-08-02": rec("strava", "2026-08-02", activities=[act(kj=500.0)]),
            "2026-08-03": rec("strava", "2026-08-03", activities=[act(kj=600.0, start="2026-08-03T08:00:00")]),
        }
        assert wd.ex_strava(recs, profile_row())["training_monotony"] is None

    def test_a_duplicate_garmin_sync_of_the_same_session_is_counted_once(self):
        dup = act(name="Morning Walk (Garmin)", secs=3595.0, start="2026-08-02T08:02:00")
        recs = {"2026-08-02": rec("strava", "2026-08-02", activities=[act(), dup])}
        assert wd.ex_strava(recs, profile_row())["activity_count"] == 1


class TestComputeBanister:
    def test_an_empty_window_yields_a_zero_load_model_rather_than_none(self):
        out = wd.compute_banister({})
        assert out["ctl"] == 0.0 and out["atl"] == 0.0 and out["tsb"] == 0.0

    def test_recent_training_raises_fatigue_faster_than_fitness(self):
        recs = {}
        for i in range(7):
            d = (FROZEN_NOW.date() - timedelta(days=i + 1)).isoformat()
            recs[d] = rec("strava", d, activities=[act(secs=3600.0, hr=130.0, start=f"{d}T08:00:00")])
        out = wd.compute_banister(recs)
        # ATL is a 7-day EWMA and CTL a 42-day one, so a week of identical days
        # must leave ATL above CTL and TSB negative.
        assert out["atl"] > out["ctl"] > 0
        assert out["tsb"] < 0

    @pytest.mark.xfail(
        strict=False,
        reason=(
            "DEFECT (tranche-3, P1): weekly_digest_lambda.py:116-121 `query_range` drops "
            "digest_utils.query_range's `include_pilot` parameter entirely, so no caller can "
            "opt into a cross-phase read — and :1033 uses it for the 60-day Banister window. "
            "`strava` classifies as raw_timeseries, i.e. phase_filter.source_reads_cross_phase "
            "returns True, so the pre-genesis days are hidden by the ADR-058 default-deny "
            "filter. This is the exact failure #2109 measured and fixed for the compute "
            "layer's readers ('the Banister load model saw an empty 60-day window (CTL = ATL = "
            "TSB = 0.0, which downstream bands read as perfect freshness rather than as no "
            "data)') — the weekly digest was not included in that fix. Hurts: for the first "
            "six weeks of every experiment cycle the Training Load section reports near-zero "
            "CTL and a positive TSB labelled 'Fresh', and the Board is prompted on it."
        ),
    )
    def test_the_sixty_day_load_window_survives_an_experiment_reset(self, table, monkeypatch):
        monkeypatch.setattr(wd, "fetch_profile", lambda: profile_row())
        # 60 days of identical training; everything before the cycle-12 genesis is
        # tagged phase=pilot by the reset (ADR-077), which is most of the window.
        genesis = "2026-08-03"
        for i in range(1, 61):
            d = (FROZEN_NOW.date() - timedelta(days=i)).isoformat()
            row = rec("strava", d, activities=[act(secs=3600.0, hr=130.0, start=f"{d}T08:00:00")])
            row["phase"] = EXPERIMENT_PHASE_CURRENT if d >= genesis else "pilot"
            table.add(row)
        strava_60d = wd.query_range("strava", (FROZEN_NOW.date() - timedelta(days=60)).isoformat(), W1_END)
        out = wd.compute_banister(strava_60d)
        # A 42-day EWMA over 60 consecutive identical training days must be a real
        # fitness number, not the near-zero of a five-day-old cycle.
        assert out["ctl"] > 10, f"pre-genesis training vanished from the load model: {out}"


# ══════════════════════════════════════════════════════════════════════════════
# Nutrition, strength, habits, Apple Health, Todoist
# ══════════════════════════════════════════════════════════════════════════════


class TestExMacrofactor:
    def test_no_records_is_absence(self):
        assert wd.ex_macrofactor({}, profile_row()) is None

    def test_averages_and_hit_rates_come_from_the_profile_targets(self):
        m = as_range(
            "macrofactor",
            {
                "2026-08-02": {
                    "total_calories_kcal": Decimal("1500"),
                    "total_protein_g": Decimal("200"),
                    "total_fat_g": Decimal("50"),
                    "total_carbs_g": Decimal("120"),
                    "total_fiber_g": Decimal("30"),
                },
                "2026-08-03": {
                    "total_calories_kcal": Decimal("2200"),
                    "total_protein_g": Decimal("100"),
                    "total_fat_g": Decimal("70"),
                    "total_carbs_g": Decimal("180"),
                    "total_fiber_g": Decimal("20"),
                },
            },
        )
        out = wd.ex_macrofactor(m, profile_row())
        # calories (1500 + 2200)/2 = 1850.0 ; protein (200 + 100)/2 = 150.0
        assert out["calories_avg"] == 1850.0
        assert out["protein_avg_g"] == 150.0
        # calorie hit = c <= 1800 × 1.10 = 1980 → 1500 yes, 2200 no → 1/2 = 50%
        assert out["calorie_hit_rate"] == 50
        # protein hit = p >= 190 → 200 yes, 100 no → 1/2 = 50%
        assert out["protein_hit_rate"] == 50
        assert out["days_logged"] == 2

    def test_a_day_with_no_totals_leaves_the_hit_rates_absent_not_zero(self):
        m = as_range("macrofactor", {"2026-08-02": {"food_log": []}})
        out = wd.ex_macrofactor(m, profile_row())
        assert out["calorie_hit_rate"] is None
        assert out["protein_hit_rate"] is None
        assert out["calories_avg"] is None

    @pytest.mark.xfail(
        strict=False,
        reason=(
            "DEFECT (tranche-3, P2 — window/denominator honesty, #1917): "
            "weekly_digest_lambda.py:365-366 `ex_macrofactor` divides both hit rates by "
            "len(cals)/len(prots) — the days he LOGGED — while the section they render into is "
            "the week. One logged day at target renders 'Protein Hit Rate: 100%' with a full "
            "green bar (hit_bar, :1802/:1808) for a week he logged once. 'Days Logged' is a "
            "separate row further down the same table, so the two numbers never appear as a "
            "fraction. ADR-104: an unlogged day is absence, and a rate quoted over the week "
            "must either use the week's denominator or state its own n. Hurts: Matthew reads a "
            "perfect adherence week off one meal-logged day."
        ),
    )
    def test_a_hit_rate_is_stated_against_the_week_not_only_the_logged_days(self):
        m = as_range("macrofactor", {"2026-08-02": {"total_calories_kcal": Decimal("1500"), "total_protein_g": Decimal("200")}})
        out = wd.ex_macrofactor(m, profile_row())
        # One logged day out of a seven-day week: at most 1/7 ≈ 14%, never 100%.
        assert out["protein_hit_rate"] is None or out["protein_hit_rate"] <= 15


class TestExHevyWorkouts:
    def test_no_workouts_is_absence(self):
        assert wd.ex_hevy_workouts([]) is None
        assert wd.ex_hevy_workouts(None) is None

    def test_volume_converts_kilograms_to_pounds_and_multiplies_by_reps(self):
        workout = {
            "date": "2026-08-04",
            "title": "Push A",
            "exercises": [
                {"sets": [{"weight_kg": Decimal("100"), "reps": 5}, {"weight_kg": Decimal("50"), "reps": 10}]},
            ],
        }
        out = wd.ex_hevy_workouts([workout])
        # 100 kg = 100 / 0.45359237 = 220.46226 lb × 5 = 1102.3113
        #  50 kg =  50 / 0.45359237 = 110.23113 lb × 10 = 1102.3113
        # total = 2204.6226 → round → 2205
        assert out["total_volume_lbs"] == 2205
        assert out["total_sets"] == 2
        assert out["workout_count"] == 1
        assert out["workouts"][0]["name"] == "Push A"

    def test_two_workouts_on_the_same_day_are_both_counted(self):
        """Hevy is read as a flat list precisely so a two-a-day is not collapsed."""
        w = [
            {"date": "2026-08-04", "title": "AM", "exercises": [{"sets": [{"weight_kg": Decimal("50"), "reps": 10}]}]},
            {"date": "2026-08-04", "title": "PM", "exercises": [{"sets": [{"weight_kg": Decimal("50"), "reps": 10}]}]},
        ]
        assert wd.ex_hevy_workouts(w)["workout_count"] == 2

    def test_a_bodyweight_set_counts_as_a_set_without_inventing_volume(self):
        w = [{"date": "2026-08-04", "title": "Pull", "exercises": [{"sets": [{"reps": 12}]}]}]
        out = wd.ex_hevy_workouts(w)
        assert out["total_sets"] == 1
        assert out["total_volume_lbs"] == 0

    def test_an_untitled_workout_gets_a_placeholder_rather_than_a_blank_row(self):
        w = [{"date": "2026-08-04", "exercises": []}]
        assert wd.ex_hevy_workouts(w)["workouts"][0]["name"] == "Workout"

    def test_the_best_workout_is_the_highest_volume_session(self):
        w = [
            {"date": "2026-08-04", "title": "Light", "exercises": [{"sets": [{"weight_kg": Decimal("20"), "reps": 5}]}]},
            {"date": "2026-08-06", "title": "Heavy", "exercises": [{"sets": [{"weight_kg": Decimal("100"), "reps": 5}]}]},
        ]
        assert wd.ex_hevy_workouts(w)["best_workout"]["name"] == "Heavy"


class TestExHabitify:
    def test_no_records_is_absence(self):
        assert wd.ex_habitify({}, profile_row()) is None

    def test_mvp_completion_is_counted_against_the_profiles_habit_list(self):
        p = profile_row(mvp_habits=["a", "b", "c", "d"])
        h = as_range(
            "habitify",
            {
                "2026-08-02": {"habits": {"a": 1, "b": 1, "c": 0, "d": 0}, "completion_pct": Decimal("0.5")},
                "2026-08-03": {"habits": {"a": 1, "b": 1, "c": 1, "d": 1}, "completion_pct": Decimal("1.0")},
            },
        )
        out = wd.ex_habitify(h, p)
        # day 1: 2/4 = 50% ; day 2: 4/4 = 100% → mean = 75.0
        assert out["mvp_avg_pct"] == 75.0
        # completion_pct is a fraction on the writer side → ×100 for display
        assert out["overall_avg_pct"] == 75.0
        assert out["mvp_completion"] == {"a": 2, "b": 2, "c": 1, "d": 1}
        assert out["days_tracked"] == 2
        assert out["mvp_total"] == 4

    def test_a_day_with_no_habit_map_is_not_counted_as_a_tracked_day(self):
        p = profile_row(mvp_habits=["a"])
        h = as_range("habitify", {"2026-08-02": {"habits": {"a": 1}}, "2026-08-03": {"habits": {}}})
        assert wd.ex_habitify(h, p)["days_tracked"] == 1

    @pytest.mark.xfail(
        strict=False,
        reason=(
            "DEFECT (tranche-3, P2 — ADR-104 absence-as-zero): weekly_digest_lambda.py:433 "
            "`ex_habitify` reads `habits_map.get(h, 0)` — an MVP habit that Habitify did not "
            "return for a day at all (archived, paused, renamed, or an ingestion gap) is scored "
            "an explicit MISS, indistinguishable from a habit he was offered and skipped. The "
            "per-habit row then renders '0/7 (0%)' in red for a habit that was never tracked. "
            "Hurts: a habit rename silently reads as a total collapse in adherence, and the "
            "MVP average it feeds is depressed by data absence."
        ),
    )
    def test_a_habit_absent_from_the_days_map_is_absence_not_a_recorded_miss(self):
        p = profile_row(mvp_habits=["tracked", "archived"])
        h = as_range("habitify", {"2026-08-02": {"habits": {"tracked": 1}}})
        out = wd.ex_habitify(h, p)
        # Only one of the two habits was tracked at all, and it was completed.
        assert out["mvp_avg_pct"] == 100.0


class TestExAppleHealth:
    def test_no_records_is_absence(self):
        assert wd.ex_apple_health({}) is None

    def test_every_field_read_is_a_field_health_auto_export_actually_writes(self):
        a = as_range(
            "apple_health",
            {
                "2026-08-02": {
                    "steps": Decimal("10000"),
                    "water_intake_ml": Decimal("2000"),
                    "blood_glucose_avg": Decimal("95"),
                    "blood_glucose_time_in_range_pct": Decimal("92"),
                    "walking_speed_mph": Decimal("3.1"),
                },
                "2026-08-03": {"steps": Decimal("12000"), "water_intake_ml": Decimal("1000")},
            },
        )
        out = wd.ex_apple_health(a)
        # steps (10000 + 12000)/2 = 11000.0 ; total 22000
        assert out["steps_avg"] == 11000.0
        assert out["steps_total"] == 22000
        # water (2000 + 1000)/2 = 1500.0
        assert out["water_avg_ml"] == 1500.0
        assert out["glucose_avg"] == 95.0
        assert out["glucose_tir_avg"] == 92.0
        assert out["gait_speed_avg"] == 3.1
        assert out["days"] == 2

    def test_a_trivially_small_water_reading_is_discarded_from_the_average(self):
        """Characterisation: the 118 ml (4 oz) floor treats a genuinely low
        hydration day as absence, which lifts water_avg_ml."""
        a = as_range("apple_health", {"2026-08-02": {"water_intake_ml": Decimal("100")}})
        out = wd.ex_apple_health(a)
        assert out["water_days"] == 0
        assert out["water_avg_ml"] is None


class TestExTodoist:
    def test_no_records_is_absence(self):
        assert wd.ex_todoist({}) is None

    def test_completed_tasks_are_read_from_the_field_todoist_actually_writes(self):
        """#2245: todoist_lambda writes `completed_count` (the #480/A-7 rename
        documented in ingestion_validator.py:292). Reading the pre-rename
        `tasks_completed` matched nothing and published a permanent measured zero."""
        t = as_range("todoist", {"2026-08-02": {"completed_count": 5}, "2026-08-03": {"completed_count": 7}})
        out = wd.ex_todoist(t)
        # 5 + 7 = 12 completions over 2 days → 6.0 per day
        assert out["tasks_completed"] == 12
        assert out["avg_per_day"] == 6.0
        assert out["days"] == 2

    def test_the_pre_rename_field_name_is_not_what_is_read(self):
        """Regression guard for #2245 in the other direction: a record carrying ONLY the
        dead `tasks_completed` name is not silently counted. No record in the live
        partition has carried that name since 2022 — reading it back would re-introduce
        exactly the ambiguity the rename removed."""
        t = as_range("todoist", {"2026-08-02": {"tasks_completed": 5}, "2026-08-03": {"tasks_completed": 7}})
        out = wd.ex_todoist(t)
        assert out["tasks_completed"] == 0
        assert out["days"] == 2

    def test_a_null_completed_count_is_treated_as_zero_not_a_crash(self):
        t = as_range("todoist", {"2026-08-02": {"completed_count": None}, "2026-08-03": {"completed_count": 4}})
        assert wd.ex_todoist(t)["tasks_completed"] == 4

    def test_the_rendered_row_and_its_delta_carry_the_real_count(self):
        """End-to-end over the real extractor: raw records → ex_todoist → build_html.
        Before #2245 both weeks extracted to 0 and the delta arrow compared two zeros."""
        this = wd.ex_todoist(as_range("todoist", {"2026-08-02": {"completed_count": 5}, "2026-08-03": {"completed_count": 7}}))
        prior = wd.ex_todoist(as_range("todoist", {"2026-07-26": {"completed_count": 3}}))
        html = wd.build_html(digest_data(this={"todoist": this}, prior={"todoist": prior}), BOARD_TEXT, profile_row())
        assert "Tasks Completed" in html and ">12<" in html
        assert "6.0" in html  # avg per day, not 0.0
        assert "↑9" in html  # week-over-week delta: 12 vs 3, not the →0 of two dead zeros
        assert "→0" not in html

    def test_the_board_prompt_payload_carries_the_real_completion_count(self, monkeypatch):
        """The same `this`/`prior` dict is serialised verbatim into BOARD_PROMPT's
        data_json — a permanently-zero todoist signal was being reasoned over."""
        captured = {}

        def fake_call(req, **kwargs):
            captured["req"] = req
            return {"content": [{"text": BOARD_TEXT}]}

        monkeypatch.setattr(wd, "call_anthropic_with_retry", fake_call)
        monkeypatch.setattr(wd, "_presence_block", lambda: "")
        monkeypatch.setattr(wd, "_HAS_INSIGHT_WRITER", False)

        this = wd.ex_todoist(as_range("todoist", {"2026-08-02": {"completed_count": 5}, "2026-08-03": {"completed_count": 7}}))
        wd.call_haiku(digest_data(this={"todoist": this}), profile_row())
        import json as _json

        prompt = _json.loads(captured["req"].data.decode())["messages"][0]["content"]
        assert '"tasks_completed": 12' in prompt


# ══════════════════════════════════════════════════════════════════════════════
# Journal
# ══════════════════════════════════════════════════════════════════════════════


def jentry(**fields):
    return {"template": "Daily", **fields}


class TestExJournal:
    def test_no_entries_is_absence(self):
        assert wd.ex_journal({}) is None
        assert wd.ex_journal({"2026-08-02": []}) is None

    def test_enriched_scores_are_averaged_across_entries(self):
        entries = {
            "2026-08-02": [jentry(enriched_mood=4, enriched_energy=3, enriched_stress=2)],
            "2026-08-03": [jentry(enriched_mood=2, enriched_energy=5, enriched_stress=4)],
        }
        out = wd.ex_journal(entries)
        # mood (4 + 2)/2 = 3.0 ; energy (3 + 5)/2 = 4.0 ; stress (2 + 4)/2 = 3.0
        assert out["mood_avg"] == 3.0
        assert out["energy_avg"] == 4.0
        assert out["stress_avg"] == 3.0
        assert out["entries"] == 2
        assert out["days_journaled"] == 2

    def test_the_raw_notion_field_is_used_only_when_the_enrichment_is_missing(self):
        entries = {
            "2026-08-02": [jentry(enriched_mood=5, morning_mood=1)],
            "2026-08-03": [jentry(morning_mood=3)],
        }
        # enriched wins on day 1 → (5 + 3)/2 = 4.0
        assert wd.ex_journal(entries)["mood_avg"] == 4.0

    def test_best_and_worst_mood_days_come_from_the_per_day_means(self):
        entries = {
            "2026-08-02": [jentry(enriched_mood=5), jentry(enriched_mood=3)],
            "2026-08-03": [jentry(enriched_mood=1)],
        }
        out = wd.ex_journal(entries)
        # 2026-08-02 mean = (5 + 3)/2 = 4.0 ; 2026-08-03 = 1.0
        assert out["best_mood_day"] == {"date": "2026-08-02", "score": 4.0}
        assert out["worst_mood_day"] == {"date": "2026-08-03", "score": 1.0}

    def test_themes_are_ranked_by_frequency_and_capped_at_six(self):
        entries = {
            "2026-08-02": [jentry(enriched_themes=["work"] * 3 + ["sleep"] * 2 + [f"t{i}" for i in range(6)])],
        }
        out = wd.ex_journal(entries)
        assert out["top_themes"][0] == ("work", 3)
        assert out["top_themes"][1] == ("sleep", 2)
        assert len(out["top_themes"]) == 6

    def test_avoidance_flags_are_deduplicated_and_capped(self):
        entries = {
            "2026-08-02": [jentry(enriched_avoidance_flags=["scrolling", "scrolling", "snacking"])],
        }
        assert wd.ex_journal(entries)["avoidance_flags"] == ["scrolling", "snacking"]

    def test_notable_quotes_carry_their_date_and_are_capped_at_three(self):
        entries = {f"2026-08-0{2 + i}": [jentry(enriched_notable_quote=f"q{i}")] for i in range(4)}
        out = wd.ex_journal(entries)
        assert len(out["notable_quotes"]) == 3
        assert all(set(q) == {"date", "quote"} for q in out["notable_quotes"])

    def test_an_entry_with_no_scores_at_all_leaves_the_averages_absent(self):
        assert wd.ex_journal({"2026-08-02": [jentry(raw_text="just words")]})["mood_avg"] is None

    def test_raw_energy_and_stress_fields_back_fill_a_missing_enrichment(self):
        entries = {"2026-08-02": [jentry(morning_energy=4, stress_level=2, enriched_cognitive_patterns=["catastrophising"])]}
        out = wd.ex_journal(entries)
        assert out["energy_avg"] == 4.0
        assert out["stress_avg"] == 2.0
        assert out["cognitive_patterns"] == ["catastrophising"]

    def test_the_end_of_day_energy_field_is_the_second_raw_fallback(self):
        assert wd.ex_journal({"2026-08-02": [jentry(energy_eod=5)]})["energy_avg"] == 5.0

    def test_emotions_are_ranked_alongside_themes(self):
        entries = {"2026-08-02": [jentry(enriched_emotions=["anxious", "anxious", "calm"])]}
        assert wd.ex_journal(entries)["top_emotions"][0] == ("anxious", 2)


# ══════════════════════════════════════════════════════════════════════════════
# Character sheet
# ══════════════════════════════════════════════════════════════════════════════


def cs_row(date_str, level, pillars, **extra):
    r = {"character_level": level, **extra}
    for name, pd in pillars.items():
        r[f"pillar_{name}"] = pd
    return rec("character_sheet", date_str, **r)


class TestExCharacterSheet:
    def test_no_records_is_absence(self):
        assert wd.ex_character_sheet({}) is None

    def test_level_delta_is_measured_from_the_first_to_the_last_day_of_the_week(self):
        recs = {
            "2026-08-02": cs_row("2026-08-02", 3, {"sleep": {"level": 2, "xp_delta": 10, "raw_score": 50}}),
            "2026-08-08": cs_row("2026-08-08", 5, {"sleep": {"level": 4, "xp_delta": 15, "raw_score": 70}}, character_xp=900),
        }
        out = wd.ex_character_sheet(recs)
        assert out["character_level_start"] == 3
        assert out["character_level_end"] == 5
        assert out["character_level_delta"] == 2
        assert out["character_xp"] == 900
        sleep = out["pillar_summary"]["sleep"]
        assert sleep["level_delta"] == 4 - 2 == 2
        # xp_delta 10 + 15 = 25 ; raw (50 + 70)/2 = 60.0
        assert sleep["xp_earned"] == 25
        assert sleep["avg_raw"] == 60.0

    def test_a_pillar_with_no_stored_block_reports_absence_for_its_raw_score(self):
        recs = {"2026-08-02": cs_row("2026-08-02", 1, {})}
        assert wd.ex_character_sheet(recs)["pillar_summary"]["mind"]["avg_raw"] is None

    def test_closest_to_tier_picks_the_pillar_with_the_smallest_positive_gap(self):
        recs = {
            "2026-08-08": cs_row(
                "2026-08-08",
                12,
                {
                    "sleep": {"level": 4, "tier": "Foundation"},
                    "movement": {"level": 18, "tier": "Foundation"},
                },
            )
        }
        out = wd.ex_character_sheet(recs)
        # Momentum starts at level 21 → movement gap 3, sleep gap 17
        assert out["closest_to_tier"]["pillar"] == "movement"
        assert out["closest_to_tier"]["levels_needed"] == 3
        assert out["closest_to_tier"]["next_tier"] == "Momentum"

    def test_a_pillar_already_at_the_top_tier_never_becomes_closest_to_tier(self):
        pillars = {p: {"level": 90, "tier": "Elite"} for p in list(character_engine.PILLAR_COMPUTERS) + ["consistency"]}
        recs = {"2026-08-08": cs_row("2026-08-08", 90, pillars)}
        assert wd.ex_character_sheet(recs)["closest_to_tier"] is None

    def test_a_pillar_the_record_never_stored_is_treated_as_level_zero(self):
        """Characterisation: an absent pillar block defaults to level 0 /
        Foundation, so it can be nominated as 'closest to tier' on data that was
        never written. Harmless while the writer always emits all seven."""
        recs = {"2026-08-08": cs_row("2026-08-08", 90, {"sleep": {"level": 90, "tier": "Elite"}})}
        out = wd.ex_character_sheet(recs)
        assert out["pillar_summary"]["movement"]["end_level"] == 0
        assert out["closest_to_tier"]["levels_needed"] == 21

    def test_level_events_are_stamped_with_the_day_they_happened(self):
        recs = {
            "2026-08-04": cs_row("2026-08-04", 4, {}, level_events=[{"type": "pillar_up", "pillar": "sleep"}]),
            "2026-08-05": cs_row("2026-08-05", 5, {}, level_events=[]),
        }
        events = wd.ex_character_sheet(recs)["events"]
        assert events == [{"type": "pillar_up", "pillar": "sleep", "date": "2026-08-04"}]

    def test_the_pillar_set_matches_the_character_engines_registry(self):
        """DERIVED, per the repo's guard-the-SET rule: a new pillar added to
        character_engine must not silently vanish from the digest."""
        (pillar_order,) = [t for t in _nested_str_tuples(wd.ex_character_sheet.__code__) if "sleep" in t]
        expected = list(character_engine.PILLAR_COMPUTERS) + ["consistency"]
        assert list(pillar_order) == expected

    def test_the_tier_names_and_thresholds_match_the_character_engines_ladder(self):
        """DERIVED: `next_min = [1, 21, 41, 61, 81][tier_idx + 1]` is a second,
        silent copy of the tier ladder — pin both halves to the registry."""
        tuples = _nested_str_tuples(wd.ex_character_sheet.__code__)
        (tier_order,) = [t for t in tuples if "Foundation" in t]
        assert list(tier_order) == [t["name"] for t in character_engine._DEFAULT_TIERS]
        mins = [c for c in wd.ex_character_sheet.__code__.co_consts if isinstance(c, list)]
        mins += [list(c) for c in wd.ex_character_sheet.__code__.co_consts if isinstance(c, tuple) and all(isinstance(x, int) for x in c)]
        expected_mins = [t["min_level"] for t in character_engine._DEFAULT_TIERS]
        assert any(m == expected_mins for m in mins), f"tier min-levels drifted from the engine: {expected_mins}"


# ══════════════════════════════════════════════════════════════════════════════
# Small render helpers
# ══════════════════════════════════════════════════════════════════════════════


class TestDeltaHtml:
    def test_a_missing_side_renders_no_delta_at_all(self):
        assert wd.delta_html(None, 5) == ""
        assert wd.delta_html(5, None) == ""

    def test_an_unchanged_metric_renders_a_flat_marker_not_a_blank(self):
        assert "→0" in wd.delta_html(5.0, 5.0)

    def test_an_increase_is_green_when_more_is_better(self):
        out = wd.delta_html(10.0, 8.0)
        assert "#27ae60" in out and "↑2.0" in out

    def test_an_increase_is_red_when_less_is_better(self):
        out = wd.delta_html(310.0, 308.0, " lbs", invert=True)
        assert "#e74c3c" in out and "↑2.0 lbs" in out

    def test_a_decrease_is_green_when_less_is_better(self):
        out = wd.delta_html(308.0, 310.0, " lbs", invert=True)
        assert "#27ae60" in out and "↓2.0 lbs" in out


class TestHitBar:
    def test_no_rate_renders_an_em_dash_rather_than_an_empty_bar(self):
        assert wd.hit_bar(None) == "—"

    def test_the_bar_width_is_clamped_while_the_stated_number_is_not(self):
        out = wd.hit_bar(150)
        assert ">150%<" in out
        assert "width:100%" in out

    def test_a_zero_rate_renders_a_zero_width_bar(self):
        assert "width:0%" in wd.hit_bar(0)


class TestGradeColour:
    def test_the_colour_ladder_matches_the_scoring_engines(self):
        """DERIVED: weekly_digest carries its own copy of grade_colour."""
        for score in range(0, 101):
            letter = scoring_engine.letter_grade(score)
            assert wd.grade_colour(letter) == scoring_engine.grade_colour(letter)


class TestCompute4WeekTrends:
    def test_a_single_observed_week_is_not_a_trend(self):
        assert wd.compute_4week_trends({"whoop": [{"hrv_avg": 50}, None, None, None]})["hrv"] == "→"

    def test_the_arrow_compares_this_week_against_the_oldest_observed_week(self):
        # newest-first [50, 48, None, 45] → slope = 50 - 45 = 5 → up
        trends = wd.compute_4week_trends({"whoop": [{"hrv_avg": 50}, {"hrv_avg": 48}, None, {"hrv_avg": 45}]})
        assert trends["hrv"] == "↑"

    def test_a_sub_half_unit_change_reads_as_flat(self):
        trends = wd.compute_4week_trends({"whoop": [{"hrv_avg": 50.0}, {"hrv_avg": 49.8}]})
        assert trends["hrv"] == "→"

    def test_every_metric_gets_an_arrow_even_with_no_data_at_all(self):
        trends = wd.compute_4week_trends({})
        assert set(trends) == {"weight", "hrv", "recovery", "sleep", "rhr", "day_grade"}
        assert set(trends.values()) == {"→"}

    def test_a_falling_series_reads_as_down(self):
        trends = wd.compute_4week_trends({"withings": [{"weight_avg": 300.0}, {"weight_avg": 303.0}, {"weight_avg": 306.0}]})
        assert trends["weight"] == "↓"


# ══════════════════════════════════════════════════════════════════════════════
# Open insights
# ══════════════════════════════════════════════════════════════════════════════


def insight_row(sk_suffix, date_saved, status="open", text="Try a 20-minute walk after dinner", tags=None):
    return {
        "pk": "USER#matthew#SOURCE#insights",
        "sk": f"INSIGHT#{sk_suffix}",
        "text": text,
        "date_saved": date_saved,
        "status": status,
        "tags": tags or ["experiment"],
    }


class TestFetchStaleInsights:
    def test_a_failed_read_degrades_to_no_section_rather_than_aborting_the_digest(self, table):
        table.query_error = RuntimeError("throttled")
        assert wd.fetch_stale_insights() == []

    def test_a_resolved_insight_is_never_reported_as_open(self, table):
        table.add(insight_row("2026-06-01T00:00:00", "2026-06-01T00:00:00Z", status="resolved"))
        assert wd.fetch_stale_insights() == []

    def test_a_timestamped_insight_older_than_the_threshold_is_reported(self, table):
        table.add(insight_row("2026-07-01T00:00:00", "2026-07-01T00:00:00Z"))
        stale = wd.fetch_stale_insights(days_threshold=7)
        # frozen now 2026-08-09 minus 2026-07-01 = 39 days
        assert len(stale) == 1
        assert stale[0]["days_open"] == 39
        assert stale[0]["date_saved"] == "2026-07-01"

    def test_the_oldest_open_insight_is_listed_first(self, table):
        table.add(insight_row("2026-07-01T00:00:00", "2026-07-01T00:00:00Z", text="older"))
        table.add(insight_row("2026-07-20T00:00:00", "2026-07-20T00:00:00Z", text="newer"))
        assert [s["text"] for s in wd.fetch_stale_insights()] == ["older", "newer"]

    @pytest.mark.xfail(
        strict=False,
        reason=(
            "DEFECT (tranche-3, P1 — the Open Insights section is permanently dark): "
            "weekly_digest_lambda.py:753-756 parses `date_saved` with "
            "datetime.fromisoformat(...) and subtracts it from a tz-AWARE "
            "datetime.now(timezone.utc). But BOTH writers store a date-only string — "
            "mcp/tools_lifestyle.py:266 and insight_email_parser_lambda.py:137 both use "
            "now.strftime('%Y-%m-%d') — which parses NAIVE, so the subtraction raises "
            "TypeError, the bare `except Exception` sets days_open = 0, and 0 >= 7 is never "
            "true. Every real insight is therefore filtered out and the '⏳ N Open Insights' "
            "box (:1950-1965) has never rendered. The MCP sibling gets it right "
            "(tools_lifestyle.py:314 compares two dates). Hurts: the accountability loop — "
            "the insights Matthew saves are never surfaced back to him."
        ),
    )
    def test_an_insight_saved_in_the_format_the_writers_use_is_reported_as_stale(self, table):
        table.add(insight_row("2026-07-01T00:00:00", "2026-07-01"))
        stale = wd.fetch_stale_insights(days_threshold=7)
        assert len(stale) == 1, "date-only date_saved (what both writers store) never goes stale"
        assert stale[0]["days_open"] == 39

    @pytest.mark.xfail(
        strict=False,
        reason=(
            "DEFECT (tranche-3, P3): weekly_digest_lambda.py:734-742 `fetch_stale_insights` "
            "issues ONE table.query and reads resp['Items'] with no LastEvaluatedKey loop, "
            "unlike every other read in this module (digest_utils.query_range and "
            "_attribution_breakdown both paginate). DynamoDB truncates a query at 1 MB, so "
            "once the insights partition grows past a page the oldest open items — exactly "
            "the ones the section exists to surface — fall off silently. Hurts: a silently "
            "truncated accountability list reads as a complete one."
        ),
    )
    def test_a_paginated_insights_partition_is_read_to_the_end(self, table):
        old = insight_row("2026-07-01T00:00:00", "2026-07-01T00:00:00Z", text="page two item")
        table.pages = [
            {"Items": [], "LastEvaluatedKey": {"pk": old["pk"], "sk": "INSIGHT#page1"}},
            {"Items": [old]},
        ]
        assert [s["text"] for s in wd.fetch_stale_insights()] == ["page two item"]


# ══════════════════════════════════════════════════════════════════════════════
# Gate telemetry (owner-private readout)
# ══════════════════════════════════════════════════════════════════════════════


class TestSubscriberTelemetry:
    def test_confirmed_subscribers_are_counted_and_canaries_excluded(self, table):
        table.add(sub_row("SUB#a@x.test"))
        table.add(sub_row("SUB#b@x.test"))
        table.add(sub_row("SUB#canary", source="canary"))
        table.add(sub_row("SUB#pending", status="pending"))
        assert wd._count_real_subscribers() == 2

    def test_a_failed_count_fails_open_to_a_sentinel_rather_than_blocking_the_digest(self, table):
        table.query_error = RuntimeError("ddb down")
        assert wd._count_real_subscribers() == -1

    def test_attribution_prefers_a_measured_utm_over_self_report_over_referrer(self, table):
        table.add(sub_row("SUB#1", attr_utm_source="rss", attr_self_reported="a friend", attr_referrer_host="news.test"))
        table.add(sub_row("SUB#2", attr_self_reported="a friend", attr_referrer_host="news.test"))
        table.add(sub_row("SUB#3", attr_referrer_host="news.test"))
        table.add(sub_row("SUB#4"))
        labels = dict(wd._attribution_breakdown())
        assert labels == {"utm:rss": 1, "said:a friend": 1, "ref:news.test": 1, "unattributed": 1}

    def test_the_breakdown_is_ordered_by_count_then_label_and_capped(self, table):
        for i in range(3):
            table.add(sub_row(f"SUB#a{i}", attr_utm_source="rss"))
        table.add(sub_row("SUB#b", attr_utm_source="bluesky"))
        table.add(sub_row("SUB#c", attr_utm_source="mastodon"))
        out = wd._attribution_breakdown(limit=2)
        # rss 3 first; then bluesky and mastodon tie at 1 and sort alphabetically
        assert out == [("utm:rss", 3), ("utm:bluesky", 1)]

    def test_the_breakdown_reads_every_page_so_it_is_never_silently_truncated(self, table):
        rows = [sub_row(f"SUB#{i}", attr_utm_source="rss") for i in range(2)]
        table.pages = [
            {"Items": [rows[0]], "LastEvaluatedKey": {"pk": rows[0]["pk"], "sk": rows[0]["sk"]}},
            {"Items": [rows[1]]},
        ]
        assert wd._attribution_breakdown() == [("utm:rss", 2)]

    def test_a_failed_breakdown_fails_open_to_an_empty_list(self, table):
        table.query_error = RuntimeError("ddb down")
        assert wd._attribution_breakdown() == []

    def test_a_self_reported_label_is_length_capped(self, table):
        table.add(sub_row("SUB#1", attr_self_reported="x" * 100))
        label, _count = wd._attribution_breakdown()[0]
        assert label == "said:" + "x" * 24

    def test_gate_telemetry_survives_a_reset_week_where_withings_is_present_but_none(self):
        """The 2026-07-19 Sunday DLQ crash: `.get(k, {})` does not guard an
        existing key whose value is None."""
        out = wd._gate_telemetry({"this": {"withings": None}}, profile_row(), 4)
        assert out["current_weight"] is None
        assert out["real_subscribers"] == 4
        assert out["goal_weight"] == 185

    def test_gate_telemetry_reads_the_latest_weight_when_there_is_one(self):
        data = {"this": {"withings": {"weight_latest": 303.5}}}
        assert wd._gate_telemetry(data, profile_row(), 1)["current_weight"] == 303.5


class TestEscaping:
    def test_free_text_a_stranger_typed_is_escaped_before_it_reaches_the_email(self):
        assert wd._esc('<img src=x onerror="alert(1)">') == "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;"

    def test_a_hostile_attribution_label_is_escaped_in_the_rendered_gate_row(self):
        data = digest_data()
        data["_gate"] = {"real_subscribers": 1, "attribution": [("said:<script>x</script>", 1)], "current_weight": None}
        html = wd.build_html(data, BOARD_TEXT, profile_row())
        assert "<script>x</script>" not in html
        assert "&lt;script&gt;" in html

    def test_no_attributed_signups_reads_as_an_honest_absence_not_a_zero(self):
        data = digest_data()
        data["_gate"] = {"real_subscribers": 0, "attribution": [], "current_weight": None}
        html = wd.build_html(data, BOARD_TEXT, profile_row())
        assert "no attributed signups yet" in html

    def test_an_unavailable_subscriber_count_renders_a_question_mark_not_a_zero(self):
        data = digest_data()
        data["_gate"] = {"real_subscribers": -1, "attribution": [], "current_weight": None}
        html = wd.build_html(data, BOARD_TEXT, profile_row())
        assert "confirmed subscribers (real): <strong>?</strong>" in html


# ══════════════════════════════════════════════════════════════════════════════
# MCP audit trail line
# ══════════════════════════════════════════════════════════════════════════════


class TestMcpMutationsLine:
    def test_the_tool_name_is_read_out_of_the_object_key_with_a_count(self, monkeypatch):
        s3 = FakeS3(
            {
                "mcp-audit/2026/08/02/": ["mcp-audit/2026/08/02/120000-save_insight-ab12cd34.json"],
                "mcp-audit/2026/08/03/": [
                    "mcp-audit/2026/08/03/090000-save_insight-11112222.json",
                    "mcp-audit/2026/08/03/100000-log_decision-33334444.json",
                ],
            }
        )
        monkeypatch.setattr(wd, "boto3", FakeBoto3(s3))
        line = wd.get_mcp_mutations_digest_line("2026-08-02", "2026-08-03")
        # 1 + 2 = 3 objects total; save_insight seen twice
        assert line.startswith("3 MCP mutations this week")
        assert "save_insight (2)" in line

    def test_a_single_mutation_is_not_pluralised(self, monkeypatch):
        s3 = FakeS3({"mcp-audit/2026/08/02/": ["mcp-audit/2026/08/02/120000-save_insight-ab12cd34.json"]})
        monkeypatch.setattr(wd, "boto3", FakeBoto3(s3))
        assert wd.get_mcp_mutations_digest_line("2026-08-02", "2026-08-02") == "1 MCP mutation this week (top tools: save_insight (1))"

    def test_a_quiet_week_states_zero_rather_than_omitting_the_line(self, monkeypatch):
        monkeypatch.setattr(wd, "boto3", FakeBoto3(FakeS3({})))
        assert wd.get_mcp_mutations_digest_line("2026-08-02", "2026-08-03") == "0 MCP mutations this week"

    def test_a_hyphenated_tool_name_is_reassembled_from_the_key(self, monkeypatch):
        s3 = FakeS3({"mcp-audit/2026/08/02/": ["mcp-audit/2026/08/02/120000-manage-reading-ab12cd34.json"]})
        monkeypatch.setattr(wd, "boto3", FakeBoto3(s3))
        assert "manage-reading (1)" in wd.get_mcp_mutations_digest_line("2026-08-02", "2026-08-02")

    def test_a_broken_audit_trail_omits_the_line_instead_of_breaking_the_digest(self, monkeypatch):
        monkeypatch.setattr(wd, "boto3", FakeBoto3(FakeS3(error=RuntimeError("access denied"))))
        assert wd.get_mcp_mutations_digest_line("2026-08-02", "2026-08-03") is None


# ══════════════════════════════════════════════════════════════════════════════
# gather_all — the query windows
# ══════════════════════════════════════════════════════════════════════════════


class TestGatherAll:
    def test_no_profile_aborts_the_gather_rather_than_shipping_default_targets(self, table):
        assert wd.gather_all() == (None, None)

    def test_this_week_is_the_seven_complete_days_ending_yesterday(self, table, monkeypatch):
        monkeypatch.setattr(wd, "boto3", FakeBoto3(FakeS3({})))
        table.add(profile_row())
        data, _profile = wd.gather_all()
        assert data["dates"] == {"this_start": W1_START, "this_end": W1_END, "prior_start": W2_START, "prior_end": W2_END}
        start = datetime.strptime(W1_START, "%Y-%m-%d").date()
        end = datetime.strptime(W1_END, "%Y-%m-%d").date()
        assert (end - start).days + 1 == 7

    def test_every_source_the_extractors_consume_is_actually_queried(self, table, monkeypatch):
        """DERIVED from the keys `gather_all` indexes out of raw_this — a source
        added to one list and not the other is a KeyError in production."""
        monkeypatch.setattr(wd, "boto3", FakeBoto3(FakeS3({})))
        table.add(profile_row())
        wd.gather_all()
        queried = {q["ExpressionAttributeValues"][":pk"] for q in table.queries if ":pk" in (q.get("ExpressionAttributeValues") or {})}
        for src in ("whoop", "strava", "apple_health", "macrofactor", "withings", "habitify", "todoist", "day_grade", "hevy"):
            assert f"USER#matthew#SOURCE#{src}" in queried, f"{src} never queried"

    def test_every_read_carries_the_phase_filter(self, table, monkeypatch):
        """ADR-058 default-deny: a prior cycle's rows must not leak into a week."""
        monkeypatch.setattr(wd, "boto3", FakeBoto3(FakeS3({})))
        table.add(profile_row())
        wd.gather_all()
        ranged = [q for q in table.queries if ":s" in (q.get("ExpressionAttributeValues") or {})]
        assert ranged
        assert all(PHASE_FILTER_EXPRESSION in (q.get("FilterExpression") or "") for q in ranged)

    def test_the_extracted_week_only_contains_days_inside_the_window(self, table, monkeypatch):
        monkeypatch.setattr(wd, "boto3", FakeBoto3(FakeS3({})))
        table.add(profile_row())
        for d in (W2_END, W1_START, W1_END):
            table.add(rec("whoop", d, hrv=Decimal("50"), recovery_score=Decimal("60")))
        data, _ = wd.gather_all()
        # W1_START and W1_END are inside this week; W2_END belongs to the prior week
        assert data["this"]["whoop"]["days"] == 2
        assert data["prior"]["whoop"]["days"] == 1

    def test_a_genesis_week_with_no_data_still_returns_a_renderable_payload(self, table, monkeypatch):
        monkeypatch.setattr(wd, "boto3", FakeBoto3(FakeS3({})))
        table.add(profile_row())
        data, profile = wd.gather_all()
        assert profile["goal_weight_lbs"] == 185
        assert data["this"]["withings"] is None
        assert data["training_load"] == {"ctl": 0.0, "atl": 0.0, "tsb": 0.0}
        assert data["projection"] is None
        # must not raise — the reset-morning DLQ crash class
        wd.build_html(data, BOARD_TEXT, profile)

    @pytest.mark.xfail(
        strict=False,
        reason=(
            "DEFECT (tranche-3, P3 — cost/latency): weekly_digest_lambda.py:951 already pulls "
            "four weeks of every source in one paginated query per source, then :998 evaluates "
            "a dict comprehension whose result is DISCARDED (a dead statement, one more "
            "day_grade query) and :1001-1003 re-issues the identical four-week query for all "
            "ten sources a second time to build `full_data`. Every source is therefore read at "
            "least twice per run, and day_grade four times (here, the dead line, and again in "
            "lambda_handler:2120). Hurts: nothing the reader sees — pure RCU and cold-start "
            "latency on a Lambda that already runs close to its timeout."
        ),
    )
    def test_each_source_is_read_once_per_run(self, table, monkeypatch):
        monkeypatch.setattr(wd, "boto3", FakeBoto3(FakeS3({})))
        table.add(profile_row())
        wd.gather_all()
        pks = [q["ExpressionAttributeValues"][":pk"] for q in table.queries if ":s" in (q.get("ExpressionAttributeValues") or {})]
        assert pks.count("USER#matthew#SOURCE#whoop") == 1


# ══════════════════════════════════════════════════════════════════════════════
# The Board prompt
# ══════════════════════════════════════════════════════════════════════════════


class TestCallHaiku:
    @pytest.fixture(autouse=True)
    def _no_network(self, monkeypatch):
        self.captured = {}

        def fake_call(req, **kwargs):
            self.captured["req"] = req
            return {"content": [{"text": BOARD_TEXT}]}

        monkeypatch.setattr(wd, "call_anthropic_with_retry", fake_call)
        monkeypatch.setattr(wd, "_presence_block", lambda: "")
        monkeypatch.setattr(wd, "_HAS_INSIGHT_WRITER", False)

    def _prompt(self):
        import json as _json

        return _json.loads(self.captured["req"].data.decode())["messages"][0]["content"]

    def test_the_board_is_given_every_day_grade_with_its_letter(self):
        data = digest_data(
            this={
                "day_grades": {
                    "days": [{"date": "2026-08-02", "score": 82, "grade": "B+"}],
                    "avg_score": 82.0,
                    "days_graded": 1,
                }
            }
        )
        wd.call_haiku(data, profile_row())
        prompt = self._prompt()
        assert "2026-08-02: 82 (B+)" in prompt
        assert "Weekly avg: 82.0" in prompt

    def test_a_week_with_no_grades_says_so_rather_than_showing_an_empty_table(self):
        wd.call_haiku(digest_data(), profile_row())
        assert "No day grade data available." in self._prompt()

    def test_the_journey_stage_is_derived_from_the_profile_not_hardcoded(self):
        wd.call_haiku(digest_data(), profile_row(journey_start_date="2026-08-03"))
        prompt = self._prompt()
        # 2026-08-03 → 2026-08-09 inclusive = 7 days in → week 1
        assert "JOURNEY STAGE: Week 1 (7 days in)" in prompt
        assert "Foundation Stage" in prompt

    def test_a_long_running_journey_advances_past_the_foundation_stage(self):
        wd.call_haiku(digest_data(), profile_row(journey_start_date="2026-01-01"))
        # 2026-01-01 → 2026-08-09 = 220 days in → week (220+6)//7 = 32 → Advanced
        assert "Advanced Stage" in self._prompt()

    def test_the_momentum_stage_covers_weeks_five_through_twelve(self):
        # start 2026-07-01 → 2026-08-09 = 40 days in → week (40+6)//7 = 6
        wd.call_haiku(digest_data(), profile_row(journey_start_date="2026-07-01"))
        assert "Momentum Stage" in self._prompt()

    def test_the_building_stage_covers_weeks_thirteen_through_twenty_six(self):
        # start 2026-05-01 → 2026-08-09 = 101 days in → week (101+6)//7 = 15
        wd.call_haiku(digest_data(), profile_row(journey_start_date="2026-05-01"))
        assert "Building Stage" in self._prompt()

    def test_an_unparseable_journey_start_falls_back_to_a_week_one_framing(self):
        wd.call_haiku(digest_data(), profile_row(journey_start_date="not-a-date"))
        assert "JOURNEY STAGE: Week 1 of transformation" in self._prompt()

    def test_previously_saved_insights_are_carried_into_the_prompt(self, monkeypatch):
        writer = FakeInsightWriter(context="PREVIOUS INSIGHTS: protect the 10pm boundary.")
        monkeypatch.setattr(wd, "insight_writer", writer, raising=False)
        monkeypatch.setattr(wd, "_HAS_INSIGHT_WRITER", True)
        wd.call_haiku(digest_data(), profile_row())
        assert "protect the 10pm boundary" in self._prompt()

    def test_a_failed_insight_context_read_does_not_stop_the_board_call(self, monkeypatch):
        class Broken:
            def build_insights_context(self, **kwargs):
                raise RuntimeError("ledger down")

        monkeypatch.setattr(wd, "insight_writer", Broken(), raising=False)
        monkeypatch.setattr(wd, "_HAS_INSIGHT_WRITER", True)
        assert wd.call_haiku(digest_data(), profile_row()) == BOARD_TEXT

    def test_the_activity_list_is_trimmed_for_token_economy(self):
        acts = [{"date": "2026-08-02", "name": f"a{i}", "miles": 1, "elev": 1, "hr": None, "mins": 10, "kj": 0} for i in range(9)]
        data = digest_data(this={"strava": {"activities": acts, "activity_count": 9}})
        wd.call_haiku(data, profile_row())
        prompt = self._prompt()
        assert '"a4"' in prompt
        assert '"a5"' not in prompt

    def test_the_baseline_weight_in_the_prompt_comes_from_the_experiment_constant(self):
        wd.call_haiku(digest_data(), profile_row())
        prompt = self._prompt()
        start = int(round(EXPERIMENT_BASELINE_WEIGHT_LBS))
        assert f"lose ~{start - 185} lbs ({start}→185)" in prompt

    def test_a_presence_gap_is_injected_so_the_board_does_not_narrate_over_silence(self, monkeypatch):
        monkeypatch.setattr(wd, "_presence_block", lambda: "PRESENCE: 4 quiet days this week.")
        wd.call_haiku(digest_data(), profile_row())
        assert "PRESENCE: 4 quiet days this week." in self._prompt()

    def test_decimals_from_dynamodb_survive_serialisation_into_the_prompt(self):
        data = digest_data(this={"withings": {"weight_latest": Decimal("303.5")}})
        wd.call_haiku(data, profile_row())
        assert "303.5" in self._prompt()


class TestPresenceBlock:
    def test_a_missing_engagement_state_degrades_to_no_block(self, table):
        assert wd._presence_block() == ""

    def test_a_failed_engagement_read_never_breaks_the_digest(self, table):
        table.get_error = RuntimeError("ddb down")
        assert wd._presence_block() == ""


# ══════════════════════════════════════════════════════════════════════════════
# build_html — what the reader actually sees
# ══════════════════════════════════════════════════════════════════════════════


class TestBuildHtmlSections:
    def test_a_week_with_no_data_renders_no_empty_sections(self):
        html = wd.build_html(digest_data(), BOARD_TEXT, profile_row())
        for title in ("Training</h2>", "Recovery &amp; HRV", "Nutrition</h2>", "Weight &amp; Body Composition"):
            assert title not in html
        # the Board and the load model always render
        assert "Board of Advisors" in html
        assert "Training Load — Banister" in html

    def test_the_board_sections_and_the_pattern_block_are_split_apart(self):
        html = wd.build_html(digest_data(), BOARD_TEXT, profile_row())
        assert "DR. SARAH CHEN" in html
        assert "PATTERN OF THE WEEK" in html
        # the pattern block gets the amber insight card, the advisors do not
        assert "#92400e" in html

    def test_the_week_label_is_rendered_from_the_window_dates(self):
        html = wd.build_html(digest_data(), BOARD_TEXT, profile_row())
        assert "Aug 2 → Aug 8, 2026" in html

    def test_the_medical_disclaimer_is_always_present(self):
        html = wd.build_html(digest_data(), BOARD_TEXT, profile_row())
        assert "not medical advice" in html

    def test_the_training_load_bands_label_a_positive_balance_as_fresh(self):
        html = wd.build_html(digest_data(training_load={"ctl": 40.0, "atl": 30.0, "tsb": 10.0}), BOARD_TEXT, profile_row())
        assert "10.0 (Fresh)" in html

    def test_a_deeply_negative_training_balance_is_labelled_very_fatigued(self):
        html = wd.build_html(digest_data(training_load={"ctl": 40.0, "atl": 70.0, "tsb": -30.0}), BOARD_TEXT, profile_row())
        assert "Very Fatigued" in html

    def test_an_acwr_alert_surfaces_its_reason_to_the_reader(self):
        data = digest_data(acwr_data={"acwr": 1.7, "zone": "danger", "alert": True, "alert_reason": "acute load spike"})
        html = wd.build_html(data, BOARD_TEXT, profile_row())
        assert "1.7 — DANGER" in html
        assert "acute load spike" in html

    def test_no_acwr_record_simply_omits_the_row(self):
        html = wd.build_html(digest_data(), BOARD_TEXT, profile_row())
        assert "ACWR — Training Load" not in html

    def test_the_open_insights_box_counts_what_it_lists(self):
        data = digest_data(
            open_insights=[
                {"text": "walk after dinner", "date_saved": "2026-07-01", "days_open": 39, "tags": []},
                {"text": "cut late caffeine", "date_saved": "2026-07-10", "days_open": 30, "tags": []},
            ]
        )
        html = wd.build_html(data, BOARD_TEXT, profile_row())
        assert "2 Open Insights" in html
        assert "walk after dinner" in html and "cut late caffeine" in html

    def test_the_mcp_audit_line_renders_only_when_there_is_one(self):
        assert "MCP audit" not in wd.build_html(digest_data(), BOARD_TEXT, profile_row())
        html = wd.build_html(digest_data(mcp_mutations_line="3 MCP mutations this week"), BOARD_TEXT, profile_row())
        assert "3 MCP mutations this week" in html

    def test_journey_progress_is_derived_from_the_profiles_start_and_goal(self):
        data = digest_data(this={"withings": {"weight_latest": 301.6, "weight_min": 301.6, "weight_max": 305.0}})
        html = wd.build_html(data, BOARD_TEXT, profile_row(journey_start_weight_lbs=321.6, goal_weight_lbs=185))
        # lost = 321.6 - 301.6 = 20.0 ; span = 321.6 - 185 = 136.6 ; 20/136.6 = 14.6% → 15
        # to go = 301.6 - 185 = 116.6
        assert "20.0 lbs lost · 15% · 116.6 lbs to go" in html

    def test_a_projection_that_is_not_losing_says_so_plainly(self):
        html = wd.build_html(
            digest_data(this={"withings": {"weight_latest": 305.0}}, projection={"status": "not_losing"}),
            BOARD_TEXT,
            profile_row(),
        )
        assert "Weight flat or trending up" in html

    def test_the_character_sheet_renders_its_level_tier_and_pillar_ladder(self):
        cs = {
            "character_level_end": 12,
            "character_level_delta": 2,
            "character_tier": "Foundation",
            "character_tier_emoji": "🔨",
            "character_xp": 1250,
            "pillar_summary": {p: {"end_level": 5, "level_delta": 1, "tier": "Foundation", "avg_raw": 55.0} for p in ("sleep", "movement")},
            "events": [{"type": "pillar_level_up", "pillar": "sleep", "old_level": 4, "new_level": 5}],
            "closest_to_tier": {"pillar": "movement", "levels_needed": 3, "next_tier": "Momentum"},
        }
        html = wd.build_html(digest_data(character_sheet=cs), BOARD_TEXT, profile_row())
        assert "Level 12" in html and "(+2)" in html
        assert "1,250 XP" in html
        assert "Sleep Lv4 → 5" in html
        assert "is 3 levels from Momentum tier" in html

    def test_no_character_record_omits_the_section_entirely(self):
        assert "Character Sheet" not in wd.build_html(digest_data(), BOARD_TEXT, profile_row())

    def test_a_losing_week_on_the_character_sheet_renders_the_negative_delta(self):
        cs = {
            "character_level_end": 8,
            "character_level_delta": -2,
            "character_tier": "Momentum",
            "character_tier_emoji": "🔥",
            "character_xp": 400,
            "pillar_summary": {"sleep": {"end_level": 5, "level_delta": -1, "tier": "Foundation", "avg_raw": None}},
            "events": [{"type": "pillar_tier_down", "pillar": "sleep", "old_tier": "Momentum", "new_tier": "Foundation"}],
            "closest_to_tier": None,
        }
        html = wd.build_html(digest_data(character_sheet=cs), BOARD_TEXT, profile_row())
        assert "(-2)" in html
        assert "Sleep: Momentum → Foundation" in html

    def test_a_character_level_event_is_labelled_as_a_character_level_change(self):
        cs = {
            "character_level_end": 9,
            "character_level_delta": 1,
            "character_tier": "Foundation",
            "character_tier_emoji": "🔨",
            "character_xp": 0,
            "pillar_summary": {},
            "events": [{"type": "character_level_up", "old_level": 8, "new_level": 9}],
            "closest_to_tier": None,
        }
        html = wd.build_html(digest_data(character_sheet=cs), BOARD_TEXT, profile_row())
        assert "Character Level 8 → 9" in html

    def test_a_malformed_window_date_falls_back_to_the_raw_strings(self):
        data = digest_data()
        data["dates"] = {"this_start": "not-a-date", "this_end": W1_END, "prior_start": W2_START, "prior_end": W2_END}
        assert "not-a-date → 2026-08-08" in wd.build_html(data, BOARD_TEXT, profile_row())

    def test_the_sleep_section_renders_architecture_rows_when_they_are_measured(self):
        sleep = {"score_avg": 82.0, "score_min": 61.0, "duration_avg_hrs": 7.1, "efficiency_avg": 88.0, "deep_pct": 17.0, "rem_pct": 22.0}
        html = wd.build_html(digest_data(this={"sleep": sleep}), BOARD_TEXT, profile_row())
        assert "88.0%" in html and "(target 15-20%)" in html and "(target 20-25%)" in html

    def test_an_unmeasured_sleep_architecture_omits_its_rows_rather_than_printing_zero(self):
        sleep = {"score_avg": 82.0, "score_min": 61.0, "duration_avg_hrs": 7.1, "efficiency_avg": None, "deep_pct": None, "rem_pct": None}
        html = wd.build_html(digest_data(this={"sleep": sleep}), BOARD_TEXT, profile_row())
        for label in ("Deep %", "REM %", "Efficiency"):
            assert f">{label}</td>" not in html

    def test_the_nutrition_section_renders_the_optional_macro_rows(self):
        m = {
            "calories_avg": 1850.0,
            "protein_avg_g": 150.0,
            "fat_avg_g": 60.0,
            "carbs_avg_g": 150.0,
            "fiber_avg_g": 25.0,
            "calorie_target": 1800,
            "protein_target": 190,
            "calorie_hit_rate": 50,
            "protein_hit_rate": 50,
            "days_logged": 2,
        }
        html = wd.build_html(digest_data(this={"macrofactor": m}), BOARD_TEXT, profile_row())
        assert "Avg Fat" in html and "Avg Carbs" in html and "Avg Fiber" in html
        assert "1850.0 kcal" in html and "(target 1800)" in html

    def test_the_cgm_section_colours_glucose_and_time_in_range(self):
        apple = {"glucose_avg": 96.0, "glucose_tir_avg": 94.0, "glucose_days": 6, "gait_speed_avg": 3.2, "gait_days": 5}
        html = wd.build_html(digest_data(this={"apple": apple}), BOARD_TEXT, profile_row())
        assert "96.0 mg/dL" in html and "94.0%" in html
        assert "Days w/ CGM Data" in html
        assert "3.2 mph" in html and "(5 days)" in html

    def test_the_journal_section_renders_mood_themes_and_a_quote(self):
        journal = {
            "mood_avg": 3.5,
            "energy_avg": 3.0,
            "stress_avg": 2.5,
            "entries": 5,
            "days_journaled": 4,
            "top_themes": [("work", 3), ("sleep", 2)],
            "avoidance_flags": ["scrolling"],
            "notable_quotes": [{"date": "2026-08-04", "quote": "I chose the walk."}],
        }
        html = wd.build_html(digest_data(this={"journal": journal}, prior={"journal": {"mood_avg": 3.0}}), BOARD_TEXT, profile_row())
        assert "3.5/5" in html
        assert "5 across 4 days" in html
        assert "work (3)" in html
        assert "scrolling" in html
        assert "I chose the walk." in html

    def test_the_productivity_section_renders_the_task_counts(self):
        html = wd.build_html(
            digest_data(this={"todoist": {"tasks_completed": 21, "avg_per_day": 3.0, "days": 7}}), BOARD_TEXT, profile_row()
        )
        assert "Tasks Completed" in html and ">21<" in html
        assert "Avg Per Day" in html

    def test_a_healthy_projection_names_the_rate_and_the_eta(self):
        data = digest_data(
            this={"withings": {"weight_latest": 303.5, "weight_min": 303.0, "weight_max": 306.0, "body_fat_avg": 34.5}},
            projection={"status": "ok", "weeks": 8, "rate_per_week": 2.0, "eta": "September 2026"},
        )
        html = wd.build_html(data, BOARD_TEXT, profile_row())
        assert "2.0 lbs/wk → goal ~September 2026 (8 weeks)" in html
        assert "Body Fat %" in html

    def test_the_training_section_lists_activities_and_flags_high_monotony(self):
        strava = {
            "activity_count": 1,
            "total_minutes": 60,
            "total_miles": 3.0,
            "total_elevation_feet": 120,
            "zone2_minutes": 60,
            "zone2_target": 150,
            "zone2_pct": 100,
            "zone2_hr_range": "112-130",
            "training_monotony": 2.4,
            "activities": [{"date": "2026-08-02", "name": "Morning Walk", "miles": 3.0, "elev": 120, "hr": 120, "mins": 60, "kj": 0}],
        }
        html = wd.build_html(digest_data(this={"strava": strava}), BOARD_TEXT, profile_row())
        assert "plateau risk" in html
        assert "Morning Walk" in html and "120 bpm" in html


class TestBuildHtmlNumbers:
    def test_the_headline_grade_renders_the_average_and_the_range(self):
        dg = {
            "days": [{"date": "2026-08-02", "score": 90, "grade": "A"}, {"date": "2026-08-03", "score": 70, "grade": "B-"}],
            "avg_score": 80.0,
            "min_score": 70.0,
            "max_score": 90.0,
            "grade_counts": {"A": 1, "B": 1},
            "days_graded": 2,
        }
        html = wd.build_html(digest_data(this={"day_grades": dg}), BOARD_TEXT, profile_row())
        assert ">80 <span" in html
        assert "Range: 70.0–90.0" in html
        assert "2 days graded" in html

    @pytest.mark.xfail(
        strict=False,
        reason=(
            "DEFECT (tranche-3, P2 — the number and the letter beside it disagree): "
            "weekly_digest_lambda.py:1362-1383 `from_letter` is a private re-implementation of "
            "scoring_engine.letter_grade and is applied to the UNROUNDED weekly average, while "
            ":1423 prints `round(dg_avg)` next to it. A week averaging 84.6 renders "
            "'85 B+' — because from_letter(84.6) = 'B+' but the platform's own "
            "letter_grade(85) = 'A-'. The mismatched letter also picks the colour "
            "(grade_colour), so the headline is painted blue instead of green. Hurts: the one "
            "number at the top of the email contradicts the letter printed on it, and "
            "contradicts what /cockpit shows for the same week."
        ),
    )
    def test_the_headline_letter_matches_the_headline_number(self):
        dg = {
            "days": [{"date": "2026-08-02", "score": 85, "grade": "A-"}],
            "avg_score": 84.6,
            "min_score": 84.6,
            "max_score": 84.6,
            "grade_counts": {"A": 1},
            "days_graded": 1,
        }
        html = wd.build_html(digest_data(this={"day_grades": dg}), BOARD_TEXT, profile_row())
        shown = re.search(r'line-height:1;">(\d+) <span style="font-size:16px;">([A-F][+-]?)</span>', html)
        assert shown, "headline grade block not found"
        score, letter = int(shown.group(1)), shown.group(2)
        assert letter == scoring_engine.letter_grade(score)

    def test_the_scorecard_prefers_the_stored_component_score_over_the_raw_source(self):
        dg = {
            "days": [{"date": "2026-08-02", "score": 80, "grade": "B+"}],
            "avg_score": 80.0,
            "min_score": 80,
            "max_score": 80,
            "days_graded": 1,
        }
        data = digest_data(this={"day_grades": dg, "sleep": {"score_avg": 40.0}})
        data["_raw_grades"] = {"2026-08-02": {"component_sleep_quality": Decimal("88")}}
        html = wd.build_html(data, BOARD_TEXT, profile_row())
        assert scorecard_value(html, "Sleep") == "88"

    def test_an_unmeasured_component_renders_an_em_dash_not_a_zero(self):
        html = wd.build_html(digest_data(), BOARD_TEXT, profile_row())
        for label in ("Nutrition", "Movement", "Water", "Journal", "Glucose"):
            assert scorecard_value(html, label) == "—"

    @pytest.mark.xfail(
        strict=False,
        reason=(
            "DEFECT (tranche-3, P1 — ADR-104 falsy-fallback): weekly_digest_lambda.py:1574-1578 "
            "uses `comp_avgs.get(x) or <fallback>` for Sleep, Recovery and Habits. A component "
            "average of exactly 0.0 — a real, measured, catastrophic week — is falsy, so the "
            "cell silently falls through to a DIFFERENT measurement (the raw Whoop/Habitify "
            "aggregate), which is computed over a different denominator and is usually "
            "non-zero. The reader is shown a healthy-looking number for the worst week the "
            "scoring engine can record. Correct: `if comp_avgs.get(x) is not None`. Hurts: the "
            "single worst week is the one the scorecard misreports."
        ),
    )
    def test_a_genuinely_zero_component_average_is_shown_as_zero(self):
        dg = {
            "days": [{"date": "2026-08-02", "score": 10, "grade": "F"}],
            "avg_score": 10.0,
            "min_score": 10,
            "max_score": 10,
            "days_graded": 1,
        }
        data = digest_data(this={"day_grades": dg, "habitify": {"mvp_avg_pct": 71.4, "days_tracked": 7, "mvp_completion": {}}})
        data["_raw_grades"] = {"2026-08-02": {"component_habits_mvp": Decimal("0")}}
        html = wd.build_html(data, BOARD_TEXT, profile_row())
        assert scorecard_value(html, "Habits") == "0"

    def test_the_zone_two_row_states_the_target_and_the_band(self):
        strava = {
            "activity_count": 3,
            "total_minutes": 180,
            "total_miles": 6.0,
            "total_elevation_feet": 300,
            "zone2_minutes": 120,
            "zone2_target": 150,
            "zone2_pct": 67,
            "zone2_hr_range": "112-130",
            "training_monotony": None,
            "activities": [],
        }
        html = wd.build_html(digest_data(this={"strava": strava}), BOARD_TEXT, profile_row())
        assert "Zone 2 (112-130 bpm)" in html
        assert "120 / 150 min (67% of cardio)" in html

    def test_the_strength_section_reports_volume_and_set_count(self):
        mfw = {
            "workout_count": 2,
            "total_volume_lbs": 24500,
            "total_sets": 42,
            "workouts": [{"date": "2026-08-04", "name": "Push A", "exercises": 5, "volume_lbs": 12000}],
            "best_workout": None,
        }
        html = wd.build_html(digest_data(this={"mf_workouts": mfw}), BOARD_TEXT, profile_row())
        assert "24,500 lbs, 42 sets" in html
        assert "Push A" in html

    def test_the_habits_section_lists_each_mvp_habit_with_its_own_rate(self):
        hab = {
            "mvp_avg_pct": 75.0,
            "overall_avg_pct": 80.0,
            "mvp_completion": {"Sleep 7h": 6, "Walk 8k": 3},
            "mvp_total": 4,
            "days_tracked": 7,
        }
        html = wd.build_html(digest_data(this={"habitify": hab}), BOARD_TEXT, profile_row(mvp_habits=["Sleep 7h", "Walk 8k"]))
        # 6/7 = 85.7% → round → 86 ; 3/7 = 42.9% → round → 43
        assert "6/7 (86%)" in html
        assert "3/7 (43%)" in html

    def test_a_long_habit_name_is_truncated_rather_than_breaking_the_table(self):
        name = "Do the very long thing every single morning without fail"
        hab = {"mvp_avg_pct": 100.0, "mvp_completion": {name: 7}, "mvp_total": 1, "days_tracked": 7}
        html = wd.build_html(digest_data(this={"habitify": hab}), BOARD_TEXT, profile_row(mvp_habits=[name]))
        assert name[:30] + "..." in html
        assert name not in html

    @pytest.mark.xfail(
        strict=False,
        reason=(
            "DEFECT (tranche-3, P2 — a lower bound printed as an exact count): "
            "weekly_digest_lambda.py:1755-1769 renders '⭐ Essential Seven — Perfect Days: "
            "N/M days' where N is `min(per-habit completion counts)`. The code's own comment "
            "concedes it is 'at least this many days' — min-of-counts is a lower bound on the "
            "number of days where ALL habits were done, not that number. Two habits each done "
            "5 of 7 days on DISJOINT days yields 0 perfect days but renders 5/7 with a green "
            "bar. `ex_habitify` already walks the per-day habit maps (:428-443) and could "
            "count perfect days exactly. Hurts: Matthew's flagship consistency metric is "
            "systematically overstated, and never understated, so the error only ever "
            "flatters."
        ),
    )
    def test_perfect_days_counts_days_on_which_every_habit_was_done(self):
        # Two habits, each completed on 1 of 2 tracked days, on DIFFERENT days →
        # zero days had both done.
        hab = {"mvp_avg_pct": 50.0, "mvp_completion": {"a": 1, "b": 1}, "mvp_total": 2, "days_tracked": 2}
        html = wd.build_html(digest_data(this={"habitify": hab}), BOARD_TEXT, profile_row(mvp_habits=["a", "b"]))
        assert "0/2 days" in html

    @pytest.mark.xfail(
        strict=False,
        reason=(
            "DEFECT (tranche-3, P2 — window-name honesty, #1917): weekly_digest_lambda.py:1739 "
            "renders the row '7-Day Sleep Debt' but compute_sleep_debt (:720) accrues the "
            "target only over the nights that HAVE a duration — `target × len(durs)`. Three "
            "nights at exactly 7.5 h and four nights with no strap render '7-Day Sleep Debt: "
            "0.0 hrs' in green. The returned dict already carries `nights`, and the renderer "
            "drops it. Hurts: four unmeasured nights are published as a debt-free week."
        ),
    )
    def test_a_sleep_debt_row_discloses_how_many_nights_it_covers(self):
        sd = {"debt_hrs": 0.0, "nights": 3, "avg_hrs": 7.5, "target_hrs": 7.5}
        html = wd.build_html(digest_data(this={"sleep": {"score_avg": 80.0}}, sleep_debt=sd), BOARD_TEXT, profile_row())
        assert "3 nights" in html or "3 of 7" in html

    def test_the_component_set_matches_the_scoring_engines_registry(self):
        """DERIVED, per the guard-the-SET rule: a ninth day-grade component would
        otherwise be silently absent from the weekly scorecard."""
        (components,) = [t for t in _nested_str_tuples(wd.build_html.__code__) if "sleep_quality" in t]
        assert list(components) == list(scoring_engine.COMPONENT_SCORERS)


class TestBuildHtmlPrivacy:
    def test_the_delivery_free_streak_is_never_rendered_in_the_digest(self, table, delivery_public):
        """Pins today's behaviour: `get_food_delivery_digest_line` exists and
        returns a line, but nothing calls it — see the xfail below.

        #2233 gates `get_food_delivery_digest_line` behind NUTRITION_DELIVERY_PUBLIC
        (default off); the `delivery_public` fixture turns the flag on so this test's
        own point (the line exists but nothing calls it) is exercised rather than
        short-circuited by an unrelated disclosure default.
        `test_no_binge_or_delivery_spend_figure_reaches_the_rendered_digest` below is
        the dedicated flag-off guard.
        """
        table.add(
            {
                "pk": "USER#matthew#SOURCE#food_delivery",
                "sk": "STREAK#current",
                "streak_days": 31,
                "updated_at": FROZEN_NOW.isoformat(),  # #2235: fresh
            }
        )
        assert wd.get_food_delivery_digest_line() == "Delivery-free streak: 31 days (nutrition bonus 1.10x active)"
        m = {"calories_avg": 1800.0, "protein_avg_g": 190.0, "calorie_target": 1800, "protein_target": 190, "days_logged": 7}
        html = wd.build_html(digest_data(this={"macrofactor": m}), BOARD_TEXT, profile_row())
        assert "Delivery-free streak" not in html

    def test_no_binge_or_delivery_spend_figure_reaches_the_rendered_digest(self, table):
        """Privacy regression guard: the delivery/binge signals are owner-only
        (NUTRITION_DELIVERY_PUBLIC off) and must not appear even here by name."""
        html = wd.build_html(digest_data(), BOARD_TEXT, profile_row())
        for token in ("binge", "delivery_spend", "doordash", "ubereats"):
            assert token.lower() not in html.lower()


class TestFoodDeliveryDigestLine:
    # #2233 gates these functions behind NUTRITION_DELIVERY_PUBLIC (default off);
    # that disclosure question has its own dedicated coverage in
    # tests/test_food_delivery_gate_2233.py. This class is about the #2235
    # freshness/formatting logic, so each test takes main's `delivery_public`
    # fixture (023874f0) to exercise it independent of disclosure defaults.
    def test_no_streak_record_yields_no_line(self, table, delivery_public):
        assert wd.get_food_delivery_digest_line() is None

    def test_a_zero_day_streak_is_absence_rather_than_a_zero_line(self, table, delivery_public):
        # Keeps main's `delivery_public` gating fixture (023874f0) AND #2235's fresh
        # `updated_at`: without the timestamp the read would return None for a
        # STALENESS reason and this test would pass vacuously, asserting nothing
        # about the zero-day case it is named for.
        table.add(
            {
                "pk": "USER#matthew#SOURCE#food_delivery",
                "sk": "STREAK#current",
                "streak_days": 0,
                "updated_at": FROZEN_NOW.isoformat(),
            }
        )
        assert wd.get_food_delivery_digest_line() is None

    def test_each_bonus_band_is_named_at_its_threshold(self, table, delivery_public):
        for days, marker in ((7, "1.02x"), (14, "1.05x"), (30, "1.10x")):
            table.add(
                {
                    "pk": "USER#matthew#SOURCE#food_delivery",
                    "sk": "STREAK#current",
                    "streak_days": days,
                    "updated_at": FROZEN_NOW.isoformat(),
                }
            )
            assert marker in wd.get_food_delivery_digest_line()

    def test_a_failed_read_yields_no_line_rather_than_an_exception(self, table, delivery_public):
        table.get_error = RuntimeError("ddb down")
        assert wd.get_food_delivery_digest_line() is None

    @pytest.mark.xfail(
        strict=False,
        reason=(
            "DEFECT (tranche-3, P2 — a shipped feature that is dead code): "
            "weekly_digest_lambda.py:2050 `get_food_delivery_digest_line` documents itself as "
            "'Returns a one-line summary for the weekly digest nutrition section', but a "
            "repo-wide grep finds no caller — not build_html, not lambda_handler, not any "
            "test. The delivery-free streak (which the character engine already treats as a "
            "nutrition multiplier, character_sheet_lambda.py:653) is never reported back to "
            "Matthew in the weekly email. Hurts: the behaviour-change loop this streak exists "
            "to reinforce has no weekly readout, and the function is carried, deployed and "
            "maintained for nothing."
        ),
    )
    def test_the_streak_line_reaches_the_nutrition_section_it_is_written_for(self, table, delivery_public):
        table.add(
            {
                "pk": "USER#matthew#SOURCE#food_delivery",
                "sk": "STREAK#current",
                "streak_days": 31,
                "updated_at": FROZEN_NOW.isoformat(),
            }
        )
        m = {"calories_avg": 1800.0, "protein_avg_g": 190.0, "calorie_target": 1800, "protein_target": 190, "days_logged": 7}
        html = wd.build_html(digest_data(this={"macrofactor": m}), BOARD_TEXT, profile_row())
        assert "Delivery-free streak: 31 days" in html


class TestFoodDeliveryDigestFreshness2235:
    """#2235: the weekly digest reads the SAME frozen-snapshot record as the daily
    brief and the character engine. A record whose `updated_at` is past
    food_delivery's stale_hours threshold (336h = 14 days, source_registry.py) must
    not surface as a live streak here either."""

    # This class is about the #2235 freshness gate, not the #2233 disclosure gate,
    # so every test takes main's module-level `delivery_public` fixture (023874f0)
    # to exercise freshness independent of disclosure defaults.
    def test_a_stale_record_yields_no_line(self, table, delivery_public):
        stale = (FROZEN_NOW - timedelta(hours=337)).isoformat()
        table.add(
            {
                "pk": "USER#matthew#SOURCE#food_delivery",
                "sk": "STREAK#current",
                "streak_days": 40,
                "last_order_date": "2026-01-01",
                "updated_at": stale,
            }
        )
        assert wd.get_food_delivery_digest_line() is None

    def test_a_record_just_inside_the_threshold_still_reports(self, table, delivery_public):
        fresh = (FROZEN_NOW - timedelta(hours=335)).isoformat()
        table.add(
            {
                "pk": "USER#matthew#SOURCE#food_delivery",
                "sk": "STREAK#current",
                "streak_days": 40,
                "last_order_date": "2026-01-01",
                "updated_at": fresh,
            }
        )
        assert "1.10x" in wd.get_food_delivery_digest_line()

    def test_a_record_with_no_updated_at_is_withheld(self, table, delivery_public):
        table.add({"pk": "USER#matthew#SOURCE#food_delivery", "sk": "STREAK#current", "streak_days": 40})
        assert wd.get_food_delivery_digest_line() is None


# ══════════════════════════════════════════════════════════════════════════════
# Handler
# ══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def wired(monkeypatch):
    """A fully-stubbed handler run: no SES, no DDB, no S3, no Bedrock."""
    t = FakeTable()
    t.add(profile_row())
    for i, d in enumerate(W1_DATES):
        t.add(rec("day_grade", d, total_score=Decimal(str(70 + i)), letter_grade="B", component_sleep_quality=Decimal("80")))
        t.add(rec("whoop", d, hrv=Decimal("50"), recovery_score=Decimal("60"), sleep_duration_hours=Decimal("7.0")))
        t.add(rec("withings", d, weight_lbs=Decimal("303.5")))
    t.add(sub_row("SUB#a@x.test", attr_utm_source="rss"))
    s = FakeSes()
    writer = FakeInsightWriter()
    monkeypatch.setattr(wd, "table", t)
    monkeypatch.setattr(wd, "ses", s)
    monkeypatch.setattr(wd, "boto3", FakeBoto3(FakeS3({})))
    monkeypatch.setattr(wd, "insight_writer", writer, raising=False)
    monkeypatch.setattr(wd, "_HAS_INSIGHT_WRITER", True)
    monkeypatch.setattr(wd, "_HAS_AI_VALIDATOR", False)
    monkeypatch.setattr(wd, "call_haiku", lambda data, profile: BOARD_TEXT)
    return {"table": t, "ses": s, "writer": writer}


class TestLambdaHandler:
    def test_a_normal_run_sends_exactly_one_email_to_the_configured_recipient(self, wired):
        out = wd.lambda_handler({}, None)
        assert out["statusCode"] == 200
        assert len(wired["ses"].sent) == 1
        sent = wired["ses"].sent[0]
        assert sent["Destination"]["ToAddresses"] == [wd.RECIPIENT]
        assert sent["FromEmailAddress"] == wd.SENDER

    def test_the_subject_carries_the_window_end_and_the_graded_day_count(self, wired):
        wd.lambda_handler({}, None)
        subject = wired["ses"].sent[0]["Content"]["Simple"]["Subject"]["Data"]
        # scores 70..76 over the 7 window days → mean 73.0 → round → 73
        assert subject == f"Weekly Report · {W1_END} · Grade: 73 (7d)"

    def test_the_subject_and_the_body_headline_quote_the_same_average(self, wired):
        wd.lambda_handler({}, None)
        sent = wired["ses"].sent[0]
        subject = sent["Content"]["Simple"]["Subject"]["Data"]
        html = sent["Content"]["Simple"]["Body"]["Html"]["Data"]
        shown = re.search(r'line-height:1;">(\d+) <span', html)
        assert shown and f"Grade: {shown.group(1)} " in subject

    def test_a_week_with_no_grades_says_em_dash_in_the_subject_not_zero(self, wired):
        wired["table"].items = {k: v for k, v in wired["table"].items.items() if "day_grade" not in k[0]}
        wd.lambda_handler({}, None)
        assert wired["ses"].sent[0]["Content"]["Simple"]["Subject"]["Data"].endswith("Grade: —")

    def test_the_send_is_tagged_for_open_and_bounce_tracking(self, wired):
        wd.lambda_handler({}, None)
        sent = wired["ses"].sent[0]
        assert sent["ConfigurationSetName"] == "life-platform-emails"
        assert sent["EmailTags"] == [{"Name": "message_type", "Value": "weekly_digest"}]

    def test_no_profile_returns_a_failure_without_sending_anything(self, wired):
        wired["table"].items = {}
        out = wd.lambda_handler({}, None)
        assert out["statusCode"] == 500
        assert wired["ses"].sent == []

    def test_a_completion_record_is_written_for_the_status_page(self, wired):
        wd.lambda_handler({}, None)
        logs = [p for p in wired["table"].puts if "email_log" in p["pk"]]
        assert len(logs) == 1
        assert logs[0]["pk"] == f"USER#{wd.USER_ID}#SOURCE#email_log#weekly_digest"
        assert logs[0]["sk"] == f"DATE#{TODAY}"
        assert logs[0]["status"] == "success"

    def test_a_failed_completion_write_does_not_undo_a_successful_send(self, wired, monkeypatch):
        def boom(*_a, **_k):
            raise RuntimeError("ddb down")

        monkeypatch.setattr(wired["table"], "put_item", boom)
        assert wd.lambda_handler({}, None)["statusCode"] == 200
        assert len(wired["ses"].sent) == 1

    def test_the_gate_readout_reaches_the_rendered_email(self, wired):
        wd.lambda_handler({}, None)
        html = wired["ses"].sent[0]["Content"]["Simple"]["Body"]["Html"]["Data"]
        assert "confirmed subscribers (real): <strong>1</strong>" in html
        assert "utm:rss" in html

    def test_a_failed_board_call_still_ships_the_data_sections(self, wired, monkeypatch):
        monkeypatch.setattr(wd, "call_haiku", lambda d, p: (_ for _ in ()).throw(RuntimeError("bedrock 500")))
        wd.lambda_handler({}, None)
        html = wired["ses"].sent[0]["Content"]["Simple"]["Body"]["Html"]["Data"]
        assert "Commentary unavailable" in html
        assert "Recovery &amp; HRV" in html or "Recovery" in html

    def test_a_blocked_ai_output_is_replaced_by_the_validators_fallback(self, wired, monkeypatch):
        class Blocked:
            blocked = True
            block_reason = "unsupported claim"
            safe_fallback = "(Weekly digest coaching temporarily unavailable.)"
            warnings = []

        monkeypatch.setattr(wd, "validate_ai_output", lambda text, kind: Blocked(), raising=False)
        monkeypatch.setattr(wd, "_HAS_AI_VALIDATOR", True)
        wd.lambda_handler({}, None)
        html = wired["ses"].sent[0]["Content"]["Simple"]["Body"]["Html"]["Data"]
        assert "temporarily unavailable" in html
        assert "DR. SARAH CHEN" not in html

    def test_a_genuine_board_commentary_is_filed_into_the_insight_ledger(self, wired):
        wd.lambda_handler({}, None)
        assert len(wired["writer"].written) == 1
        written = wired["writer"].written[0]
        assert written["digest_type"] == "weekly_digest"
        assert written["date"] == W1_END

    def test_a_failed_ledger_write_does_not_fail_the_run(self, wired, monkeypatch):
        def boom(insights):
            raise RuntimeError("ledger down")

        monkeypatch.setattr(wired["writer"], "write_insights_batch", boom)
        assert wd.lambda_handler({}, None)["statusCode"] == 200

    @pytest.mark.xfail(
        strict=False,
        reason=(
            "DEFECT (tranche-3, P2 — an AI-failure stub filed as genuine coaching): "
            "weekly_digest_lambda.py:2173 gates the insight write on `if _HAS_INSIGHT_WRITER "
            "and commentary` only. When call_haiku raises (:2140-2142, which includes the "
            "tier-3 BudgetExceeded path) commentary becomes the canned '🎯 THE CHAIR — "
            "OVERVIEW / Commentary unavailable.' stub, and that stub is written to the ledger "
            "with insight_type='coaching', confidence='high', actionable=True. "
            "insight_writer.build_insights_context then replays it into NEXT week's Board "
            "prompt as PREVIOUS INSIGHTS (:1199). The validator's safe_fallback takes the same "
            "path. Same shape as the tranche-1/tranche-2 findings on daily_brief and "
            "weekly_plate. Hurts: the insight ledger accumulates non-content that is fed back "
            "to the model as if it were last week's coaching."
        ),
    )
    def test_a_failed_board_call_is_not_filed_as_genuine_coaching(self, wired, monkeypatch):
        monkeypatch.setattr(wd, "call_haiku", lambda d, p: (_ for _ in ()).throw(RuntimeError("bedrock 500")))
        wd.lambda_handler({}, None)
        assert wired["writer"].written == []

    def test_a_dry_run_invoke_does_not_send_a_real_email(self, wired):
        """FIXED by #2222 — this handler now honours a dry-run suppressor.

        It was an `xfail` describing a real defect: the handler ignored `event`
        entirely, so there was no safe way to exercise it and every verification
        invoke mailed Matthew and burned a Sonnet call. #2222 put all 17 SES-sending
        handlers behind one derived guard, which made this marker stale — it xpassed,
        i.e. it was still asserting a defect that no longer exists. Flipped to a real
        assertion so it now protects the fix instead of describing the bug."""
        wd.lambda_handler({"dry_run": True}, None)
        assert wired["ses"].sent == []


class TestRecordEmailSend:
    def test_the_completion_record_is_keyed_to_the_configured_user(self, table):
        wd.record_email_send(table, "weekly_digest")
        assert table.puts[0]["pk"].startswith(f"USER#{wd.USER_ID}#SOURCE#email_log#")

    def test_the_record_carries_a_ninety_day_ttl(self, table):
        import time as _time

        wd.record_email_send(table, "weekly_digest")
        ttl = table.puts[0]["ttl"]
        # 90 days = 86400 × 90 = 7,776,000 seconds from now
        assert 7_776_000 - 120 <= ttl - int(_time.time()) <= 7_776_000 + 120
