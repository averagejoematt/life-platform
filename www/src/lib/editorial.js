// The editorial release (owner authorisation, review 14, 2026-11-24): the homepage's first screen, the featured reader
// path (The Rate Flag → Prologue → Park's Blind Spot, revisited → What happens next → Subscribe), the date-first chapter
// index and the figures "What happens next" shares with the homepage. Pure functions here (tests/editorial.test.mjs);
// the one async reader, currentProgress(), loads the snapshot the same way the homepage always has.
//
// Two rules hold every sentence below:
//   * the owner's first-person words (the homepage opening) are static text in pages/index.astro, never built here;
//   * every changing figure is the platform's, read from the snapshot through ONE computation — progress() — which the
//     homepage's data line, its "where the experiment stands" body figure and "What happens next" all read, so the
//     three cannot disagree (scripts/check_www_build.py::progress_agreement checks the built pages).

import { bodyChange } from "./standing.js";
import { dayInWords, num } from "./format.js";
import { featureMeta } from "./feature.js";

const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
const ISO = /^\d{4}-\d{2}-\d{2}$/;
const ms = (iso) => Date.parse(`${iso}T00:00:00Z`);
const isoOf = (t) => new Date(t).toISOString().slice(0, 10);

/** "6–8 September", "30 September – 6 October", "4–10 November 2026" ({year:true}) — the index's date-first labels. */
export function dashRange(a, b, opts = {}) {
  if (!ISO.test(a || "") || !ISO.test(b || "") || a > b) return null;
  const [ya, ma, da] = a.split("-").map(Number);
  const [yb, mb, db] = b.split("-").map(Number);
  const y = opts.year ? ` ${yb}` : "";
  if (ya !== yb) return `${da} ${MONTHS[ma - 1]} ${ya} – ${db} ${MONTHS[mb - 1]} ${yb}`;
  if (a === b) return `${da} ${MONTHS[ma - 1]}${y}`;
  if (ma === mb) return `${da}–${db} ${MONTHS[mb - 1]}${y}`;
  return `${da} ${MONTHS[ma - 1]} – ${db} ${MONTHS[mb - 1]}${y}`;
}

/** The experiment's day number of `iso` (day 1 = the start). */
export function dayNo(iso, startDate) {
  return ISO.test(iso || "") && ISO.test(startDate || "") ? Math.round((ms(iso) - ms(startDate)) / 864e5) + 1 : null;
}

// ── the one progress computation ───────────────────────────────────────────────────────────────────────────────────

/**
 * Where the weight stands: {day, latest: {value, date}, start: {value, date}, body, below, lighter} — `body` is
 * standing.js bodyChange (the homepage's figure since 2026-11-15), `below` its pounds to one decimal, as the homepage
 * prints them. Null when no weigh-in is served.
 */
export function progress({ weightSeries, startDate, startValue, dayN }) {
  const body = bodyChange(weightSeries, startDate, startValue);
  if (!body) return null;
  const readings = weightSeries.days.filter((d) => (!startDate || d.date >= startDate) && d.value != null && !d.gap);
  const last = readings[readings.length - 1];
  const start = startValue ?? readings[0].value;
  return {
    day: Number.isInteger(dayN) ? dayN : null,
    latest: { value: last.value, date: last.date },
    start: { value: start, date: startDate || readings[0].date },
    body,
    below: num(Math.abs(body.lost), 1),
    lighter: body.lost < 0,
  };
}

/** The homepage's platform-voiced data line, directly below the owner's opening — never inside it. */
export function progressLine(p) {
  if (!p) return null;
  const startDay = dayInWords(p.start.date)?.replace(/ \d{4}$/, "");
  return [
    p.day != null ? `Day ${p.day}` : null,
    `latest weigh-in ${num(p.latest.value, 1)} lb on ${dayInWords(p.latest.date)}`,
    `${p.below} lb ${p.lighter ? "below" : "above"} the ${startDay} start (${num(p.start.value, 1)} lb)`,
  ]
    .filter(Boolean)
    .join(" · ");
}

/** The snapshot's inputs to progress(), read the way the homepage always has: the start from the journey (else the
 *  edition's today block), the day from the edition. */
export function progressInputs({ series, journey, edition }) {
  const today = edition?.blocks?.today?.state === "ok" ? edition.blocks.today.data : null;
  return {
    weightSeries: series ? series["weight_lbs"] || null : null,
    startDate: today?.start_date || edition?.start_date || null,
    startValue: journey?.start_weight_lbs ?? today?.start_weight_lbs ?? null,
    dayN: edition?.day_n ?? null,
  };
}

// ── the coaches against a guess (the first screen's dated evidence line, "What happens next" and the coaches page) ──

/** {asOf, k, n, eligible, baseline, words} from the calibration file — the room's verified lead and its denominators,
 *  as served (lib/calibration.js). Null unless all are served. */
export function coachesChecked(calFile, lead, steps) {
  if (!calFile || calFile.state !== "ok" || !lead || !lead.baseline || !steps) return null;
  const asOf = calFile.as_of || calFile.calibration?.as_of || null;
  if (!ISO.test(String(asOf || "").slice(0, 10))) return null;
  return { asOf: String(asOf).slice(0, 10), k: lead.k, n: lead.n, eligible: steps.eligible, baseline: lead.baseline.right, verdict: lead.sign?.verdict || null, words: lead.sign?.words || null };
}

// ── "What happens next": the three questions (owner, review 11 §What happens next; approved as supplied, review 14) ──

/** The three questions with their live figures. `own` maps an own-words key to the served line or null; a sentence
 *  quoting his words is shown only when the platform serves the line (lib/own_words.js). His 8 November sentence about
 *  the coaches is a dated, historical statement: placed only where `own.coaches_changed` is passed (the path's page,
 *  never the homepage — owner decision on PR #6263), and always with its full date. */
export function whatHappensNext({ p, checked, own = {} }) {
  const q1 = p
    ? `It's day ${p.day}. He is ${p.below} pounds ${p.lighter ? "lighter" : "heavier"} and has weighed in on ${p.body.readings} of the ${p.body.days} mornings. He counted this start as “the 15th or 16th reset in a few months”. Only the weeks ahead can answer it.`
    : "He counted this start as “the 15th or 16th reset in a few months”. Only the weeks ahead can answer it.";
  const level = checked && checked.verdict === "no_clear_difference";
  const q2a = checked
    ? level
      ? `So far the coaches' predictions are level with a guess that nothing changes: ${checked.k} to ${checked.baseline}, on the ${checked.n} of ${checked.eligible} graded calls that could be checked fairly.`
      : `So far, on the ${checked.n} of ${checked.eligible} graded calls that could be checked fairly, the coaches have ${checked.k} right and a guess that nothing changes ${checked.baseline}: ${checked.words}.`
    : "The coaches' checked record is not served in this build.";
  const q2b = own.coaches_changed ? ` On 8 November 2026 Matt wrote: “${own.coaches_changed}”` : "";
  const q3b = own.content ? " On 8 November he wrote one sentence: “I feel more content overall.”" : "";
  return [
    { n: "01", q: "Will this attempt last?", text: q1 },
    { n: "02", q: "Will the AI prove genuinely helpful?", text: `${q2a}${q2b} More graded calls could move this, and so could a day he records acting on a coach's advice.` },
    {
      n: "03",
      q: "Will the measurable progress translate into a better, sustainable life?",
      text: `The weight is measured every morning; whether he is happier is not measured anywhere on the site.${q3b} Whether the pace is costing muscle is also open: no body scan was taken at the start. A new scan, or more of his own words, could add to what is known.`,
    },
  ];
}

// ── the featured path (distinct from the chronological chapters) ─────────────────────────────────────────────────────

export const START = "/story/start/";
export const PATH = [
  { key: "rate-flag", label: "1 · The Rate Flag", to: `${START}rate-flag/` },
  { key: "prologue", label: "2 · How it started", to: `${START}prologue/` },
  { key: "feature", label: "3 · Park's Blind Spot, revisited", to: featureMeta("parks-blind-spot-revisited").path },
  { key: "next", label: "What happens next", to: `${START}what-happens-next/` },
  { key: "subscribe", label: "Subscribe", to: `${START}what-happens-next/#follow` },
];
/** The chapters the path frames, by id (historical identifiers, unchanged). */
export const PATH_CHAPTERS = { "rate-flag": "week-12", prologue: "week-01" };
/** The prologue's narrated day (owner, review 13 §5: 5 September is the narrated event date). */
export const PROLOGUE_NARRATED = "2026-09-05";

// ── the date-first chapter index (owner, review 11 §Reader journey; labels approved as supplied, review 14) ───────────

const listWords = (xs) => (xs.length <= 1 ? xs.join("") : `${xs.slice(0, -1).join(", ")} and ${xs[xs.length - 1]}`);

/** A gap's sentence from the program weeks inside it: skipped → "had no chapter written", retired → "were retired", held →
 *  "is held"; a pending week has no draft and is not named. Never a reason. */
export function gapSentence(weeks, trailing) {
  const range = (w) => dashRange(w.week_start, w.week_end);
  const by = (st) => weeks.filter((w) => w.status === st).map(range).filter(Boolean);
  const skipped = by("skipped");
  const retired = by("retired");
  const held = by("held");
  const clauses = [];
  if (skipped.length) clauses.push(`the ${skipped.length === 1 ? "week" : "weeks"} of ${listWords(skipped)} had no chapter written`);
  if (retired.length) clauses.push(retired.length === 1 ? `a draft for ${retired[0]} was retired` : `drafts for ${listWords(retired)} were retired`);
  if (held.length) clauses.push(held.length === 1 ? `a draft for ${held[0]} is held` : `drafts for ${listWords(held)} are held`);
  const head = trailing ? "No published chapter covers these days yet." : "No published chapter covers these days.";
  if (!clauses.length) return head;
  const tail = clauses.join("; ");
  return `${head} ${tail[0].toUpperCase()}${tail.slice(1)}.`;
}

/**
 * The index rows, oldest first: the prologue, each published chapter (number, days, title) and a gap row for every run of
 * days no published chapter covers, the last one up to the build's day. `chapters` have their covered days applied
 * (snapshot.js loadAll) and their date-first number (`chapter_no`, format.js applyChapterNumbers).
 */
export function chapterIndex({ chapters, startDate, asOf, prologueFirstPublished }) {
  const pub = (chapters || []).filter((c) => c && c.status === "published");
  const rows = [];
  const prologue = pub.find((c) => c.week === 0);
  if (prologue) {
    rows.push({
      kind: "chapter",
      chapter: prologue,
      d: dayInWords(PROLOGUE_NARRATED, { weekday: true }),
      s: `Prologue · the night before day 1${prologueFirstPublished ? ` · first published ${dayInWords(prologueFirstPublished)}` : ""}`,
    });
  }
  const numbered = pub.filter((c) => Number.isInteger(c.week) && c.week >= 1 && ISO.test(c.covers_start || "") && ISO.test(c.covers_end || "")).sort((a, b) => (a.covers_start < b.covers_start ? -1 : 1));
  const others = (chapters || []).filter((c) => c && c.status !== "published" && ISO.test(c.week_start || "") && ISO.test(c.week_end || ""));
  const gap = (from, to, trailing) => {
    if (!from || !to || from > to) return null;
    const inside = others.filter((w) => w.week_start <= to && w.week_end >= from && (!trailing || w.week_start <= to)).sort((a, b) => (a.week_start < b.week_start ? -1 : 1));
    // a trailing gap names only the weeks whose days have all passed by the build's day
    const named = trailing ? inside.filter((w) => w.week_end <= to) : inside;
    return {
      kind: "gap",
      d: `${dashRange(from, to)}${trailing ? " (to the build date)" : ""}`,
      s: `days ${dayNo(from, startDate)}–${dayNo(to, startDate)}`,
      t: gapSentence(named, trailing),
    };
  };
  let cursor = startDate;
  for (const c of numbered) {
    if (cursor && cursor < c.covers_start) {
      const g = gap(cursor, isoOf(ms(c.covers_start) - 864e5), false);
      if (g) rows.push(g);
    }
    rows.push({ kind: "chapter", chapter: c, d: dashRange(c.covers_start, c.covers_end), s: `Chapter ${c.chapter_no ?? c.week} · days ${dayNo(c.covers_start, startDate)}–${dayNo(c.covers_end, startDate)}` });
    cursor = isoOf(ms(c.covers_end) + 864e5);
  }
  if (cursor && ISO.test(asOf || "") && cursor <= asOf) rows.push(gap(cursor, asOf, true));
  return rows.filter(Boolean);
}

// ── the coaches' introduction (owner, review 12 §Coaches; approved as supplied, review 14) ───────────────────────────

const ASK_ORDER = ["kept", "broken", "pending", "unresolved", "ungradeable"];
/** "21 held, 1 kept, 20 unresolved" — the producer's ask tally as served (a zero bucket left out), or null. */
export function askTally(counts) {
  if (!counts || !Number.isInteger(counts.held)) return null;
  return [`${counts.held} held`, ...ASK_ORDER.filter((k) => Number.isInteger(counts[k]) && counts[k] > 0).map((k) => `${counts[k]} ${k}`)].join(", ");
}

/** One coach's checked record beside the guess, as served (calibration.js coachLead): "14 right of 28 checked forecasts;
 *  a guess that nothing changes, 15" — or with `short`, "…; the guess, 8; too few to tell". */
export function coachRecordWords(lead, { short = false } = {}) {
  if (!lead || !lead.baseline) return null;
  return short
    ? `${lead.k} right of ${lead.n} checked forecasts; the guess, ${lead.baseline.right}${lead.sign?.verdict === "too_few" ? "; too few to tell" : ""}`
    : `${lead.k} right of ${lead.n} checked forecasts; a guess that nothing changes, ${lead.baseline.right}`;
}

/** A kind's line from the coach's served comparison (versus_guess.kinds): "0 of 5 (guess 5 of 5, too few to tell)". */
export function kindWords(kinds, kind, verdictWords, { guessOf = true } = {}) {
  const k = (kinds || []).find((x) => x && x.kind === kind);
  if (!k || !Number.isInteger(k.scored)) return null;
  return `${k.coach_right} of ${k.scored} (guess ${k.rule_right}${guessOf ? ` of ${k.scored}` : ""}, ${verdictWords(k.verdict)})`;
}

/** "0 of 4": the protein floor over the edition's last seven days (week.measures.food.data.met), as the homepage reads it. */
export function floorDays(food) {
  const met = food && food.state === "ok" && Array.isArray(food.data?.met) ? food.data.met : null;
  if (!met) return null;
  const logged = met.filter((x) => x === true || x === false);
  return logged.length ? { met: logged.filter(Boolean).length, logged: logged.length } : null;
}
