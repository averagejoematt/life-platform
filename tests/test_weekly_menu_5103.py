"""tests/test_weekly_menu_5103.py — the weekly menu built by code from the owner's anchor foods (#5103 N9, epic #5092).

Holds (each test iterates its whole set and reports every offender):

  1. A FIVE-LIFTING-DAY WEEK FITS BY CONSTRUCTION: every day inside its band (the resolved kcal +/- half the
     prescribed band's width), protein at the range low, the fat / carbohydrate / fibre floors met (a lifting day's
     carbohydrate line at the session carbohydrate), the charter's feeding count with every feeding at the threshold
     and the post-session one on each lifting day, all inside the eating window — every expected number read from the
     charter or the resolver, none typed here.
  2. THE FOOD PANEL'S CODE CHECKS SCORE 10 on the menu's plan (the plan's feedings replaced by the menu's grams).
  3. DETERMINISTIC: the same plan and table give the same menu; the rotation gives the week more than one day shape.
  4. FAILS LOUDLY WITH A NAMED REASON: no table, too few anchors, no feeding core, an unreadable charter block; a day
     the anchors cannot fit is built, marked unfit, and each miss named.
  5. R7's SWITCH: an anchor marked off_limits is never placed. R6: the cook days are the charter's, and the grocery
     list sums exactly the cook days' servings, rounded up to the anchor's own packages.
  6. THE NUMBERS MOVE WITH THE CHARTER: a re-versioned floor is the floor the fit and the check use.
  7. THE TABLE IS OWNER DATA: the default read is the owner-only twin's `anchor_foods` (a PRIVATE key, never on the
     published whitelist); the public charter names no anchor table key.
  8. THE MCP READ (`get_exercise_notes action='weekly_menu'`) builds the menu over the weekly food plan and refuses a
     week_start that is not a Monday.

The foods below are INVENTED placeholders (the repo is public; the owner's anchors live only in his twin).
No AWS, no clock (every date is fixed), no model.
"""

from __future__ import annotations

import copy
import json
import math
import os
import pathlib
import sys

import pytest

_REPO = pathlib.Path(__file__).resolve().parent.parent
os.environ.setdefault("S3_BUCKET", "test-bucket")  # mcp.config reads these at import (the MCP read below)
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
sys.path.insert(0, str(_REPO / "lambdas"))
sys.path.insert(0, str(_REPO))

from health import weekly_menu as wm  # noqa: E402
from training import food_panel, panel_rubric, training_charter as tc  # noqa: E402

WEEK = "2026-10-26"  # a Monday
LIFTING = ["2026-10-26", "2026-10-27", "2026-10-28", "2026-10-29", "2026-10-30"]


def _food(fid, kcal, p, c, f, fib, **extra):
    return {"id": fid, "label": f"placeholder {fid}", "serving": "1 test serving", "kcal": kcal, "protein_g": p, "carb_g": c,
            "fat_g": f, "fibre_g": fib, **extra}  # fmt: skip


ANCHORS = [
    _food("t_isolate", 100, 24, 0.5, 0.4, 0, package={"label": "test tub", "servings": 10}),
    _food("t_lean", 120, 26, 0, 1.5, 0),
    _food("t_white", 90, 20, 1, 0.5, 0),
    _food("t_fish", 200, 22, 0, 12, 0, fatty_fish=True, nutrient_tags=["omega3"]),
    _food("t_egg", 70, 6, 0.5, 5, 0),
    _food("t_veg", 25, 2, 5, 0.2, 4, max_per_day=6),
    _food("t_berry", 60, 1.5, 14, 0.7, 8),
    _food("t_seed", 60, 2, 5, 4, 5),
    _food("t_oil", 120, 0, 0, 14, 0),
    _food("t_nut", 165, 6, 6, 14, 3.5),
    _food("t_bean", 120, 8, 20, 0.5, 7),
]


@pytest.fixture(autouse=True)
def _bundled_charter_only(monkeypatch):
    monkeypatch.delenv(tc.PRIVATE_ENV_VAR, raising=False)
    monkeypatch.setattr(tc, "_from_s3", lambda key: None)
    monkeypatch.setattr(tc, "_load_private", lambda: tc._from_env(tc.PRIVATE_ENV_VAR))  # never a local twin on a laptop
    tc.reset_cache()
    yield
    tc.reset_cache()


def _cv(path):
    return tc.charter_value(path)


def _titration_record():
    """A held week at the charter's own target and band, under the current charter version (read, never typed)."""
    band = _cv("nutrition.calories.prescribed_band_kcal")
    return {
        "week": WEEK,
        "action": "hold",
        "step_kcal": 0,
        "kcal": _cv("nutrition.calories.target_kcal"),
        "band_low": band[0],
        "band_high": band[1],
        "position": "in",
        "reason_code": "in_band",
        "reason": "in the band: hold",
        "charter_version": _cv("version"),
        "inputs": {"steps_avg": _cv("steps.floor"), "steps_floor": _cv("steps.floor")},
    }


def _plan():
    rec = _titration_record()
    return food_panel.build_food_plan(WEEK, planned_dates=LIFTING, titration_reader=lambda week: rec, case_id="menu-test")


def _menu(anchors=None, **kw):
    return wm.build(_plan(), anchors_raw=copy.deepcopy(ANCHORS if anchors is None else anchors), **kw)


# ── 1. the five-lifting-day week fits ────────────────────────────────────────────────────────────────────────
def test_a_five_lifting_day_week_fits_every_day_by_construction():
    plan = _plan()
    menu = wm.build(plan, anchors_raw=copy.deepcopy(ANCHORS))
    assert menu["built"] and menu["reason_code"] is None, menu.get("reason")
    half = (_cv("nutrition.calories.prescribed_band_kcal")[1] - _cv("nutrition.calories.prescribed_band_kcal")[0]) / 2
    p_low, thr = _cv("nutrition.protein.range_g.low"), _cv("nutrition.protein.feeding_threshold_g")
    n_feed, hours = _cv("nutrition.protein.feedings_per_day"), _cv("nutrition.eating_window.eating_hours")
    pre, post = _cv("nutrition.training_day.pre_session"), _cv("nutrition.training_day.post_session")
    problems = []
    typed = {d["date"]: d for d in plan["days"]}
    if sorted(d for d, x in typed.items() if x["day_type"] == "lifting") != LIFTING:
        problems.append(f"the plan's lifting days are not the five planned: {typed}")
    for d in menu["days"]:
        tot, rd = d["totals"], typed[d["date"]]
        lifting = rd["day_type"] == "lifting"
        if not d["fits"] or d["misses"]:
            problems.append(f"{d['date']}: does not fit {d['misses']}")
        if not rd["kcal"] - half <= tot["kcal"] <= rd["kcal"] + half:
            problems.append(f"{d['date']}: {tot['kcal']} kcal outside {rd['kcal']} +/- {half}")
        if tot["protein_g"] < p_low:
            problems.append(f"{d['date']}: protein {tot['protein_g']} < {p_low}")
        carb_line = max(_cv("nutrition.floors.carb.floor_g"), (pre["carb_g"] + post["carb_g"]) if lifting else 0)
        for macro, line in (
            ("fat_g", _cv("nutrition.floors.fat.floor_g")),
            ("carb_g", carb_line),
            ("fibre_g", _cv("nutrition.floors.fibre.floor_g")),
        ):
            if tot[macro] < line:
                problems.append(f"{d['date']}: {macro} {tot[macro]} < {line}")
        feeds = d["feedings"]
        if len(feeds) != n_feed or any(f["protein_g"] < thr for f in feeds):
            problems.append(f"{d['date']}: feedings {[f['protein_g'] for f in feeds]} (want {n_feed} at {thr} g or more)")
        posts = [f for f in feeds if f["when"] == wm.POST_SESSION]
        if lifting and (len(posts) != 1 or posts[0]["protein_g"] < max(thr, post["protein_g"])):
            problems.append(f"{d['date']}: lifting day without one post-session feeding at {post['protein_g']} g")
        if not lifting and posts:
            problems.append(f"{d['date']}: a post-session feeding on a {rd['day_type']} day")
        if any(not 0 <= f["window_offset_h"] < hours for f in feeds):
            problems.append(f"{d['date']}: a feeding outside the {hours} h window {[f['window_offset_h'] for f in feeds]}")
        if abs(sum(f["kcal"] for f in feeds) - tot["kcal"]) > 0.5:
            problems.append(f"{d['date']}: the feedings do not add up to the day")
    assert menu["fits_all"] and not menu["unfit_days"]
    assert not problems, "\n".join(problems)


def test_the_food_panel_code_checks_score_ten_on_the_menu():
    plan = _plan()
    menu = wm.build(plan, anchors_raw=copy.deepcopy(ANCHORS))
    graded = wm.food_plan(plan, menu)
    rubric = panel_rubric.load_rubric()
    assert rubric is not None
    scores = food_panel.prescore(graded, rubric)
    low = [f"{seat}.{cid}: {c['score']} ({c['evidence']})" for seat, cs in scores.items() for cid, c in cs.items() if c["score"] < 10]
    assert scores and not low, "\n".join(low)
    menu_g = {d["date"]: [f["protein_g"] for f in d["feedings"]] for d in menu["days"]}
    assert all([f["protein_g"] for f in d["feedings"]] == menu_g[d["date"]] for d in graded["days"])
    assert plan["days"][0]["feedings"] != graded["days"][0]["feedings"] or plan is not graded  # a copy, the plan untouched
    assert _plan()["days"] == plan["days"]


# ── 3. deterministic, with variety ───────────────────────────────────────────────────────────────────────────
def test_the_menu_is_deterministic_and_the_week_is_not_one_day_repeated():
    a, b = _menu(), _menu()
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    shapes = {json.dumps([f["items"] for f in d["feedings"]], sort_keys=True) for d in a["days"]}
    assert len(shapes) > 1, "every day is the same menu: the rotation did nothing"


# ── 4. the named failures ────────────────────────────────────────────────────────────────────────────────────
def test_too_few_anchors_fails_loudly_with_a_named_reason(caplog):
    few = ANCHORS[: _cv("nutrition.weekly_menu.min_anchors") - 1]
    with caplog.at_level("WARNING", logger=wm.logger.name):
        out = _menu(few)
    assert out["built"] is False and out["reason_code"] == wm.TOO_FEW_ANCHORS, out
    assert str(_cv("nutrition.weekly_menu.min_anchors")) in out["reason"]
    assert wm.TOO_FEW_ANCHORS in caplog.text, "the refusal is logged, not silent"
    assert "days" not in out and "grocery_list" not in out, "no remembered or partial menu rides a refusal"


def test_every_other_refusal_names_its_reason():
    no_protein = [_food(f"t_side{i}", 60, 1, 10, 2, 3) for i in range(8)]
    broken_policy = dict(wm.policy())
    cases = {
        wm.NO_ANCHOR_TABLE: wm.build(_plan(), anchors_raw=[]),
        wm.NO_FEEDING_CORE: _menu(no_protein),
        wm.NO_PLAN: wm.build({"days": []}, anchors_raw=ANCHORS),
        wm.NO_POLICY: _menu(read=lambda p: None if p == wm.POLICY_PATH else _cv(p)),
    }
    problems = [
        f"{code}: got {out.get('built')} / {out.get('reason_code')}"
        for code, out in cases.items()
        if out.get("built") or out.get("reason_code") != code
    ]
    assert set(cases) | {wm.TOO_FEW_ANCHORS, wm.NO_CALORIE_TARGET, wm.DAY_UNFIT} == set(wm.REASON_CODES)
    assert broken_policy and not problems, "\n".join(problems)


def test_a_day_the_anchors_cannot_fit_is_built_marked_and_every_miss_named():
    fatty = [_food(f"t_fat{i}", 150, 25, 1, 10, 0) for i in range(6)] + [_food("t_fibre", 30, 1, 6, 0, 5)]
    out = _menu(fatty)
    assert out["built"] is True and out["fits_all"] is False and out["reason_code"] == wm.DAY_UNFIT, out.get("reason")
    assert out["unfit_days"] and all(u["misses"] for u in out["unfit_days"])
    for d in out["days"]:
        if not d["fits"]:
            assert d["reason_code"] == wm.DAY_UNFIT and any("kcal" in m or "_g" in m for m in d["misses"])
            assert "DOES NOT FIT" in next(line for line in out["lines"] if d["date"] in line)


def test_a_bad_anchor_row_is_set_aside_by_id_never_guessed():
    rows = [*copy.deepcopy(ANCHORS), {"id": "t_bad", "kcal": "x"}, {"label": "no id"}, copy.deepcopy(ANCHORS[0])]
    usable, problems = wm.parse_anchors(rows, 3)
    assert {a["id"] for a in usable} == {a["id"] for a in ANCHORS}
    assert len(problems) == 3 and any("t_bad" in p for p in problems) and any("duplicate" in p for p in problems)


# ── 5. R7's switch, R6's cook days and the grocery list ──────────────────────────────────────────────────────
def test_an_off_limits_anchor_is_never_placed():
    rows = copy.deepcopy(ANCHORS)
    rows[0]["off_limits"] = True  # the most protein-dense food: the fit would otherwise lean on it
    out = _menu(rows)
    placed = {i["item"] for d in out["days"] for f in d["feedings"] for i in f["items"]}
    assert out["built"] and "t_isolate" not in placed
    assert any("t_isolate" in p and "off_limits" in p for p in out["anchor_problems"])
    assert "t_isolate" in {i["item"] for d in _menu()["days"] for f in d["feedings"] for i in f["items"]}, "the control places it"


def test_the_grocery_list_is_the_cook_days_servings_in_packages():
    out = _menu()
    cook = set(_cv("nutrition.weekly_menu.cook_days"))
    assert {d["weekday"] for d in out["days"] if d["service"] == wm.SERVICE_COOK} == cook
    want: dict[str, float] = {}
    for d in out["days"]:
        if d["weekday"] in cook:
            for f in d["feedings"]:
                for i in f["items"]:
                    want[i["item"]] = want.get(i["item"], 0) + i["servings"]
    got = {g["item"]: g["servings"] for g in out["grocery_list"]}
    assert got == want and got
    pkg = {a["id"]: (a.get("package") or {}).get("servings") or 1 for a in ANCHORS}
    assert all(g["packages"] == math.ceil(g["servings"] / pkg[g["item"]]) for g in out["grocery_list"])
    every = wm.grocery_list(out, wm.parse_anchors(ANCHORS, 3)[0], which="all")
    assert sum(g["servings"] for g in every) > sum(g["servings"] for g in out["grocery_list"])


# ── 6. the numbers are the charter's ─────────────────────────────────────────────────────────────────────────
def test_a_re_versioned_floor_is_the_floor_the_fit_and_check_use():
    impossible = _cv("nutrition.floors.fibre.floor_g") * 10

    def read(path):
        return impossible if path == "nutrition.floors.fibre.floor_g" else _cv(path)

    out = _menu(read=read)
    assert out["built"] and not out["fits_all"]
    assert all(any(m.startswith("fibre_g") and f"{impossible:g}" in m for m in d["misses"]) for d in out["days"])
    assert all(d["targets"]["floors_g"]["fibre_g"] == impossible for d in out["days"])


# ── 7. the anchor table is owner data ────────────────────────────────────────────────────────────────────────
def test_the_default_table_is_the_owner_only_twins_and_never_public(monkeypatch):
    assert wm.ANCHORS_PATH in tc.PRIVATE_KEYS and wm.ANCHORS_PATH in tc.NEVER_PUBLISHED
    public = (_REPO / "config" / "training_charter.json").read_text(encoding="utf-8")
    assert f'"{wm.ANCHORS_PATH}"' not in public, "the public charter carries an anchor table key"
    assert wm.build(_plan())["reason_code"] == wm.NO_ANCHOR_TABLE, "no twin, no table: nothing is invented"
    monkeypatch.setenv(tc.PRIVATE_ENV_VAR, json.dumps({wm.ANCHORS_PATH: ANCHORS}))
    tc.reset_cache()
    out = wm.build(_plan())
    assert out["built"] and out["fits_all"] and out["tier"] == "owner_only"
    assert wm.ANCHORS_PATH not in json.dumps(tc.public_view())


# ── 8. the MCP read ──────────────────────────────────────────────────────────────────────────────────────────
def test_the_mcp_read_builds_the_menu_over_the_weekly_food_plan(monkeypatch):
    from mcp import panel_weekly_grade as pwg, tools_training_notes as ttn

    seen = {}
    monkeypatch.setattr(pwg, "read_routines", lambda start, end: seen.setdefault("routines", (start, end)) and [])
    monkeypatch.setattr(pwg, "read_food_plan", lambda week, routines: seen.setdefault("plan", week) and _plan())
    from training import lab_priorities

    monkeypatch.setattr(lab_priorities, "read_priorities", lambda table: None)  # #5105: no DDB read in a test
    monkeypatch.setenv(tc.PRIVATE_ENV_VAR, json.dumps({wm.ANCHORS_PATH: ANCHORS}))
    tc.reset_cache()
    out = ttn.tool_get_exercise_notes({"action": "weekly_menu", "week_start": WEEK})
    assert out["built"] and out["fits_all"] and seen == {"routines": (WEEK, "2026-11-01"), "plan": WEEK}
    bad = ttn.tool_get_exercise_notes({"action": "weekly_menu", "week_start": "2026-10-27"})
    assert "error" in bad and "Monday" in bad["error"]
    monkeypatch.setattr(pwg, "read_food_plan", lambda week, routines: None)
    assert "error" in ttn.tool_get_exercise_notes({"action": "weekly_menu", "week_start": WEEK})
