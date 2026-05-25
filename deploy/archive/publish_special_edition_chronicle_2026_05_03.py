#!/usr/bin/env python3
"""
publish_special_edition_chronicle_2026_05_03.py
================================================

Publishes "The Architecture of Absence" (Cycle 2 special-edition chronicle)
directly to the live site, bypassing the normal Wednesday-chronicle Lambda
flow. Sources content from docs/elena_special_edition_chronicle_2026_05_03.md.

This reuses the publishing functions from lambdas/wednesday_chronicle_lambda.py
to ensure the artifact looks identical to a regular Wednesday installment —
same blog template, same journal template, same DDB schema.

Does NOT send the SES email.
Does NOT generate from data — content is fixed in the markdown file.

Important: Run cleanup_gap_chronicles_2026_05_03.py with --apply first to clear
the stale Apr 8 / 15 / 22 / 29 draft records before publishing this one.

Usage:
    python3 deploy/publish_special_edition_chronicle_2026_05_03.py            # dry-run
    python3 deploy/publish_special_edition_chronicle_2026_05_03.py --apply    # publish
"""
import argparse
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal

# ── Set env vars BEFORE importing the lambda module ─────────────────────────
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LAMBDAS_DIR  = os.path.join(PROJECT_ROOT, "lambdas")

os.environ.setdefault("AWS_REGION",          "us-west-2")
os.environ.setdefault("TABLE_NAME",          "life-platform")
os.environ.setdefault("S3_BUCKET",           "matthew-life-platform")
os.environ.setdefault("USER_ID",             "matthew")
os.environ.setdefault("EMAIL_RECIPIENT",     "noop@noop.invalid")  # not sent
os.environ.setdefault("EMAIL_SENDER",        "noop@noop.invalid")  # not sent
os.environ.setdefault("PREVIEW_MODE",        "false")              # direct publish
os.environ.setdefault("APPROVE_LAMBDA_URL",  "")

sys.path.insert(0, LAMBDAS_DIR)

import boto3
from boto3.dynamodb.conditions import Key
import wednesday_chronicle_lambda as chronicle_lambda  # type: ignore

# ── Configuration ───────────────────────────────────────────────────────────
REGION             = "us-west-2"
TABLE              = "life-platform"
USER_ID            = "matthew"
S3_BUCKET          = "matthew-life-platform"
CF_DISTRIBUTION_ID = "E3S424OXQZ8NBE"

CHRONICLE_MD_PATH  = os.path.join(PROJECT_ROOT, "docs",
                                  "elena_special_edition_chronicle_2026_05_03.md")
PUBLISH_DATE       = "2026-05-04"   # Monday
WEEK_NUMBER        = 5              # Calendar week 5 of journey (Apr 29 - May 5)


def d2f(obj):
    if isinstance(obj, list):    return [d2f(i) for i in obj]
    if isinstance(obj, dict):    return {k: d2f(v) for k, v in obj.items()}
    if isinstance(obj, Decimal): return float(obj)
    return obj


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="Publish to live site. Without this, runs in dry-run mode.")
    args = parser.parse_args()

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"\n=== Publish Special Edition Chronicle [{mode}] ===\n")

    # ── 1. Read the chronicle markdown ──────────────────────────────────────
    if not os.path.isfile(CHRONICLE_MD_PATH):
        print(f"ERROR: Chronicle markdown not found at {CHRONICLE_MD_PATH}")
        return 1

    with open(CHRONICLE_MD_PATH, "r", encoding="utf-8") as f:
        raw_markdown = f.read()
    print(f"  Markdown source:  {CHRONICLE_MD_PATH}")
    print(f"  Markdown length:  {len(raw_markdown)} chars (~{len(raw_markdown.split())} words)")

    # ── 2. Parse title / stats / body via the same parser the Lambda uses ───
    title, stats_line, body_md = chronicle_lambda.parse_installment(raw_markdown)
    body_html = chronicle_lambda.markdown_to_html(body_md)

    print(f"  Title:            \"{title}\"")
    print(f"  Stats line:       {stats_line}")
    print(f"  Body HTML length: {len(body_html)} chars")
    print(f"  Publish date:     {PUBLISH_DATE}")
    print(f"  Week number:      {WEEK_NUMBER}")
    print()

    has_board = ">" in body_md  # blockquote indicator (none in this piece)

    # ── 3. Pre-flight: confirm no stale gap draft at this week_number ───────
    ddb   = boto3.resource("dynamodb", region_name=REGION)
    table = ddb.Table(TABLE)
    s3    = boto3.client("s3", region_name=REGION)
    cf    = boto3.client("cloudfront")

    pk = f"USER#{USER_ID}#SOURCE#chronicle"
    print("Pre-flight: checking for conflicts at this week_number / date...")
    resp = table.query(
        KeyConditionExpression=Key("pk").eq(pk) & Key("sk").begins_with("DATE#"),
        ScanIndexForward=False,
    )
    existing = [d2f(i) for i in resp.get("Items", [])]

    # Real conflicts: would overwrite something we care about.
    #   - Same date  → DDB sk collision
    #   - Same week_number AND status=published → S3 blog/journal artifact would clobber a real published piece
    # Stale drafts at the same week_number but a different date are NOT blocking — they just sit in DDB.
    real_conflicts = [
        i for i in existing
        if i.get("date") == PUBLISH_DATE
        or (i.get("week_number") == WEEK_NUMBER and i.get("status") == "published")
    ]
    stale_drafts_same_week = [
        i for i in existing
        if i.get("week_number") == WEEK_NUMBER
        and i.get("status") != "published"
        and i.get("date") != PUBLISH_DATE
    ]

    if real_conflicts:
        print(f"  ❌ {len(real_conflicts)} BLOCKING conflict(s) — same date or same week+published:")
        for c in real_conflicts:
            print(f"     - sk={c.get('sk')}  week={c.get('week_number')}  status={c.get('status')}  title=\"{c.get('title')}\"")
        if args.apply:
            print(f"  → Refusing to publish over a real conflict. Aborting.")
            return 2
    else:
        print(f"  ✓ No blocking conflicts at date={PUBLISH_DATE} (no same-date record, no published record at week={WEEK_NUMBER}).")

    if stale_drafts_same_week:
        print(f"  ℹ️  {len(stale_drafts_same_week)} stale draft(s) at week={WEEK_NUMBER} (informational only, not blocking):")
        for c in stale_drafts_same_week:
            print(f"     - sk={c.get('sk')}  status={c.get('status')}  title=\"{c.get('title')}\"")
        print(f"     These remain in DDB. They have different sk than ours so will not be overwritten.")
    print()

    # ── 4. Build all_installments list (for index rebuild) ──────────────────
    # Filter to non-draft records only (drafts shouldn't appear in public index).
    all_installments = [i for i in existing if i.get("status") != "draft"]
    # Prepend the new record so the index includes it.
    all_installments = [{
        "title":               title,
        "week_number":         WEEK_NUMBER,
        "date":                PUBLISH_DATE,
        "stats_line":          stats_line,
        "word_count":          len(raw_markdown.split()),
        "content_markdown":    raw_markdown[:300],
        "has_board_interview": has_board,
        "status":              "published",
    }] + all_installments

    print(f"  Index will be rebuilt with {len(all_installments)} total installment(s).")
    print()

    # ── 5. Plan ─────────────────────────────────────────────────────────────
    print("Planned actions:")
    print(f"  • DDB put_item:  pk={pk}  sk=DATE#{PUBLISH_DATE}  status=published")
    print(f"  • S3 put:        blog/week-{WEEK_NUMBER:02d}.html")
    print(f"  • S3 put:        blog/style.css")
    print(f"  • S3 put:        blog/index.html (rebuilt from {len(all_installments)} entries)")
    print(f"  • S3 put:        generated/journal/posts/week-{WEEK_NUMBER:02d}/index.html")
    print(f"  • S3 put:        generated/journal/posts.json (rebuilt)")
    print(f"  • CloudFront invalidation: /blog/* /journal/*")
    print()

    if not args.apply:
        print("DRY-RUN — pass --apply to publish.")
        return 0

    # ── 6. Execute ──────────────────────────────────────────────────────────
    print("=" * 60)
    print("PUBLISHING...")
    print()

    # 6a. Store DDB record (status=published, no draft fields)
    try:
        chronicle_lambda.store_installment(
            date_str          = PUBLISH_DATE,
            week_num          = WEEK_NUMBER,
            title             = title,
            stats_line        = stats_line,
            raw_markdown      = raw_markdown,
            body_html         = body_html,
            themes            = [],
            has_board         = has_board,
            confidence_level  = "MEDIUM",
            confidence_badge_html = "",
            status            = "published",
        )
        print(f"  ✓ DDB record stored: Week {WEEK_NUMBER} ({PUBLISH_DATE})")
    except Exception as e:
        print(f"  ✗ DDB store failed: {e}")
        return 3

    # 6b. Publish to /blog/
    try:
        blog_url = chronicle_lambda.publish_to_blog(
            title           = title,
            stats_line      = stats_line,
            body_html       = body_html,
            week_num        = WEEK_NUMBER,
            date_str        = PUBLISH_DATE,
            all_installments= all_installments,
            write_to_s3     = True,
        )
        print(f"  ✓ Blog published: {blog_url}")
    except Exception as e:
        print(f"  ✗ publish_to_blog failed: {e}")

    # 6c. Publish to /journal/
    try:
        journal_url = chronicle_lambda.publish_to_journal(
            title           = title,
            stats_line      = stats_line,
            body_html       = body_html,
            week_num        = WEEK_NUMBER,
            date_str        = PUBLISH_DATE,
            all_installments= all_installments,
            write_to_s3     = True,
        )
        print(f"  ✓ Journal published: {journal_url}")
    except Exception as e:
        print(f"  ✗ publish_to_journal failed: {e}")

    # 6d. CloudFront invalidation
    try:
        inv = cf.create_invalidation(
            DistributionId=CF_DISTRIBUTION_ID,
            InvalidationBatch={
                "Paths": {"Quantity": 2, "Items": ["/blog/*", "/journal/*"]},
                "CallerReference": f"special-edition-publish-{datetime.now(timezone.utc).isoformat()}",
            },
        )
        print(f"  ✓ CloudFront invalidation: {inv['Invalidation']['Id']}")
    except Exception as e:
        print(f"  ✗ CloudFront invalidation failed: {e}")

    print()
    print("=" * 60)
    print("DONE")
    print()
    print("Verify at:")
    print(f"  https://averagejoematt.com/blog/week-{WEEK_NUMBER:02d}.html")
    print(f"  https://averagejoematt.com/journal/posts/week-{WEEK_NUMBER:02d}/")
    print(f"  https://averagejoematt.com/blog/")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
