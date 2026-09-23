"""tests/test_nutrition_critics_3754.py — three nutrition critics, disjoint evidence, decisions never silent (#3754 boxes 3+4).

What this file holds `health.nutrition_critics` to:

  1. DISJOINT — the three packets share no metric name (the #3752 mechanism).
  2. EVERY RULE, BOTH WAYS — a positive and a negative fixture per rule, and the rule's
     threshold read from `training.owner_redlines`, never a literal repeated here.
  3. PROPOSED vs ACTIVE — the same redline breach is a `change` while `owner_redlines.ACTIVE`
     is False (reason says PROPOSED) and a `veto` when True. Both branches, monkeypatched;
     the current value is not pinned.
  4. HONEST PAUSE — every verdict says the model did not run (`model.paused`).
  5. UNKNOWN IS NAMED — each absent input lands in `unknown` by name, never skipped.
  6. NEVER WRITES — the module source carries no table reference and does not import
     `tool_log_decision`; decisions are offered with the exact payload, dedup'd on prior rows.
  7. THE SPECIMEN — the red-team record's 1,533 kcal / 146 g week yields a muscle_defense
     objection naming the intake floor, never an approval.
  8. OWNER-ONLY — no module under lambdas/ imports `nutrition_critics`; the only importers
     are the MCP layer (os.walk sweep; pre-merge via `_PREMERGE_EXTRA_FILES`).

Mutation control (watched 2026-09-21, recorded in the PR): removing the energy-floor breach
rule from `build_muscle_defense_packet` reds `test_energy_floor_two_days_below_is_a_breach`
and `test_specimen_from_the_red_team_record_names_the_intake_floor`.
"""

from __future__ import annotations

import ast
import itertools
import os
import pathlib
import re
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "lambdas"))
sys.path.insert(0, str(REPO))

from health import nutrition_critics as nc  # noqa: E402
from training import owner_redlines as rl  # noqa: E402

ENERGY = rl.REDLINES["energy_floor_kcal"]
PROTEIN = rl.REDLINES["protein_floor_g"]
LIFTS = rl.REDLINES["lifting_sessions_per_wk"]
TW = {t["id"]: t for t in rl.TRIPWIRES}
LO, HI = ENERGY["prescribed"]
TARGET_317 = rl.rate_target_lb_per_wk(317.0)["target_lb_wk"]  # the scheduled target at the fixture's weight, never a literal


def _inputs(**over):
    """A clean, adherent fortnight at 317 lb: inside the band, protein at target, lifting 5 of 7
    (above the redline's low), losing exactly on the schedule, walking flat week over week. Every
    rule's NEGATIVE fixture. The loss rate is the redlines' own scheduled target at 317 lb, so the
    fixture follows a v3 → v4 rate edit instead of silently going stale (#3753 v3: 3.0 → 3.5)."""
    base = {
        "window_end": "2026-09-20",
        "intake_kcal_by_day": [2100] * 14,
        "protein_g_by_day": [205] * 14,
        "lifting_day_flags": [True, True, False, True, True, True, False] * 2,
        "weight_lb": 317.0,
        "weight_trend_lb_wk": -TARGET_317,
        "weighin_count": 12,
        "weighin_span_days": 13,
        "rate_provisional": False,
        "weekly_loss_rates_lb_wk": [TARGET_317, TARGET_317],
        "weeks_since_genesis": 6,
        "walking_hr_this_wk": 9.0,
        "walking_hr_last_wk": 9.0,
        "deficit_severity": "SUSTAINABLE",
        "degraded_count": 0,
        "metabolic_adaptation_severity": "NONE",
        "metabolic_adaptation_flag": False,
        "training_above_prescription_weeks": 0,
    }
    base.update(over)
    return base


def _verdict(res, critic):
    return next(v for v in res["verdicts"] if v["critic"] == critic)


def _flags(packet, metric):
    return [f for f in packet["flags"] if f["metric"] == metric]


# ── 1. disjoint ───────────────────────────────────────────────────────────────
@pytest.mark.parametrize("variant", ["clean", "flagged"])
def test_the_three_packets_are_pairwise_disjoint(variant):
    inputs = (
        _inputs() if variant == "clean" else _inputs(intake_kcal_by_day=[1500] * 14, protein_g_by_day=[140] * 14, walking_hr_this_wk=4.0)
    )
    packets = nc.build_packets(inputs)
    assert set(packets) == set(nc.CRITIC_IDS)
    for a, b in itertools.combinations(nc.CRITIC_IDS, 2):
        shared = set(packets[a]["numbers"]) & set(packets[b]["numbers"])
        assert not shared, f"{a} and {b} both hold {sorted(shared)} — two critics reading one number agree by construction"


def test_every_packet_has_the_shared_shape_and_every_flag_the_shared_record():
    for packet in nc.build_packets(_inputs(intake_kcal_by_day=[1500] * 14)).values():
        assert set(packet) == {"critic", "numbers", "flags", "unknown", "violations"}
        for f in packet["flags"]:
            assert set(f) == {"metric", "severity", "reason", "provenance", "field", "to"}
            assert f["metric"] in packet["numbers"], f"{packet['critic']} flags {f['metric']} which is not in its numbers"
            assert f["provenance"], f"{packet['critic']}: a flag without provenance (ADR-105)"


# ── 2. the clean fortnight approves everywhere; the model is paused everywhere ────────
def test_clean_fortnight_is_approved_by_all_three_and_the_model_is_declared_paused():
    res = nc.run(_inputs())
    assert [v["verdict"] for v in res["verdicts"]] == ["approve", "approve", "approve"]
    for v in res["verdicts"]:
        assert v["model"] == {"paused": nc.MODEL_PAUSED_REASON}
    assert res["model_ran"] is False and res["engine"] == nc.CRITICS_VERSION
    assert res["redlines_active"] == rl.ACTIVE  # reported, not pinned


def test_run_refuses_to_run_a_model_even_when_asked():
    res = nc.run(_inputs(), model_allowed=True)
    assert all(v["model"] == {"paused": nc.MODEL_PAUSED_REASON} for v in res["verdicts"])


# ── 3. deficit advocate ───────────────────────────────────────────────────────
def test_below_target_with_intake_in_band_is_an_adherence_audit_never_eat_less():
    p = nc.build_deficit_advocate_packet(_inputs(weight_trend_lb_wk=-1.5))
    (f,) = _flags(p, "loss_rate_14d_lb_wk")
    assert f["severity"] == "change" and f["to"] == "adherence_audit"
    assert "never 'eat less'" in f["reason"]
    assert str(rl.rate_target_lb_per_wk(317.0)["target_lb_wk"]) in f["reason"]
    assert f["provenance"].startswith(rl.REDLINES["rate_schedule_lb_wk"]["provenance"])


def test_below_target_with_intake_above_the_band_top_brings_intake_to_the_top():
    p = nc.build_deficit_advocate_packet(_inputs(weight_trend_lb_wk=-1.5, intake_kcal_by_day=[HI + 300] * 14))
    (f,) = _flags(p, "loss_rate_14d_lb_wk")
    assert f["severity"] == "change" and f["field"] == "intake_kcal_per_day" and f["to"] == HI


def test_on_schedule_rate_is_info_only():
    p = nc.build_deficit_advocate_packet(_inputs())
    (f,) = _flags(p, "loss_rate_14d_lb_wk")
    assert f["severity"] == "info" and "on the schedule" in f["reason"]


def test_provisional_trend_argues_no_change_and_names_its_n():
    p = nc.build_deficit_advocate_packet(_inputs(weight_trend_lb_wk=-1.0, rate_provisional=True, weighin_count=3, weighin_span_days=4))
    (f,) = _flags(p, "loss_rate_14d_lb_wk")
    assert f["severity"] == "info" and "PROVISIONAL" in f["reason"] and "n=3" in f["reason"]


def test_overshoot_two_weeks_over_cap_after_week_4_quotes_the_schedule_rule():
    cap = rl.rate_target_lb_per_wk(317.0)["cap_lb_wk"]
    need = TW["rate_overshoot"]["threshold_weeks"]
    p = nc.build_deficit_advocate_packet(
        _inputs(weekly_loss_rates_lb_wk=[cap + 0.5] * need, weight_trend_lb_wk=-(cap + 0.5), weeks_since_genesis=5)
    )
    (f,) = _flags(p, "rate_over_cap_consecutive_weeks")
    assert f["severity"] == "change" and f["to"] == 2100 + 250
    assert rl.REDLINES["rate_schedule_lb_wk"]["overshoot_rule"] in f["reason"]
    assert f["provenance"] == TW["rate_overshoot"]["provenance"]


@pytest.mark.parametrize("over", [{"weeks_since_genesis": 3}, {"weekly_loss_rates_lb_wk": [2.0, 4.0]}])
def test_overshoot_does_not_trip_before_week_4_or_on_one_week(over):
    cap = rl.rate_target_lb_per_wk(317.0)["cap_lb_wk"]
    kw = {"weekly_loss_rates_lb_wk": [cap + 0.5, cap + 0.5], "weight_trend_lb_wk": -(cap + 0.5), "weeks_since_genesis": 6}
    kw.update(over)
    p = nc.build_deficit_advocate_packet(_inputs(**kw))
    assert not _flags(p, "rate_over_cap_consecutive_weeks")


def test_ic29_moderate_adaptation_is_a_diet_break_decision_with_its_provenance():
    p = nc.build_deficit_advocate_packet(_inputs(metabolic_adaptation_severity="MODERATE"))
    (f,) = _flags(p, "metabolic_adaptation_severity")
    assert f["severity"] == "change" and f["field"] == "diet_break" and f["provenance"] == nc.IC29_PROVENANCE
    assert "population-derived" in f["provenance"]


# ── 4. muscle defense ─────────────────────────────────────────────────────────
def test_energy_floor_two_days_below_is_a_breach(monkeypatch):
    monkeypatch.setattr(rl, "ACTIVE", False)
    days = [2100] * 12 + [ENERGY["floor_any_day"] - 100, ENERGY["floor_any_day"] - 50]
    p = nc.build_muscle_defense_packet(_inputs(intake_kcal_by_day=days, lifting_day_flags=[False] * 14))
    assert p["numbers"]["energy_floor_days_below_7d"] == TW["intake_floor_breached"]["threshold_days"]
    (f,) = _flags(p, "energy_floor_days_below_7d")
    assert f["severity"] == "change" and "PROPOSED" in f["reason"] and f["to"] == LO
    assert TW["intake_floor_breached"]["action"] in f["reason"]
    assert f["provenance"].startswith(ENERGY["provenance"])


def test_energy_floor_one_day_below_is_info_not_a_breach():
    days = [2100] * 13 + [ENERGY["floor_any_day"] - 100]
    p = nc.build_muscle_defense_packet(_inputs(intake_kcal_by_day=days, lifting_day_flags=[False] * 14))
    (f,) = _flags(p, "energy_floor_days_below_7d")
    assert f["severity"] == "info"
    assert not p["violations"]


def test_lifting_day_uses_the_higher_floor():
    """1,750 kcal clears the any-day floor and breaches the lifting-day floor — the flag
    decides which one a day is graded against."""
    kcal = ENERGY["floor_any_day"] + 50
    assert kcal < ENERGY["floor_lifting_day"]
    days = [2100] * 12 + [kcal, kcal]
    rest = nc.build_muscle_defense_packet(_inputs(intake_kcal_by_day=days, lifting_day_flags=[False] * 14))
    lift = nc.build_muscle_defense_packet(_inputs(intake_kcal_by_day=days, lifting_day_flags=[True] * 14))
    assert rest["numbers"]["energy_floor_days_below_7d"] == 0
    assert lift["numbers"]["energy_floor_days_below_7d"] == 2


def test_unlogged_days_are_unmeasured_not_breaches():
    days = [2100] * 7 + [None] * 7
    p = nc.build_muscle_defense_packet(_inputs(intake_kcal_by_day=days))
    assert p["numbers"]["energy_floor_days_below_7d"] is None
    assert "energy_floor_days_below_7d" in p["unknown"]


def test_mean_intake_below_the_prescribed_band_is_a_change_with_the_kcal_delta():
    p = nc.build_muscle_defense_packet(_inputs(intake_kcal_by_day=[LO - 150] * 14))
    (f,) = _flags(p, "mean_intake_kcal_7d")
    assert f["severity"] == "change" and f["to"] == LO and "150 kcal BELOW" in f["reason"]


def test_mean_intake_inside_the_band_is_not_flagged():
    p = nc.build_muscle_defense_packet(_inputs())
    assert not _flags(p, "mean_intake_kcal_7d")


def test_protein_floor_missed_three_of_seven_is_a_breach_with_the_kitchen_action(monkeypatch):
    monkeypatch.setattr(rl, "ACTIVE", False)
    n = TW["protein_floor_missed"]["threshold_days"]
    grams = [205] * (14 - n) + [PROTEIN["value"] - 10] * n
    p = nc.build_muscle_defense_packet(_inputs(protein_g_by_day=grams))
    (f,) = _flags(p, "protein_days_missed_7d")
    assert f["severity"] == "change" and TW["protein_floor_missed"]["action"] in f["reason"]
    assert f["provenance"] == TW["protein_floor_missed"]["provenance"]


def test_protein_floor_missed_below_threshold_is_info():
    n = TW["protein_floor_missed"]["threshold_days"] - 1
    grams = [205] * (14 - n) + [PROTEIN["value"] - 10] * n
    p = nc.build_muscle_defense_packet(_inputs(protein_g_by_day=grams))
    (f,) = _flags(p, "protein_days_missed_7d")
    assert f["severity"] == "info"


def test_protein_target_on_fewer_than_six_of_seven_is_a_change_to_the_target():
    grams = [205] * 12 + [PROTEIN["target_g"] - 5] * 2  # floor met, target missed twice -> 5 of 7
    p = nc.build_muscle_defense_packet(_inputs(protein_g_by_day=grams))
    (f,) = _flags(p, "protein_target_days_7d")
    assert f["severity"] == "change" and f["to"] == PROTEIN["target_g"] and f"{PROTEIN['days_of_7']} of 7" in f["reason"]


def test_protein_target_on_six_of_seven_is_not_flagged():
    grams = [205] * 13 + [PROTEIN["target_g"] - 5]
    p = nc.build_muscle_defense_packet(_inputs(protein_g_by_day=grams))
    assert not _flags(p, "protein_target_days_7d")


def test_deficit_tool_critical_is_a_refeed_decision_change_with_the_bands_provenance():
    p = nc.build_muscle_defense_packet(_inputs(deficit_severity="CRITICAL", degraded_count=4))
    (f,) = _flags(p, "deficit_tool_severity")
    assert f["severity"] == "change" and f["to"] == "refeed_decision" and f["provenance"] == "population-derived"


def test_deficit_tool_sustainable_is_not_flagged():
    assert not _flags(nc.build_muscle_defense_packet(_inputs()), "deficit_tool_severity")


# ── 5. adherence ──────────────────────────────────────────────────────────────
def test_logging_dark_two_trailing_days_is_a_check_in_not_a_scolding():
    n = TW["logging_dark"]["threshold_days"]
    p = nc.build_adherence_packet(_inputs(intake_kcal_by_day=[2100] * (14 - n) + [None] * n))
    (f,) = _flags(p, "logging_dark_trailing_days")
    assert f["severity"] == "change" and f["to"] == "check_in" and "a check-in, not a scolding" in f["reason"]


def test_logging_dark_one_day_is_not_flagged_and_a_past_gap_is_info():
    p = nc.build_adherence_packet(_inputs(intake_kcal_by_day=[2100] * 13 + [None]))
    assert not _flags(p, "logging_dark_trailing_days")
    p2 = nc.build_adherence_packet(_inputs(intake_kcal_by_day=[2100] * 5 + [None, None] + [2100] * 7))
    assert not _flags(p2, "logging_dark_trailing_days")
    (f,) = _flags(p2, "logging_dark_longest_run_14d")
    assert f["severity"] == "info"


def test_walking_collapse_over_thirty_percent_is_the_relapse_prodrome():
    p = nc.build_adherence_packet(_inputs(walking_hr_this_wk=6.0, walking_hr_last_wk=10.0))
    (f,) = _flags(p, "walking_wow_pct")
    assert f["severity"] == "change" and "mandatory human contact" in f["reason"]
    assert f["provenance"] == TW["walking_collapse"]["provenance"] == "owner-history"


def test_walking_down_less_than_thirty_percent_is_info():
    p = nc.build_adherence_packet(_inputs(walking_hr_this_wk=8.0, walking_hr_last_wk=10.0))
    (f,) = _flags(p, "walking_wow_pct")
    assert f["severity"] == "info" and p["numbers"]["walking_wow_pct"] == -20.0


def test_self_added_volume_two_weeks_is_info_not_a_change_and_absent_is_unknown():
    """#4111 (owner ruling 2026-09-23): `self_added_volume` is `report_only` — two weeks above
    the prescription is reported for the end-of-week report, never a `change` and never routed
    to `subtract_only`. Acceptance fixture: two weeks above -> no change flag, report present."""
    assert TW["self_added_volume"].get("tripwire_class") == "report_only"
    p = nc.build_adherence_packet(_inputs(training_above_prescription_weeks=TW["self_added_volume"]["threshold_weeks"]))
    (f,) = _flags(p, "training_above_prescription_weeks")
    assert f["severity"] == "info"
    assert f["field"] is None and f["to"] is None, "report_only must never route to subtract_only"
    assert "anxiety tell" not in f["reason"] and "mood asked" not in f["reason"]
    assert "end-of-week report" in f["reason"]
    assert not [c for c in _flags(p, "training_above_prescription_weeks") if c["severity"] == "change"]
    p2 = nc.build_adherence_packet(_inputs(training_above_prescription_weeks=None))
    assert "training_above_prescription_weeks" in p2["unknown"] and not _flags(p2, "training_above_prescription_weeks")


def test_self_added_volume_report_only_never_reaches_a_change_verdict():
    """The packet-level verdict (`coach.critics.deterministic_verdict`) filters on
    `severity == "change"` — an `info` flag must never surface as a change/veto."""
    inputs = _inputs(training_above_prescription_weeks=TW["self_added_volume"]["threshold_weeks"] + 3)
    res = nc.run(inputs)
    v = _verdict(res, "adherence")
    assert v["verdict"] != "change", "self_added_volume alone must never trip the adherence critic's verdict"


# ── 6. PROPOSED vs ACTIVE — both branches, the current value not pinned ─────────
_BREACH = dict(intake_kcal_by_day=[2100] * 12 + [1000, 1000], lifting_day_flags=[False] * 14)


def test_redline_breach_is_a_change_saying_proposed_while_active_is_false(monkeypatch):
    monkeypatch.setattr(rl, "ACTIVE", False)
    res = nc.run(_inputs(**_BREACH))
    v = _verdict(res, "muscle_defense")
    assert v["verdict"] == "change" and v["metric"] == "energy_floor_days_below_7d"
    assert "PROPOSED" in v["reason"] and "#3753" in v["reason"]
    assert res["redlines_active"] is False
    assert not res["veto"]


def test_redline_breach_is_a_veto_carrying_its_provenance_when_active_is_true(monkeypatch):
    monkeypatch.setattr(rl, "ACTIVE", True)
    res = nc.run(_inputs(**_BREACH))
    v = _verdict(res, "muscle_defense")
    assert v["verdict"] == "veto" and v["redline"] == "energy_floor_kcal"
    assert v["provenance"].startswith("population-derived"), "a population-derived redline keeps its label even as a veto (ADR-105)"
    assert res["veto"] is True


# ── 7. unknown is named, per input ───────────────────────────────────────────
@pytest.mark.parametrize(
    "missing, critic, names",
    [
        ("weight_lb", "deficit_advocate", {"weight_lb"}),
        ("weight_trend_lb_wk", "deficit_advocate", {"loss_rate_14d_lb_wk"}),
        ("weeks_since_genesis", "deficit_advocate", {"weeks_since_genesis"}),
        ("weekly_loss_rates_lb_wk", "deficit_advocate", {"weekly_loss_rates_lb_wk"}),
        ("metabolic_adaptation_severity", "deficit_advocate", {"metabolic_adaptation_severity"}),
        ("intake_kcal_by_day", "muscle_defense", {"energy_floor_days_below_7d", "mean_intake_kcal_7d"}),
        ("intake_kcal_by_day", "adherence", {"logging_dark_trailing_days", "logged_days_14d"}),
        ("protein_g_by_day", "muscle_defense", {"protein_days_missed_7d", "protein_target_days_7d"}),
        ("lifting_day_flags", "muscle_defense", {"lifting_days_7d"}),
        ("deficit_severity", "muscle_defense", {"deficit_tool_severity"}),
        ("walking_hr_last_wk", "adherence", {"walking_wow_pct"}),
        ("training_above_prescription_weeks", "adherence", {"training_above_prescription_weeks"}),
    ],
)
def test_each_absent_input_is_named_in_unknown(missing, critic, names):
    inputs = _inputs()
    inputs[missing] = None
    res = nc.run(inputs)
    v = _verdict(res, critic)
    assert names <= set(v["unknown"]), f"{critic} did not name {names - set(v['unknown'])} as unknown"
    assert v["verdict"] != "veto"


def test_a_missing_input_never_crashes_and_an_empty_dict_is_all_unknown():
    res = nc.block({}, already_logged=None)
    assert all(v["verdict"] == "approve" for v in res["verdicts"])
    assert set(res["unknown"]) == set(nc.CRITIC_IDS)
    assert all(d["state"] == "unevaluable" for d in res["decisions_offered"])


# ── 8. the specimen from the red-team record ─────────────────────────────────
SPECIMEN = dict(
    # mean 1,533 kcal; protein mean 146 g with >= 180 g on exactly 3 of 14 days
    intake_kcal_by_day=[1533] * 14,
    protein_g_by_day=[135] * 11 + [190, 186, 183],
    lifting_day_flags=[True, False, True, False, True, True, False] * 2,
    weight_lb=317.0,
)


def test_specimen_from_the_red_team_record_names_the_intake_floor():
    res = nc.run(_inputs(**SPECIMEN))
    v = _verdict(res, "muscle_defense")
    assert v["verdict"] in ("change", "veto"), "1,533 kcal / 146 g must never be approved"
    assert v["metric"] == "energy_floor_days_below_7d"
    assert str(ENERGY["floor_any_day"]) in v["reason"] and "energy floor" in v["reason"]
    assert sum(p >= PROTEIN["value"] for p in SPECIMEN["protein_g_by_day"]) == 3
    assert round(sum(SPECIMEN["protein_g_by_day"]) / 14) == 146


# ── 9. box 4 — decisions offered, never written ───────────────────────────────
STALL = dict(weight_trend_lb_wk=0.1, weekly_loss_rates_lb_wk=[0.0, -0.1])


def test_weight_stall_with_adherence_offers_a_pending_decision_with_the_exact_payload():
    inputs = _inputs(**STALL)
    res = nc.run(inputs)
    offered = nc.decisions_offered(res["verdicts"], inputs, already_logged=[])
    (d,) = [d for d in offered if d["trigger"]["id"] == "weight_stall_with_adherence"]
    assert d["state"] == "pending"
    payload = d["log_decision_payload"]
    assert set(payload) == {"decision", "source", "pillars", "note", "followed"}
    assert payload["source"] == "nutrition_critics" and payload["pillars"] == ["nutrition"] and payload["followed"] is None
    assert "trigger=weight_stall_with_adherence" in payload["note"] and "loss_rate_14d_lb_wk=-0.1" in payload["note"]
    assert any(o.startswith("diet break") for o in d["options"]) and "hold: no change this week" in d["options"]
    assert nc.STALL_FLAT_PROVENANCE in d["trigger"]["provenance"]


@pytest.mark.parametrize(
    "over",
    [
        {"intake_kcal_by_day": [LO - 300] * 14},  # intake below the band: an audit, not a break
        {"protein_g_by_day": [205] * 9 + [PROTEIN["value"] - 20] * 5},  # protein floor on 2 of 7
        {"lifting_day_flags": [False] * 14},  # no lifting
        {"weight_trend_lb_wk": -1.0},  # not flat
    ],
)
def test_weight_stall_without_adherence_offers_nothing(over):
    inputs = _inputs(**{**STALL, **over})
    offered = nc.decisions_offered(nc.run(inputs)["verdicts"], inputs, already_logged=[])
    assert not [d for d in offered if d["trigger"]["id"] == "weight_stall_with_adherence"]


def test_stall_conditions_are_read_from_the_redlines_not_literals():
    assert LIFTS["low"] == 3 and PROTEIN["days_of_7"] == 6  # the values the fixture above is built around (v3: 3–4 sessions)
    short = LIFTS["low"] - 1  # one lift under the redline's low in the trailing 7
    inputs = _inputs(**STALL, lifting_day_flags=[True] * 7 + [True] * short + [False] * (7 - short))
    offered = nc.decisions_offered(nc.run(inputs)["verdicts"], inputs, already_logged=[])
    assert not [d for d in offered if d["trigger"]["id"] == "weight_stall_with_adherence"]


def test_rate_overshoot_offers_the_plus_250_decision():
    cap = rl.rate_target_lb_per_wk(317.0)["cap_lb_wk"]
    inputs = _inputs(weekly_loss_rates_lb_wk=[cap + 0.5, cap + 0.5], weight_trend_lb_wk=-(cap + 0.5), weeks_since_genesis=5)
    offered = nc.decisions_offered(nc.run(inputs)["verdicts"], inputs, already_logged=[])
    (d,) = [d for d in offered if d["trigger"]["id"] == "rate_overshoot"]
    assert d["state"] == "pending" and any("+250 kcal/day" in o for o in d["options"])
    assert d["log_decision_payload"]["decision"].startswith("[rate_overshoot]")


def test_ic29_flag_and_deficit_critical_each_offer_a_decision():
    inputs = _inputs(metabolic_adaptation_severity="SEVERE", metabolic_adaptation_flag=True, deficit_severity="CRITICAL", degraded_count=4)
    offered = nc.decisions_offered(nc.run(inputs)["verdicts"], inputs, already_logged=[])
    ids = {d["trigger"]["id"]: d for d in offered}
    assert ids["metabolic_adaptation"]["state"] == "pending"
    assert ids["deficit_critical"]["state"] == "pending" and any("+300-400 kcal" in o for o in ids["deficit_critical"]["options"])


def test_clean_fortnight_offers_no_pending_decision():
    inputs = _inputs()
    offered = nc.decisions_offered(nc.run(inputs)["verdicts"], inputs, already_logged=[])
    assert not [d for d in offered if d["state"] == "pending"]


def test_a_decision_already_logged_for_the_trigger_is_returned_as_already_decided_not_a_fresh_payload():
    inputs = _inputs(**STALL)
    row = {
        "sk": "DECISION#2026-09-18T10:00:00.000Z",
        "date": "2026-09-18",
        "source": "nutrition_critics",
        "followed": False,
        "decision": "[weight_stall_with_adherence] ...",
        "note": "trigger=weight_stall_with_adherence; x",
    }
    offered = nc.decisions_offered(nc.run(inputs)["verdicts"], inputs, already_logged=[row])
    (d,) = [d for d in offered if d["trigger"]["id"] == "weight_stall_with_adherence"]
    assert d["state"] == "already_decided" and d["already_decided"] == row["sk"] and d["followed"] is False
    assert "log_decision_payload" not in d


def test_dedup_ignores_rows_from_other_sources_and_other_triggers():
    inputs = _inputs(**STALL)
    rows = [
        {"sk": "DECISION#1", "date": "2026-09-18", "source": "daily_brief", "note": "trigger=weight_stall_with_adherence"},
        {"sk": "DECISION#2", "date": "2026-09-18", "source": "nutrition_critics", "note": "trigger=rate_overshoot"},
    ]
    offered = nc.decisions_offered(nc.run(inputs)["verdicts"], inputs, already_logged=rows)
    (d,) = [d for d in offered if d["trigger"]["id"] == "weight_stall_with_adherence"]
    assert d["state"] == "pending"


def test_the_module_never_writes():
    src = (REPO / "lambdas" / "health" / "nutrition_critics.py").read_text(encoding="utf-8")
    for banned in ("put_item", "update_item", "table.", "boto3"):
        assert banned not in src, f"nutrition_critics.py must never write: found {banned!r}"
    assert not re.search(r"^\s*(from|import)\s+mcp", src, re.M), "the pure module must not import the MCP layer"
    assert not re.search(
        r"^\s*(from\s+\S+\s+import\s+.*tool_log_decision|import\s+.*tool_log_decision)", src, re.M
    ), "tool_log_decision must not be imported"


def test_the_log_decision_payload_matches_the_tool_signature():
    """The payload keys are exactly the args `mcp/tools_decisions.py::tool_log_decision` reads
    by name (`args.get(...)`), so the owner can pass it through untouched."""
    src = (REPO / "mcp" / "tools_decisions.py").read_text(encoding="utf-8")
    fn = src[src.index("def tool_log_decision") : src.index("def tool_get_decisions")]
    read = set(re.findall(r'args\.get\("([a-z_]+)"', fn))
    inputs = _inputs(**STALL)
    offered = nc.decisions_offered(nc.run(inputs)["verdicts"], inputs, already_logged=[])
    payload = next(d for d in offered if d["state"] == "pending")["log_decision_payload"]
    assert set(payload) <= read, f"payload carries {set(payload) - read}, which tool_log_decision never reads"
    assert "followed" in read and "override_reason" in read


# ── 10. owner-only wiring: no module under lambdas/ imports the critics ──────────
def _imports_nutrition_critics(text: str) -> bool:
    """AST, not regex: a parenthesised multi-line `from health import (..., nutrition_critics)`
    is an import too."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod == "health.nutrition_critics" or (mod in ("health",) and any(a.name == "nutrition_critics" for a in node.names)):
                return True
        elif isinstance(node, ast.Import):
            if any(a.name == "health.nutrition_critics" for a in node.names):
                return True
    return False


def _importers(root: pathlib.Path, scan_dirs=("lambdas", "mcp")) -> list[str]:
    hits = []
    for scan in scan_dirs:
        base = root / scan
        if not base.is_dir():
            continue
        for dirpath, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for fname in files:
                if not fname.endswith(".py"):
                    continue
                path = pathlib.Path(dirpath) / fname
                if path == root / "lambdas" / "health" / "nutrition_critics.py":
                    continue
                try:
                    text = path.read_text(encoding="utf-8")
                except (UnicodeDecodeError, OSError):
                    continue
                if _imports_nutrition_critics(text):
                    hits.append(str(path.relative_to(root)))
    return sorted(hits)


ALLOWED_IMPORTERS = ["mcp/nutrition_critics_inputs.py"]


def test_only_the_mcp_resolver_imports_nutrition_critics():
    """Owner-only: no lambdas/web (site-api), lambdas/emails, lambdas/content or coach
    narrative module may import the block. A new importer must be added here on purpose."""
    assert _importers(REPO) == ALLOWED_IMPORTERS


def test_the_importer_sweep_catches_a_planted_web_importer_mutation_control(tmp_path):
    (tmp_path / "lambdas" / "web").mkdir(parents=True)
    (tmp_path / "lambdas" / "web" / "site_api_nutrition.py").write_text(
        "from health import (\n    deficit_disclosures,\n    nutrition_critics,\n)\n", encoding="utf-8"
    )
    (tmp_path / "lambdas" / "web" / "clean.py").write_text("from health import deficit_disclosures\n", encoding="utf-8")
    (tmp_path / "lambdas" / "web" / "prose.py").write_text("NOTE = 'see health.nutrition_critics'\n", encoding="utf-8")
    assert _importers(tmp_path, scan_dirs=("lambdas",)) == ["lambdas/web/site_api_nutrition.py"]


def test_the_two_surfaces_reach_the_block_through_the_one_resolver():
    tn = (REPO / "mcp" / "tools_nutrition.py").read_text(encoding="utf-8")
    tp = (REPO / "mcp" / "tools_plan.py").read_text(encoding="utf-8")
    assert "nutrition_critics_inputs" in tn and '"critics"' in tn and '"decisions_offered"' in tn
    assert "nutrition_critics_inputs" in tp and 'out["nutrition_critics"]' in tp


# ── 11. the MCP resolver — pure pieces over the live row shapes, and the block never raises ──
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from mcp import nutrition_critics_inputs as nci  # noqa: E402

KEYS = nci.day_keys("2026-09-20")


def test_day_keys_are_fourteen_pacific_days_ending_on_the_window_end():
    assert len(KEYS) == 14 and KEYS[0] == "2026-09-07" and KEYS[-1] == "2026-09-20"


def test_macrofactor_series_maps_the_writer_fields_and_leaves_unlogged_days_none():
    rows = [
        {"date": "2026-09-20", "total_calories_kcal": "1533", "total_protein_g": 146},
        {"sk": "DATE#2026-09-19", "total_calories_kcal": 2100},  # sk-keyed row, no protein
    ]
    intake, protein = nci.macrofactor_series(rows, KEYS)
    assert intake[-1] == 1533.0 and intake[-2] == 2100.0 and intake[0] is None
    assert protein[-1] == 146.0 and protein[-2] is None
    assert nci.macrofactor_series(None, KEYS) == (None, None), "an unreadable partition is None, never an empty fortnight"


def test_lifting_day_flags_count_a_lift_and_not_a_treadmill_only_session():
    workouts = [
        {"date": "2026-09-20", "exercises": [{"name": "Squat (Barbell)", "sets": [{"reps": 5, "weight_kg": 80}]}]},
        {"date": "2026-09-19", "exercises": [{"name": "Treadmill", "sets": [{"duration_sec": 1800}]}]},
    ]
    flags = nci.lifting_day_flags(workouts, KEYS)
    assert flags[-1] is True and flags[-2] is False and flags[0] is False
    assert nci.lifting_day_flags(None, KEYS) is None


def test_withings_trend_reads_the_shared_loss_rate_and_splits_the_weeks():
    """#4068: the trend is THE loss rate (`mcp.shared_quantities`) — least-squares over the
    14 days, water weeks 1-2 excluded — not the TDEE check's first-vs-last endpoint. A
    pre-genesis window (no water weeks in it) exercises the estimator on its own."""
    keys = nci.day_keys("2026-08-20")
    rows = [{"date": k, "weight_lbs": 320 - 0.4 * i} for i, k in enumerate(keys)]
    t = nci.withings_trend(rows, keys)
    assert t["weight_lb"] == pytest.approx(320 - 0.4 * 13)
    assert t["weight_trend_lb_wk"] == pytest.approx(-2.8, abs=0.01)
    assert t["loss_rate"]["rate_lb_wk"] == pytest.approx(2.8, abs=0.01)
    assert t["weighin_count"] == 14 and t["weighin_span_days"] == 13 and t["rate_provisional"] is False
    assert t["weekly_loss_rates_lb_wk"] == [2.8, 2.8]
    thin = nci.withings_trend(rows[-3:], keys)
    assert thin["rate_provisional"] is True and thin["weekly_loss_rates_lb_wk"] == [2.8]
    assert nci.withings_trend(None, keys)["weight_lb"] is None


def test_withings_trend_excludes_the_water_weeks():
    """Mutation control: drop the water floor in `loss_rate_from_rows` — the 14 days ending
    09-20 then read the whole of weeks 1-2 and a rate appears."""
    rows = [{"date": k, "weight_lbs": 330 - 0.9 * i} for i, k in enumerate(KEYS)]
    t = nci.withings_trend(rows, KEYS)
    assert t["loss_rate"]["water_weeks_excluded_through"] == "2026-09-19"
    assert t["loss_rate"]["window"]["start"] == "2026-09-20" and t["loss_rate"]["n_weighins"] == 1
    assert t["weight_trend_lb_wk"] is None and t["loss_rate"]["rate_lb_wk"] is None


def test_the_resolver_block_carries_the_verdicts_and_names_what_it_could_not_read(monkeypatch):
    rows = {
        "macrofactor": [{"date": k, "total_calories_kcal": 1533, "total_protein_g": 146} for k in KEYS],
        "hevy": [{"date": k, "exercises": [{"name": "Squat (Barbell)", "sets": [{"reps": 5, "weight_kg": 80}]}]} for k in KEYS[::2]],
        "withings": [{"date": k, "weight_lbs": 320 - 0.4 * i} for i, k in enumerate(KEYS)],
    }
    monkeypatch.setattr(nci, "query_source", lambda source, start, end: rows[source])
    monkeypatch.setattr(nci, "_walking_hours", lambda end: 9.0)
    monkeypatch.setattr(nci, "_metabolic_severity", lambda end: None)  # IC-29 unreadable
    monkeypatch.setattr(nci, "already_logged", lambda days=14: [])
    out = nci.block("2026-09-20", deficit_severity="SUSTAINABLE", degraded_count=0)
    md = next(v for v in out["verdicts"] if v["critic"] == "muscle_defense")
    assert md["verdict"] in ("change", "veto") and md["metric"] == "energy_floor_days_below_7d"
    assert set(out["inputs_unresolved"]) == {"metabolic_adaptation"}, "only the reader that failed is named"
    assert "metabolic_adaptation_severity" in next(v for v in out["verdicts"] if v["critic"] == "deficit_advocate")["unknown"]
    assert out["window_end"] == "2026-09-20" and out["model_ran"] is False


def test_the_resolver_block_never_raises_when_every_reader_raises(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("ddb down")

    monkeypatch.setattr(nci, "query_source", boom)
    monkeypatch.setattr(nci, "_walking_hours", lambda end: None)
    monkeypatch.setattr(nci, "_metabolic_severity", lambda end: None)
    monkeypatch.setattr(nci, "already_logged", lambda days=14: None)
    out = nci.block("2026-09-20")
    assert [v["verdict"] for v in out["verdicts"]] == ["approve", "approve", "approve"]
    assert set(out["inputs_unresolved"]) >= {"macrofactor", "hevy", "withings", "walking_volume", "decisions"}
    assert all(d["state"] == "unevaluable" for d in out["decisions_offered"])
