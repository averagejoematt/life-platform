#!/usr/bin/env python3
"""
remove_blog_post.py — Remove a blog post from S3 and update the index

Removes blog/week-01.html ("The Week Everything Leveled Up And Nothing Changed")
and scrubs all references to it from blog/index.html.
Also cleans up the corresponding DynamoDB chronicle record if it exists.

Usage: python3 patches/remove_blog_post.py
"""

import json
import re
import boto3
from decimal import Decimal

REGION    = "us-west-2"
S3_BUCKET = "matthew-life-platform"
TABLE     = "life-platform"
FILE_KEY  = "blog/week-01.html"
CF_DIST   = "E1JOC1V6E6DDYI"

s3  = boto3.client("s3", region_name=REGION)
ddb = boto3.resource("dynamodb", region_name=REGION)
cf  = boto3.client("cloudfront", region_name=REGION)

# ── Step 1: confirm the file and show its title ───────────────────────────────
print(f"Checking s3://{S3_BUCKET}/{FILE_KEY} ...")
try:
    resp = s3.get_object(Bucket=S3_BUCKET, Key=FILE_KEY)
    html = resp["Body"].read().decode("utf-8", errors="replace")
    title_match = re.search(r"<title>([^<]+)</title>", html)
    h2_match    = re.search(r"<h[12][^>]*>([^<]+)</h[12]>", html)
    print(f"  Title tag : {title_match.group(1) if title_match else '(not found)'}")
    print(f"  First h1/2: {h2_match.group(1) if h2_match else '(not found)'}")
    print(f"  Size      : {len(html):,} bytes")
except s3.exceptions.NoSuchKey:
    print("  File not found — nothing to delete.")
    exit(0)

confirm = input("\nDelete this file and remove from index? [y/N] ").strip().lower()
if confirm != "y":
    print("Aborted.")
    exit(0)

# ── Step 2: delete the S3 file ────────────────────────────────────────────────
s3.delete_object(Bucket=S3_BUCKET, Key=FILE_KEY)
print(f"\nDeleted s3://{S3_BUCKET}/{FILE_KEY}")

# ── Step 3: patch the index ───────────────────────────────────────────────────
print("Patching blog/index.html ...")
idx_resp = s3.get_object(Bucket=S3_BUCKET, Key="blog/index.html")
index_html = idx_resp["Body"].read().decode("utf-8")

before_len = len(index_html)

# Remove any <li> block containing week-01.html
index_html = re.sub(
    r'<li>\s*<a href="week-01\.html"[^<]*</a>[^<]*</li>\s*\n?',
    "",
    index_html,
    flags=re.DOTALL,
)
# Remove any hero/featured block linking to week-01.html
index_html = re.sub(
    r'<div class="hero">.*?href="week-01\.html".*?</div>',
    "",
    index_html,
    flags=re.DOTALL,
)
# Catch any remaining bare href references
index_html = re.sub(r'href="week-01\.html"[^>]*>[^<]*</a>', "", index_html)

after_len = len(index_html)
print(f"  Index: {before_len:,} → {after_len:,} bytes ({before_len - after_len:+,} chars removed)")

s3.put_object(
    Bucket=S3_BUCKET,
    Key="blog/index.html",
    Body=index_html.encode("utf-8"),
    ContentType="text/html",
    CacheControl="max-age=300",
)
print("  Updated blog/index.html written to S3")

# ── Step 4: invalidate CloudFront ─────────────────────────────────────────────
print("Invalidating CloudFront ...")
cf.create_invalidation(
    DistributionId=CF_DIST,
    InvalidationBatch={
        "Paths": {"Quantity": 2, "Items": ["/week-01.html", "/index.html"]},
        "CallerReference": "remove-week-01",
    },
)
print("  CloudFront invalidation created for /week-01.html and /index.html")

# ── Step 5: remove DynamoDB record if it exists ───────────────────────────────
print("Checking DynamoDB for chronicle record ...")
table = ddb.Table(TABLE)
# Chronicle records use sk=CHRONICLE#YYYY-MM-DD or similar — scan for week_number=1
resp = table.query(
    KeyConditionExpression="pk = :pk",
    ExpressionAttributeValues={":pk": "USER#matthew#SOURCE#chronicle"},
)
deleted_ddb = 0
for item in resp.get("Items", []):
    wn = item.get("week_number")
    title = item.get("title", "")
    if "Leveled Up" in title or "Nothing Changed" in title or (wn is not None and float(str(wn)) == 1.0):
        sk = item["sk"]
        print(f"  Deleting DDB record: sk={sk}, title={title!r}")
        table.delete_item(Key={"pk": "USER#matthew#SOURCE#chronicle", "sk": sk})
        deleted_ddb += 1

if deleted_ddb == 0:
    print("  No matching DynamoDB record found (may not have been stored, or already gone)")

print(f"\nDone. week-01.html removed from S3, index patched, {deleted_ddb} DDB record(s) deleted.")
