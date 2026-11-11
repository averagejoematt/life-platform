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

/**
 * THE GO-LIVE SWITCH — the owner's GO is the one-line PR that sets this to `true` (feat/story-go-live). `false`: HS1 is
 * dark (the env switch above gives a private, never-deployed build). `true`: the timeline and the "story so far" entry
 * are part of every build, so every `www/**` merge deploys them: public (no private label), in the sitemap, owned in
 * owned_paths.json, no longer refused by the deploy scan. Read as text by scripts/publish_snapshot_story.py
 * (`story_live`) and scripts/check_www_build.py — keep it one line: `export const STORY_LIVE = true|false;`.
 */
export const STORY_LIVE = true;

/** The routes HS1 adds when the switch is on (pattern → entrypoint, relative to www/). */
export const STORY_ROUTES = [
  // NOT /story/timeline/: that URL is the established v8 page, served from site/story/timeline/ by the site deploy (and
  // the target of three redirects). HS1's timeline lives at its own address so no deploy can overwrite the kept page —
  // tests/test_www_route_site_collision.py refuses any www route on a site/ page that owned_paths.json does not claim.
  { pattern: "/story/so-far", entrypoint: "./src/story/timeline.astro", path: "/story/so-far/" },
  // The episode index (/story/episodes/) is folded into the timeline (2026-11-09 readiness review): it repeated
  // /story/'s own chapter list with less in it.
];

/** The attribute every story-rendered element carries; the dist scans look for it (and for STORY_DATA_KEYS). */
export const STORY_MARKER = "data-story-dark";

/** Keys that exist only in the Human Story's data file (story.json); none may appear in a flag-off dist. */
export const STORY_DATA_KEYS = ["story_weeks", "installments_index", "story_exclusions"];

/** The data file the producer writes only on a WEB_STORY=1 export (never copied into dist). */
export const STORY_DATA_FILE = "story.json";

/** Is the Human Story switched on for this build? Live (the committed switch) or the private env switch. */
export function storyEnabled(env = process.env, live = STORY_LIVE) {
  return live === true || (Boolean(env) && env[STORY_ENV] === "1");
}

/** A PRIVATE story build: on by the env switch while HS1 is not live — local review only, never deployed. */
export function storyPrivate(env = process.env, live = STORY_LIVE) {
  return live !== true && storyEnabled(env, false);
}

/** The Astro integration that injects the Human Story's routes — and nothing at all when the switch is off. */
export function storyIntegration(env = process.env, live = STORY_LIVE) {
  return {
    name: "human-story-dark",
    hooks: {
      "astro:config:setup": ({ injectRoute }) => {
        if (!storyEnabled(env, live)) return;
        for (const r of STORY_ROUTES) injectRoute({ pattern: r.pattern, entrypoint: r.entrypoint, prerender: true });
      },
    },
  };
}

/** The sitemap filter: while HS1 is dark a story path is never listed (true = keep); once live every story page is kept. */
export function notStoryPage(url, live = STORY_LIVE) {
  if (live === true) return true;
  const path = new URL(url, "https://averagejoematt.com").pathname;
  return !STORY_ROUTES.some((r) => path === r.path || path.endsWith(r.path));
}
