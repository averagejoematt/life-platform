"""coach/evening_checkin.py — the 20-second evening check-in (#5106, epic #5093).

WHAT IT CAPTURES. Three ratings and one word for the evening: ``hunger``, ``stress`` and ``cravings``,
each on the 0-4 scale the evening tools already use (``log_evening_intake``'s count and the felt probe
are both 0-4), plus ``word`` — one free word for the day. Nothing else: no meal, no number about the body.

THE CHANNELS (no new surface).
  * Telegram: the coach worker's scheduled ``{"kind": "evening_checkin"}`` run texts ONE fixed prompt at
    20:00 PDT / 19:00 PST (the UTC-fixed ``telegram-coach-worker#TelegramEveningCheckin`` row in
    config/schedules.json) from the nutrition coach's bot, or the lead's when that bot is dark. He answers
    with one line — ``2 3 1 tired`` — or ``/checkin 2 3 1 tired`` at any time. A bare reply is a check-in
    only on an evening whose prompt went out, and only in a 1:1 chat (never the board room). Deterministic:
    no model call, so no budget gate and no grounding gate apply.
  * MCP: ``log_evening_intake`` takes the same fields (Claude-side entry) through ``mcp_count`` / ``mcp_log`` ->
    ``write`` below; its input table is ``mcp/tools_descriptions.LOG_EVENING_INTAKE_INPUT``.

IDEMPOTENT PER DAY. One row per Pacific evening (``DATE#<day>``); a second answer overwrites the fields it
names in place and the reply says it updated (``ReturnValues=UPDATED_OLD``). A reply before 04:00 PT
belongs to the previous evening (``evening_day``), so a late answer never opens a second day.

THE PROMPT LEDGER + DEAD-MAN. ``COACH#evening_checkin`` holds ``PROMPT#<day>`` (a conditional put BEFORE
the send, so a double-fired rule texts once) and ``EVAL#<day>``, overwritten on EVERY scheduled run with
the verdict (``sent``, ``dark``, ``already_logged`` ...). ``nudge_ledger_qa.check_evening_checkin_liveness``
(the nightly qa-smoke) reds when a completed day has no ``EVAL#`` row: the rule stopped firing.

PRIVACY. Owner-only (``field_tiers.SOURCE_TIERS``). No ``lambdas/web`` or ``lambdas/emails`` module reads
the partition; ``tests/test_evening_checkin_5106.py`` holds that set.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping, Optional

logger = logging.getLogger(__name__)

VERSION = "evening-checkin@1.0.0"
SOURCE = "evening_checkin"
PK = f"USER#matthew#SOURCE#{SOURCE}"
LEDGER_PK = "COACH#evening_checkin"
PROMPT_PREFIX = "PROMPT#"
EVAL_PREFIX = "EVAL#"
FIELDS = ("hunger", "stress", "cravings")
SCALE_MIN, SCALE_MAX = 0, 4  # the 0-4 scale log_evening_intake and the felt probe already use
WORD_MAX_CHARS = 24
ROLLOVER_HOUR_PT = 4  # a reply before 04:00 PT belongs to the previous evening
# Who texts the prompt: the nutrition coach's bot, else the lead's (persona_registry.LEAD_PERSONA_ID), resolved by the worker's seat.
PROMPT_PERSONA = "nutrition_coach"
PROMPT_TEXT = "Evening check-in, 20 seconds: hunger, stress, cravings (0-4 each) and one word for today. Reply like: 2 3 1 tired"
USAGE_TEXT = "Check-in format: three numbers 0-4 (hunger, stress, cravings) and one word, e.g. /checkin 2 3 1 tired"

_COMMAND = "/checkin"
_REPLY_RE = re.compile(r"^([0-4])[\s,/]*([0-4])[\s,/]*([0-4])(?:[\s,.;:-]+([A-Za-z][A-Za-z'-]*))?[\s.!]*$")


def evening_day(now_pt: datetime) -> str:
    """The Pacific evening a moment belongs to: before ROLLOVER_HOUR_PT it is still last night."""
    return (now_pt - timedelta(hours=ROLLOVER_HOUR_PT)).date().isoformat()


def validate(values: Mapping[str, Any]) -> dict[str, Any]:
    """The check-in fields present in ``values``, checked: ints 0-4 and one word. ValueError on junk.

    Partial is allowed (the MCP path may log only stress); an empty result means no check-in field was given."""
    out: dict[str, Any] = {}
    for f in FIELDS:
        v = values.get(f)
        if v is None or v == "":
            continue
        try:
            n = int(v)
        except (TypeError, ValueError):
            n = None
        if n is None or isinstance(v, bool) or (isinstance(v, float) and v != n) or not SCALE_MIN <= n <= SCALE_MAX:
            raise ValueError(f"{f} must be an integer {SCALE_MIN}-{SCALE_MAX}")
        out[f] = n
    word = values.get("word")
    if word not in (None, ""):
        w = str(word).strip().lower()
        if not w or len(w) > WORD_MAX_CHARS or not re.fullmatch(r"[a-z][a-z'-]*", w):
            raise ValueError(f"word must be one word (letters only, up to {WORD_MAX_CHARS} characters)")
        out["word"] = w
    return out


def parse_reply(text: str) -> tuple[Optional[dict[str, Any]], bool]:
    """``(values or None, explicit)`` for one chat line. ``explicit`` = it began with /checkin."""
    t = (text or "").strip()
    explicit = t.lower().startswith(_COMMAND)
    if explicit:
        t = t[len(_COMMAND) :].strip()
    m = _REPLY_RE.match(t)
    if not m:
        return None, explicit
    values: dict[str, Any] = dict(zip(FIELDS, (int(m.group(i)) for i in (1, 2, 3))))
    if m.group(4) and len(m.group(4)) <= WORD_MAX_CHARS:
        values["word"] = m.group(4).lower()
    return values, explicit


def write(table, day: str, values: Mapping[str, Any], source: str, now_utc: Optional[datetime] = None) -> dict[str, Any]:
    """Overwrite the evening's row with the given fields (idempotent); report what it replaced."""
    clean = validate(values)
    if not clean:
        raise ValueError("no check-in field given (hunger, stress, cravings 0-4, word)")
    datetime.strptime(day, "%Y-%m-%d")  # a calendar-day key; raises on junk
    stamp = (now_utc or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    sets = {**clean, "source": source, "logged_at": stamp, "version": VERSION, "date": day}
    resp = table.update_item(
        Key={"pk": PK, "sk": f"DATE#{day}"},
        UpdateExpression="SET " + ", ".join(f"#{k} = :{k}" for k in sets),
        ExpressionAttributeNames={f"#{k}": k for k in sets},
        ExpressionAttributeValues={f":{k}": v for k, v in sets.items()},
        ReturnValues="UPDATED_OLD",
    )
    old = (resp or {}).get("Attributes") or {}
    previous = {k: (int(old[k]) if k in FIELDS else old[k]) for k in (*FIELDS, "word") if k in old}
    return {"logged": True, "date": day, **clean, "updated": bool(previous), "previous": previous or None, "private": True}


def mcp_count(args: Mapping[str, Any]) -> Optional[int]:
    """For MCP ``log_evening_intake``: the drinks count validated 0-4, or None when it is absent and a check-in field
    carries the call. Raises ValueError for a bad count, a bad check-in value, or a call with neither (nothing written)."""
    has_checkin = bool(validate(args))
    if args.get("count") is None and has_checkin:
        return None
    try:
        count = int(args.get("count"))
    except (TypeError, ValueError):
        raise ValueError("count is required (integer 0-4; 4 = four or more) unless hunger/stress/cravings/word is given")
    if not (0 <= count <= 4):
        raise ValueError("count must be between 0 and 4 (4 = four or more)")
    return count


def mcp_log(args: Mapping[str, Any], table, day: str) -> Optional[dict[str, Any]]:
    """For MCP ``log_evening_intake``: write the check-in fields in ``args`` (if any); None when the call carries none."""
    return write(table, day, args, "mcp") if validate(args) else None


def read_day(table, day: str) -> Optional[dict[str, Any]]:
    return table.get_item(Key={"pk": PK, "sk": f"DATE#{day}"}).get("Item")


def _prompt_row(table, day: str) -> Optional[dict[str, Any]]:
    return table.get_item(Key={"pk": LEDGER_PK, "sk": f"{PROMPT_PREFIX}{day}"}).get("Item")


def confirmation(result: Mapping[str, Any]) -> str:
    parts = ", ".join(f"{f} {result[f]}" for f in FIELDS if f in result)
    word = f", '{result['word']}'" if result.get("word") else ""
    verb = "Updated" if result.get("updated") else "Logged"
    return f"{verb} the check-in for {result['date']}: {parts}{word}."


def capture_reply(table, text: str, now_pt: datetime, *, is_group: bool = False) -> Optional[str]:
    """The reply line for a chat message that IS a check-in, or None (then the coach answers as usual).

    A bare ``2 3 1 tired`` counts only on an evening whose prompt was sent; ``/checkin ...`` counts any time.
    Never in a group chat. The regex runs first, so an ordinary message costs no read."""
    if is_group:
        return None
    values, explicit = parse_reply(text)
    if values is None:
        return USAGE_TEXT if explicit else None
    day = evening_day(now_pt)
    try:
        if not explicit and str((_prompt_row(table, day) or {}).get("status")) != "sent":
            return None
        return confirmation(write(table, day, values, "telegram"))
    except Exception as e:  # noqa: BLE001 — he must hear that it did not land, never a silent drop
        logger.warning("[evening-checkin] write failed: %s", type(e).__name__)
        return "That check-in did not save; try again in a minute, or log it in the Claude chat."


def _claim_prompt(table, day: str, now_utc: datetime) -> bool:
    try:
        table.put_item(
            Item={"pk": LEDGER_PK, "sk": f"{PROMPT_PREFIX}{day}", "status": "attempting", "attempted_at": now_utc.isoformat()},
            ConditionExpression="attribute_not_exists(pk)",
        )
        return True
    except Exception as e:  # noqa: BLE001 — ConditionalCheckFailed = already prompted today
        if "ConditionalCheckFailed" not in type(e).__name__ and "ConditionalCheckFailed" not in str(e):
            logger.warning("[evening-checkin] prompt claim failed (%s) — standing down", type(e).__name__)
        return False


def _stamp_eval(table, day: str, reason: str, now_utc: datetime) -> None:
    try:
        table.put_item(
            Item={"pk": LEDGER_PK, "sk": f"{EVAL_PREFIX}{day}", "reason": reason, "evaluated_at": now_utc.isoformat(), "version": VERSION}
        )
    except Exception as e:  # noqa: BLE001 — the stamp is the dead-man's food; never block the run
        logger.warning("[evening-checkin] eval stamp failed: %s", type(e).__name__)


def decide(table, day: str, now_pt: datetime, seat: Callable[[str], tuple]) -> tuple[str, Optional[tuple]]:
    """``(reason, (token, chat_id) or None)`` — whether tonight's prompt goes out, and through which bot."""
    from coach.coach_outbound import in_quiet_hours

    if in_quiet_hours(now_pt):
        return "quiet_hours", None
    row = read_day(table, day) or {}
    if all(row.get(f) is not None for f in FIELDS):
        return "already_logged", None
    from coach.persona_registry import LEAD_PERSONA_ID

    for persona in (PROMPT_PERSONA, LEAD_PERSONA_ID):
        token, chat = seat(persona)
        if token and chat is not None:
            return "send", (token, chat)
    return "dark", None


def run_prompt(table, now_pt: datetime, seat: Callable[[str], tuple], send: Callable[[str, Any, str], Any], now_utc=None) -> dict[str, Any]:
    """The scheduled evening run: decide, claim the day, send the one prompt, stamp the verdict (always)."""
    now_utc = now_utc or datetime.now(timezone.utc)
    day = now_pt.date().isoformat()
    try:
        reason, target = decide(table, day, now_pt, seat)
        if target is not None:
            if _claim_prompt(table, day, now_utc):
                send(target[0], target[1], PROMPT_TEXT)
                table.update_item(
                    Key={"pk": LEDGER_PK, "sk": f"{PROMPT_PREFIX}{day}"},
                    UpdateExpression="SET #s = :s, sent_at = :t",
                    ExpressionAttributeNames={"#s": "status"},
                    ExpressionAttributeValues={":s": "sent", ":t": now_utc.isoformat()},
                )
                reason = "sent"
            else:
                reason = "already_prompted"
    except Exception as e:  # noqa: BLE001 — the verdict still gets stamped, naming the failure class
        logger.warning("[evening-checkin] prompt run failed: %s", type(e).__name__)
        reason = f"error:{type(e).__name__}"
    _stamp_eval(table, day, reason, now_utc)
    logger.info("[evening-checkin] %s: %s", day, reason)
    return {"ok": not reason.startswith("error"), "reason": reason, "date": day}
