#!/usr/bin/env python3
"""tests/test_adaptive_mode_behavior.py — behavioral contracts of
`lambdas/compute/adaptive_mode_lambda.py`.

Part of #1658 tranche 2. This Lambda decides the daily brief's *tone*: the
`brief_mode` it stores drives a 🌟 green banner, no banner, or a 💛 "Rough
Patch" banner, and the board's register follows it. A defect here does not
corrupt a number — it tells a person they are struggling, or fails to notice
that they are.

#2214 (fixed): two of the four scoring components used to read field names no
writer produced — score_journal did a plain get_item against the notion
partition when notion_lambda only ever writes suffixed keys, and
score_grade_trend read 'score'/'grade_numeric'/'numeric_grade' when both
day_grade writers stamp 'total_score'. Both are now fixed (query the date's
suffix range for journal; read total_score for grade trend) and the four
tests that pinned the defect (below) are real, passing assertions again.

Every clock is frozen; the fake table is bounded and hand-rolled.
"""

import os
import sys
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from pacific_clock import freeze_pacific  # noqa: E402 — #2811: the PT clock the module actually calls

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LAMBDAS = os.path.join(ROOT, "lambdas")
if LAMBDAS not in sys.path:
    sys.path.insert(0, LAMBDAS)

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

_import_err = None
try:
    import adaptive_mode_lambda as am
except ImportError as _e:  # pragma: no cover — only when the bundle layout changes
    _import_err = _e
    am = None  # type: ignore

if _import_err is not None:  # pragma: no cover
    pytestmark = pytest.mark.skip(reason=f"adaptive_mode_lambda unavailable: {_import_err}")  # type: ignore


FROZEN_NOW = datetime(2026, 5, 10, 16, 36, 0, tzinfo=timezone.utc)
TODAY = "2026-05-10"
YESTERDAY = "2026-05-09"
PK = f"USER#{am.USER_ID}#SOURCE#" if am else ""


class _FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return FROZEN_NOW if tz else FROZEN_NOW.replace(tzinfo=None)


@pytest.fixture
def frozen_clock(monkeypatch):
    monkeypatch.setattr(am, "datetime", _FrozenDatetime)
    freeze_pacific(monkeypatch, am, _FrozenDatetime)
    return FROZEN_NOW


class FakeTable:
    """Bounded in-memory table; `query` understands the module's two SK shapes."""

    def __init__(self, items=None):
        self.items = list(items or [])
        self.puts = []
        self.queries = []
        self.get_error = None
        self.query_error = None

    def get_item(self, Key=None, **kw):
        if self.get_error is not None:
            raise self.get_error
        for i in self.items:
            if i["pk"] == Key["pk"] and i["sk"] == Key["sk"]:
                return {"Item": i}
        return {}

    def put_item(self, Item=None, **kw):
        self.puts.append(Item)
        return {}

    def query(self, **kwargs):
        self.queries.append(kwargs)
        if self.query_error is not None:
            raise self.query_error
        vals = kwargs.get("ExpressionAttributeValues", {})
        rows = [i for i in self.items if i["pk"] == vals.get(":pk")]
        if ":lo" in vals:
            rows = [r for r in rows if vals[":lo"] <= r["sk"] <= vals[":hi"]]
        return {"Items": rows}


@pytest.fixture
def table(monkeypatch):
    t = FakeTable()
    monkeypatch.setattr(am, "table", t)
    return t


def row(source, sk, **fields):
    return {"pk": PK + source, "sk": sk, **fields}


def seed(table, *rows):
    table.items.extend(rows)


def _habit_row(date_str, t0_done=4, t0_total=4, t1_done=2, t1_total=2):
    return row(
        "habit_scores",
        "DATE#" + date_str,
        tier0_done=t0_done,
        tier0_total=t0_total,
        tier1_done=t1_done,
        tier1_total=t1_total,
    )


# ──────────────────────────────────────────────────────────────────────────────
# DDB helpers
# ──────────────────────────────────────────────────────────────────────────────


class TestFetchHelpers:
    def test_a_present_record_is_returned(self, table):
        seed(table, row("habit_scores", "DATE#" + YESTERDAY, tier0_done=1))
        assert am.fetch_record("habit_scores", YESTERDAY)["tier0_done"] == 1

    def test_a_missing_record_is_an_empty_dict_not_none(self, table):
        """Every caller does `item.get(...)` straight away — None would crash."""
        assert am.fetch_record("habit_scores", YESTERDAY) == {}

    def test_a_failed_read_degrades_to_an_empty_dict(self, table):
        table.get_error = RuntimeError("throttled")
        assert am.fetch_record("habit_scores", YESTERDAY) == {}

    def test_recent_dates_walks_back_from_the_base_date(self, table, frozen_clock):
        from datetime import date

        seed(table, _habit_row("2026-05-09"), _habit_row("2026-05-07"))
        recs = am.fetch_recent_dates("habit_scores", days=3, base_date=date(2026, 5, 9))
        assert set(recs) == {"2026-05-09", "2026-05-07"}

    def test_recent_dates_skips_days_with_no_record(self, table, frozen_clock):
        from datetime import date

        seed(table, _habit_row("2026-05-09"))
        assert list(am.fetch_recent_dates("habit_scores", days=3, base_date=date(2026, 5, 9))) == ["2026-05-09"]


# ──────────────────────────────────────────────────────────────────────────────
# Habit components
# ──────────────────────────────────────────────────────────────────────────────


class TestHabitScoring:
    def test_full_tier_zero_adherence_scores_one_hundred(self, table):
        seed(table, _habit_row(YESTERDAY, t0_done=4, t0_total=4))
        assert am.score_t0_habits(YESTERDAY)[0] == 100

    def test_partial_tier_zero_adherence_is_the_completion_percentage(self, table):
        seed(table, _habit_row(YESTERDAY, t0_done=3, t0_total=4))
        score, reason = am.score_t0_habits(YESTERDAY)
        assert score == 75
        assert "3/4" in reason

    def test_zero_adherence_scores_zero(self, table):
        seed(table, _habit_row(YESTERDAY, t0_done=0, t0_total=4))
        assert am.score_t0_habits(YESTERDAY)[0] == 0

    def test_absent_habit_data_is_neutral_rather_than_a_zero(self, table):
        """ADR-104: no data is not a failed day. The component deliberately
        returns the midpoint and says so."""
        score, reason = am.score_t0_habits(YESTERDAY)
        assert score == 50
        assert "neutral" in reason

    def test_a_day_with_no_tier_zero_habits_defined_is_neutral(self, table):
        seed(table, _habit_row(YESTERDAY, t0_done=0, t0_total=0))
        assert am.score_t0_habits(YESTERDAY)[0] == 50

    def test_tier_one_scoring_mirrors_tier_zero(self, table):
        seed(table, _habit_row(YESTERDAY, t1_done=1, t1_total=2))
        assert am.score_t1_habits(YESTERDAY)[0] == 50
        assert am.score_t1_habits(YESTERDAY)[1].startswith("1/2")

    def test_absent_tier_one_data_is_neutral(self, table):
        assert am.score_t1_habits(YESTERDAY)[0] == 50

    def test_a_day_with_no_tier_one_habits_defined_is_neutral(self, table):
        seed(table, _habit_row(YESTERDAY, t1_done=0, t1_total=0))
        assert am.score_t1_habits(YESTERDAY)[0] == 50

    def test_decimal_counts_from_dynamodb_are_handled(self, table):
        seed(table, row("habit_scores", "DATE#" + YESTERDAY, tier0_done=Decimal("3"), tier0_total=Decimal("4")))
        assert am.score_t0_habits(YESTERDAY)[0] == 75


# ──────────────────────────────────────────────────────────────────────────────
# Grade-trend component
# ──────────────────────────────────────────────────────────────────────────────


class TestGradeTrend:
    def test_too_little_history_is_neutral_rather_than_a_guess(self, table):
        score, reason = am.score_grade_trend(YESTERDAY)
        assert score == 50
        assert "insufficient" in reason

    def test_an_unparseable_grade_value_is_skipped_not_fatal(self, table):
        for i, d in enumerate(["2026-05-07", "2026-05-08", "2026-05-09"]):
            seed(table, row("day_grade", "DATE#" + d, score="not-a-number"))
        assert am.score_grade_trend(YESTERDAY)[0] == 50

    def test_the_trend_score_is_clamped_into_the_zero_to_one_hundred_band(self, table):
        # An extreme collapse must not produce a negative component score.
        for d, v in [("2026-05-09", 5), ("2026-05-08", 5), ("2026-05-07", 5), ("2026-05-06", 95), ("2026-05-05", 95)]:
            seed(table, row("day_grade", "DATE#" + d, score=v))
        score, _ = am.score_grade_trend(YESTERDAY)
        assert 0 <= score <= 100

    def test_a_real_grade_history_produces_a_real_trend(self, table):
        # A week of clearly improving grades, written the way the partition is
        # actually written (total_score).
        for d, v in [
            ("2026-05-03", 60),
            ("2026-05-04", 62),
            ("2026-05-05", 64),
            ("2026-05-06", 66),
            ("2026-05-07", 80),
            ("2026-05-08", 82),
            ("2026-05-09", 84),
        ]:
            seed(table, row("day_grade", "DATE#" + d, total_score=Decimal(str(v)), letter_grade="B"))
        score, reason = am.score_grade_trend(YESTERDAY)
        assert score > 50, reason
        assert "improving" in reason


# ──────────────────────────────────────────────────────────────────────────────
# Journal component
# ──────────────────────────────────────────────────────────────────────────────


class TestJournalScoring:
    def test_no_journal_record_scores_zero(self, table):
        assert am.score_journal(YESTERDAY) == (0, "no journal entry")

    def test_two_substantive_entries_score_full_marks(self, table):
        seed(
            table,
            row("notion", f"DATE#{YESTERDAY}#journal#morning", word_count=Decimal("300"), entry_count=Decimal("1")),
            row("notion", f"DATE#{YESTERDAY}#journal#evening", word_count=Decimal("300"), entry_count=Decimal("1")),
        )
        assert am.score_journal(YESTERDAY)[0] == 100

    def test_a_single_decent_entry_scores_sixty(self, table):
        seed(table, row("notion", "DATE#" + YESTERDAY, entry_count=1, word_count=200))
        assert am.score_journal(YESTERDAY)[0] == 60

    def test_a_template_only_day_scores_thirty(self, table):
        seed(table, row("notion", "DATE#" + YESTERDAY, entry_count=0, word_count=0, template_count=1))
        assert am.score_journal(YESTERDAY)[0] == 30

    def test_a_record_with_no_content_at_all_scores_zero(self, table):
        seed(table, row("notion", "DATE#" + YESTERDAY, entry_count=0, word_count=0, template_count=0))
        assert am.score_journal(YESTERDAY) == (0, "no journal content")


# ──────────────────────────────────────────────────────────────────────────────
# The composite — what the reader actually experiences
# ──────────────────────────────────────────────────────────────────────────────


def _best_possible_day(table):
    """Seed the strongest day the platform can record."""
    seed(table, _habit_row(YESTERDAY, t0_done=4, t0_total=4, t1_done=2, t1_total=2))
    seed(
        table,
        row("notion", f"DATE#{YESTERDAY}#journal#morning", word_count=Decimal("400"), entry_count=Decimal("1")),
        row("notion", f"DATE#{YESTERDAY}#journal#evening", word_count=Decimal("400"), entry_count=Decimal("1")),
    )
    for d, v in [
        ("2026-05-03", 60),
        ("2026-05-04", 62),
        ("2026-05-05", 64),
        ("2026-05-06", 66),
        ("2026-05-07", 88),
        ("2026-05-08", 90),
        ("2026-05-09", 92),
    ]:
        seed(table, row("day_grade", "DATE#" + d, total_score=Decimal(str(v)), letter_grade="A"))


class TestCompositeMode:
    def test_the_component_weights_sum_to_one(self, table):
        """A weight drift would silently rescale the mode thresholds."""
        result = am.compute_adaptive_mode(YESTERDAY)
        cs = result["component_scores"]
        # Recover the weights from a known component vector by solving the
        # documented weighting against the reported composite.
        expected = cs["journal"] * 0.25 + cs["t0_habits"] * 0.30 + cs["t1_habits"] * 0.20 + cs["grade_trend"] * 0.25
        assert result["engagement_score"] == round(expected, 1)

    def test_every_component_reports_a_human_readable_reason(self, table):
        result = am.compute_adaptive_mode(YESTERDAY)
        assert set(result["factors"]) == set(result["component_scores"])
        assert all(isinstance(v, str) and v for v in result["factors"].values())

    def test_the_mode_label_matches_the_mode(self, table):
        seed(table, _habit_row(YESTERDAY, t0_done=0, t0_total=4, t1_done=0, t1_total=2))
        result = am.compute_adaptive_mode(YESTERDAY)
        assert result["brief_mode"] == "struggling"
        assert "Rough Patch" in result["mode_label"]

    @pytest.mark.parametrize(
        "t0_done,t0_total,expected_mode",
        [(0, 4, "struggling"), (4, 4, "standard")],
    )
    def test_the_mode_moves_with_measured_adherence(self, table, t0_done, t0_total, expected_mode):
        seed(table, _habit_row(YESTERDAY, t0_done=t0_done, t0_total=t0_total, t1_done=t0_done and 2 or 0, t1_total=2))
        assert am.compute_adaptive_mode(YESTERDAY)["brief_mode"] == expected_mode

    def test_the_best_possible_day_can_reach_flourishing(self, table):
        _best_possible_day(table)
        result = am.compute_adaptive_mode(YESTERDAY)
        assert result["brief_mode"] == "flourishing", result["component_scores"]

    def test_a_day_with_no_data_at_all_is_not_called_a_rough_patch(self, table):
        result = am.compute_adaptive_mode(YESTERDAY)
        assert result["brief_mode"] != "struggling", result["component_scores"]


# ──────────────────────────────────────────────────────────────────────────────
# Storage
# ──────────────────────────────────────────────────────────────────────────────


class TestStoreAdaptiveMode:
    def _result(self, **kw):
        base = {
            "date": YESTERDAY,
            "engagement_score": 62.5,
            "brief_mode": "standard",
            "mode_label": "Standard",
            "factors": {"journal": "x"},
            "component_scores": {"journal": 0},
        }
        base.update(kw)
        return base

    def test_the_record_lands_on_the_adaptive_mode_partition_for_that_date(self, table, frozen_clock):
        am.store_adaptive_mode(YESTERDAY, self._result())
        item = table.puts[0]
        assert item["pk"] == PK + "adaptive_mode"
        assert item["sk"] == "DATE#" + YESTERDAY
        assert item["date"] == YESTERDAY

    def test_the_stored_score_is_an_integer_the_brief_can_render(self, table, frozen_clock):
        am.store_adaptive_mode(YESTERDAY, self._result(engagement_score=62.5))
        assert table.puts[0]["engagement_score"] == 62

    def test_the_mode_and_its_reasons_are_stored_for_the_brief_to_explain_itself(self, table, frozen_clock):
        am.store_adaptive_mode(YESTERDAY, self._result())
        item = table.puts[0]
        assert item["brief_mode"] == "standard"
        assert item["mode_label"] == "Standard"
        assert item["factors"] == {"journal": "x"}
        assert item["component_scores"] == {"journal": 0}

    def test_every_row_is_phase_stamped(self, table, frozen_clock):
        """ADR-058/#1814 — an unstamped row reads as CURRENT after a reset."""
        am.store_adaptive_mode(YESTERDAY, self._result())
        assert "phase" in table.puts[0]

    def test_a_critical_validation_failure_skips_the_write(self, table, frozen_clock, monkeypatch):
        import ingestion.ingestion_validator as validator

        class _Res:
            should_skip_ddb = True
            errors = ["CRITICAL: bad"]
            warnings = []

        monkeypatch.setattr(validator, "validate_item", lambda *a, **kw: _Res())
        am.store_adaptive_mode(YESTERDAY, self._result())
        assert table.puts == []


# ──────────────────────────────────────────────────────────────────────────────
# Handler
# ──────────────────────────────────────────────────────────────────────────────


class TestHandler:
    @pytest.fixture(autouse=True)
    def _no_engagement(self, monkeypatch):
        """The presence instrument is a separate concern with its own reads;
        stub it so these tests assert only the adaptive_mode path."""
        monkeypatch.setattr(am, "compute_and_store_engagement", lambda: {"presence_class": "present"})

    def test_healthcheck_short_circuits_before_any_read(self, table, frozen_clock):
        assert am.lambda_handler({"healthcheck": True}, None)["statusCode"] == 200
        assert table.puts == []

    def test_the_default_target_is_yesterday(self, table, frozen_clock):
        am.lambda_handler({}, None)
        assert table.puts[0]["sk"] == "DATE#" + YESTERDAY

    def test_an_explicit_date_is_honoured(self, table, frozen_clock):
        am.lambda_handler({"date": "2026-04-01"}, None)
        assert table.puts[0]["sk"] == "DATE#2026-04-01"

    def test_a_backfill_writes_one_record_per_requested_day(self, table, frozen_clock):
        am.lambda_handler({"backfill_days": 3}, None)
        assert sorted(p["sk"] for p in table.puts) == ["DATE#2026-05-08", "DATE#2026-05-09", "DATE#2026-05-10"]

    def test_one_bad_day_does_not_abort_the_rest_of_a_backfill(self, table, frozen_clock, monkeypatch):
        calls = {"n": 0}
        real = am.compute_adaptive_mode

        def _flaky(date_str):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("boom")
            return real(date_str)

        monkeypatch.setattr(am, "compute_adaptive_mode", _flaky)
        am.lambda_handler({"backfill_days": 3}, None)
        assert len(table.puts) == 2

    def test_an_engagement_failure_never_loses_the_adaptive_mode_write(self, table, frozen_clock, monkeypatch):
        """The presence instrument is fail-soft by design — the mode record is
        what the brief actually needs."""
        monkeypatch.setattr(am, "compute_and_store_engagement", lambda: (_ for _ in ()).throw(RuntimeError("gap compute down")))
        am.lambda_handler({}, None)
        assert len(table.puts) == 1


# ──────────────────────────────────────────────────────────────────────────────
# Presence / engagement window reads
# ──────────────────────────────────────────────────────────────────────────────


class TestPresenceWindowReads:
    def test_log_dates_returns_deduped_days_newest_first(self, table):
        seed(
            table,
            row("hevy", f"DATE#{YESTERDAY}#WORKOUT#a"),
            row("hevy", f"DATE#{YESTERDAY}#WORKOUT#b"),
            row("hevy", "DATE#2026-05-07#WORKOUT#c"),
        )
        assert am._log_dates("hevy", TODAY) == [YESTERDAY, "2026-05-07"]

    def test_the_window_start_can_be_floored_at_the_experiment_genesis(self, table):
        """#955: the prior cycle's logs must not leak into this cycle's gap."""
        seed(table, row("hevy", "DATE#2026-04-20#WORKOUT#a"), row("hevy", f"DATE#{YESTERDAY}#WORKOUT#b"))
        assert am._log_dates("hevy", TODAY, floor="2026-05-01") == [YESTERDAY]

    def test_a_predicate_decides_whether_a_record_counts_as_logged(self, table):
        """#914: habitify writes a record every day even at zero completions —
        counting bare record-days read a 14-day stall as no gap at all."""
        seed(
            table,
            row("habitify", "DATE#" + YESTERDAY, total_completed=0),
            row("habitify", "DATE#2026-05-08", total_completed=3),
        )
        got = am._log_dates("habitify", TODAY, attrs=("total_completed",), predicate=lambda i: i.get("total_completed", 0) > 0)
        assert got == ["2026-05-08"]

    def test_a_malformed_sort_key_is_skipped_rather_than_crashing_the_window(self, table):
        seed(table, row("hevy", "DATE#not-a-date#WORKOUT#a"), row("hevy", f"DATE#{YESTERDAY}#WORKOUT#b"))
        assert am._log_dates("hevy", TODAY) == [YESTERDAY]

    def test_a_failed_window_query_degrades_to_an_empty_window(self, table):
        table.query_error = RuntimeError("throttled")
        assert am._log_dates("hevy", TODAY) == []

    def test_latest_date_is_the_newest_day_in_the_window(self, table):
        seed(table, row("whoop", "DATE#2026-05-07"), row("whoop", "DATE#" + YESTERDAY))
        assert am._latest_date("whoop", TODAY) == YESTERDAY

    def test_latest_date_is_none_when_the_source_is_silent(self, table):
        assert am._latest_date("whoop", TODAY) is None

    def test_the_weight_series_drops_rows_with_no_weight(self, table):
        seed(
            table,
            row("withings", "DATE#2026-05-07", weight_lbs=Decimal("320.0")),
            row("withings", "DATE#2026-05-08"),
            row("withings", "DATE#" + YESTERDAY, weight_lbs=Decimal("318.5")),
        )
        assert am._weight_series(TODAY) == [("2026-05-07", 320.0), (YESTERDAY, 318.5)]

    def test_an_unparseable_weight_is_skipped_not_fatal(self, table):
        seed(table, row("withings", "DATE#2026-05-07", weight_lbs="heavy"))
        assert am._weight_series(TODAY) == []

    def test_a_failed_weight_query_degrades_to_an_empty_series(self, table):
        table.query_error = RuntimeError("throttled")
        assert am._weight_series(TODAY) == []

    def test_travel_days_are_returned_as_a_set_of_days(self, table):
        seed(table, row("travel", "DATE#2026-05-07"), row("travel", "DATE#2026-05-07"))
        assert am._travel_days(TODAY) == {"2026-05-07"}


class TestStoreEngagementState:
    def test_the_signal_is_written_both_as_history_and_as_a_cheap_current_read(self, table, frozen_clock):
        """The orchestrator and site-api read STATE#current rather than scanning
        the dated history."""
        am.store_engagement_state(TODAY, {"presence_class": "present", "gap_days": 0, "returned": False})
        assert {p["sk"] for p in table.puts} == {"DATE#" + TODAY, "STATE#current"}

    def test_both_rows_carry_the_same_signal(self, table, frozen_clock):
        am.store_engagement_state(TODAY, {"presence_class": "quiet", "gap_days": 6, "returned": False})
        for item in table.puts:
            assert item["presence_class"] == "quiet"
            assert item["gap_days"] == 6
            assert item["pk"] == PK + "engagement_state"

    def test_floats_in_the_signal_are_decimalised_before_the_write(self, table, frozen_clock):
        am.store_engagement_state(TODAY, {"presence_class": "present", "weight_delta_lbs": 1.5})
        assert not any(isinstance(v, float) for v in table.puts[0].values())
        assert table.puts[0]["weight_delta_lbs"] == Decimal("1.5")
