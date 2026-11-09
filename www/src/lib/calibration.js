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
// the band, sized by n — never a curve — and the label is the API's own, in words (no threshold is invented here).
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

/** The API's calibration label, in words. Inadequate evidence reads as such; nothing favourable is implied. */
const LABEL_WORDS = {
  not_measurable: "not measurable — nearly every call was stated at one confidence",
  insufficient_data: "insufficient evidence",
  nascent: "insufficient evidence",
  "over-confident": "came true less often than stated",
  "under-confident": "came true more often than stated",
  not_yet_skillful: "not yet skillful — no better than its base rate",
  "well-calibrated": "stated confidence matched what came true",
  under_review: "under review",
};
export function labelWords(label) {
  if (!label) return "no label served";
  return LABEL_WORDS[label] || String(label).replace(/[_-]+/g, " ");
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
  return { rows, total: Number.isInteger(vs.excluded_total) ? vs.excluded_total : null, note: typeof vs.note === "string" && vs.note.trim() ? vs.note : null };
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

/** A served `assessment_v2` in words (its own sentence first, else its label), or null when not served. */
export function assessmentWords(a) {
  if (!a || typeof a !== "object") return null;
  for (const k of ["sentence", "text", "summary"]) if (typeof a[k] === "string" && a[k].trim()) return a[k];
  return typeof a.label === "string" && a.label ? labelWords(a.label) : null;
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
    return {
      mode: "verified",
      k: v.confirmed,
      n: v.n,
      h1: `The coaches were right on ${v.confirmed} of ${v.n} re-verified calls.`,
      dek: [p ? `${p}${ci ? ` — the ${ci}` : " — no interval published yet"}.` : null, vBaseline, vSkill].filter(Boolean).join(" "),
      sentence: `${v.confirmed} of ${v.n} re-verified calls right${p ? ` — ${p}${ci ? `, ${ci}` : ""}` : ""}${vBaseline ? ` — and ${lower(vBaseline)}` : ""}.`,
      caveat:
        "Only calls that pass the current checks are counted here — a smaller set of calls, graded the same way. The earlier grades are kept in the archive below.",
      skill: vSkill,
      baselineSameCalls: Boolean(vBaseline),
      ci95: v.accuracy_ci95 || null,
      records: (vc && vc.records) || null,
      archive: { k: rec.confirmed, n: rec.decided, pct: pct(rec.accuracy_pct), label: "as first graded, including grades not re-verified" },
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
    label: (s || {}).calibration,
  });
  return [
    row("coaches", "Coach calls", st.coaches, { accuracy_pct: rec.accuracy_pct, accuracy_ci95: (st.coaches || {}).accuracy_ci95 }),
    row("hypotheses", "Hypothesis bets", st.hypotheses, cal.hypotheses),
    row("interval_forecasts", "Interval forecasts (the daily metric engine)", st.interval_forecasts, cal.interval_forecasts),
    row("weekly_prescriptions", "Weekly training prescriptions", st.weekly_prescriptions, cal.weekly_prescriptions),
  ];
}

/** The platform card — the blend of every stratum — as served. Never presented as the coaches' record. */
export function blendRow(file) {
  const p = ((file && file.calibration) || {}).platform || {};
  if (!isNum(p.n)) return null;
  return { n: p.n, right: p.confirmed, pct: pct(p.accuracy_pct), ci: intervalText(p.accuracy_ci95), skill: p.brier_skill, label: p.calibration };
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
