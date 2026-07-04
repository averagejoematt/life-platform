"""tests/test_persona_core.py — #531: one mind per coach.

The shared persona core (persona_core.py) renders the SAME voice-spec fields
(config/coaches/*.json) for every surface: the daily brief keeps its inline
assembly, while the public board (site_api_ai_lambda) and the observatory
experts (ai_expert_analyzer_lambda) render this block. These tests pin:

  P1  voice_block is deterministic + renders the load-bearing spec fields
  P2  defensive caps hold (a corrupt spec can't balloon a cached system block)
  P3  load_voice_spec local fallback resolves every operational coach
  P4  the board system prompt carries the voice core + stays byte-stable
  P5  board_ask loads memory (COMPRESSED#latest) + episodic recall and writes
      the answer back into coach memory AFTER the grounding gate
  P6  the observatory expert prompt sources the same persona core
  P7  the summarizer's coach meta comes from the canonical registry (the old
      hand-copied dict had drifted to a retired cast)
  P8  the weekly compression folds INTERACTION# records in
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

import persona_core  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AI_SRC = open(os.path.join(ROOT, "lambdas/web/site_api_ai_lambda.py")).read()
EXPERT_SRC = open(os.path.join(ROOT, "lambdas/intelligence/ai_expert_analyzer_lambda.py")).read()
SUMMARIZER_SRC = open(os.path.join(ROOT, "lambdas/coach/coach_history_summarizer.py")).read()

OPERATIONAL = [
    "sleep_coach",
    "training_coach",
    "nutrition_coach",
    "mind_coach",
    "physical_coach",
    "glucose_coach",
    "labs_coach",
    "explorer_coach",
]


# ── P1: rendering ─────────────────────────────────────────────────────────────


def test_voice_block_renders_spec_fields():
    spec = persona_core.load_voice_spec("sleep_coach")
    block = persona_core.voice_block(spec)
    assert "YOUR VOICE" in block
    assert "Sentence rhythm:" in block
    assert "Uncertainty:" in block
    assert "DECISION STYLE:" in block
    assert "NEVER USE" in block
    # deterministic — same spec, same bytes (the prompt-cache contract)
    assert block == persona_core.voice_block(spec)


def test_voice_block_handles_junk():
    assert persona_core.voice_block(None) == ""
    assert persona_core.voice_block({}) == ""
    assert persona_core.voice_block("not a dict") == ""


# ── P2: caps ──────────────────────────────────────────────────────────────────


def test_voice_block_caps_hold():
    bloated = {
        "structural_voice_rules": {
            "sentence_rhythm": "x" * 5000,
            "signature_moves": [f"move {i}" for i in range(50)],
        },
        "anti_pattern_detection": {"phrase_blacklist": [f"phrase {i}" for i in range(50)]},
    }
    block = persona_core.voice_block(bloated)
    assert len(block) < 3000
    assert "move 5" in block and "move 6" not in block  # _MAX_LIST_ITEMS=6
    assert "phrase 5" in block and "phrase 6" not in block


# ── P3: every operational coach resolves offline ─────────────────────────────


def test_every_operational_coach_has_a_loadable_spec():
    for cid in OPERATIONAL:
        spec = persona_core.load_voice_spec(cid, force_refresh=True)
        assert isinstance(spec, dict), f"{cid} spec missing"
        assert spec.get("coach_id") == cid
        block = persona_core.voice_block(spec)
        assert "YOUR VOICE" in block, f"{cid} voice block empty"


def test_unknown_coach_fails_soft():
    assert persona_core.load_voice_spec("no_such_coach", force_refresh=True) is None
    assert persona_core.persona_block("no_such_coach") == ""


# ── P4/P5: the public board (source-level + pure-function) ────────────────────


def _ai():
    from web import site_api_ai_lambda as ai

    return ai


def test_board_system_prompt_carries_the_voice_core():
    ai = _ai()
    for pid in OPERATIONAL:
        sysp = ai._coach_system(pid)
        assert "YOUR VOICE" in sysp, f"{pid} board self lost the voice core"
        assert "WHERE YOU ARE" in sysp  # the #356 preamble survives
        # byte-stable — the ephemeral prompt-cache contract
        assert sysp == ai._coach_system(pid)


def test_board_ask_loads_memory_and_episodic_recall():
    import re

    body = re.search(r"def _handle_board_ask.*?(?=\ndef |\Z)", AI_SRC, re.S).group(0)
    assert "_coach_memory_bits(" in body
    assert "_coach_recent_interactions(" in body
    assert "YOUR MEMORY" in body and "YOUR RECENT BOARD ANSWERS" in body


def test_board_answer_written_back_after_grounding_gate():
    """The episodic record must store what the reader actually saw — so the
    write-back call must come AFTER the grounding gate replaces an ungrounded
    answer with the refusal."""
    import re

    body = re.search(r"def _handle_board_ask.*?(?=\ndef |\Z)", AI_SRC, re.S).group(0)
    gate = body.find("grounding_findings")
    writeback = body.find("_write_board_interaction(")
    assert 0 < gate < writeback, "write-back must follow the grounding gate"


def test_interaction_record_shape():
    """Write-back targets COACH#{pid} / INTERACTION#... — the partition the
    weekly summarizer folds in (and the role's LeadingKeys allow)."""
    assert 'f"COACH#{pid}"' in AI_SRC
    assert "INTERACTION#" in AI_SRC
    assert '"interaction_type": "board_qa"' in AI_SRC


# ── P6: observatory experts ───────────────────────────────────────────────────


def test_expert_prompt_sources_the_persona_core():
    assert "persona_core" in EXPERT_SRC
    assert 'persona_block(f"{expert_key}_coach"' in EXPERT_SRC


# ── P7: canonical names (the retired-cast drift is dead) ─────────────────────


def test_summarizer_meta_is_registry_derived():
    assert "Elena Vasquez" not in SUMMARIZER_SRC, "retired cast name still hardcoded"
    assert "_coach_meta(" in SUMMARIZER_SRC
    assert "persona_registry" in SUMMARIZER_SRC


def test_registry_meta_resolves_canonical_names():
    import persona_registry

    reg = persona_registry.load_registry(force_refresh=True)
    assert reg["personas"]["nutrition_coach"]["name"] == "Dr. Marcus Webb"
    assert reg["personas"]["sleep_coach"]["name"] == "Dr. Lisa Park"


# ── P8: the summarizer folds board Q&A in ─────────────────────────────────────


def test_summarizer_gathers_and_folds_interactions():
    assert '"INTERACTION#"' in SUMMARIZER_SRC
    assert "MAX_INTERACTIONS_IN_PROMPT" in SUMMARIZER_SRC
    assert "Reader Interactions" in SUMMARIZER_SRC
    # and the compression system prompt tells Haiku to preserve them
    assert "reader interactions" in SUMMARIZER_SRC.lower()
