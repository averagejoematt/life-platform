// ck_built.js — the live numbers on "How it's built" (#4586, epic #4580), in the kit and
// nothing else.
//
// The page's prose, picture and incident list are static HTML. The numbers are not: each
// one is read from a public route when the page loads, and printed with the day it was
// served or computed, so a figure cannot go stale on the page while the system moves on.
//   /api/platform_stats  programs and data sources (repo-derived, stamped at build)
//   /api/receipts        month-to-date spend, the ceiling, the tier, an ordinary day, the
//                        month's high days, both forecasts
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
export const SCHEDULED = { count: 83, asOf: "2026-10-04" };

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

/** Every /api/receipts field the cost section prints or decides on, by sentence. The
 *  section computes nothing a reader sees: each figure is printed as the route gave it.
 *  A sentence whose fields are not all there is left out whole, never printed with a
 *  stand-in. tests/js/ck_built_4586.test.mjs removes each field in turn and checks the
 *  sentence goes; tests/test_built_page_facts_4586.py checks the route still serves them. */
export const COST_FIELDS = {
  spent: ["base_ceiling_usd", "ceiling_usd", "month_to_date_usd"],
  ordinary: ["typical_day.usd", "typical_day.days_counted", "typical_day.window_end", "typical_day.month_days", "typical_day.month_usd"],
  high: ["high_days.multiple", "high_days.days", "high_days.total_usd", "high_days.above_typical_usd"],
  share: ["ai_scheduled_share_pct"],
  forecast: ["projected_month_end_usd"],
  wide: ["projected_all_classes_usd"],
};

const iso = (v) => (typeof v === "string" && /^\d{4}-\d{2}-\d{2}/.test(v) ? Date.parse(v.slice(0, 10)) : NaN);
const list = (items) => (items.length < 2 ? items.join("") : `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`);
// "October 1, 2 and 3" when every day is in one month; each day in full otherwise.
function dayList(days) {
  const parts = days.map((d) => d.split(" "));
  const oneMonth = parts.every((p) => p.length === 2 && p[0] === parts[0][0]);
  return oneMonth ? `${parts[0][0]} ${list(parts.map((p) => p[1]))}` : list(days);
}

// What an ordinary day costs, its window, and a month of such days — or null.
function ordinary(receipts) {
  const t = receipts.typical_day;
  if (!t || typeof t !== "object") return null;
  const [usdDay, days, monthDays, month] = [num(t.usd), num(t.days_counted), num(t.month_days), num(t.month_usd)];
  const to = day(t.window_end);
  if (usdDay === null || days === null || monthDays === null || month === null || !to) return null;
  return { usd: usdDay, days, monthDays, month, to };
}

// This month's days that ran well above an ordinary one, dated — or null (none is null too).
function highDays(receipts) {
  const h = receipts.high_days;
  if (!h || typeof h !== "object" || !Array.isArray(h.days) || !h.days.length) return null;
  const [multiple, total, above] = [num(h.multiple), num(h.total_usd), num(h.above_typical_usd)];
  const dates = h.days.map((d) => day(d && d.date));
  if (multiple === null || total === null || above === null || dates.some((d) => !d)) return null;
  return { multiple, total, above, dates, first: Math.min(...h.days.map((d) => iso(d.date))) };
}

/** The cost section's paragraphs: the ceiling and what is spent; what an ordinary day
 *  costs and a month of them; this month's high days, dated; the two forecasts and what
 *  each assumes; and why the tier is what it is and what raises it next. Every figure is
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
  const side = (v) => (v > ceiling ? "above the ceiling" : "under the ceiling");

  const stamp = receipts.computed_at || receipts.as_of;
  const when = instant(stamp);
  const tier = num(receipts.tier);
  const paused = tier === 0 ? "Nothing is paused." : tier === null ? "" : `The system is at tier ${tier}.`;
  out.push(para(`${top} ${when ? `As of ${when}, ` : ""}${usd(mtd)} is spent this month.${receipts.stale ? " This figure is out of date." : ""} ${paused}`.trim()));

  // The forecasts run on a recent-days rate: the last week, or the month so far if shorter.
  const t = Date.parse(String(stamp || ""));
  const elapsed = Number.isFinite(t) ? (t - Date.UTC(new Date(t).getUTCFullYear(), new Date(t).getUTCMonth(), 1)) / 86400000 : null;
  const recent = elapsed !== null && elapsed < GOVERNOR.windowDays;
  const window = recent ? "this month so far" : `over the last ${GOVERNOR.windowDays} days`;

  // An ordinary day, and a month of them. Then the days that were not ordinary, dated.
  const usual = ordinary(receipts);
  const high = usual && highDays(receipts);
  if (usual) {
    out.push(
      para(
        `An ordinary day costs ${usd(usual.usd)}, AI included: the middle day of the ${whole(usual.days)} days to ${usual.to}. ${whole(usual.monthDays)} days like it come to ${usd(usual.month)}, ${side(usual.month)}.`,
      ),
    );
  }
  if (high) {
    const times = high.multiple === 2 ? "twice" : `${whole(high.multiple)} times`;
    const n = high.dates.length;
    const days = n === 1 ? `One day this month cost more than ${times} that: ${high.dates[0]}, at ${usd(high.total)}` : `${whole(n)} days this month each cost more than ${times} that: ${dayList(high.dates)}, ${usd(high.total)} together`;
    const over = high.above > 0 ? `, ${usd(high.above)} more than ${n === 1 ? "an ordinary day" : `${whole(n)} ordinary days`}.` : ".";
    // What the AI spend was, said only when the rate's window covers every high day.
    const share = num(receipts.ai_scheduled_share_pct);
    const covered = Number.isFinite(t) && Number.isFinite(high.first) && (recent || high.first >= t - GOVERNOR.windowDays * 86400000);
    const what = share !== null && covered ? ` Of the AI spend ${window}, ${whole(share)}% ran on a schedule. The rest was building and testing the system.` : "";
    out.push(para(`${days}${over}${what}`));
  }

  // Both forecasts, what each one assumes, and what they say against the ceiling.
  const forecast = num(receipts.projected_month_end_usd);
  const all = num(receipts.projected_all_classes_usd);
  if (forecast !== null) {
    const by = day(receipts.month_end_date);
    const banked = high && forecast > ceiling && usual.month <= ceiling && forecast - high.above <= ceiling ? " because of the high days already spent" : "";
    const wide = all === null || all <= forecast ? "" : ` If building and testing also carried on at that pace every day, it would be ${usd(all)}.`;
    out.push(
      para(
        `The forecast that sets the tier is what is spent plus the scheduled programs at their pace ${window}: ${usd(forecast)} by ${by || "month end"}, ${side(forecast)}${banked}.${wide}`,
      ),
    );
    const [t1, t2] = GOVERNOR.shares.map((share) => ceiling * share);
    const early = elapsed !== null && elapsed < GOVERNOR.earlyDays;
    if (tier === 0 && forecast >= t1) {
      const why = early ? `Nothing is paused yet because in the first ${GOVERNOR.earlyDays} days of a month only money actually spent can raise the tier, and ${usd(mtd)} is under the first step of ${usd(t1)}. ` : "";
      out.push(para(`${why}After day ${GOVERNOR.earlyDays} a forecast this high starts tier 1. A forecast lifts the tier one step at most, so tier 2 waits for ${usd(t1)} actually spent and tier 3 for ${usd(t2)}.`));
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
