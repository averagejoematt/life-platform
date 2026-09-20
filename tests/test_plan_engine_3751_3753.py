"""tests/test_plan_engine_3751_3753.py — the constraint block is deterministic and honest.

WHY THIS EXISTS

Asked on 2026-09-13 how the platform picks his workout, the honest answer over chat/MCP
was: nothing does. The tools return data and one chat turn decides. The structured
procedure lives in a skill file that only Claude Code runs, so the CLIENT decided the
quality of the plan.

`plan_engine.constraint_block` is that stage extracted and made pure. What these tests
hold it to:

  1. DETERMINISM — same inputs, same block. Otherwise "chat and Claude Code get the same
     answer" is a hope, not a property.
  2. ORDER — the walking gap is computed and reported FIRST, because it is the largest
     lever on the board (the walking base, measured against a proven ~8.5 hrs/wk at this
     bodyweight) and an engine that buries it helps the coach have the wrong argument.
  3. UNKNOWN IS NOT CLEAR — a tripwire whose input is missing reports `unknown`. The
     #3767 lesson applied to safety conditions: a guard that reads clear because nobody
     could look is worse than no guard, because it is trusted.
  4. PROVENANCE — every population-derived threshold says so where it fires (ADR-105).
  5. NO UNEARNED CREDIT — the block states that the critics have NOT run (#3752).
  6. STANDING CONSTRAINTS (#3715) — the calf-lesion registry is read here too, not only by
     the conversational S3 mirror, and its unconfirmed status is disclosed every time.
"""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "lambdas"))

from training import owner_redlines, plan_engine, training_context_registry  # noqa: E402

_FULL = dict(
    date="2026-09-14",
    weight_lb=319.7,
    walk_hr_wk_now=1.14,
    recovery_tier="yellow",
    acwr_flag="safe",
    muscle_volume={"quads": 8, "chest": 6},
    days_since_movement={"squat": 3, "bench": 1},
    reference={
        "proven_target": {"band": "310-319", "band_distance_lb": 1, "n_effective": 4.0, "evidence_tier": "low", "volume_citable": False}
    },
    protein_days_missed_7d=1,
    readiness_low_streak_days=0,
    anchor_lift_drop_pct=2.0,
    anchor_lift_drop_sessions=1,
    pain_flag_sites=[],
    pain_layer_status="ok",
    weight_stall_days=3,
    adherence_on_plan=True,
)


# ── 1. Determinism ────────────────────────────────────────────────────────────
def test_the_same_inputs_produce_the_same_block():
    a = plan_engine.constraint_block(**_FULL)
    b = plan_engine.constraint_block(**_FULL)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_the_block_is_json_serialisable():
    """It has to survive an MCP response and a routine note verbatim."""
    json.dumps(plan_engine.constraint_block(**_FULL))


# ── 2. The walking gap leads ──────────────────────────────────────────────────
def test_walking_is_the_first_substantive_key():
    block = plan_engine.constraint_block(**_FULL)
    keys = [k for k in block if k not in ("engine_version", "date", "deterministic")]
    assert keys[0] == "walking", f"walking is not first: {keys[:3]}"


def test_the_walking_gap_is_computed_against_the_proven_floor():
    block = plan_engine.constraint_block(**_FULL)
    w = block["walking"]
    assert w["state"] == "below_floor"
    assert w["floor_hr_wk"] == 8.5
    assert w["gap_hr_wk"] == pytest.approx(7.36, abs=0.01)
    assert w["pct_of_floor"] == pytest.approx(13.4, abs=0.1)


def test_walking_at_the_floor_reports_no_gap():
    """NEGATIVE CONTROL — the gap must be capable of closing."""
    w = plan_engine.constraint_block(**{**_FULL, "walk_hr_wk_now": 9.0})["walking"]
    assert w["state"] == "at_or_above_floor" and w["gap_hr_wk"] == 0


def test_absent_walking_volume_is_unknown_not_zero():
    w = plan_engine.constraint_block(**{**_FULL, "walk_hr_wk_now": None})["walking"]
    assert w["state"] == "unknown"
    assert "gap_hr_wk" not in w, "a gap was computed from an absent measurement"


# ── 3. Unknown is not clear ───────────────────────────────────────────────────
def test_a_tripwire_with_no_input_is_unknown():
    block = plan_engine.constraint_block(
        **{**_FULL, "protein_days_missed_7d": None, "readiness_low_streak_days": None, "anchor_lift_drop_pct": None}
    )
    states = {t["id"]: t["state"] for t in block["tripwires"]}
    assert states["protein_floor_missed"] == "unknown"
    assert states["readiness_floor"] == "unknown"
    assert states["anchor_lift_strength_drop"] == "unknown"
    assert set(block["unreadable_tripwires"]) >= {"protein_floor_missed", "readiness_floor", "anchor_lift_strength_drop"}
    assert any("could not be evaluated" in line for line in block["honesty"])


def test_tripwires_can_actually_trip():
    """NEGATIVE CONTROL — a tripwire that cannot fire is not a tripwire."""
    block = plan_engine.constraint_block(
        **{
            **_FULL,
            "protein_days_missed_7d": 4,
            "readiness_low_streak_days": 3,
            "anchor_lift_drop_pct": 12.0,
            "anchor_lift_drop_sessions": 2,
        }
    )
    assert set(block["tripped"]) >= {"protein_floor_missed", "readiness_floor", "anchor_lift_strength_drop"}


def test_tripwires_can_actually_clear():
    """The other half of the control — a guard that always fires is noise."""
    block = plan_engine.constraint_block(**_FULL)
    assert block["tripped"] == []
    assert {t["state"] for t in block["tripwires"]} <= {"clear", "unknown"}


def test_a_dark_note_layer_makes_the_pain_tripwire_unknown_not_clear():
    """#3768: that layer was dark from the day it shipped — its silence proved nothing."""
    for status in ("dark", "unknown", None):
        block = plan_engine.constraint_block(**{**_FULL, "pain_layer_status": status, "pain_flag_sites": []})
        pain = next(t for t in block["tripwires"] if t["id"] == "pain_flag_named_site")
        assert pain["state"] == "unknown", f"layer_status={status!r} read as clear"
        assert "#3768" in pain["detail"]


def test_a_healthy_note_layer_with_no_flags_is_clear():
    pain = next(t for t in plan_engine.constraint_block(**_FULL)["tripwires"] if t["id"] == "pain_flag_named_site")
    assert pain["state"] == "clear"


# ── 4. Provenance and the reference's limits ──────────────────────────────────
def test_every_population_derived_threshold_says_so_where_it_fires():
    block = plan_engine.constraint_block(**_FULL)
    for t in block["tripwires"]:
        if t["provenance"] == "population-derived":
            assert t.get("threshold_note"), f"{t['id']} is population-derived and does not say so (ADR-105 rule 4)"


def test_every_redline_carries_a_provenance():
    for name, r in owner_redlines.REDLINES.items():
        assert r.get("provenance") in ("owner", "owner-history", "population-derived"), f"{name} has no provenance"
        assert r.get("stated"), f"{name} does not say when it was stated"


def test_the_reference_limits_are_stated_not_implied():
    block = plan_engine.constraint_block(**_FULL)
    must = " ".join(block["reference"]["must_say"])
    assert "BELOW the volume evidence floor" in must
    assert "1 lb from his current weight" in must
    assert "intake is NOT comparable" in must.replace("Intake", "intake")


def test_a_missing_reference_forbids_substituting_the_current_band():
    block = plan_engine.constraint_block(**{**_FULL, "reference": None})
    assert block["reference"]["available"] is False
    assert "do not substitute the current band" in " ".join(block["reference"]["must_say"])


# ── 5. No unearned credit ─────────────────────────────────────────────────────
def test_the_block_says_the_critics_have_not_run():
    block = plan_engine.constraint_block(**_FULL)
    assert block["critics"]["ran"] is False
    assert "#3752" in block["critics"]["note"]


def test_unconfirmed_redlines_are_reported_as_proposed():
    block = plan_engine.constraint_block(**_FULL)
    assert block["redlines"]["active"] is False
    assert any("PROPOSED" in line or "not yet" in line for line in block["honesty"])


def test_the_unresolved_rate_tension_is_carried_not_hidden():
    """He stated a 0.5-1.0%/wk window on 09-07 and asked for more aggression on 09-13.
    Two owner statements in tension must not silently resolve to whichever was read first."""
    assert "rate_band_pct_bw_per_wk" in owner_redlines.summary()["unresolved"]
    rate = plan_engine.constraint_block(**_FULL)["rate_target"]
    assert rate["low_lb_wk"] == pytest.approx(1.6, abs=0.05)
    assert rate["high_lb_wk"] == pytest.approx(3.2, abs=0.05)
    assert rate["owner_to_resolve"]


# ── 6. Standing constraints (#3715) — read here, not only by the S3 mirror ────
def test_standing_constraints_is_second_right_after_walking():
    """Safety-relevant, so it sits ahead of every volume/tripwire detail — same claim
    the module docstring makes about walking being first."""
    keys = [k for k in plan_engine.constraint_block(**_FULL) if k not in ("engine_version", "date", "deterministic")]
    assert keys[:2] == ["walking", "standing_constraints"], f"unexpected lead order: {keys[:3]}"


def test_the_calf_lesion_is_on_every_block():
    block = plan_engine.constraint_block(**_FULL)
    ids = {c["id"] for c in block["standing_constraints"]["constraints"]}
    assert "calf_lesion" in ids


def test_standing_constraints_reads_the_live_registry_not_a_frozen_copy():
    """Derivation guard: the block must be the SAME object shape `training_context_registry`
    produces, not a hand-typed duplicate that can drift from it."""
    block = plan_engine.constraint_block(**_FULL)
    assert block["standing_constraints"] == training_context_registry.summary()


def test_unconfirmed_standing_constraints_are_disclosed_in_honesty_not_implied_ok():
    """Acceptance box 4, extended to the server-side surface: a plan built on this block
    must carry the same disclosure the conversational S3-read path already gives — an
    MCP caller that never reads COACH_SESSION.md must not be able to assume coverage."""
    block = plan_engine.constraint_block(**_FULL)
    assert block["standing_constraints"]["confirmed_by_owner"] is False
    assert any("NOT owner-confirmed" in line and "calf_lesion" in line for line in block["honesty"])


def test_a_confirmed_registry_would_not_repeat_the_unconfirmed_notice():
    """NEGATIVE CONTROL — the honesty line must be capable of clearing, or it is not a
    real check on `confirmed_by_owner`, just permanent noise."""
    import unittest.mock

    fake_summary = {**training_context_registry.summary(), "confirmed_by_owner": True}
    with (
        unittest.mock.patch.object(training_context_registry, "CONFIRMED_BY_OWNER", True),
        unittest.mock.patch.object(training_context_registry, "summary", return_value=fake_summary),
    ):
        block = plan_engine.constraint_block(**_FULL)
    assert not any("NOT owner-confirmed" in line for line in block["honesty"])


# ── gather(): a failing reader yields unknown, never a wrong value ────────────
def test_a_failing_reader_yields_none_not_a_default():
    def _boom():
        raise RuntimeError("DDB down")

    out = plan_engine.gather({"walk_hr_wk_now": _boom, "weight_lb": lambda: 319.7})
    assert out["walk_hr_wk_now"] is None and out["weight_lb"] == 319.7
    block = plan_engine.constraint_block(date="2026-09-14", **out)
    assert block["walking"]["state"] == "unknown"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
