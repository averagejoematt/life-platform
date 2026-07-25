#!/usr/bin/env python3
"""v4_build_eyeball.py — generate /method/eyeball/ + site/data/eyeball_calibration.json (#1390).

The eyeball-calibration exhibit: "how wrong is the AI at eyeballing food?" A meal photo goes
to Haiku vision, which estimates macros; the estimate is graded against the day's logged
MacroFactor truth; the accumulated grades become a public reliability chart (error distribution,
n, trend) with honest zero/low-n states (AC#3, ADR-104/105).

Two outputs, both DEPLOY-RACE-SAFE (no site-api /api endpoint — the page reads a STATIC generated
JSON, exactly like /method/data reads /data/data_sources.json):
  * site/data/eyeball_calibration.json — the reliability artifact. Built from graded DDB records
    if AWS creds are present (--live), else the honest EMPTY (n=0) artifact. The live grading
    Lambda can overwrite this object in S3 as estimates accrue; the committed file is the honest
    baseline the page always has something to render.
  * site/method/eyeball/index.html — a standalone static page that fetches that JSON at runtime
    and renders the chart, degrading to the honest zero/low-n copy the artifact itself declares.

Run from repo root:  python3 scripts/v4_build_eyeball.py            (writes the empty-state artifact)
                     python3 scripts/v4_build_eyeball.py --live      (reads graded DDB records)
"""
from __future__ import annotations

import html
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lambdas"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import eyeball_calibration as ec  # noqa: E402
from v4_chrome import doors_nav, site_footer  # noqa: E402
from v4_kit import loop_ribbon  # noqa: E402

SLUG = "eyeball"
CANONICAL = f"/method/{SLUG}/"
DATA_URL = "/data/eyeball_calibration.json"
TITLE = "How wrong is the AI at eyeballing food? — The Method — averagejoematt"
DESCRIPTION = "The AI estimates a meal's macros from a photo, then gets graded against the logged truth. Its error, in public — never entered as data."


def esc(s) -> str:
    return html.escape(str(s), quote=True)


FONTS = (
    '<link rel="preload" href="/assets/fonts/v4/pxiTypc9vsFDm051Uf6KVwgkfoSxQ0GsQv8ToedPibnr0SZe1ZuWi3g.woff2" as="font" type="font/woff2" crossorigin>'
    '<link rel="preload" href="/assets/fonts/v4/6NU58FyLNQOQZAnv9ZwNjucMHVn85Ni7emAe9lKqZTnbB-gzTK0K1ChjeveQ7ZXk8g.woff2" as="font" type="font/woff2" crossorigin>'
    '<link rel="preload" href="/assets/fonts/v4/-F63fjptAgt5VM-kVkqdyU8n1i8q131nj-o.woff2" as="font" type="font/woff2" crossorigin>'
    '<link rel="stylesheet" href="/assets/css/fonts.css">'
)
THEME = (
    '<script>(function(){try{var t=localStorage.getItem("ajm-theme");'
    'if(t==="light"||t==="dark")document.documentElement.dataset.theme=t;}catch(e){}})();</script>'
)
MOTION_HEAD = (
    '<script>(function(){try{if(!("IntersectionObserver" in window))return;'
    'if(matchMedia("(prefers-reduced-motion: reduce)").matches)return;'
    'document.documentElement.classList.add("mo");'
    'window.__moFail=setTimeout(function(){document.documentElement.classList.remove("mo");},2600);}catch(e){}})();</script>'
)
MOTION_SCRIPT = '<script src="/assets/js/motion.js" defer></script>'


def topbar() -> str:
    return (
        '<header class="ev-top"><a class="brand" href="/"><span class="brand-mark" aria-hidden="true"></span>'
        '<span class="brand-name">averagejoematt</span> <span class="brand-door label">method</span></a>'
        f'{doors_nav("/data/", with_follow=False)}</header>'
    )


FOOTER = site_footer()

STYLE = """
<style>
.eb-wrap { max-width: var(--container); margin-inline: auto; padding: 0 var(--gutter) var(--sp-9); }
.eb-state { margin-top: var(--sp-5); border: var(--border-hair); border-radius: var(--radius); padding: var(--sp-6); background: var(--surface-raised); }
.eb-empty { color: var(--ink-muted); line-height: var(--lh-relaxed); }
.eb-grid { display: grid; gap: var(--sp-4); margin-top: var(--sp-5); min-width: 0; }
@media (min-width: 720px) { .eb-grid { grid-template-columns: repeat(2, 1fr); } }
.eb-macro { border: var(--border-hair); border-radius: var(--radius); padding: var(--sp-5); background: var(--surface-raised); min-width: 0; }
.eb-macro h3 { margin: 0; font-family: var(--font-serif); font-size: var(--fs-h3); color: var(--ink); }
.eb-macro .eb-n { font-family: var(--font-mono); font-size: var(--fs-small); color: var(--ink-faint); }
.eb-bar-row { display: grid; grid-template-columns: 84px 1fr auto; align-items: center; gap: var(--sp-3); margin-top: var(--sp-3); }
.eb-bar-label { font-family: var(--font-mono); font-size: var(--fs-label); text-transform: uppercase; letter-spacing: var(--tracking-label); color: var(--ink-faint); }
.eb-bar-track { height: 10px; border-radius: 999px; background: var(--surface-sunken); overflow: hidden; }
.eb-bar-fill { height: 100%; border-radius: 999px; background: var(--accent, var(--ink-muted)); }
.eb-bar-val { font-family: var(--font-mono); font-size: var(--fs-small); color: var(--ink); }
.eb-lown { margin-top: var(--sp-3); font-family: var(--font-mono); font-size: var(--fs-small); color: var(--ink-faint); }
.eb-trend { margin-top: var(--sp-2); font-size: var(--fs-small); color: var(--ink-muted); }
.eb-disclaimer { margin-top: var(--sp-6); color: var(--ink-muted); line-height: var(--lh-relaxed); }
</style>
"""

# The client renderer. Fetches the static artifact, renders honest empty / low-n / reported
# states. Pure vanilla JS, no deps (matches the v4 no-framework rule). Because the artifact
# self-declares its state, the page never fabricates a chart on thin data.
CLIENT_JS = (
    """
<script>
(function () {
  var MACRO_LABELS = { calories: "Calories", protein_g: "Protein", carbs_g: "Carbs", fat_g: "Fat" };
  var root = document.getElementById("eb-readout");
  function esc(s){ return String(s).replace(/[&<>\"]/g, function(c){ return {"&":"&amp;","<":"&lt;",">":"&gt;","\\\"":"&quot;"}[c]; }); }
  function el(html){ var d=document.createElement("div"); d.innerHTML=html; return d.firstElementChild; }
  function emptyState(a){
    return '<div class="eb-state eb-empty" data-readout data-state="empty">' +
      '<p><strong>No graded photos yet.</strong> Nothing has been eyeballed and graded, so there is no error to report ' +
      '(n = 0). This chart fills in only as real meal photos are estimated and checked against the logged day — ' +
      'it will never show a made-up accuracy number.</p></div>';
  }
  function bar(label, mape){
    var pct = Math.max(0, Math.min(100, mape));
    return '<div class="eb-bar-row"><span class="eb-bar-label">' + esc(label) + '</span>' +
      '<span class="eb-bar-track"><span class="eb-bar-fill" style="width:' + pct.toFixed(1) + '%"></span></span>' +
      '<span class="eb-bar-val">' + mape.toFixed(1) + '% MAPE</span></div>';
  }
  function macroCard(key, cell){
    var name = MACRO_LABELS[key] || key;
    if (!cell || !cell.sufficient) {
      var n = (cell && cell.n) || 0;
      return '<div class="eb-macro"><h3>' + esc(name) + '</h3>' +
        '<div class="eb-lown">n = ' + n + ' — too few to score yet. Stats are withheld until there are enough graded days ' +
        '(honest low-n; no precision claimed on thin data).</div></div>';
    }
    var body = '<div class="eb-macro"><h3>' + esc(name) + '</h3>' +
      '<div class="eb-n">n = ' + cell.n + ' graded days</div>' +
      bar("Mean abs err", cell.mape_pct) +
      '<div class="eb-bar-row"><span class="eb-bar-label">Median</span><span></span>' +
        '<span class="eb-bar-val">' + cell.median_abs_pct.toFixed(1) + '%</span></div>' +
      '<div class="eb-bar-row"><span class="eb-bar-label">Bias</span><span></span>' +
        '<span class="eb-bar-val">' + (cell.bias_pct > 0 ? "+" : "") + cell.bias_pct.toFixed(1) + '% (' +
          (cell.bias_pct > 0 ? "over" : (cell.bias_pct < 0 ? "under" : "no bias")) + ')</span></div>';
    if (cell.trend) {
      body += '<p class="eb-trend">Trend: ' + esc(cell.trend.direction) + ' — recent ' +
        cell.trend.recent_mape_pct.toFixed(1) + '% vs earlier ' + cell.trend.earlier_mape_pct.toFixed(1) + '%.</p>';
    }
    return body + '</div>';
  }
  function render(a){
    if (!a || a.state === "empty" || a.n_days === 0) { root.appendChild(el(emptyState(a))); return; }
    var wrap = el('<div class="eb-state" data-readout data-state="' + esc(a.state) + '"></div>');
    var head = '<p class="eb-n" style="font-family:var(--font-mono);color:var(--ink-faint)">' +
      a.n_days + ' graded day' + (a.n_days === 1 ? "" : "s") + ' &middot; as of ' + esc(a.as_of || "") +
      (a.state === "low_n" ? ' &middot; low-n: summary stats withheld below the threshold of ' + esc(a.min_n) : '') + '</p>';
    wrap.innerHTML = head + '<div class="eb-grid">' +
      Object.keys(MACRO_LABELS).map(function(k){ return macroCard(k, (a.macros||{})[k]); }).join("") + '</div>';
    root.appendChild(wrap);
  }
  fetch('"""
    + DATA_URL
    + """', { cache: "no-store" })
    .then(function(r){ if (!r.ok) throw new Error("no artifact"); return r.json(); })
    .then(render)
    .catch(function(){ root.appendChild(el(emptyState(null))); });
})();
</script>
"""
)


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
  <a class="skip" href="#eb">Skip to the content</a>
  {topbar()}
  <main id="eb">
    <div class="page-hero">
      <p class="ph-kicker label">the method &middot; the model graded</p>
      <h1 class="ph-title">How wrong is the AI at eyeballing food?</h1>
      <p class="ph-promise">Hand a vision model a meal photo and it will confidently guess the macros. So we let it — then grade every guess against the day actually logged in MacroFactor. The error is published here. The estimates are <strong>never</strong> entered as nutrition data; they exist only to be graded (ADR-105). Below the threshold, no accuracy number is claimed at all.</p>
      {loop_ribbon("method")}
    </div>
    <div class="eb-wrap">
      <section class="rd-sec" style="margin-top:0">
        <h2 class="rd-h">The reliability chart</h2>
        <p class="rd-prose">Per macro: mean and median absolute percent error, the direction of any bias (does it over- or under-estimate?), and whether recent guesses are getting better. Everything here is computed deterministically from the graded records; the model never scores itself.</p>
        <div id="eb-readout"></div>
      </section>
      <p class="eb-disclaimer">The estimate lives in its own database partition (<code>SOURCE#eyeball_estimate</code>), walled off from the nutrition record by a structural test (<code>tests/test_eyeball_isolation_1390.py</code>) that fails if an estimate value could ever reach a nutrition metric path. The vision call is Haiku-tier and budget-gated (~$1/mo, ADR-063).</p>
      <p class="correlative">Generated by <code>scripts/v4_build_eyeball.py</code> from <code>lambdas/eyeball_calibration.py</code>. The chart reads a static artifact at <code>{esc(DATA_URL)}</code>. <span class="confidence conf-low">graded, not asserted</span></p>
    </div>
  </main>
  {FOOTER}
  {MOTION_SCRIPT}
  {CLIENT_JS}
</body>
</html>
"""


def build_artifact(live: bool) -> dict:
    """The reliability artifact. --live reads graded DDB records; otherwise the honest
    empty (n=0) artifact — the committed baseline."""
    grades: list[dict] = []
    if live:
        import boto3

        table = boto3.resource("dynamodb", region_name="us-west-2").Table("life-platform")
        grades = ec.list_grades(table)
        # Decimal -> float for JSON (the artifact carries only aggregate error, never raw macros).
        from numeric import decimals_to_float

        grades = decimals_to_float(grades)
    return ec.build_reliability_artifact(grades)


def main() -> int:
    live = "--live" in sys.argv[1:]
    artifact = build_artifact(live)

    data_path = ROOT / "site" / "data" / "eyeball_calibration.json"
    data_path.parent.mkdir(parents=True, exist_ok=True)
    data_path.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    out_dir = ROOT / "site" / "method" / SLUG
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "index.html").write_text(render_page(), encoding="utf-8")

    print(f"{CANONICAL}: state={artifact['state']} n_days={artifact['n_days']} (live={live})")
    print(f"{DATA_URL}: {data_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
