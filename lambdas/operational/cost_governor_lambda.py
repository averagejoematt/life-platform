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

Tiers (projected month-end total vs the EFFECTIVE ceiling — base $85 since the
ADR-133 amendment 2026-07-08, $100 in surge mode). The tier bands are fixed
FRACTIONS of the ceiling (≈73%/87%/97%, the original $75 calibration in
_TIER_THRESHOLDS, scaled by _tier_for):
  0 Normal    < 73% of ceiling  ($62.33 at the $85 base)
  1 Caution   73–87%            → pause internal/dev AI (ensemble, chronicle editor,
                                  coherence-semantic)
  2 Restrict  87–97%            → + pause reader narratives (coach commentary,
                                  State of Matthew, chronicle)
  3 Hard stop ≥ 97% of ceiling  ($82.73 at the $85 base) → + pause the ask endpoints
                                  (/api/ask, /api/board_ask) and daily-brief AI;
                                  brief goes data-only
(The dollar figures above are the $85-base ones. A temporary raise window is in
effect — see _TEMP_CEILING_WINDOW for its dates and values — during which the
same percentages trip at proportionally higher dollars. The bands are fractions,
so only the dollars move; deliberately not restated here, because a hardcoded
ceiling figure in a docstring is exactly what check_doc_facts exists to catch.)
(Bands are the audience-ordered ADR-125 ladder — the authority is
budget_guard._FEATURE_CUTOFF, which these labels must mirror; tests/
test_budget_guard_ladder.py pins them in lockstep.)

Runs every 8h (cron(0 0/8 * * ? *)). Sets SSM /life-platform/budget-tier
(default 0). Alerts on change.
Also persists the projection breakdown (mtd/projected/ai+non-ai daily burn) to
SSM /life-platform/budget-breakdown every enforcement run so the daily brief can
render a one-line headroom readout (#822 — a dev sprint alone can trip the tier).
Auto-resets to 0 at month rollover (estimate is month-to-date).

SURGE MODE (ADR-133, #739): the base ceiling is calibrated for near-zero reader
traffic. Real reader arrival (e.g. a Reddit hit) would auto-outage the reader
AI at the moment of success. When the traffic digest's trailing 7-day unique
visitor count (LifePlatform/Traffic::UniqueVisitors7d, emitted weekly by
traffic_digest_lambda) crosses SURGE_UNIQUES_THRESHOLD, the effective monthly
ceiling floats from the base to the surge ceiling ($85 → $100 normally; $115 →
$135 during the August-2026 window, see _TEMP_CEILING_WINDOW) — the pair in effect
today comes from _active_ceilings, and surge is floored at the base so it can
never tighten the guard. See _effective_ceiling.
Tier thresholds scale proportionally with whatever ceiling is in effect (see
_tier_for). Surge is a pure function of reader traffic, never of spend — so a
dev-caused spend spike can NOT trigger it (isolates cause from effect, per
ADR-125's audience-based degradation ladder). Surge state is persisted to SSM
/life-platform/surge-active (for edge-triggered alerting) and reflected in the
budget-breakdown JSON so the daily brief's headroom line can say so.

IAM: ce:GetCostAndUsage, cloudwatch:GetMetricData, cloudwatch:PutMetricData,
     ssm:GetParameter, ssm:PutParameter, sns:Publish.
Schedule: every 8h (EventBridge — cron(0 0/8 * * ? *)).

#2116 (completes #1961): every run also publishes
LifePlatform/AI::TokenAlarmGenesisWindowActive — a 1/0 gauge derived from
`common/token_alarm_window.py`'s stamped genesis rebuild window. This Lambda's
existing 8h cron is the "periodic gauge metric... from existing machinery, no
new cron" the story calls for. `cdk/stacks/monitoring_stack.py` gates the raw
`ai-tokens-platform-daily-total` alarm's urgent-topic SNS action behind a
composite alarm keyed on this gauge, closing #1961's residual gap (the direct
human EmailSubscription had no window awareness even after #2114 fixed the
automated-triage path). See that module's docstring for the full rationale.
"""

import calendar
import json
import logging
import os
from datetime import date, datetime, timedelta, timezone

import boto3

try:
    from common.platform_logger import get_logger

    logger = get_logger("cost-governor")
except ImportError:
    logger = logging.getLogger("cost-governor")
    logger.setLevel(logging.INFO)

try:
    from common.token_alarm_window import is_within_token_alarm_window
except ImportError:  # pragma: no cover - packaging drift; fail safe = gauge reads "not in window"

    def is_within_token_alarm_window(check_date: date | None = None) -> bool:
        return False


REGION = os.environ.get("AWS_REGION", "us-west-2")
ACCT = os.environ.get("CDK_ACCOUNT", "205930651321")
SSM_TIER_PARAM = os.environ.get("BUDGET_TIER_PARAM", "/life-platform/budget-tier")
# R22-COST-05 (#822): the tier alone tells you WHAT changed, not WHY there's no
# headroom left. Only the tier survived each run (SSM); the projection/burn-rate
# breakdown that produced it was logged and thrown away. Persisting it lets the
# daily brief surface a one-line "a dev sprint alone can trip this" fact (see
# budget_guard.read_breakdown / format_headroom_line, the consumer side).
SSM_BREAKDOWN_PARAM = os.environ.get("BUDGET_BREAKDOWN_PARAM", "/life-platform/budget-breakdown")
ALERTS_TOPIC = os.environ.get("ALERTS_TOPIC_ARN", f"arn:aws:sns:{REGION}:{ACCT}:life-platform-alerts")
# Base $85 since 2026-07-08 (ADR-133 amendment; was $75 per ADR-063 — raised by
# Matthew after tier-1 degradation from internal spend creep, $79.27 projected
# vs the old $75).
MONTHLY_CEILING = float(os.environ.get("MONTHLY_CEILING_USD", "85"))
# ADR-133 (#739): surge-mode ceiling. When trailing 7-day unique visitors
# (traffic_digest_lambda's UniqueVisitors7d metric) cross this threshold, the
# effective ceiling floats from MONTHLY_CEILING to SURGE_CEILING_USD. The
# threshold is derived from the real recent baseline (165-288 uniques/week
# observed 2026-06-29..2026-07-06) — see ADR-133 for the exact derivation.
# Both are env-overridable so the numbers are a one-line adjustment, never a
# code change.
SURGE_UNIQUES_THRESHOLD = int(os.environ.get("SURGE_UNIQUES_THRESHOLD", "900"))
SURGE_CEILING_USD = float(os.environ.get("SURGE_CEILING_USD", "100"))
SSM_SURGE_PARAM = os.environ.get("SURGE_ACTIVE_PARAM", "/life-platform/surge-active")
# AUGUST 2026 ONLY (auto-reverts 2026-09-01, no manual step): Matthew's call on
# 2026-08-09 (#2381) — decided in week 2 on purpose, not in a cutoff scramble
# like July's. The 08-09 governor read: mtd $32.51, projected $121.79 against
# the $85 base, ~$3.9/day run-rate; _decide_tier's actual+1 cap put the tier-2
# reader-narrative pause on track for mid-month, and this month a tier-2 pause
# also silences the new Telegram coach chat (ADR-151 budget-ranks it with the
# daily brief). Raised for ONE month; September returns to $85/$100 automatically.
#
# $115/$135 deliberately repeats the July-2026 amendment's shape: the tier bands
# are fixed FRACTIONS of the ceiling (≈73/87/97%), so one raised number moves
# the whole ladder coherently (the July rationale for $115-not-$110 is in the
# ADR-133 2026-07-21 amendment; this window is the 2026-08-09 amendment).
#
# The surge value moves WITH the base ($135 keeps the same ~1.18 ratio as 85→100).
# It has to: _effective_ceiling returns the surge ceiling unconditionally, so a
# surge ceiling BELOW the base would tighten the guard exactly when readers
# arrive. _effective_ceiling now floors it with max() as a structural guard, but
# keeping the pair coherent here means that floor never has to fire.
_TEMP_CEILING_WINDOW = (date(2026, 8, 1), date(2026, 9, 1))  # [start, end)
_TEMP_CEILING_USD = 115.0
_TEMP_SURGE_CEILING_USD = 135.0
# One sentence of WHY, carried in the breakdown payload so a public receipt can
# explain its own raised ceiling instead of leaving the delta unattributed
# (#1999). Reader-facing prose: no dollar figures (the payload carries those),
# no operator jargon.
_TEMP_CEILING_REASON = (
    "A one-month raise Matthew approved on 2026-08-09 (ADR-133 amendment) so the reader-facing "
    "AI and the coach chat stay on through August instead of pausing mid-month. It reverts on its own date."
)
# An explicit MONTHLY_CEILING_USD in the environment is an operator override and
# defeats the window entirely — otherwise setting the env var during July would
# silently do nothing, which is the sort of surprise that costs an afternoon.
_CEILING_ENV_OVERRIDE = "MONTHLY_CEILING_USD" in os.environ
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

# Tier thresholds on PROJECTED month-end total (USD), calibrated against the
# ORIGINAL $75 ceiling (ADR-063). _tier_for scales them by
# ceiling / _THRESHOLD_REFERENCE_CEILING, so the bands are fixed FRACTIONS of
# whatever ceiling is in effect (≈73%/87%/97%) — at the $85 base they trip at
# $62.33 / $73.67 / $82.73; at the $100 surge ceiling at $73.33 / $86.67 / $97.33.
_THRESHOLD_REFERENCE_CEILING = 75.0
_TIER_THRESHOLDS = [(73, 3), (65, 2), (55, 1)]  # checked high→low; else tier 0


# The June-2026 threshold override (#169) was removed 2026-07-21 — its window
# closed 2026-07-01 and it could never fire again. The seam below is kept: it is
# where a future calendar-scoped THRESHOLD override goes, and the tests pin it.
# Note that temporary headroom is now expressed as a raised CEILING
# (_TEMP_CEILING_WINDOW) rather than as shifted thresholds. That is the better
# lever — the bands are fractions of the ceiling, so one number moves the whole
# ladder coherently instead of hand-computing three.
def _active_thresholds():
    return _TIER_THRESHOLDS


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


def _non_ai_daily_series(month_start: datetime, now: datetime) -> list[tuple[str, float]]:
    """Per-day non-Bedrock spend this month via ONE Cost Explorer DAILY call.

    Returns [(YYYY-MM-DD, cost), ...]. Both the MTD total (sum all) and the
    trailing-window run-rate (sum the last N days) derive from this single call,
    so adding the trailing projection costs no extra CE request. DAILY end is
    exclusive, so today's partial day is excluded (same as the prior MTD query).

    Bedrock is billed under per-MODEL service names — "Claude Haiku 4.5 (Amazon
    Bedrock Edition)", "Claude Sonnet 4.6 (Amazon Bedrock Edition)" — NOT a service
    literally named "Amazon Bedrock". The old ``Not Dimensions == "Amazon Bedrock"``
    filter therefore matched nothing, silently letting Bedrock into the "non-AI"
    total — which then DOUBLE-COUNTED against the token-based AI estimate added in
    the handler (observed 2026-06-17: real spend $42.70 MTD, but the governor saw
    $42.70 non-AI + $25.73 AI = $68.43 → projected $119 → false tier-3 hard cutoff).
    Fix: group by SERVICE and drop any service whose name contains "bedrock" in code
    (robust to model-name rotation). AI is metered separately from token metrics
    because CE Bedrock cost lags 24-48h."""
    start_str = month_start.strftime("%Y-%m-%d")
    end_str = now.strftime("%Y-%m-%d")
    if start_str == end_str:
        return []  # 1st of month, no full day yet
    try:
        resp = _ce.get_cost_and_usage(
            TimePeriod={"Start": start_str, "End": end_str},
            Granularity="DAILY",
            Metrics=["UnblendedCost"],
            GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
        )
        out: list[tuple[str, float]] = []
        for r in resp.get("ResultsByTime", []):
            day_total = 0.0
            for g in r.get("Groups", []):
                svc = (g.get("Keys") or [""])[0]
                if "bedrock" in svc.lower():
                    continue  # AI is metered separately, from token metrics
                day_total += float(g["Metrics"]["UnblendedCost"]["Amount"])
            out.append((r["TimePeriod"]["Start"], day_total))
        return out
    except Exception as e:
        logger.warning(f"Cost Explorer daily query failed (non-AI): {e}")
        return []


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


def _project_month_end(
    mtd: float, elapsed_days: float, days_in_month: int, non_ai_recent: float, ai_recent: float, trailing_days: float
) -> float:
    """Month-end projection = already-spent (mtd) + run-rate × days remaining.

    BOTH the AI and non-AI run-rates use a TRAILING window (`recent / trailing_days`),
    not the month-to-date average. The MTD average over-projects two ways:
      • AI: lumpy one-time AI earlier in the month (resets, podcast generation, dev
        batches) inflates the per-day rate.
      • Non-AI: the recurring monthly fixed charges (Secrets Manager, Route53, KMS)
        all land on day 1, so MTD/elapsed treats a one-time lump as a daily rate.
        Those charges are already banked in `mtd` and won't recur this month, so the
        REMAINING days should accrue only the variable daily rate — exactly what the
        trailing window measures (it excludes the day-1 lump once the window clears it).
    Observed 2026-06-15: the MTD method projected ~$115 (and forced a tier-2
    website-AI pause) against a real ~$60-90 run-rate. Trailing tracks the current
    rate. This can only *reduce* false escalation; a genuine runaway still shows up
    in actual mtd within a day and trips the actual-spend cap in _decide_tier.
    """
    days_remaining = max(days_in_month - elapsed_days, 0.0)
    daily_rate = (non_ai_recent + ai_recent) / max(trailing_days, 0.5)
    return mtd + daily_rate * days_remaining


def _tier_for(projected: float, ceiling: float = None) -> int:
    """Tier for `projected` against `ceiling` (default: the current base,
    MONTHLY_CEILING). The thresholds in _active_thresholds() are calibrated
    against the ORIGINAL $75 ceiling (_THRESHOLD_REFERENCE_CEILING); they scale
    by ceiling/reference so the tier BANDS (≈73%/87%/97% of ceiling) stay
    proportionally identical under ANY ceiling — the $85 base (ADR-133
    amendment) or the $100 surge — only the dollar amounts that trip them move.
    ceiling is resolved at call time (None sentinel) so tests can monkeypatch
    MONTHLY_CEILING without hitting the frozen-default trap."""
    if ceiling is None:
        ceiling = MONTHLY_CEILING
    thresholds = _active_thresholds()
    if ceiling != _THRESHOLD_REFERENCE_CEILING:
        ratio = ceiling / _THRESHOLD_REFERENCE_CEILING
        thresholds = [(t * ratio, tier) for t, tier in thresholds]
    for threshold, tier in thresholds:
        if projected >= threshold:
            return tier
    return 0


def _active_ceilings() -> tuple[float, float]:
    """(base, surge) ceilings in effect today.

    Mirrors _active_thresholds: a calendar-scoped override that reverts on its
    own date rather than needing anyone to remember. See _TEMP_CEILING_WINDOW
    for why August 2026 is raised and why the number is $115.
    """
    if _CEILING_ENV_OVERRIDE:
        return MONTHLY_CEILING, SURGE_CEILING_USD
    start, end = _TEMP_CEILING_WINDOW
    if start <= datetime.now(timezone.utc).date() < end:
        return _TEMP_CEILING_USD, _TEMP_SURGE_CEILING_USD
    return MONTHLY_CEILING, SURGE_CEILING_USD


def _active_ceiling_window():
    """Descriptor for the dated temp-ceiling window in effect today, or None.

    #1999: `_active_ceilings()` returns the pair but not WHY it differs from the
    module defaults, so a raised base rendered on the public receipt as an
    unexplained delta (the module base literal, a higher ceiling in effect, and
    surge_active false — every number honest, the mechanism invisible). This is
    the missing attribution:
    the window's dates, the pair it imposes, the pair it reverts to, and one
    sentence of reason, all derived from the same constants `_active_ceilings()`
    reads so the two can never disagree.

    Returns None when no window is active — including when an operator
    MONTHLY_CEILING_USD override has defeated the window entirely, matching
    `_active_ceilings()` exactly (an override means the window is NOT what set
    today's ceiling, so claiming it would be the same lie in the other
    direction).
    """
    if _CEILING_ENV_OVERRIDE:
        return None
    start, end = _TEMP_CEILING_WINDOW
    if not (start <= datetime.now(timezone.utc).date() < end):
        return None
    return {
        "start": start.isoformat(),
        # Exclusive by construction (the comparison above is `< end`); named so a
        # consumer can't render an off-by-one last day.
        "end_exclusive": end.isoformat(),
        "base_ceiling": _TEMP_CEILING_USD,
        "surge_ceiling": _TEMP_SURGE_CEILING_USD,
        "reverts_to_base_ceiling": MONTHLY_CEILING,
        "reverts_to_surge_ceiling": SURGE_CEILING_USD,
        "reason": _TEMP_CEILING_REASON,
    }


def _effective_ceiling(recent_uniques) -> tuple[float, bool]:
    """(ceiling, surge_active) from the trailing 7-day unique-visitor count.

    Surge is a pure function of reader traffic — never of spend — so it can
    only be triggered BY readers arriving, not by a dev/internal spend spike
    (#739 scope constraint: "the ceiling stays at the base when uniques are
    below threshold regardless of projection"). `recent_uniques` is None when
    the metric hasn't been read yet (e.g. transient CloudWatch error) — fails
    closed to the base ceiling, never the surge one.

    Surge is floored at the base: surging must never LOWER the ceiling. Without
    the max() a base above SURGE_CEILING_USD would invert the whole mechanism —
    reader arrival would tighten the guard at the moment surge exists to loosen
    it. Latent at any base over $100; live during the July 2026 window.
    """
    base, surge = _active_ceilings()
    surge = max(surge, base)
    if recent_uniques is not None and recent_uniques >= SURGE_UNIQUES_THRESHOLD:
        return surge, True
    return base, False


def _decide_tier(projected: float, mtd: float, elapsed_days: float, ceiling: float = None) -> int:
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
    projected_tier = _tier_for(projected, ceiling)
    actual_tier = _tier_for(mtd, ceiling)
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


def _tier_crossing_forecast(mtd: float, projected: float, daily_burn: float, now: datetime, ceiling: float = None) -> dict:
    """#2381: the projected DATE each tier band comes into force this month.

    _decide_tier caps the tier at actual_tier + 1 outside the early-month
    window, so once the projection has pinned above a band the binding
    constraint for tier t (t >= 2) is ACTUAL mtd crossing the band BELOW it —
    the derivation that put July's tier-2 scramble a week earlier than the
    naive projection read, and the reason this forecast exists: the next
    posture decision's date should be visible ~two weeks out in the daily
    brief, not discovered at the cutoff. Tier 1 needs no actual spend once the
    projection clears its own band (the +1 cap always allows it).

    A crossing later than the month's last day is None — the month rolls over
    (and the estimate resets) before it happens. Day arithmetic treats mtd as
    an end-of-day figure, so the crossing lands on the first day whose close
    is over the band. Returns {"1": iso-date|None, "2": ..., "3": ...} with
    string keys because the dict ships inside the breakdown JSON. Total
    function: any bad input returns the all-None shape (the payload is
    display-only and must never sink the breakdown write).
    """
    empty = {"1": None, "2": None, "3": None}
    out = dict(empty)
    try:
        if ceiling is None:
            ceiling = MONTHLY_CEILING
        ratio = ceiling / _THRESHOLD_REFERENCE_CEILING
        bands = {tier: threshold * ratio for threshold, tier in _active_thresholds()}
        projected_tier = _tier_for(projected, ceiling)
        _, days_in_month = _month_bounds(now)
        month_end = now.replace(day=days_in_month).date()
        today = now.date()
        for t in (1, 2, 3):
            if projected_tier < t:
                continue  # the projection arm of _decide_tier's min() blocks this tier outright
            needed = 0.0 if t == 1 else bands[t - 1]
            if mtd >= needed:
                out[str(t)] = today.isoformat()
            elif daily_burn > 0:
                crossing = today + timedelta(days=int((needed - mtd) / daily_burn) + 1)
                if crossing <= month_end:
                    out[str(t)] = crossing.isoformat()
    except Exception:
        return empty
    return out


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


def _read_surge_active() -> bool:
    """Previously-persisted surge state, for edge-triggered alerting (ADR-133).
    Fails closed to False — a transient SSM read error never fabricates a
    surge→normal transition alert that didn't happen."""
    try:
        return _ssm.get_parameter(Name=SSM_SURGE_PARAM)["Parameter"]["Value"] == "true"
    except _ssm.exceptions.ParameterNotFound:
        return False
    except Exception as e:
        logger.warning(f"Surge-state SSM read failed: {e}")
        return False


def _write_surge_active(active: bool) -> None:
    _ssm.put_parameter(Name=SSM_SURGE_PARAM, Value="true" if active else "false", Type="String", Overwrite=True)


def _write_breakdown(
    tier: int,
    mtd: float,
    projected: float,
    ai_daily: float,
    non_ai_daily: float,
    now: datetime,
    ceiling: float = None,
    surge_active: bool = False,
    recent_uniques=None,
) -> None:
    """Persist the projection breakdown alongside the tier (#822).

    Every field is code-derived from this same run's estimate (no user input,
    no LLM). Written as a plain JSON string — this parameter is a display
    artifact only, never read by budget_guard.allow()/current_tier() (the tier
    param remains the sole gating input), so a malformed or stale breakdown
    can never affect AI enforcement — only the brief's headroom line degrades.

    `ceiling`/`surge_active`/`recent_uniques` reflect the surge-mode ceiling
    rule (ADR-133, #739) — `ceiling` is the EFFECTIVE ceiling this run used
    (may be SURGE_CEILING_USD), so the brief's headroom line is always honest
    about what limit is actually in effect.

    `base_ceiling`/`surge_ceiling`/`ceiling_window` (#1999) are the ADR-133
    ENVELOPE the effective ceiling was drawn from. Without them the payload
    stated a single number and left every consumer to hardcode the base
    literal — which is how a raised July base reached the public receipt as an
    unexplained ceiling delta with `surge_active: false`. Publishing the pair
    plus the window descriptor makes the receipt self-explaining, and demotes
    each consumer's literal to a fail-closed fallback for the window between a
    ceiling change and the governor's next 8h run.
    """
    if ceiling is None:
        ceiling = MONTHLY_CEILING
    base_ceiling, surge_ceiling = _active_ceilings()
    payload = {
        "tier": int(tier),
        "mtd": round(mtd, 2),
        "projected": round(projected, 2),
        "ceiling": ceiling,
        "ai_daily": round(ai_daily, 2),
        "non_ai_daily": round(non_ai_daily, 2),
        "computed_at": now.isoformat(),
        "surge_active": bool(surge_active),
        "recent_uniques": recent_uniques,
        "surge_threshold": SURGE_UNIQUES_THRESHOLD,
        "base_ceiling": base_ceiling,
        # Floored at the base exactly as _effective_ceiling() floors it, so the
        # payload can never advertise a surge ceiling BELOW the base — a pair the
        # enforcement path would never actually use.
        "surge_ceiling": max(surge_ceiling, base_ceiling),
        # None when no dated window is in effect (the normal case) — the key is
        # always present so a consumer distinguishes "no window" from "old payload".
        "ceiling_window": _active_ceiling_window(),
        # #2381: projected in-force date per tier band at this run's actual mtd
        # and run-rate, so the brief can say WHEN the next pause arrives, not
        # just that headroom is thin. Derivation in _tier_crossing_forecast.
        "tier_crossings": _tier_crossing_forecast(mtd, projected, ai_daily + non_ai_daily, now, ceiling),
    }
    try:
        _ssm.put_parameter(Name=SSM_BREAKDOWN_PARAM, Value=json.dumps(payload), Type="String", Overwrite=True)
    except Exception as e:
        # Display-only artifact — never let a breakdown-write failure affect
        # the tier decision above it (which has already been written by now).
        logger.warning(f"Breakdown SSM write failed (non-fatal, display-only): {e}")


# Tier-change alert copy. These MUST mirror budget_guard._FEATURE_CUTOFF's
# audience bands (ADR-125): a label that names the wrong pause misinforms the
# on-call about what actually degraded. tests/test_budget_guard_ladder.py derives
# the expected band per tier from _FEATURE_CUTOFF and asserts each label matches.
_TIER_LABELS = {
    0: "Normal — all AI features active",
    1: "Caution — internal/dev AI paused (ensemble, chronicle editor, coherence-semantic)",
    2: "Restrict — + reader narratives paused (coach commentary, State of Matthew, chronicle)",
    3: (
        "Hard stop — + ask endpoints (/api/ask, /api/board_ask), daily-brief AI, and the two AI CI gates "
        "(reader-truth, visual-vision) paused; brief is data-only"
    ),
}


def _alert(prev: int, new: int, mtd: float, projected: float, ceiling: float = None) -> None:
    if ceiling is None:
        ceiling = MONTHLY_CEILING
    direction = "raised" if new > prev else "lowered"
    urgent = new >= 3
    subj = f"{'🛑' if urgent else '⚠️'} Budget tier {direction} {prev}→{new}: {_TIER_LABELS[new]}"
    body = (
        f"Budget tier {direction}: {prev} → {new}\n\n"
        f"{_TIER_LABELS[new]}\n\n"
        f"Month-to-date estimated total: ${mtd:.2f}\n"
        f"Projected month-end:           ${projected:.2f}\n"
        f"Ceiling:                       ${ceiling:.0f}\n\n"
        f"Auto-resumes at month rollover. AI = Bedrock (per-model token metrics "
        f"× price, +{int((_AI_SAFETY_BUFFER - 1) * 100)}% buffer); non-AI = Cost Explorer."
    )
    try:
        _sns.publish(TopicArn=ALERTS_TOPIC, Subject=subj[:99], Message=body)
        logger.info(f"Tier-change alert sent: {prev}→{new}")
    except Exception as e:
        logger.warning(f"SNS publish failed: {e}")


def _alert_surge(active: bool, recent_uniques, mtd: float, projected: float) -> None:
    """Edge-triggered alert when surge mode engages or disengages (#739 scope
    item 2: "alert Matthew when surge mode engages"). Reuses the same alerts
    topic as the tier-change alert.

    Dollar figures are formatted from `_active_ceilings()` — the base/surge
    pair actually in effect today — not from the bare MONTHLY_CEILING/
    SURGE_CEILING_USD module constants. Those constants are the OUT-OF-WINDOW
    default; during a dated temp-ceiling window (_TEMP_CEILING_WINDOW) the
    real enforcement math floats to a different pair, and an alert that still
    quotes the module constants would email the wrong dollars for the
    duration of the window (#1998).
    """
    base, surge = _active_ceilings()
    if active:
        subj = f"🚀 Surge mode ENGAGED — ceiling ${base:.0f} → ${surge:.0f}"
        body = (
            f"Trailing 7-day unique visitors ({recent_uniques}) crossed the surge "
            f"threshold ({SURGE_UNIQUES_THRESHOLD}).\n\n"
            f"Effective monthly ceiling floated: ${base:.0f} → ${surge:.0f} (ADR-133).\n"
            f"Month-to-date estimated total: ${mtd:.2f}\n"
            f"Projected month-end:           ${projected:.2f}\n\n"
            f"This is reader traffic, not spend creep — the extra headroom exists "
            f"specifically so the reader-facing AI doesn't outage at the moment of "
            f"success. Auto-reverts to ${base:.0f} when uniques drop back "
            f"below the threshold."
        )
    else:
        subj = f"Surge mode ended — ceiling back to ${base:.0f}"
        body = (
            f"Trailing 7-day unique visitors ({recent_uniques}) dropped back below "
            f"the surge threshold ({SURGE_UNIQUES_THRESHOLD}).\n\n"
            f"Effective monthly ceiling reverted: ${surge:.0f} → ${base:.0f}."
        )
    try:
        _sns.publish(TopicArn=ALERTS_TOPIC, Subject=subj[:99], Message=body)
        logger.info(f"Surge-mode alert sent: active={active}")
    except Exception as e:
        logger.warning(f"Surge alert SNS publish failed: {e}")


def _recent_unique_visitors(now: datetime, lookback_days: int = 14):
    """Latest LifePlatform/Traffic::UniqueVisitors7d datapoint, or None.

    traffic_digest_lambda emits this weekly (Mondays), so the lookback window
    is wider than the metric's cadence to tolerate a missed run. Returns None
    (not 0) when nothing has been emitted yet — _effective_ceiling treats
    None as "no signal, stay at the normal ceiling", never as "0 traffic."
    """
    try:
        resp = _cw.get_metric_statistics(
            Namespace="LifePlatform/Traffic",
            MetricName="UniqueVisitors7d",
            StartTime=now - timedelta(days=lookback_days),
            EndTime=now,
            Period=86400,
            Statistics=["Maximum"],
        )
        points = resp.get("Datapoints", [])
        if not points:
            return None
        latest = max(points, key=lambda d: d["Timestamp"])
        return int(latest["Maximum"])
    except Exception as e:
        logger.warning(f"traffic metric read failed (non-critical, fails closed to non-surge): {e}")
        return None


def _self_reported_cost_mtd(start: datetime, now: datetime) -> float:
    """Sum LifePlatform/AI::EstimatedCostUSD over [start, now). This is the
    self-emitted metric from bedrock_client._emit_usage_metrics() — it under-counts
    because it only fires for calls with EMF instrumentation (misses dev sessions,
    MCP direct calls, etc.). Used only to compute the drift ratio vs the authoritative
    AWS/Bedrock-derived estimate; never used for tier decisions."""
    try:
        resp = _cw.get_metric_statistics(
            Namespace="LifePlatform/AI",
            MetricName="EstimatedCostUSD",
            StartTime=start,
            EndTime=now,
            Period=2678400,
            Statistics=["Sum"],
        )
        return sum(d["Sum"] for d in resp.get("Datapoints", []))
    except Exception as e:
        logger.debug(f"self-reported cost query failed (non-critical): {e}")
        return 0.0


def _emit_metrics(mtd: float, projected: float, tier: int, self_reported_mtd: float) -> None:
    data = [
        {"MetricName": "EstimatedMonthToDateSpend", "Value": mtd, "Unit": "None"},
        {"MetricName": "ProjectedMonthlySpend", "Value": projected, "Unit": "None"},
        {"MetricName": "BudgetTier", "Value": tier, "Unit": "None"},
        # AuthoritativeCostMTD = the governor's own accurate AI estimate (AWS/Bedrock
        # token metrics × prices) + non-AI (Cost Explorer). Allows dashboards to compare
        # against the self-reported LifePlatform/AI::EstimatedCostUSD metric, which only
        # counts calls made through bedrock_client._emit_usage_metrics() and therefore
        # under-counts (dev sessions, MCP calls without EMF instrumentation, etc.).
        {"MetricName": "AuthoritativeCostMTD", "Value": mtd, "Unit": "None"},
    ]
    # Drift metric: how much larger the authoritative estimate is vs self-reported.
    # Values > 1.5 (50% gap) indicate significant under-counting in self-emitted metrics.
    if self_reported_mtd > 0:
        drift_ratio = mtd / self_reported_mtd
        data.append({"MetricName": "CostMetricDriftRatio", "Value": drift_ratio, "Unit": "None"})
        if drift_ratio > 1.5:
            logger.warning(
                f"CostMetricDrift: authoritative ${mtd:.2f} vs self-reported ${self_reported_mtd:.2f} "
                f"= {drift_ratio:.2f}x — self-emitted metrics are significantly under-counting"
            )
    try:
        _cw.put_metric_data(Namespace="LifePlatform/Budget", MetricData=data)
    except Exception as e:
        logger.warning(f"PutMetricData failed: {e}")


def _emit_token_alarm_window_gauge() -> None:
    """#2116: publish whether TODAY falls inside the stamped genesis rebuild
    window (`common/token_alarm_window.py`) as a periodic 1/0 gauge. This is
    the "periodic gauge metric... from existing machinery, no new cron" the
    story's acceptance criteria call for — this Lambda already runs every 8h.

    `cdk/stacks/monitoring_stack.py`'s composite alarm reads this gauge (via a
    sub-alarm on it) to decide whether the raw `ai-tokens-platform-daily-total`
    threshold breach should route to the urgent topic or the digest topic —
    closing the residual #1961 gap the raw CloudWatch alarm's SNS action had
    (it kept paging on a predicted spike even after #2114 fixed the automated-
    triage path). Namespace/metric match the alarm's own `LifePlatform/AI`
    namespace so they read as one family in the console.

    Never raises: a PutMetricData failure here must not fail the governor's
    real job (budget-tier enforcement). A missing/stale gauge fails safe on
    the ALARM side (NOT_BREACHING => "assume not in window" => the raw breach
    still pages) — see monitoring_stack.py's comment at the gauge alarm.
    """
    try:
        active = 1 if is_within_token_alarm_window() else 0
        _cw.put_metric_data(
            Namespace="LifePlatform/AI",
            MetricData=[{"MetricName": "TokenAlarmGenesisWindowActive", "Value": active, "Unit": "None"}],
        )
    except Exception as e:
        logger.warning(f"PutMetricData (TokenAlarmGenesisWindowActive) failed: {e}")


def lambda_handler(event, context):
    try:
        now = datetime.now(timezone.utc)
        month_start, days_in_month = _month_bounds(now)
        elapsed_days = max((now - month_start).total_seconds() / 86400.0, 0.5)

        non_ai_series = _non_ai_daily_series(month_start, now)
        non_ai = sum(c for _, c in non_ai_series)
        ai = _ai_cost(month_start, now)
        mtd = non_ai + ai

        # Month-end = what's ALREADY spent (mtd, captured precisely) + the daily
        # run-rate × days REMAINING. BOTH AI and non-AI rates use a TRAILING 7-day
        # window — the MTD average over-projects (lumpy one-time AI; day-1 monthly
        # fixed charges already banked in mtd). See _project_month_end. The window
        # is clamped to month_start so early in the month it degrades to MTD.
        trailing_start = max(now - timedelta(days=7), month_start)
        trailing_days = max((now - trailing_start).total_seconds() / 86400.0, 0.5)
        trailing_start_str = trailing_start.strftime("%Y-%m-%d")
        non_ai_recent = sum(c for d, c in non_ai_series if d >= trailing_start_str)
        ai_recent = _ai_cost(trailing_start, now)
        ai_daily = ai_recent / trailing_days
        non_ai_daily = non_ai_recent / trailing_days
        projected = _project_month_end(mtd, elapsed_days, days_in_month, non_ai_recent, ai_recent, trailing_days)

        # ADR-133 (#739): surge-mode ceiling. Pure function of reader traffic
        # (trailing 7d uniques) — never of spend — so it floats the ceiling up
        # for readers arriving but can't be triggered by a dev/internal spend
        # spike. Computed BEFORE _decide_tier so the effective ceiling — not
        # always MONTHLY_CEILING — is what tiers are measured against.
        recent_uniques = _recent_unique_visitors(now)
        effective_ceiling, surge_active = _effective_ceiling(recent_uniques)

        # Projection escalates at most ONE tier above actual mtd spend (and not at
        # all in the early-month window) — see _decide_tier for the two failure
        # modes (front-loaded day-1 charges; post-pause projection that can't decay).
        computed_tier = _decide_tier(projected, mtd, elapsed_days, effective_ceiling)
        prev = _read_tier()

        self_reported = _self_reported_cost_mtd(month_start, now)
        logger.info(
            f"Spend: non_ai=${non_ai:.2f} ai=${ai:.2f} (trailing_7d over {trailing_days:.1f}d: "
            f"non_ai ~${non_ai_daily:.2f}/day + ai ~${ai_daily:.2f}/day) mtd=${mtd:.2f} projected=${projected:.2f} "
            f"computed_tier={computed_tier} prev={prev} observe={OBSERVE_MODE} "
            f"self_reported_mtd=${self_reported:.2f} recent_uniques={recent_uniques} "
            f"surge_active={surge_active} effective_ceiling=${effective_ceiling:.0f}"
        )
        _emit_metrics(mtd, projected, computed_tier, self_reported)
        # #2116: independent of OBSERVE_MODE/budget-tier enforcement — the
        # genesis-window gauge is a pure calendar fact, not a spend decision.
        _emit_token_alarm_window_gauge()

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
                        "non_ai_per_day": round(non_ai_daily, 2),
                        "mtd_total": round(mtd, 2),
                        "projected": round(projected, 2),
                        "computed_tier": computed_tier,
                        "active_tier": prev,
                        "ceiling": effective_ceiling,
                        "surge_active": surge_active,
                        "recent_uniques": recent_uniques,
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
            _alert(prev, tier, mtd, projected, effective_ceiling)

        # Edge-triggered surge alert (#739 scope item 2) — fires only on the
        # engage/disengage transition, not every run, same pattern as the tier
        # alert above.
        prev_surge_active = _read_surge_active()
        if surge_active != prev_surge_active:
            _write_surge_active(surge_active)
            _alert_surge(surge_active, recent_uniques, mtd, projected)

        # #822: persist the projection breakdown EVERY enforcement run (not just
        # on tier change) so the daily brief's headroom line reads THIS run's
        # burn rates, not the ones from whenever the tier last flipped. Now also
        # carries the surge state (ADR-133) so the headroom line is honest about
        # which ceiling is actually in effect.
        _write_breakdown(tier, mtd, projected, ai_daily, non_ai_daily, now, effective_ceiling, surge_active, recent_uniques)

        return {
            "statusCode": 200,
            "body": json.dumps(
                {
                    "non_ai_mtd": round(non_ai, 2),
                    "ai_mtd": round(ai, 2),
                    "ai_per_day": round(ai_daily, 2),
                    "non_ai_per_day": round(non_ai_daily, 2),
                    "mtd_total": round(mtd, 2),
                    "projected": round(projected, 2),
                    "tier": tier,
                    "prev_tier": prev,
                    "ceiling": effective_ceiling,
                    "surge_active": surge_active,
                    "recent_uniques": recent_uniques,
                }
            ),
        }
    except Exception as e:
        logger.error("cost_governor failed: %s", e, exc_info=True)
        raise
