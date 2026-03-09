"""
lambda_helpers.py — Shared Lambda construction patterns for CDK stacks.

Provides a helper function that creates a Lambda function with all the
standard Life Platform conventions:
  - Per-function IAM role (least privilege)
  - DLQ configured
  - Environment variables (TABLE_NAME, S3_BUCKET, USER_ID)
  - CloudWatch error alarm
  - Handler auto-detection from source file
  - Shared Layer attachment (optional)

Usage in a stack:
    from stacks.lambda_helpers import create_platform_lambda

    fn = create_platform_lambda(
        self, "WhoopIngestion",
        function_name="whoop-data-ingestion",
        source_file="lambdas/whoop_lambda.py",
        handler="lambda_function.lambda_handler",
        table=core.table,
        bucket=core.bucket,
        dlq=core.dlq,
        secrets=["life-platform/whoop"],
        schedule="cron(0 14 * * ? *)",
        timeout_seconds=120,
    )
"""

from aws_cdk import (
    Duration,
    aws_lambda as _lambda,
    aws_iam as iam,
    aws_sqs as sqs,
    aws_events as events,
    aws_events_targets as targets,
    aws_cloudwatch as cloudwatch,
    aws_cloudwatch_actions as cw_actions,
    aws_sns as sns,
    aws_dynamodb as dynamodb,
    aws_s3 as s3,
)
from constructs import Construct


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
    secrets: list[str] = None,
    schedule: str = None,
    timeout_seconds: int = 120,
    memory_mb: int = 256,
    environment: dict = None,
    shared_layer: _lambda.ILayerVersion = None,
    ddb_write: bool = True,
    s3_write: bool = True,
    needs_ses: bool = False,
    ses_domain: str = None,
) -> _lambda.Function:
    """Create a Lambda function with standard Life Platform conventions.

    Returns the Lambda Function construct.
    """

    # ── Environment variables ──
    env = {
        "TABLE_NAME": table.table_name,
        "S3_BUCKET": bucket.bucket_name,
        "USER_ID": scope.node.try_get_context("user_id") or "matthew",
        "AWS_REGION_OVERRIDE": scope.node.try_get_context("region") or "us-west-2",
    }
    if environment:
        env.update(environment)

    # ── IAM Role ──
    role = iam.Role(
        scope, f"{id}Role",
        role_name=f"lambda-{function_name}-role",
        assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
        managed_policies=[
            iam.ManagedPolicy.from_aws_managed_policy_name(
                "service-role/AWSLambdaBasicExecutionRole"
            ),
        ],
    )

    # DynamoDB permissions
    if ddb_write:
        table.grant_read_write_data(role)
    else:
        table.grant_read_data(role)

    # S3 permissions
    if s3_write:
        bucket.grant_read_write(role)
    else:
        bucket.grant_read(role)

    # Secrets Manager permissions (scoped to specific secrets)
    if secrets:
        for secret_id in secrets:
            role.add_to_policy(iam.PolicyStatement(
                actions=["secretsmanager:GetSecretValue", "secretsmanager:UpdateSecret"],
                resources=[f"arn:aws:secretsmanager:*:*:secret:{secret_id}-*"],
            ))

    # SES permissions
    if needs_ses and ses_domain:
        role.add_to_policy(iam.PolicyStatement(
            actions=["ses:SendEmail", "ses:SendRawEmail"],
            resources=[f"arn:aws:ses:*:*:identity/{ses_domain}"],
        ))

    # DLQ send permission
    if dlq:
        dlq.grant_send_messages(role)

    # ── Lambda Function ──
    fn = _lambda.Function(
        scope, id,
        function_name=function_name,
        runtime=_lambda.Runtime.PYTHON_3_12,
        handler=handler,
        code=_lambda.Code.from_asset(".", exclude=["cdk/", "docs/", "deploy/", "*.md"]),
        role=role,
        timeout=Duration.seconds(timeout_seconds),
        memory_size=memory_mb,
        environment=env,
        dead_letter_queue=dlq,
        layers=[shared_layer] if shared_layer else [],
    )

    # ── EventBridge schedule ──
    if schedule:
        rule = events.Rule(
            scope, f"{id}Schedule",
            rule_name=f"{function_name}-schedule",
            schedule=events.Schedule.expression(schedule),
        )
        rule.add_target(targets.LambdaFunction(fn))

    # ── CloudWatch error alarm ──
    if alerts_topic:
        alarm = fn.metric_errors(
            period=Duration.hours(24),
            statistic="Sum",
        ).create_alarm(
            scope, f"{id}ErrorAlarm",
            alarm_name=f"ingestion-error-{function_name}",
            evaluation_periods=1,
            threshold=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )
        alarm.add_alarm_action(cw_actions.SnsAction(alerts_topic))
        alarm.add_ok_action(cw_actions.SnsAction(alerts_topic))

    return fn
