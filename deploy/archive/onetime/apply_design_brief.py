#!/usr/bin/env python3
"""
apply_design_brief.py — Apply Signal Doctrine Tier 1 changes to remaining pages
Design Brief: body-signal class, breadcrumbs, reading-path-v2, animations.js

Run from project root:
  python3 deploy/apply_design_brief.py --dry-run    # preview
  python3 deploy/apply_design_brief.py               # apply
"""
import os
import re
import sys
import argparse

PROJECT_ROOT = os.path.expanduser("~/Documents/Claude/life-platform")
SITE_DIR = os.path.join(PROJECT_ROOT, "site")

# ── Page reading order (linear sequence through the site) ──
READING_ORDER = [
    ("/",             "Home"),
    ("/story/",       "The Story"),
    ("/about/",       "The Mission"),
    ("/live/",        "The Pulse"),
    ("/character/",   "Character"),
    ("/habits/",      "The OS"),
    ("/sleep/",       "Sleep"),
    ("/glucose/",     "Glucose"),
    ("/benchmarks/",  "Benchmarks"),
    ("/explorer/",    "Data Explorer"),
    ("/protocols/",   "Protocols"),
    ("/supplements/", "The Pharmacy"),
    ("/experiments/", "The Lab"),
    ("/challenges/",  "The Arena"),
    ("/discoveries/", "Discoveries"),
    ("/platform/",    "Platform"),
    ("/intelligence/","The AI"),
    ("/subscribe/",   "Subscribe"),
]

# ── Pages to apply body-signal + animations.js ──
SIGNAL_PAGES = [
    "sleep", "glucose", "supplements", "habits", "benchmarks",
    "protocols", "platform", "intelligence", "challenges",
    "experiments", "explorer",
]

# ── Section mapping for breadcrumbs ──
SECTION_MAP = {
    "/sleep/":       ("Evidence", "Sleep Observatory"),
    "/glucose/":     ("Evidence", "Glucose Observatory"),
    "/supplements/": ("Method",   "The Pharmacy"),
    "/habits/":      ("Pulse",    "The Operating System"),
    "/benchmarks/":  ("Evidence", "Benchmarks"),
    "/protocols/":   ("Method",   "Protocols"),
    "/platform/":    ("Build",    "Platform"),
    "/intelligence/":("Build",    "The AI"),
    "/challenges/":  ("Method",   "The Arena"),
    "/experiments/": ("Method",   "The Lab"),
    "/explorer/":    ("Evidence", "Data Explorer"),
}


def get_reading_neighbors(page_path):
    for i, (path, title) in enumerate(READING_ORDER):
        if path == page_path:
            prev_item = READING_ORDER[i - 1] if i > 0 else None
            next_item = READING_ORDER[i + 1] if i < len(READING_ORDER) - 1 else None
            return prev_item, next_item
    return None, None


def make_breadcrumb_html(page_path):
    info = SECTION_MAP.get(page_path)
    if not info:
        return ""
    section, page_title = info
    return (
        f'<nav class="breadcrumb" aria-label="Breadcrumb">'
        f'<a href="/" class="breadcrumb__section">Home</a>'
        f'<span class="breadcrumb__sep">\u203a</span>'
        f'<span class="breadcrumb__section">{section}</span>'
        f'<span class="breadcrumb__sep">\u203a</span>'
        f'<span class="breadcrumb__current">{page_title}</span>'
        f'</nav>'
    )


def make_reading_path_html(page_path):
    prev_item, next_item = get_reading_neighbors(page_path)
    if not prev_item and not next_item:
        return ""

    html = '<nav class="reading-path-v2">\n'
    if prev_item:
        html += (
            f'  <a href="{prev_item[0]}" class="reading-path-v2__link">\n'
            f'    <span class="reading-path-v2__dir">\u2190 Previous</span>\n'
            f'    <span class="reading-path-v2__title">{prev_item[1]}</span>\n'
            f'  </a>\n'
        )
    else:
        html += '  <div></div>\n'
    if next_item:
        html += (
            f'  <a href="{next_item[0]}" class="reading-path-v2__link reading-path-v2__link--next">\n'
            f'    <span class="reading-path-v2__dir">Next \u2192</span>\n'
            f'    <span class="reading-path-v2__title">{next_item[1]}</span>\n'
            f'  </a>\n'
        )
    else:
        html += '  <div></div>\n'
    html += '</nav>'
    return html


def apply_to_page(page_slug, dry_run=False):
    page_path = f"/{page_slug}/"
    filepath = os.path.join(SITE_DIR, page_slug, "index.html")

    if not os.path.exists(filepath):
        print(f"  \u26a0 SKIP {page_slug}: file not found")
        return False

    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    original = content
    changes = []

    # 1. Add body-signal class to <body>
    if "body-signal" not in content:
        body_match = re.search(r'<body([^>]*)>', content)
        if body_match:
            attrs = body_match.group(1)
            if 'class="' in attrs:
                content = content.replace(
                    body_match.group(0),
                    body_match.group(0).replace('class="', 'class="body-signal '),
                )
            else:
                content = content.replace(
                    body_match.group(0),
                    f'<body class="body-signal"{attrs}>',
                )
            changes.append("body-signal")

    # 2. Add breadcrumb after <div id="amj-nav"></div>
    if "breadcrumb" not in content:
        breadcrumb = make_breadcrumb_html(page_path)
        if breadcrumb:
            nav_marker = '<div id="amj-nav"></div>'
            if nav_marker in content:
                content = content.replace(
                    nav_marker,
                    nav_marker + "\n\n" + breadcrumb,
                )
                changes.append("breadcrumb")

    # 3. Add reading-path-v2 before subscribe/footer
    if "reading-path-v2" not in content:
        rp_html = make_reading_path_html(page_path)
        if rp_html:
            for marker in [
                '<div id="amj-subscribe">',
                '<div id="amj-bottom-nav">',
                '<div id="amj-footer">',
            ]:
                if marker in content:
                    content = content.replace(
                        marker,
                        rp_html + "\n\n" + marker,
                    )
                    changes.append("reading-path-v2")
                    break

    # 4. Add animations.js before </body>
    if "animations.js" not in content:
        content = content.replace(
            "</body>",
            '<script src="/assets/js/animations.js" defer></script>\n</body>',
        )
        changes.append("animations.js")

    if content != original:
        if dry_run:
            print(f"  \u2713 {page_slug}: would apply [{', '.join(changes)}]")
        else:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)
            print(f"  \u2713 {page_slug}: applied [{', '.join(changes)}]")
        return True
    else:
        print(f"  \u00b7 {page_slug}: already up to date")
        return False


def main():
    parser = argparse.ArgumentParser(description="Apply Design Brief Tier 1 changes")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without writing")
    args = parser.parse_args()

    mode = "DRY RUN" if args.dry_run else "APPLYING"
    print(f"\n\u2550\u2550\u2550 Design Brief Tier 1 \u2014 {mode} \u2550\u2550\u2550\n")
    print(f"Target pages: {', '.join(SIGNAL_PAGES)}\n")

    changed = 0
    for slug in SIGNAL_PAGES:
        if apply_to_page(slug, dry_run=args.dry_run):
            changed += 1

    print(f"\n{'Would change' if args.dry_run else 'Changed'}: {changed}/{len(SIGNAL_PAGES)} pages")

    if not args.dry_run and changed > 0:
        print("\n\u2550\u2550\u2550 Next: Deploy to S3 \u2550\u2550\u2550")
        print("  aws s3 sync site/ s3://matthew-life-platform/site/ --region us-west-2 --exclude '.DS_Store'")
        print("  aws cloudfront create-invalidation --distribution-id E3S424OXQZ8NBE \\")
        print("    --paths '/*' --region us-east-1")


if __name__ == "__main__":
    main()
