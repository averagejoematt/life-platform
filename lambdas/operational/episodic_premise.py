"""lambdas/operational/episodic_premise.py — is "episodic" still true? (#3554)

`cost_governor_lambda` splits the four CallerClass values into the ones its month-end
projection extrapolates (PROJECTED_CALLER_CLASSES — prod-cron, remediation) and the ones
it excludes (EPISODIC_CALLER_CLASSES — ci, dev-session). The exclusion is correct in
principle and it is what stops one dev session reading as a permanent run-rate (#2892).

But it rests on a CLAIM ABOUT BEHAVIOUR: that an episodic class's trailing rate says what
a human did last week, not what the calendar will do next week. Nothing measured that
claim, so the label could quietly outlive the behaviour it described while the public
receipt kept publishing a projection narrowed on it. Measured 2026-09-05 for the issue
that filed this: `LifePlatform/AI::EstimatedCostUSD{CallerClass=ci}` had a datapoint on
12 of the 12 UTC days for which the dimension had existed (daily 1.13, 0.91, 2.84, 3.57,
2.83, 0.39, 1.79, 1.36, 0.86, 1.02, 0.23, 0.36 — roughly $44/month), which is not what a
class that "tracks a human's session" looks like.

This module is the measurement plus the rule. Two deliberate design choices:

  * The RULE is pure — it takes the measurement as an argument and reads no AWS — so it
    is proved with positive and negative controls rather than against whatever the fleet
    happens to be doing on the day the suite runs
    (tests/test_caller_class_attribution_2892.py).
  * A failed metric read records **None, never 0**. Zero reads as "the premise holds",
    which is the absence-as-success shape this guard exists to avoid; None makes every
    consumer say "premise check unavailable" instead.

It deliberately does NOT change the arithmetic. Silently re-scoping the number the tier
ladder is calibrated against, out of a display metric, is a decision that belongs to a
human. The guard's job is that the label can no longer be wrong in silence: the result
lands in the persisted breakdown, and from there in the daily brief's headroom line and
on /api/receipts.

Split out of cost_governor_lambda rather than added to it: that module sat 11 lines under
the 1200-line ceiling (tests/test_module_size_guard.py), and this is a cohesive seam
anyway — one question, its measurement, its bar, and the fields it persists. The governor
keeps four call sites and no logic.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# The window and the bar. 25 of 30 reads as "bills on essentially every day the platform
# runs at all", with room for the weekend gaps a genuinely human-driven class shows.
EPISODIC_PREMISE_WINDOW_DAYS = 30
EPISODIC_PREMISE_BAR_DAYS = 25


def episodic_premise_violations(
    billing_days_by_class: dict,
    episodic_classes=(),
    bar_days: int = EPISODIC_PREMISE_BAR_DAYS,
) -> list:
    """Classes labelled EPISODIC that nonetheless billed on >= `bar_days` days.

    Pure. A class whose count is None is UNKNOWN (the metric read failed) and is never
    counted as a pass: it is absent from the violation list, and consumers surface
    "premise check unavailable" off the None in the recorded counts rather than off
    silence here.
    """
    out = []
    for cls in episodic_classes or ():
        n = (billing_days_by_class or {}).get(cls)
        if n is None:
            continue
        try:
            if int(n) >= int(bar_days):
                out.append(str(cls))
        except (TypeError, ValueError):
            continue
    return sorted(out)


def billing_days_by_class(
    cw,
    classes,
    dimension: str,
    now: datetime,
    window_days: int = EPISODIC_PREMISE_WINDOW_DAYS,
) -> dict:
    """Days in the trailing window on which each class emitted any spend.

    Same self-emitted series `cost_governor_lambda._self_reported_cost_by_class` reads,
    at Period=86400 so each datapoint IS a UTC day, and COUNTED rather than summed — the
    premise is about frequency, not magnitude ("does this class bill like a calendar or
    like a person?"). One GetMetricStatistics per class, i.e. ~12/day at the governor's
    8h cadence: the same order as the class-split read it sits beside, and noise against
    the CloudWatch line. No new IAM (the governor already holds
    cloudwatch:GetMetricStatistics on `*`).
    """
    out: dict = {}
    start = now - timedelta(days=int(window_days))
    for cls in classes:
        try:
            resp = cw.get_metric_statistics(
                Namespace="LifePlatform/AI",
                MetricName="EstimatedCostUSD",
                Dimensions=[{"Name": dimension, "Value": cls}],
                StartTime=start,
                EndTime=now,
                Period=86400,
                Statistics=["Sum"],
            )
            out[cls] = sum(1 for d in resp.get("Datapoints", []) if float(d.get("Sum") or 0.0) > 0.0)
        except Exception as e:  # noqa: BLE001 — display-only; unknown is not zero
            logger.warning(f"caller-class billing-day query failed for {cls} (non-critical, records unknown): {e}")
            out[cls] = None
    return out


def premise_fields(billing_days: dict, episodic_classes) -> dict:
    """The four breakdown keys the receipt and the daily brief read (#3554).

    Assembled here rather than inline in `_write_breakdown` so the window, the bar and
    the verdict can never be persisted out of step with the rule that produced them.
    """
    return {
        # None means the metric read failed — UNKNOWN, not zero — so a telemetry gap
        # can never read as a clean bill of health for the label.
        "episodic_billing_days": {k: (None if v is None else int(v)) for k, v in (billing_days or {}).items()},
        "episodic_premise_window_days": EPISODIC_PREMISE_WINDOW_DAYS,
        "episodic_premise_bar_days": EPISODIC_PREMISE_BAR_DAYS,
        "episodic_premise_violations": episodic_premise_violations(billing_days or {}, episodic_classes),
    }


def report(billing_days: dict, episodic_classes, projected: float, projected_all_classes: float) -> list:
    """Evaluate the premise and log the break loudly. Returns the violation list.

    The log line carries BOTH projections because that gap is the size of the error the
    broken label is causing — a violation with no magnitude beside it is a fact nobody
    can prioritise.
    """
    broken = episodic_premise_violations(billing_days or {}, episodic_classes)
    if broken:
        logger.warning(
            f"EPISODIC_PREMISE_BROKEN classes={broken} billing_days={billing_days} "
            f"bar={EPISODIC_PREMISE_BAR_DAYS}/{EPISODIC_PREMISE_WINDOW_DAYS}d — the projection excludes a class that "
            f"bills like a schedule; projected=${projected:.2f} vs all-classes=${projected_all_classes:.2f}"
        )
    return broken
