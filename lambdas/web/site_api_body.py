"""lambdas/web/site_api_body.py — the live body reading (/api/vitals, /api/snapshot).

Split out of ``site_api_vitals.py`` (#1654 — god-module breakup). One seam: **what
the body is doing right now.** `/api/vitals` is the platform's highest-traffic
endpoint (weight, HRV, recovery, RHR, sleep, resolved through the ONE truth spine
in ``vitals_resolver``); `/api/weight_progress` is its 180-day weight series; and
`/api/snapshot` is the single-call homepage combo that fans out to vitals +
journey + character.

The routed handler entrypoints stay in the ``site_api_vitals`` facade as thin
delegators; the logic lives here. Handlers receive the facade's ``globals()`` as
``_g`` and read the monkeypatched/injectable state via ``_g["<name>"]``. That
matters twice over here: ``test_home_og_day_frame_1955`` freezes the module's
``datetime`` class, and ``test_pre_start_countdown`` stubs ``handle_vitals`` /
``handle_journey`` / ``handle_character`` / ``_latest_readiness`` on the facade and
then calls ``handle_snapshot`` — so snapshot's fan-out goes back through ``_g``,
reaching the facade delegators (and therefore the stubs) rather than binding the
real functions at import time.

This module does NOT import the facade; no import cycle. Every other shared helper
comes straight from ``site_api_common`` (identical binding semantics to the
pre-split module).
"""

import json
from datetime import timedelta, timezone

from common.pacific_time import pacific_day_n  # #1955 — THE one PT day-index formula
from health import weight_trend  # shared weekly-rate + projection

from web.site_api_common import (
    CORS_HEADERS,
    NIGHT_OF_FRAME,
    PT,
    USER_PREFIX,
    _error,
    _ok,
    _window_span,
    logger,
    night_of_for,
)

# #1084 / ADR-105: a "30d average" fabricated from one or two readings is not an
# average. Below this floor the avg field reads None (its n is surfaced alongside)
# and front-ends self-hide on null.
_MIN_AVG_N = 3


def vitals(date: str | None = None, *, _g) -> dict:
    """
    GET /api/vitals[?date=YYYY-MM-DD]
    Returns: current weight, HRV, recovery, RHR, sleep hours, 30d trends.
    Cache: 300s (5 min) — feels real-time, Lambda fires ~12x/hour at 50k traffic.
    With ?date= (Phase 4 historical window): the cockpit AS OF that date — latest
    readings on-or-before it, 30d trends ending there, pilot/prior-cycle records
    included, a future date clamps to today, cached a day (the past is immutable).
    """
    EXPERIMENT_START = _g["EXPERIMENT_START"]
    _latest_item = _g["_latest_item"]
    _latest_item_asof = _g["_latest_item_asof"]
    _query_source = _g["_query_source"]
    datetime = _g["datetime"]
    table = _g["table"]
    vitals_resolver = _g["vitals_resolver"]

    import re as _re

    if date and not _re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        return _error(400, "date must be YYYY-MM-DD")
    if date:
        # The regex above validates SHAPE only: 2026-02-30, 2026-13-45 and 0001-01-01
        # all match it. Calendar-validate BEFORE the string clamp below — otherwise an
        # impossible date either sorts under today and reaches the unguarded strptime
        # (2026-02-30 -> ValueError -> 502) or survives it and overflows the timedelta
        # arithmetic (0001-01-01 -> OverflowError -> 502). Both were reachable
        # unauthenticated over HTTP.
        try:
            _probe = datetime.strptime(date, "%Y-%m-%d")
            _probe.replace(tzinfo=timezone.utc) - timedelta(days=30)
        except (ValueError, OverflowError):
            return _error(400, "date must be a real calendar date")
    ip = bool(date)  # ADR-058: include pilot/prior-cycle records only when time-travelling
    # #1922: the site's day frame is PACIFIC (every user-facing date on the site
    # is PT). Anchoring this handler's "today" in UTC made the payload claim
    # "Day N+1" every PT evening — window_disclosure said Day 7 while the site's
    # phase truth (and qa-smoke's reader_truth ground truth, which is PT) said
    # Day 6, and _window_span could declare a 7-day span on Day 6. No data rows
    # dated ahead of PT-today exist (ingestion crons run 4am-10pm PT), so the
    # query end-bound is unaffected in practice; only the day frame honest-izes.
    _now = datetime.now(PT).strftime("%Y-%m-%d")
    anchor = min(date, _now) if date else _now  # clamp a future scrub to today
    _anchor_dt = datetime.strptime(anchor, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    today = anchor
    d30 = (_anchor_dt - timedelta(days=30)).strftime("%Y-%m-%d")
    d7 = (_anchor_dt - timedelta(days=7)).strftime("%Y-%m-%d")
    if not ip:
        # #1084 / ADR-077 "clamped, not hidden": LIVE trailing windows never reach
        # across genesis into prior-cycle rows — at a reset the window shrinks
        # honestly instead. (The phase filter hides *tagged* pilot rows, but rows
        # ingested between reset-tagging and genesis carry no tag; the date clamp
        # is deterministic either way.) Time-travel (?date=) keeps the full reach —
        # include_pilot=True is the deliberate ADR-058 contract there. A staged
        # FUTURE genesis makes start > end, which _query_source treats as "no data
        # yet" ([]), so this can never 500.
        d30 = max(d30, EXPERIMENT_START)
        d7 = max(d7, EXPERIMENT_START)

    # Whoop (recovery, HRV, RHR, sleep)
    whoop_7d = _query_source("whoop", d7, today, include_pilot=ip)
    whoop_30d = _query_source("whoop", d30, today, include_pilot=ip)

    # Latest reading — LIVE reads come from the ONE canonical resolver (#1369),
    # so /api/vitals, /api/snapshot, /api/pulse and the public_stats writers can
    # never disagree about the same morning's numbers. Time-travel (?date=) keeps
    # the as-of-anchor window semantics, with the same honest-null shape.
    if date:
        _lt = sorted([w for w in whoop_7d if w.get("recovery_score") is not None], key=lambda x: x.get("sk", ""), reverse=True)
        _lt = _lt[0] if _lt else {}
        _lt_sk = _lt.get("sk", "").replace("DATE#", "")[:10] or None
        _vr = {
            "recovery_pct": float(_lt["recovery_score"]) if _lt.get("recovery_score") else None,
            "hrv_ms": float(_lt["hrv"]) if _lt.get("hrv") else None,
            "rhr_bpm": float(_lt["resting_heart_rate"]) if _lt.get("resting_heart_rate") else None,
            "sleep_hours": float(_lt["sleep_duration_hours"]) if _lt.get("sleep_duration_hours") else None,
            "recovery_as_of": _lt_sk,
            "sleep_as_of": _lt_sk,
        }
        _vr["recovery_status"] = vitals_resolver.recovery_status(_vr["recovery_pct"])
    else:
        _vr = vitals_resolver.resolve_vitals(table, USER_PREFIX)

    # #2344: as_of_date is a SINGLE document-level date stamped over fields that
    # can genuinely carry different as-of dates (recovery finalizes separately
    # from sleep; weight is a same-day behavioral source that may lag both).
    # Hoisted here (was computed further down, after the disclosure text was
    # already built) so the divergence sentence below can actually see it.
    _recovery_as_of = _vr.get("recovery_as_of")
    _sleep_as_of = _vr.get("sleep_as_of")
    _as_of = _recovery_as_of or _sleep_as_of or today

    # 30d averages + trends. Order by date (oldest→newest) explicitly so the
    # half-vs-half trend is chronological by construction, not dependent on query
    # return order (the prior constant-key sort was a no-op that only worked because
    # the query happened to return ascending sk). See AUDIT BUG-04. rhr_trend below
    # passes reversed values — that's the deliberate "lower is better" inversion.
    whoop_30d_sorted = sorted(whoop_30d, key=lambda w: w.get("sk", ""))
    hrv_vals = [float(w["hrv"]) for w in whoop_30d_sorted if w.get("hrv")]
    rhr_vals = [float(w["resting_heart_rate"]) for w in whoop_30d_sorted if w.get("resting_heart_rate")]
    # #1917: how many days the "30d" HRV window ACTUALLY spans. Time-travel
    # (?date=) keeps the full 30-day reach by contract (ADR-058), so it is only
    # the LIVE path that genesis clamps — mirror the d30 computation above.
    _hrv_window = {"start": d30, "requested_days": 30, "actual_days": 30, "full": True} if ip else _window_span(d30, today, 30)
    _hrv_avg = round(sum(hrv_vals) / len(hrv_vals), 1) if len(hrv_vals) >= _MIN_AVG_N else None

    def trend(vals):
        if len(vals) < 6:
            return "insufficient_data"
        mid = len(vals) // 2
        first_avg = sum(vals[:mid]) / len(vals[:mid])
        second_avg = sum(vals[mid:]) / len(vals[mid:])
        if second_avg > first_avg * 1.03:
            return "improving"
        if second_avg < first_avg * 0.97:
            return "declining"
        return "stable"

    # G-3 → #491/M-6: latest weight via the ONE shared resolution
    # (weight_trend.latest_weight): Withings backscan + a 7-day apple_health
    # window. The old code inspected only the single latest apple_health item —
    # usually a steps record — so the Apple fallback engaged same-day only.
    # Time-travel: the latest weigh-in on-or-before the anchor (else the live latest).
    withings_latest = _latest_item_asof("withings", today, ip) if date else _latest_item("withings")
    try:
        _ah_start = (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y-%m-%d")
        if not ip:
            _ah_start = max(_ah_start, EXPERIMENT_START)  # #1084: same live genesis clamp as d7/d30
        _ah_7d = _query_source("apple_health", _ah_start, today, include_pilot=ip)
    except Exception:
        _ah_7d = []
    _lw = weight_trend.latest_weight([withings_latest] if withings_latest else [], _ah_7d)
    current_weight = _lw["weight_lbs"]
    weight_as_of = _lw["as_of"]

    withings_30d = _query_source("withings", d30, today, include_pilot=ip)
    # #1917: keep the reading DATES alongside the values. The delta's honest window
    # is the span between the first and last weigh-in actually used — not the query
    # window (which may be genesis-clamped) and not a nominal 30 days.
    _w_pairs = sorted(
        [(w.get("sk", "").replace("DATE#", "")[:10], float(w["weight_lbs"])) for w in withings_30d if w.get("weight_lbs")],
        key=lambda p: p[0],
    )
    weight_vals = [v for _, v in _w_pairs]
    weight_delta = round(weight_vals[-1] - weight_vals[0], 1) if len(weight_vals) >= 2 else None
    weight_delta_window_days = None
    if len(_w_pairs) >= 2:
        try:
            weight_delta_window_days = (datetime.strptime(_w_pairs[-1][0], "%Y-%m-%d") - datetime.strptime(_w_pairs[0][0], "%Y-%m-%d")).days
        except Exception:
            weight_delta_window_days = None
    # The legacy `_30d`-named key is truthful-or-absent (see _window_span):
    # it carries the value only when the span really is >= 30 days.
    weight_delta_30d = weight_delta if (weight_delta_window_days or 0) >= 30 else None

    # #1917 follow-up: say what the window numbers MEAN, in words.
    #
    # A bare `weight_delta_window_days: 5` sitting beside "Day 6" is ambiguous —
    # 5 days of *span* between two weigh-ins is not 5 days of *history*, and
    # nothing in the payload said which. qa-smoke's reader_truth reproducibly read
    # it as a contradiction (twice, differently worded), and a human reader has
    # exactly the same ambiguity with no way to resolve it. Both are fixed by
    # stating the relationship rather than leaving it to be inferred, which is the
    # ADR-105 "the claim carries its context" idiom already used by `disclosure`
    # on /api/fulfillment and `coverage_floor` elsewhere.
    # #1955: the shared PT day-index helper — the same formula the home og uses,
    # so this disclosure and the share card cannot disagree on the day number.
    _day_n = pacific_day_n(EXPERIMENT_START, on_date=today)
    if _day_n < 1:
        # Pre-start countdown (#931/#939): the cycle hasn't begun, so "Day 0 of the
        # cycle that began …" would claim a start that hasn't happened (reader-truth
        # finding at the cycle-13 reset, genesis in the future).
        _bits = [f"The cycle begins {EXPERIMENT_START}; today is pre-start, so no cycle data exists yet."]
    else:
        _bits = [f"Today is Day {_day_n} of the cycle that began {EXPERIMENT_START}, so at most {_day_n} day(s) of data can exist."]
    if weight_delta is not None and weight_delta_window_days is not None:
        _bits.append(
            f"weight_delta_lbs is the change between two weigh-ins {weight_delta_window_days} day(s) apart, both inside that window."
        )
    if _hrv_avg is not None:
        _bits.append(f"hrv_avg_ms averages {len(hrv_vals)} reading(s) spanning {_hrv_window['actual_days']} day(s).")
    _bits.append(
        "Fields named *_30d stay null until a genuine 30-day window exists; none of the numbers above claims more history than the cycle has."
    )
    # #2344: as_of_date is one document-level date stamped over fields whose real
    # as-of dates differ. Measured live 2026-08-09: weight_as_of 2026-08-03 next to
    # as_of_date 2026-08-08 — NOT a stale number (cycle 12 genesis is 2026-08-03 and
    # weight is a behavioral source; a Day-1 weigh-in can genuinely be the newest one
    # that exists), but the document only ever said "as of 2026-08-08" and let the
    # reader infer the weight was current too. Name the divergence instead of hiding
    # it, and ONLY when it's real — most days weight_as_of == as_of_date and this
    # stays silent.
    if weight_as_of and weight_as_of != _as_of:
        _bits.append(
            f"weight_as_of ({weight_as_of}) is the most recent weigh-in and differs from as_of_date ({_as_of}) — "
            "weight is a same-day behavioral source updated only when a scale reading exists, so an older weigh-in "
            "can still be the newest one on record."
        )
    if _recovery_as_of and _sleep_as_of and _recovery_as_of != _sleep_as_of:
        _bits.append(
            f"recovery_pct/hrv_ms/rhr_bpm are as of {_recovery_as_of} while sleep_hours is as of {_sleep_as_of} — "
            "recovery and sleep finalize from separate Whoop records."
        )
    _window_disclosure = " ".join(_bits)

    # DPR-1.20: Page freshness for nav badges
    _today_iso = datetime.now(timezone.utc).isoformat()
    # Temporal frame: sleep/recovery/HRV/RHR are wake-date-keyed (stored under the
    # morning they set up). The reading came from the night BEFORE that morning, so
    # night_of = as_of - 1 day. Surfacing this lets the front-end say "the night of
    # <night_of>" precisely, even when the latest record lags a day or two. (Weight,
    # by contrast, is same-day "today" — see weight_as_of.)
    # #1923: ONE implementation of the frame, in site_api_common. An inline offset
    # here is what let an AI judge re-litigate the contract every run.
    _night_of = night_of_for(_as_of)
    # Nutrition is a manual end-of-day upload — structurally ~24h behind. Its freshness
    # is the latest COMPLETE day (normally yesterday), NOT today. Hardcoding _today_iso
    # here (the old behavior) made the nutrition page read "as of now" when today's
    # intake simply hasn't been uploaded yet. Mirror /physical's weight_as_of pattern.
    _nutrition_as_of = None
    try:
        _mf = _query_source("macrofactor", (datetime.now(PT) - timedelta(days=10)).strftime("%Y-%m-%d"), today)
        _mf_dates = [(m.get("date") or m.get("sk", "").replace("DATE#", "")) for m in _mf]
        _nutrition_as_of = max([d for d in _mf_dates if d], default=None)
    except Exception:
        _nutrition_as_of = None
    page_freshness = {
        "/live": _today_iso,
        "/character": _today_iso,
        "/sleep": _as_of + "T12:00:00Z" if _as_of else _today_iso,
        "/glucose": _today_iso,
        "/nutrition": _nutrition_as_of + "T12:00:00Z" if _nutrition_as_of else _today_iso,
        "/training": _today_iso,
        "/physical": weight_as_of + "T12:00:00Z" if weight_as_of else _today_iso,
        "/habits": _today_iso,
        "/explorer": _today_iso,
    }

    return _ok(
        {
            "vitals": {
                "weight_lbs": round(current_weight) if current_weight is not None else None,
                "weight_as_of": weight_as_of,
                # #1917: the real number, under a name that does not claim a window.
                "weight_delta_lbs": weight_delta,
                "weight_delta_window_days": weight_delta_window_days,
                # Truthful-or-absent: None until the span really covers 30 days.
                "weight_delta_30d": weight_delta_30d,
                "hrv_ms": round(_vr["hrv_ms"], 1) if _vr["hrv_ms"] is not None else None,
                # #1084 / ADR-105: the claim carries its n — below _MIN_AVG_N the
                # avg is None (a 1-2 reading mean isn't an average), and the n
                # says how much data backs the number when it shows.
                # #1917: ...and the window says how many days those readings span,
                # because a genesis-clamped window makes "30d" a false name.
                "hrv_avg_ms": _hrv_avg,
                "hrv_avg_n": len(hrv_vals),
                "hrv_avg_window_days": _hrv_window["actual_days"],
                # Truthful-or-absent, same rule as weight_delta_30d.
                "hrv_30d_avg": _hrv_avg if _hrv_window["full"] else None,
                "hrv_30d_n": len(hrv_vals) if _hrv_window["full"] else None,
                "window_disclosure": _window_disclosure,
                "hrv_trend": trend(hrv_vals),
                "rhr_bpm": round(_vr["rhr_bpm"], 0) if _vr["rhr_bpm"] is not None else None,
                "rhr_trend": trend(list(reversed(rhr_vals))),  # lower is better
                # #1369 honest absence: no reading ⇒ null % AND null status —
                # never the old 0.0/"red" fabrication on an empty window.
                "recovery_pct": round(_vr["recovery_pct"], 0) if _vr["recovery_pct"] is not None else None,
                "recovery_status": _vr["recovery_status"],
                # #2344: recovery/hrv/rhr and sleep_hours can legitimately finalize
                # on different dates (see vitals_resolver's docstring) — as_of_date
                # below is only ONE of these two, so publish both explicitly rather
                # than making a reader infer which fields it actually covers.
                "recovery_as_of": _recovery_as_of,
                "sleep_hours": round(_vr["sleep_hours"], 1) if _vr["sleep_hours"] is not None else None,
                "sleep_as_of": _sleep_as_of,
                "as_of_date": _as_of,
                # Temporal frame (additive): recovery/sleep/hrv/rhr are about last
                # night and set up the as_of_date morning; weight (weight_as_of) is
                # same-day. night_of is the evening those readings came from.
                "frame": NIGHT_OF_FRAME,
                "night_of": _night_of,
                "time_travel": ip,
            },
            "page_freshness": page_freshness,
        },
        cache_seconds=86400 if ip else 300,  # the past is immutable
    )


def weight_progress(*, _g) -> dict:
    """
    GET /api/weight_progress
    Returns: daily weight readings for last 180 days.
    Cache: 3600s (1 hr).
    """
    EXPERIMENT_START = _g["EXPERIMENT_START"]
    _query_source = _g["_query_source"]
    datetime = _g["datetime"]

    today = datetime.now(PT).strftime("%Y-%m-%d")
    d180 = max((datetime.now(PT) - timedelta(days=180)).strftime("%Y-%m-%d"), EXPERIMENT_START)
    items = _query_source("withings", d180, today)

    readings = sorted(
        [
            {
                "date": item["sk"].replace("DATE#", ""),
                "weight_lbs": round(float(item["weight_lbs"]), 1),
            }
            for item in items
            if item.get("weight_lbs")
        ],
        key=lambda x: x["date"],
    )

    return _ok({"weight_progress": readings}, cache_seconds=3600)


def _latest_readiness(*, _g) -> dict | None:
    """RQA-04 — the pre-computed readiness score + component breakdown from computed_metrics
    (written by daily-metrics-compute). Surfaced read-only so the Cockpit shows the STORED
    score + its components, not just a band re-derived from raw vitals. None if not computed."""
    _latest_item = _g["_latest_item"]

    rec = _latest_item("computed_metrics")
    if not rec or rec.get("readiness_score") is None:
        return None
    # #492/M-4: serve the score's ACTUAL inputs (stored as readiness_components
    # by daily-metrics-compute). The old fallback borrowed the day-grade
    # component set — a different model — so when the breakdown is absent
    # (pre-#492 records) we serve none rather than the wrong ones.
    # #490/M-3: the TSB component names its provenance — the load behind it is a
    # duration proxy unless the basis says power-backed.
    _tsb_conf = str((rec.get("tsb_load_basis") or {}).get("confidence") or "")
    _tsb_label = "training balance" + (" (duration-proxy)" if _tsb_conf and _tsb_conf != "power" else "")
    label_map = {"recovery": "recovery", "sleep": "sleep", "hrv_trend": "HRV trend", "tsb": _tsb_label}
    components = [
        {"key": c.get("key"), "label": label_map.get(c.get("key"), c.get("key")), "score": round(float(c["score"]), 1)}
        for c in (rec.get("readiness_components") or [])
        if c.get("score") is not None
    ]
    return {
        "score": round(float(rec["readiness_score"]), 1),
        "band": rec.get("readiness_colour"),  # green / yellow / red
        "components": components,
        "tsb_basis": _tsb_conf or None,
        "as_of": (rec.get("sk", "") or "").replace("DATE#", "") or rec.get("date"),
    }


def snapshot(*, _g) -> dict:
    """
    GET /api/snapshot
    Combined response: vitals + journey + character (+ readiness) in one call.
    Reduces client-side roundtrips for pages that need all three (e.g. /live/, homepage).
    On partial failure any sub-object is null; callers must handle gracefully.
    """
    _latest_readiness = _g["_latest_readiness"]
    datetime = _g["datetime"]
    handle_character = _g["handle_character"]
    handle_journey = _g["handle_journey"]
    handle_vitals = _g["handle_vitals"]
    pre_start_meta = _g["pre_start_meta"]

    vitals_result = journey_result = character_result = None
    try:
        vitals_result = handle_vitals()
        vitals_body = json.loads(vitals_result.get("body", "{}"))
    except Exception as _e:
        logger.warning("[snapshot] vitals failed: %s", _e)
        vitals_body = None

    try:
        journey_result = handle_journey()
        journey_body = json.loads(journey_result.get("body", "{}"))
    except Exception as _e:
        logger.warning("[snapshot] journey failed: %s", _e)
        journey_body = None

    try:
        character_result = handle_character()
        character_body = json.loads(character_result.get("body", "{}"))
    except Exception as _e:
        logger.warning("[snapshot] character failed: %s", _e)
        character_body = None

    try:
        readiness_body = _latest_readiness(_g=_g)
    except Exception as _e:
        logger.warning("[snapshot] readiness failed: %s", _e)
        readiness_body = None

    payload = {
        "vitals": vitals_body,
        "journey": journey_body,
        "character": character_body,
        "readiness": readiness_body,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    # PRE-START (#931): the countdown contract at the snapshot's top level too, so
    # the cockpit doesn't have to dig through a possibly-failed journey sub-object.
    _pre = pre_start_meta()
    payload["pre_start"] = bool(_pre)
    if _pre:
        payload.update(_pre)
    return {
        "statusCode": 200,
        "headers": {**CORS_HEADERS, "Cache-Control": "public, max-age=60"},
        "body": json.dumps(payload, default=str),
    }
