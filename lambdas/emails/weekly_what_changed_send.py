"""emails/weekly_what_changed_send.py — the Sunday slot's trial send (#6176, item 1), beside the weekly digest.

While the outbound trial's ``SUNDAY_WHAT_CHANGED`` item is on, ``weekly_digest_lambda.lambda_handler`` hands its
Sunday slot here instead of building the Weekly Report: the same ``gather_all`` read, the same recipient, the same
replay ledger (so it never goes out twice in a week, and a mid-week rollback finds the week already recorded), and
no model call. The render is ``emails.sunday_what_changed``; the advice status is ``emails.advice_status``.

It lives beside the digest rather than inside it so the digest does not grow past its module-size baseline (#1665).
Every dependency the digest owns (its table, SES client, gather and ledger write) is passed in.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Optional

from common import outbound_trial
from common.constants import EXPERIMENT_START_DATE
from common.send_guard import guarded_send_email

from emails import advice_status, sunday_what_changed


def week_number(this_end: str) -> Optional[int]:
    """The experiment week ``this_end`` falls in (1-based), or None before genesis / on a bad date."""
    try:
        days = (datetime.strptime(this_end, "%Y-%m-%d").date() - datetime.strptime(EXPERIMENT_START_DATE, "%Y-%m-%d").date()).days
    except (TypeError, ValueError):
        return None
    return days // 7 + 1 if days >= 0 else None


def build(data: dict, *, table: Any, user_id: str) -> dict:
    """The Sunday email from ``gather_all``'s data dict (no send)."""
    dates = data["dates"]
    advice = advice_status.read(table, user_id, dates["this_start"], dates["this_end"], dates["prior_start"], dates["prior_end"])
    return sunday_what_changed.build(data, advice, week_number=week_number(dates["this_end"]))


def send(
    dry_run: bool,
    period_key: str,
    *,
    gather: Callable[[], Any],
    table: Any,
    ses: Any,
    sender: str,
    recipient: str,
    user_id: str,
    record: Callable[[Any, str, str], Any],
    ledger_name: str,
    log: Callable[[str], Any],
) -> dict:
    """Send the one Sunday email in the Weekly Report's slot. Returns the Lambda response."""
    log("[#6176] outbound trial: the Sunday slot sends 'what changed and what matters', not the Weekly Report")
    result = gather()
    if result is None or result[0] is None:
        return {"statusCode": 500, "body": "Failed to gather data"}
    email = build(result[0], table=table, user_id=user_id)
    guarded_send_email(
        ses,
        dry_run,
        FromEmailAddress=sender,
        Destination={"ToAddresses": [recipient]},
        Content={
            "Simple": {
                "Subject": {"Data": email["subject"], "Charset": "UTF-8"},
                "Body": {
                    "Text": {"Data": email["text"], "Charset": "UTF-8"},
                    "Html": {"Data": email["html"], "Charset": "UTF-8"},
                },
            }
        },
        ConfigurationSetName="life-platform-emails",
        EmailTags=[{"Name": "message_type", "Value": "weekly_what_changed"}],
    )
    if not dry_run:
        record(table, ledger_name, period_key)
    outbound_trial.sent(outbound_trial.SUNDAY_WHAT_CHANGED, "weekly-digest", log=log, dry_run=bool(dry_run), subject=email["subject"])
    log("DRY_RUN, not sent." if dry_run else f"Sent (what changed): {email['subject']}")
    return {"statusCode": 200, "body": "What-changed email generated (DRY_RUN, not sent)." if dry_run else "What-changed email sent."}
