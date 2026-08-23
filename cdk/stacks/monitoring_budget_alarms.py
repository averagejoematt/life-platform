"""cdk/stacks/monitoring_budget_alarms.py — the budget-integrity alarm (#2824, DIL-036).

Same extraction seam as the dashboards (#2610) and the prediction-science alarms
(#727/#3046): monitoring_stack.py sits at its exact module-size ratchet cap, so new
alarm surface lands in a cohesive sibling invoked from the same scope, same order.

What this watches: `lambdas/ai/budget_guard._read_tier()` logs the stable token
`BUDGET_TIER_UNREADABLE reason=<class>` at ERROR whenever the SSM budget-tier read
fails (ParameterNotFound / ClientError.AccessDeniedException / Unexpected.<Type>).
Pre-#2824 that failure was a bare `except Exception: tier = 0` — an IAM grant
regression, a deleted param, or an SSM outage silently disabled the entire monthly
ceiling, including for the PUBLIC anonymous endpoints, and nothing paged.

Scope: the metric filter targets ONLY the log group of the ENFORCING public
consumer — life-platform-site-api-ai (/api/ask + /api/board_ask + /api/explain,
feature `website_ai`, which now fails CLOSED on unreadable state). budget_guard is
bundled fleet-wide (#781) and every consumer logs the token, but the fleet's other
consumers deliberately stay fail-open (protect-longest, ADR-125) and metering all
~104 log groups would buy noise, not signal: the public surface is both where the
attacker-facing risk was and where an unreadable tier now visibly changes behavior
(readers get the honest 'paused' output — this alarm is what tells the operator
WHY). Logs-based by design — no PutMetricData from the Lambda, which would trip the
put_metric_data grant-lockstep set without an IAM change.
"""

from aws_cdk import (
    Duration,
    aws_cloudwatch as cloudwatch,
    aws_cloudwatch_actions as cw_actions,
    aws_logs as logs,
)

# Must equal the literal budget_guard._read_tier() logs — pinned by
# tests/test_budget_guard_fail_closed_2824.py so the two can never drift apart.
UNREADABLE_TOKEN = "BUDGET_TIER_UNREADABLE"  # noqa: S105 — a log token, not a credential

_SITE_API_AI_LOG_GROUP = "/aws/lambda/life-platform-site-api-ai"


def add_budget_alarms(scope, digest) -> None:
    """budget-tier-unreadable: ≥1 unreadable-state ERROR in an hour on the public
    AI path → digest. One log line == one failed refresh (the guard caches the
    unreadable result for its 5-min TTL, so a real outage produces a steady
    ~1 line/5 min/container, comfortably over threshold, while a single transient
    blip that recovers on the next refresh still surfaces — that single blip is
    exactly one denied-by-fail-closed public window and must not be silent).
    treat_missing_data=NOT_BREACHING: absence of the token is health, and a dead
    site-api-ai lambda is the throttle/5xx alarms' job, not this one's.
    """
    lg = logs.LogGroup.from_log_group_name(scope, "BudgetUnreadableLgSiteApiAi", _SITE_API_AI_LOG_GROUP)
    mf = logs.MetricFilter(
        scope,
        "BudgetUnreadableMfSiteApiAi",
        log_group=lg,
        filter_pattern=logs.FilterPattern.literal(f'"{UNREADABLE_TOKEN}"'),
        metric_namespace="LifePlatform/Budget",
        metric_name="BudgetTierUnreadable",
        metric_value="1",
    )
    unreadable = cloudwatch.Alarm(
        scope,
        "BudgetTierUnreadable",
        alarm_name="budget-tier-unreadable",
        metric=mf.metric(period=Duration.seconds(3600), statistic="Sum"),
        evaluation_periods=1,
        datapoints_to_alarm=1,
        threshold=1,
        comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
        treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
    )
    unreadable.add_alarm_action(cw_actions.SnsAction(digest))
