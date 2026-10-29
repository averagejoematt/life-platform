"""tests/test_weekly_menu_search_5103.py — the weekly menu's day search finds the day's BEST set, and the fatty fish
goes only where the day keeps its fit (#5103 search quality, #5105 fish placement; synthetic proof of 2026-10-29).

The proof found the local search (`_search_day`) stopping well short of the best set the anchors held for a day, and
the fish placement accepting a day that was already unfit, so the fish landed on the unfit days and made them worse.

Holds (each test iterates its whole set and reports every offender):

  1. A DAY THE LOCAL SEARCH CALLED UNFIT IS FOUND TO FIT: on a table and day where the local search alone stops at a
     miss (checked first, with the exact step switched off — the old behaviour), the fitter finds a fitting set by the
     exact search and says which search chose it.
  2. THE EXACT SEARCH IS THE OPTIMUM: on small seeded tables (with and without a fixed dinner and a required
     serving) `_exact_day` returns exactly the set a brute force over every serving count picks under the same total
     order — the least miss, then the distance, the servings and the ids.
  3. THE FISH GOES ONLY WHERE THE DAY KEEPS ITS FIT: with one unfit day in the week the fish lands on fitting days,
     still at the weekly low end; the old acceptance rule (patched back in) puts it on the unfit day — the mutation
     control that this test can see the defect.
  4. A SERVING NO DAY CAN TAKE IS HELD BACK AND NAMED: when every day the fish could go would fit worse with it, no day
     carries it, every day is as fit as its fish-free fit, and the quality miss names the short count and the reason.
  5. AN UNFIT DAY NAMES ITS MISSES and misses by no more than the local search alone; its search ran to completion.
  6. DETERMINISTIC: the same plan gives the same menu, and the exact set does not depend on the day's rotation.
  7. BOUNDED: a table the size of a real one builds a week inside a wall-clock bound and under the node budgets; a
     budget that runs out keeps the best set found, says so, and is never worse than the local search.

The foods are INVENTED placeholders (the repo is public; the owner's anchors live only in his twin). No AWS, no clock
(every date is fixed), no model.
"""

from __future__ import annotations

import copy
import itertools
import json
import pathlib
import random
import sys
import time

import pytest

_REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "lambdas"))
sys.path.insert(0, str(_REPO / "tests"))

from health import food_quality as fq, weekly_menu as wm  # noqa: E402
from test_weekly_menu_5103 import ANCHORS, _food, _plan  # noqa: E402 — the sibling's placeholder week and foods
from training import training_charter as tc  # noqa: E402

FISH_ID = "t_fish"
WEEKEND = (5, 6)  # the sibling plan lifts Monday-Friday: Saturday and Sunday are its rest days


@pytest.fixture(autouse=True)
def _bundled_charter_only(monkeypatch):
    monkeypatch.delenv(tc.PRIVATE_ENV_VAR, raising=False)
    monkeypatch.setattr(tc, "_from_s3", lambda key: None)
    monkeypatch.setattr(tc, "_load_private", lambda: tc._from_env(tc.PRIVATE_ENV_VAR))
    tc.reset_cache()
    yield
    tc.reset_cache()


def _read(path):
    return tc.charter_value(path)


def _dinner(kcal, protein_g, carb_g, fat_g, fibre_g, days=None):
    return {
        "id": "t_dinner",
        "label": "placeholder fixed dinner",
        "slot": "dinner",
        "kcal": kcal,
        "protein_g": protein_g,
        "carb_g": carb_g,
        "fat_g": fat_g,
        "fibre_g": fibre_g,
        "days": list(days or wm.WEEKDAY_NAMES),
        "source": "invented test placeholder",
    }


def _local_trap_table():
    """A placeholder table (found by a seeded search over invented foods) on which the local search stops one fibre
    shortfall away from a set that fits, on the weekend rest days under the placeholder dinner."""
    return [
        _food("s0", 120, 6, 0, 10, 0),
        _food("s1", 100, 3, 3, 14, 3),
        _food("s2", 180, 26, 4, 2, 0),
        _food("s3", 100, 0, 0, 10, 2),
        _food("s4", 110, 18, 1, 10, 0),
        _food("s5", 90, 30, 1, 0.5, 0),
        _food("s6", 25, 1, 14, 0.2, 5, max_per_day=4),
        _food("s7", 120, 3, 0, 10, 0),
    ]


def _fit(day_index, table, fixed_meals=(), **kw):
    pol = wm.policy(_read)
    anchors, _ = wm.parse_anchors(copy.deepcopy(table), pol["cap"])
    fixed, _ = wm.parse_fixed_meals(copy.deepcopy(list(fixed_meals)))
    return wm.fit_day(_plan()["days"][day_index], anchors, pol, day_index, _read, fixed_meals=fixed, **kw)


def _no_exact(*_a, **_k):
    return None, {"nodes": 0, "core_sets": 0, "complete": True}


def _miss(day):
    return wm._cost(day["totals"], day["targets"])[0]


def _fish_on(day):
    return sum(i["servings"] for f in day.get("feedings") or [] for i in f["items"] if i["item"] == FISH_ID)


# ── 1. a day the local search called unfit is found to fit ───────────────────────────────────────────────────
def test_a_day_the_local_search_called_unfit_is_found_to_fit(monkeypatch):
    dinner = [_dinner(550, 55, 40, 18, 6)]
    problems = []
    with monkeypatch.context() as m:
        m.setattr(wm, "_exact_day", _no_exact)  # the old behaviour: the local search alone
        for i in WEEKEND:
            old = _fit(i, _local_trap_table(), dinner)
            if old["fits"] or not old.get("feedings"):
                problems.append(f"precondition: day {i} fits on the local search alone ({old.get('misses')}): the trap is gone")
    for i in WEEKEND:
        new = _fit(i, _local_trap_table(), dinner)
        if not new["fits"]:
            problems.append(f"day {i}: a fitting set exists but the fitter calls the day unfit: {new['misses']}")
        if (new.get("search") or {}).get("method") != "exact" or not new["search"].get("complete"):
            problems.append(f"day {i}: the set was not the exact search's, or it stopped: {new.get('search')}")
    assert not problems, "\n".join(problems)


# ── 2. the exact search is the optimum ───────────────────────────────────────────────────────────────────────
def _seeded_case(seed):
    rnd = random.Random(seed)
    rows = [
        _food(
            f"b{i}",
            rnd.choice([30, 60, 90, 120, 150, 200, 260]),
            rnd.choice([0, 2, 8, 20, 28, 35]),
            rnd.choice([0, 4, 12, 30]),
            rnd.choice([0.5, 3, 9, 14]),
            rnd.choice([0, 2, 5, 8]),
            max_per_day=rnd.choice([1, 2, 2, 3]),
        )
        for i in range(6)
    ]
    with_dinner = seed % 2 == 1
    return rows, rnd.choice(range(7)), with_dinner, rnd


def test_the_exact_search_is_the_brute_force_optimum_on_small_tables():
    pol = wm.policy(_read)
    plan = _plan()
    checked, problems = 0, []
    for seed in range(40):
        rows, idx, with_dinner, rnd = _seeded_case(seed)
        anchors, _ = wm.parse_anchors(rows, pol["cap"])
        by_id = {a["id"]: a for a in anchors}
        ids = sorted(by_id)
        t = wm.day_targets(plan["days"][idx], _read)
        base = (500.0, 45.0, 40.0, 15.0, 6.0) if with_dinner else (0.0,) * len(wm.MACROS)
        need = {rnd.choice(ids): 1} if with_dinner else {}
        feedings = int(t["feedings"]) - (1 if with_dinner else 0)
        share = (float(t["kcal"]) - base[0]) / feedings
        cores = [
            c for c in wm.feeding_cores(anchors, float(t["feeding_threshold_g"]), pol["core_max"]) if wm._totals(c, by_id)["kcal"] <= share
        ]
        if not cores:
            continue
        pools = [cores] * feedings

        def key(counts):
            vec = tuple(a + b for a, b in zip(wm._vec(counts, by_id), base))
            row = tuple(counts.get(k, 0) for k in ids)
            return (*wm._cost_vec(vec, t), sum(row), row)

        brute = None
        for combo in itertools.product(*(range(int(by_id[k]["cap"]) + 1) for k in ids)):
            counts = {k: n for k, n in zip(ids, combo) if n}
            if any(counts.get(k, 0) < n for k, n in need.items()):
                continue
            k = key(counts)
            if (brute is None or k < brute) and wm._decompose(counts, pools) is not None:
                brute = k
        found, stats = wm._exact_day(pools, anchors, t, base, require=need)
        checked += 1
        got = key(wm._used(found[0], found[1])) if found is not None else None
        if got != brute or not stats["complete"]:
            problems.append(f"seed {seed}: exact {got} vs brute force {brute} ({stats})")
    assert checked >= 30 and not problems, f"{checked} checked\n" + "\n".join(problems)


# ── 3. the fish goes only where the day keeps its fit ────────────────────────────────────────────────────────
def _fish_offenders(menu, fish_free):
    """Days the fish placement made worse than their fish-free fit (a fitting day that stopped fitting included)."""
    bad = []
    for d, f in zip(menu["days"], fish_free["days"]):
        if f["fits"] and not d["fits"]:
            bad.append(f"{d['date']}: fits without the fish placement, not with it ({d['misses']})")
        if _miss(d) > _miss(f) + 1e-6:
            bad.append(f"{d['date']}: misses by {_miss(d)} with the fish placement, {_miss(f)} without")
    return bad


def _menus(fixed):
    no_fish = [a for a in ANCHORS if not a.get("fatty_fish")]
    menu = wm.build(_plan(), anchors_raw=copy.deepcopy(ANCHORS), fixed_meals_raw=copy.deepcopy(fixed))
    fish_free = wm.build(_plan(), anchors_raw=copy.deepcopy(no_fish), fixed_meals_raw=copy.deepcopy(fixed))
    return menu, fish_free


def test_the_fish_goes_only_to_days_that_keep_their_fit(monkeypatch):
    lo = _read("nutrition.food_quality.fatty_fish.servings_per_week")[0]
    fixed = [_dinner(900, 50, 100, 40, 5, days=["Tuesday"])]  # Tuesday alone cannot fit; the spread's first slot
    menu, fish_free = _menus(fixed)
    problems = _fish_offenders(menu, fish_free)
    unfit = [d["date"] for d in menu["days"] if not d["fits"]]
    if len(unfit) != 1:
        problems.append(f"precondition: want exactly the Tuesday unfit, got {unfit}")
    on_unfit = [d["date"] for d in menu["days"] if _fish_on(d) and not d["fits"]]
    if on_unfit:
        problems.append(f"fatty fish on an unfit day while fitting days were free: {on_unfit}")
    q = menu["quality"][fq.FISH]
    if q["servings"] != lo or len(q["days"]) != lo:
        problems.append(f"the fish count {q['servings']} on {q['days']} is not the weekly low end {lo} on fitting days")
    # Mutation control: the old acceptance (a day already unfit takes the fish whatever it costs) must be caught.
    with monkeypatch.context() as m:
        m.setattr(wm, "_keeps_fit", lambda before, cand: bool(cand.get("fits")) or (not before.get("fits") and bool(cand.get("feedings"))))
        old, _ = _menus(fixed)
    if not _fish_offenders(old, fish_free):
        problems.append("mutation control: the old placement rule was not caught by this test")
    assert not problems, "\n".join(problems)


# ── 4. a serving no day can take is held back and named ──────────────────────────────────────────────────────
def test_a_fish_serving_no_day_can_take_is_held_back_and_named():
    lo = _read("nutrition.food_quality.fatty_fish.servings_per_week")[0]
    fixed = [_dinner(800, 50, 100, 40, 5)]  # the weekdays fit only fish-free; the rest days miss
    menu, fish_free = _menus(fixed)
    problems = _fish_offenders(menu, fish_free)
    q = menu["quality"]
    fish = q[fq.FISH]
    if fish["servings"] >= lo:
        problems.append(f"precondition: the fish found {fish['servings']} day(s) after all: {fish['days']}")
    line = next((x for x in q["misses"] if x.startswith(fq.FISH)), "")
    if "held back" not in line or q["met"] or menu["quality_met"]:
        problems.append(f"the short fish count is not named with its reason: {q['misses']}")
    if "held back" not in menu["lines"][-1]:
        problems.append(f"the words do not carry the held-back reason: {menu['lines'][-1]}")
    assert not problems, "\n".join(problems)


# ── 5. an unfit day names its misses ─────────────────────────────────────────────────────────────────────────
def test_an_unfit_day_names_its_misses_and_misses_by_no_more_than_the_local_search(monkeypatch):
    fixed = [_dinner(800, 50, 100, 40, 5)]
    no_fish = [a for a in ANCHORS if not a.get("fatty_fish")]
    with monkeypatch.context() as m:
        m.setattr(wm, "_exact_day", _no_exact)
        local = {i: _fit(i, no_fish, fixed) for i in WEEKEND}
    problems = []
    for i in WEEKEND:
        d = _fit(i, no_fish, fixed)
        if d["fits"] or d["reason_code"] != wm.DAY_UNFIT:
            problems.append(f"precondition: day {i} fits ({d['reason_code']})")
            continue
        named = [x for x in d["misses"] if "kcal" in x or "_g " in x]
        if not named or not d["misses"][0].startswith("after the fixed dinner"):
            problems.append(f"day {i}: the misses are not named (fixed dinner first): {d['misses']}")
        if _miss(d) > _miss(local[i]) + 1e-6:
            problems.append(f"day {i}: misses by {_miss(d)}, more than the local search's {_miss(local[i])}")
        if not (d.get("search") or {}).get("complete"):
            problems.append(f"day {i}: the exact search did not run to completion: {d.get('search')}")
    assert not problems, "\n".join(problems)


# ── 6. deterministic ─────────────────────────────────────────────────────────────────────────────────────────
def test_the_menu_is_deterministic_and_the_exact_set_does_not_depend_on_the_rotation():
    fixed = [_dinner(550, 55, 40, 18, 6)]
    a = wm.build(_plan(), anchors_raw=_local_trap_table(), fixed_meals_raw=copy.deepcopy(fixed))
    b = wm.build(_plan(), anchors_raw=_local_trap_table(), fixed_meals_raw=copy.deepcopy(fixed))
    problems = [] if json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True) else ["the same plan gave two menus"]
    pol = wm.policy(_read)
    anchors, _ = wm.parse_anchors(_local_trap_table(), pol["cap"])
    meals, _ = wm.parse_fixed_meals(copy.deepcopy(fixed))
    day = _plan()["days"][WEEKEND[0]]
    shapes = set()
    for rotation in range(len(wm.WEEKDAY_NAMES)):
        d = wm.fit_day(day, anchors, pol, rotation, _read, fixed_meals=meals)
        if (d.get("search") or {}).get("method") != "exact":
            problems.append(f"rotation {rotation}: the day was not the exact search's ({d.get('search')})")
        shapes.add(json.dumps([d["feedings"], d["totals"]], sort_keys=True))
    if len(shapes) != 1:
        problems.append(f"the exact set moved with the starting rotation: {len(shapes)} different days")
    assert not problems, "\n".join(problems)


# ── 7. bounded ───────────────────────────────────────────────────────────────────────────────────────────────
def _real_size_table():
    """Twenty invented foods with the caps a real table carries (one or two a day), seeded so it never changes."""
    rnd = random.Random(5103)
    rows = []
    for i in range(20):
        kind = ("protein", "protein", "vegetable", "fat", "carb")[i % 5]
        if kind == "protein":
            row = (rnd.choice([90, 110, 130, 150, 180]), rnd.choice([18, 22, 26, 30]), rnd.choice([0, 1, 4]), rnd.choice([0.5, 2, 6]), 0)
        elif kind == "vegetable":
            row = (rnd.choice([25, 40, 60]), rnd.choice([1, 2, 3]), rnd.choice([5, 9, 14]), 0.4, rnd.choice([3, 5, 8]))
        elif kind == "fat":
            row = (rnd.choice([100, 120, 165]), rnd.choice([0, 3, 6]), rnd.choice([0, 3, 6]), rnd.choice([10, 14]), rnd.choice([0, 2, 3]))
        else:
            row = (
                rnd.choice([110, 150, 200]),
                rnd.choice([3, 5, 8]),
                rnd.choice([22, 30, 40]),
                rnd.choice([0.5, 2]),
                rnd.choice([2, 4, 7]),
            )
        rows.append(_food(f"r{i:02d}", *row, max_per_day=rnd.choice([1, 2])))
    rows[0]["fatty_fish"] = True
    return rows


def test_a_real_size_table_builds_inside_the_time_and_node_bounds(monkeypatch):
    fixed = [_dinner(600, 60, 45, 20, 5)]
    started = time.perf_counter()
    menu = wm.build(_plan(), anchors_raw=_real_size_table(), fixed_meals_raw=copy.deepcopy(fixed))
    took = time.perf_counter() - started
    problems = [] if menu["built"] else [f"not built: {menu.get('reason')}"]
    exact = [d["search"] for d in menu.get("days") or [] if (d.get("search") or {}).get("method") == "exact"]
    over = [s for s in exact if s["nodes"] > wm.EXACT_NODE_BUDGET or not s["complete"]]
    if over:
        problems.append(f"a day reached the node budget: {over}")
    if took > 20.0:  # the real twin's week builds in well under a second on a laptop; 20 s is the CI ceiling
        problems.append(f"the week took {took:.1f} s")
    # A budget that runs out keeps the best found, says so, and is never worse than the local search alone.
    trap = [_dinner(550, 55, 40, 18, 6)]
    with monkeypatch.context() as m:
        m.setattr(wm, "_exact_day", _no_exact)
        local = _fit(WEEKEND[0], _local_trap_table(), trap)
    monkeypatch.setattr(wm, "EXACT_NODE_BUDGET", 2)
    cut = _fit(WEEKEND[0], _local_trap_table(), trap)
    if (cut.get("search") or {}).get("complete") is not False:
        problems.append(f"a two-node budget ran to completion: {cut.get('search')}")
    if not any("node budget" in x for x in cut["misses"]):
        problems.append(f"the stopped search is not named: {cut['misses']}")
    if _miss(cut) > _miss(local) + 1e-6:
        problems.append(f"the stopped search ({_miss(cut)}) is worse than the local search ({_miss(local)})")
    assert not problems, "\n".join(problems)
