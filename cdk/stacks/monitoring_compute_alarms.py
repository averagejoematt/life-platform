"""cdk/stacks/monitoring_compute_alarms.py — the COMPUTE-pipeline liveness alarms.

Extracted from ``monitoring_stack.py`` by #3473, on a seam that module's own comments
had already drawn ("the REL-01 pattern"). One cohesive concern:

    The daily brief READS pre-computed artifacts it does not produce. Four compute
    crons (character-sheet / daily-metrics / daily-insight / adaptive-mode) fill those
    partitions before it runs. When one dies quietly the brief still sends — with stale
    numbers — so the failure is invisible at the only surface a human looks at. These
    alarms watch the compute pipeline itself, behind the brief.

MEMBERSHIP RULE (so the next one lands here, not back in the stack): the alarm keys on a
metric emitted by a DAILY COMPUTE detector about the compute pipeline's own freshness or
completeness, and it ships as a PAIR — a "≥1 problem" alarm with treat_missing_data=NB,
plus an absence heartbeat that reds when the detector's own gauge stops arriving. That
pairing is what separates these from the ingestion-side liveness alarms (ingest-liveness,
freshness-interior-gap), which stay in ``monitoring_stack.py`` beside the ER-01 sweep they
belong to, and from ``monitoring_silence_alarms.py``, whose members key on a log TOKEN.

    compute-pipeline-stale       + compute-pipeline-stale-heartbeat   (#411, #3473)
    compute-outputs-missing      + compute-outputs-heartbeat          (#1455)

WHY THE EXTRACTION. ``monitoring_stack.py`` sat AT its recorded 1331-line ratchet
baseline — zero headroom, and #3473's heartbeat needed ~11 lines. The guard's own rule for
a FULL file is to extract a cohesive sibling and pay for the new lines out of what came
out, never to raise the number (the #2604/#2610/#2977 precedent).

WHY #3473 EXISTED AT ALL, AND WHAT ACTUALLY CLOSES IT. ``compute-pipeline-stale`` consumes
``ComputePipelineStaleness`` with treat_missing_data=NB — deliberately, so #3430's
authoritative-run gate can suppress an off-schedule emission by emitting nothing. Its
sibling ``compute-outputs-missing`` pairs that shape with a heartbeat; this one never got
one, so a dark emitter read as a permanently healthy pipeline (the absence-read-as-success
class). But the missing ALARM was the symptom. The cause is that
``tests/test_silent_failure_heartbeats.py``'s ``_DETECTORS`` ledger — the registry that
asserts "every daily detector has both halves" — listed five pairs and named NEITHER
compute pair, so neither omission was visible to the guard that exists to see it. Both
pairs are in that ledger now: the instance and the set (#3473).

LOGICAL IDS ARE LOAD-BEARING. ``add_compute_alarms(scope, digest)`` is called once from
``MonitoringStack.__init__`` at the position the moved blocks occupied, with ``scope=self``
— so ``self`` became ``scope`` and nothing else did. The three ALREADY-DEPLOYED constructs
(``ComputePipelineStale``, ``ComputeOutputsMissing``, ``ComputeOutputsHeartbeat``) keep
their ids and are not replaced; the synthesized template gains exactly one resource.

WHY days=2 AND NOT THE 26h THE ISSUE ASKED FOR. ``ComputePipelineStaleness`` is emitted
once a day by the 17:00Z brief, and CloudWatch's 86400s periods align to UTC midnight, so
the in-progress period is empty from 00:00Z until 17:00Z every single day. A 1-day
BREACHING heartbeat would therefore fire every morning — which is exactly why
``monitoring_stack``'s own helper comment says N consecutive days "avoids a false fire from
the in-progress UTC period". days=2 reds after >31h of real silence (last emission 17:00Z
day N, two empty daily buckets closing during day N+2), which satisfies the issue's
">26h" bar without inventing a daily false positive to meet it exactly.
"""

from aws_cdk import (
    Duration,
    aws_cloudwatch as cloudwatch,
    aws_cloudwatch_actions as cw_actions,
)

GTE = cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD
LT = cloudwatch.ComparisonOperator.LESS_THAN_THRESHOLD
NB = cloudwatch.TreatMissingData.NOT_BREACHING


def _compute_problem_alarm(scope, digest, alarm_id, alarm_name, namespace, metric_name, dims=None):
    """The "≥1 problem today" half. Mirrors monitoring_stack's `_alarm(...,
    to_digest=True)` exactly: 86400s Maximum >= 1, NOT_BREACHING, digest topic.
    NB is deliberate — absence here is the heartbeat's question, not this alarm's."""
    a = cloudwatch.Alarm(
        scope,
        alarm_id,
        alarm_name=alarm_name,
        metric=cloudwatch.Metric(
            namespace=namespace,
            metric_name=metric_name,
            dimensions_map=dims or {},
            period=Duration.seconds(86400),
            statistic="Maximum",
        ),
        evaluation_periods=1,
        threshold=1,
        comparison_operator=GTE,
        treat_missing_data=NB,
    )
    a.add_alarm_action(cw_actions.SnsAction(digest))
    return a


def _compute_heartbeat_alarm(scope, digest, alarm_id, alarm_name, namespace, metric_name, dims=None, days=2):
    """The absence half (REL-01). Byte-for-byte the config of monitoring_stack's helper
    of the same name: SampleCount < 1 over `days` consecutive full days, BREACHING.
    The name is UNIQUE across cdk/stacks/*.py by contract: the #3314 routing tracer
    resolves a helper by BARE NAME, so reusing `_heartbeat_alarm` here silently made
    BOTH compute heartbeats unroutable (caught by test_stack_helper_names_are_unique).
    It is registered in tests/test_silent_failure_heartbeats.py::_HEARTBEAT_FACTORIES,
    which shape-asserts every registered factory is BREACHING and accepts any of them
    as declaring a heartbeat — so a hand-rolled alarm still cannot pass as one."""
    a = cloudwatch.Alarm(
        scope,
        alarm_id,
        alarm_name=alarm_name,
        metric=cloudwatch.Metric(
            namespace=namespace,
            metric_name=metric_name,
            dimensions_map=dims or {},
            period=Duration.seconds(86400),
            statistic="SampleCount",
        ),
        evaluation_periods=days,
        datapoints_to_alarm=days,
        threshold=1,
        comparison_operator=LT,
        treat_missing_data=cloudwatch.TreatMissingData.BREACHING,
    )
    a.add_alarm_action(cw_actions.SnsAction(digest))
    return a


def add_compute_alarms(scope, digest) -> None:
    """Attach both compute-pipeline liveness pairs to `scope`. See the module docstring."""
    # ══════════════════════════════════════════════════════════════
    # #411 / ADR-116: adopted into IaC from a hand-created (CLI-era) orphan alarm
    # (life-platform-compute-pipeline-stale), per the CloudWatch cost audit
    # (docs/reviews/CLOUDWATCH_AUDIT_2026-07.md §3b). The manual original is deleted by
    # deploy/cloudwatch_retire_orphans.sh; the new name avoids a CloudFormation collision.
    #
    # daily_brief emits ComputePipelineStaleness=1 (Source=computed_metrics) when the
    # pre-computed artifacts it reads are stale. The freshness digest watches INGESTION
    # sources; nothing else watches the COMPUTE pipeline going stale behind the brief.
    # ══════════════════════════════════════════════════════════════
    _compute_problem_alarm(
        scope,
        digest,
        "ComputePipelineStale",
        "compute-pipeline-stale",
        "LifePlatform",
        "ComputePipelineStaleness",
        dims={"Source": "computed_metrics"},
    )
    # #3473: the half this pair never had. Same dimension as the problem alarm — a
    # heartbeat on the undimensioned metric would be satisfied by ANY source's emission
    # and so could not see computed_metrics going dark, which is the only thing it is
    # here to watch (guard the set you actually mean).
    _compute_heartbeat_alarm(
        scope,
        digest,
        "ComputePipelineStaleHeartbeat",
        "compute-pipeline-stale-heartbeat",
        "LifePlatform",
        "ComputePipelineStaleness",
        dims={"Source": "computed_metrics"},
    )

    # #1455: compute-output completeness. pipeline-health-check's 16:58 UTC
    # {check_compute_outputs} run has emitted LifePlatform/Pipeline::ComputeOutputsMissing
    # on every run since Phase 3.2 — but nothing alarmed it, so a compute cron that
    # silently died (character-sheet / daily-metrics / daily-insight / adaptive-mode) was
    # only visible if the brief happened to complain about the one partition IT reads.
    # ≥1 missing compute output = digest alert the same morning; gauge absent 2 straight
    # days = the detector leg itself went dark. Digest — the brief still sends (with stale
    # data flagged), so this is a same-day fix item, not a page.
    _compute_problem_alarm(
        scope,
        digest,
        "ComputeOutputsMissing",
        "compute-outputs-missing",
        "LifePlatform/Pipeline",
        "ComputeOutputsMissing",
    )
    _compute_heartbeat_alarm(
        scope,
        digest,
        "ComputeOutputsHeartbeat",
        "compute-outputs-heartbeat",
        "LifePlatform/Pipeline",
        "ComputeOutputsMissing",
    )
