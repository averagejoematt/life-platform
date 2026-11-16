// The Human Story's read-side helpers (HS1, built dark — src/lib/story_dark.js). Pure: the snapshot's story.json, the
// public Day objects and the latest edition in; the rows the timeline, the episode index and the "story so far" entry
// render out. Nothing here reads a journal, a State of Mind or a video-diary field, and nothing counts, dates or marks
// any of them: a week is its seven days and, when one was approved and published, its installment. A week without an
// installment says only that — never held, skipped, quiet or why.
import { dayInWords, num } from "./format.js";

const iso = (s) => typeof s === "string" && /^\d{4}-\d{2}-\d{2}$/.test(s);

/** "6 to 12 September 2026" / "27 September to 3 October 2026" / across a year end, both years. Never the ISO form. */
export function spanWords(start, end) {
  if (!iso(start) || !iso(end)) return null;
  const a = dayInWords(start);
  const b = dayInWords(end);
  const [ay, am] = start.split("-");
  const [by, bm] = end.split("-");
  if (ay !== by) return `${a} to ${b}`;
  if (am !== bm) return `${a.replace(/ \d{4}$/, "")} to ${b}`;
  return `${Number(start.slice(8, 10))} to ${b}`;
}

/** The installments in reading order (Week 1 first), each with its date and week in words. */
export function installmentRows(story) {
  if (!story || story.state !== "ok") return [];
  return [...(story.installments_index || [])]
    .filter((i) => i && typeof i.chapter_id === "string" && typeof i.title === "string" && iso(i.date))
    .sort((a, b) => a.week - b.week || (a.date < b.date ? -1 : 1))
    .map((i) => ({
      id: i.chapter_id,
      week: i.week,
      weekLabel: `Week ${i.week}`,
      title: i.title,
      dateWords: dayInWords(i.date),
    }));
}

/**
 * The timeline: one row per program week the platform serves, oldest first. Each row: the week, its span in words,
 * its installment (when one is in the index) and the Day objects that fall inside it (links to the existing Day
 * pages). `days` are the snapshot's public Day objects; only their id and date are read.
 */
export function timelineRows(story, days = []) {
  if (!story || story.state !== "ok") return [];
  const byId = new Map(installmentRows(story).map((r) => [r.id, r]));
  const dated = (days || []).filter((d) => d && iso(d.date) && typeof d.id === "string").sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0));
  return [...(story.story_weeks || [])]
    .filter((w) => w && Number.isInteger(w.week) && w.week >= 1 && iso(w.start) && iso(w.end))
    .sort((a, b) => a.week - b.week)
    .map((w) => ({
      week: w.week,
      weekLabel: `Week ${w.week}`,
      span: spanWords(w.start, w.end),
      installment: (w.chapter_id && byId.get(w.chapter_id)) || null,
      days: dated
        .filter((d) => d.date >= w.start && d.date <= w.end)
        .map((d) => ({ id: d.id, words: dayInWords(d.date, { weekday: true }).replace(/ \d{4}$/, "") })),
    }));
}

/**
 * The "story so far" entry: where the experiment is (the edition's day number and the genesis date, both public), how
 * many weeks the platform lists, and the first and the latest installment in the index. Null when the file is absent.
 */
export function soFar(story, edition) {
  if (!story || story.state !== "ok") return null;
  const rows = installmentRows(story);
  const weeks = (story.story_weeks || []).filter((w) => w && Number.isInteger(w.week) && w.week >= 1).length;
  const start = iso(story.genesis) ? dayInWords(story.genesis) : null;
  const dayN = edition && Number.isInteger(edition.day_n) ? edition.day_n : null;
  const where = [dayN != null ? `Day ${dayN}` : null, start ? `of an experiment that began on ${start}` : null].filter(Boolean).join(" ");
  return {
    sentence: where ? `${where}.` : null,
    weeks,
    weeksWords: weeks === 1 ? "One week" : `${weeks} weeks`,
    count: rows.length,
    first: rows[0] || null,
    latest: rows.length > 1 ? rows[rows.length - 1] : null,
  };
}

// ── "That week in the record" (one quiet line per week) ──────────────────────────────────────────────────────────
// Built ONLY from the public Day objects the snapshot already publishes (the same objects /data/day/<date>/ renders and
// /data/days.json indexes): the measured weigh-ins, the sessions, the food log and the calls settled. Fail closed on
// the week: a line is composed ONLY for a week whose installment is in the approved, published index
// (scripts/publish_snapshot_story.py) — a held, excluded, pending or under-way week gets no line at all, so nothing
// counted here can stand for a week the owner has not released. A field the week cannot answer is omitted, never
// shown as zero; a weight is printed only from a recorded weigh-in (has_weighin), never from a mean or a normal.

const GRADED_CALLS = new Set(["confirmed", "refuted", "inconclusive"]);
const KNOWN_SESSION = new Set(["served", "none logged"]);
const KNOWN_FOOD = new Set(["served", "not logged"]);
const plural = (n, one, many) => (n === 1 ? one : many);
const dayWords = (d) => dayInWords(d.date, { weekday: true });

/**
 * The week's record, or null. `story` is story.json, `week` a story_weeks row, `days` the public Day objects, and
 * `callOf(id)` returns the PUBLIC prediction object for a call id (or null) — a call is counted only when it has a
 * public ledger page, and never while its verdict is under classification review (disputed.js: the same rule as every
 * "checked" count). Each part: { key, text: [segments] }; a segment is a string or { text, type, id, label } — a link
 * to that Day page or call page.
 */
export function weekRecord(story, week, days = [], callOf = () => null) {
  if (!story || story.state !== "ok" || !week || !week.chapter_id || !iso(week.start) || !iso(week.end)) return null;
  const indexed = (story.installments_index || []).some((i) => i && i.chapter_id === week.chapter_id && i.week === week.week);
  if (!indexed) return null;
  const inWeek = (days || [])
    .filter((d) => d && typeof d.id === "string" && iso(d.date) && d.date >= week.start && d.date <= week.end)
    .sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0));
  if (!inWeek.length) return null;
  const parts = [];
  const dayLink = (d, text) => ({ text, type: "day", id: d.id, label: dayWords(d) });

  // Weight: the first and the last RECORDED weigh-in of the week (never a carried or averaged value).
  const weighed = inWeek.filter((d) => d.has_weighin === true && d.readings && Number.isFinite(d.readings.weight_lbs));
  if (weighed.length === 1) {
    const d = weighed[0];
    parts.push({ key: "weight", text: ["weighed ", dayLink(d, `${num(d.readings.weight_lbs, 1)} lb`)] });
  } else if (weighed.length > 1) {
    const a = weighed[0];
    const b = weighed[weighed.length - 1];
    parts.push({ key: "weight", text: ["weight ", dayLink(a, num(a.readings.weight_lbs, 1)), " to ", dayLink(b, `${num(b.readings.weight_lbs, 1)} lb`)] });
  }

  // Sessions: days whose session the platform served; only when the week's session record is readable at all.
  if (inWeek.some((d) => KNOWN_SESSION.has(d.workout_state))) {
    const trained = inWeek.filter((d) => d.workout_state === "served" && d.workout);
    if (trained.length) {
      const n = trained.length;
      parts.push({ key: "sessions", text: [dayLink(trained[0], `${n} ${plural(n, "session", "sessions")}`)] });
    }
  }

  // Food: days with food logged (served, and not the platform's own logging-gap flag) of the days it can read.
  const foodKnown = inWeek.filter((d) => KNOWN_FOOD.has(d.food_state));
  if (foodKnown.length) {
    const logged = foodKnown.filter((d) => d.food_state === "served" && d.food && d.food.logging_gap !== true);
    if (logged.length) parts.push({ key: "food", text: ["food logged ", dayLink(logged[0], `${logged.length} of ${foodKnown.length} days`)] });
  }

  // Calls settled that week: graded verdicts on public, undisputed ledger entries — K right of N settled.
  const settled = [];
  for (const d of inWeek) {
    for (const c of d.calls_settled || []) {
      const p = c && typeof c.prediction_id === "string" ? callOf(c.prediction_id) : null;
      if (!p || p.classification_review === true || !GRADED_CALLS.has(c.verdict)) continue;
      settled.push({ day: d, id: c.prediction_id, right: c.verdict === "confirmed" });
    }
  }
  if (settled.length) {
    const k = settled.filter((c) => c.right).length;
    const n = settled.length;
    const text = `${k} of ${n} right`;
    const link = n === 1 ? { text, type: "prediction", id: settled[0].id, label: `The call, settled ${dayWords(settled[0].day)}` } : dayLink(settled[0].day, text);
    parts.push({ key: "calls", text: [`${plural(n, "call", "calls")} settled `, link] });
  }
  return parts.length ? { week: week.week, parts } : null;
}

/** The record for every served week, keyed by week number; held / excluded / unindexed weeks are simply absent. */
export function weekRecords(story, days = [], callOf = () => null) {
  const out = new Map();
  if (!story || story.state !== "ok") return out;
  for (const w of story.story_weeks || []) {
    const r = weekRecord(story, w, days, callOf);
    if (r) out.set(w.week, r);
  }
  return out;
}
