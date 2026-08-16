"""tests/test_genesis_blind_compute_windows_2109.py — the COMPUTE layer's trailing
windows, forecasts, data inventory and AI-context recency reads go cross-phase (#2109).

#2090 widened the #2079 AST ratchet to resolve module-level `#SOURCE#` constants, which
surfaced ~30 previously invisible phase-filtered raw-source reads. Most classified as
sanctioned current-cycle views; seven were the #1203/#2023/#2080/#2081/#2089 defect class
verbatim — trailing windows and recency reads over never-hidden measured series that
truncate to the CYCLE'S AGE after every reset, because the reset tags every pre-genesis
row `phase=pilot` (ADR-077) and these readers applied the ADR-058 filter unconditionally.

Measured on cycle 12 Day 2 (genesis 2026-08-03), a 90-day COUNT over SOURCE#whoop
returned **137 rows unfiltered and 1 filtered**. That single number is the whole issue:

  * `daily_insight_compute_lambda.fetch_range` — the 14d-vs-28d biometric drift windows,
    the 30d HRV baseline, the withings/macrofactor 14d windows, the supplement-effect
    windows and the changepoint series. A baseline-vs-recent comparison with nothing in
    the baseline arm silently produces no insight at all.
  * `daily_metrics_compute_lambda.fetch_range` — the 7/30d HRV baselines, the 60d
    Strava/Hevy Banister windows, the 7/14/28/30d weight windows. Widest blast radius in
    the set: this Lambda WRITES `computed_metrics`, which the cockpit, the coaches, the
    brief and the site API all inherit. Truncated, the load model collapses to
    CTL = ATL = TSB = 0.0, which every downstream band reads as perfect freshness rather
    than as no data.
  * `dashboard_refresh_lambda.fetch_range` — the same trailing-window class again.
  * `forecast_engine_lambda.fetch_series` — the EWMA TRAINING series and the actuals every
    matured forecast is graded against (ADR-105), fit on stub windows exactly when readers
    are watching a fresh cycle start.
  * `intelligence_common.build_data_inventory` — the #1203 liveness shape at its
    highest-leverage site: `days_of_data` is what decides whether a coach speaks in
    ORIENTATION, EMERGING or ESTABLISHED voice, and `latest` is what the validator calls
    staleness. Its `Limit: 1` half is the #1203 mechanism exactly.
  * `site_api_ai_lambda._latest_item` — newest-first `Limit: 1` recency reads (withings,
    whoop) for the AI ask's context block.
  * `daily_brief_lambda.gather_daily_data` — the SOURCE#travel `TRIP#` read. TRIP# rows
    carry no date in their sort key, so the tagger falls through to its timestamp
    fallbacks and tags a trip by when it was BOOKED; a trip booked pre-genesis but
    occurring in-cycle was hidden from the brief.

The contract is the one #2079/#2080/#2081/#2089 settled: the BODY's timeseries does not
reset when the experiment does, and the DATE WINDOW is what bounds recency — not the
phase tag. The fix is emphatically NOT a blanket flip: these same readers are also called
with `computed_metrics`, `habit_scores`, `computed_insights` and `adaptive_mode`, which
ARE EXPERIMENT_SCOPED — derived intelligence the reset tombstones on purpose. Each
reader's decision is therefore DERIVED per source from `phase_taxonomy`, through one
shared definition (`experiment.phase_filter.source_reads_cross_phase`) rather than six
copies, so a call site added later inherits the right behaviour from the source's own
class instead of from whoever wrote the call.

Structure follows tests/test_genesis_blind_brief_windows_2089.py, whose DynamoDB fake is
reused rather than re-implemented (one definition of "Limit lands before the filter"):

  1. non-vacuous anchors — every site's blindfold is reproduced against a `pre_fix`
     revert of that site, so nothing below tests nothing;
  2. the instances — a genesis-day fixture per reader, asserting the window is whole;
  3. the negative cases — the window still bounds the answer, an absent source is still
     absent, and every EXPERIMENT_SCOPED caller stays current-cycle;
  4. the SETS, derived by AST (or from each module's own config constant) and checked
     against phase_taxonomy, so a future call site cannot inherit either behaviour by
     accident — guard the SET, not the instance.

Every date here is PINNED (`_TODAY`, `_GENESIS`); nothing does now-math against the wall
clock, so this file cannot start failing on a calendar boundary.
"""

from __future__ import annotations

import ast
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("EMAIL_RECIPIENT", "test@example.com")
os.environ.setdefault("EMAIL_SENDER", "noreply@example.com")

sys.path.insert(0, str(REPO_ROOT / "tests"))
sys.path.insert(0, str(REPO_ROOT / "lambdas"))
sys.path.insert(0, str(REPO_ROOT / "lambdas" / "compute"))
sys.path.insert(0, str(REPO_ROOT / "lambdas" / "emails"))
sys.path.insert(0, str(REPO_ROOT / "lambdas" / "web"))

import daily_brief_lambda as brief  # noqa: E402
import daily_insight_compute_lambda as insight  # noqa: E402
import daily_metrics_compute_lambda as metrics  # noqa: E402
import dashboard_refresh_lambda as dashboard  # noqa: E402
import forecast_engine_lambda as forecast  # noqa: E402
from experiment import phase_taxonomy as tax  # noqa: E402
from experiment.phase_filter import source_reads_cross_phase  # noqa: E402
from intelligence import intelligence_common as ic  # noqa: E402
from test_genesis_blind_reads_2080_2081 import PhaseAwareFakeTable, _rows  # noqa: E402

# #2667: the recency layer (incl. _latest_item + its phase-filter usage) moved to the
# extracted context sibling; runtime calls still route via the lambda's re-export, but
# module-global patches and source derivations must target where the code now lives.
from web import (
    site_api_ai_context as site_ctx,  # noqa: E402
    site_api_ai_lambda as site_ai,
)  # noqa: E402  (#2667: canonical package form — the context sibling resolves `web.site_api_ai_lambda`, and a bare-name twin would take the patches while the code reads the canonical instance)

# Pinned clock. _GENESIS == _TODAY is "the reset happened this morning" — the worst case
# for this defect, and the one cycle 12 actually shipped (a same-day genesis).
_TODAY = date(2026, 8, 3)
_GENESIS = _TODAY
_YESTERDAY = (_TODAY - timedelta(days=1)).isoformat()


def _win(days: int) -> tuple[str, str]:
    """The readers' own window shape: (today - days) .. yesterday, inclusive."""
    return (_TODAY - timedelta(days=days)).isoformat(), _YESTERDAY


def _series(source: str, field: str, days: int, value=lambda i: 100.0 + i, end: date | None = None):
    """`days` consecutive daily rows ending at `end`, pilot-tagged before genesis."""
    end = end or (_TODAY - timedelta(days=1))
    return _rows(
        f"USER#matthew#SOURCE#{source}",
        field,
        {end - timedelta(days=i): value(i) for i in range(days)},
        genesis=_GENESIS,
    )


class CountingFakeTable(PhaseAwareFakeTable):
    """PhaseAwareFakeTable plus the two things `build_data_inventory` needs.

    `Select: "COUNT"` returns a Count instead of Items — the shape the 90-day inventory
    sweep reads — and `get_item` exists so a handler that touches it does not explode.
    Everything that makes the defect testable (Limit before filter, window bounds,
    newest-first ordering) is inherited, deliberately not re-implemented.
    """

    def query(self, **kwargs):
        result = super().query(**kwargs)
        if kwargs.get("Select") == "COUNT":
            return {"Count": len(result["Items"]), "Items": []}
        return result

    def get_item(self, **kwargs):
        return {}


# ══════════════════════════════════════════════════════════════════════════════
# Fixtures — one genesis-day table, and a `pre_fix` revert per module
# ══════════════════════════════════════════════════════════════════════════════


def _history_rows():
    """90 days of history across every partition these readers touch, every row
    pre-genesis and therefore pilot-tagged — the state of the table on Day 1."""
    rows = []
    rows += _series("whoop", "hrv", 90, lambda i: 60.0 - i * 0.1)
    rows += _series("withings", "weight_lbs", 90, lambda i: 320.0 + i * 0.1)
    rows += _series("strava", "activities", 90, lambda i: [{"type": "Walk", "moving_time_seconds": 3600}])
    rows += _series("hevy", "workout_count", 90, lambda i: 1.0)
    rows += _series("macrofactor", "calories", 90, lambda i: 2200.0)
    rows += _series("habitify", "completed", 90, lambda i: float(i % 5))
    rows += _series("apple_health", "blood_glucose_avg", 90, lambda i: 105.0)
    rows += _series("supplements", "taken", 90, lambda i: 1.0)
    rows += _series("eightsleep", "sleep_score", 90, lambda i: 80.0)
    rows += _series("day_grade", "grade", 90, lambda i: 3.0)
    rows += _series("garmin", "steps", 90, lambda i: 9000.0)
    rows += _series("notion", "entry", 90, lambda i: "x")
    rows += _series("state_of_mind", "valence", 90, lambda i: 0.1)
    rows += _series("measurements", "waist_in", 90, lambda i: 52.0)
    rows += _series("dexa", "body_fat_pct", 1, lambda i: 41.2, end=date(2026, 6, 14))
    rows += _series("labs", "hba1c", 1, lambda i: 5.9, end=date(2026, 5, 2))
    # The EXPERIMENT_SCOPED partitions these same readers touch. Derived intelligence
    # the reset tombstones on purpose — these must STAY hidden.
    rows += _series("computed_metrics", "readiness", 90, lambda i: 70.0)
    rows += _series("habit_scores", "score", 90, lambda i: 80.0)
    rows += _series("computed_insights", "insight", 90, lambda i: "x")
    rows += _series("adaptive_mode", "mode", 90, lambda i: "build")
    return rows


@pytest.fixture
def table():
    return CountingFakeTable(_history_rows())


@pytest.fixture
def compute_tables(monkeypatch, table):
    """Point every reader under test at the same genesis-day table."""
    for module in (insight, metrics, dashboard, forecast, site_ai, ic, brief):
        monkeypatch.setattr(module, "table", table)
    return table


@pytest.fixture
def pre_fix(monkeypatch):
    """Restore the pre-#2109 read at every site: the phase filter on every source.

    Used only by the anchor tests, which assert the blindfold is reproducible in this
    fixture — the point being that every guard below is non-vacuous. The brief's travel
    read takes a literal `include_pilot=True` rather than the derivation, so its revert
    is a `with_phase_filter` that ignores the flag.
    """
    for module in (insight, metrics, dashboard, forecast, site_ctx, ic):
        monkeypatch.setattr(module, "source_reads_cross_phase", lambda source: False)
    real_filter = brief.with_phase_filter
    monkeypatch.setattr(brief, "with_phase_filter", lambda kwargs, include_pilot=False: real_filter(kwargs))


@pytest.fixture
def frozen_inventory_clock(monkeypatch):
    """Pin `build_data_inventory`'s wall-clock reads to _TODAY.

    It is the one reader here that derives its own window (90 days back from now)
    instead of taking one, so without this the fixture's pinned dates and the
    function's `datetime.now` would drift apart on a calendar boundary.
    """

    class _FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(_TODAY.year, _TODAY.month, _TODAY.day, 12, 0, tzinfo=tz or timezone.utc)

    monkeypatch.setattr(ic, "datetime", _FrozenDatetime)


# ══════════════════════════════════════════════════════════════════════════════
# 1. Non-vacuous anchors — every site's blindfold is reproducible
# ══════════════════════════════════════════════════════════════════════════════


def test_pre_fix_every_trailing_window_is_empty_on_genesis_day(compute_tables, pre_fix):
    """Day 1: every window is entirely pre-genesis, so a phase-filtered read of a
    never-hidden series returns nothing to trend, fit or forecast over."""
    assert insight.fetch_range("whoop", *_win(30)) == []
    assert metrics.fetch_range("strava", *_win(60)) == []
    assert dashboard.fetch_range("withings", *_win(14)) == []
    assert forecast.fetch_series("whoop", "hrv", *_win(90)) == []


def test_pre_fix_recency_reads_return_nothing(compute_tables, pre_fix):
    """The #1203 mechanism at the two recency sites: newest-first `Limit: 1` reads the
    one pilot-tagged newest row, the filter drops it, and the caller sees no data at
    all — indistinguishable from a dead pipe."""
    assert site_ai._latest_item("withings") is None
    assert site_ai._latest_item("whoop") is None


def test_pre_fix_data_inventory_reports_the_pipes_as_empty(compute_tables, pre_fix, frozen_inventory_clock):
    """…and the inventory half, which is what pushes every coach back to ORIENTATION
    voice ("I have 0 nights of data") the morning after a reset."""
    inventory = ic.build_data_inventory()
    assert inventory["whoop"] == {"exists": False, "latest": None, "records": 0, "days_of_data": 0}
    assert inventory["withings"]["days_of_data"] == 0
    assert inventory["macrofactor"]["latest"] is None


def test_pre_fix_the_brief_loses_an_in_cycle_trip(compute_tables, pre_fix):
    """The travel half: a trip booked pre-genesis (so tagged pilot from its ingest
    timestamp) but running THROUGH the brief's date vanishes from the brief."""
    compute_tables.rows.append(_pilot_trip())
    assert brief.gather_daily_data({}, _in_trip_date())["travel_active"] is None


# ══════════════════════════════════════════════════════════════════════════════
# 2. The instances — every window the issue names, on genesis day
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("days", [14, 28, 30])
def test_insight_comparison_windows_are_whole_across_genesis(compute_tables, days):
    """The insight engine's baseline-vs-recent arms. Both ends of a comparison need to
    exist for the comparison to mean anything — a 28-day baseline arm that is empty
    produces silence, not a conservative answer."""
    assert len(insight.fetch_range("whoop", *_win(days))) == days
    assert len(insight.fetch_range("withings", *_win(days))) == days


def test_insight_baseline_and_recent_arms_both_populate(compute_tables):
    """The engine's actual drift shape: a recent 14-day arm and a NON-OVERLAPPING
    14-day baseline arm behind it, both from the same pre-genesis history."""
    yest = _TODAY - timedelta(days=1)
    recent = insight.fetch_range("whoop", (yest - timedelta(days=14)).isoformat(), (yest - timedelta(days=1)).isoformat())
    baseline = insight.fetch_range("whoop", (yest - timedelta(days=28)).isoformat(), (yest - timedelta(days=15)).isoformat())
    assert len(recent) == 14 and len(baseline) == 14
    assert {r["sk"] for r in recent}.isdisjoint({r["sk"] for r in baseline})


@pytest.mark.parametrize("source,days", [("whoop", 7), ("whoop", 30), ("strava", 60), ("hevy", 60), ("withings", 28)])
def test_metrics_engine_windows_are_whole_across_genesis(compute_tables, source, days):
    """The HRV baselines, the 60-day Banister load windows and the trailing weight
    windows behind every `computed_metrics` field readers inherit."""
    assert len(metrics.fetch_range(source, *_win(days))) == days


def test_banister_load_is_not_a_zeroed_stub_on_genesis_day(compute_tables):
    """The reader-facing consequence, computed the way the metrics engine computes it:
    a steady 60-day walking block yields a real CTL/ATL/TSB. Truncated to zero days the
    model returns 0.0 across the board, which downstream bands read as PERFECT freshness
    rather than as no data — the failure is silent and flattering, which is why it needs
    a pin rather than a comment."""
    strava_60d = metrics.fetch_range("strava", *_win(60))
    assert len(strava_60d) == 60
    ctl, atl, tsb = metrics.training_load.compute_ctl_atl_tsb(strava_60d, _TODAY)
    assert ctl > 0 and atl > 0
    assert not (ctl == atl == tsb == 0.0)


@pytest.mark.parametrize("source,days", [("withings", 7), ("withings", 14), ("strava", 60), ("hevy", 60), ("macrofactor", 30)])
def test_dashboard_windows_are_whole_across_genesis(compute_tables, source, days):
    assert len(dashboard.fetch_range(source, *_win(days))) == days


@pytest.mark.parametrize("source,field", [("whoop", "hrv"), ("withings", "weight_lbs")])
def test_forecast_training_series_survives_a_reset(compute_tables, source, field):
    """The EWMA's training data. `fetch_series` drops days missing the field, so the
    assertion is on real (date, value) pairs, not row counts."""
    series = forecast.fetch_series(source, field, *_win(90))
    assert len(series) == 90
    assert all(isinstance(v, float) for _, v in series)
    assert series == sorted(series), "the series must stay date-ordered"


def test_the_forecast_engine_can_actually_issue_on_genesis_day(compute_tables):
    """End to end through the engine's own math: with the history restored, the EWMA
    clears its minimum-n bar and issues an interval. On a truncated window it returns
    None and the forecast surface goes silent on Day 1."""
    values = [v for _, v in forecast.fetch_series("withings", "weight_lbs", *_win(90))]
    fc = forecast.stats_core.ewma_forecast(values, horizon=7, confidence=forecast.CONFIDENCE)
    assert fc is not None, "the forecast engine still has no history to fit on"
    assert fc["lo"] < fc["point"] < fc["hi"]


def test_data_inventory_reports_the_bodys_history_not_the_cycles_age(compute_tables, frozen_inventory_clock):
    """The maturity/recency inventory. 90 days of pre-genesis whoop history must read as
    90 days of data with a real `latest`, because that is what the coaches' ORIENTATION /
    EMERGING / ESTABLISHED thresholds are asking about."""
    inventory = ic.build_data_inventory()
    assert inventory["whoop"]["exists"] is True
    assert inventory["whoop"]["days_of_data"] == 90
    assert inventory["whoop"]["latest"] == _YESTERDAY
    assert inventory["withings"]["days_of_data"] == 90
    assert inventory["labs"]["exists"] is False, "a 5-month-old lab draw is outside the 90-day window, correctly"


def test_data_inventory_maturity_clears_orientation_on_genesis_day(compute_tables, frozen_inventory_clock):
    """The consequence the issue is actually about: with the history visible, the sleep
    coach is ESTABLISHED on Day 1 rather than re-introducing itself. `_MATURITY_THRESHOLDS`
    is read from the module so this cannot drift from the real bar."""
    inventory = ic.build_data_inventory()
    threshold = ic._MATURITY_THRESHOLDS["sleep"]
    assert inventory[threshold["source"]]["days_of_data"] >= threshold["established"]


@pytest.mark.parametrize("source", ["withings", "whoop"])
def test_site_api_ai_recency_reads_survive_a_reset(compute_tables, source):
    """The AI ask's context block: the latest weigh-in and last night's recovery are
    still there on Day 1, instead of the ask being told there is no reading at all."""
    item = site_ai._latest_item(source)
    assert item is not None, f"{source}: the latest reading vanished after the reset"
    assert item["sk"] == "DATE#" + _YESTERDAY


def _pilot_trip():
    """A trip BOOKED before genesis (hence pilot-tagged by the tagger's ingest-timestamp
    fallback — TRIP# rows carry no date in their sk) but OCCURRING after it."""
    return {
        "pk": "USER#matthew#SOURCE#travel",
        "sk": "TRIP#tokyo-2026-08",
        "start_date": (_GENESIS + timedelta(days=1)).isoformat(),
        "end_date": (_GENESIS + timedelta(days=9)).isoformat(),
        "destination_city": "Tokyo",
        "destination_country": "Japan",
        "destination_timezone": "Asia/Tokyo",
        "tz_offset_hours": 9,
        "direction": "east",
        "phase": "pilot",
    }


def _in_trip_date():
    return (_GENESIS + timedelta(days=3)).isoformat()


def test_the_brief_sees_a_trip_booked_before_genesis(compute_tables):
    """Acceptance for the travel arm: what decides whether a trip is active is its own
    start_date/end_date — which the brief's own loop checks — not when it was booked."""
    compute_tables.rows.append(_pilot_trip())
    travel = brief.gather_daily_data({}, _in_trip_date())["travel_active"]
    assert travel is not None, "a trip booked before the reset is still a trip"
    assert travel["destination"] == "Tokyo"
    assert travel["tz_offset"] == 9


# ══════════════════════════════════════════════════════════════════════════════
# 3. The negative cases — the fix widened the phase tag, not the question
# ══════════════════════════════════════════════════════════════════════════════


def test_the_window_still_bounds_the_answer(compute_tables):
    """Cross-phase is not unbounded: a 7-day window over a 90-day partition still
    returns 7 rows, and a window outside the history returns nothing. The date range is
    what answers "recent", as the contract says."""
    assert len(metrics.fetch_range("withings", *_win(7))) == 7
    assert metrics.fetch_range("withings", "2020-01-01", "2020-01-05") == []
    assert forecast.fetch_series("whoop", "hrv", "2020-01-01", "2020-01-05") == []


def test_an_absent_source_is_still_absent(compute_tables):
    """A source with no rows at all still reads empty — the fix does not invent data."""
    assert insight.fetch_range("sick_days", *_win(30)) == []
    assert dashboard.fetch_range("sick_days", *_win(30)) == []
    assert site_ai._latest_item("sick_days") is None


def test_a_missing_field_still_drops_out_of_the_forecast_series(compute_tables):
    """`fetch_series` filters on the FIELD, not the phase — a partition without the
    requested field yields an empty series even read cross-phase."""
    assert forecast.fetch_series("whoop", "not_a_field_2109", *_win(90)) == []


@pytest.mark.parametrize("source", ["computed_metrics", "habit_scores"])
def test_experiment_scoped_reads_stay_current_cycle(compute_tables, source):
    """The load-bearing half of "per-source, not blanket". `computed_metrics` and
    `habit_scores` are EXPERIMENT_SCOPED — derived intelligence the reset tombstones on
    purpose — and a blanket include_pilot=True would have widened them silently."""
    assert tax.classify(f"USER#matthew#SOURCE#{source}") == tax.EXPERIMENT_SCOPED
    assert insight.fetch_range(source, *_win(7)) == []
    assert compute_tables.query_calls[-1].get("FilterExpression"), "the scoped read lost its phase filter"


@pytest.mark.parametrize("source", ["computed_metrics", "computed_insights", "adaptive_mode"])
def test_site_api_ai_scoped_reads_stay_current_cycle(compute_tables, source):
    """The same split at the recency site: the AI ask's three scoped reads keep the
    filter while its two raw reads went cross-phase."""
    assert tax.classify(f"USER#matthew#SOURCE#{source}") == tax.EXPERIMENT_SCOPED
    assert site_ai._latest_item(source) is None
    assert compute_tables.query_calls[-1].get("FilterExpression"), "the scoped read lost its phase filter"


def test_cross_phase_reads_carry_no_filter_expression(compute_tables):
    """The complement, asserting the mechanism rather than just the row count."""
    for reader, args in (
        (insight.fetch_range, ("whoop", *_win(7))),
        (metrics.fetch_range, ("strava", *_win(7))),
        (dashboard.fetch_range, ("withings", *_win(7))),
    ):
        reader(*args)
        assert "FilterExpression" not in compute_tables.query_calls[-1]
    site_ai._latest_item("withings")
    assert "FilterExpression" not in compute_tables.query_calls[-1]


def test_an_unclassified_source_keeps_the_current_cycle_filter(compute_tables):
    """Fail-soft and conservative, and NOT theoretical: the insight engine reads
    user-defined experiment metrics whose `source` is whatever the experiment record
    says. `phase_taxonomy.classify` raises for an unknown source by design, and the
    reader must fall back to the PRE-fix behaviour rather than silently widening a read
    nobody has classified."""
    assert source_reads_cross_phase("not_a_real_source_2109") is False
    insight.fetch_range("not_a_real_source_2109", *_win(7))
    assert compute_tables.query_calls[-1].get("FilterExpression")


def test_the_shared_helper_accepts_a_full_partition_key(compute_tables):
    """Both call shapes agree — a bare source name and a full pk classify identically,
    so a caller passing either cannot get a different answer."""
    for source in ("whoop", "habit_scores", "labs"):
        assert source_reads_cross_phase(source) is source_reads_cross_phase(f"USER#matthew#SOURCE#{source}")


# ══════════════════════════════════════════════════════════════════════════════
# 4. The SETS — derived from each reader's own call sites / config constants
# ══════════════════════════════════════════════════════════════════════════════

_MODULE_PATHS = {
    "insight": REPO_ROOT / "lambdas" / "compute" / "daily_insight_compute_lambda.py",
    "metrics": REPO_ROOT / "lambdas" / "compute" / "daily_metrics_compute_lambda.py",
    "dashboard": REPO_ROOT / "lambdas" / "compute" / "dashboard_refresh_lambda.py",
    "forecast": REPO_ROOT / "lambdas" / "compute" / "forecast_engine_lambda.py",
    "site_ai": REPO_ROOT / "lambdas" / "web" / "site_api_ai_context.py",  # #2667: the reader moved here
    "inventory": REPO_ROOT / "lambdas" / "intelligence" / "intelligence_common.py",
}

# (module key, reader function name) for the five AST-derivable readers. The forecast
# engine and the data inventory take their sources from config constants instead, so
# they are derived from those constants below.
_AST_READERS = [
    ("insight", "fetch_range"),
    ("metrics", "fetch_range"),
    ("dashboard", "fetch_range"),
    ("site_ai", "_latest_item"),
]


def _literal_sources_read_by(module_key: str, *func_names: str) -> set[str]:
    """Every literal source name a module passes to the named readers (AST-derived, so a
    call site added later is covered without editing this file)."""
    found: set[str] = set()
    tree = ast.parse(_MODULE_PATHS[module_key].read_text())

    def _names_reader(func) -> bool:
        # Direct call: _latest_item("withings")
        if isinstance(func, ast.Name) and func.id in func_names:
            return True
        # #2667 seam idiom: _hook("_latest_item")("withings") — the context sibling
        # routes intra-layer calls through the lambda namespace so the behavior
        # suite's single patch surface still governs them; the derivation must
        # follow the reader through that indirection or it silently matches
        # nothing and every guard here goes vacuous.
        return (
            isinstance(func, ast.Call)
            and isinstance(func.func, ast.Name)
            and func.func.id == "_hook"
            and func.args
            and isinstance(func.args[0], ast.Constant)
            and func.args[0].value in func_names
        )

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not _names_reader(node.func):
            continue
        if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
            found.add(node.args[0].value)
    return found


def _all_read_sources() -> dict[str, set[str]]:
    """Every source every reader in this PR touches, keyed by module."""
    out = {key: _literal_sources_read_by(key, name) for key, name in _AST_READERS}
    out["forecast"] = {cfg["source"] for cfg in forecast.METRICS}
    out["inventory"] = {partition for _, partition in ic._INVENTORY_SOURCES}
    return out


def test_the_derivations_find_the_known_call_sites():
    """Prove every derivation fires before trusting it to guard anything — an AST walk
    that silently matches nothing would make every assertion below vacuous."""
    sources = _all_read_sources()
    assert {"whoop", "withings", "computed_metrics", "habit_scores"} <= sources["insight"]
    assert {"whoop", "strava", "hevy", "withings", "macrofactor", "habitify"} <= sources["metrics"]
    assert {"withings", "strava", "hevy"} <= sources["dashboard"]
    assert {"withings", "whoop", "computed_metrics", "computed_insights", "adaptive_mode"} <= sources["site_ai"]
    assert {"whoop", "withings"} <= sources["forecast"]
    assert {"whoop", "macrofactor", "notion", "labs"} <= sources["inventory"]


def test_every_source_these_readers_touch_is_classified():
    """No source reaches one of these readers without a taxonomy class — an unclassified
    one would silently take the conservative (genesis-blind) branch, which is safe but
    wrong for a measured series."""
    unclassified = sorted(
        f"{key}:{source}" for key, sources in _all_read_sources().items() for source in sources if source not in tax.SOURCE_CLASS
    )
    assert not unclassified, (
        "these sources are read by the compute layer's shared readers but are absent from "
        "phase_taxonomy.SOURCE_CLASS, so their reads fall back to the genesis-blind branch: " + ", ".join(unclassified)
    )


def test_the_read_decision_agrees_with_the_taxonomy():
    """The guard on the SET rather than the instance: for every source these readers
    actually touch, the cross-phase decision equals "not EXPERIMENT_SCOPED"."""
    for key, sources in _all_read_sources().items():
        for source in sorted(sources):
            expected = tax.classify(f"USER#matthew#SOURCE#{source}") != tax.EXPERIMENT_SCOPED
            assert source_reads_cross_phase(source) is expected, f"{key}:{source} read decision disagrees with phase_taxonomy"


def test_no_reader_reads_a_scoped_source_cross_phase(compute_tables):
    """Stated the other way round, and executed rather than derived: every
    EXPERIMENT_SCOPED source any of these readers touches still sends the filter."""
    scoped = {s for sources in _all_read_sources().values() for s in sources if tax.SOURCE_CLASS.get(s) == tax.EXPERIMENT_SCOPED}
    assert scoped, "the fixture has drifted — none of these readers touches a scoped source any more"
    for source in sorted(scoped):
        insight.fetch_range(source, *_win(7))
        assert compute_tables.query_calls[-1].get("FilterExpression"), f"{source} lost its phase filter"


@pytest.mark.parametrize("module_key,func_name", _AST_READERS + [("forecast", "fetch_series"), ("inventory", "build_data_inventory")])
def test_every_reader_routes_through_the_shared_decision(module_key, func_name):
    """A revert-catcher at the source level: none of these readers may call
    `with_phase_filter` without passing the derived decision. Cheap, and it fires on
    exactly the edit that would silently restore #2109."""
    src = _MODULE_PATHS[module_key].read_text()
    tree = ast.parse(src)
    func = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == func_name)
    seg = (ast.get_source_segment(src, func) or "").replace(" ", "").replace("\n", "")
    assert "with_phase_filter(" in seg, f"{module_key}.{func_name} no longer reads through with_phase_filter"
    assert "include_pilot=" in seg, f"{module_key}.{func_name} no longer derives its phase scope (#2109)"
    assert "source_reads_cross_phase(" in seg, f"{module_key}.{func_name} stopped deriving from the taxonomy (#2109)"


def test_the_brief_travel_read_stays_cross_phase():
    """The travel arm's revert-catcher. It takes a literal rather than the derivation
    (the source is fixed at the call site), so it needs its own pin."""
    src = (REPO_ROOT / "lambdas" / "emails" / "daily_brief_lambda.py").read_text()
    tree = ast.parse(src)
    func = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "gather_daily_data")
    seg = (ast.get_source_segment(src, func) or "").replace(" ", "").replace("\n", "")
    assert 'ExpressionAttributeValues":{":pk":USER_PREFIX+"travel"' in seg, "the travel read moved — re-point this guard"
    assert "include_pilot=True" in seg, "the brief's SOURCE#travel TRIP# read lost its cross-phase flag (#2109)"


def test_the_travel_partition_is_raw_timeseries():
    """The taxonomy premise behind reading TRIP# rows cross-phase, asserted rather than
    assumed: SOURCE#travel is a kept-forever fact layer, not derived intelligence."""
    assert tax.classify("USER#matthew#SOURCE#travel") == tax.RAW_TIMESERIES


def test_the_shared_helper_is_the_only_definition():
    """One definition to keep honest (#2109). The six readers import
    `source_reads_cross_phase` from `experiment.phase_filter`; none of them may grow a
    private copy of the same derivation, which is how six sites drift into five
    behaviours."""
    for key, path in _MODULE_PATHS.items():
        src = path.read_text()
        assert "from experiment.phase_filter import" in src, f"{key} no longer imports the shared read-path helpers"
        assert "def source_reads_cross_phase" not in src, f"{key} grew a private copy of the shared derivation"
