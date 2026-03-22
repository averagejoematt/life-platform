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

GTE = cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD
LT  = cloudwatch.ComparisonOperator.LESS_THAN_THRESHOLD
NB  = cloudwatch.TreatMissingData.NOT_BREACHING


class MonitoringStack(Stack):

    def __init__(self, scope, construct_id: str, alerts_topic: sns.ITopic, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        topic = sns.Topic.from_topic_arn(self, "AlertsTopic", ALERTS_TOPIC_ARN)

        def _alarm(alarm_id, alarm_name, namespace, metric_name, period_sec,
                   statistic, threshold, operator, dims=None, ext_stat=None):
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
            a.add_alarm_action(cw_actions.SnsAction(topic))
            return a

        # ══════════════════════════════════════════════════════════════
        # SLO alarms
        # ══════════════════════════════════════════════════════════════
        _alarm("SloDailyBriefDelivery",   "slo-daily-brief-delivery",
               "AWS/Lambda", "Errors", 86400, "Sum", 1, GTE,
               {"FunctionName": "daily-brief"})

        _alarm("SloAiCoachingSuccess",    "slo-ai-coaching-success",
               "LifePlatform/AI", "AnthropicAPIFailure", 86400, "Sum", 3, GTE)

        _alarm("SloSourceFreshness",      "slo-source-freshness",
               "LifePlatform/Freshness", "StaleSourceCount", 86400, "Maximum", 1, GTE)

        # ══════════════════════════════════════════════════════════════
        # Daily-brief operational alarms (not in EmailStack)
        # ══════════════════════════════════════════════════════════════
        _alarm("DailyBriefDurationHigh",  "daily-brief-duration-high",
               "AWS/Lambda", "Duration", 86400, None, 240000, GTE,
               {"FunctionName": "daily-brief"}, ext_stat="p99")

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
        _alarm("AiTokensDailyBriefDaily",
               "ai-tokens-daily-brief-daily",
               "LifePlatform/AI", "AnthropicOutputTokens", 86400, "Sum", 13333, GTE,
               {"LambdaFunction": "daily-brief"})

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
               "LifePlatform/DynamoDB", "ItemSizeBytes", 300, "Maximum", 307200, GTE)

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
        mem_alarm_db.add_alarm_action(cw_actions.SnsAction(topic))

        # ══════════════════════════════════════════════════════════════
        # OBS-08: S3 bucket storage size alarm
        # BucketSizeBytes is a daily metric — period must be 86400s.
        # Alerts if raw/ accumulation exceeds 50 GB unexpectedly.
        # ══════════════════════════════════════════════════════════════
        _alarm("S3BucketSizeHigh",        "life-platform-s3-bucket-size-high",
               "AWS/S3", "BucketSizeBytes", 86400, "Maximum", 50 * 1024 ** 3, GTE,
               {"BucketName": S3_BUCKET, "StorageType": "StandardStorage"})

        # NOTE: OBS-07 email-subscriber alarm lives in web_stack.py (us-east-1).
        # email-subscriber Lambda runs in us-east-1; Lambda metrics are regional.
        # Cross-region alarm would never fire. See web_stack.py SubscriberErrors alarm.

        # OBS-04: site-api cold start alarm deferred — site-api Lambda and its
        # log group (/aws/lambda/site-api) are in us-east-1; MonitoringStack is
        # in us-west-2. Cross-region MetricFilter is not supported.
        # Implement in a separate us-east-1 monitoring construct when needed.
