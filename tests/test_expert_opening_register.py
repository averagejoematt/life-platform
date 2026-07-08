"""#821 (R22 CONTENT-05): the eight observatory coaches must not open as one
templated voice in hats. Deterministic guards for the voice guidance:

  - every expert persona carries a DISTINCT per-coach opening register,
  - the banned shared-scaffold openers (the exact phrases the R22 review caught
    live on /api/coach_analysis, plus the old suggested stems that WERE the
    template) are listed and injected into every expert prompt,
  - the presence / quiet-stretch guard steers the platform-wide logging-gap
    event OUT of the opening line (the event every coach used to open on),
  - none of the new prompt text introduces digits (the grounding gate whitelists
    numbers that appear in the prompt — voice guidance must not widen it).

Voice guidance only: the ADR-104 grounding and ADR-108 quality-gate mechanics
are exercised elsewhere (tests/golden_surface_eval.py etc.), not here.
"""

import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas", "intelligence"))

import ai_expert_analyzer_lambda as az  # noqa: E402

# The scaffolds the R22 review observed verbatim across coaches — the reason
# this issue exists. If someone edits the list, these must survive.
R22_OBSERVED_SCAFFOLDS = (
    "I want to be honest with you",
    "Here's what I can see, and here's what I can't",
    "the machinery is running but the operator left the cabin",
)

# The old prompt offered these stems to all eight coaches at once — they were
# the template. They must stay banned, never re-suggested.
RETIRED_SUGGESTED_STEMS = (
    "What strikes me most",
    "The figure I keep returning to",
    "The pattern worth naming",
)


def _offline_prompt(monkeypatch, expert_key, week_number=4):
    """build_prompt with every live dependency stubbed — pure template render."""
    monkeypatch.setattr(az, "_HAS_INTELLIGENCE_COMMON", False)
    monkeypatch.setattr(az, "_persona_core", None)
    data = {"expert_key": expert_key, "period": "test", "note": "fixture"}
    return az.build_prompt(expert_key, data, days_in_experiment=30, week_number=week_number)


def test_every_persona_has_an_opening_register():
    for key, p in az.EXPERT_PERSONAS.items():
        reg = p.get("opening_register", "")
        assert isinstance(reg, str) and len(reg.strip()) >= 40, f"{key} has no substantive opening_register"


def test_opening_registers_are_pairwise_distinct():
    regs = {k: p["opening_register"] for k, p in az.EXPERT_PERSONAS.items()}
    assert len(set(regs.values())) == len(regs), "two coaches share an opening register — that's the template again"


def test_banned_list_contains_the_r22_scaffolds_and_retired_stems():
    for phrase in R22_OBSERVED_SCAFFOLDS + RETIRED_SUGGESTED_STEMS:
        assert phrase in az.BANNED_OPENER_SCAFFOLDS, f"banned-scaffold list lost: {phrase!r}"


def test_prompt_injects_register_and_banned_scaffolds(monkeypatch):
    prompt = _offline_prompt(monkeypatch, "sleep")
    assert "YOUR OPENING REGISTER" in prompt
    assert az.EXPERT_PERSONAS["sleep"]["opening_register"] in prompt
    for phrase in az.BANNED_OPENER_SCAFFOLDS:
        assert phrase in prompt, f"banned scaffold not surfaced in prompt: {phrase!r}"
    # Anti-template constraints ride along.
    assert "never lead" in prompt.lower() or "never your opening line" in prompt.lower()
    assert "another coach's byline" in prompt


def test_old_shared_stems_are_no_longer_suggested(monkeypatch):
    prompt = _offline_prompt(monkeypatch, "training")
    # The stems may appear ONLY inside the banned list, never as a suggestion.
    assert 'Use "What strikes me most' not in prompt
    banned_section = prompt.split("NEVER open with any of these shared-scaffold phrases", 1)
    assert len(banned_section) == 2, "banned-scaffold constraint missing from prompt"
    for stem in RETIRED_SUGGESTED_STEMS:
        assert stem not in banned_section[0], f"{stem!r} still appears before the ban — reads as a suggestion"


def test_two_coaches_get_different_opening_guidance(monkeypatch):
    p_sleep = _offline_prompt(monkeypatch, "sleep")
    p_nutrition = _offline_prompt(monkeypatch, "nutrition")
    reg_sleep = az.EXPERT_PERSONAS["sleep"]["opening_register"]
    reg_nutrition = az.EXPERT_PERSONAS["nutrition"]["opening_register"]
    assert reg_sleep in p_sleep and reg_sleep not in p_nutrition
    assert reg_nutrition in p_nutrition and reg_nutrition not in p_sleep


def test_voice_guidance_adds_no_digits_to_the_grounding_surface():
    # grounded_generation whitelists numbers found in the prompt — the voice
    # layer must not widen that whitelist.
    for key, p in az.EXPERT_PERSONAS.items():
        assert not any(ch.isdigit() for ch in p["opening_register"]), f"digit in {key} opening_register"
    for phrase in az.BANNED_OPENER_SCAFFOLDS:
        assert not any(ch.isdigit() for ch in phrase), f"digit in banned scaffold {phrase!r}"


def test_presence_guard_steers_gap_out_of_the_opening_line(monkeypatch):
    sig = {
        "presence_class": "dark",
        "gap_days": 5,
        "last_food_log_date": "2026-06-24",
        "channels_quiet": ["food"],
        "passive_still_flowing": True,
        "planned_pause": False,
        "returned": False,
    }
    monkeypatch.setattr(az, "_load_engagement_signal", lambda: sig)
    blk = az._presence_block()
    # The honesty gate stays intact...
    assert "perfect adherence" in blk.lower()
    # ...and the placement steer is present: the shared event is not the opener.
    assert "OPENING line" in blk
    assert "templated voice" in blk


def test_shared_system_prompt_carries_the_one_voice_constraint(monkeypatch):
    monkeypatch.setattr(az, "_HAS_INTELLIGENCE_COMMON", False)
    monkeypatch.setattr(az, "_load_canonical_facts", lambda: {})
    monkeypatch.setattr(az, "_load_engagement_signal", lambda: {})
    sp = az._build_shared_system_prompt()
    assert "opening register" in sp
    assert "no other coach" in sp
