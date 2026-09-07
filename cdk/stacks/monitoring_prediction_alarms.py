"""cdk/stacks/monitoring_prediction_alarms.py — the prediction-science alarms (#727/#3046).

Extracted from monitoring_stack.py the same way the dashboards were (#2610): the
stack file sits at its module-size ratchet baseline, so the seam the codebase
already recognises — a sibling module invoked from the same scope, same order —
is where new alarm surface lands. Both alarms watch the coach-prediction-
evaluator's LifePlatform/Predictions namespace and route to the digest topic.
"""

import sys
from pathlib import Path

from aws_cdk import (
    Duration,
    aws_cloudwatch as cloudwatch,
    aws_cloudwatch_actions as cw_actions,
)

# #3553: the dead-man's name, metric names, expression and window come from the module
# the Lambda emits with, not from four literals typed a second time here — the same
# sys.path idiom ingestion_stack.py uses for source_registry. commitment_grading is
# boto3-free by construction precisely so this import is cheap and safe at synth time.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "lambdas"))
from coach import commitment_grading  # noqa: E402

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


def add_commitment_alarms(scope, digest) -> None:
    """#3553: the dead-man on the follow-through ledger.

    The #532 commitment ledger ran for its ENTIRE LIFE — cycles 5 through 17, 503
    records, 52 of them past a due date they had a deterministic check for — and
    returned 0 kept / 0 broken. The evaluator logged `Commitment stats: kept=0
    broken=0` on every run for 21 straight days and nothing read the line: no alarm, no
    test, no page. That is the whole failure. The grading bugs were fixable in an
    afternoon; the reason they lasted four months is that the instrument had no reader.

    So this alarm reads the two numbers together. `CommitmentsDueCheckable` is the
    denominator (there was gradeable work) and `CommitmentsGraded` is the numerator (a
    verdict came out). ALARM when there was work and no verdict, for DEADMAN_DAYS
    consecutive daily periods (7 — CloudWatch's own ceiling, see below).

    Neither half alone would have caught this. `graded == 0` on its own fires on a
    legitimately quiet fortnight — the ledger is allowed to have nothing due. `due > 0`
    on its own fires on a perfectly healthy backlog. It is the CONJUNCTION that says
    "work arrived and the grader produced nothing", which is the sentence the live
    defect would have set off on day 14 of 120.

    treat_missing_data=BREACHING, deliberately: an evaluator that stops running emits
    neither metric, and a dead grader is the failure this exists to catch — the same
    posture as grading-stalled's gauge, and the opposite of prediction-gradable-share-
    low (whose absence is already covered by that gauge). Digest-routed, not paging:
    a stalled ledger is a next-morning problem.

    The expression and the window are `commitment_grading`'s own constants, so the
    alarm and the Python predicate `deadman_breached()` cannot drift into meaning
    different things — tests/test_commitment_grading_3553.py drives BOTH against one
    truth table.

    #3685: the window is SEVEN days, not the fourteen this first shipped with, and the
    period comes from the same module as the count. CloudWatch rejects any alarm whose
    EvaluationPeriods x Period exceeds 604800s once Period is >= 3600s, so 14 x 86400
    was uncreatable — the alarm CREATE_FAILED, this stack rolled back, and the dead-man
    never existed in AWS. `cdk synth` renders the oversized window happily; the ceiling
    is enforced service-side at CREATE. tests/test_alarm_evaluation_window_3685.py is
    the guard that now catches it here, by resolving these very constants.
    """
    period = Duration.seconds(commitment_grading.DEADMAN_PERIOD_SECONDS)
    ungraded = cloudwatch.Alarm(
        scope,
        "CommitmentsUngraded",
        # A LITERAL, deliberately. `deploy/alarm_discovery.py` resolves alarm NAMES by
        # static AST and an attribute reference is invisible to it, so an alarm declared
        # by constant is COUNTED but never NAMED — and the name set silently diverges
        # from the count (tests/test_sync_doc_metadata_check.py). The literal is held
        # equal to commitment_grading.DEADMAN_ALARM_NAME by
        # tests/test_commitment_grading_3553.py, so the two cannot drift.
        alarm_name="commitments-ungraded",
        metric=cloudwatch.MathExpression(
            expression=commitment_grading.DEADMAN_EXPRESSION,
            label="commitments due but ungraded",
            using_metrics={
                "due": cloudwatch.Metric(
                    namespace=commitment_grading.DEADMAN_NAMESPACE,
                    metric_name=commitment_grading.DEADMAN_METRIC_DUE,
                    period=period,
                    statistic="Maximum",
                ),
                "graded": cloudwatch.Metric(
                    namespace=commitment_grading.DEADMAN_NAMESPACE,
                    metric_name=commitment_grading.DEADMAN_METRIC_GRADED,
                    period=period,
                    statistic="Sum",
                ),
            },
            period=period,
        ),
        evaluation_periods=commitment_grading.DEADMAN_DAYS,
        datapoints_to_alarm=commitment_grading.DEADMAN_DAYS,
        threshold=1,
        comparison_operator=_GTE,
        treat_missing_data=cloudwatch.TreatMissingData.BREACHING,
    )
    ungraded.add_alarm_action(cw_actions.SnsAction(digest))
