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
                }
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
    from bedrock_client import invoke as _bedrock_invoke

    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            resp = _bedrock_invoke(body, model_name=body["model"])
            # Token usage + spend metered centrally at bedrock_client.invoke() (G1).
            return resp["content"][0]["text"].strip()

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


def call_anthropic_raw(req: Union[dict[str, Any], urllib.request.Request], timeout: int = 55) -> dict[str, Any]:
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
    from bedrock_client import invoke as _bedrock_invoke

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
