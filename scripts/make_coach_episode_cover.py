#!/usr/bin/env python3
"""make_coach_episode_cover.py — per-episode Panel cover art with coach portraits (#593).

Successor to make_panelcast_cover.py (which draws only the show-level cover). Each Panel
episode pairs the embedded journalist (host: Elena Voss) with a rotating AI coach (guest);
this composes BOTH engraved portraits into the instrument frame from the SAME signed recipes
the site renders (web.portrait_raster) — the faces travel to the podcast art from one source
of truth (ADR-106). Credited on the card: "illustration: commissioned, AI-assisted."

Square 1500x1500 (Apple/Spotify requirement). Uses full macOS system fonts for the title
text (the bundled webfonts are glyph-subsetted and render arbitrary cover text as tofu — the
same reason make_panelcast_cover.py does), and the code-drawn portraits for the faces.

Usage:
    python3 scripts/make_coach_episode_cover.py --guest sarah_chen \\
        --title "Building The Base" --episode 4 --out /tmp/panel_ep4.jpg
"""

import argparse
import json
import os
import sys

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))

import v4_build_portraits as vbp  # noqa: E402
from web import portrait_raster  # noqa: E402

PAGE = (14, 12, 8)
INK = (236, 227, 210)
MUTED = (169, 159, 140)
EMBER = (221, 122, 55)
S = 1500

SUP = "/System/Library/Fonts/Supplemental"
DISP = f"{SUP}/Avenir Next Condensed.ttc"
MONO = f"{SUP}/Courier New.ttf"
MONOB = f"{SUP}/Courier New Bold.ttf"

HOST_PID = "elena_voss"


def _members():
    try:
        with open(os.path.join(ROOT, "config", "board_of_directors.json")) as f:
            return json.load(f).get("members", {})
    except Exception:
        return {}


def _identity(pid, recipe, members):
    m = members.get(pid)
    if not m:
        for a in recipe.get("aliases") or []:
            if a in members:
                m = members[a]
                break
    m = m or {}
    return {"name": m.get("name") or pid.replace("_", " ").title(), "color": m.get("color") or "#a99f8c"}


def _tf(path, px, idx=None):
    """Load a truetype font, falling back to Pillow's default when the (macOS system)
    path is absent — so the composer runs headless (CI/Linux) without crashing."""
    try:
        return ImageFont.truetype(path, px, index=idx) if idx is not None else ImageFont.truetype(path, px)
    except Exception:
        return ImageFont.load_default()


def _fit(draw, text, path, target_w, start_px, idx=None):
    px = start_px
    f = _tf(path, px, idx)
    while px > 12:
        f = _tf(path, px, idx)
        if draw.textlength(text, font=f) <= target_w:
            return f
        px -= 2
    return f


def _center(draw, text, font, y, fill, tracking=0):
    if tracking:
        total = sum(draw.textlength(c, font=font) + tracking for c in text) - tracking
        x = (S - total) / 2
        for c in text:
            draw.text((x, y), c, font=font, fill=fill)
            x += draw.textlength(c, font=font) + tracking
    else:
        w = draw.textlength(text, font=font)
        draw.text(((S - w) / 2, y), text, font=font, fill=fill)


def build_episode_cover(guest_pid, recipes, members, title=None, episode=None, host_pid=HOST_PID):
    """Return a 1500x1500 RGB Pillow cover pairing host + guest engraved portraits."""
    if guest_pid not in recipes or not vbp.is_signed(recipes[guest_pid]):
        raise SystemExit(f"guest {guest_pid!r} has no signed portrait recipe")
    host = recipes.get(host_pid)

    img = Image.new("RGB", (S, S), PAGE)
    d = ImageDraw.Draw(img)
    d.rectangle([60, 60, S - 60, S - 60], outline=(38, 33, 24), width=2)

    guest_id = _identity(guest_pid, recipes[guest_pid], members)
    host_id = _identity(host_pid, host, members) if host else {"name": "Elena Voss", "color": "#94a3b8"}

    # Two portraits, side by side, centred on the middle band (clear of the title).
    ph = 470
    guest_img = portrait_raster.render_recipe(recipes[guest_pid], size=ph, mode="full", ink=INK, coach_color=guest_id["color"])
    portraits = [(guest_img, guest_id)]
    if host:
        host_img = portrait_raster.render_recipe(host, size=ph, mode="full", ink=INK, coach_color=host_id["color"])
        portraits = [(host_img, host_id), (guest_img, guest_id)]

    gap = 40
    total_w = sum(p.size[0] for p, _ in portraits) + gap * (len(portraits) - 1)
    x = (S - total_w) // 2
    py = 440
    for pim, ident in portraits:
        pw, phh = pim.size
        img.paste(pim, (x, py), pim)
        # name plate under each portrait
        nf = _fit(d, ident["name"].upper(), MONOB, pw + 40, 40)
        nw = d.textlength(ident["name"].upper(), font=nf)
        d.text((x + (pw - nw) / 2, py + phh + 10), ident["name"].upper(), font=nf, fill=MUTED)
        x += pw + gap

    # Header + title text.
    _center(d, "A PUBLIC N=1 HEALTH EXPERIMENT", _fit(d, "A PUBLIC N=1 HEALTH EXPERIMENT", MONO, 900, 34), 150, MUTED, tracking=6)
    _center(d, "THE PANEL", _fit(d, "THE PANEL", DISP, 1000, 210, idx=1), 195, EMBER)
    if episode is not None:
        _center(d, f"EPISODE {episode}", _fit(d, f"EPISODE {episode}", MONOB, 500, 40), 1005, MUTED, tracking=4)
    if title:
        _center(d, title.upper(), _fit(d, title.upper(), DISP, 1240, 150, idx=1), 1050, INK)
    _center(d, "illustration: commissioned, AI-assisted", _tf(MONO, 30), 1310, (110, 102, 88))
    _center(d, "averagejoematt.com", _tf(MONOB, 36), 1360, MUTED)
    return img


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--guest", required=True, help="guest persona_id (e.g. sarah_chen)")
    ap.add_argument("--host", default=HOST_PID)
    ap.add_argument("--title", default=None)
    ap.add_argument("--episode", type=int, default=None)
    ap.add_argument("--out", default="/tmp/panel_episode_cover.jpg")
    args = ap.parse_args(argv)

    recipes = vbp.load_recipes()
    members = _members()
    img = build_episode_cover(args.guest, recipes, members, title=args.title, episode=args.episode, host_pid=args.host)
    img.save(args.out, "JPEG", quality=90)
    print(f"✅ episode cover → {args.out} {img.size}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
