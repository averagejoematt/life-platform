"""lambdas/web/site_api_freshness.py — pipeline liveness handlers split out of
site_api_data.py (#1654): source_freshness / last_sync / presence / device_agreement.
Handlers receive `_g` (the facade's globals()) from their thin delegator and read the
facade's injectable/monkeypatched state via `_g["<name>"]` — same object the test patched."""

from datetime import datetime, timezone

from boto3.dynamodb.conditions import Key
from phase_filter import with_phase_filter

from web.site_api_common import USER_PREFIX, _decimal_to_float, _error, _ok, logger

_DEVICE_AGREEMENT_START = "2020-01-01"  # generous floor; predates any real device data


_DEVICE_AGREEMENT_DAILY_CAP = 90  # most-recent N overlap days in the payload; aggregates cover the full window


_PRESENCE_LOUD = {"light", "quiet", "dark"}


def _latest_date_str(source: str, *, _g) -> str | None:
    """Latest YYYY-MM-DD among a source's DATE# records, or None.

    Uses begins_with('DATE#') so non-DATE sort keys (e.g. measurements' YEAR# rollup)
    don't shadow the real latest day. Projects sk only — cheap.

    #1203: include_pilot=True — freshness is pipe/behavior LIVENESS, a "dark N days"
    signal about real recency regardless of experiment phase. Every source on this
    board is RAW_TIMESERIES (cross_phase, phase_taxonomy.py — "phase tags are
    harmless/optional"), so a source whose newest DATE# predates the current cycle
    (e.g. after a reset tags all pre-genesis records phase=pilot) must still report
    its true last-update date and days-dark, not render last_update:null exactly when
    the lapse is longest. This matches the operator checker (freshness_checker_lambda.py,
    which queries these partitions with NO phase filter) and the deliberate
    include_pilot=True device-agreement read below. Note the phase filter is a
    FilterExpression applied AFTER Limit, so without this the newest DATE# is fetched,
    filtered out as phase!=current, and the query returns empty — the exact blindfold.
    """
    # Facade state injected via `_g` (the delegator's globals()) — same module the test patched.
    table = _g["table"]
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


def _apple_health_datatypes(*, _g):
    """Per-datatype HAE liveness the freshness-checker stores (D-4/#468). None if absent."""
    # Facade state injected via `_g` (the delegator's globals()) — same module the test patched.
    table = _g["table"]
    try:
        rec = table.get_item(Key={"pk": USER_PREFIX + "apple_health", "sk": "DATATYPE_LIVENESS"}).get("Item")
        if not rec:
            return None
        return _decimal_to_float(rec).get("datatypes")
    except Exception as e:  # never break the feed for a missing sentinel
        logger.warning("source_freshness: apple_health datatypes read failed: %s", e)
        return None


def _carried_from_cycle(source: str, date_str: str, *, _g) -> int | None:
    """The ADR-077 cycle stamp on a source's latest record, or None.

    Only consulted when that record's CONTENT date predates the current genesis
    (never inferred from tombstoned_at) — the chip provenance for "carried from
    attempt N" (#1371). Fail-soft: a missing stamp renders an unnumbered label.
    """
    # Facade state injected via `_g` (the delegator's globals()) — same module the test patched.
    table = _g["table"]
    try:
        item = table.get_item(
            Key={"pk": f"{USER_PREFIX}{source}", "sk": f"DATE#{date_str}"},
            ProjectionExpression="#c",
            ExpressionAttributeNames={"#c": "cycle"},
        ).get("Item")
        if item and item.get("cycle") is not None:
            return int(item["cycle"])
    except Exception as e:
        logger.warning("source_freshness: carried-cycle read failed for %s: %s", source, e)
    return None


def source_freshness(*, _g) -> dict:
    """GET /api/source_freshness — live pipeline status per data source.

    status ∈ {fresh, stale, behavioral-stale, paused}. Behavioral sources (manual
    logs) report "behavioral-stale" rather than "stale" so a lapse in logging never
    reads as a broken pipeline. Always a shaped 200 — sparse/empty data still renders.

    #1371: sources whose newest record predates the current genesis carry explicit
    cross-cycle provenance (`carried` + `carried_from_cycle`) and the payload carries
    the experiment anchor, so a Day-1 board can label a 110-day-old chip "carried
    from attempt 7" instead of rendering an unexplained ghost.
    """
    # Facade state injected via `_g` (the delegator's globals()) — same module the test patched.
    EXPERIMENT_START = _g["EXPERIMENT_START"]
    _FRESHNESS_DEFAULT_STALE_HOURS = _g["_FRESHNESS_DEFAULT_STALE_HOURS"]
    _FRESHNESS_PAUSED = _g["_FRESHNESS_PAUSED"]
    _FRESHNESS_SOURCES = _g["_FRESHNESS_SOURCES"]
    _FRESHNESS_STALE_HOURS = _g["_FRESHNESS_STALE_HOURS"]
    _MANUAL_CAPTURE = _g["_MANUAL_CAPTURE"]
    _days_dark = _g["_days_dark"]
    now = datetime.now(timezone.utc)
    sources = []
    summary = {"fresh": 0, "stale": 0, "paused": 0, "total": 0}
    try:
        from coach_checkin import read_cycle

        current_cycle = read_cycle()
    except Exception:
        current_cycle = None

    for sid, meta in _FRESHNESS_SOURCES.items():
        last_update = None
        last_update_ts = None
        age_hours = None
        stale_hours = None
        status = "stale"
        try:
            date_str = _latest_date_str(sid, _g=_g)
            if date_str:
                last_update = date_str
                last_dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                last_update_ts = last_dt.isoformat()
                age_hours = round((now - last_dt).total_seconds() / 3600, 1)
                stale_hours = _FRESHNESS_STALE_HOURS.get(sid, _FRESHNESS_DEFAULT_STALE_HOURS)
                if age_hours <= stale_hours:
                    status = "fresh"
                elif meta.get("behavioral"):
                    status = "behavioral-stale"
                else:
                    status = "stale"
            elif meta.get("behavioral"):
                status = "behavioral-stale"
        except Exception as e:  # never let one source break the feed
            logger.warning("source_freshness: %s failed: %s", sid, e)
            status = "unknown"
        entry = {
            "id": sid,
            "label": meta["label"],
            "desc": meta["desc"],
            "category": meta["category"],
            "last_update": last_update,
            # #589: the real instant + this source's OWN registry-derived window, so the
            # front-end's freshness pulse is tied to an actual timestamp — never a fixed
            # decorative loop. Only present when a real last-write date exists.
            "last_update_ts": last_update_ts,
            "stale_hours": stale_hours,
            "age_hours": age_hours,
            "status": status,
            "is_behavioral": bool(meta.get("behavioral")),
        }
        # #746: manual-capture degraded stamp. For a hand-filled source (HAE /
        # Notion / MCP) that has gone quiet past its threshold, expose the honest
        # "dark N days" count so the board can say "manual source dark N days" —
        # the ADR-104 behavioral-absence treatment a device gap gets, never a
        # fabricated value. Automatic pipes carry no capture_channel, so they're
        # untouched here.
        manual_meta = _MANUAL_CAPTURE.get(sid)
        if manual_meta:
            entry["capture_channel"] = manual_meta["channel"]
            entry["manual"] = True
            if status in ("stale", "behavioral-stale"):
                entry["days_dark"] = _days_dark(last_update, now)
        # #1371: explicit cross-cycle provenance — the newest record predates the
        # current genesis, so its age is carried history, not a live-cycle outage.
        if last_update and last_update < EXPERIMENT_START:
            entry["carried"] = True
            entry["carried_from_cycle"] = _carried_from_cycle(sid, last_update, _g=_g)
        # D-4 (#468): apple_health is one partition fed by many sensors, so its single
        # "fresh" hides a months-dark CGM/BP/SoM/workout stream. Surface the per-datatype
        # liveness the freshness-checker stores so the darkness is visible.
        if sid == "apple_health":
            dts = _apple_health_datatypes(_g=_g)
            if dts:
                entry["datatypes"] = dts
                # #746: dark HAE streams now carry their days-dark + manual flag, so
                # the board can stamp "CGM dark 5d" and separate the hand-captured
                # streams (CGM/BP/SoM/water) from a passive device-stream gap.
                entry["dark_datatypes"] = [
                    {"label": d["label"], "days_dark": d.get("age_days"), "manual": bool(d.get("manual"))} for d in dts if d.get("dark")
                ]
        sources.append(entry)
        summary["total"] += 1
        if status == "fresh":
            summary["fresh"] += 1
        elif status in ("stale", "behavioral-stale", "unknown"):
            summary["stale"] += 1

    for sid, meta in _FRESHNESS_PAUSED.items():
        sources.append(
            {
                "id": sid,
                "label": meta["label"],
                "desc": meta["desc"],
                "category": meta["category"],
                "last_update": None,
                "age_hours": None,
                "status": "paused",
                "is_behavioral": False,
            }
        )
        summary["paused"] += 1
        summary["total"] += 1

    return _ok(
        {
            "sources": sources,
            "summary": summary,
            # #1371: the anchor the front-end labels provenance against.
            "experiment": {"genesis": EXPERIMENT_START, "cycle": current_cycle},
        },
        cache_seconds=300,
    )


def device_agreement(*, _g) -> dict:
    """GET /api/device_agreement — Whoop vs Garmin cross-device agreement on HRV + RHR.

    Garmin ingestion has been paused since 2026-06 (vendor anti-automation, ADR-074),
    so recent days may show no overlap — the historical window still stands as evidence.
    Always a shaped 200 (ADR-104 honest-gaps semantics): a thin/empty window says so
    explicitly rather than silently rendering nothing.
    """
    # Facade state injected via `_g` (the delegator's globals()) — same module the test patched.
    _query_source = _g["_query_source"]
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        whoop_items = _query_source("whoop", _DEVICE_AGREEMENT_START, today, include_pilot=True)
        garmin_items = _query_source("garmin", _DEVICE_AGREEMENT_START, today, include_pilot=True)
    except Exception as e:
        logger.error(f"[site_api] /api/device_agreement query failed: {e}")
        return _error(500, "device agreement unavailable")

    # Day-summary records only — Whoop workout sub-items (sk DATE#...#WORKOUT#...)
    # never carry resting_heart_rate/hrv, so this filter drops them for free.
    whoop_by_date = {i["date"]: i for i in whoop_items if i.get("date") and i.get("resting_heart_rate") is not None}
    garmin_by_date = {i["date"]: i for i in garmin_items if i.get("date") and i.get("resting_heart_rate") is not None}
    garmin_last_date = max((i.get("date") for i in garmin_items if i.get("date")), default=None)

    all_dates = sorted(set(whoop_by_date) & set(garmin_by_date))

    if not all_dates:
        return _ok(
            {
                "status": "unavailable",
                "reason": "No overlapping Whoop + Garmin days recorded.",
                "garmin_last_date": garmin_last_date,
            },
            cache_seconds=3600,
        )

    hrv_agree = hrv_minor = hrv_flag = 0
    rhr_agree = rhr_minor = rhr_flag = 0
    daily = []
    flagged = []

    for date in all_dates:
        w = whoop_by_date[date]
        g = garmin_by_date[date]
        row = {"date": date}
        flags = []

        whoop_hrv = w.get("hrv")
        garmin_hrv = g.get("hrv_last_night")
        if whoop_hrv is not None and garmin_hrv is not None:
            wh, gh = float(whoop_hrv), float(garmin_hrv)
            diff = abs(wh - gh)
            row.update({"whoop_hrv_ms": round(wh, 1), "garmin_hrv_ms": round(gh, 1), "hrv_abs_diff_ms": round(diff, 1)})
            if diff <= 10:
                row["hrv_agreement"] = "agree"
                hrv_agree += 1
            elif diff <= 20:
                row["hrv_agreement"] = "minor_variance"
                hrv_minor += 1
            else:
                row["hrv_agreement"] = "flag"
                hrv_flag += 1
                flags.append(f"HRV diff {diff:.0f}ms")

        whoop_rhr = w.get("resting_heart_rate")
        garmin_rhr = g.get("resting_heart_rate")
        if whoop_rhr is not None and garmin_rhr is not None:
            wr, gr = float(whoop_rhr), float(garmin_rhr)
            diff = abs(wr - gr)
            row.update({"whoop_rhr_bpm": round(wr, 1), "garmin_rhr_bpm": round(gr, 1), "rhr_abs_diff_bpm": round(diff, 1)})
            if diff <= 3:
                row["rhr_agreement"] = "agree"
                rhr_agree += 1
            elif diff <= 6:
                row["rhr_agreement"] = "minor_variance"
                rhr_minor += 1
            else:
                row["rhr_agreement"] = "flag"
                rhr_flag += 1
                flags.append(f"RHR diff {diff:.0f}bpm")

        daily.append(row)
        if flags:
            flagged.append({"date": date, "flags": flags})

    n = len(all_dates)
    hrv_days = hrv_agree + hrv_minor + hrv_flag
    rhr_days = rhr_agree + rhr_minor + rhr_flag
    hrv_rate = round(hrv_agree / hrv_days * 100, 1) if hrv_days else None
    rhr_rate = round(rhr_agree / rhr_days * 100, 1) if rhr_days else None
    rates = [r for r in (hrv_rate, rhr_rate) if r is not None]
    combined = round(sum(rates) / len(rates), 1) if rates else None

    if combined is None:
        confidence = "UNKNOWN — insufficient overlapping data"
    elif combined >= 80:
        confidence = "HIGH — devices closely agree; composite readiness score is reliable"
    elif combined >= 60:
        confidence = "MODERATE — minor inter-device variance; composite score is broadly reliable"
    else:
        confidence = "LOW — significant disagreement; investigate fit, positioning, or artifacts"

    # Newest-first, capped — aggregate stats above already cover the full window.
    daily_recent = list(reversed(daily))[:_DEVICE_AGREEMENT_DAILY_CAP]
    flagged_recent = list(reversed(flagged))[:_DEVICE_AGREEMENT_DAILY_CAP]

    return _ok(
        {
            "status": "ok",
            "period": {"start": all_dates[0], "end": all_dates[-1], "overlapping_days": n},
            "hrv_agreement": (
                {
                    "agree_days": hrv_agree,
                    "minor_days": hrv_minor,
                    "flagged_days": hrv_flag,
                    "agreement_rate_pct": hrv_rate,
                    "threshold_note": "Agree: <=10ms delta; minor: 10-20ms; flag: >20ms",
                }
                if hrv_days
                else None
            ),
            "rhr_agreement": (
                {
                    "agree_days": rhr_agree,
                    "minor_days": rhr_minor,
                    "flagged_days": rhr_flag,
                    "agreement_rate_pct": rhr_rate,
                    "threshold_note": "Agree: <=3bpm delta; minor: 3-6bpm; flag: >6bpm",
                }
                if rhr_days
                else None
            ),
            "device_confidence": confidence,
            "combined_agreement_rate_pct": combined,
            "daily": daily_recent,
            "flagged_disagreement_days": flagged_recent if flagged_recent else None,
            "garmin_last_date": garmin_last_date,
            "garmin_paused": bool(garmin_last_date and garmin_last_date < today),
            "interpretation": (
                "HRV delta is expected between devices (different sampling windows and algorithms); "
                "10-15ms variance is normal. RHR should agree within 3-5bpm; larger gaps suggest sensor "
                "placement or motion artifacts. Consistent small disagreement, not perfect agreement, is "
                "what real independent sensors produce — identical numbers would be the red flag."
            ),
        },
        cache_seconds=3600,
    )


def _parse_iso_ts(ts):
    """Best-effort ISO parse → aware UTC datetime, or None (never raises)."""
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def last_sync(*, _g) -> dict:
    """GET /api/last_sync — per registry source, the real last ingestion write + honest status.

    Returns {sources: [{id, label, last_write, last_seen, precision, stale_hours,
    status}], server_now}. The client computes and ticks the "ago" display
    (server_now closes clock skew). stale_hours (#589) is the SAME source_registry-
    derived window /api/source_freshness uses — so each source's pulse and status
    are tied to its OWN freshness window (e.g. Todoist's cadence-derived 72h), not
    a flat guess. status ∈ {fresh, stale, behavioral-stale, paused, unknown} with
    /api/source_freshness semantics: a behavioral lapse never reads as a broken
    pipe, a paused source says so, and nothing is faked (#1101)."""
    # Facade state injected via `_g` (the delegator's globals()) — same module the test patched.
    _FRESHNESS_DEFAULT_STALE_HOURS = _g["_FRESHNESS_DEFAULT_STALE_HOURS"]
    _FRESHNESS_PAUSED = _g["_FRESHNESS_PAUSED"]
    _FRESHNESS_SOURCES = _g["_FRESHNESS_SOURCES"]
    _FRESHNESS_STALE_HOURS = _g["_FRESHNESS_STALE_HOURS"]
    table = _g["table"]
    now = datetime.now(timezone.utc)
    sources = []
    for sid, meta in _FRESHNESS_SOURCES.items():
        last_write = None
        last_date = None
        failed = False
        try:
            kwargs = with_phase_filter(
                {
                    "KeyConditionExpression": Key("pk").eq(f"{USER_PREFIX}{sid}") & Key("sk").begins_with("DATE#"),
                    "ScanIndexForward": False,
                    "Limit": 3,  # today's record + possible sub-records; max() picks the true latest write
                    "ProjectionExpression": "sk, ingested_at, webhook_ingested_at",
                },
                # #1203: same cross-phase liveness basis as _latest_date_str — the pulse
                # must report a source's true last write even when its newest DATE#
                # predates the current cycle (post-reset phase=pilot records), or the
                # sync line masks a genuinely dark pipe with last_seen:null.
                include_pilot=True,
            )
            for it in table.query(**kwargs).get("Items", []):
                ts = str(it.get("webhook_ingested_at") or it.get("ingested_at") or "")
                if ts and (last_write is None or ts > last_write):
                    last_write = ts
                d = str(it.get("sk", "")).replace("DATE#", "")[:10]
                if d and (last_date is None or d > last_date):
                    last_date = d
        except Exception as e:
            logger.warning("last_sync: %s failed: %s", sid, e)
            failed = True
        stale_hours = _FRESHNESS_STALE_HOURS.get(sid, _FRESHNESS_DEFAULT_STALE_HOURS)
        last_seen, precision = None, None
        if last_write:
            last_seen, precision = last_write, "instant"
        elif last_date:
            parsed = _parse_iso_ts(last_date)
            if parsed:
                last_seen, precision = parsed.isoformat(), "day"
        if failed:
            status = "unknown"
        else:
            status = "behavioral-stale" if meta.get("behavioral") else "stale"
            seen_dt = _parse_iso_ts(last_seen) if last_seen else None
            if seen_dt and (now - seen_dt).total_seconds() / 3600 <= stale_hours:
                status = "fresh"
        sources.append(
            {
                "id": sid,
                "label": meta["label"],
                "last_write": last_write,
                "last_seen": last_seen,
                "precision": precision,
                "stale_hours": stale_hours,
                "status": status,
            }
        )
    for sid, meta in _FRESHNESS_PAUSED.items():
        sources.append(
            {
                "id": sid,
                "label": meta["label"],
                "last_write": None,
                "last_seen": None,
                "precision": None,
                "stale_hours": None,
                "status": "paused",
            }
        )
    return _ok({"sources": sources, "server_now": now.isoformat()}, cache_seconds=60)


def presence(*, _g) -> dict:
    """GET /api/presence — the honest "quiet stretch" state for the cockpit line +
    Story beat: is Matthew actively logging, or has he gone quiet?

    FAIL-CLOSED public projection: this builds the response field-by-field from an
    explicit allowlist and NEVER spreads the stored record — no passive_read
    internals, no retention/mood ever leak. Day-counts are already publicly
    disclosed via /api/source_freshness, so this is consistent with existing
    disclosure. Honest 'present' default before the first compute (front-end
    simply hides). Always a shaped 200.

    #975 amendment: per-channel last-logged marks ARE now public — the cockpit's
    "inputs" instrument-health row needs them (cycle 4 died of 14 silent days no
    standing surface showed). They're projected field-by-field below (label +
    mark only, same day-level granularity as /api/source_freshness), never by
    spreading the stored channel_detail."""
    # Facade state injected via `_g` (the delegator's globals()) — same module the test patched.
    _ENGAGEMENT_CHANNELS = _g["_ENGAGEMENT_CHANNELS"]
    table = _g["table"]
    try:
        resp = table.get_item(Key={"pk": USER_PREFIX + "engagement_state", "sk": "STATE#current"})
        rec = resp.get("Item") or {}
    except Exception as e:
        logger.warning("handle_presence read failed: %s", e)
        rec = {}

    rec = _decimal_to_float(rec)
    presence_class = rec.get("presence_class") or "present"
    returned = bool(rec.get("returned"))
    in_lull = presence_class in _PRESENCE_LOUD

    out = {
        "available": bool(rec),
        "presence_class": presence_class,
        "in_lull": in_lull,
        "gap_days": rec.get("gap_days"),
        "last_log_date": rec.get("last_food_log_date"),
        "channels_quiet_count": rec.get("channels_quiet_count") or len(rec.get("channels_quiet") or []),
        "passive_still_flowing": rec.get("passive_still_flowing"),
        "planned_pause": bool(rec.get("planned_pause")),
        "planned_pause_reason": rec.get("planned_pause_reason") or "",
        "returned": returned,
        "resumed_after_days": rec.get("resumed_after_days") if returned else None,
        "weight_delta_over_gap_lbs": rec.get("weight_delta_over_gap") if returned else None,
        "as_of": rec.get("date"),
    }

    # #975: per-channel freshness marks for the cockpit's "inputs" row. Iterate the
    # REGISTRY (not the stored record) so the channel set + labels are always the
    # engine's own, then merge in only the explicitly-projected mark fields from
    # channel_detail — never a spread. `quiet` derives from the registry stale
    # tolerance AT READ TIME, so it's correct even for records written before this
    # projection existed. Before the first compute (or on a failed read) the marks
    # are honest nulls and quiet is None — "unknown", never a scold.
    detail = rec.get("channel_detail") or {}
    channels = []
    for src, meta in _ENGAGEMENT_CHANNELS.items():
        det = detail.get(src) or {}
        gap = det.get("gap_days")
        channels.append(
            {
                "id": src,
                "label": meta["label"],
                "last_log_date": det.get("last_log_date"),
                "gap_days": gap,
                "quiet": (gap is None or gap > meta["stale_days"]) if rec else None,
                "primary": bool(meta.get("primary")),
            }
        )
    channels.sort(key=lambda c: not c["primary"])  # the primary (food) leads; stable sort keeps registry order after it
    out["channels"] = channels
    return _ok(out, cache_seconds=300)
