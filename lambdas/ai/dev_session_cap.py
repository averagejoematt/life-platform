"""ai/dev_session_cap.py — the spend cap on AI calls made from a laptop (#4589), and the
monthly dev-session envelope around it (#5135).

WHY
  On 2026-10-01 and 2026-10-02 two Story Desk season rebuilds and a fix run, all on
  Sonnet, spent about $29 from a dev session in two days — a seventh of the month's
  ceiling — and nothing stopped them. The cost governor's tiers gate the scheduled
  platform by audience (ADR-125) and deliberately leave dev-session spend out of the
  month-end projection, so the only thing that noticed was the bill. #4589 added the
  per-run and per-day limits below.

  On 2026-10-18 dev sessions metered $27.37 in one UTC day with those limits live
  (#5135). Nothing failed: the season re-stage ran under `DEV_AI_BUDGET_USD=20`, the
  repair passes after it ran under named numbers too, and as written a named number
  switched the 24-hour check off for its run. Each run was inside its own cap; nothing
  bounded their sum. The fixes are (a) a named number now bounds the 24-hour total
  instead of switching it off, (b) a calendar-month envelope that no env var lifts, and
  (c) the window is re-read during a long run, so concurrent sessions see each other.
  `tests/test_dev_session_envelope_5135.py` replays the 10-18 traffic against it.

THE CLASS THIS GOVERNS
  `dev-session` is defined in ONE place, `ai.bedrock_client.caller_class()`: a call that
  is not in a Lambda container and carries no GitHub Actions marker (a laptop, an agent
  lane, a scratch script), plus any Lambda container that declares itself a dev context
  (`INVOCATION_CONTEXT=dev`, today only the MCP Lambda). Its spend is metered on
  `LifePlatform/AI` `EstimatedCostUSD` with `CallerClass=dev-session`.

COVERAGE — what is refused here, and what is only counted
  REFUSED   every dev-session call outside a Lambda container: laptop scripts, agent
            lanes, Bedrock batch jobs submitted from a laptop (`check_projected`).
  COUNTED   the MCP Lambda's dev-session calls count toward the day and month totals
            (they are on the same series) but are never refused here: it is
            production traffic in a container, and refusing it would pause the
            owner's own tool mid-conversation. Measured on 10-18: $0.02 of the $27.37.
  NEVER     CI, the remediation agent and the scheduled platform (other classes), and
            any test run (the cap is off under pytest unless a test opts in).

WHAT IT DOES
  For a refused-class call the Bedrock chokepoint asks this module before it sends:

    PER RUN    the estimated cost of this process's own calls. Past `PER_RUN_USD`
               (or the named number) the next call is refused.
    PER DAY    dev-session spend in the trailing 24 hours, this run included. Past
               `PER_DAY_USD` — or past the named number, if that is higher — the next
               call is refused. A trailing window, not a calendar day: the October
               spikes straddled midnight UTC.
    PER MONTH  dev-session spend in the current UTC calendar month, this run included.
               Past `PER_MONTH_USD` the next call is refused, named number or not.
               The owner set it on 2026-10-26: $60 a month, separate from the
               production ceiling (ADR-063/133 unchanged). `MONTH_ALARM_FRACTION` of it
               is the `ai-dev-session-month-high` alarm, fed by the cost governor's
               `LifePlatform/Budget` `DevSessionSpendMTD` gauge.

  The day and month figures are read from the metric the chokepoint itself writes, at
  the first governed call and again every `REFRESH_SECONDS`, so two lanes running at
  once each see what the other has spent within a few minutes.

  A refusal is `DevSessionBudgetExceeded`, a `BudgetExceeded`, so both retry wrappers
  return at once instead of backing off, and it is printed to stderr once with what was
  spent and what would raise the limit — a script that catches the budget stop and
  degrades must not do so silently.

THE OVERRIDE
  `DEV_AI_BUDGET_USD=<dollars>` on the command is consent for that run: the run may
  spend that much, and dev sessions together may have spent that much in the trailing
  24 hours once the run is counted. It is a ceiling on the total, not an allowance on
  top of it, so a second run naming the same number after the first has spent it is
  refused at its first call. It never raises the monthly envelope: that is the owner's
  number, and changing it is a change to `PER_MONTH_USD`. There is no way to switch the
  cap off except by naming a number.

LIMITS
  The dollars are this module's own estimate (`bedrock_client.estimate_cost_usd`), which
  runs below the bill. CloudWatch shows a datapoint a minute or two after it is written,
  so another session's last minutes may be missing from a read. If the FIRST read fails,
  the per-run cap still applies and the failure is printed; if a later re-read fails, the
  last good figures are kept. Under pytest the cap is off unless a test opts in, so a
  laptop test run and CI behave the same.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping, Optional

from ai.budget_guard import BudgetExceeded

PER_RUN_USD = 5.0
PER_DAY_USD = 10.0
# Owner ruling 2026-10-26 (#5135): "$60/month, alarm at 80%". Read by
# scripts/budget_ceilings.py for the alarm, so it stays a bare literal.
PER_MONTH_USD = 60.0
MONTH_ALARM_FRACTION = 0.8
DAY_WINDOW_HOURS = 24
REFRESH_SECONDS = 300
OVERRIDE_ENV = "DEV_AI_BUDGET_USD"

_NAMESPACE = "LifePlatform/AI"
_METRIC = "EstimatedCostUSD"
_CLASS_DIMENSION = "CallerClass"
_DEV_SESSION = "dev-session"
_MONTH_MARK = "this calendar month"

_lock = threading.Lock()
_run_spent = 0.0
_day_read: Optional[float] = None  # trailing-24h dev-session spend at the last read
_month_read: Optional[float] = None  # month-to-date dev-session spend at the last read
_run_spent_at_read = 0.0  # this run's own spend when that read was taken
_read_at: Optional[float] = None  # time.monotonic() of the last read attempt
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


def decide(run_spent: float, day_before_run: float, override: Optional[float], month_before_run: float = 0.0) -> Optional[str]:
    """Pure. The refusal sentence, or None when the next call may go.

    `day_before_run` / `month_before_run` are what OTHER dev-session spend the window
    holds; this run's own `run_spent` is added here. The month is checked first and no
    override reaches it (#5135).
    """
    month = month_before_run + run_spent
    if month >= PER_MONTH_USD:
        return (
            f"dev sessions have spent about ${month:.2f} {_MONTH_MARK} (UTC; ${run_spent:.2f} of it in this run); "
            f"the monthly envelope is ${PER_MONTH_USD:.2f} and {OVERRIDE_ENV} does not raise it."
        )
    day = day_before_run + run_spent
    if override is not None:
        if run_spent >= override:
            return f"this run has spent about ${run_spent:.2f} of the ${override:.2f} set by {OVERRIDE_ENV}."
        day_limit = max(PER_DAY_USD, override)
        if day >= day_limit:
            return (
                f"dev sessions have spent about ${day:.2f} in the last {DAY_WINDOW_HOURS} hours (${run_spent:.2f} of it in this run); "
                f"{OVERRIDE_ENV}={override:g} lets that total reach ${day_limit:.2f}, it does not add to it."
            )
        return None
    if run_spent >= PER_RUN_USD:
        return f"this run has spent about ${run_spent:.2f}; the per-run limit is ${PER_RUN_USD:.2f}."
    if day >= PER_DAY_USD:
        return f"dev sessions have spent about ${day:.2f} in the last {DAY_WINDOW_HOURS} hours (${run_spent:.2f} of it in this run); the limit is ${PER_DAY_USD:.2f}."
    return None


def _sum_dev_session(cloudwatch: Any, start: datetime, end: datetime) -> float:
    if end - start < timedelta(minutes=1):
        return 0.0
    resp = cloudwatch.get_metric_statistics(
        Namespace=_NAMESPACE,
        MetricName=_METRIC,
        Dimensions=[{"Name": _CLASS_DIMENSION, "Value": _DEV_SESSION}],
        StartTime=start,
        EndTime=end,
        Period=3600,
        Statistics=["Sum"],
    )
    return float(sum(float(p.get("Sum") or 0.0) for p in resp.get("Datapoints") or []))


def read_day_spend(cloudwatch: Any, now: Optional[datetime] = None) -> float:
    """What dev sessions spent in the trailing window, from the metric the chokepoint
    itself writes. Raises on any failure — the caller decides what a failed read means."""
    now = now or datetime.now(timezone.utc)
    return _sum_dev_session(cloudwatch, now - timedelta(hours=DAY_WINDOW_HOURS), now)


def month_start(now: datetime) -> datetime:
    """00:00 UTC on the first of `now`'s month — the same month the cost governor uses."""
    return now.astimezone(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def read_month_spend(cloudwatch: Any, now: Optional[datetime] = None) -> float:
    """What dev sessions spent so far this UTC calendar month (hourly sums; at most 744
    datapoints, inside one GetMetricStatistics page). Raises on any failure."""
    now = now or datetime.now(timezone.utc)
    return _sum_dev_session(cloudwatch, month_start(now), now)


def _refresh(cloudwatch_factory: Callable[[], Any]) -> None:
    """Re-read the day and month totals when due. Called with `_lock` held."""
    global _day_read, _month_read, _run_spent_at_read, _read_at
    now_mono = time.monotonic()
    if _read_at is not None and now_mono - _read_at < REFRESH_SECONDS:
        return
    first = _read_at is None
    _read_at = now_mono
    try:
        cw = cloudwatch_factory()
        day, month = read_day_spend(cw), read_month_spend(cw)
    except Exception as e:  # noqa: BLE001 — a failed read leaves the per-run cap in force
        if first:
            _day_read, _month_read, _run_spent_at_read = 0.0, 0.0, _run_spent
            print(
                f"[dev-session cap] could not read dev-session spend for the last {DAY_WINDOW_HOURS} hours or this month "
                f"({type(e).__name__}); only the ${PER_RUN_USD:.2f} per-run limit applies.",
                file=sys.stderr,
            )
        return  # a later failure keeps the last good figures
    _day_read, _month_read, _run_spent_at_read = day, month, _run_spent


def _others() -> tuple[float, float]:
    """(day, month) spend that is not this run's, as of the last read. The read already
    holds this run's spend up to that moment, so that part is taken back out; never below 0."""
    return max(0.0, (_day_read or 0.0) - _run_spent_at_read), max(0.0, (_month_read or 0.0) - _run_spent_at_read)


def _advice(reason: str) -> str:
    if _MONTH_MARK in reason:
        return "The monthly envelope is the owner's number (#5135); raising it is a change to PER_MONTH_USD in ai/dev_session_cap.py."
    return f"To spend more on purpose, re-run with {OVERRIDE_ENV}=<dollars>."


def check(caller_class: str, cloudwatch_factory: Callable[[], Any]) -> None:
    """Called by the chokepoint before a send. Raises `DevSessionBudgetExceeded`, or returns."""
    global _announced
    if not applies(caller_class):
        return
    override = run_override()
    with _lock:
        _refresh(cloudwatch_factory)
        day_others, month_others = _others()
        reason = decide(_run_spent, day_others, override, month_others)
        if reason is None:
            return
        first = not _announced
        _announced = True
    message = f"AI call refused — {reason} {_advice(reason)} Nothing was sent or billed for this call."
    if first:
        print(f"[dev-session cap] {message}", file=sys.stderr)
    raise DevSessionBudgetExceeded(message)


def check_projected(caller_class: str, projected_usd: float, cloudwatch_factory: Callable[[], Any]) -> None:
    """Refuse a send whose PROJECTED cost would carry this run past its cap (#4777).

    A Bedrock batch job is one submission that bills 100+ records at once, so the
    per-call `check` (which only asks whether the run is ALREADY over) would let a
    single job overshoot the cap by its whole size. This asks the same question with
    the job's upper-bound estimate added to the run's spend. Raises
    `DevSessionBudgetExceeded`, or returns; the same applies/override rules as `check`.
    """
    check(caller_class, cloudwatch_factory)  # already over → refuse; also takes the window read
    if not applies(caller_class):
        return
    override = run_override()
    with _lock:
        day_others, month_others = _others()
        reason = decide(_run_spent + max(0.0, float(projected_usd)), day_others, override, month_others)
    if reason is None:
        return
    message = f"batch job refused — its projected cost (about ${projected_usd:.2f}) would cross the cap: {reason} {_advice(reason)} Nothing was sent or billed."
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
    global _run_spent, _day_read, _month_read, _run_spent_at_read, _read_at, _announced
    with _lock:
        _run_spent, _day_read, _month_read, _run_spent_at_read, _read_at, _announced = 0.0, None, None, 0.0, None, False
