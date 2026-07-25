"""
tests/test_whole_life_context_1385.py — #1385 (epic #1080): whole-life-context
chronicle + State of Matthew over the full multi-cycle archive via 1-hour cached
reads, with the grounded-generation gate widened to match (rigor is the product).

Covers:
  AC2 — the archive is passed as a 1-hour cache_control block (NOT inline uncached),
        on both the chronicle call path and State of Matthew.
  AC3 — a fabricated dated/numeric callback is still caught by the grounding gate,
        while a real archival callback passes ONLY because the archive feeds the
        allow-list (proving the widened window didn't widen the fabrication surface).
  AC4 — Bedrock Structured Outputs support at the chokepoint + the installment schema
        validation.
  AC5 — State of Matthew remains tier-2-paused (budget gating unchanged).
"""

import importlib
import json

import pytest
import whole_life_context as wlc

# ── AC2: cached-block wiring (the primitive) ────────────────────────────────


def test_archive_rides_as_1h_cache_control_block_not_inline():
    system = "You are Elena."
    archive = "=== ARCHIVE ===\nWeek 1: he began."
    blocks = wlc.with_cached_archive(system, archive)
    # A list of content blocks — not the bare string (which would be uncached inline).
    assert isinstance(blocks, list)
    # The archive is its OWN block, cached at 1-hour TTL (reads at ~0.1x).
    archive_block = blocks[-1]
    assert archive_block["text"] == archive
    assert archive_block["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
    # The persona prompt precedes it as a stable cached prefix (cache-hit requirement).
    assert blocks[0]["text"] == system
    assert blocks[0]["cache_control"]["ttl"] == "1h"


def test_no_archive_leaves_system_unchanged():
    assert wlc.with_cached_archive("sys", "") == "sys"
    assert wlc.with_cached_archive("sys", None) == "sys"


def test_format_full_archive_multicycle_oldest_first_untruncated():
    installments = [
        {"cycle": 2, "week_number": 1, "date": "2026-07-01", "title": "New start", "content_markdown": "B" * 5000},
        {"cycle": 1, "week_number": 3, "date": "2026-05-08", "title": "The plunge", "content_markdown": "A" * 5000},
    ]
    text = wlc.format_full_archive(installments)
    # Oldest cycle first.
    assert text.index("The plunge") < text.index("New start")
    # Un-truncated — the full 5000-char bodies survive (the old path capped at 2000).
    assert "A" * 5000 in text
    assert "B" * 5000 in text


def test_format_full_archive_empty():
    assert wlc.format_full_archive([]) == ""
    assert wlc.format_full_archive([{"content_markdown": "   "}]) == ""


# ── AC2: chronicle call path passes the archive as the 1h cached system block ─


def test_chronicle_call_anthropic_sends_archive_as_cached_block(monkeypatch):
    import chronicle_prompt
    import retry_utils

    captured = {}

    def _fake_call(**kwargs):
        captured.update(kwargs)
        return "stub installment"

    monkeypatch.setattr(retry_utils, "call_anthropic_api", _fake_call)
    archive = "=== ARCHIVE ===\nreal history"
    chronicle_prompt.call_anthropic("You are Elena.", "This week's packet", archive_text=archive)

    system = captured["system"]
    assert isinstance(system, list)  # multi-block, not a bare string
    assert any(b.get("text") == archive and b["cache_control"].get("ttl") == "1h" for b in system)
    # The volatile weekly packet stays in the (uncached) user turn, not the cached block.
    assert captured["prompt"] == "This week's packet"


def test_chronicle_call_anthropic_no_archive_is_plain_string(monkeypatch):
    import chronicle_prompt
    import retry_utils

    captured = {}
    monkeypatch.setattr(retry_utils, "call_anthropic_api", lambda **kw: captured.update(kw) or "x")
    chronicle_prompt.call_anthropic("You are Elena.", "packet")
    assert captured["system"] == "You are Elena."  # backward-compatible


# ── AC2: State of Matthew carries the archive as a 1h cached block ────────────


def test_state_of_matthew_narration_body_archive_cached_block():
    som = importlib.import_module("state_of_matthew_lambda")
    archive = "=== ARCHIVE ===\nWeek 3 (2026-05-08): the plunge, 218.4 lbs."
    state = {"as_of": "2026-07-22", "phase": {"as_of": "2026-07-22"}, "archive_text": archive}
    body = som.build_narration_body(state)
    system = body["system"]
    assert isinstance(system, list)
    assert any(b.get("text") == archive and b["cache_control"].get("ttl") == "1h" for b in system)
    # Archive is context in the cached block — NOT dumped inline into the user turn.
    assert archive not in body["messages"][0]["content"]


def test_state_of_matthew_no_archive_is_plain_string():
    som = importlib.import_module("state_of_matthew_lambda")
    state = {"as_of": "2026-07-22", "phase": {"as_of": "2026-07-22"}}
    body = som.build_narration_body(state)
    assert isinstance(body["system"], str)  # unchanged when no archive


# ── AC3: the grounding gate still catches fabricated dated callbacks ──────────


def _archive_with_real_callback():
    return wlc.format_full_archive(
        [
            {
                "cycle": 1,
                "week_number": 3,
                "date": "2026-05-08",
                "title": "The plunge",
                "content_markdown": "On 2026-05-08 he first tried the cold plunge, weighing 218.4 lbs.",
            }
        ]
    )


def test_real_archive_callback_passes_only_because_archive_feeds_allowlist():
    import chronicle_prompt

    elena_prompt = "You are Elena Voss."
    user_message = "Week ending: 2026-07-22\nWeight: 210 lbs this week."
    archive = _archive_with_real_callback()
    # A genuine callback to the archived attempt: its date + weight are real.
    text = "Back on 2026-05-08, at 218.4 lbs, he first braved the plunge — this week he did it again."

    # WITH the archive in the allow-list: grounded, ships clean.
    assert chronicle_prompt.installment_grounding_findings(elena_prompt, user_message, text, archive_text=archive) == []
    # WITHOUT the archive: the SAME real callback is (wrongly) flagged — proving the
    # widened window MUST widen the allow-list, or every callback false-fails.
    assert chronicle_prompt.installment_grounding_findings(elena_prompt, user_message, text, archive_text=None) != []


def test_fabricated_dated_callback_is_caught_even_with_whole_life_context():
    import chronicle_prompt

    elena_prompt = "You are Elena Voss."
    user_message = "Week ending: 2026-07-22\nWeight: 210 lbs this week."
    archive = _archive_with_real_callback()
    # A fabricated callback: 2026-01-15 and 195.2 lbs appear nowhere — prompt, packet,
    # or archive. Whole-life context must NOT let this through.
    text = "He tried it back on 2026-01-15, weighing 195.2 lbs at the time."
    findings = chronicle_prompt.installment_grounding_findings(elena_prompt, user_message, text, archive_text=archive)
    details = " ".join(str(f) for f in findings)
    assert findings, "fabricated dated callback must be caught"
    assert "2026-01-15" in details or "195.2" in details


# ── AC4: Bedrock Structured Outputs at the chokepoint + installment schema ────


def test_bedrock_structured_output_config_shape():
    import bedrock_client
    import chronicle_schema

    cfg = bedrock_client.structured_output_config(chronicle_schema.INSTALLMENT_SCHEMA)
    assert cfg == {"format": {"type": "json_schema", "schema": chronicle_schema.INSTALLMENT_SCHEMA}}


def test_invoke_forwards_output_config_and_strips_model(monkeypatch):
    import bedrock_client

    captured = {}

    class _FakeBody:
        def read(self):
            return json.dumps({"content": [{"type": "text", "text": "ok"}], "usage": {}}).encode()

    class _FakeClient:
        def invoke_model(self, *, modelId, body, contentType, accept):
            captured["modelId"] = modelId
            captured["body"] = json.loads(body)
            return {"body": _FakeBody()}

    monkeypatch.setattr(bedrock_client, "_BEDROCK", _FakeClient())
    monkeypatch.setattr(bedrock_client, "_emit_usage_metrics", lambda *a, **k: None)
    monkeypatch.delenv("BEDROCK_SHADOW_MODE", raising=False)

    schema = {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"], "additionalProperties": False}
    body = {
        "model": "claude-sonnet-4-6",
        "max_tokens": 100,
        "messages": [{"role": "user", "content": "hi"}],
        "output_config": bedrock_client.structured_output_config(schema),
    }
    bedrock_client.invoke(body)
    sent = captured["body"]
    assert sent["output_config"] == {"format": {"type": "json_schema", "schema": schema}}  # forwarded
    assert "model" not in sent  # stripped from the Bedrock body
    assert sent["anthropic_version"] == "bedrock-2023-05-31"


def test_installment_schema_validates_good_and_rejects_bad():
    import chronicle_schema

    good = {"title": "The week it clicked", "weight_lbs": 209.4, "week_grade": 71.0, "t0_streak_days": 12, "body_markdown": "..."}
    assert chronicle_schema.validate_installment(good) == []

    missing = {"title": "x", "weight_lbs": 209.4, "week_grade": 71.0, "body_markdown": "..."}  # no t0_streak_days
    assert chronicle_schema.validate_installment(missing)

    wrong_type = dict(good, t0_streak_days="twelve")
    assert chronicle_schema.validate_installment(wrong_type)

    extra = dict(good, surprise=1)
    assert chronicle_schema.validate_installment(extra)


def test_parse_stats_line_feeds_schema_validation():
    import chronicle_schema

    stats = "[Weight: 209.4 lbs | Week Grade: avg 71 | T0 Streak: 12 days]"
    envelope = chronicle_schema.installment_from_stats("A title", chronicle_schema.parse_stats_line(stats), "body")
    assert chronicle_schema.validate_installment(envelope) == []

    # A garbled stat line (missing the streak number) fails the schema — the parse
    # error is CAUGHT deterministically instead of silently mis-rendered.
    garbled = "[Weight: 209.4 lbs | Week Grade: avg 71]"
    envelope2 = chronicle_schema.installment_from_stats("A title", chronicle_schema.parse_stats_line(garbled), "body")
    assert chronicle_schema.validate_installment(envelope2)


# ── AC5: budget gating unchanged — State of Matthew stays tier-2-paused ───────


def test_state_of_matthew_still_budget_gated(monkeypatch):
    som = importlib.import_module("state_of_matthew_lambda")
    import budget_guard

    # This surface pauses at tier 2 alongside the other reader narratives (ADR-125).
    assert som.BUDGET_FEATURE == "state_of_matthew"

    monkeypatch.setattr(budget_guard, "allow", lambda feature: False)  # simulate the pause
    state = {"as_of": "2026-07-22", "phase": {"as_of": "2026-07-22"}, "archive_text": "big archive"}
    result = som.narrate(state)
    # New whole-life cost rides the SAME lever — a pause still short-circuits to the
    # deterministic fallback before any Bedrock call.
    assert result["narrated"] is False
    assert result["reason"] == "budget_tier"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
