// ck_call.js — a page for each settled coach call (#4586, epic #4580), in the kit and
// nothing else.
//
// One template: who called it and when, the call in the coach's words, what happened, the
// verdict as the kit's Right/Wrong tag, what the simple guess said, and that coach's
// running record. `/next/v8/call/?id=<id>` is one call; with no id the page shows the
// newest settled call and a plain list of all of them, newest first. The list is the
// destination of the front page's "last settled call" number, never a menu item.
//
// Everything is read from ONE served body, GET /api/calls, so every call page shares one
// cached response. The sentences are the route's (lambdas/web/site_api_calls.py): this
// file arranges them and writes dates in words; it never grades, counts or rounds. Until
// the route is live the page prints one plain sentence and nothing else.
//
// The builders are pure and exported for tests/js/ck_call_4586.test.mjs and for the front
// page (`lastCallHTML`, `nextCallHTML`); mount() is the only thing that touches the DOM.
import { tryJSON, esc } from "/assets/js/evidence_shared.js";
import { dayInWords } from "/assets/js/entry_age.js";
import { coachComparison } from "/assets/js/coach_comparison.js";
import {
  ruleFor,
  verdictTag,
  callVerdictTag,
  callVerdictText,
  callCardHTML,
  cardLabel,
  gradedOnText,
  measuredDay,
  showcasePair,
  hasRule,
  toleranceNote,
} from "/assets/js/ck_verdict.js";

export const NOT_SERVED = "The settled calls are not served right now.";
export const NO_SUCH_CALL = "No settled call has this address.";
export const NO_RULE = "The rule this call was checked by is not served, so it is not shown as right or wrong.";
const LIST_FIRST = 8; // rows shown before the rest fold under one disclosure

const soft = (t) => (t ? `<p class="ck-soft">${esc(t)}</p>` : "");
const shortDay = (iso) => dayInWords(iso, { weekday: false });
const isCall = (c) => c && typeof c.id === "string" && c.called_short && c.happened_short && c.settled_date;

// ── where a deep page returns to (#4675) ───────────────────────────────────────
// A deep page exists only as the destination of a number or a name, and returns to where the
// reader came from, by name. The page that links one sets `from=`; the page opened reads it
// here. `from` arrives from the address bar, so it is only ever matched against a closed set
// of shapes and is never echoed as a path:
//   2026-09-20           a day page            "← Sunday, September 20"
//   call:<call id>       a call's page         "← The call"
//   coach:<persona id>   a coach's page        "← Lisa Park" (the coach's name when the page has it)
//   calls                every settled call    "← Every settled call"
//   coaches              the Coaches page      "← The AI coaches"
// Anything else, or nothing, falls back to the front page.
const RE_FROM_CALL = /^call:([a-z0-9-]{1,80})$/;
const RE_FROM_COACH = /^coach:([a-z][a-z0-9_]{1,39})$/;
const FROM_PAGES = { calls: ["call/", "Every settled call"], coaches: ["coaches/", "The AI coaches"] };
export const FRONT_BACK = "← Average Joe Matt";
// A calendar day that exists: "2026-02-30" has the shape and is still not one.
const realDay = (iso) => /^\d{4}-\d{2}-\d{2}$/.test(String(iso || "")) && !Number.isNaN(Date.parse(`${iso}T12:00:00Z`)) && new Date(`${iso}T12:00:00Z`).toISOString().slice(0, 10) === iso;
/** A link into a deep page that says where it was followed from. */
export function withFrom(href, from) {
  const f = String(from || "");
  return f ? `${href}${href.includes("?") ? "&" : "?"}from=${encodeURIComponent(f)}` : href;
}
/** `{href, text}` for the back link of a page opened with `from=`. `names` maps a persona id
 *  to the coach's name when the page has served it. */
export function backFor(from, base, names = {}) {
  const f = String(from || "");
  const named = (href, text) => ({ href, text: `← ${text}` });
  if (realDay(f) && dayInWords(f)) return named(`${base}day/?d=${f}`, dayInWords(f));
  let m;
  if ((m = RE_FROM_CALL.exec(f))) return named(callHref(base, m[1]), "The call");
  if ((m = RE_FROM_COACH.exec(f))) {
    const own = names && Object.prototype.hasOwnProperty.call(names, m[1]) ? String(names[m[1]] || "").trim() : "";
    return named(`${base}coach/?c=${encodeURIComponent(m[1])}`, own || "The coach");
  }
  if (Object.prototype.hasOwnProperty.call(FROM_PAGES, f)) return named(`${base}${FROM_PAGES[f][0]}`, FROM_PAGES[f][1]);
  return { href: base, text: FRONT_BACK };
}
/** Point the page's back links (`#ck-back`, and `#ck-back-foot` without its arrow) at `to`. */
export function setBack(to) {
  for (const id of ["ck-back", "ck-back-foot"]) {
    const a = document.getElementById(id);
    if (!a) continue;
    a.setAttribute("href", to.href);
    a.textContent = id === "ck-back" ? to.text : to.text.replace(/^← /, "");
  }
}

// A call's coach_id is the coach's short id ("sleep"); the coach page is keyed on the persona
// id ("sleep_coach"). "" when the short id is not one a call can carry.
export const personaOfCall = (shortId) => (/^[a-z]{1,30}$/.test(String(shortId || "")) ? `${shortId}_coach` : "");
/** persona id -> coach name, from every call and bet side in the served body. */
export function callNames(body) {
  const out = {};
  for (const c of callsOf(body)) {
    for (const s of [c, ...(Array.isArray(c.sides) ? c.sides : [])]) {
      const pid = personaOfCall(s && s.coach_id);
      if (pid && s.coach_name && !out[pid]) out[pid] = String(s.coach_name);
    }
  }
  return out;
}

export const callHref = (base, id) => `${base}call/?id=${encodeURIComponent(id)}`;
export const callsOf = (body) => (body && body.state === "ok" && Array.isArray(body.calls) ? body.calls.filter(isCall) : []);
// Own-value match only: the id arrives from the address bar and is never used as a key.
export const findCall = (body, id) => callsOf(body).find((c) => c.id === String(id)) || null;

// "Right" / "Wrong" for a coach's call is never printed alone (#4647): every tag comes from
// ck_verdict.js with the rule that decided it. A bet has a winner and a loser, so its line
// is the sentence naming both, beside the question the bet fixed.

// What the simple guess said, as a tag and a sentence. A call it has not been checked on
// says so; nothing here fills the gap.
function guessCard(call) {
  const g = call.simple_guess || {};
  // The simple guess is graded by the same rule as the call, so it carries the same one.
  // With no readable rule the guess is not shown as a verdict either: its heading is the label.
  const head = (g.state === "scored" && verdictTag(!!g.right, ruleFor(call, !!g.right), "The simple guess")) || cardLabel("The simple guess");
  return `<div>${head}<p>${esc(g.text || "The simple guess has not been checked against this call yet.")}</p></div>`;
}

// The graded day as a date (#4675), read from the served sentence's own words ("for
// September 20", a bet's "on September 30") — a call names its day without the year, so the
// year is the settled date's, or the one before when that would put the day after the check.
// "" when the sentence names no day (a direction call is graded on a trend, not a day).
const MONTH_NUMBER = Object.fromEntries(
  ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"].map((m, i) => [m, String(i + 1).padStart(2, "0")]),
);
export function gradedDayISO(call) {
  const m = /^([A-Z][a-z]+) (\d{1,2})$/.exec(measuredDay(call));
  const ref = String((call && (call.settled_date || call.logged_date)) || "");
  if (!m || !MONTH_NUMBER[m[1]] || !/^\d{4}-\d{2}-\d{2}$/.test(ref)) return "";
  const year = Number(ref.slice(0, 4));
  const tail = `${MONTH_NUMBER[m[1]]}-${m[2].padStart(2, "0")}`;
  const iso = `${year}-${tail}` > ref ? `${year - 1}-${tail}` : `${year}-${tail}`;
  return realDay(iso) && shortDay(iso) ? iso : "";
}
// A coach's name on a call page, as the door to that coach's page; plain text without a base.
const coachNameHTML = (call, short, name, base) => {
  const pid = base ? personaOfCall(short) : "";
  return pid ? `<a class="ck-link" href="${esc(withFrom(`${base}coach/?c=${encodeURIComponent(pid)}`, `call:${call.id}`))}">${esc(name)}</a>` : esc(name);
};

// The call in the coach's own words, on the kit's card: who and when above, the sentence
// in bold, and what it means in plain words below. With `base`, each coach's name opens that
// coach's page (#4675).
export function claimHTML(call, base = "") {
  if (!isCall(call)) return "";
  const logged = shortDay(call.logged_date);
  if (call.kind === "bet") {
    // #4673: a side whose words rested on a sensor with no reading that day comes with
    // `unsourced.text` in place of its words; that sentence is printed beside its name.
    const held = (s) => (s && s.unsourced && typeof s.unsourced.text === "string" ? s.unsourced.text.trim() : "");
    const sides = (call.sides || [])
      .filter((s) => s && s.coach_name && (s.claim || held(s)))
      .map((s) => {
        const who = coachNameHTML(call, s.coach_id, s.coach_name, base);
        return s.claim ? `<p class="ck-soft">${who} said ${esc(s.said)}: “${esc(s.claim)}”</p>` : `<p class="ck-soft">${who} said ${esc(s.said)}. ${esc(held(s))}</p>`;
      })
      .join("");
    return `<div class="ck-bet"><p class="ck-small">${esc(logged ? `A bet opened ${logged}` : "A bet between two coaches")}</p><p><b>${esc(call.called)}</b></p>${sides}</div>`;
  }
  const when = logged ? ` · ${call.sealed ? `sealed ${logged}, before day one` : `logged ${logged}`}` : "";
  return `<div class="ck-bet"><p class="ck-small">${coachNameHTML(call, call.coach_id, call.coach_name, base)}${esc(when)}</p><p><b>“${esc(call.claim)}”</b></p>${soft(call.called)}</div>`;
}

// What happened, the verdict and the simple guess: the kit's verdict pair. With `base`, the
// graded day opens that day's page (#4675).
export function outcomeHTML(call, base = "") {
  if (!isCall(call)) return "";
  const checked = shortDay(call.settled_date);
  // The day whose reading decided it, then the day the check ran: the two can be days
  // apart, and the reader is owed both.
  const graded = gradedOnText(call);
  const day = measuredDay(call);
  const iso = base ? gradedDayISO(call) : "";
  const gradedHTML = graded && iso && day ? esc(graded).replace(esc(day), `<a class="ck-link" href="${esc(withFrom(`${base}day/?d=${iso}`, `call:${call.id}`))}">${esc(day)}</a>`) : esc(graded);
  const when = `${graded ? ` ${gradedHTML}` : ""}${checked ? esc(` Checked ${checked}.`) : ""}`;
  const softHTML = (lead) => (lead || when ? `<p class="ck-soft">${esc(lead || "")}${when}</p>` : "");
  if (call.kind === "bet") {
    const cards = (call.sides || [])
      .filter((s) => s && s.coach_name)
      .map((s) => `<div>${verdictTag(!!s.right, ruleFor(call, !!s.right))}<p><b>${esc(s.coach_name)} said ${esc(s.said)}.</b></p>${softHTML(call.happened)}</div>`)
      .join("");
    return `<div class="ck-verdicts">${cards}</div>${soft((call.simple_guess && call.simple_guess.text) || "")}`;
  }
  // #4808: the tag carries the rule; the soft line says what the allowed distance is, once. A
  // call whose rule cannot be read is not shown as right or wrong: no tag and no "was right".
  const tag = callVerdictTag(call);
  const lead = tag ? [call.verdict_text, toleranceNote(call)].filter(Boolean).join(" ") : NO_RULE;
  const verdict = `<div>${tag}<p><b>${esc(call.happened)}</b></p>${softHTML(lead)}</div>`;
  return `<div class="ck-verdicts">${verdict}${guessCard(call)}</div>`;
}

// The running record beside the call: counts only, in the route's own sentence, and never
// alone (#4585): what a simple guess scored on the same calls sits directly under it.
export function recordHTML(call, body) {
  if (!isCall(call)) return "";
  const lines = (call.records || []).filter((r) => r && r.text).map((r) => `<p>${esc(r.text)}</p>${coachComparison(r.comparison, { cls: "ck-soft" })}`);
  const more = body && body.excluded && body.excluded.count ? "The record counts every checked call, including the ones with no page of their own." : "";
  return `${lines.join("")}${soft(more)}`;
}

// ── for the front page ─────────────────────────────────────────────────────────
// One settled call as a compact block that opens its page. It leads with the clearest miss
// on record (the wrong call that landed the most allowed distances out), because a wide
// hit as the lead example reads as soft grading; with no miss it is the tightest hit, and
// with neither the newest call. The label is the day it settled, whichever call it is.
// "Settled <day>: <coach> called X. It came in at Y. Wrong · not within Z either way."
// The simple guess is said here only once it has a result on this call.
// Which call leads, and why: {call, kind} with kind "wrong" (the clearest miss), "right" (the
// tightest hit, when no miss is printable) or "latest". {call: null, kind: ""} with nothing served.
// With `asOf`, the clearest miss settled in the seven days up to it comes first ("recent"),
// so the slot moves with the week; the all-time clearest miss stands in when the week has none.
export const RECENT_DAYS = 7;
const daysBefore = (iso, n) => {
  const t = Date.parse(`${iso}T12:00:00Z`);
  return Number.isFinite(t) ? new Date(t - n * 86400000).toISOString().slice(0, 10) : "";
};
export function lastCallPick(callsBody, asOf = "") {
  const all = callsOf(callsBody).filter(hasRule);
  const since = asOf ? daysBefore(asOf, RECENT_DAYS) : "";
  if (since) {
    const recent = showcasePair(all.filter((c) => c.settled_date >= since && c.settled_date <= asOf));
    if (recent.wrong) return { call: recent.wrong, kind: "recent" };
  }
  const pair = showcasePair(all);
  if (pair.wrong) return { call: pair.wrong, kind: "wrong" };
  if (pair.right) return { call: pair.right, kind: "right" };
  return { call: all[0] || null, kind: all[0] ? "latest" : "" };
}
// `jobs` maps a persona id to the coach's job in a word or two: with it, the card's first line
// names the coach and the job ("Settled Saturday, October 10 · Lisa Park, the sleep coach"),
// and the result is the bold line — the punch, not the rule (round 8b).
export function lastCallHTML(callsBody, base, asOf = "", jobs = null, { moreDoor = "" } = {}) {
  const { call } = lastCallPick(callsBody, asOf);
  if (!call) return "";
  const day = dayInWords(call.settled_date);
  const g = call.simple_guess;
  // Round 2: say which guess. The served sentence names it ("…stay at 75, the last reading before
  // the call"); otherwise it stays "The simple guess".
  const which = g && /the last reading before the call/.test(String(g.text || "")) ? "A guess that nothing changes from the last reading" : "The simple guess";
  const guess = g && g.state === "scored" && g.short ? `${which}: ${g.short}.` : "";
  const job = jobs && call.kind !== "bet" && call.coach_name && jobs[personaOfCall(call.coach_id)] ? ` · ${call.coach_name}, the ${jobs[personaOfCall(call.coach_id)]} coach` : "";
  const head = `<p class="ck-small">${esc(day ? `Settled ${day}` : "A settled call")}${esc(job)}</p>`;
  if (call.kind === "bet") {
    return `<div class="ck-bet">${head}<p>${esc(call.verdict_text)}</p><p>${esc(call.called || call.called_short)} <b>${esc(call.happened_short)}</b></p>${soft(guess)}<p><a class="ck-link" href="${esc(callHref(base, call.id))}">The whole call</a></p></div>`;
  }
  // The house rule (#4808): the shared card — tag, the call with the result in bold, one soft line.
  const card = callCardHTML(call, { full: true, extra: guess, href: callHref(base, call.id), wrap: "", moreDoor });
  return card ? `<div class="ck-bet">${head}${card}</div>` : "";
}

// "Next: <question> settles <day>." — the day is written here from the served date so the
// sentence and every other date on the page are spelled the same way.
export function nextCallHTML(callsBody) {
  const next = callsBody && callsBody.next;
  const d = next && next.state === "ok" && next.data;
  const day = d ? dayInWords(d.due_date) : "";
  if (!d || !d.question || !day) return "";
  return `<p class="ck-soft">${esc(`Next: ${d.question} settles ${day}.`)}</p>`;
}

// ── the list ───────────────────────────────────────────────────────────────────
// A row says the verdict with its rule. A bet's row names who was right; its question, which
// is the rule, is the row's own sentence.
// A row opens the call's page, which then returns here by name (#4675).
const row = (base) => (c) =>
  `<li><a href="${esc(withFrom(callHref(base, c.id), "calls"))}">${esc(`${shortDay(c.settled_date)}: ${c.called_short}`)} <span>${esc(c.kind === "bet" ? c.verdict_text || "Settled" : callVerdictText(c) || "Not shown as right or wrong: its rule is not served.")}</span></a></li>`;
export function listHTML(callsBody, base) {
  const calls = callsOf(callsBody);
  if (!calls.length) return "";
  const first = calls.slice(0, LIST_FIRST).map(row(base)).join("");
  const rest = calls.slice(LIST_FIRST);
  const older = rest.length
    ? `<details><summary>${rest.length} earlier ${rest.length === 1 ? "call" : "calls"}</summary><ul class="ck-rows ck-rows--more ck-rows--calls">${rest.map(row(base)).join("")}</ul></details>`
    : "";
  const out = callsBody.excluded && callsBody.excluded.text ? soft(callsBody.excluded.text) : "";
  return `<ul class="ck-rows ck-rows--more ck-rows--calls">${first}</ul>${older}${out}`;
}

// The page's own title and link-card text, from the call.
export function metaFor(call) {
  if (!isCall(call)) return { title: "A coach’s call, checked — Average Joe Matt", description: "" };
  const text = call.kind === "bet" ? call.verdict_text : callVerdictText(call);
  const result = text ? `${text}${call.kind === "bet" ? "" : "."}` : "";
  return { title: `${call.title} — Average Joe Matt`, description: [call.called_short, call.happened_short, result].filter(Boolean).join(" ") };
}

// ── mount ──────────────────────────────────────────────────────────────────────
const fill = (id, html) => {
  const el = document.getElementById(id);
  if (el) el.innerHTML = html;
};
const drop = (...ids) => ids.forEach((id) => document.getElementById(id)?.remove());
function setMeta(meta) {
  document.title = meta.title;
  const set = (selector, value) => {
    const el = document.querySelector(selector);
    if (el && value) el.setAttribute("content", value);
  };
  set('meta[property="og:title"]', meta.title);
  set('meta[name="description"]', meta.description);
  set('meta[property="og:description"]', meta.description);
}

export async function mount() {
  if (!document.body || document.body.dataset.ckPage !== "call") return;
  const base = document.body.dataset.ckBase || "/";
  const params = new URLSearchParams(location.search);
  const id = params.get("id") || "";
  // Back goes to the page named by `from=`, by name; without it, the front page (#4675).
  const from = params.get("from") || "";
  setBack(backFor(from, base));
  const body = await tryJSON("/api/calls");
  setBack(backFor(from, base, callNames(body)));
  const calls = callsOf(body);
  const call = id ? findCall(body, id) : calls[0];
  if (!call) {
    // Not live yet, a failed read, nothing settled, or an address that names no call:
    // one plain sentence, and the list when there is one.
    fill("ck-title", id && calls.length ? "Not a settled call" : "A coach’s call, checked");
    fill("ck-call", soft(calls.length ? NO_SUCH_CALL : (body && body.absent_text) || NOT_SERVED));
    drop("ck-outcome-section", "ck-record-section");
    fill("ck-list", listHTML(body, base));
    if (!calls.length) drop("ck-list-section");
    document.body.dataset.ckReady = "1";
    return;
  }
  const day = dayInWords(call.settled_date);
  fill("ck-label", esc(day ? `Settled ${day}` : "A settled call"));
  fill("ck-title", esc(call.called_short));
  setMeta(metaFor(call));
  fill("ck-call", claimHTML(call, base));
  fill("ck-happened", esc(call.kind === "bet" ? call.verdict_text : call.happened_short));
  fill("ck-outcome", outcomeHTML(call, base));
  fill("ck-record", recordHTML(call, body));
  fill("ck-next", nextCallHTML(body));
  if (id) {
    drop("ck-list-section");
    fill("ck-all", `<a class="ck-link" href="${esc(base)}call/">Every settled call, newest first</a>`);
  } else {
    fill("ck-list", listHTML(body, base));
    drop("ck-all");
  }
  document.body.dataset.ckReady = "1";
}

if (typeof document !== "undefined") mount();
