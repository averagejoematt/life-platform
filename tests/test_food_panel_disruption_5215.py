"""tests/test_food_panel_disruption_5215.py — the weekly food panel reads disruption records (#5215, epic #5094).

  1. ONE DISRUPTED DAY: a date inside an active record is typed `disrupted`, ahead of the routine-derived type; its
     neighbours keep theirs; the panel's code half grades it as the minimum viable day (the protein floor and the
     any-day calorie floor held) — not the four-feedings / fat / carbohydrate rubric — and still FAILS a day that
     breaks the minimum.
  2. NONE: no record (or none read) leaves the plan and its code grade exactly as before.
  3. OUTSIDE THE WEEK: a record whose dates miss the week is ignored.

No AWS, no AI: the records are built with `disruption.build_disruption_record`; the charter is the bundled file.
"""

from __future__ import annotations

import copy
import pathlib
import sys

import pytest

_REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "lambdas"))

from training import disruption, food_panel, panel_rubric, training_charter as tc  # noqa: E402

WEEK = "2026-10-19"
LIFTING = ["2026-10-19", "2026-10-20", "2026-10-21", "2026-10-22", "2026-10-23"]
OFF_DAY = "2026-10-21"


@pytest.fixture(autouse=True)
def _bundled_charter_only(monkeypatch):
    monkeypatch.delenv(tc.PRIVATE_ENV_VAR, raising=False)
    monkeypatch.setattr(tc, "_from_s3", lambda key: None)
    tc.reset_cache()
    yield
    tc.reset_cache()


def _record(start, until):
    return disruption.build_disruption_record(
        start_date=start, until=until, words="travelling", template="travel", recorded_at="2026-10-19T12:00:00Z"
    )


def _plan(records=None):
    return food_panel.build_food_plan(WEEK, planned_dates=LIFTING, disruption_records=records, case_id="x")


def _scores(plan):
    rubric = panel_rubric.load_rubric()
    return {s: {c: v["score"] for c, v in crit.items()} for s, crit in food_panel.prescore(plan, rubric).items()}


def test_one_disrupted_day_is_typed_ahead_of_the_routine_and_graded_as_the_minimum():
    plan = _plan([_record(OFF_DAY, OFF_DAY)])
    types = {d["date"]: d["day_type"] for d in plan["days"]}
    assert types[OFF_DAY] == "disrupted", types  # a planned lifting date, the record wins
    assert [t for dt, t in types.items() if dt != OFF_DAY].count("lifting") == 4
    assert next(d for d in plan["days"] if d["date"] == OFF_DAY)["disruption_template"] == "travel"
    # the minimum viable day: strip the full-day structure — the reduced rubric still holds it
    thin = copy.deepcopy(plan)
    day = next(d for d in thin["days"] if d["date"] == OFF_DAY)
    day.update(feedings=[{"when": "meal", "protein_g": 100}], split=dict(day["split"], fat_g=10, carb_g=20))
    r = food_panel.rules()
    assert food_panel.minimum_day_held(day, r) is True
    held = food_panel.plan_features(thin)
    assert food_panel.check_four_feedings(held)[0] == 10.0 and "minimum viable day" in food_panel.check_four_feedings(held)[1]
    assert food_panel.check_feedings_cover(held)[0] == 10.0 and food_panel.check_macro_floors(held)[0] == 10.0
    # the same thin day, typed as a full day, is what the full rubric refuses
    full = copy.deepcopy(thin)
    next(d for d in full["days"] if d["date"] == OFF_DAY)["day_type"] = "rest"
    fh = food_panel.plan_features(full)
    assert food_panel.check_four_feedings(fh)[0] < 10.0 and food_panel.check_macro_floors(fh)[0] < 10.0
    # and the minimum is still a bar: under the protein floor, the disrupted day fails
    day["split"] = dict(day["split"], protein_g=10)
    assert food_panel.minimum_day_held(day, r) is False
    assert food_panel.check_four_feedings(food_panel.plan_features(thin))[0] < 10.0


def test_no_record_leaves_the_plan_and_its_grade_unchanged():
    base = _plan()
    for records in ([], None):
        assert _plan(records) == base
        assert _scores(_plan(records)) == _scores(base)
    assert "disrupted" not in {d["day_type"] for d in base["days"]}


def test_a_record_outside_the_week_is_ignored():
    base = _plan()
    for rec in (_record("2026-10-12", "2026-10-18"), _record("2026-10-26", "2026-10-30")):
        plan = _plan([rec])
        assert plan == base
        assert _scores(plan) == _scores(base)
