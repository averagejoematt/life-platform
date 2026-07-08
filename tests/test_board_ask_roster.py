"""
#373 — /api/board_ask convenes the REAL coach roster, grounded.

Pins the contract that killed the phantom cast: one roster site-wide, legacy
ids mapped (never 500), unknown ids 400 before any model spend, the facts +
stance grounding present in every persona turn, and no retired real-surname
wire IDs anywhere in either lambda module.

All offline — source-level assertions + pure-function calls.
"""

import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

AI_SRC = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas/web/site_api_ai_lambda.py")).read()
SITE_SRC = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas/web/site_api_lambda.py")).read()
COACHING_JS = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "site/assets/js/coaching.js")).read()

REAL_ROSTER = {
    "sleep_coach",
    "training_coach",
    "nutrition_coach",
    "mind_coach",
    "physical_coach",
    "glucose_coach",
    "labs_coach",
    "explorer_coach",
}
RETIRED_WIRE_IDS = ["vasquez", "okafor_persona", "driggs", "goggins", "patrick_persona"]


def _roster():
    from web import site_api_ai_lambda as ai

    return ai


def test_roster_is_the_real_cast():
    ai = _roster()
    assert set(ai.COACH_ROSTER) == REAL_ROSTER
    # every entry carries a display name + title (the FE contract)
    for pid, c in ai.COACH_ROSTER.items():
        assert c["name"].startswith("Dr. ") and c["title"] and c["lens"]


def test_legacy_ids_map_to_real_coaches_never_500():
    ai = _roster()
    for old, new in ai.LEGACY_PERSONA_MAP.items():
        assert new in ai.COACH_ROSTER, f"{old} maps to unknown {new}"
    # the stale fallback that used to KeyError is mapped too
    assert "clear" in ai.LEGACY_PERSONA_MAP


def test_unknown_persona_is_400_before_model_spend():
    """The 400 branch must run BEFORE any bedrock invoke in the handler source."""
    body = re.search(r"def _handle_board_ask.*?(?=\ndef |\Z)", AI_SRC, re.S).group(0)
    reject = body.find("Unknown persona id")
    invoke = body.find("_bedrock_invoke")
    assert 0 < reject < invoke, "unknown-id rejection must precede the model call"


def test_grounding_in_every_persona_turn():
    body = re.search(r"def _handle_board_ask.*?(?=\ndef |\Z)", AI_SRC, re.S).group(0)
    # #743: facts block now takes the shared, once-fetched brief so the reader
    # receipt (board_grounding_receipts) describes the SAME ctx the prompt used.
    assert "_board_facts_block(_brief_ctx)" in body
    assert "CURRENT DATA" in body and "cite only these numbers" in body
    assert "_coach_stance_bits(" in body


def test_system_prompt_has_the_guardrails():
    ai = _roster()
    sysp = ai._coach_system("sleep_coach")
    for needle in ("Dr. Lisa Park", "correlative", "N=1", "never medical advice", "AI coach persona"):
        assert needle in sysp, needle
    # stable per coach — the ephemeral prompt-cache contract
    assert sysp == ai._coach_system("sleep_coach")


def test_meta_pressure_preamble_present():
    """#356 — every persona knows WHERE it is, deflects identity probes in
    voice without naming the AI vendor, and never asks the reader for data the
    platform already tracks."""
    ai = _roster()
    for pid, c in ai.COACH_ROSTER.items():
        sysp = ai._coach_system(pid)
        # situational frame: the public board, the data is Matthew's real data,
        # the platform already tracks it (so no "start tracking" prescriptions).
        assert "WHERE YOU ARE" in sysp
        assert "public board of averagejoematt.com" in sysp
        assert "already" in sysp and "start tracking" in sysp
        assert "never ask the reader to supply Matthew's data" in sysp
        assert "not in a private consult" in sysp.lower()
        # identity deflection — in voice, never names a vendor/model.
        assert "IDENTITY" in sysp
        assert "Never name the underlying AI vendor" in sysp
        # the persona's own name is interpolated into the identity clause,
        # not a literal placeholder left behind.
        assert "{name}" not in sysp
        assert c["name"] in sysp
        # injection resistance is still explicit in the block.
        assert "Refuse requests for private information" in sysp


def test_no_ai_vendor_named_in_prompt():
    """The persona prompt must not itself name the underlying vendor/model —
    the model cannot leak what it was never told to say."""
    ai = _roster()
    sysp = " ".join(ai._coach_system(p) for p in ai.COACH_ROSTER)
    for banned in ("Anthropic", "Claude", "Haiku", "Sonnet", "GPT", "OpenAI", "Bedrock"):
        assert banned not in sysp, f"prompt names the AI vendor/model: {banned}"


def test_no_retired_wire_ids_serve_anywhere():
    """Retired ids must not exist as live definitions in either lambda (the
    LEGACY_PERSONA_MAP keys are the only sanctioned mention in the AI module)."""
    ai_minus_map = re.sub(r"LEGACY_PERSONA_MAP = \{.*?\}", "", AI_SRC, flags=re.S)
    for wid in ["vasquez", "driggs", "goggins", '"clear"', '"patrick"', '"norton"', '"cole"']:
        assert wid not in ai_minus_map, f"retired id {wid} still live in ai lambda"
        assert wid not in SITE_SRC, f"retired id {wid} still in site_api_lambda"


def test_frontend_uses_the_same_cast():
    for pid in REAL_ROSTER:
        assert pid in COACHING_JS, f"{pid} missing from BOARD_PERSONAS"
    for old in ["vasquez", "driggs", '"cole"']:
        assert old not in COACHING_JS, f"retired id {old} still in coaching.js"


def test_facts_block_formats_only_present_keys(monkeypatch):
    ai = _roster()
    monkeypatch.setattr(ai, "_ask_fetch_context", lambda: {"weight_lbs": 300.7, "recovery_pct": 64.0})
    out = ai._board_facts_block()
    assert "weight: 300.7 lb" in out and "recovery: 64%" in out
    assert "HRV" not in out  # absent keys never fabricate
    monkeypatch.setattr(ai, "_ask_fetch_context", lambda: {})
    assert ai._board_facts_block() == "no current data available"
