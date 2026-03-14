"""
McpStack — MCP server Lambda + Function URL + WAF + alarms.

v2.0 (v3.4.0): CDK-managed IAM role replaces existing_role_arn reference.
v2.1 (v3.7.9): TB7-26 — WAF WebACL (REGIONAL) with rate-based rule attached to
  MCP Lambda Function URL. Blocks IPs exceeding 1000 requests per 5-minute window.
  Cost: ~$5/month (1 WebACL + 1 rule + requests processed).
"""

import aws_cdk as cdk
from aws_cdk import (
    Stack, Duration,
    aws_lambda as _lambda, aws_iam as iam,
    aws_cloudwatch as cloudwatch, aws_cloudwatch_actions as cw_actions,
    aws_dynamodb as dynamodb, aws_s3 as s3, aws_sqs as sqs, aws_sns as sns,
    aws_wafv2 as wafv2,
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
MCP_FUNCTION_ARN     = f"arn:aws:lambda:{REGION}:{ACCT}:function:{MCP_FUNCTION_NAME}"

def _rule_arn(name): return f"arn:aws:events:{REGION}:{ACCT}:rule/{name}"


class McpStack(Stack):
    def __init__(self, scope, construct_id, table, bucket, **kwargs):
        super().__init__(scope, construct_id, **kwargs)
        local_table        = dynamodb.Table.from_table_name(self, "LifePlatformTable", LIFE_PLATFORM_TABLE)
        local_bucket       = s3.Bucket.from_bucket_name(self, "LifePlatformBucket", LIFE_PLATFORM_BUCKET)
        local_alerts_topic = sns.Topic.from_topic_arn(self, "AlertsTopic", ALERTS_TOPIC_ARN)

        mcp = create_platform_lambda(self, "McpServer", function_name=MCP_FUNCTION_NAME, source_file="lambdas/mcp_server.py", handler="mcp_server.lambda_handler", timeout_seconds=300, memory_mb=512, environment={"DEPLOY_VERSION": "2.74.0"}, custom_policies=rp.mcp_server(), table=local_table, bucket=local_bucket, dlq=None, alerts_topic=None)
        mcp.add_permission("EBNightlyWarmer", principal=iam.ServicePrincipal("events.amazonaws.com"), source_arn=_rule_arn("life-platform-nightly-warmer"))

        # Function URL: deliberately NOT CDK-managed.
        # Existing URL has 4 resource-based policy statements including duplicates;
        # importing would create conflicting permissions. The URL never changes.
        # URL: https://c5hljblvma4u2xd6wf6oe4clk40unthu.lambda-url.us-west-2.on.aws/

        # ── WAF WebACL — rate-based protection for MCP Function URL (TB7-26) ──
        # REGIONAL scope required for Lambda Function URL associations.
        # Rate limit: 1000 requests per 5-minute window per source IP.
        # Default action: ALLOW (WAF only blocks rate-exceeded IPs).
        # Cost: ~$1/month WebACL + ~$1/month rule + $0.60/million requests processed.
        mcp_waf_acl = wafv2.CfnWebACL(
            self, "McpRateLimitACL",
            name="life-platform-mcp-rate-limit",
            scope="REGIONAL",
            default_action=wafv2.CfnWebACL.DefaultActionProperty(allow={}),
            visibility_config=wafv2.CfnWebACL.VisibilityConfigProperty(
                cloud_watch_metrics_enabled=True,
                metric_name="McpRateLimitACL",
                sampled_requests_enabled=True,
            ),
            rules=[
                wafv2.CfnWebACL.RuleProperty(
                    name="McpRateLimit",
                    priority=1,
                    action=wafv2.CfnWebACL.RuleActionProperty(
                        block=wafv2.CfnWebACL.BlockActionProperty(
                            custom_response=wafv2.CfnWebACL.CustomResponseProperty(
                                response_code=429,
                            )
                        )
                    ),
                    visibility_config=wafv2.CfnWebACL.VisibilityConfigProperty(
                        cloud_watch_metrics_enabled=True,
                        metric_name="McpRateLimit",
                        sampled_requests_enabled=True,
                    ),
                    statement=wafv2.CfnWebACL.StatementProperty(
                        rate_based_statement=wafv2.CfnWebACL.RateBasedStatementProperty(
                            limit=1000,
                            aggregate_key_type="IP",
                        )
                    ),
                )
            ],
        )

        # Associate WAF WebACL with the MCP Lambda Function URL.
        # resource_arn must be the Lambda function ARN (not the Function URL string).
        # The Function URL is identified by AWS WAF via the function ARN association.
        wafv2.CfnWebACLAssociation(
            self, "McpFunctionUrlWafAssociation",
            resource_arn=MCP_FUNCTION_ARN,
            web_acl_arn=mcp_waf_acl.attr_arn,
        )

        # CloudWatch alarm: WAF blocked requests (rate limit hits)
        waf_block_alarm = cloudwatch.Alarm(
            self, "McpWafBlockedAlarm",
            alarm_name="mcp-waf-rate-limit-blocks",
            metric=cloudwatch.Metric(
                namespace="AWS/WAFV2",
                metric_name="BlockedRequests",
                dimensions_map={
                    "WebACL": "life-platform-mcp-rate-limit",
                    "Region": REGION,
                    "Rule": "McpRateLimit",
                },
                period=Duration.seconds(3600),
                statistic="Sum",
            ),
            evaluation_periods=1,
            threshold=10,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )
        waf_block_alarm.add_alarm_action(cw_actions.SnsAction(local_alerts_topic))

        duration_alarm = cloudwatch.Alarm(self, "McpDurationHighAlarm", alarm_name="mcp-server-duration-high", metric=cloudwatch.Metric(namespace="AWS/Lambda", metric_name="Duration", dimensions_map={"FunctionName": MCP_FUNCTION_NAME}, period=Duration.seconds(86400), statistic="p99"), evaluation_periods=1, threshold=240000, comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD, treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING)
        duration_alarm.add_alarm_action(cw_actions.SnsAction(local_alerts_topic))

        slo_alarm = cloudwatch.Alarm(self, "SloMcpAvailabilityAlarm", alarm_name="slo-mcp-availability", metric=cloudwatch.Metric(namespace="AWS/Lambda", metric_name="Errors", dimensions_map={"FunctionName": MCP_FUNCTION_NAME}, period=Duration.seconds(3600), statistic="Sum"), evaluation_periods=1, threshold=3, comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD, treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING)
        slo_alarm.add_alarm_action(cw_actions.SnsAction(local_alerts_topic))

        cdk.CfnOutput(self, "McpFunctionArn", value=mcp.function_arn, description="MCP server Lambda ARN")
        cdk.CfnOutput(self, "McpFunctionUrl", value="https://c5hljblvma4u2xd6wf6oe4clk40unthu.lambda-url.us-west-2.on.aws/", description="MCP server Function URL (unmanaged)")
        cdk.CfnOutput(self, "McpWafAclArn", value=mcp_waf_acl.attr_arn, description="MCP WAF WebACL ARN")
