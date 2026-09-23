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
  6. gate:owner CANNOT BE SIMULATED. `ACTIVE` is True in the tree ONLY together with the
     owner's review date (2026-09-21, the v0.3 approval on #3753) — the same must-fail shape
     `training_context_registry` carries. Flipping ACTIVE back to False reds the pin.
  7. v0.3 IS THE GRID (#3753 approval): three full-body sessions on non-consecutive days,
     an optional fourth flagged `optional`, every anchor pattern reachable 2x/wk on the
     required days, the trap-bar gate recorded once, loads that HOLD; the accessory check
     now measures DRIFT (accessories added mid-block), because v0.3 fixes them per block.
"""

from __future__ import annotations

import ast
import json
import os
import pathlib
import sys
import unittest.mock

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
def test_active_is_true_only_with_the_owner_review_date():
    """The owner approved v0.3 on 2026-09-21 (#3753/#3755). ACTIVE without that date is the
    inherited-assumption failure this module exists to prevent — the pair is pinned.
    Mutation control (recorded in the PR): set ACTIVE = False → this reds."""
    assert program_structure.ACTIVE is True
    assert program_structure.LAST_REVIEWED_BY_OWNER == "2026-09-21"
    assert program_structure.PROGRAM_VERSION == "0.3"


def test_active_and_review_date_cannot_disagree():
    if program_structure.ACTIVE:
        assert program_structure.LAST_REVIEWED_BY_OWNER, "ACTIVE True with no review date recorded"
    else:
        assert program_structure.LAST_REVIEWED_BY_OWNER is None, "a review date exists but ACTIVE is still False"


def test_summary_reports_active_with_the_review_date():
    s = program_structure.summary()
    assert s["active"] is True
    assert s["status_note"].startswith("ACTIVE") and "2026-09-21" in s["status_note"]
    assert s["split"] == "full_body"
    assert s["program_version"] == "0.3"
    assert s["prose_home"].endswith("TRAINING_PROGRAM_v0.3.md")


def test_the_split_decision_records_both_owner_dates():
    """The 2026-09-19 PPL ruling was real and was overtaken, not ignored — both dates travel."""
    d = program_structure.SPLIT_DECISION
    assert d["chosen"] == "full_body" and d["stated"] == "2026-09-21" and d["provenance"] == "owner"
    assert d["supersedes"]["stated"] == "2026-09-19" and "PPL" in d["supersedes"]["ruling"]
    assert any("ppl" in r for r in d["rejected"])


def test_every_anchor_and_knob_carries_provenance():
    """ADR-105: no bare number. A frequency band with no provenance is the defect."""
    for name, anchor in program_structure.ANCHORS.items():
        assert anchor["provenance"], name
        assert anchor["stated"], name
        assert anchor["frequency_per_week"]["provenance"], name
        assert anchor["frequency_per_week"]["note"], name
    assert program_structure.ROTATION_RULE["provenance"] == "population-derived"
    assert program_structure.ROTATION_RULE["window_provenance"] == "platform-proposed"  # the window is still the platform's
    assert program_structure.DAY_SHAPE["provenance"]
    for k, v in program_structure.WEEK_GRID_PROVENANCE.items():
        assert v.get("provenance"), k
        if v["provenance"] != "unchanged":
            assert v.get("note"), k


def test_conflicts_with_the_owners_redlines_are_named_not_hidden():
    """v3 redlines say 3–4 lifting sessions and v0.3 schedules 3 + an optional 4th, so the frequency
    conflict is gone BY COMPUTATION — it must REAPPEAR under the v1 (2–3) and v2 (5–6) values
    (mutation control: the check is live, not deleted). The barbell-bench-vs-skill-ceiling
    conflict is RESOLVED (not deleted — still NAMED, per the #4080 audit-trail style) by the
    owner's 2026-09-23 exemption: bench is one of the four core anchor families
    ANCHOR_SKILL_CEILING_RULING carves out of skill_ceiling. Mutation control: drop bench
    from the exempt set and the conflict reports unresolved again."""
    from training import owner_redlines

    conflicts = program_structure.conflicts()
    ids = {c["id"] for c in conflicts}
    by_id = {c["id"]: c for c in conflicts}
    assert "lifting_frequency_vs_redline" not in ids
    assert "barbell_anchors_vs_skill_ceiling" in ids
    bench_conflict = by_id["barbell_anchors_vs_skill_ceiling"]
    assert bench_conflict["resolved"] is True
    assert bench_conflict["resolved_on"] == "2026-09-23"
    assert bench_conflict["resolution_source"] == "owner ruling recorded on #4080 (option B)"
    with unittest.mock.patch.dict(owner_redlines.REDLINES["lifting_sessions_per_wk"], {"low": 2, "high": 3}):
        assert "lifting_frequency_vs_redline" in {c["id"] for c in program_structure.conflicts()}
    with unittest.mock.patch.dict(owner_redlines.REDLINES["lifting_sessions_per_wk"], {"low": 5, "high": 6}):
        assert "lifting_frequency_vs_redline" in {c["id"] for c in program_structure.conflicts()}
    # mutation control: without the exemption, the bench conflict is unresolved again
    with unittest.mock.patch.dict(program_structure.ANCHOR_SKILL_CEILING_RULING, {"exempt_families": ("squat", "hinge", "row")}):
        unresolved = {c["id"]: c for c in program_structure.conflicts()}["barbell_anchors_vs_skill_ceiling"]
        assert unresolved["resolved"] is False
        assert "resolved_on" not in unresolved


# ── 2. shape parity with the JSON the engine runs on ─────────────────────────
def test_week_grid_keys_equal_the_json_keys():
    live = json.loads((CONFIG / "training_week.json").read_text())
    assert set(program_structure.week_grid()) == set(live), "week_grid() must be a drop-in for config/training_week.json"


def test_week_grid_is_a_full_body_week_the_generator_can_read():
    grid = program_structure.week_grid()
    assert grid["_version"] == 3
    archetypes = {d["archetype"] for d in grid["schedule"].values()}
    assert archetypes == {"full", "aerobic"}, "v0.3: full-body lifting days and walking days, nothing else"
    # every scheduled archetype must have a targets entry, or the generator silently
    # produces an empty session for that day
    for day in grid["schedule"].values():
        assert day["archetype"] in grid["archetype_targets"], day
    assert set(grid["archetype_targets"]["full"]) == {"chest", "back", "shoulders", "quadriceps", "hamstrings", "glutes"}
    assert grid["session_set_ceiling"] == 18, "v0.3 §3: 12–18 hard sets per session"
    assert grid["session_minutes_ceiling"] == 70, "v0.3 §3: 55–70 min"
    assert grid["weekly_volume_cap_per_muscle"] == 22, "the fail-safe cap does not move; the 6–10 target lives in owner_redlines"
    assert grid["exercise_notes_mode"] == "one_best_line" and grid["exercise_notes_lookback_days"] == 3650


def test_three_required_lifting_days_on_non_consecutive_days_plus_an_optional_fourth():
    grid = program_structure.week_grid()
    lifting = [int(k) for k, d in grid["schedule"].items() if d["archetype"] == "full"]
    required = [int(k) for k, d in grid["schedule"].items() if d["archetype"] == "full" and not d.get("optional")]
    optional = [d for d in grid["schedule"].values() if d.get("optional")]
    assert required == [0, 2, 4], "heavy / moderate / heavy-moderate on Mon / Wed / Fri"
    assert all(b - a >= 2 for a, b in zip(required, required[1:])), "the three required sessions are non-consecutive"
    assert len(optional) == 1 and optional[0]["session_role"] == "optional_fourth"
    assert "two consecutive green recovery days" in optional[0]["gate"]
    assert "OPTIONAL" in optional[0]["label"]
    assert len(lifting) == 4 and program_structure.lifting_days() == ["0", "2", "4", "5"]
    roles = [grid["schedule"][k]["session_role"] for k in ("0", "2", "4")]
    assert roles == ["heavy", "moderate", "heavy_moderate"]
    # walking is every day: the non-lifting days are aerobic, never rest
    assert all(d["archetype"] == "aerobic" for k, d in grid["schedule"].items() if int(k) not in lifting)


def test_every_anchor_pattern_is_reachable_twice_a_week_on_the_required_days():
    """Six patterns, each 2x/wk (population-derived). 'Reachable' = a required lifting day whose
    targets include one of the pattern's primary muscles; the generator selects by muscle."""
    reach = program_structure.anchor_reachability()
    assert set(reach) == {"squat", "hinge", "bench", "row", "overhead_press", "vertical_pull"}
    for name, r in reach.items():
        assert r["frequency_target"] == 2, name
        assert r["reachable_at_target"] is True, name
        assert len(r["reachable_days_excluding_optional"]) >= 2, name
        assert program_structure.ANCHORS[name]["frequency_per_week"]["provenance"] == "population-derived"
    assert set(program_structure.CORE_ANCHORS) == {"bench", "row", "squat", "hinge"}


def test_the_trap_bar_gate_and_the_load_hold_rule_have_one_home_each():
    """The hinge is the trap bar until ≤ 275 lb; loads HOLD. Both numbers live in owner_redlines
    and the program points at them rather than restating a different value."""
    from training import owner_redlines

    hinge = program_structure.ANCHORS["hinge"]
    assert hinge["conventional_pull_gate_lb"] == owner_redlines.REDLINES["load_anchoring"]["trap_bar_until_lb"] == 275
    assert "trap bar" in hinge["pattern"].lower() and "trap_bar_deadlift" in hinge["catalog_keys"]
    lifting = owner_redlines.REDLINES["lifting_sessions_per_wk"]
    assert lifting["load_rule"].startswith("hold")
    assert lifting["load_entry"]["then"] == "hold" and lifting["load_entry"]["max_pct_of_band_e1rm_until_week_8"] == 85
    assert lifting["deload"] == {"every_nth_week": 6, "sets_pct": -30, "loads": "held"}
    assert any("HOLD" in n for n in program_structure.week_grid()["_notes"])


def test_the_generator_trims_a_full_body_budget_to_the_session_ceiling():
    """Six landmark muscles at MEV//2 ask for ~23 sets; the ceiling is 18. The trim is proportional,
    deterministic, and never invents sets. Mutation control: return `budgets` unchanged from
    `_trim_budgets_to_ceiling` and the full-body generation below asserts on the BUG line."""
    from training import routine_generator as rg

    budgets = {"chest": 4, "back": 5, "shoulders": 4, "quadriceps": 4, "hamstrings": 3, "glutes": 3}
    trimmed = rg._trim_budgets_to_ceiling(budgets, 18)
    assert sum(trimmed.values()) == 18 and set(trimmed) == set(budgets)
    assert all(0 < trimmed[m] <= budgets[m] for m in budgets)
    assert rg._trim_budgets_to_ceiling(budgets, 25) == budgets, "under the ceiling nothing moves"
    assert rg._trim_budgets_to_ceiling({"chest": 0, "back": 20}, 18) == {"chest": 0, "back": 18}
    assert rg._trim_budgets_to_ceiling(budgets, 18) == trimmed, "deterministic"


def test_a_full_body_week_generates_through_the_module_grid(monkeypatch):
    """The seam serves the module; a Monday generates a valid full session under the ceiling, the
    Saturday is titled optional, and a walking day is a non-lifting placeholder."""
    from training import exercise_history, routine_generator as rg

    monkeypatch.setattr(rg, "CONFIG_DIR", str(CONFIG))
    monkeypatch.setattr(exercise_history, "load_history_indexes", lambda **kw: ({}, {}))
    monkeypatch.setattr(exercise_history, "load_bodyweight_index", lambda **kw: {})
    monkeypatch.setattr(exercise_history, "load_whoop_workout_index", lambda **kw: {})

    def _gen(day):
        return rg.generate_routines(
            rg.GeneratorInputs(
                target_date=day, volume_7d={}, recovery_tier="green", acwr_flag="safe", z2_minutes_7d=240.0, days_since_last_workout=1
            )
        )

    # #4064: from block 1 (Thu 2026-09-24) the block calendar answers, and a v0.3 role is
    # built as a §3 session (anchor patterns at heavy/moderate), not a muscle-budget one.
    # Mon 2026-09-28 is week 1's third session: heavy-moderate.
    monday = _gen("2026-09-28")[0]
    assert monday.archetype == "full" and monday.variant == "ideal"
    assert 12 <= sum(len(e.sets) for e in monday.exercises) <= 18
    assert any(r.startswith("week grid source=module") for r in monday.rationale)
    assert any("session_role=heavy_moderate" in r for r in monday.rationale)
    assert "block calendar: week 1, block 1" in monday.rationale
    patterns = {e.rationale_tag.split(":")[1] for e in monday.exercises if e.rationale_tag.startswith("anchor:")}
    assert patterns == {"hinge", "overhead_press", "bench", "row"}
    # before block 1 the weekday grid answers — a Monday is still the grid's heavy day
    pre_block = _gen("2026-09-21")[0]
    assert pre_block.archetype == "full" and any("session_role=heavy;" in r for r in pre_block.rationale)
    saturday = _gen("2026-10-03")[0]
    assert saturday.title.endswith("(optional)") and any(r.startswith("OPTIONAL session") for r in saturday.rationale)
    tuesday = _gen("2026-09-29")[0]
    assert tuesday.archetype == "aerobic" and not tuesday.exercises


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
    # v0.3 names lifts the catalog does not carry — they must be REPORTED, by anchor
    assert "trap_bar_deadlift" in gaps["anchor:hinge"]
    assert {"safety_bar_squat", "high_bar_back_squat"} <= set(gaps["anchor:squat"])


# ── 3. the seam, with its mutation control ───────────────────────────────────
def _loader_stub(calls: list[str]):
    def _load(name: str) -> dict:
        calls.append(name)
        return {"_source": "stub-json", "session_set_ceiling": 25}

    return _load


def test_seam_serves_the_json_while_the_program_is_proposed(monkeypatch):
    monkeypatch.setattr(program_structure, "ACTIVE", False)
    monkeypatch.setattr(program_structure, "LAST_REVIEWED_BY_OWNER", None)
    calls: list[str] = []
    resolved = program_seam.resolve_week_grid(_loader_stub(calls))
    assert resolved.source == "json"
    assert calls == ["training_week.json"]
    assert resolved.week["_source"] == "stub-json"
    assert "PROPOSED" in resolved.detail or "not active" in resolved.detail


def test_seam_serves_the_module_when_active__mutation_control(monkeypatch):
    """THE CONTROL. ACTIVE is True in the tree; the source must be the module and the JSON
    loader must not run. Flipping ACTIVE off (the test above) changes the source — a seam
    that returned "module" under both states would be wired to nothing.
    """
    calls: list[str] = []
    monkeypatch.setattr(program_structure, "ACTIVE", True)
    monkeypatch.setattr(program_structure, "LAST_REVIEWED_BY_OWNER", "2026-09-21")
    resolved = program_seam.resolve_week_grid(_loader_stub(calls))
    assert resolved.source == "module"
    assert calls == [], "the JSON must not be read at all once the program is active"
    assert set(resolved.week) == set(program_structure.week_grid())
    assert "v0.3" in resolved.detail and "full_body" in resolved.detail and "2026-09-21" in resolved.detail


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


# ── 5. the accessory check, computed from the Hevy wire shape ────────────────
def _shift(rows: list[dict], days: int) -> list[dict]:
    import datetime as _dt

    out = []
    for r in rows:
        d = _dt.date.fromisoformat(r["date"][:10]) + _dt.timedelta(days=days)
        out.append({**r, "date": d.isoformat()})
    return out


def test_accessory_check_on_the_live_week_is_unknown_without_a_prior_week():
    """The fixture IS the wire: DDB `USER#matthew#SOURCE#hevy` rows captured for #3930 — seven days.
    v0.3's verdict is DRIFT (accessories added mid-block), which needs a prior week to compare
    against; a window whose earlier half holds no session is `unknown`, never `ok`."""
    rows = _hevy_rows()
    out = program_structure.accessory_rotation(window_start="2026-09-06", window_end="2026-09-19", hevy_workouts=rows)
    assert out["n_sessions"] == 7 and out["n_early_session_days"] == 0
    assert out["window"] == {"start": "2026-09-06", "end": "2026-09-19", "days": 14}
    assert out["ok"] is None and out["state"] == "unknown"
    # the measurement still travels: what was performed, classified against the SIX v0.3 anchors
    assert out["distinct_accessories"] == 11
    assert set(out["anchors_trained"]) == {"bench", "hinge", "squat", "row", "overhead_press", "vertical_pull"}
    assert out["anchor_families_missing"] == []
    repeats = {r["movement"] for r in out["repeats_within_window"]}
    assert "lateral raise (dumbbell)" in repeats  # repeats are reported, not graded — v0.3 fixes accessories
    # cardio blocks logged inside the session are NOT accessory diversity
    assert {"treadmill", "cycling"} <= set(out["cardio_blocks_excluded"])
    assert all(c not in repeats for c in out["cardio_blocks_excluded"])


def test_a_fixed_accessory_set_across_two_weeks_is_ok_and_an_addition_is_drift():
    """Two passes of the live week (the second shifted back seven days) = a FIXED set; one movement
    that appears only in the trailing week = DRIFT, named. Both legs on the wire shape."""
    rows = _hevy_rows()
    two_weeks = _shift(rows, -7) + rows
    fixed = program_structure.accessory_rotation(window_start="2026-09-06", window_end="2026-09-19", hevy_workouts=two_weeks)
    assert fixed["n_sessions"] == 14 and fixed["n_early_session_days"] == 7
    assert fixed["ok"] is True and fixed["state"] == "fixed" and fixed["added_in_trailing_7d"] == []
    drift_rows = two_weeks + [{"date": "2026-09-18", "exercises": [{"name": "Preacher Curl (Machine)", "sets": [{"reps": 12}]}]}]
    drift = program_structure.accessory_rotation(window_start="2026-09-06", window_end="2026-09-19", hevy_workouts=drift_rows)
    assert drift["ok"] is False and drift["state"] == "drifting"
    assert drift["added_in_trailing_7d"] == ["preacher curl (machine)"]
    assert any("block calendar" in h for h in drift["honesty"])


def test_rotation_window_is_respected():
    """Rows OUTSIDE the window are not counted inside it."""
    rows = _hevy_rows()
    narrow = program_structure.accessory_rotation(window_start="2026-09-18", window_end="2026-09-19", hevy_workouts=rows)
    assert narrow["n_sessions"] < 7
    assert narrow["ok"] is None, "no prior session in a two-day window — unknown, not a pass"


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
    assert program_structure.classify_movement("Romanian Deadlift (Barbell)") == "anchor:hinge"
    assert program_structure.classify_movement("Trap Bar Deadlift") == "anchor:hinge"
    assert program_structure.classify_movement("Leg Press (Machine)") == "anchor:squat"
    assert program_structure.classify_movement("Seated Cable Row - V Grip (Cable)") == "anchor:row"
    assert program_structure.classify_movement("Rowing Machine") == "cardio", "the row hint must not swallow the rower"
    assert program_structure.classify_movement("Lat Pulldown (Cable)") == "anchor:vertical_pull"
    assert program_structure.classify_movement("Shoulder Press (Dumbbell)") == "anchor:overhead_press"
    assert program_structure.classify_movement("Treadmill") == "cardio"
    assert program_structure.classify_movement("Lateral Raise (Dumbbell)") == "accessory"


# ── 6. the constraint block carries the program and the computed answer ──────
def _block(**over):
    kwargs = dict(date="2026-09-19", weight_lb=319.7, walk_hr_wk_now=8.79)
    kwargs.update(over)
    return plan_engine.constraint_block(**kwargs)


def test_constraint_block_carries_the_program_summary():
    """The only named conflict today (bench vs skill_ceiling) is RESOLVED by the owner's
    2026-09-23 exemption (#4080) — it must still be NAMED in honesty (audit trail), but as
    resolved, never as UNRESOLVED."""
    block = _block()
    assert block["program"]["program_version"] == "0.3"
    assert block["program"]["split"] == "full_body"
    assert block["program"]["active"] is True
    assert not any("is PROPOSED, not approved" in line for line in block["honesty"])
    assert not any("UNRESOLVED conflicts" in line for line in block["honesty"])
    assert any("RESOLVED by owner ruling" in line and "barbell_anchors_vs_skill_ceiling" in line for line in block["honesty"])
    assert block["program"]["anchor_reachability"]["hinge"]["reachable_at_target"] is True


def test_constraint_block_rotation_is_unknown_without_the_rows():
    block = _block()
    assert block["accessory_rotation_ok"] is None
    assert block["accessory_rotation"]["state"] == "unknown"


def test_constraint_block_computes_the_accessory_check_when_the_rows_are_injected():
    rows = _hevy_rows()
    block = _block(hevy_workouts_rotation_window=rows, rotation_window_start="2026-09-06")
    assert block["accessory_rotation_ok"] is None, "seven days of rows carry no prior week — unknown, said out loud"
    assert block["accessory_rotation"]["n_sessions"] == 7
    assert block["accessory_rotation"]["window"]["start"] == "2026-09-06"
    assert any("accessory layer is unknown" in line for line in block["honesty"])
    drift_rows = (
        _shift(rows, -7) + rows + [{"date": "2026-09-18", "exercises": [{"name": "Preacher Curl (Machine)", "sets": [{"reps": 12}]}]}]
    )
    block = _block(hevy_workouts_rotation_window=drift_rows, rotation_window_start="2026-09-06")
    assert block["accessory_rotation_ok"] is False
    assert any("DRIFTING" in line and "preacher curl (machine)" in line for line in block["honesty"])


def test_constraint_block_stays_deterministic():
    rows = _hevy_rows()
    a = _block(hevy_workouts_rotation_window=rows, rotation_window_start="2026-09-06")
    b = _block(hevy_workouts_rotation_window=rows, rotation_window_start="2026-09-06")
    assert json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)
