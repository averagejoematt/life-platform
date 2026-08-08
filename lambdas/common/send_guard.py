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

The set is kept honest by ``tests/test_ses_send_guard_set.py``, which derives
the member list from source (AST) rather than from a hand-written list, and
fails the day a 19th SES-sending handler ships without a suppressor.
"""

from __future__ import annotations

import os
from typing import Any, Mapping, Optional

# Event keys that request a build-but-do-not-send run. ``dryRun`` is accepted
# because a hand-typed console invoke is as likely to camelCase it.
SUPPRESSOR_EVENT_KEYS = ("dry_run", "dryRun", "no_send", "preview_mode", "test_mode")

# Environment variables with the same meaning, for the modules whose trigger
# payload is not under an operator's control (EventBridge scheduled rules).
SUPPRESSOR_ENV_VARS = ("DRY_RUN", "NO_SEND", "PREVIEW_MODE", "TEST_MODE")

_FALSEY_STRINGS = {"", "0", "false", "no", "off", "none"}

DRY_RUN_MESSAGE_ID = "dry-run-suppressed"


def _truthy(value: Any) -> bool:
    """Truthiness with string semantics — ``"false"``/``"0"`` are False."""
    if isinstance(value, str):
        return value.strip().lower() not in _FALSEY_STRINGS
    return bool(value)


def is_dry_run(event: Optional[Any] = None, env: Optional[Mapping[str, str]] = None) -> bool:
    """True when this invoke asked for a build-but-don't-send run.

    Checks the event payload first (``{"dry_run": true}`` and its aliases),
    then the environment. Anything that is not a mapping is ignored rather
    than raising — an S3/SES record list is a legitimate event shape.
    """
    if isinstance(event, Mapping):
        for key in SUPPRESSOR_EVENT_KEYS:
            if key in event and _truthy(event[key]):
                return True
        # A scheduled rule can carry the flag one level down in a wrapper.
        detail = event.get("detail")
        if isinstance(detail, Mapping):
            for key in SUPPRESSOR_EVENT_KEYS:
                if key in detail and _truthy(detail[key]):
                    return True

    environ = os.environ if env is None else env
    for name in SUPPRESSOR_ENV_VARS:
        if _truthy(environ.get(name, "")):
            return True
    return False


def _describe(kwargs: Mapping[str, Any]) -> str:
    """Best-effort one-line description of a send, for the dry-run log."""
    destination = kwargs.get("Destination") or {}
    recipients = []
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
