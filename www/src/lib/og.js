// The share card a page points og:image at (2026-11-14, sprint II): scripts/v9_og_images.py draws one per published
// chapter and one for the front page into public/assets/og/v9/ during the deploy, from the same snapshot the build
// reads. A page names its card; the card is used only when its file exists at build time, so a build without the
// cards (a local or fixture build, or no Pillow) keeps the site-wide wordmark rather than pointing at nothing.
import { existsSync, readdirSync } from "node:fs";
import { join } from "node:path";

export const WORDMARK = "https://averagejoematt.com/assets/og/wordmark-1200x630.png";

/** The absolute URL of a page's card when its file is in the build's public tree, else null. */
// A card's name is `<key>.<sha8>.png` (the deploy caches assets/ for a year, so a changed card is a new name).
export function cardUrl(key, root = process.cwd()) {
  if (!key || !/^[a-z0-9-]+$/.test(key)) return null;
  const dir = join(root, "public", "assets", "og", "v9");
  if (!existsSync(dir)) return null;
  const name = readdirSync(dir)
    .filter((f) => new RegExp(`^${key}\\.[0-9a-f]{8}\\.png$`).test(f))
    .sort()[0];
  return name ? `https://averagejoematt.com/assets/og/v9/${name}` : null;
}
