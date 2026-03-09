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
    alarm_name: str = None,          # override default "ingestion-error-{function_name}"
    secrets: list[str] = None,
    schedule: str = None,
    timeout_seconds: int = 120,
    memory_mb: int = 256,
    environment: dict = None,
    shared_layer: _lambda.ILayerVersion = None,
    additional_layers: list = None,
    ddb_write: bool = True,
    s3_write: bool = True,
    needs_ses: bool = False,
    ses_domain: str = None,
    existing_role_arn: str = None,
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
    if existing_role_arn:
        # Reference existing role by ARN — CDK treats it as immutable.
        # No DefaultPolicy is generated, no DependsOn on Lambda, no import friction.
        # IAM permissions remain managed outside CDK (as-is in AWS).
        role = iam.Role.from_role_arn(scope, f"{id}Role", existing_role_arn)
    else:
        # Create new role (for new Lambdas not yet in AWS)
        role = iam.Role(
            scope, f"{id}Role",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                ),
            ],
        )

        # DynamoDB permissions
        ddb_actions = [
            "dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem",
            "dynamodb:DeleteItem", "dynamodb:Query", "dynamodb:Scan",
            "dynamodb:BatchGetItem", "dynamodb:BatchWriteItem",
        ] if ddb_write else [
            "dynamodb:GetItem", "dynamodb:Query", "dynamodb:Scan", "dynamodb:BatchGetItem",
        ]
        role.add_to_policy(iam.PolicyStatement(
            actions=ddb_actions,
            resources=[table.table_arn, f"{table.table_arn}/index/*"],
        ))

        # S3 permissions
        s3_actions = [
            "s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket",
        ] if s3_write else [
            "s3:GetObject", "s3:ListBucket",
        ]
        role.add_to_policy(iam.PolicyStatement(
            actions=s3_actions,
            resources=[bucket.bucket_arn, f"{bucket.bucket_arn}/*"],
        ))

        # Secrets Manager permissions
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
    # Asset path is ".." (project root) because cdk synth runs from the cdk/ subdir.
    # Excludes prevent bundling venv, cdk artifacts, docs, and deploy scripts.
    # Asset path is "../lambdas" so the zip root = lambdas/ directory.
    # Handler files (e.g. whoop_lambda.py) land at the zip root, which is where
    # Lambda resolves module names from. Using ".." caused files to land at
    # lambdas/whoop_lambda.py inside the zip, breaking all imports (fixed v3.3.6).
    _ASSET_EXCLUDES = [
        "__pycache__", "**/__pycache__/**",
        "*.pyc", "**/*.pyc",
        "*.md",
        "dashboard", "dashboard/**",   # static HTML assets — not Lambda code
        "buddy", "buddy/**",            # static HTML assets — not Lambda code
        "cf-auth", "cf-auth/**",        # CloudFront auth assets
        "requirements", "requirements/**",
        ".DS_Store",
    ]
    # When using an existing role (from_role_arn), we must NOT pass dead_letter_queue
    # to the Function constructor — CDK automatically calls grant_send_messages on the
    # queue when that param is set, which generates an AWS::IAM::Policy attached to the
    # role. That policy creates a DependsOn on the Lambda, causing CloudFormation to
    # reject the import changeset with "Unresolved resource dependencies".
    # Instead, configure the DLQ via the L1 escape hatch (no grant triggered).
    fn = _lambda.Function(
        scope, id,
        function_name=function_name,
        runtime=_lambda.Runtime.PYTHON_3_12,
        handler=handler,
        code=_lambda.Code.from_asset("../lambdas", exclude=_ASSET_EXCLUDES),
        role=role,
        timeout=Duration.seconds(timeout_seconds),
        memory_size=memory_mb,
        environment=env,
        dead_letter_queue=None if existing_role_arn else dlq,
        layers=([shared_layer] if shared_layer else []) + (additional_layers or []),
    )

    # Set DLQ via L1 escape hatch when using existing role — avoids auto-grant.
    if existing_role_arn and dlq:
        cfn_fn = fn.node.default_child
        cfn_fn.dead_letter_config = _lambda.CfnFunction.DeadLetterConfigProperty(
            target_arn=dlq.queue_arn
        )

    # ── EventBridge schedule ──
    # No rule_name — import uses actual AWS name; CDK manages by logical ID after import.
    if schedule:
        rule = events.Rule(
            scope, f"{id}Schedule",
            schedule=events.Schedule.expression(schedule),
        )
        rule.add_target(targets.LambdaFunction(fn))

    # ── CloudWatch error alarm ──
    if alerts_topic:
        _alarm_name = alarm_name if alarm_name else f"ingestion-error-{function_name}"
        alarm = fn.metric_errors(
            period=Duration.hours(24),
            statistic="Sum",
        ).create_alarm(
            scope, f"{id}ErrorAlarm",
            alarm_name=_alarm_name,
            evaluation_periods=1,
            threshold=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )
        alarm.add_alarm_action(cw_actions.SnsAction(alerts_topic))
        alarm.add_ok_action(cw_actions.SnsAction(alerts_topic))

    return fn
