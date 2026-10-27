"""tests/test_grocery_travel_5104.py — the grocery list beside the weekly menu and the dated travel-kit prompt (#5104 N10).

Holds:

  1. THE GROCERY LIST IS RENDERED BESIDE THE MENU: `menu['lines']` carries the code-built list in words (one line per store
     section, `other` for an anchor with no section), with every item's servings and packages equal to `menu['grocery_list']`.
  2. A TRAVEL DAY IS NOT SHOPPED AT HOME: a menu day typed `travel` (the trip's dates) is left out of the home list, named in
     `grocery_travel_days` and in a line that points at the travel kit; the control (no travel day) lists it.
  3. THE PROMPT FIRES WITH THE TRIP DATES SET: the dated charter still yields ONE `due` prompt (the same fixed key) from the
     prompt date until `ready_by`, naming the dates and the kit read; before it and from `ready_by` the row is `ok` (the
     dead-man needs missing dates, so it never fires on a dated trip).
  4. THE MENU STAYS OWNER-ONLY: the optional `section` column rides the owner's anchor row only; the committed example documents it
     with a null.

The foods are INVENTED placeholders (the repo is public). No AWS, no clock (every date is passed in), no model.
"""

from __future__ import annotations

import copy
import datetime as _dt
import json
import os
import pathlib
import sys

import pytest

_REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "lambdas"))
sys.path.insert(0, str(_REPO))
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

import test_weekly_menu_5103 as base  # noqa: E402
from health import (
    travel_food as tf,  # noqa: E402
    weekly_menu as wm,  # noqa: E402
)
from training import (
    calibration_cadence as cc,  # noqa: E402
    training_charter as tc,  # noqa: E402
)


@pytest.fixture(autouse=True)
def _bundled_charter_only(monkeypatch):
    monkeypatch.delenv(tc.PRIVATE_ENV_VAR, raising=False)
    monkeypatch.setattr(tc, "_from_s3", lambda key: None)
    monkeypatch.setattr(tc, "_load_private", lambda: tc._from_env(tc.PRIVATE_ENV_VAR))
    tc.reset_cache()
    yield
    tc.reset_cache()


def _anchors(sectioned: bool):
    rows = copy.deepcopy(base.ANCHORS)
    if sectioned:
        for r in rows:
            r["section"] = "produce" if r["id"] in ("t_veg", "t_berry") else "protein" if r["id"] != "t_oil" else None
    return rows


# ── 1. the list in words ─────────────────────────────────────────────────────────────────────────────────────
def test_the_grocery_list_is_rendered_beside_the_menu_in_words():
    problems = []
    for sectioned in (False, True):
        menu = wm.build(base._plan(), anchors_raw=_anchors(sectioned))
        want = {g["item"]: g for g in menu["grocery_list"]}
        text = [ln for ln in menu["lines"] if ln.startswith("Grocery list")]
        if not want or not text:
            problems.append(f"sectioned={sectioned}: no list or no grocery line")
            continue
        sections = {ln.split(",")[1].split(" (")[0].strip() for ln in text}
        if sectioned and not {"produce", "protein", "other"} <= sections:
            problems.append(f"sectioned: sections {sections}")
        if not sectioned and sections != {"other"}:
            problems.append(f"unsectioned: sections {sections}")
        body = " ".join(text)
        for g in want.values():
            if f"{g['label']}: {g['servings']:g} x {g['serving']}" not in body:
                problems.append(f"{g['item']} missing or mis-stated in the lines")
        if all(g["section"] is None for g in want.values()) != (not sectioned):
            problems.append(f"sectioned={sectioned}: the list rows do not carry the section")
    assert not problems, problems


# ── 2. travel days ───────────────────────────────────────────────────────────────────────────────────────────
def _with_travel(date):
    plan = base._plan()
    for d in plan["days"]:
        if d["date"] == date:
            d["day_type"] = "travel"
    return wm.build(plan, anchors_raw=copy.deepcopy(base.ANCHORS))


def test_a_travel_day_is_not_shopped_at_home_and_points_at_the_kit():
    control = wm.build(base._plan(), anchors_raw=copy.deepcopy(base.ANCHORS))
    assert control["grocery_travel_days"] == [] and not any(ln.startswith("Travel days") for ln in control["lines"])
    cook = [d for d in control["days"] if d["service"] == wm.SERVICE_COOK and d.get("feedings")]
    assert cook, "the control has cook days"
    target = cook[0]["date"]
    menu = _with_travel(target)
    assert menu["built"] and menu["grocery_travel_days"] == [target]
    mine = {g["item"]: g["servings"] for g in menu["grocery_list"]}
    base_total = sum(g["servings"] for g in control["grocery_list"])
    assert sum(mine.values()) < base_total, "the travel day's servings are not bought at home"
    assert any(ln.startswith("Travel days not shopped here") and target in ln and "travel_kit" in ln for ln in menu["lines"])
    every = wm.grocery_list(menu, wm.parse_anchors(base.ANCHORS, 3)[0], which="all")
    assert sum(g["servings"] for g in every) < sum(
        g["servings"] for g in wm.grocery_list(control, wm.parse_anchors(base.ANCHORS, 3)[0], which="all")
    )


# ── 3. the dated prompt ──────────────────────────────────────────────────────────────────────────────────────
def test_the_prompt_fires_once_with_the_trip_dates_set_and_names_them():
    pol = tf.policy()
    ready, lead, retire = (
        _dt.date.fromisoformat(pol["ready_by"]),
        pol["prompt_days_before_ready"],
        _dt.date.fromisoformat(pol["retire_after"]),
    )
    due = ready - _dt.timedelta(days=lead)
    w = next(x for x in tc.charter_value("travel.windows") if x.get("label") == pol["window_label"])
    assert w.get("start") and w.get("end"), "the live charter's trip is dated"
    rows = {
        label: tf.calibration_row(day.isoformat())
        for label, day in (
            ("before", due - _dt.timedelta(days=1)),
            ("due", due),
            ("eve", ready - _dt.timedelta(days=1)),
            ("ready", ready),
            ("past", retire + _dt.timedelta(days=1)),
        )
    }
    got = {k: r["state"] for k, r in rows.items()}
    assert got == {"before": cc.OK, "due": cc.DUE, "eve": cc.DUE, "ready": cc.OK, "past": cc.OK}, got
    assert rows["due"]["prompt_key"] == rows["eve"]["prompt_key"] == cc.prompt_key(tf.CALIBRATION_KIND, due.isoformat())
    for k in ("due", "eve"):
        prompt = rows[k]["prompt"]
        assert w["start"] in prompt and w["end"] in prompt and ready.isoformat() in prompt and "travel_kit" in prompt, prompt
        assert not rows[k].get("alert"), "no dead-man on a dated trip"
    assert all(rows[k]["prompt"] is None for k in ("before", "ready", "past"))
    block = {"kinds": {tf.CALIBRATION_KIND: rows["due"]}}
    assert [r["kind"] for r in cc.prompts_due(block)] == [tf.CALIBRATION_KIND] and tf.CALIBRATION_KIND not in cc.deadman_kinds(block)


# ── 4. the owner-only column ─────────────────────────────────────────────────────────────────────────────────
def test_the_section_column_is_documented_with_a_null_in_the_committed_example_only():
    ex = json.loads((_REPO / "config" / "training_charter.private.example.json").read_text(encoding="utf-8"))
    row = ex["anchor_foods"][0]
    assert "section" in row and row["section"] is None
    assert "anchor_foods" not in tc.charter_value("nutrition") and tc.charter_value("anchor_foods") is None
