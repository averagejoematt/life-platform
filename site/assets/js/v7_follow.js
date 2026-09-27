// v7_follow.js — the v7 "Follow" page (#4182, plan §2a row 9; Prototype C's Follow entry).
//
// The form is the live one: subscribe_page.js (the double-opt-in door, /api/subscribe,
// and the honest count from /api/sub_count) is loaded here unchanged and reads the ids
// scripts/v7/follow.py pours. This module renders only the three dated lines — the next
// write-up from /api/content_cadence (a held draft's served words win, the entry_age.js
// rule every v7 page uses), the next weigh-in as last_weighin_date + 1 day from
// /api/journey, and the dated return line — plus the margins that carry those dates.
//
// The pure helpers are exported and unit-tested (tests/js/v7_follow.test.mjs); every one
// takes its inputs explicitly so no test reads the wall clock. Dates in words come from
// entry_age.js; the margin parts and plusDays are v7_week.js's, imported so the two
// pages cannot spell a day two ways.
import { dayInWords, nextWriteUpText } from "/assets/js/entry_age.js";
import { marginParts, plusDays } from "/assets/js/v7_week.js";

const esc = (s) => String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

/** The next weigh-in: /api/journey's last_weighin_date + 1 day (YYYY-MM-DD), "" when unusable. */
export function nextWeighIn(journey) {
  const lw = journey && journey.journey && journey.journey.last_weighin_date;
  return plusDays(lw, 1);
}

/** "The next weigh-in is due Sunday, September 27." — "" when nothing is served. */
export function weighInLine(journey) {
  const nw = nextWeighIn(journey);
  const w = dayInWords(nw);
  return w ? `The next weigh-in is due ${w}.` : "";
}

/** What a subscriber gets, with the next write-up's day in words. A held draft or a paused
 *  cadence keeps its own served words after the Sunday clause; "" when nothing is served. */
export function writeUpLine(cad, pending) {
  const t = nextWriteUpText(cad, pending);
  if (!t) return "";
  const m = /^Next write-up: (.+)$/.exec(t);
  if (m) return `The numbers every Sunday. The next write-up is drafted ${m[1]} and publishes once Matthew has read it.`;
  return `The numbers every Sunday. ${t.replace(/\.?$/, ".")}`;
}

/** The dated return line: "Next write-up: Wednesday, September 30." — the served words for a
 *  held draft or a paused cadence; "" when nothing is served. */
export function returnLine(cad, pending) {
  const t = nextWriteUpText(cad, pending);
  return t ? t.replace(/\.?$/, ".") : "";
}

/** The ISO day the return entry's margin should carry: a held draft's expected day, else the
 *  cadence's next_date when not paused, else "". */
export function returnDay(cad, pending) {
  if (pending && pending.expected_date) return String(pending.expected_date).slice(0, 10);
  const c = cad && cad.chronicle;
  return c && !c.paused && c.next_date ? String(c.next_date).slice(0, 10) : "";
}

// ── rendering ────────────────────────────────────────────────────────────────
function setMargin(section, dateStr) {
  const m = section && section.querySelector("[data-margin]");
  const p = marginParts(dateStr);
  if (!m || !p) return;
  m.innerHTML = `<span class="d">${esc(p.d)}</span><span class="mo">${esc(p.mo)}</span><span class="w">${esc(p.w)}</span>`;
}

function setLine(id, text, src) {
  const el = document.getElementById(id);
  if (!el) return;
  if (!text) {
    el.hidden = true;
    return;
  }
  el.hidden = false;
  el.classList.remove("fo-pending");
  if (src) el.setAttribute("data-src", src);
  const iso = el.getAttribute("data-day");
  el.innerHTML = iso ? `<time datetime="${esc(iso)}">${esc(text)}</time>` : esc(text);
}

async function getJSON(p) {
  try {
    const r = await fetch(p, { headers: { accept: "application/json" } });
    return r.ok ? await r.json() : null;
  } catch (e) {
    return null;
  }
}

async function main() {
  const [cad, journey, postsJson] = await Promise.all([getJSON("/api/content_cadence"), getJSON("/api/journey"), getJSON("/journal/posts.json")]);
  const pending = postsJson && postsJson.pending;
  const wu = writeUpLine(cad, pending);
  const wuSrc = pending && pending.display ? "journal_posts.pending.display" : "api_content_cadence.chronicle.next_date";
  if (wu) setLine("fo-writeup", wu, wuSrc);
  const nw = nextWeighIn(journey);
  const wl = weighInLine(journey);
  const weigh = document.getElementById("fo-weighin");
  if (weigh && nw) weigh.setAttribute("data-day", nw);
  setLine("fo-weighin", wl);
  if (nw) setMargin(document.getElementById("fo-get"), nw);
  const rl = returnLine(cad, pending);
  const rd = returnDay(cad, pending);
  const ret = document.getElementById("fo-return-line");
  if (ret && rd) ret.setAttribute("data-day", rd);
  setLine("fo-return-line", rl, wuSrc);
  if (rd) setMargin(document.getElementById("fo-return"), rd);
}

if (typeof document !== "undefined" && document.getElementById("fo-form")) {
  // The live form, unchanged: it binds #submit-btn / #email / #source-field and fills
  // #sub-count-line from /api/sub_count ("One subscriber so far.").
  import("/assets/js/subscribe_page.js").catch(() => {});
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", main);
  else main();
}
