"""
Milestone Digest Lambda — #1623 ("private milestone notes to 5-8 named humans")

When a genuine, window-validated milestone lands in the durable MILESTONE#
ledger (#1626), send a short private note to the small set of people Matthew
chose. Not a feed, not a broadcast — a replyable note.

Contract (the issue's ACs, in order):
  - SES via the existing email stack; no new delivery vendor or identity.
  - Recipients live OUTSIDE git: Secrets Manager ``life-platform/digest``
    ({"reply_to": "...", "recipients": [{"name": "...", "email": "..."}]}).
    No secret / empty list => the digest is DISARMED (logged no-op).
  - Fires only on announced events from milestone_ledger.read_announced_events()
    — never a raw daily threshold snapshot.
  - Gated by the spiral circuit breaker (#1627), fail-closed: no celebratory
    note during a suspected downturn; the event stays pending and re-evaluates.
  - Plain, short, replyable: text-only body, real Reply-To, no links, no
    tracking pixel, no unsubscribe funnel, no CTA to the website.
  - Global cooldown: the ledger already spaces announced events by
    GLOBAL_COOLDOWN_DAYS (12); a belt-and-suspenders MIN_SEND_GAP_DAYS (10)
    guard here means recipients are never asked to celebrate weekly even if
    ledger history is replayed.

First-run semantics mirror the ledger's own genesis: everything already
announced before arming is BASELINED (cursor row, no mail) — old news is
never delivered as fresh. One note per run, oldest pending first.

v1.0.0 — 2026-07-26 (#1623)
"""

import logging
import os

import boto3
from coach import spiral_breaker  # noqa: F401 — registered celebratory emitter (#1627); used via check_celebration_allowed
from common import send_ledger  # #3113 / DIL-025: the durable replay guard
from common.pacific_time import pacific_today
from common.secret_cache import get_secret_json
from common.send_guard import guarded_send_email, is_dry_run  # #2222: SES send-suppressor gate
from experiment.phase_taxonomy import experiment_stamp
from health import milestone_ledger

logger = logging.getLogger()
logger.setLevel(logging.INFO)

_REGION = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
SENDER = os.environ["EMAIL_SENDER"]
USER_ID = os.environ.get("USER_ID", "matthew")
DIGEST_SECRET = os.environ.get("DIGEST_SECRET", "life-platform/digest")  # noqa: S105 — secret ID, not a secret

USER_PREFIX = f"USER#{USER_ID}#SOURCE#"

# Belt-and-suspenders floor between two actual sends (the ledger's 12-day
# announcement cooldown is the primary spacing; issue band is 10-14 days).
MIN_SEND_GAP_DAYS = 10

dynamodb = boto3.resource("dynamodb", region_name=_REGION)
table = dynamodb.Table(TABLE_NAME)
ses = boto3.client("sesv2", region_name=_REGION)
secretsmanager = boto3.client("secretsmanager", region_name=_REGION)


def _load_config() -> tuple[list[dict], str | None]:
    """Recipients + reply-to from Secrets Manager. Missing/empty => disarmed."""
    try:
        cfg = get_secret_json(DIGEST_SECRET, secretsmanager)
    except Exception as exc:  # noqa: BLE001 — no secret yet is a sanctioned state, not an error
        logger.info(f"[milestone-digest] disarmed — recipients secret unavailable: {exc}")
        return [], None
    recipients = []
    for entry in cfg.get("recipients", []):
        if isinstance(entry, str):
            entry = {"email": entry}
        email = str(entry.get("email", "")).strip()
        if "@" in email:
            recipients.append({"email": email, "name": str(entry.get("name", "")).strip()})
    if recipients and not 5 <= len(recipients) <= 8:
        # The issue names 5-8 people; Matthew may configure fewer while building
        # the list — deliver anyway, but say so out loud.
        logger.warning(f"[milestone-digest] recipient count {len(recipients)} outside the 5-8 band")
    reply_to = str(cfg.get("reply_to", "")).strip() or None
    return recipients, reply_to


def _note(event: dict, name: str) -> tuple[str, str]:
    """Subject + plain-text body. Short, warm, zero links, zero CTA."""
    label = str(event.get("label", "a milestone"))
    description = str(event.get("description", "")).strip()
    event_date = str(event.get("event_date", ""))
    greeting = f"Hi {name}," if name else "Hi,"
    lines = [
        greeting,
        "",
        f"A real milestone from Matthew's experiment, confirmed {event_date}:",
        "",
        f"  {label}",
    ]
    if description and description != label:
        lines.append(f"  {description}")
    lines += [
        "",
        "You're getting this because Matthew picked a handful of people he",
        "wants to share these moments with. Nothing to click, nothing to do —",
        "but if you feel like it, hit reply. It goes straight to him.",
    ]
    return f"From Matthew's experiment: {label}", "\n".join(lines)


def _send(recipient: dict, reply_to: str | None, subject: str, body: str, dry_run: bool = False) -> bool:
    kwargs = {
        "FromEmailAddress": SENDER,
        "Destination": {"ToAddresses": [recipient["email"]]},
        "Content": {"Simple": {"Subject": {"Data": subject}, "Body": {"Text": {"Data": body}}}},
    }
    if reply_to:
        kwargs["ReplyToAddresses"] = [reply_to]
    try:
        guarded_send_email(ses, dry_run, **kwargs)
        return True
    except Exception as exc:  # noqa: BLE001 — one bad address must not sink the rest
        logger.error(f"[milestone-digest] send failed for one recipient: {exc}")
        return False


def _celebration_allowed() -> bool:
    """Spiral-breaker gate (#1627). Any failure counts as suppressed (fail closed)."""
    try:
        allowed, verdict = spiral_breaker.check_celebration_allowed("milestone_digest", table=table)
        if not allowed:
            logger.info(f"[milestone-digest] suppressed by spiral breaker: {verdict.get('reasons')}")
        return allowed
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[milestone-digest] breaker check failed — treating as suppressed: {exc}")
        return False


#: The `email_log#` partition this sender's completion rows live in (#3113).
LEDGER_NAME = "milestone_digest"


def _period_key(milestone_id: str) -> str:
    """WHICH note this is — the milestone announced, not the day it was mailed.

    This sender is episodic, not periodic: it runs daily and mails only when a
    window-validated milestone lands, so there is no calendar period to key on.
    The milestone id IS the identity of the letter, and it is the same id on a
    replay however many days later the redrive arrives.
    """
    return f"milestone:{milestone_id}"


def lambda_handler(event: dict, context) -> dict:  # noqa: ARG001
    try:
        return _run(dry_run=is_dry_run(event), event=event)
    except Exception:
        # I4: fail loudly into the DLQ/digest-alarm path — a swallowed error here
        # would silently kill the platform's best downturn-signal channel.
        logger.exception("[milestone-digest] run failed")
        raise


def _run(dry_run: bool = False, event: dict | None = None) -> dict:
    today = pacific_today()
    stamp = experiment_stamp()

    recipients, reply_to = _load_config()
    if not recipients:
        return {"status": "disarmed", "reason": "no recipients configured"}

    state = milestone_ledger.read_digest_state(table, USER_PREFIX)
    announced = milestone_ledger.read_announced_events(table, USER_PREFIX)

    if not state["has_genesis"]:
        for ev in announced:
            milestone_ledger.mark_digest_sent(
                table,
                USER_PREFIX,
                str(ev["milestone_id"]),
                origin=milestone_ledger.DIGEST_ORIGIN_BASELINE,
                sent_date=None,
                recorded_at=today,
                stamp=stamp,
            )
        milestone_ledger.write_digest_genesis(table, USER_PREFIX, today, stamp)
        logger.info(f"[milestone-digest] armed — baselined {len(announced)} pre-existing announced events, no mail")
        return {"status": "baselined", "baselined": len(announced)}

    pending = [e for e in announced if str(e.get("milestone_id")) not in state["sent_ids"]]
    if not pending:
        return {"status": "quiet"}

    if state["last_sent_date"] and milestone_ledger._days_between(state["last_sent_date"], today) < MIN_SEND_GAP_DAYS:
        logger.info(f"[milestone-digest] cooldown — last note {state['last_sent_date']}, {len(pending)} pending")
        return {"status": "cooldown_deferred", "pending": len(pending)}

    if not _celebration_allowed():
        return {"status": "suppressed", "pending": len(pending)}

    ev = pending[0]  # oldest first (read_announced_events sorts by event_date)
    period_key = _period_key(str(ev["milestone_id"]))

    # DIL-025 / #3113 replay guard — FIRST, because this sender mails third
    # parties. `mark_digest_sent` below is a cursor, not a replay guard: it is
    # written after the whole fan-out, so every "mailed some of the list, then
    # crashed" invocation leaves the cursor untouched and a redrive re-mails
    # everyone. The ledger row is written after the FIRST delivery instead.
    if send_ledger.should_skip_replay(table, LEDGER_NAME, period_key, dry_run=dry_run, event=event, logger=logger):
        logger.warning(
            f"[DIL-025] milestone note for {period_key} already went out — refusing to mail it twice (pass force_send to override)"
        )
        return {"status": "already_sent", "milestone_id": ev.get("milestone_id")}

    delivered = 0
    for recipient in recipients:
        subject, body = _note(ev, recipient["name"])
        if _send(recipient, reply_to, subject, body, dry_run=dry_run):
            delivered += 1
            if delivered == 1 and not dry_run:
                # Mail is on the wire NOW. Record before the rest of the fan-out,
                # not after it — everything between here and the cursor write is
                # window in which a crash loses the only evidence of the send.
                send_ledger.record_sent(table, LEDGER_NAME, period_key, logger=logger)
    if delivered == 0:
        # Nothing went out: leave the cursor untouched so tomorrow retries, and
        # let the invocation fail into the DLQ/digest alarm path.
        raise RuntimeError(f"[milestone-digest] 0/{len(recipients)} deliveries for {ev.get('milestone_id')}")

    milestone_ledger.mark_digest_sent(
        table,
        USER_PREFIX,
        str(ev["milestone_id"]),
        origin=milestone_ledger.DIGEST_ORIGIN_SENT,
        sent_date=today,
        recorded_at=today,
        delivered=delivered,
        stamp=stamp,
    )
    logger.info(f"[milestone-digest] sent '{ev.get('label')}' to {delivered}/{len(recipients)} people")
    return {"status": "sent", "milestone_id": ev.get("milestone_id"), "delivered": delivered, "recipients": len(recipients)}
