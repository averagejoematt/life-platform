"""tests/test_kcal_floor_clamp_5794.py — the served calorie target is CLAMPED at the day's floor (owner ruling 2026-11-11, #5794).

The ruling (option A): a lifting day is never served under `nutrition.calories.floor_lifting_day_kcal` and every other
day never under `floor_any_day_kcal` (the rest-day floor; reused, not a new key). The clamp REPLACES the planned-day
`floor_warnings` entry `health.calorie_target._apply_day_type` stamped under R1 ("a warning, not a clamp"); it does not
sit beside it. The re-read rule: from the charter's `floor_clamp_reread.reread_on` (14 days after the ruling), a 14-day
loss rate under `decide_below_lb_per_wk` is a PENDING owner decision in `nutrition_critics.decisions_offered` — the
existing decision channel (get_deficit_sustainability and the plan's nutrition_critics block), never a new one.

Holds, each iterating its whole set and reporting every offender:
  1. every day type at the live charter serves at or above its floor, and a day under it is lifted to it exactly;
  2. no served day carries the retired warning (no `floor_warnings` key, no "a warning, not a clamp" text);
  3. the re-read decision fires only from day 14 and only under the charter rate, deduped against a logged decision;
  4. MUST-FAIL CONTROLS: the clamp switched off (the pre-ruling path) and the re-read's date or rate edge moved are
     each caught by the same checks.

FIXED CLOCK: every date is a literal handed to the code under test (`resolve(day)`, `inputs["window_end"]`); the platform
clock is replaced by a bomb so a path that reads it reds here instead of drifting (tests/test_wallclock_fixture_bombs_2376.py).
No AWS, no model.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

_REPO = pathlib.Path(__file__).resolve().parent.parent
for _p in (_REPO / "lambdas", _REPO):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from common import pacific_time  # noqa: E402
from health import (
    calorie_target as ct,  # noqa: E402
    nutrition_critics as nc,  # noqa: E402
)
from training import training_charter as tc  # noqa: E402

WEEK = [f"2026-11-{n:02d}" for n in range(16, 23)]  # a fixed Mon..Sun
LIFTING_DATES = set(WEEK[:5])
REREAD = tc.charter_value(nc.FLOOR_CLAMP_REREAD_PATH)
DAY_13, DAY_14, DAY_30 = "2026-11-24", "2026-11-25", "2026-12-11"  # counted from the ruling's effective date 2026-11-11


@pytest.fixture(autouse=True)
def _clock_bomb(monkeypatch):
    """The fixed clock: nothing under test may read the platform's 'today' (every date is passed in)."""

    def bomb(*_a, **_k):
        raise AssertionError("the wall clock was read: every date in this file is passed in")

    monkeypatch.setattr(pacific_time, "pacific_today", bomb)
    yield


def _floor(day_type):
    key = "floor_lifting_day_kcal" if day_type == "lifting" else "floor_any_day_kcal"
    return tc.charter_value(f"nutrition.calories.{key}")


def _clamp_offenders(resolve):
    """Every served day under its floor, every day under the floor not lifted to it exactly, every retired warning."""
    bad = []
    for d, t in [(d, "lifting" if d in LIFTING_DATES else "rest") for d in WEEK] + [(WEEK[0], x) for x in ct.DAY_TYPES]:
        r = resolve(d, day_type=t)
        floor, unclamped = _floor(t), r["base_kcal"] + r["uplift_kcal"]
        if r["kcal"] < floor:
            bad.append(f"{d} {t}: served {r['kcal']} under its {floor} floor")
        if unclamped < floor and (r["kcal"], r.get("floor_clamp_kcal")) != (floor, floor - unclamped):
            bad.append(f"{d} {t}: {unclamped} not clamped to {floor} exactly ({r['kcal']}, {r.get('floor_clamp_kcal')})")
        if "floor_warnings" in r or "a warning, not a clamp" in r["provenance"]:
            bad.append(f"{d} {t}: carries the retired planned-day floor warning")
    return bad


def test_the_charter_states_the_ruling():
    cal = tc.charter_value("nutrition.calories")
    assert (cal["floor_lifting_day_kcal"], cal["floor_any_day_kcal"]) == (1900, 1600)
    assert "floor_rest_day_kcal" not in cal, "the rest-day floor is floor_any_day_kcal, reused (one key, one number)"
    assert REREAD["effective_date"] == "2026-11-11" and REREAD["reread_on"] == DAY_14
    assert REREAD["decide_below_lb_per_wk"] == 3.0
    log = tc.charter_value("change_log")[-1]
    assert "#5794" in log["by"] and log["version"] == tc.charter_value("version")


def test_every_served_day_is_clamped_at_its_floor_and_carries_no_warning():
    assert not _clamp_offenders(ct.resolve), _clamp_offenders(ct.resolve)
    lift, rest = ct.resolve(WEEK[0], day_type="lifting"), ct.resolve(WEEK[5], day_type="rest")
    assert (lift["kcal"], rest["kcal"]) == (1900, 1600), "the live base sits under both floors: each day serves its floor"
    assert lift["floor_clamp_kcal"] > 0 and rest["floor_clamp_kcal"] > 0


def test_the_retired_warning_path_is_gone_from_the_resolver():
    src = (_REPO / "lambdas" / "health" / "calorie_target.py").read_text(encoding="utf-8")
    assert "floor_warnings" not in src and "a warning, not a clamp" not in src


def test_control_the_clamp_switched_off_is_caught(monkeypatch):
    """Must-fail: the pre-ruling path (no floor applied to the served day) reds the same check, on both day types."""
    monkeypatch.setattr(ct, "day_floor", lambda *_a, **_k: None)
    bad = _clamp_offenders(ct.resolve)
    assert any("lifting: served" in b for b in bad) and any("rest: served" in b for b in bad), bad


def _decisions(window_end, loss_lb_wk, already=()):
    inputs = {"window_end": window_end, "weight_trend_lb_wk": None if loss_lb_wk is None else -loss_lb_wk}
    out = nc.decisions_offered([], inputs, already_logged=list(already))
    return [d for d in out if d["trigger"]["id"] == nc.FLOOR_CLAMP_REREAD_ID]


def _reread_offenders():
    """The re-read rule over its edges: (window_end, 14-day loss, expected state or None)."""
    cases = [
        (DAY_13, 2.0, None),  # day 13: not yet
        (DAY_13, None, None),  # not yet due: an unread rate is not asked for
        (DAY_14, 2.0, "pending"),  # day 14, under 3.0
        (DAY_30, 2.99, "pending"),
        (DAY_14, 3.0, None),  # at the rate: no decision
        (DAY_14, 3.4, None),
        (DAY_14, None, "unevaluable"),  # due, rate unread: named, never a silent pass
        (None, 2.0, "unevaluable"),
    ]
    bad = []
    for end, loss, want in cases:
        got = _decisions(end, loss)
        state = got[0]["state"] if got else None
        if state != want or len(got) > 1:
            bad.append(f"window_end={end} loss={loss}: want {want}, got {[g['state'] for g in got]}")
    return bad


def test_the_reread_decision_fires_only_from_day_14_and_only_under_the_rate():
    assert not _reread_offenders(), _reread_offenders()
    (d,) = _decisions(DAY_14, 2.0)
    assert d["log_decision_payload"]["source"] == nc.DECISION_SOURCE
    assert d["trigger"]["values"] == {"loss_rate_14d_lb_wk": 2.0, "decide_below_lb_per_wk": 3.0, "reread_on": DAY_14, "window_end": DAY_14}
    assert any("1900" in o and "1600" in o for o in d["options"]), d["options"]


def test_a_logged_reread_decision_is_already_decided():
    (pending,) = _decisions(DAY_14, 2.0)
    row = {"source": nc.DECISION_SOURCE, "note": pending["log_decision_payload"]["note"], "date": DAY_14, "followed": True}
    (d,) = _decisions(DAY_30, 2.0, already=[row])
    assert d["state"] == "already_decided" and d["followed"] is True


def test_control_a_moved_reread_edge_is_caught(monkeypatch):
    """Must-fail: the same edge sweep reds when the rule reads a different date or rate than the charter's."""
    real = nc.charter_value
    for moved in ({"reread_on": DAY_13}, {"decide_below_lb_per_wk": 3.5}):
        rule = {**REREAD, **moved}
        monkeypatch.setattr(nc, "charter_value", lambda p, *a, _r=rule: _r if p == nc.FLOOR_CLAMP_REREAD_PATH else real(p, *a))
        assert _reread_offenders(), f"a re-read moved to {moved} was not caught"
    monkeypatch.setattr(nc, "charter_value", lambda p, *a: None if p == nc.FLOOR_CLAMP_REREAD_PATH else real(p, *a))
    assert {d["state"] for d in _decisions(DAY_14, 2.0)} == {"unevaluable"}, "an unreadable rule is named, never a pass"
