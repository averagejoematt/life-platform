// tests/js/daily_line.test.mjs — pins the two Day-1-only copy branches that had
// no unit owner (both fired as front-page bugs on Day 1 of cycle 11, /fullreview
// 2026-07-28 reader-4/reader-5):
//
// #1994 — heroProofLine's zero-delta branch must compose deliberate English
// ("holding even since the start"), never the bare mid-sentence token "even"
// placed sentence-initial ("even since the start —"). All three delta branches
// (down / up / zero) are pinned, in both the single-weigh-in and
// multi-weigh-in templates.
//
// #1995 — BRIEF_LINE_KICKER: the morning brief's daily line carries deictics
// anchored to the DATA day (yesterday by mint time, #1251), so its label may
// never re-anchor it to the render-day as "today" — that inversion is exactly
// how "DAY 1 · running now" and "starts tomorrow" co-occurred. The kicker is a
// single shared constant; the set-guard below scans ALL of site/assets/js/ so
// no consumer can drift back to a hardcoded "today's line".
import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

// Dynamic import after loader registration (the
// reference_site_js_test_and_build_pairs gotcha — a static import would resolve
// the graph before the "/assets/…" resolver exists).
const { heroProofLine, heroDeltaPhrase, BRIEF_LINE_KICKER } = await import("../../site/assets/js/daily_line.js");

const SITE_JS = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "site", "assets", "js");

/* ── #1994 — the hero proof sentence ─────────────────────────────────────── */

test("zero-delta Day-1 (one weigh-in): reads as deliberate English, never a bare 'even' fragment", () => {
  // The exact cycle-11 Day-1 payload shape: a single genesis weigh-in, delta 0.
  const line = heroProofLine({ lost_lbs: 0, weighin_count: 1, weighin_span_days: 0, last_weighin_date: "2026-07-27" }, 1);
  assert.equal(line, "holding even since the start — one weigh-in so far, Jul 27. The shape of it, every day, just below.");
});

test("zero-delta with a multi-weigh-in trend: 'holding even in N days', still a sentence", () => {
  const now = new Date("2026-08-08T12:00:00").getTime();
  const line = heroProofLine({ lost_lbs: 0.02, weighin_count: 5, weighin_span_days: 11, last_weighin_date: "2026-08-08" }, 12, now);
  assert.equal(line, "holding even in 12 days — the shape of it, every day, just below.");
});

test("down branch: magnitude rounded to 0.1, elapsed-days framing on a real trend", () => {
  const now = new Date("2026-08-08T12:00:00").getTime();
  const line = heroProofLine({ lost_lbs: 3.24, weighin_count: 5, weighin_span_days: 11, last_weighin_date: "2026-08-08" }, 12, now);
  assert.equal(line, "down 3.2 lb in 12 days — the shape of it, every day, just below.");
});

test("up branch (negative lost_lbs): honest 'up X lb', single-weigh-in template stays grammatical", () => {
  const line = heroProofLine({ lost_lbs: -1.6, weighin_count: 1, weighin_span_days: 0, last_weighin_date: "2026-07-27" }, 4);
  assert.equal(line, "up 1.6 lb since the start — one weigh-in so far, Jul 27. The shape of it, every day, just below.");
});

test("stale multi-weigh-in trend: the as-of anchor names the last weigh-in (#1225 honesty)", () => {
  const now = new Date("2026-08-12T12:00:00").getTime(); // 4 days after the last weigh-in
  const line = heroProofLine({ lost_lbs: 2.0, weighin_count: 4, weighin_span_days: 10, last_weighin_date: "2026-08-08" }, 16, now);
  assert.equal(line, "down 2 lb in 16 days (last weigh-in Aug 8) — the shape of it, every day, just below.");
});

test("no weigh-in date at all: degrades to honest copy, never 'undefined' or NaN", () => {
  const line = heroProofLine({ lost_lbs: 0, weighin_count: 0, weighin_span_days: 0 }, 1);
  assert.equal(line, "holding even since the start so far. The shape of it, every day, just below.");
});

test("no branch ever opens with the bare mid-sentence token 'even' (#1994 regression pin)", () => {
  for (const lost of [0, 0.04, -0.04]) {
    for (const [n, span] of [[1, 0], [3, 6]]) {
      const line = heroProofLine({ lost_lbs: lost, weighin_count: n, weighin_span_days: span, last_weighin_date: "2026-07-27" }, 7, Date.now());
      assert.ok(!/^even\b/.test(line), `bare 'even' fragment leaked: "${line}"`);
      assert.match(line, /^(down [\d.]+ lb|up [\d.]+ lb|holding even) /, `unexpected opener: "${line}"`);
    }
  }
  assert.equal(heroDeltaPhrase(0), "holding even");
});

/* ── #1995 — the brief-line kicker ───────────────────────────────────────── */

test("BRIEF_LINE_KICKER anchors to the data day: says 'yesterday's read', never any 'today'", () => {
  assert.match(BRIEF_LINE_KICKER, /yesterday's read/);
  assert.match(BRIEF_LINE_KICKER, /from the morning brief/);
  // The deictic guard: an elena_hero_line saying "tomorrow" under this kicker can
  // no longer invert — the label itself contains no render-day "today" claim.
  assert.ok(!/\btoday\b/i.test(BRIEF_LINE_KICKER), `kicker re-anchors to the render-day: "${BRIEF_LINE_KICKER}"`);
});

test("set-guard: no site module hardcodes a \"today's line\" kicker; all three consumers share the constant", () => {
  const files = readdirSync(SITE_JS).filter((f) => f.endsWith(".js"));
  for (const f of files) {
    const src = readFileSync(join(SITE_JS, f), "utf8");
    assert.ok(!/today.s line/i.test(src), `${f} re-anchors the brief line to "today's line"`);
  }
  // Guard the SET (all three consumers of elena_hero_line), not one instance.
  for (const f of ["story.js", "coaching.js", "cockpit.js"]) {
    const src = readFileSync(join(SITE_JS, f), "utf8");
    assert.ok(src.includes("BRIEF_LINE_KICKER"), `${f} must label the brief line via the shared BRIEF_LINE_KICKER`);
    assert.match(src, /from ["']\/assets\/js\/daily_line\.js["']/, `${f} must import the shared daily_line.js`);
  }
});

test("story.js composes the hero proof via the tested heroProofLine, never an inline bare-'even' ternary (#1994)", () => {
  const src = readFileSync(join(SITE_JS, "story.js"), "utf8");
  assert.ok(src.includes("heroProofLine("), "story.js must delegate the hero sentence to daily_line.heroProofLine");
  assert.ok(!/:\s*"even"/.test(src), "story.js reintroduced an inline bare-'even' delta token");
});
