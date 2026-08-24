"""cdk/stacks/monitoring_silence_alarms.py — the **fail-soft silence** alarms of MonitoringStack.

Extracted from ``monitoring_stack.py`` by #2977, on the seam that module's own comments
had already drawn twice ("the #2654 silence shape"). One cohesive concern:

    A Lambda swallows a failure by design — indexing must not block a publish, a privacy
    scrub that cannot run must abort the send rather than leak, a grounding gate that
    loses its infrastructure must HOLD rather than serve unverified prose. Fail-soft is
    the right contract and it is also, by construction, silent. So the swallowing path
    logs a literal TOKEN, a CloudWatch MetricFilter on that token mints a metric, and an
    alarm on the metric turns the silence into news.

Membership rule (so the next one lands here, not back in the stack): the alarm keys on a
``FilterPattern.literal`` of a token that is a **named constant in a lambda module**, and
a test pins the two literals together (the #2654 twin pattern). That is what separates
these from the #1951 kill-switch alarms, which stay in ``monitoring_stack.py`` — those
match a prose INFO line with ``all_terms`` and report a *deliberate pause*, not a
swallowed failure, so they have no twin constant to pin.

    between-chronicle-scrub-failed-closed    BETWEEN-CHRONICLE-SCRUB-FAILED-CLOSED  (#2654)
    expert-gate-infra-hold                   EXPERT-GATE-INFRA-HOLD                 (#2763)
    recall-index-failed-chronicle-approve    RECALL-INDEX-FAILED                    (#2977)
    recall-index-failed-wednesday-chronicle  RECALL-INDEX-FAILED                    (#2977)
    telegram-coach-hold                      TELEGRAM-COACH-HOLD                    (#2823)

#2823's ONE DELIBERATE DEVIATION — THRESHOLD, NOT SHAPE. Every alarm above is
threshold=1 over 5 minutes: those tokens mean "this should never happen." A held
coach reply is different — the same regenerate-or-hold gate that protects a real
reply also runs on three speculative unsolicited-outbound turns (referral,
morning check-in, event ping) that are *expected* to miss sometimes and are
silently discarded by design when they do (coach_outbound.DAILY_OUTBOUND_CAP
bounds those to at most 2/day, platform-wide, across all three). Alarming at
threshold=1 would page on routine discards. See the threshold derivation in
``add_silence_alarms`` below for the measured/structural reasoning (ADR-105).

WHY THE EXTRACTION. ``monitoring_stack.py`` sat at 1357 of its recorded 1358-line ratchet
baseline (#1665) — one line of headroom, and #2977 needed 33. The guard's own rule for a
FULL file is to extract a cohesive sibling, never to raise the number (the #2604/#2610
precedent), so the two existing token alarms moved here with the new pair and the
baseline was tightened to the measured result rather than banking the headroom the #2610
earned-headroom rule would have allowed.

WHY THE MOVED BLOCKS ARE VERBATIM, AND NOT FACTORED INTO ONE HELPER. The obvious cleanup
— one ``_token_alarm(prefix, token, metric, alarm_name)`` helper, four calls — was written
and then reverted, because THREE separate static analyses read these blocks by shape and
all three degrade when the literals move behind a parameter:

  * ``scripts/generate_platform_model.py`` resolves each alarm's SNS routing by tracing
    ``<var> = Alarm(alarm_name="literal")`` → ``<var>.add_alarm_action(SnsAction(digest))``
    within one module. Behind a helper the ``alarm_name`` is a parameter Name, the trace
    breaks, and #2654/#2763 regress from ``digest`` to ``unresolved`` in the committed
    model — a generated artifact quietly getting less true.
  * ``deploy/alarm_discovery.py`` resolves alarm NAMES for the doc census; a helper's
    templated name resolves only through its call sites, and only when the parameter is
    positional-or-keyword (a keyword-ONLY param lives in ``kwonlyargs`` and vanishes).
  * ``tests/cdk_alarm_pins.py`` traces MetricFilter → Alarm to pin each token against its
    lambda constant.

Four near-identical 20-line blocks is the honest cost of being legible to the tooling that
already exists. The duplication is bounded and visible; the alternative was a helper that
made four alarms less analyzable to buy back sixty lines in a 185-line file.

LOGICAL IDS ARE LOAD-BEARING. ``add_silence_alarms(scope, digest)`` is called once from
``MonitoringStack.__init__`` at the position the moved blocks occupied, with ``scope=self``
— so ``self`` became ``scope`` and nothing else did. Same scope, same construct ids: the
two ALREADY-DEPLOYED alarms (#2654, #2763) and their metric filters keep their logical ids
and are not replaced. Verified by diffing the synthesized ``LifePlatformMonitoring``
template before and after: 78 → 82 resources, the four #2977 additions and NOTHING else —
zero removed, zero changed.
"""

from aws_cdk import (
    Duration,
    aws_cloudwatch as cloudwatch,
    aws_cloudwatch_actions as cw_actions,
    aws_logs as logs,
)

GTE = cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD
NB = cloudwatch.TreatMissingData.NOT_BREACHING


def add_silence_alarms(scope, digest) -> None:
    """Attach every fail-soft silence alarm to `scope`. See the module docstring.

    NOT_BREACHING throughout: absence of the token is health, and a dead Lambda is the
    error/heartbeat alarms' job, not this one's.
    """
    # ══════════════════════════════════════════════════════════════
    # #2654: between-chronicle scrub failed CLOSED
    # The lambda logs this literal token when its privacy scrub cannot run
    # and the send is aborted. Nothing leaked when this fires — but the
    # friends&family digest went dark, and silence must not be the only
    # signal (#2503 class). Token must equal
    # between_chronicle_lambda.SCRUB_FAILED_TOKEN — pinned by
    # tests/test_between_chronicle_scrub_2654.py::test_metric_filter_token_twin.
    # ══════════════════════════════════════════════════════════════
    bc_scrub_lg = logs.LogGroup.from_log_group_name(scope, "ScrubFailLgBetweenChronicle", "/aws/lambda/between-chronicle")
    bc_scrub_mf = logs.MetricFilter(
        scope,
        "ScrubFailFilterBetweenChronicle",
        log_group=bc_scrub_lg,
        filter_pattern=logs.FilterPattern.literal('"BETWEEN-CHRONICLE-SCRUB-FAILED-CLOSED"'),
        metric_name="BetweenChronicleScrubFailedClosed",
        metric_namespace="LifePlatform/Privacy",
        metric_value="1",
    )
    bc_scrub_alarm = cloudwatch.Alarm(
        scope,
        "ScrubFailAlarmBetweenChronicle",
        alarm_name="between-chronicle-scrub-failed-closed",
        metric=bc_scrub_mf.metric(period=Duration.seconds(300), statistic="Sum"),
        evaluation_periods=1,
        threshold=1,
        comparison_operator=GTE,
        treat_missing_data=NB,
    )
    bc_scrub_alarm.add_alarm_action(cw_actions.SnsAction(digest))

    # #2763: the analyzer's gate-INFRA arm HOLDS and logs this token (nothing
    # wrong served; analyses stopped refreshing — the #2654 silence shape).
    # Token twin-pinned to the lambda literal by test_analyzer_gate_all_paths_2421.
    gi_lg = logs.LogGroup.from_log_group_name(scope, "GateInfraLgExpert", "/aws/lambda/ai-expert-analyzer")
    gi_mf = logs.MetricFilter(
        scope,
        "GateInfraFilterExpert",
        log_group=gi_lg,
        filter_pattern=logs.FilterPattern.literal('"EXPERT-GATE-INFRA-HOLD"'),
        metric_name="ExpertGateInfraHold",
        metric_namespace="LifePlatform/AI",
        metric_value="1",
    )
    gi_alarm = cloudwatch.Alarm(
        scope,
        "GateInfraAlarmExpert",
        alarm_name="expert-gate-infra-hold",
        metric=gi_mf.metric(period=Duration.seconds(300), statistic="Sum"),
        evaluation_periods=1,
        threshold=1,
        comparison_operator=GTE,
        treat_missing_data=NB,
    )
    gi_alarm.add_alarm_action(cw_actions.SnsAction(digest))

    # ══════════════════════════════════════════════════════════════
    # #2977: the publish-time recall indexer FAILED — fail-soft went silent.
    # recall_indexer logs this token on every FAILED return (embed/write,
    # metadata repair, partition read). The 2026-08-21 sweep published the
    # 2026-08-18 installment, the hook died AccessDenied, and the only
    # signal was a nightly qa-smoke FAIL buried in an already-lit alarm
    # (#2976). One filter per publish lambda so the alarm NAMES the broken
    # path. Token must equal recall_indexer.INDEX_FAILED_TOKEN — pinned by
    # tests/test_recall_publish_self_heal_2977.py (the #2654 twin pattern).
    #
    # TWO EXPLICIT SITES, NOT A LOOP — and both reasons are load-bearing:
    #   * `for _fn in ("chronicle-approve", "wednesday-chronicle")` is a literal
    #     enumeration of `lambdas` registry vocabulary, which is the #2844
    #     conformance guard's exact defect class; its ledger is shrink-only, so
    #     "add an exemption" is not a green path.
    #   * Deriving the pair at synth time (lambda_map entries whose source calls
    #     the hook) would fix that and break the census: deploy/alarm_discovery
    #     resolves names statically, and a non-literal loop counts x1 with 0
    #     names — the 113-vs-111 divergence again, from the other direction.
    # The COVERAGE claim keeps its dead-man where derivation actually works:
    # tests/test_recall_publish_self_heal_2977.py builds the caller set from
    # ci/lambda_map.json + source and reds if any publish path lacks an alarm.
    # ══════════════════════════════════════════════════════════════
    ri_approve_lg = logs.LogGroup.from_log_group_name(scope, "RecallIndexFailLgChronicleApprove", "/aws/lambda/chronicle-approve")
    ri_approve_mf = logs.MetricFilter(
        scope,
        "RecallIndexFailFilterChronicleApprove",
        log_group=ri_approve_lg,
        filter_pattern=logs.FilterPattern.literal('"RECALL-INDEX-FAILED"'),
        metric_name="RecallIndexFailedChronicleApprove",
        metric_namespace="LifePlatform/AI",
        metric_value="1",
    )
    ri_approve_alarm = cloudwatch.Alarm(
        scope,
        "RecallIndexFailAlarmChronicleApprove",
        alarm_name="recall-index-failed-chronicle-approve",
        metric=ri_approve_mf.metric(period=Duration.seconds(300), statistic="Sum"),
        evaluation_periods=1,
        threshold=1,
        comparison_operator=GTE,
        treat_missing_data=NB,
    )
    ri_approve_alarm.add_alarm_action(cw_actions.SnsAction(digest))

    ri_wed_lg = logs.LogGroup.from_log_group_name(scope, "RecallIndexFailLgWednesdayChronicle", "/aws/lambda/wednesday-chronicle")
    ri_wed_mf = logs.MetricFilter(
        scope,
        "RecallIndexFailFilterWednesdayChronicle",
        log_group=ri_wed_lg,
        filter_pattern=logs.FilterPattern.literal('"RECALL-INDEX-FAILED"'),
        metric_name="RecallIndexFailedWednesdayChronicle",
        metric_namespace="LifePlatform/AI",
        metric_value="1",
    )
    ri_wed_alarm = cloudwatch.Alarm(
        scope,
        "RecallIndexFailAlarmWednesdayChronicle",
        alarm_name="recall-index-failed-wednesday-chronicle",
        metric=ri_wed_mf.metric(period=Duration.seconds(300), statistic="Sum"),
        evaluation_periods=1,
        threshold=1,
        comparison_operator=GTE,
        treat_missing_data=NB,
    )
    ri_wed_alarm.add_alarm_action(cw_actions.SnsAction(digest))

    # ══════════════════════════════════════════════════════════════
    # #2823: a held Telegram coach reply was a log line and nothing else — the
    # 2026-08-10 P2 held every reply containing a number for ~9h and left one
    # INFO log line as its only trace. `slo-ai-coaching-success` cannot see a
    # gate hold either (it watches AnthropicAPIFailure; a hold rides a
    # SUCCESSFUL Bedrock call). `telegram_worker_lambda._emit_hold` logs this
    # token on every hold path — the primary reply AND the three
    # unsolicited-outbound paths (referral/checkin/event) — so a fourth hold
    # site added later inherits the alarm automatically rather than needing a
    # second filter. Token must equal telegram_worker_lambda.TELEGRAM_COACH_HOLD_TOKEN
    # — pinned by tests/test_telegram_coach_hold_2823.py (the #2654 twin pattern).
    #
    # THRESHOLD DERIVATION (ADR-105 — recorded here, not just in the PR, so the
    # number outlives the PR description):
    #   * Measured 2026-08-24, CloudWatch Logs Insights over
    #     /aws/lambda/telegram-coach-worker, 30-day window (2026-07-25 -
    #     2026-08-24): 38 primary-reply turns total, 1 held (the 08-10
    #     precedent itself) — an isolated single hold is normal model variance,
    #     not a regression, and zero unsolicited-outbound holds were observed
    #     in the same window (those paths are mostly dark pending BotFather
    #     registration per the coach fleet's rollout state).
    #   * Structural ceiling for the unsolicited class: coach_outbound's shared
    #     daily ledger (DAILY_OUTBOUND_CAP=2, DAILY_REFERRAL_CAP=1) permits at
    #     most 2 unsolicited-turn ATTEMPTS per day, platform-wide, across all
    #     three paths combined — so at most 2 unsolicited holds are even
    #     possible in any window, let alone one hour (the scheduled check-in
    #     and event-sweep crons are >1h apart; only a coincident referral could
    #     add a third, which the ledger's own cap forbids).
    #   * threshold=3 over a 1-hour period sits strictly above both numbers
    #     (the empirical single-hold baseline and the structural 2/day
    #     unsolicited ceiling) while still catching a systemic regression
    #     within the hour, per the acceptance bar: the 08-10 incident, sustained
    #     over ~9h of an active chat, would have crossed 3 in its first hour.
    # ══════════════════════════════════════════════════════════════
    tg_hold_lg = logs.LogGroup.from_log_group_name(scope, "CoachHoldLgTelegram", "/aws/lambda/telegram-coach-worker")
    tg_hold_mf = logs.MetricFilter(
        scope,
        "CoachHoldFilterTelegram",
        log_group=tg_hold_lg,
        filter_pattern=logs.FilterPattern.literal('"TELEGRAM-COACH-HOLD"'),
        metric_name="TelegramCoachHold",
        metric_namespace="LifePlatform/Telegram",
        metric_value="1",
    )
    tg_hold_alarm = cloudwatch.Alarm(
        scope,
        "CoachHoldAlarmTelegram",
        alarm_name="telegram-coach-hold",
        metric=tg_hold_mf.metric(period=Duration.seconds(3600), statistic="Sum"),
        evaluation_periods=1,
        threshold=3,
        comparison_operator=GTE,
        treat_missing_data=NB,
    )
    tg_hold_alarm.add_alarm_action(cw_actions.SnsAction(digest))
