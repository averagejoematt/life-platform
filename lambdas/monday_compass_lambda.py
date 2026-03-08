"""
Monday Compass Lambda — v1.0.0
Fires Monday 7:00 AM PT (Monday 15:00 UTC via EventBridge).

A forward-looking weekly planning email that bridges Matthew's health state
with his task and project load — answering "what matters most THIS week and why."

Sections:
  1. State of the Week — Monday readiness, Character Sheet tier, last week grade
  2. On Deck This Week — tasks due this week grouped by project/pillar, P1/P2 flagged
  3. Prioritization Intelligence — AI: health state + pillar gaps → where to focus
  4. The Overdue Pile — backlog summary, commit-or-defer framing
  5. Board Pro Tips — 2-3 Board member recs calibrated to this week's context
  6. This Week's Keystone — one single "if nothing else, do this" recommendation

Data sources:
  Todoist (live API — due-this-week + overdue), Character Sheet (DDB),
  Computed Metrics (DDB), Day Grades (DDB last 7), Profile (DDB), Insights (DDB).

Project→Pillar mapping: s3://matthew-life-platform/config/project_pillar_map.json
Board config: s3://matthew-life-platform/config/board_of_directors.json

AI: claude-sonnet-4-6, temperature 0.4 (planning clarity over creativity), ~$0.05/week.

v1.0.0 — 2026-03-08
"""

import json
import os
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# ── Config ────────────────────────────────────────────────────────────────────
REGION     = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
USER_ID    = os.environ.get("USER_ID", "matthew")
RECIPIENT  = os.environ.get("EMAIL_RECIPIENT", "awsdev@mattsusername.com")
SENDER     = os.environ.get("EMAIL_SENDER", "awsdev@mattsusername.com")
S3_BUCKET  = os.environ.get("S3_BUCKET", "matthew-life-platform")
SECRET_NAME = os.environ.get("SECRET_NAME", "life-platform/api-keys")

USER_PREFIX = f"USER#{USER_ID}#SOURCE#"

dynamodb   = boto3.resource("dynamodb", region_name=REGION)
table      = dynamodb.Table(TABLE_NAME)
ses        = boto3.client("sesv2", region_name=REGION)
s3_client  = boto3.client("s3", region_name=REGION)
secrets    = boto3.client("secretsmanager", region_name=REGION)

_TODOIST_BASE = "https://api.todoist.com/api/v1"

# Optional shared modules (bundled in zip)
try:
    import board_loader
    _HAS_BOARD_LOADER = True
except ImportError:
    _HAS_BOARD_LOADER = False
    logger.warning("board_loader not found — using fallback Board prompt")

try:
    import insight_writer
    insight_writer.init(table, USER_ID)
    _HAS_INSIGHT_WRITER = True
except ImportError:
    _HAS_INSIGHT_WRITER = False

# ── Default project→pillar mapping (overridden by S3 config if present) ──────
_DEFAULT_PROJECT_PILLAR_MAP = {
    "Health & Body":    "movement",
    "Health":           "movement",
    "Nutrition":        "nutrition",
    "Sleep":            "sleep",
    "Mind":             "mind",
    "Meditation":       "mind",
    "Relationships":    "relationships",
    "Social":           "relationships",
    "Finance":          "metabolic",
    "Work":             "consistency",
    "Career":           "consistency",
    "Home":             "consistency",
    "Admin":            "consistency",
    "Personal":         "consistency",
    "Growth":           "mind",
    "Learning":         "mind",
    "Inbox":            "consistency",
}

_PILLAR_EMOJIS = {
    "sleep":        "😴",
    "movement":     "🏃",
    "nutrition":    "🥗",
    "mind":         "🧠",
    "metabolic":    "📈",
    "consistency":  "🔗",
    "relationships":"❤️",
    "general":      "📌",
}

_PILLAR_WEIGHTS = {
    "sleep": 20, "movement": 18, "nutrition": 18,
    "mind": 15, "metabolic": 12, "consistency": 10, "relationships": 7,
}


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

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

def get_secret():
    resp = secrets.get_secret_value(SecretId=SECRET_NAME)
    return json.loads(resp["SecretString"])

def fetch_profile():
    try:
        r = table.get_item(Key={"pk": f"USER#{USER_ID}", "sk": "PROFILE#v1"})
        return d2f(r.get("Item", {}))
    except Exception as e:
        logger.warning(f"Profile fetch failed: {e}")
        return {}

def query_source(source, start_date, end_date):
    pk = f"USER#{USER_ID}#SOURCE#{source}"
    items = []
    kwargs = {
        "KeyConditionExpression": "pk = :pk AND sk BETWEEN :s AND :e",
        "ExpressionAttributeValues": {
            ":pk": pk, ":s": f"DATE#{start_date}", ":e": f"DATE#{end_date}"
        },
    }
    while True:
        resp = table.query(**kwargs)
        items.extend([d2f(i) for i in resp.get("Items", [])])
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    return sorted(items, key=lambda x: x.get("date", ""))

def query_source_latest(source):
    """Get the most recent record for a source."""
    pk = f"USER#{USER_ID}#SOURCE#{source}"
    resp = table.query(
        KeyConditionExpression="pk = :pk",
        ExpressionAttributeValues={":pk": pk},
        ScanIndexForward=False,
        Limit=1,
    )
    items = resp.get("Items", [])
    return d2f(items[0]) if items else {}

def load_project_pillar_map():
    """Load project→pillar mapping from S3. Falls back to default if not found."""
    try:
        resp = s3_client.get_object(
            Bucket=S3_BUCKET, Key="config/project_pillar_map.json"
        )
        return json.loads(resp["Body"].read().decode("utf-8"))
    except Exception as e:
        logger.info(f"S3 project_pillar_map not found — using defaults: {e}")
        return _DEFAULT_PROJECT_PILLAR_MAP


# ══════════════════════════════════════════════════════════════════════════════
# TODOIST API
# ══════════════════════════════════════════════════════════════════════════════

def _todoist_request(method, path, payload=None, token=None):
    url = _TODOIST_BASE + path
    data = json.dumps(payload).encode("utf-8") if payload else None
    req = urllib.request.Request(
        url, data=data,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read()
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Todoist {method} {path} → {e.code}: {body[:200]}")

def _fetch_tasks_with_filter(filter_str, token, limit=200):
    """Fetch tasks matching a Todoist filter string (paginated)."""
    all_tasks = []
    cursor = None
    for _ in range(10):  # max pages
        params = {"filter": filter_str, "limit": limit}
        if cursor:
            params["cursor"] = cursor
        path = "/tasks?" + urllib.parse.urlencode(params)
        try:
            result = _todoist_request("GET", path, token=token)
        except Exception as e:
            logger.warning(f"Todoist filter '{filter_str}' failed: {e}")
            break
        items = result.get("items", result.get("results", result)) if isinstance(result, dict) else result
        if not isinstance(items, list):
            break
        all_tasks.extend(items)
        cursor = result.get("next_cursor") if isinstance(result, dict) else None
        if not cursor or not items:
            break
    return all_tasks

def _fetch_projects(token):
    try:
        result = _todoist_request("GET", "/projects", token=token)
        projects = result.get("items", result.get("results", result)) if isinstance(result, dict) else result
        return {str(p["id"]): p["name"] for p in projects}
    except Exception as e:
        logger.warning(f"Todoist projects fetch failed: {e}")
        return {}

def gather_todoist_data(token):
    """Fetch due-this-week tasks, overdue tasks, and project map."""
    logger.info("Fetching Todoist data...")
    project_map = _fetch_projects(token)

    # Tasks due this week (today through end of Sunday)
    due_this_week = _fetch_tasks_with_filter("due before: next Sunday", token)
    overdue_tasks = _fetch_tasks_with_filter("overdue", token)

    # Remove duplicates between overdue and due_this_week (overdue are a subset of due)
    overdue_ids = {str(t.get("id", "")) for t in overdue_tasks}

    def _normalize(task):
        tid = str(task.get("project_id", ""))
        return {
            "id": str(task.get("id", "")),
            "content": task.get("content", "Untitled"),
            "project_id": tid,
            "project_name": project_map.get(tid, "Inbox"),
            "due": task.get("due"),
            "priority": task.get("priority", 4),
            "labels": task.get("labels", []),
            "description": task.get("description", ""),
        }

    due_normalized = [_normalize(t) for t in due_this_week]
    overdue_normalized = [_normalize(t) for t in overdue_tasks]

    # Due-this-week (excluding overdue — those get their own section)
    due_fresh = [t for t in due_normalized if t["id"] not in overdue_ids]

    return {
        "due_this_week": due_fresh,
        "overdue": overdue_normalized,
        "total_due_this_week": len(due_fresh),
        "total_overdue": len(overdue_normalized),
        "project_map": project_map,
    }


# ══════════════════════════════════════════════════════════════════════════════
# HEALTH DATA GATHERING
# ══════════════════════════════════════════════════════════════════════════════

def gather_health_data():
    """Pull Monday readiness, last week grades, and Character Sheet from DDB."""
    today = datetime.now(timezone.utc).date()
    last_7_start = (today - timedelta(days=7)).isoformat()
    today_str = today.isoformat()

    # Last 7 day grades
    grade_items = query_source("day_grade", last_7_start, today_str)

    # Computed metrics (most recent)
    metrics = query_source_latest("computed_metrics")

    # Character sheet (most recent)
    char_items = query_source("character_sheet", last_7_start, today_str)
    char_today = char_items[-1] if char_items else {}

    # Whoop recovery (today)
    whoop_items = query_source("whoop", today_str, today_str)
    whoop_today = whoop_items[0] if whoop_items else {}

    # Habit scores last 7 days
    habit_items = query_source("habit_scores", last_7_start, today_str)

    return {
        "day_grades": grade_items,
        "computed_metrics": metrics,
        "character_sheet": char_today,
        "whoop_today": whoop_today,
        "habit_scores_7d": habit_items,
        "today_str": today_str,
    }


# ══════════════════════════════════════════════════════════════════════════════
# DATA PROCESSING
# ══════════════════════════════════════════════════════════════════════════════

def _group_tasks_by_pillar(tasks, pillar_map):
    """Group tasks by pillar using project→pillar mapping."""
    groups = {}
    for task in tasks:
        proj = task.get("project_name", "Inbox")
        pillar = None
        # Try exact match first, then partial
        for proj_key, p in pillar_map.items():\
            if proj_key.startswith("_"):
                continue
            if proj_key.lower() == proj.lower():
                pillar = p
                break
        if not pillar:
            for proj_key, p in pillar_map.items():
                if proj_key.startswith("_"):
                    continue
                if proj_key.lower() in proj.lower() or proj.lower() in proj_key.lower():
                    pillar = p
                    break
        if not pillar:
            pillar = "general"

        if pillar not in groups:
            groups[pillar] = []
        groups[pillar].append(task)
    return groups

def _priority_label(p):
    return {1: "🔴 P1", 2: "🟠 P2", 3: "🟡 P3", 4: ""}.get(p, "")

def _due_label(due):
    if not due:
        return ""
    date_str = due.get("date", "") if isinstance(due, dict) else str(due)
    try:
        due_date = datetime.strptime(date_str[:10], "%Y-%m-%d").date()
        today = datetime.now(timezone.utc).date()
        delta = (due_date - today).days
        if delta == 0: return "· due today"
        if delta == 1: return "· due tomorrow"
        if delta < 0:  return f"· {abs(delta)}d overdue"
        return f"· {due_date.strftime('%a')}"
    except Exception:
        return ""

def build_week_state_summary(health_data, profile):
    """Build human-readable week state for prompt and email."""
    metrics = health_data.get("computed_metrics", {})
    whoop  = health_data.get("whoop_today", {})
    char   = health_data.get("character_sheet", {})
    grades = health_data.get("day_grades", [])

    recovery   = safe_float(whoop, "recovery_score")
    hrv        = safe_float(metrics, "hrv_yesterday") or safe_float(whoop, "hrv_rmssd_ms")
    readiness  = safe_float(metrics, "readiness_score")
    tsb        = safe_float(metrics, "tsb")
    char_level = char.get("character_level", 1)
    char_tier  = char.get("character_tier", "Foundation")

    # Last week grade avg
    grade_scores = [float(g.get("day_grade", 0)) for g in grades if g.get("day_grade") is not None]
    last_week_avg = round(sum(grade_scores) / len(grade_scores), 1) if grade_scores else None

    # Pillar scores from character sheet
    pillar_scores = {}
    for p in ["sleep", "movement", "nutrition", "mind", "metabolic", "consistency", "relationships"]:
        pd = char.get(f"pillar_{p}", {})
        s = pd.get("raw_score")
        if s is not None:
            pillar_scores[p] = round(float(s), 1)

    weakest_pillar = None
    if pillar_scores:
        weakest_pillar = min(pillar_scores, key=lambda x: pillar_scores[x])

    start_w  = profile.get("journey_start_weight_lbs", 302)
    goal_w   = profile.get("goal_weight_lbs", 185)
    week_num = _compute_week_num(profile)

    return {
        "recovery": recovery,
        "hrv": hrv,
        "readiness": readiness,
        "tsb": tsb,
        "char_level": char_level,
        "char_tier": char_tier,
        "last_week_avg_grade": last_week_avg,
        "pillar_scores": pillar_scores,
        "weakest_pillar": weakest_pillar,
        "start_weight": start_w,
        "goal_weight": goal_w,
        "week_num": week_num,
    }

def _compute_week_num(profile):
    try:
        start = datetime.strptime(profile.get("journey_start_date", "2026-02-22"), "%Y-%m-%d").date()
        today = datetime.now(timezone.utc).date()
        return max(1, ((today - start).days + 6) // 7)
    except Exception:
        return 1


# ══════════════════════════════════════════════════════════════════════════════
# BOARD PRO TIPS (config-driven)
# ══════════════════════════════════════════════════════════════════════════════

def _build_board_context_for_compass(week_state, todoist_data):
    """Build Board of Directors context for weekly planning."""
    if not _HAS_BOARD_LOADER:
        return _fallback_board_context(week_state)

    config = board_loader.load_board(s3_client, S3_BUCKET)
    if not config:
        return _fallback_board_context(week_state)

    weakest = week_state.get("weakest_pillar", "consistency")
    overdue_count = todoist_data.get("total_overdue", 0)
    recovery = week_state.get("recovery")

    priority_members = ["rodriguez"]

    pillar_to_member = {
        "sleep": "park", "movement": "chen", "nutrition": "webb",
        "mind": "conti", "metabolic": "attia", "relationships": "murthy",
        "consistency": "the_chair",
    }
    pillar_member = pillar_to_member.get(weakest, "the_chair")
    if pillar_member not in priority_members:
        priority_members.append(pillar_member)

    if recovery is not None and recovery < 50:
        extra = "park" if weakest != "sleep" else "chen"
        if extra not in priority_members:
            priority_members.append(extra)
    elif overdue_count > 20:
        if "the_chair" not in priority_members:
            priority_members.append("the_chair")

    priority_members = priority_members[:3]

    members_data = config.get("members", {})
    lines = []
    for mid in priority_members:
        member = members_data.get(mid)
        if not member or not member.get("active", True):
            continue
        name = member.get("name", mid)
        title = member.get("title", "")
        voice = member.get("voice", {})
        catchphrase = voice.get("catchphrase", "")
        domains = ", ".join(member.get("domains", [])[:3])
        lines.append(f"{name} ({title}) — domains: {domains}")
        if catchphrase:
            lines.append(f'  Principle: "{catchphrase}"')

    if not lines:
        return _fallback_board_context(week_state)

    return "\n".join(lines)

def _fallback_board_context(week_state):
    weakest = week_state.get("weakest_pillar", "consistency")
    return (
        "Dr. Elena Rodriguez (Behavioral Scientist) — domains: decision fatigue, willpower, behavioral change\n"
        "  Principle: 'You cannot out-willpower a bad environment. Design the week before it designs you.'\n\n"
        f"Relevant expert for {weakest} pillar improvement\n"
        "The Chair (Platform Intelligence) — domains: cross-pillar optimization, compounding leverage\n"
        "  Principle: 'The constraint determines the ceiling. Fix the bottleneck, not the highlights.'"
    )


# ══════════════════════════════════════════════════════════════════════════════
# AI CALL
# ══════════════════════════════════════════════════════════════════════════════

def call_anthropic(system_prompt, user_message, api_key, max_tokens=3000):
    payload = json.dumps({
        "model": "claude-sonnet-4-6",
        "max_tokens": max_tokens,
        "temperature": 0.4,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_message}],
    }).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages", data=payload,
        headers={"Content-Type": "application/json", "x-api-key": api_key,
                 "anthropic-version": "2023-06-01"}, method="POST",
    )
    for attempt in range(1, 3):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.loads(r.read())["content"][0]["text"].strip()
        except urllib.error.HTTPError as e:
            logger.warning(f"Anthropic HTTP {e.code} attempt {attempt}")
            if attempt < 2 and e.code in (429, 529, 500, 502, 503, 504):
                time.sleep(5)
            else:
                raise
        except urllib.error.URLError as e:
            logger.warning(f"Anthropic network error attempt {attempt}: {e}")
            if attempt < 2: time.sleep(5)
            else: raise


SYSTEM_PROMPT = """You are the author of "The Monday Compass" — Matthew's weekly planning intelligence email. Your job is to connect his health state to his task load and help him start the week with clarity and intention rather than anxiety and noise.

You have three jobs:
1. Tell Matthew what his body and Character Sheet say about the week ahead
2. Help him see what's actually on his plate — organized, not overwhelming
3. Give him one clear answer to "what should I focus on this week and why"

## MATTHEW'S CONTEXT
{journey_context}
Life platform weights: Sleep 20%, Movement 18%, Nutrition 18%, Mind 15%, Metabolic Health 12%, Consistency 10%, Relationships 7%.

## YOUR VOICE
Clear, direct, intelligent — like a trusted advisor who reviewed his data before this meeting. Not cheerleader-y. Not clinical. A blend of strategic thinking and genuine care. You see the patterns he's in the middle of. You name them without judgment.

## WRITE EXACTLY THESE 6 SECTIONS (in HTML):

### Section 1: "🌅 State of the Week"
3-4 sentences covering: Monday readiness (recovery, HRV, TSB if notable), Character Sheet tier + level, how last week graded overall. Set the strategic tone for the week. If recovery is low, acknowledge it and factor it into the prioritization. If it's strong, say so — the week opens with a tailwind.

### Section 2: "📋 On Deck This Week"
Display tasks due this week, grouped by pillar. Use the pillar groupings provided. For each pillar group:
- Pillar emoji + name as header
- List tasks (max 6 per pillar). Mark P1/P2 clearly. Include due day if available.
- Brief 1-line note per pillar on whether this load is reasonable given health state.
If a pillar has no tasks this week, note it — absence of planned work in the Relationships or Mind pillar IS information.

### Section 3: "🎯 Prioritization Intelligence"
This is the most important section. 4-6 sentences of AI reasoning:
- Given Matthew's health state (recovery, HRV, Character Sheet pillar gaps), which tasks and pillars deserve extra energy this week?
- Cross-pillar reasoning: if Sleep pillar is weak, high-cognitive work should be front-loaded to Mon/Tue when recovery is freshest.
- If there's an overloaded day (P1 + P2 stack) that could create decision fatigue and spill over into habit failures, name it.
- Ground every recommendation in the specific data provided. No generic advice.

### Section 4: "🗂️ The Overdue Pile"
State the overdue count. Group by project/pillar. For each overdue cluster:
- Name it, count it.
- One-line recommendation: commit this week | defer to next | delete it.
Framing: this is cognitive debt. Every unreviewed overdue task is background anxiety. The goal is to clear or consciously defer it, not feel guilty. Rodriguez would say: "An unreviewed backlog is a willpower tax."

### Section 5: "💡 Board Pro Tips"
2-3 Board member recommendations, each in a small card:
- Name + title (from the board context provided)
- Their recommendation for THIS week — grounded in Matthew's actual data
- Tone matches their voice/principle
Keep each card to 2-3 sentences. These should feel like real expert opinions, not generic motivational quotes.

### Section 6: "🔑 This Week's Keystone"
ONE thing. The single highest-leverage action this week given health state + task load + pillar gaps. Could be a task to complete, a habit to protect, or a behaviour to change. 2-3 sentences maximum.
Format it as a clear call-to-action. Bold the actual action. End with why this one thing has compounding value beyond the week.

## FORMAT RULES
- Background: #1a1a2e. Text: #e0e0e0. Accent: #6366f1 (indigo — planning, intelligence)
- Secondary accent: #f59e0b (gold — for keystone and high-priority flags)
- Section headers: white, 16px, font-weight 700
- Task lists: clean, readable, monospace-feel for the task names. P1 tasks: #f87171 (red), P2: #fb923c (orange)
- On Deck pillar groups: card per pillar — background #16213e, border-left 3px in pillar color, border-radius 8px, padding 12px
- Board Pro Tips cards: background #16213e, border-radius 8px, subtle top border in member color
- Keystone section: distinct — background #1e1b4b, gold left border 4px, padding 16px
- No <html>/<head>/<body> tags — just content divs. max-width 600px, centered.
- Footer: "The Monday Compass · Life Platform · Weekly Planning Edition"

## CRITICAL RULES
- Every recommendation must trace directly to data provided. No generic advice.
- If a pillar has strong scores, say so briefly and move on — don't over-coach the strong stuff.
- Cross-pillar reasoning is your superpower. Use it. Name trade-offs explicitly.
- The overdue section is about reducing anxiety, not adding to it. Tone is matter-of-fact, not judgmental.
- Task names should appear exactly as provided — don't rephrase or paraphrase them.
- This email is read Monday morning before the week starts. It should feel like a strategic briefing, not a review."""


def build_user_message(week_state, todoist_data, health_data, profile,
                       pillar_map, board_context):
    """Assemble the full data payload for the AI."""
    today = datetime.now(timezone.utc).date()

    week_num = week_state.get("week_num", 1)
    start_w = week_state.get("start_weight", 302)
    goal_w  = week_state.get("goal_weight", 185)
    char_level = week_state.get("char_level", 1)
    char_tier  = week_state.get("char_tier", "Foundation")
    journey_context = (
        f"Week {week_num} of transformation journey ({start_w}→{goal_w} lbs). "
        f"Character Level {char_level} ({char_tier}). "
        f"Today is Monday {today.strftime('%B %-d, %Y')}."
    )

    pillar_block = []
    for p, score in sorted(week_state.get("pillar_scores", {}).items(),
                            key=lambda x: x[1]):
        emoji = _PILLAR_EMOJIS.get(p, "📌")
        pillar_block.append(f"  {emoji} {p.capitalize()}: {score:.0f}/100")

    weakest = week_state.get("weakest_pillar", "consistency")

    due_groups = _group_tasks_by_pillar(todoist_data.get("due_this_week", []), pillar_map)
    overdue_groups = _group_tasks_by_pillar(todoist_data.get("overdue", []), pillar_map)

    def _format_task_list(tasks, max_count=8):
        lines = []
        for t in tasks[:max_count]:
            p_label = _priority_label(t.get("priority", 4))
            due_label = _due_label(t.get("due"))
            content = t.get("content", "Untitled")
            proj = t.get("project_name", "")
            parts = [content]
            if p_label: parts.append(p_label)
            if due_label: parts.append(due_label)
            if proj: parts.append(f"[{proj}]")
            lines.append("    - " + " ".join(parts))
        if len(tasks) > max_count:
            lines.append(f"    ... +{len(tasks) - max_count} more")
        return "\n".join(lines)

    task_block = []
    for pillar in ["sleep", "movement", "nutrition", "mind", "metabolic",
                   "consistency", "relationships", "general"]:
        tasks = due_groups.get(pillar, [])
        if not tasks:
            continue
        emoji = _PILLAR_EMOJIS.get(pillar, "📌")
        task_block.append(f"\n{emoji} {pillar.upper()} ({len(tasks)} tasks):")
        task_block.append(_format_task_list(tasks))

    overdue_block = []
    for pillar, tasks in sorted(overdue_groups.items()):
        emoji = _PILLAR_EMOJIS.get(pillar, "📌")
        overdue_block.append(f"\n{emoji} {pillar.upper()} ({len(tasks)} overdue):")
        overdue_block.append(_format_task_list(tasks, max_count=5))

    habit_items = health_data.get("habit_scores_7d", [])
    habit_summary = ""
    if habit_items:
        t0_rates = []
        for h in habit_items:
            total = int(h.get("t0_total", 0))
            comp  = int(h.get("t0_completed", 0))
            if total > 0:
                t0_rates.append(round(comp / total * 100))
        if t0_rates:
            avg_t0 = round(sum(t0_rates) / len(t0_rates))
            habit_summary = f"T0 habit compliance last 7 days: avg {avg_t0}% (daily: {', '.join(str(r)+'%' for r in t0_rates[-7:])})"

    grades = health_data.get("day_grades", [])
    grade_line = ""
    if grades:
        scores = [(g.get("date", ""), g.get("day_grade"), g.get("grade_label", ""))
                  for g in grades if g.get("day_grade") is not None]
        grade_line = "Last 7 day grades: " + ", ".join(
            f"{d[5:]} {v:.0f} ({lbl})" for d, v, lbl in scores[-7:]
        )

    insights_ctx = ""
    if _HAS_INSIGHT_WRITER:
        try:
            insights_ctx = insight_writer.build_insights_context(
                days=7, max_items=3,
                label="RECENT PLATFORM INSIGHTS (context for planning)")
        except Exception as e:
            logger.warning(f"IC-16 insights failed: {e}")

    payload = f"""== MATTHEW'S MONDAY MORNING BRIEFING ==

JOURNEY CONTEXT: {journey_context}

READINESS STATE:
  Recovery: {week_state.get('recovery', 'N/A')}%
  HRV: {week_state.get('hrv', 'N/A')} ms
  Readiness: {week_state.get('readiness', 'N/A')}%
  TSB (training stress balance): {week_state.get('tsb', 'N/A')}

CHARACTER SHEET:
  Level {char_level} ({char_tier})
  Pillar scores (weakest to strongest):
{chr(10).join(pillar_block) if pillar_block else '  No pillar data yet'}
  Weakest pillar this week: {weakest.capitalize()}

LAST WEEK:
  {grade_line or 'No grade data'}
  Last week avg grade: {week_state.get('last_week_avg_grade', 'N/A')}
  {habit_summary or 'No habit data'}

TASKS DUE THIS WEEK: {todoist_data.get('total_due_this_week', 0)} tasks
{chr(10).join(task_block) if task_block else 'No tasks due this week'}

OVERDUE: {todoist_data.get('total_overdue', 0)} tasks
{chr(10).join(overdue_block) if overdue_block else 'None — clean slate'}

BOARD OF DIRECTORS CONTEXT:
{board_context}

{insights_ctx}

== END BRIEFING ==

Write the Monday Compass email now. All 6 sections. Ground every recommendation in the data above."""

    return payload, journey_context


# ══════════════════════════════════════════════════════════════════════════════
# EMAIL HTML WRAPPER
# ══════════════════════════════════════════════════════════════════════════════

def build_email_html(ai_content, week_state, today_str):
    try:
        dt = datetime.strptime(today_str, "%Y-%m-%d")
        date_label = dt.strftime("%B %-d, %Y")
    except Exception:
        date_label = today_str

    char_level = week_state.get("char_level", 1)
    char_tier  = week_state.get("char_tier", "Foundation")
    recovery   = week_state.get("recovery")
    week_num   = week_state.get("week_num", 1)

    recovery_str = f"{recovery:.0f}%" if recovery is not None else "—"
    recovery_color = (
        "#4ade80" if recovery and recovery >= 67 else
        "#fb923c" if recovery and recovery >= 34 else
        "#f87171"
    )

    return f'''<div style="max-width:600px;margin:0 auto;background:#1a1a2e;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;padding:20px;color:#e0e0e0;">
  <div style="text-align:center;margin-bottom:28px;">
    <div style="font-size:11px;letter-spacing:2px;color:#6366f1;font-weight:600;margin-bottom:4px;">LIFE PLATFORM · WEEK {week_num}</div>
    <div style="font-size:23px;font-weight:700;color:#ffffff;">🧭 The Monday Compass</div>
    <div style="color:#9ca3af;font-size:13px;margin-top:4px;">{date_label}</div>
    <div style="margin-top:10px;display:inline-flex;gap:16px;font-size:12px;">
      <span style="color:#9ca3af;">Level <span style="color:#f59e0b;font-weight:700;">{char_level}</span> · {char_tier}</span>
      <span style="color:#9ca3af;">Recovery <span style="color:{recovery_color};font-weight:700;">{recovery_str}</span></span>
    </div>
  </div>
  {ai_content}
  <div style="text-align:center;padding:16px 0;border-top:1px solid #2a2d4a;margin-top:28px;">
    <div style="color:#6b7280;font-size:11px;">The Monday Compass · Life Platform · Weekly Planning Edition</div>
  </div>
</div>'''


# ══════════════════════════════════════════════════════════════════════════════
# HANDLER
# ══════════════════════════════════════════════════════════════════════════════

def lambda_handler(event, context):
    logger.info("Monday Compass v1.0.0 starting...")

    secret = get_secret()
    api_key       = secret.get("anthropic_api_key")
    todoist_token = secret.get("todoist_api_token") or secret.get("todoist")

    if not api_key:
        logger.error("No Anthropic API key found")
        return {"statusCode": 500, "body": "Missing Anthropic API key"}

    profile = fetch_profile()
    if not profile:
        logger.error("No profile found in DDB")
        return {"statusCode": 500, "body": "No profile"}

    pillar_map  = load_project_pillar_map()
    health_data = gather_health_data()

    todoist_data = {"due_this_week": [], "overdue": [], "total_due_this_week": 0, "total_overdue": 0}
    if todoist_token:
        try:
            todoist_data = gather_todoist_data(todoist_token)
            logger.info(f"Todoist: {todoist_data['total_due_this_week']} due, {todoist_data['total_overdue']} overdue")
        except Exception as e:
            logger.error(f"Todoist gather failed (non-fatal): {e}")
    else:
        logger.warning("No Todoist token — skipping task data")

    week_state    = build_week_state_summary(health_data, profile)
    board_context = _build_board_context_for_compass(week_state, todoist_data)

    user_message, journey_context = build_user_message(
        week_state, todoist_data, health_data, profile, pillar_map, board_context
    )
    system = SYSTEM_PROMPT.format(journey_context=journey_context)

    try:
        ai_content = call_anthropic(system, user_message, api_key, max_tokens=3500)
    except Exception as e:
        logger.error(f"Anthropic failed: {e}")
        ai_content = (
            '<div style="background:#16213e;border-radius:8px;padding:20px;color:#e0e0e0;">'
            'Monday Compass AI unavailable this week. Check CloudWatch logs.</div>'
        )

    today_str = health_data.get("today_str", datetime.now(timezone.utc).date().isoformat())
    html      = build_email_html(ai_content, week_state, today_str)

    try:
        dt = datetime.strptime(today_str, "%Y-%m-%d")
        subject_date = dt.strftime("%b %-d")
    except Exception:
        subject_date = today_str

    subject = f"🧭 Monday Compass · {subject_date} · Week {week_state.get('week_num', 1)}"

    ses.send_email(
        FromEmailAddress=SENDER,
        Destination={"ToAddresses": [RECIPIENT]},
        Content={"Simple": {
            "Subject": {"Data": subject, "Charset": "UTF-8"},
            "Body":    {"Html": {"Data": html, "Charset": "UTF-8"}},
        }},
    )
    logger.info(f"Sent: {subject}")

    if _HAS_INSIGHT_WRITER and ai_content and "unavailable" not in ai_content[:50]:
        try:
            insight_writer.write_insight(
                digest_type="monday_compass",
                insight_type="coaching",
                text=ai_content[:800],
                pillars=list(week_state.get("pillar_scores", {}).keys()),
                data_sources=["todoist", "character_sheet", "whoop", "computed_metrics"],
                tags=["planning", "weekly", "compass", "cross_pillar"],
                confidence="medium",
                actionable=True,
                date=today_str,
            )
        except Exception as e:
            logger.warning(f"IC-15 failed (non-fatal): {e}")

    return {
        "statusCode": 200,
        "body": json.dumps({
            "email": subject,
            "tasks_due_this_week": todoist_data.get("total_due_this_week", 0),
            "overdue": todoist_data.get("total_overdue", 0),
            "week_num": week_state.get("week_num", 1),
            "char_level": week_state.get("char_level", 1),
        })
    }
