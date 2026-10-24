"""tests/test_wake_consistency_5133.py — the wake-time consistency rule in the charter (#5133, epic #5120).

Holds:
  1. THE RULE IS DATA: `sleep.wake_time` carries the tolerance, the anchor window and its minimum, every day with
     weekends included, the one grader, the habit pointer (#5124) and the #5029 cross-reference (timing only; the
     heart-rate re-baselining is not duplicated here).
  2. ONE GRADER: `health.wake_consistency` grades a day against his own trailing median, never against the day
     itself; within the tolerance either side is on time, beyond it off; a day with no wake time and a window under
     the minimum are unknown, never a miss. Every expectation is derived from the charter's numbers (no pinned
     tolerance), and no clock is read — every day is an argument.
  3. THE SHARED CONTEXT: every daily coach's standing lines (`coach_context.charter_goal_lines`) state the rule from
     the charter, and the sleep coach's input carries it; the rule fields are on the published whitelist (a rule,
     no clock time) and the published charter view carries no wake clock time.
"""

from __future__ import annotations

import datetime as _dt
import os
import sys

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

from health import wake_consistency as wc  # noqa: E402
from training import coach_context, training_charter as tc  # noqa: E402

END = "2026-11-15"  # a fixed fixture day; nothing below reads the clock


@pytest.fixture(autouse=True)
def _public_only(monkeypatch):
    monkeypatch.delenv(tc.PRIVATE_ENV_VAR, raising=False)
    monkeypatch.setattr(tc, "_from_s3", lambda key: None)
    tc.reset_cache()
    yield
    tc.reset_cache()


def _hhmm(minutes: float) -> str:
    m = int(minutes) % 1440
    return f"{m // 60:02d}:{m % 60:02d}"


def _history(end: str, days: int, at: int = 6 * 60 + 30) -> dict:
    d = _dt.date.fromisoformat(end)
    return {(d - _dt.timedelta(days=i)).isoformat(): _hhmm(at) for i in range(1, days + 1)}


def test_the_rule_is_charter_data_with_its_cross_references():
    r = tc.charter_value("sleep.wake_time")
    assert r["tolerance_minutes"] > 0 and r["anchor_window_days"] >= r["min_days_for_anchor"] > 0
    assert r["every_day"] is True and r["weekends_included"] is True
    assert r["anchor"] == "trailing_median" and "never a typed clock time" in r["rule"]
    assert r["reader"].startswith("health.wake_consistency")
    assert "#5124" in r["habit"] and "health.wake_consistency" in r["habit"], "the out-of-bed-on-time habit reads the same grader"
    assert "#5029" in r["hr_regime"] and "timing" in r["hr_regime"].lower(), "the HR re-baselining is cross-referenced, not duplicated"
    assert wc.rule() == {k: r[k] for k in ("tolerance_minutes", "anchor_window_days", "min_days_for_anchor")}


def test_one_grader_against_his_own_trailing_median():
    r = wc.rule()
    tol, window, need = r["tolerance_minutes"], r["anchor_window_days"], r["min_days_for_anchor"]
    anchor = 6 * 60 + 30
    hist = _history(END, window, anchor)
    wrong = []
    for delta, want in ((0, wc.ON_TIME), (tol, wc.ON_TIME), (-tol, wc.ON_TIME), (tol + 1, wc.OFF), (-(tol + 1), wc.OFF)):
        got = wc.grade_day(END, {**hist, END: _hhmm(anchor + delta)})
        if got["state"] != want or got["anchor_minutes"] != anchor:
            wrong.append(f"delta {delta}: {got['state']} (anchor {got.get('anchor_minutes')}) != {want}")
    assert not wrong, "\n".join(wrong)
    # the graded day is never in its own anchor: a late day does not drag the anchor toward itself
    assert wc.grade_day(END, {**hist, END: _hhmm(anchor + 3 * tol)})["anchor_minutes"] == anchor
    # unknown, never a miss
    assert wc.grade_day(END, hist)["state"] == wc.UNKNOWN and wc.grade_day(END, hist)["reason"] == "no_wake_time"
    thin = _history(END, need - 1, anchor)
    thin[END] = _hhmm(anchor)
    assert wc.grade_day(END, thin)["reason"] == "no_anchor"
    assert wc.grade_day(END, {END: "06:30"}, settings={})["reason"] == "rule_unreadable"
    # midnight: the distance is circular
    late = _history(END, window, 23 * 60 + 50)
    assert wc.grade_day(END, {**late, END: "00:05"})["delta_minutes"] == 15


def test_the_week_counts_unknown_days_apart_from_misses():
    r = wc.rule()
    anchor = 7 * 60
    wakes = _history(END, r["anchor_window_days"] + 7, anchor)
    d = _dt.date.fromisoformat(END)
    wakes[END] = _hhmm(anchor + r["tolerance_minutes"] + 5)  # off
    del wakes[(d - _dt.timedelta(days=1)).isoformat()]  # unknown
    wk = wc.grade_week(END, wakes)
    assert (wk["on_time"], wk["off"], wk["unknown"]) == (5, 1, 1), wk
    assert wk["charter_version"] == tc.charter_version() and len(wk["days"]) == 7


def test_every_daily_coach_and_the_sleep_coach_read_the_rule_from_the_charter():
    r = tc.charter_value("sleep.wake_time")
    lines = coach_context.charter_goal_lines()
    assert f"within {r['tolerance_minutes']} min" in lines and f"trailing {r['anchor_window_days']} days" in lines
    assert "weekends" in lines and "never a miss" in lines
    rule = coach_context.wake_time_rule()
    assert rule["tolerance_minutes"] == r["tolerance_minutes"] and rule["source"].startswith("config/training_charter.json sleep.wake_time")
    from coach import coach_input_facts as ci

    ci._run.clear()
    out = ci.coach_inputs("sleep_coach", {"sleep_score": 80}, {"date": END})
    assert out["wake_time_rule"] == rule
    ci._run.clear()
    assert "wake_time_rule" not in ci.coach_inputs("mind_coach", {"mood": 3}, {"date": END})
    pub = tc.public_view().get("sleep", {}).get("wake_time", {})
    assert pub.get("tolerance_minutes") == r["tolerance_minutes"]
    assert not {"hr_regime", "provenance"} & set(pub), "only the rule fields are published"
