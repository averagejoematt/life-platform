"""
Nutrition Review Lambda — v1.1.0 (Board Centralization)
Fires Saturday 9:00 AM PT (17:00 UTC via EventBridge).

Weekly nutrition analysis email with expert panel:
  - Layne Norton: Macros, protein, adherence
  - Rhonda Patrick: Micronutrients, genome crossover
  - Peter Attia: Metabolic health, CGM, body composition
  - Unified: Top 3 priorities, grocery list, meal ideas, supplement check

Data sources: MacroFactor (7d food logs), Withings (30d weight), Strava (7d training),
Apple Health CGM (7d), Genome (static), Labs (latest), DEXA (latest), Supplements (7d),
Profile (targets).

v1.1.0: Expert panel prompt dynamically built from s3://matthew-life-platform/config/board_of_directors.json
        Falls back to hardcoded _FALLBACK_SYSTEM_PROMPT if S3 config unavailable.
"""

import json
import os
import logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)
import time
import boto3
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from collections import defaultdict

_logger_std = logging.getLogger()
_logger_std.setLevel(logging.INFO)

REGION     = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
USER_ID    = os.environ["USER_ID"]
RECIPIENT  = os.environ["EMAIL_RECIPIENT"]
SENDER     = os.environ["EMAIL_SENDER"]

USER_PREFIX = f"USER#{USER_ID}#SOURCE#"

dynamodb   = boto3.resource("dynamodb", region_name=REGION)
table      = dynamodb.Table(TABLE_NAME)
ses        = boto3.client("sesv2", region_name=REGION)
secrets    = boto3.client("secretsmanager", region_name=REGION)
s3_client  = boto3.client("s3", region_name=REGION)
S3_BUCKET  = os.environ["S3_BUCKET"]

# Board of Directors config loader
try:
    import board_loader
    _HAS_BOARD_LOADER = True
except ImportError:
    _HAS_BOARD_LOADER = False
    logger.warning("[nutrition] board_loader not available — using fallback prompts")

# IC-15/16: Insight Ledger
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
    logger = get_logger("nutrition-review")
except ImportError:
    import logging as _log
    logger = _log.getLogger("nutrition-review")
    logger.setLevel(_log.INFO)


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
        "KeyConditionExpression": "pk = :pk AND sk BETWEEN :s AND :e",
        "ExpressionAttributeValues": {
            ":pk": pk, ":s": f"DATE#{start_date}", ":e": f"DATE#{end_date}",
        },
    }
    while True:
        resp = table.query(**kwargs)
        for item in resp.get("Items", []):
            date_str = item.get("date") or item["sk"].replace("DATE#", "")
            records[date_str] = d2f(item)
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    return records

def query_all(source):
    pk = f"USER#{USER_ID}#SOURCE#{source}"
    items = []
    kwargs = {
        "KeyConditionExpression": "pk = :pk",
        "ExpressionAttributeValues": {":pk": pk},
    }
    while True:
        resp = table.query(**kwargs)
        items.extend(resp.get("Items", []))
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    return [d2f(i) for i in items]

def fetch_profile():
    try:
        r = table.get_item(Key={"pk": f"USER#{USER_ID}", "sk": "PROFILE#v1"})
        return d2f(r.get("Item", {}))
    except Exception as e:
        logger.error(f"fetch_profile: {e}")
        return {}


# ══════════════════════════════════════════════════════════════════════════════
# DATA GATHERING
# ══════════════════════════════════════════════════════════════════════════════

def gather_nutrition_data():
    today = datetime.now(timezone.utc).date()
    w1_end = (today - timedelta(days=1)).isoformat()
    w1_start = (today - timedelta(days=7)).isoformat()
    w2_end = (today - timedelta(days=8)).isoformat()
    w2_start = (today - timedelta(days=14)).isoformat()
    weight_start = (today - timedelta(days=30)).isoformat()

    logger.info(f"This week: {w1_start} -> {w1_end}")

    profile = fetch_profile()
    if not profile:
        logger.error("No profile found")
        return None

    mf_this = query_range("macrofactor", w1_start, w1_end)
    mf_prior = query_range("macrofactor", w2_start, w2_end)
    logger.info(f"MacroFactor: {len(mf_this)} days this, {len(mf_prior)} prior")

    withings = query_range("withings", weight_start, w1_end)
    strava = query_range("strava", w1_start, w1_end)
    cgm = query_range("apple_health", w1_start, w1_end)

    genome_items = query_all("genome")
    nutrient_snps = [g for g in genome_items if g.get("category") in
                     ("nutrient_metabolism", "metabolism", "lipids")]
    logger.info(f"Genome: {len(nutrient_snps)} relevant SNPs")

    lab_items = query_all("labs")
    latest_lab = None
    if lab_items:
        lab_items.sort(key=lambda x: x.get("draw_date", ""), reverse=True)
        latest_lab = lab_items[0]

    dexa_items = query_all("dexa")
    latest_dexa = dexa_items[0] if dexa_items else None

    supplements = query_range("supplements", w1_start, w1_end)

    # Previous week's nutrition review (for trending)
    prev_review = None
    try:
        pk = f"USER#{USER_ID}#SOURCE#nutrition_review"
        resp = table.query(
            KeyConditionExpression="pk = :pk",
            ExpressionAttributeValues={":pk": pk},
            ScanIndexForward=False, Limit=1,
        )
        items = resp.get("Items", [])
        if items:
            prev_review = d2f(items[0])
            logger.info(f"Previous review: {prev_review.get('date', '?')}")
    except Exception as e:
        logger.warning(f"No previous review: {e}")

    return {
        "macrofactor_this": mf_this, "macrofactor_prior": mf_prior,
        "withings": withings, "strava": strava, "cgm": cgm,
        "genome_snps": nutrient_snps, "latest_lab": latest_lab,
        "latest_dexa": latest_dexa, "supplements": supplements,
        "prev_review": prev_review, "profile": profile,
        "dates": {"this_start": w1_start, "this_end": w1_end,
                  "prior_start": w2_start, "prior_end": w2_end},
    }


# ══════════════════════════════════════════════════════════════════════════════
# EXTRACT & SUMMARIZE
# ══════════════════════════════════════════════════════════════════════════════

def extract_daily_nutrition(mf_data):
    days = []
    for date_str in sorted(mf_data.keys()):
        rec = mf_data[date_str]
        food_log = rec.get("food_log", [])
        foods = []
        for item in food_log:
            name = item.get("food_name", "unknown")
            if any(s in name.lower() for s in ("supplement",)):
                continue
            foods.append({
                "name": name, "time": item.get("time", "?"),
                "cal": safe_float(item, "calories_kcal", 0),
                "protein_g": safe_float(item, "protein_g", 0),
                "carbs_g": safe_float(item, "carbs_g", 0),
                "fat_g": safe_float(item, "fat_g", 0),
                "fiber_g": safe_float(item, "fiber_g"),
            })
        day = {
            "date": date_str,
            "total_calories": safe_float(rec, "total_calories_kcal"),
            "total_protein_g": safe_float(rec, "total_protein_g"),
            "total_carbs_g": safe_float(rec, "total_carbs_g"),
            "total_fat_g": safe_float(rec, "total_fat_g"),
            "total_fiber_g": safe_float(rec, "total_fiber_g"),
            "total_sodium_mg": safe_float(rec, "total_sodium_mg"),
            "total_potassium_mg": safe_float(rec, "total_potassium_mg"),
            "total_magnesium_mg": safe_float(rec, "total_magnesium_mg"),
            "total_calcium_mg": safe_float(rec, "total_calcium_mg"),
            "total_iron_mg": safe_float(rec, "total_iron_mg"),
            "total_zinc_mg": safe_float(rec, "total_zinc_mg"),
            "total_vitamin_d_mcg": safe_float(rec, "total_vitamin_d_mcg"),
            "total_vitamin_k_mcg": safe_float(rec, "total_vitamin_k_mcg"),
            "total_vitamin_c_mg": safe_float(rec, "total_vitamin_c_mg"),
            "total_choline_mg": safe_float(rec, "total_choline_mg"),
            "total_folate_mcg": safe_float(rec, "total_folate_mcg"),
            "total_omega3_total_g": safe_float(rec, "total_omega3_total_g"),
            "total_omega3_epa_g": safe_float(rec, "total_omega3_epa_g"),
            "total_omega3_dha_g": safe_float(rec, "total_omega3_dha_g"),
            "total_omega3_ala_g": safe_float(rec, "total_omega3_ala_g"),
            "total_omega6_g": safe_float(rec, "total_omega6_g"),
            "total_saturated_fat_g": safe_float(rec, "total_saturated_fat_g"),
            "total_sugars_g": safe_float(rec, "total_sugars_g"),
            "total_sugars_added_g": safe_float(rec, "total_sugars_added_g"),
            "total_cholesterol_mg": safe_float(rec, "total_cholesterol_mg"),
            "meals_above_30g_protein": safe_float(rec, "meals_above_30g_protein"),
            "protein_distribution_score": safe_float(rec, "protein_distribution_score"),
            "total_meals": safe_float(rec, "total_meals"),
            "micronutrient_sufficiency": rec.get("micronutrient_sufficiency"),
            "micronutrient_avg_pct": safe_float(rec, "micronutrient_avg_pct"),
            "foods": foods,
        }
        days.append(day)
    return days

def extract_weight_trend(withings_data):
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
    return {
        "latest_weight_lbs": latest, "earliest_weight_lbs": earliest,
        "change_30d_lbs": round(latest - earliest, 1),
        "measurements": len(weights), "readings": weights[-7:],
    }

def extract_training(strava_data):
    activities = []
    for date_str in sorted(strava_data.keys()):
        rec = strava_data[date_str]
        acts = rec.get("activities", [])
        if isinstance(acts, list):
            for a in acts:
                activities.append({
                    "date": date_str,
                    "type": a.get("sport_type", a.get("type", "?")),
                    "name": a.get("name", ""),
                    "duration_min": round(safe_float(a, "elapsed_time_seconds", 0) / 60, 1)
                        if safe_float(a, "elapsed_time_seconds") else safe_float(a, "moving_time_minutes"),
                    "calories": safe_float(a, "calories"),
                    "avg_hr": safe_float(a, "average_heartrate"),
                    "distance_miles": round(safe_float(a, "distance_meters", 0) / 1609.34, 2)
                        if safe_float(a, "distance_meters") else safe_float(a, "distance_miles"),
                })
    return activities

def extract_cgm(cgm_data):
    days = []
    for date_str in sorted(cgm_data.keys()):
        rec = cgm_data[date_str]
        glucose = safe_float(rec, "glucose_mean_mg_dl")
        if glucose:
            days.append({
                "date": date_str, "mean_mg_dl": glucose,
                "std_dev": safe_float(rec, "glucose_std_dev"),
                "time_in_range_pct": safe_float(rec, "glucose_time_in_range_pct"),
                "time_above_140_pct": safe_float(rec, "glucose_time_above_140_pct"),
                "spikes_above_140": safe_float(rec, "glucose_spikes_above_140"),
            })
    return days if days else None

def extract_genome_context(snps):
    return [{"gene": s.get("gene"), "risk": s.get("risk_level"),
             "summary": s.get("summary"), "category": s.get("category")} for s in snps]

def extract_dexa_context(dexa):
    if not dexa:
        return None
    bc = dexa.get("body_composition", {})
    scan_date = dexa.get("scan_date", "unknown")
    try:
        sd = datetime.strptime(scan_date, "%Y-%m-%d").date()
        months_ago = round((datetime.now(timezone.utc).date() - sd).days / 30.44)
    except Exception:
        months_ago = None
    return {
        "scan_date": scan_date, "months_ago": months_ago,
        "weight_at_scan_lbs": safe_float(bc, "weight_lb"),
        "body_fat_pct": safe_float(bc, "body_fat_pct"),
        "lean_mass_lbs": safe_float(bc, "lean_mass_lb"),
        "fat_mass_lbs": safe_float(bc, "fat_mass_lb"),
        "visceral_fat_g": safe_float(bc, "visceral_fat_g"),
        "bmd_t_score": safe_float(bc, "bmd_t_score"),
        "ag_ratio": safe_float(bc, "ag_ratio"),
        "caveat": f"Scan is {months_ago} months old. Weight has changed significantly since.",
    }

def compute_weekly_summary(days):
    if not days:
        return {}
    n = len(days)
    def avg_field(field):
        vals = [d.get(field) for d in days if d.get(field) is not None]
        return round(sum(vals) / len(vals), 1) if vals else None
    return {
        "days_logged": n,
        "avg_calories": avg_field("total_calories"),
        "avg_protein_g": avg_field("total_protein_g"),
        "avg_carbs_g": avg_field("total_carbs_g"),
        "avg_fat_g": avg_field("total_fat_g"),
        "avg_fiber_g": avg_field("total_fiber_g"),
        "avg_sodium_mg": avg_field("total_sodium_mg"),
        "avg_potassium_mg": avg_field("total_potassium_mg"),
        "avg_choline_mg": avg_field("total_choline_mg"),
        "avg_vitamin_d_mcg": avg_field("total_vitamin_d_mcg"),
        "avg_vitamin_k_mcg": avg_field("total_vitamin_k_mcg"),
        "avg_omega3_total_g": avg_field("total_omega3_total_g"),
        "avg_omega6_g": avg_field("total_omega6_g"),
        "avg_micronutrient_pct": avg_field("micronutrient_avg_pct"),
    }


# ══════════════════════════════════════════════════════════════════════════════
# ANTHROPIC API
# ══════════════════════════════════════════════════════════════════════════════

def _build_nutrition_prompt_from_config(calorie_target, protein_target_g):
    """Build nutrition review system prompt from S3 board config.

    Returns the fully-rendered prompt string (no remaining placeholders),
    or None if config unavailable.
    """
    if not _HAS_BOARD_LOADER:
        return None

    config = board_loader.load_board(s3_client, S3_BUCKET)
    if not config:
        return None

    members = board_loader.get_feature_members(config, "nutrition_review")
    if not members:
        logger.warning("[nutrition] No members configured for 'nutrition_review' feature")
        return None

    # Build per-expert section instructions
    expert_blocks = []
    color_rules = []
    for mid, member, feat_cfg in members:
        header = feat_cfg.get("section_header", f"### {member['name']}")
        focus = feat_cfg.get("prompt_focus", "Provide your nutrition analysis.")
        voice = member.get("voice", {})
        color = member.get("color", "#6366f1")

        # Build the expert prompt section with template vars rendered
        section = f"{header}\n"
        section += f"Analyze: {focus}\n" if not focus.startswith("Analyze:") else f"{focus}\n"
        section += f'Tone: {voice.get("tone", "Professional and direct.")}.\n'
        section += f'Principle: \"{voice.get("catchphrase", "")}\"' if voice.get("catchphrase") else ""

        # Render calorie/protein targets into the focus text
        section = section.replace("{calorie_target}", str(calorie_target))
        section = section.replace("{protein_target_g}", str(protein_target_g))

        expert_blocks.append(section)

        # Track colors for HTML format rules
        short_name = member["name"].split()[-1]  # Norton, Patrick, Attia
        color_rules.append(f"- {short_name} card: left border {color}")

    experts_text = "\n\n".join(expert_blocks)
    colors_text = "\n".join(color_rules)

    prompt = f"""You are the Saturday Nutrition Review panel for Matthew's Life Platform. You write a weekly email arriving Saturday morning before his grocery shopping trip to Metropolitan Market in Seattle.

## YOUR PANEL

Write as three distinct expert voices analyzing the week's nutrition data, followed by a unified tactical section.

{experts_text}

## UNIFIED TACTICAL SECTION

### Top 3 Nutrition Priorities This Week
3 specific, actionable changes. Not vague goals.

### Metropolitan Market Grocery List
By store section. Each item has parenthetical WHY. Only foods that fit his cooking style (Mexican, Asian, simple protein+sides), <30 min prep, available at premium Seattle grocer.

### Meal Ideas (3-4)
Build from his existing repertoire. Format: **Meal Name** (addresses: [priority]) + brief description.

### Supplement Check
Current supplementation vs genome gaps. Redundancies? Additions?

## RULES
1. DEXA has age caveat - note scan date and weight change. Benchmark only.
2. Supplement entries in food_log: analyze for micros but exclude from meal analysis.
3. Deduce meal names from ingredient clusters at same timestamp.
4. He gained significant weight over 10+ months. Active recovery. Encouraging but honest.
5. Eating window ~11am-7pm (16:8). Don't suggest 7am breakfast.
6. If previous week data provided, weave in light trending comparisons naturally.

## FORMAT
Write clean HTML with inline styles. Design:
- Card backgrounds: #16213e. Text: #e0e0e0. Accent: #4cc9f0
{colors_text}
- Unified section: border #4cc9f0
- Grocery list: checkboxes for print
- ~1500-2000 words. No <html>/<head>/<body> tags.
- Each expert section in a div with border-left, padding, margin-bottom.
- Section headers: font-size 15px, font-weight 700, color matching border.

## CRITICAL: Every recommendation must cite a specific food he ate, a specific number, or a specific gene variant. No generic advice."""

    logger.info("[nutrition] Built prompt from config with %d panel members", len(members))
    return prompt


# Fallback prompt (original hardcoded version, used if S3 config unavailable)
_FALLBACK_SYSTEM_PROMPT = """You are the Saturday Nutrition Review panel for Matthew's Life Platform. You write a weekly email arriving Saturday morning before his grocery shopping trip to Metropolitan Market in Seattle.

## YOUR PANEL

Write as three distinct expert voices analyzing the week's nutrition data, followed by a unified tactical section.

### Dr. Layne Norton - Macros, Protein & Adherence
Analyze: Weekly calorie avg vs target ({calorie_target} kcal) and deficit consistency. Protein total AND distribution (flag meals <30g, praise >40g). Target: {protein_target_g}g. Protein source diversity. Carb/fat balance relative to training. Meal frequency and eating window. Fiber trend.
Tone: Direct, evidence-based. Reference HIS actual food log entries by deduced meal name.
Principle: "Build from what's working. Don't overhaul - optimize."

### Dr. Rhonda Patrick - Micronutrients, Genome & Longevity
Analyze: Cross-reference dietary intake against genome SNPs provided. Vitamin D gap + genetics. FADS2 ALA conversion issue. FADS1 omega-6/inflammation. MTHFR methylfolate. Choline (MTHFD1+MTRR+PEMT triple risk, target 550mg+). Vitamin K (VKORC1). Potassium. Any micro <50% for 3+ days.
Tone: Scientific but accessible. Connect genes to nutrients to foods.
Principle: "Genomics tells us WHERE to focus. Food logs tell us what's missing."

### Dr. Peter Attia - Metabolic Health & Composition
Analyze: Weight trend and rate. CGM data if available. Meal glucose impact. Meal timing vs training. Deficit sustainability. DEXA benchmark context. Carb quality/timing.
Tone: Strategic, longevity-focused.
Principle: "Rate of loss matters less than body composition trajectory."

## UNIFIED TACTICAL SECTION

### Top 3 Nutrition Priorities This Week
3 specific, actionable changes. Not vague goals.

### Metropolitan Market Grocery List
By store section. Each item has parenthetical WHY. Only foods that fit his cooking style (Mexican, Asian, simple protein+sides), <30 min prep, available at premium Seattle grocer.

### Meal Ideas (3-4)
Build from his existing repertoire. Format: **Meal Name** (addresses: [priority]) + brief description.

### Supplement Check
Current supplementation vs genome gaps. Redundancies? Additions?

## RULES
1. DEXA has age caveat - note scan date and weight change. Benchmark only.
2. Supplement entries in food_log: analyze for micros but exclude from meal analysis.
3. Deduce meal names from ingredient clusters at same timestamp.
4. He gained significant weight over 10+ months. Active recovery. Encouraging but honest.
5. Eating window ~11am-7pm (16:8). Don't suggest 7am breakfast.
6. If previous week data provided, weave in light trending comparisons naturally.

## FORMAT
Write clean HTML with inline styles. Design:
- Card backgrounds: #16213e. Text: #e0e0e0. Accent: #4cc9f0
- Norton card: left border #10b981. Patrick: #8b5cf6. Attia: #f59e0b
- Unified section: border #4cc9f0
- Grocery list: checkboxes for print
- ~1500-2000 words. No <html>/<head>/<body> tags.
- Each expert section in a div with border-left, padding, margin-bottom.
- Section headers: font-size 15px, font-weight 700, color matching border.

## CRITICAL: Every recommendation must cite a specific food he ate, a specific number, or a specific gene variant. No generic advice."""


def build_user_message(data):
    days_this = extract_daily_nutrition(data["macrofactor_this"])
    days_prior = extract_daily_nutrition(data["macrofactor_prior"])
    summary_this = compute_weekly_summary(days_this)
    summary_prior = compute_weekly_summary(days_prior)

    payload = {
        "this_week": {"summary": summary_this, "daily_detail": days_this},
        "prior_week_summary": summary_prior,
        "weight": extract_weight_trend(data["withings"]),
        "training": extract_training(data["strava"]),
        "cgm": extract_cgm(data["cgm"]),
        "genome_nutrient_snps": extract_genome_context(data["genome_snps"]),
        "dexa": extract_dexa_context(data["latest_dexa"]),
        "profile_targets": {
            "calorie_target": data["profile"].get("calorie_target", 1800),
            "protein_target_g": data["profile"].get("protein_target_g", 190),
            "goal_weight_lbs": data["profile"].get("goal_weight_lbs", 185),
        },
    }
    if data.get("prev_review"):
        pr = data["prev_review"]
        payload["prev_week_review"] = {
            "date": pr.get("date"),
            "avg_calories": pr.get("avg_calories"),
            "avg_protein_g": pr.get("avg_protein_g"),
            "avg_fiber_g": pr.get("avg_fiber_g"),
        }
    return json.dumps(payload, indent=2, default=str)


def call_anthropic(system_prompt, user_message, api_key):
    # Delegates to retry_utils for exponential backoff + CloudWatch metrics (P1.8/P1.9)
    import retry_utils
    return retry_utils.call_anthropic_api(
        prompt=user_message,
        api_key=api_key,
        max_tokens=4096,
        system=system_prompt,
        temperature=0.3,
        timeout=90,
    )


# ══════════════════════════════════════════════════════════════════════════════
# HTML EMAIL
# ══════════════════════════════════════════════════════════════════════════════

def build_summary_table(days, profile):
    if not days:
        return ""
    cal_target = profile.get("calorie_target", 1800)
    protein_target = profile.get("protein_target_g", 190)

    rows = ""
    for d in days:
        try:
            day_name = datetime.strptime(d["date"], "%Y-%m-%d").strftime("%a %m/%d")
        except Exception:
            day_name = d["date"]
        cal = d.get("total_calories") or 0
        pro = d.get("total_protein_g") or 0
        carb = d.get("total_carbs_g") or 0
        fat = d.get("total_fat_g") or 0
        fiber = d.get("total_fiber_g") or 0
        micro_pct = d.get("micronutrient_avg_pct") or 0

        cal_c = "#10b981" if cal <= cal_target * 1.05 else "#f59e0b" if cal <= cal_target * 1.2 else "#ef4444"
        pro_c = "#10b981" if pro >= protein_target * 0.85 else "#f59e0b" if pro >= protein_target * 0.7 else "#ef4444"
        fib_c = "#10b981" if fiber >= 30 else "#f59e0b" if fiber >= 20 else "#ef4444"
        mic_c = "#10b981" if micro_pct >= 70 else "#f59e0b" if micro_pct >= 50 else "#ef4444"

        rows += f'''<tr style="border-bottom:1px solid #2a2d4a;">
            <td style="padding:8px;color:#e0e0e0;font-size:13px;">{day_name}</td>
            <td style="padding:8px;color:{cal_c};font-size:13px;text-align:center;font-weight:600;">{int(cal)}</td>
            <td style="padding:8px;color:{pro_c};font-size:13px;text-align:center;font-weight:600;">{int(pro)}g</td>
            <td style="padding:8px;color:#e0e0e0;font-size:13px;text-align:center;">{int(carb)}g</td>
            <td style="padding:8px;color:#e0e0e0;font-size:13px;text-align:center;">{int(fat)}g</td>
            <td style="padding:8px;color:{fib_c};font-size:13px;text-align:center;">{fiber:.0f}g</td>
            <td style="padding:8px;color:{mic_c};font-size:13px;text-align:center;">{micro_pct:.0f}%</td>
        </tr>'''

    n = len(days)
    ac = sum(d.get("total_calories") or 0 for d in days) / n
    ap = sum(d.get("total_protein_g") or 0 for d in days) / n
    acb = sum(d.get("total_carbs_g") or 0 for d in days) / n
    af = sum(d.get("total_fat_g") or 0 for d in days) / n
    afb = sum(d.get("total_fiber_g") or 0 for d in days) / n
    am = sum(d.get("micronutrient_avg_pct") or 0 for d in days) / n

    rows += f'''<tr style="border-top:2px solid #4cc9f0;background:#0f1127;">
        <td style="padding:8px;color:#4cc9f0;font-size:13px;font-weight:700;">AVG</td>
        <td style="padding:8px;color:#4cc9f0;font-size:13px;text-align:center;font-weight:700;">{int(ac)}</td>
        <td style="padding:8px;color:#4cc9f0;font-size:13px;text-align:center;font-weight:700;">{int(ap)}g</td>
        <td style="padding:8px;color:#4cc9f0;font-size:13px;text-align:center;font-weight:700;">{int(acb)}g</td>
        <td style="padding:8px;color:#4cc9f0;font-size:13px;text-align:center;font-weight:700;">{int(af)}g</td>
        <td style="padding:8px;color:#4cc9f0;font-size:13px;text-align:center;font-weight:700;">{afb:.0f}g</td>
        <td style="padding:8px;color:#4cc9f0;font-size:13px;text-align:center;font-weight:700;">{am:.0f}%</td>
    </tr>'''

    return f'''<table style="width:100%;border-collapse:collapse;background:#16213e;border-radius:8px;overflow:hidden;margin-bottom:20px;">
        <tr style="background:#0f1127;">
            <th style="padding:8px;color:#9ca3af;font-size:11px;text-align:left;">DAY</th>
            <th style="padding:8px;color:#9ca3af;font-size:11px;text-align:center;">KCAL</th>
            <th style="padding:8px;color:#9ca3af;font-size:11px;text-align:center;">PROTEIN</th>
            <th style="padding:8px;color:#9ca3af;font-size:11px;text-align:center;">CARBS</th>
            <th style="padding:8px;color:#9ca3af;font-size:11px;text-align:center;">FAT</th>
            <th style="padding:8px;color:#9ca3af;font-size:11px;text-align:center;">FIBER</th>
            <th style="padding:8px;color:#9ca3af;font-size:11px;text-align:center;">MICRO</th>
        </tr>
        {rows}
        <tr><td colspan="7" style="padding:4px 8px;color:#6b7280;font-size:10px;">
            Targets: {int(cal_target)} kcal | {int(protein_target)}g protein | 38g fiber | Micro = avg sufficiency %
        </td></tr>
    </table>'''


def build_email_html(summary_table, ai_content, dates, weight_info):
    try:
        dt_start = datetime.strptime(dates["this_start"], "%Y-%m-%d")
        dt_end = datetime.strptime(dates["this_end"], "%Y-%m-%d")
        week_label = f'{dt_start.strftime("%b %-d")} - {dt_end.strftime("%b %-d, %Y")}'
    except Exception:
        week_label = f'{dates["this_start"]} - {dates["this_end"]}'

    weight_line = ""
    if weight_info:
        w = weight_info["latest_weight_lbs"]
        delta = weight_info.get("change_30d_lbs", 0)
        arrow = "down" if delta < 0 else "up" if delta > 0 else "flat"
        weight_line = f'<div style="color:#9ca3af;font-size:13px;margin-top:4px;">Weight: {w:.1f} lbs ({arrow} {abs(delta):.1f} over 30d)</div>'

    return f'''<div style="max-width:600px;margin:0 auto;background:#1a1a2e;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;padding:20px;color:#e0e0e0;">
    <div style="text-align:center;margin-bottom:24px;">
        <div style="font-size:11px;letter-spacing:2px;color:#4cc9f0;font-weight:600;margin-bottom:4px;">LIFE PLATFORM</div>
        <div style="font-size:20px;font-weight:700;color:#ffffff;">Weekly Nutrition Review</div>
        <div style="color:#9ca3af;font-size:13px;margin-top:4px;">{week_label}</div>
        {weight_line}
    </div>
    <div style="margin-bottom:24px;">
        <div style="font-size:12px;letter-spacing:1px;color:#9ca3af;font-weight:600;margin-bottom:10px;">WEEKLY SNAPSHOT</div>
        {summary_table}
    </div>
    {ai_content}
    <div style="text-align:center;padding:16px 0;border-top:1px solid #2a2d4a;margin-top:24px;">
        <div style="color:#6b7280;font-size:11px;">Life Platform - Saturday Nutrition Review</div>
        <div style="color:#9ca3af;font-size:9px;margin-top:6px;">&#9874;&#65039; Personal health tracking only &mdash; not medical advice. Consult a qualified healthcare professional before making changes to your diet, exercise, or supplement regimen.</div>
    </div>
</div>'''


# ══════════════════════════════════════════════════════════════════════════════
# STORE WEEKLY SUMMARY
# ══════════════════════════════════════════════════════════════════════════════

def store_weekly_summary(dates, summary):
    try:
        pk = f"USER#{USER_ID}#SOURCE#nutrition_review"
        sk = f"DATE#{dates['this_end']}"
        item = {
            "pk": pk, "sk": sk,
            "date": dates["this_end"],
            "source": "nutrition_review",
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        for k, v in summary.items():
            if v is not None:
                item[k] = Decimal(str(v)) if isinstance(v, float) else v
        table.put_item(Item=item)
        logger.info(f"Stored weekly summary: {sk}")
    except Exception as e:
        logger.warning(f"Failed to store summary: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# HANDLER
# ══════════════════════════════════════════════════════════════════════════════

def lambda_handler(event, context):
    logger.info("Nutrition Review v1.0 starting...")

    data = gather_nutrition_data()
    if not data:
        return {"statusCode": 500, "body": "Failed to gather data"}

    dates = data["dates"]
    profile = data["profile"]

    days_this = extract_daily_nutrition(data["macrofactor_this"])
    if not days_this:
        logger.error("No MacroFactor data this week")
        return {"statusCode": 500, "body": "No nutrition data"}

    summary_table = build_summary_table(days_this, profile)
    user_message = build_user_message(data)
    logger.info(f"Prompt size: {len(user_message)} chars")

    cal_target = profile.get("calorie_target", 1800)
    pro_target = profile.get("protein_target_g", 190)

    # Try config-driven prompt first, fall back to hardcoded
    system = _build_nutrition_prompt_from_config(cal_target, pro_target)
    if system:
        print("[INFO] Using config-driven nutrition panel prompt")
    else:
        print("[INFO] Using fallback hardcoded nutrition panel prompt")
        system = _FALLBACK_SYSTEM_PROMPT.format(
            calorie_target=cal_target,
            protein_target_g=pro_target,
        )

    # P2: Dynamic journey context — panel must know stage for appropriate coaching
    try:
        _start = datetime.strptime(profile.get("journey_start_date", "2026-02-22"), "%Y-%m-%d").date()
        _days_in = max(1, (datetime.now(timezone.utc).date() - _start).days + 1)
        _week_num = max(1, (_days_in + 6) // 7)
        _start_w = profile.get("journey_start_weight_lbs", 302)
        _goal_w = profile.get("goal_weight_lbs", 185)
        if _week_num <= 4:
            _stage = "Foundation Stage"
            _note = (f"Week {_week_num}: At {_start_w}+ lbs, caloric deficit sustainability and protein consistency "
                     "matter more than macro fine-tuning. Do NOT apply intermediate-athlete nutrition benchmarks. "
                     "Acknowledge adherence wins warmly — this is still the hardest phase.")
        elif _week_num <= 12:
            _stage = "Momentum Stage"
            _note = f"Week {_week_num}: habit foundation established. Progressive nutrition optimization is appropriate."
        elif _week_num <= 26:
            _stage = "Building Stage"
            _note = f"Week {_week_num}: protocol refinement and deficit sustainability are primary levers."
        else:
            _stage = "Advanced Stage"
            _note = f"Week {_week_num}: performance nutrition coaching fully applicable."
        journey_block = (
            f"JOURNEY CONTEXT: Week {_week_num} ({_days_in} days in) | {_start_w}→{_goal_w} lbs | {_stage}\n"
            f"{_note}\n"
        )
        user_message = journey_block + "\n" + user_message
    except Exception as e:
        print(f"[WARN] P2 journey context failed: {e}")

    # IC-16: Progressive context for nutrition insights
    if _HAS_INSIGHT_WRITER:
        try:
            prev_ctx = insight_writer.build_insights_context(
                days=30, pillars=["nutrition"], max_items=5,
                label="PREVIOUS NUTRITION INSIGHTS (last 30 days)")
            if prev_ctx:
                user_message = prev_ctx + "\n\n" + user_message
        except Exception as e:
            print(f"[WARN] IC-16 failed: {e}")

    api_key = get_anthropic_key()
    logger.info("Calling Sonnet for analysis...")
    try:
        ai_content = call_anthropic(system, user_message, api_key)
    except Exception as e:
        logger.error(f"Anthropic failed: {e}")
        ai_content = '<div style="background:#16213e;border-radius:8px;padding:20px;color:#e0e0e0;">AI analysis unavailable. Review data table above.</div>'

    # AI-3: Validate output before rendering
    if _HAS_AI_VALIDATOR and ai_content and not ai_content.startswith("<div"):
        _val = validate_ai_output(ai_content, AIOutputType.NUTRITION_COACH)
        if _val.blocked:
            logger.error(f"[AI-3] Nutrition review output BLOCKED: {_val.block_reason}")
            ai_content = _val.safe_fallback or "<p>AI analysis unavailable. Review data table above.</p>"
        elif _val.warnings:
            logger.warning(f"[AI-3] Nutrition review warnings: {_val.warnings}")

    weight_info = extract_weight_trend(data["withings"])
    html = build_email_html(summary_table, ai_content, dates, weight_info)

    summary = compute_weekly_summary(days_this)
    avg_cal = summary.get("avg_calories", 0)
    avg_pro = summary.get("avg_protein_g", 0)
    subject = f"Nutrition Review - {dates['this_end']} - {int(avg_cal)} kcal - {int(avg_pro)}g protein"

    ses.send_email(
        FromEmailAddress=SENDER,
        Destination={"ToAddresses": [RECIPIENT]},
        Content={"Simple": {
            "Subject": {"Data": subject, "Charset": "UTF-8"},
            "Body":    {"Html": {"Data": html, "Charset": "UTF-8"}},
        }},
    )
    logger.info(f"Sent: {subject}")

    store_weekly_summary(dates, summary)

    # IC-15: Persist nutrition insights
    if _HAS_INSIGHT_WRITER and ai_content and not ai_content.startswith("<div"):
        try:
            insight_writer.write_insight(
                digest_type="nutrition_review", insight_type="coaching",
                text=ai_content[:800], pillars=["nutrition"],
                data_sources=["macrofactor"], tags=["nutrition", "weekly", "coaching"],
                confidence="high", actionable=True, date=dates.get("this_end", ""))
            print("[INFO] IC-15: nutrition insight persisted")
        except Exception as e:
            print(f"[WARN] IC-15 failed: {e}")

    return {"statusCode": 200, "body": f"Nutrition review sent: {subject}"}
