"""tests/test_food_panel_5110.py — the food seats in the panel rubric harness (#5110, epic #5094).

What each test holds (each iterates its whole set and reports every offender):

  1. THE FOOD RUBRIC IS THE CHARTER'S FOOD PANEL: the food seats are exactly the charter's
     `nutrition.concession_ledger`, eight of them, 4-6 criteria each with a judge criterion; every CODE criterion
     names a check in `food_panel.CHECKS` and every check is used; each concession is readable.
  2. THE PLAN IS THE WIRE: `build_food_plan` produces the golden fixture's shape (every day the resolver's own
     fields), stamps the charter version, and reads the protein range and floors from the engines.
  3. THE GOOD WEEK GRADES A ON CODE ALONE; THE CONTROLS FAIL — the old flat constant with no protein structure
     above all; and the weekly mutations fail what the hand-built fixtures fail (two paths to each defect).
  4. THE BAR: overall A AND every seat 9 or better AND its concession NAMED — a seat with no named concession fails.
  5. BLINDED: the food judge's prompt names no engine, version, issue or record key.
  6. A PAUSED JUDGE: the code criteria stand, the judge criteria report unscored, nothing is fabricated.
  7. THE GATE CAN FAIL (mutation): a food check that stops discriminating reds the gate, naming the control.
  8. THE WEEKLY RUN without a food plan says so (degraded), never a silent training-only grade.

No live AI call and no AWS: the judge is a replay of `recorded_judge.json`; the charter is the bundled file.
"""

from __future__ import annotations

import copy
import importlib
import json
import pathlib
import sys

import pytest

_REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "lambdas"))
sys.path.insert(0, str(_REPO / "scripts"))
sys.path.insert(0, str(_REPO))

from health import macro_floors, protein_engine  # noqa: E402
from training import food_panel, panel_judge, panel_rubric, training_charter as tc  # noqa: E402

FIX = _REPO / "tests" / "fixtures" / "panel_golden_5072"
gate = importlib.import_module("panel_rubric_gate")
LIFTING = ["2026-10-19", "2026-10-20", "2026-10-21", "2026-10-22", "2026-10-23"]


@pytest.fixture(autouse=True)
def _bundled_charter_only(monkeypatch):
    monkeypatch.delenv(tc.PRIVATE_ENV_VAR, raising=False)
    monkeypatch.setattr(tc, "_from_s3", lambda key: None)
    tc.reset_cache()
    yield
    tc.reset_cache()


def _rubric():
    r = panel_rubric.load_rubric()
    assert r is not None, "config/panel_rubric.json unreadable"
    return r


def _case(name):
    return json.loads((FIX / f"{name}.json").read_text(encoding="utf-8"))


def _replay(reply, calls=None):
    def call(body):
        if calls is not None:
            calls.append(body)
        return {"content": [{"type": "text", "text": json.dumps(reply)}], "stop_reason": "end_turn", "usage": {}}

    return call


def _code_only(case, rubric):
    graded = panel_rubric.combine(food_panel.prescore(case, rubric), None, food_panel.view(rubric), food_panel.concession)
    return graded


def test_the_food_rubric_is_the_charters_food_panel_and_every_check_resolves():
    rubric = _rubric()
    seats = food_panel.view(rubric)["seats"]
    ledger = set(tc.charter_value(food_panel.LEDGER_PATH, {}) or {})
    problems = []
    if set(seats) != ledger or len(ledger) != 8:
        problems.append(f"food seats {sorted(seats)} != charter {food_panel.LEDGER_PATH} {sorted(ledger)}")
    if set(seats) & set(rubric["seats"]):
        problems.append(f"a food seat shares a key with a training seat: {sorted(set(seats) & set(rubric['seats']))}")
    used = set()
    for seat, spec in seats.items():
        crits = spec["criteria"]
        if not 4 <= len(crits) <= 6 or len({c["id"] for c in crits}) != len(crits):
            problems.append(f"{seat}: {len(crits)} criteria or a duplicate id")
        if not spec.get("school"):
            problems.append(f"{seat}: no school/role named")
        if not any(c["by"] == panel_rubric.BY_JUDGE for c in crits):
            problems.append(f"{seat}: no judge criterion")
        for c in crits:
            if c["by"] == panel_rubric.BY_CODE:
                used.add(c.get("check"))
                if c.get("check") not in food_panel.CHECKS:
                    problems.append(f"{seat}.{c['id']}: check {c.get('check')!r} is not in food_panel.CHECKS")
            elif c["by"] != panel_rubric.BY_JUDGE:
                problems.append(f"{seat}.{c['id']}: by={c['by']!r}")
        con = food_panel.concession(seat)
        if not con or not con.get("concedes") or not con.get("in_return"):
            problems.append(f"{seat}: no concession readable from the charter")
    if set(food_panel.CHECKS) - used:
        problems.append(f"checks no criterion uses: {sorted(set(food_panel.CHECKS) - used)}")
    n_code = sum(c["by"] == panel_rubric.BY_CODE for s in seats.values() for c in s["criteria"])
    n_judge = sum(c["by"] == panel_rubric.BY_JUDGE for s in seats.values() for c in s["criteria"])
    if n_code <= n_judge:
        problems.append(f"{n_code} code criteria vs {n_judge} judge criteria — the deterministic half must carry the panel")
    assert not problems, "\n".join(problems)


def test_the_food_plan_is_the_resolvers_wire():
    plan = food_panel.build_food_plan("2026-10-19", planned_dates=LIFTING, case_id="x")
    good = _case("food_good_week")
    problems = []
    if [set(d) for d in plan["days"]] != [set(d) for d in good["days"]] or len(plan["days"]) != food_panel.WEEK_DAYS:
        problems.append("the golden food week's day shape is not build_food_plan's")
    if set(plan) != set(good) - {"kind"}:
        problems.append(f"top-level keys differ: {sorted(set(plan) ^ (set(good) - {'kind'}))}")
    if plan["charter_version"] != tc.charter_version() or any(d["charter_version"] != tc.charter_version() for d in plan["days"]):
        problems.append("a day or the plan is not stamped with the charter version")
    if plan["protein"]["range_low"] != protein_engine.range_low():
        problems.append("the plan's protein range is not the protein engine's")
    if plan["floors"] != {m: macro_floors.floor_g(m) for m in ("fat", "carb", "fibre")}:
        problems.append("the plan's floors are not the macro floors")
    types = [d["day_type"] for d in plan["days"]]
    if types.count("lifting") != len(LIFTING) or types.count("rest") != food_panel.WEEK_DAYS - len(LIFTING):
        problems.append(f"days not typed from the planned dates: {types}")
    for d in plan["days"]:
        thr = tc.charter_value("nutrition.protein.feeding_threshold_g")
        if len(d["feedings"]) != tc.charter_value("nutrition.protein.feedings_per_day") or min(f["protein_g"] for f in d["feedings"]) < thr:
            problems.append(f"{d['date']}: feedings {d['feedings']}")
        if d["day_type"] == "lifting" and not any(f["when"] == food_panel.POST_SESSION for f in d["feedings"]):
            problems.append(f"{d['date']}: a lifting day with no post-session feeding")
    untyped = food_panel.build_food_plan("2026-10-19")
    if {d["day_type"] for d in untyped["days"]} != {"unknown"} or untyped["titration"] is not None:
        problems.append("with no plan read, days must be unknown (never a guessed rest day) and no titration read")
    assert not problems, "\n".join(problems)


def test_the_good_week_grades_a_and_every_control_fails_on_code_alone():
    rubric = _rubric()
    problems = []
    cases = gate.golden_cases(panel=gate.FOOD_PANEL)
    if sum(c["kind"] == gate.GOOD_KIND for c in cases) < 1 or sum(c["kind"] == gate.CONTROL_KIND for c in cases) < 2:
        problems.append(f"food golden cases: {[c['case_id'] for c in cases]}")
    for case in cases:
        graded = _code_only(case, rubric)
        if case["kind"] == gate.GOOD_KIND:
            low = {f"{s}.{c}": v["score"] for s, seat in graded["seats"].items() for c, v in seat["criteria"].items() if v["score"] < 9}
            if not graded["target_met"] or low:
                problems.append(f"{case['case_id']}: the good week misses on code alone: {low} {graded['overall']}")
        else:
            missed = panel_judge.failed_expectations(graded, case["expect_fail"])
            if missed:
                problems.append(f"{case['case_id']}: {missed}")
    old = _case("food_neg_old_constant")
    if {d["kcal"] for d in old["days"]} != {1500} or old["protein"] or any(d["feedings"] for d in old["days"]):
        problems.append("the old-constant control is no longer the flat 1,500 target with no protein structure")
    if _code_only(old, rubric)["overall"]["letter"] != "F":
        problems.append(f"the old constant grades {_code_only(old, rubric)['overall']} — it must be an F")
    assert not problems, "\n".join(problems)


def test_the_weekly_mutations_fail_what_the_hand_built_fixtures_fail():
    rubric = _rubric()
    good = _case("food_good_week")
    fixture_fails = sorted(
        tuple(sorted(c["expect_fail"])) for c in gate.golden_cases(panel=gate.FOOD_PANEL) if c["kind"] == gate.CONTROL_KIND
    )
    mutation_fails = sorted(tuple(sorted(must)) for _, must in food_panel.CONTROL_MUTATIONS.values())
    assert fixture_fails == mutation_fails, "the food fixtures and food_panel.CONTROL_MUTATIONS must cover the same defects"
    before = json.dumps(good, sort_keys=True)
    problems = [
        f"{c['case_id']}: {m}"
        for c in food_panel.negative_controls(good)
        if (m := panel_judge.failed_expectations(_code_only(c, rubric), c["expect_fail"]))
    ]
    assert json.dumps(good, sort_keys=True) == before, "negative_controls mutated the real food plan"
    assert not problems, "\n".join(problems)


def test_the_bar_needs_every_concession_named(monkeypatch):
    rubric = _rubric()
    good = _case("food_good_week")
    assert _code_only(good, rubric)["target_met"]
    gone = sorted(food_panel.view(rubric)["seats"])[0]
    real = food_panel.concession
    monkeypatch.setattr(food_panel, "concession", lambda seat: None if seat == gone else real(seat))
    graded = _code_only(good, rubric)
    assert not graded["target_met"] and graded["concessions_unnamed"] == [gone], graded["concessions_unnamed"]


def test_the_food_judge_is_blinded():
    rubric = _rubric()
    case = copy.deepcopy(_case("food_good_week"))
    case["titration"]["reason"] = "in the band: hold (titration@1.0.0, #5096)"
    body = food_panel.build_body(case, rubric, panel_judge.WEEKLY_ROUTE)
    volatile = " ".join(b["text"] for b in body["system"][1:]) + " " + json.dumps(body["messages"])
    forbidden = ("titration@", "#5096", "WEEK#", "charter nutrition", "provenance", tc.charter_version(), "food_good_week", "engine")
    leaks = [t for t in forbidden if t and t.lower() in volatile.lower()]
    assert not leaks, f"the food judge's prompt names: {leaks}"
    assert "DAY 1 (lifting)" in volatile and "post-session" in volatile and "weekly refit: hold" in volatile, volatile[:600]
    assert body["system"][0].get("cache_control"), "the food judge rides the cached charter block"


def test_a_paused_judge_leaves_the_code_criteria_and_fabricates_nothing(monkeypatch):
    from ai import budget_guard

    rubric = _rubric()
    monkeypatch.setattr(budget_guard, "allow", lambda feature: False)
    monkeypatch.setattr(budget_guard, "current_tier", lambda: 1)
    g = food_panel.grade_case(_case("food_good_week"), rubric)
    judge_ids = {f"{s}.{c['id']}" for s, cs in panel_rubric.judge_criteria(food_panel.view(rubric)).items() for c in cs}
    problems = []
    if g["judge"]["status"] != "paused" or not g["degraded"] or not any("paused" in r for r in g["degraded_reasons"]):
        problems.append(f"judge {g['judge']['status']} degraded={g['degraded']} {g['degraded_reasons']}")
    if set(g["unscored"]) != judge_ids:
        problems.append(f"unscored {sorted(g['unscored'])} != every food judge criterion")
    if any(v["by"] == panel_rubric.BY_JUDGE for seat in g["seats"].values() for v in seat["criteria"].values()):
        problems.append("a judge score appeared with no judge reply")
    if any(len(seat["criteria"]) == 0 for seat in g["seats"].values()):
        problems.append("a seat lost its code criteria")
    assert not problems, "\n".join(problems)


def test_the_gate_reds_when_a_food_check_stops_discriminating(monkeypatch):
    """Mutation proof: a band check that passes everything lets the old constant through on that criterion."""
    monkeypatch.setitem(food_panel.CHECKS, "week_in_band", lambda f: (10.0, "mutated: always in band"))
    code, lines = gate.run("recorded")
    assert code == 1, "\n".join(lines)
    assert any(ln.startswith("FAIL food_neg_old_constant") for ln in lines), lines
    assert any("energy_balance_metabolism.in_band" in ln for ln in lines), lines


def test_the_weekly_run_grades_the_food_plan_or_says_it_did_not():
    rubric = _rubric()
    good, food = _case("good_charter_plan"), _case("food_good_week")
    rec = json.loads((FIX / gate.RECORDED).read_text(encoding="utf-8"))["responses"]

    def call(body):
        reply = rec["food_good_week" if "FOOD PLAN UNDER REVIEW" in json.dumps(body["messages"]) else "good_charter_plan"]
        return {"content": [{"type": "text", "text": json.dumps(reply)}], "stop_reason": "end_turn", "usage": {}}

    kw = dict(week_start="2026-10-12", routines=good["routines"], constraint_block=good["constraint_block"], rubric=rubric, call=call)
    g = panel_judge.grade_committed_week("2026-10-18", food_plan=food, **kw)
    assert g["food"]["target_met"] and not g["food"]["degraded"], (g["food"]["degraded_reasons"], g["food"]["overall"])
    assert [c["control"] for c in g["food"]["controls"]] == list(food_panel.CONTROL_MUTATIONS)
    assert not any(c["missed"] for c in g["food"]["controls"]) and not any(c["target_met"] for c in g["food"]["controls"])
    none = panel_judge.grade_committed_week("2026-10-18", food_plan=None, **kw)
    assert none["food"] is None and none["degraded"] and any("food plan was not read" in r for r in none["degraded_reasons"])
    assert panel_judge.panel_item(none, "USER#matthew")["food"] is None
