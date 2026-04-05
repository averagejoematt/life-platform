#!/usr/bin/env python3
"""
site_stats_refresh_lambda.py — Lightweight stats refresh for averagejoematt.com

Runs 4x/day (8am, 12pm, 4pm, 8pm Pacific) to keep public_stats.json fresh
without making any AI/Claude calls. Invokes whoop + withings + habitify
ingestion Lambdas to pull fresh API data, then reads DynamoDB and updates
the vitals section of public_stats.json in-place.

Preserves: journey, platform counts, trends, baseline, brief_excerpt from
the morning daily-brief run. Only overwrites: vitals (recovery, HRV, weight,
sleep), tier0_streak, and _meta timestamp.

Cost: ~$0/month (well within Lambda free tier).
"""
import boto3
import json
import os
from datetime import datetime, timezone, date, timedelta

REGION       = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME   = os.environ.get("TABLE_NAME", "life-platform")
S3_BUCKET    = os.environ.get("S3_BUCKET", "matthew-life-platform")
USER_ID      = os.environ.get("USER_ID", "matthew")
STATS_KEY    = "generated/public_stats.json"  # ADR-046

# Ingestion Lambdas to re-invoke before reading DynamoDB
INGESTION_LAMBDAS = [
    "whoop-data-ingestion",
    "withings-data-ingestion",
    "habitify-data-ingestion",
]

_lambda = boto3.client("lambda", region_name=REGION)
_dynamo = boto3.resource("dynamodb", region_name=REGION)
_s3     = boto3.client("s3", region_name=REGION)


def _safe_float(d, key):
    try:
        v = d.get(key)
        if v is None:
            return None
        f = float(v)
        return f if f != 0.0 else None
    except Exception:
        return None


def _get_latest(table, source, days_back=2):
    """Return most recent DynamoDB record for source, or {}."""
    today = date.today().isoformat()
    start = (date.today() - timedelta(days=days_back)).isoformat()
    try:
        resp = table.query(
            KeyConditionExpression="pk = :pk AND sk BETWEEN :s AND :e",
            ExpressionAttributeValues={
                ":pk": f"USER#{USER_ID}#SOURCE#{source}",
                ":s":  f"DATE#{start}",
                ":e":  f"DATE#{today}",
            },
            ScanIndexForward=False,
            Limit=1,
        )
        items = resp.get("Items", [])
        return dict(items[0]) if items else {}
    except Exception as e:
        print(f"[WARN] DynamoDB read failed ({source}): {e}")
        return {}


def lambda_handler(event, context):
    print("[INFO] site-stats-refresh starting...")

    # ── 1. Re-invoke ingestion Lambdas to pull fresh source API data ─────────
    for fn in INGESTION_LAMBDAS:
        try:
            resp = _lambda.invoke(
                FunctionName=fn,
                InvocationType="RequestResponse",   # synchronous — wait for data
                Payload=json.dumps({}),
            )
            print(f"[INFO] {fn}: HTTP {resp['StatusCode']}")
        except Exception as e:
            print(f"[WARN] {fn} invoke failed (non-fatal): {e}")

    # ── 2. Read fresh records from DynamoDB ───────────────────────────────────
    table    = _dynamo.Table(TABLE_NAME)
    whoop    = _get_latest(table, "whoop")
    withings = _get_latest(table, "withings")
    habitify = _get_latest(table, "habitify")
    apple_health = _get_latest(table, "apple_health")
    character = _get_latest(table, "character_sheet")

    # ── 3. Read existing public_stats.json to preserve non-vitals sections ───
    try:
        existing = json.loads(
            _s3.get_object(Bucket=S3_BUCKET, Key=STATS_KEY)["Body"].read()
        )
    except Exception as e:
        print(f"[WARN] Could not read existing public_stats.json: {e}")
        existing = {}

    ev = existing.get("vitals", {})

    # ── 4. Build fresh vitals ────────────────────────────────────────────────
    recovery = _safe_float(whoop, "recovery_score")
    hrv      = _safe_float(whoop, "hrv")
    rhr      = _safe_float(whoop, "resting_heart_rate")
    sleep    = _safe_float(whoop, "sleep_duration_hours")
    weight   = _safe_float(withings, "weight_lbs")

    weight_as_of = withings.get("sk", "").replace("DATE#", "") or None
    # v1.4.2: Check apple_health for more recent weight (HAE fallback)
    ah_weight = _safe_float(apple_health, "weight_lbs")
    ah_date = apple_health.get("sk", "").replace("DATE#", "") if apple_health else None
    if ah_weight and (not weight or (ah_date and weight_as_of and ah_date > weight_as_of)):
        weight = ah_weight
        weight_as_of = ah_date
    if not weight:
        weight       = ev.get("weight_lbs")
        weight_as_of = ev.get("weight_as_of")

    rec_status = (
        "green"  if (recovery or 0) >= 67 else
        "yellow" if (recovery or 0) >= 34 else
        "red"
    )

    fresh_vitals = {
        "weight_lbs":          round(weight) if weight else None,
        "weight_as_of":        weight_as_of,
        "weight_delta_30d":    ev.get("weight_delta_30d"),   # preserved from morning
        "hrv_ms":              round(hrv, 1)  if hrv      else ev.get("hrv_ms"),
        "hrv_trend":           ev.get("hrv_trend"),
        "rhr_bpm":             round(rhr, 1)  if rhr      else ev.get("rhr_bpm"),
        "rhr_trend":           ev.get("rhr_trend"),
        "recovery_pct":        round(recovery, 0) if recovery else None,
        "recovery_status":     rec_status if recovery else ev.get("recovery_status"),
        "sleep_hours":         round(sleep, 1) if sleep   else ev.get("sleep_hours"),
        "sleep_hours_30d_avg": ev.get("sleep_hours_30d_avg"),
    }

    # ── 5. Update tier0_streak from habitify if available ────────────────────
    ep = existing.get("platform", {})
    fresh_streak = _safe_float(habitify, "tier0_streak")
    fresh_streak = int(fresh_streak) if fresh_streak is not None else ep.get("tier0_streak")

    # ── 5b. Water from apple_health ───────────────────────────────────────────
    water_ml = _safe_float(apple_health, "water_intake_ml")
    if water_ml:
        fresh_vitals["water_ml"] = round(water_ml, 0)
    else:
        fresh_vitals["water_ml"] = ev.get("water_ml")

    # ── 5c. Character level ────────────────────────────────────────────────
    char_level = _safe_float(character, "character_level") if character else None
    char_tier = character.get("character_tier") if character else None

    # ── 5d. Glucose average (CGM from apple_health) ──────────────────────
    glucose_avg = _safe_float(apple_health, "blood_glucose_avg")
    if glucose_avg:
        fresh_vitals["glucose_avg"] = round(glucose_avg)
    else:
        fresh_vitals["glucose_avg"] = ev.get("glucose_avg")

    # ── 5e. Nutrition summary (MacroFactor) ──────────────────────────────
    macrofactor = _get_latest(table, "macrofactor")
    mf_cal = _safe_float(macrofactor, "total_calories_kcal")
    mf_pro = _safe_float(macrofactor, "total_protein_g")
    fresh_vitals["nutrition_calories"] = round(mf_cal) if mf_cal else ev.get("nutrition_calories")
    fresh_vitals["nutrition_protein_g"] = round(mf_pro) if mf_pro else ev.get("nutrition_protein_g")
    # Aliases for homepage JS compatibility
    fresh_vitals["calories_avg"] = fresh_vitals["nutrition_calories"]

    # ── 5f. Training summary (average daily active minutes from Strava) ──
    # Use the experiment start to compute avg daily training
    exp_start = date.fromisoformat("2026-04-01")
    days_in = max(1, (date.today() - exp_start).days + 1) if date.today() >= exp_start else 1
    try:
        _tr_resp = table.query(
            KeyConditionExpression="pk = :pk AND sk BETWEEN :s AND :e",
            ExpressionAttributeValues={
                ":pk": f"USER#{USER_ID}#SOURCE#strava",
                ":s": f"DATE#{exp_start.isoformat()}",
                ":e": f"DATE#{date.today().isoformat()}",
            },
        )
        _tr_items = _tr_resp.get("Items", [])
        total_min = 0
        for ti in _tr_items:
            acts = ti.get("activities") or ti.get("activities_list") or []
            if isinstance(acts, list):
                for a in acts:
                    dur = a.get("duration_minutes") or a.get("moving_time_seconds")
                    if dur:
                        d_val = float(str(dur))
                        total_min += d_val if d_val < 1440 else d_val / 60  # handle seconds vs minutes
        fresh_vitals["training_avg_daily_min"] = round(total_min / days_in) if total_min else ev.get("training_avg_daily_min")
    except Exception:
        fresh_vitals["training_avg_daily_min"] = ev.get("training_avg_daily_min")

    # Homepage JS aliases (zone2_min_avg used for training tile)
    fresh_vitals["zone2_min_avg"] = fresh_vitals.get("training_avg_daily_min")

    # Protein avg in platform section for homepage JS compatibility
    # (homepage reads p.protein_avg from platform, not vitals)

    # ── 6. Merge — preserve everything except vitals + streak + _meta ────────
    # Update character in payload
    existing_char = existing.get("character") or {}
    if char_level is not None:
        existing_char = {
            "level": int(char_level),
            "tier": char_tier or existing_char.get("tier"),
            "tier_emoji": character.get("character_tier_emoji") or existing_char.get("tier_emoji"),
        }

    payload = {
        **existing,
        "character": existing_char or None,
        "_meta": {
            **existing.get("_meta", {}),
            "generated_at":  existing.get("_meta", {}).get("generated_at"),  # keep morning time
            "refreshed_at":  datetime.now(timezone.utc).isoformat(),
            "generated_by":  "daily-brief-lambda",
        },
        "vitals":   fresh_vitals,
        "platform": {**ep, "tier0_streak": fresh_streak,
                     "protein_avg": fresh_vitals.get("nutrition_protein_g"),
                     "days_in": max(1, (date.today() - date.fromisoformat("2026-04-01")).days + 1) if date.today() >= date.fromisoformat("2026-04-01") else 0},
    }

    # ── 7. Write back ─────────────────────────────────────────────────────────
    _s3.put_object(
        Bucket=S3_BUCKET,
        Key=STATS_KEY,
        Body=json.dumps(payload, indent=2, default=str),
        ContentType="application/json",
        CacheControl="max-age=3600",
    )
    print("[INFO] public_stats.json refreshed (vitals only — no AI calls)")
    return {"statusCode": 200, "body": "refreshed"}
