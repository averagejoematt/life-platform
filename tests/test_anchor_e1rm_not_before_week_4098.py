"""tests/test_anchor_e1rm_not_before_week_4098.py — the anchor-drop tripwire waits for week 6 and compares e1RM.

THE ISSUE (#4098)
  The owner's "shoulder press 75 vs 45, a 40 % drop" was ONE template (`878CD1D0` Shoulder
  Press (Dumbbell)): 75 lb × 5 on 2026-05-30 and 45 lb × 8 on 2026-09-19. #4069 fixed the
  identity half. Three defects were left, and these tests hold each one:

  1. `not_before_week: 6` on `anchor_lift_strength_drop` was declared and read by nothing. The
     engine now enforces EVERY declared `not_before_week` from the v0.3 block calendar's week
     (#4064) — the set-level test below walks the redlines module for every declaration and
     proves each has a reader, so a new one cannot land unread.
  2. The trend compared top WEIGHT with reps thrown away. It is now v3's rolling 3-session e1RM
     median against the 6-session baseline, per template identity, over the session's own
     `best_1rm` (Epley, `mcp.strength_helpers.estimate_1rm` — no second formula).
  3. The muscle-defense critic re-derived the drop on its own. It now reads the SAME two
     functions (`plan_engine.anchor_drop_tripped`, `plan_engine.not_before_week_gate`), and an
     AST guard holds that no other module writes a `drop_pct`.
"""

from __future__ import annotations

import ast
import os
import pathlib
import sys
from typing import Any

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "lambdas"))

os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("TABLE_NAME", "test-table")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from coach import critics  # noqa: E402
from training import owner_redlines, plan_engine, program_structure  # noqa: E402

import mcp.tools_plan as tp  # noqa: E402
from mcp.strength_helpers import estimate_1rm  # noqa: E402

DB_SP = ("878CD1D0", "Shoulder Press (Dumbbell)")


def _week_start(week: int) -> str:
    return program_structure.block_calendar(weeks=week)[week - 1]["starts"]


def _sessions(sets: list[tuple[float, int]], tid_name=DB_SP) -> list[dict[str, Any]]:
    """History-tool session rows for one template: (top weight, reps) per session, oldest first."""
    return [
        {
            "date": f"2026-{5 + i // 28:02d}-{1 + i % 28:02d}",
            "template_id": tid_name[0],
            "identity": tid_name[0],
            "exercise_name": tid_name[1],
            "best_weight": float(w),
            "best_1rm": estimate_1rm(float(w), r),
        }
        for i, (w, r) in enumerate(sets)
    ]


def _anchor_state(date: str, trend: dict[str, Any]) -> dict[str, Any]:
    """The tools_plan chain: a drafted CORE-anchor row → `_worst_anchor` → the engine's tripwire row."""
    evidence = {"exercises": [{"idx": 0, "label": DB_SP[1], "anchor_family": "bench", **trend}]}
    pct, sessions = tp._worst_anchor(evidence)
    block = plan_engine.constraint_block(date=date, anchor_lift_drop_pct=pct, anchor_lift_drop_sessions=sessions)
    return next(t for t in block["tripwires"] if t["id"] == "anchor_lift_strength_drop")


# ── 1. every declared `not_before_week` has a reader ─────────────────────────
def _declarations(node: Any, path: str = "") -> list[tuple[str, Any]]:
    out: list[tuple[str, Any]] = []
    if isinstance(node, dict):
        if "not_before_week" in node:
            out.append((path, node))
        for k, v in node.items():
            out.extend(_declarations(v, f"{path}.{k}"))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            out.extend(_declarations(v, f"{path}[{i}]"))
    return out


def test_the_declaration_set_is_not_empty():
    """Mutation control for the set test below: an empty set would pass it vacuously."""
    decl = _declarations(owner_redlines.TRIPWIRES, "TRIPWIRES") + _declarations(owner_redlines.REDLINES, "REDLINES")
    assert any(d.get("id") == "anchor_lift_strength_drop" for _p, d in decl), decl


@pytest.mark.parametrize(
    "path,decl",
    _declarations(owner_redlines.TRIPWIRES, "TRIPWIRES") + _declarations(owner_redlines.REDLINES, "REDLINES"),
    ids=lambda v: v if isinstance(v, str) else "",
)
def test_every_declared_not_before_week_is_enforced_by_the_engine(path, decl):
    """Derivation guard: a `not_before_week` anywhere in the redlines module must be on an
    engine-evaluated tripwire, and the engine must hold that row `not_yet_active` below it and
    release it at it — read from the block calendar's week, never a hand-typed date."""
    assert path.startswith("TRIPWIRES["), f"{path} declares not_before_week but is not a tripwire — nothing can read it"
    engine_ids = {t["id"] for t in owner_redlines.engine_evaluated_tripwires()}
    assert decl["id"] in engine_ids, f"{decl['id']} declares not_before_week but plan_engine does not evaluate it"
    m = int(decl["not_before_week"])
    assert m >= 2, "a gate at week 1 would be vacuous — pick the week it actually arms"

    before = plan_engine.constraint_block(date=_week_start(m - 1))
    row = next(t for t in before["tripwires"] if t["id"] == decl["id"])
    assert before["program_week"] == m - 1
    assert row["state"] == "not_yet_active" and row["detail"].startswith(f"not_yet_active (week {m - 1} < {m})")
    assert decl["id"] in before["not_yet_active_tripwires"]
    assert any("not yet active" in line for line in before["honesty"])

    at = plan_engine.constraint_block(date=_week_start(m))
    row = next(t for t in at["tripwires"] if t["id"] == decl["id"])
    assert at["program_week"] == m and row["state"] != "not_yet_active"


def test_before_block_1_is_week_0_and_still_gated():
    assert plan_engine.program_week("2026-09-20") == 0
    row = next(t for t in plan_engine.constraint_block(date="2026-09-20")["tripwires"] if t["id"] == "anchor_lift_strength_drop")
    assert row["detail"].startswith("not_yet_active (week 0 < 6)")


def test_an_unknown_week_never_arms_a_gated_tripwire():
    t = next(t for t in owner_redlines.TRIPWIRES if t["id"] == "anchor_lift_strength_drop")
    assert plan_engine.not_before_week_gate(t, None) == "not_yet_active (week unknown < 6)"
    assert plan_engine.not_before_week_gate(t, 6) is None
    assert plan_engine.not_before_week_gate({"id": "x"}, 0) is None


# ── 2. the owner's fixture: 75 × 5 → 45 × 8 on one template ──────────────────
def test_75x5_to_45x8_in_week_3_does_not_trip():
    """The specimen: in the ramp weeks a detraining return is never read as a strength loss."""
    trend = tp._anchor_trend(_sessions([(75, 5)] * 6 + [(45, 8)] * 3), _week_start(3))
    assert trend["drop_pct"] > 5  # the e1RM drop is real (87.5 → 57.0) ...
    row = _anchor_state(_week_start(3), trend)
    assert row["state"] == "not_yet_active"  # ... and the gate holds it
    assert row["state_if_active"] == "tripped"
    assert row["detail"].startswith("not_yet_active (week 3 < 6)")


def test_a_same_template_e1rm_drop_in_week_7_trips():
    """MUTATION CONTROL: the same series, past the gate, trips — the gate is not a mute."""
    trend = tp._anchor_trend(_sessions([(75, 5)] * 6 + [(45, 8)] * 3), _week_start(7))
    assert trend["baseline_median_e1rm_lb"] == pytest.approx(87.5) and trend["recent_median_e1rm_lb"] == pytest.approx(57.0)
    assert trend["drop_pct"] == pytest.approx(34.9, abs=0.1) and trend["sessions_below"] == 3
    assert _anchor_state(_week_start(7), trend)["state"] == "tripped"


def test_reps_count_a_lighter_top_set_at_more_reps_is_not_a_drop():
    """Top weight fell 13 % (75 → 65) but e1RM held (87.5 → 86.7): the old top-set read would
    have tripped in week 7; the e1RM median does not."""
    trend = tp._anchor_trend(_sessions([(75, 5)] * 6 + [(65, 10)] * 3), _week_start(7))
    assert trend["drop_pct"] < 5 and trend["sessions_below"] == 0
    assert _anchor_state(_week_start(7), trend)["state"] == "clear"


def test_the_median_ignores_one_bad_session():
    """A rolling MEDIAN, not the latest session: one off day in the last three is not a drop."""
    trend = tp._anchor_trend(_sessions([(75, 5)] * 6 + [(75, 5), (45, 5), (75, 5)]), _week_start(7))
    assert trend["drop_pct"] == 0.0 and trend["sessions_below"] == 1
    assert _anchor_state(_week_start(7), trend)["state"] == "clear"


def test_too_few_sessions_is_unknown_never_a_small_drop():
    trend = tp._anchor_trend(_sessions([(75, 5), (45, 8)]), _week_start(7))
    assert "drop_pct" not in trend and "needs 9" in trend["insufficient"]
    assert _anchor_state(_week_start(7), trend)["state"] == "unknown"


# ── 3. the critic reads the same computation ─────────────────────────────────
def _draft():
    return {"exercises": [{"idx": 0, "label": DB_SP[1], "top_weight_lbs": 50.0}]}


def _muscle_packet(week: int, trend: dict[str, Any]) -> dict[str, Any]:
    """A CORE-anchor row (#4112's tier gate) — this file exercises the redline mechanics
    (ramp gate, engine/critic agreement), not the tier split; test_plan_critics_3752.py and
    test_the_critic_never_escalates_an_accessory_drop_4112 below hold the tier gate itself."""
    return critics.build_muscle_defense_packet(
        _draft(),
        anchor_trends={0: {**trend, "anchor_family": "bench"}},
        protein_days_missed_7d=0,
        protein_days_measured_7d=7,
        program_week=week,
    )


def test_the_critic_holds_the_drop_in_the_ramp_weeks_and_flags_it_after():
    trend = tp._anchor_trend(_sessions([(75, 5)] * 6 + [(45, 8)] * 3), _week_start(3))
    ramp = [f for f in _muscle_packet(3, trend)["flags"] if f["metric"] == "anchor_drop_pct[0]"]
    assert [f["severity"] for f in ramp] == ["info"] and "not_yet_active (week 3 < 6)" in ramp[0]["reason"]
    armed = [f for f in _muscle_packet(7, trend)["flags"] if f["metric"] == "anchor_drop_pct[0]"]
    assert [f["severity"] for f in armed] == ["change"] and "rolling e1RM median" in armed[0]["reason"]


def test_the_critic_and_the_engine_agree_on_every_trend():
    """Same trend in, same verdict out — the two cannot disagree because they call one function."""
    for sets in ([(75, 5)] * 6 + [(45, 8)] * 3, [(75, 5)] * 6 + [(65, 10)] * 3, [(75, 5)] * 9):
        trend = tp._anchor_trend(_sessions(sets), _week_start(7))
        engine = _anchor_state(_week_start(7), trend)["state"] == "tripped"
        critic = any(f["severity"] == "change" for f in _muscle_packet(7, trend)["flags"] if f["metric"] == "anchor_drop_pct[0]")
        assert engine == critic, sets


# ── #4112: the tier gate — only a CORE anchor can reach change/veto ──────────
def test_the_critic_never_escalates_an_accessory_drop_4112():
    """The exact numbers that trip a CORE anchor (armed week, past threshold, enough sessions
    below) produce only `info` when the row carries no `anchor_family` — the owner ruling
    ("B more ancillary tracked") applied to the per-exercise critic, not just the engine's
    `_worst_anchor` filter (#4069) which only ever fed the tripwire a core row to begin with.

    MUTATION CONTROL: dropping the `is_core` gate in `critics_muscle_defense.build_muscle_defense_packet`
    (i.e. `tripped = plan_engine.anchor_drop_tripped(...)` unconditionally) makes this red —
    the severity would read `change`.
    """
    trend = tp._anchor_trend(_sessions([(75, 5)] * 6 + [(45, 8)] * 3), _week_start(7))
    assert "anchor_family" not in trend  # `_anchor_trend` never sets it; `_gather_draft_evidence` does, only for core rows
    packet = critics.build_muscle_defense_packet(
        _draft(), anchor_trends={0: trend}, protein_days_missed_7d=0, protein_days_measured_7d=7, program_week=7
    )
    rows = [f for f in packet["flags"] if f["metric"] == "anchor_drop_pct[0]"]
    assert [f["severity"] for f in rows] == ["info"]
    assert "accessory" in rows[0]["reason"] and "never a change or veto" in rows[0]["reason"]
    assert packet["numbers"]["anchor_is_core_anchor[0]"] is False
    # the positive control: the SAME trend, marked a core anchor, DOES escalate (proves the
    # negative result above is the gate, not a broken fixture)
    core = critics.build_muscle_defense_packet(
        _draft(),
        anchor_trends={0: {**trend, "anchor_family": "hinge"}},
        protein_days_missed_7d=0,
        protein_days_measured_7d=7,
        program_week=7,
    )
    core_rows = [f for f in core["flags"] if f["metric"] == "anchor_drop_pct[0]"]
    assert [f["severity"] for f in core_rows] == ["change"]


def _drop_writers(src: str) -> list[tuple[str, int]]:
    """(function, line) of every assignment to a `drop_pct` / `sessions_below` subscript."""
    tree = ast.parse(src)
    found: list[tuple[str, int]] = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for node in ast.walk(fn):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AugAssign) else []
            for t in targets:
                if isinstance(t, ast.Subscript) and isinstance(t.slice, ast.Constant) and t.slice.value in ("drop_pct", "sessions_below"):
                    found.append((fn.name, node.lineno))
    return found


def _calls(src: str, fn_name: str) -> set[str]:
    fn = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef) and n.name == fn_name)
    calls = [n.func for n in ast.walk(fn) if isinstance(n, ast.Call)]
    return {f.attr for f in calls if isinstance(f, ast.Attribute)} | {f.id for f in calls if isinstance(f, ast.Name)}


def _compared_keys(src: str, fn_name: str) -> set[str]:
    """Every constant subscript key read inside a COMPARISON in `fn_name` — `t["threshold_pct"] <= x`
    applies a threshold; interpolating it into a sentence does not."""
    fn = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef) and n.name == fn_name)
    keys: set[str] = set()
    for cmp_ in (n for n in ast.walk(fn) if isinstance(n, ast.Compare)):
        for sub in ast.walk(cmp_):
            if isinstance(sub, ast.Subscript) and isinstance(sub.slice, ast.Constant) and isinstance(sub.slice.value, str):
                keys.add(sub.slice.value)
            if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute) and sub.func.attr == "get" and sub.args:
                if isinstance(sub.args[0], ast.Constant) and isinstance(sub.args[0].value, str):
                    keys.add(sub.args[0].value)
    return keys


def test_one_computation_ast_guard():
    """Derivation guard: the anchor drop is WRITTEN in exactly one function and its threshold is
    APPLIED in exactly one — the engine row, the tools_plan trend and the critic only read them."""
    engine_src = (REPO / "lambdas/training/plan_engine.py").read_text()
    plan_src = (REPO / "mcp/tools_plan.py").read_text()
    # #4112: build_muscle_defense_packet moved to this cohesive sibling when critics.py hit
    # its size ceiling — the re-export in critics.py carries no logic, so this guard reads it.
    critic_src = (REPO / "lambdas/coach/critics_muscle_defense.py").read_text()

    assert {f for f, _ in _drop_writers(engine_src)} == {"anchor_e1rm_trend"}
    assert _drop_writers(plan_src) == [] and _drop_writers(critic_src) == []

    assert "anchor_e1rm_trend" in _calls(plan_src, "_anchor_trend")
    assert {"anchor_drop_tripped", "not_before_week_gate"} <= _calls(critic_src, "build_muscle_defense_packet")
    assert {"anchor_drop_tripped", "not_before_week_gate"} <= _calls(engine_src, "_tripwire_states")
    for src, fn in ((critic_src, "build_muscle_defense_packet"), (engine_src, "_tripwire_states"), (plan_src, "_anchor_trend")):
        applied = {"threshold_pct", "consecutive_sessions", "not_before_week"} & _compared_keys(src, fn)
        assert not applied, f"{fn} compares against {sorted(applied)} itself — call plan_engine's one computation"


def test_the_ast_guard_can_fail():
    """Mutation control: a second writer of `drop_pct` is found."""
    assert _drop_writers("def rogue(out):\n    out['drop_pct'] = 40.0\n") == [("rogue", 2)]
    rogue = "def rogue(tr, t):\n    return tr['drop_pct'] >= t['threshold_pct']\n"
    assert "threshold_pct" in _compared_keys(rogue, "rogue")
