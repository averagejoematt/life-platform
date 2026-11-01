// Read-side helpers over the collections: one place that loads every collection, builds
// the relationship index once per build, and exposes the small vocabulary the templates
// use. Templates never import astro:content directly for the index — they import this.
import { getCollection } from "astro:content";

import { buildIndex, COLLECTION_OF, connected } from "./edges.js";

let _cache = null;

// Astro's `reference()` validates a cross-collection id at build and then hands the
// template `{ collection, id }`. The templates want the id string (one vocabulary for
// `all.get(type, id)` and the edge index), so the reference fields are flattened here —
// the validation has already happened by the time this runs.
const REFERENCE_FIELDS = ["coach_id", "coach_a", "coach_b"];
function plainIds(data) {
  const o = { ...data };
  for (const k of REFERENCE_FIELDS) {
    if (o[k] && typeof o[k] === "object" && "id" in o[k]) o[k] = o[k].id;
  }
  return o;
}

/** Every object of every collection, plus the index. Built once per build process. */
export async function loadAll() {
  if (_cache) return _cache;
  const byType = {};
  const objects = [];
  for (const [type, collection] of Object.entries(COLLECTION_OF)) {
    const entries = await getCollection(collection);
    byType[type] = entries.map((e) => plainIds(e.data));
    for (const o of byType[type]) objects.push(o);
  }
  const index = buildIndex(objects);
  const lookup = new Map(objects.map((o) => [`${o.type}:${o.id}`, o]));
  _cache = { byType, objects, index, get: (type, id) => lookup.get(`${type}:${id}`) || null };
  return _cache;
}

/** The Connected rail for one object, resolved to the objects themselves. */
export async function connectedTo(type, id, opts) {
  const all = await loadAll();
  const { items, total, more } = connected(all.index, type, id, opts);
  return {
    total,
    more,
    items: items.map((e) => ({ ...e, object: all.get(e.type, e.id) })).filter((e) => e.object),
  };
}

/** The newest edition (the dated document the front page reads). */
export async function latestEdition() {
  const all = await loadAll();
  const eds = [...all.byType.edition].sort((a, b) => (a.as_of < b.as_of ? 1 : -1));
  return eds[0] || null;
}

/** "Day 56" from the edition, or nothing — never computed from the wall clock. */
export function dayLine(edition) {
  if (!edition || edition.day_n == null) return null;
  return `Day ${edition.day_n}`;
}
