"""
ai_calls.py — Anthropic API call functions for the Daily Brief.

Extracted from daily_brief_lambda.py (Phase 2 monolith extraction).
Handles all four AI calls plus data-summary builders consumed by those calls.

Exports:
  init(s3_client, bucket, has_board_loader)  — must call before using module
  call_anthropic(prompt, api_key, max_tokens) — raw Anthropic API call
  call_training_nutrition_coach(data, profile, api_key)
  call_journal_coach(data, profile, api_key)
  call_board_of_directors(data, profile, day_grade, grade, component_scores, api_key, ...)
  call_tldr_and_guidance(data, profile, day_grade, grade, ...)
  build_data_summary(data, profile)           — shared data dict for AI prompts
  build_food_summary(data)
  build_activity_summary(data)
  build_workout_summary(data)
"""

import json
import time
import urllib.error
import urllib.request

# ==============================================================================
# MODULE STATE (set by init())
# ==============================================================================

_s3 = None
_S3_BUCKET = None
_HAS_BOARD_LOADER = False
_board_loader = None


def init(s3_client, bucket, has_board_loader, board_loader_module=None):
    """Inject shared dependencies. Call once at Lambda startup."""
    global _s3, _S3_BUCKET, _HAS_BOARD_LOADER, _board_loader
    _s3 = s3_client
    _S3_BUCKET = bucket
    _HAS_BOARD_LOADER = has_board_loader
    _board_loader = board_loader_module


# ==============================================================================
# INLINE UTILITIES
# ==============================================================================

def _safe_float(rec, field, default=None):
    if rec and field in rec:
        try: return float(rec[field])
        except Exception: return default
    return default

def _avg(vals):
    v = [x for x in vals if x is not None]
    return round(sum(v)/len(v), 1) if v else None


# ==============================================================================
# DATA SUMMARY BUILDERS (used by AI prompt construction)
# ==============================================================================

def build_data_summary(data, profile):
    journal = data.get("journal") or {}
    mf = data.get("macrofactor") or {}
    strava = data.get("strava") or {}
    habitify = data.get("habitify") or {}
    apple = data.get("apple") or {}
    sleep = data.get("sleep") or {}
    return {
        "date": data.get("date"),
        "recovery_score": _safe_float(data.get("whoop"), "recovery_score"),
        "strain": _safe_float(data.get("whoop"), "strain"),
        "sleep_score": _safe_float(sleep, "sleep_score"),
        "sleep_duration_hrs": _safe_float(sleep, "sleep_duration_hours"),
        "sleep_efficiency_pct": _safe_float(sleep, "sleep_efficiency_pct"),
        "deep_sleep_pct": _safe_float(sleep, "deep_pct"),
        "rem_sleep_pct": _safe_float(sleep, "rem_pct"),
        "hrv_yesterday": data["hrv"].get("hrv_yesterday"),
        "hrv_7d_avg": data["hrv"].get("hrv_7d"),
        "hrv_30d_avg": data["hrv"].get("hrv_30d"),
        "calories": _safe_float(mf, "total_calories_kcal"),
        "protein_g": _safe_float(mf, "total_protein_g"),
        "fat_g": _safe_float(mf, "total_fat_g"),
        "carbs_g": _safe_float(mf, "total_carbs_g"),
        "fiber_g": _safe_float(mf, "total_fiber_g"),
        "steps": _safe_float(apple, "steps"),
        "water_ml": _safe_float(apple, "water_intake_ml"),
        "glucose_avg": _safe_float(apple, "blood_glucose_avg"),
        "glucose_tir": _safe_float(apple, "blood_glucose_time_in_range_pct"),
        "glucose_std_dev": _safe_float(apple, "blood_glucose_std_dev"),
        "glucose_min": _safe_float(apple, "blood_glucose_min"),
        "walking_speed_mph": _safe_float(apple, "walking_speed_mph"),
        "walking_step_length_in": _safe_float(apple, "walking_step_length_in"),
        "walking_asymmetry_pct": _safe_float(apple, "walking_asymmetry_pct"),
        "habits_completed": _safe_float(habitify, "total_completed"),
        "habits_possible": _safe_float(habitify, "total_possible"),
        "exercise_count": _safe_float(strava, "activity_count"),
        "exercise_minutes": round((_safe_float(strava, "total_moving_time_seconds") or 0) / 60, 1),
        "journal_mood": journal.get("mood_avg"),
        "journal_energy": journal.get("energy_avg"),
        "journal_stress": journal.get("stress_avg"),
        "current_weight": data.get("latest_weight"),
        "week_ago_weight": data.get("week_ago_weight"),
        "tsb": data.get("tsb"),
        "sleep_debt_7d_hrs": data.get("sleep_debt_7d_hrs"),
    }


def build_food_summary(data):
    mf = data.get("macrofactor") or {}
    food_log = mf.get("food_log", [])
    if not food_log:
        return "No food log data."
    meals = []
    for item in food_log:
        name = item.get("food_name", "?")
        cal = item.get("calories_kcal", 0)
        prot = item.get("protein_g", 0)
        t = item.get("time", "?")
        meals.append(str(t) + " - " + str(name) + " (" + str(round(float(cal))) + " cal, " + str(round(float(prot))) + "g P)")
    return "\n".join(meals)


def build_activity_summary(data):
    """Extract activity details from Strava."""
    strava = data.get("strava") or {}
    activities = strava.get("activities", [])
    if not activities:
        return "No activities recorded."
    lines = []
    for a in activities:
        name = a.get("name", "Activity")
        sport = a.get("sport_type", "?")
        duration_min = round((a.get("moving_time_seconds") or 0) / 60)
        avg_hr = a.get("average_heartrate")
        max_hr_act = a.get("max_heartrate")
        start = a.get("start_date_local", "")
        time_part = start.split("T")[1][:5] if "T" in start else "?"
        line = time_part + " - " + name + " (" + sport + ", " + str(duration_min) + " min"
        if avg_hr:
            line += ", avg HR " + str(round(avg_hr))
        if max_hr_act:
            line += ", max HR " + str(round(max_hr_act))
        line += ")"
        lines.append(line)
    return "\n".join(lines)


def build_workout_summary(data):
    """v2.2: Extract exercise-level detail from MacroFactor workouts."""
    mf_workouts = data.get("mf_workouts")
    if not mf_workouts:
        return "No strength training data."
    workouts = mf_workouts.get("workouts", [])
    if not workouts:
        return "No strength training data."
    lines = []
    for w in workouts:
        w_name = w.get("workout_name", "Workout")
        lines.append("WORKOUT: " + w_name)
        exercises = w.get("exercises", [])
        for ex in exercises:
            ex_name = ex.get("exercise_name", "?")
            sets = ex.get("sets", [])
            set_strs = []
            for s in sets:
                reps = s.get("reps", 0)
                weight = s.get("weight_lbs", 0)
                rir = s.get("rir")
                st = str(reps)
                if weight:
                    st += "@" + str(round(float(weight))) + "lb"
                if rir is not None:
                    st += " (RIR " + str(rir) + ")"
                set_strs.append(st)
            lines.append("  " + ex_name + ": " + ", ".join(set_strs))
        total_vol = mf_workouts.get("total_volume_lbs")
        total_sets = mf_workouts.get("total_sets")
        if total_vol:
            lines.append("Total volume: " + str(round(float(total_vol))) + " lbs, " + str(round(float(total_sets or 0))) + " sets")
    return "\n".join(lines)


# ==============================================================================
# ANTHROPIC API
# ==============================================================================

def call_anthropic(prompt, api_key, max_tokens=200):
    payload = json.dumps({
        "model": "claude-sonnet-4-6",
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}]
    }).encode()
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=payload,
        headers={"Content-Type": "application/json", "x-api-key": api_key,
                 "anthropic-version": "2023-06-01"}, method="POST")
    for attempt in range(1, 3):
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                resp = json.loads(r.read())
                return resp["content"][0]["text"].strip()
        except urllib.error.HTTPError as e:
            print("[WARN] Anthropic HTTP " + str(e.code) + " attempt " + str(attempt))
            if attempt < 2 and e.code in (429, 529, 500, 502, 503, 504):
                time.sleep(5)
            else:
                raise
        except urllib.error.URLError as e:
            print("[WARN] Anthropic network error attempt " + str(attempt) + ": " + str(e))
            if attempt < 2:
                time.sleep(5)
            else:
                raise


# ==============================================================================
# AI PROMPT HELPERS
# ==============================================================================

def _build_weight_context(data, profile):
    """Dynamic weight context for AI prompts."""
    start_w = profile.get("journey_start_weight_lbs", 302)
    goal_w = profile.get("goal_weight_lbs", 185)
    current_w = data.get("latest_weight")
    if current_w:
        lost = round(start_w - current_w, 1)
        remaining = round(current_w - goal_w, 1)
        return (f"Started at {start_w} lbs, currently {round(current_w, 1)} lbs, "
                f"goal {goal_w} lbs ({lost} lost so far, {remaining} to go)")
    return f"{start_w}->{goal_w} lbs"


def _build_recent_training_summary(data):
    """Summarize last 7 days of training for AI context."""
    strava_7d = data.get("strava_7d") or []
    if not strava_7d:
        return "No activities in last 7 days."
    lines = []
    for day_rec in strava_7d:
        date_str = day_rec.get("sk", "").replace("DATE#", "")
        activities = day_rec.get("activities", [])
        for a in activities:
            name = a.get("name", "Activity")
            sport = a.get("sport_type", "?")
            dur = round((a.get("moving_time_seconds") or 0) / 60)
            lines.append(f"{date_str}: {name} ({sport}, {dur} min)")
    return "\n".join(lines) if lines else "No activities in last 7 days."


# ==============================================================================
# AI CALLS
# ==============================================================================

def call_training_nutrition_coach(data, profile, api_key):
    """AI call: Training coach + Nutritionist combined."""
    data_summary = build_data_summary(data, profile)
    food_summary = build_food_summary(data)
    activity_summary = build_activity_summary(data)
    workout_summary = build_workout_summary(data)
    weight_ctx = _build_weight_context(data, profile)
    recent_training = _build_recent_training_summary(data)

    prompt = """You are two coaches speaking to Matthew, a 36yo man in Phase 1 of weight loss (""" + weight_ctx + """, 1800 cal/day, 190g protein target).
Tone: direct, specific, no-BS. Reference specific numbers.

LAST 7 DAYS TRAINING CONTEXT:
""" + recent_training + """

STRAVA ACTIVITIES YESTERDAY:
""" + activity_summary + """

STRENGTH TRAINING DETAIL (from MacroFactor):
""" + workout_summary + """

FOOD LOG YESTERDAY (with timestamps):
""" + food_summary + """

MACRO TOTALS: """ + json.dumps({k: data_summary[k] for k in ["calories", "protein_g", "fat_g", "carbs_g", "fiber_g"] if k in data_summary}, default=str) + """
TARGETS: 1800 cal, P190g, F60g, C125g

INSTRUCTIONS:
- For TRAINING: Give per-activity feedback. For strength sessions, comment on exercise selection, volume, intensity (RIR), and how it connects to goals. For casual walks, just a brief NEAT acknowledgment. Do NOT give generic training advice. IMPORTANT: Consider the 7-day training context above. If yesterday was a rest day or light day after recent strength sessions, acknowledge that recovery is appropriate — do NOT panic about "zero strength training".
- For NUTRITION: Comment on macro adherence AND meal timing/distribution. When was protein consumed? Any long gaps? Be specific about what to adjust TODAY. Reference actual food items from the log.

Respond in EXACTLY this JSON format, no other text:
{"training": "2-4 sentences from sports scientist. Per-activity analysis. Reference specific exercises, sets, weights. Brief for walks.", "nutrition": "2-3 sentences from nutritionist about macro adherence + meal timing. Reference specific foods and timestamps. What to adjust today."}"""

    try:
        raw = call_anthropic(prompt, api_key, max_tokens=450)
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()
        return json.loads(cleaned)
    except Exception as e:
        print("[WARN] Training/nutrition coach failed: " + str(e))
        return {}


def call_journal_coach(data, profile, api_key):
    journal_entries = data.get("journal_entries", [])
    if not journal_entries:
        return ""
    texts = []
    for e in journal_entries[:3]:
        raw = e.get("raw_text", "")
        if raw:
            texts.append(raw[:500])
    if not texts:
        return ""
    journal_text = "\n---\n".join(texts)
    obstacles = profile.get("primary_obstacles", [])
    obstacles_str = ", ".join(obstacles) if obstacles else "none specified"
    weight_ctx = _build_weight_context(data, profile)

    prompt = """You are a wise, warm-but-direct inner coach reading Matthew's journal from yesterday. He's 36, on a weight loss journey (""" + weight_ctx + """), battling: """ + obstacles_str + """.

His coaching tone: Jocko's discipline meets Attia's precision meets Brene Brown's vulnerability.

JOURNAL ENTRIES:
""" + journal_text + """

Write EXACTLY two parts separated by " || ":
Part 1: A perspective/reflection on what he wrote — something profound, motivating, or reframing. Not a summary. A mirror that shows him something he might not see. 2 sentences max.
Part 2: One specific tactical thing he can try JUST TODAY that would make a material difference based on what he wrote. Be concrete (e.g. "practice box breathing for 30 seconds before each meal" or "text one person you're grateful for before noon"). 1 sentence.

Format: [reflection] || [tactical thing]
No labels, no formatting. Natural voice. Max 80 words total."""

    try:
        return call_anthropic(prompt, api_key, max_tokens=250)
    except Exception as e:
        print("[WARN] Journal coach failed: " + str(e))
        return ""


# -- Board of Directors prompt builder -----------------------------------------

_FALLBACK_BOD_INTRO = None  # replaced by dynamic _build_daily_bod_intro_from_config()


def _build_daily_bod_intro_from_config(data=None, profile=None):
    """Build the Board of Directors role intro from S3 config."""
    if not _HAS_BOARD_LOADER or not _board_loader:
        return None

    config = _board_loader.load_board(_s3, _S3_BUCKET)
    if not config:
        return None

    members = _board_loader.get_feature_members(config, "daily_brief")
    if not members:
        return None

    panel_parts = []
    for mid, member, feat_cfg in members:
        role = feat_cfg.get("role", "unified_panel")
        if role == "unified_panel":
            title = member.get("title", member["name"])
            contribution = feat_cfg.get("contribution", "")
            panel_parts.append(f"{title} ({contribution})" if contribution else title)

    panel_desc = " + ".join(panel_parts) if panel_parts else "sports scientist + nutritionist + sleep specialist + behavioral coach"

    protocol_note = ""
    for mid, member, feat_cfg in members:
        if feat_cfg.get("role") == "protocol_tips":
            protocol_note = f"\n{member['name']} provides: {feat_cfg.get('contribution', 'protocol recommendations')}"

    weight_ctx = _build_weight_context(data, profile) if data and profile else "302->185 lbs"
    intro = f"""You are the Board of Directors for Project40 — {panel_desc} — unified.
Speaking to Matthew, 36yo, weight loss journey ({weight_ctx}). Phase 1 Ignition: 3 lbs/week, 1500 kcal deficit, 1800 cal daily.
Tone: direct, empathetic, no-BS.{protocol_note}"""

    print("[INFO] Using config-driven daily BoD prompt")
    return intro


def call_board_of_directors(data, profile, day_grade, grade, component_scores, api_key,
                             character_sheet=None, brief_mode="standard"):
    data_summary = build_data_summary(data, profile)
    comp_lines = []
    for comp, score in component_scores.items():
        label = comp.replace("_", " ").title()
        val = str(score) + "/100" if score is not None else "no data"
        comp_lines.append("  " + label + ": " + val)
    component_summary = "\n".join(comp_lines)
    obstacles = profile.get("primary_obstacles", [])
    health_ctx = "Primary obstacles: " + ", ".join(obstacles) + "." if obstacles else ""
    journal_ctx = ""
    journal_entries = data.get("journal_entries", [])
    if journal_entries:
        texts = []
        for e in journal_entries[:3]:
            raw = e.get("raw_text", "")
            if raw:
                texts.append(raw[:300])
        if texts:
            journal_ctx = "JOURNAL ENTRIES:\n" + "\n---\n".join(texts)

    # Habit context from registry
    registry = profile.get("habit_registry", {})
    habitify = data.get("habitify") or {}
    h_map = habitify.get("habits", {})
    missed_t0 = []
    missed_t1 = []
    for h_name, meta in registry.items():
        if meta.get("status") != "active" or meta.get("tier", 2) > 1:
            continue
        done = h_map.get(h_name, 0)
        if not (done is not None and float(done) >= 1):
            why = meta.get("why_matthew", "")
            tier = meta.get("tier", 2)
            if tier == 0:
                missed_t0.append(h_name + (" — " + why[:80] if why else ""))
            elif tier == 1:
                missed_t1.append(h_name)
    habit_ctx = ""
    if missed_t0:
        habit_ctx += "\nMISSED TIER 0 (non-negotiable): " + "; ".join(missed_t0)
    if missed_t1:
        habit_ctx += "\nMISSED TIER 1 (high priority): " + ", ".join(missed_t1[:8])

    # Synergy group analysis
    synergy_misses = {}
    for h_name, meta in registry.items():
        if meta.get("status") != "active":
            continue
        sg = meta.get("synergy_group")
        if not sg:
            continue
        done = h_map.get(h_name, 0)
        if not (done is not None and float(done) >= 1):
            synergy_misses.setdefault(sg, []).append(h_name)
    for sg, misses in synergy_misses.items():
        total_in_group = sum(1 for _, m in registry.items() if m.get("synergy_group") == sg and m.get("status") == "active")
        if len(misses) >= total_in_group * 0.5 and total_in_group >= 3:
            habit_ctx += "\nSYNERGY ALERT: " + sg + " stack mostly missing (" + ", ".join(misses[:5]) + ")"

    # Character sheet context
    character_ctx = ""
    if character_sheet:
        cs_level = character_sheet.get("character_level", 1)
        cs_tier = character_sheet.get("character_tier", "Foundation")
        cs_events = character_sheet.get("level_events", [])
        cs_effects = character_sheet.get("active_effects", [])
        character_ctx = "\nCHARACTER SHEET: Level " + str(cs_level) + " (" + cs_tier + ")"
        for pn in ["sleep", "movement", "nutrition", "metabolic", "mind", "relationships", "consistency"]:
            pd = character_sheet.get("pillar_" + pn, {})
            character_ctx += "\n  " + pn.capitalize() + ": Level " + str(pd.get("level", "?")) + " (" + str(pd.get("tier", "?")) + ") raw=" + str(pd.get("raw_score", "?"))
        if cs_events:
            character_ctx += "\nLEVEL EVENTS TODAY:"
            for ev in cs_events:
                ev_type = ev.get("type", "")
                if "tier" in ev_type:
                    character_ctx += "\n  " + ev.get("pillar", "").capitalize() + ": " + str(ev.get("old_tier", "")) + " → " + str(ev.get("new_tier", ""))
                elif "character" in ev_type:
                    character_ctx += "\n  Character Level " + str(ev.get("old_level", "")) + " → " + str(ev.get("new_level", ""))
                else:
                    arrow = "↑" if "up" in ev_type else "↓"
                    character_ctx += "\n  " + arrow + " " + ev.get("pillar", "").capitalize() + " Level " + str(ev.get("old_level", "")) + " → " + str(ev.get("new_level", ""))
        if cs_effects:
            character_ctx += "\nACTIVE EFFECTS: " + ", ".join(e.get("name", "") for e in cs_effects)

    # Try config-driven intro, fall back to dynamic default
    bod_intro = _build_daily_bod_intro_from_config(data, profile)
    if not bod_intro:
        print("[INFO] Using fallback dynamic daily BoD prompt")
        weight_ctx = _build_weight_context(data, profile)
        bod_intro = ("You are the Board of Directors for Project40 — sports scientist + nutritionist + sleep specialist + behavioral coach unified.\n"
                     f"Speaking to Matthew, 36yo, weight loss journey ({weight_ctx}). Phase 1 Ignition: 3 lbs/week, 1500 kcal deficit, 1800 cal daily.\n"
                     "Tone: direct, empathetic, no-BS.")

    prompt = bod_intro + """
""" + health_ctx + """

YESTERDAY'S DATA:
""" + json.dumps(data_summary, indent=2, default=str) + """

DAY GRADE: """ + str(day_grade if day_grade is not None else "N/A") + "/100 (" + grade + """)
""" + component_summary + """
""" + habit_ctx + """
""" + character_ctx + """
""" + journal_ctx + """

Write 2-3 sentences. Reference specific numbers (at least two). Connect yesterday to today. Celebrate wins briefly, name gaps directly — if a Tier 0 habit was missed, NAME it. If a synergy stack is broken, note it. If there are LEVEL EVENTS, mention them — these are rare and meaningful. If there are ACTIVE EFFECTS like Sleep Drag, note the impact. DO NOT start with "Matthew". Max 60 words."""

    if brief_mode == "flourishing":
        prompt += "\n\nTONE: He is FLOURISHING — engagement is high, habits strong, trajectory improving. Lead with reinforcement. Be energising. Name what's working specifically. One brief forward-looking note."
    elif brief_mode == "struggling":
        prompt += "\n\nTONE: He is in a ROUGH PATCH — engagement is low, habits slipping. Be warm, not clinical. Acknowledge the difficulty without piling on. Focus on the smallest possible next right action. No guilt."

    return call_anthropic(prompt, api_key, max_tokens=200)


def call_tldr_and_guidance(data, profile, day_grade, grade, component_scores, component_details,
                            readiness_score, readiness_colour, api_key):
    """v2.2: Combined TL;DR + Smart Guidance — one AI call that returns both."""
    data_summary = build_data_summary(data, profile)

    # Missed habits context
    habitify = data.get("habitify") or {}
    habits_map = habitify.get("habits", {})
    registry = profile.get("habit_registry", {})
    missed_mvp = []
    missed_context = []
    if registry:
        for h_name, meta in registry.items():
            if meta.get("status") != "active" or meta.get("tier", 2) > 1:
                continue
            done = habits_map.get(h_name, 0)
            if not (done is not None and float(done) >= 1):
                missed_mvp.append(h_name)
                why = meta.get("why_matthew", "")
                if why:
                    missed_context.append(h_name + " (T" + str(meta.get("tier", "?")) + "): " + why[:60])
    else:
        mvp_list = profile.get("mvp_habits", [])
        for h in mvp_list:
            done = habits_map.get(h, 0)
            if not (done is not None and float(done) >= 1):
                missed_mvp.append(h)

    comp_lines = []
    for comp, score in component_scores.items():
        if score is not None:
            comp_lines.append(comp.replace("_", " ") + ": " + str(score))
        elif comp == "hydration":
            comp_lines.append("hydration: NO DATA (Apple Health sync gap — do not give hydration tips)")

    sleep = data.get("sleep") or {}
    sleep_arch = ""
    deep = _safe_float(sleep, "deep_pct")
    rem = _safe_float(sleep, "rem_pct")
    if deep is not None:
        sleep_arch = "Deep: " + str(round(deep)) + "%, REM: " + str(round(rem or 0)) + "%"

    weight_ctx = _build_weight_context(data, profile)

    prompt = """You are the intelligence engine behind Matthew's Life Platform daily brief. Your job: synthesize ALL of yesterday's data into (1) one TL;DR sentence and (2) 3-4 smart, personalized guidance items for TODAY.

Matthew: 36yo, weight loss journey (""" + weight_ctx + """). Phase 1: 1800 cal/day, 190g protein, 16:8 IF.

YESTERDAY'S SIGNALS:
- Day grade: """ + str(day_grade) + "/100 (" + grade + """)
- Components: """ + ", ".join(comp_lines) + """
- Recovery/readiness: """ + str(readiness_score) + " (" + readiness_colour + """)
- HRV: """ + str(data_summary.get("hrv_yesterday")) + "ms yesterday, 7d avg " + str(data_summary.get("hrv_7d_avg")) + "ms, 30d avg " + str(data_summary.get("hrv_30d_avg")) + """ms
- TSB (training stress balance): """ + str(data_summary.get("tsb")) + """
- Sleep: """ + str(data_summary.get("sleep_duration_hrs")) + "hrs, score " + str(data_summary.get("sleep_score")) + ", efficiency " + str(data_summary.get("sleep_efficiency_pct")) + "%. " + sleep_arch + """
- 7-day sleep debt: """ + str(data.get("sleep_debt_7d_hrs")) + """hrs
- Calories: """ + str(data_summary.get("calories")) + "/1800, Protein: " + str(data_summary.get("protein_g")) + """/190g
- Glucose: avg """ + str(data_summary.get("glucose_avg")) + " mg/dL, TIR " + str(data_summary.get("glucose_tir")) + """%, overnight low """ + str(data_summary.get("glucose_min")) + """ mg/dL
- Gait: walking speed """ + str(data_summary.get("walking_speed_mph")) + " mph, step length " + str(data_summary.get("walking_step_length_in")) + " in, asymmetry " + str(data_summary.get("walking_asymmetry_pct")) + """%
- Steps: """ + str(data_summary.get("steps")) + """
- Weight: """ + str(data_summary.get("current_weight")) + " lbs (week ago: " + str(data_summary.get("week_ago_weight")) + """)
- Missed habits: """ + (", ".join(missed_mvp) if missed_mvp else "none — all completed") + """
- Missed habit context: """ + ("; ".join(missed_context[:5]) if missed_context else "n/a") + """
- Journal mood: """ + str(data_summary.get("journal_mood")) + "/5, stress: " + str(data_summary.get("journal_stress")) + """/5

RULES:
- TL;DR: One sentence, max 20 words. The single most important takeaway from yesterday. Specific. Not generic.
- Guidance: 3-4 items, each with an emoji prefix and 1 sentence. These must be SMART — derived from the data above, not static advice. Each item should be something that could ONLY apply to TODAY given this specific data combination. Avoid repeating daily constants (IF window, supplements, bedtime) unless there is a data-driven reason to modify them today.
- Examples of smart guidance: "HRV down 15% + high stress yesterday — do Zone 2 instead of planned HIIT", "Protein 40g short yesterday — front-load with 50g shake before first meal", "3.2hr sleep debt this week — prioritize nap or 30min earlier bedtime tonight"
- Examples of BAD guidance (too generic): "Stay hydrated", "Get 7.5 hours of sleep", "Caffeine cutoff at noon"
- NEVER suggest hydration tips if hydration shows NO DATA — the sync is broken, not the behaviour. Suggesting hydration when we have no data is misleading.

Respond in EXACTLY this JSON format, no other text:
{"tldr": "One sentence TL;DR", "guidance": ["emoji + sentence 1", "emoji + sentence 2", "emoji + sentence 3"]}"""

    try:
        raw = call_anthropic(prompt, api_key, max_tokens=400)
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()
        return json.loads(cleaned)
    except Exception as e:
        print("[WARN] TL;DR+Guidance failed: " + str(e))
        return {}
