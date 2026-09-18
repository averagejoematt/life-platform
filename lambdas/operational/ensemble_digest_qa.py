"""ensemble_digest_qa.py — #3829: the ENSEMBLE#digest cycle-row dead-man.

THE INCIDENT THIS EXISTS FOR
  `coach-ensemble-digest` is invoked asynchronously by daily-brief at ~17:00 UTC with
  `{"cycle_date": <PT today>}` and persists exactly one row per cycle at
  `ENSEMBLE#digest / CYCLE#{date}`. On 2026-09-13 and 2026-09-15 it logged
  `Ensemble digest produced — 7 summaries, …` and then died at its 90s ceiling, three
  times each (the async-invoke retry policy), writing NOTHING. Two of four consecutive
  cycles had no row.

  Nothing reported it. The partition appears in `qa_smoke_lambda` only inside
  `_PHASE_STAMP_ENSEMBLE_PKS` — a check on whether the rows that EXIST carry a phase
  stamp, which is silent by construction about a row that does not exist. The gap was
  found eight days later by a human chasing a DLQ alarm citation at wrap, and the DLQ
  is the wrong instrument: it only sees the *last* failed attempt of an *async* invoke,
  it clears when someone drains the queue, and it says nothing at all about the failure
  mode where the producer is never invoked (a daily-brief that dies before line 1349).

WHY ABSENCE IS UNAMBIGUOUS HERE, WHICH IS WHAT MAKES THIS CHECKABLE
  Every non-crashing path through the handler writes the row — the reuse path, the
  no-coach-data path, the LLM-failure fallback, the grounding-HOLD fallback, and the
  budget-tier pause (`budget_guard` pauses "ensemble" at tier >= 1; through 2026-08-05
  .. 08-31 the function was paused and still wrote a ~1.3s deterministic row every
  single day — CYCLE#2026-08-01 .. 08-31 are all present). So there is no legitimate
  reason for a cycle to be missing, and no tier/pause exemption is needed. A hole means
  the invocation died before its write, or was never made.

WHY THE WINDOW IS THREE DAYS AND NOT THIRTY
  A hole is PERMANENT. The digest summarises the coaches' state on its cycle date; a
  re-invoke today with `{"cycle_date": "2026-09-13"}` would read TODAY's coach records
  and stamp them onto a past cycle — a synthetic row in a measured partition, which is
  the one thing the platform will not do (the "attest, never backfill" rule). So the
  window is sized for DETECTION, not for archaeology: three days reports every hole on
  the day it opens and for two nights after, which tolerates two consecutive missed
  qa-smoke runs, and then stops nagging about something no one can repair. A 30-day
  window would carry the 09-13/09-15 holes as a standing warn for a month, and a warn
  that cannot be cleared is a warn that gets muted (#3851).

WHY THE NEWEST ROW IS NOT THE CHECK
  The obvious implementation — "is the most recent CYCLE# row recent?" — would have
  MISSED BOTH incidents. On 2026-09-14 the newest sk was CYCLE#2026-09-14, perfectly
  fresh, while 09-13 was a hole one day behind it. Holes heal at the head and stay in
  the body. This check enumerates the expected dates in the window and reports the set
  difference, so a hole is visible whether or not the next cycle succeeded.

SEVERITY
  The most recent DUE cycle missing is a FAIL: it happened in the last few hours, the
  cause is live, and the operator can still look at a log stream that has not rotated.
  An older hole in the window is a WARN: real, worth seeing, but no longer actionable
  in the same way. Both name the dates; neither emits a remediation that would backfill.

CONTENT_TRUTH, not DEPLOY_HEALTH: a cron artifact from hours ago is not evidence about
the deploy in flight, and reverting the fleet cannot conjure a missing row (#1921).
"""

from __future__ import annotations

from datetime import date, timedelta, timezone

from boto3.dynamodb.conditions import Key
from common.constants import EXPERIMENT_START_DATE

PK = "ENSEMBLE#digest"
SK_PREFIX = "CYCLE#"

# daily-brief's EventBridge cron, fixed UTC (cdk/stacks/email_stack.py). The digest is
# an async fan-out from the END of that run, observed starting ~17:09Z.
DUE_HOUR_UTC = 17

# How long after the cron a missing row stops being "still in flight". Measured:
# the 3-attempt async retry chain on the worst observed day (2026-09-15) ran
# 17:14:17Z -> 17:15:47Z at a 90s ceiling; at the current 300s ceiling the same
# chain is bounded by 3 x 300s + 2 backoff gaps ~= 20 min. 60 min is that bound
# plus the same margin again, and still lands 30 min before qa-smoke's 18:30Z run.
GRACE_MINUTES = 60

# See "WHY THE WINDOW IS THREE DAYS" above: detection horizon, not an audit horizon.
WINDOW_DAYS = 3


def _due_dates(now_utc):
    """The cycle dates whose write window has CLOSED, newest first.

    `cycle_date` is `pacific_today()` at invoke time; the cron fires at 17:00 UTC,
    which is 10:00 PT on the SAME calendar date, so the cycle date equals the UTC
    date of the run. Nothing here needs a PT conversion, and not doing one is
    deliberate — a tz round-trip is how an off-by-one enters.
    """
    cutoff = now_utc.replace(hour=DUE_HOUR_UTC, minute=0, second=0, microsecond=0) + timedelta(minutes=GRACE_MINUTES)
    latest = now_utc.date() if now_utc >= cutoff else now_utc.date() - timedelta(days=1)
    genesis = date.fromisoformat(EXPERIMENT_START_DATE)
    dates = [latest - timedelta(days=i) for i in range(WINDOW_DAYS)]
    # Pre-genesis cycles are not expected: the reset tombstones the previous cycle's
    # rows and no digest is written before Day 1 (a future genesis runs a countdown).
    return [d for d in dates if d >= genesis]


def _present_cycles(table, first, last):
    """The CYCLE# dates present in [first, last], from one paginated Query."""
    found = set()
    lek = None
    while True:
        kw = {
            "KeyConditionExpression": Key("pk").eq(PK) & Key("sk").between(SK_PREFIX + first.isoformat(), SK_PREFIX + last.isoformat()),
            "ProjectionExpression": "sk",
        }
        if lek:
            kw["ExclusiveStartKey"] = lek
        resp = table.query(**kw)
        for it in resp.get("Items", []):
            sk = str(it.get("sk", ""))
            if sk.startswith(SK_PREFIX):
                found.add(sk[len(SK_PREFIX) :])
        lek = resp.get("LastEvaluatedKey")
        if not lek:
            break
    return found


def check_ensemble_digest_liveness(table, check_cls, partition, pt_now):
    c = check_cls("ensemble_digest:cycle_rows", "Data Freshness", partition)
    now_utc = pt_now().astimezone(timezone.utc)
    due = _due_dates(now_utc)
    if not due:
        c.ok("no ensemble-digest cycle is due yet (pre-genesis window)")
        return [c]

    try:
        present = _present_cycles(table, due[-1], due[0])
    except Exception as e:
        # A read failure is NOT freshness (#2662). Never report "all present" over a
        # query that did not complete.
        c.warn(f"ensemble-digest liveness could not be read (no verdict was reached): {e}")
        return [c]

    missing = [d.isoformat() for d in due if d.isoformat() not in present]
    if not missing:
        c.ok(f"ENSEMBLE#digest has a CYCLE# row for each of the last {len(due)} due cycle(s) ({due[-1]} .. {due[0]})")
        return [c]

    newest_due = due[0].isoformat()
    if newest_due in missing:
        c.fail(
            f"no ENSEMBLE#digest row for CYCLE#{newest_due} — coach-ensemble-digest either died before its write "
            f"or was never invoked by daily-brief. Missing in the last {len(due)} due cycle(s): {', '.join(missing)}. "
            "Read /aws/lambda/coach-ensemble-digest for today: a REPORT line with `Status: timeout` (3 per cycle, the "
            "async retry) means the invocation is over its ceiling again; no START line at all means daily-brief never "
            "fanned out. There is no honest backfill: re-invoking with a past cycle_date would stamp TODAY's coach "
            "state onto that cycle (#3829)."
        )
        return [c]

    c.warn(
        f"ENSEMBLE#digest is missing {len(missing)} cycle row(s) in the last {len(due)} due cycle(s): "
        f"{', '.join(missing)} — the most recent cycle ({newest_due}) did land, so the producer is running now. "
        "These holes are permanent: the digest describes its cycle date's coach state and cannot be honestly "
        "backfilled (#3829)."
    )
    return [c]
