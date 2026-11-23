"""brief_editorial_inputs.py — the reads behind `content.brief_editorial` (#6163).

Three read-only lookups, each fail-soft (a failed read drops its key, and the renderer then
prints exactly what it printed before #6163):

  * ``nutrition`` — the food-log source's own freshness: the newest DATE# rows of the
    ``macrofactor`` partition (the read `get_freshness_status` makes), reduced to the Pacific day
    the newest export LANDED (``ingested_at`` and its summary/projection variants) and the newest
    day carrying intake.
  * ``previous_guidance`` — the previous brief's stored guidance (``computed_insights`` for the day
    before, ``guidance_given``: the TL;DR then each guidance item, written by the brief itself).
  * ``previous_protocol_recs`` — the previous brief's PROTOCOLS TO TRY block, which is a pure function
    of that day's stored ``character_sheet`` row (``output_writers.get_protocol_recs``).

No writes, no new store, no new attribute. The result reaches ``html_builder.build_html`` only —
never ``data``, an AI prompt or a generated file.
"""

from __future__ import annotations

import json

from common import food_log_state
from common.pacific_time import shift_day_key

# #6240: the read and the reduction moved to common.food_log_state, the ONE determination the public day page reads too.
_NEWEST_ROWS = food_log_state.NEWEST_ROWS


def nutrition_freshness(table, user_prefix: str) -> dict | None:
    """{"last_arrival_day", "last_intake_day"} from the newest macrofactor rows, or None when none."""
    return food_log_state.read_freshness(table, user_prefix)


def _previous_guidance(fetch_date, day: str) -> list | None:
    raw = (fetch_date("computed_insights", day) or {}).get("guidance_given")
    items = json.loads(raw) if isinstance(raw, str) else raw
    return [str(i) for i in items] if isinstance(items, list) and items else None


def gather(table, fetch_date, user_prefix: str, data_day: str, logger) -> dict:
    """The editorial inputs for the brief on `data_day`'s data. Each key present only when read."""
    from content import output_writers

    prev_day = shift_day_key(data_day, -1)
    out: dict = {}
    steps = (
        ("nutrition", lambda: nutrition_freshness(table, user_prefix)),
        ("previous_guidance", lambda: _previous_guidance(fetch_date, prev_day)),
        ("previous_protocol_recs", lambda: output_writers.get_protocol_recs(fetch_date("character_sheet", prev_day))),
    )
    for key, read in steps:
        try:
            val = read()
        except Exception as err:  # noqa: BLE001 — fail-soft: the brief renders its pre-#6163 line
            logger.warning("brief editorial input %s failed (non-fatal): %s", key, err)
            continue
        if val:
            out[key] = val
    return out
