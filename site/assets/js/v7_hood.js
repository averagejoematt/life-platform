// v7_hood.js — the v7 "Under the hood" page (#4182, plan §2a row 8; CONCEPT §3 row 8, §6).
//
// The receipts a sceptic checks, every one served: how a number is made (Home's own four
// "How it works" sentences from the same served fields, then the repo link and the cost
// line — /api/receipts month-to-date for /api/sub_count subscribers); the corrections
// column (/api/wrong.obituaries[] as three sentences each — what we said · what happened
// · what we changed — the served record folded under a <details>); the build log's last
// ten titles (/story/build/beats.json) with their days; when each device last reported
// (/api/source_freshness, poured into the build-time registry rows); the dated return line
// (/api/content_cadence).
//
// Two rules the render holds. (1) Never a machine string on the screen: a served sentence
// that still carries an evaluator record (a snake_case field, an ISO date — the shape
// /api/wrong served before #4226) is kept in the folded record and the card says so
// plainly. (2) No count of starts, no earlier-start words: the column says "since <the
// served start date>" and "early in the experiment" (the owner's ruling, 2026-09-26).
//
// The pure helpers are exported and unit-tested (tests/js/v7_hood.test.mjs); every one
// takes its inputs explicitly so no test reads the wall clock. Dates in words come from
// entry_age.js — the one spelling every v7 page uses. Every rendered figure carries a
// data-src naming the served field it came from.
import { countWord, dayInWords, dayLabel, loopReturnText } from "/assets/js/entry_age.js";

const esc = (s) => String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
const num = (v) => (v === null || v === undefined || v === "" || !Number.isFinite(Number(v)) ? null : Number(v));
const iso = (s) => String(s || "").slice(0, 10);
const isIso = (s) => /^\d{4}-\d{2}-\d{2}$/.test(iso(s));
const utcNoon = (d) => Date.parse(`${iso(d)}T12:00:00Z`);
const span = (src, text, cls) => `<span${cls ? ` class="${cls}"` : ""} data-src="${esc(src)}">${esc(text)}</span>`;
const cap = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : s);

export const REPO_URL = "https://github.com/averagejoematt/life-platform";

/** The margin of an entry, from a served date: { d: "26", mo: "Sep", w: "Saturday" }. Null when unusable. */
export function marginParts(dateStr) {
  const lab = dayLabel(dateStr); // "Sat Sep 26"
  if (!lab) return null;
  const [, mo, d] = lab.split(" ");
  const w = dayInWords(dateStr).split(",")[0];
  return { d, mo, w };
}

// ── how a number is made ─────────────────────────────────────────────────────
/** Home's four "How it works" sentences, verbatim, from the same served fields. [] when nothing is served. */
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
  }
  out.push("Every figure on this page is computed by code, not by an AI, and carries its date and its count.");
  const cc = coaches && num(coaches.count);
  out.push(
    `${cc !== null && cc !== undefined ? span("api_coaches.count", countWord(cc, { capital: true })) : "The"} AI coaches read those figures each morning and write to him; every dated claim they make is graded later by code against the data, and the misses stay on the record.`,
  );
  out.push("An AI drafts the weekly write-up and Matthew reviews it before it publishes.");
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

/** The three sentences of one correction, from one served obituary. Machine strings stay in the record. */
export function correctionSentences(ob, names) {
  const name = coachName(ob && ob.coach, names);
  const when = dayInWords(ob && ob.date);
  const believed = String((ob && ob.believed) || "").trim();
  const number = String((ob && ob.number) || "").trim();
  const changed = String((ob && ob.what_changed) || "").trim();
  const verdict = String((ob && ob.verdict) || "refuted").trim();
  const said = believed && !isRawRecord(believed) ? `${name}’s call, as the engine recorded it: ${believed.replace(/\.$/, "")}.` : `${name} made a dated call; its wording is in the record below.`;
  let happened;
  if (number && !isRawRecord(number)) happened = `${cap(number).replace(/\.$/, "")}.`;
  else if (number) happened = "The measured value is in the record below.";
  else happened = "No measured value is on the card; the record below says how it was settled.";
  let what = changed && !isRawRecord(changed) ? `${changed.replace(/\.$/, "")}.` : "The engine’s reason is in the record below.";
  what += ` Graded ${verdict} by code${when ? ` on ${when}` : ""}.`;
  return { name, when, said, happened, changed: what };
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

// ── the gear ─────────────────────────────────────────────────────────────────
/** When a registry source last reported, from /api/source_freshness.sources[] by id. Absence as absence. */
export function gearSeen(sources, id) {
  const row = (Array.isArray(sources) ? sources : []).find((s) => s && s.id === id);
  if (!row) return { status: "unknown", text: "no freshness record served" };
  const day = dayInWords(row.last_update);
  const status = String(row.status || "").toLowerCase();
  if (status === "paused") return { status, text: day ? `paused — last reported ${day}` : "paused — nothing on record" };
  if (!day) return { status: status || "none", text: "nothing on record yet" };
  if (status === "stale") return { status, text: `${day} — stale` };
  return { status: status || "fresh", text: day };
}

// ── the return line ──────────────────────────────────────────────────────────
/** "Next: the write-up lands Wednesday, September 30." — a held draft's own words win. */
export function returnLine(cad, pending) {
  const t = loopReturnText(cad, pending);
  if (!t) return "The next write-up has no date yet.";
  return /^the write-up lands /.test(t) ? `Next: ${t}.` : t;
}

// ── rendering ────────────────────────────────────────────────────────────────
function setMargin(section, dateStr) {
  const m = section && section.querySelector("[data-margin]");
  const p = marginParts(dateStr);
  if (!m || !p) return;
  m.innerHTML = `<span class="d">${esc(p.d)}</span><span class="mo">${esc(p.mo)}</span><span class="w">${esc(p.w)}</span>`;
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
  return (
    `<article class="hd-card" data-src="api_wrong.obituaries[${i}]">` +
    `<p class="hd-said"><b>What we said.</b> ${esc(s.said)}</p>` +
    `<p class="hd-happened"><b>What happened.</b> ${esc(s.happened)}</p>` +
    `<p class="hd-changed"><b>What we changed.</b> ${esc(s.changed)}</p>` +
    `<details class="hd-fold"><summary>The record, as served</summary>${recordTable(ob, names)}</details>` +
    `</article>`
  );
}

function compactRows(list, all, names) {
  return list
    .map((ob) => {
      const s = correctionSentences(ob, names);
      return `<tr data-src="api_wrong.obituaries[${all.indexOf(ob)}]"><td class="d">${esc(dayLabel(ob.date))}</td><td>${esc(s.said)}</td></tr>`;
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
    `<p class="hd-note">The code, in full: <a href="${REPO_URL}" rel="noopener">github.com/averagejoematt/life-platform</a></p>` +
    (cost ? `<p class="hd-cost">${cost}</p>` : '<p class="hd-note" data-src="api_receipts.month_to_date_usd">The cost line is not served right now.</p>');
}

function renderCorrections(wrong, stats, names) {
  const sec = document.getElementById("hd-corrections");
  const el = document.getElementById("hd-corrections-body");
  if (!el) return;
  const all = (wrong && wrong.obituaries) || [];
  const start = stats && stats.start_date;
  const startWords = dayInWords(start, { weekday: false });
  const sinceText = startWords ? `since ${span("api_platform_stats.start_date", startWords)}` : "since the experiment began";
  const { since, earlier } = splitCorrections(all, start);
  const parts = [];
  if (!all.length && !wrong) {
    el.innerHTML = '<p class="hd-note">The corrections are not served right now.</p>';
    return;
  }
  if (since.length) {
    parts.push(
      `<p class="hd-small"><b><span data-src="api_wrong.obituaries[]">${esc(countWord(since.length, { capital: true }))}</span> correction${since.length === 1 ? "" : "s"} ${sinceText}</b>, newest first. Every dated call a coach makes is graded later by code against the data; the ones the data refused to confirm stay here.</p>`,
    );
    const shown = since.slice(0, 6);
    parts.push(shown.map((ob) => cardHtml(ob, all.indexOf(ob), names)).join(""));
    const rest = since.slice(6);
    if (rest.length) parts.push(`<details class="hd-fold"><summary>The other ${countWord(rest.length)}</summary><table class="hd-compact"><tbody>${compactRows(rest, all, names)}</tbody></table></details>`);
  } else {
    parts.push(`<p class="hd-small" data-src="api_wrong.obituaries[]">No call has been refuted ${sinceText}. Early in the experiment a thin column means the slate is young, not that the calls were right.</p>`);
  }
  if (earlier.length) {
    parts.push(`<details class="hd-fold"><summary>Earlier in the experiment (${countWord(earlier.length)})</summary><table class="hd-compact"><tbody>${compactRows(earlier, all, names)}</tbody></table></details>`);
  }
  el.innerHTML = parts.join("");
  const newest = since[0] || earlier[0];
  if (newest) setMargin(sec, newest.date);
}

function renderLog(beatsJson) {
  const sec = document.getElementById("hd-log");
  const el = document.getElementById("hd-log-body");
  if (!el) return;
  const beats = lastBeats(beatsJson, 10);
  if (!beats.length) {
    el.innerHTML = '<p class="hd-note">No build note is served yet.</p>';
    return;
  }
  const items = beats
    .map((b, i) => `<li data-src="story_build_beats.beats[${i}]"><span class="hd-d">${esc(dayInWords(b.date, { weekday: false }))}</span> <a href="/story/build/">${esc(b.title)}</a></li>`)
    .join("");
  el.innerHTML = `<ol class="hd-log">${items}</ol><p class="hd-note">The last ${countWord(beats.length)} of what shipped, newest first. <a href="/story/build/">The full log — what each one shipped, why it mattered, and what it missed →</a></p>`;
  setMargin(sec, beats[0].date);
}

function renderGear(freshness) {
  const sources = freshness && freshness.sources;
  document.querySelectorAll("#hd-gear tr[data-source]").forEach((tr) => {
    const cell = tr.querySelector(".hd-gear-seen");
    if (!cell) return;
    if (!freshness) {
      cell.textContent = "freshness not served right now";
      return;
    }
    const seen = gearSeen(sources, tr.getAttribute("data-source"));
    cell.textContent = seen.text;
    cell.setAttribute("data-status", seen.status);
  });
}

function renderReturn(cad, pending) {
  const sec = document.getElementById("hd-return");
  const el = document.getElementById("hd-return-body");
  if (!el) return;
  el.innerHTML = `<p class="hd-small" data-src="${pending && pending.display ? "journal_posts.pending.display" : "api_content_cadence.chronicle.next_date"}">${esc(returnLine(cad, pending))}</p>`;
  const c = cad && cad.chronicle;
  const nd = (pending && pending.expected_date) || (c && !c.paused && c.next_date);
  if (nd) setMargin(sec, nd);
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
  const [wrong, stats, coaches, freshness, receipts, subs, cad, postsJson, beatsJson] = await Promise.all([
    getJSON("/api/wrong"),
    getJSON("/api/platform_stats"),
    getJSON("/api/coaches"),
    getJSON("/api/source_freshness"),
    getJSON("/api/receipts"),
    getJSON("/api/sub_count"),
    getJSON("/api/content_cadence"),
    getJSON("/journal/posts.json"),
    getJSON("/story/build/beats.json"),
  ]);
  renderHow(freshness, coaches, receipts, subs);
  renderCorrections(wrong, stats, coachNames(coaches));
  renderLog(beatsJson);
  renderGear(freshness);
  renderReturn(cad, postsJson && postsJson.pending);
}

if (typeof document !== "undefined" && document.getElementById("hd-corrections")) {
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", main);
  else main();
}
