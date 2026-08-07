"""tests/test_anomaly_detector_lambda.py — unit tests for the anomaly detector (#1658).

Covers the parts of `lambdas/emails/anomaly_detector_lambda.py` that decide
whether Matthew gets an email at 8:05am: the adaptive CV→Z threshold ladder,
the rolling-baseline computation (including the HRV log-domain path and the
day-of-week split), the flag/no-flag boundaries in `check_anomalies`, the
sustained-streak walker, the two HTML builders, the DDB write, and the
handler's travel/sick suppression branches.

Hermetic by construction:
  - `table` and `ses` are replaced with hand-written fakes (no MagicMock —
    a non-terminating mock has OOM'd this repo's CI runner before), so no
    test can reach DynamoDB or SES.
  - every date is passed in explicitly; nothing is computed against the wall
    clock and compared to a fixture date. The two handler tests that DO let
    the module compute "yesterday" from now() assert only self-consistency
    (the written record's date == the returned body's date), never a literal.
"""

import json
import math
import os
import statistics
import sys
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "emails"))

import anomaly_detector_lambda as anomaly  # noqa: E402

UID = anomaly.USER_ID


# ══════════════════════════════════════════════════════════════════════════════
# HAND-WRITTEN FAKES
# ══════════════════════════════════════════════════════════════════════════════


class FakeTable:
    """Minimal in-memory DynamoDB Table double.

    The detector issues only string-form key conditions
    (`pk = :pk AND begins_with(sk, :prefix)` / `pk = :pk AND sk BETWEEN :s AND :e`),
    so the fake resolves queries straight off ExpressionAttributeValues. It
    honours the ADR-058 phase FilterExpression that `with_phase_filter` injects,
    which is what lets the cross-phase baseline read (#2081) be tested for real.
    """

    def __init__(self, rows=None, fail_query_pks=(), fail_get_pks=(), fail_put=False):
        self.rows = [dict(r) for r in (rows or [])]
        self.fail_query_pks = set(fail_query_pks)
        self.fail_get_pks = set(fail_get_pks)
        self.fail_put = fail_put
        self.puts = []
        self.queries = []

    def add(self, row):
        self.rows.append(dict(row))

    def query(self, **kwargs):
        self.queries.append(kwargs)
        vals = kwargs.get("ExpressionAttributeValues", {})
        pk = vals.get(":pk")
        if pk in self.fail_query_pks:
            raise RuntimeError("simulated DynamoDB query failure")
        items = [r for r in self.rows if r.get("pk") == pk]
        if ":prefix" in vals:
            items = [r for r in items if str(r.get("sk", "")).startswith(vals[":prefix"])]
        if ":s" in vals and ":e" in vals:
            items = [r for r in items if vals[":s"] <= str(r.get("sk", "")) <= vals[":e"]]
        if kwargs.get("FilterExpression") and ":phase_experiment" in vals:
            current = vals[":phase_experiment"]
            items = [r for r in items if r.get("phase") in (None, current)]
        return {"Items": [dict(r) for r in items]}

    def get_item(self, Key=None, **kwargs):
        key = Key or {}
        if key.get("pk") in self.fail_get_pks:
            raise RuntimeError("simulated DynamoDB get failure")
        for r in self.rows:
            if r.get("pk") == key.get("pk") and r.get("sk") == key.get("sk"):
                return {"Item": dict(r)}
        return {}

    def put_item(self, Item=None, **kwargs):
        if self.fail_put:
            raise RuntimeError("simulated DynamoDB put failure")
        self.puts.append(Item)


class FakeSes:
    """Records send_email calls instead of talking to SES."""

    def __init__(self):
        self.sent = []

    def send_email(self, **kwargs):
        self.sent.append(kwargs)
        return {"MessageId": "fake-message-id"}


@pytest.fixture
def ses(monkeypatch):
    fake = FakeSes()
    monkeypatch.setattr(anomaly, "ses", fake)
    return fake


def _install(monkeypatch, table):
    monkeypatch.setattr(anomaly, "table", table)
    return table


def _row(source, date_str, **fields):
    return {"pk": f"USER#{UID}#SOURCE#{source}", "sk": f"DATE#{date_str}", "date": date_str, **fields}


def _baseline_rows(source, field, end_date, values, phase=None):
    """One row per day, walking backwards from end_date - 1 day."""
    rows = []
    for offset, value in enumerate(values, start=1):
        day = (end_date - timedelta(days=offset)).isoformat()
        row = _row(source, day, **{field: value})
        if phase:
            row["phase"] = phase
        rows.append(row)
    return rows


def _flag(source="whoop", field="hrv", label="HRV", direction="low", **over):
    """A flagged-metric dict in the shape check_anomalies emits."""
    out = {
        "source": source,
        "field": field,
        "label": label,
        "yesterday_val": 40.0,
        "baseline_mean": 65.6,
        "baseline_sd": 13.6,
        "z_score": -2.39,
        "direction": direction,
        "pct_from_mean": -39.0,
        "cv": 0.22,
        "z_threshold": 2.0,
        "baseline_type": "rolling_30d",
        "sample_size": 14,
        "log_transform": False,
        "distribution_note": "gaussian_approx",
    }
    out.update(over)
    return out


# ══════════════════════════════════════════════════════════════════════════════
# ADAPTIVE THRESHOLD LADDER
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize(
    "cv,expected",
    [
        (1.0, 2.5),
        (0.30, 2.5),  # exact high-variability boundary — inclusive
        (0.2999, 2.0),  # a hair under drops to the medium bucket
        (0.15, 2.0),  # exact medium boundary
        (0.1499, 2.0),
        (0.0, 2.0),  # a perfectly stable metric still needs Z=2.0 (TB7-21)
    ],
)
def test_compute_adaptive_threshold_bucket_boundaries(cv, expected):
    assert anomaly.compute_adaptive_threshold(cv) == expected


def test_cv_threshold_table_floor_is_two_sigma():
    """TB7-21: the Z-floor is 2.0 everywhere — a 1.5 floor gave a ~42% daily FP rate."""
    assert min(z for _, z in anomaly.CV_THRESHOLDS) == 2.0


@pytest.mark.parametrize(
    "date_str,expected",
    [
        ("2026-08-01", True),  # Saturday
        ("2026-08-02", True),  # Sunday
        ("2026-08-03", False),  # Monday
        ("2026-07-31", False),  # Friday
        ("not-a-date", False),  # malformed input must not raise
        ("", False),
    ],
)
def test_is_weekend(date_str, expected):
    assert anomaly.is_weekend(date_str) is expected


# ══════════════════════════════════════════════════════════════════════════════
# ROW READS
# ══════════════════════════════════════════════════════════════════════════════


def test_fetch_date_returns_decimal_free_row(monkeypatch):
    _install(monkeypatch, FakeTable(rows=[_row("whoop", "2026-08-01", hrv=Decimal("58.5"))]))
    rec = anomaly.fetch_date("whoop", "2026-08-01")
    assert rec["hrv"] == 58.5
    assert isinstance(rec["hrv"], float)


def test_fetch_date_missing_row_is_empty_dict_and_ddb_failure_is_swallowed(monkeypatch):
    table = FakeTable(rows=[], fail_get_pks={f"USER#{UID}#SOURCE#whoop"})
    _install(monkeypatch, table)
    assert anomaly.fetch_date("garmin", "2026-08-01") == {}
    assert anomaly.fetch_date("whoop", "2026-08-01") == {}


def test_fetch_range_is_cross_phase_and_window_bounded(monkeypatch):
    """#2081: pre-genesis rows are phase=pilot; the rolling baseline must still see them."""
    rows = [
        _row("whoop", "2026-07-20", hrv=60, phase="pilot"),
        _row("whoop", "2026-07-21", hrv=61, phase="experiment"),
        _row("whoop", "2026-07-05", hrv=99),  # outside the requested window
    ]
    _install(monkeypatch, FakeTable(rows=rows))
    got = anomaly.fetch_range("whoop", "2026-07-10", "2026-07-25")
    assert sorted(r["hrv"] for r in got) == [60, 61]


def test_fetch_range_query_failure_returns_empty_list(monkeypatch):
    _install(monkeypatch, FakeTable(rows=[], fail_query_pks={f"USER#{UID}#SOURCE#whoop"}))
    assert anomaly.fetch_range("whoop", "2026-07-10", "2026-07-25") == []


def test_check_travel_matches_open_ended_and_past_trips(monkeypatch):
    trips = [
        {"pk": anomaly.TRAVEL_PK, "sk": "TRIP#2026-06", "start_date": "2026-06-01", "end_date": "2026-06-10", "destination_city": "Reno"},
        {"pk": anomaly.TRAVEL_PK, "sk": "TRIP#2026-07", "start_date": "2026-07-04", "destination_city": "Lisbon"},  # no end_date
    ]
    _install(monkeypatch, FakeTable(rows=trips))
    assert anomaly._check_travel("2026-06-05")["destination_city"] == "Reno"
    assert anomaly._check_travel("2026-06-10")["destination_city"] == "Reno"  # inclusive end
    assert anomaly._check_travel("2026-06-11") is None
    assert anomaly._check_travel("2030-01-01")["destination_city"] == "Lisbon"  # open-ended trip


def test_check_travel_swallows_query_failure(monkeypatch):
    _install(monkeypatch, FakeTable(rows=[], fail_query_pks={anomaly.TRAVEL_PK}))
    assert anomaly._check_travel("2026-06-05") is None


# ══════════════════════════════════════════════════════════════════════════════
# BASELINE COMPUTATION
# ══════════════════════════════════════════════════════════════════════════════


def test_compute_baseline_requires_min_baseline_days(monkeypatch):
    end = date(2026, 8, 2)
    six = _baseline_rows("whoop", "recovery_score", end, [60, 61, 62, 63, 64, 65])
    _install(monkeypatch, FakeTable(rows=six))
    mean, sd, cv, z, n, kind = anomaly.compute_baseline("whoop", "recovery_score", end)
    assert (mean, sd, cv, z) == (None, None, None, None)
    assert n == 6 < anomaly.MIN_BASELINE_DAYS
    assert kind == "rolling_30d"

    _install(monkeypatch, FakeTable(rows=six + _baseline_rows("whoop", "recovery_score", end - timedelta(days=6), [66])))
    mean, sd, cv, z, n, kind = anomaly.compute_baseline("whoop", "recovery_score", end)
    assert n == anomaly.MIN_BASELINE_DAYS == 7
    assert mean == pytest.approx(63.0)
    assert z == 2.0


def test_compute_baseline_ignores_rows_missing_the_field(monkeypatch):
    end = date(2026, 8, 2)
    rows = _baseline_rows("whoop", "recovery_score", end, [50, 50, 50, 50, 50, 50, 50])
    rows += [_row("whoop", (end - timedelta(days=20)).isoformat(), other_field=9999)]
    _install(monkeypatch, FakeTable(rows=rows))
    mean, sd, cv, z, n, _kind = anomaly.compute_baseline("whoop", "recovery_score", end)
    assert n == 7
    assert mean == 50.0
    assert sd == 0
    assert cv == 0


def test_compute_baseline_dow_split_uses_only_matching_day_type(monkeypatch):
    """Weekend steps must not be scored against a weekday baseline (v2.0.0)."""
    end = date(2026, 8, 1)  # Saturday
    rows = []
    for offset in range(1, 31):
        day = end - timedelta(days=offset)
        value = (4000 if day.weekday() >= 5 else 12000) + 100 * ((day.day % 5) - 2)
        rows.append(_row("apple_health", day.isoformat(), steps=value))
    _install(monkeypatch, FakeTable(rows=rows))

    w_mean, _sd, _cv, _z, w_n, w_kind = anomaly.compute_baseline("apple_health", "steps", end, dow_normalize=True, target_is_weekend=True)
    assert (w_n, w_kind) == (8, "weekend")
    assert 3800 <= w_mean <= 4200

    d_mean, _sd, _cv, _z, d_n, d_kind = anomaly.compute_baseline("apple_health", "steps", end, dow_normalize=True, target_is_weekend=False)
    assert (d_n, d_kind) == (22, "weekday")
    assert 11800 <= d_mean <= 12200


def test_compute_baseline_log_transform_returns_log_domain_moments(monkeypatch):
    end = date(2026, 8, 2)
    values = [50, 52, 54, 56, 58, 60, 62, 64, 66, 70, 75, 80, 90, 100]
    _install(monkeypatch, FakeTable(rows=_baseline_rows("whoop", "hrv", end, values)))

    mean, sd, cv, z, n, _kind = anomaly.compute_baseline("whoop", "hrv", end, log_transform=True)
    logs = [math.log(v) for v in values]
    assert n == 14
    assert mean == pytest.approx(statistics.mean(logs))
    assert sd == pytest.approx(statistics.stdev(logs))
    # CV stays in the ORIGINAL domain so the adaptive ladder is comparable across metrics
    assert cv == pytest.approx(statistics.stdev(values) / statistics.mean(values))
    assert z == 2.0
    # geometric mean sits below the arithmetic mean on this right-skewed series
    assert math.exp(mean) < statistics.mean(values)


def test_compute_baseline_log_transform_rejects_nonpositive_values(monkeypatch):
    """A zero/negative HRV reading can't be logged — the guard must return no baseline."""
    end = date(2026, 8, 2)
    values = [60, 62, 0, -1, 64, 66, 0, 68]  # 8 rows clear the first guard, only 5 are loggable
    _install(monkeypatch, FakeTable(rows=_baseline_rows("whoop", "hrv", end, values)))
    mean, sd, cv, z, n, _kind = anomaly.compute_baseline("whoop", "hrv", end, log_transform=True)
    assert (mean, sd, cv, z) == (None, None, None, None)
    assert n == 5  # the reported count is the loggable subset, not the raw row count


# ══════════════════════════════════════════════════════════════════════════════
# check_anomalies — the flag / no-flag decision
# ══════════════════════════════════════════════════════════════════════════════

YESTERDAY = "2026-08-02"
YESTERDAY_DATE = date(2026, 8, 2)


def _run_check(monkeypatch, rows, yesterday=YESTERDAY):
    _install(monkeypatch, FakeTable(rows=rows))
    return anomaly.check_anomalies(yesterday, date.fromisoformat(yesterday) + timedelta(days=1))


@pytest.mark.parametrize(
    "observed,should_flag",
    [
        (56.0, True),  # Z = +2.89, over the 2.0 threshold
        (53.9, False),  # Z = +1.88, under it (abs change 3.9 clears the ±3 filter)
    ],
)
def test_check_anomalies_rhr_flags_only_above_z_threshold(monkeypatch, observed, should_flag):
    rows = _baseline_rows("whoop", "resting_heart_rate", YESTERDAY_DATE, [48] * 7 + [52] * 7)
    rows.append(_row("whoop", YESTERDAY, resting_heart_rate=observed))
    flagged = _run_check(monkeypatch, rows)
    fields = [f["field"] for f in flagged]
    if should_flag:
        assert fields == ["resting_heart_rate"]
        hit = flagged[0]
        assert hit["direction"] == "high"
        assert hit["z_score"] == pytest.approx((observed - 50) / statistics.stdev([48] * 7 + [52] * 7), abs=0.01)
        assert hit["z_threshold"] == 2.0
        assert hit["baseline_mean"] == 50.0
        assert hit["sample_size"] == 14
        assert hit["distribution_note"] == "gaussian_approx"
    else:
        assert fields == []


def test_check_anomalies_respects_direction_low_is_bad_false(monkeypatch):
    """RHR is only interesting when HIGH — a dramatically LOW reading is not an alert."""
    rows = _baseline_rows("whoop", "resting_heart_rate", YESTERDAY_DATE, [48] * 7 + [52] * 7)
    rows.append(_row("whoop", YESTERDAY, resting_heart_rate=42.0))  # Z = -3.85
    assert _run_check(monkeypatch, rows) == []


def test_check_anomalies_respects_direction_low_is_bad_true(monkeypatch):
    """Recovery score is only interesting when LOW."""
    baseline = [55] * 7 + [65] * 7
    sd = statistics.stdev(baseline)
    low_rows = _baseline_rows("whoop", "recovery_score", YESTERDAY_DATE, baseline)
    low_rows.append(_row("whoop", YESTERDAY, recovery_score=60 - 3 * sd))
    assert [f["direction"] for f in _run_check(monkeypatch, low_rows)] == ["low"]

    high_rows = _baseline_rows("whoop", "recovery_score", YESTERDAY_DATE, baseline)
    high_rows.append(_row("whoop", YESTERDAY, recovery_score=60 + 3 * sd))
    assert _run_check(monkeypatch, high_rows) == []


@pytest.mark.parametrize("observed,direction", [(205.0, "high"), (195.0, "low")])
def test_check_anomalies_two_sided_metric_flags_both_directions(monkeypatch, observed, direction):
    """Weight has low_is_bad=None — either tail is worth flagging."""
    rows = _baseline_rows("withings", "weight_lbs", YESTERDAY_DATE, [198] * 7 + [202] * 7)
    rows.append(_row("withings", YESTERDAY, weight_lbs=observed))
    flagged = _run_check(monkeypatch, rows)
    assert [(f["field"], f["direction"]) for f in flagged] == [("weight_lbs", direction)]
    assert flagged[0]["pct_from_mean"] == round((observed - 200) / 200 * 100, 1)


@pytest.mark.parametrize(
    "observed,should_flag",
    [
        (201.4, False),  # 1.4 lbs — under the 1.5 lb floor despite Z = 13.5
        (201.6, True),  # 1.6 lbs — clears it
    ],
)
def test_check_anomalies_minimum_absolute_change_filter(monkeypatch, observed, should_flag):
    """A very tight baseline makes tiny drifts statistically huge; the abs-change floor is what stops the noise."""
    rows = _baseline_rows("withings", "weight_lbs", YESTERDAY_DATE, [199.9] * 7 + [200.1] * 7)
    rows.append(_row("withings", YESTERDAY, weight_lbs=observed))
    flagged = _run_check(monkeypatch, rows)
    assert bool(flagged) is should_flag
    assert anomaly.MIN_ABSOLUTE_CHANGE["weight_lbs"] == 1.5


def test_check_anomalies_skips_zero_variance_baseline(monkeypatch):
    """SD=0 would make every Z infinite — the guard must skip the metric entirely."""
    rows = _baseline_rows("whoop", "recovery_score", YESTERDAY_DATE, [60] * 14)
    rows.append(_row("whoop", YESTERDAY, recovery_score=5.0))
    assert _run_check(monkeypatch, rows) == []


def test_check_anomalies_skips_metric_without_enough_baseline(monkeypatch):
    rows = _baseline_rows("whoop", "recovery_score", YESTERDAY_DATE, [40, 60, 45, 65, 50, 70])  # 6 < 7
    rows.append(_row("whoop", YESTERDAY, recovery_score=5.0))
    assert _run_check(monkeypatch, rows) == []


def test_check_anomalies_skips_metric_absent_from_yesterday(monkeypatch):
    rows = _baseline_rows("whoop", "recovery_score", YESTERDAY_DATE, [40, 60, 45, 65, 50, 70, 55, 62])
    rows.append(_row("whoop", YESTERDAY, some_other_field=1))
    assert _run_check(monkeypatch, rows) == []


def test_check_anomalies_hrv_uses_log_domain_z(monkeypatch):
    """v2.4.0: on a right-skewed HRV series the raw Z understates a low reading.

    40ms against this baseline is Z=-1.83 in raw units (no alert) but Z=-2.39
    in the log domain (alert). The log transform is what makes it visible.
    """
    values = [50, 52, 54, 56, 58, 60, 62, 64, 66, 70, 75, 80, 90, 100]
    rows = _baseline_rows("whoop", "hrv", YESTERDAY_DATE, values)
    rows.append(_row("whoop", YESTERDAY, hrv=40.0))
    flagged = _run_check(monkeypatch, rows)

    raw_z = (40 - statistics.mean(values)) / statistics.stdev(values)
    assert abs(raw_z) < 2.0, "premise: the raw-domain Z does NOT clear the threshold"

    assert len(flagged) == 1
    hit = flagged[0]
    assert hit["field"] == "hrv"
    assert hit["direction"] == "low"
    assert hit["log_transform"] is True
    assert hit["distribution_note"] == "lognormal_z"
    assert hit["z_score"] <= -2.0
    assert hit["z_score"] == pytest.approx(-2.39, abs=0.01)
    # display values stay in original units: geometric mean, delta-method SD
    assert hit["yesterday_val"] == 40.0
    assert hit["baseline_mean"] == pytest.approx(65.6, abs=0.05)
    assert hit["baseline_sd"] == pytest.approx(13.6, abs=0.05)


def test_check_anomalies_day_of_week_normalization_changes_the_verdict(monkeypatch):
    """The SAME 4,200-step day is normal on a Saturday and anomalous on a Friday."""

    def _rows_for(anchor):
        rows = []
        for offset in range(1, 31):
            day = anchor - timedelta(days=offset)
            value = (4000 if day.weekday() >= 5 else 12000) + 100 * ((day.day % 5) - 2)
            rows.append(_row("apple_health", day.isoformat(), steps=value))
        rows.append(_row("apple_health", anchor.isoformat(), steps=4200))
        return rows

    saturday = date(2026, 8, 1)
    assert _run_check(monkeypatch, _rows_for(saturday), saturday.isoformat()) == []

    friday = date(2026, 7, 31)
    weekday_flags = _run_check(monkeypatch, _rows_for(friday), friday.isoformat())
    assert [f["field"] for f in weekday_flags] == ["steps"]
    assert weekday_flags[0]["baseline_type"] == "weekday"
    assert weekday_flags[0]["sample_size"] == 22
    assert weekday_flags[0]["direction"] == "low"


def test_check_anomalies_dow_baseline_skips_rows_missing_the_field(monkeypatch):
    """A weekday row with no `steps` key must not poison the weekday sample count."""
    anchor = date(2026, 7, 31)  # Friday
    rows = []
    for offset in range(1, 31):
        day = anchor - timedelta(days=offset)
        if day.weekday() < 5 and offset % 3 == 0:
            rows.append(_row("apple_health", day.isoformat(), other=1))  # no steps field
        else:
            rows.append(_row("apple_health", day.isoformat(), steps=12000 + 100 * ((day.day % 5) - 2)))
    _install(monkeypatch, FakeTable(rows=rows))
    _mean, _sd, _cv, _z, n, kind = anomaly.compute_baseline("apple_health", "steps", anchor, dow_normalize=True, target_is_weekend=False)
    assert kind == "weekday"
    assert n == 15  # 22 weekday rows minus the 7 that carry no steps value


def test_check_anomalies_collects_flags_across_sources(monkeypatch):
    rows = _baseline_rows("whoop", "resting_heart_rate", YESTERDAY_DATE, [48] * 7 + [52] * 7)
    rows.append(_row("whoop", YESTERDAY, resting_heart_rate=56.0))
    rows += _baseline_rows("withings", "weight_lbs", YESTERDAY_DATE, [198] * 7 + [202] * 7)
    rows.append(_row("withings", YESTERDAY, weight_lbs=205.0))
    flagged = _run_check(monkeypatch, rows)
    assert sorted(f["source"] for f in flagged) == ["whoop", "withings"]
    assert anomaly.is_multi_source(flagged) is True


@pytest.mark.parametrize(
    "flagged,expected",
    [
        ([], False),
        ([_flag(source="whoop")], False),
        ([_flag(source="whoop", field="hrv"), _flag(source="whoop", field="resting_heart_rate")], False),
        ([_flag(source="whoop"), _flag(source="withings", field="weight_lbs")], True),
    ],
)
def test_is_multi_source(flagged, expected):
    assert anomaly.is_multi_source(flagged) is expected


# ══════════════════════════════════════════════════════════════════════════════
# SUSTAINED STREAKS
# ══════════════════════════════════════════════════════════════════════════════

ANOM_PK = f"USER#{UID}#SOURCE#anomalies"


def _history_row(date_str, metrics, **over):
    row = {"pk": ANOM_PK, "sk": f"DATE#{date_str}", "date": date_str, "anomalous_metrics": metrics}
    row.update(over)
    return row


def _hist_metric(field="hrv", direction="low", label="HRV", source="whoop"):
    return {"field": field, "direction": direction, "label": label, "source": source}


def test_sustained_streak_fires_at_three_consecutive_days(monkeypatch):
    rows = [
        _history_row("2026-08-01", [_hist_metric()]),
        _history_row("2026-07-31", [_hist_metric()]),
    ]
    _install(monkeypatch, FakeTable(rows=rows))
    sustained = anomaly._check_sustained_streaks("2026-08-02", [_flag()])
    assert len(sustained) == 1
    assert sustained[0] == {
        "metric": "hrv",
        "label": "HRV",
        "source": "whoop",
        "direction": "low",
        "streak_days": 3,
        "severity": "sustained_single_source",
        "training_context": None,
    }


def test_sustained_streak_of_two_days_is_not_yet_sustained(monkeypatch):
    _install(monkeypatch, FakeTable(rows=[_history_row("2026-08-01", [_hist_metric()])]))
    assert anomaly._check_sustained_streaks("2026-08-02", [_flag()]) == []


def test_sustained_streak_requires_today_to_be_flagged(monkeypatch):
    """A metric flagged for days but clean today has ended its streak."""
    rows = [_history_row(d, [_hist_metric()]) for d in ("2026-08-01", "2026-07-31", "2026-07-30")]
    _install(monkeypatch, FakeTable(rows=rows))
    assert anomaly._check_sustained_streaks("2026-08-02", []) == []


def test_sustained_streak_requires_the_same_direction(monkeypatch):
    rows = [
        _history_row("2026-08-01", [_hist_metric(direction="high")]),
        _history_row("2026-07-31", [_hist_metric(direction="high")]),
    ]
    _install(monkeypatch, FakeTable(rows=rows))
    assert anomaly._check_sustained_streaks("2026-08-02", [_flag(direction="low")]) == []


@pytest.mark.parametrize("breaker", ["sick_mode", "travel_mode"])
def test_sick_or_travel_day_breaks_the_streak(monkeypatch, breaker):
    rows = [
        _history_row("2026-08-01", [_hist_metric()], **{breaker: True}),
        _history_row("2026-07-31", [_hist_metric()]),
        _history_row("2026-07-30", [_hist_metric()]),
    ]
    _install(monkeypatch, FakeTable(rows=rows))
    assert anomaly._check_sustained_streaks("2026-08-02", [_flag()]) == []


def test_missing_history_record_breaks_the_streak(monkeypatch):
    rows = [
        _history_row("2026-08-01", [_hist_metric()]),
        # 2026-07-31 deliberately absent
        _history_row("2026-07-30", [_hist_metric()]),
        _history_row("2026-07-29", [_hist_metric()]),
    ]
    _install(monkeypatch, FakeTable(rows=rows))
    assert anomaly._check_sustained_streaks("2026-08-02", [_flag()]) == []


def test_sustained_streaks_returns_empty_when_history_read_fails(monkeypatch):
    """Jin's rule: a streak-read failure must never silence the primary alert."""
    _install(monkeypatch, FakeTable(rows=[], fail_query_pks={ANOM_PK}))
    assert anomaly._check_sustained_streaks("2026-08-02", [_flag()]) == []


def test_sustained_streaks_with_no_history_at_all(monkeypatch):
    _install(monkeypatch, FakeTable(rows=[]))
    assert anomaly._check_sustained_streaks("2026-08-02", [_flag()]) == []


@pytest.mark.parametrize(
    "atl,ctl,recovery,expected_fragment",
    [
        (90, 60, 45, "acute overreaching"),  # load up, recovery down
        (90, 60, 70, "normal adaptation"),  # load up, recovery holding
        (90, 60, 62, None),  # in the 60–65 dead band: no covariate claim
        (40, 60, 45, None),  # not under acute load at all
    ],
)
def test_training_load_covariate_on_hrv_streaks(monkeypatch, atl, ctl, recovery, expected_fragment):
    rows = [
        _history_row("2026-08-01", [_hist_metric()]),
        _history_row("2026-07-31", [_hist_metric()]),
        {
            "pk": f"USER#{UID}#SOURCE#computed_metrics",
            "sk": "DATE#2026-08-02",
            "atl": atl,
            "ctl": ctl,
            "recovery_score": recovery,
        },
    ]
    _install(monkeypatch, FakeTable(rows=rows))
    sustained = anomaly._check_sustained_streaks("2026-08-02", [_flag()])
    assert len(sustained) == 1
    context = sustained[0]["training_context"]
    if expected_fragment is None:
        assert context is None
    else:
        assert expected_fragment in context
        assert f"ATL ({atl})" in context and f"CTL ({ctl})" in context


def test_training_covariate_failure_leaves_the_streak_intact(monkeypatch):
    """A failed computed_metrics read must cost the context line, not the streak."""
    rows = [_history_row("2026-08-01", [_hist_metric()]), _history_row("2026-07-31", [_hist_metric()])]
    _install(monkeypatch, FakeTable(rows=rows, fail_get_pks={f"USER#{UID}#SOURCE#computed_metrics"}))
    sustained = anomaly._check_sustained_streaks("2026-08-02", [_flag()])
    assert [(s["metric"], s["streak_days"]) for s in sustained] == [("hrv", 3)]
    assert sustained[0]["training_context"] is None


def test_training_covariate_only_applies_to_hrv_and_rhr(monkeypatch):
    rows = [
        _history_row("2026-08-01", [_hist_metric(field="recovery_score", label="Recovery Score")]),
        _history_row("2026-07-31", [_hist_metric(field="recovery_score", label="Recovery Score")]),
        {"pk": f"USER#{UID}#SOURCE#computed_metrics", "sk": "DATE#2026-08-02", "atl": 90, "ctl": 60, "recovery_score": 40},
    ]
    _install(monkeypatch, FakeTable(rows=rows))
    sustained = anomaly._check_sustained_streaks("2026-08-02", [_flag(field="recovery_score", label="Recovery Score")])
    assert sustained[0]["training_context"] is None


def test_sustained_streaks_ignores_history_entries_with_no_field_or_direction(monkeypatch):
    """A malformed historical metric must be skipped, not counted as its own streak."""
    rows = [
        _history_row("2026-08-01", [{"label": "mystery"}, _hist_metric()]),
        _history_row("2026-07-31", [{"direction": "low"}, _hist_metric()]),
    ]
    _install(monkeypatch, FakeTable(rows=rows))
    sustained = anomaly._check_sustained_streaks("2026-08-02", [_flag()])
    assert [s["metric"] for s in sustained] == ["hrv"]


def test_sleep_metric_deduplication_keeps_efficiency(monkeypatch):
    """Park's rule: when several sleep metrics streak together only the most clinically
    meaningful one (sleep_efficiency_percentage) survives.

    #2179: uses the REAL field name METRICS emits (sleep_quality_score) — the dedup
    set used to name "sleep_score"/"sleep_performance" instead, fields METRICS never
    produces, so this rule could never actually fire in production even though a
    test exercising the mechanism directly (with the wrong field name) stayed green.
    """
    metrics = [
        _hist_metric(field="sleep_efficiency_percentage", label="Sleep Efficiency"),
        _hist_metric(field="sleep_quality_score", label="Sleep Score"),
    ]
    rows = [_history_row("2026-08-01", metrics), _history_row("2026-07-31", metrics)]
    _install(monkeypatch, FakeTable(rows=rows))
    today = [
        _flag(field="sleep_efficiency_percentage", label="Sleep Efficiency"),
        _flag(field="sleep_quality_score", label="Sleep Score"),
    ]
    sustained = anomaly._check_sustained_streaks("2026-08-02", today)
    assert [s["metric"] for s in sustained] == ["sleep_efficiency_percentage"]


def test_sleep_dedup_field_set_names_only_real_metrics_fields():
    """Guard the SET, not one call site: every field named in the sleep dedup set
    must be a field METRICS actually emits, or the dedup silently goes inert again."""
    real_fields = {field for (_source, field, _label, _low_is_bad) in anomaly.METRICS}
    assert anomaly.SLEEP_DEDUP_FIELDS <= real_fields
    assert anomaly.SLEEP_DEDUP_FIELDS == {"sleep_efficiency_percentage", "sleep_quality_score"}


# ══════════════════════════════════════════════════════════════════════════════
# HAIKU HYPOTHESIS (no network — the retry helper is replaced)
# ══════════════════════════════════════════════════════════════════════════════


def test_call_haiku_hypothesis_builds_prompt_and_strips_response(monkeypatch):
    captured = {}

    def _fake_raw(req, timeout=30):
        captured["req"] = req
        captured["timeout"] = timeout
        return {"content": [{"text": "  HRV fell after a hard session.  "}]}

    import common.retry_utils as retry_utils

    monkeypatch.setattr(retry_utils, "call_anthropic_raw", _fake_raw)

    out = anomaly.call_haiku_hypothesis([_flag()], {"date": "2026-08-02", "whoop": {"hrv": 40}})
    assert out == "HRV fell after a hard session."
    assert captured["timeout"] == 25

    req = captured["req"]
    assert req.full_url == "https://api.anthropic.com/v1/messages"
    assert req.get_method() == "POST"
    payload = json.loads(req.data)
    assert payload["model"] == anomaly.AI_MODEL_HAIKU
    assert payload["max_tokens"] == 250
    prompt = payload["messages"][0]["content"]
    assert '"field": "hrv"' in prompt  # the flagged metrics are inlined
    assert '"date": "2026-08-02"' in prompt  # so is the context
    assert "Max 80 words total" in prompt


# ══════════════════════════════════════════════════════════════════════════════
# HTML BUILDERS
# ══════════════════════════════════════════════════════════════════════════════


def test_build_sustained_alert_html_renders_each_streak():
    sustained = [
        {"label": "HRV", "direction": "low", "streak_days": 4, "training_context": None},
        {"label": "Resting Heart Rate", "direction": "high", "streak_days": 3, "training_context": "Load is up."},
    ]
    html = anomaly.build_sustained_alert_html(sustained, "2026-08-02")
    assert "Trend Alert" in html
    assert "Sunday, Aug 2" in html
    assert "2 metrics flagged" in html  # plural
    assert "HRV" in html and "Resting Heart Rate" in html
    assert "<strong>4 consecutive days</strong>" in html
    assert "<strong>3 consecutive days</strong>" in html
    assert "(below baseline)" in html and "(above baseline)" in html
    assert "Load is up." in html
    assert "Before adjusting anything" in html  # Rodriguez's mandatory behavioral frame
    assert "WARNING" not in html


def test_build_sustained_alert_html_singular_and_bad_date():
    html = anomaly.build_sustained_alert_html([{"label": "HRV", "direction": "low", "streak_days": 3}], "garbage")
    assert "1 metric flagged" in html
    assert "garbage" in html  # unparseable date falls back to the raw string


def test_build_alert_html_severity_escalates_at_four_metrics():
    two = [_flag(source="whoop", field="hrv"), _flag(source="withings", field="weight_lbs", label="Weight")]
    four = two + [
        _flag(source="garmin", field="avg_stress", label="Garmin Stress", direction="high"),
        _flag(source="todoist", field="tasks_completed", label="Tasks Completed"),
    ]
    moderate = anomaly.build_alert_html(two, "hypo", "2026-08-02")
    high = anomaly.build_alert_html(four, "hypo", "2026-08-02")

    assert "MODERATE" in moderate and "#d97706" in moderate
    assert "2 metrics flagged across 2 sources" in moderate
    assert "HIGH" in high and "#dc2626" in high
    assert "4 metrics flagged across 4 sources" in high


def test_build_alert_html_renders_metric_rows_and_hypothesis():
    flagged = [
        _flag(label="HRV", direction="low", yesterday_val=40.0, baseline_mean=65.6, baseline_sd=13.6, z_score=-2.39, pct_from_mean=-39.0),
        _flag(
            source="apple_health",
            field="steps",
            label="Steps",
            direction="high",
            yesterday_val=18000.0,
            pct_from_mean=42.5,
            baseline_type="weekend",
        ),
    ]
    html = anomaly.build_alert_html(flagged, "You slept badly after a hard session.", "2026-08-02")
    assert "You slept badly after a hard session." in html
    assert "Sunday, Aug 2" in html
    assert "1 metric flagged" not in html
    assert "\U0001f4c9 HRV" in html  # down chart for a low reading
    assert "\U0001f4c8 Steps" in html  # up chart for a high reading
    assert "-39.0% vs baseline" in html
    assert "+42.5% vs baseline" in html
    assert "Z = -2.39 (threshold: 2.0)" in html
    assert "(baseline: 65.6 +/- 13.6)" in html
    assert "weekend baseline" in html  # non-default baseline is disclosed
    assert "not medical advice" in html


def test_build_alert_html_singular_metric_and_unparseable_date():
    html = anomaly.build_alert_html([_flag()], "hypo", "n/a")
    assert "1 metric flagged across 1 sources" in html
    assert ">n/a</h1>" in html


# ══════════════════════════════════════════════════════════════════════════════
# EMAIL SEND (SES faked — no test may reach the real client)
# ══════════════════════════════════════════════════════════════════════════════


def test_send_alert_email_subject_and_body(ses):
    flagged = [_flag(source="whoop"), _flag(source="withings", field="weight_lbs", label="Weight")]
    anomaly.send_alert_email(flagged, "Hypothesis text.", "2026-08-02")
    assert len(ses.sent) == 1
    call = ses.sent[0]
    assert call["FromEmailAddress"] == anomaly.SENDER
    assert call["Destination"]["ToAddresses"] == [anomaly.RECIPIENT]
    subject = call["Content"]["Simple"]["Subject"]["Data"]
    assert "Sun Aug 2" in subject
    assert "2 metrics flagged (whoop, withings)" in subject
    assert "Hypothesis text." in call["Content"]["Simple"]["Body"]["Html"]["Data"]


def test_send_alert_email_falls_back_to_raw_date_in_subject(ses):
    anomaly.send_alert_email([_flag()], "h", "bad-date")
    assert "bad-date" in ses.sent[0]["Content"]["Simple"]["Subject"]["Data"]


def test_send_sustained_alert_email_summarizes_at_most_three_metrics(ses):
    sustained = [
        {"label": "HRV", "direction": "low", "streak_days": 5},
        {"label": "RHR", "direction": "high", "streak_days": 4},
        {"label": "Sleep Efficiency", "direction": "low", "streak_days": 3},
        {"label": "Steps", "direction": "low", "streak_days": 3},
    ]
    anomaly.send_sustained_alert_email(sustained, "2026-08-02")
    subject = ses.sent[0]["Content"]["Simple"]["Subject"]["Data"]
    assert subject.startswith("Trend Alert — HRV, RHR, Sleep Efficiency +1 more")
    assert "5 consecutive days" in subject
    assert "Steps" not in subject


# ══════════════════════════════════════════════════════════════════════════════
# DYNAMODB WRITE
# ══════════════════════════════════════════════════════════════════════════════


def test_write_anomaly_record_shape_ttl_and_decimals(monkeypatch):
    table = _install(monkeypatch, FakeTable())
    flagged = [_flag(source="whoop"), _flag(source="withings", field="weight_lbs", label="Weight")]
    anomaly.write_anomaly_record("2026-08-02", flagged, True, "Hypothesis.", "high")

    item = table.puts[0]
    assert item["pk"] == ANOM_PK
    assert item["sk"] == "DATE#2026-08-02"
    assert item["date"] == "2026-08-02"
    assert item["source_count"] == 2
    assert item["alert_sent"] is True
    assert item["severity"] == "high"
    # #2179: single source of truth — was hardcoded "2.5.0" here vs "2.3.0" in the
    # HTTP response body (see test_lambda_handler_response_body_detector_version_matches_ddb).
    assert item["detector_version"] == anomaly.DETECTOR_VERSION
    assert item["travel_mode"] is False and item["sick_mode"] is False
    # 90-day investigative TTL, measured from the record's own date (R17-17):
    # 2026-08-02 + 90 days == 2026-10-31 00:00 UTC
    assert item["ttl"] == int(datetime(2026, 10, 31, tzinfo=timezone.utc).timestamp())
    # every float survived the Decimal round-trip
    assert isinstance(item["anomalous_metrics"][0]["z_score"], Decimal)
    assert float(item["anomalous_metrics"][0]["z_score"]) == -2.39
    # additive fields stay absent when there is nothing to add
    assert "sustained_metrics" not in item
    assert "sustained_alert_sent" not in item


def test_write_anomaly_record_ttl_is_ninety_days_after_the_record_date(monkeypatch):
    table = _install(monkeypatch, FakeTable())
    anomaly.write_anomaly_record("2026-08-02", [], False, "", "none")
    anomaly.write_anomaly_record("2026-08-03", [], False, "", "none")
    assert table.puts[1]["ttl"] - table.puts[0]["ttl"] == 86400
    assert table.puts[0]["source_count"] == 0


def test_write_anomaly_record_carries_suppression_and_sustained_fields(monkeypatch):
    table = _install(monkeypatch, FakeTable())
    sustained = [{"metric": "hrv", "label": "HRV", "streak_days": 4, "direction": "low"}]
    anomaly.write_anomaly_record(
        "2026-08-02",
        [_flag()],
        False,
        "[TRAVEL] suppressed",
        "travel_suppressed",
        travel_mode=True,
        travel_dest="Lisbon",
        sick_mode=True,
        sick_reason="flu",
        sustained_metrics=sustained,
        sustained_alert_sent=True,
    )
    item = table.puts[0]
    assert item["travel_mode"] is True and item["travel_destination"] == "Lisbon"
    assert item["sick_mode"] is True and item["sick_reason"] == "flu"
    assert item["sustained_metrics"][0]["label"] == "HRV"
    assert item["sustained_alert_sent"] is True


def test_record_email_send_writes_status_row(monkeypatch):
    table = FakeTable()
    anomaly.record_email_send(table, "anomaly_detector")
    item = table.puts[0]
    assert item["pk"] == "USER#matthew#SOURCE#email_log#anomaly_detector"
    assert item["sk"].startswith("DATE#")
    assert item["status"] == "success"
    assert item["ttl"] > 0


def test_record_email_send_failure_is_non_fatal():
    anomaly.record_email_send(FakeTable(fail_put=True), "anomaly_detector")  # must not raise


# ══════════════════════════════════════════════════════════════════════════════
# HANDLER
# ══════════════════════════════════════════════════════════════════════════════


def test_handler_healthcheck_short_circuits(monkeypatch):
    _install(monkeypatch, FakeTable(fail_query_pks={ANOM_PK}))
    assert anomaly.lambda_handler({"healthcheck": True}, None) == {"statusCode": 200, "body": "ok"}


def _body(resp):
    return json.loads(resp["body"])


def test_handler_multi_source_sends_alert_and_writes_record(monkeypatch, ses):
    table = _install(monkeypatch, FakeTable())
    flagged = [
        _flag(source="whoop"),
        _flag(source="withings", field="weight_lbs", label="Weight"),
        _flag(source="garmin", field="avg_stress", label="Garmin Stress", direction="high"),
        _flag(source="todoist", field="tasks_completed", label="Tasks Completed"),
    ]
    monkeypatch.setattr(anomaly, "check_anomalies", lambda *_a, **_k: list(flagged))
    monkeypatch.setattr(anomaly, "call_haiku_hypothesis", lambda f, c: "HRV fell after a hard session.")

    body = _body(anomaly.lambda_handler({}, None))
    assert body["flagged_count"] == 4
    assert body["multi_source"] is True
    assert body["severity"] == "high"  # >= 4 metrics
    assert body["alert_sent"] is True
    assert body["travel_mode"] is False

    assert len(ses.sent) == 1
    assert "HRV fell after a hard session." in ses.sent[0]["Content"]["Simple"]["Body"]["Html"]["Data"]

    record = next(p for p in table.puts if p["pk"] == ANOM_PK)
    assert record["date"] == body["date"]  # handler-computed date is used consistently
    assert record["severity"] == "high"
    assert record["alert_sent"] is True
    assert any(p["pk"].endswith("email_log#anomaly_detector") for p in table.puts)


def test_lambda_handler_response_body_detector_version_matches_ddb_write(monkeypatch, ses):
    """#2179: detector_version drifted — the DDB record said "2.5.0" but the HTTP
    response body said "2.3.0" (a version bump that only updated one call site).
    Both must now read the same module constant."""
    table = _install(monkeypatch, FakeTable())
    monkeypatch.setattr(anomaly, "check_anomalies", lambda *_a, **_k: [_flag(source="whoop")])

    body = _body(anomaly.lambda_handler({}, None))

    assert body["detector_version"] == anomaly.DETECTOR_VERSION
    record = next(p for p in table.puts if p["pk"] == ANOM_PK)
    assert record["detector_version"] == anomaly.DETECTOR_VERSION
    assert body["detector_version"] == record["detector_version"]


def test_handler_moderate_severity_under_four_metrics(monkeypatch, ses):
    _install(monkeypatch, FakeTable())
    monkeypatch.setattr(
        anomaly,
        "check_anomalies",
        lambda *_a, **_k: [_flag(source="whoop"), _flag(source="withings", field="weight_lbs", label="Weight")],
    )
    monkeypatch.setattr(anomaly, "call_haiku_hypothesis", lambda f, c: "Two systems moved together.")
    assert _body(anomaly.lambda_handler({}, None))["severity"] == "moderate"


def test_handler_falls_back_when_hypothesis_call_fails(monkeypatch, ses):
    _install(monkeypatch, FakeTable())
    monkeypatch.setattr(
        anomaly,
        "check_anomalies",
        lambda *_a, **_k: [_flag(source="whoop"), _flag(source="withings", field="weight_lbs", label="Weight")],
    )

    def _boom(_flagged, _context):
        raise RuntimeError("bedrock unavailable")

    monkeypatch.setattr(anomaly, "call_haiku_hypothesis", _boom)
    body = _body(anomaly.lambda_handler({}, None))
    assert body["alert_sent"] is True  # the alert still goes out without an AI hypothesis
    assert "check your daily brief" in ses.sent[0]["Content"]["Simple"]["Body"]["Html"]["Data"]


def test_handler_single_source_sends_nothing(monkeypatch, ses):
    table = _install(monkeypatch, FakeTable())
    monkeypatch.setattr(anomaly, "check_anomalies", lambda *_a, **_k: [_flag(source="whoop")])
    body = _body(anomaly.lambda_handler({}, None))
    assert body["multi_source"] is False
    assert body["severity"] == "none"
    assert body["alert_sent"] is False
    assert ses.sent == []
    assert next(p for p in table.puts if p["pk"] == ANOM_PK)["hypothesis"] == ""


def test_handler_travel_mode_suppresses_the_email(monkeypatch, ses):
    trip = {
        "pk": anomaly.TRAVEL_PK,
        "sk": "TRIP#open",
        "start_date": "0001-01-01",
        "end_date": "9999-12-31",
        "destination_city": "Lisbon",
    }
    table = _install(monkeypatch, FakeTable(rows=[trip]))
    monkeypatch.setattr(
        anomaly,
        "check_anomalies",
        lambda *_a, **_k: [_flag(source="whoop"), _flag(source="withings", field="weight_lbs", label="Weight")],
    )
    body = _body(anomaly.lambda_handler({}, None))
    assert body["severity"] == "travel_suppressed"
    assert body["travel_mode"] is True
    assert body["travel_destination"] == "Lisbon"
    assert body["alert_sent"] is False
    assert ses.sent == []
    record = next(p for p in table.puts if p["pk"] == ANOM_PK)
    assert "[TRAVEL]" in record["hypothesis"] and "Lisbon" in record["hypothesis"]


def test_handler_sick_mode_suppresses_the_email(monkeypatch, ses):
    _install(monkeypatch, FakeTable())
    monkeypatch.setattr(
        anomaly,
        "check_anomalies",
        lambda *_a, **_k: [_flag(source="whoop"), _flag(source="withings", field="weight_lbs", label="Weight")],
    )
    monkeypatch.setattr(anomaly, "_check_travel", lambda _d: None)
    import health.sick_day_checker as sick

    monkeypatch.setattr(sick, "check_sick_day", lambda *_a, **_k: {"reason": "flu"})

    body = _body(anomaly.lambda_handler({}, None))
    assert body["severity"] == "sick_suppressed"
    assert body["alert_sent"] is False
    assert ses.sent == []


def test_handler_sends_sustained_alert_when_streaks_detected(monkeypatch, ses):
    table = _install(monkeypatch, FakeTable())
    monkeypatch.setattr(anomaly, "check_anomalies", lambda *_a, **_k: [_flag(source="whoop")])
    monkeypatch.setattr(
        anomaly,
        "_check_sustained_streaks",
        lambda _y, _f: [{"metric": "hrv", "label": "HRV", "direction": "low", "streak_days": 4, "training_context": None}],
    )
    body = _body(anomaly.lambda_handler({}, None))
    assert body["sustained_count"] == 1
    assert body["sustained_alert_sent"] is True
    assert body["alert_sent"] is False  # single source: no primary alert
    assert len(ses.sent) == 1
    assert "Trend Alert" in ses.sent[0]["Content"]["Simple"]["Subject"]["Data"]
    record = next(p for p in table.puts if p["pk"] == ANOM_PK)
    assert record["sustained_alert_sent"] is True


def test_handler_survives_a_sustained_email_failure(monkeypatch, ses):
    class ExplodingSes:
        def send_email(self, **kwargs):
            raise RuntimeError("SES throttled")

    table = _install(monkeypatch, FakeTable())
    monkeypatch.setattr(anomaly, "ses", ExplodingSes())
    monkeypatch.setattr(anomaly, "check_anomalies", lambda *_a, **_k: [])
    monkeypatch.setattr(
        anomaly,
        "_check_sustained_streaks",
        lambda _y, _f: [{"metric": "hrv", "label": "HRV", "direction": "low", "streak_days": 3, "training_context": None}],
    )
    body = _body(anomaly.lambda_handler({}, None))
    assert body["sustained_alert_sent"] is False
    assert next(p for p in table.puts if p["pk"] == ANOM_PK)["sustained_metrics"][0]["metric"] == "hrv"


def test_handler_survives_a_sustained_streak_crash(monkeypatch, ses):
    _install(monkeypatch, FakeTable())
    monkeypatch.setattr(anomaly, "check_anomalies", lambda *_a, **_k: [])

    def _boom(_y, _f):
        raise RuntimeError("streak walker exploded")

    monkeypatch.setattr(anomaly, "_check_sustained_streaks", _boom)
    body = _body(anomaly.lambda_handler({}, None))
    assert body["sustained_count"] == 0
    assert body["severity"] == "none"


def test_handler_survives_a_primary_email_failure(monkeypatch):
    class ExplodingSes:
        def send_email(self, **kwargs):
            raise RuntimeError("SES throttled")

    table = _install(monkeypatch, FakeTable())
    monkeypatch.setattr(anomaly, "ses", ExplodingSes())
    monkeypatch.setattr(
        anomaly,
        "check_anomalies",
        lambda *_a, **_k: [_flag(source="whoop"), _flag(source="withings", field="weight_lbs", label="Weight")],
    )
    monkeypatch.setattr(anomaly, "call_haiku_hypothesis", lambda f, c: "hypothesis")
    body = _body(anomaly.lambda_handler({}, None))
    assert body["alert_sent"] is False
    assert body["severity"] == "moderate"  # the record still tells the truth about what was found
    assert next(p for p in table.puts if p["pk"] == ANOM_PK)["alert_sent"] is False


def test_build_context_drops_keys_and_list_fields(monkeypatch):
    rows = [
        _row("whoop", "2026-08-02", hrv=55, activities=[{"x": 1}], recovery_score=42),
        _row("todoist", "2026-08-02", tasks_completed=3, food_log=[]),
    ]
    _install(monkeypatch, FakeTable(rows=rows))
    context = anomaly.build_context("2026-08-02")
    assert context["date"] == "2026-08-02"
    assert context["whoop"] == {"date": "2026-08-02", "hrv": 55, "recovery_score": 42}
    assert "pk" not in context["whoop"] and "sk" not in context["whoop"]
    assert "activities" not in context["whoop"]
    assert context["todoist"] == {"date": "2026-08-02", "tasks_completed": 3}
    assert "eightsleep" not in context  # sources with no row are omitted entirely
