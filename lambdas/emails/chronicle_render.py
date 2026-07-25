"""lambdas/emails/chronicle_render.py — markdown->HTML, the email shell, the
v5 journal post + manifest publisher, and the Weekly Signal metrics, split out of
wednesday_chronicle_lambda.py (#1654). Functions that read the (monkeypatchable)
experiment genesis or S3/SES clients take the facade globals via `_g`."""

import json
import re
from datetime import datetime, timezone

from constants import EXPERIMENT_BASELINE_WEIGHT_LBS, EXPERIMENT_START_DATE
from text_utils import truncate_at_word

# BS-05 confidence helpers (bundled digest_utils) — same optional-import shape as the facade.
try:
    from digest_utils import _confidence_badge, compute_confidence

    _HAS_CONFIDENCE = True
except ImportError:
    _HAS_CONFIDENCE = False

    def _confidence_badge(level):
        return ""


def markdown_to_html(md_text):
    """Convert Elena's markdown prose to clean HTML for email and journal."""
    lines = md_text.strip().split("\n")
    html_parts = []
    in_blockquote = False
    bq_buffer = []

    for line in lines:
        stripped = line.strip()

        # Blockquotes (Board interviews)
        if stripped.startswith("> "):
            if not in_blockquote:
                in_blockquote = True
                bq_buffer = []
            bq_buffer.append(stripped[2:])
            continue
        elif in_blockquote:
            # End of blockquote
            bq_text = " ".join(bq_buffer)
            # Convert **bold** and *italic*
            bq_text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", bq_text)
            bq_text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", bq_text)
            html_parts.append(f"<blockquote>{bq_text}</blockquote>")
            in_blockquote = False
            bq_buffer = []

        # Horizontal rule
        if stripped == "---":
            html_parts.append("<hr>")
            continue

        # Empty line
        if not stripped:
            continue

        # Italic line (closing signature like *Week N of The Measured Life*)
        if stripped.startswith("*") and stripped.endswith("*") and not stripped.startswith("**"):
            inner = stripped[1:-1]
            html_parts.append(f'<p class="signature"><em>{inner}</em></p>')
            continue

        # Regular paragraph — apply inline formatting
        text = stripped
        text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
        text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
        html_parts.append(f"<p>{text}</p>")

    # Flush any remaining blockquote
    if in_blockquote and bq_buffer:
        bq_text = " ".join(bq_buffer)
        bq_text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", bq_text)
        bq_text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", bq_text)
        html_parts.append(f"<blockquote>{bq_text}</blockquote>")

    return "\n".join(html_parts)


def parse_installment(raw_text):
    """Extract title, stats line, and body from Elena's output."""
    lines = raw_text.strip().split("\n")
    title = "Untitled"
    stats_line = ""
    body_lines = []

    i = 0
    # Find title (first non-empty line, usually in quotes)
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i < len(lines):
        title = lines[i].strip().strip('"').strip('"').strip('"')
        i += 1

    # Find stats line (contains "Weight:" or starts with "[")
    while i < len(lines):
        stripped = lines[i].strip()
        if not stripped:
            i += 1
            continue
        if "Weight:" in stripped or stripped.startswith("["):
            stats_line = stripped.strip("[]")
            i += 1
            break
        else:
            # No stats line found, this is body
            break

    # Rest is body
    body_lines = lines[i:]
    body = "\n".join(body_lines).strip()

    return title, stats_line, body


def build_email_html(title, stats_line, body_html, week_num, date_str, series_url):
    """Build a newsletter-style email — clean white, editorial, readable."""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        date_display = dt.strftime("%B %-d, %Y")
    except Exception:
        date_display = date_str

    # BS-05: Confidence badge — Chronicle is always n=7 (one week of data)
    # Henning: n<14 = LOW. Correct — weekly snapshot is preliminary by design.
    try:
        _conf = compute_confidence(days_of_data=7)
        _badge_html = _conf["badge_html"]
    except Exception:
        _badge_html = _confidence_badge("LOW") if _HAS_CONFIDENCE else ""

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>@media (prefers-color-scheme: dark){{body{{background:#1a1a1f !important;color:#e5e5e5 !important}}div[style*="background:#fafaf9"],div[style*="background:#fff"]{{background:#22222a !important;color:#e5e5e5 !important}}h1,h2,h3,h4{{color:#f5f5f5 !important}}td{{color:#d5d5d5 !important}}}}</style></head>
<body style="margin:0;padding:0;background:#f5f5f0;font-family:Georgia,'Times New Roman',serif;">
<div style="max-width:600px;margin:24px auto;background:#fafaf9;border-radius:4px;overflow:hidden;box-shadow:0 1px 4px rgba(0,0,0,0.06);">

  <!-- Masthead -->
  <div style="padding:32px 40px 20px;border-bottom:1px solid #e5e5e0;text-align:center;">
    <p style="font-family:-apple-system,sans-serif;font-size:11px;letter-spacing:3px;color:#999;margin:0 0 8px;text-transform:uppercase;">The Measured Life</p>
    <p style="font-family:-apple-system,sans-serif;font-size:13px;color:#666;margin:0;">An ongoing chronicle by Elena Voss</p>
  </div>

  <!-- Title block -->
  <div style="padding:28px 40px 8px;">
    <h1 style="font-size:26px;font-weight:400;color:#1a1a1a;margin:0 0 8px;line-height:1.3;font-style:italic;">"{title}"</h1>
    <p style="font-family:-apple-system,sans-serif;font-size:12px;color:#999;margin:0;">Week {week_num} &middot; {date_display}</p>
    <p style="font-family:-apple-system,sans-serif;font-size:11px;color:#b0b0a8;margin:6px 0 0;">{stats_line} {_badge_html}</p>
  </div>

  <!-- Body -->
  <div style="padding:12px 40px 32px;font-size:16px;line-height:1.75;color:#333;">
    <style>
      p {{ margin: 0 0 18px; }}
      blockquote {{ margin: 20px 0; padding: 12px 20px; border-left: 3px solid #d4d4c8; background: #f0f0ea; font-style: italic; color: #555; font-size: 15px; line-height: 1.7; }}
      blockquote strong {{ font-style: normal; color: #333; }}
      hr {{ border: none; border-top: 1px solid #e5e5e0; margin: 28px 0; }}
      .signature {{ text-align: center; color: #999; font-size: 14px; }}
    </style>
    {body_html}
  </div>

  <!-- Footer -->
  <div style="padding:20px 40px;border-top:1px solid #e5e5e0;text-align:center;">
    <p style="font-family:-apple-system,sans-serif;font-size:11px;color:#999;margin:0;">
      Read the full series at <a href="{series_url}" style="color:#666;">averagejoematt.com/story/chronicle</a>
    </p>
    <p style="font-family:-apple-system,sans-serif;font-size:12px;color:#888;margin:10px 0 4px;">Know someone who'd want this? They can get their own at <a href="https://averagejoematt.com/subscribe" style="color:#555;">averagejoematt.com/subscribe</a></p>
    <p style="font-family:-apple-system,sans-serif;font-size:9px;color:#bbb;margin:6px 0 0;">&#9874;&#65039; Personal health tracking only &mdash; not medical advice. Consult a qualified healthcare professional before making changes to your diet, exercise, or supplement regimen.</p>
  </div>

</div>
</body>
</html>"""


_JOURNAL_ROMAN = {1: "I", 2: "II", 3: "III", 4: "IV", 5: "V", 6: "VI", 7: "VII", 8: "VIII"}


def journal_post_ref(date_str, all_installments, week_num, *, _g):
    """The canonical journal-post reference for a chronicle date: (seq, label, url).

    #405: the share kit derives its canonical URL + card slug from the SAME sequential
    index the post is actually written to (``week-{seq:02d}``) — NOT the genesis-anchored
    week number (they diverge once pre-genesis prologue installments exist). This mirrors
    the ``_seq_for`` / ``_series_label`` closures inside ``publish_to_journal``; the two
    are pinned together by test_chronicle_share_kit so the kit can never point at a card
    slug the post doesn't live at.
    """
    EXPERIMENT_START_DATE = _g["EXPERIMENT_START_DATE"]
    genesis = EXPERIMENT_START_DATE
    all_dates = sorted(x.get("date", "") for x in all_installments if x.get("date", ""))
    pre = [d for d in all_dates if d < genesis]
    if date_str and date_str < genesis:
        n = pre.index(date_str) + 1 if date_str in pre else 1
        label = f"Prologue · Part {_JOURNAL_ROMAN.get(n, n)}"
    elif date_str:
        try:
            wk = max(
                1,
                ((datetime.strptime(date_str, "%Y-%m-%d").date() - datetime.strptime(genesis, "%Y-%m-%d").date()).days // 7) + 1,
            )
        except Exception:
            wk = int(week_num)
        label = f"Week {wk}"
    else:
        label = f"Week {int(week_num)}"
    seq = (all_dates.index(date_str) + 1) if date_str in all_dates else int(week_num)
    url = f"https://averagejoematt.com/journal/posts/week-{seq:02d}/"
    return seq, label, url


# #949 — the reader-facing dek for PRE-GENESIS lead-ins, reframed. The stored
# stats_line was authored mid-experiment ("… | Week 1 of The Measured Life"),
# which contradicts the prologue framing (only /data/cycles/ acknowledges prior
# attempts). Render parity with deploy/restart_leadin_pages.display_stats_line —
# both rebuild the SAME manifest, so a Wednesday publish must not resurrect the
# raw mid-experiment dek the reset's leadin pass reframed. DDB is never modified.
_WEEK_SEG_RE = re.compile(r"(?i)^week\s+\d+\b")
_PROLOGUE_HINT_RE = re.compile(r"(?i)prologue|before day 1")


def display_stats_line(stats_line, date_str, *, _g):
    EXPERIMENT_START_DATE = _g["EXPERIMENT_START_DATE"]
    line = str(stats_line or "")
    if not date_str or date_str >= EXPERIMENT_START_DATE:
        return line
    parts = [p.strip() for p in line.split("|") if p.strip()]
    kept = [p for p in parts if not _WEEK_SEG_RE.match(p)]
    if not any(_PROLOGUE_HINT_RE.search(p) for p in kept):
        kept.append("Prologue — the instrumented weeks before Day 1")
    return " | ".join(kept)


def publish_to_journal(title, stats_line, body_html, week_num, date_str, all_installments, write_to_s3=True, *, _g):
    """Publish installment to the Signal-themed journal on averagejoematt.com.

    Writes:
      generated/journal/posts/week-{nn}/index.html  — the post itself
      generated/journal/posts.json                   — manifest for the listing page

    Non-fatal: failure here never breaks the Chronicle email.

    FEAT-12: If write_to_s3=False, returns (post_key, post_html, posts_json_str) tuple.
    """
    s3 = _g["s3"]
    S3_BUCKET = _g["S3_BUCKET"]
    secrets = _g["secrets"]
    logger = _g["logger"]
    EXPERIMENT_START_DATE = _g["EXPERIMENT_START_DATE"]
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        date_display = dt.strftime("%B %-d, %Y")
    except Exception:
        date_display = date_str

    # Series label is anchored to the experiment GENESIS, not the installment count: posts dated
    # before genesis are the PROLOGUE (backstory), and the experiment week count starts at 1 on
    # the genesis week. URLs stay sequential (week-NN, prologue-inclusive) so existing links never
    # break; the visible label is what carries the truth. (Fixes the "Week 3 / three weeks" error
    # where pre-genesis lead-ins were numbered as experiment weeks — 2026-06-21.)
    _ROMAN = {1: "I", 2: "II", 3: "III", 4: "IV", 5: "V", 6: "VI", 7: "VII", 8: "VIII"}
    _genesis = EXPERIMENT_START_DATE
    _all_dates = sorted(x.get("date", "") for x in all_installments if x.get("date", ""))
    _pre = [d for d in _all_dates if d < _genesis]

    def _series_label(d):
        if not d:
            return f"Week {int(week_num)}"
        if d < _genesis:
            n = _pre.index(d) + 1 if d in _pre else 1
            return f"Prologue · Part {_ROMAN.get(n, n)}"
        try:
            wk = max(1, ((datetime.strptime(d, "%Y-%m-%d").date() - datetime.strptime(_genesis, "%Y-%m-%d").date()).days // 7) + 1)
        except Exception:
            wk = int(week_num)
        return f"Week {wk}"

    def _seq_for(d):
        return (_all_dates.index(d) + 1) if d in _all_dates else int(week_num)

    cur_label = _series_label(date_str)
    cur_seq = _seq_for(date_str)

    # Editorial cover image (Part II — atmospheric, free-license; fail-soft, kill-switch
    # default OFF). Carry past images forward from the existing manifest so we only fetch
    # for the NEW post (skip-if-set). ANY failure → no image, normal publish.
    cur_url = f"/journal/posts/week-{cur_seq:02d}/"
    _prior_imgs = {}
    cur_image = {}
    try:
        import editorial_image

        if editorial_image.enabled():
            try:
                _pj = json.loads(s3.get_object(Bucket=S3_BUCKET, Key="generated/journal/posts.json")["Body"].read())
                for _p in _pj.get("posts", []):
                    if _p.get("image_url"):
                        _prior_imgs[_p.get("url")] = {"image_url": _p["image_url"], "image_credit": _p.get("image_credit", "")}
            except Exception:
                _prior_imgs = {}
            cur_image = (
                _prior_imgs.get(cur_url)
                or editorial_image.fetch_and_store("chronicle", f"week-{cur_seq:02d}", cur_seq, s3_client=s3, secrets_client=secrets)
                or {}
            )
    except Exception:
        cur_image = {}

    _art_html = ""
    if cur_image.get("image_url"):
        _art_html = (
            '<figure class="post-header__art">'
            f'<img src="{cur_image["image_url"]}" alt="" loading="lazy">'
            f'<figcaption>{cur_image.get("image_credit", "")}</figcaption>'
            "</figure>"
        )

    # Extract read time (~250 words/min)
    word_count = len(body_html.split())
    read_min = max(4, round(word_count / 250))

    # Convert body_html (built for email) to prose-ready Signal HTML.
    # v5 template (#384): the live story-top five-door header + site-foot, editorial
    # cover as og:image, rel=canonical to the un-redirected /journal/posts/ URL, and an
    # end-of-read subscribe CTA. Chrome ported from scripts/v4_build_dispatches.py SHELL;
    # reading styles are chronicle-local and token-based (tokens.css .prose is the base).
    og_image = cur_image.get("image_url") or "https://averagejoematt.com/assets/images/og-home.png"
    canonical_url = f"https://averagejoematt.com/journal/posts/week-{cur_seq:02d}/"
    # #1620 — outbound social follow set, owner-confirmed 2026-07-23 (the issue's TikTok
    # typo `avereagejoematt` corrected to `averagejoematt`). This crawlable permalink is
    # the page a shared/viral chronicle link actually lands on, so the finished reader
    # needs an off-site next action here, not just an email CTA (Mara Chen's dead-end
    # bug). Kept in sync with scripts/v4_chrome.SOCIAL_LINKS + assets/js/dispatches.js
    # SOCIAL — three runtimes (email-Lambda / Python site-gen / browser JS), one handle
    # set. CTA marks are the line-art sprite via inline <use> (renders with no JS).
    _social = (
        ("bluesky", "Bluesky", "https://bsky.app/profile/averagejoematt.bsky.social"),
        ("x-twitter", "X", "https://x.com/averagejoematt_"),
        ("instagram", "Instagram", "https://www.instagram.com/averagejoematt/"),
        ("reddit", "Reddit", "https://www.reddit.com/user/averagejoematt/"),
        ("youtube", "YouTube", "https://www.youtube.com/@averagejoematt"),
        ("tiktok", "TikTok", "https://www.tiktok.com/@averagejoematt"),
    )
    social_cta_html = "".join(
        f'<a href="{url}" target="_blank" rel="me noopener" aria-label="Follow on {lbl}">'
        f'<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><use href="/assets/icons/icons.svg#i-{ic}"/></svg></a>'
        for ic, lbl, url in _social
    )
    social_foot_html = "".join(f'<a href="{url}" target="_blank" rel="me noopener">{lbl}</a>' for _ic, lbl, url in _social)
    post_html = f"""<!DOCTYPE html>
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
  <meta name="twitter:site" content="@averagejoematt_">
  <meta name="twitter:creator" content="@averagejoematt_">
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
    "datePublished": "{datetime.now(timezone.utc).date().isoformat()}",
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
    /* #1620 — outbound social follow row: the off-site next action at the end of the
       crawlable post (the page a shared/viral link actually lands on). Line-art marks
       from the shared sprite via inline <use> — renders with no JS. */
    .post-cta__social {{ display:flex;align-items:center;justify-content:center;gap:var(--sp-3);flex-wrap:wrap;margin:var(--sp-4) auto 0;max-width:none; }}
    .post-cta__social .label {{ font-family:var(--font-mono);font-size:var(--fs-label);letter-spacing:var(--tracking-label);text-transform:uppercase;color:var(--ink-faint); }}
    .post-cta__social a {{ display:inline-flex;color:var(--ink-muted);transition:color var(--dur-fast); }}
    .post-cta__social a:hover {{ color:var(--ember); }}
    .post-cta__social svg {{ width:22px;height:22px; }}
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
    <a href="/cockpit/" title="Today's live instrument — your daily numbers, read back to you"><svg class="ico ico-door" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><use href="/assets/icons/icons.svg#i-door-cockpit"></use></svg>the cockpit</a>
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
    {_art_html}
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
    <p class="post-cta__social"><span class="label">or follow off-site</span>{social_cta_html}</p>
  </aside>
  <nav class="post-nav">
    <a href="/story/chronicle/"><span>&larr; All installments</span>The Measured Life archive</a>
    <a href="/cockpit/"><span>Today</span>The live cockpit &rarr;</a>
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
      <a href="/subscribe/">Follow by email</a><a href="/rss.xml">RSS</a>{social_foot_html}<a href="/method/">The method</a><a href="/story/about/">About</a><a href="/privacy/">Privacy</a></div>
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

    post_key = f"generated/journal/posts/week-{cur_seq:02d}/index.html"

    # Update posts.json manifest — ordered newest-first by DATE (not by a week number, which now
    # collides: a pre-genesis prologue and the genesis Week 1 can share a raw number). URLs are the
    # stable sequential index; "label" carries the genesis-anchored truth (Prologue vs Week N).
    posts_manifest = []
    for inst in sorted(all_installments, key=lambda x: x.get("date", ""), reverse=True):
        idate = inst.get("date", "")
        seq = _seq_for(idate)
        _u = f"/journal/posts/week-{seq:02d}/"
        # current post → freshly fetched image; past posts → carried forward from the prior manifest.
        _im = cur_image if idate == date_str else _prior_imgs.get(_u, {})
        posts_manifest.append(
            {
                "week": int(inst.get("week_number", 0) or 0),
                "label": _series_label(idate),
                "title": inst.get("title", ""),
                "date": idate,
                "stats_line": display_stats_line(inst.get("stats_line", ""), idate, _g=_g),  # #949 — prologue-framed dek pre-genesis
                "url": _u,
                "excerpt": truncate_at_word(inst.get("content_markdown") or "", 300),  # #1224: word boundary, no mid-word cut
                "word_count": inst.get("word_count", 0),
                "has_board_interview": inst.get("has_board_interview", False),
                "image_url": _im.get("image_url", ""),
                "image_credit": _im.get("image_credit", ""),
            }
        )
    posts_json_str = json.dumps(
        {"posts": posts_manifest, "updated_at": datetime.now(timezone.utc).isoformat()},
        indent=2,
    )

    if not write_to_s3:
        return post_key, post_html, posts_json_str

    # Write the post
    s3.put_object(
        Bucket=S3_BUCKET,
        Key=post_key,
        Body=post_html.encode("utf-8"),
        ContentType="text/html; charset=utf-8",
        CacheControl="max-age=300",
    )
    logger.info(f"[journal] Post written: {post_key}")

    s3.put_object(
        Bucket=S3_BUCKET,
        Key="generated/journal/posts.json",
        Body=posts_json_str.encode("utf-8"),
        ContentType="application/json",
        CacheControl="max-age=300",
    )
    logger.info(f"[journal] posts.json manifest updated ({len(posts_manifest)} posts)")

    return f"https://averagejoematt.com/journal/posts/week-{week_num:02d}/"


def build_weekly_signal_data(data, week_num):
    """Extract structured metrics for the Weekly Signal email template."""
    BOARD_ROTATION = [
        "sarah_chen",
        "marcus_webb",
        "lisa_park",
        "james_okafor",
        "maya_rodriguez",
        "layne_norton",
        "rhonda_patrick",
        "peter_attia",
        "andrew_huberman",
        "paul_conti",
        "vivek_murthy",
        "the_chair",
        "margaret_calloway",
        "elena_voss",
    ]
    OBSERVATORY_ROTATION = [
        {"slug": "sleep", "name": "Sleep Observatory", "hook": "How does recovery score connect to sleep architecture?"},
        {"slug": "training", "name": "Training Observatory", "hook": "Zone 2 base, progressive overload, and the fitness-fatigue model."},
        {"slug": "nutrition", "name": "Nutrition Observatory", "hook": "Macros, meal timing, and the protein distribution puzzle."},
        {"slug": "glucose", "name": "Glucose Observatory", "hook": "What does the CGM reveal about real-time metabolic response?"},
        {"slug": "mind", "name": "Inner Life Observatory", "hook": "Journal sentiment, mood trajectory, and the mind-body connection."},
        {"slug": "character", "name": "Character Sheet", "hook": "The RPG-style score that tracks the whole transformation."},
        # #1218: the "benchmarks" observatory hook is retired — the /method/benchmarks board reads
        # SOURCE#benchmarks, a partition with NO writer anywhere in the codebase, so linking readers
        # there sends them to a permanently-empty page. Restore this entry only once a real writer ships.
    ]

    profile = data.get("profile") or {}
    withings = data.get("withings") or {}
    whoop = data.get("whoop") or {}
    sleep_data = data.get("sleep") or {}
    strava = data.get("strava") or {}
    habits = data.get("habits") or {}
    grades = data.get("day_grades") or {}

    # Weight
    weight_lbs = None
    if withings.get("weight_kg"):
        weight_lbs = round(float(withings["weight_kg"]) * 2.20462, 1)
    start_weight = float(profile.get("journey_start_weight_lbs", EXPERIMENT_BASELINE_WEIGHT_LBS))  # Matthew-specific fallback
    weight_delta = round(start_weight - weight_lbs, 1) if weight_lbs else None

    # Sleep
    sleep_hrs = float(sleep_data.get("sleep_duration_hours", 0) or 0)
    sleep_eff = float(sleep_data.get("sleep_efficiency_pct", 0) or whoop.get("sleep_efficiency_pct", 0) or 0)

    # Training
    activities = strava.get("activities") or []
    training_sessions = len(activities) if isinstance(activities, list) else int(activities or 0)

    # Habits
    habit_completed = int(habits.get("tier0_completed", 0) or 0)
    habit_possible = int(habits.get("tier0_possible", 1) or 1)
    habit_pct = round((habit_completed / habit_possible) * 100) if habit_possible > 0 else 0

    # Recovery
    recovery_pct = float(whoop.get("recovery_score", 0) or 0)
    hrv_ms = float(whoop.get("hrv", 0) or whoop.get("hrv_yesterday", 0) or 0)

    # Day grades
    avg_grade = grades.get("avg_score") or grades.get("total_score") or 0

    # Journey days
    journey_start = profile.get("journey_start_date", EXPERIMENT_START_DATE)
    try:
        start_dt = datetime.strptime(journey_start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        journey_days = max(0, (datetime.now(timezone.utc) - start_dt).days)
    except Exception:
        journey_days = 0

    featured_member_id = BOARD_ROTATION[(week_num - 1) % len(BOARD_ROTATION)]
    featured_observatory = OBSERVATORY_ROTATION[(week_num - 1) % len(OBSERVATORY_ROTATION)]

    return {
        "weight_lbs": weight_lbs,
        "weight_delta_journey_lbs": weight_delta,
        "avg_sleep_hours": round(sleep_hrs, 1),
        "avg_sleep_efficiency_pct": round(sleep_eff),
        "training_sessions": training_sessions,
        "habit_pct": habit_pct,
        "habits_completed": habit_completed,
        "habits_possible": habit_possible,
        "avg_recovery_pct": round(recovery_pct),
        "avg_hrv_ms": round(hrv_ms),
        "avg_day_grade": round(float(avg_grade), 1) if avg_grade else 0,
        "journey_days": journey_days,
        "featured_member_id": featured_member_id,
        "featured_observatory": featured_observatory,
    }
