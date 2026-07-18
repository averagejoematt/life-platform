"""
ServeStack — the public serving path (#793 / R22-ARCH-02).

The reader-facing API lambdas (site-api, site-api-ai) were split out of
LifePlatformOperational on 2026-07-08 so that ops-motivated deploy holds on the
15+ internal lambdas can never freeze the public serving path again, and vice
versa: stack boundaries now match change cadence and failure domains.

The physical resources were MOVED here from LifePlatformOperational with
`cdk refactor` (CloudFormation stack refactoring) — function names AND the two
Function URLs are unchanged. That matters: the Function URL subdomains are
pinned as static strings in cdk.json (`site_api_fn_url_domain`,
`site_api_ai_fn_url_domain`) and baked into the CloudFront origins in
web_stack (us-east-1). The URLs must never be deleted/recreated — a new URL
gets a new random subdomain and silently severs CloudFront.

Lambdas (2):
  life-platform-site-api      Function URL (via CloudFront /api/*) — read-mostly data endpoints
  life-platform-site-api-ai   Function URL (via CloudFront) — /api/ask + /api/board_ask

Ownership (#794, unchanged by the move): CDK owns the function definition,
IAM role, env vars, and alarms; deploy/deploy_site_api.sh remains the
sanctioned fast CODE path — both channels stage the identical
deploy/build_bundle.py full-tree bundle (ADR-131).
"""

import aws_cdk as cdk
from aws_cdk import (
    Duration,
    Stack,
    aws_cloudwatch as cloudwatch,
    aws_cloudwatch_actions as cw_actions,
    aws_dynamodb as dynamodb,
    aws_lambda as _lambda,
    aws_s3 as s3,
    aws_sns as sns,
)

from stacks import role_policies as rp
from stacks.constants import TABLE_NAME  # CONF-01 / #936: one source for the table name (DR cutover)
from stacks.lambda_helpers import create_platform_lambda
from stacks.secrets_helpers import site_api_origin_secret_value

# #1328: every Lambda this stack defines gets a Throttles alarm — a throttle on
# the public serving path is a synchronous 429 to a real reader, never an
# unobserved event. tests/test_serve_throttles_alarms.py asserts this tuple
# covers every create_platform_lambda(function_name=...) in this file.
THROTTLE_ALARMED_FUNCTIONS = (
    ("life-platform-site-api", "SiteApiThrottles"),
    ("life-platform-site-api-ai", "SiteApiAiThrottles"),
)

REGION = "us-west-2"
ACCT = "205930651321"
LIFE_PLATFORM_TABLE = TABLE_NAME
LIFE_PLATFORM_BUCKET = "matthew-life-platform"
DIGEST_TOPIC_ARN = f"arn:aws:sns:{REGION}:{ACCT}:life-platform-alerts-digest"


class ServeStack(Stack):
    def __init__(self, scope, construct_id, **kwargs):
        super().__init__(scope, construct_id, **kwargs)
        # `-c serve_bootstrap=1` synthesizes an EMPTY stack (CDKMetadata only):
        # `cdk refactor` cannot create the destination stack, so the migration
        # is (1) deploy empty shell, (2) refactor moves the resources in.
        # Harmless to keep for a future re-bootstrap; never set it in normal use.
        if self.node.try_get_context("serve_bootstrap"):
            return

        local_table = dynamodb.Table.from_table_name(self, "LifePlatformTable", LIFE_PLATFORM_TABLE)
        local_bucket = s3.Bucket.from_bucket_name(self, "LifePlatformBucket", LIFE_PLATFORM_BUCKET)
        local_digest_topic = sns.Topic.from_topic_arn(self, "DigestTopic", DIGEST_TOPIC_ARN)

        # #815 (R22-SEC-03): one read, reused for both Lambdas below. web_stack.py
        # calls the SAME helper (own construct instance, same underlying secret
        # ARN) to set the matching CloudFront custom origin header — see
        # stacks/secrets_helpers.py for why this can never drift between the two.
        site_api_origin_secret = site_api_origin_secret_value(self)

        # ── Site API Lambda — life-platform-site-api (R17-09: moved from web_stack us-east-1)
        # Read-only. DynamoDB same-region (eliminates cross-region latency).
        # Function URL is a global HTTPS endpoint — CloudFront in us-east-1 can origin to it.
        site_api_fn = create_platform_lambda(
            self,
            "SiteApiLambda",
            function_name="life-platform-site-api",
            source_file="lambdas/web/site_api_lambda.py",
            handler="web.site_api_lambda.lambda_handler",
            table=local_table,
            bucket=local_bucket,
            dlq=None,
            alerts_topic=None,
            custom_policies=rp.site_api(),
            timeout_seconds=30,  # Phase 1.6 (2026-05-16): 15s→30s. Matches CloudFront default; complex /api/changes-since queries hit 15s ceiling.
            memory_mb=256,
            environment={
                "USER_ID": "matthew",
                "TABLE_NAME": TABLE_NAME,
                "AI_SECRET_NAME": "life-platform/site-api-ai-key",
                "S3_BUCKET": "matthew-life-platform",
                "S3_REGION": "us-west-2",
                "CORS_ORIGIN": "https://averagejoematt.com",
                "SITE_API_ORIGIN_SECRET": site_api_origin_secret,  # #815 R22-SEC-03
            },
            # #794: CDK owns this function's definition (role, env, alarms); the
            # code asset is the shared staged full-tree bundle (build_bundle.py
            # via lambda_helpers.staged_tree_asset()) — the SAME bundle shape
            # deploy_site_api.sh ships for hot deploys, so the two channels can
            # never drift apart in package layout (ADR-131 / #781 retired the
            # shared layer this comment used to reference).
        )
        site_api_url = site_api_fn.add_function_url(
            auth_type=_lambda.FunctionUrlAuthType.NONE,
            cors=_lambda.FunctionUrlCorsOptions(
                allowed_origins=["https://averagejoematt.com", "https://www.averagejoematt.com"],
                allowed_methods=[_lambda.HttpMethod.GET, _lambda.HttpMethod.POST],
                allowed_headers=["Content-Type"],
            ),
        )

        site_api_fn_url_domain = cdk.Fn.select(2, cdk.Fn.split("/", site_api_url.url))

        # ADR-036 fix: cap data Lambda concurrency to isolate from AI traffic spikes
        # 2026-06-17: account concurrency quota raised to 100 (AWS case 177921309700709) — enabled.
        # #1328 (2026-07-18): 5 → 20. The cap of 5 BOUND daily — ConcurrentExecutions
        # Max hit 5.0 every day 07-10..07-17 and readers ate 627 synchronous 429s
        # over 30d (peak 110/day) while monitoring showed green. 20 = 4× the
        # measured saturation point, still leaves 78 unreserved of the 100 account
        # limit (site-api-ai holds 2). Sized against measured traffic, not load
        # testing — see docs/RESERVED_CONCURRENCY.md.
        site_api_fn.node.default_child.add_property_override("ReservedConcurrentExecutions", 20)

        # ── Site API AI Lambda — /api/ask + /api/board_ask (split from site-api for blast radius isolation)
        # Separate Lambda for AI endpoints: sequential Haiku calls can take 3-20s.
        # Reserved concurrency=2 prevents AI traffic from starving data endpoints.
        site_api_ai_fn = create_platform_lambda(
            self,
            "SiteApiAiLambda",
            function_name="life-platform-site-api-ai",
            source_file="lambdas/web/site_api_ai_lambda.py",
            handler="web.site_api_ai_lambda.lambda_handler",
            table=local_table,
            bucket=local_bucket,
            dlq=None,
            alerts_topic=None,
            custom_policies=rp.site_api_ai(),
            timeout_seconds=30,  # AI calls take 3-5s each; board_ask chains up to 6
            memory_mb=256,
            environment={
                "USER_ID": "matthew",
                "TABLE_NAME": TABLE_NAME,
                "AI_SECRET_NAME": "life-platform/site-api-ai-key",
                "S3_BUCKET": "matthew-life-platform",
                "S3_REGION": "us-west-2",
                "CORS_ORIGIN": "https://averagejoematt.com",
                "SITE_API_ORIGIN_SECRET": site_api_origin_secret,  # #815 R22-SEC-03
            },
            # #794: same staged full-tree bundle as site-api above — no layer (ADR-131).
        )
        # Cap AI Lambda concurrency — 2 concurrent is enough for personal site traffic
        # 2026-06-17: account concurrency quota raised to 100 (AWS case 177921309700709) — enabled.
        site_api_ai_fn.node.default_child.add_property_override("ReservedConcurrentExecutions", 2)

        # ── #809: site-api-ai error alarm (adopted from the 2026-05-25 orphan batch) ──
        # site-api-ai is SYNC (Function URL) — the ADR-116 DLQ path can't cover it,
        # so it keeps a real Errors alarm. Threshold ≥3/hr like slo-mcp-availability:
        # a single transient Bedrock hiccup surfaces to the reader as one failed ask,
        # not an incident. Replaces the misnamed live orphan
        # `life-platform-life-platform-site-api-ai-errors` (deleted after deploy).
        site_api_ai_errors = cloudwatch.Alarm(
            self,
            "SiteApiAiErrorsAlarm",
            alarm_name="site-api-ai-errors",
            metric=cloudwatch.Metric(
                namespace="AWS/Lambda",
                metric_name="Errors",
                dimensions_map={"FunctionName": "life-platform-site-api-ai"},
                period=Duration.seconds(3600),
                statistic="Sum",
            ),
            evaluation_periods=1,
            threshold=3,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )
        site_api_ai_errors.add_alarm_action(cw_actions.SnsAction(local_digest_topic))

        site_api_ai_url = site_api_ai_fn.add_function_url(
            auth_type=_lambda.FunctionUrlAuthType.NONE,
            cors=_lambda.FunctionUrlCorsOptions(
                allowed_origins=["https://averagejoematt.com", "https://www.averagejoematt.com"],
                allowed_methods=[_lambda.HttpMethod.POST],
                allowed_headers=["Content-Type", "X-Subscriber-Token"],
            ),
        )

        site_api_ai_fn_url_domain = cdk.Fn.select(2, cdk.Fn.split("/", site_api_ai_url.url))

        # ── Site API CloudWatch alarms (moved from web_stack — alarms must be same region as Lambda)
        GTE = cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD

        site_api_errors = cloudwatch.Metric(
            namespace="AWS/Lambda",
            metric_name="Errors",
            dimensions_map={"FunctionName": "life-platform-site-api"},
            period=Duration.minutes(5),
            statistic="Sum",
        )
        site_api_invocations = cloudwatch.Metric(
            namespace="AWS/Lambda",
            metric_name="Invocations",
            dimensions_map={"FunctionName": "life-platform-site-api"},
            period=Duration.minutes(5),
            statistic="Sum",
        )
        site_api_duration_p95 = cloudwatch.Metric(
            namespace="AWS/Lambda",
            metric_name="Duration",
            dimensions_map={"FunctionName": "life-platform-site-api"},
            period=Duration.minutes(5),
            statistic="p95",
        )
        site_api_duration_p50 = cloudwatch.Metric(
            namespace="AWS/Lambda",
            metric_name="Duration",
            dimensions_map={"FunctionName": "life-platform-site-api"},
            period=Duration.minutes(5),
            statistic="p50",
        )
        _ = site_api_duration_p50  # kept for parity with the pre-move section (dashboard candidate)

        # ADR-050: site-api alarms route to digest. The canary covers true outages
        # (CanaryS3Fail / CanaryDDBFail fire urgently); these are degradation signals.
        _site_api_errors_alarm = cloudwatch.Alarm(
            self,
            "SiteApiErrors",
            alarm_name="site-api-errors",
            metric=site_api_errors,
            threshold=1,
            evaluation_periods=1,
            comparison_operator=GTE,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )
        _site_api_errors_alarm.add_alarm_action(cw_actions.SnsAction(local_digest_topic))

        _site_api_latency_alarm = cloudwatch.Alarm(
            self,
            "SiteApiLatencyHigh",
            alarm_name="site-api-p95-latency-high",
            metric=site_api_duration_p95,
            threshold=5000,
            evaluation_periods=1,
            comparison_operator=GTE,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )
        _site_api_latency_alarm.add_alarm_action(cw_actions.SnsAction(local_digest_topic))

        _site_api_spike_alarm = cloudwatch.Alarm(
            self,
            "SiteApiInvocationSpike",
            alarm_name="site-api-invocation-spike",
            metric=site_api_invocations,
            threshold=200,
            evaluation_periods=1,
            comparison_operator=GTE,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )
        _site_api_spike_alarm.add_alarm_action(cw_actions.SnsAction(local_digest_topic))

        # ── #1328: Throttles alarms — one per serve-stack Lambda ──
        # A throttle on a Function-URL origin is a synchronous 429 to a real reader.
        # 627 throttles/30d ran unobserved (zero Throttles alarms existed anywhere)
        # while the reserved-concurrency cap of 5 bound daily. Threshold 5/15min:
        # a lone cold-start collision stays quiet, a binding cap does not.
        # tests/test_serve_throttles_alarms.py asserts one alarm per function here.
        # Deliberately unrolled (no loop): the #795/#934 alarm-count/name AST
        # discoverers resolve one Alarm() per call site with a literal name.
        _site_api_throttles = cloudwatch.Alarm(
            self,
            "SiteApiThrottles",
            alarm_name="site-api-throttles",
            metric=cloudwatch.Metric(
                namespace="AWS/Lambda",
                metric_name="Throttles",
                dimensions_map={"FunctionName": "life-platform-site-api"},
                period=Duration.minutes(15),
                statistic="Sum",
            ),
            threshold=5,
            evaluation_periods=1,
            comparison_operator=GTE,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )
        _site_api_throttles.add_alarm_action(cw_actions.SnsAction(local_digest_topic))

        _site_api_ai_throttles = cloudwatch.Alarm(
            self,
            "SiteApiAiThrottles",
            alarm_name="site-api-ai-throttles",
            metric=cloudwatch.Metric(
                namespace="AWS/Lambda",
                metric_name="Throttles",
                dimensions_map={"FunctionName": "life-platform-site-api-ai"},
                period=Duration.minutes(15),
                statistic="Sum",
            ),
            threshold=5,
            evaluation_periods=1,
            comparison_operator=GTE,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )
        _site_api_ai_throttles.add_alarm_action(cw_actions.SnsAction(local_digest_topic))

        # NOTE (2026-06-08): the "life-platform-site-api" CloudWatch Dashboard was
        # removed from CDK after it was deleted out-of-band — CFN tried to UPDATE a
        # non-existent dashboard and stuck the owning stack in
        # UPDATE_ROLLBACK_FAILED. Site-api monitoring is covered by the
        # life-platform-site-api-dashboard / -latency dashboards + the alarms above.
        # Re-add a Dashboard construct here (fresh name) if a curated board is wanted.

        cdk.CfnOutput(
            self,
            "SiteApiFunctionUrl",
            value=site_api_url.url,
            description="Lambda Function URL for life-platform-site-api (us-west-2) — R17-09",
        )
        cdk.CfnOutput(
            self,
            "SiteApiFunctionUrlDomain",
            value=site_api_fn_url_domain,
            description="Function URL domain (without https://) — use in web_stack CloudFront origin after R17-09 migration",
        )
        cdk.CfnOutput(
            self,
            "SiteApiAiFunctionUrl",
            value=site_api_ai_url.url,
            description="Lambda Function URL for life-platform-site-api-ai (us-west-2)",
        )
        cdk.CfnOutput(
            self,
            "SiteApiAiFunctionUrlDomain",
            value=site_api_ai_fn_url_domain,
            description="AI Lambda Function URL domain — use in web_stack CloudFront AiLambdaOrigin",
        )
