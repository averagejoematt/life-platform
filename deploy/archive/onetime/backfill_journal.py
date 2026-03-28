#!/usr/bin/env python3
"""
backfill_journal.py — Convert existing blog/week-*.html posts to
Signal-themed site/journal/posts/week-{nn}/index.html format.

Run from: /Users/matthewwalker/Documents/Claude/life-platform
Requires: aws CLI configured, blog posts already in s3://matthew-life-platform/blog/

What it does:
  1. Downloads each week-XX.html from S3
  2. Extracts title, stats, body HTML
  3. Wraps in Signal journal post template (amber skin, Lora serif)
  4. Uploads to s3://matthew-life-platform/site/journal/posts/week-XX/index.html
  5. Writes site/journal/posts.json manifest
  6. Uploads posts.json to S3
"""
import subprocess, sys, os, json, re
from html.parser import HTMLParser
from datetime import datetime, timezone

BUCKET = "matthew-life-platform"
REGION = "us-west-2"

# ── Post metadata (from the HTML files we read) ───────────────────────────────
# week-01 is a stub (body just says 'See S3: blog/week-00.html') — excluded intentionally.
# The prologue (week-00) and weeks 2-3 are the real content.
POSTS = [
    {
        "week": 0,
        "slug": "week-00",
        "title": "Before the Numbers",
        "date": "2026-02-22",
        "date_display": "February 22, 2026",
        "stats_line": "Prologue · February 2026 · Seattle, WA",
        "has_board": False,
    },
    {
        "week": 2,
        "slug": "week-02",
        "title": "The Empty Journal",
        "date": "2026-03-03",
        "date_display": "March 3, 2026",
        "stats_line": "Week 2 · February 25 – March 3, 2026 · Seattle, WA",
        "has_board": False,
    },
    {
        "week": 3,
        "slug": "week-03",
        "title": "The DoorDash Chronicle",
        "date": "2026-03-11",
        "date_display": "March 11, 2026",
        "stats_line": "Weight: tracking paused · Grade: sick days logged",
        "has_board": False,
    },
]


# ── HTML body extractor ────────────────────────────────────────────────────────
class BodyExtractor(HTMLParser):
    """Extract the inner HTML of the <div class='body'> element."""
    def __init__(self):
        super().__init__()
        self.in_body = False
        self.depth = 0
        self.chunks = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if attrs_dict.get("class") == "body" and not self.in_body:
            self.in_body = True
            self.depth = 0
            return
        if self.in_body:
            self.depth += 1
            a = " ".join(f'{k}="{v}"' for k, v in attrs)
            self.chunks.append(f"<{tag}{(' ' + a) if a else ''}>")

    def handle_endtag(self, tag):
        if self.in_body:
            if self.depth == 0:
                self.in_body = False
            else:
                self.depth -= 1
                self.chunks.append(f"</{tag}>")

    def handle_data(self, data):
        if self.in_body:
            self.chunks.append(data)

    def handle_entityref(self, name):
        if self.in_body:
            self.chunks.append(f"&{name};")

    def handle_charref(self, name):
        if self.in_body:
            self.chunks.append(f"&#{name};")

    def result(self):
        return "".join(self.chunks).strip()


# ── Signal journal post template ──────────────────────────────────────────────
def build_post_html(title, stats_line, body_html, week_num, date_display, read_min):
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="description" content="{title} — Week {week_num} of The Measured Life by Elena Voss">
  <meta property="og:title" content="{title} — The Measured Life">
  <meta property="og:description" content="{stats_line}">
  <meta property="og:type" content="article">
  <title>{title} — The Measured Life</title>
  <link rel="icon" type="image/svg+xml" href="/assets/icons/favicon.svg">
  <link rel="icon" type="image/png" sizes="32x32" href="/assets/icons/favicon-32x32.png">
  <link rel="apple-touch-icon" sizes="180x180" href="/assets/icons/apple-touch-icon.png">
  <meta name="theme-color" content="#080c0a">
  <link rel="stylesheet" href="/assets/css/tokens.css">
  <link rel="stylesheet" href="/assets/css/base.css">
  <style>
    :root {{
      --accent: var(--c-amber-500);
      --accent-dim: var(--c-amber-300);
      --accent-bg: var(--c-amber-100);
      --accent-bg-subtle: var(--c-amber-050);
      --border: rgba(200,132,58,0.15);
    }}
    .reading-progress {{ position:fixed;top:var(--nav-height);left:0;right:0;height:2px;background:var(--border-subtle);z-index:var(--z-overlay); }}
    .reading-progress__fill {{ height:100%;background:var(--accent);width:0%;transition:width 0.1s linear; }}
    .post-header {{ padding:calc(var(--nav-height) + var(--space-16)) var(--page-padding) var(--space-10);border-bottom:1px solid var(--border);max-width:calc(var(--prose-width) + var(--page-padding) * 2);margin:0 auto; }}
    .post-header__series {{ font-size:var(--text-2xs);letter-spacing:var(--ls-tag);text-transform:uppercase;color:var(--accent-dim);margin-bottom:var(--space-3); }}
    .post-header__title {{ font-family:var(--font-serif);font-size:clamp(28px,4vw,46px);color:var(--text);line-height:1.15;font-weight:400;font-style:italic;margin-bottom:var(--space-5); }}
    .post-header__meta {{ display:flex;align-items:center;gap:var(--space-5);font-size:var(--text-xs);letter-spacing:var(--ls-tag);text-transform:uppercase;color:var(--text-muted); }}
    .post-header__stats {{ font-size:var(--text-xs);color:var(--text-faint);letter-spacing:var(--ls-tag);margin-top:var(--space-3); }}
    .post-body {{ max-width:calc(var(--prose-width) + var(--page-padding) * 2);margin:0 auto;padding:var(--space-10) var(--page-padding) var(--space-20); }}
    .prose {{ font-family:var(--font-serif); }}
    .prose p {{ font-size:18px;line-height:1.85;color:var(--text);margin-bottom:var(--space-6); }}
    .prose p:first-of-type::first-letter {{ font-size:64px;line-height:0.8;float:left;margin-right:var(--space-3);margin-top:8px;color:var(--accent);font-family:var(--font-serif); }}
    .prose blockquote {{ border-left:2px solid var(--accent);padding:var(--space-4) var(--space-6);background:var(--accent-bg-subtle);margin:var(--space-8) 0;font-style:italic;font-size:17px;color:var(--text);line-height:1.7; }}
    .prose hr {{ border:none;border-top:1px solid var(--border);margin:var(--space-10) 0; }}
    .prose .signature {{ text-align:center;font-size:14px;color:var(--text-muted);font-style:italic; }}
    .prose strong {{ color:var(--text);font-weight:700; }}
    .post-nav {{ max-width:calc(var(--prose-width) + var(--page-padding) * 2);margin:0 auto;padding:var(--space-6) var(--page-padding) var(--space-16);border-top:1px solid var(--border);display:flex;justify-content:space-between;gap:var(--space-6); }}
    .post-nav a {{ font-family:var(--font-serif);font-size:17px;color:var(--text);text-decoration:none;transition:color var(--dur-fast); }}
    .post-nav a:hover {{ color:var(--accent); }}
    .post-nav span {{ display:block;font-family:var(--font-mono);font-size:var(--text-2xs);letter-spacing:var(--ls-tag);text-transform:uppercase;color:var(--text-muted);margin-bottom:var(--space-1); }}
  </style>
</head>
<body>
<div class="reading-progress"><div class="reading-progress__fill" id="rp"></div></div>
<nav class="nav">
  <a href="/" class="nav__brand">AMJ</a>
  <div class="nav__links">
    <a href="/#experiment" class="nav__link">The experiment</a>
    <a href="/platform/" class="nav__link">The platform</a>
    <a href="/journal/" class="nav__link active">Journal</a>
    <a href="/character/" class="nav__link">Character</a>
  </div>
  <div class="nav__status"><div class="pulse" style="background:var(--accent)"></div><span>The Measured Life</span></div>
</nav>
<div class="post-header">
  <div class="post-header__series">The Measured Life &middot; Week {week_num} &middot; By Elena Voss</div>
  <h1 class="post-header__title">&ldquo;{title}&rdquo;</h1>
  <div class="post-header__meta">
    <span>{date_display}</span>
    <span>&middot;</span>
    <span>{read_min} min read</span>
  </div>
  <div class="post-header__stats">{stats_line}</div>
</div>
<article class="post-body">
  <div class="prose">
    {body_html}
  </div>
</article>
<div class="post-nav">
  <a href="/journal/"><span>&larr; All installments</span>The Measured Life archive</a>
  <a href="/"><span>The experiment</span>averagejoematt.com &rarr;</a>
</div>
<footer class="footer">
  <div class="footer__brand" style="color:var(--accent)">AMJ</div>
  <div class="footer__links">
    <a href="/" class="footer__link">Home</a>
    <a href="/character/" class="footer__link">Character</a>
  </div>
  <div class="footer__copy">// words when there's something worth saying</div>
</footer>
<script>
  const rp = document.getElementById('rp');
  window.addEventListener('scroll', () => {{
    const pct = window.scrollY / (document.body.scrollHeight - window.innerHeight) * 100;
    rp.style.width = Math.min(pct, 100) + '%';
  }});
</script>
</body>
</html>"""


def s3_download(key, local_path):
    result = subprocess.run(
        ["aws", "s3", "cp", f"s3://{BUCKET}/{key}", local_path, "--region", REGION],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(f"S3 download failed: {result.stderr}")


def s3_upload(local_path, key, content_type="text/html; charset=utf-8", cache="max-age=300"):
    result = subprocess.run([
        "aws", "s3", "cp", local_path, f"s3://{BUCKET}/{key}",
        "--region", REGION,
        "--content-type", content_type,
        "--cache-control", cache,
    ], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"S3 upload failed: {result.stderr}")


def s3_upload_body(body_bytes, key, content_type="text/html; charset=utf-8", cache="max-age=300"):
    """Upload bytes directly using stdin pipe."""
    tmp = f"/tmp/_amj_upload_{os.getpid()}.tmp"
    with open(tmp, "wb") as f:
        f.write(body_bytes)
    s3_upload(tmp, key, content_type, cache)
    os.unlink(tmp)


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    manifest_posts = []

    for post in POSTS:
        week = post["week"]
        slug = post["slug"]
        title = post["title"]
        date_display = post["date_display"]
        stats_line = post["stats_line"]
        date = post["date"]

        print(f"\n=== Week {week}: \"{title}\" ===")

        # Download from S3
        local_html = f"/tmp/amj_blog_{slug}.html"
        s3_key = f"blog/{slug}.html"
        print(f"  Downloading {s3_key}...")
        s3_download(s3_key, local_html)

        # Extract body HTML
        with open(local_html, encoding="utf-8", errors="replace") as f:
            raw = f.read()

        extractor = BodyExtractor()
        extractor.feed(raw)
        body_html = extractor.result()

        if not body_html:
            print(f"  ⚠️  Could not extract body — using placeholder")
            body_html = f"<p><em>Full content available at <a href='/blog/{slug}.html'>the original post</a>.</em></p>"

        word_count = len(re.sub(r'<[^>]+>', '', body_html).split())
        read_min = max(4, round(word_count / 250))
        print(f"  Body: {word_count} words, ~{read_min} min read")

        # Build Signal post HTML
        post_html = build_post_html(title, stats_line, body_html, week, date_display, read_min)

        # Upload to S3
        dest_key = f"site/journal/posts/{slug}/index.html"
        s3_upload_body(post_html.encode("utf-8"), dest_key)
        print(f"  ✅ Uploaded → {dest_key}")

        # Add to manifest
        manifest_posts.append({
            "week": week,
            "title": title,
            "date": date,
            "stats_line": stats_line,
            "url": f"/journal/posts/{slug}/",
            "excerpt": re.sub(r'<[^>]+>', '', body_html)[:300].strip(),
            "word_count": word_count,
            "has_board_interview": post["has_board"],
        })

    # Sort newest-first for the listing page
    manifest_posts.sort(key=lambda x: x["week"], reverse=True)

    # Upload posts.json manifest
    manifest = {
        "posts": manifest_posts,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    manifest_json = json.dumps(manifest, indent=2).encode("utf-8")
    s3_upload_body(manifest_json, "site/journal/posts.json",
                   content_type="application/json", cache="max-age=300")
    print(f"\n✅ posts.json manifest uploaded ({len(manifest_posts)} posts)")

    # Invalidate CloudFront
    print("\nInvalidating CloudFront...")
    result = subprocess.run([
        "aws", "cloudfront", "create-invalidation",
        "--distribution-id", "E3S424OXQZ8NBE",
        "--paths", "/journal/*",
        "--region", "us-east-1",
    ], capture_output=True, text=True)
    if result.returncode == 0:
        print("✅ CloudFront invalidation created")
    else:
        print(f"⚠️  Invalidation failed: {result.stderr}")

    print("\n✅ Backfill complete. Visit https://averagejoematt.com/journal/ to verify.")


if __name__ == "__main__":
    main()
