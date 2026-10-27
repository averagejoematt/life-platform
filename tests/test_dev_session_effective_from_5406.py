"""tests/test_dev_session_effective_from_5406.py — the monthly dev-session envelope starts 2026-11-01 (#5406).

Owner ruling 2026-10-27 on #5406, verbatim "B": start the cap at 2026-11-01, a dated
effective-from, so October reads as un-capped. What is held here, all on a frozen clock:

  * before the date the MONTH rule does not refuse (month spend over $60 goes), while the
    per-run and rolling-24h caps that predate the envelope still refuse;
  * from 2026-11-01 00:00Z the month rule refuses as it did;
  * the cost governor's `DevSessionSpendMTD` gauge reads 0 for October (so
    `ai-dev-session-month-high` clears) and the real figure from November.

Mutation control (run by hand, 2026-10-26): setting `MONTH_CAP_EFFECTIVE_FROM` to a date before
October, or dropping the `month_in_force` test in `decide`, fails the October tests below.
Dollar figures only. Run: python3 -m pytest tests/test_dev_session_effective_from_5406.py -v
"""

from __future__ import annotations

import os
import sys
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))

from ai import dev_session_cap as cap  # noqa: E402
from operational import episodic_premise  # noqa: E402

OCT_27 = datetime(2026, 10, 27, 1, 50, tzinfo=timezone.utc)
LAST_INSTANT_OF_OCT = datetime(2026, 10, 31, 23, 59, 59, tzinfo=timezone.utc)
NOV_1 = datetime(2026, 11, 1, 0, 0, tzinfo=timezone.utc)
# At exactly 00:00Z the month window is empty (the metric read needs a minute of span), so the
# end-to-end refusals run just after midnight; the edge itself is held on `month_cap_in_force`.
NOV_1_JUST_AFTER = NOV_1 + timedelta(minutes=5)


def _freeze(monkeypatch, instant: datetime) -> None:
    class _Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant if tz is None else instant.astimezone(tz)

    monkeypatch.setattr(cap, "datetime", _Frozen)


class _Windows:
    """CloudWatch stand-in: the 24-hour query returns `day`, the month-to-date one `month`."""

    def __init__(self, day: float, month: float):
        self.day, self.month = day, month

    def get_metric_statistics(self, **kw):
        span = kw["EndTime"] - kw["StartTime"]
        return {"Datapoints": [{"Sum": self.day if span == timedelta(hours=cap.DAY_WINDOW_HOURS) else self.month}]}


@pytest.fixture
def laptop(monkeypatch):
    for var in ("AWS_LAMBDA_FUNCTION_NAME", "GITHUB_ACTIONS", "CI", "INVOCATION_CONTEXT", cap.OVERRIDE_ENV):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("DEV_AI_CAP_UNDER_TEST", "1")
    cap._reset_for_tests()
    yield
    cap._reset_for_tests()


def _check(windows: _Windows) -> None:
    cap.check("dev-session", lambda: windows)


# ── the date itself ──────────────────────────────────────────────────────────────────
def test_the_effective_from_date_is_the_owners_and_the_edge_is_midnight_utc():
    assert cap.MONTH_CAP_EFFECTIVE_FROM == date(2026, 11, 1)
    assert cap.month_cap_in_force(OCT_27) is False
    assert cap.month_cap_in_force(LAST_INSTANT_OF_OCT) is False
    assert cap.month_cap_in_force(NOV_1) is True
    assert cap.month_cap_in_force(NOV_1 - timedelta(seconds=1)) is False
    # the date is UTC, not the reader's zone: 10-31 17:00 Pacific is already 11-01 00:00Z
    pacific = timezone(timedelta(hours=-7))
    assert cap.month_cap_in_force(datetime(2026, 10, 31, 17, 0, tzinfo=pacific)) is True


# ── the refusal ──────────────────────────────────────────────────────────────────────
def test_october_month_spend_over_the_envelope_is_not_refused_by_the_month_rule(monkeypatch, laptop):
    _freeze(monkeypatch, OCT_27)
    _check(_Windows(day=1.0, month=75.0))  # raises nothing: $75 this month, $1 today, nothing run yet


def test_october_still_refuses_on_the_per_run_cap(monkeypatch, laptop):
    _freeze(monkeypatch, OCT_27)
    cap.record("dev-session", cap.PER_RUN_USD + 0.5)
    with pytest.raises(cap.DevSessionBudgetExceeded) as stop:
        _check(_Windows(day=0.0, month=75.0))
    assert "per-run limit" in str(stop.value) and cap._MONTH_MARK not in str(stop.value)


def test_october_still_refuses_on_the_rolling_24_hour_cap(monkeypatch, laptop):
    _freeze(monkeypatch, OCT_27)
    with pytest.raises(cap.DevSessionBudgetExceeded) as stop:
        _check(_Windows(day=cap.PER_DAY_USD + 0.5, month=75.0))
    assert "last 24 hours" in str(stop.value) and cap._MONTH_MARK not in str(stop.value)


def test_a_named_number_in_october_is_still_bounded_by_the_24_hour_total(monkeypatch, laptop):
    _freeze(monkeypatch, OCT_27)
    monkeypatch.setenv(cap.OVERRIDE_ENV, "20")
    _check(_Windows(day=19.0, month=75.0))  # under the named 20
    cap._reset_for_tests()
    with pytest.raises(cap.DevSessionBudgetExceeded):
        _check(_Windows(day=20.5, month=75.0))


def test_the_month_rule_applies_from_midnight_on_the_first(monkeypatch, laptop):
    _freeze(monkeypatch, NOV_1_JUST_AFTER)
    with pytest.raises(cap.DevSessionBudgetExceeded) as stop:
        _check(_Windows(day=1.0, month=75.0))
    assert cap._MONTH_MARK in str(stop.value)


def test_the_last_second_of_october_is_still_un_capped(monkeypatch, laptop):
    _freeze(monkeypatch, LAST_INSTANT_OF_OCT)
    _check(_Windows(day=1.0, month=75.0))


def test_decide_skips_only_the_month_rule_when_it_is_not_in_force():
    assert cap.decide(0.0, 0.0, None, 75.0, month_in_force=False) is None
    assert cap.decide(0.0, 0.0, None, 75.0, month_in_force=True) is not None
    assert cap.decide(0.0, 0.0, None, 75.0) is not None, "in force by default"
    assert "per-run" in cap.decide(cap.PER_RUN_USD, 0.0, None, 75.0, month_in_force=False)


def test_the_batch_check_follows_the_same_date(monkeypatch, laptop):
    _freeze(monkeypatch, OCT_27)
    cap.check_projected("dev-session", 1.0, lambda: _Windows(day=0.0, month=75.0))
    cap._reset_for_tests()
    _freeze(monkeypatch, NOV_1_JUST_AFTER)
    with pytest.raises(cap.DevSessionBudgetExceeded):
        cap.check_projected("dev-session", 1.0, lambda: _Windows(day=0.0, month=75.0))


# ── the gauge ────────────────────────────────────────────────────────────────────────
def _gauge(start: datetime, now: datetime, spent: float):
    cw = MagicMock()
    cw.get_metric_statistics.return_value = {"Datapoints": [{"Sum": spent}]}
    return cw, episodic_premise.publish_dev_session_month(cw, "CallerClass", start, now)


def test_the_governor_gauge_reads_zero_for_october_so_the_alarm_clears():
    start = datetime(2026, 10, 1, tzinfo=timezone.utc)
    cw, published = _gauge(start, OCT_27, 75.0)
    assert published == 0.0
    put = cw.put_metric_data.call_args.kwargs
    assert put["Namespace"] == "LifePlatform/Budget"
    assert put["MetricData"] == [{"MetricName": "DevSessionSpendMTD", "Value": 0.0, "Unit": "None"}], "emitted as 0, not omitted"


def test_the_governor_gauge_reads_the_real_figure_from_november():
    cw, published = _gauge(NOV_1, NOV_1 + timedelta(hours=3), 12.5)
    assert published == pytest.approx(12.5)
    assert cw.put_metric_data.call_args.kwargs["MetricData"][0]["Value"] == pytest.approx(12.5)
    cw, published = _gauge(NOV_1, datetime(2026, 11, 20, tzinfo=timezone.utc), 75.0)
    assert published == pytest.approx(75.0), "the alarm bar is reachable again in November"


def test_the_alarm_bar_still_derives_from_the_cap_module():
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import budget_ceilings  # noqa: PLC0415

    assert budget_ceilings.dev_session_month_cap_usd() == cap.PER_MONTH_USD
    assert budget_ceilings.dev_session_month_alarm_usd() == round(cap.PER_MONTH_USD * cap.MONTH_ALARM_FRACTION, 2)
