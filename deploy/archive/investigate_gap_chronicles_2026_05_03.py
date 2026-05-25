#!/usr/bin/env python3
"""
investigate_gap_chronicles_2026_05_03.py
========================================

Read-only investigation of what Elena's wednesday-chronicle Lambda produced
during the April 12 → May 1 platform gap. Returns a summary of every
chronicle record in DDB with date >= 2026-04-08 (start of the first
Wednesday in the gap window) so we can decide what to delete.

Companion cleanup script (TBD after this runs): cleanup_gap_chronicles_2026_05_03.py

Usage:
    python3 deploy/investigate_gap_chronicles_2026_05_03.py
"""
import json
from datetime import datetime
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key

REGION = "us-west-2"
TABLE  = "life-platform"
USER_ID = "matthew"
GAP_START_DATE = "2026-04-08"  # First Wednesday during the gap
S3_BUCKET = "matthew-life-platform"


def d2f(obj):
    if isinstance(obj, list):    return [d2f(i) for i in obj]
    if isinstance(obj, dict):    return {k: d2f(v) for k, v in obj.items()}
    if isinstance(obj, Decimal): return float(obj)
    return obj


def main():
    print(f"\n=== Chronicle Gap Investigation ===")
    print(f"  table:  {TABLE} ({REGION})")
    print(f"  pk:     USER#{USER_ID}#SOURCE#chronicle")
    print(f"  cutoff: sk >= DATE#{GAP_START_DATE}")
    print()

    ddb = boto3.resource("dynamodb", region_name=REGION)
    table = ddb.Table(TABLE)
    s3 = boto3.client("s3", region_name=REGION)

    # ── Phase 1: Query DDB for all chronicle records ──
    print("Phase 1: Querying chronicle partition...")
    pk = f"USER#{USER_ID}#SOURCE#chronicle"
    resp = table.query(
        KeyConditionExpression=Key("pk").eq(pk) & Key("sk").begins_with("DATE#"),
        ScanIndexForward=False,  # newest first
    )
    items = [d2f(i) for i in resp.get("Items", [])]
    print(f"  → {len(items)} total chronicle records in DDB")

    # ── Phase 2: Filter to gap window + later ──
    gap_or_after = [i for i in items if i.get("date", "") >= GAP_START_DATE]
    print(f"  → {len(gap_or_after)} records dated >= {GAP_START_DATE}")
    print()

    if not gap_or_after:
        print("✓ No chronicle records in or after the gap window. Clean state.")
        return 0

    # ── Phase 3: Show what's there ──
    print("Phase 2: Records in/after gap window (newest first):")
    print()
    by_status = {"draft": [], "published": [], "unknown": []}
    for r in gap_or_after:
        date     = r.get("date", "?")
        week     = r.get("week_number", "?")
        title    = r.get("title", "?")
        status   = r.get("status", "unknown")
        words    = r.get("word_count", 0)
        gen_at   = r.get("generated_at", "?")[:19]
        sk       = r.get("sk", "?")
        has_token = bool(r.get("approval_token"))
        has_blog_draft = bool(r.get("draft_blog_post_html"))

        by_status.setdefault(status, []).append(r)

        print(f"  [{status.upper():9}] Week {week} · {date}")
        print(f"             Title:        \"{title}\"")
        print(f"             SK:           {sk}")
        print(f"             Generated:    {gen_at}")
        print(f"             Words:        {words}")
        print(f"             Pending approval: {has_token}")
        print(f"             Has draft HTML: {has_blog_draft}")
        print()

    # ── Phase 4: Cross-check S3 for any published artifacts ──
    print("Phase 3: Cross-check S3 for published artifacts...")
    s3_findings = {"blog": [], "journal": []}
    for r in gap_or_after:
        wn = r.get("week_number")
        if wn is None:
            continue
        try:
            wn = int(wn)
        except (ValueError, TypeError):
            continue
        # Blog
        blog_key = f"blog/week-{wn:02d}.html"
        try:
            head = s3.head_object(Bucket=S3_BUCKET, Key=blog_key)
            s3_findings["blog"].append({
                "week":     wn,
                "key":      blog_key,
                "modified": head["LastModified"].isoformat(),
                "size":     head["ContentLength"],
            })
        except Exception:
            pass
        # Journal
        journal_key = f"generated/journal/posts/week-{wn:02d}/index.html"
        try:
            head = s3.head_object(Bucket=S3_BUCKET, Key=journal_key)
            s3_findings["journal"].append({
                "week":     wn,
                "key":      journal_key,
                "modified": head["LastModified"].isoformat(),
                "size":     head["ContentLength"],
            })
        except Exception:
            pass

    if s3_findings["blog"] or s3_findings["journal"]:
        print("  ⚠️  PUBLISHED ARTIFACTS FOUND ON S3:")
        for art in s3_findings["blog"]:
            print(f"     blog/week-{art['week']:02d}.html  ({art['size']} bytes, modified {art['modified']})")
        for art in s3_findings["journal"]:
            print(f"     {art['key']}  ({art['size']} bytes, modified {art['modified']})")
        print()
        print("  → These ARE live on the public site. Need cleanup.")
    else:
        print("  ✓ No published blog or journal artifacts for these weeks on S3.")
        print("  → Drafts in DDB only — never made it to the public site.")
    print()

    # ── Summary ──
    print("=" * 60)
    print("SUMMARY")
    print(f"  Draft records (in DDB only):     {len(by_status['draft'])}")
    print(f"  Published records (in DDB):      {len(by_status['published'])}")
    print(f"  Unknown status:                  {len(by_status['unknown'])}")
    print(f"  S3 blog artifacts found:         {len(s3_findings['blog'])}")
    print(f"  S3 journal artifacts found:      {len(s3_findings['journal'])}")
    print()
    print("RECOMMENDED CLEANUP:")
    if not gap_or_after:
        print("  Nothing to do.")
    elif not s3_findings["blog"] and not s3_findings["journal"] and all(r.get("status") == "draft" for r in gap_or_after):
        print("  All gap-period chronicles are drafts only. Safe to soft-delete from DDB:")
        print("    - Set status='archived_low_quality'")
        print("    - Set archived_reason='generated_during_april_2026_gap_no_input'")
        print("    - Keep records for audit; remove from any UI rendering")
        print("  No CloudFront invalidation needed (nothing public).")
    else:
        print("  Mixed state — some published artifacts exist on S3.")
        print("  Cleanup needs to:")
        print("    1. Soft-delete each DDB record (mark archived)")
        print("    2. Delete each S3 published artifact (blog/ + generated/journal/)")
        print("    3. Rebuild blog/index.html and generated/journal/posts.json")
        print("    4. CloudFront invalidate /blog/* and /journal/*")
        print()
        print("  This warrants a separate cleanup script — don't try by hand.")
    print()
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
