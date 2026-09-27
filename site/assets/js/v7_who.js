// v7_who.js — the v7 "Who he is" page (#4182, plan §2a row 7; Prototype C screen V).
//
// One page, three entries and a return line, every number served: the fold (the honest
// photo frame's due line from the served start date; his paragraph is static, verbatim),
// the receipts strip in one line (the weight now and since the day it began, the day count,
// data through, the cost this month for the subscriber count, the code), the weigh-in line
// drawn to the DAY from /api/weight_progress with one sentence, how to check (the same four
// plain sentences Home's "How it works" carries, from the same served counts), and the dated
// return line from /api/content_cadence.
//
// The pure helpers are exported and unit-tested (tests/js/v7_who.test.mjs); every one takes
// its inputs explicitly so no test reads the wall clock. Dates in words come from
// entry_age.js — the one spelling every v7 page uses. Every rendered figure carries a
// data-src naming the served field it came from. OWNER RULING (2026-09-26): nothing here
// names an earlier start, an attempt count, a cycle or a reset — the man and this
// experiment, counted in days.
import { esc, tryJSON } from "/assets/js/evidence_shared.js";
import { dayInWords, dataThrough, countWord, nextWriteUpText } from "/assets/js/entry_age.js";

const HORIZON = 30; // the day the first photo is due
const REPO_URL = "https://github.com/averagejoematt/life-platform";

const num = (v) => (typeof v === "number" && Number.isFinite(v) ? v : null);
const iso = (s) => String(s || "").slice(0, 10);
const isIso = (s) => /^\d{4}-\d{2}-\d{2}$/.test(iso(s));
const utcNoon = (d) => Date.parse(`${iso(d)}T12:00:00Z`);
const dayNum = (d) => Math.round(utcNoon(d) / 86400000);
const fmt1 = (v) => (num(v) === null ? "" : v.toFixed(1));
const src = (path) => ` data-src="${esc(path)}"`;
const span = (path, text) => `<span${src(path)}>${esc(text)}</span>`;
const time = (d, path) => (isIso(d) ? `<time datetime="${esc(iso(d))}"${path ? src(path) : ""}>${esc(dayInWords(d))}</time>` : "");

/** YYYY-MM-DD plus n days. "" when unusable. */
export function plusDays(dateStr, n) {
  if (!isIso(dateStr)) return "";
  return new Date(utcNoon(dateStr) + n * 86400000).toISOString().slice(0, 10);
}

/** The margin of an entry, from a served date: { d: "26", mo: "Sep", w: "Saturday" }. Null when unusable. */
export function marginParts(dateStr) {
  const w = dayInWords(dateStr);
  if (!w) return null;
  const d = new Date(utcNoon(dateStr));
  return { d: String(d.getUTCDate()), mo: d.toLocaleDateString("en-US", { timeZone: "UTC", month: "short" }), w: w.split(",")[0] };
}

/** The photo frame's second line: due on day 30 from the served start date (Home's rule, the same words). */
export function photoDue(journey) {
  const j = journey || {};
  const n = num(j.day_n);
  const due = j.started_date ? plusDays(j.started_date, HORIZON - 1) : "";
  if (!due) return "";
  const when = time(due, "api_journey.journey.started_date + 29 days");
  return n !== null && n > HORIZON ? ` The first was due ${when} — day ${HORIZON}.` : ` The first is due ${when} — day ${HORIZON}.`;
}

/** The receipts strip: [html, …] — one item per receipt the page can substantiate, in the design order. */
export function receiptItems(journey, receipts, subs) {
  const j = journey || {};
  const out = [];
  const cur = num(j.current_weight_lbs);
  if (cur !== null) {
    let s = `<b>${span("api_journey.journey.current_weight_lbs", fmt1(cur))} lb</b>`;
    if (isIso(j.last_weighin_date)) s += ` on ${time(j.last_weighin_date, "api_journey.journey.last_weighin_date")}`;
    const lost = num(j.lost_lbs);
    if (lost !== null && isIso(j.started_date)) {
      const dir = lost > 0 ? "down" : lost < 0 ? "up" : "level";
      s += dir === "level" ? `, level since ${time(j.started_date, "api_journey.journey.started_date")}` : `, ${dir} ${span("api_journey.journey.lost_lbs", fmt1(Math.abs(lost)))} lb since ${time(j.started_date, "api_journey.journey.started_date")}`;
    }
    out.push(s);
  }
  const n = num(j.day_n);
  if (n !== null && n >= 1 && !j.pre_start) out.push(`Day ${span("api_journey.journey.day_n", String(n))}`);
  const thr = dataThrough(j.last_weighin_date);
  if (thr) out.push(span("api_journey.journey.last_weighin_date", thr.replace(/\.$/, "")));
  const usd = receipts && num(receipts.month_to_date_usd);
  if (usd !== null && usd !== undefined) {
    let s = `${span("api_receipts.month_to_date_usd", `$${usd.toFixed(2)}`)} this month`;
    if (subs && subs.available !== false && num(subs.count) !== null) s += `, for ${span("api_sub_count.count", countWord(subs.count))} subscriber${subs.count === 1 ? "" : "s"}`;
    out.push(s);
  }
  out.push(`<a href="${REPO_URL}" rel="noopener">the code</a>`);
  return out;
}

/** The weigh-ins as points positioned by the DAY (a six-day gap is six days wide), for a 320×60 box. */
export function stripPoints(progress) {
  const wp = (Array.isArray(progress) ? progress : []).filter((r) => r && isIso(r.date) && num(r.weight_lbs) !== null).slice().sort((a, b) => utcNoon(a.date) - utcNoon(b.date));
  if (wp.length < 2) return [];
  const d0 = dayNum(wp[0].date);
  const d1 = dayNum(wp[wp.length - 1].date);
  const ws = wp.map((r) => r.weight_lbs);
  const wmin = Math.min(...ws);
  const wmax = Math.max(...ws);
  return wp.map((r) => ({
    x: +(6 + ((dayNum(r.date) - d0) / Math.max(1, d1 - d0)) * 308).toFixed(1),
    y: +(6 + (wmax === wmin ? 23 : ((wmax - r.weight_lbs) / (wmax - wmin)) * 46)).toFixed(1),
    date: r.date,
    lbs: r.weight_lbs,
  }));
}

/** The one sentence under the line: the count, the span in days, from → to, drawn to the day. */
export function sinceSentence(progress, journey) {
  const pts = stripPoints(progress);
  if (!pts.length) return "";
  const first = pts[0];
  const last = pts[pts.length - 1];
  const days = dayNum(last.date) - dayNum(first.date) + 1;
  const diff = last.lbs - first.lbs;
  const dir = diff < 0 ? `down ${fmt1(Math.abs(diff))} lb` : diff > 0 ? `up ${fmt1(diff)} lb` : "level";
  const j = journey || {};
  const n = num(j.day_n);
  const skipped = n !== null && n >= pts.length ? `; the scale was skipped on ${span("api_journey.journey.day_n − weigh-in count", String(n - pts.length))} of the ${span("api_journey.journey.day_n", String(n))} days` : "";
  return (
    `${countWord(pts.length, { capital: true })} weigh-ins in ${countWord(days)} days — ${dir}, from ${span("api_weight_progress.weight_progress[0].weight_lbs", fmt1(first.lbs))} on ${time(first.date, "api_weight_progress.weight_progress[0].date")}` +
    ` to ${span("api_weight_progress.weight_progress[-1].weight_lbs", fmt1(last.lbs))} on ${time(last.date, "api_weight_progress.weight_progress[-1].date")}, drawn to the day${skipped}.`
  );
}

/** The weigh-in line as inline SVG plus its two end labels. "" when fewer than two weigh-ins. */
export function stripSvg(progress) {
  const pts = stripPoints(progress);
  if (!pts.length) return "";
  const first = pts[0];
  const last = pts[pts.length - 1];
  const dots = pts
    .map((p, i) => {
      const isLast = i === pts.length - 1;
      return `<circle cx="${p.x}" cy="${p.y}" r="${isLast ? 3.2 : 2.4}"${isLast ? ' class="who-last"' : ""}><title>${esc(dayInWords(p.date))} — ${esc(fmt1(p.lbs))} lb</title></circle>`;
    })
    .join("");
  const label = `${countWord(pts.length, { capital: true })} weigh-ins from ${fmt1(first.lbs)} on ${dayInWords(first.date, { weekday: false })} to ${fmt1(last.lbs)} on ${dayInWords(last.date, { weekday: false })}, drawn to the day.`;
  return (
    `<div class="who-strip"${src("api_weight_progress.weight_progress")}><svg viewBox="0 0 320 60" role="img" aria-label="${esc(label)}">` +
    `<line class="who-ax" x1="0" y1="6" x2="320" y2="6"/><polyline class="who-ln" points="${pts.map((p) => `${p.x},${p.y}`).join(" ")}"/><g class="who-pt">${dots}</g></svg>` +
    `<div class="who-strip-lab"><span>${esc(fmt1(first.lbs))} · ${esc(dayInWords(first.date))}</span><span>${esc(fmt1(last.lbs))} · ${esc(dayInWords(last.date))}</span></div></div>`
  );
}

/** The four plain sentences — Home's "How it works", the same words from the same served counts. */
export function howSentences(freshness, coaches) {
  const sum = (freshness && freshness.summary) || {};
  const out = [];
  if (num(sum.total) !== null) {
    let s = `${countWord(sum.total, { capital: true })} devices and apps are wired in — a scale, a wrist strap, a bed sensor, a food log, a lifting log, his phone`;
    if (num(sum.fresh) !== null) {
      s += ` — and ${span("api_source_freshness.summary.fresh", countWord(sum.fresh))} reported this week`;
      const tail = [];
      if (num(sum.stale) !== null && sum.stale > 0) tail.push(`${span("api_source_freshness.summary.stale", countWord(sum.stale))} ${sum.stale === 1 ? "is" : "are"} stale`);
      if (num(sum.paused) !== null && sum.paused > 0) tail.push(`${span("api_source_freshness.summary.paused", countWord(sum.paused))} ${sum.paused === 1 ? "is" : "are"} paused`);
      if (tail.length) s += `; ${tail.join(" and ")}`;
    }
    out.push(`${s}.`);
  }
  out.push("Every figure on this page is computed by code, not by an AI, and carries its date and its count.");
  const cc = coaches && num(coaches.count);
  out.push(`${cc !== null && cc !== undefined ? span("api_coaches.count", countWord(cc, { capital: true })) : "The"} AI coaches read those figures each morning and write to him; every dated claim they make is graded later by code against the data, and the misses stay on the record.`);
  out.push("An AI drafts the weekly write-up and Matthew reviews it before it publishes.");
  return out;
}

/** The dated return line: "Next write-up: Wednesday, September 30." — "" when nothing is served. */
export function returnLine(cad, pending) {
  const t = nextWriteUpText(cad, pending);
  return t ? (/[.!?]$/.test(t) ? t : `${t}.`) : "";
}

// ── rendering ────────────────────────────────────────────────────────────────
function setMargin(section, dateStr) {
  const m = section && section.querySelector("[data-margin]");
  const p = marginParts(dateStr);
  if (!m || !p) return;
  m.innerHTML = `<span class="d">${esc(p.d)}</span><span class="mo">${esc(p.mo)}</span><span class="w">${esc(p.w)}</span>`;
}

function fill(section, html) {
  if (!section) return;
  const body = section.querySelector(".who-body");
  const h = body && body.querySelector("h2");
  if (!body) return;
  body.innerHTML = (h ? h.outerHTML : "") + html;
}

function renderFold(journey, receipts, subs) {
  const sec = document.getElementById("who-fold");
  const due = photoDue(journey);
  const photo = document.getElementById("who-photo");
  if (photo && due) {
    document.getElementById("who-photo-due").innerHTML = due;
    photo.setAttribute("aria-label", photo.querySelector("div").textContent);
  }
  const strip = document.getElementById("who-receipts");
  if (strip) strip.innerHTML = receiptItems(journey, receipts, subs).join(" · ");
  const j = journey || {};
  if (j.last_weighin_date) setMargin(sec, j.last_weighin_date);
}

function renderSince(progress, journey) {
  const sec = document.getElementById("who-since");
  const j = journey || {};
  const day = document.getElementById("who-since-day");
  if (day && isIso(j.started_date)) day.textContent = dayInWords(j.started_date, { weekday: false });
  const svg = stripSvg(progress);
  if (!svg) return fill(sec, '<p class="who-note">No weigh-ins are served yet.</p>');
  fill(sec, `${svg}<p class="who-small">${sinceSentence(progress, journey)}</p>`);
  if (j.started_date) setMargin(sec, j.started_date);
}

function renderCheck(freshness, coaches, receipts) {
  const how = document.getElementById("who-how");
  if (how) how.innerHTML = howSentences(freshness, coaches).join(" ");
  const sec = document.getElementById("who-check");
  const asOf = receipts && receipts.as_of ? new Date(Date.parse(receipts.as_of)).toLocaleDateString("en-CA", { timeZone: "America/Los_Angeles" }) : "";
  if (asOf) setMargin(sec, asOf);
}

function renderReturn(cad, pending) {
  const el = document.getElementById("who-return");
  if (el) el.textContent = returnLine(cad, pending);
}

async function main() {
  const [journeyJson, receipts, subs, progressJson, freshness, coaches, cad, postsJson] = await Promise.all([
    tryJSON("/api/journey"),
    tryJSON("/api/receipts"),
    tryJSON("/api/sub_count"),
    tryJSON("/api/weight_progress"),
    tryJSON("/api/source_freshness"),
    tryJSON("/api/coaches"),
    tryJSON("/api/content_cadence"),
    tryJSON("/journal/posts.json"),
  ]);
  const journey = journeyJson && journeyJson.journey;
  renderFold(journey, receipts, subs);
  renderSince(progressJson && progressJson.weight_progress, journey);
  renderCheck(freshness, coaches, receipts);
  renderReturn(cad, postsJson && postsJson.pending);
}

if (typeof document !== "undefined" && document.getElementById("who-fold")) {
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", main);
  else main();
}
