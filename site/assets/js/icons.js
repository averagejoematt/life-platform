/*
  icons.js — the line-icon set (zero deps). Mirrors charts.js: returns an inline-SVG
  string that <use>s a <symbol> from the shared sprite at /assets/icons/icons.svg.
  The symbol carries stroke="currentColor", so an icon inherits its host's `color`
  (token-driven via .ico / .ico-door / .kicker-ico in tokens.css §Iconography).
  Decorative by default (aria-hidden); pass a title to make it a labelled image.
*/
const SPRITE = "/assets/icons/icons.svg";
const escAttr = (s) => String(s == null ? "" : s).replace(/"/g, "&quot;").replace(/</g, "&lt;");

// Known icon ids — a typo'd name renders nothing rather than a broken ref.
const KNOWN = new Set([
  "sleep", "training", "nutrition", "vitals", "glucose", "mind", "habits", "people",
  "reading",
  "door-cockpit", "door-data", "door-coaching", "door-protocols", "door-story",
  // interface + narrative marks (visual uplevel): the ask glyph, the milestone
  // flag, transport marks, and the two narrative-medium marks.
  "ask", "milestone", "play", "pause", "podcast", "chronicle",
  // the character sheet (figure-in-ring — echoes the /data/character/ hero)
  "character",
]);

/*
  icon(name, opts) → SVG string.
    size  — any CSS length (default "1em": tracks surrounding text). Use e.g. "18px" for fixed.
    cls   — extra classes (e.g. "ico-door", "kicker-ico").
    title — accessible name; when set the icon is role="img", else aria-hidden.
*/
export function icon(name, { size = "1em", cls = "", title = "" } = {}) {
  if (!KNOWN.has(name)) return "";
  const sized = size && size !== "1em" ? ` style="width:${escAttr(size)};height:${escAttr(size)}"` : "";
  const a11y = title
    ? `role="img" aria-label="${escAttr(title)}"`
    : `aria-hidden="true" focusable="false"`;
  return `<svg class="ico${cls ? " " + escAttr(cls) : ""}" viewBox="0 0 24 24" ${a11y}${sized}>` +
    `<use href="${SPRITE}#i-${escAttr(name)}"/></svg>`;
}

/*
  DOMAIN_ICON — maps the platform's several domain name-spaces to one icon id:
  the cockpit PILLAR keys (movement/metabolic/consistency/relationships), the
  /data/ route names, and the coach short_ids all resolve here. Unknown → "".
*/
export const DOMAIN_ICON = {
  // sleep
  sleep: "sleep",
  // training / movement
  training: "training", movement: "training", exercise: "training", strength: "training",
  // nutrition
  nutrition: "nutrition",
  // vitals / recovery
  vitals: "vitals", recovery: "vitals", body: "vitals", physical: "vitals",
  // glucose / metabolic
  glucose: "glucose", metabolic: "glucose", cgm: "glucose",
  // mind
  mind: "mind", mood: "mind", reading: "reading", books: "reading",
  // habits / consistency
  habits: "habits", consistency: "habits",
  // relationships / social
  relationships: "people", social: "people", people: "people",
  // the character sheet
  character: "character", tier: "character",
  // the badge wall (#1126) — the milestone flag is the mark for "earned"
  badges: "milestone",
};

// domainIcon(key, opts) — convenience: resolve a domain name-space key to its icon.
export function domainIcon(key, opts = {}) {
  const id = DOMAIN_ICON[String(key || "").toLowerCase()];
  return id ? icon(id, opts) : "";
}
