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
