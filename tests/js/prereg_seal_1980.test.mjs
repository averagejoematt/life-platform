// tests/js/prereg_seal_1980.test.mjs — #1980: the sealed pre-registration reaches
// the page. renderCalibration + renderPredictions both render the seal block
// (link + SHA-256 + copy-pasteable verify command) when the payload carries
// `prereg_seal`, and render nothing (never a broken/guessed link) when it's
// absent — the honest-empty contract for a freshly re-anchored cycle whose
// stamp hasn't published yet.
import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";

const ei = await import("../../site/assets/js/evidence_intelligence.js");

const SEAL = {
  genesis: "2026-07-27",
  sha256: "adece752feeeb2a2e9610ec7a2f9b2556d13e6b0bf45d63bdbb2c5d18b116515",
  artifact_url: "https://averagejoematt.com/experiments/prereg/genesis-2026-07-27.json",
  stamp_url: "https://averagejoematt.com/experiments/prereg/genesis-2026-07-27.sha256.json",
  verify: "curl -s https://averagejoematt.com/experiments/prereg/genesis-2026-07-27.json | shasum -a 256",
};

const CAL_BASE = { platform: {}, coaches: [], hypotheses: {}, voided: { n: 0 }, cycle: 11 };
const PRED_BASE = { overall: {}, predictions: [] };

test("renderCalibration renders the seal link, hash, and verify command", () => {
  const html = ei.renderCalibration({ ...CAL_BASE, prereg_seal: SEAL });
  assert.match(html, /href="https:\/\/averagejoematt\.com\/experiments\/prereg\/genesis-2026-07-27\.json"/);
  assert.match(html, new RegExp(SEAL.sha256));
  assert.match(html, /shasum -a 256/);
  assert.match(html, /class="rd-copy-btn"/);
});

test("renderCalibration at the true zero-state still renders the seal (verifiable before anything grades)", () => {
  const html = ei.renderCalibration({ ...CAL_BASE, prereg_seal: SEAL });
  assert.match(html, /No graded forecasts yet/);
  assert.match(html, new RegExp(SEAL.sha256));
});

test("renderCalibration renders nothing when prereg_seal is absent (honest-empty, no guessed link)", () => {
  const html = ei.renderCalibration(CAL_BASE);
  assert.doesNotMatch(html, /frozen pre-registration/);
  assert.doesNotMatch(html, /rd-copy-btn/);
});

test("renderPredictions renders the seal link, hash, and verify command", () => {
  const html = ei.renderPredictions({ ...PRED_BASE, prereg_seal: SEAL });
  assert.match(html, /href="https:\/\/averagejoematt\.com\/experiments\/prereg\/genesis-2026-07-27\.json"/);
  assert.match(html, new RegExp(SEAL.sha256));
  assert.match(html, /shasum -a 256/);
});

test("renderPredictions at the true zero-state still renders the seal", () => {
  const html = ei.renderPredictions({ ...PRED_BASE, prereg_seal: SEAL });
  assert.match(html, /No scored predictions yet/);
  assert.match(html, new RegExp(SEAL.sha256));
});

test("renderPredictions renders nothing when prereg_seal is absent", () => {
  const html = ei.renderPredictions(PRED_BASE);
  assert.doesNotMatch(html, /frozen pre-registration/);
});

test("a seal missing sha256 or artifact_url is treated as absent (never a half-broken block)", () => {
  const html = ei.renderCalibration({ ...CAL_BASE, prereg_seal: { verify: "curl ..." } });
  assert.doesNotMatch(html, /frozen pre-registration/);
});
