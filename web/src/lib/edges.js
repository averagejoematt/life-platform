// The relationship index — one canonical object, many discovery paths (plan §E2).
//
// Edges are stored once, on the object that knows them. This module inverts them at
// build time so a page can ask "what is connected to me?" and get both directions
// without any object holding a copy of another. Pure functions, no Astro imports, so
// `node --test` can prove them (tests/edges.test.mjs).

/** Collection name per object type — the one place the plural lives. */
export const COLLECTION_OF = Object.freeze({
  chapter: "chapters",
  episode: "episodes",
  essay: "essays",
  metric: "metrics",
  insight: "insights",
  experiment: "experiments",
  prediction: "predictions",
  disagreement: "disagreements",
  coach: "coaches",
  source: "sources",
  method: "methods",
  edition: "editions",
});

/** The order the Connected rail lists types in: the story first, the machine last. */
export const RAIL_ORDER = Object.freeze([
  "chapter",
  "episode",
  "essay",
  "metric",
  "insight",
  "experiment",
  "disagreement",
  "prediction",
  "coach",
  "source",
  "method",
  "edition",
]);

const key = (type, id) => `${type}:${id}`;

/**
 * Build the index from every object in the snapshot.
 * @param {Array<{id:string,type:string,edges:Array<{type:string,id:string,rel?:string}>}>} objects
 * @returns {{out: Map<string, Array>, in: Map<string, Array>, has: (type:string,id:string)=>boolean}}
 */
export function buildIndex(objects) {
  const known = new Set();
  for (const o of objects) known.add(key(o.type, o.id));
  const out = new Map();
  const inbound = new Map();
  const dangling = [];
  for (const o of objects) {
    const from = key(o.type, o.id);
    for (const e of o.edges || []) {
      const to = key(e.type, e.id);
      if (!known.has(to)) {
        dangling.push(`${from} -> ${to}`);
        continue;
      }
      if (!out.has(from)) out.set(from, []);
      out.get(from).push({ type: e.type, id: e.id, rel: e.rel || null, direction: "out" });
      if (!inbound.has(to)) inbound.set(to, []);
      inbound.get(to).push({ type: o.type, id: o.id, rel: e.rel || null, direction: "in" });
    }
  }
  if (dangling.length) {
    // A dangling edge is a build failure, not a missing link (CHARTER derivation guard).
    throw new Error(`dangling edge(s): ${dangling.slice(0, 10).join("; ")}${dangling.length > 10 ? ` (+${dangling.length - 10})` : ""}`);
  }
  return { out, in: inbound, has: (type, id) => known.has(key(type, id)) };
}

/**
 * Everything connected to one object: outgoing and incoming, de-duplicated, ordered by
 * RAIL_ORDER then id, capped so a popular object (a coach with 70 predictions) shows a
 * handful and a count, never the whole ledger.
 * @param {ReturnType<typeof buildIndex>} index
 * @param {string} type
 * @param {string} id
 * @param {{cap?: number}} [opts]
 */
export function connected(index, type, id, opts = {}) {
  const cap = opts.cap ?? 7;
  const k = key(type, id);
  const seen = new Set();
  const all = [];
  for (const e of [...(index.out.get(k) || []), ...(index.in.get(k) || [])]) {
    const ek = key(e.type, e.id);
    if (ek === k || seen.has(ek)) continue;
    seen.add(ek);
    all.push(e);
  }
  all.sort((a, b) => {
    const ra = RAIL_ORDER.indexOf(a.type);
    const rb = RAIL_ORDER.indexOf(b.type);
    if (ra !== rb) return ra - rb;
    return a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
  });
  return { items: all.slice(0, cap), total: all.length, more: Math.max(0, all.length - cap) };
}
