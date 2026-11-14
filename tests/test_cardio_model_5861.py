"""tests/test_cardio_model_5861.py — epic #5861 lane L4: cardio on its own model (`training.cardio_model`).

What is pinned, each with the must-fail mutation that was run against it (PR body lists them):
  * cardio is never rated by the hypertrophy rubric: the conditioning rating ignores the `hypertrophy` rows and the
    module never imports `quality_rubric`;
  * no emitted prescription carries a heart-rate target, cap or zone (owner rulings: no HR intensity gating; HR is not
    effort evidence until a post-2026-10-10 baseline);
  * steps first: the walking dose is counted before any added cardio, and nothing is added without a purpose;
  * the protocols progress by their stated rule (symptoms, tolerance, recovery, adherence, then duration -> frequency
    -> intensity; intervals never step on their own);
  * joint tolerance: a high-impact modality is never chosen when tolerance is low, and the top-rated modality loses
    to a seated one on a legs-to-spare day (a stress case where the top-ranked choice is the wrong practical one);
  * missing equipment never yields an impossible session.
Fixtures are synthetic profiles, never the owner's numbers.
"""

from __future__ import annotations

import ast
import itertools
import json
import pathlib
import re

import pytest
from training import cardio_menu, cardio_model as cm, cardio_note, hevy_note_grammar, quality_rubric as qr, wrist_clock

_REPO = pathlib.Path(__file__).resolve().parent.parent
_LIB = json.loads((_REPO / "config" / "exercise_library.json").read_text(encoding="utf-8"))
_HR_TEXT = re.compile(r"\bHR\b|\bbpm\b|heart[- ]rate|\bzone\s*\d", re.IGNORECASE)

# synthetic profiles (not the owner's numbers): a high-step walker and a low-step one
HIGH_WALKER = {f"2030-01-0{i}": 20000 for i in range(1, 8)}
"""#5861 FIX3: the steps credit is conservative (a quarter of the steps over 5,000) — 10k a day no longer covers the weekly
volume by itself (tests/test_programming_fix3_5861.py holds that); a walker whose steps DO cover it now walks ~20k."""
LOW_WALKER = {f"2030-01-0{i}": 6000 for i in range(1, 8)}


def _hr_mentions(obj, path="") -> list[str]:
    """Every heart-rate field with a value, or HR wording, anywhere in an emitted structure."""
    found: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if re.search(r"(^|_)hr(_|$)|heart", str(k), re.IGNORECASE) and v not in (None, False):
                found.append(f"{path}.{k}={v!r}")
            found += _hr_mentions(v, f"{path}.{k}")
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            found += _hr_mentions(v, f"{path}[{i}]")
    elif isinstance(obj, str) and _HR_TEXT.search(obj):
        found.append(f"{path}: {obj!r}")
    return found


def _requests():
    for name, tol, legs, after, steady, equip in itertools.product(
        cm.PROTOCOLS,
        ("normal", "low"),
        (True, False),
        (False, True),
        (None, 11),
        (None, ("treadmill",), ("rower", "outdoor"), ("stationary_bike", "treadmill", "stair_climber", "jump_rope", "sled")),
    ):
        yield {
            "protocol": name,
            "joint_tolerance": tol,
            "legs_available": legs,
            "after_heavy_lower": after,
            "steady_level": steady,
            "equipment": equip,
            "gates_open": ("charter_running", "charter_plyometric"),
            "history": {"treadmill_incline_walk": 20, "recumbent_bike": 20},
            "progression_state": {"sessions_per_wk": 1, "held_sessions": 2, "rpe": "in", "adherence": 1.0},
        }


# ── cardio is not judged by the hypertrophy rubric ─────────────────────────────────────────────────────────
def test_the_conditioning_rating_ignores_the_hypertrophy_rows():
    rated = 0
    for mid, entry in _LIB["movements"].items():
        base = cm.conditioning_rating(entry, mid)
        if base is None:
            continue
        rated += 1
        for tier in ("S", "D"):
            mutated = {
                **entry,
                "hypertrophy": [{**row, "tier": tier, "rubric_tier": tier, "rubric_score": 99} for row in entry["hypertrophy"]],
            }
            assert cm.conditioning_rating(mutated, mid) == base, mid
        assert cm.conditioning_rating({k: v for k, v in entry.items() if k != "hypertrophy"}, mid) == base, mid
    assert rated >= 6


def test_a_cardio_row_rated_d_for_hypertrophy_can_be_top_rated_for_conditioning():
    rows = {mid: e for mid, e in _LIB["movements"].items() if (e.get("target") or {}).get("primary") == "cardio"}
    tops = [mid for mid, e in rows.items() if (cm.conditioning_rating(e, mid) or {}).get("tier") in ("S", "A")]
    assert tops, "no cardio row rates A or better for conditioning"
    # #5861 L1 rubric 3.0.0: a cardio row's hypertrophy is NOT APPLICABLE (null, never forced) — still never above D,
    # and the library's own conditioning rating is this model's
    assert all(e["hypertrophy"][0]["tier"] in (None, "D") for mid, e in rows.items() if mid in tops)
    assert all(e["ratings"]["hypertrophy"]["tier"] is None for mid, e in rows.items() if mid in tops)
    # (a canonical family of one machine reads the family's sustainability — #5861 FIX-DATA, `qr._cardio_view`)
    assert all(
        e["ratings"]["conditioning"]["tier"] == cm.conditioning_rating(qr._cardio_view(e), mid)["tier"]
        for mid, e in rows.items()
        if mid in tops
    )


def test_the_cardio_model_never_imports_the_hypertrophy_rubric():
    tree = ast.parse((_REPO / "lambdas" / "training" / "cardio_model.py").read_text(encoding="utf-8"))
    names = {a.name for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom)) for a in n.names}
    assert "quality_rubric" not in names


def test_a_movement_that_is_not_conditioning_is_never_forced_into_the_objective():
    lunge = _LIB["movements"].get("walking_lunge_dumbbell")
    assert lunge is not None and cm.conditioning_rating(lunge, "walking_lunge_dumbbell") is None
    assert cm.conditioning_rating({"title": "Seated Row (Machine)", "target": {"primary": "back"}}, "x") is None


def test_s_is_rare_and_needs_a_sustained_low_impact_modality():
    ratings = [cm.conditioning_rating(e, mid) for mid, e in _LIB["movements"].items()]
    s_rows = [r for r in ratings if r and r["tier"] == "S"]
    assert len(s_rows) <= 3
    for r in s_rows:
        m = cm.MODALITIES[r["modality"]]
        assert m["impact"] in ("none", "low") and m["aerobic_stimulus"] == "high" and m["intensity_control"] == "high"
    untried = {"title": "Stair Climber", "target": {"primary": "cardio"}, "history": {"exposures": 0}}
    assert cm.conditioning_rating(untried, "new_row")["tier"] == "A"


def test_a_new_library_modality_is_read_by_its_title():
    for title, modality in (
        ("Stepmill", "stair_climber"),
        ("SkiErg", "ski_erg"),
        ("Rucking", "rucking"),
        ("Arm Ergometer", "arm_ergometer"),
    ):
        r = cm.conditioning_rating({"title": title, "target": {"primary": "cardio"}}, title.lower())
        assert r and r["modality"] == modality, title


def test_every_rating_states_its_basis_and_evidence_confidence():
    for key in cm.MODALITIES:
        r = cm._rate(key)
        assert r["tier"] in cm.TIERS and r["basis"] and r["evidence_confidence"] == "consensus"


# ── no heart rate in anything emitted ──────────────────────────────────────────────────────────────────────
def test_the_hr_detector_fires_on_a_planted_cap():
    assert _hr_mentions({"clock": {"rule": "HR avg ≤ 120 bpm (target 105)"}})
    assert _hr_mentions({"hr_target": 120})
    assert not _hr_mentions({"hr_target": None, "rule": "level 11 for 30"})


def test_no_emitted_prescription_carries_a_heart_rate_target():
    for req in _requests():
        session = cm.conditioning_session(req)
        assert session["hr_target"] is None
        assert not _hr_mentions(session), _hr_mentions(session)
    for name in cm.PROTOCOLS:
        assert not _hr_mentions(cm.protocol(name)), name
        for state in _progress_states():
            assert not _hr_mentions(cm.progress(name, state)), (name, state)
    plan = cm.aerobic_plan(LOW_WALKER, purposes=cm.PURPOSES)
    assert not _hr_mentions(plan)
    load = cm.cardio_load([{"modality": "rower", "minutes": 20, "rpe": 6}], steps_by_day=HIGH_WALKER)
    assert load["hr_used"] is False and not _hr_mentions(load)


# ── recorded activity first; steps reported, never credited (#5861 FIX6, owner ruling 12) ──────────────────────────────────
def test_steps_alone_cover_nothing_and_nothing_is_added_without_a_purpose():
    plan = cm.aerobic_plan(HIGH_WALKER)
    assert not plan["volume_covered"] and plan["walking"]["moderate_min_per_wk"] == 0  # 14k steps: intensity unknown
    assert plan["walking"]["source"] == "intensity_unknown" and plan["walking"]["steps_per_day"] > 0  # still reported
    assert [a["what"] for a in plan["additions"]] == ["walking"]  # recorded brisk walking first, never structured cardio
    assert any("fill a slot" in d for d in plan["declined"])
    covered = cm.aerobic_plan(HIGH_WALKER, walk_minutes_by_day={d: 30 for d in HIGH_WALKER})  # recorded, with intensity
    assert covered["volume_covered"] and covered["additions"] == []


def test_a_low_step_week_adds_walking_first_never_structured_cardio_for_volume():
    plan = cm.aerobic_plan(LOW_WALKER)
    assert not plan["volume_covered"]
    assert plan["additions"] == [
        {"what": "walking", "purpose": "weekly_aerobic_volume", "why": "more recorded brisk walking before any added cardio"}
    ]


def test_recorded_walk_minutes_replace_the_step_estimate():
    plan = cm.aerobic_plan(LOW_WALKER, walk_minutes_by_day={d: 40 for d in LOW_WALKER})
    assert plan["walking"]["source"] == "recorded_minutes" and plan["walking"]["moderate_min_per_wk"] == 280 and plan["volume_covered"]


def test_structured_cardio_is_added_only_for_a_named_purpose_and_inside_the_menus_weekly_count():
    plan = cm.aerobic_plan(HIGH_WALKER, purposes=["intensity_domain"])
    assert [a["protocol"] for a in plan["additions"] if a["what"] == "structured_cardio"] == ["tempo_threshold"]
    goal = cm.aerobic_plan(HIGH_WALKER, purposes=["conditioning_goal"])
    hard = [a for a in goal["additions"] if a["what"] == "structured_cardio"]
    assert len(hard) <= cardio_menu.conditioning_per_wk()
    full = cm.aerobic_plan(HIGH_WALKER, recent_protocols=["tempo_threshold", "structured_intervals"], purposes=["conditioning_goal"])
    assert [a for a in full["additions"] if a["what"] == "structured_cardio"] == []
    with pytest.raises(ValueError):
        cm.aerobic_plan(HIGH_WALKER, purposes=["fill_the_slot"])


def test_poor_recovery_adds_no_hard_cardio():
    plan = cm.aerobic_plan(HIGH_WALKER, purposes=["conditioning_goal"], recovery="poor")
    assert [a for a in plan["additions"] if a["what"] == "structured_cardio"] == []
    assert all("recovery is poor" in d for d in plan["declined"])


# ── protocols progress by the stated rule ─────────────────────────────────────────────────────────────────
def _progress_states():
    base = {"minutes": 20, "sessions_per_wk": 1, "held_sessions": 2, "rpe": "in", "adherence": 1.0, "recovery": "ok", "tolerance": "ok"}
    return [
        base,
        {**base, "symptoms": True},
        {**base, "tolerance": "flag"},
        {**base, "recovery": "poor"},
        {**base, "adherence": 0.5},
        {**base, "rpe": None},
        {**base, "rpe": "over"},
        {**base, "held_sessions": 1},
        {**base, "minutes": cardio_menu.cardio_cap_minutes()},
        {**base, "minutes": cardio_menu.cardio_cap_minutes(), "sessions_per_wk": cardio_menu.conditioning_per_wk()},
    ]


def test_safety_signals_decide_before_any_progression():
    s = _progress_states()
    for name in cm.PROTOCOLS:
        assert cm.progress(name, s[1])["action"] == "stop_and_review"
        assert cm.progress(name, s[2])["action"] == "hold_change_modality"
        stepped = cm.progress(name, s[3])
        assert stepped["action"] == "step_back" and stepped["minutes"] < s[3]["minutes"]
        for held in s[4:8]:
            assert cm.progress(name, held)["action"] == "hold", (name, held)


def test_duration_then_frequency_then_intensity():
    s = _progress_states()
    cap, per_wk = cardio_menu.cardio_cap_minutes(), cardio_menu.conditioning_per_wk()
    assert cm.progress("tempo_threshold", s[0])["action"] == "add_duration"
    assert cm.progress("tempo_threshold", {**s[0], "minutes": cap})["action"] == "add_session"
    assert cm.progress("tempo_threshold", {**s[0], "minutes": cap, "sessions_per_wk": per_wk})["action"] == "add_intensity"
    # an easy protocol never progresses by adding sessions (walking carries frequency): duration, then intensity
    assert cm.progress("easy_recovery", {**s[0], "minutes": cap})["action"] == "add_intensity"
    # progressive endurance progresses by duration with no gym cap
    assert cm.progress("progressive_endurance", {**s[0], "minutes": 90})["action"] == "add_duration"


def test_intervals_never_step_intensity_on_their_own_and_nothing_is_all_out():
    s = _progress_states()
    for state in s:
        assert cm.progress("structured_intervals", state)["action"] != "add_intensity"
    assert cm.MAX_INTENSITY_PROTOCOLS == ()
    assert max(cm.protocol(n)["rpe"][1] for n in cm.PROTOCOLS) < 10
    assert max(cm.PROTOCOLS.values(), key=lambda p: p["priority"]) is cm.PROTOCOLS["structured_intervals"]


def test_the_interval_hard_step_is_protocol_data():
    assert hevy_note_grammar.INTERVAL_HARD_STEP == cm.PROTOCOLS["structured_intervals"]["levels"]["hard_over_steady"] == 2
    levels = cm.PROTOCOLS["structured_intervals"]["levels"]
    assert levels["easy_over_steady"] == cardio_note.INTERVAL_EASY_STEP and levels["escape"] == hevy_note_grammar.INTERVAL_ESCAPE_STEP


def test_protocols_read_the_menu_not_a_copy():
    assert cm.protocol("tempo_threshold")["rpe"] == list(cardio_menu.wire_band("tempo"))
    assert cm.protocol("structured_intervals")["interval_set"]["efforts"] == cardio_menu.interval_set()[0]
    assert cm.protocol("easy_recovery")["minutes"] == cardio_menu.block_minutes("easy")


# ── joint tolerance, legs, equipment ─────────────────────────────────────────────────────────────────────
def test_low_joint_tolerance_never_chooses_a_high_impact_modality():
    for req in _requests():
        session = cm.conditioning_session(req)
        if req["joint_tolerance"] == "low" and session["modality"]:
            assert cm.MODALITIES[session["modality"]]["impact"] != "high", req


def test_the_top_rated_modality_loses_on_a_legs_to_spare_day():
    req = {"protocol": "easy_recovery", "history": {"treadmill_incline_walk": 30}, "steady_level": 11}
    assert cm.conditioning_session(req)["modality"] == "treadmill_incline_walk"  # S on a fresh day
    spared = cm.conditioning_session({**req, "after_heavy_lower": True})
    assert spared["modality"] == "recumbent_bike", spared["modality"]


def test_only_high_impact_options_left_yields_no_session_rather_than_an_unsafe_one():
    req = {
        "protocol": "structured_intervals",
        "joint_tolerance": "low",
        "equipment": ("jump_rope",),
        "gates_open": ("charter_running", "charter_plyometric"),
    }
    session = cm.conditioning_session(req)
    assert session["modality"] is None and "high impact" in session["excluded"]["jump_rope"]


def test_a_session_never_needs_equipment_that_is_not_there():
    for req in _requests():
        session = cm.conditioning_session(req)
        if session["modality"]:
            need = set(cm.MODALITIES[session["modality"]]["equipment"])
            have = set(req["equipment"] or cm.DEFAULT_EQUIPMENT)
            assert not need or need & have, (req, session["modality"])
            assert req["legs_available"] or not cm.MODALITIES[session["modality"]]["uses_legs"]


def test_every_clock_rule_with_a_level_parses_back_and_holds_three_levels_at_most():
    for req in _requests():
        session = cm.conditioning_session(req)
        rule = (session.get("clock") or {}).get("rule")
        if not rule or not re.match(r"^(level \d|\d+(\.\d+)?% )", rule):
            continue
        parsed = wrist_clock.parse_note(rule, session["minutes"])
        assert parsed["status"] in ("steady", "shaped") and not parsed["unparsed"], rule
        assert len(set(re.findall(r"(?:level |^|then )(\d+)(?= for| from)", rule))) <= 3, rule


# ── the load interface ─────────────────────────────────────────────────────────────────────────────────────
def test_cardio_load_weights_leg_cost_and_never_guesses_an_unlogged_effort():
    bike = cm.cardio_load([{"modality": "recumbent_bike", "minutes": 30, "rpe": 6}])
    row = cm.cardio_load([{"modality": "rower", "minutes": 30, "rpe": 6}])
    assert bike["session_rpe_au"] == row["session_rpe_au"] == 180
    assert row["lower_body_au"] > bike["lower_body_au"]
    unknown = cm.cardio_load([{"modality": "running", "minutes": 10}])
    assert unknown["unknown_effort_minutes"] == 10 and unknown["session_rpe_au"] == 0 and unknown["impact_minutes"] == 10
    banded = cm.cardio_load([{"movement_id": "cycling", "minutes": 20, "protocol": "structured_intervals"}])
    assert banded["by_session"][0]["rpe_source"] == "protocol_band" and banded["hard_minutes"] == 20
    walked = cm.cardio_load([], steps_by_day=HIGH_WALKER)  # #5861 FIX6: steps reported apart, never an aerobic credit
    assert walked["walking"]["steps_per_day"] > 0 and walked["walking"]["moderate_min_per_wk"] == 0 and walked["minutes"] == 0
