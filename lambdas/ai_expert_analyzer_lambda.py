"""
AI Expert Analyzer Lambda — Observatory V3

Generates weekly AI expert voice analyses for 8 observatory pages.
Each expert analyzes current data and produces 2-3 paragraphs of prose
with a rotating analytical lens to prevent repetition.

Trigger: EventBridge cron — weekly, Monday 6am PT (14:00 UTC)
Can also be invoked manually with {"expert": "mind"} for a single expert.

DynamoDB cache:
  PK = USER#matthew#SOURCE#ai_analysis
  SK = EXPERT#mind | EXPERT#nutrition | EXPERT#training | EXPERT#physical
       | EXPERT#explorer | EXPERT#glucose | EXPERT#labs | EXPERT#sleep
  TTL = 8 days (auto-expire if Lambda fails to run)

v2.0.0 — 2026-04-05 (V3 Observatory spec — PB-09)
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

# Intelligence Layer V2: shared preamble utilities
try:
    from intelligence_common import (
        build_data_inventory, build_data_maturity,
        load_goals_config, build_coach_preamble,
        build_thread_prompt_block, write_coach_thread,
        extract_thread_from_narrative,
    )
    _HAS_INTELLIGENCE_COMMON = True
except ImportError:
    _HAS_INTELLIGENCE_COMMON = False
    logger.warning("intelligence_common not available — preamble injection disabled")

TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
USER_ID = os.environ.get("USER_ID", "matthew")
USER_PREFIX = f"USER#{USER_ID}#SOURCE#"
CACHE_PK = f"{USER_PREFIX}ai_analysis"
AI_SECRET_NAME = os.environ.get("AI_SECRET_NAME", "life-platform/ai-keys")
AI_MODEL = os.environ.get("AI_MODEL", "claude-sonnet-4-6")

EXPERTS = ["mind", "nutrition", "training", "physical", "explorer", "glucose", "labs", "sleep"]

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


EXPERIMENT_START = "2026-04-01"


def gather_data_for_expert(expert_key):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    # Clamp lookback to experiment start — data before April 1 is pre-experiment
    d30 = max((datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d"), EXPERIMENT_START)
    days_in_experiment = max(1, (datetime.now(timezone.utc).date() - datetime.strptime(EXPERIMENT_START, "%Y-%m-%d").date()).days + 1)

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
            vals = [float(s.get("som_avg_valence", 0)) for s in som_items if s.get("som_avg_valence") is not None]
            avg_valence = round(sum(vals) / len(vals), 2) if vals else 0

        return {
            "expert_key": "mind",
            "period": f"experiment days 1-{days_in_experiment}",
            "journal_entry_count": len(ja_items),
            "top_themes": [{"theme": t, "count": c} for t, c in top_themes],
            "avg_sentiment": avg_sentiment,
            "mood_readings": len(som_items),
            "avg_valence": avg_valence,
        }

    elif expert_key == "nutrition":
        items = _query_source("macrofactor", d30, today)
        if not items:
            return {"expert_key": "nutrition", "period": f"experiment days 1-{days_in_experiment}", "note": "No nutrition data available"}
        cal_vals = [float(i["total_calories_kcal"]) for i in items if i.get("total_calories_kcal")]
        pro_vals = [float(i["total_protein_g"]) for i in items if i.get("total_protein_g")]
        fiber_vals = [float(i["total_fiber_g"]) for i in items if i.get("total_fiber_g")]
        avg_cal = round(sum(cal_vals) / len(cal_vals)) if cal_vals else 0
        avg_pro = round(sum(pro_vals) / len(pro_vals), 1) if pro_vals else 0
        avg_fiber = round(sum(fiber_vals) / len(fiber_vals), 1) if fiber_vals else None
        protein_target = 190
        adherence = sum(1 for v in pro_vals if v >= protein_target) / max(len(pro_vals), 1) * 100
        zero_cal_days = sum(1 for i in items if i.get("total_calories_kcal") is not None and float(i.get("total_calories_kcal", 0)) == 0)
        return {
            "expert_key": "nutrition",
            "period": f"experiment days 1-{days_in_experiment}",
            "avg_calories": avg_cal,
            "avg_protein_g": avg_pro,
            "avg_fiber_g": avg_fiber,
            "protein_target_g": protein_target,
            "protein_adherence_pct": round(adherence),
            "days_tracked": len(items),
            "zero_calorie_days": zero_cal_days,
        }

    elif expert_key == "training":
        activities = _query_source("strava", d30, today)
        garmin_items = _query_source("garmin", d30, today)
        whoop_items = _query_source("whoop", d30, today)
        step_vals = [float(g["steps"]) for g in garmin_items if g.get("steps")]
        if not step_vals:
            steps_items = _query_source("apple_health", d30, today)
            step_vals = [float(s["steps"]) for s in steps_items if s.get("steps") and float(s["steps"]) > 0]
        avg_steps = round(sum(step_vals) / len(step_vals)) if step_vals else 0
        total_min = sum(float(a.get("moving_time_seconds") or a.get("elapsed_time_seconds") or 0) / 60 for a in activities)
        recovery_vals = [float(w["recovery_score"]) for w in whoop_items if w.get("recovery_score")]
        avg_recovery = round(sum(recovery_vals) / len(recovery_vals), 1) if recovery_vals else None
        modalities = {}
        for a in activities:
            t = a.get("type", "unknown")
            modalities[t] = modalities.get(t, 0) + 1
        active_dates = set(a.get("sk", "")[:15] for a in activities if a.get("sk"))
        rest_days = max(0, days_in_experiment - len(active_dates))
        return {
            "expert_key": "training",
            "period": f"experiment days 1-{days_in_experiment}",
            "sessions_count": len(activities),
            "total_active_min": round(total_min),
            "avg_daily_steps": avg_steps,
            "avg_recovery": avg_recovery,
            "rest_days": rest_days,
            "modality_breakdown": modalities,
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
            "period": f"experiment days 1-{days_in_experiment}",
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
            "period": f"experiment days 1-{days_in_experiment}",
            "significant_correlations": len(sig_pairs),
            "top_pairs": sig_pairs[:5] if sig_pairs else [],
            "active_experiments": len(active_exps),
            "experiment_names": [e.get("name", "") for e in active_exps[:3]],
        }

    elif expert_key == "glucose":
        # CGM data is stored under apple_health with pre-aggregated blood_glucose_* fields
        cgm_items = _query_source("apple_health", d30, today)
        glucose_days = [i for i in cgm_items if i.get("blood_glucose_avg") is not None]
        avg_vals = [float(i["blood_glucose_avg"]) for i in glucose_days]
        avg_glucose = round(sum(avg_vals) / len(avg_vals), 1) if avg_vals else None
        tir_vals = [float(i["blood_glucose_time_in_range_pct"]) for i in glucose_days if i.get("blood_glucose_time_in_range_pct") is not None]
        tir_pct = round(sum(tir_vals) / len(tir_vals), 1) if tir_vals else None
        sd_vals = [float(i["blood_glucose_std_dev"]) for i in glucose_days if i.get("blood_glucose_std_dev") is not None]
        std_dev = round(sum(sd_vals) / len(sd_vals), 1) if sd_vals else None
        total_readings = sum(int(float(i.get("blood_glucose_readings_count", 0))) for i in glucose_days)
        return {
            "expert_key": "glucose",
            "period": f"experiment days 1-{days_in_experiment}",
            "total_readings": total_readings,
            "days_with_data": len(glucose_days),
            "avg_glucose_mg_dl": avg_glucose,
            "time_in_range_pct": tir_pct,
            "std_dev": std_dev,
        }

    elif expert_key == "labs":
        # Labs data spans all-time (not limited to experiment window — draws are periodic)
        lab_items = _query_source("labs", "2019-01-01", today)
        if not lab_items:
            return {"expert_key": "labs", "period": "all draws", "note": "No lab data available"}
        latest = lab_items[-1] if lab_items else {}
        flagged = []
        for key, val in latest.items():
            if key.endswith("_flag") and val in ("H", "L"):
                marker_name = key.replace("_flag", "").replace("_", " ").title()
                marker_val = latest.get(key.replace("_flag", ""), "")
                flagged.append(f"{marker_name}: {marker_val} ({val})")
        return {
            "expert_key": "labs",
            "period": "most recent draw",
            "draw_date": latest.get("sk", "").replace("DATE#", "")[:10],
            "total_draws": len(lab_items),
            "flagged_markers": flagged[:10],
            "flagged_count": len(flagged),
        }

    elif expert_key == "sleep":
        whoop_items = _query_source("whoop", d30, today)
        eight_items = _query_source("eightsleep", d30, today)
        sleep_hours = [float(w["sleep_duration_hours"]) for w in whoop_items if w.get("sleep_duration_hours")]
        recovery_vals = [float(w["recovery_score"]) for w in whoop_items if w.get("recovery_score")]
        hrv_vals = [float(w["hrv"]) for w in whoop_items if w.get("hrv")]
        score_vals = [float(e["sleep_score"]) for e in eight_items if e.get("sleep_score")]
        deep_pcts = [float(e["deep_pct"]) for e in eight_items if e.get("deep_pct")]
        rem_pcts = [float(e["rem_pct"]) for e in eight_items if e.get("rem_pct")]
        bed_temps = [float(e["bed_temp_f"]) for e in eight_items if e.get("bed_temp_f")]
        sleep_starts = [w.get("sleep_start") for w in whoop_items if w.get("sleep_start")]
        avg = lambda lst: round(sum(lst) / len(lst), 1) if lst else None
        return {
            "expert_key": "sleep",
            "period": f"experiment days 1-{days_in_experiment}",
            "nights_tracked": len(whoop_items),
            "avg_sleep_hours": avg(sleep_hours),
            "avg_sleep_score": avg(score_vals),
            "avg_recovery": avg(recovery_vals),
            "avg_hrv": avg(hrv_vals),
            "avg_deep_pct": avg(deep_pcts),
            "avg_rem_pct": avg(rem_pcts),
            "avg_bed_temp_f": avg(bed_temps),
            "sleep_onset_times": sleep_starts[-7:],
        }

    return {"expert_key": expert_key, "note": "Unknown expert"}


EXPERT_PERSONAS = {
    "mind": {
        "name": "Dr. Nathan Reeves",
        "title": "Psychiatrist specializing in trauma and behavioral patterns",
        "style": "warm but direct, grounded in psychodynamic principles, attentive to patterns beneath the surface",
        "focus": "inner life patterns, emotional regulation, behavioral consistency, what the data reveals about psychological state",
        "epistemology": "You think psychodynamically. Your question is always 'What is being avoided, protected, or deflected — and what does the data reveal about the inner state that the person hasn't articulated?' not 'How is Matthew's mood score?'",
    },
    "nutrition": {
        "name": "Dr. Marcus Webb",
        "title": "Nutritional scientist and evidence-based practitioner",
        "style": "precise, data-driven, practical, no-nonsense about what works vs. what doesn't",
        "focus": "adherence patterns, macro optimization, behavior patterns in food choices, practical adjustments",
        "epistemology": "You think behaviorally. Your question is always 'What's the friction point preventing consistent adherence — and what one practical change would have the highest impact?' not 'Was protein high enough?'",
    },
    "training": {
        "name": "Dr. Sarah Chen",
        "title": "Exercise physiologist and strength coach",
        "style": "encouraging but honest, systems-focused, attentive to load management and recovery",
        "focus": "training load assessment, modality balance, recovery adequacy, progressive overload",
        "epistemology": "You think in systems and load management. Your question is always 'Is the training stimulus adequate given recovery capacity — and is the system sustainable?' not 'How many workouts happened?'",
    },
    "physical": {
        "name": "Dr. Victor Reyes",
        "title": "Longevity physician specializing in body composition",
        "style": "clinically precise, optimistic but realistic, frames everything through longevity and health-span lens",
        "focus": "body composition trajectory, visceral fat reduction, lean mass preservation, metabolic markers",
        "epistemology": "You think through the longevity lens. Your question is always 'What does this trajectory mean for healthspan at 60, 70, 80 — and which metric is the leading indicator?' not 'Did he lose weight this week?'",
    },
    "explorer": {
        "name": "Dr. Henning Brandt",
        "title": "Biostatistician and N=1 research methodologist",
        "style": "rigorous but accessible, excited by unexpected findings, careful about causal claims",
        "focus": "cross-domain correlations, surprising signal in the data, what pairs of metrics tell a story that single metrics cannot",
        "epistemology": "You think like an N=1 researcher. Your question is always 'What surprising relationship does the data suggest that no single domain expert would notice — and what would confirm or refute it?' not 'What are the trends?'",
    },
    "labs": {
        "name": "Dr. James Okafor",
        "title": "Clinical pathologist specializing in preventive lab interpretation",
        "style": "clinical but accessible, connects lab values to lifestyle context, identifies actionable patterns",
        "focus": "flagged biomarkers in context of current nutrition, training, and supplement protocols — what the numbers mean and what to do about them",
        "epistemology": "You think clinically. Your question is always 'What do these lab values mean in the context of his current lifestyle — and which flagged marker is most actionable right now?' not 'Which values are out of range?'",
    },
    "sleep": {
        "name": "Dr. Lisa Park",
        "title": "Sleep and circadian rhythm specialist",
        "style": "warm but evidence-based, connects sleep architecture to next-day performance, attentive to consistency patterns",
        "focus": "sleep duration and efficiency trends, deep sleep adequacy, HRV recovery correlation, sleep onset consistency, bed temperature optimization, and how sleep quality cascades into every other domain",
        "epistemology": "You think architecturally. Your question is always 'What does the sleep architecture — stages, consistency, timing, environment — reveal about recovery quality, and how does it cascade into every other domain?' not 'How many hours did he sleep?'",
    },
    "glucose": {
        "name": "Dr. Amara Patel",
        "title": "Metabolic health researcher specializing in continuous glucose monitoring",
        "style": "science-forward but practical, connects CGM data to dietary choices and metabolic patterns",
        "focus": "glucose variability, time-in-range optimization, meal response patterns, nocturnal glucose behavior, and how metabolic health connects to longevity",
        "epistemology": "You think mechanistically. Your question is always 'What biological process does this glucose pattern reveal — insulin sensitivity, meal composition, circadian alignment — and what does it mean for metabolic health long-term?' not 'Was glucose in range?'",
    },
}


def build_prompt(expert_key, data, days_in_experiment=None, week_number=None):
    p = EXPERT_PERSONAS[expert_key]
    if days_in_experiment is None:
        days_in_experiment = max(1, (datetime.now(timezone.utc).date() - datetime.strptime(EXPERIMENT_START, "%Y-%m-%d").date()).days + 1)
    week_num = week_number or max(1, days_in_experiment // 7 + 1)

    prior_summary = data.pop("_prior_analysis_summary", "")
    prior_recommendation = data.pop("_prior_recommendation", "")
    data_json = json.dumps(data, indent=2, default=str)

    # Rotating analytical lens — prevents repetitive framing
    lenses = [
        "Focus on the most surprising or counterintuitive finding in this data.",
        "Focus on what changed since last week and whether the direction matters.",
        "Focus on what the data does NOT show — the gaps, the missing signal, the dog that didn't bark.",
        "Focus on one specific number and explain why it matters more than it appears.",
        "Focus on the interaction between two metrics that tells a story neither tells alone.",
        "Focus on whether Matthew's current trajectory is sustainable for 3 more months.",
        "Focus on what a clinician would flag if this were a patient chart review.",
    ]
    lens = lenses[(week_num - 1) % len(lenses)]

    prior_block = ""
    if prior_summary:
        prior_block = f"""
Your PREVIOUS analysis said: "{prior_summary[:300]}..."
Your PREVIOUS recommendation was: "{prior_recommendation[:200]}..."

CRITICAL: Do NOT repeat the same observation, angle, or recommendation. Find a genuinely
different insight. If you previously discussed deep sleep percentage, discuss something else
this week — consistency, efficiency, HRV trend, or a cross-domain connection. The reader
has already read your last analysis and will notice repetition immediately.
"""

    labs_context = ""
    if expert_key == "labs":
        labs_context = f"""
IMPORTANT: Lab data spans Matthew's full history, not just the current experiment.
The data shows {data.get('total_draws', 0)} total blood draws, with the most recent
on {data.get('draw_date', 'unknown')}. Do NOT describe this as "draws during the
experiment" — these are periodic lab draws over time.
"""

    # Build intelligence preamble (goals, data inventory, data maturity, first-person voice)
    preamble_block = ""
    if _HAS_INTELLIGENCE_COMMON:
        try:
            _inventory = build_data_inventory()
            _maturity = build_data_maturity(_inventory)
            _goals = load_goals_config()
            preamble_block = build_coach_preamble(
                coach_name=p['name'],
                domain=expert_key,
                goals=_goals,
                inventory=_inventory,
                maturity=_maturity,
            )
            # Builder's Paradox: inject into mind coach prompt
            if expert_key == "mind":
                try:
                    from intelligence_common import compute_builders_paradox_score
                    bp = compute_builders_paradox_score(days=7)
                    bp_block = (
                        f"\nBUILDER'S PARADOX CHECK:\n"
                        f"This week's score: {bp['score']}/100 ({bp['label']})\n"
                        f"Platform tasks completed: {bp['platform_tasks']}\n"
                        f"Workouts: {bp['workouts']}\n"
                        f"Journal entries: {bp['journal_entries']}\n"
                        f"Habit adherence: {bp['habit_adherence_pct']}%\n"
                        f"Avg daily steps: {bp['avg_steps']}\n"
                        f"\n{bp['interpretation']}\n"
                        f"\nIf score > 50: You MUST address this directly. Not as a side note — "
                        f"as the lead finding. The question to ask: \"Is the building serving "
                        f"the transformation, or replacing it?\" Be direct. Matthew respects "
                        f"honesty over comfort.\n"
                    )
                    preamble_block += bp_block
                except Exception as _bp_e:
                    logger.warning("Builder's Paradox computation failed: %s", _bp_e)
            # V2.1: Thread injection — persistent memory for each coach
            try:
                _personality = p.get("personality", {})
                _thread_block = build_thread_prompt_block(expert_key, personality=_personality)
                if _thread_block:
                    preamble_block += "\n" + _thread_block
            except Exception as _th_e:
                logger.warning("Thread injection failed for %s: %s", expert_key, _th_e)
        except Exception as _e:
            logger.warning("Preamble generation failed: %s — proceeding without", _e)
            preamble_block = f"VOICE: Write in FIRST PERSON. You ARE {p['name']}. Say \"I\" not \"{p['name']}\". Address Matthew directly as \"you\".\n"
    else:
        preamble_block = f"VOICE: Write in FIRST PERSON. You ARE {p['name']}. Say \"I\" not \"{p['name']}\". Address Matthew directly as \"you\".\n"

    return f"""You are {p['name']}, {p['title']}.

Your communication style: {p['style']}.
Your analytical focus: {p['focus']}.
{p.get('epistemology', '')}

{preamble_block}

You are writing your weekly analysis for Matthew's public health experiment (averagejoematt.com).
This is Week {week_num} of the experiment (started {EXPERIMENT_START}, now day {days_in_experiment}).
Your analysis is the CENTERPIECE of the observatory page — it appears at position 2,
immediately after the key metrics. Returning readers come back specifically to read
what you have to say this week. This is a weekly appointment, not a generic report.

ANALYTICAL LENS FOR THIS WEEK: {lens}
{labs_context}

Here is Matthew's current data:
{data_json}

{prior_block}

Write a 2-3 paragraph analysis (200-300 words). Requirements:

STRUCTURE:
- Paragraph 1: Open with ONE specific, concrete observation. Lead with the number
  that caught your attention. Use "What strikes me most..." or "The figure I keep
  returning to..." or "The pattern worth naming..." — vary your opening each week.
- Paragraph 2: Interpret the pattern. What does it mean clinically/practically?
  Connect to another domain if relevant (sleep affects glucose, training affects
  recovery, etc.). Use your expertise to say something a dashboard cannot.
- Paragraph 3: One specific, actionable suggestion for the coming week. Be concrete
  enough that Matthew can do it tomorrow. Not "sleep more" but "try anchoring sleep
  onset to within a 30-minute window each night."

VOICE:
- First person as yourself. You are a real expert having a weekly conversation.
- Reference specific numbers naturally — don't list them, weave them into insight.
- Be honest. If the data is concerning, say so. If it's encouraging, explain why
  without being sycophantic. If it's too early to draw conclusions, say that.
- Write as if Matthew and 500 subscribers are reading this on Wednesday morning
  with their coffee. Be worth their time.
- Do NOT use bullet points, headers, or formatting. Flowing prose only.
- Vary sentence length. Mix short declarative sentences with longer analytical ones.

FRESHNESS REQUIREMENTS:
- Never open with "Looking at the data..." or "This week's data shows..." — these
  are the equivalent of "Dear Sir/Madam" in a letter. Be specific immediately.
- Each weekly analysis should feel like a different chapter, not a form letter.
- If you find yourself writing a sentence that could appear in any week's analysis,
  delete it and write something specific to THIS week.

After your analysis, on separate lines write exactly:
KEY RECOMMENDATION: [One specific behavioral action for this week. 1-2 sentences max. Concrete enough to act on tomorrow.]
ELENA QUOTE: [One sentence in Elena Voss's voice — third person, literary journalist. Elena sees what YOUR discipline blinds you to. If you focused on sleep architecture, she notices the journal entry about late-night screen time. If you talked macros, she sees the emotional eating pattern. She names the cross-domain observation you would make if you could see outside your own expertise. Example: "Five nights of data and his body is already telling a quieter story than the hours suggest." Never aspirational — just the observation the expert missed.]
{"JOURNALING PROMPT: [A single reflective question for Matthew — something he can sit with before writing. Make it specific to what the data revealed this week. If the Builder's Paradox score is above 50, the prompt MUST address the building-vs-doing tension: e.g., 'Is the building serving the transformation this week, or the other way around?']" if expert_key == "mind" else ""}

Write only the analysis — no preamble, no "Here is my analysis:", just paragraphs followed by the tagged lines."""


def generate_and_cache(expert_key):
    logger.info(f"Generating analysis for expert: {expert_key}")
    data = gather_data_for_expert(expert_key)

    # Read prior analysis + recommendation to prevent repetition
    prior_summary = ""
    prior_recommendation = ""
    try:
        prior = table.get_item(Key={"pk": CACHE_PK, "sk": f"EXPERT#{expert_key}"}).get("Item")
        if prior:
            if prior.get("analysis"):
                prior_summary = str(prior["analysis"])[:300]
            if prior.get("key_recommendation"):
                prior_recommendation = str(prior["key_recommendation"])[:200]
    except Exception:
        pass
    if prior_summary:
        data["_prior_analysis_summary"] = prior_summary
    if prior_recommendation:
        data["_prior_recommendation"] = prior_recommendation

    days_in = max(1, (datetime.now(timezone.utc).date() - datetime.strptime(EXPERIMENT_START, "%Y-%m-%d").date()).days + 1)
    week_number = max(1, days_in // 7 + 1)
    prompt = build_prompt(expert_key, data, days_in, week_number)
    api_key = _get_api_key()

    req_body = json.dumps({
        "model": AI_MODEL,
        "max_tokens": 1200,
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

    # V3.1: Extract tagged fields — split from bottom up to avoid capture leaks
    key_recommendation = ""
    journaling_prompt = ""
    elena_quote = ""
    # ELENA QUOTE is last in the output
    if "ELENA QUOTE:" in analysis_text:
        parts = analysis_text.rsplit("ELENA QUOTE:", 1)
        analysis_text = parts[0].rstrip()
        elena_quote = parts[1].strip().strip('"').strip('\u201c').strip('\u201d')
        # Extract any JOURNALING PROMPT that leaked into elena_quote
        if "JOURNALING PROMPT:" in elena_quote:
            eq_parts = elena_quote.split("JOURNALING PROMPT:", 1)
            elena_quote = eq_parts[0].strip().strip('"').strip('\u201c').strip('\u201d')
            if not journaling_prompt:
                journaling_prompt = eq_parts[1].strip()
    # JOURNALING PROMPT comes before ELENA QUOTE (Mind page only)
    if "JOURNALING PROMPT:" in analysis_text:
        parts = analysis_text.rsplit("JOURNALING PROMPT:", 1)
        analysis_text = parts[0].rstrip()
        journaling_prompt = parts[1].strip()
    if "KEY RECOMMENDATION:" in analysis_text:
        parts = analysis_text.rsplit("KEY RECOMMENDATION:", 1)
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
        "week_number": week_number,
        "days_in_experiment": days_in,
        "ttl": ttl,
    }
    if key_recommendation:
        item["key_recommendation"] = key_recommendation
    if journaling_prompt:
        item["journaling_prompt"] = journaling_prompt
    if elena_quote:
        item["elena_quote"] = elena_quote
    table.put_item(Item=item)

    # Intelligence Validator V2: post-generation quality check
    if _HAS_INTELLIGENCE_COMMON:
        try:
            from intelligence_common import validate_coach_output, write_quality_results
            _inventory = build_data_inventory()
            _maturity = build_data_maturity(_inventory)
            _flags = validate_coach_output(
                coach_id=expert_key, domain=expert_key,
                narrative=analysis_text, inventory=_inventory,
                maturity=_maturity,
            )
            today_str = now.strftime("%Y-%m-%d")
            write_quality_results(today_str, expert_key, expert_key, _flags)
            if _flags:
                err_count = sum(1 for f in _flags if f["severity"] == "error")
                warn_count = sum(1 for f in _flags if f["severity"] == "warning")
                logger.warning(
                    "Quality flags for %s: %d errors, %d warnings — %s",
                    expert_key, err_count, warn_count,
                    "; ".join(f["detail"] for f in _flags[:3]),
                )
        except Exception as _ve:
            logger.warning("Intelligence validator failed for %s: %s", expert_key, _ve)

    # V2.1: Thread extraction — extract and write coach thread entry
    if _HAS_INTELLIGENCE_COMMON and analysis_text:
        try:
            thread_data = extract_thread_from_narrative(expert_key, analysis_text, api_key)
            thread_data["generation_context"] = "observatory"
            write_coach_thread(expert_key, thread_data)
            logger.info("Thread entry written for %s: investment=%s, %d predictions",
                        expert_key,
                        thread_data.get("emotional_investment", "?"),
                        len(thread_data.get("predictions", [])))
        except Exception as _te:
            logger.warning("Thread extraction/write failed for %s: %s", expert_key, _te)

    logger.info(f"Cached analysis for {expert_key}: {len(analysis_text)} chars")
    return analysis_text


def generate_synthesis(all_coach_outputs):
    """
    Second-pass synthesis: Dr. Kai Nakamura reads all coach outputs and produces
    a single weekly priority + cross-domain context notes for each observatory page.
    """
    if not all_coach_outputs or len(all_coach_outputs) < 2:
        logger.info("Synthesis skipped — fewer than 2 coach outputs")
        return None

    try:
        goals = load_goals_config() if _HAS_INTELLIGENCE_COMMON else {}
    except Exception:
        goals = {}

    coach_sections = "\n\n".join(
        f"--- {domain.upper()} COACH ---\n{text[:800]}"
        for domain, text in all_coach_outputs.items()
        if text
    )

    goals_json = json.dumps({
        "mission": goals.get("mission", ""),
        "targets": goals.get("targets", {}),
        "philosophy": goals.get("philosophy", ""),
    }, indent=2, default=str)

    prompt = f"""You are Dr. Kai Nakamura, Integrative Health Director. You've just read assessments from all domain coaches. Your job: synthesize, resolve contradictions, and make ONE call.

Matthew's goals: {goals_json}

Coach assessments:
{coach_sections}

Write in first person. You are Nakamura. Be decisive.

Produce EXACTLY this JSON structure (no markdown, no explanation):
{{
  "weekly_priority": "One paragraph. One action. What matters most right now given where Matthew is vs where he's trying to go? If coaches disagree, make the call and say why. Do not hedge.",
  "cross_domain_notes": {{
    "sleep": "1-2 sentences connecting sleep to the other domains this week",
    "nutrition": "1-2 sentences connecting nutrition to the other domains",
    "training": "1-2 sentences connecting training to the other domains",
    "glucose": "1-2 sentences connecting glucose to the other domains",
    "physical": "1-2 sentences connecting physical/body comp to the other domains",
    "mind": "1-2 sentences connecting mind/behavioral to the other domains"
  }}
}}"""

    api_key = _get_api_key()
    req_body = json.dumps({
        "model": AI_MODEL,
        "max_tokens": 1200,
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

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read())

        text = "".join(
            b["text"] for b in result.get("content", []) if b.get("type") == "text"
        )

        # Parse JSON from response (strip markdown fencing if present)
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        synthesis = json.loads(cleaned.strip())

        # Cache synthesis to DDB
        now = datetime.now(timezone.utc)
        ttl = int((now + timedelta(days=8)).timestamp())
        item = {
            "pk": CACHE_PK,
            "sk": "EXPERT#integrator",
            "expert_key": "integrator",
            "analysis": synthesis.get("weekly_priority", ""),
            "cross_domain_notes": synthesis.get("cross_domain_notes", {}),
            "generated_at": now.isoformat(),
            "week_number": max(1, (now.date() - datetime.strptime(EXPERIMENT_START, "%Y-%m-%d").date()).days // 7 + 1),
            "ttl": ttl,
        }
        table.put_item(Item=item)
        logger.info("Synthesis generated and cached: %d chars priority, %d domain notes",
                     len(synthesis.get("weekly_priority", "")),
                     len(synthesis.get("cross_domain_notes", {})))
        return synthesis

    except Exception as e:
        logger.error("Synthesis generation failed: %s", e)
        return None


def lambda_handler(event, context):
    try:
        target = event.get("expert", "all")
        experts_to_run = EXPERTS if target == "all" else [target]
        results = {}
        all_outputs = {}

        for expert_key in experts_to_run:
            if expert_key not in EXPERTS:
                logger.warning(f"Unknown expert: {expert_key}")
                continue
            try:
                text = generate_and_cache(expert_key)
                results[expert_key] = {"status": "ok", "chars": len(text)}
                all_outputs[expert_key] = text
            except Exception as e:
                logger.error(f"Failed to generate {expert_key}: {e}")
                results[expert_key] = {"status": "error", "error": str(e)}

        # Synthesis pass — only when running all experts
        if target == "all" and len(all_outputs) >= 3:
            try:
                synthesis = generate_synthesis(all_outputs)
                if synthesis:
                    results["integrator"] = {"status": "ok", "chars": len(str(synthesis))}
            except Exception as e:
                logger.error(f"Synthesis failed: {e}")
                results["integrator"] = {"status": "error", "error": str(e)}

        return {
            "statusCode": 200,
            "body": json.dumps(results, default=str),
        }
    except Exception as e:
        logger.error(f"Handler failed: {e}")
        raise
