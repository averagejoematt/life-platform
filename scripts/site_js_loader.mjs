// scripts/site_js_loader.mjs — module customization hook (node:module `register`)
// used by scripts/import_site_js_graph.mjs (#1432).
//
// The site's ES modules import each other with root-relative specifiers, e.g.
//   import { initTheme } from "/assets/js/theme.js";
// which the BROWSER resolves against the document root (https://averagejoematt.com/).
// Node's default resolver treats a leading "/" as a literal filesystem path, which
// doesn't exist on the CI runner (or any dev machine) — this hook rewrites any such
// specifier to the real path under site/assets/ before handing it back to Node's
// default resolver.
//
// It also forces `format: "module"` for every resolved file under site/ that ends in
// .js. There's no package.json here (the site ships no build step / no deps — see
// CLAUDE.md "No framework/deps"), so Node's default format-detection would otherwise
// treat a plain .js file as CommonJS and reject the import/export syntax outright.
// That's a REAL parse (not node --check's lazy pre-parse) forcing ESM interpretation
// end to end, which is the whole point of this gate.
import { pathToFileURL, fileURLToPath } from "node:url";
import path from "node:path";

const SITE_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "site");
const SITE_ROOT_URL = pathToFileURL(SITE_ROOT + path.sep).href;

export async function resolve(specifier, context, nextResolve) {
  const target = specifier.startsWith("/assets/") ? pathToFileURL(path.join(SITE_ROOT, specifier)).href : specifier;

  const result = await nextResolve(target, context);

  if (result.url.startsWith(SITE_ROOT_URL) && result.url.endsWith(".js")) {
    return { ...result, format: "module" };
  }
  return result;
}
