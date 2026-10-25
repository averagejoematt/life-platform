"""coach/support_contact_prompts.py — the support contact's two OWNER-side prompts (#5125, epic #5120).

THE RULINGS (owner, 2026-10-23, #5125): R1 name a support person (stored privately, never in the repo), R3 arm the
7-day silence alert with them, R5 rebuild the weekly partner email on check-in data. The acceptance box this module
builds is the one those rulings left open: "a weekly check-in prompt and a pre-agreed disruption call are defined
for the contact".

TWO PROMPTS, BOTH TO HIM — NEVER TO THE CONTACT.

  1. THE WEEKLY CHECK-IN PROMPT. Once per ISO week, on ``WEEKLY_PROMPT_WEEKDAY`` or later in that week, one plain
     text: "have you checked in with your support person this week?". Idempotent on
     ``SUPPORT_CHECKIN#<Monday of the ISO week>``.
  2. THE PRE-AGREED DISRUPTION CALL. When the relapse early-warning flag (#5121, the owner-only
     ``early_warning_flag`` partition) has been up for ``CALL_AFTER_DAYS`` days, or disruption mode (#5088, his own
     ``MODE#disruption#`` record) has been active that long, one plain text reminds HIM to make the call he agreed
     with his support person. One per episode: ``SUPPORT_CALL#early_warning#<episode start>`` /
     ``SUPPORT_CALL#disruption#<record start_date>``. Both due on the same run → ONE text naming both.

THE CADENCE NUMBERS ARE DEFAULTS. ``WEEKLY_PROMPT_WEEKDAY`` (Sunday — the partner email's day) and
``CALL_AFTER_DAYS`` (3) carry no owner ruling yet. They are platform defaults pending his word on #5125, stated
here and in the PR, never presented as his.

THE PLATFORM NEVER CALLS THE CONTACT FROM HERE. The only path that reaches the support person is
``coach.named_human_contact`` — the 7-day all-channel silence alert, armed by owner ruling R3 — and this module
neither imports it nor reads its private config. The prompts say "your support person": the name and address live
only in the private S3 object ``config/coaching/named_human.json``, which this module never reads (the Telegram
worker's role has no grant on it, and none is added). So the contact's identity cannot reach this text, the worker's
logs or the event ledger. ``tests/test_support_contact_prompts_5125.py`` holds that structurally.

THE DELIVERY. A plain, fixed-text Telegram message from the program lead's PRIVATE 1:1 seat (the same transport as
``coach.calibration_deadman_alert``), sent from the worker's 16:00Z ``event_outbound`` run, ahead of the AI sweep.
No model call, so it is sent at ANY budget tier and costs $0. It respects quiet hours; it does not spend the daily
coaching cap or stand down on "two ignored" — a reminder to make a call that stood down because he ignored two
coaching pings would be the silence it exists to break. Claim-then-send on the write-once event ledger: a crash
between the two never licenses a second text; a failed send logs ``SUPPORT_PROMPT_TELEGRAM_FAILED``.

Dates and counts only in the texts — never a marker's evidence, a reading or his words (the early-warning evidence
stays on the flag row; the mind coach owns that conversation, #5126).

Fail-soft: an unreadable partition is "not active" (no reminder), never a guessed one. Never raises.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any, Callable, Mapping, Optional

logger = logging.getLogger(__name__)

ISSUE = "#5125"
PERSONA = "eli_marsh"  # the program lead's private seat (coach_event_triggers.LEAD_OWNER) — owner-only by construction

# ── The cadence (DEFAULTS — no owner ruling yet; pending his word on #5125) ──────────────────────────
WEEKLY_PROMPT_WEEKDAY = 6  # DEFAULT: Sunday (date.weekday(); Monday = 0) — the weekly partner email's day
CALL_AFTER_DAYS = 3  # DEFAULT: days the flag / the mode has been up before the pre-agreed call is due
FLAG_FRESH_DAYS = 2  # a flag whose newest row is older than this is not read as up (a stalled writer is not a signal)
FLAG_LOOKBACK_DAYS = 30

FLAG_PK = "USER#matthew#SOURCE#early_warning_flag"  # #5121's owner-only partition (health.early_warning.SOURCE)

TRIGGER_EARLY_WARNING = "early_warning"
TRIGGER_DISRUPTION = "disruption"

WEEKLY_PREFIX = "SUPPORT_CHECKIN#"
CALL_PREFIX = "SUPPORT_CALL#"
FAILED_TOKEN = "SUPPORT_PROMPT_TELEGRAM_FAILED"  # noqa: S105 — a log token, not a credential

WEEKLY_TEXT = (
    "Weekly check-in: have you checked in with your support person this week? "
    "A message or a short call is enough. (Only you see this; nothing was sent to them.)"
)
_TRIGGER_WORDS = {
    TRIGGER_EARLY_WARNING: "the early-warning flag has been up since {start} ({days} days)",
    TRIGGER_DISRUPTION: "disruption mode has been on since {start} ({days} days)",
}
CALL_CLOSER = (
    "This is the point you agreed to call your support person. Make the call today: a call, not a text. "
    "The platform has not contacted them and will not; the only thing that ever reaches them is the "
    "silence alert you armed."
)


# ── Pure ─────────────────────────────────────────────────────────────────────────────────────────────
def _day(v: Any) -> Optional[date]:
    try:
        return datetime.strptime(str(v)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def week_key(today: str) -> Optional[str]:
    """The ISO week's Monday for `today` (the weekly prompt's idempotency key), or None."""
    d = _day(today)
    return (d - timedelta(days=d.weekday())).isoformat() if d else None


def weekly_due(today: str, weekday: int = WEEKLY_PROMPT_WEEKDAY) -> Optional[dict[str, str]]:
    """{event_id, text} when the weekly prompt is due on `today` (its weekday or later in the ISO week), else None."""
    d = _day(today)
    if d is None or d.weekday() < weekday:
        return None
    return {"event_id": f"{WEEKLY_PREFIX}{week_key(today)}", "text": WEEKLY_TEXT}


def flag_episode(rows: Optional[list], today: str, fresh_days: int = FLAG_FRESH_DAYS) -> Optional[dict[str, Any]]:
    """The current early-warning episode — {start, latest} — when the newest row is active and fresh, else None.

    The episode rule is #5121's own (``health.early_warning.episode``: a day with no row does not end an episode, an
    explicit inactive row does) — imported, never restated. This module adds only two input bars: ``active`` counts
    only as a real ``True`` (a string or a number is read as not up — a reminder never rides a malformed row), and
    a newest row older than ``fresh_days`` is a stalled writer, not a signal."""
    from health import early_warning

    t = _day(today)
    ep = early_warning.episode([{**r, "active": r.get("active") is True} for r in rows or []])
    if t is None or ep is None:
        return None
    latest = _day(ep["latest"])
    if latest is None or (t - latest).days > fresh_days:
        return None
    return {"start": ep["start"], "latest": ep["latest"]}


def _days_up(start: Optional[str], today: str) -> Optional[int]:
    s, t = _day(start), _day(today)
    return (t - s).days + 1 if s and t and s <= t else None


def calls_due(
    today: str,
    *,
    flag_rows: Optional[list] = None,
    disruption_state: Optional[Mapping[str, Any]] = None,
    after_days: int = CALL_AFTER_DAYS,
) -> list[dict[str, Any]]:
    """[{trigger, start, days, event_id}] for every trigger up for at least `after_days` days. Pure."""
    out = []
    ep = flag_episode(flag_rows, today)
    if ep:
        n = _days_up(ep["start"], today)
        if n is not None and n >= after_days:
            out.append({"trigger": TRIGGER_EARLY_WARNING, "start": ep["start"], "days": n})
    st = disruption_state or {}
    if st.get("phase") == "active":  # training.disruption.PHASE_ACTIVE (step-back-up is the way OUT, not a disruption)
        start = str(st.get("start_date") or "")[:10]
        n = _days_up(start, today)
        if n is not None and n >= after_days:
            out.append({"trigger": TRIGGER_DISRUPTION, "start": start, "days": n})
    for c in out:
        c["event_id"] = f"{CALL_PREFIX}{c['trigger']}#{c['start']}"
    return out


def call_text(due: list[Mapping[str, Any]]) -> str:
    """The one fixed-template text for the call(s) due tonight. Dates and day counts only."""
    reasons = " and ".join(_TRIGGER_WORDS[c["trigger"]].format(start=c["start"], days=c["days"]) for c in due)
    return f"Pre-agreed call: {reasons}. {CALL_CLOSER}"


# ── I/O (injected table; every read fails soft to "not active") ──────────────────────────────────────
def read_flag_rows(table: Any, today: str, days: int = FLAG_LOOKBACK_DAYS) -> list:
    """The flag rows of the last `days` days, current cycle only ([] on any failure — no reminder, never a guess)."""
    t = _day(today)
    if t is None:
        return []
    try:
        from experiment.phase_filter import with_phase_filter

        kwargs = {
            "KeyConditionExpression": "pk = :pk AND sk BETWEEN :lo AND :hi",
            "ExpressionAttributeValues": {
                ":pk": FLAG_PK,
                ":lo": f"DATE#{(t - timedelta(days=days - 1)).isoformat()}",
                ":hi": f"DATE#{today}~",
            },
            "ProjectionExpression": "sk, #d, active",
            "ExpressionAttributeNames": {"#d": "date"},
        }
        return list(table.query(**with_phase_filter(kwargs)).get("Items") or [])
    except Exception as e:  # noqa: BLE001
        logger.warning("[support-prompts] early-warning flag read failed (%s) — read as not up", type(e).__name__)
        return []


def read_disruption_state(table: Any, today: str) -> dict[str, Any]:
    """`training.disruption.state` over his records ({"phase": "off"} on any failure)."""
    try:
        from training import disruption

        items: list = []
        kwargs: dict[str, Any] = {
            "KeyConditionExpression": "pk = :pk AND begins_with(sk, :pfx)",
            "ExpressionAttributeValues": {":pk": disruption.DISRUPTION_PK, ":pfx": disruption.DISRUPTION_SK_PREFIX},
        }
        while True:
            resp = table.query(**kwargs)
            items.extend(resp.get("Items") or [])
            if "LastEvaluatedKey" not in resp:
                break
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
        return dict(disruption.state(items, today))
    except Exception as e:  # noqa: BLE001
        logger.warning("[support-prompts] disruption record read failed (%s) — read as off", type(e).__name__)
        return {"phase": "off"}


# ── The run ──────────────────────────────────────────────────────────────────────────────────────────
def _claim(table: Any, event_id: str) -> bool:
    from coach import coach_outbound

    return coach_outbound.claim_event(table, event_id)


def _send(send: Callable, token: str, chat_id: Any, text: str, label: str, event_ids: list[str]) -> bool:
    """One plain text. True = sent; a failure is logged loudly, never raised."""
    try:
        send(token, chat_id, text)
    except Exception as e:  # noqa: BLE001
        logger.warning("[support-prompts] %s %s (%s)", FAILED_TOKEN, label, type(e).__name__)
        return False
    logger.info("[support-prompts] sent %s events=%s", label, ",".join(event_ids))
    return True


def run(
    table: Any,
    now_pt: Any,
    seat: Callable[[str], tuple],
    send: Callable[[str, Any, str], Any],
    *,
    flag_rows: Optional[list] = None,
    disruption_state: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Send tonight's weekly prompt and/or disruption-call reminder to HIM. Never raises; the result is identity-free.

    `seat(persona) -> (token, chat_id)` and `send(token, chat_id, text)` are the worker's transport (injected).
    `flag_rows` / `disruption_state` default to the table reads above."""
    try:
        from coach import coach_outbound

        if coach_outbound.in_quiet_hours(now_pt):
            return {"reason": "quiet hours", "sent": []}
        today = now_pt.strftime("%Y-%m-%d")
        weekly = weekly_due(today)
        rows = read_flag_rows(table, today) if flag_rows is None else flag_rows
        st = read_disruption_state(table, today) if disruption_state is None else disruption_state
        calls = calls_due(today, flag_rows=rows, disruption_state=st)
        if not weekly and not calls:
            return {"reason": "none due", "sent": []}
        token, chat_id = seat(PERSONA)
        if not token or chat_id is None:
            logger.warning("[support-prompts] prompt(s) due but the lead's seat is dark — nothing sent")
            return {"reason": "dark", "sent": [], "due": (["weekly"] if weekly else []) + [c["trigger"] for c in calls]}
        sent = []
        # Claim-then-send: a call already reminded this episode (or an unreadable ledger) is never re-sent, and the
        # text names only the triggers whose claim is new.
        fresh = [c for c in calls if _claim(table, c["event_id"])]
        if fresh and _send(send, token, chat_id, call_text(fresh), "call", [c["event_id"] for c in fresh]):
            sent += [c["trigger"] for c in fresh]
        if weekly and _claim(table, weekly["event_id"]) and _send(send, token, chat_id, weekly["text"], "weekly", [weekly["event_id"]]):
            sent.append("weekly")
        return {"reason": "sent" if sent else "already sent", "sent": sent}
    except Exception as e:  # noqa: BLE001 — never break the sweep that hosts it
        logger.warning("[support-prompts] %s run failed (%s)", FAILED_TOKEN, type(e).__name__)
        return {"reason": "failed", "sent": []}
