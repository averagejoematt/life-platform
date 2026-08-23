#!/usr/bin/env python3
"""v4_build_mirror.py — generate /method/mirror/ (#1392): The Mirror.

A reader drops the CSV export Whoop already gives them, and their months get
scored IN THE BROWSER by the same deterministic instruments that score Matthew
every night — then laid over his published distributions ("your HRV sits at his
62nd percentile"). The privacy property is architectural, not policy: there is
no upload endpoint on this site, so the promise "your file never leaves this
page" has nothing to depend on but the absence of code — which
tests/test_mirror_parity.py enforces structurally (exactly one fetch, of the
static distributions artifact; no XHR/beacon/WebSocket/EventSource).

Deploy-race-safe like grade-your-coach (#1396): the page reads only STATIC
committed artifacts —
  * /data/mirror_distributions.json  (scripts/gen_mirror_distributions.py —
    full sorted daily samples of six already-public metrics + window + n)
  * the module graph /assets/js/mirror.js → mirror-core.js / mirror_demo.js —
    mirror-core is pinned to the deployed Python by tests/vectors/mirror_vectors.json.

Run from repo root:  python3 scripts/v4_build_mirror.py
"""

from __future__ import annotations

import html
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from v4_chrome import doors_nav, site_footer  # noqa: E402
from v4_kit import loop_ribbon  # noqa: E402

SLUG = "mirror"
CANONICAL = f"/method/{SLUG}/"
TITLE = "The Mirror — your wearable export on my instruments — averagejoematt"
DESCRIPTION = (
    "Drop your Whoop CSV export and get scored by the same deterministic instruments that "
    "score me every night — readiness, sleep, recovery — then see your numbers laid over my "
    "published distributions. Your file never leaves your browser: there is no upload endpoint on this site."
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
CLIENT_JS = '<script type="module" src="/assets/js/mirror.js"></script>'


def topbar() -> str:
    return (
        '<header class="ev-top"><a class="brand" href="/"><span class="brand-mark" aria-hidden="true"></span>'
        '<span class="brand-name">averagejoematt</span> <span class="brand-door label">method</span></a>'
        f'{doors_nav("/data/", with_follow=False)}</header>'
    )


STYLE = """
<style>
.mr-wrap { max-width: var(--container); margin-inline: auto; padding: 0 var(--gutter) var(--sp-9); }
.mr-cols { display: grid; gap: var(--sp-5); margin-top: var(--sp-5); min-width: 0; align-items: start; }
@media (min-width: 901px) { .mr-cols { grid-template-columns: minmax(0, 4fr) minmax(0, 6fr); } }
.mr-pane { border: var(--border-hair); border-radius: var(--radius); padding: var(--sp-5); background: var(--surface-raised); min-width: 0; }
.mr-pane h2 { margin: 0 0 var(--sp-3); font-family: var(--font-serif); font-size: var(--fs-h3); color: var(--ink); }
/* The calibrated-on-him banner: permanent, above every readout — never dismissible. */
.mr-banner { margin-top: var(--sp-4); border: var(--border-hair); border-left: 3px solid var(--accent, var(--ink)); border-radius: var(--radius);
  padding: var(--sp-3) var(--sp-4); background: var(--surface-raised); color: var(--ink-muted); line-height: var(--lh-relaxed); }
/* display:block is load-bearing: a <label> computes display:inline, whose vertical
   padding takes no layout space — the padded box overpaints the paragraph above it
   and fragments across line boxes on mobile (render-QA FAIL-1). */
.mr-drop { display: block; border: 1.5px dashed var(--rule); border-radius: var(--radius); padding: var(--sp-5); text-align: center;
  background: var(--surface-sunken); color: var(--ink-muted); line-height: var(--lh-relaxed); cursor: pointer; }
.mr-drop-hot { border-color: var(--accent, var(--ink)); color: var(--ink); }
.mr-drop input { display: none; }
.mr-btns { display: flex; flex-wrap: wrap; gap: var(--sp-2); margin-top: var(--sp-3); }
.mr-btn { font-family: var(--font-mono); font-size: var(--fs-label); text-transform: uppercase; letter-spacing: var(--tracking-label);
  padding: var(--sp-2) var(--sp-3); border: var(--border-hair); border-radius: var(--radius); background: transparent; color: var(--ink-muted); cursor: pointer; }
.mr-btn:hover, .mr-btn:focus-visible { color: var(--ink); border-color: var(--ink-muted); }
.mr-prov { margin-top: var(--sp-3); font-family: var(--font-mono); font-size: var(--fs-small); color: var(--ink-faint); line-height: var(--lh-relaxed);
  overflow-wrap: anywhere; }
.mr-empty { color: var(--ink-muted); line-height: var(--lh-relaxed); }
.mr-latest-h { margin: 0; font-family: var(--font-mono); font-size: var(--fs-label); text-transform: uppercase; letter-spacing: var(--tracking-label); color: var(--ink-faint); }
.mr-headline { display: flex; align-items: baseline; gap: var(--sp-3); margin-top: var(--sp-2); flex-wrap: wrap; }
.mr-score { font-family: var(--font-mono); font-size: var(--fs-h1); color: var(--ink); }
.mr-headline-l { color: var(--ink-muted); }
.mr-chip { font-family: var(--font-mono); font-size: var(--fs-label); text-transform: uppercase; letter-spacing: var(--tracking-label);
  border: var(--border-hair); border-radius: var(--radius); padding: 2px var(--sp-2); color: var(--ink-muted); }
.mr-chip-green { border-color: var(--good, currentColor); }
.mr-chip-yellow { border-color: var(--warn, currentColor); }
.mr-chip-red { border-color: var(--bad, currentColor); }
.mr-figs, .mr-pillars { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--sp-4); margin-top: var(--sp-4); }
@media (min-width: 601px) { .mr-figs, .mr-pillars { grid-template-columns: repeat(4, minmax(0, 1fr)); } }
.mr-fig { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.mr-fig-v { font-family: var(--font-mono); font-size: var(--fs-h3); color: var(--ink); }
.mr-fig-u { font-size: var(--fs-small); color: var(--ink-muted); }
.mr-fig-l { color: var(--ink-faint); font-size: var(--fs-small); min-height: 2.6em; min-height: 2lh; }
.mr-sub { margin: var(--sp-3) 0 0; font-size: var(--fs-small); color: var(--ink-muted); line-height: var(--lh-relaxed); }
.mr-bands-sec { margin-top: var(--sp-6); }
.mr-legend { font-family: var(--font-mono); font-size: var(--fs-small); color: var(--ink-muted); margin-bottom: var(--sp-3); }
.mr-you-dot { display: inline-block; width: 10px; height: 10px; border-radius: 50%; background: var(--accent, var(--ink));
  border: 2px solid var(--surface-raised); vertical-align: baseline; }
.mr-band-key { display: inline-block; width: 22px; height: 10px; border-radius: 4px; background: var(--surface-sunken); border: var(--border-hair); vertical-align: baseline; }
.mr-median-key { display: inline-block; width: 2px; height: 12px; background: var(--ink-muted); vertical-align: text-bottom; }
.mr-row { margin-top: var(--sp-4); min-width: 0; }
.mr-row-h { display: flex; justify-content: space-between; gap: var(--sp-3); flex-wrap: wrap; align-items: baseline; }
.mr-metric { font-family: var(--font-mono); font-size: var(--fs-label); text-transform: uppercase; letter-spacing: var(--tracking-label); color: var(--ink); }
.mr-row-note { color: var(--ink-muted); font-size: var(--fs-small); }
.mr-row-sub { margin: 2px 0 0; color: var(--ink-faint); font-size: var(--fs-small); }
.mr-svg { width: 100%; height: auto; display: block; margin-top: var(--sp-1); }
.mr-band { fill: var(--surface-sunken); stroke: var(--rule); stroke-width: 1; }
.mr-band-inner { fill: var(--rule); stroke: var(--surface-raised); stroke-width: 2; }
.mr-median { stroke: var(--ink-muted); stroke-width: 2; }
.mr-you { fill: var(--accent, var(--ink)); stroke: var(--surface-raised); stroke-width: 2; }
.mr-note { margin-top: var(--sp-4); font-size: var(--fs-small); color: var(--ink-muted); line-height: var(--lh-relaxed); }
</style>
"""


def render_page() -> str:
    return f"""<!DOCTYPE html>
<html lang="en" data-door="method">
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
  <a class="skip" href="#mirror">Skip to the tool</a>
  {topbar()}
  <main id="mirror">
    <div class="page-hero">
      <p class="ph-kicker label">the method &middot; the open artifact</p>
      <h1 class="ph-title">The Mirror</h1>
      <p class="ph-promise">Every number on this site is me. This page is the one place it gets to be you: drop the CSV export Whoop already lets you download, and your months are scored by the <em>same</em> deterministic instruments that score me every night &mdash; then laid over my published distributions. Your file never leaves this page. There is no server on this site that could receive it.</p>
      {loop_ribbon("method")}
    </div>
    <div class="mr-wrap">
      <p class="mr-banner"><strong>One person&rsquo;s model, applied to another.</strong> These instruments are calibrated on me &mdash; my thresholds, my variance, my device. Where your own export runs deep enough (30+ days), the thresholds re-derive from <em>your</em> distribution, exactly as mine do; where it doesn&rsquo;t, the fallback is labelled. Read the output as a lens, not a verdict.</p>
      <div class="mr-cols">
        <section class="mr-pane">
          <h2>Drop the export</h2>
          <p class="rd-prose">In the Whoop app: <strong>More &rarr; App Settings &rarr; Data Export</strong>. Whoop emails you a zip &mdash; unzip it and drop <code>physiological_cycles.csv</code> here (add <code>sleeps.csv</code> too if you like). CSV only, straight from Whoop; no account, no email, no upload.</p>
          <label class="mr-drop" id="mirror-drop" for="mirror-file">Drop the CSV here &mdash; or click to pick a file<input type="file" id="mirror-file" accept=".csv" multiple></label>
          <div class="mr-btns">
            <button type="button" class="mr-btn" id="mirror-demo">Load the synthetic example</button>
            <button type="button" class="mr-btn" id="mirror-clear">Clear my data</button>
          </div>
          <p class="mr-prov" id="mirror-prov"></p>
          <p class="mr-prov" id="mirror-privacy"><strong>Nothing is uploaded.</strong> Parsing and scoring run entirely in this page. The only network request this tool makes is a GET of my published distribution file &mdash; data flows from me to you, never back. What you drop persists only in this browser&rsquo;s localStorage until you press <em>clear my data</em>.</p>
        </section>
        <section class="mr-pane">
          <h2>The readout</h2>
          <div id="mirror-readout"></div>
        </section>
      </div>

      <section class="rd-sec mr-bands-sec">
        <h2 class="rd-h">You, on my distributions</h2>
        <div id="mirror-bands"></div>
      </section>

      <section class="rd-sec">
        <h2 class="rd-h">No export handy? Type a number</h2>
        <p class="rd-prose">The lighter rung of the same ladder: type today&rsquo;s number off your watch face and see where it lands in my last year &mdash; one value per day, exact midrank percentile, computed here. (This replaces the old three-field mirror widget, which compared against a 7-day window; this one uses the full published year.)</p>
        <div id="mirror-quick"></div>
      </section>

      <section class="rd-sec">
        <h2 class="rd-h">What the numbers mean</h2>
        <p class="rd-prose"><strong>Readiness</strong> is the platform&rsquo;s composite: recovery &times;0.40, sleep &times;0.25, HRV trend &times;0.20, training-load balance &times;0.10 &mdash; renormalised over what your export actually contains. A Whoop export carries no external training-load series, so that component is <em>absent</em> here, not zero, and the page says so (ADR-104: absence is reported, never faked).</p>
        <p class="rd-prose"><strong>The HRV trend</strong> maps your 7-day/30-day RMSSD ratio through percentile anchors. Past 30 days of history the anchors come from <em>your own</em> ratio distribution &mdash; the same personal-variance machinery (and the same 30-observation floor-guard) my thresholds run under (ADR-105). Below the floor it uses the population fallback and is labelled as such.</p>
        <p class="rd-prose"><strong>The overlay</strong> places your 30-day median inside my last year, one value per day, as an exact midrank percentile &mdash; computed in this page from the full published sample, not interpolated from summary statistics. HRV here is Whoop&rsquo;s RMSSD in milliseconds against the same measure from my device; an Apple Health export reports SDNN, a different quantity, which is why this v1 is Whoop-only rather than quietly comparing incomparables.</p>
      </section>

      <section class="rd-sec">
        <h2 class="rd-h">The same instruments, provably</h2>
        <p class="rd-prose">The scoring on this page is not &ldquo;like&rdquo; the platform&rsquo;s &mdash; it is a port of the deployed Python, pinned by a shared test-vector suite generated <em>from</em> those modules (<code>tests/vectors/mirror_vectors.json</code>), which both sides must reproduce exactly, to the last banker&rsquo;s-rounded digit. The privacy promise is enforced the same way: a repo test pins this page&rsquo;s code to exactly one network request &mdash; the static distributions file &mdash; and to zero upload mechanisms. The repo is public; check the page rather than trust it.</p>
      </section>

      <p class="correlative">Generated by <code>scripts/v4_build_mirror.py</code>. Scoring: <code>/assets/js/mirror-core.js</code>, pinned to the deployed engine by <code>tests/test_mirror_parity.py</code>. <span class="confidence conf-low">client-side &middot; nothing uploaded</span></p>
    </div>
  </main>
  {site_footer(current_door="/data/")}
  {MOTION_SCRIPT}
  {CLIENT_JS}
</body>
</html>
"""


def main() -> int:
    out_dir = ROOT / "site" / "method" / SLUG
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "index.html").write_text(render_page(), encoding="utf-8")
    dist = ROOT / "site" / "data" / "mirror_distributions.json"
    if not dist.exists():
        print("WARNING: site/data/mirror_distributions.json is missing — run scripts/gen_mirror_distributions.py", file=sys.stderr)
    print(f"{CANONICAL}: written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
