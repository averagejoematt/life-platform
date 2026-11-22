"""common/outbound_trial.py — the owner's two-week outbound-mail trial: ONE switchboard, every item OFF (#6176).

THE RULING (owner, 2026-11-22, section 9, "approved for trial"). Replace the Sunday Weekly Report and the Monday
Compass with one Sunday "what changed and what matters" email; fold the Friday Weekly Plate into the Saturday
Nutrition Review; stop emailing the AI Review Pack; pause the story-question and owner-words emails until their reply
path demonstrably works (#6174); stop the duplicate 20:00 email/Telegram check-in and suppress stale repetitive
prompts; route ordinary operational action mail toward the owner-actions registry (ADR-170) where that is safe.
Preserve urgent alerts and every subscriber commitment. Keep the trial reversible.

THE SWITCHBOARD. ``TRIAL`` is the one place each item is turned on or off, one reviewed line per item. Every item
defaults OFF, and OFF is today's behaviour exactly (``tests/test_outbound_trial_6176.py`` pins both). Turning an
item on, or rolling one back alone, is one line here plus the fleet deploy (and the site-api deploy for the status
page's wording). Nothing here is read at runtime from SSM: a committed switch is reviewed, diffable and the same in
every Lambda of one deploy, which is what lets the sender and its dead-man agree.

``TRIAL_ENDS_ON`` (optional, a Pacific ``YYYY-MM-DD``): from that day every item reads OFF again with no further
change, so a trial nobody remembers to end ends itself and the inbox returns to today's behaviour.

NOTHING IS DELETED. No schedule, function or CDK resource is touched. A sender whose send is suppressed still runs
on its own schedule and logs ONE line, ``[outbound-trial] {...}``, naming the item, the function and why — so a
suppressed send is a recognised state, never a silent failure, and ``scripts/owner_outbound_volume.py`` counts it.

WHAT IT NEVER TOUCHES. Subscriber mail (the Weekly Signal, chronicle installments, between-chronicle notes,
confirmation and onboarding), the Morning Brief, the chronicle preview/approval mail, the paging SMS, the
continuity switch and the ADR-170 owner-action digest. ``tests/test_outbound_trial_6176.py`` holds the set of
modules allowed to import this file.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Optional

TRIAL_ISSUE = "#6176"

# ── the items ─────────────────────────────────────────────────────────────────────────────────
#: 1. The Sunday weekly-digest slot sends the "what changed and what matters" email instead of the Weekly Report,
#:    and the Monday Compass does not send.
SUNDAY_WHAT_CHANGED = "sunday_what_changed"
#: 2. The Friday Weekly Plate does not send; its most-logged-foods section rides the Saturday Nutrition Review.
PLATE_INTO_NUTRITION_REVIEW = "plate_into_nutrition_review"
#: 3. The AI Review Pack is still built every Sunday and written to its own log group; it is not emailed.
REVIEW_PACK_NOT_EMAILED = "review_pack_not_emailed"
#: 4. The Monday story questions and the Tuesday owner-words question are not generated or sent (#6174).
STORY_QUESTIONS_PAUSED = "story_questions_paused"
#: 5. The 20:00 check-in has ONE channel — the evening-nudge email — and drops items unlogged for 14+ days.
EVENING_ONE_CHANNEL = "evening_one_channel"
#: 6a. The DLQ escalation's SES summary is not sent when its SNS escalation (already in the digest) went out.
OPS_DLQ_SUMMARY = "ops_dlq_summary"
#: 6b. A canary failure that a declared CloudWatch alarm already carries to the digest is not also emailed.
OPS_CANARY_ALARMED = "ops_canary_alarmed"
#: 6c. The Monday ops pack is written to its log group as a record, not emailed.
OPS_MONDAY_PACK = "ops_monday_pack"

TRIAL: dict[str, bool] = {
    SUNDAY_WHAT_CHANGED: False,
    PLATE_INTO_NUTRITION_REVIEW: False,
    REVIEW_PACK_NOT_EMAILED: False,
    STORY_QUESTIONS_PAUSED: False,
    EVENING_ONE_CHANNEL: False,
    OPS_DLQ_SUMMARY: False,
    OPS_CANARY_ALARMED: False,
    OPS_MONDAY_PACK: False,
}

#: The first Pacific day on which every item reads OFF again (None = no end date).
TRIAL_ENDS_ON: Optional[str] = None

#: Plain-language description per item — the status page note and the suppression log both use it.
DESCRIPTIONS: dict[str, str] = {
    SUNDAY_WHAT_CHANGED: "replaced by the Sunday 'what changed and what matters' email",
    PLATE_INTO_NUTRITION_REVIEW: "folded into the Saturday Nutrition Review",
    REVIEW_PACK_NOT_EMAILED: "built and logged for a working session, not emailed",
    STORY_QUESTIONS_PAUSED: "paused until a reply to it is proven to arrive (#6174)",
    EVENING_ONE_CHANNEL: "the 20:00 check-in has one channel: the evening-nudge email",
    OPS_DLQ_SUMMARY: "the SNS escalation already carries it to the daily digest record",
    OPS_CANARY_ALARMED: "a declared CloudWatch alarm already carries it to the daily digest record",
    OPS_MONDAY_PACK: "written to its log group as a record for a working session",
}

#: Status-page senders (``web/site_api_status._EMAIL_LAMBDAS`` ids) an item stops, with the item that stops them.
STATUS_PAGE_PAUSED: dict[str, str] = {
    "monday_compass": SUNDAY_WHAT_CHANGED,
    "weekly_plate": PLATE_INTO_NUTRITION_REVIEW,
}

LOG_TAG = "[outbound-trial]"

_log = logging.getLogger("outbound-trial")


def _today_pt() -> str:
    from common.pacific_time import pacific_today

    return pacific_today()


def trial_ended(today: Optional[str] = None) -> bool:
    """True once ``TRIAL_ENDS_ON`` is set and today (Pacific) is on or after it."""
    if not TRIAL_ENDS_ON:
        return False
    return (today or _today_pt()) >= TRIAL_ENDS_ON


def is_on(item: str, today: Optional[str] = None) -> bool:
    """Whether trial ``item`` is in force. An unknown item raises: a typo must never read as 'off' silently."""
    if item not in TRIAL:
        raise KeyError(f"unknown outbound-trial item {item!r}; known: {sorted(TRIAL)}")
    if not TRIAL[item]:
        return False
    return not trial_ended(today)


def status_page_note(sender_id: str, today: Optional[str] = None) -> Optional[str]:
    """The status page's comment for a sender the trial has paused, or None when it should be graded as usual."""
    item = STATUS_PAGE_PAUSED.get(sender_id)
    if item is None or not is_on(item, today):
        return None
    return f"Paused during a two-week email trial ({TRIAL_ISSUE}): {DESCRIPTIONS[item]}"


def suppressed(item: str, function: str, reason: str = "", *, log: Optional[Callable[[str], Any]] = None, **detail: Any) -> dict:
    """Log ONE line saying a send was suppressed by the trial, and why. Returns the record (callers return it).

    The line is ``[outbound-trial] {json}`` with ``event: suppressed`` — the shape the measurement script counts.
    """
    record = {
        "event": "suppressed",
        "item": item,
        "function": function,
        "reason": reason or DESCRIPTIONS.get(item, ""),
        "issue": TRIAL_ISSUE,
    }
    for k, v in detail.items():
        record[k] = v
    line = f"{LOG_TAG} {json.dumps(record, default=str, sort_keys=True)}"
    (log or _log.info)(line)
    return record


def sent(item: str, function: str, *, log: Optional[Callable[[str], Any]] = None, **detail: Any) -> dict:
    """Log ONE line for a send the trial itself makes (the Sunday email, a trimmed nudge) — counted beside the rest."""
    record = {"event": "sent", "item": item, "function": function, "issue": TRIAL_ISSUE}
    for k, v in detail.items():
        record[k] = v
    (log or _log.info)(f"{LOG_TAG} {json.dumps(record, default=str, sort_keys=True)}")
    return record
