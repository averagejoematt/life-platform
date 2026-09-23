"""tests/test_producer_census_4034.py — the producer census dead-man (#4034 box 1).

`deploy/sentinel_producer_census.py` grades every Lambda that can write a
`deploy/emf_namespace_ledger.py` namespace on AWS/Lambda Invocations against its cadence,
riding the drift sentinel (no new schedule). These tests hold:

  * the population is DERIVED from the ledger's producers through the handler import
    closure (not the CDK schedule list), and every member lands in exactly one class;
  * the hand-kept rows (EVENT_WINDOWS / PAUSED / FIRST_DUE / ON_DEMAND) cannot go stale —
    a row for a non-member, a PAUSED row the source registry contradicts, and a FIRST_DUE
    row past its own window all red;
  * a planted silent producer makes the census drift (the detect half), and an unreadable
    Invocations read or a vacuous population is `error`, never clean (the cannot-observe
    half) — both halves cited from tests/test_sentinel_canfail_2578.py.
"""

import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for sub in ("deploy", "tests", "lambdas"):
    p = os.path.join(_ROOT, sub)
    if p not in sys.path:
        sys.path.insert(0, p)

import sentinel_producer_census as pc  # noqa: E402

NOW = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def population():
    return pc.census_population()


@pytest.fixture(scope="module")
def cadences():
    return pc.scheduled_cadences()


@pytest.fixture(scope="module")
def windows(population, cadences):
    return pc.member_windows(population, cadences)


# ── population: derived, non-vacuous, not the schedule list ─────────────────


def test_population_is_derived_and_not_vacuous(population, cadences):
    assert len(population) >= 80, f"census population collapsed to {len(population)} — the import-closure derivation rotted"
    # a producer with NO schedule is a member — the thing a CDK schedule list cannot see
    assert "life-platform-site-api" in population and "life-platform-site-api" not in cadences
    # a producer that emits only through a shared module is a member (coach -> ai/bedrock_client)
    assert "LifePlatform/AI" in population["coach-daily-reflection"]["namespaces"]
    # a Lambda that writes no ledger namespace is not
    assert "life-platform-key-rotator" not in population


def test_every_member_lands_in_a_gradable_or_named_class(windows):
    bad = sorted(fn for fn, w in windows.items() if w["class"] in ("unregistered", pc.VERDICT_UNREADABLE))
    assert not bad, (
        "Census member(s) with no gradable cadence and no named row. A scheduled member needs a cadence the #3506 "
        "resolver can read; an event-driven one needs a MEASURED EVENT_WINDOWS row (or, if silence truly carries no "
        "information, a dated ON_DEMAND row):\n  " + "\n  ".join(bad)
    )


def test_hand_rows_name_only_members_and_do_not_overlap(population, cadences):
    for label, rows in (
        ("EVENT_WINDOWS", pc.EVENT_WINDOWS),
        ("PAUSED", pc.PAUSED),
        ("FIRST_DUE", pc.FIRST_DUE),
        ("ON_DEMAND", pc.ON_DEMAND),
    ):
        stale = sorted(set(rows) - set(population))
        assert not stale, f"{label} row(s) for Lambdas that are no longer census members: {stale}"
    for label, rows in (("EVENT_WINDOWS", pc.EVENT_WINDOWS), ("ON_DEMAND", pc.ON_DEMAND)):
        scheduled = sorted(fn for fn in rows if cadences.get(fn))
        assert not scheduled, f"{label} row(s) for Lambdas that HAVE a readable schedule — grade them on it: {scheduled}"
    overlap = set(pc.EVENT_WINDOWS) & set(pc.ON_DEMAND)
    assert not overlap, f"a member is both windowed and on-demand: {overlap}"


def test_event_windows_carry_their_evidence():
    for fn, row in pc.EVENT_WINDOWS.items():
        assert row["window_days"] * 24 >= 2 * row["gap_h"], f"{fn}: window below 2x its own measured gap — it would red on a normal week"
        assert len(row["trigger"]) >= 20, f"{fn}: name what invokes it"


def test_paused_rows_are_derived_from_the_source_registry():
    from ingestion.source_registry import SOURCE_REGISTRY

    for fn, source in pc.PAUSED.items():
        assert (
            SOURCE_REGISTRY.get(source, {}).get("paused") is True
        ), f"{fn}: PAUSED names {source!r}, which the source registry does not mark paused"


def test_first_due_rows_expire_on_their_own(cadences):
    for fn, row in pc.FIRST_DUE.items():
        rate = cadences.get(fn)
        assert rate, f"{fn}: FIRST_DUE needs a readable schedule"
        due = datetime.fromisoformat(row["first_due"]).replace(tzinfo=timezone.utc)
        assert datetime.now(timezone.utc) <= due + timedelta(
            hours=pc.stale_window_hours(rate)
        ), f"{fn}: FIRST_DUE {row['first_due']} + its window has passed — delete the row; the census grades it now"


def test_on_demand_rows_are_dated_and_reasoned():
    for fn, row in pc.ON_DEMAND.items():
        since = datetime.strptime(row["since"], "%Y-%m-%d").date()
        assert since <= datetime.now(timezone.utc).date(), f"{fn}: dated in the future"
        assert (datetime.now(timezone.utc).date() - since).days <= 365, f"{fn}: re-attest the on-demand row (365-day cap)"
        assert len(row["reason"]) >= 40, f"{fn}: state why silence carries no information"


# ── grading (pure) ──────────────────────────────────────────────────────────


def test_stale_window_math():
    assert pc.stale_window_hours(48) == pc.STALE_FLOOR_HOURS  # half-hourly: floored
    assert pc.stale_window_hours(1.0) == 2 * 24 + 24  # daily
    assert pc.stale_window_hours(1 / 7.0) == pytest.approx(2 * 168 + 24)  # weekly


def _windows():
    return {
        "daily-producer": {"class": "scheduled", "window_hours": 72.0},
        "event-producer": {"class": "event", "window_hours": 72.0},
        "quarterly-newborn": {"class": "scheduled", "window_hours": 24 * 184.0, "first_due": "2026-10-01"},
        "button": {"class": pc.VERDICT_ON_DEMAND, "window_hours": None},
    }


def test_all_fresh_is_clean_and_on_demand_is_not_counted_as_ok():
    last = {"daily-producer": NOW - timedelta(hours=20), "event-producer": NOW - timedelta(hours=30), "quarterly-newborn": None}
    out = pc.summarize(pc.grade(_windows(), last, NOW))
    assert out["status"] == "clean", out["detail"]
    assert out["graded"] == 2 and out["on_demand"] == ["button"]
    assert {r["function"]: r["verdict"] for r in out["rows"]}["quarterly-newborn"] == pc.VERDICT_FIRST_DUE


def test_a_planted_silent_producer_drifts():
    """The detect half: one producer silent past its window reds the census, by name."""
    last = {"daily-producer": NOW - timedelta(hours=100), "event-producer": NOW - timedelta(hours=30), "quarterly-newborn": None}
    out = pc.summarize(pc.grade(_windows(), last, NOW))
    assert out["status"] == "drift" and out["silent"] == ["daily-producer"], out
    assert "daily-producer" in out["detail"] and "window 3.0d" in out["detail"]


def test_never_seen_in_the_lookback_is_silent():
    out = pc.summarize(pc.grade(_windows(), {"event-producer": NOW - timedelta(hours=1)}, NOW))
    assert "daily-producer" in out["silent"], out


def test_first_due_expires_into_silent():
    later = datetime(2027, 4, 15, tzinfo=timezone.utc)
    rows = {r["function"]: r["verdict"] for r in pc.grade(_windows(), {}, later)}
    assert rows["quarterly-newborn"] == pc.VERDICT_SILENT


def test_vacuous_population_is_error_not_clean():
    out = pc.summarize(pc.grade({"button": {"class": pc.VERDICT_ON_DEMAND, "window_hours": None}}, {}, NOW))
    assert out["status"] == "error" and "grades nothing" in out["detail"]


# ── the live-read seam, on the GetMetricData wire shape ─────────────────────


class _CW:
    """get_metric_data stub on the real response shape: one result per query, Label ==
    the function name, Timestamps/Values newest-first (ScanBy=TimestampDescending)."""

    def __init__(self, silent=(), fail=False):
        self.silent, self.fail, self.calls = set(silent), fail, 0

    def get_metric_data(self, **kw):
        self.calls += 1
        if self.fail:
            raise RuntimeError("AccessDenied: cloudwatch:GetMetricData")
        assert kw["ScanBy"] == "TimestampDescending" and len(kw["MetricDataQueries"]) <= 500
        results = []
        for q in kw["MetricDataQueries"]:
            assert q["MetricStat"]["Metric"]["Namespace"] == "AWS/Lambda"
            fn = q["Label"]
            day = (kw["EndTime"] - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            ts, vals = ([], []) if fn in self.silent else ([day, day - timedelta(days=1)], [3.0, 0.0])
            results.append({"Id": q["Id"], "Label": fn, "Timestamps": ts, "Values": vals, "StatusCode": "Complete"})
        return {"MetricDataResults": results}


def test_check_is_clean_on_the_real_population_when_every_producer_ran():
    out = pc.check_producer_census(cw=_CW(), now=NOW)
    assert out["status"] == "clean", out["detail"]
    assert out["graded"] >= 70


def test_check_drifts_on_a_planted_silent_producer_in_the_real_population():
    out = pc.check_producer_census(cw=_CW(silent={"daily-brief"}), now=NOW)
    assert out["status"] == "drift" and out["silent"] == ["daily-brief"], out["detail"]


def test_check_is_error_when_invocations_are_unreadable():
    """The cannot-observe half: a denied read is `error`, never clean."""
    out = pc.check_producer_census(cw=_CW(fail=True), now=NOW)
    assert out["status"] == "error" and "GetMetricData" in out["detail"], out


def test_a_census_drift_reaches_the_needs_human_signal():
    """Through run_sweep's contract: drift_report.as_signal flags any check whose status is 'drift'."""
    sys.path.insert(0, os.path.join(_ROOT, "remediation"))
    import drift_report

    record = {
        "status": "drift",
        "date": "2026-09-23",
        "checks": {"producer_census": pc.check_producer_census(cw=_CW(silent={"daily-brief"}), now=NOW)},
    }
    sig = drift_report.as_signal(record)
    assert sig and "producer_census" in str(sig), sig
