"""lambdas/web/site_api_physical.py — physical/body-composition endpoints (weekly_physical_summary, physical_overview).

Split out of site_api_observatory.py (#1654 slice 3 — god-module breakup). The
routed handler entrypoints stay in the site_api_observatory facade as thin
delegators; this module holds the logic. Handlers receive the facade's globals()
as `_g` and read the monkeypatched/injectable state (table / _query_source /
_experiment_date / EXPERIMENT_START) via `_g["<name>"]`. This module does NOT
import the facade — no import cycle. All other shared helpers come straight from
site_api_common (identical binding semantics to the pre-split facade).
"""

from datetime import datetime, timedelta, timezone

from boto3.dynamodb.conditions import Key
from phase_filter import with_phase_filter  # ADR-058

from web.site_api_common import (
    USER_PREFIX,
    _decimal_to_float,
    _ok,
    logger,
)

DEXA_RECHECK_DAYS = 90


def _physical_cadences() -> dict:
    """#1119 — measurement-cadence metadata for /data/physical/.

    The page's tier labels (the fluid daily block vs the checkpoint block's cadence)
    render from THIS block, sourced from real metadata — the withings entry in
    source_registry and the handler's own DEXA recheck interval — never hand-typed
    in the front-end.
    """
    from source_registry import SOURCE_REGISTRY  # shared module (bundled, #781)

    w = SOURCE_REGISTRY.get("withings", {})
    expected = w.get("expected_days")
    stale_days = int(w["stale_hours"] // 24) if w.get("stale_hours") else None
    return {
        "weight": {
            "kind": "fluid",
            "source": "withings",
            "expected_days_per_week": expected,
            "stale_days": stale_days,
            "label": f"weigh-ins — daily scale, ~{expected} days/wk expected" if expected else "weigh-ins — daily scale",
        },
        "dexa": {
            "kind": "checkpoint",
            "interval_days": DEXA_RECHECK_DAYS,
            "label": f"DEXA — re-scanned ~every {DEXA_RECHECK_DAYS} days",
        },
        "phenoage": {
            "kind": "checkpoint",
            "interval_days": None,
            "label": "PhenoAge — recomputed per blood draw",
        },
        "tape": {
            "kind": "checkpoint",
            "interval_days": None,
            "label": "tape — per session, no fixed cadence yet",
        },
    }


def weekly_physical_summary(*, _g) -> dict:
    """
    GET /api/weekly_physical_summary
    Returns: 7-day array with per-day modality breakdown (Strava + Garmin steps + breathwork).
    Cache: 3600s.
    """
    _query_source = _g["_query_source"]
    _experiment_date = _g["_experiment_date"]
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    d7 = _experiment_date(7)

    strava_items = _query_source("strava", d7, today)
    garmin_items = _query_source("garmin", d7, today)
    ah_items = _query_source("apple_health", d7, today)

    # Build per-day maps
    garmin_by_date = {(g.get("date") or g.get("sk", "").replace("DATE#", "")): g for g in garmin_items}
    ah_by_date = {(h.get("date") or h.get("sk", "").replace("DATE#", "")): h for h in ah_items}

    # Flatten Strava activities by day, dedup by activity ID
    from collections import defaultdict

    day_activities = defaultdict(list)
    _seen_activity_ids = set()
    for s in strava_items:
        d = s.get("date") or s.get("sk", "").replace("DATE#", "")[:10]
        acts = s.get("activities") or [s]
        for a in acts:
            # Dedup: skip if we've already seen this activity ID
            _aid = str(a.get("activity_id") or a.get("id") or a.get("strava_id") or "")
            if _aid and _aid in _seen_activity_ids:
                continue
            if _aid:
                _seen_activity_ids.add(_aid)
            sport = a.get("sport_type") or a.get("type") or "Other"
            dur = float(a.get("duration_minutes") or a.get("moving_time_minutes") or (a.get("moving_time_seconds") or 0) / 60 or 0)
            day_activities[d].append({"type": sport, "minutes": round(dur)})

    # Build 7-day array
    days = []
    for i in range(7):
        dt = datetime.now(timezone.utc) - timedelta(days=6 - i)
        d = dt.strftime("%Y-%m-%d")
        dow = dt.strftime("%a")
        garmin = garmin_by_date.get(d, {})
        ah = ah_by_date.get(d, {})
        activities = day_activities.get(d, [])
        total_active_min = sum(a["minutes"] for a in activities)
        bw_min = float(ah.get("breathwork_minutes") or 0)
        mm_min = float(ah.get("mindful_minutes") or 0)
        if mm_min > 0 and bw_min == 0:
            bw_min = mm_min
        if bw_min > 0:
            activities.append({"type": "Breathwork", "minutes": round(bw_min)})
            total_active_min += bw_min
        # Steps: Apple Health first; Garmin only if AH absent AND plausible (drops the
        # phantom ~298 Garmin record — same fix as handle_training_overview, #8).
        _ah_steps = int(float(ah["steps"])) if ah.get("steps") and float(ah["steps"]) > 0 else None
        _gm_steps = int(float(garmin["steps"])) if garmin.get("steps") and float(garmin["steps"]) >= 1000 else None
        days.append(
            {
                "date": d,
                "day_of_week": dow,
                "steps": _ah_steps if _ah_steps is not None else _gm_steps,
                "activities": activities,
                "total_active_minutes": round(total_active_min),
            }
        )

    return _ok({"days": days}, cache_seconds=3600)


def physical_overview(*, _g) -> dict:
    """
    GET /api/physical_overview
    Returns: Latest + baseline DEXA scans, tape measurements, delta computations.
    Source: dexa + measurements DynamoDB partitions.
    Cache: 3600s.
    """
    table = _g["table"]
    EXPERIMENT_START = _g["EXPERIMENT_START"]
    datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # ── 1. DEXA scans (all, sorted ascending) ──
    dexa_pk = f"{USER_PREFIX}dexa"
    # clinical archive — DEXA is date-independent (owner decision 2026-06-06)
    dexa_resp = table.query(
        **with_phase_filter(
            {
                "KeyConditionExpression": Key("pk").eq(dexa_pk),
                "ScanIndexForward": True,
            },
            include_pilot=True,
        )
    )
    dexa_items = _decimal_to_float(dexa_resp.get("Items", []))

    # Baseline = most recent scan on or before EXPERIMENT_START (the starting point)
    # Latest = most recent scan after EXPERIMENT_START (progress since Day 1)
    latest_dexa = None
    baseline_dexa = None
    if dexa_items:
        pre_experiment = [d for d in dexa_items if (d.get("scan_date") or "") <= EXPERIMENT_START]
        post_experiment = [d for d in dexa_items if (d.get("scan_date") or "") > EXPERIMENT_START]
        baseline_dexa = pre_experiment[-1] if pre_experiment else dexa_items[0]
        if post_experiment:
            latest_dexa = post_experiment[-1]
        else:
            # No post-experiment scan yet — show baseline as the current state
            latest_dexa = baseline_dexa
            baseline_dexa = None  # no comparison until a future scan exists

    def _dexa_summary(item):
        if not item:
            return None
        bc = item.get("body_composition", {})
        bs = item.get("body_score", {})
        bone = item.get("bone", {})
        idx = item.get("indices", {})
        s360 = item.get("score_360", {})
        seg_fat = item.get("segmental_fat", {})
        seg_lean = item.get("segmental_lean", {})
        item.get("limbs", {})
        targets = item.get("targets", {})
        changes = item.get("changes_vs_baseline", {})
        return {
            "scan_date": item.get("scan_date", ""),
            "body_composition": {
                "total_mass_lb": bc.get("total_mass_lb"),
                "body_fat_pct": bc.get("body_fat_pct"),
                "fat_mass_lb": bc.get("fat_mass_lb"),
                "lean_mass_lb": bc.get("lean_mass_lb"),
                "visceral_fat_lb": bc.get("visceral_fat_lb"),
                "visceral_fat_g": bc.get("visceral_fat_g"),
                "android_fat_pct": bc.get("android_fat_pct"),
                "gynoid_fat_pct": bc.get("gynoid_fat_pct"),
                "ag_ratio": bc.get("ag_ratio"),
            },
            "body_score": {
                "grade": bs.get("grade"),
                "numeric": bs.get("numeric"),
                "percentile": bs.get("percentile"),
            },
            "bone": {
                "t_score": bone.get("t_score"),
                "z_score": bone.get("z_score"),
            },
            "indices": (
                {
                    "almi_kg_m2": idx.get("almi_kg_m2"),
                    "ffmi_kg_m2": idx.get("ffmi_kg_m2"),
                    "fmi_kg_m2": idx.get("fmi_kg_m2"),
                    "almi_percentile": idx.get("almi_percentile"),
                    "ffmi_rating": idx.get("ffmi_rating"),
                    "fmi_rating": idx.get("fmi_rating"),
                }
                if idx
                else None
            ),
            "score_360": (
                {
                    "score": s360.get("score"),
                    # Privacy: biological_age is fine to publish, but chronological_age and
                    # biological_age_delta would let a reader back out Matt's true age — omit both.
                    "biological_age": s360.get("biological_age"),
                }
                if s360
                else None
            ),
            "segmental_fat": (
                {
                    "arms_pct": seg_fat.get("arms_pct"),
                    "trunk_pct": seg_fat.get("trunk_pct"),
                    "legs_pct": seg_fat.get("legs_pct"),
                }
                if seg_fat
                else None
            ),
            "segmental_lean": (
                {
                    "total_lb": seg_lean.get("total_lb"),
                    "arms_lb": seg_lean.get("arms_lb"),
                    "trunk_lb": seg_lean.get("trunk_lb"),
                    "legs_lb": seg_lean.get("legs_lb"),
                }
                if seg_lean
                else None
            ),
            "targets": targets if targets else None,
            "changes_vs_baseline": changes if changes else None,
        }

    # Days since latest DEXA
    days_since_dexa = None
    next_dexa_recommended = None
    if latest_dexa:
        try:
            scan_dt = datetime.strptime(latest_dexa.get("scan_date", ""), "%Y-%m-%d")
            days_since_dexa = (datetime.now(timezone.utc).replace(tzinfo=None) - scan_dt).days
            next_dt = scan_dt + timedelta(days=DEXA_RECHECK_DAYS)  # #1119: one constant with the cadence label
            next_dexa_recommended = next_dt.strftime("%Y-%m-%d")
        except Exception:
            pass

    # ── 2. Tape measurements (latest session) ──
    meas_pk = f"{USER_PREFIX}measurements"
    # ADR-058: tape measurements are progress-tracking — hide pilot records
    # (page shows an honest empty state until post-restart measurements exist)
    meas_resp = table.query(
        **with_phase_filter(
            {
                "KeyConditionExpression": Key("pk").eq(meas_pk),
                "ScanIndexForward": False,
                "Limit": 1,
            }
        )
    )
    meas_items = _decimal_to_float(meas_resp.get("Items", []))
    tape = None
    tape_session_count = 0
    if meas_items:
        m = meas_items[0]
        # Count total sessions
        count_resp = table.query(
            **with_phase_filter(
                {  # ADR-058: hide pilot measurements
                    "KeyConditionExpression": Key("pk").eq(meas_pk),
                    "Select": "COUNT",
                }
            )
        )
        tape_session_count = count_resp.get("Count", 1)

        # Build tape data from raw measurement fields
        raw = {}
        derived = {}
        for k, v in m.items():
            if k in ("pk", "sk", "ingested_at", "source_file", "unit", "measured_by", "date", "session_number"):
                continue
            if k in ("waist_height_ratio", "bilateral_symmetry_bicep_in", "bilateral_symmetry_thigh_in", "trunk_sum_in", "limb_avg_in"):
                derived[k] = v
            elif k.endswith("_in"):
                raw[k] = v

        tape = {
            "session_date": m.get("date", m.get("sk", "").replace("DATE#", "")),
            "session_number": m.get("session_number", 1),
            **raw,
            "derived": {
                **derived,
                "waist_height_ratio_target": 0.5,
            },
        }

    # ── 3. Blood pressure (from apple_health) ──
    bp_data = None
    try:
        ah_pk = f"{USER_PREFIX}apple_health"
        ah_resp = table.query(
            **with_phase_filter(
                {  # ADR-058: hide pilot BP records
                    "KeyConditionExpression": Key("pk").eq(ah_pk) & Key("sk").begins_with("DATE#"),
                    "FilterExpression": "attribute_exists(bp_systolic) OR attribute_exists(blood_pressure_systolic)",
                    "ScanIndexForward": False,
                    "Limit": 30,
                    "ProjectionExpression": (
                        "sk, bp_systolic, bp_diastolic, blood_pressure_systolic, " "blood_pressure_diastolic, blood_pressure_readings_count"
                    ),
                }
            )
        )
        bp_items = _decimal_to_float(ah_resp.get("Items", []))
        if bp_items:
            latest_bp = bp_items[0]
            sys_val = latest_bp.get("bp_systolic") or latest_bp.get("blood_pressure_systolic")
            dia_val = latest_bp.get("bp_diastolic") or latest_bp.get("blood_pressure_diastolic")
            bp_date = latest_bp.get("sk", "").replace("DATE#", "")
            # Status classification
            bp_status = "normal"
            if sys_val and float(sys_val) >= 140 or (dia_val and float(dia_val) >= 90):
                bp_status = "high"
            elif sys_val and float(sys_val) >= 130 or (dia_val and float(dia_val) >= 80):
                bp_status = "elevated"
            # Build trend
            bp_trend = []
            for bpi in bp_items:
                s = bpi.get("bp_systolic") or bpi.get("blood_pressure_systolic")
                d = bpi.get("bp_diastolic") or bpi.get("blood_pressure_diastolic")
                if s:
                    bp_trend.append(
                        {
                            "date": bpi.get("sk", "").replace("DATE#", ""),
                            "systolic": float(s),
                            "diastolic": float(d) if d else None,
                        }
                    )
            bp_data = {
                "systolic": float(sys_val) if sys_val else None,
                "diastolic": float(dia_val) if dia_val else None,
                "date": bp_date,
                "status": bp_status,
                "readings_count": len(bp_items),
                "trend": bp_trend[:14],
            }
    except Exception as _bp_e:
        logger.warning(f"BP query failed (non-fatal): {_bp_e}")

    return _ok(
        {
            "latest_dexa": _dexa_summary(latest_dexa),
            "baseline_dexa": _dexa_summary(baseline_dexa),
            "dexa_scan_count": len(dexa_items),
            "days_since_dexa": days_since_dexa,
            "next_dexa_recommended": next_dexa_recommended,
            "tape_measurements": tape,
            "tape_session_count": tape_session_count,
            "blood_pressure": bp_data,
            # #1119 — cadence metadata the page's tier labels render from (registry-sourced)
            "cadences": _physical_cadences(),
        },
        cache_seconds=3600,
    )
