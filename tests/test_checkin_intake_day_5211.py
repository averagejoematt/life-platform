"""tests/test_checkin_intake_day_5211.py — #5211: the next-morning check-in / intake day row.

The writer rides scenario-explorer (no new schedule); one join with the weekly path; absent check-in is an explicit
marker; an unfinished log is unknown; a failure never breaks the host; the dead-man names a missing day.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from decimal import Decimal

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "lambdas"))
sys.path.insert(0, os.path.join(REPO, "lambdas", "compute"))

from health import checkin_intake_pairs as cip  # noqa: E402

LINE = 800
DAY = "2026-10-27"


def _src(checkin=True, kcal=1000):
    return {
        "evening_checkin": [{"sk": f"DATE#{DAY}", "date": DAY, "stress": Decimal(3), "hunger": Decimal(2)}] if checkin else [],
        "macrofactor": [
            {
                "sk": f"DATE#{DAY}",
                "date": DAY,
                "total_calories_kcal": Decimal(kcal),
                "total_protein_g": Decimal(120),
                "food_log": [{"time": "21:30"}],
            }
        ],
        "apple_health": [],
    }


def _write(src, monkeypatch):
    monkeypatch.setattr("health.titration.settings", lambda: {"complete_log_kcal": LINE})
    puts = []
    item = cip.write_day(
        DAY,
        fetch=lambda s, a, b: src[s],
        put_item=lambda Item: puts.append(Item),
        computed_at="2026-10-28T12:10:00+00:00",
        target_for=lambda d: 900,
    )
    return item, puts


def test_day_row_is_owner_only_and_overwrites_one_key(monkeypatch):
    item, puts = _write(_src(), monkeypatch)
    assert item["pk"] == cip.PK and item["sk"] == f"DATE#{DAY}" and item["tier"] == "owner_only"
    assert item["has_checkin"] is True and item["state"] == "checkin" and item["kcal_over_target"] == 100
    assert len(puts) == 1 and isinstance(puts[0]["kcal"], Decimal)


def test_absent_checkin_is_an_explicit_marker_not_a_missing_row(monkeypatch):
    item, puts = _write(_src(checkin=False), monkeypatch)
    assert item["has_checkin"] is False and item["state"] == "no_checkin" and item["stress"] is None
    assert len(puts) == 1 and item["kcal"] == 1000  # the settled intake is still stored beside the absence


def test_unfinished_log_is_unknown_never_a_low_day(monkeypatch):
    item, _ = _write(_src(kcal=300), monkeypatch)
    assert item["kcal"] is None and item["kcal_over_target"] is None and item["protein_hit"] is None


def test_one_join_the_stored_day_equals_the_weekly_series_row(monkeypatch):
    src = _src()
    item, _ = _write(src, monkeypatch)
    from health import protein_engine

    series = cip.build_series(src["evening_checkin"], src["macrofactor"], src["apple_health"], lambda d: 900, LINE, protein_engine.hit)
    keys = set(series[DAY])
    assert {k: item[k] for k in keys} == series[DAY]


def test_host_step_failure_never_breaks_the_explorer(monkeypatch):
    import scenario_explorer_lambda as se

    def boom(*a, **k):
        raise RuntimeError("ddb down")

    monkeypatch.setattr(cip, "write_day", boom)
    assert se._write_checkin_pair("2026-10-28") == "failed:RuntimeError"


def test_host_step_writes_the_previous_pacific_day(monkeypatch):
    import scenario_explorer_lambda as se

    seen = []
    monkeypatch.setattr(cip, "write_day", lambda day, **k: seen.append(day))
    assert se._write_checkin_pair("2026-10-28") == "written:2026-10-27" and seen == ["2026-10-27"]


class _Check:
    def __init__(self, name, cat, tier):
        self.name, self.status, self.msg = name, None, ""

    def ok(self, m):
        self.status, self.msg = "ok", m

    def fail(self, m):
        self.status, self.msg = "fail", m
        return self

    def with_details(self, d):
        return self


class _Table:
    def __init__(self, sks):
        self.sks = sks

    def query(self, **k):
        return {"Items": [{"sk": s} for s in self.sks]}


def test_dead_man_names_the_missing_day_and_arms_late():
    from operational import nudge_ledger_qa as q

    now = lambda: datetime(2026, 10, 30, 11, 0)  # noqa: E731
    ok = q.check_checkin_pair_liveness(_Table(["DATE#2026-10-29", "DATE#2026-10-28", "DATE#2026-10-27"]), _Check, "t", now)[0]
    assert ok.status == "ok"
    bad = q.check_checkin_pair_liveness(_Table(["DATE#2026-10-29"]), _Check, "t", now)[0]
    assert bad.status == "fail" and "2026-10-28" in bad.msg and "2026-10-27" in bad.msg
    early = q.check_checkin_pair_liveness(_Table([]), _Check, "t", lambda: datetime(2026, 10, 26, 11, 0))[0]
    assert early.status == "ok" and "pending" in early.msg
    assert q.CHECKIN_PAIR_PK == cip.PK


def test_dead_man_is_wired_into_the_nightly_sweep():
    src = open(os.path.join(REPO, "lambdas", "operational", "qa_smoke_lambda.py")).read()
    assert "check_checkin_pair_liveness" in src
