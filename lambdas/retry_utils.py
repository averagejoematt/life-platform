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
AI_MODEL       = os.environ.get("AI_MODEL",       "claude-sonnet-4-6")
AI_MODEL_HAIKU = os.environ.get("AI_MODEL_HAIKU", "claude-haiku-4-5-20251001")


def _emit_token_metrics(input_tokens, output_tokens):
    """Emit per-Lambda token usage to CloudWatch (non-fatal)."""
    try:
        _cw.put_metric_data(
            Namespace=_CW_NAMESPACE,
            MetricData=[
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
            ],
        )
    except Exception as e:
        print(f"[WARN] CloudWatch token metric emit failed (non-fatal): {e}")


def _emit_failure_metric():
    """Emit API failure metric to CloudWatch (non-fatal)."""
    try:
        _cw.put_metric_data(
            Namespace=_CW_NAMESPACE,
            MetricData=[{
                "MetricName": "AnthropicAPIFailure",
                "Dimensions": [{"Name": "LambdaFunction", "Value": _LAMBDA_NAME}],
                "Value": 1,
                "Unit": "Count",
            }],
        )
    except Exception as e:
        print(f"[WARN] CloudWatch failure metric emit failed (non-fatal): {e}")


def call_anthropic_api(
    prompt,
    api_key,
    max_tokens=500,
    system=None,
    model=None,
    temperature=None,
    timeout=55,
):
    """Call Anthropic /v1/messages with exponential backoff + CloudWatch metrics.

    Args:
        prompt:      User message content (str).
        api_key:     Anthropic API key.
        max_tokens:  Max tokens for response.
        system:      Optional system prompt (str).
        model:       Model ID — defaults to AI_MODEL env var.
        temperature: Optional temperature override.
        timeout:     HTTP timeout in seconds (default 55).

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
    if system:
        body["system"] = system
    if temperature is not None:
        body["temperature"] = temperature

    payload = json.dumps(body).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )

    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                resp = json.loads(r.read())
                usage = resp.get("usage", {})
                if usage:
                    _emit_token_metrics(
                        usage.get("input_tokens", 0),
                        usage.get("output_tokens", 0),
                    )
                return resp["content"][0]["text"].strip()

        except urllib.error.HTTPError as e:
            print(f"[WARN] Anthropic HTTP {e.code} attempt {attempt}/{_MAX_ATTEMPTS}")
            if e.code in _RETRYABLE_CODES and attempt < _MAX_ATTEMPTS:
                delay = _BACKOFF_DELAYS[attempt - 1]
                print(f"[INFO] Retrying in {delay}s...")
                time.sleep(delay)
            else:
                _emit_failure_metric()
                raise

        except urllib.error.URLError as e:
            print(f"[WARN] Anthropic network error attempt {attempt}/{_MAX_ATTEMPTS}: {e}")
            if attempt < _MAX_ATTEMPTS:
                delay = _BACKOFF_DELAYS[attempt - 1]
                print(f"[INFO] Retrying in {delay}s...")
                time.sleep(delay)
            else:
                _emit_failure_metric()
                raise


def call_anthropic_raw(req, timeout=55):
    """Retry wrapper for pre-built urllib Request objects (used by weekly-digest pattern).

    Returns the full parsed JSON response (not just text) — callers extract
    resp["content"][0]["text"] themselves.
    Emits token metrics and failure metric same as call_anthropic_api.
    """
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                resp = json.loads(r.read())
                usage = resp.get("usage", {})
                if usage:
                    _emit_token_metrics(
                        usage.get("input_tokens", 0),
                        usage.get("output_tokens", 0),
                    )
                return resp

        except urllib.error.HTTPError as e:
            print(f"[WARN] Anthropic HTTP {e.code} attempt {attempt}/{_MAX_ATTEMPTS}")
            if e.code in _RETRYABLE_CODES and attempt < _MAX_ATTEMPTS:
                delay = _BACKOFF_DELAYS[attempt - 1]
                print(f"[INFO] Retrying in {delay}s...")
                time.sleep(delay)
            else:
                _emit_failure_metric()
                raise

        except urllib.error.URLError as e:
            print(f"[WARN] Anthropic network error attempt {attempt}/{_MAX_ATTEMPTS}: {e}")
            if attempt < _MAX_ATTEMPTS:
                delay = _BACKOFF_DELAYS[attempt - 1]
                print(f"[INFO] Retrying in {delay}s...")
                time.sleep(delay)
            else:
                _emit_failure_metric()
                raise
