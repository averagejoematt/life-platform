"""lambdas/web/site_api_social_membrane.py — the Social Membrane surface (#1670/#1672/#1674/#1679): the broadcast feed, the
contextual embeds, and the bidirectional membrane dashboard.

Split out of ``lambdas/web/site_api_social.py`` (#2515) — the facade keeps the
routed entrypoints as thin delegators and this module holds the bodies. Handlers
read the facade's shared + monkeypatched state through the ``_g`` hand-off
(``_g`` is a delegator's ``globals()``), so routes, response contracts and the
test monkeypatch surface are unchanged. This module does NOT import the facade,
so there is no import cycle.
"""


def handle_broadcast(*, _g) -> dict:
    """GET /api/broadcast — reverse-chron cleared, human-origin posts for /story/broadcast/.

    Read-only; queries the ingested-post partitions, applies the ONE membrane
    predicate (_is_broadcast_visible), and returns facade cards newest-first.
    Fail-soft per source (a query error on one channel never breaks the feed).
    Cache 900s — the feed is refreshed by hourly-ish ingestion, not per-request."""
    # Facade state injected via `_g` (the delegator's globals()) — the same
    # module object the tests patch (see web/site_api_social.py's header).
    PT = _g["PT"]
    _BROADCAST_LIMIT = _g["_BROADCAST_LIMIT"]
    _broadcast_card = _g["_broadcast_card"]
    _membrane_visible_rows = _g["_membrane_visible_rows"]
    _ok = _g["_ok"]
    datetime = _g["datetime"]
    today = datetime.now(PT).strftime("%Y-%m-%d")  # #2414: the reader's "today" is the Pacific day
    visible = _membrane_visible_rows()
    # Reverse-chron across all sources (the per-source query is already newest-first;
    # this re-sorts the merged set). sk carries the post id after the date, so sort on it.
    visible.sort(key=lambda r: str(r.get("date", "")) + str(r.get("sk", "")), reverse=True)
    cards = [_broadcast_card(r) for r in visible[:_BROADCAST_LIMIT]]

    return _ok(
        {
            "as_of_date": today,
            "items": cards,
            "total": len(cards),
        },
        cache_seconds=900,
    )


def _handle_social_context(event: dict, *, _g) -> dict:
    """GET /api/social_context?route=training|mind — contextual embeds for #1674."""
    # Facade state injected via `_g` (the delegator's globals()) — the same
    # module object the tests patch (see web/site_api_social.py's header).
    _CONTEXT_LIMIT = _g["_CONTEXT_LIMIT"]
    _CONTEXT_ROUTES = _g["_CONTEXT_ROUTES"]
    _broadcast_card = _g["_broadcast_card"]
    _error = _g["_error"]
    _membrane_visible_rows = _g["_membrane_visible_rows"]
    _ok = _g["_ok"]
    coach_route_of = _g["coach_route_of"]
    params = event.get("queryStringParameters") or {}
    route = (params.get("route") or "").strip().lower()
    if route not in _CONTEXT_ROUTES:
        return _error(400, f"route query parameter is required and must be one of: {sorted(_CONTEXT_ROUTES)}")

    enriched = [r for r in _membrane_visible_rows() if r.get("enriched_at")]
    matched = [r for r in enriched if coach_route_of(r) == route]
    matched.sort(key=lambda r: str(r.get("date", "")) + str(r.get("sk", "")), reverse=True)
    cards = [_broadcast_card(r) for r in matched[:_CONTEXT_LIMIT]]

    return _ok(
        {
            "route": route,
            "items": cards,
            "total": len(cards),
        },
        cache_seconds=900,
    )


def _outbound_ledger_rows(channel: str, *, _g) -> list:
    """The BROADCAST_ORIGIN# ledger rows for one channel (#1670). Fail-soft: a query
    error on one channel returns [] rather than breaking the whole dashboard."""
    # Facade state injected via `_g` (the delegator's globals()) — the same
    # module object the tests patch (see web/site_api_social.py's header).
    Key = _g["Key"]
    _decimal_to_float = _g["_decimal_to_float"]
    logger = _g["logger"]
    table = _g["table"]
    try:
        resp = table.query(
            KeyConditionExpression=Key("pk").eq(f"BROADCAST_ORIGIN#{channel}") & Key("sk").begins_with("POST#"),
            ScanIndexForward=False,
        )
        return _decimal_to_float(resp.get("Items", []))
    except Exception as e:  # noqa: BLE001 — one bad channel must not break the dashboard
        logger.warning("[site_api] membrane: outbound ledger %s query failed (non-fatal): %s", channel, e)
        return []


def _outbound_record(row: dict) -> dict:
    """Reduce a ledger row to the public outbound record. Provenance fields only —
    what was posted, to which channel, when it was recorded, and where it lives."""
    return {
        "id": str(row.get("post_id") or str(row.get("sk", "")).replace("POST#", "")),
        "channel": row.get("channel", ""),
        "url": row.get("url", ""),
        "recorded_at": row.get("recorded_at", ""),
    }


def handle_membrane(*, _g) -> dict:
    """GET /api/membrane — the bidirectional membrane dashboard (#1679).

    Read-only, aggregate + provenance only, fail-soft on every read. Returns the
    three stages of the loop with an explicit state per side so the page can render
    "not wired yet" differently from "wired and quiet"."""
    # Facade state injected via `_g` (the delegator's globals()) — the same
    # module object the tests patch (see web/site_api_social.py's header).
    PT = _g["PT"]
    _BROADCAST_SOURCES = _g["_BROADCAST_SOURCES"]
    _MEMBRANE_LIMIT = _g["_MEMBRANE_LIMIT"]
    _OUTBOUND_CHANNELS = _g["_OUTBOUND_CHANNELS"]
    _broadcast_card = _g["_broadcast_card"]
    _inbound_channel_live = _g["_inbound_channel_live"]
    _inbound_channel_state = _g["_inbound_channel_state"]
    _is_broadcast_visible = _g["_is_broadcast_visible"]
    _membrane_source_rows = _g["_membrane_source_rows"]
    _ok = _g["_ok"]
    datetime = _g["datetime"]
    social_provenance = _g["social_provenance"]
    today = datetime.now(PT).strftime("%Y-%m-%d")  # #2414: the reader's "today" is the Pacific day

    # ── what I said → where it went (the outbound ledger) ──────────────────────
    outbound_channels, outbound_rows = [], []
    for channel in _OUTBOUND_CHANNELS:
        rows = _outbound_ledger_rows(channel, _g=_g)
        outbound_rows.extend(rows)
        outbound_channels.append({"channel": channel, "recorded": len(rows)})
    outbound_rows.sort(key=lambda r: str(r.get("recorded_at", "")), reverse=True)

    # ── what came back (the SAME gate the Broadcast feed uses) ─────────────────
    source_rows = _membrane_source_rows()
    visible = [r for r in source_rows if _is_broadcast_visible(r)]
    # The membrane join: rows the ORIGIN half of the predicate rejected. Counted from
    # social_provenance's own predicate — the same one _is_broadcast_visible composes —
    # so an echo can never be tallied as inbound. (Rows the SENSITIVITY half held are
    # deliberately not counted or reported; see the privacy note above.)
    echoes = sum(1 for r in source_rows if not social_provenance.is_displayable_voice(r))
    visible.sort(key=lambda r: str(r.get("date", "")) + str(r.get("sk", "")), reverse=True)

    inbound_channels = []
    for source in _BROADCAST_SOURCES:
        live = _inbound_channel_live(source)
        inbound_channels.append(
            {
                "channel": source,
                "live": live,
                # #2807: 'live' | 'paste-only' | 'dormant' — a paste-only channel
                # (x/instagram/tiktok) is never `live` (no API to poll) but is a real,
                # owner-driven channel, not an unwired one; it must not render as the
                # same "dormant" a truly absent pipe gets.
                "state": _inbound_channel_state(source),
                # VISIBLE (cleared, human-origin) rows only — never the raw partition
                # count, which would make the held set derivable by subtraction.
                "visible": sum(1 for r in visible if r.get("channel") == source),
            }
        )

    return _ok(
        {
            "as_of_date": today,
            "outbound": {
                "state": "recording" if outbound_rows else "empty",
                "total": len(outbound_rows),
                "channels": outbound_channels,
                "posts": [_outbound_record(r) for r in outbound_rows[:_MEMBRANE_LIMIT]],
            },
            "inbound": {
                # "dormant" while NO inbound channel is wired — the absence of a pipe,
                # which is not the same claim as "nothing came back" (ADR-104).
                "state": "live" if any(c["live"] for c in inbound_channels) else "dormant",
                "visible": len(visible),
                "channels": inbound_channels,
                "items": [_broadcast_card(r) for r in visible[:_MEMBRANE_LIMIT]],
            },
            "membrane": {
                "echoes_excluded": echoes,
                "predicate": "origin:human AND sensitivity-cleared (fail-closed)",
            },
        },
        cache_seconds=900,
    )
