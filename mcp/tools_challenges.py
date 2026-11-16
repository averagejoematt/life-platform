"""tools_challenges.py — the OWNER's challenge check-in (#6087).

``log_challenge_checkin`` is the only writer of ``daily_checkins`` on Matthew's own challenge rows
(``USER#matthew#SOURCE#challenges`` / ``CHALLENGE#<id>``). Before #6087 the only writer was the
anonymous ``POST /api/challenge_checkin``, so the owner's check-ins and a stranger's were the same
write. The public door now writes a separate reader partition and the Site API role has no write
grant on this one; the owner's path is this MCP tool, authenticated as the owner by the MCP door.

The write is a same-date replace (one entry per day — the owner correcting a day is the point), done
as an optimistic, version-conditioned update: it reads the row, builds the new list and writes it only
if ``checkin_rev`` is still the value it read. A concurrent second write fails the condition and is
retried on a fresh read, so no update is ever lost.
"""

import re

from common.challenge_checkins import OWNER_SOURCE, owner_entries
from common.pacific_time import pacific_today, parse_day_key

from mcp.config import CHALLENGES_PK, logger, table as _table_ref

CHALLENGE_CHECKIN_DESCRIPTION = (
    "#6087: log Matthew's OWN daily check-in on one of his ACTIVE challenges (did he do today's rep). "
    "Call it only when he says he did or missed a challenge day. challenge_id = the challenge's id (the part after "
    "'CHALLENGE#', as /api/challenges serves it); completed = true (done) or false (missed); date = YYYY-MM-DD, "
    "default today (Pacific), never a future day. One entry per day: logging the same day again REPLACES that day. "
    "Readers' check-ins are stored elsewhere and never count here."
)

CHALLENGE_CHECKIN_INPUT = {
    "type": "object",
    "properties": {
        "challenge_id": {"type": "string", "description": "The challenge id (sk suffix after 'CHALLENGE#')."},
        "completed": {"type": "boolean", "description": "true = did it, false = missed it."},
        "date": {"type": "string", "description": "Optional: the day, YYYY-MM-DD. Default: today (Pacific). Never in the future."},
    },
    "required": ["challenge_id", "completed"],
}

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,119}$")
_MAX_ATTEMPTS = 3


def _write_once(table, key: dict, day: str, entry: dict):
    """One optimistic attempt. Returns (written, item_or_error)."""
    item = table.get_item(Key=key, ConsistentRead=True).get("Item")
    if not item:
        return False, "no such challenge"
    if item.get("status") != "active":
        return False, f"the challenge is not active (status: {item.get('status')})"
    rev = int(item.get("checkin_rev") or 0)
    kept = [c for c in (item.get("daily_checkins") or []) if not (isinstance(c, dict) and c.get("date") == day)]
    new_list = kept + [entry]
    table.update_item(
        Key=key,
        UpdateExpression="SET daily_checkins = :cl, checkin_rev = :next",
        ConditionExpression="attribute_exists(pk) AND (attribute_not_exists(checkin_rev) OR checkin_rev = :rev)",
        ExpressionAttributeValues={":cl": new_list, ":next": rev + 1, ":rev": rev},
    )
    return True, new_list


def tool_log_challenge_checkin(args):
    """Record (or replace) the owner's check-in for one day of one active challenge."""
    args = args or {}
    challenge_id = str(args.get("challenge_id") or "").strip()
    if challenge_id.startswith("CHALLENGE#"):
        challenge_id = challenge_id[len("CHALLENGE#") :]
    if not _ID_RE.match(challenge_id):
        return {"error": "challenge_id must be a challenge id such as 'cold-shower-finish_2026-05-04'. Nothing was stored."}
    completed = args.get("completed")
    if not isinstance(completed, bool):
        return {"error": "completed must be true or false. Nothing was stored."}
    today = pacific_today()
    day = args.get("date") or today
    if not isinstance(day, str) or len(day) != 10 or parse_day_key(day) is None:
        return {"error": f"date must be a day as YYYY-MM-DD (got {day!r}). Nothing was stored."}
    if day > today:
        return {"error": f"date {day} is after today ({today}, Pacific). Nothing was stored."}

    from datetime import datetime, timezone

    entry = {
        "date": day,
        "completed": completed,
        "logged_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
        "source": OWNER_SOURCE,
    }
    key = {"pk": CHALLENGES_PK, "sk": f"CHALLENGE#{challenge_id}"}
    for _attempt in range(_MAX_ATTEMPTS):
        try:
            written, result = _write_once(_table_ref, key, day, entry)
        except Exception as e:  # noqa: BLE001 — a lost check-in must be loud
            if "ConditionalCheckFailed" in str(e) or "ConditionalCheckFailed" in type(e).__name__:
                continue  # someone wrote between the read and the write: re-read and retry
            logger.warning(f"[#6087] challenge check-in write failed: {type(e).__name__}")
            return {"error": f"the check-in could not be stored ({type(e).__name__}). Try again."}
        if not written:
            return {"error": f"{result}: {challenge_id}. Nothing was stored."}
        return {
            "stored": True,
            "challenge_id": challenge_id,
            "date": day,
            "completed": completed,
            "checkin_days": len(owner_entries(result)),
            "completed_days": sum(1 for c in owner_entries(result) if c.get("completed")),
        }
    return {"error": "the challenge row kept changing under the write; nothing was stored. Try again."}
