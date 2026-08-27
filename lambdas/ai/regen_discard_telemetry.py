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

logger = logging.getLogger(__name__)

_cw = boto3.client("cloudwatch", region_name=os.environ.get("AWS_REGION", "us-west-2"))
_CW_NAMESPACE = "LifePlatform/AI"
_METRIC_NAME = "RegenDiscarded"


def log_discard(arm: str, surface: str, findings_count: int, *, reason: str = "", cost_estimate: str = "") -> None:
    """One ERROR line + one CloudWatch count for a billed-but-discarded regeneration.

    arm            -- which regen_once discard path fired: "transport_error",
                       "unexpected_error", "empty_response", "not_strictly_better",
                       or (since #3217) "figure_grounding_introduced" — the rewrite
                       traded one invented figure for another. The last two are the
                       two halves of the old single not-strictly-better arm, split so
                       the log names WHICH predicate dropped the rewrite; their names
                       are `ai/regen_keep_predicate.py`'s DISCARD_* constants.
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
    try:
        _cw.put_metric_data(
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
