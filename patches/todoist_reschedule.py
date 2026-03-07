#!/usr/bin/env python3
"""
todoist_reschedule.py — Life Platform task ladder scheduler
============================================================
Fetches ALL current tasks live from Todoist API, then applies:
  1. Completion-based recurrence (every! not every) for all recurring tasks
     EXCEPT hard-date anchored tasks (birthdays, anniversaries, holidays)
  2. Intelligently scattered first-fire dates across 12 months:
     - Sequencing order: Finance/Admin → Health/Body → Growth/Relationships → Home/Car
     - Weekly: day-of-week by task type (Sunday=review, Mon=finance, Tue=health, etc.)
     - Monthly: week-of-month by project (W1=Finance, W2=Health, W3=Growth, W4=Home)
     - Quarterly: spread across 3 months of quarter by project domain
     - Semi-annual: 6 slots across year (Apr/May/Jun then Oct/Nov/Dec) by domain
     - Annual: keyword-to-month + week-within-month by domain. Defer tasks → Aug-Dec.

Usage:
  python3 patches/todoist_reschedule.py            # dry run — prints full plan, no writes
  python3 patches/todoist_reschedule.py --apply    # applies all changes

Token: reads from Secrets Manager (life-platform/api-keys) or env var TODOIST_TOKEN
  export TODOIST_TOKEN=your_token_here
"""

import json
import os
import sys
import time
import urllib.request
import urllib.parse
import urllib.error
from datetime import date, timedelta
from collections import defaultdict

# ──────────────────────────────────────────────────────────────────────────────
DRY_RUN = "--apply" not in sys.argv
TODOIST_BASE = "https://api.todoist.com/api/v1"
RATE_DELAY = 0.3
TODAY = date.today()

# ──────────────────────────────────────────────────────────────────────────────
# TOKEN
# ──────────────────────────────────────────────────────────────────────────────

def get_token():
    token = os.environ.get("TODOIST_TOKEN")
    if token:
        return token
    try:
        import boto3
        client = boto3.client("secretsmanager", region_name="us-west-2")
        resp = client.get_secret_value(SecretId="life-platform/api-keys")
        secret = json.loads(resp["SecretString"])
        return secret.get("todoist_api_token") or secret.get("todoist")
    except Exception as e:
        print(f"ERROR: Could not get token from Secrets Manager: {e}")
        print("Set TODOIST_TOKEN env var instead: export TODOIST_TOKEN=your_token")
        sys.exit(1)

TOKEN = get_token()

# ──────────────────────────────────────────────────────────────────────────────
# TODOIST API
# ──────────────────────────────────────────────────────────────────────────────

def api(method, path, payload=None):
    url = TODOIST_BASE + path
    data = json.dumps(payload).encode() if payload else (b"" if method == "POST" else None)
    req = urllib.request.Request(
        url, data=data,
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
        method=method,
    )
    try:
        with urllib.request.urlopen(req) as r:
            body = r.read()
            return json.loads(body) if body.strip() else {}
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Todoist {method} {path} → {e.code}: {e.read().decode('utf-8', errors='replace')}")

def unwrap(result):
    if isinstance(result, list):
        return result
    if isinstance(result, dict):
        for key in ("items", "results", "projects", "sections"):
            if key in result and isinstance(result[key], list):
                return result[key]
    return []

def fetch_all_tasks():
    all_tasks, cursor = [], None
    while True:
        params = {"limit": 200}
        if cursor:
            params["cursor"] = cursor
        result = api("GET", "/tasks?" + urllib.parse.urlencode(params))
        items = unwrap(result)
        if not items:
            break
        all_tasks.extend(items)
        cursor = result.get("next_cursor") if isinstance(result, dict) else None
        if not cursor:
            break
    return all_tasks

def fetch_projects():
    return {str(p["id"]): p["name"] for p in unwrap(api("GET", "/projects"))}

def fetch_sections():
    return {str(s["id"]): s["name"] for s in unwrap(api("GET", "/sections"))}

def update_task(task_id, due_string=None, due_date=None):
    payload = {}
    if due_string: payload["due_string"] = due_string
    if due_date:   payload["due_date"] = due_date
    api("POST", f"/tasks/{task_id}", payload)

# ──────────────────────────────────────────────────────────────────────────────
# CADENCE & PROJECT DETECTION
# ──────────────────────────────────────────────────────────────────────────────

SECTION_TO_CADENCE = {
    "weekly":        "weekly",
    "bi-weekly":     "biweekly",
    "biweekly":      "biweekly",
    "monthly":       "monthly",
    "quarterly":     "quarterly",
    "semi-annually": "semiannual",
    "semi-annual":   "semiannual",
    "annually":      "annual",
    "annual":        "annual",
    "open items":    "open",
    "open":          "open",
}

RECURRENCE_STRING = {
    "weekly":     "every! week",
    "biweekly":   "every! 2 weeks",
    "monthly":    "every! month",
    "quarterly":  "every! 3 months",
    "semiannual": "every! 6 months",
    "annual":     "every! year",
    "open":       None,
}

def detect_cadence(section_name):
    if not section_name:
        return None
    s = section_name.lower().strip().lstrip("🔁").strip()
    for key, cadence in SECTION_TO_CADENCE.items():
        if key in s:
            return cadence
    return None

# Domain ordering: Finance → Health → Growth → Home
# Used to assign slots within any period
DOMAIN_ORDER = ["finance", "health", "growth", "home", "default"]

def project_domain(project_name):
    n = project_name.lower()
    if "finance" in n or "admin" in n:   return "finance"
    if "health" in n or "body" in n:     return "health"
    if "growth" in n or "relation" in n: return "growth"
    if "home" in n or "car" in n:        return "home"
    return "default"

def domain_index(domain):
    """0-based index in DOMAIN_ORDER, used for offset calculations."""
    try:
        return DOMAIN_ORDER.index(domain)
    except ValueError:
        return 4

# ──────────────────────────────────────────────────────────────────────────────
# HARD DATE DETECTION
# ──────────────────────────────────────────────────────────────────────────────

HARD_DATE_KEYWORDS = [
    "birthday", "anniversar", "christmas", "xmas", "new year",
    "father's day", "mother's day", "valentine", "thanksgiving",
    "easter", "halloween", "hanukkah", "diwali", "eid", "passover",
]

def is_hard_date(content, description=""):
    text = (content + " " + (description or "")).lower()
    return any(kw in text for kw in HARD_DATE_KEYWORDS)

# ──────────────────────────────────────────────────────────────────────────────
# DEFER DETECTION — push to H2 2026
# ──────────────────────────────────────────────────────────────────────────────

DEFER_KEYWORDS = [
    "dexa", "body scan", "bone density",
    "cognitive baseline", "brain test", "cambridge brain",
    "hearing test", "audiolog",
    "annual physical", "full body blood",
    "conference", "speaking opportunit",
    "open source", "biological age",
]

def is_defer(content, description=""):
    text = (content + " " + (description or "")).lower()
    return any(kw in text for kw in DEFER_KEYWORDS)

# ──────────────────────────────────────────────────────────────────────────────
# DATE HELPERS
# ──────────────────────────────────────────────────────────────────────────────

def next_weekday_on_or_after(d, weekday):
    """Next date with given weekday (0=Mon…6=Sun) on or after d."""
    days = (weekday - d.weekday()) % 7
    return d + timedelta(days=days if days else 7)

def first_weekday_of_month(year, month, weekday):
    """First occurrence of weekday in the given month."""
    d = date(year, month, 1)
    days = (weekday - d.weekday()) % 7
    return d + timedelta(days=days)

def nth_weekday_of_month(year, month, weekday, n):
    """nth occurrence (1-based) of weekday in month. Clamps to last if overflow."""
    first = first_weekday_of_month(year, month, weekday)
    result = first + timedelta(weeks=n - 1)
    # Stay in the same month
    while result.month != month:
        result -= timedelta(weeks=1)
    return result

# ──────────────────────────────────────────────────────────────────────────────
# WEEKLY SCATTER
# Goal: gradual onboarding — don't start all weekly tasks simultaneously.
# Spread first-fire across 4 weeks (Mar 8 → Mar 29) so you're adding
# roughly 25% of weekly tasks each week rather than everything at once.
#
# Within each week, assign day-of-week by domain:
#   Sunday (6):   Review / reflection / planning
#   Monday (0):   Finance & Admin
#   Wednesday (2): Health & Body
#   Thursday (3): Growth & Relationships
#   Saturday (5): Home & Car
#   Friday (4):   Everything else
#
# Onboarding order across 4 weeks: Finance → Health → Growth → Home
# so the most foundational domains start first.
# ──────────────────────────────────────────────────────────────────────────────

WEEKLY_DOMAIN_DAY = {
    "finance":  0,  # Monday
    "health":   2,  # Wednesday
    "growth":   3,  # Thursday
    "home":     5,  # Saturday
    "default":  4,  # Friday
}

# Which onboarding week each domain starts in (0-indexed, 0 = Mar 8)
WEEKLY_DOMAIN_ONBOARD_WEEK = {
    "finance":  0,  # Week 1: Mar 8  — financial foundation first
    "health":   0,  # Week 1: Mar 8  — health habits also critical early
    "growth":   1,  # Week 2: Mar 15 — growth after foundation is set
    "home":     2,  # Week 3: Mar 22 — home/car can wait
    "default":  1,
}

REVIEW_KEYWORDS = [
    "review", "reflect", "retrospect", "weekly check", "weekly review",
    "journal", "plan", "planning", "check-in", "check in",
]

def is_review_task(content):
    return any(kw in content.lower() for kw in REVIEW_KEYWORDS)

def weekly_fire_date(content, domain, domain_counter):
    """
    Spread weekly first-fires across 4 onboarding weeks.
    Within a domain, each task after the first adds +1 week so you're not
    adding 10 Finance tasks all on the same Monday.
    Max ~3 new weekly tasks per day during onboarding.
    """
    if is_review_task(content):
        weekday = 6  # Sunday regardless of domain
        base_week = 0
    else:
        weekday = WEEKLY_DOMAIN_DAY.get(domain, 4)
        base_week = WEEKLY_DOMAIN_ONBOARD_WEEK.get(domain, 1)

    # Each task in the same domain starts one week later than the previous
    # but cap at week 4 (Mar 29) — everything should be running by end of March
    week_offset = min(base_week + domain_counter, 3)
    start = next_weekday_on_or_after(TODAY + timedelta(days=1), weekday)
    return start + timedelta(weeks=week_offset)

# ──────────────────────────────────────────────────────────────────────────────
# BI-WEEKLY SCATTER
# Spread first-fires across 6 weeks (Mar 8 → Apr 12).
# Domain sequencing + counter offset, same day-of-week logic as weekly.
# ──────────────────────────────────────────────────────────────────────────────

BIWEEKLY_DOMAIN_ONBOARD_WEEK = {
    "finance":  0,  # Mar 8
    "health":   1,  # Mar 15
    "growth":   2,  # Mar 22
    "home":     3,  # Mar 29
    "default":  1,
}

def biweekly_fire_date(content, domain, domain_counter):
    if is_review_task(content):
        weekday = 6
        base_week = 0
    else:
        weekday = WEEKLY_DOMAIN_DAY.get(domain, 4)
        base_week = BIWEEKLY_DOMAIN_ONBOARD_WEEK.get(domain, 1)

    # Each subsequent task in the domain starts 2 weeks later (one full bi-weekly cycle)
    week_offset = base_week + (domain_counter * 2)
    # Cap at 8 weeks out (early May)
    week_offset = min(week_offset, 8)
    start = next_weekday_on_or_after(TODAY + timedelta(days=1), weekday)
    return start + timedelta(weeks=week_offset)

# ──────────────────────────────────────────────────────────────────────────────
# MONTHLY SCATTER
# Goal: don't start all monthly tasks in March — stagger across Mar/Apr/May.
# Rule: max ~8 monthly tasks start in March (just Finance week 1).
#       Health starts April, Growth May, Home May.
# Within each month: week-of-month by domain, day Mon-Fri by counter.
# ──────────────────────────────────────────────────────────────────────────────

MONTHLY_DOMAIN_WEEK = {
    "finance":  1,  # Week 1 — billing cycles
    "health":   2,  # Week 2
    "growth":   3,  # Week 3
    "home":     4,  # Week 4
    "default":  2,
}

# Stagger start months: Finance March, Health April, Growth May, Home May
MONTHLY_DOMAIN_START_MONTH = {
    "finance":  (2026, 3),
    "health":   (2026, 4),
    "growth":   (2026, 4),
    "home":     (2026, 5),
    "default":  (2026, 4),
}

def monthly_fire_date(content, domain, domain_counter):
    """
    First-fire for monthly tasks, spread Mon-Fri within the target week.
    If a domain has many tasks, overflow into the following month's same week.
    """
    week_num = MONTHLY_DOMAIN_WEEK.get(domain, 2)
    start_year, start_month = MONTHLY_DOMAIN_START_MONTH.get(domain, (2026, 4))

    # Spread Mon-Fri within the week (5 days), then overflow to next month
    day_offset = domain_counter % 5
    month_overflow = domain_counter // 5  # after 5 tasks, spill to next month
    weekday = day_offset

    month = start_month + month_overflow
    year = start_year
    while month > 12:
        month -= 12
        year += 1

    target = nth_weekday_of_month(year, month, weekday, week_num)

    if target <= TODAY:
        month += 1
        if month > 12:
            month = 1
            year += 1
        target = nth_weekday_of_month(year, month, weekday, week_num)

    return target

# ──────────────────────────────────────────────────────────────────────────────
# QUARTERLY SCATTER
# Spread tasks across the 3 months of the quarter, sequenced by domain.
# Q2 2026 (Apr–Jun) is the first quarter for all:
#   Finance & Admin → April  (month 1 of quarter, set the financial stage)
#   Health & Body   → May    (month 2)
#   Growth/Relat.   → June   (month 3)
#   Home & Car      → April  (same as Finance, week 2)
#
# Within each month: use week 1 of that month, spread Mon–Fri by counter.
# ──────────────────────────────────────────────────────────────────────────────

QUARTERLY_DOMAIN_MONTH = {
    "finance":  4,   # April
    "health":   5,   # May
    "growth":   6,   # June
    "home":     4,   # April (week 2 to separate from Finance week 1)
    "default":  5,   # May
}

QUARTERLY_DOMAIN_WEEK = {
    "finance":  1,
    "health":   1,
    "growth":   1,
    "home":     2,   # Week 2 to separate from Finance
    "default":  1,
}

def quarterly_fire_date(domain, domain_counter):
    month = QUARTERLY_DOMAIN_MONTH.get(domain, 5)
    week_num = QUARTERLY_DOMAIN_WEEK.get(domain, 1)
    day_offset = domain_counter % 5
    weekday = day_offset
    return nth_weekday_of_month(2026, month, weekday, week_num)

# ──────────────────────────────────────────────────────────────────────────────
# SEMI-ANNUAL SCATTER
# 6 slots across the year, domain-sequenced in two waves:
#   Wave 1 (H1):  Finance→Apr, Health→May, Growth→Jun
#   Wave 2 (H2):  Finance→Oct, Health→Nov, Growth→Dec
#   Home: Apr (W2) and Oct (W2) — aligned with Finance wave but week 2
#
# Within each month: week 1 for primary domain, week 2 for Home.
# Spread Mon–Fri within week by counter.
# ──────────────────────────────────────────────────────────────────────────────

SEMIANNUAL_DOMAIN_MONTHS = {
    "finance":  [4, 10],   # Apr, Oct
    "health":   [5, 11],   # May, Nov
    "growth":   [6, 12],   # Jun, Dec
    "home":     [4, 10],   # Apr, Oct (week 2)
    "default":  [5, 11],
}

SEMIANNUAL_DOMAIN_WEEK = {
    "finance":  1,
    "health":   1,
    "growth":   1,
    "home":     2,
    "default":  1,
}

def semiannual_fire_date(domain, domain_counter):
    """First task in domain → wave 1 month; second → wave 2 month; third → wave 1 again etc."""
    months = SEMIANNUAL_DOMAIN_MONTHS.get(domain, [5, 11])
    week_num = SEMIANNUAL_DOMAIN_WEEK.get(domain, 1)
    month = months[domain_counter % 2]
    year = 2026
    day_offset = (domain_counter // 2) % 5
    weekday = day_offset
    return nth_weekday_of_month(year, month, weekday, week_num)

# ──────────────────────────────────────────────────────────────────────────────
# ANNUAL SCATTER
# Keyword-to-month assignment (most logical calendar placement).
# Within each month: week by domain (Finance W1, Health W2, Growth W3, Home W4).
# Spread Mon–Fri within week by counter.
# Defer tasks (DEXA, hearing, cognitive baseline, etc.) → Aug–Dec.
# ──────────────────────────────────────────────────────────────────────────────

ANNUAL_KEYWORDS_TO_MONTH = {
    1:  ["tax", "goal setting", "annual review", "isa ", "pension contribution", "new year", "resolution"],
    2:  ["travel book", "summer holiday", "summer trip", "valentine", "summer plan"],
    4:  ["spring clean", "dental check", "allerg", "spring"],
    5:  ["skin check", "dermat", "sunscreen", "sun protect"],
    6:  ["mid year", "half year", "mid-year"],
    7:  ["eye exam", "optom", "vision check", "vision test"],
    8:  ["dexa", "body scan", "cognitive", "brain test", "hearing", "audiolog"],
    9:  ["401k", "pension review", "salary review", "pay review", "performance review"],
    10: ["christmas plan", "xmas gift", "gift list", "christmas present", "halloween"],
    11: ["fsa", "spend-down", "insurance review", "health savings", "open enrollment"],
    12: ["fire calc", "net worth", "financial year", "year end", "annual reflect", "year review"],
}

# Defer tasks that are new/high-effort → push to H2
DEFER_TO_MONTH = {
    "dexa": 8, "body scan": 8, "bone density": 8,
    "cognitive baseline": 8, "brain test": 8, "cambridge brain": 8,
    "hearing test": 7, "audiolog": 7,
    "annual physical": 9, "full body blood": 9,
    "conference": 10, "speaking opportunit": 10,
    "open source": 11, "biological age": 9,
}

ANNUAL_DOMAIN_WEEK = {
    "finance": 1, "health": 2, "growth": 3, "home": 4, "default": 2,
}

def annual_fire_date(content, description, domain, domain_counter):
    text = (content + " " + (description or "")).lower()

    # Check explicit defer keywords first
    for kw, month in DEFER_TO_MONTH.items():
        if kw in text:
            week_num = ANNUAL_DOMAIN_WEEK.get(domain, 2)
            day_offset = domain_counter % 5
            return nth_weekday_of_month(2026, month, day_offset, week_num)

    # Keyword-to-month
    assigned_month = None
    for month, keywords in ANNUAL_KEYWORDS_TO_MONTH.items():
        if any(kw in text for kw in keywords):
            assigned_month = month
            break

    if not assigned_month:
        # No keyword match: spread Apr–Dec by domain_counter (9 months, skip Jan–Mar)
        assigned_month = 4 + (domain_counter % 9)

    week_num = ANNUAL_DOMAIN_WEEK.get(domain, 2)
    day_offset = domain_counter % 5
    return nth_weekday_of_month(2026, assigned_month, day_offset, week_num)

# ──────────────────────────────────────────────────────────────────────────────
# OPEN ITEMS SCATTER
# One-time tasks: spread across Mar 9 – May 31, ~3 per week.
# Domain sequencing: Finance first, then Health, then Growth, then Home.
# ──────────────────────────────────────────────────────────────────────────────

def open_fire_date(domain, global_open_counter):
    """
    Spread open items: 3 per week starting Mar 9.
    Domain order: Finance (first slots) → Health → Growth → Home.
    """
    start = date(2026, 3, 9)
    # Each domain gets a base offset so they interleave across weeks
    domain_base = domain_index(domain) * 1  # 1-day stagger between domains
    week_offset = global_open_counter // 4  # ~4 tasks per week
    day_in_week = global_open_counter % 4   # Mon/Tue/Wed/Thu within week
    d = start + timedelta(weeks=week_offset, days=day_in_week + domain_base)
    return min(d, date(2026, 5, 31))

# ──────────────────────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────────────────────

def main():
    print(f"\n{'='*72}")
    print(f"  Todoist Ladder Scheduler  —  {'DRY RUN' if DRY_RUN else '*** APPLYING CHANGES ***'}")
    print(f"  Today: {TODAY}")
    print(f"{'='*72}\n")

    print("Fetching live data from Todoist API...")
    tasks    = fetch_all_tasks()
    projects = fetch_projects()
    sections = fetch_sections()
    print(f"  {len(tasks)} active tasks | {len(projects)} projects | {len(sections)} sections\n")

    # Group tasks by cadence first, then by domain within cadence.
    # This lets us assign domain-aware counters for scatter logic.
    grouped = defaultdict(lambda: defaultdict(list))  # cadence → domain → [tasks]
    skipped = []

    for task in tasks:
        task_id     = str(task.get("id", ""))
        content     = task.get("content", "")
        description = task.get("description", "") or ""
        project_id  = str(task.get("project_id", ""))
        section_id  = str(task.get("section_id", "")) if task.get("section_id") else ""
        due         = task.get("due") or {}
        current_due = due.get("date", "")
        current_rec = due.get("string", "") or ""

        project_name = projects.get(project_id, "Unknown")
        section_name = sections.get(section_id, "") if section_id else ""
        cadence      = detect_cadence(section_name)
        domain       = project_domain(project_name)

        if not cadence:
            skipped.append({
                "task": content, "project": project_name,
                "section": section_name, "reason": "no matching cadence",
            })
            continue

        # Open items that already have a real future date: leave them alone
        if cadence == "open" and current_due and current_due > TODAY.isoformat():
            skipped.append({
                "task": content, "project": project_name,
                "section": section_name, "reason": f"open item already dated {current_due}",
            })
            continue

        grouped[cadence][domain].append({
            "task_id": task_id, "content": content, "description": description,
            "project_name": project_name, "domain": domain,
            "section_name": section_name, "cadence": cadence,
            "current_due": current_due, "current_rec": current_rec,
        })

    # ── Build plan with proper counters ──
    plan = []
    global_open_counter = 0

    for cadence in ["weekly", "biweekly", "monthly", "quarterly", "semiannual", "annual", "open"]:
        domain_groups = grouped.get(cadence, {})

        # Process domains in sequencing order
        for domain in DOMAIN_ORDER:
            tasks_in_group = domain_groups.get(domain, [])
            domain_counter = 0

            for task in tasks_in_group:
                content     = task["content"]
                description = task["description"]
                hard        = is_hard_date(content, description)

                if hard:
                    # Hard-date tasks: keep date-anchored every (not every!)
                    rec_str   = RECURRENCE_STRING[cadence]
                    if rec_str:
                        rec_str = rec_str.replace("every!", "every")
                    new_due_string = rec_str
                    new_due_date   = None
                    reason = "hard-date — keeping date-anchored recurrence"
                elif cadence == "open":
                    new_due_string = None
                    new_due_date   = open_fire_date(domain, global_open_counter).isoformat()
                    global_open_counter += 1
                    reason = "scatter open item"
                else:
                    new_due_string = RECURRENCE_STRING[cadence]
                    if cadence == "weekly":
                        new_due_date = weekly_fire_date(content, domain, domain_counter).isoformat()
                    elif cadence == "biweekly":
                        new_due_date = biweekly_fire_date(content, domain, domain_counter).isoformat()
                    elif cadence == "monthly":
                        new_due_date = monthly_fire_date(content, domain, domain_counter).isoformat()
                    elif cadence == "quarterly":
                        new_due_date = quarterly_fire_date(domain, domain_counter).isoformat()
                    elif cadence == "semiannual":
                        new_due_date = semiannual_fire_date(domain, domain_counter).isoformat()
                    elif cadence == "annual":
                        new_due_date = annual_fire_date(content, description, domain, domain_counter).isoformat()
                    else:
                        new_due_date = None
                    reason = f"every! + smart scatter ({cadence}/{domain})"

                domain_counter += 1
                plan.append({**task, "new_due_string": new_due_string,
                              "new_due_date": new_due_date, "hard_date": hard, "reason": reason})

    # ── Print plan ──
    print(f"{'─'*72}")
    print(f"  PLAN — {len(plan)} tasks to update")
    print(f"{'─'*72}")

    for cadence in ["weekly", "biweekly", "monthly", "quarterly", "semiannual", "annual", "open"]:
        items = [p for p in plan if p["cadence"] == cadence]
        if not items:
            continue
        print(f"\n  ── {cadence.upper()} ({len(items)} tasks) ──")
        print(f"  {'Task':<50} {'Domain':<10} {'Current':>12} {'→ New date':>12}  {'Recurrence':<22}  Note")
        print(f"  {'─'*50} {'─'*10} {'─'*12} {'─'*12}  {'─'*22}  {'─'*15}")
        for p in items:
            hard_flag = " ⚓ HARD DATE" if p["hard_date"] else ""
            print(f"  {p['content'][:50]:<50} {p['domain']:<10} "
                  f"{p['current_due'] or 'no date':>12} {('→ '+p['new_due_date']) if p['new_due_date'] else '':>13}  "
                  f"{p['new_due_string'] or 'no recur':<22}{hard_flag}")

    # Date distribution summary — shows how many tasks land per month
    print(f"\n{'─'*72}")
    print(f"  DISTRIBUTION SUMMARY (first-fire dates by month)")
    print(f"{'─'*72}")
    month_counts = defaultdict(int)
    for p in plan:
        if p["new_due_date"]:
            ym = p["new_due_date"][:7]
            month_counts[ym] += 1
    for ym in sorted(month_counts):
        bar = "█" * month_counts[ym]
        print(f"  {ym}  {month_counts[ym]:>3}  {bar}")

    if skipped:
        print(f"\n{'─'*72}")
        print(f"  SKIPPED ({len(skipped)})")
        print(f"{'─'*72}")
        for s in skipped[:30]:
            print(f"  {s['task'][:60]:<60}  [{s.get('reason','')}]")
        if len(skipped) > 30:
            print(f"  ... and {len(skipped)-30} more")

    print(f"\n{'─'*72}")
    print(f"  TOTAL: {len(plan)} to update, {len(skipped)} skipped")
    print(f"{'─'*72}\n")

    if DRY_RUN:
        print("  DRY RUN — no changes written.")
        print("  Review the plan above, then run with --apply to commit.\n")
        return

    # ── Apply ──
    print(f"  Applying {len(plan)} updates...\n")
    success, errors = 0, []
    for i, p in enumerate(plan):
        try:
            payload = {}
            if p["new_due_string"]: payload["due_string"] = p["new_due_string"]
            if p["new_due_date"]:   payload["due_date"]   = p["new_due_date"]
            if payload:
                api("POST", f"/tasks/{p['task_id']}", payload)
                success += 1
            if (i + 1) % 20 == 0:
                print(f"    {i+1}/{len(plan)} done...")
            time.sleep(RATE_DELAY)
        except Exception as e:
            errors.append({"task": p["content"], "error": str(e)})
            print(f"    ERROR '{p['content'][:40]}': {e}")

    print(f"\n  ✅ Done. {success} updated, {len(errors)} errors.")
    if errors:
        for e in errors:
            print(f"  ✗ {e['task'][:50]}: {e['error']}")
    print()

if __name__ == "__main__":
    main()
