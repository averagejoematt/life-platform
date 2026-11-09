// The Human Story's read-side helpers (HS1, built dark — src/lib/story_dark.js). Pure: the snapshot's story.json, the
// public Day objects and the latest edition in; the rows the timeline, the episode index and the "story so far" entry
// render out. Nothing here reads a journal, a State of Mind or a video-diary field, and nothing counts, dates or marks
// any of them: a week is its seven days and, when one was approved and published, its installment. A week without an
// installment says only that — never held, skipped, quiet or why.
import { dayInWords } from "./format.js";

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
