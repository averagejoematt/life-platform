"""#1223 — the comprehensive WCAG-AA token-contrast regression guard.

The v4 palette's AA contrast math has, until now, lived ONLY as hand-written
comments in ``site/assets/css/tokens.css`` ("5.1:1 on --page" etc.). Those comments
drifted once already: the dark-root ``--alert`` #CB634C was reused in light mode where
it measures 3.37:1 on --page — a real shipped AA miss (fixed for the alert token only
by #579/#1275). There was no automated check that COMPUTES the ratios, so the next
token tweak could silently break AA again.

This test parses the hex colour primitives straight out of tokens.css for BOTH themes
(the dark ``:root`` palette block, and both light blocks — the
``@media (prefers-color-scheme: light)`` OS block and the explicit
``:root[data-theme="light"]`` choice block) and asserts every meaningful rendered
text/background pair clears WCAG AA via the standard relative-luminance computation
(sRGB → linearise → 0.2126R+0.7152G+0.0722B → (L1+0.05)/(L2+0.05)).

Pure stdlib, repo-only, offline — it belongs in the CI unit-test job at zero standing
cost and catches exactly the drift class that produced the light-mode alert miss.

Scope note vs. tests/test_light_alert_contrast_1222.py: that test is the focused
alert-only guard kept for its #1222 history; this one is the palette-wide superset
(10 text pairs × both themes). Keeping both is deliberate — the narrow one documents
the specific incident, this one guards the whole palette.
"""

import re
from pathlib import Path

TOKENS = Path(__file__).resolve().parent.parent / "site" / "assets" / "css" / "tokens.css"

# WCAG 2.1 SC 1.4.3 thresholds.
AA_NORMAL = 4.5  # normal-size text (< 18pt, or < 14pt bold)
AA_LARGE = 3.0  # large text (>= 18pt / 24px, or >= 14pt / 18.66px bold) and UI components


# ── WCAG relative-luminance / contrast-ratio math (sRGB) ──────────────────────
def _linear(channel: float) -> float:
    return channel / 12.92 if channel <= 0.03928 else ((channel + 0.055) / 1.055) ** 2.4


def _luminance(hex_str: str) -> float:
    r, g, b = (channel / 255 for channel in bytes.fromhex(hex_str.lstrip("#")))
    return 0.2126 * _linear(r) + 0.7152 * _linear(g) + 0.0722 * _linear(b)


def _contrast(fg: str, bg: str) -> float:
    a, b = _luminance(fg), _luminance(bg)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


# ── Parse the three palette blocks out of tokens.css ──────────────────────────
def _extract_theme_blocks(css: str):
    """Return {theme_label: raw_block_text} for dark + the two light blocks.

    The dark ``:root`` palette block (§1) opens with ``color-scheme: dark;`` and
    closes at the first ``}`` (it contains no nested braces — only color-mix() parens).
    The light blocks are the OS ``@media (prefers-color-scheme: light)`` block and the
    explicit ``:root[data-theme="light"]`` choice block (anchored past the empty
    placeholder rule via its ``color-scheme: light;`` first declaration).
    """
    dark = re.search(r":root\s*\{\s*color-scheme:\s*dark;(.*?)\n\}", css, re.DOTALL)
    media_light = re.search(
        r"@media\s*\(prefers-color-scheme:\s*light\)\s*\{\s*" r":root:not\(\[data-theme=\"dark\"\]\)\s*\{(.*?)\}\s*\}",
        css,
        re.DOTALL,
    )
    data_theme_light = re.search(
        r":root\[data-theme=\"light\"\]\s*\{\s*color-scheme:\s*light;(.*?)\n\}",
        css,
        re.DOTALL,
    )
    assert dark, "could not locate the dark :root palette block (color-scheme: dark)"
    assert media_light, "could not locate the @media (prefers-color-scheme: light) block"
    assert data_theme_light, 'could not locate the :root[data-theme="light"] block'
    return {
        "dark :root": dark.group(1),
        "@media light": media_light.group(1),
        ":root[data-theme=light]": data_theme_light.group(1),
    }


def _token(block: str, name: str) -> str:
    """Extract a 6-digit hex primitive by token name from a palette block."""
    m = re.search(rf"--{name}:\s*(#[0-9A-Fa-f]{{6}})\b", block)
    assert m, f"--{name} not found / not a 6-digit hex in block:\n{block[:400]}"
    return m.group(1).upper()


# ── The rendered text/background pairs we hold to AA ──────────────────────────
# (foreground token, background token, threshold, rationale). Only combinations that
# are ACTUALLY composited as rendered text are listed — no two colours that never
# touch. Every pair is asserted at AA_NORMAL (4.5): the accent tokens (ember, alert)
# ARE used at large sizes in places (the score, the ring-center value), but they also
# appear as normal-size text (nav labels, .li-up trend tags, footer headers), so we
# hold them to the stricter normal bar — and they clear it, so there is no reason to
# relax to AA_LARGE. AA_LARGE is defined above for documentation / future large-only
# tokens; today every real text pair meets the normal bar.
PAIRS = [
    ("ink", "page", AA_NORMAL, "body copy on the page background (body{color:--ink;background:--page})"),
    ("ink", "surface", AA_NORMAL, "body/panel copy on cards & panels (--surface)"),
    ("ink-muted", "page", AA_NORMAL, "secondary text (.cb-note, .honest-ink, .pa-sum) on page"),
    ("ink-muted", "surface", AA_NORMAL, "secondary text inside cards"),
    ("ink-faint", "page", AA_NORMAL, "labels/ticks/captions (.label, mono uppercase ~11px) on page — normal-size"),
    ("ink-faint", "surface", AA_NORMAL, "labels/captions inside cards"),
    ("ember", "page", AA_NORMAL, "the live accent AS TEXT (.li-up, .cb-arrow, links, nav/footer headers) on page"),
    ("ember", "surface", AA_NORMAL, "ember accent text inside cards/panels"),
    ("alert", "page", AA_NORMAL, "reserved state-alert value (.vr-alert .vr-v ring-center) on page"),
    ("alert", "surface", AA_NORMAL, "reserved state-alert value inside cards"),
]


def _ratios():
    css = TOKENS.read_text(encoding="utf-8")
    blocks = _extract_theme_blocks(css)
    out = []  # (theme, fg, bg, hex_fg, hex_bg, ratio, threshold, why)
    for theme, block in blocks.items():
        for fg, bg, threshold, why in PAIRS:
            hf, hb = _token(block, fg), _token(block, bg)
            out.append((theme, fg, bg, hf, hb, _contrast(hf, hb), threshold, why))
    return out


def test_every_text_pair_meets_wcag_aa_in_both_themes():
    """The guard: every meaningful text/background pair clears its AA threshold in
    the dark theme AND both light blocks. A failure here means a token edit broke
    AA — fix the hex (or, if the pair is genuinely large-only, justify AA_LARGE)."""
    failures = []
    for theme, fg, bg, hf, hb, ratio, threshold, why in _ratios():
        if ratio < threshold:
            failures.append(f"[{theme}] --{fg} {hf} on --{bg} {hb} = {ratio:.2f}:1 " f"< {threshold}:1 ({why})")
    assert not failures, "WCAG AA contrast violations in tokens.css:\n" + "\n".join(failures)


def test_light_and_data_theme_blocks_agree():
    """The @media-light and :root[data-theme=light] blocks must define the SAME hexes
    for every audited token — a drift between them would let OS-light and toggle-light
    disagree on AA (the exact shape of the original --alert miss, which lived in only
    one of the two blocks before #1222)."""
    css = TOKENS.read_text(encoding="utf-8")
    blocks = _extract_theme_blocks(css)
    media, choice = blocks["@media light"], blocks[":root[data-theme=light]"]
    audited = sorted({t for pair in PAIRS for t in pair[:2]})
    mismatches = [
        f"--{n}: @media={_token(media, n)} vs data-theme={_token(choice, n)}" for n in audited if _token(media, n) != _token(choice, n)
    ]
    assert not mismatches, "light-mode palette blocks disagree:\n" + "\n".join(mismatches)


def test_contrast_math_is_non_vacuous():
    """Prove the WCAG math is live: it must PASS a known-good pair and FAIL the exact
    historical drift (dark-root --alert #CB634C reused on the light --page #F4EFE4 =
    3.37:1). If this ever stops failing, the guard has gone vacuous."""
    # Known-good: black on white is the canonical 21:1.
    assert round(_contrast("#000000", "#FFFFFF"), 1) == 21.0
    # The historical light-mode alert miss the guard exists to catch.
    historical = _contrast("#CB634C", "#F4EFE4")
    assert round(historical, 2) == 3.37
    assert historical < AA_NORMAL
