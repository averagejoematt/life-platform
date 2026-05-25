#!/usr/bin/env python3
"""
PR-1: Register "The Architecture of Absence" in the chronicle index.

PROBLEM
-------
On 2026-05-03 the special-edition chronicle was published to:
  - s3://matthew-life-platform/blog/week-05.html
  - s3://matthew-life-platform/generated/journal/posts/week-05/index.html
…via deploy/publish_special_edition_chronicle_2026_05_03.py.

That publisher rebuilt blog/index.html and generated/journal/posts.json.
It did NOT touch site/chronicle/posts.json — which is what /chronicle/ reads.

So /chronicle/ shows the 4 prequel installments and looks unchanged. The
Architecture of Absence is live at /journal/posts/week-05/ and /blog/week-05.html
but invisible from the front-door /chronicle/ index.

This script is the bandaid. PR-2 (separate spec) will redesign the whole
chronicle/journal/blog mess into a single canonical namespace with
sequential issue numbering.

WHAT THIS DOES
--------------
1. Generates site/chronicle/posts/issue-05/index.html from the markdown source
   (docs/elena_special_edition_chronicle_2026_05_03.md), using the existing
   chronicle post pattern (matching site/chronicle/posts/week-00/index.html).

2. Patches site/chronicle/posts.json to add Issue 5 as the latest entry,
   pointing at /chronicle/posts/issue-05/.

3. Leaves /blog/week-05.html and /journal/posts/week-05/ ALONE — they continue
   to work as alternate URLs. PR-2 will canonicalize.

NOTE: This script only modifies the LOCAL repo. After running this, you still need:
  bash deploy/sync_site_to_s3.sh
  aws cloudfront create-invalidation --distribution-id E3S424OXQZ8NBE --paths '/chronicle/*'

USAGE
-----
  python3 deploy/pr1_register_architecture_of_absence_2026_05_03.py            # dry-run
  python3 deploy/pr1_register_architecture_of_absence_2026_05_03.py --apply    # write files

This script is idempotent — re-running with --apply will overwrite the same
files with the same content.
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone

# ── Configuration ────────────────────────────────────────────────────────────
# Resolve project root relative to this script (deploy/ is a child of root)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SOURCE_MD = os.path.join(PROJECT_ROOT, "docs",
                         "elena_special_edition_chronicle_2026_05_03.md")
CHRONICLE_DIR = os.path.join(PROJECT_ROOT, "site", "chronicle")
POSTS_JSON = os.path.join(CHRONICLE_DIR, "posts.json")
NEW_POST_DIR = os.path.join(CHRONICLE_DIR, "posts", "issue-05")
NEW_POST_HTML = os.path.join(NEW_POST_DIR, "index.html")

ISSUE_NUMBER = 5
TITLE = "The Architecture of Absence"
DATE = "2026-05-03"
URL = "/chronicle/posts/issue-05/"
PHASE = "season1"
KICKER = "Special Edition · Issue 5"
CONTEXT_LINE = ("Special Edition · Issue 5 · "
                "Days off-grid: 19 · April experiments: 5 of 5 failed · "
                "Re-entry: May 4, 2026")


def parse_markdown(path):
    """Strip the title line + bracket meta line, return body markdown."""
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()

    lines = raw.splitlines()
    # The source starts: "The Architecture of Absence"\n\n[Days off-grid...]\n\n<body>
    # Skip everything up to and including the [Days off-grid...] line.
    body_start = 0
    for i, line in enumerate(lines):
        if line.strip().startswith("[Days off-grid"):
            body_start = i + 1
            break
    body = "\n".join(lines[body_start:]).strip()
    word_count = len(body.split())
    return body, word_count


def md_to_html(md):
    """Lightweight markdown → HTML for prose-only chronicles.

    Handles: paragraphs split by blank lines, --- horizontal rules,
    and *italic* / **bold** inline. The source markdown has no headers,
    code blocks, blockquotes, or lists, so we keep this minimal."""
    blocks = re.split(r"\n\s*\n", md.strip())
    out = []
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        if block == "---":
            out.append("<hr>")
            continue
        # Bold first (avoid greedy single-* eating **), then italic
        block = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", block)
        block = re.sub(r"\*(.+?)\*", r"<em>\1</em>", block)
        # Center the trailing italic note as a signature
        if (block.startswith("<em>") and block.endswith("</em>")
                and "special-edition" in block.lower()):
            out.append(f'<p class="signature">{block}</p>')
        else:
            out.append(f"<p>{block}</p>")
    return "\n\n".join(out)


def generate_excerpt(body_md, max_chars=320):
    """First paragraph, trimmed to max_chars at a word boundary."""
    first_para = body_md.strip().split("\n\n", 1)[0]
    first_para = re.sub(r"\*+", "", first_para).strip()
    if len(first_para) <= max_chars:
        return first_para
    cut = first_para[:max_chars].rsplit(" ", 1)[0]
    return cut + "…"


def build_post_html(body_html, word_count):
    """Generate the chronicle post page, modeled on
    site/chronicle/posts/week-00/index.html."""
    read_min = max(1, round(word_count / 250))
    pretty_date = datetime.strptime(DATE, "%Y-%m-%d").strftime("%B %-d, %Y")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <style>.nav-overlay{{display:none}}</style>
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="description" content="The Architecture of Absence — Special Edition of The Measured Life by Elena Voss">
  <meta property="og:title" content="The Architecture of Absence — The Measured Life">
  <meta property="og:description" content="{CONTEXT_LINE}">
  <meta property="og:image" content="https://averagejoematt.com/assets/images/og-image.png">
  <meta property="og:image:width" content="1200">
  <meta property="og:image:height" content="630">
  <meta name="twitter:card" content="summary_large_image">
  <meta property="og:type" content="article">
  <title>The Architecture of Absence — The Measured Life</title>
  <link rel="alternate" type="application/rss+xml" title="The Measured Life" href="/rss.xml">
  <link rel="canonical" href="https://averagejoematt.com{URL}">
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
    .post-header {{ padding:var(--space-16) var(--page-padding) var(--space-10);border-bottom:1px solid var(--border);max-width:calc(var(--prose-width) + var(--page-padding) * 2);margin:0 auto; }}
    .post-header__series {{ font-size:var(--text-2xs);letter-spacing:var(--ls-tag);text-transform:uppercase;color:var(--accent-dim);margin-bottom:var(--space-3); }}
    .post-header__title {{ font-family:var(--font-serif);font-size:clamp(28px,4vw,46px);color:var(--text);line-height:1.15;font-weight:400;font-style:italic;margin-bottom:var(--space-5); }}
    .post-header__meta {{ display:flex;align-items:center;gap:var(--space-5);font-size:var(--text-xs);letter-spacing:var(--ls-tag);text-transform:uppercase;color:var(--text-muted); }}
    .post-header__stats {{ font-size:var(--text-xs);color:var(--text-faint);letter-spacing:var(--ls-tag);margin-top:var(--space-3); }}
    .post-body {{ max-width:calc(var(--prose-width) + var(--page-padding) * 2);margin:0 auto;padding:var(--space-10) var(--page-padding) var(--space-20); }}
    .prose {{ font-family:var(--font-serif); }}
    .prose p {{ font-size:18px;line-height:1.85;color:var(--text);margin-bottom:var(--space-6); }}
    .prose p:first-of-type::first-letter {{ font-size:64px;line-height:0.8;float:left;margin-right:var(--space-3);margin-top:8px;color:var(--accent);font-family:var(--font-serif); }}
    .prose hr {{ border:none;border-top:1px solid var(--border);margin:var(--space-10) 0; }}
    .prose .signature {{ text-align:center;font-size:14px;color:var(--text-muted);font-style:italic; }}
    .prose strong {{ color:var(--text);font-weight:700; }}
    .prose em {{ font-style:italic; }}
    .post-nav {{ max-width:calc(var(--prose-width) + var(--page-padding) * 2);margin:0 auto;padding:var(--space-6) var(--page-padding) var(--space-16);border-top:1px solid var(--border);display:flex;justify-content:space-between;gap:var(--space-6); }}
    .post-nav a {{ font-family:var(--font-serif);font-size:17px;color:var(--text);text-decoration:none;transition:color var(--dur-fast); }}
    .post-nav a:hover {{ color:var(--accent); }}
    .post-nav span {{ display:block;font-family:var(--font-mono);font-size:var(--text-2xs);letter-spacing:var(--ls-tag);text-transform:uppercase;color:var(--text-muted);margin-bottom:var(--space-1); }}
  </style>
</head>
<body>
<div class="reading-progress"><div class="reading-progress__fill" id="rp"></div></div>
<div id="amj-nav"></div>

<div class="post-header">
  <div class="post-header__series">The Measured Life &middot; {KICKER} &middot; By Elena Voss</div>
  <h1 class="post-header__title">&ldquo;{TITLE}&rdquo;</h1>
  <div class="post-header__meta">
    <span>{pretty_date}</span>
    <span>&middot;</span>
    <span>{read_min} min read</span>
  </div>
  <div class="post-header__stats">{CONTEXT_LINE}</div>
</div>

<article class="post-body">
  <div class="prose">
{body_html}
  </div>
</article>

<div class="discord-community-card">
  <div class="community-card-header">&sharp; COMMUNITY ──────────────</div>
  <p class="community-card-body">Have thoughts on this week's data? Want to follow along and talk about it? The community is open.</p>
  <a href="https://discord.gg/T4Ndt2WsU" target="_blank" rel="noopener" class="community-card-cta">Join Average Joe Community &rarr;</a>
</div>

<div class="post-nav">
  <a href="/chronicle/"><span>&larr; All installments</span>The Measured Life archive</a>
  <a href="/"><span>The experiment</span>averagejoematt.com &rarr;</a>
</div>

<div id="amj-bottom-nav"></div>
<div id="amj-footer"></div>

<script>
  const rp = document.getElementById('rp');
  window.addEventListener('scroll', () => {{
    const pct = window.scrollY / (document.body.scrollHeight - window.innerHeight) * 100;
    rp.style.width = Math.min(pct, 100) + '%';
  }});
</script>
<script src="/assets/js/site_constants.js"></script>
<script src="/assets/js/components.js"></script>
<script src="/assets/js/nav.js"></script>
</body>
</html>
"""


def patch_posts_json(word_count, excerpt):
    """Read posts.json, prepend Issue 5 entry, write back. Idempotent —
    re-running replaces an existing issue-05 entry rather than duplicating."""
    with open(POSTS_JSON, "r", encoding="utf-8") as f:
        data = json.load(f)

    new_entry = {
        # Forward-compatible: PR-2 will rename `week` → `number` everywhere.
        # For now, keep `week` so the existing index template renders it.
        "week": ISSUE_NUMBER,
        "title": TITLE,
        "date": DATE,
        "stats_line": CONTEXT_LINE,
        "url": URL,
        "excerpt": excerpt,
        "word_count": word_count,
        "has_board_interview": False,
        "phase": PHASE,
        "badges": ["Special Edition"],
        "coming_soon": False,
    }

    # Drop any existing entry pointing at the same URL or with the same week,
    # so re-runs are idempotent and previous bandaids get replaced.
    posts = [p for p in data.get("posts", [])
             if p.get("url") != URL and p.get("week") != ISSUE_NUMBER]
    posts.insert(0, new_entry)
    data["posts"] = posts
    data["updated_at"] = datetime.now(timezone.utc).isoformat()

    return data


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true",
                        help="Write files. Without this, runs in dry-run mode.")
    args = parser.parse_args()

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"\n=== PR-1: Register Architecture of Absence in chronicle [{mode}] ===\n")

    # 1. Read source markdown
    if not os.path.isfile(SOURCE_MD):
        print(f"ERROR: source markdown not found at {SOURCE_MD}")
        return 1
    body_md, word_count = parse_markdown(SOURCE_MD)
    body_html = md_to_html(body_md)
    excerpt = generate_excerpt(body_md)

    print(f"  Source markdown: {SOURCE_MD}")
    print(f"  Word count:      {word_count}")
    print(f"  Excerpt:         {excerpt[:120]}...")
    print()

    # 2. Build the post HTML
    post_html = build_post_html(body_html, word_count)
    print(f"  New post path:   {NEW_POST_HTML}")
    print(f"  Post HTML size:  {len(post_html)} chars")
    print()

    # 3. Patch posts.json
    if not os.path.isfile(POSTS_JSON):
        print(f"ERROR: posts.json not found at {POSTS_JSON}")
        return 1
    new_posts_json = patch_posts_json(word_count, excerpt)
    print(f"  posts.json:      {POSTS_JSON}")
    print(f"  Total posts after patch: {len(new_posts_json['posts'])}")
    print(f"  Issue 5 entry:")
    print(json.dumps(new_posts_json["posts"][0], indent=4))
    print()

    if not args.apply:
        print("DRY-RUN — pass --apply to write files.\n")
        return 0

    # 4. Write files
    os.makedirs(NEW_POST_DIR, exist_ok=True)
    with open(NEW_POST_HTML, "w", encoding="utf-8") as f:
        f.write(post_html)
    print(f"  ✓ Wrote {NEW_POST_HTML}")

    with open(POSTS_JSON, "w", encoding="utf-8") as f:
        json.dump(new_posts_json, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"  ✓ Wrote {POSTS_JSON}")

    print()
    print("=" * 60)
    print("LOCAL FILES UPDATED. Next steps (run in terminal):")
    print()
    print("  cd ~/Documents/Claude/life-platform")
    print("  bash deploy/sync_site_to_s3.sh")
    print("  aws cloudfront create-invalidation \\")
    print("    --distribution-id E3S424OXQZ8NBE \\")
    print("    --paths '/chronicle/*'")
    print()
    print("Then verify at:")
    print("  https://averagejoematt.com/chronicle/")
    print("  https://averagejoematt.com/chronicle/posts/issue-05/")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
