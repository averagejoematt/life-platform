"""mcp/invoke_gate.py — who may reach the MCP function's privileged (non-request) branches (#5540).

`mcp.handler.lambda_handler` serves three request transports (Function URL, bridge) AND three
privileged, no-request branches: the `{"job": "nightly_predraft"}` and `{"job":
"panel_weekly_grade"}` constant-input jobs, and the scheduled-event envelope that runs the nightly
cache warmer. Until #5540 those three ran BEFORE any auth check, on whichever function received
them — including the request-serving `life-platform-mcp`, whose schedules are all on the warmer.

The rule this module states (checked before ANY privileged branch runs):

- every privileged branch runs only on the dedicated warmer function (`WARMER_FUNCTION_NAME`, the
  `cdk/stacks/mcp_stack.py` declaration — pinned by tests/test_mcp_invoke_gate_5540.py);
- the scheduled-event branch additionally needs `event["resources"]` to name an EventBridge
  Scheduler schedule of THIS account and region created by the MCP stack (`SCHEDULE_NAME_PREFIX`,
  the CDK-generated name prefix of `LifePlatformMcp`'s schedules). The live warmer schedule's
  envelope carries `<aws.scheduler.schedule-arn>` there (cdk/stacks/lambda_helpers.py
  `_scheduled_event_envelope`), so the real schedule satisfies it and a hand-built envelope does not.

Not a cryptographic boundary: anyone holding `lambda:InvokeFunction` on the warmer can still
forge the envelope — IAM is the boundary. What this closes is the request-serving function
running privileged work on a payload shape, and a bare `{"source": "aws.events"}` being enough.
The job events carry no `resources` today (their constant inputs are `{"job": ...}`); requiring
it there is the residual named on #5540.
"""

from __future__ import annotations

import json
from typing import Any

#: The dedicated warmer (cdk/stacks/mcp_stack.py WARMER_FUNCTION_NAME). The ONLY function whose
#: privileged branches may run.
WARMER_FUNCTION_NAME = "life-platform-mcp-warmer"

#: CDK names an unnamed EventBridge Scheduler schedule `<StackName>-<LogicalId>-<suffix>`; the
#: MCP stack is `LifePlatformMcp` (cdk/app.py). Live: `LifePlatformMcp-McpWarmerPacificSchedule-…`.
SCHEDULE_NAME_PREFIX = "LifePlatformMcp-"

#: The privileged job names `lambda_handler` dispatches on `event["job"]`.
PRIVILEGED_JOBS = ("nightly_predraft", "panel_weekly_grade")

SCHEDULED = "scheduled"


def privileged_kind(event: Any) -> str | None:
    """The privileged branch `event` asks for — a job name, `SCHEDULED`, or None for a request."""
    if not isinstance(event, dict):
        return None
    job = event.get("job")
    if job in PRIVILEGED_JOBS:
        return str(job)
    if event.get("source") == "aws.events" or event.get("detail-type") == "Scheduled Event":
        return SCHEDULED
    return None


def _invoked_region_account(context: Any) -> tuple[str, str] | None:
    """(region, account) from the invoked function ARN, or None if it cannot be read."""
    arn = getattr(context, "invoked_function_arn", None)
    if not isinstance(arn, str):
        return None
    parts = arn.split(":")
    # arn:aws:lambda:<region>:<account>:function:<name>[:<qualifier>]
    if len(parts) < 7 or parts[0] != "arn" or parts[2] != "lambda" or not parts[3] or not parts[4]:
        return None
    return parts[3], parts[4]


def is_warmer(context: Any) -> bool:
    return getattr(context, "function_name", None) == WARMER_FUNCTION_NAME


def names_known_schedule(event: dict, context: Any) -> bool:
    """True when `event["resources"]` names one of the MCP stack's Scheduler schedules in this
    account and region (`arn:aws:scheduler:<region>:<account>:schedule/<group>/<name>`)."""
    where = _invoked_region_account(context)
    resources = event.get("resources")
    if where is None or not isinstance(resources, list):
        return False
    region, account = where
    head = f"arn:aws:scheduler:{region}:{account}:schedule/"
    for arn in resources:
        if not isinstance(arn, str) or not arn.startswith(head):
            continue
        tail = arn[len(head) :].split("/")
        if len(tail) == 2 and tail[0] and tail[1].startswith(SCHEDULE_NAME_PREFIX):
            return True
    return False


def refusal_reason(kind: str, event: dict, context: Any) -> str | None:
    """Why the privileged branch `kind` must NOT run for this invoke, or None when it may."""
    if not is_warmer(context):
        return f"privileged branch {kind!r} runs only on {WARMER_FUNCTION_NAME}, not {getattr(context, 'function_name', None)!r}"
    if kind == SCHEDULED and not names_known_schedule(event, context):
        return f"scheduled event does not name a {SCHEDULE_NAME_PREFIX}* schedule of this account/region in `resources`"
    return None


def refusal_response(reason: str) -> dict:
    return {
        "statusCode": 403,
        "body": json.dumps({"error": "Forbidden", "reason": reason}),
        "headers": {"Content-Type": "application/json"},
    }


def describe(event: dict) -> str:
    """A log-safe description of a refused event — its shape, never a value that could be private
    (keys, source, detail-type, and the resource ARNs, which name infrastructure only)."""
    resources = event.get("resources")
    return json.dumps(
        {
            "keys": sorted(str(k) for k in event.keys())[:20],
            "source": event.get("source"),
            "detail-type": event.get("detail-type"),
            "job": event.get("job"),
            "resources": resources[:5] if isinstance(resources, list) else None,
        },
        default=str,
    )
