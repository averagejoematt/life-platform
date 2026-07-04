"""tests/test_journal_extraction_v2.py — #505 (J-2/J-5/J-6): schema v2.

The contract:
  - ONE Haiku pass — the defense fields ride the main FIELD_MAPPING; the dead
    fields (emotional_depth, defense_context) are gone from the schema.
  - The extraction trio (entities/behaviors/causal_hints) is written, and every
    causal hint is deterministically grounded: a hint whose quote isn't verbatim
    in the entry is dropped before the write (the ADR-104 pattern).
  - The two "too short" floors (enricher vs analyzer) are the same 20-WORD floor.
  - retry_utils.call_anthropic_raw accepts a plain Messages dict (the urllib
    Request scaffolding is legacy-only).
"""

import os

os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")

import json  # noqa: E402
import urllib.request  # noqa: E402

import ingestion.journal_enrichment_lambda as enr  # noqa: E402

# ── One pass, v2 schema (J-6) ─────────────────────────────────────────────


def test_defense_pass_is_gone():
    """The second Haiku call and its plumbing must not exist."""
    for name in ("call_haiku_defense", "apply_defense_enrichment", "DEFENSE_SYSTEM_PROMPT", "ENRICH_DEFENSE_PATTERNS"):
        assert not hasattr(enr, name), f"{name} should have been deleted in v2"


def test_field_mapping_v2_shape():
    fm = enr.FIELD_MAPPING
    # the trio + the folded-in defense fields are written
    assert fm["entities"] == ("enriched_entities", "L")
    assert fm["behaviors"] == ("enriched_behaviors", "L")
    assert fm["causal_hints"] == ("enriched_causal_hints", "L")
    assert fm["defense_patterns"] == ("enriched_defense_patterns", "L")
    assert fm["primary_defense"] == ("enriched_primary_defense", "S")
    # the dead fields are not
    written = {col for col, _ in fm.values()}
    assert "enriched_emotional_depth" not in written
    assert "enriched_defense_context" not in written


def test_prompt_asks_for_the_trio_in_one_call():
    for key in ('"entities"', '"behaviors"', '"causal_hints"', '"defense_patterns"'):
        assert key in enr.USER_PROMPT_TEMPLATE
    for dead in ("emotional_depth_rating", "defense_context"):
        assert dead not in enr.USER_PROMPT_TEMPLATE


# ── Grounding gate (ADR-104 pattern) ──────────────────────────────────────

RAW = "Slept badly again. I skipped the evening walk because the workday ran long. Felt foggy all morning."


def test_grounded_hint_survives():
    hints = [
        {
            "cause": "workday ran long",
            "effect": "skipped the evening walk",
            "quote": "I skipped the evening walk because the workday ran long.",
        }
    ]
    kept, dropped = enr._ground_causal_hints(hints, RAW)
    assert len(kept) == 1 and dropped == 0


def test_ungrounded_quote_is_dropped():
    hints = [{"cause": "stress", "effect": "poor sleep", "quote": "Stress always wrecks my sleep."}]  # not in the entry
    kept, dropped = enr._ground_causal_hints(hints, RAW)
    assert kept == [] and dropped == 1


def test_grounding_normalizes_whitespace_and_case():
    hints = [{"cause": "c", "effect": "e", "quote": "i skipped the   evening walk because the workday ran long."}]
    kept, dropped = enr._ground_causal_hints(hints, RAW)
    assert len(kept) == 1 and dropped == 0


def test_malformed_hints_are_dropped():
    kept, dropped = enr._ground_causal_hints(
        ["not a dict", {"quote": "Slept badly again."}, {"cause": "c", "effect": "e", "quote": ""}], RAW
    )
    assert kept == [] and dropped == 3


def test_apply_enrichment_runs_the_gate(monkeypatch):
    written = {}

    def fake_update_item(Key, UpdateExpression, ExpressionAttributeNames, ExpressionAttributeValues):
        written["names"] = ExpressionAttributeNames
        written["values"] = ExpressionAttributeValues

    monkeypatch.setattr(enr.table, "update_item", fake_update_item)
    item = {"pk": "p", "sk": "s", "raw_text": RAW}
    enrichment = {
        "mood_score": 3,
        "causal_hints": [
            {"cause": "workday ran long", "effect": "skipped walk", "quote": "I skipped the evening walk because the workday ran long."},
            {"cause": "x", "effect": "y", "quote": "This sentence is fabricated."},
        ],
    }
    assert enr.apply_enrichment(item, enrichment) is True
    hints = written["values"][":enriched_causal_hints"]
    assert len(hints) == 1 and hints[0]["quote"].startswith("I skipped")
    # every write stamps the schema version
    assert int(written["values"][":esv"]) == enr.SCHEMA_VERSION == 2


# ── Floors aligned (J-5) ──────────────────────────────────────────────────


def test_floors_are_the_same_20_words():
    import intelligence.journal_analyzer_lambda as ana

    assert enr.MIN_TEXT_WORDS == ana.MIN_TEXT_WORDS == 20
    assert not hasattr(enr, "MIN_TEXT_LENGTH"), "the old char floor should be gone"


# ── Dead scaffolding deleted (J-2) ────────────────────────────────────────


def test_enricher_scaffolding_gone():
    assert not hasattr(enr, "get_anthropic_key")
    assert not hasattr(enr, "ANTHROPIC_API")


def test_analyzer_key_fetch_gone():
    import intelligence.journal_analyzer_lambda as ana

    assert not hasattr(ana, "_get_api_key")
    assert not hasattr(ana, "AI_SECRET_NAME")


def test_call_anthropic_raw_accepts_dict_and_legacy_request(monkeypatch):
    import bedrock_client
    import retry_utils

    seen = []

    def fake_invoke(body, model_name=None):
        seen.append(body)
        return {"content": [{"type": "text", "text": "ok"}]}

    monkeypatch.setattr(bedrock_client, "invoke", fake_invoke)

    body = {"model": "m", "max_tokens": 5, "messages": [{"role": "user", "content": "hi"}]}
    assert retry_utils.call_anthropic_raw(body)["content"][0]["text"] == "ok"

    legacy = urllib.request.Request("https://api.anthropic.com/v1/messages", data=json.dumps(body).encode())
    assert retry_utils.call_anthropic_raw(legacy)["content"][0]["text"] == "ok"

    assert seen[0] == body and seen[1] == body
