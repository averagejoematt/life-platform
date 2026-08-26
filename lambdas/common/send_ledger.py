"""lambdas/common/send_ledger.py — the REPLAY half of the send gate (DIL-025).

`common.send_guard` answers "should this invocation mail anyone at all?" — an
operator-safety gate, resolved from the invoke payload. It is the wrong tool for
the question DIL-025 asks, and the distinction is the whole point:

    send_guard  : "an operator typed `aws lambda invoke` — suppress the send."
    send_ledger : "this exact letter ALREADY went out — don't send it twice."

A dry-run flag cannot answer the second question, because the duplicate
invocation that worries us carries the *same payload as the original* — the
scheduled EventBridge event, replayed. There are three live replay vectors:

  1. **Lambda async retry.** A scheduled (async) invoke that raises is retried
     by Lambda itself, twice, ~1min and ~2min later. Mail already on the wire is
     not un-sent by the exception that followed it.
  2. **DLQ redrive.** Every email function routes failures to
     `life-platform-ingestion-dlq`; `operational/dlq_consumer_lambda.retry_message`
     re-invokes the original function with the *original payload* on its
     `rate(6 hours)` schedule. That is hours after the fact.
  3. **A manual re-run** — an operator re-invoking a function that already sent.

`daily_brief_lock` (#2860) covers vector 1 and only vector 1: it is a 1200s
LEASE, deliberately short so a genuine crash gets a real retry. Six hours later
the lease is long gone, so it is structurally incapable of stopping a redrive.
This module is the durable half.

**The mechanism is a row the platform already writes.** Every email Lambda in
this repo already records a completion row the status page reads:

    pk = USER#<user>#SOURCE#email_log#<lambda_name>
    sk = DATE#<utc date the send happened>

It was written *after* the send and never read *before* one, so it proved a
send had happened to a human and to nothing else. `record_sent` writes that same
row with one added attribute — `period_key`, naming *what* was sent (for the
daily brief, the content date) rather than merely when — and `already_sent`
reads it back. `monthly_digest_lambda._already_sent_this_month` (#1658) is the
in-repo precedent for exactly this read; this module generalises it so the next
sender inherits it instead of re-deriving it.

**Why `period_key` and not the sort key.** The sort key is the wall-clock UTC
date of the *send*; the thing that must not be duplicated is the *letter*. Those
differ whenever a replay crosses a UTC midnight — the daily brief sends at 17:00
UTC, so a 6-hourly redrive lands the next UTC day roughly half the time, which
is precisely the window a sort-key-only check would miss.

**Fail-open, always.** A read failure must never be the reason a letter goes
unsent. Both entry points degrade to today's behaviour rather than raising:
`already_sent` returns False (send it), `record_sent` swallows and logs. The
worst case is the duplicate we have today; there is no worse case.

**Rollout is fail-open too.** Rows written before this module shipped carry no
`period_key`, so they never match and the guard simply does not fire for them.
It arms itself on the first send after deploy. Nothing to backfill.
"""

from __future__ import annotations

import time
from datetime import date as _date, datetime, timezone
from typing import Any, Mapping, Optional

from common import dry_run as _dry_run
from common.pacific_time import PACIFIC  # #2817: the ONE Pacific frame (#1964)

#: The `SOURCE#` segment every email-completion row has always used.
EMAIL_LOG_SOURCE = "email_log"

#: The added attribute: WHAT was sent, not merely when. Absent on pre-DIL-025
#: rows, which is what makes arming this guard a no-op migration.
PERIOD_KEY_ATTR = "period_key"

#: Matches the existing `record_email_send` retention in the daily/weekly
#: senders. Only the newest row or two is ever read, so this is the status
#: page's number, not the guard's.
DEFAULT_TTL_DAYS = 90

#: How many of the newest rows `already_sent` inspects. The guard only needs to
#: see the replayed period, and a replay is by definition recent — the DLQ
#: consumer's own window is 6 hours. Eight rows covers eight daily sends (or
#: eight weeks / eight months on the slower senders) with room to spare, while
#: keeping this to one small bounded Query.
DEFAULT_LOOKBACK = 8


def email_log_pk(lambda_name: str, user_id: str = "matthew") -> str:
    """The completion-row partition for one sender.

    Kept here so the guard and the writer cannot disagree about the partition
    they are talking about — the failure mode where a guard reads a partition
    nobody writes is silent and passes every test that does not check both.
    """
    return f"USER#{user_id}#SOURCE#{EMAIL_LOG_SOURCE}#{lambda_name}"


def force_resend_requested(event: Optional[Mapping[str, Any]]) -> bool:
    """True when the operator explicitly asked to re-send with `force_send`.

    Delegates to `common.dry_run` rather than re-deriving the key list — see
    `dry_run.force_requested`. An operator who passes `{"force_send": true}` to
    re-send a letter on purpose must not be silently refused by this guard; that
    would be a new way to fail closed on a human's explicit instruction.
    """
    if event is None:
        return False
    return _dry_run.force_requested(event)


def iso_week_key(day: _date) -> str:
    """The ISO week `day` belongs to, as `YYYY-Www` — the period key for a
    WEEKLY letter (#3113).

    Weekly senders derive their coverage window from the wall clock at
    invocation (`yesterday`, `today - 7d`, …), so a redrive that crosses a UTC
    midnight computes a *shifted* window and a date-shaped period key silently
    stops matching — the exact class of miss `period_key` exists to prevent, one
    level up. An ISO week absorbs that shift: the Sunday senders' `yesterday` is
    Saturday, and Saturday and Sunday are the same ISO week, so the replay still
    lands on the letter it is replaying.

    The unit is chosen per sender, not swept: this helper is only correct for a
    sender whose letter genuinely covers one week. A daily sender uses its
    content date; an episodic one uses the id of the thing it announced.
    """
    iso_year, iso_week, _ = day.isocalendar()
    return f"{iso_year}-W{iso_week:02d}"


def already_sent(
    table: Any,
    lambda_name: str,
    period_key: str,
    *,
    user_id: str = "matthew",
    lookback: int = DEFAULT_LOOKBACK,
    logger: Optional[Any] = None,
) -> bool:
    """True when `period_key` is already recorded as sent for `lambda_name`.

    Reads the newest `lookback` completion rows for the sender and looks for one
    whose `period_key` matches. FAILS OPEN: any read failure returns False, and
    the caller sends — a broken guard must degrade to today's behaviour, never
    to a silently unsent letter.
    """
    pk = email_log_pk(lambda_name, user_id)
    try:
        response = table.query(
            KeyConditionExpression="pk = :pk",
            ExpressionAttributeValues={":pk": pk},
            ScanIndexForward=False,  # newest first — a replay is always recent
            Limit=lookback,
        )
        for item in response.get("Items", []) or []:
            if item.get(PERIOD_KEY_ATTR) == period_key:
                return True
        return False
    except Exception as e:
        if logger is not None:
            logger.warning(f"[DIL-025] send-ledger read failed for {lambda_name}/{period_key} ({e}) — proceeding WITHOUT the replay guard")
        return False


def record_sent(
    table: Any,
    lambda_name: str,
    period_key: str,
    *,
    user_id: str = "matthew",
    ttl_days: int = DEFAULT_TTL_DAYS,
    now: Optional[int] = None,
    logger: Optional[Any] = None,
) -> None:
    """Record that `period_key` has been mailed for `lambda_name`.

    Call this IMMEDIATELY after the SES call returns — not at the end of the
    handler. Everything between the send and this write is a window in which a
    crash loses the only evidence that mail went out, and it is exactly that
    window a redrive then replays. (In the daily brief that window was ~445
    lines of post-send work.)

    Writes the same row shape the status page has always read, plus
    `period_key`. Non-fatal on failure — a bookkeeping write must never turn a
    delivered letter into a raised exception, which would itself trigger the
    retry this module exists to make safe.
    """
    _now = int(time.time()) if now is None else now
    sent_at = datetime.fromtimestamp(_now, tz=timezone.utc)
    # #2817: the INSTANT stays UTC (`sent_at` below is frame-free and comparable);
    # the DAY in the sort key is PACIFIC, because that is the frame the only reader
    # of this partition uses — `lambdas/web/site_api_status.py` builds its 90-day
    # uptime bars off `datetime.now(PT).date()`. A UTC sk put every letter sent
    # after 17:00 PT on tomorrow's bar, and the senders that hand-roll their own
    # completion row (chronicle, chronicle_email_sender, partner) now write the
    # Pacific day too — one partition, one frame. Invisible to the #2811 matcher,
    # which does not treat `datetime.fromtimestamp(...)` as a clock.
    try:
        table.put_item(
            Item={
                "pk": email_log_pk(lambda_name, user_id),
                "sk": f"DATE#{sent_at.astimezone(PACIFIC).date().isoformat()}",
                "sent_at": sent_at.isoformat(),
                "status": "success",
                PERIOD_KEY_ATTR: period_key,
                "ttl": int(_now + 86400 * ttl_days),
            }
        )
    except Exception as e:
        if logger is not None:
            logger.error(
                f"[DIL-025] send-ledger write failed for {lambda_name}/{period_key} ({e}) — a redrive of this send would NOT be caught"
            )


def should_skip_replay(
    table: Any,
    lambda_name: str,
    period_key: str,
    *,
    dry_run: bool = False,
    event: Optional[Mapping[str, Any]] = None,
    user_id: str = "matthew",
    logger: Optional[Any] = None,
) -> bool:
    """The whole pre-send decision, in one call (#3113).

    True means "this letter already went out — do not send it again". The three
    carve-outs are resolved here rather than at 17 call sites, because each one
    of them is a way for a sender to fail CLOSED (a silently unsent letter),
    which is strictly worse than the duplicate this guard prevents:

      * a **dry run** puts nothing on the wire, so it has nothing to replay —
        and must stay usable for diagnosing the very send the ledger recorded;
      * an operator's explicit **`force_send`** already means "really send" for
        the dry-run gate, and must not acquire a new way to be refused;
      * a **read failure** fails open inside `already_sent`.

    `daily_brief_lambda` predates this helper and spells the same three checks
    inline; it is left alone deliberately, since its ordering is pinned by test.
    """
    if dry_run:
        return False
    if force_resend_requested(event):
        return False
    return already_sent(table, lambda_name, period_key, user_id=user_id, logger=logger)
