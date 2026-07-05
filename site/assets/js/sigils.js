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
// Exported (with mulberry32/seedOf) so portraits.js seeds from the SAME identity
// machinery — one hash vocabulary across sigils and portraits (§8.7).
export function fnv1a(str) {
  let h = 0x811c9dc5;
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return h >>> 0;
}

// mulberry32 — a tiny seeded PRNG. Pure function of the seed.
export function mulberry32(seed) {
  let a = seed >>> 0;
  return function () {
    a |= 0; a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// The stable seed string for a coach — prefers the most canonical id available.
export function seedOf(coach) {
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

  // pathLength="1" normalizes each stroke so the CSS draw-in (tokens.css §13,
  // sigilDraw) can animate dashoffset 1→0 without measuring — self-contained,
  // runs on every injection, fail-open (reduced-motion media query skips it).
  let body = `<circle class="sigil-ring" cx="${C}" cy="${C}" r="${outerR}" fill="none" stroke="currentColor" pathLength="1" ${SW}/>`;
  if (rings === 2) {
    body += `<circle class="sigil-ring" cx="${C}" cy="${C}" r="${innerR}" fill="none" stroke="currentColor" pathLength="1" ${SW}/>`;
  }

  // Radial measuring-ticks just inside the outer ring.
  for (let i = 0; i < tickN; i++) {
    const a = rot + (360 / tickN) * i;
    const [x1, y1] = pt(C, C, outerR - 5, a);
    const [x2, y2] = pt(C, C, outerR, a);
    body += `<line class="sigil-tick" x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="currentColor" pathLength="1" ${SW}/>`;
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

// ── The instrument mark — the OG share-card's brand device (og_image_lambda.mjs
// instrumentMark), ported as a shared on-site export so the two stay ONE
// vocabulary (§8.5). currentColor; the ring/tick classes ride the same
// pathLength draw-in as the coach sigils. Use SPARINGLY — a faint marginal
// mark, never decoration-confetti.
export function instrumentMark({ cls = "" } = {}) {
  const C = 50, R = 40;
  let ticks = "";
  for (let i = 0; i < 12; i++) {
    const a = (Math.PI / 6) * i;
    const x1 = C + (R - 7) * Math.cos(a), y1 = C + (R - 7) * Math.sin(a);
    const x2 = C + R * Math.cos(a), y2 = C + R * Math.sin(a);
    ticks += `<line class="sigil-tick" x1="${r2(x1)}" y1="${r2(y1)}" x2="${r2(x2)}" y2="${r2(y2)}" stroke="currentColor" pathLength="1" stroke-width="1.7" vector-effect="non-scaling-stroke"/>`;
  }
  const nx = C + (R - 14) * Math.cos(-0.9), ny = C + (R - 14) * Math.sin(-0.9);
  return `<svg class="sigil imark${cls ? " " + escAttr(cls) : ""}" viewBox="0 0 100 100" aria-hidden="true" focusable="false">` +
    `<circle class="sigil-ring" cx="${C}" cy="${C}" r="${R}" fill="none" stroke="currentColor" pathLength="1" stroke-width="1.7" vector-effect="non-scaling-stroke"/>` +
    `<circle class="sigil-ring" cx="${C}" cy="${C}" r="${R - 14}" fill="none" stroke="currentColor" pathLength="1" stroke-width="1.7" vector-effect="non-scaling-stroke"/>` +
    ticks +
    `<circle class="sigil-node" cx="${r2(nx)}" cy="${r2(ny)}" r="4" fill="currentColor"/>` +
    `<circle class="sigil-node" cx="${C}" cy="${C}" r="3" fill="currentColor"/></svg>`;
}

// ── The tier emblem — the character sheet's identity device, resurrected from
// the legacy page (site/legacy/character/index.html tierEmblem) and redrawn to
// §8: stroke-only, currentColor (host sets color: var(--tier-accent)), NO
// gradient fills — the tier is earned, not gloss. The shape evolves with the
// tier: hexagon → flame-arc hexagon → shield → crowned shield → crown + shield.
// Rings ride the shared pathLength draw-in. `level` renders inside.
export function tierEmblem(tier, level, { cls = "" } = {}) {
  const t = String(tier || "foundation").toLowerCase();
  // level=null → a bare glyph (ladder rungs); a number → the identity device.
  const lvl = level != null && Number.isFinite(Number(level)) ? Math.round(Number(level)) : null;
  const S = `fill="none" stroke="currentColor" pathLength="1" vector-effect="non-scaling-stroke"`;
  const num = (y) => (lvl == null ? "" :
    `<text x="55" y="${y}" text-anchor="middle" font-family="IBM Plex Mono,ui-monospace,monospace" font-size="34" font-weight="500" fill="currentColor">${lvl}</text>` +
    `<text x="55" y="${y + 18}" text-anchor="middle" font-family="IBM Plex Mono,ui-monospace,monospace" font-size="8" fill="currentColor" opacity="0.6" letter-spacing="2.4">LEVEL</text>`);
  let body;
  if (t === "momentum") {
    body =
      `<polygon class="sigil-ring" points="55,4 102,28 102,76 55,100 8,76 8,28" ${S} stroke-width="2"/>` +
      `<polygon class="sigil-ring" points="55,14 92,34 92,70 55,90 18,70 18,34" ${S} stroke-width="1" opacity="0.5"/>` +
      `<path class="sigil-tick" d="M40,8 Q55,-6 70,8" ${S} stroke-width="2" opacity="0.6"/>` + num(60);
  } else if (t === "discipline") {
    body =
      `<path class="sigil-ring" d="M55,4 L100,20 L100,65 Q100,95 55,112 Q10,95 10,65 L10,20 Z" ${S} stroke-width="2"/>` +
      `<path class="sigil-ring" d="M55,16 L90,28 L90,62 Q90,86 55,100 Q20,86 20,62 L20,28 Z" ${S} stroke-width="0.8" opacity="0.3"/>` + num(62);
  } else if (t === "mastery") {
    body =
      `<path class="sigil-ring" d="M55,4 L100,20 L100,65 Q100,95 55,112 Q10,95 10,65 L10,20 Z" ${S} stroke-width="2.4"/>` +
      `<path class="sigil-tick" d="M30,4 L40,14 L55,4 L70,14 L80,4" ${S} stroke-width="1.5" opacity="0.7"/>` + num(62);
  } else if (t === "elite") {
    body =
      `<path class="sigil-ring" d="M55,18 L100,32 L100,70 Q100,98 55,114 Q10,98 10,70 L10,32 Z" ${S} stroke-width="2.6"/>` +
      `<path class="sigil-tick" d="M20,14 L35,2 L55,14 L75,2 L90,14 L82,18 L55,6 L28,18 Z" ${S} stroke-width="2"/>` +
      `<circle class="sigil-node" cx="35" cy="4" r="3" fill="currentColor"/><circle class="sigil-node" cx="55" cy="10" r="3" fill="currentColor"/><circle class="sigil-node" cx="75" cy="4" r="3" fill="currentColor"/>` + num(70);
  } else {
    // foundation
    body =
      `<polygon class="sigil-ring" points="55,4 102,28 102,76 55,100 8,76 8,28" ${S} stroke-width="1.5" opacity="0.4"/>` +
      `<polygon class="sigil-ring" points="55,14 92,34 92,70 55,90 18,70 18,34" ${S} stroke-width="1"/>` + num(60);
  }
  const a11y = lvl == null
    ? `aria-hidden="true" focusable="false"`
    : `role="img" aria-label="${escAttr(`Level ${lvl} · ${tier || "Foundation"} tier emblem`)}"`;
  return `<svg class="sigil emblem${cls ? " " + escAttr(cls) : ""}" viewBox="0 0 110 120" ${a11y}>${body}</svg>`;
}

// ── The badge mark — a deterministic geometric mark per achievement (character
// sheet P1.3). Same machinery as the coach sigils (FNV-1a → mulberry32): same
// badge id → byte-identical mark, forever, and any FUTURE badge gets a mark for
// free — self-perpetuating, no asset to draw (§8.2/§8.5). Instrument vocabulary
// only: ring or hexagon frame, radial ticks, an inner polygon, a node. Earned
// state is the host's concern (CSS mutes the unearned wall).
export function badgeMark(id, { earned = false, cls = "" } = {}) {
  const rng = mulberry32(fnv1a(String(id || "badge")));
  const C = 50;
  const S = `fill="none" stroke="currentColor" pathLength="1" vector-effect="non-scaling-stroke"`;
  // frame: circle | hexagon | square-diamond — hash-picked
  const frame = Math.floor(rng() * 3);
  let out = "";
  if (frame === 0) {
    out += `<circle class="sigil-ring" cx="${C}" cy="${C}" r="40" ${S} stroke-width="1.7"/>`;
  } else if (frame === 1) {
    const hex = Array.from({ length: 6 }, (_, i) => pt(C, C, 40, i * 60 - 90).join(",")).join(" ");
    out += `<polygon class="sigil-ring" points="${hex}" ${S} stroke-width="1.7"/>`;
  } else {
    const dia = [0, 90, 180, 270].map((d) => pt(C, C, 42, d - 45).join(",")).join(" ");
    out += `<polygon class="sigil-ring" points="${dia}" ${S} stroke-width="1.7"/>`;
  }
  // radial ticks — count + phase from the hash
  const n = 4 + Math.floor(rng() * 5);
  const phase = rng() * 360;
  for (let i = 0; i < n; i++) {
    const a = phase + (i * 360) / n;
    const [x1, y1] = pt(C, C, 30, a);
    const [x2, y2] = pt(C, C, 36, a);
    out += `<line class="sigil-tick" x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="currentColor" pathLength="1" stroke-width="1.5" vector-effect="non-scaling-stroke"/>`;
  }
  // inner motif: a small polygon (3-6 sides) rotated by the hash
  const sides = 3 + Math.floor(rng() * 4);
  const rot = rng() * 360;
  const poly = Array.from({ length: sides }, (_, i) => pt(C, C, 16, rot + (i * 360) / sides).join(",")).join(" ");
  out += `<polygon class="sigil-tick" points="${poly}" ${S} stroke-width="1.4"/>`;
  // the node — filled when earned, the mark's "lit" state
  out += earned
    ? `<circle class="sigil-node" cx="${C}" cy="${C}" r="4.5" fill="currentColor"/>`
    : `<circle class="sigil-ring" cx="${C}" cy="${C}" r="4.5" ${S} stroke-width="1.4"/>`;
  return `<svg class="sigil badge-mark${cls ? " " + escAttr(cls) : ""}" viewBox="0 0 100 100" aria-hidden="true" focusable="false">${out}</svg>`;
}
