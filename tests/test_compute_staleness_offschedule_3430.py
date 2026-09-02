"""tests/test_compute_staleness_offschedule_3430.py — #3430.

THE EPISODE. `compute-pipeline-stale` sat in ALARM from 2026-08-30T15:56:48Z to
2026-08-31T15:56:48Z — exactly 24h — and nobody could say why. Traced 2026-09-02:

  * `describe-alarm-history` shows the breaching datapoint was `1.0 @ 2026-08-29T15:56Z`
    with `sampleCount: 2` in the alarm's rolling 24h window, and the clearing datapoint
    `0.0 @ 2026-08-30T15:56Z` with `sampleCount: 1`.
  * The metric itself (`get-metric-statistics`, period 60) puts the 1.0 at
    **2026-08-30T15:55Z** and a 0.0 at 2026-08-30T17:00Z — two emissions, one window.
  * `/aws/lambda/daily-brief` stream `2026/08/30/[$LATEST]76290f64…` starts at
    15:55:39Z and its FIRST log line is
    `[daily-brief] DRY_RUN mode — generating the brief but writing nothing`,
    followed by `No pre-computed metrics for 2026-08-29 — computing inline (fallback)`.
  * `daily-metrics-compute` — the Lambda that writes that row — runs at
    `cron(40 16 * * ? *)`, i.e. **16:40Z, 45 minutes AFTER that invoke**.

So the alarm did not detect a stale pipeline. An operator dry-ran the brief before the
compute cron had had its chance, the row was absent by construction, and the ops metric
went out at 1.0 anyway. The exact-24h shape is the alarm's own arithmetic, not a data
gap: period 86400 with EvaluationPeriods 1 evaluates once per day at a fixed offset, so
ANY single breaching datapoint holds ALARM for exactly one tick.

THE CLASS, measured over the 60 days of retained 5-minute data: ComputePipelineStaleness
emitted 1.0 exactly four times — 2026-07-26 16:05Z, 2026-07-26 16:10Z, 2026-07-27 16:35Z
and 2026-08-30 15:55Z. All four are before 16:40Z, not one is the scheduled 17:00Z brief,
and every scheduled run in the window emitted 0.0 — including the two cycle-11 genesis
mornings #1962 was filed about. The alarm's true-positive rate over 60 days is 0/4.

THE FIX under test: a run that cannot answer the pipeline's question emits nothing.
`_compute_staleness_observation_authoritative` is that predicate, and the emitter is
gated on it. Against pre-#3430 HEAD neither the predicate nor the gate exists, so this
file fails at import (AttributeError) and the structural test fails outright — a real
regression guard, not a vacuous one.
"""

import ast
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lambdas"))
sys.path.insert(0, str(ROOT / "lambdas" / "emails"))

os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("EMAIL_RECIPIENT", "test@example.com")
os.environ.setdefault("EMAIL_SENDER", "noreply@example.com")

import daily_brief_lambda as brief  # noqa: E402

BRIEF_SRC = ROOT / "lambdas" / "emails" / "daily_brief_lambda.py"
COMPUTE_STACK = ROOT / "cdk" / "stacks" / "compute_stack.py"

# The live episode, to the minute, from the CloudWatch record quoted above.
EPISODE_READ_DATE = "2026-08-29"
EPISODE_DRY_RUN_AT = datetime(2026, 8, 30, 15, 55, 40, tzinfo=timezone.utc)
EPISODE_SCHEDULED_AT = datetime(2026, 8, 30, 17, 0, 2, tzinfo=timezone.utc)

SCHEDULED_EVENT = {"source": "aws.events", "detail-type": "Scheduled Event", "detail": {}}
DRY_RUN_EVENT = {"dry_run": True}


class TestTheDeadlineArithmetic:
    """The row for date D is written by the cron that fires on D+1 — not on D."""

    def test_deadline_is_the_day_after_the_read_date_at_the_compute_cron(self):
        deadline = brief._compute_staleness_observation_deadline(EPISODE_READ_DATE)
        assert deadline == datetime(2026, 8, 30, 16, 40, tzinfo=timezone.utc)

    def test_deadline_crosses_a_month_boundary_correctly(self):
        assert brief._compute_staleness_observation_deadline("2026-08-31") == datetime(2026, 9, 1, 16, 40, tzinfo=timezone.utc)


class TestTheEpisodeReplayed:
    """The 2026-08-30 run, at its real clock, with its real payload."""

    def test_the_offschedule_dry_run_that_fired_the_alarm_is_not_authoritative(self):
        assert (
            brief._compute_staleness_observation_authoritative(EPISODE_READ_DATE, event=dict(DRY_RUN_EVENT), now_utc=EPISODE_DRY_RUN_AT)
            is False
        )

    def test_the_scheduled_brief_75_minutes_later_IS_authoritative(self):
        assert (
            brief._compute_staleness_observation_authoritative(EPISODE_READ_DATE, event=dict(SCHEDULED_EVENT), now_utc=EPISODE_SCHEDULED_AT)
            is True
        )


class TestTheTwoWaysARunCannotAnswer:
    def test_a_real_run_before_the_compute_cron_is_still_not_authoritative(self):
        # The clock is the mechanism; the dry-run flag is only how this one arrived.
        assert (
            brief._compute_staleness_observation_authoritative(EPISODE_READ_DATE, event=dict(SCHEDULED_EVENT), now_utc=EPISODE_DRY_RUN_AT)
            is False
        )

    def test_a_dry_run_after_the_cron_is_still_not_authoritative(self):
        assert (
            brief._compute_staleness_observation_authoritative(EPISODE_READ_DATE, event=dict(DRY_RUN_EVENT), now_utc=EPISODE_SCHEDULED_AT)
            is False
        )

    def test_one_minute_before_the_deadline_is_not_authoritative_and_one_after_is(self):
        just_before = datetime(2026, 8, 30, 16, 39, 59, tzinfo=timezone.utc)
        just_after = datetime(2026, 8, 30, 16, 40, 1, tzinfo=timezone.utc)
        assert brief._compute_staleness_observation_authoritative(EPISODE_READ_DATE, event={}, now_utc=just_before) is False
        assert brief._compute_staleness_observation_authoritative(EPISODE_READ_DATE, event={}, now_utc=just_after) is True


class TestTheAlarmCanStillFire:
    """The positive control — suppressing the false red must not cost the true one."""

    def test_a_late_backfill_run_reading_an_old_missing_date_still_reports(self):
        # Reading 2026-08-01's row on 2026-09-02: that cron fired a month ago. If the
        # row is absent, that is a real gap and this run is entitled to say so.
        assert (
            brief._compute_staleness_observation_authoritative(
                "2026-08-01", event=dict(SCHEDULED_EVENT), now_utc=datetime(2026, 9, 2, 3, 0, tzinfo=timezone.utc)
            )
            is True
        )

    def test_the_scheduled_run_with_a_dead_compute_chain_emits_one(self, monkeypatch):
        # The failure mode the alarm exists for: daily-metrics-compute died, so at
        # 17:00Z the row is genuinely missing. Authoritative AND value 1.0.
        class _NoMarkerTable:
            def get_item(self, Key):  # noqa: N803 - boto3 kwarg casing
                return {}

        monkeypatch.setattr(brief, "table", _NoMarkerTable())
        authoritative = brief._compute_staleness_observation_authoritative(
            EPISODE_READ_DATE, event=dict(SCHEDULED_EVENT), now_utc=EPISODE_SCHEDULED_AT
        )
        value, suppressed = brief._compute_staleness_metric_value(True, "2026-08-30")
        assert authoritative is True
        assert (value, suppressed) == (1.0, False)

    def test_an_unparseable_read_date_fails_OPEN_not_silent(self):
        # An unknown deadline must never manufacture silence — that would be a
        # suppressor that suppresses more than it was licensed to.
        assert brief._compute_staleness_observation_authoritative("not-a-date", event={}, now_utc=EPISODE_SCHEDULED_AT) is True


class TestTheEmitterIsActuallyGated:
    """Structural: the predicate is worthless if the put_metric_data call ignores it."""

    def test_the_staleness_put_metric_data_is_nested_under_the_authoritative_check(self):
        tree = ast.parse(BRIEF_SRC.read_text())

        def _mentions_staleness(node):
            return any(isinstance(sub, ast.Constant) and sub.value == "ComputePipelineStaleness" for sub in ast.walk(node))

        gated = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.If):
                continue
            names = {n.id for n in ast.walk(node.test) if isinstance(n, ast.Name)}
            if "_staleness_authoritative" not in names:
                continue
            for sub in ast.walk(node):
                if (
                    isinstance(sub, ast.Call)
                    and isinstance(sub.func, ast.Attribute)
                    and sub.func.attr == "put_metric_data"
                    and _mentions_staleness(sub)
                ):
                    gated.append(sub)

        all_staleness_puts = [
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "put_metric_data" and _mentions_staleness(n)
        ]
        assert len(all_staleness_puts) == 1, f"expected exactly one ComputePipelineStaleness emitter, found {len(all_staleness_puts)}"
        assert gated, "the ComputePipelineStaleness put_metric_data is NOT gated on _staleness_authoritative — #3430 regressed"


class TestTheComputeCronConstantCannotDrift:
    """#2003's rule: a schedule restated outside its registry must be pinned to it."""

    def test_the_deadline_constants_match_daily_metrics_computes_cdk_cron(self):
        src = COMPUTE_STACK.read_text()
        block = src[src.index('function_name="daily-metrics-compute"') :]
        m = re.search(r'schedule="cron\((\d+) (\d+) ', block)
        assert m, "could not read daily-metrics-compute's schedule= from cdk/stacks/compute_stack.py"
        minute, hour = int(m.group(1)), int(m.group(2))
        assert (hour, minute) == (
            brief.COMPUTE_DEADLINE_UTC_HOUR,
            brief.COMPUTE_DEADLINE_UTC_MINUTE,
        ), (
            "daily-metrics-compute's cron moved to "
            f"{hour:02d}:{minute:02d}Z but daily_brief_lambda still assumes "
            f"{brief.COMPUTE_DEADLINE_UTC_HOUR:02d}:{brief.COMPUTE_DEADLINE_UTC_MINUTE:02d}Z (#3430)"
        )

    def test_the_deadline_is_earlier_than_the_daily_briefs_own_schedule(self):
        # If it were not, the scheduled brief itself would stop emitting and the
        # alarm would go dark — the failure mode this gate must never cause.
        email_src = (ROOT / "cdk" / "stacks" / "email_stack.py").read_text()
        block = email_src[email_src.index('function_name="daily-brief"') :]
        m = re.search(r'schedule="cron\((\d+) (\d+) ', block)
        assert m, "could not read daily-brief's schedule= from cdk/stacks/email_stack.py"
        brief_minute, brief_hour = int(m.group(1)), int(m.group(2))
        assert (brief_hour, brief_minute) > (
            brief.COMPUTE_DEADLINE_UTC_HOUR,
            brief.COMPUTE_DEADLINE_UTC_MINUTE,
        ), "the daily brief now runs at or before the compute deadline — every scheduled run would go silent (#3430)"
