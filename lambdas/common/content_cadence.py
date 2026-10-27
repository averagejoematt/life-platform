"""content_cadence.py — pure cadence math for the chronicle + podcast "next
installment" line (#1972, epic #1890).

Root cause this fixes: no surface said WHEN the next chronicle/podcast
installment lands, even though the cadence is entirely cron-derivable — and no
API exposed the tier-pause-adjusted honest-pending variant either. This module
is the pure logic half; the AWS-facing shell (site-api's
``handle_content_cadence``, ``web/site_api_cadence.py``) reads the clock and
the budget tier and hands both to ``build_payload`` here.

Zero AWS/boto3 calls, zero ``datetime.now()`` calls — every function takes
``now`` as an explicit, timezone-aware argument, so this module is fully
unit-testable with a frozen clock (the wall-clock-fixture trap this
deliberately avoids: a hidden ``datetime.now()`` inside "pure" logic is a time
bomb the moment the test suite crosses whatever date is hard-coded in it).

Cron facts (read from source, not guessed):
  * ``wednesday-chronicle`` (lambdas/emails/wednesday_chronicle_lambda.py) is
    scheduled by its config/schedules.json row ``cron(0 8 ? * WED *)`` — every
    Wednesday, 8:00 AM Pacific wall clock (the table's platform_timezone, #4284 /
    ADR-165). If that row ever changes, this comment (and
    ``CHRONICLE_CRON_WEEKDAY``/``CHRONICLE_CRON_HOUR_PT`` below) go stale —
    tests/test_content_cadence_1972.py reads the row and asserts it still
    matches these constants.
  * ``wednesday_chronicle_lambda.py`` defaults ``PREVIEW_MODE=true`` — the
    Wednesday cron builds a DRAFT and emails Matthew an approval request; the
    actual publish-to-S3 only happens once he approves. So "the chronicle
    publishes every Wednesday" is NOT an unconditional promise. Every positive
    display string below is phrased around "drafted"/"due", never
    "publishes" — the exact class of promise-the-infra-won't-keep the
    growth-1 lesson warns about (docs/reviews/FULLREVIEW_2026-08-02_DELTA.md:
    /subscribe/ once promised a weekly email that was actually kill-switched
    for months).
  * "The Panel" podcast (lambdas/emails/coach_panel_podcast_lambda.py) lost
    its standing Friday cron in #734 — it is now event-driven, async-invoked
    by chronicle-approve only once a Chronicle installment actually
    publishes. It has **no independent cron** to derive a date from, so its
    cadence line is always phrased RELATIVE to the chronicle's own date
    (reusing the same ``next_date`` as "the week to watch", never claiming an
    independent schedule of its own).

Both surfaces share ONE budget_guard feature key, ``"chronicle"``
(lambdas/ai/budget_guard.py's ``_FEATURE_CUTOFF`` groups "the weekly
chronicle + Friday Panel podcast" under it, cutoff tier 2) — callers read
``budget_guard.allow("chronicle")`` once and pass the same ``allowed`` bool in
for both surfaces here.
"""

from datetime import date, datetime, time, timedelta
from typing import Dict, Optional

# Mirrors config/schedules.json's `wednesday-chronicle` row — Pacific wall clock (#4284, ADR-165).
CHRONICLE_CRON_LITERAL = "cron(0 8 ? * WED *)"
CHRONICLE_CRON_WEEKDAY = 2  # datetime.weekday(): Monday=0 .. Wednesday=2 .. Sunday=6
CHRONICLE_CRON_HOUR_PT = 8

# budget_guard._FEATURE_CUTOFF key shared by BOTH the chronicle and the podcast
# (ai/budget_guard.py: "the weekly Story installment + its Friday Panel podcast").
BUDGET_FEATURE = "chronicle"

_CHRONICLE_PAUSED_DISPLAY = (
    "The next Chronicle installment is paused — the platform's AI budget guard is "
    "protecting monthly spend. It resumes automatically once usage drops below the threshold."
)
_PODCAST_PAUSED_DISPLAY = (
    "The next Panel podcast episode is paused — it only ships once a Chronicle installment "
    "publishes, and generation is currently paused by the platform's AI budget guard. It "
    "resumes automatically once usage drops below the threshold."
)


def next_chronicle_draft_date(now: datetime) -> date:
    """The next Wednesday-08:00-Pacific schedule boundary at or after `now`.

    `now` MUST be timezone-aware (callers pass `datetime.now(timezone.utc)`).
    On the schedule's own Pacific weekday, a `now` strictly before 08:00 PT still
    counts that same Wednesday; at/after 08:00 PT it has already fired, so this
    rolls to the following Wednesday.
    """
    from common.pacific_time import PACIFIC

    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    now_pt = now.astimezone(PACIFIC)
    today = now_pt.date()
    days_ahead = (CHRONICLE_CRON_WEEKDAY - today.weekday()) % 7
    candidate = today + timedelta(days=days_ahead)
    if days_ahead == 0 and now_pt.time() >= time(CHRONICLE_CRON_HOUR_PT, 0):
        candidate = candidate + timedelta(days=7)
    return candidate


def _human_date(d: date) -> str:
    """'Wednesday, August 6' — no leading zero on the day (strftime %d pads)."""
    day = d.strftime("%d").lstrip("0") or "0"
    return f"{d.strftime('%A, %B')} {day}"


def build_payload(now: datetime, allowed: bool) -> Dict[str, Dict[str, Optional[object]]]:
    """Full cadence payload for BOTH surfaces. Pure — no datetime.now()/AWS
    calls; callers pass `now` and the already-read `allowed` bool
    (`budget_guard.allow("chronicle")`).

    Honest-pending (`allowed=False`): both payloads carry `paused: True`,
    `next_date: None` — NEVER a positive date claim alongside a pause. This is
    the anti-growth-1 guard: a payload that says both "paused" and "next
    Wednesday" would be exactly the dishonest-promise class #1972 exists to
    prevent.

    Positive (`allowed=True`): `next_date` is an ISO date (`next_chronicle_draft_date`).
    Chronicle phrases it as "drafted"/"due" (the PREVIEW_MODE nuance above — a
    draft, not an unconditional publish). Podcast REUSES the same date (it has
    no independent cron of its own) with display text that makes the
    dependency explicit — "the week to watch", conditional on that Chronicle
    installment actually shipping, never an independent claim.
    """
    if not allowed:
        return {
            "chronicle": {"paused": True, "next_date": None, "display": _CHRONICLE_PAUSED_DISPLAY},
            "podcast": {"paused": True, "next_date": None, "display": _PODCAST_PAUSED_DISPLAY},
        }
    next_date = next_chronicle_draft_date(now)
    iso = next_date.isoformat()
    human = _human_date(next_date)
    return {
        "chronicle": {
            "paused": False,
            "next_date": iso,
            "display": f"Next Chronicle installment drafted {human} — publishes once Matthew reviews and approves the draft.",
        },
        "podcast": {
            "paused": False,
            "next_date": iso,
            "display": (
                f"The Panel podcast ships the same week as the next Chronicle installment "
                f"(week of {human}), once that installment publishes — it has no schedule of its own."
            ),
        },
    }
