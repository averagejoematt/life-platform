"""#1222 — WCAG AA contrast guard for the light-mode --alert token.

The dark root defines --alert #CB634C, which measures only 3.37:1 on the light
--page #F4EFE4 (3.65:1 on --surface) — failing WCAG AA (4.5:1) for the normal-size
.vr-alert .vr-v ring-center value (--fs-h4 ~1.05rem). #579 fixed dark mode only;
both light-mode blocks must override --alert (as they already do --ember/--ink-*).

This parses the hexes straight out of site/assets/css/tokens.css for BOTH light
theme blocks — the @media (prefers-color-scheme: light) block and the explicit
:root[data-theme="light"] block — and asserts the documented text-on-background
pairs clear 4.5:1 via a WCAG relative-luminance computation. Offline, stdlib-only,
repo-only: safe in the CI unit-test job (ADR-103-clean).
"""

import re
from pathlib import Path

TOKENS = Path(__file__).resolve().parent.parent / "site" / "assets" / "css" / "tokens.css"

AA_NORMAL = 4.5  # WCAG AA for normal-size text


def _linear(channel: float) -> float:
    return channel / 12.92 if channel <= 0.03928 else ((channel + 0.055) / 1.055) ** 2.4


def _luminance(hex_str: str) -> float:
    r, g, b = (channel / 255 for channel in bytes.fromhex(hex_str.lstrip("#")))
    return 0.2126 * _linear(r) + 0.7152 * _linear(g) + 0.0722 * _linear(b)


def _contrast(fg: str, bg: str) -> float:
    a, b = _luminance(fg), _luminance(bg)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


def _extract_light_blocks(css: str):
    """Return (media_light_block, data_theme_light_block) as raw text slices."""
    # @media (prefers-color-scheme: light) { :root:not([data-theme="dark"]) { ... } }
    media = re.search(
        r"@media\s*\(prefers-color-scheme:\s*light\)\s*\{\s*" r":root:not\(\[data-theme=\"dark\"\]\)\s*\{(.*?)\}\s*\}",
        css,
        re.DOTALL,
    )
    # :root[data-theme="light"] { ... }  (the explicit-choice block, not the placeholder)
    data_theme = re.search(
        r":root\[data-theme=\"light\"\]\s*\{\s*color-scheme:\s*light;(.*?)\}",
        css,
        re.DOTALL,
    )
    assert media, "could not locate the @media (prefers-color-scheme: light) block"
    assert data_theme, 'could not locate the :root[data-theme="light"] block'
    return media.group(1), data_theme.group(1)


def _token(block: str, name: str) -> str:
    m = re.search(rf"--{name}:\s*(#[0-9A-Fa-f]{{6}})", block)
    assert m, f"--{name} not found / not a 6-digit hex in light block:\n{block}"
    return m.group(1)


def test_light_mode_alert_clears_wcag_aa_on_page_and_surface():
    css = TOKENS.read_text(encoding="utf-8")
    media_block, data_theme_block = _extract_light_blocks(css)

    for label, block in (("@media light", media_block), (":root[data-theme=light]", data_theme_block)):
        page = _token(block, "page")
        surface = _token(block, "surface")
        alert = _token(block, "alert")

        r_page = _contrast(alert, page)
        r_surface = _contrast(alert, surface)

        assert r_page >= AA_NORMAL, (
            f"[{label}] --alert {alert} on --page {page} = {r_page:.2f}:1 " f"< {AA_NORMAL}:1 (WCAG AA, .vr-alert .vr-v normal text)"
        )
        assert r_surface >= AA_NORMAL, (
            f"[{label}] --alert {alert} on --surface {surface} = {r_surface:.2f}:1 "
            f"< {AA_NORMAL}:1 (WCAG AA, .vr-alert .vr-v normal text)"
        )
