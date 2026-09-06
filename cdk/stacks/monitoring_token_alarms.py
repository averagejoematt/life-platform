"""cdk/stacks/monitoring_token_alarms.py — the AI token + spend alarm family (#3505).

Extraction seam, same one as monitoring_dashboards.py (#2610), monitoring_budget_alarms.py
(#2824), monitoring_silence_alarms.py (#2977) and monitoring_prediction_alarms.py (#727):
monitoring_stack.py sits at its module-size ratchet cap (tests/test_module_size_guard.py),
and the standing rule is to pay for new lines out of a cohesive sibling rather than raise
the number. #3505 needed both a reshaped brief-token alarm and two new composite alarms,
which is 60+ lines the parent file does not have.

The cut is by CONCERN, not by line count. Everything here answers one question — "is the
platform's AI spend, in tokens or in dollars, anomalous TODAY, and is today a day where an
anomaly was predicted?" — and the four raw alarms share one shielding mechanism (the
genesis-window gauge and the composite pairs built on it), so splitting them across two
files is what would be arbitrary.

CONSTRUCT IDS ARE UNCHANGED, deliberately. Every construct below is created against the
`scope` passed in — the stack itself — with the same construct id it had inside
MonitoringStack.__init__, so the synthesized logical ids are identical and this extraction
deploys as a no-op for the three alarms it does not otherwise change. The one exception is
`ai-tokens-daily-brief-daily` -> `ai-tokens-daily-brief-runaway`, which is a deliberate
rename (see its comment) and therefore a delete+create.

READERS: every static reader of these alarms searches the whole `cdk/stacks` tree rather
than naming a file (tests/cdk_alarm_pins.py's #2977 rule: "search the whole tree, name no
file" — a guard that reads a named file which no longer holds the thing it guards still
runs, still passes on the half it can see, and proves nothing). #3505 widened the two that
still named monitoring_stack.py; deploy/alarm_discovery.py and
scripts/platform_model_alarms.py already globbed the tree.
"""

from aws_cdk import (
    Duration,
    aws_cloudwatch as cloudwatch,
    aws_cloudwatch_actions as cw_actions,
)

GTE = cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD
NB = cloudwatch.TreatMissingData.NOT_BREACHING


def add_token_alarms(scope, topic, digest) -> None:
    """Declare the AI token/spend alarms on `scope`.

    `topic` is the URGENT SNS topic (life-platform-alerts, which carries a direct human
    email subscription); `digest` is the overnight digest topic. Both are passed in rather
    than re-imported so this module has no opinion about ARNs — the parent stack owns them.
    """

    def _token_alarm(alarm_id, alarm_name, namespace, metric_name, period_sec, statistic, threshold, operator, dims=None, to_digest=False):
        """The parent stack's `_alarm` closure, narrowed to what this family uses.

        Named `_token_alarm`, not `_alarm`: scripts/platform_model_alarms.py resolves an
        alarm factory by BARE NAME across every stack module, so a second `_alarm` in the
        tree would let one module's alarms be routed by another module's helper body.
        tests/test_boot_contract_3314.py::test_stack_helper_names_are_unique pins that,
        and caught this exact collision while #3505 was being written.

        Same construct shape (evaluation_periods=1, no datapoints_to_alarm, NOT_BREACHING)
        so a moved alarm's synthesized template is byte-identical apart from what #3505
        deliberately changed.
        """
        a = cloudwatch.Alarm(
            scope,
            alarm_id,
            alarm_name=alarm_name,
            metric=cloudwatch.Metric(
                namespace=namespace,
                metric_name=metric_name,
                dimensions_map=dims or {},
                period=Duration.seconds(period_sec),
                statistic=statistic,
            ),
            evaluation_periods=1,
            threshold=threshold,
            comparison_operator=operator,
            treat_missing_data=NB,
        )
        a.add_alarm_action(cw_actions.SnsAction(digest if to_digest else topic))
        return a

    # AI token budget alarms — consolidated 2026-03-10 (COST-A)
    # Removed 11 per-Lambda alarms ($1.10/mo). Kept: daily-brief
    # (highest-cost Lambda) + platform total (catch-all).
    # ══════════════════════════════════════════════════════════════
    # Threshold history while it was a daily Sum: 13333 → 18000 (2026-05-03) →
    # 30000 (2026-05-28, normal usage having crept to ~18003 on 8 coach V2
    # narratives). SUPERSEDED 2026-09-05 by the reshape below.
    #
    # #3505: RESHAPED, not re-thresholded. Sum over 86400s measures how many times
    # the brief RAN, not how big any one run got: the 2026-09-04 flap was three
    # ordinary runs in one window (09-03 10:00 PT scheduled 13,566 + 09-03 20:00 PT
    # reset regen 8,971 + 09-04 09:00 PT re-anchor regen 8,384 = 30,921), a process
    # that RECURS on every reset and costs a hand-written #2912 citation each time —
    # while the runaway it was built for stayed invisible, because per-call output is
    # capped by max_tokens so a runaway prompt lands as MORE CALLS, not bigger ones.
    # Re-derived from the metric's own distribution (ADR-105), n=71 hourly Sum points
    # over the 35 days to 2026-09-05: median 4,717 · Q3 7,664 · max 31,970. Period
    # 3600s is ONE run's own window (the brief finishes in minutes), so two runs on a
    # day land in different windows and the reset mechanism is gone, not suppressed.
    # 35,000 sits above every hourly point in that window including the three
    # multi-run reset hours (31,970/98 calls 08-03, 29,911/92 08-09, 22,948/71 08-17)
    # against a normal run's 20-30 calls and ~9-13k tokens: fire rate 0/71 over 35d.
    # RENAMED because it is no longer daily — a name that says "daily" about an hourly
    # window is the same stale label as the "(13)" #3505 fixed in the parent docstring.
    _token_alarm(
        "AiTokensDailyBriefRunaway",
        "ai-tokens-daily-brief-runaway",
        "LifePlatform/AI",
        "AnthropicOutputTokens",
        3600,
        "Sum",
        35000,
        GTE,
        {"LambdaFunction": "daily-brief"},
        to_digest=True,
    )

    # Platform-level total (no dims). 2026-09-04 (#3474): 150000 → 250000, re-derived (ADR-105). Set in 2026-06
    # against a ~59k/day baseline peaking ~121k, 150000 had become the platform's
    # 75th PERCENTILE and fired on the ordinary working day. n=31 daily Sums to
    # 2026-09-02: median 87,046 · Q3 145,161 · max 492,314, every breach on a
    # working session — so the question is "anomalous for THIS distribution", and
    # two robust estimators bracket it: Tukey Q3+1.5·IQR = 260,014, median+3·MAD·
    # 1.4826 = 221,743. Fire rate 25.8% [13.7%, 43.2%] → 9.7% [3.3%, 24.9%] n=31,
    # i.e. 7.7 → 2.9 per 30d. NOT a budget guard: 250k/day of output is ~$112/mo
    # at sonnet's $15/1M against a $215 ceiling — sustained burn is cost_governor's
    # tiering; this is the single-day outlier detector beside it.
    #
    # #1961 -> #2116: a genesis's predictable post-reset full-cycle rebuild spike
    # (character sheet + compute + coach dossiers + chronicle backfill regenerating
    # at once) can clear the threshold and page exactly like an unexplained runaway
    # (cycle 11 did, twice). #2114 fixed the automated remediation-triage escalation
    # (`lambdas/common/token_alarm_window.py`, consulted by
    # remediation_dispatcher_lambda.py) but left this alarm's own SNS action routed
    # straight to the urgent topic — a predicted spike still emailed the operator.
    # Mechanism: cost_governor_lambda (on its existing 8h cron, no new schedule,
    # #781) publishes a LifePlatform/AI::TokenAlarmGenesisWindowActive 1/0 gauge
    # from the SAME stamped window the dispatcher consults; the raw alarm below
    # carries NO SNS action and exists only as a signal for two composites:
    #   ai-tokens-platform-daily-total-urgent          breach AND NOT in-window -> urgent
    #   ai-tokens-platform-daily-total-genesis-window  breach AND     in-window -> digest
    # (#3505 applies the identical shape to ai-daily-spend-high below.)
    ai_tokens_platform_metric = cloudwatch.Metric(
        namespace="LifePlatform/AI",
        metric_name="AnthropicOutputTokens",
        period=Duration.seconds(86400),
        statistic="Sum",
    )
    ai_tokens_platform_alarm = cloudwatch.Alarm(
        scope,
        "AiTokensPlatformTotal",
        alarm_name="ai-tokens-platform-daily-total",
        metric=ai_tokens_platform_metric,
        evaluation_periods=1,
        threshold=250000,
        comparison_operator=GTE,
        treat_missing_data=NB,
    )

    # The window-gauge sub-alarm — NOT itself routed to any topic; it exists
    # only to give the composite alarms below a boolean ALARM/OK state to
    # combine with the threshold breach. Period matches cost_governor's 8h
    # cadence. Missing data (gauge hasn't published recently) is
    # NOT_BREACHING, i.e. "assume not in window" — the same fail-safe
    # direction as token_alarm_window.py's own malformed-stamp handling: a
    # missing/stale gauge must never silently suppress a real page.
    genesis_window_metric = cloudwatch.Metric(
        namespace="LifePlatform/AI",
        metric_name="TokenAlarmGenesisWindowActive",
        period=Duration.seconds(28800),
        statistic="Maximum",
    )
    genesis_window_alarm = cloudwatch.Alarm(
        scope,
        "TokenAlarmGenesisWindowActive",
        alarm_name="token-alarm-genesis-window-active",
        metric=genesis_window_metric,
        evaluation_periods=1,
        threshold=1,
        comparison_operator=GTE,
        treat_missing_data=NB,
    )

    _token_platform_breach = cloudwatch.AlarmRule.from_alarm(ai_tokens_platform_alarm, cloudwatch.AlarmState.ALARM)
    _in_genesis_window = cloudwatch.AlarmRule.from_alarm(genesis_window_alarm, cloudwatch.AlarmState.ALARM)

    ai_tokens_platform_urgent = cloudwatch.CompositeAlarm(
        scope,
        "AiTokensPlatformUrgent",
        composite_alarm_name="ai-tokens-platform-daily-total-urgent",
        alarm_rule=cloudwatch.AlarmRule.all_of(_token_platform_breach, cloudwatch.AlarmRule.not_(_in_genesis_window)),
    )
    ai_tokens_platform_urgent.add_alarm_action(cw_actions.SnsAction(topic))

    ai_tokens_platform_in_window = cloudwatch.CompositeAlarm(
        scope,
        "AiTokensPlatformInGenesisWindow",
        composite_alarm_name="ai-tokens-platform-daily-total-genesis-window",
        alarm_rule=cloudwatch.AlarmRule.all_of(_token_platform_breach, _in_genesis_window),
    )
    ai_tokens_platform_in_window.add_alarm_action(cw_actions.SnsAction(digest))

    # G2: daily AI-spend ceiling — the anomaly guard. EstimatedCostUSD is
    # emitted (dimensionless) at the bedrock_client chokepoint (G1), so this
    # SUM covers EVERY AI call platform-wide, not just the daily brief.
    # Normal is ~$1.3/day; weekly-digest/podcast days add ~$1-2. $6/day is a
    # ~4x runaway (≈$180/mo pace) — well clear of legitimate peaks. URGENT
    # (not digest): a cost runaway should page promptly, not batch overnight.
    # Future: swap to a CloudWatch anomaly-detection band once this metric
    # has ~2 weeks of history to train on.
    #
    # #3505: a daily SUM, so a reset day's regen burst adds to it exactly like a
    # runaway would — and unlike the token alarms this one is routed URGENT, to a
    # topic carrying a direct human EmailSubscription (it flapped 08-10→11 and twice
    # on 08-23 for that reason). A daily dollar ceiling IS a daily sum, so it cannot
    # be re-periodised the way the brief alarm above was; it takes the #2116
    # treatment verbatim instead — the raw alarm carries NO SNS action and two
    # composites combine it with the SAME genesis gauge the platform total consults:
    #   ai-daily-spend-high-urgent          breach AND NOT in-window -> urgent
    #   ai-daily-spend-high-genesis-window  breach AND     in-window -> digest
    # A predicted reset spend is recorded, never paged; an out-of-window breach pages
    # exactly as today. The gauge fails SAFE (missing data = NOT_BREACHING = "assume
    # not in window"), so a stale gauge can never silently suppress a real page.
    ai_daily_spend_alarm = cloudwatch.Alarm(
        scope,
        "AiDailySpendHigh",
        alarm_name="ai-daily-spend-high",
        metric=cloudwatch.Metric(
            namespace="LifePlatform/AI",
            metric_name="EstimatedCostUSD",
            period=Duration.seconds(86400),
            statistic="Sum",
        ),
        evaluation_periods=1,
        threshold=6.0,
        comparison_operator=GTE,
        treat_missing_data=NB,
    )
    _ai_daily_spend_breach = cloudwatch.AlarmRule.from_alarm(ai_daily_spend_alarm, cloudwatch.AlarmState.ALARM)

    ai_daily_spend_urgent = cloudwatch.CompositeAlarm(
        scope,
        "AiDailySpendHighUrgent",
        composite_alarm_name="ai-daily-spend-high-urgent",
        alarm_rule=cloudwatch.AlarmRule.all_of(_ai_daily_spend_breach, cloudwatch.AlarmRule.not_(_in_genesis_window)),
    )
    ai_daily_spend_urgent.add_alarm_action(cw_actions.SnsAction(topic))

    ai_daily_spend_in_window = cloudwatch.CompositeAlarm(
        scope,
        "AiDailySpendHighInGenesisWindow",
        composite_alarm_name="ai-daily-spend-high-genesis-window",
        alarm_rule=cloudwatch.AlarmRule.all_of(_ai_daily_spend_breach, _in_genesis_window),
    )
    ai_daily_spend_in_window.add_alarm_action(cw_actions.SnsAction(digest))
