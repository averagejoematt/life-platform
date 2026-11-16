"""#6014 — owner rulings 2026-11-15 on home_gym equipment, held over the committed library and the engine.

  A  twelve equipment ids are owner-confirmed at home_gym (served); B the standing calf raise machine is left alone.
  C  the recent-inferred window never starts before the day he began training at home_gym (`HOME_GYM_SINCE`): a log from
     an earlier gym is no evidence a machine is here.
  D  the heavy-upper horizontal pull is pinned to the free-weight one-arm dumbbell row (coaching decision, owner-vetoable):
     with the seated row machine confirmed, the row family's own order would serve `machine_row` there, leaving the week
     without a free-weight pull, and stage 1 (`week_commitments` free_weight_compounds) would block every commit.

Each rule sits beside a must-fail control. No AWS, no network, no clock: every date is a literal.
"""

from __future__ import annotations

import copy
import json
import os
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
for p in (REPO / "deploy", REPO / "lambdas", REPO):
    sys.path.insert(0, str(p))
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

import exercise_library_curation as cur  # noqa: E402
import exercise_library_integrity as inputs  # noqa: E402
from training import (  # noqa: E402
    exercise_library as xl,
    kb_entry,
    program_structure as ps,
    selection_engine as se,
    training_charter as tc,
    variant_rotation as vr,
    week_commitments as wc,
    week_floors as wf,
)

LIB = json.loads((REPO / "config" / "exercise_library.json").read_text())
CAT = json.loads((REPO / "config" / "movement_catalog.json").read_text())["movements"]
INV = LIB["gym_inventory"]["items"]
DAY = wf.KETTLEBELL_BLOCK_FROM  # every commitment row armed

CONFIRMED_1115 = {
    "seated_row_machine",
    "shoulder_press_machine",
    "hip_thrust_machine",
    "t_bar_row_machine",
    "hack_squat_machine",
    "back_extension_45",
    "triceps_machine",
    "bench_decline",
    "ab_wheel",
    "smith_machine",
    "captains_chair",
    "pullover_machine",
}


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    monkeypatch.delenv(tc.PRIVATE_ENV_VAR, raising=False)
    monkeypatch.delenv(xl.PRIVATE_ENV_VAR, raising=False)
    monkeypatch.setattr(tc, "_from_s3", lambda key: None)
    monkeypatch.setattr(xl, "_overlay_from_local", lambda: None)
    monkeypatch.setattr(xl, "_overlay_from_s3", lambda: None)
    monkeypatch.setattr(wf, "library", lambda path=None: copy.deepcopy(LIB))
    tc.reset_cache()
    se._LIB_CACHE.clear()
    yield
    tc.reset_cache()
    se._LIB_CACHE.clear()


# ── A / B ────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_a_the_confirmed_equipment_is_owner_confirmed_and_served():
    for eid in CONFIRMED_1115:
        row = INV[eid]["home_gym"]
        assert (row["evidence"], row["state"]) == ("owner_confirmed", "available"), eid
        assert "owner ruling 2026-11-15" in row["source"], eid
    assert LIB["movements"]["seated_row_machine"]["availability"]["home_gym"]["state"] == "available"
    # B: owner unsure — the standing calf raise machine keeps its log-derived state
    assert INV["calf_raise_standing_machine"]["home_gym"]["evidence"] == "historical_only"
    assert "calf_raise_standing_machine" not in cur.SEEDED_AVAILABILITY


def test_a_the_library_stays_approved_and_the_change_is_versioned():
    assert (LIB["status"], LIB["approved_on"], LIB["version"]) == ("approved", "2026-11-14", "0.4.1")
    line = LIB["change_log"][-1]
    assert (line["version"], line["date"]) == ("0.4.1", "2026-11-15") and "owner ruling 2026-11-15" in line["by"]
    assert se.mode(LIB) == se.MODE_LIVE


# ── C ────────────────────────────────────────────────────────────────────────────────────────────────────────────────
_MV = {
    "since_gym": {"equipment": ["leg_curl_seated"], "history": {"last_done": "2026-10-01"}},
    "earlier_gym": {"equipment": ["hack_squat_machine"], "history": {"last_done": "2026-01-15"}},  # inside 12 months, pre-May
    "first_day": {"equipment": ["smith_machine"], "history": {"last_done": "2026-05-01"}},
}


def _states(since):
    inv = inputs.home_gym_inventory(_MV, {"last": "2026-11-11"}, {}, since)
    return {x: r["home_gym"]["evidence"] for x, r in inv.items()}


def test_c_a_log_from_before_the_gym_start_is_not_recent_evidence():
    assert cur.HOME_GYM_SINCE["date"] == "2026-05-01" and "owner ruling 2026-11-15" in cur.HOME_GYM_SINCE["source"]
    got = _states(cur.HOME_GYM_SINCE["date"])
    assert got == {
        "leg_curl_seated": "recent_inferred",
        "hack_squat_machine": "historical_only",  # logged inside the 12 months, but before he trained here
        "smith_machine": "recent_inferred",  # the gym's first day counts
    }


def test_c_control_without_the_gym_start_the_pre_may_log_would_read_recent():
    """Must-fail control: the 12-month window alone counts the pre-May log, so the floor is what keeps it out."""
    assert _states(None)["hack_squat_machine"] == "recent_inferred"


def test_c_the_builder_and_the_rule_text_carry_the_gym_start():
    assert "never starts before the day he began training at home_gym" in LIB["gym_inventory"]["rule"]
    src = (REPO / "deploy" / "build_exercise_library.py").read_text()
    assert 'cur.HOME_GYM_SINCE["date"]' in src


# ── D ────────────────────────────────────────────────────────────────────────────────────────────────────────────────
def _approved() -> dict:
    return copy.deepcopy(LIB) | {"approved_on": "2026-01-02"}  # live from the program's first week


def _planned_week(lib: dict) -> dict:
    entry = {"week": 1, "block": 1, "session_role": "upper_heavy", "date": DAY}
    rot = vr.plan(entry, CAT, rows=[], role="*", kb_exposures=kb_entry.ENTRY_EXPOSURES, skill_ceiling=2)
    return se.apply(rot, CAT, rows=[], skill_ceiling=2, target_date=DAY, lib=lib, overlay=None)


def _row_keys(rot: dict) -> dict[str, str]:
    return {s["role"]: s["key"] for s in wc.served_week(rot, CAT) if s["slot_id"].endswith(".row")}


def test_d_the_heavy_row_is_the_dumbbell_row_and_stage_1_passes():
    assert ps.SESSION_TEMPLATES["upper_heavy"]["anchor_keys"] == {"row": ["one_arm_db_row"]}
    assert LIB["movements"]["seated_row_machine"]["availability"]["home_gym"]["state"] == "available"
    lib = _approved()
    rot = _planned_week(lib)
    assert _row_keys(rot) == {"upper_heavy": "one_arm_db_row", "upper_volume": "machine_row"}  # the volume day keeps the family order
    ev = wc.evaluate(rot, CAT, on=DAY, library=lib)
    fw = next(r for r in ev["rows"] if r["id"] == "free_weight_compounds")
    assert fw["verdict"] == wc.MET and "Dumbbell Row" in fw["detail"]
    assert ev["verdict"] == "pass", ev["lines"]


def test_d_control_without_the_pin_the_machine_row_leaves_no_free_weight_pull_and_stage_1_blocks(monkeypatch):
    """Must-fail control: with the seated row machine available and the pin removed, both rows are the machine and the
    approved week blocks on free_weight_compounds."""
    monkeypatch.setitem(
        ps.SESSION_TEMPLATES, "upper_heavy", {k: v for k, v in ps.SESSION_TEMPLATES["upper_heavy"].items() if k != "anchor_keys"}
    )
    lib = _approved()
    rot = _planned_week(lib)
    assert _row_keys(rot) == {"upper_heavy": "machine_row", "upper_volume": "machine_row"}
    ev = wc.evaluate(rot, CAT, on=DAY, library=lib)
    assert "free_weight_compounds" in ev["blocking"]


def test_d_an_in_block_machine_row_never_takes_the_heavy_slot():
    """The pin holds the in-block rule too (`in_block_variant.prefer` reorders only the pinned members): a volume-day machine
    row performed in the block does not move the heavy day off the dumbbell row."""
    performed = [{"movement_key": "machine_row", "role": "upper_volume", "date": "2026-11-20", "position": 1}]
    rx = ps.session_prescription_for_role("upper_heavy", catalog_movements=CAT, in_block=performed)
    row = next(e for e in rx["exposures"] if e.get("pattern") == "row")
    assert row["movement_key"] == "one_arm_db_row"
