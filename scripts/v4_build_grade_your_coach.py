#!/usr/bin/env python3
"""v4_build_grade_your_coach.py — generate /method/grade-your-coach/ (#1396).

"Grade your own LLM coach": paste any forecaster's predictions and outcomes and get the
SAME scorecard this platform's own AI coaches get — Brier score, reliability curve, skill
versus the base rate, and a verdict that refuses to flatter.

Two outputs, both DEPLOY-RACE-SAFE (no site-api /api endpoint — the page reads a STATIC
generated JSON, exactly like /method/eyeball reads /data/eyeball_calibration.json):

  * site/data/calibration_demo.json — the two demo ledgers, derived from the committed
    copies in oss/calibration-core/demo/ so the site and the open package can never ship
    different demo data.
  * site/method/grade-your-coach/index.html — the tool page. All computation is
    client-side (site/assets/js/grade_your_coach.js -> calibration-core.js); the pasted
    text is never uploaded anywhere, which is why there is no endpoint here to upload to.

The math is NOT reimplemented here. site/assets/js/calibration-core.js is a byte-identical
vendored copy of oss/calibration-core/js/calibration-core.js, and both are pinned to the
same test vectors as the deployed Python grader (tests/test_calibration_core_parity.py,
tests/js/calibration_core.test.mjs).

Run from repo root:  python3 scripts/v4_build_grade_your_coach.py
"""

from __future__ import annotations

import html
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from v4_chrome import doors_nav, site_footer  # noqa: E402
from v4_kit import loop_ribbon  # noqa: E402

SLUG = "grade-your-coach"
CANONICAL = f"/method/{SLUG}/"
DATA_URL = "/data/calibration_demo.json"
DEMO_DIR = ROOT / "oss" / "calibration-core" / "demo"
TITLE = "Grade your own LLM coach — The Method — averagejoematt"
DESCRIPTION = (
    "Your wearable's AI coach makes predictions. Does it publish whether they came true? "
    "Paste its calls and outcomes here and get the same scorecard mine get — Brier score, "
    "reliability curve, skill versus the base rate. Computed in your browser; nothing is uploaded."
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
        '<span class="brand-name">averagejoematt</span> <span class="brand-door label">method</span></a>'
        f'{doors_nav("/data/", with_follow=False)}</header>'
    )


FOOTER = site_footer(current_door="/data/")

STYLE = """
<style>
.gyc-wrap { max-width: var(--container); margin-inline: auto; padding: 0 var(--gutter) var(--sp-9); }
.gyc-cols { display: grid; gap: var(--sp-5); margin-top: var(--sp-5); min-width: 0; align-items: start; }
@media (min-width: 901px) { .gyc-cols { grid-template-columns: minmax(0, 4fr) minmax(0, 6fr); } }
.gyc-pane { border: var(--border-hair); border-radius: var(--radius); padding: var(--sp-5); background: var(--surface-raised); min-width: 0; }
.gyc-pane h2 { margin: 0 0 var(--sp-3); font-family: var(--font-serif); font-size: var(--fs-h3); color: var(--ink); }
#gyc-input { width: 100%; min-height: 15rem; resize: vertical; box-sizing: border-box; padding: var(--sp-3);
  font-family: var(--font-mono); font-size: var(--fs-small); line-height: var(--lh-relaxed);
  color: var(--ink); background: var(--surface-sunken); border: var(--border-hair); border-radius: var(--radius); }
.gyc-btns { display: flex; flex-wrap: wrap; gap: var(--sp-2); margin-top: var(--sp-3); }
.gyc-btn { font-family: var(--font-mono); font-size: var(--fs-label); text-transform: uppercase; letter-spacing: var(--tracking-label);
  padding: var(--sp-2) var(--sp-3); border: var(--border-hair); border-radius: var(--radius); background: transparent; color: var(--ink-muted); cursor: pointer; }
.gyc-btn:hover, .gyc-btn:focus-visible { color: var(--ink); border-color: var(--ink-muted); }
.gyc-prov { margin-top: var(--sp-3); font-family: var(--font-mono); font-size: var(--fs-small); color: var(--ink-faint); line-height: var(--lh-relaxed);
  overflow-wrap: anywhere; word-break: break-word; }
.gyc-card { border: var(--border-hair); border-radius: var(--radius); padding: var(--sp-5); background: var(--surface-raised); min-width: 0; }
.gyc-empty { color: var(--ink-muted); line-height: var(--lh-relaxed); }
.gyc-figs { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--sp-4); }
@media (min-width: 601px) { .gyc-figs { grid-template-columns: repeat(4, minmax(0, 1fr)); } }
.gyc-figs > .gyc-fig { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.gyc-fig-v { font-family: var(--font-mono); font-size: var(--fs-h3); color: var(--ink); }
/* "skill vs base rate" is the only label that wraps to two lines, which pushed its
   sub-line a row below the other three and left the block ragged. Row tracks on the
   .gyc-fig itself do NOT fix that — each fig is its own grid, so siblings share no
   tracks. Reserving two label lines everywhere does, in every browser. (`subgrid` on
   .gyc-figs would be the tidier answer once its floor is safely below the site's.) */
.gyc-fig-l { color: var(--ink-faint); min-height: 2.6em; min-height: 2lh; }
.gyc-fig-s { font-size: var(--fs-small); color: var(--ink-muted); line-height: var(--lh-relaxed); }
.gyc-verdict { margin-top: var(--sp-5); padding-top: var(--sp-4); border-top: var(--border-hair); }
.gyc-verdict-h { margin: 0; font-family: var(--font-serif); font-size: var(--fs-h3); color: var(--ink); text-transform: capitalize; }
.gyc-verdict-b { margin: var(--sp-2) 0 0; color: var(--ink-muted); line-height: var(--lh-relaxed); }
.gyc-label { margin: var(--sp-3) 0 0; color: var(--ink-faint); }
/* Chart ABOVE table, never beside it. A side-by-side grid here sat inside the
   already-narrow right pane, so its minmax(0, 1fr) table track collapsed to as
   little as 53px and clipped the `calls` column at every width — the one column
   the copy leans on. Stacked, the table always gets the full pane width and
   fits without scrolling at every breakpoint. */
.gyc-chartwrap { display: grid; gap: var(--sp-4); margin-top: var(--sp-5); min-width: 0; }
.gyc-chart { position: relative; min-width: 0; max-width: 340px; }
@media (min-width: 901px) { .gyc-chart { max-width: 400px; } }
.gyc-svg { width: 100%; height: auto; display: block; }
.gyc-plot { fill: var(--surface-sunken); stroke: var(--rule); stroke-width: 1; }
.gyc-ideal { stroke: var(--ink-faint); stroke-width: 1; stroke-dasharray: 4 4; }
.gyc-curve { stroke: var(--ink-muted); stroke-width: 1.5; }
.gyc-dot { fill: var(--accent, var(--ink)); fill-opacity: 0.75; }
.gyc-ax { margin: var(--sp-2) 0 0; color: var(--ink-faint); }
.gyc-ax-y { margin-top: 0; }
.gyc-axnote { margin-top: var(--sp-3); font-size: var(--fs-small); color: var(--ink-muted); line-height: var(--lh-relaxed); }
/* Belt-and-braces scroller for the >820px case. Below 820px the shared .rd-tbl
   primitive (evidence.css #1008) already turns the table into its own scroller —
   do NOT pin a min-width here, that re-inflates the block past this wrapper and
   re-creates the clip this is meant to prevent. */
.gyc-tblwrap { overflow-x: auto; max-width: 100%; }
.gyc-tblwrap:focus-visible { outline: 2px solid var(--ink-muted); outline-offset: 2px; }
.gyc-tbl th, .gyc-tbl td { white-space: nowrap; }
.gyc-notes { margin-top: var(--sp-4); padding-top: var(--sp-4); border-top: var(--border-hair); font-size: var(--fs-small); color: var(--ink-muted); line-height: var(--lh-relaxed); }
.gyc-rejects { margin: var(--sp-2) 0 0; padding-left: var(--sp-4); }
.gyc-scroll { overflow-x: auto; }
</style>
"""

CLIENT_JS = '<script type="module" src="/assets/js/grade_your_coach.js"></script>'


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
  <a class="skip" href="#gyc">Skip to the tool</a>
  {topbar()}
  <main id="gyc">
    <div class="page-hero">
      <p class="ph-kicker label">the method &middot; the open artifact</p>
      <h1 class="ph-title">Grade your own LLM coach</h1>
      <p class="ph-promise">Every wearable now ships an AI coach, and every one of them tells you what will happen. None of them publishes whether it was right. This page is the scorer that does &mdash; the <em>same</em> one that grades my eight coaches in public, running here in your browser. Paste what your coach predicted and what actually happened, and find out whether its confidence was ever worth anything.</p>
      {loop_ribbon("method")}
    </div>
    <div class="gyc-wrap">
      <div class="gyc-cols">
        <section class="gyc-pane">
          <h2>Paste the ledger</h2>
          <p class="rd-prose">One forecast per line: <strong>the confidence it stated</strong>, then <strong>what actually happened</strong>. CSV or tab-separated, header optional. Confidence can be <code>0.8</code>, <code>80%</code> or a word (<code>low</code>, <code>medium</code>, <code>high</code>); outcomes can be <code>confirmed</code>/<code>refuted</code>, <code>yes</code>/<code>no</code>, <code>1</code>/<code>0</code>, or <code>pending</code> for calls that have not come due.</p>
          <label class="label" for="gyc-input">your ledger</label>
          <textarea id="gyc-input" spellcheck="false" aria-describedby="gyc-privacy" placeholder="confidence,outcome&#10;0.8,confirmed&#10;0.9,refuted&#10;high,yes&#10;0.6,pending"></textarea>
          <div class="gyc-btns">
            <button type="button" class="gyc-btn" id="gyc-grade">Grade it</button>
            <button type="button" class="gyc-btn" id="gyc-demo-example">Load the worked example</button>
            <button type="button" class="gyc-btn" id="gyc-demo-matthew">Load my public ledger</button>
            <button type="button" class="gyc-btn" id="gyc-clear">Clear</button>
          </div>
          <p class="gyc-prov" id="gyc-prov"></p>
          <p class="gyc-prov" id="gyc-privacy"><strong>Nothing is uploaded.</strong> The scoring runs entirely in this page &mdash; there is no endpoint behind it, no request carrying your text, and nothing stored. Close the tab and it is gone.</p>
        </section>
        <section class="gyc-pane">
          <h2>The scorecard</h2>
          <div id="gyc-readout" class="gyc-scroll"></div>
        </section>
      </div>

      <section class="rd-sec">
        <h2 class="rd-h">What the numbers mean</h2>
        <p class="rd-prose"><strong>Brier score</strong> is the mean squared error of the stated probabilities: <code>mean((p &minus; y)&sup2;)</code>. Zero is perfect. <strong>0.25 is the always-say-50% baseline</strong> &mdash; the score you get by refusing to commit. Lower is better.</p>
        <p class="rd-prose"><strong>Skill versus the base rate</strong> is the honest question underneath: does the stated confidence beat simply guessing the observed average every single time? A coach that predicts "you'll sleep badly" on a week where you slept badly 80% of the time has a great hit rate and no skill at all. Negative skill means it did <em>worse</em> than that trivial baseline.</p>
        <p class="rd-prose"><strong>The reliability curve</strong> asks whether 80% actually means 80%. Each dot is a confidence band, sized by how many calls landed in it; on the diagonal is honest, below it is over-confident.</p>
        <p class="rd-prose"><strong>Calibrated and skilled are different claims, and the second gates the first.</strong> A forecaster whose confidences line up but whose skill is at or below zero reads <em>not yet skillful</em> here &mdash; reliability is never allowed to dress up a forecaster that lost to the base rate. Fewer than five resolved calls and the tool says <em>insufficient data</em> rather than inventing a verdict.</p>
        <p class="rd-prose">Rows whose outcome is not yet known are counted and excluded, never guessed. Rows that cannot be read are listed back to you rather than quietly scored at 0.5 &mdash; a defaulted confidence would put a claim on the scorecard that nobody made.</p>
      </section>

      <section class="rd-sec">
        <h2 class="rd-h">Take the scorer, not just the answer</h2>
        <p class="rd-prose">The engine on this page is a standalone, MIT-licensed package: one Python file, one JavaScript file, zero dependencies, no network. It is the <em>same</em> code that produces <a href="/method/calibration/">my own calibration scoreboard</a> &mdash; extracted rather than reimplemented, and held to that by a shared test-vector suite that three implementations (the deployed Python grader, the package, and the browser port running right now) must reproduce <em>exactly</em>, not approximately.</p>
        <p class="rd-prose">The package README documents the ledger schema and every grading rule in full, so a third party can reproduce a scorecard independently &mdash; in a spreadsheet if they want &mdash; and check this page rather than trust it. Source: <code>oss/calibration-core/</code>.</p>
        <p class="rd-prose">The demo ledgers are honest about themselves. <strong>My public ledger</strong> is a verbatim snapshot of the already-public <code>/api/predictions</code> surface, with its provenance stamped in the file; it was captured on day 1 of a fresh experiment cycle, so every call in it is still pending and it scores <em>insufficient data</em> &mdash; which is the correct answer, not a broken one. <strong>The worked example</strong> is explicitly synthetic and labelled as such: an illustrative wearable-coach ledger that exists so the page has something to render before you paste your own.</p>
      </section>

      <p class="correlative">Generated by <code>scripts/v4_build_grade_your_coach.py</code>. The scorer is <code>oss/calibration-core/</code>, vendored to <code>/assets/js/calibration-core.js</code> and pinned to the platform grader by <code>tests/test_calibration_core_parity.py</code>. <span class="confidence conf-low">client-side &middot; nothing uploaded</span></p>
    </div>
  </main>
  {FOOTER}
  {MOTION_SCRIPT}
  {CLIENT_JS}
</body>
</html>
"""


def build_demo_payload() -> dict:
    """Derive the site's demo artifact from the committed OSS demo ledgers.

    Single source of truth: the package's demo/ directory. If the two ever
    disagree the site would be teaching a schema the package does not ship.
    """
    with open(DEMO_DIR / "matthew_public_ledger.json", "r", encoding="utf-8") as fh:
        matthew = json.load(fh)
    with open(DEMO_DIR / "worked_example.json", "r", encoding="utf-8") as fh:
        example = json.load(fh)

    mprov = matthew["provenance"]
    eprov = example["provenance"]
    return {
        "_note": "Generated by scripts/v4_build_grade_your_coach.py from oss/calibration-core/demo/. Do not hand-edit.",
        "matthew": {
            "name": matthew["name"],
            "provenance_line": (
                f"Real data. {len(matthew['rows'])} forward calls from the public {mprov['source_url']} "
                f"payload, fetched {mprov['fetched_at']}. {mprov['reader_note']}"
            ),
            "rows": [{"confidence": r["confidence"], "outcome": r["outcome"]} for r in matthew["rows"]],
        },
        "example": {
            "name": example["name"],
            "provenance_line": (
                # `why` is written for a developer reading the package (it names the
                # sibling file); readers get the same honesty without the filename.
                f"SYNTHETIC — not real data and not anyone's real coach. {eprov['reader_note']}"
            ),
            "rows": [{"confidence": r["confidence"], "outcome": r["outcome"]} for r in example["rows"]],
        },
    }


def main() -> int:
    payload = build_demo_payload()
    data_path = ROOT / "site" / "data" / "calibration_demo.json"
    data_path.parent.mkdir(parents=True, exist_ok=True)
    data_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    out_dir = ROOT / "site" / "method" / SLUG
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "index.html").write_text(render_page(), encoding="utf-8")

    print(f"{CANONICAL}: written ({len(payload['matthew']['rows'])} real rows, {len(payload['example']['rows'])} example rows)")
    print(f"{DATA_URL}: {data_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
