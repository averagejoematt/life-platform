#!/usr/bin/env python3
"""Publish the (hand-edited) Week 1 chronicle draft + rebuild posts.json with the prologue.

The normal approve path replays PRE-BUILT artifacts stored on the draft — but those predate
the two hand-edits and would also overwrite the prologue posts.json. So we render Week 1 fresh
from the edited content_html, keep Prologue I/II, mark the draft published, and invalidate.
"""
import boto3, json, re, html as _h
from datetime import datetime, timezone

S3, BUCKET = boto3.client("s3", region_name="us-west-2"), "matthew-life-platform"
CF = boto3.client("cloudfront")
TBL = boto3.resource("dynamodb", region_name="us-west-2").Table("life-platform")
PK = "USER#matthew#SOURCE#chronicle"
DIST = "E3S424OXQZ8NBE"

TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="description" content="@@TITLE@@ — @@LABEL@@ of The Measured Life by Elena Voss">
  <meta property="og:title" content="@@TITLE@@ — The Measured Life">
  <meta property="og:description" content="@@STATS@@">
  <meta property="og:type" content="article">
  <title>@@TITLE@@ — The Measured Life</title>
  <link rel="stylesheet" href="/assets/css/tokens.css">
  <link rel="stylesheet" href="/assets/css/base.css">
  <style>
    :root { --accent: var(--c-amber-500); --accent-dim: var(--c-amber-300); --accent-bg: var(--c-amber-100); --accent-bg-subtle: var(--c-amber-050); --border: rgba(200,132,58,0.15); }
    .reading-progress { position:fixed;top:var(--nav-height);left:0;right:0;height:2px;background:var(--border-subtle);z-index:var(--z-overlay); }
    .reading-progress__fill { height:100%;background:var(--accent);width:0%;transition:width 0.1s linear; }
    .post-header { padding:calc(var(--nav-height) + var(--space-16)) var(--page-padding) var(--space-10);border-bottom:1px solid var(--border);max-width:calc(var(--prose-width) + var(--page-padding) * 2);margin:0 auto; }
    .post-header__series { font-size:var(--text-2xs);letter-spacing:var(--ls-tag);text-transform:uppercase;color:var(--accent-dim);margin-bottom:var(--space-3); }
    .post-header__title { font-family:var(--font-serif);font-size:clamp(28px,4vw,46px);color:var(--text);line-height:1.15;font-weight:400;font-style:italic;margin-bottom:var(--space-5); }
    .post-header__meta { display:flex;align-items:center;gap:var(--space-5);font-size:var(--text-xs);letter-spacing:var(--ls-tag);text-transform:uppercase;color:var(--text-muted); }
    .post-header__stats { font-size:var(--text-xs);color:var(--text-faint);letter-spacing:var(--ls-tag);margin-top:var(--space-3); }
    .post-body { max-width:calc(var(--prose-width) + var(--page-padding) * 2);margin:0 auto;padding:var(--space-10) var(--page-padding) var(--space-20); }
    .prose { font-family:var(--font-serif); }
    .prose p { font-size:18px;line-height:1.85;color:var(--text);margin-bottom:var(--space-6); }
    .prose p:first-child::first-letter { font-size:64px;line-height:0.8;float:left;margin-right:var(--space-3);margin-top:8px;color:var(--accent);font-family:var(--font-serif); }
    .prose blockquote { border-left:2px solid var(--accent);padding:var(--space-4) var(--space-6);background:var(--accent-bg-subtle);margin:var(--space-8) 0;font-style:italic;font-size:17px;color:var(--text);line-height:1.7; }
    .prose hr { border:none;border-top:1px solid var(--border);margin:var(--space-10) 0; }
    .prose strong { color:var(--text);font-weight:700; }
    .post-nav { max-width:calc(var(--prose-width) + var(--page-padding) * 2);margin:0 auto;padding:var(--space-6) var(--page-padding) var(--space-16);border-top:1px solid var(--border);display:flex;justify-content:space-between;gap:var(--space-6); }
    .post-nav a { font-family:var(--font-serif);font-size:17px;color:var(--text);text-decoration:none;transition:color var(--dur-fast); }
    .post-nav a:hover { color:var(--accent); }
    .post-nav span { display:block;font-family:var(--font-mono);font-size:var(--text-2xs);letter-spacing:var(--ls-tag);text-transform:uppercase;color:var(--text-muted);margin-bottom:var(--space-1); }
  </style>
</head>
<body>
<div class="reading-progress"><div class="reading-progress__fill" id="rp"></div></div>
<nav class="nav">
  <a href="/" class="nav__brand">AMJ</a>
  <div class="nav__links">
    <a href="/story/" class="nav__link active">The story</a>
    <a href="/now/" class="nav__link">The cockpit</a>
    <a href="/coaching/" class="nav__link">The coaching</a>
    <a href="/evidence/" class="nav__link">The evidence</a>
  </div>
  <div class="nav__status"><div class="pulse" style="background:var(--accent)"></div><span>The Measured Life</span></div>
</nav>
<div class="post-header">
  <div class="post-header__series">The Measured Life &middot; @@LABEL@@ &middot; By Elena Voss</div>
  <h1 class="post-header__title">&ldquo;@@TITLE@@&rdquo;</h1>
  <div class="post-header__meta">
    <span>@@DATE@@</span>
    <span>&middot;</span>
    <span>@@READMIN@@ min read</span>
  </div>
  <div class="post-header__stats">@@STATS@@</div>
</div>
<article class="post-body">
  <div class="prose">
@@BODY@@
  </div>
</article>
<div class="post-nav">
  <a href="/story/"><span>&larr; All installments</span>The Measured Life archive</a>
  <a href="/now/"><span>The cockpit</span>Today's live data &rarr;</a>
</div>
<footer class="footer">
  <div class="footer__brand" style="color:var(--accent)">AMJ</div>
  <div class="footer__copy">// words when there's something worth saying</div>
</footer>
<script>
  const rp = document.getElementById('rp');
  window.addEventListener('scroll', () => { const pct = window.scrollY / (document.body.scrollHeight - window.innerHeight) * 100; rp.style.width = Math.min(pct, 100) + '%'; });
</script>
</body>
</html>"""

it = TBL.get_item(Key={"pk": PK, "sk": "DATE#2026-06-20"}).get("Item", {})
title = it.get("title", "")
body_html = it.get("content_html", "")
md = it.get("content_markdown", "")
# stats line is the [Weight ...] bracket line in the markdown (not part of the HTML body)
mstat = re.search(r"\[([^\]]*Weight[^\]]*)\]", md)
stats = mstat.group(1).strip() if mstat else ""
# excerpt: first prose after the title/stat lines
prose = re.sub(r'^".*?"\s*', "", md, count=1).strip()
prose = re.sub(r"^\[[^\]]*\]\s*", "", prose).strip()
excerpt = prose[:300].strip()
wc = len(prose.split())
read_min = max(4, round(wc / 250))

page = TEMPLATE
for k, v in {
    "@@TITLE@@": _h.escape(title), "@@LABEL@@": "Week 1", "@@STATS@@": _h.escape(stats),
    "@@DATE@@": "June 20, 2026", "@@READMIN@@": str(read_min), "@@BODY@@": body_html,
}.items():
    page = page.replace(k, v)

S3.put_object(Bucket=BUCKET, Key="generated/journal/posts/week-03/index.html",
              Body=page.encode(), ContentType="text/html; charset=utf-8", CacheControl="max-age=300")
print(f"  wrote generated/journal/posts/week-03/index.html  (Week 1, {wc} words)")

# rebuild posts.json: Week 1 + the two prologue parts, newest first
posts = [
    {"week": 1, "label": "Week 1", "title": title, "date": "2026-06-20", "stats_line": stats,
     "url": "/journal/posts/week-03/", "excerpt": excerpt, "word_count": wc, "has_board_interview": True},
    {"week": 2, "label": "Prologue · Part II", "title": "The Empty Journal", "date": "2026-06-11", "stats_line": "",
     "url": "/journal/posts/week-02/", "excerpt": "", "word_count": 1370, "has_board_interview": False},
    {"week": 1, "label": "Prologue · Part I", "title": "The Body Votes First", "date": "2026-06-07", "stats_line": "",
     "url": "/journal/posts/week-01/", "excerpt": "", "word_count": 1391, "has_board_interview": False},
]
# preserve the prologue excerpts already in the live manifest
live = json.loads(S3.get_object(Bucket=BUCKET, Key="generated/journal/posts.json")["Body"].read())
ex = {p["url"]: p.get("excerpt", "") for p in live.get("posts", [])}
for p in posts:
    if not p["excerpt"]:
        p["excerpt"] = ex.get(p["url"], "")
S3.put_object(Bucket=BUCKET, Key="generated/journal/posts.json",
              Body=json.dumps({"posts": posts, "updated_at": datetime.now(timezone.utc).isoformat()}, indent=2).encode(),
              ContentType="application/json", CacheControl="max-age=300")
print("  wrote generated/journal/posts.json (Week 1 + Prologue I/II)")

# mark draft published
TBL.update_item(
    Key={"pk": PK, "sk": "DATE#2026-06-20"},
    UpdateExpression="SET #s=:p, phase=:e, approved_at=:n REMOVE approval_token, draft_blog_post_html, draft_blog_index_html",
    ExpressionAttributeNames={"#s": "status"},
    ExpressionAttributeValues={":p": "published", ":e": "experiment", ":n": datetime.now(timezone.utc).isoformat()},
)
print("  DDB DATE#2026-06-20 -> status=published, phase=experiment")

inv = CF.create_invalidation(DistributionId=DIST, InvalidationBatch={
    "Paths": {"Quantity": 4, "Items": ["/journal/posts/week-03/*", "/journal/posts.json", "/journal/*", "/story/*"]},
    "CallerReference": f"week1-publish-{datetime.now(timezone.utc).isoformat()}"})
print("  CloudFront invalidation:", inv["Invalidation"]["Id"], inv["Invalidation"]["Status"])
print("DONE")
