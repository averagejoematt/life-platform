// "Your call beside the coaches" (#6088 built it dark; #6114 takes it live) — the BUILD-TIME switches.
//
// Owner ruling 2026-11-16: reader participation is valuable, but no reader action may alter his historical evidence,
// grading records or experiments, and it is developed and tested privately until its safeguards are ready. So the
// control is behind ONE private switch, WEB_READERCALL, read here and nowhere else:
//
//   * components/ReaderCall.astro (on each call's own page, /system/ledger/<id>/) is SELF-GATING: with the switch off
//     it renders nothing and carries no <style> and no <script>;
//   * the island (islands/readercall.js) reaches the page ONLY through readerCallIntegration()'s injectScript — with
//     the switch off nothing is injected, so no chunk exists;
//   * scripts/postbuild.mjs leaves the committed owned_paths.json / reach.json alone on a WEB_READERCALL=1 build;
//   * scripts/check_www_build.py's scan (every deploy runs it with --scan-only) refuses a dist carrying the marker or
//     the island (readercall_leaks).
//
// With the switch off the build is BYTE-IDENTICAL to a build without the feature. The master proof is a recursive
// diff of dist/ against a build of main from the same snapshot. There is no committed go-live constant yet: turning
// it on for readers is a separate, reviewed change after the owner's go (and after the API's own switch,
// lambdas/web/reader_call_rules.py READER_CALL_LIVE, is flipped and deployed).
import { fileURLToPath } from "node:url";

/** The environment variable. Only the literal "1" turns the control on; anything else is off. */
export const READERCALL_ENV = "WEB_READERCALL";

/**
 * THE GO-LIVE SWITCH (#6114, the owner's standing GO once the controls passed): `true` builds the control into every
 * build, so every `www/**` merge deploys it. Read as text by scripts/www_launch_switch.py (`readercall_live`) and so by
 * scripts/check_www_build.py's deploy scan — keep it one line: `export const READERCALL_LIVE = true|false;`. The
 * door itself still answers only when the API's runtime switch (SSM /life-platform/reader-call) is `on`; until then the
 * control hides itself and the "Make your own call" block reads as empty.
 */
export const READERCALL_LIVE = true;
/** The attribute the control carries; the dist scans look for it. */
export const READERCALL_MARKER = "data-readercall";
/** The route the island calls (same origin; the site's CSP is connect-src 'self'). The dist scans look for it too. */
export const READERCALL_API = "/api/reader_call";
/** The kinds of call a reader can make beside — the API's own closed set (reader_call_rules.call_kind). */
export const READERCALL_KINDS = ["direction", "number"];
/** The island's source, injected only when the switch is on. */
export const READERCALL_ISLAND = fileURLToPath(new URL("../islands/readercall.js", import.meta.url));

/** Is the control built in? Live (the committed switch) or the private env switch. */
export function readerCallEnabled(env = process.env, live = READERCALL_LIVE) {
  return live === true || (Boolean(env) && env[READERCALL_ENV] === "1");
}

/** A PRIVATE build: on by the env switch while the control is not live — local review only, never deployed. */
export function readerCallPrivate(env = process.env, live = READERCALL_LIVE) {
  return live !== true && readerCallEnabled(env, false);
}

/** Does this call's page carry the control? A one-tap kind, not sealed, not retired, not disputed. Its WORDS need not
 *  be published (#6114): the API states the question from the fields the page already prints, and decides at runtime
 *  whether the call is open, closed or graded. */
export function readerCallFor(p) {
  if (!p || !READERCALL_KINDS.includes(p.kind) || p.sealed || p.retired) return false;
  return ["pending", "confirmed", "refuted"].includes(p.status) && !p.classification_review;
}

/** The call's PUBLIC item id, as /api/ledger_export serves it (`<coach short id>:<prediction id>`), from the page id
 *  the snapshot builds (`<coach short id>-<prediction id>`; a coach short id carries no hyphen). */
export function itemIdOf(pageId) {
  const s = String(pageId || "");
  const i = s.indexOf("-");
  return i > 0 ? `${s.slice(0, i)}:${s.slice(i + 1)}` : null;
}

/** The Astro integration that injects the island on a PRIVATE build only. Live (#6114), the island ships with the two
 *  components themselves (a component <script> is bundled only for the pages that use it — the ledger index and the
 *  call pages), so no other page, the front page included, carries it. */
export function readerCallIntegration(env = process.env, live = READERCALL_LIVE) {
  return {
    name: "reader-call",
    hooks: {
      "astro:config:setup": ({ injectScript }) => {
        if (!readerCallPrivate(env, live)) return;
        injectScript("page", `import ${JSON.stringify(READERCALL_ISLAND)};`);
      },
    },
  };
}
