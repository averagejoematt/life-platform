"""
ai_transport.py — the Bedrock transport layer for the daily-brief AI path.

Extracted from `ai/ai_calls.py` (#3082, the #1400/#1654/#2604 facade + cohesive-
sibling shape). `ai_calls` was at 2396/2396 on the #1665 module-size ratchet — zero
headroom — so the four-line #2893 re-bill fix that `common/retry_utils` got in #3081
could not land there without raising a baseline, which the ratchet's standing rule
forbids. This module pays for those lines instead.

The seam is a real one, not a line-count convenience: everything here is about
*getting bytes to and from Bedrock* — the model ids, the retry ladder, the
CloudWatch failure series, the system-block cache wrapper, the AI-3 output
validator hook. Nothing here knows what a coach, a brief, or a grade is. The
~2,200 lines left in `ai_calls` are prompt construction and coaching pipeline,
and they reach Bedrock through exactly one door: `call_anthropic`.

`ai_calls` re-exports every public name below, so `from ai.ai_calls import
call_anthropic` and `monkeypatch.setattr(ai_calls, "call_anthropic", ...)` are
unchanged for every caller and every test.

Two behaviours are pinned by tests and must not regress:

  * **A response you have already paid for is never retried** (#2893). The
    destructure of `resp["content"][0]["text"]` used to sit INSIDE the retry
    `try`, so an empty `content` list — the exact shape of a `max_tokens` stop
    with no emitted text — raised IndexError, was swallowed by the generic
    `except Exception`, and re-invoked the model up to 4×: four billed calls,
    zero usable output, logged at WARN with Errors flat. The parse now happens
    after the loop, via `bedrock_client.first_text`.
  * **A budget stop is a refusal, not a transport error** (#3084). At tier 3 the
    guard refuses before `invoke_model`, so nothing is billed — but the generic
    `except Exception` treated `BudgetExceeded` as retryable and slept
    5+15+45 = 65s per call before returning the sentinel. The daily brief makes
    ~62 AI calls, so a hard budget stop became ~67 minutes of accumulated sleeps
    against a Lambda timeout, exactly when the platform is already in trouble.
    It now returns immediately with a budget-shaped log line.
"""

import os
import time  # noqa: F401 — the retry sleep moved to bedrock_client (#4279); kept so `ai_transport.time` stays patchable
from typing import Any, Optional, Union

import boto3

from ai.bedrock_client import INVOKE_RETRY_BASE_DELAYS, RETRYABLE_BEDROCK_CODES

# AI model constants — read from env so model can be updated without redeployment
AI_MODEL = os.environ.get("AI_MODEL", "claude-sonnet-4-6")
AI_MODEL_HAIKU = os.environ.get("AI_MODEL_HAIKU", "claude-haiku-4-5-20251001")

# CloudWatch client for token usage + failure metrics (P1.8/P1.9)
_cw = boto3.client("cloudwatch", region_name=os.environ.get("AWS_REGION", "us-west-2"))
_LAMBDA_NAME = os.environ.get("AWS_LAMBDA_FUNCTION_NAME", "unknown")
_CW_NAMESPACE = "LifePlatform/AI"

# #4279: the retry schedule is owned by bedrock_client.invoke_with_retry — this name is
# the re-export ai_calls has always carried (#3082), bound to the one schedule, not a copy.
_BACKOFF_DELAYS = INVOKE_RETRY_BASE_DELAYS

# R17-16 outage sentinel returned by call_anthropic when Bedrock is unreachable
# or tier-3 BudgetExceeded fires. #952 (ai-content-6): the coach v2 pipeline must
# treat it as "no output" — it contains no numbers so it sails through the
# grounding gate, and on the same outage the quality-gate lambda's own Bedrock
# call fails open — so without an explicit check the literal gets cached under
# the brief fingerprint (sticky reuse), recorded by coach-state-updater, and
# rendered in the brief.
AI_UNAVAILABLE_SENTINEL = "[AI_UNAVAILABLE]"

# Bedrock error codes worth another attempt: the one set, owned by bedrock_client (#4279).
_RETRYABLE_BEDROCK_CODES = RETRYABLE_BEDROCK_CODES

# AI-3 middleware: lazy import of output validator (transparent fail-safe)
try:
    from ai.ai_output_validator import AIOutputType, validate_ai_output as _validate_ai_output

    _AI_VALIDATOR_AVAILABLE = True
except ImportError:
    _validate_ai_output = None
    AIOutputType = None  # type: ignore[misc]
    _AI_VALIDATOR_AVAILABLE = False


def _emit_failure_metric(metric_name: str = "AnthropicAPIFailure"):
    """Emit a failure metric to CloudWatch (P1.8).

    #2668: named, so a pass failing for its OWN reason gets its own series — an
    IC-3 truncation returned 200 and would corrupt the AnthropicAPIFailure metric
    that `slo-ai-coaching-success` keys on.
    """
    try:
        _cw.put_metric_data(
            Namespace=_CW_NAMESPACE,
            MetricData=[
                {
                    "MetricName": metric_name,
                    "Dimensions": [{"Name": "LambdaFunction", "Value": _LAMBDA_NAME}],
                    "Value": 1,
                    "Unit": "Count",
                },
                {"MetricName": metric_name, "Value": 1, "Unit": "Count"},  # #3260: fleet-wide twin (see common/retry_utils)
            ],
        )
    except Exception as e:
        print(f"[WARN] CloudWatch failure metric emit failed (non-fatal): {e}")


def _build_system_block(system, cache_system):
    """Convert system prompt to cached content block format if caching enabled."""
    if not system:
        return None
    if isinstance(system, list):
        return system  # already structured
    if cache_system:
        return [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
    return system


def call_anthropic(
    prompt: str,
    api_key: str = "",  # ADR-062: ignored — Bedrock uses IAM auth. Kept default for compat.
    max_tokens: int = 200,
    system: Union[str, list[dict[str, Any]], None] = None,
    output_type: Any = None,
    health_context: Optional[dict[str, Any]] = None,
    model: Optional[str] = None,
    cache_system: bool = True,
) -> str:
    """Call Claude on Bedrock under the one retry policy (#4279: bedrock_client.invoke_with_retry —
    3 sends, jittered 5/15 s; was 4 attempts at 5/15/45 s stacked on botocore's 3 sends).

    P1.9: Token usage emitted to CloudWatch LifePlatform/AI namespace.
    COST-OPT: Prompt caching — 90% discount on cached system message tokens.
    AI-3 middleware: validates output when output_type is specified (transparent fail-safe).
    R17-16: Graceful degradation — returns "[AI_UNAVAILABLE]" after all retries exhausted
            instead of raising. Callers should check for AI_UNAVAILABLE.

    Args:
        model:          Model ID override — defaults to AI_MODEL env var.
        cache_system:   Enable prompt caching on system message (default True).
        output_type:    AIOutputType enum value — enables AI-3 output validation.
                        Pass None (default) to skip — used for JSON callers and IC passes.
        health_context: Dict of health metrics for context-aware validation checks
                        (e.g. {"recovery_score": 45, "tsb": -12}).
    Returns text string, or "[AI_UNAVAILABLE]" if Anthropic is unavailable after all retries.
    """
    body = {
        "model": model or AI_MODEL,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    sys_block = _build_system_block(system, cache_system)
    if sys_block:
        body["system"] = sys_block

    # ADR-062 (2026-05-27): migrated from direct Anthropic API (urllib POST to
    # api.anthropic.com) to AWS Bedrock invoke_model. Auth is IAM (api_key
    # param now ignored — kept for signature compatibility). Prompt caching
    # preserved via cache_control blocks in sys_block. Response shape is
    # identical to the direct API, so parsing/validation below is unchanged.
    from ai.bedrock_client import (
        UnknownModelError as _UnknownModel,
        budget_stop_cls as _budget_stop_cls,
        first_text as _first_text,
        invoke_with_retry as _invoke_with_retry,
    )

    _BudgetStop = _budget_stop_cls()

    # #4279: the retry policy is `bedrock_client.invoke_with_retry` — the ONE loop
    # (3 sends, jittered 5/15 s bases, botocore retries off). This used to be a
    # 4-attempt 5/15/45 s copy of its own stacked on botocore's 3 sends.
    # #2893: ONLY the transport call lives inside the `try`. An empty `content` list
    # (a max_tokens stop with no text) used to raise IndexError in here and re-invoke
    # the model: up to 4 billed calls, zero usable output. Transport failures retry;
    # a response you have already paid for does not.
    try:
        resp: dict[str, Any] = _invoke_with_retry(body, model_name=body["model"])
        # Token usage + estimated spend are metered centrally at bedrock_client.invoke() (G1).
    except _BudgetStop as e:
        # #3084: the tier-3 budget guard REFUSES before invoke_model — nothing was
        # billed and nothing about the next attempt would differ, so it never enters
        # the backoff (invoke_with_retry re-raises it at once). It used to sleep
        # 5+15+45 = 65s per call; across the brief's ~62 AI calls ~67 minutes.
        print(f"[INFO] AI paused by the budget guard (tier 3) — returning the outage sentinel immediately, no retry: {e}")
        return AI_UNAVAILABLE_SENTINEL
    except _UnknownModel as e:
        # #4275: the model NAME resolved to nothing — a configuration error raised
        # before invoke_model (nothing billed) that attempt 2 cannot fix. Never the
        # old silent Haiku fallback, never the backoff: fail the call loudly (the
        # message names the input and every known name) and let the caller's existing
        # degrade path run — for the brief that is the sentinel per coach, exactly the
        # contract a hard Bedrock error already has, only in seconds.
        _emit_failure_metric()
        print(f"[ERROR] AI model name did not resolve — NOT retried, nothing billed: {e}")
        return AI_UNAVAILABLE_SENTINEL
    except Exception as e:
        _emit_failure_metric()
        # R17-16: graceful degradation — return sentinel so callers know AI failed
        # (not just empty output). Callers check for AI_UNAVAILABLE.
        print(f"[ERROR] Bedrock unavailable after the retry policy gave up: {e}")
        return AI_UNAVAILABLE_SENTINEL

    text = _first_text(resp)
    if text is None:
        # Billed in full and unusable. The sentinel (not a retry) is the honest
        # answer: callers already treat it as "no output" (#952).
        _emit_failure_metric()
        print(
            f"[ERROR] Bedrock response carried no text block (stop_reason={resp.get('stop_reason')!r}) "
            "— NOT retried, the call was already billed (#2893)."
        )
        return AI_UNAVAILABLE_SENTINEL
    text = text.strip()

    # AI-3 middleware: validate output when output_type is specified
    if output_type is not None and _AI_VALIDATOR_AVAILABLE:
        try:
            vr = _validate_ai_output(text, output_type, health_context or {})
            if vr.blocked:
                print(f"[AI-3] BLOCKED {output_type}: {vr.block_reason}")
            elif vr.warnings:
                print(f"[AI-3] WARN {output_type}: {vr.warnings}")
            return vr.sanitized_text
        except Exception as _ve:
            print(f"[WARN] ai_output_validator non-fatal: {_ve}")
    return text
