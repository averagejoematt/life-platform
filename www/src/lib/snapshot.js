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

// ── data files beside the collections (not collections: one JSON per metric series, one
// pairs file). Read once per build from the snapshot directory the collections load from.
// Resolved from the build's working directory (`astro build` runs in www/, as the content
// loaders' paths do) — NOT from import.meta.url, which points into the bundled output.
// A missing directory or file is a broken export, not an empty data room: the build fails.
import { readFile, readdir } from "node:fs/promises";
import { join, resolve } from "node:path";

const SNAPSHOT_DIR = resolve(process.cwd(), "content", "snapshot");
let _series = null;
let _pairs = null;

/** Every metric series in the snapshot, keyed by metric id. */
export async function loadSeries() {
  if (_series) return _series;
  const out = {};
  const dir = join(SNAPSHOT_DIR, "series");
  const names = await readdir(dir); // throws when the exporter did not write series/
  for (const name of names) {
    if (!name.endsWith(".json")) continue;
    out[name.slice(0, -5)] = JSON.parse(await readFile(join(dir, name), "utf8"));
  }
  _series = out;
  return out;
}

/** The precomputed pair statistics (the platform's numbers; the island reads, never computes). */
export async function loadPairs() {
  if (_pairs) return _pairs;
  _pairs = JSON.parse(await readFile(join(SNAPSHOT_DIR, "pairs.json"), "utf8")); // throws when absent
  return _pairs;
}

let _journey = null;
/** The Journey's data file (#5579): the platform's published weight-story figures, or its absent record. */
export async function loadJourney() {
  if (_journey) return _journey;
  _journey = JSON.parse(await readFile(join(SNAPSHOT_DIR, "journey.json"), "utf8")); // throws when absent: the exporter always writes it
  return _journey;
}

