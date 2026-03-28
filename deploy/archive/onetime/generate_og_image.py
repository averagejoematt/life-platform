#!/usr/bin/env python3
"""
generate_og_image.py — Generate the OG social preview image for averagejoematt.com.

Reads current stats from public_stats.json and bakes them into a 1200x630 PNG.
Requires: pip install Pillow

Usage:
  python3 deploy/generate_og_image.py                   # use local data/public_stats.json
  python3 deploy/generate_og_image.py --from-s3         # pull latest from S3 first

Output: site/assets/images/og-image.png
"""

import json
import argparse
import subprocess
import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("✗ Pillow not installed. Run: pip3 install Pillow")
    sys.exit(1)

ROOT = Path(__file__).resolve().parent.parent
STATS_FILE = ROOT / "site" / "data" / "public_stats.json"
OUTPUT = ROOT / "site" / "assets" / "images" / "og-image.png"

W, H = 1200, 630

# Colors from tokens.css
BG           = (8, 12, 10)        # #080c0a
ACCENT       = (0, 229, 160)      # #00e5a0
TEXT_PRIMARY  = (232, 237, 233)    # #e8ede9
TEXT_MUTED    = (122, 144, 128)    # #7a9080
AMBER        = (240, 180, 41)     # #F0B429
SURFACE      = (14, 21, 16)       # #0e1510


def load_font(name, size):
    """Try common font paths, fall back to default."""
    candidates = [
        f"/usr/share/fonts/truetype/dejavu/{name}.ttf",
        f"/System/Library/Fonts/Supplemental/{name}.ttf",
        f"/Library/Fonts/{name}.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except (OSError, IOError):
            continue
    # macOS system fonts
    mac_map = {
        "DejaVuSans-Bold": "/System/Library/Fonts/Helvetica.ttc",
        "DejaVuSansMono": "/System/Library/Fonts/Menlo.ttc",
    }
    if name in mac_map:
        try:
            return ImageFont.truetype(mac_map[name], size)
        except (OSError, IOError):
            pass
    return ImageFont.load_default()


def generate(stats: dict):
    v = stats.get("vitals", {})
    j = stats.get("journey", {})
    p = stats.get("platform", {})
    hero = stats.get("hero", {})

    weight = hero.get("current_weight_lbs") or j.get("current_weight_lbs") or v.get("weight_lbs", 0)
    progress = hero.get("progress_pct") or j.get("progress_pct", 0)
    tools = p.get("mcp_tools", 95)
    sources = p.get("data_sources", 19)

    font_large = load_font("DejaVuSans-Bold", 64)
    font_med   = load_font("DejaVuSansMono", 24)
    font_sm    = load_font("DejaVuSansMono", 18)
    font_xs    = load_font("DejaVuSansMono", 14)

    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    # Top accent line
    draw.line([(0, 0), (W, 0)], fill=ACCENT, width=3)

    # Kicker
    draw.text((60, 50), "SIGNAL / HUMAN SYSTEMS", fill=ACCENT, font=font_xs)

    # Headline with current weight
    weight_str = f"302 → {weight:.0f} → 185" if weight else "302 → 185"
    draw.text((60, 130), weight_str, fill=TEXT_PRIMARY, font=font_large)

    # Subtitle
    draw.text((60, 220), "One person. 19 data sources. Every number public.", fill=TEXT_MUTED, font=font_med)

    # Divider
    draw.line([(60, 290), (W - 60, 290)], fill=(*ACCENT[:3], 40), width=1)

    # Stats
    stat_items = [
        ("DATA SOURCES", str(sources)),
        ("AI TOOLS", str(tools)),
        ("COST/MONTH", "$10"),
        ("PROGRESS", f"{progress:.0f}%"),
    ]
    box_y = 320
    box_w = 200
    for i, (label, value) in enumerate(stat_items):
        x = 60 + i * (box_w + 50)
        draw.text((x, box_y), label, fill=TEXT_MUTED, font=font_xs)
        draw.text((x, box_y + 24), value, fill=ACCENT, font=font_med)

    # Tagline
    draw.text((60, 470), "Built by a non-engineer with Claude as the", fill=TEXT_MUTED, font=font_sm)
    draw.text((60, 498), "engineering partner. Every failure included.", fill=TEXT_MUTED, font=font_sm)

    # Domain
    draw.text((W - 300, H - 50), "averagejoematt.com", fill=AMBER, font=font_sm)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUTPUT)
    print(f"✓ OG image saved: {OUTPUT.relative_to(ROOT)}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--from-s3", action="store_true")
    args = parser.parse_args()

    if args.from_s3:
        print("  ↓ Pulling latest stats from S3...")
        subprocess.run([
            "aws", "s3", "cp",
            "s3://matthew-life-platform/site/data/public_stats.json",
            str(STATS_FILE),
            "--region", "us-west-2",
        ], check=True)

    if not STATS_FILE.exists():
        print(f"✗ {STATS_FILE} not found. Run with --from-s3 or ensure file exists.")
        sys.exit(1)

    with open(STATS_FILE) as f:
        stats = json.load(f)

    generate(stats)


if __name__ == "__main__":
    main()
