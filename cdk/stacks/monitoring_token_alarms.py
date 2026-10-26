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
#5135 adds the one MONTHLY alarm in the family, `ai-dev-session-month-high` (the dev-session
envelope, last in `add_token_alarms`): same question — is AI spend over its bar — asked of one
caller class over its calendar month, and deliberately outside the genesis-window shielding.

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

# ── #4517: the two daily-Sum thresholds, DERIVED from his own variance (ADR-105 rule 4) ──
#
# What the alarm evaluates. A Sum over an 86400 s period is a ROLLING 24 h window, re-read
# every minute, not a calendar day. A calendar-day sum understates it, so the sample below is the
# statistic the alarm actually sees: each UTC day's MAXIMUM of the rolling-24 h Sum, computed from
# 5-minute LifePlatform/AI datapoints (read-only get-metric-statistics, 2026-10-01). There is one
# value per day, which keeps 288 overlapping windows a day from counting as independent samples.
#
# Why log-normal. Spend and tokens are positive and right-skewed. On this sample the skew is
# +1.37 (dollars) and +0.98 (tokens) raw, and +0.17 and -0.06 after a log. A normal mean + 3 SD
# on the raw days puts the bar BELOW the old one ($5.60 vs $6, 240,911 vs 250,000) and would
# page more, not less. So the bar is mean + 3 SD in log space, which is the fitted 99.87th
# percentile: an expected ~0.04 pages per 30 days on this distribution.
#
# Backtest (the #4517 PR body, 5-minute rolling replay). Replaying the old $6 / 250,000 against
# this window reproduced both live 09-30 episodes to within 5 minutes (describe-alarm-history). At
# the derived bars there are 0 crossings from 09-01 to 10-01 18:30Z.
# tests/test_token_alarm_composite_2116.py pins each threshold to this derivation and keeps it above
# the sample's own maximum, which is what "0 crossings over the window" means for this statistic.
#
# THE BASELINE IS MOVING. The last week (09-26..09-30) holds the five highest dollar days, and a bar
# derived on 09-01..09-20 alone ($5.95) would still have paged on 09-30. Re-derive from a fresh
# trailing 30 days when the week-over-week geometric mean moves more than 25 %, and on 2026-11-01
# regardless (the docs/PROPORTIONALITY.md budget-governor row carries the trigger).
AI_ALARM_DERIVATION_WINDOW = ("2026-09-01", "2026-09-30")
AI_ALARM_DERIVATION_K_SD = 3
AI_SPEND_DAILY_MAX_ROLLING_24H_USD = (
    ("09-01", 3.37), ("09-02", 3.528), ("09-03", 3.247), ("09-04", 2.384), ("09-05", 2.297),
    ("09-06", 2.561), ("09-07", 2.561), ("09-08", 2.052), ("09-09", 1.592), ("09-10", 1.385),
    ("09-11", 1.369), ("09-12", 1.345), ("09-13", 2.501), ("09-14", 2.559), ("09-15", 2.163),
    ("09-16", 3.013), ("09-17", 3.02), ("09-18", 2.143), ("09-19", 3.19), ("09-20", 3.113),
    ("09-21", 2.9), ("09-22", 1.912), ("09-23", 2.88), ("09-24", 2.927), ("09-25", 2.609),
    ("09-26", 3.554), ("09-27", 4.7), ("09-28", 5.272), ("09-29", 5.061), ("09-30", 6.862),
)  # fmt: skip
AI_TOKENS_DAILY_MAX_ROLLING_24H = (
    ("09-01", 149182), ("09-02", 172360), ("09-03", 167518), ("09-04", 138153), ("09-05", 129008),
    ("09-06", 119692), ("09-07", 119700), ("09-08", 102622), ("09-09", 87389), ("09-10", 77980),
    ("09-11", 78507), ("09-12", 77670), ("09-13", 143801), ("09-14", 156481), ("09-15", 115674),
    ("09-16", 132606), ("09-17", 128863), ("09-18", 117771), ("09-19", 157363), ("09-20", 180626),
    ("09-21", 170365), ("09-22", 117125), ("09-23", 139005), ("09-24", 138587), ("09-25", 132660),
    ("09-26", 150642), ("09-27", 195597), ("09-28", 212378), ("09-29", 200604), ("09-30", 282563),
)  # fmt: skip


def lognormal_upper_bound(sample, k_sd=AI_ALARM_DERIVATION_K_SD) -> float:
    """exp(mean(ln x) + k·SD(ln x)) over the (label, value) pairs: the personal-variance bar."""
    import math
    import statistics

    logs = [math.log(v) for _, v in sample]
    return math.exp(statistics.mean(logs) + k_sd * statistics.stdev(logs))


AI_SPEND_VARIANCE_BAR_USD = round(lognormal_upper_bound(AI_SPEND_DAILY_MAX_ROLLING_24H_USD), 2)  # 8.72 (n=30)
AI_TOKENS_VARIANCE_BAR = int(round(lognormal_upper_bound(AI_TOKENS_DAILY_MAX_ROLLING_24H), -3))  # 337,000 (n=30)


# ── #4517 (2026-10-24): the BUDGET bar, read from the governor, and the threshold is the higher ──
#
# The variance bar above answers "is today unusual for HIM", and on a quiet September that put the
# dollar bar at $8.72 — 23 % above the base ceiling's own daily allowance (base / 30.44 days) and
# BELOW the October window's (the dated raise in cost_governor_lambda.py). A day spent exactly at
# the ceiling's pace is the plan, not an anomaly, and a bar under it pages on the plan.
#
# So the urgent page also has to clear a bar the BUDGET defines. It is the narrowest rung of the
# governor's own tier ladder (the bands are fixed fractions of the ceiling: tier 2 → tier 3 is
# 8/75 of it) times the permanent base ceiling: one rolling day that, on top of everything else,
# carries the month's spend across a whole tier band on its own. That is a runaway the governor's
# 8-hourly tiering would only answer after the fact, which is what an urgent page is for.
#
# Why the BASE ceiling and not the dated window's. This is resolved at cdk-synth time, and the window
# reverts on its own date with no deploy. A bar minted from the window would sit at the window's
# height after the revert until someone re-applied Monitoring — stale in the loose direction. The base
# is the number the AWS Budgets backstop (core_stack.py) already reads for the same reason. A base
# change moves this bar on the next `cdk_deploy.sh LifePlatformMonitoring` (the drift guard shows it).
#
# The token bar is the SAME dollar bar in output tokens, priced at the dearest output rate the
# chokepoint bills (ai.bedrock_client.PRICES). Output tokens alone at that rate reach the bar, so it
# never pages before the dollar bar would on correctly-priced traffic. It stays as an independent meter:
# tokens are counted even where EstimatedCostUSD under-prices a call (#2883's drift class).
#
# Replay (5-minute LifePlatform/AI Sums, 2026-09-02..10-24, read-only get-metric-statistics, validated
# against describe-alarm-history to within 5 minutes): both bars page on the same two episodes as the
# variance bars did — the 10-01 day ($36.59 rolling peak, 940,414 tokens) and the 10-18 dev-session day
# ($31.39, 602,639) — and on nothing else; the spend page on 10-18 lasts 11.0 h instead of 37.1 h.


def _budget_ceilings():
    """`scripts/budget_ceilings.py`, loaded BY PATH — core_stack.py's idiom and reasons (#2898)."""
    import importlib.util
    from pathlib import Path

    src = Path(__file__).resolve().parents[2] / "scripts" / "budget_ceilings.py"
    spec = importlib.util.spec_from_file_location("_cdk_budget_ceilings_4517", src)
    if spec is None or spec.loader is None:  # pragma: no cover - a missing file is a broken checkout
        raise RuntimeError(f"cannot load the budget-ceiling derivation from {src} (#4517)")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_BUDGET = _budget_ceilings()
AI_SPEND_BUDGET_BAR_USD = round(_BUDGET.base_ceiling_usd() * _BUDGET.narrowest_rung_fraction(), 2)  # 22.93
AI_TOKENS_BUDGET_BAR = int(round(AI_SPEND_BUDGET_BAR_USD / _BUDGET.dearest_output_usd_per_mtok() * 1_000_000, -3))  # 459,000

AI_DAILY_SPEND_THRESHOLD_USD = max(AI_SPEND_VARIANCE_BAR_USD, AI_SPEND_BUDGET_BAR_USD)
AI_TOKENS_PLATFORM_DAILY_THRESHOLD = max(AI_TOKENS_VARIANCE_BAR, AI_TOKENS_BUDGET_BAR)

# #5135: the dev-session envelope's alarm bar — 80 % of the owner's $60 calendar month (ruling
# 2026-10-26), read out of lambdas/ai/dev_session_cap.py, which owns both numbers and enforces the cap.
DEV_SESSION_MONTH_ALARM_USD = _BUDGET.dev_session_month_alarm_usd()  # 48.0


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

    # Platform-level total (no dims). 2026-10-24 (#4517): 337,000 → 459,000, the budget bar in output
    # tokens (top of this module); the variance bar stays as its floor. 2026-10-01 (#4517): 250000 →
    # 337,000, derived on the ROLLING-24h statistic. It fired twice on 09-30, and the calendar-day
    # estimators below never saw the rolling peak.
    # 2026-09-04 (#3474): 150000 → 250000, re-derived (ADR-105). Set in 2026-06
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
        threshold=AI_TOKENS_PLATFORM_DAILY_THRESHOLD,
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
    # 2026-10-24 (#4517): $8.72 → $22.93, the budget bar (narrowest governor rung × base ceiling, top
    # of this module), because $8.72 sat under the ceiling's own daily pace.
    # 2026-10-01 (#4517): $6.0 → $8.72, the variance bar derived at the top of this
    # module. The "~$1.3/day normal" above is history. The measured 09-01..09-30 rolling-24h daily
    # max has a geometric mean of $2.73, and $6 paged twice on the ordinary 09-30 (brief + AI-vision QA + dry runs).
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
        alarm_description=(
            "Daily total of estimated AI spend (LifePlatform/AI EstimatedCostUSD, Sum over a 24h period) "
            "at or above the daily budget bar. Routes via the -urgent / -genesis-window composites."
        ),
        metric=cloudwatch.Metric(
            namespace="LifePlatform/AI",
            metric_name="EstimatedCostUSD",
            period=Duration.seconds(86400),
            statistic="Sum",
        ),
        evaluation_periods=1,
        threshold=AI_DAILY_SPEND_THRESHOLD_USD,
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

    # #5135: the DEV-SESSION ENVELOPE, separate from the production daily-total alarms above.
    # Those watch the whole platform's rolling 24 h; this watches one class's calendar month: laptop
    # and agent AI (CallerClass=dev-session, the MCP Lambda's dev calls included) against the owner's
    # $60 a month. CloudWatch cannot sum a calendar month, so the metric is the cost governor's
    # `DevSessionSpendMTD` gauge (published every 8 h; a period of one governor cadence, Maximum).
    # The cap in lambdas/ai/dev_session_cap.py refuses at $60 on its own; this tells the owner at
    # $48 that the month is most of the way spent. Digest, not urgent: nothing a reader sees is at
    # risk, and the cap is already holding the line. Missing data (governor down) is NOT_BREACHING;
    # the governor has its own heartbeat and DLQ alarms. The gauge resets on the 1st, which clears it.
    _token_alarm(
        "AiDevSessionMonthHigh",
        "ai-dev-session-month-high",
        "LifePlatform/Budget",
        "DevSessionSpendMTD",
        28800,
        "Maximum",
        DEV_SESSION_MONTH_ALARM_USD,
        GTE,
        to_digest=True,
    )
