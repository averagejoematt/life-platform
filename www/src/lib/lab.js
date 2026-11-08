// The Laboratory's dark-launch switch (L1, owner brief 2026-11-08: "Proceed with private Laboratory prototypes using
// existing public-safe experiments, hypotheses and findings. Keep interactive challenge actions disabled until their
// record-writing behavior is safe.").
//
// The same pattern as the Coaching Room (src/lib/room.js), as a SEPARATE switch: ONE helper, read by every gated
// piece — the route injection in astro.config.mjs, the Lab entry on /data/ (components/LabEntry.astro), the Lab pages
// under src/lab/, scripts/postbuild.mjs (which refuses to rewrite the committed owned_paths.json / reach.json from a
// Lab build) and the snapshot producer's Python twin (scripts/publish_snapshot_lab.py::lab_enabled — the same
// variable, the same literal "1").
//
// With WEB_LAB unset the build is BYTE-IDENTICAL to a build without the Lab: no page, no JSON, no sitemap entry, no
// owned path, no chunk, no marker. Proven by tests/lab.test.mjs (+ scripts/lab_audit.mjs) and by a recursive dist
// diff against main. A Lab build is for local, private review only; scripts/check_www_build.py's scan (the deploy
// runs it with --scan-only) refuses a dist that carries any Lab output.

/** The environment variable. Only the literal "1" turns the Lab on; anything else is off. */
export const LAB_ENV = "WEB_LAB";

/**
 * The routes the Lab adds when the switch is on (pattern → entrypoint, relative to www/). `path` is the directory
 * every page of the route lives under — the dist scans treat anything under it as Lab output.
 */
export const LAB_ROUTES = [
  { pattern: "/data/lab", entrypoint: "./src/lab/lab-index.astro", path: "/data/lab/" },
  { pattern: "/data/lab/experiments/[id]", entrypoint: "./src/lab/lab-experiment.astro", path: "/data/lab/experiments/" },
  { pattern: "/data/lab/tests/[id]", entrypoint: "./src/lab/lab-test.astro", path: "/data/lab/tests/" },
  { pattern: "/data/lab/protocols", entrypoint: "./src/lab/lab-protocols.astro", path: "/data/lab/protocols/" },
];

/** The directory every Lab page lives under (the first route's path). */
export const LAB_ROOT = "/data/lab/";

/** The attribute every Lab-rendered element carries; the dist scans look for it (and for LAB_DATA_KEYS). */
export const LAB_MARKER = "data-lab";

/** The Lab's data file in the snapshot (written by the producer only on a WEB_LAB=1 export). */
export const LAB_DATA_FILE = "lab.json";

/** Keys that exist only in the Lab's data file; none may appear in a flag-off dist. */
export const LAB_DATA_KEYS = ["lab_tests", "lab_protocols", "lab_findings", "condition_series", "outcome_series"];

/** Is the Laboratory switched on for this build? */
export function labEnabled(env = process.env) {
  return Boolean(env) && env[LAB_ENV] === "1";
}

/** The Astro integration that injects the Lab's routes — and nothing at all when the switch is off. */
export function labIntegration(env = process.env) {
  return {
    name: "laboratory-dark",
    hooks: {
      "astro:config:setup": ({ injectRoute }) => {
        if (!labEnabled(env)) return;
        for (const r of LAB_ROUTES) injectRoute({ pattern: r.pattern, entrypoint: r.entrypoint, prerender: true });
      },
    },
  };
}

/** The sitemap filter: a Lab path is never listed (true = keep). Identity on every page the Lab does not own. */
export function notLabPage(url) {
  const path = new URL(url, "https://averagejoematt.com").pathname;
  return !(path.startsWith(LAB_ROOT) || path.includes(LAB_ROOT));
}
