// The Coaching Room's instrument (CR1, built dark — src/lib/room.js): the words and the one chart of
// /system/calibration/ and the room entry on /system/. Pure; proven in tests/calibration.test.mjs.
//
// Requirement A (www/README.md): every number here is CARRIED from the snapshot's calibration.json, which carries
// /api/calibration and /api/predictions as served. Nothing is divided, summed or estimated here: no percentage, no
// interval, no count is derived; a figure the producer did not serve is said to be unpublished, in words.
//
// The headline rule (owner, 2026-11-08): a grade that has not been re-verified under the current rules never enters
// the headline as though validated. The headline reads a verified-only record when the platform serves one
// (`platform.strata.coaches.verified`, the shape below — NOT served yet); until then it says, on the first screen,
// that the record is as first graded and not re-verified, and the career / unverified detail sits in an archive.
//
// Calibration is drawn to the data's resolution: one dot per coach per stated-confidence band as the API served
// the band, sized by n — never a curve — and the verdict is calibration-v2's three answers in the API's own words
// (no threshold is invented here).
import { esc } from "./chart.js";
import { dayInWords, num } from "./format.js";

const isNum = (v) => typeof v === "number" && Number.isFinite(v);

/** "41.2%" from a carried percentage; null when it was not served. */
export function pct(v, decimals = 1) {
  return isNum(v) ? `${num(v, decimals)}%` : null;
}

/** "95% interval 26.4–53.5%" from a carried [lo, hi]; null when not served. */
export function intervalText(ci) {
  if (!Array.isArray(ci) || ci.length !== 2 || !isNum(ci[0]) || !isNum(ci[1])) return null;
  return `95% interval ${num(ci[0], 1)}–${num(ci[1], 1)}%`;
}

/** A carried Brier skill in words; the number is shown, the sign is read, nothing is recomputed. */
export function skillText(v) {
  if (!isNum(v)) return "no skill score yet";
  const s = v.toFixed(3).replace("-", "−");
  return v > 0 ? `${s} — better than its base rate` : `${s} — no better than its base rate`;
}

// ── the calibration verdict: calibration-v2 (owner ruling 2026-11-09) ─────────────────────────────────────────
// Three separate questions, each answered in the producer's own words (`wording`, and `short` for a dense cell) —
// carried, never computed or relabelled here. The v1 fields (`calibration`, `label`, `score`) are deprecated on the
// API and are never read by this module: no v1 label reaches a page.
export const V2_QUESTIONS = [
  { key: "estimability", ask: "Can calibration be estimated across confidence levels?" },
  { key: "confidence_direction", ask: "Over- or under-confident at an observed confidence level?" },
  { key: "skill", ask: "Better than the same-call guess that nothing changes?" },
];

/** A served assessment's three answers: [{key, ask, words, short}], only those served; [] when none was served. */
export function v2Answers(a) {
  if (!a || typeof a !== "object") return [];
  return V2_QUESTIONS.map(({ key, ask }) => {
    const q = a[key];
    if (!q || typeof q !== "object") return null;
    const words = typeof q.wording === "string" && q.wording.trim() ? q.wording : null;
    const short = typeof q.short === "string" && q.short.trim() ? q.short : words;
    return words || short ? { key, ask, words: words || short, short } : null;
  }).filter(Boolean);
}

/** The assessment of a platform stratum ("coaches", "hypotheses", …) as served on `assessment_v2.strata`, or null. */
export function v2Stratum(cal, key) {
  const s = ((cal || {}).assessment_v2 || {}).strata || {};
  return s[key] && typeof s[key] === "object" ? s[key] : null;
}

/** The three short answers in one line, " · "-separated (a dense cell); null when no assessment was served. */
export function v2Short(a) {
  const xs = v2Answers(a);
  return xs.length ? xs.map((x) => x.short).join(" · ") : null;
}

/** "calibration-v2, adopted 9 November 2026" — the method and its version, as served; null when not served. */
export function v2MethodText(cal) {
  const a = (cal || {}).assessment_v2 || {};
  const m = (cal || {}).calibration_method || {};
  const v = a.method_version || m.version;
  if (!v) return null;
  const when = a.adopted || m.adopted;
  return `${v}${when ? `, adopted ${dayInWords(when) || when}` : ""}`;
}

/** The band a stated confidence was served in, in words: 0.5 → "50%". */
export function statedWords(mean) {
  return isNum(mean) ? `${num(mean * 100, 0)}%` : "—";
}

/** "46 of 48 stated at 50%" — the coach's largest served band beside its n (both carried). */
export function concentrationText(c) {
  const bins = (c && c.reliability_bins) || [];
  if (!bins.length || !isNum(c.n)) return "no stated confidence served";
  const top = [...bins].sort((a, b) => b.n - a.n || a.mean_confidence - b.mean_confidence)[0];
  return `${top.n} of ${c.n} stated at ${statedWords(top.mean_confidence)}`;
}

/** The comparison with a guess that nothing changes, per kind of call, as served: "36 v 33 of 118". */
export const KIND_WORDS = { direction: "Direction calls", number: "Number calls", yes_no: "Yes/no bets", sealed: "Sealed day-one calls" };
export function versusGuess(records, kind) {
  const r = records && records[kind];
  if (!r || !isNum(r.scored) || r.scored === 0) return null;
  return { coach: r.coach_right_on_scored, guess: r.rule_right, of: r.scored, verdict: r.verdict, text: `${r.coach_right_on_scored} v ${r.rule_right} of ${r.scored}` };
}
const VERDICT_WORDS = { no_clear_difference: "no clear difference", too_few: "too few to tell", none_scored: "none scored", coach_better: "the coaches did better", rule_better: "the guess did better" };
export function verdictWords(v) {
  return VERDICT_WORDS[v] || (v ? String(v).replace(/_/g, " ") : "");
}

/**
 * The headline: the record a reader meets first. Two modes:
 *   "verified"  — the platform serves a verified-only record (`platform.strata.coaches.verified`:
 *                 {n, confirmed, accuracy_pct, accuracy_ci95, brier_skill, baseline: {text}, skill: {sentence},
 *                 comparison: {records}}); the as-graded record — and its comparison — move to the archive.
 *   "as_graded" — no split is served (today): the record from /api/predictions, labelled as first graded and not
 *                 re-verified, with the interval said to be unpublished unless `strata.coaches.accuracy_ci95` is served.
 * Returns null when the data file is absent.
 */
/**
 * The verified-only record, wherever the platform serves it (the additive /api/calibration fields of the parallel
 * verification work): `platform.strata.coaches.verified` first, else `verification_summary.verified`. Either must
 * carry an integer `n` and an integer `confirmed` (or `right`); anything else is "not served".
 */
export function verifiedRecord(cal) {
  const c = cal || {};
  const stratum = ((c.platform || {}).strata || {}).coaches || {};
  const vs = c.verification_summary || {};
  for (const v of [stratum.verified, vs.verified]) {
    if (!v || typeof v !== "object") continue;
    const n = Number.isInteger(v.n) ? v.n : Number.isInteger(v.decided) ? v.decided : null;
    const k = Number.isInteger(v.confirmed) ? v.confirmed : Number.isInteger(v.right) ? v.right : null;
    if (n !== null && k !== null) return { ...v, n, confirmed: k };
  }
  return null;
}

/**
 * A baseline or comparison is shown beside the verified record ONLY when it is over exactly the same calls (owner,
 * 2026-11-09). It must be served ON the verified object; when it states its own `n` and that differs from the
 * verified n it is refused. The as-graded baseline never stands in.
 */
export function sameCalls(part, n) {
  if (!part || typeof part !== "object") return null;
  if (Number.isInteger(part.n) && part.n !== n) return null;
  return part;
}

/**
 * Why the denominator moved, in words: a change in WHICH calls qualify for evaluation, never an improvement. Both
 * counts are carried; nothing is subtracted here (the accounting by category is the producer's — excludedAccounting).
 */
export function qualifyText(head) {
  if (!head || head.mode !== "verified" || !head.archive) return null;
  return (
    `The headline counts the ${head.n} calls that qualify under the current checks; ${head.archive.n} calls were first graded. ` +
    "The difference is which calls qualify to be evaluated, not a change in how well the coaches called them."
  );
}

/** The publication-method change (the 2026-11-05 eligibility rule), framed the same way: who qualifies, not skill. */
export function methodChangeText(method) {
  const m = method || {};
  if (!Array.isArray(m.history) || m.history.length < 2 || !m.effective) return null;
  const d = dayInWords(m.effective);
  return `Since ${d}, only calls about publishable data qualify to be counted here. That changed which calls are in the denominator, not how well the coaches called them.`;
}

// ── the accounting of excluded calls, by category ─────────────────────────────────────────────────────────
// Fed ONLY from a producer field: `verification_summary.excluded_by_category` (or `.excluded`), either
// {category: count} or [{key|category|reason, n|count, label|text?}], with an optional `excluded_total`. Until the
// platform serves it, the accounting shows nothing — no count is summed, subtracted or estimated here. A category
// whose key names a private family is never rendered, whatever the producer sends (fail closed).
const EXCLUDED_WORDS = {
  unassessed: "graded before the quality checks existed, not yet re-checked",
  graded_before_checks: "graded before the quality checks existed, not yet re-checked",
  not_reverified: "not yet re-checked under the current rules",
  logging_gap: "the data it was graded on had a logging gap",
  low_power: "too little data to settle it",
  proxy_metric: "graded on a stand-in measure, not the one it named",
  under_review: "under classification review — counted neither way",
  classification_review: "under classification review — counted neither way",
  disputed: "under classification review — counted neither way",
  // The producer's category keys (web.verification_fields.EXCLUDED_CATEGORIES), mirrored here: the wire gate
  // blanks a served label when withheld grader notes quote the same engine text, so the page carries its own words.
  not_a_forecast: "Not a forecast: the outcome was already on the record when the call was made",
  past_period: "About a past period whose data arrived later: kept as a look back, not a forecast",
  opinion: "An opinion, explanation or hedge: not a measurable forecast",
  different_claim: "The stored test checks a different claim from the words",
  stand_in_measure: "Graded on a stand-in measure that cannot show the claim",
  either_outcome: "Either outcome satisfies the words",
  condition_not_measured: "Depends on a condition that was never measured, or names no checkable direction",
  condition_never_happened: "Its condition never happened, so it was never tested",
  docket: "Head-to-head docket bets, settled by their own rule and audited separately",
  could_not_verify: "Could not be verified under the current rules",
  not_yet_classified: "Not yet classified under the current rules",
  repeat: "The same forecast repeated: counted once",
};
const PRIVATE_CATEGORY = /journal|mood|state.?of.?mind|diary|video|self.?report|felt|private/i;
export function excludedAccounting(cal) {
  const vs = (cal || {}).verification_summary;
  if (!vs || typeof vs !== "object") return null;
  const src = vs.excluded_by_category ?? vs.excluded;
  let items = [];
  if (Array.isArray(src)) {
    items = src
      .filter((x) => x && typeof x === "object")
      .map((x) => ({ key: x.key ?? x.category ?? x.reason, n: x.n ?? x.count, label: x.label ?? x.text }));
  } else if (src && typeof src === "object") {
    items = Object.entries(src).map(([key, n]) => ({ key, n, label: null }));
  }
  const rows = items
    .filter((x) => typeof x.key === "string" && Number.isInteger(x.n) && !PRIVATE_CATEGORY.test(x.key) && !PRIVATE_CATEGORY.test(String(x.label || "")))
    .map((x) => ({ key: x.key, n: x.n, words: (typeof x.label === "string" && x.label.trim()) || EXCLUDED_WORDS[x.key] || x.key.replace(/_/g, " ") }));
  if (!rows.length) return null;
  const total = Number.isInteger(vs.excluded_total) ? vs.excluded_total : null;
  const eligible = Number.isInteger(vs.eligible_total) ? vs.eligible_total : null;
  const v = verifiedRecord(cal);
  const counted = v ? v.n : null;
  // The producer's accounting must reconcile AS SERVED (a check, not a derivation: nothing printed is computed here):
  // the rows add up to the served total, and eligible = left out + counted. A served accounting that does not add up —
  // or one that lost a row to the private-name filter above — is not shown at all (fail closed).
  let reconciles = null;
  if (total !== null) {
    const sum = rows.reduce((a, r) => a + r.n, 0);
    reconciles = sum === total && (eligible === null || counted === null || eligible === total + counted);
    if (!reconciles) return null;
  }
  return { rows, total, eligible, counted, reconciles, note: typeof vs.note === "string" && vs.note.trim() ? vs.note : null };
}

// ── the verified lead and its uncertainty (owner ruling 2026-11-09) ───────────────────────────────────────────────
// Fed ONLY from `verification_summary` / `platform.strata.coaches.verified` as served by /api/calibration. The lead
// sentence is the producer's own (`verified.sentence`, generated from the numbers); this module never writes a figure.

/** The served `verification_summary` object, or null. */
export function verificationSummary(cal) {
  const vs = (cal || {}).verification_summary;
  return vs && typeof vs === "object" ? vs : null;
}

const ciOk = (ci) => Array.isArray(ci) && ci.length === 2 && isNum(ci[0]) && isNum(ci[1]);

const SIGN_VERDICT_WORDS = {
  no_clear_difference: "no detectable difference",
  too_few: "too few calls to tell",
  coaches_better: "the coaches did better",
  rule_better: "the simple prediction did better",
};

/**
 * The lead the page opens with — only when the producer served a verified block WITH its own sentence and a baseline
 * on exactly the same calls. Returns {sentence, k, n, pct, ci, baseline:{right, n, pct, ci, unscorable}, sign} or null.
 */
export function verifiedLead(cal) {
  const v = verifiedRecord(cal);
  if (!v || typeof v.sentence !== "string" || !v.sentence.trim()) return null;
  const b = sameCalls(v.baseline, v.n);
  const baseline =
    b && Number.isInteger(b.right)
      ? { right: b.right, n: v.n, pct: pct(b.accuracy_pct), ci: ciOk(b.accuracy_ci95) ? intervalText(b.accuracy_ci95) : null, unscorable: Number.isInteger(b.unscorable) ? b.unscorable : 0 }
      : null;
  const s = v.sign_test && typeof v.sign_test === "object" ? v.sign_test : null;
  const sign =
    s && Number.isInteger(s.coach_only) && Number.isInteger(s.rule_only) && isNum(s.p)
      ? { coachOnly: s.coach_only, ruleOnly: s.rule_only, p: s.p, verdict: s.verdict, words: SIGN_VERDICT_WORDS[s.verdict] || verdictWords(s.verdict) }
      : null;
  return { sentence: v.sentence.trim(), k: v.confirmed, n: v.n, pct: pct(v.accuracy_pct), ci: intervalText(v.accuracy_ci95), baseline, sign };
}

/**
 * The three denominators, as served (owner ruling 2026-11-10, 1: "make the distinction between eligible records and the
 * deduplicated verified headline sample explicit so readers don't confuse denominators"): the eligible calls, the
 * calls left out (and how many of those are repeats of one forecast), and the verified sample. Carried from
 * excludedAccounting — which already refuses an accounting that does not reconcile — never derived here. Null when
 * any of the three is not served.
 */
export function denominatorSteps(cal) {
  const acc = excludedAccounting(cal);
  if (!acc || acc.eligible === null || acc.total === null || acc.counted === null) return null;
  const rep = acc.rows.find((r) => r.key === "repeat");
  return { eligible: acc.eligible, excluded: acc.total, counted: acc.counted, repeats: rep ? rep.n : 0 };
}

/**
 * The secondary, exploratory split of the verified sample by kind of call (owner ruling 2026-11-10, 2), as served on
 * verification_summary.subgroups — the producer's own sentences, p-values and adjustment words; nothing computed here.
 * Fails closed (null) unless it is marked exploratory, is over EXACTLY the verified sample (n = the headline N and the
 * kinds' counted calls add up to it — a check, not a derivation) and every kind carries its words.
 */
export function subgroupBlock(cal) {
  const sg = (verificationSummary(cal) || {}).subgroups;
  const v = verifiedRecord(cal);
  if (!sg || typeof sg !== "object" || sg.exploratory !== true || !v || sg.n !== v.n || !Array.isArray(sg.kinds)) return null;
  const kinds = sg.kinds.filter(
    (k) => k && typeof k === "object" && typeof k.key === "string" && Number.isInteger(k.counted) && typeof k.sentence === "string" && k.sentence.trim(),
  );
  if (!kinds.length || kinds.length !== sg.kinds.length || kinds.reduce((a, k) => a + k.counted, 0) !== v.n) return null;
  const str = (x) => (typeof x === "string" && x.trim() ? x.trim() : null);
  return {
    n: sg.n,
    caveat: str(sg.caveat),
    adjustment: str(sg.adjustment_words),
    test: str(sg.test),
    kinds: kinds.map((k) => ({
      key: k.key,
      words: KIND_WORDS[k.key] || str(k.words) || k.key,
      counted: k.counted,
      coach: Number.isInteger(k.coach_right) ? k.coach_right : null,
      rule: Number.isInteger(k.rule_right) ? k.rule_right : null,
      of: Number.isInteger(k.n) ? k.n : null,
      sentence: k.sentence.trim(),
    })),
  };
}

/** The sign test in plain words, every number carried: "The coaches alone were right on 16 of these calls and the …". */
export function signTestText(lead) {
  const s = lead && lead.sign;
  if (!s) return null;
  const p = s.p >= 0.001 ? s.p.toFixed(s.p >= 0.1 ? 2 : 3) : "< 0.001";
  return (
    `The coaches alone were right on ${s.coachOnly} of these calls and the simple prediction alone on ${s.ruleOnly}. ` +
    `On those calls an exact two-sided sign test gives p ${p.startsWith("<") ? p : `= ${p}`}: ${s.words}.`
  );
}

/** Why the record changed: the producer's sentence, beside the archived as-first-graded figure. Null when not served. */
export function whyChanged(cal) {
  const vs = verificationSummary(cal);
  if (!vs || typeof vs.why_changed !== "string" || !vs.why_changed.trim()) return null;
  return { text: vs.why_changed.trim(), archive: archiveRecord(cal) };
}

/** The archived original grading (as first graded), as served: {label, k, n, pct, ci} or null. */
export function archiveRecord(cal) {
  const a = (verificationSummary(cal) || {}).archive;
  if (!a || typeof a !== "object" || !Number.isInteger(a.n) || !Number.isInteger(a.confirmed)) return null;
  return {
    label: typeof a.label === "string" && a.label.trim() ? a.label.trim() : "as first graded",
    k: a.confirmed,
    n: a.n,
    pct: pct(a.accuracy_pct),
    ci: intervalText(a.accuracy_ci95),
  };
}

/**
 * The calls that count in the verified record — eligible, verified (reproduced or corrected) and cleared for
 * publication — as a Set of snapshot prediction ids (`<coach>-<prediction_id>`). Null when the producer did not serve
 * the list: then nothing may be presented as a verified outcome ("wrong this month" renders no miss at all).
 */
export function countedCalls(cal) {
  const list = (verificationSummary(cal) || {}).counted_calls;
  if (!Array.isArray(list) || !list.every((x) => typeof x === "string")) return null;
  return new Set(list);
}

/** A coach's own verified record (per-row `verification` / `verified`), when served: "6 of 15 re-checked right". */
export function coachVerified(c) {
  const v = c && (c.verification || c.verified);
  if (!v || typeof v !== "object") return null;
  const n = Number.isInteger(v.n) ? v.n : null;
  const k = Number.isInteger(v.confirmed) ? v.confirmed : Number.isInteger(v.right) ? v.right : null;
  if (n === null || k === null) return null;
  return { k, n, pct: pct(v.accuracy_pct), ci: intervalText(v.accuracy_ci95) };
}

/** A served calibration-v2 assessment in words: its three answers' sentences in order, or null when not served. */
export function assessmentWords(a) {
  const xs = v2Answers(a);
  return xs.length ? xs.map((x) => x.words).join(" ") : null;
}

export function recordHeadline(file) {
  if (!file || file.state !== "ok" || !file.record || !file.calibration) return null;
  const rec = file.record;
  const stratum = ((file.calibration.platform || {}).strata || {}).coaches || {};
  const v = verifiedRecord(file.calibration);
  const baseline = rec.baseline && rec.baseline.text ? rec.baseline.text : null;
  const skill = ((file.calibration.comparison || {}).skill || {}).sentence || null;
  const lower = (s) => (s ? s.charAt(0).toLowerCase() + s.slice(1).replace(/\.$/, "") : s);
  if (v) {
    const ci = intervalText(v.accuracy_ci95);
    const p = pct(v.accuracy_pct);
    // the comparison must be over the SAME re-verified set: the as-graded baseline and skill never stand in for it
    const vb = sameCalls(v.baseline, v.n);
    const vBaseline = vb && vb.text ? vb.text : null;
    const vs = sameCalls(v.skill, v.n);
    const vSkill = (vs && vs.sentence) || "No comparison with a simple guess is published for these same calls yet.";
    const vc = sameCalls(v.comparison, v.n);
    const lead = typeof v.sentence === "string" && v.sentence.trim() ? v.sentence.trim() : null; // the producer's own words
    return {
      mode: "verified",
      k: v.confirmed,
      n: v.n,
      lead,
      h1: lead || `The coaches were right on ${v.confirmed} of ${v.n} re-verified calls.`,
      dek: [p ? `${p}${ci ? ` — the ${ci}` : " — no interval published yet"}.` : null, vBaseline, vSkill].filter(Boolean).join(" "),
      sentence: lead || `${v.confirmed} of ${v.n} re-verified calls right${p ? ` — ${p}${ci ? `, ${ci}` : ""}` : ""}${vBaseline ? ` — and ${lower(vBaseline)}` : ""}.`,
      caveat:
        "Only calls that pass the current checks are counted here — a smaller set of calls, graded the same way. The earlier grades are kept in the archive below.",
      skill: vSkill,
      baselineSameCalls: Boolean(vBaseline),
      ci95: v.accuracy_ci95 || null,
      records: (vc && vc.records) || null,
      // the producer's archived original grading when served (verification_summary.archive), else the record as served
      archive: archiveRecord(file.calibration) || { k: rec.confirmed, n: rec.decided, pct: pct(rec.accuracy_pct), label: "as first graded, including grades not re-verified" },
    };
  }
  const ci = intervalText(stratum.accuracy_ci95);
  const p = pct(rec.accuracy_pct);
  return {
    mode: "as_graded",
    k: rec.confirmed,
    n: rec.decided,
    h1: `The coaches were right on ${rec.confirmed} of ${rec.decided} checked calls, as first graded.`,
    dek: [p ? `That is ${p}${ci ? ` — the ${ci}` : "; the 95% interval for the coaches' record is not published yet"}.` : null, baseline, skill].filter(Boolean).join(" "),
    sentence: `${rec.confirmed} of ${rec.decided} checked calls right as first graded${p ? ` — ${p}${ci ? `, ${ci}` : ", no interval published yet"}` : ""}${baseline ? ` — and ${lower(baseline)}` : ""}.`,
    ci95: stratum.accuracy_ci95 || null,
    caveat:
      "These are the grades as the grader first wrote them. The platform does not yet publish which of them were re-verified under the current rules, so read this as the recorded history, not a validated score.",
    skill,
    records: (file.calibration.comparison || {}).records || null,
    archive: null,
  };
}

/** The strata of the platform card, each with what was served for it; the blend is named, never the coaches' record. */
export function strataRows(file) {
  const cal = (file && file.calibration) || {};
  const st = ((cal.platform || {}).strata || {});
  const rec = (file && file.record) || {};
  const row = (key, name, s, top) => ({
    key,
    name,
    n: isNum((s || {}).n) ? s.n : null,
    right: isNum((s || {}).confirmed) ? s.confirmed : null,
    pct: pct((top || {}).accuracy_pct),
    ci: intervalText((top || {}).accuracy_ci95),
    skill: (s || {}).brier_skill,
    assessment: v2Stratum(cal, key), // calibration-v2: each stratum assessed on its own, never pooled
  });
  return [
    row("coaches", "Coach calls", st.coaches, { accuracy_pct: rec.accuracy_pct, accuracy_ci95: (st.coaches || {}).accuracy_ci95 }),
    row("hypotheses", "Hypothesis bets", st.hypotheses, cal.hypotheses),
    row("interval_forecasts", "Interval forecasts (the daily metric engine)", st.interval_forecasts, cal.interval_forecasts),
    row("weekly_prescriptions", "Weekly training prescriptions", st.weekly_prescriptions, cal.weekly_prescriptions),
  ];
}

/** The platform card — the blend of every stratum — as served. Never presented as the coaches' record, and never
 *  given a calibration verdict: calibration-v2 does not pool strata. */
export function blendRow(file) {
  const p = ((file && file.calibration) || {}).platform || {};
  if (!isNum(p.n)) return null;
  return { n: p.n, right: p.confirmed, pct: pct(p.accuracy_pct), ci: intervalText(p.accuracy_ci95), skill: p.brier_skill };
}

/** The bets a reset voided, newest reset first, dates in words. */
export function voidedRows(voided) {
  const by = (voided && voided.by_reset) || {};
  return Object.keys(by)
    .sort()
    .reverse()
    .map((d) => ({ date: d, words: dayInWords(d) || d, n: by[d] }));
}

// ── the stated-confidence chart ─────────────────────────────────────────────────────────────────────────────
// x: the stated-confidence BAND as the API served it (lo–hi, one tenth wide) — the data's resolution. Inside a
// band the coaches' dots sit side by side in a fixed order (the position inside a band carries no meaning, and
// the caption says so); y: how often those calls came true; dot area ∝ n. A dashed diagonal marks "came true
// exactly as often as stated". Every dot is an inspectable point with a prewritten label.

/** One dot per coach per served band, in a fixed order (band, then the coach order given). */
export function calibrationDots(coaches) {
  const out = [];
  (coaches || []).forEach((c, ci) => {
    for (const b of c.reliability_bins || []) {
      if (!isNum(b.lo) || !isNum(b.hi) || !isNum(b.observed_rate) || !isNum(b.n) || b.n <= 0) continue;
      out.push({ coach: c.coach_name, order: ci, lo: b.lo, hi: b.hi, mean: b.mean_confidence, rate: b.observed_rate, n: b.n });
    }
  });
  out.sort((a, b) => a.lo - b.lo || a.order - b.order);
  return out;
}

/** The svg string. `o.width` = the container's width on a phone (the island passes it), so text stays ≥ 11 px. */
export function calibrationChart(coaches, o = {}) {
  const W = o.width || (o.mobile ? 350 : 600); // the island passes the container width at every size, so text is drawn at its true size
  const H = o.mobile ? 300 : 360;
  const fs = o.mobile ? 12.5 : 12;
  const padL = Math.ceil(4 * fs * 0.6 + 14);
  const padR = 12;
  const padT = 14;
  const padB = 34;
  const x = (v) => padL + (W - padL - padR) * v;
  const y = (v) => padT + (H - padT - padB) * (1 - v);
  const dots = calibrationDots(coaches);
  const maxN = Math.max(1, ...dots.map((d) => d.n));
  const rMax = o.mobile ? 13 : 18;
  const r = (n) => Math.max(3, rMax * Math.sqrt(n / maxN));
  let g = "";
  for (const t of [0, 0.25, 0.5, 0.75, 1]) {
    g += `<line x1="${padL}" y1="${y(t).toFixed(1)}" x2="${W - padR}" y2="${y(t).toFixed(1)}" stroke="#E3E3DD" stroke-width="1"/>`;
    g += `<text x="${padL - 8}" y="${(y(t) + 4).toFixed(1)}" text-anchor="end" font-family="IBM Plex Mono,monospace" font-size="${fs}" fill="#5C5C58">${t * 100}%</text>`;
  }
  const xt = o.mobile ? [0, 0.5, 1] : [0, 0.25, 0.5, 0.75, 1];
  for (const t of xt) {
    const anchor = t === 0 ? "start" : t === 1 ? "end" : "middle";
    g += `<text x="${x(t).toFixed(1)}" y="${H - 12}" text-anchor="${anchor}" font-family="IBM Plex Mono,monospace" font-size="${fs}" fill="#5C5C58">${t * 100}%</text>`;
  }
  g += `<line x1="${x(0)}" y1="${y(0)}" x2="${x(1)}" y2="${y(1)}" stroke="#121212" stroke-width="1" stroke-dasharray="3 5"/>`;
  // the bands that hold calls, shaded, so the resolution is visible
  const bands = [...new Map(dots.map((d) => [`${d.lo}`, d])).values()];
  for (const b of bands) g += `<rect x="${x(b.lo).toFixed(1)}" y="${padT}" width="${(x(b.hi) - x(b.lo)).toFixed(1)}" height="${H - padT - padB}" fill="#121212" opacity="0.04"/>`;
  let marks = "";
  const points = [];
  for (const b of bands) {
    const inBand = dots.filter((d) => d.lo === b.lo);
    const w = x(b.hi) - x(b.lo);
    inBand.forEach((d, i) => {
      const cx = x(b.lo) + (w * (i + 0.5)) / inBand.length;
      const cy = y(d.rate);
      marks += `<circle cx="${cx.toFixed(1)}" cy="${cy.toFixed(1)}" r="${r(d.n).toFixed(1)}" fill="#1B3FD6" fill-opacity="0.28" stroke="#1B3FD6" stroke-width="1.5"/>`;
      points.push({
        x: Number(cx.toFixed(1)),
        y: Number(cy.toFixed(1)),
        v: d.rate,
        label: `${d.coach} · stated ${statedWords(d.mean)} · ${d.n} ${d.n === 1 ? "call" : "calls"} · ${num(d.rate * 100, 0)}% came true`,
      });
    });
  }
  const aria = o.aria || "Stated confidence against how often the calls came true, one dot per coach per confidence band, sized by the number of calls.";
  return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(aria)}" data-chart data-points="${esc(JSON.stringify(points))}">${g}${marks}</svg>`;
}
