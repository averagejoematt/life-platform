"""
Monthly Coach's Letter Lambda — v1.2.0 (digest_utils consolidation)
Fires first Sunday of each month at 16:00 UTC (8am PT).
EventBridge cron: cron(0 16 ? * 1#1 *)

Delivers a narrative coach's letter: 30-day current vs 30-day prior month,
6-person council loaded from centralized S3 config, annual goals tracking,
condensed section summaries.

v1.1.0: Board prompt now dynamically built from s3://matthew-life-platform/config/board_of_directors.json
        Falls back to hardcoded _FALLBACK_MONTHLY_PROMPT if S3 read fails.
v1.3.0 (#1658): cadence is enforced by the send log (at most one letter per calendar
        month), not by a weekday guard. The old `weekday() == 0` check meant the
        schedule above — the first SUNDAY — could never satisfy it, so the letter had
        never actually been delivered. The month labels now name the month the data
        covers rather than the month the send happens in.
"""

import json
import logging
import os
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

import boto3
from common.constants import EXPERIMENT_BASELINE_WEIGHT_LBS  # ADR-058
from common.send_guard import guarded_send_email, is_dry_run  # #2222: SES send-suppressor gate

_logger_std = logging.getLogger()
_logger_std.setLevel(logging.INFO)

# ── AWS clients ───────────────────────────────────────────────────────────────

# ── Config (env vars with backwards-compatible defaults) ──
REGION = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
USER_ID = os.environ.get("USER_ID", "matthew")

dynamodb = boto3.resource("dynamodb", region_name=REGION)
table = dynamodb.Table(TABLE_NAME)
ses = boto3.client("sesv2", region_name=REGION)
secrets = boto3.client("secretsmanager", region_name=REGION)
s3_client = boto3.client("s3", region_name=REGION)
S3_BUCKET = os.environ["S3_BUCKET"]

# Board of Directors config loader
try:
    from coach import board_loader

    _HAS_BOARD_LOADER = True
except ImportError:
    _HAS_BOARD_LOADER = False

try:
    from content import insight_writer

    insight_writer.init(table, USER_ID)
    _HAS_INSIGHT_WRITER = True
except ImportError:
    _HAS_INSIGHT_WRITER = False

# AI-3: Output validation
try:
    from ai.ai_output_validator import AIOutputType, validate_ai_output

    _HAS_AI_VALIDATOR = True
except ImportError:
    _HAS_AI_VALIDATOR = False

# OBS-1: Structured logger
try:
    from common.platform_logger import get_logger

    logger = get_logger("monthly-digest")
except ImportError:
    import logging as _log

    logger = _log.getLogger("monthly-digest")
    logger.setLevel(_log.INFO)

# ── Shared digest utilities ────────────────────────────────────────────
from common.digest_utils import (
    avg,
    compute_banister_from_list,
    d2f,
    dedup_activities,
    ex_whoop_from_list as ex_whoop,
    ex_whoop_sleep_from_list as ex_whoop_sleep,
    ex_withings_from_list as ex_withings,
)

# ── The letter RENDERER (#1654) ───────────────────────────────────────────────
# build_html + its section-header classifier live in the sibling
# emails/monthly_digest_render.py — a pure presentation layer with no AWS client,
# no clock and no DynamoDB reach, so nothing the behaviour tests monkeypatch on
# THIS module crosses the seam. Re-exported here so `monthly_digest_lambda.
# build_html` / `._is_section_header` / `.ZONE2_HR_LOW` / `.ZONE2_HR_HIGH` stay the
# public names their callers and tests already use — no contract change.
from emails.monthly_digest_render import (  # noqa: E402,F401
    ZONE2_HR_HIGH,
    ZONE2_HR_LOW,
    _is_section_header,
    build_html,
)

RECIPIENT = os.environ["EMAIL_RECIPIENT"]
SENDER = os.environ["EMAIL_SENDER"]
GOAL_WEIGHT_LBS = 220.0
# Nutrition constants — used as fallback when profile targets are absent
PROTEIN_TARGET_G = 180
CALORIE_TARGET = 1800

# The sources `gather_all` reads for BOTH arms. Every entry must reach the letter:
# `eightsleep` sat here with no extractor and no reader, so two full DynamoDB range
# queries a month were issued and discarded while Whoop remained the sleep SOT
# (#1658). Kept module-level so the behaviour test can derive the fetched set from
# the code instead of restating it — a fetch with no consumer reds the test.
SOURCES = ["whoop", "withings", "strava", "hevy", "macrofactor", "todoist", "chronicling"]

# The stub the letter ships when the board could not speak. It is a NAMED constant
# because the handler must be able to tell it apart from a real verdict by identity
# — the old test, `"unavailable" not in commentary[:50]`, could not (#1658).
COMMENTARY_UNAVAILABLE = (
    "\U0001f3af THE CHAIR — MONTHLY OVERVIEW\nCommentary unavailable this month.\n"
    "\U0001f4a1 INSIGHT OF THE MONTH\nReview your data sections below."
)


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS  (same patterns as weekly digest)
# ══════════════════════════════════════════════════════════════════════════════


# d2f, avg imported from digest_utils (`fmt` is a renderer concern — it moved to
# monthly_digest_render.py with build_html, its only caller here, in #1654).


def fetch_range(source, start, end):
    """Every record for `source` in [start, end], read PER-SOURCE cross-phase (#2150).

    Drives the 30d current-vs-prior-month comparison arms and the 60-day Strava
    Banister window. In a reset month the prior-month arm sat entirely pre-genesis
    and blanked, and the load model computed over a stub window — same defect class
    as #2109's compute-layer readers, fixed the same way: the include_pilot decision
    is derived per source from `phase_taxonomy` rather than fixed here, since this
    function is also (indirectly, via its only caller's source list) never asked for
    an EXPERIMENT_SCOPED source today but must not silently widen if it ever is.

    A read failure RAISES (#1658 / ADR-104). It used to `except Exception: return []`,
    which made a DynamoDB outage, a throttle, or a malformed key indistinguishable
    from a genuinely empty month — and the renderer publishes an empty month as
    confident measurement ("0%" hit rates, a CTL/TSB verdict, "data not available").
    A monthly email is wrong for a whole month before anyone notices, so the right
    failure mode is a loud one: the invocation fails, the alarm fires, and the letter
    is re-sent from real data rather than mailed once with fabricated absence.
    """
    # ADR-058: phase=pilot hidden by default unless the source reads cross-phase.
    from experiment.phase_filter import source_reads_cross_phase, with_phase_filter

    r = table.query(
        **with_phase_filter(
            {
                "KeyConditionExpression": "pk = :pk AND sk BETWEEN :s AND :e",
                "ExpressionAttributeValues": {":pk": f"USER#{USER_ID}#SOURCE#{source}", ":s": f"DATE#{start}", ":e": f"DATE#{end}"},
            },
            include_pilot=source_reads_cross_phase(source),
        )
    )
    return [d2f(i) for i in r.get("Items", [])]


# ══════════════════════════════════════════════════════════════════════════════
# DATE WINDOWS
# ══════════════════════════════════════════════════════════════════════════════


def get_date_windows():
    today = datetime.now(timezone.utc).date()

    # Current month: last 30 days up through yesterday
    cur_end = (today - timedelta(days=1)).isoformat()
    cur_start = (today - timedelta(days=30)).isoformat()

    # Prior month: days 31–60 back
    prior_end = (today - timedelta(days=31)).isoformat()
    prior_start = (today - timedelta(days=60)).isoformat()

    # Labels name the month the ARM ACTUALLY COVERS, not the month the send
    # happens in (#1658). The old labels were `today.strftime(...)` and "the
    # calendar month before today", which on the schedule's own fire slot (first
    # Sunday, e.g. 2026-08-02) headlined 29 days of JULY data as "August 2026"
    # and attributed every delta to "July" when the prior arm was June. The
    # windows themselves stay rolling-30-day; only the naming is corrected.
    month_label = datetime.strptime(cur_start, "%Y-%m-%d").strftime("%B %Y")
    prior_label = datetime.strptime(prior_start, "%Y-%m-%d").strftime("%B %Y")

    return {
        "cur_start": cur_start,
        "cur_end": cur_end,
        "prior_start": prior_start,
        "prior_end": prior_end,
        "month_label": month_label,
        "prior_label": prior_label,
    }


# ══════════════════════════════════════════════════════════════════════════════
# EXTRACTORS  (30-day versions, same logic as weekly)
# ══════════════════════════════════════════════════════════════════════════════

# ex_whoop, ex_whoop_sleep, ex_withings imported from digest_utils
# _normalize_whoop_sleep imported from digest_utils


def ex_strava(recs, profile=None):
    """Extract Strava summary from a list of records.

    Uses profile max_heart_rate for Zone 2 bounds when available;
    falls back to module-level ZONE2_HR_LOW/HIGH constants.
    Activities are deduped before processing.
    """
    if not recs:
        return None
    max_hr = (profile or {}).get("max_heart_rate", None)
    z2_low = max_hr * 0.60 if max_hr else ZONE2_HR_LOW
    z2_high = max_hr * 0.70 if max_hr else ZONE2_HR_HIGH
    acts = []
    zone2_mins = 0
    for r in recs:
        day_acts = dedup_activities(r.get("activities", []))
        for a in day_acts:
            hr = float(a.get("average_heartrate") or 0)
            secs = float(a.get("moving_time_seconds") or 0)
            obj = {
                "name": a.get("enriched_name") or a.get("name", ""),
                "sport": a.get("sport_type", ""),
                "miles": round(float(a.get("distance_miles") or 0), 1),
                "mins": round(secs / 60),
                "hr": round(hr) if hr else None,
            }
            acts.append(obj)
            if hr and z2_low <= hr <= z2_high:
                zone2_mins += obj["mins"]
    total_miles = round(sum(float(r.get("total_distance_miles", 0)) for r in recs), 1)
    total_mins = round(sum(float(r.get("total_moving_time_seconds", 0)) for r in recs) / 60)
    # Both sides of the Zone-2 ratio come from the DEDUPED activity list (#1658).
    # The numerator always did; the denominator used to be the day record's
    # `total_moving_time_seconds`, which double-counts a Garmin→Strava auto-sync
    # duplicate — halving the published zone2_pct on exactly the days that carry one.
    dedup_mins = sum(a["mins"] for a in acts)
    z2_pct = round(zone2_mins / dedup_mins * 100) if dedup_mins else 0
    return {
        "total_miles": total_miles,
        "total_minutes": total_mins,
        "activity_count": len(acts),
        "zone2_minutes": round(zone2_mins),
        "zone2_pct": z2_pct,
        "zone2_hr_range": f"{round(z2_low)}-{round(z2_high)}",
        "total_elevation_feet": round(sum(float(r.get("total_elevation_gain_feet", 0)) for r in recs)),
    }


def ex_hevy(recs):
    """Monthly strength summary: session count AND the volume behind it (#1658).

    The per-workout list (titles + volume) was always built here and then thrown
    away — the letter reported the number of sessions but not a pound of the work,
    which is the figure a lifter actually reads a monthly review for.
    """
    if not recs:
        return None
    wk = []
    for r in recs:
        for w in r.get("workouts", []):
            wk.append({"title": w.get("title", ""), "volume_lbs": round(float(w.get("total_volume_lbs", 0)))})
    return {
        "workout_count": len(wk),
        "total_volume_lbs": sum(w["volume_lbs"] for w in wk),
        "avg_volume_lbs": round(sum(w["volume_lbs"] for w in wk) / len(wk)) if wk else None,
    }


def ex_macrofactor(recs, profile=None):
    """Extract MacroFactor nutrition summary.

    Uses profile calorie_target / protein_target_g when available;
    falls back to module-level CALORIE_TARGET / PROTEIN_TARGET_G constants.
    Field names match the actual DynamoDB schema (total_calories_kcal, total_protein_g).
    """
    if not recs:
        return None
    prot_target = (profile or {}).get("protein_target_g", PROTEIN_TARGET_G)
    cal_target = (profile or {}).get("calorie_target", CALORIE_TARGET)
    cals = [float(r["total_calories_kcal"]) for r in recs if "total_calories_kcal" in r]
    prots = [float(r["total_protein_g"]) for r in recs if "total_protein_g" in r]
    # ADR-104/105 (#1658): each rate is computed over the days it was MEASURED on,
    # not over every row MacroFactor happened to write. The denominator used to be
    # len(recs), so a month with 30 rows of which 10 carried no protein published a
    # rate diluted by 10 days that were never measured — and `days_logged` counted
    # unlogged rows as logged. With nothing logged at all the rates are None
    # (absence), not a confident 0%.
    days_logged = sum(1 for r in recs if "total_calories_kcal" in r or "total_protein_g" in r)
    return {
        "calories_avg": avg(cals),
        "protein_avg_g": avg(prots),
        "calorie_target": cal_target,
        "protein_target": prot_target,
        "days_logged": days_logged,
        "days_in_window": len(recs),
        "protein_hit_rate": round(sum(1 for p in prots if p >= prot_target) / len(prots) * 100) if prots else None,
        "calorie_hit_rate": round(sum(1 for c in cals if c <= cal_target) / len(cals) * 100) if cals else None,
        "protein_hit_rate_n": len(prots),
        "calorie_hit_rate_n": len(cals),
    }


def ex_character_sheet(recs):
    """Extract character sheet metrics from pre-computed DynamoDB records.

    #1658: this used to `recs.sort(...)` IN PLACE — an extractor silently
    reordering its caller's own list — and to read a missing pillar block or a
    missing `character_xp` as a measured zero (ADR-104 behavioural absence).
    """
    if not recs:
        return None
    recs = sorted(recs, key=lambda r: r.get("sk", ""))
    latest = recs[-1]
    char_level = float(latest.get("character_level") or latest.get("level") or 0)
    char_xp = float(latest.get("character_xp") or latest.get("xp") or 0)
    char_tier = str(latest.get("character_tier") or latest.get("tier") or "Foundation")
    char_tier_emoji = str(latest.get("character_tier_emoji") or "🔨")
    pillars = {}
    for p in ("sleep", "movement", "nutrition", "metabolic", "mind", "relationships", "consistency"):
        pd = latest.get(f"pillar_{p}")
        # A pillar the engine never scored has NO block. `or {}` used to coerce that
        # into a dict, which then rendered as a measured "Level 0 — Foundation" row.
        if isinstance(pd, dict) and pd:
            pillars[p] = {"level": float(pd.get("level") or 0), "tier": str(pd.get("tier") or "Foundation")}
    # A day whose record carries no XP reading is SKIPPED, not read as 0 XP: when
    # the window's first record was such a day, xp_delta_30d became the athlete's
    # entire lifetime XP presented as one month's gain.
    xp_vals = [float(r["character_xp"]) for r in recs if r.get("character_xp") is not None]
    xp_delta = round(xp_vals[-1] - xp_vals[0], 0) if len(xp_vals) >= 2 else 0
    return {
        "character_level": char_level,
        "character_xp": char_xp,
        "character_tier": f"{char_tier_emoji} {char_tier}",
        "xp_delta_30d": xp_delta,
        "pillars": pillars,
        "days_tracked": len(recs),
    }


def ex_chronicling(recs):
    """Habit / P40 summary for the window.

    #1658, two ADR-104/105 corrections:
      * `days` is now the n `score_avg` was actually computed over, not every row
        in the window — a mean must be published with ITS OWN n;
      * a group present in the schema but never scored this month (value None)
        used to reach `float(v)` and raise, and — had it not — would have sorted
        as zero and been named the month's "⚠️ Weakest Group". An unmeasured
        group is neither the best nor the worst; it is unmeasured.
    """
    if not recs:
        return None
    scores = []
    group_totals = {}
    for r in recs:
        s = float(r["total_score"]) if r.get("total_score") is not None else None
        if s is not None:
            scores.append(s)
        for g, v in (r.get("group_scores") or {}).items():
            group_totals.setdefault(g, [])
            if v is not None:
                group_totals[g].append(float(v))
    group_avgs = {g: avg(v) for g, v in group_totals.items()}
    # Rank only the groups that carry a measured average.
    ranked = sorted(((g, v) for g, v in group_avgs.items() if v is not None), key=lambda x: x[1])
    return {
        "score_avg": avg(scores),
        "group_avgs": group_avgs,
        "days": len(scores),
        "days_in_window": len(recs),
        "best_group": ranked[-1][0] if ranked else None,
        "worst_group": ranked[0][0] if ranked else None,
    }


# ══════════════════════════════════════════════════════════════════════════════
# BANISTER  — compute_banister_from_list imported from digest_utils
# ══════════════════════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════════════════════
# ANNUAL GOALS TRACKING
# ══════════════════════════════════════════════════════════════════════════════


def compute_annual_goals(cur, windows, profile=None):
    """Compute progress against known 2026 annual goals.

    Accepts the full profile dict (from PROFILE#v1) so we avoid a redundant
    DynamoDB fetch. Falls back to module-level constants if profile is absent.
    """
    today = datetime.now(timezone.utc).date()
    year_start = today.replace(month=1, day=1)
    days_elapsed = (today - year_start).days
    # Derived, not hard-coded 365 (#1658): in a leap year every "Year elapsed"
    # figure was overstated, and 2028-12-31 read as 100% elapsed with a day to run.
    days_in_year = (year_start.replace(year=year_start.year + 1) - year_start).days
    year_pct = round(days_elapsed / days_in_year * 100)

    goals = {"year_pct_elapsed": year_pct}

    # Weight goal
    w = cur.get("withings")
    if w and w.get("weight_latest"):
        p = profile or {}
        journey_start_weight = float(p.get("journey_start_weight_lbs", EXPERIMENT_BASELINE_WEIGHT_LBS))
        goal_weight = float(p.get("goal_weight_lbs", GOAL_WEIGHT_LBS))
        str(p.get("journey_start_date", ""))

        current = w["weight_latest"]
        lost = round(journey_start_weight - current, 1)
        to_go = round(current - goal_weight, 1)
        total = journey_start_weight - goal_weight
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


def _build_monthly_prompt_from_config():
    """Build the monthly council prompt dynamically from S3 board config.

    Returns the prompt template string (with {data_json} and {goals_json} placeholders),
    or None if config unavailable.
    """
    if not _HAS_BOARD_LOADER:
        return None

    config = board_loader.load_board(s3_client, S3_BUCKET)
    if not config:
        return None

    members = board_loader.get_feature_members(config, "monthly_digest")
    if not members:
        logger.warning("[monthly] No members configured for 'monthly_digest' feature")
        return None

    # Build per-member section instructions
    section_blocks = []
    for mid, member, feat_cfg in members:
        header = feat_cfg.get("section_header", f"{member.get('emoji', '')} {member['name'].upper()}")
        focus = feat_cfg.get("prompt_focus", "Provide your monthly analysis.")
        voice = board_loader.build_member_voice(member)
        block = f"{header}\n{focus}"
        if voice:
            block += f"\n{voice}"
        section_blocks.append(block)

    sections_text = "\n\n".join(section_blocks)

    prompt = f"""You are the coordinating intelligence for Matthew's Monthly Health Board of Advisors.

CONTEXT:
Matthew Walker, 36, Seattle. Senior Director at a SaaS company. Goals: lose weight, build muscle,
improve sleep and stress management. He tracks obsessively but struggles to translate data into
consistent behavioural change.
His CURRENT weight goal, journey start weight and progress are in the ANNUAL GOALS CONTEXT block
below, and his current calorie / protein targets are in THIS MONTH'S DATA — read them from there.
Do not assume any target figure that is not in those blocks.

This is a MONTHLY review — not a weekly summary. Your job is to identify the arc and narrative
of the past 30 days, not describe individual weeks. Look for:
- Month-over-month directional change (improving / plateauing / declining)
- Cross-domain patterns that span the full month
- Progress against annual goals (weight trajectory, training consistency, habit adherence)
- What to focus on for the NEXT 30 days

THIS MONTH'S DATA vs PRIOR MONTH:
{{data_json}}

ANNUAL GOALS CONTEXT:
{{goals_json}}

RULES FOR ALL ADVISORS:
- This is a MONTHLY reflection — write about the month's arc, not week-by-week detail.
- Do NOT summarise numbers Matthew can already read in the data tables below.
- DO identify trends, momentum, and cross-domain patterns across the full 30 days.
- Reference specific numbers only when they illuminate a larger pattern.
- If data is missing, mock, or unavailable, say so and note what it prevents you from seeing.
- Each advisor has a distinct domain and must NOT repeat observations from others.
- Be direct. A month of data deserves a month's worth of insight.

Write exactly these sections with these exact headers:

{sections_text}

💡 INSIGHT OF THE MONTH
One sentence. Actionable over the next 30 days. Must cite real numbers. This is the single most important thing Matthew can change to make next month's letter better.

Be honest. A month of data deserves a month's worth of insight."""

    logger.info("[monthly] Built prompt from config with %d board members", len(members))
    return prompt


# Fallback prompt (original hardcoded version, used if S3 config unavailable)
_FALLBACK_MONTHLY_PROMPT = """You are the coordinating intelligence for Matthew's Monthly Health Board of Advisors.

CONTEXT:
Matthew Walker, 36, Seattle. Senior Director at a SaaS company. Goals: lose weight, build muscle,
improve sleep and stress management. He tracks obsessively but struggles to translate data into
consistent behavioural change.
His CURRENT weight goal, journey start weight and progress are in the ANNUAL GOALS CONTEXT block
below — read them from there rather than assuming a figure.

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
One sentence. Actionable over the next 30 days. Must cite real numbers. This is the single most important thing Matthew can change to make next month's letter better.

Be honest. A month of data deserves a month's worth of insight."""


def call_anthropic_with_retry(req, timeout=55, max_attempts=None, backoff_s=None):
    # Delegates to retry_utils for exponential backoff + CloudWatch metrics (P1.8/P1.9)
    from common import retry_utils

    return retry_utils.call_anthropic_raw(req, timeout=timeout)


def _presence_block() -> str:
    """#967: the ONE shared presence / quiet-stretch block (engagement_core,
    written by adaptive_mode → STATE#current) — the same seam daily_brief uses
    (daily_brief_lambda.py Phase 2), so a dark stretch is never narrated as a
    normal month over the silence. Empty when Matthew is present. Fail-soft."""
    try:
        from content.engagement_core import presence_prompt_block

        sig = table.get_item(Key={"pk": f"USER#{USER_ID}#SOURCE#engagement_state", "sk": "STATE#current"}).get("Item") or {}
        block = presence_prompt_block(sig)
        if block:
            logger.info("Presence block injected (class=" + str(sig.get("presence_class")) + ")")
        return block
    except Exception as e:
        logger.warning("presence block skipped (non-fatal): " + str(e))
        return ""


def call_haiku_monthly(data, goals):
    clean_data = d2f(data)
    clean_goals = d2f(goals)

    # Trim large fields for token economy
    for period in ("cur", "prior"):
        st = clean_data.get(period, {}).get("strava")
        if st and "activities" in st:
            del st["activities"]

    # Try config-driven prompt first, fall back to hardcoded
    prompt_template = _build_monthly_prompt_from_config()
    if prompt_template:
        logger.info("Using config-driven monthly board prompt")
    else:
        logger.info("Using fallback hardcoded monthly board prompt")
        prompt_template = _FALLBACK_MONTHLY_PROMPT

    prompt = prompt_template.format(data_json=json.dumps(clean_data, indent=2), goals_json=json.dumps(clean_goals, indent=2))

    # #967: the ONE shared presence block — when Matthew's own logging has gone
    # quiet, the board must not review a normal month over an incomplete window.
    presence = _presence_block()
    if presence:
        prompt += "\n\n" + presence

    # IC-16: Progressive context — quarterly insights window
    if _HAS_INSIGHT_WRITER:
        try:
            prev_ctx = insight_writer.build_insights_context(days=90, max_items=10, label="PREVIOUS INSIGHTS (last 90 days)")
            if prev_ctx:
                prompt = prev_ctx + "\n\n" + prompt
        except Exception as e:
            logger.warning(f"IC-16 failed: {e}")

    # Sonnet is DELIBERATE despite this function's name (#1658). ADR-049 tiers
    # structured work to Haiku and narrative work to Sonnet, and this is the
    # platform's flagship narrative surface: six advisor voices plus a chair's
    # verdict over 30 days of data, read once a month. The misnomer is the
    # function's name (kept for its call sites), not the model.
    payload = json.dumps(
        {"model": os.environ.get("AI_MODEL", "claude-sonnet-4-6"), "max_tokens": 2500, "messages": [{"role": "user", "content": prompt}]}
    ).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={"Content-Type": "application/json", "anthropic-version": "2023-06-01"},
        method="POST",
    )
    resp = call_anthropic_with_retry(req, timeout=60)
    return resp["content"][0]["text"]


# ══════════════════════════════════════════════════════════════════════════════
# DATA ASSEMBLY
# ══════════════════════════════════════════════════════════════════════════════


def gather_all():
    today = datetime.now(timezone.utc).date()
    wins = get_date_windows()

    # ── Profile (needed for profile-driven targets) ──
    try:
        p_item = table.get_item(Key={"pk": f"USER#{USER_ID}", "sk": "PROFILE#v1"}).get("Item", {})
        profile = d2f(p_item)
    except Exception as e:
        logger.warning(f"gather_all: profile fetch failed: {e}")
        profile = {}

    raw_cur = {s: fetch_range(s, wins["cur_start"], wins["cur_end"]) for s in SOURCES}
    raw_prior = {s: fetch_range(s, wins["prior_start"], wins["prior_end"]) for s in SOURCES}

    # One pass per extractor per arm (#1658). This used to build cur/prior with the
    # profile-blind extractors and then immediately overwrite strava + macrofactor
    # with profile-aware recomputations — four wasted passes over the month's records,
    # including a full dedup_activities sweep, every run.
    def _extract(raw):
        return {
            "whoop": ex_whoop(raw["whoop"]),
            "withings": ex_withings(raw["withings"]),
            "strava": ex_strava(raw["strava"], profile),
            "hevy": ex_hevy(raw["hevy"]),
            "macrofactor": ex_macrofactor(raw["macrofactor"], profile),
            "chronicling": ex_chronicling(raw["chronicling"]),
        }

    cur = _extract(raw_cur)
    prior = _extract(raw_prior)

    # Sleep: extracted from Whoop (SOT for duration/staging v2.55.0)
    cur["sleep"] = ex_whoop_sleep(raw_cur["whoop"])
    prior["sleep"] = ex_whoop_sleep(raw_prior["whoop"])

    # Todoist (simple count, no extractor above)
    td_cur = raw_cur.get("todoist", [])
    td_prior = raw_prior.get("todoist", [])
    # #2271: todoist_lambda has only ever written `completed_count` (see
    # ingestion_validator.py's todoist schema) — reading the never-written
    # `tasks_completed` matched nothing and published a permanent measured zero,
    # the identical defect #2245 fixed in weekly_digest.ex_todoist. The OUTPUT
    # key stays `tasks_completed`: it is this module's own contract with the
    # renderer/prompt below, not a DynamoDB attribute name.
    cur["todoist"] = {"tasks_completed": sum(int(r.get("completed_count", 0) or 0) for r in td_cur), "days": len(td_cur)}
    prior["todoist"] = {"tasks_completed": sum(int(r.get("completed_count", 0) or 0) for r in td_prior), "days": len(td_prior)}

    # Character sheet (pre-computed daily records)
    cs_recs_cur = cs_recs_prior = []
    try:
        cs_pk = f"USER#{USER_ID}#SOURCE#character_sheet"

        def _cs_fetch(s, e):
            from experiment.phase_filter import with_phase_filter

            resp = table.query(
                **with_phase_filter(
                    {
                        "KeyConditionExpression": "pk = :pk AND sk BETWEEN :s AND :e",
                        "ExpressionAttributeValues": {":pk": cs_pk, ":s": f"DATE#{s}", ":e": f"DATE#{e}"},
                    }
                )
            )
            return [d2f(i) for i in resp.get("Items", [])]

        cs_recs_cur = _cs_fetch(wins["cur_start"], wins["cur_end"])
        cs_recs_prior = _cs_fetch(wins["prior_start"], wins["prior_end"])
    except Exception as e_cs:
        logger.warning(f"Character sheet fetch failed: {e_cs}")
    cur["character_sheet"] = ex_character_sheet(cs_recs_cur)
    prior["character_sheet"] = ex_character_sheet(cs_recs_prior)

    # Banister (60d Strava) — uses shared compute_banister_from_list (includes dedup)
    strava_60d = fetch_range("strava", (today - timedelta(days=60)).isoformat(), (today - timedelta(days=1)).isoformat())
    training_load = compute_banister_from_list(strava_60d, today)

    # Profile already fetched above; build legacy compat dict for build_html / compute_annual_goals
    profile_compat = {
        "goal_weight_lbs": float(profile.get("goal_weight_lbs", GOAL_WEIGHT_LBS)),
        "journey_start_weight_lbs": float(profile["journey_start_weight_lbs"]) if profile.get("journey_start_weight_lbs") else None,
        "journey_start_date": str(profile.get("journey_start_date", "")),
    }

    annual_goals = compute_annual_goals(cur, wins, profile)

    return {
        "cur": cur,
        "prior": prior,
        "training_load": training_load,
        "profile": profile_compat,
        "windows": wins,
    }, annual_goals


# ══════════════════════════════════════════════════════════════════════════════
# HANDLER
# ══════════════════════════════════════════════════════════════════════════════


EMAIL_LOG_NAME = "monthly_digest"


def _email_log_pk():
    return f"USER#{USER_ID}#SOURCE#email_log#{EMAIL_LOG_NAME}"


def record_email_send(table_, today):
    """Write a completion record so a re-invoke can't double-send (#1658).

    Every other email lambda in this package writes one of these; this one didn't,
    so nothing stopped a retry / manual re-run / EventBridge at-least-once
    redelivery from mailing a second identical letter and filing a second identical
    insight — and the status page could not report the monthly letter's last send
    at all. Non-fatal on failure: a status write must never lose a sent letter.
    """
    import time as _time

    try:
        table_.put_item(
            Item={
                "pk": _email_log_pk(),
                "sk": f"DATE#{today.isoformat()}",
                "sent_at": datetime.now(timezone.utc).isoformat(),
                "status": "success",
                "ttl": int(_time.time()) + 86400 * 400,
            }
        )
    except Exception as e:
        logger.info(f"[status-tracking] Non-fatal write failure: {e}")


def _already_sent_this_month(today) -> bool:
    """True when a letter is already recorded for `today`'s calendar month.

    Fail-OPEN: a read failure must never be the reason a monthly letter goes
    unsent — the letter already spent months not sending (see the handler note).
    """
    month_start = today.replace(day=1).isoformat()
    try:
        r = table.query(
            KeyConditionExpression="pk = :pk AND sk BETWEEN :s AND :e",
            ExpressionAttributeValues={":pk": _email_log_pk(), ":s": f"DATE#{month_start}", ":e": f"DATE#{today.isoformat()}"},
        )
        return bool(r.get("Items"))
    except Exception as e:
        logger.warning(f"[monthly] send-log read failed, proceeding: {e}")
        return False


def lambda_handler(event, context):
    # The cadence guard is IDEMPOTENCY, not the weekday (#1658).
    #
    # This used to `return "skipped — not Monday"` unless date.today().weekday() == 0
    # — while the EventBridge rule is `cron(0 16 ? * 1#1 *)`, whose day-of-week field
    # is 1-7 = SUN-SAT, i.e. the first SUNDAY. Sunday is never Monday, so every
    # scheduled invocation no-opped and the letter was never delivered at all; three
    # ~2ms log streams are the whole record of it. The old guard also read the
    # runtime's LOCAL date to make a weekday decision, in a repo whose crons are
    # fixed-UTC precisely so weekdays can't drift.
    #
    # The schedule already guarantees a monthly cadence; what it does NOT guarantee
    # is exactly-once (retries, manual re-runs, at-least-once redelivery). So the
    # guard that stays is the one that matters: at most one letter per calendar
    # month, from the send log this handler now writes.
    dry_run = is_dry_run(event)
    today = datetime.now(timezone.utc).date()
    if not dry_run and _already_sent_this_month(today):
        logger.info(f"[SKIP] Monthly digest: a letter is already recorded for {today.strftime('%B %Y')}. Exiting.")
        return {"statusCode": 200, "body": "skipped — already sent this month"}

    logger.info("Monthly Coach's Letter v1.1.0 (Board Centralization) starting...")
    data, goals = gather_all()
    windows = data["windows"]
    logger.info(f"{windows['month_label']} | {windows['cur_start']} → {windows['cur_end']}")

    logger.info("Calling Haiku for monthly council commentary...")
    # Whether the board actually spoke is tracked as a FLAG, not sniffed back out of
    # the rendered text (#1658). The old gate was `"unavailable" not in
    # commentary[:50]`, and the failure stub's word "unavailable" starts at index 42
    # — it does not FIT in a 50-character slice, so the sentinel could never fire and
    # the stub was filed into the insight ledger as a genuine monthly coaching
    # insight with confidence="high", actionable=True. A substring test was the wrong
    # instrument anyway: the prompt explicitly asks advisors to say so when data is
    # "missing, mock, or unavailable", so a REAL insight can contain the word too.
    commentary_ok = True
    try:
        commentary = call_haiku_monthly(data, goals)
    except Exception as e:
        logger.warning(f"Haiku failed: {e}")
        commentary = COMMENTARY_UNAVAILABLE
        commentary_ok = False

    # AI-3: Validate output before rendering
    if _HAS_AI_VALIDATOR and commentary and commentary_ok:
        _val = validate_ai_output(commentary, AIOutputType.MONTHLY_DIGEST)
        if _val.blocked:
            logger.info(f"[AI-3] Monthly digest commentary BLOCKED: {_val.block_reason}")
            commentary = _val.safe_fallback or COMMENTARY_UNAVAILABLE
            commentary_ok = False
        elif _val.warnings:
            logger.info(f"[AI-3] Monthly digest warnings: {_val.warnings}")

    html = build_html(data, goals, commentary, windows)

    month = windows["month_label"]
    guarded_send_email(
        ses,
        dry_run,
        FromEmailAddress=SENDER,
        Destination={"ToAddresses": [RECIPIENT]},
        Content={
            "Simple": {
                "Subject": {"Data": f"Monthly Coach's Letter · {month}", "Charset": "UTF-8"},
                "Body": {"Html": {"Data": html, "Charset": "UTF-8"}},
            }
        },
        ConfigurationSetName="life-platform-emails",  # V2 P1.6: open/bounce tracking
        EmailTags=[{"Name": "message_type", "Value": "monthly_digest"}],
    )
    logger.info(f"Sent: Monthly Coach's Letter · {month}")

    # A dry run must leave NO trace that looks like a delivery: writing the send
    # record would make the real scheduled invocation later that month skip as
    # "already sent" — the suppressor would become the thing that suppresses the
    # letter (the exact failure mode this handler just came out of).
    if dry_run:
        logger.info("[DRY_RUN] skipping the send record and the insight ledger write — no mail went out")
        return {"statusCode": 200, "body": f"dry run — monthly letter built, not sent: {month}"}

    record_email_send(table, today)

    # IC-15: Persist monthly insights
    if _HAS_INSIGHT_WRITER and commentary and commentary_ok:
        try:
            insight_writer.write_insight(
                digest_type="monthly_digest",
                insight_type="coaching",
                text=commentary[:800],
                pillars=["sleep", "movement", "nutrition", "mind", "metabolic", "consistency"],
                tags=["monthly", "board", "coaching"],
                confidence="high",
                actionable=True,
                # A SORTABLE date, not the display label (#1658). insight_writer's
                # recency filter is a STRING comparison against a YYYY-MM-DD cutoff,
                # and "August 2026" sorts above every "2026-..-.." cutoff because "A"
                # sorts above the digits — so a monthly insight never aged out of the
                # 14/30/90-day context windows and was replayed into every downstream
                # AI prompt until its TTL expired. This is the last day the letter
                # actually reviewed.
                date=windows["cur_end"],
            )
            logger.info("IC-15: monthly insight persisted")
        except Exception as e:
            logger.warning(f"IC-15 failed: {e}")

    return {"statusCode": 200, "body": f"Monthly letter sent: {month}"}
