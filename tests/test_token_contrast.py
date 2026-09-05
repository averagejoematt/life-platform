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
