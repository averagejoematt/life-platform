"""tests/test_logging_conventions_5373.py — the carry definition layer: a carry's 'yards' are the owner's STEP COUNT, converted
to a labelled estimated distance by his watch stride, and a per-exercise load convention (total carried vs per hand) every
load reader resolves through (#5373).

Every value here is SYNTHETIC (the public repo carries no real loads, strides or health values). The Hevy wire is the #5372
fixture (`fixtures/hevy_farmers_walk_wire_5372.json`, invented values in the live payload's shape), normalised through the
real `hevy_common.normalize_workout`; the stride rows are invented apple_health DATE rows.
"""

from __future__ import annotations

import ast
import json
import os
import pathlib
import re
import sys

import pytest

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")  # mcp.config requires these at import
os.environ.setdefault("USER_ID", "matthew")

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "lambdas"))

from common import hevy_schema  # noqa: E402
from training import (  # noqa: E402
    carry_line as cl,  # noqa: E402
    hevy_common,
    load_progression,
    logging_conventions as lc,  # noqa: E402
    panel_rubric,
    routine_ir,
)
from training.muscle_volume import normalize_hevy_items, working_sets_by_muscle  # noqa: E402

from mcp import coach_packet_today, strength_helpers, tools_hevy  # noqa: E402

WIRE = json.loads((REPO / "tests" / "fixtures" / "hevy_farmers_walk_wire_5372.json").read_text())
CATALOG = json.loads((REPO / "config" / "movement_catalog.json").read_text())["movements"]
WALK_TID = "50C613D0"
DAY = "2026-10-25"


def _stride_rows(values: list[float], end: str = "2026-10-24") -> list[dict]:
    """Synthetic apple_health DATE rows, one per day backwards from `end`."""
    from common.pacific_time import shift_day_key

    return [{"sk": f"DATE#{shift_day_key(end, -i)}", lc.STRIDE_FIELD: v} for i, v in enumerate(values)]


STRIDE_ROWS = _stride_rows([28.0, 29.0, 30.0, 31.0, 32.0])  # median 30.0 in -> 60 steps = 50 yd


def _stored() -> dict:
    return {**hevy_common.normalize_workout(WIRE), "workout_uid": "hevy:" + WIRE["id"], "date": DAY}


# ── box 1 + box 3: the catalog fields ──────────────────────────────────────────────────────────────────────────────────
def test_the_farmers_walk_carries_both_conventions():
    walk = CATALOG["farmers_walk"]
    assert walk["hevy_template_id_hint"] == WALK_TID
    # #5373 (owner, 2026-10-27): the CURRENT convention is one hand; the two sessions logged as a total read through the history
    assert walk[lc.DISTANCE_UNIT_FIELD] == lc.STEPS and walk[lc.LOAD_CONVENTION_FIELD] == lc.PER_HAND
    assert walk[lc.LOAD_HISTORY_FIELD] == [{"until": "2026-10-26", "convention": lc.TOTAL_CARRIED}]


def test_every_loaded_distance_entry_is_steps_and_nothing_else_is():
    """Mutation: drop the field from one short_distance_weight entry, or put it on a treadmill — this reds."""
    steps = {k for k, v in CATALOG.items() if v.get(lc.DISTANCE_UNIT_FIELD) == lc.STEPS}
    loaded_distance = {k for k, v in CATALOG.items() if v.get("hevy_type") == "short_distance_weight"}
    assert steps == loaded_distance and "farmers_walk" in steps
    assert not any(v.get(lc.DISTANCE_UNIT_FIELD) for v in CATALOG.values() if v.get("hevy_type") == "distance_duration")


def test_every_stored_convention_is_what_the_derivation_computes():
    """The builder writes `derive_conventions`; a stored value that disagrees (or a missing one) is drift."""
    offenders = []
    for key, entry in CATALOG.items():
        want = lc.derive_conventions(entry)
        got = {f: entry[f] for f in (lc.DISTANCE_UNIT_FIELD, lc.LOAD_CONVENTION_FIELD, lc.LOAD_HISTORY_FIELD) if f in entry}
        if got != want:
            offenders.append((key, got, want))
    assert offenders == []


def test_bilateral_dumbbells_are_per_hand_and_one_implement_is_as_logged():
    by_title = {v["title"]: v for v in CATALOG.values()}
    assert lc.load_convention_of(by_title["Bench Press (Dumbbell)"], day=DAY) == lc.PER_HAND
    assert lc.load_convention_of(by_title["Lateral Raise (Dumbbell)"], day=DAY) == lc.PER_HAND
    for one in ("Goblet Squat", "Dumbbell Row", "Pullover (Dumbbell)", "Concentration Curl"):
        assert lc.load_convention_of(by_title[one], day=DAY) == lc.AS_LOGGED, one
    assert lc.load_convention_of(by_title["Squat (Barbell)"], day=DAY) == lc.AS_LOGGED
    assert lc.load_convention_of(by_title["Suitcase Carry"], day=DAY) == lc.TOTAL_CARRIED  # one dumbbell: total = one hand


def test_a_written_value_wins_over_the_derivation():
    assert (
        lc.load_convention_of({"title": "Bench Press (Dumbbell)", "equipment": "dumbbell", lc.LOAD_CONVENTION_FIELD: None}, day=DAY)
        == lc.AS_LOGGED
    )
    assert lc.distance_unit_of({"hevy_type": "short_distance_weight", lc.DISTANCE_UNIT_FIELD: None}) is None


def test_the_builder_writes_the_conventions_and_keeps_a_hand_written_one():
    import importlib.util

    spec = importlib.util.spec_from_file_location("bmc_5373", REPO / "deploy" / "build_movement_catalog.py")
    bmc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bmc)
    meta = {
        "50C613D0": {
            "id": "50C613D0",
            "title": "Farmers Walk",
            "type": "short_distance_weight",
            "primary_muscle_group": "full_body",
            "equipment": "other",
        },
        "AAAA5373": {
            "id": "AAAA5373",
            "title": "Curl (Dumbbell)",
            "type": "weight_reps",
            "primary_muscle_group": "biceps",
            "equipment": "dumbbell",
        },
    }
    hist = {
        "workouts": 2,
        "first": "2026-01-01",
        "last": "2026-10-25",
        "templates": {t: {"sessions": 1, "first_done": "2026-01-01", "last_done": "2026-10-25", "names": {"x": 1}} for t in meta},
    }
    current = {
        "movements": {
            "curl_kept": {"title": "Curl (Dumbbell)", "hevy_template_id_hint": "AAAA5373", lc.LOAD_CONVENTION_FIELD: "total_carried"}
        }
    }
    out = bmc.build_catalog(current, hist, meta)
    walk = next(v for v in out["movements"].values() if v["hevy_template_id_hint"] == "50C613D0")
    assert walk[lc.DISTANCE_UNIT_FIELD] == lc.STEPS and walk[lc.LOAD_CONVENTION_FIELD] == lc.PER_HAND
    assert walk[lc.LOAD_HISTORY_FIELD] == [{"until": lc.CARRY_TOTAL_UNTIL, "convention": lc.TOTAL_CARRIED}]
    assert out["movements"]["curl_kept"][lc.LOAD_CONVENTION_FIELD] == "total_carried"  # written by a human: kept
    assert json.dumps(bmc.build_catalog(out, hist, meta)) == json.dumps(out)  # idempotent
    assert "logging_conventions" in out["_rules"]


# ── the runtime resolver ──────────────────────────────────────────────────────────────────────────────────────────────
def test_the_resolver_reads_the_catalog_by_template_id_then_title_then_the_set_shape():
    carry_sets = [{"type": "normal", "weight_kg": 30.0, "reps": None, "distance_m": 40}]
    assert lc.is_step_count("anything", WALK_TID) and lc.load_convention_for("anything", WALK_TID, day=DAY) == lc.TOTAL_CARRIED
    assert lc.is_step_count("Farmers Walk") and lc.load_convention_for("Lateral Raise (Dumbbell)", day=DAY) == lc.PER_HAND
    # not catalogued: a loaded, reps-less distance set IS the step-count type
    assert lc.is_step_count("Sled Drag (synthetic)", "ZZZZ0000", carry_sets)
    assert not lc.is_step_count("Treadmill (synthetic)", "ZZZZ0001", [{"type": "normal", "distance_m": 2400, "duration_sec": 1200}])
    assert hevy_schema.loaded_distance_shape(carry_sets) and not hevy_schema.loaded_distance_shape([{"reps": 8, "weight_kg": 20}])
    from decimal import Decimal  # a DynamoDB read hands back Decimal

    assert hevy_schema.loaded_distance_shape([{"type": "normal", "weight_kg": Decimal("30"), "reps": None, "distance_m": Decimal("40")}])
    dec_rows = [{**r, lc.STRIDE_FIELD: Decimal(str(r[lc.STRIDE_FIELD]))} for r in STRIDE_ROWS]
    assert lc.trailing_stride(dec_rows, DAY)["stride_in"] == 30.0


def test_a_failed_catalog_read_falls_back_to_the_derivation(monkeypatch):
    monkeypatch.setattr(lc, "config_path", lambda *_a: "/nonexistent/movement_catalog.json")
    import boto3

    monkeypatch.setattr(boto3, "client", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no s3 in this test")))
    lc.set_catalog(None)
    try:
        assert lc.catalog_movements() == {}
        assert lc.load_convention_for("Bench Press (Dumbbell)", day=DAY) == lc.PER_HAND  # the title still answers
        assert lc.is_step_count("Farmers Walk", WALK_TID, [{"type": "normal", "weight_kg": 30.0, "distance_m": 40}])
    finally:
        lc.set_catalog(None)


# ── box 2: the stride and the estimated distance ─────────────────────────────────────────────────────────────────────
def test_the_stride_is_the_median_of_the_14_completed_days_before_the_day():
    stride = lc.trailing_stride(
        STRIDE_ROWS + [{"sk": f"DATE#{DAY}", lc.STRIDE_FIELD: 99.0}, {"sk": "DATE#2026-10-01", lc.STRIDE_FIELD: 1.0}], DAY
    )
    assert stride["state"] == "measured" and stride["stride_in"] == 30.0 and stride["n_days"] == 5  # the day itself + day 24 back excluded
    assert stride["window"] == {"start": "2026-10-11", "end": "2026-10-24"} and "UNLOADED" in stride["basis"]


def test_too_few_stride_days_or_a_failed_read_is_steps_only():
    thin = lc.trailing_stride(STRIDE_ROWS[:4], DAY)
    assert thin["state"] == "insufficient" and thin["stride_in"] is None
    failed = lc.trailing_stride(None, DAY)
    assert failed["state"] == "read_failed"
    for s in (thin, failed, None):
        assert lc.render_steps(60, s) == "60 steps" and lc.estimated_yards(60, s) is None


def test_the_rendered_line_names_the_estimate():
    stride = lc.trailing_stride(STRIDE_ROWS, DAY)
    assert lc.render_steps(60, stride) == "60 steps (~50 yd, est. from unloaded stride)"
    assert lc.estimated_yards(62, stride) == 52 and lc.estimated_yards(58, stride) == 48


def test_the_carry_line_carries_the_conventions_and_the_rendered_sets():
    ex = next(e for e in _stored()["exercises"] if e["name"] == "Farmers Walk")
    line = cl.carry_line(ex["name"], ex["sets"], template_id=ex["template_id"], stride=lc.trailing_stride(STRIDE_ROWS, DAY), day=DAY)
    assert line["load_convention"] == lc.TOTAL_CARRIED and line["distance_unit"] == lc.STEPS
    assert line["rendered"] == [
        "60 steps (~50 yd, est. from unloaded stride)",
        "62 steps (~52 yd, est. from unloaded stride)",
        "58 steps (~48 yd, est. from unloaded stride)",
    ]
    assert cl.carry_line(ex["name"], ex["sets"], day=DAY)["rendered"] == ["60 steps", "62 steps", "58 steps"]  # no stride: steps only


def test_get_workout_detail_renders_steps_plus_the_estimated_distance(monkeypatch):
    row = {**_stored(), "source": "hevy", "source_workout_id": WIRE["id"]}
    reads = []

    def _q(source, start, end, include_pilot=None):
        reads.append(source)
        return [row] if source == "hevy" else STRIDE_ROWS if source == "apple_health" else []

    monkeypatch.setattr(tools_hevy, "query_source_range", _q)
    out = tools_hevy.tool_get_workout_detail({"workout_uid": "hevy:" + WIRE["id"]})["workout"]
    walk = out["carries"][0]
    assert walk["rendered"][0] == "60 steps (~50 yd, est. from unloaded stride)" and walk["load_convention"] == lc.TOTAL_CARRIED
    assert out["logging_conventions"] == lc.CONVENTIONS_LINE and reads.count("apple_health") == 1


def test_get_workout_detail_with_an_unreadable_stride_is_steps_only(monkeypatch):
    row = {**_stored(), "source": "hevy", "source_workout_id": WIRE["id"]}

    def _q(source, start, end, include_pilot=None):
        if source == "apple_health":
            raise RuntimeError("synthetic read failure")
        return [row]

    monkeypatch.setattr(tools_hevy, "query_source_range", _q)
    walk = tools_hevy.tool_get_workout_detail({"workout_uid": "hevy:" + WIRE["id"]})["workout"]["carries"][0]
    assert walk["rendered"] == ["60 steps", "62 steps", "58 steps"] and walk["stride"]["state"] == "read_failed"


def test_the_packet_today_block_renders_the_carry(monkeypatch):
    row = {**_stored(), "sk": f"DATE#{DAY}#WORKOUT#{WIRE['id']}"}
    value, _status = coach_packet_today.today_view(
        "2026-10-26",
        today="2026-10-26",
        read_hevy=lambda d: [row],
        read_strava=lambda d: [],
        read_stride=lambda d: lc.trailing_stride(STRIDE_ROWS, d),
    )
    hevy = next(a for a in value["activities"] if a["source"] == "hevy")
    assert hevy["carries"][0]["rendered"][0] == "60 steps (~50 yd, est. from unloaded stride)"
    assert hevy["carries"][0]["load_convention"] == lc.TOTAL_CARRIED
    assert value["logging_conventions"] == lc.CONVENTIONS_LINE and value["carry_stride"]["state"] == "measured"


def test_the_routine_note_renders_the_estimate_and_his_rule():
    from training import session_cues

    sets = [{"kind": "working", "distance_meters": 60}, {"kind": "working", "distance_meters": 60}]
    cue = session_cues.exposure_cue("carry", sets, stride=lc.trailing_stride(STRIDE_ROWS, DAY))
    assert "2 carries of 60 steps (~50 yd, est. from unloaded stride)" in cue
    assert "count steps, type the count in yards" in cue and "load: per hand (one dumbbell's weight)" in cue
    bare = session_cues.exposure_cue("carry", sets)
    assert "2 carries of 60 steps @" in bare and "est. from unloaded stride" not in bare  # no stride: steps only


def test_the_generator_renders_the_stride_into_the_carry_block_note():
    from training import full_body_session, program_structure

    rx = {
        "exposures": [
            {
                "kind": "accessory",
                "movement_key": "farmers_walk",
                "intensity": "carry",
                "rest_seconds": 90,
                "pattern": "carry",
                "sets": [{"kind": "working", "distance_meters": 60}],
            }
        ]
    }
    blocks, used, _ = full_body_session._blocks_from_prescription(
        rx, {"movements": CATALOG}, None, "off", stride=lc.trailing_stride(STRIDE_ROWS, DAY)
    )
    assert "60 steps (~50 yd, est. from unloaded stride)" in blocks[0].notes and "type the count in yards" in blocks[0].notes
    assert blocks[0].sets[0].distance_meters == 60 and used[0]["cue"] in blocks[0].notes
    assert "est. from unloaded stride" not in program_structure.exposure_cue("carry", rx["exposures"][0]["sets"])  # the static spec cue


# ── box 3: every load reader resolves through the convention ─────────────────────────────────────────────────────────
def _workout(name: str, tid: str, weight_kg: float, reps: int, n: int = 1) -> dict:
    return {
        "sk": f"DATE#{DAY}#WORKOUT#w-{tid}",
        "date": DAY,
        "title": "t",
        "exercises": [{"name": name, "template_id": tid, "sets": [{"type": "normal", "weight_kg": weight_kg, "reps": reps}] * n}],
    }


def test_muscle_volume_counts_a_per_hand_dumbbell_load_twice_and_a_carry_not_at_all():
    db = working_sets_by_muscle(normalize_hevy_items([_workout("Bicep Curl (Dumbbell)", "37FCC2BB", 10.0, 10)]))
    bb = working_sets_by_muscle(normalize_hevy_items([_workout("Bicep Curl (Barbell)", "A5AC6449", 10.0, 10)]))
    per_set_lb = round(10.0 * 2.20462 * 10)
    assert db["muscles"]["Biceps"]["volume_lbs"] == pytest.approx(2 * per_set_lb, abs=1)
    assert bb["muscles"]["Biceps"]["volume_lbs"] == pytest.approx(per_set_lb, abs=1)
    walk = working_sets_by_muscle(normalize_hevy_items([{**_stored(), "sk": f"DATE#{DAY}#WORKOUT#x"}]))
    assert "both hands" in walk["volume_basis"]
    assert walk["muscles"]["Core"]["direct_sets"] == 3 and walk["muscles"]["Core"]["volume_lbs"] == 0.0  # the carry: no reps, no tonnage


def test_the_normaliser_names_the_convention_on_each_exercise():
    norm = normalize_hevy_items([{**_stored(), "sk": f"DATE#{DAY}#WORKOUT#x"}])[0]
    by = {e["name"]: e for e in norm["exercises"]}
    assert by["Farmers Walk"]["load_convention"] == lc.TOTAL_CARRIED and by["Lateral Raise (Dumbbell)"]["load_convention"] == lc.PER_HAND
    plain = normalize_hevy_items([_workout("Squat (Barbell)", "D04AC939", 100.0, 5)])[0]["exercises"][0]
    assert "load_convention" not in plain  # as logged: nothing to say


def test_strength_helpers_session_volume_is_the_total_and_the_best_weight_as_logged():
    item = _workout("Bench Press (Dumbbell)", "3601968B", 20.0, 10, n=2)
    s = strength_helpers.extract_hevy_sessions([item], "", template_id="3601968B")[0]
    lb = round(20.0 * 2.20462, 2)
    assert s["load_convention"] == lc.PER_HAND and s["best_weight"] == pytest.approx(lb, abs=0.1)
    assert s["volume_lbs"] == pytest.approx(2 * lb * 10 * 2, abs=0.5)


def test_load_progression_labels_every_load_with_its_convention():
    sessions = [
        {"date": "2026-10-20", "sets": [{"weight_kg": 20.0, "reps": 12, "rpe": 7.0}] * 3},
        {"date": "2026-10-16", "sets": [{"weight_kg": 20.0, "reps": 12, "rpe": 7.0}] * 3},
    ]
    rule = {"kind": "double_progression", "consecutive_same_type_exposures": 2, "step_lb": 5, "step_pct": 2.5}
    limits = {
        "tolerance_rpe": 0.5,
        "compound": {"ceiling_rpe": 8.0, "limit_rpe": 8.5},
        "last_isolation_set": {"ceiling_rpe": 9.0, "limit_rpe": 9.5},
    }  # synthetic bands: the label is under test, not the charter's numbers
    kw = dict(current_kg=20.0, rep_range=(8, 12), cls="isolation", rule=rule, limits=limits)
    per_hand = load_progression.next_prescription(sessions, load_convention=lc.PER_HAND, **kw)
    plain = load_progression.next_prescription(sessions, **kw)
    assert per_hand["basis"] == load_progression.BASIS_STEP, per_hand
    assert per_hand["load_convention"] == lc.PER_HAND and plain["load_convention"] == lc.AS_LOGGED
    assert per_hand["next_load_kg"] == plain["next_load_kg"]  # the rule never converts: Hevy takes the per-hand number back
    assert re.search(r"\d+ lb per hand", per_hand["reason"]) and "per hand" not in plain["reason"]
    assert load_progression._lb(40.0, lc.TOTAL_CARRIED).endswith(" lb total carried") and load_progression._lb(40.0).endswith(" lb")


def test_the_weekly_tonnage_counts_a_per_hand_load_twice(monkeypatch):
    from mcp import tools_training

    hevy = [_workout("Bench Press (Dumbbell)", "3601968B", 20.0, 10)]
    monkeypatch.setattr(tools_training, "query_source", lambda src, s, e, *a, **k: hevy if src == "hevy" else [])
    monkeypatch.setattr(tools_training, "_zone2_by_iso_week", lambda *a, **k: {})
    out = tools_training._get_training_periodization({"start_date": "2026-10-19", "end_date": "2026-10-25"})
    text = json.dumps(out)
    want = round(20.0 * 2.20462 * 10 * 2)
    vols = [float(v) for v in re.findall(r'"volume_lbs": ([0-9.]+)', text)]
    assert vols and any(abs(v - want) <= 1 for v in vols), vols


# ── the distance readers (the 2026-10-26 Set additions) ──────────────────────────────────────────────────────────────
def test_the_vacation_fund_never_sums_a_carry_into_miles(monkeypatch):
    from content import vacation_fund

    treadmill = {"name": "Treadmill", "template_id": "243710DE", "sets": [{"type": "normal", "distance_m": 1609.344, "duration_sec": 900}]}
    row = {**_stored(), "exercises": _stored()["exercises"] + [treadmill]}
    monkeypatch.setattr(vacation_fund, "_query_range", lambda src, s, e: [row])
    assert vacation_fund._hevy_miles(DAY, DAY) == 1.0  # the treadmill mile only — the 180 steps are not 180 m


def test_tdee_never_reads_a_carry_distance_as_a_walk(monkeypatch):
    from health import tdee

    timed = {"exercises": [{"name": "Farmers Walk", "sets": [{"type": "normal", "weight_kg": 40.0, "distance_m": 60, "duration_sec": 45}]}]}
    out = tdee.worked_set_seconds([timed])
    assert out["cardio_seconds"] == 0 and out["measured_seconds"] == 45.0  # a timed carry is a hold-like worked set, not cardio
    untimed = tdee.worked_set_seconds([_stored()])
    assert untimed["cardio_seconds"] == 0 and untimed["assumed_seconds"] == (3 + 3) * tdee.WORK_SECONDS_PER_REP_SET  # 3 raises + 3 carries


def test_tdee_still_imports_nothing_from_training():
    tree = ast.parse((REPO / "lambdas" / "health" / "tdee.py").read_text(encoding="utf-8"))
    assert not any(n.module and "training" in n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom))


def test_the_panel_judge_reads_steps_not_question_mark_reps():
    sets = [routine_ir.Set(type="normal", distance_meters=60), routine_ir.Set(type="normal", distance_meters=60)]
    assert panel_rubric._set_line(sets, CATALOG["farmers_walk"]) == "2 x 60 steps"
    timed = [routine_ir.Set(type="normal", duration_seconds=45)]
    assert panel_rubric._set_line(timed) == "1 x 45 s"
    db = [routine_ir.Set(type="normal", rep_range_start=8, rep_range_end=12, weight_kg=20.0)]
    assert panel_rubric._set_line(db, CATALOG["farmers_walk"] | {lc.LOAD_CONVENTION_FIELD: lc.PER_HAND}).endswith("lb per hand")
    assert "?" not in panel_rubric._set_line(sets, CATALOG["farmers_walk"])


# ── box 4: one line in the skill and the coach context ───────────────────────────────────────────────────────────────
def _ws(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def test_the_coach_session_skill_states_both_conventions_in_the_one_line():
    skill = (REPO / ".claude" / "skills" / "coach-session" / "SKILL.md").read_text(encoding="utf-8")
    assert _ws(lc.CONVENTIONS_LINE) in _ws(skill)


def test_the_coach_context_states_both_conventions_in_the_one_line():
    from training import coach_context

    ctx = coach_context.assemble("2026-10-26", packet=None, constraint_block=None)
    assert ctx["logging_conventions"]["line"] == lc.CONVENTIONS_LINE
    assert lc.CONVENTIONS_LINE in ctx["text"] and coach_context.summary(ctx)["logging_conventions"] == lc.CONVENTIONS_LINE
    pub = coach_context.assemble("2026-10-26", packet=None, constraint_block=None, published=True)
    assert lc.CONVENTIONS_LINE in pub["text"]  # a rule with no value: safe on a published prompt


def test_the_line_says_steps_total_and_per_hand():
    line = lc.CONVENTIONS_LINE.lower()
    assert "step count" in line and "total carried" in line and "per hand" in line and "each hand" in line
    assert "2026-10-27" in line  # the dated rule


# premerge-gate: 5373: reads `config/movement_catalog.json`, which `deploy/build_movement_catalog.py` regenerates — a PR landing a rebuilt catalog must red on itself if a carry loses `distance_unit_convention: steps` or a stored convention drifts from `logging_conventions.derive_conventions`.
