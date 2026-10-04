"""narrative_cadence.py — the long per-coach narratives are written twice a week (#4589).

THE DECISION
  The owner-approved platform plan (2026-10-03, decision 4) cut "long daily coach
  narratives" to twice a week. Those are the seven 300-450-word per-coach reads the daily
  brief writes through the Coach Intelligence pipeline (`ai_calls._run_coach_v2_pipeline`:
  computation engine -> coach-narrative-orchestrator (Haiku) -> Sonnet generation ->
  coach-quality-gate -> coach-state-updater), plus the coach-ensemble-digest fan-out that
  summarises them. Measured cost, 2026-09-04..10-03 (`LifePlatform/AI::EstimatedCostUSD`
  by `LambdaFunction`, and the daily-brief's one-minute series split at the
  "Ensemble digest invoked" log line): ~0.54 USD/day inside daily-brief, plus
  orchestrator 0.24, quality gate 0.08, state updater 0.08, ensemble digest 0.06 — about
  1.00 USD/day, ~30 USD/month, the largest recurring AI line after the brief itself.

WHY THIS IS A CODE CADENCE AND NOT A CRON
  The narratives have no schedule of their own: they are a stage inside the daily-brief
  Lambda, whose EventBridge cron (`email_stack.py`, 17:00 UTC) must stay daily — the brief
  is "protect longest" (ADR-125). So the cadence lives here, read by BOTH the producer
  (daily-brief) and every consumer that would otherwise expect a row each day (the
  ENSEMBLE#digest dead-man, the coherence sentinel's freshness floor). One constant, two
  sides — a dead-man that read a different cadence than the producer would page on every
  off day.

THE TWO DAYS — MONDAY AND THURSDAY (Pacific calendar day of the brief run; 17:00 UTC is
10:00 PT, the same calendar day in both frames)
  * Monday opens the week next to Monday's bet and the Monday Panel episode
    (coach-panel-podcast runs MON,WED 18:00 UTC, an hour after the brief), so the episode
    that starts the week reads a same-morning narrative.
  * Thursday is the most even split of the remaining week: the gaps are 3 days
    (Mon -> Thu) and 4 days (Thu -> Mon). The oldest read a reader can meet is 4 days,
    inside the coaching door's 7-day "off the first screen" bound (READ_OFF_FIRST_SCREEN_DAYS
    in site/assets/js/coach_today.js), and every read is already served with its own
    written-day stamp and a ">48 h old" banner.

WHAT AN OFF DAY DOES
  No long narrative is generated and nothing is backfilled; the ensemble digest is not
  fanned out (it summarises the coaches' new outputs; there are none). Nothing is HELD
  either — a hold (#966) means a gate judged a draft unpublishable, and no gate judged
  anything — so the brief's short daily pieces run exactly as on a day the v2 pipeline
  returned nothing: the legacy 2-4-sentence training/nutrition note, the head coach's
  lead read (#4188), the Board of Directors line, the journal coach and the TL;DR.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable, Optional

from common.pacific_time import parse_day_key  # THE calendar-day parse (#3741/#3609)

# date.weekday(): Monday == 0 ... Sunday == 6.
NARRATIVE_WEEKDAYS = (0, 3)  # Monday, Thursday
_WEEKDAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")

# What `fan_out_ensemble` reports when an off day skipped the fan-out.
OFF_CADENCE_REASON = "off_cadence"


def _as_date(day) -> date:
    if isinstance(day, date):
        return day
    parsed = parse_day_key(str(day)[:10])
    if parsed is None:
        raise ValueError(f"not a YYYY-MM-DD day: {day!r}")
    return parsed


def is_narrative_day(day) -> bool:
    """True when the long per-coach narratives are written on `day` (YYYY-MM-DD or date)."""
    return _as_date(day).weekday() in NARRATIVE_WEEKDAYS


def last_narrative_day(day) -> date:
    """The most recent narrative day on or before `day`."""
    d = _as_date(day)
    for back in range(7):
        cand = d - timedelta(days=back)
        if cand.weekday() in NARRATIVE_WEEKDAYS:
            return cand
    raise ValueError("NARRATIVE_WEEKDAYS is empty")


def next_narrative_day(day) -> date:
    """The first narrative day strictly after `day`."""
    d = _as_date(day)
    for ahead in range(1, 8):
        cand = d + timedelta(days=ahead)
        if cand.weekday() in NARRATIVE_WEEKDAYS:
            return cand
    raise ValueError("NARRATIVE_WEEKDAYS is empty")


def max_gap_days() -> int:
    """The longest a written narrative can be the newest one (4 for Monday/Thursday)."""
    days = sorted(set(NARRATIVE_WEEKDAYS))
    if not days:
        raise ValueError("NARRATIVE_WEEKDAYS is empty")
    gaps = [(days[(i + 1) % len(days)] - days[i]) % 7 or 7 for i in range(len(days))]
    return max(gaps)


def describe() -> str:
    """'Monday and Thursday' — the cadence in words, for logs and reader copy."""
    names = [_WEEKDAY_NAMES[i] for i in sorted(set(NARRATIVE_WEEKDAYS))]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def skip_line(day) -> str:
    """The one log line an off day writes — names the cadence, the last and next run."""
    d = _as_date(day)
    return (
        f"[coach-cadence] {d.isoformat()} ({_WEEKDAY_NAMES[d.weekday()]}) is not a narrative day — the long per-coach "
        f"narratives are written {describe()} (#4589). Last written {last_narrative_day(d).isoformat()}, next "
        f"{next_narrative_day(d).isoformat()}. No orchestrator/Sonnet/quality-gate call and no ensemble fan-out today; "
        "the short daily pieces (training/nutrition note, lead read, BoD, journal, TL;DR) run as usual."
    )


def plan(day, roster: Iterable[tuple]) -> tuple:
    """(roster_to_run, held_domains) for the brief's v2 loop on `day`.

    On a narrative day the whole roster runs; on an off day nothing does. `held_domains`
    starts empty either way — the loop adds a domain only when a gate actually holds its
    draft (#966). An off day is not a hold: no gate judged anything.
    """
    roster = list(roster)
    return (roster if is_narrative_day(day) else []), set()


def fan_out_ensemble(lambda_client_factory, persist: bool, day: str, ran_roster: bool, logger) -> Optional[str]:
    """The async coach-ensemble-digest kick-off, gated on persist (#2255) and cadence.

    Returns what happened ("dry_run" | "off_cadence" | "invoked" | "failed") so a test can
    read the decision without a log scrape. Never raises — the fan-out is non-blocking.
    """
    if not persist:
        logger.info("[DRY_RUN] skipping the async coach-ensemble-digest invoke")
        return "dry_run"
    if not ran_roster:
        logger.info(f"[coach-cadence] ensemble digest not fanned out on {day}: no coach narratives were written today (#4589)")
        return OFF_CADENCE_REASON
    try:
        import json

        lambda_client_factory("lambda", region_name="us-west-2").invoke(
            FunctionName="coach-ensemble-digest",
            InvocationType="Event",
            Payload=json.dumps({"cycle_date": day}).encode(),
        )
        logger.info("Ensemble digest invoked (async)")
        return "invoked"
    except Exception as e:  # noqa: BLE001 — non-blocking by design
        logger.warning(f"Ensemble digest invoke failed (non-blocking): {e}")
        return "failed"
