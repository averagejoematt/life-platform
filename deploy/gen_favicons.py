#!/usr/bin/env python3
"""
gen_favicons.py — Generate all favicon sizes for averagejoematt.com
Uses Pillow (pure Python, no system dependencies).
Run: python3 deploy/gen_favicons.py
"""
import subprocess, sys, os, math

try:
    from PIL import Image, ImageDraw
except ImportError:
    print("Installing Pillow...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "Pillow", "-q"])
    from PIL import Image, ImageDraw

OUT = "/Users/matthewwalker/Documents/Claude/averagejoematt-site/assets/icons"
os.makedirs(OUT, exist_ok=True)

# ── Write SVG (browsers use this natively — crisp at any resolution) ──────────
SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 256 256">
  <rect width="256" height="256" rx="52" fill="#080c0a"/>
  <circle cx="128" cy="52"  r="11" fill="#00e5a0"/>
  <circle cx="196" cy="94"  r="10" fill="#00e5a0"/>
  <circle cx="172" cy="178" r="10" fill="#00e5a0"/>
  <circle cx="84"  cy="178" r="10" fill="#00e5a0"/>
  <circle cx="60"  cy="94"  r="10" fill="#00e5a0"/>
  <line x1="128" y1="52"  x2="196" y2="94"  stroke="#00e5a0" stroke-width="2" opacity="0.35"/>
  <line x1="196" y1="94"  x2="172" y2="178" stroke="#00e5a0" stroke-width="2" opacity="0.35"/>
  <line x1="172" y1="178" x2="84"  y2="178" stroke="#00e5a0" stroke-width="2" opacity="0.35"/>
  <line x1="84"  y1="178" x2="60"  y2="94"  stroke="#00e5a0" stroke-width="2" opacity="0.35"/>
  <line x1="60"  y1="94"  x2="128" y2="52"  stroke="#00e5a0" stroke-width="2" opacity="0.35"/>
  <circle cx="128" cy="122" r="16" fill="#00e5a0"/>
  <line x1="128" y1="122" x2="128" y2="52"  stroke="#00e5a0" stroke-width="2" opacity="0.7"/>
  <line x1="128" y1="122" x2="196" y2="94"  stroke="#00e5a0" stroke-width="2" opacity="0.7"/>
  <line x1="128" y1="122" x2="172" y2="178" stroke="#00e5a0" stroke-width="2" opacity="0.7"/>
  <line x1="128" y1="122" x2="84"  y2="178" stroke="#00e5a0" stroke-width="2" opacity="0.7"/>
  <line x1="128" y1="122" x2="60"  y2="94"  stroke="#00e5a0" stroke-width="2" opacity="0.7"/>
</svg>"""

with open(f"{OUT}/favicon.svg", "w") as f:
    f.write(SVG)
print("  ✅ favicon.svg")


# ── Draw constellation using Pillow (4x supersampling for antialiasing) ───────
def draw_constellation(size):
    scale = 4
    S = size * scale
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # Rounded rect background
    radius = int(52 * S / 256)
    d.rounded_rectangle([0, 0, S-1, S-1], radius=radius, fill=(8, 12, 10, 255))

    def sc(v):
        return v * S / 256

    # Pentagon outer nodes (from original icon viewBox 0 0 256 256)
    outer = [
        (sc(128), sc(52)),
        (sc(196), sc(94)),
        (sc(172), sc(178)),
        (sc(84),  sc(178)),
        (sc(60),  sc(94)),
    ]
    hub = (sc(128), sc(122))
    lw  = max(1, int(2 * S / 256))

    # Outer ring edges (dimmer)
    for i in range(len(outer)):
        a, b = outer[i], outer[(i + 1) % len(outer)]
        d.line([a, b], fill=(0, 229, 160, int(255 * 0.35)), width=lw)

    # Spokes hub → outer nodes
    for pt in outer:
        d.line([hub, pt], fill=(0, 229, 160, int(255 * 0.7)), width=lw)

    # Outer nodes
    for pt in outer:
        r = int(10 * S / 256)
        r = max(1, r)
        cx, cy = pt
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(0, 229, 160, 255))

    # Hub centre
    r = max(1, int(16 * S / 256))
    cx, cy = hub
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(0, 229, 160, 255))

    return img.resize((size, size), Image.LANCZOS)


# ── Generate all PNG sizes ─────────────────────────────────────────────────────
sizes = [
    ("favicon-16x16.png",    16),
    ("favicon-32x32.png",    32),
    ("favicon-48x48.png",    48),
    ("apple-touch-icon.png", 180),
    ("icon-192.png",         192),
    ("icon-512.png",         512),
]

for filename, size in sizes:
    out_path = f"{OUT}/{filename}"
    img = draw_constellation(size)
    img.save(out_path, "PNG", optimize=True)
    kb = os.path.getsize(out_path) / 1024
    print(f"  ✅ {filename} ({size}×{size}, {kb:.1f}KB)")

print(f"\nAll favicons written to {OUT}/")
print("Next steps:")
print("  aws s3 sync assets/icons/ s3://matthew-life-platform/site/assets/icons/ \\")
print("    --cache-control 'max-age=31536000' --region us-west-2")
