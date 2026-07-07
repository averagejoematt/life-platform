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
        schedule="cron(0 14 * * ? *)",
        timeout_seconds=120,
    )
"""

import os
import sys

from aws_cdk import (
    Duration,
    aws_cloudwatch as cloudwatch,
    aws_cloudwatch_actions as cw_actions,
    aws_dynamodb as dynamodb,
    aws_events as events,
    aws_events_targets as targets,
    aws_iam as iam,
    aws_lambda as _lambda,
    aws_logs as logs,
    aws_s3 as s3,
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

_TREE_STAGE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "_bundle_staging"))
_staged = {"tree": False}


def staged_tree_asset():
    """Return the shared full-tree Code asset, staging it on first call."""
    if not _staged["tree"]:
        build_bundle.stage_tree(_TREE_STAGE)
        _staged["tree"] = True
    return _lambda.Code.from_asset(_TREE_STAGE)


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
    schedule: str = None,
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
    # degradation + the bedrock_client Tier-3 hard stop. Tiny read on one SSM
    # param. Skipped for imported roles (from_role_arn can't be modified by CDK).
    if existing_role_arn is None:
        role.add_to_policy(
            iam.PolicyStatement(
                actions=["ssm:GetParameter"],
                resources=["arn:aws:ssm:*:*:parameter/life-platform/budget-tier"],
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
        log_retention=logs.RetentionDays.ONE_MONTH,
        **({"retry_attempts": retry_attempts} if retry_attempts is not None else {}),
    )

    # Set DLQ via L1 escape hatch when using existing role — avoids auto-grant.
    if existing_role_arn and dlq:
        cfn_fn = fn.node.default_child
        cfn_fn.dead_letter_config = _lambda.CfnFunction.DeadLetterConfigProperty(target_arn=dlq.queue_arn)

    # ── EventBridge schedule ──
    if schedule:
        rule = events.Rule(
            scope,
            f"{id}Schedule",
            schedule=events.Schedule.expression(schedule),
        )
        rule.add_target(targets.LambdaFunction(fn))

    # ── CloudWatch error alarm ──
    # ADR-050: alarms route to one of two SNS topics based on `digest` flag.
    #   digest=False (default) → urgent topic (immediate email)
    #   digest=True            → digest topic (batched into daily 8am PT email)
    # Pass `digest_topic` alongside `alerts_topic` to enable digest routing.
    # NOTE: alerts_topic=None still disables alarms entirely — preserves the
    # existing opt-out pattern used by sources where no alarm is desired.
    _selected_topic = None
    if alerts_topic is not None:
        _selected_topic = digest_topic if (digest and digest_topic is not None) else alerts_topic
    if _selected_topic and error_alarm:
        _alarm_name = alarm_name if alarm_name else f"ingestion-error-{function_name}"
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

    return fn
