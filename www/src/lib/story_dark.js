// The Human Story's dark-launch switch (HS1, owner brief 2026-11-08: "Proceed with the Human Story timeline and episode
// index using only already-approved published material. Held installments and audio remain excluded.").
//
// The same pattern as the Coaching Room (src/lib/room.js, CR1), as a SEPARATE switch: ONE helper, read by every gated
// piece — the route injection in astro.config.mjs, the "story so far" entry on /story/ (components/StoryEntry.astro), the
// pages under src/story/, scripts/postbuild.mjs (which leaves the committed owned_paths.json / reach.json alone on a dark
// build) and the snapshot producer's Python twin (scripts/publish_snapshot_story.py::story_enabled — the same variable,
// the same literal "1").
//
// With WEB_STORY unset the build is BYTE-IDENTICAL to a build without the Human Story: no page, no JSON, no sitemap
// entry, no owned path, no chunk, no marker. Proven by tests/story_dark.test.mjs (scripts/story_audit.mjs) and by a
// recursive dist diff against main. A WEB_STORY=1 build is for local, private review only and is never deployed:
// scripts/check_www_build.py's scan (the deploy runs it with --scan-only) refuses a dist that carries any story output.

/** The environment variable. Only the literal "1" turns the Human Story on; anything else is off. */
export const STORY_ENV = "WEB_STORY";

/** The routes HS1 adds when the switch is on (pattern → entrypoint, relative to www/). */
export const STORY_ROUTES = [
  { pattern: "/story/timeline", entrypoint: "./src/story/timeline.astro", path: "/story/timeline/" },
  { pattern: "/story/episodes", entrypoint: "./src/story/episodes.astro", path: "/story/episodes/" },
];

/** The attribute every story-rendered element carries; the dist scans look for it (and for STORY_DATA_KEYS). */
export const STORY_MARKER = "data-story-dark";

/** Keys that exist only in the Human Story's data file (story.json); none may appear in a flag-off dist. */
export const STORY_DATA_KEYS = ["story_weeks", "installments_index", "story_exclusions"];

/** The data file the producer writes only on a WEB_STORY=1 export (never copied into dist). */
export const STORY_DATA_FILE = "story.json";

/** Is the Human Story switched on for this build? */
export function storyEnabled(env = process.env) {
  return Boolean(env) && env[STORY_ENV] === "1";
}

/** The Astro integration that injects the Human Story's routes — and nothing at all when the switch is off. */
export function storyIntegration(env = process.env) {
  return {
    name: "human-story-dark",
    hooks: {
      "astro:config:setup": ({ injectRoute }) => {
        if (!storyEnabled(env)) return;
        for (const r of STORY_ROUTES) injectRoute({ pattern: r.pattern, entrypoint: r.entrypoint, prerender: true });
      },
    },
  };
}

/** The sitemap filter: a story path is never listed (true = keep). Identity on every page HS1 does not own. */
export function notStoryPage(url) {
  const path = new URL(url, "https://averagejoematt.com").pathname;
  return !STORY_ROUTES.some((r) => path === r.path || path.endsWith(r.path));
}
