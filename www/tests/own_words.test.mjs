// His own words (owner ruling 2026-11-15): a line is placed only when the pin and the served file agree exactly, and
// the moments page carries a line only on the card its day belongs to.
import { test } from "node:test";
import assert from "node:assert/strict";
import { OWN_WORDS, ownWords, withinDays } from "../src/lib/own_words.js";
import { moments } from "../src/lib/moments.js";

const served = (rows) => ({ state: "ok", quotes: rows });
const all = served(Object.values(OWN_WORDS).map((p) => ({ date: p.date, quote: p.text })));

test("a pinned line is placed only when the served file carries the same day and the same words", () => {
  const pin = OWN_WORDS.ai_verdict;
  assert.deepEqual(ownWords(all, "ai_verdict"), { key: "ai_verdict", date: pin.date, text: pin.text, frame: null });
  assert.equal(ownWords(served([{ date: pin.date, quote: pin.text.replace("isn't", "is not") }]), "ai_verdict"), null); // one edit
  assert.equal(ownWords(served([{ date: "2026-11-09", quote: pin.text }]), "ai_verdict"), null); // another day
  assert.equal(ownWords(served([]), "ai_verdict"), null); // revoked
  assert.equal(ownWords({ state: "absent", quotes: [{ date: pin.date, quote: pin.text }] }, "ai_verdict"), null);
  assert.equal(ownWords(null, "ai_verdict"), null);
  assert.equal(ownWords(all, "not_a_placement"), null);
});

test("every placement names where it may appear, and the two that need a frame carry one", () => {
  for (const [key, pin] of Object.entries(OWN_WORDS)) {
    assert.ok(Array.isArray(pin.scope) && pin.scope.length > 0, key);
    assert.match(pin.sk, new RegExp(`^QUOTE#${pin.date}#[0-9a-f]{10}$`), key);
  }
  // his words about how he feels and about the coaches are never shown bare: the frame says what they are not
  assert.match(OWN_WORDS.content.frame, /not a measurement/);
  assert.match(OWN_WORDS.coaches_changed.frame, /not a measurement/);
});

test("withinDays is inclusive and fails closed", () => {
  assert.equal(withinDays("2026-11-08", "2026-11-04", "2026-11-10"), true);
  assert.equal(withinDays("2026-11-04", "2026-11-04", "2026-11-10"), true);
  assert.equal(withinDays("2026-11-11", "2026-11-04", "2026-11-10"), false);
  assert.equal(withinDays("2026-11-08", null, "2026-11-10"), false);
});

const journey = { start_date: "2026-09-06", start_weight_lbs: 327.3, goal_weight_lbs: 185, rungs: [] };
const chapters = [
  { status: "published", week: 2, week_label: "Week 2", title: "Eight Pounds and a Flag", excerpt: "x", covers_start: "2026-09-09", covers_end: "2026-09-15" },
  { status: "published", week: 10, week_label: "Week 10", title: "The Rate Flag", excerpt: "y", covers_start: "2026-11-04", covers_end: "2026-11-10" },
];
const paths = { dayPath: () => null, chapterPath: () => "/story/x/", coachPath: () => "/system/coaches/x/" };

test("the beginning sits on the first morning's card and the pace line on the rate-flag chapter's card", () => {
  const own = { beginning: ownWords(all, "beginning"), pace: ownWords(all, "pace") };
  const list = moments({ journey, chapters, coaches: [], lead: null, finding: null, own, ...paths });
  assert.equal(list.find((m) => m.key === "start").own, "beginning");
  assert.equal(list.find((m) => m.key === "rate-flag").own, "pace");
  assert.equal(list.find((m) => m.key === "first-flag").own ?? null, null); // the earlier flag chapter carries no line
});

test("a line that is not served, or whose day is outside the card's days, is not carried", () => {
  const none = moments({ journey, chapters, coaches: [], lead: null, finding: null, ...paths });
  assert.ok(none.every((m) => !m.own));
  const otherStart = moments({ journey: { ...journey, start_date: "2026-09-07" }, chapters, coaches: [], lead: null, finding: null, own: { beginning: ownWords(all, "beginning") }, ...paths });
  assert.equal(otherStart.find((m) => m.key === "start").own, null);
  const moved = chapters.map((c) => (c.week === 10 ? { ...c, covers_start: "2026-11-09", covers_end: "2026-11-15" } : c));
  const outside = moments({ journey, chapters: moved, coaches: [], lead: null, finding: null, own: { pace: ownWords(all, "pace") }, ...paths });
  assert.equal(outside.find((m) => m.key === "rate-flag").own, null);
});
