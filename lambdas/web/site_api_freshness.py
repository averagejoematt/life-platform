"""lambdas/web/site_api_freshness.py — pipeline liveness handlers split out of
site_api_data.py (#1654): source_freshness / last_sync / presence / device_agreement.
Handlers receive `_g` (the facade's globals()) from their thin delegator and read the
facade's injectable/monkeypatched state via `_g["<name>"]` — same object the test patched."""

from datetime import datetime, timezone

from boto3.dynamodb.conditions import Key
from common.pacific_time import (  # #1964/#3257: THE one Pacific frame + parser (the day-key anchor now runs inside instrument_presence.source_liveness)
    PACIFIC as PT,
    parse_iso_utc,
)
from experiment.phase_filter import singleton_visible, with_phase_filter
from health import instrument_presence  # #4217: the ONE liveness derivation — the coach absence gate reads these same functions
from ingestion.source_registry import SOURCE_REGISTRY, availability_facet, caveated_source_ids  # #3615/#3516: one absence story

from web import instruments  # #4980: the two instruments' public words + the agreement study's state
from web.site_api_common import USER_PREFIX, _decimal_to_float, _error, _ok, logger
from web.site_api_phase_frame import archival_frame  # #2957 — cross-phase framing

_APPLE_RHR_FIELD = "resting_heart_rate_apple"  # health_auto_export_lambda tier-2 field (Apple Watch only)
_DEVICE_AGREEMENT_HRV_NOTE = "HRV is not compared: Whoop reports RMSSD and Apple reports SDNN — two different statistics."
_DEVICE_AGREEMENT_DAILY_CAP = 90  # most-recent N overlap days in the payload; aggregates cover the full window
# #5042: the agreement study's floor (#4974 — 30 dual-wear nights). Below it the payload states
# n and the era start and returns no verdict: a 100% agreement rate over 3 nights is not a finding.
_DEVICE_AGREEMENT_MIN_NIGHTS = 30


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
    # #4217: the read itself lives in health.instrument_presence so the coach absence gate
    # and this board answer "when did this source last write?" with ONE function.
    return instrument_presence.latest_date_str(_g["table"], source, include_pilot=True)  # #1203: liveness reads every phase


def _apple_health_datatypes(*, _g):
    """Per-datatype HAE liveness the freshness-checker stores (D-4/#468). None if absent."""
    # Facade state injected via `_g` (the delegator's globals()) — same module the test patched.
    # #4217: the sentinel read lives in health.instrument_presence — the glucose coach's
    # absence is decided by the SAME rows this board serves as `datatypes[]`.
    return instrument_presence.datatype_liveness(_g["table"])


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


#: #3615: the sources whose absence needs a stated reason — DERIVED from the registry,
#: never a list here (a source becoming paused must not silently lose its caveat).
_CAVEATED_SOURCE_IDS = caveated_source_ids()


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
    pt_now = now.astimezone(PT)
    pt_today = pt_now.strftime("%Y-%m-%d")
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
                # #3257: ANCHOR THE DAY IN THE FRAME THAT NAMES IT. This line used to be
                # `.replace(tzinfo=timezone.utc)` for all 12 board sources, of which 11 are
                # PACIFIC-keyed (ingestion_framework stamps pacific_today()). That put those
                # days' start 7h (PDT) / 8h (PST) before they began, so a record stamped with
                # today's Pacific date was served as 21.7h old in the same payload that
                # reported `pacific_today` — verified live 2026-08-27. apple_health keeps the
                # UTC anchor (TD-19 Phase 2), which is why the frame is resolved PER SOURCE
                # from the registry facet rather than swept to Pacific wholesale: a blanket
                # Pacific anchor would make apple_health's age NEGATIVE for the 7h a day that
                # UTC-today runs ahead of PT-today. Same helper the ops checker uses, so the
                # public board and the alert can no longer disagree about one key (452929f17
                # fixed one of the two and created that disagreement).
                #
                # #3913: whoop joined apple_health on the UTC side — and the row #3257 quoted
                # as ITS evidence was whoop's, so this call site was over-correcting it by the
                # same 7h it had just removed from the other ten. Nothing here changes: the
                # facet moved, the arithmetic is unchanged, and that is what "resolve the frame
                # per source" is FOR. Measured: 2,249 of 2,249 straddling whoop rows are keyed
                # by the UTC day (#3677), because whoop's fetch_day turns each Pacific date
                # LABEL into a UTC WINDOW.
                #
                # #4217: the arithmetic itself is health.instrument_presence.source_liveness —
                # the coach absence gate runs the same function, so "stale" here and "dark"
                # there are one verdict.
                stale_hours = _FRESHNESS_STALE_HOURS.get(sid, _FRESHNESS_DEFAULT_STALE_HOURS)
                _live = instrument_presence.source_liveness(
                    date_str, sid, now, stale_hours=stale_hours, behavioral=bool(meta.get("behavioral"))
                )
                last_update_ts = _live["last_update_ts"]
                age_hours = _live["age_hours"]
                status = _live["status"]
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
                # #3257: `_days_dark` does `now.date() - last.date()`, so the DAY of `now`
                # is the whole arithmetic. A UTC `now` rolls over at 17:00 PT, which made
                # the reader-facing "dark N days" stamp read one day too high every
                # evening — 7 hours a day, invisible for the other 17 (the #3206 shape).
                # `pt_now` is the SAME instant, in the frame the page is written in.
                entry["days_dark"] = _days_dark(last_update, pt_now)
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
        # #3615 box 3: a source the registry expects to lag ("~24h behind by design",
        # a 336h delivery cadence) carries the registry's OWN reason for the gap, so a
        # designed cadence is never rendered as a silence that needs explaining.
        if sid in _CAVEATED_SOURCE_IDS:
            _facet = availability_facet(sid)
            entry["absence_status"] = _facet["status"]
            entry["absence_cause"] = _facet["reason"]
            entry["absence_caveat"] = _facet["caveat"]
        sources.append(entry)
        summary["total"] += 1
        if status == "fresh":
            summary["fresh"] += 1
        elif status in ("stale", "behavioral-stale", "unknown"):
            summary["stale"] += 1

    for sid, meta in _FRESHNESS_PAUSED.items():
        # #3615 box 3: a paused row used to carry `last_update: None` and no duration at
        # all, so this board said "paused" while /api/status said "stopped 97d ago. Check
        # auth/webhook" about the same source on the same night. One absence, two stories.
        # The DURATION is the source's own newest record (the same helper every other row
        # on this board uses) and the CAUSE is the registry's own facet — neither is
        # composed here, so a pause can never be narrated as a broken pipe again.
        facet = availability_facet(sid)
        paused_last_update = None
        days_dark = None
        try:
            paused_last_update = _latest_date_str(sid, _g=_g)
            if paused_last_update:
                days_dark = (pt_now.date() - datetime.strptime(paused_last_update[:10], "%Y-%m-%d").date()).days
        except Exception as e:  # never let one paused source break the feed
            logger.warning("source_freshness: paused source %s duration failed: %s", sid, e)
        sources.append(
            {
                "id": sid,
                "label": meta["label"],
                "desc": meta["desc"],
                "category": meta["category"],
                "last_update": paused_last_update,
                "days_dark": days_dark,
                "age_hours": None,
                "status": "paused",
                "is_behavioral": False,
                "absence_status": facet["status"],
                "absence_cause": facet["reason"],
                "absence_caveat": facet["caveat"],
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


def _agreement_band(diff: float) -> str:
    """One night's resting-HR agreement band (<=3 bpm agree, <=6 minor, else flag)."""
    if diff <= 3:
        return "agree"
    return "minor_variance" if diff <= 6 else "flag"


def _agreement_nights(whoop_by_date: dict, apple_by_date: dict) -> list:
    """`[(date, band)]` oldest first, for every night both devices recorded a resting HR.

    #4980: the bpm values themselves never leave this function. The Apple Watch's resting heart
    rate is TIER_INTERNAL (lambdas/privacy/field_tiers.py — Whoop's ADR-155 publication consent
    does not extend to a second instrument), so the public payload carries a night's date and,
    once the study has ruled, its band; never the watch's number, Whoop's beside it, or the gap
    between them (Whoop's value plus the gap IS the watch's value)."""
    nights = []
    for d in sorted(set(whoop_by_date) & set(apple_by_date)):
        diff = abs(float(whoop_by_date[d]["resting_heart_rate"]) - float(apple_by_date[d][_APPLE_RHR_FIELD]))
        nights.append((d, _agreement_band(diff)))
    return nights


def _confidence(rate):
    """The device-confidence words for a ruled agreement rate."""
    if rate is None:
        return "UNKNOWN — insufficient overlapping data"
    if rate >= 80:
        return "HIGH — devices closely agree; composite readiness score is reliable"
    if rate >= 60:
        return "MODERATE — minor inter-device variance; composite score is broadly reliable"
    return "LOW — significant disagreement; investigate fit, positioning, or artifacts"


def _ruled_agreement(nights: list) -> dict:
    """The agreement figures — published ONLY once the study has ruled (#4980, #4974)."""
    counts = {b: sum(1 for _, x in nights if x == b) for b in ("agree", "minor_variance", "flag")}
    rate = round(counts["agree"] / len(nights) * 100, 1) if nights else None
    recent = list(reversed(nights))[:_DEVICE_AGREEMENT_DAILY_CAP]
    flagged = [{"date": d} for d, b in recent if b == "flag"]
    return {
        "rhr_agreement": {
            "agree_days": counts["agree"],
            "minor_days": counts["minor_variance"],
            "flagged_days": counts["flag"],
            "agreement_rate_pct": rate,
            "threshold_note": "Agree: <=3bpm delta; minor: 3-6bpm; flag: >6bpm",
        },
        "device_confidence": _confidence(rate),
        "combined_agreement_rate_pct": rate,
        "daily": [{"date": d, "rhr_agreement": b} for d, b in recent],
        "flagged_disagreement_days": flagged or None,
    }


def _unruled_agreement() -> dict:
    """Before the study rules: no rate, no verdict, no per-night band — the nights are counted only."""
    return {
        "rhr_agreement": None,
        "device_confidence": None,
        "combined_agreement_rate_pct": None,
        "daily": [],
        "flagged_disagreement_days": None,
    }


def _study_reason(state: str, n: int, watch_start: str) -> str:
    """One honest sentence for where the agreement study stands."""
    if state == "collecting":
        return f"Too few nights to compare yet: {n} of the {_DEVICE_AGREEMENT_MIN_NIGHTS} the agreement study needs, the Apple Watch from {watch_start}."
    if state == "awaiting_ruling":
        return f"{n} nights recorded on both devices since {watch_start}. The comparison has enough nights; its result is published once it has been read and ruled on."
    return ""


def device_agreement(*, _g) -> dict:
    """GET /api/device_agreement — Whoop vs Apple Watch, the two instruments (#735, #4976, #4980).

    #4976: re-pointed from Garmin (its direct feed is retired, #4640) to the Apple Watch, worn
    nightly (owner ruling 2026-10-17 b). HRV is NOT compared: Whoop reports RMSSD and Apple
    reports SDNN, two different statistics; `hrv_agreement` stays null with `hrv_note` saying why.

    #4980: the payload never carries a heart-rate VALUE (see `_agreement_nights`), and states no
    agreement until the dual-wear study has ruled (`web.instruments.study`): below 30 nights it is
    `too_few_nights`, at 30+ with no ruling `awaiting_ruling`, and only a ruled study gets `ok`
    with the counts. `instruments` says which device answers for each measure, from METRIC_TRUTH.
    Always a shaped 200 (ADR-104 honest-gaps semantics).
    """
    _query_source = _g["_query_source"]
    EXPERIMENT_START = _g["EXPERIMENT_START"]
    # #5042: the WATCH era only (the registry's `watch_first_day` facet; `_g` may override it,
    # tests only) — before it the partition's resting HR came from other writers.
    era = SOURCE_REGISTRY["apple_health"]["watch_first_day"]
    watch_start = _g.get("APPLE_WATCH_FIRST_DAY") or era["date"]
    watch_era = {"start": watch_start, "determined_by": era["determined_by"]}
    today = datetime.now(PT).strftime("%Y-%m-%d")
    try:
        whoop_items = _query_source("whoop", watch_start, today, include_pilot=True)
        apple_items = _query_source("apple_health", watch_start, today, include_pilot=True)
    except Exception as e:
        logger.error(f"[site_api] /api/device_agreement query failed: {e}")
        return _error(500, "device agreement unavailable")

    # Day-summary records only (a Whoop workout sub-item never carries resting_heart_rate), and
    # the era floor applied here too, so a reader handing back older rows cannot let one in.
    whoop_by_date = {
        i["date"]: i for i in whoop_items if i.get("date") and i["date"] >= watch_start and i.get("resting_heart_rate") is not None
    }
    apple_by_date = {
        i["date"]: i for i in apple_items if i.get("date") and i["date"] >= watch_start and i.get(_APPLE_RHR_FIELD) is not None
    }
    nights = _agreement_nights(whoop_by_date, apple_by_date)
    n = len(nights)
    study = instruments.study(n, _DEVICE_AGREEMENT_MIN_NIGHTS)
    common = {
        "n_nights": n,
        "min_nights": _DEVICE_AGREEMENT_MIN_NIGHTS,
        "watch_era": watch_era,
        "devices": ["Whoop", "Apple Watch"],
        "hrv_agreement": None,
        "hrv_note": _DEVICE_AGREEMENT_HRV_NOTE,
        "apple_first_date": min(apple_by_date, default=None),
        "study": study,
        "instruments": instruments.instruments(),
    }
    if not nights:
        reason = f"No overlapping Whoop + Apple Watch resting-heart-rate nights recorded yet (the watch from {watch_start})."
        return _ok({"status": "unavailable", "reason": reason, **common}, cache_seconds=3600)

    state = study["state"]
    status = {"collecting": "too_few_nights", "awaiting_ruling": "awaiting_ruling"}.get(state, "ok")
    return _ok(
        {
            "status": status,
            "period": {"start": nights[0][0], "end": nights[-1][0], "overlapping_days": n},
            **common,
            "too_few_reason": _study_reason(state, n, watch_start) if state == "collecting" else None,
            "study_reason": _study_reason(state, n, watch_start) or None,
            **(_ruled_agreement(nights) if state == "ruled" else _unruled_agreement()),
            # #2957: frame the window off its own newest night (archival_frame, the same primitive
            # every other cross-phase surface uses).
            "archival": archival_frame(nights[-1][0], EXPERIMENT_START),
            "interpretation": (
                "RHR should agree within 3-5bpm; larger gaps suggest sensor "
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
