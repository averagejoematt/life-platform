"""
site_writer.py — Writes public_stats.json and character_stats.json to S3
for the averagejoematt.com website.

INTEGRATION INSTRUCTIONS:
  1. Add this file to lambdas/ in the life-platform repo
  2. In daily_brief_lambda.py, add at the end of lambda_handler:
       from site_writer import write_public_stats
       write_public_stats(s3_client, vitals_data, journey_data, training_data)
  3. In character_sheet_compute_lambda.py, add at the end of lambda_handler:
       from site_writer import write_character_stats
       write_character_stats(s3_client, character_record, pillar_records, timeline)

COST WARNING: This is just two extra s3.put_object calls inside Lambdas
already running daily. Zero new infrastructure. Zero new cost. 
Files served via existing CloudFront distribution on matthew-life-platform.

S3 path: s3://matthew-life-platform/site/public_stats.json
         s3://matthew-life-platform/site/character_stats.json

CloudFront: add a /site/* behaviour pointing to S3 origin.
"""

import json
import logging
from datetime import datetime, timezone
from decimal import Decimal

logger = logging.getLogger(__name__)

S3_BUCKET = "matthew-life-platform"
PUBLIC_STATS_KEY = "site/public_stats.json"
CHARACTER_STATS_KEY = "site/character_stats.json"


def _json_safe(obj):
    """Convert Decimal and other non-JSON-serializable types."""
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(i) for i in obj]
    return obj


def write_public_stats(s3_client, vitals: dict, journey: dict, training: dict, platform: dict = None) -> bool:
    """
    Write public_stats.json to S3 from daily-brief-lambda data.

    Call at the end of daily_brief_lambda.lambda_handler, after all
    computations are done but before returning.

    Args:
        s3_client:  boto3 S3 client (already initialised in the Lambda)
        vitals:     dict with keys: weight_lbs, weight_delta_30d, hrv_ms,
                    hrv_trend, rhr_bpm, rhr_trend, recovery_pct, recovery_status,
                    sleep_hours
        journey:    dict with keys: start_weight_lbs, goal_weight_lbs,
                    current_weight_lbs, lost_lbs, remaining_lbs, progress_pct,
                    weekly_rate_lbs, projected_goal_date, days_to_goal,
                    started_date, current_phase, next_milestone_lbs,
                    next_milestone_date, next_milestone_name
        training:   dict with keys: ctl_fitness, atl_fatigue, tsb_form, acwr,
                    form_status, injury_risk, total_miles_30d, activity_count_30d,
                    zone2_this_week_min, zone2_target_min
        platform:   optional dict with keys: mcp_tools, data_sources, lambdas,
                    last_review_grade (defaults used if None)

    Returns:
        True on success, False on failure (non-fatal — never raise)
    """
    try:
        payload = {
            "_meta": {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "generated_by": "daily-brief-lambda",
                "version": "1.0.0",
            },
            "vitals": _json_safe(vitals),
            "journey": _json_safe(journey),
            "training": _json_safe(training),
            "platform": _json_safe(platform or {
                "mcp_tools": 87,
                "data_sources": 19,
                "lambdas": 42,
                "last_review_grade": "A",
            }),
        }

        s3_client.put_object(
            Bucket=S3_BUCKET,
            Key=PUBLIC_STATS_KEY,
            Body=json.dumps(payload, indent=2),
            ContentType="application/json",
            CacheControl="max-age=86400",  # CloudFront caches for 24h
        )
        logger.info("[site_writer] public_stats.json written to S3")
        return True

    except Exception as e:
        # Non-fatal — website staleness is preferable to breaking the Daily Brief
        logger.warning(f"[site_writer] Failed to write public_stats.json: {e}")
        return False


def write_character_stats(s3_client, character: dict, pillars: list, timeline: list, tiers: list = None) -> bool:
    """
    Write character_stats.json to S3 from character-sheet-compute data.

    Call at the end of character_sheet_compute_lambda.lambda_handler,
    after store_character_sheet() succeeds.

    Args:
        s3_client:  boto3 S3 client
        character:  dict with keys: level, tier, tier_emoji, xp_total,
                    days_active, level_events_count, next_tier, next_tier_level,
                    started_date
        pillars:    list of dicts, each with keys: name, emoji, level,
                    raw_score, tier, xp_delta, trend
        timeline:   list of dicts, each with keys: date, character_level, event
        tiers:      optional list of tier dicts (defaults used if None)

    Returns:
        True on success, False on failure (non-fatal)
    """
    try:
        default_tiers = [
            {"name": "Foundation", "emoji": "🔨", "min_level": 1,  "max_level": 20,  "status": "current" if character.get("tier") == "Foundation" else "locked"},
            {"name": "Momentum",   "emoji": "🔥", "min_level": 21, "max_level": 40,  "status": "current" if character.get("tier") == "Momentum" else "locked"},
            {"name": "Discipline", "emoji": "⚔️", "min_level": 41, "max_level": 60,  "status": "current" if character.get("tier") == "Discipline" else "locked"},
            {"name": "Mastery",    "emoji": "🏆", "min_level": 61, "max_level": 80,  "status": "current" if character.get("tier") == "Mastery" else "locked"},
            {"name": "Elite",      "emoji": "👑", "min_level": 81, "max_level": 100, "status": "current" if character.get("tier") == "Elite" else "locked"},
        ]

        payload = {
            "_meta": {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "generated_by": "character-sheet-compute-lambda",
                "version": "1.0.0",
            },
            "character": _json_safe(character),
            "pillars": _json_safe(pillars),
            "timeline": _json_safe(timeline[-20:]),  # Last 20 events only
            "tiers": _json_safe(tiers or default_tiers),
        }

        s3_client.put_object(
            Bucket=S3_BUCKET,
            Key=CHARACTER_STATS_KEY,
            Body=json.dumps(payload, indent=2),
            ContentType="application/json",
            CacheControl="max-age=86400",
        )
        logger.info("[site_writer] character_stats.json written to S3")
        return True

    except Exception as e:
        logger.warning(f"[site_writer] Failed to write character_stats.json: {e}")
        return False
