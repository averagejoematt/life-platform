"""
Health & body composition tools.
"""

from datetime import datetime, timedelta, timezone

from mcp.config import logger
from mcp.core import date_diff_days, decimal_to_float, get_profile, query_source
from mcp.helpers import normalize_whoop_sleep
from mcp.tools_training import _get_training_load


def tool_get_readiness_score(args):
    """
    Unified readiness score (0–100) synthesising Whoop recovery, Whoop sleep quality,
    HRV 7-day trend, TSB training form, and Garmin Body Battery into a single
    GREEN / YELLOW / RED signal with a 1-line actionable recommendation.

    Weights:
      Whoop recovery score  : 40%
      Whoop sleep quality    : 25%
      HRV 7-day trend       : 20%
      TSB training form     : 10%
      Garmin Body Battery   : 5%

    If a component is unavailable, remaining weights are re-normalised so the
    score is still meaningful with partial data. Garmin Body Battery is
    additionally skipped when it is more than 1 day staler than the newest
    Whoop record (Garmin ingestion is unreliable), to keep stale Garmin data
    from entering the score.

    The top-level "date" reflects the actual newest data date across components,
    not the requested date. When the requested date has no data yet (its
    overnight hasn't happened), "is_forward_dated" is true and a
    "staleness_warning" explains the score reflects the latest available data.

    Device agreement: Whoop vs Garmin HRV and RHR delta is computed and returned
    as a confidence signal — large disagreement flags lower score reliability.
    """
    # Bad input returns an error DICT, never a stack trace out of the tool: an
    # unparseable string used to raise ValueError and an explicit {"date": None}
    # raised TypeError, both of which reach the MCP caller as a crash.
    end_date = args.get("date", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    if not isinstance(end_date, str) or not end_date.strip():
        return {"error": f"Invalid 'date' argument ({end_date!r}) — expected a YYYY-MM-DD string, or omit it for today."}
    try:
        _end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    except ValueError:
        return {"error": f"Could not parse date {end_date!r} — expected YYYY-MM-DD (e.g. 2026-05-10)."}
    # #1917 window-name honesty: `sk BETWEEN DATE#start AND DATE#end~` is
    # INCLUSIVE at both ends, so a 7-day window starts 6 days back, not 7.
    # `days=7`/`days=30` spanned 8/31 dates while publishing hrv_7d_avg_ms,
    # hrv_30d_baseline_ms and n_days_7d — every one naming a window it outran.
    d7_start = (_end_dt - timedelta(days=6)).strftime("%Y-%m-%d")
    d30_start = (_end_dt - timedelta(days=29)).strftime("%Y-%m-%d")

    def _clamp(v, lo=0.0, hi=100.0):
        return max(lo, min(hi, v))

    # ── Pre-computed metrics (SIMP-1 Ph1): single read replaces 30d Whoop +
    #    264d Strava Banister model. Falls back to live calculation if absent. ──
    _cm = {}
    try:
        cm_recs = query_source("computed_metrics", d7_start, end_date)
        cm_recs_sorted = sorted(cm_recs, key=lambda r: r.get("date", ""), reverse=True)
        _cm = next((r for r in cm_recs_sorted if r.get("date") == end_date), cm_recs_sorted[0] if cm_recs_sorted else {})
    except Exception as _e:
        logger.warning(f"get_readiness_score: computed_metrics read failed — {_e}")

    components = {}

    # ── 1. Whoop recovery score (40%) ─────────────────────────────────────────
    whoop_recent = query_source("whoop", d7_start, end_date)
    whoop_sorted = sorted(whoop_recent, key=lambda x: x.get("date", ""), reverse=True)
    whoop_today = next((w for w in whoop_sorted if w.get("recovery_score") is not None), None)

    if whoop_today:
        rec_score = float(whoop_today["recovery_score"])
        components["whoop_recovery"] = {
            "score": round(rec_score, 1),
            "weight": 0.40,
            "raw": {
                "date": whoop_today.get("date"),
                "recovery_score": whoop_today.get("recovery_score"),
                "hrv_ms": whoop_today.get("hrv"),
                "resting_hr": whoop_today.get("resting_heart_rate"),
                "sleep_hours": whoop_today.get("sleep_duration_hours"),
            },
        }

    # ── 2. Sleep quality score (25%) ─ Whoop SOT v2.55.0 ────────────────────────
    # Reuse whoop_recent (already fetched above) — avoids duplicate 7d Whoop query
    sleep_recent = [normalize_whoop_sleep(i) for i in whoop_recent]
    sleep_sorted = sorted(sleep_recent, key=lambda x: x.get("date", ""), reverse=True)
    sleep_today = next((s for s in sleep_sorted if s.get("sleep_score") is not None or s.get("sleep_efficiency_pct") is not None), None)

    if sleep_today:
        # Prefer native sleep_score (0-100); fallback: derive from efficiency
        if sleep_today.get("sleep_score") is not None:
            es_score = float(sleep_today["sleep_score"])
            es_method = "sleep_score"
        else:
            eff = float(sleep_today["sleep_efficiency_pct"])
            # 75% eff → ~50 score; 85% → ~70; 95% → ~90 (linear: score = eff - 25)
            es_score = _clamp(eff - 25.0)
            es_method = "derived_from_efficiency"

        components["sleep_quality"] = {
            "score": round(es_score, 1),
            "weight": 0.25,
            "raw": {
                "date": sleep_today.get("date"),
                "sleep_score": sleep_today.get("sleep_score"),
                "sleep_efficiency_pct": sleep_today.get("sleep_efficiency_pct"),
                "sleep_duration_hours": sleep_today.get("sleep_duration_hours"),
                "rem_pct": sleep_today.get("rem_pct"),
                "deep_pct": sleep_today.get("deep_pct"),
                "scoring_method": es_method,
            },
        }

    # ── 3. HRV 7-day trend vs 30-day baseline (20%) ───────────────────────────
    # SIMP-1 Ph1: read hrv_7d / hrv_30d from computed_metrics (single record)
    # instead of re-querying 30 days of Whoop at call time.
    hrv_7d_avg = float(_cm["hrv_7d"]) if _cm.get("hrv_7d") is not None else None
    hrv_30d_avg = float(_cm["hrv_30d"]) if _cm.get("hrv_30d") is not None else None

    if hrv_7d_avg is not None and hrv_30d_avg is not None and hrv_30d_avg > 0:
        ratio = hrv_7d_avg / hrv_30d_avg
        trend_pct = round((ratio - 1.0) * 100, 1)
        # Base 60 (neutral readiness); +10% HRV above baseline = score 80, -10% = score 40
        hrv_score = _clamp(60.0 + (ratio - 1.0) * 200.0)
        # ADR-105: the n travels with the average on BOTH branches. The live
        # fallback below counts its own readings; this branch can only report
        # what daily-metrics-compute stored beside the average — and today it
        # stores none, so the n publishes as an explicit absence rather than
        # being silently omitted (which read as "n not applicable").
        _n7 = _cm.get("hrv_7d_n")
        _n30 = _cm.get("hrv_30d_n")
        _hrv_raw = {
            "hrv_7d_avg_ms": round(hrv_7d_avg, 1),
            "hrv_30d_baseline_ms": round(hrv_30d_avg, 1),
            "trend_pct": trend_pct,
            "trend_direction": "above_baseline" if trend_pct > 3 else ("below_baseline" if trend_pct < -3 else "at_baseline"),
            "n_days_7d": int(_n7) if _n7 is not None else None,
            "n_days_30d": int(_n30) if _n30 is not None else None,
            "source": "pre_computed_metrics",
        }
        if _n7 is None or _n30 is None:
            _hrv_raw["n_note"] = (
                "daily-metrics-compute stores the HRV averages without the reading counts behind them, "
                "so the n is unknown for this branch — treat the trend as unweighted by sample size."
            )
        components["hrv_trend"] = {
            "score": round(hrv_score, 1),
            "weight": 0.20,
            "raw": _hrv_raw,
        }
    else:
        # Fallback: live 30-day Whoop query (pre-compute record missing)
        whoop_30d = query_source("whoop", d30_start, end_date)
        hrv_30d_vals = [float(w["hrv"]) for w in whoop_30d if w.get("hrv") is not None]
        hrv_7d_vals = [float(w["hrv"]) for w in whoop_recent if w.get("hrv") is not None]
        if len(hrv_30d_vals) >= 7 and hrv_7d_vals:
            baseline = sum(hrv_30d_vals) / len(hrv_30d_vals)
            recent7 = sum(hrv_7d_vals) / len(hrv_7d_vals)
            ratio = recent7 / baseline if baseline > 0 else 1.0
            trend_pct = round((ratio - 1.0) * 100, 1)
            # Base 60 (neutral readiness); +10% HRV above baseline = score 80, -10% = score 40
            hrv_score = _clamp(60.0 + (ratio - 1.0) * 200.0)
            components["hrv_trend"] = {
                "score": round(hrv_score, 1),
                "weight": 0.20,
                "raw": {
                    "hrv_7d_avg_ms": round(recent7, 1),
                    "hrv_30d_baseline_ms": round(baseline, 1),
                    "trend_pct": trend_pct,
                    "trend_direction": "above_baseline" if trend_pct > 3 else ("below_baseline" if trend_pct < -3 else "at_baseline"),
                    "n_days_30d": len(hrv_30d_vals),
                    "n_days_7d": len(hrv_7d_vals),
                    "source": "live_whoop_query",
                },
            }

    # ── 4. TSB training form (10%) ────────────────────────────────────────────
    # SIMP-1 Ph1: read tsb from computed_metrics instead of calling
    # _get_training_load (which queries 264 days of Strava + runs Banister model).
    tsb_cm = float(_cm["tsb"]) if _cm.get("tsb") is not None else None
    if tsb_cm is not None:
        # TSB +12 = 100 (peak form), TSB -28 = 0 (deeply fatigued). #490: tsb is now
        # on the shared TSS-like scale (training_load), which is what these bands
        # always assumed. Band order: most-negative check first (the old ordering made
        # "very fatigued" unreachable).
        tsb_score = _clamp(70.0 + tsb_cm * 2.5)
        form = (
            "fresh — good for key sessions or race"
            if tsb_cm > 5
            else (
                "very fatigued — recovery priority"
                if tsb_cm < -25
                else "fatigued — accumulated training stress is high" if tsb_cm < -10 else "neutral"
            )
        )
        # M-3 (#490): surface the stored load provenance beside the number.
        _tsb_basis = _cm.get("tsb_load_basis") or {}
        _tsb_conf = str(_tsb_basis.get("confidence") or "")
        raw = {
            "tsb_form": round(tsb_cm, 2),
            "form_status": form,
            "load_basis": _tsb_conf or "unknown",
            "source": "pre_computed_metrics",
        }
        if _tsb_conf and _tsb_conf != "power":
            raw["load_basis_note"] = "duration-proxy basis — loads are TSS-like estimates from duration/HR, not power-meter data"
        components["training_form"] = {
            "score": round(tsb_score, 1),
            "weight": 0.10,
            "raw": raw,
        }
    else:
        # Fallback: live Banister model (264d Strava query — only runs if pre-compute missing)
        try:
            load_result = _get_training_load({"end_date": end_date})
            cs = load_result.get("current_state") or {}
            # ADR-104: _get_training_load fills EVERY calendar date in its window,
            # using 0.0 for dates with no record — so a platform with no training
            # data at all still yields ctl=atl=0 -> tsb_form 0.0 -> clamp(70+0) =
            # a training_form component scoring 70.0 at 10% weight. With nothing
            # else present that renormalised to exactly 70.0 => GREEN => "go ahead
            # with your planned hard session" on a wholly silent platform. An
            # all-zero Banister series is the ABSENCE of training data, not
            # measured freshness: publish no component rather than a neutral 70.
            _measured_load = float(cs.get("ctl_fitness") or 0) > 0 or float(cs.get("atl_fatigue") or 0) > 0
            if cs and _measured_load:
                tsb = cs.get("tsb_form", 0.0)
                tsb_score = _clamp(70.0 + float(tsb) * 2.5)
                components["training_form"] = {
                    "score": round(tsb_score, 1),
                    "weight": 0.10,
                    "raw": {
                        "tsb_form": cs.get("tsb_form"),
                        "ctl_fitness": cs.get("ctl_fitness"),
                        "atl_fatigue": cs.get("atl_fatigue"),
                        "acwr": cs.get("acwr"),
                        "form_status": cs.get("form_status"),
                        "source": "live_banister_model",
                    },
                }
        except Exception as e:
            logger.warning(f"get_readiness_score: TSB fallback failed — {e}")

    # ── 5. Garmin Body Battery (10%) ──────────────────────────────────────────
    garmin_recent = query_source("garmin", d7_start, end_date)
    garmin_sorted = sorted(garmin_recent, key=lambda x: x.get("date", ""), reverse=True)
    garmin_today = next((g for g in garmin_sorted if g.get("body_battery_end") is not None or g.get("body_battery_high") is not None), None)

    # Freshness gate: Garmin ingestion is unreliable and Body Battery can be days
    # stale. Skip it entirely when it's more than 1 day older than the newest Whoop
    # record so stale Garmin data can't enter the score at full weight. The weight
    # re-normalisation below redistributes the freed weight onto Whoop automatically.
    garmin_stale = False
    if garmin_today and whoop_today and garmin_today.get("date") and whoop_today.get("date"):
        if date_diff_days(garmin_today["date"], whoop_today["date"]) > 1:
            garmin_stale = True

    if garmin_today and not garmin_stale:
        # Use end-of-day Body Battery as primary; fall back to high if end is missing.
        # ADR-104: `end or high` treated a fully-depleted 0 — a REAL reading, and the
        # strongest "rest today" signal Garmin produces — as missing and substituted
        # the day's HIGH. Presence is `is not None`, matching the selection guard above.
        bb = garmin_today.get("body_battery_end")
        if bb is None:
            bb = garmin_today.get("body_battery_high")
        if bb is not None:
            bb_score = _clamp(float(bb))  # Body Battery is already 0-100
            components["garmin_body_battery"] = {
                "score": round(bb_score, 1),
                "weight": 0.05,
                "raw": {
                    "date": garmin_today.get("date"),
                    "body_battery_end": garmin_today.get("body_battery_end"),
                    "body_battery_high": garmin_today.get("body_battery_high"),
                    "body_battery_low": garmin_today.get("body_battery_low"),
                    "avg_stress": garmin_today.get("avg_stress"),
                    "hrv_last_night": garmin_today.get("hrv_last_night"),
                    "hrv_status": garmin_today.get("hrv_status"),
                },
            }

    # ── Device agreement: Whoop vs Garmin cross-validation ───────────────────
    # #492/M-7: never a silent null — when the cross-check can't run, say why
    # (structurally None since ~06-16 because Garmin is paused, ADR-074).
    if garmin_today is None:
        device_agreement = {"status": "unavailable", "reason": "garmin paused (ADR-074) — no recent Garmin record to cross-check"}
    elif garmin_stale:
        device_agreement = {
            "status": "unavailable",
            "reason": f"garmin record ({garmin_today.get('date')}) is >1 day older than whoop — stale data excluded",
        }
    elif "whoop_recovery" not in components:
        device_agreement = {"status": "unavailable", "reason": "no whoop recovery record to cross-check against"}
    else:
        device_agreement = {"status": "unavailable", "reason": "overlapping garmin+whoop records lack comparable HRV/RHR fields"}
    # `not garmin_stale` is load-bearing: without it this block OVERWROTE the
    # "stale data excluded" verdict above with a cross-check computed from that
    # very record, publishing "device_agreement: available, confidence: high" off
    # a reading the tool had just refused to score at 5% weight.
    if "whoop_recovery" in components and garmin_today is not None and not garmin_stale:
        whoop_hrv_val = components["whoop_recovery"]["raw"].get("hrv_ms")
        garmin_hrv_val = garmin_today.get("hrv_last_night")
        whoop_rhr_val = components["whoop_recovery"]["raw"].get("resting_hr")
        garmin_rhr_val = garmin_today.get("resting_heart_rate")

        checks = {}
        agreement_signals = []

        if whoop_hrv_val is not None and garmin_hrv_val is not None:
            hrv_diff = abs(float(whoop_hrv_val) - float(garmin_hrv_val))
            hrv_status = "agree" if hrv_diff <= 10 else ("minor_variance" if hrv_diff <= 20 else "flag")
            checks["hrv"] = {
                "whoop_ms": round(float(whoop_hrv_val), 1),
                "garmin_ms": round(float(garmin_hrv_val), 1),
                "delta_ms": round(float(whoop_hrv_val) - float(garmin_hrv_val), 1),
                "status": hrv_status,
            }
            agreement_signals.append(hrv_status)

        if whoop_rhr_val is not None and garmin_rhr_val is not None:
            rhr_diff = abs(float(whoop_rhr_val) - float(garmin_rhr_val))
            rhr_status = "agree" if rhr_diff <= 3 else ("minor_variance" if rhr_diff <= 6 else "flag")
            checks["rhr"] = {
                "whoop_bpm": round(float(whoop_rhr_val), 1),
                "garmin_bpm": round(float(garmin_rhr_val), 1),
                "delta_bpm": round(float(whoop_rhr_val) - float(garmin_rhr_val), 1),
                "status": rhr_status,
            }
            agreement_signals.append(rhr_status)

        if agreement_signals:
            has_flag = any(s == "flag" for s in agreement_signals)
            all_agree = all(s == "agree" for s in agreement_signals)
            confidence = "high" if all_agree else ("low" if has_flag else "moderate")
            device_agreement = {
                "status": "available",
                "confidence": confidence,
                "checks": checks,
                "note": "flag = significant inter-device disagreement; readiness score may be less reliable on flagged days",
            }

    # ── Weighted aggregate ────────────────────────────────────────────────────
    total_weight = sum(c["weight"] for c in components.values())

    if not components:
        return {"error": "No data available from any source for this date. Check ingestion pipeline."}

    raw_score = sum(c["score"] * c["weight"] for c in components.values()) / total_weight
    readiness_score = round(raw_score, 1)

    # Label
    if readiness_score >= 70:
        label = "GREEN"
    elif readiness_score >= 40:
        label = "YELLOW"
    else:
        label = "RED"

    # ── Recommendation ────────────────────────────────────────────────────────
    missing = []
    all_keys = {"whoop_recovery", "sleep_quality", "hrv_trend", "training_form", "garmin_body_battery"}
    for k in sorted(all_keys - set(components.keys())):
        missing.append(k.replace("_", " "))

    # Build context-aware recommendation
    rec_parts = []

    if label == "GREEN":
        rec_parts.append("You're primed — go ahead with your planned hard session.")
        if "training_form" in components and components["training_form"]["raw"].get("tsb_form", 0) > 8:
            rec_parts.append("TSB is notably positive, meaning you're very fresh — a good day for a PR attempt or race effort.")
    elif label == "YELLOW":
        rec_parts.append("Moderate readiness — a controlled effort is appropriate; skip high-intensity intervals.")
        if "whoop_recovery" in components and components["whoop_recovery"]["score"] < 50:
            rec_parts.append("Whoop recovery is low — prioritise aerobic work over heavy strength training today.")
        if "sleep_quality" in components and components["sleep_quality"]["score"] < 50:
            rec_parts.append("Sleep quality was below average — consider a shorter session and extra cool-down.")
    else:  # RED
        rec_parts.append("Recovery day. Hard training now will deepen fatigue without adding fitness.")
        if "hrv_trend" in components and components["hrv_trend"]["raw"]["trend_pct"] < -10:
            rec_parts.append("HRV is trending meaningfully below your baseline — this is your body asking for rest.")

    recommendation = " ".join(rec_parts)

    # ── Honest data date + staleness ──────────────────────────────────────────
    # Each component pulls a 7-day window and takes the newest available record,
    # so the components may pre-date the requested end_date (e.g. asking for a
    # date whose overnight hasn't happened yet). Surface the ACTUAL data date
    # rather than stamping the request. Only whoop_recovery / sleep_quality /
    # garmin_body_battery carry a raw.date.
    _data_dates = [
        components[k]["raw"].get("date")
        for k in ("whoop_recovery", "sleep_quality", "garmin_body_battery")
        if k in components and components[k]["raw"].get("date")
    ]
    # hrv_trend / training_form carry no raw.date of their own, so a score built
    # PURELY from a pre-computed metrics row used to fall through to the requested
    # date — a six-day-old record presented as today's readiness, with
    # is_forward_dated False and no staleness warning. The record's own date is
    # the honest as-of for any component sourced from it.
    if _cm.get("date") and any(
        components.get(k, {}).get("raw", {}).get("source") == "pre_computed_metrics" for k in ("hrv_trend", "training_form")
    ):
        _data_dates.append(_cm["date"])
    as_of_date = max(_data_dates) if _data_dates else end_date
    is_forward_dated = as_of_date < end_date

    result = {
        "date": as_of_date,
        "requested_date": end_date,
        "is_forward_dated": is_forward_dated,
        "readiness_score": readiness_score,
        "label": label,
        # ADR-105: the label is the one thing a reader quotes, so its uncertainty
        # travels WITH it rather than four keys away in a free-text
        # data_completeness string. Derived from the weight actually covered.
        "label_confidence": {
            "level": "high" if total_weight >= 0.85 else ("moderate" if total_weight >= 0.60 else "low"),
            "weight_covered_pct": round(total_weight * 100),
            "n_components": len(components),
            "note": (
                "Confidence reflects how much of the 100% scoring weight was actually measured. "
                "A low-confidence label is a signal about the data, not about the body."
            ),
        },
        "recommendation": recommendation,
        "components": components,
        "device_agreement": device_agreement,
        "data_completeness": "full" if total_weight >= 0.99 else f"partial ({round(total_weight*100)}% weight covered)",
        "missing_components": missing if missing else None,
        "scoring_note": (
            "Weights: Whoop recovery 40%, Whoop sleep quality 25%, HRV 7d trend 20%, TSB form 10%, "
            "Garmin Body Battery 5%. Missing components are excluded and remaining weights re-normalised. "
            "Garmin Body Battery is skipped when >1 day staler than the newest Whoop record."
        ),
        # R13-F09: Medical disclaimer on all health-assessment tool responses
        "_disclaimer": "For personal health tracking only. Not medical advice. Consult a qualified healthcare provider before making health decisions based on this data.",
    }
    if is_forward_dated:
        result["staleness_warning"] = (
            f"No data exists for the requested date ({end_date}) yet — its overnight hasn't been recorded. "
            f"This score reflects the latest available data ({as_of_date}) and should be treated as a "
            "current/trend signal, not the requested day's readiness."
        )
    # Cross-check: show pre-computed readiness if available (computed by daily-metrics-compute
    # with slightly different weights — useful to spot drift between models)
    if _cm.get("readiness_score") is not None:
        # `_cm` is selected as (exact end_date match, else newest in the 7-day
        # window), so the stored score can pre-date the live one. A drift detector
        # that silently compares today against last week reports drift that isn't
        # there — the day it was computed FOR ships with the number.
        _cc_date = _cm.get("date")
        result["_precomputed_cross_check"] = {
            "date": _cc_date,
            "computed_for_requested_date": _cc_date == end_date,
            "readiness_score": float(_cm["readiness_score"]),
            "label": _cm.get("readiness_colour", ""),
            "source": "daily-metrics-compute (9:40 AM)",
            "note": "Pre-computed with Whoop recovery 40% + sleep 30% + HRV trend 20% + TSB 10% (no Body Battery component). Minor weight difference from live tool.",
        }
        if _cc_date and _cc_date != end_date:
            result["_precomputed_cross_check"]["drift_note"] = (
                f"The stored score is for {_cc_date}, not the requested {end_date} — a difference from the live "
                "score above may be elapsed time rather than model drift."
            )
    return result


def tool_get_weight_loss_progress(args):
    end_date = args.get("end_date", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    explicit_start = args.get("start_date")  # None when caller didn't pass one
    profile = get_profile()

    journey_start = profile.get("journey_start_date")
    journey_start_wt = profile.get("journey_start_weight_lbs")
    goal_weight = profile.get("goal_weight_lbs")
    # ADR-104: no default height. A missing height used to silently become 70in,
    # from which the tool published a BMI, a CLINICAL BMI CATEGORY, milestone
    # crossings and lbs-to-cross — a fabricated clinical classification with no
    # note anywhere that the input was assumed (at 311 lbs, 44.6 vs his real 42.2).
    height_in = profile.get("height_inches")

    # HONOR an explicit start_date verbatim — the old code always overrode it
    # with journey_start. No leak risk: query_source's phase filter (ADR-058)
    # hides pre-genesis pilot data regardless of window width. Default to genesis
    # when no start is passed, then a far-past floor.
    effective_start = explicit_start or journey_start or "2010-01-01"

    # Future/empty-window guard: a freshly re-anchored genesis can sit AHEAD of
    # today (e.g. genesis 2026-06-14 set on 2026-06-13). query_source would then
    # get start > end and raise a DynamoDB BETWEEN ValidationException. Return the
    # honest pre-genesis state instead of erroring.
    if effective_start > end_date:
        return {
            "error": f"No weight data yet — the experiment is anchored to {journey_start or effective_start}, "
            f"which is after {end_date}. Progress appears once weigh-ins accrue.",
            "pre_genesis": True,
            "journey_start_date": journey_start,
        }

    withings_items = query_source("withings", effective_start, end_date)
    if not withings_items:
        return {"error": "No Withings weight data found. Ensure scale is syncing."}

    weight_series = []
    for item in sorted(withings_items, key=lambda x: x.get("date", "")):
        wt = item.get("weight_lbs")
        if wt is not None:
            weight_series.append({"date": item["date"], "weight_lbs": round(float(wt), 1)})

    if not weight_series:
        return {"error": "No weight_lbs field found in Withings data."}

    def calc_bmi(weight_lbs, height_in):
        if not height_in:
            return None
        # 703 converts imperial (lbs/in^2) to metric BMI (kg/m^2)
        return round(703 * weight_lbs / (height_in**2), 1)

    bmi_categories = [
        (18.5, "Underweight"),
        (25.0, "Normal weight"),
        (30.0, "Overweight"),
        (35.0, "Obese Class I"),
        (40.0, "Obese Class II"),
        (float("inf"), "Obese Class III"),
    ]

    def bmi_category(bmi):
        if bmi is None:
            return None
        for threshold, label in bmi_categories:
            if bmi < threshold:
                return label
        return "Obese Class III"

    for pt in weight_series:
        bmi = calc_bmi(pt["weight_lbs"], height_in)
        pt["bmi"] = bmi
        pt["bmi_category"] = bmi_category(bmi)

    weekly_rates = []
    for i in range(len(weight_series)):
        pt = weight_series[i]
        target_dt = datetime.strptime(pt["date"], "%Y-%m-%d") - timedelta(days=7)
        prior = None
        best_gap = 999
        for j in range(i):
            d = datetime.strptime(weight_series[j]["date"], "%Y-%m-%d")
            gap = abs((target_dt - d).days)
            if gap < best_gap:
                best_gap = gap
                prior = weight_series[j]
        if prior and best_gap <= 4:
            days_diff = (datetime.strptime(pt["date"], "%Y-%m-%d") - datetime.strptime(prior["date"], "%Y-%m-%d")).days
            if days_diff > 0:
                weekly_rate = round((prior["weight_lbs"] - pt["weight_lbs"]) / days_diff * 7, 2)
                pt["weekly_loss_rate_lbs"] = weekly_rate
                weekly_rates.append(weekly_rate)
                # >2.5 lbs/week exceeds ACSM safe rate; risk of lean mass catabolism (Helms 2014)
                if weekly_rate > 2.5:
                    pt["rate_flag"] = "⚠️ Losing too fast (>2.5 lbs/wk) — risk of muscle loss. Check nutrition."
                elif weekly_rate < 0:
                    pt["rate_flag"] = "↑ Weight gain this week"
                elif weekly_rate < 0.25 and len(weight_series) > 14:
                    pt["rate_flag"] = "⏸ Very slow — review deficit"

    milestones = {}
    milestone_thresholds = [
        (40.0, "🎯 Exited Obese Class III → Class II (BMI < 40)"),
        (35.0, "🎯 Exited Obese Class II → Class I (BMI < 35)"),
        (30.0, "🎯 Exited Obese → Overweight (BMI < 30)"),
        (25.0, "🎯 Reached Normal Weight (BMI < 25)"),
    ]
    prev_bmi = None
    for pt in weight_series:
        bmi = pt.get("bmi")
        if bmi is None or prev_bmi is None:
            prev_bmi = bmi
            continue
        for threshold, label in milestone_thresholds:
            key = f"bmi_{threshold}"
            if key not in milestones and prev_bmi >= threshold > bmi:
                milestones[key] = {"date": pt["date"], "milestone": label, "bmi": bmi, "weight_lbs": pt["weight_lbs"]}
        prev_bmi = bmi

    current_bmi = weight_series[-1].get("bmi")
    upcoming_milestones = []
    if current_bmi:
        for threshold, label in sorted(milestone_thresholds, key=lambda x: x[0], reverse=True):
            if current_bmi >= threshold:
                lbs_to_threshold = round((threshold - 0.1) * (height_in**2) / 703 - weight_series[-1]["weight_lbs"], 1) * -1
                # ADR-104: the old `max(mean_rate, 0.1)` floor existed to dodge a
                # divide-by-zero, but on a NEGATIVE mean (he is gaining) it clamped
                # to +0.1 lb/wk and published a confident finite ETA to a milestone
                # he is moving away from. A direction that isn't in the data is not
                # a number to manufacture: report None and say why.
                _recent = weekly_rates[-4:]
                _recent_mean = round(sum(_recent) / len(_recent), 2) if _recent else None
                _entry = {
                    "milestone": label,
                    "lbs_to_cross": round(lbs_to_threshold, 1),
                    "recent_pace_lbs_per_week": _recent_mean,
                    "n_recent_rates": len(_recent),
                }
                if _recent_mean is not None and _recent_mean > 0:
                    _entry["weeks_at_current_pace"] = round(lbs_to_threshold / _recent_mean, 1)
                else:
                    _entry["weeks_at_current_pace"] = None
                    _entry["pace_note"] = (
                        "No ETA: recent weight trend is flat or reversing "
                        f"({'no paired weigh-ins yet' if _recent_mean is None else f'{_recent_mean} lbs/week'}) — "
                        "at this pace the milestone is not being approached."
                    )
                upcoming_milestones.append(_entry)
                break

    plateau = None
    # The lookback hangs off END_DATE — the report's own anchor — not the wall
    # clock. A live `now` spliced into a caller-chosen window made a real plateau
    # inside a historical request invisible, and the one-sided `<= 14` also
    # admitted FUTURE-dated points as negative day counts.
    _anchor = datetime.strptime(end_date, "%Y-%m-%d").date()
    recent_14 = [pt for pt in weight_series if 0 <= (_anchor - datetime.strptime(pt["date"], "%Y-%m-%d").date()).days <= 14]
    if len(recent_14) >= 3:
        wts = [pt["weight_lbs"] for pt in recent_14]
        spread = max(wts) - min(wts)
        # <1.5lb range in 14d = plateau; accounts for ~2lb daily water fluctuation noise
        if spread < 1.5:
            # #1917: duration_days was the literal 14 no matter how far the
            # qualifying weigh-ins actually spanned — a 4-day cluster was reported
            # as a 14-day stall, which is a reason to cut calories.
            # Elapsed days between the first and last qualifying weigh-in.
            _span = (datetime.strptime(recent_14[-1]["date"], "%Y-%m-%d") - datetime.strptime(recent_14[0]["date"], "%Y-%m-%d")).days
            plateau = {
                "detected": True,
                "duration_days": _span,
                "n_weigh_ins": len(recent_14),
                "first_weigh_in": recent_14[0]["date"],
                "last_weigh_in": recent_14[-1]["date"],
                "weight_range_lbs": spread,
                "note": (
                    f"Scale has moved less than 1.5 lbs across {_span} days ({len(recent_14)} weigh-ins, "
                    f"{recent_14[0]['date']} → {recent_14[-1]['date']}). This is normal — check training load "
                    "and sleep quality before changing nutrition."
                ),
            }

    start_weight = weight_series[0]["weight_lbs"]
    current_weight = weight_series[-1]["weight_lbs"]
    total_lost = round(start_weight - current_weight, 1)
    avg_weekly = round(sum(weekly_rates) / len(weekly_rates), 2) if weekly_rates else None

    projection = None
    if goal_weight and avg_weekly and avg_weekly > 0:
        weeks_remaining = (current_weight - goal_weight) / avg_weekly
        # Anchored to the LAST WEIGH-IN the projection was computed from, not the
        # wall clock: three weeks off the scale used to slide the goal date three
        # weeks later while the underlying rate never moved.
        _last_weigh_in = weight_series[-1]["date"]
        goal_date = datetime.strptime(_last_weigh_in, "%Y-%m-%d") + timedelta(weeks=weeks_remaining)
        projection = {
            "goal_weight_lbs": goal_weight,
            "lbs_remaining": round(current_weight - goal_weight, 1),
            "avg_weekly_loss_lbs": avg_weekly,
            # ADR-105: the n behind the average travels with it — three paired
            # weigh-ins and thirty no longer produce identically-confident output.
            "n_weekly_rates": len(weekly_rates),
            "projected_from_date": _last_weigh_in,
            "projected_goal_date": goal_date.strftime("%Y-%m-%d"),
            "weeks_remaining": round(weeks_remaining, 1),
        }
        if journey_start_wt:
            pct_complete = round(100 * (journey_start_wt - current_weight) / (journey_start_wt - goal_weight), 1)
            projection["pct_complete"] = pct_complete

    return {
        "journey_start_date": journey_start,
        "journey_start_weight": journey_start_wt,
        "current_weight_lbs": current_weight,
        "current_bmi": weight_series[-1].get("bmi"),
        "current_bmi_category": weight_series[-1].get("bmi_category"),
        "total_lost_lbs": total_lost,
        "avg_weekly_loss_lbs": avg_weekly,
        "projection": projection,
        "plateau_detected": plateau,
        "milestones_achieved": milestones,
        "next_milestone": upcoming_milestones[0] if upcoming_milestones else None,
        "weight_series": weight_series,
        "clinical_note": "Safe loss rate: 0.5–2.0 lbs/week. >2.5 lbs/week consistently risks lean mass catabolism.",
    }


# ══════════════════════════════════════════════════════════════════════════════
# HYDRATION TRACKING ENHANCEMENT  (#30)
# ══════════════════════════════════════════════════════════════════════════════


def _get_energy_expenditure(args):
    end_date = args.get("end_date", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    try:
        _end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    except (ValueError, TypeError):
        return {"error": f"Could not parse end_date {end_date!r} — expected YYYY-MM-DD."}
    # Both window starts hang off END_DATE, not the wall clock. Asking for a
    # historical end_date used to issue `sk BETWEEN DATE#<recent> AND DATE#<older>~`
    # — a DynamoDB ValidationException — while the result was still stamped with
    # the requested as_of_date. #1917: an INCLUSIVE BETWEEN means a 7-day window
    # starts 6 days back; `days=7`/`days=30` summed 8/31 dates and then divided by
    # the literals 7 and 30, overstating the daily average that sets his calorie
    # target by ~14%.
    d30_start = (_end_dt - timedelta(days=29)).strftime("%Y-%m-%d")
    d7_start = (_end_dt - timedelta(days=6)).strftime("%Y-%m-%d")
    _d7_days = 7
    _d30_days = 30
    # `start_date` is declared in this tool's registry schema but the 7d/30d
    # averages are fixed-width by definition — honouring an arbitrary start would
    # make `exercise_kcal_7d_daily_avg` span something other than 7 days, which is
    # the exact dishonesty being fixed here. Say it is ignored instead of
    # silently dropping it.
    _ignored_start = args.get("start_date")
    profile = get_profile()

    height_in = profile.get("height_inches")
    if not height_in:
        # ADR-104: Mifflin-St Jeor is 6.25 kcal per cm of height. Assuming 70in
        # published a BMR, a TDEE and a calorie target he would eat to, all
        # derived from a guess, with nothing saying so.
        return {"error": "No height_inches in profile — BMR cannot be computed without it, and will not be estimated."}
    dob_str = profile.get("date_of_birth")
    sex = profile.get("biological_sex", "male").lower()
    target_deficit_kcal = args.get("target_deficit_kcal", 500)

    withings_recent = query_source("withings", d7_start, end_date)
    current_weight_lbs = None
    for item in sorted(withings_recent, key=lambda x: x.get("date", ""), reverse=True):
        if item.get("weight_lbs"):
            current_weight_lbs = float(item["weight_lbs"])
            current_weight_date = item["date"]
            break

    if current_weight_lbs is None:
        return {"error": "No recent weight data. Ensure Withings is syncing."}

    weight_kg = current_weight_lbs * 0.453592
    height_cm = height_in * 2.54
    age_years = None
    if dob_str:
        try:
            dob = datetime.strptime(dob_str, "%Y-%m-%d")
            # Both sides NAIVE. This was `datetime.now(timezone.utc) - dob`, an
            # aware-minus-naive subtraction that raised TypeError on EVERY call;
            # the bare `except Exception: pass` swallowed it, so the profile's real
            # date_of_birth could never reach the BMR and the hardcoded 35 always
            # won — dead code that looked live, worth ~5 kcal per year of error.
            age_years = (datetime.now(timezone.utc).replace(tzinfo=None) - dob).days / 365.25
        except Exception as _e:
            logger.warning(f"_get_energy_expenditure: could not parse date_of_birth {dob_str!r} — {_e}")
    age_basis = (
        "profile_date_of_birth" if age_years is not None else ("date_of_birth_unparseable" if dob_str else "no_date_of_birth_in_profile")
    )
    if age_years is None:
        age_years = 35  # assumed — surfaced as bmr_age_basis so it is never mistaken for a measured input

    if sex == "female":
        bmr = round(10 * weight_kg + 6.25 * height_cm - 5 * age_years - 161, 0)
    else:
        bmr = round(10 * weight_kg + 6.25 * height_cm - 5 * age_years + 5, 0)

    def exercise_kcal_from_strava(strava_items):
        """Returns (kcal, basis). The basis is published: until the strava writer
        rolled `total_kilojoules` up, `total_kj` was always 0 and EVERY TDEE this
        tool returned came from the duration proxy while the payload said nothing
        about which branch ran."""
        total_kj = sum(float(d.get("total_kilojoules") or 0) for d in strava_items)
        total_time = sum(float(d.get("total_moving_time_seconds") or 0) for d in strava_items)
        if total_kj <= 0:
            hours = total_time / 3600
            return round(6 * weight_kg * hours, 0), ("duration_proxy_6_kcal_per_kg_hour" if total_time > 0 else "no_activity_in_window")
        # Only power-equipped activities report kJ. Counting the day's kJ as the
        # WHOLE day's expenditure would drop a run that shared the day with a
        # ride, so the moving time NOT covered by a kJ reading still gets the
        # proxy. Rows written before the writer recorded that split carry no
        # covered-time field — for them, kJ is taken to cover the day (the old
        # behaviour) rather than double-counting.
        covered_s = sum(
            float(
                d.get("kilojoules_moving_time_seconds")
                if d.get("kilojoules_moving_time_seconds") is not None
                else (d.get("total_moving_time_seconds") or 0)
            )
            for d in strava_items
            if float(d.get("total_kilojoules") or 0) > 0
        )
        uncovered_hours = max(0.0, total_time - covered_s) / 3600
        # kJ of mechanical work ≈ kcal expended at ~25% gross efficiency.
        kcal = total_kj * 1.0 + 6 * weight_kg * uncovered_hours
        return round(kcal, 0), ("measured_kilojoules" if uncovered_hours <= 0 else "mixed_measured_kilojoules_and_duration_proxy")

    strava_7d = query_source("strava", d7_start, end_date)
    strava_30d = query_source("strava", d30_start, end_date)

    ex_kcal_7d, ex_basis_7d = exercise_kcal_from_strava(strava_7d)
    ex_kcal_30d, ex_basis_30d = exercise_kcal_from_strava(strava_30d)
    ex_daily_7d_avg = round(ex_kcal_7d / _d7_days, 0)
    ex_daily_30d_avg = round(ex_kcal_30d / _d30_days, 0)

    tdee_7d_avg = round(bmr + ex_daily_7d_avg, 0)
    tdee_30d_avg = round(bmr + ex_daily_30d_avg, 0)
    calorie_target_7d = round(tdee_7d_avg - target_deficit_kcal, 0)
    calorie_target_30d = round(tdee_30d_avg - target_deficit_kcal, 0)
    implied_weekly_loss_lbs = round(target_deficit_kcal * 7 / 3500, 2)

    journey_start_wt = profile.get("journey_start_weight_lbs")
    bmr_change = None
    if journey_start_wt:
        start_kg = float(journey_start_wt) * 0.453592
        if sex == "female":
            bmr_start = round(10 * start_kg + 6.25 * height_cm - 5 * age_years - 161, 0)
        else:
            bmr_start = round(10 * start_kg + 6.25 * height_cm - 5 * age_years + 5, 0)
        bmr_change = {
            "bmr_at_start_weight": bmr_start,
            "bmr_now": bmr,
            "bmr_reduction_kcal": round(bmr_start - bmr, 0),
            "note": "BMR decreases as you lose weight — this is normal metabolic adaptation. Deficit targets should be recalculated every 10 lbs lost.",
        }

    return {
        "as_of_date": end_date,
        "current_weight_lbs": current_weight_lbs,
        "current_weight_date": current_weight_date,
        "bmr_formula": "Mifflin-St Jeor",
        "bmr_kcal": bmr,
        "bmr_age_years": round(age_years, 1),
        "bmr_age_basis": age_basis,
        "window": {
            "d7_start": d7_start,
            "d7_days": _d7_days,
            "d30_start": d30_start,
            "d30_days": _d30_days,
            "end_date": end_date,
            "start_date_ignored": _ignored_start,
            "note": (
                "The 7d/30d averages are fixed-width windows anchored to end_date; an explicit start_date is "
                "reported here rather than applied, so the field names keep matching the spans."
                if _ignored_start
                else None
            ),
        },
        "exercise_kcal_7d_daily_avg": ex_daily_7d_avg,
        "exercise_kcal_30d_daily_avg": ex_daily_30d_avg,
        "exercise_energy_basis_7d": ex_basis_7d,
        "exercise_energy_basis_30d": ex_basis_30d,
        "tdee_7d_avg": tdee_7d_avg,
        "tdee_30d_avg": tdee_30d_avg,
        "target_deficit_kcal": target_deficit_kcal,
        "calorie_target_based_on_7d": calorie_target_7d,
        "calorie_target_based_on_30d": calorie_target_30d,
        "implied_weekly_loss_lbs": implied_weekly_loss_lbs,
        "bmr_change_since_start": bmr_change,
        "coaching_note": "Recalculate targets every 10 lbs lost as BMR decreases. Eating below 1200 kcal (women) or 1500 kcal (men) risks lean mass loss even with adequate protein.",
    }


def _get_hydration_score(args):
    """
    Hydration adequacy scoring: bodyweight-adjusted daily target,
    deficit alerts, rolling average, adequacy rate, and correlation
    with exercise intensity and journal energy scores.
    Source: apple_health (water_intake_ml). Bodyweight target: 35ml/kg (Webb).
    Fallback guidance: Habitify manual log if Apple Health sync is incomplete.
    """
    end = args.get("end_date", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    try:
        _end_dt = datetime.strptime(end, "%Y-%m-%d")
    except (ValueError, TypeError):
        return {"error": f"Could not parse end_date {end!r} — expected YYYY-MM-DD."}
    # Same class as the energy view: `start` defaulted to `now - 30` while `end`
    # came from args, so passing only end_date (a documented registry parameter)
    # produced an inverted BETWEEN that DynamoDB rejects. Hangs off end_date, and
    # 30 INCLUSIVE dates start 29 days back.
    start = args.get("start_date") or (_end_dt - timedelta(days=29)).strftime("%Y-%m-%d")
    target_ml_override = args.get("target_ml")

    # Pull water data from apple_health (SOT for water domain)
    water_items = query_source("apple_health", start, end)
    if not water_items:
        return {
            "error": "No Apple Health data found. Ensure the 9pm HAE automation is running.",
            "hint": "Water field: water_intake_ml in apple_health source.",
        }

    # Get weight for personalized target
    weight_kg = None
    try:
        wt_items = query_source("withings", (datetime.strptime(end, "%Y-%m-%d") - timedelta(days=14)).strftime("%Y-%m-%d"), end)
        if wt_items:
            wt_items.sort(key=lambda x: x.get("date", ""), reverse=True)
            weight_lbs = float(wt_items[0].get("weight_lbs") or 0)
            if weight_lbs > 0:
                weight_kg = round(weight_lbs * 0.453592, 1)
    except Exception:
        pass

    # Compute target: 35ml/kg (Webb's guidance), 2500ml floor, or override
    if target_ml_override:
        daily_target_ml = float(target_ml_override)
        target_basis = f"{int(daily_target_ml)}ml caller override"
    elif weight_kg:
        _bodyweight_ml = round(weight_kg * 35)
        daily_target_ml = max(2500, _bodyweight_ml)
        # The stated basis must multiply out to the target it claims to explain.
        # It was unconditionally "35ml/kg x {weight}kg" even when the 2500ml floor
        # was what actually set the number (120 lbs -> 54.4kg -> 1904ml, published
        # as the basis for a 2500ml target).
        target_basis = (
            f"35ml/kg x {weight_kg}kg = {_bodyweight_ml}ml, raised to the 2500ml minimum floor"
            if _bodyweight_ml < 2500
            else f"35ml/kg x {weight_kg}kg"
        )
    else:
        daily_target_ml = 3000  # reasonable default
        target_basis = "3000ml default"

    daily_target_oz = round(daily_target_ml / 29.5735, 1)

    # Pull exercise intensity for correlation
    strava_items = query_source("strava", start, end)
    exercise_by_date = {}
    for item in strava_items or []:
        d = item.get("date", "")
        item = decimal_to_float(item)
        acts = item.get("activities", [])
        if acts:
            total_min = sum(float(a.get("moving_time_seconds", 0)) / 60 for a in acts)
            hr_list = [float(a.get("average_heartrate") or 0) for a in acts if a.get("average_heartrate")]
            avg_hr = sum(hr_list) / len(hr_list) if hr_list else 0
            exercise_by_date[d] = {"total_min": round(total_min, 1), "avg_hr": round(avg_hr, 1)}

    # Build daily rows
    daily_rows = []
    deficit_days = []
    zero_data_days = 0
    water_vals = []

    for item in sorted(water_items, key=lambda x: x.get("date", "")):
        d = item.get("date", "")
        if not d:
            continue
        item = decimal_to_float(item)

        ml = float(item.get("water_intake_ml") or 0)
        oz = float(item.get("water_intake_oz") or (ml / 29.5735 if ml else 0))

        has_data = ml >= 500  # 500ml min = actual reading (same threshold as daily brief)
        if not has_data:
            zero_data_days += 1
            continue

        water_vals.append(ml)
        pct_target = round(ml / daily_target_ml * 100, 1)
        met_target = ml >= daily_target_ml * 0.9  # 90% counts as met
        score = min(100, round(pct_target))

        ex = exercise_by_date.get(d)
        row = {
            "date": d,
            "water_ml": round(ml, 0),
            "water_oz": round(oz, 1),
            "pct_target": pct_target,
            "met_target": met_target,
            "score": score,
            # ADR-104: a day with NO strava record is UNMEASURED, not zero minutes
            # of exercise. That fabricated 0 was then used to CLASSIFY the day
            # (`exercise_min <= 20` -> rest day), so every unmeasured day padded
            # the rest-day average the "you drink LESS on training days"
            # recommendation is computed against.
            "exercise_min": ex["total_min"] if ex else None,
            "exercise_avg_hr": ex["avg_hr"] if ex else None,
        }
        daily_rows.append(row)
        if not met_target:
            deficit_days.append(d)

    if not daily_rows:
        return {
            "error": "No valid water readings found (>= 500ml). Check the 9pm HAE automation.",
            "zero_data_days": zero_data_days,
            "hint": "If the 9pm HAE automation is not running, water data will not appear in the Daily Brief.",
        }

    n = len(daily_rows)
    avg_ml = round(sum(water_vals) / n, 0)
    avg_oz = round(avg_ml / 29.5735, 1)
    adequacy_rate = round((n - len(deficit_days)) / n * 100, 1)
    avg_score = round(sum(r["score"] for r in daily_rows) / n, 1)

    # Streak: current consecutive CALENDAR days at target, anchored to the window
    # end. daily_rows holds only days that cleared the 500ml floor — unlogged days
    # were `continue`d out — so walking it naively jumped calendar gaps (two
    # on-target days in April + two in May read as a 4-day streak across a 17-day
    # silence) and a streak that ended weeks ago was still called "current".
    streak = 0
    streak_note = None
    _prev_date = None
    for row in reversed(daily_rows):
        _row_dt = datetime.strptime(row["date"], "%Y-%m-%d")
        if _prev_date is None:
            # Anchor: the newest logged day must be the window end or the day before.
            if (_end_dt - _row_dt).days > 1:
                streak_note = (
                    f"No current streak: the most recent logged day is {row['date']}, {(_end_dt - _row_dt).days} days before {end}."
                )
                break
        elif (_prev_date - _row_dt).days != 1:
            break  # a calendar gap (unlogged day) ends the streak
        if not row["met_target"]:
            break
        streak += 1
        _prev_date = _row_dt

    # Correlation: exercise days vs rest days. Unmeasured days (exercise_min None)
    # belong to NEITHER side — counting them as rest days is what made the split
    # mostly unknowns.
    ex_days = [r for r in daily_rows if r["exercise_min"] is not None and r["exercise_min"] > 20]
    rest_days = [r for r in daily_rows if r["exercise_min"] is not None and r["exercise_min"] <= 20]
    unmeasured_exercise_days = sum(1 for r in daily_rows if r["exercise_min"] is None)
    ex_avg_ml = round(sum(r["water_ml"] for r in ex_days) / max(1, len(ex_days)), 0) if ex_days else None
    rest_avg_ml = round(sum(r["water_ml"] for r in rest_days) / max(1, len(rest_days)), 0) if rest_days else None

    # Recommendations
    recs = []
    if avg_ml < daily_target_ml * 0.8:
        gap = round((daily_target_ml - avg_ml) / 1000, 1)
        recs.append(
            f"Average intake ({int(avg_ml)}ml) is {int(100 - avg_ml/daily_target_ml*100)}% below target. "
            f"Add ~{gap}L/day — try one extra large glass at each meal."
        )
    if len(deficit_days) > n * 0.5:
        recs.append(
            f"Missing target on {len(deficit_days)}/{n} days ({int(len(deficit_days)/n*100)}%). " "Set a mid-day hydration check alarm."
        )
    if ex_avg_ml and rest_avg_ml and ex_avg_ml < rest_avg_ml:
        recs.append(
            f"Exercise days avg {int(ex_avg_ml)}ml vs rest days {int(rest_avg_ml)}ml — "
            "you are drinking LESS on training days. Add 500ml intra-workout."
        )
    if weight_kg:
        add_per_hr = round(weight_kg * 0.7)  # ~700ml/hr moderate exercise
        recs.append(
            f"At {weight_kg}kg, add ~{add_per_hr}ml for each hour of exercise " f"(above your {int(daily_target_ml)}ml base target)."
        )

    return {
        "period": {"start_date": start, "end_date": end, "days_with_data": n},
        "target": {
            "daily_target_ml": daily_target_ml,
            "daily_target_oz": daily_target_oz,
            "basis": target_basis,
            "weight_kg": weight_kg,
        },
        "summary": {
            "avg_ml": avg_ml,
            "avg_oz": avg_oz,
            "avg_score": avg_score,
            "adequacy_rate_pct": adequacy_rate,
            "deficit_days": len(deficit_days),
            "zero_data_days": zero_data_days,
            "current_streak_days": streak,
            "current_streak_note": streak_note,
        },
        "exercise_correlation": {
            "exercise_days_avg_ml": ex_avg_ml,
            "rest_days_avg_ml": rest_avg_ml,
            "n_exercise_days": len(ex_days),
            "n_rest_days": len(rest_days),
            "n_days_exercise_unmeasured": unmeasured_exercise_days,
            "note": (
                "Higher hydration on exercise days expected — flag if inverted. Days with no Strava record "
                "are excluded from both sides rather than counted as rest days."
            ),
        },
        "deficit_dates": deficit_days,
        "recommendations": recs,
        "daily_breakdown": daily_rows,
    }


def tool_get_daily_metrics(args):
    """Unified daily metrics dispatcher.
    movement_score lives in tools_lifestyle; energy_expenditure and hydration_score are local.
    """
    from mcp.tools_lifestyle import _get_movement_score

    VALID_VIEWS = {
        "movement": _get_movement_score,
        "energy": _get_energy_expenditure,
        "hydration": _get_hydration_score,
    }
    view = (args.get("view") or "movement").lower().strip()
    if view not in VALID_VIEWS:
        return {
            "error": f"Unknown view '{view}'.",
            "valid_views": list(VALID_VIEWS.keys()),
            "hint": "'movement' for NEAT/step score, 'energy' for calorie expenditure vs intake, 'hydration' for daily water intake adequacy.",
        }
    return VALID_VIEWS[view](args)


# R13-F09: Standard medical disclaimer injected into all health-assessment responses.
_HEALTH_DISCLAIMER = (
    "For personal health tracking only. Not medical advice. "
    "Consult a qualified healthcare provider before making health decisions based on this data."
)


# ── BS-MP1: Autonomic Balance Score ──────────────────────────────────────
