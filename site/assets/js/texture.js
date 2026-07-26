/*
  texture.js — the editorial texture layer for narrative surfaces (#1471).

  Code-drawn art for the places readers linger: the story hub, chronicle
  installment headers, and season (attempt/cycle) banners. NOT a new vocabulary:
  this module imports the SAME identity machinery sigils.js exports (FNV-1a →
  mulberry32 — one hash vocabulary across sigils, portraits, and texture,
  DESIGN_SYSTEM_V5 §8.5/§8.8) and draws only instrument geometry — rule lines,
  measuring graduations, orbital nodes — with the .sigil-ring/-tick/-node
  stroke grammar, so the tokens.css §13 draw-in and reduced-motion behaviour
  apply unchanged. No stock imagery, no runtime AI generation, no random state:
  the geometry is a pure function of the seed — same seed → byte-identical SVG,
  forever. The one EMPHASIZED element (the counted beads) is data-derived — a
  real week or attempt number — per the "earned glow / no gloss" rule; the rest
  is quiet texture the host renders at low opacity and aria-hidden.
*/
// Absolute path so deploy/hash_site_assets.py rewrites this edge to the hashed
// filename (a relative "./" import would pin the unhashed URL — skew risk).
import { fnv1a, mulberry32 } from "/assets/js/sigils.js";

const escAttr = (s) => String(s == null ? "" : s).replace(/"/g, "&quot;").replace(/</g, "&lt;");
const r2 = (n) => Math.round(n * 100) / 100; // 2dp → stable output

// Shared stroke attrs — identical grammar to sigils.js: pathLength="1" so the
// CSS draw-in (tokens.css §13 sigilDraw) can animate dashoffset without
// measuring; non-scaling-stroke so the band survives responsive scaling.
const SW = (w) => `stroke="currentColor" pathLength="1" stroke-width="${w}" vector-effect="non-scaling-stroke"`;

/*
  ruleBand(seed, opts) → SVG string: a wide measuring-rule strip — the base
  texture of every narrative banner. A baseline, seeded graduations (the radial
  measuring-ticks of the sigils, flattened to a rule), and a few orbital nodes
  resting on the line like readings.
    emphasis — a REAL count (week number, attempt number): renders that many
               ember beads above the rule (capped at 24). 0/absent → none.
    cls      — extra classes on the root <svg>.
  Decorative by contract: aria-hidden, no <text> (nothing for the §10.5 SVG
  type floor to police). Wrap in an .art-band host to get the quiet styling.
*/
export function ruleBand(seed, { emphasis = 0, cls = "" } = {}) {
  const rnd = mulberry32(fnv1a(String(seed == null ? "band" : seed)));
  const W = 720, BASE = 20;
  let body = `<line class="sigil-ring" x1="0" y1="${BASE}" x2="${W}" y2="${BASE}" ${SW(1.2)}/>`;

  // Graduations: 49 marks across the rule; every 8th is a major tick, the rest
  // take seeded minor heights — a ruler that carries the seed's fingerprint.
  const N = 49, step = (W - 24) / (N - 1);
  for (let i = 0; i < N; i++) {
    const x = r2(12 + i * step);
    const h = i % 8 === 0 ? 12 : r2(4 + rnd() * 4);
    body += `<line class="sigil-tick" x1="${x}" y1="${BASE}" x2="${x}" y2="${r2(BASE - h)}" ${SW(1.2)}/>`;
  }

  // Orbital nodes resting on the rule — 2–4, seeded positions.
  const nodeN = 2 + Math.floor(rnd() * 3);
  for (let i = 0; i < nodeN; i++) {
    const x = r2(24 + rnd() * (W - 48));
    body += `<circle class="sigil-node" cx="${x}" cy="${BASE}" r="2.4"/>`;
  }

  // The earned beads — a real count, never decoration (§8.5). Capped so a long
  // record stays a texture, not a wall.
  const n = Number(emphasis);
  const beads = Number.isFinite(n) && n > 0 ? Math.min(Math.round(n), 24) : 0;
  for (let i = 0; i < beads; i++) {
    body += `<circle class="sigil-node art-count" cx="${r2(12 + i * 10)}" cy="7" r="2.1"/>`;
  }

  return `<svg class="art-tex${cls ? " " + escAttr(cls) : ""}" viewBox="0 0 ${W} 28" ` +
    `preserveAspectRatio="xMidYMid slice" aria-hidden="true" focusable="false">${body}</svg>`;
}

/*
  seasonBand(cycle, opts) → SVG string: the season banner — the rule band whose
  counted beads ARE the attempt number (cycle 10 renders ten beads; the mark
  literally counts the record). Seeded by the cycle by default; pass a richer
  seed (e.g. "attempt:<cycle>:<genesis>") to give each season its own stable
  fingerprint while keeping the count honest.
*/
export function seasonBand(cycle, { seed = null, cls = "" } = {}) {
  const n = Number(cycle);
  const ok = Number.isFinite(n) && n > 0;
  return ruleBand(seed != null ? seed : `season:${ok ? Math.round(n) : "?"}`, {
    emphasis: ok ? Math.round(n) : 0,
    cls,
  });
}
