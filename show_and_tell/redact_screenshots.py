#!/usr/bin/env python3
"""
show_and_tell/redact_screenshots.py

Applies a fixed, documented set of redaction rules to raw screenshots.
Input:  show_and_tell/screenshots/*.png   (raw, unredacted)
Output: show_and_tell/processed/*.png     (ready for PDF)

Each rule is documented so future runs know WHY it exists.
Add new rules at the bottom — never delete old ones (just disable with enabled=False).

Run after capture_screenshots.py:
  python3 redact_screenshots.py

Or selectively:
  python3 redact_screenshots.py shot02_daily_brief
"""

import sys
import os
from pathlib import Path
from PIL import Image, ImageDraw
import shutil

SRC = Path(__file__).parent / "screenshots"
OUT = Path(__file__).parent / "processed"
OUT.mkdir(exist_ok=True)

# ── Background colours used across screenshots ───────────────────────────────
BG_DARK  = (18, 28, 42)    # dark navy — matches dashboard background
BG_LIGHT = (245, 244, 242) # light beige — matches email background
BG_CARD  = (20, 30, 46)    # card background


def redact(img, x1, y1, x2, y2, fill, label=None, label_color=(60, 80, 100)):
    """Draw a solid redaction box. Optionally add a replacement label."""
    draw = ImageDraw.Draw(img)
    draw.rectangle([x1, y1, x2, y2], fill=fill)
    if label:
        cx = (x1 + x2) // 2
        cy = (y1 + y2) // 2
        draw.text((cx - len(label)*3, cy - 6), label, fill=label_color)
    return img


# ══════════════════════════════════════════════════════════════════════════════
# REDACTION RULES
# Format: (shot_name, x1_frac, y1_frac, x2_frac, y2_frac, fill, label, reason)
# Coordinates as FRACTIONS of image size (0.0–1.0) so they're resolution-independent.
# ══════════════════════════════════════════════════════════════════════════════
RULES = [
    # ── shot02_daily_brief ──────────────────────────────────────────────────
    # The habit streaks red-text line shows: "No marijuana · No alcohol · ..."
    # It sits at roughly the 69% vertical mark in the 1272px image
    {
        "shot": "shot02_daily_brief",
        "y_frac": (0.688, 0.727),   # y=875–925 in 1272px image
        "x_frac": (0.0, 1.0),
        "fill": BG_DARK,
        "label": "✓  Habit streaks tracked",
        "reason": "Reveals personal habits (no marijuana, no alcohol) not appropriate for work audience",
        "enabled": True,
    },

    # ── shot05_habits ───────────────────────────────────────────────────────
    # No alcohol row — appears as ~row 3 in Tier 0 non-negotiable list
    {
        "shot": "shot05_habits",
        "y_frac": (0.072, 0.095),
        "x_frac": (0.0, 1.0),
        "fill": BG_DARK,
        "label": None,
        "reason": "Reveals 'No alcohol' habit",
        "enabled": True,
    },
    # No marijuana row — appears just below No alcohol
    {
        "shot": "shot05_habits",
        "y_frac": (0.123, 0.148),
        "x_frac": (0.0, 1.0),
        "fill": BG_DARK,
        "label": None,
        "reason": "Reveals 'No marijuana' habit",
        "enabled": True,
    },
    # No porn row + subtext — appears in middle of Tier 1 list
    {
        "shot": "shot05_habits",
        "y_frac": (0.582, 0.620),
        "x_frac": (0.0, 1.0),
        "fill": BG_DARK,
        "label": None,
        "reason": "Reveals 'No porn' habit — dopamine hygiene protocol, private",
        "enabled": True,
    },
    # Body Skincare subtext mentioning specific weight in lbs
    {
        "shot": "shot05_habits",
        "y_frac": (0.820, 0.837),
        "x_frac": (0.0, 1.0),
        "fill": BG_DARK,
        "label": None,
        "reason": "Subtext mentions specific body weight in lbs",
        "enabled": True,
    },
    # Walk 5k subtext mentioning "at your current weight"
    {
        "shot": "shot05_habits",
        "y_frac": (0.166, 0.185),
        "x_frac": (0.02, 0.85),
        "fill": BG_DARK,
        "label": None,
        "reason": "Subtext references current weight",
        "enabled": True,
    },

    # ── shot06_cgm_board ────────────────────────────────────────────────────
    # Weight Phase Tracker section — shows exact weight in lbs, start/goal weights
    {
        "shot": "shot06_cgm_board",
        "y_frac": (0.440, 0.506),
        "x_frac": (0.02, 0.98),
        "fill": BG_CARD,
        "label": "Weight tracking in progress — trending in the right direction",
        "reason": "Shows exact body weight (290.3 lbs), start weight (302 lbs), goal weight (185 lbs)",
        "enabled": True,
    },
    # Phase line: "Phase: Ignition · target 250 lbs"
    {
        "shot": "shot06_cgm_board",
        "y_frac": (0.490, 0.508),
        "x_frac": (0.02, 0.80),
        "fill": BG_CARD,
        "label": None,
        "reason": "Shows target weight",
        "enabled": True,
    },

    # ── shot16_dashboard ────────────────────────────────────────────────────
    # Weight tile (top-right of 2x2 metric grid) — shows exact weight
    {
        "shot": "shot16_dashboard",
        "y_frac": (0.284, 0.400),
        "x_frac": (0.450, 0.810),
        "fill": (22, 32, 48),
        "label": "On track ↗",
        "reason": "Shows exact body weight (290.3 lbs) and weekly change",
        "enabled": True,
    },

    # ── shot18_dashboard_character ──────────────────────────────────────────
    # Same weight tile as shot16 (identical layout)
    {
        "shot": "shot18_dashboard_character",
        "y_frac": (0.284, 0.400),
        "x_frac": (0.450, 0.810),
        "fill": (22, 32, 48),
        "label": "On track ↗",
        "reason": "Same weight tile as shot16",
        "enabled": True,
    },

    # ── shot07_brittany1 ────────────────────────────────────────────────────
    # Coach Rodriguez section from "What's driving it" onward:
    # "not quite calm, not quite joy, but the relief of feeling in control"
    # "he may be doing well on paper without fully feeling well inside"
    {
        "shot": "shot07_brittany1",
        "y_frac": (0.690, 1.0),
        "x_frac": (0.0, 1.0),
        "fill": BG_LIGHT,
        "label": None,
        "reason": "Contains emotionally vulnerable content inappropriate for manager/delegate audience. Redact and replace with neutral description.",
        "enabled": True,
        "post_label": ("Coach Rodriguez reflects on Matthew's week —\nconsistency, momentum, and areas to watch.\n\n[AI-generated behavioural coaching — personalised\nto this week's data and habit patterns]",
                       55, None, (80, 80, 80)),
    },
]


def apply_rules(shot_name=None):
    """Apply all enabled rules. If shot_name provided, only process that file."""
    active_rules = [r for r in RULES if r["enabled"]]
    if shot_name:
        active_rules = [r for r in active_rules if r["shot"] == shot_name]

    # Group by shot
    shots_to_process = set(r["shot"] for r in active_rules)

    # Also copy over shots with no rules (passthrough)
    all_shots = list(SRC.glob("*.png"))
    passthrough = [s for s in all_shots if s.stem not in shots_to_process]

    results = {"redacted": [], "passthrough": [], "missing": []}

    for shot_path in all_shots:
        name = shot_path.stem
        out_path = OUT / shot_path.name
        img = Image.open(shot_path).convert("RGB")
        w, h = img.size
        shot_rules = [r for r in active_rules if r["shot"] == name]

        if not shot_rules:
            shutil.copy(shot_path, out_path)
            results["passthrough"].append(name)
            continue

        modified = False
        for rule in shot_rules:
            x1 = int(rule["x_frac"][0] * w)
            x2 = int(rule["x_frac"][1] * w)
            y1 = int(rule["y_frac"][0] * h)
            y2 = int(rule["y_frac"][1] * h)

            draw = ImageDraw.Draw(img)
            draw.rectangle([x1, y1, x2, y2], fill=rule["fill"])

            if rule.get("label"):
                lbl = rule["label"]
                draw.text((x1 + 10, y1 + (y2-y1)//2 - 6), lbl, fill=(60, 80, 100))

            if rule.get("post_label"):
                text, indent, _, color = rule["post_label"]
                for i, line in enumerate(text.split("\n")):
                    draw.text((x1 + indent, y1 + 15 + i*22), line, fill=color)

            modified = True

        img.save(out_path)
        results["redacted"].append(name)
        print(f"  ✓ {name} — {len(shot_rules)} rule(s) applied")

    return results


def main():
    shot_filter = sys.argv[1] if len(sys.argv) > 1 else None

    print(f"\nLife Platform Screenshot Redaction Pipeline")
    print(f"Source:  {SRC}")
    print(f"Output:  {OUT}")
    print(f"Rules:   {len([r for r in RULES if r['enabled']])} active")
    print("─"*60)

    if not any(SRC.glob("*.png")):
        print("ERROR: No screenshots found in screenshots/")
        print("Run capture_screenshots.py first, or copy screenshots manually.")
        sys.exit(1)

    results = apply_rules(shot_filter)

    print(f"\nDone.")
    print(f"  Redacted:    {len(results['redacted'])} shots")
    print(f"  Passthrough: {len(results['passthrough'])} shots")
    print(f"\nNext step: python3 build_pdf.py")


if __name__ == "__main__":
    main()
