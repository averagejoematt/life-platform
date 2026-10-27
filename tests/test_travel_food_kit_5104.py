"""tests/test_travel_food_kit_5104.py — the travel food kit before the late-December trip (#5104 N10, epic #5092).

# premerge-gate: a repo-shape sweep — reads every module under lambdas/web and lambdas/emails for an import of the owner-only travel food kit

Holds (each test iterates its whole set and reports every offender):

  1. THE CHARTER carries the kit's dates and rulings (`nutrition.travel_food`): ready by mid-December, a prompt window
     before it, the maintenance-week ruling (R3), the meal-service ruling (R6), no excluded foods (R7), and a
     change_log line for the version that added it.
  2. THE DAY is built to the charter at the resolved target: every protein core clears the feeding threshold on its
     own, the day lands inside the calorie band at the protein floor with the charter's feeding count, every floor it
     misses is a stated warning (never hidden), it is deterministic, and a maintenance-size target closes every floor.
     An unresolved target is `built: False`, never a remembered number.
  3. THE GROCERY LIST is any menu's `buy` items, summed and rounded up to packages (a menu in the day shape from
     elsewhere — N9 — gets the same list); THE KIT is the `pack` items over the trip plus spare days.
  4. THE PLAYBOOK states the charter's numbers, and every protein sum it claims is true arithmetic over the items.
  5. THE REMINDER: `calibration_row` is ok before the window, due (one prompt, a fixed key) inside it, the dead-man from
     `ready_by` while the trip dates are unset, ok once they are set and ready_by has passed (a prompt before it) or the trip is past, unknown without a ready-by —
     every date derived from the charter's own values, no clock. Wired into `calibration_cadence.read`.
  6. DISRUPTION MODE reads the playbook on a travel template (active, or a travel window it offers), never on busy.
  7. THE MCP READ (`get_exercise_notes action='travel_kit'`) serves the kit and refuses a bad argument.
  8. OWNER-ONLY: no published (web) or email module imports the kit.
"""

from __future__ import annotations

import datetime as _dt
import math
import os
import pathlib
import re
import sys

_REPO = pathlib.Path(__file__).resolve().parent.parent
os.environ.setdefault("S3_BUCKET", "test-bucket")  # mcp.config reads these at import (the MCP read below)
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
sys.path.insert(0, str(_REPO / "lambdas"))
sys.path.insert(0, str(_REPO))

from health import calorie_target, travel_food as tf  # noqa: E402
from training import calibration_cadence as cc, disruption as dm  # noqa: E402
from training.training_charter import charter_value  # noqa: E402


def _resolved(day_type: str = "travel") -> int:
    r = calorie_target.resolve("2026-12-20", titration_reader=lambda week: None, day_type=day_type)
    assert r["kcal"] is not None, "the charter resolves a calorie target"
    return int(r["kcal"])


def _reader(**overrides):
    def read(dotted):
        return overrides[dotted] if dotted in overrides else charter_value(dotted)

    return read


def _undated(**overrides):
    """The live charter with the trip window's dates removed: the not-yet-dated branches (default length, prompt, dead-man)."""

    def read(dotted):
        if dotted in overrides:
            return overrides[dotted]
        v = charter_value(dotted)
        if dotted == "travel.windows":
            return [{**w, "start": None, "end": None} for w in v]
        return v

    return read


def _d(s: str) -> _dt.date:
    return _dt.date.fromisoformat(s)


# ── 1. the charter ──────────────────────────────────────────────────────────────────────────────────────────
def test_the_charter_carries_the_kit_dates_and_the_rulings():
    pol = tf.policy()
    problems = []
    ready = _d(pol["ready_by"])
    if not (ready.month == 12 and ready.day <= 15):
        problems.append(f"ready_by {ready} is not by mid-December")
    if not (isinstance(pol.get("prompt_days_before_ready"), int) and pol["prompt_days_before_ready"] > 0):
        problems.append("no positive prompt_days_before_ready")
    if _d(pol["retire_after"]) <= ready:
        problems.append("retire_after must follow ready_by")
    if pol.get("maintenance_week") is not True:
        problems.append("R3: the trip is a planned maintenance week")
    for key, words in (("maintenance_rule", "R3"), ("meal_service", "R6"), ("excluded_foods_rule", "R7")):
        if words not in str(pol.get(key)):
            problems.append(f"{key} does not cite {words}")
    labels = [w.get("label") for w in charter_value("travel.windows")]
    if pol.get("window_label") not in labels:
        problems.append(f"window_label {pol.get('window_label')!r} names no travel window {labels}")
    log = [e for e in charter_value("change_log") if "#5104" in str(e.get("what"))]
    if not log or log[-1]["version"] > charter_value("version"):
        problems.append("no change_log line for the version that added nutrition.travel_food")
    assert not problems, problems


# ── 2. the day ──────────────────────────────────────────────────────────────────────────────────────────────
def test_every_protein_core_clears_the_feeding_threshold_on_its_own():
    thr = charter_value("nutrition.protein.feeding_threshold_g")
    short = {c["name"]: g for c in tf.CORES if (g := sum(tf.ITEMS[k]["protein_g"] * n for k, n in c["items"].items())) < thr}
    assert not short, f"cores under the {thr} g threshold: {short}"
    assert len(tf.CORES) >= charter_value("nutrition.protein.feedings_per_day")


def test_the_travel_day_is_built_to_the_charter_at_the_resolved_target():
    kcal = _resolved()
    day = tf.travel_day(kcal)
    lo, hi = charter_value("nutrition.calories.prescribed_band_kcal")
    half = (hi - lo) / 2
    problems = []
    if not day["built"]:
        problems.append(day.get("reason"))
    tot = day["totals"]
    if not kcal - half <= tot["kcal"] <= kcal + half:
        problems.append(f"{tot['kcal']} kcal outside {kcal}±{half}")
    if tot["protein_g"] < charter_value("nutrition.protein.range_g.low"):
        problems.append(f"protein {tot['protein_g']} under the floor")
    if len(day["feedings"]) != charter_value("nutrition.protein.feedings_per_day"):
        problems.append("feeding count is not the charter's")
    thr = charter_value("nutrition.protein.feeding_threshold_g")
    problems += [f"{f['name']} {f['protein_g']} g under {thr}" for f in day["feedings"] if f["protein_g"] < thr]
    summed = {m: round(sum(f[m] for f in day["feedings"]), 1) for m in tf.MACROS}
    if summed != tot:
        problems.append(f"feedings sum {summed} != totals {tot}")
    for m in tf.FLOOR_MACROS:
        floor = charter_value(f"nutrition.floors.{m}.floor_g")
        warned = any(w.startswith(f"{m} ") for w in day["warnings"])
        if (tot[f"{m}_g"] < floor) != warned or day["checks"][f"{m}_at_floor"] == warned:
            problems.append(f"{m}: {tot[f'{m}_g']} g vs floor {floor} g, warned={warned} — a miss must be stated, a hit must not")
    assert not problems, problems
    assert tf.travel_day(kcal) == day, "the same target yields the same day"


def test_a_maintenance_size_target_closes_every_floor_and_spreads_the_sides():
    problems = []
    for kcal in (2000, 2400, 2800):
        day = tf.travel_day(kcal)
        if not all(day["checks"].values()) or day["warnings"]:
            problems.append(f"{kcal}: {day['checks']} {day['warnings']}")
        biggest = max(f["kcal"] for f in day["feedings"])
        if biggest > 0.45 * day["totals"]["kcal"]:
            problems.append(f"{kcal}: one feeding carries {biggest} of {day['totals']['kcal']} kcal")
    assert not problems, problems
    assert tf.travel_day(2400)["totals"] != tf.travel_day(2800)["totals"], "the target moves the day"


def test_no_target_is_no_day_never_a_remembered_number():
    assert tf.travel_day(None)["built"] is False
    assert tf.travel_day(1700, read=_reader(**{"nutrition.protein.range_g.low": None}))["built"] is False
    kit = tf.build(None)
    assert kit["grocery_list"] == {} and kit["travel_kit"]["food"] == []


# ── 3. the grocery list and the kit ─────────────────────────────────────────────────────────────────────────
def test_the_grocery_list_is_any_menus_buy_items_rounded_up_to_packages():
    a, b = tf.travel_day(_resolved()), tf.travel_day(2400)
    menu = [a, b, a]
    counts = tf.menu_counts(menu)
    out = tf.grocery_list(menu)
    lines = {ln["item"]: ln for sec in out.values() for ln in sec}
    expected = {k for k, n in counts.items() if n and tf.ITEMS[k]["where"] == "buy"}
    problems = []
    if set(lines) != expected:
        problems.append(f"items {sorted(lines)} != the menu's buy items {sorted(expected)}")
    for k, ln in lines.items():
        if ln["servings"] != round(counts[k], 2):
            problems.append(f"{k}: {ln['servings']} servings != {counts[k]}")
        if ln["packages"] != math.ceil(counts[k] / tf.ITEMS[k]["package"]["servings"] - 1e-9):
            problems.append(f"{k}: {ln['packages']} packages")
        if tf.ITEMS[k]["section"] not in out or ln not in out[tf.ITEMS[k]["section"]]:
            problems.append(f"{k} is not under its store section")
    # the N9 contract: a day from elsewhere in the same shape is listed the same way
    foreign = [{"feedings": [{"items": [{"item": "greek_yogurt", "servings": 3}]}]}]
    if tf.grocery_list(foreign) != {"dairy": [tf._line("greek_yogurt", 3)]}:
        problems.append("a foreign menu day is not listed")
    assert not problems, problems


def test_the_kit_packs_the_shelf_stable_items_for_the_trip_plus_spare_days():
    day = tf.travel_day(_resolved())
    spare = charter_value("nutrition.travel_food.spare_days")
    kit = tf.travel_kit([day] * 5, spare)
    counts = tf.menu_counts([day])
    got = {ln["item"]: ln["servings"] for ln in kit["food"]}
    want = {k: round(n * (5 + spare), 2) for k, n in counts.items() if tf.ITEMS[k]["where"] == "pack"}
    assert got == want and kit["equipment"] and kit["spare_days"] == spare


def test_the_whole_kit_sizes_to_the_trip_and_uses_the_maintenance_day_when_known():
    kit = tf.build(_resolved(), maintenance_kcal=2400, days=6)
    assert kit["trip_days"] == 6 and kit["menu_day"] == "maintenance-week day" and kit["tier"] == "owner_only"
    assert tf.build(_resolved())["maintenance_pending"], "no maintenance estimate is stated, never guessed"
    days, basis = tf.trip_days(_reader(**{"travel.windows": [{"label": "late December 2026", "start": "2026-12-20", "end": "2026-12-27"}]}))
    assert (days, "2026-12-20" in basis) == (8, True)
    assert tf.trip_days(_undated())[0] == charter_value("nutrition.travel_food.default_trip_days")
    live_days, live_basis = tf.trip_days()  # the live charter: owner ruling 2026-10-25, 20th-27th December (#5107)
    assert (live_days, "2026-12-20..2026-12-27" in live_basis) == (8, True)


# ── 4. the playbook ─────────────────────────────────────────────────────────────────────────────────────────
def test_the_playbook_states_the_charter_numbers_and_true_protein_sums():
    day = tf.travel_day(_resolved())
    pb = tf.playbook(day["targets"], day=day, maintenance_kcal=2400)
    text = "\n".join(r for s in pb for r in s["rules"])
    thr = charter_value("nutrition.protein.feeding_threshold_g")
    problems = []
    for needle in (
        f"at least {charter_value('nutrition.protein.range_g.low'):g} g",
        f"{charter_value('nutrition.protein.feedings_per_day')} feedings",
        f"{charter_value('nutrition.eating_window.eating_hours'):g}-hour eating window",
        f"{day['targets']['kcal']} kcal",
        "2400 kcal",
        "R6",
        "R7",
    ):
        if needle not in text:
            problems.append(f"missing {needle!r}")
    for label in (h["label"] for h in charter_value("habits.core")):
        if label not in text:
            problems.append(f"core habit {label!r} not named")
    # every "= N g" sum the playbook claims, recomputed from the items
    bag = sum(tf.ITEMS[k]["protein_g"] * n for k, n in tf.CORES[2]["items"].items())
    if f"= {bag:g} g protein" not in text or bag < thr:
        problems.append(f"the day-bag line does not state its true {bag} g or misses the threshold")
    m = re.search(r"A (\d+)-scoop shake in water \(([\d.]+) g\)", text)
    if not m or float(m.group(2)) != int(m.group(1)) * tf.ITEMS["whey"]["protein_g"] or float(m.group(2)) < thr:
        problems.append(f"the shake line is not a true whole feeding: {m and m.group(0)}")
    ex = re.search(r"e\.g\. (.+?) \+ (.+?) = ([\d.]+) g", text)
    by_label = {v["label"]: v["protein_g"] for v in tf.ITEMS.values()}
    if not ex or by_label[ex.group(1)] + by_label[ex.group(2)] != float(ex.group(3)) or float(ex.group(3)) < thr:
        problems.append(f"the fallback example is not a true sum over the threshold: {ex and ex.group(0)}")
    assert not problems, problems


# ── 5. the dated reminder ───────────────────────────────────────────────────────────────────────────────────
def test_the_reminder_is_due_before_mid_december_with_a_dead_man_and_no_clock():
    pol = tf.policy()
    ready, lead, retire = _d(pol["ready_by"]), pol["prompt_days_before_ready"], _d(pol["retire_after"])
    due = ready - _dt.timedelta(days=lead)
    rows = {}
    for label, day in (
        ("before", due - _dt.timedelta(days=1)),
        ("due", due),
        ("eve", ready - _dt.timedelta(days=1)),
        ("ready", ready),
        ("past", retire + _dt.timedelta(days=1)),
    ):
        rows[label] = tf.calibration_row(day.isoformat(), read=_undated())
    got = {k: r["state"] for k, r in rows.items()}
    assert got == {"before": cc.OK, "due": cc.DUE, "eve": cc.DUE, "ready": cc.MISSED_2, "past": cc.OK}, got
    assert rows["due"]["prompt_key"] == rows["eve"]["prompt_key"] == cc.prompt_key(tf.CALIBRATION_KIND, due.isoformat())
    assert "travel_kit" in rows["due"]["prompt"] and ready.isoformat() in rows["due"]["prompt"]
    assert rows["ready"]["alert"] and cc.deadman_alert(rows["ready"]) == rows["ready"]["alert"]
    assert rows["before"]["prompt"] is None and rows["past"]["prompt"] is None
    dated = _reader(**{"travel.windows": [{"label": pol["window_label"], "start": "2026-12-20", "end": "2026-12-27"}]})
    assert tf.calibration_row(ready.isoformat(), read=dated)["state"] == cc.OK, "dates set: the kit is sized, no dead-man"
    assert tf.calibration_row(due.isoformat(), read=dated)["state"] == cc.DUE, "dates set: the prompt still points at the kit (#5104)"
    assert tf.calibration_row(due.isoformat(), read=_reader(**{"nutrition.travel_food": {}}))["state"] == cc.UNKNOWN
    assert tf.calibration_row("not-a-day")["state"] == cc.UNKNOWN
    assert tf.calibration_row(ready.isoformat())["state"] == cc.OK, "the live charter's trip is dated (2026-10-25 ruling): no dead-man"


def test_the_cadence_block_carries_the_row_so_the_prompt_and_the_dead_man_ride_the_existing_paths(monkeypatch):
    from health import titration
    from training import fitness_tests, phase_after_may

    monkeypatch.setattr(cc, "table_readers", lambda table: {k: (lambda: []) for k in cc.KINDS})
    monkeypatch.setattr(fitness_tests, "calibration_row_from_table", lambda table, today: {"kind": "fitness_tests", "state": "ok"})
    monkeypatch.setattr(titration, "calibration_row_from_table", lambda table, today: {"kind": "nutrition_titration", "state": "ok"})
    monkeypatch.setattr(phase_after_may, "calibration_row", lambda today: {"kind": "post_may_plan", "state": "ok"})
    monkeypatch.setattr(tf, "_default_reader", _undated())
    pol = tf.policy()
    due = (_d(pol["ready_by"]) - _dt.timedelta(days=pol["prompt_days_before_ready"])).isoformat()
    block = cc.read(object(), due)
    assert block["kinds"][tf.CALIBRATION_KIND]["state"] == cc.DUE
    assert any(r["kind"] == tf.CALIBRATION_KIND for r in cc.prompts_due(block)), "the coach-event trigger sends it"
    block = cc.read(object(), pol["ready_by"])
    assert tf.CALIBRATION_KIND in cc.deadman_kinds(block), "the dead-man alert sends its fixed text"


# ── 6. disruption mode reads the playbook ───────────────────────────────────────────────────────────────────
def test_disruption_mode_carries_the_playbook_on_a_travel_template_only():
    rec = dm.build_disruption_record(start_date="2026-12-20", until="2026-12-27", words="trip", template="travel", recorded_at="x")
    busy = dm.build_disruption_record(start_date="2026-12-20", until="2026-12-27", words="busy", template="busy", recorded_at="x")
    window = {"label": "late December 2026", "start": "2026-12-20", "end": "2026-12-27"}
    on = dm.constraint("2026-12-22", [rec], [])
    offered = dm.constraint("2026-12-19", [], [], windows=[window])
    problems = []
    if not (on["food"] and on["food"]["playbook"] and on["food"]["offered_only"] is False):
        problems.append(f"active travel: {on['food']}")
    if not (offered["offer"]["template"] == "travel" and offered["food"] and offered["food"]["offered_only"] is True):
        problems.append(f"offered travel window: {offered['food']}")
    if dm.constraint("2026-12-22", [busy], [])["food"] is not None:
        problems.append("busy template carries the travel playbook")
    if dm.constraint("2026-10-01", [], [], windows=[window])["food"] is not None:
        problems.append("no mode and no offer carries the playbook")
    assert not problems, problems
    # the mode never restates a calorie number: it points at the day's resolved target
    assert on["food"]["playbook"][0]["rules"][0].startswith("the day's resolved target") and "training_day_fuel" in on["food"]["kcal"]


# ── 7. the MCP read ─────────────────────────────────────────────────────────────────────────────────────────
def test_the_mcp_action_serves_the_kit_and_refuses_a_bad_argument(monkeypatch):
    from mcp import tools_training_notes as ttn

    kcal = _resolved()
    monkeypatch.setattr(calorie_target, "resolve", lambda day, **kw: {"kcal": kcal, "source": "charter", "day_type": kw.get("day_type")})
    out = ttn.tool_get_exercise_notes({"action": "travel_kit", "maintenance_kcal": 2400, "trip_days": 4})
    assert out["trip_days"] == 4 and out["menu_day"] == "maintenance-week day" and out["calorie_target"]["source"] == "charter"
    assert out["grocery_list"] and out["travel_kit"]["food"] and out["playbook"] and out["reminder"]["kind"] == tf.CALIBRATION_KIND
    assert "error" in ttn.tool_get_exercise_notes({"action": "travel_kit", "maintenance_kcal": "lots"})
    assert "error" in ttn.tool_get_exercise_notes({"action": "travel_kit", "trip_days": -1})


def test_the_mcp_action_reads_the_5107_maintenance_estimate_when_no_argument_is_given(monkeypatch):
    """#5107 is on main: with no `maintenance_kcal` the kit sizes the maintenance day from health.maintenance_week's own
    estimate over the expenditure reconciliation; a non-actionable estimate leaves maintenance_pending with its reason."""
    from mcp import tools_nutrition, tools_training_notes as ttn

    kcal = _resolved()
    monkeypatch.setattr(calorie_target, "resolve", lambda day, **kw: {"kcal": kcal, "source": "charter", "day_type": kw.get("day_type")})
    rec = {"best_match": "model_measured", "best_match_actionable": True, "models": {"model_measured": {"kcal": 2400.4}}}
    monkeypatch.setattr(tools_nutrition, "expenditure_reconciliation", lambda end_date, **kw: rec)
    out = ttn.tool_get_exercise_notes({"action": "travel_kit"})
    assert out["menu_day"] == "maintenance-week day" and out["maintenance_pending"] is None
    assert out["maintenance_estimate"]["kcal"] == 2400 and "5107" in out["maintenance_estimate"]["source"]
    rec = {"best_match": "model_measured", "best_match_actionable": False, "models": {"model_measured": {"kcal": 2400}}}
    monkeypatch.setattr(tools_nutrition, "expenditure_reconciliation", lambda end_date, **kw: rec)
    out = ttn.tool_get_exercise_notes({"action": "travel_kit"})
    assert out["days"]["maintenance"] is None and "provisional" in out["maintenance_pending"]


# ── 8. owner-only ───────────────────────────────────────────────────────────────────────────────────────────
def test_no_published_or_email_module_imports_the_kit():
    pat = re.compile(r"\btravel_food\b")
    offenders = []
    for sub in ("lambdas/web", "lambdas/emails"):
        for root, _dirs, files in os.walk(_REPO / sub):
            for f in files:
                if f.endswith(".py") and pat.search((pathlib.Path(root) / f).read_text(encoding="utf-8")):
                    offenders.append(os.path.relpath(os.path.join(root, f), _REPO))
    assert not offenders, offenders
