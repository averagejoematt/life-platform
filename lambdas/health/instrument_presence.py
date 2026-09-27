"""instrument_presence.py — is a coach's domain instrument DARK, and if so since when (#4217).

Why this module exists
----------------------
On 2026-09-26 the glucose coach had had no glucose sensor for 30 days
(`/api/source_freshness` → `apple_health.datatypes[cgm] = {dark: true, last_seen:
"2026-08-27"}`; `/data/nutrition/` rendered "no sensor this cycle") and was still
arguing from one on every reader surface: "His CGM is generating traces…" on the
coaching door, "Your CGM is warming up…" as the served stance, and a standing docket
stake "based on CGM data". The engine already HAD the fact — the registry's `dark`
facet, served on the public board — and nothing in coach generation or coach serving
consulted it.

The rule
--------
A coach whose instrument is dark is ABSENT: it is not asked for a daily read, it
writes no stance, it is not admitted to a new docket item, and its reader slots serve
`{absent: true, reason: "no sensor since <YYYY-MM-DD>", instrument: {...}}` in place
of prose. Existing docket items stay (history); the serve side hides the dark side's
claim while naming the side.

ONE derivation, not two
-----------------------
"Dark" here is exactly what `/api/source_freshness` says, computed by the same code:
`datatype_liveness()` is the sentinel read that board's `datatypes[]` block is, and
`source_liveness()` is the status arithmetic each of its rows runs (the endpoint calls
BOTH of these — `web.site_api_freshness` delegates to them — so the board and the
gate can never disagree about one key, which is the #3257 class of defect this
module is built not to reintroduce). The coach → instrument map is
`ingestion.source_registry.coach_instruments()`, inverted from the registry's own
`instrument_for` facets — never hand-typed here.

A `behavioral` source (Hevy, MacroFactor, the labs panel) can only ever be
behavioral-stale — a lapse in a hand-kept log, which is about Matthew and never about
a sensor — so it never makes its coach absent. Only a sensor that STOPPED does:
status `stale` (a KNOWN last day beyond the source's window), the registry's
`paused`, or a datatype row's `dark` (the checker's own verdict). A source partition
with no DATE# row at all is UNKNOWN, not dark (#1971 absent-is-unknown): silencing a
coach needs evidence that the sensor stopped, and "never wrote" is not that — the
board still reports such a partition as `stale` (it is describing a pipe, not
silencing a coach), and no live instrument has an empty partition, so the two words
diverge only on a shape that does not occur.

Every reader passes its own `table`, so the three generation Lambdas and the site-api
each run this over the client they already hold; nothing here opens a connection.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from boto3.dynamodb.conditions import Key
from common.numeric import decimals_to_float
from common.pacific_time import anchor_day_key
from experiment.phase_filter import with_phase_filter
from ingestion.source_registry import DEFAULT_STALE_HOURS, SOURCE_REGISTRY, coach_instruments, stale_hours_overrides

logger = logging.getLogger(__name__)

#: The single-table partition prefix every DATE#/sentinel read below keys on.
USER_PREFIX = "USER#matthew#SOURCE#"

#: The apple_health per-datatype liveness sentinel the freshness checker writes
#: (emails/freshness_checker_lambda.py, D-4/#468) — one row, `datatypes: [...]`.
DATATYPE_LIVENESS_SK = "DATATYPE_LIVENESS"

#: `/api/source_freshness`'s own status words — reused, never re-invented.
FRESH = "fresh"
STALE = "stale"
BEHAVIORAL_STALE = "behavioral-stale"
PAUSED = "paused"


def latest_date_str(table: Any, source: str) -> str | None:
    """Latest YYYY-MM-DD among a source's DATE# records, or None.

    The board's own read (it delegates here): `begins_with('DATE#')` so a non-DATE sort
    key (measurements' YEAR# rollup) never shadows the real latest day; projects `sk`
    only; `include_pilot=True` because liveness is pipe/behaviour recency regardless
    of experiment phase (#1203 — the phase filter is applied AFTER `Limit`, so
    without it the newest key is fetched, filtered out and the query returns empty:
    exactly the blindfold, on exactly the source whose lapse is longest).
    """
    kwargs = with_phase_filter(
        {
            "KeyConditionExpression": Key("pk").eq(f"{USER_PREFIX}{source}") & Key("sk").begins_with("DATE#"),
            "ScanIndexForward": False,
            "Limit": 1,
            "ProjectionExpression": "sk",
        },
        include_pilot=True,
    )
    items = table.query(**kwargs).get("Items", [])
    if not items:
        return None
    return str(items[0]["sk"]).replace("DATE#", "")[:10]


def datatype_liveness(table: Any) -> list | None:
    """The per-datatype HAE liveness rows the freshness checker stores (D-4/#468), or
    None when the sentinel is absent or unreadable — the board's own read (it
    delegates here). Each row: {key, label, last_seen, age_days, dark, stale_days,
    manual}; Decimals already walked to float, as the board serves them."""
    try:
        rec = table.get_item(Key={"pk": USER_PREFIX + "apple_health", "sk": DATATYPE_LIVENESS_SK}).get("Item")
        if not rec:
            return None
        return decimals_to_float(rec).get("datatypes")
    except Exception as e:  # never break a feed for a missing sentinel
        logger.warning("instrument_presence: apple_health datatypes read failed: %s", e)
        return None


def source_liveness(last_update: str | None, source: str, now: datetime, *, stale_hours: float, behavioral: bool) -> dict:
    """The board's per-row status arithmetic, in one place (it delegates here).

    `last_update` is a stored DATE# day key; it is anchored in the calendar frame that
    NAMED it (`anchor_day_key`, #3257 — Pacific for most sources, UTC for
    apple_health/whoop) before ageing, and the age is compared to the source's own
    registry window. No record at all is `stale` (or `behavioral-stale` for a
    behavioral source) — the board's rule, unchanged.
    """
    if not last_update:
        return {"status": BEHAVIORAL_STALE if behavioral else STALE, "last_update": None, "last_update_ts": None, "age_hours": None}
    last_dt = anchor_day_key(last_update, source)
    age_hours = round((now - last_dt).total_seconds() / 3600, 1)
    if age_hours <= stale_hours:
        status = FRESH
    elif behavioral:
        status = BEHAVIORAL_STALE
    else:
        status = STALE
    return {"status": status, "last_update": last_update, "last_update_ts": last_dt.isoformat(), "age_hours": age_hours}


def _reason(last_seen: str | None) -> str:
    """The engine's words. The page renders the date in words; nothing else composes them."""
    return f"no sensor since {last_seen}" if last_seen else "no sensor recorded"


def instrument_state(table: Any, instrument: dict, now: datetime | None = None) -> dict:
    """{source, datatype, label, dark, last_seen, reason} for one coach's instrument.

    `instrument` is a row of `coach_instruments()`. A datatype instrument reads the
    sentinel (`dark` is the checker's own verdict, `last_seen` its own date; an absent
    sentinel or datatype row is NOT dark — unknown is unknown, #1971). A source
    instrument is dark when its KNOWN last day is beyond the board's window (`stale`)
    or the registry pauses it; a behavioral source is never dark; an empty partition
    is unknown, not dark.
    """
    now = now or datetime.now(timezone.utc)
    source = str(instrument.get("source") or "")
    datatype = instrument.get("datatype")
    label = str(instrument.get("label") or source)
    state = {"source": source, "datatype": datatype, "label": label, "dark": False, "last_seen": None, "reason": None}
    if datatype:
        for row in datatype_liveness(table) or []:
            if isinstance(row, dict) and row.get("key") == datatype:
                state["last_seen"] = row.get("last_seen")
                state["dark"] = row.get("dark") is True
                break
    else:
        meta = SOURCE_REGISTRY.get(source) or {}
        if meta.get("paused"):
            state["dark"] = True
            try:
                state["last_seen"] = latest_date_str(table, source)
            except Exception as e:  # the pause alone decides; the date is a courtesy
                logger.warning("instrument_presence: paused source %s date read failed: %s", source, e)
        elif not (instrument.get("behavioral") or meta.get("behavioral")):
            last = latest_date_str(table, source)
            if last:  # no DATE# row at all is unknown, never dark — see the module docstring
                live = source_liveness(
                    last, source, now, stale_hours=stale_hours_overrides().get(source, DEFAULT_STALE_HOURS), behavioral=False
                )
                state["last_seen"] = last
                state["dark"] = live["status"] == STALE
    if state["dark"]:
        state["reason"] = _reason(state["last_seen"])
    return state


def absent_coaches(table: Any, now: datetime | None = None, instruments: dict | None = None) -> dict:
    """{coach_id: instrument_state} for every coach whose instrument is dark right now.

    The ONE call the analyzer, the stance writer, docket admission and the four serve
    surfaces make. `instruments` defaults to the registry-derived map; a caller passes
    one only to test a shape. A coach with no instrument row is never here.
    """
    now = now or datetime.now(timezone.utc)
    out: dict[str, dict] = {}
    for coach_id, instrument in (instruments if instruments is not None else coach_instruments()).items():
        state = instrument_state(table, instrument, now)
        if state["dark"]:
            out[coach_id] = state
    return out


def served_instrument(coach_id: str, instruments: dict | None = None) -> dict | None:
    """The wire shape of a coach's instrument for `/api/coaches` & co — {source, datatype}
    — or None for a coach with no single instrument. The v7 renderer's COACH_SOURCE
    table reads this shape."""
    row = (instruments if instruments is not None else coach_instruments()).get(coach_id)
    if not row:
        return None
    return {"source": row["source"], "datatype": row.get("datatype")}
