"""
retry_utils.py — Shared Anthropic API retry + CloudWatch metrics utility.

P1.8: Exponential backoff — 4 attempts, delays 5s / 15s / 45s.
P1.9: Token usage emitted to CloudWatch LifePlatform/AI per Lambda.

Bundled with: daily-brief, weekly-digest, monthly-digest, nutrition-review,
              wednesday-chronicle, weekly-plate, monday-compass, anomaly-detector,
              hypothesis-engine, daily-insight-compute
"""

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any, Optional, Union

import boto3

# CloudWatch
_cw = boto3.client("cloudwatch", region_name=os.environ.get("AWS_REGION", "us-west-2"))
_LAMBDA_NAME = os.environ.get("AWS_LAMBDA_FUNCTION_NAME", "unknown")
_CW_NAMESPACE = "LifePlatform/AI"

# Backoff delays between attempts (seconds)
_BACKOFF_DELAYS = [5, 15, 45]  # attempts 1→2, 2→3, 3→4
_MAX_ATTEMPTS = len(_BACKOFF_DELAYS) + 1  # 4

# Retryable HTTP status codes
_RETRYABLE_CODES = frozenset([429, 500, 502, 503, 504, 529])

# AI model constants — override via env to avoid silent deprecation failures
AI_MODEL = os.environ.get("AI_MODEL", "claude-sonnet-4-6")
AI_MODEL_HAIKU = os.environ.get("AI_MODEL_HAIKU", "claude-haiku-4-5-20251001")


def _emit_token_metrics(input_tokens: int, output_tokens: int, cache_creation_tokens: int = 0, cache_read_tokens: int = 0) -> None:
    """Emit per-Lambda token usage to CloudWatch (non-fatal)."""
    try:
        metric_data = [
            {
                "MetricName": "AnthropicInputTokens",
                "Dimensions": [{"Name": "LambdaFunction", "Value": _LAMBDA_NAME}],
                "Value": input_tokens,
                "Unit": "Count",
            },
            {
                "MetricName": "AnthropicOutputTokens",
                "Dimensions": [{"Name": "LambdaFunction", "Value": _LAMBDA_NAME}],
                "Value": output_tokens,
                "Unit": "Count",
            },
        ]
        if cache_creation_tokens or cache_read_tokens:
            metric_data.append(
                {
                    "MetricName": "AnthropicCacheWriteTokens",
                    "Dimensions": [{"Name": "LambdaFunction", "Value": _LAMBDA_NAME}],
                    "Value": cache_creation_tokens,
                    "Unit": "Count",
                }
            )
            metric_data.append(
                {
                    "MetricName": "AnthropicCacheReadTokens",
                    "Dimensions": [{"Name": "LambdaFunction", "Value": _LAMBDA_NAME}],
                    "Value": cache_read_tokens,
                    "Unit": "Count",
                }
            )
        _cw.put_metric_data(Namespace=_CW_NAMESPACE, MetricData=metric_data)
    except Exception as e:
        print(f"[WARN] CloudWatch token metric emit failed (non-fatal): {e}")


def _emit_failure_metric() -> None:
    """Emit API failure metric to CloudWatch (non-fatal)."""
    try:
        _cw.put_metric_data(
            Namespace=_CW_NAMESPACE,
            MetricData=[
                {
                    "MetricName": "AnthropicAPIFailure",
                    "Dimensions": [{"Name": "LambdaFunction", "Value": _LAMBDA_NAME}],
                    "Value": 1,
                    "Unit": "Count",
                },
                # #3260: THE DIMENSIONLESS TWIN — the series the alarm actually reads.
                # `slo-ai-coaching-success` (cdk/stacks/monitoring_stack.py) watches
                # LifePlatform/AI::AnthropicAPIFailure with NO dimensions, and CloudWatch does
                # not roll a custom metric up across dimension sets. All seven emitters attached
                # {LambdaFunction=...}, so for 180 days the alarm read a series nothing wrote:
                # 0 datapoints at the alarm against 191 real failures across five Lambdas on
                # 2026-05-26 alone, threshold Sum>=3, last state change 2026-03-08.
                #
                # THE RULING (#3260): the alarm keeps its FLEET-WIDE semantic — "3 Bedrock
                # transport failures anywhere on the platform in a day pages" — so the fix is to
                # write the fleet-wide series, not to split into five per-function alarms whose
                # Sum>=3 would silently become a per-function threshold (five Lambdas failing
                # twice each = 10 failures and no page). The per-function series above is
                # UNTOUCHED, so attribution and every existing consumer see no discontinuity.
                # Same shape bedrock_client._emit_usage_metrics already uses for
                # AnthropicOutputTokens / EstimatedCostUSD: one PutMetricData call, two
                # datapoints. The six sibling copies of this function carry the one-line form.
                {"MetricName": "AnthropicAPIFailure", "Value": 1, "Unit": "Count"},
            ],
        )
    except Exception as e:
        print(f"[WARN] CloudWatch failure metric emit failed (non-fatal): {e}")


def _build_system_block(
    system: Union[str, list[dict[str, Any]], None],
    cache_system: bool,
) -> Union[str, list[dict[str, Any]], None]:
    """Convert system prompt to cached content block format if caching enabled."""
    if not system:
        return None
    if isinstance(system, list):
        return system  # already structured
    if cache_system:
        return [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
    return system


def call_anthropic_api(
    prompt: str,
    max_tokens: int = 500,
    system: Union[str, list[dict[str, Any]], None] = None,
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    timeout: int = 55,
    cache_system: bool = True,
) -> str:
    """Call Anthropic /v1/messages with exponential backoff + CloudWatch metrics.

    Args:
        prompt:       User message content (str).
        max_tokens:   Max tokens for response.
        system:       Optional system prompt (str or list of content blocks).
        model:        Model ID — defaults to AI_MODEL env var.
        temperature:  Optional temperature override.
        timeout:      HTTP timeout in seconds (default 55).
        cache_system: Enable prompt caching on system message (default True).
                      90% discount on cached input tokens.

    Returns:
        str: Response text, stripped.

    Raises:
        urllib.error.HTTPError / URLError on final failure (after 4 attempts).
        Emits AnthropicAPIFailure CloudWatch metric on final failure.
    """
    body = {
        "model": model or AI_MODEL,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    sys_block = _build_system_block(system, cache_system)
    if sys_block:
        body["system"] = sys_block
    if temperature is not None:
        body["temperature"] = temperature

    # ADR-062 (2026-05-27): Bedrock invoke_model (was urllib → api.anthropic.com).
    # Auth is IAM — no API key. See lambdas/bedrock_client.py.
    import botocore.exceptions as _bce
    from ai.bedrock_client import budget_stop_cls as _budget_stop_cls, first_text as _first_text, invoke as _bedrock_invoke

    _BudgetStop = _budget_stop_cls()

    # #2893: ONLY the transport call lives inside the retry `try`. It used to end
    # `return resp["content"][0]["text"].strip()` in here, so an empty `content`
    # list — the exact shape of a max_tokens stop with no emitted text — raised
    # IndexError, was caught by the generic `except Exception` below, and
    # re-invoked the model: up to 4 billed calls, zero usable output, logged at
    # WARN with Errors flat. Transport failures retry; a response you have
    # already paid for does not.
    resp: dict[str, Any] = {}
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            resp = _bedrock_invoke(body, model_name=body["model"])
            break

        except _BudgetStop as e:
            # #3084: a tier-3 budget stop is a refusal raised BEFORE invoke_model —
            # nothing billed, nothing that another attempt could change. The generic
            # handler below used to retry it, sleeping 5+15+45 = 65s per call and
            # logging a transport-shaped WARN that buried the real cause. Re-raise
            # now; the caller's own degrade path (fallback brief, skip-AI) engages
            # in seconds instead of minutes.
            print(f"[INFO] Bedrock call refused by the budget guard (tier 3) — NOT a transport error, not retried: {e}")
            raise

        except _bce.ClientError as e:
            code = e.response.get("Error", {}).get("Code", "Unknown")
            retryable = code in (
                "ThrottlingException",
                "ModelTimeoutException",
                "ServiceUnavailableException",
                "InternalServerException",
                "ModelNotReadyException",
            )
            print(f"[WARN] Bedrock {code} attempt {attempt}/{_MAX_ATTEMPTS}")
            if retryable and attempt < _MAX_ATTEMPTS:
                delay = _BACKOFF_DELAYS[attempt - 1]
                print(f"[INFO] Retrying in {delay}s...")
                time.sleep(delay)
            else:
                _emit_failure_metric()
                raise
        except Exception as e:
            print(f"[WARN] Bedrock error attempt {attempt}/{_MAX_ATTEMPTS}: {e}")
            if attempt < _MAX_ATTEMPTS:
                delay = _BACKOFF_DELAYS[attempt - 1]
                print(f"[INFO] Retrying in {delay}s...")
                time.sleep(delay)
            else:
                _emit_failure_metric()
                raise

    # Token usage + spend metered centrally at bedrock_client.invoke() (G1).
    text = _first_text(resp)
    if text is None:
        _emit_failure_metric()
        raise ValueError(
            f"Bedrock response carried no text block (stop_reason={resp.get('stop_reason')!r}) "
            "— NOT retried, the call was already billed (#2893)"
        )
    return text.strip()


def call_anthropic_raw(req: Union[dict[str, Any], urllib.request.Request], timeout: int = 55) -> dict[str, Any]:  # type: ignore[return]  # loop always returns on success or re-raises on the final attempt; the fall-through is unreachable
    """Retry wrapper around bedrock_client.invoke() for a raw Messages body.

    Preferred call shape (#505/J-2): pass the Anthropic Messages dict directly
    (model/messages/max_tokens/system) — no urllib Request, no API key, no
    headers. Legacy shape still accepted: a pre-built urllib.request.Request
    whose .data is that JSON body (the pre-ADR-062 api.anthropic.com pattern);
    its URL/headers are ignored (Bedrock auth is IAM). Returns the full parsed
    JSON response, so callers that read resp["content"][0]["text"] are
    unchanged.

    Prompt caching: preserved if the body has cache_control blocks in its
    system message (the wire format is identical on Bedrock).
    """
    import botocore.exceptions as _bce
    from ai.bedrock_client import budget_stop_cls as _budget_stop_cls, invoke as _bedrock_invoke

    _BudgetStop = _budget_stop_cls()

    if isinstance(req, dict):
        body = req
    else:
        # Legacy: extract the Messages body the caller built into the Request.
        raw = req.data
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8")
        body = json.loads(raw) if raw else {}

    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            resp = _bedrock_invoke(body, model_name=body.get("model"))
            # Token usage + spend metered centrally at bedrock_client.invoke() (G1).
            return resp

        except _BudgetStop as e:
            # #3084 — same refusal-not-failure rule as call_anthropic_api above.
            print(f"[INFO] Bedrock call refused by the budget guard (tier 3) — NOT a transport error, not retried: {e}")
            raise

        except _bce.ClientError as e:
            code = e.response.get("Error", {}).get("Code", "Unknown")
            retryable = code in (
                "ThrottlingException",
                "ModelTimeoutException",
                "ServiceUnavailableException",
                "InternalServerException",
                "ModelNotReadyException",
            )
            print(f"[WARN] Bedrock {code} attempt {attempt}/{_MAX_ATTEMPTS}")
            if retryable and attempt < _MAX_ATTEMPTS:
                delay = _BACKOFF_DELAYS[attempt - 1]
                print(f"[INFO] Retrying in {delay}s...")
                time.sleep(delay)
            else:
                _emit_failure_metric()
                raise
        except Exception as e:
            print(f"[WARN] Bedrock error attempt {attempt}/{_MAX_ATTEMPTS}: {e}")
            if attempt < _MAX_ATTEMPTS:
                delay = _BACKOFF_DELAYS[attempt - 1]
                print(f"[INFO] Retrying in {delay}s...")
                time.sleep(delay)
            else:
                _emit_failure_metric()
                raise


# ── #3688 — the unreadable-VERDICT retry ───────────────────────────────────────
#
# The two retry loops above are TRANSPORT retries: the call did not return, so
# nothing was billed and another attempt is free of double-charge. #2893 wrote
# the rule they obey in the comment inside `call_anthropic_api` — "Transport
# failures retry; a response you have already paid for does not" — and that rule
# is right for a narrative generation, where a truncated paragraph is still
# usable prose.
#
# It is NOT right for a JUDGE. A judge's answer is a verdict or it is nothing:
# a reply cut off at `max_tokens`, or one whose JSON will not parse, yields no
# judgement at all, so the money is already spent AND no coverage was bought.
# #3652 box 1 asked for "retried (or its budget raised) before the page is
# called UNEVALUATED" and PR #3656 shipped only the budget raise (700 → 1200).
# A raised budget makes truncation less likely; it does not make a truncated
# verdict recoverable. Live proof that the tail is still there: the scheduled
# `Visual QA (standalone)` workflow has failed every run since 2026-09-05 —
# run 34907061838 (2026-09-14T23:03Z) recorded 2 truncated + 1 unparseable
# reader-truth batches, 14 reader-facing surfaces unjudged, and because
# `ai-unevaluated` is a DECLINE class in tests/visual_qa_verdict.py the site was
# never reverted. Red for 9 consecutive days, silent by construction.
#
# So the retry is deliberately NARROW and lives here, at the existing chokepoint,
# rather than as a fourth loop somewhere else:
#   * it fires ONLY on a verdict the caller's own predicate calls unreadable —
#     never on a transport error (those already retry above) and never on a
#     readable verdict the caller merely dislikes;
#   * the second attempt is not a repeat of the first. `max_tokens` is multiplied,
#     so the retry is materially different from the call that just failed — a
#     re-ask at the identical cap is the #2893 re-bill with extra steps;
#   * it is capped at ONE retry by default (2 attempts total), so the worst case
#     is 1 + `budget_multiplier` caps' worth of output tokens on a batch that
#     would otherwise have bought nothing;
#   * EVERY attempt past the first prints, by attempt number and reason. #3652
#     box 1's actual wording was "with the retry visible in the log", and a run
#     that retried must be distinguishable from a run that did not.
VERDICT_RETRY_MAX_ATTEMPTS = 2
VERDICT_RETRY_BUDGET_MULTIPLIER = 2


def invoke_until_readable_verdict(
    invoke,
    body: dict[str, Any],
    unreadable,
    model_name: Optional[str] = None,
    label: str = "judge",
    max_attempts: int = VERDICT_RETRY_MAX_ATTEMPTS,
    budget_multiplier: int = VERDICT_RETRY_BUDGET_MULTIPLIER,
    log=print,
):
    """Invoke a judge, retrying once when the reply carries no readable verdict (#3688).

    Args:
        invoke:  a `bedrock_client.invoke`-compatible callable, called as
                 ``invoke(body, model_name=model_name)``.
        body:    the Anthropic Messages body. NEVER mutated — a retry gets a copy
                 with a raised `max_tokens` (callers reuse the body per batch).
        unreadable: ``resp -> reason_or_None``. Truthy means "the judge returned,
                 and its answer cannot be read as a verdict" (truncated /
                 unparseable / no verdict). The caller owns this predicate because
                 the two judge schemas differ; this module owns only the loop.
        model_name: forwarded to `invoke` unchanged.
        label:   what is being judged, for the log line (batch paths / page name).
        max_attempts: total attempts including the first. 1 disables the retry.
        budget_multiplier: `max_tokens` multiplier applied per retry attempt.
        log:     injectable printer (tests capture it).

    Returns:
        (resp, reason, attempts) — `reason` is None when a readable verdict was
        obtained, otherwise the FINAL attempt's unreadable reason, which the
        caller records exactly as it did before this existed. `attempts` is how
        many invocations were actually made.

    Raises:
        whatever `invoke` raises — a transport failure is NOT this loop's class
        and is left to the caller's existing fail-soft handling (#1440).
    """
    attempts_allowed = max(1, int(max_attempts))
    cap = int(body.get("max_tokens") or 0)
    resp: Any = None
    reason = None
    for attempt in range(1, attempts_allowed + 1):
        call_body = body
        if attempt > 1 and cap > 0:
            call_body = dict(body)
            call_body["max_tokens"] = cap * (int(budget_multiplier) ** (attempt - 1))
        resp = invoke(call_body, model_name=model_name)
        reason = unreadable(resp)
        if not reason:
            if attempt > 1:
                log(
                    f"  ↻ verdict retry ({label}): attempt {attempt}/{attempts_allowed} returned a READABLE "
                    f"verdict at max_tokens={call_body.get('max_tokens')} — NOT recorded UNEVALUATED (#3688)"
                )
            return resp, None, attempt
        if attempt >= attempts_allowed:
            log(
                f"  ↻ verdict retry ({label}): still unreadable ({reason}) after {attempt}/{attempts_allowed} "
                f"attempt(s) — recording UNEVALUATED (#3688)"
            )
            return resp, reason, attempt
        next_cap = cap * (int(budget_multiplier) ** attempt) if cap > 0 else None
        log(
            f"  ↻ verdict retry ({label}): attempt {attempt}/{attempts_allowed} was unreadable ({reason}) — "
            f"RETRYING at max_tokens={next_cap} (#3688)"
        )
    return resp, reason, attempts_allowed  # pragma: no cover — the loop always returns
