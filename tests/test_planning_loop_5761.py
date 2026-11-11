"""tests/test_planning_loop_5761.py — every program week closes the planning loop on ONE Sunday (#5761, block-1 retro #5496).

Three boxes, three contracts:

  1. THE KEY. A `PANEL#` row's `week_end` is the Sunday of its Monday-Sunday week — pinned to `training.may_tracker`'s own
     week (`week_bounds` + `build_week`'s `week_end`), for every day of a span crossing the PDT->PST change. Block 1 had a
     `PANEL#2026-10-24` (Saturday) from an on-demand Sunday run whose default "yesterday" graded Sunday-to-Saturday.
  2. THE DEAD-MAN. qa-smoke's `planning_loop_liveness` reds a completed week with no tracker row or no panel grade from
     the following Tuesday; the fixture is the live sk shape read 2026-11-11 (sk suffixes only).
  3. THE DEPARTURES. The weekly grade names its committed `draft_custom` routines and their reasons — on the grade and
     its row, never in the blinded judge body.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
from datetime import date, datetime, timedelta

import pytest

_REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "lambdas"))
sys.path.insert(0, str(_REPO / "scripts"))
sys.path.insert(0, str(_REPO))

os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "test-bucket")

from operational import planning_loop_qa as qa  # noqa: E402
from training import may_tracker as mt, panel_judge, panel_rubric, training_charter as tc  # noqa: E402

from mcp import panel_weekly_grade as pwg  # noqa: E402

FIX = _REPO / "tests" / "fixtures" / "panel_golden_5072"

# The live sk suffixes on 2026-11-11 (read-only DDB query): may_tracker WEEK#<monday>, training_constraints PANEL#<week_end>.
LIVE_TRACKER = ["2026-10-12", "2026-10-19", "2026-10-26", "2026-11-02"]
LIVE_PANEL = ["2026-10-24", "2026-10-25", "2026-11-01", "2026-11-08"]


@pytest.fixture(autouse=True)
def _bundled_charter_only(monkeypatch):
    monkeypatch.delenv(tc.PRIVATE_ENV_VAR, raising=False)
    monkeypatch.setattr(tc, "_from_s3", lambda key: None)
    tc.reset_cache()
    yield
    tc.reset_cache()


def _tracker_week_end(monday: str) -> str:
    """The tracker's OWN week_end for `monday` — from the row it builds, not a re-derivation."""
    row = mt.build_week(
        monday,
        weight={},
        waist=mt.waist_section([], mt.shift(monday, 6)),
        steps=mt.steps_section([]),
        anchors=mt.anchors_section({}, mt.shift(monday, 6)),
        volume=mt.volume_section({"muscles": {}}),
        fitness=mt.fitness_section(None),
    )
    return row["week_end"]


# ── 1. the key ───────────────────────────────────────────────────────────────────────────────────────────────────────
def test_every_day_grades_its_week_under_the_trackers_sunday():
    """Any requested day — Saturday 10-24 included, and across 11-01's PDT->PST change — grades its Monday-Sunday week
    and the PANEL# key is the tracker's week_end for that Monday."""
    problems = []
    d = date(2026, 10, 12)
    while d <= date(2026, 11, 22):
        mon, sun = pwg.week_to_grade(d.isoformat(), "2026-12-01")
        tracker_mon = mt.week_bounds(d.isoformat())[0]
        sk = panel_judge.panel_item({"week_end": sun, "week_start": mon}, "USER#matthew")["sk"]
        if (mon, sk) != (tracker_mon, "PANEL#" + _tracker_week_end(tracker_mon)):
            problems.append(f"{d}: graded {mon}..{sun} as {sk}; tracker week {tracker_mon} ends {_tracker_week_end(tracker_mon)}")
        d += timedelta(days=1)
    assert not problems, "\n".join(problems)
    assert pwg.week_to_grade("2026-10-24", "2026-12-01") == ("2026-10-19", "2026-10-25")  # the block-1 stray's day


def test_the_default_week_is_the_newest_completed_one_on_any_day():
    """The Monday schedule still grades the Sunday just finished; an on-demand Sunday run (the stray's 2026-10-25 07:09
    PT) grades the last COMPLETED week, not Sunday-to-Saturday."""
    assert pwg.week_to_grade(None, "2026-10-26") == ("2026-10-19", "2026-10-25")
    assert pwg.week_to_grade(None, "2026-10-25") == ("2026-10-12", "2026-10-18")
    assert pwg.week_to_grade(None, "2026-10-31") == ("2026-10-19", "2026-10-25")


def test_the_row_refuses_a_key_that_is_not_a_sunday():
    for bad in ("2026-10-24", "2026-10-19", "2026-11-04"):
        with pytest.raises(ValueError, match="not the Sunday"):
            panel_judge.panel_item({"week_end": bad}, "USER#matthew")


def test_the_job_stores_a_saturday_request_under_its_sunday(monkeypatch):
    seen, stored = {}, []
    monkeypatch.setattr(pwg, "read_routines", lambda s, e: seen.update(start=s, end=e) or [{"target_date": s}])
    monkeypatch.setattr(pwg, "read_constraint_block", lambda e: None)
    monkeypatch.setattr(pwg, "read_history", lambda: [])
    monkeypatch.setattr(pwg, "read_food_plan", lambda s, r: None)
    monkeypatch.setattr(pwg, "read_menu_plan", lambda p: None)
    monkeypatch.setattr(pwg, "store", lambda g: stored.append(panel_judge.panel_item(g, "USER#matthew")["sk"]) or {"written": True})
    monkeypatch.setattr(panel_judge, "grade_committed_week", lambda end, **kw: {"week_end": end, "status": "graded", **kw})
    pwg.run("2026-10-24")
    assert (seen["start"], seen["end"]) == ("2026-10-19", "2026-10-25") and stored == ["PANEL#2026-10-25"], (seen, stored)


# ── 2. the dead-man ──────────────────────────────────────────────────────────────────────────────────────────────────
def test_a_week_is_due_from_the_following_tuesday():
    assert qa.expected_week("2026-11-17") == "2026-11-09"  # Tuesday: the week just ended
    assert qa.expected_week("2026-11-16") == "2026-11-02"  # Monday: the grade and the tracker may not have landed yet
    assert qa.due_weeks("2026-11-11") == ["2026-10-19", "2026-10-26", "2026-11-02"]
    late = qa.due_weeks("2027-03-02")
    assert len(late) == qa.LOOKBACK_WEEKS and late[-1] == qa.expected_week("2027-03-02")


def test_the_live_record_is_closed_and_the_saturday_key_is_named():
    verdict, msg = qa.assess(LIVE_TRACKER, LIVE_PANEL, "2026-11-11")
    assert verdict == "warn" and "2026-10-24" in msg, msg
    assert qa.assess(LIVE_TRACKER, [k for k in LIVE_PANEL if k != "2026-10-24"], "2026-11-11")[0] == "ok"


def test_a_missing_tracker_row_or_panel_grade_reds_the_week():
    verdict, msg = qa.assess(LIVE_TRACKER, LIVE_PANEL, "2026-11-17")  # Tuesday: week 11-09 is due, neither row exists
    assert verdict == "fail" and "WEEK#2026-11-09" in msg and "PANEL#2026-11-15" in msg, msg
    no_grade = qa.assess(LIVE_TRACKER + ["2026-11-09"], LIVE_PANEL, "2026-11-17")
    assert no_grade[0] == "fail" and "PANEL#2026-11-15" in no_grade[1] and "WEEK#2026-11-09" not in no_grade[1], no_grade
    no_row = qa.assess(LIVE_TRACKER, LIVE_PANEL + ["2026-11-15"], "2026-11-17")
    assert no_row[0] == "fail" and "WEEK#2026-11-09" in no_row[1] and "PANEL#2026-11-15" not in no_row[1], no_row
    # the Saturday key never closes the week whose Sunday it misses
    assert qa.assess(LIVE_TRACKER, ["2026-10-24", "2026-11-01", "2026-11-08"], "2026-11-11")[0] == "fail"
    assert qa.assess(LIVE_TRACKER, LIVE_PANEL, "2026-11-16")[0] == "warn"  # Monday: week 11-09 not yet due


class _Table:
    def __init__(self, items=None, fail=False):
        self.items, self.fail = items or [], fail

    def query(self, **kw):
        if self.fail:
            raise RuntimeError("ddb down")
        cond = kw["KeyConditionExpression"].get_expression()["values"]
        pk, prefix = cond[0].get_expression()["values"][1], cond[1].get_expression()["values"][1]
        return {"Items": [{"sk": i["sk"]} for i in self.items if i["pk"] == pk and i["sk"].startswith(prefix)]}


class _Check:
    def __init__(self, name, category, partition):
        self.name = name

    def ok(self, m):
        return ("ok", m)

    def warn(self, m):
        return ("warn", m)

    def fail(self, m):
        return ("fail", m)


def test_the_check_reads_sk_keys_from_both_partitions_and_warns_on_a_failed_read():
    items = [{"pk": mt.PK, "sk": "WEEK#" + m} for m in LIVE_TRACKER]
    items += [{"pk": "USER#matthew#SOURCE#training_constraints", "sk": "PANEL#" + e} for e in LIVE_PANEL if e != "2026-10-24"]
    items.append({"pk": "USER#matthew#SOURCE#training_constraints", "sk": "PHASE#EVAL#2026-11-02"})  # not a panel row
    now = lambda: datetime(2026, 11, 11, 12, 0)  # noqa: E731
    assert qa.check_planning_loop_liveness(_Table(items), _Check, "content", now)[0][0] == "ok"
    out = qa.check_planning_loop_liveness(_Table(fail=True), _Check, "content", now)
    assert out == [("warn", "planning-loop rows could not be read (no verdict was reached): RuntimeError")]


def test_the_dead_man_is_wired_into_the_qa_smoke_sweep():
    src = (_REPO / "lambdas" / "operational" / "qa_smoke_lambda.py").read_text()
    assert '("planning_loop_liveness", lambda: planning_loop_qa.check_planning_loop_liveness(' in src


# ── 3. the departures ────────────────────────────────────────────────────────────────────────────────────────────────
def _replay(calls):
    rec = json.loads((FIX / "recorded_judge.json").read_text(encoding="utf-8"))["responses"]

    def call(body):
        calls.append(body)
        food = "FOOD PLAN UNDER REVIEW" in json.dumps(body["messages"])
        reply = rec["food_good_week" if food else "good_charter_plan"]
        return {"content": [{"type": "text", "text": json.dumps(reply)}], "stop_reason": "end_turn", "usage": {}}

    return call


def test_the_grade_names_each_departure_and_its_reason_but_the_judge_never_sees_it():
    good = json.loads((FIX / "good_charter_plan.json").read_text(encoding="utf-8"))
    routines = [dict(r) for r in good["routines"]]
    routines[0] = {**routines[0], "source_action": "draft_custom", "inputs_snapshot": {"departure_reason": "SENTINEL-travel day"}}
    routines[1] = {**routines[1], "source_action": "draft_custom", "inputs_snapshot": {}}
    calls: list = []
    g = panel_judge.grade_committed_week(
        "2026-10-18",
        week_start="2026-10-12",
        routines=routines,
        constraint_block=good["constraint_block"],
        rubric=panel_rubric.load_rubric(),
        call=_replay(calls),
    )
    dep = g["departures"]
    assert (dep["committed"], dep["draft_custom"]) == (len(routines), 2), dep
    assert {r["reason"] for r in dep["reasons"]} == {"SENTINEL-travel day", "no departure_reason recorded"}, dep
    assert calls and not any("SENTINEL" in json.dumps(c) or "draft_custom" in json.dumps(c) for c in calls), "the judge stays blinded"
    assert panel_judge.panel_item(g, "USER#matthew")["departures"] == dep
    assert panel_judge.departures([])["draft_custom"] == 0
