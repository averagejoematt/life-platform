#!/usr/bin/env python3
"""scripts/v9_og_images.py — the share cards for the v9 front page and every published chapter (2026-11-14, sprint II).

A link to the site shared in a message or on LinkedIn showed one wordmark for every page. This draws a 1200×630 PNG per
page that matters most — the front page (the question, the pounds since day one, The Line in miniature) and each
PUBLISHED chapter (its number, title, dek and days) — from the publication snapshot the build reads, so a card can only
carry what the site already publishes: a held, skipped or pending week has no chapter object with a title and gets no
card. Deterministic: the same snapshot draws the same bytes.

Runs in the deploy (deploy/www_build_target.sh) before the Astro build, writing www/public/assets/og/v9/; the pages
point their og:image at a card only when it exists at build time (www/src/lib/og.js). Each card's name carries a hash of
its bytes, because the deploy caches assets/ for a year. Without Pillow it writes nothing
and says so — the pages keep the site-wide wordmark.

Usage: python3 scripts/v9_og_images.py [--snapshot www/content/snapshot] [--out www/public/assets/og/v9]
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import sys
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONTS = os.path.join(ROOT, "www", "public", "assets", "fonts", "v9")
W, H = 1200, 630
PAPER, INK, MUTED, RULE, COBALT = (244, 244, 240), (18, 18, 18), (92, 92, 88), (201, 201, 195), (27, 63, 214)
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]


def words(iso: str | None, short: bool = False) -> str:
    if not iso or not re.match(r"^\d{4}-\d{2}-\d{2}", iso):
        return ""
    d = date.fromisoformat(iso[:10])
    m = MONTHS[d.month - 1]
    return f"{d.day} {m[:3] if short else m}" + ("" if short else f" {d.year}")


def load(snapshot: str, name: str):
    path = os.path.join(snapshot, name)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    return doc.get("items", doc) if isinstance(doc, dict) and "items" in doc else doc


def font(name: str, size: int, weight: int | None = None):
    from PIL import ImageFont

    f = ImageFont.truetype(os.path.join(FONTS, name), size)
    if weight is not None:
        try:
            f.set_variation_by_axes([weight] + ([100] if "archivo" in name else []))
        except Exception:  # noqa: BLE001 — a static face has no axes; the default weight stands
            pass
    return f


def wrap(draw, text: str, f, width: int, max_lines: int) -> list[str]:
    out: list[str] = []
    line = ""
    for w in text.split():
        trial = f"{line} {w}".strip()
        if draw.textlength(trial, font=f) <= width:
            line = trial
            continue
        out.append(line)
        line = w
        if len(out) == max_lines:
            break
    if len(out) < max_lines and line:
        out.append(line)
    if len(out) == max_lines and " ".join(out) != text.strip():
        last = out[-1]
        while last and draw.textlength(last + "…", font=f) > width:
            last = last.rsplit(" ", 1)[0] if " " in last else last[:-1]
        out[-1] = last.rstrip(",;:—– ") + "…"
    return out


def frame(draw, right: str):
    draw.rectangle([0, 0, W, 8], fill=INK)
    mono = font("ibm-plex-mono-500-latin.woff2", 22)
    draw.text((64, 44), "AVERAGE JOE MATT", font=mono, fill=INK)
    draw.text((W - 64, 44), right, font=mono, fill=MUTED, anchor="ra")
    draw.line([64, H - 64, W - 64, H - 64], fill=RULE, width=2)
    draw.text((64, H - 52), "averagejoematt.com", font=font("ibm-plex-mono-400-latin.woff2", 20), fill=MUTED)


def line_points(days: list[dict], box: tuple[int, int, int, int]) -> list[tuple[float, float]]:
    vals = [d for d in days if d.get("value") is not None and not d.get("gap")]
    if len(vals) < 2:
        return []
    x0, y0, x1, y1 = box
    t = lambda iso: date.fromisoformat(iso).toordinal()  # noqa: E731
    a, b = t(days[0]["date"]), t(days[-1]["date"])
    lo, hi = min(v["value"] for v in vals), max(v["value"] for v in vals)
    return [
        (x0 + (t(v["date"]) - a) / max(1, b - a) * (x1 - x0), y0 + (1 - (v["value"] - lo) / ((hi - lo) or 1)) * (y1 - y0)) for v in vals
    ]


def save(img, out: str, key: str) -> str:
    """`<key>.<sha8>.png`: the deploy uploads assets/ with a one-year immutable cache, so a card whose content changes
    (the front page's, daily) must change its name; www/src/lib/og.js finds it by key."""
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    data = buf.getvalue()
    path = os.path.join(out, f"{key}.{hashlib.sha256(data).hexdigest()[:8]}.png")
    with open(path, "wb") as f:
        f.write(data)
    return path


def home_card(snapshot: str, out: str) -> str | None:
    from PIL import Image, ImageDraw

    ed = load(snapshot, "editions.json")
    ed = ed[0] if isinstance(ed, list) and ed else ed
    series = load(os.path.join(snapshot, "series"), "weight_lbs.json")
    journey = load(snapshot, "journey.json") or {}
    if not isinstance(ed, dict) or not isinstance(series, dict):
        return None
    start = ((ed.get("blocks") or {}).get("today") or {}).get("data", {}).get("start_date") or journey.get("start_date")
    days = [d for d in series.get("days") or [] if not start or d["date"] >= start]
    vals = [d for d in days if d.get("value") is not None and not d.get("gap")]
    if not vals:
        return None
    first_v = journey.get("start_weight_lbs") or vals[0]["value"]
    lost = first_v - vals[-1]["value"]
    img = Image.new("RGB", (W, H), PAPER)
    dr = ImageDraw.Draw(img)
    frame(dr, f"DAY {ed.get('day_n')} · {words(ed.get('as_of'), short=True).upper()}" if ed.get("day_n") is not None else "")
    title = font("archivo-latin.woff2", 64, 800)
    y = 112
    for ln in wrap(dr, "Can an ordinary person engineer an extraordinary life?", title, 620, 4):
        dr.text((64, y), ln, font=title, fill=INK)
        y += 70
    big = font("archivo-latin.woff2", 150, 800)
    stat = f"{abs(lost):.1f}"
    dr.text((W - 64, 112), stat, font=big, fill=COBALT, anchor="ra")
    unit = font("archivo-latin.woff2", 30, 700)
    dr.text((W - 64, 290), f"lb {'lighter' if lost >= 0 else 'heavier'} in {len(days)} days", font=unit, fill=INK, anchor="ra")
    dr.text((W - 64, 330), f"{len(vals)} weigh-ins, every one drawn", font=font("archivo-latin.woff2", 22, 400), fill=MUTED, anchor="ra")
    pts = line_points(days, (740, 400, W - 72, 520))
    if pts:
        dr.line(pts, fill=INK, width=4, joint="curve")
        x, y2 = pts[-1]
        dr.ellipse([x - 9, y2 - 9, x + 9, y2 + 9], fill=COBALT)
    dek = font("newsreader-latin.woff2", 28)
    y = max(y + 16, 420)
    for ln in wrap(dr, "An ordinary man, AI coaches graded in public, and the data on his body.", dek, 600, 2):
        dr.text((64, y), ln, font=dek, fill=MUTED)
        y += 36
    return save(img, out, "home")


def chapter_card(c: dict, out: str) -> str | None:
    from PIL import Image, ImageDraw

    if c.get("status") != "published" or c.get("visibility") != "public" or not c.get("title"):
        return None
    img = Image.new("RGB", (W, H), PAPER)
    dr = ImageDraw.Draw(img)
    a, b = c.get("covers_start"), c.get("covers_end")
    span = (
        f"{words(a, short=True)} – {words(b, short=True)}".upper()
        if a and b
        else (words(c.get("data_through") or c.get("date"), short=True).upper())
    )
    frame(dr, f"{(c.get('week_label') or '').upper()} · {span}".strip(" ·"))
    n = c.get("week")
    num = font("archivo-latin.woff2", 220, 800)
    left = 64
    if isinstance(n, int) and n >= 1:
        dr.text((56, 92), f"{n:02d}", font=num, fill=COBALT)
        left = 64 + int(dr.textlength(f"{n:02d}", font=num)) + 40
    dr.text((left, 112), "CHAPTER", font=font("ibm-plex-mono-400-latin.woff2", 22), fill=MUTED)
    title = font("archivo-latin.woff2", 68, 800)
    y = 150
    for ln in wrap(dr, c["title"], title, W - 64 - left, 2):
        dr.text((left, y), ln, font=title, fill=INK)
        y += 76
    dek = font("newsreader-latin.woff2", 30)
    y = max(y + 18, 330)
    for ln in wrap(dr, c.get("excerpt") or c.get("summary") or "", dek, W - 128, 5):
        dr.text((64, y), ln, font=dek, fill=MUTED)
        y += 40
    return save(img, out, c["id"])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--snapshot", default=os.path.join(ROOT, "www", "content", "snapshot"))
    ap.add_argument("--out", default=os.path.join(ROOT, "www", "public", "assets", "og", "v9"))
    args = ap.parse_args()
    try:
        import PIL  # noqa: F401
    except ImportError:
        print("v9_og_images: Pillow is not installed — no share cards drawn; pages keep the site-wide wordmark")
        return 0
    os.makedirs(args.out, exist_ok=True)
    for old in os.listdir(args.out):  # a card for a chapter that is no longer published must not outlive it
        if old.endswith(".png"):
            os.remove(os.path.join(args.out, old))
    made = []
    if home_card(args.snapshot, args.out):
        made.append("home")
    for c in load(args.snapshot, "chapters.json") or []:
        if isinstance(c, dict) and chapter_card(c, args.out):
            made.append(c["id"])
    print(f"v9_og_images: {len(made)} cards → {os.path.relpath(args.out, ROOT)} ({', '.join(made)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
