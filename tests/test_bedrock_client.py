"""
tests/test_bedrock_client.py — model routing + adaptive-surface param hygiene.

Covers:
  - resolve_model_id maps Anthropic-style names to Bedrock inference profiles
    (including fable / opus-4-8, added 2026-06-12)
  - unmapped names fall back to the cheapest current profile (haiku)
  - profile ids / ARNs pass through untouched
  - invoke() scrubs sampling params (temperature/top_p/top_k) for Fable 5 and
    Opus 4.7+ (those models 400 on them) and drops an explicit
    thinking:{type:"disabled"} on Fable — while leaving Sonnet bodies intact

Run:  python3 -m pytest tests/test_bedrock_client.py -v
"""

import json
import os
import sys
import types
from unittest.mock import MagicMock

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))

import bedrock_client as bc  # noqa: E402


def test_fable_and_opus48_map_to_us_profiles():
    assert bc.resolve_model_id("claude-fable-5") == "us.anthropic.claude-fable-5"
    assert bc.resolve_model_id("claude-opus-4-8") == "us.anthropic.claude-opus-4-8"


def test_unmapped_model_falls_back_to_haiku():
    assert "haiku" in bc.resolve_model_id("claude-future-9")


def test_profile_ids_and_arns_pass_through():
    assert bc.resolve_model_id("us.anthropic.claude-fable-5") == "us.anthropic.claude-fable-5"
    assert bc.resolve_model_id("global.anthropic.claude-sonnet-4-6") == "global.anthropic.claude-sonnet-4-6"
    arn = "arn:aws:bedrock:us-west-2:1:inference-profile/x"
    assert bc.resolve_model_id(arn) == arn


def _invoke_and_capture(monkeypatch, body, model_name):
    """Run bc.invoke with mocked Bedrock + budget guard; return the sent body."""
    # Stub budget_guard so invoke() never touches SSM.
    stub = types.ModuleType("budget_guard")
    stub.BudgetExceeded = RuntimeError
    stub.current_tier = lambda: 0
    monkeypatch.setitem(sys.modules, "budget_guard", stub)

    fake_client = MagicMock()
    fake_client.invoke_model.return_value = {"body": MagicMock(read=lambda: b'{"content": []}')}
    monkeypatch.setattr(bc, "_client", lambda: fake_client)

    bc.invoke(body, model_name=model_name)
    return json.loads(fake_client.invoke_model.call_args.kwargs["body"])


def test_invoke_scrubs_sampling_params_on_fable(monkeypatch):
    body = {"messages": [], "max_tokens": 10, "temperature": 0.7, "top_p": 0.9, "top_k": 5}
    sent = _invoke_and_capture(monkeypatch, body, "claude-fable-5")
    assert "temperature" not in sent and "top_p" not in sent and "top_k" not in sent


def test_invoke_drops_explicit_thinking_disabled_on_fable(monkeypatch):
    body = {"messages": [], "max_tokens": 10, "thinking": {"type": "disabled"}}
    sent = _invoke_and_capture(monkeypatch, body, "claude-fable-5")
    assert "thinking" not in sent


def test_invoke_keeps_adaptive_thinking_on_fable(monkeypatch):
    body = {"messages": [], "max_tokens": 10, "thinking": {"type": "adaptive"}}
    sent = _invoke_and_capture(monkeypatch, body, "claude-fable-5")
    assert sent["thinking"] == {"type": "adaptive"}


def test_invoke_leaves_sonnet_body_untouched(monkeypatch):
    body = {"messages": [], "max_tokens": 10, "temperature": 0.3}
    sent = _invoke_and_capture(monkeypatch, body, "claude-sonnet-4-6")
    assert sent["temperature"] == 0.3
