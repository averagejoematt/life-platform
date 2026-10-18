// ck_pages.js — the kit pages of the living front page (#4586, epic #4580): the front
// page, This week (round 8), Start here, Story and Coaches. Candidates on the preview path.
//
// The front page reads ONE document, /api/edition (#4582): one Pacific `as_of`, one
// `day_n`, and blocks that each carry state / as_of / source / absent_text / data. A
// block that is absent, stale or unavailable prints its own sentence — never a blank,
// a zero or a number from another day. The front page reads nothing else (#4582 box 1: the
// coach lines of the last seven days, the settled calls and the sheet's level are blocks of
// the edition too); the week page reads only the chapter's published transcript besides. The
// other layer-2 pages read the edition for the facts they share with the front page, plus the
// public routes that already exist.
//
// The look is the kit and nothing else (docs/design/v8/README.md): every class below is
// a `ck-` class from clean.css. Standing rules held here: no count of earlier starts, no
// "Dr.", no percentage on fewer than 20 items, no first-person sentence that is not
// either Matthew's own dated words or static draft copy in the page shell.
//
// The builders are pure and exported so tests/js/ck_pages_4586.test.mjs can drive them
// from fixtures; mount() is the only thing that touches the DOM.
import { tryJSON, esc } from "/assets/js/evidence_shared.js";
import { dayInWords } from "/assets/js/entry_age.js";
import { comparisonText } from "/assets/js/coach_comparison.js";
import * as F from "/assets/js/ck_front.js";
import { sheetLine } from "/assets/js/ck_sheet.js";
import { lastCallHTML, lastCallPick, nextCallHTML, withFrom } from "/assets/js/ck_call.js";
import { verdictTag, callCardHTML, gradedOnText, showcasePair, hasRule, ruleless, sharedToleranceNote } from "/assets/js/ck_verdict.js";

export const MIN_PERCENT_N = 20; // plan §6: never a percentage (or its picture) on fewer items

// ── small helpers ──────────────────────────────────────────────────────────────
const num = (v) => (typeof v === "number" && Number.isFinite(v) ? v : null);
const fmt1 = (v) => (num(v) === null ? "" : v.toFixed(1));
const trim1 = (v) => (num(v) === null ? "" : String(Number(v.toFixed(1))));
const usable = (b) => !!b && (b.state === "ok" || b.state === "stale") && b.data != null;
const soft = (text) => (text ? `<p class="ck-soft">${esc(text)}</p>` : "");
const small = (text) => (text ? `<p class="ck-small">${esc(text)}</p>` : "");
const label = (text) => `<p class="ck-label">${esc(text)}</p>`;
const absent = (b, fallback) => soft((b && b.absent_text) || fallback);
const shortDay = (iso) => dayInWords(iso, { weekday: false });
// A chapter's published excerpt -> its first COMPLETE sentence, skipping an editor's-note
// paragraph. "" when the excerpt was cut before the first sentence ended (the manifest
// truncates with "…"), so a clipped half-sentence never reaches the page.
export function summarySentence(excerpt) {
  for (const para of String(excerpt || "").split(/\n\s*\n/)) {
    const plain = para.replace(/[*_]/g, "").trim();
    if (!plain || /^editor[’']s note/i.test(plain)) continue;
    const m = /^.*?[.!?](?=\s|$)/.exec(plain);
    return m ? m[0].trim() : "";
  }
  return "";
}
// The one weight unit label on every kit page (red team 2026-10-17: "lbs" beside "lb"). A served
// stats line spells it "lbs"; lbText rewrites it before it is printed.
export const LB = "lb";
export const lbText = (text) => String(text || "").replace(/\blbs\b/g, LB);
// Pounds gone between two weights, ONE rounding (fmt1 of the difference): every page that prints
// a pounds-lost figure beside the two weights it came from uses this, so the three always agree.
export const poundsDown = (start, now) => (num(start) === null || num(now) === null ? "" : fmt1(start - now));
const listWords = (items) => (items.length < 2 ? items.join("") : `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`);
const NUMBER_WORDS = ["No", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten"];
const countWord = (n) => NUMBER_WORDS[n] || String(n);

// What each coach is for, in a reader's words, keyed on the served persona id. A coach
// that is not here shows its name and record with no job line (never a machine name).
export const COACH_JOBS = {
  // Round 3: one short form for every coach, a few words each.
  eli_marsh: "Lead, the day's plan",
  sleep_coach: "Sleep",
  explorer_coach: "Statistics",
  nutrition_coach: "Food and protein",
  mind_coach: "Mind and habits",
  physical_coach: "Training",
  labs_coach: "Blood tests",
  glucose_coach: "Blood sugar",
};

// ── the header ─────────────────────────────────────────────────────────────────
// "Saturday, October 3 · Day 28" — both from the edition's one as_of and day_n.
export function headerDay(edition) {
  const e = edition || {};
  const day = dayInWords(e.as_of);
  if (!day) return "";
  return num(e.day_n) !== null && e.day_n >= 1 ? `${day} · Day ${e.day_n}` : day;
}

// ── his words ──────────────────────────────────────────────────────────────────
// Fresh: the quote with its date. Stale, absent or unavailable: the block's own plain
// sentence. Silence is never filled.
export function hisWordsFresh(block) {
  return !!block && block.state === "ok" && !!(block.data && block.data.text);
}
export function hisWordsHTML(block) {
  if (hisWordsFresh(block)) {
    const d = block.data;
    const asked = d.prompt || d.question ? small(`Asked: ${d.prompt || d.question}`) : "";
    return `${label(`In his own words · ${shortDay(d.date) || d.date_text || ""}`)}<p class="ck-quote">“${esc(d.text)}”</p>${asked}`;
  }
  return `${label("In his own words")}${absent(block, "Nothing in his own words is served right now.")}`;
}

// ── the chapter lead, with the player ──────────────────────────────────────────
// `held`: the episode list's own hold marker (/panelcast/episodes.json `pending`, reason
// held_for_review) for this chapter's week — then the line says the episode is held, never that
// there is none yet (red team 2026-10-17: an episode held since October 9 read "no episode yet").
export function podcastHeld(episodes, weekNumber) {
  const p = episodes && episodes.pending;
  return !!p && p.reason === "held_for_review" && num(p.week) !== null && p.week === weekNumber;
}
export function playerHTML(podcast, { held = false, caption = "" } = {}) {
  if (!usable(podcast) || !podcast.data.mp3_url) {
    if (held) return small("This chapter’s podcast episode is recorded and held for review before it publishes.");
    return small((podcast && podcast.absent_text) || "No podcast episode for this chapter yet.");
  }
  const p = podcast.data;
  const mins = num(p.duration_minutes) !== null ? ` · ${p.duration_minutes} min` : "";
  const who = p.guest ? `The podcast this week: ${p.guest_domain ? `the ${p.guest_domain} coach, ` : ""}${p.guest}${mins}.` : `The podcast this week${mins}.`;
  // `caption`: the sentence under the player when the episode is not this chapter's own (the
  // newest published one, played under a newer chapter whose episode is held or not yet made).
  return `<audio controls preload="none" src="${esc(p.mp3_url)}" aria-label="${esc(p.title || "This week’s podcast episode")}"></audio>${small(caption || who)}`;
}
// The newest episode in the served list that has audio, as a podcast block the player can
// take, with the caption that says whose week it is. null when the list has none (site-to-A
// round 1, #4580 ST1: the only player was gated on the held episode, so no audio rendered
// anywhere and every row linked a bare .mp3).
export function newestEpisode(episodes) {
  const eps = ((episodes && episodes.episodes) || []).filter((e) => e && e.url && e.title).sort((a, b) => String(b.date).localeCompare(String(a.date)));
  const e = eps[0];
  if (!e) return null;
  const mins = num(e.duration_sec) !== null ? Math.round(e.duration_sec / 60) : null;
  const week = num(e.week) !== null ? `, for week ${e.week}` : "";
  const guest = e.guest_name ? `: ${e.guest_name}` : "";
  const caption = `The newest episode${week}${guest}${mins !== null ? ` · ${mins} min` : ""}.`;
  return { block: { state: "ok", data: { mp3_url: e.url, title: e.title, guest: e.guest_name || "", duration_minutes: mins } }, caption, episode: e };
}

// The week number a chapter's label names ("Week 5" -> 5); null for a prologue.
export const weekNumberOf = (label) => {
  const m = /^Week (\d+)\b/.exec(String(label || ""));
  return m ? Number(m[1]) : null;
};
// THE HELD STATE (red team 2026-10-17: on day 42 Story showed week 5 as "the latest chapter" with
// no word about week 6). A chapter publishes only after Matthew approves it, so a week can be
// written and waiting — but whether one IS waiting is a fact only the chronicle can state. What the
// page reads, in order (site-to-A round 1: the line was week arithmetic from the latest chapter's
// date, and said "Week 6 is waiting for Matthew’s approval" on the night week 6 published):
//   - the served chronicle status, when the route carries it: `chronicle.latest.status` on the
//     edition, the journal or the chapter block (lane E of #4580 adds it; bound here defensively —
//     absent, the page falls back to the next rule). A status that says held/pending/awaiting
//     approval prints the held line, naming the week when the status names one; "published"
//     and anything unrecognised print nothing.
//   - the chronicle's own hold marker on /journal/posts.json (`pending`: {week, reason}, written
//     by emails/chronicle_store.held_week): "Week N is held before publishing."
//   - nothing. The latest published chapter and its date are already on the page ("Latest
//     chapter · Week 5 (written October 6)"); no held week is ever inferred from the calendar.
// `nextBlock` is kept for the draft's due date beside a served held line.
export const CHAPTER_DAYS = 7;
const HELD_STATUS = new Set(["held", "pending", "waiting", "awaiting_approval", "waiting_approval", "held_for_review", "drafted", "draft"]);
// The served status, from whichever document carries it: {status, week} or null.
export function chronicleStatus(edition, journal, block) {
  for (const doc of [edition, journal, block && block.data]) {
    const latest = doc && doc.chronicle && doc.chronicle.latest;
    const raw = latest && (typeof latest.status === "string" ? latest.status : latest.status && typeof latest.status.state === "string" ? latest.status.state : "");
    if (raw) return { status: raw.trim().toLowerCase(), week: num(latest.week) !== null ? latest.week : num(latest.status && latest.status.week) !== null ? latest.status.week : null };
  }
  return null;
}
export function heldChapterLine(block, edition, journal, nextBlock = null) {
  if (!usable(block)) return "";
  const n = weekNumberOf(block.data.week_label);
  if (n === null) return "";
  const ch = nextBlock && nextBlock.data && nextBlock.data.chapter;
  const due = usable(ch) ? dayInWords(ch.data.date) : "";
  const served = chronicleStatus(edition, journal, block);
  if (served) {
    if (!HELD_STATUS.has(served.status)) return "";
    const which = served.week !== null && served.week > n ? `Week ${served.week}` : "The next chapter";
    return due ? `${which} is written and held before publishing; its draft was due ${due}.` : `${which} is written and held before publishing.`;
  }
  const p = journal && journal.pending;
  if (p && num(p.week) !== null && p.week > n) return `Week ${p.week} is held before publishing.`;
  return "";
}
// The chapter's teaser is the chapter's own dek, printed as served (site-to-A round 1: a rewrite
// turned "crossed 310 pounds … 18.5 pounds gone" into "went below 310 … 18.4" from rounded values,
// editing a quoted sentence of the chapter). The chapter's words are the chapter's; nothing is
// recomputed here. `teaserText` stays as the one door the Story lead prints the dek through.
export function teaserText(dek) {
  return String(dek || "");
}
// "Next chapter due <day>." — or, when the cadence says the date is a draft and not a promise,
// what actually happens on it.
export function nextChapterLine(nextBlock) {
  const ch = nextBlock && nextBlock.data && nextBlock.data.chapter;
  const day = usable(ch) ? dayInWords(ch.data.date) : "";
  if (!day) return (ch && ch.state !== "ok" && ch.absent_text) || "";
  return ch.data.drafted_not_promised ? `The next draft is due ${day}; it publishes once Matthew approves it.` : `Next chapter due ${day}.`;
}
export function chapterHTML(block, nextBlock, { heading = "h1", player = true, listenHref = "", held = "", podcastHeld: podHeld = false, asOf = "", frame = "", fallbackPlayer = null } = {}) {
  if (!usable(block)) return absent(block, "The latest chapter is not served right now.");
  const c = block.data;
  // "New this week" only while the chapter is under a week old on the edition's day (round 2:
  // "New this week · Week 5" on a day week 5 was last week's); otherwise its date says how old.
  const week = c.week_label || "";
  const age = (Date.parse(`${asOf}T12:00:00Z`) - Date.parse(`${c.date}T12:00:00Z`)) / 86400000;
  const fresh = block.state === "ok" && (!asOf || (Number.isFinite(age) && age <= CHAPTER_DAYS));
  const written = shortDay(c.date);
  // Round 2 (story, G10): the kit's accent badge is "New this week" only; a chapter the edition
  // marks stale, or older than a week, takes the neutral label, so green never claims newness.
  const badge = fresh
    ? `<span class="ck-badge">${esc(`New this week${week ? ` · ${week}` : ""}`)}</span>`
    : `<span class="ck-label">${esc(`Latest chapter${week ? ` · ${week}` : ""}${written ? ` (written ${written})` : ""}`)}</span>`;
  const read = c.url ? `<a class="ck-btn" href="${esc(c.url)}">Read${num(c.read_minutes) !== null ? ` · ${c.read_minutes} min` : ""}</a>` : "";
  const pod = c.podcast;
  const hasPod = usable(pod) && pod.data.mp3_url;
  const listen =
    !player && hasPod && listenHref
      ? `<a class="ck-btn ck-btn--ghost" href="${esc(listenHref)}">Listen${num(pod.data.duration_minutes) !== null ? ` · ${pod.data.duration_minutes} min` : ""}</a>`
      : "";
  // With the held line printed, the next date is said plainly: the approval is already said once.
  // The held line names the next draft itself; then the next-date line is not repeated.
  const nextLine = held ? (/draft (?:is|was) due/.test(held) ? "" : nextChapterLine(nextBlock).replace(/; it publishes once Matthew approves it\.$/, ".")) : nextChapterLine(nextBlock);
  // The front page runs one sentence of the chapter's own summary; Story runs it whole.
  const dek = player ? teaserText(c.dek) : summarySentence(c.dek) || c.dek;
  return [
    badge,
    `<${heading}>${esc(c.title)}</${heading}>`,
    // Story opens on a chapter title, so one sentence says what the site is before the chapter does.
    frame ? `<p class="ck-soft">${esc(frame)}</p>` : "",
    small(fresh ? `Written by AI from the record on ${shortDay(c.date)}. Matthew reads each chapter before it publishes.` : "Written by AI from the record. Matthew reads each chapter before it publishes."),
    dek ? `<p class="ck-premise ck-soft">${esc(dek)}</p>` : "",
    read || listen ? `<div class="ck-actions">${read}${listen}</div>` : "",
    // With this chapter's own episode held or not yet made, the newest published one plays here,
    // its caption naming its week; the held sentence then joins the line below instead of standing alone.
    player ? (!hasPod && fallbackPlayer ? playerHTML(fallbackPlayer.block, { caption: fallbackPlayer.caption }) : playerHTML(pod, { held: podHeld })) : "",
    !player && hasPod && pod.data.guest ? small(`On the podcast: ${pod.data.guest_domain ? `the ${pod.data.guest_domain} coach, ` : ""}${pod.data.guest}.${nextLine ? ` ${nextLine}` : ""}`) : small([!hasPod && fallbackPlayer && podHeld ? "This chapter’s own episode is recorded and held for review." : "", held, nextLine].filter(Boolean).join(" ")),
  ].join("");
}

// ── today: the weight ──────────────────────────────────────────────────────────
export function todayHTML(block, edition) {
  if (!usable(block)) return absent(block, "Today’s weight is not served right now.");
  const t = block.data;
  const sameDay = t.date && edition && t.date === edition.as_of;
  const when = sameDay ? "lb this morning." : `lb on ${dayInWords(t.date)}.`;
  const ch = num(t.change_lbs);
  const since = shortDay(t.start_date);
  const change = ch === null || !since ? "" : ch < 0 ? ` Down ${fmt1(-ch)} since ${since}.` : ch > 0 ? ` Up ${fmt1(ch)} since ${since}.` : ` The same as ${since}.`;
  return `<div class="ck-today"><div class="ck-num"><b>${esc(fmt1(t.weight_lbs))}</b><span class="ck-soft">${esc(when + change)}</span></div>${progressHTML(t)}</div>`;
}

// Start to goal as one track: how much of the distance is covered. Drawn only when the
// start, the goal and the current weight are all served and the goal lies below the start.
export function progressHTML(t) {
  const [start, goal, now] = [num(t && t.start_weight_lbs), num(t && t.goal_weight_lbs), num(t && t.weight_lbs)];
  if (start === null || goal === null || now === null || start <= goal) return "";
  const pct = Math.max(0, Math.min(100, Math.round((100 * (start - now)) / (start - goal))));
  return `<div class="ck-track" role="img" aria-label="${fmt1(start - now)} of ${fmt1(start - goal)} pounds lost"><i style="width:${pct}%"></i></div><div class="ck-ends"><span>${esc(`${trim1(start)} at the start`)}</span><span>${esc(`${trim1(Math.max(0, now - goal))} to go to ${trim1(goal)}`)}</span></div>`;
}

// ── today: what the coaches said ───────────────────────────────────────────────
export function coachLinesHTML(block) {
  const lines = usable(block) ? block.data.lines || [] : [];
  if (!lines.length) return absent(block, "The coaches have written nothing yet.");
  const rows = lines
    .map((l) => {
      const who = [l.coach, l.domain, l.replies_to ? `replying to ${l.replies_to}` : ""].filter(Boolean).join(" · ");
      const when = l.when_text ? ` <span class="ck-small">${esc(l.when_text)}</span>` : "";
      return `<li><span class="ck-coach__who">${esc(who)}</span><span>“${esc(l.text)}”${when}</span></li>`;
    })
    .join("");
  const stale = block.state === "stale" ? small(block.absent_text) : "";
  return `<ul class="ck-coach">${rows}</ul>${stale}`;
}

// ── the record, never alone ────────────────────────────────────────────────────
// One sentence pair: the count and what a simple guess would have done. With either half
// missing the block is `unavailable` upstream and this prints its sentence instead.
// Red team 2026-10-17: the count and its comparison are ONE plain sentence ("76 of 183 checked
// calls right; so far they do not beat a simple guess."). What the count counts (#4617's
// `counted_text`: sealed, bets, commentary, conditional) is the Coaches page's, under the big
// count (recordBigHTML) — not the front page's or Start's, where it read as accounting before the story.
const countedText = (d) => String((d && d.counted_text) || "").trim();
// Round 2: "they do not beat a simple guess" said nothing about the guess. The served comparison
// is a Brier skill score (lambdas/common/stats_core.brier_skill_score) against the base rate: a
// guess that gives every call the same chance, the share that came true. So the sentence
// names that guess and the gap, both from served fields: `brier_skill` (the gap, as a share of the
// guess's error) and right/decided (the guess's chance, only when the skill was scored on exactly
// the calls counted, `skill_n` === decided). With no skill served: "no comparison with a guess yet".
// Round 3: said plainly everywhere — "about as good as always guessing 42%, which is how often
// they're right". Within NEAR_SKILL of zero is "about as good as"; past it, "better"/"worse than".
// The precise skill figure is said once, on Coaches, under the breakdown (`skillClause`).
export const NEAR_SKILL = 0.05;
const baseRate = (d) => (num(d.skill_n) !== null && d.skill_n === d.decided && num(d.right) !== null && d.decided > 0 ? Math.round((100 * d.right) / d.decided) : null);
// Round 4: name the guess. The served comparison is a Brier skill score against the base rate
// (stats_core.brier_skill_score): the guess gives EVERY call the same chance of coming true — the
// share that did. So: "A guess that every call has a 42% chance of coming true does about as well."
export function guessClause(d) {
  const skill = num(d && d.brier_skill);
  if (skill === null) return "There is no comparison with a guess yet.";
  const how = Math.abs(skill) < NEAR_SKILL ? "does about as well" : skill > 0 ? "does worse" : "does better";
  const base = baseRate(d);
  return base === null ? `A guess that every call has the same chance of coming true ${how}.` : `A guess that every call has a ${base}% chance of coming true ${how}.`;
}
// Site-to-A round 1 (#4580 C1): the served figure is a Brier skill score, a share of the guess's
// error with no scale a reader knows, so "0.9% worse" read as a second unexplained statistic.
// The clause now says only the direction and whether the gap is slight (within NEAR_SKILL).
export function skillClause(d) {
  const skill = num(d && d.brier_skill);
  if (skill === null) return "";
  if (Math.abs(skill * 100).toFixed(1) === "0.0") return "Counting how sure each call was, they come out level with that guess.";
  const size = Math.abs(skill) < NEAR_SKILL ? "slightly" : "well";
  return `Counting how sure each call was, they come out ${size} ${skill > 0 ? "ahead of" : "behind"} that guess.`;
}
export function recordLine(block) {
  if (!usable(block) || !block.data.count_text || !String(block.data.comparison_text || "").trim()) return "";
  return `${String(block.data.count_text).trim()} ${guessClause(block.data)}`;
}
// Site-to-A round 1 (front:F4, item 3): on the front page and Start the comparison is ONE sayable
// sentence — the served `baseline` sentence when the edition carries it (lane E: a string, or
// {text}), else "The coaches do not beat a simple guess yet." from the served verdict — and the
// exact rate (guessClause) sits one tap deeper, under a <details>. Coaches keeps the precise clause.
export function guessSentence(d) {
  // Lane E (lambdas/web/record_words.py) serves the one sentence as `comparison_text`; the capture's older
  // "So far they do not beat a simple guess." is the same verdict in the unsayable form, so it is re-said.
  const served = String((d && d.comparison_text) || "").trim();
  if (served && !/^So far they/.test(served)) return served;
  if (num(d && d.brier_skill) === null) return "There is no comparison with a guess yet.";
  return d.beats_simple_guess === true ? "The coaches beat a simple guess." : "The coaches do not beat a simple guess yet.";
}
// The exact rate for the tap: lane E's `baseline.text` when served, else the clause computed here.
export const exactRateText = (d) => (d && d.baseline && typeof d.baseline.text === "string" && d.baseline.text.trim()) || guessClause(d);
// The record as the front page and Start print it: the count (a door to the coaches when `href`
// is given — on the count only, never the whole sentence underlined, front:F5), the one guess
// sentence, and the exact rate folded. A failed block is its own sentence, bare.
export function recordHTML(block, { href = "" } = {}) {
  if (!recordLine(block)) return esc((block && block.absent_text) || "");
  const d = block.data;
  const count = String(d.count_text).trim();
  const lead = href ? `<a class="ck-link" href="${esc(href)}">${esc(count)}</a>` : esc(count);
  const exact = exactRateText(d);
  const fold = exact && !/no comparison/.test(exact) ? `<details class="ck-small"><summary>The exact rate</summary><p>${esc(exact)}</p></details>` : "";
  return `${lead} ${esc(guessSentence(d))}${fold}`;
}
// The breakdown on Coaches, after one plain sentence that says why there is one: "Not all of
// them are formal predictions. Of the 183: 11 sealed before day one, …". The served sentence's
// own "Counted:" lead is dropped; its figures are printed as served.
export function countedHTML(d) {
  const counted = countedText(d).replace(/^Counted:\s*/, "");
  if (!counted || num(d.decided) === null) return "";
  // One tap deeper (#4580 C4): the h1 says every call is checked, and the next thing a reader
  // meets should be a call, not the accounting of what the count counts.
  return `<details class="ck-small"><summary>What the ${d.decided} are</summary><p class="ck-small">${esc(`Not all of them are formal predictions. Of the ${d.decided}: ${counted}`)}</p></details>`;
}
export function betLine(nextBlock) {
  const bet = nextBlock && nextBlock.data && nextBlock.data.bet;
  if (!usable(bet)) return "";
  const names = (bet.data.sides || []).map((s) => s.coach).filter(Boolean);
  const day = dayInWords(bet.data.settle_date);
  if (names.length < 2 || !day) return "";
  return `A bet between ${listWords(names)} settles ${day}.`;
}
// The big count on Coaches. The comparison beside it is the edition's one sentence, read
// through the shared comparison reader (#4585) so a missing sentence is the same honest
// absence line every other page prints — and then no count is drawn at all. The
// record-by-record comparison is one tap away on the scorecard.
export function recordBigHTML(block) {
  if (!usable(block) || num(block.data.right) === null || num(block.data.decided) === null) {
    return absent(block, "The coaches’ record is not served right now.");
  }
  const d = block.data;
  if (!String(d.comparison_text || "").trim()) return soft(comparisonText(null));
  // Round 2 (coaches, G9): the front, week and call pages call the baseline "a simple guess";
  // this page said "a guess that every call has a 42% chance" under the same words with no bridge.
  // Until lane E's `comparison_text` lands, the one sentence here is the same as the front's
  // (guessSentence), and the exact rate with the skill clause sits one tap deeper, as on the front.
  const cmp = exactRateText(d);
  // The track's fill is the neutral grey, not the accent (#4580 C3): green means earned, and a
  // green bar beside "they do not beat a simple guess" claimed a win the sentence denies.
  const track =
    d.decided >= MIN_PERCENT_N
      ? `<div class="ck-track" role="img" aria-label="${d.right} of ${d.decided} checked calls right"><i style="width:${Math.round((100 * d.right) / d.decided)}%;background:var(--ck-faint)"></i></div>`
      : "";
  const exact = /no comparison/.test(cmp) ? "" : `<details class="ck-small"><summary>The exact rate</summary><p>${esc(skillClause(d) ? `${cmp} ${skillClause(d)}` : cmp)}</p></details>`;
  return `<div class="ck-today ck-today--ruled"><p class="ck-soft">Right so far</p><p class="ck-big">${d.right}<span> of ${d.decided} checked calls</span></p>${track}<p>${esc(guessSentence(d))}</p>${exact}${countedHTML(d)}</div>`;
}

// ── the bet card ───────────────────────────────────────────────────────────────
export function betHTML(nextBlock, { sidesText = "", extra = "", href = "", hrefText = "What each one argued", oneLine = false } = {}) {
  const bet = nextBlock && nextBlock.data && nextBlock.data.bet;
  // #4582: with the whole `next` block unserved there is no bet part at all. Its sentence is
  // the block's ("What comes next is not served right now."), never "No coach bet is waiting
  // to settle." — that would state a fact the page could not read.
  if (!bet) return absent(nextBlock, "What comes next is not served right now.");
  if (!usable(bet) || !bet.data.question) return absent(bet, "No coach bet is waiting to settle.");
  const b = bet.data;
  // #4809: an array `sidesText` is one line per side (the front card's, each with the coach's
  // reason); a string is printed as one line (the caller's own wording). With neither, the
  // sides alone on one line — the reasons are the front card's only (ruling 2026-10-11).
  const sides = Array.isArray(sidesText) ? sidesText : [sidesText || F.betSidesLine(bet, {}, { reasons: false })].filter(Boolean);
  const door = href ? `<p><a class="ck-link" href="${esc(href)}">${esc(hrefText)}</a></p>` : "";
  // The question names its own day ("… on Monday, October 12?"), so the card's "Settles <day>"
  // line is printed only when it does not: room for the reasons (#4809), nothing said twice.
  const day = dayInWords(b.settle_date);
  const head = day && String(b.question).includes(day) ? "" : `<p class="ck-small">Settles ${esc(day)}</p>`;
  // `oneLine`: the sides, the extra sentence and the door as ONE soft paragraph — the coaches
  // page's card, which holds its four-screen budget with headroom (ruling 2026-10-11).
  if (oneLine) {
    // The door follows the sides it explains; the extra sentence closes the paragraph.
    const parts = [esc(sides.filter(Boolean).join(" ")), href ? `<a class="ck-link" href="${esc(href)}">${esc(hrefText)}</a>` : "", esc(extra)];
    const line = parts.some(Boolean) ? `<p class="ck-soft">${parts.filter(Boolean).join(" ")}</p>` : "";
    return `<div class="ck-bet">${head}<p><b>${esc(b.question)}</b></p>${line}</div>`;
  }
  return `<div class="ck-bet">${head}<p><b>${esc(b.question)}</b></p>${sides.map(soft).join("")}${soft(extra)}${door}</div>`;
}
// The bet's reasons are printed on the front card only (ruling 2026-10-11: the coaches page
// keeps its four-screen budget); the coaches page's card carries a door to them — and only
// when the front card prints them: it leads with this bet (two named sides) and at least one
// side has a served reason. Otherwise no door, never one to a card without the reasons.
export function reasonsDoor(nextBlock, base = "/") {
  const bet = nextBlock && nextBlock.data && nextBlock.data.bet;
  const sides = usable(bet) ? (bet.data.sides || []).filter((s) => s && s.coach) : [];
  const served = sides.some((s) => typeof s.reason === "string" && s.reason.trim());
  return sides.length >= 2 && served ? { href: `${base}#ck-bet`, hrefText: "Why each says so." } : {};
}
// "Three more bets settle on October 7, 12 and 16." from the served docket, minus the
// one on the card. "" when there are none.
export function moreBetsLine(docket, shownDate) {
  const open = ((docket && docket.open) || []).map((d) => d.resolution_date).filter(Boolean).sort();
  const idx = open.indexOf(shownDate);
  if (idx >= 0) open.splice(idx, 1);
  if (!open.length) return "";
  const days = open.map((iso, i) => {
    const sameMonth = i > 0 && iso.slice(0, 7) === open[i - 1].slice(0, 7);
    return sameMonth ? String(Number(iso.slice(8, 10))) : shortDay(iso);
  });
  return `${countWord(open.length)} more ${open.length === 1 ? "bet settles" : "bets settle"} on ${listWords(days)}.`;
}

// ── the chapters, in order ─────────────────────────────────────────────────────
const _weightOf = (statsLine) => {
  const m = /([\d.]+)\s*lbs/.exec(String(statsLine || ""));
  return m ? m[1] : "";
};
const isPrologue = (p) => /^Prologue/.test(String((p && p.label) || ""));
// Red team 2026-10-17: every row is `label · value`, and the value is always the same kind of
// thing. A week's value is its weight in lb; the first week's is labelled the start when it is
// the edition's start weight (the run's first weigh-in). A prologue was written before day one,
// so it says that — never a date where a weight belongs, and never a pre-start reading that would
// make week 1 read as a gain.
export function chapterValue(p, { startLb = null, first = false } = {}) {
  if (isPrologue(p)) return "Before day one";
  const w = _weightOf(p.stats_line);
  if (!w) return shortDay(p.date);
  const start = first && num(startLb) !== null && Math.abs(Number(w) - startLb) < 0.05;
  return `${w} ${LB}${start ? ", the start" : ""}`;
}
// `newestFirst`: Story's order (#4580), the newest chapter at the top with its day under the
// week label; the weight stays the value cell. Default is the served order (oldest first).
export function chapterRowsHTML(items, { currentUrl = "", startLb = null, newestFirst = false } = {}) {
  const inOrder = (items || []).filter((p) => p && p.title && p.url);
  if (!inOrder.length) return "";
  const firstWeek = inOrder.find((p) => !isPrologue(p));
  const rows = newestFirst ? [...inOrder].reverse() : inOrder;
  return `<ul class="ck-rows ck-rows--chapters">${rows
    .map((p) => {
      const key = String(p.label || "").replace(/^Prologue.*$/, "Start");
      const day = newestFirst && shortDay(p.date) ? `<br><span class="ck-small">${esc(shortDay(p.date))}</span>` : "";
      const value = chapterValue(p, { startLb, first: p === firstWeek });
      return `<li${p.url === currentUrl ? ' class="ck-rows__now"' : ""}><span class="ck-rows__key">${esc(key)}${day}</span><a href="${esc(p.url)}">${esc(p.title)}</a><span class="ck-rows__value">${esc(value)}</span></li>`;
    })
    .join("")}</ul>`;
}
export const postsInOrder = (journal) => ((journal && journal.posts) || []).filter((p) => p && p.title && p.url).sort((a, b) => String(a.date).localeCompare(String(b.date)));

// One line per chapter on Start here, the same kind of line for every chapter (red team
// 2026-10-17: two prologues opened with the same "Tomorrow morning…" sentence, and week 4 switched
// from a stat line to a narrative em-dash chain). A week is its code-rendered stats line, in lb,
// its change in words; a prologue is "Before day one." The chapters' own sentences are one tap
// away on Story.
// Site-to-A round 2 (start, G9/G10): the row prints the chapter's OWN numbers — the weight and the
// change its served stats line carries ("(-3.5 this week)" → "down 3.5 that week"), with the window
// the line names ("Day 25 to Day 31"). Round 1 recomputed the change from the weigh-ins inside the
// window, which skipped every week-boundary drop, so the captions (0.8, 2.3, 3.1, 2.5) failed the
// reader's own subtraction of the printed weights on three rows of four. One number per row, no
// second computation: the change is the chapter's, as written on its date.
// Site-to-A round 1 (start:S6): each prologue says what it is, not one shared line.
const PROLOGUE_LINES = [
  [/Part I\b(?! ?I)/, "Who he was before the record."],
  [/Part II\b/, "The plan, written before day one."],
];
export const prologueLine = (p) => (PROLOGUE_LINES.find(([rx]) => rx.test(String(p.label || ""))) || [null, "Before day one."])[1];
const SERVED_CHANGE = /\s*\(([-−+]?)(\d+(?:\.\d+)?) this week\)/;
export const servedChange = (statsLine) => {
  const m = SERVED_CHANGE.exec(String(statsLine || ""));
  if (!m) return "";
  const n = Number(m[2]);
  if (!Number.isFinite(n)) return "";
  if (n === 0) return "the same as the week before";
  return `${m[1] === "-" || m[1] === "−" ? "down" : "up"} ${n.toFixed(1)} that week`;
};
export function chapterStatLine(p) {
  if (isPrologue(p)) return prologueLine(p);
  const raw = lbText(String((p && p.stats_line) || "").split("|")[0].trim());
  if (!raw) return "";
  const change = servedChange(raw);
  const line = raw.replace(SERVED_CHANGE, change ? `, ${change}` : "");
  return /[.!?]$/.test(line) ? line : `${line}.`;
}
// Site-to-A round 1: the rows are the kit's chapter rows (start:S8), each title a door to its
// chapter (start:S4). Round 2: the change on a row is the chapter's own (chapterStatLine).
export function recapHTML(posts) {
  const rows = (posts || []).map((p) => ({ p, line: chapterStatLine(p) })).filter((r) => r.p.title && r.line);
  if (!rows.length) return "";
  return `<ul class="ck-rows ck-rows--chapters">${rows
    .map(({ p, line }) => {
      const key = String(p.label || "").replace(/^Prologue.*$/, "Start");
      const title = p.url ? `<a href="${esc(p.url)}">${esc(p.title)}</a>` : `<span>${esc(p.title)}</span>`;
      return `<li><span class="ck-rows__key">${esc(key)}</span><span>${title}<br><span class="ck-small">${esc(line)}</span></span></li>`;
    })
    .join("")}</ul>`;
}

// Every episode, newest first: the title, the guest and the day. An episode the list marks held
// (`pending`, reason held_for_review) is the first row, said as held. No row links a bare .mp3
// (#4580 ST1); the newest episode plays in the kit's player under the chapter above, and the
// row that is playing says so.
export function episodeRowsHTML(episodes, { playing = "" } = {}) {
  const eps = ((episodes && episodes.episodes) || []).filter((e) => e && e.url && e.title).sort((a, b) => String(b.date).localeCompare(String(a.date)));
  const p = episodes && episodes.pending;
  const heldWeek = p && p.reason === "held_for_review" && num(p.week) !== null && !eps.some((e) => e.week === p.week) ? p.week : null;
  if (!eps.length && heldWeek === null) return "";
  const held = heldWeek === null ? "" : `<li><span class="ck-rows__key">EP${heldWeek}</span><span>Held for review before it publishes.</span></li>`;
  return `<ul class="ck-rows ck-rows--more">${held}${eps
    .map((e) => {
      const mins = num(e.duration_sec) !== null ? ` · ${Math.round(e.duration_sec / 60)} min` : "";
      const who = e.guest_name ? ` · ${e.guest_name}` : "";
      const now = playing && e.url === playing ? ` <span class="ck-small">(playing above)</span>` : "";
      return `<li><span>${esc(e.title)}${esc(who)}${esc(mins)}${shortDay(e.date) ? ` · ${esc(shortDay(e.date))}` : ""}${now}</span></li>`;
    })
    .join("")}</ul>`;
}

// ── the weight chart ───────────────────────────────────────────────────────────
// One line in the frame the front page's mark uses — the top is the start weight, the floor the
// goal — so a 25 lb drop is 25 of the 142 lb to go, not a line falling to the bottom of its box
// (site-to-A round 1: the chart scaled between the series' own min and max and filled to the
// floor, so the same drop that is a sliver on the front page's mark filled most of this frame).
// No fill: the line is a level, and a fill would make the latest reading look like nothing.
// With no start or goal served, the frame is the series' own range, as a line alone. The ends of
// the line are labelled under it, and the frame's two rules in one text line under those (round 2:
// labels inside the drawing scaled with the viewBox and rendered at about 6 px on a phone).
// "The top rule is 327.3 lb, the start; the dashed rule is 185 lb, the goal." — one line, so the
// near-flat trace reads against the whole distance, not as a chart that failed to move.
export const chartFrameLine = (start, goal) => `The top rule is ${trim1(start)} lb, the start; the dashed rule is ${trim1(goal)} lb, the goal.`;
export function chartHTML(weights, { sentence: withSentence = true, start = null, goal = null } = {}) {
  const pts = (weights || []).filter((w) => w && w.date && num(w.lbs) !== null).sort((a, b) => String(a.date).localeCompare(String(b.date)));
  if (pts.length < 2) return "";
  const t = (iso) => Date.parse(`${iso}T12:00:00Z`);
  const [t0, t1] = [t(pts[0].date), t(pts[pts.length - 1].date)];
  const seriesLo = Math.min(...pts.map((p) => p.lbs));
  const seriesHi = Math.max(...pts.map((p) => p.lbs));
  const framed = num(start) !== null && num(goal) !== null && start > goal;
  const hi = framed ? Math.max(start, seriesHi) : seriesHi;
  const lo = framed ? Math.min(goal, seriesLo) : seriesLo;
  const x = (p) => 8 + (624 * (t(p.date) - t0)) / (t1 - t0 || 1);
  const y = (lbs) => 20 + (122 * (hi - lbs)) / (hi - lo || 1);
  const line = pts.map((p) => `${x(p).toFixed(1)},${y(p.lbs).toFixed(1)}`).join(" ");
  const first = pts[0];
  const last = pts[pts.length - 1];
  const frameWords = framed ? `, in the frame from the start weight of ${trim1(start)} to the goal of ${trim1(goal)}` : "";
  const aria = `Weight from ${fmt1(first.lbs)} pounds on ${shortDay(first.date)} to ${fmt1(last.lbs)} on ${shortDay(last.date)}, ${pts.length} weigh-ins${frameWords}`;
  const sentence = `His weight at every weigh-in: ${fmt1(first.lbs)} lb on ${shortDay(first.date)}, ${fmt1(last.lbs)} on ${shortDay(last.date)}.`;
  // The frame's two ends as rules in the drawing — the start along the top, the goal dashed along
  // the floor — and their names in the kit's text row under the dates, never as text in the SVG.
  const rules = framed
    ? `<line class="ck-chart__rule" x1="8" x2="632" y1="${y(start).toFixed(1)}" y2="${y(start).toFixed(1)}" stroke="currentColor" stroke-opacity="0.25" stroke-width="1"/>` +
      `<line class="ck-chart__rule" x1="8" x2="632" y1="${y(goal).toFixed(1)}" y2="${y(goal).toFixed(1)}" stroke="currentColor" stroke-opacity="0.25" stroke-width="1" stroke-dasharray="5 5"/>`
    : "";
  const frameEnds = framed ? `<div class="ck-ends"><span>${esc(chartFrameLine(start, goal))}</span></div>` : "";
  return `${withSentence ? `<p class="ck-soft">${esc(sentence)}</p>` : ""}<svg class="ck-chart" viewBox="0 0 640 ${framed ? 172 : 164}" role="img" aria-label="${esc(aria)}">${rules}<polyline class="ck-chart__line" points="${line}"/><circle class="ck-chart__now" cx="${x(last).toFixed(1)}" cy="${y(last.lbs).toFixed(1)}" r="5"/></svg><div class="ck-ends"><span>${esc(`${shortDay(first.date)} · ${fmt1(first.lbs)}`)}</span><span>${esc(`${shortDay(last.date)} · ${fmt1(last.lbs)}`)}</span></div>${frameEnds}`;
}

// ── the team ───────────────────────────────────────────────────────────────────
// `from` is the page this list is on, so the coach page returns to it by name (#4675).
// Red team 2026-10-17: "Sitting out: no sensor since August 27" beside a counted record read as
// calls with no instrument. The record is this run's only (the route counts from the run's start),
// so when the sitting-out date is before the run's first day (`startDate`, the edition's
// today.start_date — never a literal), the line says so and says what the counted calls rest on.
const ISO_RE = /(\d{4}-\d{2}-\d{2})/;
// `asOf`: the edition's day. A record whose served `through` day is earlier says so in its
// cell (#4580 C2: three records lagged the page's day with no word why).
export function teamHTML(coachesBody, base = "", from = "", { startDate = "", asOf = "" } = {}) {
  const coaches = ((coachesBody && coachesBody.coaches) || []).filter((c) => c && c.name);
  if (!coaches.length) return "";
  const n = (c) => (c.record && num(c.record.n)) || 0;
  const ordered = [...coaches].sort((a, b) => (b.tier === "lead") - (a.tier === "lead") || n(b) - n(a));
  const sittingOut = [];
  const rows = ordered
    .map((c) => {
      const job = COACH_JOBS[c.persona_id] || "";
      const r = c.record;
      const since = c.absent && c.reason ? (ISO_RE.exec(String(c.reason)) || [])[1] : "";
      const preStart = since && startDate && since < startDate && r && num(r.n) !== null && r.n > 0;
      // The sitting-out sentence goes under the list as one small line (#4580 C5): a four-line
      // job cell beside "1 of 7" broke the row and read as a contradiction.
      if (c.absent) {
        sittingOut.push(`${c.name} is sitting out${c.reason ? `: ${String(c.reason).replace(ISO_RE, (iso) => shortDay(iso))}` : ""}${preStart ? ", before day one, so the calls counted here were checked on other readings" : ""}.`);
      }
      // One rule for every row (round 2: a bar on some rows and not others read as a ranking):
      // the count alone, never a bar — a coach's n is often under MIN_PERCENT_N. A coach with
      // no checked call prints the served reason in its job cell (the lead's `headline_stat`,
      // "runs the program") and "none" in the record cell, which does not wrap.
      let record = "none";
      let why = "";
      if (r && num(r.n) !== null && r.n > 0) {
        record = `${r.confirmed} of ${r.n}`;
        const through = r.through && asOf && r.through < asOf ? shortDay(r.through) : "";
        if (through) record += `<br><span class="ck-small">through ${esc(through)}</span>`;
      } else {
        why = c.headline_stat && !/\d/.test(String(c.headline_stat)) ? `; ${String(c.headline_stat).trim()}, so no checked calls` : "; no checked calls";
      }
      const jobLine = `${job}${why}`.replace(/^; /, "").trim();
      const name = base && c.persona_id ? `<a class="ck-link" href="${esc(withFrom(`${base}coach/?c=${encodeURIComponent(c.persona_id)}`, from))}">${esc(c.name)}</a>` : esc(c.name);
      return `<li><span class="ck-coach__name">${name}</span><span class="ck-coach__job">${esc(jobLine)}</span><span class="ck-coach__record">${record}</span></li>`;
    })
    .join("");
  return `<ul class="ck-coach ck-coach--record">${rows}</ul>${sittingOut.map(small).join("")}`;
}
// "Next to settle: Nathan Reeves’s call on protein, Thursday, October 29." — the earliest pending
// call due on or after the page's day, from GET /api/predictions (#4580 C6: the page ended with
// no date to come back for). "" when nothing is pending or the route is not served.
const METRIC_WORDS = { total_protein_g: "protein", weight_lbs: "weight", sleep_hours: "sleep", recovery_pct: "recovery", deep_pct_7day_avg: "deep sleep", total_calories: "calories", hrv: "HRV" };
export function nextSettleLine(predictionsBody, asOf = "") {
  const pending = ((predictionsBody && predictionsBody.predictions) || []).filter((p) => p && p.status === "pending" && p.coach_name && /^\d{4}-\d{2}-\d{2}$/.test(String(p.due_date || "")) && (!asOf || p.due_date >= asOf));
  if (!pending.length) return "";
  const p = [...pending].sort((a, b) => String(a.due_date).localeCompare(String(b.due_date)))[0];
  const on = METRIC_WORDS[p.metric] || String(p.subdomain || "").replace(/_/g, " ");
  const day = dayInWords(p.due_date);
  if (!day) return "";
  return `Next to settle: ${p.coach_name}’s call${on ? ` on ${on}` : ""}, ${day}.`;
}

// ── one right, one wrong ───────────────────────────────────────────────────────
// The newest checked call of each kind, in the coach's own words. Only a call with a plain
// measured result ("point") shows its number; a direction call's stored result is a slope,
// which is not a reader's number, so it shows the date alone.
export function verdictPick(coachesBody, ruleOf = null) {
  // A conditional ("If dinner is disrupted…") is graded on its outcome with the condition
  // never checked, so it is no example of a right or a wrong call. A claim that quotes a
  // raw date is machine wording and is passed over too.
  const conditional = /^\s*(if|once|when|unless|should)\b/i;
  const calls = ((coachesBody && coachesBody.coaches) || [])
    .filter((c) => c && c.latest_checked && c.latest_checked.claim && !conditional.test(c.latest_checked.claim) && !/\b20\d\d-\d\d-\d\d\b/.test(c.latest_checked.claim))
    .map((c) => ({ coach: c.name, ...c.latest_checked }));
  // With `ruleOf`, a call it gives no rule is skipped and counted (#4808).
  const ruled = ruleOf ? calls.filter((c) => ruleOf(c)) : calls;
  const skipped = calls.filter((c) => c.status === "confirmed" || c.status === "refuted").length - ruled.filter((c) => c.status === "confirmed" || c.status === "refuted").length;
  const newest = (status) => {
    const of = ruled.filter((c) => c.status === status).sort((a, b) => String(b.outcome_date).localeCompare(String(a.outcome_date)));
    return of.find((c) => c.eval_type === "point" && num(c.actual_value) !== null) || of[0] || null;
  };
  return { right: newest("confirmed"), wrong: newest("refuted"), skipped };
}
// /api/coaches serves no allowed distance for a number call, so only a direction call has a
// rule this fallback can print. A call with no printable rule is never shown as right or wrong
// (#4808): the pick passes over it, and the page says how many it passed over.
const coachesRule = (call) => (call && call.eval_type === "directional" ? "by the trend in his most recent readings" : "");
export function verdictsHTML(coachesBody) {
  const { right, wrong, skipped } = verdictPick(coachesBody, coachesRule);
  if (!right && !wrong) return skipped ? soft(ruleless(skipped)) : "";
  const card = (call, tag) => {
    if (!call) return `<div>${soft(`No call with a printable rule has been checked and found ${tag.toLowerCase()} yet.`)}</div>`;
    // Only a direction call reaches here (its rule is the trend), so there is no number result.
    return `<div>${verdictTag(tag === "Right", coachesRule(call))}<p>${esc(call.coach)}: “${esc(call.claim)}”</p>${soft(`Checked ${shortDay(call.outcome_date)}.`)}</div>`;
  };
  return `<div class="ck-verdicts">${card(right, "Right")}${card(wrong, "Wrong")}</div>${soft(ruleless(skipped))}`;
}

// The same pair from the settled calls that have a page (GET /api/calls), each a door to
// its own page. The pair is chosen to be checkable at a glance (#4647): the right call
// whose allowed distance was tightest, and the wrong call that missed by the most. Each
// carries its rule in the tag and the day its reading was taken. "" when the route has
// nothing, so the caller can fall back.
// `trailer`: trusted HTML (the shell's own door) closing the paragraph under the pair, so the
// note and the door share one line instead of two paragraphs (the four-screen budget, 2026-10-11).
export function callVerdictsHTML(callsBody, base = "/", from = "", { trailer = "" } = {}) {
  const calls = ((callsBody && callsBody.calls) || []).filter((c) => c && c.id && c.called_short && c.kind !== "bet");
  const { right, wrong } = showcasePair(calls);
  if (!right && !wrong) return "";
  // What the allowed distance is: once under the pair when both were computed the same way.
  const shared = sharedToleranceNote([right, wrong]);
  const card = (call, word) => {
    if (!call) return `<div>${soft(`No call with a page has been found ${word} yet.`)}</div>`;
    const day = shortDay(call.settled_date);
    // Round 2: "Graded on the reading for September 11. Checked September 24." gave two dates and
    // no reason for the gap (the API carries none), so the day it was graded on stands alone.
    const when = gradedOnText(call) || (day ? `Checked ${day}.` : "");
    return callCardHTML(call, { when, note: !shared, href: withFrom(`${base}call/?id=${encodeURIComponent(call.id)}`, from) });
  };
  const after = [shared, ruleless(calls.filter((c) => !hasRule(c)).length)].filter(Boolean).join(" ");
  const close = after || trailer ? `<p class="ck-soft">${esc(after)}${after && trailer ? " " : ""}${trailer}</p>` : "";
  return `<div class="ck-verdicts">${card(right, "right")}${card(wrong, "wrong")}</div>${close}`;
}

// ── the catch-up list on the front page ────────────────────────────────────────
export function catchUpHTML(block, chapterBlock) {
  if (!usable(block) || !(block.data.items || []).length) return absent(block, "No chapters yet.");
  const current = usable(chapterBlock) ? chapterBlock.data.url : "";
  return chapterRowsHTML(block.data.items, { currentUrl: current });
}

// ── mount ──────────────────────────────────────────────────────────────────────
const UNSERVED = { state: "unavailable", absent_text: "This is not served right now.", data: null };
const fill = (id, html) => {
  const el = document.getElementById(id);
  if (el) el.innerHTML = html;
  return el;
};

// Every front-page slot the edition alone fills, as { element id: html } — `null` removes
// the element. Pure, so tests/js/edition_contract_4582.test.mjs drives the page's real
// block-to-slot wiring with the documents the route composes (#4582): one upstream failing
// must leave its slot printing the block's own sentence, never a blank or another figure.
export function frontSlots(edition, b, base = "/") {
  const e = edition || {};
  const t = usable(b.today) ? b.today.data : {};
  // His words lead when they are fresh. Silence is not a headline: the plain sentence that
  // there is nothing new sits at the foot of the page instead.
  // Site-to-A round 1 (front:F16): with no fresh words the row has no door — the page it went to
  // ended on the same absence sentence — and the sentence keeps its own date.
  const words = hisWordsFresh(b.his_words)
    ? { "ck-words": hisWordsHTML(b.his_words) }
    : {
        "ck-words": null,
        // The row keeps its key (a plain span, no door) and its sentence slot; the slot is filled after the row.
        "ck-words-row": '<span class="ck-rows__key">In his own words</span><span id="ck-words-absent"></span>',
        "ck-words-absent": esc(String((b.his_words && b.his_words.absent_text) || "").replace(/ in his own words\b/i, "")),
      };
  // Fresh words lead the page; then the "In his own words" row under Go deeper is not drawn.
  if (hisWordsFresh(b.his_words)) words["ck-words-row"] = null;
  const span = F.weekSpan(b.week);
  return {
    // The fixed top: the record beside the premise, the daily mark, his own dated note when
    // there is a fresh one.
    // Round 8b: every number on the first screen is a door — the record to the coaches, the
    // weight to its trend. A failed block prints its own sentence, with no door.
    "ck-record": recordHTML(b.record, { href: `${base}coaches/` }),
    // No weigh-in in the window draws no picture; the slot then says so (#4586 box 2).
    "ck-mark": F.markHTML(usable(b.week) ? b.week.data.weight_series : null, e.as_of, t.start_weight_lbs, t.goal_weight_lbs) || soft(usable(b.week) ? "No weigh-in in the last 28 days." : (b.week && b.week.absent_text) || "The weigh-ins are not served right now."),
    "ck-mark-caption": F.markCaption(b.today, e) ? `<a href="${esc(base)}trend/?m=weight">${F.markCaption(b.today, e)}</a>` : esc((b.today && b.today.absent_text) || ""),
    ...words,
    // The argument: the open bet is the edition's; the lines come in mountFront from the
    // last seven days of served moves.
    "ck-bet": betHTML(b.next),
    // Today: the last 24 hours.
    "ck-today-label": esc(`Today · ${dayInWords(e.as_of)}`),
    "ck-today": F.todayBandHTML(e, b, base),
    "ck-coach-lines": F.coachTodayHTML(b.coach_lines),
    // Go deeper: the week is one row (its own page, /week/), the chapter one row.
    "ck-week-span": esc(span ? `How the whole thing is going · ${span}` : "How the whole thing is going"),
    "ck-chapter-row": F.chapterRowHTML(latestChapterBlock(b)),
    "ck-follow-line": esc(F.followLine(b.next)),
  };
}
// The latest chapter for the front page's row: the chapter block, which is the latest published
// chapter, with lane E's `data.latest` {week, label, date, status} bound over its label and date
// when served. Defensive — an unserved field changes nothing.
export function latestChapterBlock(b) {
  if (!usable(b.chapter)) return b.chapter;
  const latest = b.chapter.data.latest;
  if (!latest || typeof latest !== "object") return b.chapter;
  const data = { ...b.chapter.data };
  if (typeof latest.label === "string" && latest.label.trim()) data.week_label = latest.label.trim();
  if (typeof latest.date === "string" && /^\d{4}-\d{2}-\d{2}$/.test(latest.date)) data.date = latest.date;
  return { ...b.chapter, data };
}
// The week page (round 8): the band that used to sit under Today on the front page, whole.
// "Next: the chapter draft Wednesday, October 21; the numbers every Sunday." — the day the next
// chapter is due: the chapter block's served `next_due` (lane E of #4580, the chronicle's own
// date), else the `next` block's chapter date, else the standing Wednesday after the page's day
// (#4580 W4: the page ended on an absence with no date to come back for).
export function weekNextLine(nextBlock, asOf = "", chapterBlock = null) {
  const ch = nextBlock && nextBlock.data && nextBlock.data.chapter;
  const served = usable(chapterBlock) && /^\d{4}-\d{2}-\d{2}$/.test(String(chapterBlock.data.next_due || "")) ? chapterBlock.data.next_due : "";
  let iso = served || (usable(ch) ? ch.data.next_due || ch.data.date || "" : "");
  if (!iso && /^\d{4}-\d{2}-\d{2}$/.test(String(asOf || ""))) {
    const t = Date.parse(`${asOf}T12:00:00Z`);
    const ahead = (3 - new Date(t).getUTCDay() + 7) % 7 || 7; // the next Wednesday, never today
    iso = new Date(t + ahead * 86400000).toISOString().slice(0, 10);
  }
  const day = dayInWords(iso);
  return day ? `Next: the chapter draft ${day}; the numbers every Sunday.` : "";
}
export function weekSlots(edition, b, base = "/") {
  const span = F.weekSpan(b.week);
  const words = hisWordsFresh(b.his_words) ? { "ck-words": hisWordsHTML(b.his_words), "ck-words-absent": null } : { "ck-words": null, "ck-words-absent": esc((b.his_words && b.his_words.absent_text) || "") };
  return {
    "ck-week-label": esc(span ? `This week · ${span}` : "This week"),
    // #4595: the served scorecard (one written rule per area, decided in code) when the edition
    // serves it; until the API that serves it is deployed, the older seven-day sort stands in.
    // The AI row carries the record block's one comparison sentence (lane E writes it once).
    "ck-week": F.scorecardRows(b.scorecard).length ? F.scorecardHTML(b.scorecard, base, { label: false, aiText: usable(b.record) ? b.record.data.comparison_text || "" : "" }) : F.weekSortHTML(b.week, base),
    "ck-quotes": F.quotesHTML(b.chapter, null, base),
    "ck-next-line": esc(weekNextLine(b.next, edition && edition.as_of, b.chapter)) || null,
    ...words,
  };
}

// The days the argument reads: the edition's day and the six before it — the window the
// edition's `moves` block is read over (site_api_edition.moves_days, #4582).
export function argumentDays(asOf, n = F.ARGUMENT_DAYS) {
  const out = [];
  let iso = asOf;
  for (let i = 0; i < n && iso; i += 1) {
    out.push(iso);
    const t = Date.parse(`${iso}T12:00:00Z`);
    iso = Number.isFinite(t) ? new Date(t - 86400000).toISOString().slice(0, 10) : "";
  }
  return out;
}

const fillSlots = (slots) => {
  for (const [id, html] of Object.entries(slots)) {
    if (html === null) document.getElementById(id)?.remove();
    else fill(id, html);
  }
};

// The edition's blocks for what the front page and the week page used to read from their own
// routes (#4582 box 1), each in that route's own shape so the builders read them unchanged.
// A block that failed gives the builder nothing — the caller prints the block's sentence.
export const movesOf = (b) => (usable(b.moves) && Array.isArray(b.moves.data.days) ? b.moves.data.days : []);
export const callsBodyOf = (b) => (usable(b.calls) && Array.isArray(b.calls.data.calls) ? { state: "ok", calls: b.calls.data.calls } : null);
export const characterOf = (b) => (usable(b.sheet) ? b.sheet.data : null);
export const leadReadOf = (b) => (usable(b.lead_read) ? b.lead_read.data : null);

// Every front-page slot that needs more than one block (the argument reads the open bet and the
// week of coach lines; the coach band leaves out what the argument printed), as { id: html } —
// `null` removes the element, an id left out keeps what frontSlots put there. Pure, so
// tests/js/edition_contract_4582.test.mjs renders it over the route's own documents: a block
// that failed prints its own sentence, never a claim the failed read cannot support.
export function frontReadSlots(edition, b, base = "/") {
  const e = edition || {};
  const out = {};
  const moves = movesOf(b);
  // The argument: the open bet (two coaches, opposite sides, a date) with the live number
  // against it; failing a bet, the newest exchange, from the served moves.
  const pick = F.pickArgument(moves, b.next);
  // The quiet section's label is "The AI" over the heading "The coaches." — not the same words twice.
  out["ck-argue-label"] = esc(pick ? F.argumentLabel(pick) : "The AI");
  // Round 4: with no bet and no exchange, the newest dated line that passes the plain-language
  // rule (any coach, newest first) keeps the coaches' voice on a quiet day; only with none does
  // the section say there is no open bet.
  const quiet = pick ? "" : F.lastHeardHTML(moves, [], base);
  // Site-to-A round 1 (front:F2, item 2): with no bet and no exchange the section is still "The
  // coaches" — the newest line the front may quote leads it when there is one, and the null bet
  // is one quiet sentence under it, never the heading the reader meets first.
  const noBet = !pick && b.next.state !== "unavailable" && !usable(b.next.data && b.next.data.bet) ? soft("No open bet between them this week.") : "";
  if (quiet) {
    out["ck-argue-heading"] = esc("The coaches.");
    out["ck-argument"] = `${quiet}${noBet}`;
  } else if (!pick && b.moves.state === "unavailable") {
    // A failed read is not "nothing in dispute": the section says the lines are not served.
    out["ck-argue-heading"] = esc("What they are arguing about.");
    out["ck-argument"] = soft(b.moves.absent_text);
  } else if (!pick) {
    out["ck-argue-heading"] = esc("The coaches.");
    out["ck-argument"] = noBet || soft("Nothing from the coaches this week is one the front page may quote.");
  } else {
    out["ck-argue-heading"] = esc(F.argumentHeading(pick));
    out["ck-argument"] = F.argumentHTML(pick, base);
  }
  if (pick && pick.kind === "bet") {
    // The card in the bet's own terms: each coach with its job, the live number inside the
    // card, and the door to what each one argued (round 8b).
    out["ck-bet"] = betHTML(b.next, { sidesText: F.betSidesLines(pick.bet, F.jobsByName(moves)), extra: F.betLiveLine(pick.bet, b.week), href: `${base}coaches/#ck-bet`, hrefText: "Every open bet, on the coaches page" });
    // The card's own door goes to the coaches page; a second door there under it says it twice.
    out["ck-coaches-door"] = null;
  } else if (pick && pick.kind === "reply") {
    out["ck-bet"] = null;
  } else if (!pick && b.next.state !== "unavailable" && !usable(b.next.data && b.next.data.bet)) {
    // The heading already says there is no open bet; the card's own "No coach bet is waiting to
    // settle." would say it twice (round 3).
    out["ck-bet"] = null;
  }
  // A line from the edition's day that the argument already printed is not printed twice.
  // With nothing said today, the newest line the coaches said stands under its own label,
  // and with nothing in the window at all the band has no coach part — unless the day's lines
  // failed to read, when frontSlots' sentence for them stands.
  const shown = F.argumentTexts(pick);
  const today = F.coachTodayHTML(b.coach_lines, { skip: shown });
  const spokeToday = usable(b.coach_lines) && (b.coach_lines.data.lines || []).length > 0;
  if (today && spokeToday) out["ck-coach-lines"] = today;
  else {
    // The last line heard stands in only when the argument section is empty: with an exchange or
    // an open bet above it, the coaches have already spoken on this page, and a further quote is the
    // same voice twice (a quarter screen; red team 2026-10-17 — the front page should get shorter).
    // No "last heard" row here: with no argument the section above carries the newest quotable line.
    if (b.coach_lines.state !== "unavailable") {
      out["ck-coach-lines-label"] = null;
      out["ck-coach-lines"] = null;
    }
  }
  // The clearest miss this week, or on record, or the calls block's own sentence.
  const calls = callsBodyOf(b);
  // "This week" is the week the page prints (the week block's first day), one window for both.
  const weekFrom = usable(b.week) ? (b.week.data.days || [])[0] || "" : "";
  const { kind } = lastCallPick(calls, e.as_of, { since: weekFrom });
  // The list of every settled call shares the card's door line (one line, not a paragraph of its own).
  const everyDoor = `<a class="ck-link" href="${esc(base)}call/">Every settled call</a>`;
  const last = lastCallHTML(calls, base, e.as_of, F.SHORT_JOBS, { moreDoor: everyDoor, since: weekFrom });
  if (last) {
    // front:F3: the week is the week the call was CHECKED in; the card carries the call's own dates.
    const heading = { recent: "The clearest miss checked this week.", wrong: "The clearest miss so far.", right: "The tightest right call so far." }[kind] || "The latest checked call.";
    out["ck-miss-heading"] = esc(heading);
    out["ck-call"] = last.includes(everyDoor) ? last : `${last}<p>${everyDoor}</p>`;
  } else {
    out["ck-call"] = soft(b.calls.absent_text || "The settled calls are not served right now.");
  }
  // What recovery is, said once: when the miss card's served sentence already glosses it, the
  // Today band does not repeat it.
  if (/morning score out of 100/.test(out["ck-call"] || "")) out["ck-today"] = F.todayBandHTML(e, b, base, { gloss: false });
  const sheet = sheetLine(characterOf(b));
  if (sheet) out["ck-sheet-span"] = esc(sheet);
  return out;
}

// The front page reads nothing but the edition (#4582 box 1): every slot is the edition's.
async function mountFront(edition, b) {
  const base = document.body.dataset.ckBase || "/";
  fillSlots(frontSlots(edition, b, base));
  fillSlots(frontReadSlots(edition, b, base));
}

// The week page: the edition, and the chapter's published transcript for its quotes.
async function mountWeek(edition, b) {
  const base = document.body.dataset.ckBase || "/";
  fillSlots(weekSlots(edition, b, base));
  // Round 8: a section with nothing to show does not render its heading; a read that failed
  // says so instead.
  const lead = F.leadReadHTML(leadReadOf(b), base);
  if (lead) fill("ck-lead-read", lead);
  else if (b.lead_read.state === "unavailable") fill("ck-lead-read", soft(b.lead_read.absent_text));
  else document.getElementById("ck-lead-section")?.remove();
  const sheet = sheetLine(characterOf(b));
  // The door is the words that name it, not the whole two-line sentence (#4580 W9).
  fill("ck-sheet-line", sheet ? `${esc(sheet)}: <a class="ck-link" href="${esc(base)}sheet/">the character sheet</a>` : esc(b.sheet.absent_text || ""));
  const pod = usable(b.chapter) && usable(b.chapter.data.podcast) ? b.chapter.data.podcast.data : null;
  const transcriptUrl = pod && /\.mp3$/.test(pod.mp3_url || "") ? pod.mp3_url.replace(/\.mp3$/, ".transcript.json") : "";
  const transcript = transcriptUrl ? await tryJSON(transcriptUrl) : null;
  if (transcript) fill("ck-quotes", F.quotesHTML(b.chapter, transcript, base));
}

async function mountStart(edition, b) {
  const [journal, timeline] = await Promise.all([tryJSON("/journal/posts.json"), tryJSON("/api/timeline")]);
  const allWeights = timeline && timeline.timeline && timeline.timeline.weights;
  const t = usable(b.today) ? b.today.data : {};
  fill("ck-recap", recapHTML(postsInOrder(journal)) || soft("The chapters are not served right now."));
  // The same series the front page's mark draws (the edition's weigh-ins) in the same frame (start
  // to goal); the timeline's weights stand in when the edition's week block is not served.
  const weights = usable(b.week) && Array.isArray(b.week.data.weight_series) ? b.week.data.weight_series : allWeights;
  fill("ck-chart", chartHTML(weights, { start: t.start_weight_lbs, goal: t.goal_weight_lbs }) || soft("The weigh-ins are not served right now."));
  // Site-to-A round 1 (start:S1/S3): the next chapter's date is the chapter list's tail; an open
  // bet sits with the coaches; nothing waiting to settle draws nothing.
  const open = chapterNextLine(b.next, b.chapter);
  if (open) fill("ck-open", esc(open));
  else document.getElementById("ck-open")?.remove();
  const bet = coachesBetHTML(b.next, null);
  if (bet === null) document.getElementById("ck-bet")?.remove();
  else fill("ck-bet", bet);
  fill("ck-record", recordHTML(b.record));
  fill("ck-follow-line", esc(F.followLine(b.next)));
}
const chapterNextLine = (nextBlock, chapterBlock = null) => {
  const ch = nextBlock && nextBlock.data && nextBlock.data.chapter;
  if (usable(ch) && dayInWords(ch.data.date)) return nextChapterLine(nextBlock).replace(/^Next chapter due/, "The next chapter is due");
  // Lane E: the chapter block's own `next_due` (from the cadence) when the next block has no date.
  const due = usable(chapterBlock) && typeof chapterBlock.data.next_due === "string" ? dayInWords(chapterBlock.data.next_due) : "";
  return due ? `The next draft is due ${due}.` : "";
};

const startLbOf = (b) => (usable(b.today) ? num(b.today.data.start_weight_lbs) : null);
// The one-line frame the front page opens with, said once under Story's chapter title (#4580 ST10:
// the page opened on a chapter title with no sentence saying what the site is).
export const STORY_FRAME = "I’m trying to get from 327 pounds to 185, in public. A team of AI coaches I built predicts how it will go, and code checks every call.";
// Story's lead: the latest chapter, its served held state, the podcast's hold (the newest published
// episode plays when this chapter's own is held) and the frame sentence; the teaser is the
// chapter's dek as served. Pure, for tests/js/ck_red_team_4586.test.mjs.
export function storyChapterHTML(edition, b, journal, episodes) {
  const c = usable(b.chapter) ? b.chapter.data : null;
  return chapterHTML(b.chapter, b.next, {
    held: heldChapterLine(b.chapter, edition, journal, b.next),
    podcastHeld: c ? podcastHeld(episodes, weekNumberOf(c.week_label)) : false,
    asOf: (edition && edition.as_of) || "",
    frame: STORY_FRAME,
    fallbackPlayer: newestEpisode(episodes),
  });
}
async function mountStory(edition, b) {
  const [journal, episodes] = await Promise.all([tryJSON("/journal/posts.json"), tryJSON("/panelcast/episodes.json")]);
  fill("ck-chapter", storyChapterHTML(edition, b, journal, episodes));
  const current = usable(b.chapter) ? b.chapter.data.url : "";
  fill("ck-chapters", chapterRowsHTML(postsInOrder(journal), { currentUrl: current, startLb: startLbOf(b), newestFirst: true }) || soft("The chapters are not served right now."));
  const own = usable(b.chapter) && usable(b.chapter.data.podcast) && b.chapter.data.podcast.data.mp3_url;
  const newest = own ? null : newestEpisode(episodes);
  fill("ck-episodes", episodeRowsHTML(episodes, { playing: own || (newest ? newest.episode.url : "") }) || soft("The podcast episodes are not served right now."));
}

async function mountCoaches(edition, b) {
  const base = document.body.dataset.ckBase || "/";
  const [coaches, docket, calls, predictions] = await Promise.all([tryJSON("/api/coaches"), tryJSON("/api/coach_docket"), tryJSON("/api/calls"), tryJSON("/api/predictions")]);
  fill("ck-record-big", recordBigHTML(b.record));
  fill("ck-team", teamHTML(coaches, base, "coaches", { startDate: usable(b.today) ? b.today.data.start_date || "" : "", asOf: (edition && edition.as_of) || "" }) || soft("The team is not served right now."));
  // The day to come back for: the earliest pending call's due day; with none, the line is not drawn.
  const settle = nextSettleLine(predictions, (edition && edition.as_of) || "");
  if (settle) fill("ck-next-settle", esc(settle));
  else document.getElementById("ck-next-settle")?.remove();
  // The shell's scorecard door joins the note under the pair; with no pair it stands as served.
  const more = document.getElementById("ck-verdicts-more");
  const pair = callVerdictsHTML(calls, base, "coaches", { trailer: more ? more.innerHTML.trim() : "" });
  if (pair && more) more.remove();
  fill("ck-verdicts", pair || verdictsHTML(coaches) || soft("No checked call is served right now."));
  const bet = coachesBetHTML(b.next, docket, base);
  if (bet === null) document.getElementById("ck-bet")?.closest("section")?.remove();
  else fill("ck-bet", bet);
}
// The bet section on Coaches. null — the section is not drawn — when the edition read the docket
// and there is nothing waiting to settle (red team 2026-10-17: the page ended on an empty "When
// two disagree, they bet. No coach bet is waiting to settle."). A failed read still says so.
export function coachesBetHTML(nextBlock, docket, base = "/") {
  const bet = nextBlock && nextBlock.data && nextBlock.data.bet;
  const open = usable(bet) && bet.data.question;
  if (bet && !open && bet.state !== "unavailable") {
    const more = moreBetsLine(docket, "");
    return more ? soft(more) : null;
  }
  return betHTML(nextBlock, { extra: moreBetsLine(docket, open ? bet.data.settle_date : ""), ...reasonsDoor(nextBlock, base), oneLine: true });
}

const PAGES = { front: mountFront, week: mountWeek, start: mountStart, story: mountStory, coaches: mountCoaches };

export async function mount() {
  const page = document.body && document.body.dataset.ckPage;
  if (!PAGES[page]) return;
  const edition = (await tryJSON("/api/edition")) || {};
  const blocks = new Proxy(edition.blocks || {}, { get: (o, k) => o[k] || UNSERVED });
  fill("ck-day", esc(headerDay(edition)));
  await PAGES[page](edition, blocks);
  document.body.dataset.ckReady = "1";
}

if (typeof document !== "undefined") mount();
