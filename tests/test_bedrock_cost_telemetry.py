"""
tests/test_bedrock_cost_telemetry.py — G1: chokepoint AI cost metering.

Covers the telemetry added to bedrock_client (ADR-062 chokepoint), which makes
every Claude call attributable per-feature and feeds the daily-spend anomaly
alarm (G2):
  - estimate_cost_usd: per-model pricing, cache tokens, unknown→most-expensive
  - _emit_usage_metrics: emits per-LambdaFunction tokens + dimensionless
    OutputTokens (platform-total alarm) + EstimatedCostUSD per-feature AND
    dimensionless (G2 alarm); cache metrics only when present
  - strictly fail-open: a CloudWatch error never propagates to the AI caller
  - invoke() meters on the return path and still returns the parsed response

Run:  python3 -m pytest tests/test_bedrock_cost_telemetry.py -v
"""

import json
import os
import sys
import types
from unittest.mock import MagicMock

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))

import bedrock_client as bc  # noqa: E402


# ── estimate_cost_usd (pure) ─────────────────────────────────────────────────


def test_cost_haiku_in_out():
    # 1M in @ $1 + 1M out @ $5 = $6.00
    usage = {"input_tokens": 1_000_000, "output_tokens": 1_000_000}
    assert abs(bc.estimate_cost_usd(usage, "us.anthropic.claude-haiku-4-5-20251001-v1:0") - 6.0) < 1e-9


def test_cost_sonnet_in_out():
    # 1M in @ $3 + 1M out @ $15 = $18.00
    usage = {"input_tokens": 1_000_000, "output_tokens": 1_000_000}
    assert abs(bc.estimate_cost_usd(usage, "us.anthropic.claude-sonnet-4-6") - 18.0) < 1e-9


def test_cost_includes_cache_tokens():
    usage = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_input_tokens": 1_000_000,  # haiku cache_read $0.10
        "cache_creation_input_tokens": 1_000_000,  # haiku cache_write $1.25
    }
    assert abs(bc.estimate_cost_usd(usage, "haiku") - 1.35) < 1e-9


def test_unknown_model_prices_as_most_expensive():
    # An unmapped model must not under-report — defaults to the fable tier.
    usage = {"input_tokens": 1_000_000, "output_tokens": 0}
    assert abs(bc.estimate_cost_usd(usage, "claude-from-the-future") - 10.0) < 1e-9


def test_zero_usage_is_zero_cost():
    assert bc.estimate_cost_usd({}, "haiku") == 0.0


# ── _emit_usage_metrics ──────────────────────────────────────────────────────


def _capture_emit(monkeypatch, usage, model_id="us.anthropic.claude-haiku-4-5-20251001-v1:0"):
    fake = MagicMock()
    monkeypatch.setattr(bc, "_cw", lambda: fake)
    bc._emit_usage_metrics(usage, model_id)
    if not fake.put_metric_data.called:
        return None
    return fake.put_metric_data.call_args.kwargs["MetricData"]


def _names_with_dims(md):
    """Set of (MetricName, has_LambdaFunction_dim) for assertions."""
    out = []
    for m in md:
        has_fn = any(d.get("Name") == "LambdaFunction" for d in m.get("Dimensions", []))
        out.append((m["MetricName"], has_fn))
    return out


def test_emit_includes_dimensionless_cost_for_g2_alarm(monkeypatch):
    md = _capture_emit(monkeypatch, {"input_tokens": 100, "output_tokens": 50})
    # The G2 alarm watches a dimensionless EstimatedCostUSD.
    assert ("EstimatedCostUSD", False) in _names_with_dims(md)
    # And a per-feature copy for attribution.
    assert ("EstimatedCostUSD", True) in _names_with_dims(md)


def test_emit_includes_dimensionless_output_tokens_for_platform_alarm(monkeypatch):
    md = _capture_emit(monkeypatch, {"input_tokens": 100, "output_tokens": 50})
    # ai-tokens-platform-daily-total watches dimensionless AnthropicOutputTokens.
    assert ("AnthropicOutputTokens", False) in _names_with_dims(md)
    assert ("AnthropicOutputTokens", True) in _names_with_dims(md)


def test_emit_omits_cache_metrics_when_absent(monkeypatch):
    md = _capture_emit(monkeypatch, {"input_tokens": 100, "output_tokens": 50})
    names = {m["MetricName"] for m in md}
    assert "AnthropicCacheReadTokens" not in names
    assert "AnthropicCacheWriteTokens" not in names


def test_emit_includes_cache_metrics_when_present(monkeypatch):
    md = _capture_emit(
        monkeypatch,
        {"input_tokens": 100, "output_tokens": 50, "cache_read_input_tokens": 10, "cache_creation_input_tokens": 5},
    )
    names = {m["MetricName"] for m in md}
    assert "AnthropicCacheReadTokens" in names and "AnthropicCacheWriteTokens" in names


def test_emit_noop_on_zero_usage(monkeypatch):
    # No tokens → no CloudWatch call at all (don't pay to emit nothing).
    assert _capture_emit(monkeypatch, {}) is None
    assert _capture_emit(monkeypatch, {"input_tokens": 0, "output_tokens": 0}) is None


def test_emit_is_fail_open(monkeypatch):
    # A CloudWatch failure must never surface to the AI caller.
    boom = MagicMock()
    boom.put_metric_data.side_effect = RuntimeError("throttled")
    monkeypatch.setattr(bc, "_cw", lambda: boom)
    bc._emit_usage_metrics({"input_tokens": 1, "output_tokens": 1}, "haiku")  # must not raise


# ── invoke() integration ─────────────────────────────────────────────────────


def _stub_budget(monkeypatch):
    stub = types.ModuleType("budget_guard")
    stub.BudgetExceeded = RuntimeError
    stub.current_tier = lambda: 0
    monkeypatch.setitem(sys.modules, "budget_guard", stub)


def test_invoke_meters_on_return_path(monkeypatch):
    _stub_budget(monkeypatch)
    fake_client = MagicMock()
    payload = {"content": [{"text": "hi"}], "usage": {"input_tokens": 100, "output_tokens": 20}}
    fake_client.invoke_model.return_value = {"body": MagicMock(read=lambda: json.dumps(payload).encode())}
    monkeypatch.setattr(bc, "_client", lambda: fake_client)
    fake_cw = MagicMock()
    monkeypatch.setattr(bc, "_cw", lambda: fake_cw)

    out = bc.invoke({"messages": [], "max_tokens": 10}, model_name="claude-haiku-4-5-20251001")
    assert out == payload  # response returned unchanged
    assert fake_cw.put_metric_data.called  # and metered


def test_invoke_returns_even_if_telemetry_breaks(monkeypatch):
    _stub_budget(monkeypatch)
    fake_client = MagicMock()
    payload = {"content": [{"text": "hi"}], "usage": {"input_tokens": 100, "output_tokens": 20}}
    fake_client.invoke_model.return_value = {"body": MagicMock(read=lambda: json.dumps(payload).encode())}
    monkeypatch.setattr(bc, "_client", lambda: fake_client)
    boom = MagicMock()
    boom.put_metric_data.side_effect = RuntimeError("cw down")
    monkeypatch.setattr(bc, "_cw", lambda: boom)

    assert bc.invoke({"messages": [], "max_tokens": 10}, model_name="claude-haiku-4-5-20251001") == payload
