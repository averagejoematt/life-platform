"""ai/dev_session_cap.py — a spend cap on AI calls made from a laptop (#4589).

WHY
  On 2026-10-01 and 2026-10-02 two Story Desk season rebuilds and a fix run, all on
  Sonnet, spent about $29 from a dev session in two days — a seventh of the month's
  ceiling — and nothing stopped them. The cost governor's tiers gate the scheduled
  platform by audience (ADR-125) and deliberately leave dev-session spend out of the
  month-end projection, so the only thing that noticed was the bill.

WHAT IT DOES
  For a call classed `dev-session` and NOT running inside a Lambda container, the
  Bedrock chokepoint asks this module before it sends anything:

    PER RUN   the estimated cost of this process's own calls so far. Past
              `PER_RUN_USD` the next call is refused.
    PER DAY   what dev sessions spent in the trailing 24 hours (one read of the
              `LifePlatform/AI` `EstimatedCostUSD` series, `CallerClass=dev-session`,
              taken once at the first call) plus this run. Past `PER_DAY_USD` the
              next call is refused. A trailing window, not a calendar day: the October
              spike straddled midnight UTC.

  A refusal is `DevSessionBudgetExceeded`, a `BudgetExceeded`, so both retry wrappers
  return at once instead of backing off, and it is printed to stderr once with what was
  spent and how to raise the limit — a script that catches the budget stop and degrades
  must not do so silently.

THE OVERRIDE
  `DEV_AI_BUDGET_USD=<dollars>` on the command sets this run's cap. It is consent for
  that run, so the per-day check is not applied on top of it. There is no way to switch
  the cap off except by naming a number.

WHAT IT NEVER TOUCHES
  A Lambda container (the MCP Lambda self-declares a dev context and is still production
  traffic), CI, the remediation agent, and the scheduled platform. Nothing a reader sees
  can be paused here.

LIMITS
  The dollars are this module's own estimate (`bedrock_client.estimate_cost_usd`), which
  runs below the bill, so the defaults are set conservatively. If the day read fails the
  per-run cap still applies and the failure is printed. Under pytest the cap is off
  unless a test opts in, so a laptop test run and CI behave the same.
"""

from __future__ import annotations

import os
import sys
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping, Optional

from ai.budget_guard import BudgetExceeded

PER_RUN_USD = 5.0
PER_DAY_USD = 10.0
DAY_WINDOW_HOURS = 24
OVERRIDE_ENV = "DEV_AI_BUDGET_USD"

_NAMESPACE = "LifePlatform/AI"
_METRIC = "EstimatedCostUSD"
_CLASS_DIMENSION = "CallerClass"
_DEV_SESSION = "dev-session"

_lock = threading.Lock()
_run_spent = 0.0
_day_before_run: Optional[float] = None  # read once, at the first governed call
_announced = False


class DevSessionBudgetExceeded(BudgetExceeded):
    """Raised before a Bedrock send when a dev session has reached its cap."""


def applies(caller_class: str, env: Optional[Mapping[str, str]] = None) -> bool:
    """True only for a dev-session call outside a Lambda container and outside pytest."""
    env = os.environ if env is None else env
    if caller_class != _DEV_SESSION:
        return False
    if (env.get("AWS_LAMBDA_FUNCTION_NAME") or "").strip():
        return False
    if env.get("PYTEST_CURRENT_TEST") and not env.get("DEV_AI_CAP_UNDER_TEST"):
        return False
    return True


def run_override(env: Optional[Mapping[str, str]] = None) -> Optional[float]:
    """This run's cap from `DEV_AI_BUDGET_USD`, or None. A value that is not a positive
    number is ignored (and said so), never read as "no cap"."""
    env = os.environ if env is None else env
    raw = (env.get(OVERRIDE_ENV) or "").strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        value = -1.0
    if value <= 0:
        print(
            f"[dev-session cap] {OVERRIDE_ENV}={raw!r} is not a positive number; the default ${PER_RUN_USD:.2f} applies.", file=sys.stderr
        )
        return None
    return value


def decide(run_spent: float, day_before_run: float, override: Optional[float]) -> Optional[str]:
    """Pure. The refusal sentence, or None when the next call may go."""
    if override is not None:
        if run_spent >= override:
            return f"this run has spent about ${run_spent:.2f} of the ${override:.2f} set by {OVERRIDE_ENV}."
        return None
    if run_spent >= PER_RUN_USD:
        return f"this run has spent about ${run_spent:.2f}; the per-run limit is ${PER_RUN_USD:.2f}."
    day = day_before_run + run_spent
    if day >= PER_DAY_USD:
        return f"dev sessions have spent about ${day:.2f} in the last {DAY_WINDOW_HOURS} hours (${run_spent:.2f} of it in this run); the limit is ${PER_DAY_USD:.2f}."
    return None


def read_day_spend(cloudwatch: Any, now: Optional[datetime] = None) -> float:
    """What dev sessions spent in the trailing window, from the metric the chokepoint
    itself writes. Raises on any failure — the caller decides what a failed read means."""
    now = now or datetime.now(timezone.utc)
    resp = cloudwatch.get_metric_statistics(
        Namespace=_NAMESPACE,
        MetricName=_METRIC,
        Dimensions=[{"Name": _CLASS_DIMENSION, "Value": _DEV_SESSION}],
        StartTime=now - timedelta(hours=DAY_WINDOW_HOURS),
        EndTime=now,
        Period=3600,
        Statistics=["Sum"],
    )
    return float(sum(float(p.get("Sum") or 0.0) for p in resp.get("Datapoints") or []))


def check(caller_class: str, cloudwatch_factory: Callable[[], Any]) -> None:
    """Called by the chokepoint before a send. Raises `DevSessionBudgetExceeded`, or returns."""
    global _day_before_run, _announced
    if not applies(caller_class):
        return
    override = run_override()
    with _lock:
        if _day_before_run is None and override is None:
            try:
                _day_before_run = read_day_spend(cloudwatch_factory())
            except Exception as e:  # noqa: BLE001 — a failed read leaves the per-run cap in force
                _day_before_run = 0.0
                print(
                    f"[dev-session cap] could not read the last {DAY_WINDOW_HOURS} hours of dev-session spend ({type(e).__name__}); only the ${PER_RUN_USD:.2f} per-run limit applies.",
                    file=sys.stderr,
                )
        reason = decide(_run_spent, _day_before_run or 0.0, override)
        if reason is None:
            return
        first = not _announced
        _announced = True
    message = f"AI call refused — {reason} To spend more on purpose, re-run with {OVERRIDE_ENV}=<dollars>. Nothing was sent or billed for this call."
    if first:
        print(f"[dev-session cap] {message}", file=sys.stderr)
    raise DevSessionBudgetExceeded(message)


def record(caller_class: str, cost_usd: float) -> None:
    """Called by the chokepoint after a billed send. Never raises."""
    global _run_spent
    try:
        if applies(caller_class) and cost_usd > 0:
            with _lock:
                _run_spent += float(cost_usd)
    except Exception:  # noqa: BLE001 — metering must never break a call that already succeeded
        pass


def _reset_for_tests() -> None:
    global _run_spent, _day_before_run, _announced
    with _lock:
        _run_spent, _day_before_run, _announced = 0.0, None, False
