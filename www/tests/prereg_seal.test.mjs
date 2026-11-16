// No page claims the sealed pre-registration can be checked unless the file served at the sealed address hashes to the
// published digest (owner ruling 2026-11-11, item 3). The producer decides that from the served bytes and writes
// `prereg_seal.verifiable` into the snapshot (scripts/publish_snapshot_calibration.py::guard_seal); the page offers the
// verify command and the file link only when it is true. This scans the built dist (CI: the fixture build
// scripts/check_www_build.py leaves in www/dist) for any verifiability claim and requires the snapshot's seal to be
// verifiable wherever one appears — with a planted claim as the mutation control.
import { test } from "node:test";
import assert from "node:assert/strict";
import { cpSync, existsSync, mkdtempSync, readFileSync, readdirSync, rmSync, statSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const WWW = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const DIST = resolve(process.env.SEAL_AUDIT_DIST || join(WWW, "dist"));
const SNAPSHOT_CAL = join(WWW, "content", "snapshot", "calibration.json");
const HAVE_DIST = existsSync(join(DIST, "index.html"));

/** What a page says when it offers the reader a check: the verify block, its label, the command, the invitation. */
const CLAIMS = [/data-verify\b/, /Verify command/, /shasum -a 256/, /Anyone can check that/];

function htmlFiles(dir, out = []) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) htmlFiles(p, out);
    else if (name.endsWith(".html")) out.push(p);
  }
  return out;
}

function claims(dist) {
  const found = [];
  for (const f of htmlFiles(dist)) {
    const s = readFileSync(f, "utf8");
    for (const rx of CLAIMS) if (rx.test(s)) found.push(`${rx.source} in ${f.slice(dist.length)}`);
  }
  return found;
}

function snapshotSeal() {
  if (!existsSync(SNAPSHOT_CAL)) return null;
  const cal = JSON.parse(readFileSync(SNAPSHOT_CAL, "utf8"));
  return cal?.calibration?.prereg_seal ?? null;
}

test("no built page offers a check of the seal unless the snapshot's seal is verifiable (control: a planted claim)", { skip: !HAVE_DIST && "no www/dist (build first)" }, () => {
  const seal = snapshotSeal();
  const found = claims(DIST);
  if (!(seal && seal.verifiable === true)) assert.deepEqual(found, [], "a page offers a check of a seal the served file does not match");

  const dir = mkdtempSync(join(tmpdir(), "seal-audit-"));
  try {
    cpSync(DIST, dir, { recursive: true });
    writeFileSync(join(dir, "planted.html"), `<div data-verify><span>Verify command</span></div>`);
    assert.ok(claims(dir).some((f) => f.includes("planted.html")), "control: the planted claim is found");
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("an unverifiable seal is still published: the digest and the reason are on the page", { skip: !HAVE_DIST && "no www/dist (build first)" }, () => {
  const seal = snapshotSeal();
  if (!seal || seal.verifiable === true || !seal.sha256) return;
  const pages = htmlFiles(DIST).filter((f) => readFileSync(f, "utf8").includes("data-seal-unverifiable"));
  assert.ok(pages.length > 0, "the calibration page states why the seal cannot be checked");
  for (const f of pages) assert.ok(readFileSync(f, "utf8").includes(seal.sha256), `the digest is published on ${f.slice(DIST.length)}`);
});
