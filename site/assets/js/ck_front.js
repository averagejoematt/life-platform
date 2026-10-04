// ck_front.js — the reshaped preview front page (#4586, epic #4580).
//
// The page has two rhythms under one fixed top. The top never changes shape: who he is,
// his own dated note, the daily mark, and the coaches' last settled call with the next
// one due. Under it sit two bands:
//
//   TODAY      changes every day and is specific to the last 24 hours — this morning's
//              weigh-in and sleep, what was recorded yesterday, what is planned, and what
//              the coaches said today.
//   THIS WEEK  changes weekly — what is going well and what is not, the lead coach's read,
//              one line from the chapter and one from the podcast.
//
// Every builder is pure and exported for tests/js/ck_front_4586.test.mjs. Each prints a
// plain sentence when its data is absent: never a blank, a zero or another day's number.
// Standing rules held here: no first-person sentence is generated (his words are his own
// and dated), no count of earlier starts, no "Dr.", no percentage on fewer than 20 items.
import { esc } from "/assets/js/evidence_shared.js";
import { dayInWords } from "/assets/js/entry_age.js";

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
// One stripe a day for the last four weeks, in a frame that never changes: green when the
// scale went down from the weigh-in before, dark when it went up or held, a short tick
// when there was no weigh-in. The same drawing is the link-preview image, so it carries
// no axis — the caption beside it carries the one plain number.
export const MARK_DAYS = 28;
export function markDays(series, todayIso, days = MARK_DAYS) {
  const byDay = new Map((series || []).filter((w) => w && w.date && num(w.lbs) !== null).map((w) => [w.date, w.lbs]));
  const sorted = [...byDay.keys()].sort();
  const out = [];
  let iso = todayIso;
  for (let i = 0; i < days && iso; i += 1) {
    const lbs = byDay.has(iso) ? byDay.get(iso) : null;
    let kind = "none";
    if (lbs !== null) {
      const before = sorted.filter((d) => d < iso).pop();
      kind = before === undefined ? "first" : lbs < byDay.get(before) ? "down" : "up";
    }
    out.unshift({ date: iso, lbs, kind });
    iso = dayBefore(iso);
  }
  return out;
}
export function markSentence(cells) {
  const down = cells.filter((c) => c.kind === "down").length;
  const up = cells.filter((c) => c.kind === "up").length;
  const none = cells.filter((c) => c.kind === "none").length;
  const parts = [`${down} ${down === 1 ? "day" : "days"} down`, `${up} up or level`];
  if (none) parts.push(`${none} with no weigh-in`);
  return `The last ${cells.length} days: ${parts.join(", ")}.`;
}
export function markHTML(series, todayIso, { width = 640, height = 96 } = {}) {
  if (!todayIso) return "";
  const cells = markDays(series, todayIso);
  if (!cells.some((c) => c.lbs !== null)) return "";
  const gap = 4;
  const w = (width - gap * (cells.length - 1)) / cells.length;
  const rects = cells
    .map((c, i) => {
      const x = (i * (w + gap)).toFixed(1);
      if (c.kind === "none") return `<rect class="ck-mark__none" x="${x}" y="${height - 6}" width="${w.toFixed(1)}" height="6" rx="2"/>`;
      const cls = c.kind === "down" ? "ck-mark__down" : c.kind === "up" ? "ck-mark__up" : "ck-mark__first";
      return `<rect class="${cls}" x="${x}" y="0" width="${w.toFixed(1)}" height="${height}" rx="3"/>`;
    })
    .join("");
  return `<svg class="ck-mark" viewBox="0 0 ${width} ${height}" role="img" aria-label="${esc(markSentence(cells))}">${rects}</svg>`;
}
// "312.1 lb · Day 29 · 15.2 down, 127.1 to go to 185" — the mark's one line of numbers,
// the weight in bold. Returns HTML.
export function markCaption(today, edition) {
  if (!usable(today)) return "";
  const t = today.data;
  const [now, start, goal] = [num(t.weight_lbs), num(t.start_weight_lbs), num(t.goal_weight_lbs)];
  if (now === null) return "";
  const parts = [`<b>${esc(fmt1(now))} lb</b>${t.date && edition && t.date !== edition.as_of ? esc(` on ${shortDay(t.date)}`) : ""}`];
  if (edition && num(edition.day_n) !== null && edition.day_n >= 1) parts.push(`Day ${edition.day_n}`);
  if (start !== null && goal !== null && start > goal) {
    const lost = start - now;
    parts.push(esc(`${fmt1(Math.abs(lost))} ${lost >= 0 ? "down" : "up"}, ${fmt1(Math.max(0, now - goal))} to go to ${String(Number(goal.toFixed(1)))}`));
  }
  return parts.join(" · ");
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
const RECOVERY_GLOSS = "recovery is the wrist strap’s morning score out of 100";
// Step counts are left off this page: the served counts are unreliable (a caveat sits on
// their trend page).
function factRows(facts, { skip = [], floorMet = null } = {}) {
  return (facts || [])
    .filter((f) => f && f.label && f.text && f.label !== "Steps" && !skip.includes(f.label))
    .map((f) => {
      let text = f.text;
      if (f.label === "Food" && floorMet !== null) text += floorMet ? ", at or above the protein floor" : ", under the protein floor";
      return `<li><span class="ck-rows__key">${esc(f.label)}</span><span>${esc(text)}</span></li>`;
    })
    .join("");
}
export function todayBandHTML(edition, b, base = "/") {
  const todayIso = (edition && edition.as_of) || "";
  const week = b.week;
  if (!usable(week)) return soft((week && week.absent_text) || "The last 24 hours are not served right now.");
  const detail = week.data.detail || [];
  const today = detail.find((d) => d.date === todayIso);
  const yIso = dayBefore(todayIso);
  const yesterday = detail.find((d) => d.date === yIso);
  const out = [];
  const morning = morningLine(week, todayIso);
  const dayLink = (iso, text) => `<p><a class="ck-link" href="${esc(base)}day/?d=${esc(iso)}">${esc(text)}</a></p>`;
  if (today) {
    const rows = `${morning ? `<li><span class="ck-rows__key">Weight</span><span>${esc(morning)}</span></li>` : ""}${factRows(today.facts, { skip: morning ? ["Weight"] : [] })}`;
    out.push(`<p class="ck-label">This morning</p><ul class="ck-rows">${rows}</ul>`);
    if (/recovery/i.test(rows)) out.push(small(`${RECOVERY_GLOSS.charAt(0).toUpperCase()}${RECOVERY_GLOSS.slice(1)}.`));
  } else {
    out.push(`<p class="ck-label">This morning</p>${soft("Nothing recorded yet today.")}`);
  }
  if (yesterday) {
    const days = week.data.days || [];
    const food = week.data.measures && week.data.measures.food;
    const met = usable(food) ? (food.data.met || [])[days.indexOf(yIso)] : null;
    const rows = factRows(yesterday.facts, { skip: ["Weight"], floorMet: met === true ? true : met === false ? false : null });
    out.push(`<p class="ck-label">Yesterday, ${esc(weekdayOf(yIso))}</p>${rows ? `<ul class="ck-rows">${rows}</ul>` : soft("Nothing else was recorded.")}${dayLink(yIso, "Everything recorded yesterday")}`);
  }
  const plan = b.life && usable(b.life) && b.life.data.rows && b.life.data.rows.training;
  if (usable(plan) && /^Planned for today/.test(plan.data.text || "")) out.push(soft(plan.data.text));
  return out.join("");
}
// What the coaches said today: each line a move, or the block's own plain sentence.
export function coachTodayHTML(block) {
  const lines = usable(block) ? block.data.lines || [] : [];
  if (!lines.length) return soft((block && block.absent_text) || "The coaches have written nothing today.");
  const rows = lines
    .map((l) => {
      const who = [l.coach, l.domain, l.replies_to ? `replying to ${l.replies_to}` : ""].filter(Boolean).join(" · ");
      return `<li><span class="ck-coach__who">${esc(who)}</span><span>“${esc(l.text)}”</span></li>`;
    })
    .join("");
  return `<ul class="ck-coach">${rows}</ul>${block.state === "stale" ? small(block.absent_text) : ""}`;
}

// ── the This week band ─────────────────────────────────────────────────────────
// A measure is "going well" when it was met on at least five days in seven (or the same
// share of the days recorded); the weight is going well when it ended the week lower than
// it began. The rule is printed under the lists, so the sort is checkable.
export const WELL_SHARE = 5 / 7;
const WEEK_NAMES = { weight: "Weight", training: "Training", sleep: "Sleep", food: "Protein" };
const WEEK_TRENDS = { weight: "weight", training: "training", sleep: "sleep", food: "protein" };
export function weekSort(week) {
  const well = [];
  const notWell = [];
  if (!usable(week)) return { well, notWell };
  const measures = week.data.measures || {};
  for (const key of week.data.order || Object.keys(measures)) {
    const m = measures[key];
    if (!usable(m) || !m.data.text) continue;
    const item = { key, name: WEEK_NAMES[key] || key, text: m.data.text };
    if (key === "weight") {
      const v = (m.data.values || []).filter((x) => num(x) !== null);
      if (v.length < 2) continue;
      (v[v.length - 1] < v[0] ? well : notWell).push(item);
      continue;
    }
    const met = (m.data.met || []).filter((x) => x === true || x === false);
    if (!met.length) continue;
    (met.filter(Boolean).length / met.length >= WELL_SHARE ? well : notWell).push(item);
  }
  return { well, notWell };
}
export function weekSortHTML(week, base = "/") {
  if (!usable(week)) return soft((week && week.absent_text) || "The last seven days are not served right now.");
  const { well, notWell } = weekSort(week);
  const list = (items) =>
    `<ul class="ck-rows">${items.map((i) => `<li><a class="ck-rows__key" href="${esc(base)}trend/?m=${esc(WEEK_TRENDS[i.key] || i.key)}">${esc(i.name)}</a><span>${esc(i.text)}</span></li>`).join("")}</ul>`;
  const part = (title, items, none) => `<p class="ck-label">${esc(title)}</p>${items.length ? list(items) : soft(none)}`;
  return [
    part("Going well", well, "Nothing met its mark on five days in seven this week."),
    part("Not going well", notWell, "Nothing fell short this week."),
    small("Going well means the mark was met on at least five days in seven, or the scale ended the week lower than it began."),
  ].join("");
}
// The first sentences of a text, up to `max` characters, never cut mid-sentence.
export function firstSentences(text, max = 260) {
  const sentences = String(text || "").replace(/\s+/g, " ").trim().match(/[^.!?]+[.!?]+(?=\s|$)/g) || [];
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
  const lead = firstSentences(text);
  const day = dayInWords(body && body.data_through);
  if (!lead || !day || !body.coach_name) return soft("The lead coach’s read of the week is not served right now.");
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
  return day ? `The next chapter and podcast are due ${day}. The week’s numbers go out every Sunday.` : "A new chapter and podcast most weeks, the numbers every Sunday.";
}
