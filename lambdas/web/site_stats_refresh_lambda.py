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

import json
import os
from datetime import date, datetime, timedelta, timezone

import boto3
from common.constants import EXPERIMENT_START_DATE  # ADR-058
from common.pacific_time import PACIFIC as PT  # #2414: reader-facing days anchor in the Pacific frame
from health.sensor_absence import carry_forward_ok  # #3204: may a value be republished as current?

from web.vitals_resolver import resolve_vitals  # #1369: the ONE current-vitals truth

REGION = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")
USER_ID = os.environ.get("USER_ID", "matthew")
STATS_KEY = "generated/public_stats.json"  # ADR-046

# Ingestion Lambdas to re-invoke before reading DynamoDB
INGESTION_LAMBDAS = [
    "whoop-data-ingestion",
    "withings-data-ingestion",
    "habitify-data-ingestion",
]

_lambda = boto3.client("lambda", region_name=REGION)
_dynamo = boto3.resource("dynamodb", region_name=REGION)
_s3 = boto3.client("s3", region_name=REGION)


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
    today = datetime.now(PT).date().isoformat()
    start = (datetime.now(PT).date() - timedelta(days=days_back)).isoformat()
    try:
        # ADR-058: phase=pilot hidden by default.
        from experiment.phase_filter import with_phase_filter

        resp = table.query(
            **with_phase_filter(
                {
                    "KeyConditionExpression": "pk = :pk AND sk BETWEEN :s AND :e",
                    "ExpressionAttributeValues": {
                        ":pk": f"USER#{USER_ID}#SOURCE#{source}",
                        ":s": f"DATE#{start}",
                        ":e": f"DATE#{today}",
                    },
                    "ScanIndexForward": False,
                    "Limit": 1,
                }
            )
        )
        items = resp.get("Items", [])
        return dict(items[0]) if items else {}
    except Exception as e:
        print(f"[WARN] DynamoDB read failed ({source}): {e}")
        return {}


def resolve_glucose(apple_health, existing_vitals, today):
    """The CGM average public_stats.json may publish, and the day it is from (#3204).

    Returns ``(glucose_avg, glucose_as_of)`` — both None when there is nothing
    honest to publish.

    This was three lines inline, and the `else` branch re-read this artifact's OWN
    previous ``public_stats.json``:

        glucose_avg = _safe_float(apple_health, "blood_glucose_avg")
        if glucose_avg: fresh_vitals["glucose_avg"] = round(glucose_avg)
        else:           fresh_vitals["glucose_avg"] = ev.get("glucose_avg")

    So when the Dexcom Stelo session ended on 2026-08-24 the file went on
    republishing ``glucose_avg: 107`` every single day — **undated**, sitting beside
    a correctly dated ``weight_as_of``, with no mechanism anywhere that could expire
    it. Worse than ``/api/glucose``, which at least stamped a date a reader (and the
    nightly oracle) could check.

    Carrying a value forward is honest only while it is still current, and "still
    current" is the registry's number, not this module's opinion — ``reader_surface.
    max_days_behind`` for the ``cgm`` sub-datatype (ADR-104, #2003). A carried value
    now travels WITH its date, so the next run can judge it; a value that fails the
    bar is dropped rather than republished. A pre-#3204 artifact has no
    ``glucose_as_of`` to judge, and an undatable number cannot be shown to be
    current, so it is dropped too — self-healing on the first day a sensor lands.

    Extracted so the decision is reachable by a test: ``lambda_handler`` synchronously
    invokes the real ingestion Lambdas before it gets here, so the branch was
    unreachable in-process while it lived inline.
    """
    fresh = _safe_float(apple_health, "blood_glucose_avg")
    if fresh:
        return round(fresh), (apple_health.get("sk", "").replace("DATE#", "") or None)

    prior_as_of = (existing_vitals or {}).get("glucose_as_of")
    if prior_as_of and carry_forward_ok("cgm", prior_as_of, today):
        return (existing_vitals or {}).get("glucose_avg"), prior_as_of
    return None, None


def resolve_tier0_streak(computed_metrics_record, existing_platform):
    """#3172: `tier0_streak` is written by daily-metrics-compute onto the
    ``computed_metrics`` ``DATE#`` row (``store_computed_metrics`` in
    ``compute.daily_metrics_compute_lambda``) — it was never on the raw ``habitify``
    ingestion partition this refresh cron used to read it from. habitify's raw
    payload has no ``tier0_streak`` field at all, so that read was a permanent
    dead-zone None (#2804's class): this section always silently fell through to
    whatever `platform.tier0_streak` the morning brief had last written, and could
    never actually refresh intraday the way its own docstring/comment promised.
    Falls back to the existing public_stats.json value when computed_metrics
    hasn't landed for today yet (pre ~9:40am PT) or is itself absent.
    """
    fresh = _safe_float(computed_metrics_record or {}, "tier0_streak")
    return int(fresh) if fresh is not None else (existing_platform or {}).get("tier0_streak")


def lambda_handler(event, context):
    print("[INFO] site-stats-refresh starting...")

    # ── 1. Re-invoke ingestion Lambdas to pull fresh source API data ─────────
    for fn in INGESTION_LAMBDAS:
        try:
            resp = _lambda.invoke(
                FunctionName=fn,
                InvocationType="RequestResponse",  # synchronous — wait for data
                Payload=json.dumps({}),
            )
            print(f"[INFO] {fn}: HTTP {resp['StatusCode']}")
        except Exception as e:
            print(f"[WARN] {fn} invoke failed (non-fatal): {e}")

    # ── 2. Read fresh records from DynamoDB ───────────────────────────────────
    table = _dynamo.Table(TABLE_NAME)
    withings = _get_latest(table, "withings")
    computed_metrics = _get_latest(table, "computed_metrics")
    apple_health = _get_latest(table, "apple_health")
    character = _get_latest(table, "character_sheet")

    # ── 3. Read existing public_stats.json to preserve non-vitals sections ───
    try:
        existing = json.loads(_s3.get_object(Bucket=S3_BUCKET, Key=STATS_KEY)["Body"].read())
    except Exception as e:
        print(f"[WARN] Could not read existing public_stats.json: {e}")
        existing = {}

    ev = existing.get("vitals", {})

    # ── 4. Build fresh vitals ────────────────────────────────────────────────
    # #1369 Truth Spine: recovery/HRV/RHR/sleep come from the ONE canonical
    # resolver (web/vitals_resolver.py) — the same module /api/pulse and
    # /api/vitals read — so public_stats.json can't disagree with the live site.
    # (Finalized-recovery selection + separate sleep finalization live there now.)
    _vr = resolve_vitals(table, f"USER#{USER_ID}#SOURCE#")
    recovery = _vr["recovery_pct"]
    hrv = _vr["hrv_ms"]
    rhr = _vr["rhr_bpm"]
    sleep = _vr["sleep_hours"]
    weight = _safe_float(withings, "weight_lbs")

    weight_as_of = withings.get("sk", "").replace("DATE#", "") or None
    # v1.4.2: Check apple_health for more recent weight (HAE fallback)
    ah_weight = _safe_float(apple_health, "weight_lbs")
    ah_date = apple_health.get("sk", "").replace("DATE#", "") if apple_health else None
    if ah_weight and (not weight or (ah_date and weight_as_of and ah_date > weight_as_of)):
        weight = ah_weight
        weight_as_of = ah_date
    if not weight:
        weight = ev.get("weight_lbs")
        weight_as_of = ev.get("weight_as_of")

    # Status MUST track the %: never a color without a number behind it (the
    # "recovery_pct: null + recovery_status: red" honesty bug). Both null together
    # when there's no finalized reading; the front-end already omits a null-% row.
    rec_status = _vr["recovery_status"]

    fresh_vitals = {
        "weight_lbs": round(weight) if weight else None,
        "weight_as_of": weight_as_of,
        # #1917: preserved from morning, under the writer's honest name (it is a
        # 7-day delta; it was carried as `weight_delta_30d` until #1917).
        "weight_delta_7d": ev.get("weight_delta_7d"),
        "weight_delta_window_days": ev.get("weight_delta_window_days"),
        "hrv_ms": round(hrv, 1) if hrv else ev.get("hrv_ms"),
        "hrv_trend": ev.get("hrv_trend"),
        "rhr_bpm": round(rhr, 1) if rhr else ev.get("rhr_bpm"),
        "rhr_trend": ev.get("rhr_trend"),
        "recovery_pct": round(recovery, 0) if recovery is not None else None,
        "recovery_status": rec_status,
        "sleep_hours": round(sleep, 1) if sleep else ev.get("sleep_hours"),
        "sleep_hours_30d_avg": ev.get("sleep_hours_30d_avg"),
        # #3451: the n travels with the average — this refresh only ever preserves
        # the morning daily-brief's pair, it never recomputes either half alone.
        "sleep_hours_30d_n": ev.get("sleep_hours_30d_n"),
    }

    # ── 5. Update tier0_streak from computed_metrics if available (#3172) ────
    ep = existing.get("platform", {})
    fresh_streak = resolve_tier0_streak(computed_metrics, ep)

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
    fresh_vitals["glucose_avg"], fresh_vitals["glucose_as_of"] = resolve_glucose(apple_health, ev, datetime.now(PT).strftime("%Y-%m-%d"))

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
    exp_start = date.fromisoformat(EXPERIMENT_START_DATE)
    days_in = max(1, (datetime.now(PT).date() - exp_start).days + 1) if datetime.now(PT).date() >= exp_start else 1
    try:
        # ADR-058: phase=pilot hidden by default.
        from experiment.phase_filter import with_phase_filter

        _tr_resp = table.query(
            **with_phase_filter(
                {
                    "KeyConditionExpression": "pk = :pk AND sk BETWEEN :s AND :e",
                    "ExpressionAttributeValues": {
                        ":pk": f"USER#{USER_ID}#SOURCE#strava",
                        ":s": f"DATE#{exp_start.isoformat()}",
                        ":e": f"DATE#{datetime.now(PT).date().isoformat()}",
                    },
                }
            )
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
            "generated_at": (existing.get("_meta") or {}).get("generated_at"),  # keep morning time
            "refreshed_at": datetime.now(timezone.utc).isoformat(),
            "generated_by": "daily-brief-lambda",
        },
        "vitals": fresh_vitals,
        "platform": {
            **ep,
            "tier0_streak": fresh_streak,
            "protein_avg": fresh_vitals.get("nutrition_protein_g"),
            "days_in": max(1, (datetime.now(PT).date() - exp_start).days + 1) if datetime.now(PT).date() >= exp_start else 0,
        },
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
