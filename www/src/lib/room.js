// The Coaching Room's dark-launch switch (CR1, owner ruling 2026-11-08: "Coaching Room remains NO-GO for public
// publication, but that should not prevent private implementation, prototyping or testing").
//
// ONE helper, read by every gated piece: the route injection in astro.config.mjs, the room entry on /system/
// (components/RoomEntry.astro), the room pages under src/room/, scripts/postbuild.mjs (which refuses to rewrite the
// committed owned_paths.json / reach.json from a room build) and the snapshot producer's Python twin
// (scripts/publish_snapshot_calibration.py::room_enabled — the same variable, the same literal "1").
//
// With WEB_ROOM unset the build is BYTE-IDENTICAL to a build without the room: no page, no JSON, no sitemap entry,
// no owned path, no chunk. The room pages live OUTSIDE src/pages/ (Astro and postbuild never see them) and are
// injected only when the switch is on. Proven by tests/room.test.mjs and by a recursive dist diff against main.
//
// A room build is for local, private review only. It is never deployed: scripts/check_www_build.py's scan (the
// deploy path runs it with --scan-only) refuses a dist that carries any room marker.

/** The environment variable. Only the literal "1" turns the room on; anything else is off. */
export const ROOM_ENV = "WEB_ROOM";

/** The routes the room adds when the switch is on (pattern → entrypoint, relative to www/). */
export const ROOM_ROUTES = [{ pattern: "/system/calibration", entrypoint: "./src/room/calibration.astro", path: "/system/calibration/" }];

/** The attribute every room-rendered element carries; the dist scans look for it (and for ROOM_DATA_KEYS). */
export const ROOM_MARKER = "data-room";

/** Keys that exist only in the room's data file (calibration.json); none may appear in a flag-off dist. */
export const ROOM_DATA_KEYS = ["prereg_seal", "reliability_bins", "brier_skill", "interval_forecasts", "weekly_prescriptions"];

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
  const path = new URL(url, "https://averagejoematt.com").pathname;
  return !ROOM_ROUTES.some((r) => path === r.path || path.endsWith(r.path));
}
