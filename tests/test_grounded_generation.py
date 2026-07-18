"""tests/test_grounded_generation.py — ADR-104 grounded-generation harness.

The core claims under test:
  * the allow-list gate catches the fabricated-trend class ("climbed from 58
    to 64" when only 64 was in the input) that no canonical-value check can;
  * canonical contradictions (RHR/recovery/HRV) surface as findings;
  * regen_once keeps a rewrite only when it's strictly better — never worse.

Run with:   python3 -m pytest tests/test_grounded_generation.py -v
"""

import os
import sys

LAMBDAS_DIR = os.path.join(os.path.dirname(__file__), "..", "lambdas")
sys.path.insert(0, os.path.abspath(LAMBDAS_DIR))

from grounded_generation import (  # noqa: E402
    allowed_numbers,
    authoritative_facts_block,
    band_adjective_findings,
    correction_prompt,
    fabricated_numbers,
    grounding_findings,
    numbers_in_text,
    regen_once,
)

FACTS = {
    "recovery_pct": 62.0,
    "hrv_ms": 25.2,
    "rhr_bpm": 64.0,
    "protein_g_avg": 148.3,
    "protein_g_target": 190.0,
    "protein_g_floor": 170.0,
    "latest_weight": 309.4,
}


# ── the allow-list ──


def test_numbers_in_text_handles_thousands_separators():
    assert numbers_in_text("walked 8,000 steps and ate 2,450 kcal") == {8000.0, 2450.0}


def test_allowed_numbers_unions_strings_and_structures():
    allowed = allowed_numbers("recovery 62%", {"sleep": {"hours": 7.4}}, [190, "64 bpm"])
    assert {62.0, 7.4, 190.0, 64.0} <= allowed


def test_fabricated_trend_endpoint_is_caught():
    """The flagship case: 'climbed from 58 to 64' with only 64 in the input."""
    allowed = allowed_numbers("resting HR: 64 bpm")
    assert fabricated_numbers("Your RHR climbed from 58 to 64 this week.", allowed) == [58.0]


def test_grounded_numbers_pass():
    allowed = allowed_numbers({"rhr": 64, "recovery": 62, "protein": 148.3})
    assert fabricated_numbers("RHR 64, recovery 62%, protein ~148.3 g", allowed) == []


def test_integer_restatement_of_input_float_is_grounded():
    allowed = allowed_numbers({"hrv": 25.2})
    assert fabricated_numbers("HRV sits at 25 ms", allowed) == []


def test_benign_small_counts_and_durations_pass():
    assert fabricated_numbers("three of the last 5 days; walk 30 minutes; since 2026", allowed_numbers("")) == []


def test_plausible_invented_vital_is_not_benign():
    assert fabricated_numbers("recovery hovering near 55", allowed_numbers("recovery data absent")) == [55.0]


# ── findings composition ──


def test_contradiction_finding_from_canonical_facts():
    text = "Resting heart rate of 53 tells a good story."
    findings = grounding_findings(text, facts=FACTS)
    assert any(f["type"] == "contradiction" and f["claimed"] == 53.0 for f in findings)


def test_fabricated_number_finding_with_allow_list():
    findings = grounding_findings("You dropped 13.8 pounds in four weeks.", allowed=allowed_numbers("weight 309.4"))
    assert [f["claimed"] for f in findings if f["type"] == "fabricated_number"] == [13.8]


def test_clean_text_yields_no_findings():
    text = "Recovery held at 62% and the resting HR of 64 was steady; protein averaged 148.3 g."
    assert grounding_findings(text, facts=FACTS, allowed=allowed_numbers(FACTS)) == []


# ── the facts block ──


def test_facts_block_contains_exact_values_and_hard_rule():
    block = authoritative_facts_block(FACTS)
    for token in ("62%", "25.2 ms", "64 bpm", "148.3", "HARD RULE"):
        assert token in block
    assert authoritative_facts_block({}) == ""


# ── regen-once, keep-if-strictly-improved ──


def _findings_fn(allowed):
    return lambda text: grounding_findings(text, facts=FACTS, allowed=allowed)


def test_regen_once_keeps_the_improved_rewrite():
    allowed = allowed_numbers(FACTS)
    bad = "Your RHR climbed from 53 to 58 this week."
    fixed = "Your resting HR held at 64 this week."
    text, findings, corrected = regen_once(bad, _findings_fn(allowed), lambda corr: fixed)
    assert corrected and text == fixed and findings == []


def test_regen_once_never_regresses():
    allowed = allowed_numbers(FACTS)
    bad = "Recovery at 31% today."
    worse = "Recovery at 31% today, HRV 50 ms, RHR 53."
    text, findings, corrected = regen_once(bad, _findings_fn(allowed), lambda corr: worse)
    assert not corrected and text == bad and findings


def test_regen_once_no_findings_no_call():
    calls = []

    def regen(corr):
        calls.append(corr)
        return "unused"

    text, findings, corrected = regen_once("Recovery 62% held.", _findings_fn(allowed_numbers(FACTS)), regen)
    assert text == "Recovery 62% held." and not corrected and not calls


def test_regen_once_survives_regen_exception():
    allowed = allowed_numbers(FACTS)
    bad = "RHR of 53 again."

    def boom(corr):
        raise RuntimeError("api down")

    text, findings, corrected = regen_once(bad, _findings_fn(allowed), boom)
    assert text == bad and not corrected and findings


def test_correction_prompt_names_canonical_value():
    findings = grounding_findings("Resting heart rate of 53.", facts=FACTS)
    corr = correction_prompt(findings)
    assert "64" in corr and "never invent" in corr


# ── band↔adjective (#1208): number-true but verdict-false ─────────────────────
# The live incident: "Strong biometric recovery—44% on Whoop" — 44% is Whoop's
# YELLOW band, so "Strong" is semantically false though 44 is digit-grounded.
_LIVE_INCIDENT = "Strong biometric recovery—44% on Whoop, 34 ms HRV, resting heart rate holding at 62"


def test_band_adjective_flags_superlative_on_yellow_recovery():
    # NON-VACUOUS: this exact draft drew ZERO findings before the fix (number gate
    # only). It must now yield a band_contradiction.
    findings = band_adjective_findings(_LIVE_INCIDENT, {"recovery_pct": 44})
    assert len(findings) == 1
    f = findings[0]
    assert f["type"] == "band_contradiction" and f["band"] == "yellow" and f["adjective"].lower() == "strong"


def test_band_adjective_flows_through_grounding_findings():
    # The live surface (ai_expert_analyzer) calls grounding_findings(text, facts, allowed).
    findings = grounding_findings(_LIVE_INCIDENT, facts={"recovery_pct": 44}, allowed=allowed_numbers(_LIVE_INCIDENT))
    assert any(f["type"] == "band_contradiction" for f in findings)


def test_band_adjective_no_flag_on_honest_yellow_adjective():
    # TRUE NEGATIVE: an honest band word for 44% must NOT flag.
    assert band_adjective_findings("Moderate recovery — 44% on Whoop today.", {"recovery_pct": 44}) == []


def test_band_adjective_no_flag_when_superlative_matches_green():
    # TRUE NEGATIVE: "strong" is genuinely consistent with a green-band value.
    assert band_adjective_findings("Strong recovery — 72% on Whoop today.", {"recovery_pct": 72}) == []


def test_band_adjective_no_flag_on_unrelated_superlative():
    # TRUE NEGATIVE: a superlative describing something else, far from any recovery
    # mention, must not be attributed to recovery.
    text = (
        "Recovery sat at 44% this morning, well into the yellow zone for him. "
        "Much later that afternoon he hit a strong set of heavy back squats in the gym."
    )
    assert band_adjective_findings(text, {"recovery_pct": 44}) == []


def test_band_adjective_flags_red_band():
    findings = band_adjective_findings("An excellent recovery at 20%.", {"recovery_pct": 20})
    assert len(findings) == 1 and findings[0]["band"] == "red"


def test_band_adjective_correction_prompt_says_use_band_word():
    findings = grounding_findings(_LIVE_INCIDENT, facts={"recovery_pct": 44})
    corr = correction_prompt([f for f in findings if f["type"] == "band_contradiction"])
    assert "yellow" in corr and "superlative" in corr


def test_band_adjective_noop_without_facts():
    assert band_adjective_findings(_LIVE_INCIDENT, None) == []
    assert band_adjective_findings(_LIVE_INCIDENT, {}) == []
