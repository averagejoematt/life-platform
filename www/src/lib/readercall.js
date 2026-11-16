// "Your call beside the coaches" (#6088) — the BUILD-TIME switch, built dark.
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
/** The attribute the control carries; the dist scans look for it. */
export const READERCALL_MARKER = "data-readercall";
/** The route the island calls (same origin; the site's CSP is connect-src 'self'). The dist scans look for it too. */
export const READERCALL_API = "/api/reader_call";
/** The kinds of call a reader can make beside — the API's own closed set (reader_call_rules.call_kind). */
export const READERCALL_KINDS = ["direction", "number"];
/** The island's source, injected only when the switch is on. */
export const READERCALL_ISLAND = fileURLToPath(new URL("../islands/readercall.js", import.meta.url));

/** Is the private switch on for this build? */
export function readerCallEnabled(env = process.env) {
  return Boolean(env) && env[READERCALL_ENV] === "1";
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

/** The Astro integration that injects the island — and nothing at all when the switch is off. */
export function readerCallIntegration(env = process.env) {
  return {
    name: "reader-call-dark",
    hooks: {
      "astro:config:setup": ({ injectScript }) => {
        if (!readerCallEnabled(env)) return;
        injectScript("page", `import ${JSON.stringify(READERCALL_ISLAND)};`);
      },
    },
  };
}
