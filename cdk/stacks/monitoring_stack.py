"""
MonitoringStack — Cross-cutting CloudWatch alarms not owned by other stacks.

Covers:
  SLO alarms (3):
    slo-daily-brief-delivery     Errors Sum >= 1, daily-brief, 86400s
    slo-ai-coaching-success      LifePlatform/AI AnthropicAPIFailure Sum >= 3, 86400s
    slo-source-freshness         LifePlatform/Freshness StaleSourceCount Max >= 1, 86400s

  Daily-brief operational alarms (4, not in EmailStack):
    daily-brief-duration-high           Duration p99 >= 240000ms, 86400s
    daily-brief-no-invocations-24h      Invocations Sum < 1, 86400s
    life-platform-daily-brief-errors    Errors Sum >= 1, 300s
    life-platform-daily-brief-invocations Invocations Sum < 1, 93600s

  AI token budget alarms (13):
    ai-tokens-<lambda>-daily  AnthropicOutputTokens Sum, 86400s
    Per-Lambda threshold: 1818 (most); 13333 (daily-brief); 33333 (platform total)

  DynamoDB item-size warning (1):
    life-platform-ddb-item-size-warning  LifePlatform/DynamoDB ItemSizeBytes Max >= 307200, 300s

  S3 storage size alarm (1):  OBS-08
    life-platform-s3-bucket-size-high  BucketSizeBytes Max >= 50GB, 86400s
"""

import aws_cdk as cdk
from aws_cdk import (
    Stack,
    Duration,
    aws_cloudwatch as cloudwatch,
    aws_cloudwatch_actions as cw_actions,
    aws_logs as logs,
    aws_sns as sns,
)
from constructs import Construct
from stacks.constants import REGION, ACCT, S3_BUCKET, TABLE_NAME  # CONF-01

ALERTS_TOPIC_ARN = f"arn:aws:sns:{REGION}:{ACCT}:life-platform-alerts"
DIGEST_TOPIC_ARN = f"arn:aws:sns:{REGION}:{ACCT}:life-platform-alerts-digest"

GTE = cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD
LT  = cloudwatch.ComparisonOperator.LESS_THAN_THRESHOLD
NB  = cloudwatch.TreatMissingData.NOT_BREACHING


class MonitoringStack(Stack):

    def __init__(self, scope, construct_id: str, alerts_topic: sns.ITopic, digest_topic: sns.ITopic = None, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        topic = sns.Topic.from_topic_arn(self, "AlertsTopic", ALERTS_TOPIC_ARN)
        digest = sns.Topic.from_topic_arn(self, "DigestTopic", DIGEST_TOPIC_ARN)

        # ADR-050: alarms classified urgent (→ topic) or digest (→ digest topic).
        # Default: urgent. Pass digest=True to route to the daily batched email.
        def _alarm(alarm_id, alarm_name, namespace, metric_name, period_sec,
                   statistic, threshold, operator, dims=None, ext_stat=None,
                   to_digest=False):
            metric = cloudwatch.Metric(
                namespace=namespace,
                metric_name=metric_name,
                dimensions_map=dims or {},
                period=Duration.seconds(period_sec),
                statistic=ext_stat if ext_stat else statistic,
            )
            a = cloudwatch.Alarm(
                self, alarm_id,
                alarm_name=alarm_name,
                metric=metric,
                evaluation_periods=1,
                threshold=threshold,
                comparison_operator=operator,
                treat_missing_data=NB,
            )
            a.add_alarm_action(cw_actions.SnsAction(digest if to_digest else topic))
            return a

        # ══════════════════════════════════════════════════════════════
        # SLO alarms
        # ══════════════════════════════════════════════════════════════
        _alarm("SloDailyBriefDelivery",   "slo-daily-brief-delivery",
               "AWS/Lambda", "Errors", 86400, "Sum", 1, GTE,
               {"FunctionName": "daily-brief"})

        _alarm("SloAiCoachingSuccess",    "slo-ai-coaching-success",
               "LifePlatform/AI", "AnthropicAPIFailure", 86400, "Sum", 3, GTE,
               to_digest=True)

        # Stale-source alerts re-fire daily; perfect digest candidate.
        _alarm("SloSourceFreshness",      "slo-source-freshness",
               "LifePlatform/Freshness", "StaleSourceCount", 86400, "Maximum", 1, GTE,
               to_digest=True)

        # ══════════════════════════════════════════════════════════════
        # Daily-brief operational alarms (not in EmailStack)
        # ══════════════════════════════════════════════════════════════
        # 2026-05-03: bumped threshold 240000 → 720000 ms (4min → 12min).
        # Lambda timeout is now 900s (was 300s); old 240s threshold fired on
        # every healthy run that included the full 6-coach narrative pass.
        # 720s = 80% of timeout — still catches genuine runaways.
        _alarm("DailyBriefDurationHigh",  "daily-brief-duration-high",
               "AWS/Lambda", "Duration", 86400, None, 720000, GTE,
               {"FunctionName": "daily-brief"}, ext_stat="p99", to_digest=True)

        _alarm("DailyBriefNoInvocations", "daily-brief-no-invocations-24h",
               "AWS/Lambda", "Invocations", 86400, "Sum", 1, LT,
               {"FunctionName": "daily-brief"})

        _alarm("DailyBriefErrors",        "life-platform-daily-brief-errors",
               "AWS/Lambda", "Errors", 300, "Sum", 1, GTE,
               {"FunctionName": "daily-brief"})

        # NOTE: life-platform-daily-brief-invocations (93600s) removed 2026-03-10 —
        # duplicate of daily-brief-no-invocations-24h above. COST-A cleanup.

        # ══════════════════════════════════════════════════════════════
        # AI token budget alarms — consolidated 2026-03-10 (COST-A)
        # Removed 11 per-Lambda alarms ($1.10/mo). Kept: daily-brief
        # (highest-cost Lambda) + platform total (catch-all).
        # ══════════════════════════════════════════════════════════════
        # 2026-05-03: bumped threshold 13333 → 18000. Today's healthy brief
        # used 14414 tokens (above old threshold). With IC-3 max_tokens bumped
        # to 600 + 6 coach narratives + ensemble, healthy budget is ~14-16k.
        # 2026-05-28: bumped 18000 → 30000. Normal usage had crept to ~18003
        # (8 coach V2 narratives post-restart), so 18000 sat right at the daily
        # baseline and false-fired almost every day into the alarm digest.
        # 30000 alerts only on a genuine ~1.7x spike, not normal operation.
        _alarm("AiTokensDailyBriefDaily",
               "ai-tokens-daily-brief-daily",
               "LifePlatform/AI", "AnthropicOutputTokens", 86400, "Sum", 30000, GTE,
               {"LambdaFunction": "daily-brief"}, to_digest=True)

        # Platform-level total (no dims)
        _alarm("AiTokensPlatformTotal",   "ai-tokens-platform-daily-total",
               "LifePlatform/AI", "AnthropicOutputTokens", 86400, "Sum", 33333, GTE)

        # ══════════════════════════════════════════════════════════════
        # OBS-01: DynamoDB throttling alarm
        # Any throttled requests means data is silently dropped.
        # ══════════════════════════════════════════════════════════════
        _alarm("DdbThrottledRequests",    "life-platform-ddb-throttled-requests",
               "AWS/DynamoDB", "ThrottledRequests", 300, "Sum", 1, GTE,
               {"TableName": "life-platform", "Operation": "PutItem"})

        # ══════════════════════════════════════════════════════════════
        # DynamoDB item-size warning
        # ══════════════════════════════════════════════════════════════
        _alarm("DdbItemSizeWarning",      "life-platform-ddb-item-size-warning",
               "LifePlatform/DynamoDB", "ItemSizeBytes", 300, "Maximum", 307200, GTE,
               to_digest=True)

        # ══════════════════════════════════════════════════════════════
        # OBS-09: SQS DLQ message count alarm
        # Any message in the DLQ means an ingestion Lambda failed all retries.
        # ══════════════════════════════════════════════════════════════
        _alarm("IngestionDlqMessages",    "life-platform-ingestion-dlq-messages",
               "AWS/SQS", "ApproximateNumberOfMessagesVisible", 300, "Maximum", 1, GTE,
               {"QueueName": "life-platform-ingestion-dlq"})

        # ══════════════════════════════════════════════════════════════
        # OBS-02: Lambda memory utilization > 90% of limit
        # Only daily-brief (us-west-2) can be filtered here.
        # site-api log group is in us-east-1 — cross-region not supported.
        # REPORT line format: REPORT RequestId: X Duration: X ms Billed Duration: X ms
        #   Memory Size: X MB Max Memory Used: X MB [Init Duration: X ms]
        # Fields [0-indexed]: 0=REPORT 17=max_memory_used_mb
        # NOTE: dimensions and default_value are mutually exclusive in CWL MetricFilter.
        # ══════════════════════════════════════════════════════════════
        _report_pattern = (
            "[w0=\"REPORT\", w1, w2, w3, w4, w5, w6, w7, w8, w9, "
            "w10, w11, w12, w13, w14, w15, w16, maxMem, ...]"
        )
        db_log_group = logs.LogGroup.from_log_group_name(
            self, "MemFilerLgdailybrief", "/aws/lambda/daily-brief"
        )
        db_mf = logs.MetricFilter(
            self, "MemFilterdailybrief",
            log_group=db_log_group,
            filter_pattern=logs.FilterPattern.literal(_report_pattern),
            metric_name="DailyBriefMaxMemoryMB",
            metric_namespace="LifePlatform/Lambda",
            metric_value="$maxMem",
        )
        mem_alarm_db = cloudwatch.Alarm(
            self, "MemoryHighdailybrief",
            alarm_name="life-platform-daily-brief-memory-high",
            metric=db_mf.metric(period=Duration.seconds(300), statistic="Maximum"),
            evaluation_periods=1,
            threshold=int(512 * 0.9),
            comparison_operator=GTE,
            treat_missing_data=NB,
        )
        # ADR-050: memory-high is a slow degradation signal, not page-worthy.
        mem_alarm_db.add_alarm_action(cw_actions.SnsAction(digest))

        # ══════════════════════════════════════════════════════════════
        # OBS-08: S3 bucket storage size alarm
        # BucketSizeBytes is a daily metric — period must be 86400s.
        # Alerts if raw/ accumulation exceeds 50 GB unexpectedly.
        # ══════════════════════════════════════════════════════════════
        _alarm("S3BucketSizeHigh",        "life-platform-s3-bucket-size-high",
               "AWS/S3", "BucketSizeBytes", 86400, "Maximum", 50 * 1024 ** 3, GTE,
               {"BucketName": S3_BUCKET, "StorageType": "StandardStorage"},
               to_digest=True)

        # NOTE: OBS-07 email-subscriber alarm lives in web_stack.py (us-east-1).
        # email-subscriber Lambda runs in us-east-1; Lambda metrics are regional.
        # Cross-region alarm would never fire. See web_stack.py SubscriberErrors alarm.

        # OBS-04: site-api cold start alarm deferred — site-api Lambda and its
        # log group (/aws/lambda/site-api) are in us-east-1; MonitoringStack is
        # in us-west-2. Cross-region MetricFilter is not supported.
        # Implement in a separate us-east-1 monitoring construct when needed.

        # ══════════════════════════════════════════════════════════════
        # SiteAPI EMF dashboard (BACKLOG.md:252 — closes P3.4 observability loop)
        # ══════════════════════════════════════════════════════════════
        # site_api_lambda.py emits a per-request structured log line:
        #   {"_aws": {...}, "Route": "/api/...", "Method": "GET", "DurationMs": N, "ColdStart": 0/1}
        # CloudWatch auto-extracts DurationMs + ColdStart as metrics in
        # the LifePlatform/SiteAPI namespace, dimensions (Route, Method).
        # The Lambda runs in us-west-2 (R17-09 move) so same-region dashboards work.
        #
        # Top 6 routes by expected traffic: /api/vitals, /api/healthz, /api/character,
        # /api/snapshot, /api/journey, /api/platform_stats
        TOP_ROUTES = ["/api/vitals", "/api/healthz", "/api/character",
                      "/api/snapshot", "/api/journey", "/api/platform_stats"]

        def _route_p_metric(route: str, method: str, stat: str = "p50"):
            return cloudwatch.Metric(
                namespace="LifePlatform/SiteAPI",
                metric_name="DurationMs",
                dimensions_map={"Route": route, "Method": method},
                statistic=stat,
                period=Duration.minutes(5),
                label=f"{route} {stat}",
            )

        site_api_dash = cloudwatch.Dashboard(
            self, "SiteApiDashboard",
            dashboard_name="life-platform-site-api-dashboard",
            period_override=cloudwatch.PeriodOverride.AUTO,
            start="-PT1H",
        )

        # Row 1: Latency p50 + p95 for top 6 GET routes
        site_api_dash.add_widgets(
            cloudwatch.GraphWidget(
                title="Latency p50 (top routes, GET)",
                width=12, height=6,
                left=[_route_p_metric(r, "GET", "p50") for r in TOP_ROUTES],
                left_y_axis=cloudwatch.YAxisProps(label="ms", show_units=False),
            ),
            cloudwatch.GraphWidget(
                title="Latency p95 (top routes, GET)",
                width=12, height=6,
                left=[_route_p_metric(r, "GET", "p95") for r in TOP_ROUTES],
                left_y_axis=cloudwatch.YAxisProps(label="ms", show_units=False),
            ),
        )

        # Row 2: Cold-start count + total invocations
        site_api_dash.add_widgets(
            cloudwatch.GraphWidget(
                title="Cold starts per route (Sum, 5min)",
                width=12, height=6,
                left=[cloudwatch.Metric(
                    namespace="LifePlatform/SiteAPI",
                    metric_name="ColdStart",
                    dimensions_map={"Route": r, "Method": "GET"},
                    statistic="Sum",
                    period=Duration.minutes(5),
                    label=r,
                ) for r in TOP_ROUTES],
            ),
            cloudwatch.GraphWidget(
                title="site-api Lambda — Errors + Invocations + Duration",
                width=12, height=6,
                left=[
                    cloudwatch.Metric(
                        namespace="AWS/Lambda",
                        metric_name="Invocations",
                        dimensions_map={"FunctionName": "life-platform-site-api"},
                        statistic="Sum",
                        period=Duration.minutes(5),
                        label="Invocations",
                    ),
                    cloudwatch.Metric(
                        namespace="AWS/Lambda",
                        metric_name="Errors",
                        dimensions_map={"FunctionName": "life-platform-site-api"},
                        statistic="Sum",
                        period=Duration.minutes(5),
                        label="Errors",
                        color=cloudwatch.Color.RED,
                    ),
                ],
                right=[
                    cloudwatch.Metric(
                        namespace="AWS/Lambda",
                        metric_name="Duration",
                        dimensions_map={"FunctionName": "life-platform-site-api"},
                        statistic="p99",
                        period=Duration.minutes(5),
                        label="Duration p99 (ms)",
                    ),
                ],
                right_y_axis=cloudwatch.YAxisProps(label="ms", show_units=False),
            ),
        )

        # Row 3: 404s + slow endpoints (single-number panels)
        site_api_dash.add_widgets(
            cloudwatch.SingleValueWidget(
                title="Total requests last 1h (all routes, GET)",
                width=8, height=4,
                metrics=[cloudwatch.Metric(
                    namespace="LifePlatform/SiteAPI",
                    metric_name="DurationMs",
                    dimensions_map={"Route": r, "Method": "GET"},
                    statistic="SampleCount",
                    period=Duration.hours(1),
                    label=r,
                ) for r in TOP_ROUTES],
            ),
            cloudwatch.SingleValueWidget(
                title="Cold start rate (1h)",
                width=8, height=4,
                metrics=[cloudwatch.Metric(
                    namespace="LifePlatform/SiteAPI",
                    metric_name="ColdStart",
                    dimensions_map={"Route": r, "Method": "GET"},
                    statistic="Sum",
                    period=Duration.hours(1),
                    label=r,
                ) for r in TOP_ROUTES],
            ),
        )
