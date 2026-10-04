// ck_built.js — the live numbers on "How it's built" (#4586, epic #4580), in the kit and
// nothing else.
//
// The page's prose, picture and incident list are static HTML. The numbers are not: each
// one is read from a public route when the page loads, and printed with the day it was
// served or computed, so a figure cannot go stale on the page while the system moves on.
//   /api/platform_stats  programs and data sources (repo-derived, stamped at build)
//   /api/receipts        month-to-date spend, the ceiling, the tier, both forecasts
//   /api/predictions     the coaches' checked calls, and the "nothing changes" comparison
//   /api/coaches         how many coaches there are
// A route that does not answer is said as an absence. No figure is ever invented or
// carried over from an earlier load.
//
// ONE number here is not served by any public route: how many programs run on a timer.
// It is a dated constant (SCHEDULED). The cost governor's rules (GOVERNOR) are restated here
// so the page can say why the tier is what it is. tests/test_built_page_facts_4586.py pins
// both to their sources, so the build goes red when the system moves and the page has not.
//
// The builders are pure and exported for tests/js/ck_built_4586.test.mjs; mount() is the
// only thing that touches the DOM.
import { tryJSON, esc } from "/assets/js/evidence_shared.js";
import { dayInWords, instantDayInWords } from "/assets/js/entry_age.js";
import { coachComparison } from "/assets/js/coach_comparison.js";

/** Programs that run on a timer. Source: model/platform_model.json meta.counts.scheduled_lambdas. */
export const SCHEDULED = { count: 82, asOf: "2026-10-04" };

/** The cost governor's rules, restated: each tier's threshold as a share of the ceiling, and
 *  the opening days of a month in which only money actually spent can raise the tier.
 *  Source: lambdas/operational/cost_governor_lambda.py (_TIER_THRESHOLDS over
 *  _THRESHOLD_REFERENCE_CEILING, EARLY_MONTH_DAYS, the trailing window in the handler). */
export const GOVERNOR = { shares: [55 / 75, 65 / 75, 73 / 75], earlyDays: 5, windowDays: 7 };

const num = (v) => (typeof v === "number" && Number.isFinite(v) ? v : null);
const whole = (v) => Math.round(v).toLocaleString("en-US");
const usd = (v) => `$${v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const usd0 = (v) => `$${whole(v)}`;
const day = (iso) => dayInWords(iso, { weekday: false });
const instant = (ts) => instantDayInWords(ts, { weekday: false });
const absent = (what) => `<p class="ck-soft">${esc(what)} not available right now.</p>`;
const para = (text, cls = "") => `<p${cls ? ` class="${cls}"` : ""}>${esc(text)}</p>`;

// One number and its sentence, with the day it is true for underneath.
function numberHTML(figure, sentence, dated, extra = "") {
  const when = dated ? `<p class="ck-small">${esc(dated)}</p>` : "";
  return `<div class="ck-today ck-today--ruled"><div class="ck-num"><b>${esc(figure)}</b><span class="ck-soft">${esc(sentence)}</span></div>${extra}${when}</div>`;
}

/** Programs on a timer, the ones that run when called, what they read, and the coaches.
 *  The total is never printed as a figure: it sits one block above "N of M checked calls"
 *  and the two were read as one number. */
export function programsHTML(stats, coaches) {
  const n = num(stats && stats.lambdas);
  if (n === null) return absent("The count of programs is");
  const onCall = n > SCHEDULED.count ? ` Another ${whole(n - SCHEDULED.count)} run when called.` : "";
  const sources = num(stats.data_sources);
  const read = sources === null ? "" : ` They read ${whole(sources)} sources of data: devices, apps and lab results.`;
  const roster = coaches && Array.isArray(coaches.coaches) ? coaches.coaches.length : 0;
  const cast = roster ? ` ${whole(roster)} AI coaches write and predict.` : "";
  return numberHTML(whole(SCHEDULED.count), `programs run on a timer.${onCall}${read}${cast}`, `As of ${day(SCHEDULED.asOf)}.`);
}

/** The coaches' record, never alone: the comparison sits directly under it. */
export function recordHTML(predictions) {
  const o = predictions && predictions.overall;
  const right = num(o && o.confirmed);
  const wrong = num(o && o.refuted);
  if (right === null || wrong === null || !(right + wrong)) return absent("The coaches’ record is");
  const cmp = coachComparison(predictions.comparison, { cls: "ck-soft", src: "api_predictions.comparison.sentence" });
  const when = day(o.due && o.due.as_of) || instant(predictions._meta && predictions._meta.served_at);
  const dated = `${when ? `As of ${when}. ` : ""}Code does the grading, not a person and not an AI.`;
  return numberHTML(`${whole(right)} right, ${whole(wrong)} wrong`, "is the AI coaches’ record on the predictions that have come due.", dated, cmp);
}

/** The numbers section: two blocks, each figure dated. Spend has its own section. */
export function numbersHTML(src) {
  return [programsHTML(src.stats, src.coaches), recordHTML(src.predictions)].join("");
}

// The largest single day in the month so far, from the running total.
function biggestDay(history) {
  let best = null;
  let prev = 0;
  for (const row of Array.isArray(history) ? history : []) {
    const total = num(row && row.mtd_usd);
    if (total === null) continue;
    if (best === null || total - prev > best.usd) best = { date: row.date, usd: total - prev };
    prev = total;
  }
  return best;
}

/** The cost section's paragraphs: the ceiling, what is spent, the daily rate and its window,
 *  both forecasts, and why the tier is what it is and what raises it next. Every figure is
 *  as the route gave it; the thresholds are the ceiling times the governor's shares. */
export function costHTML(receipts) {
  const base = num(receipts && receipts.base_ceiling_usd);
  const ceiling = num(receipts && receipts.ceiling_usd);
  const mtd = num(receipts && receipts.month_to_date_usd);
  if (base === null || ceiling === null || mtd === null) return para("The ceiling and this month’s spend are not available right now.", "ck-soft");
  const surge = num(receipts.surge_ceiling_usd);
  const lift = surge !== null && surge > base ? ` It rises to ${usd0(surge)} when reader traffic is high.` : "";
  const out = [];
  const top = `The ceiling is ${usd0(base)} a month for the whole cloud bill, AI included.${lift}`;

  const stamp = receipts.computed_at || receipts.as_of;
  const when = instant(stamp);
  const tier = num(receipts.tier);
  const paused = tier === 0 ? "Nothing is paused." : tier === null ? "" : `The system is at tier ${tier}.`;
  out.push(para(`${top} ${when ? `As of ${when}, ` : ""}${usd(mtd)} is spent this month.${receipts.stale ? " This figure is out of date." : ""} ${paused}`.trim()));

  // The daily rate: a recent-days rate, never the month's average.
  const ai = num(receipts.ai_daily_usd);
  const t = Date.parse(String(stamp || ""));
  const elapsed = Number.isFinite(t) ? (t - Date.UTC(new Date(t).getUTCFullYear(), new Date(t).getUTCMonth(), 1)) / 86400000 : null;
  if (ai !== null) {
    const rest = num(receipts.non_ai_daily_usd);
    const window = elapsed !== null && elapsed < GOVERNOR.windowDays ? "the days of this month so far" : `the last ${GOVERNOR.windowDays} days`;
    const big = biggestDay(receipts.history);
    const lumpy = big && big.usd > ai && day(big.date) ? ` One day, ${day(big.date)}, was ${usd(big.usd)} of the total.` : "";
    const other = rest === null ? "" : ` Everything that is not AI costs ${usd(rest)} a day and never pauses.`;
    out.push(para(`AI cost ${usd(ai)} a day over ${window}. That is a recent rate, not a monthly average.${lumpy}${other}`));
  }

  // Both forecasts, and what they say against the ceiling.
  const forecast = num(receipts.projected_month_end_usd);
  const all = num(receipts.projected_all_classes_usd);
  if (forecast !== null) {
    const side = (v) => (v > ceiling ? "above the ceiling" : "under the ceiling");
    const wide = all === null ? "" : ` Counting everything, including AI used to test and build the system, it is ${usd(all)}, ${side(all)}.`;
    out.push(para(`The forecast for month end, counting the scheduled programs only, is ${usd(forecast)}, ${side(forecast)}.${wide}`));
    const [t1, t2] = GOVERNOR.shares.map((share) => ceiling * share);
    const early = elapsed !== null && elapsed < GOVERNOR.earlyDays;
    if (tier === 0 && forecast >= t1) {
      const why = early ? `Nothing is paused yet because in the first ${GOVERNOR.earlyDays} days of a month only money actually spent can raise the tier, and ${usd(mtd)} is under the first step of ${usd(t1)}. ` : "";
      out.push(para(`${why}After day ${GOVERNOR.earlyDays} a forecast this high starts tier 1. Tier 2 needs ${usd(t1)} actually spent, and tier 3 needs ${usd(t2)}.`));
    }
    if ((all !== null && all > ceiling) || forecast > ceiling) {
      out.push(para("On these figures the bill passes the ceiling unless the pauses start or the pace drops. This month has not yet shown which."));
    }
  }
  return out.join("");
}

// ── mount ──────────────────────────────────────────────────────────────────────
const fill = (id, html) => {
  const el = document.getElementById(id);
  if (el) el.innerHTML = html;
};

export async function mount() {
  if (!document.body || document.body.dataset.ckPage !== "built") return;
  const [stats, receipts, predictions, coaches] = await Promise.all(["/api/platform_stats", "/api/receipts", "/api/predictions", "/api/coaches"].map(tryJSON));
  fill("ck-numbers", numbersHTML({ stats, receipts, predictions, coaches }));
  fill("ck-cost", costHTML(receipts));
  document.body.dataset.ckReady = "1";
}

if (typeof document !== "undefined") mount();
