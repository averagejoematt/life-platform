"""lambdas/web/site_api_sleep.py — sleep, its correlates, and circadian rhythm.

Split out of ``site_api_vitals.py`` (#1654 — god-module breakup). One seam: **the
night** — `/api/sleep_detail` (per-night architecture, gated through
``_sane_sleep_score`` so one glitched score can't make the page look broken),
`/api/sleep_correlations` (the self-policing cross-source correlation board: every
card carries n + overlap_weeks + a confidence tag, and the coefficient is withheld
below the overlap floor), and `/api/circadian`. The night-frame label comes from
the shared ``night_of_for`` helper (#1923) — never computed inline here.

The routed handler entrypoints stay in the ``site_api_vitals`` facade as thin
delegators; the logic lives here. Handlers receive the facade's ``globals()`` as
``_g`` and read the monkeypatched/injectable state (``_query_source``,
``_latest_item``, ``_experiment_date``, ``EXPERIMENT_START``, ``datetime``) via
``_g["<name>"]``.

This module does NOT import the facade; no import cycle. Every other shared helper
comes straight from ``site_api_common`` (identical binding semantics to the
pre-split module).
"""

from datetime import timedelta

from common.pacific_time import parse_iso_utc  # #1964: the ONE ISO-8601 parser

from web.site_api_common import (
    NIGHT_OF_FRAME,
    PT,
    _ok,
    _window_span,
    night_of_for,
)


def _sane_sleep_score(raw, hours, whoop_quality):
    """Gate an implausible nightly sleep score. A score <40 next to >=6h slept AND/OR a healthy
    Whoop quality (>=70) is a scoring/attribution glitch (the live '12' next to 8.2h + 84%
    quality), not a real terrible night — fall back to Whoop quality so one bad number doesn't
    make the whole sleep page look broken. Returns a rounded score or None."""
    if raw is None:
        return None
    try:
        raw = round(float(raw), 0)
    except (TypeError, ValueError):
        return None
    hrs = float(hours) if hours else 0
    wq = float(whoop_quality) if whoop_quality else 0
    if raw < 40 and (hrs >= 6 or wq >= 70):
        return round(wq, 0) if wq else None
    return raw


# ── Cross-source correlation board (sleep §8, Phase 2) ───────────────────────
# Self-policing: every card carries n + overlap_weeks + a confidence tag. The Pearson
# coefficient is computed ONLY at >=14 overlapping days (>=2 weeks); below that it's
# direction-only ("watching — too early"). Sleep-vs-weight (C1) is hard-WITHHELD through
# the water-weight phase. Powered by the same raw sources the platform tools read; the
# Pearson + day-lag logic is replicated compactly here (site-api can't import mcp/).
_CORR_MIN_COEF_DAYS = 14  # >=2 weeks of overlap before any coefficient

_CORR_MIN_DIR_DAYS = 4  # below this, not even a direction


def _shift_date(d, lag, *, _g):
    datetime = _g["datetime"]

    try:
        return (datetime.strptime(d, "%Y-%m-%d") + timedelta(days=lag)).strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return None


def _corr_card(cid, label, predictor, outcome, pred_series, outc_series, lag=0, withhold=False, note="", *, _g):
    """Build one self-policing correlation card from two {date: value} maps."""
    xs, ys = [], []
    for d, x in (pred_series or {}).items():
        d2 = _shift_date(d, lag, _g=_g)
        if d2 and d2 in (outc_series or {}) and x is not None and outc_series[d2] is not None:
            xs.append(float(x))
            ys.append(float(outc_series[d2]))
    n = len(xs)
    card = {
        "id": cid,
        "label": label,
        "predictor": predictor,
        "outcome": outcome,
        "n": n,
        "overlap_weeks": round(n / 7, 1),
        "lag_days": lag,
        "direction": "insufficient",
        "coefficient": None,
        "withheld": bool(withhold),
        "confidence": "watching — too early",
        "noise": False,
        "note": note,
    }
    if n >= _CORR_MIN_DIR_DAYS:
        mx, my = sum(xs) / n, sum(ys) / n
        cov = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
        card["direction"] = "moves together" if cov > 0 else ("moves opposite" if cov < 0 else "flat")
        card["noise"] = n < 7  # thin pairs are likely noise
    if withhold:
        card["confidence"] = "withheld — water-weight phase"
        card["coefficient"] = None
    elif n >= _CORR_MIN_COEF_DAYS:
        mx, my = sum(xs) / n, sum(ys) / n
        cov = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
        sx = sum((a - mx) ** 2 for a in xs) ** 0.5
        sy = sum((b - my) ** 2 for b in ys) ** 0.5
        card["coefficient"] = round(cov / (sx * sy), 2) if sx > 0 and sy > 0 else None
        card["confidence"] = "low confidence" if n < 30 else "moderate"
    return card


def _whoop_daily(d30, today, *, _g):
    """Whoop daily metrics keyed by date: recovery, strain, deep hours, sleep hours."""
    _query_source = _g["_query_source"]

    out = {}
    for w in _query_source("whoop", d30, today):
        if "#WORKOUT#" in w.get("sk", ""):
            continue
        dt = w.get("sk", "").replace("DATE#", "")[:10]
        if not dt:
            continue
        out[dt] = {
            "recovery": _f(w.get("recovery_score")),
            "strain": _f(w.get("strain")),
            "deep": _f(w.get("slow_wave_sleep_hours")),
            "hours": _f(w.get("sleep_duration_hours")),
            "hrv": _f(w.get("hrv")),
        }
    return out


def _f(v):
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def sleep_correlations(*, _g) -> dict:
    """
    GET /api/sleep_correlations
    The self-policing cross-source signal board. Each card: n + overlap-weeks + confidence;
    direction-only under 2 weeks (no coefficient); Pearson only at >=2 weeks. Sleep-vs-weight
    withheld through the water-weight phase. Cache: 3600s.
    """
    _experiment_date = _g["_experiment_date"]
    _query_source = _g["_query_source"]
    datetime = _g["datetime"]

    today = datetime.now(PT).strftime("%Y-%m-%d")
    d30 = _experiment_date(30)
    wd = _whoop_daily(d30, today, _g=_g)
    recovery = {d: v["recovery"] for d, v in wd.items() if v["recovery"] is not None}
    strain = {d: v["strain"] for d, v in wd.items() if v["strain"] is not None}

    cards = []
    # A1 (LEAD) — last night's recovery → today's training capacity (same-day; the only
    # arrow that changes tomorrow morning). Outcome proxy: the day's Whoop strain.
    cards.append(
        _corr_card(
            "A1",
            "Last night's recovery → today's training capacity",
            "sleep recovery",
            "day strain",
            recovery,
            strain,
            lag=0,
            note="The only arrow that changes tomorrow morning — high recovery should let the day carry more strain.",
            _g=_g,
        )
    )
    # A2 — day strain → next-night deep sleep (day-lagged: "did I earn it?").
    deep = {d: v["deep"] for d, v in wd.items() if v["deep"] is not None}
    cards.append(
        _corr_card(
            "A2",
            "Day strain → next-night deep sleep",
            "day strain",
            "deep sleep",
            strain,
            deep,
            lag=1,
            note="Did I earn it? — yesterday's training load against tonight's deep sleep.",
            _g=_g,
        )
    )
    # Eight Sleep nightly sleep-score series (feeds the A4 last-meal card).
    # NB: the former "A3 — bed temp → deep sleep" card was retired (ADR-118,
    # #489) — the Eight Sleep temperature pipeline is dead (dead /v2/intervals
    # endpoint, no bed_temp_f for 4+ months), so the card only ever rendered empty.
    eight = {}
    for e in _query_source("eightsleep", d30, today):
        dt = e.get("sk", "").replace("DATE#", "")[:10]
        if dt:
            eight[dt] = {"score": _f(e.get("sleep_score"))}
    sleep_score = {d: v["score"] for d, v in eight.items() if v["score"] is not None}
    # A4 — last meal time → sleep score. MacroFactor food_log latest time per day.
    last_meal = {}
    for m in _query_source("macrofactor", d30, today):
        dt = m.get("date") or m.get("sk", "").replace("DATE#", "")[:10]
        times = []
        for ent in m.get("food_log") or []:
            try:
                p = str(ent.get("time")).split(":")
                times.append(int(p[0]) * 60 + int(p[1]))
            except (ValueError, IndexError, AttributeError):
                pass
        if times and dt:
            last_meal[dt] = max(times)
    cards.append(
        _corr_card(
            "A4",
            "Last meal time → sleep score",
            "last meal",
            "sleep score",
            last_meal,
            sleep_score,
            lag=0,
            note="Eating late can blunt the night — last-meal minutes against how the night scored.",
            _g=_g,
        )
    )
    # B1 — decision fatigue (Todoist completed-task load) → sleep score. No app tracks this.
    todoist = {}
    for t in _query_source("todoist", d30, today):
        dt = t.get("date") or t.get("sk", "").replace("DATE#", "")[:10]
        # #2271: `completed_count` is the only completion field todoist_lambda
        # has ever written; the three former fallbacks (tasks_completed /
        # completed / completed_today) were dead names that could never match.
        v = _f(t.get("completed_count"))
        if v is not None and dt:
            todoist[dt] = v
    cards.append(
        _corr_card(
            "B1",
            "Decision load (Todoist) → sleep score",
            "Todoist load",
            "sleep score",
            todoist,
            sleep_score,
            lag=0,
            note="A heavy decision day against how the night scored — the cross-source signal no sleep app has.",
            _g=_g,
        )
    )
    # B2 — mood/journal → sleep (bidirectional). State-of-Mind valence as the mood proxy;
    # empty (n=0 → watching) when mood/journal logging is stale.
    mood = {}
    # SoM daily valence lands on the apple_health partition as som_avg_valence
    # (there is no separate state_of_mind partition).
    for sm in _query_source("apple_health", d30, today):
        dt = sm.get("date") or sm.get("sk", "").replace("DATE#", "")[:10]
        v = _f(sm.get("som_avg_valence"))
        if v is not None and dt:
            mood[dt] = v
    cards.append(
        _corr_card(
            "B2",
            "Mood → sleep score",
            "mood / valence",
            "sleep score",
            mood,
            sleep_score,
            lag=0,
            note="Mood and sleep move together both ways — gated on active mood/journal logging; empty until entries accrue.",
            _g=_g,
        )
    )
    # B3 — day-of-week best duration. Not a Pearson pair; n=1/day at week one = noise.
    durations = {d: v["hours"] for d, v in wd.items() if v["hours"] is not None}
    dow: dict[int, list[float]] = {}
    for d, h in durations.items():
        try:
            dow.setdefault(datetime.strptime(d, "%Y-%m-%d").weekday(), []).append(h)
        except ValueError:
            pass
    _wk = round(len(durations) / 7, 1)
    b3 = {
        "id": "B3",
        "label": "Day-of-week → best sleep duration",
        "predictor": "day of week",
        "outcome": "sleep duration",
        "n": len(durations),
        "overlap_weeks": _wk,
        "lag_days": 0,
        "coefficient": None,
        "withheld": False,
        "direction": "fills in ~4 weeks",
        "confidence": "watching — needs ~4 weeks",
        "noise": True,
        "note": "Which weekday sleeps best needs ~4 weeks — one Tuesday is not a pattern.",
    }
    if _wk >= 4 and dow:
        _best = max(dow, key=lambda k: sum(dow[k]) / len(dow[k]))
        _names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        b3.update(
            {
                "direction": f"best on {_names[_best]} ({round(sum(dow[_best]) / len(dow[_best]), 1)}h avg)",
                "confidence": "low confidence",
                "noise": False,
            }
        )
    cards.append(b3)
    # C1 (shown LAST, labelled loudest) — sleep vs weight. HIGHEST false-positive risk in a
    # water-weight cut; the coefficient is HARD-WITHHELD until well past the early water phase
    # AND explicit sign-off (the STOP-AND-ASK gate). Direction is still shown honestly.
    weight = {}
    for w in _query_source("withings", d30, today):
        dt = w.get("date") or w.get("sk", "").replace("DATE#", "")[:10]
        v = _f(w.get("weight_lbs"))
        if v is not None and dt:
            weight[dt] = v
    cards.append(
        _corr_card(
            "C1",
            "Sleep → weight",
            "sleep score",
            "weight",
            sleep_score,
            weight,
            lag=0,
            withhold=True,
            note="Highest false-positive risk in a water-weight cut — the coefficient stays withheld until well past the early water phase.",
            _g=_g,
        )
    )

    return _ok({"cards": cards, "min_coef_days": _CORR_MIN_COEF_DAYS, "as_of": today}, cache_seconds=3600)


def sleep_detail(*, _g) -> dict:
    """
    GET /api/sleep_detail
    Returns: 30-day sleep stats from Eight Sleep + Whoop cross-referenced.
    Shows sleep score, efficiency, quality, and daily trend.
    Cache: 3600s (1h).
    """
    EXPERIMENT_START = _g["EXPERIMENT_START"]
    _experiment_date = _g["_experiment_date"]
    _query_source = _g["_query_source"]
    datetime = _g["datetime"]

    today = datetime.now(PT).strftime("%Y-%m-%d")
    d30 = _experiment_date(30)
    _w30 = _window_span(d30, today, 30)  # #1917: is "30d" a true name today?

    eight_days = _query_source("eightsleep", d30, today)
    whoop_days = _query_source("whoop", d30, today)

    # Index whoop by date for cross-referencing
    whoop_by_date = {r.get("sk", "").replace("DATE#", ""): r for r in whoop_days if r.get("sk")}

    eight_days.sort(key=lambda x: x.get("sk", ""))
    # Filter to experiment window — EXPERIMENT_QUERY_START fetches 1 day early for sleep lookback,
    # but we only display data from EXPERIMENT_START onwards
    eight_with_data = [
        r for r in eight_days if r.get("sleep_score") is not None and r.get("sk", "").replace("DATE#", "") >= EXPERIMENT_START
    ]

    if not eight_with_data:
        return _ok({"sleep_detail": None, "sleep_trend": []}, cache_seconds=3600)

    latest = eight_with_data[-1]
    latest_date = latest.get("sk", "").replace("DATE#", "")
    whoop_latest = whoop_by_date.get(latest_date, {})
    # #495/M-9: if the latest Eight Sleep night has no matching Whoop recovery,
    # borrow the most recent night that has one — but ONLY the recovery block
    # (recovery/HRV/RHR), and SAY SO via recovery_night_of. The old code swapped
    # the whole Whoop record, so night-A hours/stages + night-B recovery rendered
    # under one dated header with no per-field date.
    whoop_recovery_rec = whoop_latest
    recovery_night_of = None
    if not whoop_latest.get("recovery_score"):
        for r in reversed(eight_with_data):
            _rd = r.get("sk", "").replace("DATE#", "")
            _wm = whoop_by_date.get(_rd, {})
            if _wm.get("recovery_score"):
                whoop_recovery_rec = _wm
                if _rd != latest_date:
                    recovery_night_of = _rd
                break

    # 30-day averages (actual field names: sleep_efficiency_pct, sleep_duration_hours)
    score_vals = [float(r["sleep_score"]) for r in eight_with_data if r.get("sleep_score")]
    eff_vals = [float(r["sleep_efficiency_pct"]) for r in eight_with_data if r.get("sleep_efficiency_pct")]
    # Bed-temperature surfaces retired (ADR-118, #489) — the Eight Sleep temp
    # pipeline is dead (dead /v2/intervals endpoint, no bed_temp_f for 4+ months).

    def avg(lst):
        return round(sum(lst) / len(lst), 1) if lst else None

    # #1917: hoisted out of the response literal so the honest key and the gated
    # `30d_`-named key are the SAME number by construction, never two expressions
    # that could drift apart. Must sit AFTER `def avg` — the response literal it
    # came from is only evaluated at return time, so the original position was
    # fine there and is not here (flake8 F821 caught the move).
    _avg_recovery_window = (
        avg(
            [
                float(whoop_by_date.get(r.get("sk", "").replace("DATE#", ""), {}).get("recovery_score", 0))
                for r in eight_with_data
                if whoop_by_date.get(r.get("sk", "").replace("DATE#", ""), {}).get("recovery_score")
            ]
        )
        if whoop_by_date
        else None
    )

    # Daily trend — filter to experiment start (EXPERIMENT_QUERY_START is 1 day early for sleep lookback)
    trend = []
    for r in eight_with_data:
        date = r.get("sk", "").replace("DATE#", "")
        if date < EXPERIMENT_START:
            continue  # Don't include pre-experiment days in trend output
        w = whoop_by_date.get(date, {})
        trend.append(
            {
                "date": date,
                "sleep_score": _sane_sleep_score(r.get("sleep_score"), w.get("sleep_duration_hours"), w.get("sleep_quality_score")),
                "efficiency": round(float(r["sleep_efficiency_pct"]), 1) if r.get("sleep_efficiency_pct") else None,
                "hours": round(float(w["sleep_duration_hours"]), 1) if w.get("sleep_duration_hours") else None,
                "whoop_quality": round(float(w["sleep_quality_score"]), 0) if w.get("sleep_quality_score") else None,
                "deep_sleep_hours": round(float(w["slow_wave_sleep_hours"]), 2) if w.get("slow_wave_sleep_hours") else None,
                "rem_sleep_hours": round(float(w["rem_sleep_hours"]), 2) if w.get("rem_sleep_hours") else None,
                "deep_pct": round(float(r["deep_pct"]), 1) if r.get("deep_pct") else None,
                "rem_pct": round(float(r["rem_pct"]), 1) if r.get("rem_pct") else None,
                "light_pct": round(float(r["light_pct"]), 1) if r.get("light_pct") else None,
                "recovery_score": round(float(w["recovery_score"]), 0) if w.get("recovery_score") else None,
                "hrv": round(float(w["hrv"]), 1) if w.get("hrv") else None,
                "rhr": round(float(w["resting_heart_rate"]), 0) if w.get("resting_heart_rate") else None,
                "sleep_start": w.get("sleep_start"),
            }
        )

    # Use the gated latest trend score so a glitch score (the '12') doesn't drive the headline.
    score_today = float(trend[-1]["sleep_score"]) if trend and trend[-1].get("sleep_score") else float(latest.get("sleep_score", 0) or 0)
    score_status = "excellent" if score_today >= 85 else ("good" if score_today >= 70 else "needs_attention")

    # Compute bed time / wake time averages and social jet lag from Whoop sleep_start/end
    bed_times_weekday = []
    bed_times_weekend = []
    wake_times = []
    for w in whoop_days:
        ss = w.get("sleep_start")
        se = w.get("sleep_end")
        if not ss or "#WORKOUT#" in w.get("sk", ""):
            continue
        try:
            # #1964: the ONE ISO-8601 parser. These are stored instants, not the
            # clock, so they read the real parser rather than `_g`'s datetime.
            start_dt = parse_iso_utc(ss)
            end_dt = parse_iso_utc(se)
            if start_dt is None or end_dt is None:
                continue
            start_pt = start_dt.astimezone(PT)
            end_pt = end_dt.astimezone(PT)
            # Normalize bed hour: treat times after 6 PM as evening (18-30), before 6 AM as late night (24-30)
            bed_hour = start_pt.hour + start_pt.minute / 60
            if bed_hour < 6:
                bed_hour += 24  # 1 AM → 25, so avg with 11 PM (23) works correctly
            wake_hour = end_pt.hour + end_pt.minute / 60
            wake_times.append(wake_hour)
            if start_pt.weekday() in (4, 5):  # Fri/Sat night = weekend sleep
                bed_times_weekend.append(bed_hour)
            else:
                bed_times_weekday.append(bed_hour)
        except Exception:
            continue

    def _fmt_hour(h):
        """Convert decimal hour to HH:MM AM/PM."""
        h = h % 24
        hr = int(h)
        mn = int((h - hr) * 60)
        ampm = "AM" if hr < 12 else "PM"
        hr12 = hr % 12 or 12
        return f"{hr12}:{mn:02d} {ampm}"

    # ── #1968: name the night, and name the device ───────────────────────────
    # Measured 2026-08-06: the summary published `total_sleep_hours: 8.4` for a night
    # whose `sleep_trend` row read `hours: null`. Both were true. `total_sleep_hours`
    # is EIGHT SLEEP's duration for `latest_date`; the trend's `hours` is WHOOP's for
    # the same date, and whoop was in an auth outage. Nothing in the payload said
    # either thing, so a reader (and the reader_truth judge, which raised it HIGH) saw
    # one surface assert a duration its sibling reported as unknown.
    #
    # The fix is labels, not arithmetic: the night these figures describe (via the ONE
    # #1923 helper — never an inline offset), and the device each duration came from.
    # `recovery_night_of` stays exactly as it is — a DIFFERENT quantity (#495/M-9, the
    # borrowed block's stored wake date), deliberately out of the frame rule's scope.
    _night_of = night_of_for(latest_date)
    _whoop_hours_present = whoop_latest.get("sleep_duration_hours") is not None
    _eight_hours_present = latest.get("sleep_duration_hours") is not None
    # #2344: `sleep_trend` (a sibling array, not nested under `sleep_detail`) is
    # keyed by a bare `date` field with no stated convention of its own. Measured
    # live: the array's date IS the wake date — the same convention as as_of_date,
    # NOT night_of — proven by value identity (the row dated `latest_date` is the
    # same record as the `sleep_detail` block above, whose night_of is one day
    # earlier). Without a stated convention a reader has no way to tell that
    # `2026-08-08` in the array and `night_of 2026-08-07` one level up name the
    # SAME night. Extending the existing figure_scope seam (not a second
    # provenance mechanism) rather than adding a per-row field to every trend entry.
    _figure_scope = {
        "frame": NIGHT_OF_FRAME,
        "night_of": _night_of,
        "total_sleep_hours_source": "eightsleep" if _eight_hours_present else None,
        "whoop_hours_source": "whoop" if _whoop_hours_present else None,
        # The disclosure the payload owed a reader: this summary carries a duration
        # from one device while the trend row for the same night carries none.
        "divergence": (
            (
                f"total_sleep_hours is Eight Sleep's duration for the night of {_night_of}; "
                f"Whoop has no sleep record for that night, so whoop_hours and the trend "
                f"row's hours are null. The two are different devices, not a correction."
            )
            if (_eight_hours_present and not _whoop_hours_present)
            else None
        ),
        # #2344: the sibling `sleep_trend` array's date convention, named once here
        # rather than per-row.
        "trend_date_field": "date",
        "trend_date_convention": "wake_date",
        "trend_note": (
            f"sleep_trend rows are keyed by WAKE date (the same convention as as_of_date), not night_of — "
            f"the row dated {latest_date} is the night of {_night_of}, the same night described above."
        ),
        # #2613: the OTHER half of the trend's frame, and the one that was missing.
        # #2344 named the row DATE's convention; `sleep_start` is a raw UTC instant
        # from Whoop, sitting in a payload whose every other date is a Pacific
        # calendar date. Nothing said so. Measured: the genesis-dated row published
        # `sleep_start: <date>T05:05:46Z` — 22:05 the PREVIOUS Pacific evening — and
        # three consecutive nightly reader-truth runs read that Z-timestamp as a
        # local date, could not reconcile it with the wake-date rule trend_note had
        # just taught them, and raised a high "pre-genesis row" contradiction (#2613).
        # The data was right every time; the payload simply never named the frame.
        # Same #1968 principle as `divergence` above: a figure that does not name its
        # frame is unreconcilable, and an unreconcilable figure reads as a lie.
        "trend_sleep_start_tz": "UTC",
        "trend_sleep_start_note": (
            "sleep_trend[].sleep_start is a UTC instant (trailing Z); every DATE in this payload "
            "(date, as_of_date, night_of) is a Pacific calendar date. A bedtime of 05:05Z is 22:05 the "
            "previous Pacific evening, so a row's sleep_start normally reads one calendar day earlier than "
            "its wake date. The earliest row is dated at the cycle start because trailing windows clamp to "
            "genesis (ADR-077), and its bedtime therefore falls the evening before Day 1 — the wake-date "
            "frame being correct, not a pre-cycle reading."
        ),
    }

    all_bed = bed_times_weekday + bed_times_weekend
    avg_bed = round(sum(all_bed) / len(all_bed), 2) if all_bed else None
    avg_bed_wd = round(sum(bed_times_weekday) / len(bed_times_weekday), 2) if bed_times_weekday else None
    avg_bed_we = round(sum(bed_times_weekend) / len(bed_times_weekend), 2) if bed_times_weekend else None
    avg_wake = round(sum(wake_times) / len(wake_times), 2) if wake_times else None
    social_jet_lag_hrs = round(abs((avg_bed_wd or 0) - (avg_bed_we or 0)), 1) if avg_bed_wd is not None and avg_bed_we is not None else None

    return _ok(
        {
            "sleep_detail": {
                "sleep_score": round(score_today, 0),
                "sleep_efficiency": round(float(latest.get("sleep_efficiency_pct", 0)), 1) if latest.get("sleep_efficiency_pct") else None,
                "total_sleep_hours": round(float(latest.get("sleep_duration_hours", 0)), 1) if latest.get("sleep_duration_hours") else None,
                "whoop_quality": (
                    round(float(whoop_latest.get("sleep_quality_score", 0)), 0) if whoop_latest.get("sleep_quality_score") else None
                ),
                "whoop_hours": (
                    round(float(whoop_latest.get("sleep_duration_hours", 0)), 1) if whoop_latest.get("sleep_duration_hours") else None
                ),
                "deep_sleep_hours": (
                    round(float(whoop_latest.get("slow_wave_sleep_hours", 0)), 2) if whoop_latest.get("slow_wave_sleep_hours") else None
                ),
                "rem_sleep_hours": round(float(whoop_latest.get("rem_sleep_hours", 0)), 2) if whoop_latest.get("rem_sleep_hours") else None,
                "recovery_score": (
                    round(float(whoop_recovery_rec.get("recovery_score", 0)), 0) if whoop_recovery_rec.get("recovery_score") else None
                ),
                # #495/M-9: when the recovery/HRV/RHR trio above comes from a different
                # night than the Eight Sleep record, this carries that night's date (else null).
                "recovery_night_of": recovery_night_of,
                "hrv": round(float(whoop_recovery_rec.get("hrv", 0)), 1) if whoop_recovery_rec.get("hrv") else None,
                "rhr": (
                    round(float(whoop_recovery_rec.get("resting_heart_rate", 0)), 0)
                    if whoop_recovery_rec.get("resting_heart_rate")
                    else None
                ),
                "score_status": score_status,
                "deep_pct": round(float(latest.get("deep_pct", 0)), 1) if latest.get("deep_pct") else None,
                "rem_pct": round(float(latest.get("rem_pct", 0)), 1) if latest.get("rem_pct") else None,
                "light_pct": round(float(latest.get("light_pct", 0)), 1) if latest.get("light_pct") else None,
                # #1917: truthful-or-absent, same rule as the CGM block above.
                "avg_recovery_window": _avg_recovery_window,
                "avg_score_window": avg(score_vals),
                "avg_efficiency_window": avg(eff_vals),
                "avg_window_days": _w30["actual_days"],
                "30d_avg_recovery": _avg_recovery_window if _w30["full"] else None,
                "30d_avg_score": avg(score_vals) if _w30["full"] else None,
                "30d_avg_efficiency": avg(eff_vals) if _w30["full"] else None,
                "days_tracked": len(eight_with_data),
                "as_of_date": latest_date,
                # #1968: the night every sleep figure above describes, plus which device
                # each duration came from. Flat keys (front-ends read them directly) and
                # the nested scope object (the qa/reader_truth pass reads that).
                "frame": NIGHT_OF_FRAME,
                "night_of": _night_of,
                "figure_scope": _figure_scope,
                "avg_bedtime": _fmt_hour(avg_bed) if avg_bed is not None else None,
                "avg_bedtime_weekday": _fmt_hour(avg_bed_wd) if avg_bed_wd is not None else None,
                "avg_bedtime_weekend": _fmt_hour(avg_bed_we) if avg_bed_we is not None else None,
                "avg_waketime": _fmt_hour(avg_wake) if avg_wake is not None else None,
                "social_jet_lag_hrs": social_jet_lag_hrs,
            },
            "sleep_trend": trend,
        },
        cache_seconds=3600,
    )


def circadian(*, _g) -> dict:
    """
    GET /api/circadian
    Today's circadian-compliance score — computed daily by
    circadian_compliance_lambda and stored at SOURCE#circadian | DATE#<today>,
    but (until now) never surfaced. A *predictive* 0–100 behavioral score across
    four anchors (wake light, meal timing, screen wind-down, sleep consistency):
    it estimates what tonight's sleep will look like based on today's behaviors.
    Cache: 900s — recomputed once daily; refreshing faster gains nothing.
    """
    _latest_item = _g["_latest_item"]

    item = _latest_item("circadian")
    if not item:
        return _ok({"available": False}, cache_seconds=900)

    comps = item.get("components", {}) or {}
    components = {
        name: {
            "score": c.get("score"),
            "max": c.get("max"),
            "note": c.get("note"),
            # Staleness honesty (truth audit 2026-07-10): False = the lambda had no
            # real signal for this anchor — render "unknown", never a scored default.
            # Legacy records predate the flag; absent means measured (old behavior).
            "measured": c.get("measured", True),
        }
        for name, c in comps.items()
    }
    return _ok(
        {
            "available": True,
            "date": item.get("date"),
            # Temporal frame (additive): this is a forward-looking forecast of how
            # tonight's sleep will turn out given today's behaviours — not a measurement.
            "frame": "tonight",
            "score": item.get("score"),
            "category": item.get("category"),
            "prescription": item.get("prescription"),
            "weakest_component": item.get("weakest_component"),
            "measured_count": item.get("measured_count"),
            "components": components,
        },
        cache_seconds=900,
    )


# ── PhenoAge (Levine et al. 2018) — transparent biological age (P1.5) ──────────────
# Replaces the DEXA black-box "biological age" with a published formula over 9 standard blood
# markers + chronological age. PRIVACY (owner decision, Option A): chronological age is used
# ONLY to compute — it is NEVER returned, and neither is the chrono−pheno gap, so the page
# can't be used to back out the owner's real age. (Residual: the 9 markers are public on the
