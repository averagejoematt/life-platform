// tests/js/page_feedback_4182.test.mjs — the reader form's site half (#4182, M3).
// Honest by construction: only a 2xx earns "Thanks — read weekly."; a 404 (endpoint not
// deployed yet), 5xx, 429 or a network failure (postJSON's status 0) stays silent.
import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";

const pf = await import("../../site/assets/js/page_feedback.js");

test("the body is {page, made_sense, looking_for}: path only, text trimmed and capped at 500", () => {
  assert.deepEqual(pf.feedbackBody("/data/sleep/", "partly", "  where is REM?  "), {
    page: "/data/sleep/", made_sense: "partly", looking_for: "where is REM?",
  });
  assert.equal(pf.feedbackBody("/story/?utm=x#y", "yes", "").page, "/story/");
  assert.equal(pf.feedbackBody("/", "no", "x".repeat(900)).looking_for.length, pf.MAX_LOOKING_FOR);
  assert.equal(pf.feedbackBody(undefined, "yes", null).page, "/");
});

test("only a 2xx speaks; 404 / 5xx / 429 / network-fail are silent", () => {
  assert.equal(pf.statusFor({ ok: true, status: 201, data: {} }), "Thanks — read weekly.");
  for (const status of [404, 500, 503, 429, 0]) assert.equal(pf.statusFor({ ok: false, status, data: {} }), "");
  assert.equal(pf.statusFor(null), "");
});
