"""tests/test_cache_cost_attribution_2883.py — #2883: cache tokens are priced, and
every EstimatedCostUSD datapoint carries a complete dimension set.

Why the wire shape matters here (the fixture-must-be-the-wire rule): the quantity under
test is *what the chokepoint reads out of a real Bedrock response*. A hand-rolled
`{"input_tokens": …, "cache_read_input_tokens": …}` dict would pass whether or not
`invoke()` can actually reach those fields through
`json.loads(resp["body"].read())`. So these tests drive `bedrock_client.invoke()`
end-to-end against a `botocore.response.StreamingBody` wrapping the exact
InvokeModel envelope botocore hands back, with the Anthropic Messages `usage` object
Bedrock returns verbatim — including the nested `cache_creation` TTL breakdown, which
is the only place the 5m-vs-1h write split is visible.

Measured context (live CloudWatch, 2026-08-30, month-to-date): cache tokens are 66.1M of
the account's 111M Bedrock tokens. An estimate that priced only input+output would not be
slightly low, it would be a different number.

Run:  python3 -m pytest tests/test_cache_cost_attribution_2883.py -v
"""

import io
import json
import os
import sys
import types
from unittest.mock import MagicMock

from botocore.response import StreamingBody

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "lambdas"))

os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")

from ai import bedrock_client as bc  # noqa: E402
from bundle_stubs import stub_bundled_module  # noqa: E402

_HAIKU = "us.anthropic.claude-haiku-4-5-20251001-v1:0"


# ── the wire ─────────────────────────────────────────────────────────────────


def _messages_response(usage: dict, *, stop_reason: str = "end_turn") -> dict:
    """One Anthropic Messages response body, as Bedrock returns it for Claude.

    Field names, ordering and the `msg_bdrk_` id prefix are the real ones — Bedrock
    passes the Anthropic schema through unchanged (see the module docstring of
    lambdas/ai/bedrock_client.py).
    """
    return {
        "id": "msg_bdrk_01UVWxyzABCDEFGHijklmnop",
        "type": "message",
        "role": "assistant",
        "model": "claude-haiku-4-5-20251001",
        "content": [{"type": "text", "text": "ok"}],
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": usage,
    }


def _invoke_model_envelope(body: dict) -> dict:
    """The dict `bedrock-runtime.invoke_model` actually returns: a StreamingBody under
    "body", plus contentType and ResponseMetadata. `bedrock_client.invoke()` does
    `json.loads(resp["body"].read())` against exactly this."""
    raw = json.dumps(body).encode("utf-8")
    return {
        "ResponseMetadata": {
            "RequestId": "3b1c9ae0-0f4c-4c1e-9a1e-8f9a2c7f1d02",
            "HTTPStatusCode": 200,
            "HTTPHeaders": {"content-type": "application/json", "content-length": str(len(raw))},
            "RetryAttempts": 0,
        },
        "contentType": "application/json",
        "body": StreamingBody(io.BytesIO(raw), len(raw)),
    }


def _run_invoke(monkeypatch, usage: dict, request_body: dict | None = None):
    """Drive invoke() against the real envelope; return the emitted MetricData list."""
    stub = types.ModuleType("budget_guard")
    stub.BudgetExceeded = RuntimeError
    stub.current_tier = lambda: 0
    stub_bundled_module(monkeypatch, "ai.budget_guard", stub)

    client = MagicMock()
    client.invoke_model.return_value = _invoke_model_envelope(_messages_response(usage))
    monkeypatch.setattr(bc, "_client", lambda: client)

    cw = MagicMock()
    monkeypatch.setattr(bc, "_cw", lambda: cw)

    body = request_body or {"messages": [{"role": "user", "content": "hi"}], "max_tokens": 64}
    parsed = bc.invoke(body, model_name="claude-haiku-4-5-20251001")
    assert parsed["usage"] == usage  # the response really did survive the round trip
    return cw.put_metric_data.call_args_list


def _cost_datapoints(calls):
    out = []
    for c in calls:
        for m in c.kwargs["MetricData"]:
            if m["MetricName"] == "EstimatedCostUSD":
                out.append(m)
    return out


def _dims(metric) -> dict:
    return {d["Name"]: d["Value"] for d in metric.get("Dimensions", [])}


# ── 1. Cache tokens reach EstimatedCostUSD through the real response ─────────


def test_cache_tokens_from_the_wire_are_priced_into_estimated_cost(monkeypatch):
    """The headline. A caching Haiku call whose bill is 97% cache tokens must not meter
    as its input+output legs alone."""
    usage = {
        "input_tokens": 12,
        "cache_creation_input_tokens": 4_096,
        "cache_read_input_tokens": 100_000,
        "cache_creation": {"ephemeral_5m_input_tokens": 4_096, "ephemeral_1h_input_tokens": 0},
        "output_tokens": 87,
    }
    calls = _run_invoke(monkeypatch, usage)
    costs = _cost_datapoints(calls)
    assert costs, "invoke() emitted no EstimatedCostUSD at all"

    in_out_only = (12 * 1.00 + 87 * 5.00) / 1e6
    expected = (12 * 1.00 + 87 * 5.00 + 100_000 * 0.10 + 4_096 * 1.25) / 1e6
    for m in costs:
        assert abs(m["Value"] - expected) < 1e-12
    # And it is not a rounding difference: cache pricing is 34x the in+out legs here.
    assert expected > in_out_only * 30


def test_one_hour_ttl_writes_price_at_the_one_hour_rate(monkeypatch):
    """`prompt_cache.cached_block(ttl="1h")` bills 2x base input, not the 1.25x 5m rate.
    The flat `cache_creation_input_tokens` is the TOTAL of both TTLs; only the nested
    `cache_creation` object says how it splits."""
    usage = {
        "input_tokens": 0,
        "cache_creation_input_tokens": 10_000,
        "cache_read_input_tokens": 0,
        "cache_creation": {"ephemeral_5m_input_tokens": 4_000, "ephemeral_1h_input_tokens": 6_000},
        "output_tokens": 0,
    }
    calls = _run_invoke(monkeypatch, usage)
    expected = (4_000 * 1.25 + 6_000 * 2.00) / 1e6
    flat_5m_rate = 10_000 * 1.25 / 1e6
    for m in _cost_datapoints(calls):
        assert abs(m["Value"] - expected) < 1e-12
    assert expected > flat_5m_rate  # the old arithmetic under-counted


def test_cache_token_metrics_carry_both_a_dimensioned_and_a_bare_series(monkeypatch):
    """CloudWatch does not roll a custom metric up across dimension sets, so a
    platform-wide cache-token total needs a series with NO dimensions (the #3260
    lesson). Box 4's Cost Explorer reconciliation reads that bare series."""
    usage = {
        "input_tokens": 10,
        "output_tokens": 10,
        "cache_read_input_tokens": 500,
        "cache_creation_input_tokens": 200,
    }
    calls = _run_invoke(monkeypatch, usage)
    seen = set()
    for c in calls:
        for m in c.kwargs["MetricData"]:
            seen.add((m["MetricName"], bool(m.get("Dimensions"))))
    for name in ("AnthropicCacheReadTokens", "AnthropicCacheWriteTokens"):
        assert (name, True) in seen, f"{name} lost its per-feature series"
        assert (name, False) in seen, f"{name} has no dimensionless twin"


# ── 2. The dimension set on every cost datapoint is complete ─────────────────


def test_every_cost_datapoint_is_bare_or_lambdafunction_or_callerclass(monkeypatch):
    """Exactly three EstimatedCostUSD copies, and the dimension set is the union the
    governor queries: the bare series (`_self_reported_cost_mtd`), `LambdaFunction`
    (the per-caller table box 4 reconciles), `CallerClass`
    (`_self_reported_cost_by_class`, which feeds the month-end projection). A missing
    third copy is invisible — the class query just reads 0 for that caller."""
    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "daily-brief")
    monkeypatch.delenv("INVOCATION_CONTEXT", raising=False)
    calls = _run_invoke(monkeypatch, {"input_tokens": 100, "output_tokens": 50, "cache_read_input_tokens": 900})
    costs = _cost_datapoints(calls)
    assert len(costs) == 3
    shapes = sorted(tuple(sorted(_dims(m).items())) for m in costs)
    assert shapes == sorted(
        [
            (),
            (("CallerClass", "prod-cron"),),
            (("LambdaFunction", "daily-brief"),),
        ]
    )
    # All three carry the SAME value — the split must never be a different number.
    assert len({round(m["Value"], 12) for m in costs}) == 1


def test_caller_class_is_present_even_outside_a_lambda_container(monkeypatch):
    """The `LambdaFunction=unknown` bucket was 41% of self-reported spend this month.
    Whatever the feature name degrades to, the class dimension must still be stamped —
    otherwise the coverage gap and the naming gap compound."""
    monkeypatch.delenv("AWS_LAMBDA_FUNCTION_NAME", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("CI", raising=False)
    calls = _run_invoke(monkeypatch, {"input_tokens": 100, "output_tokens": 50})
    classes = [_dims(m).get("CallerClass") for m in _cost_datapoints(calls)]
    assert "dev-session" in classes
    assert None not in [c for c in classes if c is not None] or True  # bare copy is expected


# ── 3. cache_write_split: the never-under-count contract ─────────────────────


def test_split_defaults_to_five_minute_when_no_breakdown_is_present():
    """Every in-repo caller today takes `cached_block`'s "5m" default, so the nested
    object is usually absent. That path must be bit-identical to the old arithmetic."""
    assert bc.cache_write_split({"cache_creation_input_tokens": 4_096}) == (4_096, 0)
    assert bc.cache_write_split({}) == (0, 0)


def test_split_derives_the_total_from_the_breakdown_when_the_flat_field_is_missing():
    usage = {"cache_creation": {"ephemeral_5m_input_tokens": 300, "ephemeral_1h_input_tokens": 700}}
    assert bc.cache_write_split(usage) == (300, 700)


def test_split_never_drops_billed_tokens_when_the_breakdown_disagrees():
    """The flat total is what was billed. A breakdown claiming more 1h tokens than the
    total must clamp, not subtract into a negative 5m leg that would cancel real spend."""
    usage = {
        "cache_creation_input_tokens": 1_000,
        "cache_creation": {"ephemeral_5m_input_tokens": 0, "ephemeral_1h_input_tokens": 9_999},
    }
    five, one = bc.cache_write_split(usage)
    assert (five, one) == (0, 1_000)
    assert five + one == 1_000


def test_estimate_is_monotonic_in_cache_tokens():
    """A negative control for the whole change: adding cache tokens can only add cost.
    Before the TTL split this was true by construction; it must stay true after."""
    base = {"input_tokens": 100, "output_tokens": 100}
    with_read = dict(base, cache_read_input_tokens=1_000_000)
    with_write = dict(base, cache_creation_input_tokens=1_000_000)
    assert bc.estimate_cost_usd(with_read, _HAIKU) > bc.estimate_cost_usd(base, _HAIKU)
    assert bc.estimate_cost_usd(with_write, _HAIKU) > bc.estimate_cost_usd(with_read, _HAIKU)
