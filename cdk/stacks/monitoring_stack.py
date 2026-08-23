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
    Per-Lambda threshold: 1818 (most); 30000 (daily-brief); 150000 (platform total)

  DynamoDB item-size warning (1):
    life-platform-ddb-item-size-warning  LifePlatform/DynamoDB ItemSizeBytes Max >= 307200, 300s

  S3 storage size alarm (1):  OBS-08
    life-platform-s3-bucket-size-high  BucketSizeBytes Max >= 50GB, 86400s

  #411 / ADR-116 (CloudWatch cost audit, 2026-07 — docs/reviews/CLOUDWATCH_AUDIT_2026-07.md):
    Adopted 2 previously-orphan silent-failure signals into IaC:
      compute-pipeline-stale            LifePlatform ComputePipelineStaleness Max >= 1, 86400s (digest)
      hae-webhook-no-invocations-24h    AWS/Lambda Invocations < 1, 86400s, BREACHING (digest)
    18 redundant/dead orphan alarms retired via deploy/cloudwatch_retire_orphans.sh.

  #1445 (qa-smoke observability, 2026-07-18): qa_smoke_lambda.py now emits an
  EMF LifePlatform/QaSmoke summary on EVERY run, including all-green:
      qa-smoke-heartbeat   RunCompleted SampleCount < 1, 2 consecutive days, BREACHING (digest)
      qa-smoke-failures    FailCount Max >= 1, 86400s (digest)
      qa-smoke-warnings    WarnCount Max >= 1, 86400s (digest) — a warnings-only
                            run is now visible in the daily digest, not fully silent.

  #1455 (heartbeat completeness, 2026-07-19): the compute-output check's gauge is
  now alarmed (it had emitted unalarmed since Phase 3.2):
      compute-outputs-missing    LifePlatform/Pipeline ComputeOutputsMissing Max >= 1, 86400s (digest)
      compute-outputs-heartbeat  same gauge ABSENT 2 consecutive days, BREACHING (digest)
  tests/test_heartbeat_completeness.py asserts every scheduled Lambda has a
  liveness signal or a dated exemption.

  #1440 (ADR-104 applied to QA itself): budget-tier pause visibility for the
  reader-truth AI QA pass (both the CI/local harness and the nightly qa_smoke
  hook — lambdas/reader_truth_qa.emit_budget_pause_metric()):
    qa-paused-by-budget    LifePlatform/QA QAPausedByBudget Sum >= 1, 86400s (digest)

  #1951 (growth-1: /subscribe/ promised "every Wednesday" while every
  subscriber-facing weekly send was kill-switched, undetected for ~3
  months): one metric filter + alarm per subscriber-facing sender on the
  "[kill-switch] ... skipping ... subscriber send" INFO log line, so a
  paused send is a visible state, not a silent green (3):
    life-platform-chronicle-email-sender-kill-switch-skip  LifePlatform/Email
      SubscriberSendSkippedByKillSwitch Sum >= 1, 86400s (digest)
    life-platform-weekly-signal-kill-switch-skip            (same metric, digest)
    life-platform-between-chronicle-kill-switch-skip        (same metric, digest)
"""

from aws_cdk import (
    Duration,
    Stack,
    aws_cloudwatch as cloudwatch,
    aws_cloudwatch_actions as cw_actions,
    aws_logs as logs,
    aws_sns as sns,
)

from stacks.constants import ACCT, REGION, S3_BUCKET, TABLE_NAME  # CONF-01
from stacks.monitoring_dashboards import add_dashboards  # #2610: the dashboards live in a sibling

ALERTS_TOPIC_ARN = f"arn:aws:sns:{REGION}:{ACCT}:life-platform-alerts"
DIGEST_TOPIC_ARN = f"arn:aws:sns:{REGION}:{ACCT}:life-platform-alerts-digest"
PAGING_TOPIC_ARN = f"arn:aws:sns:{REGION}:{ACCT}:life-platform-paging"  # ADR-143 (#1333)

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
            evaluation_periods=1,
            treat_missing=None,  # #2754: pass BREACHING for zero-emission metrics (Invocations of a dead cron)
        ):
            # #1927: `evaluation_periods` defaults to 1, so every existing caller is
            # unchanged. It exists for alarms whose whole point is DURATION — a
            # condition that is normal for one period and pathological if it never
            # lets up. CloudWatch caps evaluation_periods x period at 604800s (7d).
            #
            # datapoints_to_alarm is set ONLY for a multi-period alarm. Passing it
            # unconditionally is semantically identical at 1-of-1 (CloudFormation
            # already defaults it to EvaluationPeriods) but it emits the property on
            # every alarm in the stack — the cdk diff showed `[+] DatapointsToAlarm 1`
            # against ~30 untouched resources. A no-op change to that many deployed
            # alarms is noise in every future diff and buries the one that matters.
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
                evaluation_periods=evaluation_periods,
                # all N datapoints must breach — see the sustained-tier alarm below
                datapoints_to_alarm=evaluation_periods if evaluation_periods > 1 else None,
                threshold=threshold,
                comparison_operator=operator,
                treat_missing_data=treat_missing or NB,
            )
            a.add_alarm_action(cw_actions.SnsAction(digest if to_digest else topic))
            return a

        # REL-01 (AUDIT 2026-06-30): a silent-failure DETECTOR that stops being
        # invoked emits no metric, so its "≥1 problem" alarm (treat_missing=NB) sits OK
        # forever — the watchdog itself goes dark (the 44-day-Garmin class, one level up).
        # Give each daily detector a HEARTBEAT: BREACHING when its own gauge is ABSENT
        # for `days` consecutive days. The absence-is-failure pattern —
        # SampleCount<1 over N full days = "the producer did not run". Requiring N
        # consecutive days avoids a false fire from the in-progress UTC period (the
        # reason the problem alarms can't simply flip to BREACHING at evaluation=1).
        def _heartbeat_alarm(alarm_id, alarm_name, namespace, metric_name, dims=None, days=2):
            metric = cloudwatch.Metric(
                namespace=namespace,
                metric_name=metric_name,
                dimensions_map=dims or {},
                period=Duration.seconds(86400),
                statistic="SampleCount",
            )
            a = cloudwatch.Alarm(
                self,
                alarm_id,
                alarm_name=alarm_name,
                metric=metric,
                evaluation_periods=days,
                datapoints_to_alarm=days,
                threshold=1,
                comparison_operator=LT,
                treat_missing_data=cloudwatch.TreatMissingData.BREACHING,
            )
            a.add_alarm_action(cw_actions.SnsAction(digest))
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

        # DI-2: source-of-truth reconciliation. Unlike liveness/freshness (which
        # read only DDB and so see only the high-water mark), the strava reconcile
        # job diffs the trailing-14d Strava API activity set against the store and
        # emits the count of activities the API has but we never stored. Catches a
        # *silent drop* (the Jun 2026 evening-walk class) that every DDB-only check
        # is blind to. Fires the day after a gap appears.
        _alarm(
            "IngestReconciliationStrava",
            "ingest-reconciliation-strava",
            "LifePlatform/IngestReconciliation",
            "MissingActivityCount",
            86400,
            "Maximum",
            1,
            GTE,
            dims={"Source": "strava"},
            to_digest=True,
        )

        # DI-2 / TR-07 (#415): the Strava reconciler generalized to Whoop. Same
        # metric, distinguished by the Source dimension — the whoop reconcile job
        # (daily, {"reconcile": true}) diffs the trailing-14d Whoop sleep+workout
        # set against the store and emits the count the API has but we never stored.
        # Catches the silent-drop class (a late-syncing workout / dropped night)
        # that every DDB-only Whoop check is blind to.
        _alarm(
            "IngestReconciliationWhoop",
            "ingest-reconciliation-whoop",
            "LifePlatform/IngestReconciliation",
            "MissingActivityCount",
            86400,
            "Maximum",
            1,
            GTE,
            dims={"Source": "whoop"},
            to_digest=True,
        )

        # DI-2b: interior-gap detection. Freshness/liveness see only the latest
        # date per source; this catches a DAILY source going dead mid-window then
        # resuming (a hole behind the high-water mark). Emitted by freshness_checker
        # from a per-source DATE# scan over the trailing window. Digest, not urgent.
        _alarm(
            "FreshnessInteriorGap",
            "freshness-interior-gap",
            "LifePlatform/Freshness",
            "InteriorGapCount",
            86400,
            "Maximum",
            1,
            GTE,
            to_digest=True,
        )

        # Coherence Sentinel: the intelligence layer produced INCOHERENT-but-green
        # output. Fires when any invariant ALARMed (predictions never grading, a
        # served narrative contradicting the canonical facts, an all-zero endpoint,
        # cross-surface counts disagreeing) or the AI semantic pass flagged it.
        # The class of failure every existing liveness check is blind to. Digest.
        _alarm(
            "CoherenceOverall",
            "coherence-overall",
            "LifePlatform/Coherence",
            "OverallAlarm",
            86400,
            "Maximum",
            1,
            GTE,
            to_digest=True,
        )

        # AI Quality Canary (#385): a DETERMINISTIC quality check over the public
        # AI endpoints ALARMed — an empty/stub answer, a fourth-wall vendor leak,
        # a fabricated (ungrounded) number, a blocked term served, or the
        # invalid-persona 400 regressed to a 500. The only alarm that watches the
        # AI a reader actually touches. The advisory Haiku judge never trips it.
        # Digest, not urgent.
        _alarm(
            "AiCanaryOverall",
            "ai-canary-overall",
            "LifePlatform/AICanary",
            "OverallAlarm",
            86400,
            "Maximum",
            1,
            GTE,
            to_digest=True,
        )

        # #1589: the canary's transport self-test. Fires when a run was BLIND —
        # every probe rejected at the invoke/auth layer (403s, invoke failures),
        # so NO AI-quality verdict exists. Distinguishes "the watcher is broken"
        # from "the answers are bad" at the alarm level; ai-canary-overall alone
        # cannot (it fires for both). Digest.
        _alarm(
            "AiCanaryBlind",
            "ai-canary-blind",
            "LifePlatform/AICanary",
            "Blind",
            86400,
            "Maximum",
            1,
            GTE,
            to_digest=True,
        )

        # #1440: a budget-tier pause of the reader-truth AI QA pass (either hook —
        # tests/visual_ai_qa.assess_reader_truth on CI/local, or the nightly
        # qa_smoke_lambda.check_reader_truth — both call
        # reader_truth_qa.emit_budget_pause_metric(), dimension-less) must be
        # visible even on a day nothing else fails. qa_smoke's own email only
        # fires on a real FAILURE (a lone ⏸ pause sends nothing), so this alarm is
        # the only guaranteed surface for a pause-only day — it lands in the SAME
        # daily digest every other alarm here uses. ADR-104 applied to QA itself:
        # a paused check must never be indistinguishable from a passing one.
        _alarm(
            "QaPausedByBudget",
            "qa-paused-by-budget",
            "LifePlatform/QA",
            "QAPausedByBudget",
            86400,
            "Sum",
            1,
            GTE,
            to_digest=True,
        )

        # REL-01: heartbeats for the four silent-failure detectors above. Each fires if
        # the detector's own daily metric is ABSENT for 2 straight days — i.e. the
        # producer (pipeline-health / strava-reconcile / freshness-checker / coherence-
        # sentinel) stopped running. The "≥1 problem" alarms above are NB and blind to
        # this; these close the "who watches the watchdog" gap. Digest, not urgent.
        _heartbeat_alarm(
            "IngestLivenessHeartbeat",
            "ingest-liveness-heartbeat",
            "LifePlatform/IngestLiveness",
            "UnhealthySourceCount",
        )
        _heartbeat_alarm(
            "IngestReconciliationStravaHeartbeat",
            "ingest-reconciliation-strava-heartbeat",
            "LifePlatform/IngestReconciliation",
            "MissingActivityCount",
            dims={"Source": "strava"},
        )
        # TR-07 (#415): the whoop reconciler is a daily detector too — pair its
        # ≥1-problem alarm with an absence heartbeat (producer went dark).
        _heartbeat_alarm(
            "IngestReconciliationWhoopHeartbeat",
            "ingest-reconciliation-whoop-heartbeat",
            "LifePlatform/IngestReconciliation",
            "MissingActivityCount",
            dims={"Source": "whoop"},
        )
        _heartbeat_alarm(
            "FreshnessInteriorGapHeartbeat",
            "freshness-interior-gap-heartbeat",
            "LifePlatform/Freshness",
            "InteriorGapCount",
        )
        _heartbeat_alarm(
            "CoherenceHeartbeat",
            "coherence-heartbeat",
            "LifePlatform/Coherence",
            "OverallAlarm",
        )
        # The canary runs 3×/week (Mon/Wed/Fri 16:20 UTC — #1443; was weekly, which
        # left the public AI blind up to 7 days). The max healthy gap is Fri→Mon
        # (3 calendar days: Sat + Sun empty, Mon's run lands after 16:20), so a
        # trailing-4-day window always contains at least one scheduled run: days=4
        # fires the first time a run is missed and never on a healthy cadence.
        # (Historical: at weekly cadence this was days=7 — the CloudWatch max,
        # since EvaluationPeriods × Period ≤ 604800; days=9 was rejected at CREATE.)
        _heartbeat_alarm(
            "AiCanaryHeartbeat",
            "ai-canary-heartbeat",
            "LifePlatform/AICanary",
            "OverallAlarm",
            days=4,
        )
        # REL-01 extension (#372): cost-governor heartbeat. The governor is the sole
        # writer of the budget tier that gates every AI feature; if it starts erroring
        # the platform silently reads a frozen tier while spend continues. It runs 3×/day
        # (every 8h) and emits LifePlatform/Budget::BudgetTier on each run. Missing for
        # 2 straight days → ALARM (same pattern as the four watchdog heartbeats above).
        _heartbeat_alarm(
            "CostGovernorHeartbeat",
            "cost-governor-heartbeat",
            "LifePlatform/Budget",
            "BudgetTier",
        )

        # #1445: qa-smoke was previously silent unless a check FAILED — a green run and a dead
        # Lambda both produced zero signal, so "the nightly data-health layer stopped running"
        # was indistinguishable from "the site is healthy." qa_smoke_lambda.py now emits a
        # LifePlatform/QaSmoke EMF summary (PassCount/WarnCount/FailCount/PausedCount/
        # RunCompleted) on EVERY run, including all-green. Three alarms close the loop, all
        # digest — matching the dispatcher's own "the daily sweep already handles routine ...
        # QA smoke" posture (remediation_dispatcher_lambda.py), so a routine QA finding stays
        # off the urgent page while still being real, queryable signal:
        #   qa-smoke-heartbeat — RunCompleted absent 2 straight days (the Lambda stopped
        #     running / died before its EMF line, mirrors the REL-01 heartbeats).
        #   qa-smoke-failures  — FailCount >= 1 (was already emailed directly; this also makes
        #     it a queryable alarm the remediation agent's describe_alarms(StateValue="ALARM")
        #     sweep ingests as a source, same mechanism every other alarm class already uses).
        #   qa-smoke-warnings  — WarnCount >= 1: a warnings-only run was previously fully
        #     silent (no email, no alarm); now it surfaces in the next daily digest — visible,
        #     not a full alert. #1958: WarnCount is the ALARMED warn count only — the known-
        #     recurring timing warns (optional-source no-record days, cache-warm partial) emit
        #     as ChronicWarnCount, DELIBERATELY unalarmed (their honest daily floor was 4-11,
        #     which held this alarm red 15+ consecutive nights against the >= 1 threshold;
        #     ADR-105). #2378: chronic set AST-guarded in test_qa_smoke_chronic_warns. No
        #     ChronicWarnCount alarm; keep the 86400s Maximum window — load-bearing. #2670:
        #     receipt-replay's drift branch is chronic too (threshold UNCHANGED).
        #
        # #2912 — ALARM STATE IS NOT A RELIABLE AUDIT SURFACE for these (or any Period=86400/
        # EvaluationPeriods=1 alarm on a sparse custom metric); OK does NOT mean "no failure fired today":
        # (a) it evaluates a SLIDING 24h window about once a minute (history startDate == queryDate -
        # 86400s, never midnight-aligned), so a breaching datapoint ages out ~24h after emission (the
        # observed organic 24h+3min clearances); (b) measured live 2026-08-20 15:34->18:03Z: for ~2.5h
        # after a fresh datapoint, one-minute evaluations of near-identical windows returned MUTUALLY
        # EXCLUSIVE sample sets ([max 1.0, n=1] fresh point only, alternating [max 0.0, n=2] older zeros
        # only), flapping OK<->ALARM 35 times with 1-3 min dwells; TreatMissingData never engaged
        # (sampleCount >= 1 throughout). SNS fires per transition so notifications survive; the STATE
        # does not carry the signal. The honest audit surface is transition history:
        # scripts/check_alarm_citations.py (the /wrap e10 gate) reads describe-alarm-history and forces every fired-and-cleared episode in 72h to be answered.
        _heartbeat_alarm(
            "QaSmokeHeartbeat",
            "qa-smoke-heartbeat",
            "LifePlatform/QaSmoke",
            "RunCompleted",
        )
        _alarm(
            "QaSmokeFailures",
            "qa-smoke-failures",
            "LifePlatform/QaSmoke",
            "FailCount",
            86400,
            "Maximum",
            1,
            GTE,
            to_digest=True,
        )
        _alarm(
            "QaSmokeWarnings",
            "qa-smoke-warnings",
            "LifePlatform/QaSmoke",
            "WarnCount",
            86400,
            "Maximum",
            1,
            GTE,
            to_digest=True,
        )

        # #1927: a budget PAUSE is routine; a budget pause that never lifts is a
        # different fact, and the existing machinery could not tell them apart.
        #
        # #1440's QAPausedByBudget alarm is per-day and correct — but between
        # 2026-07-06 and 2026-08-01 the tier sat at >= 1 for 26 CONSECUTIVE days, so
        # it fired 26 times, read as background, and nothing moved. In that window
        # the whole budget_guard cutoff-1 band was off: ensemble, chronicle_editor,
        # coherence_semantic, reader_truth_qa, visual_ai_qa, eyeball_estimate,
        # conversation_enrichment — including two CI gates, both of which report
        # green when paused. A daily alarm on a permanent condition is not a signal.
        #
        # This one can only fire when the tier NEVER returned to 0 across a full
        # week. Statistic=Minimum per 8h period + datapoints_to_alarm == all 21
        # periods means a single tier-0 datapoint anywhere in the window clears it,
        # so it stays silent through ordinary end-of-month pressure and speaks only
        # when band 1 has become the default operating state rather than an
        # exception. Rarity IS the escalation: it says something the daily alarm
        # structurally cannot.
        #
        # 28800 x 21 = 604800s, exactly CloudWatch's evaluation-window ceiling — do
        # not lengthen the period or the count without shortening the other.
        # cost_governor emits BudgetTier every 8h (measured: 91 datapoints/30d, no
        # gaps), so all 21 periods are genuinely populated.
        _alarm(
            "BudgetTierSustained",
            "budget-tier-sustained-7d",
            "LifePlatform/Budget",
            "BudgetTier",
            28800,
            "Minimum",
            1,
            GTE,
            to_digest=True,
            evaluation_periods=21,
        )

        # #727: scientific-liveness heartbeat. The coach-prediction-evaluator ran
        # daily for WEEKS and graded nothing, and no alarm noticed — every heartbeat
        # above watches the ingestion/coherence PIPELINE, none watched the SCIENCE.
        # The evaluator now emits LifePlatform/Predictions::DaysSinceLastDecided every
        # run: whole days since grading last produced a confirmed/refuted outcome
        # (999 = never, this cycle). ALARM when it sits >= 14 for 2 consecutive daily
        # periods. ONE alarm covers BOTH failure modes: a genuine 14-day grading
        # stall, AND a dead evaluator (treat_missing=BREACHING — an absent gauge is
        # itself a stall). 2 periods, not 1, mirrors the REL-01 heartbeats' guard
        # against a false fire from the in-progress UTC period (the reason those use
        # days=2). Fires on the CURRENT state the day it deploys — grading has been
        # dark for weeks, which is exactly the point (E1.3 / #727 AC). Digest.
        grading_stalled = cloudwatch.Alarm(
            self,
            "GradingStalled",
            alarm_name="grading-stalled",
            metric=cloudwatch.Metric(
                namespace="LifePlatform/Predictions",
                metric_name="DaysSinceLastDecided",
                period=Duration.seconds(86400),
                statistic="Maximum",
            ),
            evaluation_periods=2,
            datapoints_to_alarm=2,
            threshold=14,
            comparison_operator=GTE,
            treat_missing_data=cloudwatch.TreatMissingData.BREACHING,
        )
        grading_stalled.add_alarm_action(cw_actions.SnsAction(digest))

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

        # #2754: zero invocations emit NO datapoint — NB could never fire. BREACHING; SET guard: test_no_invocation_alarms_2754.
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
            treat_missing=cloudwatch.TreatMissingData.BREACHING,
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
        # NB: garmin is intentionally EXCLUDED — its auth death is a known, accepted,
        # Garmin-side condition (datacenter-IP 429 block; server-side refresh can't
        # recover) already covered by the digest-routed `garmin-auth-unhealthy-24h`
        # below. Paging URGENT on it too was pure duplicate noise for an unfixable state.
        for _src in ("whoop", "withings", "strava", "eightsleep", "hevy"):
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

        # ── Garmin alarms intentionally REMOVED (2026-06-19) ────────────────────
        # Garmin ingestion is brittle by a KNOWN, accepted Garmin-side cause: their
        # 2026 datacenter-IP 429 block defeats the server-side OAuth2 refresh, and a
        # browser re-auth holds only ~48h. Sleep/HRV/recovery are all covered by Whoop
        # + Eight Sleep, so Garmin is a best-effort second source we deliberately do
        # NOT alarm on — the auth + token alarms were permanent-red digest noise for an
        # unfixable, expected state. Garmin is also excluded from the fleet
        # UnhealthySourceCount (pipeline_health_check_lambda BEST_EFFORT_SOURCES) so it
        # can't keep `ingest-liveness-unhealthy` red or mask a real source death.
        # Re-add real alarms here if/when the Garmin API path becomes stable again.
        # (Was: garmin-auth-unhealthy-24h + garmin-token-expiring-7d.)

        # ── Fleet-wide ingestion auth-liveness (elite review 2026-06-15) ────────
        # Generalises the Garmin auth-health signal to every breaker-using source.
        # auth_breaker.py emits LifePlatform/OAuth IngestAuthHealthy = 1 on each
        # successful run and 0 on every mark + 24h short-circuit. Emitters: notion +
        # dropbox call auth_breaker directly; the SIMP-2 framework sources emit via
        # ingestion_framework's breaker hooks, which DELEGATE to auth_breaker since
        # #467 (X-13 — before that the framework had a metric-less private copy and
        # this comment overstated coverage). A tripped breaker returns a healthy 200
        # "skip", so without this a dead credential silently suppresses a source
        # for 24h — exactly how Garmin/Strava stayed dead for weeks. Reads the
        # DIMENSIONLESS stream (still emitted verbatim after #1960 added the
        # Source-dimensioned twin) + Minimum: if ANY breaker source emits a 0 in the
        # window, Min=0 → fire. The per-source alarms below name the culprit.
        # Absence (no breaker source ran at all) is NOT a failure — the freshness
        # checker covers prolonged data gaps; here we only care about a source
        # that ran and got auth-suppressed.
        _ingest_auth_dead = cloudwatch.Alarm(
            self,
            "IngestAuthUnhealthy",
            alarm_name="ingest-auth-unhealthy-24h",
            # #2976 re-cut 86400s → 3600s, superseding #2004's "do not shorten": every
            # authenticated-successful run now emits 1 (≥1 point/30 min, and a tripped
            # breaker keeps landing 0s) — fires as fast as before, clears ~1h after
            # real recovery instead of a 24h latch (2026-08-21→22). See RUNBOOK.md.
            alarm_description="some source emitted IngestAuthHealthy=0 in the last hour; clears ~1h after recovery (#2976) — confirm via AUTH_FAILURE markers.",
            metric=cloudwatch.Metric(
                namespace="LifePlatform/OAuth",
                metric_name="IngestAuthHealthy",
                period=Duration.seconds(3600),
                statistic="Minimum",
            ),
            evaluation_periods=1,
            threshold=1,
            comparison_operator=LT,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )
        _ingest_auth_dead.add_alarm_action(cw_actions.SnsAction(topic))

        # ── Per-source auth-liveness (#1960) ───────────────────────────────────
        # The aggregate above could not NAME the dead source, because the metric was
        # emitted without dimensions "on purpose". That gap had a second cost: the
        # remediation agent acked ingest-auth-unhealthy-24h as "duplicate, covered by
        # source-specific alarms" — false for every OAuth source outside the 5-source
        # consecutive-failures loop above, so a garmin/notion/todoist auth death fired
        # ONLY the alarm the ack dismissed. auth_breaker now emits the same 0/1 TWICE:
        # dimensionless (the aggregate above, unchanged) AND Source=<name>. These read
        # the dimensioned stream, so the page names the culprit.
        #
        # Same shape as the aggregate (Minimum over 24h, NOT_BREACHING): a source that
        # never ran emits nothing and must not fire; a source that ran and got
        # auth-suppressed emits a 0 and does.
        #
        # The tuples are LITERALS on purpose — deploy/sync_doc_metadata.py AST-resolves
        # alarm names out of this file for docs/MONITORING.md and can only resolve a
        # loop var bound to a constant, so an import here would erase these names from
        # the inventory. lambdas/ingestion/source_registry.py stays the authority:
        # tests/test_oauth_alarm_coverage.py derives oauth_source_ids() /
        # oauth_digest_only_source_ids() from the registry and FAILS if any credentialed
        # source is missing coverage or is routed to the wrong topic. (Loop var is
        # `_auth_src`, not `_src` — test_source_enumeration_drift.py regex-matches the
        # first `for _src in (...)` and must keep finding the consec-failures tuple.)
        #
        # `whoop` added #1934: it was already "covered" per test_oauth_alarm_coverage's
        # weaker bar (an `ingest-consecutive-failures-whoop` alarm exists — ER-01,
        # 2026-06-12) but that family needs 3 consecutive failing runs (~2-3h) AND
        # conflates auth failures with transport/parse/throttle ones, so a latched
        # breaker reads only as generic "failing", never as "auth". habitify — the
        # platform's OTHER qa_required OAuth source — already gets the dedicated,
        # single-datapoint, auth-specific signal below; whoop (the only fully-passive
        # daily source, feeding recovery/HRV/RHR/sleep) did not, purely because it
        # predates #1960. Verified against the actual 2026-08-01 outage: the
        # consecutive-failures alarm DID fire (dispatched 08-01T14:01Z, ~2h after the
        # breaker latched at 12:00:28Z) — so this is a fix-in-place, not a new report.
        # #2976: window = emitter cadence — dropbox (≤30-min emissions) re-cut to 3600s;
        # daily-cron sources KEEP 86400s (NB missing-data would clear them overnight).
        for _auth_src in ("todoist", "habitify", "dropbox", "whoop"):
            _alarm(
                f"IngestAuthUnhealthy{_auth_src.title()}",
                f"ingest-auth-unhealthy-{_auth_src}",
                "LifePlatform/OAuth",
                "IngestAuthHealthy",
                3600 if _auth_src == "dropbox" else 86400,
                "Minimum",
                1,
                LT,
                dims={"Source": _auth_src},
            )
        # DIGEST, not urgent — registry-derived (oauth_digest_only_source_ids):
        # garmin is paused + best_effort (its 429 auth death is the accepted,
        # unfixable state ADR-074 de-paged; coverage returns, the page does not) and
        # notion is monitored:False (operator view only, never a paging surface).
        for _auth_src in ("garmin", "notion"):
            _alarm(
                f"IngestAuthUnhealthy{_auth_src.title()}",
                f"ingest-auth-unhealthy-{_auth_src}",
                "LifePlatform/OAuth",
                "IngestAuthHealthy",
                86400,
                "Minimum",
                1,
                LT,
                dims={"Source": _auth_src},
                to_digest=True,
            )

        # ══════════════════════════════════════════════════════════════
        # RETIRED 2026-07-08 (#734): panelcast-no-episode-7d.
        # The Panel is now EVENT-DRIVEN (ships only when a chronicle publishes),
        # so a quiet week is a LEGITIMATE silence, not a failure — the old
        # treat_missing_data=BREACHING absence alarm would fire red exactly when
        # Matthew disengages and no week earns an episode, which is precisely the
        # false page #734 removes. The PanelcastPublished heartbeat metric is still
        # emitted on publish (for dashboards); it is simply no longer alarmed on
        # absence. The distribution-liveness signal moves to the DAILY debrief's
        # no-INVOCATIONS alarm below (a broken cron is a real failure; a budget-skip
        # day still invokes + publishes a template episode, so it never false-fires).

        # Daily-debrief liveness (#734) — the debrief runs every day at 19:00 UTC.
        # This watches INVOCATIONS (not published-episode absence): it fires only if
        # the schedule itself stops firing the Lambda for 24h — a genuine outage —
        # and a budget-skip / template-fallback day is still an invocation, so a
        # quiet-but-healthy day is never red. Mirrors daily-brief-no-invocations-24h.
        _alarm(
            "DailyDebriefNoInvocations",
            "daily-debrief-no-invocations-24h",
            "AWS/Lambda",
            "Invocations",
            86400,
            "Sum",
            1,
            LT,
            {"FunctionName": "daily-debrief"},
            to_digest=True,
            treat_missing=cloudwatch.TreatMissingData.BREACHING,  # #2754 — see daily-brief above
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
        # 2026-06-24: bumped threshold 33333 → 150000. The platform's autonomous
        # AI baseline crept to ~59k output tokens/day (Jun 22/23/24 all ~58-59k:
        # daily brief + 8 coach narratives + the panelcast revision loop + compute),
        # so 33333 sat far *below* normal operation and fired into the alarm digest
        # every single day — pure noise, not a cost signal (the $75 budget guard +
        # the ai-daily-spend-high $ alarm are the real cost protection, both intact).
        # Legitimate content-heavy days (weekly podcast/chronicle generation) peak
        # ~121k. 150000 clears those peaks and alerts only on a genuine ~2.5x runaway.
        # Future: swap to a CloudWatch anomaly-detection band (per ai-daily-spend-high).
        #
        # #1961 -> #2116 (this block closes #1961's residual gap, flagged in
        # PR #2114): a genesis's predictable post-reset full-cycle rebuild spike
        # (character sheet + compute + coach dossiers + chronicle backfill all
        # regenerating at once) can clear 150000 and page exactly like an
        # unexplained runaway (cycle 11 did, twice). #2114 fixed the AUTOMATED
        # remediation-triage escalation (Lambda-side,
        # `lambdas/common/token_alarm_window.py`, consulted by
        # remediation_dispatcher_lambda.py) but left the raw CloudWatch alarm's
        # own SNS action — routed straight to the urgent topic, which ALSO
        # carries a direct human EmailSubscription (operational_stack.py) — with
        # no window awareness at all: a predicted spike still emailed the
        # operator directly.
        #
        # Mechanism (the composite-alarm design #2114 flagged as the follow-up):
        # `lambdas/operational/cost_governor_lambda.py` (already on its existing
        # 8h cron — no new schedule, #781) now publishes a
        # LifePlatform/AI::TokenAlarmGenesisWindowActive 1/0 gauge from the SAME
        # stamped window the dispatcher consults. The raw threshold alarm below
        # carries NO SNS action of its own anymore — it exists only as a signal
        # two composite alarms combine with the window gauge:
        #   ai-tokens-platform-daily-total-urgent          breach AND NOT in-window -> urgent topic
        #   ai-tokens-platform-daily-total-genesis-window  breach AND     in-window -> digest topic
        # so a genesis-week breach is still recorded (digest), never paged, and
        # an out-of-window breach still pages exactly as before #2116. This is a
        # CDK-only change — NEEDS `cdk deploy LifePlatformMonitoring` to take
        # effect; until that deploy, the raw alarm's behavior (and the direct
        # human email) is UNCHANGED from #1961's pre-fix state.
        ai_tokens_platform_metric = cloudwatch.Metric(
            namespace="LifePlatform/AI",
            metric_name="AnthropicOutputTokens",
            period=Duration.seconds(86400),
            statistic="Sum",
        )
        ai_tokens_platform_alarm = cloudwatch.Alarm(
            self,
            "AiTokensPlatformTotal",
            alarm_name="ai-tokens-platform-daily-total",
            metric=ai_tokens_platform_metric,
            evaluation_periods=1,
            threshold=150000,
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
            self,
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
            self,
            "AiTokensPlatformUrgent",
            composite_alarm_name="ai-tokens-platform-daily-total-urgent",
            alarm_rule=cloudwatch.AlarmRule.all_of(_token_platform_breach, cloudwatch.AlarmRule.not_(_in_genesis_window)),
        )
        ai_tokens_platform_urgent.add_alarm_action(cw_actions.SnsAction(topic))

        ai_tokens_platform_in_window = cloudwatch.CompositeAlarm(
            self,
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
        _alarm(
            "AiDailySpendHigh",
            "ai-daily-spend-high",
            "LifePlatform/AI",
            "EstimatedCostUSD",
            86400,
            "Sum",
            6.0,
            GTE,
        )

        # ══════════════════════════════════════════════════════════════
        # SS-03: budget-tier HARD-STOP alarm — the kill-switch can't be silent.
        # cost_governor writes a tier 0-3 to SSM AND emits LifePlatform/Budget
        # BudgetTier (the computed tier, even in observe mode). Tier >= 2 (website AI
        # paused) is already surfaced to the DIGEST by `life-platform-budget-tier-
        # escalation` below. But that digest alarm conflates tier 2 with tier 3, and
        # tier 3 is categorically worse: ALL Bedrock paused, so the *daily brief
        # itself* goes data-only — the flagship output silently degrades. A digest
        # line is too quiet for that. This alarm escalates tier 3 specifically to the
        # URGENT topic so a hard-stop pages promptly instead of waiting for someone to
        # read the overnight digest (the 6-month hands-off failure mode is "AI dies,
        # nobody notices for weeks"). Hourly Maximum matches the escalation alarm's
        # cadence; NOT_BREACHING (the _alarm default) so a missed emit never false-fires.
        _alarm(
            "BudgetTierHardStop",
            "budget-tier-hardstop",
            "LifePlatform/Budget",
            "BudgetTier",
            3600,
            "Maximum",
            3,
            GTE,
        )

        # 2026-05-29: the ~46 per-Lambda ingestion-error-* alarms ($4.60/mo) were removed
        # (error_alarm=False in ingestion_stack). No aggregate replaces them: CloudWatch
        # rejects SEARCH in alarms and caps metric-math alarms at ~10 metrics (19 ingestion
        # fns). Sustained failure is caught downstream by the freshness-checker (stale → SNS),
        # the DLQ + dlq-consumer (async), the canary, and the remediation agent (per-Lambda
        # log diagnosis); the removed alarms mostly fired on transient self-healing errors.
        # #2822 carves out the ONE near-real-time exception: hae-webhook-errors (ingestion_stack,
        # digest) — an inbound push with no backfill cron sits blind 2-3 days on this posture.

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
            {"TableName": TABLE_NAME, "Operation": "PutItem"},
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
        # #2654: between-chronicle scrub failed CLOSED
        # The lambda logs this literal token when its privacy scrub cannot run
        # and the send is aborted. Nothing leaked when this fires — but the
        # friends&family digest went dark, and silence must not be the only
        # signal (#2503 class). Token must equal
        # between_chronicle_lambda.SCRUB_FAILED_TOKEN — pinned by
        # tests/test_between_chronicle_scrub_2654.py::test_metric_filter_token_twin.
        # ══════════════════════════════════════════════════════════════
        bc_scrub_lg = logs.LogGroup.from_log_group_name(self, "ScrubFailLgBetweenChronicle", "/aws/lambda/between-chronicle")
        bc_scrub_mf = logs.MetricFilter(
            self,
            "ScrubFailFilterBetweenChronicle",
            log_group=bc_scrub_lg,
            filter_pattern=logs.FilterPattern.literal('"BETWEEN-CHRONICLE-SCRUB-FAILED-CLOSED"'),
            metric_name="BetweenChronicleScrubFailedClosed",
            metric_namespace="LifePlatform/Privacy",
            metric_value="1",
        )
        bc_scrub_alarm = cloudwatch.Alarm(
            self,
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
        gi_lg = logs.LogGroup.from_log_group_name(self, "GateInfraLgExpert", "/aws/lambda/ai-expert-analyzer")
        gi_mf = logs.MetricFilter(
            self,
            "GateInfraFilterExpert",
            log_group=gi_lg,
            filter_pattern=logs.FilterPattern.literal('"EXPERT-GATE-INFRA-HOLD"'),
            metric_name="ExpertGateInfraHold",
            metric_namespace="LifePlatform/AI",
            metric_value="1",
        )
        gi_alarm = cloudwatch.Alarm(
            self,
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

        # ══════════════════════════════════════════════════════════════
        # #1229: watch the watchdog's own delivery path.
        # life-platform-alert-digest is the single consumer that drains the
        # alerts-digest queue and emails the daily batch — 52 of 67 alarms route
        # THROUGH it. It was itself unwatched: if it errors, alarm notifications
        # pile up in the queue silently (25h retention → >1 day of failure loses
        # notifications permanently). Both alarms route URGENT (the default `topic`,
        # NOT the digest) — the digest path cannot announce its own death.
        # ADR-095's "error alarm omitted by design" is specific to the traffic
        # digest (CF logs retained 90d, next run recovers) and does NOT transfer to
        # a 25h-retention queue. ADR-103: load-bearing notification path (~$0.20/mo).
        # ══════════════════════════════════════════════════════════════
        _alarm(
            "AlertDigestErrors",
            "life-platform-alert-digest-errors",
            "AWS/Lambda",
            "Errors",
            86400,
            "Sum",
            1,
            GTE,
            {"FunctionName": "life-platform-alert-digest"},
        )

        # ApproximateAgeOfOldestMessage is in SECONDS. The queue drains once daily
        # (Invocations=1/day), so a healthy oldest-message age tops out near ~24h
        # (86400s) between drains. 48h (172800s) means the daily drainer missed at
        # least a full cycle — notifications are now stranded. Period 3600s with
        # evaluation_periods=1 (in _alarm) stays well under the 604800s week cap.
        _alarm(
            "AlertDigestQueueAge",
            "life-platform-alert-digest-queue-age",
            "AWS/SQS",
            "ApproximateAgeOfOldestMessage",
            3600,
            "Maximum",
            172800,  # 48h in seconds
            GTE,
            {"QueueName": "life-platform-alerts-digest-queue"},
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

        # ══════════════════════════════════════════════════════════════
        # ADR-143 (#1333): the paging P1 set — the ONLY alarms that reach the
        # phone, via the DEDICATED life-platform-paging topic (CoreStack). The
        # SMS subscription is operator-wired from SSM /life-platform/paging-phone
        # by deploy/wire_paging_phone.sh. Set membership (≤5, incl. the two
        # canary outage legs in operational_stack) is pinned by
        # tests/test_paging_alarms_1333.py; growing it is an ADR-143 amendment.
        # ══════════════════════════════════════════════════════════════
        paging = sns.Topic.from_topic_arn(self, "PagingTopic", PAGING_TOPIC_ARN)

        # Budget tier 3 = the ADR-063 hard cutoff (website AI dark, brief degraded).
        # Distinct from life-platform-budget-tier-escalation above (>=2, digest):
        # tier 2 is a posture change worth reading about; tier 3 is worth a page.
        paging_budget_tier3 = cloudwatch.Alarm(
            self,
            "PagingBudgetTier3",
            alarm_name="paging-budget-tier-3",
            metric=cloudwatch.Metric(
                namespace="LifePlatform/Budget", metric_name="BudgetTier", period=Duration.seconds(3600), statistic="Maximum"
            ),
            evaluation_periods=1,
            threshold=3,
            comparison_operator=GTE,
            treat_missing_data=NB,
        )
        paging_budget_tier3.add_alarm_action(cw_actions.SnsAction(paging))

        # Total-pipeline-failure class: >=8 of the ~15 ingestion sources stale at
        # once (creds/region/scheduler dead), not one flaky source — single-source
        # staleness stays a digest item (slo-source-freshness above).
        paging_pipeline_dead = cloudwatch.Alarm(
            self,
            "PagingPipelineDead",
            alarm_name="paging-pipeline-dead",
            metric=cloudwatch.Metric(
                namespace="LifePlatform/Freshness", metric_name="StaleSourceCount", period=Duration.seconds(86400), statistic="Maximum"
            ),
            evaluation_periods=1,
            threshold=8,
            comparison_operator=GTE,
            treat_missing_data=NB,
        )
        paging_pipeline_dead.add_alarm_action(cw_actions.SnsAction(paging))

        # ══════════════════════════════════════════════════════════════
        # #411 / ADR-116: two UNIQUE silent-failure signals adopted into IaC.
        # Both existed only as hand-created (CLI-era) orphan alarms — the CloudWatch
        # cost audit (docs/reviews/CLOUDWATCH_AUDIT_2026-07.md §3b) codifies them here
        # under IaC-owned names so they are managed + reviewable. The manual originals
        # (life-platform-compute-pipeline-stale, health-auto-export-no-invocations-24h)
        # are deleted by deploy/cloudwatch_retire_orphans.sh; new names avoid any
        # CloudFormation collision at deploy time.
        # ══════════════════════════════════════════════════════════════
        # Compute-pipeline staleness: daily_brief emits ComputePipelineStaleness=1
        # (Source=computed_metrics) when the pre-computed compute artifacts it reads
        # are stale. The freshness digest watches INGESTION sources; nothing else
        # watches the COMPUTE pipeline going stale behind the brief. Digest.
        _alarm(
            "ComputePipelineStale",
            "compute-pipeline-stale",
            "LifePlatform",
            "ComputePipelineStaleness",
            86400,
            "Maximum",
            1,
            GTE,
            dims={"Source": "computed_metrics"},
            to_digest=True,
        )

        # #1455: compute-output completeness. pipeline-health-check's 16:58 UTC
        # {check_compute_outputs} run has emitted
        # LifePlatform/Pipeline::ComputeOutputsMissing on every run since Phase 3.2
        # — but nothing alarmed it, so a compute cron that silently died
        # (character-sheet / daily-metrics / daily-insight / adaptive-mode) was only
        # visible if the brief happened to complain about the one partition IT reads.
        # Problem alarm + absence heartbeat (the REL-01 pattern): ≥1 missing compute
        # output = digest alert the same morning; gauge absent 2 straight days = the
        # detector leg itself went dark. Digest — the brief still sends (with stale
        # data flagged), so this is a same-day fix item, not a page.
        _alarm(
            "ComputeOutputsMissing",
            "compute-outputs-missing",
            "LifePlatform/Pipeline",
            "ComputeOutputsMissing",
            86400,
            "Maximum",
            1,
            GTE,
            to_digest=True,
        )
        _heartbeat_alarm(
            "ComputeOutputsHeartbeat",
            "compute-outputs-heartbeat",
            "LifePlatform/Pipeline",
            "ComputeOutputsMissing",
        )

        # HAE webhook liveness: the Health Auto Export webhook (CGM/water/BP/State of
        # Mind) is near-real-time and streams continuously, so <1 invocation in 24h =
        # a dead webhook. treat_missing=BREACHING (absence IS the failure) — the
        # absence-is-failure pattern, apt here because the HAE webhook (unlike the
        # now-event-driven Panel) genuinely streams continuously. Digest — a quiet
        # webhook is worth surfacing but is rarely a same-hour page.
        _hae_silent = cloudwatch.Alarm(
            self,
            "HaeWebhookNoInvocations",
            alarm_name="hae-webhook-no-invocations-24h",
            metric=cloudwatch.Metric(
                namespace="AWS/Lambda",
                metric_name="Invocations",
                dimensions_map={"FunctionName": "health-auto-export-webhook"},
                period=Duration.seconds(86400),
                statistic="Sum",
            ),
            evaluation_periods=1,
            threshold=1,
            comparison_operator=LT,
            treat_missing_data=cloudwatch.TreatMissingData.BREACHING,
        )
        _hae_silent.add_alarm_action(cw_actions.SnsAction(digest))

        # NOTE: OBS-07 email-subscriber alarm lives in web_stack.py (us-east-1).
        # email-subscriber Lambda runs in us-east-1; Lambda metrics are regional.
        # Cross-region alarm would never fire. See web_stack.py SubscriberErrors alarm.

        # OBS-04: site-api cold start alarm deferred — site-api Lambda and its
        # log group (/aws/lambda/site-api) are in us-east-1; MonitoringStack is
        # in us-west-2. Cross-region MetricFilter is not supported.
        # Implement in a separate us-east-1 monitoring construct when needed.

        # ══════════════════════════════════════════════════════════════
        # #1951: subscriber-send kill-switch visibility. Each subscriber-facing
        # weekly sender logs a specific INFO line
        # ("[kill-switch] EXTERNAL_EMAILS_ENABLED=false — skipping ... send")
        # the moment it no-ops on the switch — and before this alarm, NOTHING
        # watched that line. That is exactly how EXTERNAL_EMAILS_ENABLED stayed
        # pinned "false" for ~3 months (since 2026-04-23, commit 0e7abd03) while
        # /subscribe/ kept promising "every Wednesday": every nightly qa-smoke
        # and every CloudWatch dashboard stayed green because a skipped send
        # was never a FAILURE from the Lambda's own point of view, only a
        # quiet no-op. One metric filter + digest alarm per sender makes a
        # paused send a VISIBLE state regardless of which direction the switch
        # is set — this alarm fires whether the pause is deliberate (a future
        # privacy-mode decision) or a regression, same as
        # operational/qa_check_subscriber_promise.py's promise-vs-switch guard
        # covers the /subscribe/ page side of the same defect. 86400s window
        # matches each sender's own at-most-weekly cadence; NOT_BREACHING
        # treat-missing keeps a normal (unskipped) day silent, as intended.
        # ══════════════════════════════════════════════════════════════
        # Inline literal tuple (not a separately-assigned list name) — deploy/sync_doc_metadata.py's
        # alarm-count/alarm-name AST discoverers only multiply/bind through a for-loop whose
        # iterable is a literal Tuple/List/Set node in the `for` statement itself (mirrors the
        # ingest-consecutive-failures loop a few hundred lines above); a Name reference to a
        # module/local list variable resolves to a x1 fallback and an unresolved f-string name.
        for _ks_fn in ("chronicle-email-sender", "weekly-signal", "between-chronicle"):
            _ks_id = "".join(p.capitalize() for p in _ks_fn.split("-"))
            _ks_lg = logs.LogGroup.from_log_group_name(self, f"KillSwitchLg{_ks_id}", f"/aws/lambda/{_ks_fn}")
            _ks_mf = logs.MetricFilter(
                self,
                f"KillSwitchMf{_ks_id}",
                log_group=_ks_lg,
                filter_pattern=logs.FilterPattern.all_terms("[kill-switch]", "skipping", "subscriber send"),
                # Per-sender metric NAME, not a dimension: CloudWatch Logs rejects
                # dimensions on plain-term filter patterns (deploy-time 400 that
                # cdk synth does not catch) — dimensions need JSON/field patterns.
                metric_name=f"SubscriberSendSkippedByKillSwitch{_ks_id}",
                metric_namespace="LifePlatform/Email",
                metric_value="1",
            )
            _ks_alarm = cloudwatch.Alarm(
                self,
                f"KillSwitchAlarm{_ks_id}",
                alarm_name=f"life-platform-{_ks_fn}-kill-switch-skip",
                metric=_ks_mf.metric(period=Duration.hours(24), statistic="Sum"),
                evaluation_periods=1,
                threshold=1,
                comparison_operator=GTE,
                treat_missing_data=NB,
            )
            _ks_alarm.add_alarm_action(cw_actions.SnsAction(digest))

        # ══════════════════════════════════════════════════════════════
        # Dashboards (the VIEW, not the contract) — #2610 extracted both
        # CloudWatch dashboards into the cohesive sibling
        # stacks/monitoring_dashboards.py. Same scope, same order, so every
        # logical id is unchanged; the synthesized template is byte-identical.
        # This module was at 1623/1623 — zero headroom — so the next alarm
        # could not be added at all. Alarms stay here; views live next door.
        # ══════════════════════════════════════════════════════════════
        add_dashboards(self)
