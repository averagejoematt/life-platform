"""#4619 — the /story/panel/ bet-ledger tags hold WCAG AA on their own washes, both themes.

Each `.pl-tag` variant paints its text as an ink and its ground as a TINT of that same ink
(`color-mix(in oklch, <ink> N%, transparent)`), composited over whatever paper step the
ledger lands on. A tint eats the contrast margin — #3726's class — and the nightly light
sweep reported five axe `color-contrast` nodes on /story/panel/: .pl-won x3 (~3.9:1),
.pl-lost (~3.9:1), .pl-open (~4.46:1 after a first, token-name-only fix).

This test is the computed pin, not a token-name check. For every `.pl-<outcome> .pl-tag`
rule in story.css it reads the declared `color` and `background`, resolves both from
tokens.css per theme, composites the translucent wash over EVERY paper-ramp step with
straight sRGB alpha blending (what the browser paints and axe measures), and asserts
the text clears 4.5:1. A negative control proves the engine still fails the pre-fix
values, so a pass here means something.

Offline, stdlib-only, repo-only.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

# One contrast engine for the repo (see test_ink_faint_on_wash_3726's rationale).
from test_paper_ramp_contrast import AA, RAMP_STEPS, TOKENS, _mix_oklch, _palettes, _resolve, _strip_comments, contrast  # noqa: E402

STORY_CSS = TOKENS.parent / "story.css"
VARIANTS = ("won", "lost", "open")

# The values the live sweep failed on, for the negative control: (text, background).
PRE_FIX = {
    "won": ("var(--ember)", "var(--ember-soft)"),
    "lost": ("var(--ink-muted)", "color-mix(in oklch, var(--ink-muted) 18%, transparent)"),
    "open": ("var(--ink-faint)", "color-mix(in oklch, var(--ink-faint) 14%, transparent)"),
}


def _themes():
    dark, light_media, light_explicit = _palettes()
    assert light_media == light_explicit, "the two light blocks drifted — test_paper_ramp_contrast owns that contract"
    return {"dark": ({}, dark), "light": (light_media, dark)}


def _paint(expr, theme, dark):
    """Resolve a CSS colour expression to ((r, g, b), alpha).

    Supports the three forms these rules use: `var(--token)` (a token may itself be a
    `<ink> N%, transparent` wash such as --ember-soft), `color-mix(in oklch, var(--a) N%,
    transparent)` (a wash: the ink at alpha N — oklch interpolation against transparent
    takes the ink's L/C/h unchanged), and `color-mix(in oklch, var(--a) N%, var(--b))`
    (an opaque two-token mix; the missing weight is 100 - N per CSS Color 5)."""
    expr = expr.strip()
    var_only = re.fullmatch(r"var\(\s*(--[\w-]+)\s*\)", expr)
    if var_only:
        token = var_only.group(1)
        raw = theme.get(token, dark.get(token))
        assert raw is not None, f"token {token} is not defined"
        if "transparent" in raw:
            return _paint(raw, theme, dark)
        return _resolve(token, theme, dark), 1.0
    wash = re.fullmatch(r"color-mix\(in oklch,\s*var\(\s*(--[\w-]+)\s*\)\s+([\d.]+)%,\s*transparent\s*\)", expr)
    if wash:
        return _resolve(wash.group(1), theme, dark), float(wash.group(2)) / 100.0
    mix = re.fullmatch(r"color-mix\(in oklch,\s*var\(\s*(--[\w-]+)\s*\)\s+([\d.]+)%,\s*var\(\s*(--[\w-]+)\s*\)\s*(?:([\d.]+)%)?\s*\)", expr)
    if mix:
        w1 = float(mix.group(2))
        w2 = float(mix.group(4)) if mix.group(4) else 100.0 - w1
        return _mix_oklch(_resolve(mix.group(1), theme, dark), w1, _resolve(mix.group(3), theme, dark), w2), 1.0
    raise AssertionError(f"unsupported colour expression: {expr!r}")


def _over(fg, alpha, bg):
    return tuple(round(f * alpha + b * (1.0 - alpha)) for f, b in zip(fg, bg))


def _rule(variant):
    css = _strip_comments(STORY_CSS.read_text())
    m = re.search(r"\.pl-" + variant + r"\s+\.pl-tag\s*\{([^}]*)\}", css)
    assert m, f"story.css: no .pl-{variant} .pl-tag rule"
    decls = {d.group(1): d.group(2).strip() for d in re.finditer(r"(?<![\w-])([\w-]+)\s*:\s*([^;]+);", m.group(1))}
    assert "color" in decls and "background" in decls, f".pl-{variant} .pl-tag must declare both color and background, got {decls}"
    return decls["color"], decls["background"]


def _worst(text_expr, bg_expr, theme_name):
    theme, dark = _themes()[theme_name]
    ink, ink_alpha = _paint(text_expr, theme, dark)
    assert ink_alpha == 1.0, f"translucent text colour {text_expr!r} — measure it against its ground, not alone"
    wash, wash_alpha = _paint(bg_expr, theme, dark)
    return min((contrast(ink, _over(wash, wash_alpha, _resolve(step, theme, dark))), step) for step in RAMP_STEPS)


def test_every_pl_tag_variant_holds_aa_on_its_wash_in_both_themes():
    """Iterates every variant x theme x ramp step and reports every offender at once."""
    failures = []
    for variant in VARIANTS:
        text_expr, bg_expr = _rule(variant)
        for theme_name in ("dark", "light"):
            ratio, step = _worst(text_expr, bg_expr, theme_name)
            if ratio < AA:
                failures.append(f"{theme_name}: .pl-{variant} .pl-tag {text_expr} on {bg_expr} over {step} = {ratio:.2f}:1 (< {AA}:1)")
    assert not failures, "panel-ledger tag contrast regressions (#4619):\n  " + "\n  ".join(failures)


def test_the_pre_fix_values_still_fail():
    """Negative control: the exact pairs the sweep reported must still measure under AA
    through this engine in BOTH themes, or the assertion above has gone blind."""
    passing = []
    for variant, (text_expr, bg_expr) in PRE_FIX.items():
        for theme_name in ("dark", "light"):
            ratio, step = _worst(text_expr, bg_expr, theme_name)
            if ratio >= AA:
                passing.append(f"{theme_name}: pre-fix .pl-{variant} now measures {ratio:.2f}:1 over {step}")
    assert not passing, "the negative control has gone blind:\n  " + "\n  ".join(passing)
