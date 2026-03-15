"""
McpStack — MCP server Lambda + Function URL + alarms.

v2.0 (v3.4.0): CDK-managed IAM role replaces existing_role_arn reference.
v2.1 (v3.7.9): TB7-26 — WAF attempted but not viable. AWS WAFv2 associate-web-acl
  does not support Lambda Function URLs as a resource type (supported: ALB, API GW,
  AppSync, Cognito, App Runner, Verified Access). WebACL was created and rolled back.
  Alternative: MCP Function URL is protected by HMAC Bearer auth; unauthenticated
  requests fail at the Lambda handler before any meaningful processing. The existing
  slo-mcp-availability alarm (≥3 errors/hour → SNS) covers runaway behavior.
  TB7-26 closed as N/A.
v2.2 (v3.7.22): R9 hardening — dedicated warmer Lambda (life-platform-mcp-warmer)
  separated from request-serving MCP Lambda. Warmer has 300s timeout; MCP Lambda
  stays at 300s for tool requests. SLO-5 warmer alarm added.
"""

import aws_cdk as cdk
from aws_cdk import (
    Stack, Duration,
    aws_lambda as _lambda, aws_iam as iam,
    aws_events as events, aws_events_targets as targets,
    aws_cloudwatch as cloudwatch, aws_cloudwatch_actions as cw_actions,
    aws_dynamodb as dynamodb, aws_s3 as s3, aws_sqs as sqs, aws_sns as sns,
)
from constructs import Construct
from stacks.lambda_helpers import create_platform_lambda
from stacks import role_policies as rp

REGION = "us-west-2"
ACCT = "205930651321"
LIFE_PLATFORM_TABLE  = "life-platform"
LIFE_PLATFORM_BUCKET = "matthew-life-platform"
ALERTS_TOPIC_ARN     = f"arn:aws:sns:{REGION}:{ACCT}:life-platform-alerts"
MCP_FUNCTION_NAME    = "life-platform-mcp"
WARMER_FUNCTION_NAME = "life-platform-mcp-warmer"

def _rule_arn(name): return f"arn:aws:events:{REGION}:{ACCT}:rule/{name}"


class McpStack(Stack):
    def __init__(self, scope, construct_id, table, bucket, **kwargs):
        super().__init__(scope, construct_id, **kwargs)
        local_table        = dynamodb.Table.from_table_name(self, "LifePlatformTable", LIFE_PLATFORM_TABLE)
        local_bucket       = s3.Bucket.from_bucket_name(self, "LifePlatformBucket", LIFE_PLATFORM_BUCKET)
        local_alerts_topic = sns.Topic.from_topic_arn(self, "AlertsTopic", ALERTS_TOPIC_ARN)

        # ── MCP Server Lambda (request-serving) ───────────────────────────────
        # R13-XR: ACTIVE tracing enables X-Ray for every invocation.
        # Lambda runtime auto-instruments boto3 calls (DDB queries, Secrets reads)
        # without requiring aws_xray_sdk in the package. Subsegments for each
        # DDB query appear in the X-Ray service map, enabling per-query latency
        # diagnosis that previously required CloudWatch log parsing.
        mcp = create_platform_lambda(self, "McpServer",
            function_name=MCP_FUNCTION_NAME,
            source_file="lambdas/mcp_server.py",
            handler="mcp_server.lambda_handler",
            timeout_seconds=300,
            memory_mb=768,  # R5: power-tuned — 768 MB is cost-optimal (AWS Lambda Power Tuning v4.4.0)
            tracing=_lambda.Tracing.ACTIVE,  # R13-XR: X-Ray active tracing
            environment={"DEPLOY_VERSION": "2.74.0"},
            custom_policies=rp.mcp_server(),
            table=local_table, bucket=local_bucket, dlq=None, alerts_topic=None)

        # Existing EventBridge permission kept for legacy nightly-warmer rule.
        # The new dedicated warmer Lambda (below) is the primary warmer from v3.7.22.
        # The old rule is left in place to avoid CDK drift during transition.
        mcp.add_permission("EBNightlyWarmer",
            principal=iam.ServicePrincipal("events.amazonaws.com"),
            source_arn=_rule_arn("life-platform-nightly-warmer"))

        # Function URL: deliberately NOT CDK-managed.
        # Existing URL has 4 resource-based policy statements including duplicates;
        # importing would create conflicting permissions. The URL never changes.
        # URL: https://c5hljblvma4u2xd6wf6oe4clk40unthu.lambda-url.us-west-2.on.aws/

        # ── Dedicated Cache Warmer Lambda (R9 hardening) ──────────────────────
        # Separated from MCP request-serving Lambda so a 90s warm run does not
        # hold MCP concurrency. Same mcp_server.py source; warmer event triggers
        # the nightly_cache_warmer() path inside mcp/handler.py.
        # Uses same IAM policy as MCP server (reads same DDB partitions, writes cache).
        warmer = create_platform_lambda(self, "McpWarmer",
            function_name=WARMER_FUNCTION_NAME,
            source_file="lambdas/mcp_server.py",
            handler="mcp_server.lambda_handler",
            schedule="cron(0 17 * * ? *)",  # 10:00 AM PT daily
            timeout_seconds=300,
            memory_mb=768,  # R5: matched to MCP server power-tuned value
            alarm_name="mcp-warmer-error",
            environment={"DEPLOY_VERSION": "2.74.0"},
            custom_policies=rp.mcp_server(),
            table=local_table, bucket=local_bucket, dlq=None, alerts_topic=local_alerts_topic)

        # ── MCP Server alarms ─────────────────────────────────────────────────
        duration_alarm = cloudwatch.Alarm(self, "McpDurationHighAlarm",
            alarm_name="mcp-server-duration-high",
            metric=cloudwatch.Metric(
                namespace="AWS/Lambda", metric_name="Duration",
                dimensions_map={"FunctionName": MCP_FUNCTION_NAME},
                period=Duration.seconds(86400), statistic="p99"),
            evaluation_periods=1, threshold=240000,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING)
        duration_alarm.add_alarm_action(cw_actions.SnsAction(local_alerts_topic))

        slo_alarm = cloudwatch.Alarm(self, "SloMcpAvailabilityAlarm",
            alarm_name="slo-mcp-availability",
            metric=cloudwatch.Metric(
                namespace="AWS/Lambda", metric_name="Errors",
                dimensions_map={"FunctionName": MCP_FUNCTION_NAME},
                period=Duration.seconds(3600), statistic="Sum"),
            evaluation_periods=1, threshold=3,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING)
        slo_alarm.add_alarm_action(cw_actions.SnsAction(local_alerts_topic))

        # ── SLO-5: Warmer completeness alarm (R9 A+ hardening) ────────────────
        # Fires if the dedicated warmer Lambda errors on its daily run.
        # Warmer failure = tools serve stale cached data silently all day.
        warmer_alarm = cloudwatch.Alarm(self, "SloWarmerCompletenessAlarm",
            alarm_name="slo-warmer-completeness",
            metric=cloudwatch.Metric(
                namespace="AWS/Lambda", metric_name="Errors",
                dimensions_map={"FunctionName": WARMER_FUNCTION_NAME},
                period=Duration.seconds(86400), statistic="Sum"),
            evaluation_periods=1, threshold=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING)
        warmer_alarm.add_alarm_action(cw_actions.SnsAction(local_alerts_topic))

        cdk.CfnOutput(self, "McpFunctionArn", value=mcp.function_arn,
            description="MCP server Lambda ARN")
        cdk.CfnOutput(self, "McpWarmerArn", value=warmer.function_arn,
            description="MCP cache warmer Lambda ARN")
        cdk.CfnOutput(self, "McpFunctionUrl",
            value="https://c5hljblvma4u2xd6wf6oe4clk40unthu.lambda-url.us-west-2.on.aws/",
            description="MCP server Function URL (unmanaged)")
