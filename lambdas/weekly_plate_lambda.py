"""
The Weekly Plate Lambda — v1.0.0
Fires Friday 6:00 PM PT (Saturday 02:00 UTC via EventBridge).

A magazine-style Friday evening email about food — personalized from actual
MacroFactor data. Designed to be a fun couch read that ends with an actionable
grocery list for the weekend shop at Metropolitan Market.

Sections:
  1. This Week on Your Plate — narrative week recap
  2. Your Greatest Hits — most frequent meals/ingredients
  3. Try This — 2-3 recipe riffs on what you already eat
  4. The Wildcard — one ingredient you haven't had recently
  5. The Grocery Run — copy-paste grocery list by store section

Data sources: MacroFactor (14d food logs), Withings (30d weight), Profile (targets).

AI: Sonnet 4.5, temperature 0.6 for creative warmth.
Cost: ~$0.04/week.
"""

import json
import os
import logging
import time
import boto3
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from collections import Counter, defaultdict
import re

_logger_std = logging.getLogger()
_logger_std.setLevel(logging.INFO)

REGION     = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
USER_ID    = os.environ.get("USER_ID", "matthew")
RECIPIENT  = os.environ["EMAIL_RECIPIENT"]
SENDER     = os.environ["EMAIL_SENDER"]

USER_PREFIX = f"USER#{USER_ID}#SOURCE#"

dynamodb   = boto3.resource("dynamodb", region_name=REGION)
table      = dynamodb.Table(TABLE_NAME)
ses        = boto3.client("sesv2", region_name=REGION)
secrets    = boto3.client("secretsmanager", region_name=REGION)
s3_client  = boto3.client("s3", region_name=REGION)
S3_BUCKET  = os.environ["S3_BUCKET"]

USER_PREFIX_MEMORY = f"USER#{USER_ID}#SOURCE#platform_memory"
MAX_PLATE_HISTORY = 4  # past plates to inject for anti-repeat context

# Board of Directors config loader (optional — for voice customization)
try:
    import board_loader
    _HAS_BOARD_LOADER = True
except ImportError:
    _HAS_BOARD_LOADER = False

try:
    import insight_writer
    insight_writer.init(table, USER_ID)
    _HAS_INSIGHT_WRITER = True
except ImportError:
    _HAS_INSIGHT_WRITER = False

# AI-3: Output validation
try:
    from ai_output_validator import validate_ai_output, AIOutputType
    _HAS_AI_VALIDATOR = True
except ImportError:
    _HAS_AI_VALIDATOR = False

# OBS-1: Structured logger
try:
    from platform_logger import get_logger
    logger = get_logger("weekly-plate")
except ImportError:
    import logging as _log
    logger = _log.getLogger("weekly-plate")
    logger.setLevel(_log.INFO)


# ══════════════════════════════════════════════════════════════════════════════
# PLATE MEMORY (P1) — load/store plate history to prevent weekly repeats
# ══════════════════════════════════════════════════════════════════════════════

def load_plate_history(today_str):
    """Load last MAX_PLATE_HISTORY weekly plate summaries from DynamoDB platform_memory."""
    try:
        start_date = (datetime.strptime(today_str, "%Y-%m-%d") - timedelta(days=70)).strftime("%Y-%m-%d")
        resp = table.query(
            KeyConditionExpression="pk = :pk AND sk BETWEEN :s AND :e",
            ExpressionAttributeValues={
                ":pk": USER_PREFIX_MEMORY,
                ":s": f"MEMORY#weekly_plate#{start_date}",
                ":e": f"MEMORY#weekly_plate#{today_str}",
            },
            ScanIndexForward=False,
            Limit=MAX_PLATE_HISTORY,
        )
        items = [d2f(i) for i in resp.get("Items", [])]
        logger.info(f"Plate history: {len(items)} past plates loaded")
        return items
    except Exception as e:
        logger.warning(f"load_plate_history failed: {e}")
        return []


def build_plate_history_context(history):
    """Format plate history as anti-repeat block for the AI."""
    if not history:
        return ""
    lines = ["PREVIOUS WEEKLY PLATE EDITIONS (anti-repeat — you MUST avoid these):"]
    for i, rec in enumerate(history, 1):
        date_str = rec.get("plate_date", "?")
        top_foods = rec.get("top_foods", [])
        wildcard = rec.get("wildcard", "")
        recipes = rec.get("recipes", [])
        lines.append(f"  Week -{i} ({date_str}):")
        if top_foods:
            lines.append(f"    Greatest Hits featured: {', '.join(top_foods[:6])}")
        if wildcard:
            lines.append(f"    Wildcard was: {wildcard}  ← DO NOT REPEAT THIS")
        if recipes:
            lines.append(f"    Recipes suggested: {', '.join(recipes[:4])}  ← DO NOT REPEAT THESE")
    lines.append("")
    lines.append("ANTI-REPEAT RULES:")
    lines.append("  • The Wildcard MUST be a different ingredient than any previous wildcard.")
    lines.append("  • Recipes must not repeat names or be obvious variations of past suggestions.")
    lines.append("  • Greatest Hits should reflect actual data frequency — if same foods recur, add new angle.")
    return "\n".join(lines)


def extract_plate_summary(ai_content, top_food_names, date_str):
    """Extract a condensed summary from the AI plate HTML for storage."""
    summary = {
        "plate_date": date_str,
        "top_foods": top_food_names[:8],
        "wildcard": "",
        "recipes": [],
    }
    # Extract wildcard: look for text following Wildcard section header
    wc_match = re.search(r'(?i)wildcard[^>]*>[^<]{0,30}<[^>]+>([^<]{8,80})', ai_content)
    if not wc_match:
        wc_match = re.search(r'(?i)wildcard[^<>]*>\s*([A-Z][a-z][^<]{5,60})', ai_content)
    if wc_match:
        summary["wildcard"] = wc_match.group(1).strip()[:80]
    # Extract recipe names: bold/heading text in Try This area, capitalized multi-word
    recipe_matches = re.findall(r'(?:font-weight:\s*[6-9]00[^>]*>|<strong>|<b>)([A-Z][^<]{6,60})<', ai_content)
    skip = {"try this", "greatest hits", "the wildcard", "grocery run", "this week on",
             "life platform", "weekly plate", "section", "the grocery run", "your greatest hits"}
    recipes = []
    for name in recipe_matches:
        if name.lower().strip() not in skip and len(name.strip()) > 8 and len(recipes) < 5:
            recipes.append(name.strip())
    summary["recipes"] = recipes
    return summary


def store_plate_summary(summary, today_str):
    """Store condensed plate summary to platform_memory DDB partition."""
    try:
        item = {
            "pk": USER_PREFIX_MEMORY,
            "sk": f"MEMORY#weekly_plate#{today_str}",
            "category": "weekly_plate",
            "plate_date": summary.get("plate_date", today_str),
            "stored_at": datetime.now(timezone.utc).isoformat(),
        }
        if summary.get("top_foods"):
            item["top_foods"] = summary["top_foods"]
        if summary.get("wildcard"):
            item["wildcard"] = summary["wildcard"]
        if summary.get("recipes"):
            item["recipes"] = summary["recipes"]
        table.put_item(Item=item)
        logger.info(f"Plate summary stored: {today_str} | wildcard='{summary.get('wildcard', '')}' | recipes={len(summary.get('recipes', []))}")
    except Exception as e:
        logger.warning(f"store_plate_summary failed (non-fatal): {e}")


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def get_anthropic_key():
    secret_name = os.environ.get("ANTHROPIC_SECRET", "life-platform/ai-keys")
    secret = secrets.get_secret_value(SecretId=secret_name)
    return json.loads(secret["SecretString"])["anthropic_api_key"]

def d2f(obj):
    if isinstance(obj, list):    return [d2f(i) for i in obj]
    if isinstance(obj, dict):    return {k: d2f(v) for k, v in obj.items()}
    if isinstance(obj, Decimal): return float(obj)
    return obj

def safe_float(rec, field, default=None):
    if rec and field in rec:
        try: return float(rec[field])
        except Exception: return default
    return default

def query_range(source, start_date, end_date):
    pk = f"USER#{USER_ID}#SOURCE#{source}"
    records = {}
    kwargs = {
        "KeyConditionExpression": "pk = :pk AND sk BETWEEN :sk1 AND :sk2",
        "ExpressionAttributeValues": {
            ":pk": pk,
            ":sk1": f"DATE#{start_date}",
            ":sk2": f"DATE#{end_date}",
        },
    }
    while True:
        resp = table.query(**kwargs)
        for item in resp.get("Items", []):
            date_str = item["sk"].replace("DATE#", "")
            records[date_str] = d2f(item)
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    return records

def fetch_profile():
    """Load profile from DynamoDB (same as daily brief)."""
    try:
        r = table.get_item(Key={"pk": f"USER#{USER_ID}", "sk": "PROFILE#v1"})
        return d2f(r.get("Item", {}))
    except Exception as e:
        logger.warning(f"Profile fetch failed: {e}")
        return {}


# ══════════════════════════════════════════════════════════════════════════════
# DATA GATHERING
# ══════════════════════════════════════════════════════════════════════════════

def gather_data():
    """Gather 14 days of food logs + 30 days of weight data."""
    today = datetime.now(timezone.utc).date()
    end_date = (today - timedelta(days=1)).isoformat()
    start_14d = (today - timedelta(days=14)).isoformat()
    weight_start = (today - timedelta(days=30)).isoformat()

    logger.info(f"Data window: {start_14d} -> {end_date}")

    profile = fetch_profile()
    if not profile:
        logger.error("No profile found")
        return None

    mf_data = query_range("macrofactor", start_14d, end_date)
    logger.info(f"MacroFactor: {len(mf_data)} days")

    withings = query_range("withings", weight_start, end_date)
    logger.info(f"Withings: {len(withings)} days")

    return {
        "macrofactor": mf_data,
        "withings": withings,
        "profile": profile,
        "dates": {"start": start_14d, "end": end_date},
    }


# ══════════════════════════════════════════════════════════════════════════════
# EXTRACT & ANALYZE
# ══════════════════════════════════════════════════════════════════════════════

def extract_food_data(mf_data):
    """Extract all food items and daily summaries from 14 days of MacroFactor data."""
    days = []
    all_foods = []
    for date_str in sorted(mf_data.keys()):
        rec = mf_data[date_str]
        food_log = rec.get("food_log", [])
        day_foods = []
        for item in food_log:
            name = item.get("food_name", "unknown")
            # Skip supplements — we're interested in real food
            if any(s in name.lower() for s in ("supplement", "vitamin", "fish oil", "creatine", "magnesium")):
                continue
            food = {
                "name": name, "time": item.get("time", "?"),
                "cal": safe_float(item, "calories_kcal", 0),
                "protein_g": safe_float(item, "protein_g", 0),
                "carbs_g": safe_float(item, "carbs_g", 0),
                "fat_g": safe_float(item, "fat_g", 0),
                "fiber_g": safe_float(item, "fiber_g"),
            }
            day_foods.append(food)
            all_foods.append(food)

        day = {
            "date": date_str,
            "total_calories": safe_float(rec, "total_calories_kcal"),
            "total_protein_g": safe_float(rec, "total_protein_g"),
            "total_carbs_g": safe_float(rec, "total_carbs_g"),
            "total_fat_g": safe_float(rec, "total_fat_g"),
            "total_fiber_g": safe_float(rec, "total_fiber_g"),
            "foods": day_foods,
        }
        days.append(day)
    return days, all_foods


def analyze_food_patterns(all_foods):
    """Find most common ingredients and meal patterns."""
    name_counter = Counter()
    for f in all_foods:
        # Normalize food names for pattern matching
        name_lower = f["name"].lower().strip()
        name_counter[name_lower] += 1

    top_foods = name_counter.most_common(20)
    return {"top_foods": [{"name": n, "count": c} for n, c in top_foods]}


def extract_weight_trend(withings_data):
    """Extract weight trend from Withings data."""
    weights = []
    for date_str in sorted(withings_data.keys()):
        rec = withings_data[date_str]
        w = safe_float(rec, "weight_lbs") or safe_float(rec, "weight_lb")
        if w:
            weights.append({"date": date_str, "weight_lbs": w})
    if not weights:
        return None
    latest = weights[-1]["weight_lbs"]
    earliest = weights[0]["weight_lbs"]
    # 7-day trend
    week_weights = [w for w in weights if w["date"] >= (datetime.now(timezone.utc).date() - timedelta(days=7)).isoformat()]
    week_change = round(week_weights[-1]["weight_lbs"] - week_weights[0]["weight_lbs"], 1) if len(week_weights) >= 2 else None
    return {
        "latest_weight_lbs": latest,
        "change_30d_lbs": round(latest - earliest, 1),
        "change_7d_lbs": week_change,
        "measurements": len(weights),
    }


def build_weight_context(withings_data, profile):
    """Build human-readable weight context for AI."""
    weight = extract_weight_trend(withings_data)
    start_w = profile.get("journey_start_weight_lbs", 307)
    goal_w = profile.get("goal_weight_lbs", 185)
    if weight:
        current = weight["latest_weight_lbs"]
        lost = round(start_w - current, 1)
        remaining = round(current - goal_w, 1)
        trend_7d = weight.get("change_7d_lbs")
        trend_str = f", {'+' if trend_7d > 0 else ''}{trend_7d} lbs this week" if trend_7d is not None else ""
        return f"Currently {current:.1f} lbs (started {start_w}, goal {goal_w} — {lost} lost, {remaining} to go{trend_str})"
    return f"Goal: {start_w} -> {goal_w} lbs"


# ══════════════════════════════════════════════════════════════════════════════
# AI PROMPT
# ══════════════════════════════════════════════════════════════════════════════

SYSTEM_PROMPT = """You are the writer of "The Weekly Plate" — a personalized Friday evening food email for Matthew's Life Platform. Think of yourself as a food-obsessed friend who also happens to know his exact macros, weight goals, and what's in his fridge.

## ABOUT MATTHEW
{weight_context}
Targets: {calorie_target} cal/day, {protein_target_g}g protein, 16:8 IF (eating window ~11am-7pm).
Shops at: Metropolitan Market in Seattle (premium grocer — think quality proteins, good produce, specialty items).
Cooking style: Mexican, Asian, simple protein+sides. Weeknight meals under 30 min.

## YOUR VOICE
Warm, fun, conversational — like a food magazine column written just for him. Brittany (his wife) should enjoy reading this too, even though the macros are his. Not clinical. Not preachy. Occasionally playful. You genuinely love food and it shows.

## WRITE EXACTLY THESE 5 SECTIONS (in HTML):

### Section 1: "This Week on Your Plate"
3-4 sentence narrative of how the week went food-wise. Reference actual meals and patterns from the data. Mention weight trend naturally (not as a report — weave it in). Set the tone for the whole email.

### Section 2: "Your Greatest Hits"
Identify 3-4 most frequent food items from the last 14 days using ONLY the exact food names in the data. Celebrate what's working — these are his go-to moves. Give each one a quick note: why it works (macro-wise), or a small tweak that'd make it even better. Format as short cards.

CRITICAL: Only reference foods by names that literally appear in the food_log data. Do NOT combine separate food items into a single "meal" or infer that foods were eaten together unless they share the exact same date AND time. Do NOT invent side dishes, accompaniments, or pairings that aren't explicitly logged. If the data shows "Lean Ground Beef (93%)" logged alone, present it alone — do not add quinoa, rice, spinach, or anything else.

### Section 3: "Try This"
2-3 recipe ideas that are RIFFS ON WHAT HE ALREADY EATS. Not random internet recipes. Take his actual ingredients and favorite flavor profiles, then suggest a twist. Each recipe gets:
- A fun name
- 2-3 sentence description of what it is and why it's a good fit
- Approximate macros per serving (cal/P/C/F)
- Difficulty: "weeknight easy" or "weekend project"
- Key ingredients list (short)

IMPORTANT: These must feel like natural extensions of his existing cooking, not aspirational Pinterest meals. If he eats a lot of ground turkey, suggest a new way to cook ground turkey.

### Section 4: "The Wildcard"
ONE ingredient or food category he hasn't logged in the last 14 days (or barely has) that would genuinely benefit him. Explain WHY in 2-3 sentences — connect it to his goals, his macros, or just to breaking monotony. Suggest a specific product to look for at Met Market.

### Section 5: "The Grocery Run"
A clean, practical grocery list organized by store section:
- 🥩 Protein
- 🥬 Produce
- 🧀 Dairy & Eggs
- 🫙 Pantry & Staples
- ❄️ Frozen (if applicable)

Each item gets a brief parenthetical: (for the köfte) or (your staple — running low?). Include both:
- Ingredients needed for the recipes in Section 3
- His regular staples based on what he's been eating

This list should be SCREENSHOT-ABLE. Someone should be able to walk into Met Market with this list.

## FORMAT RULES
- Write clean HTML with inline styles
- Overall background: #1a1a2e. Text: #e0e0e0. Accent: #f59e0b (warm gold)
- Section headers: white text, 17px, font-weight 700, with an emoji prefix
- Recipe cards: background #16213e, border-radius 10px, padding 16px, margin-bottom 12px
- Greatest Hits cards: same but with a subtle left border in #4cc9f0
- Grocery list: clean, readable, with section emoji headers. NO checkboxes — just clean text with bullet points
- The Wildcard: a standout card with left border #f59e0b and slightly different background
- Keep total length ~1200-1800 words. Readable in 5 minutes.
- No <html>/<head>/<body> tags — just the content divs.
- Mobile-friendly: max-width 600px, centered.
- Footer: "The Weekly Plate · Life Platform · Friday Edition"

## CRITICAL — HALLUCINATION PREVENTION
- Every food reference must come from his ACTUAL food log data. Don't invent meals he didn't eat.
- In Greatest Hits and This Week sections: ONLY use food names that literally appear in the food_log data. Never fabricate pairings, side dishes, or meal compositions.
- If a food item was logged standalone (e.g., just "Lean Ground Beef"), describe it standalone. Do NOT assume it was served with rice, vegetables, or anything else unless those items appear in the same meal (same date + same time).
- Recipe suggestions (Try This section) CAN be creative — that's where you suggest new ideas. But Greatest Hits and This Week must be 100% grounded in logged data.
- The Wildcard must be something genuinely ABSENT from his recent logs.
- Grocery list must be practical for a single person's weekend shop (not 47 items).
- This is a FRIDAY EVENING email — the vibe is relaxed, looking-forward-to-the-weekend energy."""


def build_user_message(data):
    """Build the data payload for the AI."""
    days, all_foods = extract_food_data(data["macrofactor"])
    patterns = analyze_food_patterns(all_foods)
    weight = extract_weight_trend(data["withings"])

    payload = {
        "food_log_14_days": days,
        "food_frequency": patterns,
        "weight_trend": weight,
        "profile_targets": {
            "calorie_target": data["profile"].get("calorie_target", 1800),
            "protein_target_g": data["profile"].get("protein_target_g", 190),
            "goal_weight_lbs": data["profile"].get("goal_weight_lbs", 185),
            "eating_window": "11am-7pm (16:8 IF)",
        },
    }
    return json.dumps(payload, indent=2, default=str)


def build_system_prompt(profile, withings_data):
    """Render the system prompt with dynamic weight context."""
    weight_ctx = build_weight_context(withings_data, profile)
    cal = profile.get("calorie_target", 1800)
    pro = profile.get("protein_target_g", 190)
    return SYSTEM_PROMPT.format(
        weight_context=weight_ctx,
        calorie_target=cal,
        protein_target_g=pro,
    )


# ══════════════════════════════════════════════════════════════════════════════
# AI CALL
# ══════════════════════════════════════════════════════════════════════════════

def call_anthropic(system_prompt, user_message, api_key):
    # Delegates to retry_utils for exponential backoff + CloudWatch metrics (P1.8/P1.9)
    import retry_utils
    return retry_utils.call_anthropic_api(
        prompt=user_message,
        api_key=api_key,
        max_tokens=4096,
        system=system_prompt,
        temperature=0.6,
        timeout=120,
    )


# ══════════════════════════════════════════════════════════════════════════════
# HTML EMAIL
# ══════════════════════════════════════════════════════════════════════════════

def build_email_html(ai_content, dates, weight_info):
    try:
        dt_end = datetime.strptime(dates["end"], "%Y-%m-%d")
        week_label = dt_end.strftime("%B %-d, %Y")
    except Exception:
        week_label = dates["end"]

    weight_line = ""
    if weight_info:
        w = weight_info["latest_weight_lbs"]
        delta_7d = weight_info.get("change_7d_lbs")
        if delta_7d is not None:
            arrow = "↓" if delta_7d < 0 else "↑" if delta_7d > 0 else "→"
            weight_line = f'<div style="color:#9ca3af;font-size:13px;margin-top:4px;">{w:.1f} lbs · {arrow} {abs(delta_7d):.1f} this week</div>'
        else:
            weight_line = f'<div style="color:#9ca3af;font-size:13px;margin-top:4px;">{w:.1f} lbs</div>'

    return f'''<div style="max-width:600px;margin:0 auto;background:#1a1a2e;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;padding:20px;color:#e0e0e0;">
    <div style="text-align:center;margin-bottom:24px;">
        <div style="font-size:11px;letter-spacing:2px;color:#f59e0b;font-weight:600;margin-bottom:4px;">LIFE PLATFORM</div>
        <div style="font-size:22px;font-weight:700;color:#ffffff;">🍽️ The Weekly Plate</div>
        <div style="color:#9ca3af;font-size:13px;margin-top:4px;">Friday · {week_label}</div>
        {weight_line}
    </div>
    {ai_content}
    <div style="text-align:center;padding:16px 0;border-top:1px solid #2a2d4a;margin-top:24px;">
        <div style="color:#6b7280;font-size:11px;">The Weekly Plate · Life Platform · Friday Edition</div>
        <div style="color:#9ca3af;font-size:9px;margin-top:6px;">⚕️ Personal health tracking only &mdash; not medical advice. Consult a qualified healthcare professional before making changes to your diet or supplement regimen.</div>
    </div>
</div>'''


# ══════════════════════════════════════════════════════════════════════════════
# HANDLER
# ══════════════════════════════════════════════════════════════════════════════


def record_email_send(table, lambda_name):
    """Write a completion record so the status page can track last send."""
    import time as _time
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        table.put_item(Item={
            "pk": f"USER#matthew#SOURCE#email_log#{lambda_name}",
            "sk": f"DATE#{today}",
            "sent_at": datetime.now(timezone.utc).isoformat(),
            "status": "success",
            "ttl": int(_time.time()) + 86400 * 90
        })
    except Exception as e:
        print(f"[status-tracking] Non-fatal write failure: {e}")


def lambda_handler(event, context):
    logger.info("The Weekly Plate v1.0.0 starting...")

    data = gather_data()
    if not data:
        return {"statusCode": 500, "body": "Failed to gather data"}

    dates = data["dates"]
    profile = data["profile"]

    days, all_foods = extract_food_data(data["macrofactor"])
    if not days:
        logger.error("No MacroFactor data in last 14 days")
        return {"statusCode": 500, "body": "No food data"}

    logger.info(f"Food data: {len(days)} days, {len(all_foods)} food items")

    # P1: Load plate history to prevent repeats
    today_str = datetime.now(timezone.utc).date().isoformat()
    plate_history = load_plate_history(today_str)
    history_context = build_plate_history_context(plate_history)

    user_message = build_user_message(data)
    if history_context:
        user_message = history_context + "\n\n" + user_message
    logger.info(f"Prompt size: {len(user_message)} chars | plate history: {len(plate_history)} weeks loaded")

    system_prompt = build_system_prompt(profile, data["withings"])

    # IC-16: Progressive context — nutrition insights for meal planning
    if _HAS_INSIGHT_WRITER:
        try:
            prev_ctx = insight_writer.build_insights_context(
                days=14, pillars=["nutrition"], max_items=3,
                label="RECENT NUTRITION INSIGHTS (context for meal planning)")
            if prev_ctx:
                user_message = prev_ctx + "\n\n" + user_message
        except Exception as e:
            print(f"[WARN] IC-16 failed: {e}")

    api_key = get_anthropic_key()
    logger.info("Calling Sonnet for The Weekly Plate...")
    try:
        ai_content = call_anthropic(system_prompt, user_message, api_key)
    except Exception as e:
        logger.error(f"Anthropic failed: {e}")
        ai_content = ('<div style="background:#16213e;border-radius:8px;padding:20px;color:#e0e0e0;">'
                      'AI content unavailable this week. Check CloudWatch logs.</div>')

    # AI-3: Validate output before rendering
    if _HAS_AI_VALIDATOR and ai_content and "unavailable" not in ai_content[:50]:
        _val = validate_ai_output(ai_content, AIOutputType.NUTRITION_COACH)
        if _val.blocked:
            logger.error(f"[AI-3] Weekly Plate output BLOCKED: {_val.block_reason}")
            ai_content = _val.safe_fallback or '<div style="background:#16213e;border-radius:8px;padding:20px;color:#e0e0e0;">AI content unavailable this week. Check CloudWatch logs.</div>'
        elif _val.warnings:
            logger.warning(f"[AI-3] Weekly Plate warnings: {_val.warnings}")

    weight_info = extract_weight_trend(data["withings"])
    html = build_email_html(ai_content, dates, weight_info)

    # P1: Store plate summary for future anti-repeat context
    try:
        _, all_foods_store = extract_food_data(data["macrofactor"])
        patterns_store = analyze_food_patterns(all_foods_store)
        top_food_names = [f["name"] for f in patterns_store.get("top_foods", [])[:8]]
        plate_summary = extract_plate_summary(ai_content, top_food_names, dates["end"])
        store_plate_summary(plate_summary, today_str)
    except Exception as e:
        logger.warning(f"Plate summary storage failed (non-fatal): {e}")

    try:
        dt_end_dt = datetime.strptime(dates["end"], "%Y-%m-%d")
        subject_date = dt_end_dt.strftime("%b %-d")
    except Exception:
        subject_date = dates["end"]
    subject = f"🍽️ The Weekly Plate · {subject_date}"

    ses.send_email(
        FromEmailAddress=SENDER,
        Destination={"ToAddresses": [RECIPIENT]},
        Content={"Simple": {
            "Subject": {"Data": subject, "Charset": "UTF-8"},
            "Body":    {"Html": {"Data": html, "Charset": "UTF-8"}},
        }},
    )
    logger.info(f"Sent: {subject}")

    # IC-15: Persist plate insight
    if _HAS_INSIGHT_WRITER and ai_content and "unavailable" not in ai_content[:50]:
        try:
            insight_writer.write_insight(
                digest_type="weekly_plate", insight_type="coaching",
                text=ai_content[:800], pillars=["nutrition"],
                data_sources=["macrofactor"], tags=["plate", "meal_plan", "nutrition"],
                confidence="medium", actionable=True, date=dates.get("end", ""))
            print("[INFO] IC-15: plate insight persisted")
        except Exception as e:
            print(f"[WARN] IC-15 failed: {e}")

    record_email_send(table, "weekly_plate")
    return {"statusCode": 200, "body": f"The Weekly Plate sent: {subject}"}
