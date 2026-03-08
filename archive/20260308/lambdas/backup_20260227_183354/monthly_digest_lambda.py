"""
Monthly Coach's Letter Lambda — v1.0.0
Fires first Sunday of each month at 16:00 UTC (8am PT).
EventBridge cron: cron(0 16 ? * 1#1 *)

Delivers a narrative coach's letter: 30-day current vs 30-day prior month,
same 6-person council as weekly digest, annual goals tracking,
condensed section summaries.
"""

import json
import os
import logging
import math
import statistics
import time
import boto3
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from decimal import Decimal

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# ── AWS clients ───────────────────────────────────────────────────────────────

# ── Config (env vars with backwards-compatible defaults) ──
REGION     = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
USER_ID    = os.environ.get("USER_ID", "matthew")

dynamodb = boto3.resource("dynamodb", region_name=REGION)
table    = dynamodb.Table(TABLE_NAME)
ses      = boto3.client("sesv2", region_name=REGION)
secrets  = boto3.client("secretsmanager", region_name=REGION)

RECIPIENT         = "awsdev@mattsusername.com"
SENDER            = "awsdev@mattsusername.com"
PROTEIN_TARGET_G  = 180
CALORIE_TARGET    = 1800
GOAL_WEIGHT_LBS   = 220.0
ZONE2_HR_LOW      = 110
ZONE2_HR_HIGH     = 129


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS  (same patterns as weekly digest)
# ══════════════════════════════════════════════════════════════════════════════

def get_anthropic_key():
    secret = secrets.get_secret_value(SecretId="life-platform/anthropic")
    return json.loads(secret["SecretString"])["api_key"]

def d2f(obj):
    if isinstance(obj, list):    return [d2f(i) for i in obj]
    if isinstance(obj, dict):    return {k: d2f(v) for k, v in obj.items()}
    if isinstance(obj, Decimal): return float(obj)
    return obj

def fetch_range(source, start, end):
    try:
        r = table.query(
            KeyConditionExpression="pk = :pk AND sk BETWEEN :s AND :e",
            ExpressionAttributeValues={":pk": f"USER#{USER_ID}#SOURCE#{source}",
                                       ":s": f"DATE#{start}", ":e": f"DATE#{end}"})
        return r.get("Items", [])
    except Exception: return []

def avg(vals):
    v = [x for x in vals if x is not None]
    return round(sum(v)/len(v), 1) if v else None

def fmt(val, unit="", dec=1):
    return "—" if val is None else f"{round(val, dec)}{unit}"


# ══════════════════════════════════════════════════════════════════════════════
# DATE WINDOWS
# ══════════════════════════════════════════════════════════════════════════════

def get_date_windows():
    today = datetime.now(timezone.utc).date()

    # Current month: last 30 days up through yesterday
    cur_end   = (today - timedelta(days=1)).isoformat()
    cur_start = (today - timedelta(days=30)).isoformat()

    # Prior month: days 31–60 back
    prior_end   = (today - timedelta(days=31)).isoformat()
    prior_start = (today - timedelta(days=60)).isoformat()

    # Month label (the calendar month we just completed or are in)
    month_label = today.strftime("%B %Y")
    prior_label = (today.replace(day=1) - timedelta(days=1)).strftime("%B %Y")

    return {
        "cur_start": cur_start, "cur_end": cur_end,
        "prior_start": prior_start, "prior_end": prior_end,
        "month_label": month_label, "prior_label": prior_label,
    }


# ══════════════════════════════════════════════════════════════════════════════
# EXTRACTORS  (30-day versions, same logic as weekly)
# ══════════════════════════════════════════════════════════════════════════════

def ex_whoop(recs):
    if not recs: return None
    hrvs  = [float(r["hrv"])               for r in recs if "hrv"               in r]
    recov = [float(r["recovery_score"])    for r in recs if "recovery_score"    in r]
    rhrs  = [float(r["resting_heart_rate"])for r in recs if "resting_heart_rate"in r]
    strs  = [float(r["strain"])            for r in recs if "strain"            in r]
    return {"hrv_avg": avg(hrvs), "hrv_min": min(hrvs, default=None),
            "hrv_max": max(hrvs, default=None),
            "recovery_avg": avg(recov), "rhr_avg": avg(rhrs),
            "strain_avg": avg(strs), "days": len(recs)}

def ex_withings(recs):
    if not recs: return None
    weights  = [float(r["weight_lbs"])   for r in recs if "weight_lbs"   in r]
    bodyfats = [float(r["body_fat_pct"]) for r in recs if "body_fat_pct" in r]
    sr = sorted(recs, key=lambda r: r.get("sk",""), reverse=True)
    return {"weight_latest": float(sr[0]["weight_lbs"]) if sr and "weight_lbs" in sr[0] else None,
            "weight_avg": avg(weights), "weight_min": min(weights, default=None),
            "weight_max": max(weights, default=None), "body_fat_avg": avg(bodyfats),
            "measurements": len(recs)}

def ex_eightsleep(recs):
    if not recs: return None
    scores = [float(r["sleep_score"])             for r in recs if "sleep_score"          in r]
    durs   = [float(r["total_sleep_seconds"])/3600 for r in recs if "total_sleep_seconds" in r]
    effs   = [float(r["sleep_efficiency"])         for r in recs if "sleep_efficiency"     in r]
    rems   = [float(r["rem_sleep_seconds"])/3600   for r in recs if "rem_sleep_seconds"   in r]
    deeps  = [float(r["deep_sleep_seconds"])/3600  for r in recs if "deep_sleep_seconds"  in r]
    total_avg = avg(durs) or 0
    rem_pct  = round(avg(rems)  / total_avg * 100, 1) if total_avg and avg(rems)  else None
    deep_pct = round(avg(deeps) / total_avg * 100, 1) if total_avg and avg(deeps) else None
    return {"score_avg": avg(scores), "duration_avg_hrs": avg(durs),
            "efficiency_avg": avg(effs), "rem_pct": rem_pct,
            "deep_pct": deep_pct, "nights": len(recs)}

def ex_strava(recs):
    if not recs: return None
    acts = []
    zone2_mins = 0
    for r in recs:
        for a in r.get("activities", []):
            hr   = float(a.get("average_heartrate") or 0)
            secs = float(a.get("moving_time_seconds") or 0)
            obj  = {"name": a.get("enriched_name") or a.get("name",""),
                    "sport": a.get("sport_type",""),
                    "miles": round(float(a.get("distance_miles") or 0), 1),
                    "mins": round(secs/60), "hr": round(hr) if hr else None}
            acts.append(obj)
            if hr and ZONE2_HR_LOW <= hr <= ZONE2_HR_HIGH:
                zone2_mins += obj["mins"]
    total_miles = round(sum(float(r.get("total_distance_miles",0)) for r in recs), 1)
    total_mins  = round(sum(float(r.get("total_moving_time_seconds",0)) for r in recs)/60)
    z2_pct      = round(zone2_mins/total_mins*100) if total_mins else 0
    return {"total_miles": total_miles, "total_minutes": total_mins,
            "activity_count": len(acts), "zone2_minutes": round(zone2_mins),
            "zone2_pct": z2_pct,
            "total_elevation_feet": round(sum(float(r.get("total_elevation_gain_feet",0)) for r in recs))}

def ex_hevy(recs):
    if not recs: return None
    wk = []
    for r in recs:
        for w in r.get("workouts",[]):
            wk.append({"title": w.get("title",""),
                       "volume_lbs": round(float(w.get("total_volume_lbs",0)))})
    return {"workout_count": len(wk)}

def ex_macrofactor(recs):
    if not recs: return None
    cals  = [float(r["calories"])  for r in recs if "calories"  in r]
    prots = [float(r["protein_g"]) for r in recs if "protein_g" in r]
    days  = len(recs)
    return {"calories_avg": avg(cals), "protein_avg_g": avg(prots),
            "days_logged": days,
            "protein_hit_rate": round(sum(1 for p in prots if p>=PROTEIN_TARGET_G)/days*100) if days else None,
            "calorie_hit_rate": round(sum(1 for c in cals  if c<=CALORIE_TARGET   )/days*100) if days else None}

def ex_chronicling(recs):
    if not recs: return None
    scores = []
    group_totals = {}
    for r in recs:
        s = float(r["total_score"]) if "total_score" in r else None
        if s is not None: scores.append(s)
        for g, v in (r.get("group_scores") or {}).items():
            group_totals.setdefault(g, []).append(float(v))
    group_avgs = {g: avg(v) for g, v in group_totals.items()}
    sorted_groups = sorted(group_avgs.items(), key=lambda x: x[1] or 0)
    return {"score_avg": avg(scores), "group_avgs": group_avgs,
            "days": len(recs),
            "best_group":  sorted_groups[-1][0] if sorted_groups else None,
            "worst_group": sorted_groups[0][0]  if sorted_groups else None}


# ══════════════════════════════════════════════════════════════════════════════
# BANISTER (same as weekly)
# ══════════════════════════════════════════════════════════════════════════════

def compute_banister(strava_60d, today):
    kj = {}
    for r in strava_60d:
        d = str(r.get("date",""))
        if d: kj[d] = sum(float(a.get("kilojoules") or 0) for a in r.get("activities",[]))
    ctl = atl = 0.0
    cd, ad = math.exp(-1/42), math.exp(-1/7)
    for i in range(59,-1,-1):
        day = (today - timedelta(days=i)).isoformat()
        load = kj.get(day, 0)
        ctl = ctl*cd + load*(1-cd)
        atl = atl*ad + load*(1-ad)
    return {"ctl": round(ctl,1), "atl": round(atl,1), "tsb": round(ctl-atl,1)}


# ══════════════════════════════════════════════════════════════════════════════
# ANNUAL GOALS TRACKING
# ══════════════════════════════════════════════════════════════════════════════

def compute_annual_goals(cur, windows):
    """Compute progress against known 2026 annual goals."""
    today = datetime.now(timezone.utc).date()
    year_start = today.replace(month=1, day=1)
    days_elapsed = (today - year_start).days
    days_in_year = 365
    year_pct = round(days_elapsed / days_in_year * 100)

    goals = {"year_pct_elapsed": year_pct}

    # Weight goal
    w = cur.get("withings")
    if w and w.get("weight_latest"):
        try:
            p = table.get_item(Key={"pk":f"USER#{USER_ID}","sk":"PROFILE"}).get("Item",{})
            journey_start_weight = float(p.get("journey_start_weight_lbs", 300))
            goal_weight = float(p.get("goal_weight_lbs", GOAL_WEIGHT_LBS))
            journey_start_date_str = str(p.get("journey_start_date",""))
        except Exception:
            journey_start_weight = 300
            goal_weight = GOAL_WEIGHT_LBS
            journey_start_date_str = ""

        current = w["weight_latest"]
        lost    = round(journey_start_weight - current, 1)
        to_go   = round(current - goal_weight, 1)
        total   = journey_start_weight - goal_weight
        pct_complete = round(lost / total * 100) if total > 0 else 0

        # Rate: compare cur vs prior month
        goals["weight"] = {
            "current_lbs": current,
            "goal_lbs": goal_weight,
            "lost_lbs": lost,
            "to_go_lbs": to_go,
            "pct_complete": pct_complete,
            "journey_start_weight": journey_start_weight,
        }

    # Training consistency: activity count per 30 days
    st = cur.get("strava")
    if st:
        goals["training_activities_30d"] = st.get("activity_count", 0)
        goals["zone2_minutes_30d"] = st.get("zone2_minutes", 0)

    # Habit adherence monthly avg
    ch = cur.get("chronicling")
    if ch:
        goals["habit_score_avg"] = ch.get("score_avg")

    return goals


# ══════════════════════════════════════════════════════════════════════════════
# HAIKU — MONTHLY COUNCIL PROMPT
# ══════════════════════════════════════════════════════════════════════════════

MONTHLY_PROMPT = """You are the coordinating intelligence for Matthew's Monthly Health Board of Advisors.

CONTEXT:
Matthew Walker, 36, Seattle. Senior Director at a SaaS company. Goal: lose ~80 lbs, build muscle,
improve sleep and stress management. He tracks obsessively but struggles to translate data into
consistent behavioural change.

This is a MONTHLY review — not a weekly summary. Your job is to identify the arc and narrative
of the past 30 days, not describe individual weeks. Look for:
- Month-over-month directional change (improving / plateauing / declining)
- Cross-domain patterns that span the full month
- Progress against annual goals (weight trajectory, training consistency, habit adherence)
- What to focus on for the NEXT 30 days

THIS MONTH'S DATA vs PRIOR MONTH:
{data_json}

ANNUAL GOALS CONTEXT:
{goals_json}

RULES FOR ALL ADVISORS:
- This is a MONTHLY reflection — write about the month's arc, not week-by-week detail.
- Do NOT summarise numbers Matthew can already read in the data tables below.
- DO identify trends, momentum, and cross-domain patterns across the full 30 days.
- Reference specific numbers only when they illuminate a larger pattern.
- If data is missing, mock, or unavailable, say so and note what it prevents you from seeing.
- Each advisor has a distinct domain and must NOT repeat observations from others.
- Be direct. A month is long enough that patterns are real — name them clearly.

Write exactly these six sections with these exact headers:

🏋️ DR. SARAH CHEN — MONTHLY TRAINING REVIEW
Domain: training volume arc, Zone 2 base-building, CTL trajectory, periodisation, fatigue accumulation across the month.
Key question: Did Matthew build fitness this month, or just accumulate fatigue? Is Zone 2 base growing, holding, or eroding? What does the Banister CTL say about fitness direction? Recommend ONE structural change to training for next month.

🥗 DR. MARCUS WEBB — MONTHLY NUTRITION REVIEW
Domain: 30-day calorie and protein adherence, consistency vs spikes, nutrition-training interaction.
Key question: Was nutrition consistent this month, or erratic? Did the calorie/protein adherence patterns correlate with good vs bad recovery weeks? If MacroFactor is mock data, name that clearly and explain the cost. One specific nutrition adjustment for next month.

😴 DR. LISA PARK — MONTHLY SLEEP REVIEW
Domain: sleep architecture monthly averages (REM%, deep%), efficiency trend, social jetlag, cumulative sleep debt across the month.
Key question: What does 30 days of sleep data reveal that a single week cannot? Is the architecture improving, stable, or declining? Is there a circadian pattern issue (weekday vs weekend)? One structural sleep intervention for next month.

🩺 DR. JAMES OKAFOR — MONTHLY TRAJECTORY REVIEW
Domain: body composition arc, long-term indicators, what changed and what didn't across 30 days.
Key question: Month-over-month, what is the single most encouraging trend? What is the single most concerning? At current trajectory, are Matthew's 12-month goals achievable? What critical measurement is still absent that would change recommendations?

🧠 COACH MAYA RODRIGUEZ — MONTHLY BEHAVIOURAL REVIEW
Domain: a full month of habit and adherence data reveals patterns that single weeks mask.
Key question: Across 30 days, where is the genuine behavioural gap? Not the worst week — the PATTERN. What does P40 group data say about which life domain is consistently underserved? What is the one friction point Matthew hasn't solved yet? Speak directly to Matthew.

🎯 THE CHAIR — MONTHLY VERDICT & FOCUS
5–7 sentences. Give the month a clear verdict. Address weight progress and trajectory explicitly. Acknowledge what the data shows is genuinely working. Name ONE focus for the next 30 days, justified by the month's data. End with a forward-looking statement that connects this month's progress to the larger 12-month goal.

💡 INSIGHT OF THE MONTH
One sentence. Actionable over the next 30 days. Must cite real numbers. This is the single most important thing Matthew can change in April to make May's letter better.

Be honest. A month of data deserves a month's worth of insight."""


def call_anthropic_with_retry(req, timeout=30, max_attempts=2, backoff_s=5):
    """Call Anthropic API with 2-attempt retry and 5s backoff on transient errors."""
    for attempt in range(1, max_attempts + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            print(f"[WARN] Anthropic API HTTP {e.code} on attempt {attempt}/{max_attempts}")
            if attempt < max_attempts and e.code in (429, 529, 500, 502, 503, 504):
                time.sleep(backoff_s)
            else:
                raise
        except urllib.error.URLError as e:
            print(f"[WARN] Anthropic API network error on attempt {attempt}/{max_attempts}: {e}")
            if attempt < max_attempts:
                time.sleep(backoff_s)
            else:
                raise


def call_haiku_monthly(data, goals, api_key):
    clean_data  = d2f(data)
    clean_goals = d2f(goals)

    # Trim large fields for token economy
    for period in ("cur", "prior"):
        st = clean_data.get(period, {}).get("strava")
        if st and "activities" in st:
            del st["activities"]

    payload = json.dumps({
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 2500,
        "messages": [{"role": "user", "content": MONTHLY_PROMPT.format(
            data_json=json.dumps(clean_data, indent=2),
            goals_json=json.dumps(clean_goals, indent=2)
        )}]
    }).encode()
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=payload,
        headers={"Content-Type": "application/json", "x-api-key": api_key,
                 "anthropic-version": "2023-06-01"}, method="POST")
    resp = call_anthropic_with_retry(req, timeout=60)
    return resp["content"][0]["text"]


# ══════════════════════════════════════════════════════════════════════════════
# DATA ASSEMBLY
# ══════════════════════════════════════════════════════════════════════════════

def gather_all():
    today  = datetime.now(timezone.utc).date()
    wins   = get_date_windows()
    sources = ["whoop","withings","strava","eightsleep","hevy","macrofactor","todoist","chronicling"]
    extractors = {
        "whoop": ex_whoop, "withings": ex_withings, "strava": ex_strava,
        "eightsleep": ex_eightsleep, "hevy": ex_hevy, "macrofactor": ex_macrofactor,
        "chronicling": ex_chronicling,
    }

    raw_cur   = {s: fetch_range(s, wins["cur_start"],   wins["cur_end"])   for s in sources}
    raw_prior = {s: fetch_range(s, wins["prior_start"], wins["prior_end"]) for s in sources}

    cur   = {s: extractors[s](raw_cur[s])   for s in extractors}
    prior = {s: extractors[s](raw_prior[s]) for s in extractors}

    # Todoist (simple count, no extractor above)
    td_cur   = raw_cur.get("todoist",  [])
    td_prior = raw_prior.get("todoist",[])
    cur["todoist"]   = {"tasks_completed": sum(int(r.get("tasks_completed",0)) for r in td_cur),   "days": len(td_cur)}
    prior["todoist"] = {"tasks_completed": sum(int(r.get("tasks_completed",0)) for r in td_prior), "days": len(td_prior)}

    # Banister (60d Strava)
    strava_60d = fetch_range("strava",
        (today - timedelta(days=60)).isoformat(), (today - timedelta(days=1)).isoformat())
    training_load = compute_banister(strava_60d, today)

    # Profile
    try:
        p = table.get_item(Key={"pk":f"USER#{USER_ID}","sk":"PROFILE"}).get("Item",{})
        profile = {
            "goal_weight_lbs": float(p.get("goal_weight_lbs", GOAL_WEIGHT_LBS)),
            "journey_start_weight_lbs": float(p["journey_start_weight_lbs"]) if p.get("journey_start_weight_lbs") else None,
            "journey_start_date": str(p.get("journey_start_date","")),
        }
    except Exception:
        profile = {"goal_weight_lbs": GOAL_WEIGHT_LBS}

    annual_goals = compute_annual_goals(cur, wins)

    return {
        "cur": cur, "prior": prior,
        "training_load": training_load,
        "profile": profile,
        "windows": wins,
    }, annual_goals


# ══════════════════════════════════════════════════════════════════════════════
# HTML BUILDER
# ══════════════════════════════════════════════════════════════════════════════

def build_html(data, goals, commentary, windows):
    cur   = data["cur"]
    prior = data["prior"]
    tl    = data["training_load"]
    pro   = data.get("profile", {})
    month = windows["month_label"]
    prior_month = windows["prior_label"]

    def delta(cur_val, prior_val, unit="", dec=1, invert=False):
        if cur_val is None or prior_val is None: return ""
        diff = round(cur_val - prior_val, dec)
        if diff == 0: return '<span style="color:#888;font-size:11px;"> →0</span>'
        better = (diff < 0) if invert else (diff > 0)
        color  = "#27ae60" if better else "#e74c3c"
        arrow  = "↑" if diff > 0 else "↓"
        return f'<span style="color:{color};font-size:11px;"> {arrow}{abs(diff)}{unit}</span>'

    def row(label, value, dlt="", highlight=False):
        bg = "#fff8e7" if highlight else "#ffffff"
        return (f'<tr style="background:{bg}">'
                f'<td style="padding:6px 12px;color:#666;font-size:13px;">{label}</td>'
                f'<td style="padding:6px 12px;font-size:13px;font-weight:600;">{value}{dlt}</td></tr>')

    def section(title, emoji, content):
        return (f'<div style="margin-bottom:28px;">'
                f'<h2 style="font-size:15px;font-weight:700;color:#1a1a2e;margin:0 0 8px;'
                f'border-bottom:2px solid #e8e8f0;padding-bottom:6px;">{emoji} {title}</h2>'
                f'{content}</div>')

    def tbl(rows):
        return f'<table style="width:100%;border-collapse:collapse;background:#fafafa;border-radius:8px;">{rows}</table>'

    # ── Parse commentary ──
    board_html = insight_html = ""
    in_insight = False
    for line in commentary.strip().split("\n"):
        if line.startswith("💡"):
            in_insight = True
            insight_html += f'<p style="font-size:13px;font-weight:700;color:#92400e;margin:0 0 6px;">{line}</p>'
        elif in_insight:
            if line.strip():
                insight_html += f'<p style="font-size:14px;color:#78350f;line-height:1.7;margin:0;">{line}</p>'
        elif any(line.startswith(e) for e in ("🏋️","🥗","😴","🩺","🧠","🎯")):
            board_html += f'<p style="font-size:13px;font-weight:700;color:#1a1a2e;margin:16px 0 4px;">{line}</p>'
        elif line.strip():
            board_html += f'<p style="font-size:13px;color:#333;line-height:1.6;margin:0 0 8px;">{line}</p>'

    insight_box = (
        f'<div style="background:#fffbeb;border:2px solid #f59e0b;border-radius:10px;'
        f'padding:16px 20px;margin-bottom:24px;">{insight_html}</div>'
    ) if insight_html else ""

    board_section = section("Monthly Board of Advisors", "📋",
        f'<div style="background:#f0f4ff;border-left:4px solid #4a6cf7;padding:16px;border-radius:0 8px 8px 0;">'
        f'{board_html}</div>')

    # ── Monthly scorecard ──
    def sc_pill(label, cur_val, prior_val, unit="%", invert=False, thresholds=(60,80)):
        if cur_val is None:
            col, emoji = "#888", "⚫"
        else:
            lo, hi = thresholds
            if invert:
                col, emoji = ("#27ae60","🟢") if cur_val <= lo else ("#e67e22","🟡") if cur_val <= hi else ("#e74c3c","🔴")
            else:
                col, emoji = ("#e74c3c","🔴") if cur_val < lo else ("#e67e22","🟡") if cur_val < hi else ("#27ae60","🟢")
        dlt = delta(cur_val, prior_val, unit, invert=invert) if prior_val else ""
        return (f'<div style="text-align:center;padding:10px 8px;flex:1;">'
                f'<div style="font-size:20px;">{emoji}</div>'
                f'<div style="font-size:15px;font-weight:700;color:{col};">'
                f'{fmt(cur_val, unit)}</div>'
                f'<div style="font-size:10px;color:#888;">{label}</div>'
                f'<div style="font-size:10px;">{dlt}</div>'
                f'</div>')

    w_c  = cur.get("whoop")
    w_p  = prior.get("whoop")  or {}
    s_c  = cur.get("eightsleep")
    s_p  = prior.get("eightsleep") or {}
    st_c = cur.get("strava")
    st_p = prior.get("strava") or {}
    ch_c = cur.get("chronicling")
    ch_p = prior.get("chronicling") or {}
    wi_c = cur.get("withings")
    wi_p = prior.get("withings") or {}

    scorecard_html = (
        f'<div style="background:#f8f9fc;border-radius:10px;padding:12px 4px;margin-bottom:24px;">'
        f'<p style="text-align:center;font-size:11px;color:#888;margin:0 0 8px;'
        f'text-transform:uppercase;letter-spacing:1px;">{month} — Month at a Glance</p>'
        f'<div style="display:flex;justify-content:space-around;flex-wrap:wrap;">'
        f'{sc_pill("Recovery", w_c["recovery_avg"]  if w_c else None, w_p.get("recovery_avg"))}'
        f'{sc_pill("Sleep",    s_c["score_avg"]     if s_c else None, s_p.get("score_avg"), thresholds=(65,82))}'
        f'{sc_pill("HRV ms",   w_c["hrv_avg"]       if w_c else None, w_p.get("hrv_avg"), unit="ms", thresholds=(45,60))}'
        f'{sc_pill("Habits",   ch_c["score_avg"]    if ch_c else None, ch_p.get("score_avg"), thresholds=(55,75))}'
        f'{sc_pill("RHR bpm",  w_c["rhr_avg"]       if w_c else None, w_p.get("rhr_avg"), unit=" bpm", invert=True, thresholds=(55,65))}'
        f'</div></div>'
    )

    # ── Annual goals progress bar ──
    wt_goal  = goals.get("weight",{})
    pct_done = wt_goal.get("pct_complete", 0)
    year_pct = goals.get("year_pct_elapsed", 0)
    w_bar    = max(0, min(100, pct_done))
    y_bar    = max(0, min(100, year_pct))
    goals_html = (
        f'<div style="background:#f0fdf4;border:1px solid #86efac;border-radius:8px;padding:14px 18px;margin-bottom:24px;">'
        f'<p style="font-size:12px;font-weight:700;color:#166534;margin:0 0 10px;'
        f'text-transform:uppercase;letter-spacing:0.5px;">2026 Annual Goals Progress</p>'
        + (f'<div style="margin-bottom:8px;">'
           f'<div style="display:flex;justify-content:space-between;font-size:12px;color:#15803d;margin-bottom:3px;">'
           f'<span>⚖️ Weight Goal ({wt_goal.get("current_lbs","—")} → {wt_goal.get("goal_lbs","—")} lbs)</span>'
           f'<span>{pct_done}% done</span></div>'
           f'<div style="background:#dcfce7;border-radius:4px;height:8px;">'
           f'<div style="background:#22c55e;width:{w_bar}%;height:8px;border-radius:4px;"></div></div>'
           f'</div>' if wt_goal else "")
        + f'<div>'
          f'<div style="display:flex;justify-content:space-between;font-size:12px;color:#15803d;margin-bottom:3px;">'
          f'<span>📅 Year elapsed</span><span>{year_pct}%</span></div>'
          f'<div style="background:#dcfce7;border-radius:4px;height:8px;">'
          f'<div style="background:#86efac;width:{y_bar}%;height:8px;border-radius:4px;"></div></div>'
          f'</div>'
        + f'</div>'
    )

    # ── Training ──
    tr_rows = ""
    if st_c:
        tr_rows += row("Total Miles", fmt(st_c.get("total_miles")," mi"), delta(st_c.get("total_miles"), st_p.get("total_miles")," mi"))
        tr_rows += row("Total Elevation", f'{st_c.get("total_elevation_feet",0):,} ft', delta(st_c.get("total_elevation_feet"), st_p.get("total_elevation_feet")," ft"))
        tr_rows += row("Activities", str(st_c.get("activity_count",0)), delta(st_c.get("activity_count"), st_p.get("activity_count")))
        z2 = st_c.get("zone2_minutes",0); z2pct = st_c.get("zone2_pct",0)
        z2col = "#27ae60" if z2>=500 else "#e67e22" if z2>=200 else "#e74c3c"
        tr_rows += row(f'Zone 2 ({ZONE2_HR_LOW}–{ZONE2_HR_HIGH} bpm)', f'<span style="color:{z2col};font-weight:700;">{z2} min ({z2pct}% of cardio)</span>')
    tsb = tl.get("tsb",0)
    tcol = "#27ae60" if tsb>=0 else "#e67e22" if tsb>=-15 else "#e74c3c"
    tr_rows += row("CTL — 42-day Fitness", fmt(tl.get("ctl")), highlight=True)
    tr_rows += row("TSB — Current Form", f'<span style="color:{tcol};">{fmt(tl.get("tsb"))} ({"Fresh" if tsb>=5 else "Neutral" if tsb>=-5 else "Fatigued"})</span>')
    if cur.get("hevy"):
        h = cur["hevy"]; hp = prior.get("hevy") or {}
        tr_rows += row("Strength Workouts", str(h.get("workout_count",0)), delta(h.get("workout_count"), hp.get("workout_count")))
    training_section = section("Training — 30 Days","🏃", tbl(tr_rows))

    # ── Recovery ──
    rec_rows = ""
    if w_c:
        rec_rows += row("Avg Recovery", fmt(w_c.get("recovery_avg"),"%"), delta(w_c.get("recovery_avg"), w_p.get("recovery_avg"),"%"), highlight=True)
        rec_rows += row("Avg HRV", fmt(w_c.get("hrv_avg")," ms"), delta(w_c.get("hrv_avg"), w_p.get("hrv_avg")," ms"))
        rec_rows += row("HRV Range", f'{fmt(w_c.get("hrv_min")," ms")} – {fmt(w_c.get("hrv_max")," ms")}')
        rec_rows += row("Avg RHR", fmt(w_c.get("rhr_avg")," bpm"), delta(w_c.get("rhr_avg"), w_p.get("rhr_avg")," bpm", invert=True))
    recovery_section = section("Recovery & HRV","❤️", tbl(rec_rows)) if rec_rows else ""

    # ── Sleep ──
    sl_rows = ""
    if s_c:
        sl_rows += row("Avg Sleep Score", fmt(s_c.get("score_avg"),"%"), delta(s_c.get("score_avg"), s_p.get("score_avg"),"%"), highlight=True)
        sl_rows += row("Avg Duration", fmt(s_c.get("duration_avg_hrs")," hrs"), delta(s_c.get("duration_avg_hrs"), s_p.get("duration_avg_hrs")," hrs"))
        sl_rows += row("Avg Efficiency", fmt(s_c.get("efficiency_avg"),"%"), delta(s_c.get("efficiency_avg"), s_p.get("efficiency_avg"),"%"))
        if s_c.get("rem_pct"):  sl_rows += row("REM %",  fmt(s_c["rem_pct"],"%"), delta(s_c.get("rem_pct"), s_p.get("rem_pct"),"%"))
        if s_c.get("deep_pct"): sl_rows += row("Deep %", fmt(s_c["deep_pct"],"%"), delta(s_c.get("deep_pct"), s_p.get("deep_pct"),"%"))
        sl_rows += row("Nights Tracked", str(s_c.get("nights",0)))
    sleep_section = section("Sleep — 30 Days","😴", tbl(sl_rows)) if sl_rows else ""

    # ── Weight ──
    wt_rows = ""
    if wi_c:
        wt_rows += row("Month-End Weight", fmt(wi_c.get("weight_latest")," lbs"), delta(wi_c.get("weight_latest"), wi_p.get("weight_latest")," lbs", invert=True), highlight=True)
        wt_rows += row("Monthly Avg", fmt(wi_c.get("weight_avg")," lbs"), delta(wi_c.get("weight_avg"), wi_p.get("weight_avg")," lbs", invert=True))
        wt_rows += row("Range", f'{fmt(wi_c.get("weight_min")," lbs")} – {fmt(wi_c.get("weight_max")," lbs")}')
        if wi_c.get("body_fat_avg"): wt_rows += row("Body Fat %", fmt(wi_c["body_fat_avg"],"%"), delta(wi_c.get("body_fat_avg"), wi_p.get("body_fat_avg"),"%", invert=True))
        wg = goals.get("weight",{})
        if wg:
            wt_rows += row("Journey Progress", f'{wg.get("lost_lbs","—")} lbs lost · {wg.get("pct_complete","—")}% to goal', highlight=True)
    weight_section = section("Weight & Body Composition","⚖️", tbl(wt_rows)) if wt_rows else ""

    # ── Nutrition ──
    nu_rows = ""
    m_c = cur.get("macrofactor"); m_p = prior.get("macrofactor") or {}
    if m_c:
        nu_rows += row("Avg Calories", fmt(m_c.get("calories_avg")," kcal"), delta(m_c.get("calories_avg"), m_p.get("calories_avg")," kcal", invert=True), highlight=True)
        nu_rows += row("Calorie Target Hit", f'{m_c.get("calorie_hit_rate","—")}%')
        nu_rows += row("Avg Protein", fmt(m_c.get("protein_avg_g"),"g"), delta(m_c.get("protein_avg_g"), m_p.get("protein_avg_g"),"g"))
        nu_rows += row("Protein Target Hit", f'{m_c.get("protein_hit_rate","—")}%')
        nu_rows += row("Days Logged", str(m_c.get("days_logged",0)))
    else:
        nu_rows = '<tr><td colspan="2" style="padding:12px;color:#999;font-size:13px;font-style:italic;">MacroFactor pending — export CSV from app</td></tr>'
    nutrition_section = section("Nutrition — 30 Days","🥗", tbl(nu_rows))

    # ── Habits ──
    hab_rows = ""
    if ch_c:
        scol = "#27ae60" if (ch_c.get("score_avg") or 0)>=75 else "#e67e22" if (ch_c.get("score_avg") or 0)>=55 else "#e74c3c"
        hab_rows += row("Avg P40 Score", f'<span style="color:{scol};font-weight:700;">{fmt(ch_c.get("score_avg"),"%")}</span>', delta(ch_c.get("score_avg"), ch_p.get("score_avg"),"%"), highlight=True)
        if ch_c.get("group_avgs"):
            for g, v in sorted(ch_c["group_avgs"].items(), key=lambda x: x[1] or 0):
                gcol = "#27ae60" if (v or 0)>=75 else "#e67e22" if (v or 0)>=55 else "#e74c3c"
                cp = ch_p.get("group_avgs",{}).get(g)
                hab_rows += row(f'↳ {g}', f'<span style="color:{gcol};">{fmt(v,"%")}</span>', delta(v, cp, "%") if cp else "")
        if ch_c.get("best_group"):  hab_rows += row("🏆 Best Group",  ch_c["best_group"])
        if ch_c.get("worst_group"): hab_rows += row("⚠️ Weakest Group", ch_c["worst_group"])
    else:
        hab_rows = '<tr><td colspan="2" style="padding:12px;color:#999;font-size:13px;font-style:italic;">Chronicling data not available</td></tr>'
    habits_section = section("Habits & P40 — 30 Days","🎯", tbl(hab_rows))

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f4f4f8;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
  <div style="max-width:660px;margin:32px auto;background:#fff;border-radius:14px;overflow:hidden;box-shadow:0 2px 16px rgba(0,0,0,0.09);">

    <div style="background:linear-gradient(135deg,#0f172a 0%,#1e3a5f 100%);padding:32px;">
      <p style="color:#94a3b8;font-size:11px;margin:0 0 4px;text-transform:uppercase;letter-spacing:2px;">Monthly Coach's Letter</p>
      <h1 style="color:#fff;font-size:26px;margin:0 0 4px;">{month}</h1>
      <p style="color:#64748b;font-size:12px;margin:0;">30-day review · Deltas vs {prior_month}</p>
    </div>

    <div style="padding:28px 32px;">
      {scorecard_html}
      {goals_html}
      {insight_box}
      {board_section}
      {training_section}
      {recovery_section}
      {sleep_section}
      {weight_section}
      {nutrition_section}
      {habits_section}
    </div>

    <div style="background:#f8f8fc;padding:16px 32px;border-top:1px solid #e8e8f0;">
      <p style="color:#999;font-size:11px;margin:0;">Life Platform Monthly · All sources · AWS us-west-2</p>
    </div>
  </div>
</body>
</html>"""


# ══════════════════════════════════════════════════════════════════════════════
# HANDLER
# ══════════════════════════════════════════════════════════════════════════════

def lambda_handler(event, context):
    print("[INFO] Monthly Coach's Letter v1 starting...")
    data, goals = gather_all()
    windows = data["windows"]
    print(f"[INFO] {windows['month_label']} | {windows['cur_start']} → {windows['cur_end']}")

    api_key = get_anthropic_key()
    print("[INFO] Calling Haiku for monthly council commentary...")
    try:
        commentary = call_haiku_monthly(data, goals, api_key)
    except Exception as e:
        print(f"[WARN] Haiku failed: {e}")
        commentary = ("🎯 THE CHAIR — MONTHLY OVERVIEW\nCommentary unavailable this month.\n"
                      "💡 INSIGHT OF THE MONTH\nReview your data sections below.")

    html = build_html(data, goals, commentary, windows)

    month = windows["month_label"]
    ses.send_email(
        FromEmailAddress=SENDER,
        Destination={"ToAddresses": [RECIPIENT]},
        Content={"Simple": {
            "Subject": {"Data": f"Monthly Coach's Letter · {month}", "Charset": "UTF-8"},
            "Body":    {"Html": {"Data": html, "Charset": "UTF-8"}},
        }},
    )
    print(f"[INFO] Sent: Monthly Coach's Letter · {month}")
    return {"statusCode": 200, "body": f"Monthly letter sent: {month}"}
