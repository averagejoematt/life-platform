"""
qa_smoke_lambda.py — Life Platform QA Smoke Test

Runs at 10:30 AM PT daily (30 min after the pipeline completes).
Checks data freshness, score sanity, link integrity, and key output files.
Sends a concise email report — green summary if all pass, red alert if anything fails.

Trigger: EventBridge cron(30 18 ? * * *)  (10:30 AM PT = 18:30 UTC)
Handler: qa_smoke_lambda.lambda_handler
Runtime: python3.12, 256 MB, timeout 120s
Env vars: TABLE_NAME, S3_BUCKET, EMAIL_RECIPIENT, EMAIL_SENDER
"""

import json
import os
import re
import boto3
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import logging

# OBS-1: Structured logger — JSON output for CloudWatch Logs Insights
try:
    from platform_logger import get_logger
    logger = get_logger("qa-smoke")
except ImportError:
    logger = logging.getLogger("qa-smoke")
    logger.setLevel(logging.INFO)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
REGION       = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME   = os.environ.get("TABLE_NAME", "life-platform")
S3_BUCKET    = os.environ["S3_BUCKET"]
RECIPIENT    = os.environ["EMAIL_RECIPIENT"]
SENDER       = os.environ["EMAIL_SENDER"]
USER_PREFIX  = "USER#matthew#SOURCE#"

dynamodb = boto3.resource("dynamodb", region_name=REGION)
table    = dynamodb.Table(TABLE_NAME)
s3       = boto3.client("s3", region_name=REGION)
ses      = boto3.client("sesv2", region_name=REGION)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def pt_now():
    return datetime.now(timezone.utc) - timedelta(hours=8)

def yesterday_str():
    return (pt_now() - timedelta(days=1)).strftime("%Y-%m-%d")


class Check:
    """Single assertion result."""
    def __init__(self, name, category):
        self.name = name
        self.category = category
        self.passed = None   # True=green, False=red, None=yellow
        self.message = ""

    def ok(self, msg=""):
        self.passed = True; self.message = msg; return self

    def fail(self, msg=""):
        self.passed = False; self.message = msg; return self

    def warn(self, msg=""):
        self.passed = None; self.message = msg; return self


# ---------------------------------------------------------------------------
# CHECK 1 — DynamoDB data freshness
# ---------------------------------------------------------------------------

def check_ddb_freshness():
    yesterday = yesterday_str()
    checks = []

    REQUIRED = [
        ("whoop",        "Sleep/Recovery"),
        ("macrofactor",  "Nutrition"),
        ("habitify",     "Habits"),
        ("withings",     "Weight"),
        ("strava",       "Training"),
        ("garmin",       "Steps/Activity"),
        ("apple_health", "Apple Health"),
    ]
    OPTIONAL = [
        ("eightsleep",  "Eight Sleep"),
        ("supplements", "Supplements"),
        ("journal",     "Notion Journal"),
    ]

    for source, label in REQUIRED:
        c = Check(f"DDB:{source}", "Data Freshness")
        try:
            resp = table.get_item(Key={"pk": USER_PREFIX + source, "sk": "DATE#" + yesterday})
            item = resp.get("Item")
            c.ok(f"{label} record found for {yesterday}") if item else c.fail(f"{label} — no record for {yesterday}")
        except Exception as e:
            c.fail(f"{label} — DDB error: {e}")
        checks.append(c)

    for source, label in OPTIONAL:
        c = Check(f"DDB:{source}", "Data Freshness")
        try:
            resp = table.get_item(Key={"pk": USER_PREFIX + source, "sk": "DATE#" + yesterday})
            item = resp.get("Item")
            c.ok(f"{label} found") if item else c.warn(f"{label} — no record (optional)")
        except Exception as e:
            c.warn(f"{label} — error: {e}")
        checks.append(c)

    return checks


# ---------------------------------------------------------------------------
# CHECK 2 — S3 output file freshness
# ---------------------------------------------------------------------------

def check_s3_freshness():
    checks = []

    # (s3_key, label, max_age_hours)
    FILES = [
        ("dashboard/data.json",     "Dashboard JSON",  4),
        ("dashboard/clinical.json", "Clinical JSON",  26),
        ("buddy/data.json",         "Buddy JSON",     26),
    ]

    for key, label, max_hours in FILES:
        c = Check(f"S3:{key}", "Output Files")
        try:
            head = s3.head_object(Bucket=S3_BUCKET, Key=key)
            age_h = (datetime.now(timezone.utc) - head["LastModified"]).total_seconds() / 3600
            if age_h <= max_hours:
                c.ok(f"{label} is current ({age_h:.1f}h ago)")
            else:
                c.fail(f"{label} is STALE — last written {age_h:.1f}h ago (max {max_hours}h)")
        except Exception as e:
            c.fail(f"{label} — error: {e}")
        checks.append(c)

    return checks


# ---------------------------------------------------------------------------
# CHECK 3 — Score sanity (read dashboard/data.json, validate value ranges)
# ---------------------------------------------------------------------------

def check_score_sanity():
    checks = []

    try:
        resp = s3.get_object(Bucket=S3_BUCKET, Key="dashboard/data.json")
        data = json.loads(resp["Body"].read())
    except Exception as e:
        return [Check("dashboard:parse", "Score Sanity").fail(f"Cannot load dashboard/data.json: {e}")]

    expected_date = yesterday_str()
    actual_date   = data.get("date", "")
    c = Check("dashboard:date", "Score Sanity")
    if actual_date == expected_date:
        c.ok(f"Date = {actual_date}")
    elif actual_date:
        c.fail(f"Stale date — expected {expected_date}, got {actual_date}")
    else:
        c.fail("Date field missing from dashboard JSON")
    checks.append(c)

    def _range_check(name, value, lo, hi, unit="", optional=False):
        c = Check(f"value:{name}", "Score Sanity")
        if value is None:
            return c.warn(f"{name} is null (may not have synced)") if optional else c.fail(f"{name} is null — expected data")
        if lo <= float(value) <= hi:
            return c.ok(f"{name} = {value}{unit}")
        return c.fail(f"{name} = {value}{unit} — outside plausible range [{lo},{hi}]")

    readiness = (data.get("readiness") or {}).get("score")
    sleep_s   = (data.get("sleep")     or {}).get("score")
    weight    = (data.get("weight")    or {}).get("current")
    hrv       = (data.get("hrv")       or {}).get("value")
    glucose   = (data.get("glucose")   or {}).get("avg")
    grade_l   = (data.get("day_grade") or {}).get("letter")
    grade_s   = (data.get("day_grade") or {}).get("score")
    hydration = (data.get("day_grade", {}).get("components") or {}).get("hydration")

    checks += [
        _range_check("readiness",  readiness,  0, 100, "%",    optional=True),
        _range_check("sleep",      sleep_s,    0, 100, "",     optional=True),
        _range_check("weight",     weight,     150, 450, " lbs"),
        _range_check("hrv",        hrv,        5, 250, " ms",  optional=True),
        _range_check("glucose",    glucose,    50, 300, " mg/dL", optional=True),
    ]

    c = Check("score:day_grade", "Score Sanity")
    if grade_l and grade_s is not None:
        c.ok(f"Day grade = {grade_l} ({grade_s}/100)")
    else:
        c.fail(f"Day grade missing — grade={grade_l}, score={grade_s}")
    checks.append(c)

    c = Check("score:hydration", "Score Sanity")
    if hydration is None:
        c.warn("Hydration null — Apple Health water likely didn't sync")
    elif hydration < 30:
        c.warn(f"Hydration = {hydration} — low, possible HAE sync gap (may be valid if <1L consumed)")
    else:
        c.ok(f"Hydration = {hydration}")
    checks.append(c)

    cs = data.get("character_sheet") or {}
    c = Check("character_sheet", "Score Sanity")
    lvl, tier = cs.get("level"), cs.get("tier")
    if lvl and tier:
        xp = cs.get("xp", 0)
        c.ok(f"Level {lvl} {tier} ({xp:,} XP)")
    else:
        c.fail(f"Character sheet missing — level={lvl}, tier={tier}")
    checks.append(c)

    return checks


# ---------------------------------------------------------------------------
# CHECK 4 — Blog link integrity
# ---------------------------------------------------------------------------

def check_blog_links():
    checks = []

    try:
        resp = s3.get_object(Bucket=S3_BUCKET, Key="blog/index.html")
        index_html = resp["Body"].read().decode("utf-8")
    except Exception as e:
        return [Check("blog:index", "Blog Links").fail(f"Cannot fetch blog/index.html: {e}")]

    try:
        paginator = s3.get_paginator("list_objects_v2")
        existing = set()
        for page in paginator.paginate(Bucket=S3_BUCKET, Prefix="blog/"):
            for obj in page.get("Contents", []):
                existing.add(obj["Key"])
    except Exception as e:
        return [Check("blog:list", "Blog Links").fail(f"Cannot list blog/ objects: {e}")]

    linked = set(re.findall(r'href="(week-[\w.]+\.html)"', index_html))

    if not linked:
        checks.append(Check("blog:links", "Blog Links").warn("No week-*.html links found in blog index"))
        return checks

    broken, ok_count = [], 0
    for fname in sorted(linked):
        if "blog/" + fname in existing:
            ok_count += 1
        else:
            broken.append(fname)

    c = Check("blog:links", "Blog Links")
    if broken:
        c.fail(f"{len(broken)} broken link(s): {', '.join(broken)} — linked from index but not in S3")
    else:
        c.ok(f"All {ok_count} blog post link(s) resolve")
    checks.append(c)

    return checks


# ---------------------------------------------------------------------------
# CHECK 5 — Lambda secret health
# ---------------------------------------------------------------------------

def check_lambda_secrets():
    """Verify every Lambda's SECRET_NAME env var points to an existing secret."""
    lm  = boto3.client("lambda",         region_name=REGION)
    sm  = boto3.client("secretsmanager", region_name=REGION)

    # Build set of existing (non-deleted) secrets
    existing = set()
    try:
        paginator = sm.get_paginator("list_secrets")
        for page in paginator.paginate():
            for s in page["SecretList"]:
                if s.get("DeletedDate") is None:
                    existing.add(s["Name"])
    except Exception as e:
        return [Check("secrets:inventory", "Lambda Secrets").fail(f"Cannot list secrets: {e}")]

    stale = []
    try:
        paginator = lm.get_paginator("list_functions")
        for page in paginator.paginate():
            for fn in page["Functions"]:
                secret_name = fn.get("Environment", {}).get("Variables", {}).get("SECRET_NAME")
                if secret_name and secret_name not in existing:
                    stale.append(f"{fn['FunctionName']} → {secret_name}")
    except Exception as e:
        return [Check("secrets:sweep", "Lambda Secrets").fail(f"Cannot list functions: {e}")]

    c = Check("secrets:lambda_refs", "Lambda Secrets")
    if stale:
        c.fail(f"{len(stale)} stale SECRET_NAME(s): " + "; ".join(stale))
    else:
        c.ok(f"All Lambda SECRET_NAME references resolve ({len(existing)} secrets in inventory)")
    return [c]


# ---------------------------------------------------------------------------
# CHECK 6 — Avatar PNG assets
# ---------------------------------------------------------------------------

def check_avatar_assets():
    TIERS  = ["foundation", "momentum", "discipline", "mastery", "elite"]
    FRAMES = [1, 2, 3]

    try:
        paginator = s3.get_paginator("list_objects_v2")
        existing = set()
        for page in paginator.paginate(Bucket=S3_BUCKET, Prefix="dashboard/avatar/base/"):
            for obj in page.get("Contents", []):
                existing.add(obj["Key"])
    except Exception as e:
        return [Check("avatar:sprites", "Avatar Assets").fail(f"Cannot list avatar assets: {e}")]

    missing = [
        f"{tier}-frame{frame}.png"
        for tier in TIERS for frame in FRAMES
        if f"dashboard/avatar/base/{tier}-frame{frame}.png" not in existing
    ]

    c = Check("avatar:sprites", "Avatar Assets")
    total = len(TIERS) * len(FRAMES)
    if missing:
        c.fail(f"Missing {len(missing)}/{total} sprites: {', '.join(missing)}")
    else:
        c.ok(f"All {total} avatar sprites present")
    return [c]


# ---------------------------------------------------------------------------
# Report builder
# ---------------------------------------------------------------------------

def build_report_html(all_checks, run_time_str):
    fails  = [c for c in all_checks if c.passed is False]
    warns  = [c for c in all_checks if c.passed is None]
    passes = [c for c in all_checks if c.passed is True]

    overall      = "ALL CLEAR" if not fails else f"{len(fails)} FAILURE(S)"
    banner_emoji = "✅" if not fails else "🔴"
    hdr_bg       = "#064e3b" if not fails else "#450a0a"
    hdr_fg       = "#d1fae5" if not fails else "#fecaca"

    cats = {}
    for c in all_checks:
        cats.setdefault(c.category, []).append(c)

    html = f"""<!DOCTYPE html><html><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#0f0f23;font-family:'SF Pro Display','Segoe UI',sans-serif;">
<div style="max-width:600px;margin:0 auto;background:#1a1a2e;">
  <div style="background:{hdr_bg};padding:20px 24px;border-bottom:3px solid #2d2d5e;">
    <p style="color:#94a3b8;font-size:10px;margin:0 0 4px;font-weight:700;">LIFE PLATFORM · QA SMOKE TEST</p>
    <h1 style="color:{hdr_fg};font-size:24px;font-weight:700;margin:0 0 4px;">{banner_emoji} {overall}</h1>
    <p style="color:#94a3b8;font-size:11px;margin:0;">{run_time_str} &middot; {len(passes)} passed &middot; {len(warns)} warnings &middot; {len(fails)} failed</p>
  </div>"""

    for cat, checks in cats.items():
        cat_fails = sum(1 for c in checks if c.passed is False)
        cat_warns = sum(1 for c in checks if c.passed is None)
        icon = "🔴" if cat_fails else ("🟡" if cat_warns else "🟢")
        html += f"""
  <div style="padding:14px 24px;border-bottom:1px solid #2d2d5e;">
    <p style="color:#64748b;font-size:10px;margin:0 0 8px;font-weight:700;">{icon} {cat.upper()}</p>"""
        for c in checks:
            ci, cc = (("✅", "#22c55e") if c.passed else ("❌", "#f87171")) if c.passed is not None else ("⚠️", "#fbbf24")
            html += f"""    <p style="margin:2px 0;font-size:11px;">
      <span style="color:{cc}">{ci} <strong>{c.name}</strong></span>
      <span style="color:#9ca3af;"> — {c.message}</span></p>"""
        html += "\n  </div>"

    html += """
  <div style="background:#111827;padding:10px 24px;text-align:center;">
    <p style="color:#374151;font-size:9px;margin:0;">Life Platform QA · auto-generated</p>
  </div>
</div></body></html>"""

    return html


# ---------------------------------------------------------------------------
# Lambda handler
# ---------------------------------------------------------------------------

def lambda_handler(event, context):
    run_time     = pt_now()
    run_time_str = run_time.strftime("%A, %b %-d at %-I:%M %p PT")
    print(f"[QA] Smoke test starting — {run_time_str}")

    all_checks  = []
    all_checks += check_ddb_freshness()
    all_checks += check_s3_freshness()
    all_checks += check_score_sanity()
    all_checks += check_blog_links()
    all_checks += check_lambda_secrets()
    all_checks += check_avatar_assets()

    html = build_report_html(all_checks, run_time_str)

    fails  = [c for c in all_checks if c.passed is False]
    warns  = [c for c in all_checks if c.passed is None]

    if not fails and not warns:
        print(f"[QA] All clear — no email sent (green-only suppression)")
        return {"statusCode": 200, "body": json.dumps({"failed": 0, "warned": 0, "emailed": False})}

    subject = (f"⚠️ QA: {len(warns)} warning{'s' if len(warns)>1 else ''} — {run_time.strftime('%b %-d')}" if not fails
               else f"🔴 QA: {len(fails)} failure{'s' if len(fails)>1 else ''} — {run_time.strftime('%b %-d')}")

    ses.send_email(
        FromEmailAddress=SENDER,
        Destination={"ToAddresses": [RECIPIENT]},
        Content={"Simple": {
            "Subject": {"Data": subject, "Charset": "UTF-8"},
            "Body":    {"Html": {"Data": html, "Charset": "UTF-8"}},
        }},
    )

    print(f"[QA] Done — {len(fails)} failures, {len(warns)} warnings, email sent")
    return {"statusCode": 200, "body": json.dumps({"failed": len(fails), "warned": len(warns), "emailed": True})}
