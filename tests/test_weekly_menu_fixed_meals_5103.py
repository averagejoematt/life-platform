"""tests/test_weekly_menu_fixed_meals_5103.py — the weekly menu plans around a FIXED dinner (#5103, owner ruling 2026-10-26).

From the week of 2026-10-25 the owner eats a prepared meal-service dinner every day; the ruling ("Plan around the
Fuller dinner") makes the code-built menu treat it as a fixed feeding and fit only the rest of the day from the anchors.
The four feedings of 40 g+ stand: the dinner counts as one, the anchors build the others.

Holds (each test iterates its whole set and reports every offender):

  1. THE FIXED DINNER REDUCES WHAT THE ANCHORS GET: on every day it applies to, `targets.remaining` is the band, kcal and
     floors less the dinner's label values; the anchors' own kcal sit inside that remaining band; the day's totals are
     the anchors plus the dinner, and the week still fits with the fatty fish placed around it.
  2. THE FEEDING COUNT INCLUDES IT: the charter's feedings per day, exactly one of them fixed — the last (dinner),
     inside the window, carrying the dinner's label values and no anchor — the post-session feeding still on each
     lifting day, and the words say "log its printed label".
  3. A REMAINDER THAT CANNOT FIT IS A NAMED MISS: an oversized dinner leaves the day built, marked unfit, the fixed
     meal first in the misses and still on the menu at its full label (never shrunk or dropped); a dinner under the
     feeding threshold is a named feeding miss.
  4. ABSENT KEY = UNCHANGED: no `fixed_meals` key, None and [] give the same menu with no trace of a fixed feeding;
     a fixed row limited to some weekdays leaves every other day exactly as the no-fixed menu fits it.
  5. AN UNREADABLE ROW REFUSES THE MENU (`fixed_meal_unreadable`), each problem named — a fixed meal is never dropped.
  6. THE QUALITY ROWS AND THE FOOD PANEL'S PLAN CARRY IT with its nutrition; the panel's code checks score 10.
  7. THE KEY IS OWNER DATA: a PRIVATE twin key, never published, absent from the public charter, read from the twin.

The foods and the dinner are INVENTED placeholders (the repo is public; the owner's values live only in his twin).
No AWS, no clock (every date is fixed), no model.
"""

from __future__ import annotations

import copy
import json
import pathlib
import sys

import pytest

_REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "lambdas"))
sys.path.insert(0, str(_REPO / "tests"))

from health import food_quality as fq, weekly_menu as wm  # noqa: E402
from test_weekly_menu_5103 import ANCHORS, _cv, _plan  # noqa: E402 — the sibling's placeholder week and foods
from training import food_panel, panel_rubric, training_charter as tc  # noqa: E402

EVERY_DAY = list(wm.WEEKDAY_NAMES)
DINNER = {
    "id": "t_dinner",
    "label": "placeholder fixed dinner",
    "slot": "dinner",
    "kcal": 450,
    "protein_g": 42,
    "carb_g": 30,
    "fat_g": 15,
    "fibre_g": 10,
    "days": EVERY_DAY,
    "source": "invented test placeholder",
}


@pytest.fixture(autouse=True)
def _bundled_charter_only(monkeypatch):
    monkeypatch.delenv(tc.PRIVATE_ENV_VAR, raising=False)
    monkeypatch.setattr(tc, "_from_s3", lambda key: None)
    monkeypatch.setattr(tc, "_load_private", lambda: tc._from_env(tc.PRIVATE_ENV_VAR))
    tc.reset_cache()
    yield
    tc.reset_cache()


def _dinner(**over):
    return {**copy.deepcopy(DINNER), **over}


def _menu(fixed=None, anchors=None, **kw):
    raw = None if fixed is None else copy.deepcopy(fixed)
    return wm.build(_plan(), anchors_raw=copy.deepcopy(ANCHORS if anchors is None else anchors), fixed_meals_raw=raw, **kw)


def _fixed(day):
    return [f for f in day["feedings"] if f["when"] == wm.FIXED]


def _anchor_kcal(day):
    return round(sum(f["kcal"] for f in day["feedings"] if f["when"] != wm.FIXED), 1)


# ── 1. the fixed dinner reduces what the anchors get ─────────────────────────────────────────────────────────
def test_the_fixed_dinner_reduces_the_remaining_band_and_floors_and_the_week_still_fits():
    menu = _menu([_dinner()])
    problems = []
    if not (menu["built"] and menu["fits_all"] and menu["quality_met"]):
        problems.append(f"built {menu['built']} fits_all {menu.get('fits_all')} quality {menu.get('quality', {}).get('misses')}")
    for d in menu["days"]:
        t, rem = d["targets"], d["targets"].get("remaining")
        if rem is None:
            problems.append(f"{d['date']}: no remaining targets on a fixed-dinner day")
            continue
        want_band = [t["band"][0] - DINNER["kcal"], t["band"][1] - DINNER["kcal"]]
        if rem["band"] != want_band or rem["kcal"] != t["kcal"] - DINNER["kcal"] or rem["fixed_kcal"] != DINNER["kcal"]:
            problems.append(f"{d['date']}: remaining band {rem['band']} / kcal {rem['kcal']}, want {want_band}")
        for m, f in t["floors_g"].items():
            if rem["floors_g"][m] != max(0.0, f - DINNER[m]):
                problems.append(f"{d['date']}: remaining {m} floor {rem['floors_g'][m]}, want {f} - {DINNER[m]}")
        if rem["feedings"] != t["feedings"] - 1:
            problems.append(f"{d['date']}: the anchors build {rem['feedings']} feedings, want {t['feedings'] - 1}")
        if not rem["band"][0] <= _anchor_kcal(d) <= rem["band"][1]:
            problems.append(f"{d['date']}: the anchors' {_anchor_kcal(d)} kcal sit outside the remaining band {rem['band']}")
        if abs(d["totals"]["kcal"] - (_anchor_kcal(d) + DINNER["kcal"])) > 0.5:
            problems.append(f"{d['date']}: the totals {d['totals']['kcal']} are not the anchors plus the dinner")
    lo = _cv("nutrition.food_quality.fatty_fish.servings_per_week")[0]
    if menu["quality"][fq.FISH]["servings"] < lo or len(menu["quality"][fq.FISH]["days"]) != lo:
        problems.append(f"the fatty fish was not placed around the dinner: {menu['quality'][fq.FISH]}")
    assert menu["fixed_meals"][0]["id"] == DINNER["id"]
    assert not problems, "\n".join(problems)


# ── 2. the feeding count includes it ─────────────────────────────────────────────────────────────────────────
def test_the_feeding_count_includes_the_fixed_dinner_as_the_last_feeding():
    menu = _menu([_dinner()])
    n_feed, thr = _cv("nutrition.protein.feedings_per_day"), _cv("nutrition.protein.feeding_threshold_g")
    hours = _cv("nutrition.eating_window.eating_hours")
    problems = []
    for d in menu["days"]:
        feeds, fixed = d["feedings"], _fixed(d)
        if len(feeds) != n_feed or len(fixed) != 1:
            problems.append(f"{d['date']}: {len(feeds)} feedings with {len(fixed)} fixed (want {n_feed}, one fixed)")
            continue
        f = fixed[0]
        if feeds[-1] is not f or f["slot"] != "dinner" or f["fixed"]["id"] != DINNER["id"] or f["items"]:
            problems.append(f"{d['date']}: the fixed dinner is not the last, anchor-free feeding: {f}")
        if any(f[m] != DINNER[m] for m in wm.MACROS):
            problems.append(f"{d['date']}: the fixed feeding's values are not the dinner's label: {[f[m] for m in wm.MACROS]}")
        if not 0 <= f["window_offset_h"] < hours or f["window_offset_h"] != max(x["window_offset_h"] for x in feeds):
            problems.append(f"{d['date']}: the dinner sits at +{f['window_offset_h']} h, not the last place in the {hours} h window")
        if not d["checks"]["every_feeding_counts"] or any(x["protein_g"] < thr for x in feeds):
            problems.append(f"{d['date']}: a feeding under {thr} g: {[x['protein_g'] for x in feeds]}")
        posts = [x for x in feeds if x["when"] == wm.POST_SESSION]
        if (d["day_type"] == "lifting") != (len(posts) == 1):
            problems.append(f"{d['date']}: {len(posts)} post-session feeding(s) on a {d['day_type']} day")
        line = next(x for x in menu["lines"] if d["date"] in x)
        if "log its printed label" not in line or DINNER["label"] not in line:
            problems.append(f"{d['date']}: the words do not render the fixed dinner: {line}")
    assert not problems, "\n".join(problems)


def test_a_breakfast_slot_is_the_first_feeding_and_only_named_days_carry_a_fixed_row():
    weekend = ["Saturday", "Sunday"]
    menu = _menu([_dinner(id="t_breakfast", slot="breakfast", days=weekend, kcal=300, protein_g=40, carb_g=20, fat_g=10, fibre_g=5)])
    problems = []
    for d in menu["days"]:
        fixed = _fixed(d)
        if d["weekday"] in weekend and (len(fixed) != 1 or d["feedings"][0] is not fixed[0] or d["feedings"][0]["window_offset_h"] != 0):
            problems.append(f"{d['date']}: the fixed breakfast is not the first feeding: {[x['when'] for x in d['feedings']]}")
        if d["weekday"] not in weekend and (fixed or "remaining" in d["targets"]):
            problems.append(f"{d['date']}: a fixed row on a day its days do not name")
    assert menu["built"] and not problems, "\n".join(problems)


# ── 3. a remainder that cannot fit is a named miss ───────────────────────────────────────────────────────────
def test_a_remainder_the_anchors_cannot_fit_is_a_named_miss_and_the_dinner_is_never_dropped():
    big = _dinner(kcal=1400, protein_g=50, carb_g=100, fat_g=60, fibre_g=5)
    menu = _menu([big])
    problems = []
    if not menu["built"] or menu["fits_all"] or menu["reason_code"] != wm.DAY_UNFIT:
        problems.append(f"built {menu['built']} fits_all {menu.get('fits_all')} reason {menu.get('reason_code')}")
    for d in menu.get("days") or []:
        fixed = _fixed(d)
        if len(fixed) != 1 or fixed[0]["kcal"] != big["kcal"] or fixed[0]["protein_g"] != big["protein_g"]:
            problems.append(f"{d['date']}: the fixed dinner was shrunk or dropped: {fixed}")
        if d["fits"] or not d["misses"] or not d["misses"][0].startswith("after the fixed dinner"):
            problems.append(f"{d['date']}: the miss does not name the fixed dinner first: {d['misses']}")
        if d["totals"]["kcal"] < big["kcal"]:
            problems.append(f"{d['date']}: the day's totals {d['totals']['kcal']} leave the dinner out")
        if "DOES NOT FIT" not in next(x for x in menu["lines"] if d["date"] in x):
            problems.append(f"{d['date']}: the words do not say the day does not fit")
    unfit = {u["date"] for u in menu.get("unfit_days") or []}
    if unfit != {d["date"] for d in menu.get("days") or []}:
        problems.append(f"unfit_days {sorted(unfit)} is not every day")
    assert not problems, "\n".join(problems)


def test_a_dinner_under_the_feeding_threshold_is_a_named_feeding_miss():
    thr = _cv("nutrition.protein.feeding_threshold_g")
    menu = _menu([_dinner(protein_g=thr - 10)])
    problems = [
        f"{d['date']}: {d['misses']}"
        for d in menu["days"]
        if d["fits"] or d["checks"]["every_feeding_counts"] or not any("fixed dinner" in m and f"under {thr:g} g" in m for m in d["misses"])
    ]
    assert menu["built"] and not menu["fits_all"] and not problems, "\n".join(problems)


# ── 4. absent key = unchanged ────────────────────────────────────────────────────────────────────────────────
def test_no_fixed_meals_key_or_an_empty_list_is_the_menu_unchanged():
    def no_key(path):
        return None if path == wm.FIXED_PATH else _cv(path)

    a, b, c = _menu(), _menu([]), _menu(read=no_key)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True) == json.dumps(c, sort_keys=True)
    trace = [
        f"{d['date']}: {d['targets'].get('remaining')} {[f['when'] for f in d['feedings']]}"
        for d in a["days"]
        if "remaining" in d["targets"] or _fixed(d)
    ]
    assert a["fits_all"] and "fixed_meals" not in a and not trace, "\n".join(trace)


def test_a_fixed_row_on_some_days_leaves_every_other_day_exactly_as_before():
    no_fish = [x for x in ANCHORS if not x.get("fatty_fish")]  # no week-level placement: every day is fitted on its own
    weekend = ["Saturday", "Sunday"]
    before, after = _menu(anchors=no_fish), _menu([_dinner(days=weekend)], anchors=no_fish)
    changed = [
        b["date"]
        for b, x in zip(before["days"], after["days"])
        if b["weekday"] not in weekend and json.dumps(b, sort_keys=True) != json.dumps(x, sort_keys=True)
    ]
    assert not changed, f"days the fixed row does not name were refitted: {changed}"
    assert all(_fixed(x) for x in after["days"] if x["weekday"] in weekend)


# ── 5. an unreadable row refuses the menu ────────────────────────────────────────────────────────────────────
def test_an_unreadable_fixed_row_refuses_the_menu_with_each_problem_named():
    cases = {
        "no id": [_dinner(id=None)],
        "duplicate id": [_dinner(), _dinner(days=["Monday"])],
        "unreadable label value": [_dinner(kcal="x")],
        "fibre_g": [_dinner(fibre_g=-1)],
        "slot": [_dinner(slot="lunch")],
        "days": [_dinner(days=["Someday"])],
        "more than one fixed row": [_dinner(), _dinner(id="t_other", days=["Monday"])],
        "not a list": {"id": "t_dinner"},
    }
    problems = []
    for want, rows in cases.items():
        out = _menu(rows)
        named = " ".join(out.get("fixed_meal_problems") or [])
        if out.get("built") or out.get("reason_code") != wm.FIXED_MEAL_UNREADABLE or want not in named or "days" in out:
            problems.append(f"{want}: built {out.get('built')} reason {out.get('reason_code')} problems {named!r}")
    good, none = wm.parse_fixed_meals([_dinner(fibre_g=None, days=["sat", "Sunday"])])
    if none or good[0]["fibre_g"] is not None or good[0]["days"] != ["Saturday", "Sunday"]:
        problems.append(f"a null fibre or abbreviated days was not read: {good} {none}")
    assert not problems, "\n".join(problems)


def test_an_unknown_dinner_fibre_counts_as_none_and_is_named_unknown():
    menu = _menu([_dinner(fibre_g=None)])
    floor = _cv("nutrition.floors.fibre.floor_g")
    problems = []
    for d in menu["days"]:
        f, rem = _fixed(d)[0], d["targets"]["remaining"]
        if f["fibre_g"] != 0 or f["fixed"]["fibre_known"] or rem["fibre_unknown"] != [DINNER["id"]] or rem["floors_g"]["fibre_g"] != floor:
            problems.append(f"{d['date']}: unknown fibre not counted as none: {f['fibre_g']} {rem}")
        if "fibre unknown" not in next(x for x in menu["lines"] if d["date"] in x):
            problems.append(f"{d['date']}: the words do not say the dinner's fibre is unknown")
    plan_rows = [x for d in wm.food_plan(_plan(), menu)["days"] for x in d["feedings"] if x.get("fixed")]
    if not plan_rows or any(x["fibre_g"] is not None for x in plan_rows):
        problems.append(f"the panel's plan states a fibre the label table does not carry: {plan_rows[:1]}")
    assert not problems, "\n".join(problems)


# ── 6. the quality rows and the food panel's plan carry it ───────────────────────────────────────────────────
def test_the_quality_rows_and_the_food_panel_plan_carry_the_fixed_dinner_and_the_panel_scores_ten():
    plan = _plan()
    menu = wm.build(plan, anchors_raw=copy.deepcopy(ANCHORS), fixed_meals_raw=[_dinner()])
    graded = wm.food_plan(plan, menu)
    problems = []
    for row, d in zip(menu["quality"]["rows"], menu["days"]):
        fm = row.get("fixed_meals") or []
        if len(fm) != 1 or fm[0]["id"] != DINNER["id"] or fm[0]["kcal"] != DINNER["kcal"] or fm[0]["fibre_g"] != DINNER["fibre_g"]:
            problems.append(f"{row['date']}: the quality row does not carry the dinner: {fm}")
        if row["fibre_g"] != d["totals"]["fibre_g"]:
            problems.append(f"{row['date']}: the quality row's fibre {row['fibre_g']} is not the whole day's {d['totals']['fibre_g']}")
    for d in graded["days"]:
        fixed = [x for x in d["feedings"] if x.get("fixed")]
        if len(fixed) != 1 or any(fixed[0][m] != DINNER[m] for m in wm.MACROS) or fixed[0]["when"] != wm.FIXED:
            problems.append(f"{d['date']}: the panel's plan does not carry the dinner with its nutrition: {d['feedings']}")
    if graded["quality_days"] != menu["quality"]["rows"]:
        problems.append("the panel's quality rows are not the menu's")
    scores = food_panel.prescore(graded, panel_rubric.load_rubric())
    low = [f"{seat}.{cid}: {c['score']} ({c['evidence']})" for seat, cs in scores.items() for cid, c in cs.items() if c["score"] < 10]
    if not scores or low:
        problems.append("the food panel's code checks do not score 10 on the fixed-dinner menu:\n" + "\n".join(low))
    assert not problems, "\n".join(problems)


# ── 7. the key is owner data ─────────────────────────────────────────────────────────────────────────────────
def test_the_fixed_meals_key_is_owner_only_and_read_from_the_twin(monkeypatch):
    assert wm.FIXED_PATH in tc.PRIVATE_KEYS and wm.FIXED_PATH in tc.NEVER_PUBLISHED
    public = (_REPO / "config" / "training_charter.json").read_text(encoding="utf-8")
    assert f'"{wm.FIXED_PATH}"' not in public, "the public charter carries a fixed_meals key"
    example = json.loads((_REPO / "config" / tc.PRIVATE_EXAMPLE_BASENAME).read_text(encoding="utf-8"))
    shape = example[wm.FIXED_PATH][0]
    want = {"id", "label", "slot", "kcal", "protein_g", "carb_g", "fat_g", "fibre_g", "days", "source"}
    assert set(shape) == want and all(v in (None, []) for v in shape.values()), shape
    monkeypatch.setenv(tc.PRIVATE_ENV_VAR, json.dumps({wm.ANCHORS_PATH: ANCHORS, wm.FIXED_PATH: [DINNER]}))
    tc.reset_cache()
    out = wm.build(_plan())
    assert out["built"] and all(_fixed(d) for d in out["days"]), "the default read is the twin's fixed_meals"
    assert wm.FIXED_PATH not in json.dumps(tc.public_view())
