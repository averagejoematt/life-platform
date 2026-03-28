#!/usr/bin/env python3
"""
patch_tier2_narrative.py — Add story-mode narrative intro sections to Sleep and Glucose pages.
Idempotent: checks for existing narrative-intro before adding.

These are serif-font story paragraphs that sit above the signal dashboard,
giving the observatory pages a human voice before the data.
"""
import os

SITE = os.path.expanduser("~/Documents/Claude/life-platform/site")

NARRATIVES = {
    "sleep": {
        "file": os.path.join(SITE, "sleep", "index.html"),
        "anchor": '<section class="s-hero"',  # insert before this
        "html": '''
<!-- Tier 2: Narrative intro — story mode above signal dashboard -->
<section class="narrative-intro reveal" style="
  padding: calc(var(--nav-height) + var(--space-16)) var(--page-padding) var(--space-12);
  max-width: var(--prose-width);
  margin: 0 auto;
  border-bottom: 1px solid var(--border-subtle);
">
  <div class="eyebrow" style="margin-bottom:var(--space-4);color:var(--pillar-sleep)">// Sleep Observatory</div>
  <h1 style="font-family:var(--font-display);font-size:var(--text-h2);color:var(--text);letter-spacing:var(--ls-display);margin-bottom:var(--space-6);">
    The thing I thought I was <span style="color:var(--pillar-sleep)">good at.</span>
  </h1>
  <div style="font-family:var(--font-serif);font-size:var(--text-lg);color:var(--text-muted);line-height:1.8;">
    <p style="margin-bottom:var(--space-4);">
      I always told myself I slept well. Eight hours, no alarm, out like a light.
      Then I put a sensor on my wrist, a pod under my mattress, and a thermometer
      in my bedroom — and discovered that <em>duration</em> and <em>quality</em>
      are completely different metrics.
    </p>
    <p style="margin-bottom:var(--space-4);">
      This page tracks what actually happens between lights-out and wake-up:
      sleep architecture, HRV recovery, bed temperature experiments, and the
      circadian patterns that predict whether tomorrow will be a good day or a hard one.
    </p>
    <p style="font-size:var(--text-sm);color:var(--text-faint);font-family:var(--font-mono);">
      Data from Whoop, Eight Sleep, and Apple Health. Updated daily.
    </p>
  </div>
</section>
'''
    },
    "glucose": {
        "file": os.path.join(SITE, "glucose", "index.html"),
        "anchor": '<section class="',  # first section after body content
        "html": '''
<!-- Tier 2: Narrative intro — story mode above signal dashboard -->
<section class="narrative-intro reveal" style="
  padding: calc(var(--nav-height) + var(--space-16)) var(--page-padding) var(--space-12);
  max-width: var(--prose-width);
  margin: 0 auto;
  border-bottom: 1px solid var(--border-subtle);
">
  <div class="eyebrow" style="margin-bottom:var(--space-4);color:var(--pillar-nutrition)">// Glucose Observatory</div>
  <h1 style="font-family:var(--font-display);font-size:var(--text-h2);color:var(--text);letter-spacing:var(--ls-display);margin-bottom:var(--space-6);">
    The number that <span style="color:var(--pillar-nutrition)">quieted the anxiety.</span>
  </h1>
  <div style="font-family:var(--font-serif);font-size:var(--text-lg);color:var(--text-muted);line-height:1.8;">
    <p style="margin-bottom:var(--space-4);">
      At 302 pounds, I assumed my blood sugar was a disaster. I wore a CGM expecting
      to confirm every fear I had about my metabolic health. Instead, I found out
      I wasn't in the danger zone I'd imagined — and that data changed my relationship
      with the anxiety more than any reassurance ever could.
    </p>
    <p style="margin-bottom:var(--space-4);">
      This page shows what my glucose actually does: time-in-range, variability,
      meal responses, and the patterns that connect what I eat to how I feel
      two hours later.
    </p>
    <p style="font-size:var(--text-sm);color:var(--text-faint);font-family:var(--font-mono);">
      Data from Dexcom Stelo CGM. 30-day rolling window.
    </p>
  </div>
</section>
'''
    },
}

patched = 0
for page, cfg in NARRATIVES.items():
    fpath = cfg["file"]
    if not os.path.isfile(fpath):
        print(f"  SKIP: {fpath} not found")
        continue

    with open(fpath, "r") as f:
        content = f.read()

    if "narrative-intro" in content:
        print(f"  SKIP: {page}/index.html already has narrative intro")
        continue

    # For sleep: insert before the hero section, after the nav div
    # For glucose: similar pattern
    # Strategy: insert after <div id="amj-nav"></div> line
    nav_marker = '<div id="amj-nav"></div>'
    if nav_marker in content:
        content = content.replace(nav_marker, nav_marker + cfg["html"], 1)
        # Also need to remove the padding-top from the hero since narrative now provides it
        # For sleep: .s-hero has padding-top: calc(var(--nav-height) + ...)
        # We'll adjust by removing nav-height from the hero padding
        content = content.replace(
            'padding: calc(var(--nav-height) + var(--space-20))',
            'padding: var(--space-12)',
            1
        )
    else:
        print(f"  WARN: Could not find nav marker in {page}/index.html")
        continue

    with open(fpath, "w") as f:
        f.write(content)

    print(f"  DONE: {page}/index.html — narrative intro added")
    patched += 1

print(f"\nNarrative intros: {patched} patched")
