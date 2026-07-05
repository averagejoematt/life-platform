"""og_coach_cards.py — per-coach OG share cards + episode-art frame (#593, ADR-106).

The engraved coach portraits (config/portraits/*.json) travel off-site: each coach gets a
1200x630 share card featuring the approved portrait + identity, drawn entirely in code from
the same recipe the site renders. Portraits are rasterized by web.portrait_raster (the one
code-drawn renderer); this module composes them into brand cards.

── Share-card engine adoption (coordination w/ #595) ───────────────────────────────────
Issue #595 ships "the share-card engine — one code-drawn renderer for every off-site card."
This module is an ADOPTER, not a second engine. All brand-frame drawing goes through the
thin `_Engine` adapter below, whose surface is deliberately tiny so the merge is a one-class
swap. The interface this file ASSUMES of the engine:

    engine.canvas(accent_rgb) -> (PIL.Image "RGB" 1200x630, ImageDraw)   # brand base: bg,
        top accent rule (tinted `accent_rgb`), bottom bar.
    engine.header(draw, kicker, sub=None)                                # top-left brand id
    engine.footer(draw, left=None, right=None)                           # bottom rule text
    engine.font(role, size) -> ImageFont   # role in {"display","mono","mono_bold"}
    engine.W, engine.H, engine.INK, engine.MUTED, engine.FAINT, engine.BG

Until #595 lands, `_Engine` is implemented locally by reusing the OG image lambda's existing
tokens + font loader (web.og_image_lambda) — same fonts, same palette, no new asset fetch.
Reconciliation at merge: replace the local `_Engine` body with a bind to #595's engine object.
No other symbol in this file needs to change.
"""

import io
import json

from PIL import Image

from web import og_image_lambda as _og, portrait_raster


class _Engine:
    """Local stand-in for the #595 share-card engine (see module docstring)."""

    W = _og.W
    H = _og.H
    BG = _og.BG
    INK = _og.TEXT
    MUTED = _og.MUTED
    FAINT = _og.FAINT

    _FONTS = {
        "display": _og.FONT_DISPLAY,
        "mono": _og.FONT_MONO,
        "mono_bold": _og.FONT_MONO_BOLD,
    }

    def font(self, role, size):
        return _og._font(self._FONTS[role], size)

    def canvas(self, accent_rgb):
        from PIL import ImageDraw

        img = Image.new("RGB", (self.W, self.H), self.BG)
        draw = ImageDraw.Draw(img)
        draw.rectangle([0, 0, self.W, 3], fill=accent_rgb)  # top accent rule
        draw.rectangle([0, self.H - 40, self.W, self.H], fill=(6, 10, 8))  # bottom bar
        return img, draw

    def header(self, draw, kicker, sub=None):
        draw.text((48, 28), "averagejoematt.com", fill=self.MUTED, font=self.font("mono", 13))
        draw.text((48, 52), kicker.upper(), fill=(34, 197, 94), font=self.font("mono", 11))
        if sub:
            draw.text((48, 74), sub, fill=self.FAINT, font=self.font("mono", 11))

    def footer(self, draw, left=None, right=None):
        if left:
            draw.text((48, self.H - 30), left, fill=self.FAINT, font=self.font("mono", 11))
        if right:
            draw.text((self.W - 48, self.H - 30), right, fill=self.FAINT, font=self.font("mono", 11), anchor="ra")


ENGINE = _Engine()


def _hex(c):
    c = (c or "#8aaa90").lstrip("#")
    return (int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16))


def coach_identity(persona_id, recipe, members):
    """Resolve display identity from the board roster (persona_id or an alias), falling
    back to the recipe. Returns {name, title, color}. Public-safe fields only."""
    m = (members or {}).get(persona_id)
    if not m:
        for a in recipe.get("aliases") or []:
            if a in (members or {}):
                m = members[a]
                break
    if m:
        return {"name": m.get("name") or persona_id, "title": m.get("title") or "AI Coach", "color": m.get("color") or "#8aaa90"}
    return {"name": persona_id.replace("_", " ").title(), "title": "AI Coach", "color": "#8aaa90"}


def _wrap(draw, text, font, max_w):
    words = text.split()
    lines, cur = [], ""
    for wd in words:
        trial = (cur + " " + wd).strip()
        if draw.textlength(trial, font=font) <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = wd
    if cur:
        lines.append(cur)
    return lines


def build_coach_card(persona_id, recipe, identity):
    """Compose a 1200x630 OG share card: engraved portrait + coach identity. Returns a
    Pillow RGB image. Deterministic — same recipe + identity → same pixels."""
    accent = _hex(identity["color"])
    img, draw = ENGINE.canvas(accent)
    ENGINE.header(draw, "The Board", sub="AI COACHING PANEL")

    # Portrait — full-colour engraving, coach-colour accent channel. Rendered tall on the
    # right third; a faint accent panel grounds it.
    port_h = 430
    portrait = portrait_raster.render_recipe(
        recipe, size=port_h, mode="full", ink=ENGINE.INK, coach_color=identity["color"], with_frame=True
    )
    pw, ph = portrait.size
    px = ENGINE.W - pw - 90
    py = (ENGINE.H - ph) // 2 + 6
    # subtle accent backing plate behind the portrait
    plate = Image.new("RGB", (pw + 60, ph + 60), (int(accent[0] * 0.10) + 8, int(accent[1] * 0.10) + 12, int(accent[2] * 0.10) + 10))
    img.paste(plate, (px - 30, py - 30))
    img.paste(portrait, (px, py), portrait)

    # Identity block — left column
    lx = 48
    draw.text((lx, 150), identity["name"].upper(), fill=ENGINE.INK, font=ENGINE.font("display", 68))
    # title, wrapped
    title_font = ENGINE.font("mono", 18)
    ty = 235
    for line in _wrap(draw, identity["title"], title_font, px - lx - 60):
        draw.text((lx, ty), line, fill=accent, font=title_font)
        ty += 26
    # disclosure line (ADR-106 honesty): these are fictional AI personas
    draw.text((lx, ty + 16), "A fictional AI advisor on The Measured Life.", fill=ENGINE.MUTED, font=ENGINE.font("mono", 14))
    draw.text((lx, ty + 44), "Portrait: commissioned, AI-assisted.", fill=ENGINE.FAINT, font=ENGINE.font("mono", 12))

    ENGINE.footer(draw, left="The Board · averagejoematt.com", right="illustrated by code")
    return img


def _is_signed(recipe):
    """Bundle gate (ADR-106 §3): only a recorded contact-sheet sign-off ships. Mirror of
    scripts/v4_build_portraits.is_signed — inlined so the lambda has no scripts dependency."""
    sign = (recipe.get("_meta") or {}).get("sign_off")
    return isinstance(sign, dict) and all(sign.get(k) for k in ("by", "date", "sheet"))


def load_signed_recipes_from_bundle(text):
    """Extract the signed recipe map from a generated portrait_data.js body. This is the
    exact bundle the site renders (already signed-only, ADR-106) — the lambda's one source
    of truth. Returns {persona_id: recipe}."""
    marker = "export const PORTRAITS = "
    start = text.index(marker) + len(marker)
    end = text.index(";", start)
    return json.loads(text[start:end])


def build_all_coach_cards(recipes, members):
    """Return {output_name: PIL.Image} for every signed recipe. output_name has no suffix
    (caller adds .png/.webp). Skips recipes the renderer can't handle, fail-soft."""
    out = {}
    for pid, recipe in sorted(recipes.items()):
        if not _is_signed(recipe):
            continue
        try:
            identity = coach_identity(pid, recipe, members)
            out[f"og-coach-{pid.replace('_', '-')}"] = build_coach_card(pid, recipe, identity)
        except Exception as e:  # never let one card fail the sweep
            print(f"[WARN] coach card {pid} failed: {e}")
    return out


def _s3_text(s3, bucket, key):
    return s3.get_object(Bucket=bucket, Key=key)["Body"].read().decode("utf-8")


def sweep_coach_cards(s3, bucket):
    """Daily-sweep entry for the OG image lambda: pull the signed portrait bundle + board
    roster from S3, write every coach card under generated/assets/images/. Fail-soft — a
    read error yields zero cards rather than raising into the daily OG sweep. Returns the
    list of card names written."""
    try:
        recipes = load_signed_recipes_from_bundle(_s3_text(s3, bucket, "site/assets/js/portrait_data.js"))
    except Exception as e:
        print(f"[WARN] coach cards: could not load portrait bundle: {e}")
        return []
    try:
        members = json.loads(_s3_text(s3, bucket, "config/board_of_directors.json")).get("members", {})
    except Exception as e:
        print(f"[WARN] coach cards: could not load board roster ({e}); using recipe-only identity")
        members = {}
    return render_coach_cards_to_s3(s3, bucket, recipes, members)


def render_coach_cards_to_s3(s3, bucket, recipes, members):
    """Write each coach card to generated/assets/images/ as PNG + WebP (ADR-046 prefix).
    Called from the OG image lambda's daily sweep. Returns the list of names written."""
    written = []
    for name, img in build_all_coach_cards(recipes, members).items():
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        s3.put_object(
            Bucket=bucket,
            Key=f"generated/assets/images/{name}.png",
            Body=buf.getvalue(),
            ContentType="image/png",
            CacheControl="max-age=86400",
        )
        try:
            wbuf = io.BytesIO()
            img.save(wbuf, format="WebP", quality=82, method=4)
            s3.put_object(
                Bucket=bucket,
                Key=f"generated/assets/images/{name}.webp",
                Body=wbuf.getvalue(),
                ContentType="image/webp",
                CacheControl="max-age=86400",
            )
        except Exception as e:
            print(f"[WARN] WebP encode failed for {name}: {e}")
        written.append(name)
    return written
