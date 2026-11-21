"""
alert_digest_lambda.py — ADR-050: daily-batched alarm digest.

Drains the life-platform-alerts-digest-queue SQS (fed by the
life-platform-alerts-digest SNS topic with raw message delivery), groups
by AlarmName, and sends ONE summary SES email at 8 AM PT.

#2827: SNS only fires on state TRANSITIONS, so an alarm that stays red
falls out of the digest entirely (one live alarm had been red 29 days on a
single transition). Every run now also does ONE read-only
describe-alarms(StateValue=ALARM) sweep and appends a "STILL IN ALARM"
section with each standing red's age — and a digest IS sent when standing
reds exist even if the transition queue is empty.

#5821: besides CloudWatch alarms the queue carries ops notices published through
common.ops_digest (a content-truth-only QA-smoke failure, the remediation hand-off, a
budget-tier change below tier 3) in the same alarm-notification JSON shape, so they
group and render here with no special case.

If the queue is empty AND nothing is standing in ALARM, sends nothing
(no "all clear" emails).

ADR-170 (2026-11-21): the EMAIL carries only what the owner himself must do. The full
record above (every transition, every standing red) is still built each run and LOGGED
(`digest_record`), where a Claude session reads it; the email is sent only when an entry
in operational/owner_actions.py is live, with the instruction as its subject. Nobody acted
on the all-alarms email in six months — code and config reds belong to sessions (the
SessionStart pre-flight prints every red) and the remediation agent. The urgent topic
(`life-platform-alerts`) now feeds this queue too, in place of its raw "ALARM: …" email
subscription, so an owner action raised there lands here as well.

Replaces the previous model where every CloudWatch alarm produced an
immediate email — see DECISIONS.md ADR-050 for rationale.

Environment variables:
  DIGEST_QUEUE_URL   (required)
  EMAIL_RECIPIENT    (default awsdev@mattsusername.com)
  EMAIL_SENDER       (default awsdev@mattsusername.com)
  REGION             (default us-west-2)
"""

import json
import logging
import os
from collections import defaultdict
from datetime import datetime, timezone

import boto3
from common.pacific_time import pacific_today  # #2798: the digest names the Pacific day
from common.send_guard import guarded_send_email, is_dry_run  # #2222: SES send-suppressor gate

from operational.owner_actions import STANDING_REMINDER_WEEKDAY, owner_action_for  # ADR-170

try:
    from common.platform_logger import get_logger

    logger = get_logger("alert-digest")
except ImportError:
    logger = logging.getLogger("alert-digest")
    logger.setLevel(logging.INFO)

REGION = os.environ.get("AWS_REGION", "us-west-2")
DIGEST_QUEUE_URL = os.environ["DIGEST_QUEUE_URL"]
EMAIL_RECIPIENT = os.environ.get("EMAIL_RECIPIENT", "awsdev@mattsusername.com")
EMAIL_SENDER = os.environ.get("EMAIL_SENDER", "awsdev@mattsusername.com")

# SQS receive-message caps at 10 per call. Loop until empty.
MAX_RECEIVE_BATCH = 10

sqs = boto3.client("sqs", region_name=REGION)
ses = boto3.client("sesv2", region_name=REGION)
cloudwatch = boto3.client("cloudwatch", region_name=REGION)


def _parse_alarm_payload(body):
    """SNS raw delivery puts the CloudWatch alarm JSON directly in the SQS body.

    Fall back to parsing the full SNS envelope (Message field) for safety in
    case raw delivery isn't enabled.
    """
    try:
        payload = json.loads(body)
    except (TypeError, ValueError):
        return {"AlarmName": "unparseable", "NewStateReason": body[:200]}
    if isinstance(payload, dict) and "Message" in payload and "AlarmName" not in payload:
        try:
            inner = json.loads(payload["Message"])
            if isinstance(inner, dict):
                return inner
        except (TypeError, ValueError):
            pass
        # ADR-170: a plain-text publish on the urgent topic (a Panel hold, a budget tier-3
        # notice) arrives in its SNS envelope; its Subject is the line's name, so it can be
        # matched by owner_actions and grouped, instead of collapsing into `unparseable`.
        subject = payload.get("Subject")
        if subject:
            return {
                "AlarmName": str(subject)[:200],
                "NewStateValue": "NOTICE",
                "NewStateReason": str(payload["Message"])[:300],
                "StateChangeTime": payload.get("Timestamp", ""),
            }
        return {"AlarmName": "unparseable", "NewStateReason": str(payload["Message"])[:200]}
    return payload


def _drain_queue():
    """Pull all messages from the digest queue and delete them after parsing."""
    alarms = []
    while True:
        resp = sqs.receive_message(
            QueueUrl=DIGEST_QUEUE_URL,
            MaxNumberOfMessages=MAX_RECEIVE_BATCH,
            WaitTimeSeconds=1,
            VisibilityTimeout=60,
        )
        msgs = resp.get("Messages", [])
        if not msgs:
            break
        for m in msgs:
            alarms.append(_parse_alarm_payload(m.get("Body", "")))
        # Batch delete (SQS allows up to 10 per call, which matches MAX_RECEIVE_BATCH).
        sqs.delete_message_batch(
            QueueUrl=DIGEST_QUEUE_URL,
            Entries=[{"Id": str(i), "ReceiptHandle": m["ReceiptHandle"]} for i, m in enumerate(msgs)],
        )
    return alarms


def _group_by_alarm(alarms):
    """Dedupe by AlarmName. Count fires, keep first reason + latest state-change time."""
    grouped = defaultdict(lambda: {"count": 0, "reason": "", "last_state_change": "", "last_state": ""})
    seen = set()
    for a in alarms:
        name = a.get("AlarmName", "unknown")
        # ADR-170: an alarm routed digest+urgent now reaches this queue through both topics —
        # the same transition (name, state, time) is one fire, not two.
        ident = (name, a.get("NewStateValue", ""), a.get("StateChangeTime", ""))
        if ident[2]:
            if ident in seen:
                continue
            seen.add(ident)
        entry = grouped[name]
        entry["count"] += 1
        if not entry["reason"]:
            entry["reason"] = a.get("NewStateReason", "")[:300]
        # Keep latest state-change so the digest reflects current state.
        sc = a.get("StateChangeTime", "")
        if sc > entry["last_state_change"]:
            entry["last_state_change"] = sc
            entry["last_state"] = a.get("NewStateValue", "")
    return dict(grouped)


def _format_age(since):
    """Human age of a standing red: '29d 4h', '7h 12m', '45m'."""
    if not isinstance(since, datetime):
        return "age unknown"
    if since.tzinfo is None:
        since = since.replace(tzinfo=timezone.utc)
    secs = max(0, int((datetime.now(timezone.utc) - since).total_seconds()))
    days, rem = divmod(secs, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def _fetch_standing_alarms():
    """#2827: one read-only describe-alarms sweep for everything currently in ALARM.

    Returns [{name, since, age, reason}] sorted oldest-red first. Fail-open by
    design: a CloudWatch error must never block the transition digest that
    already works, so any failure logs and returns [] (the section is simply
    absent that day — the Mon/Wed/Fri remediation agent remains the backstop).
    """
    standing = []
    try:
        params = {"StateValue": "ALARM", "AlarmTypes": ["CompositeAlarm", "MetricAlarm"]}
        while True:
            resp = cloudwatch.describe_alarms(**params)
            for a in list(resp.get("MetricAlarms", [])) + list(resp.get("CompositeAlarms", [])):
                since = a.get("StateTransitionedTimestamp") or a.get("StateUpdatedTimestamp")
                standing.append(
                    {
                        "name": a.get("AlarmName", "unknown"),
                        "since": since,
                        "age": _format_age(since),
                        "reason": (a.get("StateReason") or "")[:200],
                    }
                )
            token = resp.get("NextToken")
            if not token:
                break
            params["NextToken"] = token
    except Exception as e:  # noqa: BLE001 — deliberate fail-open, see docstring
        logger.error("standing_alarm_sweep_failed: %s", e)
        return []

    def _sort_key(s):
        since = s["since"]
        if not isinstance(since, datetime):
            return datetime.max.replace(tzinfo=timezone.utc)
        return since if since.tzinfo else since.replace(tzinfo=timezone.utc)

    standing.sort(key=_sort_key)
    return standing


def _format_email(grouped, standing=None):
    standing = standing or []
    today = pacific_today()
    distinct = len(grouped)
    total = sum(g["count"] for g in grouped.values())
    subject = f"[LP digest {today}] {distinct} alarm(s), {total} fire(s)"
    if standing:
        subject += f", {len(standing)} still red"

    lines = [
        f"Life Platform alarm digest — {today}",
        f"{distinct} distinct alarm(s), {total} total fire(s) in the last 24h.",
        "",
    ]
    if grouped:
        lines.append("Per-alarm summary (sorted by fire count):")
        lines.append("")
        for name, entry in sorted(grouped.items(), key=lambda kv: -kv[1]["count"]):
            lines.append(f"• {name}  ×{entry['count']}  [{entry['last_state'] or 'ALARM'}]")
            if entry["reason"]:
                lines.append(f"    {entry['reason']}")
            if entry["last_state_change"]:
                lines.append(f"    last state change: {entry['last_state_change']}")
            lines.append("")
    else:
        lines.append("No new alarm state transitions in the last 24h.")
        lines.append("")
    if standing:
        # #2827: re-surface every standing red daily — SNS only fires on
        # transitions, so without this section a long-red alarm is invisible
        # between Mon/Wed/Fri remediation-agent runs.
        lines.append(f"STILL IN ALARM ({len(standing)}) — standing reds, oldest first:")
        lines.append("")
        for s in standing:
            since_str = s["since"].strftime("%Y-%m-%d %H:%M UTC") if isinstance(s["since"], datetime) else "unknown"
            lines.append(f"• {s['name']}  red for {s['age']}  (since {since_str})")
            if s["reason"]:
                lines.append(f"    {s['reason']}")
            lines.append("")
        lines.append("A standing red stays in this section every day until it returns to OK.")
        lines.append("")
    lines.append("Urgent alarms still dispatch the remediation agent in real time, and the four")
    lines.append("paging alarms still text. Only owner actions (ADR-170) are emailed.")
    return subject, "\n".join(lines)


def _owner_items(grouped, standing, weekday):
    """ADR-170: the live entries only the owner can act on, one per action, newest cause first.

    A line counts when it fired in the window and is not back to OK, or — once a week, on
    STANDING_REMINDER_WEEKDAY — when it is still standing red from before.
    """
    items = {}
    for name, entry in grouped.items():
        action = owner_action_for(name)
        if action and entry.get("last_state") != "OK":
            items.setdefault(action.short, {"action": action, "signals": []})["signals"].append(
                f"{name} — {entry.get('reason') or 'no reason given'}"
            )
    if weekday == STANDING_REMINDER_WEEKDAY:
        for s in standing:
            action = owner_action_for(s["name"])
            if action and s["name"] not in grouped:
                items.setdefault(action.short, {"action": action, "signals": []})["signals"].append(
                    f"{s['name']} — still waiting on you, red for {s['age']}"
                )
    return list(items.values())


def _format_owner_email(items, grouped, standing):
    today = pacific_today()
    first = items[0]["action"].short
    subject = f"Do: {first}" + (f" (+{len(items) - 1} more)" if len(items) > 1 else "")
    lines = [f"Life Platform — what only you can do ({today})", ""]
    for i, item in enumerate(items, 1):
        a = item["action"]
        lines.append(f"{i}. {a.do}")
        lines.append(f"   Why you: {a.why_you}")
        for sig in item["signals"]:
            lines.append(f"   Signal: {sig[:300]}")
        lines.append("")
    owner_names = {n for n in grouped if owner_action_for(n)} | {s["name"] for s in standing if owner_action_for(s["name"])}
    others = len((set(grouped) | {s["name"] for s in standing}) - owner_names)
    if others:
        lines.append(
            f"Not for you: {others} other alarm(s) are with the remediation agent and the next Claude "
            "session (its pre-flight lists every red). Nothing to do about them here."
        )
    return subject, "\n".join(lines)


def lambda_handler(event: dict, context) -> dict:  # Phase 4.12 type hints
    dry_run = is_dry_run(event)
    try:
        alarms = _drain_queue()
        standing = _fetch_standing_alarms()  # #2827: read-only, fail-open
        if not alarms and not standing:
            logger.info("digest_empty")
            return {"statusCode": 200, "drained": 0, "standing": 0, "sent": False}

        grouped = _group_by_alarm(alarms)
        record_subject, record = _format_email(grouped, standing)
        # ADR-170: the full record is for sessions, not the inbox — log it whole.
        logger.info("digest_record %s\n%s", record_subject, record)

        weekday = datetime.strptime(pacific_today(), "%Y-%m-%d").weekday()
        items = _owner_items(grouped, standing, weekday)
        base = {"statusCode": 200, "drained": len(alarms), "distinct": len(grouped), "standing": len(standing)}
        if not items:
            logger.info("digest_no_owner_action drained=%d distinct=%d standing=%d", len(alarms), len(grouped), len(standing))
            return {**base, "owner_items": 0, "sent": False, "record_subject": record_subject, "record": record}
        subject, body = _format_owner_email(items, grouped, standing)

        guarded_send_email(
            ses,
            dry_run,
            FromEmailAddress=EMAIL_SENDER,
            Destination={"ToAddresses": [EMAIL_RECIPIENT]},
            Content={
                "Simple": {
                    "Subject": {"Data": subject, "Charset": "UTF-8"},
                    "Body": {"Text": {"Data": body, "Charset": "UTF-8"}},
                }
            },
        )
        logger.info("owner_action_sent items=%d drained=%d distinct=%d standing=%d", len(items), len(alarms), len(grouped), len(standing))
        return {**base, "owner_items": len(items), "sent": True, "record_subject": record_subject, "record": record}
    except Exception as e:
        logger.error("alert_digest_failed: %s", e)
        raise
