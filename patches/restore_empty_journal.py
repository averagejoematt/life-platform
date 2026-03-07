#!/usr/bin/env python3
"""
restore_empty_journal.py — Restore week-02.html (The Empty Journal) to blog/index.html

The remove_chronicle_record.py script incorrectly removed week-02.html from the
index because both chronicle records shared week_number=2. This script restores
the correct entry.
"""

import boto3

REGION    = "us-west-2"
S3_BUCKET = "matthew-life-platform"
CF_DIST   = "E1JOC1V6E6DDYI"

s3 = boto3.client("s3", region_name=REGION)
cf = boto3.client("cloudfront", region_name=REGION)

# Read current index
resp = s3.get_object(Bucket=S3_BUCKET, Key="blog/index.html")
html = resp["Body"].read().decode("utf-8")

# Verify week-02.html is missing
if 'week-02.html' in html:
    print("week-02.html already present in index — nothing to do.")
    exit(0)

# The archive list entry to restore
new_entry = '''<li>
          <a href="week-02.html">"The Empty Journal" <span class="label">Week 2</span></a>
          <span class="date">March 3, 2026</span>
        </li>'''

# Insert after the week-00.html entry in the archive list
if 'week-00.html' in html:
    html = html.replace(
        '<a href="week-00.html">',
        new_entry + '\n        <li>\n          <a href="week-00.html">',
        1
    )
    # Clean up the doubled <li> we just created
    html = html.replace(
        new_entry + '\n        <li>\n          <a href="week-00.html">',
        new_entry + '\n        <li>\n          <a href="week-00.html">',
        1
    )
else:
    # Fallback: append before </ul>
    html = html.replace('</ul>', new_entry + '\n        </ul>', 1)

# Also update the hero section if it's showing week-00 as latest
# (week-02 should be the featured/latest post)
if 'class="hero"' in html and 'week-02.html' not in html:
    # Replace hero to point to week-02
    import re
    html = re.sub(
        r'(<div class="hero">.*?href=")[^"]*(")',
        r'\g<1>week-02.html\g<2>',
        html, flags=re.DOTALL, count=1
    )
    html = re.sub(
        r'(Read ).*?( &rarr;)',
        r'\g<1>week 2\g<2>',
        html, count=1
    )

# Upload
s3.put_object(
    Bucket=S3_BUCKET, Key="blog/index.html",
    Body=html.encode("utf-8"),
    ContentType="text/html", CacheControl="max-age=300",
)
print("blog/index.html restored with week-02.html entry")

# Invalidate CloudFront
cf.create_invalidation(
    DistributionId=CF_DIST,
    InvalidationBatch={
        "Paths": {"Quantity": 1, "Items": ["/index.html"]},
        "CallerReference": "restore-empty-journal",
    },
)
print("CloudFront invalidated — /index.html")
print("Done. The Empty Journal is back.")
