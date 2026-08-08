#!/usr/bin/env python3
"""tests/test_daily_metrics_compute_behavior.py — behavioral contracts of
`lambdas/compute/daily_metrics_compute_lambda.py`.

Part of #1658 tranche 2. This Lambda is the *only* writer of the
`computed_metrics` partition, which the daily brief, the cockpit, the coach
prompts and `public_stats.json` all read. A wrong number here is published
everywhere at once, so the contracts under test are the ones a reader sees:

  * the window reads honour the per-source phase class (#2109) — a
    RAW_TIMESERIES window must not truncate to the cycle's age,
  * readiness weighting, colour bands and honest absence,
  * habit-streak arithmetic including weekday/post-training applicability,
  * Strava multi-device dedup,
  * what each of the three stored partitions actually contains,
  * the data-aware idempotency fingerprints,
  * the handler's sick-day and no-profile branches.

Time is frozen everywhere `datetime.now` is reachable — no fixture date is ever
combined with the real clock.
"""

import os
import sys
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LAMBDAS = os.path.join(ROOT, "lambdas")
if LAMBDAS not in sys.path:
    sys.path.insert(0, LAMBDAS)

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

_import_err = None
try:
    import daily_metrics_compute_lambda as dmc
    from experiment.phase_filter import source_reads_cross_phase
except ImportError as _e:  # pragma: no cover — only when the bundle layout changes
    _import_err = _e
    dmc = None  # type: ignore

if _import_err is not None:  # pragma: no cover
    pytestmark = pytest.mark.skip(reason=f"daily_metrics_compute_lambda unavailable: {_import_err}")  # type: ignore


FROZEN_NOW = datetime(2026, 5, 10, 17, 40, 0, tzinfo=timezone.utc)
TODAY = "2026-05-10"
YESTERDAY = "2026-05-09"


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
    monkeypatch.setattr(dmc, "datetime", _FrozenDatetime)
    return FROZEN_NOW


# ──────────────────────────────────────────────────────────────────────────────
# Test double
# ──────────────────────────────────────────────────────────────────────────────


class FakeTable:
    """DynamoDB Table stand-in keyed the way this module keys the real table.

    `items` maps (pk, sk) → item. `query()` honours the two shapes the module
    issues — `sk BETWEEN :s AND :e` and `begins_with(sk, :prefix|:sk)` — and
    records the full kwargs so a test can assert on the phase FilterExpression.
    """

    def __init__(self, items=None):
        self.items = dict(items or {})
        self.puts = []
        self.queries = []
        self.get_errors = set()
        self.query_error = None
        self.pages = None  # optional list of LastEvaluatedKey-chained pages

    # -- writes --
    def put_item(self, Item=None, **kwargs):
        self.puts.append(Item)
        self.items[(Item["pk"], Item["sk"])] = Item
        return {}

    # -- reads --
    def get_item(self, Key=None, **kwargs):
        if Key["pk"] in self.get_errors:
            raise RuntimeError("throttled")
        item = self.items.get((Key["pk"], Key["sk"]))
        return {"Item": item} if item is not None else {}

    def query(self, **kwargs):
        self.queries.append(kwargs)
        if self.query_error is not None:
            raise self.query_error
        if self.pages:
            return self.pages.pop(0)
        vals = kwargs.get("ExpressionAttributeValues", {})
        pk = vals.get(":pk")
        rows = [v for (p, _s), v in self.items.items() if p == pk]
        if ":s" in vals and ":e" in vals:
            rows = [r for r in rows if vals[":s"] <= r["sk"] <= vals[":e"]]
        prefix = vals.get(":prefix") or vals.get(":sk")
        if prefix:
            rows = [r for r in rows if str(r["sk"]).startswith(prefix)]
        return {"Items": sorted(rows, key=lambda r: r["sk"])}


def _row(source, sk, **fields):
    return {"pk": dmc.USER_PREFIX + source, "sk": sk, **fields}


def _date_row(source, date_str, **fields):
    return _row(source, "DATE#" + date_str, **fields)


@pytest.fixture
def table(monkeypatch):
    t = FakeTable()
    monkeypatch.setattr(dmc, "table", t)
    return t


def seed(table, *rows):
    for r in rows:
        table.items[(r["pk"], r["sk"])] = r


def stored(table, source, sk_suffix=None):
    """The items this run put into a partition, in write order."""
    pk = dmc.USER_PREFIX + source
    return [i for i in table.puts if i["pk"] == pk and (sk_suffix is None or i["sk"].endswith(sk_suffix))]


# ──────────────────────────────────────────────────────────────────────────────
# Small numeric helpers
# ──────────────────────────────────────────────────────────────────────────────


class TestNumericHelpers:
    def test_latest_weight_takes_the_most_recent_non_null_reading(self):
        recs = [{"weight_lbs": 320}, {"weight_lbs": None}, {"weight_lbs": 318}, {"other": 1}]
        assert dmc.latest_weight_lbs(recs) == 318

    def test_latest_weight_is_none_when_the_window_holds_no_weigh_in(self):
        assert dmc.latest_weight_lbs([{"other": 1}]) is None
        assert dmc.latest_weight_lbs([]) is None

    def test_avg_ignores_absent_values_rather_than_scoring_them_as_zero(self):
        """ADR-104: a missing night is absent, not a zero-HRV night."""
        assert dmc.avg([50, None, 60]) == 55.0

    def test_avg_of_an_all_absent_window_is_none_not_zero(self):
        assert dmc.avg([None, None]) is None
        assert dmc.avg([]) is None

    def test_clamp_bounds_both_ends(self):
        assert dmc.clamp(-5) == 0
        assert dmc.clamp(150) == 100
        assert dmc.clamp(63) == 63
        assert dmc.clamp(5, lo=10, hi=20) == 10

    def test_to_dec_rounds_and_preserves_absence(self):
        assert dmc._to_dec(1.23456) == Decimal("1.2346")
        assert dmc._to_dec(None) is None

    def test_deep_dec_converts_every_number_and_stringifies_map_keys(self):
        """DynamoDB rejects floats and non-string map keys alike."""
        out = dmc._deep_dec({0: {"a": 1.5}, 1: [2, True]})
        assert out == {"0": {"a": Decimal("1.5")}, "1": [Decimal("2"), True]}
        assert all(isinstance(k, str) for k in out)

    def test_deep_dec_keeps_booleans_as_booleans(self):
        assert dmc._deep_dec({"flag": True})["flag"] is True


# ──────────────────────────────────────────────────────────────────────────────
# DDB read helpers — the #2109 phase contract
# ──────────────────────────────────────────────────────────────────────────────


class TestFetchHelpers:
    def test_fetch_date_returns_the_decimal_free_item(self, table):
        seed(table, _date_row("whoop", YESTERDAY, hrv=Decimal("55.5")))
        rec = dmc.fetch_date("whoop", YESTERDAY)
        assert rec["hrv"] == 55.5
        assert not isinstance(rec["hrv"], Decimal)

    def test_fetch_date_returns_none_for_a_missing_day(self, table):
        assert dmc.fetch_date("whoop", YESTERDAY) is None

    def test_fetch_date_degrades_to_none_on_a_read_failure(self, table):
        """Fail-soft: a throttled read must not abort the whole compute."""
        table.get_errors.add(dmc.USER_PREFIX + "whoop")
        assert dmc.fetch_date("whoop", YESTERDAY) is None

    def test_fetch_range_is_bounded_by_the_requested_dates(self, table):
        seed(
            table,
            _date_row("whoop", "2026-05-01", hrv=Decimal("40")),
            _date_row("whoop", "2026-05-05", hrv=Decimal("50")),
            _date_row("whoop", "2026-05-09", hrv=Decimal("60")),
        )
        recs = dmc.fetch_range("whoop", "2026-05-03", "2026-05-09")
        assert [r["hrv"] for r in recs] == [50.0, 60.0]

    def test_fetch_range_follows_pagination_to_the_last_page(self, table):
        """A truncated window silently shortens every trailing baseline."""
        table.pages = [
            {"Items": [_date_row("whoop", "2026-05-01", hrv=Decimal("40"))], "LastEvaluatedKey": {"pk": "x", "sk": "y"}},
            {"Items": [_date_row("whoop", "2026-05-02", hrv=Decimal("41"))]},
        ]
        assert len(dmc.fetch_range("whoop", "2026-05-01", "2026-05-09")) == 2

    def test_fetch_range_degrades_to_an_empty_window_on_a_query_failure(self, table):
        table.query_error = RuntimeError("throttled")
        assert dmc.fetch_range("whoop", "2026-05-01", "2026-05-09") == []

    @pytest.mark.parametrize("source", ["whoop", "strava", "hevy", "withings", "macrofactor", "habitify", "computed_metrics"])
    def test_phase_filter_is_applied_exactly_when_the_taxonomy_says_so(self, table, source):
        """#2109: the include_pilot decision is derived per source, never
        hard-coded. Expectation comes from the taxonomy, so a source that
        changes class cannot leave this test asserting the old answer."""
        dmc.fetch_range(source, "2026-05-01", "2026-05-09")
        kwargs = table.queries[-1]
        applied = "FilterExpression" in kwargs
        assert applied is not source_reads_cross_phase(source), (
            f"{source}: cross_phase={source_reads_cross_phase(source)} but " f"FilterExpression present={applied}"
        )

    def test_journal_entries_are_fetched_under_the_dated_journal_prefix(self, table):
        seed(
            table,
            _row("notion", f"DATE#{YESTERDAY}#journal#1", title="a"),
            _row("notion", f"DATE#{YESTERDAY}#journal#2", title="b"),
            _row("notion", f"DATE#{TODAY}#journal#3", title="c"),
        )
        assert len(dmc.fetch_journal_entries(YESTERDAY)) == 2

    def test_journal_fetch_degrades_to_an_empty_list_on_failure(self, table):
        table.query_error = RuntimeError("throttled")
        assert dmc.fetch_journal_entries(YESTERDAY) == []


# ──────────────────────────────────────────────────────────────────────────────
# Diary sessions (#1843)
# ──────────────────────────────────────────────────────────────────────────────


class TestDiarySessions:
    def test_zero_is_returned_for_a_day_with_no_entries(self):
        """0 is an honest absence the correlation engine can use, not a gap."""
        assert dmc.compute_diary_sessions([]) == 0
        assert dmc.compute_diary_sessions(None) == 0

    def test_only_diary_channels_are_counted(self):
        entries = [{"channel": ch} for ch in dmc._DIARY_CHANNELS]
        entries.append({"channel": "written"})
        assert dmc.compute_diary_sessions(entries) == len(dmc._DIARY_CHANNELS)

    def test_every_registered_diary_channel_counts(self):
        """Guard the SET: the counted channels are derived from the module's own
        frozenset, so adding a recording channel can't silently go uncounted."""
        for channel in dmc._DIARY_CHANNELS:
            assert dmc.compute_diary_sessions([{"channel": channel}]) == 1


# ──────────────────────────────────────────────────────────────────────────────
# Whoop sleep normalization
# ──────────────────────────────────────────────────────────────────────────────


class TestNormalizeWhoopSleep:
    def test_absent_record_passes_through_untouched(self):
        assert dmc.normalize_whoop_sleep(None) is None
        assert dmc.normalize_whoop_sleep({}) == {}

    def test_whoop_field_names_are_mapped_onto_the_scoring_schema(self):
        out = dmc.normalize_whoop_sleep(
            {
                "sleep_quality_score": 82,
                "sleep_efficiency_percentage": 91,
                "time_awake_hours": 0.6,
                "disturbance_count": 12,
            }
        )
        assert out["sleep_score"] == 82
        assert out["sleep_efficiency_pct"] == 91
        assert out["waso_hours"] == 0.6
        assert out["toss_and_turns"] == 12

    def test_an_existing_common_schema_value_is_never_overwritten(self):
        out = dmc.normalize_whoop_sleep({"sleep_quality_score": 82, "sleep_score": 70})
        assert out["sleep_score"] == 70

    def test_stage_percentages_are_derived_from_hours_over_duration(self):
        out = dmc.normalize_whoop_sleep(
            {"sleep_duration_hours": 8.0, "slow_wave_sleep_hours": 1.6, "rem_sleep_hours": 2.0, "light_sleep_hours": 4.4}
        )
        assert out["deep_pct"] == 20.0
        assert out["rem_pct"] == 25.0
        assert out["light_pct"] == 55.0

    def test_no_stage_percentages_are_invented_when_duration_is_missing(self):
        out = dmc.normalize_whoop_sleep({"slow_wave_sleep_hours": 1.6})
        assert "deep_pct" not in out

    def test_the_input_record_is_not_mutated(self):
        src = {"sleep_quality_score": 82}
        dmc.normalize_whoop_sleep(src)
        assert src == {"sleep_quality_score": 82}


# ──────────────────────────────────────────────────────────────────────────────
# Strava dedup
# ──────────────────────────────────────────────────────────────────────────────


def _activity(start, sport="Run", **kw):
    return {"start_date_local": start, "sport_type": sport, **kw}


class TestDedupActivities:
    def test_a_single_activity_is_returned_unchanged(self):
        acts = [_activity("2026-05-09T08:00:00")]
        assert dmc.dedup_activities(acts) == acts

    def test_the_richer_of_two_overlapping_recordings_survives(self):
        watch = _activity("2026-05-09T08:00:00", distance_meters=8000, moving_time_seconds=2400)
        phone = _activity("2026-05-09T08:05:00", distance_meters=0, moving_time_seconds=100)
        kept = dmc.dedup_activities([phone, watch])
        assert len(kept) == 1
        assert kept[0]["distance_meters"] == 8000

    def test_the_same_sport_more_than_fifteen_minutes_apart_is_two_workouts(self):
        a = _activity("2026-05-09T08:00:00", distance_meters=8000)
        b = _activity("2026-05-09T09:00:00", distance_meters=5000)
        assert len(dmc.dedup_activities([a, b])) == 2

    def test_different_sports_at_the_same_time_are_never_merged(self):
        run = _activity("2026-05-09T08:00:00", sport="Run", distance_meters=8000)
        ride = _activity("2026-05-09T08:00:00", sport="Ride", distance_meters=20000)
        assert len(dmc.dedup_activities([run, ride])) == 2

    def test_the_legacy_type_field_is_honoured_when_sport_type_is_absent(self):
        a = {"start_date_local": "2026-05-09T08:00:00", "type": "Run", "distance_meters": 8000}
        b = {"start_date_local": "2026-05-09T08:05:00", "type": "Run", "distance_meters": 0}
        assert len(dmc.dedup_activities([a, b])) == 1

    def test_activities_with_an_unparseable_start_are_kept_not_dropped(self):
        good = _activity("2026-05-09T08:00:00", distance_meters=8000)
        undated = {"sport_type": "Run", "distance_meters": 3000}
        kept = dmc.dedup_activities([good, undated])
        assert len(kept) == 2
        assert undated in kept

    def test_a_polyline_breaks_the_tie_between_otherwise_equal_records(self):
        plain = _activity("2026-05-09T08:00:00", distance_meters=8000, moving_time_seconds=2400)
        mapped = _activity("2026-05-09T08:01:00", distance_meters=8000, moving_time_seconds=2400, summary_polyline="abc")
        kept = dmc.dedup_activities([mapped, plain])
        assert len(kept) == 1
        assert kept[0].get("summary_polyline") == "abc"


# ──────────────────────────────────────────────────────────────────────────────
# Readiness
# ──────────────────────────────────────────────────────────────────────────────


def _readiness_data(**kw):
    base = {"whoop_today": None, "whoop": None, "sleep": None, "hrv": {}, "tsb": None}
    base.update(kw)
    return base


class TestComputeReadiness:
    def test_no_inputs_yields_no_score_and_a_gray_light(self):
        """ADR-104: an unmeasurable day must not score 0 — 0 reads as 'terrible',
        absence reads as 'unknown'."""
        score, colour, breakdown = dmc.compute_readiness(_readiness_data())
        assert score is None
        assert colour == "gray"
        assert breakdown == []

    def test_a_lone_recovery_reading_carries_the_whole_score(self):
        score, colour, _ = dmc.compute_readiness(_readiness_data(whoop_today={"recovery_score": 85}))
        assert score == 85
        assert colour == "green"

    def test_present_components_are_reweighted_to_sum_to_one(self):
        """Weights are renormalised over what exists, so a missing component
        neither dilutes nor is imputed."""
        data = _readiness_data(whoop_today={"recovery_score": 90}, sleep={"sleep_score": 50})
        score, _, _ = dmc.compute_readiness(data)
        assert score == round((90 * 0.40 + 50 * 0.25) / 0.65)

    def test_todays_recovery_beats_yesterdays_when_both_exist(self):
        data = _readiness_data(whoop_today={"recovery_score": 90}, whoop={"recovery_score": 30})
        assert dmc.compute_readiness(data)[0] == 90

    def test_yesterdays_recovery_is_used_when_today_has_not_synced(self):
        data = _readiness_data(whoop_today=None, whoop={"recovery_score": 30})
        assert dmc.compute_readiness(data)[0] == 30

    def test_tsb_is_mapped_onto_the_documented_anchor_points(self):
        """TSB 0 → 60, −30 → 0, +20 → 100."""
        for tsb, expected in ((0, 60), (-30, 0), (20, 100)):
            score, _, breakdown = dmc.compute_readiness(_readiness_data(tsb=tsb))
            assert score == expected
            assert breakdown[0]["key"] == "tsb"

    def test_deeply_negative_tsb_is_clamped_at_zero_not_negative(self):
        assert dmc.compute_readiness(_readiness_data(tsb=-100))[0] == 0

    def test_hrv_trend_is_skipped_when_the_thirty_day_baseline_is_absent(self):
        data = _readiness_data(whoop_today={"recovery_score": 80}, hrv={"hrv_7d": 55, "hrv_30d": None})
        _, _, breakdown = dmc.compute_readiness(data)
        assert [c["key"] for c in breakdown] == ["recovery"]

    def test_hrv_trend_contributes_when_both_baselines_exist(self):
        data = _readiness_data(whoop_today={"recovery_score": 80}, hrv={"hrv_7d": 55, "hrv_30d": 50})
        _, _, breakdown = dmc.compute_readiness(data)
        assert {c["key"] for c in breakdown} == {"recovery", "hrv_trend"}
        assert next(c for c in breakdown if c["key"] == "hrv_trend")["weight"] == 0.20

    @pytest.mark.parametrize("recovery,colour", [(80, "green"), (79, "yellow"), (60, "yellow"), (59, "red"), (10, "red")])
    def test_colour_bands_switch_at_eighty_and_sixty(self, recovery, colour):
        assert dmc.compute_readiness(_readiness_data(whoop_today={"recovery_score": recovery}))[1] == colour

    def test_the_breakdown_reports_the_actual_inputs_and_their_weights(self):
        """#492/M-4: the cockpit shows this breakdown, so it must be the
        readiness inputs — not the day-grade component set."""
        data = _readiness_data(whoop_today={"recovery_score": 90}, sleep={"sleep_score": 50}, tsb=0)
        _, _, breakdown = dmc.compute_readiness(data)
        assert [(c["key"], c["weight"]) for c in breakdown] == [("recovery", 0.40), ("sleep", 0.25), ("tsb", 0.10)]


# ──────────────────────────────────────────────────────────────────────────────
# Habit streaks
# ──────────────────────────────────────────────────────────────────────────────


def _profile(registry=None, mvp=None, **kw):
    return {"habit_registry": registry or {}, "mvp_habits": mvp or [], **kw}


def _habit_days(table, days, habits_by_offset):
    """Seed `days` consecutive habitify records ending at YESTERDAY."""
    from datetime import timedelta as _td

    base = date.fromisoformat(YESTERDAY)
    for i in range(days):
        d = (base - _td(days=i)).isoformat()
        seed(table, _date_row("habitify", d, habits=habits_by_offset(i)))


class TestHabitStreaks:
    def test_no_habitify_history_yields_zero_streaks(self, table, frozen_clock):
        out = dmc.compute_habit_streaks(_profile({"sleep": {"status": "active", "tier": 0}}), YESTERDAY)
        assert out == {"tier0_streak": 0, "tier01_streak": 0, "vice_streaks": {"sleep": 0}} or out["tier0_streak"] == 0

    def test_an_unbroken_run_of_complete_days_counts_every_day(self, table, frozen_clock):
        _habit_days(table, 5, lambda i: {"sleep": 1})
        out = dmc.compute_habit_streaks(_profile({"sleep": {"status": "active", "tier": 0}}), YESTERDAY)
        assert out["tier0_streak"] == 5

    def test_the_streak_stops_at_the_first_incomplete_day(self, table, frozen_clock):
        _habit_days(table, 5, lambda i: {"sleep": 0 if i == 2 else 1})
        out = dmc.compute_habit_streaks(_profile({"sleep": {"status": "active", "tier": 0}}), YESTERDAY)
        assert out["tier0_streak"] == 2

    def test_a_missing_day_record_ends_the_walk_rather_than_counting_as_done(self, table, frozen_clock):
        _habit_days(table, 2, lambda i: {"sleep": 1})
        out = dmc.compute_habit_streaks(_profile({"sleep": {"status": "active", "tier": 0}}), YESTERDAY)
        assert out["tier0_streak"] == 2

    def test_inactive_habits_are_excluded_from_the_streak(self, table, frozen_clock):
        _habit_days(table, 3, lambda i: {"sleep": 1})
        registry = {"sleep": {"status": "active", "tier": 0}, "retired": {"status": "archived", "tier": 0}}
        assert dmc.compute_habit_streaks(_profile(registry), YESTERDAY)["tier0_streak"] == 3

    def test_tier_one_habits_join_the_combined_streak_only(self, table, frozen_clock):
        _habit_days(table, 3, lambda i: {"sleep": 1, "steps": 0})
        registry = {"sleep": {"status": "active", "tier": 0}, "steps": {"status": "active", "tier": 1}}
        out = dmc.compute_habit_streaks(_profile(registry), YESTERDAY)
        assert out["tier0_streak"] == 3
        assert out["tier01_streak"] == 0

    def test_a_weekday_only_habit_is_not_required_at_the_weekend(self, table, frozen_clock):
        # 2026-05-09 is a Saturday and 2026-05-08 a Friday.
        assert date.fromisoformat("2026-05-09").weekday() == 5
        seed(
            table,
            _date_row("habitify", "2026-05-09", habits={"work": 0}),
            _date_row("habitify", "2026-05-08", habits={"work": 1}),
        )
        registry = {"work": {"status": "active", "tier": 0, "applicable_days": "weekdays"}}
        assert dmc.compute_habit_streaks(_profile(registry), "2026-05-09")["tier0_streak"] == 2

    def test_a_post_training_habit_is_excluded_from_the_combined_streak(self, table, frozen_clock):
        _habit_days(table, 3, lambda i: {"stretch": 0})
        registry = {"stretch": {"status": "active", "tier": 1, "applicable_days": "post_training"}}
        assert dmc.compute_habit_streaks(_profile(registry), YESTERDAY)["tier01_streak"] == 3

    def test_vice_streaks_are_tracked_per_habit_and_break_independently(self, table, frozen_clock):
        _habit_days(table, 4, lambda i: {"no_weed": 1, "no_porn": 0 if i == 1 else 1})
        registry = {
            "no_weed": {"status": "active", "tier": 2, "vice": True},
            "no_porn": {"status": "active", "tier": 2, "vice": True},
        }
        out = dmc.compute_habit_streaks(_profile(registry), YESTERDAY)
        assert out["vice_streaks"] == {"no_weed": 4, "no_porn": 1}

    def test_an_empty_registry_falls_back_to_the_mvp_habit_list(self, table, frozen_clock):
        _habit_days(table, 3, lambda i: {"sleep": 1})
        assert dmc.compute_habit_streaks(_profile({}, mvp=["sleep"]), YESTERDAY)["tier0_streak"] == 3

    def test_the_lookback_is_capped_at_ninety_days(self, table, frozen_clock):
        _habit_days(table, 120, lambda i: {"sleep": 1})
        assert dmc.compute_habit_streaks(_profile({"sleep": {"status": "active", "tier": 0}}), YESTERDAY)["tier0_streak"] == 90


# ──────────────────────────────────────────────────────────────────────────────
# Stored partitions
# ──────────────────────────────────────────────────────────────────────────────


_MIN_STREAKS = {"tier0_streak": 3, "tier01_streak": 2, "vice_streaks": {"no_weed": 9}}


def _store(table, **overrides):
    kwargs = dict(
        date_str=YESTERDAY,
        day_grade_score=82.0,
        grade="B",
        component_scores={"sleep": 80, "habits_mvp": 90, "empty": None},
        component_details={"sleep": {"hours": 7.5}, "blank": {}},
        readiness_score=71,
        readiness_colour="yellow",
        streak_data=_MIN_STREAKS,
        tsb=-4.5,
        hrv_7d=55.0,
        hrv_30d=52.0,
        sleep_debt_7d_hrs=3.5,
        latest_weight=318.2,
        week_ago_weight=320.0,
        avatar_weight=318.2,
    )
    kwargs.update(overrides)
    dmc.store_computed_metrics(**kwargs)
    return stored(table, "computed_metrics")[0]


class TestStoreComputedMetrics:
    def test_the_record_is_keyed_to_the_computed_metrics_partition_and_date(self, table, frozen_clock):
        item = _store(table)
        assert item["pk"] == dmc.USER_PREFIX + "computed_metrics"
        assert item["sk"] == "DATE#" + YESTERDAY
        assert item["date"] == YESTERDAY

    def test_headline_values_are_stored_as_decimals(self, table, frozen_clock):
        item = _store(table)
        assert item["day_grade_letter"] == "B"
        assert item["day_grade_score"] == Decimal("82")
        assert item["readiness_score"] == Decimal("71")
        assert item["tsb"] == Decimal("-4.5")
        assert not any(isinstance(v, float) for v in item.values())

    def test_absent_optional_values_are_omitted_not_zeroed(self, table, frozen_clock):
        """ADR-104 again: an unscoreable day must not publish tsb=0/weight=0."""
        item = _store(table, day_grade_score=None, readiness_score=None, tsb=None, latest_weight=None)
        for field in ("day_grade_score", "readiness_score", "tsb", "latest_weight"):
            assert field not in item

    def test_streaks_are_always_written_including_zero(self, table, frozen_clock):
        item = _store(table, streak_data={"tier0_streak": 0, "tier01_streak": 0})
        assert item["tier0_streak"] == Decimal("0")
        assert item["tier01_streak"] == Decimal("0")

    def test_a_zero_diary_day_is_recorded_rather_than_omitted(self, table, frozen_clock):
        """#1843: presence of the key is the correlation engine's 'this day was
        scored' signal, so 0 must be written."""
        item = _store(table, diary_sessions=0)
        assert item["diary_sessions"] == Decimal("0")

    def test_diary_sessions_is_omitted_only_when_the_caller_passes_none(self, table, frozen_clock):
        assert "diary_sessions" not in _store(table, diary_sessions=None)

    def test_null_component_scores_are_dropped_and_empty_details_skipped(self, table, frozen_clock):
        item = _store(table)
        assert set(item["component_scores"]) == {"sleep", "habits_mvp"}
        assert set(item["component_details"]) == {"sleep"}

    def test_vice_streaks_are_stored_as_decimals(self, table, frozen_clock):
        assert _store(table)["vice_streaks"] == {"no_weed": Decimal("9")}

    def test_the_weight_trajectory_carries_its_uncertainty_band(self, table, frozen_clock):
        """ADR-105: a rate without a CI is not publishable."""
        traj = {
            "weekly_rate_lbs": -1.4,
            "rate_provisional": False,
            "weekly_rate_ci_low": -2.0,
            "weekly_rate_ci_high": -0.8,
            "projection_confidence": 0.8,
            "projected_goal_date": "2027-01-01",
            "projected_goal_date_earliest": "2026-11-01",
            "projected_goal_date_latest": "2027-04-01",
            "days_to_goal": 236,
        }
        item = _store(table, weight_traj=traj)
        assert item["weekly_rate_lbs"] == Decimal("-1.4")
        assert item["rate_provisional"] is False
        assert item["weekly_rate_ci_low"] == Decimal("-2")
        assert item["weekly_rate_ci_high"] == Decimal("-0.8")
        assert item["projected_goal_date"] == "2027-01-01"
        assert item["days_to_goal"] == Decimal("236")

    def test_a_projection_without_a_confidence_interval_stores_neither_bound(self, table, frozen_clock):
        item = _store(table, weight_traj={"weekly_rate_lbs": -1.4, "rate_provisional": True})
        assert item["rate_provisional"] is True
        assert "weekly_rate_ci_low" not in item
        assert "projection_confidence" not in item

    def test_canonical_vitals_are_stored_with_units_in_the_field_names(self, table, frozen_clock):
        vitals = {"recovery_pct": 62, "hrv_ms": 55.4, "rhr_bpm": 58, "protein_g_avg": 141.2, "protein_g_target": 190}
        item = _store(table, vitals=vitals)
        assert item["recovery_pct"] == Decimal("62")
        assert item["hrv_ms"] == Decimal("55.4")
        assert item["protein_g_avg"] == Decimal("141.2")
        assert "protein_g_floor" not in item

    def test_fingerprints_are_stored_so_the_next_run_can_detect_late_data(self, table, frozen_clock):
        fps = {"whoop": "2026-05-10T14:00:00+00:00"}
        assert _store(table, source_fingerprints=fps)["source_fingerprints"] == fps

    def test_a_ddb_write_failure_is_raised_not_swallowed(self, table, frozen_clock, monkeypatch):
        """A scheduled async invocation that RETURNS looks like success — the
        failure has to raise to reach the error metric and the DLQ."""

        def _boom(**kwargs):
            raise RuntimeError("ProvisionedThroughputExceeded")

        monkeypatch.setattr(table, "put_item", _boom)
        with pytest.raises(RuntimeError):
            _store(table)


class TestStoreDayGrade:
    def test_the_record_preserves_the_mcp_compatible_schema(self, table, frozen_clock):
        dmc.store_day_grade(YESTERDAY, 82.0, "B", {"sleep": 80, "nutrition": None}, {"sleep": 0.3})
        item = stored(table, "day_grade")[0]
        assert item["sk"] == "DATE#" + YESTERDAY
        assert item["total_score"] == Decimal("82.0")
        assert item["letter_grade"] == "B"
        assert item["component_sleep"] == Decimal("80")
        assert "component_nutrition" not in item
        assert item["weights_snapshot"] == {"sleep": Decimal("0.3")}

    def test_every_row_is_phase_stamped(self, table, frozen_clock):
        """ADR-058/#1814: an unstamped row passes the default-deny read filter
        as CURRENT, so a pre-genesis row would count as an experiment day."""
        dmc.store_day_grade(YESTERDAY, 82.0, "B", {}, {})
        assert "phase" in stored(table, "day_grade")[0]

    def test_a_write_failure_is_logged_and_does_not_abort_the_run(self, table, frozen_clock, monkeypatch):
        monkeypatch.setattr(table, "put_item", lambda **kw: (_ for _ in ()).throw(RuntimeError("boom")))
        dmc.store_day_grade(YESTERDAY, 82.0, "B", {}, {})  # must not raise


class TestStoreHabitScores:
    def _details(self, **kw):
        base = {
            "habits_mvp": {
                "composite_method": "tier_weighted",
                "tier0": {"done": 3, "total": 4},
                "tier1": {"done": 1, "total": 2},
                "vices": {"held": 2, "total": 3},
                "tier_status": {0: {"sleep": True, "steps": False}, 1: {"read": True}},
            }
        }
        base["habits_mvp"].update(kw)
        return base

    def test_nothing_is_written_when_the_composite_method_is_not_tier_weighted(self, table, frozen_clock):
        dmc.store_habit_scores(YESTERDAY, {"habits_mvp": {"composite_method": "legacy"}}, {}, {}, _profile())
        assert stored(table, "habit_scores") == []

    def test_nothing_is_written_when_there_are_no_habit_details(self, table, frozen_clock):
        dmc.store_habit_scores(YESTERDAY, {}, {}, {}, _profile())
        assert stored(table, "habit_scores") == []

    def test_tier_counts_and_percentages_are_stored(self, table, frozen_clock):
        dmc.store_habit_scores(YESTERDAY, self._details(), {"habits_mvp": 78}, {}, _profile())
        item = stored(table, "habit_scores")[0]
        assert (item["tier0_done"], item["tier0_total"]) == (3, 4)
        assert item["tier0_pct"] == Decimal("0.75")
        assert item["tier1_pct"] == Decimal("0.5")
        assert item["composite_score"] == Decimal("78")
        assert item["scoring_method"] == "tier_weighted_v1"

    def test_the_missed_tier_zero_habits_are_named(self, table, frozen_clock):
        dmc.store_habit_scores(YESTERDAY, self._details(), {}, {}, _profile())
        assert stored(table, "habit_scores")[0]["missed_tier0"] == ["steps"]

    def test_a_fully_complete_tier_zero_day_records_no_missed_list(self, table, frozen_clock):
        details = self._details(tier_status={0: {"sleep": True}})
        dmc.store_habit_scores(YESTERDAY, details, {}, {}, _profile())
        assert "missed_tier0" not in stored(table, "habit_scores")[0]

    def test_synergy_group_completion_is_computed_from_the_active_registry(self, table, frozen_clock):
        registry = {
            "sleep": {"status": "active", "synergy_group": "recovery"},
            "read": {"status": "active", "synergy_group": "recovery"},
            "retired": {"status": "archived", "synergy_group": "recovery"},
        }
        dmc.store_habit_scores(YESTERDAY, self._details(), {}, {}, _profile(registry))
        assert stored(table, "habit_scores")[0]["synergy_groups"] == {"recovery": Decimal("1")}

    def test_a_write_failure_is_logged_and_does_not_abort_the_run(self, table, frozen_clock, monkeypatch):
        monkeypatch.setattr(table, "put_item", lambda **kw: (_ for _ in ()).throw(RuntimeError("boom")))
        dmc.store_habit_scores(YESTERDAY, self._details(), {}, {}, _profile())


# ──────────────────────────────────────────────────────────────────────────────
# Data-aware idempotency
# ──────────────────────────────────────────────────────────────────────────────


class TestFingerprints:
    def test_the_default_source_list_names_only_real_registered_sources(self, table):
        """Guard the SET: TB7-16 says 'add your new source here', so a typo would
        silently stop triggering recomputes for the source it was meant to cover.
        The expectation is derived from the ingestion registry, not a literal, so
        renaming a source there surfaces here instead of going quiet."""
        from ingestion import source_registry

        known = set(source_registry.SOURCE_REGISTRY)
        # Exercise the default list by seeding one row per registered source and
        # reading back which keys the default call actually fingerprints.
        for src in known:
            seed(table, _date_row(src, YESTERDAY, ingested_at="T"))
            seed(table, _row(src, f"DATE#{YESTERDAY}#WORKOUT#a", ingested_at="T"))
        used = set(dmc.get_source_fingerprints(YESTERDAY))
        assert used, "the default fingerprint list produced nothing"
        assert used <= known, f"unknown fingerprint sources: {sorted(used - known)}"

    def test_the_webhook_stamp_is_preferred_over_the_scheduled_one(self, table):
        seed(table, _date_row("whoop", YESTERDAY, webhook_ingested_at="B", ingested_at="A"))
        assert dmc.get_source_fingerprints(YESTERDAY, sources=["whoop"]) == {"whoop": "B"}

    def test_a_source_with_no_record_contributes_no_fingerprint(self, table):
        assert dmc.get_source_fingerprints(YESTERDAY, sources=["whoop"]) == {}

    def test_hevy_is_fingerprinted_from_its_newest_workout_of_the_day(self, table):
        """Hevy has no plain DATE# item — one row per workout — so a naive
        fetch_date would never see a late Hevy sync."""
        seed(
            table,
            _row("hevy", f"DATE#{YESTERDAY}#WORKOUT#a", ingested_at="2026-05-10T01:00:00Z"),
            _row("hevy", f"DATE#{YESTERDAY}#WORKOUT#b", ingested_at="2026-05-10T09:00:00Z"),
        )
        assert dmc.get_source_fingerprints(YESTERDAY, sources=["hevy"]) == {"hevy": "2026-05-10T09:00:00Z"}

    def test_a_hevy_day_with_no_workouts_yields_no_fingerprint(self, table):
        assert dmc._hevy_day_fingerprint(YESTERDAY) is None

    def test_a_failed_hevy_query_degrades_to_no_fingerprint(self, table):
        table.query_error = RuntimeError("throttled")
        assert dmc._hevy_day_fingerprint(YESTERDAY) is None

    def test_identical_fingerprints_mean_no_recompute(self):
        fps = {"whoop": "2026-05-10T09:00:00Z"}
        assert dmc.fingerprints_changed(fps, dict(fps)) is False

    def test_a_newer_source_timestamp_triggers_a_recompute(self):
        assert dmc.fingerprints_changed({"whoop": "2026-05-10T09:00:00Z"}, {"whoop": "2026-05-10T11:00:00Z"}) is True

    def test_a_source_appearing_for_the_first_time_triggers_a_recompute(self):
        assert dmc.fingerprints_changed({}, {"hevy": "2026-05-10T09:00:00Z"}) is True

    def test_an_older_timestamp_does_not_trigger_a_recompute(self):
        assert dmc.fingerprints_changed({"whoop": "2026-05-10T11:00:00Z"}, {"whoop": "2026-05-10T09:00:00Z"}) is False


# ──────────────────────────────────────────────────────────────────────────────
# Handler branches
# ──────────────────────────────────────────────────────────────────────────────


class TestLambdaHandler:
    def test_healthcheck_returns_before_touching_dynamodb(self, table, frozen_clock):
        assert dmc.lambda_handler({"healthcheck": True}, None)["statusCode"] == 200
        assert table.queries == [] and table.puts == []

    def test_an_unchanged_day_is_skipped_without_rewriting_the_record(self, table, frozen_clock):
        seed(
            table,
            _date_row(
                "computed_metrics",
                YESTERDAY,
                day_grade_letter="B",
                source_fingerprints={"whoop": "2026-05-10T09:00:00Z"},
            ),
            _date_row("whoop", YESTERDAY, ingested_at="2026-05-10T09:00:00Z"),
        )
        resp = dmc.lambda_handler({}, None)
        assert resp["skipped"] is True
        assert resp["day_grade_letter"] == "B"
        assert table.puts == []

    def test_the_target_date_defaults_to_yesterday_in_utc(self, table, frozen_clock):
        seed(
            table,
            _date_row("computed_metrics", YESTERDAY, day_grade_letter="B", source_fingerprints={"whoop": "T"}),
            _date_row("whoop", YESTERDAY, ingested_at="T"),
        )
        assert dmc.lambda_handler({}, None)["skipped"] is True

    def test_an_explicit_date_overrides_the_default(self, table, frozen_clock):
        seed(
            table,
            _date_row("computed_metrics", "2026-04-01", day_grade_letter="C", source_fingerprints={"whoop": "T"}),
            _date_row("whoop", "2026-04-01", ingested_at="T"),
        )
        assert dmc.lambda_handler({"date": "2026-04-01"}, None)["day_grade_letter"] == "C"

    def test_a_legacy_record_without_fingerprints_is_always_recomputed(self, table, frozen_clock, monkeypatch):
        seed(table, _date_row("computed_metrics", YESTERDAY, day_grade_letter="B"))
        monkeypatch.setattr(dmc, "fetch_profile", lambda: None)
        with pytest.raises(RuntimeError):
            dmc.lambda_handler({}, None)

    def test_force_bypasses_the_idempotency_check(self, table, frozen_clock, monkeypatch):
        seed(
            table,
            _date_row("computed_metrics", YESTERDAY, day_grade_letter="B", source_fingerprints={"whoop": "T"}),
            _date_row("whoop", YESTERDAY, ingested_at="T"),
        )
        monkeypatch.setattr(dmc, "fetch_profile", lambda: None)
        with pytest.raises(RuntimeError):
            dmc.lambda_handler({"force": True}, None)

    def test_a_missing_profile_raises_so_the_scheduled_failure_is_visible(self, table, frozen_clock, monkeypatch):
        """A returned dict on an async invocation counts as SUCCESS — no Errors
        metric, no DLQ, no alarm. It has to raise."""
        monkeypatch.setattr(dmc, "fetch_profile", lambda: None)
        with pytest.raises(RuntimeError, match="no profile"):
            dmc.lambda_handler({"force": True}, None)

    def test_a_sick_day_stores_a_sick_record_and_never_scores_the_day(self, table, frozen_clock, monkeypatch):
        monkeypatch.setattr(dmc, "fetch_profile", lambda: _profile())
        import health.sick_day_checker as sdc

        monkeypatch.setattr(sdc, "check_sick_day", lambda t, u, d: {"reason": "flu"})
        resp = dmc.lambda_handler({"force": True}, None)
        assert resp["day_grade_letter"] == "sick"
        item = stored(table, "computed_metrics")[0]
        assert item["sick_day"] is True
        assert item["sick_day_reason"] == "flu"
        assert item["readiness_colour"] == "gray"
        assert "day_grade_score" not in item

    def test_a_sick_day_preserves_the_previous_days_streaks(self, table, frozen_clock, monkeypatch):
        seed(
            table,
            _date_row(
                "computed_metrics",
                "2026-05-08",
                tier0_streak=Decimal("11"),
                tier01_streak=Decimal("7"),
                vice_streaks={"no_weed": Decimal("40")},
            ),
        )
        monkeypatch.setattr(dmc, "fetch_profile", lambda: _profile())
        import health.sick_day_checker as sdc

        monkeypatch.setattr(sdc, "check_sick_day", lambda t, u, d: {"reason": "flu"})
        resp = dmc.lambda_handler({"force": True}, None)
        assert (resp["tier0_streak"], resp["tier01_streak"]) == (11, 7)
        assert stored(table, "computed_metrics")[0]["vice_streaks"] == {"no_weed": Decimal("40")}

    def test_a_sick_day_write_failure_is_raised(self, table, frozen_clock, monkeypatch):
        monkeypatch.setattr(dmc, "fetch_profile", lambda: _profile())
        import health.sick_day_checker as sdc

        monkeypatch.setattr(sdc, "check_sick_day", lambda t, u, d: {"reason": "flu"})
        monkeypatch.setattr(table, "put_item", lambda **kw: (_ for _ in ()).throw(RuntimeError("boom")))
        with pytest.raises(RuntimeError):
            dmc.lambda_handler({"force": True}, None)


# ──────────────────────────────────────────────────────────────────────────────
# Data assembly
# ──────────────────────────────────────────────────────────────────────────────


class TestAssembleData:
    def test_an_empty_platform_assembles_without_inventing_numbers(self, table, frozen_clock):
        """ADR-104: nothing measured must produce None, not 0."""
        data, hrv_7d, hrv_30d = dmc.assemble_data(YESTERDAY, _profile())
        assert data["date"] == YESTERDAY
        assert (hrv_7d, hrv_30d) == (None, None)
        assert data["latest_weight"] is None
        assert data["week_ago_weight"] is None
        assert data["protein_g_avg"] is None
        assert data["recovery_pct"] is None
        assert data["diary_sessions"] == 0

    def test_hrv_baselines_average_their_own_windows(self, table, frozen_clock):
        seed(
            table,
            _date_row("whoop", "2026-05-08", hrv=Decimal("50")),
            _date_row("whoop", "2026-05-09", hrv=Decimal("60")),
            _date_row("whoop", "2026-04-20", hrv=Decimal("100")),  # inside 30d, outside 7d
        )
        data, hrv_7d, hrv_30d = dmc.assemble_data(YESTERDAY, _profile())
        assert hrv_7d == 55.0
        assert hrv_30d == 70.0
        assert data["hrv"] == {"hrv_7d": 55.0, "hrv_30d": 70.0, "hrv_yesterday": 60.0}

    def test_canonical_vitals_come_from_the_scored_days_whoop_record(self, table, frozen_clock):
        seed(table, _date_row("whoop", YESTERDAY, recovery_score=Decimal("62"), hrv=Decimal("55.4"), resting_heart_rate=Decimal("58")))
        data, _, _ = dmc.assemble_data(YESTERDAY, _profile())
        assert (data["recovery_pct"], data["hrv_ms"], data["rhr_bpm"]) == (62.0, 55.4, 58.0)
        assert data["hrv"]["hrv_yesterday"] == 55.4

    def test_sleep_debt_counts_only_shortfalls_against_the_profile_target(self, table, frozen_clock):
        seed(
            table,
            _date_row("whoop", "2026-05-08", sleep_duration_hours=Decimal("6.0")),
            _date_row("whoop", "2026-05-09", sleep_duration_hours=Decimal("9.0")),
        )
        data, _, _ = dmc.assemble_data(YESTERDAY, _profile(sleep_target_hours_ideal=7.5))
        assert data["sleep_debt_7d_hrs"] == 1.5  # a long night does not repay a short one

    def test_an_unmeasured_night_adds_no_fabricated_sleep_debt(self, table, frozen_clock):
        seed(table, _date_row("whoop", "2026-05-08", recovery_score=Decimal("60")))
        data, _, _ = dmc.assemble_data(YESTERDAY, _profile(sleep_target_hours_ideal=7.5))
        assert data["sleep_debt_7d_hrs"] == 0

    def test_latest_weight_falls_back_through_the_fourteen_and_thirty_day_windows(self, table, frozen_clock):
        """#783: sporadic weigh-ins are routine; a 7-day-only lookback takes the
        headline metric dark and trips false-positive canary alarms."""
        seed(table, _date_row("withings", "2026-04-18", weight_lbs=Decimal("321.6")))
        data, _, _ = dmc.assemble_data(YESTERDAY, _profile())
        assert data["latest_weight"] == 321.6
        assert data["avatar_weight"] == 321.6

    def test_the_protein_window_average_is_the_one_number_every_surface_reads(self, table, frozen_clock):
        seed(
            table,
            _date_row("macrofactor", "2026-05-08", total_protein_g=Decimal("140")),
            _date_row("macrofactor", "2026-05-09", total_protein_g=Decimal("160")),
        )
        data, _, _ = dmc.assemble_data(YESTERDAY, _profile(protein_target_g=190, protein_floor_g=170))
        assert data["protein_g_avg"] == 150.0
        assert (data["protein_g_target"], data["protein_g_floor"]) == (190.0, 170.0)

    def test_strava_multi_device_duplicates_are_collapsed_and_totals_restated(self, table, frozen_clock):
        acts = [
            {"start_date_local": "2026-05-09T08:00:00", "sport_type": "Run", "distance_meters": 8000, "moving_time_seconds": 2400},
            {"start_date_local": "2026-05-09T08:05:00", "sport_type": "Run", "distance_meters": 0, "moving_time_seconds": 100},
        ]
        seed(table, _date_row("strava", YESTERDAY, activities=acts, activity_count=2))
        data, _, _ = dmc.assemble_data(YESTERDAY, _profile())
        assert data["strava"]["activity_count"] == 1
        assert data["strava"]["total_moving_time_seconds"] == 2400

    def test_the_diary_session_count_rides_the_assembled_data(self, table, frozen_clock):
        channel = sorted(dmc._DIARY_CHANNELS)[0]
        seed(table, _row("notion", f"DATE#{YESTERDAY}#journal#1", channel=channel))
        data, _, _ = dmc.assemble_data(YESTERDAY, _profile())
        assert data["diary_sessions"] == 1
        assert len(data["journal_entries"]) == 1

    # FIXED by #2299 (2026-08-09) — marker removed, this is now a real assertion.
    # The tranche-2 record said this module "diverges" from daily_brief and
    # dashboard_refresh, implying two implementations to reconcile. The truth was
    # narrower and the fix better: the compute Lambda's `next(...)` over an ASCENDING
    # 14-day window was simply WRONG (it took the OLDEST weigh-in, so the published
    # weekly delta was a two-week delta), and the brief was already right. Rather than
    # align two copies, #2299 lifted ONE definition into intelligence.weight_recency and
    # pointed both at it — which is why this stopped xfailing without anyone editing it.
    #
    # It survived one full session as a strict=False XPASS, which reports as a pass and
    # is therefore invisible: `-rX` is what surfaces it. Worth remembering that a
    # non-strict marker left behind by someone else's fix is silent debt.
    def test_week_ago_weight_is_the_reading_nearest_seven_days_ago(self, table, frozen_clock):
        seed(
            table,
            _date_row("withings", "2026-04-27", weight_lbs=Decimal("330.0")),  # 13 days back
            _date_row("withings", "2026-05-03", weight_lbs=Decimal("322.0")),  # 7 days back
            _date_row("withings", "2026-05-09", weight_lbs=Decimal("318.0")),  # latest
        )
        data, _, _ = dmc.assemble_data(YESTERDAY, _profile())
        assert data["latest_weight"] == 318.0
        assert data["week_ago_weight"] == 322.0


# ──────────────────────────────────────────────────────────────────────────────
# Ledger sweeps — fail-soft contract
# ──────────────────────────────────────────────────────────────────────────────


class TestLedgerSweeps:
    def test_an_achievement_sweep_failure_never_fails_the_metrics_run(self, table, frozen_clock, monkeypatch):
        monkeypatch.setattr(
            dmc.achievement_rules, "collect_inputs", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("badge engine down"))
        )
        assert dmc.sweep_achievement_first_earns(_profile()) == 0

    def test_the_achievement_sweep_reports_how_many_first_earns_it_wrote(self, table, frozen_clock, monkeypatch):
        written = [{"badge_id": "lost_10", "label": "Lost 10", "earned_date": "2026-05-01", "date_basis": "withings"}]
        monkeypatch.setattr(dmc.achievement_rules, "collect_inputs", lambda *a, **kw: {})
        monkeypatch.setattr(dmc.achievement_rules, "signals_from", lambda i: {})
        monkeypatch.setattr(dmc.achievement_rules, "read_first_earns", lambda *a, **kw: {})
        monkeypatch.setattr(dmc.achievement_rules, "histories_from", lambda i: {})
        monkeypatch.setattr(dmc.achievement_rules, "persist_first_earns", lambda *a, **kw: written)
        assert dmc.sweep_achievement_first_earns(_profile()) == 1

    def test_a_milestone_sweep_failure_never_fails_the_metrics_run(self, table, frozen_clock, monkeypatch):
        monkeypatch.setattr(dmc.milestone_ledger, "sweep", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("ledger down")))
        assert dmc.sweep_milestone_ledger() == 0

    def test_only_announced_milestones_are_counted_not_deferred_ones(self, table, frozen_clock, monkeypatch):
        result = {
            "genesis": False,
            "written": [],
            "announced": [{"milestone_id": "m1", "label": "L", "event_date": "2026-05-09", "measurement": {}}],
            "deferred": ["m2"],
            "cooldown_active": True,
            "suppressed": False,
        }
        monkeypatch.setattr(dmc.milestone_ledger, "sweep", lambda *a, **kw: result)
        assert dmc.sweep_milestone_ledger() == 1

    def test_a_genesis_run_consumes_rungs_without_announcing_them(self, table, frozen_clock, monkeypatch):
        """A first run must not congratulate on a year of already-true rungs."""
        result = {
            "genesis": True,
            "written": [{"milestone_id": "m1"}, {"milestone_id": "m2"}],
            "announced": [],
            "deferred": [],
            "cooldown_active": False,
            "suppressed": False,
        }
        monkeypatch.setattr(dmc.milestone_ledger, "sweep", lambda *a, **kw: result)
        assert dmc.sweep_milestone_ledger() == 0

    def test_the_spiral_breaker_holds_announcements_without_consuming_them(self, table, frozen_clock, monkeypatch):
        """#1627/#1628: during a suspected downturn we check in, not congratulate."""
        result = {
            "genesis": False,
            "written": [],
            "announced": [],
            "deferred": ["m1"],
            "cooldown_active": False,
            "suppressed": True,
        }
        monkeypatch.setattr(dmc.milestone_ledger, "sweep", lambda *a, **kw: result)
        assert dmc.sweep_milestone_ledger() == 0


# ──────────────────────────────────────────────────────────────────────────────
# Handler — the full scored day
# ──────────────────────────────────────────────────────────────────────────────


class TestHandlerFullRun:
    @pytest.fixture
    def scored_day(self, table, frozen_clock, monkeypatch):
        monkeypatch.setattr(dmc, "fetch_profile", lambda: _profile({"sleep": {"status": "active", "tier": 0}}))
        monkeypatch.setattr(dmc, "sweep_achievement_first_earns", lambda profile: 2)
        monkeypatch.setattr(dmc, "sweep_milestone_ledger", lambda: 1)
        monkeypatch.setattr(
            dmc.scoring_engine,
            "compute_day_grade",
            lambda data, profile: (
                82.0,
                "B",
                {"sleep": 80, "habits_mvp": 90},
                {
                    "habits_mvp": {
                        "composite_method": "tier_weighted",
                        "tier0": {"done": 1, "total": 1},
                        "tier1": {"done": 0, "total": 0},
                        "vices": {"held": 0, "total": 0},
                        "tier_status": {0: {"sleep": True}},
                    }
                },
            ),
        )
        seed(
            table,
            _date_row("whoop", YESTERDAY, recovery_score=Decimal("85"), hrv=Decimal("55"), ingested_at="2026-05-10T09:00:00Z"),
            _date_row("habitify", YESTERDAY, habits={"sleep": 1}),
        )
        return table

    def test_a_scored_day_writes_all_three_partitions(self, scored_day):
        dmc.lambda_handler({"force": True}, None)
        assert len(stored(scored_day, "computed_metrics")) == 1
        assert len(stored(scored_day, "day_grade")) == 1
        assert len(stored(scored_day, "habit_scores")) == 1

    def test_the_response_carries_the_grade_readiness_and_sweep_counts(self, scored_day):
        resp = dmc.lambda_handler({"force": True}, None)
        assert resp["statusCode"] == 200
        assert (resp["day_grade_score"], resp["day_grade_letter"]) == (82.0, "B")
        # colour must agree with the score's own band, not a hand-typed literal
        bands = {"green": (80, 101), "yellow": (60, 80), "red": (0, 60)}
        lo, hi = bands[resp["readiness_colour"]]
        assert lo <= resp["readiness_score"] < hi
        assert resp["tier0_streak"] == 1
        assert (resp["first_earns_written"], resp["milestones_announced"]) == (2, 1)

    def test_the_stored_record_carries_the_fingerprints_the_next_run_compares(self, scored_day):
        dmc.lambda_handler({"force": True}, None)
        assert stored(scored_day, "computed_metrics")[0]["source_fingerprints"] == {"whoop": "2026-05-10T09:00:00Z"}

    def test_an_unscoreable_day_still_writes_computed_metrics_but_no_day_grade(self, scored_day, monkeypatch):
        monkeypatch.setattr(dmc.scoring_engine, "compute_day_grade", lambda data, profile: (None, "-", {}, {}))
        resp = dmc.lambda_handler({"force": True}, None)
        assert resp["day_grade_score"] is None
        assert len(stored(scored_day, "computed_metrics")) == 1
        assert stored(scored_day, "day_grade") == []
