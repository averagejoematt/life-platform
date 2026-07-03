"""Regenerate the podcast cover art for The Panel (#374).

Apple/Spotify require a square 1400-3000px cover that RESOLVES, or they reject
the feed. This produces the 1500x1500 cover referenced by the feed's
<itunes:image> and uploaded once to s3://<bucket>/generated/panelcast/cover.jpg
(viewer URL https://averagejoematt.com/panelcast/cover.jpg).

On-brand: the tokens.css palette (page #0E0C08, ink #ECE3D2, ember #DD7A37) and
a data-waveform motif. Uses full macOS system fonts because the repo's bundled
webfonts (lambdas/fonts/*.ttf) are subsetted to the site's glyphs and render
arbitrary cover text as tofu. Run locally, then:
    python3 scripts/make_panelcast_cover.py
    aws s3 cp /tmp/panelcast_cover.jpg \\
      s3://matthew-life-platform/generated/panelcast/cover.jpg \\
      --content-type image/jpeg --cache-control "max-age=86400, public"
"""

import math

from PIL import Image, ImageDraw, ImageFont

PAGE = (14, 12, 8)
INK = (236, 227, 210)
MUTED = (169, 159, 140)
EMBER = (221, 122, 55)
S = 1500
SUP = "/System/Library/Fonts/Supplemental"
DISP = f"{SUP}/Avenir Next Condensed.ttc"  # heavy condensed display
MONO = f"{SUP}/Courier New.ttf"
MONOB = f"{SUP}/Courier New Bold.ttf"

img = Image.new("RGB", (S, S), PAGE)
d = ImageDraw.Draw(img)
d.rectangle([60, 60, S - 60, S - 60], outline=(38, 33, 24), width=2)


def disp(px, idx=1):  # Avenir Next Condensed Bold-ish face
    return ImageFont.truetype(DISP, px, index=idx)


def fit(text, path, target_w, start_px, idx=None):
    px = start_px
    while px > 10:
        f = ImageFont.truetype(path, px, index=idx) if idx is not None else ImageFont.truetype(path, px)
        if d.textlength(text, font=f) <= target_w:
            return f
        px -= 2
    return f


def center(text, font, y, fill, tracking=0):
    if tracking:
        total = sum(d.textlength(c, font=font) + tracking for c in text) - tracking
        x = (S - total) / 2
        for c in text:
            d.text((x, y), c, font=font, fill=fill)
            x += d.textlength(c, font=font) + tracking
    else:
        w = d.textlength(text, font=font)
        d.text(((S - w) / 2, y), text, font=font, fill=fill)


# waveform band
cx, cy = S // 2, 700
n = 47
for i in range(n):
    t = i / (n - 1)
    env = (math.sin(t * math.pi) ** 1.6) * (0.55 + 0.45 * math.sin(t * 9.2 + 0.7) ** 2)
    h = 18 + env * 300
    x = 160 + i * ((S - 320) / n)
    col = EMBER if (i % 6 in (0, 3)) else (118, 62, 34)
    d.rounded_rectangle([x, cy - h / 2, x + ((S - 320) / n) * 0.5, cy + h / 2], radius=6, fill=col)
d.line([160, cy, S - 160, cy], fill=(58, 50, 37), width=2)

# text
center("A PUBLIC N=1 HEALTH EXPERIMENT", fit("A PUBLIC N=1 HEALTH EXPERIMENT", MONO, 900, 34), 205, MUTED, tracking=6)
center("THE MEASURED LIFE", fit("THE MEASURED LIFE", DISP, 1220, 190, idx=1), 250, INK)
center("THE PANEL", fit("THE PANEL", DISP, 1000, 250, idx=1), 940, EMBER)
center("ELENA VOSS + A ROTATING AI COACH", fit("ELENA VOSS + A ROTATING AI COACH", MONO, 1000, 34), 1235, MUTED, tracking=3)
center("averagejoematt.com", ImageFont.truetype(MONOB, 40), 1310, INK)

img.save("/tmp/panelcast_cover.jpg", "JPEG", quality=90)
print("ok", img.size)
