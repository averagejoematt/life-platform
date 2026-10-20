"""mcp/tools_evening_checkin.py — the Claude-side door to the 20-second evening check-in (#5106).

`log_evening_intake` (mcp/tools_lifestyle.py) is the existing evening log; #5106 widens it rather than adding a
tool: `hunger`, `stress`, `cravings` (0-4, the same scale as its `count`) and one `word` ride the same call and
land in the owner-only `evening_checkin` partition through `coach.evening_checkin.write` — the SAME writer the
Telegram reply uses, so the two doors cannot disagree on a field, a scale or the idempotency rule. `count` stays
the drinks ledger and becomes optional when a check-in field is given.

The tool's input table lives here (the #3759 extraction shape) so `mcp/registry.py`, at its size ceiling, pays
for the four new properties instead of growing.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

LOG_EVENING_INTAKE_INPUT = {
    "type": "object",
    "properties": {
        "count": {
            "type": "integer",
            "description": "Evening drinks count, 0-4 (4 = four or more). Optional when a check-in field is given.",
        },
        "hunger": {"type": "integer", "description": "#5106 evening check-in: hunger 0-4."},
        "stress": {"type": "integer", "description": "#5106 evening check-in: stress 0-4."},
        "cravings": {"type": "integer", "description": "#5106 evening check-in: cravings 0-4."},
        "word": {"type": "string", "description": "#5106 evening check-in: one word for the day."},
        "date": {"type": "string", "description": "YYYY-MM-DD (default: tonight, the Pacific calendar day)."},
    },
    "required": [],
}


def evening_count(args: Mapping[str, Any]) -> Optional[int]:
    """The drinks count, validated 0-4 — or None when it is absent and a check-in field carries the call.

    Raises ValueError for a bad count, a bad check-in value, or a call with neither (nothing is written then)."""
    from coach import evening_checkin

    has_checkin = bool(evening_checkin.validate(args))
    if args.get("count") is None and has_checkin:
        return None
    try:
        count = int(args.get("count"))
    except (TypeError, ValueError):
        raise ValueError("count is required (integer 0-4; 4 = four or more) unless hunger/stress/cravings/word is given")
    if not (0 <= count <= 4):
        raise ValueError("count must be between 0 and 4 (4 = four or more)")
    return count


def log_checkin_part(args: Mapping[str, Any], table, date_str: str) -> Optional[dict[str, Any]]:
    """Write the check-in fields in ``args`` (if any) for ``date_str``; None when the call carries none."""
    from coach import evening_checkin

    if not evening_checkin.validate(args):  # raises ValueError on a bad value, before anything is written
        return None
    return evening_checkin.write(table, date_str, args, "mcp")
