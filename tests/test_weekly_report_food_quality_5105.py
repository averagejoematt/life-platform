"""tests/test_weekly_report_food_quality_5105.py — the WEEKLY REPORT shows the food-quality targets' hit or miss (#5105).

#5105's first slice put the targets in the charter and made the weekly menu enforce them. The weekly report is the
owner-only PANEL# row the Monday panel grade writes; its real food plan had no foods, so the food-quality check read
"no menu on the plan - not checked" every week. Holds:

  1. THE WEEKLY PLAN CARRIES THE MENU: `panel_weekly_grade._menu_plan_or_plain` lays `weekly_menu.food_plan` over the
     plan when the menu builds, so the food panel checks fibre and fatty fish over real foods.
  2. A MENU THAT CANNOT BUILD (no anchor table) OR RAISES leaves the plain plan, named `checked: False`, never a pass.
  3. THE ROW SHOWS HIT OR MISS: `food_panel.quality_report` is the same `check_week` the menu reports with, reduced to
     numbers and names (no day rows, no tag words, no priorities text), and `row_summary` carries it as `quality`.
  4. A MISS IS A MISS: a pool with no fatty fish is `met: False` with the miss named.

The foods are INVENTED placeholders (the repo is public). No AWS, no clock, no model.
"""

from __future__ import annotations

import copy
import json
import os
import pathlib
import sys

import pytest

_REPO = pathlib.Path(__file__).resolve().parent.parent
os.environ.setdefault("S3_BUCKET", "test-bucket")  # mcp.config reads these at import
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
sys.path.insert(0, str(_REPO / "lambdas"))
sys.path.insert(0, str(_REPO / "tests"))
sys.path.insert(0, str(_REPO))

from health import food_quality as fq, weekly_menu as wm  # noqa: E402
from test_weekly_menu_5103 import ANCHORS, _plan  # noqa: E402 — the sibling's placeholder week and foods
from training import food_panel, training_charter as tc  # noqa: E402

from mcp import panel_weekly_grade as pwg  # noqa: E402


@pytest.fixture(autouse=True)
def _bundled_charter_only(monkeypatch):
    monkeypatch.delenv(tc.PRIVATE_ENV_VAR, raising=False)
    monkeypatch.setattr(tc, "_from_s3", lambda key: None)
    monkeypatch.setattr(tc, "_load_private", lambda: tc._from_env(tc.PRIVATE_ENV_VAR))
    tc.reset_cache()
    yield
    tc.reset_cache()


def _twin(monkeypatch, anchors):
    monkeypatch.setenv(tc.PRIVATE_ENV_VAR, json.dumps({wm.ANCHORS_PATH: copy.deepcopy(anchors)}))
    tc.reset_cache()


def test_the_weekly_plan_carries_the_menu_when_it_builds(monkeypatch):
    _twin(monkeypatch, ANCHORS)
    plan = pwg._menu_plan_or_plain(_plan())
    rep = food_panel.quality_report(plan)
    problems = []
    if not plan.get("quality_days"):
        problems.append("the weekly plan carries no quality_days (no menu laid over it)")
    if rep["checked"] is not True or rep["met"] is not True or rep["misses"] or rep["problems"]:
        problems.append(f"the week is not a quality hit: {rep}")
    if (rep["fatty_fish_per_week"] or {}).get("met") is not True or (rep["fibre_daily"] or {}).get("met") is not True:
        problems.append(f"fibre / fish not both met in the report: {rep}")
    assert not problems, "\n".join(problems)


def test_a_menu_that_cannot_build_or_raises_leaves_the_plain_plan_not_checked(monkeypatch):
    plain = _plan()
    problems = []
    out = pwg._menu_plan_or_plain(copy.deepcopy(plain))  # no owner-only twin: no anchor table, no menu
    if out.get("quality_days") or food_panel.quality_report(out)["checked"] is not False:
        problems.append("no anchor table, yet the plan claims a quality check")
    _twin(monkeypatch, ANCHORS)

    def boom(*a, **k):
        raise RuntimeError("fitter down")

    monkeypatch.setattr(wm, "build", boom)
    out = pwg._menu_plan_or_plain(copy.deepcopy(plain))
    if out != plain:
        problems.append("a raising menu changed the plan")
    rep = food_panel.quality_report(out)
    if rep["checked"] is not False or rep["met"] is not None or "not checked" not in rep["reason"]:
        problems.append(f"an unchecked plan must say so: {rep}")
    assert not problems, "\n".join(problems)


def test_a_pool_with_no_fatty_fish_is_a_named_miss_on_the_row(monkeypatch):
    _twin(monkeypatch, [a for a in ANCHORS if not a.get("fatty_fish")])
    rep = food_panel.quality_report(pwg._menu_plan_or_plain(_plan()))
    assert rep["checked"] and rep["met"] is False, rep
    assert any(m.startswith(fq.FISH) for m in rep["misses"]), rep["misses"]
    assert rep["fatty_fish_per_week"]["met"] is False and rep["fatty_fish_per_week"]["servings"] == 0


def test_the_stored_report_is_numbers_and_names_only(monkeypatch):
    _twin(monkeypatch, [{**a, "nutrient_tags": ["omega3"]} for a in ANCHORS])
    rep = food_panel.quality_report(pwg._menu_plan_or_plain(_plan()))
    blob = json.dumps(rep)
    problems = [k for k in ("rows", "tag_servings", "nutrient_tags", "omega3", "text") if k in blob]
    assert not problems, f"the PANEL# row would carry: {problems}"
    assert set(rep) == {"checked", "met", "fibre_daily", "fatty_fish_per_week", "misses", "problems"}, sorted(rep)


def test_the_row_summary_carries_the_quality_hit_or_miss(monkeypatch):
    _twin(monkeypatch, ANCHORS)
    rep = food_panel.quality_report(pwg._menu_plan_or_plain(_plan()))
    summary = food_panel.row_summary({"overall": {}, "seats": {}, "quality": rep})
    assert summary["quality"] == rep
    assert food_panel.row_summary(None) is None
