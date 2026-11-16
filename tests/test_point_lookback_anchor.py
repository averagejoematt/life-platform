"""tests/test_point_lookback_anchor.py — an old number call is graded on its OWN window, not on the run day's (owner 2026-11-09).

THE DEFECT (coaching-room manifest v3 §2.15 / §4). The point grader read its source data with a 60-day look-back
ending on the RUN day (``prediction_point_grader.metric_value_on`` passed ``today_str`` as the read's end). Re-grading
a September call in November therefore read a window that stopped weeks after its target day: "no reading" →
inconclusive → past the 2x window → ``expired``, although the reading is in the table. Two live calls showed it:

  * explorer 2026-09-06 "Sleep model expects approximately 7 hours tonight ..." — target 2026-09-07,
    7.0 ±1.2082 h; stored REFUTED on a reading of 8.37 h; the November re-run said expired.
  * sleep 2026-09-07 "Recovery score is expected to climb back to roughly 61% tomorrow ..." — target 2026-09-08,
    61 ±17.9029; stored CONFIRMED on a reading of 67; the November re-run said expired.

THE FIX. The read ends on the call's own target day (``prediction_point_grader.read_anchor``), capped at the run day.

The fixtures below are modelled on those two rows (their frozen specs and the readings the stored grade text quotes);
the readings are a synthetic daily series around them. The evaluator runs on its own path (``_evaluate_all`` with
``write=False``) over a fake ``_fetch_range`` that honours the requested date range exactly — the property the defect
turned on. The mutation control puts the old anchor back (``read_anchor`` → the run day) and shows the same fixtures
come out ``expired``, so the regression tests cannot pass vacuously. A call graded when it falls due is graded
identically under both anchors.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta

os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("USER_ID", "matthew")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

import pytest  # noqa: E402
from coach import coach_prediction_evaluator as ev, prediction_point_grader as ppg  # noqa: E402

RUN_DAY = "2026-11-08"  # the manifest's as-of: the day the re-run said "expired"


def _day(start: str, offset: int) -> str:
    return (datetime.strptime(start, "%Y-%m-%d") + timedelta(days=offset)).strftime("%Y-%m-%d")


def _whoop_rows() -> list[dict]:
    """A daily Whoop series 2026-08-01 .. RUN_DAY with the two readings the stored grades quote."""
    rows = []
    for i in range(0, 100):
        d = _day("2026-08-01", i)
        if d > RUN_DAY:
            break
        rows.append({"date": d, "sk": f"DATE#{d}", "sleep_duration_hours": 6.5 + (i % 3) * 0.2, "recovery_score": 40.0 + (i % 5)})
    by_day = {r["date"]: r for r in rows}
    by_day["2026-09-07"]["sleep_duration_hours"] = 8.37  # "sleep_duration_hours=8.37 on 2026-09-07" (stored grade text)
    by_day["2026-09-08"]["recovery_score"] = 67.0  # "recovery_score=67.00 on 2026-09-08" (stored grade text)
    return rows


ROWS = _whoop_rows()


def _fake_fetch_range(source, start_date, end_date, include_pilot=False):
    """The table read, honouring [start, end] exactly — the property the defect turned on."""
    assert source == "whoop", source
    return [dict(r) for r in ROWS if start_date <= r["date"] <= end_date]


@pytest.fixture(autouse=True)
def _wired(monkeypatch):
    monkeypatch.setattr(ev, "_fetch_range", _fake_fetch_range)


def _call(pid, coach, created, spec, stored):
    return {
        "pk": f"COACH#{coach}",
        "sk": f"PREDICTION#{pid}",
        "prediction_id": pid,
        "coach_id": coach,
        "subdomain": "",
        "created_date": created,
        "status": stored,
        "evaluation": spec,
    }


SEPTEMBER_CALLS = (
    # (call, stored verdict) — the frozen specs as the manifest records them
    (
        _call(
            "pred_20260906_sleep_model_expects_approximately_7_hour",
            "explorer_coach",
            "2026-09-06",
            {
                "type": "point",
                "condition": "within",
                "metric": "sleep_duration_hours",
                "evaluation_window_days": 1,
                "target_date": "2026-09-07",
                "threshold": 7.0,
                "tolerance": 1.2082,
                "tolerance_rule": "±1 SD of the trailing 30-day personal series (n=30 readings, SD=1.2082)",
            },
            "refuted",
        ),
        "refuted",
    ),
    (
        _call(
            "pred_20260907_recovery_score_is_expected_to_climb_back",
            "sleep_coach",
            "2026-09-07",
            {
                "type": "point",
                "condition": "within",
                "metric": "recovery_score",
                "evaluation_window_days": 1,
                "target_date": "2026-09-08",
                "threshold": 61.0,
                "tolerance": 17.9029,
                "tolerance_rule": "±1 SD of the trailing 30-day personal series (n=31 readings, SD=17.9029)",
            },
            "confirmed",
        ),
        "confirmed",
    ),
)


def _grade(calls, today=RUN_DAY):
    evaluations, _stats = ev._evaluate_all([dict(c) for c in calls], today, write=False)
    return {e["prediction_id"]: e for e in evaluations}


def _old_anchor(monkeypatch):
    """The mutation: the read ends on the run day again (the code before the fix)."""
    monkeypatch.setattr(ppg, "read_anchor", lambda target_date, today_str: str(today_str)[:10])


@pytest.mark.parametrize("call,stored", SEPTEMBER_CALLS, ids=lambda x: x["prediction_id"] if isinstance(x, dict) else x)
def test_a_september_call_regraded_today_reproduces_its_stored_verdict(call, stored):
    got = _grade([call])[call["prediction_id"]]
    assert got["status"] == stored, got["reason"]
    assert "Expired" not in got["reason"] and "No reading" not in got["reason"]
    assert f"on {call['evaluation']['target_date']}" in got["reason"], "graded on the target day's own reading"


def test_both_september_calls_reproduce_the_reading_their_stored_grade_quotes():
    got = _grade([c for c, _ in SEPTEMBER_CALLS])
    assert got["pred_20260906_sleep_model_expects_approximately_7_hour"]["actual_value"] == 8.37
    assert got["pred_20260907_recovery_score_is_expected_to_climb_back"]["actual_value"] == 67.0


def test_mutation_control_the_old_run_day_anchor_expires_both_calls(monkeypatch):
    """Put the old anchor back: the same fixtures read 'no reading' and expire — the manifest's re-run artifact,
    reproduced. Without this, the tests above could pass on fixtures the defect never touched."""
    _old_anchor(monkeypatch)
    got = _grade([c for c, _ in SEPTEMBER_CALLS])
    for call, _stored in SEPTEMBER_CALLS:
        e = got[call["prediction_id"]]
        assert e["status"] == "expired", e
        assert "No reading" in e["reason"] and "days elapsed" in e["reason"]


def test_the_read_anchor_is_the_target_day_capped_at_the_run_day():
    assert ppg.read_anchor("2026-09-07", RUN_DAY) == "2026-09-07"
    assert ppg.read_anchor("2026-12-01", RUN_DAY) == RUN_DAY  # a target after the run day never reads the future
    assert ppg.read_anchor("2026-09-07T05:00:00", RUN_DAY) == "2026-09-07"


# ── scheduled grading of a call that is due now: identical under both anchors ──────────────────────────────────


DUE_NOW = (
    _call(
        "pred_due_point",
        "sleep_coach",
        _day(RUN_DAY, -1),
        {
            "type": "point",
            "condition": "within",
            "metric": "recovery_score",
            "evaluation_window_days": 1,
            "target_date": RUN_DAY,
            "threshold": 42.0,
            "tolerance": 3.0,
        },
        "pending",
    ),
    _call(
        "pred_due_point_grace",
        "explorer_coach",
        _day(RUN_DAY, -3),
        {
            "type": "point",
            "condition": "within",
            "metric": "sleep_duration_hours",
            "evaluation_window_days": 2,
            "target_date": _day(RUN_DAY, -1),
            "threshold": 9.5,
            "tolerance": 0.5,
        },
        "pending",
    ),
    _call(
        "pred_due_aggregate",
        "sleep_coach",
        _day(RUN_DAY, -8),
        {
            "type": "point",
            "condition": "within",
            "metric": "recovery_score_7day_avg",
            "evaluation_window_days": 7,
            "target_date": _day(RUN_DAY, -1),
            "threshold": 42.0,
            "tolerance": 2.0,
        },
        "pending",
    ),
)

_COMPARED = ("status", "reason", "actual_value", "beats_null", "bayesian_update", "grading_open", "quality_flags", "evaluator_version")


def test_scheduled_grading_of_due_calls_is_identical_under_both_anchors(monkeypatch):
    new = _grade(DUE_NOW)
    assert set(new) == {c["prediction_id"] for c in DUE_NOW}, "every due call was graded"
    assert {e["status"] for e in new.values()} >= {"confirmed", "refuted"}, "both verdicts are exercised"
    _old_anchor(monkeypatch)
    old = _grade(DUE_NOW)
    for pid, e in new.items():
        assert {k: e.get(k) for k in _COMPARED} == {k: old[pid].get(k) for k in _COMPARED}, pid


def test_a_call_not_yet_due_is_still_skipped():
    not_due = _call(
        "pred_not_due",
        "sleep_coach",
        RUN_DAY,
        {
            "type": "point",
            "condition": "within",
            "metric": "recovery_score",
            "evaluation_window_days": 1,
            "threshold": 42.0,
            "tolerance": 3,
        },
        "pending",
    )
    assert _grade([not_due]) == {}
