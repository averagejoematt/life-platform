"""tests/test_program_structure_3755.py — the program is data, and one seam serves it.

WHY THIS FILE EXISTS

#3755's acceptance is not "a program document exists" — the prose half lives in the
owner-private S3 home. It is that the anchors and the accessory pool are **data the engine
reads**, so "is the accessory layer rotating" becomes a COMPUTED check rather than an
intention, and so the diversity the owner said was missing is measured with its n.

What these tests hold:

  1. ONE SEAM, WITH A MUTATION CONTROL. `program_seam.resolve_week_grid` decides
     module-vs-JSON once and names its source. The control flips `ACTIVE` and asserts the
     source CHANGES — a seam that returns "json" under both states would pass every
     other assertion here while being wired to nothing.
  2. SHAPE PARITY. `week_grid()`'s top-level keys equal `config/training_week.json`'s.
     The generator indexes that dict directly; a missing key is a KeyError in a Lambda,
     which is the worst place to find out.
  3. BOTH CONSUMERS GO THROUGH THE SEAM. Asserted structurally over the function bodies
     (docstrings stripped, so prose ABOUT the seam cannot be read as a call to it), each
     leg carrying its own must-fail control.
  4. THE ROTATION CHECK IS COMPUTED FROM THE WIRE. The fixture is a real Hevy DDB
     partition read (`tests/fixtures/walking_volume_3930/hevy_2026-09-13_19.json`,
     captured live for #3930), not a hand-built dict — and the answer it produces on that
     week is a measured `not rotating`, not a pass.
  5. UNKNOWN IS NOT OK. An unreadable window, and a window with zero sessions, both report
     `ok is None`. A rotation rule with nothing to check is not a satisfied rule (#3767).
  6. gate:owner CANNOT BE SIMULATED. `ACTIVE` is False in the tree and pairs with a null
     review date — the same must-fail shape `training_context_registry` carries.
"""

from __future__ import annotations

import ast
import json
import os
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "lambdas"))

from training import plan_engine, program_seam, program_structure  # noqa: E402

CONFIG = REPO / "config"
HEVY_FIXTURE = REPO / "tests" / "fixtures" / "walking_volume_3930" / "hevy_2026-09-13_19.json"


def _hevy_rows() -> list[dict]:
    """The live-captured Hevy partition rows: `{date, exercises: [{name, sets}]}`."""
    return json.loads(HEVY_FIXTURE.read_text())


# ── 1. gate:owner cannot be simulated ────────────────────────────────────────
def test_active_is_false_until_the_owner_approves_v0_2():
    """The must-fail test: the only thing between an unapproved program and the engine."""
    assert program_structure.ACTIVE is False
    assert program_structure.LAST_REVIEWED_BY_OWNER is None


def test_active_and_review_date_cannot_disagree():
    if program_structure.ACTIVE:
        assert program_structure.LAST_REVIEWED_BY_OWNER, "ACTIVE True with no review date recorded"
    else:
        assert program_structure.LAST_REVIEWED_BY_OWNER is None, "a review date exists but ACTIVE is still False"


def test_summary_reports_proposed_while_inactive():
    s = program_structure.summary()
    assert s["active"] is False
    assert s["status_note"].startswith("PROPOSED")
    assert s["split"] == "ppl"
    assert s["program_version"] == "0.2"


def test_every_anchor_and_knob_carries_provenance():
    """ADR-105: no bare number. A frequency band with no provenance is the defect."""
    for name, anchor in program_structure.ANCHORS.items():
        assert anchor["provenance"], name
        assert anchor["stated"], name
        assert anchor["frequency_per_week"]["provenance"], name
        assert anchor["frequency_per_week"]["note"], name
    assert program_structure.ROTATION_RULE["provenance"] == "platform-proposed"
    assert program_structure.DAY_SHAPE["provenance"]


def test_conflicts_with_the_owners_redlines_are_named_not_hidden():
    """Six lifting days contradicts lifting_sessions_per_wk 2-3. The engine must say so."""
    ids = {c["id"] for c in program_structure.conflicts()}
    assert "lifting_frequency_vs_redline" in ids
    assert all(c["resolved"] is False for c in program_structure.conflicts())


# ── 2. shape parity with the JSON the engine runs on ─────────────────────────
def test_week_grid_keys_equal_the_json_keys():
    live = json.loads((CONFIG / "training_week.json").read_text())
    assert set(program_structure.week_grid()) == set(live), "week_grid() must be a drop-in for config/training_week.json"


def test_week_grid_is_a_ppl_week_the_generator_can_read():
    grid = program_structure.week_grid()
    archetypes = {d["archetype"] for d in grid["schedule"].values()}
    assert {"push", "pull", "legs"} <= archetypes
    # every scheduled archetype must have a targets entry, or the generator silently
    # produces an empty session for that day
    for day in grid["schedule"].values():
        assert day["archetype"] in grid["archetype_targets"], day
    assert grid["session_set_ceiling"] <= 25, "six sessions/wk against an unchanged weekly cap means the per-session ceiling comes down"
    assert grid["weekly_volume_cap_per_muscle"] == 22, "the fail-safe cap does not move for a more aggressive program"


def test_catalog_gaps_names_anchor_members_the_generator_cannot_select():
    catalog = json.loads((CONFIG / "movement_catalog.json").read_text())["movements"]
    gaps = program_structure.catalog_gaps(catalog.keys())
    # No assertion that the gap set is empty — it is not, and pretending otherwise is the
    # lie. The contract is that every named key either EXISTS or is REPORTED.
    named = {k for a in program_structure.ANCHORS.values() for k in a["catalog_keys"]}
    named |= {k for pool in program_structure.ACCESSORY_POOL.values() for k in pool}
    reported = {k for keys in gaps.values() for k in keys}
    assert reported <= named
    assert all(k in catalog for k in named - reported)


# ── 3. the seam, with its mutation control ───────────────────────────────────
def _loader_stub(calls: list[str]):
    def _load(name: str) -> dict:
        calls.append(name)
        return {"_source": "stub-json", "session_set_ceiling": 25}

    return _load


def test_seam_serves_the_json_while_the_program_is_proposed():
    calls: list[str] = []
    resolved = program_seam.resolve_week_grid(_loader_stub(calls))
    assert resolved.source == "json"
    assert calls == ["training_week.json"]
    assert resolved.week["_source"] == "stub-json"
    assert "PROPOSED" in resolved.detail or "not active" in resolved.detail


def test_seam_serves_the_module_when_active__mutation_control(monkeypatch):
    """THE CONTROL. Flip ACTIVE and the source must change; the JSON loader must not run.

    Without this leg every other assertion here is satisfied by a seam hard-wired to the
    JSON — which is exactly the state this issue is trying to leave behind.
    """
    calls: list[str] = []
    monkeypatch.setattr(program_structure, "ACTIVE", True)
    monkeypatch.setattr(program_structure, "LAST_REVIEWED_BY_OWNER", "2026-09-21")
    resolved = program_seam.resolve_week_grid(_loader_stub(calls))
    assert resolved.source == "module"
    assert calls == [], "the JSON must not be read at all once the program is active"
    assert set(resolved.week) == set(program_structure.week_grid())


def test_seam_result_always_names_its_source():
    for active in (False, True):
        saved = program_structure.ACTIVE
        try:
            program_structure.ACTIVE = active
            resolved = program_seam.resolve_week_grid(_loader_stub([]))
            assert resolved.source in ("module", "json")
            assert resolved.detail
        finally:
            program_structure.ACTIVE = saved


# ── 4. both consumers reach the grid THROUGH the seam ────────────────────────
def _strip_docstrings(node: ast.AST) -> ast.AST:
    """Prose explaining the seam must not read as a call to the seam (the #3792 lesson)."""
    for sub in ast.walk(node):
        if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
            body = getattr(sub, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
                sub.body = body[1:]
    return node


def _calls_in(source: str, func_name: str) -> set[str]:
    tree = _strip_docstrings(ast.parse(source))
    fn = next((n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == func_name), None)
    assert fn is not None, f"{func_name} not found"
    names: set[str] = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            f = node.func
            names.add(f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", ""))
    return names


def _week_json_literals(source: str) -> list[str]:
    tree = _strip_docstrings(ast.parse(source))
    return [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and n.value == "training_week.json"]


@pytest.mark.parametrize(
    "relpath,func",
    [
        ("lambdas/training/routine_generator.py", "generate_routines"),
        ("mcp/tools_hevy_routine.py", "_action_draft_custom"),
    ],
)
def test_each_consumer_resolves_the_week_through_the_seam(relpath, func):
    source = (REPO / relpath).read_text()
    assert "resolve_week_grid" in _calls_in(source, func), f"{relpath}::{func} must reach the week grid through program_seam"
    assert not _week_json_literals(source), f"{relpath} still names training_week.json directly — that is a second decision point"


def test_only_the_seam_names_the_week_config_filename():
    """The literal has ONE home now. A new module that re-reads it re-opens the split."""
    offenders = []
    for root in ("lambdas", "mcp"):
        for dirpath, _dirs, files in os.walk(REPO / root):
            for fname in files:
                if not fname.endswith(".py"):
                    continue
                path = pathlib.Path(dirpath) / fname
                if path.name == "program_seam.py":
                    continue
                if _week_json_literals(path.read_text(encoding="utf-8")):
                    offenders.append(str(path.relative_to(REPO)))
    assert offenders == [], f"training_week.json is read outside the seam by: {offenders}"


def test_the_delegation_check_can_fail__must_fail_control():
    """A guard that cannot fail is not a guard. A body that loads the JSON itself is caught."""
    bad = 'def generate_routines(x):\n    """Reads the grid through resolve_week_grid."""\n    return _load_json("training_week.json")\n'
    assert "resolve_week_grid" not in _calls_in(bad, "generate_routines")
    assert _week_json_literals(bad)


# ── 5. the rotation check, computed from the Hevy wire shape ─────────────────
def test_accessory_rotation_is_computed_from_the_live_hevy_shape():
    """The fixture IS the wire: DDB `USER#matthew#SOURCE#hevy` rows captured for #3930."""
    rows = _hevy_rows()
    out = program_structure.accessory_rotation(window_start="2026-09-06", window_end="2026-09-19", hevy_workouts=rows)
    assert out["n_sessions"] == 7
    assert out["window"] == {"start": "2026-09-06", "end": "2026-09-19", "days": 14}
    assert out["distinct_accessories"] >= 10
    # the measured verdict on that real week: accessories DID repeat inside 14 days
    assert out["ok"] is False
    assert out["state"] == "repeating"
    repeats = {r["movement"] for r in out["repeats_within_window"]}
    assert "lateral raise (dumbbell)" in repeats
    # anchors are exempt and reported separately — a bench that repeats is the program
    assert set(out["anchors_trained"]) == {"bench", "deadlift", "squat"}
    assert out["anchor_families_missing"] == []
    # cardio blocks logged inside the session are NOT accessory diversity
    assert {"treadmill", "cycling"} <= set(out["cardio_blocks_excluded"])
    assert all(c not in repeats for c in out["cardio_blocks_excluded"])


def test_rotation_window_is_respected():
    """A movement repeated OUTSIDE the window is not a repeat inside it."""
    rows = _hevy_rows()
    narrow = program_structure.accessory_rotation(window_start="2026-09-18", window_end="2026-09-19", hevy_workouts=rows)
    assert narrow["n_sessions"] < 7
    assert narrow["ok"] is True, "one session in the window cannot repeat anything"


def test_unreadable_window_is_unknown_not_ok():
    out = program_structure.accessory_rotation(window_start="2026-09-06", window_end="2026-09-19", hevy_workouts=None)
    assert out["ok"] is None
    assert out["state"] == "unknown"
    assert out["honesty"]


def test_empty_window_is_unknown_not_ok():
    """A rule with nothing to check is vacuously true and that is NOT a pass (#3767)."""
    out = program_structure.accessory_rotation(window_start="2026-09-06", window_end="2026-09-19", hevy_workouts=[])
    assert out["ok"] is None
    assert out["state"] == "unknown"
    assert out["n_sessions"] == 0


def test_classify_movement_separates_anchors_cardio_and_accessories():
    assert program_structure.classify_movement("Bench Press (Barbell)") == "anchor:bench"
    assert program_structure.classify_movement("Romanian Deadlift (Barbell)") == "anchor:deadlift"
    assert program_structure.classify_movement("Leg Press (Machine)") == "anchor:squat"
    assert program_structure.classify_movement("Treadmill") == "cardio"
    assert program_structure.classify_movement("Lateral Raise (Dumbbell)") == "accessory"


# ── 6. the constraint block carries the program and the computed answer ──────
def _block(**over):
    kwargs = dict(date="2026-09-19", weight_lb=319.7, walk_hr_wk_now=8.79)
    kwargs.update(over)
    return plan_engine.constraint_block(**kwargs)


def test_constraint_block_carries_the_program_summary():
    block = _block()
    assert block["program"]["program_version"] == "0.2"
    assert block["program"]["split"] == "ppl"
    assert block["program"]["active"] is False
    assert any("PROPOSED" in line for line in block["honesty"])
    assert any("conflicts" in line for line in block["honesty"])


def test_constraint_block_rotation_is_unknown_without_the_rows():
    block = _block()
    assert block["accessory_rotation_ok"] is None
    assert block["accessory_rotation"]["state"] == "unknown"


def test_constraint_block_computes_rotation_when_the_rows_are_injected():
    block = _block(hevy_workouts_rotation_window=_hevy_rows(), rotation_window_start="2026-09-06")
    assert block["accessory_rotation_ok"] is False
    assert block["accessory_rotation"]["n_sessions"] == 7
    assert block["accessory_rotation"]["window"]["start"] == "2026-09-06"
    assert any("NOT rotating" in line for line in block["honesty"])


def test_constraint_block_stays_deterministic():
    rows = _hevy_rows()
    a = _block(hevy_workouts_rotation_window=rows, rotation_window_start="2026-09-06")
    b = _block(hevy_workouts_rotation_window=rows, rotation_window_start="2026-09-06")
    assert json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)
