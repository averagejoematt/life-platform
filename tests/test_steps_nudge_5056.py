"""#5056 — the day's steps line and the 19:00 PT lifting-day nudge."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))

from coach import coach_nudge_engine  # noqa: E402
from common.pacific_time import PACIFIC  # noqa: E402
from emails import steps_nudge_runner as runner  # noqa: E402
from operational import nudge_ledger_qa  # noqa: E402
from training import steps_nudge as sn  # noqa: E402

DATE = "2026-10-20"
NOW = datetime(2026, 10, 20, 19, 10, tzinfo=PACIFIC)  # 19:10 PT, a fixed instant (no live clock)
RAMP = {"state": "at_floor", "today_target": 12000, "floor": 12000, "held_by": []}
LIFT = [{"date": DATE, "exercises": [{"name": "Bench Press", "sets": [{"weight_kg": 80, "reps": 8, "type": "normal"}]}]}]
OFF = [{"date": DATE, "exercises": [{"name": "Incline Walk", "sets": [{"duration_sec": 1200}]}]}]
PACE = 9875  # 12000 x (19:10 - 06:00) / (22:00 - 06:00) = 12000 x 790/960


def decide(steps, hevy=LIFT, **kw):
    args = dict(date=DATE, now_pt=NOW, ramp=RAMP, steps_day={"steps": steps}, hevy_rows=hevy, already_sent=False, budget_tier=0)
    args.update(kw)
    return sn.decide(**args)


def test_pace_formula_pinned():
    assert sn.pace(12000, NOW) == PACE
    assert sn.pace(12000, NOW.replace(hour=22, minute=0)) == 12000  # clamp at 22:00
    assert sn.pace(12000, NOW.replace(hour=5)) == 0  # clamp before the day starts
    early = NOW.replace(hour=5, minute=0)
    assert sn.pace(12000, NOW, first_session_pt=early) > PACE  # an early lifter's day began earlier
    assert sn.pace(12000, NOW, first_session_pt=NOW.replace(hour=17)) == PACE  # a late session never shortens the day


def test_lifting_day_behind_pace_sends_with_the_walk():
    v = decide(7000)
    assert v["send"] and v["reason"] == "behind_pace" and v["pace"] == PACE
    assert v["gap_to_target"] == 5000 and v["walk_minutes"] == 50
    assert "50-min walk" in v["text"] and "5,000 steps" in v["text"] and "7,000" in v["text"]


def test_ahead_of_pace_is_silent():
    assert decide(11000)["reason"] == "ahead_of_pace" and not decide(11000)["send"]


def test_exact_threshold_is_not_behind():
    assert not decide(PACE)["send"] and decide(PACE)["reason"] == "ahead_of_pace"
    assert decide(PACE - 1)["send"]


def test_off_day_is_silent_even_far_behind():
    for rows in (None, [], OFF):
        v = decide(500, hevy=rows)
        assert not v["send"] and v["reason"] == "off_day"


def test_gym_cardio_minutes_count_toward_the_pace():
    both = LIFT + OFF  # 20 min of incline walk = 2,000 steps-equivalent
    assert sn.gym_cardio(both) == {"minutes": 20, "steps_equivalent": 2000}
    assert decide(PACE - 1500, hevy=both)["send"] is False
    assert decide(PACE - 2001, hevy=both)["send"] is True


def test_never_a_nudge_built_on_nothing():
    assert decide(None)["reason"] == "no_steps_reading"
    assert decide(7000, ramp={"state": "unknown"})["reason"] == "no_target"


def test_rails_budget_window_already_sent():
    assert decide(7000, budget_tier=coach_nudge_engine.BUDGET_SILENCE_TIER)["reason"] == "budget_tier_2"
    assert sn.BUDGET_SILENCE_TIER == coach_nudge_engine.BUDGET_SILENCE_TIER
    assert decide(7000, now_pt=NOW.replace(hour=18))["reason"] == "outside_window"
    assert decide(7000, now_pt=NOW.replace(hour=21))["reason"] == "outside_window"
    assert decide(7000, already_sent=True)["reason"] == "already_sent"
    assert decide(7000)["key"] == "STEPS_NUDGE#2026-10-20"


def test_copy_is_information_not_command():
    t = decide(7000)["text"].lower()
    assert "skip" in t and not any(w in t for w in ("streak", "you must", "failed", "lazy", "behind schedule"))


def test_target_line():
    assert sn.target_line(RAMP) == "Steps today: floor 12,000, target 15,000"
    ramping = {"state": "ramping", "today_target": 9100, "floor": 12000, "held_by": []}
    assert "today's ramp step 9,100 (ramping)" in sn.target_line(ramping)
    assert sn.target_line({"state": "unknown"}) is None and sn.target_line(None) is None


def test_plan_engine_ramp_block_carries_the_line():
    from training import plan_engine

    out = plan_engine._steps_ramp_block(DATE, None, None, None, None, {})
    assert out["state"] == "unknown" and "steps_target_line" not in out  # unread -> stated, no line built on nothing


# ── the runner: idempotency, claim before send, eval stamp ────────────────────────────────────────────────────
class FakeTable:
    def __init__(self):
        self.items = {}

    def put_item(self, Item, ConditionExpression=None):
        key = (Item["pk"], Item["sk"])
        if ConditionExpression and key in self.items:
            raise RuntimeError("ConditionalCheckFailedException")
        self.items[key] = dict(Item)

    def get_item(self, Key):
        item = self.items.get((Key["pk"], Key["sk"]))
        return {"Item": item} if item else {}

    def update_item(self, Key, ExpressionAttributeNames, ExpressionAttributeValues, **_):
        row = self.items[(Key["pk"], Key["sk"])]
        row["status"] = ExpressionAttributeValues[":s"]
        row["text"] = ExpressionAttributeValues[":t"]


@pytest.fixture
def wired(monkeypatch):
    t = FakeTable()
    state = {"steps": 7000, "hevy": LIFT}
    monkeypatch.setattr(runner, "make_fetch", lambda table, user="matthew": lambda s, a, b: state["hevy"] if s == "hevy" else [])
    monkeypatch.setattr(runner, "read_ramp", lambda table, date, user="matthew": RAMP)
    monkeypatch.setattr(runner.steps_resolver, "daily_steps", lambda date, fetch, derived=False: {"steps": state["steps"]})
    return t, state


NOW_UTC = datetime(2026, 10, 21, 2, 10, tzinfo=timezone.utc)  # 19:10 PDT on 2026-10-20


def test_runner_sends_once_per_day(wired):
    t, _ = wired
    sent = []
    first = runner.run(t, sent.append, NOW_UTC, 0)
    second = runner.run(t, sent.append, NOW_UTC, 0)
    assert first["send"] and not second["send"] and second["reason"] == "already_sent"
    assert len(sent) == 1
    assert t.items[(runner.LEDGER_PK, "STEPS_NUDGE#2026-10-20")]["status"] == "sent"
    assert (runner.LEDGER_PK, "EVAL#2026-10-20") in t.items  # the dead-man's food, stamped even when not sent


def test_runner_racing_claim_never_double_sends(wired):
    t, _ = wired
    t.put_item({"pk": runner.LEDGER_PK, "sk": "STEPS_NUDGE#2026-10-20"})
    sent = []
    assert runner.run(t, sent.append, NOW_UTC, 0)["reason"] == "already_sent" and not sent


def test_runner_off_day_and_ahead_send_nothing_but_stamp(wired):
    t, state = wired
    state["hevy"] = []
    sent = []
    assert runner.run(t, sent.append, NOW_UTC, 0)["reason"] == "off_day"
    state["hevy"], state["steps"] = LIFT, 12500
    assert runner.run(t, sent.append, NOW_UTC, 0)["reason"] == "ahead_of_pace"
    assert not sent and not t.items[(runner.LEDGER_PK, "EVAL#2026-10-20")]["send"]


def test_runner_outside_window_does_nothing(wired):
    t, _ = wired
    assert runner.run(t, lambda s: None, datetime(2026, 10, 20, 20, 0, tzinfo=timezone.utc), 0)["reason"] == "outside_window"
    assert not t.items


def test_runner_send_failure_is_recorded_not_raised(wired):
    t, _ = wired

    def boom(_):
        raise RuntimeError("ses down")

    assert runner.run(t, boom, NOW_UTC, 0)["reason"] == "send_failed"
    assert t.items[(runner.LEDGER_PK, "STEPS_NUDGE#2026-10-20")]["status"] == "failed"


# ── the dead-man ───────────────────────────────────────────────────────────────────────────────────────────────
class _Check:
    def __init__(self, name, cat, tier):
        self.ok_msg = self.fail_msg = None

    def ok(self, m):
        self.ok_msg = m

    def fail(self, m):
        self.fail_msg = m
        return self


class _QTable:
    def __init__(self, days):
        self.days = days

    def query(self, **_):
        return {"Items": [{"sk": f"EVAL#{d}"} for d in self.days]}


def _pt_now():
    return datetime(2026, 10, 23, 9, 0, tzinfo=PACIFIC)


def test_deadman_reds_when_a_completed_day_has_no_eval():
    red = nudge_ledger_qa.check_steps_nudge_liveness(_QTable(["2026-10-22"]), _Check, "t", _pt_now, armed_on="2026-10-20")[0]
    assert red.fail_msg and "2026-10-21" in red.fail_msg and "2026-10-20" in red.fail_msg
    green = nudge_ledger_qa.check_steps_nudge_liveness(
        _QTable(["2026-10-22", "2026-10-21", "2026-10-20"]), _Check, "t", _pt_now, armed_on="2026-10-20"
    )[0]
    assert green.ok_msg and not green.fail_msg


def test_deadman_pending_before_armed():
    early = lambda: datetime(2026, 10, 20, 9, 0, tzinfo=PACIFIC)  # noqa: E731
    assert nudge_ledger_qa.check_steps_nudge_liveness(_QTable([]), _Check, "t", early)[0].ok_msg.startswith("steps nudge pending")


def test_brief_line_is_failsoft_and_states_the_floor(monkeypatch):
    import logging

    from emails import brief_lines

    monkeypatch.setattr(runner, "read_ramp", lambda table, date, user="matthew": RAMP)
    assert brief_lines.steps_line(object(), DATE, logging.getLogger()) == "Steps today: floor 12,000, target 15,000"

    def boom(*a, **k):
        raise RuntimeError("ddb down")

    monkeypatch.setattr(runner, "read_ramp", boom)
    assert brief_lines.steps_line(object(), DATE, logging.getLogger()) is None
