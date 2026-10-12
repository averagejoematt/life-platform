"""#4847 — Score Sanity's dashboard:date must read a flagged sick day as the
honest "last graded day", not as staleness.

The live specimen (2026-10-11 18:31Z qa-smoke, request 51bc0c11):
``[content_truth] Score Sanity / dashboard:date: Stale date — expected 2026-10-10,
got 2026-10-09``. The three clocks, all fixed-UTC crons in cdk/stacks/:

  * daily-metrics-compute   cron(40 16 * * ? *)  16:40Z — stamps PT-yesterday's grade
  * daily-brief             cron(0 17 * * ? *)   17:00Z — the ONLY writer of the
    dashboard's ``date`` (output_writers.write_dashboard_json)
  * dashboard-refresh       cron(0 21 …) + cron(0 1 …) — merges intraday values,
    never moves ``date``
  * qa-smoke                cron(30 18 ? * * *)  18:30Z — expects PT-yesterday

None of the clocks was wrong: 2026-10-10 was flagged in the sick_days partition
(logged 2026-10-11T02:22Z), so the 17:00Z brief took its recovery path and
returned before the dashboard write. The sweep's expectation was the wrong rule —
it now walks back past flagged sick days to the last graded day, and an unflagged
gap stays a hard FAIL.

The clock is frozen at the live sweep instant (#4848): every expectation below is
derived from that frozen ``pacific_now``, never from the wall clock.
"""

from __future__ import annotations

import io
import json
import os
from datetime import datetime

os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("EMAIL_RECIPIENT", "qa@example.com")
os.environ.setdefault("EMAIL_SENDER", "qa@example.com")

import pytest  # noqa: E402
from operational import qa_check_outputs as qco  # noqa: E402

DASH = "dashboard/matthew/data.json"

# The live sweep instant: 2026-10-11 18:31Z = 11:31 PDT (pacific_now is naive PT).
SWEEP_PT = datetime(2026, 10, 11, 11, 31)


class _S3:
    def __init__(self, doc):
        self.body = json.dumps(doc).encode()

    def get_object(self, Bucket, Key):
        assert Key == DASH
        return {"Body": io.BytesIO(self.body)}


class _Table:
    """The sick_days partition as DynamoDB returns it (the 10-11 wire row)."""

    def __init__(self, items):
        self.items = items
        self.queries = []

    def query(self, KeyConditionExpression, ExpressionAttributeValues):
        self.queries.append(ExpressionAttributeValues)
        lo = ExpressionAttributeValues[":s"]
        hi = ExpressionAttributeValues[":e"]
        pk = ExpressionAttributeValues[":pk"]
        return {"Items": [i for i in self.items if i["pk"] == pk and lo <= i["sk"] <= hi]}


class _Resource:
    def __init__(self, table):
        self._table = table

    def Table(self, name):
        return self._table


def _sick_row(day, cleared=False):
    row = {
        "pk": "USER#matthew#SOURCE#sick_days",
        "sk": f"DATE#{day}",
        "date": day,
        "reason": "redacted",
        "logged_at": "2026-10-11T02:22:35.496774+00:00",
        "schema_version": 1,
    }
    if cleared:
        row["cleared_at"] = "2026-10-11T03:00:00+00:00"
    return row


# The 10-11 dashboard wire shape (date + day grade of the last GRADED day, 10-09;
# dashboard-refresh had re-stamped generated_at/refreshed_at, not date).
def _wire_dashboard(date_str):
    return {
        "date": date_str,
        "generated_at": "2026-10-11T01:00:24.929587+00:00",
        "refreshed_at": "2026-10-11T01:00:24.929605+00:00",
        "refresh_type": "intraday",
        "readiness": {"score": 62},
        "sleep": {"score": 78},
        "weight": {"current": 306.5},
        "hrv": {"value": 44},
        "glucose": {"avg": 96},
        "day_grade": {"letter": "C+", "score": 71, "components": {"hydration": 72}},
        "character_sheet": {"level": 7, "tier": "discipline", "xp": 12345},
    }


@pytest.fixture()
def sweep(monkeypatch):
    from common import constants, pacific_time

    monkeypatch.setattr(pacific_time, "pacific_now", lambda: SWEEP_PT)
    monkeypatch.setattr(pacific_time, "pacific_today", lambda: SWEEP_PT.date().isoformat())
    monkeypatch.setattr(constants, "EXPERIMENT_START_DATE", "2026-09-06", raising=False)
    monkeypatch.setattr(qco, "EXPERIMENT_START_DATE", "2026-09-06", raising=False)

    def _run(dashboard_date, sick_rows):
        table = _Table(sick_rows)
        monkeypatch.setattr(qco, "s3", _S3(_wire_dashboard(dashboard_date)))
        monkeypatch.setattr(qco.boto3, "resource", lambda *a, **k: _Resource(table))
        checks = {c.name: c for c in qco.check_score_sanity()}
        return checks["dashboard:date"], table

    return _run


def test_the_live_10_11_specimen_is_the_last_graded_day_not_staleness(sweep):
    assert qco._yesterday_str() == "2026-10-10"  # the frozen sweep's D-1
    c, table = sweep("2026-10-09", [_sick_row("2026-10-10")])
    assert c.passed is True, c.message
    assert "last graded day" in c.message and "2026-10-10 flagged sick" in c.message
    assert len(table.queries) == 1  # one bounded Query, not a per-day walk


def test_an_unflagged_one_day_gap_is_still_a_red(sweep):
    c, _ = sweep("2026-10-09", [])
    assert c.passed is False and "Stale date — expected 2026-10-10, got 2026-10-09" in c.message


def test_a_cleared_sick_day_is_not_a_sick_day(sweep):
    # #4378: a tombstoned row means "logged in error" — the gap is real again.
    c, _ = sweep("2026-10-09", [_sick_row("2026-10-10", cleared=True)])
    assert c.passed is False and "Stale date" in c.message


def test_consecutive_sick_days_walk_back_to_the_last_graded_day(sweep):
    c, _ = sweep("2026-10-08", [_sick_row("2026-10-09"), _sick_row("2026-10-10")])
    assert c.passed is True and "2026-10-09, 2026-10-10 flagged sick" in c.message


def test_a_dashboard_older_than_the_last_graded_day_is_still_a_red(sweep):
    # 10-10 sick excuses holding at 10-09 — NOT holding at 10-08.
    c, _ = sweep("2026-10-08", [_sick_row("2026-10-10")])
    assert c.passed is False and "Stale date" in c.message


def test_an_on_time_dashboard_never_reads_the_sick_day_partition(sweep):
    c, table = sweep("2026-10-10", [_sick_row("2026-10-10")])
    assert c.passed is True and table.queries == []


def test_a_failed_sick_day_lookup_fails_strict(sweep, monkeypatch):
    # Fail-soft toward STRICT: an AccessDenied must never excuse a gap.
    def _boom(*a, **k):
        raise RuntimeError("AccessDenied")

    monkeypatch.setattr(qco, "s3", _S3(_wire_dashboard("2026-10-09")))
    monkeypatch.setattr(qco.boto3, "resource", _boom)
    assert qco._last_graded_day("2026-10-10") == ("2026-10-10", [])
    c = {c.name: c for c in qco.check_score_sanity()}["dashboard:date"]
    assert c.passed is False and "Stale date — expected 2026-10-10, got 2026-10-09" in c.message
