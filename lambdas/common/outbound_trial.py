"""common/outbound_trial.py — the owner's outbound-mail consolidation: ONE switchboard, every item ON and STANDING.

THE RULINGS. Owner, 2026-11-22 (section 9, "approved for trial", #6176): replace the Sunday Weekly Report and the
Monday Compass with one Sunday "what changed and what matters" email; fold the Friday Weekly Plate into the Saturday
Nutrition Review; stop emailing the AI Review Pack; pause the story-question and owner-words emails until their reply
path demonstrably works (#6174); stop the duplicate 20:00 email/Telegram check-in and suppress stale repetitive
prompts; route ordinary operational action mail toward the owner-actions registry (ADR-170) where that is safe.
Owner, 2026-11-23 (#6243): make the trial's changes permanent; do not let an expiry restore the suppressed mail; a
missing or invalid setting must not silently reactivate it; keep a safe rollback.

THE SWITCHBOARD. ``TRIAL`` is the one place each item is set, one reviewed line per item, and every item is ON (the
consolidated state). There is NO end date: nothing here reads a clock, so no day can turn an item off.

FAIL-SAFE DIRECTION: CONSOLIDATED. ``is_on`` reads an item as OFF (the old, louder behaviour) ONLY when its line is
exactly ``False``. A missing line, ``None``, ``0``, ``""``, ``"false"`` or any other value reads ON, so a typo or a
dropped line keeps the suppressed mail suppressed. The set of items is ``ITEMS`` (fixed here, not derived from
``TRIAL``), and asking about a name outside it raises: a misspelt item must never read as anything silently.

ROLLBACK, PER ITEM. Set that one item's line to ``False`` in a reviewed PR, then ``bash deploy/deploy_fleet.sh`` (and
``bash deploy/deploy_site_api.sh`` for the status page's wording). Only that item returns to its pre-#6176 behaviour;
the others stay consolidated (``tests/test_outbound_trial_6176.py`` pins both). Nothing here is read at runtime from
SSM or the environment: a committed switch is reviewed, diffable and the same in every Lambda of one deploy, which is
what lets a sender and its dead-man agree.

NOTHING IS DELETED. No schedule, function or CDK resource is touched. A sender whose send is suppressed still runs
on its own schedule and logs ONE line, ``[outbound-trial] {...}``, naming the item, the function and why — so a
suppressed send is a recognised state, never a silent failure, and ``scripts/owner_outbound_volume.py`` counts it.
(The module, item and log-tag names keep the word "trial": callers, tests and that script read them.)

WHAT IT NEVER TOUCHES. Subscriber mail (the Weekly Signal, chronicle installments, between-chronicle notes,
confirmation and onboarding), the Morning Brief, the chronicle preview/approval mail, the paging SMS, the
continuity switch, QA smoke and the ADR-170 owner-action digest. ``tests/test_outbound_trial_6176.py`` holds the set
of modules allowed to import this file.
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

#: 7. The scheduled evening Telegram prompt (``TelegramEveningCheckin``, 20:00 PT) does not send (owner ruling 2026-11-26,
#:    #6290: 29 prompts for one reply). A ``/checkin`` he sends himself still logs. Independent of item 5, which is the
#:    evening-nudge EMAIL's rule.
TELEGRAM_EVENING_PROMPT_HELD = "telegram_evening_prompt_held"
#: 8. The weekday Telegram morning check-in (``TelegramMorningCheckin``, 17:15Z Mon-Fri), the routine prompt for an
#:    answer that is re-asked until two go unanswered, does not send (#6290). The run stamps its outcome row as held.
TELEGRAM_MORNING_CHECKIN_HELD = "telegram_morning_checkin_held"

#: 9. The event-sweep lift-PR celebration (``coach_event_triggers.KIND_LIFT_PR``) does not send (owner ruling 2026-11-26,
#:    #6302): a PR congratulation reports a lift he logged himself. The candidate is neither claimed nor spent.
TELEGRAM_LIFT_PR_HELD = "telegram_lift_pr_held"
#: 10. The event-sweep milestone celebration does not send UNLESS it reports something he has not otherwise been told
#:     (``coach_event_triggers.milestone_is_untold``): a count of his own actions, or a milestone the milestone digest already
#:     mailed, is held; a measured milestone the digest has not delivered still sends (#6302).
TELEGRAM_MILESTONE_HELD = "telegram_milestone_held"
#: 11. The event-sweep tape / photo / DEXA due-day prompt (``calibration_prompt``) does not send: a calibration errand
#:     asked for the platform's benefit (#6302).
TELEGRAM_CALIBRATION_PROMPT_HELD = "telegram_calibration_prompt_held"
#: 12. The calibration dead-man's Telegram text for a missed LOG (tape / photos / battery) does not send. The
#:     ``calibration-deadman`` email alarm is untouched, and a row that names its own alert (the weekly titration's
#:     missed run: the platform's own failure) still sends (#6302).
TELEGRAM_CALIBRATION_DEADMAN_TEXT_HELD = "telegram_calibration_deadman_text_held"

#: Every item, fixed here — NOT derived from ``TRIAL``, so a line dropped from ``TRIAL`` still names a known item (and
#: reads ON, below) instead of raising in a sender.
ITEMS: tuple[str, ...] = (
    SUNDAY_WHAT_CHANGED,
    PLATE_INTO_NUTRITION_REVIEW,
    REVIEW_PACK_NOT_EMAILED,
    STORY_QUESTIONS_PAUSED,
    EVENING_ONE_CHANNEL,
    OPS_DLQ_SUMMARY,
    OPS_CANARY_ALARMED,
    OPS_MONDAY_PACK,
    TELEGRAM_EVENING_PROMPT_HELD,
    TELEGRAM_MORNING_CHECKIN_HELD,
    TELEGRAM_LIFT_PR_HELD,
    TELEGRAM_MILESTONE_HELD,
    TELEGRAM_CALIBRATION_PROMPT_HELD,
    TELEGRAM_CALIBRATION_DEADMAN_TEXT_HELD,
)

#: ON = consolidated (standing since #6243). Rollback of ONE item: that line → exactly ``False``.
TRIAL: dict[str, bool] = {
    SUNDAY_WHAT_CHANGED: True,
    PLATE_INTO_NUTRITION_REVIEW: True,
    REVIEW_PACK_NOT_EMAILED: True,
    STORY_QUESTIONS_PAUSED: True,
    EVENING_ONE_CHANNEL: True,
    OPS_DLQ_SUMMARY: True,
    OPS_CANARY_ALARMED: True,
    OPS_MONDAY_PACK: True,
    TELEGRAM_EVENING_PROMPT_HELD: True,
    TELEGRAM_MORNING_CHECKIN_HELD: True,
    TELEGRAM_LIFT_PR_HELD: True,
    TELEGRAM_MILESTONE_HELD: True,
    TELEGRAM_CALIBRATION_PROMPT_HELD: True,
    TELEGRAM_CALIBRATION_DEADMAN_TEXT_HELD: True,
}

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
    TELEGRAM_EVENING_PROMPT_HELD: "held by owner ruling 2026-11-26 (#6290): a routine prompt that went unanswered; not sent",
    TELEGRAM_MORNING_CHECKIN_HELD: "held by owner ruling 2026-11-26 (#6290): a routine check-in that re-asks after silence; not sent",
    TELEGRAM_LIFT_PR_HELD: "held by owner ruling 2026-11-26 (#6302): a PR congratulation on a lift he logged himself; not sent",
    TELEGRAM_MILESTONE_HELD: "held by owner ruling 2026-11-26 (#6302): a milestone congratulation he has already been told; not sent",
    TELEGRAM_CALIBRATION_PROMPT_HELD: "held by owner ruling 2026-11-26 (#6302): a calibration errand for the platform's benefit; not sent",
    TELEGRAM_CALIBRATION_DEADMAN_TEXT_HELD: "held by owner ruling 2026-11-26 (#6302): a missed-log nudge; the email alarm still carries it",
}

#: Status-page senders (``web/site_api_status._EMAIL_LAMBDAS`` ids) an item stops, with the item that stops them.
STATUS_PAGE_PAUSED: dict[str, str] = {
    "monday_compass": SUNDAY_WHAT_CHANGED,
    "weekly_plate": PLATE_INTO_NUTRITION_REVIEW,
}

LOG_TAG = "[outbound-trial]"

_log = logging.getLogger("outbound-trial")


def is_on(item: str) -> bool:
    """Whether ``item`` is consolidated (its old send held). ON unless its line is exactly ``False`` — see the docstring.

    An unknown item raises: a typo must never read as anything silently."""
    if item not in ITEMS:
        raise KeyError(f"unknown outbound-trial item {item!r}; known: {sorted(ITEMS)}")
    return TRIAL.get(item, True) is not False


def status_page_note(sender_id: str) -> Optional[str]:
    """The status page's comment for a sender the consolidation has paused, or None when it should be graded as usual."""
    item = STATUS_PAGE_PAUSED.get(sender_id)
    if item is None or not is_on(item):
        return None
    return f"Paused by the owner's email consolidation ({TRIAL_ISSUE}): {DESCRIPTIONS[item]}"


def suppressed(item: str, function: str, reason: str = "", *, log: Optional[Callable[[str], Any]] = None, **detail: Any) -> dict:
    """Log ONE line saying a send was suppressed by the consolidation, and why. Returns the record (callers return it).

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
    """Log ONE line for a send the consolidation itself makes (the Sunday email, a trimmed nudge) — counted beside the rest."""
    record = {"event": "sent", "item": item, "function": function, "issue": TRIAL_ISSUE}
    for k, v in detail.items():
        record[k] = v
    (log or _log.info)(f"{LOG_TAG} {json.dumps(record, default=str, sort_keys=True)}")
    return record
