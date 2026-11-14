// Dates in words, numbers with tabular figures. Pure; proven in tests/format.test.mjs.
// Every date on a reader surface is written in words (the kit gate's rule: an ISO date on
// a page is a defect), and every count is plain.

const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
const DAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];

/** "2026-10-31" -> "31 October 2026" (or "31 Oct" with {short:true}; weekday with {weekday:true}). */
export function dayInWords(iso, opts = {}) {
  if (!iso || !/^\d{4}-\d{2}-\d{2}/.test(iso)) return null;
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d));
  const month = opts.short ? MONTHS[m - 1].slice(0, 3) : MONTHS[m - 1];
  const core = opts.short ? `${d} ${month}` : `${d} ${month} ${y}`;
  return opts.weekday ? `${DAYS[dt.getUTCDay()]} ${core}` : core;
}

const ISO_DAY_RE = /^\d{4}-\d{2}-\d{2}$/;
const dayMs = (iso) => Date.parse(`${iso}T00:00:00Z`);

/** Two days as one range in words: "4 to 10 November" (the year when {year:true}), "30 September to 6 October",
 * "29 December 2026 to 4 January 2027"; {short:true} gives "4–10 Nov". null unless both are ISO days, in order. */
export function rangeInWords(a, b, opts = {}) {
  if (!ISO_DAY_RE.test(a || "") || !ISO_DAY_RE.test(b || "") || a > b) return null;
  const [ya, ma] = a.split("-").map(Number);
  const [yb, mb] = b.split("-").map(Number);
  const da = Number(a.slice(8));
  const db = Number(b.slice(8));
  const month = (m) => (opts.short ? MONTHS[m - 1].slice(0, 3) : MONTHS[m - 1]);
  const year = opts.year && !opts.short ? ` ${yb}` : "";
  if (ya !== yb) return opts.short ? `${dayInWords(a, { short: true })} – ${dayInWords(b, { short: true })}` : `${dayInWords(a)} to ${dayInWords(b)}`;
  if (a === b) return `${da} ${month(ma)}${year}`;
  if (ma === mb) return opts.short ? `${da}–${db} ${month(mb)}` : `${da} to ${db} ${month(mb)}${year}`;
  return opts.short ? `${da} ${month(ma)} – ${db} ${month(mb)}` : `${da} ${month(ma)} to ${db} ${month(mb)}${year}`;
}

/** A published chapter's covered days (`covers_start`..`covers_end`, its own "Day A to Day B" stats line) in words:
 * "Days 60–66 · 4 to 10 November". The day numbers count from genesis, which is the chapter's own program-week start
 * less 7·(week−1) (the exporter's explicit interval). null when the snapshot carries no covered days — the caller then
 * shows the program week (`week_start`..`week_end`), never a span inferred from `date`. */
export function chapterCovers(c, opts = {}) {
  if (!c || !ISO_DAY_RE.test(c.covers_start || "") || !ISO_DAY_RE.test(c.covers_end || "")) return null;
  const range = rangeInWords(c.covers_start, c.covers_end, opts);
  if (!range) return null;
  const genesis = ISO_DAY_RE.test(c.week_start || "") && Number.isInteger(c.week) && c.week >= 1 ? dayMs(c.week_start) - 7 * (c.week - 1) * 864e5 : null;
  if (genesis == null) return range;
  const n = (iso) => Math.round((dayMs(iso) - genesis) / 864e5) + 1;
  const [a, b] = [n(c.covers_start), n(c.covers_end)];
  if (a < 1) return range;
  return `${a === b ? `Day ${a}` : `Days ${a}–${b}`} · ${range}`;
}

/** The days a chapter's week-scoped lists read: the covered days when served, else the program week. */
export function chapterWindow(c) {
  if (c && ISO_DAY_RE.test(c.covers_start || "") && ISO_DAY_RE.test(c.covers_end || "") && c.covers_start <= c.covers_end) return [c.covers_start, c.covers_end];
  if (c && ISO_DAY_RE.test(c.week_start || "") && ISO_DAY_RE.test(c.week_end || "")) return [c.week_start, c.week_end];
  return null;
}

/** When a published chapter was published, in words: "Published 13 November 2026" from the owner's approval day
 * (`published_at`). When that is not served the chapter's `date` is a DATA date, so it is never called the publication:
 * "Data through 10 November 2026" ({lower:true} for a mid-line form). null for an unpublished week. */
export function chapterPublished(c, opts = {}) {
  if (!c || c.status !== "published") return null;
  const lead = (w) => (opts.lower ? w.toLowerCase() : w);
  if (ISO_DAY_RE.test(c.published_at || "")) return `${lead("Published")} ${dayInWords(c.published_at)}`;
  const through = c.data_through || c.date;
  return ISO_DAY_RE.test(through || "") ? `${lead("Data through")} ${dayInWords(through)}` : null;
}

/** A number with a fixed number of decimals and en-GB grouping; null -> "—". */
export function num(v, decimals = 0) {
  if (v == null || Number.isNaN(Number(v))) return "—";
  return Number(v).toLocaleString("en-GB", { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}

/** "K of N" — the record as the site states it; a percentage never appears alone. */
export function kOfN(right, n) {
  if (n == null || n === 0) return "no checked call yet";
  if (right == null) return `${n} checked`;
  return `${right} of ${n} right`;
}

/** A call's OWN outcome in words — the one mapping every surface uses (the rail, the Journey, the Day, the
 * ledger, the coach pages). The simple guess's result is a different fact and never borrows these words: on
 * 2 November the rail printed the simple guess's "wrong" under a call the ledger graded right. The exporter's
 * `summary` for a prediction is this same word (scripts/publish_snapshot.py CALL_OUTCOME, pinned equal). */
export const CALL_OUTCOME = {
  confirmed: "right",
  refuted: "wrong",
  expired: "could not be checked",
  inconclusive: "inconclusive",
  pending: "open",
  observation: "not graded",
};
export function callOutcome(status) {
  return CALL_OUTCOME[status] || String(status || "");
}

/** Trim a claim for a row without cutting mid-word. */
export function clip(text, max = 90) {
  if (!text) return "";
  if (text.length <= max) return text;
  const cut = text.slice(0, max - 1);
  const sp = cut.lastIndexOf(" ");
  return `${(sp > 40 ? cut.slice(0, sp) : cut).trimEnd()}…`;
}

/** A coach's domain id in plain words: `nutrition_science` → "nutrition". The ids stay in System. */
const DOMAIN_WORDS = {
  orchestration: "runs the program",
  sleep_science: "sleep",
  nutrition_science: "nutrition",
  behavioral_psychology: "mind and habits",
  performance_science: "training",
  metabolic_health: "blood sugar",
  clinical_pathology: "lab results",
  biostatistics_n1_research: "the statistics",
  training: "training",
};
export function domainWords(id) {
  if (!id) return "";
  return DOMAIN_WORDS[id] || String(id).replace(/_/g, " ");
}

// ── Verbatim quotations (#5609: the dates-in-words exception inside coach quotes) ────────────────
// A coach's words are published exactly as said. An ISO date inside them is kept, wrapped in
// <time datetime> (semantics only — the characters are untouched), and glossed in words AFTER the
// quotation. Pure; nothing here alters the quoted string.
const ISO_IN_QUOTE = /\b(20\d\d)-(\d\d)-(\d\d)\b/g;

function isCalendarDay(iso) {
  const [y, m, d] = iso.split("-").map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d));
  return dt.getUTCFullYear() === y && dt.getUTCMonth() === m - 1 && dt.getUTCDate() === d;
}

/** "night of 2026-09-09 baseline" -> [{text:"night of "}, {date:"2026-09-09"}, {text:" baseline"}]. Joined, the parts ARE the input. */
export function quoteParts(text) {
  const s = String(text ?? "");
  const out = [];
  let at = 0;
  for (const m of s.matchAll(ISO_IN_QUOTE)) {
    if (!isCalendarDay(m[0])) continue; // "2026-13-40" is not a date: left as plain quoted text, never glossed
    if (m.index > at) out.push({ text: s.slice(at, m.index) });
    out.push({ date: m[0] });
    at = m.index + m[0].length;
  }
  if (at < s.length) out.push({ text: s.slice(at) });
  return out;
}

/** The ISO dates a quotation carries, in order of first appearance, each in words: [{iso, words}]. */
export function quoteGlosses(text) {
  const seen = new Set();
  const out = [];
  for (const p of quoteParts(text)) {
    if (!p.date || seen.has(p.date)) continue;
    seen.add(p.date);
    out.push({ iso: p.date, words: dayInWords(p.date, { weekday: true }) });
  }
  return out;
}

/** The quoted dates in words as one list ("Monday 14 September 2026 and Thursday 17 September 2026"), or "". Never the ISO form. */
export function glossList(text) {
  const g = quoteGlosses(text).map((x) => x.words);
  return g.length <= 1 ? g[0] || "" : `${g.slice(0, -1).join(", ")} and ${g[g.length - 1]}`;
}

/** The block form: "The date quoted is …." / "The dates quoted are …."; "" when none. */
export function glossText(text) {
  const n = quoteGlosses(text).length;
  return n ? `${n === 1 ? "The date quoted is" : "The dates quoted are"} ${glossList(text)}.` : "";
}

/**
 * A call whose words are withheld, in a compact mention (2026-11-14): its frozen test as the grader states it — already
 * public on the call's own page — instead of repeating the ledger's one sentence ("The words of this call are not
 * published.") five times down a day page. The ledger row itself still carries that sentence (owner ruling
 * 2026-11-06). Null when the test is not served, so the caller falls back to the sentence. ISO dates become words.
 */
export function heldCallWords(p, max = 90) {
  const how = p && p.grading && typeof p.grading.how === "string" ? p.grading.how.trim() : "";
  if (!how) return null;
  const t = how.replace(/\b1 days\b/, "1 day").replace(/\d{4}-\d{2}-\d{2}/g, (iso) => dayInWords(iso, { short: true }) || iso);
  // An observation is never graded, so it has no test: its line reads as itself ("…: an observation, not graded").
  const observation = p.status === "observation" || p.kind === "observation" || /observation, not graded/.test(t);
  return observation ? clip(t, max) : `the test: ${clip(t, max)}`;
}
