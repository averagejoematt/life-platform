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


def _client():
    """Lazy-init bedrock-runtime client. Read timeout generous for long
    Sonnet narrative passes; botocore adaptive retries on throttling."""
    global _BEDROCK
    if _BEDROCK is None:
        _BEDROCK = boto3.client(
            "bedrock-runtime",
            region_name=BEDROCK_REGION,
            config=Config(
                read_timeout=60,
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
    return json.loads(resp["body"].read())
