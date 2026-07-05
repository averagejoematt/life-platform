/*
  portraits.js — commissioned engraved coach portraits (ADR-106, DESIGN_SYSTEM_V5 §8.7).

  portrait(coach, opts) → SVG string when a SIGNED recipe exists in the generated
  registry (portrait_data.js), else null — call sites compose the fallback chain
  `portrait(c) || sigil(c)`, so an uncommissioned coach renders exactly as today.

  Deterministic by construction: the SVG is a pure function of (recipe, coach id,
  opts) — same inputs, byte-identical output, mirroring the sigils.js bar. All
  contours stroke currentColor (ink); the ONE accent layer (`hatch`) rides
  var(--coach) via CSS (.pt-hatch, tokens.css §13) — the same sanctioned persona
  colour channel as the sigils. Animation is CSS-only and fail-open: draw-in
  reuses sigilDraw, blink period is seeded per coach (FNV-1a → 4–8s, inline
  --pt-blink), breath is a 4.5s micro-translate; `prefers-reduced-motion` gets
  the full static portrait (eyes-open visible via inline attrs, not JS).
*/
import { fnv1a, mulberry32, seedOf } from "/assets/js/sigils.js";
import { PORTRAITS } from "/assets/js/portrait_data.js";

const escAttr = (s) => String(s == null ? "" : s).replace(/"/g, "&quot;").replace(/</g, "&lt;");
const r2 = (n) => Math.round(n * 100) / 100;

// Draw order (background → foreground). `frame` composes first (behind the bust),
// `hatch` (the coach-colour shading) sits under the ink contours.
const DRAW_ORDER = [
  "hatch", "bust", "head", "hair", "brow",
  "eyes-closed", "eyes-open", "glasses", "nose",
  "mouth-rest", "mouth-a", "mouth-b",
];

// Layers hidden at rest via INLINE opacity (fail-open static correctness: with no
// CSS at all the portrait still reads right). CSS animations outrank inline styles
// while running, so the blink can still drive eyes-closed visible.
const HIDDEN_AT_REST = { "eyes-closed": true, "mouth-a": true, "mouth-b": true };

const STROKE = 'fill="none" stroke="currentColor" stroke-width="1.7" ' +
  'stroke-linecap="round" stroke-linejoin="round" vector-effect="non-scaling-stroke"';

// Colour tones a recipe's palette may define (fixed order → deterministic output).
// `accent` defaults to the coach identity channel when the palette omits it.
export const TONES = ["skin", "hair", "cloth", "accent", "blush", "line"];

function pathEl(el) {
  if (el.tone) return `<path d="${escAttr(el.d)}" fill="var(--pt-${escAttr(el.tone)})" stroke="none"/>`;
  if (el.filled) return `<path d="${escAttr(el.d)}" fill="currentColor" stroke="none"/>`;
  return `<path class="pt-stroke" d="${escAttr(el.d)}" ${STROKE} pathLength="1"/>`;
}

// The sigil-as-frame (§8.7): when the recipe has no `frame` layer of its own, a
// deterministic ring + measuring-ticks behind the head — the coach's instrument
// vocabulary carried into the portrait. Seeded exactly like sigil() so the frame
// is stable per coach forever. Centred on the head (50,46), r 42.
function seededFrame(seed) {
  const rnd = mulberry32(seed);
  const C = 50, CY = 46, R = 42;
  const tickN = [6, 8, 12][seed % 3];
  const rot = rnd() * 360;
  let out = `<circle class="pt-stroke" cx="${C}" cy="${CY}" r="${R}" ${STROKE} pathLength="1"/>`;
  for (let i = 0; i < tickN; i++) {
    const a = ((rot + (360 / tickN) * i) * Math.PI) / 180;
    const x1 = r2(C + (R - 5) * Math.cos(a)), y1 = r2(CY + (R - 5) * Math.sin(a));
    const x2 = r2(C + R * Math.cos(a)), y2 = r2(CY + R * Math.sin(a));
    out += `<line class="pt-stroke" x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="currentColor" stroke-width="1.7" vector-effect="non-scaling-stroke" pathLength="1"/>`;
  }
  return out;
}

/*
  renderPortrait(recipe, coach, opts) → SVG string. The pure renderer — no registry
  lookup, no sign-off gate. portrait() below is the gated public entry; this export
  exists for the unit/QA harness and the contact-sheet builder (#587), which must
  render candidate recipes that are deliberately NOT in the shipped bundle.
    title — accessible name; "" → decorative (aria-hidden). Default is the ADR-106
            disclosure convention: "Illustrated portrait of <name>, a fictional AI persona".
    cls   — extra classes on the root svg (e.g. "portrait-lg").
    size  — rendered px hint; the frame composes only at ≥ 40 (below that it's noise).
*/
export function renderPortrait(recipe, coach, { title, cls = "", size } = {}) {
  if (!recipe || !recipe.layers || !recipe.layers.head) return null;
  const id = String(recipe.persona_id || seedOf(coach));
  const seed = fnv1a(id);
  const blink = r2(4 + (seed % 4001) / 1000); // 4.00–8.00s, deterministic per coach

  const withFrame = size == null || size >= 40;
  let body = "";
  if (withFrame) {
    body += `<g class="pt-l pt-frame" data-l="frame">` +
      (recipe.layers.frame ? recipe.layers.frame.map(pathEl).join("") : seededFrame(seed)) +
      `</g>`;
  }
  let inner = "";
  for (const lid of DRAW_ORDER) {
    const elems = recipe.layers[lid];
    if (!elems || !elems.length) continue;
    const hide = HIDDEN_AT_REST[lid] ? ' style="opacity:0"' : "";
    inner += `<g class="pt-l pt-${lid}" data-l="${lid}"${hide}>${elems.map(pathEl).join("")}</g>`;
  }
  body += `<g class="pt-breath">${inner}</g>`;

  const name = (coach && coach.name) || recipe.persona_id || "coach";
  const a11y = title === ""
    ? 'aria-hidden="true" focusable="false"'
    : `role="img" aria-label="${escAttr(title || `Illustrated portrait of ${name}, a fictional AI persona`)}"`;
  // Palette → inline custom props, fixed TONES order so output stays byte-deterministic.
  const pal = recipe.palette || {};
  let vars = `--pt-blink:${blink}s`;
  for (const t of TONES) {
    if (pal[t]) vars += `;--pt-${t}:${escAttr(pal[t])}`;
    else if (t === "accent") vars += `;--pt-accent:var(--coach, currentColor)`;
  }
  return `<svg class="portrait${cls ? " " + escAttr(cls) : ""}" viewBox="0 0 100 120" style="${vars}" ${a11y}>${body}</svg>`;
}

/*
  portrait(coach, opts) → SVG string or null. The public entry, mirroring the
  sigil() contract. Null when the coach has no signed recipe in the bundle — the
  caller's `|| sigil(coach)` keeps today's rendering, pixel-identical.
*/
export function portrait(coach, opts = {}) {
  const recipe = PORTRAITS[seedOf(coach)];
  return recipe ? renderPortrait(recipe, coach, opts) : null;
}
