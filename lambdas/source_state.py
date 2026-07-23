"""Source-state legibility (WORKORDER DI-1.1).

A single resolver for every ingest source's operational state —
``live`` / ``paused`` / ``rate_limited`` / ``stale`` — so a deliberately-off source
(Strava, paused at the 402 paywall) or a chronically rate-limited one (Garmin's 429
refresh block) is legible as off-by-design and is never mistaken for silent breakage.

Read by three consumers (all get it via the bundled lambdas/ tree):
  - ``get_freshness_status`` (MCP) — surfaces the state so the flip is visible.
  - the training-coach honesty guard (DI-1.3) — withholds an under-training verdict
    when the movement sources aren't ``live``.
  - the pipeline health check (operational) — a ``paused`` source's healthcheck "ok"
    must NOT be reported as healthy (that masks a missing cron) nor alarmed as broken.

Precedence is **freshness-first**: fresh data ⇒ ``live`` regardless of any paused
declaration, so re-enabling a source flips it to ``live`` the moment data flows again
— no second edit required. The declaration only labels the *not-fresh* case.
"""

from datetime import datetime

# Sources intentionally OFF (no live ingestion cron). A paused source is off-by-design,
# not broken. Flip here when re-enabling — though freshness wins for 'live', so removing
# a source is only needed to relabel a future *real* outage as 'stale' rather than
# 'paused'. (Strava was paused 2026-06-14 at the 402 paywall and REMOVED 2026-07-04
# (#496/C-3) — its cron has been live again since 06-20, and the stale declaration
# was suppressing real-outage detection: the health check skipped it, MCP freshness
# said 'paused' for behavioral lapses, and the training coach was told it wasn't a
# live ingest path. Currently empty on purpose; garmin's pause is registry-driven
# (source_registry paused=True, ADR-074), not declared here.)
DECLARED_PAUSED_SOURCES: set[str] = set()

STATE_LIVE = "live"
STATE_PAUSED = "paused"
STATE_RATE_LIMITED = "rate_limited"
STATE_STALE = "stale"

DEFAULT_STALE_DAYS = 2

# Sub-key markers that signal a source is being throttled upstream (state = rate_limited
# when not fresh). Garmin writes REFRESH_RATELIMIT when the 429 defeats its OAuth refresh.
RATE_LIMIT_MARKER_SK = {"garmin": "REFRESH_RATELIMIT"}


def _gap_days(latest_date, today):
    try:
        a = datetime.strptime(str(latest_date), "%Y-%m-%d").date()
        b = datetime.strptime(str(today), "%Y-%m-%d").date()
        return (b - a).days
    except (ValueError, TypeError):
        return None


def is_paused(source):
    """True if the source is declared off-by-design (no live cron)."""
    return source in DECLARED_PAUSED_SOURCES


def resolve_source_state(source, latest_date, today, *, rate_limited=False, stale_days=DEFAULT_STALE_DAYS):
    """Operational state for an ingest source. Freshness wins for ``live``.

    source:       normalized source id (e.g. 'strava', 'garmin').
    latest_date:  newest DATE# present for the source ('YYYY-MM-DD'), or None.
    today:        'YYYY-MM-DD'.
    rate_limited: True if a rate-limit marker is present (e.g. Garmin REFRESH_RATELIMIT).

    Returns one of: live / rate_limited / paused / stale. The order matters — fresh
    data is 'live' even for a source still in DECLARED_PAUSED_SOURCES (the re-enable
    flip); a rate-limit marker outranks the paused/stale labels; a declared-paused
    source with no fresh data is 'paused'; everything else is 'stale'.
    """
    gap = _gap_days(latest_date, today)
    if gap is not None and gap <= stale_days:
        return STATE_LIVE
    if rate_limited:
        return STATE_RATE_LIMITED
    if source in DECLARED_PAUSED_SOURCES:
        return STATE_PAUSED
    return STATE_STALE


def has_rate_limit_marker(table, user_id, source):
    """Best-effort check for a source's rate-limit marker record. Never raises."""
    sk = RATE_LIMIT_MARKER_SK.get(source)
    if not sk:
        return False
    try:
        resp = table.get_item(Key={"pk": f"USER#{user_id}#SOURCE#{source}", "sk": sk})
        return bool(resp.get("Item"))
    except Exception:
        return False
