// tests/js/evidence_shared.test.mjs — unit tests for the shared formatter/
// micro-builder helpers in site/assets/js/evidence_shared.js (#1431). This
// module is imported by every /data/, /protocols/ and /method/ renderer
// (evidence_*.js) — a regression here (e.g. `esc` losing an escape, `fmt`
// mis-rounding, `isBad` failing to catch a "[REDACTED]"-shaped sentinel) is a
// silent XSS/formatting bug across ~40 pages at once.
import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";
import { esc, isBad, has, fmt, ttl, fmtShort, nightOf, dayBefore, warmup, note, evClass, kvval, kvtable, fig, figs, sec, empty } from "../../site/assets/js/evidence_shared.js";

test("esc — escapes all five HTML-significant characters", () => {
  assert.equal(esc(`<a href="x">&y</a>`), "&lt;a href=&quot;x&quot;&gt;&amp;y&lt;/a&gt;");
});

test("esc — null/undefined render as empty string, never the literal word 'null'", () => {
  assert.equal(esc(null), "");
  assert.equal(esc(undefined), "");
});

test("isBad — catches the null/empty/N-A/bracketed-sentinel shapes an upstream field can carry", () => {
  assert.equal(isBad(null), true);
  assert.equal(isBad(""), true);
  assert.equal(isBad("   "), true);
  assert.equal(isBad("N/A"), true);
  assert.equal(isBad("n/a"), true);
  assert.equal(isBad("[REDACTED]"), true);
  assert.equal(isBad("42"), false);
  assert.equal(isBad("a real string"), false);
});

test("has — 0 and non-empty arrays are truthy data; null/''/empty-array are not", () => {
  assert.equal(has(0), true); // a real zero is data, not absence
  assert.equal(has(null), false);
  assert.equal(has(""), false);
  assert.equal(has([]), false);
  assert.equal(has([1]), true);
  assert.equal(has("x"), true);
});

test("fmt — null/empty render the em-dash; numbers default to 1 decimal unless integral", () => {
  assert.equal(fmt(null), "—");
  assert.equal(fmt(""), "—");
  assert.equal(fmt(3), "3");
  assert.equal(fmt(3.14159), "3.1");
  assert.equal(fmt(3.14159, 2), "3.14");
});

test("fmt — booleans are NOT treated as numbers (Number(true)===1 trap) and pass through escaped", () => {
  assert.equal(fmt(true), "true");
});

test("ttl — snake_case/kebab-case becomes Title Case", () => {
  assert.equal(ttl("some_field-name"), "Some Field Name");
});

test("fmtShort — an ISO date renders 'Mon D'; a non-date renders empty, not garbage", () => {
  assert.equal(fmtShort("2026-03-05T00:00:00"), "Mar 5");
  assert.equal(fmtShort("garbage"), "");
  assert.equal(fmtShort(""), "");
});

test("nightOf — sleep/recovery records are wake-date-keyed; the night is one day earlier", () => {
  assert.equal(nightOf("2026-03-05"), "Mar 4");
  assert.equal(nightOf("2026-01-01"), "Dec 31"); // month/year rollover
});

test("dayBefore — returns the ISO date one day earlier; invalid input is honest empty, not NaN-ish text", () => {
  assert.equal(dayBefore("2026-03-05"), "2026-03-04");
  assert.equal(dayBefore("garbage"), "");
});

test("warmup — no real threshold renders nothing (never a fake progress bar)", () => {
  assert.equal(warmup(3, 0, "x"), "");
  assert.equal(warmup(3, null, "x"), "");
  assert.equal(warmup(3, -1, "x"), "");
});

test("warmup — lights marks proportional to current/threshold, caps the row at 12", () => {
  const out = warmup(5, 10, "Intake responses");
  assert.equal((out.match(/wu-dot lit/g) || []).length, 5);
  assert.equal((out.match(/class="wu-dot"/g) || []).length, 5); // unlit marks
  assert.match(out, /5\/10/);
});

test("warmup — a null current renders all-hollow with an honest em-dash, never a fake 0", () => {
  const out = warmup(null, 10, "Intake responses");
  assert.equal((out.match(/wu-dot lit/g) || []).length, 0);
  assert.match(out, /—\/10/);
});

test("note — wraps prose with the N=1 low-confidence badge", () => {
  assert.equal(note("Correlative read"), '<p class="correlative">Correlative read <span class="confidence conf-low">N=1</span></p>');
});

test("evClass — maps an evidence-strength string to its badge class + label", () => {
  assert.deepEqual(evClass("strong"), ["backed-strong", "well supported"]);
  assert.deepEqual(evClass("robust"), ["backed-strong", "well supported"]);
  assert.deepEqual(evClass("moderate"), ["backed-some", "moderate support"]);
  assert.deepEqual(evClass("mixed"), ["backed-some", "moderate support"]);
  assert.deepEqual(evClass("anything else"), ["backed-thin", "preliminary"]);
  assert.deepEqual(evClass(undefined), ["backed-thin", "preliminary"]);
});

test("kvval — null renders em-dash, empty array renders em-dash, non-empty array renders a count", () => {
  assert.equal(kvval(null), "—");
  assert.equal(kvval([]), "—");
  assert.equal(kvval([1, 2]), "2 items");
  assert.equal(kvval([1]), "1 item"); // singular
});

test("kvval — a plain nested object compacts to 'Key val · Key val', not a wall of dashes", () => {
  assert.equal(kvval({ a: 1, b: 2 }), "A 1 · B 2");
});

test("kvtable — drops rows whose value renders empty, so nested-null objects don't leave dash rows", () => {
  const out = kvtable({ good: 3, bad: null, nested_empty: {} });
  assert.match(out, /Good/);
  assert.doesNotMatch(out, /Bad/);
  assert.doesNotMatch(out, /Nested Empty/);
});

test("kvtable — an all-empty object renders no table at all", () => {
  assert.equal(kvtable({}), "");
  assert.equal(kvtable({ x: null }), "");
});

test("fig/figs/sec/empty — the HTML micro-builders shape their markup as expected", () => {
  assert.equal(fig("42", "Label"), '<div class="fig"><span class="fig-v num">42</span><span class="fig-k label">Label</span></div>');
  assert.equal(figs([fig("1", "a"), null, fig("2", "b")]), '<div class="figs">' + fig("1", "a") + fig("2", "b") + "</div>");
  assert.equal(sec("T", ""), ""); // no section wrapper when there's nothing to show
  assert.match(sec("T", "<p>hi</p>"), /<section class="rd-sec"><h2 class="rd-h">T<\/h2><p>hi<\/p><\/section>/);
  assert.equal(empty("nothing"), '<p class="rd-archive">nothing</p>');
});
