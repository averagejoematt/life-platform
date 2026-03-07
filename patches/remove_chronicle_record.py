#!/usr/bin/env python3
"""
remove_chronicle_record.py — Remove a specific DynamoDB chronicle record and patch the index

Deletes the DynamoDB record for "The Week Everything Leveled Up (And Nothing Changed)"
and regenerates the blog index from the remaining records.

Usage: python3 patches/remove_chronicle_record.py
"""

import json
import re
import boto3
from decimal import Decimal

REGION    = "us-west-2"
S3_BUCKET = "matthew-life-platform"
TABLE     = "life-platform"
CF_DIST   = "E1JOC1V6E6DDYI"
PK        = "USER#matthew#SOURCE#chronicle"

s3    = boto3.client("s3", region_name=REGION)
ddb   = boto3.resource("dynamodb", region_name=REGION)
table = ddb.Table(TABLE)
cf    = boto3.client("cloudfront", region_name=REGION)


# ── Step 1: list all chronicle records ───────────────────────────────────────
print("Chronicle records in DynamoDB:\n")
resp = table.query(KeyConditionExpression=boto3.dynamodb.conditions.Key("pk").eq(PK))
items = sorted(resp.get("Items", []), key=lambda x: str(x.get("sk", "")))

to_delete = None
for item in items:
    wn    = item.get("week_number", "?")
    title = item.get("title", "(no title)")
    sk    = item.get("sk", "")
    date  = item.get("date", "?")
    fname = item.get("blog_filename", item.get("filename", "?"))
    marker = " ← DELETE" if "Leveled Up" in title or "Nothing Changed" in title else ""
    print(f"  sk={sk}  week={wn}  date={date}  title={title!r}{marker}")
    if marker:
        to_delete = item

print()

if not to_delete:
    print("Could not find 'The Week Everything Leveled Up' record — may already be deleted.")
    exit(0)

print(f"Target to delete:\n  sk    = {to_delete['sk']}\n  title = {to_delete.get('title')}\n  date  = {to_delete.get('date')}\n")

confirm = input("Delete this DynamoDB record and patch the blog index? [y/N] ").strip().lower()
if confirm != "y":
    print("Aborted.")
    exit(0)

# ── Step 2: delete the DDB record ────────────────────────────────────────────
table.delete_item(Key={"pk": PK, "sk": to_delete["sk"]})
print(f"\nDeleted DynamoDB record sk={to_delete['sk']}")

# ── Step 3: check for orphaned S3 file ───────────────────────────────────────
fname = to_delete.get("blog_filename") or to_delete.get("filename")
if fname:
    s3_key = f"blog/{fname}"
    try:
        s3.head_object(Bucket=S3_BUCKET, Key=s3_key)
        s3.delete_object(Bucket=S3_BUCKET, Key=s3_key)
        print(f"Deleted orphaned S3 file: {s3_key}")
    except s3.exceptions.ClientError:
        print(f"No S3 file at {s3_key} — nothing to delete")

# ── Step 4: patch the index to remove any reference to that title/filename ───
print("Patching blog/index.html ...")
idx_resp = s3.get_object(Bucket=S3_BUCKET, Key="blog/index.html")
index_html = idx_resp["Body"].read().decode("utf-8")
before_len = len(index_html)

# Remove any href referencing the deleted filename
if fname:
    clean_fname = re.escape(fname)
    index_html = re.sub(
        r'<li>\s*<a href="' + clean_fname + r'".*?</li>',
        "", index_html, flags=re.DOTALL
    )
    index_html = re.sub(
        r'<div class="hero">.*?href="' + clean_fname + r'".*?</div>',
        "", index_html, flags=re.DOTALL
    )

# Also remove any float-formatted links (week-2.0.html, week-1.0.html) that remain
def fix_float_week(m):
    try:
        n = int(float(m.group(1)))
        return f'href="week-{n:02d}.html"'
    except Exception:
        return m.group(0)
index_html = re.sub(r'href="week-([\d.]+)\.html"', fix_float_week, index_html)

after_len = len(index_html)
print(f"  {before_len:,} → {after_len:,} bytes ({before_len - after_len:+,} chars removed)")

s3.put_object(
    Bucket=S3_BUCKET, Key="blog/index.html",
    Body=index_html.encode("utf-8"),
    ContentType="text/html", CacheControl="max-age=300",
)
print("  blog/index.html updated in S3")

# ── Step 5: invalidate CloudFront ─────────────────────────────────────────────
cf.create_invalidation(
    DistributionId=CF_DIST,
    InvalidationBatch={
        "Paths": {"Quantity": 1, "Items": ["/index.html"]},
        "CallerReference": "remove-leveled-up-record",
    },
)
print("  CloudFront invalidation created for /index.html")
print("\nDone.")
