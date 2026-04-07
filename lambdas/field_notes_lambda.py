"""
Field Notes Generate Lambda — BL-04 Phase 1

Weekly lab notebook entry generator. Gathers 7-day data across all domains,
calls Claude Sonnet for synthesis, writes AI-generated notes to DynamoDB.

Trigger: EventBridge cron — Sunday 10am PT (18:00 UTC)
Can be manually invoked with {"manual_week": "2026-W13"}.

DynamoDB:
  PK = USER#matthew#SOURCE#field_notes
  SK = WEEK#YYYY-WNN

v1.0.0 — 2026-03-31
"""

import json
import logging
import os
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
USER_ID = os.environ.get("USER_ID", "matthew")
USER_PREFIX = f"USER#{USER_ID}#SOURCE#"
FN_PK = f"{USER_PREFIX}field_notes"
AI_SECRET_NAME = os.environ.get("AI_SECRET_NAME", "life-platform/ai-keys")
AI_MODEL = os.environ.get("AI_MODEL", "claude-sonnet-4-6")

dynamodb = boto3.resource("dynamodb", region_name="us-west-2")
table = dynamodb.Table(TABLE_NAME)

_api_key_cache = None


def _get_api_key():
    global _api_key_cache
    if _api_key_cache:
        return _api_key_cache
    sm = boto3.client("secretsmanager", region_name="us-west-2")
    resp = sm.get_secret_value(SecretId=AI_SECRET_NAME)
    secret = resp["SecretString"]
    try:
        parsed = json.loads(secret)
        _api_key_cache = parsed.get("anthropic_api_key", secret)
    except (json.JSONDecodeError, TypeError):
        _api_key_cache = secret
    return _api_key_cache


def _decimal_to_float(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, dict):
        return {k: _decimal_to_float(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_decimal_to_float(i) for i in obj]
    return obj


def get_iso_week(dt=None):
    if dt is None:
        dt = datetime.now(timezone.utc)
    year, week, _ = dt.isocalendar()
    return f"{year}-W{week:02d}"


def week_bounds(iso_week):
    year, week = int(iso_week[:4]), int(iso_week[6:])
    monday = datetime.fromisocalendar(year, week, 1)
    sunday = datetime.fromisocalendar(year, week, 7)
    return monday.strftime("%Y-%m-%d"), sunday.strftime("%Y-%m-%d")


def _query_source(source, start_date, end_date):
    pk = f"{USER_PREFIX}{source}"
    resp = table.query(
        KeyConditionExpression=Key("pk").eq(pk) & Key("sk").between(
            f"DATE#{start_date}", f"DATE#{end_date}"
        )
    )
    return _decimal_to_float(resp.get("Items", []))


def _latest_item(source):
    pk = f"{USER_PREFIX}{source}"
    resp = table.query(
        KeyConditionExpression=Key("pk").eq(pk),
        ScanIndexForward=False,
        Limit=1,
    )
    items = _decimal_to_float(resp.get("Items", []))
    return items[0] if items else None


def gather_week_data(start_date, end_date):
    """Gather data from all partitions for a given week."""
    data = {}

    # Sleep (Whoop)
    sleep_items = _query_source("whoop", start_date, end_date)
    if sleep_items:
        hrs = [i.get("sleep_duration_hours", 0) for i in sleep_items if i.get("sleep_duration_hours")]
        hrvs = [i.get("hrv", 0) for i in sleep_items if i.get("hrv")]
        data["sleep"] = {
            "nights": len(sleep_items),
            "avg_hours": round(sum(hrs) / len(hrs), 1) if hrs else None,
            "avg_hrv": round(sum(hrvs) / len(hrvs), 1) if hrvs else None,
        }

    # Nutrition (MacroFactor)
    nutrition = _query_source("macrofactor", start_date, end_date)
    if nutrition:
        cals = [float(i["total_calories_kcal"]) for i in nutrition if i.get("total_calories_kcal")]
        protein = [float(i["total_protein_g"]) for i in nutrition if i.get("total_protein_g")]
        data["nutrition"] = {
            "days_tracked": len(nutrition),
            "avg_calories": round(sum(cals) / len(cals)) if cals else None,
            "avg_protein_g": round(sum(protein) / len(protein), 1) if protein else None,
        }

    # Training (Strava)
    activities = _query_source("strava", start_date, end_date)
    if activities:
        total_min = sum(float(a.get("moving_time_seconds") or a.get("elapsed_time_seconds") or 0) / 60 for a in activities)
        data["training"] = {
            "sessions": len(activities),
            "total_minutes": round(total_min),
        }

    # Weight (Withings)
    weights = _query_source("withings", start_date, end_date)
    if weights:
        wt = [float(w.get("weight_lbs", 0)) for w in weights if w.get("weight_lbs")]
        if wt:
            data["weight"] = {
                "readings": len(wt),
                "start": wt[0],
                "end": wt[-1],
                "change": round(wt[-1] - wt[0], 1),
            }

    # Habits (habit_scores)
    habits = _query_source("habit_scores", start_date, end_date)
    if habits:
        completion_rates = [float(h.get("completion_rate", 0)) for h in habits if h.get("completion_rate") is not None]
        data["habits"] = {
            "days_scored": len(habits),
            "avg_completion": round(sum(completion_rates) / len(completion_rates) * 100) if completion_rates else None,
        }

    # Journal (Notion)
    journal_pk = f"{USER_PREFIX}notion"
    j_resp = table.query(
        KeyConditionExpression=Key("pk").eq(journal_pk) & Key("sk").between(
            f"DATE#{start_date}#journal", f"DATE#{end_date}#journal#~"
        ),
    )
    journal_items = _decimal_to_float(j_resp.get("Items", []))
    journal_items = [j for j in journal_items if "#journal#" in j.get("sk", "")]
    if journal_items:
        data["journal"] = {"entry_count": len(journal_items)}

    # Character sheet (latest)
    cs = _latest_item("character_sheet")
    if cs:
        data["character"] = {
            "level": cs.get("level"),
            "day_grade": cs.get("day_grade"),
        }

    # Mood (State of Mind)
    mood_items = _query_source("state_of_mind", start_date, end_date)
    if mood_items:
        valences = [float(m.get("valence", 0)) for m in mood_items if m.get("valence") is not None]
        data["mood"] = {
            "readings": len(mood_items),
            "avg_valence": round(sum(valences) / len(valences), 2) if valences else None,
        }

    return data


def get_prior_notes(current_week, count=4):
    """Get prior weeks' field notes for context."""
    year, week_num = int(current_week[:4]), int(current_week[6:])
    prior_weeks = []
    for i in range(1, count + 1):
        dt = datetime.fromisocalendar(year, week_num, 1) - timedelta(weeks=i)
        pw = get_iso_week(dt)
        prior_weeks.append(pw)

    notes = []
    for pw in prior_weeks:
        resp = table.get_item(Key={"pk": FN_PK, "sk": f"WEEK#{pw}"})
        item = _decimal_to_float(resp.get("Item"))
        if item and item.get("ai_present"):
            notes.append({
                "week": pw,
                "present": item.get("ai_present", ""),
                "tone": item.get("ai_tone", ""),
            })
    return notes


def build_prompt(iso_week, data, prior_notes):
    start, end = week_bounds(iso_week)

    data_section = json.dumps(data, indent=2, default=str)

    prior_section = ""
    if prior_notes:
        prior_section = "\n\nPrior weeks' notes for context:\n"
        for n in prior_notes:
            prior_section += f"\n--- {n['week']} (tone: {n['tone']}) ---\n{n['present'][:500]}\n"

    return f"""You are the AI health advisor for Matthew's personal health platform (averagejoematt.com).
You are writing the weekly Field Notes — a lab notebook entry that synthesizes all data from the week.

This is week {iso_week} ({start} to {end}).

Here is all the data collected this week:
{data_section}
{prior_section}

Write three distinct sections. Respond with ONLY a JSON object (no other text):

{{
  "ai_present": "2-3 paragraphs. What happened this week. Be specific — reference actual numbers. This is the 'present signal' section. Honest, direct, no cheerleading. If data is sparse, say so.",
  "ai_cautionary": "1-2 paragraphs. What concerns you. Patterns that deserve attention. If nothing concerning, write about what to watch for. Optional — omit this field if genuinely nothing to flag.",
  "ai_affirming": "1-2 paragraphs. What's going well. Bright spots in the data. Don't force positivity — only affirm what the data actually supports. Optional — omit if nothing stands out.",
  "ai_tone": "one of: affirming, cautionary, urgent, mixed"
}}

Requirements:
- Write in first person as the platform's AI advisor
- Be honest and direct — Matthew chose radical transparency
- Reference specific numbers from the data
- Do NOT use bullet points — flowing prose only
- If a data domain has no entries, acknowledge the gap briefly
- Tone should match the data: don't be affirming when the data is concerning"""


def generate_field_notes(iso_week):
    start, end = week_bounds(iso_week)
    logger.info(f"Generating field notes for {iso_week} ({start} to {end})")

    # Check if already exists
    existing = table.get_item(Key={"pk": FN_PK, "sk": f"WEEK#{iso_week}"}).get("Item")
    if existing and existing.get("ai_generated_at"):
        logger.info(f"Field notes for {iso_week} already exist, skipping")
        return {"status": "already_exists", "week": iso_week}

    data = gather_week_data(start, end)
    prior_notes = get_prior_notes(iso_week)
    prompt = build_prompt(iso_week, data, prior_notes)

    api_key = _get_api_key()
    req_body = json.dumps({
        "model": AI_MODEL,
        "max_tokens": 2000,
        "messages": [{"role": "user", "content": prompt}],
    })

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=req_body.encode(),
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
    )

    with urllib.request.urlopen(req, timeout=60) as resp:
        result = json.loads(resp.read())

    text = "".join(b["text"] for b in result.get("content", []) if b.get("type") == "text")

    # Parse JSON response
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    analysis = json.loads(text)
    now = datetime.now(timezone.utc).isoformat()

    item = {
        "pk": FN_PK,
        "sk": f"WEEK#{iso_week}",
        "week": iso_week,
        "ai_present": analysis.get("ai_present", ""),
        "ai_tone": analysis.get("ai_tone", "mixed"),
        "ai_generated_at": now,
    }
    if analysis.get("ai_cautionary"):
        item["ai_cautionary"] = analysis["ai_cautionary"]
    if analysis.get("ai_affirming"):
        item["ai_affirming"] = analysis["ai_affirming"]

    table.put_item(Item=item)
    logger.info(f"Wrote field notes for {iso_week}: {len(item.get('ai_present', ''))} chars")

    return {"status": "ok", "week": iso_week, "chars": len(item.get("ai_present", ""))}


def lambda_handler(event, context):
    manual_week = event.get("manual_week")
    if manual_week:
        iso_week = manual_week
    else:
        # Default: generate for the week that just ended (previous week)
        last_sunday = datetime.now(timezone.utc) - timedelta(days=1)
        iso_week = get_iso_week(last_sunday)

    try:
        result = generate_field_notes(iso_week)
        return {"statusCode": 200, "body": json.dumps(result)}
    except Exception as e:
        logger.error(f"Failed to generate field notes for {iso_week}: {e}")
        return {"statusCode": 500, "body": json.dumps({"error": str(e), "week": iso_week})}
