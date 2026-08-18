"""lambdas/emails/daily_brief_lock.py — #2860 in-flight guard for daily-brief.

Split out of daily_brief_lambda.py rather than grown in place: that file sits
on the module-size ratchet's BASELINE registry at zero headroom (#1665/#2610
— "never raise a baseline", extract instead). Facade state via the `_g`
hand-off, matching chronicle_store.py's established shape for exactly this
kind of small extracted lambdas/emails/ sibling.

2026-08-17 15:54-15:56Z: a default-timeout SYNC `aws lambda invoke` of
daily-brief retried on its own client-side read timeout (the AWS SDK's
"standard" retry mode treats that as transient) — attempts=3, ~60s apart.
Each retry landed on a container with no memory of the first attempt and
re-ran the whole ~7.5min, 4-AI-call generation from scratch: three paid
generations for one scheduled run, and enough token spend in one window to
trip the AI token alarms. `DRY_RUN`/`dry_run:true` does NOT protect against
this — per #2255 it suppresses writes only, never AI spend.

The mechanism is a DynamoDB conditional-put LEASE — never a permanent
tombstone — keyed on `(date, dry_run)`:
  * the put only succeeds when no lease row exists yet for that key, OR the
    existing row's `ttl` has already passed;
  * a concurrent retry inside the TTL window is refused, letting the caller
    (`daily_brief_lambda.lambda_handler`) short-circuit BEFORE
    `fetch_profile`/`gather_daily_data` even run, let alone any of the 4 AI
    calls — this is what makes it a spend guard and not just a dedup log
    line;
  * a genuine crash (Lambda killed, OOM, ...) still gets a real retry once
    the TTL — deliberately set well past daily-brief's own 900s configured
    Lambda timeout (cdk/stacks/email_stack.py) — elapses. The scheduled
    run's legitimate retry semantics are unaffected: this is a bounded
    lease, not a tombstone.

`DAILY_BRIEF_LOCK_PK` is a `SYSTEM#` ops-namespace partition — same shape as
`daily_brief_lambda.GENESIS_ALARM_WINDOW_PK` and
`dlq_consumer_lambda.LEDGER_PK` — that `phase_taxonomy.classify()` resolves
to SYSTEM_STATE via its existing generic `SYSTEM#` prefix rule: never
tagged, never wiped, never phase-filtered, and (per that module's own docs)
invisible to the restart tagger either way, since it only ever traverses
`USER#...#SOURCE#`.

Reserved-concurrency=1 on the function was weighed as an alternative and
rejected — see the shipping PR body for the full trade-off. In short: it
would also serialize the unrelated `regrade_dates` mode (a fast, non-AI,
deterministic path with its own legitimate concurrent use), throttles
opaquely rather than returning a legible "already in flight for DATE"
response, and — most importantly — puts the ONLY entry point for the
scheduled cron behind the same single concurrency slot as ad-hoc manual
invokes, so an operator's overlapping diagnostic run could throttle the
real scheduled send instead of the reverse. This lease is scoped per
(date, dry_run) and lives entirely inside the code path that already knows
which invocation is which, so it cannot have that failure mode.
"""

from __future__ import annotations

import time
from decimal import Decimal
from typing import Optional

from botocore.exceptions import ClientError

# A LEASE, not a tombstone: comfortably longer than daily-brief's own 900s
# (15min) configured Lambda timeout so the lease cannot expire while a first
# attempt could still legitimately be running, but short enough that a
# genuine crash still gets a real retry within a bounded window rather than
# a permanent block.
DAILY_BRIEF_LOCK_PK = "SYSTEM#daily-brief-lock"
DAILY_BRIEF_LOCK_TTL_SECONDS = 1200


def acquire_daily_brief_lock(date_str: str, dry_run_flag: bool, *, _g: dict, now: Optional[int] = None) -> bool:
    """Try to claim the in-flight lease for (date_str, dry_run_flag).

    Returns True if THIS invocation may proceed, False if another invocation
    already holds an unexpired lease for the same (date, dry_run) pair.

    Never raises. `False` is the expected, non-exceptional "someone else is
    already generating this" outcome the caller short-circuits on. Any OTHER
    failure (DDB throttled, a network blip, ...) is logged loudly — a broken
    guard is itself worth an operator's attention — but FAILS OPEN (returns
    True) rather than propagating: this lease is a backstop against a
    duplicate-spend retry storm, not a dependency the whole brief should go
    dark over. Losing the day's brief entirely because the lock write itself
    hiccuped would be a strictly worse outcome than the rare double-
    generation this degrades to.

    `_g` is the facade hand-off (chronicle_store.py's pattern): `{"table":
    ..., "logger": ...}`.
    """
    table = _g["table"]
    logger = _g["logger"]
    _now = int(time.time()) if now is None else now
    lock_sk = f"LOCK#{date_str}#{bool(dry_run_flag)}"
    try:
        table.put_item(
            Item={
                "pk": DAILY_BRIEF_LOCK_PK,
                "sk": lock_sk,
                "ttl": Decimal(_now + DAILY_BRIEF_LOCK_TTL_SECONDS),
                "acquired_at": Decimal(_now),
            },
            ConditionExpression="attribute_not_exists(pk) OR #ttl < :now",
            ExpressionAttributeNames={"#ttl": "ttl"},
            ExpressionAttributeValues={":now": Decimal(_now)},
        )
        return True
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return False
        logger.error(f"[#2860] in-flight lock write failed ({e}) — proceeding WITHOUT the guard rather than losing the brief entirely")
        return True
    except Exception as e:  # not even a ClientError — same fail-open reasoning
        logger.error(
            f"[#2860] in-flight lock write failed unexpectedly ({e}) — proceeding WITHOUT the guard rather than losing the brief entirely"
        )
        return True
