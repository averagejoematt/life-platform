#!/usr/bin/env python3
"""
v4_build_journal.py — generate the "In my own words" essay permalink pages (#1566).

Kills the hand-HTML step for Matt's own essays. Before this, a new essay meant
hand-authoring a full static page at site/journal/essays/<slug>/index.html AND
hand-appending to site/journal/blog.json — which is why the surface had exactly
one post. Now an essay is TWO edits:

    1. one entry in  site/journal/blog.json  (title, date, excerpt, url, label, …)
    2. one body file  site/journal/essays/<slug>/body.html  (a verbatim .prose
       fragment)  OR  site/journal/essays/<slug>/body.md  (lightweight markdown)

…and this generator renders the designed permalink page (v5 page kit — .prose,
tokens, canonical/OG/JSON-LD, the reading-progress rail) with ZERO hand-authored
page HTML. RSS already merges blog.json (scripts/v4_build_rss.py), so a new essay
rides into the feed on the same deploy that publishes its page.

PUBLISHING STAYS MANUAL (the #1563 "Voice" scope guard — never auto-publish
Matthew's words). This script is DRY-RUN BY DEFAULT: a bare invocation prints what
it WOULD write and touches nothing. It writes only with an explicit --write, which
is what the site deploy path (deploy/sync_site_to_s3.sh) passes — the same deploy
Matthew triggers by hand. There is no schedule, no auto-publish.

Every rendered body passes the same fail-closed privacy gate as every other
published surface (lambdas/privacy_guard) — a blocked-vice / real-name leak aborts
the build before anything is written.

Chrome (doors nav, footer, loop-forward close) is emitted from the single source
scripts/v4_chrome.py, so the page lands already-normalized and v4_apply_chrome.py
(run last in the deploy) is a no-op on it.

stdlib only; run from the repo root:
    python3 scripts/v4_build_journal.py                 # dry-run (default) — prints, writes nothing
    python3 scripts/v4_build_journal.py --write          # emit the permalink pages
    python3 scripts/v4_build_journal.py --check          # exit 1 if any page is out of date (CI)
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from datetime import datetime
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_REPO / "lambdas"))

import privacy_guard  # noqa: E402  — the fail-closed publish gate (ADR-104)
import v4_chrome  # noqa: E402  — the single-source doors nav / footer / loop-forward

BLOG_SRC = _REPO / "site" / "journal" / "blog.json"
ESSAYS_DIR = _REPO / "site" / "journal" / "essays"
STORY_DOOR = "/story/"  # essays live under the Story door (aria-current + loop-forward key)
WORDS_PER_MIN = 210  # reading-speed constant for the derived "N min read"

# The essay-page CSS, kept verbatim from the proven org-chart-of-one page. Essay-
# specific (reading-progress rail, drop-cap, .prose tuning, the CTA/nav blocks) so it
# lives inline rather than in the shared story.css — one <style> block, one source.
STYLE = """  <style>
    .reading-progress { position:fixed;top:0;left:0;right:0;height:2px;background:transparent;z-index:var(--z-overlay); }
    .reading-progress__fill { height:100%;background:var(--ember);width:0%;transition:width 0.1s linear; }
    .post-wrap { max-width:var(--container-read);margin:0 auto;padding-inline:var(--gutter); }
    .post-header { padding:var(--sp-8) 0 var(--sp-6);border-bottom:var(--border-hair); }
    .post-header__series { font-family:var(--font-mono);font-size:var(--fs-label);letter-spacing:var(--tracking-label);text-transform:uppercase;color:var(--ember);margin-bottom:var(--sp-3); }
    .post-header__title { font-family:var(--font-serif);font-size:var(--fs-h1);color:var(--ink);line-height:var(--lh-snug);font-weight:var(--weight-reg);font-style:italic;margin-bottom:var(--sp-4); }
    .post-header__meta { display:flex;flex-wrap:wrap;align-items:center;gap:var(--sp-3);font-family:var(--font-mono);font-size:var(--fs-label);letter-spacing:var(--tracking-label);text-transform:uppercase;color:var(--ink-muted); }
    .post-header__stats { font-family:var(--font-mono);font-size:var(--fs-label);color:var(--ink-faint);letter-spacing:var(--tracking-label);margin-top:var(--sp-2); }
    .post-body { padding:var(--sp-7) 0 var(--sp-8); }
    .post-body .prose { font-family:var(--font-serif);max-width:none; }
    .post-body .prose p { max-width:none;line-height:var(--lh-relaxed); }
    .post-body .prose > p:first-of-type::first-letter { font-size:64px;line-height:0.8;float:left;margin-right:var(--sp-2);margin-top:6px;color:var(--ember);font-family:var(--font-serif); }
    .post-body .prose blockquote { border-left:2px solid var(--ember);padding:var(--sp-3) var(--sp-5);background:var(--ember-wash);margin:var(--sp-6) 0;font-style:italic;color:var(--ink); }
    .post-body .prose h2 { max-width:none; }
    .post-body .prose hr { border:none;border-top:var(--border-hair);margin:var(--sp-7) 0; }
    .post-body .prose strong { color:var(--ink);font-weight:var(--weight-med); }
    .post-body .prose ol { max-width:none; }
    .post-body .prose code { font-family:var(--font-mono);font-size:0.82em;color:var(--ink-muted);word-break:break-word; }
    .post-receipts { font-family:var(--font-mono);font-size:var(--fs-label);color:var(--ink-faint);letter-spacing:var(--tracking-label);margin-top:var(--sp-6);border-top:var(--border-hair);padding-top:var(--sp-4); }
    .post-receipts a { color:var(--ember);text-decoration:none;border-bottom:1px solid var(--ember-line); }
    .post-cta { margin:var(--sp-6) 0 var(--sp-7);padding:var(--sp-6);border:var(--border-hair);border-radius:var(--radius);background:var(--ember-wash);text-align:center; }
    .post-cta h2 { font-family:var(--font-serif);font-style:italic;font-weight:var(--weight-reg);font-size:var(--fs-h3);color:var(--ink);margin:0 0 var(--sp-2); }
    .post-cta p { color:var(--ink-muted);font-size:var(--fs-small);margin:0 auto var(--sp-4);max-width:44ch; }
    .post-cta a.cta-btn { display:inline-block;font-family:var(--font-mono);font-size:var(--fs-label);letter-spacing:var(--tracking-label);text-transform:uppercase;color:var(--page);background:var(--ember);padding:10px 20px;border-radius:var(--radius-sm);text-decoration:none; }
    .post-cta a.cta-btn:hover { filter:brightness(1.08); }
    .post-nav { padding:var(--sp-5) 0 var(--sp-8);border-top:var(--border-hair);display:flex;justify-content:space-between;gap:var(--sp-5);flex-wrap:wrap; }
    .post-nav a { font-family:var(--font-serif);font-size:var(--fs-body);color:var(--ink);text-decoration:none;transition:color var(--dur-fast); }
    .post-nav a:hover { color:var(--ember); }
    .post-nav span { display:block;font-family:var(--font-mono);font-size:var(--fs-label);letter-spacing:var(--tracking-label);text-transform:uppercase;color:var(--ink-faint);margin-bottom:var(--sp-1); }
  </style>"""

PAGE = """<!DOCTYPE html>
<html lang="en" data-door="story">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
  <title>{title} — averagejoematt</title>
  <meta name="description" content="{meta_desc}">
  <link rel="canonical" href="https://averagejoematt.com{url}">
  <meta property="og:type" content="article">
  <meta property="og:site_name" content="averagejoematt">
  <meta property="og:url" content="https://averagejoematt.com{url}">
  <meta property="og:title" content="{og_title}">
  <meta property="og:description" content="{og_desc}">
  <meta property="og:image" content="https://averagejoematt.com/assets/images/{og_image}">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="{og_title}">
  <meta name="twitter:description" content="{twitter_desc}">
  <meta name="twitter:image" content="https://averagejoematt.com/assets/images/{og_image}">
{head_chrome}
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-title" content="Measured Life">
  <link rel="alternate" type="application/rss+xml" title="averagejoematt" href="/rss.xml">
  <script type="application/ld+json">
  {ld_json}
  </script>
  <link rel="preload" href="/assets/fonts/v4/pxiTypc9vsFDm051Uf6KVwgkfoSxQ0GsQv8ToedPibnr0SZe1ZuWi3g.woff2" as="font" type="font/woff2" crossorigin>
  <link rel="preload" href="/assets/fonts/v4/6NU78FyLNQOQZAnv9bYEvDiIdE9Ea92uemAk_WBq8U_9v0c2Wa0KxC9TeP2Xz5c.woff2" as="font" type="font/woff2" crossorigin>
  <link rel="preload" href="/assets/fonts/v4/-F63fjptAgt5VM-kVkqdyU8n1i8q131nj-o.woff2" as="font" type="font/woff2" crossorigin>
  <link rel="stylesheet" href="/assets/css/fonts.css">
  <link rel="stylesheet" href="/assets/css/tokens.css">
  <link rel="stylesheet" href="/assets/css/story.css">
  <script>(function(){{try{{var t=localStorage.getItem("ajm-theme");if(t==="light"||t==="dark")document.documentElement.dataset.theme=t;}}catch(e){{}}}})();</script>
{style}
</head>
<body class="dx-page">
<a class="skip" href="#post">Skip to the essay</a>
<div class="reading-progress"><div class="reading-progress__fill" id="rp"></div></div>
<header class="story-top">
  <a class="brand" href="/"><span class="brand-mark" aria-hidden="true"></span><span class="brand-name">averagejoematt</span> <span class="brand-door label">the story</span></a>
  {doors_nav}
</header>
<main id="post">
<div class="post-wrap">
  <div class="post-header">
    <div class="post-header__series">{series}</div>
    <h1 class="post-header__title">{title}</h1>
    <div class="post-header__meta">
      <span>{date_human}</span>
      <span>&middot;</span>
      <span>{read_minutes} min read</span>
    </div>
{stats_block}  </div>
  <article class="post-body">
    <div class="prose">
{body}
    </div>
  </article>
  <aside class="post-cta">
    <h2>{cta_title}</h2>
    <p>{cta_body}</p>
    <a class="cta-btn" href="{cta_href}">{cta_button}</a>
  </aside>
  <nav class="post-nav">
    <a href="{nav_prev_href}"><span>{nav_prev_sub}</span>{nav_prev_label}</a>
    <a href="{nav_next_href}"><span>{nav_next_sub}</span>{nav_next_label}</a>
  </nav>
</div>
</main>
{loop_forward}{site_footer}
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
</html>
"""


def _esc(s) -> str:
    """HTML-attribute-safe escape (quotes escaped)."""
    return html.escape(str(s if s is not None else ""), quote=True)


def human_date(date_str: str) -> str:
    """2026-07-08 -> 'July 8, 2026' (no leading zero on the day)."""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return f"{dt.strftime('%B')} {dt.day}, {dt.year}"


def slug_for(post: dict) -> str:
    """The essay's directory slug — from its url (/journal/essays/<slug>/) or id."""
    url = (post.get("url") or "").strip("/")
    if url.startswith("journal/essays/"):
        return url[len("journal/essays/") :].strip("/")
    return str(post.get("id") or "").strip("/")


def read_minutes(post: dict) -> int:
    """Explicit read_minutes, else derived from word_count, else a 1-min floor."""
    if post.get("read_minutes"):
        return int(post["read_minutes"])
    wc = int(post.get("word_count") or 0)
    return max(1, round(wc / WORDS_PER_MIN)) if wc else 1


# ── Minimal markdown → HTML for the body.md authoring path ────────────────────
# Deliberately a SMALL, predictable subset (no external deps, matches the repo's
# no-third-party convention): ## / ### headings, paragraphs, blockquotes, - and
# 1. lists, --- rules, plus inline **bold**, _italic_, `code`, and [text](url).
# The verbatim body.html path stays the primary one; this is the convenience layer
# so a plain-text essay never needs hand HTML.
_INLINE_CODE = re.compile(r"`([^`]+)`")
_BOLD = re.compile(r"\*\*([^*]+)\*\*")
_ITALIC = re.compile(r"(?<![\w*])[*_]([^*_]+)[*_](?![\w*])")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


def _inline_md(text: str) -> str:
    # Escape first, then re-introduce the sanctioned inline tags — so raw HTML in a
    # markdown source can't inject markup.
    out = html.escape(text, quote=False)
    out = _INLINE_CODE.sub(lambda m: f"<code>{m.group(1)}</code>", out)
    out = _LINK.sub(lambda m: f'<a href="{html.escape(m.group(2), quote=True)}">{m.group(1)}</a>', out)
    out = _BOLD.sub(lambda m: f"<strong>{m.group(1)}</strong>", out)
    out = _ITALIC.sub(lambda m: f"<em>{m.group(1)}</em>", out)
    return out


def markdown_to_html(md: str) -> str:
    """Render the supported markdown subset to a .prose HTML fragment."""
    lines = md.replace("\r\n", "\n").split("\n")
    out: list[str] = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            i += 1
            continue
        if stripped == "---":
            out.append("<hr>")
            i += 1
            continue
        if stripped.startswith("### "):
            out.append(f"<h3>{_inline_md(stripped[4:].strip())}</h3>")
            i += 1
            continue
        if stripped.startswith("## "):
            out.append(f"<h2>{_inline_md(stripped[3:].strip())}</h2>")
            i += 1
            continue
        if stripped.startswith("> "):
            buf = []
            while i < n and lines[i].strip().startswith("> "):
                buf.append(lines[i].strip()[2:])
                i += 1
            out.append(f"<blockquote><p>{_inline_md(' '.join(buf))}</p></blockquote>")
            continue
        if re.match(r"^[-*] ", stripped):
            buf = []
            while i < n and re.match(r"^[-*] ", lines[i].strip()):
                buf.append(f"<li>{_inline_md(lines[i].strip()[2:])}</li>")
                i += 1
            out.append("<ul>" + "".join(buf) + "</ul>")
            continue
        if re.match(r"^\d+\. ", stripped):
            buf = []
            while i < n and re.match(r"^\d+\. ", lines[i].strip()):
                buf.append(f"<li>{_inline_md(re.sub(r'^\d+\. ', '', lines[i].strip()))}</li>")
                i += 1
            out.append("<ol>" + "".join(buf) + "</ol>")
            continue
        # paragraph: gather until a blank line
        buf = []
        while i < n and lines[i].strip():
            buf.append(lines[i].strip())
            i += 1
        out.append(f"<p>{_inline_md(' '.join(buf))}</p>")
    return "\n".join(out)


def load_body(slug: str) -> str:
    """The essay body fragment: body.html (verbatim) preferred, else body.md (rendered).

    The returned fragment goes inside `<div class="prose">…</div>`. Fail loud if
    neither exists — a blog.json entry with no body is an authoring error, not a
    silent empty page.
    """
    d = ESSAYS_DIR / slug
    html_path = d / "body.html"
    md_path = d / "body.md"
    if html_path.exists():
        return html_path.read_text(encoding="utf-8").rstrip("\n")
    if md_path.exists():
        return markdown_to_html(md_path.read_text(encoding="utf-8"))
    raise FileNotFoundError(f"essay '{slug}': no body.html or body.md under {d} — add the body fragment")


def _ld_json(post: dict, url: str, title: str, read_desc: str) -> str:
    author = post.get("author") or "Matt"
    ld = {
        "@context": "https://schema.org",
        "@type": "BlogPosting",
        "headline": title,
        "description": read_desc,
        "datePublished": post["date"],
        "author": {"@type": "Person", "name": author, "url": "https://averagejoematt.com/story/about/"},
        "image": f"https://averagejoematt.com/assets/images/{post.get('og_image') or 'og-home.png'}",
        "publisher": {
            "@type": "Organization",
            "name": "The Measured Life",
            "url": "https://averagejoematt.com",
            "logo": {"@type": "ImageObject", "url": "https://averagejoematt.com/apple-touch-icon.png"},
        },
        "mainEntityOfPage": {"@type": "WebPage", "@id": f"https://averagejoematt.com{url}"},
        "articleSection": post.get("article_section") or "Essays",
        "isPartOf": {"@type": "Blog", "name": "In My Own Words", "url": "https://averagejoematt.com/story/journal/"},
    }
    return json.dumps(ld, indent=2, ensure_ascii=False).replace("\n", "\n  ")


def render(post: dict) -> str:
    """Render ONE blog.json entry to its full permalink-page HTML string."""
    slug = slug_for(post)
    if not slug:
        raise ValueError(f"blog post {post.get('id')!r} has no resolvable slug (need url or id)")
    url = post.get("url") or f"/journal/essays/{slug}/"
    title = post["title"]
    excerpt = post.get("excerpt") or ""

    body = load_body(slug)

    # Fail-closed publish gate on everything reader-visible (ADR-104).
    for field, txt in (("title", title), ("excerpt", excerpt), ("body", body)):
        privacy_guard.assert_clean(txt, context=f"{slug}.{field}")

    label = post.get("label") or "Essay"
    author = post.get("author") or "Matt"
    series = post.get("series") or f"In My Own Words &middot; {_esc(label)} &middot; By {_esc(author)}"

    meta_desc = post.get("meta_desc") or excerpt
    og_title = post.get("og_title") or title
    og_desc = post.get("og_desc") or meta_desc
    twitter_desc = post.get("twitter_desc") or og_desc
    read_desc = post.get("schema_description") or og_desc

    stats = post.get("stats")
    stats_block = f'    <div class="post-header__stats">{_esc(stats)}</div>\n' if stats else ""

    cta = post.get("cta") or {}
    cta_title = cta.get("title") or "Follow the experiment"
    cta_body = cta.get("body") or (
        "The platform this essay describes publishes its own weekly chronicle — the data, "
        "the coaches, and what actually moved. The down weeks included."
    )
    cta_button = cta.get("button") or "Follow by email"
    cta_href = cta.get("href") or "/subscribe/"

    nav_prev = post.get("nav_prev") or {"href": "/story/journal/", "sub": "← In my own words", "label": "All of Matt's writing"}
    nav_next = post.get("nav_next") or {"href": "/story/", "sub": "The story", "label": "Back to the writing →"}

    return PAGE.format(
        title=_esc(title),
        meta_desc=_esc(meta_desc),
        url=url,
        og_title=_esc(og_title),
        og_desc=_esc(og_desc),
        twitter_desc=_esc(twitter_desc),
        og_image=_esc(post.get("og_image") or "og-home.png"),
        ld_json=_ld_json(post, url, title, read_desc),
        style=STYLE,
        head_chrome=v4_chrome.head_chrome(),
        doors_nav=v4_chrome.doors_nav(STORY_DOOR),
        series=series,
        date_human=_esc(human_date(post["date"])),
        read_minutes=read_minutes(post),
        stats_block=stats_block,
        body=body,
        cta_title=_esc(cta_title),
        cta_body=_esc(cta_body),
        cta_button=_esc(cta_button),
        cta_href=_esc(cta_href),
        nav_prev_href=_esc(nav_prev.get("href", "/story/journal/")),
        nav_prev_sub=_esc(nav_prev.get("sub", "← In my own words")),
        nav_prev_label=_esc(nav_prev.get("label", "All of Matt's writing")),
        nav_next_href=_esc(nav_next.get("href", "/story/")),
        nav_next_sub=_esc(nav_next.get("sub", "The story")),
        nav_next_label=_esc(nav_next.get("label", "Back to the writing →")),
        loop_forward=v4_chrome.loop_forward(STORY_DOOR, self_path=url),
        site_footer=v4_chrome.site_footer(),
    )


def load_posts() -> list[dict]:
    data = json.loads(BLOG_SRC.read_text(encoding="utf-8"))
    return [p for p in data.get("posts", []) if p.get("date") and p.get("title") and p.get("url")]


def build(write: bool, check: bool) -> int:
    posts = load_posts()
    if not posts:
        print("v4_build_journal: no essays in blog.json — nothing to render.")
        return 0

    stale: list[str] = []
    rendered = 0
    for post in posts:
        slug = slug_for(post)
        out_path = ESSAYS_DIR / slug / "index.html"
        html_text = render(post)
        current = out_path.read_text(encoding="utf-8") if out_path.exists() else None
        changed = current != html_text

        if check:
            if changed:
                stale.append(str(out_path.relative_to(_REPO)))
            continue
        if write:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(html_text, encoding="utf-8")
            print(f"  ✅ wrote {out_path.relative_to(_REPO)} ({len(html_text)} bytes)")
        else:
            state = "would UPDATE" if changed else "up to date"
            print(f"  · [dry-run] {out_path.relative_to(_REPO)} — {state} ({len(html_text)} bytes)")
        rendered += 1

    if check:
        if stale:
            print("❌ v4_build_journal --check: these essay pages are out of date (run --write):", file=sys.stderr)
            for s in stale:
                print(f"    {s}", file=sys.stderr)
            return 1
        print(f"✅ v4_build_journal --check: {len(posts)} essay page(s) up to date.")
        return 0

    if write:
        print(f"✅ v4_build_journal: wrote {rendered} essay page(s). RSS picks them up via v4_build_rss.py.")
    else:
        print(
            f"· v4_build_journal DRY-RUN: {rendered} essay page(s) previewed, nothing written. "
            "Re-run with --write to emit (publishing stays a manual deploy step)."
        )
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1] if __doc__ else None)
    ap.add_argument("--write", action="store_true", help="emit the permalink pages (default: dry-run, writes nothing)")
    ap.add_argument("--check", action="store_true", help="exit 1 if any essay page is out of date (CI drift gate)")
    args = ap.parse_args()
    return build(write=args.write, check=args.check)


if __name__ == "__main__":
    raise SystemExit(main())
