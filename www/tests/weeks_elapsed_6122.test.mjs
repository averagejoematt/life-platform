// #6122: "Day 72 of an experiment that began on 6 September 2026" sat beside "11 weeks so far" — 72 days are 10 full
// weeks and 2 days of the 11th. One wording for weeks elapsed (format.js weeksElapsed), read by every page that counts
// them; an ordinal (weekOfDay) names the week a day falls in.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { weekOfDay, weeksElapsed } from "../src/lib/format.js";
import { soFar } from "../src/lib/story.js";

test("a week in progress is never counted as a week done", () => {
  assert.equal(weeksElapsed(72).words, "10 full weeks and 2 days of week 11");
  assert.deepEqual([weeksElapsed(72).full, weeksElapsed(72).rest, weeksElapsed(72).week], [10, 2, 11]);
  assert.equal(weeksElapsed(70).words, "10 full weeks", "day 70 closes week 10: nothing under way");
  assert.equal(weeksElapsed(71).words, "10 full weeks and 1 day of week 11");
  assert.equal(weeksElapsed(7).words, "One full week");
  assert.equal(weeksElapsed(8).words, "One full week and 1 day of week 2");
  assert.equal(weeksElapsed(3).words, "3 days of week 1");
  assert.equal(weeksElapsed(1).words, "1 day of week 1");
  for (const bad of [0, -3, 2.5, null, undefined, "72"]) assert.equal(weeksElapsed(bad), null);
});

test("the count never exceeds the full weeks plus one under way, for every day of a long experiment", () => {
  for (let d = 1; d <= 400; d++) {
    const w = weeksElapsed(d);
    assert.equal(w.full * 7 + w.rest, d, `day ${d}`);
    assert.equal(w.week, weekOfDay(d), `day ${d}: the ordinal and the count name the same week`);
    assert.ok(w.rest === 0 ? !/ of week /.test(w.words) : w.words.endsWith(`of week ${w.full + 1}`), `day ${d}: ${w.words}`);
  }
  assert.deepEqual([1, 7, 8, 14, 15, 72].map(weekOfDay), [1, 1, 2, 2, 3, 11]);
});

test("the story-so-far entry counts weeks from the edition's day, not from the length of the week list", () => {
  const story = { state: "ok", genesis: "2026-09-06", installments_index: [], story_weeks: Array.from({ length: 11 }, (_, i) => ({ week: i + 1 })) };
  assert.equal(soFar(story, { day_n: 72 }).weeksWords, "10 full weeks and 2 days of week 11");
  assert.equal(soFar(story, null).weeksWords, "11 program weeks listed", "no day number: it says what the list holds, not weeks elapsed");
});

test("every page that counts weeks elapsed reads the one helper; none counts the list's rows as weeks done", () => {
  for (const p of ["src/components/StoryEntry.astro", "src/story/timeline.astro"]) {
    const src = readFileSync(p, "utf8");
    assert.match(src, /so\.weeksWords\} so far/, `${p} prints the shared wording`);
  }
  const story = readFileSync("src/lib/story.js", "utf8");
  assert.doesNotMatch(story, /`\$\{weeks\} weeks`/, "the bare row count is never worded as weeks elapsed");
  const day = readFileSync("src/pages/data/day/[id].astro", "utf8");
  assert.match(day, /weekOfDay\(x\.day_number\)/, "the Day page's fallback week is the shared ordinal");
});
