"""tests/test_may_tracker_5073.py — the weekly May tracker (#5073, C6, epic #5067).

What this holds:
  * every target the row compares against is the CHARTER's (`charter_value`), never a copy;
  * every value is a labelled cell — measured / absent / read_failed with its source (ADR-104):
    no weigh-in, no tape, no steps, no fitness test is ever a 0;
  * each AMBER/RED trigger fires on its calibration-table condition and NAMES its lever, and an
    input that is not measured lands the trigger in `unevaluated`, never green;
  * the store round-trips (Decimal on the way in, a broken read is `read_failed`);
  * the nightly leg never raises into the pre-draft;
  * PRIVACY: no `lambdas/web/` or `lambdas/emails/` module imports the tracker (the target date and
    the band are owner-only by ruling — no May countdown on a published surface).

No clock is read by any asserted literal: every week is a fixed Monday and the projection is
derived from the same charter date the code reads (#4848).
"""

# premerge-gate: #5073: os.walk sweep of lambdas/web/ and lambdas/emails/ — no published-surface module imports the owner-only May tracker

from __future__ import annotations

import os
import re
import sys
from decimal import Decimal
from pathlib import Path

import pytest

os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lambdas"))
sys.path.insert(0, str(ROOT))

from training import (  # noqa: E402
    may_tracker as mt,  # noqa: E402
    plan_engine,
    program_structure,
)
from training.training_charter import charter_value  # noqa: E402

MON = "2026-10-12"
SUN = "2026-10-18"
FLOOR = float(charter_value("governing_goal.rate_band_lb_per_wk.floor"))
CEIL = float(charter_value("governing_goal.rate_band_lb_per_wk.ceiling"))
STEPS_FLOOR = int(charter_value("steps.floor"))
STEPS_TARGET = int(charter_value("steps.target"))
RUN_AT_LB = float(charter_value("gated_movements.running.gate_lb"))
WEIGHT = RUN_AT_LB + 60.0  # above the landing weight, so the band governs


def _week_rate(rate, counted=True):
    return {"rate_lb_wk": rate, "counted": counted, "status": "complete" if counted else "partial", "n_weighins": 6}


def _weight(rate, counted=True, weight=WEIGHT, guidance=None):
    return mt.weight_section(SUN, _week_rate(rate, counted), {"rate_lb_wk": rate, "provisional": False}, (SUN, weight), guidance)


def _days(counts, start=MON):
    return [{"date": mt.shift(start, i), "steps": c, "degraded": None} for i, c in enumerate(counts)]


def _sessions(e1rms, identity="T1", start="2026-08-01"):
    return [{"date": mt.shift(start, 3 * i), "best_1rm": v, "identity": identity} for i, v in enumerate(e1rms)]


def _row(weight=None, steps=None, anchors=None, volume=None, monday=MON, prior=None):
    return mt.build_week(
        monday,
        weight=weight or _weight(FLOOR + 0.2),
        waist=mt.waist_section([], mt.shift(monday, 6)),
        steps=steps or mt.steps_section(_days([STEPS_TARGET] * 7, monday)),
        anchors=anchors or mt.anchors_section({}, mt.shift(monday, 6)),
        volume=volume or mt.volume_section({"muscles": {}}),
        fitness=mt.fitness_section(None),
        prior=prior,
    )


# ── the calendar ────────────────────────────────────────────────────────────────


def test_week_bounds_are_monday_to_sunday():
    assert mt.week_bounds("2026-10-15") == (MON, SUN)
    assert mt.week_bounds(MON) == (MON, SUN)
    assert mt.week_bounds(SUN) == (MON, SUN)


def test_the_newest_completed_week_ends_before_today():
    assert mt.last_completed_monday("2026-10-19") == MON  # Monday: last week just completed
    assert mt.last_completed_monday(SUN) == "2026-10-05"  # Sunday: this week is not over yet


# ── weight: the band from the charter, both units, the projection ─────────────────


def test_the_band_is_the_charters_in_lb_and_percent_of_bodyweight():
    w = _weight(FLOOR + 0.2)
    band = w["band"]
    assert (band["floor_lb_wk"], band["ceiling_lb_wk"]) == (FLOOR, CEIL)
    assert band["floor_pct_bodyweight_per_wk"] == round(FLOOR / WEIGHT * 100, 2)
    assert w["rate_week"]["pct_bodyweight_per_wk"] == round((FLOOR + 0.2) / WEIGHT * 100, 2)
    assert w["band_position_week"] == "in"


def test_the_projection_reads_the_charter_target_date():
    w = _weight(FLOOR)
    t = w["target"]
    target = charter_value("governing_goal.target_date")
    assert t["target_date"] == target
    weeks = round(mt._days_between(SUN, target) / 7.0, 1)
    assert t["weeks_to_go"] == weeks
    assert t["projection"]["at_4wk_rate_lb"] == round(WEIGHT - FLOOR * weeks, 1)
    assert t["projection"]["at_band_ceiling_lb"] == round(WEIGHT - CEIL * weeks, 1)


def test_a_guidance_cap_below_the_ceiling_wins_and_only_its_state_is_carried():
    w = _weight(CEIL, guidance={"state": "measured", "cap_lb_wk": FLOOR})
    assert w["band"]["ceiling_lb_wk"] == FLOOR and w["band"]["guidance_capped"] is True
    assert w["guidance"] == {"state": "measured", "capped": True}


def test_an_uncounted_week_has_no_band_position():
    assert _weight(FLOOR - 1, counted=False)["band_position_week"] is None


def test_below_the_landing_weight_the_band_does_not_position_the_week():
    landing = plan_engine.owner_redlines.REDLINES["landing"]["deceleration_begins_lb"]
    w = _weight(FLOOR - 1, weight=float(landing) - 5)
    assert w["band_position_week"] is None
    trig = mt.evaluate_triggers({"weight": w})
    assert any(u["id"] == "rate_band" and "landing" in u["why"] for u in trig["unevaluated"])


def test_no_weigh_in_is_absent_never_zero():
    w = mt.weight_section(SUN, None, None, None)
    assert w["weight_lb"]["state"] == "absent" and w["weight_lb"]["value"] is None
    assert w["rate_week"]["state"] == "absent" and w["rate_week"]["value"] is None
    assert w["target"]["projection"] is None


def test_a_failed_weight_read_is_read_failed():
    w = mt.weight_section(SUN, None, None, None, read_error="ClientError: boom")
    assert w["state"] == "read_failed" and w["error"].startswith("ClientError")


# ── waist / steps / anchors / volume / fitness / running ───────────────────────────


def test_waist_is_absent_until_a_tape_exists_and_takes_the_latest_row_by_sunday():
    assert mt.waist_section([], SUN)["state"] == "absent"
    rows = [
        {"date": "2026-10-01", "waist_navel_in": Decimal("50.0")},
        {"date": "2026-10-10", "waist_navel_in": Decimal("49.0"), "waist_narrowest_in": Decimal("47.5")},
        {"date": "2026-10-25", "waist_navel_in": Decimal("48.0")},  # after Sunday — not this week's
        {"date": "2026-10-11", "chest_in": 50},  # no waist site
    ]
    w = mt.waist_section(rows, SUN)
    assert w["state"] == "measured" and w["date"] == "2026-10-10"
    assert w["value"] == {"waist_navel_in": 49.0, "waist_narrowest_in": 47.5}
    assert w["age_days"] == 8 and w["every_weeks"] == charter_value("calibration.tape_and_photos.every_weeks")


def test_steps_count_days_at_floor_and_target_and_never_zero_fill():
    counts = [STEPS_TARGET, STEPS_FLOOR, STEPS_FLOOR - 1, None, STEPS_TARGET + 1, STEPS_FLOOR, STEPS_FLOOR]
    s = mt.steps_section(_days(counts))
    assert s["state"] == "measured" and s["days_measured"] == 6
    assert s["days_at_floor"] == 5 and s["days_at_target"] == 2
    assert s["days_below_floor"] == [mt.shift(MON, 2)]
    assert s["days_without_a_count"] == [mt.shift(MON, 3)]
    assert s["value"] == round(sum(c for c in counts if c is not None) / 6)
    assert (s["floor"], s["target"]) == (STEPS_FLOOR, STEPS_TARGET)
    assert mt.steps_section(_days([None] * 7))["state"] == "absent"


def test_anchors_use_the_one_trend_and_cut_to_the_latest_identity():
    falling = [200.0] * 6 + [150.0] * 3
    series = {"bench": _sessions([300.0] * 9, identity="OLD") + _sessions(falling, identity="NEW", start="2026-09-01")}
    a = mt.anchors_section(series, SUN)
    bench = a["anchors"]["bench"]
    assert bench["identity"] == "NEW"
    assert bench["trend"] == plan_engine.anchor_e1rm_trend(falling)
    assert bench["down"] is True
    assert bench["tripped"] is plan_engine.anchor_drop_tripped(bench["trend"]["drop_pct"], bench["trend"]["sessions_below"])
    assert set(a["anchors"]) == set(program_structure.CORE_ANCHORS)
    assert a["anchors"]["squat"]["state"] == "absent"


def test_an_anchor_with_too_few_sessions_is_absent_with_the_reason():
    a = mt.anchors_section({"row": _sessions([100.0, 101.0])}, SUN)
    assert a["anchors"]["row"]["state"] == "absent" and "needs" in a["anchors"]["row"]["detail"]
    assert a["state"] == "absent"


def _ex(title, tid, n):
    return {"name": title, "template_id": tid, "working_sets": n}


LATERAL = ("Lateral Raise (Dumbbell)", "422B08F1")
FACE_PULL = ("Face Pull", "BE640BA0")
OHP = ("Overhead Press (Barbell)", "7B8D84E8")
INCLINE = ("Incline Bench Press (Dumbbell)", "07B38369")


def _vol(exercises, muscles=None):
    return {"muscles": muscles or {}, "exercise_sets": [_ex(*e) for e in exercises]}


def test_side_rear_delt_sets_by_movement_show_beside_the_charter_band():
    bands = charter_value("volume_priorities.sets_per_wk")
    # 5 lateral + 4 face-pull sets = 9 by movement, whatever the Shoulders bucket says
    v = mt.volume_section(_vol([(*LATERAL, 5), (*FACE_PULL, 4), (*OHP, 6)], {"shoulders": {"total_sets": 15.0}}))
    assert set(v["rows"]) == set(bands)
    srd = v["rows"]["side_rear_delts"]
    assert srd["state"] == "measured" and srd["value"] == 9 and srd["member_sets"] == [9]
    assert srd["band"] == list(bands["side_rear_delts"]) and srd["below_floor"] is True


def test_a_press_only_week_counts_zero_side_rear_delts():
    v = mt.volume_section(_vol([(*OHP, 8)], {"shoulders": {"total_sets": 8.0}}))
    srd = v["rows"]["side_rear_delts"]
    assert srd["state"] == "measured" and srd["value"] == 0 and srd["below_floor"] is True


def test_upper_chest_and_legs_arms_members_are_counted_with_their_bands():
    muscles = {"Quads": {"total_sets": 9.0}, "Hamstrings": {"total_sets": 3.0}, "Glutes": {"total_sets": 2.0}}
    v = mt.volume_section(_vol([(*INCLINE, 4)], muscles))["rows"]
    assert v["upper_chest"]["member_sets"] == [4]
    assert v["legs"]["member_sets"] == [9, 5] and v["legs"]["band"] == list(charter_value("volume_priorities.sets_per_wk")["legs"])
    assert v["arms"]["member_sets"] == [0, 0]


LAT_PULLDOWN = ("Lat Pulldown (Cable)", "LATPD000")


def test_5073_legs_and_arms_read_the_muscles_display_labels():
    """The live repro (2026-10-25): `muscles` is keyed by MUSCLES labels; legs/arms read [0, 0] before the bridge."""
    muscles = {"Quads": {"total_sets": 18}, "Biceps": {"total_sets": 13.5}, "Triceps": {"total_sets": 12}}
    muscles.update({"Hamstrings": {"total_sets": 6}, "Glutes": {"total_sets": 4}})
    rows = mt.volume_section(_vol([(*LAT_PULLDOWN, 5)], muscles))["rows"]
    assert rows["legs"]["member_sets"] == [18, 10]
    assert rows["arms"]["member_sets"] == [14, 12]  # 13.5 rounds half-even to 14
    assert rows["legs"]["value"] == 10


def test_5073_legs_and_arms_meeting_their_bands_are_not_below_floor():
    bands = charter_value("volume_priorities.sets_per_wk")
    muscles = {"Quads": {"total_sets": 18}, "Hamstrings": {"total_sets": 6}, "Glutes": {"total_sets": 6}}
    muscles.update({"Biceps": {"total_sets": 13}, "Triceps": {"total_sets": 12}})
    rows = mt.volume_section(_vol([], muscles))["rows"]
    for g in ("legs", "arms"):
        assert min(rows[g]["member_sets"]) >= bands[g][0]
        assert rows[g]["below_floor"] is False and rows[g]["gap_to_floor"] == 0


def test_5073_the_bridge_is_derived_from_the_hevy_table_and_covers_the_band_members():
    from training import muscle_volume as mv, volume_floors as vf

    assert mv.LABEL_TO_LANDMARK_KEY["Quads"] == "quadriceps" and mv.LABEL_TO_LANDMARK_KEY["Biceps"] == "biceps"
    keys = set(mv.LABEL_TO_LANDMARK_KEY.values())
    for group in ("legs", "arms"):
        for member in vf.BAND_MEMBERS[group]:
            assert set(member) <= keys, (group, member)


def test_no_per_exercise_counts_leaves_the_movement_bands_absent():
    v = mt.volume_section({"muscles": {}})["rows"]
    assert v["side_rear_delts"]["state"] == "absent" and v["side_rear_delts"]["value"] is None
    assert mt.volume_section(None)["rows"]["legs"]["state"] == "absent"


def test_fitness_tests_are_absent_until_the_battery_exists():
    f = mt.fitness_section(None)
    assert f["state"] == "absent" and "#5078" in f["detail"]


def test_the_running_gate_is_the_charters():
    r = mt.running_gate_section(RUN_AT_LB + 12.5)
    assert r["value"] == 12.5 and r["gate_lb"] == RUN_AT_LB and r["weight_cleared"] is False
    assert r["prerequisites"] == charter_value("gated_movements.running.prerequisites")
    assert mt.running_gate_section(None)["state"] == "absent"


# ── triggers: the condition and the lever ──────────────────────────────────────────


def _fired(row):
    return {t["id"]: t for t in row["triggers"]["fired"]}


def test_rate_below_the_floor_two_weeks_running_is_amber_naming_steps_or_food():
    prior = _row(weight=_weight(FLOOR - 0.5), monday="2026-10-05")
    assert "rate_below_floor" not in _fired(prior)  # one week is not a trigger
    row = _row(weight=_weight(FLOOR - 0.5), prior=prior)
    t = _fired(row)["rate_below_floor"]
    assert t["level"] == "amber" and t["lever"] == mt.LEVERS["rate_below_floor"] and "steps or food" in t["lever"]
    assert row["triggers"]["status"] == "amber"


def test_rate_above_the_ceiling_is_amber_then_red_naming_the_nutrition_review():
    prior = _row(weight=_weight(CEIL + 0.5), monday="2026-10-05")
    assert _fired(prior)["rate_above_ceiling"]["level"] == "amber"
    row = _row(weight=_weight(CEIL + 0.5), prior=prior)
    t = _fired(row)["rate_above_ceiling"]
    assert t["level"] == "red" and "nutrition review" in t["lever"]


def test_an_anchor_down_two_weeks_is_amber_naming_fatigue_before_work():
    soft = [200.0] * 6 + [198.0, 199.0, 197.0]  # down, but under the redline's threshold
    a = mt.anchors_section({"squat": _sessions(soft)}, SUN)
    assert a["anchors"]["squat"]["down"] and not a["anchors"]["squat"]["tripped"]
    prior = _row(anchors=a, monday="2026-10-05")
    row = _row(anchors=a, prior=prior)
    t = _fired(row)["anchor_down"]
    assert t["level"] == "amber" and t["evidence"] == ["squat"] and "fatigue" in t["lever"]


def test_a_tripped_anchor_is_red():
    a = mt.anchors_section({"hinge": _sessions([200.0] * 6 + [150.0] * 3)}, SUN)
    assert a["anchors"]["hinge"]["tripped"] is True
    assert _fired(_row(anchors=a))["anchor_down"]["level"] == "red"


def test_a_steps_day_under_the_floor_is_amber_and_a_mean_under_it_is_red():
    amber = _row(steps=mt.steps_section(_days([STEPS_TARGET] * 6 + [STEPS_FLOOR - 1])))
    t = _fired(amber)["steps_floor_missed"]
    assert t["level"] == "amber" and "walk prescription" in t["lever"]
    red = _row(steps=mt.steps_section(_days([STEPS_FLOOR - 1000] * 7)))
    assert _fired(red)["steps_floor_missed"]["level"] == "red"


def test_a_priority_muscle_below_its_floor_two_weeks_is_amber_naming_a_slot():
    bands = charter_value("volume_priorities.sets_per_wk")
    key = next(iter(bands))
    vol = mt.volume_section(_vol([(*LATERAL, 3)]))
    prior = _row(volume=vol, monday="2026-10-05")
    t = _fired(_row(volume=vol, prior=prior))["priority_volume_below_floor"]
    assert t["level"] == "amber" and key in t["evidence"] and "slot" in t["lever"]


def test_unmeasured_inputs_are_unevaluated_never_green():
    row = _row(steps=mt.steps_section(None, read_error="ClientError: x"))
    ids = {u["id"] for u in row["triggers"]["unevaluated"]}
    assert {"steps_floor_missed", "anchor_down", "priority_volume_below_floor"} <= ids
    assert row["triggers"]["status"] == "green_with_gaps"


def test_every_fired_trigger_names_a_lever():
    prior = _row(weight=_weight(CEIL + 1), steps=mt.steps_section(_days([1000] * 7)), monday="2026-10-05")
    row = _row(weight=_weight(CEIL + 1), steps=mt.steps_section(_days([1000] * 7)), prior=prior)
    assert row["triggers"]["fired"]
    for t in row["triggers"]["fired"]:
        assert t["lever"] == mt.LEVERS[t["id"]] and t["lever"]


def test_the_row_is_stamped_and_keyed():
    row = _row()
    assert row["pk"] == "USER#matthew#SOURCE#may_tracker" and row["sk"] == "WEEK#" + MON
    assert row["charter_version"] == charter_value("version") and row["version"] == mt.TRACKER_VERSION
    assert (row["week_start"], row["week_end"]) == (MON, SUN)


# ── the store ───────────────────────────────────────────────────────────────────


class _Table:
    def __init__(self, fail=False):
        self.items, self.fail = {}, fail

    def put_item(self, Item):
        self.items[(Item["pk"], Item["sk"])] = Item

    def query(self, **kw):
        if self.fail:
            raise RuntimeError("down")
        pk = kw["ExpressionAttributeValues"][":pk"]
        items = sorted((v for (p, _s), v in self.items.items() if p == pk), key=lambda i: i["sk"], reverse=True)
        return {"Items": items[: kw.get("Limit", 100)]}


def test_write_week_stores_decimals_and_latest_row_reads_back_the_newest():
    t = _Table()
    mt.write_week(t, _row(monday="2026-10-05"))
    mt.write_week(t, _row())
    stored = t.items[(mt.PK, "WEEK#" + MON)]
    assert isinstance(stored["weight"]["band"]["floor_lb_wk"], Decimal)
    t2 = _Table()
    mt.write_week(t2, _row(volume=mt.volume_section(_vol([(*LATERAL, 5)])), monday="2026-10-05"))
    srd = t2.items[(mt.PK, "WEEK#2026-10-05")]["volume"]["rows"]["side_rear_delts"]
    assert isinstance(srd["value"], (int, Decimal)) and srd["value"] == 5 and all(isinstance(n, (int, Decimal)) for n in srd["member_sets"])
    assert not any(isinstance(n, float) for n in [*srd["band"], *srd["member_sets"], srd["value"]])
    got = mt.latest_row(t)
    assert got["state"] == "measured" and got["row"]["week_start"] == MON
    assert isinstance(got["row"]["weight"]["band"]["floor_lb_wk"], float)


def test_latest_row_absent_and_read_failed_are_distinct():
    assert mt.latest_row(_Table())["state"] == "absent"
    failed = mt.latest_row(_Table(fail=True))
    assert failed["state"] == "read_failed" and failed["error"] == "RuntimeError"


def test_write_week_refuses_a_foreign_row():
    with pytest.raises(ValueError):
        mt.write_week(_Table(), {"pk": "USER#matthew#SOURCE#withings", "sk": "WEEK#x"})


# ── the reader layer (fakes at the sanctioned reads) and the nightly leg ──────────────


def test_compute_weeks_wires_every_read_into_its_section(monkeypatch):
    from training import rate_band

    from mcp import core, tools_may_tracker as tmt

    weighins = [{"date": mt.shift("2026-09-01", i), "weight_lbs": WEIGHT + 30 - i * 0.5} for i in range(48)]

    def qs(source, start, end, *a, **k):
        if source == "withings":
            return [r for r in weighins if start <= r["date"] <= end]
        if source == "measurements":
            return [{"date": "2026-10-10", "waist_navel_in": 49.0}]
        return []

    def qsr(source, start, end, *a, **k):
        if source == "whoop":
            return [{"sk": "DATE#" + mt.shift(start, i), "date": mt.shift(start, i), "step_count": STEPS_TARGET} for i in range(21)]
        return []

    monkeypatch.setattr(core, "query_source", qs)
    monkeypatch.setattr(core, "query_source_range", qsr)
    monkeypatch.setattr(rate_band, "guidance_cap_for", lambda table, user_id="matthew": None)
    monkeypatch.setattr("mcp.tools_strength._read_hevy_all_phases", lambda s, e: ([], []))
    monkeypatch.setattr(tmt, "_anchor_series", lambda items: {"bench": _sessions([200.0] * 9)})
    monkeypatch.setattr(tmt, "pacific_today", lambda: "2026-10-19")

    rows = tmt.compute_weeks(MON, weeks=2)
    assert [r["week_start"] for r in rows] == ["2026-10-05", MON]
    last = rows[-1]
    assert last["weight"]["rate_week"]["state"] == "measured"
    assert last["weight"]["rate_week"]["value"] == pytest.approx(3.5, abs=0.01)
    assert last["waist"]["value"] == {"waist_navel_in": 49.0}
    assert last["steps"]["state"] == "measured" and last["steps"]["days_at_target"] == 7
    assert last["anchors"]["anchors"]["bench"]["state"] == "measured"
    assert last["fitness_tests"]["state"] == "absent"
    assert last["weight"]["guidance"]["state"] == "absent"


def test_rate_week_stays_the_7_day_slope_when_it_differs_from_the_14_day_trend(monkeypatch):
    """#5100: the critics count the 14-day trend; the tracker cell (and the block retro's registered prediction) stays the 7-day slope."""
    from training import rate_band

    from mcp import core, shared_quantities as sq, tools_may_tracker as tmt

    weighins = [{"date": mt.shift("2026-09-01", i), "weight_lbs": WEIGHT + 30 - i * 0.4 + ((i % 7) - 3)} for i in range(48)]
    monkeypatch.setattr(
        core, "query_source", lambda s, a, b, *x, **k: [r for r in weighins if a <= r["date"] <= b] if s == "withings" else []
    )
    monkeypatch.setattr(core, "query_source_range", lambda *a, **k: [])
    monkeypatch.setattr(rate_band, "guidance_cap_for", lambda table, user_id="matthew": None)
    monkeypatch.setattr("mcp.tools_strength._read_hevy_all_phases", lambda s, e: ([], []))
    monkeypatch.setattr(tmt, "_anchor_series", lambda items: {})
    monkeypatch.setattr(tmt, "pacific_today", lambda: "2026-10-19")
    sun = mt.shift(MON, 6)
    slope7 = sq.loss_rate_from_rows(weighins, sun, window_days=7)["rate_lb_wk"]
    trend14 = sq.loss_rate_from_rows(weighins, sun)["rate_lb_wk"]
    assert abs(slope7 - trend14) > 1.0  # the fixture can tell the two apart
    cell = tmt.compute_weeks(MON, weeks=1)[-1]["weight"]["rate_week"]
    assert cell["state"] == "measured" and cell["value"] == pytest.approx(slope7, abs=0.01)


def test_a_failed_hevy_read_is_read_failed_in_both_hevy_sections(monkeypatch):
    from training import rate_band

    from mcp import core, tools_may_tracker as tmt

    def boom(s, e):
        raise RuntimeError("hevy down")

    monkeypatch.setattr(core, "query_source", lambda *a, **k: [])
    monkeypatch.setattr(core, "query_source_range", lambda *a, **k: [])
    monkeypatch.setattr(rate_band, "guidance_cap_for", lambda table, user_id="matthew": None)
    monkeypatch.setattr("mcp.tools_strength._read_hevy_all_phases", boom)
    row = tmt.compute_weeks(MON, weeks=1)[-1]
    assert row["anchors"]["state"] == "read_failed" and row["volume"]["state"] == "read_failed"
    assert row["weight"]["weight_lb"]["state"] == "absent"


def test_the_nightly_leg_never_raises(monkeypatch):
    from mcp import nightly_predraft, tools_may_tracker as tmt

    def boom(today=None):
        raise RuntimeError("no table")

    monkeypatch.setattr(tmt, "write_latest", boom)
    assert tmt.nightly_leg() == {"outcome": "failed", "error": "RuntimeError"}
    assert nightly_predraft._may_tracker_leg() == {"outcome": "failed", "error": "RuntimeError"}


def test_the_tool_reports_a_stale_stored_row(monkeypatch):
    from mcp import core, tools_may_tracker as tmt

    t = _Table()
    mt.write_week(t, _row(monday="2026-10-05"))
    monkeypatch.setattr(core, "table", t)
    monkeypatch.setattr(tmt, "pacific_today", lambda: "2026-10-19")
    monkeypatch.setattr(tmt, "compute_weeks", lambda monday, weeks: [_row(monday=monday)])
    out = tmt.tool_get_may_tracker({"weeks": 1})
    assert out["stored"]["state"] == "stale" and out["latest"]["week_start"] == MON
    assert out["trend"][0]["week_start"] == MON


# ── privacy: never a published surface ────────────────────────────────────────────

_IMPORT_RE = re.compile(
    r"^\s*(?:from|import)\s+[\w.]*\b(?:may_tracker|tools_may_tracker)\b|^\s*from\s+[\w.]+\s+import\s+[^#\n]*\b(?:may_tracker|tools_may_tracker)\b",
    re.M,
)
PUBLISHED_TREES = ("lambdas/web", "lambdas/emails")


def importers(root: Path, trees=PUBLISHED_TREES) -> list[str]:
    hits = []
    for tree in trees:
        for dirpath, _dirs, files in os.walk(root / tree):
            for f in files:
                if f.endswith(".py"):
                    p = Path(dirpath) / f
                    if _IMPORT_RE.search(p.read_text(encoding="utf-8", errors="replace")):
                        hits.append(str(p.relative_to(root)))
    return sorted(hits)


def test_no_published_surface_imports_the_tracker():
    assert all((ROOT / t).is_dir() for t in PUBLISHED_TREES), "the sweep must reach the trees it claims"
    assert importers(ROOT) == [], "the May tracker is owner-only (no May countdown on a published surface)"


def test_the_sweep_catches_a_planted_importer(tmp_path):
    for tree in PUBLISHED_TREES:
        (tmp_path / tree).mkdir(parents=True)
    (tmp_path / "lambdas/web/x.py").write_text("from training import may_tracker\n")
    (tmp_path / "lambdas/emails/y.py").write_text("from mcp.tools_may_tracker import tool_get_may_tracker\n")
    assert importers(tmp_path) == ["lambdas/emails/y.py", "lambdas/web/x.py"]


def test_the_tier_and_the_class_are_declared():
    from experiment import phase_taxonomy
    from privacy import field_tiers

    assert field_tiers.SOURCE_TIERS["may_tracker"] == field_tiers.TIER_OWNER_ONLY
    assert phase_taxonomy.SOURCE_CLASS["may_tracker"] == phase_taxonomy.CROSS_PHASE
