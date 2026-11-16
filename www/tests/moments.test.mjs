// The moments that explain it (2026-11-14, sprint III): chosen by rule from published objects; a moment whose evidence
// is absent is not shown, a chapter's words are its approved dek verbatim, and no claim is made the data cannot carry.
import assert from "node:assert/strict";
import { test } from "node:test";

import { heldEveryWeek, moments } from "../src/lib/moments.js";

const ch = (o) => ({ status: "published", week_label: `Week ${o.week}`, ...o });
const chapters = [
  ch({ id: "week-05", week: 2, title: "Eight Pounds and a Flag", excerpt: "He weighed 318.9 pounds on Day 10.", covers_start: "2026-09-09", covers_end: "2026-09-15", week_start: "2026-09-13", week_end: "2026-09-19" }),
  ch({ id: "week-08", week: 5, title: "Park's Blind Spot", excerpt: "Recovery at 98%.", covers_start: "2026-09-30", covers_end: "2026-10-06", week_start: "2026-10-04", week_end: "2026-10-10" }),
  { id: "program-week-07", status: "skipped", week: 7, title: "Week 7", week_start: "2026-10-18", week_end: "2026-10-24" },
  ch({ id: "week-12", week: 10, title: "The Rate Flag", excerpt: "A 5.2-pound week.", covers_start: "2026-11-04", covers_end: "2026-11-10", week_start: "2026-11-08", week_end: "2026-11-14" }),
];
const journey = { start_date: "2026-09-06", start_weight_lbs: 327.3, goal_weight_lbs: 185, rungs: [{ lb: 310, date: "2026-10-06", days: 24 }, { lb: 300, date: "2026-10-21", days: 15 }] };
const paths = { dayPath: (d) => `/data/day/${d}/`, chapterPath: (c) => `/story/${c.id}/`, coachPath: (id) => `/system/coaches/${id}/` };
const coaches = [{ id: "sleep_coach", name: "Lisa Park" }, { id: "physical_coach", name: "Max Reyes" }];

test("every moment carries evidence; quotations are the published deks verbatim", () => {
  const m = moments({ journey, chapters, coaches, lead: { n: 73, k: 37, baseline: { right: 40 }, sign: { words: "no detectable difference" } }, finding: null, ...paths });
  assert.deepEqual(m.map((x) => x.key), ["start", "first-flag", "blind-spot", "under-300", "rate-flag", "versus-guess"]);
  for (const x of m) assert.ok(x.links.length > 0, x.key);
  assert.equal(m[1].quote.text, chapters[0].excerpt);
  assert.equal(m[4].quote.text, chapters[3].excerpt);
  assert.match(m[2].links[1].label, /Lisa Park/, "the coach is the one the title names");
});

test("a chapter's moment carries its chapter, placed on the line at the last of its days (#6081)", () => {
  const m = moments({ journey, chapters, coaches, ...paths });
  for (const x of m.filter((y) => ["first-flag", "blind-spot", "rate-flag"].includes(y.key))) {
    assert.ok(x.chapter && x.chapter.status === "published", x.key);
    assert.equal(x.date, x.chapter.covers_end, `${x.key}: the line's tick is the last covered day`);
  }
  assert.equal(m.find((x) => x.key === "start").chapter, undefined);
});

test("the week-without-a-chapter line is computed, never assumed", () => {
  const skipped = moments({ journey, chapters, coaches, ...paths }).find((x) => x.key === "under-300");
  assert.match(skipped.body, /No chapter was published for that week/);
  const withChapter = chapters.map((c) => (c.week === 7 ? { ...c, status: "published", title: "Under Three Hundred", excerpt: "x" } : c));
  const pub = moments({ journey, chapters: withChapter, coaches, ...paths }).find((x) => x.key === "under-300");
  assert.doesNotMatch(pub.body, /No chapter/);
  assert.ok(pub.links.some((l) => l.path === "/story/program-week-07/"));
});

test("absent evidence shrinks the list; nothing is filled in", () => {
  assert.deepEqual(moments({ journey: null, chapters: [], coaches, lead: null, finding: null, ...paths }), []);
  const noLead = moments({ journey, chapters, coaches, lead: null, ...paths });
  assert.ok(!noLead.some((x) => x.key === "versus-guess"));
});

test("a relationship 'held every week' only when every run listed it", () => {
  const t = (f) => `${f.metric_a} × ${f.metric_b}`;
  assert.equal(heldEveryWeek([{ metric_a: "A", metric_b: "B", r: 0.6, seen: 3, of: 4 }], t), null);
  const f = heldEveryWeek([{ metric_a: "HRV", metric_b: "Recovery", r: 0.65, seen: 4, of: 4 }], t);
  assert.equal(f.title, "HRV × Recovery");
  assert.equal(f.r, "+0.65");
});
