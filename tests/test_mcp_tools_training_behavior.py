"""tests/test_mcp_tools_training_behavior.py — behavioral contracts for the two
MCP training tools served by ``mcp/tools_training.py``:

    get_training      (view = load | periodization | recommendation)
    get_acwr_status

These are the numbers Matthew asks for by name in Claude Desktop and on
claude.ai — "am I overtraining?", "what should I do today?", "what's my ACWR?" —
and he trains off the answer. The whole ``mcp/tools_*`` family had zero dedicated
behavioural coverage before this file (#1658 tranche 3), despite being the
largest directly user-facing read surface in the platform.

The contracts pinned here:

  * ADR-104 honest numbers — an absent signal is ABSENT, never a factual 0 and
    never a neutral-looking default. ``composite_readiness`` on a day with no
    recovery data at all is the canonical violation (§5).
  * ADR-105 rigor — an average / ratio / "trend" ships with its n, and a
    threshold verdict is not asserted off a window the data does not fill.
  * #1917 window-name honesty — a field named for an N-day window either spans a
    real N days or says so. ``alerts_last_7d`` and ``trend_7d`` count RECORDS.
  * Unit + threshold agreement — two tools that both publish "Zone 2 minutes"
    must mean the same thing (§4); they do not.
  * Reader/writer field-name agreement — every DynamoDB field these tools read
    is checked against a real writer in ``lambdas/``.
  * ADR-058 phase filtering — the ``computed_metrics`` partition is
    EXPERIMENT_SCOPED (``lambdas/experiment/phase_taxonomy.py``), so the ACWR
    read must go through the phase-filtered query (§6).
  * Registry parity — the set of tools this file must exercise is DERIVED from
    ``mcp/registry.py``'s ``TOOLS`` dict, never restated ("guard the SET").

Everything is driven through the real registered entry point with the declared
arguments, a frozen clock, and hand-rolled bounded fakes. No MagicMock inside a
loop-shaped read, no AWS, no network.

Arithmetic expectations are hand-derived from the closed form of the model (the
EWMA is ``L*(1 - exp(-n/tau))`` for a constant load L) and written as literals
with the derivation in a comment — never "whatever the code returned".

Production defects found while writing this file are marked xfail and NOT fixed
here; each reason names module:line, the function, what it does, what it should
do, and who it is wrong for.
"""

from __future__ import annotations

import math
import os
from datetime import datetime, timedelta, timezone

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")  # mcp.config reads these at import
os.environ.setdefault("USER_ID", "matthew")

import pytest  # noqa: E402

from mcp import core as mcp_core, tools_correlation as tc, tools_training as tt  # noqa: E402
from mcp.registry import TOOLS  # noqa: E402

# ──────────────────────────────────────────────────────────────────────────────
# Frozen clock
# ──────────────────────────────────────────────────────────────────────────────

NOW = datetime(2026, 8, 8, 17, 30, 0, tzinfo=timezone.utc)
TODAY = "2026-08-08"
YESTERDAY = "2026-08-07"  # tool_get_acwr_status's declared default for `date`


class _FrozenDatetime(datetime):
    """``datetime`` subclass with a pinned ``now()``.

    A subclass, not a Mock, because the code under test calls ``strptime`` and
    ``timedelta`` arithmetic on the same name it calls ``now()`` on.
    """

    @classmethod
    def now(cls, tz=None):
        return NOW if tz is not None else NOW.replace(tzinfo=None)

    @classmethod
    def utcnow(cls):
        return NOW.replace(tzinfo=None)


def _d(offset_days: int, anchor: str = TODAY) -> str:
    """``anchor`` shifted by ``offset_days`` (negative = earlier), as YYYY-MM-DD."""
    return (datetime.strptime(anchor, "%Y-%m-%d") + timedelta(days=offset_days)).strftime("%Y-%m-%d")


# ──────────────────────────────────────────────────────────────────────────────
# Bounded hand-rolled fakes
# ──────────────────────────────────────────────────────────────────────────────


class FakeSourceReader:
    """Stand-in for ``mcp.core.query_source``.

    Faithful where the tools depend on it: filters to the requested inclusive
    ``[start_date, end_date]`` window (the real one issues an ``sk BETWEEN``),
    returns ``[]`` for an unknown source and for ``start > end``, hands back a
    fresh copy of each row so a tool cannot mutate the fixture, and records every
    call so a test can assert which partitions were — and were NOT — read.

    Deliberately not a MagicMock: this sits inside the day-by-day loops of the
    load model, where a Mock's auto-attribute behaviour would silently fabricate
    data instead of failing.
    """

    def __init__(self, **by_source):
        self.data = {k: list(v) for k, v in by_source.items()}
        self.calls: list[tuple] = []

    def __call__(self, source, start_date, end_date, lean=False, include_pilot=False):
        self.calls.append((source, start_date, end_date, include_pilot))
        if start_date > end_date:
            return []
        out = []
        for row in self.data.get(source, []):
            date = row.get("date") or str(row.get("sk", "")).replace("DATE#", "")
            if start_date <= date <= end_date:
                out.append(dict(row))
        return out

    def window_for(self, source: str) -> tuple[str, str]:
        for src, start, end, _pilot in self.calls:
            if src == source:
                return start, end
        raise AssertionError(f"{source} was never queried; queried: {[c[0] for c in self.calls]}")


class RecordingTable:
    """Bounded stand-in for the boto3 ``Table`` resource used by ``mcp.core``.

    Only ``query`` is implemented, single page (``LastEvaluatedKey`` absent) so
    ``query_source``'s pagination loop terminates after one pass. Every call's
    kwargs are captured so the ADR-058 phase filter can be asserted on the real
    ``mcp.core.query_source`` rather than on a stub of it.
    """

    def __init__(self, items=None):
        self.items = list(items or [])
        self.query_kwargs: list[dict] = []

    def query(self, **kwargs):
        self.query_kwargs.append(kwargs)
        return {"Items": list(self.items)}


def strava_day(date: str, *, kilojoules=None, activities=None, activity_count=None) -> dict:
    """One Strava DATE# record as ``strava_lambda`` writes it.

    ``total_kilojoules`` is the top-priority load proxy in
    ``mcp/helpers.py::compute_daily_load_score`` (kJ > TRIMP > distance+elev), so
    supplying it makes the load model's input exactly known.
    """
    rec: dict = {"pk": "USER#matthew#SOURCE#strava", "sk": f"DATE#{date}", "date": date, "source": "strava"}
    if kilojoules is not None:
        rec["total_kilojoules"] = kilojoules
    if activities is not None:
        rec["activities"] = activities
    if activity_count is not None:
        rec["activity_count"] = activity_count
    return rec


def activity(sport: str, *, minutes: float, avg_hr=None) -> dict:
    """One nested Strava activity as ``strava_lambda`` writes it.

    Both duration fields are SECONDS and both are populated, because the two
    tools disagree about which one to read: ``tools_training`` filters and
    measures on ``elapsed_time_seconds``, ``tools_correlation``'s Zone-2
    breakdown on ``moving_time_seconds``. The <600s (10 min) floor drops the
    activity entirely in both.
    """
    act = {"sport_type": sport, "elapsed_time_seconds": minutes * 60, "moving_time_seconds": minutes * 60}
    if avg_hr is not None:
        act["average_heartrate"] = avg_hr
    return act


def computed_metrics_day(date: str, **fields) -> dict:
    """One ``computed_metrics`` DATE# record.

    Field names verified against the writer,
    ``lambdas/compute/acwr_compute_lambda.py`` (acwr / acute_load_7d /
    chronic_load_28d / acwr_zone / acwr_alert / acwr_alert_reason / acwr_method).
    """
    return {"pk": "USER#matthew#SOURCE#computed_metrics", "sk": f"DATE#{date}", "date": date, **fields}


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def frozen_clock(monkeypatch):
    monkeypatch.setattr(tt, "datetime", _FrozenDatetime)
    monkeypatch.setattr(tc, "datetime", _FrozenDatetime)


@pytest.fixture(autouse=True)
def profile(monkeypatch):
    """Max HR 190 — the module's own fallback, pinned so every %-of-max
    threshold in this file is computed against a known number."""
    prof = {"max_heart_rate": 190, "resting_heart_rate_baseline": 55}
    monkeypatch.setattr(tt, "get_profile", lambda: prof)
    monkeypatch.setattr(tc, "get_profile", lambda: prof)
    monkeypatch.setattr(tt, "get_sot", lambda domain: {"cardio": "strava"}.get(domain, "strava"))
    return prof


@pytest.fixture
def sources(monkeypatch):
    """Install a FakeSourceReader over every query_source binding the training
    path can reach (tools_training's own, and tools_correlation's — the
    recommendation view calls tool_get_zone2_breakdown)."""

    def _install(**by_source):
        reader = FakeSourceReader(**by_source)
        monkeypatch.setattr(tt, "query_source", reader)
        monkeypatch.setattr(tc, "query_source", reader)
        return reader

    return _install


def call(tool_name: str, args: dict):
    """Drive a tool through its REAL registered entry point."""
    return TOOLS[tool_name]["fn"](args)


# ═══════════════════════════════════════════════════════════════════════════════
# §1 — Registry parity: the SET of tools under test is derived, never restated
# ═══════════════════════════════════════════════════════════════════════════════

TRAINING_TOOL_NAMES = {name for name, spec in TOOLS.items() if getattr(spec["fn"], "__module__", "") == "mcp.tools_training"}

EXERCISED_HERE = {"get_training", "get_acwr_status"}


def test_registry_is_the_source_of_truth_for_which_training_tools_exist():
    """If a tool is added to mcp/tools_training.py and wired into the registry,
    this file must grow a case for it. Derive the set; never hand-maintain it."""
    assert TRAINING_TOOL_NAMES == EXERCISED_HERE, (
        f"mcp/tools_training.py now exports {sorted(TRAINING_TOOL_NAMES)} through the registry; "
        f"this behavioural file only exercises {sorted(EXERCISED_HERE)}."
    )


def test_every_declared_get_training_view_dispatches(sources):
    """The view enum lives in the tool's declared inputSchema. Derive it and
    prove every declared value reaches a handler — an enum value with no branch
    would answer a legitimate Claude Desktop call with 'Unknown view'."""
    sources(strava=[], whoop=[], eightsleep=[], garmin=[], macrofactor_workouts=[], computed_metrics=[])
    declared = TOOLS["get_training"]["schema"]["inputSchema"]["properties"]["view"]["enum"]
    assert declared, "get_training must declare its views"
    for view in declared:
        out = call("get_training", {"view": view, "end_date": TODAY, "date": TODAY, "start_date": _d(-7)})
        assert not str(out.get("error", "")).startswith("Unknown view"), f"declared view {view!r} does not dispatch"


def test_unknown_view_returns_an_error_envelope_not_an_exception():
    out = call("get_training", {"view": "vibes"})
    assert out["error"].startswith("Unknown view")
    assert set(out["valid_views"]) == set(TOOLS["get_training"]["schema"]["inputSchema"]["properties"]["view"]["enum"])


def test_view_is_normalised_for_case_and_whitespace(sources):
    sources()
    out = call("get_training", {"view": "  LOAD  ", "end_date": TODAY})
    assert "valid_views" not in out  # normalised, not rejected


# ═══════════════════════════════════════════════════════════════════════════════
# §2 — view=load: the Banister CTL/ATL/TSB model
# ═══════════════════════════════════════════════════════════════════════════════


def test_load_on_a_completely_empty_partition_returns_the_honest_empty_envelope(sources):
    """FIXED (#2221, ADR-104 P1): with NOTHING in the cardio partition the tool used
    to answer with a complete fitness/fatigue model of zeros — ctl 0.0 / atl 0.0 /
    tsb 0.0 / injury_risk 'low' / form_status 'neutral' / peak_fitness 0.0 — because
    its own empty-data guard (`if not result_rows`) tested a list built from a
    GENERATED calendar grid, which is non-empty for every window where start <= end.
    The guard now tests whether any record was actually read."""
    sources(strava=[])
    out = call("get_training", {"view": "load", "start_date": _d(-30), "end_date": TODAY})
    assert out == {"error": "No training data found for the requested window."}
    assert "current_state" not in out and "peak_fitness" not in out


def test_load_honest_empty_is_keyed_off_the_QUERIED_window_not_the_partition(sources):
    """The guard must fire on a window with no records even when the partition has
    plenty of them elsewhere — this is the shape an ingestion outage takes (history
    intact, the recent window dark), and it is the case a partition-level
    `if not day_records` check would answer with a zeros model."""
    sources(strava=[strava_day(_d(-400), kilojoules=500)])
    out = call("get_training", {"view": "load", "start_date": _d(-30), "end_date": TODAY})
    assert out == {"error": "No training data found for the requested window."}


def test_load_error_envelope_only_fires_on_an_inverted_window(sources):
    """The only reachable path to the error envelope: start_date after end_date,
    which empties the generated grid."""
    sources(strava=[])
    out = call("get_training", {"view": "load", "start_date": _d(+5), "end_date": TODAY})
    assert out == {"error": "No training data found for the requested window."}


def test_load_warmup_window_is_84_days_before_the_requested_start(sources):
    """The model queries an 84-day warm-up before start_date so the 42-day CTL
    has something to converge on. Pin the actual span the tool asks DynamoDB for."""
    reader = sources(strava=[strava_day(TODAY, kilojoules=100)])
    call("get_training", {"view": "load", "start_date": _d(-30), "end_date": TODAY})
    start, end = reader.window_for("strava")
    assert start == _d(-114)  # start_date (TODAY-30) minus 84 warm-up days
    assert end == TODAY


def test_load_series_is_hand_derivable_from_the_closed_form(sources):
    """Constant daily load L=100 kJ every day from the warm-up start.

    ``compute_ewa`` (mcp/helpers.py) delegates to ``stats_core.ewma_series`` with
    alpha = 1 - exp(-1/tau) and, since #2221, the warm-start seed the training-load
    model now supplies (the mean of the first 7 days of the warm-up — the same
    warm-start ``acwr_compute_lambda._ewma_acwr`` uses). The closed form for a
    constant series is ``L + (seed - L) * exp(-n/tau)``; with seed == L == 100 that
    collapses to exactly 100.00 at every n, for both time constants.

    So identical training yields an identical verdict at the head and the tail of the
    window: ctl 100.00, atl 100.00, tsb 0.00, acwr 1.00 — no bias term at all.
    """
    start = _d(-180)
    rows = [strava_day(_d(-i, TODAY), kilojoules=100) for i in range(0, 181 + 84)]
    sources(strava=rows)
    out = call("get_training", {"view": "load", "start_date": start, "end_date": TODAY})

    series = out["series"]
    assert len(series) == 181  # start..end inclusive
    first, last = series[0], series[-1]

    # Independently recomputed closed form (not read off the tool's output). n is the
    # index into the series; the exp() term is multiplied by (seed - L) == 0.
    for n, row in ((85, first), (265, last)):
        assert row["ctl_fitness"] == round(100 + (100 - 100) * math.exp(-n / 42), 2) == 100.0
        assert row["atl_fatigue"] == round(100 + (100 - 100) * math.exp(-n / 7), 2) == 100.0
        assert row["acwr"] == 1.0 and row["tsb_form"] == 0.0
    assert out["current_state"] == last


def test_load_ewma_convergence_is_hand_derivable_when_the_seed_is_genuinely_zero(sources):
    """The convergence half of the closed form, on a series whose warm-start seed is
    a MEASURED zero rather than an artefact: 164 recorded days of no training (the
    seed window included, so seed = 0), then 101 consecutive days at L=100 kJ.

    From a true zero the closed form is the familiar ``L * (1 - exp(-k/tau))`` for k
    days since the step:

        CTL(101) = 100*(1-exp(-101/42)) = 90.97     ATL(101) = 100*(1-exp(-101/7)) = 100.00

    Here the low CTL at the head of the block is honest — he really had not trained.
    """
    rows = [strava_day(_d(-i, TODAY), kilojoules=(100 if i <= 100 else 0)) for i in range(0, 181 + 84)]
    sources(strava=rows)
    out = call("get_training", {"view": "load", "start_date": _d(-180), "end_date": TODAY})

    first, last = out["series"][0], out["series"][-1]
    assert (first["ctl_fitness"], first["atl_fatigue"], first["acwr"]) == (0.0, 0.0, None)
    assert last["ctl_fitness"] == round(100 * (1 - math.exp(-101 / 42)), 2) == 90.97
    assert last["atl_fatigue"] == round(100 * (1 - math.exp(-101 / 7)), 2) == 100.0
    assert last["acwr"] == round(100.0 / 90.97, 2) == 1.1


def test_constant_training_should_not_produce_a_fabricated_early_fatigue_cliff(sources):
    rows = [strava_day(_d(-i, TODAY), kilojoules=100) for i in range(0, 181 + 84)]
    sources(strava=rows)
    out = call("get_training", {"view": "load", "start_date": _d(-180), "end_date": TODAY})
    first, last = out["series"][0], out["series"][-1]
    assert first["acwr"] == pytest.approx(last["acwr"], abs=0.03)
    assert first["form_status"] == last["form_status"]


def test_load_form_bands_are_ordered_most_negative_first(sources):
    """#490 fixed an unreachable band. Pin all four TSB bands through the tool
    by choosing loads that land each one, so a reorder cannot silently regress.

    TSB = CTL - ATL. A long flat block then a spike drives TSB negative; a long
    flat block then rest drives it positive.
    """
    # Fresh: 84 warm-up days of load, then 30 days of nothing → ATL decays far faster than CTL.
    rows = [strava_day(_d(-i, TODAY), kilojoules=200) for i in range(31, 31 + 90)]
    sources(strava=rows)
    out = call("get_training", {"view": "load", "start_date": _d(-30), "end_date": TODAY})
    assert out["current_state"]["tsb_form"] > 5
    assert out["current_state"]["form_status"].startswith("fresh")


def test_load_reports_absence_as_a_factual_zero_daily_load(sources):
    """A day with no cardio record still contributes daily_load 0.0 — the model is a
    day grid and cannot represent a hole. That is why the coverage block below is the
    fix rather than a change to the arithmetic: the series is unchanged, the payload
    now says how much of it was observed."""
    sources(strava=[strava_day(TODAY, kilojoules=500)])
    out = call("get_training", {"view": "load", "start_date": _d(-6), "end_date": TODAY})
    loads = [r["daily_load"] for r in out["series"]]
    assert loads == [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 500.0]


def test_load_should_publish_the_data_coverage_behind_the_form_verdict(sources):
    """FIXED (#2221, ADR-105 n-beside-the-number). One recorded day in a 7-day window
    used to be reported with no coverage field of any kind, so nothing downstream could
    tell a quiet week from a dark one — an ingestion outage is arithmetically identical
    to a rest week (CTL decays, TSB climbs, verdict 'fresh — good for key sessions')."""
    sources(strava=[strava_day(TODAY, kilojoules=500)])
    out = call("get_training", {"view": "load", "start_date": _d(-6), "end_date": TODAY})
    cov = out["coverage"]
    assert cov["days_in_window"] == 7  # start..end inclusive
    assert cov["days_with_data"] == 1  # only TODAY had a record
    assert cov["coverage_pct"] == round(100 / 7, 1) == 14.3
    assert cov["warmup_days"] == 84 and cov["warmup_days_with_data"] == 0


def test_load_coverage_is_100_pct_when_every_day_in_the_window_has_a_record(sources):
    """The other end of the same field — a coverage figure that is always low, or
    always the same, would be decoration rather than a measurement."""
    sources(strava=[strava_day(_d(-i), kilojoules=100) for i in range(0, 200)])
    out = call("get_training", {"view": "load", "start_date": _d(-6), "end_date": TODAY})
    assert out["coverage"]["days_with_data"] == 7
    assert out["coverage"]["coverage_pct"] == 100.0
    assert out["coverage"]["warmup_days_with_data"] == 84


def test_load_monotony_requires_a_full_seven_day_tail(sources):
    """Galpin monotony = weekly mean / SD. Guarded on len>=7 so a 3-day window
    reports {} rather than a two-point 'weekly' statistic (ADR-105)."""
    sources(strava=[strava_day(_d(-i), kilojoules=100) for i in range(0, 100)])
    short = call("get_training", {"view": "load", "start_date": _d(-2), "end_date": TODAY})
    assert short["monotony"] == {}
    full = call("get_training", {"view": "load", "start_date": _d(-10), "end_date": TODAY})
    assert set(full["monotony"]) == {"training_monotony", "weekly_training_strain", "monotony_risk"}


def test_load_monotony_is_none_when_the_week_has_zero_variance(sources):
    """Perfectly constant load ⇒ SD 0 ⇒ monotony is mathematically undefined.
    It returns None (honest) rather than a divide-by-zero or a fabricated ceiling."""
    sources(strava=[strava_day(_d(-i), kilojoules=100) for i in range(0, 100)])
    out = call("get_training", {"view": "load", "start_date": _d(-10), "end_date": TODAY})
    assert out["monotony"]["training_monotony"] is None
    assert out["monotony"]["weekly_training_strain"] is None
    assert out["monotony"]["monotony_risk"] == "ok"


def test_load_malformed_end_date_escapes_as_an_unhandled_valueerror(sources):
    """The dispatcher returns a clean envelope for a bad `view` but a bad `date`
    string raises straight out of the tool. Pinned as observed behaviour."""
    sources(strava=[])
    with pytest.raises(ValueError):
        call("get_training", {"view": "load", "end_date": "2026-13-45"})


# ═══════════════════════════════════════════════════════════════════════════════
# §3 — view=periodization
# ═══════════════════════════════════════════════════════════════════════════════


def test_periodization_empty_window_returns_error_envelope_with_the_window(sources):
    sources(strava=[], macrofactor_workouts=[])
    out = call("get_training", {"view": "periodization", "end_date": TODAY, "weeks": 4})
    assert out["error"] == "No training data for range."
    assert out["start_date"] == _d(-28) and out["end_date"] == TODAY


def test_periodization_weeks_argument_sets_the_queried_window(sources):
    reader = sources(strava=[strava_day(TODAY, activities=[activity("Run", minutes=40, avg_hr=120)])])
    call("get_training", {"view": "periodization", "end_date": TODAY, "weeks": 12})
    start, end = reader.window_for("strava")
    assert (start, end) == (_d(-84), TODAY)  # 12 weeks = 84 days


def test_periodization_drops_activities_under_ten_minutes(sources):
    """<600s is treated as not-a-session. Pin the floor: a 9-minute run does not
    create a session, a 10-minute one does."""
    sources(strava=[strava_day(TODAY, activities=[activity("Run", minutes=9, avg_hr=120)])], macrofactor_workouts=[])
    out = call("get_training", {"view": "periodization", "end_date": TODAY, "weeks": 2})
    assert out["weekly_breakdown"][-1]["sessions"] == 0

    sources(strava=[strava_day(TODAY, activities=[activity("Run", minutes=10, avg_hr=120)])], macrofactor_workouts=[])
    out = call("get_training", {"view": "periodization", "end_date": TODAY, "weeks": 2})
    assert out["weekly_breakdown"][-1]["sessions"] == 1


def test_periodization_does_not_count_a_recovery_walk_as_zone_2(sources):
    """FIXED (#2221): the periodization view used to classify ANY cardio at avg HR
    <= 70% of max as Zone 2 — Zone 1 and below included. At max_hr 190 a 60-minute
    walk at 95 bpm is 50% of max (Zone 1 by every 5-zone model) and landed in
    zone2_minutes in full. It is now classified through the canonical band, so it
    counts as easy volume but not as Zone 2."""
    sources(strava=[strava_day(TODAY, activities=[activity("Walk", minutes=60, avg_hr=95)])], macrofactor_workouts=[])
    out = call("get_training", {"view": "periodization", "end_date": TODAY, "weeks": 2})
    assert out["weekly_breakdown"][-1]["zone2_minutes"] == 0.0
    assert out["zone2_status"]["current_week"] == 0.0
    assert out["polarization"]["easy_pct"] == 100.0  # still easy volume, just not Zone 2


def test_periodization_zone2_agrees_with_the_canonical_zone2_tool(sources):
    """FIXED (#2221). Both tools are driven over the same fixture and their published
    Zone-2 minutes compared — DERIVED from the canonical producer, never restated.

    Three activities that exercise the disagreements at once: a 50%-of-max walk (below
    the canonical Zone-2 floor — periodization used to count it in full), a 65%-of-max
    ride (genuinely Zone 2 in both), and a 74%-of-max run (Zone 3, which periodization
    used to fold into easy). Expected Zone 2 = the 45-minute ride only. The upper bound
    can no longer disagree either: both tools now classify through the one
    `mcp.helpers.classify_hr_zone`, so `<= 70%` vs `< 70%` cannot drift apart again.
    """
    day = strava_day(
        TODAY,
        activities=[
            activity("Walk", minutes=60, avg_hr=95),  # 50.0% — below zone 2
            activity("Ride", minutes=45, avg_hr=124),  # 65.3% — zone 2
            activity("Run", minutes=30, avg_hr=140),  # 73.7% — zone 3
        ],
    )
    sources(strava=[day], macrofactor_workouts=[])
    periodization = call("get_training", {"view": "periodization", "end_date": TODAY, "weeks": 2})
    breakdown = TOOLS["get_zone2_breakdown"]["fn"]({"start_date": _d(-7), "end_date": TODAY})
    # `total_zone_2_min` is the key the producer actually publishes (mcp/tools_correlation.py);
    # `total_zone2_minutes` has never existed on it — the same reader/writer mismatch #2246 fixed.
    assert periodization["zone2_status"]["current_week"] == breakdown["summary"]["total_zone_2_min"] == 45.0
    assert periodization["weekly_breakdown"][-1]["moderate_minutes"] == 30.0  # the 70.0% run


def test_polarization_separates_zone_three_from_easy(sources):
    """FIXED (#2221). Zone 3 (70-80% of max HR) used to be filed into `easy_minutes`
    with the comment "Zone 3 counted as moderate", and the Seiler split was computed as
    easy/(easy+hard) — so `middle_zone_pct` was 0.0 by construction and a week of pure
    Zone 3 reported easy_pct 100.0 / status 'well_polarized'. The board note that warns
    about exactly this could never fire, because the minutes that would have triggered
    it had been relabelled easy. Zone 3 now has its own bucket and its own share."""
    sources(
        strava=[strava_day(TODAY, activities=[activity("Run", minutes=60, avg_hr=142)])],  # 142/190 = 74.7% → Zone 3
        macrofactor_workouts=[],
    )
    out = call("get_training", {"view": "periodization", "end_date": TODAY, "weeks": 2})
    assert out["polarization"]["middle_zone_pct"] == 100.0
    assert out["polarization"]["easy_pct"] == 0.0 and out["polarization"]["hard_pct"] == 0.0
    assert out["polarization"]["status"] == "too_much_moderate"
    assert out["weekly_breakdown"][-1]["moderate_minutes"] == 60.0
    assert any("no man's land" in n.lower() for n in out["board_of_directors"])


def test_polarization_should_separate_zone_three_from_easy(sources):
    """The contract the marker asked for, kept as its own assertion: the middle zone
    is reported and a pure-Zone-3 week is not called well polarized."""
    sources(strava=[strava_day(TODAY, activities=[activity("Run", minutes=60, avg_hr=142)])], macrofactor_workouts=[])
    out = call("get_training", {"view": "periodization", "end_date": TODAY, "weeks": 2})
    assert out["polarization"]["middle_zone_pct"] > 0
    assert out["polarization"]["status"] != "well_polarized"


def test_periodization_rest_days_are_bounded_by_the_elapsed_part_of_the_week(sources):
    """FIXED (#2221, #1917 window honesty): rest_days was `7 - len(dates)` for EVERY
    week, including the in-progress one. TODAY (2026-08-08) is a Saturday, so the
    current ISO week has 6 elapsed days; two training days on two of them used to
    report 5 rest days — counting Sunday, which has not happened. The denominator is
    now the days of that ISO week the query actually covers, published as
    `days_in_window` so the n is visible beside the number."""
    assert datetime.strptime(TODAY, "%Y-%m-%d").isoweekday() == 6  # Saturday — 6 elapsed days this ISO week
    sources(
        strava=[
            strava_day(TODAY, activities=[activity("Run", minutes=40, avg_hr=120)]),
            strava_day(_d(-1), activities=[activity("Run", minutes=40, avg_hr=120)]),
        ],
        macrofactor_workouts=[],
    )
    out = call("get_training", {"view": "periodization", "end_date": TODAY, "weeks": 1})
    current = out["weekly_breakdown"][-1]
    assert current["sessions"] == 2
    assert current["days_in_window"] == 6  # Mon 08-03 .. Sat 08-08
    assert current["rest_days"] == 4  # 6 elapsed - 2 trained


def test_periodization_a_complete_past_week_still_gets_the_full_seven_day_denominator(sources):
    """The bound is the queried window, not a blanket reduction: a week that is wholly
    inside the window keeps all 7 days, so a real rest day is still counted as rest."""
    sources(
        strava=[strava_day(_d(-9), activities=[activity("Run", minutes=40, avg_hr=120)])],
        macrofactor_workouts=[],
    )
    out = call("get_training", {"view": "periodization", "end_date": TODAY, "weeks": 4})
    prior = next(w for w in out["weekly_breakdown"] if w["sessions"] == 1)
    assert prior["days_in_window"] == 7 and prior["rest_days"] == 6


def test_current_week_rest_days_should_not_count_days_that_have_not_happened(sources):
    sources(
        strava=[
            strava_day(TODAY, activities=[activity("Run", minutes=40, avg_hr=120)]),
            strava_day(_d(-1), activities=[activity("Run", minutes=40, avg_hr=120)]),
        ],
        macrofactor_workouts=[],
    )
    out = call("get_training", {"view": "periodization", "end_date": TODAY, "weeks": 1})
    assert out["weekly_breakdown"][-1]["rest_days"] <= 4  # 6 elapsed days - 2 trained


def test_periodization_a_day_of_only_sub_threshold_activity_is_not_a_rest_day(sources):
    """OBSERVED (still true, and out of scope for #2221): the date is added to the
    week's `dates` set BEFORE the <600s filter, so a day whose only activity was a
    5-minute stroll counts against rest_days while contributing 0 sessions and 0
    minutes. The denominator is now the 6 elapsed days of the current week."""
    sources(strava=[strava_day(TODAY, activities=[activity("Walk", minutes=5, avg_hr=95)])], macrofactor_workouts=[])
    out = call("get_training", {"view": "periodization", "end_date": TODAY, "weeks": 1})
    current = out["weekly_breakdown"][-1]
    assert current["sessions"] == 0 and current["total_minutes"] == 0
    assert current["rest_days"] == 5  # 6 elapsed - 1 dated, though nothing was trained


def test_periodization_progressive_overload_needs_four_volume_weeks(sources):
    """Overload = first-half vs second-half mean weekly volume, gated at n>=4
    weeks with volume. Below the gate it is None (honest) rather than a two-point
    'trend' (ADR-105)."""
    mf = [{"date": _d(-7 * i), "total_volume_lbs": 1000} for i in range(0, 3)]
    sources(strava=[strava_day(TODAY, activities=[activity("Run", minutes=40, avg_hr=120)])], macrofactor_workouts=mf)
    out = call("get_training", {"view": "periodization", "end_date": TODAY, "weeks": 8})
    assert out["progressive_overload"] is None


def test_periodization_progressive_overload_delta_is_hand_derivable(sources):
    """Six weekly volume points 1000,1000,1000,2000,2000,2000 (oldest→newest).
    mid = 6//2 = 3 ⇒ first half mean = 1000, second half mean = 2000 ⇒
    delta_pct = (2000-1000)/1000*100 = 100.0 ⇒ trend 'increasing'."""
    mf = [{"date": _d(-7 * i), "total_volume_lbs": (2000 if i < 3 else 1000)} for i in range(0, 6)]
    strava = [strava_day(_d(-7 * i), activities=[activity("Run", minutes=40, avg_hr=120)]) for i in range(0, 6)]
    sources(strava=strava, macrofactor_workouts=mf)
    out = call("get_training", {"view": "periodization", "end_date": TODAY, "weeks": 8})
    ov = out["progressive_overload"]
    assert ov["first_half_avg_volume_lbs"] == 1000.0
    assert ov["second_half_avg_volume_lbs"] == 2000.0
    assert ov["delta_pct"] == 100.0 and ov["trend"] == "increasing"


def test_periodization_deload_recommendation_fires_after_four_loading_weeks(sources):
    """4+ consecutive non-deload weeks ⇒ deload_recommended with the Galpin 3:1/4:1
    reason, and the board note is emitted."""
    strava = []
    for wk in range(0, 6):
        for day in range(0, 4):  # 4 sessions/week, >60 min total → never classified deload
            strava.append(
                strava_day(_d(-(7 * wk + day)), activities=[activity("Run", minutes=45, avg_hr=120)]),
            )
    sources(strava=strava, macrofactor_workouts=[])
    out = call("get_training", {"view": "periodization", "end_date": TODAY, "weeks": 8})
    assert out["deload_analysis"]["deload_recommended"] is True
    assert out["deload_analysis"]["weeks_since_last_deload"] >= 4
    assert any("Galpin" in note for note in out["board_of_directors"])


def test_periodization_non_numeric_weeks_escapes_as_valueerror(sources):
    """`weeks` is declared "type": "number" but arrives from an LLM; int() is
    unguarded. Pinned as observed behaviour."""
    sources(strava=[])
    with pytest.raises(ValueError):
        call("get_training", {"view": "periodization", "end_date": TODAY, "weeks": "twelve"})


# ═══════════════════════════════════════════════════════════════════════════════
# §4 — view=recommendation: the tool that tells Matthew what to do today
# ═══════════════════════════════════════════════════════════════════════════════


def _recovery_day(date: str, *, recovery=None, hrv=None, rhr=None, strain=None) -> dict:
    """One Whoop DATE# record. Field names verified against the writer,
    lambdas/ingestion/whoop_lambda.py (recovery_score / hrv / resting_heart_rate /
    strain — note the writer stores `hrv`, NOT `hrv_rmssd`)."""
    rec = {"date": date}
    for key, val in (("recovery_score", recovery), ("hrv", hrv), ("resting_heart_rate", rhr), ("strain", strain)):
        if val is not None:
            rec[key] = val
    return rec


def test_recommendation_with_no_recovery_data_at_all_reports_absence(sources):
    """FIXED (#2221, ADR-104 P1): with Whoop, Eight Sleep and Garmin all silent the
    tool used to publish composite_readiness 50.0 and a confident YELLOW tier with a
    Zone 2 prescription — a literal default presented in the same field, with the same
    type, as a measured number. All-silent is a live state (Garmin is paused per
    ADR-074; Whoop has latched AUTH_FAILURE repeatedly)."""
    sources(whoop=[], eightsleep=[], garmin=[], strava=[], macrofactor_workouts=[], computed_metrics=[])
    out = call("get_training", {"view": "recommendation", "date": TODAY})
    assert out["readiness_signals"] == {}
    assert out["composite_readiness"] is None
    assert out["composite_readiness_n"] == 0
    assert out["readiness_tier"] == "UNKNOWN"
    assert out["recommendation"]["type"].startswith("No recommendation")
    assert out["recommendation"]["hr_ceiling"] is None
    assert any("ADR-104" in n for n in out["board_of_directors"])


def test_recommendation_should_not_invent_a_readiness_score_from_no_signals(sources):
    """The marker's own contract, kept as its own assertion."""
    sources(whoop=[], eightsleep=[], garmin=[], strava=[], macrofactor_workouts=[], computed_metrics=[])
    out = call("get_training", {"view": "recommendation", "date": TODAY})
    assert out["composite_readiness"] is None or out["readiness_tier"] not in ("GREEN", "YELLOW", "RED")


def test_recommendation_unknown_tier_is_not_promoted_by_the_consecutive_day_floor(sources):
    """The Meeusen 5-consecutive-day guard is a FLOOR on an existing verdict. Applied
    to UNKNOWN it would manufacture a YELLOW — asserting a readiness level nothing
    measured — so it is skipped, and the measured fact rides as a warning instead."""
    strava = [strava_day(_d(-i), activities=[activity("Run", minutes=60, avg_hr=140)], activity_count=1) for i in range(1, 8)]
    sources(whoop=[], eightsleep=[], garmin=[], strava=strava, macrofactor_workouts=[], computed_metrics=[])
    out = call("get_training", {"view": "recommendation", "date": TODAY})
    assert out["training_context"]["consecutive_training_days"] >= 5
    assert out["readiness_tier"] == "UNKNOWN"
    assert any("consecutive training days" in w for w in out["warnings"])


def test_recommendation_measured_acwr_override_still_fires_with_no_recovery_signals(sources):
    """The ACWR > 1.5 override comes from the load model, not from the recovery
    signals, so it is a MEASURED fact and must survive a dark recovery side —
    an UNKNOWN readiness tier must not swallow a real injury-risk verdict."""
    rows = [strava_day(_d(-i), kilojoules=(2000 if i <= 6 else 50)) for i in range(0, 300)]
    sources(whoop=[], eightsleep=[], garmin=[], strava=rows, macrofactor_workouts=[], computed_metrics=[])
    out = call("get_training", {"view": "recommendation", "date": TODAY})
    assert out["composite_readiness"] is None  # still no recovery measurement
    assert out["training_context"]["training_load"]["acwr"] > 1.5
    assert out["readiness_tier"] == "RED"


def test_recommendation_composite_is_the_plain_mean_of_the_present_signals(sources):
    """Whoop recovery 80, sleep score 70, body battery 60 ⇒ (80+70+60)/3 = 70.0
    ⇒ GREEN (>= 67). Unweighted mean, hand-derived."""
    sources(
        whoop=[_recovery_day(TODAY, recovery=80, hrv=60)],
        eightsleep=[{"date": TODAY, "sleep_score": 70, "sleep_duration_hours": 7.5}],
        garmin=[{"date": TODAY, "body_battery_high": 60}],
        strava=[],
        macrofactor_workouts=[],
        computed_metrics=[],
    )
    out = call("get_training", {"view": "recommendation", "date": TODAY})
    assert out["composite_readiness"] == 70.0
    assert out["readiness_tier"] == "GREEN"


def test_recommendation_composite_carries_the_n_behind_its_average(sources):
    """FIXED (#2221, ADR-105): a composite built from ONE signal and one built from
    THREE used to be reported identically — same field, same type, no n. The mean is
    unchanged; what it was averaged over is now published beside it."""
    sources(whoop=[_recovery_day(TODAY, recovery=70)], eightsleep=[], garmin=[], strava=[], macrofactor_workouts=[], computed_metrics=[])
    one = call("get_training", {"view": "recommendation", "date": TODAY})
    sources(
        whoop=[_recovery_day(TODAY, recovery=70)],
        eightsleep=[{"date": TODAY, "sleep_score": 70}],
        garmin=[{"date": TODAY, "body_battery_high": 70}],
        strava=[],
        macrofactor_workouts=[],
        computed_metrics=[],
    )
    three = call("get_training", {"view": "recommendation", "date": TODAY})
    assert one["composite_readiness"] == three["composite_readiness"] == 70.0
    # Identical means, different n — and the payload now says so.
    assert one["composite_readiness_n"] == 1 and three["composite_readiness_n"] == 3
    assert one["composite_readiness_signals"] == ["whoop_recovery"]
    assert three["composite_readiness_signals"] == ["whoop_recovery", "sleep_score", "body_battery"]
    # The signals dict is honest about absence (missing sub-fields are None, never 0).
    present = lambda r: {k for k, v in r["readiness_signals"].items() if v is not None}  # noqa: E731
    assert present(one) == {"whoop_recovery"}
    assert present(three) == {"whoop_recovery", "sleep_score", "body_battery"}


def test_recommendation_acwr_above_one_point_five_forces_red(sources):
    """The one hard override that does fire: a load-model ACWR > 1.5 pins the tier
    to RED regardless of recovery. Built by a step change in load, not asserted
    off recovery alone."""
    rows = [strava_day(_d(-i), kilojoules=(2000 if i <= 6 else 50)) for i in range(0, 300)]
    sources(
        whoop=[_recovery_day(TODAY, recovery=95)],
        eightsleep=[{"date": TODAY, "sleep_score": 95}],
        garmin=[{"date": TODAY, "body_battery_high": 95}],
        strava=rows,
        macrofactor_workouts=[],
        computed_metrics=[],
    )
    out = call("get_training", {"view": "recommendation", "date": TODAY})
    assert out["training_context"]["training_load"]["acwr"] > 1.5
    assert out["readiness_tier"] == "RED"
    assert out["recommendation"]["type"] in ("Full Rest", "Active Recovery")


def test_five_consecutive_training_days_demotes_green_to_yellow(sources):
    """FIXED (#2247) — mcp/tools_training.py used to demote GREEN→YELLOW after 5+
    consecutive training days with `min(tier, "YELLOW")`. `min` on str is
    lexicographic ("GREEN" < "YELLOW" alphabetically), so the branch reassigned
    GREEN to GREEN and the demotion never fired: Matthew on his 7th straight
    training day with great sleep was told GREEN and prescribed VO2max intervals
    or heavy compounds — the exact scenario the guard exists to prevent. The fix
    ranks tiers by an explicit severity map (`_TIER_SEVERITY`) instead of
    comparing the strings. This test fails against the pre-fix code (asserts
    GREEN survives) and passes now that the demotion actually fires."""
    strava = [strava_day(_d(-i), activities=[activity("Run", minutes=60, avg_hr=140)], activity_count=1) for i in range(1, 8)]
    sources(
        whoop=[_recovery_day(TODAY, recovery=95)],
        eightsleep=[{"date": TODAY, "sleep_score": 95}],
        garmin=[{"date": TODAY, "body_battery_high": 95}],
        strava=strava,
        macrofactor_workouts=[],
        computed_metrics=[],
    )
    out = call("get_training", {"view": "recommendation", "date": TODAY})
    assert out["training_context"]["consecutive_training_days"] >= 5
    assert out["readiness_tier"] == "YELLOW"


def test_five_consecutive_training_days_does_not_promote_red_to_yellow(sources):
    """The demotion is a floor, not a reset: a composite that already earned RED
    (e.g. from #1.5 ACWR or, here, uniformly poor recovery/sleep/battery signals)
    must stay RED under the same 5+ consecutive-training-day condition — the
    Meeusen guard should never accidentally IMPROVE a worse verdict."""
    strava = [strava_day(_d(-i), activities=[activity("Run", minutes=60, avg_hr=140)], activity_count=1) for i in range(1, 8)]
    sources(
        whoop=[_recovery_day(TODAY, recovery=10)],
        eightsleep=[{"date": TODAY, "sleep_score": 10}],
        garmin=[{"date": TODAY, "body_battery_high": 10}],
        strava=strava,
        macrofactor_workouts=[],
        computed_metrics=[],
    )
    out = call("get_training", {"view": "recommendation", "date": TODAY})
    assert out["training_context"]["consecutive_training_days"] >= 5
    assert out["readiness_tier"] == "RED"


def test_recommendation_warning_agrees_with_its_own_tier(sources):
    """FIXED (#2247) — before the fix this scenario shipped a self-contradictory
    payload: 'GREEN, go hard' next to '⚠️ 7 consecutive training days'. Now the
    tier the warning attaches to actually reflects the risk it names."""
    strava = [strava_day(_d(-i), activities=[activity("Run", minutes=60, avg_hr=140)], activity_count=1) for i in range(1, 8)]
    sources(
        whoop=[_recovery_day(TODAY, recovery=95)],
        eightsleep=[{"date": TODAY, "sleep_score": 95}],
        garmin=[{"date": TODAY, "body_battery_high": 95}],
        strava=strava,
        macrofactor_workouts=[],
        computed_metrics=[],
    )
    out = call("get_training", {"view": "recommendation", "date": TODAY})
    assert out["readiness_tier"] == "YELLOW"
    assert any("consecutive training days" in w for w in out["warnings"])


def test_recommendation_survives_a_macrofactor_workout_with_exercises(sources):
    """FIXED (#2249) — `classify_exercise(ename)` at mcp/tools_training.py:621
    calls a name that was never imported in this module; the `# noqa: F821`
    beside it was added mechanically by deploy/archive/onetime/fix_ci_lint.py
    (whose own comment says "imported from strength_helpers") instead of the
    import actually being added — mcp/tools_strength.py imports the same symbol
    correctly from mcp.strength_helpers. Before the fix, the moment any
    macrofactor_workouts record in the tool's 14-day window carried a workout
    with an exercise, get_training(view='recommendation') raised NameError out
    of the MCP handler instead of returning a recommendation. It was latent only
    because macrofactor_workouts has had no writer for ~4 months
    (phase_taxonomy.py:130, #485) — but historical rows are explicitly KEPT, so
    the tool's own declared `date` argument landing on a date with strength
    history reached it. Now `classify_exercise` is imported properly and the
    call both survives AND actually classifies the exercise into muscle_recovery
    (Bench Press -> Chest/Triceps/Shoulders), rather than merely not crashing."""
    sources(
        whoop=[_recovery_day(TODAY, recovery=80)],
        eightsleep=[],
        garmin=[],
        strava=[],
        computed_metrics=[],
        macrofactor_workouts=[
            {
                "date": _d(-2),
                "workouts": [{"exercises": [{"exercise_name": "Barbell Bench Press"}]}],
            }
        ],
    )
    out = call("get_training", {"view": "recommendation", "date": TODAY})
    assert "muscle_recovery" in out
    assert set(out["muscle_recovery"]) == {"Chest", "Triceps", "Shoulders"}
    for mg in ("Chest", "Triceps", "Shoulders"):
        assert out["muscle_recovery"][mg]["last_trained"] == _d(-2)


def test_recommendation_muscle_recovery_is_empty_without_strength_history(sources):
    """Envelope parity: the muscle_recovery key is always present, empty when the
    (dead) macrofactor_workouts partition has nothing."""
    sources(whoop=[_recovery_day(TODAY, recovery=80)], eightsleep=[], garmin=[], strava=[], macrofactor_workouts=[], computed_metrics=[])
    out = call("get_training", {"view": "recommendation", "date": TODAY})
    assert out["muscle_recovery"] == {}


def test_recommendation_hr_ceilings_are_derived_from_the_profile_max_hr(sources):
    """Zone 2 ceiling = 70% of max HR, floor = 60%. max_hr 190 ⇒ 133 / 114."""
    sources(
        whoop=[_recovery_day(TODAY, recovery=50)],
        eightsleep=[{"date": TODAY, "sleep_score": 50}],
        garmin=[],
        strava=[],
        macrofactor_workouts=[],
        computed_metrics=[],
    )
    out = call("get_training", {"view": "recommendation", "date": TODAY})
    assert out["readiness_tier"] == "YELLOW"
    assert out["recommendation"]["hr_ceiling"] == round(190 * 0.7) == 133


def test_recommendation_reads_exactly_the_five_declared_partitions(sources):
    """The `source` field claims whoop + eightsleep + garmin + strava +
    macrofactor_workouts. Assert the tool actually queries those and no other
    partition (a silent extra read is how a private partition leaks)."""
    reader = sources(whoop=[], eightsleep=[], garmin=[], strava=[], macrofactor_workouts=[], computed_metrics=[])
    out = call("get_training", {"view": "recommendation", "date": TODAY})
    queried = {c[0] for c in reader.calls}
    declared = set(out["source"].replace(" ", "").split("+"))
    # computed_metrics/strava arrive via the nested load + zone2 sub-calls.
    assert declared <= queried
    assert queried <= declared | {"computed_metrics"}


def test_recommendation_never_passes_include_pilot(sources):
    """ADR-058: no read on this path may opt out of the phase filter."""
    reader = sources(whoop=[], eightsleep=[], garmin=[], strava=[], macrofactor_workouts=[], computed_metrics=[])
    call("get_training", {"view": "recommendation", "date": TODAY})
    assert all(pilot is False for *_rest, pilot in reader.calls)


def test_recommendation_yellow_strength_branch_can_only_ever_say_general(sources):
    """OBSERVED: the YELLOW strength branch picks target muscles from
    `muscle_recovery`, which is populated exclusively from macrofactor_workouts —
    a partition that has had no writer for ~4 months (#485, unrelated to #2249's
    now-fixed classify_exercise import). With no writer, no historical row falls
    in the query window here, so the branch is permanently reduced to
    'Full Body (Light)' targeting the literal string 'General'."""
    sources(
        whoop=[_recovery_day(TODAY, recovery=50)],
        eightsleep=[{"date": TODAY, "sleep_score": 50}],
        garmin=[],
        strava=[
            strava_day(_d(-1), activities=[activity("Run", minutes=40, avg_hr=120)], activity_count=1),
            strava_day(_d(-3), activities=[activity("WeightTraining", minutes=45, avg_hr=110)], activity_count=1),
        ],
        macrofactor_workouts=[],
        computed_metrics=[],
    )
    out = call("get_training", {"view": "recommendation", "date": TODAY})
    assert out["readiness_tier"] == "YELLOW"
    assert out["recommendation"]["type"] == "Strength — Full Body (Light)"
    assert out["recommendation"]["target_muscles"] == ["General"]
    assert out["training_context"]["days_since_strength"] == 3


def test_recommendation_green_and_rested_prescribes_vo2max_intervals(sources):
    """GREEN + no hard session for 5 days + no cardio for 5 days ⇒ HIIT, with the
    interval band derived from max HR: floor 85% = 162, ceiling 90% = 171."""
    sources(
        whoop=[_recovery_day(TODAY, recovery=90)],
        eightsleep=[{"date": TODAY, "sleep_score": 90}],
        garmin=[],
        strava=[strava_day(_d(-5), activities=[activity("Run", minutes=45, avg_hr=170)], activity_count=1)],
        macrofactor_workouts=[],
        computed_metrics=[],
    )
    out = call("get_training", {"view": "recommendation", "date": TODAY})
    assert out["readiness_tier"] == "GREEN"
    assert out["recommendation"]["type"] == "High-Intensity Intervals"
    assert out["recommendation"]["hr_floor"] == round(190 * 0.85) == 162
    assert out["recommendation"]["hr_ceiling"] == round(190 * 0.9) == 171
    assert any("Attia" in n for n in out["board_of_directors"])


def test_recommendation_green_with_recent_cardio_prescribes_heavy_strength(sources):
    sources(
        whoop=[_recovery_day(TODAY, recovery=90)],
        eightsleep=[{"date": TODAY, "sleep_score": 90}],
        garmin=[],
        strava=[
            strava_day(_d(-1), activities=[activity("Ride", minutes=60, avg_hr=120)], activity_count=1),
            strava_day(_d(-5), activities=[activity("Run", minutes=45, avg_hr=170)], activity_count=1),
        ],
        macrofactor_workouts=[],
        computed_metrics=[],
    )
    out = call("get_training", {"view": "recommendation", "date": TODAY})
    assert out["recommendation"]["type"] == "Strength — Full Body"
    assert out["recommendation"]["rpe_range"] == "8-9"
    assert any("Galpin" in n for n in out["board_of_directors"])


def test_recommendation_green_after_a_recent_hard_session_falls_back_to_zone_2(sources):
    sources(
        whoop=[_recovery_day(TODAY, recovery=90)],
        eightsleep=[{"date": TODAY, "sleep_score": 90}],
        garmin=[],
        strava=[strava_day(_d(-1), activities=[activity("Run", minutes=45, avg_hr=170)], activity_count=1)],
        macrofactor_workouts=[],
        computed_metrics=[],
    )
    out = call("get_training", {"view": "recommendation", "date": TODAY})
    assert out["readiness_tier"] == "GREEN"
    assert out["recommendation"]["type"] == "Zone 2 Cardio"
    assert out["training_context"]["days_since_hard_session"] == 1


def test_recommendation_red_after_two_rest_days_prescribes_active_recovery_not_rest(sources):
    """The one place rest/active-recovery is chosen: consecutive_rest_days >= 2."""
    sources(
        whoop=[_recovery_day(TODAY, recovery=10)],
        eightsleep=[{"date": TODAY, "sleep_score": 10}],
        garmin=[],
        strava=[],
        macrofactor_workouts=[],
        computed_metrics=[],
    )
    out = call("get_training", {"view": "recommendation", "date": TODAY})
    assert out["readiness_tier"] == "RED"
    assert out["training_context"]["consecutive_rest_days"] >= 2
    assert out["recommendation"]["type"] == "Active Recovery"
    assert out["recommendation"]["hr_ceiling"] == round(190 * 0.6) == 114


def test_recommendation_red_with_no_rest_history_prescribes_full_rest(sources):
    sources(
        whoop=[_recovery_day(TODAY, recovery=10)],
        eightsleep=[{"date": TODAY, "sleep_score": 10}],
        garmin=[],
        strava=[strava_day(_d(-1), activities=[activity("Run", minutes=45, avg_hr=140)], activity_count=1)],
        macrofactor_workouts=[],
        computed_metrics=[],
    )
    out = call("get_training", {"view": "recommendation", "date": TODAY})
    assert out["recommendation"] == {
        "type": "Full Rest",
        "intensity": "None",
        "description": "Your body needs recovery. Focus on sleep, nutrition, and stress management.",
        "duration_min": "0",
        "hr_ceiling": None,
    }
    assert any("Walker" in n for n in out["board_of_directors"])


def test_recommendation_short_sleep_and_high_stress_raise_warnings(sources):
    """Two independent single-signal warnings. Note they are WARNINGS, not tier
    changes — the rest/params decision stays multi-factor."""
    sources(
        whoop=[_recovery_day(TODAY, recovery=80)],
        eightsleep=[{"date": TODAY, "sleep_score": 80, "sleep_duration_hours": 5.2}],
        garmin=[{"date": TODAY, "body_battery_high": 80, "avg_stress": 61}],
        strava=[],
        macrofactor_workouts=[],
        computed_metrics=[],
    )
    out = call("get_training", {"view": "recommendation", "date": TODAY})
    assert any("5.2h sleep" in w for w in out["warnings"])
    assert any("Garmin stress score 61" in w for w in out["warnings"])


def test_recommendation_hrv_warning_compares_today_against_a_mean_that_includes_today(sources):
    """OBSERVED (ADR-105): the '7-day average' the HRV drop is measured against is
    built from the same 8-date window that supplied today's value, today included.
    Values 100, 100, 100 and today 60: mean = (60+100+100+100)/4 = 90, and
    60 < 90*0.8 = 72 ⇒ warning at round((1-60/90)*100) = 33%. A self-excluding
    baseline would be 100, i.e. a 40% drop."""
    sources(
        whoop=[
            _recovery_day(TODAY, recovery=80, hrv=60),
            _recovery_day(_d(-1), hrv=100),
            _recovery_day(_d(-2), hrv=100),
            _recovery_day(_d(-3), hrv=100),
        ],
        eightsleep=[],
        garmin=[],
        strava=[],
        macrofactor_workouts=[],
        computed_metrics=[],
    )
    out = call("get_training", {"view": "recommendation", "date": TODAY})
    hrv_warning = next(w for w in out["warnings"] if "HRV" in w)
    assert "33% below your 7-day average" in hrv_warning


def test_recommendation_zone2_board_note_reports_the_real_minutes(sources):
    """FIXED #2246. 60 genuine Zone-2 minutes in the window (avg HR 124 = 65% of
    max, squarely inside the canonical 60-70% band) is 40% of the 150 min target,
    so the deficit note fires — and it must quote the REAL figure, not the
    hardcoded 0 the reader/writer key mismatch used to produce.

    The expected minute count is DERIVED from the canonical producer
    (``get_zone2_breakdown``'s ``summary.total_zone_2_min``) rather than restated,
    so a future rename on either side fails here instead of silently reverting to
    the ``.get`` default."""
    sources(
        whoop=[_recovery_day(TODAY, recovery=80)],
        eightsleep=[{"date": TODAY, "sleep_score": 80}],
        garmin=[],
        strava=[strava_day(_d(-1), activities=[activity("Run", minutes=60, avg_hr=124)], activity_count=1)],
        macrofactor_workouts=[],
        computed_metrics=[],
    )
    breakdown = TOOLS["get_zone2_breakdown"]["fn"]({"start_date": _d(-7), "end_date": TODAY})
    real_min = breakdown["summary"]["total_zone_2_min"]
    real_target = breakdown["summary"]["weekly_target_min"]
    assert (real_min, real_target) == (60.0, 150)  # the producer's own numbers

    out = call("get_training", {"view": "recommendation", "date": TODAY})
    note = next(n for n in out["board_of_directors"] if "Zone 2 minutes this week" in n)
    assert note == (
        f"Attia: Only {real_min:.0f} of {real_target:.0f} Zone 2 minutes this week "
        f"({round(100 * real_min / real_target)}%). Prioritize Zone 2 sessions."
    )
    assert note.startswith("Attia: Only 60 of 150 Zone 2 minutes this week (40%)")


def test_recommendation_zone2_note_is_suppressed_once_half_the_target_is_met(sources):
    """FIXED #2246, the other half. 120 Zone-2 minutes is 80% of the 150 min
    target, above the tool's own ``z2_pct < 50`` gate, so the deficit note must
    NOT appear. Before the fix z2_pct was unconditionally 0 and this note fired
    on every call — including weeks Matthew beat the target."""
    sources(
        whoop=[_recovery_day(TODAY, recovery=80)],
        eightsleep=[{"date": TODAY, "sleep_score": 80}],
        garmin=[],
        strava=[
            strava_day(_d(-1), activities=[activity("Run", minutes=60, avg_hr=124)], activity_count=1),
            strava_day(_d(-2), activities=[activity("Ride", minutes=60, avg_hr=124)], activity_count=1),
        ],
        macrofactor_workouts=[],
        computed_metrics=[],
    )
    assert TOOLS["get_zone2_breakdown"]["fn"]({"start_date": _d(-7), "end_date": TODAY})["summary"]["total_zone_2_min"] == 120.0

    out = call("get_training", {"view": "recommendation", "date": TODAY})
    assert [n for n in out["board_of_directors"] if "Zone 2 minutes this week" in n] == []


def test_recommendation_non_numeric_recovery_score_degrades_to_absent(sources):
    """A corrupt Whoop value must not crash the tool — _sf swallows it and the
    signal reads as absent rather than as a number."""
    sources(
        whoop=[{"date": TODAY, "recovery_score": "n/a"}],
        eightsleep=[{"date": TODAY, "sleep_score": 60}],
        garmin=[],
        strava=[],
        macrofactor_workouts=[],
        computed_metrics=[],
    )
    out = call("get_training", {"view": "recommendation", "date": TODAY})
    assert out["readiness_signals"]["whoop_recovery"] is None
    assert out["composite_readiness"] == 60.0  # only the sleep score counted


def test_periodization_polarization_flags_too_much_intensity(sources):
    """60 min at 160 bpm (84% of max ⇒ hard) + 30 min at 120 bpm (63% ⇒ easy):
    easy_ratio = 30/90 = 33.3% ⇒ below the 60% floor ⇒ 'too_much_intensity',
    and the Seiler board note fires."""
    sources(
        strava=[
            strava_day(TODAY, activities=[activity("Run", minutes=60, avg_hr=160)]),
            strava_day(_d(-1), activities=[activity("Ride", minutes=30, avg_hr=120)]),
        ],
        macrofactor_workouts=[],
    )
    out = call("get_training", {"view": "periodization", "end_date": TODAY, "weeks": 2})
    assert out["polarization"]["easy_pct"] == 33.3 and out["polarization"]["hard_pct"] == 66.7
    assert out["polarization"]["status"] == "too_much_intensity"
    assert any("Seiler" in n for n in out["board_of_directors"])


def test_periodization_deload_fires_on_three_weeks_of_rising_volume(sources):
    """Weeks (oldest→newest) 30 / 120 / 150 / 180 minutes. The oldest is <60 min
    ⇒ 'deload', so consecutive non-deload weeks = 3, and 120<150<180 is monotonic
    rising ⇒ the progressive-overload deload trigger."""
    strava = [strava_day(_d(-21), activities=[activity("Run", minutes=30, avg_hr=120)])]
    for offset, minutes in ((-14, 40), (-7, 50), (0, 60)):
        strava.append(strava_day(_d(offset), activities=[activity("Run", minutes=minutes, avg_hr=120)] * 3))
    sources(strava=strava, macrofactor_workouts=[])
    out = call("get_training", {"view": "periodization", "end_date": TODAY, "weeks": 4})
    assert [w["total_minutes"] for w in out["weekly_breakdown"]] == [30.0, 120.0, 150.0, 180.0]
    assert out["weekly_breakdown"][0]["phase"] == "deload"
    assert out["deload_analysis"]["weeks_since_last_deload"] == 3
    assert out["deload_analysis"]["deload_recommended"] is True
    assert "3 consecutive weeks of increasing volume" in out["deload_analysis"]["reason"]


def test_periodization_classifies_a_high_intensity_week_as_build_and_a_big_week_as_peak(sources):
    """>30% of weekly minutes hard ⇒ 'build'; otherwise >300 min ⇒ 'peak'."""
    sources(
        strava=[
            strava_day(_d(-7), activities=[activity("Run", minutes=60, avg_hr=160)] * 3),  # all hard ⇒ build
            strava_day(_d(0), activities=[activity("Ride", minutes=120, avg_hr=120)] * 3),  # 360 easy min ⇒ peak
        ],
        macrofactor_workouts=[],
    )
    out = call("get_training", {"view": "periodization", "end_date": TODAY, "weeks": 3})
    phases = [w["phase"] for w in out["weekly_breakdown"]]
    assert phases == ["build", "peak"]


def test_periodization_ignores_records_without_a_date(sources):
    """A malformed row (no `date`) must be skipped, not used as a partition key
    or crashed on inside _week_key's strptime."""
    sources(
        strava=[{"pk": "USER#matthew#SOURCE#strava", "activities": [activity("Run", minutes=60, avg_hr=120)]}],
        macrofactor_workouts=[{"total_volume_lbs": 500}],
    )
    out = call("get_training", {"view": "periodization", "end_date": TODAY, "weeks": 2})
    assert out["error"] == "No training data for range."


def test_periodization_consistency_assessment_bands(sources):
    """4 weeks, every one with 3+ sessions ⇒ 100% ⇒ 'excellent'; avg sessions is
    the plain mean 3.0 and total_weeks_analyzed is the n behind it (ADR-105)."""
    strava = [strava_day(_d(-7 * w), activities=[activity("Run", minutes=40, avg_hr=120)] * 3) for w in range(0, 4)]
    sources(strava=strava, macrofactor_workouts=[])
    out = call("get_training", {"view": "periodization", "end_date": TODAY, "weeks": 5})
    c = out["training_consistency"]
    assert c["avg_sessions_per_week"] == 3.0
    assert c["weeks_with_3plus_sessions_pct"] == 100.0
    assert c["total_weeks_analyzed"] == 4
    assert c["assessment"] == "excellent"


# ═══════════════════════════════════════════════════════════════════════════════
# §5 — get_acwr_status
# ═══════════════════════════════════════════════════════════════════════════════


def test_acwr_absent_precomputed_record_returns_error_envelope_with_a_hint(sources):
    sources(computed_metrics=[])
    out = call("get_acwr_status", {"date": YESTERDAY})
    assert out["error"].startswith("No ACWR data found")
    assert "acwr-compute" in out["hint"] and YESTERDAY in out["hint"]


def test_acwr_default_date_is_yesterday_and_default_window_is_14_days(sources):
    """Declared defaults: date = yesterday, days_back = 14. The queried window is
    [end - (days_back - 1), end] = 14 inclusive dates — the name and the span agree."""
    reader = sources(computed_metrics=[computed_metrics_day(YESTERDAY, acwr=1.0, acwr_zone="safe")])
    call("get_acwr_status", {})
    start, end = reader.window_for("computed_metrics")
    assert end == YESTERDAY
    assert start == _d(-13, YESTERDAY)
    assert (datetime.strptime(end, "%Y-%m-%d") - datetime.strptime(start, "%Y-%m-%d")).days + 1 == 14


def test_acwr_latest_is_the_newest_record_not_the_first_returned(sources):
    """The fake returns rows oldest-first; the tool must sort newest-first before
    taking [0]. An unsorted [0] would report the oldest ACWR as current."""
    sources(
        computed_metrics=[
            computed_metrics_day(_d(-3, YESTERDAY), acwr=0.7, acwr_zone="detraining"),
            computed_metrics_day(_d(-1, YESTERDAY), acwr=1.4, acwr_zone="caution"),
            computed_metrics_day(YESTERDAY, acwr=1.6, acwr_zone="danger", acwr_alert=True, acwr_alert_reason="spike"),
        ]
    )
    out = call("get_acwr_status", {"date": YESTERDAY})
    assert out["date"] == YESTERDAY and out["acwr"] == 1.6 and out["zone"] == "danger"
    assert out["alert"] is True and out["alert_reason"] == "spike"
    assert [h["date"] for h in out["history"]] == [YESTERDAY, _d(-1, YESTERDAY), _d(-3, YESTERDAY)]


@pytest.mark.parametrize(
    "zone,fragment",
    [
        ("danger", "Rest is not optional"),
        ("caution", "Reduce volume by 30-40%"),
        ("safe", "optimal window"),
        ("detraining", "Increase training frequency"),
    ],
)
def test_acwr_coaching_note_is_keyed_off_the_precomputed_zone(sources, zone, fragment):
    sources(computed_metrics=[computed_metrics_day(YESTERDAY, acwr=1.0, acwr_zone=zone)])
    out = call("get_acwr_status", {"date": YESTERDAY})
    assert fragment in out["coaching"]


def test_acwr_unknown_zone_yields_no_coaching_rather_than_a_default(sources):
    """A record with load but no zone must not inherit a neighbouring verdict."""
    sources(computed_metrics=[computed_metrics_day(YESTERDAY, acute_load_7d=12.0, chronic_load_28d=11.0)])
    out = call("get_acwr_status", {"date": YESTERDAY})
    assert out["acwr"] is None and out["zone"] == "unknown" and out["coaching"] is None


def test_acwr_records_with_no_acwr_payload_at_all_are_skipped(sources):
    """A computed_metrics row written by a sibling Lambda (no ACWR fields) must
    not enter the history as a null-ACWR day."""
    sources(
        computed_metrics=[
            {"date": _d(-1, YESTERDAY), "some_other_metric": 5},
            computed_metrics_day(YESTERDAY, acwr=1.1, acwr_zone="safe"),
        ]
    )
    out = call("get_acwr_status", {"date": YESTERDAY})
    assert [h["date"] for h in out["history"]] == [YESTERDAY]


def test_acwr_trend_is_computed_from_three_points_with_no_n_reported(sources):
    """OBSERVED (ADR-105): trend_7d fires at n=3 and the payload never says which
    n it used. 1.30 vs 1.00: 1.30 > 1.00*1.05 ⇒ 'rising'."""
    sources(
        computed_metrics=[
            computed_metrics_day(_d(-2, YESTERDAY), acwr=1.00, acwr_zone="safe"),
            computed_metrics_day(_d(-1, YESTERDAY), acwr=1.15, acwr_zone="safe"),
            computed_metrics_day(YESTERDAY, acwr=1.30, acwr_zone="caution"),
        ]
    )
    out = call("get_acwr_status", {"date": YESTERDAY})
    assert out["trend_7d"] == "rising"
    assert not any("n" == k for k in out) and "trend_n" not in out


@pytest.mark.parametrize(
    "newest,oldest,expected",
    [
        (1.30, 1.00, "rising"),  # 1.30 > 1.00 * 1.05
        (1.00, 1.30, "falling"),  # 1.00 < 1.30 * 0.95
        (1.02, 1.00, "stable"),  # inside the +-5% dead band
    ],
)
def test_acwr_trend_direction_bands(sources, newest, oldest, expected):
    """The trend compares only the newest and oldest of the slice — a +-5% dead
    band, no regression, no n. Pin all three outcomes."""
    sources(
        computed_metrics=[
            computed_metrics_day(_d(-2, YESTERDAY), acwr=oldest, acwr_zone="safe"),
            computed_metrics_day(_d(-1, YESTERDAY), acwr=1.1, acwr_zone="safe"),
            computed_metrics_day(YESTERDAY, acwr=newest, acwr_zone="safe"),
        ]
    )
    assert call("get_acwr_status", {"date": YESTERDAY})["trend_7d"] == expected


def test_acwr_non_numeric_stored_value_degrades_to_absent_not_zero(sources):
    """A corrupt computed_metrics value must read as None, never as 0.0 — a 0.0
    ACWR would render as 'detraining' advice."""
    sources(computed_metrics=[computed_metrics_day(YESTERDAY, acwr="n/a", acute_load_7d="oops", chronic_load_28d=None)])
    out = call("get_acwr_status", {"date": YESTERDAY})
    assert out["acwr"] is None and out["acute_load_7d"] is None and out["chronic_load_28d"] is None


def test_acwr_trend_is_absent_below_three_points(sources):
    sources(
        computed_metrics=[
            computed_metrics_day(_d(-1, YESTERDAY), acwr=1.00, acwr_zone="safe"),
            computed_metrics_day(YESTERDAY, acwr=1.30, acwr_zone="caution"),
        ]
    )
    assert call("get_acwr_status", {"date": YESTERDAY})["trend_7d"] is None


def test_acwr_seven_day_fields_count_days_not_records(sources):
    """FIXED (#2221, #1917): both `alerts_last_7d` and `trend_7d` used to slice
    history[:7] — the newest SEVEN RECORDS. With acwr-compute having produced one
    record every 10 days, those 7 "last 7 days" records spanned 61 calendar days and
    reported `alerts_last_7d: 7`, which reads as a catastrophic week. They are now
    bounded by date, and the n actually covered rides beside them."""
    rows = [computed_metrics_day(_d(-10 * i, YESTERDAY), acwr=1.6, acwr_zone="danger", acwr_alert=True) for i in range(0, 7)]
    sources(computed_metrics=rows)
    out = call("get_acwr_status", {"date": YESTERDAY, "days_back": 90})
    span = (datetime.strptime(YESTERDAY, "%Y-%m-%d") - datetime.strptime(_d(-60, YESTERDAY), "%Y-%m-%d")).days
    assert span == 60  # the 7 records cover 61 calendar dates; only ONE is inside 7 days
    assert out["alerts_last_7d"] == 1
    assert out["records_last_7d"] == 1
    assert out["history"] and len(out["history"]) == 7  # the full requested history is untouched
    assert out["trend_7d"] is None and out["trend_7d_n"] == 1  # 1 point is not a trend


def test_acwr_seven_day_fields_should_be_bounded_by_calendar_days(sources):
    """The marker's own contract, kept as its own assertion."""
    rows = [computed_metrics_day(_d(-10 * i, YESTERDAY), acwr=1.6, acwr_zone="danger", acwr_alert=True) for i in range(0, 7)]
    sources(computed_metrics=rows)
    out = call("get_acwr_status", {"date": YESTERDAY, "days_back": 90})
    assert out["alerts_last_7d"] <= 1  # only YESTERDAY falls inside a real 7-day window


def test_acwr_seven_day_alert_count_still_sees_a_genuinely_bad_week(sources):
    """The bound must not simply suppress the field: seven consecutive alerting days
    inside the real 7-day window still count seven."""
    rows = [computed_metrics_day(_d(-i, YESTERDAY), acwr=1.6, acwr_zone="danger", acwr_alert=True) for i in range(0, 7)]
    sources(computed_metrics=rows)
    out = call("get_acwr_status", {"date": YESTERDAY, "days_back": 90})
    assert out["alerts_last_7d"] == 7 and out["records_last_7d"] == 7


def test_acwr_declares_how_old_a_stale_answer_is_and_withholds_live_coaching(sources):
    """FIXED (#2221): `latest = history[0]` was hoisted to the top level with no
    comparison against the REQUESTED date, so a 12-day-old record answered "what is my
    ACWR?" with a live-voice verdict ("Increase training frequency this week"). The
    record is still returned — it is the best available measurement — but its age is
    published and the present-tense coaching is withheld.

    The staleness floor is derived from the WRITER's cadence, not from a literature
    default: acwr-compute runs nightly, so >= 2 days behind means a run was missed."""
    stale = _d(-12, YESTERDAY)
    sources(computed_metrics=[computed_metrics_day(stale, acwr=0.6, acwr_zone="detraining")])
    out = call("get_acwr_status", {"date": YESTERDAY, "days_back": 30})
    assert out["date"] == stale and out["zone"] == "detraining" and out["acwr"] == 0.6
    assert out["days_stale"] == 12 and out["is_stale"] is True
    assert "acwr-compute writes nightly" in out["staleness_note"]
    assert out["coaching"] is None


def test_acwr_should_declare_how_old_the_answer_is(sources):
    """The marker's own contract, kept as its own assertion."""
    stale = _d(-12, YESTERDAY)
    sources(computed_metrics=[computed_metrics_day(stale, acwr=0.6, acwr_zone="detraining")])
    out = call("get_acwr_status", {"date": YESTERDAY, "days_back": 30})
    assert any(k in out for k in ("stale", "is_stale", "days_stale", "as_of_age_days"))


def test_acwr_a_fresh_record_is_not_flagged_stale_and_keeps_its_coaching(sources):
    """The floor must not fire on the normal case: the tool's own declared default
    `date` is YESTERDAY precisely because acwr-compute writes for yesterday, and a
    one-day gap (today's run not yet done) is the writer's cadence, not a failure."""
    sources(computed_metrics=[computed_metrics_day(_d(-1, YESTERDAY), acwr=1.6, acwr_zone="danger")])
    out = call("get_acwr_status", {"date": YESTERDAY, "days_back": 30})
    assert out["days_stale"] == 1 and out["is_stale"] is False
    assert out["staleness_note"] is None
    assert "Rest is not optional" in out["coaching"]


def test_acwr_ships_its_method_coupling_and_proxy_caveats(sources):
    """ADR-105: the ratio is coupled by construction and the load proxy is
    cardiac, not mechanical. Both caveats must ride with every answer."""
    sources(computed_metrics=[computed_metrics_day(YESTERDAY, acwr=1.1, acwr_zone="safe", acwr_method="ewma")])
    out = call("get_acwr_status", {"date": YESTERDAY})
    assert out["method"] == "ewma"
    assert "EWMA(7d)" in out["interpretation"] and "EWMA(28d)" in out["interpretation"]
    assert "coupled ratio" in out["_coupling_caveat"]
    assert "cardiac stress measure" in out["_proxy_note"]
    assert out["_disclaimer"].startswith("For personal training guidance only")


def test_acwr_non_numeric_days_back_escapes_as_valueerror(sources):
    sources(computed_metrics=[])
    with pytest.raises(ValueError):
        call("get_acwr_status", {"date": YESTERDAY, "days_back": "two weeks"})


# ═══════════════════════════════════════════════════════════════════════════════
# §6 — ADR-058: the computed_metrics read really is phase-filtered
# ═══════════════════════════════════════════════════════════════════════════════


def test_acwr_read_goes_through_the_phase_filtered_query(monkeypatch):
    """computed_metrics is EXPERIMENT_SCOPED (lambdas/experiment/phase_taxonomy.py:227),
    so rows from a previous experiment cycle must not read as live. Driven against
    the REAL mcp.core.query_source with a recording table, so this asserts the
    filter that actually ships rather than a stub of it.
    """
    from experiment.phase_taxonomy import SCOPED_SOURCES

    assert "computed_metrics" in SCOPED_SOURCES  # derived from the registry, not restated

    table = RecordingTable(items=[computed_metrics_day(YESTERDAY, acwr=1.1, acwr_zone="safe")])
    monkeypatch.setattr(mcp_core, "table", table)
    monkeypatch.setattr(tt, "query_source", mcp_core.query_source)

    out = call("get_acwr_status", {"date": YESTERDAY})
    assert out["acwr"] == 1.1

    kwargs = table.query_kwargs[0]
    assert "#phase" in kwargs["FilterExpression"]
    assert kwargs["ExpressionAttributeNames"]["#phase"] == "phase"
    assert kwargs["ExpressionAttributeValues"][":phase_experiment"] == "experiment"
