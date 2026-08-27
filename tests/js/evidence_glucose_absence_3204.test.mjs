// tests/js/evidence_glucose_absence_3204.test.mjs — #3204: the glucose door tells
// the reader when the sensor stopped, and binds the keys the endpoint really serves.
//
// Two defects met here. The endpoint published 2026-08-24's `avg_mg_dl: 104.3` and
// `tir_status: "excellent"` for days after the Dexcom Stelo session ended — and the
// door never showed them, because the head figures bound `cur.avg` / `cur.tir` while
// /api/glucose has always published `avg_mg_dl` / `time_in_range_pct`.
//
// That is ACCIDENTAL honesty, and it is not coverage: a rename on either side would
// have restored the lie with nothing to catch it. The fix binds the endpoint's real
// keys — safe because the endpoint now nulls its day scalars once the sensor is dark
// (see tests/test_sensor_absence_3204.py) — and renders `sensor.note` so the empty
// figure row has a stated reason rather than being mysteriously absent.
import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";

const { renderGlucose } = await import("../../site/assets/js/evidence_nutrition.js");

function stubFetch(payloads) {
  globalThis.fetch = async (path) => {
    const body = payloads[path];
    if (body === undefined) return { ok: false, status: 404, json: async () => ({}) };
    return { ok: true, status: 200, json: async () => body };
  };
}

// has_cgm true = the 30-day window still contains CGM data, which is exactly the
// state during a fresh gap: the door does NOT fall into its long-gap empty state
// (that is gated on 30 days and would not have appeared until ~2026-09-23), so this
// is the path where the stale numbers would have surfaced.
const MEAL_ARM = { "/api/meal_glucose": { meals: [], period_days: 30, has_cgm: true } };

const LIVE = {
  glucose: {
    avg_mg_dl: 104.3,
    time_in_range_pct: 91,
    as_of_date: "2026-08-27",
    sensor: { status: "fresh", label: "CGM (glucose)", days_behind: 0, note: null },
  },
  glucose_trend: [{ date: "2026-08-27", value: 104.3 }],
};

// The exact wire state that filed #3204, as the endpoint now serves it: day scalars
// absent, the silence described.
const DARK = {
  glucose: {
    avg_mg_dl: null,
    time_in_range_pct: null,
    tir_status: null,
    as_of_date: null,
    sensor: {
      status: "stale",
      label: "CGM (glucose)",
      last_reading_date: "2026-08-24",
      days_behind: 3,
      max_days_behind: 1,
      note: "No CGM (glucose) reading since 2026-08-24 — 3 days dark. The values shown are that day's last-known readings, NOT current.",
    },
  },
  glucose_trend: [{ date: "2026-08-24", value: 104.3 }],
};

test("a live sensor renders the head figures from the endpoint's real keys", async () => {
  stubFetch(MEAL_ARM);
  const html = await renderGlucose(LIVE);
  assert.match(html, /104\.3/, "avg_mg_dl must reach the reader — binding `cur.avg` printed nothing");
  assert.match(html, /91%/, "time_in_range_pct must reach the reader");
  assert.doesNotMatch(html, /dark/, "a live sensor carries no absence banner");
});

test("the old key names are no longer what the door binds", async () => {
  // The must-fail control for the rename: a payload in the OLD shape must now
  // render no figures. If this still printed 104.3 the binding was not actually
  // moved and the first test could be passing on the wrong key.
  stubFetch(MEAL_ARM);
  const html = await renderGlucose({ glucose: { avg: 104.3, tir: 91 }, glucose_trend: [] });
  assert.doesNotMatch(html, /104\.3/, "`cur.avg` must no longer be a binding");
});

test("a dark sensor prints no current figures and says why", async () => {
  stubFetch(MEAL_ARM);
  const html = await renderGlucose(DARK);
  assert.doesNotMatch(html, /avg mg\/dL/, "no figure may claim to be the current average");
  assert.doesNotMatch(html, /time in range/, "nor the current time-in-range");
  assert.doesNotMatch(html, /excellent/, "nor a grade earned days ago");
  assert.match(html, /No CGM \(glucose\) reading since 2026-08-24/, "the absence must be STATED, not merely blank");
  assert.match(html, /NOT current/, "the reader must be told these are last-known values");
});

test("the absence note precedes the trend chart, which frames the chart's own caption", async () => {
  // The shared lineChart component captions a short series "Latest 104.3 · 1
  // reading so far" — a component-level phrasing, not a glucose one, and out of
  // scope to change here. It reads correctly ONLY because the absence note lands
  // above it and says in so many words that the values shown are that day's
  // last-known readings. That ordering is therefore load-bearing, so it is pinned:
  // moving the note below the chart would leave "Latest 104.3" unframed.
  stubFetch(MEAL_ARM);
  const html = await renderGlucose(DARK);
  assert.ok(html.indexOf("3 days dark") < html.indexOf("Glucose trend"), "the absence must be stated before any figure derived from it");
});

test("a dark sensor keeps the dated trend — cutting the day scalars must not cut the archive", async () => {
  stubFetch(MEAL_ARM);
  const html = await renderGlucose(DARK);
  assert.match(html, /Glucose trend/, "the historical curve survives the sensor ending");
});
