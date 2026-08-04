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

TWO INVARIANTS LIVE HERE, BOTH STRUCTURALLY GUARDED (#1964)
-----------------------------------------------------------
1. **The Pacific frame.** ``PACIFIC`` / ``pacific_now()`` / ``pacific_today()`` /
   ``pacific_day_n()``. No module outside this one may construct its own
   ``ZoneInfo("America/Los_Angeles")`` or a fixed ``-7``/``-8`` offset.
2. **ISO-8601 parsing.** ``parse_iso_utc()`` — the ONE parser, with one explicit
   naive-timestamp semantic (tz-less input means UTC, never runner-local). No
   module outside this one may define a private ``_parse_iso*`` fork.

Both are enforced by ``tests/test_time_invariant_helpers_1964.py``, an AST scan of
``lambdas/`` + ``mcp/`` (the deployed surface) — the D5 pattern from #1207. The
guard exists because the docstring convention alone did not hold: seven inline
Pacific "today" derivations and 27 inline ISO-parse forks accreted after this
module shipped, two of them (``site_api_freshness._parse_iso_ts`` backfilling
``tzinfo=UTC``, ``whoop_lambda._parse_iso`` leaving naive naive) with *divergent*
answers to the same question.
"""

from datetime import date, datetime, timezone
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


def parse_iso_utc(value) -> datetime | None:
    """THE ISO-8601 parser (#1964) — returns a timezone-AWARE datetime, or None.

    **The naive-timestamp semantic, stated once so it can never fork again: a
    tz-less input is interpreted as UTC.** It is never interpreted as the
    runner's local time, which is what a bare ``datetime.fromisoformat(...)``
    followed by ``.astimezone(...)`` silently does — and which is only invisible
    today because the Lambda runtime happens to run in UTC. That coincidence is
    not a contract: the same code under a local ``pytest`` or a laptop-run
    backfill script would shift every naive stamp by the operator's offset.

    UTC is chosen (over Pacific) because every naive stamp this platform actually
    receives is a UTC instant with the ``Z`` dropped by an upstream serializer —
    Whoop, Notion, Hevy, GitHub and the DynamoDB ``computed_at``/``generated_at``
    stamps are all UTC-emitting. It is also the semantic the majority fork
    (``site_api_freshness._parse_iso_ts``) already used, so adopting it changes
    the fewest live call sites.

    An input that already carries an offset KEEPS that offset — the value is a
    fixed instant either way, and comparison/subtraction across offsets is exact,
    so re-normalising to UTC would only lose the original frame. Call
    ``.astimezone(timezone.utc)`` if a caller genuinely needs the UTC rendering.

    Accepts ``Z``/``z``-suffixed and offset-suffixed forms. Never raises: an
    empty, malformed, or non-string value returns None and the caller decides the
    fallback (the same contract as ``pacific_date_of``).
    """
    if not value:
        return None
    s = str(value).strip()
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def pacific_date_of(iso_ts: str) -> str | None:
    """The Pacific calendar date (YYYY-MM-DD) of an ISO-8601 instant.

    A record keyed by its UTC date lands on the wrong platform day for evening-PT
    events (they roll into the next UTC day) — use this to recover the Pacific day
    a timestamp actually belongs to. A naive (tz-less) timestamp is assumed UTC
    (``parse_iso_utc``'s documented semantic). Returns None if the timestamp can't
    be parsed (caller decides the fallback).
    """
    dt = parse_iso_utc(iso_ts)
    return dt.astimezone(PACIFIC).strftime("%Y-%m-%d") if dt else None


def pacific_day_n(start_date: str, on_date: str | None = None) -> int:
    """1-based day index of a cycle in the Pacific frame — Day 1 IS ``start_date``.

    THE one day-index formula (#1955): every public "Day N" claim — the vitals
    window disclosure, /api/journey's ``day_n``, the home og:description — must
    derive from this helper so two surfaces can never disagree on the day number
    at the same wall-clock instant (og said "Day 6 … As of 2026-08-02" while
    /api/vitals said "Day 7", 2026-08-02T02:36Z). Companion sweep of the
    remaining UTC anchors in site_api_vitals is #1937.

    ``start_date`` and ``on_date`` are YYYY-MM-DD strings already in the Pacific
    calendar; ``on_date`` defaults to ``pacific_today()``. Clamped at 0 for a
    pre-start date (matching the site_api_vitals inline formula this replaces);
    returns 0 when either date can't be parsed (caller decides the fallback).
    """
    on = on_date or pacific_today()
    try:
        return max((date.fromisoformat(on) - date.fromisoformat(start_date)).days + 1, 0)
    except (ValueError, TypeError):
        return 0
