// The Coaching Room's dark-launch switch (CR1, owner ruling 2026-11-08: "Coaching Room remains NO-GO for public
// publication, but that should not prevent private implementation, prototyping or testing").
//
// ONE helper, read by every gated piece: the route injection in astro.config.mjs, the room entries on /system/
// (components/RoomEntry.astro), on each coach page (components/CoachRoomEntry.astro, CR2) and on each disagreement
// page (components/DisagreementRoomEntry.astro, CR3), the room pages under
// src/room/, scripts/postbuild.mjs (which refuses to rewrite the committed owned_paths.json / reach.json from a room
// build) and the snapshot producers' Python twin (scripts/publish_snapshot_calibration.py::room_enabled — the same
// variable, the same literal "1"; scripts/publish_snapshot_coach_room.py reads it from there).
//
// With WEB_ROOM unset the build is BYTE-IDENTICAL to a build without the room: no page, no JSON, no sitemap entry,
// no owned path, no chunk. The room pages live OUTSIDE src/pages/ (Astro and postbuild never see them) and are
// injected only when the switch is on. Proven by tests/room.test.mjs and by a recursive dist diff against main.
//
// A room build is for local, private review only. It is never deployed: scripts/check_www_build.py's scan (the
// deploy path runs it with --scan-only) refuses a dist that carries any room marker.

/** The environment variable. Only the literal "1" turns the room on; anything else is off. */
export const ROOM_ENV = "WEB_ROOM";

/** The routes the room adds when the switch is on (pattern → entrypoint, relative to www/). A `[param]` segment in
 *  `path` stands for one URL segment (CR2's per-coach record); every check reads it through roomPathPattern(). */
export const ROOM_ROUTES = [
  { pattern: "/system/calibration", entrypoint: "./src/room/calibration.astro", path: "/system/calibration/" },
  { pattern: "/system/coaches/[id]/record", entrypoint: "./src/room/coach-record.astro", path: "/system/coaches/[id]/record/" },
  // CR3: the docket (every standing disagreement), one page per entry, and the "refuted this month" ledger preset
  { pattern: "/system/docket", entrypoint: "./src/room/docket.astro", path: "/system/docket/" },
  { pattern: "/system/docket/[id]", entrypoint: "./src/room/docket-entry.astro", path: "/system/docket/[id]/" },
  { pattern: "/system/ledger/refuted", entrypoint: "./src/room/refuted.astro", path: "/system/ledger/refuted/" },
];

/** The attribute every room-rendered element carries; the dist scans look for it (and for ROOM_DATA_KEYS). */
export const ROOM_MARKER = "data-room";

/** Keys that exist only in the room's data files; none may appear in a flag-off dist. */
export const ROOM_DATA_KEYS = [
  "prereg_seal",
  "reliability_bins",
  "brier_skill",
  "interval_forecasts",
  "weekly_prescriptions",
  "stance_history",
  "commitment_counts",
  "docket_positions",
  "voice_fidelity",
  "docket_entries",
  "docket_counts",
  "concession_withheld",
];

/** The room's data files in the snapshot — written by the producers ONLY on a WEB_ROOM=1 export, never in a dist. */
export const ROOM_DATA_FILES = ["calibration.json", "coach_room.json"];

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

/** Is the Coaching Room switched on for this build? */
export function roomEnabled(env = process.env) {
  return Boolean(env) && env[ROOM_ENV] === "1";
}

/**
 * The Astro integration that injects the room's routes — and nothing at all when the switch is off. The sitemap
 * integration is also told to drop every room path, so even a room build never lists one.
 */
export function roomIntegration(env = process.env) {
  return {
    name: "coaching-room-dark",
    hooks: {
      "astro:config:setup": ({ injectRoute }) => {
        if (!roomEnabled(env)) return;
        for (const r of ROOM_ROUTES) injectRoute({ pattern: r.pattern, entrypoint: r.entrypoint, prerender: true });
      },
    },
  };
}

/** The sitemap filter: a room path is never listed (true = keep). Identity on every page the room does not own. */
export function notRoomPage(url) {
  return !isRoomPath(new URL(url, "https://averagejoematt.com").pathname);
}
