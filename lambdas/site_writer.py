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

v1.1.0 — 2026-03-17 (BS-02): hero section added to public_stats.json.
  Contains narrative copy, live counter values, and Chronicle headline for
  the averagejoematt.com homepage transformation story hero.
v1.1.1 — 2026-03-17: Hero paragraph finalised, placeholder flag set to False.
v1.3.0 — 2026-03-22 (D10): baseline param added. Day 1 historical constants
  (weight, HRV, RHR, recovery) now included in public_stats.json so the
  compare card is fully dynamic with no hardcoded fallback values in HTML.
"""

import json
import logging
from datetime import datetime, timezone
from decimal import Decimal

logger = logging.getLogger(__name__)

S3_BUCKET = "matthew-life-platform"
# ADR-046: generated/ prefix isolates Lambda-written files from site deploy --delete
PUBLIC_STATS_KEY = "generated/public_stats.json"
CHARACTER_STATS_KEY = "generated/data/character_stats.json"
PULSE_KEY = "generated/pulse.json"

# ─────────────────────────────────────────────────────────────────────────────
# BS-02: Hero narrative copy (finalised v3.7.67)
# ─────────────────────────────────────────────────────────────────────────────
HERO_WHY_PARAGRAPH = (
    "Most people optimize in the dark — gut feelings, Instagram advice, someone's podcast take. "
    "I connect 19 data sources to a custom AI and publish every number, every week, without filtering. "
    "307 lbs to 185. Every failure included. This is what systematic self-improvement actually looks like."
)

# Journey start date — used for "X days on journey" counter
JOURNEY_START_DATE = "2026-04-01"
JOURNEY_START_WEIGHT = 307.0  # April 1 baseline weight — matches profile and site_constants.js
GOAL_WEIGHT = 185.0


def _json_safe(obj):
    """Convert Decimal and other non-JSON-serializable types."""
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(i) for i in obj]
    return obj


def _compute_hero(vitals: dict, journey: dict) -> dict:
    """
    BS-02: Build the hero section for the homepage transformation story.

    Returns a dict the website JS reads to populate:
    - Live weight counter (302 → current → 185)
    - Days on journey
    - Progress percentage
    - The narrative paragraph
    - Scroll invitation line
    """
    today = datetime.now(timezone.utc).date()
    try:
        start = datetime.strptime(JOURNEY_START_DATE, "%Y-%m-%d").date()
        days_on_journey = max(1, (today - start).days + 1)
    except Exception:
        days_on_journey = 0

    current_weight = journey.get("current_weight_lbs") or vitals.get("weight_lbs")
    lost_lbs       = journey.get("lost_lbs")
    progress_pct   = journey.get("progress_pct")
    goal_date      = journey.get("projected_goal_date", "")

    return {
        "why_paragraph":    HERO_WHY_PARAGRAPH,
        "scroll_invitation": "See the actual numbers below →",
        "days_on_journey":  days_on_journey,
        "start_weight_lbs": JOURNEY_START_WEIGHT,
        "goal_weight_lbs":  GOAL_WEIGHT,
        "current_weight_lbs": current_weight,
        "lost_lbs":         lost_lbs,
        "progress_pct":     progress_pct,
        "projected_goal_date": goal_date,
        "journey_started":  JOURNEY_START_DATE,
        "paragraph_is_placeholder": False,
    }


def _get_latest_chronicle_headline(table_client, user_id: str) -> dict | None:
    """
    BS-02: Fetch the most recent Chronicle headline for the below-fold section.
    Non-fatal — returns None if unavailable.
    """
    if table_client is None:
        return None
    try:
        from datetime import timedelta
        today = datetime.now(timezone.utc).date()
        week_ago = (today - timedelta(days=7)).isoformat()
        resp = table_client.query(
            KeyConditionExpression="pk = :pk AND sk BETWEEN :s AND :e",
            ExpressionAttributeValues={
                ":pk": f"USER#{user_id}#SOURCE#chronicle",
                ":s":  f"DATE#{week_ago}",
                ":e":  f"DATE#{today.isoformat()}",
            },
            ScanIndexForward=False,
            Limit=1,
        )
        items = resp.get("Items", [])
        if items:
            item = items[0]
            return {
                "title":      item.get("title", ""),
                "week_num":   int(item.get("week_number", 0)),
                "date":       item.get("date", ""),
                "stats_line": item.get("stats_line", ""),
            }
    except Exception as exc:
        logger.warning("[site_writer] Chronicle headline fetch failed: %s", exc)
    return None


def _get_recent_chronicles(table_client, user_id: str, count: int = 3) -> list:
    """
    HP-14: Fetch the N most recent Chronicle entries for homepage cards.
    Returns list of {title, week_num, date, url, excerpt}.
    Non-fatal — returns [] if unavailable.
    """
    if table_client is None:
        return []
    try:
        from datetime import timedelta
        today = datetime.now(timezone.utc).date()
        d90 = (today - timedelta(days=90)).isoformat()
        resp = table_client.query(
            KeyConditionExpression="pk = :pk AND sk BETWEEN :s AND :e",
            ExpressionAttributeValues={
                ":pk": f"USER#{user_id}#SOURCE#chronicle",
                ":s":  f"DATE#{d90}",
                ":e":  f"DATE#{today.isoformat()}",
            },
            ScanIndexForward=False,
            Limit=count,
        )
        items = resp.get("Items", [])
        entries = []
        for item in items:
            week_num = int(item.get("week_number", 0))
            title = item.get("title", "")
            date = item.get("date", "")
            # Build excerpt from opening paragraph or stats_line
            excerpt = item.get("stats_line") or item.get("opening_line", "")
            if not excerpt:
                body = item.get("body", "")
                if body:
                    # Take first sentence (up to 120 chars)
                    first_sentence = body.split(".")[0][:120]
                    excerpt = first_sentence + ("." if len(first_sentence) < 120 else "…")
            # URL: /chronicle/week-N/ pattern
            url = f"/chronicle/week-{week_num}/" if week_num else "/chronicle/"
            entries.append({
                "title":    title,
                "week_num": week_num,
                "date":     date,
                "url":      url,
                "excerpt":  (excerpt or "")[:150],
            })
        return entries
    except Exception as exc:
        logger.warning("[site_writer] Recent chronicles fetch failed: %s", exc)
    return []


def write_public_stats(s3_client, vitals: dict, journey: dict, training: dict,
                       platform: dict = None, table_client=None, user_id: str = "matthew",
                       trends: dict = None, brief_excerpt: str = None,
                       baseline: dict = None, group_narratives: dict = None,
                       elena_hero_line: str = None,
                       character: dict = None) -> bool:
    """
    Write public_stats.json to S3 from daily-brief-lambda data.

    Call at the end of daily_brief_lambda.lambda_handler, after all
    computations are done but before returning.

    Args:
        s3_client:    boto3 S3 client (already initialised in the Lambda)
        vitals:       dict with keys: weight_lbs, weight_delta_30d, hrv_ms,
                      hrv_trend, rhr_bpm, rhr_trend, recovery_pct, recovery_status,
                      sleep_hours
        journey:      dict with keys: start_weight_lbs, goal_weight_lbs,
                      current_weight_lbs, lost_lbs, remaining_lbs, progress_pct,
                      weekly_rate_lbs, projected_goal_date, days_to_goal,
                      started_date, current_phase, next_milestone_lbs,
                      next_milestone_date, next_milestone_name
        training:     dict with keys: ctl_fitness, atl_fatigue, tsb_form, acwr,
                      form_status, injury_risk, total_miles_30d, activity_count_30d,
                      zone2_this_week_min, zone2_target_min
        platform:     optional dict with keys: mcp_tools, data_sources, lambdas,
                      last_review_grade (defaults used if None)
        table_client: optional DynamoDB table resource for Chronicle headline fetch
        user_id:      user ID for Chronicle headline query (default: 'matthew')
        baseline:     optional dict with Day 1 historical constants:
                      { date, weight_lbs, hrv_ms, rhr_bpm, recovery_pct }
                      Populated from profile fields or known journey-start readings.
        elena_hero_line: optional one-sentence Elena Voss observation for homepage
                      hero section. Updated weekly when Chronicle publishes.
        character:    optional dict with character sheet headline data:
                      { level, tier, tier_emoji, xp_total, composite_score,
                        next_level_xp, xp_to_next, days_active }
                      Populated from character_sheet_compute output.

    Returns:
        True on success, False on failure (non-fatal — never raise)
    """
    try:
        hero = _compute_hero(vitals, journey)

        # BS-02: Fetch latest Chronicle headline for below-fold section
        chronicle_headline = None
        if table_client is not None:
            chronicle_headline = _get_latest_chronicle_headline(table_client, user_id)

        # HP-14: Fetch 3 most recent Chronicle entries for homepage cards
        chronicle_recent = _get_recent_chronicles(table_client, user_id, count=3)

        payload = {
            "_meta": {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "generated_by": "daily-brief-lambda",
                "version": "1.2.0",
            },
            # BS-02: Transformation story hero data
            "hero": _json_safe(hero),
            # BS-02: Latest Chronicle headline for below-fold
            "chronicle_latest": _json_safe(chronicle_headline) if chronicle_headline else None,
            "vitals":   _json_safe(vitals),
            "journey":  _json_safe(journey),
            "training": _json_safe(training),
            "platform": _json_safe(platform or {
                "mcp_tools": 95,
                "data_sources": 19,
                "lambdas": 50,
                "last_review_grade": "A-",
            }),
            # v1.2.0: Trend arrays for homepage sparkline charts
            "trends": _json_safe(trends or {}),
            # v1.2.0: AI brief excerpt for "What Claude Sees" homepage widget
            "brief_excerpt": brief_excerpt,
            # D10: Day 1 baseline for compare card — historical constants, not live data
            "baseline": _json_safe(baseline) if baseline else None,
            # LIVE-2: One sentence per cockpit group for /live/ page narratives
            "group_narratives": _json_safe(group_narratives or {}),
            # HP-12: Elena Voss hero one-liner (updated weekly by chronicle/digest)
            "elena_hero_line": elena_hero_line,
            # HP-14: Recent Chronicle entries for homepage cards
            "chronicle_recent": _json_safe(chronicle_recent) if chronicle_recent else [],
            # PB-R1: Character sheet headline data for homepage heartbeat + nav badge
            "character": _json_safe(character) if character else None,
        }

        s3_client.put_object(
            Bucket=S3_BUCKET,
            Key=PUBLIC_STATS_KEY,
            Body=json.dumps(payload, indent=2),
            ContentType="application/json",
            CacheControl="max-age=3600",
        )
        logger.info("[site_writer] public_stats.json written to S3 (hero + chronicle + baseline + elena + character + chronicle_recent)")
        return True

    except Exception as e:
        # Non-fatal — website staleness is preferable to breaking the Daily Brief
        logger.warning(f"[site_writer] Failed to write public_stats.json: {e}")
        return False


def write_character_stats(s3_client, character: dict, pillars: list, timeline: list,
                          tiers: list = None, pillar_history: list = None) -> bool:
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
            # CHAR-4: Weekly pillar history for independence heatmap
            "pillar_history": _json_safe(pillar_history or []),
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


# ── PULSE-A1/A2/A3: Pulse computation and storage ──────────────────────────────

def _glyph_state(green_test, amber_test, has_data):
    """Return 'green', 'amber', 'red', or 'gray' based on signal thresholds."""
    if not has_data:
        return "gray"
    if green_test:
        return "green"
    if amber_test:
        return "amber"
    return "red"


def _compute_pulse(vitals: dict, journey: dict, training: dict,
                   journal_data: dict = None, mood_data: dict = None,
                   trends: dict = None, brief_excerpt: str = None) -> dict:
    """Compute the full pulse object from daily brief data."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    try:
        from datetime import date as _date
        started = _date.fromisoformat(JOURNEY_START_DATE)
        day_number = max(1, (_date.today() - started).days + 1)
    except Exception:
        day_number = 0

    glyphs = {}

    # ── 1. SCALE ──
    weight = vitals.get("weight_lbs")
    weight_daily = (trends or {}).get("weight_daily", [])
    day_delta = None
    direction = None
    if weight_daily and len(weight_daily) >= 2:
        prev = weight_daily[-2].get("lbs")
        curr = weight_daily[-1].get("lbs")
        if prev and curr:
            day_delta = round(curr - prev, 1)
            direction = "down" if day_delta < 0 else ("up" if day_delta > 0 else "flat")

    glyphs["scale"] = {
        "state": _glyph_state(
            green_test=(day_delta is not None and day_delta <= 0),
            amber_test=(day_delta is not None and day_delta <= 0.5),
            has_data=(weight is not None),
        ),
        "direction": direction,
        "value": round(weight, 1) if weight else None,
        "delta": day_delta,
        "delta_label": f"{day_delta:+.1f} from yesterday" if day_delta is not None else None,
        "journey_summary": (
            f"{round(JOURNEY_START_WEIGHT - weight, 1)} lbs lost "
            f"({round((JOURNEY_START_WEIGHT - weight) / (JOURNEY_START_WEIGHT - GOAL_WEIGHT) * 100, 1)}%)"
            if weight and weight < JOURNEY_START_WEIGHT else None
        ),
        "sparkline_7d": [d.get("lbs") for d in weight_daily[-7:]] if weight_daily else [],
        "as_of": vitals.get("weight_as_of") or today,
    }

    # ── 2. WATER (not yet tracked) ──
    glyphs["water"] = {"state": "gray", "liters": None, "target": 3.0, "label": None,
                       "sparkline_7d": [], "as_of": today}

    # ── 3. MOVEMENT ──
    z2_week = training.get("zone2_this_week_min", 0) or 0
    activity_type = training.get("today_activity")
    has_movement = z2_week > 0 or activity_type
    glyphs["movement"] = {
        "state": _glyph_state(green_test=bool(activity_type or z2_week > 60),
                              amber_test=(z2_week > 0), has_data=has_movement),
        "steps": None, "zone2_week_min": round(z2_week), "zone2_target": 150,
        "activity_type": activity_type, "sparkline_7d": [], "as_of": today,
    }

    # ── 4. LIFT ──
    trained_today = bool(activity_type)
    glyphs["lift"] = {
        "state": _glyph_state(green_test=trained_today, amber_test=True, has_data=True),
        "trained_today": trained_today, "workout_type": activity_type or "Rest",
        "strain": training.get("today_strain"), "sessions_this_week": 0,
        "rest_day_streak": 0, "as_of": today,
    }

    # ── 5. RECOVERY ──
    recovery_pct = vitals.get("recovery_pct")
    recovery_trend = (trends or {}).get("recovery_daily", [])
    glyphs["recovery"] = {
        "state": _glyph_state(green_test=(recovery_pct and recovery_pct >= 67),
                              amber_test=(recovery_pct and recovery_pct >= 33),
                              has_data=(recovery_pct is not None)),
        "recovery_pct": round(recovery_pct) if recovery_pct else None,
        "status_label": ("Optimal" if (recovery_pct or 0) >= 67 else
                         ("Moderate" if (recovery_pct or 0) >= 33 else "Needs rest"))
                         if recovery_pct else None,
        "hrv_ms": vitals.get("hrv_ms"), "rhr_bpm": vitals.get("rhr_bpm"),
        "sparkline_7d": [d.get("pct") for d in recovery_trend[-7:]] if recovery_trend else [],
        "as_of": today,
    }

    # ── 6. SLEEP ──
    sleep_hours = vitals.get("sleep_hours")
    sleep_trend = (trends or {}).get("sleep_daily", [])
    glyphs["sleep"] = {
        "state": _glyph_state(green_test=(sleep_hours and sleep_hours >= 7),
                              amber_test=(sleep_hours and sleep_hours >= 6),
                              has_data=(sleep_hours is not None)),
        "hours": round(sleep_hours, 1) if sleep_hours else None,
        "score": vitals.get("sleep_score"),
        "sparkline_7d": [d.get("hrs") for d in sleep_trend[-7:]] if sleep_trend else [],
        "as_of": today,
    }

    # ── 7. JOURNAL ──
    journal = journal_data or {}
    written_today = bool(journal.get("entries") and journal["entries"] > 0)
    glyphs["journal"] = {
        "state": "green" if written_today else "gray",
        "written_today": written_today, "streak_days": journal.get("streak_days", 0),
        "themes": (journal.get("themes") or [])[:3], "binary_14d": [], "as_of": today,
    }

    # ── 8. MIND ──
    mood = mood_data or {}
    mood_score = mood.get("score") or mood.get("mood_avg")
    has_mood = mood_score is not None
    mood_labels = {1: "Low", 2: "Below avg", 3: "Average", 4: "Good", 5: "Excellent"}
    glyphs["mind"] = {
        "state": _glyph_state(green_test=(mood_score and float(mood_score) >= 4),
                              amber_test=(mood_score and float(mood_score) >= 3),
                              has_data=has_mood),
        "score": round(float(mood_score)) if mood_score else None, "max_score": 5,
        "label": mood_labels.get(round(float(mood_score))) if mood_score else None,
        "sparkline_7d": [], "as_of": today,
    }

    # ── PULSE STATUS ──
    glyph_states = [g["state"] for g in glyphs.values()]
    green_count = glyph_states.count("green")
    reporting_count = len([s for s in glyph_states if s != "gray"])
    has_red = "red" in glyph_states

    if reporting_count <= 2:
        status, status_color = "quiet", "#3a5a48"
    elif green_count >= 6 and not has_red:
        status, status_color = "strong", "#00e5a0"
    else:
        status, status_color = "mixed", "#f5a623"

    # ── NARRATIVE ──
    narrative = brief_excerpt
    if not narrative:
        if status == "quiet":
            narrative = (f"{reporting_count} signal{'s' if reporting_count != 1 else ''}"
                         " reporting. The rest is silence.")
        elif status == "strong":
            parts = []
            if day_delta is not None and day_delta < 0:
                parts.append(f"Weight dropped {abs(day_delta)} lbs")
            if sleep_hours and sleep_hours >= 7:
                parts.append(f"Sleep at {round(sleep_hours, 1)}h")
            if recovery_pct and recovery_pct >= 67:
                parts.append(f"Recovery {round(recovery_pct)}%")
            narrative = ". ".join(parts[:3]) + ". The system is humming." if parts else "All signals green."
        else:
            amber_red = [n for n, g in glyphs.items() if g["state"] in ("amber", "red")]
            narrative = f"{', '.join(amber_red[:2]).title()} flagged. Mixed signals today."

    return {
        "pulse": {
            "day_number": day_number, "date": today,
            "status": status, "status_color": status_color,
            "narrative": narrative,
            "signals_reporting": reporting_count, "signals_total": 8,
            "glyphs": glyphs,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
    }


def write_pulse_json(s3_client, vitals: dict, journey: dict, training: dict,
                     journal_data: dict = None, mood_data: dict = None,
                     trends: dict = None, brief_excerpt: str = None,
                     table_client=None, user_id: str = "matthew") -> bool:
    """PULSE-A2/A3: Write pulse.json to S3 + DynamoDB for /api/pulse."""
    try:
        pulse = _compute_pulse(vitals=vitals, journey=journey, training=training,
                               journal_data=journal_data, mood_data=mood_data,
                               trends=trends, brief_excerpt=brief_excerpt)
        s3_client.put_object(Bucket=S3_BUCKET, Key=PULSE_KEY,
                             Body=json.dumps(pulse, indent=2, default=str),
                             ContentType="application/json", CacheControl="max-age=300")
        logger.info("[site_writer] pulse.json written to S3")

        if table_client is not None:
            today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            try:
                pulse_json = json.dumps(pulse["pulse"], default=str)
                pulse_item = json.loads(pulse_json, parse_float=Decimal)
                table_client.put_item(Item={"pk": "PULSE", "sk": f"DATE#{today_str}",
                                            "date": today_str,
                                            **{k: v for k, v in pulse_item.items() if v is not None}})
                logger.info(f"[site_writer] Pulse DynamoDB: {today_str}")
            except Exception as ddb_e:
                logger.warning(f"[site_writer] Pulse DDB write failed: {ddb_e}")
        return True
    except Exception as e:
        logger.warning(f"[site_writer] pulse.json failed: {e}")
        return False
