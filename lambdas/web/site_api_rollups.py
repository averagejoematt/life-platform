"""lambdas/web/site_api_rollups.py — windowed rollup + comparison surface split out of
site_api_data.py (#1654): tools_baseline / platform_stats / changes_since /
observatory_week / cycle_compare / survival. Reads facade state via `_g`."""

from datetime import datetime, timedelta, timezone

from web.site_api_common import (
    EXPERIMENT_BASELINE_WEIGHT_LBS,
    PLATFORM_STATS,
    PT,
    _error,
    _get_profile,
    _latest_item,
    _ok,
    logger,
)

_ENGAGEMENT_SOURCES = ("withings", "macrofactor", "notion")


_COLLAPSE_GAP = 4


_SURVIVAL_HORIZON = 30


def tools_baseline(*, _g) -> dict:
    """
    GET /api/tools_baseline
    Returns baseline (first week of experiment) and current values for the
    Tools page comparison badges: RHR, HRV, sleep quality, weight.
    Cache: 3600s — baseline is fixed, current shifts slowly.
    """
    # Facade state injected via `_g` (the delegator's globals()) — same module the test patched.
    EXPERIMENT_START = _g["EXPERIMENT_START"]
    _query_source = _g["_query_source"]
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Baseline: first 7 days of the experiment
    baseline_end = (datetime.strptime(EXPERIMENT_START, "%Y-%m-%d") + timedelta(days=7)).strftime("%Y-%m-%d")

    # Current: last 7 days
    d7 = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")

    baseline_whoop = _query_source("whoop", EXPERIMENT_START, baseline_end)
    current_whoop = _query_source("whoop", d7, today)

    def first_val(records, field):
        """First non-null value from sorted records."""
        for r in sorted(records, key=lambda x: x.get("sk", "")):
            if r.get(field) is not None:
                return round(float(r[field]), 1)
        return None

    def avg_val(records, field):
        """Average of non-null values."""
        vals = [float(r[field]) for r in records if r.get(field) is not None]
        return round(sum(vals) / len(vals), 1) if vals else None

    baseline = {
        "rhr_bpm": first_val(baseline_whoop, "resting_heart_rate"),
        "hrv_ms": first_val(baseline_whoop, "hrv"),
        "sleep_score": first_val(baseline_whoop, "sleep_quality_score"),
        "sleep_hours": first_val(baseline_whoop, "sleep_duration_hours"),
    }
    current = {
        "rhr_bpm": avg_val(current_whoop, "resting_heart_rate"),
        "hrv_ms": avg_val(current_whoop, "hrv"),
        "sleep_score": avg_val(current_whoop, "sleep_quality_score"),
        "sleep_hours": avg_val(current_whoop, "sleep_duration_hours"),
    }

    # Weight — baseline uses EXPERIMENT_BASELINE_WEIGHT_LBS (ADR-058: May 18 Withings reading)
    _p = _get_profile()
    baseline["weight_lbs"] = float(_p.get("journey_start_weight_lbs", EXPERIMENT_BASELINE_WEIGHT_LBS))

    latest_withings = _latest_item("withings")
    current["weight_lbs"] = round(float(latest_withings["weight_lbs"])) if latest_withings and latest_withings.get("weight_lbs") else None

    return _ok(
        {
            "baseline": baseline,
            "baseline_date": EXPERIMENT_START,
            "current": current,
            "current_date": today,
        },
        cache_seconds=3600,
    )


def platform_stats() -> dict:
    """GET /api/platform_stats — authoritative platform counts for all site pages."""
    return _ok(PLATFORM_STATS, cache_seconds=3600)


def changes_since(qs: dict = None, *, _g) -> dict:
    """GET /api/changes-since?ts=EPOCH — Returns notable changes since timestamp."""
    # Facade state injected via `_g` (the delegator's globals()) — same module the test patched.
    _query_source = _g["_query_source"]
    qs = qs or {}
    ts_str = qs.get("ts", "")
    if not ts_str:
        return _error(400, "Missing ts parameter")

    try:
        since_ts = int(ts_str)
    except (ValueError, TypeError):
        return _error(400, "Invalid ts parameter")

    from datetime import datetime, timedelta, timezone

    since_dt = datetime.fromtimestamp(since_ts, tz=timezone.utc)
    now = datetime.now(timezone.utc)
    days_ago = max(1, (now - since_dt).days)
    # Cap lookback to 30 days
    if days_ago > 30:
        since_dt = now - timedelta(days=30)
        days_ago = 30

    start_date = since_dt.strftime("%Y-%m-%d")
    end_date = now.strftime("%Y-%m-%d")

    # Fetch weight, HRV, sleep, character data
    deltas = {}
    try:
        whoop_items = _query_source("whoop", start_date, end_date)
        withings_items = _query_source("withings", start_date, end_date)

        # Weight delta
        weights = [
            float(i.get("weight_kg", 0)) * 2.20462 for i in withings_items if i.get("weight_kg") and float(i.get("weight_kg", 0)) > 0
        ]
        if len(weights) >= 2:
            spark = weights[-7:] if len(weights) > 7 else weights
            deltas["weight"] = {
                "from": round(weights[0], 1),
                "to": round(weights[-1], 1),
                "change": round(weights[-1] - weights[0], 1),
                "unit": "lbs",
                "sparkline": [round(w, 1) for w in spark],
            }

        # HRV delta
        hrvs = [float(i.get("hrv", 0)) for i in whoop_items if i.get("hrv") and float(i.get("hrv", 0)) > 0]
        if len(hrvs) >= 2:
            spark = hrvs[-7:] if len(hrvs) > 7 else hrvs
            trend = "climbing" if hrvs[-1] > hrvs[0] else "declining" if hrvs[-1] < hrvs[0] else "stable"
            deltas["hrv"] = {
                "from": round(hrvs[0]),
                "to": round(hrvs[-1]),
                "change": round(hrvs[-1] - hrvs[0]),
                "unit": "ms",
                "trend": trend,
                "sparkline": [round(h) for h in spark],
            }

        # Sleep delta
        sleeps = [
            float(i.get("sleep_duration_hours", 0))
            for i in whoop_items
            if i.get("sleep_duration_hours") and float(i.get("sleep_duration_hours", 0)) > 0
        ]
        if len(sleeps) >= 2:
            spark = sleeps[-7:] if len(sleeps) > 7 else sleeps
            trend = "improving" if sleeps[-1] > sleeps[0] else "declining"
            deltas["sleep"] = {
                "from": round(sleeps[0], 1),
                "to": round(sleeps[-1], 1),
                "change": round(sleeps[-1] - sleeps[0], 1),
                "unit": "hrs",
                "trend": trend,
                "sparkline": [round(s, 1) for s in spark],
            }
    except Exception as e:
        logger.warning(f"[changes-since] DynamoDB query failed: {e}")

    # Character delta
    try:
        char_items = _query_source("character_sheet", start_date, end_date)
        scores = [float(i.get("overall_score", 0)) for i in char_items if i.get("overall_score")]
        if len(scores) >= 2:
            deltas["character"] = {
                "from": round(scores[0]),
                "to": round(scores[-1]),
                "change": round(scores[-1] - scores[0]),
                "unit": "pts",
                "sparkline": [round(s) for s in (scores[-7:] if len(scores) > 7 else scores)],
            }
    except Exception:
        pass

    # Events (experiments completed, chronicles published)
    events_list = []
    try:
        exp_items = _query_source("experiments", start_date, end_date)
        for ev in exp_items:
            if ev.get("status") == "completed":
                events_list.append(
                    {
                        "type": "experiment_complete",
                        "title": ev.get("name", "Experiment"),
                        "link": "/experiments/",
                        "date": ev.get("sk", "").replace("DATE#", ""),
                    }
                )
    except Exception:
        pass

    return _ok(
        {
            "since": since_dt.isoformat(),
            "days_ago": days_ago,
            "deltas": deltas,
            "events": events_list[:5],
        },
        cache_seconds=300,
    )


def observatory_week(qs: dict = None, *, _g) -> dict:
    """GET /api/observatory_week?domain=sleep[&date=YYYY-MM-DD] — 7-day domain summary.

    With ?date= (Phase 4 historical window): the 7-day window AS OF that date — records
    served verbatim (gaps stay gaps, never interpolated), pilot/prior-cycle records
    included (history is explicitly cross-cycle, mirroring handle_character), a future
    date clamps to today, and the response caches a full day (the past is immutable).
    """
    # Facade state injected via `_g` (the delegator's globals()) — same module the test patched.
    EXPERIMENT_START = _g["EXPERIMENT_START"]
    _query_source = _g["_query_source"]
    pre_start_meta = _g["pre_start_meta"]
    qs = qs or {}
    domain = (qs.get("domain") or "sleep").lower().strip()
    valid_domains = {"sleep", "glucose", "nutrition", "training", "mind", "physical"}
    if domain not in valid_domains:
        return _error(400, f"Invalid domain. Use: {', '.join(sorted(valid_domains))}")

    import re as _re
    from datetime import datetime, timedelta, timezone

    date = (qs.get("date") or "").strip()
    if date and not _re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        return _error(400, "date must be YYYY-MM-DD")
    ip = bool(date)  # ADR-058: include pilot/prior-cycle records only when time-travelling

    now = datetime.now(timezone.utc)

    # PRE-START (#948, the #939 contract): with genesis staged in the FUTURE the 7-day
    # window inverts (start 2026-07-12 > end 2026-07-11) and every branch below emits
    # invented zero-comparisons against a week that doesn't exist (ADR-104). Honest
    # empty shape instead — null summary + the countdown fields — so the front-end's
    # existing "numbers aren't in yet" branches engage. Time-travel (?date=) still
    # serves real prior-cycle history. Inert (nothing changes) once genesis <= today.
    if not date:
        _pre = pre_start_meta()
        if _pre:
            return _ok(
                {
                    "domain": domain,
                    "period": None,
                    "summary": None,
                    "notable": None,
                    "last_updated": now.isoformat(),
                    "as_of_date": None,
                    "time_travel": False,
                    **_pre,
                },
                cache_seconds=900,
            )

    # Anchor the window to `date` (clamped to today so a future scrub shows the live week),
    # else to now. start/prev_* derive off the anchor — every domain branch below is unchanged.
    anchor = min(date, now.strftime("%Y-%m-%d")) if date else now.strftime("%Y-%m-%d")
    _anchor = datetime.strptime(anchor, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    end_date = anchor
    start_date = max((_anchor - timedelta(days=7)).strftime("%Y-%m-%d"), EXPERIMENT_START)
    prev_start = max((_anchor - timedelta(days=14)).strftime("%Y-%m-%d"), EXPERIMENT_START)
    prev_end = max((_anchor - timedelta(days=8)).strftime("%Y-%m-%d"), EXPERIMENT_START)

    try:
        if domain == "sleep":
            items = _query_source("whoop", start_date, end_date, include_pilot=ip)
            prev_items = _query_source("whoop", prev_start, prev_end, include_pilot=ip)

            durations = [float(i.get("sleep_duration_hours", 0)) for i in items if i.get("sleep_duration_hours")]
            prev_durations = [float(i.get("sleep_duration_hours", 0)) for i in prev_items if i.get("sleep_duration_hours")]
            avg_dur = sum(durations) / len(durations) if durations else 0
            prev_avg = sum(prev_durations) / len(prev_durations) if prev_durations else 0

            best: dict = max(items, key=lambda i: float(i.get("sleep_duration_hours", 0)), default={})
            worst: dict = min(items, key=lambda i: float(i.get("sleep_duration_hours", 99)), default={})

            eff_vals = [
                float(i.get("sleep_quality_score") or i.get("sleep_efficiency_pct") or 0)
                for i in items
                if i.get("sleep_quality_score") or i.get("sleep_efficiency_pct")
            ]
            best_eff = max(eff_vals) if eff_vals else None

            # ADR-104 (#948): a week-over-week claim needs BOTH weeks. In week 1 of a
            # cycle the prior window clamps to genesis and stays empty — "vs 0 last
            # week" would be a fabricated comparison, so the delta goes null instead.
            _has_wow = bool(durations and prev_durations)
            summary = {
                "primary": {
                    "label": "Average Duration",
                    "value": round(avg_dur, 1) if durations else None,
                    "unit": "hrs",
                    "delta": round(avg_dur - prev_avg, 1) if _has_wow else None,
                    "delta_label": f"vs {round(prev_avg, 1)} last week" if _has_wow else "",
                    "trend": ("up" if avg_dur > prev_avg else "down") if _has_wow else "flat",
                    "sparkline": [round(d, 1) for d in durations],
                },
                "highlight": {
                    "label": "Best Night",
                    "value": (
                        f"{best.get('sk', '').replace('DATE#', '')[5:]} · {round(float(best.get('sleep_duration_hours', 0)), 1)}h"
                        if best
                        else None
                    ),
                    "detail": f"Recovery {round(float(best.get('recovery_score', 0)))}%" if best else "",
                },
                "lowlight": {
                    "label": "Worst Night",
                    "value": (
                        f"{worst.get('sk', '').replace('DATE#', '')[5:]} · {round(float(worst.get('sleep_duration_hours', 0)), 1)}h"
                        if worst
                        else None
                    ),
                    "detail": "",
                },
                "best_efficiency": round(best_eff) if best_eff else None,
            }
            if _has_wow:
                notable = f"Avg sleep {'improved' if avg_dur > prev_avg else 'declined'} {abs(round(avg_dur - prev_avg, 1))}h vs last week"
            elif durations:
                notable = f"Avg sleep {round(avg_dur, 1)}h this week (no completed prior week in this cycle to compare)"
            else:
                notable = "No sleep data in the window yet"

        elif domain == "nutrition":
            items = _query_source("macrofactor", start_date, end_date, include_pilot=ip)
            prev_items = _query_source("macrofactor", prev_start, prev_end, include_pilot=ip)

            cals = [
                float(i.get("total_calories_kcal") or i.get("calories") or 0)
                for i in items
                if i.get("total_calories_kcal") or i.get("calories")
            ]
            prev_cals = [
                float(i.get("total_calories_kcal") or i.get("calories") or 0)
                for i in prev_items
                if i.get("total_calories_kcal") or i.get("calories")
            ]
            avg_cal = sum(cals) / len(cals) if cals else 0
            prev_avg_cal = sum(prev_cals) / len(prev_cals) if prev_cals else 0
            proteins = [
                float(i.get("total_protein_g") or i.get("protein_g") or 0) for i in items if i.get("total_protein_g") or i.get("protein_g")
            ]
            avg_protein = sum(proteins) / len(proteins) if proteins else 0

            # Nutrition uploads at end of day, so today is structurally never logged yet.
            # Counting it in the denominator (the old "X/7") made perfect logging read as a
            # gap. Denominator = COMPLETE days in the window (through yesterday); today's
            # absence is expected, surfaced via current_day_pending — not a miss.
            try:
                _complete_days = max(1, (datetime.strptime(end_date, "%Y-%m-%d") - datetime.strptime(start_date, "%Y-%m-%d")).days)
            except Exception:
                _complete_days = 6
            # ADR-104 (#948): same week-over-week rule as sleep — no prior-week data,
            # no comparison claim (week 1 of a cycle must not read "vs 0 last week").
            _has_wow = bool(cals and prev_cals)
            summary = {
                "primary": {
                    "label": "Avg Calories",
                    "value": round(avg_cal) if cals else None,
                    "unit": "kcal",
                    "delta": round(avg_cal - prev_avg_cal) if _has_wow else None,
                    "delta_label": f"vs {round(prev_avg_cal)} last week" if _has_wow else "",
                    "trend": ("up" if avg_cal > prev_avg_cal else "down") if _has_wow else "flat",
                    "sparkline": [round(c) for c in cals],
                },
                "highlight": {"label": "Avg Protein", "value": f"{round(avg_protein)}g/day", "detail": ""},
                "lowlight": {
                    "label": "Days logged",
                    "value": f"{len(cals)}/{_complete_days}",
                    "detail": "complete days · today uploads tonight",
                },
                "current_day_pending": True,
            }
            notable = f"Protein averaged {round(avg_protein)}g/day this week"

        elif domain == "training":
            items = _query_source("whoop", start_date, end_date, include_pilot=ip)
            strains = [float(i.get("strain", 0)) for i in items if i.get("strain")]
            recoveries = [float(i.get("recovery_score", 0)) for i in items if i.get("recovery_score")]
            avg_strain = sum(strains) / len(strains) if strains else 0
            avg_recovery = sum(recoveries) / len(recoveries) if recoveries else 0

            summary = {
                "primary": {
                    "label": "Avg Strain",
                    "value": round(avg_strain, 1),
                    "unit": "",
                    "delta": 0,
                    "delta_label": "",
                    "trend": "flat",
                    "sparkline": [round(s, 1) for s in strains],
                },
                "highlight": {"label": "Avg Recovery", "value": f"{round(avg_recovery)}%", "detail": ""},
                "lowlight": {"label": "Active Days", "value": f"{len([s for s in strains if s > 5])}/7", "detail": ""},
            }
            notable = f"Average recovery {round(avg_recovery)}% this week"

        elif domain == "glucose":
            items = _query_source("apple_health", start_date, end_date, include_pilot=ip)
            tirs = [float(i.get("blood_glucose_time_in_range_pct", 0)) for i in items if i.get("blood_glucose_time_in_range_pct")]
            avg_tir = sum(tirs) / len(tirs) if tirs else 0
            avg_glucoses = [float(i.get("blood_glucose_avg", 0)) for i in items if i.get("blood_glucose_avg")]
            avg_glucose = sum(avg_glucoses) / len(avg_glucoses) if avg_glucoses else 0

            summary = {
                "primary": {
                    "label": "Avg TIR",
                    "value": round(avg_tir, 1),
                    "unit": "%",
                    "delta": 0,
                    "delta_label": "",
                    "trend": "flat",
                    "sparkline": [round(t, 1) for t in tirs],
                },
                "highlight": {
                    "label": "Best Day",
                    "value": f"{round(max(tirs))}% TIR" if tirs else "\u2014",
                    "detail": f"Avg glucose {round(avg_glucose)} mg/dL" if avg_glucose else "",
                },
                "lowlight": {"label": "Worst Day", "value": f"{round(min(tirs))}% TIR" if tirs else "\u2014", "detail": ""},
            }
            notable = f"Average time-in-range {round(avg_tir)}% this week"

        elif domain == "mind":
            items = _query_source("journal", start_date, end_date, include_pilot=ip)
            moods = [float(i.get("mood_valence", 0)) for i in items if i.get("mood_valence") is not None]
            avg_mood = sum(moods) / len(moods) if moods else 0

            summary = {
                "primary": {
                    "label": "Avg Mood",
                    "value": round(avg_mood, 2),
                    "unit": "",
                    "delta": 0,
                    "delta_label": "",
                    "trend": "flat",
                    "sparkline": [round(m, 2) for m in moods],
                },
                "highlight": {"label": "Journal Entries", "value": str(len(items)), "detail": "this week"},
                "lowlight": {"label": "Energy", "value": "—", "detail": ""},
            }
            notable = f"{len(items)} journal entries this week"

        elif domain == "physical":
            items = _query_source("withings", start_date, end_date, include_pilot=ip)
            weights = [float(i.get("weight_lbs", 0)) for i in items if i.get("weight_lbs")]
            if weights:
                start_w = weights[0]
                end_w = weights[-1]
                delta = round(end_w - start_w, 1)
                summary = {
                    "primary": {
                        "label": "Weight Change",
                        "value": round(end_w),
                        "unit": "lbs",
                        "delta": delta,
                        "delta_label": f"{delta:+.1f} lbs this week",
                        "trend": "down" if delta < 0 else "up",
                        "sparkline": [round(w) for w in weights],
                    },
                    "highlight": {"label": "Weigh-ins", "value": str(len(weights)), "detail": "this week"},
                    "lowlight": {"label": "Current", "value": f"{round(end_w)} lbs", "detail": ""},
                }
                notable = f"Weight {'dropped' if delta < 0 else 'gained'} {abs(delta)} lbs this week"
            else:
                summary = {
                    "primary": {
                        "label": "Weight",
                        "value": None,
                        "unit": "lbs",
                        "delta": 0,
                        "delta_label": "",
                        "trend": "flat",
                        "sparkline": [],
                    },
                    "highlight": {"label": "Weigh-ins", "value": "0", "detail": "this week"},
                    "lowlight": {"label": "", "value": "", "detail": ""},
                }
                notable = "No weigh-ins recorded this week"

        else:
            return _error(400, "Unsupported domain")

        return _ok(
            {
                "domain": domain,
                "period": {"start": start_date, "end": end_date},
                "summary": summary,
                "notable": notable,
                "last_updated": now.isoformat(),
                "as_of_date": end_date,
                "time_travel": ip,
            },
            cache_seconds=86400 if ip else 900,  # the past is immutable
        )

    except Exception as e:
        logger.warning(f"[observatory_week] {domain} failed: {e}")
        return _error(503, f"Weekly {domain} data temporarily unavailable.")


def _engaged_dates(start: str, end: str, *, _g) -> set:
    # Facade state injected via `_g` (the delegator's globals()) — same module the test patched.
    _query_source = _g["_query_source"]
    days = set()
    for src in _ENGAGEMENT_SOURCES:
        for r in _query_source(src, start, end, include_pilot=True):
            days.add(str(r.get("sk", ""))[5:15])
    return days


def cycle_compare(*, _g) -> dict:
    """GET /api/cycle_compare — matched-window comparison across cycles.

    Window K = days elapsed in the CURRENT cycle (capped at 28), applied
    identically to every cycle so day-5 of cycle 3 is compared with day-5 of
    cycles 1 and 2 — never a 5-day run vs a 60-day run.
    """
    # Facade state injected via `_g` (the delegator's globals()) — same module the test patched.
    CYCLE_GENESES = _g["CYCLE_GENESES"]
    _query_source = _g["_query_source"]
    pre_start_meta = _g["pre_start_meta"]
    try:
        current = max(CYCLE_GENESES)

        # PRE-START (#948): the current cycle is staged but has 0 elapsed days — a
        # matched window of 0 days is not a comparison, and flooring it to 1 produced
        # the degenerate "the same first 1 days" pseudo-window. Say when the comparison
        # begins instead. Inert (normal path below) once genesis <= today.
        _pre = pre_start_meta()
        if _pre:
            return _ok(
                {
                    "window_days": 0,
                    "current_cycle": current,
                    "cycles": [],
                    "note": (
                        f"Cycle {current} begins {CYCLE_GENESES[current]}. The matched-window comparison "
                        "starts with Day 1 — no pseudo-window before then. Correlative, N=1."
                    ),
                    **_pre,
                },
                cache_seconds=3600,
            )

        today = datetime.now(PT).date()
        elapsed = (today - datetime.strptime(CYCLE_GENESES[current], "%Y-%m-%d").date()).days + 1
        window = max(1, min(elapsed, 28))

        cycles = []
        for n, genesis in sorted(CYCLE_GENESES.items()):
            g = datetime.strptime(genesis, "%Y-%m-%d").date()
            end = (g + timedelta(days=window - 1)).isoformat()
            wd = _query_source("withings", genesis, end, include_pilot=True)
            wh = _query_source("whoop", genesis, end, include_pilot=True)

            weights = [(r["sk"][5:], float(r["weight_lbs"])) for r in wd if r.get("weight_lbs")]
            weights.sort()
            rec = [float(r["recovery_score"]) for r in wh if r.get("recovery_score")]
            slp = [float(r["sleep_duration_hours"]) for r in wh if r.get("sleep_duration_hours")]

            cycles.append(
                {
                    "cycle": n,
                    "genesis": genesis,
                    "is_current": n == current,
                    "weight_start_lbs": round(weights[0][1], 1) if weights else None,
                    "weight_delta_lbs": round(weights[-1][1] - weights[0][1], 1) if len(weights) >= 2 else None,
                    "avg_recovery_pct": round(sum(rec) / len(rec), 1) if rec else None,
                    "avg_sleep_hours": round(sum(slp) / len(slp), 2) if slp else None,
                    "days_with_data": len({r["sk"] for r in wd} | {r["sk"] for r in wh}),
                }
            )

        return _ok(
            {
                "window_days": window,
                "current_cycle": current,
                "cycles": cycles,
                "note": (
                    # #948: "first 1 days" recurs on every genesis day of every cycle — pluralize.
                    f"Each cycle measured over its own first {window} day{'s' if window != 1 else ''} — matched windows, "
                    "never a short run vs a long one. Correlative, N=1."
                ),
            },
            cache_seconds=3600,
        )
    except Exception as e:
        logger.warning(f"[cycle_compare] failed: {e}")
        return _error(503, "Cycle comparison temporarily unavailable.")


def survival(*, _g) -> dict:
    """GET /api/survival — per-cycle engagement strips + a loudly-caveated
    probability that the current cycle reaches day 30."""
    # Facade state injected via `_g` (the delegator's globals()) — same module the test patched.
    CYCLE_GENESES = _g["CYCLE_GENESES"]
    try:
        today = datetime.now(PT).date()
        geneses = sorted(CYCLE_GENESES.items())
        cycles, priors = [], []
        for idx, (n, genesis) in enumerate(geneses):
            g = datetime.strptime(genesis, "%Y-%m-%d").date()
            next_g = datetime.strptime(geneses[idx + 1][1], "%Y-%m-%d").date() if idx + 1 < len(geneses) else None
            last = min((next_g - timedelta(days=1)) if next_g else today, g + timedelta(days=69))
            window = (last - g).days + 1
            if window < 1:
                continue
            engaged = _engaged_dates(genesis, last.isoformat(), _g=_g)
            strip = [(g + timedelta(days=i)).isoformat() in engaged for i in range(window)]
            collapse_day = None
            for i in range(0, window - _COLLAPSE_GAP + 1):
                if not any(strip[i : i + _COLLAPSE_GAP]):
                    collapse_day = i + 1
                    break
            is_current = next_g is None
            ended_by_reset = next_g is not None and collapse_day is None
            cycles.append(
                {
                    "cycle": n,
                    "genesis": genesis,
                    "is_current": is_current,
                    "window_days": window,
                    "engaged_days": sum(strip),
                    "strip": "".join("█" if d else "·" for d in strip),
                    "collapse_day": collapse_day,
                    "censored": ended_by_reset,  # re-anchored while still engaged
                }
            )
            if not is_current:
                priors.append((collapse_day, window))

        # Laplace-smoothed survival-to-30 from prior cycles: a cycle counts as a
        # survivor if it stayed engaged through day 30 OR was reset while still
        # engaged before 30 (censored — treated optimistically, and we say so).
        survivors = sum(1 for cd, w in priors if cd is None or cd > _SURVIVAL_HORIZON)
        p30 = round((survivors + 1) / (len(priors) + 2) * 100)

        cur = next((c for c in cycles if c["is_current"]), None)
        cur_strip = str(cur["strip"]) if cur else ""
        silent_now = len(cur_strip) - len(cur_strip.rstrip("·")) if cur else 0

        return _ok(
            {
                "horizon_days": _SURVIVAL_HORIZON,
                "p_reach_30_pct": p30,
                "method": f"Laplace-smoothed over {len(priors)} prior cycles: (survivors+1)/(n+2). n=2 is narrative, not statistics.",
                "current_silent_days": silent_now,
                "collapse_definition": f"{_COLLAPSE_GAP}+ consecutive days with no weigh-in, food log, or journal entry",
                "cycles": cycles,
                "confidence": "preliminary pattern · n=2 cycles",
                "note": (
                    "The model handicapping its own human. Engagement counts only deliberate "
                    "acts — weigh-ins, food logs, journal entries — never passive wearable data. "
                    "Treat the probability as a mirror, not a forecast."
                ),
            },
            cache_seconds=3600,
        )
    except Exception as e:
        logger.warning(f"[survival] failed: {e}")
        return _error(503, "Survival curve temporarily unavailable.")
