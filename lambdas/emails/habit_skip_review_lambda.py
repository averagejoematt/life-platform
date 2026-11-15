"""
habit_skip_review_lambda.py — the Saturday skipped-habits queue (#4622).

Owner ruling 2026-10-04: a daily habit has two FINAL states, completed or failed. Habitify
runs an in-app automation that marks anything left unlogged at bedtime as `skipped`, so a
stored `skipped` means "unconfirmed — he forgot to log it", not a decision. Those days are a
queue the owner settles later in Habitify (as passed or failed); the next habitify re-ingest
then carries his answer onto the record (`habitify_lambda.upgrade_only_merge`, #4622).

Nothing surfaced that queue — the owner had to remember to look. This Lambda did, once a
week, by email. #5821 (owner ruling 2026-11-15): "Habits to settle" no longer arrives as its
own email — the Saturday Morning Brief carries the same list as a section, built from the
same `collect_skips` / `render_lines` below (`brief_section`). This Lambda keeps its schedule
and its run record, and sends nothing:

  * Reads the stored habitify records for the previous seven Pacific days (yesterday and
    the six before it — today has not closed) from DynamoDB ONLY. No Habitify API call, no
    Bedrock, no secret.
  * Collects the DAILY habits whose stored status is `skipped`, grouped by date. Weekly /
    monthly habits are excluded: their per-day status is the vendor's PERIOD judgement
    (`habit_statuses[name].periodicity`, written by habitify_lambda since #3666), not a
    day the owner owes an answer for. A row with no periodicity predates that field and is
    treated as daily.
  * Sends NOTHING (#5821). Its role still carries an SES grant; retiring that grant, the
    schedule and the function is a later CDK change (the PR that folded it says so).
  * Records every run, empty or not, as an EMF datapoint (`LifePlatform/Email` ::
    `HabitSkipReviewRun` + `HabitSkipQueueDays` / `HabitSkipQueueHabits`), so a quiet week
    ("nothing skipped") and a dead cron ("never ran") stay distinguishable. The producer
    census (deploy/sentinel_producer_census.py) grades this Lambda's Invocations against its
    weekly cadence — its row in tests/test_heartbeat_completeness.py.

PRIVACY. The repo is public and some habit names are sensitive. Habit names appear ONLY in
the owner-only Morning Brief section; logs and metrics carry counts, never a name.

Schedule: Saturday 09:00 Pacific (config/schedules.json), an hour before the 10:00 brief.
Invoke with {"dry_run": true} to preview: the logs carry the counts, the response payload
(invoker only, never logged) carries the rendered lines.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

import boto3
from common import digest_utils  # the shared paginated, phase-scoped DATE# range read (#970)
from common.habit_pause import is_name_paused_on  # #5007
from common.pacific_time import pacific_today, parse_day_key, shift_day_key
from common.send_guard import is_dry_run  # #2222: the dry-run vocabulary (nothing is sent since #5821)

# OBS-1: structured logger
try:
    from common.platform_logger import get_logger

    logger = get_logger("habit-skip-review")
except ImportError:  # pragma: no cover — bundle-dependent
    logger = logging.getLogger("habit-skip-review")
    logger.setLevel(logging.INFO)

REGION = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
USER_ID = os.environ.get("USER_ID", "matthew")

SOURCE = "habitify"
SATURDAY = 5  # date.weekday(): the brief carries the queue on the day this review runs
WINDOW_DAYS = 7
SKIPPED = "skipped"
DAILY = "daily"

EMF_NAMESPACE = "LifePlatform/Email"
RUN_METRIC = "HabitSkipReviewRun"
DAYS_METRIC = "HabitSkipQueueDays"
HABITS_METRIC = "HabitSkipQueueHabits"

RESOLVE_HINT = (
    "To settle them: mark each one done or missed in Habitify (the next habitify ingest carries the answer), "
    "or paste this list into a Claude session / run /habitify review."
)


def window_dates(today: str | None = None) -> list[str]:
    """The WINDOW_DAYS closed Pacific days before `today`, oldest first."""
    today = today or pacific_today()
    return [shift_day_key(today, -n) for n in range(WINDOW_DAYS, 0, -1)]


def _is_daily(hs: dict) -> bool:
    periodicity = hs.get("periodicity")
    return periodicity in (None, "", DAILY)


def collect_skips(records: dict, dates: list[str], registry: dict | None = None) -> list[tuple[str, list[str]]]:
    """[(date, [habit, ...]), ...] — oldest first, only dates with at least one skip.

    `records` is {date: record} as returned by digest_utils.query_range. #5007: a habit whose
    registry entry is paused on that day is not scheduled, so it is never a skip to settle.
    """
    out = []
    for d in dates:
        rec = records.get(d) or {}
        statuses = rec.get("habit_statuses") or {}
        if not isinstance(statuses, dict):
            continue
        names = sorted(
            name
            for name, hs in statuses.items()
            if isinstance(hs, dict) and hs.get("status") == SKIPPED and _is_daily(hs) and not is_name_paused_on(registry, name, d)
        )
        if names:
            out.append((d, names))
    return out


def day_label(date_str: str) -> str:
    """'Tue 09-29' for a YYYY-MM-DD day key (the key unchanged if it does not parse)."""
    d = parse_day_key(date_str)
    return f"{d.strftime('%a')} {d.strftime('%m-%d')}" if d else date_str


def render_lines(queue: list[tuple[str, list[str]]]) -> list[str]:
    return [f"{day_label(d)}: {', '.join(names)}" for d, names in queue]


def emit_run_metric(days: int, habits: int, sent: bool) -> None:
    """One EMF line per run — the 'it ran' record, empty week included. Counts only."""
    doc = {
        "_aws": {
            "Timestamp": int(datetime.now(timezone.utc).timestamp() * 1000),
            "CloudWatchMetrics": [
                {
                    "Namespace": EMF_NAMESPACE,
                    "Dimensions": [[]],
                    "Metrics": [
                        {"Name": RUN_METRIC, "Unit": "Count"},
                        {"Name": DAYS_METRIC, "Unit": "Count"},
                        {"Name": HABITS_METRIC, "Unit": "Count"},
                    ],
                }
            ],
        },
        RUN_METRIC: 1,
        DAYS_METRIC: int(days),
        HABITS_METRIC: int(habits),
        "sent": bool(sent),
    }
    print(json.dumps(doc))


def lambda_handler(event: dict, context) -> dict:
    try:
        return _run(event or {}, context)
    except Exception as e:
        logger.error("habit-skip-review failed: %s", type(e).__name__)
        raise


def _load_registry(table) -> dict:
    """The profile's habit_registry (read-only); fail-open to {} — nothing is paused then."""
    try:
        item = table.get_item(Key={"pk": f"USER#{USER_ID}", "sk": "PROFILE#v1"}).get("Item") or {}
        return item.get("habit_registry") or {}
    except Exception as e:  # noqa: BLE001
        logger.warning("[habit-skip-review] profile read failed (%s) — nothing treated as paused", type(e).__name__)
        return {}


def brief_section(table, today: str, user_id: str = USER_ID) -> dict | None:
    """#5821: the Saturday Morning Brief's "Habits to settle" section, or None.

    Saturday only (the weekly cadence this review had as an email); the same seven closed
    Pacific days and the same pause-aware queue. Read-only. None on an empty week, as the
    email was. The lines carry habit names: they go to the owner-only brief body and nowhere
    else (never a log line, a metric or a public artifact)."""
    day = parse_day_key(today)
    if day is None or day.weekday() != SATURDAY:
        return None
    dates = window_dates(today)
    queue = collect_skips(digest_utils.query_range(table, SOURCE, dates[0], dates[-1], user_id=user_id), dates, _load_registry(table))
    if not queue:
        return None
    n_habits = sum(len(names) for _, names in queue)
    head = f"{n_habits} skipped across {len(queue)} day(s), {day_label(dates[0])} to {day_label(dates[-1])}:"
    return {"key": "habits_to_settle", "title": "Habits to settle", "lines": [head] + render_lines(queue) + [RESOLVE_HINT]}


def _run(event: dict, context, table=None) -> dict:
    dry_run = is_dry_run(event)
    dates = window_dates(event.get("today") if isinstance(event, dict) else None)
    table = table or boto3.resource("dynamodb", region_name=REGION).Table(TABLE_NAME)
    records = digest_utils.query_range(table, SOURCE, dates[0], dates[-1], user_id=USER_ID)
    queue = collect_skips(records, dates, _load_registry(table))
    n_days = len(queue)
    n_habits = sum(len(names) for _, names in queue)
    logger.info(
        "[habit-skip-review] %s..%s: %d stored day(s), %d skipped daily habit(s) across %d day(s) — folded into the brief, not mailed",
        dates[0],
        dates[-1],
        len(records),
        n_habits,
        n_days,
    )

    # #5821: no SES call. The Saturday Morning Brief renders this queue (`brief_section`); the
    # run record below stays, so the producer census still tells "ran, nothing" from "never ran".
    emit_run_metric(n_days, n_habits, False)
    result = {
        "statusCode": 200,
        "window": [dates[0], dates[-1]],
        "skipped_days": n_days,
        "skipped_habits": n_habits,
        "sent": False,
        "folded_into_brief": True,
        "dry_run": dry_run,
    }
    if dry_run:
        # The rendered lines go back to the INVOKER only (the response payload is not
        # logged) so a dry run can preview the section; logs above stay counts-only.
        result["lines"] = render_lines(queue)
    return result
