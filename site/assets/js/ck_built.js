// ck_built.js — the live numbers on "How it's built" (#4586, epic #4580), in the kit and
// nothing else.
//
// The page's prose, picture and incident list are static HTML. The numbers are not: each
// one is read from a public route when the page loads, and printed with the day it was
// served or computed, so a figure cannot go stale on the page while the system moves on.
//   /api/platform_stats  programs and data sources (repo-derived, stamped at build)
//   /api/receipts        month-to-date spend, the ceiling, the tier, the forecast
//   /api/predictions     the coaches' checked calls, and the "nothing changes" comparison
//   /api/coaches         how many coaches there are
// A route that does not answer is said as an absence. No figure is ever invented or
// carried over from an earlier load.
//
// ONE number here is not served by any public route: how many programs run on a timer.
// It is a dated constant (SCHEDULED) and tests/test_built_page_facts_4586.py pins it to
// model/platform_model.json, so the build goes red when the model moves and the page has
// not.
//
// The builders are pure and exported for tests/js/ck_built_4586.test.mjs; mount() is the
// only thing that touches the DOM.
import { tryJSON, esc } from "/assets/js/evidence_shared.js";
import { dayInWords, instantDayInWords } from "/assets/js/entry_age.js";
import { coachComparison } from "/assets/js/coach_comparison.js";

/** Programs that run on a timer. Source: model/platform_model.json meta.counts.scheduled_lambdas. */
export const SCHEDULED = { count: 82, asOf: "2026-10-04" };

const num = (v) => (typeof v === "number" && Number.isFinite(v) ? v : null);
const whole = (v) => Math.round(v).toLocaleString("en-US");
const usd = (v) => `$${v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const usd0 = (v) => `$${whole(v)}`;
const day = (iso) => dayInWords(iso, { weekday: false });
const instant = (ts) => instantDayInWords(ts, { weekday: false });
const absent = (what) => `<p class="ck-soft">${esc(what)} not served right now.</p>`;

// One number and its sentence, with the day it is true for underneath.
function numberHTML(figure, sentence, dated, extra = "") {
  const when = dated ? `<p class="ck-small">${esc(dated)}</p>` : "";
  return `<div class="ck-today ck-today--ruled"><div class="ck-num"><b>${esc(figure)}</b><span class="ck-soft">${esc(sentence)}</span></div>${extra}${when}</div>`;
}

/** Programs, how many of them run on a timer, and what they read; the coaches are counted beside them. */
export function programsHTML(stats, coaches) {
  const n = num(stats && stats.lambdas);
  if (n === null) return absent("The count of programs is");
  const sources = num(stats.data_sources);
  const read = sources === null ? "" : ` They read ${whole(sources)} data sources: devices, apps and lab results.`;
  const roster = coaches && Array.isArray(coaches.coaches) ? coaches.coaches.length : 0;
  const cast = roster ? ` ${whole(roster)} AI coaches write and predict.` : "";
  const served = instant(stats._meta && stats._meta.served_at);
  const dated = `${served ? `Counts served ${served}. ` : ""}Timer count as of ${day(SCHEDULED.asOf)}.`;
  return numberHTML(whole(n), `programs run the system. ${whole(SCHEDULED.count)} of them run on a timer.${read}${cast}`, dated);
}

/** Month-to-date spend against the ceiling in force, with the per-day rate beside it. */
export function spendHTML(receipts) {
  const mtd = num(receipts && receipts.month_to_date_usd);
  const ceiling = num(receipts && receipts.ceiling_usd);
  if (mtd === null || ceiling === null) return absent("This month’s spend is");
  const ai = num(receipts.ai_daily_usd);
  const rest = num(receipts.non_ai_daily_usd);
  const perDay = ai === null ? "" : ` Over recent days AI has cost ${usd(ai)} a day${rest === null ? "" : ` and everything else ${usd(rest)}`}.`;
  const when = instant(receipts.computed_at || receipts.as_of);
  const stale = receipts.stale ? " This figure is out of date." : "";
  return numberHTML(usd(mtd), `spent so far this month, against a ceiling of ${usd0(ceiling)}. It is the whole cloud bill, AI included.${perDay}`, `${when ? `As of ${when}.` : ""}${stale}`);
}

/** The coaches' record, never alone: the served comparison sits directly under it. */
export function recordHTML(predictions) {
  const o = predictions && predictions.overall;
  const right = num(o && o.confirmed);
  const decided = num(o && o.decided);
  if (right === null || !decided) return absent("The coaches’ record is");
  const cmp = coachComparison(predictions.comparison, { cls: "ck-soft", src: "api_predictions.comparison.sentence" });
  const when = day(o.due && o.due.as_of) || instant(predictions._meta && predictions._meta.served_at);
  const dated = `${when ? `As of ${when}. ` : ""}Code grades each call against the data. No person and no AI decides a result.`;
  return numberHTML(`${whole(right)} of ${whole(decided)}`, "checked calls by the AI coaches were right.", dated, cmp);
}

/** The numbers section: three blocks, each figure dated. */
export function numbersHTML(src) {
  return [programsHTML(src.stats, src.coaches), spendHTML(src.receipts), recordHTML(src.predictions)].join("");
}

/** The cost section's live paragraph: the ceiling, today's tier, and the forecast. */
export function costHTML(receipts) {
  const base = num(receipts && receipts.base_ceiling_usd);
  const surge = num(receipts && receipts.surge_ceiling_usd);
  if (base === null) return `<p class="ck-soft">The ceiling and this month’s spend are not served right now.</p>`;
  const lift = surge !== null && surge > base ? ` It rises to ${usd0(surge)} when reader traffic is high.` : "";
  const out = [`<p>The ceiling is ${usd0(base)} a month for the whole cloud bill.${lift}</p>`];
  const tier = num(receipts.tier);
  const when = instant(receipts.computed_at || receipts.as_of);
  if (tier !== null) {
    const words = typeof receipts.tier_semantics === "string" ? ` ${receipts.tier_semantics.trim()}` : "";
    out.push(`<p>${esc(`${when ? `On ${when} the` : "The"} system is at tier ${tier}.${words}`)}</p>`);
  }
  const forecast = num(receipts.projected_month_end_usd);
  const ceiling = num(receipts.ceiling_usd);
  if (forecast !== null && ceiling !== null) {
    const side = forecast > ceiling ? "above the ceiling" : "under the ceiling";
    out.push(`<p class="ck-soft">${esc(`The forecast for month end is ${usd(forecast)}, ${side}.`)}</p>`);
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
