"""health/band_description.py — the Habitify calorie-band habit's description follows the week's band (#5099).

The owner ruled 2026-10-26 ("Auto-update on Mondays"): the description of the Habitify habit that grades the
calorie band states the week's ACTUAL band, so it is rewritten by the weekly titration (``mcp/titration_leg.py``)
after it writes a week whose band differs from the previous stored week's band — and only then.

THE HABIT is found by vendor id, never by display name: the registry entry that carries the ``calories_in_band``
core flag (``health.core_habits``) names it in ``habitify_id``. Zero or several candidate ids, or an entry with no
id, is a skip (named in the result), never a guess.

THE WRITE is the v2 API's metadata update — ``PUT https://api.habitify.me/v2/habits/{id}`` with ``{"description":
...}``, header ``X-API-Key`` from the ``habitify_api_key_v2`` field of Secrets Manager ``life-platform/habitify``
(through ``secret_cache``) — the same call the owner's habitify skill makes. ``urllib.request`` only.

FAIL-SOFT: ``sync`` never raises. Any failure logs ONE line (the error class, never a body or a number) and returns
``failed``; the titration record is already written by then and a Friday-to-Sunday retry does not re-run the write.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable, Mapping, Optional
from urllib.error import HTTPError
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

CORE_ID = "calories_in_band"  # the charter `habits.core` id of the calorie-band habit
SECRET_ID = "life-platform/habitify"  # noqa: S105 — a secret NAME, not a value
SECRET_FIELD = "habitify_api_key_v2"  # noqa: S105 — a field NAME, not a value
BASE_URL = "https://api.habitify.me/v2"
TIMEOUT_S = 15
ATTEMPTS = 3
LOG_MARK = "NUTRITION_BAND_DESCRIPTION"

TEMPLATE = (
    "{low:,}–{high:,} kcal this week (wk of {month} {day}). Floor and ceiling from the charter; "
    "under the floor is a miss, over the ceiling is a miss. Updated Mondays."
)

Opener = Callable[..., Any]


def _int(v: Any) -> Optional[int]:
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return int(f) if f == f else None


def band_of(record: Optional[Mapping[str, Any]]) -> Optional[tuple[int, int]]:
    """``(band_low, band_high)`` of a titration record or decision, or None when either end is missing."""
    if not record:
        return None
    lo, hi = _int(record.get("band_low")), _int(record.get("band_high"))
    return None if lo is None or hi is None else (lo, hi)


def band_moved(previous: Optional[Mapping[str, Any]], decision: Mapping[str, Any]) -> bool:
    """True when the decision carries a band and the previous stored week carried a DIFFERENT one. No previous
    band (a first record, or one that wrote none) is not provably a move: False."""
    new, old = band_of(decision), band_of(previous)
    return new is not None and old is not None and new != old


def render(low: int, high: int, week: str) -> str:
    """The description text for the band ``low``..``high`` kcal applying to the ISO-Monday ``week``."""
    from common.pacific_time import parse_day_key  # noqa: PLC0415 — the calendar-day parse (#3741)

    d = parse_day_key(week)
    if d is None:
        raise ValueError("week is not a YYYY-MM-DD day key")
    return TEMPLATE.format(low=low, high=high, month=d.strftime("%b"), day=d.day)


def band_habit_id(registry: Any) -> Optional[str]:
    """The vendor id of the calorie-band habit: the ONE ``habitify_id`` among the active registry entries flagged
    ``calories_in_band``, or None (none flagged, none with an id, or more than one distinct id)."""
    from health import core_habits  # noqa: PLC0415 — keeps this module import-light

    if not isinstance(registry, Mapping):
        return None
    ids = set()
    for key in core_habits.members(registry).get(CORE_ID, []):
        meta = registry.get(key)
        hid = meta.get("habitify_id") if isinstance(meta, Mapping) else None
        if isinstance(hid, str) and hid.strip():
            ids.add(hid.strip())
    return next(iter(ids)) if len(ids) == 1 else None


def _api_key() -> str:
    import boto3  # noqa: PLC0415
    from common.secret_cache import get_secret_json  # noqa: PLC0415

    key = get_secret_json(SECRET_ID, boto3.client("secretsmanager", region_name="us-west-2")).get(SECRET_FIELD)
    if not key:
        raise RuntimeError("no habitify_api_key_v2 in the secret")
    return str(key)


def put_description(habit_id: str, text: str, api_key: str, opener: Opener = urlopen, sleep: Callable[[float], None] = time.sleep) -> None:
    """``PUT /v2/habits/{id}`` with ``{"description": text}``; retries 429/5xx. Raises on any final failure."""
    req = Request(
        f"{BASE_URL}/habits/{habit_id}",
        data=json.dumps({"description": text}).encode(),
        headers={"X-API-Key": api_key, "User-Agent": "LifePlatform/1.0", "Content-Type": "application/json"},
        method="PUT",
    )
    for attempt in range(ATTEMPTS):
        try:
            with opener(req, timeout=TIMEOUT_S) as resp:
                resp.read()
            return
        except HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < ATTEMPTS - 1:
                sleep(2 * (attempt + 1))
                continue
            raise


def sync(
    previous: Optional[Mapping[str, Any]],
    decision: Mapping[str, Any],
    registry: Any,
    *,
    api_key_reader: Optional[Callable[[], str]] = None,
    put: Optional[Callable[[str, str, str], None]] = None,
) -> str:
    """After a decision is written: when its band moved, rewrite the calorie-band habit's description. Returns
    ``unchanged`` | ``updated`` | ``no_habit`` | ``failed``. Never raises."""
    try:
        if not band_moved(previous, decision):
            return "unchanged"
        band = band_of(decision)
        habit_id = band_habit_id(registry)
        if band is None or not habit_id:
            logger.warning("%s skipped: no single calories_in_band registry entry with a habitify_id", LOG_MARK)
            return "no_habit"
        (put or put_description)(habit_id, render(band[0], band[1], str(decision["week"])), (api_key_reader or _api_key)())
        logger.info("%s updated week=%s", LOG_MARK, decision["week"])
        return "updated"
    except Exception as e:  # noqa: BLE001 — fail-soft: the titration record is already written
        logger.warning("%s failed (%s)", LOG_MARK, type(e).__name__)
        return "failed"
