"""
output_writers.py — S3 JSON output writers for the Daily Brief.

Extracted from daily_brief_lambda.py (Phase 3 monolith extraction).
Handles all three post-email side-effect writes: dashboard, clinical, buddy.
Also contains reward evaluation and protocol recommendation logic (pre-compute
for html_builder) and the demo-mode sanitizer.

Exports:
  init(...)                    — must call before using module
  write_dashboard_json(...)
  write_clinical_json(...)
  write_buddy_json(...)
  evaluate_rewards(...)        — pre-computes triggered rewards for html_builder
  get_protocol_recs(...)       — pre-computes protocol recs for html_builder
  sanitize_for_demo(...)
"""

import json
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal

# ==============================================================================
# MODULE STATE (set by init())
# ==============================================================================

_s3 = None
_table = None
_S3_BUCKET = None
_USER_ID = None
_USER_PREFIX = None
_fetch_range = None
_fetch_date = None
_normalize_whoop_sleep = None

# Derived constants (set by init)
_DASHBOARD_KEY = "dashboard/data.json"
_REWARDS_PK = None
_CS_CONFIG_KEY = "config/character_sheet.json"
_PILLAR_ORDER = ["sleep", "movement", "nutrition", "metabolic", "mind", "relationships", "consistency"]


def init(s3_client, table_client, bucket, user_id, user_prefix,
         fetch_range_fn, fetch_date_fn, normalize_whoop_fn):
    """Inject shared dependencies. Call once at Lambda startup."""
    global _s3, _table, _S3_BUCKET, _USER_ID, _USER_PREFIX
    global _fetch_range, _fetch_date, _normalize_whoop_sleep, _REWARDS_PK
    _s3 = s3_client
    _table = table_client
    _S3_BUCKET = bucket
    _USER_ID = user_id
    _USER_PREFIX = user_prefix
    _fetch_range = fetch_range_fn
    _fetch_date = fetch_date_fn
    _normalize_whoop_sleep = normalize_whoop_fn
    _REWARDS_PK = f"USER#{user_id}#SOURCE#rewards"


# ==============================================================================
# INLINE UTILITIES
# ==============================================================================

def _safe_float(rec, field, default=None):
    if rec and field in rec:
        try: return float(rec[field])
        except Exception: return default
    return default

def _d2f(obj):
    if isinstance(obj, list):    return [_d2f(i) for i in obj]
    if isinstance(obj, dict):    return {k: _d2f(v) for k, v in obj.items()}
    if isinstance(obj, Decimal): return float(obj)
    return obj

def _get_current_phase(profile, current_weight_lbs):
    phases = profile.get("weight_loss_phases", [])
    for p in phases:
        if current_weight_lbs >= p.get("end_lbs", 0):
            return p
    return phases[-1] if phases else None


# ==============================================================================
# AVATAR DATA BUILDER
# ==============================================================================

def _build_avatar_data(character_sheet, profile, current_weight=None):
    """Build avatar display state from character sheet + weight data."""
    if not character_sheet:
        return None

    tier = (character_sheet.get("character_tier") or "Foundation").lower().replace(" ", "_")
    pillar_names = _PILLAR_ORDER

    start_w = profile.get("journey_start_weight_lbs", 302)
    goal_w = profile.get("goal_weight_lbs", 185)
    cw = current_weight or start_w
    if start_w != goal_w:
        composition_score = max(0, min(100, ((start_w - cw) / (start_w - goal_w)) * 100))
    else:
        composition_score = 100
    if composition_score >= 75:
        body_frame = 3
    elif composition_score >= 36:
        body_frame = 2
    else:
        body_frame = 1

    badges = {}
    for pn in pillar_names:
        pd = character_sheet.get(f"pillar_{pn}", {})
        lvl = pd.get("level", 1) if pd else 1
        if lvl >= 61:
            badges[pn] = "bright"
        elif lvl >= 41:
            badges[pn] = "dim"
        else:
            badges[pn] = "hidden"

    raw_effects = character_sheet.get("active_effects", [])
    effect_names = [e.get("name", "").lower().replace(" ", "_") for e in raw_effects if e.get("name")]

    sleep_lvl = (character_sheet.get("pillar_sleep") or {}).get("level", 1)
    move_lvl = (character_sheet.get("pillar_movement") or {}).get("level", 1)
    meta_lvl = (character_sheet.get("pillar_metabolic") or {}).get("level", 1)
    cons_lvl = (character_sheet.get("pillar_consistency") or {}).get("level", 1)
    expressions = {
        "eyes": "bright" if sleep_lvl >= 61 else ("dim" if sleep_lvl < 35 else "normal"),
        "posture": "forward" if move_lvl >= 61 else "normal",
        "skin_tone": "warm" if meta_lvl >= 61 else ("cool" if meta_lvl < 35 else "normal"),
        "ground": "solid" if cons_lvl >= 61 else ("faded" if cons_lvl < 35 else "normal"),
    }

    char_lvl = character_sheet.get("character_level", 1)
    all_discipline = all(badges[p] != "hidden" for p in pillar_names)
    elite_crown = char_lvl >= 81
    alignment_ring = all_discipline and all(badges[p] == "bright" for p in pillar_names)

    return {
        "tier": tier,
        "body_frame": body_frame,
        "composition_score": round(composition_score, 1),
        "badges": badges,
        "effects": effect_names,
        "expressions": expressions,
        "elite_crown": elite_crown,
        "alignment_ring": alignment_ring,
    }


# ==============================================================================
# CHARACTER SHEET — REWARD EVALUATION & PROTOCOL RECS
# (pre-computed in lambda_handler and passed to html_builder as params)
# ==============================================================================

def evaluate_rewards(character_sheet):
    """Check all active rewards against current character sheet. Returns newly triggered rewards."""
    if not character_sheet:
        return []
    tier_order = ["Foundation", "Momentum", "Discipline", "Mastery", "Elite"]
    try:
        resp = _table.query(
            KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
            ExpressionAttributeValues={":pk": _REWARDS_PK, ":prefix": "REWARD#"},
        )
        items = resp.get("Items", [])
    except Exception as e:
        print("[WARN] evaluate_rewards query failed: " + str(e))
        return []

    triggered = []
    now = datetime.now(timezone.utc).isoformat()
    for item in items:
        if item.get("status") != "active":
            continue
        condition = _d2f(item.get("condition", {}))
        if isinstance(condition, str):
            try:
                condition = json.loads(condition)
            except Exception:
                continue
        met = False
        ctype = condition.get("type", "")
        if ctype == "character_level":
            met = character_sheet.get("character_level", 0) >= condition.get("level", 999)
        elif ctype == "character_tier":
            cur = character_sheet.get("character_tier", "Foundation")
            tgt = condition.get("tier", "Elite")
            met = (tier_order.index(cur) >= tier_order.index(tgt)
                   if cur in tier_order and tgt in tier_order else False)
        elif ctype == "pillar_level":
            p = condition.get("pillar", "")
            met = character_sheet.get("pillar_" + p, {}).get("level", 0) >= condition.get("level", 999)
        elif ctype == "pillar_tier":
            p = condition.get("pillar", "")
            cur = character_sheet.get("pillar_" + p, {}).get("tier", "Foundation")
            tgt = condition.get("tier", "Elite")
            met = (tier_order.index(cur) >= tier_order.index(tgt)
                   if cur in tier_order and tgt in tier_order else False)
        if met:
            try:
                _table.update_item(
                    Key={"pk": item["pk"], "sk": item["sk"]},
                    UpdateExpression="SET #s = :s, triggered_at = :t",
                    ExpressionAttributeNames={"#s": "status"},
                    ExpressionAttributeValues={":s": "triggered", ":t": now},
                )
                triggered.append({
                    "reward_id": str(item.get("reward_id", "")),
                    "title": str(_d2f(item.get("title", ""))),
                    "description": str(_d2f(item.get("description", ""))),
                    "condition": condition,
                })
            except Exception as e:
                print("[WARN] failed to update reward " + str(item.get("reward_id")) + ": " + str(e))
    return triggered


def get_protocol_recs(character_sheet):
    """Get protocol recommendations for struggling pillars from S3 config."""
    if not character_sheet:
        return []
    try:
        resp = _s3.get_object(Bucket=_S3_BUCKET, Key=_CS_CONFIG_KEY)
        config = json.loads(resp["Body"].read())
    except Exception as e:
        print("[WARN] protocol recs: config load failed: " + str(e))
        return []

    protocols_config = config.get("protocols", {})
    if not protocols_config:
        return []

    events = character_sheet.get("level_events", [])
    dropped = {ev.get("pillar", "") for ev in events if "down" in ev.get("type", "")}

    recs = []
    for pillar in _PILLAR_ORDER:
        pdata = character_sheet.get("pillar_" + pillar, {})
        level = pdata.get("level", 1)
        tier = pdata.get("tier", "Foundation")
        if (pillar in dropped or level < 41) and pillar in protocols_config:
            pillar_protos = protocols_config[pillar]
            if isinstance(pillar_protos, dict) and tier in pillar_protos:
                tier_recs = pillar_protos[tier]
                if tier_recs:
                    recs.append({
                        "pillar": pillar,
                        "tier": tier,
                        "level": level,
                        "dropped": pillar in dropped,
                        "protocols": tier_recs[:2],
                    })
    return recs


# ==============================================================================
# DEMO MODE SANITIZER
# ==============================================================================

def sanitize_for_demo(html, data, profile):
    """Apply demo mode sanitization using profile-driven rules."""
    rules = profile.get("demo_mode_rules", {})
    if not rules:
        return html

    # 1. Hide entire sections via comment markers
    for section in rules.get("hide_sections", []):
        pattern = r'<!-- S:' + re.escape(section) + r' -->.*?<!-- /S:' + re.escape(section) + r' -->'
        html = re.sub(pattern, '', html, flags=re.DOTALL)

    # 2. Replace specific data values with masked text
    rv = rules.get("replace_values", {})

    if "weight_lbs" in rv:
        mask = rv["weight_lbs"]
        for w in [data.get("latest_weight"), data.get("week_ago_weight")]:
            if w:
                for fmt in [str(round(float(w), 1)), str(round(float(w)))]:
                    html = html.replace(fmt, mask)
        for phase in profile.get("weight_loss_phases", []):
            for key in ["start_lbs", "end_lbs"]:
                v = phase.get(key)
                if v:
                    for fmt in [str(round(float(v), 1)), str(round(float(v)))]:
                        html = html.replace(fmt, mask)
        for key in ["goal_weight_lbs", "journey_start_weight_lbs"]:
            v = profile.get(key)
            if v:
                for fmt in [str(round(float(v), 1)), str(round(float(v)))]:
                    html = html.replace(fmt, mask)

    if "calories" in rv:
        mask = rv["calories"]
        mf = data.get("macrofactor") or {}
        cal = mf.get("total_calories_kcal")
        if cal:
            html = html.replace(str(round(float(cal))), mask)
        cal_target = profile.get("calorie_target")
        if cal_target:
            html = html.replace(str(round(float(cal_target))), mask)

    if "protein" in rv:
        mask = rv["protein"]
        mf = data.get("macrofactor") or {}
        prot = mf.get("total_protein_g")
        if prot:
            html = html.replace(str(round(float(prot))), mask)

    # 3. Redact text patterns (case-insensitive)
    for pat in rules.get("redact_patterns", []):
        html = re.sub(r'(?i)\b' + re.escape(pat) + r'(?:s|ed|ing)?\b', '[redacted]', html)

    # 4. Add demo banner
    demo_banner = ('<div style="background:#fef3c7;border:2px solid #f59e0b;border-radius:8px;'
                   'padding:8px 16px;margin:0 16px 8px;text-align:center;">'
                   '<p style="font-size:11px;color:#92400e;margin:0;font-weight:700;">'
                   '&#128274; DEMO VERSION — Some data redacted for privacy</p></div>')
    header_end = '</div></div>'
    idx = html.find(header_end)
    if idx > 0:
        insert_at = idx + len(header_end)
        html = html[:insert_at] + demo_banner + html[insert_at:]

    return html


# ==============================================================================
# DASHBOARD JSON WRITER
# ==============================================================================

def write_dashboard_json(data, profile, day_grade_score, grade, component_scores,
                          readiness_score, readiness_colour, tldr_guidance, yesterday,
                          component_details=None, character_sheet=None):
    """Write dashboard/data.json to S3 for the static web dashboard."""
    if component_details is None:
        component_details = {}
    try:
        today = datetime.now(timezone.utc).date()

        # Sparklines
        sleep_7d = [_normalize_whoop_sleep(i) for i in _fetch_range("whoop",
                               (today - timedelta(days=7)).isoformat(), yesterday)]
        sleep_sparkline = [_safe_float(d, "sleep_score") for d in sleep_7d]

        hrv_7d_recs = _fetch_range("whoop", (today - timedelta(days=7)).isoformat(), yesterday)
        hrv_sparkline = [_safe_float(d, "hrv") for d in hrv_7d_recs]

        withings_14d = _fetch_range("withings", (today - timedelta(days=14)).isoformat(), yesterday)
        weight_by_date = {}
        for w in withings_14d:
            d = w.get("sk", "").replace("DATE#", "")
            wt = _safe_float(w, "weight_lbs")
            if wt:
                weight_by_date[d] = wt
        weight_sparkline = []
        last_w = None
        for i in range(6, -1, -1):
            d = (today - timedelta(days=i + 1)).isoformat()
            if d in weight_by_date:
                last_w = weight_by_date[d]
            if last_w is not None:
                weight_sparkline.append(round(last_w, 1))

        apple_7d = data.get("apple_7d") or []
        glucose_sparkline = [_safe_float(d, "blood_glucose_avg") for d in apple_7d]

        # Readiness training recommendation
        training_rec = ""
        if readiness_colour == "green":
            training_rec = "Hard workout OK · Follow today's plan"
        elif readiness_colour == "yellow":
            training_rec = "Moderate effort · Zone 2 or easy strength"
        elif readiness_colour == "red":
            training_rec = "Active recovery only · Walk, yoga, stretch"

        tsb = data.get("tsb")
        if tsb is not None:
            if tsb < -20:
                training_rec = "Overreached · Deload recommended"
            elif tsb > 15:
                training_rec = "Fresh legs · Good day for a hard session"

        # Weight context
        latest_weight = data.get("latest_weight")
        week_ago_weight = data.get("week_ago_weight")
        weekly_delta = None
        if latest_weight and week_ago_weight:
            weekly_delta = round(latest_weight - week_ago_weight, 1)

        phase = _get_current_phase(profile, latest_weight) if latest_weight else None
        phase_name = phase.get("name", "") if phase else ""
        journey_start = profile.get("journey_start_weight_lbs", 302)
        goal_weight = profile.get("goal_weight_lbs", 185)
        journey_pct = None
        if latest_weight and journey_start and goal_weight:
            total_to_lose = journey_start - goal_weight
            lost = journey_start - latest_weight
            journey_pct = max(0, min(100, round(lost / total_to_lose * 100))) if total_to_lose > 0 else 0

        # Glucose
        apple = data.get("apple") or {}
        glucose_avg = _safe_float(apple, "blood_glucose_avg")
        glucose_tir = _safe_float(apple, "blood_glucose_time_in_range_pct")
        glucose_std = _safe_float(apple, "blood_glucose_std_dev")
        glucose_min = _safe_float(apple, "blood_glucose_min")

        # Sleep
        sleep = data.get("sleep") or {}
        sleep_score = _safe_float(sleep, "sleep_score")
        sleep_duration = _safe_float(sleep, "sleep_duration_hours")
        sleep_efficiency = _safe_float(sleep, "sleep_efficiency_pct")
        deep_pct = _safe_float(sleep, "deep_pct")
        rem_pct = _safe_float(sleep, "rem_pct")

        # Zone 2 this week
        zone2_min = None
        try:
            week_start = today - timedelta(days=today.weekday())
            strava_week = _fetch_range("strava", week_start.isoformat(), yesterday)
            max_hr = profile.get("max_heart_rate", 184)
            z2_lo = max_hr * 0.60
            z2_hi = max_hr * 0.70
            z2_total = 0.0
            for day_rec in strava_week:
                for act in (day_rec.get("activities") or []):
                    avg_hr = _safe_float(act, "average_heartrate")
                    dur_s = _safe_float(act, "moving_time_seconds") or 0
                    if avg_hr and z2_lo <= avg_hr <= z2_hi:
                        z2_total += dur_s / 60
            zone2_min = round(z2_total)
        except Exception:
            pass

        # Active sources count
        source_names = ["whoop", "sleep", "macrofactor", "habitify",
                        "apple", "strava", "garmin", "supplements_today", "weather_yesterday"]
        sources_active = sum(1 for s_name in source_names if data.get(s_name))
        if data.get("journal"):
            sources_active += 1

        dashboard = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "date": yesterday,
            "readiness": {
                "score": readiness_score,
                "color": readiness_colour,
                "label": {"green": "Go", "yellow": "Moderate",
                          "red": "Easy", "gray": "No Data"}.get(readiness_colour, "—"),
                "training_rec": training_rec,
            },
            "sleep": {
                "score": sleep_score,
                "duration_hrs": sleep_duration,
                "efficiency": sleep_efficiency,
                "deep_pct": deep_pct,
                "rem_pct": rem_pct,
                "sparkline": sleep_sparkline,
            },
            "hrv": {
                "value": _safe_float(data.get("whoop"), "hrv"),
                "avg_7d": data["hrv"].get("hrv_7d"),
                "avg_30d": data["hrv"].get("hrv_30d"),
                "sparkline": hrv_sparkline,
            },
            "weight": {
                "current": latest_weight,
                "weekly_delta": weekly_delta,
                "phase": phase_name,
                "journey_pct": journey_pct,
                "sparkline": weight_sparkline,
            },
            "glucose": {
                "avg": glucose_avg,
                "tir_pct": glucose_tir,
                "variability": glucose_std,
                "fasting_proxy": glucose_min,
                "sparkline": glucose_sparkline,
            },
            "tsb": tsb,
            "zone2_min": zone2_min,
            "day_grade": {
                "score": day_grade_score,
                "letter": grade if grade != "—" else None,
                "components": {
                    "sleep": component_scores.get("sleep_quality"),
                    "recovery": component_scores.get("recovery"),
                    "nutrition": component_scores.get("nutrition"),
                    "movement": component_scores.get("movement"),
                    "habits": component_scores.get("habits_mvp"),
                    "habits_tier0": (component_details.get("habits_mvp", {}).get("tier0", {}).get("done")),
                    "habits_tier1": (component_details.get("habits_mvp", {}).get("tier1", {}).get("done")),
                    "hydration": component_scores.get("hydration"),
                    "journal": component_scores.get("journal"),
                    "glucose": component_scores.get("glucose"),
                },
                "tldr": (tldr_guidance or {}).get("tldr", ""),
            },
            "sources_active": sources_active,
            "character_sheet": {
                "level": character_sheet.get("character_level", 1) if character_sheet else None,
                "tier": character_sheet.get("character_tier") if character_sheet else None,
                "tier_emoji": character_sheet.get("character_tier_emoji") if character_sheet else None,
                "xp": character_sheet.get("character_xp", 0) if character_sheet else None,
                "pillars": {pn: {
                    "level": (character_sheet.get("pillar_" + pn) or {}).get("level"),
                    "tier": (character_sheet.get("pillar_" + pn) or {}).get("tier"),
                    "raw_score": (character_sheet.get("pillar_" + pn) or {}).get("raw_score")}
                    for pn in _PILLAR_ORDER}
                if character_sheet else {},
                "events": character_sheet.get("level_events", []) if character_sheet else [],
                "effects": [{"name": e.get("name"), "emoji": e.get("emoji")}
                            for e in character_sheet.get("active_effects", [])] if character_sheet else [],
            } if character_sheet else None,
            "avatar": _build_avatar_data(character_sheet, profile,
                                         data.get("avatar_weight") or data.get("latest_weight")),
        }

        _s3.put_object(
            Bucket=_S3_BUCKET,
            Key=_DASHBOARD_KEY,
            Body=json.dumps(dashboard, default=str),
            ContentType="application/json",
            CacheControl="max-age=300",
        )
        print("[INFO] Dashboard JSON written to s3://" + _S3_BUCKET + "/" + _DASHBOARD_KEY)

    except Exception as e:
        print("[WARN] Dashboard JSON write failed: " + str(e))


# ==============================================================================
# CLINICAL JSON WRITER
# ==============================================================================

def write_clinical_json(data, profile, yesterday):
    """Write dashboard/clinical.json to S3 for the clinical summary view."""
    try:
        today = datetime.now(timezone.utc).date()

        # Vitals: 30-day averages
        whoop_30d = _fetch_range("whoop", (today - timedelta(days=30)).isoformat(), yesterday)
        rhr_vals = [v for v in (_safe_float(r, "resting_heart_rate") for r in whoop_30d) if v is not None]
        hrv_vals = [v for v in (_safe_float(r, "hrv") for r in whoop_30d) if v is not None]

        withings_30d = _fetch_range("withings", (today - timedelta(days=30)).isoformat(), yesterday)
        weight_current = None
        weight_30d_ago = None
        for w in reversed(withings_30d):
            wt = _safe_float(w, "weight_lbs")
            if wt and weight_current is None:
                weight_current = wt
        for w in withings_30d:
            wt = _safe_float(w, "weight_lbs")
            if wt:
                weight_30d_ago = wt
                break
        weight_30d_delta = None
        if weight_current and weight_30d_ago:
            weight_30d_delta = round(weight_current - weight_30d_ago, 1)

        vitals = {
            "weight_current": weight_current,
            "weight_30d_delta": weight_30d_delta,
            "rhr_avg": round(sum(rhr_vals) / len(rhr_vals)) if rhr_vals else None,
            "hrv_avg": round(sum(hrv_vals) / len(hrv_vals)) if hrv_vals else None,
            "bp_systolic": None,
            "bp_diastolic": None,
        }

        # Body Composition (DEXA)
        body_comp = {}
        try:
            resp = _table.query(
                KeyConditionExpression="pk = :pk AND begins_with(sk, :sk)",
                ExpressionAttributeValues={":pk": _USER_PREFIX + "dexa", ":sk": "DATE#"},
                ScanIndexForward=False, Limit=1
            )
            if resp.get("Items"):
                dexa = resp["Items"][0]
                bc = dexa.get("body_composition", {})
                bd = dexa.get("bone_density", {})
                body_comp = {
                    "scan_date": dexa.get("scan_date"),
                    "body_fat_pct": _d2f(bc.get("body_fat_pct")),
                    "ffmi": _d2f(dexa.get("interpretations", {}).get("ffmi")),
                    "lean_mass_lbs": _d2f(bc.get("lean_mass_lbs")),
                    "fat_mass_lbs": _d2f(bc.get("fat_mass_lbs")),
                    "visceral_fat_area": _d2f(bc.get("visceral_fat_g")),
                    "bmd": _d2f(bd.get("t_score")),
                }
        except Exception as e:
            print("[WARN] Clinical: DEXA query failed: " + str(e))

        # Lab Results
        labs = {}
        try:
            resp = _table.query(
                KeyConditionExpression="pk = :pk AND begins_with(sk, :sk)",
                ExpressionAttributeValues={":pk": _USER_PREFIX + "labs", ":sk": "DATE#"},
                ScanIndexForward=False, Limit=1
            )
            all_draws = _table.query(
                KeyConditionExpression="pk = :pk AND begins_with(sk, :sk)",
                ExpressionAttributeValues={":pk": _USER_PREFIX + "labs", ":sk": "DATE#"},
                Select="COUNT"
            )
            total_draws = all_draws.get("Count", 0)

            if resp.get("Items"):
                lab_rec = resp["Items"][0]
                biomarkers_raw = lab_rec.get("biomarkers", {})
                out_of_range = lab_rec.get("out_of_range", [])

                cat_order = [
                    "lipids", "lipids_advanced", "cardiovascular", "metabolic",
                    "cbc", "cbc_differential", "liver", "kidney", "thyroid",
                    "hormones", "inflammation", "iron", "vitamins", "minerals",
                    "electrolytes", "immune", "omega_fatty_acids", "prostate",
                    "toxicology", "genetics", "blood_type", "digestive"
                ]
                cat_names = {
                    "lipids": "Lipids", "lipids_advanced": "Advanced Lipids",
                    "cardiovascular": "Cardiovascular", "metabolic": "Metabolic",
                    "cbc": "Complete Blood Count", "cbc_differential": "CBC Differential",
                    "liver": "Liver", "kidney": "Kidney", "thyroid": "Thyroid",
                    "hormones": "Hormones", "inflammation": "Inflammation",
                    "iron": "Iron Studies", "vitamins": "Vitamins", "minerals": "Minerals",
                    "electrolytes": "Electrolytes", "immune": "Immune",
                    "omega_fatty_acids": "Omega Fatty Acids", "prostate": "Prostate",
                    "toxicology": "Toxicology", "genetics": "Genetics",
                    "blood_type": "Blood Type", "digestive": "Digestive"
                }

                by_cat = {}
                for key, bm in biomarkers_raw.items():
                    cat = bm.get("category", "other")
                    if cat not in by_cat:
                        by_cat[cat] = []
                    flag = bm.get("flag", "normal")
                    flag_code = None
                    if flag == "high":
                        flag_code = "H"
                    elif flag == "low":
                        flag_code = "L"

                    val = bm.get("value_numeric")
                    if val is None:
                        val = bm.get("value")
                    decimals = 0
                    if isinstance(val, (int, float)):
                        if val != 0 and abs(val) < 1:
                            decimals = 2
                        elif abs(val) < 10:
                            decimals = 1

                    by_cat[cat].append({
                        "name": key.replace("_", " ").title(),
                        "value": _d2f(val) if isinstance(val, (int, float)) else val,
                        "unit": bm.get("unit", ""),
                        "range": bm.get("ref_text", ""),
                        "flag": flag_code,
                        "decimals": decimals,
                        "category": cat_names.get(cat, cat.replace("_", " ").title()),
                    })

                biomarker_list = []
                for cat in cat_order:
                    if cat in by_cat:
                        biomarker_list.extend(sorted(by_cat[cat], key=lambda x: x["name"]))
                for cat in sorted(by_cat.keys()):
                    if cat not in cat_order:
                        biomarker_list.extend(sorted(by_cat[cat], key=lambda x: x["name"]))

                labs = {
                    "latest_draw_date": lab_rec.get("draw_date"),
                    "lab_provider": lab_rec.get("lab_provider"),
                    "total_draws": total_draws,
                    "biomarkers": biomarker_list,
                    "flagged_count": len(out_of_range),
                }
        except Exception as e:
            print("[WARN] Clinical: labs query failed: " + str(e))

        # Supplements
        supplements = []
        try:
            supp_7d = _fetch_range("supplements", (today - timedelta(days=7)).isoformat(), yesterday)
            seen = {}
            for day_rec in supp_7d:
                for s_item in (day_rec.get("supplements") or []):
                    name = s_item.get("name", "").strip()
                    if name and name.lower() not in seen:
                        dose_str = ""
                        if s_item.get("dose") and s_item.get("unit"):
                            dose_str = str(s_item["dose"]) + " " + str(s_item["unit"])
                        elif s_item.get("dose"):
                            dose_str = str(s_item["dose"])
                        seen[name.lower()] = {
                            "name": name,
                            "dose": dose_str,
                            "timing": s_item.get("timing", ""),
                        }
            supplements = sorted(seen.values(), key=lambda x: x["name"])
        except Exception as e:
            print("[WARN] Clinical: supplements query failed: " + str(e))

        # Sleep 30-day averages
        sleep_30d = [_normalize_whoop_sleep(i) for i in _fetch_range(
            "whoop", (today - timedelta(days=30)).isoformat(), yesterday)]
        s_scores = [v for v in (_safe_float(r, "sleep_score") for r in sleep_30d) if v is not None]
        s_dur = [v for v in (_safe_float(r, "sleep_duration_hours") for r in sleep_30d) if v is not None]
        s_eff = [v for v in (_safe_float(r, "sleep_efficiency_pct") for r in sleep_30d) if v is not None]
        s_deep = [v for v in (_safe_float(r, "deep_pct") for r in sleep_30d) if v is not None]
        s_rem = [v for v in (_safe_float(r, "rem_pct") for r in sleep_30d) if v is not None]

        sleep_summary = {
            "avg_score": round(sum(s_scores) / len(s_scores)) if s_scores else None,
            "avg_duration_hrs": round(sum(s_dur) / len(s_dur), 1) if s_dur else None,
            "avg_efficiency": round(sum(s_eff) / len(s_eff)) if s_eff else None,
            "avg_deep_pct": round(sum(s_deep) / len(s_deep)) if s_deep else None,
            "avg_rem_pct": round(sum(s_rem) / len(s_rem)) if s_rem else None,
            "avg_bedtime": None,
            "avg_wake": None,
        }

        # Activity: weekly averages (last 4 weeks)
        strava_28d = _fetch_range("strava", (today - timedelta(days=28)).isoformat(), yesterday)
        apple_28d = _fetch_range("apple_health", (today - timedelta(days=28)).isoformat(), yesterday)

        max_hr = profile.get("max_heart_rate", 184)
        z2_lo = max_hr * 0.60
        z2_hi = max_hr * 0.70
        total_sessions = 0
        total_z2_min = 0.0
        sport_counts = {}
        for day_rec in strava_28d:
            for act in (day_rec.get("activities") or []):
                total_sessions += 1
                sport = act.get("sport_type", "Unknown")
                sport_counts[sport] = sport_counts.get(sport, 0) + 1
                avg_hr_v = _safe_float(act, "average_heartrate")
                dur_s = _safe_float(act, "moving_time_seconds") or 0
                if avg_hr_v and z2_lo <= avg_hr_v <= z2_hi:
                    total_z2_min += dur_s / 60

        step_vals = [v for v in (_safe_float(r, "steps") for r in apple_28d) if v is not None]
        top_sports = sorted(sport_counts.items(), key=lambda x: -x[1])[:3]
        primary_types = [sp[0] for sp in top_sports]

        weeks = 4.0
        activity_summary = {
            "avg_sessions_week": round(total_sessions / weeks, 1) if total_sessions else 0,
            "avg_zone2_min": round(total_z2_min / weeks) if total_z2_min else 0,
            "avg_daily_steps": round(sum(step_vals) / len(step_vals)) if step_vals else None,
            "primary_types": primary_types,
            "ctl": None,
            "tsb": data.get("tsb"),
        }

        # Glucose / Metabolic
        apple_30d = _fetch_range("apple_health", (today - timedelta(days=30)).isoformat(), yesterday)
        gl_avgs = [v for v in (_safe_float(r, "blood_glucose_avg") for r in apple_30d) if v is not None]
        gl_tir = [v for v in (_safe_float(r, "blood_glucose_time_in_range_pct") for r in apple_30d) if v is not None]
        gl_sd = [v for v in (_safe_float(r, "blood_glucose_std_dev") for r in apple_30d) if v is not None]
        gl_min = [v for v in (_safe_float(r, "blood_glucose_min") for r in apple_30d) if v is not None]

        glucose_summary = {
            "mean": round(sum(gl_avgs) / len(gl_avgs)) if gl_avgs else None,
            "tir_pct": round(sum(gl_tir) / len(gl_tir)) if gl_tir else None,
            "variability_sd": round(sum(gl_sd) / len(gl_sd), 1) if gl_sd else None,
            "fasting_proxy": round(sum(gl_min) / len(gl_min)) if gl_min else None,
        }

        # Genome flags
        genome_flags = []
        try:
            resp = _table.query(
                KeyConditionExpression="pk = :pk AND begins_with(sk, :sk)",
                ExpressionAttributeValues={":pk": _USER_PREFIX + "genome", ":sk": "GENE#"}
            )
            for item in (resp.get("Items") or []):
                risk = item.get("risk_level", "")
                if risk in ("unfavorable", "mixed"):
                    genome_flags.append({
                        "gene": item.get("gene", ""),
                        "variant": item.get("genotype", ""),
                        "risk": risk,
                        "note": item.get("summary", ""),
                    })
            genome_flags.sort(key=lambda x: (0 if x["risk"] == "unfavorable" else 1, x["gene"]))
        except Exception as e:
            print("[WARN] Clinical: genome query failed: " + str(e))

        # Active sources count
        sources_active = 0
        for s_name in ["whoop", "sleep", "macrofactor", "habitify", "apple", "strava",
                        "garmin", "supplements_today", "weather_yesterday"]:
            if data.get(s_name):
                sources_active += 1
        if data.get("journal"):
            sources_active += 1

        clinical = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "report_date": yesterday,
            "report_period": "30 days ending " + yesterday,
            "patient_name": profile.get("name", "Matthew Walker"),
            "sources_active": sources_active,
            "vitals": vitals,
            "body_comp": body_comp,
            "labs": labs,
            "supplements": supplements,
            "sleep_30d": sleep_summary,
            "activity": activity_summary,
            "glucose": glucose_summary,
            "genome_flags": genome_flags,
        }

        _s3.put_object(
            Bucket=_S3_BUCKET,
            Key="dashboard/clinical.json",
            Body=json.dumps(clinical, default=str),
            ContentType="application/json",
            CacheControl="max-age=300",
        )
        print("[INFO] Clinical JSON written to s3://" + _S3_BUCKET + "/dashboard/clinical.json")

    except Exception as e:
        print("[WARN] Clinical JSON write failed: " + str(e))


# ==============================================================================
# BUDDY JSON WRITER
# ==============================================================================

_BUDDY_LOOKBACK_DAYS = 7


def _buddy_days_since(date_str, ref_date):
    """Days between a YYYY-MM-DD string and a date object."""
    if not date_str:
        return 99
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").date() if isinstance(date_str, str) else date_str
        return (ref_date - d).days
    except Exception:
        return 99


def _buddy_friendly_date(date_str):
    """Convert YYYY-MM-DD to 'Mon Feb 27' style."""
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d")
        return d.strftime("%a %b %-d")
    except Exception:
        return date_str or ""


def _buddy_friendly_name(name, sport_type):
    """Make activity names more readable."""
    friendly = {
        "Walk": "Walk", "Run": "Run", "Ride": "Bike Ride",
        "VirtualRide": "Indoor Ride", "WeightTraining": "Weight Training",
        "Hike": "Hike", "Yoga": "Yoga", "Swim": "Swim",
    }
    if name == sport_type or not name:
        return friendly.get(sport_type, sport_type)
    return name


def _dedup_activities(activities):
    """Remove duplicate activities from multi-device recording (WHOOP + Garmin)."""
    if len(activities) <= 1:
        return activities

    def parse_start(a):
        try:
            return datetime.strptime(a.get("start_date", "")[:19], "%Y-%m-%dT%H:%M:%S")
        except Exception:
            return None

    def device_priority(a):
        dev = (a.get("device_name") or "").lower()
        if "garmin" in dev: return 3
        if "apple" in dev: return 2
        if "whoop" in dev: return 1
        return 0

    sorted_acts = sorted(activities, key=lambda a: a.get("start_date", ""))
    keep = []
    skip_ids = set()

    for i, a in enumerate(sorted_acts):
        aid = a.get("strava_id", str(i))
        if aid in skip_ids:
            continue
        start_a = parse_start(a)
        dur_a = float(a.get("moving_time_seconds") or 0)
        for j in range(i + 1, len(sorted_acts)):
            b = sorted_acts[j]
            bid = b.get("strava_id", str(j))
            if bid in skip_ids:
                continue
            start_b = parse_start(b)
            dur_b = float(b.get("moving_time_seconds") or 0)
            if not start_a or not start_b:
                continue
            gap = abs((start_b - start_a).total_seconds())
            if gap > 900:
                break
            if dur_a > 0 and dur_b > 0:
                ratio = min(dur_a, dur_b) / max(dur_a, dur_b)
                if ratio < 0.6:
                    continue
            if device_priority(a) >= device_priority(b):
                skip_ids.add(bid)
            else:
                skip_ids.add(aid)
                break
        if aid not in skip_ids:
            keep.append(a)

    return keep


def write_buddy_json(data, profile, yesterday, character_sheet=None):
    """Generate buddy/data.json for accountability partner page."""
    try:
        today_dt = datetime.now(timezone.utc).date()
        lookback_start = (today_dt - timedelta(days=_BUDDY_LOOKBACK_DAYS)).isoformat()
        lookback_end = today_dt.isoformat()

        mf_days = _fetch_range("macrofactor", lookback_start, lookback_end)
        strava_days = _fetch_range("strava", lookback_start, lookback_end)
        habit_days = _fetch_range("habitify", lookback_start, lookback_end)
        weight_days = _fetch_range("withings", lookback_start, lookback_end)

        # Food Logging Signal
        mf_logged_dates = set()
        latest_mf_date = None
        total_cals = []
        total_protein = []
        for item in mf_days:
            date_str = (item.get("sk") or "").replace("DATE#", "")
            cals = _safe_float(item, "total_calories_kcal") or _safe_float(item, "calories") or _safe_float(item, "energy_kcal")
            prot = _safe_float(item, "total_protein_g") or _safe_float(item, "protein_g") or _safe_float(item, "protein")
            if cals and cals > 200:
                mf_logged_dates.add(date_str)
                total_cals.append(cals)
                if prot:
                    total_protein.append(prot)
                if not latest_mf_date or date_str > latest_mf_date:
                    latest_mf_date = date_str

        days_since_food = _buddy_days_since(latest_mf_date, today_dt)
        food_logged_count = len(mf_logged_dates)
        if days_since_food <= 1 and food_logged_count >= 5:
            food_status = "green"
            food_text = f"Consistent — logged meals {food_logged_count} of last {_BUDDY_LOOKBACK_DAYS} days"
        elif days_since_food <= 2 and food_logged_count >= 3:
            food_status = "green"
            food_text = f"Logging food — {food_logged_count} of last {_BUDDY_LOOKBACK_DAYS} days tracked"
        elif days_since_food <= 3:
            food_status = "yellow"
            food_text = f"Last food log was {days_since_food} days ago"
        else:
            food_status = "red"
            food_text = f"No food logged in {days_since_food} days — might be off track"

        food_snapshot = ""
        if total_cals:
            avg_cals = int(sum(total_cals) / len(total_cals))
            if total_protein:
                avg_prot = int(sum(total_protein) / len(total_protein))
                food_snapshot = f"Averaging about {avg_cals:,} calories per day this week with {avg_prot}g protein."
            else:
                food_snapshot = f"Averaging about {avg_cals:,} calories per day this week."

        # Exercise Signal
        monday = today_dt - timedelta(days=today_dt.weekday())
        monday_str = monday.isoformat()
        day_of_week = today_dt.strftime("%A")

        activities = []
        week_activities = []
        latest_activity_date = None
        for item in strava_days:
            date_str = (item.get("sk") or "").replace("DATE#", "")
            raw_acts = item.get("activities", [])
            acts = _dedup_activities(raw_acts) if isinstance(raw_acts, list) else []
            if isinstance(acts, list):
                for a in acts:
                    sport = a.get("sport_type") or a.get("type", "Activity")
                    name = a.get("name", sport)
                    dist = _safe_float(a, "distance_miles")
                    moving_sec = _safe_float(a, "moving_time_seconds")
                    dur_min = int(moving_sec / 60) if moving_sec else None
                    detail_parts = []
                    if dist and dist > 0.1:
                        detail_parts.append(f"{dist:.1f} mi")
                    if dur_min:
                        detail_parts.append(f"{dur_min} min")
                    entry = {
                        "name": _buddy_friendly_name(name, sport),
                        "detail": ", ".join(detail_parts) if detail_parts else sport,
                        "date": _buddy_friendly_date(date_str),
                        "sort_date": date_str,
                    }
                    activities.append(entry)
                    if date_str >= monday_str:
                        week_activities.append(entry)
                    if not latest_activity_date or date_str > latest_activity_date:
                        latest_activity_date = date_str

        week_count = len(week_activities)
        days_since_exercise = _buddy_days_since(latest_activity_date, today_dt)
        days_into_week = today_dt.weekday() + 1

        if week_count >= 3:
            exercise_status = "green"
            exercise_text = f"Active — {week_count} sessions this week"
        elif week_count >= 1 and days_since_exercise <= 2:
            exercise_status = "green"
            exercise_text = f"{week_count} session{'s' if week_count != 1 else ''} so far this week"
        elif week_count >= 1:
            exercise_status = "yellow"
            exercise_text = f"{week_count} session{'s' if week_count != 1 else ''} this week, last was {days_since_exercise} days ago"
        elif days_into_week <= 2:
            exercise_status = "yellow"
            exercise_text = f"No sessions yet this week ({day_of_week})"
        else:
            exercise_status = "red"
            exercise_text = f"No exercise this week — last session {days_since_exercise} days ago"

        activities.sort(key=lambda x: x.get("sort_date", ""), reverse=True)
        activity_highlights = [
            {"name": a["name"], "detail": a["detail"], "date": a["date"]}
            for a in activities[:4]
        ]

        # Routine Signal
        latest_habit_date = None
        habit_logged_count = 0
        for item in habit_days:
            date_str = (item.get("sk") or "").replace("DATE#", "")
            completed = _safe_float(item, "completed_count") or _safe_float(item, "total_completed")
            if completed and completed > 0:
                habit_logged_count += 1
                if not latest_habit_date or date_str > latest_habit_date:
                    latest_habit_date = date_str

        days_since_habits = _buddy_days_since(latest_habit_date, today_dt)
        if days_since_habits <= 1 and habit_logged_count >= 4:
            routine_status = "green"
            routine_text = "In his routine — habits tracked consistently"
        elif days_since_habits <= 2:
            routine_status = "green"
            routine_text = "Routine is holding, habits being logged"
        elif days_since_habits <= 3:
            routine_status = "yellow"
            routine_text = f"Habit tracking quiet for {days_since_habits} days"
        else:
            routine_status = "red"
            routine_text = f"No habit data in {days_since_habits} days — routine may have slipped"

        # Weight Signal
        weights = []
        for item in weight_days:
            date_str = (item.get("sk") or "").replace("DATE#", "")
            w = _safe_float(item, "weight_lbs")
            if w and w > 100:
                weights.append((date_str, w))
        weights.sort(key=lambda x: x[0])
        latest_weight_date = weights[-1][0] if weights else None
        days_since_weigh = _buddy_days_since(latest_weight_date, today_dt)

        if len(weights) >= 2:
            delta = weights[-1][1] - weights[0][1]
            if delta < -0.5:
                weight_status = "green"
                weight_text = "Heading in the right direction"
            elif delta < 0.5:
                weight_status = "green"
                weight_text = "Weight holding steady"
            else:
                weight_status = "yellow"
                weight_text = "Weight ticked up slightly this week"
        elif len(weights) == 1:
            weight_status = "green" if days_since_weigh <= 3 else "yellow"
            weight_text = "Weighed in" + (f" {days_since_weigh} days ago" if days_since_weigh > 1 else " recently")
        else:
            weight_status = "yellow" if days_since_weigh <= 7 else "red"
            weight_text = f"No weigh-in in {days_since_weigh}+ days"

        # Beacon
        statuses = [food_status, exercise_status, routine_status, weight_status]
        red_count = statuses.count("red")
        yellow_count = statuses.count("yellow")
        if red_count >= 2:
            beacon = "red"
            beacon_label = "Check in on him"
            beacon_summary = "Multiple signals have gone quiet. He might be in a rough stretch."
            prompt = "Time to reach out. Don't make it about health data — just ask how he's really doing. Be direct but kind."
        elif red_count >= 1 or yellow_count >= 2:
            beacon = "yellow"
            beacon_label = "Might be a quiet stretch"
            beacon_summary = "A couple of things have dropped off. Probably fine, but worth a nudge."
            prompt = "A casual check-in would be good. Don't lead with the health stuff — just ask how his week's going."
        else:
            beacon = "green"
            beacon_label = "Matt's doing his thing"
            beacon_summary = "He's logging food, exercising, and sticking to his routine. All good."
            prompt = "No action needed. If you reach out, just be a mate — talk about life, not health."

        # Journey Stats
        journey_start = profile.get("journey_start_date", "2026-02-22")
        goal_weight = _safe_float(profile, "goal_weight_lbs") or 185
        start_weight = _safe_float(profile, "start_weight_lbs") or 302
        try:
            journey_days = (today_dt - datetime.strptime(journey_start, "%Y-%m-%d").date()).days
        except Exception:
            journey_days = 0
        current_weight = weights[-1][1] if weights else (data.get("avatar_weight") or start_weight)
        lost_lbs = round(start_weight - current_weight, 1)
        total_to_lose = start_weight - goal_weight
        pct_complete = round((lost_lbs / total_to_lose) * 100, 0) if total_to_lose > 0 else 0

        # Friendly timestamp
        try:
            now_pt = datetime.now(timezone.utc) - timedelta(hours=8)
            day_name = now_pt.strftime("%A")
            tod = "morning" if now_pt.hour < 12 else "afternoon" if now_pt.hour < 17 else "evening"
            month_day = now_pt.strftime("%B %-d")
            time_pt = now_pt.strftime("%-I:%M %p").lower().replace(" ", "")
            friendly_time = f"{day_name} {tod}, {month_day} at {time_pt} PT"
        except Exception:
            friendly_time = yesterday

        buddy_data = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "date": yesterday,
            "beacon": beacon,
            "beacon_label": beacon_label,
            "beacon_summary": beacon_summary,
            "prompt_for_tom": prompt,
            "status_lines": [
                {"area": "Food Logging", "status": food_status, "text": food_text},
                {"area": "Exercise", "status": exercise_status, "text": exercise_text},
                {"area": "Routine", "status": routine_status, "text": routine_text},
                {"area": "Weight", "status": weight_status, "text": weight_text},
            ],
            "activity_highlights": activity_highlights,
            "food_snapshot": food_snapshot,
            "journey": {
                "days": journey_days,
                "lost_lbs": lost_lbs,
                "pct_complete": int(pct_complete),
                "goal_lbs": int(goal_weight),
            },
            "last_updated_friendly": friendly_time,
            "character_sheet": {
                "level": character_sheet.get("character_level", 1),
                "tier": character_sheet.get("character_tier"),
                "tier_emoji": character_sheet.get("character_tier_emoji"),
                "events": character_sheet.get("level_events", []),
            } if character_sheet else None,
            "avatar": _build_avatar_data(character_sheet, profile, current_weight),
        }

        _s3.put_object(
            Bucket=_S3_BUCKET,
            Key="buddy/data.json",
            Body=json.dumps(buddy_data, default=str),
            ContentType="application/json",
            CacheControl="max-age=300",
        )
        print("[INFO] Buddy JSON written to s3://" + _S3_BUCKET + "/buddy/data.json")

    except Exception as e:
        print("[WARN] Buddy JSON write failed: " + str(e))
