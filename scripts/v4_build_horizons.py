#!/usr/bin/env python3
"""
v4_build_horizons.py — generate the Horizons feed page (#1707, epic #1686 S3).

Horizons is the Mind coach's weekly, broadly-curated media pick (article / podcast /
video / paper / news / longform / essay / song) that widens Matthew's aperture beyond
the day's numbers. It lives on the DATA door at /data/horizons/ (near the reading
shelf), NOT the Story door (owner decision, 2026-07-25). The reader hook is the
retrospective: the week after each pick, the coach writes a grounded "why I sent it /
what I hoped it'd do" reflection (see lambdas/reading/horizons_retrospective.py).

CHROME NOTE (#1009): the `<nav class="doors">`, `<footer class="site-foot">`, the
`.loop-forward` CTA, and the `<head>` icon/manifest block emitted here come straight
from `scripts/v4_chrome.py` (the single source), so `scripts/v4_apply_chrome.py` is a
no-op on this page. Data comes from the read-only /api/horizons endpoint; the shell only
provides the mount point (`[data-horizons]`) that assets/js/horizons.js fills.

Read-only; writes only site/data/horizons/index.html. Run from repo root:
    python3 scripts/v4_build_horizons.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import v4_chrome  # noqa: E402

OUT = Path("site/data/horizons/index.html")

TITLE = "Horizons — The Data — averagejoematt"
DESC = "The Mind coach's weekly media pick — and, a week later, the grounded retrospective on why it went out."
CANONICAL = "https://averagejoematt.com/data/horizons/"

_PRELOADS = (
    '<link rel="preload" href="/assets/fonts/v4/pxiTypc9vsFDm051Uf6KVwgkfoSxQ0GsQv8ToedPibnr0SZe1ZuWi3g.woff2" as="font" type="font/woff2" crossorigin>',
    '<link rel="preload" href="/assets/fonts/v4/6NU78FyLNQOQZAnv9bYEvDiIdE9Ea92uemAk_WBq8U_9v0c2Wa0KxC9TeP2Xz5c.woff2" as="font" type="font/woff2" crossorigin>',
    '<link rel="preload" href="/assets/fonts/v4/-F63fjptAgt5VM-kVkqdyU8n1i8q131nj-o.woff2" as="font" type="font/woff2" crossorigin>',
)


def render() -> str:
    head_chrome = v4_chrome.head_chrome()
    doors = v4_chrome.doors_nav("/data/", with_follow=True)
    loop_fwd = v4_chrome.loop_forward("/data/", self_path="/data/horizons/")
    footer = v4_chrome.site_footer()
    preloads = "\n  ".join(_PRELOADS)
    return f"""<!DOCTYPE html>
<html lang="en" data-door="data">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
  <title>{TITLE}</title>
  <meta name="description" content="{DESC}">
  <link rel="canonical" href="{CANONICAL}">
  <meta property="og:type" content="website">
  <meta property="og:site_name" content="averagejoematt">
  <meta property="og:url" content="{CANONICAL}">
  <meta property="og:title" content="{TITLE}">
  <meta property="og:description" content="{DESC}">
  <meta property="og:image" content="https://averagejoematt.com/assets/images/og-home.png">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="{TITLE}">
  <meta name="twitter:description" content="{DESC}">
{head_chrome}
  {preloads}
  <link rel="stylesheet" href="/assets/css/fonts.css">
  <link rel="stylesheet" href="/assets/css/tokens.css">
  <link rel="stylesheet" href="/assets/css/story.css">
  <script>(function(){{try{{var t=localStorage.getItem("ajm-theme");if(t==="light"||t==="dark")document.documentElement.dataset.theme=t;}}catch(e){{}}}})();</script>
  <script>(function(){{try{{if(!("IntersectionObserver" in window))return;if(matchMedia("(prefers-reduced-motion: reduce)").matches)return;document.documentElement.classList.add("mo");window.__moFail=setTimeout(function(){{document.documentElement.classList.remove("mo");}},2600);}}catch(e){{}}}})();</script>
</head>
<body class="dx-page">
  <a class="skip" href="#dx">Skip to the picks</a>
  <header class="story-top">
    <a class="brand" href="/"><span class="brand-mark" aria-hidden="true"></span><span class="brand-name">averagejoematt</span> <span class="brand-door label">the data</span></a>
    {doors}
  </header>
  <main id="dx" class="dx-main">
    <div class="page-hero">
      <p class="ph-kicker label">the data · broadening the horizon</p>
      <h1 class="ph-title">Horizons</h1>
      <p class="ph-promise">A weekly media pick from the Mind coach — chosen to widen the aperture beyond the day's numbers. A week after each one, the coach writes back: why it went out, and what it was meant to open up. The live shelf lives in <a href="/data/reading/">the reading room</a>.</p>
      <nav class="loop-ribbon" aria-label="Where this sits in the loop"><a href="/cockpit/">Now</a><span class="lr-sep" aria-hidden="true">&middot;</span><span class="lr-here" aria-current="page">Data</span><span class="lr-arrow" aria-hidden="true">&rarr;</span><a href="/coaching/">Coaching</a><span class="lr-arrow" aria-hidden="true">&rarr;</span><a href="/protocols/">Protocols</a><span class="lr-arrow" aria-hidden="true">&rarr;</span><a href="/story/">Story</a><span class="lr-arrow" aria-hidden="true">&#8635;</span></nav>
    </div>
    <section class="dx-read" data-horizons aria-label="Horizons picks">
      <p class="dx-loading shimmer">Loading the picks…</p>
    </section>
  </main>
  {loop_fwd}{footer}
  <script src="/assets/js/motion.js" defer></script>
  <script type="module" src="/assets/js/horizons.js"></script>
</body>
</html>
"""


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(render(), encoding="utf-8")
    print(f"✅ wrote {OUT}")


if __name__ == "__main__":
    main()
