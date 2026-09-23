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

WEEK_7 = "2026-11-04"  # #4098: program week 7 on the v0.3 block calendar (#4064)

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
        # #4098: a program week past `not_before_week`, so the anchor tripwire reads its input rather than the gate
        **{**_FULL, "date": WEEK_7, "protein_days_missed_7d": None, "readiness_low_streak_days": None, "anchor_lift_drop_pct": None}
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
            "date": WEEK_7,  # #4098: armed — before week 6 the anchor tripwire is not_yet_active
            "protein_days_missed_7d": 4,
            "readiness_low_streak_days": 5,  # v3: 7-day mean < 50 read over 5–7 days; the engine's proxy is the streak
            "anchor_lift_drop_pct": 12.0,
            "anchor_lift_drop_sessions": 2,
        }
    )
    assert set(block["tripped"]) >= {"protein_floor_missed", "readiness_floor", "anchor_lift_strength_drop"}


def test_tripwires_can_actually_clear():
    """The other half of the control — a guard that always fires is noise."""
    block = plan_engine.constraint_block(**{**_FULL, "date": WEEK_7})
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


def test_approved_redlines_are_reported_active_not_proposed():
    """Approved 2026-09-21 (#3753, v3): the block no longer calls the redlines PROPOSED, but still names
    the tripwires the engine does not evaluate (ADR-105: silence is not clearance).
    Mutation control (recorded in the PR): set owner_redlines.ACTIVE = False → this reds."""
    block = plan_engine.constraint_block(**_FULL)
    assert block["redlines"]["active"] is True
    assert not any("redlines are PROPOSED" in line for line in block["honesty"])
    assert any("NOT evaluated by this" in line for line in block["honesty"])
    assert owner_redlines.ACTIVE is True and owner_redlines.LAST_REVIEWED_BY_OWNER == "2026-09-23"
    assert owner_redlines.REDLINES_VERSION == "3.1"


def test_the_rate_tension_is_resolved_as_a_schedule_and_approved():
    """He stated a 0.5-1.0%/wk window on 09-07, asked for 3 lb/wk on 09-20, and on 09-21 approved v0.3's
    'reproduce the 2024–25 velocity' schedule. The two owner statements are reconciled as a SCHEDULE
    in one file — the envelope kept as history, superseded above 240 lb by what he approved."""
    summ = owner_redlines.summary()
    assert "rate_band_pct_bw_per_wk" not in summ["unresolved"]
    assert owner_redlines.REDLINES["rate_band_pct_bw_per_wk"]["resolution"].startswith("RESOLVED as a schedule")
    assert "2026-09-21" in owner_redlines.REDLINES["rate_band_pct_bw_per_wk"]["resolution"]
    assert summ["active"] is True and summ["version"] == "3.1" and summ["last_reviewed_by_owner"] == "2026-09-23"
    assert summ["plan"].endswith("TRAINING_PROGRAM_v0.3.md") and summ["red_team_record"].endswith("TRAINING_PROGRAM_v0.3_redteam.md")
    rate = owner_redlines.rate_target_lb_per_wk(316.9)
    assert rate["target_lb_wk"] == 3.5 and rate["cap_lb_wk"] == 4.0 and rate["schedule_step_above_lb"] == 295
    assert owner_redlines.rate_target_lb_per_wk(250.0)["target_lb_wk"] == 2.75
    assert owner_redlines.rate_target_lb_per_wk(199.0)["target_lb_wk"] == 0.0  # the maintenance block
    # the tripwires the engine cannot compute are named in the block, never silent (ADR-105)
    block = plan_engine.constraint_block(**_FULL)
    assert set(block["unevaluated_tripwires"]) == set(owner_redlines.unevaluated_tripwires())
    assert any("NOT evaluated by this engine" in line and "walking_collapse" in line for line in block["honesty"])
    rate = plan_engine.constraint_block(**_FULL)["rate_target"]
    assert rate["low_lb_wk"] == pytest.approx(1.6, abs=0.05)
    assert rate["high_lb_wk"] == pytest.approx(3.2, abs=0.05)
    assert rate["owner_to_resolve"] is None and rate["resolution"].startswith("RESOLVED as a schedule")


# ── 5b. v3 (#3753 approved 2026-09-21): the §1 table, the landing, the new tripwires ────
_V3_TABLE = [
    # (weight_lb, target, cap, step_above_lb) — the plan's §1 rows, sampled INSIDE each band
    (317.0, 3.5, 4.0, 295),
    (296.0, 3.5, 4.0, 295),
    (290.0, 3.25, 3.75, 275),
    (276.0, 3.25, 3.75, 275),
    (270.0, 3.0, 3.5, 260),
    (250.0, 2.75, 3.25, 240),
    (230.0, 2.25, 2.75, 220),
    (215.0, 1.75, 2.25, 210),
    (207.0, 1.25, 1.75, 205),
    (203.0, 0.0, 0.0, 0),  # inside the 200–205 landing band → maintenance
    (200.0, 0.0, 0.0, 0),
]


@pytest.mark.parametrize("weight,target,cap,above", _V3_TABLE)
def test_v3_rate_schedule_matches_the_plans_section_1_table(weight, target, cap, above):
    """Mutation control (recorded in the PR): delete the `above_lb: 275` step → the 290/276 rows red."""
    r = owner_redlines.rate_target_lb_per_wk(weight)
    assert (r["target_lb_wk"], r["cap_lb_wk"], r["schedule_step_above_lb"]) == (target, cap, above), weight
    assert r["landing_phase"] is (weight <= 240)


def test_v3_schedule_boundaries_are_strict_and_the_dxa_gates_travel():
    """A weight exactly ON a boundary belongs to the band below it (`weight > above_lb`), and the
    DXA-gated steps carry their gate text so a coach cannot take 3.5 at 270 without seeing it."""
    steps = owner_redlines.REDLINES["rate_schedule_lb_wk"]["steps"]
    assert [s["above_lb"] for s in steps] == [295, 275, 260, 240, 220, 210, 205, 0]
    assert [s["target"] for s in steps] == [3.5, 3.25, 3.0, 2.75, 2.25, 1.75, 1.25, 0.0]
    assert [s["cap"] for s in steps] == [4.0, 3.75, 3.5, 3.25, 2.75, 2.25, 1.75, 0.0]
    assert owner_redlines.rate_target_lb_per_wk(295.0)["target_lb_wk"] == 3.25
    assert owner_redlines.rate_target_lb_per_wk(240.0)["target_lb_wk"] == 2.25
    assert "12 %" in owner_redlines.rate_target_lb_per_wk(270.0)["dxa_gate"]
    assert "15 %" in owner_redlines.rate_target_lb_per_wk(250.0)["dxa_gate"]
    assert owner_redlines.rate_target_lb_per_wk(317.0)["dxa_gate"] is None
    assert "ursodiol" in owner_redlines.REDLINES["rate_schedule_lb_wk"]["overshoot_rule"]


def test_v3_landing_block_is_data_the_coach_reads():
    land = owner_redlines.landing()
    assert land is owner_redlines.REDLINES["landing"]
    assert land["deceleration_begins_lb"] == 240
    assert land["rehearsal_maintenance_weeks_at_lb"] == [260, 240, 220]
    assert land["land_lb"] == [200, 205] and land["never_lb"] == 188
    assert land["maintenance_weeks"] == 26 and land["band_lb"] == [195, 205]
    assert "14 days at the last cut prescription" in land["overshoot_rules"]["plus_5_for_3_days"]
    assert "re-entered" in land["overshoot_rules"]["over_208"]
    assert land["walking_floor_hr_wk"] == 10 == owner_redlines.REDLINES["walking_floor_hr_wk"]["maintenance_floor_hr_wk"]
    assert land["provenance"] and land["stated"] and land["derived_by"]
    assert owner_redlines.summary()["landing"] == land


def test_v3_floors_and_new_redlines_carry_the_plans_numbers():
    R = owner_redlines.REDLINES
    e = R["energy_floor_kcal"]
    assert (e["floor_7d_mean"], e["floor_lifting_day"], e["floor_any_day"], e["opening_kcal"]) == (1800, 1900, 1600, 2100)
    assert e["titration"]["step_kcal"] == 150 and e["titration"]["never_on_a_week_with_fewer_complete_logs_than"] == 6
    assert R["protein_floor_g"]["value"] == 180 and R["protein_floor_g"]["target_g"] == 200 and R["protein_floor_g"]["days_of_7"] == 6
    assert R["protein_floor_g"]["g_per_kg_dxa_lean"]["floor"] == 2.3
    assert R["fat_floor_g"]["value"] == 65 and R["carb_floor_g"]["value"] == 120
    w = R["walking_floor_hr_wk"]
    assert (w["value"], w["target_hr_wk"], w["target_by_week"], w["front_load_permitted_hr_wk"], w["maintenance_floor_hr_wk"]) == (
        8.5,
        13,
        6,
        16,
        10,
    )
    assert w["front_load_weeks"] == [3, 12] and w["hr_ceiling_bpm"] == 105 and w["permanent"] is True
    lift = R["lifting_sessions_per_wk"]
    assert (lift["low"], lift["high"], lift["sets_per_muscle_wk"], lift["session_minutes"]) == (3, 4, [6, 10], [55, 70])
    assert R["run_gate_lb"]["value"] == 240 and "12 h walking" in R["run_gate_lb"]["gate"]
    m = R["medical_cover"]
    assert m["dxa_every_weeks"] == 8 and m["baseline_within_weeks"] == 2 and m["ursodiol"]["trend_threshold_lb_wk"] == 3.0
    assert (
        any("DXA (week 0" in b for b in m["baseline"])
        and any("RMR" in b for b in m["baseline"])
        and any("gallbladder" in b for b in m["baseline"])
    )
    # Owner ruling 2026-09-22: no fresh baseline — the latest on record IS week 0, and the file says so
    # with the scan, the labs date and the caveat, not by silently dropping the booking.
    w0 = m["week0_reference"]
    assert w0["dxa"]["date"] == "2026-03-30" and w0["dxa"]["lean_lb"] == 170.6 and w0["labs"]["date"] == "2026-04-03"
    assert w0["wired_to_engine"] is False and w0["next_scan"]["week"] == 8
    assert "WAIVED" in m["baseline_status"] and "2026-03-30" in " ".join(m["baseline"])
    assert R["logging_completeness"]["dark_day_kcal"] == 600


_V3_NEW_TRIPWIRES = {
    "loss_acceptable",
    "loss_excessive_clean",
    "loss_excessive_flagged",
    "rate_ceiling",
    "loss_insufficient_adherent",
    "loss_insufficient_nonadherent",
    "under_floor",
    "walking_vs_fork",
    "leverage_not_deterioration",
    "lean_mass",
    "sleep",
    "weigh_in_dark",
    "joy",
    "post_goal_walking",
}


def test_v3_new_tripwires_are_reported_as_unevaluated_by_name():
    """Report, don't compute: every §7 addition is in TRIPWIRES with `evaluated_by_engine: False`, is
    named in the block's honesty line, and never appears among the computed rows."""
    ids = {t["id"] for t in owner_redlines.TRIPWIRES}
    assert _V3_NEW_TRIPWIRES <= ids
    assert "abstinence_violation_spiral" not in ids, "folded into weigh_in_dark + logging_dark in v3"
    unevaluated = set(owner_redlines.unevaluated_tripwires())
    assert _V3_NEW_TRIPWIRES <= unevaluated
    assert {
        "intake_floor_breached",
        "rate_overshoot",
        "walking_collapse",
        "logging_dark",
        "volume_ceiling",
        "medical_stop_lines",
        "mood_declared",
    } <= unevaluated
    # #4081: self_added_volume is computed by the engine now (from adherence's set counts).
    assert "self_added_volume" not in unevaluated
    assert [t["id"] for t in owner_redlines.engine_evaluated_tripwires()] == [
        "anchor_lift_strength_drop",
        "protein_floor_missed",
        "readiness_floor",
        "pain_flag_named_site",
        "weight_stall_with_adherence",
        "self_added_volume",
    ]
    for t in owner_redlines.TRIPWIRES:
        assert t.get("provenance") in ("owner", "owner-history", "population-derived"), t["id"]
        assert t.get("action") and t.get("signal"), t["id"]
    block = plan_engine.constraint_block(**_FULL)
    computed = {t["id"] for t in block["tripwires"]}
    assert not (computed & _V3_NEW_TRIPWIRES)
    line = next(line for line in block["honesty"] if "NOT evaluated by this engine" in line)
    assert all(tid in line for tid in _V3_NEW_TRIPWIRES)
    assert f"v{owner_redlines.REDLINES_VERSION} tripwire(s)" in line


def test_v3_updated_thresholds_on_the_kept_tripwires():
    tw = {t["id"]: t for t in owner_redlines.TRIPWIRES}
    assert tw["readiness_floor"]["threshold"] == 50 and tw["readiness_floor"]["consecutive_days"] == 5
    assert tw["anchor_lift_strength_drop"]["threshold_pct"] == 5 and "e1RM median" in tw["anchor_lift_strength_drop"]["signal"]
    assert (
        "cap" in tw["rate_overshoot"]["signal"]
        and "ursodiol" in tw["rate_overshoot"]["action"]
        and tw["rate_overshoot"]["threshold_weeks"] == 2
    )
    assert (
        tw["logging_dark"]["dark_day_kcal"] == 600
        and tw["logging_dark"]["threshold_days_of_7"] == 2
        and tw["logging_dark"]["threshold_days_of_14"] == 4
    )
    assert tw["volume_ceiling"]["threshold"]["sets_per_muscle_wk"] == 10
    assert tw["walking_collapse"]["threshold_pct"] == 30 and tw["walking_collapse"]["provenance"] == "owner-history"
    assert tw["intake_floor_breached"]["threshold_days"] == 2 and tw["protein_floor_missed"]["threshold_days"] == 3
    assert "PHQ-9 ≥ 10" in tw["mood_declared"]["signal"]


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
    import unittest.mock

    # #3715 box 5 flipped on the owner's 2026-09-20 ruling: the live block carries NO
    # unconfirmed line. The disclosure path is still pinned by mutating the registry back.
    block = plan_engine.constraint_block(**_FULL)
    assert block["standing_constraints"]["confirmed_by_owner"] is True
    assert not any("NOT owner-confirmed" in line for line in block["honesty"])
    with unittest.mock.patch.object(training_context_registry, "CONFIRMED_BY_OWNER", False):
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


# ── gather(): a failing reader yields read_failed (#4072), never a wrong value ─
def test_a_failing_reader_yields_none_not_a_default():
    def _boom():
        raise RuntimeError("DDB down")

    out = plan_engine.gather({"walk_hr_wk_now": _boom, "weight_lb": lambda: 319.7})
    assert out["walk_hr_wk_now"] is None and out["weight_lb"] == 319.7
    block = plan_engine.constraint_block(date="2026-09-14", **out)
    # #4072 replaced "unknown" here: a raise is a FAILED read, and says which error.
    assert block["walking"]["state"] == "read_failed"
    assert block["inputs"]["walk_hr_wk_now"]["error"] == "RuntimeError: DDB down"
    assert block["inputs"]["weight_lb"]["state"] == "measured"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
