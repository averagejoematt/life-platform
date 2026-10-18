// ck_front.js — the reshaped preview front page (#4586, epic #4580).
//
// Round 8 (2026-10-11): the page leads with the coaches' open argument and the clearest
// miss on record, then the last 24 hours, and everything below that is a link. The top
// never changes shape: who he is, the record, the daily mark and his own dated note.
//
//   THE ARGUMENT  what two coaches disagree about, from the last seven days of their
//                 served lines (GET /api/coach_moves?date=<day>): a reply and the line it
//                 answers, printed exactly as served; failing a pair, the open bet's sides.
//   THE MISS      the clearest wrong call on record, with the rule that graded it.
//   TODAY         the last 24 hours — this morning's weigh-in and sleep, yesterday, the plan,
//                 and any coach line from today not already in the argument.
//   GO DEEPER     one row each: this week (its own page now, /next/v8/week/), the seven
//                 days, the character sheet, the chapter, the coaches.
//
// The week band (what is going well and what is not, the lead coach's read, the chapter
// and podcast lines) moved whole to /next/v8/week/; its builders stay here.
//
// Every builder is pure and exported for tests/js/ck_front_4586.test.mjs. Each prints a
// plain sentence when its data is absent: never a blank, a zero or another day's number.
// Standing rules held here: no first-person sentence is generated (his words are his own
// and dated), no count of earlier starts, no "Dr.", no percentage on fewer than 20 items.
import { esc } from "/assets/js/evidence_shared.js";
import { dayInWords } from "/assets/js/entry_age.js";
import { TERMS } from "/assets/js/ck_terms.js";

const num = (v) => (typeof v === "number" && Number.isFinite(v) ? v : null);
const fmt1 = (v) => (num(v) === null ? "" : v.toFixed(1));
const usable = (b) => !!b && (b.state === "ok" || b.state === "stale") && b.data != null;
const soft = (text) => (text ? `<p class="ck-soft">${esc(text)}</p>` : "");
const small = (text) => (text ? `<p class="ck-small">${esc(text)}</p>` : "");
const shortDay = (iso) => dayInWords(iso, { weekday: false });
const weekdayOf = (iso) => dayInWords(iso).split(",")[0] || "";
const dayBefore = (iso) => {
  const t = Date.parse(`${iso}T12:00:00Z`);
  return Number.isFinite(t) ? new Date(t - 86400000).toISOString().slice(0, 10) : "";
};

// ── the daily mark ─────────────────────────────────────────────────────────────
// One column a day for the last four weeks, in a frame that never changes. The frame's
// height is the whole distance from the start weight to the goal: the green cap hanging
// from the top is what is gone as of that day, the grey beneath it is what is left. A day
// with no weigh-in leaves a gap. One encoding, no axis; the caption carries the number.
// The same drawing is meant to be the link-preview image.
export const MARK_DAYS = 28;
export function markDays(series, todayIso, start, goal, days = MARK_DAYS) {
  const byDay = new Map((series || []).filter((w) => w && w.date && num(w.lbs) !== null).map((w) => [w.date, w.lbs]));
  const span = num(start) !== null && num(goal) !== null && start > goal ? start - goal : null;
  const out = [];
  let iso = todayIso;
  for (let i = 0; i < days && iso; i += 1) {
    const lbs = byDay.has(iso) ? byDay.get(iso) : null;
    const gone = lbs === null || span === null ? null : Math.max(0, Math.min(1, (start - lbs) / span));
    out.unshift({ date: iso, lbs, gone });
    iso = dayBefore(iso);
  }
  return out;
}
export function markSentence(cells, start, goal) {
  const weighed = cells.filter((c) => c.gone !== null);
  if (!weighed.length) return "";
  const last = weighed[weighed.length - 1];
  const missed = cells.length - weighed.length;
  return `The last ${cells.length} days: ${fmt1(start - last.lbs)} of the ${fmt1(start - goal)} pounds to the goal are gone as of the latest weigh-in${missed ? `; ${missed} ${missed === 1 ? "day has" : "days have"} no weigh-in` : ""}.`;
}
export function markHTML(series, todayIso, start, goal, { width = 640, height = 120 } = {}) {
  if (!todayIso) return "";
  const cells = markDays(series, todayIso, start, goal);
  if (!cells.some((c) => c.gone !== null)) return "";
  const gap = 4;
  const w = (width - gap * (cells.length - 1)) / cells.length;
  const rects = cells
    .map((c, i) => {
      if (c.gone === null) return "";
      const x = (i * (w + gap)).toFixed(1);
      const cap = Math.max(c.gone > 0 ? 2 : 0, c.gone * height);
      return `<rect class="ck-mark__left" x="${x}" y="0" width="${w.toFixed(1)}" height="${height}" rx="2"/><rect class="ck-mark__gone" x="${x}" y="0" width="${w.toFixed(1)}" height="${cap.toFixed(1)}" rx="2"/>`;
    })
    .join("");
  return `<svg class="ck-mark" viewBox="0 0 ${width} ${height}" role="img" aria-label="${esc(markSentence(cells, start, goal))}">${rects}</svg>${markEndsHTML(start, goal)}`;
}
// The mark's two ends, named under it (site-to-A round 1, front:F15): the start weight at the
// left, the goal at the right — the floor the grey stands for. "" without both numbers.
export function markEndsHTML(start, goal) {
  if (num(start) === null || num(goal) === null || start <= goal) return "";
  return `<div class="ck-ends"><span>${esc(`${fmt1(start)} lb at the start`)}</span><span>${esc(`${String(Number(goal.toFixed(1)))} lb, the goal`)}</span></div>`;
}
// "312.1 lb · Day 29 · 15.2 down, 127.1 to go to 185" — the mark's one line of numbers,
// the weight in bold. Returns HTML.
export function markCaption(today, edition) {
  if (!usable(today)) return "";
  const t = today.data;
  const [now, start, goal] = [num(t.weight_lbs), num(t.start_weight_lbs), num(t.goal_weight_lbs)];
  if (now === null) return "";
  const head = `<b>${esc(fmt1(now))} lb</b>`;
  const parts = [];
  if (t.date && edition && t.date !== edition.as_of) parts.push(esc(`on ${shortDay(t.date)}`));
  if (edition && num(edition.day_n) !== null && edition.day_n >= 1) parts.push(`Day ${edition.day_n}`);
  if (start !== null && goal !== null && start > goal) {
    const lost = start - now;
    parts.push(esc(`${fmt1(Math.abs(lost))} ${lost >= 0 ? "down" : "up"}, ${fmt1(Math.max(0, now - goal))} to go to ${String(Number(goal.toFixed(1)))}`));
  }
  // Round 8: the weight is the page's one large number (the kit's `ck-num`), the rest soft beside it.
  return parts.length ? `${head}<span class="ck-soft">${parts.join(" · ")}</span>` : head;
}

// ── the Today band ─────────────────────────────────────────────────────────────
// "312.1 lb, up 1.1 from Saturday." — this morning against the weigh-in before it.
export function morningLine(week, todayIso) {
  if (!usable(week)) return "";
  const detail = week.data.detail || [];
  const days = week.data.days || [];
  const values = (week.data.measures && usable(week.data.measures.weight) && week.data.measures.weight.data.values) || [];
  const i = days.indexOf(todayIso);
  const now = i >= 0 ? num(values[i]) : null;
  if (now === null || !detail.some((d) => d.date === todayIso)) return "";
  for (let j = i - 1; j >= 0; j -= 1) {
    const prev = num(values[j]);
    if (prev === null) continue;
    const diff = now - prev;
    const move = Math.abs(diff) < 0.05 ? "the same as" : diff < 0 ? `down ${fmt1(-diff)} from` : `up ${fmt1(diff)} from`;
    return `${fmt1(now)} lb, ${move} ${weekdayOf(days[j])}.`;
  }
  return `${fmt1(now)} lb.`;
}
const RECOVERY_GLOSS = "Recovery is the wrist strap’s morning score, as a percentage.";
// THE recovery display (round 3): the score is served on a 0-100 scale and the chapters write it
// "98%", so every kit page prints it that way — one helper over the served day text.
export const recoveryShown = (text) => String(text || "").replace(/\brecovery (\d+(?:\.\d+)?) out of 100\b/gi, (m, n) => `recovery ${n}%`);
// One day's facts as one line: "241 minutes of walking · 8.8 hours of sleep; recovery 98
// out of 100 · 153 g protein, 1,732 kcal, under the protein floor". Step counts are left
// out: the served counts are unreliable (a caveat sits on their trend page).
export function factLine(facts, { skip = [], floorMet = null } = {}) {
  return (facts || [])
    .filter((f) => f && f.label && f.text && f.label !== "Steps" && !skip.includes(f.label))
    .map((f) => {
      if (f.label === "Sleep") return `slept ${recoveryShown(f.text.replace(/^(\d[\d.]*) hours/, "$1 hours"))}`;
      if (f.label === "Food" && floorMet !== null) return `${f.text}, ${floorMet ? "at or above" : "under"} the protein target`;
      return recoveryShown(f.text);
    })
    .join(" · ");
}
// `gloss: false` when the page already says what recovery is (the miss card's served sentence
// often carries the same gloss) — said once per page.
export function todayBandHTML(edition, b, base = "/", { gloss = true } = {}) {
  const todayIso = (edition && edition.as_of) || "";
  const week = b.week;
  if (!usable(week)) return soft((week && week.absent_text) || "The last 24 hours are not served right now.");
  const detail = week.data.detail || [];
  const today = detail.find((d) => d.date === todayIso);
  const yIso = dayBefore(todayIso);
  const yesterday = detail.find((d) => d.date === yIso);
  const rows = [];
  const morning = morningLine(week, todayIso);
  const stop = (text) => (/[.!?]$/.test(text) ? text : `${text}.`);
  const row = (key, text, href) => `<li><span class="ck-rows__key">${esc(key)}</span><span>${esc(href ? stop(text) : text)}${href ? ` <a class="ck-link" href="${esc(href)}">The full day</a>` : ""}</span></li>`;
  if (today) {
    const rest = factLine(today.facts, { skip: ["Weight"] });
    const first = morning || factLine(today.facts.filter((f) => f.label === "Weight"));
    rows.push(row("Today so far", [rest && first ? first.replace(/\.$/, "") : first, rest].filter(Boolean).join(" · ") || "Nothing recorded yet today.", `${base}day/?d=${todayIso}`));
  } else {
    rows.push(row("Today so far", "Nothing recorded yet today."));
  }
  if (yesterday) {
    const days = week.data.days || [];
    const food = week.data.measures && week.data.measures.food;
    const met = usable(food) ? (food.data.met || [])[days.indexOf(yIso)] : null;
    const line = factLine(yesterday.facts, { skip: ["Weight"], floorMet: met === true ? true : met === false ? false : null });
    rows.push(row(`Yesterday, ${weekdayOf(yIso)}`, line || "Nothing else was recorded.", `${base}day/?d=${yIso}`));
  }
  const plan = b.life && usable(b.life) && b.life.data.rows && b.life.data.rows.training;
  if (usable(plan) && /^Planned for today: /.test(plan.data.text || "")) rows.push(row("Planned", plan.data.text.replace(/^Planned for today: /, "")));
  const html = `<ul class="ck-rows">${rows.join("")}</ul>`;
  return gloss && /recovery/i.test(html) ? `${html}${small(RECOVERY_GLOSS)}` : html;
}
// ── which coach line the front page may quote (red team 2026-10-17) ────────────
// THE RULE, deterministic, read off two served fields of every line: the front page quotes a
// coach line only when
//   (1) its `move` (the move classifier's own type) is about the record: a call, a reply, a
//       reaction to a result or a bet. A `question` is addressed to him, not about the data,
//       and a line with no served move is not quoted; and
//   (2) its coach is not the mind coach (`coach_id` mind_coach, or `domain` mind on the day's
//       lines). That coach's served domain is behavioral psychology: its lines read HIM (his
//       motive, what he is "avoiding"), not the data or the plan, and a first-time reader
//       should meet the record, not an AI's diagnosis of the person.
// It holds for every quote on the front page: the argument, the day's lines and the last-heard
// row. The excluded lines are still served whole on the coach's own page and the day pages.
//   (3) it passes the plain-language test (`plainLanguage`, round 3 of the 10-17 red team — a word
//       list was a losing game, so the rule is structural): at most FRONT_MAX_WORDS words, one
//       sentence, no term from the coach page's glossary (ck_terms.js TERMS, the one list), no hedge
//       chain ("which means", "suggesting", "for now"), no mechanism noun, and no served reader-gate
//       finding; and
//   (4) a line that names another coach is quoted only as a reply TO that coach — a line about
//       another coach's call ("Lisa's protein prediction came true", said by the food coach) reads
//       as the wrong coach owning it, so it is dropped.
// With no line that qualifies, the front page prints no coach quote rather than a bad one.
export const FRONT_MOVES = new Set(["call", "reply", "reaction", "bet"]);
const FRONT_UNQUOTED = { coach_id: new Set(["mind_coach"]), domain: new Set(["mind"]) };
export const FRONT_MAX_WORDS = 28;
const HEDGE_CHAIN = /\bwhich means\b|\bsuggesting\b|\bfor now\b/i;
export const MECHANISM_NOUNS = /\b(activation|escalation|anchor|regression|variance|mechanism|depletion|confounder|baseline)\b/i;
const sentenceCount = (t) => (String(t).trim().match(/[.!?]+(?=\s+\S)/g) || []).length + 1;
export function plainLanguage(text, line = null) {
  const finding = line && (line.reader || line.reader_findings || line.reader_finding);
  if (finding && (!Array.isArray(finding) || finding.length)) return false;
  const t = String(text || "").trim();
  if (!t || wordCount(t) > FRONT_MAX_WORDS || sentenceCount(t) > 1) return false;
  return !HEDGE_CHAIN.test(t) && !MECHANISM_NOUNS.test(t) && !TERMS.some(([rx]) => rx.test(t));
}
// The coach names a line uses, from the roster the page already knows (the served names in the window).
// Also any "<Name>'s … prediction/call/read/bet" — a call attributed to someone by name, whoever the
// window's roster holds (the line that prompted this rule named a coach who spoke on another day).
const ATTRIBUTED = /\b[A-Z][a-z]+(?:'s|’s) (?:[a-z-]+ ){0,2}(?:prediction|call|read|bet|forecast)\b/;
export function namesOtherCoach(line, names = []) {
  const text = String((line && line.text) || "");
  if (ATTRIBUTED.test(text) && !(line.replies_to && text.includes(String(line.replies_to).split(" ")[0]))) return true;
  return names.some((n) => n && n !== line.coach && n !== line.replies_to && new RegExp(`\\b${escapeRe(n.split(" ")[0])}(?:\\b|’s|'s)`).test(text));
}
export function frontQuotable(line, names = []) {
  if (!line || !FRONT_MOVES.has(line.move) || !plainLanguage(line.text, line) || namesOtherCoach(line, names)) return false;
  return !FRONT_UNQUOTED.coach_id.has(line.coach_id) && !FRONT_UNQUOTED.domain.has(line.domain);
}
// What the coaches said today: each line a move, or the block's own plain sentence. A line
// already printed in the argument above (`skip`: its served texts) is not printed twice;
// when every line was, the band says nothing and the caller drops its label — "" here.
export function coachTodayHTML(block, { skip = [] } = {}) {
  const served = usable(block) ? block.data.lines || [] : [];
  if (!served.length) return soft((block && block.absent_text) || "The coaches have written nothing today.");
  const names = [...new Set(served.map((l) => l && l.coach).filter(Boolean))];
  const lines = served.filter((l) => frontQuotable(l, names) && !skip.includes(l.text));
  if (!lines.length) return "";
  const rows = lines
    .map((l) => {
      const who = [l.coach, l.domain, l.replies_to ? `replying to ${l.replies_to}` : ""].filter(Boolean).join(" · ");
      return `<li><span class="ck-coach__who">${esc(who)}</span><span>“${esc(l.text)}”</span></li>`;
    })
    .join("");
  return `<ul class="ck-coach">${rows}</ul>${block.state === "stale" ? small(block.absent_text) : ""}`;
}

// ── the This week band ─────────────────────────────────────────────────────────
// A measure is "going well" when its target was met on at least five days in seven (or the
// same share of the days recorded); the weight is going well when it ended the week lower
// than it began. The rule is printed under the lists, so the sort is checkable. Training is
// left out of the sort: its only daily test is "trained", which every day passes, and an
// unbroken run of training days is the thing the coaches are arguing about, not a win.
export const WELL_SHARE = 5 / 7;
export const MIN_DAYS_TO_SORT = 5; // fewer recorded days than this and the measure is not sorted
const WEEK_NAMES = { weight: "Weight", sleep: "Sleep", food: "Protein" };
const WEEK_UNSORTED = new Set(["training"]);
const WEEK_TRENDS = { weight: "weight", training: "training", sleep: "sleep", food: "protein" };
export function weekSort(week) {
  const well = [];
  const notWell = [];
  const tooFew = [];
  if (!usable(week)) return { well, notWell, tooFew };
  const measures = week.data.measures || {};
  for (const key of week.data.order || Object.keys(measures)) {
    const m = measures[key];
    if (WEEK_UNSORTED.has(key) || !usable(m) || !m.data.text) continue;
    const item = { key, name: WEEK_NAMES[key] || key, text: m.data.text };
    if (key === "weight") {
      const v = (m.data.values || []).filter((x) => num(x) !== null);
      if (v.length < 2) continue;
      (v[v.length - 1] < v[0] ? well : notWell).push(item);
      continue;
    }
    const met = (m.data.met || []).filter((x) => x === true || x === false);
    if (!met.length) continue;
    // Too few recorded days to sort: two days met of three is not a week that fell short.
    if (met.length < MIN_DAYS_TO_SORT) {
      tooFew.push(item);
      continue;
    }
    (met.filter(Boolean).length / met.length >= WELL_SHARE ? well : notWell).push(item);
  }
  return { well, notWell, tooFew };
}
export function weekSortHTML(week, base = "/") {
  if (!usable(week)) return soft((week && week.absent_text) || "The last seven days are not served right now.");
  const { well, notWell, tooFew } = weekSort(week);
  const list = (items) =>
    `<ul class="ck-rows">${items.map((i) => `<li><a class="ck-rows__key" href="${esc(base)}trend/?m=${esc(WEEK_TRENDS[i.key] || i.key)}">${esc(i.name)}</a><span>${esc(i.text)}</span></li>`).join("")}</ul>`;
  const part = (title, items, none) => `<p class="ck-label">${esc(title)}</p>${items.length ? list(items) : soft(none)}`;
  return [
    part("Going well", well, "Nothing met its target on five days in seven this week."),
    part("Not going well", notWell, "Nothing fell short this week."),
    tooFew.length ? part("Too few days recorded to say", tooFew, "") : "",
    small("Going well means the target was met on at least five days in seven, or the scale ended the week lower than it began. A measure recorded on fewer than five days is not sorted."),
  ].join("");
}
// ── the whole-life scorecard (#4595) ───────────────────────────────────────────
// The rows are decided in code (lambdas/web/edition_scorecard.py, one written rule per area)
// and served in /api/edition's `scorecard` block; this only prints them. Each row reads its
// verdict in words — a dot is never the only carrier — and the rules sit under the rows with
// the day they were set. A row whose source failed prints its own not-served sentence.
const SCORE_LINKS = { body: "trend/?m=weight", training: "trend/?m=training", sleep: "trend/?m=sleep", food: "trend/?m=protein", ai: "coaches/" };
export function scorecardRows(block) {
  if (!usable(block)) return [];
  const rows = block.data.rows || {};
  return (block.data.order || Object.keys(rows))
    .map((key) => ({ key, row: rows[key] }))
    .filter(({ row }) => row && row.state);
}
// The rule under a row is its judgment, not its floor: the "not enough data" clause is a
// grader's detail (round 8b: "a rulebook where a scoreboard should be").
export const shortRule = (rule) => String(rule || "").replace(/\s*(?:Fewer than|When the)[^.]*not enough data\.?\s*$/, "").trim();
// A row that earned its mark: going well, or ahead of the plan. Both take the filled dot.
const EARNED = new Set(["going_well", "faster_than_planned"]);
const NOTHING = /^nothing this week\.?$/i;
export function scorecardHTML(block, base = "/", { label = true } = {}) {
  const rows = scorecardRows(block);
  if (!rows.length) return soft((block && block.absent_text) || "The scorecard is not served right now.");
  const d = block.data;
  // Round 8: the rule sits under the row it decided, so "Not yet" beside "7 of 7 days" is
  // never read without the sentence that explains it.
  const items = rows
    .map(({ key, row }) => {
      const r = usable(row) ? row.data : null;
      const name = (r && r.name) || (d.names && d.names[key]) || key;
      const keyHTML = SCORE_LINKS[key] ? `<a class="ck-rows__key" href="${esc(base)}${SCORE_LINKS[key]}">${esc(name)}</a>` : `<span class="ck-rows__key">${esc(name)}</span>`;
      if (!r || !r.verdict_text) return `<li>${keyHTML}<span>${esc(row.absent_text || "Not served right now.")}</span></li>`;
      // Site-to-A round 1: a row with too little data showed no dot at all beside rows that had
      // one, so the absence read as a missing mark. It takes the kit's hollow dot and says so in
      // words — an absence shown as an absence, never as a verdict either way.
      const thin = r.verdict === "not_enough_data";
      const dot = EARNED.has(r.verdict) ? '<i class="ck-dot" aria-hidden="true"></i>' : `<i class="ck-dot ck-dot--off${thin ? " ck-dot--none" : ""}" aria-hidden="true"></i>`;
      const thinLabel = thin ? ' <span class="ck-small">Not enough data for a verdict.</span>' : "";
      const rule = r.rule ? `<br><span class="ck-small">${esc(shortRule(r.rule))}</span>` : "";
      return `<li>${keyHTML}<span>${dot}<b>${esc(r.verdict_text)}.</b> ${esc(r.text || "")}${thinLabel}${rule}</span></li>`;
    })
    .join("");
  const right = d.went_right || {};
  // "Nothing this week." is not a line worth a row: a party with nothing to show is left out,
  // and with neither having anything the part is not printed at all.
  const said = (part) => (part && part.text && !NOTHING.test(String(part.text).trim()) ? part.text : "");
  const line = (who, part) => (said(part) ? `<li><span class="ck-rows__key">${esc(who)}</span><span>${esc(said(part))}</span></li>` : "");
  const wentRight = `${line("Matthew", right.matthew)}${line("The engine", right.engine)}`;
  return [
    label ? `<p class="ck-label">How the whole thing is going</p>` : "",
    `<ul class="ck-rows">${items}</ul>`,
    wentRight ? `<p class="ck-label">What went right this week</p><ul class="ck-rows">${wentRight}</ul>` : "",
    small(d.rules_set_text),
  ].join("");
}
// The first sentences of a text, up to `max` characters, never cut mid-sentence.
export function firstSentences(text, max = 260) {
  const sentences = String(text || "").replace(/\s+/g, " ").trim().match(/(?:[^.!?]|[.!?](?!\s|$))+[.!?]+(?=\s|$)/g) || [];
  let out = "";
  for (const s of sentences) {
    if (out && (out + s).length > max) break;
    out += s;
    if (out.length >= max) break;
  }
  return out.trim();
}
// The lead coach's weekly read (GET /api/weekly_priority): who, when, and its opening.
export function leadReadHTML(body, base = "/") {
  const text = body && typeof body.weekly_priority === "string" ? body.weekly_priority : "";
  // The read usually opens with a recap of numbers the page already shows; what a weekly
  // reader wants is what the lead asked for, so start from the sentence that names it.
  const at = text.search(/[^.!?]*\bpriority\b/i);
  const lead = firstSentences(at > 0 ? text.slice(at).trim() : text);
  const day = dayInWords(body && body.data_through);
  if (!lead || !day || !body.coach_name) return "";
  const first = String(body.coach_name).split(" ")[0];
  const more = body.coach_id || /^Eli Marsh$/.test(body.coach_name) ? `<p><a class="ck-link" href="${esc(base)}coach/?c=${esc(body.coach_id || "eli_marsh")}">${esc(`${first}’s page`)}</a></p>` : "";
  return `<p class="ck-small">${esc(`${body.coach_name}, the AI lead coach, on ${day}`)}</p><p>“${esc(lead)}”</p>${more}`;
}
// One line from the podcast: the guest's first turn in the published transcript, verbatim.
export function guestQuote(transcript, guestName) {
  const turns = (transcript && transcript.turns) || [];
  const turn = turns.find((t) => t && t.speaker === guestName && t.line);
  if (!turn) return "";
  const line = String(turn.line).replace(/\s+/g, " ").trim();
  const afterGreeting = line.replace(/^Thanks for having me\.\s*/i, "");
  return firstSentences(afterGreeting, 220) || firstSentences(line, 220);
}
export function quotesHTML(chapter, transcript, base = "/") {
  if (!usable(chapter)) return soft((chapter && chapter.absent_text) || "The latest chapter is not served right now.");
  const c = chapter.data;
  const pod = c.podcast;
  const hasPod = usable(pod) && pod.data.mp3_url;
  const out = [];
  const line = firstSentences(c.dek, 200);
  const week = c.week_label ? `${c.week_label} · ` : "";
  out.push(`<p class="ck-small">${esc(`${week}“${c.title}”, the chapter. Written by AI from the record on ${shortDay(c.date)}; Matthew reads each chapter before it publishes.`)}</p>`);
  if (line) out.push(`<p class="ck-quote ck-quote--chapter">${esc(line)}</p>`);
  const read = c.url ? `<a class="ck-btn" href="${esc(c.url)}">Read${num(c.read_minutes) !== null ? ` · ${c.read_minutes} min` : ""}</a>` : "";
  const listen = hasPod ? `<a class="ck-btn ck-btn--ghost" href="${esc(base)}story/">Listen${num(pod.data.duration_minutes) !== null ? ` · ${pod.data.duration_minutes} min` : ""}</a>` : "";
  const quote = hasPod && pod.data.guest ? guestQuote(transcript, pod.data.guest) : "";
  if (quote) {
    const who = `${pod.data.guest}, the AI ${pod.data.guest_domain ? `${pod.data.guest_domain} ` : ""}coach, on the podcast`;
    out.push(`<p class="ck-quote ck-quote--chapter">“${esc(quote)}”</p><p class="ck-small">${esc(who)}</p>`);
  }
  if (read || listen) out.push(`<div class="ck-actions">${read}${listen}</div>`);
  return out.join("");
}
// "September 28 to October 4" — the seven days the band covers.
export function weekSpan(week) {
  const days = usable(week) ? week.data.days || [] : [];
  if (days.length < 2) return "";
  return `${shortDay(days[0])} to ${shortDay(days[days.length - 1])}`;
}
// What arrives next and when — the follow box says what a reader is signing up for.
export function followLine(nextBlock) {
  const ch = nextBlock && nextBlock.data && nextBlock.data.chapter;
  const day = usable(ch) ? dayInWords(ch.data.date) : "";
  // A drafted date is not a promise (the cadence says `drafted_not_promised`): a chapter publishes
  // once Matthew approves it, so the box does not say it is "due".
  if (day && ch.data.drafted_not_promised) return "A new chapter and podcast most weeks, each once Matthew approves it, and the numbers every Sunday.";
  return day ? `The next chapter and podcast are due ${day}. The week’s numbers go out every Sunday.` : "A new chapter and podcast most weeks, the numbers every Sunday.";
}

// ── the argument (round 8) ─────────────────────────────────────────────────────
// What the coaches are arguing about, from the last ARGUMENT_DAYS days of served moves
// (one GET /api/coach_moves?date=<day> each; `days` is their bodies in any order). The
// newest reply and the line it answers make the argument. With no reply in the window,
// the open bet's two sides stand, each with the newest line that coach said. With neither,
// nothing is called an argument: the caller prints a plain sentence. Lines are the served
// words, dated. A line in which a coach names herself as if she were someone else (the
// generator defect #4705 fixed; three such lines were served 2026-10-05 → 10-09) is never
// chosen, so the lead of the page is not a line the page would have to explain.
export const ARGUMENT_DAYS = 7;
const escapeRe = (s) => String(s).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
// Name parts that are ordinary words are never read as a self-reference on their own (the same
// set the generator's gate excludes, coach_moves_sheet.COMMON_WORD_NAME_PARTS, for the live roster).
const COMMON_WORD_NAMES = new Set(["Max", "Park", "Marsh", "Vale", "Brooks"]);
export function namesSelf(line) {
  const name = String((line && line.coach) || "").trim();
  const text = String((line && line.text) || "");
  if (!name || !text) return false;
  const parts = name.split(/\s+/);
  if (parts.length >= 2 && new RegExp(`\\b${escapeRe(name)}\\b`, "i").test(text)) return true;
  return parts.some((p) => p.length >= 2 && !COMMON_WORD_NAMES.has(p) && new RegExp(`(?:^|[^\\w-])${escapeRe(p)}(?![\\w-])`).test(text));
}
// Every served line across the bodies, newest day first, each stamped with its day.
export function argumentLines(days) {
  const ok = (days || []).filter((d) => d && d.state === "ok" && typeof d.date === "string" && Array.isArray(d.lines) && d.lines.length);
  ok.sort((a, b) => b.date.localeCompare(a.date));
  return ok.flatMap((d) => d.lines.filter((l) => l && l.coach && l.text).map((l) => ({ ...l, date: d.date })));
}
// Round 8a's seven reviewers, unanimously: a reply and its answer can agree (they did, on
// October 7 and 8), so an exchange is never headed "disagree". The open bet IS a disagreement
// by construction — two coaches on opposite sides of one dated question — so it leads when
// there is one; an exchange stands in only when there is no bet, as "the latest exchange".
export function pickArgument(days, nextBlock) {
  const bet = nextBlock && nextBlock.data && nextBlock.data.bet;
  const sides = usable(bet) ? (bet.data.sides || []).map((s) => s && s.coach).filter(Boolean) : [];
  if (sides.length >= 2) return { kind: "bet", bet };
  const all = argumentLines(days);
  const names = [...new Set(all.map((l) => l.coach))];
  const lines = all.filter((l) => !namesSelf(l) && frontQuotable(l, names));
  for (const reply of lines) {
    if (reply.move !== "reply" || !reply.replies_to) continue;
    // The newest line by the coach answered, said no later than the reply.
    const first = lines.find((l) => l !== reply && l.coach === reply.replies_to && l.date <= reply.date) || null;
    return { kind: "reply", first, second: reply };
  }
  return null;
}
// "The open bet" / "The latest exchange" / "The coaches" — the section's label follows what
// the page could find, and only the bet is ever called a disagreement.
export function argumentLabel(pick) {
  if (!pick) return "The coaches";
  return pick.kind === "bet" ? "The open bet" : "The latest exchange";
}
export function argumentHeading(pick) {
  // No open bet and no exchange the front page may quote: the one thing the page can say for sure.
  if (!pick) return "No open bet between them this week.";
  if (pick.kind === "bet") return "Two coaches disagree.";
  return "One coach answers another.";
}
// The live number against the open bet: the newest recorded day of the measure the question
// names, from the week block ("Friday: 158 g protein."). "" when the question names no
// measure the week carries, or the week has no reading. Nothing is computed: the day's own
// served value, named by its day.
const BET_MEASURES = [
  [/protein/i, "food", (v) => `${trim1(v)} g protein`],
  [/weight|lb\b|pounds/i, "weight", (v) => `${fmt1(v)} lb`],
  // Sleep TIME only: a deep- or REM-sleep share is not the hours the week carries (round 2).
  [/^(?!.*(?:deep|REM|share|%)).*(?:sleep time|hours of sleep|sleep duration)/i, "sleep", (v) => `${trim1(v)} hours of sleep`],
  [/train|minutes/i, "training", (v) => `${trim1(v)} minutes of training`],
];
const trim1 = (v) => (num(v) === null ? "" : String(Number(v.toFixed(1))));
export function betLiveLine(bet, week) {
  if (!usable(bet) || !usable(week) || !bet.data.question) return "";
  const hit = BET_MEASURES.find(([re]) => re.test(bet.data.question));
  if (!hit) return "";
  const m = week.data.measures && week.data.measures[hit[1]];
  const days = week.data.days || [];
  if (!usable(m) || !Array.isArray(m.data.values)) return "";
  const weekText = String(m.data.text || "").trim();
  const week7 = weekText ? ` This week, ${weekText.charAt(0).toLowerCase()}${weekText.slice(1)}${/[.!?]$/.test(weekText) ? "" : "."}` : "";
  for (let i = m.data.values.length - 1; i >= 0; i -= 1) {
    if (num(m.data.values[i]) !== null && days[i]) return `${weekdayOf(days[i])}: ${hit[2](m.data.values[i])}.${week7}`;
  }
  return "";
}
// Each coach's job in one or two words, for the first mention of a name on the front page
// (round 8b, the friend: "two strangers arguing"). Keyed on the served persona id.
export const SHORT_JOBS = {
  eli_marsh: "lead",
  sleep_coach: "sleep",
  explorer_coach: "statistics",
  nutrition_coach: "food",
  mind_coach: "mind",
  physical_coach: "training",
  labs_coach: "blood tests",
  glucose_coach: "blood sugar",
};
// name -> short job, from the served lines (the only front-page read that pairs a name with its id).
export function jobsByName(days) {
  const out = {};
  for (const l of argumentLines(days)) if (l.coach_id && SHORT_JOBS[l.coach_id] && !out[l.coach]) out[l.coach] = SHORT_JOBS[l.coach_id];
  return out;
}
// One sentence per side: "Nathan Reeves (mind) says no: “Fuel-cognition link may be slower than
// estimated”." — the job only when known, and the coach's reason (#4809: the opening position
// from the docket row, one clause in its served words, `sides[].reason`) only when served. A
// side with no reason is the side alone; nothing is written in a coach's voice here.
// `reasons: false` prints the sides alone: the reasons are the FRONT card's (ruling
// 2026-10-11 — the coaches page keeps its four-screen budget and links to the front card).
// Round 2 of the 10-17 red team: a job label goes beside every side or none ("Lisa Park (sleep)"
// beside a bare "Max Reyes" read as a ranking), and a reason is printed only when it passes the
// front page's plain-language test — otherwise the side stands alone.
export function betSidesLines(bet, jobs = {}, { reasons = true } = {}) {
  if (!usable(bet)) return [];
  const sides = (bet.data.sides || []).filter((s) => s && s.coach);
  const labelled = sides.length > 0 && sides.every((s) => jobs[s.coach]);
  return sides.map((s) => {
    const who = `${s.coach}${labelled ? ` (${jobs[s.coach]})` : ""} says ${s.says}`;
    const raw = reasons && typeof s.reason === "string" ? s.reason.trim() : "";
    const why = raw && plainLanguage(raw) ? raw : "";
    return why ? `${who}: “${why}”.` : `${who}.`;
  });
}
// The sides as one line: "Nathan Reeves (mind) says no. Marcus Webb (food) says yes."
export const betSidesLine = (bet, jobs = {}, opts = {}) => betSidesLines(bet, jobs, opts).join(" ");
// The newest line the coaches said in the window, minus any the page already printed, as one
// dated row — what the Today band shows when no coach spoke today. "" with nothing left.
// A short line is preferred (round 8b: the one coach voice on the front page was its hardest
// sentence): the newest of forty words or fewer, else the newest at all.
export const HEARD_MAX_WORDS = 40;
const wordCount = (t) => String(t || "").trim().split(/\s+/).filter(Boolean).length;
export function lastHeardHTML(days, skip = [], base = "/") {
  const all = argumentLines(days);
  const names = [...new Set(all.map((l) => l.coach))];
  const clean = all.filter((l) => !namesSelf(l) && frontQuotable(l, names) && !skip.includes(l.text));
  const line = clean.find((l) => wordCount(l.text) <= HEARD_MAX_WORDS) || clean[0];
  if (!line) return "";
  const job = line.coach_id && SHORT_JOBS[line.coach_id] ? ` (${SHORT_JOBS[line.coach_id]})` : "";
  const name = line.coach_id ? `<a class="ck-link" href="${esc(base)}coach/?c=${esc(line.coach_id)}">${esc(line.coach)}</a>${esc(job)}` : esc(line.coach);
  const kind = line.move === "reply" && line.replies_to ? `answering ${line.replies_to}` : "";
  return `<ul class="ck-coach"><li><span class="ck-coach__who">${name}${esc(` · ${[kind, dayInWords(line.date)].filter(Boolean).join(" · ")}`)}</span><span>“${esc(line.text)}”</span></li></ul>`;
}
// The lines as the kit's coach rows: who (a door to the coach's page) · what kind of line ·
// the day, then the served words. "" with nothing to print.
export function argumentHTML(pick, base = "/") {
  if (!pick) return "";
  const who = (l, kind) => {
    const name = l.coach_id ? `<a class="ck-link" href="${esc(base)}coach/?c=${esc(l.coach_id)}">${esc(l.coach)}</a>` : esc(l.coach);
    return `<span class="ck-coach__who">${name}${esc(` · ${[kind, dayInWords(l.date)].filter(Boolean).join(" · ")}`)}</span>`;
  };
  const row = (l, kind) => `<li>${who(l, kind)}<span>“${esc(l.text)}”</span></li>`;
  if (pick.kind !== "reply") return "";
  const html = [pick.first ? row(pick.first, "") : "", row(pick.second, `answering ${pick.second.replies_to}`)].join("");
  return html ? `<ul class="ck-coach">${html}</ul>` : "";
}
// The served texts a pick prints, so the Today band can leave them out.
export const argumentTexts = (pick) => (pick && pick.kind === "reply" ? [pick.first, pick.second].filter(Boolean).map((l) => l.text) : []);

// ── go deeper: the chapter's row ───────────────────────────────────────────────
// One row in the "Go deeper" list for the latest chapter: its week and title as the door, the
// read time as the grey note. A block that failed prints its own sentence — never a blank.
export function chapterRowHTML(chapter) {
  if (!usable(chapter) || !chapter.data.title || !chapter.data.url) return soft((chapter && chapter.absent_text) || "The latest chapter is not served right now.");
  const c = chapter.data;
  const lead = c.week_label ? `${c.week_label} · ` : "";
  // Site-to-A round 1 (front:F6): the row leads "Go deeper" and its note is the chapter's own
  // date and length — the dek's first sentence carried claims ("crossed 310 pounds", "18.5 pounds
  // gone") that Story has to repair against the page and the front page cannot.
  const note = ["The latest chapter", shortDay(c.date), num(c.read_minutes) !== null ? `${c.read_minutes} min` : ""].filter(Boolean).join(" · ");
  return `<a class="ck-rows__key" href="${esc(c.url)}">${esc(`${lead}“${c.title}”`)}</a><span>${esc(note)}</span>`;
}
