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
        # The canary runs WEEKLY (Mon). CloudWatch caps an hourly+ alarm's window at
        # 7 days (EvaluationPeriods × Period ≤ 604800), so a >7-day heartbeat is
        # impossible as a single alarm — days=9 was rejected at CREATE. days=7 is the
        # max AND exactly right: the trailing-7-day window always contains one
        # scheduled run, so it fires the first time a weekly run is missed (a full 7
        # days with no datapoint) and never on a healthy cadence.
        _heartbeat_alarm(
            "AiCanaryHeartbeat",
            "ai-canary-heartbeat",
            "LifePlatform/AICanary",
            "OverallAlarm",
            days=7,
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
        # for 24h — exactly how Garmin/Strava stayed dead for weeks. Dimensionless
        # + Minimum: if ANY breaker source emits a 0 in the window, Min=0 → fire.
        # Absence (no breaker source ran at all) is NOT a failure — the freshness
        # checker covers prolonged data gaps; here we only care about a source
        # that ran and got auth-suppressed.
        _ingest_auth_dead = cloudwatch.Alarm(
            self,
            "IngestAuthUnhealthy",
            alarm_name="ingest-auth-unhealthy-24h",
            metric=cloudwatch.Metric(
                namespace="LifePlatform/OAuth",
                metric_name="IngestAuthHealthy",
                period=Duration.seconds(86400),
                statistic="Minimum",
            ),
            evaluation_periods=1,
            threshold=1,
            comparison_operator=LT,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )
        _ingest_auth_dead.add_alarm_action(cw_actions.SnsAction(topic))

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
        _alarm(
            "AiTokensPlatformTotal", "ai-tokens-platform-daily-total", "LifePlatform/AI", "AnthropicOutputTokens", 86400, "Sum", 150000, GTE
        )

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
