"""
AI Expert Analyzer Lambda — Observatory V2

Generates weekly AI expert voice analyses for 4 observatory pages.
Each expert analyzes current data and produces 2-3 paragraphs of prose.

Trigger: EventBridge cron — weekly, Monday 6am PT (14:00 UTC)
Can also be invoked manually with {"expert": "mind"} for a single expert.

DynamoDB cache:
  PK = USER#matthew#SOURCE#ai_analysis
  SK = EXPERT#mind | EXPERT#nutrition | EXPERT#training | EXPERT#physical
  TTL = 8 days (auto-expire if Lambda fails to run)

v1.0.0 — 2026-03-31
"""

import json
import logging
import os
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
USER_ID = os.environ.get("USER_ID", "matthew")
USER_PREFIX = f"USER#{USER_ID}#SOURCE#"
CACHE_PK = f"{USER_PREFIX}ai_analysis"
AI_SECRET_NAME = os.environ.get("AI_SECRET_NAME", "life-platform/ai-keys")
AI_MODEL = os.environ.get("AI_MODEL", "claude-sonnet-4-6")

EXPERTS = ["mind", "nutrition", "training", "physical", "explorer", "glucose"]

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
    # Handle JSON-wrapped secret (life-platform/ai-keys has {"anthropic_api_key": "..."})
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


def gather_data_for_expert(expert_key):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    d30 = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")

    if expert_key == "mind":
        # Journal analysis + mood + vice streaks
        ja_items = _query_source("journal_analysis", d30, today)
        som_items = _query_source("state_of_mind", d30, today)
        avg_sentiment = 0
        if ja_items:
            scores = [float(i.get("sentiment_score", 0)) for i in ja_items]
            avg_sentiment = round(sum(scores) / len(scores), 2) if scores else 0
        # Top themes
        theme_counts = {}
        for item in ja_items:
            for t in item.get("themes", []):
                theme_counts[t] = theme_counts.get(t, 0) + 1
        top_themes = sorted(theme_counts.items(), key=lambda x: x[1], reverse=True)[:5]

        avg_valence = 0
        if som_items:
            vals = [float(s.get("valence", 0)) for s in som_items if s.get("valence") is not None]
            avg_valence = round(sum(vals) / len(vals), 2) if vals else 0

        return {
            "expert_key": "mind",
            "period": "last 30 days",
            "journal_entry_count": len(ja_items),
            "top_themes": [{"theme": t, "count": c} for t, c in top_themes],
            "avg_sentiment": avg_sentiment,
            "mood_readings": len(som_items),
            "avg_valence": avg_valence,
        }

    elif expert_key == "nutrition":
        items = _query_source("macrofactor", d30, today)
        if not items:
            return {"expert_key": "nutrition", "period": "last 30 days", "note": "No nutrition data available"}
        cal_vals = [float(i["calories"]) for i in items if i.get("calories")]
        pro_vals = [float(i["protein_g"]) for i in items if i.get("protein_g")]
        avg_cal = round(sum(cal_vals) / len(cal_vals)) if cal_vals else 0
        avg_pro = round(sum(pro_vals) / len(pro_vals), 1) if pro_vals else 0
        protein_target = 190
        adherence = sum(1 for v in pro_vals if v >= protein_target) / max(len(pro_vals), 1) * 100
        return {
            "expert_key": "nutrition",
            "period": "last 30 days",
            "avg_calories": avg_cal,
            "avg_protein_g": avg_pro,
            "protein_target_g": protein_target,
            "protein_adherence_pct": round(adherence),
            "days_tracked": len(items),
        }

    elif expert_key == "training":
        # Strava/activity data (30d for step averages to match hero metric)
        activities = _query_source("strava", d30, today)
        # Steps: prefer Garmin (more accurate with watch), fall back to Apple Health
        garmin_items = _query_source("garmin", d30, today)
        step_vals = [float(g["steps"]) for g in garmin_items if g.get("steps")]
        if not step_vals:
            steps_items = _query_source("apple_health", d30, today)
            step_vals = [float(s["steps"]) for s in steps_items if s.get("steps") and float(s["steps"]) > 0]
        avg_steps = round(sum(step_vals) / len(step_vals)) if step_vals else 0
        total_min = sum(float(a.get("duration_min", 0) or a.get("moving_time_min", 0)) for a in activities)
        return {
            "expert_key": "training",
            "period": "last 30 days",
            "sessions_count": len(activities),
            "total_active_min": round(total_min),
            "avg_daily_steps": avg_steps,
        }

    elif expert_key == "physical":
        # DEXA + measurements + weight
        dexa = _latest_item("dexa")
        meas = _latest_item("measurements")
        weight_items = _query_source("withings", d30, today)
        weights = [float(w.get("weight_lbs", 0)) for w in weight_items if w.get("weight_lbs")]
        current_weight = weights[-1] if weights else None
        weight_4wk = round(weights[-1] - weights[0], 1) if len(weights) >= 2 else None

        data = {
            "expert_key": "physical",
            "period": "last 30 days",
            "current_weight_lb": current_weight,
            "weight_change_4wk": weight_4wk,
            "weight_readings": len(weights),
        }
        if dexa:
            bc = dexa.get("body_composition", {})
            data["body_fat_pct"] = float(bc.get("body_fat_pct", 0)) if bc.get("body_fat_pct") else None
            data["lean_mass_lb"] = float(bc.get("lean_mass_lb", 0)) if bc.get("lean_mass_lb") else None
            data["visceral_fat_lb"] = float(bc.get("visceral_fat_lb", 0)) if bc.get("visceral_fat_lb") else None
            data["days_since_dexa"] = (datetime.now(timezone.utc) - datetime.strptime(
                dexa.get("scan_date", today), "%Y-%m-%d").replace(tzinfo=timezone.utc)).days
        if meas:
            whr = meas.get("waist_height_ratio")
            if whr:
                data["waist_height_ratio"] = float(whr)
        return data

    elif expert_key == "explorer":
        # Cross-domain correlations + high-level experiment status
        # Query weekly correlations if they exist
        corr_items = _query_source("weekly_correlations", d30, today)
        sig_pairs = []
        for c in corr_items:
            pairs = c.get("pairs") or c.get("significant_pairs") or []
            if isinstance(pairs, list):
                sig_pairs.extend(pairs)
        # Active experiments
        exp_pk = f"{USER_PREFIX}experiments"
        try:
            exp_resp = table.query(
                KeyConditionExpression=Key("pk").eq(exp_pk),
                ScanIndexForward=False,
                Limit=10,
            )
            experiments = _decimal_to_float(exp_resp.get("Items", []))
            active_exps = [e for e in experiments if e.get("status") == "active"]
        except Exception:
            active_exps = []

        return {
            "expert_key": "explorer",
            "period": "last 30 days",
            "significant_correlations": len(sig_pairs),
            "top_pairs": sig_pairs[:5] if sig_pairs else [],
            "active_experiments": len(active_exps),
            "experiment_names": [e.get("name", "") for e in active_exps[:3]],
        }

    elif expert_key == "glucose":
        cgm_items = _query_source("dexcom", d30, today)
        readings = [float(i.get("glucose_mg_dl", 0)) for i in cgm_items if i.get("glucose_mg_dl")]
        avg_glucose = round(sum(readings) / len(readings), 1) if readings else None
        in_range = sum(1 for r in readings if 70 <= r <= 140)
        tir_pct = round(in_range / len(readings) * 100, 1) if readings else None
        std_dev = None
        if len(readings) > 1:
            mean = sum(readings) / len(readings)
            std_dev = round((sum((r - mean) ** 2 for r in readings) / len(readings)) ** 0.5, 1)
        return {
            "expert_key": "glucose",
            "period": "last 30 days",
            "total_readings": len(readings),
            "avg_glucose_mg_dl": avg_glucose,
            "time_in_range_pct": tir_pct,
            "std_dev": std_dev,
        }

    return {"expert_key": expert_key, "note": "Unknown expert"}


EXPERT_PERSONAS = {
    "mind": {
        "name": "Dr. Paul Conti",
        "title": "Psychiatrist and author of Trauma: The Invisible Epidemic",
        "style": "warm but direct, grounded in psychodynamic principles, attentive to patterns beneath the surface",
        "focus": "inner life patterns, emotional regulation, behavioral consistency, what the data reveals about psychological state",
    },
    "nutrition": {
        "name": "Dr. Layne Webb",
        "title": "Nutritional scientist and evidence-based practitioner",
        "style": "precise, data-driven, practical, no-nonsense about what works vs. what doesn't",
        "focus": "adherence patterns, macro optimization, behavior patterns in food choices, practical adjustments",
    },
    "training": {
        "name": "Dr. Sarah Chen",
        "title": "Exercise physiologist and strength coach",
        "style": "encouraging but honest, systems-focused, attentive to load management and recovery",
        "focus": "training load assessment, modality balance, recovery adequacy, progressive overload",
    },
    "physical": {
        "name": "Dr. Victor Reyes",
        "title": "Longevity physician specializing in body composition",
        "style": "clinically precise, optimistic but realistic, frames everything through longevity and health-span lens",
        "focus": "body composition trajectory, visceral fat reduction, lean mass preservation, metabolic markers",
    },
    "explorer": {
        "name": "Dr. Henning Brandt",
        "title": "Biostatistician and N=1 research methodologist",
        "style": "rigorous but accessible, excited by unexpected findings, careful about causal claims",
        "focus": "cross-domain correlations, surprising signal in the data, what pairs of metrics tell a story that single metrics cannot",
    },
    "glucose": {
        "name": "Dr. Rhonda Patrick",
        "title": "Metabolic health researcher specializing in continuous glucose monitoring",
        "style": "science-forward but practical, connects CGM data to dietary choices and metabolic patterns",
        "focus": "glucose variability, time-in-range optimization, meal response patterns, nocturnal glucose behavior, and how metabolic health connects to longevity",
    },
}


def build_prompt(expert_key, data):
    p = EXPERT_PERSONAS[expert_key]
    prior_summary = data.pop("_prior_analysis_summary", "")
    prior_block = f"Your previous analysis said: \"{prior_summary}...\" — find a different angle today." if prior_summary else ""
    data_json = json.dumps(data, indent=2, default=str)

    return f"""You are {p['name']}, {p['title']}.

Your communication style: {p['style']}.
Your analytical focus: {p['focus']}.

You are writing your weekly analysis section for Matthew's personal health data platform (averagejoematt.com).
This section is public-facing — Matthew has chosen radical transparency about his health journey.

Here is Matthew's recent data:
{data_json}

Write a 2-3 paragraph analysis (approximately 180-250 words).

Requirements:
- Open with one specific, concrete observation from the data (not a generic statement)
- Identify one pattern or trend that deserves attention — either positive or concerning
- End with one specific, actionable suggestion for the coming week
- Use first person as yourself (e.g., "What strikes me most..." or "From a clinical standpoint...")
- Do NOT use bullet points or headers — this is flowing prose
- Do NOT be sycophantic or overly positive — honest assessment serves Matthew better
- Reference specific numbers from the data when you do so naturally
- Tone: authoritative but human, like a trusted advisor's private note
- If prior analysis is provided below, find a DIFFERENT angle — do not repeat the same observation or suggestion

{prior_block}
After your analysis paragraphs, on a new line, write exactly:
KEY RECOMMENDATION: [one specific behavioral suggestion for the coming week, maximum 2 sentences]
{"" if expert_key != "mind" else chr(10) + "Then on another new line, write exactly:" + chr(10) + "JOURNALING PROMPT: [a single sentence journaling prompt for this week — something Matthew can sit with before writing]"}
Write only the analysis text — no preamble, no "Here is my analysis:", just the paragraphs themselves followed by the KEY RECOMMENDATION line."""


def generate_and_cache(expert_key):
    logger.info(f"Generating analysis for expert: {expert_key}")
    data = gather_data_for_expert(expert_key)

    # Read prior analysis to prevent repetition
    prior_summary = ""
    try:
        prior = table.get_item(Key={"pk": CACHE_PK, "sk": f"EXPERT#{expert_key}"}).get("Item")
        if prior and prior.get("analysis"):
            prior_text = str(prior["analysis"])
            prior_summary = prior_text[:300]
    except Exception:
        pass
    if prior_summary:
        data["_prior_analysis_summary"] = prior_summary

    prompt = build_prompt(expert_key, data)
    api_key = _get_api_key()

    req_body = json.dumps({
        "model": AI_MODEL,
        "max_tokens": 1000,
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

    analysis_text = "".join(
        b["text"] for b in result.get("content", []) if b.get("type") == "text"
    )

    # DPR-1.13: Extract KEY RECOMMENDATION if present
    key_recommendation = ""
    journaling_prompt = ""
    if "JOURNALING PROMPT:" in analysis_text:
        parts = analysis_text.split("JOURNALING PROMPT:", 1)
        analysis_text = parts[0].rstrip()
        journaling_prompt = parts[1].strip()
    if "KEY RECOMMENDATION:" in analysis_text:
        parts = analysis_text.split("KEY RECOMMENDATION:", 1)
        analysis_text = parts[0].rstrip()
        key_recommendation = parts[1].strip()

    now = datetime.now(timezone.utc)
    ttl = int((now + timedelta(days=8)).timestamp())

    item = {
        "pk": CACHE_PK,
        "sk": f"EXPERT#{expert_key}",
        "expert_key": expert_key,
        "analysis": analysis_text,
        "generated_at": now.isoformat(),
        "data_snapshot": json.dumps(data, default=str)[:5000],
        "ttl": ttl,
    }
    if key_recommendation:
        item["key_recommendation"] = key_recommendation
    if journaling_prompt:
        item["journaling_prompt"] = journaling_prompt
    table.put_item(Item=item)

    logger.info(f"Cached analysis for {expert_key}: {len(analysis_text)} chars")
    return analysis_text


def lambda_handler(event, context):
    try:
        target = event.get("expert", "all")
        experts_to_run = EXPERTS if target == "all" else [target]
        results = {}

        for expert_key in experts_to_run:
            if expert_key not in EXPERTS:
                logger.warning(f"Unknown expert: {expert_key}")
                continue
            try:
                text = generate_and_cache(expert_key)
                results[expert_key] = {"status": "ok", "chars": len(text)}
            except Exception as e:
                logger.error(f"Failed to generate {expert_key}: {e}")
                results[expert_key] = {"status": "error", "error": str(e)}

        return {
            "statusCode": 200,
            "body": json.dumps(results, default=str),
        }
    except Exception as e:
        logger.error(f"Handler failed: {e}")
        raise
