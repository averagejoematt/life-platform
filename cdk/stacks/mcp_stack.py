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
    Duration,
    Stack,
    aws_cloudwatch as cloudwatch,
    aws_cloudwatch_actions as cw_actions,
    aws_dynamodb as dynamodb,
    aws_events as events,
    aws_events_targets as targets,
    aws_iam as iam,
    aws_lambda as _lambda,
    aws_s3 as s3,
    aws_sns as sns,
)

from stacks import role_policies as rp
from stacks.constants import TABLE_NAME  # CONF-01 / #936: one source for the table name (DR cutover)
from stacks.lambda_helpers import create_platform_lambda

REGION = "us-west-2"
ACCT = "205930651321"
LIFE_PLATFORM_TABLE = TABLE_NAME
LIFE_PLATFORM_BUCKET = "matthew-life-platform"
ALERTS_TOPIC_ARN = f"arn:aws:sns:{REGION}:{ACCT}:life-platform-alerts"
DIGEST_TOPIC_ARN = f"arn:aws:sns:{REGION}:{ACCT}:life-platform-alerts-digest"
MCP_FUNCTION_NAME = "life-platform-mcp"
WARMER_FUNCTION_NAME = "life-platform-mcp-warmer"


def _rule_arn(name):
    return f"arn:aws:events:{REGION}:{ACCT}:rule/{name}"


class McpStack(Stack):
    def __init__(self, scope, construct_id, table, bucket, **kwargs):
        super().__init__(scope, construct_id, **kwargs)
        local_table = dynamodb.Table.from_table_name(self, "LifePlatformTable", LIFE_PLATFORM_TABLE)
        local_bucket = s3.Bucket.from_bucket_name(self, "LifePlatformBucket", LIFE_PLATFORM_BUCKET)
        local_alerts_topic = sns.Topic.from_topic_arn(self, "AlertsTopic", ALERTS_TOPIC_ARN)
        local_digest_topic = sns.Topic.from_topic_arn(self, "DigestTopic", DIGEST_TOPIC_ARN)

        # ── MCP code asset (#781) ─────────────────────────────────────────────
        # MCP Lambda lives at repo root (mcp_server.py + mcp/ package), not in
        # lambdas/. The bundle is the SAME staged full tree every other function
        # gets (shared modules flat, reading/ package, food_vocabulary.json) PLUS
        # mcp_server.py + mcp/ — staged by the one bundle implementation in
        # deploy/build_bundle.py. This retires the shared-layer dependency
        # (ADR-066 hevy routine modules, numeric/retry_utils) and the
        # hand-curated staging that kept re-breaking (reading/ omitted from the
        # CI zip; hevy modules only on the layer).
        import os
        import sys

        _deploy_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "deploy"))
        if _deploy_dir not in sys.path:
            sys.path.insert(0, _deploy_dir)
        import build_bundle

        _stage = os.path.join(os.path.dirname(__file__), "..", "_mcp_staging")
        build_bundle.stage_mcp(_stage)
        mcp_code = _lambda.Code.from_asset(_stage)

        # ── MCP Server Lambda (request-serving) ───────────────────────────────
        # R13-XR: ACTIVE tracing enables X-Ray for every invocation.
        # Lambda runtime auto-instruments boto3 calls (DDB queries, Secrets reads)
        # without requiring aws_xray_sdk in the package. Subsegments for each
        # DDB query appear in the X-Ray service map, enabling per-query latency
        # diagnosis that previously required CloudWatch log parsing.
        mcp = create_platform_lambda(
            self,
            "McpServer",
            function_name=MCP_FUNCTION_NAME,
            source_file="mcp_server.py",
            handler="mcp_server.lambda_handler",
            code=mcp_code,
            timeout_seconds=300,
            memory_mb=768,  # R5: power-tuned — 768 MB is cost-optimal (AWS Lambda Power Tuning v4.4.0)
            tracing=_lambda.Tracing.ACTIVE,  # R13-XR: X-Ray active tracing
            environment={
                "DEPLOY_VERSION": "2.74.0",
                # COST-05: MCP lambda serves interactive Claude Desktop sessions — dev context,
                # not scheduled production. Attributable separately from prod AI spend in CW.
                "INVOCATION_CONTEXT": "dev",
            },
            custom_policies=rp.mcp_server(),
            table=local_table,
            bucket=local_bucket,
            dlq=None,
            alerts_topic=None,
        )

        # Existing EventBridge permission kept for legacy nightly-warmer rule.
        # The new dedicated warmer Lambda (below) is the primary warmer from v3.7.22.
        # The old rule is left in place to avoid CDK drift during transition.
        mcp.add_permission(
            "EBNightlyWarmer", principal=iam.ServicePrincipal("events.amazonaws.com"), source_arn=_rule_arn("life-platform-nightly-warmer")
        )

        # Function URL: deliberately NOT CDK-managed.
        # Existing URL has 4 resource-based policy statements including duplicates;
        # importing would create conflicting permissions.
        # SEC-02 (#780): the URL is the possession-based auth boundary and the repo
        # is public — it is NOT committed here. Read it live when needed:
        #   aws lambda get-function-url-config --function-name life-platform-mcp --region us-west-2
        # Rotating = delete + recreate the URL config (new url-id); runbook in the
        # private security memory. Consumers discover it at runtime (mcp_url.py).

        # ── Dedicated Cache Warmer Lambda (R9 hardening) ──────────────────────
        # Separated from MCP request-serving Lambda so a 90s warm run does not
        # hold MCP concurrency. Same mcp_server.py source; warmer event triggers
        # the nightly_cache_warmer() path inside mcp/handler.py.
        # Uses same IAM policy as MCP server (reads same DDB partitions, writes cache).
        warmer = create_platform_lambda(
            self,
            "McpWarmer",
            function_name=WARMER_FUNCTION_NAME,
            source_file="mcp_server.py",
            handler="mcp_server.lambda_handler",
            code=mcp_code,
            schedule="cron(10 17 * * ? *)",  # 10:10 AM PT daily (staggered from daily-brief)
            timeout_seconds=300,
            memory_mb=768,  # R5: matched to MCP server power-tuned value
            alarm_name="mcp-warmer-error",
            environment={"DEPLOY_VERSION": "2.74.0"},
            custom_policies=rp.mcp_server(),
            table=local_table,
            bucket=local_bucket,
            dlq=None,
            alerts_topic=local_alerts_topic,
            digest_topic=local_digest_topic,
            digest=True,
        )

        # ── MCP Server alarms ─────────────────────────────────────────────────
        duration_alarm = cloudwatch.Alarm(
            self,
            "McpDurationHighAlarm",
            alarm_name="mcp-server-duration-high",
            metric=cloudwatch.Metric(
                namespace="AWS/Lambda",
                metric_name="Duration",
                dimensions_map={"FunctionName": MCP_FUNCTION_NAME},
                period=Duration.seconds(86400),
                statistic="p99",
            ),
            evaluation_periods=1,
            threshold=240000,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )
        # ADR-050: duration is a degradation signal, not page-worthy → digest.
        duration_alarm.add_alarm_action(cw_actions.SnsAction(local_digest_topic))

        slo_alarm = cloudwatch.Alarm(
            self,
            "SloMcpAvailabilityAlarm",
            alarm_name="slo-mcp-availability",
            metric=cloudwatch.Metric(
                namespace="AWS/Lambda",
                metric_name="Errors",
                dimensions_map={"FunctionName": MCP_FUNCTION_NAME},
                period=Duration.seconds(3600),
                statistic="Sum",
            ),
            evaluation_periods=1,
            threshold=3,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )
        slo_alarm.add_alarm_action(cw_actions.SnsAction(local_digest_topic))

        # ── SLO-5: Warmer completeness alarm (R9 A+ hardening) ────────────────
        # Fires if the dedicated warmer Lambda errors on its daily run.
        # Warmer failure = tools serve stale cached data silently all day.
        warmer_alarm = cloudwatch.Alarm(
            self,
            "SloWarmerCompletenessAlarm",
            alarm_name="slo-warmer-completeness",
            metric=cloudwatch.Metric(
                namespace="AWS/Lambda",
                metric_name="Errors",
                dimensions_map={"FunctionName": WARMER_FUNCTION_NAME},
                period=Duration.seconds(86400),
                statistic="Sum",
            ),
            evaluation_periods=1,
            threshold=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )
        # ADR-050: warmer failure means stale caches all day, but not user-blocking → digest.
        warmer_alarm.add_alarm_action(cw_actions.SnsAction(local_digest_topic))

        # ── #3161: warmer ABSENCE alarm (heartbeat-completeness ledger) ────────
        # slo-warmer-completeness above is an Errors alarm — treat_missing=NOT_BREACHING
        # by construction, so it cannot fire on the "cron stopped firing entirely" case
        # (errors require an invocation; a dead schedule invokes zero times and emits
        # zero Errors datapoints). #3161's audit found life-platform-mcp-warmer was
        # invisible to tests/test_heartbeat_completeness.py's enumerator ENTIRELY (its
        # function_name is this file's WARMER_FUNCTION_NAME constant, not a string
        # literal — the AST walk silently `continue`d past it). Mirrors
        # daily-brief-no-invocations-24h / daily-debrief-no-invocations-24h
        # (monitoring_stack.py): BREACHING on zero Invocations over 24h is the real
        # absence signal; a quiet-but-healthy day still invokes (and still emits a
        # datapoint), so this never false-fires on a normal warmer run.
        warmer_no_invocations_alarm = cloudwatch.Alarm(
            self,
            "McpWarmerNoInvocations",
            alarm_name="mcp-warmer-no-invocations-24h",
            metric=cloudwatch.Metric(
                namespace="AWS/Lambda",
                metric_name="Invocations",
                dimensions_map={"FunctionName": WARMER_FUNCTION_NAME},
                period=Duration.seconds(86400),
                statistic="Sum",
            ),
            evaluation_periods=1,
            threshold=1,
            comparison_operator=cloudwatch.ComparisonOperator.LESS_THAN_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.BREACHING,
        )
        warmer_no_invocations_alarm.add_alarm_action(cw_actions.SnsAction(local_digest_topic))

        # ── #4084: the nightly pre-draft — tomorrow's session drafted + red-teamed ──
        # Same function, constant input (the #3764 hevy_index_rule idiom): the fleet gains a
        # schedule, not a function. mcp.handler dispatches {"job": "nightly_predraft"} to
        # mcp/nightly_predraft.py, whose JOB dict is the one declaration these literals must
        # match (tests/test_nightly_predraft_4084.py reads this file and compares).
        # Fixed UTC: 02:00Z = 19:00 PDT / 18:00 PST — the same Pacific day either way.
        predraft_rule = events.Rule(
            self,
            "NightlyPredraft",
            schedule=events.Schedule.expression("cron(0 2 * * ? *)"),
            description="#4084: draft + red-team tomorrow's session (never commits to Hevy)",
        )
        predraft_rule.add_target(targets.LambdaFunction(warmer, event=events.RuleTargetInput.from_object({"job": "nightly_predraft"})))

        # ── #4084: the pre-draft's dead-man ──────────────────────────────────────
        # mcp-warmer-no-invocations-24h CANNOT see this rule die — the 17:10Z warmer run keeps
        # the function's Invocations >= 1 with the pre-draft rule stone dead (the #3764 lesson:
        # an Invocations heartbeat on a shared function is green by construction). So the job
        # emits PredraftOutcome=1 (EMF) on every HONEST outcome — drafted, exists, no_session,
        # skipped, blocked — and nothing on a crash. 24 consecutive empty 1-hour buckets with
        # missing = BREACHING closes exactly at the end of the 02:00-03:00Z bucket the run
        # should have landed in: red when there is no pre-draft outcome by 03:00Z.
        # Digest (ADR-050): a missing pre-draft means the evening chat builds the session the
        # way it always did — slower, never wrong.
        predraft_missing_alarm = cloudwatch.Alarm(
            self,
            "NightlyPredraftMissing",
            alarm_name="nightly-predraft-missing",
            alarm_description=(
                "#4084: no nightly pre-draft outcome in the last 24 hourly buckets — the 02:00Z run did not reach an "
                "honest outcome by 03:00Z (rule not firing, or the run crashed). Check the NIGHTLY_PREDRAFT log line "
                "in /aws/lambda/life-platform-mcp-warmer."
            ),
            metric=cloudwatch.Metric(
                namespace="LifePlatform/HevyRoutine",
                metric_name="PredraftOutcome",
                dimensions_map={"Job": "nightly_predraft"},
                period=Duration.seconds(3600),
                statistic="Sum",
            ),
            evaluation_periods=24,
            datapoints_to_alarm=24,
            threshold=1,
            comparison_operator=cloudwatch.ComparisonOperator.LESS_THAN_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.BREACHING,
        )
        predraft_missing_alarm.add_alarm_action(cw_actions.SnsAction(local_digest_topic))

        # ── #809: recursive-invocation guard (adopted from the 2026-05-25 orphan batch) ──
        # AWS drops Lambda invocations it detects as recursive; a nonzero
        # RecursiveInvocationsDropped on the MCP server would indicate a serious
        # tool-loop bug. Reuses the live alarm's exact name so CloudFormation
        # adopts the existing orphan in place (PutMetricAlarm upserts by name).
        recursive_alarm = cloudwatch.Alarm(
            self,
            "McpRecursiveLoopAlarm",
            alarm_name="life-platform-recursive-loop",
            metric=cloudwatch.Metric(
                namespace="AWS/Lambda",
                metric_name="RecursiveInvocationsDropped",
                dimensions_map={"FunctionName": MCP_FUNCTION_NAME},
                period=Duration.seconds(3600),
                statistic="Sum",
            ),
            evaluation_periods=1,
            threshold=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )
        recursive_alarm.add_alarm_action(cw_actions.SnsAction(local_digest_topic))

        cdk.CfnOutput(self, "McpFunctionArn", value=mcp.function_arn, description="MCP server Lambda ARN")
        cdk.CfnOutput(self, "McpWarmerArn", value=warmer.function_arn, description="MCP cache warmer Lambda ARN")
        # SEC-02 (#780): the MCP Function URL is intentionally NOT emitted as a CfnOutput —
        # it is the possession-based auth boundary and this repo is public. Read it live:
        #   aws lambda get-function-url-config --function-name life-platform-mcp --region us-west-2
