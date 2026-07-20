"""#1470 — the paper-elevation ramp, enforced.

tokens.css §1 defines a five-step neutral surface ramp (sunken well / page / paper /
toned paper / raised paper) for BOTH themes, so surface hierarchy comes from neutral
tonality — never from leaning on the ember accent. This test re-derives the ramp the
way a browser would (var() resolution + color-mix in oklch) and asserts the contract:

1. THEME-TOGGLE PARITY — the @media (prefers-color-scheme: light) block and the
   explicit :root[data-theme="light"] block define the IDENTICAL token map. If they
   drift, the toggle stops winning in one direction (DESIGN_SYSTEM_V5 §4).
2. WCAG AA REGISTER RULE — --ink / --ink-muted / --ink-faint / --ember all hold
   >= 4.5:1 on every ramp step 0-3 (page, surface, surface-2, surface-raised) in both
   themes; the sunken well (step -1) is machine-text territory: full --ink only, and
   --ink must hold AA there.
3. RAMP MONOTONICITY — the steps stay tonally ORDERED per theme (dark lifts toward
   the ink, light lifts toward warm white), so "raised" can never silently invert
   into an inset again (the pre-#1470 light-mode bug).

Offline, repo-only: safe in the CI unit-test job.
"""

import math
import re
from pathlib import Path

TOKENS = Path(__file__).resolve().parent.parent / "site" / "assets" / "css" / "tokens.css"

RAMP_STEPS = ["--page", "--surface", "--surface-2", "--surface-raised"]  # steps 0-3
TEXT_TOKENS = ["--ink", "--ink-muted", "--ink-faint", "--ember"]
AA = 4.5


# ── sRGB / OKLab / OKLCh plumbing (the CSS Color 4 reference math) ───────────────


def _srgb_to_linear(c):
    c = c / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _linear_to_srgb(c):
    c = max(0.0, min(1.0, c))
    return 12.92 * c if c <= 0.0031308 else 1.055 * (c ** (1 / 2.4)) - 0.055


def _hex_to_rgb(h):
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    return tuple(bytes.fromhex(h))


def _rgb_to_oklab(rgb):
    r, g, b = (_srgb_to_linear(v) for v in rgb)
    l = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b
    m = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
    s = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b
    l_, m_, s_ = (v ** (1 / 3) for v in (l, m, s))
    return (
        0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_,
        1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_,
        0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_,
    )


def _oklab_to_rgb(lab):
    big_l, a, b = lab
    l_ = big_l + 0.3963377774 * a + 0.2158037573 * b
    m_ = big_l - 0.1055613458 * a - 0.0638541728 * b
    s_ = big_l - 0.0894841775 * a - 1.2914855480 * b
    l, m, s = (v**3 for v in (l_, m_, s_))
    r = 4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s
    g = -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s
    bl = -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s
    return tuple(round(_linear_to_srgb(v) * 255) for v in (r, g, bl))


def _mix_oklch(rgb1, w1, rgb2, w2):
    """color-mix(in oklch, c1 w1%, c2 w2%) — interpolate L, C and hue (shorter arc)."""

    def to_lch(lab):
        big_l, a, b = lab
        return (big_l, math.hypot(a, b), math.degrees(math.atan2(b, a)) % 360)

    l1, l2 = to_lch(_rgb_to_oklab(rgb1)), to_lch(_rgb_to_oklab(rgb2))
    f1, f2 = w1 / 100.0, w2 / 100.0
    dh = ((l2[2] - l1[2] + 180) % 360) - 180
    hue = (l1[2] + dh * f2 / (f1 + f2)) % 360
    big_l = l1[0] * f1 + l2[0] * f2
    chroma = l1[1] * f1 + l2[1] * f2
    return _oklab_to_rgb((big_l, chroma * math.cos(math.radians(hue)), chroma * math.sin(math.radians(hue))))


def _rel_lum(rgb):
    r, g, b = (_srgb_to_linear(v) for v in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(rgb_a, rgb_b):
    hi, lo = sorted((_rel_lum(rgb_a), _rel_lum(rgb_b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


# ── tokens.css parsing — the dark root and the TWO light blocks ──────────────────


def _strip_comments(text):
    return re.sub(r"/\*.*?\*/", " ", text, flags=re.S)


def _block_body(css, selector_pattern):
    """Body of the first NON-EMPTY block whose selector matches (token blocks are
    flat — no nested braces inside a declaration block)."""
    for m in re.finditer(selector_pattern + r"\s*\{", css):
        depth, start = 1, m.end()
        i = start
        while depth and i < len(css):
            if css[i] == "{":
                depth += 1
            elif css[i] == "}":
                depth -= 1
            i += 1
        end = i - 1
        body = css[start:end]
        if re.search(r"--[\w-]+\s*:", body):
            return body
    raise AssertionError(f"tokens.css: no non-empty block for {selector_pattern!r}")


def _decls(body):
    return {m.group(1): m.group(2).strip() for m in re.finditer(r"(--[\w-]+)\s*:\s*([^;]+);", body)}


def _palettes():
    css = _strip_comments(TOKENS.read_text())
    dark = {}
    # merge every plain `:root {` block (palette, typography, band tokens, ...).
    # `:root:not(...)` / `:root[data-theme...]` selectors never match this pattern
    # (the next char there is `:` or `[`, not `{`).
    for m in re.finditer(r":root\s*\{", css):
        depth, start = 1, m.end()
        i = start
        while depth and i < len(css):
            if css[i] == "{":
                depth += 1
            elif css[i] == "}":
                depth -= 1
            i += 1
        end = i - 1
        dark.update(_decls(css[start:end]))
    media = re.search(r"@media \(prefers-color-scheme: light\)\s*\{", css)
    assert media, "tokens.css lost the OS-preference light block"
    media_end = media.end()
    light_media = _decls(_block_body(css[media_end:], r':root:not\(\[data-theme="dark"\]\)'))
    light_explicit = _decls(_block_body(css, r':root\[data-theme="light"\]'))
    return dark, light_media, light_explicit


def _resolve(token, theme, dark, seen=None):
    """Resolve a token to an (r, g, b) tuple: theme override -> dark root, following
    var() references and evaluating the ramp's color-mix(in oklch, ...) forms."""
    seen = seen or set()
    assert token not in seen, f"circular token reference at {token}"
    seen.add(token)
    value = theme.get(token, dark.get(token))
    assert value is not None, f"token {token} is not defined"
    value = value.strip()
    if value.startswith("#"):
        return _hex_to_rgb(value)
    var_only = re.fullmatch(r"var\(\s*(--[\w-]+)\s*\)", value)
    if var_only:
        return _resolve(var_only.group(1), theme, dark, seen)
    leg_pat = r"(var\(\s*--[\w-]+\s*\)|#[0-9a-fA-F]{3,6})"
    mix = re.fullmatch(
        r"color-mix\(in oklch,\s*" + leg_pat + r"\s+([\d.]+)%,\s*" + leg_pat + r"\s+([\d.]+)%\)",
        value,
    )
    assert mix, f"unsupported value for {token}: {value!r}"

    def leg(expr):
        expr = expr.strip()
        if expr.startswith("#"):
            return _hex_to_rgb(expr)
        return _resolve(re.match(r"var\(\s*(--[\w-]+)", expr).group(1), theme, dark, set(seen))

    return _mix_oklch(leg(mix.group(1)), float(mix.group(2)), leg(mix.group(3)), float(mix.group(4)))


# ── the contract ─────────────────────────────────────────────────────────────────


def test_light_blocks_stay_identical():
    """The OS-preference block and the explicit-choice block must define the SAME
    tokens with the SAME values — otherwise the theme toggle stops winning in one
    direction (an explicit choice that renders differently from the OS default)."""
    _, light_media, light_explicit = _palettes()
    media_only = {k: v for k, v in light_media.items() if light_explicit.get(k) != v}
    explicit_only = {k: v for k, v in light_explicit.items() if light_media.get(k) != v}
    assert light_media == light_explicit, (
        "the two light-theme blocks in tokens.css drifted apart:\n" f"  media-only: {media_only}\n" f"  explicit-only: {explicit_only}"
    )


def test_ramp_holds_aa_in_both_themes():
    """Every neutral text token + ember reads AA (>=4.5:1) on every ramp step 0-3,
    both themes; the sunken well holds AA for full ink (its only sanctioned text)."""
    dark, light_media, _ = _palettes()
    failures = []
    for theme_name, theme in (("dark", {}), ("light", light_media)):
        for step in RAMP_STEPS:
            bg = _resolve(step, theme, dark)
            for text in TEXT_TOKENS:
                ratio = contrast(_resolve(text, theme, dark), bg)
                if ratio < AA:
                    failures.append(f"{theme_name}: {text} on {step} = {ratio:.2f}:1 (< {AA}:1)")
        well = _resolve("--surface-sunken", theme, dark)
        ink_ratio = contrast(_resolve("--ink", theme, dark), well)
        if ink_ratio < AA:
            failures.append(f"{theme_name}: --ink on --surface-sunken = {ink_ratio:.2f}:1 (< {AA}:1)")
    assert not failures, "paper-ramp AA regressions:\n" + "\n".join(failures)


def test_ramp_stays_tonally_ordered():
    """Dark lifts toward the ink (sunken < page < surface < surface-2 < raised);
    light lifts toward warm white (sunken < surface-2 < page < surface < raised).
    This is what makes 'raised' mean raised — the pre-#1470 light theme derived a
    raised surface DARKER than the paper (inverted elevation)."""
    dark, light_media, _ = _palettes()
    orders = {
        "dark": ({}, ["--surface-sunken", "--page", "--surface", "--surface-2", "--surface-raised"]),
        "light": (light_media, ["--surface-sunken", "--surface-2", "--page", "--surface", "--surface-raised"]),
    }
    for theme_name, (theme, order) in orders.items():
        lums = [(_rel_lum(_resolve(t, theme, dark)), t) for t in order]
        sorted_lums = sorted(lums, key=lambda p: p[0])
        assert lums == sorted_lums, f"{theme_name} ramp out of tonal order: {[(t, round(lm, 4)) for lm, t in lums]}"
