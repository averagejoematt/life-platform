"""tests/test_core_habits_5124.py — the core-12 calculation set (#5124, M4, epic #5120).

Owner ruling 2026-10-18: core-12 is the CALCULATION set (the score, the character sheet and the coaches read it); ALL
other habits are RETAINED. What is held here:

  1. THE CHARTER DEFINES THE TWELVE (`habits.core`), in the issue's order, each with a basis; out of bed on time is
     graded by `health.wake_consistency` against `sleep.wake_time` (the #5133 note), steps against `steps.floor`.
  2. ONE RESOLVER (`health.core_habits`): membership by the registry's `core` flag, a multi-member id held only when
     every member is held, unknown never a miss, the score done / known.
  3. THE READERS: the habit scorer (unarmed unchanged; armed = the core share, non-core habits still tracked), both
     habit_scores writers, the character sheet's mind habit compliance, and the daily coaches' missed-habit lines.
  4. THE DRIFT CHECK reports the flag as counts only, and the owner-run flag script refuses what it cannot apply.

No clock is read anywhere on these paths (every day is passed in), so no literal here can move with the calendar.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
for _k, _v in [
    ("AWS_REGION", "us-west-2"),
    ("AWS_DEFAULT_REGION", "us-west-2"),
    ("AWS_ACCESS_KEY_ID", "testing"),
    ("AWS_SECRET_ACCESS_KEY", "testing"),
    ("TABLE_NAME", "life-platform"),
    ("S3_BUCKET", "matthew-life-platform"),
    ("USER_ID", "matthew"),
    ("EMAIL_RECIPIENT", "reader@example.invalid"),
    ("EMAIL_SENDER", "brief@example.invalid"),
    ("AI_VALIDATOR_AUTOLOAD", "off"),
]:
    os.environ.setdefault(_k, _v)
sys.path.insert(0, str(REPO / "lambdas"))
sys.path.insert(0, str(REPO / "scripts"))

from health import character_engine, core_habits, scoring_engine  # noqa: E402
from training import coach_context, training_charter as tc  # noqa: E402

DAY = "2026-10-21"  # a Wednesday
ISSUE_LIST = [
    "weigh in",
    "food logged",
    "calories in band",
    "protein at or above the floor",
    "steps at or above the floor",
    "planned session done",
    "evening check-in",
    "no alcohol",
    "no solo takeout",
    "no sweets or fried food",
    "out of bed on time",
    "one connection",
]
HABITIFY_IDS = [
    "weigh_in",
    "food_logged",
    "calories_in_band",
    "protein_floor",
    "planned_session_done",
    "no_alcohol",
    "no_solo_takeout",
    "no_sweets_or_fried",
    "one_connection",
]


def _registry(flagged: bool = True) -> dict:
    """A synthetic registry: one entry per Habitify-basis core id (two for the sweets/fried pair) plus two retained."""
    reg = {f"Habit {cid}": {"status": "active", "tier": 1, **({"core": cid} if flagged else {})} for cid in HABITIFY_IDS}
    reg["Habit no_sweets_or_fried"]["vice"] = True
    reg["Habit fried"] = {"status": "active", "tier": 2, "vice": True, **({"core": "no_sweets_or_fried"} if flagged else {})}
    reg["Retained floss"] = {"status": "active", "tier": 0}
    reg["Retained read"] = {"status": "active", "tier": 2, "target_frequency": 3}
    return reg


def _day(done: set[str], *, registry: dict) -> dict:
    habits = {name: (1 if name in done else 0) for name in registry}
    return {"date": DAY, "habitify": {"sk": f"DATE#{DAY}", "habits": habits}, "habitify_7d": []}


# ── 1. the charter defines the twelve ───────────────────────────────────────────────────────


def test_the_charter_defines_the_twelve_in_the_issues_order_with_a_basis_each():
    spec = core_habits.core_spec()
    assert [e["label"] for e in spec] == ISSUE_LIST
    assert len({e["id"] for e in spec}) == 12
    by = {e["id"]: e for e in spec}
    assert by["out_of_bed_on_time"]["basis"] == "wake_consistency" and by["out_of_bed_on_time"]["rule_ref"] == "sleep.wake_time"
    assert by["steps_floor"]["basis"] == "steps" and tc.charter_value(by["steps_floor"]["rule_ref"]) == tc.charter_value("steps.floor")
    assert by["evening_checkin"]["basis"] == "evening_checkin"
    assert [e["id"] for e in spec if e["basis"] == "habitify"] == HABITIFY_IDS
    h = tc.charter_value("habits")
    assert "never archived or deleted" in h["retained"] and h["reader"].startswith("health.core_habits")
    assert "pending his ruling" in h["provenance"], "the defaults are named as defaults"
    assert tc.charter_value("change_log")[-1]["version"] == tc.charter_version()
    assert "#5124" in tc.charter_value("sleep.wake_time.habit"), "the wake rule still names the M4 habit it grades"


def test_the_charter_names_no_registry_entry():
    raw = (REPO / "config" / "training_charter.json").read_text()
    for name in ("Weigh In", "Food Journal", "Calorie Goal", "Primary Exercise", "Social Gratitude", "Out Of Bed"):
        assert name not in raw, "habit names are owner data; the charter names ids, the registry carries the flag"


# ── 2. the one resolver ──────────────────────────────────────────────────────────────────────


def test_membership_arming_and_flag_drift():
    reg = _registry()
    assert core_habits.is_armed(reg) and not core_habits.is_armed(_registry(flagged=False))
    assert core_habits.members(reg)["no_sweets_or_fried"] == ["Habit no_sweets_or_fried", "Habit fried"]
    assert core_habits.flag_drift(reg) == {
        "core_ids": 12,
        "core_flagged_entries": 10,
        "core_ids_unflagged": 0,
        "core_flag_unknown": 0,
        "core_flag_inactive": 0,
    }
    bad = {**reg, "X": {"status": "active", "core": "steps_floor"}, "Y": {"status": "active", "core": "nope"}}
    bad["Habit weigh_in"] = {**bad["Habit weigh_in"], "status": "archived"}
    d = core_habits.flag_drift(bad)
    assert (d["core_flag_unknown"], d["core_flag_inactive"], d["core_ids_unflagged"]) == (2, 1, 1)


def test_grade_day_reads_each_basis_and_never_counts_an_unknown_as_a_miss():
    reg = _registry()
    readings = {k: 1.0 for k in reg}
    readings["Habit fried"] = 0.0  # one member of the pair broken -> the pair is missed
    readings.pop("Habit one_connection")  # unobserved -> unknown
    floor = tc.charter_value("steps.floor")
    wakes = {f"2026-10-{d:02d}": "06:00" for d in range(7, 21)} | {DAY: "06:10"}
    g = core_habits.grade_day(reg, day=DAY, reading=lambda k, m: readings.get(k), steps=floor, wakes=wakes, checkin=False)
    st = {r["id"]: r["state"] for r in g["habits"]}
    assert st["no_sweets_or_fried"] == "missed" and st["one_connection"] == "unknown"
    assert st["steps_floor"] == "done" and st["out_of_bed_on_time"] == "done" and st["evening_checkin"] == "missed"
    assert (g["done"], g["missed"], g["unknown"], g["known"]) == (9, 2, 1, 11)
    assert g["score"] == round(9 / 11 * 100) and g["missed_labels"] == ["evening check-in", "no sweets or fried food"]
    # the wake grade IS health.wake_consistency's: 45 min off the 06:00 anchor is off
    late = core_habits.grade_day(reg, day=DAY, reading=lambda k, m: 1.0, wakes={**wakes, DAY: "06:45"})
    assert {r["id"]: r["state"] for r in late["habits"]}["out_of_bed_on_time"] == "missed"
    # nothing passed -> every derived basis unknown, never a miss
    bare = core_habits.grade_day({}, day=DAY)
    assert bare["known"] == 0 and bare["score"] is None and bare["unknown"] == 12 and not bare["armed"]
    below = core_habits.grade_day(reg, day=DAY, steps=floor - 1)
    assert {r["id"]: r["state"] for r in below["habits"]}["steps_floor"] == "missed"


def test_the_derived_inputs_are_read_honestly():
    rows = [
        {"sk": "DATE#2026-10-20", "sleep_end": "2026-10-20T13:05:00Z"},  # 06:05 PDT
        {"sk": "DATE#2026-10-20#WORKOUT#1", "sleep_end": "2026-10-20T20:00:00Z"},
        {"sk": "DATE#2026-10-19", "sleep_end": None},
    ]
    assert core_habits.wakes_from_sleep_rows(rows) == {"2026-10-20": "06:05"}
    full = {"hunger": 1, "stress": 2, "cravings": 0}
    assert core_habits.checkin_state(full, None) is True
    assert core_habits.checkin_state({"hunger": 1}, {"status": "sent"}) is False
    assert core_habits.checkin_state(None, {"status": "attempting"}) is None and core_habits.checkin_state(None, None) is None


# ── 3. the readers ───────────────────────────────────────────────────────────────────────────


def test_the_scorer_is_unchanged_until_armed():
    reg = _registry(flagged=False)
    score, d = scoring_engine.score_habits_registry(_day(set(reg), registry=reg), {"habit_registry": reg})
    # the tier-weighted read, by hand: T0 100 (x3), T1 100 (x1), T2 the 7-day frequency (1/7 and 1/3 of target) (x0.5)
    t2 = (round(1 / 7 * 100) + round(1 / 3 * 100)) / 2
    assert d["composite_method"] == "tier_weighted" and d["core"]["armed"] is False
    assert score == round((100 * 3 + 100 * 1 + t2 * 0.5) / 4.5)


def test_armed_the_score_is_the_core_share_and_every_other_habit_is_still_tracked():
    reg = _registry()
    done = set(reg) - {"Habit weigh_in", "Retained floss"}  # one core miss, one retained miss
    data = _day(done, registry=reg)
    data["core_inputs"] = {"steps": tc.charter_value("steps.floor"), "wakes": None, "checkin": True}
    score, d = scoring_engine.score_habits_registry(data, {"habit_registry": reg})
    assert d["composite_method"] == "core_set"
    assert (d["core"]["done"], d["core"]["known"]) == (10, 11)  # 9 habitify + steps + check-in known; wake unknown
    assert score == round(10 / 11 * 100), "the retained miss does not move the score"
    assert d["tier_status"][0] == {"Retained floss": False}, "a retained habit is still read and visible"
    assert scoring_engine.core_day(data, {"habit_registry": reg})["score"] == score


def test_both_habit_scores_writers_store_the_core_day():
    import test_tier0_streak_writer_2242 as w  # the shared fake table and writer harness

    reg = _registry()
    data = _day(set(reg) - {"Habit weigh_in"}, registry=reg)
    score, d = scoring_engine.score_habits_registry(data, {"habit_registry": reg})
    for module in (w.dmc, pytest.importorskip("daily_brief_lambda")):
        table = w.FakeTable()
        module.table = table
        module.store_habit_scores(DAY, {"habits_mvp": d}, {"habits_mvp": score}, {}, {"habit_registry": reg}, tier0_streak=0)
        row = table.habit_rows()[0]
        assert row["scoring_method"] == "core_set_v1", module.__name__
        assert int(row["core_done"]) == 8 and int(row["core_known"]) == 9 and int(row["core_total"]) == 12
        assert float(row["core_pct"]) == round(8 / 9, 3) and row["core_status"]["weigh_in"] == "missed"
        assert row["missed_core"] == ["weigh in"] and "Habit weigh_in" not in json.dumps(row["core_status"])


def test_the_character_sheet_reads_the_core_share_on_an_armed_day():
    cfg = json.loads((REPO / "config" / "character_sheet.json").read_text())  # the real mind components (behavioral flags)
    armed = {"habit_scores": {"scoring_method": "core_set_v1", "core_pct": 0.75, "tier0_pct": 0.2, "tier1_pct": 0.1}}
    _, det = character_engine.compute_mind_raw(armed, cfg)
    assert det["t0_habit_compliance"]["score"] == 75.0 and det["t1_habit_compliance"]["score"] == 75.0
    assert "t1_habit_compliance" not in det["_absent_behaviors"], "the core share is not scored as an absent behaviour"
    unarmed = {"habit_scores": {"scoring_method": "tier_weighted_v1", "tier0_pct": 0.2, "tier1_pct": 0.1}}
    _, det2 = character_engine.compute_mind_raw(unarmed, cfg)
    assert (det2["t0_habit_compliance"]["score"], det2["t1_habit_compliance"]["score"]) == (20.0, 10.0)


def test_the_coaches_read_only_the_core_set_once_armed():
    from ai import habit_context

    reg = _registry()
    data = _day(set(reg) - {"Habit weigh_in", "Retained floss"}, registry=reg)
    lines, missed = habit_context.core_habit_lines(data, {"habit_registry": reg})
    assert missed == ["weigh in"] and "Retained floss" not in lines and "unknown (no reading; never a miss)" in lines
    assert habit_context.core_habit_lines(data, {"habit_registry": _registry(flagged=False)}) is None
    goal = coach_context.charter_goal_lines()
    assert "Core habits (the calculation set" in goal and "; ".join(ISSUE_LIST) in goal
    assert tc.public_view()["habits"]["core"] == tc.charter_value("habits.core")


# ── 4. the drift check and the flag script ───────────────────────────────────────────────────


def _fixture(tmp_path, registry):
    p = tmp_path / "habit_core_drift_5124.json"
    p.write_text(json.dumps({"live_names": sorted(registry), "habit_registry": registry, "bridge_keys": []}))
    return str(p)


def test_the_drift_check_reports_the_core_flag_as_counts_only(tmp_path, capsys):
    import check_habit_registry_drift as drift

    assert drift.main(["--fixture", _fixture(tmp_path, _registry(flagged=False))]) == 0
    assert "CORE-SET: UNARMED" in capsys.readouterr().out
    assert drift.main(["--fixture", _fixture(tmp_path, _registry())]) == 0
    out = capsys.readouterr().out
    assert "HABIT-REGISTRY-DRIFT: OK" in out and "core_ids_unflagged: 0" in out and "Habit weigh_in" not in out
    partial = _registry()
    del partial["Habit one_connection"]["core"]
    assert drift.main(["--fixture", _fixture(tmp_path, partial)]) == 1, "armed, an unflagged core id is drift"
    unknown = {**_registry(flagged=False), "Retained floss": {"status": "active", "core": "nope"}}
    assert drift.main(["--fixture", _fixture(tmp_path, unknown)]) == 1, "an unknown flag is drift even unarmed"
    assert "Retained floss" not in capsys.readouterr().out


def test_the_flag_script_refuses_what_it_cannot_apply():
    import apply_habit_core_flags as ap

    reg = _registry(flagged=False)
    writes, errors = ap.plan(reg, ["weigh_in=Habit weigh_in", "no_sweets_or_fried=Habit fried"])
    assert writes == [("Habit weigh_in", "weigh_in"), ("Habit fried", "no_sweets_or_fried")] and not errors
    _, errors = ap.plan(reg, ["steps_floor=Habit weigh_in", "nope=Habit weigh_in", "weigh_in=Missing", "weigh_in"])
    assert len(errors) == 4 and not any("Habit weigh_in" in e for e in errors)
