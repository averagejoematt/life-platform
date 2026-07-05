"""portrait_raster.py — rasterize a signed coach-portrait recipe (#593, ADR-106).

The site renders the layered-SVG recipe (config/portraits/*.json) in the browser via
portraits.js. Off-site surfaces — OG share cards, email avatars, podcast episode art —
are Pillow-drawn PNGs and cannot embed an SVG. This module is the one code-drawn
rasterizer that turns the SAME recipe into a Pillow image, so the faces travel from a
single source of truth (no re-sketched raster, ADR-106 §1).

Pure-stdlib + Pillow (already bundled with the OG image lambda). No external asset fetch,
no cairosvg — a compact SVG-path flattener (M/L/H/V/C/S/Q/T/A/Z) rasterized with
supersampling for clean antialiased edges. Deterministic: same recipe + params → same
pixels, mirroring portraits.js.

Two render modes:
  * "mono" — ink contours + filled dots only, tone fills skipped. The engraved stamp used
    for email avatars ("ink on transparent", either theme's ink colour).
  * "full" — palette tones (skin/hair/cloth/blush) filled under the ink contours; the
    `accent` tone resolves to the coach colour. Used for OG cards + episode art.

renderPortrait() in portraits.js is the visual authority; this mirrors its DRAW_ORDER and
seeded frame so the two stay recognisably the same portrait.
"""

import math
import re

from PIL import Image, ImageDraw

# Draw order (background → foreground), mirroring portraits.js DRAW_ORDER. `frame` is
# composed first (behind the bust) when present; `hatch` is the coach-colour shading.
DRAW_ORDER = [
    "hatch",
    "bust",
    "head",
    "hair",
    "brow",
    "eyes-closed",
    "eyes-open",
    "glasses",
    "nose",
    "mouth-rest",
    "mouth-a",
    "mouth-b",
]

# Layers hidden at rest in the animated SVG (blink / speech frames). The static raster
# shows the resting face, so these never draw. Mirrors portraits.js HIDDEN_AT_REST.
HIDDEN_AT_REST = {"eyes-closed", "mouth-a", "mouth-b"}

VIEWBOX_W, VIEWBOX_H = 100.0, 120.0

# Supersample factor for antialiasing — render at N× then LANCZOS-downscale.
_SS = 4

_TOKEN_RE = re.compile(r"[MmLlHhVvCcSsQqTtAaZz]|-?\d*\.?\d+(?:[eE][+-]?\d+)?")
_CMD_RE = re.compile(r"[MmLlHhVvCcSsQqTtAaZz]")


def _tokenize(d):
    return _TOKEN_RE.findall(d)


def _flatten_cubic(p0, p1, p2, p3, steps=18):
    pts = []
    for i in range(1, steps + 1):
        t = i / steps
        mt = 1 - t
        x = mt * mt * mt * p0[0] + 3 * mt * mt * t * p1[0] + 3 * mt * t * t * p2[0] + t * t * t * p3[0]
        y = mt * mt * mt * p0[1] + 3 * mt * mt * t * p1[1] + 3 * mt * t * t * p2[1] + t * t * t * p3[1]
        pts.append((x, y))
    return pts


def _flatten_quad(p0, p1, p2, steps=14):
    pts = []
    for i in range(1, steps + 1):
        t = i / steps
        mt = 1 - t
        x = mt * mt * p0[0] + 2 * mt * t * p1[0] + t * t * p2[0]
        y = mt * mt * p0[1] + 2 * mt * t * p1[1] + t * t * p2[1]
        pts.append((x, y))
    return pts


def _flatten_arc(p0, rx, ry, phi_deg, large_arc, sweep, p1, steps=24):
    # SVG arc (endpoint param) → center param, then sample. Ref: SVG impl notes F.6.
    x0, y0 = p0
    x1, y1 = p1
    if rx == 0 or ry == 0 or (x0 == x1 and y0 == y1):
        return [p1]
    rx, ry = abs(rx), abs(ry)
    phi = math.radians(phi_deg)
    cosp, sinp = math.cos(phi), math.sin(phi)
    dx, dy = (x0 - x1) / 2.0, (y0 - y1) / 2.0
    x1p = cosp * dx + sinp * dy
    y1p = -sinp * dx + cosp * dy
    # Correct out-of-range radii.
    lam = (x1p * x1p) / (rx * rx) + (y1p * y1p) / (ry * ry)
    if lam > 1:
        s = math.sqrt(lam)
        rx *= s
        ry *= s
    num = rx * rx * ry * ry - rx * rx * y1p * y1p - ry * ry * x1p * x1p
    den = rx * rx * y1p * y1p + ry * ry * x1p * x1p
    co = math.sqrt(max(0.0, num / den)) if den else 0.0
    if large_arc == sweep:
        co = -co
    cxp = co * (rx * y1p / ry)
    cyp = co * (-ry * x1p / rx)
    cx = cosp * cxp - sinp * cyp + (x0 + x1) / 2.0
    cy = sinp * cxp + cosp * cyp + (y0 + y1) / 2.0

    def ang(ux, uy, vx, vy):
        dot = ux * vx + uy * vy
        n = math.hypot(ux, uy) * math.hypot(vx, vy)
        a = math.acos(max(-1.0, min(1.0, dot / n))) if n else 0.0
        if ux * vy - uy * vx < 0:
            a = -a
        return a

    theta1 = ang(1, 0, (x1p - cxp) / rx, (y1p - cyp) / ry)
    dtheta = ang((x1p - cxp) / rx, (y1p - cyp) / ry, (-x1p - cxp) / rx, (-y1p - cyp) / ry)
    if not sweep and dtheta > 0:
        dtheta -= 2 * math.pi
    elif sweep and dtheta < 0:
        dtheta += 2 * math.pi
    pts = []
    for i in range(1, steps + 1):
        t = theta1 + dtheta * (i / steps)
        xt = cosp * rx * math.cos(t) - sinp * ry * math.sin(t) + cx
        yt = sinp * rx * math.cos(t) + cosp * ry * math.sin(t) + cy
        pts.append((xt, yt))
    return pts


def path_to_subpaths(d):
    """Flatten an SVG path 'd' string into a list of subpaths (each a list of (x, y))."""
    toks = _tokenize(d)
    i = 0
    cur = (0.0, 0.0)
    start = (0.0, 0.0)
    prev_cubic_ctrl = None
    prev_quad_ctrl = None
    subpaths = []
    cur_sub = []
    cmd = None

    def num():
        nonlocal i
        v = float(toks[i])
        i += 1
        return v

    while i < len(toks):
        if _CMD_RE.match(toks[i]):
            cmd = toks[i]
            i += 1
        rel = cmd.islower()
        c = cmd.upper()
        if c == "M":
            x, y = num(), num()
            if rel:
                x, y = cur[0] + x, cur[1] + y
            if cur_sub:
                subpaths.append(cur_sub)
            cur = (x, y)
            start = cur
            cur_sub = [cur]
            prev_cubic_ctrl = prev_quad_ctrl = None
            cmd = "l" if rel else "L"  # subsequent coords are implicit lineto
        elif c == "L":
            x, y = num(), num()
            if rel:
                x, y = cur[0] + x, cur[1] + y
            cur = (x, y)
            cur_sub.append(cur)
            prev_cubic_ctrl = prev_quad_ctrl = None
        elif c == "H":
            x = num()
            x = cur[0] + x if rel else x
            cur = (x, cur[1])
            cur_sub.append(cur)
            prev_cubic_ctrl = prev_quad_ctrl = None
        elif c == "V":
            y = num()
            y = cur[1] + y if rel else y
            cur = (cur[0], y)
            cur_sub.append(cur)
            prev_cubic_ctrl = prev_quad_ctrl = None
        elif c in ("C", "S"):
            if c == "C":
                c1 = (num(), num())
                c2 = (num(), num())
                end = (num(), num())
                if rel:
                    c1 = (cur[0] + c1[0], cur[1] + c1[1])
                    c2 = (cur[0] + c2[0], cur[1] + c2[1])
                    end = (cur[0] + end[0], cur[1] + end[1])
            else:  # S — smooth cubic; first control is reflection of prev
                c2 = (num(), num())
                end = (num(), num())
                if rel:
                    c2 = (cur[0] + c2[0], cur[1] + c2[1])
                    end = (cur[0] + end[0], cur[1] + end[1])
                if prev_cubic_ctrl:
                    c1 = (2 * cur[0] - prev_cubic_ctrl[0], 2 * cur[1] - prev_cubic_ctrl[1])
                else:
                    c1 = cur
            cur_sub.extend(_flatten_cubic(cur, c1, c2, end))
            cur = end
            prev_cubic_ctrl = c2
            prev_quad_ctrl = None
        elif c in ("Q", "T"):
            if c == "Q":
                c1 = (num(), num())
                end = (num(), num())
                if rel:
                    c1 = (cur[0] + c1[0], cur[1] + c1[1])
                    end = (cur[0] + end[0], cur[1] + end[1])
            else:  # T — smooth quad
                end = (num(), num())
                if rel:
                    end = (cur[0] + end[0], cur[1] + end[1])
                if prev_quad_ctrl:
                    c1 = (2 * cur[0] - prev_quad_ctrl[0], 2 * cur[1] - prev_quad_ctrl[1])
                else:
                    c1 = cur
            cur_sub.extend(_flatten_quad(cur, c1, end))
            cur = end
            prev_quad_ctrl = c1
            prev_cubic_ctrl = None
        elif c == "A":
            rx, ry = num(), num()
            rot = num()
            large = num()
            sweep = num()
            end = (num(), num())
            if rel:
                end = (cur[0] + end[0], cur[1] + end[1])
            cur_sub.extend(_flatten_arc(cur, rx, ry, rot, int(large), int(sweep), end))
            cur = end
            prev_cubic_ctrl = prev_quad_ctrl = None
        elif c == "Z":
            if cur_sub:
                cur_sub.append(start)
                subpaths.append(cur_sub)
            cur_sub = []
            cur = start
            prev_cubic_ctrl = prev_quad_ctrl = None
        else:
            i += 1  # unknown — skip defensively
    if cur_sub:
        subpaths.append(cur_sub)
    return subpaths


def _seeded_frame_elems(seed):
    """Deterministic ring + measuring ticks — the Python mirror of portraits.js
    seededFrame() (same FNV seed, same geometry). Returned as stroked path 'd' strings."""

    # mulberry32, matching sigils.js.
    def mulberry32(a):
        state = a & 0xFFFFFFFF

        def rnd():
            nonlocal state
            state = (state + 0x6D2B79F5) & 0xFFFFFFFF
            t = state
            t = ((t ^ (t >> 15)) * (t | 1)) & 0xFFFFFFFF
            t ^= (t + (((t ^ (t >> 7)) * (t | 61)) & 0xFFFFFFFF)) & 0xFFFFFFFF
            t &= 0xFFFFFFFF
            return ((t ^ (t >> 14)) & 0xFFFFFFFF) / 4294967296.0

        return rnd

    rnd = mulberry32(seed)
    C, CY, R = 50.0, 46.0, 42.0
    tick_n = [6, 8, 12][seed % 3]
    rot = rnd() * 360.0
    elems = []
    # ring — approximate the circle with an arc pair
    elems.append({"d": f"M{C - R},{CY} A{R},{R} 0 1 0 {C + R},{CY} A{R},{R} 0 1 0 {C - R},{CY} Z"})
    for i in range(tick_n):
        a = math.radians(rot + (360.0 / tick_n) * i)
        x1, y1 = C + (R - 5) * math.cos(a), CY + (R - 5) * math.sin(a)
        x2, y2 = C + R * math.cos(a), CY + R * math.sin(a)
        elems.append({"d": f"M{x1},{y1} L{x2},{y2}"})
    return elems


def _hex(c):
    c = c.lstrip("#")
    return (int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16))


def render_recipe(recipe, size=192, mode="mono", ink=(236, 227, 210), coach_color="#a99f8c", with_frame=True):
    """Rasterize a portrait recipe to a transparent RGBA Pillow image (square-ish,
    height = size, width = size * 100/120).

    mode="mono": ink strokes + filled dots only (tones skipped) — the email stamp.
    mode="full": palette tones filled beneath the ink contours; `accent` → coach_color.
    ink: RGB of the contour/ink colour (theme-dependent for mono).
    """
    ss = _SS
    h = size * ss
    w = int(round(size * (VIEWBOX_W / VIEWBOX_H))) * ss
    sx = w / VIEWBOX_W
    sy = h / VIEWBOX_H
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    palette = recipe.get("palette") or {}
    layers = recipe.get("layers") or {}

    def tone_rgb(tone):
        if tone == "accent":
            hexv = palette.get("accent") or coach_color
        else:
            hexv = palette.get(tone)
        if not hexv:
            return ink
        try:
            return _hex(hexv)
        except Exception:
            return ink

    def to_px(pts):
        return [(x * sx, y * sy) for (x, y) in pts]

    stroke_px = max(2, int(round(1.6 * ss)))

    def draw_elem(el):
        subs = path_to_subpaths(el["d"])
        tone = el.get("tone")
        filled = el.get("filled")
        if tone is not None:
            if mode == "mono":
                return  # tones are colour fills; the mono stamp is ink-only
            color = tone_rgb(tone)
            for sub in subs:
                if len(sub) >= 3:
                    draw.polygon(to_px(sub), fill=color + (255,))
            return
        if filled:
            for sub in subs:
                if len(sub) >= 3:
                    draw.polygon(to_px(sub), fill=ink + (255,))
            return
        # stroked contour
        for sub in subs:
            px = to_px(sub)
            if len(px) >= 2:
                draw.line(px, fill=ink + (255,), width=stroke_px, joint="curve")
                # round caps
                r = stroke_px / 2.0
                for cx, cy in (px[0], px[-1]):
                    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=ink + (255,))

    if with_frame:
        frame_elems = layers.get("frame") or _seeded_frame_elems(_fnv1a(str(recipe.get("persona_id", ""))))
        # frame is ink-stroked regardless of mode
        for el in frame_elems:
            if "tone" not in el and not el.get("filled"):
                draw_elem(el)
            else:
                draw_elem(el)

    for lid in DRAW_ORDER:
        if lid in HIDDEN_AT_REST:
            continue
        for el in layers.get(lid) or []:
            draw_elem(el)

    return img.resize((w // ss, h // ss), Image.LANCZOS)


def _fnv1a(s):
    h = 0x811C9DC5
    for ch in s:
        h ^= ord(ch)
        h = (h * 0x01000193) & 0xFFFFFFFF
    return h
