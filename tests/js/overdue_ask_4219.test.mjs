// tests/js/overdue_ask_4219.test.mjs — the cockpit's "one ask" says when it is late (#4219).
//
// On 2026-09-26 /api/coaching-dashboard (19:31Z) served ten open_actions, every one
// asked 2026-09-12 and due 2026-09-19, status "pending", check null — and the cockpit
// printed the first as "The one ask … Sep 12, due Sep 19." with nothing saying it was a
// week late. The fixture below is that payload's shape: coach ids/names and dates are the
// served ones (Park ×2, Webb, Reeves ×2, Reyes, Okafor ×4); only the Park text is quoted
// verbatim in the issue, so the other nine texts are stand-ins — askLine prints text
// verbatim and never branches on it.
import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";

const tq = await import("../../site/assets/js/three_questions.js");
const { daysOverdue, lateWords } = await import("../../site/assets/js/entry_age.js");

const NOW = new Date("2026-09-26T19:31:00Z"); // 12:31 PT, Saturday Sep 26
const row = (coach_id, coach_name, text) => ({ coach_id, coach_name, text, asked_on: "2026-09-12", due: "2026-09-19", status: "pending", check: null, evidence_link: null });
const OPEN_ACTIONS_0926 = [
  row("sleep_coach", "Dr. Lisa Park", "Start logging the daily 1-to-5 subjective feeling scale before checking the app"),
  row("sleep_coach", "Dr. Lisa Park", "(stand-in text 2)"),
  row("nutrition_coach", "Dr. Marcus Webb", "(stand-in text 3)"),
  row("mind_coach", "Dr. Nathan Reeves", "(stand-in text 4)"),
  row("mind_coach", "Dr. Nathan Reeves", "(stand-in text 5)"),
  row("physical_coach", "Dr. Max Reyes", "(stand-in text 6)"),
  row("labs_coach", "Dr. James Okafor", "(stand-in text 7)"),
  row("labs_coach", "Dr. James Okafor", "(stand-in text 8)"),
  row("labs_coach", "Dr. James Okafor", "(stand-in text 9)"),
  row("labs_coach", "Dr. James Okafor", "(stand-in text 10)"),
];

const text = (html) => {
  let s = String(html);
  for (let i = 0; i < 20 && /<[^>]*>/.test(s); i++) s = s.replace(/<[^>]*>/g, "");
  return s;
};

test("daysOverdue: the ten 09-19-due rows read on 09-26 (PT clock) are 7 days late", () => {
  for (const a of OPEN_ACTIONS_0926) assert.equal(daysOverdue(a, NOW), 7);
  // PT, not UTC: 03:00Z on Sep 20 is still Sep 19 in Pacific — due today, not late
  assert.equal(daysOverdue({ due: "2026-09-19" }, new Date("2026-09-20T03:00:00Z")), 0);
  assert.equal(daysOverdue({ due: "2026-10-02" }, NOW), 0);
  assert.equal(daysOverdue({ due: "n/a" }, NOW), null);
  // a served days_overdue (the server-side box) wins over the client computation
  assert.equal(daysOverdue({ due: "2026-09-19", days_overdue: 3 }, NOW), 3);
  assert.equal(lateWords(7), "7 days late");
  assert.equal(lateWords(1), "1 day late");
  assert.equal(lateWords(0), "");
});

test("every open ask overdue: the one ask carries its lateness, and the line says all are late — once", () => {
  const line = text(tq.askLine({ open_actions: OPEN_ACTIONS_0926 }, NOW));
  assert.equal(
    line,
    "The one ask: “Start logging the daily 1-to-5 subjective feeling scale before checking the app” — Dr. Lisa Park, asked September 12, due September 19 — 7 days late. All ten open asks are past due."
  );
  assert.equal(line.split("past due").length - 1, 1);
});

test("a current ask leads over overdue ones, and the late ones are counted, not hidden", () => {
  const current = { coach_id: "physical_coach", coach_name: "Dr. Max Reyes", text: "reach 170 g protein per day for seven consecutive days", asked_on: "2026-09-25", due: "2026-10-02", status: "pending" };
  const line = text(tq.askLine({ open_actions: OPEN_ACTIONS_0926.slice(0, 3).concat([current]) }, NOW));
  assert.equal(line, "The one ask: “reach 170 g protein per day for seven consecutive days” — Dr. Max Reyes, asked September 25, due October 2. Three earlier asks are past due.");
  assert.ok(!/late/.test(line));
});

test("guard: an overdue ask is never printed without its lateness", () => {
  for (let k = 1; k <= OPEN_ACTIONS_0926.length; k++) {
    const line = text(tq.askLine({ open_actions: OPEN_ACTIONS_0926.slice(0, k) }, NOW));
    assert.match(line, /due September 19 — 7 days late\./);
  }
});
