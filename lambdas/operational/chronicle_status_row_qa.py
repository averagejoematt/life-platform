"""chronicle_status_row_qa.py — #3563 box 3, third clause: the chronicle
status-row WRITE-LIVENESS dead-man.

THE INCIDENT THIS EXISTS FOR
  `chronicle-email-sender` delivered the Wednesday chronicle on 2026-08-14,
  08-21 and 08-28. All three sends succeeded — SES accepted, `Sent 1/1` logged,
  subscribers received mail. All three `email_log#wednesday_chronicle` status
  rows were then DENIED (`AccessDeniedException ... dynamodb:PutItem`, the role
  had GetItem/Query/UpdateItem only) and swallowed at INFO. `/api/status` read
  `wednesday_chronicle | red | 44d ago` for four weeks while the thing it
  reports on ran perfectly every week.

WHY NONE OF THE EXISTING INSTRUMENTS COULD SEE IT, which is the whole design
constraint here:

  * `chronicle-delivery-heartbeat` fires when a chronicle is not DELIVERED.
    Delivery happened. It was correctly silent for all 44 days.
  * `tests/test_heartbeat_completeness.py` quantifies over scheduled Lambda
    FUNCTION NAMES and asserts each has a liveness signal. `chronicle-email-sender`
    is already enrolled there (mapped to the delivery heartbeat above). A
    DynamoDB *partition* is not a member of the set that file ranges over, so
    the clause's literal wording ("`email_log#wednesday_chronicle` enrolled in
    `test_heartbeat_completeness`") is a category error — recorded by Sessions
    AG and AI on #3563, and re-homed here rather than forced into a file that
    structurally cannot answer.
  * The three live metric-filter alarms (`swallowed-permission-denial`,
    `chronicle-status-write-failed`, `freshness-sentinel-write-failed`) all fire
    on a LOGGED failure. They cover the denial path now that it logs at ERROR
    with a sentinel token. They cannot see the residual class this check exists
    for: a send that reports success and writes no row WITHOUT RAISING — no
    exception, no token, nothing to filter on.

THE TWO WITNESSES, AND WHY THEY ARE INDEPENDENT
  The handler writes both of these under one identical `if sent > 0:` guard, in
  adjacent statements (`chronicle_email_sender_lambda.py`, end of the send
  loop):

    A. `_mark_installment_delivered()` -> UpdateItem `delivered_at` on
       `USER#matthew#SOURCE#chronicle / DATE#{installment}`  (#2112)
    B. `_record_email_send()`          -> PutItem on
       `USER#matthew#SOURCE#email_log#wednesday_chronicle / DATE#{pt today}` (#2254)

  They are independent where it matters: different partitions, different verbs,
  different IAM statements. The #3563 failure was exactly a grant that covered
  one and not the other, so A survives to witness the delivery that B failed to
  record. Measured spread between the two stamps on the two clean sends:
  **17 ms and 8 ms** — far inside the 60 s the acceptance clause names.

WHY NOT CLOUDWATCH LOGS, AND WHY NOT THE ChronicleSent METRIC
  The clause's literal source is the `Sent N/N` log line. Reading it needs
  `logs:FilterLogEvents`, which NO Lambda in this fleet has — a new capability
  class, and an owner decision left open on #3563 rather than taken as a side
  effect of closing a P2. Pairing against the `ChronicleSent` metric instead is
  UNSOUND and was rejected on #3563/#3865: that metric's vocabulary collides at
  exactly 1 (one real subscriber delivered == the sanctioned budget-pause
  datapoint), so a `1` with no status row cannot distinguish "delivered and the
  row was lost" from "paused, no row expected". `delivered_at` has neither
  problem, costs no new grant (the qa-smoke role already holds table-wide
  `dynamodb:Query`), and is written on exactly the same condition as the row it
  is paired with.

WHAT IS NOT CLAIMED
  If BOTH writes are lost in the same run, this check is blind — the delivery
  has no witness left in DynamoDB. That residual belongs to the delivery-side
  dead-man (`chronicle-delivery-heartbeat`), whose own ambiguity is filed as
  #3865 and is not fixed here. Stated rather than papered over: this instrument
  closes the one-of-two-writes-lost class, which is the class that actually
  happened, three times.

WINDOW AND SEVERITY
  A breach is PERMANENT — the status row belongs to a delivery instant that has
  passed, and writing one today would be a synthetic row in a measured partition
  ("attest, never backfill"). So the window is sized for DETECTION, not
  archaeology: 14 days covers the last two weekly sends, reports a breach the
  night it opens and keeps reporting for thirteen more, then stops nagging about
  something no one can repair (a warn that cannot be cleared is a warn that gets
  muted, #3851).

  The NEWEST delivery in the window missing its row is a FAIL: it happened in
  the last few days, the cause is live, and `/api/status` is wrong about a send
  RIGHT NOW. An older breach with a clean newest delivery is a WARN: real, worth
  seeing, no longer the same kind of actionable.

CONTENT_TRUTH, not DEPLOY_HEALTH: a missing row from a cron days ago is not
evidence about the deploy in flight, and reverting the fleet cannot conjure it
(#1921).
"""

from __future__ import annotations

from datetime import datetime, timedelta

from boto3.dynamodb.conditions import Key
from common.pacific_time import parse_iso_utc  # #1964/#3609: THE ISO-8601 instant parser

INSTALLMENT_SUFFIX = "chronicle"
STATUS_SUFFIX = "email_log#wednesday_chronicle"
SK_PREFIX = "DATE#"

# The acceptance clause's own number: "a 'Sent N/N' line without a status row
# within 60s is a dead-man breach". Measured live spread on the two sends that
# wrote both witnesses: 0.017 s and 0.008 s.
PAIRING_WINDOW_SECONDS = 60

# See "WINDOW AND SEVERITY" above. Two weekly sends, then silence.
WINDOW_DAYS = 14


def _query_partition(table, pk: str, attrs: str) -> list[dict]:
    """Every ``DATE#`` row on one partition, paginated. Small by construction
    (tens of items); the projection keeps it to the two stamps we compare."""
    items: list[dict] = []
    lek = None
    while True:
        kw: dict = {
            "KeyConditionExpression": Key("pk").eq(pk) & Key("sk").begins_with(SK_PREFIX),
            "ProjectionExpression": attrs,
        }
        if lek:
            kw["ExclusiveStartKey"] = lek
        resp = table.query(**kw)
        items.extend(resp.get("Items", []))
        lek = resp.get("LastEvaluatedKey")
        if not lek:
            break
    return items


def deliveries(rows: list[dict]) -> list[tuple[str, datetime]]:
    """``(sk, delivered_at instant)`` for every installment that was DELIVERED,
    oldest first. A row with no parseable ``delivered_at`` was never sent (or
    the send failed entirely, which leaves the marker off by design) and is not
    a member of the set this check quantifies over."""
    out: list[tuple[str, datetime]] = []
    for r in rows:
        ts = parse_iso_utc(r.get("delivered_at"))
        if ts is not None:
            out.append((str(r.get("sk", "")), ts))
    return sorted(out, key=lambda p: p[1])


def status_instants(rows: list[dict]) -> list[tuple[str, datetime]]:
    """``(sk, sent_at instant)`` for every status row that carries a stamp."""
    out: list[tuple[str, datetime]] = []
    for r in rows:
        ts = parse_iso_utc(r.get("sent_at"))
        if ts is not None:
            out.append((str(r.get("sk", "")), ts))
    return sorted(out, key=lambda p: p[1])


def unpaired(delivered: list[tuple[str, datetime]], recorded: list[tuple[str, datetime]]) -> list[tuple[str, datetime]]:
    """The deliveries with no status row inside ``PAIRING_WINDOW_SECONDS``.

    Deliberately ONE-DIRECTIONAL. A status row with no matching delivery is not
    a finding: rows dated 2026-06-24 .. 2026-07-22 predate #2112's
    ``delivered_at`` marker entirely, and older ones were written by the
    generator's preview route before #2254 moved the write into the sender.
    Quantifying in that direction would red on history nobody can change.
    """
    gaps: list[tuple[str, datetime]] = []
    for sk, when in delivered:
        if not any(abs((s - when).total_seconds()) <= PAIRING_WINDOW_SECONDS for _, s in recorded):
            gaps.append((sk, when))
    return gaps


def check_chronicle_status_row_liveness(table, user_prefix, check_cls, partition, pt_now):
    c = check_cls("chronicle_status_row:write_liveness", "Data Freshness", partition)
    now = pt_now()
    cutoff = now - timedelta(days=WINDOW_DAYS)

    try:
        installments = _query_partition(table, f"{user_prefix}{INSTALLMENT_SUFFIX}", "sk, delivered_at")
        rows = _query_partition(table, f"{user_prefix}{STATUS_SUFFIX}", "sk, sent_at")
    except Exception as e:
        # A read failure is NOT liveness (#2662). Never report "every delivery
        # recorded" over a query that did not complete.
        c.warn(f"chronicle status-row liveness could not be read (no verdict was reached): {e}")
        return [c]

    if not installments:
        # The vacuous-read trap: this partition is written most weeks and holds
        # the whole chronicle archive. Zero DATE# rows means the read is wrong,
        # not that nothing was delivered.
        c.warn(
            f"no DATE# rows at all on {user_prefix}{INSTALLMENT_SUFFIX} — the chronicle archive cannot be empty, "
            "so this is a broken read, not a clean week. No verdict was reached."
        )
        return [c]

    delivered = deliveries(installments)
    if not delivered:
        # Non-vacuity on the WITNESS, not just on the read: `delivered_at` is
        # written by `_mark_installment_delivered` on every successful send
        # since #2112. If a refactor renames or drops it, every assertion below
        # passes for free, forever — the #3563 failure mode one level up.
        c.warn(
            f"{len(installments)} chronicle installment row(s) read, but NONE carries a `delivered_at` stamp — "
            "the delivery witness this dead-man pairs against is absent from the entire partition "
            "(renamed, dropped, or never written since #2112). No verdict was reached."
        )
        return [c]

    recorded = status_instants(rows)
    # Bounded on BOTH sides. The upper bound is not decoration: without it a
    # future-dated `delivered_at` (a hand-written row, a clock skew, a replayed
    # fixture) joins the window and becomes "the newest delivery", which is the
    # one that decides FAIL vs WARN — so a breach that happened today would be
    # demoted to a warn by a row nobody has reached yet. Caught by
    # test_the_founding_incident_replays_as_a_fail_naming_both_sends.
    in_window = [(sk, when) for sk, when in delivered if cutoff <= when <= now]
    if not in_window:
        newest_sk, newest_when = delivered[-1]
        c.ok(
            f"no chronicle delivery in the last {WINDOW_DAYS} days (newest: {newest_sk} delivered "
            f"{newest_when.isoformat()}) — a delivery GAP is the chronicle-delivery-heartbeat's class, not this one; "
            f"this check reports only a delivery whose status row is missing."
        )
        return [c]

    gaps = unpaired(in_window, recorded)
    if not gaps:
        c.ok(
            f"every one of the {len(in_window)} chronicle delivery/deliveries in the last {WINDOW_DAYS} days has an "
            f"email_log#wednesday_chronicle status row within {PAIRING_WINDOW_SECONDS}s "
            f"({in_window[0][0]} .. {in_window[-1][0]})"
        )
        return [c]

    named = ", ".join(f"{sk} (delivered {when.isoformat()})" for sk, when in gaps)
    newest_sk = in_window[-1][0]
    detail = (
        f"chronicle-email-sender recorded a DELIVERY with no email_log#wednesday_chronicle status row within "
        f"{PAIRING_WINDOW_SECONDS}s: {named}. The send happened — `delivered_at` is written under the same "
        "`if sent > 0:` guard as the row — so /api/status is reporting the Wednesday chronicle as older than it is. "
        "Check /aws/lambda/chronicle-email-sender for the CHRONICLE-STATUS-WRITE-FAILED token; if it is ABSENT the "
        "write was lost without raising, which is the silent class this dead-man exists for (#3563). There is no "
        "honest backfill: a status row written now would claim a send instant that has passed."
    )
    if any(sk == newest_sk for sk, _ in gaps):
        c.fail(detail)
    else:
        c.warn(
            detail + f" The newest delivery in the window ({newest_sk}) DID record its row, so the writer is "
            "working now and these are historical."
        )
    return [c]
