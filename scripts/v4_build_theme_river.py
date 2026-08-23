#!/usr/bin/env python3
"""v4_build_theme_river.py — generate /story/theme-river/ + site/data/theme_river.json (#1381).

The Theme River (epic #1364): the journal enrichment pass codes up to four
`enriched_themes` per entry; this exhibit renders their EVOLUTION across the
attempt as monochrome small-multiples — one micro column-sparkline per theme,
neutral ink carrying the shape, the ember accent reserved for the single RISING
theme (earned glow — "this is alive / up"). A fading theme is just neutral ink,
never red.

Two outputs, both DEPLOY-RACE-SAFE (no site-api /api endpoint — the page reads a
STATIC generated JSON, exactly like /method/eyeball reads /data/eyeball_calibration.json):
  * site/data/theme_river.json — the aggregation artifact. Built from the notion
    journal partition if AWS creds are present (--live), else the honest empty
    (n=0) artifact — the committed baseline the page always has something to
    render. A refresh (rerun --live, or a future lambda) overwrites the S3 object
    as the attempt accrues enriched entries.
  * site/story/theme-river/index.html — a standalone static page that fetches that
    JSON at runtime and renders the small-multiples, degrading to the honest
    empty / warming-up copy the artifact itself declares (AC4).

The aggregation is deterministic and unit-tested (tests/test_theme_river_1381.py);
no AI runs at render time.

Run from repo root:  python3 scripts/v4_build_theme_river.py            (writes the empty-state artifact)
                     python3 scripts/v4_build_theme_river.py --live      (reads the live journal partition)
"""

from __future__ import annotations

import html
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lambdas"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from content import theme_river as tr  # noqa: E402
from v4_chrome import doors_nav, site_footer  # noqa: E402
from v4_kit import loop_ribbon  # noqa: E402

try:
    from common import constants as _constants  # noqa: E402

    EXPERIMENT_START = _constants.EXPERIMENT_START_DATE
except Exception:  # pragma: no cover — constants always import in-repo
    EXPERIMENT_START = "2026-07-22"

SLUG = "theme-river"
CANONICAL = f"/story/{SLUG}/"
DATA_URL = "/data/theme_river.json"
TITLE = "The Theme River — what the journal has been about — The Story — averagejoematt"
DESCRIPTION = (
    "The journal enrichment codes the themes of each day's writing. Here they are across the attempt — "
    "a monochrome river of what the entries keep returning to. Read from prose by a model, never entered as data."
)


def esc(s) -> str:
    return html.escape(str(s), quote=True)


FONTS = (
    '<link rel="preload" href="/assets/fonts/v4/pxiTypc9vsFDm051Uf6KVwgkfoSxQ0GsQv8ToedPibnr0SZe1ZuWi3g.woff2" as="font" type="font/woff2" crossorigin>'
    '<link rel="preload" href="/assets/fonts/v4/6NU58FyLNQOQZAnv9ZwNjucMHVn85Ni7emAe9lKqZTnbB-gzTK0K1ChjeveQ7ZXk8g.woff2" as="font" type="font/woff2" crossorigin>'
    '<link rel="preload" href="/assets/fonts/v4/-F63fjptAgt5VM-kVkqdyU8n1i8q131nj-o.woff2" as="font" type="font/woff2" crossorigin>'
    '<link rel="stylesheet" href="/assets/css/fonts.css">'
)
# #3048: extracted to a real asset so the site CSP can drop 'unsafe-inline' for
# scripts — synchronous head script, so theme still applies before first paint.
THEME = '<script src="/assets/js/boot_theme.js"></script>'
MOTION_HEAD = '<script src="/assets/js/boot_motion.js"></script>'
MOTION_SCRIPT = '<script src="/assets/js/motion.js" defer></script>'


def topbar() -> str:
    return (
        '<header class="ev-top"><a class="brand" href="/"><span class="brand-mark" aria-hidden="true"></span>'
        '<span class="brand-name">averagejoematt</span> <span class="brand-door label">story</span></a>'
        f'{doors_nav("/story/", with_follow=False)}</header>'
    )


FOOTER = site_footer(current_door="/story/")

STYLE = """
<style>
.tr-wrap { max-width: var(--container); margin-inline: auto; padding: 0 var(--gutter) var(--sp-9); }
.tr-state { margin-top: var(--sp-5); border: var(--border-hair); border-radius: var(--radius); padding: var(--sp-6); background: var(--surface-raised); }
.tr-empty { color: var(--ink-muted); line-height: var(--lh-relaxed); }
.tr-banner { margin-top: var(--sp-5); border: var(--border-hair); border-left: 2px solid var(--ink-faint); border-radius: var(--radius);
  padding: var(--sp-4) var(--sp-5); background: var(--surface-raised); color: var(--ink-muted); line-height: var(--lh-relaxed); }
.tr-meta { font-family: var(--font-mono); font-size: var(--fs-small); color: var(--ink-faint); margin: var(--sp-5) 0 0; }
.tr-grid { display: grid; gap: var(--sp-4); margin-top: var(--sp-4); min-width: 0; grid-template-columns: 1fr; }
@media (min-width: 601px) { .tr-grid { grid-template-columns: repeat(2, 1fr); } }
@media (min-width: 901px) { .tr-grid { grid-template-columns: repeat(3, 1fr); } }
.tr-card { border: var(--border-hair); border-radius: var(--radius); padding: var(--sp-5); background: var(--surface-raised); min-width: 0; }
.tr-card--glow { border-color: var(--ember); box-shadow: inset 0 0 0 1px var(--ember-wash); }
.tr-card h3 { margin: 0; font-family: var(--font-serif); font-size: var(--fs-h3); color: var(--ink); text-transform: capitalize; overflow-wrap: anywhere; }
.tr-rank { font-family: var(--font-mono); font-size: var(--fs-label); text-transform: uppercase; letter-spacing: var(--tracking-label); color: var(--ink-faint); }
.tr-total { font-family: var(--font-mono); font-size: var(--fs-small); color: var(--ink-muted); margin: var(--sp-1) 0 var(--sp-3); }
.tr-rising-tag { color: var(--ember); }
.tr-spark { width: 100%; height: 54px; display: block; overflow: visible; }
.tr-bar { fill: var(--ink-muted); }
.tr-bar--z { fill: var(--surface-sunken); }
.tr-card--glow .tr-bar { fill: var(--ember); }
.tr-axis { stroke: var(--ink-faint); stroke-width: 1; }
.tr-wk { font-family: var(--font-mono); font-size: var(--fs-small); color: var(--ink-faint); margin-top: var(--sp-2); }
.tr-disclaimer { margin-top: var(--sp-6); color: var(--ink-muted); line-height: var(--lh-relaxed); }
</style>
"""

# The client renderer: fetch the static artifact, render honest empty / warming-up /
# flowing states. Pure vanilla JS, no deps (the v4 no-framework rule). Because the
# artifact self-declares its state and n, the page never fabricates a river on thin
# data. Small-multiples: one monochrome column-sparkline per theme, shared y-scale;
# the single rising theme (from the artifact) gets the ember accent.
# #3048: the renderer moved verbatim to a real asset (/assets/js/theme_river_readout.js)
# so the site CSP can drop 'unsafe-inline' for scripts. The artifact URL is
# baked inside the asset; keep it in sync with DATA_URL above.
CLIENT_JS = '<script src="/assets/js/theme_river_readout.js"></script>'


def render_page() -> str:
    return f"""<!DOCTYPE html>
<html lang="en" data-door="story">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
  <title>{esc(TITLE)}</title>
  <meta name="description" content="{esc(DESCRIPTION)}">
  <link rel="canonical" href="https://averagejoematt.com{CANONICAL}">
  <meta property="og:type" content="website">
  <meta property="og:site_name" content="averagejoematt">
  <meta property="og:url" content="https://averagejoematt.com{CANONICAL}">
  <meta property="og:title" content="{esc(TITLE)}">
  <meta property="og:description" content="{esc(DESCRIPTION)}">
  <meta property="og:image" content="https://averagejoematt.com/assets/images/og-home.png">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="{esc(TITLE)}">
  <meta name="twitter:description" content="{esc(DESCRIPTION)}">
  <link rel="icon" href="/favicon.ico">
  {FONTS}
  <link rel="stylesheet" href="/assets/css/tokens.css">
  <link rel="stylesheet" href="/assets/css/evidence.css">
  {STYLE}
  {THEME}
  {MOTION_HEAD}
</head>
<body>
  <a class="skip" href="#tr">Skip to the content</a>
  {topbar()}
  <main id="tr">
    <div class="page-hero">
      <p class="ph-kicker label">the story &middot; the writing, aggregated</p>
      <h1 class="ph-title">The Theme River</h1>
      <p class="ph-promise">Every enriched journal entry is coded with the life-themes it touches — work pressure, personal growth, family, health, the recurring weather of a life. This is those themes across the attempt: a monochrome river of what the writing keeps returning to. The themes are <strong>read from the prose by a model</strong>, never entered as data (ADR-104); below the threshold no dominant theme is claimed at all.</p>
      {loop_ribbon("story")}
    </div>
    <div class="tr-wrap">
      <section class="rd-sec" style="margin-top:0">
        <h2 class="rd-h">The river, theme by theme</h2>
        <p class="rd-prose">Each panel is one theme; its bars are the weekly count of entries that touched it, on a shared scale so the panels are comparable. Neutral ink carries the shape — a theme that fades just gets shorter, never red. The one theme rising fastest this week earns the ember accent. Everything here is computed deterministically from the enriched entries; no model runs when the page loads.</p>
        <div id="tr-readout"></div>
      </section>
      <p class="tr-disclaimer">The counts are of theme <em>labels</em> only — the private one-line summaries and the raw entries never leave the database (J-8). A theme is a language model's reading of what a day's writing was about; treat it as prose-coding, not measurement.</p>
      <p class="correlative">Generated by <code>scripts/v4_build_theme_river.py</code> from <code>lambdas/theme_river.py</code>. The chart reads a static artifact at <code>{esc(DATA_URL)}</code>. <span class="confidence conf-low">prose-coded, not asserted</span></p>
    </div>
  </main>
  {FOOTER}
  {MOTION_SCRIPT}
  {CLIENT_JS}
</body>
</html>
"""


def build_artifact(live: bool) -> dict:
    """The theme-river artifact. --live reads the notion journal partition over the
    attempt window; otherwise the honest empty (n=0) baseline.

    Clamps end = max(start, today) (#1823) — a pre-genesis run (today <
    EXPERIMENT_START, e.g. the countdown window ahead of a reset's genesis date)
    would otherwise emit an inverted window (end before start), which
    tr.build_river()/list_enriched_entries() were never designed to see.
    """
    today = date.today().isoformat()
    start = EXPERIMENT_START
    end = max(start, today)
    entries: list[dict] = []
    model = None
    schema_version = None
    if live:
        import boto3

        table = boto3.resource("dynamodb", region_name="us-west-2").Table("life-platform")
        entries = tr.list_enriched_entries(table, start, end)
        model, schema_version = tr.latest_provenance(table)
    return tr.build_river(entries, start, end, model=model, schema_version=schema_version)


def main() -> int:
    live = "--live" in sys.argv[1:]
    artifact = build_artifact(live)

    data_path = ROOT / "site" / "data" / "theme_river.json"
    data_path.parent.mkdir(parents=True, exist_ok=True)
    data_path.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    out_dir = ROOT / "site" / "story" / SLUG
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "index.html").write_text(render_page(), encoding="utf-8")

    print(f"{CANONICAL}: state={artifact['state']} n_days={artifact['n_days']} n_themes={artifact['n_themes']} (live={live})")
    print(f"{DATA_URL}: {data_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
