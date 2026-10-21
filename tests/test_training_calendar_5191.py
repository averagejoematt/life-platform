"""tests/test_training_calendar_5191.py — the per-date training calendar types the week lifting/rest (#5191, carrier for #5101).

Pure: every date is a fixed day key and `today` is passed, so no clock is read; no AWS, no AI.
"""

from __future__ import annotations

import pathlib
import sys

_REPO = pathlib.Path(__file__).resolve().parent.parent
for _p in (_REPO / "lambdas", _REPO):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import training.training_calendar as tc  # noqa: E402
from health import calorie_target as ct  # noqa: E402
from training import training_charter  # noqa: E402

WEEK = [f"2026-11-{n:02d}" for n in range(2, 9)]  # Mon 11-02 .. Sun 11-08
MON, TUE, WED, THU, FRI, SAT, SUN = WEEK
COUNT = training_charter.charter_value("split.lifting_days_per_wk")


def _types(cal):
    return [d["day_type"] for d in cal["days"]]


def test_the_count_is_the_charters_and_a_fresh_week_lays_it_on_the_nominal_weekdays():
    assert isinstance(COUNT, int) and COUNT == tc.lifting_days_per_wk()
    cal = tc.week_calendar(MON, [], today=MON)
    assert cal["state"] == "typed" and cal["dates"] == WEEK
    assert cal["typed_lifting_days"] == COUNT and cal["reaches_count"]
    assert cal["planned_dates"] == [MON, TUE, WED, FRI, SAT]  # program_structure.NOMINAL_LIFTING_DAYS
    assert _types(cal) == ["lifting", "lifting", "lifting", "rest", "lifting", "lifting", "rest"]


def test_a_rest_day_postponement_does_not_shift_the_typed_weeks_total():
    on_plan = tc.week_calendar(WED, [MON, TUE], today=WED)
    postponed = tc.week_calendar(WED, [MON], today=WED)  # Tuesday was a rest day: its session moves, it is not lost
    assert on_plan["typed_lifting_days"] == postponed["typed_lifting_days"] == COUNT
    assert _types(postponed).count("rest") == _types(on_plan).count("rest") == 7 - COUNT
    assert postponed["days"][1]["day_type"] == "rest" and "past" in postponed["days"][1]["basis"]
    assert postponed["remaining_sessions"] == COUNT - 1
    # two rest days in a row still leave the week its count while days remain
    assert tc.week_calendar(WED, [], today=WED)["typed_lifting_days"] == COUNT


def test_a_week_out_of_days_types_fewer_and_says_so():
    cal = tc.week_calendar(FRI, [], today=FRI)
    assert cal["planned_dates"] == [FRI, SAT, SUN] and not cal["reaches_count"]


def test_an_extra_session_is_credited_and_a_met_count_rests_the_remainder():
    cal = tc.week_calendar(SAT, [MON, TUE, WED, THU, FRI], today=SAT)
    assert cal["remaining_sessions"] == 0 and cal["planned_dates"] == [MON, TUE, WED, THU, FRI]
    six = tc.week_calendar(SUN, [MON, TUE, WED, THU, FRI, SAT], today=SUN)
    assert six["typed_lifting_days"] == 6 and six["days"][6]["day_type"] == "rest"


def test_unavailable_dates_get_no_session_and_unreadable_inputs_type_nothing():
    cal = tc.week_calendar(MON, [], today=MON, unavailable_dates=[TUE, WED])
    assert TUE not in cal["planned_dates"] and WED not in cal["planned_dates"]
    assert set(cal["planned_dates"]) == {MON, THU, FRI, SAT, SUN}
    none = tc.week_calendar(MON, None, today=MON)
    assert none["state"] == "unreadable" and none["planned_dates"] is None and "not read" in none["reason"]
    assert tc.credited_dates(None, MON) is None


def test_the_count_follows_the_charter(monkeypatch):
    monkeypatch.setattr(tc, "lifting_days_per_wk", lambda: 4)
    assert tc.week_calendar(MON, [], today=MON)["typed_lifting_days"] == 4
    monkeypatch.setattr(tc, "lifting_days_per_wk", lambda: None)
    cal = tc.week_calendar(MON, [], today=MON)
    assert cal["state"] == "unreadable" and "lifting_days_per_wk" in cal["reason"]


def _base(day):
    return ct.resolve(day)["kcal"]


def test_the_typed_weeks_mean_is_the_base_target():
    # one test over every scenario (a parametrize would be one census gate per case)
    offenders = []
    for name, credited, today in [("fresh", [], MON), ("postponed", [MON], WED), ("on_plan", [MON, TUE], WED), ("late_week", [], FRI)]:
        cal = tc.week_calendar(today, credited, today=today)
        blk = ct.plan_block(today, None, calendar=cal)
        lift = [d["kcal"] for d in blk["week_days"] if d["day_type"] == "lifting"]
        rest = [d["kcal"] for d in blk["week_days"] if d["day_type"] == "rest"]
        ok = (
            blk["day_type"] in ("lifting", "rest")
            and blk["day_type_basis"].startswith("per-date calendar")
            and "if_lifting_day" not in blk
            and blk["week_balance_held"]
            and abs(blk["week_mean_kcal"] - _base(today)) < 0.5
            and min(lift) > _base(today) > max(rest)
        )
        if not ok:
            offenders.append((name, blk["week_days"], blk["provenance"]))
    assert not offenders, offenders


def test_a_week_whose_rest_offset_hits_the_floor_is_named_unbalanced():
    # six lifts and one rest day: the one rest day would carry the whole offset; the resolver clamps it at its floor
    cal = tc.week_calendar(SUN, [MON, TUE, WED, THU, FRI, SAT], today=SUN)
    blk = ct.plan_block(SUN, None, calendar=cal)
    rest = blk["week_days"][6]
    floor = blk["floor_any_day_kcal"]
    assert floor is not None and _base(SUN) - 6 * ct.resolve(SUN, day_type="lifting")["uplift_kcal"] < floor  # the precondition
    assert (
        not blk["week_balance_held"]
        and rest["kcal"] == floor
        and "NOT held" in ct.resolve(SUN, day_type="rest", week_day_types=[d["day_type"] for d in blk["week_days"]])["provenance"]
    )


def test_an_unread_calendar_keeps_the_conditional_reading():
    blk = ct.plan_block(MON, None, calendar=tc.week_calendar(MON, None, today=MON))
    assert blk["day_type"] == "unknown" and "if_lifting_day" in blk and "not read" in blk["day_type_basis"]


def test_the_plan_engine_types_the_date_from_the_hevy_record():
    from training import plan_engine

    blk = plan_engine._effort_blocks(MON, [], [], {}, None, [])["training_day_fuel"]
    assert blk["day_type"] == "lifting" and blk["uplift_kcal"] > 0 and blk["calendar"]["lifting_days_per_wk"] == COUNT
    assert abs(blk["week_mean_kcal"] - blk["base_kcal"]) < 0.5
    # no Hevy record read: the untyped reading, never a guessed calendar
    assert plan_engine._effort_blocks(MON, [], [], {}, None)["training_day_fuel"]["day_type"] == "unknown"


def test_a_travel_window_keeps_its_dates_travel_and_off_the_laying():
    from training import disruption

    rec = disruption.build_disruption_record(start_date=MON, until=TUE, words="w", template="travel", recorded_at="2026-11-02T00:00:00Z")
    blk = tc.plan_fuel(MON, disruption.state([rec], MON), [])
    assert blk["day_type"] == "travel"
    by = {d["date"]: d["day_type"] for d in blk["week_days"]}
    assert by[MON] == by[TUE] == "travel" and list(by.values()).count("lifting") == COUNT
    # no rest day is left to pay the uplift (travel days hold the base): the resolver names the week unbalanced
    assert not blk["week_balance_held"] and blk["week_mean_kcal"] > blk["base_kcal"]
    lifting_day = next(d["date"] for d in blk["week_days"] if d["day_type"] == "lifting")
    types = [d["day_type"] for d in blk["week_days"]]
    assert "NOT held" in ct.resolve(lifting_day, day_type="lifting", week_day_types=types)["provenance"]


def test_the_food_panel_types_its_week_by_the_calendar(monkeypatch):
    from training import food_panel

    monkeypatch.setattr(tc, "credited_dates", lambda rows, day: [MON, WED, THU, FRI, SAT])
    plan = food_panel.build_food_plan(MON, planned_dates=[TUE], block_workouts=[], case_id="x")
    assert [d["day_type"] for d in plan["days"]] == ["lifting", "rest", "lifting", "lifting", "lifting", "lifting", "rest"]
    # no Hevy record: the committed routines' dates, as before
    assert [d["day_type"] for d in food_panel.build_food_plan(MON, planned_dates=[TUE], case_id="x")["days"]].count("lifting") == 1


def test_planned_dates_over_a_window_that_straddles_two_weeks():
    window = WEEK[3:] + ["2026-11-09", "2026-11-10", "2026-11-11"]  # Thu .. next Wed
    out = tc.planned_dates_over(window, [FRI, SAT, SUN], today="2026-11-12")
    assert out == [FRI, SAT, SUN]  # the past, typed by credit only
    assert tc.planned_dates_over(window, None, today=MON) is None
