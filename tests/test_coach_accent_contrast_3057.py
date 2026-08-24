"""#3057 — WCAG AA clamp for the data-supplied coach-accent TEXT colors.

`--coach` arrives per-request from DATA (the `/api/coaches` roster / a coach
payload's `color` field, injected as an inline `style="--coach:#hex"`), not from a
locked design-system palette. Before this fix, `.rd-name`/`.th-name`/`.cv-name`/
`.coach-name` (tokens.css) and the duplicate `.rd-name` (story.css) painted that raw
value straight onto text with `color: var(--coach, <fallback>)` — nothing between
the payload and the pixel could stop an under-contrast roster color from reaching a
reader. `.coach-pick.is-active`'s background (evidence.css) tints the SAME text's
ground with a raw 12% `--coach` wash, so it can move the ground out from under an
otherwise-safe foreground too. This is the SECOND occurrence of the data-driven a11y
dark-state class (first: `.wu-carried`, INCIDENT_LOG 2026-08-10) — this one caused
the 2026-08-23 site-deploy auto-rollback (INCIDENT_LOG, same date) on a roster color
the axe sweep read at `/method/board/`.

The fix wraps every one of those three render sites in
`color-mix(in oklch, var(--coach, <fallback>) 25%, <anchor> 75%)` (`<anchor>` is
`var(--ink)` in all three — see the CSS comments for why `--ink-muted` was rejected
as an anchor: its own AA margin, ~4.5-4.9:1 on the ramp per
test_paper_ramp_contrast.py, is too thin to survive blending ANY adversarial
`--coach` at all). `--ink` clears 4.5:1 on every paper-ramp step in both themes with
real headroom (test_paper_ramp_contrast.py), so folding 75% of it into an arbitrary
25%-weighted accent keeps the blend inside that headroom regardless of what the
25% leg supplies — proven below not just for the issue's own adversarial example
(`#818cf8`) but for literal `#000`/`#fff`, the two extremes an unvalidated hex can
supply and the actual worst case (found by the N-tuning sweep this fix was derived
from: pure black in dark theme, pure white in light theme — see the module comment
in tokens.css).

MUTATION-PROOF BY CONSTRUCTION, not by re-deriving the formula: every test below
extracts the LIVE `color`/`background` value straight out of the shipped CSS files
and evaluates it with a real oklch color-mix engine (the same reference algorithm
test_paper_ramp_contrast.py uses, re-derived here so this file stays self-contained
per that file's own precedent). If the clamp is ever reverted to a bare
`var(--coach, <fallback>)`, this module's resolver returns the RAW adversarial
`--coach` value unmixed, and the contrast assertions below fail for #000/#fff/
#818cf8 exactly as they would in a real browser — nothing here hardcodes "clamped"
math independent of what the CSS actually says.

Offline, stdlib-only, repo-only: safe in the CI unit-test job.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

CSS_DIR = Path(__file__).resolve().parent.parent / "site" / "assets" / "css"
TOKENS = CSS_DIR / "tokens.css"
STORY = CSS_DIR / "story.css"
EVIDENCE = CSS_DIR / "evidence.css"

AA = 4.5
RAMP_STEPS = ["--page", "--surface", "--surface-2", "--surface-raised"]

# The adversarial inputs: the issue's own named example, plus the two extremes an
# unvalidated data-supplied hex can actually take — proven (by direct sweep, see the
# tokens.css comment) to be the true worst case for an --ink-anchored 25/75 blend.
ADVERSARIAL_COACH_COLORS = {
    "#818cf8 (issue example)": (0x81, 0x8C, 0xF8),
    "#000000 (adversarial extreme)": (0x00, 0x00, 0x00),
    "#ffffff (adversarial extreme)": (0xFF, 0xFF, 0xFF),
}


# ── sRGB / OKLab / OKLCh plumbing — the CSS Color 4 reference math (mirrors
#    tests/test_paper_ramp_contrast.py; duplicated per that file's own precedent of
#    each contrast test staying self-contained rather than importing a sibling). ──


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


# ── tokens.css palette parsing — dark root + the two light blocks ────────────────


def _strip_comments(text):
    return re.sub(r"/\*.*?\*/", " ", text, flags=re.S)


def _block_body(css, selector_pattern):
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
    light_media = _decls(_block_body(css[media.end() :], r':root:not\(\[data-theme="dark"\]\)'))
    return dark, light_media


# ── the general resolver: any CSS colour expression, with --coach injectable ─────


def _split_top_level(s):
    """Split `s` on top-level commas (not inside nested parens)."""
    parts, depth, buf = [], 0, []
    for ch in s:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    parts.append("".join(buf))
    return [p.strip() for p in parts]


def resolve(expr, coach_rgb, theme, dark, seen=None):
    """Evaluate a CSS colour expression (hex / var() / color-mix(), arbitrarily
    nested) to an (r, g, b) tuple. `coach_rgb` is injected wherever `var(--coach,
    ...)` appears — `None` simulates --coach being entirely unset (the no-data
    fallback path); a tuple simulates a real data-supplied colour."""
    seen = seen or set()
    expr = expr.strip()

    if expr.startswith("#"):
        return _hex_to_rgb(expr)

    if expr.startswith("var("):
        assert expr.endswith(")"), f"unterminated var(): {expr!r}"
        args = _split_top_level(expr[len("var(") : -1])
        name = args[0].strip()
        if name == "--coach":
            if coach_rgb is not None:
                return coach_rgb
            assert len(args) > 1, "var(--coach) with no fallback and no injected value"
            return resolve(",".join(args[1:]), coach_rgb, theme, dark, seen)
        assert name not in seen, f"circular token reference at {name}"
        value = theme.get(name, dark.get(name))
        assert value is not None, f"token {name} is not defined"
        return resolve(value, coach_rgb, theme, dark, seen | {name})

    if expr.startswith("color-mix("):
        assert expr.endswith(")"), f"unterminated color-mix(): {expr!r}"
        parts = _split_top_level(expr[len("color-mix(") : -1])
        assert parts[0].strip() == "in oklch", f"unsupported color-mix space: {parts[0]!r}"
        leg1, leg2 = parts[1].strip(), parts[2].strip()
        # A leg's trailing `N%` is OPTIONAL per the color-mix() grammar — CSS fills
        # in whichever percentage is omitted as `100% - the other`. Both of our
        # sites omit it on exactly one leg (evidence.css's outer `... 12%, var(--surface))`).
        m1 = re.match(r"^(.*)\s+([\d.]+)%$", leg1)
        m2 = re.match(r"^(.*)\s+([\d.]+)%$", leg2)
        color1_expr = m1.group(1) if m1 else leg1
        color2_expr = m2.group(1) if m2 else leg2
        if m1 and m2:
            w1, w2 = float(m1.group(2)), float(m2.group(2))
        elif m1 and not m2:
            w1 = float(m1.group(2))
            w2 = 100.0 - w1
        elif m2 and not m1:
            w2 = float(m2.group(2))
            w1 = 100.0 - w2
        else:
            w1 = w2 = 50.0
        c1 = resolve(color1_expr, coach_rgb, theme, dark, seen)
        c2 = resolve(color2_expr, coach_rgb, theme, dark, seen)
        return _mix_oklch(c1, w1, c2, w2)

    raise AssertionError(f"unsupported colour expression: {expr!r}")


def _ramp_bg(step, theme, dark):
    return resolve(theme.get(step, dark.get(step)), None, theme, dark)


# ── extracting the live property VALUE from each site's real CSS ────────────────


def _rule_prop_value(css_text, selector_literal, prop):
    """The raw value text of `prop:` inside the flat (non-nested) rule whose
    selector is EXACTLY `selector_literal` — mirrors test_paper_ramp_contrast.py's
    subscribe-panel test helper. Reads the value up to the next `;`, so a nested
    color-mix()'s internal commas/parens are captured whole."""
    css = _strip_comments(css_text)
    m = re.search(re.escape(selector_literal) + r"\s*\{([^}]*)\}", css)
    assert m, f"no rule found for selector {selector_literal!r}"
    body = m.group(1)
    pm = re.search(r"(?<![\w-])" + re.escape(prop) + r"\s*:\s*([^;]+);", body)
    assert pm, f"{selector_literal!r} declares no {prop!r} property"
    return pm.group(1).strip()


def _tokens_coach_name_value():
    return _rule_prop_value(TOKENS.read_text(), ".rd-name, .th-name, .cv-name, .coach-name", "color")


def _story_rd_name_value():
    return _rule_prop_value(STORY.read_text(), ".rd-name", "color")


def _evidence_is_active_bg_value():
    return _rule_prop_value(EVIDENCE.read_text(), ".coach-pick.is-active", "background")


# ── the contract ──────────────────────────────────────────────────────────────────


def test_tokens_combined_coach_name_rule_holds_aa():
    """.rd-name / .th-name / .cv-name / .coach-name (tokens.css) — the primary
    persona-identity text rule — must clear 4.5:1 against every paper-ramp step,
    both themes, for the adversarial coach colours (incl. the issue's own
    #818cf8), evaluated straight from the LIVE CSS value."""
    dark, light_media = _palettes()
    value = _tokens_coach_name_value()
    failures = []
    for label, coach_rgb in ADVERSARIAL_COACH_COLORS.items():
        for theme_name, theme in (("dark", {}), ("light", light_media)):
            fg = resolve(value, coach_rgb, theme, dark)
            for step in RAMP_STEPS:
                bg = _ramp_bg(step, theme, dark)
                ratio = contrast(fg, bg)
                if ratio < AA:
                    failures.append(f"{theme_name}/{step}: {label} -> {fg} on {bg} = {ratio:.2f}:1 (< {AA}:1)")
    assert not failures, ".coach-name AA regressions:\n" + "\n".join(failures)


def test_story_rd_name_rule_holds_aa():
    """story.css's SECOND `.rd-name` definition (this file loads after tokens.css,
    so it is the one that actually wins the cascade on any page loading both) must
    independently clear the same 4.5:1 floor — a fix to only one of the two
    competing rules would leave the other one live and unguarded."""
    dark, light_media = _palettes()
    value = _story_rd_name_value()
    failures = []
    for label, coach_rgb in ADVERSARIAL_COACH_COLORS.items():
        for theme_name, theme in (("dark", {}), ("light", light_media)):
            fg = resolve(value, coach_rgb, theme, dark)
            for step in RAMP_STEPS:
                bg = _ramp_bg(step, theme, dark)
                ratio = contrast(fg, bg)
                if ratio < AA:
                    failures.append(f"{theme_name}/{step}: {label} -> {fg} on {bg} = {ratio:.2f}:1 (< {AA}:1)")
    assert not failures, "story.css .rd-name AA regressions:\n" + "\n".join(failures)


def test_coach_pick_is_active_background_holds_aa_for_the_text_on_it():
    """.coach-pick.is-active (evidence.css) tints the SAME text's own ground with a
    12% --coach wash. Prove the nested clamp holds: the clamped .coach-name text
    (tokens.css) must still clear 4.5:1 against this tinted background — not just
    against the plain --surface the ramp test above assumes — for the same
    adversarial coach colour driving BOTH the text and the tint simultaneously."""
    dark, light_media = _palettes()
    text_value = _tokens_coach_name_value()
    bg_value = _evidence_is_active_bg_value()
    failures = []
    for label, coach_rgb in ADVERSARIAL_COACH_COLORS.items():
        for theme_name, theme in (("dark", {}), ("light", light_media)):
            fg = resolve(text_value, coach_rgb, theme, dark)
            bg = resolve(bg_value, coach_rgb, theme, dark)
            ratio = contrast(fg, bg)
            if ratio < AA:
                failures.append(f"{theme_name}: {label} -> text {fg} on is-active bg {bg} = {ratio:.2f}:1 (< {AA}:1)")
    assert not failures, ".coach-pick.is-active AA regressions:\n" + "\n".join(failures)


def test_no_data_fallback_still_holds_aa():
    """When --coach is entirely unset (no roster colour at all — the pre-data,
    pre-render, or malformed-payload case), each rule's own fallback token must
    still clear AA on its own. Sanity check that the clamp doesn't regress the
    already-safe no-data path."""
    dark, light_media = _palettes()
    sites = [
        (".coach-name (tokens.css)", _tokens_coach_name_value()),
        (".rd-name (story.css)", _story_rd_name_value()),
    ]
    failures = []
    for site_name, value in sites:
        for theme_name, theme in (("dark", {}), ("light", light_media)):
            fg = resolve(value, None, theme, dark)
            for step in RAMP_STEPS:
                bg = _ramp_bg(step, theme, dark)
                ratio = contrast(fg, bg)
                if ratio < AA:
                    failures.append(f"{theme_name}/{step}: {site_name} (no data) -> {fg} on {bg} = {ratio:.2f}:1 (< {AA}:1)")
    assert not failures, "no-data fallback AA regressions:\n" + "\n".join(failures)


def test_issue_example_reported_ratios():
    """The issue's own adversarial example (#818cf8, ~3.0:1 raw on white — the
    exact colour the 2026-08-23 rollback traced to) resolved+measured in both
    themes against --surface, printed so a failure names real numbers rather than
    a bare assert. (The full ramp is already covered by the tests above; this one
    pins the single number the issue and PR body quote.)"""
    dark, light_media = _palettes()
    value = _tokens_coach_name_value()
    coach_rgb = ADVERSARIAL_COACH_COLORS["#818cf8 (issue example)"]
    results = {}
    for theme_name, theme in (("dark", {}), ("light", light_media)):
        fg = resolve(value, coach_rgb, theme, dark)
        bg = resolve(theme.get("--surface", dark.get("--surface")), None, theme, dark)
        results[theme_name] = contrast(fg, bg)
    assert results["dark"] >= AA, f"#818cf8 dark/--surface = {results['dark']:.2f}:1 (< {AA}:1)"
    assert results["light"] >= AA, f"#818cf8 light/--surface = {results['light']:.2f}:1 (< {AA}:1)"
