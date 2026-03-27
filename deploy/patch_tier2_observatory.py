#!/usr/bin/env python3
"""
patch_tier2_observatory.py — Add --obs-accent pillar colors to observatory pages.
Idempotent: checks for existing --obs-accent before adding.

Maps:
  sleep    → --pillar-sleep    (#818cf8)
  glucose  → --pillar-nutrition (#f59e0b)
  nutrition → --pillar-nutrition (#f59e0b)
  training → --pillar-movement  (#3ecf8e)
  mind     → --pillar-mind      (#a78bfa)
"""
import os, re, sys

SITE = os.path.expanduser("~/Documents/Claude/life-platform/site")

PAGES = {
    "sleep":     ("--pillar-sleep",     "#818cf8"),
    "glucose":   ("--pillar-nutrition", "#f59e0b"),
    "nutrition": ("--pillar-nutrition", "#f59e0b"),
    "training":  ("--pillar-movement",  "#3ecf8e"),
    "mind":      ("--pillar-mind",      "#a78bfa"),
}

CSS_BLOCK = """
    /* DB-03: Observatory pillar accent */
    :root {{
      --obs-accent: var({token});
      --obs-accent-dim: {hex}66;
      --obs-accent-bg: {hex}18;
    }}
    .s-hero__eyebrow, .eyebrow {{ color: var(--obs-accent) !important; }}
    .detail-card {{ border-left-color: var(--obs-accent); }}
"""

patched = 0
skipped = 0

for page, (token, hex_val) in PAGES.items():
    fpath = os.path.join(SITE, page, "index.html")
    if not os.path.isfile(fpath):
        print(f"  SKIP: {fpath} not found")
        skipped += 1
        continue

    with open(fpath, "r") as f:
        content = f.read()

    if "--obs-accent" in content:
        print(f"  SKIP: {page}/index.html already has --obs-accent")
        skipped += 1
        continue

    css = CSS_BLOCK.format(token=token, hex=hex_val)

    # Insert CSS block right after the opening <style> tag (after the first :root block)
    # Strategy: insert after the first closing </style> or before the first custom :root
    # Best: insert before the closing </head> inside a new <style> block
    insertion = f"\n  <style>{css}  </style>\n"
    content = content.replace("</head>", insertion + "</head>", 1)

    with open(fpath, "w") as f:
        f.write(content)

    print(f"  DONE: {page}/index.html — --obs-accent: var({token})")
    patched += 1

print(f"\nObservatory accents: {patched} patched, {skipped} skipped")
