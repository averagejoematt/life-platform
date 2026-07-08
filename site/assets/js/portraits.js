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

  Semantic states (#594) — `data-portrait-state` on the root <svg>, ambient CSS
  in tokens.css §Coach-portraits, all inside the same reduced-motion guard:
    - "writing"      — passed as a render opt (opts.state), pure CSS, no JS.
    - "speaking"      — wireSpeakingAudio() below drives the mouth-rest/mouth-a
      toggle from a Panel-page <audio> element's play/pause/ended. Only
      mouth-rest + mouth-a exist in ANY commissioned recipe (config/portraits/
      *.json never got a third "mouth-b" frame) — this toggles the two real
      ones, it never fabricates a third shape.
    - "stance-change" — markStanceChange() below detects (client-side, via
      localStorage) that a coach's stance_history grew, and sets the attribute
      for exactly one non-looping CSS sweep, then clears it.
  Every JS entry point here re-checks prefers-reduced-motion itself (a CSS
  @media guard alone cannot stop a running setInterval).
*/
import { fnv1a, mulberry32, seedOf } from "/assets/js/sigils.js";
import { PORTRAITS, ALIASES } from "/assets/js/portrait_data.js";

const reducedMotion = () => {
  try { return window.matchMedia("(prefers-reduced-motion: reduce)").matches; }
  catch (e) { return true; } // no matchMedia (very old/non-browser env) — fail toward NOT starting motion
};

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
export function renderPortrait(recipe, coach, { title, cls = "", size, state } = {}) {
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
  const stateAttr = state ? ` data-portrait-state="${escAttr(state)}"` : "";
  return `<svg class="portrait${cls ? " " + escAttr(cls) : ""}" viewBox="0 0 100 120" style="${vars}" ${a11y}${stateAttr}>${body}</svg>`;
}

/*
  portrait(coach, opts) → SVG string or null. The public entry, mirroring the
  sigil() contract. Null when the coach has no signed recipe in the bundle — the
  caller's `|| sigil(coach)` keeps today's rendering, pixel-identical.
*/
export function portrait(coach, opts = {}) {
  const key = seedOf(coach);
  const recipe = PORTRAITS[key] || PORTRAITS[ALIASES[key]];
  return recipe ? renderPortrait(recipe, coach, opts) : null;
}

/*
  wireSpeakingAudio(audioEl, portraitEls) — the Panel page's "speaking" state
  (#594). Toggles each portrait's mouth-rest/mouth-a layers (the only two real
  mouth frames any recipe has — see the file header) at a ~180ms cadence for as
  long as `audioEl` is actually playing, and sets/clears `data-portrait-state`
  in step (tokens.css supplies the accompanying ring-pulse, keyed to the SAME
  attribute — no separate CSS trigger to keep in sync). `portraitEls` should be
  ONLY the portrait(s) credited on that one episode (e.g. Elena + the guest
  coach) — never every portrait on the page.
*/
function setMouthFrame(portraitEl, showAlt) {
  const rest = portraitEl.querySelector('[data-l="mouth-rest"]');
  const alt = portraitEl.querySelector('[data-l="mouth-a"]');
  if (rest) rest.style.opacity = showAlt ? "0" : "1";
  if (alt) alt.style.opacity = showAlt ? "1" : "0";
}
const _speakingTimers = new WeakMap();
export function wireSpeakingAudio(audioEl, portraitEls) {
  const els = (portraitEls || []).filter(Boolean);
  if (!audioEl || !els.length) return;
  const stop = () => {
    const t = _speakingTimers.get(audioEl);
    if (t != null) { clearInterval(t); _speakingTimers.delete(audioEl); }
    els.forEach((el) => { el.removeAttribute("data-portrait-state"); setMouthFrame(el, false); });
  };
  const start = () => {
    // JS-side reduced-motion check: a CSS @media guard alone can't stop this
    // setInterval from running, so the interval itself must never be created.
    if (reducedMotion() || _speakingTimers.has(audioEl)) return;
    let alt = false;
    els.forEach((el) => el.setAttribute("data-portrait-state", "speaking"));
    const timer = setInterval(() => {
      alt = !alt;
      els.forEach((el) => setMouthFrame(el, alt));
    }, 180);
    _speakingTimers.set(audioEl, timer);
  };
  audioEl.addEventListener("play", start);
  audioEl.addEventListener("pause", stop);
  audioEl.addEventListener("ended", stop);
}

/*
  markStanceChange(portraitEl, coachId, stanceHistory) — the "stance-change"
  state (#594): a ONE-TIME, non-looping re-draw sweep when a coach's
  stance_history gains an entry ("the instrument recalibrating"). Detected
  client-side by diffing (length, newest `as_of`) against the last-seen value
  for that coach, persisted in localStorage — the same fail-soft
  seen/dismissed-once pattern already used elsewhere on the site (e.g.
  cockpit.js's level-up ribbon, evidence.js's intro card), chosen over
  sessionStorage so a reader who comes back a day later — after the stance
  really did change while they were away — still sees the sweep once.
  Never fires on the very first time a coach's history is observed at all
  (nothing to compare against yet — that's not a "change").
*/
const STANCE_SEEN_KEY = "ajm-portrait-stance-seen";
function readStanceSeen() {
  try { return JSON.parse(localStorage.getItem(STANCE_SEEN_KEY) || "{}"); }
  catch (e) { return {}; }
}
function writeStanceSeen(map) {
  try { localStorage.setItem(STANCE_SEEN_KEY, JSON.stringify(map)); }
  catch (e) { /* private mode / quota — fail quiet, just re-checks every visit */ }
}
export function markStanceChange(portraitEl, coachId, stanceHistory) {
  if (!portraitEl || !coachId || reducedMotion()) return;
  const hist = Array.isArray(stanceHistory) ? stanceHistory : [];
  if (!hist.length) return;
  const latest = String((hist[0] && hist[0].as_of) || "");
  const fingerprint = `${hist.length}:${latest}`;
  const seen = readStanceSeen();
  const prior = seen[coachId];
  if (prior === fingerprint) return; // nothing new since we last recorded this coach
  seen[coachId] = fingerprint;
  writeStanceSeen(seen);
  if (prior === undefined) return; // first-ever observation of this coach — nothing "changed" yet
  portraitEl.setAttribute("data-portrait-state", "stance-change");
  const clear = () => portraitEl.removeAttribute("data-portrait-state");
  portraitEl.addEventListener("animationend", clear, { once: true });
  setTimeout(clear, 1500); // belt-and-braces (backgrounded tab, animationend can be throttled/skipped)
}
