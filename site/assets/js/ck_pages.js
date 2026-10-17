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
  eli_marsh: "Lead. Turns the others into one plan for the day.",
  sleep_coach: "Sleep",
  explorer_coach: "The statistician. Asks whether a pattern is real.",
  nutrition_coach: "Food and protein",
  mind_coach: "Mind and habits",
  physical_coach: "Training",
  labs_coach: "Blood tests and long-term health",
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
    return `${label(`In my words · ${shortDay(d.date) || d.date_text || ""}`)}<p class="ck-quote">“${esc(d.text)}”</p>${asked}`;
  }
  return `${label("In my words")}${absent(block, "Nothing in his own words is served right now.")}`;
}

// ── the chapter lead, with the player ──────────────────────────────────────────
// `held`: the episode list's own hold marker (/panelcast/episodes.json `pending`, reason
// held_for_review) for this chapter's week — then the line says the episode is held, never that
// there is none yet (red team 2026-10-17: an episode held since October 9 read "no episode yet").
export function podcastHeld(episodes, weekNumber) {
  const p = episodes && episodes.pending;
  return !!p && p.reason === "held_for_review" && num(p.week) !== null && p.week === weekNumber;
}
export function playerHTML(podcast, { held = false } = {}) {
  if (!usable(podcast) || !podcast.data.mp3_url) {
    if (held) return small("This chapter’s podcast episode is recorded and held for review before it publishes.");
    return small((podcast && podcast.absent_text) || "No podcast episode for this chapter yet.");
  }
  const p = podcast.data;
  const mins = num(p.duration_minutes) !== null ? ` · ${p.duration_minutes} min` : "";
  const who = p.guest ? `The podcast this week: ${p.guest_domain ? `the ${p.guest_domain} coach, ` : ""}${p.guest}${mins}.` : `The podcast this week${mins}.`;
  return `<audio controls preload="none" src="${esc(p.mp3_url)}" aria-label="${esc(p.title || "This week’s podcast episode")}"></audio>${small(who)}`;
}

// The week number a chapter's label names ("Week 5" -> 5); null for a prologue.
export const weekNumberOf = (label) => {
  const m = /^Week (\d+)\b/.exec(String(label || ""));
  return m ? Number(m[1]) : null;
};
// THE HELD STATE (red team 2026-10-17: on day 42 Story showed week 5 as "the latest chapter" with
// "next chapter due Wednesday" and no word about week 6). A chapter publishes only after Matthew
// approves it, so a week can be written and waiting. What the page can read: the chronicle's own
// hold marker on /journal/posts.json (`pending`: {week, reason}, written by
// emails/chronicle_store.held_week), and the edition's day against the latest chapter's date.
//   - the marker names a later week: "Week N is held before publishing."
//   - no marker, but the latest chapter is more than a week older than the edition's day: the
//     next week has not published. One calm line; it never claims a draft exists, because no
//     served field says one does.
// "" when the latest chapter is current.
export const CHAPTER_DAYS = 7;
export function heldChapterLine(block, edition, journal) {
  if (!usable(block)) return "";
  const n = weekNumberOf(block.data.week_label);
  if (n === null) return "";
  const p = journal && journal.pending;
  if (p && num(p.week) !== null && p.week > n) return `Week ${p.week} is held before publishing.`;
  const [t0, t1] = [Date.parse(`${block.data.date}T12:00:00Z`), Date.parse(`${(edition && edition.as_of) || ""}T12:00:00Z`)];
  if (!Number.isFinite(t0) || !Number.isFinite(t1) || (t1 - t0) / 86400000 <= CHAPTER_DAYS) return "";
  return `Week ${n + 1} has not published yet: each chapter waits for Matthew to read and approve it.`;
}
// The chapter's teaser, with the two claims a reader can check against the page made to agree with
// it (red team 2026-10-17). "crossed 310 pounds" says which way only through the chapter's own
// weight: below it, "went below"; above it, "went above". "N pounds gone" is recomputed with
// poundsDown from the start weight and the chapter's weight — the two numbers the page prints.
// Without the chapter's weight the teaser is printed as served.
export function teaserText(dek, { chapterLb = null, startLb = null } = {}) {
  let t = String(dek || "");
  if (num(chapterLb) === null) return t;
  t = t.replace(/\bcrossed (\d+(?:\.\d+)?) (pounds|lb|lbs)\b/g, (m, n, unit) => (chapterLb < Number(n) ? `went below ${n} ${unit}` : chapterLb > Number(n) ? `went above ${n} ${unit}` : m));
  const down = poundsDown(startLb, chapterLb);
  return down ? t.replace(/\b\d+(?:\.\d+)? pounds gone\b/g, `${down} pounds gone`) : t;
}
// "Next chapter due <day>." — or, when the cadence says the date is a draft and not a promise,
// what actually happens on it.
export function nextChapterLine(nextBlock) {
  const ch = nextBlock && nextBlock.data && nextBlock.data.chapter;
  const day = usable(ch) ? dayInWords(ch.data.date) : "";
  if (!day) return (ch && ch.state !== "ok" && ch.absent_text) || "";
  return ch.data.drafted_not_promised ? `The next draft is due ${day}; it publishes once Matthew approves it.` : `Next chapter due ${day}.`;
}
export function chapterHTML(block, nextBlock, { heading = "h1", player = true, listenHref = "", held = "", podcastHeld: podHeld = false, teaser = null } = {}) {
  if (!usable(block)) return absent(block, "The latest chapter is not served right now.");
  const c = block.data;
  const fresh = block.state === "ok";
  const week = c.week_label || "";
  const badge = fresh ? `New this week${week ? ` · ${week}` : ""}` : `The latest chapter${week ? ` · ${week}` : ""}`;
  const read = c.url ? `<a class="ck-btn" href="${esc(c.url)}">Read${num(c.read_minutes) !== null ? ` · ${c.read_minutes} min` : ""}</a>` : "";
  const pod = c.podcast;
  const hasPod = usable(pod) && pod.data.mp3_url;
  const listen =
    !player && hasPod && listenHref
      ? `<a class="ck-btn ck-btn--ghost" href="${esc(listenHref)}">Listen${num(pod.data.duration_minutes) !== null ? ` · ${pod.data.duration_minutes} min` : ""}</a>`
      : "";
  // With the held line printed, the next date is said plainly: the approval is already said once.
  const nextLine = held ? nextChapterLine(nextBlock).replace(/; it publishes once Matthew approves it\.$/, ".") : nextChapterLine(nextBlock);
  // The front page runs one sentence of the chapter's own summary; Story runs it whole.
  const dek = player ? teaserText(c.dek, teaser || {}) : summarySentence(c.dek) || c.dek;
  return [
    `<span class="ck-badge">${esc(badge)}</span>`,
    `<${heading}>${esc(c.title)}</${heading}>`,
    small(`Written by AI from the record on ${shortDay(c.date)}. Matthew reads each chapter before it publishes.`),
    dek ? `<p class="ck-premise ck-soft">${esc(dek)}</p>` : "",
    read || listen ? `<div class="ck-actions">${read}${listen}</div>` : "",
    player ? playerHTML(pod, { held: podHeld }) : "",
    !player && hasPod && pod.data.guest ? small(`On the podcast: ${pod.data.guest_domain ? `the ${pod.data.guest_domain} coach, ` : ""}${pod.data.guest}.${nextLine ? ` ${nextLine}` : ""}`) : small([held, nextLine].filter(Boolean).join(" ")),
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
export function recordLine(block) {
  if (!usable(block) || !block.data.count_text || !String(block.data.comparison_text || "").trim()) return "";
  const count = String(block.data.count_text).trim().replace(/[.\s]+$/, "");
  const cmp = comparisonText({ sentence: block.data.comparison_text });
  return `${count}; ${cmp.charAt(0).toLowerCase()}${cmp.slice(1)}`;
}
// The breakdown on Coaches, after one plain sentence that says why there is one: "Not all of
// them are formal predictions. Of the 183: 11 sealed before day one, …". The served sentence's
// own "Counted:" lead is dropped; its figures are printed as served.
export function countedHTML(d) {
  const counted = countedText(d).replace(/^Counted:\s*/, "");
  if (!counted || num(d.decided) === null) return "";
  return `<p class="ck-small">${esc(`Not all of them are formal predictions. Of the ${d.decided}: ${counted}`)}</p>`;
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
  const track =
    d.decided >= MIN_PERCENT_N
      ? `<div class="ck-track" role="img" aria-label="${d.right} of ${d.decided} checked calls right"><i style="width:${Math.round((100 * d.right) / d.decided)}%"></i></div>`
      : "";
  return `<div class="ck-today ck-today--ruled"><p class="ck-soft">Right so far</p><p class="ck-big">${d.right}<span> of ${d.decided} checked calls</span></p>${track}<p>${esc(comparisonText({ sentence: d.comparison_text }))}</p>${countedHTML(d)}</div>`;
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
export function chapterRowsHTML(items, { currentUrl = "", startLb = null } = {}) {
  const rows = (items || []).filter((p) => p && p.title && p.url);
  if (!rows.length) return "";
  const firstWeek = rows.find((p) => !isPrologue(p));
  return `<ul class="ck-rows ck-rows--chapters">${rows
    .map((p) => {
      const key = String(p.label || "").replace(/^Prologue.*$/, "Start");
      const value = chapterValue(p, { startLb, first: p === firstWeek });
      return `<li${p.url === currentUrl ? ' class="ck-rows__now"' : ""}><span class="ck-rows__key">${esc(key)}</span><a href="${esc(p.url)}">${esc(p.title)}</a><span class="ck-rows__value">${esc(value)}</span></li>`;
    })
    .join("")}</ul>`;
}
export const postsInOrder = (journal) => ((journal && journal.posts) || []).filter((p) => p && p.title && p.url).sort((a, b) => String(a.date).localeCompare(String(b.date)));

// One line per chapter on Start here, the same kind of line for every chapter (red team
// 2026-10-17: two prologues opened with the same "Tomorrow morning…" sentence, and week 4 switched
// from a stat line to a narrative em-dash chain). A week is its code-rendered stats line, in lb,
// its change in words; a prologue is "Before day one." The chapters' own sentences are one tap
// away on Story.
export function chapterStatLine(p) {
  if (isPrologue(p)) return "Before day one.";
  const raw = lbText(String((p && p.stats_line) || "").split("|")[0].trim());
  if (!raw) return "";
  const line = raw.replace(/\s*\(([-−+])?(\d+(?:\.\d+)?) this week\)/, (m, sign, n) => `, ${sign === "+" ? "up" : "down"} ${n} this week`);
  return /[.!?]$/.test(line) ? line : `${line}.`;
}
export function recapHTML(posts) {
  const rows = (posts || []).map((p) => ({ p, line: chapterStatLine(p) })).filter((r) => r.p.title && r.line);
  if (!rows.length) return "";
  return `<ul class="ck-coach">${rows
    .map(({ p, line }) => `<li><span class="ck-coach__who">${esc([String(p.label || "").replace(/^Prologue.*$/, "Start"), p.title].filter(Boolean).join(" · "))}</span><span>${esc(line)}</span></li>`)
    .join("")}</ul>`;
}

// Every episode, newest first, as onward links.
export function episodeRowsHTML(episodes) {
  const eps = ((episodes && episodes.episodes) || []).filter((e) => e && e.url && e.title).sort((a, b) => String(b.date).localeCompare(String(a.date)));
  if (!eps.length) return "";
  return `<ul class="ck-rows ck-rows--more">${eps
    .map((e) => {
      const mins = num(e.duration_sec) !== null ? ` · ${Math.round(e.duration_sec / 60)} min` : "";
      return `<li><a href="${esc(e.url)}">${esc(e.title)}${esc(mins)} <span>Listen →</span></a></li>`;
    })
    .join("")}</ul>`;
}

// ── the weight chart ───────────────────────────────────────────────────────────
// One line, the last point labelled, and the sentence above it says what it shows.
export function chartHTML(weights, { sentence: withSentence = true } = {}) {
  const pts = (weights || []).filter((w) => w && w.date && num(w.lbs) !== null).sort((a, b) => String(a.date).localeCompare(String(b.date)));
  if (pts.length < 2) return "";
  const t = (iso) => Date.parse(`${iso}T12:00:00Z`);
  const [t0, t1] = [t(pts[0].date), t(pts[pts.length - 1].date)];
  const lo = Math.min(...pts.map((p) => p.lbs));
  const hi = Math.max(...pts.map((p) => p.lbs));
  const x = (p) => 8 + (624 * (t(p.date) - t0)) / (t1 - t0 || 1);
  const y = (p) => 20 + (122 * (hi - p.lbs)) / (hi - lo || 1);
  const line = pts.map((p) => `${x(p).toFixed(1)},${y(p).toFixed(1)}`).join(" ");
  const first = pts[0];
  const last = pts[pts.length - 1];
  const aria = `Weight from ${fmt1(first.lbs)} pounds on ${shortDay(first.date)} to ${fmt1(last.lbs)} on ${shortDay(last.date)}, ${pts.length} weigh-ins`;
  const sentence = `My weight at every weigh-in: ${fmt1(first.lbs)} lb on ${shortDay(first.date)}, ${fmt1(last.lbs)} on ${shortDay(last.date)}.`;
  return `${withSentence ? `<p class="ck-soft">${esc(sentence)}</p>` : ""}<svg class="ck-chart" viewBox="0 0 640 196" role="img" aria-label="${esc(aria)}"><polygon class="ck-chart__area" points="8.0,164 ${line} 632.0,164"/><polyline class="ck-chart__line" points="${line}"/><circle class="ck-chart__now" cx="${x(last).toFixed(1)}" cy="${y(last).toFixed(1)}" r="5"/></svg><div class="ck-ends"><span>${esc(`${shortDay(first.date)} · ${fmt1(first.lbs)}`)}</span><span>${esc(`${shortDay(last.date)} · ${fmt1(last.lbs)}`)}</span></div>`;
}

// ── the team ───────────────────────────────────────────────────────────────────
// `from` is the page this list is on, so the coach page returns to it by name (#4675).
// Red team 2026-10-17: "Sitting out: no sensor since August 27" beside a counted record read as
// calls with no instrument. The record is this run's only (the route counts from the run's start),
// so when the sitting-out date is before the run's first day (`startDate`, the edition's
// today.start_date — never a literal), the line says so and says what the counted calls rest on.
const ISO_RE = /(\d{4}-\d{2}-\d{2})/;
export function teamHTML(coachesBody, base = "", from = "", { startDate = "" } = {}) {
  const coaches = ((coachesBody && coachesBody.coaches) || []).filter((c) => c && c.name);
  if (!coaches.length) return "";
  const n = (c) => (c.record && num(c.record.n)) || 0;
  const ordered = [...coaches].sort((a, b) => (b.tier === "lead") - (a.tier === "lead") || n(b) - n(a));
  return `<ul class="ck-coach ck-coach--record">${ordered
    .map((c) => {
      const job = COACH_JOBS[c.persona_id] || "";
      const r = c.record;
      const since = c.absent && c.reason ? (ISO_RE.exec(String(c.reason)) || [])[1] : "";
      const preStart = since && startDate && since < startDate && r && num(r.n) !== null && r.n > 0;
      const sitting = c.absent
        ? ` Sitting out${c.reason ? `: ${String(c.reason).replace(ISO_RE, (iso) => shortDay(iso))}` : ""}${preStart ? ", before day one, so the calls counted here were checked on other readings" : ""}.`
        : "";
      let record = "no checked calls";
      if (c.tier === "lead" && !r) record = "no bets";
      else if (r && num(r.n) !== null && r.n > 0) {
        const meter = r.n >= MIN_PERCENT_N ? `<span class="ck-meter"><i style="width:${Math.round((100 * r.confirmed) / r.n)}%"></i></span>` : "";
        record = `${r.confirmed} of ${r.n}${meter}`;
      }
      const jobLine = `${job}${job && sitting && !/[.!?]$/.test(job) ? "." : ""}${sitting}`.trim();
      const name = base && c.persona_id ? `<a class="ck-link" href="${esc(withFrom(`${base}coach/?c=${encodeURIComponent(c.persona_id)}`, from))}">${esc(c.name)}</a>` : esc(c.name);
      return `<li><span class="ck-coach__name">${name}</span><span class="ck-coach__job">${esc(jobLine)}</span><span class="ck-coach__record">${record}</span></li>`;
    })
    .join("")}</ul>`;
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
    const when = `${gradedOnText(call)} ${day ? `Checked ${day}.` : ""}`.trim();
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
  const words = hisWordsFresh(b.his_words)
    ? { "ck-words": hisWordsHTML(b.his_words) }
    : { "ck-words": null, "ck-words-absent": esc((b.his_words && b.his_words.absent_text) || "") };
  const span = F.weekSpan(b.week);
  return {
    // The fixed top: the record beside the premise, the daily mark, his own dated note when
    // there is a fresh one.
    // Round 8b: every number on the first screen is a door — the record to the coaches, the
    // weight to its trend. A failed block prints its own sentence, with no door.
    "ck-record": recordLine(b.record) ? `<a href="${esc(base)}coaches/">${esc(recordLine(b.record))}</a>` : esc((b.record && b.record.absent_text) || ""),
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
    "ck-chapter-row": F.chapterRowHTML(b.chapter),
    "ck-follow-line": esc(F.followLine(b.next)),
  };
}
// The week page (round 8): the band that used to sit under Today on the front page, whole.
export function weekSlots(edition, b, base = "/") {
  const span = F.weekSpan(b.week);
  const words = hisWordsFresh(b.his_words) ? { "ck-words": hisWordsHTML(b.his_words), "ck-words-absent": null } : { "ck-words": null, "ck-words-absent": esc((b.his_words && b.his_words.absent_text) || "") };
  return {
    "ck-week-label": esc(span ? `This week · ${span}` : "This week"),
    // #4595: the served scorecard (one written rule per area, decided in code) when the edition
    // serves it; until the API that serves it is deployed, the older seven-day sort stands in.
    "ck-week": F.scorecardRows(b.scorecard).length ? F.scorecardHTML(b.scorecard, base, { label: false }) : F.weekSortHTML(b.week, base),
    "ck-quotes": F.quotesHTML(b.chapter, null, base),
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
  out["ck-argue-label"] = esc(F.argumentLabel(pick));
  if (!pick && b.moves.state === "unavailable") {
    // A failed read is not "nothing in dispute": the section says the lines are not served.
    out["ck-argue-heading"] = esc("What they are arguing about.");
    out["ck-argument"] = soft(b.moves.absent_text);
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
    const heard = pick ? "" : F.lastHeardHTML(moves, shown, base);
    if (heard) {
      out["ck-coach-lines-label"] = "The coaches, last heard";
      out["ck-coach-lines"] = heard;
    } else if (b.coach_lines.state !== "unavailable") {
      out["ck-coach-lines-label"] = null;
      out["ck-coach-lines"] = null;
    }
  }
  // The clearest miss this week, or on record, or the calls block's own sentence.
  const calls = callsBodyOf(b);
  const { kind } = lastCallPick(calls, e.as_of);
  const last = lastCallHTML(calls, base, e.as_of, F.SHORT_JOBS);
  if (last) {
    const heading = { recent: "The clearest miss this week.", wrong: "The clearest miss so far.", right: "The tightest right call so far." }[kind] || "The latest checked call.";
    out["ck-miss-heading"] = esc(heading);
    out["ck-call"] = `${last}<p><a class="ck-link" href="${esc(base)}call/">Every settled call</a></p>`;
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
  fill("ck-sheet-line", sheet ? `<a class="ck-link" href="${esc(base)}sheet/">${esc(`${sheet}: the character sheet`)}</a>` : esc(b.sheet.absent_text || ""));
  const pod = usable(b.chapter) && usable(b.chapter.data.podcast) ? b.chapter.data.podcast.data : null;
  const transcriptUrl = pod && /\.mp3$/.test(pod.mp3_url || "") ? pod.mp3_url.replace(/\.mp3$/, ".transcript.json") : "";
  const transcript = transcriptUrl ? await tryJSON(transcriptUrl) : null;
  if (transcript) fill("ck-quotes", F.quotesHTML(b.chapter, transcript, base));
}

async function mountStart(edition, b) {
  const [journal, timeline] = await Promise.all([tryJSON("/journal/posts.json"), tryJSON("/api/timeline")]);
  fill("ck-recap", recapHTML(postsInOrder(journal)) || soft("The chapters are not served right now."));
  fill("ck-chart", chartHTML(timeline && timeline.timeline && timeline.timeline.weights) || soft("The weigh-ins are not served right now."));
  // Nothing waiting to settle is not a section's content: with no bet, the next chapter's line alone.
  const bet = coachesBetHTML(b.next, null);
  fill("ck-open", `${bet === null ? "" : bet}${small(chapterNextLine(b.next))}`);
  fill("ck-record", esc(recordLine(b.record) || (b.record && b.record.absent_text) || ""));
}
const chapterNextLine = (nextBlock) => {
  const ch = nextBlock && nextBlock.data && nextBlock.data.chapter;
  return usable(ch) && dayInWords(ch.data.date) ? nextChapterLine(nextBlock).replace(/^Next chapter due/, "The next chapter is due") : "";
};

const startLbOf = (b) => (usable(b.today) ? num(b.today.data.start_weight_lbs) : null);
// Story's lead: the latest chapter, its held state, the podcast's hold and the teaser made to
// agree with the rows below it. Pure, for tests/js/ck_red_team_4586.test.mjs.
export function storyChapterHTML(edition, b, journal, episodes) {
  const c = usable(b.chapter) ? b.chapter.data : null;
  const post = c ? postsInOrder(journal).find((p) => p.url === c.url) : null;
  const chapterLb = post && _weightOf(post.stats_line) ? Number(_weightOf(post.stats_line)) : null;
  return chapterHTML(b.chapter, b.next, {
    held: heldChapterLine(b.chapter, edition, journal),
    podcastHeld: c ? podcastHeld(episodes, weekNumberOf(c.week_label)) : false,
    teaser: { chapterLb, startLb: startLbOf(b) },
  });
}
async function mountStory(edition, b) {
  const [journal, episodes] = await Promise.all([tryJSON("/journal/posts.json"), tryJSON("/panelcast/episodes.json")]);
  fill("ck-chapter", storyChapterHTML(edition, b, journal, episodes));
  const current = usable(b.chapter) ? b.chapter.data.url : "";
  fill("ck-chapters", chapterRowsHTML(postsInOrder(journal), { currentUrl: current, startLb: startLbOf(b) }) || soft("The chapters are not served right now."));
  fill("ck-episodes", episodeRowsHTML(episodes) || soft("The podcast episodes are not served right now."));
}

async function mountCoaches(edition, b) {
  const base = document.body.dataset.ckBase || "/";
  const [coaches, docket, calls] = await Promise.all([tryJSON("/api/coaches"), tryJSON("/api/coach_docket"), tryJSON("/api/calls")]);
  fill("ck-record-big", recordBigHTML(b.record));
  fill("ck-team", teamHTML(coaches, base, "coaches", { startDate: usable(b.today) ? b.today.data.start_date || "" : "" }) || soft("The team is not served right now."));
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
