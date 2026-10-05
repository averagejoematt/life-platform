// ck_coach.js — one page per AI coach on the preview (#4586, epic #4580; the coach half
// of #4583): `/next/v8/coach/?c=<persona_id>`, in the kit and nothing else.
//
// The coaches are read at three distances. The last 24 hours is on the front page and
// the day pages; this week is the lead's read; THIS page is what comes next for one
// coach, in the order a reader needs it: the record with what a simple guess would have
// scored and the newest call right and wrong, what settles next and when, the bets
// against another coach and who was right, then what the coach is watching, the longer
// view and how the character is written.
//
// One template for every coach, read from routes the site already serves:
//   /api/coach/<persona_id>   stance (watch list, stage ladder), record, checked calls,
//                             the newest ask, the authored character notes
//   /api/coach_docket         open and settled bets between two coaches
//   /api/predictions          this coach's pending calls and the date each is due
//   /api/coaches              the roster: every coach's name, and the fallback when the
//                             profile is not served
//
// Rules held here: nothing is written by this module in a coach's voice; a coach's own
// words appear only as served, inside quotation marks or under a line that says whose
// they are and when they were written; every block has a plain absence sentence; no
// percentage is drawn (counts only) and the count never appears without the comparison
// (#4585); no honorific; an ISO date inside served text is put into words; the page's own
// sentences name the coach or say "this coach" — never a gendered pronoun for a persona.
//
// A deep page: it exists only as the destination of a coach's name, has no index of its
// own, and goes back to where the reader came from.
//
// The builders are pure and exported for tests/js/ck_coach_4586.test.mjs; mount() is the
// only thing that touches the DOM.
import { tryJSON, esc, fmtShort, todayPT } from "/assets/js/evidence_shared.js";
import { dayInWords, countWord } from "/assets/js/entry_age.js";
import { comparisonText } from "/assets/js/coach_comparison.js";
import { COACH_JOBS } from "/assets/js/ck_pages.js";
import { verdictTag } from "/assets/js/ck_verdict.js";
import { docketQuestion, recentLines, ledgerLine, standingAsk, shortId } from "/assets/js/v7_coaches.js";

const isDay = (s) => /^\d{4}-\d{2}-\d{2}$/.test(String(s || ""));
const num = (v) => (typeof v === "number" && Number.isFinite(v) ? v : null);
const soft = (t) => (t ? `<p class="ck-soft">${esc(t)}</p>` : "");
const small = (t) => (t ? `<p class="ck-small">${esc(t)}</p>` : "");
const shortDay = (iso) => dayInWords(iso, { weekday: false });
const words = (list) => (Array.isArray(list) ? list : []).map((s) => String(s || "").trim()).filter(Boolean);
const trim1 = (v) => (num(v) === null ? "" : String(Number(v.toFixed(1))));
const cap = (s) => String(s).charAt(0).toUpperCase() + String(s).slice(1);
const period = (s) => (/[.!?]$/.test(String(s).trim()) ? String(s).trim() : `${String(s).trim()}.`);

// A served sentence can carry a machine date ("on 2026-09-20"); the page writes dates in
// words. Formatting only: nothing else in a served sentence is touched.
export const wordDates = (text) => String(text || "").replace(/\b(\d{4}-\d{2}-\d{2})\b/g, (iso) => shortDay(iso) || iso);

// ── the address ────────────────────────────────────────────────────────────────
// The id arrives from the address bar and goes into a request path, so only the shape a
// persona id can have is ever accepted.
export const isCoachId = (id) => /^[a-z][a-z0-9_]{1,39}$/.test(String(id || ""));
/** The page for one coach — or the Coaches page when the id is not a persona id. */
export function coachHref(personaId, base = "/next/v8/") {
  return isCoachId(personaId) ? `${base}coach/?c=${encodeURIComponent(personaId)}` : `${base}coaches/`;
}
/** Where "Back" goes: the page the reader came from when it is on this site (and is not
 *  this page), otherwise the preview's Coaches page. Only a path is ever returned. */
export function backTarget(referrer, here, base = "/next/v8/") {
  const fallback = { href: `${base}coaches/`, text: "← The AI coaches" };
  try {
    const [from, at] = [new URL(String(referrer)), new URL(String(here))];
    if (from.origin !== at.origin || (from.pathname === at.pathname && from.search === at.search)) return fallback;
    return { href: `${from.pathname}${from.search}`, text: "← Back" };
  } catch {
    return fallback;
  }
}

// What each coach is for, in a reader's words, keyed on the served persona id. Static
// page copy in the third person; a coach that is not here falls back to the Coaches
// page's own job word, then to nothing (never a machine name).
export const COACH_FOR = {
  eli_marsh: "The lead. Turns what the other coaches report into one plan for the day.",
  sleep_coach: "Reads Matthew’s sleep, and the score out of 100 his wrist strap gives each morning.",
  nutrition_coach: "Reads what Matthew eats: calories, protein and whether the food log is kept.",
  mind_coach: "Reads Matthew’s habits and journal, and notices what goes unsaid.",
  physical_coach: "Reads Matthew’s training: the lifting, the walking and what his body is made of.",
  labs_coach: "Reads Matthew’s blood tests and the slow markers of long-term health.",
  glucose_coach: "Reads Matthew’s blood sugar, from a sensor worn on the arm.",
  explorer_coach: "The statistician. Asks whether a pattern the others see is real.",
};

const nameOf = (names, pid) => (names && names[pid]) || "another coach";
/** persona id -> name, from the served roster. */
export const rosterNames = (roster) => Object.fromEntries(((roster && roster.coaches) || []).filter((c) => c && c.persona_id && c.name).map((c) => [c.persona_id, c.name]));
const sittingOut = (p) => (p && p.absent ? `Sitting out${p.reason ? `: ${wordDates(p.reason)}` : ""}.` : "");

/** The profile the page draws from: the coach's own route when it is served, otherwise
 *  the roster's row for the same coach (name, record, last checked call, benched or not).
 *  null when neither names this coach. */
export function coachView(pid, profile, roster) {
  if (profile && profile.persona_id === pid && profile.name) return profile;
  const row = ((roster && roster.coaches) || []).find((c) => c && c.persona_id === pid && c.name);
  if (!row) return null;
  return {
    persona_id: pid,
    name: row.name,
    tier: row.tier,
    absent: !!row.absent,
    reason: row.reason,
    latest_checked: row.latest_checked,
    report_card: { track_record: { record: row.record, comparison: row.comparison, recent: [] } },
    partial: true,
  };
}

// ── who this is ────────────────────────────────────────────────────────────────
export function whoHTML(p) {
  if (!p) return "";
  const job = COACH_FOR[p.persona_id] || COACH_JOBS[p.persona_id] || "";
  const note = p.trait_scores && String(p.trait_scores.note || "").trim();
  return [
    job ? `<p class="ck-premise">${esc(job)}</p>` : "",
    soft("Software Matthew built with Claude. Not a person, and not a clinician."),
    p.absent ? `<p><b>${esc(sittingOut(p))}</b></p>` : "",
    note ? `<p>“${esc(period(note))}”</p>${small("How the author wrote this character.")}` : "",
  ].join("");
}

// ── watching now ───────────────────────────────────────────────────────────────
// A coach's watch list is written in its trade's terms and is never reworded here. So
// ONE item is on the page, in quotation marks, with whose words they are and their date,
// and every term in it that the gloss list knows is explained directly underneath. The
// rest of the list is one tap away.
const list = (items) => `<ul class="ck-coach">${items.map((t) => `<li><span>${esc(cap(period(wordDates(t))))}</span></li>`).join("")}</ul>`;
export function watchingHTML(p, shown = 1) {
  if (!p || p.partial) return soft("What this coach is watching is not available right now.");
  if (p.absent) return soft(`${p.name} is sitting out${p.reason ? ` (${wordDates(p.reason)})` : ""} and has nothing to watch until the readings come back.`);
  const st = p.stance || {};
  const items = words(st.focused_on_now);
  const ask = standingAsk(p.dossier && p.dossier.commitments);
  const askLine = ask
    ? `<p class="ck-soft">${esc(`The latest thing ${p.name} asked of Matthew, ${shortDay(ask.date)}: “${wordDates(ask.text)}”${isDay(ask.due_date) ? ` Due ${shortDay(ask.due_date)}.` : ""}`)}</p>`
    : "";
  if (!items.length) {
    const none = p.tier === "lead" ? `${p.name} is the lead and keeps no watch list: the lead reads what the other coaches report.` : `${p.name} has no watch list on record right now.`;
    return `${soft(none)}${askLine}`;
  }
  // Whose words these are, and how old. A list the coach wrote carries its date; a list
  // that belongs to the coach's current stage is the author's, and is not this week's.
  const whose =
    st.source === "stance" && isDay(st.as_of)
      ? `In ${p.name}’s own words, written ${shortDay(st.as_of)}.`
      : st.source === "ladder"
        ? "Set by the author for the stage Matthew is in. Not written this week."
        : "As recorded, with no date on it.";
  const first = items.slice(0, shown);
  const firstHTML = first.map((t) => `<p>“${esc(cap(period(wordDates(t))))}”</p>${glossLines(t).map((g) => soft(g)).join("")}`).join("");
  const rest = items.slice(shown);
  const more = rest.length ? `<details><summary>${esc(`${cap(countWord(rest.length))} more on the list`)}</summary>${list(rest)}</details>` : "";
  const aside = words(st.set_aside_for_now);
  const asideHTML = aside.length ? `<details><summary>${esc(`What ${p.name} has set aside for now`)}</summary>${list(aside)}</details>` : "";
  const changed = String(st.how_my_read_changed || "").trim();
  const changedHTML = changed ? `<details><summary>${esc(`How ${p.name}’s read changed`)}</summary><p class="ck-soft">“${esc(wordDates(changed))}”</p></details>` : "";
  return `${small(whose)}${firstHTML}${more}${asideHTML}${changedHTML}${askLine}`;
}

// ── next: what settles, and when ───────────────────────────────────────────────
const involves = (item, pid) => !!item && (item.coach_a === pid || item.coach_b === pid);
const otherOf = (item, pid) => (item.coach_a === pid ? item.coach_b : item.coach_a);
export const betsOf = (docket, pid, key) => ((docket && docket[key]) || []).filter((d) => involves(d, pid)).sort((a, b) => String(a.resolution_date).localeCompare(String(b.resolution_date)));
/** This coach's pending calls that carry a due date, soonest first. */
export function pendingCalls(predictions, pid) {
  const short = shortId(pid);
  return ((predictions && predictions.predictions) || [])
    .filter((c) => c && c.status === "pending" && isDay(c.due_date) && String(c.text || "").trim() && (!c.coach_id || c.coach_id === short))
    .sort((a, b) => a.due_date.localeCompare(b.due_date) || String(a.date).localeCompare(String(b.date)));
}
const shiftDay = (iso, days) => new Date(Date.parse(`${iso}T12:00:00Z`) + days * 86400000).toISOString().slice(0, 10);
/** The day a call is ABOUT, when its own words name one: a machine date in the sentence,
 *  or "tonight" / "tomorrow" counted from the day it was said. "" when it names none. */
export function statedDay(call) {
  const t = String((call && call.text) || "");
  const iso = /\b(\d{4}-\d{2}-\d{2})\b/.exec(t);
  if (iso) return iso[1];
  if (!isDay(call && call.date)) return "";
  if (/\btomorrow\b/i.test(t)) return shiftDay(call.date, 1);
  if (/\btonight\b/i.test(t)) return call.date;
  return "";
}
/** A pending call that can be listed as coming up: due today or later and within this
 *  year, and — when its words name a day — that day is neither before the day it was said
 *  nor already gone. Some "tomorrow" number calls were stored with a check date two weeks
 *  out (and a few years out); those are still waiting, but they are not what comes next. */
export function isUpcoming(call, today) {
  if (!call || !isDay(call.due_date) || call.due_date < today || call.due_date.slice(0, 4) !== today.slice(0, 4)) return false;
  const about = statedDay(call);
  if (!about) return true;
  return !(isDay(call.date) && about < call.date) && about >= today;
}
export function nextHTML(p, docket, predictions, names, today, shown = 2) {
  if (!p) return soft("What settles next is not available right now.");
  const pid = p.persona_id;
  const bets = docket ? betsOf(docket, pid, "open").filter((b) => isDay(b.resolution_date)) : [];
  const calls = pendingCalls(predictions, pid);
  if (p.tier === "lead" && !bets.length && !calls.length) return soft(`${p.name} is the lead. The lead makes no dated calls and has no bet open, so nothing is waiting to settle.`);
  const out = [];
  const ahead = calls.filter((c) => isUpcoming(c, today));
  const older = calls.length - ahead.length;
  const nextBet = bets.find((b) => b.resolution_date >= today);
  const first = [nextBet && nextBet.resolution_date, ahead[0] && ahead[0].due_date].filter(Boolean).sort()[0];
  if (first) {
    const what = [
      nextBet && nextBet.resolution_date === first ? `a bet against ${nameOf(names, otherOf(nextBet, pid))} settles` : "",
      ahead[0] && ahead[0].due_date === first ? "a call comes due to be checked" : "",
    ].filter(Boolean);
    out.push(`<p><b>${esc(`${dayInWords(first)}:`)}</b> ${esc(`${what.join(", and ")}.`)}</p>`);
  }
  if (!predictions) out.push(soft(`${p.name}’s open calls are not available right now.`));
  else if (!calls.length) out.push(soft(`${p.name} has no call waiting to be checked.`));
  else {
    out.push(soft(`${cap(countWord(calls.length))} ${calls.length === 1 ? "call is" : "calls are"} waiting to be checked.`));
    const rows = ahead
      .slice(0, shown)
      .map((c) => `<li><span class="ck-rows__key"><time datetime="${esc(c.due_date)}">${esc(fmtShort(c.due_date))}</time></span><span>“${esc(wordDates(c.text))}” <span class="ck-small">${esc(isDay(c.date) ? `Said ${fmtShort(c.date)}.` : "")}</span></span></li>`)
      .join("");
    if (rows) out.push(`<ul class="ck-rows">${rows}</ul>`);
    if (older) out.push(soft(`${cap(countWord(older))} older ${older === 1 ? "call is" : "calls are"} still waiting to be checked.`));
  }
  if (!docket) out.push(soft("The bets between coaches are not available right now."));
  else if (bets.length) out.push(soft(`${cap(countWord(bets.length))} open ${bets.length === 1 ? "bet" : "bets"} against another coach: the next section has ${bets.length === 1 ? "it" : "them"}.`));
  return out.join("");
}

// ── the longer view ────────────────────────────────────────────────────────────
// On the wire only as a ladder of stages (the author's, keyed on where Matthew is now)
// with the gate that opens the next one. A coach with no ladder gets the plain sentence:
// nothing here is composed to fill the gap.
export function longerHTML(p) {
  if (!p || p.partial) return soft("The longer view is not available right now.");
  if (p.absent) return soft(`${p.name} has no longer view on record while sitting out.`);
  const st = p.stance || {};
  const ladder = (Array.isArray(st.ladder) ? st.ladder : []).filter((s) => s && String(s.headline || "").trim());
  if (ladder.length < 2) return soft(`${p.name} has no longer view on record yet.`);
  const nowId = st.rung && st.rung.stage_id;
  const rows = ladder.map((s) => `<li><span>${s.stage_id === nowId ? `<b>${esc(period(s.headline))}</b> Now.` : esc(period(s.headline))}</span></li>`).join("");
  const plan = st.rung && String(st.rung.plan || "").trim();
  const gate = String(st.graduation_gate || "").trim();
  return [
    small("The stages this coach works through, set by the author."),
    `<ol class="ck-rows ck-rows--steps">${rows}</ol>`,
    plan ? `<p>${esc(`The plan for this stage: ${period(plan)}`)}</p>` : "",
    gate ? soft(`What opens the next stage: ${period(gate)}`) : "",
  ].join("");
}

// ── the record, never alone ────────────────────────────────────────────────────
const trackOf = (p) => (p && p.report_card && p.report_card.track_record) || {};
/** The comparison sentence, saying whose record it is. /api/coach/<id> serves the
 *  comparison for THAT coach's calls alone (its n is the coach's own count), so the
 *  served "Across 24 checked calls, …" becomes "Across Lisa Park’s 24 checked calls, …".
 *  Any other served wording is printed untouched. */
export function ownComparison(p, cmp) {
  const sentence = comparisonText(cmp);
  const n = trackOf(p).record && trackOf(p).record.n;
  return sentence.replace(/^Across (\d+) checked calls\b/, (all, k) => (Number(k) === n ? `Across ${p.name}’s ${k} checked calls` : all));
}
export const SIMPLE_GUESS = "The simple guess is that nothing changes from the last reading.";
export function recordHTML(p) {
  if (!p) return soft("The record is not available right now.");
  const t = trackOf(p);
  const r = t.record;
  if (!r || num(r.n) === null || r.n < 1 || num(r.confirmed) === null) {
    return soft(p.tier === "lead" ? `${p.name} is the lead. The lead makes no checked calls, so there is no record here.` : `No call by ${p.name} has been checked yet.`);
  }
  // Counts only. With no comparison on the wire the count is not drawn at all (#4585).
  const sentence = t.comparison && String(t.comparison.sentence || "").trim();
  if (!sentence) return soft(comparisonText(null));
  const through = isDay(r.through) ? ` through ${shortDay(r.through)}` : "";
  return `<div class="ck-today ck-today--ruled"><p class="ck-soft">Right so far</p><p class="ck-big">${r.confirmed}<span>of ${r.n} checked calls</span></p><p>${esc(ownComparison(p, t.comparison))} ${esc(SIMPLE_GUESS)}</p>${small(`${p.name}’s calls alone${through}. Code checks each call against what happened; no coach does the marking.`)}</div>`;
}
/** The newest checked call of each kind, in reader words. */
export function verdictPair(p) {
  const recent = [...((trackOf(p).recent || []).filter((r) => r && r.status))].sort((a, b) => String(b.date).localeCompare(String(a.date)));
  const lines = recentLines(recent, p && p.name);
  const pair = { right: lines.find((l) => l.verdict === "right") || null, wrong: lines.find((l) => l.verdict === "wrong") || null };
  const last = ledgerLine(p && p.latest_checked, p && p.name);
  if (last && !pair[last.verdict]) pair[last.verdict] = last;
  return pair;
}
export function verdictsHTML(p) {
  if (!p) return "";
  const { right, wrong } = verdictPair(p);
  if (!right && !wrong) return "";
  const card = (line, tag) =>
    line
      ? `<div>${verdictTag(tag === "Right", line.rule)}<p><b>${esc(line.text)}</b></p>${soft(line.checked)}</div>`
      : `<div>${soft(`No call by ${p.name} has been checked and found ${tag.toLowerCase()} yet.`)}</div>`;
  return `<div class="ck-verdicts">${card(right, "Right")}${card(wrong, "Wrong")}</div>`;
}

// ── disagreements ──────────────────────────────────────────────────────────────
// A bet is a yes-or-no question with a date, built from the docket's criterion; each
// side is yes or no. What each coach argued is one tap away, in its own words.
const sideWord = (item, pid) => (item.sides && typeof item.sides[pid] === "boolean" ? (item.sides[pid] ? "yes" : "no") : "");
const argued = (item, pid, names) => {
  const claims = item.claims || {};
  const rows = [pid, otherOf(item, pid)]
    .filter((id) => String(claims[id] || "").trim())
    .map((id) => `<p class="ck-soft"><b>${esc(id === pid ? names[pid] || "This coach" : nameOf(names, id))}:</b> “${esc(wordDates(claims[id]))}”</p>`)
    .join("");
  return rows ? `<details><summary>What each one argued</summary>${rows}</details>` : "";
};
export function disagreementsHTML(p, docket, names) {
  if (!p || !docket) return soft("The bets between coaches are not available right now.");
  const pid = p.persona_id;
  const who = { ...names, [pid]: p.name };
  const [open, settled] = [betsOf(docket, pid, "open"), betsOf(docket, pid, "resolved").reverse()];
  if (!open.length && !settled.length) return soft(`${p.name} has no bet against another coach, open or settled.`);
  const won = settled.filter((d) => d.winner === pid).length;
  const lost = settled.filter((d) => d.loser === pid).length;
  const tally = settled.length ? soft(`Bets settled so far: ${won ? countWord(won) : "none"} won, ${lost ? countWord(lost) : "none"} lost.`) : soft(`No bet of ${p.name}’s has settled yet.`);
  const openCards = open.map((d) => {
    const other = otherOf(d, pid);
    const q = docketQuestion(d.criterion, d.resolution_date) || String(d.topic || "").trim();
    const [mine, theirs] = [sideWord(d, pid), sideWord(d, other)];
    const says = mine && theirs ? soft(`${p.name} says ${mine}. ${nameOf(who, other)} says ${theirs}.`) : "";
    return `<div class="ck-bet">${small(`Against ${nameOf(who, other)} · settles ${dayInWords(d.resolution_date)}`)}<p><b>${esc(q)}</b></p>${says}${argued(d, pid, who)}</div>`;
  });
  const settledCards = settled.map((d) => {
    const other = otherOf(d, pid);
    const q = docketQuestion(d.criterion, d.resolution_date) || String(d.topic || "").trim();
    const result = num(d.actual_value) !== null ? ` The result was ${trim1(d.actual_value)}.` : "";
    const verdict = d.winner && d.loser ? `${nameOf(who, d.winner)} was right. ${nameOf(who, d.loser)} was wrong.${result}` : "It settled with no winner.";
    return `<div class="ck-bet">${small(`Against ${nameOf(who, other)} · settled ${shortDay(d.resolved_date || d.resolution_date)}`)}<p><b>${esc(`The question was: ${q}`)}</b></p><p>${esc(verdict)}</p>${argued(d, pid, who)}</div>`;
  });
  return `${tally}${openCards.join("")}${settledCards.join("")}`;
}

// ── how the character is written ───────────────────────────────────────────────
export function personaHTML(p) {
  if (!p || p.partial) return soft("The character notes are not available right now.");
  const rules = words(p.character && p.character.principles).slice(0, 3);
  const arc = p.character && String(p.character.arc || "").trim();
  const creed = String(p.philosophy || "").trim();
  const more = creed ? rules : rules.slice(1);
  if (!rules.length && !arc && !creed) return soft(`${p.name} has no character notes on record.`);
  return [
    small("Written by the author as character design. Not generated day to day, and not a measurement."),
    creed ? `<p>“${esc(creed)}”</p>` : "",
    !creed && rules.length ? `<p>“${esc(rules[0])}”</p>` : "",
    arc ? soft(`The arc this coach was given: ${period(arc.charAt(0).toLowerCase() + arc.slice(1))}`) : "",
    more.length ? `<details><summary>${esc(more.length === 1 ? "One more of this coach’s rules" : `${cap(countWord(more.length))} more of this coach’s rules`)}</summary><ul class="ck-coach">${more.map((r) => `<li><span>“${esc(r)}”</span></li>`).join("")}</ul></details>` : "",
  ].join("");
}

// ── the terms ──────────────────────────────────────────────────────────────────
// A coach's served words use its trade's terms. Each one that appears on the page gets a
// plain line here; one that does not appear is not listed.
export const TERMS = [
  [/\brecovery\b/i, "Recovery", "his wrist strap’s morning score out of 100"],
  [/\bHRV\b|heart-rate variability/i, "HRV", "heart-rate variability: how much the gap between heartbeats changes overnight, as the wrist strap measures it"],
  [/deep[- ]sleep|slow-wave/i, "Deep sleep", "also called slow-wave sleep: the share of the night spent in the deepest stage"],
  [/\bREM\b|dreaming sleep/i, "REM", "the dreaming stage of sleep"],
  [/\bEWMA\b|running average/i, "Running average", "also written EWMA: an average that counts recent days more than older ones"],
  [/(seven|7)-(night|day) average/i, "Seven-day average", "the average of the last seven readings"],
  [/zone 2/i, "Zone 2", "steady, easy cardio, such as a brisk walk"],
  [/regression[- ]to[- ](the[- ])?mean|mean reversion/i, "Regression to the mean", "an unusual reading tends to be followed by a more ordinary one"],
  [/\bDEXA\b/i, "DEXA", "a body scan that measures fat, muscle and bone"],
  [/\bCGM\b/i, "CGM", "a worn sensor that reads blood sugar through the day"],
];
/** "Deep sleep: also called slow-wave sleep: …" for every known term in a sentence. */
export const glossLines = (text) => TERMS.filter(([rx]) => rx.test(String(text || ""))).map(([, term, gloss]) => `${term}: ${period(gloss)}`);
export function termsHTML(html) {
  const text = String(html || "").replace(/<[^>]*>/g, " ");
  const rows = TERMS.filter(([rx]) => rx.test(text)).map(([, term, gloss]) => `<li><span class="ck-rows__key">${esc(term)}</span><span>${esc(cap(period(gloss)))}</span></li>`);
  if (!rows.length) return "";
  // One tap away, so the page keeps its length; the line that opens it names the terms.
  const named = TERMS.filter(([rx]) => rx.test(text)).map(([, term]) => term);
  const summary = named.length < 2 ? named[0] : `${named.slice(0, -1).join(", ")} and ${named[named.length - 1]}`;
  return `<details><summary>${esc(summary)}</summary><ul class="ck-rows">${rows.join("")}</ul></details>`;
}

// ── mount ──────────────────────────────────────────────────────────────────────
const fill = (id, html) => {
  const el = document.getElementById(id);
  if (el) el.innerHTML = html;
};
const SECTION_IDS = ["ck-who", "ck-record", "ck-verdicts", "ck-next", "ck-disagreements", "ck-watching", "ck-longer", "ck-persona"];

export async function mount() {
  const page = document.body && document.body.dataset.ckPage;
  if (page !== "coach") return;
  const base = document.body.dataset.ckBase || "/next/v8/";
  const back = backTarget(document.referrer, location.href, base);
  for (const id of ["ck-back", "ck-back-foot"]) {
    const a = document.getElementById(id);
    if (a) {
      a.setAttribute("href", back.href);
      a.textContent = id === "ck-back" ? back.text : back.text.replace(/^← /, "");
    }
  }
  const asked = new URLSearchParams(location.search).get("c") || "";
  const pid = isCoachId(asked) ? asked : "";
  const [profile, roster, docket] = pid ? await Promise.all([tryJSON(`/api/coach/${encodeURIComponent(pid)}`), tryJSON("/api/coaches"), tryJSON("/api/coach_docket")]) : [null, null, null];
  const p = pid ? coachView(pid, profile, roster) : null;
  if (!p) {
    // No coach named, or a name the roster does not have: one sentence and the way back.
    const known = pid && !(roster && Array.isArray(roster.coaches));
    fill("ck-title", known ? "Not available right now" : "No coach by that name");
    fill("ck-who", `${soft(known ? "This coach’s page is not available right now." : "This address does not name one of the AI coaches.")}<p><a class="ck-link" href="${esc(base)}coaches/">The AI coaches, and their record</a></p>`);
    document.querySelectorAll("[data-ck-coach-section]").forEach((el) => el.remove());
    document.body.dataset.ckReady = "1";
    return;
  }
  const predictions = p.tier === "lead" ? null : await tryJSON(`/api/predictions?coach_id=${encodeURIComponent(shortId(pid))}&status=pending&limit=200`);
  const names = rosterNames(roster);
  const today = todayPT();
  fill("ck-title", esc(p.name));
  document.title = `${p.name}, AI coach — Average Joe Matt`;
  const parts = {
    "ck-who": whoHTML(p),
    "ck-watching": watchingHTML(p),
    "ck-next": nextHTML(p, docket, p.tier === "lead" ? { predictions: [] } : predictions, names, today),
    "ck-longer": longerHTML(p),
    "ck-record": recordHTML(p),
    "ck-verdicts": verdictsHTML(p) || soft(`No checked call by ${p.name} is on record yet.`),
    "ck-disagreements": disagreementsHTML(p, docket, names),
    "ck-persona": personaHTML(p),
  };
  for (const [id, html] of Object.entries(parts)) fill(id, html);
  const terms = termsHTML(SECTION_IDS.map((id) => parts[id]).join(" "));
  if (terms) fill("ck-terms", terms);
  else document.getElementById("ck-terms-section")?.remove();
  document.body.dataset.ckReady = "1";
}

if (typeof document !== "undefined") mount();
