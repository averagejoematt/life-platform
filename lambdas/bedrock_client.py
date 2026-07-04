"""
bedrock_client.py — AWS Bedrock inference primitive for Claude models.

Migrated from the direct Anthropic API on 2026-05-27 (ADR-062). Replaces
urllib POSTs to api.anthropic.com with boto3 bedrock-runtime invoke_model,
so Claude inference bills through the AWS account instead of prepaid
Anthropic credits (no more "credit balance too low" cliff that takes every
AI feature down at once).

Key facts:
  • Auth is IAM — no API key. Lambda roles need bedrock:InvokeModel on the
    inference-profile ARN + the underlying foundation-model ARN.
  • On-demand 4.x Claude models REQUIRE an inference profile (the `us.`
    prefix). Bare `anthropic.claude-*` IDs reject with
    "on-demand throughput isn't supported".
  • The InvokeModel response for Claude is byte-identical to the direct
    Anthropic Messages API (content[], usage{}, stop_reason, …) so all
    downstream parsing is unchanged.
  • Prompt caching is GA on Bedrock for supported Claude models via the
    same cache_control blocks used on the direct API — no beta header.

This module is part of the shared Lambda layer.
"""

import json
import os

import boto3
from botocore.config import Config

# ── Model-name → Bedrock inference-profile ID ──────────────────────────────
# The platform's AI_MODEL / AI_MODEL_HAIKU env vars hold Anthropic-style names
# (e.g. "claude-sonnet-4-6"). Map them to the us-region cross-region inference
# profiles that Bedrock requires for on-demand throughput.
_MODEL_MAP = {
    "claude-fable-5": "us.anthropic.claude-fable-5",
    "claude-opus-4-8": "us.anthropic.claude-opus-4-8",
    "claude-sonnet-4-6": "us.anthropic.claude-sonnet-4-6",
    "claude-sonnet-4-5-20250929": "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
    "claude-haiku-4-5-20251001": "us.anthropic.claude-haiku-4-5-20251001-v1:0",
    "claude-opus-4-7": "us.anthropic.claude-opus-4-7",
    "claude-opus-4-6": "us.anthropic.claude-opus-4-6-v1",
    "claude-3-5-haiku-20241022": "us.anthropic.claude-3-5-haiku-20241022-v1:0",
}

# Fable 5 / Opus 4.7+ removed sampling params (temperature/top_p/top_k → 400);
# Fable additionally rejects an explicit thinking disable. Scrub at this single
# chokepoint so callers (retry_utils, ai_calls) stay model-agnostic.
_ADAPTIVE_SURFACE_MARKERS = ("fable", "opus-4-7", "opus-4-8")

# Fallback if an unmapped model name shows up — Haiku 4.5 (cheapest current).
_DEFAULT_PROFILE = "us.anthropic.claude-haiku-4-5-20251001-v1:0"

BEDROCK_REGION = os.environ.get("BEDROCK_REGION", "us-west-2")

_BEDROCK = None

# ── Cost telemetry (G1) ─────────────────────────────────────────────────────
# ADR-062 makes invoke() the single chokepoint for every Claude call, so it is
# the one correct place to meter token usage + spend. Metering here (rather than
# only in ai_calls / retry_utils, which cover just the daily-brief path) makes
# per-feature AI cost attributable in one CloudWatch query — site-api-ai,
# partner, the podcast, coach reflections, the canary etc. were previously
# invisible — and feeds the daily-spend anomaly alarm (G2). Strictly fail-open:
# a telemetry error must never surface to an AI caller.
_CW_NAMESPACE = "LifePlatform/AI"
_LAMBDA_NAME = os.environ.get("AWS_LAMBDA_FUNCTION_NAME", "unknown")
# COST-05: "prod" for scheduled production triggers; set to "dev" on the MCP Lambda
# so that interactive debugging sessions are attributable separately in CloudWatch
# (June's breach was dev sessions driving $4-5 spike days on a ~$1.50 baseline).
# Default to "prod" so untagged scheduled lambdas don't inflate the dev bucket.
_INVOCATION_CONTEXT = os.environ.get("INVOCATION_CONTEXT", "prod")
# $/1M tokens, keyed by a substring of the resolved model id. Mirrors
# cost_governor._PRICES; an unmapped model prices as the most expensive tier so
# a new/unknown model can never under-report spend.
_PRICES = {
    "fable": {"in": 10.00, "out": 50.00, "cache_read": 1.00, "cache_write": 12.50},
    "opus": {"in": 5.00, "out": 25.00, "cache_read": 0.50, "cache_write": 6.25},
    "sonnet": {"in": 3.00, "out": 15.00, "cache_read": 0.30, "cache_write": 3.75},
    "haiku": {"in": 1.00, "out": 5.00, "cache_read": 0.10, "cache_write": 1.25},
}
_DEFAULT_PRICE = _PRICES["fable"]
_CW = None


def _cw():
    """Lazy-init a CloudWatch client for metric emission (separate from the
    bedrock-runtime client; only created if/when telemetry actually runs)."""
    global _CW
    if _CW is None:
        _CW = boto3.client("cloudwatch", region_name=BEDROCK_REGION)
    return _CW


def _price_for(model_id: str) -> dict:
    mid = (model_id or "").lower()
    for key, price in _PRICES.items():
        if key in mid:
            return price
    return _DEFAULT_PRICE


def estimate_cost_usd(usage: dict, model_id: str) -> float:
    """Estimated USD for one Claude call from its usage dict + resolved model.
    Pure — no I/O — so it is unit-testable without AWS."""
    p = _price_for(model_id)
    return (
        int(usage.get("input_tokens", 0) or 0) * p["in"]
        + int(usage.get("output_tokens", 0) or 0) * p["out"]
        + int(usage.get("cache_read_input_tokens", 0) or 0) * p["cache_read"]
        + int(usage.get("cache_creation_input_tokens", 0) or 0) * p["cache_write"]
    ) / 1_000_000.0


def _emit_usage_metrics(usage: dict, model_id: str) -> None:
    """Meter token usage + estimated spend at the inference chokepoint (G1).

    Emits per-LambdaFunction token metrics (per-feature attribution) plus a
    dimensionless AnthropicOutputTokens (feeds the existing platform-total
    alarm) and EstimatedCostUSD both per-feature and dimensionless (the latter
    feeds the daily-spend anomaly alarm, G2). Fully fail-open."""
    try:
        in_tok = int(usage.get("input_tokens", 0) or 0)
        out_tok = int(usage.get("output_tokens", 0) or 0)
        cache_read = int(usage.get("cache_read_input_tokens", 0) or 0)
        cache_write = int(usage.get("cache_creation_input_tokens", 0) or 0)
        if not (in_tok or out_tok or cache_read or cache_write):
            return
        cost = estimate_cost_usd(usage, model_id)
        fn_dim = [{"Name": "LambdaFunction", "Value": _LAMBDA_NAME}]
        ctx_dim = [{"Name": "Context", "Value": _INVOCATION_CONTEXT}]
        md = [
            {"MetricName": "AnthropicInputTokens", "Dimensions": fn_dim, "Value": in_tok, "Unit": "Count"},
            {"MetricName": "AnthropicOutputTokens", "Dimensions": fn_dim, "Value": out_tok, "Unit": "Count"},
            # Dimensionless output-token total — feeds ai-tokens-platform-daily-total.
            {"MetricName": "AnthropicOutputTokens", "Value": out_tok, "Unit": "Count"},
            # Estimated spend: per-feature attribution + a dimensionless aggregate (G2 alarm).
            {"MetricName": "EstimatedCostUSD", "Dimensions": fn_dim, "Value": cost, "Unit": "None"},
            {"MetricName": "EstimatedCostUSD", "Value": cost, "Unit": "None"},
            # COST-05: Context-tagged spend — enables prod vs dev attribution in CloudWatch.
            {"MetricName": "EstimatedCostUSD", "Dimensions": ctx_dim, "Value": cost, "Unit": "None"},
        ]
        if cache_read or cache_write:
            md.append({"MetricName": "AnthropicCacheReadTokens", "Dimensions": fn_dim, "Value": cache_read, "Unit": "Count"})
            md.append({"MetricName": "AnthropicCacheWriteTokens", "Dimensions": fn_dim, "Value": cache_write, "Unit": "Count"})
        _cw().put_metric_data(Namespace=_CW_NAMESPACE, MetricData=md)
    except Exception as e:  # never break an AI call on telemetry
        print(f"[WARN] bedrock cost telemetry emit failed (non-fatal): {e}")


def _client():
    """Lazy-init bedrock-runtime client. Read timeout generous for long
    Sonnet narrative passes; botocore adaptive retries on throttling."""
    global _BEDROCK
    if _BEDROCK is None:
        _BEDROCK = boto3.client(
            "bedrock-runtime",
            region_name=BEDROCK_REGION,
            config=Config(
                # 60s was too short for long Sonnet narrative passes (4k-token
                # podcast scripts) → intermittent ReadTimeout. 180s gives headroom.
                read_timeout=180,
                connect_timeout=10,
                retries={"max_attempts": 2, "mode": "adaptive"},
            ),
        )
    return _BEDROCK


def resolve_model_id(model_name: str | None) -> str:
    """Map an Anthropic model name to a Bedrock inference-profile ID.

    Pass-through if already a profile id (us.* / global.*) or a full ARN.
    """
    if not model_name:
        return _DEFAULT_PROFILE
    if model_name.startswith(("us.", "global.", "arn:")):
        return model_name
    return _MODEL_MAP.get(model_name, _DEFAULT_PROFILE)


def invoke(body: dict, model_name: str | None = None) -> dict:
    """Invoke a Claude model on Bedrock.

    Args:
        body: an Anthropic Messages dict — {messages, max_tokens, system?}.
              A top-level "model" key (Anthropic-style name) is honored for
              routing if model_name isn't passed, then stripped from the
              Bedrock request body.
        model_name: explicit model name/profile override.

    Returns the parsed JSON response — identical shape to the direct
    Anthropic Messages API (content[], usage{}, role, stop_reason, …).

    Raises botocore.exceptions.ClientError on Bedrock errors (ThrottlingException,
    ModelTimeoutException, ServiceUnavailableException, AccessDeniedException, …)
    — callers handle retry/backoff.
    """
    # COST-05: Shadow mode — exercises the pipeline without model calls (for debugging
    # coach regeneration without burning budget). Set BEDROCK_SHADOW_MODE=1 to enable.
    if os.environ.get("BEDROCK_SHADOW_MODE"):
        return {
            "id": "shadow-stub",
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": "[SHADOW MODE — Bedrock call suppressed; BEDROCK_SHADOW_MODE=1]"}],
            "model": "shadow",
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {"input_tokens": 0, "output_tokens": 0},
        }

    # Budget guardrail (Tier-3 hard stop): the single backstop every AI call
    # routes through. If the monthly $75 ceiling is reached, refuse — callers
    # catch this and degrade (coaches → fallback brief, ai_calls → [AI_UNAVAILABLE]).
    # Fail-open: if budget_guard is unavailable, proceed (never break AI on a blip).
    try:
        from budget_guard import BudgetExceeded, current_tier

        if current_tier() >= 3:
            raise BudgetExceeded("AI paused — monthly $75 budget ceiling reached (tier 3). " "Auto-resumes at month rollover.")
    except ImportError:
        pass

    model_id = resolve_model_id(model_name or body.get("model"))
    bedrock_body = {k: v for k, v in body.items() if k != "model"}
    if any(marker in model_id.lower() for marker in _ADAPTIVE_SURFACE_MARKERS):
        for param in ("temperature", "top_p", "top_k"):
            bedrock_body.pop(param, None)
        if "fable" in model_id.lower() and (bedrock_body.get("thinking") or {}).get("type") == "disabled":
            bedrock_body.pop("thinking", None)
    # Bedrock requires this exact version string for the Anthropic schema.
    bedrock_body["anthropic_version"] = "bedrock-2023-05-31"

    resp = _client().invoke_model(
        modelId=model_id,
        body=json.dumps(bedrock_body),
        contentType="application/json",
        accept="application/json",
    )
    parsed = json.loads(resp["body"].read())
    # G1: meter token usage + estimated spend at the single chokepoint. Fail-open.
    _emit_usage_metrics(parsed.get("usage") or {}, model_id)
    return parsed
