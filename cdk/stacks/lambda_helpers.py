"""
lambda_helpers.py — Shared Lambda construction patterns for CDK stacks.

Provides a helper function that creates a Lambda function with all the
standard Life Platform conventions:
  - Per-function IAM role with explicit least-privilege policies
  - DLQ configured
  - Environment variables (TABLE_NAME, S3_BUCKET, USER_ID)
  - CloudWatch error alarm
  - Handler auto-detection from source file

v2.0 (v3.4.0): Added custom_policies parameter to replace existing_role_arn.
  CDK now OWNS all IAM roles — no more from_role_arn references.
  Migration: existing_role_arn is DEPRECATED and will be removed in a future version.

v3.0 (#781, 2026-07-06): the shared layer (life-platform-shared-utils) is RETIRED.
  Every function's code asset is the staged full-tree bundle from
  deploy/build_bundle.py (lambdas/ + food_vocabulary.json), so shared modules
  ship inside the function bundle — one distribution channel, no layer-version
  drift. `additional_layers` remains for real third-party dependency layers
  (garth, pillow) only.

Usage in a stack:
    from stacks.lambda_helpers import create_platform_lambda
    from stacks.role_policies import ingestion_policies

    fn = create_platform_lambda(
        self, "WhoopIngestion",
        function_name="whoop-data-ingestion",
        source_file="lambdas/ingestion/whoop_lambda.py",
        handler="ingestion.whoop_lambda.lambda_handler",
        table=core.table,
        bucket=core.bucket,
        dlq=core.dlq,
        custom_policies=ingestion_policies("whoop"),
        timeout_seconds=120,
    )

Schedules (#4284): the factory takes NO schedule argument. It reads the function's row from
config/schedules.json (cdk/stacks/schedule_table.py) by `function_name`; a schedule built beside
the factory is `add_table_schedule(..., schedule=table_schedule("<function>#<ConstructId>"))`.
Every cron row is wall-clock time in the table's `platform_timezone` (ADR-165) and becomes an
EventBridge Scheduler schedule on the stack's ONE scheduler role; a rate or a UTC opt-out stays
a fixed-UTC `events.Rule`.
"""

import dataclasses
import json
import os
import sys

from aws_cdk import (
    Duration,
    Stack,
    aws_cloudwatch as cloudwatch,
    aws_cloudwatch_actions as cw_actions,
    aws_dynamodb as dynamodb,
    aws_events as events,
    aws_events_targets as targets,
    aws_iam as iam,
    aws_lambda as _lambda,
    aws_logs as logs,
    aws_s3 as s3,
    aws_scheduler as scheduler,
    aws_sns as sns,
    aws_sqs as sqs,
)
from constructs import Construct

# ── The ONE code bundle (#781) ────────────────────────────────────────────────
# All function code stages through deploy/build_bundle.py so CDK, hot deploys,
# and fleet deploys ship byte-identical bundles. Staged once per synth process.
_DEPLOY_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "deploy"))
if _DEPLOY_DIR not in sys.path:
    sys.path.insert(0, _DEPLOY_DIR)
import build_bundle  # noqa: E402

from stacks import schedule_table  # noqa: E402  — #4284, the ONE schedule table

# ── Enrollment by construction (#2846) ────────────────────────────────────────
# Importing by module path rather than package-relative: cdk/app.py puts
# cdk/ on sys.path and imports `stacks.<name>`, and this module is also read
# directly by the CI guard, which has no CDK install.
from stacks.constants import log_retention_days_for  # noqa: E402  — #3278, see _RETENTION_DAYS_TO_ENUM below
from stacks.lambda_enrollment import record, validate_enrollment  # noqa: E402

# ── Log retention by construction (#3278) ─────────────────────────────────────
# The tier is DERIVED from the registry in stacks/constants.py, never passed per call
# site: a kwarg is a thing a future create_platform_lambda caller forgets, and the
# forgotten case would silently land at the default tier — the exact way the documented
# 90-day security tier spent three months as 30. The dict lookup fails CLOSED at synth
# (KeyError) if the registry ever declares a day-count with no RetentionDays member.
_RETENTION_DAYS_TO_ENUM = {
    14: logs.RetentionDays.TWO_WEEKS,
    30: logs.RetentionDays.ONE_MONTH,
    90: logs.RetentionDays.THREE_MONTHS,
}

_TREE_STAGE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "_bundle_staging"))
_staged = {"tree": False}


def staged_tree_asset():
    """Return the shared full-tree Code asset, staging it on first call."""
    if not _staged["tree"]:
        build_bundle.stage_tree(_TREE_STAGE)
        _staged["tree"] = True
    return _lambda.Code.from_asset(_TREE_STAGE)


@dataclasses.dataclass(frozen=True)
class TableSchedule:
    """One config/schedules.json row, resolved (#4284): the expression, the zone it runs in (None =
    fixed UTC: a `rate(...)` or a UTC opt-out with its `utc_reason`), and the enabled state."""

    key: str
    expression: str
    timezone: str | None
    enabled: bool


def table_schedule(key: str) -> TableSchedule:
    """The row for a schedule built beside the factory, from config/schedules.json (#4284). The key
    is `<function-name>#<ConstructId>`; a missing row fails the synth naming the file. Pass it to
    `add_table_schedule(..., schedule=table_schedule("<key>"))` — the one carrier builder."""
    row = schedule_table.entry(key)
    return TableSchedule(key, row["expression"], schedule_table.zone(row), bool(row.get("enabled", True)))


def table_enabled(key: str) -> bool:
    """The `enabled` state the table records for a schedule built beside the factory (default True)."""
    return table_schedule(key).enabled


#: Logical-id suffix of a zoned schedule. A string, not a zone claim: `DailyBriefPacificSchedule`
#: has been live since 2026-10-18, and a renamed logical id is a CloudFormation REPLACEMENT.
ZONED_SCHEDULE_SUFFIX = "PacificSchedule"
SCHEDULER_ROLE_ID = "PlatformSchedulerRole"


def _scheduler_role(scope) -> iam.Role:
    """The ONE EventBridge Scheduler role of `scope`'s stack (#4284, ADR-165): assumable only by
    scheduler.amazonaws.com from this account, holding only `lambda:InvokeFunction`, scoped to the
    ARNs of the functions this stack schedules (each zoned schedule adds its target's ARN; CDK's
    `minimizePolicies` folds them into one statement). Replaces the per-schedule role of 10-18."""
    stack = Stack.of(scope)
    role = stack.node.try_find_child(SCHEDULER_ROLE_ID)
    if role is None:
        role = iam.Role(
            stack,
            SCHEDULER_ROLE_ID,
            assumed_by=iam.PrincipalWithConditions(
                iam.ServicePrincipal("scheduler.amazonaws.com"),
                {"StringEquals": {"aws:SourceAccount": stack.account}},
            ),
            description=f"EventBridge Scheduler -> {stack.stack_name} scheduled functions (#4284); invoke only",
        )
        role._lp_invoke_targets = set()  # type: ignore[attr-defined]
    if not hasattr(role, "_lp_invoke_targets"):
        raise TypeError(f"{SCHEDULER_ROLE_ID} in {stack.stack_name} is not the platform scheduler role")
    return role


def _grant_scheduler_invoke(scope, fn) -> iam.Role:
    role = _scheduler_role(scope)
    if fn.node.path not in role._lp_invoke_targets:
        role.add_to_policy(iam.PolicyStatement(actions=["lambda:InvokeFunction"], resources=[fn.function_arn]))
        role._lp_invoke_targets.add(fn.node.path)
    return role


def _scheduled_event_envelope(stack: Stack, fn) -> str:
    """The input a zoned schedule with no constant input delivers: EventBridge's scheduled-event
    envelope, field for field, with Scheduler's context attributes in place of the rule's values.
    Without it Scheduler sends its own default notification, and every handler that branches on
    the rule's shape reads a manual invoke — mcp/handler.py runs the nightly warmer only on
    `source == "aws.events"` / `detail-type == "Scheduled Event"`; chronicle-approve and
    closure_probe_qa key their scheduled mode on `source`; the DLQ consumer resolves the failed
    function from `resources` (the function ARN rides there, since a schedule ARN is not a rule)."""
    return stack.to_json_string(
        {
            "version": "0",
            "id": "<aws.scheduler.execution-id>",
            "detail-type": "Scheduled Event",
            "source": "aws.events",
            "account": stack.account,
            "time": "<aws.scheduler.scheduled-time>",
            "region": stack.region,
            "resources": ["<aws.scheduler.schedule-arn>", fn.function_arn],
            "detail": {},
        }
    )


def _add_zoned_schedule(scope, id, fn, schedule, timezone, schedule_input=None, *, enabled=True, description=None, name=None):
    """EventBridge Scheduler carrier for ONE zoned schedule (#4284): wall-clock `schedule` in
    `timezone`, invoked through the stack's ONE scheduler role. Two async attempts inside a one-hour
    event age (Scheduler's default is 185 attempts over 24 h — a run delivered a day late is worse
    than a missed one, and each job's own ledger is the dedup for the retry)."""
    stack = Stack.of(scope)
    role = _grant_scheduler_invoke(scope, fn)
    payload = json.dumps(schedule_input) if schedule_input is not None else _scheduled_event_envelope(stack, fn)
    target = scheduler.CfnSchedule.TargetProperty(
        arn=fn.function_arn,
        role_arn=role.role_arn,
        retry_policy=scheduler.CfnSchedule.RetryPolicyProperty(maximum_retry_attempts=2, maximum_event_age_in_seconds=3600),
        input=payload,
    )
    sched = scheduler.CfnSchedule(
        scope,
        f"{id}{ZONED_SCHEDULE_SUFFIX}",
        flexible_time_window=scheduler.CfnSchedule.FlexibleTimeWindowProperty(mode="OFF"),
        schedule_expression=schedule,
        schedule_expression_timezone=timezone,
        state="ENABLED" if enabled else "DISABLED",
        target=target,
        description=(description or f"{fn.function_name} at {schedule} {timezone} (#4284)")[:500],
        **({"name": name} if name else {}),
    )
    sched.node.add_dependency(role)
    return sched


def add_table_schedule(
    scope,
    id: str,
    *,
    target: _lambda.IFunction,
    schedule: TableSchedule,
    schedule_input: dict = None,
    description: str = None,
    name: str = None,
):
    """A schedule built BESIDE the factory (#4284): a second schedule on a function, a constant
    input, a disabled or a named one. `schedule` is `table_schedule("<function>#<ConstructId>")`.
    A zoned row becomes an EventBridge Scheduler schedule on the stack's one scheduler role; a
    fixed-UTC row (a rate, or a UTC opt-out) stays an `events.Rule` with a Lambda target."""
    if schedule.timezone:
        return _add_zoned_schedule(
            scope,
            id,
            target,
            schedule.expression,
            schedule.timezone,
            schedule_input,
            enabled=schedule.enabled,
            description=description,
            name=name,
        )
    rule = events.Rule(
        scope,
        id,
        schedule=events.Schedule.expression(schedule.expression),
        description=description,
        rule_name=name,
        enabled=schedule.enabled,
    )
    rule.add_target(
        targets.LambdaFunction(target, event=events.RuleTargetInput.from_object(schedule_input))
        if schedule_input is not None
        else targets.LambdaFunction(target)
    )
    return rule


def create_platform_lambda(
    scope: Construct,
    id: str,
    function_name: str,
    source_file: str,
    handler: str,
    table: dynamodb.ITable,
    bucket: s3.IBucket,
    dlq: sqs.IQueue = None,
    alerts_topic: sns.ITopic = None,
    digest_topic: sns.ITopic = None,
    digest: bool = False,
    alarm_name: str = None,
    secrets: list[str] = None,
    # #4284: NO `schedule=` / `schedule_timezone=` here — the schedule is this function's row in
    # config/schedules.json, read below by function_name. A zoned row (every cron row follows the
    # table's `platform_timezone`, ADR-165) is an EventBridge Scheduler schedule — wall-clock time,
    # follows the DST change; a rate or a UTC opt-out (`utc_reason`) is the fixed-UTC rule.
    schedule_input: dict = None,  # constant event for the scheduled target; None = EventBridge's own event
    timeout_seconds: int = 120,
    memory_mb: int = 256,
    environment: dict = None,
    additional_layers: list = None,  # third-party dependency layers ONLY (garth, pillow)
    # ── Legacy parameter (DEPRECATED — use custom_policies instead) ──
    existing_role_arn: str = None,
    # ── Fine-grained IAM (v2.0) ──
    custom_policies: list[iam.PolicyStatement] = None,
    # ── Legacy broad-permission flags (used when neither existing_role_arn nor custom_policies) ──
    ddb_write: bool = True,
    s3_write: bool = True,
    needs_ses: bool = False,
    ses_domain: str = None,
    # ── Code override ──
    code: _lambda.Code = None,  # Override code asset (default: Code.from_asset("../lambdas"))
    # ── Async invoke retry (EventBridge-triggered Lambdas) ──
    # None = AWS default (2). Set 0 for sources where a failed run must NOT be
    # auto-retried — e.g. Garmin, whose failures are OAuth-refresh 429s; retrying
    # re-hammers the throttled endpoint and prolongs the lockout (the source then
    # gap-fills on its next scheduled run anyway).
    retry_attempts: int = None,
    # ── Per-Lambda error alarm ──
    # 2026-05-29: ingestion Lambdas set error_alarm=False — their ~46 per-Lambda
    # ingestion-error-* alarms ($4.60/mo) are replaced by ONE metric-math
    # aggregate in monitoring_stack. The remediation agent provides per-Lambda
    # diagnosis from logs, so per-Lambda alarms add cost without much signal.
    error_alarm: bool = True,
    # ── Observability ──
    # ADR-058 follow-up (2026-05-24): default to ACTIVE so all Lambdas emit X-Ray
    # traces. ~$0.50/month for this platform's volume. Enables distributed-tracing
    # debugging of multi-hop chains (ingest → enrich → DDB → site-api).
    # Pass _lambda.Tracing.PASS_THROUGH explicitly to opt out for a specific Lambda.
    tracing: _lambda.Tracing = _lambda.Tracing.ACTIVE,
) -> _lambda.Function:
    """Create a Lambda function with standard Life Platform conventions.

    IAM role resolution order:
      1. custom_policies → CDK creates role with ONLY these statements + BasicExecution
      2. existing_role_arn → from_role_arn (DEPRECATED, for backward compat only)
      3. Neither → CDK creates role with broad default DDB/S3/Secrets/SES grants

    Returns the Lambda Function construct.
    """

    # ── The schedule, from the ONE table (#4284) ──
    _sched_row = schedule_table.factory_entry(function_name) if isinstance(function_name, str) else None
    schedule = _sched_row["expression"] if _sched_row else None
    schedule_timezone = schedule_table.zone(_sched_row) if _sched_row else None
    if _sched_row:
        _stack_name = Stack.of(scope).stack_name
        if _sched_row["stack"] != _stack_name:
            raise schedule_table.ScheduleTableError(
                f"config/schedules.json[{function_name!r}] says stack {_sched_row['stack']!r} but the function is built in {_stack_name!r}"
            )

    # ── Enrollment gate (#2846) ──
    # Runs BEFORE anything is constructed: a stack that violates E1–E3 does not
    # synthesize, so it cannot deploy, so the drift cannot reach production.
    validate_enrollment(
        function_name=function_name,
        source_file=source_file,
        handler=handler,
        schedule=schedule,
        where=f"{getattr(scope.node, 'id', type(scope).__name__)}/{id}",
    )

    # ── Environment variables ──
    env = {
        "TABLE_NAME": table.table_name,
        "S3_BUCKET": bucket.bucket_name,
        "USER_ID": scope.node.try_get_context("user_id") or "matthew",
        "AWS_REGION_OVERRIDE": scope.node.try_get_context("region") or "us-west-2",
        "EMAIL_RECIPIENT": scope.node.try_get_context("email_recipient") or "lifeplatform@mattsusername.com",
        "EMAIL_SENDER": scope.node.try_get_context("email_sender") or "lifeplatform@mattsusername.com",
    }
    if environment:
        env.update(environment)

    # ── IAM Role ──
    if custom_policies is not None:
        # v2.0: CDK-owned role with explicit least-privilege policies.
        role = iam.Role(
            scope,
            f"{id}Role",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaBasicExecutionRole"),
            ],
        )
        for stmt in custom_policies:
            role.add_to_policy(stmt)
        # DLQ send permission comes from role_policies.py statements AND
        # the Lambda constructor's dead_letter_queue auto-grant. No explicit
        # grant_send_messages needed here.

    elif existing_role_arn:
        # DEPRECATED: Reference existing role by ARN.
        role = iam.Role.from_role_arn(scope, f"{id}Role", existing_role_arn)

    else:
        # Fallback: broad default grants (for new Lambdas not yet audited)
        role = iam.Role(
            scope,
            f"{id}Role",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaBasicExecutionRole"),
            ],
        )

        ddb_actions = (
            [
                "dynamodb:GetItem",
                "dynamodb:PutItem",
                "dynamodb:UpdateItem",
                "dynamodb:DeleteItem",
                "dynamodb:Query",
                "dynamodb:Scan",
                "dynamodb:BatchGetItem",
                "dynamodb:BatchWriteItem",
            ]
            if ddb_write
            else [
                "dynamodb:GetItem",
                "dynamodb:Query",
                "dynamodb:Scan",
                "dynamodb:BatchGetItem",
            ]
        )
        role.add_to_policy(
            iam.PolicyStatement(
                actions=ddb_actions,
                resources=[table.table_arn, f"{table.table_arn}/index/*"],
            )
        )

        s3_actions = (
            [
                "s3:GetObject",
                "s3:PutObject",
                "s3:DeleteObject",
                "s3:ListBucket",
            ]
            if s3_write
            else [
                "s3:GetObject",
                "s3:ListBucket",
            ]
        )
        role.add_to_policy(
            iam.PolicyStatement(
                actions=s3_actions,
                resources=[bucket.bucket_arn, f"{bucket.bucket_arn}/*"],
            )
        )

        if secrets:
            for secret_id in secrets:
                role.add_to_policy(
                    iam.PolicyStatement(
                        actions=["secretsmanager:GetSecretValue", "secretsmanager:UpdateSecret"],
                        resources=[f"arn:aws:secretsmanager:*:*:secret:{secret_id}-*"],
                    )
                )

        if needs_ses and ses_domain:
            role.add_to_policy(
                iam.PolicyStatement(
                    actions=["ses:SendEmail", "ses:SendRawEmail"],
                    resources=[f"arn:aws:ses:*:*:identity/{ses_domain}"],
                )
            )

        if dlq:
            dlq.grant_send_messages(role)

    # Budget guardrail: every CDK-owned-role Lambda can read the budget tier
    # (budget_guard.py) so the cost-governor's tier drives graceful AI
    # degradation + the bedrock_client Tier-3 hard stop. Tiny read on two SSM
    # params (#822 added budget-breakdown, the display-only projection detail
    # behind the daily brief's headroom line — read via the same budget_guard
    # module). Skipped for imported roles (from_role_arn can't be modified by CDK).
    if existing_role_arn is None:
        role.add_to_policy(
            iam.PolicyStatement(
                actions=["ssm:GetParameter"],
                resources=[
                    "arn:aws:ssm:*:*:parameter/life-platform/budget-tier",
                    "arn:aws:ssm:*:*:parameter/life-platform/budget-breakdown",
                ],
            )
        )

    # ── Lambda Function ──
    # When using an existing role (from_role_arn), we must NOT pass dead_letter_queue
    # to the Function constructor — CDK automatically calls grant_send_messages which
    # generates an AWS::IAM::Policy that causes import issues.
    # For custom_policies, DLQ grant is handled above, so we CAN pass it normally.
    use_dlq_constructor = (custom_policies is not None or existing_role_arn is None) and dlq is not None

    fn = _lambda.Function(
        scope,
        id,
        function_name=function_name,
        runtime=_lambda.Runtime.PYTHON_3_12,
        handler=handler,
        code=code if code else staged_tree_asset(),
        role=role,
        timeout=Duration.seconds(timeout_seconds),
        memory_size=memory_mb,
        environment=env,
        dead_letter_queue=dlq if use_dlq_constructor else None,
        layers=additional_layers or [],
        tracing=tracing,  # R13-XR: None = CDK default (PASS_THROUGH); ACTIVE = X-Ray
        # V2 P2.3 (2026-05-17): default 30-day retention on log groups created
        # by CDK for new Lambdas. Prevents indefinite log accumulation
        # (was the drift class that re-emerged with coach-observatory-renderer
        # and life-platform-delete-user-data on 2026-05-17).
        # #3278: the tier comes from the ONE registry (stacks/constants.py) — the
        # security-tier functions get docs/DATA_GOVERNANCE.md's 90 days by construction.
        log_retention=_RETENTION_DAYS_TO_ENUM[log_retention_days_for(function_name)],
        **({"retry_attempts": retry_attempts} if retry_attempts is not None else {}),
    )

    # Set DLQ via L1 escape hatch when using existing role — avoids auto-grant.
    if existing_role_arn and dlq:
        cfn_fn = fn.node.default_child
        cfn_fn.dead_letter_config = _lambda.CfnFunction.DeadLetterConfigProperty(target_arn=dlq.queue_arn)

    # ── EventBridge schedule ──
    if schedule and schedule_timezone:
        _add_zoned_schedule(scope, id, fn, schedule, schedule_timezone, schedule_input)
    elif schedule:
        rule = events.Rule(
            scope,
            f"{id}Schedule",
            schedule=events.Schedule.expression(schedule),
        )
        # `schedule_input` sends a CONSTANT event instead of EventBridge's own. It exists
        # because a handler that reads a flag off its event gets the DEFAULT on a scheduled
        # run, and the default is whatever the code says — not whatever the operator
        # assumes. #3741: recap-card-generator reads `event.get("deliver", True)`, the rule
        # passed no input, and so the schedule delivered. Naming the flag on the rule makes
        # the scheduled behaviour readable in the stack instead of inferable from a default.
        rule.add_target(
            targets.LambdaFunction(fn, event=events.RuleTargetInput.from_object(schedule_input))
            if schedule_input is not None
            else targets.LambdaFunction(fn)
        )

    # ── CloudWatch error alarm ──
    # ADR-050: alarms route to one of two SNS topics based on `digest` flag.
    #   digest=False (default) → urgent topic (immediate email)
    #   digest=True            → digest topic (batched into daily 8am PT email)
    # Pass `digest_topic` alongside `alerts_topic` to enable digest routing.
    # NOTE: alerts_topic=None still disables alarms entirely — preserves the
    # existing opt-out pattern used by sources where no alarm is desired.
    _selected_topic = None
    _enrolled_alarm_name = None
    if alerts_topic is not None:
        _selected_topic = digest_topic if (digest and digest_topic is not None) else alerts_topic
    if _selected_topic and error_alarm:
        _alarm_name = alarm_name if alarm_name else f"ingestion-error-{function_name}"
        _enrolled_alarm_name = _alarm_name
        # 2026-05-03 v6.9.2: period reduced 24h → 1h. Old window kept alarms in
        # ALARM state for 24h on a single transient error, and re-emailed if
        # set-alarm-state was overridden during evaluation. 1h window means a
        # transient blip self-clears within an hour; sustained failures still
        # re-fire as new errors arrive. Net: less inbox noise, same signal.
        alarm = fn.metric_errors(
            period=Duration.hours(1),
            statistic="Sum",
        ).create_alarm(
            scope,
            f"{id}ErrorAlarm",
            alarm_name=_alarm_name,
            evaluation_periods=1,
            threshold=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )
        alarm.add_alarm_action(cw_actions.SnsAction(_selected_topic))
        # OK actions intentionally omitted — inbox should only receive actionable alerts

    # ── Enrollment census (#2846) ──
    # The construction is now a registry row: after `cdk synth` walks cdk/app.py,
    # lambda_enrollment.ENROLLED IS the platform's Lambda set, with the alarm
    # posture this call actually produced (not the one the call site asked for).
    record(
        function_name=function_name,
        source_file=source_file,
        handler=handler,
        stack=getattr(scope.node, "id", type(scope).__name__),
        logical_id=id,
        schedule=schedule,
        alarm_name=_enrolled_alarm_name,
    )

    return fn
