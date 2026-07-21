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
const { renderReceipts } = await import("../../site/assets/js/evidence_meta.js");

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
  per_feature_note: "reported in tokens, not dollars: the per-Lambda metric stream carries no model dimension",
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
