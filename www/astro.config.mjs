// averagejoematt.com v9 — the static build over the publication snapshot.
// Plan: docs/design/v9/STAGE4_ENGINEERING_PLAN.md §B. Phase 0 (#5530, epic #5529).
//
// Two build targets, one tree:
//   WEB_BASE=/          production root (Phase 4 cut-over; never before the owner's go)
//   WEB_BASE=/next/v9/  the preview path (noindex; the existing /next/ convention)
// WEB_NOINDEX=1 stamps <meta name="robots" content="noindex"> on every page and
// turns the sitemap off, so a preview build can never compete with the live site in
// search (owner requirement C, 2026-10-31).
import { defineConfig } from "astro/config";
import sitemap from "@astrojs/sitemap";

const base = process.env.WEB_BASE || "/";
const noindex = process.env.WEB_NOINDEX === "1";

export default defineConfig({
  site: "https://averagejoematt.com",
  base,
  // Directory URLs with a trailing slash: that is how the S3 website origin routes
  // `/<path>/` to `<path>/index.html`, and how every existing page is addressed.
  trailingSlash: "always",
  output: "static",
  build: {
    format: "directory",
    // CloudFront's CSP is `script-src 'self'`; styles may be inline (`style-src`
    // allows it) but the stylesheet is one cacheable file, not a per-page <style>.
    inlineStylesheets: "never",
    assets: "_astro",
  },
  // Astro 7 defaults to JSX whitespace rules; the templates are hand-written HTML
  // and rely on ordinary inline whitespace between <span>s.
  compressHTML: true,
  scopedStyleStrategy: "class",
  // Nothing on this site is a form POST to Astro; the origin check is irrelevant to a
  // static build but harmless.
  security: { checkOrigin: true },
  vite: {
    build: {
      // Never inline an asset (or a script) as a data: URL or an inline tag — the CSP
      // forbids inline scripts and `tests/web_preview_gate.py` fails the build on one.
      assetsInlineLimit: 0,
    },
  },
  integrations: noindex ? [] : [sitemap()],
});
