// v7_hood.js — the v7 "Under the hood" page (#4182, plan §2a row 8; CONCEPT §3 row 8, §6).
//
// The receipts a sceptic checks, every one served: how a number is made (Home's own four
// "How it works" sentences from the same served fields, the repo named in words, then the
// cost line — /api/receipts month-to-date for /api/sub_count subscribers); the corrections
// column (/api/wrong.obituaries[] as three sentences each — what we said · what happened
// · what we changed — the served record folded under a <details>); the build log's last
// ten titles (/story/build/beats.json) with their days; when each device last reported
// (/api/source_freshness, poured into the build-time registry rows); the one "Data
// through" line (/api/vitals) and the dated return line (/api/content_cadence).
//
// Three rules the render holds. (1) Empty is not unreachable (R6 class 1): a fetch that
// failed prints "<what> is not served right now."; a served-empty list prints the fact
// sentence. Never a fact sentence on a 404. (2) Never a machine string on the screen: a
// served sentence that still carries an evaluator record (a snake_case field, an ISO
// date, a slope — the shape /api/wrong served before #4226 — or anything v7_coaches'
// lintPublic refuses) is kept in the folded record and the card says so plainly. Two
// symbols the engine's templated sentences carry, "%" and "±", are SPELLED on the card
// ("7.8 percent", "give or take 18.3") — typography, not a rewrite: the served string is
// verbatim in the record under the card. (3) No count of starts, no earlier-start words:
// the column says "since <the served start date>" and "early in the experiment" (the
// owner's ruling, 2026-09-26).
//
// The pure helpers are exported and unit-tested (tests/js/v7_hood.test.mjs); every one
// takes its inputs explicitly so no test reads the wall clock. Dates in words come from
// entry_age.js — the one spelling every v7 page uses. Every rendered figure carries a
// data-src naming the served field it came from.
import { countWord, dataThrough, dayInWords, dayLabel, loopReturnText } from "/assets/js/entry_age.js";
import { lintPublic } from "/assets/js/v7_coaches.js";

const esc = (s) => String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
const num = (v) => (v === null || v === undefined || v === "" || !Number.isFinite(Number(v)) ? null : Number(v));
const iso = (s) => String(s || "").slice(0, 10);
const isIso = (s) => /^\d{4}-\d{2}-\d{2}$/.test(iso(s));
const utcNoon = (d) => Date.parse(`${iso(d)}T12:00:00Z`);
const span = (src, text, cls) => `<span${cls ? ` class="${cls}"` : ""} data-src="${esc(src)}">${esc(text)}</span>`;
const cap = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : s);

export const REPO_URL = "https://github.com/averagejoematt/life-platform";
export const REPO_WORDS = "github.com/averagejoematt/life-platform";

/** How many corrections stand as full cards before the rest fold (R6 class 6: the page ≤ ~5 screens). */
export const CARDS_SHOWN = 3;

/** The margin of an entry, from a served date: { d: "26", mo: "Sep", w: "Saturday" }. Null when unusable. */
export function marginParts(dateStr) {
  const lab = dayLabel(dateStr); // "Sat Sep 26"
  if (!lab) return null;
  const [, mo, d] = lab.split(" ");
  const w = dayInWords(dateStr).split(",")[0];
  return { d, mo, w };
}

// ── how a number is made ─────────────────────────────────────────────────────
/** Home's four "How it works" sentences, verbatim, from the same served fields. The first is
 *  an absence line when freshness is unreachable — never silently dropped (R6 class 1). */
export function howSentences(freshness, coaches) {
  const sum = (freshness && freshness.summary) || {};
  const out = [];
  if (num(sum.total) !== null) {
    let s = `${span("api_source_freshness.summary.total", countWord(sum.total, { capital: true }))} devices and apps are wired in — a scale, a wrist strap, a bed sensor, a food log, a lifting log, his phone`;
    if (num(sum.fresh) !== null) {
      s += ` — and ${span("api_source_freshness.summary.fresh", countWord(sum.fresh))} reported this week`;
      const tail = [];
      if (num(sum.stale) !== null && sum.stale > 0) tail.push(`${span("api_source_freshness.summary.stale", countWord(sum.stale))} ${sum.stale === 1 ? "is" : "are"} stale`);
      if (num(sum.paused) !== null && sum.paused > 0) tail.push(`${span("api_source_freshness.summary.paused", countWord(sum.paused))} ${sum.paused === 1 ? "is" : "are"} paused`);
      if (tail.length) s += `; ${tail.join(" and ")}`;
    }
    out.push(`${s}.`);
  } else if (!freshness) {
    out.push("How many devices and apps are wired in is not served right now.");
  }
  out.push("Every figure on this page is computed by code, not by an AI, and carries its date and its count.");
  const cc = coaches && num(coaches.count);
  out.push(
    `${cc !== null && cc !== undefined ? span("api_coaches.count", countWord(cc, { capital: true })) : "The"} AI coaches read those figures each morning and write to him; every dated claim they make is graded later by code against the data, and the misses stay on the record.`,
  );
  out.push("An AI drafts the weekly write-up and Matthew reviews it before it publishes.");
  out.push(`Every line of the code that does this is public, at <a href="${REPO_URL}" rel="noopener">${REPO_WORDS}</a>.`);
  return out;
}

/** The cost line: "$102.74 so far in September, for one subscriber." — "" when no cost is served. */
export function costLine(receipts, subs) {
  const usd = receipts && num(receipts.month_to_date_usd);
  if (usd === null || usd === undefined) return "";
  const month = receipts.as_of ? new Date(Date.parse(receipts.as_of)).toLocaleDateString("en-US", { timeZone: "America/Los_Angeles", month: "long" }) : "this month";
  let s = `Running all of it has cost ${span("api_receipts.month_to_date_usd", `$${usd.toFixed(2)}`, "num")} so far in ${month}`;
  if (subs && subs.available !== false && num(subs.count) !== null) s += `, for ${span("api_sub_count.count", countWord(subs.count))} subscriber${subs.count === 1 ? "" : "s"}`;
  return `${s}.`;
}

// ── the corrections column ───────────────────────────────────────────────────
/** persona_id → name from /api/coaches. */
export function coachNames(coaches) {
  const out = {};
  for (const c of (coaches && coaches.coaches) || []) if (c && c.persona_id && c.name) out[c.persona_id] = c.name;
  return out;
}

/** A card's short coach id ("sleep", "explorer", "eli_marsh") → the roster name, or a plain phrase. */
export function coachName(id, names) {
  const k = String(id || "");
  if (!k) return "a coach";
  if (names && names[`${k}_coach`]) return names[`${k}_coach`];
  if (names && names[k]) return names[k];
  return `the ${k.replace(/_/g, " ")} coach`;
}

/** True when a served sentence still carries the evaluator's record — a snake_case field, an ISO date, a slope. */
export function isRawRecord(s) {
  const t = String(s || "");
  return /\b[a-z0-9]+_[a-z0-9_]+\b/i.test(t) || /\d{4}-\d{2}-\d{2}/.test(t) || /\b(slope|predicted|trend)=/.test(t);
}

/** The two symbols the engine's templated sentences carry, spelled for the reader: "7.8%" → "7.8 percent",
 *  "±18.3" → "give or take 18.3". Typography only — the served string stays verbatim in the folded record. */
export function spellSymbols(s) {
  return String(s || "")
    .replace(/(\d)\s?%/g, "$1 percent")
    .replace(/\bthe ±\s?([\d.,]+(?: percent)?(?: (?!noise\b)[a-z]+)?) (noise )?band\b/g, "the $2band of $1 either way")
    .replace(/\s*±\s*/g, " give or take ");
}

/** A served sentence is fit for the main screen when it carries no evaluator record and passes the
 *  coaches page's public lint (an ISO date, a percent sign, a device brand) once its symbols are spelled. */
export function fitForScreen(s) {
  const t = spellSymbols(s);
  return Boolean(t) && !isRawRecord(t) && lintPublic(t).length === 0;
}

/** The three sentences of one correction, from one served obituary. Machine strings stay in the record. */
export function correctionSentences(ob, names) {
  const name = coachName(ob && ob.coach, names);
  const when = dayInWords(ob && ob.date);
  const believed = String((ob && ob.believed) || "").trim();
  const number = String((ob && ob.number) || "").trim();
  const changed = String((ob && ob.what_changed) || "").trim();
  const verdict = String((ob && ob.verdict) || "refuted").trim();
  const said = fitForScreen(believed) ? `${name}’s call, as the engine recorded it: ${spellSymbols(believed).replace(/\.$/, "")}.` : `${name} made a dated call; its wording is in the record below.`;
  let happened;
  if (fitForScreen(number)) happened = `${cap(spellSymbols(number)).replace(/\.$/, "")}.`;
  else if (number) happened = "The measured value is in the record below.";
  else happened = "No measured value is on the card; the record below says how it was settled.";
  const changedBody = fitForScreen(changed) ? `${spellSymbols(changed).replace(/\.$/, "")}.` : "The engine’s reason is in the record below.";
  // The grading tail names the verdict once: when the reason already says "graded refuted", only the day is added.
  const graded = new RegExp(`graded ${verdict}`, "i").test(changedBody) ? "Graded" : `Graded ${verdict}`;
  const what = `${changedBody} ${graded} by code${when ? ` on ${when}` : ""}.`;
  return { name, when, said, happened, changed: what, changedBody, graded };
}

/** Newest first; split at the served start date — since it, and earlier in the experiment. */
export function splitCorrections(obituaries, startDate) {
  const all = (Array.isArray(obituaries) ? obituaries : []).filter((o) => o && isIso(o.date));
  const served = new Map(all.map((o, i) => [o, i]));
  all.sort((a, b) => utcNoon(b.date) - utcNoon(a.date) || served.get(a) - served.get(b)); // same day: the served order
  if (!isIso(startDate)) return { since: all, earlier: [] };
  const t0 = utcNoon(startDate);
  return { since: all.filter((o) => utcNoon(o.date) >= t0), earlier: all.filter((o) => utcNoon(o.date) < t0) };
}

// ── the build log ────────────────────────────────────────────────────────────
/** The last n dated build notes, newest first. */
export function lastBeats(beatsJson, n = 10) {
  const beats = (beatsJson && beatsJson.beats) || [];
  const ok = beats.filter((b) => b && isIso(b.date) && b.title);
  ok.sort((a, b) => utcNoon(b.date) - utcNoon(a.date));
  return ok.slice(0, n);
}

/** The build log's absence line — unreachable and served-empty are two different sentences (R6 class 1). */
export function logAbsence(beatsJson) {
  if (!beatsJson) return "The build log is not served right now.";
  return "No build note has been published yet.";
}

// ── the gear ─────────────────────────────────────────────────────────────────
/** When a registry source last reported, from /api/source_freshness.sources[] by id. Absence as absence. */
export function gearSeen(sources, id) {
  const row = (Array.isArray(sources) ? sources : []).find((s) => s && s.id === id);
  if (!row) return { status: "unknown", text: "outside the daily check" };
  const day = dayInWords(row.last_update);
  const status = String(row.status || "").toLowerCase();
  if (status === "paused") return { status, text: day ? `paused — last reported ${day}` : "paused — nothing on record" };
  if (!day) return { status: status || "none", text: "nothing on record yet" };
  if (status.includes("stale")) return { status: "stale", text: `${day} — stale` };
  return { status: status || "fresh", text: day };
}

/** The gear lead's freshness clause: how many of the listed sources the daily check covers. "" when unusable. */
export function gearCoverage(freshness, listed) {
  const total = freshness && freshness.summary && num(freshness.summary.total);
  if (total === null || total === undefined) return freshness ? "" : "How many of them the site checks each day is not served right now.";
  const n = num(listed);
  const covered = span("api_source_freshness.summary.total", countWord(total));
  if (n !== null && n > total) return `The site’s daily freshness check covers ${covered} of them; a row with no last-reported day is outside that check.`;
  return `The site’s daily freshness check covers ${covered} of them.`;
}

// ── the return line ──────────────────────────────────────────────────────────
/** "Next: the write-up lands Wednesday, September 30." — a held draft's own words win; unreachable says so. */
export function returnLine(cad, pending) {
  const t = loopReturnText(cad, pending);
  if (!t) return cad ? "The next write-up has no date yet." : "The next write-up’s date is not served right now.";
  return /^the write-up lands /.test(t) ? `Next: ${t}.` : t;
}

// ── rendering ────────────────────────────────────────────────────────────────
function setMargin(section, dateStr, src) {
  const m = section && section.querySelector("[data-margin]");
  const p = marginParts(dateStr);
  if (!m || !p) return;
  m.innerHTML = `<span class="d">${esc(p.d)}</span><span class="mo">${esc(p.mo)}</span><span class="w">${esc(p.w)}</span>`;
  if (src) m.setAttribute("data-src", src);
}

function recordTable(ob, names) {
  const rows = [
    ["Coach", esc(coachName(ob.coach, names))],
    ["Graded", esc(dayInWords(ob.date) || "no date served")],
    ["Believed", esc(ob.believed || "(empty)")],
    ["Measured", esc(ob.number || "(empty)")],
    ["Reason", esc(ob.what_changed || "(empty)")],
    ["Verdict", esc(ob.verdict || "(empty)")],
  ];
  if (ob.permalink) rows.push(["Card", `<a href="${esc(ob.permalink)}">the card, on the live site</a>`]);
  return `<table class="hd-record"><tbody>${rows.map(([k, v]) => `<tr><th scope="row">${k}</th><td>${v}</td></tr>`).join("")}</tbody></table>`;
}

function cardHtml(ob, i, names) {
  const s = correctionSentences(ob, names);
  const tail = `${esc(s.graded)} by code${s.when ? ` on ${span(`api_wrong.obituaries[${i}].date`, s.when)}` : ""}.`;
  return (
    `<article class="hd-card" data-src="api_wrong.obituaries[${i}]">` +
    `<p class="hd-said"><b>What we said.</b> ${esc(s.said)}</p>` +
    `<p class="hd-happened"><b>What happened.</b> ${esc(s.happened)}</p>` +
    `<p class="hd-changed"><b>What we changed.</b> ${esc(s.changedBody)} ${tail}</p>` +
    `<details class="hd-fold"><summary>The record, as served</summary>${recordTable(ob, names)}</details>` +
    `</article>`
  );
}

function compactRows(list, all, names) {
  return list
    .map((ob) => {
      const i = all.indexOf(ob);
      const s = correctionSentences(ob, names);
      return `<tr data-src="api_wrong.obituaries[${i}]"><td class="d">${span(`api_wrong.obituaries[${i}].date`, dayLabel(ob.date))}</td><td>${esc(s.said)}</td></tr>`;
    })
    .join("");
}

function renderHow(freshness, coaches, receipts, subs) {
  const el = document.getElementById("hd-how-body");
  if (!el) return;
  const sentences = howSentences(freshness, coaches);
  const cost = costLine(receipts, subs);
  el.innerHTML =
    `<p class="hd-prose">${sentences.join(" ")}</p>` +
    (cost ? `<p class="hd-cost">${cost}</p>` : `<p class="hd-note" data-src="api_receipts.month_to_date_usd">${receipts ? "No cost is served for this month yet." : "The cost line is not served right now."}</p>`);
}

function renderCorrections(wrong, stats, names) {
  const sec = document.getElementById("hd-corrections");
  const el = document.getElementById("hd-corrections-body");
  if (!el) return;
  if (!wrong) {
    el.innerHTML = '<p class="hd-note">The corrections are not served right now.</p>';
    return;
  }
  const all = wrong.obituaries || [];
  const start = stats && stats.start_date;
  const startWords = dayInWords(start, { weekday: false });
  const sinceText = startWords ? `since ${span("api_platform_stats.start_date", startWords)}` : "since the experiment began";
  const { since, earlier } = splitCorrections(all, start);
  const parts = [];
  if (since.length) {
    parts.push(
      `<p class="hd-small"><b><span data-src="api_wrong.obituaries[]">${esc(countWord(since.length, { capital: true }))}</span> correction${since.length === 1 ? "" : "s"} ${sinceText}</b>, newest first. Every dated call a coach makes is graded later by code against the data; the ones the data refused to confirm stay here.</p>`,
    );
    const shown = since.slice(0, CARDS_SHOWN);
    parts.push(shown.map((ob) => cardHtml(ob, all.indexOf(ob), names)).join(""));
    const rest = since.slice(CARDS_SHOWN);
    if (rest.length) parts.push(`<details class="hd-fold"><summary>The other ${countWord(rest.length)}, one line each</summary><table class="hd-compact"><tbody>${compactRows(rest, all, names)}</tbody></table></details>`);
  } else {
    parts.push(`<p class="hd-small" data-src="api_wrong.obituaries[]">No call has been refuted ${sinceText}. Early in the experiment a thin column means the slate is young, not that the calls were right.</p>`);
  }
  if (earlier.length) {
    parts.push(`<details class="hd-fold"><summary>Earlier in the experiment (${countWord(earlier.length)})</summary><table class="hd-compact"><tbody>${compactRows(earlier, all, names)}</tbody></table></details>`);
  }
  el.innerHTML = parts.join("");
  const newest = since[0] || earlier[0];
  if (newest) setMargin(sec, newest.date, `api_wrong.obituaries[${all.indexOf(newest)}].date`);
}

function renderLog(beatsJson) {
  const sec = document.getElementById("hd-log");
  const el = document.getElementById("hd-log-body");
  if (!el) return;
  const beats = lastBeats(beatsJson, 10);
  if (!beats.length) {
    el.innerHTML = `<p class="hd-note">${esc(logAbsence(beatsJson))}</p>`;
    return;
  }
  const items = beats
    .map((b, i) => `<li data-src="story_build_beats.beats[${i}]"><span class="hd-d">${esc(dayInWords(b.date, { weekday: false }))}</span> <a href="/story/build/">${esc(b.title)}</a></li>`)
    .join("");
  el.innerHTML = `<ol class="hd-log">${items}</ol><p class="hd-note">The last ${countWord(beats.length)} of what shipped, newest first. <a href="/story/build/">The full log — what each one shipped, why it mattered, and what it missed →</a></p>`;
  setMargin(sec, beats[0].date, "story_build_beats.beats[0].date");
}

function renderGear(freshness) {
  const sources = freshness && freshness.sources;
  const rows = document.querySelectorAll("#hd-gear tr[data-source]");
  rows.forEach((tr) => {
    const cell = tr.querySelector(".hd-gear-seen");
    if (!cell) return;
    if (!freshness) {
      cell.textContent = "not served right now";
      return;
    }
    const seen = gearSeen(sources, tr.getAttribute("data-source"));
    cell.textContent = seen.text;
    cell.setAttribute("data-status", seen.status);
  });
  const lead = document.getElementById("hd-gear-cover");
  if (lead) lead.innerHTML = gearCoverage(freshness, rows.length);
}

function renderReturn(cad, pending, vitals) {
  const sec = document.getElementById("hd-return");
  const el = document.getElementById("hd-return-body");
  if (!el) return;
  el.innerHTML = `<p class="hd-small" data-src="${pending && pending.display ? "journal_posts.pending.display" : "api_content_cadence.chronicle.next_date"}">${esc(returnLine(cad, pending))}</p>`;
  const c = cad && cad.chronicle;
  const nd = (pending && pending.expected_date) || (c && !c.paused && c.next_date);
  if (nd) setMargin(sec, nd, pending && pending.expected_date ? "journal_posts.pending.expected_date" : "api_content_cadence.chronicle.next_date");
  const thr = document.getElementById("hd-through");
  if (thr) thr.textContent = dataThrough(vitals && vitals.vitals && vitals.vitals.as_of_date);
}

/** One served JSON, or null. A non-2xx body is DRAINED before returning null: an unread body
 *  stays "in flight" to Chromium, so `networkidle` never arrives and the visual-QA gate that
 *  waits on it rolls the deploy back (proved live by the Today lane, Session AW). */
export async function getJSON(p, fetchImpl = fetch) {
  try {
    const r = await fetchImpl(p, { headers: { accept: "application/json" } });
    if (r.ok) return await r.json();
    await r.text().catch(() => "");
    return null;
  } catch (e) {
    return null;
  }
}

async function main() {
  const [wrong, stats, coaches, freshness, receipts, subs, cad, postsJson, beatsJson, vitals] = await Promise.all([
    getJSON("/api/wrong"),
    getJSON("/api/platform_stats"),
    getJSON("/api/coaches"),
    getJSON("/api/source_freshness"),
    getJSON("/api/receipts"),
    getJSON("/api/sub_count"),
    getJSON("/api/content_cadence"),
    getJSON("/journal/posts.json"),
    getJSON("/story/build/beats.json"),
    getJSON("/api/vitals"),
  ]);
  renderHow(freshness, coaches, receipts, subs);
  renderCorrections(wrong, stats, coachNames(coaches));
  renderLog(beatsJson);
  renderGear(freshness);
  renderReturn(cad, postsJson && postsJson.pending, vitals);
}

if (typeof document !== "undefined" && document.getElementById("hd-corrections")) {
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", main);
  else main();
}
