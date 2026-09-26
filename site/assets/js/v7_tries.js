// v7_tries.js — the v7 "What he's trying" page (#4182, plan §2a row 6; CONCEPT §3 row 6).
//
// One page, four dated entries, every number served: what he takes (the stack from
// /api/supplements — how many he takes and how many are paused, each compound as
// what · should move · how we'd know, the August correction folded under the cards and
// its count derived from the same payload), what he's testing (/api/experiments — what
// is running first, then what is ready to start, then the honest count of ideas
// waiting; /api/protocols for a standing rule, stated as absent when there is none),
// his calls in his words (/api/decisions — the notes he chose to publish, verbatim and
// dated; the channel name is never printed and anything carrying tool-call residue is
// dropped, not cleaned), and the dated return line (/api/content_cadence).
//
// The pure helpers are exported and unit-tested (tests/js/v7_tries.test.mjs); none reads
// the wall clock. Dates in words come from entry_age.js — the one spelling every v7 page
// uses. Every rendered figure carries a data-src naming the served field it came from.
// No word for a start count, a restart or an earlier try appears in this file's copy
// (the owner's ruling on Prototype C, 2026-09-26).
import { dayInWords, dayLabel, dataThrough, instantDayInWords, countWord, loopReturnText } from "/assets/js/entry_age.js";

const esc = (s) => String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
const num = (v) => (Number.isFinite(Number(v)) ? Number(v).toLocaleString("en-US") : "");
const iso = (s) => String(s || "").slice(0, 10);
const isIso = (s) => /^\d{4}-\d{2}-\d{2}$/.test(iso(s));
const bad = (v) => v == null || String(v).trim() === "" || /^\[.*\]$/.test(String(v).trim()) || String(v).trim().toUpperCase() === "N/A";

/** The margin of an entry, from a served date: { d: "25", mo: "Sep", w: "Friday" }. Null when unusable. */
export function marginParts(dateStr) {
  const lab = dayLabel(dateStr); // "Fri Sep 25"
  if (!lab) return null;
  const [, mo, d] = lab.split(" ");
  const w = dayInWords(dateStr).split(",")[0];
  return { d, mo, w };
}

/** Tool-call residue (#4190): text carrying it is dropped whole, never trimmed. */
export const RESIDUE = /<tool_call|\bfunction_call\b/i;
export function hasResidue(text) {
  return RESIDUE.test(String(text || ""));
}

// ── what he takes ────────────────────────────────────────────────────────────
/** Every item of the served stack, flattened, with the group it sits in and its payload path. */
export function stackItems(supp) {
  const groups = (supp && supp.groups) || {};
  const out = [];
  for (const key of Object.keys(groups)) {
    const g = groups[key] || {};
    (g.items || []).forEach((s, i) => {
      if (s) out.push({ group: key, groupName: g.name || key, item: s, src: `api_supplements.groups.${key}.items[${i}]` });
    });
  }
  return out;
}

/** { taking, paused, total } from the served `paused` flags. */
export function stackCounts(supp) {
  const items = stackItems(supp);
  const paused = items.filter((x) => x.item.paused).length;
  return { taking: items.length - paused, paused, total: items.length };
}

/** The fold sentence: "18 in the current stack, 3 paused." — "" when nothing is served. */
export function stackLine(supp) {
  const c = stackCounts(supp);
  if (!c.total) return "";
  return `${num(c.taking)} in the current stack${c.paused ? `, ${num(c.paused)} paused` : ""}.`;
}

/** One compound as the three lines a reader gets. Absence is a stated absence, never a blank. */
export function compoundCard(entry) {
  const s = entry.item || entry;
  const move = bad(s.hoped_outcome) ? "" : String(s.hoped_outcome);
  const know = bad(s.measured_by) ? "" : String(s.measured_by);
  return {
    what: String(s.name || ""),
    dose: bad(s.dose) ? "" : String(s.dose),
    timing: bad(s.timing) ? "" : String(s.timing),
    paused: !!s.paused,
    pausedReason: s.paused && !bad(s.pausedReason) ? String(s.pausedReason) : "",
    shouldMove: move,
    howWeKnow: know,
    src: entry.src || "",
  };
}

/** #1940 — the withdrawn-citation count, derived from the payload the page just rendered. */
export function withdrawnCount(supp) {
  return stackItems(supp)
    .flatMap((x) => x.item.sources || [])
    .filter((x) => x && !x.url && /withdrawn/i.test(String(x.title || ""))).length;
}

/** The standing-rules line from /api/protocols. Null payload → the honest "not loaded". */
export function rulesLine(protocols) {
  if (!protocols) return "Standing rules: not loaded.";
  const n = Array.isArray(protocols.protocols) ? protocols.protocols.length : Number(protocols.count) || 0;
  if (!n) return "No standing rule is on the record beyond the stack.";
  return `${countWord(n, { capital: true })} standing rule${n === 1 ? "" : "s"} ${n === 1 ? "is" : "are"} on the record.`;
}

// ── what he's testing ────────────────────────────────────────────────────────
/** Running (anything not from the library), ready to start (library, available), waiting (the rest). */
export function splitExperiments(exp) {
  const xs = (exp && Array.isArray(exp.experiments) ? exp.experiments : []).filter(Boolean);
  const idx = (x) => xs.indexOf(x);
  const running = xs.filter((x) => x.origin && x.origin !== "library");
  const ready = xs.filter((x) => !running.includes(x) && x.status === "available");
  const waiting = xs.filter((x) => !running.includes(x) && !ready.includes(x));
  return {
    running: running.map((x) => ({ x, i: idx(x) })),
    ready: ready.map((x) => ({ x, i: idx(x) })),
    waiting: waiting.map((x) => ({ x, i: idx(x) })),
  };
}

/** One test as the three lines: what he'd try · what it should move · how we'd know. */
export function tryCard({ x, i }) {
  const days = Number(x.planned_duration_days);
  const know = !bad(x.measurement) ? String(x.measurement) : !bad(x.primary_metric) ? String(x.primary_metric) : "";
  return {
    what: String(x.name || ""),
    duration: Number.isFinite(days) && days > 0 ? `${num(days)} days` : "",
    shouldMove: bad(x.hypothesis) ? "" : String(x.hypothesis),
    howWeKnow: know,
    src: `api_experiments.experiments[${i}]`,
  };
}

/** The running line: "Nothing formal is running." or "Two are running." */
export function runningLine(split) {
  const n = split.running.length;
  if (!n) return "Nothing formal is running.";
  return `${countWord(n, { capital: true })} ${n === 1 ? "is" : "are"} running.`;
}

/** The honest count of ideas waiting: "63 ideas are waiting in the library; none is scheduled." */
export function waitingLine(split) {
  const n = split.waiting.length;
  if (!n) return "";
  return `${num(n)} idea${n === 1 ? "" : "s"} ${n === 1 ? "is" : "are"} waiting in the library; none is scheduled.`;
}

// ── his calls, in his words ──────────────────────────────────────────────────
/** The decisions a reader gets: a published note, residue-free, with the day it was made.
 *  The channel (`source`) is never carried; the platform's side is kept only when it is clean. */
export function hisCalls(dec) {
  const rows = (dec && Array.isArray(dec.decisions) ? dec.decisions : []).filter(Boolean);
  const out = [];
  rows.forEach((r, i) => {
    if (bad(r.note) || hasResidue(r.note)) return;
    const day = isIso(r.date) ? iso(r.date) : "";
    const rec = bad(r.decision) || hasResidue(r.decision) ? "" : String(r.decision);
    out.push({ note: String(r.note), date: day, noteAt: r.note_at || "", recommended: rec, followed: r.followed === true ? true : r.followed === false ? false : null, src: `api_decisions.decisions[${i}]` });
  });
  return out;
}

/** The day line under a note: the decision's date in words, else the note's own write day. */
export function callDay(call) {
  return call.date ? dayInWords(call.date) : instantDayInWords(call.noteAt);
}

/** "He went the other way." / "He went with it." / "" when the record does not say. */
export function followedWords(call) {
  if (call.followed === true) return "He went with it.";
  if (call.followed === false) return "He went the other way.";
  return "";
}

// ── next ─────────────────────────────────────────────────────────────────────
/** The dated return line: "The write-up lands Wednesday, September 30." — "" when nothing is served. */
export function returnLine(cad) {
  const t = loopReturnText(cad, null);
  if (!t) return "";
  return t.charAt(0).toUpperCase() + t.slice(1) + (/[.!?]$/.test(t) ? "" : ".");
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
  const body = section.querySelector(".tr-body");
  const h = body && body.querySelector("h2");
  if (!body) return;
  body.innerHTML = (h ? h.outerHTML : "") + html;
}

const absent = (t) => `<dd class="tr-absent">${esc(t)}</dd>`;

function cardHtml(c, { whatLabel = "what", moveLabel = "should move", knowLabel = "how we’d know", tail = "" } = {}) {
  const dose = [c.dose, c.timing].filter(Boolean).join(" · ");
  const what =
    `<p class="tr-card-what"><span data-src="${esc(c.src)}.name">${esc(c.what)}</span>` +
    (c.duration ? ` <span class="num" data-src="${esc(c.src)}.planned_duration_days">${esc(c.duration)}</span>` : "") +
    (dose ? ` <span class="num" data-src="${esc(c.src)}.dose">${esc(dose)}</span>` : "") +
    (c.paused ? ` <span class="tr-card-flag" data-src="${esc(c.src)}.paused">paused</span>` : "") +
    `</p>`;
  const rows =
    (c.pausedReason ? `<div><dt>why paused</dt><dd data-src="${esc(c.src)}.pausedReason">${esc(c.pausedReason)}</dd></div>` : "") +
    `<div><dt>${esc(moveLabel)}</dt>${c.shouldMove ? `<dd data-src="${esc(c.src)}.${c.duration ? "hypothesis" : "hoped_outcome"}">${esc(c.shouldMove)}</dd>` : absent("Not stated.")}</div>` +
    `<div><dt>${esc(knowLabel)}</dt>${c.howWeKnow ? `<dd data-src="${esc(c.src)}.${c.duration ? "measurement" : "measured_by"}">${esc(c.howWeKnow)}</dd>` : absent(tail || "The instrument is not named.")}</div>`;
  return `<li class="tr-card${c.paused ? " tr-card--paused" : ""}">${what}<dl>${rows}</dl></li>`;
}

function correctionHtml(supp) {
  const n = withdrawnCount(supp);
  if (!n) return "";
  return (
    `<details class="tr-fold" role="note"><summary>A correction, August 2 — <span data-src="api_supplements.groups[].items[].sources[].title">${esc(num(n))}</span> citations withdrawn</summary>` +
    `<p>Correction · 2 August 2026 · updated 4 August 2026.</p>` +
    `<p>${esc(num(n))} citations on this page were withdrawn. They pointed to papers that did not support the claims they were attached to — they were never verified when they were written. Two more were withdrawn from the list of tests the same day. On 4 August 2026 one of those two (Tongkat Ali) was re-resolved to a real supporting trial and restored — the original claim was sound, the link attached to it was not.</p>` +
    `<p>Nothing was removed quietly: each withdrawn claim now reads “Open question” in the served record, and the affected compounds’ evidence ratings were downgraded to match what is actually cited — in two cases, nothing. Every citation that survives stores the resolved title of the paper it points to, and a test re-resolves each one against PubMed, so a citation that does not say what it claims fails the build instead of sitting on the page.</p></details>`
  );
}

function renderTakes(supp, protocols) {
  const sec = document.getElementById("tr-takes");
  const items = stackItems(supp);
  if (!items.length) return fill(sec, '<p class="tr-note">The stack is not served.</p>');
  const c = stackCounts(supp);
  let html = `<p class="tr-lead"><span class="num" data-src="api_supplements.groups[].items[]">${esc(num(c.taking))}</span> in the current stack${c.paused ? `, <span class="num" data-src="api_supplements.groups[].items[].paused">${esc(num(c.paused))}</span> paused` : ""}.</p>`;
  html += `<p class="tr-small">Each one below: what he takes, what it should move, and how we’d know. The expectations are the stack’s own claims, not results.</p>`;
  const byGroup = new Map();
  for (const it of items) {
    if (!byGroup.has(it.group)) byGroup.set(it.group, { name: it.groupName, cards: [] });
    byGroup.get(it.group).cards.push(compoundCard(it));
  }
  for (const [key, g] of byGroup) {
    html += `<p class="tr-group" data-src="api_supplements.groups.${esc(key)}.name">${esc(g.name)}</p><ul class="tr-cards">${g.cards.map((c) => cardHtml(c)).join("")}</ul>`;
  }
  html += `<p class="tr-small" data-src="api_protocols.count">${esc(rulesLine(protocols))}</p>`;
  html += correctionHtml(supp);
  fill(sec, html);
  setMargin(sec, supp.as_of_date);
}

function renderTesting(exp) {
  const sec = document.getElementById("tr-testing");
  if (!exp || !Array.isArray(exp.experiments)) return fill(sec, '<p class="tr-note">The list of tests is not served.</p>');
  const split = splitExperiments(exp);
  let html = `<p class="tr-lead" data-src="api_experiments.experiments[].origin">${esc(runningLine(split))}</p>`;
  const opts = { moveLabel: "should move", knowLabel: "how we’d know", tail: "Not named beyond the claim above." };
  if (split.running.length) html += `<p class="tr-group">Running</p><ul class="tr-cards">${split.running.map((r) => cardHtml(tryCard(r), opts)).join("")}</ul>`;
  if (split.ready.length) {
    html += `<p class="tr-group"><span data-src="api_experiments.experiments[].status">${esc(countWord(split.ready.length, { capital: true }))}</span> ready to start — what he’d try, what it should move, how we’d know</p>`;
    html += `<ul class="tr-cards">${split.ready.map((r) => cardHtml(tryCard(r), opts)).join("")}</ul>`;
  } else {
    html += `<p class="tr-note" data-src="api_experiments.experiments[].status">Nothing is ready to start.</p>`;
  }
  const w = waitingLine(split);
  if (w) html += `<p class="tr-small" data-src="api_experiments.experiments[].status">${esc(w)}</p>`;
  fill(sec, html);
  const stamp = exp._meta && (exp._meta.generated_at || exp._meta.served_at);
  const t = Date.parse(String(stamp || ""));
  if (Number.isFinite(t)) setMargin(sec, new Date(t).toLocaleDateString("en-CA", { timeZone: "America/Los_Angeles" }));
}

function renderCalls(dec) {
  const sec = document.getElementById("tr-calls");
  if (!dec) return fill(sec, '<p class="tr-note">His calls are not served.</p>');
  const calls = hisCalls(dec);
  if (!calls.length) return fill(sec, '<p class="tr-note" data-src="api_decisions.count">He has published no calls yet.</p>');
  let html = `<p class="tr-small">Only the calls he chose to publish, in his own words as he typed them. The site’s side of each one is folded under it.</p>`;
  for (const c of calls) {
    const day = callDay(c);
    const fw = followedWords(c);
    html +=
      `<blockquote class="tr-quote"><p data-src="${esc(c.src)}.note">${esc(c.note)}</p>` +
      (day ? `<span class="tr-dated"><time datetime="${esc(c.date || iso(c.noteAt))}" data-src="${esc(c.src)}.date">${esc(day)}</time></span>` : "") +
      (c.recommended ? `<details class="tr-fold"><summary>what the site had recommended</summary><p data-src="${esc(c.src)}.decision">${esc(c.recommended)}</p>${fw ? `<p data-src="${esc(c.src)}.followed">${esc(fw)}</p>` : ""}</details>` : "") +
      `</blockquote>`;
  }
  fill(sec, html);
  const first = calls.find((c) => c.date);
  if (first) setMargin(sec, first.date);
}

function renderNext(cad) {
  const sec = document.getElementById("tr-next");
  const line = returnLine(cad);
  if (!line) return fill(sec, '<p class="tr-note">Nothing is scheduled.</p>');
  fill(sec, `<p class="tr-small" data-src="api_content_cadence.chronicle.next_date">${esc(line)}</p>`);
  const c = cad && cad.chronicle;
  if (c && !c.paused && c.next_date) setMargin(sec, c.next_date);
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
  const [supp, exp, protocols, dec, cad] = await Promise.all([
    getJSON("/api/supplements"),
    getJSON("/api/experiments"),
    getJSON("/api/protocols"),
    getJSON("/api/decisions"),
    getJSON("/api/content_cadence"),
  ]);
  const thr = document.getElementById("tr-through");
  if (thr) thr.textContent = dataThrough(supp && supp.as_of_date);
  renderTakes(supp, protocols);
  renderTesting(exp);
  renderCalls(dec);
  renderNext(cad);
}

if (typeof document !== "undefined" && document.getElementById("tr-takes")) {
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", main);
  else main();
}
