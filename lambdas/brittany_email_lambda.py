"""
Brittany Weekly Email — v1.1.0
Fires Sunday 9:30 AM PT (17:30 UTC) via EventBridge.

Design philosophy: narrative-first, not a data dashboard.
Brittany is Matthew's partner, not his doctor. She doesn't need Whoop scores.
She needs to understand how he's doing emotionally and how to show up for him.

Structure:
  - Hero: Elena's one-line narrative lede
  - At a glance: 3 plain-English signals (mood/energy, sleep quality, week grade — no jargon)
  - Weight: one honest sentence of context
  - The Board sections — the centrepiece:
      💚 Rodriguez: How He's Feeling (emotional/behavioural state)
      🧠 Conti: What's Happening Underneath (psychological patterns)
      🤝 Murthy: How to Show Up for Him (specific, actionable)
      💪 The Chair: His Body This Week (physical synthesis, plain English)
  - Footer: warm one-liner about the platform

Board: Full consultation. Rodriguez/Conti/Murthy are primary authors.
Physical board (Chen/Webb/Park/Okafor/Attia/Huberman/Patrick/Norton) synthesised
by The Chair into plain English for a partner audience.
"""

import json
import logging
import os
import time
import boto3
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone, date
from decimal import Decimal
from collections import defaultdict

# OBS-1: Structured logger — JSON output for CloudWatch Logs Insights
try:
    from platform_logger import get_logger
    logger = get_logger("brittany-weekly")
except ImportError:
    logger = logging.getLogger("brittany-weekly")
    logger.setLevel(logging.INFO)

_REGION    = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
SENDER     = os.environ["EMAIL_SENDER"]
RECIPIENT  = os.environ.get("BRITTANY_EMAIL", "awsdev@mattsusername.com")
ANTHROPIC_SECRET = os.environ.get("ANTHROPIC_SECRET", "life-platform/ai-keys")

dynamodb = boto3.resource("dynamodb", region_name=_REGION)
table    = dynamodb.Table(TABLE_NAME)
ses      = boto3.client("sesv2", region_name=_REGION)
secrets  = boto3.client("secretsmanager", region_name=_REGION)


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def get_api_key():
    secret = secrets.get_secret_value(SecretId=ANTHROPIC_SECRET)
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

def avg(vals):
    v = [x for x in vals if x is not None]
    return round(sum(v) / len(v), 1) if v else None

def query_range(source, start_date, end_date):
    pk = "USER#matthew#SOURCE#" + source
    records = {}
    kwargs = {
        "KeyConditionExpression": "pk = :pk AND sk BETWEEN :s AND :e",
        "ExpressionAttributeValues": {":pk": pk, ":s": "DATE#" + start_date, ":e": "DATE#" + end_date},
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

def query_journal_range(start_date, end_date):
    entries_by_date = defaultdict(list)
    kwargs = {
        "KeyConditionExpression": "pk = :pk AND sk BETWEEN :s AND :e",
        "ExpressionAttributeValues": {
            ":pk": "USER#matthew#SOURCE#notion",
            ":s": "DATE#" + start_date + "#journal#",
            ":e": "DATE#" + end_date + "#journal#zzz",
        },
    }
    while True:
        resp = table.query(**kwargs)
        for item in resp.get("Items", []):
            date_str = item["sk"].split("#")[1]
            entries_by_date[date_str].append(d2f(item))
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    return dict(entries_by_date)

def fetch_profile():
    try:
        r = table.get_item(Key={"pk": "USER#matthew", "sk": "PROFILE#v1"})
        return d2f(r.get("Item", {}))
    except Exception as e:
        print("[ERROR] fetch_profile: " + str(e))
        return {}

def _normalize_whoop_sleep(item):
    out = dict(item)
    if "sleep_quality_score" in item and "sleep_score" not in item:
        out["sleep_score"] = item["sleep_quality_score"]
    try:
        dur = float(item.get("sleep_duration_hours") or 0)
    except Exception:
        dur = 0
    if dur > 0:
        for src_field, pct_field in [("slow_wave_sleep_hours", "deep_pct"), ("rem_sleep_hours", "rem_pct")]:
            val = item.get(src_field)
            if val is not None and pct_field not in item:
                try: out[pct_field] = round(float(val) / dur * 100, 1)
                except Exception: pass
    return out


# ══════════════════════════════════════════════════════════════════════════════
# DATA GATHERING
# ══════════════════════════════════════════════════════════════════════════════

def gather_all():
    today   = datetime.now(timezone.utc).date()
    w_end   = (today - timedelta(days=1)).isoformat()
    w_start = (today - timedelta(days=7)).isoformat()
    print("[INFO] Gathering " + w_start + " → " + w_end)

    profile = fetch_profile()
    sources = ["whoop", "apple_health", "macrofactor", "habitify", "strava", "withings", "day_grade"]
    raw = {}
    for src in sources:
        raw[src] = query_range(src, w_start, w_end)
        print("  " + src + ": " + str(len(raw[src])) + " records")

    journal = query_journal_range(w_start, w_end)
    print("  journal: " + str(len(journal)) + " days")

    # ── Sleep (Whoop SOT) ──
    sleep_scores, sleep_durations = [], []
    for r in raw["whoop"].values():
        r = _normalize_whoop_sleep(r)
        s = safe_float(r, "sleep_score")
        d = safe_float(r, "sleep_duration_hours")
        if s: sleep_scores.append(s)
        if d: sleep_durations.append(d)

    sleep_score_avg = avg(sleep_scores)
    sleep_dur_avg   = avg(sleep_durations)
    nights          = len(sleep_scores)

    # Plain-English sleep quality
    if sleep_score_avg is None:
        sleep_quality_label = "no data"
    elif sleep_score_avg >= 80:
        sleep_quality_label = "good"
    elif sleep_score_avg >= 60:
        sleep_quality_label = "mixed"
    else:
        sleep_quality_label = "poor"

    # ── Recovery ──
    recoveries = [safe_float(r, "recovery_score") for r in raw["whoop"].values() if safe_float(r, "recovery_score") is not None]
    hrvs = [safe_float(r, "hrv") for r in raw["whoop"].values() if safe_float(r, "hrv") is not None]
    recovery_avg = avg(recoveries)

    # ── Mood / Journal ──
    mood_scores, energy_scores, stress_scores = [], [], []
    all_themes, all_emotions, all_avoidance, all_defense = [], [], [], []
    notable_quotes = []
    for date_str, entries in journal.items():
        for entry in entries:
            m = entry.get("enriched_mood") or entry.get("morning_mood") or entry.get("day_rating")
            e = entry.get("enriched_energy") or entry.get("morning_energy") or entry.get("energy_eod")
            s = entry.get("enriched_stress") or entry.get("stress_level")
            if m is not None: mood_scores.append(float(m))
            if e is not None: energy_scores.append(float(e))
            if s is not None: stress_scores.append(float(s))
            for t in (entry.get("enriched_themes") or []): all_themes.append(str(t))
            for em in (entry.get("enriched_emotions") or []): all_emotions.append(str(em))
            for av in (entry.get("enriched_avoidance_flags") or []): all_avoidance.append(str(av))
            for df in (entry.get("enriched_defense_patterns") or []): all_defense.append(str(df))
            q = entry.get("enriched_notable_quote")
            if q: notable_quotes.append({"date": date_str, "quote": str(q)})

    theme_freq = defaultdict(int)
    for t in all_themes: theme_freq[t] += 1
    emotion_freq = defaultdict(int)
    for em in all_emotions: emotion_freq[em] += 1

    mood_avg   = avg(mood_scores)
    energy_avg = avg(energy_scores)
    stress_avg = avg(stress_scores)

    # Plain-English mood label
    if mood_avg is None:
        mood_label = "no data"
    elif mood_avg >= 4:
        mood_label = "positive"
    elif mood_avg >= 3:
        mood_label = "neutral"
    else:
        mood_label = "struggling"

    # ── Nutrition ──
    cals  = [safe_float(r, "total_calories_kcal") for r in raw["macrofactor"].values() if safe_float(r, "total_calories_kcal")]
    prots = [safe_float(r, "total_protein_g")     for r in raw["macrofactor"].values() if safe_float(r, "total_protein_g")]
    cal_target  = profile.get("calorie_target", 1800)
    prot_target = profile.get("protein_target_g", 190)
    cal_hit_rate  = round(sum(1 for c in cals if c <= cal_target * 1.1) / len(cals) * 100) if cals else None
    prot_hit_rate = round(sum(1 for p in prots if p >= prot_target) / len(prots) * 100) if prots else None
    days_logged   = len(raw["macrofactor"])

    # ── Training ──
    total_acts = 0
    zone2_mins = 0
    max_hr     = profile.get("max_heart_rate", 186)
    z2_low, z2_high = max_hr * 0.60, max_hr * 0.70
    for r in raw["strava"].values():
        for a in r.get("activities", []):
            total_acts += 1
            hr   = float(a.get("average_heartrate") or 0)
            mins = float(a.get("moving_time_seconds") or 0) / 60
            if hr and z2_low <= hr <= z2_high:
                zone2_mins += mins

    # ── Weight ──
    weight_rows = [(d, safe_float(r, "weight_lbs")) for d, r in sorted(raw["withings"].items()) if safe_float(r, "weight_lbs")]
    weight_latest    = weight_rows[-1][1] if weight_rows else None
    weight_week_start = weight_rows[0][1] if weight_rows else None
    goal             = profile.get("goal_weight_lbs", 185)
    journey_start    = profile.get("journey_start_weight_lbs", 302)
    week_delta       = round(weight_latest - weight_week_start, 1) if weight_latest and weight_week_start else None
    lbs_lost         = round(journey_start - weight_latest, 1) if weight_latest else None
    lbs_to_go        = round(weight_latest - goal, 1) if weight_latest else None
    pct_to_goal      = round(lbs_lost / (journey_start - goal) * 100) if lbs_lost and (journey_start - goal) > 0 else None

    # ── Habits ──
    mvp_pcts = [safe_float(r, "completion_pct") for r in raw["habitify"].values() if safe_float(r, "completion_pct") is not None]
    habit_avg_pct = round(avg([p * 100 for p in mvp_pcts])) if mvp_pcts else None

    # ── Day grades ──
    grade_vals = [safe_float(r, "total_score") for r in raw["day_grade"].values() if safe_float(r, "total_score")]
    day_grade_avg = avg(grade_vals)
    days_graded   = len(grade_vals)

    # Plain-English week summary
    if day_grade_avg is None:
        week_summary = "no data"
    elif day_grade_avg >= 80:
        week_summary = "strong week"
    elif day_grade_avg >= 65:
        week_summary = "solid week"
    elif day_grade_avg >= 50:
        week_summary = "mixed week"
    else:
        week_summary = "tough week"

    return {
        "sleep": {
            "score_avg": sleep_score_avg,
            "duration_avg": sleep_dur_avg,
            "nights": nights,
            "quality_label": sleep_quality_label,
        },
        "recovery": {
            "avg": recovery_avg,
            "hrv_avg": avg(hrvs),
        },
        "mood": {
            "mood_avg": mood_avg,
            "energy_avg": energy_avg,
            "stress_avg": stress_avg,
            "mood_label": mood_label,
            "entries": sum(len(e) for e in journal.values()),
            "days_journaled": len(journal),
            "top_themes": sorted(theme_freq.items(), key=lambda x: -x[1])[:5],
            "top_emotions": sorted(emotion_freq.items(), key=lambda x: -x[1])[:5],
            "avoidance_flags": list(dict.fromkeys(all_avoidance))[:4],
            "defense_patterns": list(dict.fromkeys(all_defense))[:4],
            "notable_quotes": notable_quotes[:2],
        },
        "nutrition": {
            "calories_avg": avg(cals),
            "protein_avg": avg(prots),
            "days_logged": days_logged,
            "cal_hit_rate": cal_hit_rate,
            "prot_hit_rate": prot_hit_rate,
            "cal_target": cal_target,
            "prot_target": prot_target,
        },
        "training": {
            "activity_count": total_acts,
            "zone2_minutes": round(zone2_mins),
            "zone2_target": 150,
        },
        "weight": {
            "latest": weight_latest,
            "week_delta": week_delta,
            "lbs_lost": lbs_lost,
            "lbs_to_go": lbs_to_go,
            "pct_to_goal": pct_to_goal,
            "goal": goal,
            "journey_start": journey_start,
        },
        "habits": {
            "avg_pct": habit_avg_pct,
            "days_tracked": len(raw["habitify"]),
        },
        "day_grade": {
            "avg": day_grade_avg,
            "days": days_graded,
            "week_summary": week_summary,
        },
        "dates": {"start": w_start, "end": w_end},
        "journey_week": max(1, ((today - date(2026, 2, 22)).days // 7) + 1),
        "profile": profile,
    }


# ══════════════════════════════════════════════════════════════════════════════
# AI PROMPT
# ══════════════════════════════════════════════════════════════════════════════

BOARD_PROMPT = """You are writing Brittany's weekly update about Matthew — her partner.
Matthew is on a major health transformation: losing weight, building fitness, improving sleep.
He tracks everything obsessively. This email is for Brittany so she understands how he's doing
and how to be a great partner to him this week.

IMPORTANT CONTEXT ABOUT MATTHEW:
- 36 years old, Senior Director at a SaaS company in Seattle
- He is in week {journey_week} of his transformation. He has lost {lbs_lost} lbs and has {lbs_to_go} lbs to go. His target is roughly 10 months away from when he started (February 2026). When referencing where he is in his journey, be accurate: he is early — a few weeks in — not in the middle. Do NOT say "10% of the way there" or imply he’s halfway. If you can’t reference his timeline accurately, don’t mention it at all.
- He tends to intellectualise his feelings and rarely asks for help directly
- High-achiever who can be hard on himself when he falls short
- Tracking obsessively is part coping mechanism, part genuine commitment to change

THIS WEEK'S DATA (plain language context only — do NOT repeat these numbers in your writing):
- Overall week: {week_summary}
- Mood: {mood_label} (avg {mood_avg}/5 across journal entries)
- Energy: {energy_avg}/5 average
- Stress: {stress_avg}/5 average (higher = more stressed)
- Sleep quality: {sleep_quality_label} ({sleep_score_avg}% avg Whoop score, {nights} nights tracked)
- Sleep duration: {sleep_dur_avg} hrs/night average
- Recovery: {recovery_avg}% average (Whoop)
- Training: {activity_count} workouts this week
- Nutrition: logged food {days_logged}/7 days, hit calorie target {cal_hit_rate}% of days, protein target {prot_hit_rate}% of days
- Journal themes: {top_themes}
- Emotional patterns: {top_emotions}
- Avoidance flags: {avoidance_flags}
- Defence patterns: {defense_patterns}
- Notable journal quotes: {notable_quotes}

WRITING RULES (strictly follow these):
- Write TO Brittany. Warm, personal, direct.
- NO jargon. Don't say "Whoop recovery" or "HRV" or "Zone 2". Translate everything to plain English.
- NEVER mention specific numbers except in context where it's meaningful and already translated
  (e.g. "he slept just over 6 hours most nights" is fine; "sleep score 61%" is not)
- Do NOT mention exact calorie counts, pound amounts, or Whoop scores anywhere in your response
- Be honest. If it was a hard week, say so clearly but compassionately.
- Each section has one specific job. Don't repeat content across sections.
- Short, clear paragraphs. This is an email, not a report.
- Speak to Brittany's intelligence — she knows Matthew well.
- Do NOT use markdown formatting. No ##, no **, no ---, no bullet points. Plain text only.
- Do NOT mention percentage of goal completion, gamification levels, or frame him as being at the start/early in his journey. Focus on this week's effort and what it means.

Write EXACTLY these five sections with EXACTLY these headers (include the emoji):

🪞 THIS WEEK IN ONE LINE
One sentence only. A journalist's opening line — specific, honest, narrative. Not a summary.
Capture the emotional texture of the week. Reference something real.

💚 HOW HE'S FEELING — COACH RODRIGUEZ
Coach Maya Rodriguez specialises in the psychology of behaviour change. She reads the whole picture.
3 short paragraphs. Cover: What is Matthew's emotional state this week? What's driving it?
What should Brittany know about where he is right now — not just the data, but the person?

🧠 WHAT'S HAPPENING UNDERNEATH — DR. CONTI
Dr. Conti is a psychiatrist who pays attention to what's not being said.
3 short paragraphs. Cover: What psychological patterns are showing up this week?
What might Matthew be protecting himself from? What does Brittany need to understand
about how to reach him — not what to do, but how to be with him?

🤝 HOW TO SHOW UP FOR HIM — DR. MURTHY
Dr. Vivek Murthy is the world's leading expert on connection and loneliness.
His research shows close relationships are the single strongest predictor of health outcomes.
3 short paragraphs. What does Matthew actually need from Brittany this week?
Specific to where he is right now. End with one concrete, small thing she can do in the next 48 hours.

💪 HIS BODY THIS WEEK — THE CHAIR
The Chair synthesises the full medical panel's view (sports science, nutrition, sleep medicine,
longevity, psychiatry) into plain English for Brittany.
2 short paragraphs. How is he doing physically — honestly? Is the body supporting the mind
or fighting it this week? What does Brittany need to know about his physical state to understand
his energy and mood levels?

Be warm. Be honest. Be human."""


def build_commentary(data):
    api_key = get_api_key()
    mood    = data["mood"]
    sl      = data["sleep"]
    tr      = data["training"]
    nu      = data["nutrition"]
    w       = data["weight"]
    rec     = data["recovery"]
    dg      = data["day_grade"]

    def fmt(v, fallback="unknown"):
        return str(round(v, 1)) if v is not None else fallback

    prompt = BOARD_PROMPT.format(
        week_summary    = dg.get("week_summary", "unknown"),
        mood_label      = mood.get("mood_label", "unknown"),
        mood_avg        = fmt(mood.get("mood_avg")),
        energy_avg      = fmt(mood.get("energy_avg")),
        stress_avg      = fmt(mood.get("stress_avg")),
        sleep_quality_label = sl.get("quality_label", "unknown"),
        sleep_score_avg = fmt(sl.get("score_avg")),
        nights          = sl.get("nights", 0),
        sleep_dur_avg   = fmt(sl.get("duration_avg")),
        recovery_avg    = fmt(rec.get("avg")),
        activity_count  = tr.get("activity_count", 0),
        days_logged     = nu.get("days_logged", 0),
        cal_hit_rate    = fmt(nu.get("cal_hit_rate"), "unknown"),
        prot_hit_rate   = fmt(nu.get("prot_hit_rate"), "unknown"),
        top_themes      = ", ".join(t for t, _ in mood.get("top_themes", [])[:4]) or "none",
        top_emotions    = ", ".join(e for e, _ in mood.get("top_emotions", [])[:4]) or "none",
        avoidance_flags = ", ".join(mood.get("avoidance_flags", [])) or "none",
        defense_patterns = ", ".join(mood.get("defense_patterns", [])) or "none",
        notable_quotes  = " | ".join('"' + q["quote"] + '"' for q in mood.get("notable_quotes", [])) or "none",
        pct_to_goal     = w.get("pct_to_goal", 0),
        lbs_lost        = fmt(w.get("lbs_lost")),
        lbs_to_go       = fmt(w.get("lbs_to_go")),
        journey_week    = data.get("journey_week", 1),
    )

    payload = json.dumps({
        "model": "claude-sonnet-4-6",
        "max_tokens": 1400,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages", data=payload,
        headers={"Content-Type": "application/json", "x-api-key": api_key,
                 "anthropic-version": "2023-06-01"}, method="POST")

    for attempt in range(1, 3):
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                resp = json.loads(r.read())
                text = resp["content"][0]["text"]
                print("[DEBUG] Raw response (first 300): " + text[:300])
                return text
        except urllib.error.HTTPError as e:
            print("[WARN] Anthropic HTTP " + str(e.code) + " attempt " + str(attempt))
            if attempt < 2 and e.code in (429, 529, 500, 502, 503):
                time.sleep(5)
            else:
                raise
    return ""


# ══════════════════════════════════════════════════════════════════════════════
# SECTION PARSER
# ══════════════════════════════════════════════════════════════════════════════

def parse_sections(text):
    """Split AI output into named sections by header emoji."""
    key_map = {
        "🪞": "lede",
        "💚": "rodriguez",
        "🧠": "conti",
        "🤝": "murthy",
        "💪": "chair",
    }
    sections = {}
    current_key = None
    current_lines = []
    for line in text.strip().split("\n"):
        # Strip markdown heading/bold markers (e.g. ## 🪞 or **🪞) that Sonnet may add
        cleaned = line.strip().lstrip("#").lstrip("*").strip()
        matched = None
        for emoji, key in key_map.items():
            if cleaned.startswith(emoji):
                matched = key
                break
        if matched:
            if current_key is not None:
                sections[current_key] = "\n".join(current_lines).strip()
            current_key = matched
            current_lines = [line]
        elif current_key is not None:
            current_lines.append(line)
    if current_key is not None:
        sections[current_key] = "\n".join(current_lines).strip()
    return sections


# ══════════════════════════════════════════════════════════════════════════════
# HTML BUILDER
# ══════════════════════════════════════════════════════════════════════════════

def section_html(raw_text, accent_color, bg_color, label_color):
    """Render a board section as clean HTML paragraphs."""
    if not raw_text:
        return ""
    lines = raw_text.strip().split("\n")
    html = ""
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        # Header line (has emoji)
        is_header = any(stripped.startswith(e) for e in ["🪞", "💚", "🧠", "🤝", "💪"])
        if is_header:
            html += (
                '<p style="font-size:12px;font-weight:700;color:' + label_color + ';'
                'text-transform:uppercase;letter-spacing:1px;margin:0 0 14px;">'
                + stripped + '</p>'
            )
        else:
            html += (
                '<p style="font-size:15px;color:#2d3748;line-height:1.8;margin:0 0 14px;">'
                + stripped + '</p>'
            )
    return (
        '<div style="background:' + bg_color + ';border-left:4px solid ' + accent_color + ';'
        'border-radius:0 12px 12px 0;padding:24px 28px;margin-bottom:16px;">'
        + html
        + '</div>'
    )

def weight_sentence(w):
    """One honest sentence about weight progress."""
    if not w.get("latest"):
        return ""
    delta = w.get("week_delta")
    lbs_lost = w.get("lbs_lost")
    lbs_to_go = w.get("lbs_to_go")
    pct = w.get("pct_to_goal")

    if delta is not None and delta < 0:
        direction = "down " + str(abs(delta)) + " lbs"
    elif delta is not None and delta > 0:
        direction = "up " + str(delta) + " lbs"
    else:
        direction = "holding steady"

    parts = [direction + " this week"]
    if lbs_lost:
        parts.append(str(lbs_lost) + " lbs lost overall")
    if pct:
        parts.append(str(pct) + "% of the way to his goal")

    return " · ".join(parts)

def signal_dot(label, good, neutral=None):
    """A simple coloured status indicator."""
    if good is None:
        color = "#9ca3af"
        symbol = "○"
    elif good:
        color = "#059669"
        symbol = "●"
    elif neutral is not None and neutral:
        color = "#d97706"
        symbol = "●"
    else:
        color = "#dc2626"
        symbol = "●"
    return (
        '<span style="display:inline-flex;align-items:center;gap:6px;'
        'font-size:13px;color:#4b5563;margin-right:20px;">'
        '<span style="color:' + color + ';font-size:10px;">' + symbol + '</span>'
        + label + '</span>'
    )

def build_html(data, commentary_text):
    sections = parse_sections(commentary_text)
    w   = data["weight"]
    sl  = data["sleep"]
    dg  = data["day_grade"]
    mood = data["mood"]
    dates = data["dates"]

    print("[DEBUG] Parsed sections: " + str(list(sections.keys())))
    print("[DEBUG] Lede: " + sections.get("lede", "(empty)")[:80])

    try:
        start_dt = datetime.strptime(dates["start"], "%Y-%m-%d")
        end_dt   = datetime.strptime(dates["end"], "%Y-%m-%d")
        week_label = start_dt.strftime("%b %-d") + " – " + end_dt.strftime("%b %-d, %Y")
    except Exception:
        week_label = dates["start"] + " – " + dates["end"]

    # ── Lede ──
    lede_text = ""
    for line in sections.get("lede", "").split("\n"):
        stripped = line.strip()
        if stripped and not stripped.startswith("🪞"):
            lede_text = stripped
            break

    lede_block = ""
    if lede_text:
        lede_block = (
            '<div style="background:linear-gradient(135deg,#fdf6ec,#fef9f0);'
            'border-radius:14px;padding:24px 28px;margin-bottom:28px;'
            'border-left:4px solid #f59e0b;">'
            '<p style="font-size:11px;color:#b45309;text-transform:uppercase;'
            'letter-spacing:1px;margin:0 0 8px;font-weight:700;">This week</p>'
            '<p style="font-size:17px;color:#78350f;line-height:1.65;margin:0;'
            'font-style:italic;">' + lede_text + '</p>'
            '</div>'
        )

    # ── At a glance: 3 plain signals ──
    mood_avg = mood.get("mood_avg")
    sl_score = sl.get("score_avg")
    dg_avg   = dg.get("avg")
    dg_label = dg.get("week_summary", "")

    mood_good    = mood_avg >= 3.5 if mood_avg is not None else None
    mood_neutral = mood_avg >= 2.5 if mood_avg is not None else None
    sleep_good   = sl_score >= 70 if sl_score is not None else None
    sleep_neutral = sl_score >= 55 if sl_score is not None else None
    grade_good   = dg_avg >= 70 if dg_avg is not None else None
    grade_neutral = dg_avg >= 55 if dg_avg is not None else None

    mood_dot_label  = "Mood: " + mood.get("mood_label", "unknown")
    sleep_dot_label = "Sleep: " + sl.get("quality_label", "unknown")
    grade_dot_label = "Week: " + dg_label

    glance_block = (
        '<div style="background:#f8fafc;border-radius:12px;padding:18px 24px;'
        'margin-bottom:20px;border:1px solid #e2e8f0;">'
        '<p style="font-size:11px;font-weight:700;color:#94a3b8;text-transform:uppercase;'
        'letter-spacing:1px;margin:0 0 10px;">At a glance</p>'
        '<div style="display:flex;flex-wrap:wrap;gap:4px;">'
        + signal_dot(mood_dot_label, mood_good, mood_neutral)
        + signal_dot(sleep_dot_label, sleep_good, sleep_neutral)
        + signal_dot(grade_dot_label, grade_good, grade_neutral)
        + '</div></div>'
    )

    # ── Weight sentence ── (removed per design: Brittany doesn't need raw numbers)
    weight_block = ""

    # ── Separator ── (no label — Brittany knows who these people are)
    sep = '<div style="border-top:1px solid #e5e7eb;margin:28px 0;"></div>'

    # ── Board sections ──
    rodriguez_block = section_html(sections.get("rodriguez", ""), "#22c55e", "#f0fdf4", "#15803d")
    conti_block     = section_html(sections.get("conti", ""),     "#a855f7", "#faf5ff", "#7e22ce")
    murthy_block    = section_html(sections.get("murthy", ""),    "#3b82f6", "#eff6ff", "#1e40af")
    chair_block     = section_html(sections.get("chair", ""),     "#6b7280", "#f9fafb", "#374151")

    # ── Notable quote ──
    quote_block = ""
    for q in mood.get("notable_quotes", [])[:1]:
        quote_block = (
            '<div style="border-left:3px solid #818cf8;padding:14px 20px;'
            'margin:28px 0;background:#eef2ff;border-radius:0 10px 10px 0;">'
            '<p style="font-size:14px;font-style:italic;color:#4338ca;margin:0 0 6px;">'
            '"' + q["quote"] + '"</p>'
            '<p style="font-size:11px;color:#818cf8;margin:0;">From his journal · ' + q["date"] + '</p>'
            '</div>'
        )

    return """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
</head>
<body style="margin:0;padding:0;background:#f1f5f9;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,sans-serif;">
<div style="max-width:600px;margin:28px auto;background:#fff;border-radius:16px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,0.07);">

  <!-- Header -->
  <div style="background:linear-gradient(135deg,#1a1a2e 0%,#2d1b69 100%);padding:28px 32px;">
    <p style="color:#a78bfa;font-size:11px;text-transform:uppercase;letter-spacing:2px;margin:0 0 6px;font-weight:700;">For Brittany · Weekly Update</p>
    <h1 style="color:#fff;font-size:22px;font-weight:800;margin:0 0 4px;">How Matthew's Week Went</h1>
    <p style="color:#c4b5fd;font-size:13px;margin:0;">""" + week_label + """</p>
  </div>

  <!-- Body -->
  <div style="padding:32px;">
    """ + lede_block + """
    """ + glance_block + """
    """ + weight_block + """
    """ + sep + """
    """ + rodriguez_block + """
    """ + conti_block + """
    """ + murthy_block + """
    """ + chair_block + """
    """ + quote_block + """
  </div>

  <!-- Footer -->
  <div style="background:#f8fafc;padding:18px 32px;border-top:1px solid #e2e8f0;">
    <p style="color:#94a3b8;font-size:12px;margin:0;line-height:1.6;">
      This weekly update is prepared by Matthew's Life Platform — a personal health tracking system
      he built as part of his transformation journey. It's sent to you because you matter to him and
      to his success. 💜
    </p>
  </div>

</div>
</body>
</html>"""


# ══════════════════════════════════════════════════════════════════════════════
# HANDLER
# ══════════════════════════════════════════════════════════════════════════════

def lambda_handler(event, context):
    logger.set_date(datetime.now(timezone.utc).strftime("%Y-%m-%d"))  # OBS-1
    logger.info("Brittany Weekly Email v1.1.0 starting...")
    data = gather_all()

    logger.info("Calling Sonnet 4.6 for Board commentary...")
    try:
        commentary = build_commentary(data)
        logger.info("Commentary length: %s chars", len(commentary))
        # AI-3: validate output before rendering
        try:
            from ai_output_validator import validate_ai_output, AIOutputType
            _val = validate_ai_output(commentary, AIOutputType.WEEKLY_DIGEST)
            if _val.was_replaced:
                logger.warning("[AI-3] Brittany commentary replaced with fallback: %s", _val.failure_reason)
            commentary = _val.final_text
        except ImportError:
            pass
    except Exception as e:
        logger.warning("AI call failed: %s", e)
        commentary = (
            "💚 HOW HE'S FEELING — COACH RODRIGUEZ\n"
            "Commentary unavailable this week.\n\n"
            "💪 HIS BODY THIS WEEK — THE CHAIR\n"
            "Check back next week."
        )

    html = build_html(data, commentary)

    dates   = data["dates"]
    subject = "Matthew's Week · " + dates["end"]

    ses.send_email(
        FromEmailAddress=SENDER,
        Destination={"ToAddresses": [RECIPIENT]},
        Content={"Simple": {
            "Subject": {"Data": subject, "Charset": "UTF-8"},
            "Body":    {"Html": {"Data": html, "Charset": "UTF-8"}},
        }},
    )
    print("[INFO] Sent to " + RECIPIENT + ": " + subject)
    return {"statusCode": 200, "body": "Brittany email v1.1.0 sent: " + subject}
