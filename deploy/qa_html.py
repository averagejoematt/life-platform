#!/usr/bin/env python3
"""
qa_html.py — Pre-deploy HTML quality assurance for averagejoematt.com

Runs against LOCAL site/ files. Catches structural and consistency bugs
BEFORE they reach S3. This is the step that was missing from the Sprint 10
expert review.

Usage:
    python3 deploy/qa_html.py           # audit all pages, print report
    python3 deploy/qa_html.py --fail    # exit 1 if any errors found (for CI)

What it checks:
  - CSS/JS assets linked on every page exist on disk
  - nav-overlay HTML present and has correct class (position:fixed hides it)
  - Footer-v2 present and contains expected links
  - Meta tags (og:title, og:description, og:image, twitter:card) present
  - <title> not empty / not placeholder
  - No placeholder text ("TODO", "Coming soon", "PLACEHOLDER")
  - Internal hrefs point to pages that exist on disk
  - No duplicate <title> across pages
  - <html lang> present
  - viewport meta present
  - RSS link in <head> present
  - No /biology/ links in nav-overlay or footer (removed Sprint 10)
"""

import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

SITE_DIR = Path(__file__).parent.parent / "site"
ERRORS = []
WARNINGS = []
PASS_COUNT = 0


def error(page: str, msg: str):
    ERRORS.append(f"  ❌  {page}: {msg}")


def warn(page: str, msg: str):
    WARNINGS.append(f"  ⚠️  {page}: {msg}")


def ok():
    global PASS_COUNT
    PASS_COUNT += 1


def check_page(html_path: Path):
    rel = str(html_path.relative_to(SITE_DIR))
    try:
        content = html_path.read_text(encoding="utf-8")
    except Exception as e:
        error(rel, f"Cannot read file: {e}")
        return

    # Skip deep checks on redirect-only pages (meta http-equiv refresh)
    # They intentionally have no nav, OG tags, RSS, etc.
    if 'http-equiv="refresh"' in content or "http-equiv='refresh'" in content:
        ok()  # count as pass
        return

    # ── 1. DOCTYPE and basic structure
    if "<!DOCTYPE html>" not in content and "<!doctype html>" not in content:
        error(rel, "Missing DOCTYPE")
    else:
        ok()

    # ── 2. <html lang>
    if not re.search(r'<html[^>]+lang=', content):
        warn(rel, "Missing lang attribute on <html>")
    else:
        ok()

    # ── 3. viewport meta
    if 'name="viewport"' not in content:
        error(rel, "Missing viewport meta tag")
    else:
        ok()

    # ── 4. <title> not empty or placeholder
    title_match = re.search(r'<title>([^<]*)</title>', content)
    if not title_match:
        error(rel, "Missing <title>")
    elif not title_match.group(1).strip():
        error(rel, "<title> is empty")
    elif "TODO" in title_match.group(1) or "PLACEHOLDER" in title_match.group(1):
        error(rel, f"<title> has placeholder text: {title_match.group(1)!r}")
    else:
        ok()

    # ── 5. OG tags
    for tag in ["og:title", "og:description", "og:image"]:
        if f'property="{tag}"' not in content:
            warn(rel, f"Missing <meta property=\"{tag}\">")
        else:
            ok()

    # ── 6. Twitter card
    if 'name="twitter:card"' not in content:
        warn(rel, "Missing twitter:card meta tag")
    else:
        ok()

    # ── 7. RSS link in <head>
    if 'rel="alternate"' not in content or 'rss' not in content.lower():
        warn(rel, "Missing RSS <link> in <head>")
    else:
        ok()

    # ── 8. CSS assets linked and exist on disk
    css_links = re.findall(r'<link[^>]+href="(/assets/[^"]+\.css)"', content)
    for css_href in css_links:
        css_path = SITE_DIR / css_href.lstrip("/")
        if not css_path.exists():
            error(rel, f"CSS not found on disk: {css_href}")
        else:
            ok()

    # ── 9. JS assets linked and exist on disk
    js_links = re.findall(r'<script[^>]+src="(/assets/[^"]+\.js)"', content)
    for js_href in js_links:
        js_path = SITE_DIR / js_href.lstrip("/")
        if not js_path.exists():
            error(rel, f"JS not found on disk: {js_href}")
        else:
            ok()

    # ── 10. nav correct and consistent (Sprint 8+)
    if 'nav__hamburger' not in content:
        error(rel, "nav__hamburger button missing — mobile menu broken (fix_site_meta.py may have overwritten it)")
    else:
        ok()
    if 'href="/#experiment"' in content:
        error(rel, "Old nav links detected (/#experiment) — nav not updated to Sprint 8 Story/Live/Journal/Platform")
    else:
        ok()
    # Phase 1 IA: top nav must use 5-section dropdown (nav__dropdown-btn)
    if 'nav__dropdown-btn' not in content:
        error(rel, "Nav missing dropdown buttons — not Phase 1 IA nav")
    else:
        ok()
    # Phase 1 IA: Chronicle must be in nav (replaced Journal)
    if 'href="/chronicle/"' not in content:
        warn(rel, "Nav/footer missing /chronicle/ link — check Phase 1 IA nav deploy")
    else:
        ok()

    # ── 11. FOUC guard: inline <style> must hide overlay before external CSS loads
    if '.nav-overlay{display:none}' not in content:
        error(rel, "FOUC guard missing — add <style>.nav-overlay{display:none}</style> after <meta charset> "
                   "(without it, overlay renders as unstyled text before base.css loads)")
    else:
        ok()

    # ── 11b. nav-overlay present and has correct class
    if 'class="nav-overlay"' not in content:
        error(rel, "nav-overlay div missing — overlay will not work")
    else:
        ok()
        # Check overlay is not open by default (no is-open class at load time)
        if 'class="nav-overlay is-open"' in content or 'class="nav-overlay  is-open"' in content:
            error(rel, "nav-overlay has is-open class by default — overlay will be visible on load!")

    # ── 11. Footer-v2 present, structurally complete, and has key links
    if 'class="footer-v2"' not in content:
        error(rel, "footer-v2 missing — footer broken (wrong version or stripped)")
    else:
        ok()
        # footer-v2__grid must be present (without it, CSS grid has nothing to target)
        if 'class="footer-v2__grid"' not in content:
            error(rel, "footer-v2__grid div missing — footer will render as unstyled block")
        else:
            ok()
        # At least one footer-v2__col must be present
        col_count = content.count('class="footer-v2__col"')
        if col_count == 0:
            error(rel, "footer-v2__col missing — footer columns not present")
        elif col_count < 3:
            warn(rel, f"Only {col_count} footer-v2__col elements — expected 4")
        else:
            ok()
        # Footer should NOT include /biology/
        footer_match = re.search(r'<footer[^>]*class="footer-v2"[^>]*>(.+?)</footer>', content, re.DOTALL)
        if footer_match:
            footer_html = footer_match.group(1)
            if '/biology/' in footer_html:
                error(rel, "Footer still contains /biology/ link (should be removed per Sprint 10)")
            else:
                ok()

    # ── 12. nav-overlay should NOT contain /biology/
    overlay_match = re.search(r'class="nav-overlay"(.+?)(?=<header|<main|<section|<div class="(?:story|page|live|journal)-)', content, re.DOTALL)
    if overlay_match and '/biology/' in overlay_match.group(1):
        error(rel, "nav-overlay still contains /biology/ link (should be removed per Sprint 10)")
    elif overlay_match:
        ok()

    # ── 13. Wrong asset paths (common copy-paste errors)
    if "'/site/public_stats.json'" in content or '"/site/public_stats.json"' in content:
        error(rel, "Wrong path: '/site/public_stats.json' should be '/public_stats.json' (S3 prefix leaking)")
    else:
        ok()

    if "lxhjl2qvq2ystwp47464uhs2jti0hpdcq.lambda-url" in content:
        error(rel, "Raw Lambda URL used instead of /api/current_challenge — CORS error in browser")
    else:
        ok()

    # ── 14. No placeholder text in body
    placeholder_patterns = [
        (r'\[COMING SOON\]', "placeholder '[COMING SOON]' text in body"),
        (r'\[TODO\]', "placeholder '[TODO]' text in body"),
        (r'Lorem ipsum', "Lorem ipsum placeholder text"),
        (r'href="#"(?!\s*class)', "bare href=\"#\" links (unimplemented)"),
    ]
    # Only check body content (strip head)
    body_match = re.search(r'<body[^>]*>(.+)', content, re.DOTALL)
    body = body_match.group(1) if body_match else content
    for pattern, msg in placeholder_patterns:
        if re.search(pattern, body, re.IGNORECASE):
            warn(rel, msg)

    # ── 14. Internal links point to existing pages
    internal_links = re.findall(r'href="(/[a-z0-9/_-]+/)"', content)
    for href in set(internal_links):
        # Skip API, external, anchor-only
        if href.startswith("/api/") or href.startswith("//"):
            continue
        target = SITE_DIR / href.lstrip("/")
        # Expect either target/index.html or target.html
        index_path = target / "index.html"
        html_path_direct = SITE_DIR / (href.strip("/") + ".html")
        if not index_path.exists() and not html_path_direct.exists():
            warn(rel, f"Internal link may be broken: {href} (no index.html found)")

    # ── 15. Base CSS and tokens loaded (order matters)
    if '/assets/css/tokens.css' not in content:
        error(rel, "tokens.css not linked — design tokens missing")
    else:
        ok()
    if '/assets/css/base.css' not in content:
        error(rel, "base.css not linked — global styles missing")
    else:
        ok()

    # ── 16. nav.js loaded (required for back-to-top, hamburger, etc.)
    if '/assets/js/nav.js' not in content:
        warn(rel, "nav.js not linked — hamburger/overlay/back-to-top will not work")
    else:
        ok()


def check_css_validity():
    """Basic structural check on base.css."""
    base_css = SITE_DIR / "assets" / "css" / "base.css"
    if not base_css.exists():
        error("assets/css/base.css", "File not found!")
        return

    content = base_css.read_text()

    # Brace balance
    opens = content.count("{")
    closes = content.count("}")
    if opens != closes:
        error("base.css", f"Unbalanced braces: {opens} open, {closes} close — CSS parse error!")
    else:
        ok()

    # Critical rules must be present
    critical_rules = [
        (".nav-overlay",          "position: fixed",   "overlay must be fixed-positioned"),
        (".nav-overlay",          "opacity: 0",        "overlay must be invisible by default"),
        (".nav-overlay",          "display: none",     "FOUC guard: overlay must have display:none so it is hidden before CSS loads"),
        (".nav-overlay.is-open",  "opacity: 1",        "overlay must be visible when open"),
        (".nav-overlay.is-open",  "display: flex",     "overlay must switch to display:flex when opened"),
        (".footer-v2",            None,                "footer-v2 must be styled"),
        (".pulse",                "var(--c-green-500)", "pulse must use green-500 (not accent var which turns amber on journal pages)"),
        (".reading-path",         None,                "GAM-02 reading-path component must be defined"),
        (".bottom-nav__link.has-badge", None,          "GAM-01 badge dot must be defined"),
        (".back-to-top",          None,                "back-to-top button must be styled (U07)"),
    ]
    for selector, prop, reason in critical_rules:
        if selector not in content:
            error("base.css", f"Missing rule: {selector} — {reason}")
        elif prop and prop not in content:
            error("base.css", f"Rule {selector!r} missing {prop!r} — {reason}")
        else:
            ok()


def check_consistency():
    """Cross-page consistency checks."""
    all_titles = {}
    all_pages = list(SITE_DIR.rglob("index.html"))

    # Pages where duplicate titles are expected and acceptable:
    # - redirect pages (meta http-equiv refresh) — intentionally share generic titles
    # - journal/posts mirror chronicle/posts (same content at two URLs during transition)
    SKIP_DUPLICATE_CHECK = {
        "journal/index.html",
        "journal/archive/index.html",
        "journal/sample/index.html",
        "results/index.html",
        "progress/index.html",
        "achievements/index.html",
        "start/index.html",
    }
    # Also skip all journal/posts/* (they mirror chronicle/posts/*)
    for page in all_pages:
        rel = str(page.relative_to(SITE_DIR))
        if rel in SKIP_DUPLICATE_CHECK or rel.startswith("journal/posts/"):
            continue
        content = page.read_text(encoding="utf-8", errors="ignore")
        # Skip redirect pages (any page with meta http-equiv refresh)
        if 'http-equiv="refresh"' in content or "http-equiv='refresh'" in content:
            continue
        title_match = re.search(r'<title>([^<]+)</title>', content)
        if title_match:
            title = title_match.group(1).strip()
            if title in all_titles:
                warn(rel, f"Duplicate <title> with {all_titles[title]!r}: {title!r}")
            else:
                all_titles[title] = rel
                ok()


def main():
    fail_mode = "--fail" in sys.argv

    print("=" * 60)
    print("averagejoematt.com — Pre-deploy HTML QA")
    print("=" * 60)
    print()

    # CSS validity first — if CSS is broken, everything else is suspect
    print("── CSS sanity check ──────────────────────────────")
    check_css_validity()
    print()

    # Check all HTML pages
    pages = sorted(SITE_DIR.rglob("index.html"))
    # Also check non-index HTML (subscribe.html, 404.html, etc.)
    pages += sorted(p for p in SITE_DIR.rglob("*.html") if p.name != "index.html" and "posts" not in str(p))

    print(f"── Checking {len(pages)} HTML pages ─────────────────────")
    for page in pages:
        check_page(page)
    print()

    # Cross-page consistency
    print("── Cross-page consistency ─────────────────────────")
    check_consistency()
    print()

    # Report
    print("=" * 60)
    print(f"PASS: {PASS_COUNT} checks")
    if ERRORS:
        print(f"\nERRORS ({len(ERRORS)}) — must fix before deploy:")
        for e in ERRORS:
            print(e)
    if WARNINGS:
        print(f"\nWARNINGS ({len(WARNINGS)}) — review before deploy:")
        for w in WARNINGS:
            print(w)
    if not ERRORS and not WARNINGS:
        print("\n✅ All checks passed — safe to deploy.")
    elif not ERRORS:
        print(f"\n✅ No errors. {len(WARNINGS)} warnings to review.")
    else:
        print(f"\n❌ {len(ERRORS)} error(s) must be fixed before deploying.")

    print("=" * 60)

    if fail_mode and ERRORS:
        sys.exit(1)


if __name__ == "__main__":
    main()
