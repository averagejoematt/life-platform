"""tests/test_disruption_mode_5088.py — the minimum viable day, disruption mode and the travel templates (#5088).

Owner ruling 2026-10-18: a late-December trip — resort/hotel gym and bodyweight variants of every session type,
steps held, two or three short sessions a week, then a step back up on return. The mode is HIS switch: the coach
offers it and never imposes it. Fixture = the wire: every variant compiles through `hevy_compiler` with the
template ids the committed movement catalog carries.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
from unittest.mock import patch

import pytest

os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

_REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "lambdas"))
sys.path.insert(0, str(_REPO))

from training import (
    disruption as d,  # noqa: E402
    training_charter as tc,  # noqa: E402
)

CATALOG = json.loads((_REPO / "config" / "movement_catalog.json").read_text())
MOVEMENTS = CATALOG["movements"]
WINDOW = {"label": "fixture trip", "start": "2026-12-20", "end": "2026-12-30"}


@pytest.fixture(autouse=True)
def _public_charter_only(monkeypatch):
    monkeypatch.delenv(tc.PRIVATE_ENV_VAR, raising=False)
    monkeypatch.setattr(tc, "_from_s3", lambda key: None)
    tc.reset_cache()
    yield
    tc.reset_cache()


def _record(start="2026-12-20", until="2026-12-30", template="travel"):
    return d.build_disruption_record(start_date=start, until=until, words="away for the holidays", template=template, recorded_at="t")


def _wire(movement_key: str) -> str:
    hint = MOVEMENTS[movement_key].get("hevy_template_id_hint")
    assert hint, f"{movement_key}: no Hevy template id in the catalog — it could not be pushed"
    return hint


# ── the charter shape ──────────────────────────────────────────────────────────────────────
def test_the_charter_carries_the_minimum_and_the_disruption_block_with_a_change_log_line():
    c = tc.load_charter()
    assert c["version"] == c["change_log"][-1]["version"]
    # the #5088 entry by content, not position: later lanes add entries after it
    assert [e["version"] for e in c["change_log"] if "#5088" in e["by"]] == ["1.2.0"]
    shape = d.minimum_shape()
    # the shape fits its own minutes: max movements x sets each x minutes per set
    assert shape["max_movements"] * shape["sets_per_movement"] * shape["est_minutes_per_set"] <= shape["minutes"]
    pol = d.policy()
    assert pol["owner_switched"] is True and pol["imposed"] is False
    assert set(pol["templates"]) == {"travel", "busy"}
    assert all(p in d.POOL_NAMES for t in pol["templates"].values() for p in t["pools"])
    # not on a published surface: the mode and the travel windows are engine/owner context
    assert "disruption" not in tc.public_view() and "minimum_session" not in (tc.public_view().get("split") or {})


def test_the_roles_are_the_charters_five_session_types_and_the_preview_names_every_one():
    roles = d.role_keys()
    assert len(roles) == len(tc.charter_value("split.sequence")) == tc.charter_value("split.lifting_days_per_wk")
    assert len(set(roles)) == len(roles)
    preview = d.templates_preview(MOVEMENTS)
    assert list(preview) == roles and all(set(p) == set(d.POOL_NAMES) for p in preview.values())
    assert not [(r, p) for r, pools in preview.items() for p, v in pools.items() if v["unresolved"] or not v["movements"]]


# ── (1) + (2): every role has a minimum and both variants, each compiling to the wire ─────
def test_every_role_has_a_minimum_and_both_variants_that_compile_with_catalog_template_ids():
    from training import hevy_compiler

    shape = d.minimum_shape()
    problems = []
    for role in d.role_keys():
        for pool in d.POOL_NAMES:
            rx = d.session(role, pool, MOVEMENTS)
            keys = [e["movement_key"] for e in rx["exposures"]]
            if rx["unresolved"] or not keys:
                problems.append(f"{role}/{pool}: unresolved {rx['unresolved']}")
                continue
            if rx["est_minutes"] > shape["minutes"] or len(keys) > shape["max_movements"]:
                problems.append(f"{role}/{pool}: {len(keys)} movements, ~{rx['est_minutes']} min over the charter's shape")
            if len(set(keys)) != len(keys):
                problems.append(f"{role}/{pool}: a movement twice {keys}")
            for e in rx["exposures"]:
                if [s["kind"] for s in e["sets"]] != ["top", "back_off"]:
                    problems.append(f"{role}/{pool}/{e['movement_key']}: not top set + one back-off")
            ir = d.to_routine(
                rx, target_date="2026-12-22", variant=d.PRIMARY_VARIANT, mode={"phase": "active", "template": "travel"}, catalog=CATALOG
            )
            asked: list = []
            body = hevy_compiler.to_create_body(ir, lambda k: asked.append(k) or _wire(k))
            wire = json.dumps(body)
            if asked != keys or len(body["routine"]["exercises"]) != len(keys) or not all(_wire(k) in wire for k in keys):
                problems.append(f"{role}/{pool}: compiled {asked} for {keys}")
            if len(ir.notes) > 150:
                problems.append(f"{role}/{pool}: session note {len(ir.notes)} chars (Hevy cuts ~150)")
    assert not problems, "\n".join(problems)


def test_the_variants_respect_their_equipment_and_every_movement_is_generator_eligible():
    from training.movement_catalog import generator_eligible

    problems = []
    for role in d.role_keys():
        for e in d.session(role, "hotel", MOVEMENTS)["exposures"]:
            m = MOVEMENTS[e["movement_key"]]
            if m.get("equipment") not in ("dumbbell", "kettlebell", "none"):
                problems.append(f"hotel {role}: {e['movement_key']} needs {m.get('equipment')}")
        for e in d.session(role, "bodyweight", MOVEMENTS)["exposures"]:
            m = MOVEMENTS[e["movement_key"]]
            if m.get("hevy_type") != "reps_only":
                problems.append(f"bodyweight {role}: {e['movement_key']} is {m.get('hevy_type')}, not a bodyweight rep movement")
        for pool in ("hotel", "bodyweight"):
            for e in d.session(role, pool, MOVEMENTS)["exposures"]:
                if not generator_eligible(MOVEMENTS[e["movement_key"]], 2):
                    problems.append(f"{pool} {role}: {e['movement_key']} not generator_eligible")
    assert not problems, "\n".join(problems)


def test_a_lower_day_away_from_the_club_fills_its_saved_time_with_a_single_leg_slot_and_a_carry():
    for role in [r for r in d.role_keys() if d.role_archetype(r) == "lower"]:
        assert [e["pattern"] for e in d.session(role, "hotel", MOVEMENTS)["exposures"]][-2:] == ["single_leg", "carry"], role
        assert not [e for e in d.session(role, "gym_minimum", MOVEMENTS)["exposures"] if e["kind"] != "anchor"], role


def test_every_pool_key_names_a_catalogued_movement_and_no_plyometric_one():
    missing = [k for pools in d.POOLS.values() for keys in pools.values() for k in keys if k not in MOVEMENTS]
    assert not missing
    assert not [k for pools in d.POOLS.values() for keys in pools.values() for k in keys if "jump" in k or "plyo" in k]


def test_every_anchor_pattern_the_program_uses_has_a_hotel_and_a_bodyweight_pool():
    from training import program_structure

    patterns = {p for t in program_structure.SESSION_TEMPLATES.values() for p, _ in t["anchors"]}
    patterns |= {p for r in d.FALLBACK_ROLE_ANCHORS.values() for p, _ in r}
    assert not [p for p in patterns if not (d.POOLS.get(p) or {}).get("hotel") or not (d.POOLS.get(p) or {}).get("bodyweight")]


# ── (3) the switch, the hold, the step back up ─────────────────────────────────────────────
def test_the_switch_turns_on_holds_habits_and_steps_back_up_then_off():
    recs = [_record()]
    assert d.state(recs, "2026-12-19")["phase"] == "off"
    on = d.state(recs, "2026-12-20")
    assert on["phase"] == "active" and on["template"] == "travel" and on["pools"] == ["hotel", "bodyweight"]
    assert d.state(recs, "2026-12-30")["phase"] == "active"
    days = d.policy()["step_back_up"]["days"]
    from common.pacific_time import shift_day_key

    assert d.state(recs, "2026-12-31")["phase"] == "step_back_up"
    assert d.state(recs, "2026-12-31")["pools"][0] == "gym_minimum"
    assert d.state(recs, shift_day_key("2026-12-30", days))["phase"] == "step_back_up"
    assert d.state(recs, shift_day_key("2026-12-30", days + 1))["phase"] == "off"
    block = d.constraint("2026-12-22", recs, [])
    assert block["active"] is True and block["offer"] is None
    held = {h["habit"]: h for h in block["holds"]}
    assert set(held) == {"steps", "protein", "sleep", "session"}
    assert held["steps"]["floor"] == tc.charter_value("steps.floor")
    assert held["session"]["sessions_per_wk"] == tc.charter_value("disruption.templates.travel.sessions_per_wk")


def test_switching_it_off_early_starts_the_step_back_up_from_the_first_day_back():
    ended = d.end_record(_record(), ended_on="2026-12-26", words="home early", recorded_at="t")
    assert d.state([ended], "2026-12-25")["phase"] == "active"
    assert d.state([ended], "2026-12-26")["phase"] == "step_back_up"
    with pytest.raises(ValueError):
        d.end_record(_record(), ended_on="2026-12-26", words="", recorded_at="t")


def test_a_record_without_his_words_or_with_a_bad_shape_is_refused():
    base = {"start_date": "2026-12-20", "until": "2026-12-30", "words": "away", "template": "travel", "recorded_at": "t"}
    bad = [{"words": ""}, {"template": "vacation"}, {"until": "2026-12-19"}, {"until": "2027-03-01"}, {"start_date": "next week"}]
    accepted = []
    for kwargs in bad:
        try:
            d.build_disruption_record(**{**base, **kwargs})
            accepted.append(kwargs)
        except ValueError:
            pass
    assert not accepted, f"accepted a record it must refuse: {accepted}"
    assert d.build_disruption_record(**base)["sk"] == "MODE#disruption#2026-12-20"


def test_the_weekly_band_on_travel_stops_drafting_once_it_is_met():
    recs = [_record()]
    st = d.state(recs, "2026-12-27")
    rows = [
        {"date": day, "exercises": [{"title": "Push Up", "sets": [{"reps": 12}]}]} for day in ("2026-12-21", "2026-12-23", "2026-12-25")
    ]
    assert d.sessions_due(st, "2026-12-27", rows)["due"] is False
    assert d.sessions_due(st, "2026-12-27", rows[:1])["due"] is True


# ── the draft path ─────────────────────────────────────────────────────────────────────────
def _generate(disruption_records):
    from training.routine_generator import GeneratorInputs, generate_routines

    with patch("training.routine_generator._load_note_indexes", return_value=({}, {}, {}, {})):
        return generate_routines(
            GeneratorInputs(target_date="2026-12-22", block_workouts=[], deload_records=[], disruption_records=disruption_records)
        )


def test_the_generator_serves_the_variant_pool_while_the_mode_is_on_and_the_split_when_it_is_not():
    on = _generate([_record()])
    assert [r.variant for r in on] == [d.PRIMARY_VARIANT, "floor"]
    assert on[0].inputs_snapshot["disruption"]["pool"] == "hotel" and on[1].inputs_snapshot["disruption"]["pool"] == "bodyweight"
    assert on[0].inputs_snapshot["charter_version"] == tc.charter_version()
    off = _generate([])
    assert "ideal" in [r.variant for r in off] and d.PRIMARY_VARIANT not in [r.variant for r in off]


def test_the_step_back_up_week_serves_the_club_minimum():
    rs = _generate([_record(start="2026-12-10", until="2026-12-18")])
    assert rs[0].variant == d.PRIMARY_VARIANT and rs[0].inputs_snapshot["disruption"]["pool"] == "gym_minimum"
    assert rs[0].inputs_snapshot["disruption"]["phase"] == "step_back_up"


def test_the_short_session_asserts_no_load_floor_and_is_hidden_from_the_public_routine_door():
    from web import site_api_protocols

    from mcp import hevy_prescription_gate

    assert d.PRIMARY_VARIANT in hevy_prescription_gate.NO_LOAD_VARIANTS
    assert d.PRIMARY_VARIANT in site_api_protocols._ROUTINE_HIDDEN_VARIANTS
    gate = hevy_prescription_gate.prescription_gate(_generate([_record()])[0])
    assert gate["verdict"] == "skipped"


# ── (4) the coach offers, never imposes ────────────────────────────────────────────────────
def test_a_fixture_travel_window_is_offered_and_never_applies_itself():
    off = d.offer("2026-12-18", block_workouts=[], windows=[WINDOW])
    assert off["offered"] is True and off["applies"] is False and off["template"] == "travel"
    assert d.offer("2026-12-10", block_workouts=[], windows=[WINDOW])["offered"] is False
    # an offer is not a mode: with no record the plan is the full split
    block = d.constraint("2026-12-22", [], [], windows=[WINDOW])
    assert block["active"] is False and block["phase"] == "off" and block["offer"]["offered"] is True
    assert d.PRIMARY_VARIANT not in [r.variant for r in _generate([])]


def test_the_charters_null_dated_window_is_pending_never_offered_or_guessed():
    # A fixture null-dated window, not the live charter's: the owner dates the trip before December (#5088).
    off = d.offer("2026-12-24", block_workouts=[], windows=[{"label": "x", "start": None, "end": None}])
    assert off["offered"] is False
    assert off["pending_windows"] and "dates pending the owner" in off["pending_windows"][0]


def test_a_missed_session_streak_offers_the_busy_template():
    rows = [{"date": "2026-11-01", "exercises": [{"sets": [{"reps": 5, "weight_kg": 100}]}]}]
    gap = d.policy()["offer"]["missed_session_days"]
    from common.pacific_time import shift_day_key

    assert d.offer(shift_day_key("2026-11-01", gap), block_workouts=rows, windows=[])["template"] == "busy"
    assert d.offer(shift_day_key("2026-11-01", gap - 1), block_workouts=rows, windows=[])["offered"] is False
    assert d.offer("2026-11-20", block_workouts=None, windows=[])["missed_session_read"] is False


def test_the_plan_packet_carries_the_disruption_block():
    from training import plan_engine

    assert "disruption_records" in plan_engine.ENGINE_INPUTS
    block = plan_engine.constraint_block(date="2026-12-22", block_workouts=[], disruption_records=[_record()])
    assert block["disruption"]["active"] is True and block["disruption"]["template"] == "travel"
    assert set(block["disruption"]) >= {"active", "template", "until", "offer"}


def test_the_nightly_predraft_drafts_nothing_once_the_travel_week_is_met():
    from mcp import nightly_predraft

    rows = [{"date": day, "exercises": [{"sets": [{"reps": 12}]}]} for day in ("2026-12-21", "2026-12-23", "2026-12-25")]
    with (
        patch("training.disruption.load_records_failsoft", return_value=[_record()]),
        patch.object(nightly_predraft, "_block_record", return_value=rows),
    ):
        mode = nightly_predraft._disruption("2026-12-27")
    assert mode["phase"] == "active" and mode["due"] is False
    assert d.PRIMARY_VARIANT in nightly_predraft.GENERATOR_VARIANTS


def test_the_chat_write_path_records_his_words_and_refuses_without_them(monkeypatch):
    from mcp import tools_training_notes as tn

    written = []
    monkeypatch.setattr(tn, "_put_disruption", lambda rec: written.append(rec))
    refused = tn.tool_get_exercise_notes({"action": "disruption", "until": "2026-12-30", "template": "travel", "start_date": "2026-12-20"})
    assert refused["wrote"] is False and not written
    ok = tn.tool_get_exercise_notes(
        {"action": "disruption", "until": "2026-12-30", "template": "travel", "start_date": "2026-12-20", "words": "away for the holidays"}
    )
    assert ok["wrote"] is True and written[0]["sk"] == "MODE#disruption#2026-12-20" and written[0]["words"] == "away for the holidays"
    monkeypatch.setattr(tn, "_disruption_records", lambda: [dict(written[0])])
    ended = tn.tool_get_exercise_notes({"action": "disruption_end", "ended_on": "2026-12-27", "words": "back early"})
    assert ended["wrote"] is True and written[-1]["ended_on"] == "2026-12-27"
