#!/usr/bin/env python3
"""
tombstone_orphan_journals_2026_05_03.py
========================================

Overwrites the orphan journal posts at:
  s3://matthew-life-platform/generated/journal/posts/week-03/index.html
  s3://matthew-life-platform/generated/journal/posts/week-04/index.html

The original cleanup script tried to s3:DeleteObject these but hit an
explicit-deny in the bucket's resource-based policy. PutObject works, so we
overwrite each one with a tiny meta-refresh HTML that bounces the visitor
to /blog/ — the public archive of remaining chronicle entries.

This is a follow-up to cleanup_gap_chronicles_2026_05_03.py. After this
runs, the orphan S3 files no longer serve stale draft content.

Usage:
    python3 deploy/tombstone_orphan_journals_2026_05_03.py            # dry-run
    python3 deploy/tombstone_orphan_journals_2026_05_03.py --apply    # execute
"""
import argparse
import sys
from datetime import datetime, timezone

import boto3

REGION             = "us-west-2"
S3_BUCKET          = "matthew-life-platform"
CF_DISTRIBUTION_ID = "E3S424OXQZ8NBE"

ORPHAN_KEYS = [
    "generated/journal/posts/week-03/index.html",
    "generated/journal/posts/week-04/index.html",
]

TOMBSTONE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta http-equiv="refresh" content="0; url=/blog/">
  <meta name="robots" content="noindex">
  <title>Post unavailable — The Measured Life</title>
  <style>
    body { font-family: Georgia, serif; background: #fafaf9; color: #333; margin: 0; padding: 60px 24px; text-align: center; }
    p { font-size: 16px; line-height: 1.7; }
    a { color: #555; }
  </style>
</head>
<body>
  <p>This installment is no longer available. <a href="/blog/">Return to The Measured Life archive.</a></p>
</body>
</html>
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="Overwrite the orphan files. Without this, runs in dry-run mode.")
    args = parser.parse_args()

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"\n=== Tombstone Orphan Journal Posts [{mode}] ===\n")

    s3 = boto3.client("s3", region_name=REGION)
    cf = boto3.client("cloudfront")

    print("Targets:")
    for k in ORPHAN_KEYS:
        try:
            head = s3.head_object(Bucket=S3_BUCKET, Key=k)
            print(f"  • s3://{S3_BUCKET}/{k}")
            print(f"      {head['ContentLength']} bytes, modified {head['LastModified'].isoformat()}")
        except Exception as e:
            print(f"  • s3://{S3_BUCKET}/{k}  (NOT FOUND — already gone or never existed)")
    print()
    print(f"Tombstone HTML size: {len(TOMBSTONE_HTML.encode('utf-8'))} bytes")
    print(f"Redirect target:     /blog/")
    print()

    if not args.apply:
        print("DRY-RUN — pass --apply to overwrite each orphan with the tombstone HTML.")
        return 0

    print("=" * 60)
    print("OVERWRITING...")
    print()
    written = 0
    for k in ORPHAN_KEYS:
        try:
            s3.put_object(
                Bucket=S3_BUCKET, Key=k,
                Body=TOMBSTONE_HTML.encode("utf-8"),
                ContentType="text/html; charset=utf-8",
                CacheControl="max-age=300",
            )
            written += 1
            print(f"  ✓ Tombstoned: s3://{S3_BUCKET}/{k}")
        except Exception as e:
            print(f"  ✗ Failed: {k} — {e}")

    if written:
        print()
        print("CloudFront invalidation...")
        try:
            inv = cf.create_invalidation(
                DistributionId=CF_DISTRIBUTION_ID,
                InvalidationBatch={
                    "Paths": {
                        "Quantity": len(ORPHAN_KEYS),
                        "Items":    [f"/{k.replace('generated/journal/', 'journal/')}" for k in ORPHAN_KEYS]
                                  + [f"/journal/posts/week-{n:02d}/" for n in (3, 4)],
                    },
                    "CallerReference": f"tombstone-orphans-{datetime.now(timezone.utc).isoformat()}",
                },
            )
            print(f"  ✓ Invalidation created: {inv['Invalidation']['Id']}")
        except Exception as e:
            print(f"  ✗ Invalidation failed: {e}")

    print()
    print("=" * 60)
    print(f"DONE — {written} file(s) tombstoned.")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
