"""lambdas/web/site_api_freshness.py — pipeline liveness handlers split out of
site_api_data.py (#1654): source_freshness / last_sync / presence / device_agreement.
Handlers receive `_g` (the facade's globals()) from their thin delegator and read the
facade's injectable/monkeypatched state via `_g["<name>"]` — same object the test patched."""

from datetime import datetime, timezone

from boto3.dynamodb.conditions import Key
from common.pacific_time import PACIFIC as PT, parse_iso_utc  # #1964: THE one Pacific frame + ISO parser
from experiment.phase_filter import singleton_visible, with_phase_filter

from web.site_api_common import USER_PREFIX, _decimal_to_float, _error, _ok, logger
from web.site_api_phase_frame import archival_frame  # #2957 — cross-phase framing

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


def _carried_from_cycle(date_str: str, *, _g) -> int | None:
    """Which experiment attempt a pre-genesis record belongs to — a PURE function
    of the record's CONTENT date against the CYCLE_GENESES ledger (#2002).

    #1371 originally read an ADR-077 `cycle` attribute stamped on the record, but
    NO writer in the reset pipeline ever stamps `cycle` on raw partitions
    (restart_phase_tag writes only `phase`; the wipe stamps only tombstoned
    experiment-scoped intelligence), so the numbered chip was structurally
    unreachable — every carried source rendered the unnumbered fallback. Deriving
    from the date needs no extra read and handles hevy's sub-record-only shape
    (no plain DATE#{date} item, only DATE#…#WORKOUT#<uuid>) for free.

    Returns the highest cycle whose genesis is <= the date; None for a date that
    predates cycle 1 entirely (the unnumbered "a previous attempt" fallback stays
    the honest label — ADR-104: absence stated, never fabricated).
    """
    try:
        geneses = sorted(_g["CYCLE_GENESES"].items(), key=lambda kv: str(kv[1]))
    except Exception as e:
        logger.warning("source_freshness: carried-cycle derivation failed: %s", e)
        return None
    d = str(date_str)[:10]
    cycle = None
    for n, genesis in geneses:
        if d >= str(genesis)[:10]:
            cycle = int(n)
        else:
            break
    return cycle


def source_freshness(*, _g) -> dict:
    """GET /api/source_freshness — live pipeline status per data source.

    status ∈ {fresh, stale, behavioral-stale, paused}. Behavioral sources (manual
    logs) report "behavioral-stale" rather than "stale" so a lapse in logging never
    reads as a broken pipeline. Always a shaped 200 — sparse/empty data still renders.

    #1371: sources whose newest record predates the current genesis carry explicit
    cross-cycle provenance (`carried` + `carried_from_cycle`) and the payload carries
    the experiment anchor, so a Day-1 board can label a 110-day-old chip "carried
    from attempt 7" instead of rendering an unexplained ghost.

    #2798: `last_update` is a stored DATE# day key, NOT a Pacific calendar day. The
    payload therefore states its own frame — `pacific_today` board-wide, plus a
    per-row `last_update_ahead_of_pt` / `last_update_frame` stamp. See the frame block
    in the loop below for the full ruling; nothing here is clamped.
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
    # #2798: both calendars, taken from the SAME instant so they can never skew against
    # each other. `pt_today` is the reader-facing day — this page is Pacific-framed
    # (feedback_site_pacific_time; the PT-today guard since #2506, the gate clock since
    # #2675) — and it is computed server-side because the front-end cannot: a reader in
    # Tokyo has a different "today", and the site's frame is Pacific by decree, not by
    # viewer locale.
    pt_today = now.astimezone(PT).strftime("%Y-%m-%d")
    # utc-exempt(#2798): NOT a reader "today" — never rendered as a date. Used only to
    # PROVE that a stored day key sitting ahead of PT-today is tracking the UTC calendar
    # (see the frame block below), so the frame label is derived rather than asserted.
    utc_today = now.strftime("%Y-%m-%d")
    sources = []
    summary = {"fresh": 0, "stale": 0, "paused": 0, "total": 0}
    try:
        from coach.coach_checkin import read_cycle

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
        # #2798 (epic) — THE FRAME, stamped per row.
        #
        # THE RULING: `last_update` is a stored DATE# day key and for the near-real-time
        # sources that key is a **UTC** calendar day, deliberately and by audit. TD-19
        # Phase 2 (2026-05-03, docs/audits/TD-19_DATE_PARTITION_AUDIT.md) changed
        # health_auto_export_lambda.parse_date_str to convert the device's source-tz
        # timestamp to UTC *before* extracting the day, precisely so every source shares
        # one partition frame and cross-source aggregation stops undercounting. The key
        # is right. What was wrong is presenting it unqualified on a Pacific page.
        #
        # UTC rolls over at 17:00 PT, so between 17:00 PT and PT-midnight a source that
        # has just delivered serves tomorrow's calendar date to a reader whose own page
        # header says that day has not happened yet. The armed reader-truth judge caught
        # exactly that on post-deploy run 33040437876 ("LAST UPDATE 2026-08-27 6h but
        # today is 2026-08-26. This is a future date") and gated CI on it — real for 7
        # hours a day, invisible for the other 17, the same shape as #3206/#3222 one
        # layer out.
        #
        # THE VALUE IS NOT CLAMPED. Clamping a legitimately-UTC day would hide a record
        # that genuinely exists — a worse failure than the bug, and the reason this is a
        # label rather than a max(). The label is DERIVED at request time, never asserted
        # from a table: a row is stamped frame="utc" only when its stored day IS the
        # current UTC calendar day, which is itself the proof that this key tracks UTC.
        # A date further ahead than UTC-today is a genuine anomaly (bad payload, bad
        # backfill), earns NO frame label, and the front-end flags it loudly instead of
        # explaining it away as a timezone artifact.
        if last_update and last_update > pt_today:
            entry["last_update_ahead_of_pt"] = True
            if last_update == utc_today:
                entry["last_update_frame"] = "utc"
        # #1371: explicit cross-cycle provenance — the newest record predates the
        # current genesis, so its age is carried history, not a live-cycle outage.
        if last_update and last_update < EXPERIMENT_START:
            entry["carried"] = True
            entry["carried_from_cycle"] = _carried_from_cycle(last_update, _g=_g)
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
                # #2001: when the checker exhausted its deep lookback without a hit,
                # forward the floor so the board can say "dark >400d" — the honest
                # bound (ADR-104), never an unnumbered shrug when a bound is known.
                dark_rows = []
                for d in dts:
                    if not d.get("dark"):
                        continue
                    row = {"label": d["label"], "days_dark": d.get("age_days"), "manual": bool(d.get("manual"))}
                    if d.get("age_days") is None and d.get("age_floor_days") is not None:
                        row["days_dark_floor"] = int(d["age_floor_days"])
                    dark_rows.append(row)
                entry["dark_datatypes"] = dark_rows
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
            # #2798: the page's OWN calendar day, on the Pacific clock. Every consumer
            # that renders a `last_update` date now has the frame to render it against
            # without guessing from the browser's timezone.
            "pacific_today": pt_today,
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
    EXPERIMENT_START = _g["EXPERIMENT_START"]
    today = datetime.now(PT).strftime("%Y-%m-%d")
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
            # #2957: `garmin_paused` explains WHY the window stopped moving, but says
            # nothing about whether it belongs to the live cycle — a 30-row "night by
            # night" table read as current on a Day-8 cycle-14 page even with the pause
            # note above it. Frame the window itself, off its own newest night (the
            # most favorable date for still being in-cycle): if even that predates the
            # genesis, none of the table does. Same primitive the lab-notes reactions
            # and the wrong-page catches use — the reader-truth judge reads the same
            # frame either way.
            "archival": archival_frame(all_dates[-1], EXPERIMENT_START),
            "interpretation": (
                "HRV delta is expected between devices (different sampling windows and algorithms); "
                "10-15ms variance is normal. RHR should agree within 3-5bpm; larger gaps suggest sensor "
                "placement or motion artifacts. Consistent small disagreement, not perfect agreement, is "
                "what real independent sensors produce — identical numbers would be the red flag."
            ),
        },
        cache_seconds=3600,
    )


# #1964: the private `_parse_iso_ts` fork that lived here is gone — its
# tzinfo-backfill semantic IS what `common.pacific_time.parse_iso_utc` adopted as
# the canonical answer, so call sites below use the shared helper directly and
# this module no longer carries a second, drift-capable ISO parser.


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
            parsed = parse_iso_utc(last_date)
            if parsed:
                last_seen, precision = parsed.isoformat(), "day"
        if failed:
            status = "unknown"
        else:
            status = "behavioral-stale" if meta.get("behavioral") else "stale"
            seen_dt = parse_iso_utc(last_seen) if last_seen else None
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
        # #1895: honor the restart tombstone — engagement_state is wiped ("all") and
        # tombstoned, not deleted, and get_item bypasses the query-level phase filter.
        # Without this, /api/presence reports the wiped cycle's presence/quiet-stretch
        # as current until the next engagement compute runs. `available: false` (the
        # empty-record path below) is the honest answer in that window.
        rec = resp.get("Item") or {}
        if not singleton_visible(rec):
            rec = {}
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
