"""
cost_governor_lambda.py — near-real-time AWS spend estimator + budget-tier setter.

Why this exists: AWS Bedrock cost lags 24-48h in Cost Explorer / AWS Budgets,
so budgets alone can't enforce a hard monthly ceiling. This Lambda estimates
month-to-date total spend in near-real-time and projects month-end, then writes
a "budget tier" to SSM that the AI features read (budget_guard.py) to degrade
gracefully. The hard stop lives in bedrock_client.invoke() (Tier 3). AWS Budgets
is the lagged secondary backstop + notice.

Estimate = non-AI (Cost Explorer, all services EXCEPT Bedrock, month-to-date)
         + AI    (AWS/Bedrock per-model token metrics × Bedrock prices, ×buffer)

Tiers (projected month-end total, $75 all-in ceiling):
  0 Normal   < $55
  1 Caution  $55-65   → pause heaviest coach AI (narrative/ensemble/chronicle)
  2 Restrict $65-73   → + pause public website AI (/api/ask, /api/board_ask)
  3 Hard stop ≥ $73   → + pause ALL Bedrock; daily brief goes data-only

Runs hourly. Sets SSM /life-platform/budget-tier (default 0). Alerts on change.
Auto-resets to 0 at month rollover (estimate is month-to-date).

IAM: ce:GetCostAndUsage, cloudwatch:GetMetricData, cloudwatch:PutMetricData,
     ssm:GetParameter, ssm:PutParameter, sns:Publish.
Schedule: hourly (EventBridge).
"""

import calendar
import json
import logging
import os
from datetime import datetime, timezone

import boto3

try:
    from platform_logger import get_logger

    logger = get_logger("cost-governor")
except ImportError:
    logger = logging.getLogger("cost-governor")
    logger.setLevel(logging.INFO)

REGION = os.environ.get("AWS_REGION", "us-west-2")
ACCT = os.environ.get("CDK_ACCOUNT", "205930651321")
SSM_TIER_PARAM = os.environ.get("BUDGET_TIER_PARAM", "/life-platform/budget-tier")
ALERTS_TOPIC = os.environ.get("ALERTS_TOPIC_ARN", f"arn:aws:sns:{REGION}:{ACCT}:life-platform-alerts")
MONTHLY_CEILING = float(os.environ.get("MONTHLY_CEILING_USD", "75"))
# Phase B ships observe-only (emit metrics, don't set tier/alert). Phase C flips
# this to "false" via env to enable enforcement once the estimate is validated.
OBSERVE_MODE = os.environ.get("OBSERVE_MODE", "true").lower() in ("1", "true", "yes")

# Bedrock on-demand prices, USD per 1M tokens (us cross-region inference profiles).
# VERIFY against the Bedrock pricing page on model changes. We bias conservative
# (a buffer below) so the estimate never under-counts the real bill.
_PRICES = {
    "fable": {"in": 10.00, "out": 50.00, "cache_read": 1.00, "cache_write": 12.50},
    "sonnet": {"in": 3.00, "out": 15.00, "cache_read": 0.30, "cache_write": 3.75},
    "haiku": {"in": 1.00, "out": 5.00, "cache_read": 0.10, "cache_write": 1.25},
    "opus": {"in": 5.00, "out": 25.00, "cache_read": 0.50, "cache_write": 6.25},
}
_DEFAULT_PRICE = _PRICES["fable"]  # unknown model → price as the most expensive tier
_AI_SAFETY_BUFFER = 1.15  # bias the AI estimate high so we degrade early, never overshoot

# Tier thresholds on PROJECTED month-end total (USD).
_TIER_THRESHOLDS = [(73, 3), (65, 2), (55, 1)]  # checked high→low; else tier 0

# Days at the start of the month during which the month-end projection is too
# noisy to trust (fixed monthly charges are front-loaded onto day 1). Inside this
# window we escalate on ACTUAL mtd vs ceiling instead of the projection.
EARLY_MONTH_DAYS = 5.0

_cw = boto3.client("cloudwatch", region_name=REGION)
_ssm = boto3.client("ssm", region_name=REGION)
_sns = boto3.client("sns", region_name=REGION)
# Cost Explorer is a global service homed in us-east-1.
_ce = boto3.client("ce", region_name="us-east-1")


def _month_bounds(now: datetime):
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    days_in_month = calendar.monthrange(now.year, now.month)[1]
    return start, days_in_month


def _non_ai_mtd(month_start: datetime, now: datetime) -> float:
    """Cost Explorer month-to-date for all services EXCEPT Bedrock."""
    start_str = month_start.strftime("%Y-%m-%d")
    end_str = now.strftime("%Y-%m-%d")
    if start_str == end_str:
        return 0.0  # 1st of month, no full day yet
    try:
        resp = _ce.get_cost_and_usage(
            TimePeriod={"Start": start_str, "End": end_str},
            Granularity="MONTHLY",
            Metrics=["UnblendedCost"],
            Filter={"Not": {"Dimensions": {"Key": "SERVICE", "Values": ["Amazon Bedrock"]}}},
        )
        rows = resp.get("ResultsByTime", [])
        return sum(float(r["Total"]["UnblendedCost"]["Amount"]) for r in rows)
    except Exception as e:
        logger.warning(f"Cost Explorer query failed (non-AI): {e}")
        return 0.0


def _price_for(model_id: str) -> dict:
    m = (model_id or "").lower()
    for key, price in _PRICES.items():
        if key in m:
            return price
    return _DEFAULT_PRICE


def _bedrock_metric_sum(metric: str, model_id: str, start: datetime, now: datetime) -> float:
    """Sum an AWS/Bedrock token metric for one ModelId over the month-to-date."""
    try:
        resp = _cw.get_metric_statistics(
            Namespace="AWS/Bedrock",
            MetricName=metric,
            Dimensions=[{"Name": "ModelId", "Value": model_id}],
            StartTime=start,
            EndTime=now,
            Period=2678400,  # 31 days — one bucket
            Statistics=["Sum"],
        )
        return sum(d["Sum"] for d in resp.get("Datapoints", []))
    except Exception as e:
        logger.warning(f"Bedrock metric {metric}/{model_id} failed: {e}")
        return 0.0


def _list_bedrock_models() -> list[str]:
    """Discover which ModelIds emitted token metrics this month."""
    try:
        resp = _cw.list_metrics(Namespace="AWS/Bedrock", MetricName="InputTokenCount")
        ids = set()
        for m in resp.get("Metrics", []):
            for d in m.get("Dimensions", []):
                if d["Name"] == "ModelId":
                    ids.add(d["Value"])
        return sorted(ids)
    except Exception as e:
        logger.warning(f"list_metrics failed: {e}")
        return []


def _ai_cost(start: datetime, now: datetime) -> float:
    """Bedrock spend over [start, now) from per-model token metrics × prices."""
    total = 0.0
    for model_id in _list_bedrock_models():
        p = _price_for(model_id)
        inp = _bedrock_metric_sum("InputTokenCount", model_id, start, now)
        out = _bedrock_metric_sum("OutputTokenCount", model_id, start, now)
        cr = _bedrock_metric_sum("CacheReadInputTokenCount", model_id, start, now)
        cw = _bedrock_metric_sum("CacheWriteInputTokenCount", model_id, start, now)
        cost = (inp * p["in"] + out * p["out"] + cr * p["cache_read"] + cw * p["cache_write"]) / 1_000_000
        if cost:
            logger.info(f"AI model {model_id}: in={inp:.0f} out={out:.0f} " f"cache_r={cr:.0f} cache_w={cw:.0f} → ${cost:.2f}")
        total += cost
    return total * _AI_SAFETY_BUFFER


def _ai_active_days(month_start: datetime, now: datetime) -> int:
    """Distinct days this month with Bedrock activity. Bedrock only began on the
    ADR-062 migration (mid-month), so projecting AI over total elapsed days would
    dilute it — we project over the days AI was actually billing instead."""
    try:
        resp = _cw.get_metric_statistics(
            Namespace="AWS/Bedrock",
            MetricName="InputTokenCount",
            StartTime=month_start,
            EndTime=now,
            Period=86400,
            Statistics=["Sum"],
        )
        return sum(1 for d in resp.get("Datapoints", []) if d["Sum"] > 0)
    except Exception as e:
        logger.warning(f"active-days query failed: {e}")
        return 0


def _tier_for(projected: float) -> int:
    for threshold, tier in _TIER_THRESHOLDS:
        if projected >= threshold:
            return tier
    return 0


def _decide_tier(projected: float, mtd: float, elapsed_days: float) -> int:
    """Tier from the projection, bounded by ACTUAL month-to-date spend.

    The projection is an early-warning signal, but it has two failure modes that
    made it untrustworthy as the SOLE tier input (N-08, 2026-06-06):
      1. Early month: fixed monthly charges (Route53, Secrets Manager, ...) all
         land on day 1, so mtd/elapsed overstates the run-rate (e.g. $15 mtd on
         day 2 → $233 projected → false tier-3 cutoff).
      2. After a pause: ai_daily is a month-average over ACTIVE days, so pausing
         AI freezes the numerator AND the denominator — the projection stays
         inflated for weeks and the tier can never de-escalate (observed: tier 3
         set Jun 5 at $28 mtd would have held until ~Jun 22 with AI fully off).
    Rule: the projection may escalate at most ONE tier above what actual mtd
    justifies. So the harsh tiers (2: website AI off, 3: hard stop) require real
    dollars, not extrapolation — a genuine runaway shows up in actual spend
    within a day and unlocks them — while the projection still buys one tier of
    preemptive degradation (tier 1 pauses the heaviest spender). Inside the
    first EARLY_MONTH_DAYS the projection gets no benefit of the doubt at all.
    """
    projected_tier = _tier_for(projected)
    actual_tier = _tier_for(mtd)
    if elapsed_days < EARLY_MONTH_DAYS:
        tier = min(projected_tier, actual_tier)
    else:
        tier = min(projected_tier, actual_tier + 1)
    if tier != projected_tier:
        logger.info(
            f"Projection tier {projected_tier} (${projected:.2f}) capped to {tier} "
            f"by actual mtd ${mtd:.2f} (actual tier {actual_tier}, "
            f"{elapsed_days:.1f}d elapsed)"
        )
    return tier


def _read_tier() -> int:
    try:
        return int(_ssm.get_parameter(Name=SSM_TIER_PARAM)["Parameter"]["Value"])
    except _ssm.exceptions.ParameterNotFound:
        return 0
    except Exception as e:
        logger.warning(f"SSM read failed: {e}")
        return 0


def _write_tier(tier: int) -> None:
    _ssm.put_parameter(Name=SSM_TIER_PARAM, Value=str(tier), Type="String", Overwrite=True)


_TIER_LABELS = {
    0: "Normal — all AI features active",
    1: "Caution — heavy coach AI paused (narrative/ensemble/chronicle)",
    2: "Restrict — + public website AI paused (/api/ask, /api/board_ask)",
    3: "Hard stop — ALL Bedrock paused; daily brief is data-only",
}


def _alert(prev: int, new: int, mtd: float, projected: float) -> None:
    direction = "raised" if new > prev else "lowered"
    urgent = new >= 3
    subj = f"{'🛑' if urgent else '⚠️'} Budget tier {direction} {prev}→{new}: {_TIER_LABELS[new]}"
    body = (
        f"Budget tier {direction}: {prev} → {new}\n\n"
        f"{_TIER_LABELS[new]}\n\n"
        f"Month-to-date estimated total: ${mtd:.2f}\n"
        f"Projected month-end:           ${projected:.2f}\n"
        f"Ceiling:                       ${MONTHLY_CEILING:.0f}\n\n"
        f"Auto-resumes at month rollover. AI = Bedrock (per-model token metrics "
        f"× price, +{int((_AI_SAFETY_BUFFER - 1) * 100)}% buffer); non-AI = Cost Explorer."
    )
    try:
        _sns.publish(TopicArn=ALERTS_TOPIC, Subject=subj[:99], Message=body)
        logger.info(f"Tier-change alert sent: {prev}→{new}")
    except Exception as e:
        logger.warning(f"SNS publish failed: {e}")


def _emit_metrics(mtd: float, projected: float, tier: int) -> None:
    try:
        _cw.put_metric_data(
            Namespace="LifePlatform/Budget",
            MetricData=[
                {"MetricName": "EstimatedMonthToDateSpend", "Value": mtd, "Unit": "None"},
                {"MetricName": "ProjectedMonthlySpend", "Value": projected, "Unit": "None"},
                {"MetricName": "BudgetTier", "Value": tier, "Unit": "None"},
            ],
        )
    except Exception as e:
        logger.warning(f"PutMetricData failed: {e}")


def lambda_handler(event, context):
    try:
        now = datetime.now(timezone.utc)
        month_start, days_in_month = _month_bounds(now)
        elapsed_days = max((now - month_start).total_seconds() / 86400.0, 0.5)

        non_ai = _non_ai_mtd(month_start, now)
        ai = _ai_cost(month_start, now)
        mtd = non_ai + ai

        # Month-end = what's ALREADY spent (mtd, captured precisely) + the daily
        # run-rate × days REMAINING. (The old `daily × days_in_month` ignored that
        # most of the month already happened, so late in the month it massively
        # over-projected — e.g. $35 mtd on day 29 projected $121.) Non-AI rate is
        # uniform (per elapsed day); AI rate is per ACTIVE day since Bedrock only
        # began mid-month, so it isn't diluted by pre-migration days.
        days_remaining = max(days_in_month - elapsed_days, 0.0)
        non_ai_daily = non_ai / elapsed_days
        ai_active = _ai_active_days(month_start, now)
        ai_daily = (ai / ai_active) if ai_active > 0 else 0.0
        projected = mtd + (non_ai_daily + ai_daily) * days_remaining

        # Projection escalates at most ONE tier above actual mtd spend (and not at
        # all in the early-month window) — see _decide_tier for the two failure
        # modes (front-loaded day-1 charges; post-pause projection that can't decay).
        computed_tier = _decide_tier(projected, mtd, elapsed_days)
        prev = _read_tier()

        logger.info(
            f"Spend: non_ai=${non_ai:.2f} ai=${ai:.2f} (active_days={ai_active}, "
            f"~${ai_daily:.2f}/day) mtd=${mtd:.2f} projected=${projected:.2f} "
            f"computed_tier={computed_tier} prev={prev} observe={OBSERVE_MODE}"
        )
        _emit_metrics(mtd, projected, computed_tier)

        # Phase B ships in OBSERVE mode: emit metrics + log the computed tier, but
        # do NOT write SSM or alert — lets us validate the estimate vs the real
        # AWS bill for a few days before enforcement (Phase C sets OBSERVE_MODE=false).
        if OBSERVE_MODE:
            return {
                "statusCode": 200,
                "body": json.dumps(
                    {
                        "observe_mode": True,
                        "non_ai_mtd": round(non_ai, 2),
                        "ai_mtd": round(ai, 2),
                        "ai_per_day": round(ai_daily, 2),
                        "mtd_total": round(mtd, 2),
                        "projected": round(projected, 2),
                        "computed_tier": computed_tier,
                        "active_tier": prev,
                        "ceiling": MONTHLY_CEILING,
                    }
                ),
            }

        # force_tier in the event lets an AWS-Budgets action pin a floor.
        tier = computed_tier
        forced = event.get("force_tier") if isinstance(event, dict) else None
        if forced is not None:
            tier = max(tier, int(forced))

        if tier != prev:
            _write_tier(tier)
            _alert(prev, tier, mtd, projected)

        return {
            "statusCode": 200,
            "body": json.dumps(
                {
                    "non_ai_mtd": round(non_ai, 2),
                    "ai_mtd": round(ai, 2),
                    "ai_per_day": round(ai_daily, 2),
                    "mtd_total": round(mtd, 2),
                    "projected": round(projected, 2),
                    "tier": tier,
                    "prev_tier": prev,
                    "ceiling": MONTHLY_CEILING,
                }
            ),
        }
    except Exception as e:
        logger.error("cost_governor failed: %s", e, exc_info=True)
        raise
