"""cdk/stacks/monitoring_denial_alarms.py — the PERMISSION-DENIAL class alarm (#3563).

WHY THIS IS NOT IN `monitoring_silence_alarms.py`. That module's own membership rule is
explicit: an alarm belongs there when it keys on a `FilterPattern.literal` of a token that
is a **named constant in a lambda module**, twin-pinned from both ends. This alarm keys on
`AccessDenied` — a string **botocore** produces, present in the exception text of every
IAM refusal on every AWS API in every runtime, in whatever the swallowing site happened to
print. There is no lambda constant to pin, and that absence is the entire point: this is
the alarm for the denial NOBODY tokenized.

THE INCIDENT CLASS (#3563, findings G-3 + INT-1 of the 2026-09-05 `/review full` baseline)
A fail-soft write is the right contract — indexing must not block a publish, telemetry must
not break an AI call, an alert-state write must not stop the alert. It is also, by
construction, silent, and an `AccessDenied` is the one failure inside it that will NEVER
self-heal: it is a misconfiguration, it recurs on every single invocation, and the only
alarm those functions carry (`AWS/Lambda Errors`) needs a RAISED exception to see anything.
So:

  * `chronicle-email-sender` — 3/3 sends from 2026-08-08 wrote the `email_log` row
    `/api/status` reads; 3/3 AccessDenied; the public status page called the flagship
    weekly product red / "44d ago" for four weeks while it shipped. Four weeks.
  * `life-platform-freshness-checker` — 155 denials in 14 days on the #1480 notion
    journal-dark sentinel; the dedup that PR shipped had never once executed.
  * `life-platform-qa-smoke` — 131 denials in the 30d window (an S3 List prefix, #3573).
  * **twelve Bedrock-invoking roles** that could invoke and could not
    `cloudwatch:PutMetricData`, so `bedrock_client` billed in full and dropped every cost
    datapoint — the same series the ADR-133 budget governor projects spend from. #2974
    found this shape once on a CI role; the 2026-09-14 sweep for #3563 found it on eight
    production roles still emitting that day. Granted in `role_policies_base.
    _bedrock_telemetry_statement()` in the same PR; `tests/test_bedrock_telemetry_iam_
    parity_3563.py` keeps the pairing.

Each of those was repaired ONE AT A TIME, by a human reading logs, weeks late. The repair
is not the instrument. THIS is: any denial, in any function of the email + operational
family, reaches the digest within the hour — including the next one nobody predicted.

THE SHAPE, AND WHY IT IS AFFORDABLE. One `MetricFilter` per watched log group (metric
filters are free), every one of them publishing the SAME dimensionless metric, and ONE
alarm on it. The 2026-09-05 forensic RCA rejected a `level=ERROR` filter fleet at
$1.50–2.90/mo — correctly: its cost driver is DISTINCT METRIC NAMES ($0.30 each) plus an
alarm each ($0.10). Collapsing N filters onto one metric makes the bill independent of N:
$0.10/mo for the alarm, and the metric itself costs nothing while no datapoint is ever
published, which is the healthy state (`AccessDenied` appears in no healthy log line).
`docs/PROPORTIONALITY.md` carries the row.

WHAT IT CANNOT DO, STATED. The metric is dimensionless, so the alarm says "a denial
happened in the family" and not which function — that is the price of one metric instead
of forty-six. The alarm DESCRIPTION carries the Logs Insights query that names it in one
step; it is the first line of the runbook, not an exercise for the reader.

MEMBERSHIP IS DERIVED, NOT CURATED. `WATCHED_LOG_GROUPS` below is the log group of every
Lambda constructed in `email_stack.py` and `operational_stack.py` — the "email or checker
Lambda" family the issue names. It is written out as literals because three static
analyses read this tree by shape (see the extraction note in `monitoring_silence_alarms.py`),
and `tests/test_swallowed_denial_visibility_3563.py` re-derives the same set from those two
stacks and reds BOTH ways: a new email/operational Lambda missing here, and a name here
that is no longer a Lambda. A hand-typed list with a derivation ratchet on it is a
registry; without one it is a comment.
"""

from aws_cdk import (
    Duration,
    aws_cloudwatch as cloudwatch,
    aws_cloudwatch_actions as cw_actions,
    aws_logs as logs,
)

#: The literal every IAM refusal carries. `AccessDenied` is a substring of
#: `AccessDeniedException` (DynamoDB/SSM/Secrets Manager) as well as the bare
#: `AccessDenied` that S3 and CloudWatch return, so ONE quoted term covers both
#: spellings — a CloudWatch quoted term is a substring match, not a word match.
#: Real captured lines from all three incidents are pinned as fixtures in
#: tests/test_swallowed_denial_visibility_3563.py, so "the pattern still matches
#: what the platform actually prints" is asserted against the wire, not assumed.
DENIAL_TERM = "AccessDenied"

#: One metric for the whole class — see the cost note in the module docstring.
#: These four constants are the TWINS of the string literals written out at the
#: construct call sites in `add_denial_alarms` (the static analyses go blind on a
#: variable — see the docstring there). They are the readable, importable form and
#: are pinned equal to the literals by the visibility test; nothing else may rely on
#: one without the other.
DENIAL_METRIC = "SwallowedPermissionDenied"
#: `LifePlatform/Lambda` is the existing namespace for metrics minted in CDK from
#: log TEXT rather than emitted by Python (tests/test_emf_namespace_ledger_2837.py
#: pins that semantic). This is one of those; it does not need a namespace of its own.
DENIAL_NAMESPACE = "LifePlatform/Lambda"

DENIAL_ALARM_NAME = "swallowed-permission-denial"

#: Every Lambda in LifePlatformEmail + LifePlatformOperational — the email and
#: checker family. Derived + ratcheted by tests/test_swallowed_denial_visibility_3563.py.
WATCHED_LOG_GROUPS = (
    # ── LifePlatformEmail ────────────────────────────────────────────────────
    "/aws/lambda/ai-review-pack",
    "/aws/lambda/between-chronicle",
    "/aws/lambda/chronicle-approve",
    "/aws/lambda/chronicle-email-sender",
    "/aws/lambda/chronicle-podcast",
    "/aws/lambda/coach-nudge",
    "/aws/lambda/coach-panel-podcast",
    "/aws/lambda/daily-brief",
    "/aws/lambda/daily-debrief",
    "/aws/lambda/elena-state-updater",
    "/aws/lambda/milestone-digest",
    "/aws/lambda/monday-compass",
    "/aws/lambda/monthly-digest",
    "/aws/lambda/nutrition-review",
    "/aws/lambda/partner-weekly-email",
    "/aws/lambda/subscriber-onboarding",
    "/aws/lambda/wednesday-chronicle",
    "/aws/lambda/weekly-digest",
    "/aws/lambda/weekly-plate",
    "/aws/lambda/weekly-signal",
    "/aws/lambda/evening-nudge",
    # ── LifePlatformOperational ──────────────────────────────────────────────
    "/aws/lambda/hevy-restamp",
    "/aws/lambda/hevy-routine-cron",
    "/aws/lambda/insight-email-parser",
    "/aws/lambda/life-platform-ai-quality-canary",
    "/aws/lambda/life-platform-alert-digest",
    "/aws/lambda/life-platform-canary",
    "/aws/lambda/life-platform-coherence-sentinel",
    "/aws/lambda/life-platform-cost-governor",
    "/aws/lambda/life-platform-data-export",
    "/aws/lambda/life-platform-data-reconciliation",
    "/aws/lambda/life-platform-delete-user-data",
    "/aws/lambda/life-platform-dlq-consumer",
    "/aws/lambda/life-platform-freshness-checker",
    "/aws/lambda/life-platform-key-rotator",
    "/aws/lambda/life-platform-permanence",
    "/aws/lambda/life-platform-pip-audit",
    "/aws/lambda/life-platform-qa-smoke",
    "/aws/lambda/life-platform-remediation-dispatcher",
    "/aws/lambda/life-platform-traffic-digest",
    "/aws/lambda/og-image-generator",
    "/aws/lambda/pipeline-health-check",
    "/aws/lambda/reading-cover-pipeline",
    "/aws/lambda/reading-recall-sweep",
    "/aws/lambda/recap-card-generator",
    "/aws/lambda/site-stats-refresh",
)

_ALARM_DESCRIPTION = (
    "An IAM permission denial was logged by a Lambda in the email/operational family (#3563). "
    "Nothing raised — these are fail-soft paths, so the work SILENTLY did not happen and the "
    "surface that depends on it is now quietly wrong (the class that read /api/status 'Wednesday "
    "chronicle' as red for four weeks while it shipped). This never self-heals: a denial is a "
    "misconfiguration and recurs every invocation until the grant is widened. "
    "Name the offender: aws logs start-query --log-group-names $(python3 -c "
    "\"import sys;sys.path.insert(0,'cdk/stacks');import monitoring_denial_alarms as m;"
    "print(' '.join(m.WATCHED_LOG_GROUPS))\") --start-time $(($(date +%s)-86400)) --end-time "
    "$(date +%s) --query-string 'fields @log,@message | filter @message like /AccessDenied/ "
    "| stats count() by @log' — then widen the role in cdk/stacks/role_policies*.py (Bucket B, #2611)."
)


def add_denial_alarms(scope, digest) -> None:
    """Attach the permission-denial class alarm to `scope`. See the module docstring.

    NOT_BREACHING: absence of a denial is health. A dead Lambda is the error/heartbeat
    alarms' job, not this one's.

    THE FILTERS ARE A LOOP AND EVERY NAME IS A STRING LITERAL — deliberately, and the
    split is load-bearing. `deploy/alarm_discovery.py`, `scripts/generate_platform_model.py`
    and `deploy/doc_alarm_inventory.py` all resolve alarm names, metric names and SNS
    routing STATICALLY, and every one of them goes blind on a name passed as a variable —
    this file's first draft used `alarm_name=DENIAL_ALARM_NAME` and the name discoverer
    returned 124 names for 125 alarms, the exact #2977/#795 divergence, caught by
    `tests/test_sync_doc_metadata_check.py`. So the literals are written out at the
    construct call sites and the module constants above are their twins, pinned equal by
    `tests/test_swallowed_denial_visibility_3563.py`. Forty-six verbatim filter blocks
    would buy nothing (no analysis reads metric filters by construct) and would hide the
    one thing worth reading: that every filter publishes the same metric.
    """
    denial_metric = cloudwatch.Metric(
        namespace="LifePlatform/Lambda",
        metric_name="SwallowedPermissionDenied",
        period=Duration.seconds(300),
        statistic="Sum",
    )

    for log_group_name in WATCHED_LOG_GROUPS:
        # Construct ids are derived from the function name so adding/removing a watched
        # Lambda never renumbers the others' logical ids (a positional id would replace
        # every filter after the insertion point on the next deploy).
        suffix = "".join(part.capitalize() for part in log_group_name.rsplit("/", 1)[-1].split("-"))
        logs.MetricFilter(
            scope,
            f"DenialFilter{suffix}",
            log_group=logs.LogGroup.from_log_group_name(scope, f"DenialLg{suffix}", log_group_name),
            filter_pattern=logs.FilterPattern.literal('"AccessDenied"'),
            metric_name="SwallowedPermissionDenied",
            metric_namespace="LifePlatform/Lambda",
            metric_value="1",
        )

    denial_alarm = cloudwatch.Alarm(
        scope,
        "SwallowedPermissionDenialAlarm",
        alarm_name="swallowed-permission-denial",
        alarm_description=_ALARM_DESCRIPTION,
        metric=denial_metric,
        evaluation_periods=1,
        threshold=1,
        comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
        treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
    )
    denial_alarm.add_alarm_action(cw_actions.SnsAction(digest))
