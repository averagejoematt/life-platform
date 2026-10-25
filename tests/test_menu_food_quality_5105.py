"""tests/test_menu_food_quality_5105.py — the weekly menu's food-quality targets (#5105 N11, epic #5092).

Holds (each test iterates its set and reports every offender):

  1. THE TARGETS LIVE IN THE CHARTER: `nutrition.food_quality` reads the ONE fibre floor through a path (no second
     fibre number in the block), carries the fatty-fish weekly range labelled as a platform default pending the owner,
     and points the micronutrient priorities at the owner-only lab priorities row (#5111).
  2. A WEEK MEETS FIBRE + FISH: with a tagged fatty-fish anchor the menu places the range's low end on spread days, every
     day's fibre is at the floor, every day still fits, and the quality report says met.
  3. A POOL WITH NO FISH REPORTS THE MISS BY NAME: the menu is still built, `quality.misses` names fatty_fish_per_week
     with the reason, the words say MISSED, and the food panel's macro-floors check scores it down naming the same miss.
  4. THE NUMBERS MOVE WITH THE CHARTER: a re-versioned range is the count placed; an unreadable block is a named problem.
  5. THE PRIORITIES ROW RIDES THE REPORT: the week's servings of anchors whose nutrient_tags it names; no row, nothing
     weighted. The MCP read passes the row it reads.
  6. A PLAN WITHOUT A MENU is not quality-checked by the food panel, and says so (its score is unchanged).
  7. THE ROW SHAPE IS DOCUMENTED in the committed private example (nulls only).

The foods are INVENTED placeholders (the repo is public). No AWS, no clock (every date is fixed), no model.
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
from test_weekly_menu_5103 import ANCHORS, WEEK, _cv, _plan  # noqa: E402 — the sibling's placeholder week and foods
from training import food_panel, panel_rubric, training_charter as tc  # noqa: E402

FISH_ID = "t_fish"
CHECK = "macro_floors_held"  # the food panel's check the quality targets fold into (#5105)


@pytest.fixture(autouse=True)
def _bundled_charter_only(monkeypatch):
    monkeypatch.delenv(tc.PRIVATE_ENV_VAR, raising=False)
    monkeypatch.setattr(tc, "_from_s3", lambda key: None)
    monkeypatch.setattr(tc, "_load_private", lambda: tc._from_env(tc.PRIVATE_ENV_VAR))
    tc.reset_cache()
    yield
    tc.reset_cache()


def _menu(anchors=None, **kw):
    return wm.build(_plan(), anchors_raw=copy.deepcopy(ANCHORS if anchors is None else anchors), **kw)


def _no_fish():
    return [a for a in ANCHORS if not a.get("fatty_fish")]


def _fish_servings(menu):
    return sum(i["servings"] for d in menu["days"] for f in d["feedings"] for i in f["items"] if i["item"] == FISH_ID)


def _macro_floors(plan):
    rubric = panel_rubric.load_rubric()
    scores = food_panel.prescore(plan, rubric)
    ids = {(seat, c["id"]) for seat, spec in food_panel.view(rubric)["seats"].items() for c in spec["criteria"] if c.get("check") == CHECK}
    return {f"{seat}.{cid}": c for seat, cs in scores.items() for cid, c in cs.items() if (seat, cid) in ids}


# ── 1. the targets live in the charter ───────────────────────────────────────────────────────────────────────
def test_the_quality_block_reads_the_one_fibre_floor_and_labels_the_fish_default():
    block = _cv(fq.POLICY_PATH)
    problems = []
    if block["fibre_daily"]["floor_path"] != "nutrition.floors.fibre.floor_g":
        problems.append(f"fibre floor_path is {block['fibre_daily']['floor_path']!r}, not the one fibre floor")
    numbers = [k for k, v in block["fibre_daily"].items() if isinstance(v, (int, float))]
    if numbers:
        problems.append(f"a second fibre number in the quality block: {numbers}")
    if "pending his ruling" not in block["fatty_fish"]["provenance"] or "platform default" not in block["fatty_fish"]["provenance"]:
        problems.append("the fatty-fish range is not labelled a platform default pending the owner's ruling")
    if "lab_priorities" not in block["micronutrient_priorities"]["source"]:
        problems.append("the micronutrient priorities do not read the lab priorities row")
    pol = fq.policy()
    if pol["fibre_floor_g"] != _cv("nutrition.floors.fibre.floor_g") or pol["problems"]:
        problems.append(f"the reader's fibre floor {pol['fibre_floor_g']} / problems {pol['problems']}")
    if pol["fish_range"] != tuple(block["fatty_fish"]["servings_per_week"]):
        problems.append(f"the reader's fish range {pol['fish_range']}")
    log = _cv("change_log")[-1]
    if log["version"] != _cv("version") or "#5105" not in log["what"]:
        problems.append(f"the last change_log line is not #5105's at the charter version: {log['version']}")
    assert not problems, "\n".join(problems)


# ── 2. a week meets fibre + fish ─────────────────────────────────────────────────────────────────────────────
def test_a_week_with_a_tagged_fish_meets_fibre_and_fish_and_every_day_still_fits():
    menu = _menu()
    lo, hi = _cv("nutrition.food_quality.fatty_fish.servings_per_week")
    floor = _cv("nutrition.floors.fibre.floor_g")
    q = menu["quality"]
    problems = []
    if not (menu["built"] and menu["fits_all"]):
        problems.append(f"the menu does not fit: {menu.get('unfit_days')}")
    if not (menu["quality_met"] and q["met"] and not q["misses"] and not q["problems"]):
        problems.append(f"quality not met: {q['misses']} {q['problems']}")
    n = _fish_servings(menu)
    if not lo <= n <= hi or n != q[fq.FISH]["servings"]:
        problems.append(f"{n} fatty-fish servings (report {q[fq.FISH]['servings']}), target {lo}-{hi}")
    fish_days = [d["date"] for d in menu["days"] if any(i["item"] == FISH_ID for f in d["feedings"] for i in f["items"])]
    if len(fish_days) != lo or fish_days != q[fq.FISH]["days"]:
        problems.append(f"fish on {fish_days}, want {lo} spread day(s) matching the report {q[fq.FISH]['days']}")
    idx = sorted(int(d[-2:]) for d in fish_days)
    if len(idx) > 1 and min(b - a for a, b in zip(idx, idx[1:])) < 2:
        problems.append(f"the fish days are bunched: {fish_days}")
    under = [f"{d['date']} {d['totals']['fibre_g']}" for d in menu["days"] if d["totals"]["fibre_g"] < floor]
    if under or not q[fq.FIBRE]["met"]:
        problems.append(f"fibre under the {floor} g floor: {under}")
    if "every target met" not in menu["lines"][-1]:
        problems.append(f"the words do not say the quality is met: {menu['lines'][-1]}")
    assert not problems, "\n".join(problems)


# ── 3. a pool with no fish ───────────────────────────────────────────────────────────────────────────────────
def test_a_pool_with_no_fatty_fish_reports_the_miss_by_name_and_the_panel_sees_it():
    menu = _menu(_no_fish())
    q = menu["quality"]
    problems = []
    if not menu["built"] or menu["quality_met"] or q["met"]:
        problems.append(f"built {menu['built']}, quality_met {menu.get('quality_met')}")
    if not any(m.startswith(fq.FISH) and "no anchor in the table is tagged fatty_fish" in m for m in q["misses"]):
        problems.append(f"the miss is not named: {q['misses']}")
    if "MISSED" not in menu["lines"][-1] or fq.FISH not in menu["lines"][-1]:
        problems.append(f"the words do not name the miss: {menu['lines'][-1]}")
    graded = _macro_floors(wm.food_plan(_plan(), menu))
    if not graded or any(c["score"] >= 10 or fq.FISH not in c["evidence"] for c in graded.values()):
        problems.append(f"the panel's macro-floors check did not score the miss: {graded}")
    good = _macro_floors(wm.food_plan(_plan(), _menu()))
    if any(c["score"] < 10 or "food quality: met" not in c["evidence"] for c in good.values()):
        problems.append(f"the control (fish placed) is not 10 with quality met: {good}")
    assert not problems, "\n".join(problems)


def test_a_menu_day_under_the_fibre_floor_is_a_named_miss_in_the_menu_and_the_panel():
    low_fibre = [{**a, "fibre_g": 0} for a in ANCHORS]
    menu = _menu(low_fibre)
    q = menu["quality"]
    assert menu["built"] and not q[fq.FIBRE]["met"] and any(m.startswith(fq.FIBRE) for m in q["misses"]), q["misses"]
    graded = _macro_floors(wm.food_plan(_plan(), menu))
    assert graded and all(c["score"] < 10 and "fibre" in c["evidence"] for c in graded.values()), graded


# ── 4. the numbers move with the charter ─────────────────────────────────────────────────────────────────────
def test_a_re_versioned_fish_range_is_the_count_placed_and_an_unreadable_block_is_named():
    def reader(rng):
        def read(path):
            if path == fq.POLICY_PATH:
                block = copy.deepcopy(_cv(path))
                block["fatty_fish"]["servings_per_week"] = rng
                return block
            return _cv(path)

        return read

    problems = []
    for rng in ([3, 3], [0, 0], [1, 2]):
        menu = _menu(read=reader(rng))
        if _fish_servings(menu) != rng[0] or not menu["quality_met"]:
            problems.append(f"range {rng}: placed {_fish_servings(menu)}, met {menu['quality_met']} {menu['quality']['misses']}")
    broken = _menu(read=lambda p: None if p == fq.POLICY_PATH else _cv(p))
    if not broken["built"] or broken["quality_met"] or not any(fq.POLICY_PATH in p for p in broken["quality"]["problems"]):
        problems.append(f"an unreadable block is not named: {broken.get('quality')}")
    assert not problems, "\n".join(problems)


# ── 5. the priorities row ────────────────────────────────────────────────────────────────────────────────────
def test_the_priorities_row_rides_the_report_with_the_tagged_servings():
    row = {"text": "weight omega3 foods this cycle", "source": "clinical PRIORITIES#current", "updated_at": "2026-10-20"}
    with_row = _menu(priorities=row)["quality"][fq.PRIORITIES]
    without = _menu()["quality"][fq.PRIORITIES]
    assert with_row["available"] and with_row["tagged_servings"] == {"omega3": _fish_servings(_menu())}, with_row
    assert with_row["text"] == row["text"] and "omega3" in with_row["line"]
    assert without["available"] is False and "nothing is weighted" in without["line"]


def test_the_mcp_read_passes_the_priorities_row_it_reads(monkeypatch):
    from training import lab_priorities

    from mcp import panel_weekly_grade as pwg, tools_training_notes as ttn

    monkeypatch.setattr(pwg, "read_routines", lambda start, end: [])
    monkeypatch.setattr(pwg, "read_food_plan", lambda week, routines: _plan())
    monkeypatch.setattr(lab_priorities, "read_priorities", lambda table: {"text": "omega3 first", "source": "test"})
    monkeypatch.setenv(tc.PRIVATE_ENV_VAR, json.dumps({wm.ANCHORS_PATH: ANCHORS}))
    tc.reset_cache()
    out = ttn.tool_get_exercise_notes({"action": "weekly_menu", "week_start": WEEK})
    assert out["built"] and out["quality"][fq.PRIORITIES]["text"] == "omega3 first", out.get("quality")


def test_a_failed_priorities_read_is_none_never_raised():
    from training import lab_priorities

    class Broken:
        def query(self, **kw):
            raise RuntimeError("no table")

    assert lab_priorities.read_priorities(Broken()) is None


# ── 6. a plan without a menu ─────────────────────────────────────────────────────────────────────────────────
def test_a_plan_without_a_menu_is_not_quality_checked_and_says_so():
    graded = _macro_floors(_plan())
    assert graded and all("no menu on the plan" in c["evidence"] for c in graded.values()), graded


# ── 7. the row shape ─────────────────────────────────────────────────────────────────────────────────────────
def test_the_private_example_documents_the_quality_tags_with_nulls_only():
    ex = json.loads((_REPO / "config" / "training_charter.private.example.json").read_text(encoding="utf-8"))
    row = ex["anchor_foods"][0]
    assert {"fatty_fish", "nutrient_tags"} <= set(row) and row["fatty_fish"] is None and row["nutrient_tags"] == []
    assert "fatty_fish" in ex["_README"] and "nutrient_tags" in ex["_README"]
    usable, _ = wm.parse_anchors([{**ANCHORS[0], "fatty_fish": "yes", "nutrient_tags": [" Omega3 ", 7]}], 3)
    assert usable[0]["fatty_fish"] is False and usable[0]["nutrient_tags"] == ["omega3"], "only a literal true tags a food"
