# averagejoematt.com v7 — the concept (driver synthesis, 2026-09-26 13:10 PT)

Inputs: R1 the masters' playbook · R2 the five-persona red team of the live site · the A-grade sweep (3 A · 12 B · 2 C · 8 D) · the coach-voice red team · the owner's brief of 12:40 PT. R3 (content inventory) is folded in when it lands; it changes the material, not the frame.

## 1. The one question

**Can AI, working over one ordinary man's own numbers, move his life — and by how much?** Every page is a chapter of that investigation, published weekly, allowed to find nothing. The subject is a 300-plus-pound man on his seventeenth start, published either way. The site is a documentary, not a dashboard; the reader is a witness, not the patient.

## 2. The order rule (this is the redesign)

R2's verdict is the design: the receipts of an honest experiment exist and are hidden under the site describing itself. So every page, and the site as a whole, runs in this order and no other:

1. **The human first** — his photo (dated), his own words (dated, this cycle), this week's number with its range and its day.
2. **The counted failures second** — 17 starts, none past day 30; the coach who is 0 for 5; 468 expired calls; the refusals ("the engine does not publish a deficit", "no sensor this cycle").
3. **The mechanism third** — how the number is made, in one paragraph; the dispute docket as a table; the repo link; a way to check.
4. **The coaches last and short** — one voice a day, third person, opened by its ledger line; at most three on a screen; no generated dialogue, ever.
5. **The machine vocabulary never** — no loop, station, pillar, cockpit, chronicle, calibration, gate, EWMA on a reader page.

## 3. Nine pages (bottom bar carries the first five)

| # | page | its one job | the fold at 390 px (≤ 120 words, ≤ ~700 px) |
|---|---|---|---|
| 1 | **Home** | the case so far | photo beside "313.8 lb, Saturday, September 26 — down 13.5 lb in 21 days from 327.3" · the premise with its receipt ("300+ lb, seventeenth start, published either way") · alive-and-keeps-score: "data through today · the coaches right 18 of 37 · next write-up Wednesday, September 30" |
| 2 | **Today** | Matthew's morning screen, open to anyone | the three questions (keep — R2's 9/10) + the session with loads + the one ask, allowed to say "7 days late"; nothing after it |
| 3 | **This week** | the instalment | title · day in words · his testimony paragraph · the finding · previously / next |
| 4 | **His numbers** | the evidence | one page, sections: weight · sleep · eating · training · blood tests; one chart + one sentence each; CSV under every chart |
| 5 | **The coaches** | the witnesses, on the record | today's read + its ledger line · where two disagree, the engine's number between them · the record as "K of N through <day>" |
| 6 | **What he's trying** | the protocol | what · should move · how we'd know; his decisions in his words |
| 7 | **Who he is** | the subject | first person, photo, the seventeen starts, the email address |
| 8 | **Under the hood** | the mechanism + the corrections column | how a number is made · the wrong page as sentences · the build log's titles · the gear · the repo |
| 9 | **Follow** | the return | "The numbers every Sunday; the write-up every Wednesday." · the honest count |

Plus `/privacy/`. Everything else keeps its URL and leaves the nav (the `unlisted` registry flag; reach ratchet 25 → 9; no 301s, no deletions).

## 4. The ten-second test (R1 c, R2 confirmed)

1. A dated photo of him beside one number with its day and range.
2. The premise with its honesty receipt: the seventeenth start — **and Day 21 is the farthest any of them has got** (R3: `survival.n_prior_cycles 16`, `longest_run_days 13`, `reached_horizon_n 0`; served today only on unlinked pages). This is the lead of the whole site until it stops being true.
3. Proof it is alive and keeps score: data through, K of N, the next dated write-up.

## 5. The coaches: expert witnesses with memory

- **Third person for Matthew, first person for the coach; the ask reported, never commanded** (#4213 lane in flight). A slot with no public twin renders empty.
- **The ledger line opens every read:** "On September 19 I said X — it came in at Y." That line is the owner's "memory, not state in time" test; it is the first thing to ship on the engine side (checked prediction + claim + value per coach, served).
- **Disagreement as two named witnesses** with the engine's number between them, from the docket — as a table, never a screenplay. The generated Webb/Reyes dialogue and "the integrator's call" are deleted.
- **The record as "K of N through <day>"**, never a bare percentage; the embarrassing rows stay up.
- **A coach with no instrument is absent, not arguing:** the glucose coach does not speak while "no sensor this cycle" is true.
- ≤ 3 coaches visible on any screen; the roster one tap down; no trait sliders, no cast sheet.

## 6. Receipts a sceptic checks (R2 b) — each gets a home

| receipt | today | v7 |
|---|---|---|
| a real photo | none on 25 pages (a stock photo on home) | the owner adds one (#3761); the frame is honest until then, never a stock image or a silhouette |
| his own words this cycle | none (one July essay) | one dated sentence a week on Home; the morning note (#4189) is the channel |
| admitted failure | best in class, 14 screens down | second on Home |
| methodology in a paragraph | none | Under the hood, first paragraph; linked from every number |
| a way to check | repo on one footer page; no CSV | repo link in the header of Under the hood; CSV under every chart |
| anyone vouching | "One subscriber so far." | kept, verbatim — it is the truest line on the site |

## 7. Return triggers

One dated promise per page, in a human's voice: "next write-up Wednesday, September 30" (kept), "the Sunday numbers", "resolves October 30 by code" for open calls, "next weigh-in tomorrow". Never "follow by email for the next entry".

## 8. Delete list (adopted from R2 e; the URLs survive unlinked)

The loop diagram and station blocks · the seven-areas bubbles and "newly unlocked" · "try it on" · "ask the data" · the generated dialogues and the integrator's call · "where the team stands" one-liners · the engine's-score gauges that duplicate "last night?" · the cast-sheet sliders · the per-page feedback widget, the "you are here" and "next on the loop" blocks, the loop strip under every H1 · the podcast page until episode 2 · the character-level explainer · the "new here?" banners · the silhouette · the milestone ladder · the seven-network follow list.

## 9. Keep list (R2 f) — these are the site

The three questions · every start counted · the scorecard's embarrassing rows · the docket as a table · the refusals · "range held 79 % of 253 graded" · the build-log titles · "One subscriber so far." and the email address.

## 10. Non-negotiables carried from v6 (ADR-104/105/156)

Served fields only; absence stated as absence; no engine number changes to make a page simpler; dates in words, one formatter, "data through <day>" once per page; green means earned; served coach text never rewritten (guarded or empty); percentages carry n, below n = 30 render "7 of 16".

## 11. Design direction

Two prototypes tonight — A: the serialised investigation, editorial and quiet; B: a materially different world on the same data. The owner picks one in one message; the build week starts from that choice. Both obey §2–§10. Photos are on the critical path of §4 and §6.

## 12. How it gets built (V7_BUILD_PLAN.md carries the mechanics)

Built beside the live site at a preview path; the five personas red-team it; cut over when all nine pages grade A on the sweep rubric, axe serious = 0, and the comprehension judge scores ≥ 2 on every door. Never a half-migrated live site.

## 13. Engine defects the red team found (filed today)

A ninth coach, "Dr. Sarah Chen", on the scorecard and on no roster · an August dispute docket re-refuted on 09-24, 09-25 and 09-26 (no thread expiry) · the glucose coach arguing about glucose with no sensor this cycle · `/method/` prints a slope as a recovery score ("measured 0.08") · the cockpit's "one ask" seven days overdue with nothing saying so.

## 14. Folded in from R3 (13:05 PT)

- **The lead truth:** Day 21 is farther than any of his 16 earlier starts (longest 13 days); the odds of day 30 are withheld because no start ever reached it. Home carries it in the fold; "Who he is" carries every start counted.
- **The same thing served twice in six places** (two front doors, two coaching doors, two "team" pages, two character explainers, two stats pages, three weight pages): R3's 91-page table — SPINE 10 · FOLD 43 · ARCHIVE 23 · KILL 15 — is the cut-over map; the build plan uses it page by page. R3's nine-page proposal and §3 agree on the set; §3's names stand.
- **One record producer.** `api_coaches`, `api_calibration` and `api_wrong` give Webb three different records, and a pre-cycle docket resolved 2026-08-10 is re-recorded as 20 learnings each for Webb and Brandt. "K of N through <day>" must come from ONE producer before it is printed anywhere; until then the coaches page prints the docket's own counts and says which. Filed with the engine defects.
- **Two goal-date producers:** `public_stats.journey` still serves 2027-04-20 while `/api/journey` serves `projected_goal_date null` — one of them lies on every page that reads it (#4184's tail).
- **The coaches' memory, as it exists:** threads have no identity across days (every restatement is a new record; `check` null everywhere); retractions are counted (`retracted 0`) and never served; five of seven stances are the ladder's authored text; learnings and obituaries exist verbatim but never re-enter the next day's text. So the ledger line is buildable NOW from the docket + learnings (the data exists), and thread identity + served retractions are the week's engine work. Park has the only real arc (one ask renegotiated over 16 mornings; 40 commitments held, 1 kept) — that is the serial a reader could follow. Eli is the only third-person voice and has no thread, ledger or record.
- **His words need a channel:** two coaches have asked ~27 times for a morning felt-sense word and nothing can receive it (#4189). The morning note is both his weekly sentence on Home and the coaches' missing input; it is the first engine story of the build week.
- **The skips, in one vocabulary:** journal 17 days, blood-sugar sensor 30 days, blood pressure 17, state of mind 18, Garmin 103; the site says each once, in words, as absence — never as a coach's "he went dark".
- **The cost line is a receipt:** $102.74 this month for one subscriber; Under the hood prints it.

## 15. The measurement baseline (the judge's first live run, 20:00Z, build `5cd8c63`)

A blind Haiku reader, given each door's 390 px fold and the first 1,500 characters of its text, was asked what the page is for and what it would click; a grader scored the answer 0/1/2 against the page's stated intent. **8 of 12: `/` 1 · `/cockpit/` 1 · `/data/` 1 · `/coaching/` 1 · `/protocols/` 2 · `/story/` 2.** Four of six doors are half-understood by a first-time reader after a full day of fold polish — the same verdict as the red team, by an instrument that will run nightly. The v7 cut-over bar is 2 on every door.
