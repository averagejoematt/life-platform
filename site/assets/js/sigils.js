/*
  sigils.js — a deterministic generative mark per coach (zero deps). Same coach →
  byte-identical SVG, forever: the geometry is seeded from the coach's stable id
  (FNV-1a → mulberry32), never from random state. The vocabulary is instrument
  geometry — concentric rings, radial measuring-ticks, orbital nodes — NOT an
  avatar. Colour rides the existing per-coach --coach channel (.sigil in tokens.css
  §13), the one sanctioned persona-identity exception to the single-ember rule.
  Static SVG: always visible, reduced-motion-safe, light/dark via currentColor.
*/
const escAttr = (s) => String(s == null ? "" : s).replace(/"/g, "&quot;").replace(/</g, "&lt;");

// FNV-1a (32-bit) — a stable string hash. Deterministic across browsers/runs.
function fnv1a(str) {
  let h = 0x811c9dc5;
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return h >>> 0;
}

// mulberry32 — a tiny seeded PRNG. Pure function of the seed.
function mulberry32(seed) {
  let a = seed >>> 0;
  return function () {
    a |= 0; a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// The stable seed string for a coach — prefers the most canonical id available.
function seedOf(coach) {
  if (!coach) return "coach";
  return String(
    coach.persona_id || coach.coach_id || coach.id || coach.short_id || coach.name || "coach"
  );
}

const r2 = (n) => Math.round(n * 100) / 100;          // 2dp → stable output
const pt = (cx, cy, r, deg) => {
  const a = (deg * Math.PI) / 180;
  return [r2(cx + r * Math.cos(a)), r2(cy + r * Math.sin(a))];
};

/*
  sigil(coach, opts) → SVG string (viewBox 0 0 100 100, centred at 50,50).
    title — accessible name (default "<name> mark"); pass "" for a decorative mark.
    cls   — extra classes on the root <svg>.
  Wrap in an element that sets `--coach` (the coach badge already does) to colour it.
*/
export function sigil(coach, { title, cls = "" } = {}) {
  const seed = fnv1a(seedOf(coach));
  const rnd = mulberry32(seed);
  const C = 50;

  const rings = 1 + (seed % 2);                        // 1–2 concentric rings
  const tickN = [6, 8, 12][seed % 3];                  // radial measuring-ticks
  const nodeN = 2 + Math.floor(rnd() * 3);             // 2–4 orbital nodes
  const rot = rnd() * 360;                             // base rotation
  const hasCore = rnd() > 0.45;                        // sometimes a centre dot

  const outerR = 40;
  const innerR = 27;
  const SW = `stroke-width="1.7" vector-effect="non-scaling-stroke"`;

  let body = `<circle class="sigil-ring" cx="${C}" cy="${C}" r="${outerR}" fill="none" stroke="currentColor" ${SW}/>`;
  if (rings === 2) {
    body += `<circle class="sigil-ring" cx="${C}" cy="${C}" r="${innerR}" fill="none" stroke="currentColor" ${SW}/>`;
  }

  // Radial measuring-ticks just inside the outer ring.
  for (let i = 0; i < tickN; i++) {
    const a = rot + (360 / tickN) * i;
    const [x1, y1] = pt(C, C, outerR - 5, a);
    const [x2, y2] = pt(C, C, outerR, a);
    body += `<line class="sigil-tick" x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="currentColor" ${SW}/>`;
  }

  // Orbital nodes on a mid radius, at seeded angles, with a spoke to centre.
  const nodeR = rings === 2 ? innerR : outerR - 8;
  for (let i = 0; i < nodeN; i++) {
    const a = rnd() * 360;
    const [nx, ny] = pt(C, C, nodeR, a);
    const [sx, sy] = pt(C, C, hasCore ? 6 : 0, a);
    body += `<line class="sigil-tick" x1="${sx}" y1="${sy}" x2="${nx}" y2="${ny}" stroke="currentColor" ${SW}/>`;
    body += `<circle class="sigil-node" cx="${nx}" cy="${ny}" r="3.9"/>`;
  }

  if (hasCore) body += `<circle class="sigil-node" cx="${C}" cy="${C}" r="2.6"/>`;

  const name = coach && coach.name ? coach.name : "coach";
  const a11y = title === ""
    ? `aria-hidden="true" focusable="false"`
    : `role="img" aria-label="${escAttr(title || name + " mark")}"`;
  return `<svg class="sigil${cls ? " " + escAttr(cls) : ""}" viewBox="0 0 100 100" ${a11y}>${body}</svg>`;
}
