"""#5861 L3 — THE NO-LIVE-CHANGE PROOF: while the exercise library is `proposed`, every path L3 touched produces the output
it produced before L3 (base `c97168868`, the #5857 integration branch), byte for byte.

Two halves:
  1. PINNED DIGESTS — sha256 of the shadow output, per family, over a fixed synthetic world (every rotation position of
     blocks 1-3, every role, an empty and a populated ledger, a synthetic Hevy record with load trends and notes):
     `variant_rotation.for_session(select=True)` (rotation + shadow selection), `selection_engine.select_week`,
     `week_commitments.evaluate` and `selection_engine.note_fallbacks`. The pins were computed by running THIS module's
     `scenarios()` against the base tree and against L3's tree: identical. They are tied to the inputs they were computed
     on (`INPUT_SHA`): when the library, catalog or charter is regenerated (L1/L2 land), the pinned half SKIPS with that
     reason and half 2 still runs. A pinned digest that moves while the inputs did not is a shadow change: red.
  2. LIVE CODE NEVER RUNS IN SHADOW — every live-only entry point (`selection_live.*`, `fatigue_model.assess`/
     `apply_to_session`/`movement_signals`, the gate-evaluation read, the cron's live reads, the bodyweight-pull floor) is
     replaced by a function that FAILS the test, and the whole shadow world — plus the generator's draft path, the
     selection critic and the cron's input gathering — runs clean. Input-independent: this half never skips.

Must-fail controls (run on the lane, recorded on the PR): make `select_slot` take the live branch without a policy -> half 1
reds (the pinned digests move) and half 2 reds (a poisoned entry point is called); make `fatigue_model.for_live_draft`
skip its mode check -> half 2 reds.
"""

from __future__ import annotations

import copy
import dataclasses
import hashlib
import json
import os
import pathlib
import sys
from unittest.mock import patch

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "lambdas"))
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from training import (
    exercise_library as xl,  # noqa: E402
    selection_engine as se,  # noqa: E402
    training_charter as tc,  # noqa: E402
    variant_rotation as vr,  # noqa: E402
    week_commitments as wc,  # noqa: E402
)

INPUTS = ("config/exercise_library.json", "config/movement_catalog.json", "config/training_charter.json")
INPUT_SHA = "35d9aebe28d3535c"  # sha256 (first 16) of the three INPUTS, concatenated, when the pins were computed
PINNED = {
    "for_session": "d4d3f08f8f981be3",
    "select_week": "561116ff3b5f44f6",
    "commit": "e437491b8e81f8b4",
    "note_fb": "d0bba5d70f4a6792",
}
"""Per family, the digest of every scenario's shadow output — identical on the base tree and on L3's (see the module doc)."""

ROLES = ("upper_heavy", "lower_heavy", "shoulders_arms", "upper_volume", "lower_volume")
WEEKS = (1, 4, 7, 10, 13)


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    monkeypatch.delenv(tc.PRIVATE_ENV_VAR, raising=False)
    monkeypatch.delenv(xl.PRIVATE_ENV_VAR, raising=False)
    monkeypatch.setattr(tc, "_from_s3", lambda key: None)
    monkeypatch.setattr(xl, "_overlay_from_local", lambda: None)
    monkeypatch.setattr(xl, "_overlay_from_s3", lambda: None)
    tc.reset_cache()
    se._LIB_CACHE.clear()
    yield
    tc.reset_cache()
    se._LIB_CACHE.clear()


def _h(x) -> str:
    return hashlib.sha256(json.dumps(x, sort_keys=True, default=str).encode()).hexdigest()[:16]


def input_sha(root: pathlib.Path = REPO) -> str:
    return hashlib.sha256(b"".join((root / p).read_bytes() for p in INPUTS)).hexdigest()[:16]


def workouts() -> list[dict]:
    """A synthetic Hevy record: a progressing press, a flat squat, a hinge with a discomfort note, an unlogged-RPE raise."""
    days = ["2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06", "2026-11-09", "2026-11-10", "2026-11-11"]
    out = []
    for i, d in enumerate(days):
        out.append(
            {
                "date": d,
                "source_workout_id": f"w{i}",
                "exercises": [
                    {
                        "name": "Bench Press (Barbell)",
                        "template_id": "79D0BB3A",
                        "sets": [{"type": "normal", "weight_kg": 60 + i, "reps": 5, "rpe": 8}],
                    },
                    {
                        "name": "Squat (Barbell)",
                        "template_id": "D04AC939",
                        "sets": [{"type": "normal", "weight_kg": 80, "reps": 5, "rpe": 8}] * 3,
                    },
                    {
                        "name": "Romanian Deadlift (Barbell)",
                        "template_id": "2B4B7310",
                        "sets": [{"type": "normal", "weight_kg": 70, "reps": 8, "rpe": 8}] * 3,
                        "notes": "left elbow achy today",
                    },
                    {
                        "name": "Lateral Raise (Dumbbell)",
                        "template_id": "422B08F1",
                        "sets": [{"type": "normal", "weight_kg": 8, "reps": 12}],
                    },
                ],
            }
        )
    return out


def scenarios(lib: dict, cat: dict) -> dict[str, dict[str, object]]:
    """family -> {scenario: shadow output}. Pure over its inputs (the library and catalog are deep-copied per call)."""
    out: dict[str, dict[str, object]] = {"for_session": {}, "select_week": {}, "commit": {}, "note_fb": {}}
    w = workouts()
    for week in WEEKS:
        for role in ROLES:
            entry = {"week": week, "block": (week - 1) // 6 + 1, "session_role": role, "date": "2026-11-12"}
            base = vr.plan(entry, copy.deepcopy(cat), role="*", rows=[], ledger_state="injected")
            pos = base.get("position") or {}
            phase = max(1, int(pos.get("phase") or 1) - 1)
            ledger = [
                {
                    "sk": vr.ledger_sk(pos["block"], s["slot_id"]),
                    "block": pos["block"],
                    f"phase_{phase}": {"variant": s["variant"], "weeks": s["weeks"]},
                }
                for s in base["slots"]
            ]
            for name, rows in (("empty", []), ("ledger", ledger)):
                key = f"{week}:{role}:{name}"
                rot = vr.for_session(entry, copy.deepcopy(cat), rows=copy.deepcopy(rows), select=True, block_workouts=w)
                out["for_session"][key] = rot
                r2 = copy.deepcopy(rot)
                se.snapshot_fields(r2)
                out["commit"][key] = wc.evaluate(r2, copy.deepcopy(cat), on="2026-11-12", library=copy.deepcopy(lib))
                served = list((rot.get("variants") or {}).values())
                out["note_fb"][key] = se.note_fallbacks(rot, served, copy.deepcopy(cat), lib=copy.deepcopy(lib), overlay=None)
        out["select_week"][str(week)] = se.select_week(
            vr.position({"week": week, "block": (week - 1) // 6 + 1}), copy.deepcopy(cat), copy.deepcopy(lib), None, rows=[], missing=[]
        )
    return out


def digests(lib: dict, cat: dict) -> dict[str, str]:
    return {fam: _h(rows) for fam, rows in scenarios(lib, cat).items()}


def _inputs() -> tuple[dict, dict]:
    lib = json.loads((REPO / "config" / "exercise_library.json").read_text())
    cat = json.loads((REPO / "config" / "movement_catalog.json").read_text())["movements"]
    se._LIB_CACHE.update(lib=lib, at=float("inf"))  # the drafting paths read the library through the cache
    return lib, cat


# ── half 1: the pinned digests ───────────────────────────────────────────────
def test_shadow_output_is_byte_identical_to_the_base_tree():
    if input_sha() != INPUT_SHA:
        pytest.skip(f"the pinned inputs were regenerated ({input_sha()} != {INPUT_SHA}); half 2 still holds the boundary")
    lib, cat = _inputs()
    assert lib["status"] == "proposed"
    assert digests(lib, cat) == PINNED


# ── half 2: live code never runs in shadow ───────────────────────────────────
def _poisoned():
    from training import block_design_review, fatigue_model, selection_live

    def boom(name):
        def _f(*a, **k):
            pytest.fail(f"live-only {name} ran while the library is proposed")

        return _f

    targets = [
        (selection_live, "build_policy"),
        (selection_live, "select_slot"),
        (selection_live, "decorate"),
        (selection_live, "gate_locked"),
        (fatigue_model, "assess"),
        (fatigue_model, "apply_to_session"),
        (fatigue_model, "movement_signals"),
        (block_design_review, "load_gate_eval_failsoft"),
        (wc, "_with_bodyweight_pull"),
    ]
    return [patch.object(mod, name, boom(f"{mod.__name__}.{name}")) for mod, name in targets]


def test_no_live_only_code_runs_in_shadow():
    from contextlib import ExitStack

    from training import routine_generator, selection_critic

    lib, cat = _inputs()
    assert se.mode(lib) == se.MODE_SHADOW
    with ExitStack() as stack:
        for p in _poisoned():
            stack.enter_context(p)
        world = scenarios(lib, cat)
        for rot in world["for_session"].values():
            assert all("rotation_decision" not in s for s in rot.get("slots") or [])  # the live-hold key is live-only
            assert "live_policy" not in (rot.get("selection") or {})
        stack.enter_context(patch.object(routine_generator, "_load_note_indexes", return_value=({}, {}, {}, {})))
        stack.enter_context(patch("training.deload_word.load_records_failsoft", return_value=[]))
        stack.enter_context(patch("training.disruption.load_records_failsoft", return_value=[]))
        for day in ("2026-11-12", "2026-11-13", "2026-11-14", "2026-11-16", "2026-11-17"):
            for ir in routine_generator.generate_routines(
                routine_generator.GeneratorInputs(target_date=day, block_workouts=workouts(), rotation_rows=[])
            ):
                d = dataclasses.asdict(ir)
                assert "fatigue" not in ((d.get("inputs_snapshot") or {}).get("session_prescription") or {})
                selection_critic.evaluate(ir, lib, None, None, catalog=cat)
        sys.path.insert(0, str(REPO / "lambdas" / "operational"))
        import hevy_routine_cron_lambda as cron

        stack.enter_context(patch.object(cron, "_read_partition", side_effect=AssertionError("no live read while proposed")))
        stack.enter_context(patch.object(cron, "_z2_minutes_7d", return_value=123.0))
        got = cron._gather_inputs("2026-11-12", False)
        assert (got.recovery_tier, got.acwr_flag, got.volume_7d) == ("yellow", "safe", {})
        assert not hasattr(got, "sleep_hours")
