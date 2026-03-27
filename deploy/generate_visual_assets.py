#!/usr/bin/env python3
"""
generate_visual_assets.py — Generates the complete icon set and geometric badge set
for averagejoematt.com. Phase A: clean geometric SVGs generated directly.

Run from project root:
    python3 deploy/generate_visual_assets.py

Output:
    site/assets/icons/custom/*.svg   (25 icons)
    site/assets/img/badges/*.svg     (40 badges)
"""

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ICON_DIR = PROJECT_ROOT / "site" / "assets" / "icons" / "custom"
BADGE_DIR = PROJECT_ROOT / "site" / "assets" / "img" / "badges"

# ── ICON DEFINITIONS ──────────────────────────────────────────────
# All icons: 24x24 viewBox, stroke="currentColor", stroke-width="1.5",
# fill="none", stroke-linecap="round", stroke-linejoin="round"

ICONS = {
    "icon-sleep": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
  <path d="M21 12.79A9 9 0 1 1 11.21 3a7 7 0 0 0 9.79 9.79z"/>
  <path d="M15 4l1.5 2L18 4" opacity="0.6"/>
  <path d="M18 7l1 1.5L20 7" opacity="0.4"/>
</svg>""",

    "icon-movement": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
  <circle cx="14" cy="4" r="2"/>
  <path d="M8 21l2-6 3 2v-6l-4-2-3 4"/>
  <path d="M13 11l3-2 3 5"/>
</svg>""",

    "icon-nutrition": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
  <path d="M12 2c-3 4-6 6-6 10a6 6 0 0 0 12 0c0-4-3-6-6-10z"/>
  <path d="M12 8v8"/>
  <path d="M9 14h6"/>
</svg>""",

    "icon-metabolic": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
  <polyline points="2 13 5 13 7 8 9 18 11 6 13 16 15 10 17 13 22 13"/>
</svg>""",

    "icon-mind": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
  <path d="M12 2a7 7 0 0 0-7 7c0 2.5 1.3 4.7 3.3 6L9 22h6l.7-7c2-1.3 3.3-3.5 3.3-6a7 7 0 0 0-7-7z"/>
  <path d="M9 15h6" opacity="0.5"/>
  <path d="M10 18h4" opacity="0.4"/>
</svg>""",

    "icon-social": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
  <circle cx="9" cy="10" r="5"/>
  <circle cx="15" cy="10" r="5"/>
</svg>""",

    "icon-consistency": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
  <circle cx="12" cy="12" r="9"/>
  <circle cx="12" cy="12" r="5"/>
  <circle cx="12" cy="12" r="1.5" fill="currentColor"/>
</svg>""",

    "icon-scale": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
  <path d="M12 3v15"/>
  <path d="M5 7l7-4 7 4"/>
  <path d="M3 13l2-6 2 6a3 3 0 0 1-4 0z"/>
  <path d="M17 13l2-6 2 6a3 3 0 0 1-4 0z"/>
  <path d="M8 21h8"/>
</svg>""",

    "icon-water": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
  <path d="M12 2s-6 8-6 12a6 6 0 0 0 12 0c0-4-6-12-6-12z"/>
  <path d="M8 16c1.5 1 3.5 1 5 0" opacity="0.5"/>
</svg>""",

    "icon-lift": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
  <path d="M4 12h16"/>
  <rect x="2" y="9" width="3" height="6" rx="1"/>
  <rect x="19" y="9" width="3" height="6" rx="1"/>
  <rect x="6" y="10" width="2" height="4" rx="0.5"/>
  <rect x="16" y="10" width="2" height="4" rx="0.5"/>
</svg>""",

    "icon-recovery": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
  <path d="M20.42 4.58a5.4 5.4 0 0 0-7.65 0L12 5.34l-.77-.76a5.4 5.4 0 0 0-7.65 7.65l.77.76L12 20.65l7.65-7.66.77-.76a5.4 5.4 0 0 0 0-7.65z"/>
  <polyline points="8 13 10 13 11 11 13 15 14 13 16 13" stroke-width="1.2"/>
</svg>""",

    "icon-journal": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
  <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/>
  <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>
  <path d="M8 7h8" opacity="0.5"/>
  <path d="M8 11h5" opacity="0.4"/>
</svg>""",

    "icon-streak": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
  <path d="M12 2c0 4-4 6-4 10a4 4 0 0 0 8 0c0-4-4-6-4-10z"/>
  <path d="M12 10c0 2-1.5 3-1.5 4.5a1.5 1.5 0 0 0 3 0c0-1.5-1.5-2.5-1.5-4.5z" fill="currentColor" opacity="0.3"/>
</svg>""",

    "icon-experiment": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
  <path d="M9 3h6"/>
  <path d="M10 3v6l-5 8.5a1 1 0 0 0 .85 1.5h12.3a1 1 0 0 0 .85-1.5L14 9V3"/>
  <circle cx="10" cy="14" r="1" fill="currentColor" opacity="0.4"/>
  <circle cx="13" cy="16" r="0.7" fill="currentColor" opacity="0.3"/>
</svg>""",

    "icon-discovery": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
  <path d="M9 18h6"/>
  <path d="M10 22h4"/>
  <path d="M12 2a7 7 0 0 1 4 12.7V18H8v-3.3A7 7 0 0 1 12 2z"/>
  <path d="M12 8v2" opacity="0.5"/>
  <path d="M11 10h2" opacity="0.5"/>
</svg>""",

    "icon-supplement": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
  <rect x="6" y="4" width="12" height="16" rx="6"/>
  <path d="M6 12h12"/>
  <rect x="6" y="4" width="12" height="8" rx="6" fill="currentColor" opacity="0.15"/>
</svg>""",

    "icon-cgm": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
  <rect x="3" y="3" width="18" height="18" rx="2"/>
  <polyline points="7 15 9 11 11 14 13 8 15 12 17 9"/>
</svg>""",

    "icon-blood": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
  <path d="M12 2s-5 7-5 11a5 5 0 0 0 10 0c0-4-5-11-5-11z"/>
  <path d="M10 14h4"/>
  <path d="M12 12v4"/>
</svg>""",

    "icon-steps": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
  <path d="M8 3c-.5 2.5-.2 4.5 1 6s1.5 4 .5 6"/>
  <ellipse cx="8" cy="18" rx="2.5" ry="3"/>
  <path d="M16 1c-.5 2.5-.2 4.5 1 6s1.5 4 .5 6"/>
  <ellipse cx="16" cy="16" rx="2.5" ry="3"/>
</svg>""",

    "icon-zone2": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
  <circle cx="14" cy="4" r="2"/>
  <path d="M8 21l2-6 3 2v-6l-4-2-3 4"/>
  <path d="M13 11l3-2 3 5"/>
  <path d="M3 12h2" opacity="0.4"/>
  <path d="M3 9h1" opacity="0.3"/>
  <path d="M3 15h1" opacity="0.3"/>
</svg>""",

    "icon-level-up": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
  <polygon points="12 2 21.5 7.5 21.5 16.5 12 22 2.5 16.5 2.5 7.5"/>
  <polyline points="8 14 12 8 16 14"/>
</svg>""",

    "icon-tier": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
  <path d="M12 2l8 4v6c0 5.5-3.8 10.7-8 12-4.2-1.3-8-6.5-8-12V6l8-4z"/>
  <path d="M8 13h8" opacity="0.5"/>
  <path d="M8 10h8" opacity="0.4"/>
  <path d="M8 16h8" opacity="0.3"/>
</svg>""",

    "icon-alert": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
  <polygon points="13 2 3 14 12 14 11 22 21 10 12 10"/>
</svg>""",

    "icon-calendar": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
  <rect x="3" y="4" width="18" height="18" rx="2"/>
  <path d="M16 2v4"/>
  <path d="M8 2v4"/>
  <path d="M3 10h18"/>
  <rect x="7" y="14" width="3" height="3" rx="0.5" fill="currentColor" opacity="0.2"/>
</svg>""",

    "icon-trend-up": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
  <polyline points="4 18 8 14 12 16 20 6"/>
  <polyline points="15 6 20 6 20 11"/>
</svg>""",

    "icon-trend-down": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
  <polyline points="4 6 8 10 12 8 20 18"/>
  <polyline points="15 18 20 18 20 13"/>
</svg>""",
}


# ── BADGE DEFINITIONS ─────────────────────────────────────────────
# Phase A: Geometric badges. Each is 72x72 viewBox.
# Structure: outer frame (hexagon or shield) + inner motif + label area
# Uses category accent color on dark transparent background.

def hex_frame(accent, opacity="0.3"):
    """Hexagonal badge frame"""
    return f'''  <polygon points="36 2 66 19 66 53 36 70 6 53 6 19" fill="none" stroke="{accent}" stroke-width="1.5" opacity="{opacity}"/>
  <polygon points="36 8 60 22 60 50 36 64 12 50 12 22" fill="none" stroke="{accent}" stroke-width="1"/>'''

def shield_frame(accent, opacity="0.3"):
    """Shield-shaped badge frame"""
    return f'''  <path d="M36 2L66 14V42Q66 62 36 70Q6 62 6 42V14Z" fill="none" stroke="{accent}" stroke-width="1.5" opacity="{opacity}"/>
  <path d="M36 8L60 18V40Q60 56 36 64Q12 56 12 40V18Z" fill="none" stroke="{accent}" stroke-width="0.8" opacity="0.15"/>'''

def circle_frame(accent, opacity="0.3"):
    """Circular badge frame"""
    return f'''  <circle cx="36" cy="36" r="33" fill="none" stroke="{accent}" stroke-width="1.5" opacity="{opacity}"/>
  <circle cx="36" cy="36" r="27" fill="none" stroke="{accent}" stroke-width="0.8" opacity="0.15"/>'''

# Colors per category
C_STREAK = "#c8843a"
C_LEVEL = "#00e5a0"
C_WEIGHT = "#5ba4cf"
C_DATA = "#8b6cc1"
C_EXPERIMENT = "#e06060"
C_CHALLENGE = "#f59e0b"
C_VICE = "#00e5a0"
C_RUNNING = "#5ba4cf"
C_TEXT = "#e8ede9"
C_FAINT = "#4a6050"

def badge_svg(frame_fn, accent, motif_paths, label=""):
    """Generate a complete badge SVG"""
    frame = frame_fn(accent)
    motif = "\n".join(f"  {p}" for p in motif_paths)
    label_el = f'\n  <text x="36" y="62" text-anchor="middle" font-family="Space Mono,monospace" font-size="6" fill="{accent}" letter-spacing="0.08em">{label}</text>' if label else ""
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 72 72" fill="none">
{frame}
{motif}{label_el}
</svg>'''

BADGES = {
    # ── STREAKS ──
    "badge_week_warrior": badge_svg(hex_frame, C_STREAK, [
        f'<path d="M36 22c0 4-5 6-5 10s2 5 5 5 5-1 5-5-5-6-5-10z" fill="{C_STREAK}" opacity="0.6"/>',
        f'<path d="M36 22c0 4-5 6-5 10s2 5 5 5 5-1 5-5-5-6-5-10z" stroke="{C_STREAK}" stroke-width="1.2" fill="none"/>',
    ], "7 DAYS"),

    "badge_monthly_grind": badge_svg(hex_frame, C_STREAK, [
        f'<path d="M32 24c0 3-4 5-4 8s1.5 4 4 4 4-1 4-4-4-5-4-8z" fill="{C_STREAK}" opacity="0.5"/>',
        f'<path d="M40 24c0 3-4 5-4 8s1.5 4 4 4 4-1 4-4-4-5-4-8z" fill="{C_STREAK}" opacity="0.5"/>',
        f'<path d="M32 24c0 3-4 5-4 8s1.5 4 4 4 4-1 4-4-4-5-4-8z" stroke="{C_STREAK}" stroke-width="1" fill="none"/>',
        f'<path d="M40 24c0 3-4 5-4 8s1.5 4 4 4 4-1 4-4-4-5-4-8z" stroke="{C_STREAK}" stroke-width="1" fill="none"/>',
    ], "30 DAYS"),

    "badge_quarterly": badge_svg(shield_frame, C_STREAK, [
        f'<path d="M30 22c0 3-3 5-3 8s1.2 3.5 3 3.5" stroke="{C_STREAK}" stroke-width="1" fill="none"/>',
        f'<path d="M36 20c0 3.5-4 5.5-4 9s1.5 4 4 4 4-1 4-4-4-5.5-4-9z" fill="{C_STREAK}" opacity="0.6"/>',
        f'<path d="M42 22c0 3 3 5 3 8s-1.2 3.5-3 3.5" stroke="{C_STREAK}" stroke-width="1" fill="none"/>',
    ], "90 DAYS"),

    "badge_half_year": badge_svg(shield_frame, C_STREAK, [
        f'<path d="M36 18c0 5-6 7-6 12s3 6 6 6 6-1 6-6-6-7-6-12z" fill="{C_STREAK}" opacity="0.5"/>',
        f'<path d="M36 18c0 5-6 7-6 12s3 6 6 6 6-1 6-6-6-7-6-12z" stroke="{C_STREAK}" stroke-width="1.2" fill="none"/>',
        f'<text x="36" y="34" text-anchor="middle" font-family="Space Mono,monospace" font-size="8" fill="{C_TEXT}" font-weight="bold">180</text>',
    ]),

    "badge_annual_fire": badge_svg(shield_frame, C_STREAK, [
        f'<circle cx="36" cy="32" r="12" fill="{C_STREAK}" opacity="0.15"/>',
        f'<path d="M36 16c0 6-8 8-8 14s4 8 8 8 8-2 8-8-8-8-8-14z" fill="{C_STREAK}" opacity="0.5"/>',
        f'<path d="M36 16c0 6-8 8-8 14s4 8 8 8 8-2 8-8-8-8-8-14z" stroke="{C_STREAK}" stroke-width="1.5" fill="none"/>',
        f'<line x1="28" y1="12" x2="26" y2="8" stroke="{C_STREAK}" stroke-width="0.8" opacity="0.4"/>',
        f'<line x1="44" y1="12" x2="46" y2="8" stroke="{C_STREAK}" stroke-width="0.8" opacity="0.4"/>',
        f'<line x1="36" y1="10" x2="36" y2="6" stroke="{C_STREAK}" stroke-width="0.8" opacity="0.4"/>',
    ], "365 DAYS"),

    # ── LEVELS ──
    "badge_first_level_up": badge_svg(hex_frame, C_LEVEL, [
        f'<polyline points="30 38 36 28 42 38" stroke="{C_LEVEL}" stroke-width="1.5" fill="none" stroke-linecap="round"/>',
    ], "LV 2"),

    "badge_apprentice": badge_svg(hex_frame, C_LEVEL, [
        f'<polyline points="30 40 36 32 42 40" stroke="{C_LEVEL}" stroke-width="1.5" fill="none" stroke-linecap="round"/>',
        f'<polyline points="30 34 36 26 42 34" stroke="{C_LEVEL}" stroke-width="1.5" fill="none" stroke-linecap="round"/>',
    ], "LV 5"),

    "badge_journeyman": badge_svg(shield_frame, C_LEVEL, [
        f'<polyline points="30 42 36 36 42 42" stroke="{C_LEVEL}" stroke-width="1.5" fill="none" stroke-linecap="round"/>',
        f'<polyline points="30 36 36 30 42 36" stroke="{C_LEVEL}" stroke-width="1.5" fill="none" stroke-linecap="round"/>',
        f'<polyline points="30 30 36 24 42 30" stroke="{C_LEVEL}" stroke-width="1.5" fill="none" stroke-linecap="round"/>',
    ], "LV 10"),

    "badge_adept": badge_svg(shield_frame, C_LEVEL, [
        f'<polygon points="36 18 40 30 52 30 42 38 46 50 36 42 26 50 30 38 20 30 32 30" fill="{C_LEVEL}" opacity="0.2"/>',
        f'<polygon points="36 18 40 30 52 30 42 38 46 50 36 42 26 50 30 38 20 30 32 30" stroke="{C_LEVEL}" stroke-width="1" fill="none"/>',
    ], "LV 15"),

    "badge_expert": badge_svg(shield_frame, C_LEVEL, [
        f'<polygon points="36 14 40 26 52 26 42 34 46 46 36 38 26 46 30 34 20 26 32 26" fill="{C_LEVEL}" opacity="0.25"/>',
        f'<polygon points="36 14 40 26 52 26 42 34 46 46 36 38 26 46 30 34 20 26 32 26" stroke="{C_LEVEL}" stroke-width="1.2" fill="none"/>',
        f'<circle cx="36" cy="32" r="4" fill="{C_LEVEL}" opacity="0.4"/>',
    ], "LV 20"),

    "badge_master": badge_svg(shield_frame, "#d4a520", [
        f'<polygon points="36 12 40 24 52 24 42 32 46 44 36 36 26 44 30 32 20 24 32 24" fill="#d4a520" opacity="0.3"/>',
        f'<polygon points="36 12 40 24 52 24 42 32 46 44 36 36 26 44 30 32 20 24 32 24" stroke="#d4a520" stroke-width="1.5" fill="none"/>',
        f'<circle cx="36" cy="30" r="6" fill="#d4a520" opacity="0.3"/>',
        f'<circle cx="36" cy="30" r="3" fill="#d4a520" opacity="0.5"/>',
    ], "LV 40"),

    # ── WEIGHT MILESTONES ──
    "badge_first_10": badge_svg(hex_frame, C_WEIGHT, [
        f'<path d="M29 30l7-4 7 4" stroke="{C_WEIGHT}" stroke-width="1.2" fill="none"/>',
        f'<path d="M36 26v-4" stroke="{C_WEIGHT}" stroke-width="1.2"/>',
        f'<polyline points="34 22 36 18 38 22" stroke="{C_WEIGHT}" stroke-width="1" fill="none"/>',
        f'<text x="36" y="44" text-anchor="middle" font-family="Space Mono,monospace" font-size="8" fill="{C_WEIGHT}" font-weight="bold">-10</text>',
    ]),

    "badge_lost_20": badge_svg(hex_frame, C_WEIGHT, [
        f'<path d="M29 30l7-4 7 4" stroke="{C_WEIGHT}" stroke-width="1.2" fill="none"/>',
        f'<path d="M36 26v-4" stroke="{C_WEIGHT}" stroke-width="1.2"/>',
        f'<polyline points="33 24 36 18 39 24" stroke="{C_WEIGHT}" stroke-width="1" fill="none"/>',
        f'<polyline points="33 20 36 14 39 20" stroke="{C_WEIGHT}" stroke-width="0.8" fill="none" opacity="0.5"/>',
        f'<text x="36" y="44" text-anchor="middle" font-family="Space Mono,monospace" font-size="8" fill="{C_WEIGHT}" font-weight="bold">-20</text>',
    ]),

    "badge_sub_280": badge_svg(circle_frame, C_WEIGHT, [
        f'<text x="36" y="32" text-anchor="middle" font-family="Space Mono,monospace" font-size="9" fill="{C_FAINT}" text-decoration="line-through">280</text>',
        f'<text x="36" y="44" text-anchor="middle" font-family="Space Mono,monospace" font-size="7" fill="{C_WEIGHT}">SUB</text>',
    ]),

    "badge_sub_260": badge_svg(circle_frame, C_WEIGHT, [
        f'<text x="36" y="32" text-anchor="middle" font-family="Space Mono,monospace" font-size="9" fill="{C_FAINT}" text-decoration="line-through">260</text>',
        f'<text x="36" y="44" text-anchor="middle" font-family="Space Mono,monospace" font-size="7" fill="{C_WEIGHT}">SUB</text>',
    ]),

    "badge_sub_240": badge_svg(circle_frame, C_WEIGHT, [
        f'<path d="M22 36h28" stroke="{C_WEIGHT}" stroke-width="1" opacity="0.4"/>',
        f'<text x="36" y="32" text-anchor="middle" font-family="Space Mono,monospace" font-size="9" fill="{C_FAINT}" text-decoration="line-through">240</text>',
        f'<text x="36" y="44" text-anchor="middle" font-family="Space Mono,monospace" font-size="6" fill="{C_WEIGHT}">HALFWAY</text>',
    ]),

    "badge_sub_220": badge_svg(circle_frame, C_WEIGHT, [
        f'<text x="36" y="32" text-anchor="middle" font-family="Space Mono,monospace" font-size="9" fill="{C_FAINT}" text-decoration="line-through">220</text>',
        f'<text x="36" y="44" text-anchor="middle" font-family="Space Mono,monospace" font-size="7" fill="{C_WEIGHT}">SUB</text>',
    ]),

    "badge_sub_200": badge_svg(shield_frame, C_WEIGHT, [
        f'<text x="36" y="34" text-anchor="middle" font-family="Impact,Bebas Neue,sans-serif" font-size="14" fill="{C_WEIGHT}">199</text>',
        f'<text x="36" y="46" text-anchor="middle" font-family="Space Mono,monospace" font-size="6" fill="{C_WEIGHT}" letter-spacing="0.1em">ONDERLAND</text>',
    ]),

    "badge_goal_weight": badge_svg(shield_frame, "#d4a520", [
        f'<path d="M28 16l4 5h-3l4 5h-3l7 7 7-7h-3l4-5h-3l4-5z" fill="#d4a520" opacity="0.2"/>',
        f'<text x="36" y="38" text-anchor="middle" font-family="Impact,Bebas Neue,sans-serif" font-size="16" fill="#d4a520">185</text>',
        f'<text x="36" y="50" text-anchor="middle" font-family="Space Mono,monospace" font-size="6" fill="#d4a520" letter-spacing="0.08em">THE GOAL</text>',
        f'<path d="M20 56c4-2 8-3 16-3s12 1 16 3" stroke="#d4a520" stroke-width="0.8" fill="none" opacity="0.4"/>',
    ]),

    # ── DATA CONSISTENCY ──
    "badge_100_days": badge_svg(hex_frame, C_DATA, [
        # 10x10 dot grid
        *[f'<circle cx="{22 + (i % 10) * 2.8}" cy="{24 + (i // 10) * 2.8}" r="0.8" fill="{C_DATA}" opacity="0.6"/>' for i in range(100)],
    ], "100 DAYS"),

    "badge_200_days": badge_svg(hex_frame, C_DATA, [
        *[f'<circle cx="{20 + (i % 14) * 2.3}" cy="{22 + (i // 14) * 2.3}" r="0.6" fill="{C_DATA}" opacity="0.5"/>' for i in range(196)],
    ], "200 DAYS"),

    "badge_365_days": badge_svg(circle_frame, C_DATA, [
        f'<circle cx="36" cy="36" r="18" fill="none" stroke="{C_DATA}" stroke-width="4" stroke-dasharray="1 0.5" opacity="0.5"/>',
        f'<text x="36" y="38" text-anchor="middle" font-family="Space Mono,monospace" font-size="8" fill="{C_DATA}" font-weight="bold">365</text>',
    ]),

    "badge_data_complete": badge_svg(circle_frame, C_DATA, [
        # 19-point star/radial
        *[f'<line x1="36" y1="36" x2="{36 + 16 * __import__("math").cos(__import__("math").radians(i * 360/19 - 90)):.1f}" y2="{36 + 16 * __import__("math").sin(__import__("math").radians(i * 360/19 - 90)):.1f}" stroke="{C_DATA}" stroke-width="1" opacity="0.6"/>' for i in range(19)],
        f'<circle cx="36" cy="36" r="3" fill="{C_DATA}" opacity="0.5"/>',
    ], "FULL SIGNAL"),

    # ── EXPERIMENTS ──
    "badge_first_experiment": badge_svg(hex_frame, C_EXPERIMENT, [
        f'<path d="M32 18h8" stroke="{C_EXPERIMENT}" stroke-width="1.2"/>',
        f'<path d="M34 18v8l-6 12a1.5 1.5 0 0 0 1.3 2.2h13.4a1.5 1.5 0 0 0 1.3-2.2l-6-12v-8" stroke="{C_EXPERIMENT}" stroke-width="1.2" fill="none"/>',
        f'<circle cx="33" cy="34" r="1.5" fill="{C_EXPERIMENT}" opacity="0.4"/>',
        f'<circle cx="38" cy="36" r="1" fill="{C_EXPERIMENT}" opacity="0.3"/>',
    ]),

    "badge_five_experiments": badge_svg(hex_frame, C_EXPERIMENT, [
        f'<path d="M30 20h4v6l-4 8h8l-4-8v-6" stroke="{C_EXPERIMENT}" stroke-width="1" fill="none"/>',
        f'<path d="M38 20h4v6l-4 8h8l-4-8v-6" stroke="{C_EXPERIMENT}" stroke-width="1" fill="none"/>',
        f'<text x="36" y="48" text-anchor="middle" font-family="Space Mono,monospace" font-size="8" fill="{C_EXPERIMENT}" font-weight="bold">×5</text>',
    ]),

    "badge_hypothesis_confirmed": badge_svg(shield_frame, C_EXPERIMENT, [
        f'<path d="M32 20h8" stroke="{C_EXPERIMENT}" stroke-width="1.2"/>',
        f'<path d="M34 20v6l-5 10a1 1 0 0 0 .9 1.5h12.2a1 1 0 0 0 .9-1.5l-5-10v-6" stroke="{C_EXPERIMENT}" stroke-width="1.2" fill="none"/>',
        f'<polyline points="30 42 34 46 42 36" stroke="{C_EXPERIMENT}" stroke-width="2" fill="none" stroke-linecap="round"/>',
    ]),

    "badge_ten_experiments": badge_svg(shield_frame, C_EXPERIMENT, [
        f'<path d="M28 18h6v5l-4 8h8l-4-8v-5" stroke="{C_EXPERIMENT}" stroke-width="0.8" fill="none"/>',
        f'<path d="M38 18h6v5l-4 8h8l-4-8v-5" stroke="{C_EXPERIMENT}" stroke-width="0.8" fill="none"/>',
        f'<path d="M33 30h6v4l-3 6h6l-3-6v-4" stroke="{C_EXPERIMENT}" stroke-width="0.8" fill="none"/>',
        f'<text x="36" y="52" text-anchor="middle" font-family="Space Mono,monospace" font-size="7" fill="{C_EXPERIMENT}" font-weight="bold">×10</text>',
    ]),

    # ── CHALLENGES ──
    "badge_first_challenge": badge_svg(hex_frame, C_CHALLENGE, [
        f'<path d="M28 28h16v-4l4 4-4 4v-4" stroke="{C_CHALLENGE}" stroke-width="1.2" fill="none"/>',
        f'<path d="M28 28v8h16v-8" stroke="{C_CHALLENGE}" stroke-width="1.2" fill="none"/>',
        f'<path d="M33 36v4h6v-4" stroke="{C_CHALLENGE}" stroke-width="1" fill="none"/>',
    ]),

    "badge_five_challenges": badge_svg(hex_frame, C_CHALLENGE, [
        f'<path d="M28 26h16v-4l4 4-4 4v-4" stroke="{C_CHALLENGE}" stroke-width="1.2" fill="none"/>',
        f'<path d="M28 26v10h16v-10" stroke="{C_CHALLENGE}" stroke-width="1.2" fill="none"/>',
        f'<path d="M33 36v4h6v-4" stroke="{C_CHALLENGE}" stroke-width="1" fill="none"/>',
        f'<text x="36" y="50" text-anchor="middle" font-family="Space Mono,monospace" font-size="7" fill="{C_CHALLENGE}">×5</text>',
    ]),

    "badge_ten_challenges": badge_svg(shield_frame, C_CHALLENGE, [
        f'<path d="M28 24h16v-4l4 4-4 4v-4" stroke="{C_CHALLENGE}" stroke-width="1.2" fill="none"/>',
        f'<path d="M28 24v10h16v-10" stroke="{C_CHALLENGE}" stroke-width="1.2" fill="none"/>',
        f'<path d="M33 34v4h6v-4" stroke="{C_CHALLENGE}" stroke-width="1" fill="none"/>',
        f'<circle cx="36" cy="24" r="3" fill="{C_CHALLENGE}" opacity="0.3"/>',
    ], "×10"),

    "badge_twenty_five": badge_svg(shield_frame, C_CHALLENGE, [
        f'<path d="M28 22h16v-4l4 4-4 4v-4" stroke="{C_CHALLENGE}" stroke-width="1.5" fill="none"/>',
        f'<path d="M28 22v12h16v-12" stroke="{C_CHALLENGE}" stroke-width="1.5" fill="none"/>',
        f'<path d="M33 34v4h6v-4" stroke="{C_CHALLENGE}" stroke-width="1" fill="none"/>',
        # Laurel wreath
        f'<path d="M20 20c2 4 2 10 0 16" stroke="{C_CHALLENGE}" stroke-width="0.8" fill="none" opacity="0.5"/>',
        f'<path d="M52 20c-2 4-2 10 0 16" stroke="{C_CHALLENGE}" stroke-width="0.8" fill="none" opacity="0.5"/>',
    ], "×25"),

    "badge_perfect_challenge": badge_svg(circle_frame, C_CHALLENGE, [
        f'<path d="M28 30h16v-4l4 4-4 4v-4" stroke="{C_CHALLENGE}" stroke-width="1.2" fill="none"/>',
        f'<path d="M28 30v8h16v-8" stroke="{C_CHALLENGE}" stroke-width="1.2" fill="none"/>',
        f'<circle cx="36" cy="30" r="14" fill="none" stroke="{C_CHALLENGE}" stroke-width="0.8" stroke-dasharray="2 2" opacity="0.5"/>',
        f'<text x="36" y="50" text-anchor="middle" font-family="Space Mono,monospace" font-size="6" fill="{C_CHALLENGE}">PERFECT</text>',
    ]),

    # ── VICE STREAKS ──
    "badge_vice_30": badge_svg(hex_frame, C_VICE, [
        f'<path d="M24 32c2 0 3-2 5-2s3 2 5 2 3-2 5-2 3 2 5 2 3-2 5-2" stroke="{C_VICE}" stroke-width="1.5" fill="none"/>',
        f'<line x1="34" y1="30" x2="38" y2="34" stroke="{C_VICE}" stroke-width="2" opacity="0.6"/>',
    ], "30 DAYS"),

    "badge_vice_90": badge_svg(hex_frame, C_VICE, [
        f'<path d="M22 30c2 0 3-2 5-2s3 2 5 2 3-2 5-2 3 2 5 2 3-2 5-2 3 2 5 2" stroke="{C_FAINT}" stroke-width="1.5" fill="none"/>',
        f'<line x1="32" y1="28" x2="40" y2="36" stroke="{C_VICE}" stroke-width="2.5"/>',
        f'<line x1="32" y1="36" x2="40" y2="28" stroke="{C_VICE}" stroke-width="2.5"/>',
    ], "90 DAYS"),

    "badge_vice_180": badge_svg(shield_frame, C_VICE, [
        f'<path d="M24 30c2 0 3-2 5-2s3 2 5 2" stroke="{C_FAINT}" stroke-width="1" fill="none" opacity="0.3"/>',
        f'<path d="M38 30c2 0 3-2 5-2s3 2 5 2" stroke="{C_FAINT}" stroke-width="1" fill="none" opacity="0.3"/>',
        f'<path d="M30 34l6 8 6-8" stroke="{C_VICE}" stroke-width="1.5" fill="none" stroke-linecap="round"/>',
    ], "180 DAYS"),

    "badge_vice_365": badge_svg(shield_frame, C_VICE, [
        f'<path d="M36 20c-3 4-4 8-2 12s4 6 2 10" stroke="{C_VICE}" stroke-width="1.2" fill="none"/>',
        f'<path d="M36 20c3 4 4 8 2 12s-4 6-2 10" stroke="{C_VICE}" stroke-width="1.2" fill="none"/>',
        f'<circle cx="36" cy="26" r="2" fill="{C_VICE}" opacity="0.4"/>',
    ], "1 YEAR"),

    # ── RUNNING ──
    "badge_first_5k": badge_svg(circle_frame, C_RUNNING, [
        f'<text x="36" y="34" text-anchor="middle" font-family="Impact,Bebas Neue,sans-serif" font-size="14" fill="{C_RUNNING}">5K</text>',
        f'<polyline points="24 42 30 38 36 40 42 37 48 42" stroke="{C_RUNNING}" stroke-width="1" fill="none" opacity="0.4"/>',
    ]),

    "badge_first_10k": badge_svg(circle_frame, C_RUNNING, [
        f'<text x="36" y="34" text-anchor="middle" font-family="Impact,Bebas Neue,sans-serif" font-size="13" fill="{C_RUNNING}">10K</text>',
        f'<polyline points="22 42 28 36 34 40 40 34 46 38 50 42" stroke="{C_RUNNING}" stroke-width="1" fill="none" opacity="0.4"/>',
    ]),

    "badge_half_marathon": badge_svg(shield_frame, C_RUNNING, [
        f'<text x="36" y="32" text-anchor="middle" font-family="Impact,Bebas Neue,sans-serif" font-size="12" fill="{C_RUNNING}">13.1</text>',
        f'<text x="36" y="44" text-anchor="middle" font-family="Space Mono,monospace" font-size="6" fill="{C_RUNNING}" letter-spacing="0.08em">MILES</text>',
        f'<polyline points="20 50 28 42 36 46 44 40 52 50" stroke="{C_RUNNING}" stroke-width="1" fill="none" opacity="0.3"/>',
    ]),
}


def main():
    # Create directories
    ICON_DIR.mkdir(parents=True, exist_ok=True)
    BADGE_DIR.mkdir(parents=True, exist_ok=True)

    # Write icons
    icon_count = 0
    for name, svg in ICONS.items():
        path = ICON_DIR / f"{name}.svg"
        path.write_text(svg.strip() + "\n")
        icon_count += 1

    # Write badges
    badge_count = 0
    for name, svg in BADGES.items():
        path = BADGE_DIR / f"{name}.svg"
        path.write_text(svg.strip() + "\n")
        badge_count += 1

    # Create SVG sprite for icons (optional, for <use> references)
    sprite_parts = ['<svg xmlns="http://www.w3.org/2000/svg" style="display:none">']
    for name, svg in ICONS.items():
        # Extract inner content (everything between <svg> tags)
        inner = svg.strip()
        inner = inner.split(">", 1)[1]  # remove opening <svg ...>
        inner = inner.rsplit("</svg>", 1)[0]  # remove closing </svg>
        sprite_parts.append(f'  <symbol id="{name}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">')
        sprite_parts.append(f"    {inner.strip()}")
        sprite_parts.append("  </symbol>")
    sprite_parts.append("</svg>")
    sprite_path = ICON_DIR / "sprite.svg"
    sprite_path.write_text("\n".join(sprite_parts) + "\n")

    print(f"✓ Generated {icon_count} icons in {ICON_DIR}")
    print(f"✓ Generated {badge_count} badges in {BADGE_DIR}")
    print(f"✓ Generated icon sprite at {sprite_path}")
    print(f"\nTotal: {icon_count + badge_count} SVG assets")


if __name__ == "__main__":
    main()
