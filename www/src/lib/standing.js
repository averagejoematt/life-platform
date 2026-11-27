// Where the experiment stands — the four parts, from served figures (owner rulings 2026-11-15/16 on #6067: "Continue
// connecting Body, Behaviour, Life and AI throughout the site"). One producer of the four figures for every page that
// shows them: the front page's block and the strip the Story, Data and System doors carry (components/FourParts.astro).
// Nothing here is a judgement: the body is the weight series' own change, the behaviour is the Laboratory's
// pre-registered tests and how many have a verdict, the life is how many of the six dimensions have a public measure,
// and the AI is the checked record beside a simple guess on the same calls, under the producer's own verdict. A part
// whose figure is not served carries value null and says so.
import { headline } from "./chart.js";
import { lineCounts } from "./theline.js";
import { num } from "./format.js";

/** The three dimensions a public series can measure (the other three — mind, connection, purpose — have none). */
export const MEASURABLE = ["weight_lbs", "sleep_duration_hours", "hrv"];
export const DIMENSIONS = 6;

/** This page's short label for the producer's verdict on coaches against a simple guess. */
export const AI_STATUS = {
  no_clear_difference: "no advantage shown",
  too_few: "too few calls to tell",
  rule_better: "behind a simple guess",
  coaches_better: "ahead of a simple guess",
};

/** The weight series since the start: {lost, days, readings} — lost < 0 is lighter. Null when no reading is served. */
export function bodyChange(weightSeries, startDate, startValue) {
  const days = weightSeries ? weightSeries.days.filter((d) => !startDate || d.date >= startDate) : [];
  const readings = days.filter((d) => d.value != null && !d.gap);
  if (!readings.length) return null;
  const c = lineCounts(days);
  return { lost: readings[readings.length - 1].value - (startValue ?? readings[0].value), days: c.days, readings: c.readings };
}

/** {open, decided} over the Laboratory's tests that are not archived; null when the Laboratory is not served. */
export function labVerdicts(lab) {
  if (!lab || lab.state !== "ok") return null;
  const ts = (lab.lab_tests || []).filter((t) => t.status !== "archived");
  const verdictOf = (t) => (t.verdict && typeof t.verdict === "object" ? t.verdict.result : t.verdict);
  return { open: ts.length, decided: ts.filter((t) => verdictOf(t) && verdictOf(t) !== "inconclusive").length };
}

/** How many of the measurable dimensions have a latest reading in the served series. */
export function measuredDimensions(series) {
  return MEASURABLE.filter((k) => series && series[k] && headline(series[k].days).last != null).length;
}

/**
 * The four parts: [{id, part, status, value|null, short}] — `value` opens the part's sentence on the front page and
 * stands alone in the strip; `short` is the strip's few words after it. `lead` is lib/calibration.js verifiedLead.
 */
export function fourParts({ body, lab, measured, lead }) {
  const lighter = body ? body.lost < 0 : false;
  const verdict = lead?.sign?.verdict;
  return [
    { id: "body", part: "The body", status: "measured", value: body ? `${num(Math.abs(body.lost), 1)} lb` : null, short: body ? (lighter ? "lighter" : "heavier") : "not served" },
    { id: "behaviour", part: "The behaviour", status: "being tested", value: lab ? `${lab.decided} of ${lab.open}` : null, short: lab ? "tests with a verdict" : "not served" },
    // owner, 2026-11-27: coverage, not a verdict — an uninstrumented dimension is "not measured", never "not established"
    { id: "life", part: "The life", status: "measured in part", value: `${measured} of ${DIMENSIONS}`, short: "dimensions have a public measure" },
    {
      id: "ai",
      part: "The AI",
      status: (verdict && AI_STATUS[verdict]) || "being checked",
      value: lead?.baseline ? `${lead.k} v ${lead.baseline.right}` : null,
      short: lead?.baseline ? `coaches v a guess, of ${lead.n}` : "not served",
    },
  ];
}
