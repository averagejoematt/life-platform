#!/usr/bin/env python3
"""
smoke_test.py — Life Platform CLI Smoke Test

Runs the same checks as qa_smoke_lambda.py but from your terminal.
No email sent — results printed to console with color.

Usage:
  python3 tests/smoke_test.py              # full run
  python3 tests/smoke_test.py --quick      # skip blog + avatar checks
  python3 tests/smoke_test.py --date 2026-03-05   # check a specific date

Requirements: AWS credentials configured (same profile used for deployments)
"""

import argparse
import json
import os
import re
import sys
import boto3
from datetime import datetime, timedelta, timezone
from decimal import Decimal

# ── ANSI colors ──────────────────────────────────────────────────────────────
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
RESET  = "\033[0m"
BOLD   = "\033[1m"
DIM    = "\033[2m"

# ── Config ────────────────────────────────────────────────────────────────────
REGION      = "us-west-2"
TABLE_NAME  = "life-platform"
S3_BUCKET   = "matthew-life-platform"
USER_PREFIX = "USER#matthew#SOURCE#"

dynamodb = boto3.resource("dynamodb", region_name=REGION)
table    = dynamodb.Table(TABLE_NAME)
s3       = boto3.client("s3", region_name=REGION)


# ── Helpers ───────────────────────────────────────────────────────────────────

class Check:
    def __init__(self, name, category):
        self.name = name; self.category = category
        self.passed = None; self.message = ""

    def ok(self, msg=""):
        self.passed = True; self.message = msg; return self

    def fail(self, msg=""):
        self.passed = False; self.message = msg; return self

    def warn(self, msg=""):
        self.passed = None; self.message = msg; return self

    def render(self):
        if self.passed is True:
            return f"  {GREEN}✓{RESET} {BOLD}{self.name}{RESET} {DIM}— {self.message}{RESET}"
        elif self.passed is False:
            return f"  {RED}✗ {BOLD}{self.name}{RESET} {RED}— {self.message}{RESET}"
        else:
            return f"  {YELLOW}⚠ {self.name}{RESET} {DIM}— {self.message}{RESET}"


def pt_now():
    return datetime.now(timezone.utc) - timedelta(hours=8)


# ── Check functions (reuse same logic as lambda) ──────────────────────────────

def check_ddb_freshness(yesterday):
    checks = []
    REQUIRED = [
        ("whoop","Sleep/Recovery"),("macrofactor","Nutrition"),("habitify","Habits"),
        ("withings","Weight"),("strava","Training"),("garmin","Steps"),("apple_health","Apple Health"),
    ]
    OPTIONAL = [("eightsleep","Eight Sleep"),("supplements","Supplements"),("journal","Journal")]

    for source, label in REQUIRED:
        c = Check(f"DDB:{source}", "Data Freshness")
        try:
            resp = table.get_item(Key={"pk": USER_PREFIX + source, "sk": "DATE#" + yesterday})
            c.ok(f"{label} found") if resp.get("Item") else c.fail(f"{label} — no record for {yesterday}")
        except Exception as e:
            c.fail(str(e))
        checks.append(c)

    for source, label in OPTIONAL:
        c = Check(f"DDB:{source}", "Data Freshness")
        try:
            resp = table.get_item(Key={"pk": USER_PREFIX + source, "sk": "DATE#" + yesterday})
            c.ok(f"{label} found") if resp.get("Item") else c.warn(f"{label} not found (optional)")
        except Exception as e:
            c.warn(str(e))
        checks.append(c)

    return checks


def check_s3_freshness():
    checks = []
    FILES = [
        ("dashboard/data.json","Dashboard JSON",4),
        ("dashboard/clinical.json","Clinical JSON",26),
        ("buddy/data.json","Buddy JSON",26),
    ]
    for key, label, max_h in FILES:
        c = Check(f"S3:{key}", "Output Files")
        try:
            head = s3.head_object(Bucket=S3_BUCKET, Key=key)
            age_h = (datetime.now(timezone.utc) - head["LastModified"]).total_seconds() / 3600
            c.ok(f"{label} — {age_h:.1f}h ago") if age_h <= max_h else c.fail(f"{label} STALE — {age_h:.1f}h ago (max {max_h}h)")
        except Exception as e:
            c.fail(str(e))
        checks.append(c)
    return checks


def check_score_sanity(yesterday):
    checks = []
    try:
        resp = s3.get_object(Bucket=S3_BUCKET, Key="dashboard/data.json")
        data = json.loads(resp["Body"].read())
    except Exception as e:
        return [Check("dashboard:parse", "Score Sanity").fail(str(e))]

    # Date
    c = Check("dashboard:date", "Score Sanity")
    actual = data.get("date", "")
    c.ok(f"{actual}") if actual == yesterday else c.fail(f"expected {yesterday}, got '{actual}'")
    checks.append(c)

    def rng(name, val, lo, hi, unit="", opt=False):
        c = Check(f"value:{name}", "Score Sanity")
        if val is None:
            return c.warn(f"null") if opt else c.fail("null")
        if lo <= float(val) <= hi:
            return c.ok(f"{val}{unit}")
        return c.fail(f"{val}{unit} out of range [{lo}–{hi}]")

    r = data.get("readiness") or {}; s = data.get("sleep") or {}
    w = data.get("weight") or {};   h = data.get("hrv") or {}
    g = data.get("glucose") or {};  dg = data.get("day_grade") or {}
    comps = dg.get("components") or {}

    checks += [
        rng("readiness",  r.get("score"),   0,100,"%",  opt=True),
        rng("sleep",      s.get("score"),   0,100,     opt=True),
        rng("weight",     w.get("current"), 150,450," lbs"),
        rng("hrv",        h.get("value"),   5,250," ms",opt=True),
        rng("glucose",    g.get("avg"),     50,300," mg/dL",opt=True),
        rng("hydration",  comps.get("hydration"), 0,100,  opt=True),
    ]

    c = Check("score:day_grade", "Score Sanity")
    if dg.get("letter") and dg.get("score") is not None:
        c.ok(f"{dg['letter']} ({dg['score']}/100)")
    else:
        c.fail(f"letter={dg.get('letter')}, score={dg.get('score')}")
    checks.append(c)

    cs = data.get("character_sheet") or {}
    c = Check("character_sheet", "Score Sanity")
    if cs.get("level") and cs.get("tier"):
        c.ok(f"Level {cs['level']} {cs['tier']} — {cs.get('xp',0):,} XP")
    else:
        c.fail(f"level={cs.get('level')}, tier={cs.get('tier')}")
    checks.append(c)

    # Print current values nicely
    print(f"\n{DIM}  Dashboard snapshot:{RESET}")
    if w.get("current"):
        delta = w.get("weekly_delta")
        delta_str = f"  ({'+' if delta and delta>0 else ''}{delta} lbs vs 7d ago)" if delta else ""
        print(f"  {DIM}  Weight:    {w['current']:.1f} lbs{delta_str}{RESET}")
    if r.get("score"):
        print(f"  {DIM}  Readiness: {r['score']}% ({r.get('color','?')}){RESET}")
    if s.get("score"):
        print(f"  {DIM}  Sleep:     {s['score']} · {s.get('duration_hrs','?')}h{RESET}")
    if h.get("value"):
        print(f"  {DIM}  HRV:       {h['value']:.0f}ms (7d avg: {h.get('avg_7d','?')}){RESET}")
    if comps.get("hydration"):
        print(f"  {DIM}  Hydration: {comps['hydration']}{RESET}")

    return checks


def check_blog_links():
    checks = []
    try:
        resp = s3.get_object(Bucket=S3_BUCKET, Key="blog/index.html")
        html = resp["Body"].read().decode("utf-8")
    except Exception as e:
        return [Check("blog:index", "Blog Links").fail(str(e))]

    try:
        paginator = s3.get_paginator("list_objects_v2")
        existing = set()
        for page in paginator.paginate(Bucket=S3_BUCKET, Prefix="blog/"):
            for obj in page.get("Contents", []):
                existing.add(obj["Key"])
    except Exception as e:
        return [Check("blog:list", "Blog Links").fail(str(e))]

    linked = sorted(set(re.findall(r'href="(week-[\w.]+\.html)"', html)))
    if not linked:
        return [Check("blog:links", "Blog Links").warn("No links found in index")]

    broken = [f for f in linked if "blog/" + f not in existing]
    c = Check("blog:links", "Blog Links")
    if broken:
        c.fail(f"Broken: {', '.join(broken)}")
    else:
        c.ok(f"All {len(linked)} links resolve")
    return [c]


def check_avatar_assets():
    TIERS = ["foundation","momentum","discipline","mastery","elite"]
    try:
        paginator = s3.get_paginator("list_objects_v2")
        existing = set()
        for page in paginator.paginate(Bucket=S3_BUCKET, Prefix="dashboard/avatar/base/"):
            for obj in page.get("Contents", []):
                existing.add(obj["Key"])
    except Exception as e:
        return [Check("avatar:sprites", "Avatar Assets").fail(str(e))]

    missing = [
        f"{t}-frame{f}.png" for t in TIERS for f in [1,2,3]
        if f"dashboard/avatar/base/{t}-frame{f}.png" not in existing
    ]
    c = Check("avatar:sprites", "Avatar Assets")
    total = len(TIERS) * 3
    c.fail(f"Missing {len(missing)}/{total}: {', '.join(missing)}") if missing else c.ok(f"All {total} sprites present")
    return [c]


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Life Platform smoke test")
    parser.add_argument("--quick",  action="store_true", help="Skip blog + avatar checks")
    parser.add_argument("--date",   default=None,        help="Override yesterday date (YYYY-MM-DD)")
    args = parser.parse_args()

    yesterday = args.date or (pt_now() - timedelta(days=1)).strftime("%Y-%m-%d")
    print(f"\n{BOLD}Life Platform Smoke Test{RESET} — checking {yesterday}\n")

    all_checks = []
    sections = [
        ("Data Freshness",  lambda: check_ddb_freshness(yesterday)),
        ("Output Files",    check_s3_freshness),
        ("Score Sanity",    lambda: check_score_sanity(yesterday)),
    ]
    if not args.quick:
        sections += [
            ("Blog Links",     check_blog_links),
            ("Avatar Assets",  check_avatar_assets),
        ]

    for section_name, fn in sections:
        print(f"{BOLD}{section_name}{RESET}")
        checks = fn()
        for c in checks:
            print(c.render())
        all_checks += checks
        print()

    fails  = [c for c in all_checks if c.passed is False]
    warns  = [c for c in all_checks if c.passed is None]
    passes = [c for c in all_checks if c.passed is True]

    if fails:
        print(f"{RED}{BOLD}RESULT: {len(fails)} failure(s), {len(warns)} warning(s){RESET}")
        sys.exit(1)
    elif warns:
        print(f"{YELLOW}{BOLD}RESULT: All passed with {len(warns)} warning(s){RESET}")
    else:
        print(f"{GREEN}{BOLD}RESULT: All {len(passes)} checks passed ✓{RESET}")


if __name__ == "__main__":
    main()
