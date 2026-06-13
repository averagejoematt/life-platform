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

from aws_cdk import (
    Duration,
    Stack,
    aws_cloudwatch as cloudwatch,
    aws_cloudwatch_actions as cw_actions,
    aws_logs as logs,
    aws_sns as sns,
)

from stacks.constants import ACCT, REGION, S3_BUCKET  # CONF-01

ALERTS_TOPIC_ARN = f"arn:aws:sns:{REGION}:{ACCT}:life-platform-alerts"
DIGEST_TOPIC_ARN = f"arn:aws:sns:{REGION}:{ACCT}:life-platform-alerts-digest"

GTE = cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD
LT = cloudwatch.ComparisonOperator.LESS_THAN_THRESHOLD
NB = cloudwatch.TreatMissingData.NOT_BREACHING


class MonitoringStack(Stack):

    def __init__(self, scope, construct_id: str, alerts_topic: sns.ITopic, digest_topic: sns.ITopic = None, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        topic = sns.Topic.from_topic_arn(self, "AlertsTopic", ALERTS_TOPIC_ARN)
        digest = sns.Topic.from_topic_arn(self, "DigestTopic", DIGEST_TOPIC_ARN)

        # ADR-050: alarms classified urgent (→ topic) or digest (→ digest topic).
        # Default: urgent. Pass digest=True to route to the daily batched email.
        def _alarm(
            alarm_id,
            alarm_name,
            namespace,
            metric_name,
            period_sec,
            statistic,
            threshold,
            operator,
            dims=None,
            ext_stat=None,
            to_digest=False,
        ):
            metric = cloudwatch.Metric(
                namespace=namespace,
                metric_name=metric_name,
                dimensions_map=dims or {},
                period=Duration.seconds(period_sec),
                statistic=ext_stat if ext_stat else statistic,
            )
            a = cloudwatch.Alarm(
                self,
                alarm_id,
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
        _alarm(
            "SloDailyBriefDelivery",
            "slo-daily-brief-delivery",
            "AWS/Lambda",
            "Errors",
            86400,
            "Sum",
            1,
            GTE,
            {"FunctionName": "daily-brief"},
        )

        _alarm(
            "SloAiCoachingSuccess",
            "slo-ai-coaching-success",
            "LifePlatform/AI",
            "AnthropicAPIFailure",
            86400,
            "Sum",
            3,
            GTE,
            to_digest=True,
        )

        # Stale-source alerts re-fire daily; perfect digest candidate.
        _alarm(
            "SloSourceFreshness",
            "slo-source-freshness",
            "LifePlatform/Freshness",
            "StaleSourceCount",
            86400,
            "Maximum",
            1,
            GTE,
            to_digest=True,
        )

        # ER-01: infra-liveness — separate from behavioral freshness above. Fires
        # when an ingestion Lambda is running-but-erroring (failure streak) or has
        # stopped running (attempt staleness), independent of whether new data was
        # expected. This is the signal the silent 44-day Garmin outage lacked.
        # Set by pipeline_health_check's check_ingest_liveness mode (daily).
        _alarm(
            "IngestLivenessUnhealthy",
            "ingest-liveness-unhealthy",
            "LifePlatform/IngestLiveness",
            "UnhealthySourceCount",
            86400,
            "Maximum",
            1,
            GTE,
            to_digest=True,
        )

        # ══════════════════════════════════════════════════════════════
        # Daily-brief operational alarms (not in EmailStack)
        # ══════════════════════════════════════════════════════════════
        # 2026-05-03: bumped threshold 240000 → 720000 ms (4min → 12min).
        # Lambda timeout is now 900s (was 300s); old 240s threshold fired on
        # every healthy run that included the full 6-coach narrative pass.
        # 720s = 80% of timeout — still catches genuine runaways.
        _alarm(
            "DailyBriefDurationHigh",
            "daily-brief-duration-high",
            "AWS/Lambda",
            "Duration",
            86400,
            None,
            720000,
            GTE,
            {"FunctionName": "daily-brief"},
            ext_stat="p99",
            to_digest=True,
        )

        _alarm(
            "DailyBriefNoInvocations",
            "daily-brief-no-invocations-24h",
            "AWS/Lambda",
            "Invocations",
            86400,
            "Sum",
            1,
            LT,
            {"FunctionName": "daily-brief"},
        )

        _alarm(
            "DailyBriefErrors",
            "life-platform-daily-brief-errors",
            "AWS/Lambda",
            "Errors",
            300,
            "Sum",
            1,
            GTE,
            {"FunctionName": "daily-brief"},
        )

        # NOTE: life-platform-daily-brief-invocations (93600s) removed 2026-03-10 —
        # duplicate of daily-brief-no-invocations-24h above. COST-A cleanup.

        # ══════════════════════════════════════════════════════════════
        # ══════════════════════════════════════════════════════════════
        # Ingest consecutive-failure alarms (ER-01 follow-up, 2026-06-13)
        # Whoop's refresh token died 2026-06-10 and failed 49 consecutive runs
        # before a human noticed — auth-class outages were only visible in the
        # daily digest. These fire URGENT when any OAuth-token source reports
        # ConsecutiveFailures >= 3 (the ingest_health heartbeat emits the
        # running count per run). Sources that don't emit simply never fire
        # (missing data = not breaching).
        # ══════════════════════════════════════════════════════════════
        for _src in ("whoop", "withings", "strava", "eightsleep", "garmin", "hevy"):
            _alarm(
                f"IngestConsecFail{_src.title()}",
                f"ingest-consecutive-failures-{_src}",
                "LifePlatform/IngestLiveness",
                "ConsecutiveFailures",
                21600,
                "Maximum",
                3,
                GTE,
                dims={"Source": _src},
            )

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
        _alarm(
            "AiTokensDailyBriefDaily",
            "ai-tokens-daily-brief-daily",
            "LifePlatform/AI",
            "AnthropicOutputTokens",
            86400,
            "Sum",
            30000,
            GTE,
            {"LambdaFunction": "daily-brief"},
            to_digest=True,
        )

        # Platform-level total (no dims)
        _alarm(
            "AiTokensPlatformTotal", "ai-tokens-platform-daily-total", "LifePlatform/AI", "AnthropicOutputTokens", 86400, "Sum", 33333, GTE
        )

        # 2026-05-29: the ~46 per-Lambda ingestion-error-* alarms ($4.60/mo) were
        # removed (error_alarm=False in ingestion_stack). No aggregate replaces them:
        # CloudWatch rejects SEARCH in alarms and caps metric-math alarms at ~10
        # metrics (we have 19 ingestion fns). Sustained ingestion failure is already
        # caught downstream by the freshness-checker (stale data → SNS), the DLQ +
        # dlq-consumer (async failures), the canary (pipeline health), and the
        # remediation agent (per-Lambda diagnosis from logs). The per-Lambda alarms
        # mostly fired on transient self-healing errors — that was the noise.

        # ══════════════════════════════════════════════════════════════
        # OBS-01: DynamoDB throttling alarm
        # Any throttled requests means data is silently dropped.
        # ══════════════════════════════════════════════════════════════
        _alarm(
            "DdbThrottledRequests",
            "life-platform-ddb-throttled-requests",
            "AWS/DynamoDB",
            "ThrottledRequests",
            300,
            "Sum",
            1,
            GTE,
            {"TableName": "life-platform", "Operation": "PutItem"},
        )

        # ══════════════════════════════════════════════════════════════
        # DynamoDB item-size warning
        # ══════════════════════════════════════════════════════════════
        _alarm(
            "DdbItemSizeWarning",
            "life-platform-ddb-item-size-warning",
            "LifePlatform/DynamoDB",
            "ItemSizeBytes",
            300,
            "Maximum",
            307200,
            GTE,
            to_digest=True,
        )

        # ══════════════════════════════════════════════════════════════
        # OBS-09: SQS DLQ message count alarm
        # Any message in the DLQ means an ingestion Lambda failed all retries.
        # ══════════════════════════════════════════════════════════════
        _alarm(
            "IngestionDlqMessages",
            "life-platform-ingestion-dlq-messages",
            "AWS/SQS",
            "ApproximateNumberOfMessagesVisible",
            300,
            "Maximum",
            1,
            GTE,
            {"QueueName": "life-platform-ingestion-dlq"},
        )

        # ══════════════════════════════════════════════════════════════
        # OBS-02: Lambda memory utilization > 90% of limit
        # Only daily-brief (us-west-2) can be filtered here.
        # site-api log group is in us-east-1 — cross-region not supported.
        # REPORT line format: REPORT RequestId: X Duration: X ms Billed Duration: X ms
        #   Memory Size: X MB Max Memory Used: X MB [Init Duration: X ms]
        # Fields [0-indexed]: 0=REPORT 17=max_memory_used_mb
        # NOTE: dimensions and default_value are mutually exclusive in CWL MetricFilter.
        # ══════════════════════════════════════════════════════════════
        _report_pattern = '[w0="REPORT", w1, w2, w3, w4, w5, w6, w7, w8, w9, ' "w10, w11, w12, w13, w14, w15, w16, maxMem, ...]"
        db_log_group = logs.LogGroup.from_log_group_name(self, "MemFilerLgdailybrief", "/aws/lambda/daily-brief")
        db_mf = logs.MetricFilter(
            self,
            "MemFilterdailybrief",
            log_group=db_log_group,
            filter_pattern=logs.FilterPattern.literal(_report_pattern),
            metric_name="DailyBriefMaxMemoryMB",
            metric_namespace="LifePlatform/Lambda",
            metric_value="$maxMem",
        )
        mem_alarm_db = cloudwatch.Alarm(
            self,
            "MemoryHighdailybrief",
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
        _alarm(
            "S3BucketSizeHigh",
            "life-platform-s3-bucket-size-high",
            "AWS/S3",
            "BucketSizeBytes",
            86400,
            "Maximum",
            50 * 1024**3,
            GTE,
            {"BucketName": S3_BUCKET, "StorageType": "StandardStorage"},
            to_digest=True,
        )

        # ══════════════════════════════════════════════════════════════
        # 2026-06-09 (Tier-2 observability): three previously-UNWATCHED signals.
        # NB: per-Lambda *ingestion* alarms stay removed by design (see the
        # 2026-05-29 note above) — these are NOT that; they watch the self-healer,
        # the DLQ drainer, and the cost-governor, none of which had any alarm.
        # ══════════════════════════════════════════════════════════════
        # The self-healing remediation agent itself was unwatched — if its daily
        # run (~07:45 PT) errors, nobody hears. Digest (not page-worthy same-hour).
        _alarm(
            "RemediationDispatcherErrors",
            "life-platform-remediation-dispatcher-errors",
            "AWS/Lambda",
            "Errors",
            86400,
            "Sum",
            1,
            GTE,
            {"FunctionName": "life-platform-remediation-dispatcher"},
            to_digest=True,
        )

        # DLQ has a depth alarm, but if the dlq-consumer that drains it is broken,
        # failures pile up silently behind a firing depth alarm. Urgent.
        _alarm(
            "DlqConsumerErrors",
            "life-platform-dlq-consumer-errors",
            "AWS/Lambda",
            "Errors",
            300,
            "Sum",
            1,
            GTE,
            {"FunctionName": "life-platform-dlq-consumer"},
        )

        # Budget-tier escalation: tier >= 2 means website AI is paused (cost-governor,
        # ADR-063). The tier rides SSM + this metric, but nothing alerted on the jump.
        _alarm(
            "BudgetTierEscalation",
            "life-platform-budget-tier-escalation",
            "LifePlatform/Budget",
            "BudgetTier",
            3600,
            "Maximum",
            2,
            GTE,
            to_digest=True,
        )

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
        TOP_ROUTES = ["/api/vitals", "/api/healthz", "/api/character", "/api/snapshot", "/api/journey", "/api/platform_stats"]

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
            self,
            "SiteApiDashboard",
            dashboard_name="life-platform-site-api-dashboard",
            period_override=cloudwatch.PeriodOverride.AUTO,
            start="-PT1H",
        )

        # Row 1: Latency p50 + p95 for top 6 GET routes
        site_api_dash.add_widgets(
            cloudwatch.GraphWidget(
                title="Latency p50 (top routes, GET)",
                width=12,
                height=6,
                left=[_route_p_metric(r, "GET", "p50") for r in TOP_ROUTES],
                left_y_axis=cloudwatch.YAxisProps(label="ms", show_units=False),
            ),
            cloudwatch.GraphWidget(
                title="Latency p95 (top routes, GET)",
                width=12,
                height=6,
                left=[_route_p_metric(r, "GET", "p95") for r in TOP_ROUTES],
                left_y_axis=cloudwatch.YAxisProps(label="ms", show_units=False),
            ),
        )

        # Row 2: Cold-start count + total invocations
        site_api_dash.add_widgets(
            cloudwatch.GraphWidget(
                title="Cold starts per route (Sum, 5min)",
                width=12,
                height=6,
                left=[
                    cloudwatch.Metric(
                        namespace="LifePlatform/SiteAPI",
                        metric_name="ColdStart",
                        dimensions_map={"Route": r, "Method": "GET"},
                        statistic="Sum",
                        period=Duration.minutes(5),
                        label=r,
                    )
                    for r in TOP_ROUTES
                ],
            ),
            cloudwatch.GraphWidget(
                title="site-api Lambda — Errors + Invocations + Duration",
                width=12,
                height=6,
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
                width=8,
                height=4,
                metrics=[
                    cloudwatch.Metric(
                        namespace="LifePlatform/SiteAPI",
                        metric_name="DurationMs",
                        dimensions_map={"Route": r, "Method": "GET"},
                        statistic="SampleCount",
                        period=Duration.hours(1),
                        label=r,
                    )
                    for r in TOP_ROUTES
                ],
            ),
            cloudwatch.SingleValueWidget(
                title="Cold start rate (1h)",
                width=8,
                height=4,
                metrics=[
                    cloudwatch.Metric(
                        namespace="LifePlatform/SiteAPI",
                        metric_name="ColdStart",
                        dimensions_map={"Route": r, "Method": "GET"},
                        statistic="Sum",
                        period=Duration.hours(1),
                        label=r,
                    )
                    for r in TOP_ROUTES
                ],
            ),
        )

        # ══════════════════════════════════════════════════════════════
        # OPS-DASH (2026-06-09, Tier-2): the CDK-managed `life-platform-ops`
        # dashboard — replaces the hand-built console one (which was the headline
        # ops view but lived nowhere in code). The row that matters most is
        # ingestion health: the 2026 Garmin 44-day outage was caught by a MANUAL
        # audit, not an alarm — this surfaces a source that stops or starts erroring
        # on day 1. All metrics here are already emitted; this just composes them.
        # ══════════════════════════════════════════════════════════════
        COMPUTE_FNS = ["character-sheet-compute", "adaptive-mode-compute", "daily-metrics-compute", "daily-insight-compute", "daily-brief"]
        # SEARCH auto-discovers every ingestion Lambda (all 13 names contain "ingestion")
        # and graphs one line each — no hardcoded list to drift.
        _ingest_errors = cloudwatch.MathExpression(
            expression="SEARCH('{AWS/Lambda,FunctionName} MetricName=\"Errors\" ingestion', 'Sum', 300)",
            period=Duration.minutes(5),
            using_metrics={},
        )
        _ingest_invocations = cloudwatch.MathExpression(
            expression="SEARCH('{AWS/Lambda,FunctionName} MetricName=\"Invocations\" ingestion', 'Sum', 300)",
            period=Duration.minutes(5),
            using_metrics={},
        )

        def _lambda_metric(fn, metric_name, statistic="Sum", period_min=5):
            return cloudwatch.Metric(
                namespace="AWS/Lambda",
                metric_name=metric_name,
                dimensions_map={"FunctionName": fn},
                statistic=statistic,
                period=Duration.minutes(period_min),
                label=fn,
            )

        def _freshness_metric(metric_name, label, color):
            return cloudwatch.Metric(
                namespace="LifePlatform/Freshness",
                metric_name=metric_name,
                statistic="Maximum",
                period=Duration.hours(1),
                label=label,
                color=color,
            )

        ops_dash = cloudwatch.Dashboard(
            self,
            "OpsDashboard",
            dashboard_name="life-platform-ops",
            period_override=cloudwatch.PeriodOverride.AUTO,
            start="-PT24H",
        )

        # Row 1 — Ingestion freshness (aggregate source-health counts)
        ops_dash.add_widgets(
            cloudwatch.GraphWidget(
                title="Ingestion freshness — source counts (stale / warning / partial)",
                width=16,
                height=6,
                left=[
                    _freshness_metric("StaleSourceCount", "Stale (actionable)", cloudwatch.Color.RED),
                    _freshness_metric("WarningSourceCount", "Warning", cloudwatch.Color.ORANGE),
                    _freshness_metric("PartialCompletenessCount", "Partial fields", cloudwatch.Color.BLUE),
                ],
            ),
            cloudwatch.SingleValueWidget(
                title="Stale sources (now)",
                width=8,
                height=6,
                metrics=[_freshness_metric("StaleSourceCount", "stale", cloudwatch.Color.RED)],
            ),
        )

        # Row 2 — Per-source ingestion Lambda health (SEARCH-discovered, one line per source)
        ops_dash.add_widgets(
            cloudwatch.GraphWidget(
                title="Ingestion Lambda errors per source (Sum 5min) — a source going dark shows here",
                width=12,
                height=6,
                left=[_ingest_errors],
            ),
            cloudwatch.GraphWidget(
                title="Ingestion Lambda invocations per source (Sum 5min)",
                width=12,
                height=6,
                left=[_ingest_invocations],
            ),
        )

        # Row 3 — Compute pipeline (the daily-brief dependency chain)
        ops_dash.add_widgets(
            cloudwatch.GraphWidget(
                title="Compute pipeline — duration p99 (ms)",
                width=12,
                height=6,
                left=[_lambda_metric(fn, "Duration", "p99") for fn in COMPUTE_FNS],
                left_y_axis=cloudwatch.YAxisProps(label="ms", show_units=False),
            ),
            cloudwatch.GraphWidget(
                title="Compute pipeline — errors (Sum 1h)",
                width=12,
                height=6,
                left=[_lambda_metric(fn, "Errors", "Sum", period_min=60) for fn in COMPUTE_FNS],
            ),
        )

        # Row 4 — AI spend + budget tier (cost-governor)
        ops_dash.add_widgets(
            cloudwatch.GraphWidget(
                title="AI output tokens (Sum 1h) + projected month-end spend ($)",
                width=12,
                height=6,
                left=[
                    cloudwatch.Metric(
                        namespace="LifePlatform/AI",
                        metric_name="AnthropicOutputTokens",
                        statistic="Sum",
                        period=Duration.hours(1),
                        label="output tokens",
                    )
                ],
                right=[
                    cloudwatch.Metric(
                        namespace="LifePlatform/Budget",
                        metric_name="ProjectedMonthlySpend",
                        statistic="Maximum",
                        period=Duration.hours(1),
                        label="projected $/mo",
                        color=cloudwatch.Color.ORANGE,
                    )
                ],
                right_y_axis=cloudwatch.YAxisProps(label="USD", show_units=False),
            ),
            cloudwatch.GraphWidget(
                title="Budget tier (0 normal → 3 hard cutoff)",
                width=12,
                height=6,
                left=[
                    cloudwatch.Metric(
                        namespace="LifePlatform/Budget",
                        metric_name="BudgetTier",
                        statistic="Maximum",
                        period=Duration.hours(1),
                        label="tier",
                        color=cloudwatch.Color.ORANGE,
                    )
                ],
                left_y_axis=cloudwatch.YAxisProps(min=0, max=3, show_units=False),
            ),
        )

        # Row 5 — Ingestion DLQ depth + consumer health
        ops_dash.add_widgets(
            cloudwatch.GraphWidget(
                title="Ingestion DLQ — depth + consumer health",
                width=24,
                height=6,
                left=[
                    cloudwatch.Metric(
                        namespace="AWS/SQS",
                        metric_name="ApproximateNumberOfMessagesVisible",
                        dimensions_map={"QueueName": "life-platform-ingestion-dlq"},
                        statistic="Maximum",
                        period=Duration.minutes(5),
                        label="DLQ depth",
                        color=cloudwatch.Color.RED,
                    )
                ],
                right=[
                    _lambda_metric("life-platform-dlq-consumer", "Errors", "Sum"),
                    _lambda_metric("life-platform-dlq-consumer", "Invocations", "Sum"),
                ],
            ),
        )
