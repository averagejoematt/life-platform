"""
challenge_generator_lambda.py — AI-Powered Challenge Generation Pipeline

Runs weekly (Sunday 3 PM PT, after hypothesis engine + weekly correlations).
Generates 0-5 challenge candidates from 5 sources:

  1. journal_mining   — Scans enriched journal for recurring avoidance flags / themes
  2. data_signal      — Reads character sheet for weak pillars, habit scores for broken streaks
  3. hypothesis_graduate — Confirmed hypotheses that should become behavioural challenges
  4. science_scan     — AI suggests evidence-based challenges from current research context
  5. (manual/community — handled via MCP tools, not this Lambda)

Pipeline:
  1. Gather context: 14d journal entries, character sheet, habit scores, active challenges
  2. Build structured prompt with all context
  3. Call Claude Sonnet → JSON response with 0-5 challenge candidates
  4. Dedup against existing challenges
  5. Write candidates to DDB SOURCE#challenges partition (status='candidate')
  6. Matthew reviews and activates via MCP tool or website

DDB pattern:
  pk = USER#matthew#SOURCE#challenges
  sk = CHALLENGE#<slug>_<date>

EventBridge: cron(0 22 ? * SUN *)  → 3 PM PT / 10 PM UTC on Sundays

Cost: ~$0.05/week (one Sonnet call + DDB reads/writes)
"""

import json
import os
import logging
import re
import time
import boto3
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone
from decimal import Decimal

try:
    from platform_logger import get_logger
    logger = get_logger("challenge-generator")
except ImportError:
    logger = logging.getLogger("challenge-generator")
    logger.setLevel(logging.INFO)

try:
    from ai_output_validator import validate_ai_output, AIOutputType
    _HAS_AI_VALIDATOR = True
except ImportError:
    _HAS_AI_VALIDATOR = False

REGION     = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
USER_ID    = os.environ["USER_ID"]
S3_BUCKET  = os.environ["S3_BUCKET"]

dynamodb = boto3.resource("dynamodb", region_name=REGION)
table    = dynamodb.Table(TABLE_NAME)
s3       = boto3.client("s3", region_name=REGION)
secrets  = boto3.client("secretsmanager", region_name=REGION)

AI_MODEL = os.environ.get("AI_MODEL", "claude-sonnet-4-6")

CHALLENGES_PK  = f"USER#{USER_ID}#SOURCE#challenges"
HYPOTHESES_PK  = f"USER#{USER_ID}#SOURCE#hypotheses"
CHARACTER_PK   = f"USER#{USER_ID}#SOURCE#character_sheet"
HABIT_SCORES_PK = f"USER#{USER_ID}#SOURCE#habit_scores"

MAX_NEW_CHALLENGES = 5
LOOKBACK_DAYS = 14


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def get_anthropic_key():
    secret_name = os.environ.get("ANTHROPIC_SECRET", "life-platform/ai-keys")
    try:
        val = secrets.get_secret_value(SecretId=secret_name)
        data = json.loads(val["SecretString"])
        return data.get("ANTHROPIC_API_KEY") or data.get("anthropic_api_key")
    except Exception as e:
        logger.error(f"Failed to get Anthropic key: {e}")
        raise


def d2f(obj):
    """Convert DynamoDB Decimals to float/int."""
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, dict):
        return {k: d2f(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [d2f(i) for i in obj]
    return obj


def query_range(source, start_date, end_date):
    from boto3.dynamodb.conditions import Key
    pk = f"USER#{USER_ID}#SOURCE#{source}"
    try:
        resp = table.query(
            KeyConditionExpression=Key("pk").eq(pk) & Key("sk").between(
                f"DATE#{start_date}", f"DATE#{end_date}"
            )
        )
        return d2f(resp.get("Items", []))
    except Exception as e:
        logger.warning(f"query_range({source}) failed: {e}")
        return []


def to_decimal(obj):
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: to_decimal(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [to_decimal(v) for v in obj]
    return obj


def slug(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:50] if name else "challenge"


# ══════════════════════════════════════════════════════════════════════════════
# DATA GATHERING
# ══════════════════════════════════════════════════════════════════════════════

def gather_context():
    """Gather all context needed for challenge generation."""
    now = datetime.now(timezone.utc)
    end_date = now.strftime("%Y-%m-%d")
    start_date = (now - timedelta(days=LOOKBACK_DAYS - 1)).strftime("%Y-%m-%d")

    context = {}

    # 1. Journal entries (enriched fields only — themes, avoidance, emotions)
    journal_entries = query_range("notion", start_date, end_date)
    if journal_entries:
        journal_summary = []
        for entry in journal_entries:
            j = {
                "date": entry.get("sk", "").replace("DATE#", "").split("#")[0],
                "template": entry.get("template", ""),
            }
            # Enriched fields — the gold for challenge mining
            for field in ["enriched_themes", "enriched_avoidance_flags",
                          "enriched_growth_signals", "enriched_emotions",
                          "enriched_cognitive_patterns", "enriched_stress",
                          "enriched_mood", "enriched_energy",
                          "enriched_primary_defense", "enriched_defense_context"]:
                val = entry.get(field)
                if val:
                    j[field] = val
            # Raw text snippets for context (truncated)
            for field in ["win_of_the_day", "what_drained_me", "todays_intention",
                          "biggest_challenge", "what_would_i_change"]:
                val = entry.get(field, "")
                if val:
                    j[field] = val[:200]
            journal_summary.append(j)
        context["journal_14d"] = journal_summary
        logger.info(f"Journal: {len(journal_summary)} entries")

    # 2. Character sheet — latest pillar scores
    from boto3.dynamodb.conditions import Key
    try:
        cs_resp = table.query(
            KeyConditionExpression=Key("pk").eq(CHARACTER_PK) & Key("sk").begins_with("DATE#"),
            ScanIndexForward=False, Limit=1,
        )
        cs_items = d2f(cs_resp.get("Items", []))
        if cs_items:
            cs = cs_items[0]
            pillars = {}
            for p in ["sleep", "movement", "nutrition", "metabolic", "mind", "relationships", "consistency"]:
                pdata = cs.get(f"pillar_{p}", {})
                if pdata:
                    pillars[p] = {
                        "level": pdata.get("level"),
                        "tier": pdata.get("tier"),
                        "raw_score": pdata.get("raw_score"),
                        "level_score": pdata.get("level_score"),
                    }
            context["character"] = {
                "overall_level": cs.get("character_level"),
                "overall_tier": cs.get("character_tier"),
                "pillars": pillars,
            }
            logger.info(f"Character: level {cs.get('character_level')}")
    except Exception as e:
        logger.warning(f"Character sheet load failed: {e}")

    # 3. Habit scores — recent tier completion + missed T0 habits
    habit_items = query_range("habit_scores", start_date, end_date)
    if habit_items:
        missed_t0_freq = {}
        avg_t0_pct = []
        for h in habit_items:
            t0_pct = h.get("tier0_pct")
            if t0_pct is not None:
                avg_t0_pct.append(float(t0_pct))
            for missed in (h.get("missed_tier0") or []):
                missed_t0_freq[missed] = missed_t0_freq.get(missed, 0) + 1

        context["habits"] = {
            "avg_tier0_completion": round(sum(avg_t0_pct) / len(avg_t0_pct) * 100) if avg_t0_pct else None,
            "most_missed_tier0": sorted(missed_t0_freq.items(), key=lambda x: -x[1])[:5],
            "days_with_data": len(habit_items),
        }

        # Vice streaks
        latest_habit = habit_items[-1] if habit_items else {}
        vice_streaks = latest_habit.get("vice_streaks", {})
        if vice_streaks:
            context["habits"]["vice_streaks"] = vice_streaks
        logger.info(f"Habits: {len(habit_items)} days, T0 avg={context['habits'].get('avg_tier0_completion')}%")

    # 4. Confirmed hypotheses — candidates for challenge graduation
    try:
        hyp_resp = table.query(
            KeyConditionExpression=Key("pk").eq(HYPOTHESES_PK) & Key("sk").begins_with("HYPOTHESIS#"),
            ScanIndexForward=False,
        )
        confirmed = [
            d2f(h) for h in hyp_resp.get("Items", [])
            if h.get("status") in ("confirmed", "confirming") and h.get("check_count", 0) >= 2
        ]
        if confirmed:
            context["confirmed_hypotheses"] = [
                {"hypothesis": h.get("hypothesis"), "domains": h.get("domains"),
                 "actionable_if_confirmed": h.get("actionable_if_confirmed")}
                for h in confirmed[:5]
            ]
            logger.info(f"Confirmed hypotheses: {len(confirmed)}")
    except Exception as e:
        logger.warning(f"Hypothesis load failed: {e}")

    # 5. Existing challenges — for dedup
    try:
        ch_resp = table.query(
            KeyConditionExpression=Key("pk").eq(CHALLENGES_PK) & Key("sk").begins_with("CHALLENGE#"),
            ScanIndexForward=False,
        )
        existing = d2f(ch_resp.get("Items", []))
        context["existing_challenges"] = [
            {"name": c.get("name"), "status": c.get("status"), "domain": c.get("domain")}
            for c in existing
        ]
        logger.info(f"Existing challenges: {len(existing)}")
    except Exception as e:
        logger.warning(f"Challenge load failed: {e}")

    # 6. Basic health metrics for science scan context
    whoop_data = query_range("whoop", start_date, end_date)
    if whoop_data:
        avg_hrv = [w.get("hrv") for w in whoop_data if w.get("hrv")]
        avg_recovery = [w.get("recovery_score") for w in whoop_data if w.get("recovery_score")]
        context["health_snapshot"] = {
            "avg_hrv": round(sum(avg_hrv) / len(avg_hrv), 1) if avg_hrv else None,
            "avg_recovery": round(sum(avg_recovery) / len(avg_recovery), 1) if avg_recovery else None,
        }

    withings_data = query_range("withings", start_date, end_date)
    if withings_data:
        weights = [w.get("weight_lbs") for w in withings_data if w.get("weight_lbs")]
        if weights:
            context.setdefault("health_snapshot", {})["latest_weight"] = weights[-1]

    return context


# ══════════════════════════════════════════════════════════════════════════════
# AI GENERATION
# ══════════════════════════════════════════════════════════════════════════════

SYSTEM_PROMPT = """You are a challenge generation engine for a personal health platform.
Your job is to create 1-5 short-term challenge candidates based on the data provided.

CHALLENGE PHILOSOPHY:
- Challenges are ACTION, not science. No hypothesis required.
- Duration: 7-30 days (prefer 7 or 14 for first-timers)
- Each challenge targets a SPECIFIC weakness revealed by the data
- Challenges should be achievable but uncomfortable
- Every challenge must have a clear daily action and success criteria

SOURCES YOU CAN DRAW FROM:
1. JOURNAL MINING: Look for recurring avoidance flags, themes, defense mechanisms.
   If "late-night snacking" appears 4+ times → create a "No eating after 8pm" challenge.
   If "skipped workout" appears 3+ times → create a daily movement challenge.

2. DATA SIGNALS: Look at character sheet pillar scores.
   If a pillar is below level 30 or in "Foundation" tier → challenge for that domain.
   If Tier 0 habits are being missed → create a challenge around the most-missed habit.
   If vice streaks are short → create a streak extension challenge.

3. HYPOTHESIS GRADUATES: If a confirmed hypothesis has an actionable recommendation,
   convert it into a behavioural challenge.

4. SCIENCE SCAN: Based on the person's current health snapshot (weight, HRV, recovery),
   suggest 1 evidence-based challenge from sports science, nutrition, or longevity research.
   Cite the research basis briefly.

RULES:
- Do NOT create challenges that duplicate existing active/candidate challenges
- Each challenge must specify: name, description, source, source_detail, domain, difficulty, duration_days, protocol, success_criteria
- Domain must be one of: sleep, movement, nutrition, supplements, mental, social, discipline, metabolic, general
- Difficulty: easy (habit reinforcement), moderate (behaviour change), hard (significant discomfort)
- Return 0 challenges if there's insufficient data or no clear signal. Quality over quantity.

Respond ONLY with valid JSON:
{
  "challenges": [
    {
      "name": "Short punchy name",
      "description": "Why this challenge exists — the motivation from data",
      "source": "journal_mining|data_signal|hypothesis_graduate|science_scan",
      "source_detail": "Specific data trigger (e.g. 'avoidance_flag: late_night_snacking ×6 in 14d')",
      "domain": "movement",
      "difficulty": "moderate",
      "duration_days": 7,
      "protocol": "Exactly what to do each day",
      "success_criteria": "How to know you succeeded",
      "tags": ["tag1", "tag2"],
      "verification_method": "self_report|metric_auto|hybrid",
      "metric_targets": {}
    }
  ],
  "reasoning": "Brief explanation of why these challenges were chosen"
}"""


def generate_challenges(context, api_key):
    """Call Claude Sonnet to generate challenge candidates."""
    user_message = f"""Here is the current platform data for challenge generation.
Today is {datetime.now(timezone.utc).strftime('%Y-%m-%d')} ({datetime.now(timezone.utc).strftime('%A')}).

JOURNAL ENTRIES (14 days, enriched fields):
{json.dumps(context.get('journal_14d', []), indent=2, default=str)[:4000]}

CHARACTER SHEET:
{json.dumps(context.get('character', {}), indent=2, default=str)}

HABIT DATA:
{json.dumps(context.get('habits', {}), indent=2, default=str)}

CONFIRMED HYPOTHESES:
{json.dumps(context.get('confirmed_hypotheses', []), indent=2, default=str)}

HEALTH SNAPSHOT:
{json.dumps(context.get('health_snapshot', {}), indent=2, default=str)}

EXISTING CHALLENGES (do NOT duplicate):
{json.dumps(context.get('existing_challenges', []), indent=2, default=str)}

Generate 1-5 challenge candidates based on the strongest signals in this data.
If no clear signal exists, return 0 challenges. Quality over quantity."""

    payload = json.dumps({
        "model": AI_MODEL,
        "max_tokens": 2000,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": user_message}],
    }).encode()

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages", data=payload,
        headers={"Content-Type": "application/json", "x-api-key": api_key,
                 "anthropic-version": "2023-06-01"}, method="POST",
    )

    for attempt in range(1, 3):
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                resp = json.loads(r.read())
                raw = resp["content"][0]["text"].strip()
                # Strip markdown fences
                if raw.startswith("```"):
                    raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
                if raw.endswith("```"):
                    raw = raw[:-3]
                # AI-3 validation
                if _HAS_AI_VALIDATOR:
                    val_result = validate_ai_output(raw, AIOutputType.GENERIC)
                    if val_result.blocked:
                        logger.error("[AI-3] challenge generation blocked: %s", val_result.block_reason)
                        return None
                return json.loads(raw.strip())
        except urllib.error.HTTPError as e:
            logger.warning(f"Anthropic HTTP {e.code} attempt {attempt}")
            if attempt < 2 and e.code in (429, 529, 500, 502, 503, 504):
                time.sleep(5)
            else:
                raise
        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"Challenge parse error: {e}")
            return None


# ══════════════════════════════════════════════════════════════════════════════
# STORAGE
# ══════════════════════════════════════════════════════════════════════════════

def store_challenge(challenge: dict):
    """Write a challenge candidate to DynamoDB."""
    now = datetime.now(timezone.utc)
    name = challenge.get("name", "Unnamed Challenge")
    date_str = now.strftime("%Y-%m-%d")
    ch_slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:50]
    challenge_id = f"{ch_slug}_{date_str}"
    sk = f"CHALLENGE#{challenge_id}"

    # Dedup check
    existing = table.get_item(Key={"pk": CHALLENGES_PK, "sk": sk}).get("Item")
    if existing:
        logger.info(f"Skipping duplicate challenge: {challenge_id}")
        return None

    # Valid domains
    valid_domains = ["sleep", "movement", "nutrition", "supplements",
                     "mental", "social", "discipline", "metabolic", "general"]
    domain = challenge.get("domain", "general")
    if domain not in valid_domains:
        domain = "general"

    valid_diff = ["easy", "moderate", "hard"]
    difficulty = challenge.get("difficulty", "moderate")
    if difficulty not in valid_diff:
        difficulty = "moderate"

    valid_sources = ["journal_mining", "data_signal", "hypothesis_graduate", "science_scan"]
    source = challenge.get("source", "science_scan")
    if source not in valid_sources:
        source = "science_scan"

    item = {
        "pk":                   CHALLENGES_PK,
        "sk":                   sk,
        "challenge_id":         challenge_id,
        "name":                 name,
        "description":          challenge.get("description", ""),
        "source":               source,
        "source_detail":        challenge.get("source_detail", ""),
        "domain":               domain,
        "difficulty":           difficulty,
        "duration_days":        int(challenge.get("duration_days", 7)),
        "protocol":             challenge.get("protocol", ""),
        "success_criteria":     challenge.get("success_criteria", ""),
        "metric_targets":       challenge.get("metric_targets", {}),
        "status":               "candidate",
        "verification_method":  challenge.get("verification_method", "self_report"),
        "tags":                 challenge.get("tags", []),
        "daily_checkins":       [],
        "outcome":              "",
        "character_xp_awarded": 0,
        "badge_earned":         "",
        "related_experiment_id": "",
        "generated_by":         "challenge-generator",
        "generated_at":         now.strftime("%Y-%m-%dT%H:%M:%S"),
        "activated_at":         "",
        "completed_at":         "",
        "created_at":           now.strftime("%Y-%m-%dT%H:%M:%S"),
    }

    table.put_item(Item=to_decimal(item))
    logger.info(f"Stored challenge candidate: {challenge_id} (source={source})")
    return challenge_id


# ══════════════════════════════════════════════════════════════════════════════
# LAMBDA HANDLER
# ══════════════════════════════════════════════════════════════════════════════

def lambda_handler(event, context):
    """Weekly challenge generation pipeline."""
    logger.info("Challenge generator starting")
    start_time = time.time()

    try:
        # 1. Gather context
        ctx = gather_context()
        if not ctx:
            logger.warning("No context gathered — skipping generation")
            return {"status": "skipped", "reason": "no_data"}

        # Check minimum data availability
        journal_count = len(ctx.get("journal_14d", []))
        has_character = bool(ctx.get("character"))
        has_habits = bool(ctx.get("habits"))

        if journal_count < 3 and not has_character and not has_habits:
            logger.warning(f"Insufficient data: journal={journal_count}, character={has_character}, habits={has_habits}")
            return {"status": "skipped", "reason": "insufficient_data"}

        logger.info(f"Context gathered: journal={journal_count}, character={has_character}, habits={has_habits}")

        # 2. Get API key
        api_key = get_anthropic_key()

        # 3. Generate challenges
        result = generate_challenges(ctx, api_key)
        if not result or "challenges" not in result:
            logger.warning("No challenges generated or invalid response")
            return {"status": "completed", "generated": 0, "reason": "no_signal"}

        challenges = result["challenges"]
        reasoning = result.get("reasoning", "")
        logger.info(f"AI generated {len(challenges)} candidates. Reasoning: {reasoning[:200]}")

        # 4. Store candidates (with dedup)
        stored = 0
        stored_ids = []
        for ch in challenges[:MAX_NEW_CHALLENGES]:
            challenge_id = store_challenge(ch)
            if challenge_id:
                stored += 1
                stored_ids.append(challenge_id)

        elapsed = round(time.time() - start_time, 1)
        logger.info(f"Challenge generator complete: {stored}/{len(challenges)} stored in {elapsed}s")

        return {
            "status": "completed",
            "generated": len(challenges),
            "stored": stored,
            "challenge_ids": stored_ids,
            "reasoning": reasoning[:500],
            "elapsed_seconds": elapsed,
        }

    except Exception as e:
        logger.error(f"Challenge generator failed: {e}", exc_info=True)
        return {"status": "error", "error": str(e)}
