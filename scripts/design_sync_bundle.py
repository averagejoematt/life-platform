#!/usr/bin/env python3
"""design_sync_bundle.py — export the v5 design system as a self-contained Claude Design
bundle (#1462, Epic #1460 D1: "REPO (truth) -> CLAUDE DESIGN PROJECT").

Produces a four-directory bundle at --out (default: scratch/design_sync_bundle/, already
gitignored):

    assets/         tokens.css + fonts.css (rewritten relative) + the 5 self-hosted woff2 +
                     a fonts_base64.json manifest (fonts need base64 for binary upload to a
                     design project) + icons.svg
    foundations/    palette (dark + light), type triad, spacing/radii, pillar colors, the
                     6 canonical breakpoints — every value pulled live from tokens.css, not
                     hand-copied, so the bundle can't silently drift from repo truth
    components/     the shared kit with sample data: .page-hero + .loop-ribbon, .prose,
                     .provenance, .tabset, the .loop diagram, the .rd-* readout family,
                     .cb-* correlation cards, the confidence grammar (fan/whisker/nDots),
                     coach sigils + tier emblems, coach portraits, the icon sheet, and a
                     charts.js gallery
    reference/      a handful of representative BUILT pages (home, cockpit, the data hub)
                     with every asset/nav reference rewritten to resolve from the bundle.
                     The LIVE layer of reference/ — full-page captures of the current
                     site (the doors + a data-dense surface) — is added by the companion
                     script scripts/design_sync_capture.py (#1467), which runs AFTER this
                     builder: captures are network-dependent and change with the live
                     data, so they stay out of this deterministic build on purpose

Three special cases (from the issue's evidence inventory), each handled explicitly and
documented here rather than silently:

  1. motion.js is the one IIFE in the JS layer (every other module is a plain ES module
     export). It is OMITTED from every preview/reference page: motion.js only ever ADDS a
     reveal transition on top of content that already painted (fail-open by design — see
     DESIGN_SYSTEM_V5.md §7, "Motion can never hide content") — so leaving it out changes
     nothing about what a design session sees, and it avoids wiring an IIFE into a bundle
     built for review, not interaction. The inline motion head-guard script (the one that
     sets `html.mo`) is omitted for the same reason on reference/ pages.

  2. Breakpoints are NOT CSS custom properties (`--bp-*` cannot be read from inside an
     `@media` query, so tokens.css documents them as a comment-block table instead of
     `:root` declarations — see tokens.css "RESPONSIVE BREAKPOINTS"). This script parses
     that comment block with a dedicated regex (`_parse_breakpoints`), not the `:root`
     parser used for every other foundation.

  3. Fonts are binary (woff2) and most upload surfaces for a design project take files or
     base64, not a live URL a browser can fetch. `assets/fonts_base64.json` carries a
     `{filename: base64}` manifest of all 5 vendored woff2 files alongside the raw copies,
     so either upload path works without re-deriving anything.

A fourth, code-level special case: `charts.js` and `sigils.js` deliberately import
`svgtype.js` via an ABSOLUTE path (`/assets/js/svgtype.js`) in the live site — that's
required for `deploy/hash_site_assets.py`'s asset-hashing graph walk (a relative import
"escapes" its regex — see the comment in charts.js). This script's bundle copies rewrite
that one import line to a relative `./svgtype.js` so the copies resolve when served from
the bundle root instead of the live CDN; the live source files are untouched.

Determinism: every foundation/component value is parsed straight out of the checked-in
tokens.css / icons.svg / charts.js / sigils.js / v4_kit.py at HEAD, file lists are sorted,
no timestamps are written into content, and the output directory is fully recreated
(rmtree + mkdir) on every run — same repo state in, byte-identical bundle out.

Usage:
    python3 scripts/design_sync_bundle.py [--out DIR] [--repo-root DIR]

Self-verifies on exit: after writing every file, the bundle is swept for the two things a
Claude Design session cannot resolve (an absolute `/…` asset/nav reference, or a literal
`https://averagejoematt` URL) and for the `@dsCard` marker contract on every
foundations/components/reference card (#1467 extended the marker contract to reference/).
A violation raises — this script cannot silently ship a broken bundle.
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import shutil
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT_DEFAULT = SCRIPT_DIR.parent

# ─────────────────────────────────────────────────────────────────────────────
# tokens.css parsing — every foundation value below is derived from this file,
# never hand-copied, so the bundle can't drift from repo truth.
# ─────────────────────────────────────────────────────────────────────────────

_SECTION_HEADER_RE = re.compile(r"^/\* ── (.+?) ─+\s*\*/\s*$", re.M)
_VAR_RE = re.compile(r"--([\w-]+):\s*([^;]+);(?:\s*/\*(.*?)\*/)?", re.S)
_BP_RE = re.compile(r"--bp-(\w+)\s+(\d+)\s+(.+)")


def _section(css: str, header_startswith: str) -> str:
    """Return the text between a section's `/* ── … ── */` header comment and the next one.

    Section headers in tokens.css look like `/* ── 1. Palette — dark (primary) ── … */`
    (see the `grep -n '^/\\* ── '` map used to build this parser). Matching on a stable
    prefix (rather than the full banner, whose trailing dash-count/comment-close varies)
    keeps this resilient to the cosmetic re-padding tokens.css sometimes gets.
    """
    headers = list(_SECTION_HEADER_RE.finditer(css))
    for i, m in enumerate(headers):
        if m.group(1).startswith(header_startswith):
            start = m.end()
            end = headers[i + 1].start() if i + 1 < len(headers) else len(css)
            return css[start:end]
    raise AssertionError(
        f"tokens.css section header not found: {header_startswith!r} (upstream"
        f" tokens.css structure changed — update design_sync_bundle.py's section map)"
    )


def _parse_vars(section_text: str) -> list[tuple[str, str, str]]:
    """Parse `--name: value;` declarations (with an optional trailing /* comment */) out of
    a section's `:root { … }` block(s). Returns (name, value, note) triples in file order."""
    out = []
    for m in _VAR_RE.finditer(section_text):
        name, value, note = m.group(1), m.group(2).strip(), (m.group(3) or "").strip()
        note = re.sub(r"\s+", " ", note)
        out.append((name, value, note))
    return out


def _parse_light_palette(css: str) -> list[tuple[str, str, str]]:
    """The light-mode palette lives in the explicit `:root[data-theme="light"] { … }`
    override block (tokens.css §9), not the `@media (prefers-color-scheme: light)`
    duplicate above it — that block is the one an explicit `data-theme="light"` picks up,
    which is exactly how foundations/palette-light.html forces light mode for the preview."""
    m = re.search(r':root\[data-theme="light"\]\s*\{(.*?)\n\}', css, re.S)
    if not m:
        raise AssertionError('tokens.css :root[data-theme="light"] block not found — light palette source moved')
    return _parse_vars(m.group(1))


def _parse_breakpoints(css: str) -> list[tuple[str, str, str]]:
    """Special case #2 (see module docstring): breakpoints are a comment-block table, not
    `:root` custom properties, because `@media` can't read a CSS variable. Parsed straight
    out of the RESPONSIVE BREAKPOINTS comment block."""
    m = re.search(r"RESPONSIVE BREAKPOINTS.*?═+(.*?)═+", css, re.S)
    if not m:
        raise AssertionError("tokens.css RESPONSIVE BREAKPOINTS comment block not found")
    block = m.group(1)
    rows = [(bp, px, re.sub(r"\s+", " ", job).strip()) for bp, px, job in _BP_RE.findall(block)]
    if len(rows) != 6:
        raise AssertionError(f"expected the 6 canonical breakpoints, parsed {len(rows)} — tokens.css breakpoint block changed shape")
    return rows


def _parse_pillar_colors(css: str) -> list[tuple[str, str]]:
    # "Pillar identity colors" is a multi-line banner comment (doesn't close with `*/` on
    # its own line like the numbered sections), so anchor on the header text directly
    # rather than routing through the numbered-section splitter.
    i = css.find("Pillar identity colors")
    if i < 0:
        raise AssertionError("tokens.css 'Pillar identity colors' header not found")
    m = re.search(r":root\s*\{(.*?)\n\}", css[i:], re.S)
    if not m:
        raise AssertionError("pillar identity colors :root block not found")
    pairs = re.findall(r"--(pillar-[\w-]+):\s*(#[0-9A-Fa-f]{6});", m.group(1))
    if len(pairs) != 7:
        raise AssertionError(f"expected 7 pillar colors, parsed {len(pairs)}")
    return pairs


def _parse_icon_ids(icons_svg: str) -> list[str]:
    ids = re.findall(r'<symbol\s+id="([^"]+)"', icons_svg)
    if not ids:
        raise AssertionError("no <symbol id=…> entries parsed out of icons.svg")
    return ids


# ─────────────────────────────────────────────────────────────────────────────
# small HTML helpers
# ─────────────────────────────────────────────────────────────────────────────


def _esc(s: str) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _page(group: str, title: str, body: str, *, theme: str = "dark", extra_head: str = "", extra_body: str = "") -> str:
    """Wrap `body` in the standard preview-page shell. The `@dsCard` marker MUST be byte 0
    of the file (acceptance criterion #2) — everything else, including `<!doctype html>`,
    comes after it."""
    return (
        f'<!-- @dsCard group="{_esc(group)}" -->\n'
        "<!doctype html>\n"
        f'<html lang="en" data-theme="{theme}">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{_esc(group)} / {_esc(title)} — v5 design system</title>\n"
        '<link rel="stylesheet" href="../assets/css/fonts.css">\n'
        '<link rel="stylesheet" href="../assets/css/tokens.css">\n'
        "<style>\n"
        "  body{padding:var(--sp-7) var(--gutter);max-width:var(--container);margin:0 auto;}\n"
        "  .ds-title{margin-bottom:var(--sp-6);}\n"
        "  .ds-group{display:flex;flex-wrap:wrap;gap:var(--sp-5);align-items:flex-start;}\n"
        "  .ds-swatch{display:flex;flex-direction:column;gap:var(--sp-2);width:180px;}\n"
        "  .ds-chip{height:64px;border-radius:var(--radius);border:var(--border-hair);}\n"
        "  .ds-cap{font-family:var(--font-mono);font-size:var(--fs-small);color:var(--ink-muted);}\n"
        "  .ds-note{color:var(--ink-faint);font-size:var(--fs-small);margin-top:var(--sp-1);}\n"
        "  .ds-block{margin-bottom:var(--sp-8);}\n"
        "  table.ds-tbl{border-collapse:collapse;width:100%;}\n"
        "  table.ds-tbl th, table.ds-tbl"
        " td{text-align:left;padding:var(--sp-2) var(--sp-4);border-bottom:var(--border-hair);font-size:var(--fs-small);}\n"
        "</style>\n"
        f"{extra_head}"
        "</head>\n"
        "<body>\n"
        f'<p class="label ds-title">{_esc(group)} / {_esc(title)}</p>\n'
        f"{body}\n"
        f"{extra_body}"
        "</body>\n"
        "</html>\n"
    )


# ─────────────────────────────────────────────────────────────────────────────
# foundations/
# ─────────────────────────────────────────────────────────────────────────────


def _write_palette(out_dir: Path, name: str, title: str, theme: str, rows: list[tuple[str, str, str]]) -> None:
    swatches = []
    for varname, value, note in rows:
        if value.startswith("#") or value.startswith("rgba(") or "color-mix(" in value:
            chip = f'<div class="ds-chip" style="background:var(--{_esc(varname)})"></div>'
        else:
            chip = (
                '<div class="ds-chip" style="display:flex;align-items:center;justify-content:center;'
                'font-family:var(--font-mono);font-size:11px;">n/a (not a color)</div>'
            )
        cap = f"--{_esc(varname)}<br>{_esc(value)}"
        note_html = f'<span class="ds-note">{_esc(note)}</span>' if note else ""
        swatches.append(f'<div class="ds-swatch">{chip}<span class="ds-cap mono">{cap}</span>{note_html}</div>')
    body = f'<div class="ds-block"><div class="ds-group">{"".join(swatches)}</div></div>'
    (out_dir / f"{name}.html").write_text(_page("foundations", title, body, theme=theme), encoding="utf-8")


def _write_type_triad(out_dir: Path, rows: list[tuple[str, str, str]]) -> None:
    by_name = {n: v for n, v, _ in rows}
    samples = [
        ("--font-serif", "--fs-display", "Human voice — Fraunces display"),
        ("--font-serif", "--fs-h1", "Human voice — Fraunces h1"),
        ("--font-serif", "--fs-quote", "Human voice — Fraunces italic quote", "italic"),
        ("--font-sans", "--fs-body-lg", "Interface — Instrument Sans"),
        ("--font-sans", "--fs-body", "Interface — Instrument Sans body"),
        ("--font-mono", "--fs-data-xl", "Machine & data — IBM Plex Mono (tabular-nums)"),
        ("--font-mono", "--fs-label", "Machine & data — IBM Plex Mono label (uppercase, tracked)", "label"),
    ]
    rows_html = []
    for sample in samples:
        font, size, caption = sample[0], sample[1], sample[2]
        style_variant = sample[3] if len(sample) > 3 else ""
        assert font.lstrip("-") in by_name and size.lstrip("-") in by_name, f"unknown token in type-triad sample: {font}/{size}"
        style = f"font-family:var({font});font-size:var({size});"
        if style_variant == "italic":
            style += "font-style:italic;"
        cls = "label" if style_variant == "label" else ""
        text = "The measured life" if style_variant != "label" else "MACHINE LABEL — 11PX TRACKED"
        rows_html.append(
            f'<div class="ds-block"><p class="ds-cap mono">{_esc(font)} · {_esc(size)} — {_esc(caption)}</p>'
            f'<p class="{cls}" style="{style}margin:0;">{_esc(text)} 1234567890</p></div>'
        )
    (out_dir / "type-triad.html").write_text(_page("foundations", "Type triad", "".join(rows_html)), encoding="utf-8")


def _write_spacing_radii(out_dir: Path, spacing: list[tuple[str, str, str]], radii: list[tuple[str, str, str]]) -> None:
    sp_boxes = []
    for name, value, _ in spacing:
        if not name.startswith("sp-"):
            continue
        sp_boxes.append(
            f'<div class="ds-swatch"><div'
            f' style="width:var(--{name});height:var(--{name});background:var(--ember);border-radius:2px;"></div>'
            f'<span class="ds-cap mono">--{_esc(name)}<br>{_esc(value)}</span></div>'
        )
    rad_boxes = []
    for name, value, _ in radii:
        if not name.startswith("radius"):
            continue
        rad_boxes.append(
            f'<div class="ds-swatch"><div style="width:64px;height:64px;background:var(--surface-raised);'
            f'border:var(--border-strong);border-radius:var(--{name});"></div>'
            f'<span class="ds-cap mono">--{_esc(name)}<br>{_esc(value)}</span></div>'
        )
    body = (
        f'<div class="ds-block"><p class="ds-cap mono">Spacing — 4px base rhythm</p><div class="ds-group">{"".join(sp_boxes)}</div></div>'
        f'<div class="ds-block"><p class="ds-cap mono">Radii</p><div class="ds-group">{"".join(rad_boxes)}</div></div>'
    )
    (out_dir / "spacing-radii.html").write_text(_page("foundations", "Spacing & radii", body), encoding="utf-8")


def _write_pillar_colors(out_dir: Path, pillars: list[tuple[str, str]]) -> None:
    tiers = ["foundation", "momentum", "discipline", "mastery", "elite"]
    swatches = "".join(
        f'<div class="ds-swatch"><div class="ds-chip" style="background:var(--{_esc(n)})"></div>'
        f'<span class="ds-cap mono">--{_esc(n)}<br>{_esc(hexv)}</span></div>'
        for n, hexv in pillars
    )
    tier_chips = "".join(
        f'<div class="ds-swatch" data-tier="{t}"><div class="ds-chip" style="background:var(--tier-accent)"></div>'
        f'<span class="ds-cap mono">[data-tier="{t}"]<br>--tier-accent</span></div>'
        for t in tiers
    )
    body = (
        f'<div class="ds-block"><p class="ds-cap mono">--pillar-* (identity encoding only'
        f' — never buttons/text/alerts)</p><div class="ds-group">{swatches}</div></div>'
        f'<div class="ds-block"><p class="ds-cap mono">--tier-accent (set via [data-tier] —'
        f' tier emblem + hero frame only)</p><div class="ds-group">{tier_chips}</div></div>'
    )
    (out_dir / "pillar-colors.html").write_text(_page("foundations", "Pillar identity colors", body), encoding="utf-8")


def _write_breakpoints(out_dir: Path, rows: list[tuple[str, str, str]]) -> None:
    trs = "".join(
        f"<tr><td class=mono>--bp-{_esc(bp)}</td><td class=mono>{_esc(px)}px</td><td>{_esc(job)}</td></tr>" for bp, px, job in rows
    )
    body = (
        '<p class="ds-note">Parsed from the RESPONSIVE BREAKPOINTS comment block in tokens.css — breakpoints '
        "cannot be CSS custom properties (a <code>@media</code> query can't read a <code>var()</code>), "
        "so they're documented named constants instead of <code>:root</code> declarations "
        "(special case #2, see this script's module docstring).</p>"
        f'<table class="ds-tbl"><thead><tr><th>token</th><th>px</th><th>job</th></tr></thead><tbody>{trs}</tbody></table>'
    )
    (out_dir / "breakpoints.html").write_text(_page("foundations", "Breakpoints", body), encoding="utf-8")


# ─────────────────────────────────────────────────────────────────────────────
# components/ — hand-authored sample markup, each pattern lifted verbatim from
# a real call site (v4_kit.py / v4_build_evidence.py / coaching.js / evidence_habits.js /
# evidence_meta.js / tokens.css's own .tabset contract) so previews match production DOM,
# not an invented approximation.
# ─────────────────────────────────────────────────────────────────────────────


def _loop_ribbon(current_door: str) -> str:
    """Sourced from scripts/v4_kit.py's loop_ribbon() — imported directly rather than
    re-implemented, so this preview can never drift from the real generator. Production
    markup is absolute-path by design (`/data/`, `/coaching/`, …, meant to run on the live
    site) — neutralized the same way a reference/ page's nav links are (see
    `_neutralize_nav_links`) so the preview ships zero absolute refs."""
    sys.path.insert(0, str(SCRIPT_DIR))
    from v4_kit import loop_ribbon  # noqa: E402  (local import — scripts/ path added just above)

    return _neutralize_nav_links(loop_ribbon(current_door))


def _write_page_hero(out_dir: Path) -> None:
    body = (
        '<div class="page-hero">\n'
        '  <p class="ph-kicker label">the data · sleep</p>\n'
        '  <h1 class="ph-title">Sleep — a full-night ledger, not a single score</h1>\n'
        '  <p class="ph-promise">Every stage, every night, and how it moves everything else.</p>\n'
        f"  {_loop_ribbon('data')}\n"
        "</div>"
    )
    (out_dir / "page-hero-loop-ribbon.html").write_text(_page("components", ".page-hero + .loop-ribbon", body), encoding="utf-8")


def _write_prose(out_dir: Path) -> None:
    body = (
        '<div class="prose">\n'
        "<h2>What the week actually said</h2>\n"
        "<p>Four nights under seven hours, two of them back to back. The recovery score tracked it almost "
        "exactly — not a coincidence, the same pattern shows up every time sleep debt compounds.</p>\n"
        "<blockquote>The band never lies about sleep the way people do to themselves.</blockquote>\n"
        "<h3>What moved</h3>\n"
        "<ul><li>Resting heart rate up 4 bpm on the two short nights</li>"
        "<li>HRV down across the same window, recovering by day three</li>"
        "<li>Training load held steady — the body absorbed it, this time</li></ul>\n"
        '<p>Full breakdown in <a href="#">the sleep readout</a>.</p>\n'
        "</div>"
    )
    (out_dir / "prose.html").write_text(_page("components", ".prose — the typographic fix", body), encoding="utf-8")


def _write_provenance(out_dir: Path) -> None:
    body = (
        '<p class="provenance"><span class="pv-src">whoop</span><span>updated 6m ago</span></p>\n'
        '<p class="provenance pv-stale"><span class="fr-dot" aria-hidden="true"></span>'
        '<span class="pv-src">todoist</span> <span class="rd-unit">31h</span></p>'
    )
    (out_dir / "provenance.html").write_text(_page("components", ".provenance — fresh + stale", body), encoding="utf-8")


def _write_tabset(out_dir: Path) -> None:
    body = (
        '<div class="tabset" role="tablist" aria-label="Coach profile sections">\n'
        '  <button class="tab" role="tab" aria-selected="true">Bio</button>\n'
        '  <button class="tab" role="tab" aria-selected="false">Track record</button>\n'
        '  <button class="tab" role="tab" aria-selected="false">Current read</button>\n'
        "</div>\n"
        '<div class="tabpanel prose" role="tabpanel">'
        "<p>Bio panel content — the active tab's region. Inactive panels carry the "
        "<code>hidden</code> attribute (<code>.tabpanel[hidden]{display:none}</code>).</p></div>"
    )
    (out_dir / "tabset.html").write_text(_page("components", ".tabset + .tabpanel", body), encoding="utf-8")


def _write_loop_diagram(out_dir: Path) -> None:
    body = (
        '<div class="loop">\n'
        '  <a class="loop-node" href="#"><span class="ln-name">The Data</span><span'
        ' class="ln-role">Every source — the body, the mind — now and over time.</span></a>\n'
        '  <span class="loop-arrow" aria-hidden="true">→</span>\n'
        '  <a class="loop-node" href="#"><span class="ln-name">The Coaching</span><span'
        ' class="ln-role">AI coaches read the data and offer different takes on it.</span></a>\n'
        '  <span class="loop-arrow" aria-hidden="true">→</span>\n'
        '  <a class="loop-node" href="#"><span class="ln-name">The Protocols</span><span'
        ' class="ln-role">The levers — what gets changed to move the data.</span></a>\n'
        '  <span class="loop-arrow" aria-hidden="true">→</span>\n'
        '  <a class="loop-node" href="#"><span class="ln-name">The Story</span><span'
        ' class="ln-role">The human journey — chronicle, podcast, journal.</span></a>\n'
        "</div>"
    )
    (out_dir / "loop-diagram.html").write_text(_page("components", ".loop — the causal-loop card row", body), encoding="utf-8")


def _write_readout(out_dir: Path) -> None:
    body = (
        '<ul style="list-style:none;padding:0;display:flex;flex-direction:column;gap:var(--sp-3);">\n'
        '  <li class="rd-card" style="--coach:#DD7A37;"><button type="button"'
        ' class="rd-btn" style="all:unset;cursor:pointer;display:block;">'
        '<span class="rd-body"><span class="rd-top"><span class="rd-dom label">sleep coach</span>'
        '<span class="rd-name">Dr. Elena Voss</span></span>'
        '<span class="rd-say">Consolidation over duration this week — the fragmented nights cost more than the short ones.</span>'
        '<span class="rd-asof label">as of today</span></span></button></li>\n'
        "</ul>\n"
        '<div class="rd-sec" style="margin-top:var(--sp-6);">\n'
        '  <div class="table-scroll"><table class="rd-tbl"><thead><tr><th>metric</th><th>value</th><th>flag</th></tr></thead>'
        '<tbody><tr><td>RHR</td><td class="num">54 bpm</td><td><span class="rd-flag">watch</span></td></tr></tbody></table></div>\n'
        "</div>"
    )
    (out_dir / "readout.html").write_text(_page("components", "the .rd-* readout family", body), encoding="utf-8")


def _write_cb_cards(out_dir: Path) -> None:
    body = (
        '<div class="cb-grid">\n'
        '  <article class="cb-card"><header class="cb-head"><h3 class="cb-pair">sleep'
        ' duration <span class="cb-arrow">→</span> the day grade</h3>'
        '<span class="cb-tag">medium confidence</span></header>'
        '<div class="cb-read"><p class="cb-dir mono">r = 0.41</p></div>'
        '<p class="cb-meta label">n=18 · 2.6 wk overlap · N=1, correlative</p></article>\n'
        '  <article class="cb-card"><header class="cb-head"><h3 class="cb-pair">late'
        ' caffeine <span class="cb-arrow">→</span> the day grade</h3>'
        '<span class="cb-tag">low confidence</span></header>'
        '<div class="cb-read"><p class="cb-dir">a weak negative pull — direction only, coefficient too weak to trust'
        '<span class="cb-noise">⚠ likely noise at this n — direction only</span></p></div>'
        '<p class="cb-meta label">n=6 · 0.9 wk overlap · N=1, correlative</p></article>\n'
        "</div>"
    )
    (out_dir / "cb-cards.html").write_text(_page("components", ".cb-* correlation cards", body), encoding="utf-8")


def _write_icon_sheet(out_dir: Path, icon_ids: list[str]) -> None:
    cells = "".join(
        f'<div class="ds-swatch" style="width:90px;align-items:center;">'
        f'<svg class="ico" style="width:28px;height:28px;" aria-hidden="true"><use href="../assets/icons/icons.svg#{_esc(i)}"></use></svg>'
        f'<span class="ds-cap mono">{_esc(i)}</span></div>'
        for i in icon_ids
    )
    body = f'<div class="ds-group">{cells}</div>'
    (out_dir / "icon-sheet.html").write_text(_page("components", f"the icon sheet ({len(icon_ids)} symbols)", body), encoding="utf-8")


def _write_portraits(out_dir: Path, portrait_names: list[str]) -> None:
    rows = []
    for name in portrait_names:
        cells = "".join(
            f'<div class="ds-swatch" style="width:96px;"><img src="img/portraits/{name}-96-ondark.png"'
            f' alt="" width="96" height="96" style="background:var(--page);border-radius:var(--radius);">'
            f'<span class="ds-cap mono">96 · on-dark</span></div>'
            f'<div class="ds-swatch" style="width:96px;"><img src="img/portraits/{name}-96-onlight.png"'
            f' alt="" width="96" height="96" style="background:var(--page);border-radius:var(--radius);">'
            f'<span class="ds-cap mono">96 · on-light</span></div>'
        )
        rows.append(f'<div class="ds-block"><p class="ds-cap mono">{_esc(name)}</p><div class="ds-group">{cells}</div></div>')
    body = (
        '<p class="ds-note">Commissioned engraved portraits (ADR-106) — code-drawn layered-SVG recipes, '
        "pre-rendered here to their checked-in PNG derivatives rather than re-executing the SVG recipe "
        "engine, so this preview has zero JS dependency.</p>" + "".join(rows)
    )
    (out_dir / "portraits.html").write_text(_page("components", "coach portraits", body), encoding="utf-8")


_CHARTS_JS_MODULE_SCRIPT = """
<script type="module">
  import {{ {imports} }} from "./js/charts.js";
  {calls}
</script>
"""


def _write_confidence_grammar(out_dir: Path) -> None:
    body = (
        '<div class="ds-block"><p class="ds-cap mono">Fan chart — projectionCone() (weight projection)</p><div id="cg-cone"></div></div>'
        '<div class="ds-block"><p class="ds-cap mono">CI whisker — ciWhisker() at high / medium / low confidence</p>'
        '<div id="cg-ciw-hi"></div><div id="cg-ciw-med"></div><div id="cg-ciw-low"></div></div>'
        '<div class="ds-block"><p class="ds-cap mono">Sample-size dots — nDots() at n=28 / n=12 / n=3</p>'
        '<p id="cg-dots-hi"></p><p id="cg-dots-med"></p><p id="cg-dots-low"></p></div>'
    )
    calls = (
        'document.getElementById("cg-cone").innerHTML = projectionCone('
        '{ w: 189.4, date: "2026-07-01" }, 175, -0.9, '
        '{ rateCiLow: -1.3, rateCiHigh: -0.5, goalDateRange: ["2026-09-10", "2026-11-02"], confidence: 0.7 });\n'
        '  document.getElementById("cg-ciw-hi").innerHTML = ciWhisker(-0.9, -1.1,'
        ' -0.7, { unit: " lb/wk", label: "weekly rate", confidence: 0.85 });\n'
        '  document.getElementById("cg-ciw-med").innerHTML = ciWhisker(-0.6,'
        ' -1.2, 0.0, { unit: " lb/wk", label: "weekly rate", confidence: 0.55 });\n'
        '  document.getElementById("cg-ciw-low").innerHTML = ciWhisker(0.1,'
        ' -0.9, 1.1, { unit: " lb/wk", label: "weekly rate", confidence: 0.2 });\n'
        '  document.getElementById("cg-dots-hi").innerHTML = nDots(28);\n'
        '  document.getElementById("cg-dots-med").innerHTML = nDots(12);\n'
        '  document.getElementById("cg-dots-low").innerHTML = nDots(3);'
    )
    extra_body = _CHARTS_JS_MODULE_SCRIPT.format(imports="projectionCone, ciWhisker, nDots", calls=calls)
    (out_dir / "confidence-grammar.html").write_text(
        _page("components", "the confidence grammar (fan / whisker / nDots)", body, extra_body=extra_body), encoding="utf-8"
    )


def _write_chart_gallery(out_dir: Path) -> None:
    body = (
        '<div class="ds-block"><p class="ds-cap mono">lineChart()</p><div id="cg-line"></div></div>'
        '<div class="ds-block"><p class="ds-cap mono">lineChart() — honest-sparse'
        ' state (&lt;4 points)</p><div id="cg-line-sparse"></div></div>'
        '<div class="ds-block"><p class="ds-cap mono">ring()</p><div id="cg-ring" style="width:120px;"></div></div>'
        '<div class="ds-block"><p class="ds-cap mono">barChart()</p><div id="cg-bar"></div></div>'
        '<div class="ds-block"><p class="ds-cap mono">stackedBar()</p><div id="cg-stack"></div></div>'
        '<div class="ds-block"><p class="ds-cap mono">heatStrip()</p><div id="cg-heat"></div></div>'
        '<div class="ds-block"><p class="ds-cap mono">sufficiencyBars()</p><div id="cg-suf"></div></div>'
    )
    calls = (
        "const days = Array.from({ length: 10 }, (_, i) => ({ date: `2026-07-${String(i + 1).padStart(2,'0')}`, "
        "value: 180 - i * 0.6 + (i % 3 ? 0.4 : -0.3) }));\n"
        '  document.getElementById("cg-line").innerHTML = lineChart(days,'
        ' { valueKey: "value", dateKey: "date", unit: " lb", label: "weight" });\n'
        '  document.getElementById("cg-line-sparse").innerHTML = lineChart(days.slice(0,'
        ' 2), { valueKey: "value", dateKey: "date", unit: " lb" });\n'
        '  document.getElementById("cg-ring").innerHTML = ring({ value: "72", sub: "recovery", label: "recovery score", fill: 0.72 });\n'
        '  document.getElementById("cg-bar").innerHTML = barChart(['
        '{ label: "Mon", value: 3 }, { label: "Tue", value: 5 }, { label: "Wed", value: 2 }, { label: "Thu", value: 6 }'
        "], {});\n"
        '  document.getElementById("cg-stack").innerHTML = stackedBar(['
        '{ label: "Protein", value: 140, tone: "ember" }, { label: "Carbs", value: 210, tone: "ink" }, '
        '{ label: "Fat", value: 70, tone: "ink" }], { unit: "g" });\n'
        '  document.getElementById("cg-heat").innerHTML = heatStrip(days.map((d)'
        " => ({ date: d.date, value: 6000 + Math.random() * 4000 })), "
        '{ valueKey: "value", unit: " steps" });\n'
        '  document.getElementById("cg-suf").innerHTML = sufficiencyBars(['
        '{ label: "Vitamin D", pct: 45, actual: 18, target: 40, unit: "mcg" }, '
        '{ label: "Iron", pct: 88, actual: 15.8, target: 18, unit: "mg" }, '
        '{ label: "B12", pct: 120, actual: 3.2, target: 2.4, unit: "mcg" }]);'
    )
    extra_body = _CHARTS_JS_MODULE_SCRIPT.format(imports="lineChart, ring, barChart, stackedBar, heatStrip, sufficiencyBars", calls=calls)
    (out_dir / "chart-gallery.html").write_text(
        _page("components", "chart gallery (charts.js)", body, extra_body=extra_body), encoding="utf-8"
    )


def _write_sigils_tier_emblems(out_dir: Path) -> None:
    body = (
        '<div class="ds-block"><p class="ds-cap mono">sigil() — 3 sample coaches</p>'
        '<div class="ds-group">'
        '<div class="ds-swatch" style="width:80px;--coach:#DD7A37;"><div class="sigil'
        ' sigil-lg" id="sg-1"></div><span class="ds-cap mono">elena_voss</span></div>'
        '<div class="ds-swatch" style="width:80px;--coach:#7B87C4;"><div class="sigil'
        ' sigil-lg" id="sg-2"></div><span class="ds-cap mono">marcus_webb</span></div>'
        '<div class="ds-swatch" style="width:80px;--coach:#4E9E7C;"><div class="sigil'
        ' sigil-lg" id="sg-3"></div><span class="ds-cap mono">sarah_chen</span></div>'
        "</div></div>"
        '<div class="ds-block"><p class="ds-cap mono">tierEmblem() — the 5 tiers</p><div class="ds-group">'
        + "".join(
            f'<div class="ds-swatch" style="width:140px;" data-tier="{t}"><div'
            f' style="color:var(--tier-accent);width:70px;" id="te-{t}"></div>'
            f'<span class="ds-cap mono">[data-tier="{t}"]</span></div>'
            for t in ["foundation", "momentum", "discipline", "mastery", "elite"]
        )
        + "</div></div>"
    )
    calls = (
        'document.getElementById("sg-1").innerHTML = sigil({ id: "elena_voss", name: "Dr. Elena Voss" });\n'
        '  document.getElementById("sg-2").innerHTML = sigil({ id: "marcus_webb", name: "Marcus Webb" });\n'
        '  document.getElementById("sg-3").innerHTML = sigil({ id: "sarah_chen", name: "Sarah Chen" });\n'
        + "\n  ".join(
            f'document.getElementById("te-{t}").innerHTML = tierEmblem("{t}", {lvl});'
            for t, lvl in [("foundation", 3), ("momentum", 11), ("discipline", 24), ("mastery", 38), ("elite", 47)]
        )
    )
    extra_body = f"""
<script type="module">
  import {{ sigil, tierEmblem }} from "./js/sigils.js";
  {calls}
</script>
"""
    (out_dir / "sigils-tier-emblems.html").write_text(
        _page("components", "coach sigils + tier emblems", body, extra_body=extra_body), encoding="utf-8"
    )


# ─────────────────────────────────────────────────────────────────────────────
# assets/ + component JS copies + reference/ page sanitizer
# ─────────────────────────────────────────────────────────────────────────────


def _replace_once(text: str, old: str, new: str, *, what: str) -> str:
    n = text.count(old)
    if n != 1:
        raise AssertionError(f"expected exactly 1 occurrence of {what!r} to rewrite, found {n}")
    return text.replace(old, new)


def _build_assets(repo_root: Path, out_dir: Path) -> None:
    css_src = repo_root / "site/assets/css"
    icons_src = repo_root / "site/assets/icons/icons.svg"
    fonts_src = repo_root / "site/assets/fonts/v4"

    (out_dir / "css").mkdir(parents=True, exist_ok=True)
    (out_dir / "fonts/v4").mkdir(parents=True, exist_ok=True)
    (out_dir / "icons").mkdir(parents=True, exist_ok=True)

    shutil.copyfile(css_src / "tokens.css", out_dir / "css/tokens.css")
    shutil.copyfile(icons_src, out_dir / "icons/icons.svg")

    # The brand mark is a foundation, so it travels with the bundle. tokens.css
    # points at these with a bundle-portable relative url(../marks/…), so no
    # rewrite is needed here — only the files themselves.
    (out_dir / "marks").mkdir(parents=True, exist_ok=True)
    marks_src = repo_root / "site/assets/marks"
    marks = sorted(marks_src.glob("mark-header-*.svg"))
    if not marks:
        raise AssertionError(f"no mark-header-*.svg found in {marks_src} — run scripts/build_brand_assets.py")
    for mark in marks:
        shutil.copyfile(mark, out_dir / "marks" / mark.name)

    # fonts.css references woff2 by absolute `/assets/fonts/v4/…` path on the live site;
    # rewrite to bundle-relative (fonts.css sits in assets/css/, the woff2s in assets/fonts/v4/).
    fonts_css = (css_src / "fonts.css").read_text(encoding="utf-8")
    rewritten = re.sub(r"url\(/assets/fonts/v4/([^)]+)\)", r"url(../fonts/v4/\1)", fonts_css)
    if rewritten == fonts_css:
        raise AssertionError("fonts.css rewrite matched nothing — /assets/fonts/v4/ url() pattern not found")
    (out_dir / "css/fonts.css").write_text(rewritten, encoding="utf-8")

    # Special case #3: fonts need base64 for binary upload to a design project.
    b64_manifest = {}
    for woff2 in sorted(fonts_src.glob("*.woff2")):
        shutil.copyfile(woff2, out_dir / "fonts/v4" / woff2.name)
        b64_manifest[woff2.name] = base64.b64encode(woff2.read_bytes()).decode("ascii")
    if len(b64_manifest) != 5:
        raise AssertionError(f"expected 5 self-hosted woff2 files, found {len(b64_manifest)}")
    (out_dir / "fonts_base64.json").write_text(json.dumps(b64_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _build_component_js(repo_root: Path, components_dir: Path) -> None:
    js_src = repo_root / "site/assets/js"
    js_out = components_dir / "js"
    js_out.mkdir(parents=True, exist_ok=True)

    shutil.copyfile(js_src / "svgtype.js", js_out / "svgtype.js")

    for fname in ("charts.js", "sigils.js"):
        text = (js_src / fname).read_text(encoding="utf-8")
        # Special case (see module docstring): the live file imports svgtype.js by ABSOLUTE
        # path on purpose (deploy/hash_site_assets.py's hasher needs it) — this bundle copy
        # rewrites to a relative import so it resolves from the bundle root instead.
        rewritten = _replace_once(text, 'import "/assets/js/svgtype.js";', 'import "./svgtype.js";', what=f"{fname} svgtype.js import")
        (js_out / fname).write_text(rewritten, encoding="utf-8")


def _build_portraits_assets(repo_root: Path, components_dir: Path) -> list[str]:
    portraits_src = repo_root / "site/assets/portraits"
    out = components_dir / "img/portraits"
    out.mkdir(parents=True, exist_ok=True)
    names = set()
    for png in sorted(portraits_src.glob("*.png")):
        shutil.copyfile(png, out / png.name)
        m = re.match(r"(.+)-(?:96|192)-(?:ondark|onlight)\.png$", png.name)
        if m:
            names.add(m.group(1))
    return sorted(names)


_LIVE_ROUTE_LINK_RE = re.compile(r'(href)="(/[^"#]*)"')
_ASSET_REF_RE = re.compile(r'(href|src)="(/assets/[^"]+)"')


def _neutralize_nav_links(html: str) -> str:
    """Rewrite an absolute-path nav href (`/coaching/`, `/data/`, …) to `href="#"` plus a
    slash-free `data-live-route` attribute carrying the original route as documentation
    only. Used both for reference/ page copies and for real generator output (e.g.
    v4_kit.loop_ribbon()) reused inside a components/ preview — production markup is
    absolute-path by design (it's meant to run on the live site), so anything built from a
    real generator needs this same neutralization before it's safe to ship in the bundle."""

    def _neutralize(m: re.Match) -> str:
        route = m.group(2).strip("/")
        return f'href="#" data-live-route="{_esc(route)}"'

    return _LIVE_ROUTE_LINK_RE.sub(_neutralize, html)


def _sanitize_reference_page(html: str, *, strip_scripts: list[str], strip_meta_containing: list[str]) -> str:
    """Rewrite a live built page into a bundle-portable reference copy.

    - `/assets/...` refs -> `../assets/...` (real, resolving rewrite — reference/ pages sit
      one level below the bundle root, same depth as foundations/ and components/).
    - any other absolute-path href (internal nav: /coaching/, /data/, /rss.xml, …) -> `#`,
      with the original route preserved as a slash-free `data-live-route` attribute (pure
      documentation, not a working link — these pages are a visual/structural snapshot, not
      a crawlable mirror).
    - whole `<script>`/`<meta>`/`<link>` elements that only exist to reference the live site
      (the SW-registration inline script, canonical/og:url/og:image meta, the manifest/
      favicon/RSS links, the page's own data-fetching module, motion.js) are removed, where
      present — which of these appear varies by page (e.g. the SW-registration script and
      the RSS <link> are only on some doors), so this is a best-effort strip, not an
      assert-must-find-one; the page-specific rewrites below (css links) stay hard asserts.
    """
    script_block_re = re.compile(r"<script\b.*?</script>", re.S)
    for needle in strip_scripts:
        blocks = script_block_re.findall(html)
        for b in blocks:
            if needle in b:
                html = html.replace(b, "<!-- omitted for the design-sync bundle: relies on a live fetch/asset -->", 1)

    for needle in strip_meta_containing:
        pattern = re.compile(r"<(?:meta|link)[^>]*" + re.escape(needle) + r"[^>]*>")
        html = pattern.sub("", html)

    html = _ASSET_REF_RE.sub(lambda m: f'{m.group(1)}="..{m.group(2)}"', html)
    return _neutralize_nav_links(html)


def _build_reference_pages(repo_root: Path, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "css").mkdir(parents=True, exist_ok=True)

    common_strip_scripts = ['serviceWorker.register("/sw.js")', "__moFail"]
    common_strip_meta = [
        'rel="canonical"',
        'property="og:url"',
        'property="og:image"',
        'rel="manifest"',
        'rel="apple-touch-icon"',
        'rel="icon" href="/favicon.ico"',
        'rel="alternate" type="application/rss+xml"',
    ]

    pages = [
        ("index.html", "home.html", "story.css", ['src="/assets/js/story.js"']),
        ("cockpit/index.html", "cockpit.html", "cockpit.css", ['src="/assets/js/cockpit.js"']),
        ("data/index.html", "data-hub.html", "evidence.css", ['src="/assets/js/evidence.js"']),
    ]
    for src_rel, out_name, door_css, extra_scripts in pages:
        src_path = repo_root / "site" / src_rel
        html = src_path.read_text(encoding="utf-8")
        html = _replace_once(html, "/assets/css/tokens.css", "../assets/css/tokens.css", what=f"{src_rel} tokens.css link")
        html = _replace_once(html, "/assets/css/fonts.css", "../assets/css/fonts.css", what=f"{src_rel} fonts.css link")
        html = _replace_once(html, f"/assets/css/{door_css}", f"css/{door_css}", what=f"{src_rel} {door_css} link")
        html = _sanitize_reference_page(
            html,
            strip_scripts=common_strip_scripts + ['src="/assets/js/motion.js"'] + extra_scripts,
            strip_meta_containing=common_strip_meta,
        )
        # #1467: reference cards carry the same first-line @dsCard contract as
        # foundations/ + components/, so they render in the Design System pane.
        html = f'<!-- @dsCard group="reference" -->\n<!-- design-sync reference snapshot of site/{src_rel} — see MANIFEST.md -->\n' + html
        (out_dir / out_name).write_text(html, encoding="utf-8")
        shutil.copyfile(repo_root / "site/assets/css" / door_css, out_dir / "css" / door_css)


# ─────────────────────────────────────────────────────────────────────────────
# self-verification — the guarantee behind "grep the bundle, get zero"
# ─────────────────────────────────────────────────────────────────────────────

_ABS_REF_RE = re.compile(r'(?:href|src)="/[^"]')
_URL_ABS_RE = re.compile(r"url\(/[^)]")
_SITE_URL_RE = re.compile(r"https://averagejoematt")
_DSCARD_RE = re.compile(r'^<!-- @dsCard group="[^"]+" -->')


_XML_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)


def _verify_bundle(bundle_dir: Path) -> None:
    violations = []
    for path in sorted(bundle_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix not in (".html", ".css", ".js", ".json", ".md", ".svg"):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if path.suffix == ".svg":
            # icons.svg is copied byte-verbatim from site truth (design fidelity — a Claude
            # Design session should see the real file, authorial comments included), and its
            # own file-header comment documents how CONSUMING code references the sprite
            # (`<use href="/assets/icons/icons.svg#i-NAME"/>`) — that's prose about usage
            # elsewhere, not a resolvable reference inside icons.svg itself, so it's excluded
            # from this check the same way MANIFEST.md's prose about the check is.
            text = _XML_COMMENT_RE.sub("", text)
        if _ABS_REF_RE.search(text):
            violations.append(f"{path}: absolute href/src ref")
        if _URL_ABS_RE.search(text):
            violations.append(f"{path}: absolute url(...) ref")
        if _SITE_URL_RE.search(text):
            violations.append(f"{path}: literal https://averagejoematt reference")

    for sub in ("foundations", "components", "reference"):
        d = bundle_dir / sub
        if not d.is_dir():
            continue
        for html_path in sorted(d.glob("*.html")):
            first_line = html_path.read_text(encoding="utf-8").split("\n", 1)[0]
            if not _DSCARD_RE.match(first_line):
                violations.append(f"{html_path}: missing first-line @dsCard marker (got {first_line!r})")

    if violations:
        raise AssertionError("design_sync_bundle self-verification FAILED:\n  " + "\n  ".join(violations))


# ─────────────────────────────────────────────────────────────────────────────
# manifest + orchestration
# ─────────────────────────────────────────────────────────────────────────────

_MANIFEST_TEMPLATE = """# Design sync bundle — v5 "Coherence"

Generated by `scripts/design_sync_bundle.py` from repo HEAD. Re-run the script any time
tokens.css / icons.svg / the shared JS kit changes — this file and everything under
`assets/`, `foundations/`, `components/`, `reference/` is fully regenerated (not merged),
so a stale bundle never lingers on disk.

## Contents

- `assets/` — tokens.css, fonts.css (paths rewritten bundle-relative), the 5 self-hosted
  woff2 files + `fonts_base64.json` (base64 manifest for binary upload), icons.svg
  ({icon_count} symbols).
- `foundations/` — palette (dark + light), type triad, spacing/radii, pillar identity
  colors, the {bp_count} canonical breakpoints. Every value is parsed live out of
  tokens.css — nothing here is hand-copied.
- `components/` — the shared kit with sample data (`.page-hero`+`.loop-ribbon`, `.prose`,
  `.provenance`, `.tabset`, the `.loop` diagram, the `.rd-*` readout family, `.cb-*` cards,
  the confidence grammar, coach sigils + tier emblems, coach portraits, the icon sheet, a
  `charts.js` gallery). `components/js/` carries the two JS modules the JS-rendered
  previews need (`charts.js`, `sigils.js`, `svgtype.js`); `components/img/portraits/`
  carries the checked-in portrait PNGs.
- `reference/` — {ref_count} representative BUILT page shells (home, cockpit, the data
  hub), each sanitized to resolve entirely from the bundle (see "Special cases" below).
  The LIVE layer — `reference/captures/*.png` full-page screenshots of the current site
  (the doors + a data-dense surface), one `@dsCard` card per capture, plus a
  `captures_base64.json` upload manifest — is refreshed on every sync by the companion
  `scripts/design_sync_capture.py` (#1467), so what a design session sees is today's
  real pages, never a checked-in stale artifact.

## Special cases (from the #1462 issue's evidence inventory)

1. **motion.js is the one IIFE** in an otherwise all-ES-module JS layer. It's OMITTED from
   every preview and reference page: motion.js only ever adds a reveal transition on top of
   content that already painted (fail-open by design, DESIGN_SYSTEM_V5.md §7 — "Motion can
   never hide content"), so leaving it out changes nothing about what a design session sees.
2. **Breakpoints are parsed from the tokens.css COMMENT block**, not `:root` — `@media`
   can't read a CSS custom property, so tokens.css documents the 6 canonical breakpoints as
   a named-constants table in a comment instead. `foundations/breakpoints.html` is built by
   a dedicated regex over that block, not the `:root`-var parser every other foundation uses.
3. **Fonts are binary** — `assets/fonts_base64.json` carries a `{{filename: base64}}`
   manifest of all 5 woff2 files alongside the raw copies in `assets/fonts/v4/`, so a
   design-project upload surface that wants base64 (rather than a fetchable URL) has what
   it needs without re-deriving anything.
4. **charts.js / sigils.js import svgtype.js by an intentionally ABSOLUTE path** on the live
   site (`/assets/js/svgtype.js` — required by `deploy/hash_site_assets.py`'s asset-hashing
   graph walk; a relative import escapes its regex). The bundle copies under `components/js/`
   rewrite that one line to a relative `./svgtype.js` so they resolve from the bundle root;
   the live source files in `site/assets/js/` are untouched.

## Previewing

Several component previews (`confidence-grammar.html`, `chart-gallery.html`,
`sigils-tier-emblems.html`) use real `<script type="module">` imports of the copied JS —
**serve the bundle over HTTP** (e.g. `python3 -m http.server` from the bundle root) rather
than opening files via `file://`: ES module imports are CORS-blocked under `file://` in
Chromium-based browsers, and SVG-sprite `<use href="…icons.svg#…">` refs (`icon-sheet.html`)
have the same restriction. Every reference is bundle-relative either way — only the
transport (served vs. double-clicked) changes what a browser will fetch.

## Verification

The builder self-verifies on every run (`_verify_bundle`): it fails loudly if any `.html`/
`.css`/`.js`/`.json`/`.md` file under the bundle contains an absolute `href`/`src`/`url(...)`
reference, a literal absolute reference to the live production domain, or a
`foundations/`/`components/`/`reference/` card missing its first-line `@dsCard` marker
(#1467). A green run of this script IS the "zero absolute refs" proof; the capture script
re-runs the same sweep after it adds the live layer.
"""


def build(repo_root: Path, out: Path) -> None:
    tokens_css = (repo_root / "site/assets/css/tokens.css").read_text(encoding="utf-8")
    icons_svg = (repo_root / "site/assets/icons/icons.svg").read_text(encoding="utf-8")

    dark_palette = _parse_vars(_section(tokens_css, "1. Palette"))
    light_palette = _parse_light_palette(tokens_css)
    typography = _parse_vars(_section(tokens_css, "2. Typography"))
    spacing = _parse_vars(_section(tokens_css, "3. Spacing"))
    radii = _parse_vars(_section(tokens_css, "7. Radii"))
    pillars = _parse_pillar_colors(tokens_css)
    breakpoints = _parse_breakpoints(tokens_css)
    icon_ids = _parse_icon_ids(icons_svg)

    if out.exists():
        shutil.rmtree(out)
    (out / "foundations").mkdir(parents=True)
    (out / "components").mkdir(parents=True)
    (out / "reference").mkdir(parents=True)

    _build_assets(repo_root, out / "assets")

    _write_palette(out / "foundations", "palette-dark", "Palette — dark", "dark", dark_palette)
    _write_palette(out / "foundations", "palette-light", "Palette — light", "light", light_palette)
    _write_type_triad(out / "foundations", typography)
    _write_spacing_radii(out / "foundations", spacing, radii)
    _write_pillar_colors(out / "foundations", pillars)
    _write_breakpoints(out / "foundations", breakpoints)

    _build_component_js(repo_root, out / "components")
    portrait_names = _build_portraits_assets(repo_root, out / "components")

    _write_page_hero(out / "components")
    _write_prose(out / "components")
    _write_provenance(out / "components")
    _write_tabset(out / "components")
    _write_loop_diagram(out / "components")
    _write_readout(out / "components")
    _write_cb_cards(out / "components")
    _write_confidence_grammar(out / "components")
    _write_sigils_tier_emblems(out / "components")
    _write_portraits(out / "components", portrait_names)
    _write_icon_sheet(out / "components", icon_ids)
    _write_chart_gallery(out / "components")

    _build_reference_pages(repo_root, out / "reference")

    manifest = _MANIFEST_TEMPLATE.format(icon_count=len(icon_ids), bp_count=len(breakpoints), ref_count=3)
    (out / "MANIFEST.md").write_text(manifest, encoding="utf-8")

    _verify_bundle(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default="scratch/design_sync_bundle", help="output directory (repo-root-relative unless absolute)")
    parser.add_argument("--repo-root", default=str(REPO_ROOT_DEFAULT), help="repo root (default: this script's parent dir)")
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    out = Path(args.out)
    if not out.is_absolute():
        out = repo_root / out

    build(repo_root, out)
    print(f"design_sync_bundle: wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
