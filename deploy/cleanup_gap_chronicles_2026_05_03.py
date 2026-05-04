#!/usr/bin/env python3
"""
cleanup_gap_chronicles_2026_05_03.py
=====================================

Removes all chronicle records dated 2026-04-08 → 2026-05-02 (the gap window
when Matthew was off-grid for the house move and the wednesday-chronicle
Lambda fired into an empty room four Wednesdays in a row).

Handles both:
  • Drafts (status="draft" with no S3 artifacts)        → DDB delete only
  • Anything published to S3                            → DDB delete + S3 delete + index rebuild + CF invalidate

Dry-run by default. Pass --apply to execute.

Usage:
    python3 deploy/cleanup_gap_chronicles_2026_05_03.py            # dry-run
    python3 deploy/cleanup_gap_chronicles_2026_05_03.py --apply    # execute
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key

REGION             = "us-west-2"
TABLE              = "life-platform"
USER_ID            = "matthew"
S3_BUCKET          = "matthew-life-platform"
CF_DISTRIBUTION_ID = "E3S424OXQZ8NBE"

GAP_START_DATE = "2026-04-08"   # First Wednesday during the gap
GAP_END_DATE   = "2026-05-02"   # Last day before re-entry


def d2f(obj):
    if isinstance(obj, list):    return [d2f(i) for i in obj]
    if isinstance(obj, dict):    return {k: d2f(v) for k, v in obj.items()}
    if isinstance(obj, Decimal): return float(obj)
    return obj


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="Execute the cleanup. Without this flag, runs in dry-run mode.")
    args = parser.parse_args()

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"\n=== Chronicle Gap Cleanup [{mode}] ===")
    print(f"  table:        {TABLE}")
    print(f"  s3 bucket:    {S3_BUCKET}")
    print(f"  cf:           {CF_DISTRIBUTION_ID}")
    print(f"  gap window:   {GAP_START_DATE} → {GAP_END_DATE}")
    print()

    ddb   = boto3.resource("dynamodb", region_name=REGION)
    table = ddb.Table(TABLE)
    s3    = boto3.client("s3", region_name=REGION)
    cf    = boto3.client("cloudfront")

    # ── Phase 1: Find candidates ─────────────────────────────────────────────
    print("Phase 1: Querying chronicle partition for gap-window records...")
    pk = f"USER#{USER_ID}#SOURCE#chronicle"
    resp = table.query(
        KeyConditionExpression=Key("pk").eq(pk) &
                                Key("sk").between(f"DATE#{GAP_START_DATE}", f"DATE#{GAP_END_DATE}~"),
        ScanIndexForward=False,
    )
    candidates = [d2f(i) for i in resp.get("Items", [])]
    print(f"  → {len(candidates)} record(s) found in gap window.")
    print()

    if not candidates:
        print("✓ Nothing to clean up. Exiting.")
        return 0

    # ── Phase 2: Classify each record ────────────────────────────────────────
    print("Phase 2: Classifying records and cross-checking S3...")
    actions = []

    for r in candidates:
        date     = r.get("date", "?")
        sk       = r.get("sk", "?")
        wn       = r.get("week_number")
        try:
            wn_int = int(wn) if wn is not None else None
        except (ValueError, TypeError):
            wn_int = None
        title    = r.get("title", "?")
        status   = r.get("status", "unknown")

        s3_artifacts = []

        if wn_int is not None:
            # Blog post
            blog_key = f"blog/week-{wn_int:02d}.html"
            try:
                s3.head_object(Bucket=S3_BUCKET, Key=blog_key)
                s3_artifacts.append(blog_key)
            except Exception:
                pass

            # Journal post (single file under generated/journal/posts/week-NN/)
            journal_dir_prefix = f"generated/journal/posts/week-{wn_int:02d}/"
            try:
                listing = s3.list_objects_v2(Bucket=S3_BUCKET, Prefix=journal_dir_prefix)
                for obj in listing.get("Contents", []):
                    s3_artifacts.append(obj["Key"])
            except Exception as e:
                print(f"  WARN: list_objects_v2 failed for {journal_dir_prefix}: {e}")

        actions.append({
            "pk": pk,
            "sk": sk,
            "date": date,
            "week_number": wn_int,
            "title": title,
            "status": status,
            "s3_artifacts": s3_artifacts,
        })

    # ── Phase 3: Show plan ───────────────────────────────────────────────────
    print()
    print("Phase 3: Planned actions:")
    print()
    needs_index_rebuild = False
    needs_cf_invalidation = False

    for a in actions:
        wn_str = f"Week {a['week_number']}" if a['week_number'] is not None else "Week ?"
        print(f"  • {wn_str} · {a['date']} · status={a['status']}")
        print(f"      Title:       \"{a['title']}\"")
        print(f"      DDB delete:  pk={a['pk']}  sk={a['sk']}")
        if a["s3_artifacts"]:
            needs_index_rebuild = True
            needs_cf_invalidation = True
            for art in a["s3_artifacts"]:
                print(f"      S3 delete:   s3://{S3_BUCKET}/{art}")
        else:
            print(f"      S3:          (no published artifacts found)")
        print()

    if needs_index_rebuild:
        print("  • Rebuild blog/index.html (excluding deleted weeks)")
        print("  • Rebuild generated/journal/posts.json (excluding deleted weeks)")
    if needs_cf_invalidation:
        print(f"  • CloudFront invalidation: /blog/* /journal/*")
    print()

    if not args.apply:
        print("DRY-RUN — pass --apply to execute the above.")
        return 0

    # ── Phase 4: Execute ─────────────────────────────────────────────────────
    print("=" * 60)
    print("EXECUTING...")
    print()

    deleted_ddb = 0
    deleted_s3  = 0

    for a in actions:
        # DDB delete
        try:
            table.delete_item(Key={"pk": a["pk"], "sk": a["sk"]})
            deleted_ddb += 1
            print(f"  ✓ Deleted DDB: {a['sk']}")
        except Exception as e:
            print(f"  ✗ DDB delete failed for {a['sk']}: {e}")

        # S3 delete
        for art in a["s3_artifacts"]:
            try:
                s3.delete_object(Bucket=S3_BUCKET, Key=art)
                deleted_s3 += 1
                print(f"  ✓ Deleted S3: {art}")
            except Exception as e:
                print(f"  ✗ S3 delete failed for {art}: {e}")

    # ── Phase 5: Rebuild indexes if anything was published ───────────────────
    if needs_index_rebuild:
        print()
        print("Phase 5: Rebuilding indexes from remaining DDB chronicle records...")

        # Query ALL remaining chronicle records (post-cleanup)
        resp = table.query(
            KeyConditionExpression=Key("pk").eq(pk) & Key("sk").begins_with("DATE#"),
            ScanIndexForward=False,
        )
        remaining = [d2f(i) for i in resp.get("Items", []) if i.get("status") != "draft"]
        print(f"  → {len(remaining)} non-draft chronicle records remain.")

        # Rebuild blog/index.html — minimal version listing remaining weeks
        blog_index_lines = [
            "<!DOCTYPE html>",
            '<html lang="en"><head><meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width,initial-scale=1">',
            "<title>The Measured Life — by Elena Voss</title>",
            '<link rel="stylesheet" href="style.css"></head>',
            "<body>",
            "<header>",
            '  <span class="series-title">The Measured Life</span>',
            '  <p class="byline">An ongoing chronicle by Elena Voss</p>',
            "</header>",
            "<main>",
            '  <ul class="archive-list">',
        ]
        for inst in remaining:
            wn_r = inst.get("week_number")
            if wn_r is None:
                continue
            try:
                wn_r = int(wn_r)
            except (ValueError, TypeError):
                continue
            t = inst.get("title", "Untitled")
            d = inst.get("date", "")
            try:
                d_disp = datetime.strptime(d, "%Y-%m-%d").strftime("%B %-d, %Y")
            except Exception:
                d_disp = d
            blog_index_lines.append(
                f'    <li><a href="week-{wn_r:02d}.html">"{t}"</a> '
                f'<span class="date">Week {wn_r} · {d_disp}</span></li>'
            )
        blog_index_lines += [
            "  </ul>",
            "</main>",
            "<footer>The Measured Life · A chronicle by Elena Voss · Est. 2026</footer>",
            "</body></html>",
        ]
        blog_index_html = "\n".join(blog_index_lines)
        try:
            s3.put_object(
                Bucket=S3_BUCKET, Key="blog/index.html",
                Body=blog_index_html.encode("utf-8"),
                ContentType="text/html; charset=utf-8",
                CacheControl="max-age=300",
            )
            print(f"  ✓ Rebuilt blog/index.html ({len(remaining)} entries)")
        except Exception as e:
            print(f"  ✗ Failed to rebuild blog/index.html: {e}")

        # Rebuild generated/journal/posts.json
        posts_manifest = []
        for inst in remaining:
            wn_r = inst.get("week_number")
            if wn_r is None:
                continue
            try:
                wn_r = int(wn_r)
            except (ValueError, TypeError):
                continue
            posts_manifest.append({
                "week":                wn_r,
                "title":               inst.get("title", ""),
                "date":                inst.get("date", ""),
                "stats_line":          inst.get("stats_line", ""),
                "url":                 f"/journal/posts/week-{wn_r:02d}/",
                "excerpt":             (inst.get("content_markdown") or "")[:300].strip(),
                "word_count":          inst.get("word_count", 0),
                "has_board_interview": inst.get("has_board_interview", False),
            })
        posts_json = json.dumps(
            {"posts": posts_manifest, "updated_at": datetime.now(timezone.utc).isoformat()},
            indent=2,
        )
        try:
            s3.put_object(
                Bucket=S3_BUCKET, Key="generated/journal/posts.json",
                Body=posts_json.encode("utf-8"),
                ContentType="application/json",
                CacheControl="max-age=300",
            )
            print(f"  ✓ Rebuilt generated/journal/posts.json ({len(posts_manifest)} entries)")
        except Exception as e:
            print(f"  ✗ Failed to rebuild posts.json: {e}")

    # ── Phase 6: CloudFront invalidation ─────────────────────────────────────
    if needs_cf_invalidation:
        print()
        print("Phase 6: CloudFront invalidation...")
        try:
            inv = cf.create_invalidation(
                DistributionId=CF_DISTRIBUTION_ID,
                InvalidationBatch={
                    "Paths": {"Quantity": 2, "Items": ["/blog/*", "/journal/*"]},
                    "CallerReference": f"chronicle-cleanup-{datetime.now(timezone.utc).isoformat()}",
                },
            )
            inv_id = inv["Invalidation"]["Id"]
            print(f"  ✓ CloudFront invalidation created: {inv_id}")
        except Exception as e:
            print(f"  ✗ CloudFront invalidation failed: {e}")

    # ── Summary ──────────────────────────────────────────────────────────────
    print()
    print("=" * 60)
    print("DONE")
    print(f"  DDB records deleted:  {deleted_ddb}")
    print(f"  S3 objects deleted:   {deleted_s3}")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
