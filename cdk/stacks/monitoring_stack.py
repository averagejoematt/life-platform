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
"""

import aws_cdk as cdk
from aws_cdk import (
    Stack,
    Duration,
    aws_cloudwatch as cloudwatch,
    aws_cloudwatch_actions as cw_actions,
    aws_sns as sns,
)
from constructs import Construct

REGION = "us-west-2"
ACCT   = "205930651321"
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
        # DynamoDB item-size warning
        # ══════════════════════════════════════════════════════════════
        _alarm("DdbItemSizeWarning",      "life-platform-ddb-item-size-warning",
               "LifePlatform/DynamoDB", "ItemSizeBytes", 300, "Maximum", 307200, GTE)
