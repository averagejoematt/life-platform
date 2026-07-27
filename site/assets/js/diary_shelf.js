/*
  diary_shelf.js — the consent-gated diary shelf (#1846, /story/diary/)

  One card per diary entry Matthew cleared for publication: the day-mark (the
  same daily fingerprint the cockpit masthead and the studio HUD render — one
  visual system), the date, the cycle + day number, the format, the measured
  duration, the coarse theme, and ONLY the lines he marked publishable.

  Honesty contract — the client renders exactly what the server gives it and
  never invents a state:
    · An unconsented entry never arrives here at all. There is no redacted card,
      no ghost row, no lock icon — it is simply absent (AC1). What the reader
      DOES get is an honest count of how many entries are held back, so the
      shelf never implies the diary is only what you can see.
    · Absence is absence (ADR-104). No duration ⇒ no duration shown, never
      "0:00". No entries ⇒ a quiet page, never padded with placeholders.
    · Every renderer returns "" for empty input, so a dead payload collapses
      the block instead of scaffolding an empty shell.
*/

/* The coarse public theme vocabulary — mirrors lambdas/diary_consent.py's
   8-way laundered categories exactly (the server never sends a raw enrichment
   tag). "other" renders as no theme at all, matching the tier's granularity. */
const THEME_COPY = {
  anxiety_stress: "stress and worry",
  health_body: "the body — training, sleep, food",
  relationships: "relationships",
  work_ambition: "work and ambition",
  gratitude: "gratitude",
  personal_growth: "habits and growth",
  reflection: "reflection",
  other: "",
};

const MONTHS = ["January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December"];

export function esc(s) {
  return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

export function human(dateStr) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(dateStr || ""));
  if (!m) return "";
  return `${MONTHS[Number(m[2]) - 1]} ${Number(m[3])}, ${m[1]}`;
}

/* "Day 12 · cycle 11" — or just the cycle when the day number is unknown, or
   nothing at all for an entry recorded before the first cycle began. Never
   fabricates a Day 1 for a pre-genesis date (the #1824 lesson). */
export function stampHTML(entry) {
  const bits = [];
  if (entry.day_number != null) bits.push(`Day ${esc(entry.day_number)}`);
  if (entry.cycle != null) bits.push(`cycle ${esc(entry.cycle)}`);
  if (!bits.length) return "";
  return `<p class="dsh-stamp label">${bits.join(" &middot; ")}</p>`;
}

/* The measured line: date · format · duration. Duration is included ONLY when
   the payload carries one (it is computed from the session's transcript, so an
   entry with no transcript honestly has none). */
export function metaLine(entry) {
  // `format` is the reader-facing label the server sends; falling back to the raw
  // `channel` key would print an enum ("SOLO_RECORDING") at a reader, so the
  // fallback de-snakes it. Unreachable today — reachable the day a fourth channel
  // lands or a cached older payload shape is served.
  const bits = [human(entry.date), entry.format || String(entry.channel || "").replace(/_/g, " ")];
  if (entry.duration && entry.duration.label) bits.push(entry.duration.label);
  return bits.filter(Boolean).map(esc).join(" &middot; ");
}

export function quotesHTML(entry) {
  const quotes = Array.isArray(entry.quotes) ? entry.quotes : [];
  const cards = quotes
    .filter((q) => q && String(q.quote || "").trim())
    .map((q) => `<blockquote class="dsh-quote">&ldquo;${esc(q.quote)}&rdquo;</blockquote>`)
    .join("");
  const held = Number(entry.quotes_withheld || 0);
  const heldLine = held
    ? `<p class="dsh-held label">${held} more line${held === 1 ? "" : "s"} from this entry stayed private.</p>`
    : "";
  // No marked lines at all: say so plainly rather than leaving a silent gap —
  // the card is the entry's receipt, the quotes are a separate consent.
  const none = cards ? "" : `<p class="dsh-held label">No lines from this entry were marked for publication.</p>`;
  return cards + none + heldLine;
}

/* On-tape forecasts (#1841). Claims are private by default and grade privately;
   only an explicitly public-marked claim carries text. The count is disclosed
   either way — that he put N forecasts on the record is the signal. */
export function claimsHTML(entry) {
  const claims = Array.isArray(entry.claims) ? entry.claims : [];
  const total = Number(entry.claims_on_record || 0);
  if (!total) return "";
  const listed = claims
    .filter((c) => c && c.claim_natural)
    .map((c) => `<li class="dsh-claim">${esc(c.claim_natural)}` +
      (c.grade_by ? ` <span class="label">&mdash; called by ${esc(c.grade_by)}</span>` : "") + `</li>`)
    .join("");
  const list = listed ? `<ul class="dsh-claims">${listed}</ul>` : "";
  const held = total - claims.filter((c) => c && c.claim_natural).length;
  const heldLine = held > 0
    ? `<p class="dsh-held label">${held} forecast${held === 1 ? "" : "s"} on the record from this entry, graded privately.</p>`
    : "";
  return list + heldLine;
}

export function cardHTML(entry) {
  if (!entry || !entry.date) return "";
  const theme = THEME_COPY[entry.theme] || "";
  const mark = entry.day_mark && entry.day_mark.svg ? entry.day_mark.svg : "";
  return (
    `<li class="dsh-card">` +
    `<div class="dsh-mark" aria-hidden="${mark ? "false" : "true"}">${mark}</div>` +
    `<div class="dsh-body">` +
    stampHTML(entry) +
    `<p class="dsh-meta label">${metaLine(entry)}</p>` +
    (theme ? `<p class="dsh-theme">On his mind: ${esc(theme)}.</p>` : "") +
    quotesHTML(entry) +
    claimsHTML(entry) +
    `<p class="dsh-receipts label"><a href="/cockpit/?date=${encodeURIComponent(entry.date)}">that day&rsquo;s data &rarr;</a></p>` +
    `</div></li>`
  );
}

/* The whole shelf. An empty shelf is a real, reportable state — a quiet week
   renders as quiet, and the withheld count is stated rather than implied. */
export function shelfHTML(payload) {
  const shelf = (payload && payload.shelf) || null;
  if (!shelf) return "";
  const entries = Array.isArray(shelf.entries) ? shelf.entries : [];
  const withheld = Number(shelf.withheld || 0);
  const cards = entries.map(cardHTML).filter(Boolean).join("");

  if (!cards) {
    const line = withheld
      ? `${withheld} diary entr${withheld === 1 ? "y is" : "ies are"} recorded and none are published yet.`
      : `No diary entries have been published yet.`;
    // The standing policy sentence is the SERVER's copy (shelf.note) — one source
    // for the honesty statement, so editing it in the handler actually changes
    // the page. The literal is only a fallback for a payload without one.
    const note = String(shelf.note || "Nothing here publishes by default.");
    return `<p class="dsh-empty dx-prose">${esc(line)} ${esc(note)}</p>`;
  }

  const foot = withheld
    ? `<p class="dsh-foot label">${withheld} more entr${withheld === 1 ? "y" : "ies"} ` +
      `${withheld === 1 ? "is" : "are"} recorded and not published.</p>`
    : "";
  return `<ul class="dsh-shelf">${cards}</ul>` + foot;
}

async function getJSON(path) {
  try {
    const r = await fetch(path, { headers: { accept: "application/json" } });
    return r.ok ? await r.json() : null;
  } catch { return null; }
}

export async function boot(doc) {
  const d = doc || (typeof document !== "undefined" ? document : null);
  if (!d) return;
  const mount = d.querySelector("[data-diary-shelf]");
  if (!mount) return;
  const payload = await getJSON("/api/diary_shelf");
  const html = shelfHTML(payload);
  mount.innerHTML = html ||
    `<p class="dsh-empty dx-prose">The shelf couldn&rsquo;t be read right now. It will be back with the next deploy.</p>`;
  mount.hidden = false;
}

if (typeof document !== "undefined") boot(document);
