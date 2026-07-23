"""tests/test_retry_utils_behavior.py — behavioral coverage for the shared
Anthropic/Bedrock retry wrapper (lambdas/retry_utils.py).

This module is bundled into every AI-emitting Lambda (daily brief, digests,
chronicle, hypothesis engine, …) and is the ONE place backoff, prompt-caching,
and the AnthropicAPIFailure CloudWatch signal live — so its retry/no-retry
decisions and the cached-system-block wire shape are deploy-critical. Prior to
#1658 it had only wiring/import assertions and zero behavioral tests.

Every test asserts real behavior: a controlled fake `bedrock_client.invoke`
(monkeypatched on the real module, so the real wrapper runs) drives the retry
ladder; `time.sleep` is stubbed so the 5/15/45s backoff never actually blocks;
the CloudWatch client is a recorder so failure/token metrics are asserted, not
sent.
"""

import json

import pytest
import retry_utils
from botocore.exceptions import ClientError


class _RecordingCW:
    """Stand-in for the module-level CloudWatch client: records put_metric_data."""

    def __init__(self):
        self.calls = []

    def put_metric_data(self, **kwargs):
        self.calls.append(kwargs)

    def metric_names(self):
        names = []
        for c in self.calls:
            for m in c.get("MetricData", []):
                names.append(m["MetricName"])
        return names


def _client_error(code):
    return ClientError({"Error": {"Code": code, "Message": "x"}}, "InvokeModel")


@pytest.fixture
def cw(monkeypatch):
    rec = _RecordingCW()
    monkeypatch.setattr(retry_utils, "_cw", rec)
    return rec


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """Never actually sleep the 5/15/45s backoff during tests."""
    slept = []
    monkeypatch.setattr(retry_utils.time, "sleep", lambda s: slept.append(s))
    return slept


def _patch_invoke(monkeypatch, side_effect):
    """Monkeypatch bedrock_client.invoke — the real retry wrapper imports it by
    name inside the call, so patching the attribute is what production would see."""
    import bedrock_client

    calls = {"n": 0, "bodies": []}

    def fake_invoke(body, model_name=None):
        calls["n"] += 1
        calls["bodies"].append((body, model_name))
        result = side_effect(calls["n"])
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(bedrock_client, "invoke", fake_invoke)
    return calls


# ── _build_system_block ──────────────────────────────────────────────────────


def test_build_system_block_none_returns_none():
    assert retry_utils._build_system_block(None, True) is None
    assert retry_utils._build_system_block("", True) is None


def test_build_system_block_str_cached_wraps_with_cache_control():
    block = retry_utils._build_system_block("SYSTEM RULES", cache_system=True)
    assert block == [{"type": "text", "text": "SYSTEM RULES", "cache_control": {"type": "ephemeral"}}]


def test_build_system_block_str_uncached_passthrough():
    assert retry_utils._build_system_block("SYSTEM RULES", cache_system=False) == "SYSTEM RULES"


def test_build_system_block_list_passthrough_unchanged():
    already = [{"type": "text", "text": "x"}]
    assert retry_utils._build_system_block(already, cache_system=True) is already


# ── call_anthropic_api: success/body shape ──────────────────────────────────


def test_call_anthropic_api_success_returns_stripped_text(monkeypatch, cw):
    calls = _patch_invoke(monkeypatch, lambda n: {"content": [{"text": "  hello there  "}]})
    out = retry_utils.call_anthropic_api("hi", max_tokens=42)
    assert out == "hello there"
    assert calls["n"] == 1
    body, model_name = calls["bodies"][0]
    assert body["max_tokens"] == 42
    assert body["messages"] == [{"role": "user", "content": "hi"}]
    assert body["model"] == retry_utils.AI_MODEL
    # No system, no temperature by default.
    assert "system" not in body
    assert "temperature" not in body
    # Success path emits no failure metric.
    assert "AnthropicAPIFailure" not in cw.metric_names()


def test_call_anthropic_api_caches_system_and_sets_temperature(monkeypatch, cw):
    calls = _patch_invoke(monkeypatch, lambda n: {"content": [{"text": "ok"}]})
    retry_utils.call_anthropic_api("hi", system="RULES", model="claude-haiku-x", temperature=0.2)
    body, model_name = calls["bodies"][0]
    assert body["model"] == "claude-haiku-x"
    assert model_name == "claude-haiku-x"
    assert body["temperature"] == 0.2
    # cache_system default True → system rendered as a cached content block.
    assert body["system"] == [{"type": "text", "text": "RULES", "cache_control": {"type": "ephemeral"}}]


# ── call_anthropic_api: retry ladder ────────────────────────────────────────


def test_retryable_clienterror_retries_then_succeeds(monkeypatch, cw, _no_sleep):
    # Fail with a retryable Bedrock code twice, then succeed on the 3rd attempt.
    def side(n):
        if n < 3:
            return _client_error("ThrottlingException")
        return {"content": [{"text": "recovered"}]}

    calls = _patch_invoke(monkeypatch, side)
    out = retry_utils.call_anthropic_api("hi")
    assert out == "recovered"
    assert calls["n"] == 3
    # Backoff used the first two configured delays, in order.
    assert _no_sleep == [5, 15]
    # Recovered → no failure metric emitted.
    assert "AnthropicAPIFailure" not in cw.metric_names()


def test_nonretryable_clienterror_raises_immediately_and_emits_failure(monkeypatch, cw, _no_sleep):
    calls = _patch_invoke(monkeypatch, lambda n: _client_error("ValidationException"))
    with pytest.raises(ClientError):
        retry_utils.call_anthropic_api("hi")
    assert calls["n"] == 1  # not retried
    assert _no_sleep == []  # no backoff
    assert "AnthropicAPIFailure" in cw.metric_names()


def test_retryable_clienterror_exhausts_attempts_then_raises(monkeypatch, cw, _no_sleep):
    calls = _patch_invoke(monkeypatch, lambda n: _client_error("ServiceUnavailableException"))
    with pytest.raises(ClientError):
        retry_utils.call_anthropic_api("hi")
    assert calls["n"] == retry_utils._MAX_ATTEMPTS == 4
    # Three backoffs between four attempts.
    assert _no_sleep == retry_utils._BACKOFF_DELAYS == [5, 15, 45]
    assert "AnthropicAPIFailure" in cw.metric_names()


def test_generic_exception_retries_then_raises(monkeypatch, cw, _no_sleep):
    calls = _patch_invoke(monkeypatch, lambda n: RuntimeError("boom"))
    with pytest.raises(RuntimeError):
        retry_utils.call_anthropic_api("hi")
    assert calls["n"] == 4
    assert "AnthropicAPIFailure" in cw.metric_names()


# ── call_anthropic_raw: dict + legacy Request shapes ────────────────────────


def test_call_anthropic_raw_dict_passthrough_returns_full_response(monkeypatch, cw):
    resp_obj = {"content": [{"text": "full"}], "usage": {"input_tokens": 3}}
    calls = _patch_invoke(monkeypatch, lambda n: resp_obj)
    body = {"model": "claude-sonnet-4-6", "messages": [{"role": "user", "content": "x"}]}
    out = retry_utils.call_anthropic_raw(body)
    assert out is resp_obj  # returns the FULL parsed response, not just text
    sent_body, model_name = calls["bodies"][0]
    assert sent_body is body
    assert model_name == "claude-sonnet-4-6"


def test_call_anthropic_raw_legacy_request_extracts_json_body(monkeypatch, cw):
    import urllib.request

    calls = _patch_invoke(monkeypatch, lambda n: {"content": [{"text": "ok"}]})
    payload = {"model": "claude-haiku-x", "messages": [{"role": "user", "content": "y"}]}
    req = urllib.request.Request("https://ignored.example/v1/messages", data=json.dumps(payload).encode("utf-8"))
    retry_utils.call_anthropic_raw(req)
    sent_body, model_name = calls["bodies"][0]
    assert sent_body == payload  # body decoded from the Request.data
    assert model_name == "claude-haiku-x"


def test_call_anthropic_raw_retries_then_emits_failure_on_exhaustion(monkeypatch, cw, _no_sleep):
    calls = _patch_invoke(monkeypatch, lambda n: _client_error("ModelTimeoutException"))
    with pytest.raises(ClientError):
        retry_utils.call_anthropic_raw({"model": "m", "messages": []})
    assert calls["n"] == 4
    assert "AnthropicAPIFailure" in cw.metric_names()


# ── token-metric emission ────────────────────────────────────────────────────


def test_emit_token_metrics_includes_cache_metrics_when_present(cw):
    retry_utils._emit_token_metrics(100, 50, cache_creation_tokens=10, cache_read_tokens=20)
    names = cw.metric_names()
    assert "AnthropicInputTokens" in names
    assert "AnthropicOutputTokens" in names
    assert "AnthropicCacheWriteTokens" in names
    assert "AnthropicCacheReadTokens" in names


def test_emit_token_metrics_omits_cache_metrics_when_zero(cw):
    retry_utils._emit_token_metrics(100, 50)
    names = cw.metric_names()
    assert "AnthropicInputTokens" in names
    assert "AnthropicCacheWriteTokens" not in names


def test_emit_metrics_never_raises_on_cloudwatch_failure(monkeypatch):
    class _BoomCW:
        def put_metric_data(self, **kwargs):
            raise RuntimeError("cw down")

    monkeypatch.setattr(retry_utils, "_cw", _BoomCW())
    # Both emitters are explicitly non-fatal — a monitoring blip must never break AI.
    retry_utils._emit_token_metrics(1, 1, 1, 1)
    retry_utils._emit_failure_metric()
