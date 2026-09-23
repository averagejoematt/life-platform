"""tests/test_v03_nearest_band_anchor_4107.py — the v0.3 anchor when the current band has none.

WHY THIS FILE EXISTS (#4107)

#4090 put v0.3 §3's entry ramp on every loaded exercise, but the ramp re-bases a band
anchor, and at 315 lb (band 310–319) the three heavy anchors of Thursday 2026-09-24 —
leg press, flat DB bench, machine row — have no session in that band. The floor returned
`no_band_matched_history`, so they came out UNLOADED. Two residuals rode with it: the chat
path (`draft_custom` -> commit gate) still judged a routine against the 100 % best-load
floor, and an anchor set THIS cycle (pulldown, 09-20) was discounted as if detrained.

What these tests hold:

  1. FALLBACK — the heavy squat with 0 in-band / 4 out-of-band sessions gets a week-1 load
     at 60–65 % of the discounted NEAREST-band anchor, and the row names it (`anchor_band`,
     `anchor_date`, `fallback: nearest_band`). Mutation control: no fallback -> unloaded.
     (#4080: owner option B exempts the squat/hinge/bench/row families from skill_ceiling 2,
     so the 09-24 heavy squat is `squat_barbell` — its first key — not the leg press #4107
     was written against. The fallback rule is movement-agnostic; only the fixture moved.)
  2. NEAREST, not most-evidenced — a nearer band with one session beats a farther band
     with 25 (resolve_band's walking-volume pass must not rank load anchors).
  3. THE DISCOUNT HAS AN AGE — 28 d before block 1 or older: discounted; younger: not.
     Mutation control: an age of 0 discounts the this-cycle anchor again.
  4. ONE LOAD PATH — the chat commit gate derives the same rows the generator applies;
     a draft_custom routine at the generator's loads commits, one under them refuses;
     and by AST nothing but `load_ramp.v03_floor` calls the ramp or the fallback.
  5. THE PLANNER — `plan_next_session target_date=2026-09-24` through the MCP handler
     carries loads on squat / row with `fallback: nearest_band`. The heavy bench is the
     barbell bench, which carries no `hevy_template_id_hint` (ADR-069), so the load path
     reports `no_template_id` for it rather than a load — pinned in test_v03_load_ramp_4090.
"""

from __future__ import annotations

import ast
import json
import os
import pathlib
import sys
import types
from contextlib import ExitStack
from unittest.mock import patch

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "lambdas"))

os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from training import load_ramp, program_structure, routine_generator  # noqa: E402

CATALOG = json.loads((REPO / "config" / "movement_catalog.json").read_text())
MOVEMENTS = CATALOG["movements"]
LB = 0.45359237
TID = {
    k: MOVEMENTS[k]["hevy_template_id_hint"] for k in ("squat_barbell", "leg_press", "db_bench_press_flat", "machine_row", "lat_pulldown")
}
# #4080: the 09-24 heavy anchors the load path can load (both carry a template id). The third,
# `barbell_bench_press`, has no `hevy_template_id_hint` (ADR-069) — never loaded from history.
HEAVY = ("squat_barbell", "machine_row")

# The live 2026-09-23 shape (#4107's table): leg press 0 in band / 5 elsewhere, DB bench's
# nearest band one session at 300–309 with more sessions further down, machine row one
# session far below, lat pulldown in band three days before block 1.
WEIGHTS = {
    "2022-08-31": 225.0,
    "2023-05-29": 245.0,
    "2023-10-17": 255.0,
    "2025-10-01": 265.0,
    "2025-11-05": 264.0,
    "2024-11-03": 275.0,
    "2024-09-15": 305.0,
    "2025-05-18": 195.0,
    "2026-09-20": 316.0,
    "2026-09-23": 315.4,
}


def _s(day: str, lb: float, reps: int = 8) -> dict:
    return {"date": day, "top_weight_kg": lb * LB, "sets": [{"weight_kg": lb * LB, "reps": reps}]}


HISTORY = {
    # #4080: the barbell squat, 0 sessions in today's 310–319 band and 4 elsewhere — bands
    # 240–249 (05-29-23 @ 245 lb bw), 270–279 (11-03-24 @ 275), 260–269 (10-01-25 @ 265 and
    # 11-05-25 @ 264). The NEAREST to 310–319 is 270–279 (40 lb), whose best is 265 lb.
    TID["squat_barbell"]: [
        _s("2023-05-29", 185, 5),
        _s("2024-11-03", 265, 5),
        _s("2025-10-01", 245, 5),
        _s("2025-11-05", 255, 5),
    ],
    TID["leg_press"]: [
        _s("2022-08-31", 270),
        _s("2023-05-29", 180),
        _s("2023-10-17", 190),
        _s("2025-10-01", 300),
        _s("2025-11-05", 320),
    ],
    TID["db_bench_press_flat"]: [_s("2024-09-15", 40, 10)] + [_s("2024-11-03", 60, 8)] * 25,
    TID["machine_row"]: [_s("2025-05-18", 130, 10)],
    TID["lat_pulldown"]: [_s("2026-09-20", 140, 10)],
}
NEAREST = {
    "squat_barbell": ("270-279", "2024-11-03", 265),
    "leg_press": ("260-269", "2025-11-05", 320),
    "db_bench_press_flat": ("300-309", "2024-09-15", 40),
    "machine_row": ("190-199", "2025-05-18", 130),
}


def _generate(day="2026-09-24", history=HISTORY, weights=WEIGHTS):
    with patch.object(routine_generator, "_load_note_indexes", return_value=(history, weights, {}, {})):
        return routine_generator.generate_routines(routine_generator.GeneratorInputs(target_date=day))


def _block(ideal, key):
    return next(b for b in ideal.exercises if b.movement_key == key)


# ── 1. the fallback ─────────────────────────────────────────────────────────
def test_the_heavy_squat_with_no_in_band_history_gets_a_week_1_load_from_the_nearest_band():
    ideal = _generate()[0]
    assert _block(ideal, "squat_barbell").rationale_tag == "anchor:squat:heavy"
    row = ideal.inputs_snapshot["load_floors"]["movements"]["squat_barbell"]
    assert row["fallback"] == "nearest_band"
    # 270–279 is 40 lb from 310–319; 260–269 is 50 and 240–249 is 70 — nearest wins
    assert row["anchor_band"] == "270-279" and row["anchor_date"] == "2024-11-03"
    assert row["fallback_detail"]["current_band_counts"] == {"sessions_in_band": 0, "sessions_other_band": 4, "sessions_unweighed": 0}
    assert row["fallback_detail"]["band_requested"] == "310-319"
    top = _block(ideal, "squat_barbell").sets[0].weight_kg
    # 2024-11-03 is > 28 d before block 1, so the 10 % detraining discount applies; week 1 = 60 %
    discounted = 265 * LB * 0.90
    assert 0.60 <= top / discounted <= 0.65, top / discounted
    assert row["ramp"]["discount_pct"] == 10 and row["ramp"]["ramp_pct"] == 60
    assert "nearest band you have lifted in: 270-279" in _block(ideal, "squat_barbell").notes


def test_every_heavy_anchor_of_2026_09_24_is_loaded_from_its_nearest_band():
    ideal = _generate()[0]
    rows = ideal.inputs_snapshot["load_floors"]["movements"]
    for key in HEAVY:
        band, day, lb = NEAREST[key]
        assert (rows[key]["anchor_band"], rows[key]["anchor_date"], rows[key]["fallback"]) == (band, day, "nearest_band"), key
        top = _block(ideal, key).sets[0].weight_kg
        assert top and 0.60 <= top / (lb * LB * 0.90) <= 0.65, key
        assert [s.weight_kg for s in _block(ideal, key).sets[1:]] == [routine_generator._floor_half_kg(top * 0.9)] * 2


def test_mutation_control_without_the_fallback_the_heavy_anchors_come_out_unloaded():
    with patch.object(load_ramp, "nearest_band_anchor", return_value=None):
        ideal = _generate()[0]
    for key in HEAVY:
        assert all(s.weight_kg is None for s in _block(ideal, key).sets), key
        assert ideal.inputs_snapshot["load_floors"]["movements"][key]["status"] == "no_band_matched_history"


def test_an_in_band_anchor_is_not_a_fallback():
    ideal = _generate()[0]
    row = ideal.inputs_snapshot["load_floors"]["movements"]["lat_pulldown"]
    assert row["fallback"] is None and row["anchor_band"] == "310-319" and row["anchor_date"] == "2026-09-20"


def test_no_history_anywhere_is_still_an_absence_not_a_guess():
    ideal = _generate(history={})[0]
    assert all(s.weight_kg is None for b in ideal.exercises for s in b.sets)
    assert ideal.inputs_snapshot["load_floors"]["movements"]["squat_barbell"]["status"] == "no_history"


# ── 2. nearest, not most-evidenced ──────────────────────────────────────────
def test_a_nearer_band_with_one_session_beats_a_farther_band_with_25():
    near = load_ramp.nearest_band_anchor(TID["db_bench_press_flat"], HISTORY, WEIGHTS, 315.4, as_of="2026-09-24")
    assert near["fallback"]["anchor_band"] == "300-309" and near["best_kg"] == pytest.approx(40 * LB)
    assert near["fallback"]["anchor_band_distance_lb"] == 6


def test_mutation_control_counting_sessions_as_volume_days_picks_the_farther_band():
    """25 sessions clear resolve_band's 21-day walking-VOLUME floor; fed as `n_days`, that
    pass ranks the 270–279 band over the nearer 300–309 — why `_per_band_sessions` zeroes it."""
    real = load_ramp._per_band_sessions

    def as_volume(*a, **kw):
        return {k: {**v, "n_days": v["sessions"]} for k, v in real(*a, **kw).items()}

    with patch.object(load_ramp, "_per_band_sessions", side_effect=as_volume):
        near = load_ramp.nearest_band_anchor(TID["db_bench_press_flat"], HISTORY, WEIGHTS, 315.4, as_of="2026-09-24")
    assert near["fallback"]["anchor_band"] == "270-279"


def test_a_tie_goes_to_the_heavier_band():
    weights = {"2025-01-01": 305.0, "2025-02-01": 325.0, "2026-09-23": 315.0}
    history = {"X": [_s("2025-01-01", 100), _s("2025-02-01", 90)]}
    near = load_ramp.nearest_band_anchor("X", history, weights, 315.0, as_of="2026-09-24")
    assert near["fallback"]["anchor_band"] == "320-329"


def test_the_fallback_never_reaches_past_the_target_date():
    history = {"X": [_s("2026-09-24", 100)]}
    assert load_ramp.nearest_band_anchor("X", history, {"2026-09-24": 250.0, "2026-09-23": 315.0}, 315.0, as_of="2026-09-24") is None


# ── 3. the discount has an age ──────────────────────────────────────────────
@pytest.mark.parametrize(
    "anchor_date, expected",
    [("2025-11-05", 10), ("2026-08-27", 10), ("2026-08-28", 0), ("2026-09-20", 0), ("2026-10-05", 0), (None, 10)],
)
def test_the_detraining_discount_applies_only_to_anchors_28_days_older_than_block_1(anchor_date, expected):
    assert program_structure.BLOCK_CALENDAR["block_1_start"] == "2026-09-24"
    pct, ruling = load_ramp.anchor_discount(anchor_date)
    assert pct == expected, ruling
    assert ruling["threshold_days"] == load_ramp.DETRAINING_ANCHOR_AGE_DAYS == 28


def test_a_this_cycle_anchor_ramps_from_the_undiscounted_load():
    ideal = _generate()[0]
    row = ideal.inputs_snapshot["load_floors"]["movements"]["lat_pulldown"]
    assert row["ramp"]["discount_pct"] == 0 and row["ramp"]["discount"]["anchor_age_days_at_block_1"] == 4
    assert _block(ideal, "lat_pulldown").sets[0].weight_kg == load_ramp._ceil_half_kg(140 * LB * 0.60)
    assert "no detraining discount" in _block(ideal, "lat_pulldown").notes


def test_the_discount_decision_is_fixed_for_the_program_not_re_aged_each_session():
    """Week 9 reads the SAME discount ruling as week 1 — an age measured to the session date
    would discount the 09-20 anchor from late October and cut the load mid-ramp."""
    w9 = _generate("2026-11-18", weights={**WEIGHTS, "2026-11-17": 314.0})[0].inputs_snapshot["load_floors"]["movements"]["lat_pulldown"]
    assert w9["ramp"]["week"] == 9 and w9["ramp"]["discount_pct"] == 0


def test_mutation_control_an_age_of_zero_discounts_the_this_cycle_anchor_twice():
    with patch.object(load_ramp, "DETRAINING_ANCHOR_AGE_DAYS", 0):
        ideal = _generate()[0]
    assert ideal.inputs_snapshot["load_floors"]["movements"]["lat_pulldown"]["ramp"]["discount_pct"] == 10


# ── 4. one load path ────────────────────────────────────────────────────────
def _as_custom(ideal, **overrides):
    """A draft_custom routine carrying the generator's exact sets: no stored load_floors,
    so the commit gate derives its own — which is the path under test."""
    return types.SimpleNamespace(
        variant="ideal",
        target_date=ideal.target_date,
        notes="",
        inputs_snapshot={"authored": "custom"},
        exercises=ideal.exercises,
        **overrides,
    )


def test_the_chat_gate_derives_the_generator_rows_and_commits_its_loads():
    from mcp.hevy_prescription_gate import prescription_gate

    ideal = _generate()[0]
    gate = prescription_gate(_as_custom(ideal), movements=MOVEMENTS, history_index=HISTORY, weight_index=WEIGHTS)
    assert gate["verdict"] == "clean", gate["audit"]
    rows = gate["load_floors"]["movements"]
    assert gate["load_floors"]["load_rule"]["week"] == 1
    gen = ideal.inputs_snapshot["load_floors"]["movements"]
    for key in ("squat_barbell", "barbell_bench_press", "machine_row", "lat_pulldown"):
        for f in ("floor_kg", "anchor_band", "anchor_date", "fallback"):
            assert rows[key][f] == gen[key][f], (key, f)


def test_the_chat_gate_refuses_a_top_set_under_the_ramped_load():
    from mcp.hevy_prescription_gate import prescription_gate

    ideal = _generate()[0]
    _block(ideal, "squat_barbell").sets[0].weight_kg -= 5
    gate = prescription_gate(_as_custom(ideal), movements=MOVEMENTS, history_index=HISTORY, weight_index=WEIGHTS)
    assert gate["verdict"] == "refuse"
    assert {v["where"] for v in gate["audit"]["violations"]} == {"squat_barbell"}


def test_mutation_control_the_100_percent_floor_refuses_the_generator_own_loads():
    """What #4107 names: judged against the #3927 best-load floor, the ramped session the
    generator wrote would refuse at commit on the in-band anchor."""
    from mcp import hevy_prescription_gate

    ideal = _generate()[0]
    with patch.object(hevy_prescription_gate, "v03_load_rule", return_value=None):
        gate = hevy_prescription_gate.prescription_gate(_as_custom(ideal), movements=MOVEMENTS, history_index=HISTORY, weight_index=WEIGHTS)
    assert gate["verdict"] == "refuse" and "lat_pulldown" in {v["where"] for v in gate["audit"]["violations"]}


def test_before_block_1_the_chat_gate_keeps_the_3927_floor():
    from mcp.hevy_prescription_gate import v03_load_rule

    assert v03_load_rule("2026-09-19") is None
    assert v03_load_rule("2026-09-24")["week"] == 1
    with patch.object(program_structure, "ACTIVE", False):
        assert v03_load_rule("2026-09-24") is None


def _calls(tree: ast.AST, name: str) -> list[ast.Call]:
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            called = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)
            if called == name:
                out.append(node)
    return out


def _enclosing_functions(tree: ast.AST, name: str) -> set[str]:
    found = set()
    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and _calls(fn, name):
            found.add(fn.name)
    return found


def test_derivation_guard_only_v03_floor_calls_the_ramp_and_the_fallback():
    """ONE v0.3 load path, by AST over every module in lambdas/ and mcp/."""
    sites: dict[str, set[str]] = {"ramp_floor": set(), "nearest_band_anchor": set()}
    users_of_v03: set[str] = set()
    for root in ("lambdas", "mcp"):
        for path in (REPO / root).rglob("*.py"):
            src = path.read_text()
            if "ramp_floor" not in src and "nearest_band_anchor" not in src and "v03_floor" not in src:
                continue
            tree = ast.parse(src)
            rel = str(path.relative_to(REPO))
            for name in sites:
                for fn in _enclosing_functions(tree, name):
                    sites[name].add(f"{rel}::{fn}")
            if "v03_floor" in src:
                users_of_v03.add(rel)
    assert sites["ramp_floor"] == {"lambdas/training/load_ramp.py::v03_floor"}, sites
    assert sites["nearest_band_anchor"] == {"lambdas/training/load_ramp.py::v03_floor"}, sites
    # the generator, the planner and the chat commit gate all name the one path
    assert {"lambdas/training/full_body_session.py", "lambdas/training/load_ramp.py", "mcp/hevy_prescription_gate.py"} <= users_of_v03


# ── 5. the planner ──────────────────────────────────────────────────────────
def test_plan_next_session_2026_09_24_loads_squat_and_row_from_the_nearest_band():
    from mcp import handler as h
    from tests.test_fullbody_block_calendar_4064 import _stage1_patches

    with ExitStack() as st:
        for cm in _stage1_patches():
            st.enter_context(cm)
        st.enter_context(patch("mcp.tools_plan._load_anchor_indexes", return_value=(HISTORY, WEIGHTS)))
        st.enter_context(patch.object(h, "_emit_tool_metric"))
        st.enter_context(patch.object(h, "_audit_tool_call"))
        resp = h.handle_tools_call({"name": "plan_next_session", "arguments": {"target_date": "2026-09-24"}})
    session = json.loads(resp["content"][0]["text"])["constraint_block"]["session"]
    ideal = _generate()[0]
    by_key = {e["movement_key"]: e["load"] for e in session["prescription"]["exposures"]}
    assert set(HEAVY) <= set(by_key)
    for key in HEAVY:
        load = by_key[key]
        assert load["fallback"] == "nearest_band" and load["anchor_band"] == NEAREST[key][0], key
        assert load["top_kg"] == _block(ideal, key).sets[0].weight_kg, "planner and draft disagree"
