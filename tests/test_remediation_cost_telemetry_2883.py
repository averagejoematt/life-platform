"""tests/test_remediation_cost_telemetry_2883.py — #2883: attribute the remediation
agent's own Bedrock spend into the platform's AI-cost self-metric.

Context: `CostMetricDriftRatio` (cost_governor_lambda.py) divides the AWS/Bedrock
native-metric estimate (`_ai_cost`, unbuffered) by `LifePlatform/AI::EstimatedCostUSD`
summed over ALL callers (`_self_reported_cost_mtd`). The ratio stalled at ~1.4x
against the <1.15 acceptance bar (issue #2883) with a ~$20.64 residual traced to two
out-of-repo candidates: the remediation agent's own Bedrock usage, and interactive
dev-session usage (left out of scope — see remediation/agent.py's `_emit_cost_telemetry`
docstring comment). This file covers the FIRST candidate: `remediation/agent.py` runs
entirely inside the Agent SDK on Bedrock and never touches `bedrock_client.py`'s
ADR-062 chokepoint, so its spend previously counted in the numerator (native AWS/Bedrock
metrics see every InvokeModel call regardless of caller) but never in the denominator.

These tests pin the EXACT CloudWatch payload shape `_emit_cost_telemetry` emits —
Namespace, MetricName, Dimensions, Value — because `cost_governor_lambda._self_reported_cost_mtd`
reads the dimensionless `LifePlatform/AI::EstimatedCostUSD` series with NO dimension
filter (see cost_governor_lambda.py:761-779); a wrong namespace or a metric emitted
ONLY dimensioned would silently not move the drift ratio at all.
"""

import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")

sys.path.insert(0, os.path.join(_ROOT, "remediation"))

import agent  # noqa: E402


class _CWStub:
    """Captures put_metric_data calls instead of hitting the network."""

    def __init__(self, raise_on_put=None):
        self.calls = []
        self._raise = raise_on_put

    def put_metric_data(self, **kw):
        if self._raise:
            raise self._raise
        self.calls.append(kw)


def _entries(call):
    """MetricData list from a captured put_metric_data call, keyed by (MetricName, has-dims)."""
    return call["MetricData"]


def _find(entries, name, dimensioned):
    for e in entries:
        has_dims = bool(e.get("Dimensions"))
        if e["MetricName"] == name and has_dims == dimensioned:
            return e
    return None


# ── Shape: namespace, dimensionless series, LambdaFunction dimension ─────────


def test_emit_cost_telemetry_uses_lifeplatform_ai_namespace(monkeypatch):
    cw = _CWStub()
    monkeypatch.setattr(agent, "_cw", cw)
    agent._emit_cost_telemetry(1.23, None)
    assert len(cw.calls) == 1
    assert cw.calls[0]["Namespace"] == "LifePlatform/AI"


def test_emit_cost_telemetry_emits_dimensionless_estimatedcostusd(monkeypatch):
    # This is the exact series cost_governor_lambda._self_reported_cost_mtd sums
    # with NO dimension filter — the one that must move for the drift ratio to close.
    cw = _CWStub()
    monkeypatch.setattr(agent, "_cw", cw)
    agent._emit_cost_telemetry(4.5, None)
    entries = _entries(cw.calls[0])
    dimensionless = _find(entries, "EstimatedCostUSD", dimensioned=False)
    assert dimensionless is not None
    assert dimensionless["Value"] == 4.5
    assert dimensionless["Unit"] == "None"


def test_emit_cost_telemetry_also_emits_lambdafunction_dimensioned_cost(monkeypatch):
    cw = _CWStub()
    monkeypatch.setattr(agent, "_cw", cw)
    agent._emit_cost_telemetry(4.5, None)
    entries = _entries(cw.calls[0])
    dimensioned = _find(entries, "EstimatedCostUSD", dimensioned=True)
    assert dimensioned is not None
    assert dimensioned["Value"] == 4.5
    assert dimensioned["Dimensions"] == [{"Name": "LambdaFunction", "Value": "remediation-agent"}]


def test_emit_cost_telemetry_caller_dimension_matches_module_constant(monkeypatch):
    # Pin the literal so a future rename of the caller tag can't silently split the
    # per-caller table into two rows without a deliberate edit here.
    assert agent._REMEDIATION_CALLER == "remediation-agent"


# ── Skip on no/zero cost — never emit a bogus zero-cost datapoint ────────────


def test_emit_cost_telemetry_skips_when_cost_is_none(monkeypatch):
    cw = _CWStub()
    monkeypatch.setattr(agent, "_cw", cw)
    agent._emit_cost_telemetry(None, {"input_tokens": 100})
    assert cw.calls == []


def test_emit_cost_telemetry_skips_when_cost_is_zero(monkeypatch):
    cw = _CWStub()
    monkeypatch.setattr(agent, "_cw", cw)
    agent._emit_cost_telemetry(0, None)
    assert cw.calls == []


# ── Token metrics, when usage is present (dict shape AND object shape) ───────


def test_emit_cost_telemetry_includes_token_metrics_for_dict_usage(monkeypatch):
    cw = _CWStub()
    monkeypatch.setattr(agent, "_cw", cw)
    usage = {
        "input_tokens": 1000,
        "output_tokens": 200,
        "cache_read_input_tokens": 50,
        "cache_creation_input_tokens": 30,
    }
    agent._emit_cost_telemetry(0.02, usage)
    entries = _entries(cw.calls[0])
    in_tok = _find(entries, "AnthropicInputTokens", dimensioned=True)
    out_tok_dim = _find(entries, "AnthropicOutputTokens", dimensioned=True)
    out_tok_flat = _find(entries, "AnthropicOutputTokens", dimensioned=False)
    cache_r = _find(entries, "AnthropicCacheReadTokens", dimensioned=True)
    cache_w = _find(entries, "AnthropicCacheWriteTokens", dimensioned=True)
    assert in_tok["Value"] == 1000
    assert out_tok_dim["Value"] == 200
    assert out_tok_flat["Value"] == 200  # feeds ai-tokens-platform-daily-total, same as bedrock_client
    assert cache_r["Value"] == 50
    assert cache_w["Value"] == 30


class _ObjUsage:
    """Object-shape usage — the Agent SDK's ResultMessage.usage may be an object,
    not a dict (mirrors the dual-shape handling in logfire's claude_agent_sdk
    integration, which the docstring above cites as the confirmed attribute source)."""

    def __init__(self, **kw):
        self.__dict__.update(kw)


def test_emit_cost_telemetry_includes_token_metrics_for_object_usage(monkeypatch):
    cw = _CWStub()
    monkeypatch.setattr(agent, "_cw", cw)
    usage = _ObjUsage(input_tokens=500, output_tokens=75, cache_read_input_tokens=0, cache_creation_input_tokens=0)
    agent._emit_cost_telemetry(0.01, usage)
    entries = _entries(cw.calls[0])
    in_tok = _find(entries, "AnthropicInputTokens", dimensioned=True)
    assert in_tok["Value"] == 500
    # zero cache legs must NOT be emitted (mirrors bedrock_client's "if cache_read or cache_write")
    assert _find(entries, "AnthropicCacheReadTokens", dimensioned=True) is None
    assert _find(entries, "AnthropicCacheWriteTokens", dimensioned=True) is None


def test_emit_cost_telemetry_no_token_metrics_when_usage_absent(monkeypatch):
    cw = _CWStub()
    monkeypatch.setattr(agent, "_cw", cw)
    agent._emit_cost_telemetry(0.01, None)
    entries = _entries(cw.calls[0])
    assert _find(entries, "AnthropicInputTokens", dimensioned=True) is None
    # cost metrics still present
    assert _find(entries, "EstimatedCostUSD", dimensioned=False) is not None


# ── Fail-open: telemetry can never break a remediation run ───────────────────


def test_emit_cost_telemetry_is_fail_open_on_put_metric_data_error(monkeypatch, capsys):
    cw = _CWStub(raise_on_put=RuntimeError("AccessDeniedException"))
    monkeypatch.setattr(agent, "_cw", cw)
    agent._emit_cost_telemetry(3.0, None)  # must not raise
    out = capsys.readouterr().out
    assert "remediation cost telemetry emit failed" in out
    assert "[error]" in out  # ERROR not WARN — the #2974 lesson: WARN is invisible on a channel that always fails


# ── run_agent wiring: the ResultMessage's cost/usage actually reach the emit ──


def test_run_agent_extracts_cost_and_usage_from_result_message(monkeypatch):
    """Simulate the Agent SDK without requiring it installed: inject a fake
    claude_agent_sdk module (run_agent imports it lazily inside the function) whose
    query() yields one AssistantMessage-like chunk then a ResultMessage-like object
    carrying total_cost_usd/usage, and assert _emit_cost_telemetry receives them."""
    import asyncio
    import types

    class _FakeContentBlock:
        def __init__(self, text):
            self.text = text

    class _FakeAssistantMessage:
        def __init__(self, text):
            self.content = [_FakeContentBlock(text)]

    class _FakeResultMessage:
        def __init__(self, result, total_cost_usd, usage):
            self.is_error = False
            self.result = result
            self.total_cost_usd = total_cost_usd
            self.usage = usage

    async def _fake_query(prompt, options):
        yield _FakeAssistantMessage("investigating...")
        yield _FakeResultMessage("done", 0.0456, {"input_tokens": 2000, "output_tokens": 300})

    class _AsyncGenWrapper:
        """query() in the real SDK returns an async generator with an aclose()
        the caller awaits explicitly — replicate that shape exactly."""

        def __init__(self, gen):
            self._gen = gen

        def __aiter__(self):
            return self

        async def __anext__(self):
            return await self._gen.__anext__()

        async def aclose(self):
            await self._gen.aclose()

    fake_module = types.SimpleNamespace(
        query=lambda prompt, options: _AsyncGenWrapper(_fake_query(prompt, options)),
        ClaudeAgentOptions=lambda **kw: kw,
    )
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", fake_module)

    captured = {}

    def _fake_emit(cost_usd, usage):
        captured["cost_usd"] = cost_usd
        captured["usage"] = usage

    monkeypatch.setattr(agent, "_emit_cost_telemetry", _fake_emit)

    text = asyncio.run(agent.run_agent("do the thing"))

    assert "investigating..." in text
    assert captured["cost_usd"] == 0.0456
    assert captured["usage"] == {"input_tokens": 2000, "output_tokens": 300}


def test_run_agent_still_emits_when_result_message_has_no_cost(monkeypatch):
    """Older/degraded ResultMessage shapes without total_cost_usd must not crash —
    _emit_cost_telemetry(None, ...) is called and self no-ops (covered above)."""
    import asyncio
    import types

    class _FakeResultMessage:
        def __init__(self):
            self.is_error = False
            self.result = "done"
            # no total_cost_usd / usage attributes at all

    async def _fake_query(prompt, options):
        yield _FakeResultMessage()

    class _AsyncGenWrapper:
        def __init__(self, gen):
            self._gen = gen

        def __aiter__(self):
            return self

        async def __anext__(self):
            return await self._gen.__anext__()

        async def aclose(self):
            await self._gen.aclose()

    fake_module = types.SimpleNamespace(
        query=lambda prompt, options: _AsyncGenWrapper(_fake_query(prompt, options)),
        ClaudeAgentOptions=lambda **kw: kw,
    )
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", fake_module)

    captured = {}
    monkeypatch.setattr(agent, "_emit_cost_telemetry", lambda c, u: captured.update(cost_usd=c, usage=u))

    text = asyncio.run(agent.run_agent("do the thing"))
    assert text == "done"
    assert captured["cost_usd"] is None
    assert captured["usage"] is None


# ── IAM: the grant this code depends on is staged in the declarative source ──


def test_remediation_role_grants_scoped_ai_cost_putmetricdata():
    # Without this grant, _emit_cost_telemetry's put_metric_data call is a live
    # AccessDenied — the code ships inert until the attended `put-role-policy`
    # apply documented in infra/iam/README.md runs. Guard the staged grant exists
    # with the correct least-privilege shape (mirrors #2974's diagnosis-role grant).
    with open(os.path.join(_ROOT, "infra", "iam", "github-actions-remediation-role.permissions.json")) as f:
        doc = json.load(f)
    stmts = doc.get("Statement", [])
    match = [s for s in stmts if s.get("Sid") == "AiCostTelemetry"]
    assert len(match) == 1, "expected exactly one AiCostTelemetry statement"
    stmt = match[0]
    assert stmt["Effect"] == "Allow"
    assert stmt["Action"] == "cloudwatch:PutMetricData"
    assert stmt["Condition"] == {"StringEquals": {"cloudwatch:namespace": "LifePlatform/AI"}}
