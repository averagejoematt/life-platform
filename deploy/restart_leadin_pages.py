#!/usr/bin/env python3
"""restart_leadin_pages.py — rebuild the public journal pages + manifest for resurrected
pre-genesis chronicle lead-ins after an experiment reset.

WHY: the reset pipeline archives every generated/journal/posts/week-NN/ page and
tombstones generated/journal/posts.json, then restart_chronicle_handler resurrects the
kept chronicle installments as re-dated pre-genesis lead-ins (phase=experiment, no
tombstone) — but nothing regenerates their PUBLIC pages, so the story hub's chronicle
feed (/journal/posts.json) serves a tombstone marker and the article URLs 404/leak
tombstone JSON until the first post-genesis Wednesday publish. This script closes that
gap deterministically from the DDB records.

PIPELINE POSITION (wired 2026-07-11, pre-launch content calendar): runs in
deploy/restart_pipeline.py AFTER restart_chronicle_handler (which resurrects +
re-dates the PRELAUNCH_CALENDAR chronicle lead-ins) and AFTER restart_media_reset
(which resurrects the calendar's podcast prequel) — order: chronicle → media →
leadin pages — so the pages it renders reflect the fully re-dated arc. It covers
ALL visible (phase=experiment, non-tombstoned) chronicle records: with 3 lead-ins
it writes week-01/02/03 in date order, and the next real Wednesday publish
(wednesday_chronicle_lambda._seq_for indexes the same date-sorted list) continues
at week-04. Standalone use:

    python3 deploy/restart_leadin_pages.py            # dry-run (default): print the plan
    python3 deploy/restart_leadin_pages.py --apply    # write S3 + CloudFront invalidation

RENDER PARITY: the article template, series-label / sequential-URL logic
(week-{seq:02d}, "Prologue · Part N" for pre-genesis dates), manifest schema, and
Content-Type/CacheControl are ported from publish_to_journal() in
lambdas/emails/wednesday_chronicle_lambda.py (~lines 1550-1855) so the next real
Wednesday publish re-derives the SAME urls/labels for these installments (its _seq_for
indexes the date-sorted installment list) and simply extends the manifest.
Editorial images are intentionally OFF here (the no-image path) — the next live
publish carries images forward only for posts that have them.

WRITE SURFACE: S3 keys under generated/journal/ only. No DynamoDB writes, no deploys.
Idempotent: re-running regenerates byte-identical pages (manifest updated_at aside).
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import boto3

# Import the genesis anchor from the same generated constants the lambdas use.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lambdas"))
from constants import EXPERIMENT_PHASE_CURRENT, EXPERIMENT_START_DATE  # noqa: E402

REGION = "us-west-2"
TABLE_NAME = "life-platform"
S3_BUCKET = "matthew-life-platform"
USER_ID = "matthew"
CLOUDFRONT_DISTRIBUTION_ID = "E3S424OXQZ8NBE"  # averagejoematt.com

MANIFEST_KEY = "generated/journal/posts.json"

_ROMAN = {1: "I", 2: "II", 3: "III", 4: "IV", 5: "V", 6: "VI", 7: "VII", 8: "VIII"}


# ──────────────────────────────────────────────────────────────────────────────
# DDB — visible chronicle installments (phase=experiment, not tombstoned)
# ──────────────────────────────────────────────────────────────────────────────


def fetch_visible_installments(table):
    """All non-tombstoned phase-experiment DATE# chronicle records, oldest-first by date."""
    resp = table.query(
        KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
        FilterExpression="#phase = :phase AND attribute_not_exists(tombstone)",
        ExpressionAttributeNames={"#phase": "phase"},
        ExpressionAttributeValues={
            ":pk": f"USER#{USER_ID}#SOURCE#chronicle",
            ":prefix": "DATE#",
            ":phase": EXPERIMENT_PHASE_CURRENT,
        },
    )
    items = resp.get("Items", [])
    while "LastEvaluatedKey" in resp:
        resp = table.query(
            KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
            FilterExpression="#phase = :phase AND attribute_not_exists(tombstone)",
            ExpressionAttributeNames={"#phase": "phase"},
            ExpressionAttributeValues={
                ":pk": f"USER#{USER_ID}#SOURCE#chronicle",
                ":prefix": "DATE#",
                ":phase": EXPERIMENT_PHASE_CURRENT,
            },
            ExclusiveStartKey=resp["LastEvaluatedKey"],
        )
        items.extend(resp.get("Items", []))
    return sorted(items, key=lambda x: x.get("date", ""))


# ──────────────────────────────────────────────────────────────────────────────
# Body derivation — the stored content already carries the h1/byline header the
# page chrome replaces (the live path strips it via parse_installment before render)
# ──────────────────────────────────────────────────────────────────────────────


def body_html_from_record(item):
    """Prose-only body HTML: upleveled content_html minus the leading h1/byline/hr header."""
    html = (item.get("content_html") or "").strip()
    if html:
        return re.sub(
            r'^\s*<h1>.*?</h1>\s*(?:<p class="byline">.*?</p>\s*)?(?:<hr\s*/?>\s*)?',
            "",
            html,
            count=1,
            flags=re.DOTALL,
        ).strip()
    return markdown_to_html(body_markdown_from_record(item))


def body_markdown_from_record(item):
    """Prose-only markdown (for excerpts): strip either stored header format —
    old assembled ('# heading' + '*By …*' byline + '---') or raw installment
    ('"Title"' line + '[stats]' line)."""
    lines = (item.get("content_markdown") or "").strip().split("\n")
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i < len(lines):
        first = lines[i].strip()
        if first.startswith("# ") or (first.startswith('"') and first.endswith('"')):
            i += 1
    while i < len(lines):
        s = lines[i].strip()
        if not s:
            i += 1
        elif s.startswith("*By ") or s.startswith("[") or s == "---":
            i += 1
        else:
            break
    return "\n".join(lines[i:]).strip()


def markdown_to_html(md_text):
    """Fallback markdown→HTML — ported verbatim from wednesday_chronicle_lambda.markdown_to_html."""
    lines = md_text.strip().split("\n")
    html_parts = []
    in_blockquote = False
    bq_buffer = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("> "):
            if not in_blockquote:
                in_blockquote = True
                bq_buffer = []
            bq_buffer.append(stripped[2:])
            continue
        elif in_blockquote:
            bq_text = " ".join(bq_buffer)
            bq_text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", bq_text)
            bq_text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", bq_text)
            html_parts.append(f"<blockquote>{bq_text}</blockquote>")
            in_blockquote = False
            bq_buffer = []
        if stripped == "---":
            html_parts.append("<hr>")
            continue
        if not stripped:
            continue
        if stripped.startswith("*") and stripped.endswith("*") and not stripped.startswith("**"):
            html_parts.append(f'<p class="signature"><em>{stripped[1:-1]}</em></p>')
            continue
        text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", stripped)
        text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
        html_parts.append(f"<p>{text}</p>")

    if in_blockquote and bq_buffer:
        bq_text = " ".join(bq_buffer)
        bq_text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", bq_text)
        bq_text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", bq_text)
        html_parts.append(f"<blockquote>{bq_text}</blockquote>")

    return "\n".join(html_parts)


# ──────────────────────────────────────────────────────────────────────────────
# Series label + sequential URL — the SAME closures publish_to_journal() uses,
# so the next live publish re-derives identical urls/labels for these posts
# ──────────────────────────────────────────────────────────────────────────────


def series_label(date_str, all_dates, week_num):
    genesis = EXPERIMENT_START_DATE
    pre = [d for d in all_dates if d < genesis]
    if not date_str:
        return f"Week {int(week_num)}"
    if date_str < genesis:
        n = pre.index(date_str) + 1 if date_str in pre else 1
        return f"Prologue · Part {_ROMAN.get(n, n)}"
    try:
        wk = max(1, ((datetime.strptime(date_str, "%Y-%m-%d").date() - datetime.strptime(genesis, "%Y-%m-%d").date()).days // 7) + 1)
    except Exception:
        wk = int(week_num)
    return f"Week {wk}"


def seq_for(date_str, all_dates, week_num):
    return (all_dates.index(date_str) + 1) if date_str in all_dates else int(week_num)


_WEEK_SEG_RE = re.compile(r"(?i)^week\s+\d+\b")
_PROLOGUE_HINT_RE = re.compile(r"(?i)prologue|before day 1")


def display_stats_line(stats_line, date_str):
    """The reader-facing dek, reframed for pre-genesis lead-ins (#949).

    The stored stats_line was authored mid-experiment ("… | Week 1 of The Measured
    Life"), which contradicts the countdown banner sitting right above it on the
    story hub ("the experiment begins tomorrow" vs "Week 1" three lines later).
    For a pre-genesis date: drop any "Week N …" segment and stamp the prologue
    framing instead. Post-genesis installments pass through untouched, and the
    DDB record is never modified — this reframes only the rendered surfaces.
    """
    line = str(stats_line or "")
    if not date_str or date_str >= EXPERIMENT_START_DATE:
        return line
    parts = [p.strip() for p in line.split("|") if p.strip()]
    kept = [p for p in parts if not _WEEK_SEG_RE.match(p)]
    if not any(_PROLOGUE_HINT_RE.search(p) for p in kept):
        kept.append("Prologue — the instrumented weeks before Day 1")
    return " | ".join(kept)


# ──────────────────────────────────────────────────────────────────────────────
# Article page — the v5 template ported from publish_to_journal() (no-image path)
# ──────────────────────────────────────────────────────────────────────────────


def render_post_html(title, stats_line, body_html, cur_label, date_str, seq):
    try:
        date_display = datetime.strptime(date_str, "%Y-%m-%d").strftime("%B %-d, %Y")
    except Exception:
        date_display = date_str
    word_count = len(body_html.split())
    read_min = max(4, round(word_count / 250))
    # No editorial image for resurrected lead-ins (the no-image path): default OG card.
    og_image = "https://averagejoematt.com/assets/images/og-home.png"
    canonical_url = CANONICAL_URL_FMT.format(seq=seq)
    # JSON-LD datePublished uses the record's (pre-genesis) date, not the run date —
    # truthful for a lead-in and keeps re-runs byte-identical.
    return f"""<!DOCTYPE html>
<html lang="en" data-door="story">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
  <title>{title} — The Measured Life</title>
  <meta name="description" content="{title} — {cur_label} of The Measured Life by Elena Voss">
  <link rel="canonical" href="{canonical_url}">
  <meta property="og:type" content="article">
  <meta property="og:site_name" content="averagejoematt">
  <meta property="og:url" content="{canonical_url}">
  <meta property="og:title" content="{title} — The Measured Life">
  <meta property="og:description" content="{stats_line}">
  <meta property="og:image" content="{og_image}">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="{title} — The Measured Life">
  <meta name="twitter:description" content="{stats_line}">
  <meta name="twitter:image" content="{og_image}">
  <meta name="theme-color" media="(prefers-color-scheme: light)" content="#F4EFE4">
  <meta name="theme-color" media="(prefers-color-scheme: dark)" content="#0E0C08">
  <link rel="icon" href="/favicon.ico">
  <link rel="manifest" href="/manifest.webmanifest">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-title" content="Measured Life">
  <link rel="apple-touch-icon" href="/apple-touch-icon.png">
  <link rel="alternate" type="application/rss+xml" title="averagejoematt" href="/rss.xml">
  <script type="application/ld+json">
  {{
    "@context": "https://schema.org",
    "@type": "BlogPosting",
    "headline": "{title}",
    "description": "{cur_label} of The Measured Life by Elena Voss",
    "datePublished": "{date_str}",
    "author": {{"@type": "Person", "name": "Elena Voss"}},
    "image": "{og_image}",
    "publisher": {{
      "@type": "Organization",
      "name": "The Measured Life",
      "url": "https://averagejoematt.com",
      "logo": {{"@type": "ImageObject", "url": "https://averagejoematt.com/apple-touch-icon.png"}}
    }},
    "mainEntityOfPage": {{"@type": "WebPage", "@id": "{canonical_url}"}},
    "articleSection": "Health Transformation",
    "isPartOf": {{"@type": "Blog", "name": "The Measured Life", "url": "https://averagejoematt.com/story/chronicle/"}}
  }}
  </script>
  <link rel="stylesheet" href="/assets/css/fonts.css">
  <link rel="stylesheet" href="/assets/css/tokens.css">
  <link rel="stylesheet" href="/assets/css/story.css">
  <script>(function(){{try{{var t=localStorage.getItem("ajm-theme");if(t==="light"||t==="dark")document.documentElement.dataset.theme=t;}}catch(e){{}}}})();</script>
  <style>
    .reading-progress {{ position:fixed;top:0;left:0;right:0;height:2px;background:transparent;z-index:var(--z-overlay); }}
    .reading-progress__fill {{ height:100%;background:var(--ember);width:0%;transition:width 0.1s linear; }}
    .post-wrap {{ max-width:var(--container-read);margin:0 auto;padding-inline:var(--gutter); }}
    .post-header {{ padding:var(--sp-8) 0 var(--sp-6);border-bottom:var(--border-hair); }}
    .post-header__art {{ margin:0 0 var(--sp-5);border-radius:var(--radius);overflow:hidden;position:relative;aspect-ratio:21/9;background:#16130E; }}
    .post-header__art img {{ width:100%;height:100%;object-fit:cover;filter:saturate(.62) contrast(1.03); }}
    .post-header__art figcaption {{ position:absolute;right:8px;bottom:6px;font:11px/1.4 var(--font-mono);color:#e7dccb;background:rgba(0,0,0,.5);padding:2px 7px;border-radius:var(--radius-xs); }}
    .post-header__series {{ font-family:var(--font-mono);font-size:var(--fs-label);letter-spacing:var(--tracking-label);text-transform:uppercase;color:var(--ember);margin-bottom:var(--sp-3); }}
    .post-header__title {{ font-family:var(--font-serif);font-size:var(--fs-h1);color:var(--ink);line-height:var(--lh-snug);font-weight:var(--weight-reg);font-style:italic;margin-bottom:var(--sp-4); }}
    .post-header__meta {{ display:flex;align-items:center;gap:var(--sp-3);font-family:var(--font-mono);font-size:var(--fs-label);letter-spacing:var(--tracking-label);text-transform:uppercase;color:var(--ink-muted); }}
    .post-header__stats {{ font-family:var(--font-mono);font-size:var(--fs-label);color:var(--ink-faint);letter-spacing:var(--tracking-label);margin-top:var(--sp-2); }}
    .post-body {{ padding:var(--sp-7) 0 var(--sp-8); }}
    .post-body .prose {{ font-family:var(--font-serif);max-width:none; }}
    .post-body .prose p {{ max-width:none;line-height:var(--lh-relaxed); }}
    .post-body .prose > p:first-of-type::first-letter {{ font-size:64px;line-height:0.8;float:left;margin-right:var(--sp-2);margin-top:6px;color:var(--ember);font-family:var(--font-serif); }}
    .post-body .prose blockquote {{ border-left:2px solid var(--ember);padding:var(--sp-3) var(--sp-5);background:var(--ember-wash);margin:var(--sp-6) 0;font-style:italic;color:var(--ink); }}
    .post-body .prose hr {{ border:none;border-top:var(--border-hair);margin:var(--sp-7) 0; }}
    .post-body .prose .signature {{ text-align:center;font-size:var(--fs-small);color:var(--ink-muted);font-style:italic; }}
    .post-body .prose strong {{ color:var(--ink);font-weight:var(--weight-med); }}
    .post-cta {{ margin:var(--sp-6) 0 var(--sp-7);padding:var(--sp-6);border:var(--border-hair);border-radius:var(--radius);background:var(--ember-wash);text-align:center; }}
    .post-cta h2 {{ font-family:var(--font-serif);font-style:italic;font-weight:var(--weight-reg);font-size:var(--fs-h3);color:var(--ink);margin:0 0 var(--sp-2); }}
    .post-cta p {{ color:var(--ink-muted);font-size:var(--fs-small);margin:0 auto var(--sp-4);max-width:44ch; }}
    .post-cta a.cta-btn {{ display:inline-block;font-family:var(--font-mono);font-size:var(--fs-label);letter-spacing:var(--tracking-label);text-transform:uppercase;color:var(--page);background:var(--ember);padding:10px 20px;border-radius:var(--radius-sm);text-decoration:none; }}
    .post-cta a.cta-btn:hover {{ filter:brightness(1.08); }}
    .post-nav {{ padding:var(--sp-5) 0 var(--sp-8);border-top:var(--border-hair);display:flex;justify-content:space-between;gap:var(--sp-5); }}
    .post-nav a {{ font-family:var(--font-serif);font-size:var(--fs-body);color:var(--ink);text-decoration:none;transition:color var(--dur-fast); }}
    .post-nav a:hover {{ color:var(--ember); }}
    .post-nav span {{ display:block;font-family:var(--font-mono);font-size:var(--fs-label);letter-spacing:var(--tracking-label);text-transform:uppercase;color:var(--ink-faint);margin-bottom:var(--sp-1); }}
  </style>
</head>
<body class="dx-page">
<a class="skip" href="#post">Skip to the story</a>
<div class="reading-progress"><div class="reading-progress__fill" id="rp"></div></div>
<header class="story-top">
  <a class="brand" href="/"><span class="brand-mark" aria-hidden="true"></span><span class="brand-name">averagejoematt</span> <span class="brand-door label">the story</span></a>
  <nav class="doors" aria-label="Doors">
    <a href="/now/" title="Today's live instrument — your daily numbers, read back to you"><svg class="ico ico-door" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><use href="/assets/icons/icons.svg#i-door-cockpit"></use></svg>the cockpit</a>
    <a href="/data/" title="Every source the platform reads — trends now and over time"><svg class="ico ico-door" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><use href="/assets/icons/icons.svg#i-door-data"></use></svg>the data</a>
    <a href="/coaching/" title="The AI team &amp; their arguments — stances, track records, disagreements"><svg class="ico ico-door" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><use href="/assets/icons/icons.svg#i-door-coaching"></use></svg>the coaching</a>
    <a href="/protocols/" title="The levers — supplements, experiments, challenges, discoveries"><svg class="ico ico-door" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><use href="/assets/icons/icons.svg#i-door-protocols"></use></svg>the protocols</a>
    <a href="/story/" aria-current="page" title="The writing &amp; the why — chronicle, journal, timeline, about"><svg class="ico ico-door" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><use href="/assets/icons/icons.svg#i-door-story"></use></svg>the story</a>
    <button class="theme-toggle" type="button" aria-label="Toggle light and dark"><span class="theme-dot" aria-hidden="true"></span></button>
  </nav>
</header>
<main id="post">
<div class="post-wrap">
  <div class="post-header">

    <div class="post-header__series">The Measured Life &middot; {cur_label} &middot; By Elena Voss</div>
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
  <aside class="post-cta">
    <h2>Follow the experiment</h2>
    <p>A new installment every week — the data, the coaches, and what actually moved. No spam, unsubscribe anytime.</p>
    <a class="cta-btn" href="/subscribe/">Follow by email</a>
  </aside>
  <nav class="post-nav">
    <a href="/story/chronicle/"><span>&larr; All installments</span>The Measured Life archive</a>
    <a href="/now/"><span>Today</span>The live cockpit &rarr;</a>
  </nav>
</div>
</main>
<footer class="site-foot">
  <nav class="site-foot-cols" aria-label="Site map">
    <div class="sf-col"><p class="sf-h label">The Story</p>
      <a href="/story/chronicle/">Chronicle</a><a href="/story/panel/">Podcast</a><a href="/story/journal/">In my own words</a><a href="/story/timeline/">Timeline</a><a href="/story/about/">About</a></div>
    <div class="sf-col"><p class="sf-h label">The Coaching</p>
      <a href="/coaching/">The Team</a><a href="/coaching/lab-notes/">AI lab notes</a></div>
    <div class="sf-col"><p class="sf-h label">The Data</p>
      <a href="/data/">All topics</a><a href="/method/ask/">Ask the data</a><a href="/data/labs/">Labs</a><a href="/data/training/">Training</a><a href="/data/sleep/">Sleep</a></div>
    <div class="sf-col"><p class="sf-h label">The Protocols</p>
      <a href="/protocols/">All protocols</a><a href="/protocols/supplements/">Supplements</a><a href="/protocols/experiments/">Experiments</a><a href="/protocols/challenges/">Challenges</a></div>
    <div class="sf-col"><p class="sf-h label">Follow &amp; context</p>
      <a href="/subscribe/">Follow by email</a><a href="/rss.xml">RSS</a><a href="/method/">The method</a><a href="/story/about/">About</a><a href="/privacy/">Privacy</a></div>
  </nav>
  <p class="sf-base label"><span>averagejoematt · the story</span><a href="/">← home</a></p>
</footer>
<script>
  (function(){{
    var b=document.querySelector('.theme-toggle');
    if(b){{b.addEventListener('click',function(){{
      var r=document.documentElement;
      var cur=r.dataset.theme||(matchMedia('(prefers-color-scheme: light)').matches?'light':'dark');
      var next=cur==='light'?'dark':'light';
      r.dataset.theme=next;
      try{{localStorage.setItem('ajm-theme',next);}}catch(e){{}}
    }});}}
    var rp=document.getElementById('rp');
    window.addEventListener('scroll',function(){{
      if(!rp)return;
      var pct=window.scrollY/(document.body.scrollHeight-window.innerHeight)*100;
      rp.style.width=Math.min(pct,100)+'%';
    }});
  }})();
</script>
</body>
</html>"""


CANONICAL_URL_FMT = "https://averagejoematt.com/journal/posts/week-{seq:02d}/"


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────


def main():
    ap = argparse.ArgumentParser(description="Rebuild public journal pages + manifest for resurrected chronicle lead-ins")
    ap.add_argument("--apply", action="store_true", help="write to S3 (default: dry-run print of the plan)")
    ap.add_argument("--no-invalidate", action="store_true", help="with --apply: skip the CloudFront invalidation")
    args = ap.parse_args()

    dynamodb = boto3.resource("dynamodb", region_name=REGION)
    table = dynamodb.Table(TABLE_NAME)
    s3 = boto3.client("s3", region_name=REGION)

    installments = fetch_visible_installments(table)
    if not installments:
        print("No visible (phase=experiment, non-tombstoned) chronicle installments found — nothing to publish.")
        return 0

    all_dates = sorted(x.get("date", "") for x in installments if x.get("date", ""))
    genesis = EXPERIMENT_START_DATE
    print(f"Genesis: {genesis} · visible installments: {len(installments)}")

    writes = []  # (key, body_bytes, content_type)
    invalidation_paths = ["/journal/posts.json"]

    for item in installments:
        date_str = item.get("date", "")
        week_num = int(item.get("week_number", 0) or 0)
        title = item.get("title", "Untitled")
        stats_line = display_stats_line(item.get("stats_line", ""), date_str)  # #949 — prologue-framed dek pre-genesis
        label = series_label(date_str, all_dates, week_num)
        seq = seq_for(date_str, all_dates, week_num)
        body_html = body_html_from_record(item)
        page = render_post_html(title, stats_line, body_html, label, date_str, seq)
        key = f"generated/journal/posts/week-{seq:02d}/index.html"
        writes.append((key, page.encode("utf-8"), "text/html; charset=utf-8"))
        invalidation_paths.append(f"/journal/posts/week-{seq:02d}/*")
        print(f'  {date_str} · "{title}" → {key}  [{label}]  ({len(body_html.split())} words)')

    # Manifest — newest-first by date, schema identical to publish_to_journal()
    posts_manifest = []
    for item in sorted(installments, key=lambda x: x.get("date", ""), reverse=True):
        date_str = item.get("date", "")
        seq = seq_for(date_str, all_dates, int(item.get("week_number", 0) or 0))
        posts_manifest.append(
            {
                "week": int(item.get("week_number", 0) or 0),
                "label": series_label(date_str, all_dates, int(item.get("week_number", 0) or 0)),
                "title": item.get("title", ""),
                "date": date_str,
                "stats_line": display_stats_line(item.get("stats_line", ""), date_str),  # #949 — prologue-framed dek
                "url": f"/journal/posts/week-{seq:02d}/",
                # Prose-only excerpt (header stripped) — same field the reader shows verbatim.
                "excerpt": body_markdown_from_record(item)[:300].strip(),
                "word_count": int(item.get("word_count", 0) or 0),
                "has_board_interview": bool(item.get("has_board_interview", False)),
                "image_url": "",
                "image_credit": "",
            }
        )
    posts_json_str = json.dumps({"posts": posts_manifest, "updated_at": datetime.now(timezone.utc).isoformat()}, indent=2)
    writes.append((MANIFEST_KEY, posts_json_str.encode("utf-8"), "application/json"))
    print(f"  manifest → {MANIFEST_KEY} ({len(posts_manifest)} posts)")

    if not args.apply:
        print("\nDRY RUN — nothing written. Re-run with --apply to write S3 + invalidate CloudFront.")
        return 0

    for key, body, ctype in writes:
        s3.put_object(Bucket=S3_BUCKET, Key=key, Body=body, ContentType=ctype, CacheControl="max-age=300")
        print(f"WROTE s3://{S3_BUCKET}/{key} ({len(body)} bytes, {ctype})")

    if args.no_invalidate:
        print("Skipping CloudFront invalidation (--no-invalidate).")
        return 0
    try:
        cf = boto3.client("cloudfront", region_name="us-east-1")
        ref = f"leadin-pages-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}"
        inv = cf.create_invalidation(
            DistributionId=CLOUDFRONT_DISTRIBUTION_ID,
            InvalidationBatch={
                "Paths": {"Quantity": len(invalidation_paths), "Items": invalidation_paths},
                "CallerReference": ref,
            },
        )
        print(f"CloudFront invalidation {inv['Invalidation']['Id']} created for: {', '.join(invalidation_paths)}")
    except Exception as e:
        print(f"WARNING: CloudFront invalidation failed (pages ARE written; caches expire in <=300s anyway): {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
