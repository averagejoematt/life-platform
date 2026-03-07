#!/usr/bin/env python3
"""
rebuild_blog_index.py — Rebuild blog/index.html from scratch based on known S3 files.

Posts (verified in S3):
  week-00.html  "Before the Numbers"   Feb 28, 2026  (Prologue)
  week-02.html  "The Empty Journal"    March 3, 2026  (Week 2)

week-01.html is "Before the Numbers" stub (1020 bytes) — kept in S3 but NOT linked.
"""

import boto3

REGION    = "us-west-2"
S3_BUCKET = "matthew-life-platform"
CF_DIST   = "E1JOC1V6E6DDYI"

s3 = boto3.client("s3", region_name=REGION)
cf = boto3.client("cloudfront", region_name=REGION)

hero_html = '''<div class="hero">
      <div class="kicker">Week 2 &middot; March 3, 2026</div>
      <h2><a href="week-02.html">"The Empty Journal"</a></h2>
      <a href="week-02.html" class="read-link">Read week 2 &rarr;</a>
    </div>'''

entries_html = '''<li>
          <a href="week-02.html">"The Empty Journal" <span class="label">Week 2</span></a>
          <span class="date">March 3, 2026</span>
        </li>
        <li>
          <a href="week-00.html">"Before the Numbers" <span class="label">Prologue</span></a>
          <span class="date">February 28, 2026</span>
        </li>'''

index_html = f'''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>The Measured Life &mdash; by Elena Voss</title>
  <link rel="stylesheet" href="style.css">
  <style>
    .hero {{ padding: 48px 0 40px; border-bottom: 1px solid #e5e5e0; }}
    .hero .kicker {{ font-family: -apple-system, sans-serif; font-size: 11px; letter-spacing: 2px; text-transform: uppercase; color: #999; margin-bottom: 16px; }}
    .hero h2 {{ font-size: 32px; font-weight: 400; font-style: italic; color: #1a1a1a; line-height: 1.3; margin: 0 0 16px; }}
    .hero h2 a {{ color: inherit; text-decoration: none; }}
    .hero h2 a:hover {{ color: #444; }}
    .hero .read-link {{ font-family: -apple-system, sans-serif; font-size: 13px; color: #333; text-decoration: none; letter-spacing: 0.5px; border-bottom: 1px solid #ccc; padding-bottom: 2px; }}
    .hero .read-link:hover {{ color: #000; border-color: #333; }}
    .series-intro {{ padding: 32px 0; font-size: 16px; color: #777; line-height: 1.7; border-bottom: 1px solid #e5e5e0; }}
    .archive-section {{ padding: 28px 0 0; }}
    .archive-label {{ font-family: -apple-system, sans-serif; font-size: 11px; letter-spacing: 2px; text-transform: uppercase; color: #bbb; margin-bottom: 16px; }}
    .archive-list {{ list-style: none; padding: 0; }}
    .archive-list li {{ padding: 14px 0; border-bottom: 1px solid #f0f0ea; display: flex; justify-content: space-between; align-items: baseline; }}
    .archive-list li a {{ color: #333; text-decoration: none; font-size: 17px; }}
    .archive-list li a:hover {{ color: #000; }}
    .archive-list .date {{ font-family: -apple-system, sans-serif; font-size: 12px; color: #bbb; white-space: nowrap; margin-left: 16px; }}
    .archive-list .label {{ font-family: -apple-system, sans-serif; font-size: 11px; letter-spacing: 0.5px; color: #999; text-transform: uppercase; }}
  </style>
</head>
<body>
  <header>
    <span class="series-title">The Measured Life</span>
    <p class="byline">An ongoing chronicle by Elena Voss</p>
    <nav class="site-nav"><a href="index.html">Archive</a><a href="about.html">About</a></nav>
  </header>
  <main>
    {hero_html}
    <div class="series-intro">
      What happens when a 37-year-old tech executive decides to transform his health using a custom-built AI platform that tracks everything his body produces? "The Measured Life" is an ongoing chronicle following one man's attempt to change &mdash; tracked by 19 data sources, coached by artificial intelligence, and observed by a journalist who's seen it all. New installments every Wednesday.
    </div>
    <div class="archive-section">
      <div class="archive-label">All Installments</div>
      <ul class="archive-list">
        {entries_html}
      </ul>
    </div>
  </main>
  <footer>
    The Measured Life &middot; A chronicle by Elena Voss &middot; Est. 2026
  </footer>
</body>
</html>'''

s3.put_object(
    Bucket=S3_BUCKET, Key="blog/index.html",
    Body=index_html.encode("utf-8"),
    ContentType="text/html", CacheControl="max-age=300",
)
print("blog/index.html written to S3")

cf.create_invalidation(
    DistributionId=CF_DIST,
    InvalidationBatch={
        "Paths": {"Quantity": 1, "Items": ["/index.html"]},
        "CallerReference": "rebuild-index-clean",
    },
)
print("CloudFront invalidated")
print("\nIndex now shows:")
print("  Week 2  — The Empty Journal      → week-02.html")
print("  Prologue — Before the Numbers    → week-00.html")
