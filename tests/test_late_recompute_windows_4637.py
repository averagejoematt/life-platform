"""tests/test_late_recompute_windows_4637.py — #4637: a late or back-filled recompute of a
daily computed-metrics row builds its trailing windows from the TARGET day, not the wall clock.

THE DEFECT. `lambda_handler` takes the target day from `event["date"]`, but `assemble_data`
set `today = pacific_now().date()` and built every window as `[today - N, target]`. On the
scheduled run the two agree (target = today - 1). On a recompute a week late they do not:
the "7-day" windows collapse to the target alone (start = target, end = target), the load
model decays a further week of zero-load days, the week-ago weigh-in is looked up at the
target itself, readiness reads the recovery of the day the operator happened to run it, and
the protein window ends on the real today. The row then describes a different period than
its date.

THE RULE. Inside `assemble_data`, "today" is `window_anchor(target)` — the target's
morning-after. Nothing there reads the clock for a window.

Every value below is SYNTHETIC (a function of the day index); none is a real reading.

Three things are pinned:
  1. each window's BOUNDS, on a recompute eight days late;
  2. the wall-clock guard — the late recompute returns exactly what the on-time run
     returned, and `assemble_data` still runs with every clock it could reach rigged to
     explode. Mutation-proved (see the PR): putting any one window back on
     `pacific_now()` reds it;
  3. the stored row's `computed_lag_days` mark, 1 on time and >= 2 late, as a Decimal.
"""

import os
import sys
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

_REPO = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.dirname(__file__))

os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("TABLE_NAME", "test-table")
os.environ.setdefault("USER_ID", "matthew")

import compute.daily_metrics_compute_lambda as dmc  # noqa: E402
from health import weight_trend  # noqa: E402
from pacific_clock import freeze_pacific  # noqa: E402

GENESIS = "2026-04-01"
TARGET = "2026-05-09"
T = date.fromisoformat(TARGET)
ANCHOR = T + timedelta(days=1)  # the on-time run's "today"
LATE_BY = 8  # days after the on-time run that the recompute happens


def _d(offset):
    """The day key `offset` days from the target (negative = before)."""
    return (T + timedelta(days=offset)).isoformat()


def _noon_utc(day):
    """19:00Z is midday Pacific on `day` in both DST states — never near a day boundary."""
    return datetime(day.year, day.month, day.day, 19, 0, 0, tzinfo=timezone.utc)


ON_TIME_NOW = _noon_utc(ANCHOR)
LATE_NOW = _noon_utc(ANCHOR + timedelta(days=LATE_BY))


class _Table:
    """Minimal DynamoDB Table double: get_item + the `sk BETWEEN` / begins_with queries."""

    def __init__(self):
        self.items = {}
        self.puts = []

    def put_item(self, Item=None, **_kw):
        self.puts.append(Item)
        self.items[(Item["pk"], Item["sk"])] = Item
        return {}

    def get_item(self, Key=None, **_kw):
        item = self.items.get((Key["pk"], Key["sk"]))
        return {"Item": item} if item is not None else {}

    def query(self, **kwargs):
        vals = kwargs.get("ExpressionAttributeValues", {})
        rows = [v for (p, _s), v in self.items.items() if p == vals.get(":pk")]
        if ":s" in vals and ":e" in vals:
            rows = [r for r in rows if vals[":s"] <= r["sk"] <= vals[":e"]]
        prefix = vals.get(":prefix") or vals.get(":sk")
        if prefix:
            rows = [r for r in rows if str(r["sk"]).startswith(prefix)]
        return {"Items": sorted(rows, key=lambda r: r["sk"])}


def _seed(table):
    """75 days of synthetic rows on every source, running PAST the target up to the late
    'now' — so a window anchored on the wall clock has different data to pick up."""
    for off in range(-66, LATE_BY + 2):
        day, i = _d(off), off + 66
        rows = {
            "whoop": {
                "hrv": Decimal(str(40 + (i * 7) % 31)),
                "recovery_score": Decimal(str(30 + (i * 11) % 60)),
                "resting_heart_rate": Decimal(str(50 + i % 9)),
                "sleep_duration_hours": Decimal(str(5 + (i * 3) % 4)),
            },
            "withings": {"weight_lbs": Decimal(str(300 - i * 0.5))},
            "strava": {
                "activity_count": Decimal("1"),
                "activities": [{"id": f"ride-{i}", "sport_type": "Ride", "kilojoules": Decimal(str(200 + (i * 37) % 500))}],
            },
            "macrofactor": {"total_protein_g": Decimal(str(120 + (i * 13) % 70))},
            "habitify": {"habits": {"walk": Decimal(str(i % 2))}},
        }
        for source, fields in rows.items():
            table.items[(dmc.USER_PREFIX + source, "DATE#" + day)] = {
                "pk": dmc.USER_PREFIX + source,
                "sk": "DATE#" + day,
                "date": day,
                **fields,
            }


@pytest.fixture
def table(monkeypatch):
    t = _Table()
    _seed(t)
    monkeypatch.setattr(dmc, "table", t)
    monkeypatch.setattr(dmc, "EXPERIMENT_START_DATE", GENESIS)
    return t


def _freeze(monkeypatch, now):
    """Pin every clock `assemble_data` and its helpers can reach to `now`."""

    class _Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return now if tz else now.replace(tzinfo=None)

    monkeypatch.setattr(dmc, "datetime", _Frozen)
    freeze_pacific(monkeypatch, dmc, now)
    freeze_pacific(monkeypatch, weight_trend, now)


def _record_reads(monkeypatch):
    """Wrap the two read helpers; return the (source, start, end) calls they receive."""
    ranges, days = [], []
    real_range, real_date = dmc.fetch_range, dmc.fetch_date

    def fetch_range(source, start, end):
        ranges.append((source, start, end))
        return real_range(source, start, end)

    def fetch_date(source, date_str):
        days.append((source, date_str))
        return real_date(source, date_str)

    monkeypatch.setattr(dmc, "fetch_range", fetch_range)
    monkeypatch.setattr(dmc, "fetch_date", fetch_date)
    return ranges, days


PROFILE = {"goal_weight_lbs": 185.0, "sleep_target_hours_ideal": 7.5}


def test_a_late_recompute_anchors_every_window_on_the_target_day(table, monkeypatch):
    """Box 1: recompute a past day eight days late; assert each window's bounds."""
    _freeze(monkeypatch, LATE_NOW)
    ranges, days = _record_reads(monkeypatch)

    data, hrv_7d, hrv_30d = dmc.assemble_data(TARGET, PROFILE)

    anchor = ANCHOR.isoformat()
    expected = sorted(
        [
            ("whoop", _d(-6), TARGET),  # 7-day HRV
            ("whoop", _d(-29), TARGET),  # 30-day HRV
            ("strava", _d(-59), TARGET),  # fitness / fatigue / balance
            ("hevy", _d(-59), TARGET),
            ("whoop", _d(-6), TARGET),  # sleep debt
            ("withings", _d(-6), TARGET),  # latest weight
            ("withings", _d(-13), TARGET),  # week-ago weight
            ("withings", _d(-27), anchor),  # weight trajectory: 28 days ending the anchor
            ("apple_health", _d(-6), anchor),  # trajectory's newer-reading check
            ("habitify", _d(-6), TARGET),
            ("macrofactor", dmc.nutrition_logging.window_start(anchor, GENESIS), anchor),  # protein
        ]
    )
    assert sorted(ranges) == expected

    # No window reaches past the anchor — nothing from the days between the target and the
    # day the recompute actually ran can leak into the row.
    assert max(end for _s, _start, end in ranges) == anchor
    # The readiness input is the anchor morning's recovery, not the operator's day.
    assert [d for s, d in days if s == "whoop"] == [TARGET, anchor]
    assert data["whoop_today"]["date"] == anchor

    # Values, each from its own window: seven nights, not the target night alone...
    week = [float(table.items[(dmc.USER_PREFIX + "whoop", "DATE#" + _d(o))]["hrv"]) for o in range(-6, 1)]
    assert hrv_7d == round(sum(week) / 7, 1) == data["hrv"]["hrv_7d"]
    assert len(set(week)) > 1 and hrv_7d != week[-1]
    assert hrv_30d is not None and hrv_30d != hrv_7d
    # ...the week-ago weigh-in is the reading six days before the target, not the latest...
    assert data["latest_weight"] == float(table.items[(dmc.USER_PREFIX + "withings", "DATE#" + TARGET)]["weight_lbs"])
    assert data["week_ago_weight"] == float(table.items[(dmc.USER_PREFIX + "withings", "DATE#" + _d(-6))]["weight_lbs"])
    assert data["week_ago_weight"] != data["latest_weight"]
    # ...the load model is charged (a zero model cannot show a decay) and ends at the target...
    assert data["ctl"] > 0 and data["atl"] > 0 and data["tsb"] is not None
    # ...sleep debt sums seven nights, and the protein window names the anchor's window.
    nights = [float(table.items[(dmc.USER_PREFIX + "whoop", "DATE#" + _d(o))]["sleep_duration_hours"]) for o in range(-6, 1)]
    assert data["sleep_debt_7d_hrs"] == round(sum(max(0, 7.5 - n) for n in nights), 1) > 0
    assert data["protein_g_avg_since"] == dmc.nutrition_logging.window_start(anchor, GENESIS)


def test_no_window_reads_the_wall_clock_when_a_target_date_is_set(table, monkeypatch):
    """Box 2: the guard. Two halves, either of which reds on a window put back on the clock.

    (a) The late recompute returns EXACTLY what the on-time run returned — every field,
        so a new window added on `pacific_now()` is caught without being named here.
    (b) `assemble_data` completes with every clock it could reach rigged to raise.
    """
    with monkeypatch.context() as m:
        _freeze(m, ON_TIME_NOW)
        on_time = dmc.assemble_data(TARGET, PROFILE)
    with monkeypatch.context() as m:
        _freeze(m, LATE_NOW)
        late = dmc.assemble_data(TARGET, PROFILE)

    differing = sorted(k for k in on_time[0] if on_time[0][k] != late[0].get(k))
    assert differing == [], f"window fields that moved with the wall clock on a late recompute: {differing}"
    assert late == on_time

    def _boom(*_a, **_kw):
        raise AssertionError("assemble_data read the wall clock while a target date was set (#4637)")

    class _NoClock(datetime):
        now = classmethod(_boom)
        utcnow = classmethod(_boom)
        today = classmethod(_boom)

    with monkeypatch.context() as m:
        m.setattr(dmc, "datetime", _NoClock)
        m.setattr(dmc, "pacific_now", _boom)
        m.setattr(dmc, "pacific_today", _boom)
        m.setattr(weight_trend, "pacific_now", _boom)
        assert dmc.assemble_data(TARGET, PROFILE) == on_time


def test_the_on_time_run_is_unchanged_and_a_bad_date_is_refused(table, monkeypatch):
    """The anchor IS the scheduled run's Pacific today, so the daily path does not move;
    an unparseable override raises rather than writing a row keyed on it."""
    _freeze(monkeypatch, ON_TIME_NOW)
    assert dmc.window_anchor(TARGET) == dmc.pacific_now().date() == ANCHOR
    with pytest.raises(ValueError):
        dmc.window_anchor("yesterday")
    with pytest.raises(ValueError):
        dmc.assemble_data("2026-13-40", PROFILE)


def _store(date_str):
    dmc.store_computed_metrics(
        date_str, 80, "B", {}, {}, 70, "green", {"tier0_streak": 1, "tier01_streak": 1}, 0.0, 50.0, 50.0, 0, 300.0, 301.0, 300.0
    )


def test_a_stored_row_says_how_late_it_was_computed(table, monkeypatch):
    """Box 4 (code half): `computed_lag_days` = Pacific day written - the row's date.
    1 on the scheduled run, >= 2 on a late recompute; a Decimal, as DynamoDB requires."""
    with monkeypatch.context() as m:
        _freeze(m, ON_TIME_NOW)
        _store(TARGET)
    with monkeypatch.context() as m:
        _freeze(m, LATE_NOW)
        _store(_d(-1))  # a different row, written late

    by_date = {i["date"]: i for i in table.puts if i["pk"].endswith("computed_metrics")}
    on_time, late = by_date[TARGET], by_date[_d(-1)]
    assert on_time["computed_lag_days"] == Decimal("1")
    assert late["computed_lag_days"] == Decimal(str(LATE_BY + 2))
    assert all(isinstance(r["computed_lag_days"], Decimal) for r in (on_time, late))
    assert on_time["computed_at"] and late["computed_at"]


def test_the_sick_day_row_carries_the_same_mark(table, monkeypatch):
    """The handler's second from-scratch writer (the sick-day record) is marked too, and
    the override date reaches it."""
    import health.sick_day_checker as sdc

    _freeze(monkeypatch, LATE_NOW)
    monkeypatch.setattr(sdc, "check_sick_day", lambda _t, _u, _d: {"reason": "flu"})
    dmc.lambda_handler({"date": TARGET, "force": True}, None)
    (row,) = [i for i in table.puts if i["pk"].endswith("computed_metrics")]
    assert (row["date"], row["computed_lag_days"]) == (TARGET, Decimal(str(LATE_BY + 1)))
