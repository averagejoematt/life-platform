// tests/js/evidence_receipts.test.mjs — the Glass Engine renderer (#1397).
//
// renderReceipts is the reader-facing half of the cost-honesty contract: the API
// omits figures when the governor's breakdown is stale, and this renderer has to
// ACT on that rather than quietly printing whatever it was handed. The failure
// mode these tests exist to block is a cost page that looks perfectly healthy
// while showing three-day-old numbers.
//
// These are pure string assertions — renderReceipts takes a payload and returns
// HTML — so they run offline and catch regressions the Playwright render sweep
// would only catch if someone remembered to re-run it against all four states.
import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";

// Dynamic import, matching evidence_character_receipts.test.mjs: evidence_meta.js
// pulls in root-relative "/assets/js/…" specifiers, and STATIC imports are resolved
// during linking — i.e. before loader.mjs has had a chance to register the resolver.
// A top-level await defers resolution until after registration.
const { renderReceipts, renderInference } = await import("../../site/assets/js/evidence_meta.js");

const HEALTHY = {
  stale: false,
  stale_reason: null,
  tier: 1,
  tier_semantics: "Internal/dev AI paused — the ensemble, the chronicle editor, and coherence-semantic checks.",
  base_ceiling_usd: 85.0,
  ceiling_usd: 85.0,
  surge_active: false,
  surge_threshold_uniques: 900,
  recent_uniques: 120,
  month_to_date_usd: 26.11,
  projected_month_end_usd: 62.4,
  ai_daily_usd: 1.2,
  non_ai_daily_usd: 0.8,
  computed_at: "2026-07-21T02:00:00+00:00",
  history: [
    { date: "2026-07-01", mtd_usd: 2.1 },
    { date: "2026-07-02", mtd_usd: 5.0 },
    { date: "2026-07-03", mtd_usd: 8.4 },
    { date: "2026-07-04", mtd_usd: 12.2 },
    { date: "2026-07-05", mtd_usd: 15.9 },
  ],
  mtd_pct_of_ceiling: 30.7,
  projected_pct_of_ceiling: 73.4,
  // #3554 — the scope fields. `projected_month_end_usd` is the tier-deciding
  // (recurring-classes-only) figure; `projected_all_classes_usd` is the scope-complete
  // one. BOTH percentages are computed by the API beside each other — this renderer
  // must never divide anything, or the page mints a second projection (#1618's rule).
  projected_all_classes_usd: 77.9,
  projected_all_classes_pct_of_ceiling: 91.6,
  projected_scope: "recurring classes only (prod-cron, remediation)",
  projected_classes: ["prod-cron", "remediation"],
  episodic_classes: ["ci", "dev-session"],
  episodic_billing_days: { "prod-cron": 30, ci: 6, "dev-session": 2, remediation: 13 },
  episodic_premise_violations: [],
  projection_note: "Scope: this month-end projection extrapolates only the spend classes that recur on a schedule (prod-cron, remediation). Episodic spend (ci, dev-session) is counted in full in month-to-date but is not multiplied out across the days remaining (#2892). Extrapolating every class instead gives $77.90.",
  per_feature_note: "Per-feature dollars are published on the inference receipt. They are self-metered at the inference chokepoint (ADR-062).",
  note: "One AWS budget covers the WHOLE platform, not just AI.",
};

const STALE = {
  ...HEALTHY,
  stale: true,
  stale_reason: "budget breakdown last computed 72h ago (governor runs every 8h)",
  month_to_date_usd: null,
  projected_month_end_usd: null,
  ceiling_usd: null,
  ai_daily_usd: null,
  non_ai_daily_usd: null,
  history: [],
  mtd_pct_of_ceiling: undefined,
  projected_pct_of_ceiling: undefined,
  // #3554: the new figures join the staleness contract rather than becoming the one
  // number that quietly keeps rendering.
  projected_all_classes_usd: null,
  projected_all_classes_pct_of_ceiling: undefined,
  projected_scope: null,
  projection_note: null,
};

// ── the honesty contract ─────────────────────────────────────────────────────
test("stale — renders NO dollar figure anywhere", () => {
  // Non-vacuity first (the check_doc_facts house rule): prove the detector fires on
  // the healthy render, so a green stale assertion means "no dollars" and not
  // "the regex never matched anything in the first place".
  assert.equal(/\$\d/.test(renderReceipts(HEALTHY)), true, "the $-detector itself is broken — healthy state has dollar figures");
  const html = renderReceipts(STALE);
  assert.equal(/\$\d/.test(html), false, `a dollar figure leaked into the stale state:\n${html}`);
});

test("stale — states the reason verbatim rather than failing silently", () => {
  const html = renderReceipts(STALE);
  assert.ok(html.includes("72h ago"), "the stale reason must reach the reader");
  assert.ok(html.includes("left blank rather than shown at their last-known value"));
});

test("stale — still reports the tier, which is read independently of the figures", () => {
  const html = renderReceipts(STALE);
  assert.ok(html.includes("rcp-gauge"));
  assert.ok(html.includes("Internal/dev AI paused"));
});

test("stale — provenance is present AND carries the concrete timestamp", () => {
  // The regression this pins: an early-return branch that skips provenance, so the
  // one state where "how stale?" matters most is the one that won't tell you.
  const html = renderReceipts(STALE);
  assert.ok(html.includes("provenance"), "stale state dropped the provenance line");
  assert.ok(html.includes("last run 2026-07-21 02:00 UTC"), "stale state withheld computed_at");
  assert.ok(html.includes("pv-stale"), "stale provenance must be visually marked");
  // …and the timestamp must sit INSIDE the emphasised span, not trail it faintly.
  assert.match(html, /<span class="pv-src pv-stale">[^<]*last run 2026-07-21 02:00 UTC<\/span>/);
});

test("healthy — provenance renders exactly once and is NOT marked stale", () => {
  const html = renderReceipts(HEALTHY);
  assert.equal(html.match(/class="provenance"/g).length, 1);
  assert.equal(html.includes("pv-stale"), false);
});

// ── the figures come through, and are the payload's ──────────────────────────
test("healthy — every headline figure is the payload value, not a literal", () => {
  const html = renderReceipts(HEALTHY);
  assert.ok(html.includes("$26.1"), "month-to-date");
  assert.ok(html.includes("$62.4"), "projection");
  assert.ok(html.includes("$85"), "ceiling from the payload");
  assert.ok(html.includes("73.4% of ceiling"));
});

test("surge — names both ceilings and the traffic that floated it", () => {
  const html = renderReceipts({ ...HEALTHY, surge_active: true, ceiling_usd: 100.0, recent_uniques: 972 });
  assert.ok(html.includes("$85") && html.includes("$100"), "both the base and the floated ceiling");
  assert.ok(html.includes("972"));
  assert.ok(html.includes("ADR-133"));
  assert.ok(html.includes("ceiling (surge mode)"));
});

// ── the dated ceiling window (#1999) ─────────────────────────────────────────
// A temp window used to render as a silent gap between the base figure and the
// one in effect. The governor now names the window; the page must SAY it.
const WINDOW = {
  start: "2026-07-01",
  end_exclusive: "2026-08-01",
  base_ceiling: 115.0,
  surge_ceiling: 135.0,
  reverts_to_base_ceiling: 85.0,
  reverts_to_surge_ceiling: 100.0,
  reason: "A one-month raise approved on 2026-07-21 (ADR-133 amendment).",
};

test("dated window — the raised base is attributed, not left as a bare delta", () => {
  const html = renderReceipts({ ...HEALTHY, base_ceiling_usd: 115.0, ceiling_usd: 115.0, ceiling_window: WINDOW });
  assert.ok(html.includes("$115"), "the window's base");
  assert.ok(html.includes("$85"), "what it reverts to — the delta is meaningless without it");
  assert.ok(html.includes("2026-07-01") && html.includes("2026-08-01"), "the window's dates");
  assert.ok(html.includes("ADR-133 amendment"), "the reason the governor supplied");
});

test("no window — no window prose at all", () => {
  const html = renderReceipts({ ...HEALTHY, ceiling_window: null });
  assert.ok(!html.includes("dated window"));
});

test("incomplete window descriptor renders nothing rather than a hole", () => {
  const html = renderReceipts({ ...HEALTHY, ceiling_window: { start: "2026-07-01" } });
  assert.ok(!html.includes("dated window"));
});

// ── the tier ladder ──────────────────────────────────────────────────────────
test("tier ladder — the current band is lit and lower bands read as crossed", () => {
  const html = renderReceipts({ ...HEALTHY, tier: 2 });
  const bands = [...html.matchAll(/<span class="rcp-band([^"]*)"/g)].map((m) => m[1].trim());
  assert.equal(bands.length, 4, "four bands, 0–3");
  assert.equal(bands[0], "is-past");
  assert.equal(bands[1], "is-past");
  assert.equal(bands[2], "is-on");
  assert.equal(bands[3], "", "bands above the current tier stay neutral");
});

test("tier 0 — nothing is marked past, band 0 is lit", () => {
  const bands = [...renderReceipts({ ...HEALTHY, tier: 0 }).matchAll(/<span class="rcp-band([^"]*)"/g)].map((m) => m[1].trim());
  assert.equal(bands[0], "is-on");
  assert.deepEqual(bands.slice(1), ["", "", ""]);
});

// ── degenerate inputs ────────────────────────────────────────────────────────
test("a short history does not draw a misleading trend line", () => {
  // charts.js refuses to draw below 4 points; this asserts the renderer routes
  // through that guard instead of hand-rolling a 2-point diagonal.
  const html = renderReceipts({ ...HEALTHY, history: [{ date: "2026-07-01", mtd_usd: 2.1 }, { date: "2026-07-02", mtd_usd: 5.0 }] });
  assert.ok(html.includes("chart--empty"), "a 2-point series must render the honest empty state");
  assert.equal(html.includes("<path"), false, "no line geometry below the 4-point floor");
});

test("missing tier — the ladder is omitted rather than rendering a phantom band", () => {
  const html = renderReceipts({ ...HEALTHY, tier: null, tier_semantics: null });
  assert.equal(html.includes("rcp-gauge"), false);
});

test("null/garbage payload degrades to an honest empty state", () => {
  assert.ok(renderReceipts(null).length > 0);
  assert.ok(renderReceipts(undefined).includes("unavailable"));
});

test("no raw payload object ever reaches the output", () => {
  for (const p of [HEALTHY, STALE]) {
    const html = renderReceipts(p);
    assert.equal(html.includes("[object Object]"), false);
    assert.equal(/\bundefined\b/.test(html), false, "an undefined leaked into rendered copy");
    assert.equal(/\bNaN\b/.test(html), false);
  }
});

// ── the over-ceiling case (found live on day one: projected $96.09 vs an $85 ceiling) ──
// #3554 note: the breach is judged on the HEADLINE figure — the scope-complete one when
// the API publishes it — because "will this month go over" is a question about the whole
// bill, not about the subset the tier ladder happens to extrapolate.
const UNSCOPED = (() => {
  const p = { ...HEALTHY };
  delete p.projected_all_classes_usd;
  delete p.projected_all_classes_pct_of_ceiling;
  delete p.projected_scope;
  delete p.projection_note;
  return p;
})();

test("over-ceiling — the breach is stated in prose, not left as a faint delta", () => {
  const html = renderReceipts({ ...UNSCOPED, projected_month_end_usd: 96.09, projected_pct_of_ceiling: 113.0 });
  assert.ok(html.includes("over the ceiling"), "a projection above the ceiling must be named, not just implied by a percentage");
  assert.ok(html.includes("$96.1") && html.includes("$85"), "both sides of the comparison appear");
});

test("over-ceiling — both scopes over: the ladder IS the response, and says so", () => {
  const html = renderReceipts({
    ...HEALTHY,
    projected_month_end_usd: 96.09, projected_pct_of_ceiling: 113.0,
    projected_all_classes_usd: 120.0, projected_all_classes_pct_of_ceiling: 141.2,
  });
  assert.ok(html.includes("over the ceiling"));
  assert.ok(html.includes("The tier ladder above is the response"));
  assert.ok(html.includes("$120"), "the breach is stated against the headline figure");
});

test("over-ceiling — only the ALL-CLASS figure is over: the prose must not claim the ladder responded", () => {
  // #3554's second-order trap. The ladder is decided on the recurring-only projection,
  // so "features switch off as the projection climbs" would be a second untrue sentence
  // on the same page when that narrower figure is still inside the ceiling.
  const html = renderReceipts({
    ...HEALTHY,
    projected_month_end_usd: 62.4, projected_pct_of_ceiling: 73.4,
    projected_all_classes_usd: 96.09, projected_all_classes_pct_of_ceiling: 113.0,
  });
  assert.ok(html.includes("over the ceiling"), "the all-class breach must still be named");
  assert.equal(html.includes("The tier ladder above is the response"), false, "the ladder has NOT responded — do not claim it has");
  assert.ok(html.includes("The tier ladder above has not moved"));
  assert.ok(html.includes("$62.4"), "the figure the ladder actually reads must be named");
});

test("under-ceiling — no breach language when the projection is fine", () => {
  const html = renderReceipts(UNSCOPED); // 73.4%
  assert.equal(html.includes("over the ceiling"), false);
});

test("run-rate labels read as prose, not ttl()-mangled keys", () => {
  const html = renderReceipts(HEALTHY);
  assert.ok(html.includes("AI, per day"), "'ai_per_day' title-cases to the wrong-looking 'Ai Per Day'");
  assert.ok(html.includes("infrastructure, per day"));
  assert.equal(/\bAi\b/.test(html), false, "'Ai' must never render — it is AI");
});

// ══════════════════════════════════════════════════════════════════════════════
// #3554 — the headline projection carries its scope
//
// What a reader saw on 2026-09-05: "$83.7 projected month-end · 33.2% of ceiling",
// green, with the word "projected" doing all the work. That figure extrapolates only
// the recurring caller classes; the same payload's all-class figure was $103.49. This
// renderer now headlines the scope-complete number and keeps the narrower one visible
// as what the tier ladder is actually decided on.
// ══════════════════════════════════════════════════════════════════════════════
test("scoped — the headline projection is the all-class figure, labelled as such", () => {
  const html = renderReceipts(HEALTHY);
  assert.ok(html.includes("$77.9"), "the scope-complete figure headlines");
  assert.ok(html.includes("projected month-end · all spend"), "the tile label names the scope");
  assert.ok(html.includes("91.6% of ceiling"), "its percentage comes from the API, beside its own figure");
});

test("scoped — the narrower tier-deciding figure is stated, not hidden", () => {
  const html = renderReceipts(HEALTHY);
  assert.ok(html.includes("The tier ladder is decided on a narrower figure"));
  assert.ok(html.includes("$62.4"), "the recurring-only projection");
  assert.ok(html.includes("73.4% of ceiling"));
});

test("scoped — the scope prose is the API's sentence, not one composed here", () => {
  const html = renderReceipts(HEALTHY);
  assert.ok(html.includes("extrapolates only the spend classes that recur on a schedule"));
  assert.ok(html.includes("ci, dev-session"), "the excluded classes reach the reader");
});

test("scoped — no percentage is ever derived in JS", () => {
  // The negative control for #1618's rule, extended to the new pair: blank both
  // API-supplied percentages and NO percentage may appear anywhere.
  const html = renderReceipts({
    ...HEALTHY,
    mtd_pct_of_ceiling: undefined,
    projected_pct_of_ceiling: undefined,
    projected_all_classes_pct_of_ceiling: undefined,
    projection_note: null,
  });
  assert.equal(/\d% of ceiling/.test(html), false, "a percentage was minted client-side");
  // …and the detector is not vacuous: the healthy render does contain them.
  assert.equal(/\d% of ceiling/.test(renderReceipts(HEALTHY)), true);
});

test("unscoped payload — renders exactly as before, with no invented scope label", () => {
  // Back-compat: until the governor's next 8h run the payload may predate these fields.
  const html = renderReceipts(UNSCOPED);
  assert.ok(html.includes("$62.4"));
  assert.equal(html.includes("all spend"), false, "no scope may be claimed that the API did not state");
  assert.equal(html.includes("narrower figure"), false);
});

test("broken premise — the reader is told the excluded class bills like a schedule", () => {
  const html = renderReceipts({
    ...HEALTHY,
    episodic_premise_violations: ["ci"],
    projection_note: HEALTHY.projection_note + " Premise check: ci billed on 28 of the last 30 days — at or above the 25-day bar, so calling it episodic understates the forecast.",
  });
  assert.ok(html.includes("ci billed on 28 of the last 30 days"));
});

test("stale — the scope figures go blank with everything else", () => {
  const html = renderReceipts(STALE);
  assert.equal(html.includes("all spend"), false);
  assert.equal(html.includes("narrower figure"), false);
});

// ══════════════════════════════════════════════════════════════════════════════
// #3555 — the per-feature DOLLAR column on /method/inference/
// ══════════════════════════════════════════════════════════════════════════════
const INFERENCE = {
  ai_month_to_date_usd: 10.61,
  budget_ceiling_usd: 252.0,
  budget_tier: 0,
  models: [],
  features: [
    { lambda: "daily-brief", month_input_tokens: 320045, month_output_tokens: 64857, month_est_cost_usd: 2.8151 },
    { lambda: "life-platform-site-api-ai", month_input_tokens: 108654, month_output_tokens: 7314, month_est_cost_usd: 0.1669 },
    { lambda: "voice-fidelity-harness", month_input_tokens: 11454, month_output_tokens: 2636, month_est_cost_usd: null },
  ],
  attribution: {
    features_est_cost_usd: 10.62,
    models_est_cost_usd: 10.61,
    reconciliation_ratio: 0.999,
    drift_bar: 1.15,
    unpriced_features: 1,
    unattributed_label: "unknown",
    unattributed_usd: 0.2071,
    note: "Per-feature dollars are self-metered at the inference chokepoint: every call is priced from its own token usage and the model it actually resolved. One row is one Lambda, not one budget-guard feature.",
  },
  note: "Every Claude call routes through one audited chokepoint (ADR-062).",
};

test("inference — the per-feature dollar column renders from the API", () => {
  const html = renderInference(INFERENCE);
  assert.ok(html.includes("month $"), "the column exists");
  assert.ok(html.includes("$2.82"), "daily-brief's month-to-date dollars");
  assert.ok(html.includes("By feature (month-to-date)"));
});

test("inference — an unmetered feature renders an em dash, never $0.00", () => {
  const html = renderInference(INFERENCE);
  assert.equal(html.includes("$0.00"), false, "absence must not render as free");
  assert.ok(html.includes("<td class=\"num\">—</td>"));
});

test("inference — a Lambda appears exactly once", () => {
  // COST-04's reader-facing consequence: three identical site-api-ai rows meant a reader
  // summing the column triple-counted the ask endpoints.
  const html = renderInference(INFERENCE);
  assert.equal((html.match(/life-platform-site-api-ai/g) || []).length, 1);
});

test("inference — the attribution caveat is published with its checkable ratio", () => {
  const html = renderInference(INFERENCE);
  assert.ok(html.includes("self-metered at the inference chokepoint"));
  assert.ok(html.includes("0.999"), "the reconciliation ratio, so the caveat is checkable rather than asserted");
  assert.ok(html.includes("unknown row"));
  // The reason that was never true must not come back through the front-end either.
  assert.equal(/model dimension|model mix/.test(html), false);
});

test("inference — a payload with no attribution block still renders", () => {
  const html = renderInference({ ...INFERENCE, attribution: undefined });
  assert.ok(html.includes("$2.82"));
  assert.equal(html.includes("self-metered"), false);
});
