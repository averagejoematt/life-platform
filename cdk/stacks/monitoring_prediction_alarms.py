"""cdk/stacks/monitoring_prediction_alarms.py — the prediction-science alarms (#727/#3046).

Extracted from monitoring_stack.py the same way the dashboards were (#2610): the
stack file sits at its module-size ratchet baseline, so the seam the codebase
already recognises — a sibling module invoked from the same scope, same order —
is where new alarm surface lands. Both alarms watch the coach-prediction-
evaluator's LifePlatform/Predictions namespace and route to the digest topic.
"""

from aws_cdk import (
    Duration,
    aws_cloudwatch as cloudwatch,
    aws_cloudwatch_actions as cw_actions,
)

_GTE = cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD
_LT = cloudwatch.ComparisonOperator.LESS_THAN_THRESHOLD

_NAMESPACE = "LifePlatform/Predictions"


def add_prediction_alarms(scope, digest) -> None:
    """The two science-liveness alarms, complementary by design:

    - grading-stalled (#727) watches RECENCY: days since the evaluator last
      decided anything (BREACHING on absence, so a dead evaluator also fires).
    - prediction-gradable-share-low (#3046) watches COMPOSITION: the stalled
      alarm resets on ANY decided outcome, so a corpus whose MAJORITY is
      structurally ungradeable (the DIL-007 finding — 28/50 pending were
      eval_type=qualitative, which the evaluator skips) stayed invisible as
      long as one gradable call resolved now and then. The share alarm cannot
      be reset by a lone decided outcome — only by the corpus getting healthier.
    """
    # #727: scientific-liveness heartbeat. The coach-prediction-evaluator ran
    # daily for WEEKS and graded nothing, and no alarm noticed — every heartbeat
    # in monitoring_stack watches the ingestion/coherence PIPELINE, none watched
    # the SCIENCE. The evaluator emits DaysSinceLastDecided every run: whole days
    # since grading last produced a confirmed/refuted outcome (999 = never, this
    # cycle). ALARM when it sits >= 14 for 2 consecutive daily periods. ONE alarm
    # covers BOTH failure modes: a genuine 14-day grading stall, AND a dead
    # evaluator (treat_missing=BREACHING — an absent gauge is itself a stall).
    # 2 periods, not 1, mirrors the REL-01 heartbeats' guard against a false fire
    # from the in-progress UTC period. Fires on the CURRENT state the day it
    # deploys — grading has been dark for weeks, which is exactly the point
    # (E1.3 / #727 AC). Digest.
    grading_stalled = cloudwatch.Alarm(
        scope,
        "GradingStalled",
        alarm_name="grading-stalled",
        metric=cloudwatch.Metric(
            namespace=_NAMESPACE,
            metric_name="DaysSinceLastDecided",
            period=Duration.seconds(86400),
            statistic="Maximum",
        ),
        evaluation_periods=2,
        datapoints_to_alarm=2,
        threshold=14,
        comparison_operator=_GTE,
        treat_missing_data=cloudwatch.TreatMissingData.BREACHING,
    )
    grading_stalled.add_alarm_action(cw_actions.SnsAction(digest))

    # #3046: GradableCount/TotalPending composition. The evaluator emits
    # GradableShare = gradable / (gradable + ungradeable-pending) on every run
    # with a non-empty pending corpus (an empty board has no composition to
    # judge). ALARM when the gradable share sits below 0.5 — an ungradeable
    # MAJORITY — for 3 consecutive daily periods. treat_missing=NOT_BREACHING:
    # a dead evaluator is grading-stalled's job (its gauge breaches on absence);
    # duplicating that here would double-fire every evaluator outage.
    # NB: fires on the CURRENT corpus the day it deploys (28/50 pending are
    # legacy qualitative rows) and clears as the evaluator retires them at
    # window end (_retire_ungradeable) — deliberate, same posture as #727.
    share_low = cloudwatch.Alarm(
        scope,
        "PredictionGradableShareLow",
        alarm_name="prediction-gradable-share-low",
        metric=cloudwatch.Metric(
            namespace=_NAMESPACE,
            metric_name="GradableShare",
            period=Duration.seconds(86400),
            statistic="Minimum",
        ),
        evaluation_periods=3,
        datapoints_to_alarm=3,
        threshold=0.5,
        comparison_operator=_LT,
        treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
    )
    share_low.add_alarm_action(cw_actions.SnsAction(digest))
