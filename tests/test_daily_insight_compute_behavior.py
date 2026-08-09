#!/usr/bin/env python3
"""tests/test_daily_insight_compute_behavior.py — behavioral contracts of
`lambdas/compute/daily_insight_compute_lambda.py`.

Part of #1658 tranche 2. This Lambda is the sole writer of the
`computed_insights` partition, whose `ai_context_block` is injected verbatim
into every Daily Brief AI call and every coach prompt. A wrong signal here is
not a wrong number on a page — it is a sentence a coach says out loud.

The contracts under test, outward from the pure functions:

  * the window reads honour the per-source phase class (#2109) — derived from
    the taxonomy, never a literal source list,
  * ADR-105 rigor: a drift below the effect floor, below the significance bar,
    or below the sample floor must NOT be published; every published claim
    carries n and p,
  * ADR-104 honesty: absence is absence — an empty registry, an empty window
    or an absent journal must not become a fabricated insight,
  * ranking/selection: priority ordering, budget enforcement, caps, ties,
  * Decimal/JSON conversion before the DynamoDB write,
  * fail-soft boundaries: a failed sub-computation must not abort the run.

Time is frozen everywhere `datetime.now` is reachable — no fixture date is
ever combined with the real clock.
"""

import ast
import inspect
import json
import os
import re
import statistics
import sys
import textwrap
from datetime import date, datetime, timedelta, timezone
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
    import daily_insight_compute_lambda as di
    from experiment.phase_filter import source_reads_cross_phase
except ImportError as _e:  # pragma: no cover — only when the bundle layout changes
    _import_err = _e
    di = None  # type: ignore

if _import_err is not None:  # pragma: no cover
    pytestmark = pytest.mark.skip(reason=f"daily_insight_compute_lambda unavailable: {_import_err}")  # type: ignore


FROZEN_NOW = datetime(2026, 5, 10, 17, 42, 0, tzinfo=timezone.utc)
TODAY = "2026-05-10"
YESTERDAY = "2026-05-09"
YEST_D = date(2026, 5, 9)


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


@pytest.fixture(autouse=True)
def frozen_clock(monkeypatch):
    monkeypatch.setattr(di, "datetime", _FrozenDatetime)
    return FROZEN_NOW


# ──────────────────────────────────────────────────────────────────────────────
# Test doubles — hand-rolled and bounded (never a MagicMock in a paging loop)
# ──────────────────────────────────────────────────────────────────────────────


def _cond_terms(cond, out):
    """Flatten a boto3 `Key(...)` condition tree into (attr, operator, values)."""
    expr = cond.get_expression()
    op = expr["operator"]
    vals = expr["values"]
    if op == "AND":
        for v in vals:
            _cond_terms(v, out)
        return
    out.append((getattr(vals[0], "name", None), op, list(vals[1:])))


class FakeTable:
    """DynamoDB Table stand-in keyed the way this module keys the real table.

    `items` maps (pk, sk) → item. `query()` honours every shape the module
    issues — the `sk BETWEEN` string form, `begins_with(sk, :prefix)`, the
    bare `pk = :pk` (Todoist), and the two boto3 `Key(...)` condition objects
    (prior guidance, weekly correlations) — plus ScanIndexForward/Limit and the
    experiments `#st = :active` filter. Every call's kwargs are recorded so a
    test can assert on the phase FilterExpression and the window boundaries.
    """

    def __init__(self, items=None):
        self.items = dict(items or {})
        self.puts = []
        self.queries = []
        self.get_errors = set()
        self.put_errors = set()
        self.query_error = None
        self.pages = None  # optional list of LastEvaluatedKey-chained pages

    # -- writes --
    def put_item(self, Item=None, **kwargs):
        if Item["pk"] in self.put_errors:
            raise RuntimeError("put throttled")
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

        kce = kwargs.get("KeyConditionExpression")
        vals = kwargs.get("ExpressionAttributeValues", {}) or {}
        pk = lo = hi = prefix = None
        if isinstance(kce, str):
            pk = vals.get(":pk")
            lo, hi = vals.get(":s"), vals.get(":e")
            prefix = vals.get(":prefix") or vals.get(":sk")
        elif kce is not None:
            terms = []
            _cond_terms(kce, terms)
            for name, op, vs in terms:
                if name != "pk" and op == "=":
                    continue
                if name == "pk":
                    pk = vs[0]
                elif op == "BETWEEN":
                    lo, hi = vs[0], vs[1]
                elif op == "begins_with":
                    prefix = vs[0]

        rows = [v for (p, _s), v in self.items.items() if p == pk]
        if lo is not None and hi is not None:
            rows = [r for r in rows if lo <= r["sk"] <= hi]
        if prefix:
            rows = [r for r in rows if str(r["sk"]).startswith(prefix)]
        if ":active" in vals:
            rows = [r for r in rows if r.get("status") == vals[":active"]]
        rows.sort(key=lambda r: r["sk"], reverse=kwargs.get("ScanIndexForward", True) is False)
        limit = kwargs.get("Limit")
        if limit:
            rows = rows[:limit]
        return {"Items": rows}


@pytest.fixture
def table(monkeypatch):
    t = FakeTable()
    monkeypatch.setattr(di, "table", t)
    return t


def _row(source, sk, **fields):
    return {"pk": di.USER_PREFIX + source, "sk": sk, **fields}


def _date_row(source, date_str, **fields):
    return _row(source, "DATE#" + date_str, date=date_str, **fields)


def seed(table, *rows):
    for r in rows:
        table.items[(r["pk"], r["sk"])] = r


def _days(anchor, back):
    """ISO date `back` days before `anchor` (a `date`)."""
    return (anchor - timedelta(days=back)).isoformat()


class WindowFetcher:
    """A bounded `fetch_range` stand-in that answers per (source, start, end).

    Registered windows return their records; anything unregistered returns [].
    Every call is recorded so a test can assert the window boundaries the
    module actually asked for (the TB7-22 equal-window contract).
    """

    def __init__(self):
        self.windows = {}
        self.calls = []

    def register(self, source, start, end, records):
        self.windows[(source, start, end)] = records

    def __call__(self, source, start, end):
        self.calls.append((source, start, end))
        return list(self.windows.get((source, start, end), []))


# ──────────────────────────────────────────────────────────────────────────────
# Hand-derived slow-drift arithmetic (see the class docstring below)
# ──────────────────────────────────────────────────────────────────────────────
#
# Baseline window: [50, 54] repeated 7× → n=14, mean 52.0, Σ(x-x̄)² = 14·4 = 56,
# sample variance 56/13 = 4.3076923…, sd = √(56/13) = 2.0754980866510833.
# The strict alternation makes the lag-1 autocorrelation ≈ −1, so the
# effective-n clamp `max(2, min(n, n(1−ρ)/(1+ρ)))` pins n_eff at exactly n = 14
# — which makes the SE (and therefore z) closed-form:
#     SE = √(2 · (56/13) / 14) = √(8/13) = 0.7844645405527362
#     z  = (recent_mean − 52.0) / SE
#     effect = (recent_mean − 52.0) / √(56/13)
_BASE_SD = 2.0754980866510833
_BASE_SE = 0.7844645405527362


def _alt(mean_val):
    """14 alternating points ±2 about `mean_val` — same sd/n_eff as the baseline."""
    return [mean_val - 2.0, mean_val + 2.0] * 7


# ──────────────────────────────────────────────────────────────────────────────
# DDB read helpers
# ──────────────────────────────────────────────────────────────────────────────


class TestFetchHelpers:
    def test_fetch_date_returns_a_decimal_free_record(self, table):
        seed(table, _date_row("whoop", YESTERDAY, hrv=Decimal("55.5")))
        rec = di.fetch_date("whoop", YESTERDAY)
        assert rec["hrv"] == 55.5
        assert not isinstance(rec["hrv"], Decimal)

    def test_fetch_date_is_none_for_a_missing_day(self, table):
        assert di.fetch_date("whoop", YESTERDAY) is None

    def test_fetch_date_degrades_to_none_on_a_read_failure(self, table):
        """Fail-soft: a throttled read must not abort the whole compute."""
        table.get_errors.add(di.USER_PREFIX + "whoop")
        assert di.fetch_date("whoop", YESTERDAY) is None

    def test_fetch_range_is_bounded_by_the_requested_dates(self, table):
        seed(
            table,
            _date_row("whoop", "2026-05-01", hrv=Decimal("40")),
            _date_row("whoop", "2026-05-05", hrv=Decimal("50")),
            _date_row("whoop", "2026-05-09", hrv=Decimal("60")),
        )
        assert [r["hrv"] for r in di.fetch_range("whoop", "2026-05-03", "2026-05-09")] == [50.0, 60.0]

    def test_fetch_range_follows_pagination_to_the_last_page(self, table):
        """A truncated window silently shortens every trailing baseline."""
        table.pages = [
            {"Items": [_date_row("whoop", "2026-05-01", hrv=Decimal("40"))], "LastEvaluatedKey": {"pk": "x", "sk": "y"}},
            {"Items": [_date_row("whoop", "2026-05-02", hrv=Decimal("41"))]},
        ]
        assert len(di.fetch_range("whoop", "2026-05-01", "2026-05-09")) == 2

    def test_fetch_range_degrades_to_an_empty_window_on_a_query_failure(self, table):
        table.query_error = RuntimeError("throttled")
        assert di.fetch_range("whoop", "2026-05-01", "2026-05-09") == []

    @pytest.mark.parametrize(
        "source",
        # The SET is every source this module actually reads through fetch_range,
        # plus one deliberately unclassified name (a user-defined experiment
        # metric's source, which must keep the current-cycle filter).
        [
            "whoop",
            "withings",
            "macrofactor",
            "apple_health",
            "eightsleep",
            "supplements",
            "day_grade",
            "computed_metrics",
            "habit_scores",
            "zzz_user_defined_metric",
        ],
    )
    def test_the_phase_filter_is_applied_exactly_when_the_taxonomy_says_so(self, table, source):
        """#2109: include_pilot is derived per source, never hard-coded — so a
        source that changes class cannot leave this test asserting the old answer."""
        di.fetch_range(source, "2026-05-01", "2026-05-09")
        applied = "FilterExpression" in table.queries[-1]
        assert applied is not source_reads_cross_phase(
            source
        ), f"{source}: cross_phase={source_reads_cross_phase(source)} but filter present={applied}"

    def test_the_phase_parametrisation_still_exercises_both_branches(self):
        """Guard against the test above degenerating: the read set must keep at
        least one cross-phase source (a body timeseries) and one scoped source
        (derived intelligence the reset tombstones)."""
        read_sources = [
            "whoop",
            "withings",
            "macrofactor",
            "apple_health",
            "eightsleep",
            "supplements",
            "day_grade",
            "computed_metrics",
            "habit_scores",
        ]
        classes = {source_reads_cross_phase(s) for s in read_sources}
        assert classes == {True, False}

    def test_memory_records_are_read_newest_first_within_the_category_window(self, table):
        for d in ("2026-04-20", "2026-05-01", "2026-05-08"):
            seed(table, _row("platform_memory", f"MEMORY#what_worked#{d}", note=d))
        recs = di.fetch_memory_records("what_worked", days=30)
        assert [r["note"] for r in recs] == ["2026-05-08", "2026-05-01", "2026-04-20"]

    def test_memory_records_are_bounded_by_the_requested_lookback(self, table):
        """`days=30` from the frozen clock excludes anything older."""
        seed(
            table,
            _row("platform_memory", "MEMORY#what_worked#2026-03-01", note="old"),
            _row("platform_memory", "MEMORY#what_worked#2026-05-01", note="new"),
        )
        assert [r["note"] for r in di.fetch_memory_records("what_worked", days=30)] == ["new"]

    def test_memory_records_degrade_to_empty_on_failure(self, table):
        table.query_error = RuntimeError("throttled")
        assert di.fetch_memory_records("what_worked") == []

    def test_journal_entries_are_fetched_under_the_dated_journal_prefix(self, table):
        seed(
            table,
            _row("notion", f"DATE#{YESTERDAY}#journal#1", todays_intention="a"),
            _row("notion", f"DATE#{YESTERDAY}#journal#2", todays_intention="b"),
            _row("notion", f"DATE#{TODAY}#journal#3", todays_intention="c"),
        )
        assert len(di._fetch_journal_for_date(YESTERDAY)) == 2

    def test_journal_fetch_degrades_to_an_empty_list_on_failure(self, table):
        table.query_error = RuntimeError("throttled")
        assert di._fetch_journal_for_date(YESTERDAY) == []

    def test_the_profile_read_uses_the_one_canonical_profile_key(self, table):
        seed(table, {"pk": di.PROFILE_PK, "sk": "PROFILE#v1", "calorie_target": Decimal("1750")})
        assert di.fetch_profile()["calorie_target"] == 1750.0

    def test_a_missing_profile_is_an_empty_dict_not_a_crash(self, table):
        assert di.fetch_profile() == {}


# ──────────────────────────────────────────────────────────────────────────────
# Momentum
# ──────────────────────────────────────────────────────────────────────────────


def _grade(date_str, score, field="total_score"):
    return {"date": date_str, field: score}


class TestComputeMomentum:
    def test_week_averages_are_split_at_the_seven_day_boundary(self):
        """The boundary is `yesterday - 7`, exclusive of the previous week."""
        recs = [_grade("2026-05-08", 90), _grade("2026-05-07", 80), _grade("2026-05-01", 60), _grade("2026-04-30", 60)]
        signal, this_avg, prev_avg, trend = di.compute_momentum(recs, YESTERDAY, {})
        assert (this_avg, prev_avg) == (85.0, 60.0)

    def test_the_trend_percent_is_the_week_over_week_change_of_the_averages(self):
        """(85 - 60) / 60 * 100 = 41.666… → 41.7."""
        recs = [_grade("2026-05-08", 90), _grade("2026-05-07", 80), _grade("2026-05-01", 60), _grade("2026-04-30", 60)]
        signal, _t, _p, trend = di.compute_momentum(recs, YESTERDAY, {})
        assert trend == 41.7
        assert signal == "improving"

    def test_an_empty_history_reports_unknown_rather_than_a_neutral_score(self):
        """ADR-104: no grades is not a stable week."""
        assert di.compute_momentum([], YESTERDAY, {}) == ("unknown", None, None, None)

    def test_a_first_week_with_no_prior_week_is_stable_with_no_invented_trend(self):
        signal, this_avg, prev_avg, trend = di.compute_momentum([_grade("2026-05-08", 70)], YESTERDAY, {})
        assert (signal, this_avg, prev_avg, trend) == ("stable", 70.0, None, None)

    def test_the_fallback_band_is_plus_or_minus_five_percent_when_no_personal_band_exists(self):
        """80 → 84 is +5.0%, exactly ON the band edge, so still stable."""
        recs = [_grade("2026-05-08", 84), _grade("2026-05-01", 80)]
        assert di.compute_momentum(recs, YESTERDAY, {})[0] == "stable"

    def test_a_move_past_the_fallback_band_is_labelled_declining(self):
        """80 → 75 is -6.25%, below the -5% fallback floor."""
        recs = [_grade("2026-05-08", 75), _grade("2026-05-01", 80)]
        signal, _t, _p, trend = di.compute_momentum(recs, YESTERDAY, {})
        assert (signal, trend) == ("declining", -6.2)

    def test_a_personal_band_that_cleared_the_sample_floor_overrides_the_fallback(self):
        """ADR-105 r4: with n≥30 the cutoffs come from Matthew's own swings."""
        recs = [_grade("2026-05-08", 84), _grade("2026-05-01", 80)]
        wide = {"grade_trend_pct": {"lo": -20.0, "hi": 20.0, "n": 40}}
        narrow = {"grade_trend_pct": {"lo": -1.0, "hi": 1.0, "n": 40}}
        assert di.compute_momentum(recs, YESTERDAY, wide)[0] == "stable"
        assert di.compute_momentum(recs, YESTERDAY, narrow)[0] == "improving"

    def test_a_personal_band_below_the_sample_floor_does_not_override_the_fallback(self):
        """n=5 must not be allowed to redefine what 'improving' means."""
        recs = [_grade("2026-05-08", 84), _grade("2026-05-01", 80)]
        thin = {"grade_trend_pct": {"lo": -1.0, "hi": 1.0, "n": 5}}
        assert di.compute_momentum(recs, YESTERDAY, thin)[0] == "stable"

    def test_the_score_is_read_from_either_the_day_grade_or_computed_metrics_field_name(self):
        """`day_grade` writes total_score; computed_metrics writes day_grade_score."""
        by_total = di.compute_momentum([_grade("2026-05-08", 70, "total_score")], YESTERDAY, {})
        by_dgs = di.compute_momentum([_grade("2026-05-08", 70, "day_grade_score")], YESTERDAY, {})
        assert by_total[1] == by_dgs[1] == 70.0

    def test_records_with_no_score_are_skipped_rather_than_counted_as_zero(self):
        recs = [_grade("2026-05-08", 90), {"date": "2026-05-07"}]
        assert di.compute_momentum(recs, YESTERDAY, {})[1] == 90.0


# ──────────────────────────────────────────────────────────────────────────────
# Metric trend detection
# ──────────────────────────────────────────────────────────────────────────────


def _cm(date_str, **fields):
    comp = {k: v for k, v in fields.items() if k in ("sleep_quality", "recovery", "nutrition", "movement", "habits_mvp", "journal")}
    top = {k: v for k, v in fields.items() if k not in comp}
    return {"date": date_str, "component_scores": comp, **top}


class TestDetectMetricTrends:
    def test_three_falling_readings_are_reported_as_a_declining_run(self):
        recs = [_cm("2026-05-06", readiness_score=80), _cm("2026-05-07", readiness_score=70), _cm("2026-05-08", readiness_score=60)]
        declining, improving = di.detect_metric_trends(recs)
        assert [d["metric"] for d in declining] == ["readiness_score"]
        assert improving == []

    def test_the_declining_delta_and_baseline_are_the_hand_computed_values(self):
        """current 60, first-of-run 80 → (60-80)/80*100 = -25.0; 7d avg (80+70+60)/3 = 70.0."""
        recs = [_cm("2026-05-06", readiness_score=80), _cm("2026-05-07", readiness_score=70), _cm("2026-05-08", readiness_score=60)]
        d = di.detect_metric_trends(recs)[0][0]
        assert (d["delta_pct"], d["baseline_7d_avg"], d["current"]) == (-25.0, 70.0, 60)

    def test_three_rising_readings_are_reported_as_an_improving_run(self):
        recs = [_cm("2026-05-06", readiness_score=60), _cm("2026-05-07", readiness_score=70), _cm("2026-05-08", readiness_score=80)]
        declining, improving = di.detect_metric_trends(recs)
        assert declining == [] and [i["metric"] for i in improving] == ["readiness_score"]

    def test_a_plateau_inside_the_run_breaks_it_in_both_directions(self):
        """Equality is neither strictly rising nor strictly falling."""
        recs = [_cm("2026-05-06", readiness_score=70), _cm("2026-05-07", readiness_score=70), _cm("2026-05-08", readiness_score=60)]
        assert di.detect_metric_trends(recs) == ([], [])

    def test_only_the_last_three_readings_decide_the_run(self):
        """A four-day slide that ends flat is not a declining run."""
        recs = [
            _cm("2026-05-05", readiness_score=90),
            _cm("2026-05-06", readiness_score=80),
            _cm("2026-05-07", readiness_score=70),
            _cm("2026-05-08", readiness_score=70),
        ]
        assert di.detect_metric_trends(recs)[0] == []

    def test_fewer_than_three_readings_produces_no_claim(self):
        """ADR-105: the run length IS the claim — two points cannot support it."""
        recs = [_cm("2026-05-07", readiness_score=80), _cm("2026-05-08", readiness_score=60)]
        assert di.detect_metric_trends(recs) == ([], [])

    def test_component_scores_are_read_from_the_nested_map_not_the_top_level(self):
        recs = [_cm("2026-05-06", recovery=80), _cm("2026-05-07", recovery=70), _cm("2026-05-08", recovery=60)]
        assert [d["metric"] for d in di.detect_metric_trends(recs)[0]] == ["recovery"]

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "DEFECT (tranche-2 discovery): detect_metric_trends hard-codes "
            "consecutive_days=3 on the last three RECORDS without checking that "
            "their dates are adjacent. A window with gaps (e.g. 05-01/05-05/05-09) "
            "publishes 'declining 3 days' — and build_ai_context_block renders that "
            "literally as 'LEADING INDICATOR: … declining 3 days'."
        ),
    )
    def test_a_run_spanning_gaps_does_not_claim_three_consecutive_days(self):
        recs = [_cm("2026-05-01", readiness_score=80), _cm("2026-05-05", readiness_score=70), _cm("2026-05-09", readiness_score=60)]
        declining, _ = di.detect_metric_trends(recs)
        assert declining == [], "a gapped window must not be published as a 3-day consecutive run"


# ──────────────────────────────────────────────────────────────────────────────
# Habit patterns
# ──────────────────────────────────────────────────────────────────────────────


def _registry(*names, tier=0, status="active"):
    return {"habit_registry": {n: {"tier": tier, "status": status} for n in names}}


def _hs(date_str, missed=None, **fields):
    rec = {"date": date_str, **fields}
    if missed is not None:
        rec["missed_tier0"] = missed
    return rec


class TestComputeHabitPatterns:
    def test_the_miss_rate_is_missed_days_over_days_in_the_window(self):
        """'water' missed 2 of 4 days → 0.5."""
        recs = [_hs("2026-05-0%d" % i, missed=(["water"] if i <= 2 else [])) for i in (1, 2, 3, 4)]
        miss_rates, _s, _w, _sy = di.compute_habit_patterns(recs, _registry("water"))
        assert miss_rates == {"water": 0.5}

    def test_an_empty_registry_produces_no_habit_claims_at_all(self):
        """ADR-104: an unconfigured registry is absence, not perfect adherence."""
        recs = [_hs("2026-05-01", missed=["water"])]
        assert di.compute_habit_patterns(recs, {}) == ({}, [], [], {})

    def test_an_empty_window_produces_no_habit_claims_at_all(self):
        assert di.compute_habit_patterns([], _registry("water")) == ({}, [], [], {})

    def test_a_habit_at_or_above_eighty_percent_completion_is_strong(self):
        """Missed 1 of 5 → 0.8, exactly on the inclusive threshold."""
        recs = [_hs("2026-05-0%d" % i, missed=(["water"] if i == 1 else [])) for i in range(1, 6)]
        _m, strongest, weakest, _sy = di.compute_habit_patterns(recs, _registry("water"))
        assert strongest == ["water"] and weakest == []

    def test_a_habit_at_or_below_forty_percent_completion_is_weak(self):
        """Missed 3 of 5 → 0.4, exactly on the inclusive threshold."""
        recs = [_hs("2026-05-0%d" % i, missed=(["water"] if i <= 3 else [])) for i in range(1, 6)]
        _m, strongest, weakest, _sy = di.compute_habit_patterns(recs, _registry("water"))
        assert weakest == ["water"] and strongest == []

    def test_only_active_tier_zero_habits_are_ranked(self):
        recs = [_hs("2026-05-01", missed=[])]
        profile = {
            "habit_registry": {
                "core": {"tier": 0, "status": "active"},
                "paused": {"tier": 0, "status": "paused"},
                "tier_one": {"tier": 1, "status": "active"},
            }
        }
        _m, strongest, _w, _sy = di.compute_habit_patterns(recs, profile)
        assert strongest == ["core"]

    def test_the_strongest_and_weakest_lists_are_capped_at_five(self):
        names = [f"h{i}" for i in range(8)]
        recs = [_hs("2026-05-01", missed=[])]
        _m, strongest, _w, _sy = di.compute_habit_patterns(recs, _registry(*names))
        assert len(strongest) == 5

    def test_synergy_health_is_the_mean_of_each_group_across_the_window(self):
        """(0.4 + 0.8) / 2 = 0.6."""
        recs = [
            _hs("2026-05-01", missed=[], synergy_groups={"evening": 0.4}),
            _hs("2026-05-02", missed=[], synergy_groups={"evening": 0.8}),
        ]
        _m, _s, _w, synergy = di.compute_habit_patterns(recs, _registry("x"))
        assert synergy == {"evening": 0.6}

    def test_a_day_with_no_missed_list_still_counts_toward_the_denominator(self):
        """The writer strips `missed_tier0` on a perfect day — that day is still a day."""
        recs = [_hs("2026-05-01", missed=["water"]), _hs("2026-05-02")]
        miss_rates, _s, _w, _sy = di.compute_habit_patterns(recs, _registry("water"))
        assert miss_rates == {"water": 0.5}


# ──────────────────────────────────────────────────────────────────────────────
# Platform memory context
# ──────────────────────────────────────────────────────────────────────────────


class TestBuildMemoryContext:
    def test_no_memory_records_produce_an_empty_context_not_a_placeholder(self, table):
        """ADR-104: an empty memory must not become an invented coaching note."""
        assert di.build_memory_context() == ""

    def test_only_the_most_recent_calibration_note_is_surfaced(self, table):
        seed(
            table,
            _row("platform_memory", "MEMORY#coaching_calibration#2026-05-01", note="older"),
            _row("platform_memory", "MEMORY#coaching_calibration#2026-05-08", note="newest"),
        )
        ctx = di.build_memory_context()
        assert "COACHING CALIBRATION: newest" in ctx and "older" not in ctx

    def test_a_structured_calibration_note_is_serialised_rather_than_dropped(self, table):
        seed(table, _row("platform_memory", "MEMORY#coaching_calibration#2026-05-08", note={"tone": "direct"}))
        assert '"tone": "direct"' in di.build_memory_context()

    def test_at_most_two_what_worked_episodes_are_surfaced(self, table):
        for d in ("2026-05-06", "2026-05-07", "2026-05-08"):
            seed(table, _row("platform_memory", f"MEMORY#what_worked#{d}", conditions=f"c{d}", behaviors="b", outcomes="o"))
        ctx = di.build_memory_context()
        assert sum(1 for ln in ctx.splitlines() if ln.startswith("  When ")) == 2

    def test_failure_patterns_are_surfaced_under_their_own_heading(self, table):
        seed(table, _row("platform_memory", "MEMORY#failure_pattern#2026-05-08", pattern="skips dinner logging"))
        ctx = di.build_memory_context()
        assert "KNOWN FAILURE PATTERNS:" in ctx and "skips dinner logging" in ctx


# ──────────────────────────────────────────────────────────────────────────────
# IC-8: intent vs execution
# ──────────────────────────────────────────────────────────────────────────────


class TestExtractIntentionTexts:
    def test_the_first_usable_morning_intention_wins(self):
        entries = [{"todays_intention": "walk 10k steps"}, {"todays_intention": "second"}]
        assert di._extract_intention_texts(entries)["today"] == "walk 10k steps"

    def test_a_trivially_short_intention_is_not_treated_as_an_intention(self):
        """A five-character stub is noise, not a stated intention."""
        assert di._extract_intention_texts([{"todays_intention": "hi..."}])["today"] is None

    def test_morning_and_evening_intentions_are_kept_apart(self):
        entries = [{"todays_intention": "log every meal", "tomorrow_focus": "bed by ten"}]
        assert di._extract_intention_texts(entries) == {"today": "log every meal", "tomorrow": "bed by ten"}

    def test_no_journal_entries_yield_both_intentions_absent(self):
        assert di._extract_intention_texts([]) == {"today": None, "tomorrow": None}


class TestFetchExecutionMetrics:
    PROFILE = {"calorie_target": 1800, "protein_target_g": 190}

    def test_an_absent_nutrition_log_reports_no_calorie_figure_at_all(self, table):
        """ADR-104: an unlogged day is not a zero-calorie day."""
        m = di._fetch_execution_metrics(YESTERDAY, self.PROFILE)
        assert "calories_logged" not in m and "protein_g" not in m

    def test_a_log_below_sixty_five_percent_of_target_is_flagged_incomplete(self, table):
        """0.65 × 1800 = 1170; 1100 is below it."""
        seed(table, _date_row("macrofactor", YESTERDAY, total_calories_kcal=1100, food_log=[{"a": 1}]))
        m = di._fetch_execution_metrics(YESTERDAY, self.PROFILE)
        assert "nutrition_note" in m and "1100" in m["nutrition_note"]

    def test_a_log_at_or_above_the_incompleteness_floor_is_not_flagged(self, table):
        seed(table, _date_row("macrofactor", YESTERDAY, total_calories_kcal=1170, food_log=[]))
        assert "nutrition_note" not in di._fetch_execution_metrics(YESTERDAY, self.PROFILE)

    def test_an_absent_strava_day_is_reported_as_zero_sessions(self, table):
        m = di._fetch_execution_metrics(YESTERDAY, self.PROFILE)
        assert m["exercise_sessions"] == 0

    def test_the_sleep_start_is_reduced_to_a_wall_clock_time(self, table):
        seed(table, _date_row("whoop", YESTERDAY, sleep_start="2026-05-09T23:45:00Z", recovery_score=61))
        m = di._fetch_execution_metrics(YESTERDAY, self.PROFILE)
        assert m["sleep_start_time"] == "23:45" and m["recovery_score"] == 61

    def test_tier_zero_completion_is_a_percentage_of_the_day_total(self, table):
        """3 of 5 → 60%."""
        seed(table, _date_row("habit_scores", YESTERDAY, tier0_done=3, tier0_total=5, missed_tier0=["a", "b"]))
        m = di._fetch_execution_metrics(YESTERDAY, self.PROFILE)
        assert m["habit_tier0_pct"] == 60 and m["habit_tier0_detail"] == "3/5 T0 habits completed"

    def test_a_habit_record_with_no_configured_habits_reports_no_percentage(self, table):
        """0/0 is undefined, not 0%."""
        seed(table, _date_row("habit_scores", YESTERDAY, tier0_done=0, tier0_total=0))
        assert "habit_tier0_pct" not in di._fetch_execution_metrics(YESTERDAY, self.PROFILE)


class TestEvaluateIntentionsHaiku:
    def _patch_transport(self, monkeypatch, result):
        from common import retry_utils

        calls = []

        def fake_call(req, timeout=25):
            calls.append(req)
            if isinstance(result, Exception):
                raise result
            return {"content": [{"text": result}]}

        monkeypatch.setattr(retry_utils, "call_anthropic_raw", fake_call)
        return calls

    def test_no_stated_intentions_short_circuits_before_any_inference_call(self, monkeypatch):
        calls = self._patch_transport(monkeypatch, "[]")
        assert di._evaluate_intentions_haiku({"today": None, "tomorrow": None}, {}, "k") == []
        assert calls == []

    def test_a_plain_json_array_is_returned_as_parsed_evaluations(self, monkeypatch):
        self._patch_transport(monkeypatch, '[{"type": "exercise", "executed": true}]')
        out = di._evaluate_intentions_haiku({"today": "run today"}, {}, "k")
        assert out == [{"type": "exercise", "executed": True}]

    def test_a_fenced_json_array_is_unwrapped(self, monkeypatch):
        self._patch_transport(monkeypatch, '```json\n[{"type": "walk"}]\n```')
        assert di._evaluate_intentions_haiku({"today": "walk today"}, {}, "k") == [{"type": "walk"}]

    def test_unparseable_output_yields_no_evaluations_rather_than_raising(self, monkeypatch):
        """Non-fatal: a bad model response must not take down the compute."""
        self._patch_transport(monkeypatch, "I could not determine this.")
        assert di._evaluate_intentions_haiku({"today": "walk today"}, {}, "k") == []

    def test_a_transport_failure_yields_no_evaluations_rather_than_raising(self, monkeypatch):
        self._patch_transport(monkeypatch, RuntimeError("bedrock down"))
        assert di._evaluate_intentions_haiku({"today": "walk today"}, {}, "k") == []

    def test_both_intention_sources_reach_the_prompt(self, monkeypatch):
        calls = self._patch_transport(monkeypatch, "[]")
        di._evaluate_intentions_haiku({"today": "log all meals", "tomorrow": "bed by ten"}, {"calories_logged": 1200}, "k")
        body = json.loads(calls[0].data.decode())["messages"][0]["content"]
        assert "[Morning intention] log all meals" in body and "[Previous-evening plan] bed by ten" in body
        assert "calories_logged" in body


class TestIntentionPatterns:
    def test_no_history_produces_no_pattern_claims(self):
        assert di._compute_intention_patterns([]) == {}

    def test_a_type_stated_twice_and_missed_both_times_is_a_recurring_gap(self):
        hist = [
            {"evaluations": [{"type": "walk", "executed": False, "confidence": "high"}]},
            {"evaluations": [{"type": "walk", "executed": False, "confidence": "high"}]},
        ]
        gaps = di._compute_intention_patterns(hist)["gap_types_ranked"]
        assert gaps == [{"type": "walk", "stated": 2, "missed": 2, "miss_rate": 1.0}]

    def test_a_type_stated_only_once_is_never_called_recurring(self):
        """ADR-105: n=1 cannot support a 'this keeps happening' claim."""
        hist = [{"evaluations": [{"type": "walk", "executed": False, "confidence": "high"}]}]
        assert di._compute_intention_patterns(hist)["gap_types_ranked"] == []

    def test_a_miss_rate_below_one_half_is_not_a_gap(self):
        """1 of 3 missed = 0.333 — under the 0.50 bar."""
        hist = [{"evaluations": [{"type": "walk", "executed": e, "confidence": "high"}]} for e in (True, True, False)]
        assert di._compute_intention_patterns(hist)["gap_types_ranked"] == []

    def test_a_miss_rate_exactly_one_half_is_a_gap(self):
        hist = [{"evaluations": [{"type": "walk", "executed": e, "confidence": "high"}]} for e in (True, False)]
        assert di._compute_intention_patterns(hist)["gap_types_ranked"][0]["miss_rate"] == 0.5

    def test_gaps_are_ranked_worst_first_and_capped_at_four(self):
        hist = []
        for i, rate in enumerate([0.5, 1.0, 0.75, 0.5, 1.0]):
            misses = int(round(4 * rate))
            evals = [{"type": f"t{i}", "executed": j >= misses, "confidence": "high"} for j in range(4)]
            hist.append({"evaluations": evals})
        gaps = di._compute_intention_patterns(hist)["gap_types_ranked"]
        assert len(gaps) == 4
        assert gaps == sorted(gaps, key=lambda g: -g["miss_rate"])

    def test_a_low_confidence_execution_does_not_count_as_follow_through(self):
        """ADR-105: 'insufficient data to judge' is not evidence of success."""
        hist = [{"evaluations": [{"type": "walk", "executed": True, "confidence": "low"}]}]
        assert di._compute_intention_patterns(hist)["follow_through_rate_7d"] == 0.0

    def test_the_rate_is_the_mean_of_per_day_rates_not_of_all_intentions(self):
        """Day A: 1/1 = 1.0. Day B: 0/3 = 0.0. Mean of day rates = 0.5 (pooled would be 0.25)."""
        hist = [
            {"evaluations": [{"type": "a", "executed": True, "confidence": "high"}]},
            {"evaluations": [{"type": "b", "executed": False, "confidence": "high"} for _ in range(3)]},
        ]
        assert di._compute_intention_patterns(hist)["follow_through_rate_7d"] == 0.5

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "DEFECT (tranche-2 discovery): _load_intention_history queries with "
            "ScanIndexForward=False, so history_records arrive NEWEST-FIRST, but "
            "_compute_intention_patterns takes day_rates[-7:] — the seven OLDEST "
            "days. With >7 days of history the published '7-day follow-through "
            "rate' describes days 8-14, not the last week."
        ),
    )
    def test_the_seven_day_rate_describes_the_most_recent_seven_days(self):
        recent = [
            {"date": f"2026-05-{d:02d}", "evaluations": [{"type": "a", "executed": True, "confidence": "high"}]} for d in range(9, 2, -1)
        ]
        older = [
            {"date": f"2026-05-{d:02d}", "evaluations": [{"type": "a", "executed": False, "confidence": "high"}]} for d in range(2, -5, -1)
        ]
        newest_first = recent + older  # exactly what ScanIndexForward=False returns
        assert di._compute_intention_patterns(newest_first)["follow_through_rate_7d"] == 1.0


class TestLoadIntentionHistory:
    def test_stored_evaluations_are_rehydrated_from_their_json_string(self, table):
        seed(table, _row("platform_memory", f"MEMORY#intention_tracking#{YESTERDAY}", evaluations=json.dumps([{"type": "walk"}])))
        assert di._load_intention_history(YESTERDAY)[0]["evaluations"] == [{"type": "walk"}]

    def test_a_corrupt_evaluations_blob_degrades_to_an_empty_list(self, table):
        seed(table, _row("platform_memory", f"MEMORY#intention_tracking#{YESTERDAY}", evaluations="{not json"))
        assert di._load_intention_history(YESTERDAY)[0]["evaluations"] == []

    def test_the_window_reaches_back_exactly_fourteen_days(self, table):
        seed(
            table,
            _row("platform_memory", "MEMORY#intention_tracking#2026-04-25", evaluations="[]"),
            _row("platform_memory", "MEMORY#intention_tracking#2026-04-24", evaluations="[]"),
        )
        # yesterday 2026-05-09 minus 14 days = 2026-04-25
        assert [r["sk"] for r in di._load_intention_history(YESTERDAY)] == ["MEMORY#intention_tracking#2026-04-25"]

    def test_a_query_failure_degrades_to_no_history(self, table):
        table.query_error = RuntimeError("throttled")
        assert di._load_intention_history(YESTERDAY) == []


class TestAnalyzeIntentionExecutionGap:
    @pytest.fixture(autouse=True)
    def _no_network(self, monkeypatch):
        monkeypatch.setattr(di, "_get_api_key", lambda: "test-key")

    def test_an_unreachable_secret_makes_the_whole_feature_a_no_op(self, table, monkeypatch):
        def boom():
            raise RuntimeError("no secret")

        monkeypatch.setattr(di, "_get_api_key", boom)
        assert di.analyze_intention_execution_gap(YESTERDAY, {}) == ""

    def test_no_journal_intentions_skip_the_inference_call_entirely(self, table, monkeypatch):
        called = []
        monkeypatch.setattr(di, "_evaluate_intentions_haiku", lambda *a: called.append(a) or [])
        assert di.analyze_intention_execution_gap(YESTERDAY, {}) == ""
        assert called == []

    def test_the_evening_plan_is_taken_from_the_day_before_yesterday(self, table, monkeypatch):
        """`tomorrow_focus` written on 05-08 is a plan ABOUT 05-09."""
        seed(table, _row("notion", "DATE#2026-05-08#journal#1", tomorrow_focus="bed by ten"))
        seen = {}
        monkeypatch.setattr(di, "_evaluate_intentions_haiku", lambda intents, metrics, key: seen.update(intents) or [])
        di.analyze_intention_execution_gap(YESTERDAY, {})
        assert seen == {"today": None, "tomorrow": "bed by ten"}

    def test_an_empty_evaluation_set_produces_no_context_block(self, table, monkeypatch):
        seed(table, _row("notion", f"DATE#{YESTERDAY}#journal#1", todays_intention="log every meal"))
        monkeypatch.setattr(di, "_evaluate_intentions_haiku", lambda *a: [])
        assert di.analyze_intention_execution_gap(YESTERDAY, {}) == ""

    def _run(self, table, monkeypatch, evaluations):
        seed(table, _row("notion", f"DATE#{YESTERDAY}#journal#1", todays_intention="log every meal"))
        monkeypatch.setattr(di, "_evaluate_intentions_haiku", lambda *a: evaluations)
        return di.analyze_intention_execution_gap(YESTERDAY, {})

    def test_a_missed_intention_is_named_with_its_evidence(self, table, monkeypatch):
        block = self._run(
            table,
            monkeypatch,
            [{"type": "food_logging", "text": "log every meal", "executed": False, "evidence": "only 900 kcal", "confidence": "high"}],
        )
        assert "Intent: 'log every meal' (food logging) -- only 900 kcal" in block

    def test_a_low_confidence_miss_is_not_listed_as_a_gap(self, table, monkeypatch):
        """ADR-105: we do not accuse on evidence the evaluator called insufficient."""
        block = self._run(table, monkeypatch, [{"type": "walk", "text": "walk", "executed": False, "confidence": "low"}])
        assert "Intent:" not in block

    def test_the_run_is_persisted_to_platform_memory_with_a_decimal_rate(self, table, monkeypatch):
        self._run(
            table,
            monkeypatch,
            [{"type": "walk", "executed": True, "confidence": "high"}, {"type": "food_logging", "executed": False, "confidence": "high"}],
        )
        mem = [p for p in table.puts if p["sk"].startswith("MEMORY#intention_tracking#")][0]
        assert (mem["total_intentions"], mem["intentions_executed"]) == (2, 1)
        assert mem["follow_through_rate"] == Decimal("0.5")
        assert isinstance(mem["follow_through_rate"], Decimal)

    def test_the_persisted_run_carries_a_ninety_day_expiry(self, table, monkeypatch):
        self._run(table, monkeypatch, [{"type": "walk", "executed": True, "confidence": "high"}])
        mem = [p for p in table.puts if p["sk"].startswith("MEMORY#intention_tracking#")][0]
        assert mem["ttl"] == int((FROZEN_NOW + timedelta(days=90)).timestamp())

    def test_a_failed_memory_write_does_not_suppress_the_context_block(self, table, monkeypatch):
        """Fail-soft: the coach still gets today's gap even if the ledger write fails."""
        table.put_errors.add(di.USER_PREFIX + "platform_memory")
        block = self._run(table, monkeypatch, [{"type": "walk", "executed": True, "confidence": "high"}])
        assert block.startswith("INTENT VS EXECUTION GAP (IC-8):")


# ──────────────────────────────────────────────────────────────────────────────
# IC-5: early warning
# ──────────────────────────────────────────────────────────────────────────────


class TestDetectEarlyWarning:
    def test_a_single_marker_is_not_a_warning(self):
        recs = [_cm(f"2026-05-0{d}", journal=10) for d in (6, 7, 8)]
        active, markers, block = di.detect_early_warning(recs, [], [])
        assert markers == ["journal_sparse"] and active is False and block == ""

    def test_two_simultaneous_markers_raise_the_warning(self):
        recs = [_cm(f"2026-05-0{d}", journal=10, nutrition=10) for d in (6, 7, 8)]
        active, markers, block = di.detect_early_warning(recs, [], [])
        assert active is True and set(markers) == {"journal_sparse", "nutrition_gap"}
        assert "EARLY WARNING" in block

    def test_the_journal_marker_needs_two_low_days_of_the_last_three(self):
        recs = [_cm("2026-05-06", journal=10), _cm("2026-05-07", journal=90), _cm("2026-05-08", journal=90)]
        assert di.detect_early_warning(recs, [], [])[1] == []

    def test_the_journal_threshold_is_strictly_below_fifty(self):
        recs = [_cm(f"2026-05-0{d}", journal=50) for d in (6, 7, 8)]
        assert di.detect_early_warning(recs, [], [])[1] == []

    def test_the_nutrition_threshold_is_strictly_below_forty(self):
        recs = [_cm(f"2026-05-0{d}", nutrition=40) for d in (6, 7, 8)]
        assert di.detect_early_warning(recs, [], [])[1] == []

    def test_only_the_last_three_days_of_the_window_are_examined(self):
        recs = [_cm(f"2026-05-0{d}", journal=10) for d in (1, 2, 3)] + [_cm(f"2026-05-0{d}", journal=90) for d in (6, 7, 8)]
        assert di.detect_early_warning(recs, [], [])[1] == []

    def test_a_declining_recovery_run_is_a_marker(self):
        declining = [{"metric": "recovery"}]
        assert di.detect_early_warning([], [], declining)[1] == ["recovery_sliding"]

    def test_absent_component_scores_produce_no_markers_rather_than_low_ones(self):
        """ADR-104: a missing journal score is not a journal score of zero."""
        recs = [_cm(f"2026-05-0{d}") for d in (6, 7, 8)]
        assert di.detect_early_warning(recs, [], [])[1] == []

    def test_the_habit_marker_needs_at_least_four_days_of_habit_history(self):
        habits = [_hs(f"2026-05-0{d}", t0_completion_rate=r) for d, r in zip((6, 7, 8), (0.9, 0.2, 0.2))]
        assert "habit_declining" not in di.detect_early_warning([], habits, [])[1]

    def test_a_fifteen_point_habit_drop_is_a_marker(self):
        """prior (05-01..05-04) mean 0.90; recent (05-06..05-08) mean 0.75; drop = 0.15."""
        prior = [_hs(f"2026-05-0{d}", t0_completion_rate=0.90) for d in (1, 2, 3, 4)]
        recent = [_hs(f"2026-05-0{d}", t0_completion_rate=0.75) for d in (6, 7, 8)]
        assert "habit_declining" in di.detect_early_warning([], prior + recent, [])[1]

    def test_a_habit_drop_under_the_bar_is_not_a_marker(self):
        prior = [_hs(f"2026-05-0{d}", t0_completion_rate=0.90) for d in (1, 2, 3, 4)]
        recent = [_hs(f"2026-05-0{d}", t0_completion_rate=0.80) for d in (6, 7, 8)]
        assert "habit_declining" not in di.detect_early_warning([], prior + recent, [])[1]

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "DEFECT (tranche-2 discovery): reader/writer field-name mismatch. "
            "detect_early_warning's habit_declining marker reads "
            "`t0_completion_rate`, but BOTH writers of the habit_scores partition "
            "(daily_brief_lambda.store_habit_scores and daily_metrics_compute) "
            "write `tier0_pct` and nothing writes `t0_completion_rate` anywhere in "
            "the repo. On real data the marker is permanently dark — one of the "
            "four IC-5 markers can never contribute to the 2-marker warning gate."
        ),
    )
    def test_the_habit_marker_fires_on_the_field_the_writers_actually_write(self):
        prior = [_hs(f"2026-05-0{d}", tier0_pct=0.95) for d in (1, 2, 3, 4)]
        recent = [_hs(f"2026-05-0{d}", tier0_pct=0.20) for d in (6, 7, 8)]
        assert "habit_declining" in di.detect_early_warning([], prior + recent, [])[1]


# ──────────────────────────────────────────────────────────────────────────────
# Priority queue assembly
# ──────────────────────────────────────────────────────────────────────────────


def _sig(priority, content, est=20):
    return {"priority": priority, "content": content, "token_estimate": est}


class TestPrioritizedContextBlock:
    def test_signals_are_emitted_in_ascending_priority_order(self):
        out = di._build_prioritized_context_block([_sig(9, "low"), _sig(1, "urgent"), _sig(5, "middle")])
        body = out.splitlines()
        assert body.index("urgent") < body.index("middle") < body.index("low")

    def test_the_block_is_framed_by_its_header_and_instruction_footer(self):
        out = di._build_prioritized_context_block([])
        lines = out.splitlines()
        assert lines[0].startswith("PLATFORM INTELLIGENCE") and lines[-1].startswith("INSTRUCTION:")

    def test_an_empty_signal_set_still_produces_a_well_formed_block(self):
        """A quiet day is a quiet block, not a crash and not an invented signal."""
        lines = di._build_prioritized_context_block([]).splitlines()
        assert len(lines) == 3 and lines[1] == ""

    def test_a_priority_one_signal_is_included_even_past_the_token_budget(self):
        out = di._build_prioritized_context_block([_sig(1, "critical", est=10_000)], token_budget=50)
        assert "critical" in out

    def test_a_lower_priority_signal_is_dropped_once_the_budget_is_exhausted(self):
        out = di._build_prioritized_context_block([_sig(2, "keep", est=40), _sig(3, "drop", est=40)], token_budget=50)
        assert "keep" in out and "drop" not in out

    def test_the_budget_accounts_for_the_header_before_any_signal(self):
        """The header costs 5 word-tokens, so a 40-token signal needs budget ≥ 45."""
        assert "only" not in di._build_prioritized_context_block([_sig(2, "only", est=40)], token_budget=44)
        assert "only" in di._build_prioritized_context_block([_sig(2, "only", est=40)], token_budget=45)


# ──────────────────────────────────────────────────────────────────────────────
# Pure numerics
# ──────────────────────────────────────────────────────────────────────────────


class TestLinregSlope:
    def test_a_perfectly_linear_series_returns_its_exact_slope(self):
        assert di._linreg_slope([1.0, 3.0, 5.0, 7.0]) == 2.0

    def test_a_falling_series_returns_a_negative_slope(self):
        assert di._linreg_slope([5.0, 4.0, 3.0, 2.0]) == -1.0

    def test_a_flat_series_has_zero_slope_not_none(self):
        assert di._linreg_slope([200.0, 200.0, 200.0]) == 0.0

    def test_fewer_than_two_points_cannot_support_a_slope(self):
        assert di._linreg_slope([5.0]) is None
        assert di._linreg_slope([]) is None

    def test_the_slope_is_least_squares_not_endpoint_difference(self):
        """[10, 0, 0, 0]: x̄=1.5, ȳ=2.5 → Σ(x-x̄)(y-ȳ) = -15, Σ(x-x̄)² = 5 → -3.0.
        The endpoint difference would be (0-10)/3 = -3.333…, which is not what a
        plateau/rate decision may be based on."""
        assert di._linreg_slope([10.0, 0.0, 0.0, 0.0]) == -3.0


class TestToDecimal:
    def test_a_float_is_converted_and_rounded_to_four_places(self):
        assert di._to_dec(1.23456) == Decimal("1.2346")
        assert isinstance(di._to_dec(1.23456), Decimal)

    def test_absence_survives_the_conversion_as_absence(self):
        assert di._to_dec(None) is None

    def test_an_integer_valued_input_still_becomes_a_decimal(self):
        assert isinstance(di._to_dec(42), Decimal)


class TestCircadianConsistency:
    def test_fewer_than_seven_bedtimes_cannot_support_a_consistency_claim(self, table):
        for i in range(6):
            seed(table, _date_row("eightsleep", f"2026-05-0{i + 1}", bedtime_start=f"2026-05-0{i + 1}T23:00:00Z"))
        assert di._check_circadian_consistency(YESTERDAY) is None

    def test_a_perfectly_regular_bedtime_has_zero_variability(self, table):
        for i in range(1, 9):
            seed(table, _date_row("eightsleep", f"2026-05-{i:02d}", bedtime_start=f"2026-05-{i:02d}T23:00:00Z"))
        assert di._check_circadian_consistency(YESTERDAY) == 0.0

    def test_the_variability_is_the_sample_sd_of_bedtime_hours(self, table):
        """Four nights at 22:00 and four at 24:00 → hours [22,22,22,22,0,0,0,0]."""
        hours = [22, 22, 22, 22, 0, 0, 0, 0]
        for i, h in enumerate(hours, start=1):
            seed(table, _date_row("eightsleep", f"2026-05-{i:02d}", bedtime_start=f"2026-05-{i:02d}T{h:02d}:00:00Z"))
        assert di._check_circadian_consistency(YESTERDAY) == round(statistics.stdev([float(h) for h in hours]), 2)


# ──────────────────────────────────────────────────────────────────────────────
# IC-19 slow drift — the ADR-105 gates
# ──────────────────────────────────────────────────────────────────────────────


class TestSlowDrift:
    """Hand-derived arithmetic — see the module-level `_BASE_SD` / `_BASE_SE` note.

    Baseline is 14 alternating points about 52.0 (sd = √(56/13)); the alternation
    pins the effective n at exactly 14, so SE = √(8/13) and both the effect size
    and the z are closed-form.
    """

    RECENT_START, RECENT_END = _days(YEST_D, 14), _days(YEST_D, 1)
    BASE_START, BASE_END = _days(YEST_D, 28), _days(YEST_D, 15)

    def _fetcher(self, monkeypatch, *, baseline=None, recent=None, field="hrv", source="whoop"):
        f = WindowFetcher()
        if baseline is not None:
            f.register(source, self.BASE_START, self.BASE_END, [{"date": f"b{i}", field: v} for i, v in enumerate(baseline)])
        if recent is not None:
            f.register(source, self.RECENT_START, self.RECENT_END, [{"date": f"r{i}", field: v} for i, v in enumerate(recent)])
        monkeypatch.setattr(di, "fetch_range", f)
        return f

    def test_the_two_windows_are_equal_length_and_do_not_overlap(self, monkeypatch):
        """TB7-22: equal 14d windows so both means carry the same SE."""
        f = self._fetcher(monkeypatch)
        di._compute_slow_drift(YESTERDAY, {})
        assert (date.fromisoformat(self.RECENT_END) - date.fromisoformat(self.RECENT_START)).days == 13
        assert (date.fromisoformat(self.BASE_END) - date.fromisoformat(self.BASE_START)).days == 13
        assert self.BASE_END < self.RECENT_START
        assert (self.RECENT_START, self.RECENT_END) in [(s, e) for _src, s, e in f.calls]

    def test_a_baseline_under_fourteen_points_publishes_no_drift_claim(self, monkeypatch):
        """ADR-105 sample floor (Henning): 13 nights cannot anchor a baseline."""
        self._fetcher(monkeypatch, baseline=_alt(52.0)[:13], recent=_alt(40.0))
        assert di._compute_slow_drift(YESTERDAY, {}) == []

    def test_a_drift_below_the_half_sd_effect_floor_is_not_published(self, monkeypatch):
        """effect = -1.0 / √(56/13) = -0.482 SD — real but too small to matter."""
        self._fetcher(monkeypatch, baseline=_alt(52.0), recent=_alt(51.0))
        assert abs(-1.0 / _BASE_SD) < 0.5
        assert di._compute_slow_drift(YESTERDAY, {}) == []

    def test_a_drift_that_clears_the_effect_floor_but_not_significance_is_suppressed(self, monkeypatch):
        """effect = -1.3/√(56/13) = -0.626 SD (clears 0.5); z = -1.3/√(8/13) = -1.657 (under 1.96)."""
        assert abs(-1.3 / _BASE_SD) >= 0.5 and abs(-1.3 / _BASE_SE) < 1.96
        self._fetcher(monkeypatch, baseline=_alt(52.0), recent=_alt(50.7))
        assert di._compute_slow_drift(YESTERDAY, {}) == []

    def test_a_large_significant_drop_is_published_as_severe(self, monkeypatch):
        """effect = -3.0/√(56/13) = -1.445 SD; z = -3.0/√(8/13) = -3.824 (past 2.576)."""
        assert abs(-3.0 / _BASE_SE) >= 2.576
        self._fetcher(monkeypatch, baseline=_alt(52.0), recent=_alt(49.0))
        out = di._compute_slow_drift(YESTERDAY, {})
        hrv = [d for d in out if d["metric"] == "HRV"][0]
        assert hrv["severity"] == "severe"
        assert hrv["drift_sd"] == round(-3.0 / _BASE_SD, 2) == -1.45
        assert hrv["drift_z"] == round(-3.0 / _BASE_SE, 2) == -3.82

    def test_every_published_drift_carries_its_sample_size_and_p_value(self, monkeypatch):
        """ADR-105: no statistical claim without uncertainty and n."""
        self._fetcher(monkeypatch, baseline=_alt(52.0), recent=_alt(49.0))
        hrv = [d for d in di._compute_slow_drift(YESTERDAY, {}) if d["metric"] == "HRV"][0]
        assert hrv["baseline_n"] == 14
        assert hrv["p_value"] == 0.0001
        assert hrv["recent_mean"] == 49.0 and hrv["baseline_mean"] == 52.0

    def test_falling_hrv_is_worsening_but_falling_resting_heart_rate_is_not(self, monkeypatch):
        f = WindowFetcher()
        for field in ("hrv", "resting_heart_rate"):
            f.register(
                "whoop",
                self.BASE_START,
                self.BASE_END,
                [{"date": f"b{i}", "hrv": v, "resting_heart_rate": v} for i, v in enumerate(_alt(52.0))],
            )
            f.register(
                "whoop",
                self.RECENT_START,
                self.RECENT_END,
                [{"date": f"r{i}", "hrv": v, "resting_heart_rate": v} for i, v in enumerate(_alt(49.0))],
            )
        monkeypatch.setattr(di, "fetch_range", f)
        out = {d["metric"]: d["worsening"] for d in di._compute_slow_drift(YESTERDAY, {})}
        assert out["HRV"] is True and out["Resting HR"] is False

    def test_a_baseline_with_no_variance_cannot_anchor_an_effect_size(self, monkeypatch):
        """Dividing a shift by a zero SD is undefined — publish nothing."""
        self._fetcher(monkeypatch, baseline=[52.0] * 14, recent=_alt(20.0))
        assert di._compute_slow_drift(YESTERDAY, {}) == []

    def test_an_empty_recent_window_publishes_nothing_even_with_a_full_baseline(self, monkeypatch):
        self._fetcher(monkeypatch, baseline=_alt(52.0), recent=[])
        assert di._compute_slow_drift(YESTERDAY, {}) == []

    def test_a_circadian_note_is_attached_when_bedtimes_have_also_scattered(self, monkeypatch):
        self._fetcher(monkeypatch, baseline=_alt(52.0), recent=_alt(49.0))
        monkeypatch.setattr(di, "_check_circadian_consistency", lambda *a, **k: 1.8)
        hrv = [d for d in di._compute_slow_drift(YESTERDAY, {}) if d["metric"] == "HRV"][0]
        assert "bedtime consistency" in hrv["note"] and "1.8" in hrv["note"]

    def test_no_circadian_note_when_bedtimes_are_regular(self, monkeypatch):
        self._fetcher(monkeypatch, baseline=_alt(52.0), recent=_alt(49.0))
        monkeypatch.setattr(di, "_check_circadian_consistency", lambda *a, **k: 0.4)
        hrv = [d for d in di._compute_slow_drift(YESTERDAY, {}) if d["metric"] == "HRV"][0]
        assert hrv["note"] is None

    def test_a_rising_hrv_drift_gets_no_circadian_blame(self, monkeypatch):
        self._fetcher(monkeypatch, baseline=_alt(52.0), recent=_alt(55.0))
        monkeypatch.setattr(di, "_check_circadian_consistency", lambda *a, **k: 3.0)
        hrv = [d for d in di._compute_slow_drift(YESTERDAY, {}) if d["metric"] == "HRV"][0]
        assert hrv["worsening"] is False and hrv["note"] is None


class TestWeightPlateau:
    WT_START = _days(YEST_D, 14)

    def _fetcher(self, monkeypatch, *, weights, mf_records=None, apple=None):
        f = WindowFetcher()
        f.register(
            "withings", self.WT_START, YESTERDAY, [{"date": f"2026-04-{25 + i:02d}", "weight_lbs": w} for i, w in enumerate(weights)]
        )
        f.register("macrofactor", self.WT_START, YESTERDAY, mf_records or [])
        if apple is not None:
            f.register("apple_health", self.WT_START, YESTERDAY, apple)
        monkeypatch.setattr(di, "fetch_range", f)
        return f

    def _mf(self, n, kcal=1500, **extra):
        return [{"date": f"2026-04-{25 + i:02d}", "total_calories_kcal": kcal, **extra} for i in range(n)]

    def test_a_flat_scale_with_a_complete_log_is_published_as_a_plateau(self, monkeypatch):
        self._fetcher(monkeypatch, weights=[300.0] * 8, mf_records=self._mf(11, expenditure_kcal=2600))
        wt = [d for d in di._compute_slow_drift(YESTERDAY, {}) if d["metric"] == "Weight Plateau"][0]
        assert wt["slope_lbs_week"] == 0.0
        assert (wt["measurements_n"], wt["complete_log_days"]) == (8, 11)
        assert wt["tdee_source"] == "MacroFactor"

    def test_fewer_than_eight_weigh_ins_cannot_support_a_plateau_claim(self, monkeypatch):
        """ADR-105 sample floor (Attia): 7 points is not a regression."""
        self._fetcher(monkeypatch, weights=[300.0] * 7, mf_records=self._mf(14))
        assert [d for d in di._compute_slow_drift(YESTERDAY, {}) if d["metric"] == "Weight Plateau"] == []

    def test_fewer_than_eleven_complete_log_days_cannot_support_a_plateau_claim(self, monkeypatch):
        """ADR-105 (Henning): a flat scale means nothing without a trustworthy intake log."""
        self._fetcher(monkeypatch, weights=[300.0] * 10, mf_records=self._mf(10))
        assert [d for d in di._compute_slow_drift(YESTERDAY, {}) if d["metric"] == "Weight Plateau"] == []

    def test_a_log_day_below_sixty_five_percent_of_target_is_not_a_complete_day(self, monkeypatch):
        """0.65 × 1800 = 1170; days logged at 1100 do not count."""
        self._fetcher(monkeypatch, weights=[300.0] * 10, mf_records=self._mf(14, kcal=1100))
        assert [d for d in di._compute_slow_drift(YESTERDAY, {}) if d["metric"] == "Weight Plateau"] == []

    def test_a_genuine_loss_rate_is_not_reported_as_a_plateau(self, monkeypatch):
        """-0.1 lb/day → -0.7 lb/week, comfortably past the -0.2 bar."""
        weights = [300.0 - 0.1 * i for i in range(10)]
        self._fetcher(monkeypatch, weights=weights, mf_records=self._mf(14))
        assert [d for d in di._compute_slow_drift(YESTERDAY, {}) if d["metric"] == "Weight Plateau"] == []

    def test_the_plateau_always_carries_the_recomposition_caveat(self, monkeypatch):
        """ADR-104/Okafor: a flat scale is not proof of a stalled deficit."""
        self._fetcher(monkeypatch, weights=[300.0] * 8, mf_records=self._mf(11))
        wt = [d for d in di._compute_slow_drift(YESTERDAY, {}) if d["metric"] == "Weight Plateau"][0]
        assert "recomposition" in wt["note"]

    def test_apple_watch_is_the_named_tdee_source_only_when_macrofactor_has_none(self, monkeypatch):
        self._fetcher(
            monkeypatch,
            weights=[300.0] * 8,
            mf_records=self._mf(11),
            apple=[{"date": "2026-05-01", "active_energy_burned": 600}],
        )
        wt = [d for d in di._compute_slow_drift(YESTERDAY, {}) if d["metric"] == "Weight Plateau"][0]
        assert wt["tdee_source"] == "Apple Watch"

    def test_a_weight_read_failure_does_not_abort_the_biometric_drift_results(self, monkeypatch):
        """Fail-soft boundary: the plateau block is wrapped for exactly this."""

        def exploding(source, start, end):
            if source == "withings":
                raise RuntimeError("throttled")
            if source == "whoop" and start == _days(YEST_D, 28):
                return [{"date": f"b{i}", "hrv": v} for i, v in enumerate(_alt(52.0))]
            if source == "whoop" and start == _days(YEST_D, 14):
                return [{"date": f"r{i}", "hrv": v} for i, v in enumerate(_alt(49.0))]
            return []

        monkeypatch.setattr(di, "fetch_range", exploding)
        assert [d["metric"] for d in di._compute_slow_drift(YESTERDAY, {})] == ["HRV"]


# ──────────────────────────────────────────────────────────────────────────────
# IC-31 changepoints (the consumer's wiring, not the detector's maths)
# ──────────────────────────────────────────────────────────────────────────────


class TestChangepointWiring:
    def test_every_configured_series_is_scanned_over_the_declared_window(self, monkeypatch):
        """Guard the SET: the expectation is derived from CHANGEPOINT_SERIES."""
        f = WindowFetcher()
        monkeypatch.setattr(di, "fetch_range", f)
        di._compute_changepoints(YESTERDAY)
        expected_start = _days(YEST_D, di.CHANGEPOINT_WINDOW_DAYS)
        wanted = {(src, expected_start, YESTERDAY) for src, _f, _l, _u, _h in di.CHANGEPOINT_SERIES}
        assert wanted <= set(f.calls)

    def test_a_series_shorter_than_fourteen_points_is_skipped_silently(self, monkeypatch):
        recs = [{"date": f"2026-05-{i:02d}", "hrv": 50 + i} for i in range(1, 14)]
        monkeypatch.setattr(di, "fetch_range", lambda s, a, b: recs if s == "whoop" else [])
        assert di._compute_changepoints(YESTERDAY, series_defs=[("whoop", "hrv", "HRV", "ms", True)]) == []

    def test_a_scan_failure_on_one_series_does_not_lose_the_others(self, monkeypatch):
        def half_broken(source, start, end):
            if source == "whoop":
                raise RuntimeError("throttled")
            return []

        monkeypatch.setattr(di, "fetch_range", half_broken)
        assert di._compute_changepoints(YESTERDAY) == []


class TestFormatChangepointLine:
    BASE = {
        "metric": "HRV",
        "unit": "ms",
        "date": "2026-04-20",
        "before_mean": 62.0,
        "after_mean": 50.0,
        "magnitude": -12.0,
        "effect_size": -2.4,
        "confidence": 0.996,
        "direction": "decrease",
        "worsening": True,
        "n_before": 20,
        "n_after": 18,
        "window_days": 60,
    }

    def test_the_line_states_the_magnitude_direction_and_approximate_date(self):
        line = di._format_changepoint_line(dict(self.BASE))
        assert "HRV stepped ↓ -12.0 ms around 2026-04-20" in line

    def test_the_line_carries_effect_size_confidence_and_both_sample_sizes(self):
        """ADR-105: the number and the uncertainty travel together."""
        line = di._format_changepoint_line(dict(self.BASE))
        assert "2.4 SD" in line and "100% confidence" in line and "n=20→18" in line

    def test_an_adverse_shift_is_labelled_adverse(self):
        assert "(adverse)" in di._format_changepoint_line(dict(self.BASE))

    def test_a_favorable_shift_is_labelled_favorable(self):
        cp = dict(self.BASE, worsening=False, direction="increase", magnitude=12.0)
        assert "(favorable)" in di._format_changepoint_line(cp)

    def test_a_polarity_free_metric_gets_no_valence_label(self):
        """Weight has no inherent good/bad direction — a step is just a step."""
        cp = dict(self.BASE, metric="Weight", unit="lbs", worsening=None)
        line = di._format_changepoint_line(cp)
        assert "(adverse)" not in line and "(favorable)" not in line


# ──────────────────────────────────────────────────────────────────────────────
# Experiment context
# ──────────────────────────────────────────────────────────────────────────────


def _exp(exp_id, **fields):
    return _row("experiments", f"EXP#{exp_id}", status="active", **fields)


class TestExperimentContext:
    def test_no_active_experiments_costs_no_further_reads_and_says_nothing(self, table):
        assert di._build_experiment_context(YESTERDAY, {}) == ""
        assert len(table.queries) == 1

    def test_a_completed_experiment_is_not_described_as_active(self, table):
        seed(table, _row("experiments", "EXP#1", status="completed", name="Creatine", start_date="2026-05-01"))
        assert di._build_experiment_context(YESTERDAY, {}) == ""

    def test_the_day_count_is_inclusive_of_the_start_date(self, table):
        """Started 2026-05-01, yesterday 2026-05-09 → Day 9."""
        seed(table, _exp("1", name="Creatine", start_date="2026-05-01"))
        assert "Creatine (Day 9, started 2026-05-01)" in di._build_experiment_context(YESTERDAY, {})

    def test_a_metric_snapshot_reports_baseline_recent_and_delta_without_a_verdict(self, table, monkeypatch):
        seed(
            table,
            _exp("1", name="Creatine", start_date="2026-05-01", primary_metrics=[{"source": "whoop", "field": "hrv", "label": "HRV"}]),
        )
        f = WindowFetcher()
        f.register("whoop", "2026-04-22", "2026-04-30", [{"date": "2026-04-25", "hrv": 50.0}])
        f.register("whoop", "2026-05-03", YESTERDAY, [{"date": "2026-05-05", "hrv": 56.0}])
        monkeypatch.setattr(di, "fetch_range", f)
        ctx = di._build_experiment_context(YESTERDAY, {})
        assert "HRV: baseline 50.0 | 7d avg 56.0 | delta +6.0" in ctx
        assert "improv" not in ctx.lower() and "working" not in ctx.lower()

    def test_a_metric_with_no_data_on_either_side_produces_no_line(self, table, monkeypatch):
        """ADR-104: an empty window is silence, not a delta of zero."""
        seed(
            table,
            _exp("1", name="Creatine", start_date="2026-05-01", primary_metrics=[{"source": "whoop", "field": "hrv", "label": "HRV"}]),
        )
        monkeypatch.setattr(di, "fetch_range", WindowFetcher())
        assert "HRV:" not in di._build_experiment_context(YESTERDAY, {})

    def test_at_most_four_metrics_per_experiment_are_described(self, table, monkeypatch):
        metrics = [{"source": "whoop", "field": f"m{i}", "label": f"M{i}"} for i in range(6)]
        seed(table, _exp("1", name="Creatine", start_date="2026-05-01", primary_metrics=metrics))
        rows = [{"date": "2026-05-05", **{f"m{i}": 10.0 for i in range(6)}}]
        f = WindowFetcher()
        f.register("whoop", "2026-04-22", "2026-04-30", rows)
        f.register("whoop", "2026-05-03", YESTERDAY, rows)
        monkeypatch.setattr(di, "fetch_range", f)
        ctx = di._build_experiment_context(YESTERDAY, {})
        assert sum(1 for i in range(6) if f"M{i}:" in ctx) == 4

    def test_supplement_adherence_counts_only_the_matching_supplement(self, table, monkeypatch):
        seed(table, _exp("1", name="Creatine Trial", category="supplement", start_date="2026-05-01", supplement_name="Creatine"))
        f = WindowFetcher()
        f.register(
            "supplements",
            "2026-05-01",
            YESTERDAY,
            [{"supplement_name": "Creatine"}, {"supplement_name": "Creatine"}, {"supplement_name": "Magnesium"}],
        )
        monkeypatch.setattr(di, "fetch_range", f)
        assert "Adherence: 2/9 doses logged" in di._build_experiment_context(YESTERDAY, {})

    def test_a_negative_psychological_hypothesis_is_framed_as_exploratory(self, table, monkeypatch):
        """Conti: a stress/mood hypothesis must not read as a diagnosis."""
        seed(table, _exp("1", name="Journaling", start_date="2026-05-01", hypothesis="Daily journaling lowers my anxiety"))
        monkeypatch.setattr(di, "fetch_range", WindowFetcher())
        assert "exploratory, not diagnostic" in di._build_experiment_context(YESTERDAY, {})

    def test_a_neutral_hypothesis_gets_no_intervention_framing(self, table, monkeypatch):
        seed(table, _exp("1", name="Creatine", start_date="2026-05-01", hypothesis="Creatine raises my bench press"))
        monkeypatch.setattr(di, "fetch_range", WindowFetcher())
        assert "exploratory, not diagnostic" not in di._build_experiment_context(YESTERDAY, {})

    def test_a_failed_experiments_query_is_non_fatal(self, table):
        table.query_error = RuntimeError("throttled")
        assert di._build_experiment_context(YESTERDAY, {}) == ""


# ──────────────────────────────────────────────────────────────────────────────
# IC-28 ACWR
# ──────────────────────────────────────────────────────────────────────────────


def _acwr_zones():
    """The zone SET, derived from the module's own ZONE_ICONS map (never a literal).

    A zone added to the detector without a priority tier — or one whose tier
    lands between the assembler's two admission guards — must fail these tests
    rather than slip through unnoticed.
    """
    src = textwrap.dedent(inspect.getsource(di._build_acwr_signal))
    m = re.search(r"ZONE_ICONS\s*=\s*(\{.*?\})", src, re.S)
    assert m, "ZONE_ICONS literal not found — the ACWR zone set can no longer be derived"
    return sorted(ast.literal_eval(m.group(1)).keys())


ACWR_ZONES = _acwr_zones()
ACWR_ALERTING_ZONES = [z for z in ACWR_ZONES if z != "safe"]


def _acwr(date_str, zone, acwr=1.5, **fields):
    return {"date": date_str, "acwr_zone": zone, "acwr": acwr, "acute_load_7d": 400.0, "chronic_load_28d": 266.7, **fields}


class TestAcwrSignal:
    def test_a_window_with_no_acwr_data_produces_no_signal(self):
        """ADR-104: no training-load model is silence, not a 'safe' verdict."""
        assert di._build_acwr_signal([{"date": "2026-05-08"}]) is None

    def test_an_unknown_zone_produces_no_signal(self):
        assert di._build_acwr_signal([_acwr("2026-05-08", "unknown")]) is None

    def test_the_most_recent_zoned_record_wins(self):
        recs = [_acwr("2026-05-06", "danger"), _acwr("2026-05-08", "safe")]
        assert "SAFE" in di._build_acwr_signal(recs)["content"]

    @pytest.mark.parametrize("zone", ACWR_ZONES)
    def test_every_zone_lands_on_one_of_the_two_declared_priority_tiers(self, zone):
        assert di._build_acwr_signal([_acwr("2026-05-08", zone)])["priority"] in (4, 8)

    @pytest.mark.parametrize("zone", ACWR_ALERTING_ZONES)
    def test_an_alerting_zone_is_ranked_for_the_prescription_tier(self, zone):
        assert di._build_acwr_signal([_acwr("2026-05-08", zone)])["priority"] == 4

    def test_the_safe_zone_is_ranked_as_informational_only(self):
        assert di._build_acwr_signal([_acwr("2026-05-08", "safe")])["priority"] == 8

    def test_the_content_carries_the_ratio_and_both_load_figures(self):
        content = di._build_acwr_signal([_acwr("2026-05-08", "danger", acwr=1.62)])["content"]
        assert "ACWR 1.62 (DANGER)" in content and "7d acute: 400.0" in content and "28d chronic: 266.7" in content

    def test_the_danger_instruction_forbids_coaching_it_as_a_normal_day(self):
        content = di._build_acwr_signal([_acwr("2026-05-08", "danger")])["content"]
        assert "Do NOT coach as a normal training day" in content

    def test_the_detraining_instruction_is_framed_as_an_opportunity_not_an_alarm(self):
        content = di._build_acwr_signal([_acwr("2026-05-08", "detraining", acwr=0.6)])["content"]
        assert "opportunity" in content and "Don't alarm" in content

    @pytest.mark.parametrize("zone", ACWR_ZONES)
    def test_every_zone_the_detector_can_emit_survives_into_the_context_block(self, zone):
        """Guard the SET: the assembler admits ACWR only at priority ≤4 or ≥8, so a
        zone whose priority lands between the two guards would be silently dropped."""
        sig = di._build_acwr_signal([_acwr("2026-05-08", zone)])
        block = _empty_context_block(acwr_signal=sig)
        assert sig["content"] in block, f"zone {zone} (priority {sig['priority']}) was dropped by the assembler"


# ──────────────────────────────────────────────────────────────────────────────
# BS-MP3 decision fatigue
# ──────────────────────────────────────────────────────────────────────────────


def _todoist(sk, **fields):
    return _row("todoist", sk, **fields)


class TestDecisionFatigue:
    def test_no_todoist_snapshot_means_no_alert(self, table):
        """ADR-104: an absent task count is not a load of zero."""
        assert di._compute_decision_fatigue_alert(YESTERDAY, [_hs("2026-05-08", tier0_pct=0.2)]) == (False, "")

    def test_no_habit_history_means_no_alert(self, table):
        seed(table, _todoist("DATE#2026-05-09", active_task_count=300, overdue_count=40, due_today_count=5))
        assert di._compute_decision_fatigue_alert(YESTERDAY, []) == (False, "")

    def test_both_conditions_together_fire_the_alert(self, table):
        """overdue 20 + due_today 5 = 25 > 15; habits 0.30 < 0.60."""
        seed(table, _todoist("DATE#2026-05-09", active_task_count=300, overdue_count=20, due_today_count=5))
        fired, block = di._compute_decision_fatigue_alert(YESTERDAY, [_hs("2026-05-08", tier0_pct=0.30)])
        assert fired is True and "DECISION FATIGUE DETECTED" in block

    def test_pressing_load_is_overdue_plus_due_today_not_the_active_backlog(self, table):
        """#478/ADR-122: a 300-task backlog with 2 pressing items is not fatigue."""
        seed(table, _todoist("DATE#2026-05-09", active_task_count=300, overdue_count=1, due_today_count=1))
        assert di._compute_decision_fatigue_alert(YESTERDAY, [_hs("2026-05-08", tier0_pct=0.10)])[0] is False

    def test_the_load_threshold_is_strictly_greater_than_the_configured_floor(self, table):
        seed(table, _todoist("DATE#2026-05-09", active_task_count=300, overdue_count=15, due_today_count=0))
        assert di._compute_decision_fatigue_alert(YESTERDAY, [_hs("2026-05-08", tier0_pct=0.10)])[0] is False

    def test_healthy_habits_suppress_the_alert_however_high_the_load(self, table):
        seed(table, _todoist("DATE#2026-05-09", active_task_count=300, overdue_count=200, due_today_count=50))
        assert di._compute_decision_fatigue_alert(YESTERDAY, [_hs("2026-05-08", tier0_pct=0.95)])[0] is False

    def test_the_alert_breaks_the_load_down_into_overdue_and_due_today(self, table):
        seed(table, _todoist("DATE#2026-05-09", active_task_count=300, overdue_count=20, due_today_count=5))
        block = di._compute_decision_fatigue_alert(YESTERDAY, [_hs("2026-05-08", tier0_pct=0.30)])[1]
        assert "25 tasks (20 overdue + 5 due today)" in block

    def test_the_alert_states_the_habit_rate_it_fired_on(self, table):
        seed(table, _todoist("DATE#2026-05-09", active_task_count=300, overdue_count=20, due_today_count=5))
        block = di._compute_decision_fatigue_alert(YESTERDAY, [_hs("2026-05-08", tier0_pct=0.30)])[1]
        assert "T0 habit completion: 30% this week" in block

    def test_a_query_failure_is_non_fatal(self, table):
        table.query_error = RuntimeError("throttled")
        assert di._compute_decision_fatigue_alert(YESTERDAY, [_hs("2026-05-08", tier0_pct=0.30)]) == (False, "")

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "DEFECT (tranche-2 discovery): the T0 rate is read as "
            "`safe_float(r,'tier0_pct') or safe_float(r,'t0_completion_rate')`. A "
            "genuine 0.0 completion day is falsy, so it coalesces to the (never-"
            "written) fallback field and is dropped from the 7-day mean — the "
            "worst days are exactly the ones excluded, biasing the average UP and "
            "suppressing the alert when it is most warranted."
        ),
    )
    def test_a_zero_completion_day_counts_toward_the_weekly_habit_average(self, table):
        seed(table, _todoist("DATE#2026-05-09", active_task_count=300, overdue_count=20, due_today_count=5))
        habits = [_hs("2026-05-07", tier0_pct=0.0), _hs("2026-05-08", tier0_pct=1.0)]
        # true mean = 0.5 < 0.60 → should fire; dropping the zero gives 1.0 → silent
        assert di._compute_decision_fatigue_alert(YESTERDAY, habits)[0] is True


# ──────────────────────────────────────────────────────────────────────────────
# S2-T1-9 deficit ceiling
# ──────────────────────────────────────────────────────────────────────────────


class TestDeficitCeiling:
    WT_START = _days(YEST_D, 13)
    HRV_BASE_START, HRV_BASE_END = _days(YEST_D, 21), _days(YEST_D, 8)
    HRV_RECENT_START = _days(YEST_D, 7)

    def _fetcher(self, monkeypatch, *, weights=None, hrv_baseline=None, hrv_recent=None, sleep_eff=None):
        f = WindowFetcher()
        if weights is not None:
            f.register(
                "withings", self.WT_START, YESTERDAY, [{"date": f"2026-04-{26 + i:02d}", "weight_lbs": w} for i, w in enumerate(weights)]
            )
        if hrv_baseline is not None:
            f.register("whoop", self.HRV_BASE_START, self.HRV_BASE_END, [{"date": f"b{i}", "hrv": v} for i, v in enumerate(hrv_baseline)])
        recent = [dict({"date": f"r{i}"}, **({"hrv": v} if hrv_recent else {})) for i, v in enumerate(hrv_recent or [])]
        if sleep_eff is not None:
            recent = recent or [{"date": f"r{i}"} for i in range(len(sleep_eff))]
            for i, v in enumerate(sleep_eff):
                recent[i]["sleep_efficiency_percentage"] = v
        if hrv_recent is not None or sleep_eff is not None:
            f.register("whoop", self.HRV_RECENT_START, YESTERDAY, recent)
        monkeypatch.setattr(di, "fetch_range", f)
        return f

    def test_a_quiet_week_produces_no_alert(self, monkeypatch):
        self._fetcher(monkeypatch, weights=[300.0] * 8, hrv_baseline=[60.0] * 10, hrv_recent=[60.0] * 5)
        assert di._compute_deficit_ceiling_alert(YESTERDAY, [], [], {}) == (None, "")

    def test_a_loss_rate_past_the_medical_line_fires_the_rate_tier(self, monkeypatch):
        """-0.5 lb/day × 7 = 3.5 lb/week, past the 2.5 threshold."""
        weights = [300.0 - 0.5 * i for i in range(8)]
        self._fetcher(monkeypatch, weights=weights)
        tier, block = di._compute_deficit_ceiling_alert(YESTERDAY, [], [], {})
        assert tier == "rate" and "3.5 lbs/wk" in block

    def test_a_loss_rate_under_the_line_does_not_fire(self, monkeypatch):
        """-0.3 lb/day × 7 = 2.1 lb/week."""
        self._fetcher(monkeypatch, weights=[300.0 - 0.3 * i for i in range(8)])
        assert di._compute_deficit_ceiling_alert(YESTERDAY, [], [], {})[0] is None

    def test_fewer_than_four_weigh_ins_cannot_support_a_rate_claim(self, monkeypatch):
        self._fetcher(monkeypatch, weights=[300.0, 297.0, 294.0])
        assert di._compute_deficit_ceiling_alert(YESTERDAY, [], [], {})[0] is None

    def test_two_physiological_channels_together_fire_the_multi_tier(self, monkeypatch):
        """HRV 60 → 45 is a 25% drop (>15%), and 4 nights under 80% efficiency."""
        self._fetcher(
            monkeypatch, weights=[300.0] * 8, hrv_baseline=[60.0] * 10, hrv_recent=[45.0] * 5, sleep_eff=[70.0, 70.0, 70.0, 70.0, 90.0]
        )
        tier, block = di._compute_deficit_ceiling_alert(YESTERDAY, [], [], {})
        assert tier == "multi" and "MULTI-SIGNAL" in block

    def test_one_channel_alone_is_not_a_multi_signal_alert(self, monkeypatch):
        self._fetcher(monkeypatch, weights=[300.0] * 8, hrv_baseline=[60.0] * 10, hrv_recent=[45.0] * 5, sleep_eff=[95.0] * 5)
        assert di._compute_deficit_ceiling_alert(YESTERDAY, [], [], {})[0] is None

    def test_a_thin_hrv_baseline_cannot_support_the_drop_channel(self, monkeypatch):
        """ADR-105: 6 baseline nights is below the gate — no drop claim."""
        self._fetcher(monkeypatch, weights=[300.0] * 8, hrv_baseline=[60.0] * 6, hrv_recent=[30.0] * 5, sleep_eff=[70.0] * 5)
        assert di._compute_deficit_ceiling_alert(YESTERDAY, [], [], {})[0] is None

    def test_the_habit_channel_counts_distinct_failed_habits_this_week(self, monkeypatch):
        self._fetcher(monkeypatch, weights=[300.0] * 8, hrv_baseline=[60.0] * 10, hrv_recent=[45.0] * 5)
        habits = [_hs("2026-05-07", missed=["water", "steps"]), _hs("2026-05-08", missed=["water"])]
        assert di._compute_deficit_ceiling_alert(YESTERDAY, habits, [], {})[0] == "multi"

    def test_one_repeatedly_failed_habit_is_still_only_one_habit(self, monkeypatch):
        self._fetcher(monkeypatch, weights=[300.0] * 8, hrv_baseline=[60.0] * 10, hrv_recent=[45.0] * 5)
        habits = [_hs(f"2026-05-0{d}", missed=["water"]) for d in (5, 6, 7, 8)]
        assert di._compute_deficit_ceiling_alert(YESTERDAY, habits, [], {})[0] is None

    def test_the_prescription_names_the_exact_new_calorie_ceiling(self, monkeypatch):
        """1700 + 200 = 1900 kcal for 5 days."""
        self._fetcher(monkeypatch, weights=[300.0 - 0.5 * i for i in range(8)])
        block = di._compute_deficit_ceiling_alert(YESTERDAY, [], [], {"calorie_target": 1700, "protein_target_g": 200})[1]
        assert "1700 → 1900 kcal/day" in block and "Maintain protein at 200g" in block
        assert "Reassess trend at day 5" in block

    def test_the_alert_carries_the_medical_disclaimer(self, monkeypatch):
        """R13-F09: a prescription-shaped block must say it is not medical advice."""
        self._fetcher(monkeypatch, weights=[300.0 - 0.5 * i for i in range(8)])
        block = di._compute_deficit_ceiling_alert(YESTERDAY, [], [], {})[1]
        assert "Consult a qualified healthcare provider" in block

    def test_a_read_failure_is_non_fatal(self, monkeypatch):
        def boom(*a):
            raise RuntimeError("throttled")

        monkeypatch.setattr(di, "fetch_range", boom)
        assert di._compute_deficit_ceiling_alert(YESTERDAY, [], [], {}) == (None, "")


# ──────────────────────────────────────────────────────────────────────────────
# The assembled AI context block
# ──────────────────────────────────────────────────────────────────────────────


def _empty_context_block(**overrides):
    """Call build_ai_context_block with every signal off except the overrides."""
    kwargs = dict(
        momentum_signal="unknown",
        this_week_avg=None,
        prev_week_avg=None,
        trend_pct=None,
        declining=[],
        improving=[],
        miss_rates={},
        strongest=[],
        weakest=[],
        synergy_health={},
        memory_ctx="",
    )
    kwargs.update(overrides)
    return di.build_ai_context_block(**kwargs)


def _drift(metric, severity, worsening=True, **fields):
    return {
        "metric": metric,
        "severity": severity,
        "worsening": worsening,
        "drift_sd": -1.5,
        "recent_mean": 49.0,
        "baseline_mean": 52.0,
        "baseline_n": 14,
        "p_value": 0.0032,
        **fields,
    }


class TestBuildAiContextBlock:
    def test_a_completely_quiet_day_produces_only_the_frame(self):
        """ADR-104: nothing to say means nothing is said, not a filler insight."""
        block = _empty_context_block()
        assert block.splitlines() == ["PLATFORM INTELLIGENCE (7-day context, pre-computed):", "", block.splitlines()[-1]]

    def test_the_early_warning_outranks_every_other_signal(self):
        block = _empty_context_block(early_warning_block="EARLY-WARN", memory_ctx="MEM", this_week_avg=70.0, momentum_signal="stable")
        lines = block.splitlines()
        assert lines.index("EARLY-WARN") < lines.index("MEM")

    def test_a_multi_signal_deficit_alert_outranks_a_rate_only_one(self):
        multi = _empty_context_block(deficit_ceiling_block="DEF", deficit_ceiling_tier="multi", early_warning_block="WARN")
        assert multi.splitlines().index("DEF") in (1, 2)

    def test_a_deficit_block_with_no_tier_is_not_injected(self):
        assert "DEF" not in _empty_context_block(deficit_ceiling_block="DEF", deficit_ceiling_tier=None)

    def test_a_severe_drift_line_carries_its_sample_size_and_p_value(self):
        """ADR-105: the number never travels without its uncertainty."""
        block = _empty_context_block(slow_drift_metrics=[_drift("HRV", "severe")])
        line = [ln for ln in block.splitlines() if "SLOW DRIFT" in ln][0]
        assert "N=14" in line and "p=0.0032" in line and "1.5 SD" in line

    def test_a_weight_plateau_reports_its_weigh_in_and_log_day_counts(self):
        plateau = {
            "metric": "Weight Plateau",
            "severity": "significant",
            "worsening": True,
            "slope_lbs_week": 0.05,
            "measurements_n": 9,
            "complete_log_days": 12,
            "tdee_source": "MacroFactor",
            "note": "recomp caveat",
        }
        line = [ln for ln in _empty_context_block(slow_drift_metrics=[plateau]).splitlines() if "WEIGHT PLATEAU" in ln][0]
        assert "+0.05 lbs/wk over 9 weigh-ins, 12 complete log days" in line and "recomp caveat" in line

    def test_at_most_two_changepoints_are_surfaced(self):
        cps = [dict(TestFormatChangepointLine.BASE, date=f"2026-04-2{i}") for i in range(4)]
        block = _empty_context_block(changepoints=cps)
        assert sum(1 for ln in block.splitlines() if "REGIME SHIFT" in ln) == 2

    def test_an_adverse_regime_shift_outranks_a_favorable_one(self):
        adverse = dict(TestFormatChangepointLine.BASE, worsening=True, metric="HRV")
        favorable = dict(TestFormatChangepointLine.BASE, worsening=False, metric="RHR", direction="increase")
        lines = _empty_context_block(changepoints=[favorable, adverse]).splitlines()
        assert [i for i, ln in enumerate(lines) if "HRV" in ln][0] < [i for i, ln in enumerate(lines) if "RHR" in ln][0]

    def test_at_most_two_declining_metrics_are_surfaced(self):
        declining = [
            {"metric": f"m{i}", "consecutive_days": 3, "current": 50, "baseline_7d_avg": 60.0, "delta_pct": -10.0} for i in range(4)
        ]
        assert sum(1 for ln in _empty_context_block(declining=declining).splitlines() if "LEADING INDICATOR" in ln) == 2

    def test_an_unknown_momentum_produces_no_momentum_line(self):
        """ADR-104: no grade history is not a stable week."""
        assert "Momentum" not in _empty_context_block(momentum_signal="unknown", this_week_avg=None)

    def test_an_improving_momentum_line_states_both_week_averages(self):
        block = _empty_context_block(momentum_signal="improving", this_week_avg=85.0, prev_week_avg=60.0, trend_pct=41.7)
        assert "Momentum: IMPROVING (60.0→85.0 avg grade, +41.7% WoW)" in block

    def test_a_declining_momentum_line_states_the_signed_trend(self):
        block = _empty_context_block(momentum_signal="declining", this_week_avg=60.0, prev_week_avg=85.0, trend_pct=-29.4)
        assert "Momentum: DECLINING (85.0→60.0 avg grade, -29.4% WoW)" in block

    def test_the_weakest_habits_line_converts_the_miss_rate_to_days(self):
        """0.57 × 7 = 3.99 → 4 days."""
        block = _empty_context_block(weakest=["water"], miss_rates={"water": 0.57})
        assert "water (missed 4/7 days)" in block

    def test_only_broken_synergy_stacks_are_named(self):
        block = _empty_context_block(synergy_health={"evening": 0.4, "morning": 0.9})
        assert "Broken synergy stacks: evening" in block and "morning" not in block

    def test_the_social_flag_is_the_lowest_priority_signal(self):
        block = _empty_context_block(social_flag="SOCIAL", memory_ctx="MEM", corr_ctx="CORR")
        lines = block.splitlines()
        assert lines.index("SOCIAL") > lines.index("MEM") and lines.index("SOCIAL") > lines.index("CORR")


# ──────────────────────────────────────────────────────────────────────────────
# The DynamoDB write
# ──────────────────────────────────────────────────────────────────────────────


FULL_PAYLOAD = {
    "momentum_signal": "improving",
    "week_grade_avg": 85.0,
    "prev_week_grade_avg": 60.0,
    "grade_trend_pct": 41.66666,
    "declining_metrics": [{"metric": "recovery"}],
    "improving_metrics": [{"metric": "readiness_score"}],
    "miss_rates": {"water": 0.5},
    "strongest": ["steps"],
    "weakest": ["water"],
    "synergy_health": {"evening": 0.4},
    "memory_context": "MEM",
    "ai_context_block": "BLOCK",
    "slow_drift_metrics": [{"metric": "HRV", "drift_sd": -1.45}],
    "changepoints": [{"metric": "HRV", "confidence": 0.996}],
}


class TestStoreComputedInsights:
    def test_the_record_is_keyed_to_the_computed_insights_partition_and_date(self, table):
        di.store_computed_insights(YESTERDAY, dict(FULL_PAYLOAD))
        item = table.puts[0]
        assert item["pk"] == di.USER_PREFIX + "computed_insights"
        assert item["sk"] == "DATE#" + YESTERDAY and item["date"] == YESTERDAY

    def test_no_python_float_ever_reaches_dynamodb(self, table):
        """boto3 rejects float — every number is a Decimal or a JSON string."""
        di.store_computed_insights(YESTERDAY, dict(FULL_PAYLOAD))

        def walk(v):
            assert not isinstance(v, float), f"raw float in the stored item: {v!r}"
            if isinstance(v, dict):
                for x in v.values():
                    walk(x)
            elif isinstance(v, list):
                for x in v:
                    walk(x)

        walk(table.puts[0])

    def test_the_grade_figures_are_stored_as_rounded_decimals(self, table):
        di.store_computed_insights(YESTERDAY, dict(FULL_PAYLOAD))
        item = table.puts[0]
        assert item["week_grade_avg"] == Decimal("85.0") and item["grade_trend_pct"] == Decimal("41.6667")

    def test_the_structured_analyses_round_trip_as_json(self, table):
        di.store_computed_insights(YESTERDAY, dict(FULL_PAYLOAD))
        item = table.puts[0]
        assert json.loads(item["slow_drift_metrics"]) == FULL_PAYLOAD["slow_drift_metrics"]
        assert json.loads(item["changepoints"]) == FULL_PAYLOAD["changepoints"]
        assert json.loads(item["habit_miss_rates_7d"]) == {"water": 0.5}

    def test_absent_payload_keys_are_omitted_rather_than_written_as_null(self, table):
        """ADR-104: an absent analysis must not appear as an empty finding."""
        di.store_computed_insights(YESTERDAY, {"momentum_signal": "stable"})
        item = table.puts[0]
        for absent in ("week_grade_avg", "slow_drift_metrics", "changepoints", "weakest_habits"):
            assert absent not in item

    def test_an_empty_analysis_list_is_omitted_rather_than_stored_empty(self, table):
        di.store_computed_insights(YESTERDAY, {"momentum_signal": "stable", "declining_metrics": [], "changepoints": []})
        assert "declining_metrics" not in table.puts[0] and "changepoints" not in table.puts[0]

    def test_the_record_is_phase_stamped_so_a_reset_can_hide_it(self, table):
        """ADR-058: an unstamped row passes the default-deny filter as current."""
        di.store_computed_insights(YESTERDAY, dict(FULL_PAYLOAD))
        assert table.puts[0]["phase"] in ("pilot", "experiment")

    def test_a_record_the_validator_rejects_is_never_written(self, table, monkeypatch):
        """DATA-2: the write is gated on validate_item, not merely logged."""
        from ingestion import ingestion_validator

        real = ingestion_validator.validate_item

        def rejecting(source, item, date_str=""):
            result = real(source, item, date_str)
            result.errors.append("synthetic critical failure")  # should_skip_ddb derives from errors
            return result

        monkeypatch.setattr(ingestion_validator, "validate_item", rejecting)
        di.store_computed_insights(YESTERDAY, dict(FULL_PAYLOAD))
        assert table.puts == []

    def test_a_validator_crash_does_not_block_the_write(self, table, monkeypatch):
        """Fail-soft: a broken validator must not silently drop the day's insight."""
        from ingestion import ingestion_validator

        def boom(*a, **k):
            raise RuntimeError("validator exploded")

        monkeypatch.setattr(ingestion_validator, "validate_item", boom)
        di.store_computed_insights(YESTERDAY, dict(FULL_PAYLOAD))
        assert len(table.puts) == 1

    def test_a_record_with_only_a_context_block_satisfies_validation(self, table):
        di.store_computed_insights(YESTERDAY, {"ai_context_block": "BLOCK"})
        assert len(table.puts) == 1


# ──────────────────────────────────────────────────────────────────────────────
# Handler
# ──────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def offline_handler(monkeypatch, table):
    """Neutralise the one network-touching path; everything else runs for real."""

    def no_secret():
        raise RuntimeError("no secrets manager offline")

    monkeypatch.setattr(di, "_get_api_key", no_secret)
    return table


class TestHandler:
    def test_a_healthcheck_returns_ok_without_touching_the_table(self, offline_handler):
        assert di.lambda_handler({"healthcheck": True}, None) == {"statusCode": 200, "body": "ok"}
        assert offline_handler.queries == [] and offline_handler.puts == []

    def test_the_default_target_date_is_yesterday(self, offline_handler):
        out = di.lambda_handler({}, None)
        assert out["body"] == f"Insights computed for {YESTERDAY}"
        assert offline_handler.puts[-1]["sk"] == "DATE#" + YESTERDAY

    def test_an_already_computed_day_is_skipped_without_a_rewrite(self, offline_handler):
        seed(offline_handler, _date_row("computed_insights", YESTERDAY, momentum_signal="stable"))
        out = di.lambda_handler({}, None)
        assert out["skipped"] is True and offline_handler.puts == []

    def test_force_recomputes_a_day_that_already_exists(self, offline_handler):
        seed(offline_handler, _date_row("computed_insights", YESTERDAY, momentum_signal="stable"))
        out = di.lambda_handler({"force": True}, None)
        assert "skipped" not in out and any(p["sk"] == "DATE#" + YESTERDAY for p in offline_handler.puts)

    def test_an_explicit_date_overrides_the_default(self, offline_handler):
        out = di.lambda_handler({"date": "2026-05-07"}, None)
        assert out["body"] == "Insights computed for 2026-05-07"

    def test_the_return_payload_summarises_every_detector(self, offline_handler):
        out = di.lambda_handler({}, None)
        for key in (
            "momentum",
            "declining_count",
            "improving_count",
            "weakest_habits",
            "ic8_active",
            "ic5_warning",
            "ic5_markers",
            "decision_fatigue_fired",
            "deficit_ceiling_tier",
            "changepoint_count",
        ):
            assert key in out

    def test_an_empty_platform_reports_unknown_momentum_rather_than_a_number(self, offline_handler):
        """ADR-104: day one is 'unknown', not a stable 0."""
        out = di.lambda_handler({}, None)
        assert out["momentum"] == "unknown"
        assert "week_grade_avg" not in offline_handler.puts[-1]

    def test_a_real_grade_history_reaches_the_stored_record(self, offline_handler):
        for d, s in (("2026-05-08", 90), ("2026-05-07", 80), ("2026-05-01", 60), ("2026-04-30", 60)):
            seed(offline_handler, _date_row("day_grade", d, total_score=Decimal(str(s))))
        di.lambda_handler({}, None)
        item = offline_handler.puts[-1]
        assert item["momentum_signal"] == "improving" and item["week_grade_avg"] == Decimal("85.0")

    def test_a_failing_sub_computation_does_not_abort_the_run(self, offline_handler, monkeypatch):
        """Fail-soft: slow drift dying must still leave a stored record."""

        def boom(*a, **k):
            raise RuntimeError("stats exploded")

        monkeypatch.setattr(di, "_compute_slow_drift", boom)
        monkeypatch.setattr(di, "_compute_changepoints", boom)
        monkeypatch.setattr(di, "_build_experiment_context", boom)
        out = di.lambda_handler({}, None)
        assert out["statusCode"] == 200 and offline_handler.puts[-1]["sk"] == "DATE#" + YESTERDAY

    def test_an_unreachable_inference_key_leaves_the_intent_gap_inactive(self, offline_handler):
        assert di.lambda_handler({}, None)["ic8_active"] is False

    def test_prior_guidance_from_the_last_three_days_is_injected_for_anti_repetition(self, offline_handler):
        seed(offline_handler, _date_row("computed_insights", "2026-05-07", guidance_given=json.dumps(["walk after dinner"])))
        di.lambda_handler({}, None)
        assert "AVOID REPEATING" in offline_handler.puts[-1]["ai_context_block"]
        assert "walk after dinner" in offline_handler.puts[-1]["ai_context_block"]

    def test_weekly_correlations_are_injected_with_their_coefficients(self, offline_handler):
        seed(
            offline_handler,
            _row("weekly_correlations", "DATE#2026-05-04", pairs=json.dumps([{"label_a": "Sleep", "label_b": "HRV", "r": 0.62}])),
        )
        di.lambda_handler({}, None)
        assert "Sleep ↔ HRV (r=0.62)" in offline_handler.puts[-1]["ai_context_block"]

    def test_a_high_grade_week_is_recorded_as_a_what_worked_memory(self, offline_handler):
        for d in ("2026-05-08", "2026-05-07", "2026-05-06"):
            seed(offline_handler, _date_row("day_grade", d, total_score=Decimal("90")))
        di.lambda_handler({}, None)
        assert any(p["sk"].startswith("MEMORY#what_worked#") for p in offline_handler.puts)

    def test_the_social_flag_needs_both_multiple_drift_and_a_sparse_journal(self, offline_handler, monkeypatch):
        monkeypatch.setattr(di, "_compute_slow_drift", lambda *a: [_drift("HRV", "severe"), _drift("Recovery Score", "severe")])
        for d in ("2026-05-06", "2026-05-07", "2026-05-08"):
            seed(offline_handler, _date_row("computed_metrics", d, component_scores={"journal": Decimal("10")}))
        di.lambda_handler({}, None)
        assert "SOCIAL NOTE" in offline_handler.puts[-1]["ai_context_block"]

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "DEFECT (tranche-2 discovery): the handler anchors its 7d/14d windows "
            "on datetime.now() (`today - 7d`) but ends them at the event's "
            "`date`. Backfilling any date older than a week produces an INVERTED "
            "range (start > end), so momentum, metric trends and habit patterns "
            "silently read zero records — while slow drift and changepoints, "
            "which anchor on yesterday_str, read correctly. The backfilled record "
            "is half-computed with no error raised."
        ),
    )
    def test_a_backfilled_date_reads_the_window_ending_at_that_date(self, offline_handler):
        target = "2026-04-09"
        for d in ("2026-04-08", "2026-04-07", "2026-04-01", "2026-03-31"):
            seed(offline_handler, _date_row("day_grade", d, total_score=Decimal("90" if d > "2026-04-02" else "60")))
        out = di.lambda_handler({"date": target}, None)
        assert out["momentum"] != "unknown", "a backfilled day must see its own trailing window"
