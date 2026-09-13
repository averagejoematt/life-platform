"""regen_discard_telemetry.py — #3086: observability for grounded_generation.regen_once's
silent-discard arms (transport/unexpected exception on the regen call, an empty regen
response, and — since #3217, split in two — a rewrite the keep predicate rejected).

Split out of grounded_generation.py rather than inlined there for two reasons: (1) that
module's own docstring commits it to "pure functions, no AWS, no HTTP" — a CloudWatch
`put_metric_data` call does not belong in it; (2) it sits at its §2/#1665 module-size
ceiling (see tests/test_module_size_guard.py) with no line budget for a new AWS client.

Every discard emits ONE ERROR log line (grep-able as `REGEN_DISCARDED`) plus a CloudWatch
`RegenDiscarded` count in the existing `LifePlatform/AI` namespace — same namespace, same
non-fatal try/except-and-print shape as `common.retry_utils._emit_token_metrics` (this
module is the sibling for the discard side of that same pipeline), with `Surface` + `Arm`
dimensions instead of that sibling's `LambdaFunction` (baseline cardinality kept deliberately
low — no alarm yet, per #3081's rule, so a third dimension isn't earning its keep today).
Before #3086, exactly ONE caller of regen_once (`ai_calls._ground_legacy_output`) printed
anything about a discard at all, so #2893's waste table could only price the
corrective-rewrite discard rate for that one surface out of ~15 (#3081).
"""

import logging
import os

import boto3
from botocore.config import Config

logger = logging.getLogger(__name__)

_CW_NAMESPACE = "LifePlatform/AI"
_METRIC_NAME = "RegenDiscarded"

# #3722: the client is built LAZILY and bounded, and it was neither.
#
# It used to be a module-level `boto3.client(...)` and `log_discard` called
# `put_metric_data` on it unconditionally — so every caller that merely IMPORTED this
# module paid a client build, and every discard made a live HTTPS round-trip. The test
# suite is a caller: `tests/test_prop_grounded_generation.py::test_regen_once_never_
# regresses` drives `regen_once` 150 times per run, most of which discard, so the
# property test was doing ~150 live CloudWatch calls. Measured on this machine,
# n=150: first call 68.7ms, median 18.1ms, p95 57.1ms — and under Hypothesis's 200ms
# default deadline that is a coin flip on network latency, which Hypothesis reports as
# `FlakyFailure: produces unreliable results: Failed on the first call but did not on a
# subsequent one`. The filed suspicion was lazy CREDENTIAL resolution; the measurement
# says the divergence is real but the mechanism is per-call LATENCY, not a first-call
# code path — the same numbers appear under CI's FAKE credentials (first 59.1ms,
# median 14.9ms), where every call fails and is swallowed.
#
# Two independent things follow, and both are fixed:
#   * telemetry must be OFF by default outside a Lambda. `AWS_LAMBDA_FUNCTION_NAME` is
#     set by the runtime and by nothing else, so it is the signal that distinguishes
#     "in production" from "imported by a test" without a test-only flag.
#   * when it IS on, it must be bounded. An unbounded put_metric_data inside a
#     fail-soft except is a hang wearing a no-op's clothes: a dead CloudWatch endpoint
#     would have held a Lambda open for the SDK's default 60s connect timeout per
#     discard. 1s/1s and a single attempt — this is fire-and-forget observability, and
#     a metric worth waiting a minute for is not one.
_TELEMETRY_ENABLED_ENV = "REGEN_TELEMETRY"
_cw = None


def _telemetry_enabled() -> bool:
    """True when the CloudWatch emit should actually be attempted.

    Explicit `REGEN_TELEMETRY=1|0` wins in both directions (so a test can turn it ON
    and production can turn it OFF); otherwise it follows "am I running inside a
    Lambda".
    """
    override = os.environ.get(_TELEMETRY_ENABLED_ENV, "").strip().lower()
    if override in {"1", "true", "yes", "on"}:
        return True
    if override in {"0", "false", "no", "off"}:
        return False
    return bool(os.environ.get("AWS_LAMBDA_FUNCTION_NAME"))


def _client():
    """The CloudWatch client, built on first use and cached for the container."""
    global _cw
    if _cw is None:
        _cw = boto3.client(
            "cloudwatch",
            region_name=os.environ.get("AWS_REGION", "us-west-2"),
            config=Config(connect_timeout=1, read_timeout=1, retries={"max_attempts": 1}),
        )
    return _cw


def log_discard(arm: str, surface: str, findings_count: int, *, reason: str = "", cost_estimate: str = "") -> None:
    """One ERROR line + one CloudWatch count for a billed-but-discarded regeneration.

    arm            -- which regen_once discard path fired: "transport_error",
                       "unexpected_error", "empty_response", "not_strictly_better",
                       or (since #3217) "figure_grounding_introduced" — the rewrite
                       traded one invented figure for another. The last two are the
                       two halves of the old single not-strictly-better arm, split so
                       the log names WHICH predicate dropped the rewrite; their names
                       are `ai/regen_keep_predicate.py`'s DROP_* constants (named DROP_, not DISCARD_,
                       for the CodeQL reason that module's docstring records).
    surface        -- caller identity, same convention as ai_calls._ground_legacy_output's
                       `label` param (the one caller that already logged this pre-#3086).
    findings_count -- len(findings) still outstanding on the text regen_once kept.
    reason         -- exception class name, for the two exception arms (else "").
    cost_estimate  -- token/cost context, when the caller has it. regen_fn's contract is
                       "returns text only" for every current caller, so this is almost
                       always absent today ("n/a") — the param exists so a caller that
                       later threads usage/cost through has somewhere to put it.
    """
    logger.error(
        "REGEN_DISCARDED arm=%s surface=%s findings=%d reason=%s cost=%s",
        arm,
        surface,
        findings_count,
        reason or "n/a",
        cost_estimate or "n/a",
    )
    if not _telemetry_enabled():
        # The ERROR line above is the durable record and is emitted either way; only
        # the metric emit is skipped. A discard is never silent (#3086's whole point).
        return
    try:
        _client().put_metric_data(
            Namespace=_CW_NAMESPACE,
            MetricData=[
                {
                    "MetricName": _METRIC_NAME,
                    "Dimensions": [
                        {"Name": "Surface", "Value": surface},
                        {"Name": "Arm", "Value": arm},
                    ],
                    "Value": 1,
                    "Unit": "Count",
                }
            ],
        )
    except Exception as e:
        print(f"[WARN] CloudWatch {_METRIC_NAME} metric emit failed (non-fatal): {e}")
