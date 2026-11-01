// The relationship index: dangling edges fail, inverse edges resolve, the rail is ordered
// and capped. node --test (zero dependencies), run from www/ as `npm test`.
import assert from "node:assert/strict";
import { test } from "node:test";

import { buildIndex, connected, COLLECTION_OF, RAIL_ORDER } from "../src/lib/edges.js";

const objects = [
  { id: "sleep_coach", type: "coach", edges: [] },
  { id: "deep_pct", type: "metric", edges: [{ type: "source", id: "whoop" }] },
  { id: "whoop", type: "source", edges: [] },
  { id: "p1", type: "prediction", edges: [{ type: "coach", id: "sleep_coach", rel: "made_by" }, { type: "metric", id: "deep_pct" }] },
  { id: "p2", type: "prediction", edges: [{ type: "coach", id: "sleep_coach" }] },
  { id: "week-06", type: "chapter", edges: [{ type: "prediction", id: "p1" }] },
];

test("every object type has a collection and a rail position", () => {
  for (const t of Object.keys(COLLECTION_OF)) assert.ok(RAIL_ORDER.includes(t), `${t} missing from RAIL_ORDER`);
  assert.equal(new Set(Object.values(COLLECTION_OF)).size, Object.keys(COLLECTION_OF).length);
});

test("a dangling edge is a build failure, naming the edge", () => {
  assert.throws(() => buildIndex([{ id: "x", type: "prediction", edges: [{ type: "coach", id: "nobody" }] }]), /dangling edge\(s\): prediction:x -> coach:nobody/);
});

test("inverse edges resolve: the coach sees the predictions that point at it", () => {
  const index = buildIndex(objects);
  const rail = connected(index, "coach", "sleep_coach");
  assert.deepEqual(
    rail.items.map((e) => `${e.type}:${e.id}:${e.direction}`),
    ["prediction:p1:in", "prediction:p2:in"],
  );
  assert.equal(rail.total, 2);
});

test("both directions, de-duplicated, ordered by RAIL_ORDER then id", () => {
  const index = buildIndex(objects);
  const rail = connected(index, "prediction", "p1");
  // out: coach, metric · in: chapter — the story first, the machine last
  assert.deepEqual(
    rail.items.map((e) => e.type),
    ["chapter", "metric", "coach"],
  );
});

test("the cap keeps a popular object short and counts the rest", () => {
  const many = [{ id: "c", type: "coach", edges: [] }];
  for (let i = 0; i < 20; i++) many.push({ id: `p${String(i).padStart(2, "0")}`, type: "prediction", edges: [{ type: "coach", id: "c" }] });
  const rail = connected(buildIndex(many), "coach", "c", { cap: 7 });
  assert.equal(rail.items.length, 7);
  assert.equal(rail.total, 20);
  assert.equal(rail.more, 13);
  assert.equal(rail.items[0].id, "p00");
});

test("an object never lists itself", () => {
  const index = buildIndex([{ id: "a", type: "metric", edges: [{ type: "metric", id: "a" }] }]);
  assert.equal(connected(index, "metric", "a").total, 0);
});
