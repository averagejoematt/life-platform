"""tests/test_measurement_placed_5760.py — the overdue battery placed, the tape named in the plan, the dead-man named (#5760).

The block-1 retro (#5496) graded Measurement F: 0 of 4 calibration items done. Three holes, each held here:

  1. PLACEMENT. The battery went on the test-day role ONLY in the week that closes a block, so a battery missed in
     week 6 was never drafted again until week 12 — while the prompt said "the test-day draft carries them". Now the
     next test day after an uncovered closing week carries it (`fitness_tests.place_battery`, the same `due()` the
     prompt and the dead-man read), and a battery logged since the due week's opening leaves the session alone.
  2. THE DAILY PLAN. Due tape / photos / battery are an explicit `calibration_due` field of `plan_next_session`
     stage 1, every day until logged — the dead-man state included (the old prompt path drops it).
  3. THE DEAD-MAN. The fixed Telegram text names the item and the day it lapsed; a missed battery now rides it
     (`missed_2`, one claim per due week) instead of only the digest alarm.
  4. The retro's Measurement row reads `calibration.done / calibration.due` from the stored rows — no supplied count.

No clock is read: every day is passed in. PRIVACY: the plan items carry dates and states only, never a reading.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import sys
from unittest.mock import patch

import pytest

os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

_REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "lambdas"))
sys.path.insert(0, str(_REPO))

from training import (  # noqa: E402
    calibration_cadence as cc,
    fitness_tests as ft,
    session_sequence as ss,
    training_charter as tc,
)

START = "2026-10-19"  # the preview's synthetic start: one session a day through the real week rule


@pytest.fixture(autouse=True)
def _public_charter_only(monkeypatch):
    monkeypatch.delenv(tc.PRIVATE_ENV_VAR, raising=False)
    monkeypatch.setattr(tc, "_from_s3", lambda key: None)
    tc.reset_cache()
    yield
    tc.reset_cache()


# ── 1. the overdue battery goes on the NEXT test day ─────────────────────────────────────
def _preview():
    return ss.preview(80, start_day=START)


def _entry(role, week):
    entry = next(e for e in _preview() if e["session_role"] == role and e["week"] == week)
    return {**entry, "source": "session_sequence"}


def _opening(week):
    return next(e for e in _preview() if e["week"] == week)["week_basis"]["week_opened_on"]


def _generate(entry, batteries, *, ledger=True):
    """The generator over a real ledger position; `completed_positions` is the ledger's own sessions before the day
    (the Hevy rows a live run reads), or nothing when `ledger` is False (an unplaced due week)."""
    from training.routine_generator import GeneratorInputs, generate_routines

    done = [e for e in _preview() if e["date"] < entry["date"]] if ledger else []
    with (
        patch("training.routine_generator._load_note_indexes", return_value=({}, {}, {}, {})),
        patch("training.routine_generator._schedule_entry_for_date", return_value=entry),
        patch("training.fitness_tests.load_records_failsoft", return_value=None),
        patch("training.session_sequence.completed_positions", return_value=done),
    ):
        rs = generate_routines(
            GeneratorInputs(
                target_date=entry["date"], block_workouts=[], deload_records=[], disruption_records=[], fitness_batteries=batteries
            )
        )
    return next(r for r in rs if r.variant == "ideal")


def _carries(ideal):
    return ideal.title.startswith(ft.BATTERY_TITLE) and "fitness_battery" in ideal.inputs_snapshot


def test_a_battery_missed_in_the_closing_week_is_drafted_on_the_next_test_day():
    role = ft.test_day_role()
    for week in (7, 8):  # overdue (inside the grace week), then missed — both carried until one is logged
        ideal = _generate(_entry(role, week), [])
        assert _carries(ideal), f"week {week}: the overdue battery was not placed"
        fb = ideal.inputs_snapshot["fitness_battery"]
        assert fb["due"]["due_program_week"] == 6 and fb["due"]["due_on"] == _opening(6) and fb["due"]["due_on_is_estimate"] is False
        assert fb["tests"] == [s for s in ft.protocol()["order"] if s in ft.tests_spec()]
        assert len(ideal.notes) <= 150 and "not logged" in ideal.notes and _opening(6) in ideal.notes
        assert any("next test day carries it" in line for line in ideal.rationale)


def test_a_battery_logged_since_the_due_week_or_a_non_test_role_leaves_the_session_alone():
    role = ft.test_day_role()
    logged = [ft.build_battery_record(date=_opening(7), results={"dead_hang": 1}, recorded_at="t")]
    assert not _carries(_generate(_entry(role, 8), logged))
    assert not _carries(_generate(_entry("upper_heavy", 8), []))  # the battery only ever goes on the test-day role
    assert not _carries(_generate(_entry(role, 5), []))  # no block has closed yet: nothing is overdue
    # an unplaced due week (no ledger opening) is unknown, never read as overdue
    assert not _carries(_generate(_entry(role, 8), [], ledger=False))


def test_the_test_day_gate_admits_every_test_role_week_after_the_first_block():
    role, n = ft.test_day_role(), ft.block_weeks()
    assert [w for w in range(1, 2 * n + 1) if ft.is_test_day({"session_role": role, "week": w})] == list(range(n, 2 * n + 1))
    assert not any(ft.is_test_day({"session_role": r, "week": n + 2}) for r in ft.never_on_roles())


# ── 3. the dead-man names the item and the day it lapsed ─────────────────────────────────
def _pos(week):
    openings = {w: _opening(w) for w in range(1, week + 1)}
    return {"week": week, "week_opened_on": openings[week], "floor_days": 7, "week_openings": openings}


def test_a_missed_battery_rides_the_dead_man_once_per_due_week_naming_the_day_it_lapsed():
    from coach import calibration_deadman_alert as cda, coach_event_triggers as cet

    today = _opening(8)
    row = ft.calibration_row(today, ft.due(today, _pos(8), []))
    assert row["state"] == cc.MISSED_2 and row["battery_state"] == ft.MISSED and row["lapsed_on"] == _opening(6)
    block = {"kinds": {ft.CALIBRATION_KIND: row}}
    assert cc.deadman_kinds(block) == [ft.CALIBRATION_KIND]
    (alert,) = cda.due(block)
    assert alert["event_id"] == f"CALIB_DEADMAN#fitness_battery#{_opening(6)}"
    assert "fitness battery" in alert["text"] and f"lapsed on {_opening(6)}" in alert["text"]
    assert cet.detect_calibration(block, today) == []  # the AI sweep never sends a second, model-written one
    over = ft.calibration_row(_opening(7), ft.due(_opening(7), _pos(7), []))
    assert over["state"] == cc.OVERDUE and cc.deadman_kinds({"kinds": {ft.CALIBRATION_KIND: over}}) == []


def test_the_tape_dead_man_names_the_day_it_lapsed():
    b = cc.compute("2026-11-11", {"tape": lambda: ["2026-09-06"], "photos": lambda: ["2026-11-10"]}, anchor="2026-09-06")
    text = cc.deadman_alert(b["kinds"]["tape"])
    assert text.startswith("tape has gone") and "lapsed on 2026-09-20" in text and "2026-09-06" in text


# ── 2. the daily plan names each due measurement until it is logged ───────────────────────
def _plan(monkeypatch, tape, battery_row):
    monkeypatch.setattr(cc, "table_readers", lambda table: {"tape": lambda: list(tape), "photos": lambda: ["2026-11-10"]})
    monkeypatch.setattr(ft, "calibration_row_from_table", lambda table, today: battery_row)
    return cc.plan_block(object(), "2026-11-11")


def test_a_due_tape_is_an_item_in_the_plan_through_the_dead_man_and_leaves_once_logged(monkeypatch):
    ok_battery = {"kind": ft.CALIBRATION_KIND, "state": "ok", "prompt": None}
    lapsed = _plan(monkeypatch, ["2026-09-06"], ok_battery)
    (item,) = lapsed["items"]
    assert item["kind"] == "tape" and item["state"] == cc.MISSED_2 and item["text"].startswith("Tape due")
    assert lapsed["read_failed"] == [] and lapsed["tier"] == "owner_only" and lapsed["instruction"]
    due_today = _plan(monkeypatch, ["2026-10-28"], ok_battery)  # 14 days ago: due today
    assert [(i["kind"], i["state"]) for i in due_today["items"]] == [("tape", cc.DUE)]
    assert _plan(monkeypatch, ["2026-11-05"], ok_battery)["items"] == []  # logged this cycle: gone


def test_the_overdue_battery_is_in_the_plan_with_its_one_write_door(monkeypatch):
    row = ft.calibration_row(_opening(7), ft.due(_opening(7), _pos(7), []))
    items = _plan(monkeypatch, ["2026-11-05"], row)["items"]
    assert [i["kind"] for i in items] == [ft.CALIBRATION_KIND]
    assert "get_exercise_notes action='fitness_test'" in items[0]["text"] and items[0]["text"].startswith("Fitness battery due")


def test_a_failed_read_is_named_never_an_empty_plan(monkeypatch):
    def boom():
        raise RuntimeError("denied")

    monkeypatch.setattr(cc, "table_readers", lambda table: {"tape": boom, "photos": boom})
    monkeypatch.setattr(ft, "calibration_row_from_table", lambda table, today: {"kind": ft.CALIBRATION_KIND, "state": cc.READ_FAILED})
    got = cc.plan_block(object(), "2026-11-11")
    assert got["read_failed"] == ["fitness_battery", "photos", "tape"] and got["items"] == []


def test_the_plan_field_rides_stage_1_and_fails_soft(monkeypatch):
    from mcp import plan_helpers

    src = (_REPO / "mcp" / "tools_plan.py").read_text(encoding="utf-8")
    assert re.search(r'out\["calibration_due"\]\s*=\s*calibration_due_field\(target_date\)', src)
    monkeypatch.setattr(cc, "plan_block", lambda table, today: (_ for _ in ()).throw(RuntimeError("x")))
    assert plan_helpers.calibration_due_field("2026-11-11") == {"state": "read_failed", "error": "RuntimeError", "items": None}


def test_the_plan_items_carry_dates_and_states_never_a_reading(monkeypatch):
    got = _plan(monkeypatch, ["2026-09-06"], ft.calibration_row(_opening(8), ft.due(_opening(8), _pos(8), [])))
    text = json.dumps(got, ensure_ascii=False)
    stripped = re.sub(r"\d{4}-\d{2}-\d{2}|missed_2", "", text)
    # what remains of the digits is the charter's protocol words (a 6-minute walk, a 20-minute bike, RPE 6) and the
    # program week — never a reading, a body number or a goal
    assert set(re.findall(r"\d+(?:\.\d+)?", stripped)) <= {"6", "20"}, re.findall(r"\d+(?:\.\d+)?", stripped)


# ── 4. the retro's Measurement row is done / due from the stored rows ─────────────────────
def test_the_retro_measurement_row_reads_done_over_due_from_stored_rows():
    from common.pacific_time import shift_day_key
    from training import block_retro as br

    window = br.block_window("2026-12-06")
    sundays = [shift_day_key(window["end"], -7 * k) for k in range(window["weeks"] - 1, -1, -1)]

    def row(sunday, i, taped, tested):
        waist = {"state": "measured", "value": {}, "date": sunday} if taped else {"state": "absent"}
        fit = {"state": "measured", "value": {"date": sunday}} if tested else {"state": "absent"}
        return {"week_start": shift_day_key(sunday, -6), "week_end": sunday, "waist": waist, "fitness_tests": fit}

    tape_every = tc.charter_value("calibration.tape_and_photos.every_weeks")
    due = window["weeks"] // tape_every + window["weeks"] // ft.every_weeks()
    none = br.assemble_evidence(window, may_rows=[row(s, i, False, False) for i, s in enumerate(sundays)])["calibration"]
    assert (none["due"]["value"], none["done"]["value"]) == (due, 0)
    full = [row(s, i, i % tape_every == tape_every - 1, i == len(sundays) - 1) for i, s in enumerate(sundays)]
    got = br.assemble_evidence(window, may_rows=full)["calibration"]
    assert (got["due"]["value"], got["done"]["value"]) == (due, due)
    measurement = br.code_scores(br.load_scorecard(), br.assemble_evidence(window, may_rows=full))["measurement"]
    assert measurement["score"] is not None
