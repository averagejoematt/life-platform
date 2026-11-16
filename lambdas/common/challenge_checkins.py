"""common/challenge_checkins.py — who may write a challenge check-in, and where (#6087).

Owner ruling 2026-11-16: a public interaction must never overwrite the canonical personal
experiment record. Two stores, never one:

  * OWNER — ``USER#matthew#SOURCE#challenges`` / ``CHALLENGE#<id>``, the ``daily_checkins``
    list. Written ONLY by the MCP tool ``log_challenge_checkin`` (``mcp/tools_challenges.py``),
    tagged ``source: OWNER_SOURCE``. The Site API role holds no write grant on this partition.
  * READER — ``CHALLENGE_CHECKINS#<id>`` / ``READER#<salted ip hash>#DATE#<day>``, one item per
    reader x challenge x day, written by ``POST /api/challenge_checkin`` with a conditional put
    (a replay or a concurrent duplicate is a no-op). Never read into the owner's progress.

``PUBLIC_DOOR_SOURCE`` is the tag the retired anonymous write into the owner row stamped. An
entry carrying it cannot be told apart from the owner's own, so no owner-facing figure counts it
(``owner_entries``). The live audit on 2026-11-16 found no such entry; the filter is the guard
for any that a restore or a replay might bring back.
"""

from __future__ import annotations

OWNER_SOURCE = "owner_mcp"
PUBLIC_DOOR_SOURCE = "website"
READER_CHECKIN_PK_PREFIX = "CHALLENGE_CHECKINS#"
READER_CHECKIN_TTL_DAYS = 180


def owner_entries(checkins) -> list:
    """The owner's check-ins in a stored ``daily_checkins`` list: drops non-dicts and every
    entry the anonymous door wrote (``source == PUBLIC_DOOR_SOURCE``)."""
    return [c for c in (checkins or []) if isinstance(c, dict) and c.get("source") != PUBLIC_DOOR_SOURCE]


def reader_checkin_key(challenge_id: str, reader_hash: str, day: str) -> dict:
    """The reader partition key for one reader's check-in on one challenge on one day."""
    return {"pk": f"{READER_CHECKIN_PK_PREFIX}{challenge_id}", "sk": f"READER#{reader_hash}#DATE#{day}"}
