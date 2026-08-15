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


def _registry_paused():
    """Sources the REGISTRY marks paused. Fail-soft: an unreadable registry is not a pause.

    #2715: this module and `source_registry` each held half of the same fact and never
    met. `DECLARED_PAUSED_SOURCES` above is empty on purpose and its own comment says why
    — "garmin's pause is registry-driven (source_registry paused=True, ADR-074), not
    declared here" — while the registry's `paused` facet says, equally plainly,
    "intentionally off — shown as 'paused', never counted stale". Both were true, and
    nothing read both, so `resolve_source_state` answered `stale` for a source that is off
    by design and `get_freshness_status` turned the whole verdict RED for it.

    Imported lazily: `source_registry` is a large module and this one is imported by
    handlers that only want the constants. Failure returns an empty set — labelling a
    source paused when we cannot confirm it would suppress a real outage, which is the
    error that matters here (and is exactly what #496/C-3 hit with Strava).
    """
    try:
        from ingestion.source_registry import SOURCE_REGISTRY

        return {k for k, v in SOURCE_REGISTRY.items() if v.get("paused")}
    except Exception:  # noqa: BLE001 — never let a registry read decide a source is broken
        return set()


def is_paused(source):
    """True if the source is off-by-design (no live cron), by declaration or registry."""
    return source in DECLARED_PAUSED_SOURCES or source in _registry_paused()


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
    # #2715: `is_paused` now reads the registry's `paused` facet as well as the declared
    # set. Before, this asked only the declared set — which is empty by design — so garmin,
    # paused by ADR-074 with no EventBridge rule, resolved `stale` and pushed
    # get_freshness_status's whole verdict to RED. The order is unchanged and matters:
    # freshness still wins, so a paused source that starts producing again reads `live`
    # with no code change, and a rate-limit marker still outranks the paused label.
    if is_paused(source):
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
