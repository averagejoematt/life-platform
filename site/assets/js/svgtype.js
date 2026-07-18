/*
  svgtype.js — the SVG legibility floor, generalized (#1210).
  ----------------------------------------------------------------------------
  SVG <text> is sized in viewBox units, so its ON-SCREEN size scales with the
  rendered width of the svg: a 320-unit viewBox drawn 340px wide renders at
  scale ~1.06, but a radar drawn 280px wide (viewBox 320) renders at ~0.88 —
  so an 8–10px label lands at 7–9px effective, below the 11px smallest-shipping
  register (DESIGN_SYSTEM_V5 §10.5). #1017 fixed exactly this for the home
  constellation (story.js sizeConstellation); this is that technique, made
  shared and data-driven so charts.js + sigils.js reuse ONE floor.

  For each registered SVG-text class we set an svg-scoped CSS var to the
  user-unit size that yields >=11px on screen — max(base, floor / scale) —
  where `scale` is the live user→screen scale read off getScreenCTM().a (with a
  boundingClientRect/viewBox fallback). The stylesheet consumes the var with a
  static default (`.radar-lbl { font-size: var(--fs-radar-lbl) }`, default
  defined in tokens.css), so with JS off the label keeps today's desktop-true
  size and with JS on it is floored. On desktop where scale is large enough
  that the base already clears the floor, max() is a no-op — no regression.

  Self-initializing on import (side-effect): imported by charts.js AND sigils.js
  so any page that renders one of these charts wires the floor automatically —
  re-measured rAF-debounced on resize and re-applied when charts are injected
  (the SPA readouts mount their svg after fetch). The rendered-px audit in
  tests/visual_qa.py is the arbiter that this actually holds; this module is the
  fix, that test is the guard.
*/

// class selector → { cssVar consumed by the stylesheet, base user-unit size,
// effective-px floor }. base MUST equal the stylesheet's default for that var so
// max(base, floor/scale) never shrinks a label below its designed size.
export const SVG_TYPE_FLOORS = [
  { sel: ".aq-lab, .aq-ax", cssVar: "--fs-aq", base: 8, floor: 11 }, // autonomic 2x2 (charts.js autonomicQuadrant)
  { sel: ".radar-lbl", cssVar: "--fs-radar-lbl", base: 10, floor: 11 }, // pillar radar (charts.js radarChart)
  { sel: ".bm-cap", cssVar: "--fs-bm-cap", base: 8, floor: 11 }, // body-map front/back caption (evidence_body.js)
  { sel: ".emblem-level", cssVar: "--fs-emblem-level", base: 8, floor: 11 }, // tier-emblem "LEVEL" (sigils.js tierEmblem)
  { sel: ".arch-svg .at", cssVar: "--fs-arch-at", base: 13, floor: 11 }, // architecture diagram box title (/method/build editorial)
  { sel: ".arch-svg .as", cssVar: "--fs-arch-as", base: 9.5, floor: 11 }, // architecture diagram box subtitle
  { sel: ".att-svg .att-tick, .att-svg .att-label, .att-svg .att-censor, .att-svg .att-live-mark", cssVar: "--fs-att-sm", base: 11, floor: 11 }, // attempts overlay ticks/labels (#1375)
  { sel: ".att-svg .att-death", cssVar: "--fs-att-death", base: 13, floor: 12 }, // attempts overlay death mark (#1375)
];

// The live user→screen horizontal scale of an svg: getScreenCTM().a is exact
// (it folds in the viewBox, preserveAspectRatio AND any CSS transform), so it
// works for a scale >1 (aq wrap wider than its viewBox) and <1 (radar capped
// narrower than its viewBox) alike. Fallback to rendered-width / viewBox-width
// for the rare case getScreenCTM is unavailable.
function svgScale(svg) {
  try {
    const ctm = svg.getScreenCTM();
    // hypot(a, b) is the magnitude of the transformed x-axis unit vector — the true
    // uniform scale even for a rotated element (a -90deg axis label has a≈0), so a
    // font's on-screen size is fontSize * this regardless of orientation.
    if (ctm) {
      const s = Math.hypot(ctm.a, ctm.b);
      if (s > 0) return s;
    }
  } catch (e) {
    /* detached / not laid out — fall through */
  }
  try {
    const vb = svg.viewBox && svg.viewBox.baseVal;
    const w = svg.getBoundingClientRect().width;
    if (vb && vb.width > 0 && w > 0) return w / vb.width;
  } catch (e) {
    /* ignore */
  }
  return 0;
}

// Measure once per svg, set each matched class's var on that svg root. Scoping
// the var to the svg (not :root) means every chart floors to ITS OWN rendered
// scale, and the value inherits down to the <text> elements.
export function sizeSvgTextFloors(scope) {
  const root = scope && scope.querySelectorAll ? scope : document;
  const scaleCache = new Map();
  for (const spec of SVG_TYPE_FLOORS) {
    let texts;
    try {
      texts = root.querySelectorAll(spec.sel);
    } catch (e) {
      continue;
    }
    for (const t of texts) {
      const svg = t.ownerSVGElement;
      if (!svg) continue;
      let scale = scaleCache.get(svg);
      if (scale === undefined) {
        scale = svgScale(svg);
        scaleCache.set(svg, scale);
      }
      if (!scale) continue; // hidden / not laid out — the stylesheet default stands
      // Round the user-unit size UP to 0.01px so it never rounds BELOW floor/scale
      // (a plain toFixed can shave the effective size a hair under 11px).
      const size = Math.ceil(Math.max(spec.base, spec.floor / scale) * 100) / 100;
      svg.style.setProperty(spec.cssVar, size + "px");
    }
  }
}

// ── self-init (browser only) ─────────────────────────────────────────────────
if (typeof window !== "undefined" && typeof document !== "undefined") {
  let raf = 0;
  const reflow = () => {
    if (raf) cancelAnimationFrame(raf);
    raf = requestAnimationFrame(() => {
      raf = 0;
      sizeSvgTextFloors(document);
    });
  };
  const start = () => {
    sizeSvgTextFloors(document);
    // rAF-debounced on resize/orientation so a drag stays smooth (vars only — no redraw).
    window.addEventListener("resize", reflow, { passive: true });
    try {
      // SPA readouts (evidence.js / cockpit.js) inject their svg after fetch —
      // reflow on any DOM insertion, debounced, so a newly-mounted chart floors too.
      new MutationObserver((muts) => {
        for (const m of muts) {
          for (const n of m.addedNodes) {
            if (n.nodeType === 1) {
              reflow();
              return;
            }
          }
        }
      }).observe(document.body, { childList: true, subtree: true });
    } catch (e) {
      /* no MutationObserver — the initial + resize passes still floor static markup */
    }
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
}
