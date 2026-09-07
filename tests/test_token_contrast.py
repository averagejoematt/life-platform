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
import sys
from pathlib import Path

import pytest

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

# #3545 — the seven pillar identity tokens are TEXT tokens. tokens.css §8.6 called them
# "identity only … never text", but evidence_character.js renders pillar NAMES in them
# (`.ch-cal-p` at 17px, the decay/calibration <strong>s) and evidence_receipts.js does the
# same for `.ch-comp-n`. They were declared once, in a bare `:root` BELOW the light blocks
# that no light block overrode, so every one of them fell through to its dark value on the
# light paper: 2.81-3.47:1 on --page. (charts.js also uses them, but only as an SVG
# stroke/fill on ring segments and radar dots — a graphic, not text, and outside this set.)
PILLARS = ["sleep", "movement", "nutrition", "metabolic", "mind", "relationships", "consistency"]
PAIRS += [
    (f"pillar-{name}", bg, AA_NORMAL, f"the {name} pillar's NAME rendered in its identity colour (.ch-cal-p / .ch-comp-n)")
    for name in PILLARS
    for bg in ("page", "surface")
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


# ── #1989 — the cockpit scope-button opacity-composite guard ──────────────────
# The Month/Journey de-emphasis shipped as whole-element `opacity: 0.6` over
# --ink-faint, compositing to 2.84:1 (dark) / 2.34:1 (light) — a WCAG AA miss the
# plain token pairs above cannot see (they measure tokens at full opacity). This
# section composites the ACTUAL applied opacity from cockpit.css and holds the
# result to AA, so re-adding an opacity de-emphasis reds CI offline instead of
# waiting for the live axe sweep.

COCKPIT_CSS = TOKENS.parent / "cockpit.css"


def _composite(fg: str, bg: str, alpha: float) -> str:
    """Simple-alpha composite of fg text over an opaque bg (per-channel lerp) —
    the effective rendered colour of text under whole-element opacity."""
    f, b = fg.lstrip("#"), bg.lstrip("#")
    return "#" + "".join(f"{round(alpha * int(f[i:i + 2], 16) + (1 - alpha) * int(b[i:i + 2], 16)):02X}" for i in (0, 2, 4))


def _scope_deep_default_opacity(css: str) -> float:
    """The effective DEFAULT-state opacity on .scope-btn.scope-deep (1.0 when no
    opacity is declared). Scans every rule whose selector hits .scope-deep in its
    resting state (no :hover/:focus pseudo, no .is-active) and takes the lowest
    declared opacity. Asserts the rule still exists so a rename can't silently
    no-op this guard (memory: guard the set, prove it fires)."""
    opacity, found_rule = 1.0, False
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)  # comments would bleed into the naive selector chunks
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        selectors, body = m.group(1), m.group(2)
        default_sels = [s for s in selectors.split(",") if ".scope-deep" in s and ":" not in s and ".is-active" not in s]
        if not default_sels:
            continue
        found_rule = True
        om = re.search(r"opacity:\s*([0-9.]+)", body)
        if om:
            opacity = min(opacity, float(om.group(1)))
    assert found_rule, ".scope-btn.scope-deep rule not found in cockpit.css — re-point this #1989 guard at the renamed selector"
    return opacity


def test_cockpit_scope_deep_composites_to_aa_in_both_themes():
    """#1989: the Month/Journey scope buttons (--ink-faint text, --page behind, any
    default-state opacity from cockpit.css) must clear AA normal-size in the dark
    theme AND both light blocks. Fails if anyone re-adds an opacity de-emphasis."""
    alpha = _scope_deep_default_opacity(COCKPIT_CSS.read_text(encoding="utf-8"))
    blocks = _extract_theme_blocks(TOKENS.read_text(encoding="utf-8"))
    failures = []
    for theme, block in blocks.items():
        fg, bg = _token(block, "ink-faint"), _token(block, "page")
        ratio = _contrast(_composite(fg, bg, alpha), bg)
        if ratio < AA_NORMAL:
            failures.append(
                f"[{theme}] .scope-btn.scope-deep: --ink-faint {fg} @ opacity {alpha} on --page {bg} "
                f"= {ratio:.2f}:1 < {AA_NORMAL}:1 (WCAG AA, #1989 — de-emphasize by size, never opacity)"
            )
    assert not failures, "cockpit scope-button composite contrast regressed:\n" + "\n".join(failures)


def test_scope_deep_composite_guard_is_non_vacuous():
    """Prove the composite math catches the exact shipped #1989 miss: opacity 0.6
    over --ink-faint measured 2.83:1 (dark) / 2.35:1 (light) — both under AA. If
    this stops failing at 0.6, the guard has gone vacuous."""
    dark = _contrast(_composite("#988D78", "#0E0C08", 0.6), "#0E0C08")
    light = _contrast(_composite("#6F6757", "#F4EFE4", 0.6), "#F4EFE4")
    assert round(dark, 2) == 2.83 and dark < AA_NORMAL
    assert round(light, 2) == 2.35 and light < AA_NORMAL
    # and at full opacity the same pairs clear AA — the fix is sound, not accidental
    assert _contrast("#988D78", "#0E0C08") >= AA_NORMAL
    assert _contrast("#6F6757", "#F4EFE4") >= AA_NORMAL


# ══════════════════════════════════════════════════════════════════════════════
# #3545 — a text token that exists ONLY in the dark block
# ══════════════════════════════════════════════════════════════════════════════
def test_no_audited_text_token_is_dark_only():
    """Every token this file holds to AA must be DECLARED in all three palette
    blocks, not merely resolvable from the dark root by fall-through.

    This is the structural half of the class #1222 (--alert), #2919/#3057 (the coach
    accents) and #3545 (the seven pillars) each fixed as one instance: a token whose
    only declaration sits in the dark `:root` silently keeps its dark value under
    light mode, where the palette around it inverted. `_token()` raises on a missing
    declaration, so simply asserting it resolves in every block IS the check — and it
    fails loudly with the token name rather than measuring a colour nobody chose."""
    blocks = _extract_theme_blocks(TOKENS.read_text(encoding="utf-8"))
    audited = sorted({t for pair in PAIRS for t in pair[:2]})
    missing = []
    for theme, block in blocks.items():
        for name in audited:
            if not re.search(rf"--{name}:\s*(#[0-9A-Fa-f]{{6}})\b", block):
                missing.append(f"[{theme}] --{name} is not declared in this palette block")
    assert not missing, (
        "a token used as TEXT is declared in only some themes — it will fall through to "
        "another theme's value (#1222 / #2919 / #3057 / #3545):\n" + "\n".join(missing)
    )


def test_pillar_light_override_guard_is_non_vacuous():
    """The must-fail control for #3545: the DARK pillar values, measured against the
    LIGHT --page, are the exact ratios live axe read on /data/character/ before the
    override existed. If these ever clear AA, the guard has gone vacuous."""
    light_page = "#F4EFE4"
    shipped_dark = {
        "sleep": ("#7B87C4", 3.00),  # axe: 2.99 on '.is-uncal.ch-cal-row:nth-child(2) > .ch-cal-p'
        "movement": ("#4E9E7C", 2.81),
        "nutrition": ("#B8862F", 2.82),
        "metabolic": ("#4E93A5", 3.03),
        "mind": ("#9781BC", 2.96),
        "relationships": ("#B06E6A", 3.47),  # axe: 3.46
        "consistency": ("#8A9455", 2.84),
    }
    for name, (hex_dark, expected) in shipped_dark.items():
        ratio = _contrast(hex_dark, light_page)
        assert round(ratio, 2) == expected, f"--pillar-{name} arithmetic drifted: {ratio:.2f} != {expected}"
        assert ratio < AA_NORMAL, f"--pillar-{name} dark-on-light no longer fails — the control is vacuous"
    # ...and the shipped light values clear it, so the fix is chosen, not accidental.
    blocks = _extract_theme_blocks(TOKENS.read_text(encoding="utf-8"))
    for theme in ("@media light", ":root[data-theme=light]"):
        block = blocks[theme]
        page = _token(block, "page")
        for name in shipped_dark:
            assert _contrast(_token(block, f"pillar-{name}"), page) >= AA_NORMAL


# ══════════════════════════════════════════════════════════════════════════════
# #3544 — the "recede" state-grammar composite guard
# ══════════════════════════════════════════════════════════════════════════════
# The platform's de-emphasis grammar was `opacity: <1` on a whole card. Element
# opacity composites the TEXT toward the page, and the plain token PAIRS above
# cannot see it — they measure tokens at full opacity. Live axe (2026-09-04) read
# ~230 serious color-contrast nodes across /data/{character,badges,vitals} from five
# such rules; the class had been fixed three times as instances (#1989 the cockpit
# scope buttons, #1822 the staged wall card, the 2026-08-31 paused-supplement cards)
# and never swept.
#
# Two halves, so this is a SET guard rather than another instance:
#   (a) every rule below is composited over --page AND --surface in all three palette
#       blocks and held to AA — with the alpha PARSED from the CSS, so re-adding an
#       opacity reds offline instead of waiting for the live sweep;
#   (b) every `opacity: <1` declaration in the two sheets must be CLASSIFIED — either
#       in RECEDE_TEXT_RULES (measured) or in DECORATIVE_OPACITY with a written reason.
#       A new dim-the-card rule cannot enter unclassified.
EVIDENCE_CSS = TOKENS.parent / "evidence.css"

# selector -> (cascade, ink tokens rendered as TEXT inside it, what the text says)
# `cascade` is ordered least-specific -> most-specific: the element's computed opacity
# is the LAST entry in it that declares one (CSS opacity does not multiply within an
# element, only across nested elements).
RECEDE_TEXT_RULES = {
    ".ch-rung.is-locked": (
        [".ch-rung.is-locked"],
        ["ink", "ink-muted", "ink-faint"],
        "a locked tier rung: name, band label, and the floor line ('The base holds and starts compounding.')",
    ),
    ".ch-fx": (
        [".ch-fx"],
        ["ink", "ink-muted", "ink-faint"],
        "a cross-pillar effect chip at rest: name, targets, and the 'activates when …' condition",
    ),
    ".ch-fx.is-inert": (
        [".ch-fx", ".ch-fx.is-inert"],
        ["ink", "ink-muted", "ink-faint"],
        "an effect chip whose condition cannot be evaluated",
    ),
    ".ch-badge": (
        [".ch-badge"],
        ["ink", "ink-faint"],
        "an unearned badge card: its name and the 'N days to unlock' hint",
    ),
    ".ch-tl li.ch-tl-muted": (
        [".ch-tl li.ch-tl-muted"],
        ["ink", "ink-muted", "ink-faint"],
        "a de-celebrated timeline row: the event line and its date label",
    ),
    ".ev-intro__note": ([".ev-intro__note"], ["ink-muted"], "the evidence-intro footnote"),
    ".rdg-abandoned .rdg-face": (
        [".rdg-abandoned .rdg-face"],
        ["ink", "ink-faint"],
        "an abandoned book's spine: title and author",
    ),
    # tokens.css — the off vital glyph (/data/vitals/)
    ".vg-off": (
        [".vg-off"],
        ["ink-muted", "ink-faint"],
        "an unlit vital glyph: the metric word and its 'No entry in 25 days' reading",
    ),
}

# Every OTHER opacity declaration in the two sheets, with the reason it is exempt from
# WCAG 1.4.3. Text-free marks and inactive UI components only — a card that wraps prose
# does not belong here, it belongs above.
DECORATIVE_OPACITY = {
    # evidence.css
    ".ev-card::before": "the spine-tick gutter strip — a background band, no text node",
    ".shimmer": "loading shimmer keyframes on skeleton blocks — no text node",
    ".sk-b": "a skeleton placeholder block — no text node",
    ".pring-seg": "the pillar-ring track segment — SVG stroke",
    '.ch-hero[data-state="dormant"] .ch-ringsvg': "the hero ring SVG — a graphic",
    '.ch-hero[data-state="dormant"] .ch-emblem': "the hero emblem SVG — a graphic",
    '.ch-hero[data-state="dormant"] .pring-fill.pring-dimmed': "a ring fill arc — SVG stroke",
    '.ch-hero[data-state="fading"] .pring-fill.pring-dimmed': "a ring fill arc — SVG stroke",
    ".ch-rbar i.ch-rbar-none": "the not-instrumented stat bar — an empty 100%-width block, no text node",
    ".ch-rung.is-locked .ch-rung-em": "tierEmblem(tier, null) — a bare glyph, aria-hidden, no text node (sigils.js)",
    ".ch-badge:not(.is-earned) .ch-badge-m": "badgeMark() — aria-hidden, geometric paths only, no text node (sigils.js)",
    ".ch-wv-na": "the no-data waveform segment — SVG fill",
    ".ch-xpbar b": "the XP-bar quartile ticks — 2px bars",
    ".ch-ticks i.dn": "an unmet gate tick — a 7x14px block",
    ".cg-cell.is-miss": "a missed consistency-grid cell — a block",
    ".part-btn:disabled": "a disabled control — WCAG 1.4.3 exempts inactive UI components",
    ".wall-attempt:not(.is-live) .wall-cell": "the sealed-attempt fingerprint SVG — evidence_wall.js puts only ${d.svg} inside",
    ".wall-cell": "the fingerprint SVG wrapper — no text node",
    ".wall-cell.is-warming": "a date-only fingerprint mark — no text node",
    ".wall-attempt.is-staged .wall-cell": "a staged fingerprint mark — no text node (#1822 already moved the text out)",
    ".rdg-abandoned .rdg-cover": "an abandoned book's cover IMAGE — the spine text is a sibling, at full contrast",
    # tokens.css
    ".vg-off .vg-dot": "the unlit glyph's 7px status dot",
    ".cgm-meal": "a CGM meal marker line — SVG stroke",
    ".cgm-meal-dot": "a CGM meal marker dot — SVG fill",
    ".wf-arrow": "the waterfall connector arrow — a decorative glyph between two labelled nodes",
    ".loop-ribbon .lr-arrow": "the loop-ribbon connector arrow — a decorative glyph",
    ".ask-btn:disabled": "a disabled control — WCAG 1.4.3 exempts inactive UI components",
    ".explain-btn:disabled": "a disabled control — WCAG 1.4.3 exempts inactive UI components",
    ".art-band": "the code-drawn editorial texture band — aria-hidden, inert (tokens.css §13)",
    ".art-band .art-count": "the counted beads inside the texture band — SVG fill",
}


def _rules(css: str):
    """(selector, body) for every flat rule in a sheet, comments stripped. Skips
    @-rule preludes; the sheets have no nested rule syntax."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        selectors, body = m.group(1), m.group(2)
        for sel in selectors.split(","):
            sel = re.sub(r"\s+", " ", sel).strip()
            if sel and not sel.startswith("@") and "{" not in sel:
                yield sel, body


def _opacity_by_selector(css: str) -> dict:
    """{normalised selector: lowest declared opacity} for every rule declaring one."""
    out = {}
    for sel, body in _rules(css):
        m = re.search(r"(?<![-\w])opacity:\s*([0-9.]+)", body)
        if m:
            value = float(m.group(1))
            out[sel] = min(out.get(sel, 1.0), value)
    return out


def _recede_alpha(declared: dict, cascade: list) -> float:
    """The element's computed opacity: the last entry in its cascade that declares
    one, 1.0 if none does. Asserts every selector in the cascade still EXISTS as a
    rule somewhere in the sheet, so a rename cannot silently no-op this guard."""
    alpha = 1.0
    for sel in cascade:
        if sel in declared:
            alpha = declared[sel]
    return alpha


def _all_selectors(css: str) -> set:
    return {sel for sel, _ in _rules(css)}


def _recede_failures(evidence_css: str, tokens_css: str) -> list:
    """The measured half. Returns a list of human-readable AA failures."""
    declared = _opacity_by_selector(evidence_css)
    declared.update(_opacity_by_selector(tokens_css))
    blocks = _extract_theme_blocks(tokens_css)
    failures = []
    for selector, (cascade, inks, what) in RECEDE_TEXT_RULES.items():
        alpha = _recede_alpha(declared, cascade)
        if alpha >= 1.0:
            continue  # no element opacity: the plain PAIRS above already hold these tokens
        for theme, block in blocks.items():
            for ink in inks:
                for bg_name in ("page", "surface"):
                    fg, bg = _token(block, ink), _token(block, bg_name)
                    ratio = _contrast(_composite(fg, bg, alpha), bg)
                    if ratio < AA_NORMAL:
                        failures.append(
                            f"[{theme}] {selector} @ opacity {alpha}: --{ink} {fg} over --{bg_name} {bg} "
                            f"= {ratio:.2f}:1 < {AA_NORMAL}:1 — {what}"
                        )
    return failures


def test_recede_grammar_composites_to_aa_in_both_themes():
    """#3544: no state-grammar rule that wraps informational text may composite its
    ink below AA, in the dark theme or either light block. The de-emphasis is a colour
    step down the ramp (--recede-ink / --recede-ink-2); an opacity here reds this."""
    failures = _recede_failures(EVIDENCE_CSS.read_text(encoding="utf-8"), TOKENS.read_text(encoding="utf-8"))
    assert not failures, (
        "the recede grammar composites informational text below WCAG AA (#3544 — "
        "recede by COLOUR, never by whole-element opacity):\n" + "\n".join(failures)
    )


def test_every_recede_selector_still_exists():
    """Guard the SET, not the instance: a rename or deletion must red this file rather
    than quietly leaving the measured rule unmeasured."""
    live = _all_selectors(EVIDENCE_CSS.read_text(encoding="utf-8")) | _all_selectors(TOKENS.read_text(encoding="utf-8"))
    gone = [sel for _, (cascade, _, _) in RECEDE_TEXT_RULES.items() for sel in cascade if sel not in live]
    assert not gone, "RECEDE_TEXT_RULES points at selectors that no longer exist — re-point it:\n" + "\n".join(sorted(set(gone)))


# A keyframe step / a pre-reveal resting-at-zero state is not a contrast question:
# `0%`, `from`, `to`, `50%` are animation stops, and motion.js's `html.mo .x { opacity: 0 }`
# is the hidden state a reveal animates OUT of. Both are excluded by shape, not by name.
_KEYFRAME_SELECTOR = re.compile(r"^(from|to|[\d.]+%)$")


def test_every_opacity_declaration_is_classified():
    """The second half of the set guard: every resting-state `opacity: <1` in
    evidence.css is either MEASURED (RECEDE_TEXT_RULES) or EXEMPT with a written reason
    (DECORATIVE_OPACITY). A new dim-the-whole-card rule cannot land unclassified —
    which is exactly how five of them accumulated into ~230 axe nodes.

    SCOPE, stated honestly: evidence.css only — the sheet that owns /data/character/,
    /data/badges/ and /wall/, every surface #3544 measured. tokens.css carries ~40 more
    opacity declarations (chart instrument parts, portraits, disabled controls); they are
    NOT classified here because that would mean asserting "no text node" for selectors
    this change did not verify. The MEASURED half above still reads tokens.css, so
    .vg-off is covered; the rest of that sheet is open work."""
    unclassified = []
    for sel, alpha in sorted(_opacity_by_selector(EVIDENCE_CSS.read_text(encoding="utf-8")).items()):
        if alpha >= 1.0 or alpha == 0.0 or _KEYFRAME_SELECTOR.match(sel):
            continue
        if sel in RECEDE_TEXT_RULES or sel in DECORATIVE_OPACITY:
            continue
        unclassified.append(f"{EVIDENCE_CSS.name}: `{sel}` declares opacity {alpha}")
    assert not unclassified, (
        "an unclassified opacity de-emphasis (#3544). If the selector wraps text, fix it with a "
        "colour step (--recede-ink / --recede-ink-2) and list it in RECEDE_TEXT_RULES; if it is a "
        "text-free mark or an inactive UI component, add it to DECORATIVE_OPACITY with the reason:\n" + "\n".join(unclassified)
    )


# The exact value each rule shipped with before #3544 swept them, and the anchor the
# control replaces to put it back. One row per RECEDE_TEXT_RULES entry — a new entry with
# no control row reds test_every_measured_rule_has_a_negative_control below, so the SET
# stays proven rather than one specimen of it.
SHIPPED_OPACITY = {
    # selector: (shipped alpha, did it ALSO fail dark?, anchor to replace, the restored rule)
    # `dark_too=False` for .ev-intro__note is a real scope fact, not a weakening: --ink-muted
    # at 0.8 held 5.13:1 on the dark page and fell to 3.35:1 on the light one. Every other
    # row failed in all three palette blocks.
    ".ch-rung.is-locked": (0.55, True, ".ch-rung.is-locked { border-style: dashed; }", ".ch-rung.is-locked { opacity: 0.55; }"),
    ".ch-fx": (0.75, True, "gap: var(--sp-1); }\n.ch-fx.is-active", "gap: var(--sp-1); opacity: 0.75; }\n.ch-fx.is-active"),
    ".ch-fx.is-inert": (0.55, True, ".ch-fx.is-inert { border-style: dashed; }", ".ch-fx.is-inert { opacity: 0.55; }"),
    ".ch-badge": (
        0.55,
        True,
        "text-align: center; }\n.ch-badge.is-earned",
        "text-align: center; opacity: 0.55; }\n.ch-badge.is-earned",
    ),
    ".ch-tl li.ch-tl-muted": (
        0.75,
        True,
        ".ch-tl li.ch-tl-muted { border-left-color: var(--rule); }",
        ".ch-tl li.ch-tl-muted { opacity: 0.75; }",
    ),
    ".ev-intro__note": (
        0.8,
        False,
        ".ev-intro__note { margin: var(--sp-3) 0 0; color: var(--ink-muted); }",
        ".ev-intro__note { margin: var(--sp-3) 0 0; color: var(--ink-muted); opacity: 0.8; }",
    ),
    ".rdg-abandoned .rdg-face": (
        0.72,
        True,
        ".rdg-abandoned .rdg-face { border-left-color: var(--ink-faint); filter: grayscale(1); }",
        ".rdg-abandoned .rdg-face { border-left-color: var(--ink-faint); opacity: 0.72; }",
    ),
    ".vg-off": (0.55, True, ".vg-off { border-style: dashed; }", ".vg-off { opacity: 0.55; border-style: dashed; }"),
}


def test_every_measured_rule_has_a_negative_control():
    """No measured rule may sit in RECEDE_TEXT_RULES without a control row. Otherwise the
    set grows entries nobody ever watched fail — the #3544 defect one abstraction up."""
    assert set(SHIPPED_OPACITY) == set(RECEDE_TEXT_RULES), (
        "SHIPPED_OPACITY and RECEDE_TEXT_RULES disagree: " f"{sorted(set(RECEDE_TEXT_RULES) ^ set(SHIPPED_OPACITY))}"
    )


@pytest.mark.parametrize("selector", sorted(SHIPPED_OPACITY))
def test_recede_guard_reds_when_the_shipped_opacity_comes_back(selector):
    """The NEGATIVE CONTROL, per measured rule, run through the real code path: put that
    rule's ORIGINAL opacity back into a copy of the live sheet and the same evaluator must
    produce failures naming that selector, in the dark block AND both light blocks.
    Without this, a guard that parsed nothing would pass identically."""
    evidence = EVIDENCE_CSS.read_text(encoding="utf-8")
    tokens_css = TOKENS.read_text(encoding="utf-8")
    assert not _recede_failures(evidence, tokens_css), "precondition: the live sheets are clean"

    alpha, dark_too, anchor, restored = SHIPPED_OPACITY[selector]
    in_tokens = anchor in tokens_css
    target = tokens_css if in_tokens else evidence
    assert target.count(anchor) == 1, f"the mutation anchor for {selector} moved — re-point this control"
    mutated = target.replace(anchor, restored, 1)
    failures = _recede_failures(evidence if in_tokens else mutated, mutated if in_tokens else tokens_css)
    mine = [f for f in failures if f"] {selector} @ opacity {alpha}" in f]
    assert mine, f"restoring the shipped opacity {alpha} on {selector} did NOT red the guard — it is vacuous"
    expected = ["@media light", ":root[data-theme=light]"] + (["dark :root"] if dark_too else [])
    for theme in expected:
        assert any(f.startswith(f"[{theme}]") for f in mine), f"the control never fired in {theme} for {selector}"
    if not dark_too:
        assert not any(
            f.startswith("[dark :root]") for f in mine
        ), f"{selector} now fails dark too — the recorded scope of this control is stale"


def test_recede_arithmetic_matches_the_live_axe_measurement():
    """The composite math is the browser's, not an approximation: these are the exact
    ratios live axe read on 2026-09-04 before the sweep."""
    assert round(_contrast(_composite("#988D78", "#0E0C08", 0.55), "#0E0C08"), 2) == 2.57  # dark --ink-faint  (axe 2.56)
    assert round(_contrast(_composite("#A99F8C", "#0E0C08", 0.55), "#0E0C08"), 2) == 2.99  # dark --ink-muted  (axe 2.99)
    assert round(_contrast(_composite("#6F6757", "#F4EFE4", 0.55), "#F4EFE4"), 2) == 2.16  # light --ink-faint (axe 2.16)


def test_ch_state_grounds_on_a_ramp_step_not_an_accent_wash():
    """#3545's wash sub-claim, resolved by the #2592 rule rather than by retuning the
    wash: a text-bearing panel grounds on a ramp step. `--ember-wash` is
    `color-mix(in oklch, var(--ember) 9%, transparent)`, so its real ground is the
    accent composited over whatever it lands on — over the light --page that is
    #EDE1D1, DARKER than any ramp step, where --ink-faint measured 4.34:1 and
    --ink-muted 4.38:1 (both confirmed against live axe's reported background).
    Derived from the CSS: flip .ch-state back onto a wash and this reds."""
    evidence = re.sub(r"/\*.*?\*/", "", EVIDENCE_CSS.read_text(encoding="utf-8"), flags=re.DOTALL)
    m = re.search(r"\.ch-state\s*\{([^}]*)\}", evidence)
    assert m, "evidence.css: no rule for .ch-state"
    bg = re.search(r"background:\s*([^;]+);", m.group(1))
    assert bg, "evidence.css: .ch-state no longer declares a background"
    token = re.fullmatch(r"var\(\s*(--[\w-]+)\s*\)", bg.group(1).strip())
    assert token and token.group(1) in ("--page", "--surface", "--surface-2", "--surface-raised"), (
        f".ch-state sits on {bg.group(1).strip()} — a text-bearing panel must ground on a paper-ramp "
        "step, whose AA is enforced by the PAIRS above and by tests/test_paper_ramp_contrast.py. "
        "A translucent accent tint (--*-wash) composites BELOW the ramp (#2592, #3545)."
    )
    # the arithmetic behind the rule, held live so the reason cannot rot
    wash_over_light_page = _composite("#A34E13", "#F4EFE4", 0.09)
    assert wash_over_light_page == "#EDE1D1"  # exactly the background live axe reported
    assert round(_contrast("#6F6757", wash_over_light_page), 2) == 4.34
    assert round(_contrast("#6E665A", wash_over_light_page), 2) == 4.39


# ══════════════════════════════════════════════════════════════════════════════
# #3544 (second pass) — the recede set DERIVED from the CSS, not enumerated
# ══════════════════════════════════════════════════════════════════════════════
# The first pass above measured a hand-written RECEDE_TEXT_RULES list of six selectors.
# A hand list only ever holds the members someone thought of, and this one missed a
# seventh, an eighth and a ninth:
#
#   `.ndots-more`          tokens.css  — the "+76" overflow badge on a sample-size dot row.
#                          It declares NO colour of its own: it inherits --ember from
#                          `.ndots.cf-high` (or --ink-muted / --ink-faint from `.cf-med` /
#                          `.cf-low`), and `opacity: 0.8` composited that inherited ink to
#                          3.32–4.47:1 in every palette block. It is emitted by
#                          charts.js::nDots ONLY when `n > cap` (12), so it did not exist on
#                          any page until the correlations crossed 12 overlapping days — the
#                          pages passed all day and then began failing. On 2026-09-06 it
#                          rolled the site back three times (site-deploy runs 34056404335,
#                          34057051481, 34066269969), each time CONFIRMED by the #2978
#                          re-probe: deterministic, never a race.
#   `.cockpit-intro__note` cockpit.css — "Shown once. It won't interrupt again." at 0.8.
#   `.rd-comp-note`        cockpit.css — "a 0 is a real reading — counted, not hidden." at 0.85.
#
# So this pass replaces the list with a DERIVATION over every stylesheet in
# site/assets/css/. Three questions, each answered from the CSS itself:
#
#   (1) which rules recede?      every `opacity: <1` declaration, minus animation stops and
#                                the `opacity: 0` pre-reveal resting state.
#   (2) which of those wrap text? the rule declares a text property itself (font-size,
#                                color, letter-spacing …), OR the sheet contains a
#                                descendant rule under it that does. The second half is what
#                                catches the original `.ch-rung.is-locked { opacity: .55 }`
#                                shape — a bare wrapper whose text lives in children.
#   (3) at what colour?          the rule's own `color:` if it declares one; otherwise the
#                                INHERITED candidates — the colours declared by its selector
#                                family (`.ndots-more` → `.ndots.cf-high|cf-med|cf-low`) and
#                                by the descendants that made it text-bearing — plus, always,
#                                the dimmest text token in the palette, because an element
#                                with no colour of its own can inherit anything above it.
#
# Everything the derivation flags is then either MEASURED to AA or listed in
# DERIVED_OPACITY_EXEMPT with a written reason. Unlike the evidence.css-only classification
# above, this half spans every sheet the site ships.

SITE_CSS_DIR = TOKENS.parent
# Derived, not enumerated: whatever stylesheets the site ships. A new sheet is in scope the
# day it lands, without anyone remembering to add it here.
GUARDED_SHEETS = tuple(sorted(SITE_CSS_DIR.glob("*.css")))

# Properties whose presence in a rule body is the CSS's own statement that the rule styles
# TEXT. `color` is included deliberately even though it also feeds currentColor on SVG and
# borders: a false positive costs one exemption line with a reason, a false negative costs a
# rolled-back deploy.
TEXT_EVIDENCE_PROPS = (
    "font-size",
    "font-family",
    "font-weight",
    "font-style",
    "font-variant",
    "font-feature-settings",
    "letter-spacing",
    "line-height",
    "text-transform",
    "text-decoration",
    "text-align",
    "text-indent",
    "word-break",
    "color",
)

# The derived text-bearing rules that are NOT held to AA, each with the reason WCAG 1.4.3
# does not reach it. Text-free marks, aria-hidden decoration and inactive UI components
# only — a rule that wraps informational prose does not belong here, it belongs in the
# measured set, and the fix is a colour step (see --recede-ink above).
DERIVED_OPACITY_EXEMPT = {
    ".wall-cell": "the attempt fingerprint SVG wrapper — evidence_wall.js puts only ${d.svg} inside, no text node",
    ".imark-rail": 'the instrument mark — <div class="imark-rail" aria-hidden="true">${instrumentMark()}</div>, an SVG glyph',
    ".wf-arrow": 'the wayfinder connector — <span class="wf-arrow" aria-hidden="true">&rarr;</span>, decorative, hidden below 600px',
    ".wf-sep": 'the wayfinder separator — <span class="wf-sep" aria-hidden="true">&middot;</span>, decorative',
    ".loop-ribbon .lr-arrow": 'the loop-ribbon connector — <span class="lr-arrow" aria-hidden="true">&rarr;</span>, decorative',
    ".loop-ribbon .lr-sep": 'the loop-ribbon separator — <span class="lr-sep" aria-hidden="true">&middot;</span>, decorative',
    ".portrait .pt-hatch": "the coach portrait's hatch layer — SVG strokes in var(--coach), no text node (portraits.js, ADR-106)",
    ".art-band": 'the code-drawn editorial texture band — <div class="art-band" aria-hidden="true">, inert (tokens.css §13)',
    ".predict-btn:disabled": "a disabled control — WCAG 1.4.3 exempts inactive UI components",
}


def _sheet_rules(path):
    return list(_rules(path.read_text(encoding="utf-8")))


def _all_guarded_rules():
    """[(sheet_name, selector, body)] across every shipped stylesheet."""
    return [(p.name, sel, body) for p in GUARDED_SHEETS for sel, body in _sheet_rules(p)]


def _declares_text(body: str) -> bool:
    return any(re.search(rf"(?<![-\w]){prop}:", body) for prop in TEXT_EVIDENCE_PROPS)


def _classes(compound: str) -> set:
    return set(re.findall(r"\.([\w-]+)", compound))


def _color_tokens(body: str) -> list:
    """The custom-property names a rule's `color:` resolves through, outermost first.

    `color: var(--coach, var(--ember))` yields ['coach', 'ember'] — every link in the
    fallback chain is a colour this element can actually render in.
    """
    m = re.search(r"(?<![-\w])color:\s*([^;]+)", body)
    if not m:
        return []
    return re.findall(r"var\(\s*--([\w-]+)", m.group(1))


def _is_pseudo_element(selector: str) -> bool:
    return "::" in selector.split()[-1]


def _dimmest_text_token(block: str, bg_hex: str, candidates) -> str:
    """The palette token, among those the sheets actually use as `color:`, that a text node
    inheriting blindly could land on with the LEAST contrast against `bg_hex`. The
    worst-case stand-in for an inherited colour nobody declared."""
    return min(candidates, key=lambda name: _contrast(_token(block, name), bg_hex))


def _derived_recede_hits():
    """Every `opacity: <1` rule the CSS itself says wraps text.

    Returns [(sheet, selector, alpha, own_color_tokens, inherited_color_tokens, why)] —
    `why` records WHICH evidence made it text-bearing, so a failure names its own reason.
    """
    rules_all = _all_guarded_rules()
    hits = []
    for sheet, selector, body in rules_all:
        m = re.search(r"(?<![-\w])opacity:\s*([0-9.]+)\s*(?:;|$)", body)
        if not m:
            continue
        alpha = float(m.group(1))
        # opacity: 0 is motion.js's pre-reveal resting state, and `from`/`to`/`50%` are
        # animation stops — neither is a rendered contrast question. Excluded by SHAPE.
        if alpha >= 1.0 or alpha == 0.0 or _KEYFRAME_SELECTOR.match(selector):
            continue
        own = _color_tokens(body)
        tail_classes = _classes(selector.split()[-1])
        descendants = []
        if not _is_pseudo_element(selector) and tail_classes:
            for _s, sel2, body2 in rules_all:
                parts = sel2.split()
                if len(parts) < 2 or not _declares_text(body2):
                    continue
                if any(tail_classes <= _classes(p) for p in parts[:-1]):
                    descendants.append((sel2, body2))
        if not _declares_text(body) and not descendants:
            continue
        why = "declares a text property" if _declares_text(body) else f"wraps text via `{descendants[0][0]}`"
        inherited = []
        if not own:
            # (a) the selector's own family — strip trailing `-segment`s off the tail class
            #     to find the block it belongs to (`.ndots-more` → `.ndots`), then take the
            #     colours every rule on that block declares. This is where --ember,
            #     --ink-muted and --ink-faint come from for the n-dots overflow badge.
            family = set()
            for cls in tail_classes:
                parts = cls.split("-")
                family.update("-".join(parts[:i]) for i in range(1, len(parts)))
            family.discard("")
            for _s, sel2, body2 in rules_all:
                if not _color_tokens(body2):
                    continue
                if _classes(sel2.split()[-1]) & family:
                    inherited.extend(_color_tokens(body2))
            # (b) the descendants that made it text-bearing declare colours of their own
            for sel2, body2 in descendants:
                inherited.extend(_color_tokens(body2))
        hits.append((sheet, selector, alpha, own, sorted(set(inherited)), why))
    return hits


def _derived_failures(hits=None) -> list:
    """The measured half: every non-exempt derived hit, composited over --page and
    --surface in all three palette blocks."""
    hits = _derived_recede_hits() if hits is None else hits
    blocks = _extract_theme_blocks(TOKENS.read_text(encoding="utf-8"))
    # The palette tokens the shipped sheets actually set text in — the pool an element with
    # no colour of its own can inherit from. Derived from the CSS, filtered to the ones the
    # palette really declares (var(--coach) and friends are per-component, not palette).
    used = {t for _s, _sel, body in _all_guarded_rules() for t in _color_tokens(body)}
    palette = sorted(t for t in used if re.search(rf"--{t}:\s*#[0-9A-Fa-f]{{6}}\b", blocks["dark :root"]))
    failures = []
    for sheet, selector, alpha, own, inherited, why in hits:
        if selector in DERIVED_OPACITY_EXEMPT:
            continue
        for theme, block in blocks.items():
            for bg_name in ("page", "surface"):
                bg = _token(block, bg_name)
                names = [t for t in (own or inherited) if re.search(rf"--{t}:\s*#[0-9A-Fa-f]{{6}}\b", block)]
                if not own:
                    # An inherited colour is whatever an ancestor happened to set, so the
                    # worst case in the palette is always in scope, not just the ancestors
                    # this parser could name. A token whose hex IS the ground is dropped
                    # first: `color: var(--page)` exists only as a deliberate inverted
                    # pairing on a filled control, never as an inherited fall-through, and
                    # keeping it would emit a meaningless --page-on---page 1.00:1 row.
                    pool = [t for t in palette if _token(block, t) != bg]
                    names.append(_dimmest_text_token(block, bg, pool))
                for ink in sorted(set(names)):
                    fg = _token(block, ink)
                    ratio = _contrast(_composite(fg, bg, alpha), bg)
                    if ratio < AA_NORMAL:
                        kind = "declares" if own else "inherits"
                        failures.append(
                            f"[{theme}] {sheet}: {selector} @ opacity {alpha} {kind} --{ink} {fg} "
                            f"over --{bg_name} {bg} = {ratio:.2f}:1 < {AA_NORMAL}:1 ({why})"
                        )
    return failures


def test_derived_text_opacity_rules_composite_to_aa():
    """#3544 second pass: NOTHING the CSS itself describes as receding text may composite
    below AA, in any shipped stylesheet, in either theme.

    Derived, not enumerated — the list this replaces missed `.ndots-more`, and
    `.ndots-more` rolled the site back three times."""
    failures = _derived_failures()
    assert not failures, (
        "a text-bearing `opacity: <1` composites below WCAG AA (#3544 — recede by COLOUR, "
        "never by whole-element opacity; see --recede-ink / --recede-ink-2 in tokens.css). "
        "If the selector is genuinely a text-free mark or an inactive UI component, add it "
        "to DERIVED_OPACITY_EXEMPT with the reason:\n" + "\n".join(failures)
    )


def test_derived_scan_is_live_and_its_exemptions_are_not_stale():
    """The derivation must actually be finding rules, and every exemption must still name a
    rule it really found. A scan that silently matched nothing would pass the test above
    identically — and a stale exemption is a member of the set nobody is measuring."""
    hits = _derived_recede_hits()
    assert hits, "the derived scan found no text-bearing opacity rule at all — the parser has gone blind"
    found = {selector for _s, selector, *_ in hits}
    stale = sorted(set(DERIVED_OPACITY_EXEMPT) - found)
    assert not stale, (
        "DERIVED_OPACITY_EXEMPT names selectors the scan no longer finds — the rule was renamed, "
        "deleted, or lost its opacity. Drop the row:\n" + "\n".join(stale)
    )
    # And the two halves must partition the set: nothing measured is exempt, nothing is both.
    measured = sorted(found - set(DERIVED_OPACITY_EXEMPT))
    assert not _derived_failures(hits), f"live sheets are not clean; measured set = {measured}"


# The exact rule text each derived member shipped with, and the anchor to put it back. The
# first three are the #3544 second-pass members; `.ch-rung.is-locked` is the ORIGINAL
# hand-listed member, replayed here to prove the derivation reaches the shape the hand list
# was written for (a bare wrapper with no text property and no colour of its own).
#
# selector: (sheet, shipped alpha, live anchor, restored rule, inherited inks, failing themes)
# The failing-theme tuple is a recorded SCOPE FACT, asserted exactly: `.cockpit-intro__note`
# renders in --ink-muted, which composites to 5.13:1 on the dark page and only misses on the
# light one, so demanding all three blocks there would be a lie. If the set a member fails in
# ever CHANGES, this reds — a widened miss is not allowed to pass as "still failing".
ALL_BLOCKS = ("dark :root", "@media light", ":root[data-theme=light]")
LIGHT_ONLY = ("@media light", ":root[data-theme=light]")
DERIVED_SHIPPED = {
    ".ndots-more": (
        "tokens.css",
        0.8,
        ".ndots-more { font-size: 0.62rem; margin-left: 2px; }",
        ".ndots-more { font-size: 0.62rem; margin-left: 2px; opacity: 0.8; }",
        ["ember", "ink-faint", "ink-muted"],
        ALL_BLOCKS,
    ),
    ".cockpit-intro__note": (
        "cockpit.css",
        0.8,
        ".cockpit-intro__note { margin: var(--sp-3) 0 0; color: var(--ink-muted); }",
        ".cockpit-intro__note { margin: var(--sp-3) 0 0; color: var(--ink-muted); opacity: 0.8; }",
        ["ink-muted"],
        LIGHT_ONLY,
    ),
    ".rd-comp-note": (
        "cockpit.css",
        0.85,
        ".rd-comp-note { margin-top: 2px; color: var(--ink-faint); }",
        ".rd-comp-note { margin-top: 2px; color: var(--ink-faint); opacity: 0.85; }",
        ["ink-faint"],
        ALL_BLOCKS,
    ),
    ".ch-rung.is-locked": (
        "evidence.css",
        0.55,
        ".ch-rung.is-locked { border-style: dashed; }",
        ".ch-rung.is-locked { opacity: 0.55; }",
        ["ink-faint"],
        ALL_BLOCKS,
    ),
}


@pytest.mark.parametrize("selector", sorted(DERIVED_SHIPPED))
def test_derived_guard_reds_when_the_shipped_opacity_comes_back(selector, monkeypatch, tmp_path):
    """THE MUST-FAIL CONTROL, per member, through the real code path: write the rule's
    shipped opacity back into a copy of the live sheet, re-point the scan at that copy, and
    the same evaluator must produce failures naming the selector in ALL THREE palette
    blocks — and naming every ink it inherits, not just one.

    That last clause is the part that matters. A guard that only measured rules with a
    literal `color:` would pass `.ndots-more` silently: the rule declares none. This asserts
    --ember, --ink-muted AND --ink-faint all appear, i.e. the inheritance really resolved."""
    sheet, alpha, anchor, restored, inks, themes = DERIVED_SHIPPED[selector]
    assert not _derived_failures(), "precondition: the live sheets are clean"

    staged = tmp_path / "css"
    staged.mkdir()
    for p in GUARDED_SHEETS:
        text = p.read_text(encoding="utf-8")
        if p.name == sheet:
            assert text.count(anchor) == 1, f"the mutation anchor for {selector} moved — re-point this control"
            text = text.replace(anchor, restored, 1)
        (staged / p.name).write_text(text, encoding="utf-8")
    monkeypatch.setattr(sys.modules[__name__], "GUARDED_SHEETS", tuple(sorted(staged.glob("*.css"))))

    failures = _derived_failures()
    mine = [f for f in failures if f"{selector} @ opacity {alpha}" in f]
    assert mine, f"restoring the shipped opacity {alpha} on {selector} did NOT red the derived guard — it is vacuous"
    # NB the block label itself contains a "]" (`:root[data-theme=light]`), so match by
    # prefix against the known block names rather than splitting on the bracket.
    fired = {t for t in ALL_BLOCKS for f in mine if f.startswith(f"[{t}]")}
    assert fired == set(themes), f"{selector} fails in {sorted(fired)}, but its recorded scope is {sorted(themes)} — the control is stale"
    for ink in inks:
        assert any(
            f"--{ink} " in f for f in mine
        ), f"{selector}'s control never measured the inherited --{ink} — inheritance did not resolve"


def test_ndots_more_arithmetic_matches_the_live_axe_measurement():
    """The blocking instance, pinned to the numbers a browser actually produced.

    Live axe on /method/intelligence/ (chromium, 1440x900, light) read --ember #A34E13 at
    4.45:1 on the flagged row's ember wash. The dark-theme composite at the shipped
    opacity 0.8 is 4.47:1 on --page — a MISS by 0.03, which is why this member sat
    invisible until n crossed the dot cap and then failed deterministically."""
    assert round(_contrast(_composite("#DD7A37", "#0E0C08", 0.8), "#0E0C08"), 2) == 4.47  # dark  --ember @0.8
    assert round(_contrast(_composite("#A34E13", "#F4EFE4", 0.8), "#F4EFE4"), 2) == 3.51  # light --ember @0.8
    assert round(_contrast(_composite("#6F6757", "#F4EFE4", 0.8), "#F4EFE4"), 2) == 3.32  # light --ink-faint @0.8
    # …and at full opacity every one of the three inherited inks clears AA on both grounds,
    # so dropping the opacity is a fix, not a coincidence.
    for fg in ("#DD7A37", "#A99F8C", "#988D78"):
        assert _contrast(fg, "#0E0C08") >= AA_NORMAL
    for fg in ("#A34E13", "#6E665A", "#6F6757"):
        assert _contrast(fg, "#F4EFE4") >= AA_NORMAL


def test_flagged_row_names_the_ndots_parent_not_three_of_its_four_states():
    """#3325 lifted a flagged table row's faint readouts to --ink because --ember and the
    faint inks both miss AA on the ember wash (4.34–4.45:1 over the light --page). It did
    that by ENUMERATING `.ndots.cf-med, .ndots.cf-low, .ndots--none` — and left `.cf-high`,
    the one state that renders in --ember, still failing. Requiring the PARENT `.ndots`
    means every confidence state, and the `.ndots-more` badge inheriting from it, is
    covered by construction. Re-enumerate the states and this reds."""
    evidence = re.sub(r"/\*.*?\*/", "", EVIDENCE_CSS.read_text(encoding="utf-8"), flags=re.DOTALL)
    m = re.search(r"\.rd-tbl tr\.rd-flag :is\(([^)]*)\)\s*\{([^}]*)\}", evidence)
    assert m, "evidence.css: the flagged-row ink override is gone — re-point this guard"
    members = {s.strip() for s in m.group(1).split(",")}
    assert "--ink" in m.group(2), "the flagged-row override no longer lifts to --ink"
    assert ".ndots" in members, (
        "the flagged-row ink override enumerates .ndots confidence states instead of naming the "
        f"parent .ndots — .cf-high would miss AA on the wash again (#3325 / #3544). Members: {sorted(members)}"
    )
    assert ".rd-flagmark" in members, "the FDR flag mark renders in --ember, which is 4.45:1 on the wash — it must lift to --ink"
    # the arithmetic the rule exists for, held live
    wash = _composite("#A34E13", "#F4EFE4", 0.09)
    assert wash == "#EDE1D1"  # the background live axe reported
    assert round(_contrast("#A34E13", wash), 2) == 4.46 and _contrast("#A34E13", wash) < AA_NORMAL  # axe rounds down to 4.45


@pytest.mark.parametrize("selector", sorted(DERIVED_OPACITY_EXEMPT))
def test_every_derived_exemption_is_load_bearing(selector, monkeypatch):
    """The other must-fail control, one per exemption: an exemption that changes nothing is
    a row nobody would notice going wrong.

    Drop the row and the MEASURED half must red naming that selector, in all three palette
    blocks — i.e. every entry in DERIVED_OPACITY_EXEMPT is genuinely holding back a real
    AA failure, and is a written WCAG 1.4.3 judgement rather than a shrug. Together with
    test_derived_scan_is_live_and_its_exemptions_are_not_stale (which reds if the CSS rule
    behind a row disappears) that is both directions, per entry."""
    reason = DERIVED_OPACITY_EXEMPT[selector]
    assert reason.strip(), f"{selector} is exempt with no written reason"
    kept = {k: v for k, v in DERIVED_OPACITY_EXEMPT.items() if k != selector}
    monkeypatch.setattr(sys.modules[__name__], "DERIVED_OPACITY_EXEMPT", kept)
    mine = [f for f in _derived_failures() if f" {selector} @ opacity" in f]
    assert mine, f"un-exempting {selector} produced no AA failure — the exemption is decorative, drop it"
    for theme in ALL_BLOCKS:
        assert any(f.startswith(f"[{theme}]") for f in mine), f"{selector} does not fail in {theme} — narrow the row's reason"
