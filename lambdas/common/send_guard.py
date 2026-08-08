"""Shared SES send-suppressor gate (#2222).

Every scheduled Lambda in ``lambdas/`` that sends mail through SES must be
invocable *without* actually mailing anyone, so that diagnosing a failed
scheduled run — or verifying a fix — never has "sends real mail to real
people" as a side effect. Two of the modules in that set mail third parties
(``milestone_digest_lambda`` mails the friends-and-family list,
``partner_email_lambda`` mails a partner address resolved from SSM), so the
gate is a safety property, not a convenience.

The convention is deliberately tiny and uniform:

    from common.send_guard import is_dry_run, guarded_send_email

    def lambda_handler(event, context):
        dry_run = is_dry_run(event)
        ...                       # build the whole email as normal
        guarded_send_email(ses, dry_run, Source=..., Destination=..., Message=...)

``guarded_send_email`` builds nothing and decides nothing — it is the last
inch before the wire. Under a dry run it logs what *would* have gone out and
returns a synthetic response, so callers that read ``["MessageId"]`` keep
working and the whole build path is still exercised.

**What lives where.** This module owns the *send* half only. What counts as a
dry run in the first place is `common.dry_run` — one vocabulary for sends and
writes alike, so `{"no_send": true}` cannot suppress the SES call in one Lambda
and be silently ignored by the write gate in another.
`tests/test_ses_send_guard_set_2222.py` pins that the two entry points can
never disagree.

The set is kept honest by that same file, which derives the member list from
source (AST) rather than from a hand-written list, and fails the day a 19th
SES-sending handler ships without a suppressor.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from common import dry_run as _dry_run

DRY_RUN_MESSAGE_ID = "dry-run-suppressed"


def is_dry_run(event: Optional[Any] = None) -> bool:
    """True when this invoke asked for a build-but-don't-send run.

    This module deliberately does NOT define its own answer — it delegates to
    `common.dry_run`, which is the single definition of what a dry run *is*
    (#2255/#2222). Two modules resolving the same flag with different
    vocabularies is how `{"no_send": true}` came to suppress 17 Lambdas while
    the daily brief ignored it and sent for real.

    `_dry_run.is_dry_run` reads the decision a handler already `stash()`ed on
    the event when there is one, so a send site can never reach a different
    verdict than the write gate that ran earlier in the same invocation.
    """
    return _dry_run.is_dry_run(event)


def _describe(kwargs: Mapping[str, Any]) -> str:
    """Best-effort one-line description of a send, for the dry-run log."""
    destination = kwargs.get("Destination") or {}
    recipients: list[str] = []
    if isinstance(destination, Mapping):
        for field in ("ToAddresses", "CcAddresses", "BccAddresses"):
            value = destination.get(field)
            if isinstance(value, (list, tuple)):
                recipients.extend(str(v) for v in value)

    subject = ""
    message = kwargs.get("Message")
    if isinstance(message, Mapping):
        # SES v1: Message.Subject.Data
        subject_block = message.get("Subject")
        if isinstance(subject_block, Mapping):
            subject = str(subject_block.get("Data", ""))
    content = kwargs.get("Content")
    if not subject and isinstance(content, Mapping):
        # SES v2: Content.Simple.Subject.Data
        simple = content.get("Simple")
        if isinstance(simple, Mapping):
            subject_block = simple.get("Subject")
            if isinstance(subject_block, Mapping):
                subject = str(subject_block.get("Data", ""))

    return f"to={recipients or ['<unknown>']} subject={subject!r}"


def guarded_send_email(ses_client: Any, dry_run: bool, **kwargs: Any) -> dict:
    """``ses_client.send_email(**kwargs)`` unless ``dry_run`` is set.

    Works for both the SES v1 (``Message``) and SES v2 (``Content``) call
    shapes — the kwargs are passed through untouched.
    """
    if dry_run:
        print(f"[DRY-RUN] SES send suppressed — {_describe(kwargs)}")
        return {"MessageId": DRY_RUN_MESSAGE_ID, "dry_run": True}
    return ses_client.send_email(**kwargs)


def guarded_send_raw_email(ses_client: Any, dry_run: bool, **kwargs: Any) -> dict:
    """``ses_client.send_raw_email(**kwargs)`` unless ``dry_run`` is set."""
    if dry_run:
        destinations = kwargs.get("Destinations") or ["<unknown>"]
        print(f"[DRY-RUN] SES raw send suppressed — to={destinations}")
        return {"MessageId": DRY_RUN_MESSAGE_ID, "dry_run": True}
    return ses_client.send_raw_email(**kwargs)
