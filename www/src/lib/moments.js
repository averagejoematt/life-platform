// The moments that explain it (2026-11-14, sprint III): a short, curated entry for a stranger — the few documented
// events that best explain the experiment so far, each tied to its evidence. Curated by RULE, not by hand-written
// drama: every moment is selected from published objects and says only what they say. A chapter's own words are its
// approved dek, quoted, never paraphrased; a number is the platform's. A moment whose evidence is absent from the
// snapshot is simply not shown — the list shrinks, it is never filled.
import { dayInWords, num } from "./format.js";

const published = (chapters) => (chapters || []).filter((c) => c && c.status === "published" && (c.week ?? 0) >= 1);
const lastDay = (c) => c.covers_end || c.data_through || c.date;

/** The first published chapter whose title matches `re` (the flag chapter, the coach's blind spot …). */
function chapterBy(chapters, re) {
  return published(chapters)
    .filter((c) => re.test(c.title || ""))
    .sort((a, b) => (a.week ?? 0) - (b.week ?? 0))[0];
}

/**
 * The moments, oldest first. Inputs are snapshot objects: `journey` (start, rungs), `chapters`, `lead` (the verified
 * record against a guess, lib/calibration.js verifiedLead), `finding` (the correlation listed in every weekly run, with
 * its `seen`/`of`). Each moment: {key, date|null, kicker, title, body, quote|null, links: [{label, path}]}.
 */
export function moments({ journey, chapters, coaches, lead, finding, dayPath, chapterPath, coachPath }) {
  const out = [];
  if (journey && journey.start_date && journey.start_weight_lbs != null) {
    const prologue = (chapters || []).find((c) => c.status === "published" && c.week === 0);
    out.push({
      key: "start",
      date: journey.start_date,
      kicker: "Day 1",
      title: "The first morning on the scale",
      body: `${num(journey.start_weight_lbs, 1)} pounds on ${dayInWords(journey.start_date)}. Every weigh-in since is on the line above; the goal is ${num(journey.goal_weight_lbs, 0)}.`,
      quote: null,
      links: [
        { label: "The journey, every reading", path: "/data/journey/" },
        dayPath(journey.start_date) && { label: "That day", path: dayPath(journey.start_date) },
        prologue && { label: `The prologue: ${prologue.title}`, path: chapterPath(prologue) },
      ].filter(Boolean),
    });
  }
  const flag = chapterBy(chapters, /flag/i);
  if (flag) {
    out.push({
      key: "first-flag",
      date: lastDay(flag),
      kicker: flag.week_label,
      title: `The rate flag, ${String(flag.week_label || "").toLowerCase()}`,
      body: "The platform's own rate flag — a heuristic about pace, not a measurement of muscle — in the experiment's second week.",
      quote: { text: flag.excerpt || flag.summary, cite: flag.title },
      links: [{ label: `Read ${flag.title}`, path: chapterPath(flag) }],
    });
  }
  const blind = chapterBy(chapters, /blind spot/i);
  // the coach the chapter is named for: a coach whose surname is in the title (no match → no coach link)
  const coach = blind ? (coaches || []).find((c) => c && c.name && new RegExp(`\\b${c.name.split(" ").slice(-1)[0]}\\b`).test(blind.title)) || null : null;
  if (blind) {
    out.push({
      key: "blind-spot",
      date: lastDay(blind),
      kicker: blind.week_label,
      title: blind.title,
      body: "The chapter is named for a coach's miss; its record, every call checked against a simple guess, is one click away.",
      quote: { text: blind.excerpt || blind.summary, cite: blind.title },
      links: [{ label: `Read ${blind.title}`, path: chapterPath(blind) }, coach && { label: `${coach.name}'s record`, path: coachPath(coach.id) }].filter(Boolean),
    });
  }
  const r300 = (journey?.rungs || []).find((r) => r.lb === 300 && r.date);
  if (r300) {
    const prev = (journey.rungs || []).find((r) => r.lb === 310 && r.date);
    // the program week the crossing fell in, by its served interval — never assumed
    const weekOf = (chapters || []).find((c) => (c.week ?? 0) >= 1 && c.week_start && c.week_end && c.week_start <= r300.date && r300.date <= c.week_end) || null;
    out.push({
      key: "under-300",
      date: r300.date,
      kicker: `Day ${Math.round((Date.parse(`${r300.date}T00:00:00Z`) - Date.parse(`${journey.start_date}T00:00:00Z`)) / 864e5) + 1}`,
      title: "Under 300 pounds",
      body: `The scale first read under 300 on ${dayInWords(r300.date)}${prev ? `, ${r300.days} days after it first read under 310` : ""}.${weekOf && weekOf.status !== "published" ? " No chapter was published for that week; the readings were kept all the same." : ""}`,
      quote: null,
      links: [
        dayPath(r300.date) && { label: "That morning", path: dayPath(r300.date) },
        weekOf && weekOf.status === "published" && { label: `Read ${weekOf.title}`, path: chapterPath(weekOf) },
        { label: "The milestones", path: "/data/journey/" },
      ].filter(Boolean),
    });
  }
  const again = published(chapters)
    .filter((c) => /rate flag/i.test(c.title || "") && c !== flag)
    .sort((a, b) => (b.week ?? 0) - (a.week ?? 0))[0];
  if (again) {
    out.push({
      key: "rate-flag",
      date: lastDay(again),
      kicker: again.week_label,
      title: "The pace question, again",
      body: `${flag && again.week > flag.week ? `${again.week - flag.week} weeks after ${flag.title}, the` : "The"} flag fired again. Whether the pace can hold without costing muscle is the chapter's own open question.`,
      quote: { text: again.excerpt || again.summary, cite: again.title },
      links: [{ label: `Read ${again.title}`, path: chapterPath(again) }],
    });
  }
  if (lead && lead.baseline && lead.n) {
    out.push({
      key: "versus-guess",
      date: null,
      kicker: "So far",
      title: "The AI coaches against a simple guess",
      body: `On the ${lead.n} forecasts that could be checked fairly, the coaches were right ${lead.k} times and a guess that nothing changes ${lead.baseline.right} times${lead.sign?.words ? ` — ${lead.sign.words}` : ""}. Every call, right or wrong, is on the record.`,
      quote: null,
      links: [
        { label: "How the coaches are graded", path: "/system/" },
        { label: "Every call", path: "/system/ledger/" },
      ],
    });
  }
  if (finding) {
    out.push({
      key: "held-every-week",
      date: null,
      kicker: "The Laboratory",
      title: "A relationship that held every week",
      body: `${finding.title}: listed in ${finding.seen} of ${finding.of} weekly runs (r ${finding.r}). A correlation, not a cause — the pre-registered tests that could say more are still collecting days.`,
      quote: null,
      links: [{ label: "The Laboratory", path: "/data/lab/" }],
    });
  }
  return out;
}

/** The correlation listed in every weekly run, strongest first — null when none held every week. */
export function heldEveryWeek(items, titleOf) {
  const all = (items || []).filter((f) => f && f.seen != null && f.of != null && f.seen === f.of && f.of >= 3 && f.r != null);
  all.sort((a, b) => Math.abs(b.r) - Math.abs(a.r));
  const f = all[0];
  if (!f) return null;
  return { title: titleOf(f), seen: f.seen, of: f.of, r: `${f.r >= 0 ? "+" : "−"}${Math.abs(f.r).toFixed(2)}` };
}
