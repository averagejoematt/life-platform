"""#4580 B-14 — a graded bet serves WHICH device and WHICH days its number came from.

The wire: the resolved docket `ENSEMBLE#docket` /
`RESOLVED#2026-10-16#physical_coach__sleep_coach#deep-sleep-spike-interpretation-signal-vs-noise`
(criterion `deep_pct_7day_avg >= 26 on 2026-10-16`, verdict actual_value 16.357…, read 2026-10-18), served on
/api/calls as "It came in at 16.4%." with no device and no window. The verifier re-measured it: 16.4 is Eight
Sleep's 7-day deep share over Oct 9–15 (deep_pct 15.8, 14.8, 8.9, 16.6, 21.8, 17.5, 19.4); Whoop's share to
Oct 16 is 22.9%. The verdict (below 26% on both devices) is unchanged by this fix — only the label is new.

Mutation controls (run by hand for the PR, each reds a test here): drop `actual_reading` from
`dispute_docket._resolve_one`'s verdict; drop `**reading` from `site_api_calls.build_bet`'s `actual`.
"""

import copy
import os
import sys
from decimal import Decimal

os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("USER_ID", "matthew")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "coach"))
sys.path.insert(0, os.path.join(_REPO, "tests"))

import coach_prediction_evaluator as evaluator  # noqa: E402
import pytest  # noqa: E402
from coach import (
    dispute_docket as dd,  # noqa: E402
    metric_reading,  # noqa: E402
)
from test_dispute_docket_1386 import FakeTable  # noqa: E402
from web import site_api_calls as calls  # noqa: E402

RESOLVE_DAY = "2026-10-16"
EIGHTSLEEP_ROWS = [  # the stored rows the 7-day window read, as boto3 returns them
    {"date": d, "sk": f"DATE#{d}", "deep_pct": Decimal(v)}
    for d, v in [
        ("2026-10-09", "15.8"),
        ("2026-10-10", "14.8"),
        ("2026-10-11", "8.9"),
        ("2026-10-12", "16.6"),
        ("2026-10-13", "21.8"),
        ("2026-10-14", "17.5"),
        ("2026-10-15", "19.4"),
    ]
]
CRITERION = {
    "metric": "deep_pct_7day_avg",
    "condition": "gte",
    "threshold": Decimal("26"),
    "description": "deep_pct_7day_avg >= 26 on 2026-10-16",
}


def _cache():
    return {evaluator.source_cache_key("eightsleep", RESOLVE_DAY, 7): copy.deepcopy(EIGHTSLEEP_ROWS)}


def test_provenance_names_the_device_and_the_days_the_value_used():
    cache = _cache()
    value = evaluator._resolve_metric_value("deep_pct_7day_avg", cache, RESOLVE_DAY)
    reading = metric_reading.metric_reading_provenance(evaluator, "deep_pct_7day_avg", cache, RESOLVE_DAY)
    assert round(value, 1) == 16.4
    # the label names exactly the points the graded value is the mean of
    pts = metric_reading.reading_points(evaluator, "deep_pct_7day_avg", cache, RESOLVE_DAY)["_values"]
    assert sum(pts) / len(pts) == value
    assert reading == {
        "source": "eightsleep",
        "source_label": "Eight Sleep",
        "metric": "deep_pct",
        "aggregate": "mean",
        "days": 7,
        "start": "2026-10-09",
        "end": "2026-10-15",
        "n": 7,
    }


def test_provenance_never_reads_a_second_time():
    """Control: no slot in the cache → None (the label can only describe rows the value was computed from)."""
    assert metric_reading.metric_reading_provenance(evaluator, "deep_pct_7day_avg", {}, RESOLVE_DAY) is None


@pytest.fixture()
def table(monkeypatch):
    t = FakeTable()
    monkeypatch.setattr(dd, "table", t)
    monkeypatch.setattr(dd, "EXPERIMENT_START_DATE", "2026-09-06")
    monkeypatch.setattr(evaluator, "_update_bayesian_confidence", lambda *a: None)
    monkeypatch.setattr(dd.coach_baseline, "docket_stamp", lambda *a, **k: None)
    return t


def test_the_resolved_row_carries_the_reading(table):
    docket = {
        "pk": dd.DOCKET_PK,
        "sk": "OPEN#physical_coach__sleep_coach#deep_pct_7day_avg",
        "topic": "Deep sleep spike: signal vs noise",
        "topic_slug": "deep-sleep-spike-interpretation-signal-vs-noise",
        "coach_a": "physical_coach",
        "coach_b": "sleep_coach",
        "claims": {"physical_coach": "Deep share holds at 26%+.", "sleep_coach": "It regresses below 26%."},
        "criterion": {**CRITERION, "threshold": 26.0},  # the resolver reads rows through decimals_to_float
        "sides": {"physical_coach": True, "sleep_coach": False},
        "resolution_date": RESOLVE_DAY,
        "opened_date": "2026-10-09",
        "subdomain": "sleep",
    }
    table.put_item(Item=docket)
    resolved, voided, waiting = [], [], []
    dd._resolve_one(docket, RESOLVE_DAY, RESOLVE_DAY, _cache(), resolved, voided, waiting)
    assert len(resolved) == 1 and resolved[0]["winner"] == "sleep_coach"  # the verdict logic is unchanged
    row = table.store[(dd.DOCKET_PK, resolved[0]["sk"])]
    reading = row["verdict"]["actual_reading"]
    assert (reading["source_label"], reading["start"], reading["end"], reading["days"]) == ("Eight Sleep", "2026-10-09", "2026-10-15", 7)


def _resolved_docket(reading):
    verdict = {"outcome": "graded", "winner": "sleep_coach", "loser": "physical_coach", "actual_value": 16.357142857142858, "holds": False}
    if reading:
        verdict["actual_reading"] = reading
    return {
        "pk": dd.DOCKET_PK,
        "sk": "RESOLVED#2026-10-16#physical_coach__sleep_coach#deep-sleep-spike-interpretation-signal-vs-noise",
        "topic": "Deep sleep spike: signal vs noise",
        "topic_slug": "deep-sleep-spike-interpretation-signal-vs-noise",
        "coach_a": "physical_coach",
        "coach_b": "sleep_coach",
        "claims": {"physical_coach": "Deep share holds at 26% or more.", "sleep_coach": "It regresses below 26%."},
        "criterion": dict(CRITERION),
        "sides": {"physical_coach": True, "sleep_coach": False},
        "resolution_date": RESOLVE_DAY,
        "resolved_date": RESOLVE_DAY,
        "opened_date": "2026-10-09",
        "verdict": verdict,
    }


NAMES = {"sleep": "Lisa Park", "physical": "Max Reyes"}
READING = {"source": "eightsleep", "source_label": "Eight Sleep", "metric": "deep_pct", "aggregate": "mean", "days": 7,
           "start": "2026-10-09", "end": "2026-10-15", "n": 7}  # fmt: skip


def test_the_served_bet_names_the_device_and_the_window():
    page, why = calls.build_bet(_resolved_docket(READING), NAMES, {}, {})
    assert page is not None, why
    assert page["actual"]["source"] == "eightsleep" and page["actual"]["source_label"] == "Eight Sleep"
    assert page["actual"]["window"] == {"start": "2026-10-09", "end": "2026-10-15", "days": 7, "aggregate": "mean", "n": 7}
    assert page["happened"] == f"It came in at {page['actual']['text']} (Eight Sleep, the 7-day average from October 9 to October 15)."
    assert page["verdict"] == "right" and page["coach_id"] == "sleep"


def test_a_pre_stamp_row_serves_as_before():
    """Control: a row resolved before this change has no reading — no invented label, the sentence is unchanged."""
    page, why = calls.build_bet(_resolved_docket(None), NAMES, {}, {})
    assert page is not None, why
    assert "source" not in page["actual"] and page["happened"] == f"It came in at {page['actual']['text']}."
