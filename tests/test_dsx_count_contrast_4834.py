"""#4834 - the deficit-sustainability count badge sits on --ember-wash (9% ember) at the --fs-h3 floor (19px, not
'large text'); plain --ember measured ~4.4:1 there in the light theme. The test COMPUTES the ratio: it parses the
.dsx-count colour (color-mix in oklch of --ember and --ink), mixes it, composites the wash over page/surface and
requires >= 4.5:1 in both themes (a 99%-ember mix would fail)."""

import math
import re
from pathlib import Path

CSS = Path(__file__).resolve().parent.parent / "site" / "assets" / "css" / "tokens.css"

THEMES = {
    "light": {"page": "#F4EFE4", "surface": "#FBF8F1", "ink": "#221E17", "ember": "#A34E13"},
    "dark": {"page": "#0E0C08", "surface": "#16130E", "ink": "#ECE3D2", "ember": "#DD7A37"},
}
WASH = 0.09


def _rgb(h):
    h = h.lstrip("#")
    return [int(h[i : i + 2], 16) / 255 for i in (0, 2, 4)]


def _lin(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _unlin(c):
    return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def _to_oklab(rgb):
    r, g, b = (_lin(c) for c in rgb)
    l_ = (0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b) ** (1 / 3)
    m_ = (0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b) ** (1 / 3)
    s_ = (0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b) ** (1 / 3)
    return (
        0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_,
        1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_,
        0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_,
    )


def _from_oklab(lab):
    L, a, b = lab
    l_ = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m_ = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s_ = (L - 0.0894841775 * a - 1.2914855480 * b) ** 3
    lin = (
        4.0767416621 * l_ - 3.3077115913 * m_ + 0.2309699292 * s_,
        -1.2684380046 * l_ + 2.6097574011 * m_ - 0.3413193965 * s_,
        -0.0041960863 * l_ - 0.7034186147 * m_ + 1.7076147010 * s_,
    )
    return [min(1.0, max(0.0, _unlin(min(1.0, max(0.0, c))))) for c in lin]


def _mix_oklch(c1, p1, c2):
    """color-mix(in oklch, c1 p1%, c2): interpolate L, C linearly and hue along the shorter arc."""
    w = p1 / 100
    L1, a1, b1 = _to_oklab(c1)
    L2, a2, b2 = _to_oklab(c2)
    C1, C2 = math.hypot(a1, b1), math.hypot(a2, b2)
    h1, h2 = math.atan2(b1, a1), math.atan2(b2, a2)
    d = (h2 - h1 + math.pi) % (2 * math.pi) - math.pi
    h = h1 + d * (1 - w)
    L, C = L1 * w + L2 * (1 - w), C1 * w + C2 * (1 - w)
    return _from_oklab((L, C * math.cos(h), C * math.sin(h)))


def _luminance(rgb):
    r, g, b = (_lin(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _ratio(fg, bg):
    a, b = _luminance(fg), _luminance(bg)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


def _dsx_color():
    m = re.search(r"^\.dsx-count\s*\{([^}]*)\}", CSS.read_text(), re.M)
    assert m, ".dsx-count rule missing"
    return re.search(r"color:\s*([^;]+);", m.group(1)).group(1).strip()


def test_dsx_count_clears_4_5_on_the_ember_wash_in_both_themes():
    color = _dsx_color()
    assert color != "var(--ember)", "bare --ember on --ember-wash is ~4.4:1 light (#4834)"
    m = re.fullmatch(r"color-mix\(in oklch,\s*var\(--ember\)\s*(\d+(?:\.\d+)?)%,\s*var\(--ink\)\)", color)
    assert m, f"unrecognised .dsx-count colour {color!r}; extend this test's parser"
    pct = float(m.group(1))
    failures = []
    for theme, t in THEMES.items():
        fg = _mix_oklch(_rgb(t["ember"]), pct, _rgb(t["ink"]))
        for ground in ("page", "surface"):
            base = _rgb(t[ground])
            bg = [base[i] * (1 - WASH) + _rgb(t["ember"])[i] * WASH for i in range(3)]
            r = _ratio(fg, bg)
            if r < 4.5:
                failures.append(f"{theme}/{ground}: {r:.2f}:1")
    assert not failures, f".dsx-count under 4.5:1 on --ember-wash: {failures}"
