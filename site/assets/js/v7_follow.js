// v7_follow.js — the v7 "Follow" page (#4182, plan §2a row 9; Prototype C's Follow entry).
//
// The form is the live one: subscribe_page.js (the double-opt-in door, /api/subscribe,
// and the honest count from /api/sub_count) is loaded here unchanged and reads the ids
// scripts/v7/follow.py pours. This module renders only the three dated lines — the next
// write-up from /api/content_cadence (a held draft's served words win, the entry_age.js
// rule every v7 page uses), the next weigh-in from /api/journey's last_weighin_date in the
// ONE spelling every v7 page uses (entry_age.nextWeighInText: due, or "no weigh-in since
// <day> — N days" once that day is past — R6 fix 4), and the dated return line — plus the
// margins that carry those dates. Every line has an absence branch; nothing is hidden.
//
// The pure helpers are exported and unit-tested (tests/js/v7_follow.test.mjs); every one
// takes its inputs explicitly so no test reads the wall clock (main() passes todayPT(), the
// platform's PT clock — this page serves no data-through of its own). Dates in words come
// from entry_age.js; the margin parts are v7_week.js's, imported so the two pages cannot
// spell a day two ways.
import { nextWriteUpText, nextWeighInText } from "/assets/js/entry_age.js";
import { marginParts } from "/assets/js/v7_week.js";
import { todayPT } from "/assets/js/evidence_shared.js";

const esc = (s) => String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

/** The weigh-in line: "The next weigh-in is due Sunday, September 27." while the day after the last
 *  weigh-in is on or after `through` (the PT day); "No weigh-in since Monday, September 21 — 5 days."
 *  once it is past. { text, day } — `day` for <time datetime> and the margin; text "" when no
 *  weigh-in date is served (the caller prints the absence). */
export function weighInLine(journey, through) {
  const lw = journey && journey.journey && journey.journey.last_weighin_date;
  const r = nextWeighInText(lw, through, { capital: true });
  return { text: r.text ? `${r.text}.` : "", day: r.day };
}

/** The next write-up's day in words. A held draft or a paused cadence keeps its own served words;
 *  "" when nothing is served. (The cadence itself is the fold's derived line — not re-typed here.) */
export function writeUpLine(cad, pending) {
  const t = nextWriteUpText(cad, pending);
  if (!t) return "";
  const m = /^Next write-up: (.+)$/.exec(t);
  if (m) return `The next write-up is drafted ${m[1]} and publishes once Matthew has read it.`;
  return t.replace(/\.?$/, ".");
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
    if (!r.ok) {
      await r.text().catch(() => ""); // drain the body: an unread non-2xx response stays "in flight" and networkidle never arrives
      return null;
    }
    return await r.json();
  } catch (e) {
    return null;
  }
}

// Absence as absence (never hidden, never a promise): the three lines' not-served text.
const NO_WRITEUP_DAY = "The next write-up’s day is not served right now.";
const NO_WEIGHIN_DAY = "The last weigh-in’s day is not served right now.";

async function main() {
  const [cad, journey, postsJson] = await Promise.all([getJSON("/api/content_cadence"), getJSON("/api/journey"), getJSON("/journal/posts.json")]);
  const pending = postsJson && postsJson.pending;
  const wu = writeUpLine(cad, pending);
  const wuSrc = pending && pending.display ? "journal_posts.pending.display" : "api_content_cadence.chronicle.next_date";
  setLine("fo-writeup", wu || NO_WRITEUP_DAY, wuSrc);
  const wl = weighInLine(journey, todayPT());
  const weigh = document.getElementById("fo-weighin");
  if (weigh) weigh.setAttribute("data-day", wl.day);
  setLine("fo-weighin", wl.text || NO_WEIGHIN_DAY, "api_journey.journey.last_weighin_date");
  if (wl.day) setMargin(document.getElementById("fo-get"), wl.day);
  const rl = returnLine(cad, pending);
  const rd = returnDay(cad, pending);
  const ret = document.getElementById("fo-return-line");
  if (ret && rd) ret.setAttribute("data-day", rd);
  setLine("fo-return-line", rl || NO_WRITEUP_DAY, wuSrc);
  if (rd) setMargin(document.getElementById("fo-return"), rd);
}

if (typeof document !== "undefined" && document.getElementById("fo-form")) {
  // The live form, unchanged: it binds #submit-btn / #email / #source-field and fills
  // #sub-count-line from /api/sub_count ("One subscriber so far.").
  import("/assets/js/subscribe_page.js").catch(() => {});
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", main);
  else main();
}
