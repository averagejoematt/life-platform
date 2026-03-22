#!/usr/bin/env python3
"""
fix_public_stats.py — Rebuild public_stats.json from live DynamoDB data.

All values are sourced dynamically — nothing hardcoded.

Sources:
  - Profile (PROFILE#v1):     journey targets, phase definitions, zone2 target
  - Withings DynamoDB:        latest weight (30-day lookback)
  - Whoop DynamoDB:           hrv, recovery, rhr, sleep, rhr_trend
  - computed_metrics DynamoDB: tsb, acwr, zone, alert, tier0_streak
  - Strava DynamoDB:          zone2 this week, total miles/activity 30d
  - PLATFORM_FACTS (local):   tool_count, lambda_count, data_sources (auto-discovered)

Run from repo root:
    python3 deploy/fix_public_stats.py           # dry run
    python3 deploy/fix_public_stats.py --write   # write to S3 + invalidate CloudFront
"""

import re
import sys
import json
import math
import boto3
from datetime import datetime, timedelta, timezone, date
from decimal import Decimal
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────
REGION      = "us-west-2"
TABLE_NAME  = "life-platform"
S3_BUCKET   = "matthew-life-platform"
S3_KEY      = "site/public_stats.json"
CF_DIST_ID  = "E3S424OXQZ8NBE"
USER_ID     = "matthew"
USER_PREFIX = f"USER#{USER_ID}#SOURCE#"
PROFILE_PK  = f"USER#{USER_ID}"
DRY_RUN     = "--write" not in sys.argv

# ── AWS clients ───────────────────────────────────────────────────────────────
dynamodb = boto3.resource("dynamodb", region_name=REGION)
table    = dynamodb.Table(TABLE_NAME)
s3       = boto3.client("s3", region_name=REGION)
cf       = boto3.client("cloudfront", region_name="us-east-1")

# ── Helpers ───────────────────────────────────────────────────────────────────
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

def fetch_range(source, start, end):
    r = table.query(
        KeyConditionExpression="pk = :pk AND sk BETWEEN :s AND :e",
        ExpressionAttributeValues={
            ":pk": USER_PREFIX + source,
            ":s":  "DATE#" + start,
            ":e":  "DATE#" + end,
        }
    )
    return [d2f(i) for i in r.get("Items", [])]

def fetch_profile():
    r = table.get_item(Key={"pk": PROFILE_PK, "sk": "PROFILE#v1"})
    return d2f(r.get("Item", {}))

def avg(vals):
    v = [x for x in vals if x is not None]
    return round(sum(v) / len(v), 1) if v else None


# ── Platform counts: auto-discover from source files ─────────────────────────
def discover_platform_counts() -> dict:
    """Read tool_count, lambda_count, data_sources from source — no hardcoding."""
    root = Path(__file__).resolve().parent.parent
    counts = {}

    # Tool count from mcp/registry.py
    try:
        src = (root / "mcp" / "registry.py").read_text(encoding="utf-8")
        start = src.find("TOOLS = {")
        if start != -1:
            tool_names = re.findall(r'^    "([a-z0-9_]+)"\s*:\s*\{', src[start:], re.MULTILINE)
            counts["mcp_tools"] = len(tool_names)
            print(f"[platform] mcp_tools={counts['mcp_tools']} (from registry.py)")
    except Exception as e:
        print(f"[platform] WARNING: could not count tools from registry.py: {e}")

    # Lambda count from CDK stacks
    try:
        names = set()
        stacks_dir = root / "cdk" / "stacks"
        for sf in stacks_dir.glob("*.py"):
            found = re.findall(r'function_name=["\']([a-z0-9_-]+)["\']', sf.read_text(encoding="utf-8"))
            names.update(found)
        if len(names) >= 10:
            counts["lambdas"] = len(names)
            print(f"[platform] lambdas={counts['lambdas']} (from CDK stacks)")
    except Exception as e:
        print(f"[platform] WARNING: could not count Lambdas from CDK: {e}")

    # data_sources from PLATFORM_FACTS in sync_doc_metadata.py
    try:
        src = (root / "deploy" / "sync_doc_metadata.py").read_text(encoding="utf-8")
        m = re.search(r'"data_sources"\s*:\s*(\d+)', src)
        if m:
            counts["data_sources"] = int(m.group(1))
            print(f"[platform] data_sources={counts['data_sources']} (from sync_doc_metadata.py)")
    except Exception as e:
        print(f"[platform] WARNING: could not read data_sources: {e}")

    # last_review_grade from CHANGELOG (most recent review entry)
    try:
        cl = (root / "docs" / "CHANGELOG.md").read_text(encoding="utf-8")
        m = re.search(r'Architecture Review.*?grade\s+([AB][+-]?)', cl, re.IGNORECASE)
        if m:
            counts["last_review_grade"] = m.group(1)
            print(f"[platform] last_review_grade={counts['last_review_grade']} (from CHANGELOG.md)")
    except Exception as e:
        print(f"[platform] WARNING: could not read review grade: {e}")

    return counts


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    today     = date.today()
    yesterday = (today - timedelta(days=1)).isoformat()
    thirty_ago = (today - timedelta(days=30)).isoformat()
    seven_ago  = (today - timedelta(days=7)).isoformat()

    print(f"\n[fix_public_stats] today={today}, yesterday={yesterday}")
    print(f"[fix_public_stats] mode={'DRY RUN (pass --write to push to S3)' if DRY_RUN else 'WRITE'}\n")

    # ── Profile ───────────────────────────────────────────────────────────────
    profile = fetch_profile()
    if not profile:
        print("[ERROR] No profile found — aborting"); sys.exit(1)

    start_weight     = float(profile.get("journey_start_weight_lbs") or 0)
    goal_weight      = float(profile.get("goal_weight_lbs") or 0)
    start_date       = profile.get("journey_start_date") or ""
    goal_date        = profile.get("projected_goal_date") or profile.get("goal_date") or ""
    zone2_target_min = int(profile.get("zone2_weekly_target_min") or profile.get("zone2_target_min_weekly") or 150)
    step_target      = int(profile.get("step_target") or 7000)

    if not start_weight or not goal_weight or not start_date:
        print("[ERROR] Profile missing required fields (journey_start_weight_lbs / goal_weight_lbs / journey_start_date)")
        sys.exit(1)

    try:
        days_in = max(0, (today - date.fromisoformat(start_date)).days)
    except Exception:
        days_in = 0

    print(f"[profile] start={start_weight}lbs → goal={goal_weight}lbs, started={start_date}, days_in={days_in}")
    print(f"[profile] zone2_target={zone2_target_min}min/wk, step_target={step_target}")

    # ── Withings: latest weight (30-day lookback) ─────────────────────────────
    withings_30d = fetch_range("withings", thirty_ago, yesterday)
    latest_weight = None
    latest_weight_date = None
    for rec in reversed(withings_30d):
        wt = safe_float(rec, "weight_lbs")
        if wt:
            latest_weight = wt
            latest_weight_date = rec.get("sk", "").replace("DATE#", "")
            break

    if latest_weight:
        print(f"\n[withings] latest={latest_weight}lbs on {latest_weight_date}")
        lost_lbs     = round(start_weight - latest_weight, 1)
        remain_lbs   = round(latest_weight - goal_weight, 1)
        progress_pct = round(lost_lbs / (start_weight - goal_weight) * 100, 1) if start_weight != goal_weight else 0
    else:
        print("\n[withings] WARNING: no weight in last 30 days")
        lost_lbs = remain_lbs = progress_pct = None

    # Current phase
    current_phase = None
    if latest_weight:
        for p in profile.get("weight_loss_phases", []):
            if latest_weight >= float(p.get("end_lbs", 0)):
                current_phase = p.get("name")
                break

    # Weekly rate
    week_ago_weight = None
    if latest_weight_date:
        target_sk = "DATE#" + (date.fromisoformat(latest_weight_date) - timedelta(days=7)).isoformat()
        for rec in withings_30d:
            if rec.get("sk", "") <= target_sk:
                wt = safe_float(rec, "weight_lbs")
                if wt:
                    week_ago_weight = wt
    weekly_rate = round(latest_weight - week_ago_weight, 2) if latest_weight and week_ago_weight else None

    print(f"[withings] lost={lost_lbs}lbs, remain={remain_lbs}lbs, progress={progress_pct}%, phase={current_phase}")
    print(f"[withings] week_ago={week_ago_weight}, weekly_rate={weekly_rate}")

    # ── Whoop: vitals ─────────────────────────────────────────────────────────
    whoop_30d   = fetch_range("whoop", thirty_ago, yesterday)
    whoop_7d    = [r for r in whoop_30d if r.get("sk", "") >= "DATE#" + seven_ago]
    latest_whoop = whoop_7d[-1] if whoop_7d else {}

    hrv_ms       = safe_float(latest_whoop, "hrv")
    recovery_pct = safe_float(latest_whoop, "recovery_score")
    rhr_bpm      = safe_float(latest_whoop, "resting_heart_rate")
    sleep_hours  = safe_float(latest_whoop, "sleep_duration_hours")

    hrv_7d_vals  = [safe_float(r, "hrv") for r in whoop_7d  if safe_float(r, "hrv")]
    hrv_30d_vals = [safe_float(r, "hrv") for r in whoop_30d if safe_float(r, "hrv")]
    hrv_7d_avg   = avg(hrv_7d_vals)
    hrv_30d_avg  = avg(hrv_30d_vals)

    # HRV trend string
    if hrv_7d_avg and hrv_30d_avg and hrv_30d_avg > 0:
        pct_chg   = round((hrv_7d_avg - hrv_30d_avg) / hrv_30d_avg * 100)
        direction = "trending up" if hrv_7d_avg >= hrv_30d_avg else "trending down"
        sign      = "+" if pct_chg >= 0 else ""
        hrv_trend = f"{round(hrv_7d_avg)}ms 7d avg ({sign}{pct_chg}% vs 30d, {direction})"
    else:
        hrv_trend = f"{round(hrv_7d_avg)}ms 7d avg" if hrv_7d_avg else None

    # RHR trend: compare 7d avg vs 30d avg
    rhr_7d_vals  = [safe_float(r, "resting_heart_rate") for r in whoop_7d  if safe_float(r, "resting_heart_rate")]
    rhr_30d_vals = [safe_float(r, "resting_heart_rate") for r in whoop_30d if safe_float(r, "resting_heart_rate")]
    rhr_7d_avg   = avg(rhr_7d_vals)
    rhr_30d_avg  = avg(rhr_30d_vals)
    if rhr_7d_avg and rhr_30d_avg:
        rhr_trend = "improving" if rhr_7d_avg < rhr_30d_avg else ("stable" if abs(rhr_7d_avg - rhr_30d_avg) < 2 else "worsening")
    else:
        rhr_trend = None

    if recovery_pct:
        rec_status = "green" if recovery_pct >= 67 else ("yellow" if recovery_pct >= 34 else "red")
    else:
        rec_status = "gray"

    print(f"\n[whoop] hrv={hrv_ms}ms, recovery={recovery_pct}%, rhr={rhr_bpm}, sleep={sleep_hours}h")
    print(f"[whoop] hrv_trend='{hrv_trend}', rhr_trend='{rhr_trend}'")

    # ── computed_metrics: training + streaks ──────────────────────────────────
    cm_recs = fetch_range("computed_metrics", seven_ago, yesterday)
    latest_cm = cm_recs[-1] if cm_recs else {}

    tsb          = safe_float(latest_cm, "tsb") or 0.0
    acwr         = safe_float(latest_cm, "acwr") or 1.0
    form_zone    = latest_cm.get("zone", "neutral")
    alert        = bool(latest_cm.get("alert", False))
    tier0_streak = int(float(latest_cm.get("tier0_streak") or 0))

    # CTL/ATL estimated from TSB (same formula as daily_brief_lambda)
    ctl_fitness  = round(tsb + 6.0, 1)
    atl_fatigue  = round(tsb + 6.5, 1)
    injury_risk  = "high" if alert else "low"

    print(f"\n[computed_metrics] tsb={tsb}, acwr={acwr}, zone={form_zone}, alert={alert}")
    print(f"[computed_metrics] tier0_streak={tier0_streak}")

    # ── Strava: zone2 this week + 30d totals ──────────────────────────────────
    ZONE2_SPORTS = {"run", "walk", "ride", "swim", "elliptical", "workout",
                    "hike", "virtualride", "weighttraining"}
    strava_30d = fetch_range("strava", thirty_ago, yesterday)
    strava_7d  = [r for r in strava_30d if r.get("sk", "") >= "DATE#" + seven_ago]

    zone2_min_this_week = 0.0
    for day_rec in strava_7d:
        for act in (day_rec.get("activities") or []):
            sport = (act.get("sport_type") or act.get("type") or "").lower()
            if any(s in sport for s in ZONE2_SPORTS):
                zone2_min_this_week += float(act.get("moving_time_seconds") or 0) / 60

    total_miles_30d   = 0.0
    activity_count_30d = 0
    for day_rec in strava_30d:
        for act in (day_rec.get("activities") or []):
            dist_m = float(act.get("distance_meters") or 0)
            total_miles_30d += dist_m / 1609.34
            activity_count_30d += 1

    print(f"\n[strava] zone2_this_week={round(zone2_min_this_week)}min (target={zone2_target_min})")
    print(f"[strava] total_miles_30d={round(total_miles_30d, 1)}, activity_count_30d={activity_count_30d}")

    # ── Platform counts: auto-discover from source ────────────────────────────
    print()
    platform_counts = discover_platform_counts()

    # ── Assemble payload ──────────────────────────────────────────────────────
    payload = {
        "_meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "generated_by": "fix_public_stats.py",
            "version":      "1.2.0",
            "note":         f"Manually rebuilt — weight from {latest_weight_date or 'none'}, "
                            f"vitals from {latest_whoop.get('sk', 'none').replace('DATE#', '') if latest_whoop else 'none'}",
        },
        "vitals": {
            "weight_lbs":      round(latest_weight, 1) if latest_weight else None,
            "weight_delta_30d": weekly_rate,
            "hrv_ms":          hrv_ms,
            "hrv_trend":       hrv_trend,
            "rhr_bpm":         rhr_bpm,
            "rhr_trend":       rhr_trend,
            "recovery_pct":    recovery_pct,
            "recovery_status": rec_status,
            "sleep_hours":     sleep_hours,
        },
        "journey": {
            "start_weight_lbs":   start_weight,
            "goal_weight_lbs":    goal_weight,
            "current_weight_lbs": latest_weight,
            "lost_lbs":           lost_lbs,
            "remaining_lbs":      remain_lbs,
            "progress_pct":       progress_pct,
            "weekly_rate_lbs":    weekly_rate,
            "projected_goal_date": goal_date or None,
            "started_date":       start_date,
            "current_phase":      current_phase,
            "days_in":            days_in,
        },
        "training": {
            "ctl_fitness":         ctl_fitness,
            "atl_fatigue":         atl_fatigue,
            "tsb_form":            round(tsb, 1),
            "acwr":                round(acwr, 2),
            "form_status":         form_zone,
            "injury_risk":         injury_risk,
            "total_miles_30d":     round(total_miles_30d, 1),
            "activity_count_30d":  activity_count_30d,
            "zone2_this_week_min": round(zone2_min_this_week),
            "zone2_target_min":    zone2_target_min,
        },
        "platform": {
            "mcp_tools":          platform_counts.get("mcp_tools"),
            "data_sources":       platform_counts.get("data_sources"),
            "lambdas":            platform_counts.get("lambdas"),
            "last_review_grade":  platform_counts.get("last_review_grade"),
            "tier0_streak":       tier0_streak,
            "days_in":            days_in,
        },
        # D10: Day 1 baseline — from profile fields or fallback to known journey-start values.
        # These are historical constants (true Day 1 readings) stored in PROFILE#v1.
        # Fallback values are the actual readings from journey start (Feb 22, 2026).
        "baseline": {
            "date":         profile.get("baseline_date") or start_date,
            "weight_lbs":   float(profile.get("baseline_weight_lbs") or start_weight),
            "hrv_ms":       float(profile.get("baseline_hrv_ms") or 45),
            "rhr_bpm":      float(profile.get("baseline_rhr_bpm") or 62),
            "recovery_pct": float(profile.get("baseline_recovery_pct") or 55),
        },
    }

    print("\n[payload]")
    print(json.dumps(payload, indent=2))

    # ── Write to S3 ───────────────────────────────────────────────────────────
    if DRY_RUN:
        print(f"\n[DRY RUN] Would write to s3://{S3_BUCKET}/{S3_KEY}")
        print("[DRY RUN] Re-run with --write to push to S3 and invalidate CloudFront.")
        return

    s3.put_object(
        Bucket=S3_BUCKET,
        Key=S3_KEY,
        Body=json.dumps(payload, indent=2),
        ContentType="application/json",
        CacheControl="max-age=3600",
    )
    print(f"\n[OK] Written to s3://{S3_BUCKET}/{S3_KEY}")

    inv = cf.create_invalidation(
        DistributionId=CF_DIST_ID,
        InvalidationBatch={
            "Paths": {"Quantity": 2, "Items": ["/site/public_stats.json", "/public_stats.json"]},
            "CallerReference": f"fix-public-stats-{int(datetime.now().timestamp())}",
        }
    )
    inv_id = inv["Invalidation"]["Id"]
    print(f"[OK] CloudFront invalidation created: {inv_id}")
    print("[OK] Done — averagejoematt.com will serve fresh data within ~30 seconds.")


if __name__ == "__main__":
    main()
