#!/usr/bin/env python3
"""
Life Platform — Demo Screenshot Obfuscation Pipeline
=====================================================
Reusable script for sanitising screenshots for demo/share purposes.

USAGE:
    python3 demo/obfuscate_pipeline.py

INPUT:   PNG/JPG files in life-platform/demo/raw/
OUTPUT:  Processed files in life-platform/demo/processed/

WORKFLOW:
  1. Drop new screenshots into demo/raw/
  2. Add redaction zones to REDACTIONS dict below (pixel coords)
  3. Run this script
  4. Processed images are ready for presentations, docs, etc.
  5. Source files in demo/raw/ are NEVER modified

FINDING PIXEL COORDINATES:
  - Open the screenshot in Preview (macOS): View → Show Inspector
  - Hover over the area to redact — coordinates shown in inspector
  - For @2x Retina screenshots, pixel coords = visual coords × 2
  - Use a generous box — better to over-redact than under-redact

REQUIREMENTS:
    pip install Pillow
"""

from PIL import Image, ImageDraw, ImageFont
import os, glob, shutil
from pathlib import Path

# ── Paths ────────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent
RAW_DIR    = SCRIPT_DIR / "raw"          # Source screenshots go here
OUT_DIR    = SCRIPT_DIR / "processed"   # Output lands here

RAW_DIR.mkdir(exist_ok=True)
OUT_DIR.mkdir(exist_ok=True)

# ── Redaction config ─────────────────────────────────────────────────────────
# Format: "filename_stem": [(x1, y1, x2, y2), ...]
# Each tuple defines one rectangular redaction box in PIXEL coordinates.
# Add as many boxes as needed per screenshot.
# Leave empty list [] to process without any redactions.
#
# CATEGORIES TO REDACT:
#   - AWS Account IDs (12-digit numbers in alarm emails, ARNs)
#   - Full legal names in formal clinical/document contexts
#   - Full ARNs (contain account ID + region)
#   - Real domain names if sensitive
#   - Job titles in AI coaching tooltips (personal context)
#
# LEAVE IN PLACE:
#   - Health data values (that's the whole point)
#   - First name in personal emails (context-appropriate)
#   - AI coaching content (demonstrates platform value)
#   - Error messages (shows operational maturity)

REDACTIONS = {
    # CloudWatch alarm email — AWS account ID + full ARN
    # Image: ~1864×528 (adjust if your screenshot differs)
    "shot09_alarm": [
        (100,  15, 1500, 75),   # Management console URL (contains account ID)
        (370, 350,  720, 380),  # "– AWS Account: 205930651321"
        (370, 390, 1200, 420),  # "– Alarm Arn: arn:aws:cloudwatch:..."
    ],

    # Habits deep-dive — "Senior Director" in tooltip text
    # Image: ~880×1542
    "shot05_habits": [
        (95, 308, 790, 332),    # Tooltip under "Deep Work Block"
        (95, 800, 790, 820),    # Tooltip under "Daytime Glasses"
    ],

    # Clinical summary — Patient full name
    # Image: ~1696×1530
    "shot17_clinical": [
        (140, 160, 530, 185),   # "Patient: [Full Name]"
    ],

    # Add new entries here as needed:
    # "new_screenshot": [
    #     (x1, y1, x2, y2),
    # ],
}

# ── Replacement labels (optional) ────────────────────────────────────────────
# After redacting, optionally draw replacement text over the box.
# Format: "filename_stem": [(x, y, "text", color_rgb)]
REPLACEMENTS = {
    "shot09_alarm": [
        (375, 353, "[account-id-redacted]", (100, 150, 140)),
        (375, 393, "[arn-redacted]",         (100, 150, 140)),
    ],
    "shot17_clinical": [
        (142, 162, "Demo User", (80, 120, 180)),
    ],
}

# ── Colours ───────────────────────────────────────────────────────────────────
BOX_FILL = (13, 25, 38)   # Dark navy — matches platform aesthetic


# ── Processing ────────────────────────────────────────────────────────────────
def process_screenshot(src_path: Path) -> Path:
    """Obfuscate one screenshot and return the output path."""
    stem = src_path.stem
    img = Image.open(src_path).convert("RGB")
    draw = ImageDraw.Draw(img)

    # Apply redaction boxes
    for (x1, y1, x2, y2) in REDACTIONS.get(stem, []):
        draw.rectangle([x1, y1, x2, y2], fill=BOX_FILL)

    # Apply replacement labels
    for (x, y, text, color) in REPLACEMENTS.get(stem, []):
        draw.text((x, y), text, fill=color)

    out_path = OUT_DIR / f"{stem}.png"
    img.save(out_path, "PNG", optimize=True)
    return out_path


def main():
    # Find all images in raw/
    sources = list(RAW_DIR.glob("*.png")) + list(RAW_DIR.glob("*.jpg")) + \
              list(RAW_DIR.glob("*.jpeg")) + list(RAW_DIR.glob("*.webp"))

    if not sources:
        print(f"No images found in {RAW_DIR}")
        print("Drop screenshot files into demo/raw/ and re-run.")
        return

    print(f"Processing {len(sources)} screenshot(s)...")
    redacted_count = 0

    for src in sorted(sources):
        out = process_screenshot(src)
        had_redactions = src.stem in REDACTIONS
        label = "✓ REDACTED" if had_redactions else "✓ copied"
        print(f"  {label}: {src.name} → {out.name}")
        if had_redactions:
            redacted_count += 1

    print(f"\nDone. {len(sources)} processed ({redacted_count} with redactions).")
    print(f"Output: {OUT_DIR}")


if __name__ == "__main__":
    main()
