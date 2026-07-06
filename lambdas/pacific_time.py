"""pacific_time.py — Canonical Pacific-time "today" for the platform.

Many compute/email Lambdas run on EventBridge crons fixed in UTC (no DST drift, by
platform convention) but their DATA is keyed by the *Pacific* calendar day the
behavior occurred (the site uses Pacific Time end-to-end). A handler that derives
"today" with ``datetime.now(timezone.utc)`` therefore selects the WRONG day during
its scheduled window: an evening-PT cron fires at ~01:00–03:00 UTC — i.e. *tomorrow*
in Pacific — so it reads an empty future day (circadian compliance) or reports every
manual source "not logged" (evening nudge).

See ``docs/reviews/PLATFORM_AUDIT_2026-06-30.md`` (BUG-01/02/03) and the #133 DST
fix, which swept *time-of-day* parsing but not the *day-selection* sibling.

Use ``pacific_today()`` / ``pacific_now()`` for any date or "now" used to SELECT data
keyed by the Pacific day. DST-aware via ``zoneinfo`` (mirrors the existing usage in
``output_writers.py``). This is the single source of truth — do not re-derive a
Pacific "today" from a raw UTC ``now`` inline.
"""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

# DST-aware Pacific Time. PT swings between UTC-8 (PST) and UTC-7 (PDT) — a hardcoded
# offset is wrong for ~8 months of the year.
PACIFIC = ZoneInfo("America/Los_Angeles")


def pacific_now() -> datetime:
    """Timezone-aware "now" in America/Los_Angeles (DST-aware)."""
    return datetime.now(PACIFIC)


def pacific_today() -> str:
    """Today's date as YYYY-MM-DD in America/Los_Angeles — the Pacific calendar day."""
    return pacific_now().strftime("%Y-%m-%d")


def pacific_date_of(iso_ts: str) -> str | None:
    """The Pacific calendar date (YYYY-MM-DD) of an ISO-8601 instant.

    A record keyed by its UTC date lands on the wrong platform day for evening-PT
    events (they roll into the next UTC day) — use this to recover the Pacific day
    a timestamp actually belongs to. A naive (tz-less) timestamp is assumed UTC.
    Returns None if the timestamp can't be parsed (caller decides the fallback).
    """
    if not iso_ts:
        return None
    try:
        dt = datetime.fromisoformat(str(iso_ts).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(PACIFIC).strftime("%Y-%m-%d")
