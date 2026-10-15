// tests/js/ck_absence_4586.test.mjs — #4586 acceptance box 2: every block has an absence state.
//
// Scope: the /next/v8/ preview's front page, This week page (week/) and trend page (trend/).
// The page code is MOUNTED, not just its builders: the real shell (site/next/v8/**/index.html)
// supplies the element ids and their static text, a fake document records what mount() writes
// or removes, and fetch serves the committed captures (tests/fixtures/kit_pages_4586/) except
// where a scenario takes the data a block binds to away. Then every slot must end as a
// sentence, or be removed together with its label — never a blank, never a dangling label,
// never "undefined" / "null" / "NaN".
import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const FIX = join(HERE, "..", "fixtures", "kit_pages_4586");
const SHELL = (page) => readFileSync(join(HERE, "..", "..", "site", "next", "v8", page, "index.html"), "utf8");
const load = (name) => JSON.parse(readFileSync(join(FIX, `${name}.json`), "utf8"));
const EDITION = load("edition");
const ROUTES = { "/api/pulse_history": "pulse_history", "/api/workouts": "workouts", "/api/training_overview": "training_overview", "/api/nutrition_overview": "nutrition_overview", "/api/frequent_meals": "frequent_meals" };

// ── a document that remembers: ids from the real shell, their static text, writes, removals ──
let els = new Map();
function mountShell(html, page, search = "") {
  els = new Map();
  const el = (innerHTML) => ({ innerHTML, removed: false, dataset: {}, remove() { this.removed = true; } });
  for (const m of html.matchAll(/id="([\w-]+)"[^>]*>([^<]*)</g)) els.set(m[1], el(m[2]));
  for (const m of html.matchAll(/id="([\w-]+)"/g)) if (!els.has(m[1])) els.set(m[1], el(""));
  globalThis.document = { readyState: "complete", title: "", body: { dataset: { ckPage: page, ckBase: "/next/v8/" } }, getElementById: (id) => (els.has(id) && !els.get(id).removed ? els.get(id) : null), addEventListener() {}, querySelector: () => null, querySelectorAll: () => [] };
  globalThis.location = { search };
}
const served = (overrides) => async (url) => {
  const path = String(url).split("?")[0];
  const miss = { ok: false, status: 404, text: async () => "", json: async () => null };
  if (path in overrides) return overrides[path] === null ? miss : { ok: true, json: async () => overrides[path] };
  if (path === "/api/edition") return { ok: true, json: async () => EDITION };
  return ROUTES[path] ? { ok: true, json: async () => load(ROUTES[path]) } : miss;
};
const seen = (id) => (els.has(id) && !els.get(id).removed ? els.get(id).innerHTML.replace(/aria-label="([^"]*)"/g, ">$1<").replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim() : null);
const BAD = /\bundefined\b|\bnull\b|\bNaN\b|\[object/;

// A slot ends as a sentence (`say`) or is removed with its label (`gone`); `pairs` are
// [label, content] — the label may never outlive its content.
// `sections` are [section, body]: a body that ends empty must have its whole section removed.
function check(where, { say = [], gone = [], pairs = [], oneOf = [], sections = [] }) {
  for (const id of [...say, ...gone, ...pairs.flat(), ...oneOf.flat()]) assert.ok(els.has(id), `${where}: the shell has no #${id}`);
  for (const id of say) assert.ok(seen(id), `${where}: #${id} is blank`);
  for (const id of gone) if (seen(id) !== null) assert.ok(seen(id), `${where}: #${id} stands empty`);
  // The argument's body is empty by design when the bet card carries it, or its heading says nothing is in dispute.
  if (els.has("ck-argument")) assert.ok(seen("ck-argument") || seen("ck-bet") || /^Nothing is in dispute/.test(seen("ck-argue-heading")), `${where}: the argument section says nothing`);
  for (const [section, body] of sections) if (!seen(body)) assert.equal(seen(section), null, `${where}: #${section} stands over an empty #${body}`);
  for (const [lab, body] of pairs) if (seen(body) === null) assert.equal(seen(lab), null, `${where}: #${lab} dangles over a removed #${body}`);
  for (const group of oneOf) assert.equal(group.filter((id) => seen(id)).length, 1, `${where}: exactly one of ${group} says something`);
  for (const id of els.keys()) if (seen(id)) assert.doesNotMatch(seen(id), BAD, `${where}: #${id} leaks a placeholder`);
}

// ── the blocks, taken away one at a time (both ways a block can fail) and all at once ──
const BLOCKS = Object.keys(EDITION.blocks);
const without = (key, state) => ({ ...EDITION, blocks: { ...EDITION.blocks, [key]: { state, as_of: null, source: null, absent_text: `The ${key} is not here.`, data: null } } });
const FRONT = { say: ["ck-record", "ck-mark", "ck-mark-caption", "ck-argue-label", "ck-argue-heading", "ck-call", "ck-miss-heading", "ck-today-label", "ck-today", "ck-week-span", "ck-sheet-span", "ck-chapter-row", "ck-follow-line"], gone: ["ck-bet", "ck-coach-lines"], pairs: [["ck-coach-lines-label", "ck-coach-lines"]], oneOf: [["ck-words", "ck-words-absent"]] };
const WEEK = { say: ["ck-week-label", "ck-week", "ck-sheet-line", "ck-quotes"], pairs: [["ck-lead-section", "ck-lead-read"]], oneOf: [["ck-words", "ck-words-absent"]] };
const ALL_GONE = { ...EDITION, blocks: {} };

async function run(pageKey, page, edition, search = "") {
  mountShell(SHELL(pageKey), page, search);
  globalThis.fetch = served({ "/api/edition": edition });
  await (await import("../../site/assets/js/ck_pages.js")).mount();
}

for (const [pageKey, page, rules] of [["", "front", FRONT], ["week", "week", WEEK]]) {
  test(`${page}: the served capture is the control (every slot already says something)`, async () => {
    await run(pageKey, page, EDITION);
    check(`${page} as served`, rules);
  });
  for (const state of ["unavailable", "absent"]) {
    test(`${page}: each block gone (${state}) leaves a sentence or a clean removal, never a blank or a dangling label`, async () => {
      for (const key of BLOCKS) {
        await run(pageKey, page, without(key, state));
        check(`${page} without ${key} (${state})`, rules);
      }
    });
  }
  test(`${page}: no edition at all -> every block says it is not served`, async () => {
    await run(pageKey, page, ALL_GONE);
    check(`${page} with no blocks`, rules);
    mountShell(SHELL(pageKey), page);
    globalThis.fetch = served({ "/api/edition": null });
    await (await import("../../site/assets/js/ck_pages.js")).mount();
    check(`${page} with the edition route down`, rules);
  });
}

test("front: the weight picture says so when it has nothing to draw, and the day's weight still stands", async () => {
  await run("", "front", without("week", "unavailable"));
  assert.match(seen("ck-mark"), /not here/);
  assert.match(seen("ck-mark-caption"), /\blb\b/, "the weigh-in caption is the today block's, unaffected");
  const empty = structuredClone(EDITION);
  empty.blocks.week.data.weight_series = [];
  await run("", "front", empty);
  assert.equal(seen("ck-mark"), "No weigh-in in the last 28 days.");
});

// ── the trend page: the series it binds to, removed ──
const TREND = { say: ["ck-label", "ck-title", "ck-chart"], sections: [["ck-recent-section", "ck-recent"], ["ck-extra-section", "ck-extra"], ["ck-related-section", "ck-related"]] };
async function trend(search, overrides) {
  mountShell(SHELL("trend"), "trend", search);
  globalThis.fetch = served(overrides);
  await (await import("../../site/assets/js/ck_depth.js")).mount();
}
const EMPTY = { "/api/pulse_history": { pulse_history: [] }, "/api/workouts": { workouts: [] }, "/api/training_overview": { daily_modality_minutes_30d: [] }, "/api/nutrition_overview": { nutrition: {}, nutrition_trend: [] }, "/api/frequent_meals": { meals: [] } };
const DOWN = Object.fromEntries(Object.keys(EMPTY).map((k) => [k, null]));
for (const m of ["weight", "sleep", "recovery", "steps", "training", "protein", "calories", "carbs", "fat"]) {
  test(`trend ${m}: the served capture, then an empty series, then the route down, each leave a sentence`, async () => {
    for (const [name, overrides] of [["as served", {}], ["empty", EMPTY], ["route down", DOWN]]) {
      await trend(`?m=${m}`, overrides);
      check(`trend ${m} ${name}`, TREND);
      if (name !== "as served") {
        assert.equal(seen("ck-chart"), "Nothing has been recorded for this yet.", `trend ${m} ${name}`);
        assert.equal(seen("ck-recent-section"), null, `trend ${m} ${name}: the empty day-by-day section leaves with its heading`);
      }
    }
  });
}
test("trend: a lift with no sessions, the index, and an unknown measure each say what they are", async () => {
  await trend("?m=lift&x=Nothing%20Lifted", EMPTY);
  check("trend lift with no sessions", TREND);
  await trend("", EMPTY);
  check("trend index", { say: ["ck-title", "ck-chart"] });
  await trend("?m=bogus", EMPTY);
  assert.match(seen("ck-about"), /does not name a measure/);
});
