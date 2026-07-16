"""cover_placeholder.py — the DESIGNED missing-cover spine (brief §4).

"Missing-cover placeholder is *designed*, not broken": a generated cover in the
house palette with the title in the display face and the author beneath. The
empty state of one book honors the same honesty as the empty state of a chart —
it never looks like a broken image. Pillow, in the ink/ember palette
(`DESIGN_SYSTEM_V5`). Returns JPEG bytes.
"""

from __future__ import annotations

import io
import os

# House palette (DESIGN_SYSTEM_V5 — ink void background, AA ember accent, warm ink type)
_BG = (14, 12, 8)  # --ink-void #0E0C08
_EMBER = (163, 78, 19)  # AA ember #A34E13
_TITLE = (232, 225, 212)  # warm off-white
_AUTHOR = (150, 140, 125)  # muted ink

_W, _H = 600, 900  # 2:3 cover ratio
_FONTS_DIR = os.path.join(os.path.dirname(__file__), "..", "fonts")
# v5 brand fonts (the retired Bebas/Space Mono subsets had no basic-Latin glyphs —
# they rendered placeholders as tofu; Fraunces + IBM Plex Mono are the live-site faces).
_DISPLAY = os.path.join(_FONTS_DIR, "fraunces-400.ttf")
_MONO = os.path.join(_FONTS_DIR, "ibm-plex-mono-400.ttf")


def _font(path: str, size: int):
    from PIL import ImageFont

    try:
        return ImageFont.truetype(path, size)
    except Exception:  # noqa: BLE001 — bundled font missing → degrade, never crash
        return ImageFont.load_default()


def _wrap(draw, text: str, font, max_width: int) -> list[str]:
    words = (text or "").split()
    lines: list[str] = []
    cur = ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if draw.textlength(trial, font=font) <= max_width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def render(title: str, author: str = "") -> bytes:
    """Render a designed placeholder cover → JPEG bytes."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (_W, _H), _BG)
    draw = ImageDraw.Draw(img)

    margin = 56
    # spine accent — a quiet ember rule down the left edge
    draw.rectangle([margin - 18, margin, margin - 12, _H - margin], fill=_EMBER)

    title_font = _font(_DISPLAY, 76)
    author_font = _font(_MONO, 24)
    max_w = _W - 2 * margin

    title_lines = _wrap(draw, (title or "Untitled").upper(), title_font, max_w)[:6]
    y = int(_H * 0.30)
    for line in title_lines:
        draw.text((margin, y), line, fill=_TITLE, font=title_font)
        y += 78

    if author:
        y += 24
        for line in _wrap(draw, author, author_font, max_w)[:2]:
            draw.text((margin, y), line, fill=_AUTHOR, font=author_font)
            y += 32

    # bottom ember tick — the house "earned glow" signature, restrained
    draw.rectangle([margin, _H - margin, margin + 64, _H - margin + 5], fill=_EMBER)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=88, optimize=True)
    buf.seek(0)
    return buf.read()
