// The share card a page points at (2026-11-14, sprint II): used only when its hashed file exists at build time.
import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";

import { cardUrl } from "../src/lib/og.js";

test("a card is used only when its hashed file is in the build's public tree", () => {
  const root = mkdtempSync(join(tmpdir(), "og-"));
  assert.equal(cardUrl("home", root), null, "no cards drawn: the page keeps the wordmark");
  mkdirSync(join(root, "public", "assets", "og", "v9"), { recursive: true });
  writeFileSync(join(root, "public", "assets", "og", "v9", "week-12.6b0fe141.png"), "x");
  assert.equal(cardUrl("week-12", root), "https://averagejoematt.com/assets/og/v9/week-12.6b0fe141.png");
  assert.equal(cardUrl("week-1", root), null, "a key never matches a longer key's card");
  assert.equal(cardUrl("../x", root), null);
  assert.equal(cardUrl(null, root), null);
});
