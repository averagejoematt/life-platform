// The Coaching Room's switches (CR1, owner ruling 2026-11-08: "Coaching Room remains NO-GO for public
// publication, but that should not prevent private implementation, prototyping or testing"; owner ruling 2026-11-09:
// "CR1 and the 'wrong this month' experience should launch ahead of CR2 and CR3").
//
// ONE helper, read by every gated piece: the route injection in astro.config.mjs, the room entries on /system/
// (components/RoomEntry.astro), on each coach page (components/CoachRoomEntry.astro, CR2) and on each disagreement
// page (components/DisagreementRoomEntry.astro, CR3), the room pages under src/room/, scripts/postbuild.mjs, the
// audits, and the snapshot producers' Python twin (scripts/publish_snapshot_calibration.py::room_scope).
//
// TWO switches, one scope:
//   * WEB_ROOM — the PRIVATE, local switch. "1" = the whole room (CR1 + CR2 + CR3); "cr1" = CR1 only (the
//     calibration page, "wrong this month" and the /system/ entry). A private build carries the private banner
//     (ROOM_PRIVATE_MARKER) and noindex on every room page, never rewrites the committed owned_paths.json /
//     reach.json, and scripts/check_www_build.py's scan (the deploy runs it with --scan-only) refuses it.
//   * `room_public` in www/owned_paths.json — the COMMITTED, production switch: "off", "cr1" or "cr2". Each launch is
//     one reviewed merge: "cr1" (owner GO 2026-11-10) publishes CR1 — indexed, in the sitemap and in owned_paths.json;
//     "cr2" (owner GO 2026-11-11, second message) publishes CR1 + CR2 (each coach's record page and the entry on each
//     coach page). Neither ever builds a CR3 page, and the deploy scan refuses one whatever the switch says.
//   WEB_ROOM, when it is "1", "cr1" or "cr2", wins (a private look); otherwise the committed switch decides.
//
// With both off the build is BYTE-IDENTICAL to a build without the room: no page, no JSON, no sitemap entry, no owned
// path, no chunk. The room pages live OUTSIDE src/pages/ (Astro and postbuild never see them) and are injected only
// for the scope that is on. Proven by tests/room.test.mjs and by a recursive dist diff against main.
import { existsSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

/** The private switch. Only the literals "1" (all), "cr1" (CR1 only) and "cr2" (CR1 + CR2) turn anything on. */
export const ROOM_ENV = "WEB_ROOM";
/** The committed production switch's key in www/owned_paths.json, and the values it may take. */
export const ROOM_PUBLIC_KEY = "room_public";
export const ROOM_PUBLIC_VALUES = ["off", "cr1", "cr2"];
/** The scopes a switch can name, narrowest first ("all" = the whole room, private builds only). */
const PRIVATE_SCOPES = { 1: "all", cr1: "cr1", cr2: "cr2" };

/** The routes the room adds when the switch is on (pattern → entrypoint, relative to www/). A `[param]` segment in
 *  `path` stands for one URL segment (CR2's per-coach record); every check reads it through roomPathPattern().
 *  `release` is the launch a route belongs to: "cr1" ships with the calibration page (owner, 2026-11-09: "wrong this
 *  month" launches with CR1); "cr2" ships with the committed "cr2" (owner GO 2026-11-11, second message); "cr3" is
 *  built only by WEB_ROOM=1 and never published by the committed switch. */
export const ROOM_ROUTES = [
  { pattern: "/system/calibration", entrypoint: "./src/room/calibration.astro", path: "/system/calibration/", release: "cr1" },
  { pattern: "/system/coaches/[id]/record", entrypoint: "./src/room/coach-record.astro", path: "/system/coaches/[id]/record/", release: "cr2" },
  // CR3: the docket (every standing disagreement) and one page per entry
  { pattern: "/system/docket", entrypoint: "./src/room/docket.astro", path: "/system/docket/", release: "cr3" },
  { pattern: "/system/docket/[id]", entrypoint: "./src/room/docket-entry.astro", path: "/system/docket/[id]/", release: "cr3" },
  // "wrong this month", the ledger preset — built in CR3, released with CR1 (owner, 2026-11-09)
  { pattern: "/system/ledger/refuted", entrypoint: "./src/room/refuted.astro", path: "/system/ledger/refuted/", release: "cr1" },
];

/** The routes a scope builds: "all" = every room route, "cr1" = the CR1 release, "cr2" = CR1 + CR2, else none. */
export function scopeRoutes(scope) {
  if (scope === "all") return [...ROOM_ROUTES];
  if (scope === "cr1") return ROOM_ROUTES.filter((r) => r.release === "cr1");
  if (scope === "cr2") return ROOM_ROUTES.filter((r) => r.release === "cr1" || r.release === "cr2");
  return [];
}

/** The attribute every room-rendered element carries; the dist scans look for it (and for ROOM_DATA_KEYS). */
export const ROOM_MARKER = "data-room";
/** The marker values a published CR1 build may carry (the calibration page, "wrong this month", the /system/ entry);
 *  every other value (coach-record, coach-entry, docket, docket-entry, disagreement-entry) is CR2/CR3 output. */
export const CR1_MARKERS = ["calibration", "refuted", "entry"];
/** The marker values CR2 adds (each coach's record page and the entry on each coach page); the rest are CR3's. */
export const CR2_MARKERS = ["coach-record", "coach-entry"];
/** The marker values a published build may carry under each committed switch value. */
export function publishedMarkers(committed) {
  if (committed === "cr2") return [...CR1_MARKERS, ...CR2_MARKERS];
  if (committed === "cr1") return [...CR1_MARKERS];
  return [];
}
/** The private-build banner's attribute: on every room page of a WEB_ROOM build, never on a published one. A dist that
 *  carries it is a private build and is refused by the deploy scan whatever the committed switch says. */
export const ROOM_PRIVATE_MARKER = "data-room-private";

/** Keys that exist only in the room's data files; none may appear in a flag-off dist. CR1's first, then CR2/CR3's. */
export const CR1_DATA_KEYS = ["prereg_seal", "reliability_bins", "brier_skill", "interval_forecasts", "weekly_prescriptions"];
/** Keys only CR2 data carries (the coach profiles, the approved historical words, the public-safe brief). */
export const CR2_DATA_KEYS = [
  "stance_history",
  "commitment_counts",
  "voice_fidelity",
  // owner ruling 2026-11-09 (third, D + E): the approved historical words and the public-safe brief, CR2 only
  "approved_words",
  "public_briefs",
];
/** Keys only CR3 data carries (the docket): none may appear in a CR1 or a CR2 build. */
export const CR3_DATA_KEYS = ["docket_positions", "docket_entries", "docket_counts", "concession_withheld"];
/** Keys only CR2 / CR3 data carries: none may appear anywhere in a CR1-only build either. */
export const CR23_DATA_KEYS = [...CR2_DATA_KEYS, ...CR3_DATA_KEYS];
export const ROOM_DATA_KEYS = [...CR1_DATA_KEYS, ...CR23_DATA_KEYS];

/** The room's data files in the snapshot — written by the producers ONLY when a scope is on, never in a dist.
 *  calibration.json is CR1's (any scope); coach_room.json is CR2/CR3's (scope "all" only). */
export const ROOM_DATA_FILES = ["calibration.json", "coach_room.json"];
export const CR23_DATA_FILES = ["coach_room.json"];

/** Every regex metacharacter escaped, backslash included, so a path is matched literally. */
const escapeRx = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/** The source of a RegExp for one room path: literal characters, and a `[param]` segment = exactly one URL segment. */
export function roomPathPattern(path) {
  return path
    .split(/(\[[^\]]+\])/)
    .map((part) => (/^\[[^\]]+\]$/.test(part) ? "[^/]+" : escapeRx(part)))
    .join("");
}

/** Is this URL path (with or without a base prefix in front) a room page? */
export function isRoomPath(pathname) {
  return ROOM_ROUTES.some((r) => new RegExp(`${roomPathPattern(r.path)}$`).test(pathname));
}

/** The committed switch as written in www/owned_paths.json: "cr1" or "cr2", else "off" (missing, unreadable or any
 *  other value is off — fail closed). Read from the build's working directory (www/, where every npm script runs), else beside
 *  this file. */
export function committedRoomPublic(file = null) {
  const candidates = file
    ? [file]
    : [join(process.cwd(), "owned_paths.json"), resolve(dirname(fileURLToPath(import.meta.url)), "..", "..", "owned_paths.json")];
  for (const f of candidates) {
    if (!existsSync(f)) continue;
    try {
      const v = JSON.parse(readFileSync(f, "utf8"))[ROOM_PUBLIC_KEY];
      return v === "cr1" || v === "cr2" ? v : "off";
    } catch {
      return "off";
    }
  }
  return "off";
}

/** Is WEB_ROOM set to a value that turns the room on (a PRIVATE build)? */
export function roomPrivate(env = process.env) {
  const v = env ? env[ROOM_ENV] : undefined;
  return typeof v === "string" && Object.prototype.hasOwnProperty.call(PRIVATE_SCOPES, v);
}

/** The room's scope for this build: "all" | "cr2" | "cr1" | "off". WEB_ROOM ("1" / "cr1" / "cr2") wins; else the
 *  committed switch. */
export function roomScope(env = process.env, committed = committedRoomPublic()) {
  if (roomPrivate(env)) return PRIVATE_SCOPES[env[ROOM_ENV]];
  return committed === "cr1" || committed === "cr2" ? committed : "off";
}

/** Is this a PUBLISHED room build (the committed switch, no private override)? A private build carries the banner. */
export function roomPublic(env = process.env, committed = committedRoomPublic()) {
  return roomScope(env, committed) !== "off" && !roomPrivate(env);
}

/** Is CR2 on for this build (the committed "cr2", WEB_ROOM=cr2 or the whole room)? */
export function roomCr2(env = process.env, committed = committedRoomPublic()) {
  const s = roomScope(env, committed);
  return s === "cr2" || s === "all";
}

/** Is any part of the Coaching Room on for this build (CR1 at least)? */
export function roomEnabled(env = process.env, committed = committedRoomPublic()) {
  return roomScope(env, committed) !== "off";
}

/** Is the WHOLE room on (CR2 + CR3 as well)? Only WEB_ROOM=1 — the committed switch never publishes CR3. */
export function roomAll(env = process.env, committed = committedRoomPublic()) {
  return roomScope(env, committed) === "all";
}

/** The Astro integration that injects the routes of the scope that is on — and nothing at all when off. */
export function roomIntegration(env = process.env, committed = committedRoomPublic()) {
  return {
    name: "coaching-room-dark",
    hooks: {
      "astro:config:setup": ({ injectRoute }) => {
        for (const r of scopeRoutes(roomScope(env, committed))) injectRoute({ pattern: r.pattern, entrypoint: r.entrypoint, prerender: true });
      },
    },
  };
}

/** Is this URL path a room page the committed switch publishes, on a published build? */
export function isPublishedRoomPath(pathname, env = process.env, committed = committedRoomPublic()) {
  if (!roomPublic(env, committed)) return false;
  return scopeRoutes(roomScope(env, committed)).some((r) => new RegExp(`${roomPathPattern(r.path)}$`).test(pathname));
}

/** The sitemap filter (true = keep): a room path is listed only when the committed switch publishes it on a published
 *  build; a private build never lists one. Identity on every page the room does not own. */
export function notRoomPage(url, env = process.env, committed = committedRoomPublic()) {
  const path = new URL(url, "https://averagejoematt.com").pathname;
  return !isRoomPath(path) || isPublishedRoomPath(path, env, committed);
}
