# Handover — Session BH: the first candidate pages graded C to D, two research rounds, and the redesign's direction reset (2026-10-04 13:40Z → ~19:30Z, Fable 5.1, owner on hand)

**Driving instruction:** the owner read the overnight candidate pages and said they looked "so bare bones … only podcast+chronicle", asked whether expert red teams and research on comparable sites had been done (they had not), and then steered the session: grade it honestly, research what makes such a site break out, keep the character sheet and badges, lose no good content, serve a daily reader and a weekly one, and make open design calls without asking ("you just fill in the blanks or recommend"). He will supply his own words by email or through his Claude chat.

## Shipped: 2 PRs merged and deployed to the preview (main green at 9e03b929); 2 more open at wrap
- **#4602** → #4586: the preview front page shows progress to goal, the last seven days as rows of dots, the coaches with the open bet, a labelled one-sentence chapter with Read and Listen, and "the rest of it" as doors. `/api/edition` gained a `week` block and a `life` block; eight routes joined its `SOURCES`.
- **#4603** → #4586: each of the last seven days opens in place to what was recorded that day; today's unlogged training is no reading, never a day without training.
- **#4605** (open, checks running at wrap) → #4586: a page per day (`/next/v8/day/?d=`) and a page per trend (`/next/v8/trend/?m=`, and `?m=lift&x=`), plus one index of trends. A lift's trend is its best set by estimated one-rep max; daily counts are bars from zero with a target line and a seven-day average; each lift shows the best set last time. Steps left the front page's day.
- **#4606** (open, checks running at wrap) → #4583: the coach-moves cast recognises a coach referred to by name.
- **Filed:** #4604 (five served, sitemap-listed pages still show the count of earlier starts), #4607 (`/api/edition` takes about five seconds uncached).
- **Research, private and off-repo:** two reports under `~/.claude/plans/averagejoematt-platform-plan/reports/` ("Journey site design research", "Journey site breakout and virality") with their notes. A content map of all 95 live pages was published privately to the owner.

## Verified live
- `/api/edition` serves `week` (measures, per-day `detail`, `weight_series`) and `life` (eight rows) — read by content at 17:14Z and again after #4603's deploy ("Trained on 6 of 6 days recorded").
- The preview front page renders with the day's weigh-in at 390×844 with no JS error and no sideways overflow; the day rows open.
- `coach-daily-reflection` ran its moves stage for the first time at 19:00Z and wrote `MOVES#2026-10-04` with **zero lines**: the cast chose three speakers by name and `admit_cast` dropped all three as off the roster (read from the stored row's `dropped`). #4606 fixes it; the lines' quality is still unproven.
- `GET /api/edition` uncached: 5.35 s, 4.58 s, 4.56 s (three timed requests), against 0.10 s for `/api/journey`.

## Grades the work received (hard-marked reviewers, unfiltered)
- First candidate front page: called "a chapter landing page"; a design director refused to present it.
- Revised front page: design C+, storytelling C, returnability C to C+, platform as a whole C−, depth D+.
- Four readers on the current preview — would they come back: cold Reddit newcomer D+, non-technical friend D+, quantified-self skeptic C, hiring leader C+ on taking a meeting.
- Day page C+, trend page D+ before fixes; not re-graded after.
- What every reader agreed: the owner is missing from his own page; the one new idea (coaches publicly graded against a simple guess, with bets) is buried three and a half screens down; "Open a day" and "The rest of it" pushed the story down, and "The rest of it" is the old topic menu returning.

## Decisions the owner made
- Keep the character sheet and badges as a feature. Pages marked to retire stay reachable from an appendix at the foot of the site; only exact duplicates redirect.
- Renamed topic sections (Today / Team / Record / Method / Story) are the first version's mistake; he wants a new approach to the design itself.
- He will supply his own words, by email or his Claude chat; design may assume it. The Telegram Tuesday question (PR #4596) is the wrong channel.
- Two rhythms: he returns daily and wants specifics on the last 24 hours; a casual reader returns weekly and wants what is trending up and down, the overall read, and quotes that invite a tap. Coaches likewise speak at three distances.
- Open design calls are the driver's to make. Before he is shown work it is red-teamed with honest grades and grounded in research.

## Gotchas
- **A composed route's cost is the sum of its upstreams.** Eight sources added to `/api/edition` in one morning took it to about five seconds uncached and flapped `site-api-p95-latency-high` twice on cold preview loads. Measure the route after adding a source (#4607).
- **A fixture is not the wire.** The coach-moves cast passed 33 tests and produced nothing live, because the tests cast by id and the model answered with names.
- **The research cuts against two ideas the driver proposed the same day:** opening content in place is the last resort for depth, not the first (days, coaches and chapters should be real pages); and the scoreboard is proof and a source of shareable misses, not the hook — framing the man as a contestant invites wagering on his body.
- **Nothing shows a game layer interests onlookers**, and badges have documented backfire; the character sheet stays by the owner's ruling and should be presented plainly.
- **Step counts are unreliable** (1,113 on a day with 155 minutes of training). They are off the front page's day and carry a caveat on their trend page; the cause is not established.
- **A lift's estimated one-rep max overstates high-rep sets**, so a "peak" from a set of 12 is partly a formula artefact. The page says it is an estimate; it does not yet say this.
- **`gh pr merge --squash` with a custom subject/body is seen by no guard**; use the bare form. An artifact upload rejects a filename containing a question mark.

## Residual / next picks
- **#4607** first: `/api/edition` takes about five seconds uncached; it gates the cut-over and flaps the latency alarm on every cold preview load.
- **#4586**: land PR #4605 (day and trend pages). Then the agreed build order — the owner's words at the top; a page for each settled prediction and the latest on the front page; the front page reshaped into a fixed top line, his dated note, the last settled call and the next, a Today band and a This week band; coaches at three distances; one signature daily mark proposed on a real screen; the character sheet presented plainly; the appendix. Take "The rest of it" off the front page, make the seven-day list one link, and drop the list of individual lifts from the trend index.
- **#4583**: land PR #4606; read `MOVES#<date>` after the next 19:00 UTC run and judge the lines; the 14-day box has not started.
- **#4584**: a lane is building the owner's-words channel (an MCP tool for his Claude chat, and his email replies to the Monday questions) with one store, one filter and one route; find its PR, review, land and prove it with one real note. PR #4596 is superseded; close it with a note once the replacement merges.
- **#4585**: the back-fill is still the owner's write; the Coaches page's examples must be checkable calls (threshold, result, what the simple guess said), not a conditional.
- **#4604**: five served, sitemap-listed pages still show the count of earlier starts; the owner rules per page.
- **#4595**: the scorecard by written rule; consider whether the character sheet's seven areas are that view.
- **#4588**: the cut-over, only after every screen has his yes, five real readers, and #4607.
- **#4587** five real readers and **#4590** the interview — owner-gated; the research found no substitute for either.
- **#4589**: live proofs still due (Tuesday 2026-10-06 off-day brief; the first judge skip; the 14-day projection).
- **#4582**: the page-side contract test and a schema baseline for `/api/edition`.
- **#4540**, **#4546**, **#4593**, **#4531**: unchanged from Session BG.
- not-work — the memory backup to S3: an AWS write outside the stories; run it at the next attended wrap.
- not-work — whether readers may make their own predictions about his outcomes, and whether each day's meals are public: owner rulings; neither is built.
- not-work — why 185 and why in public, in his own words: only he can say; the top of the site and Start here wait on it.
- not-work — the first-person copy on the preview is draft wording; each page says so.

**Build beat:** none — everything this session shipped is on the unlisted preview path, and the reviewers graded it C to D
**Docs:** docs/alarm_citations.json and docs/OPERATING_KNOWLEDGE_LEDGER.md (this wrap); the kit page gate's PROPORTIONALITY row landed in the previous wrap
**Decisions:** none needed — the owner's rulings are design direction recorded in memory and on the issues; no governance rule moved
**Main:** green (9e03b929)
**Incidents:** none — `site-api-p95-latency-high` flapped twice for five minutes on cold preview loads (cited to #4607); no reader surface was affected
**Stash/hooks:** clean
**Closures:** none — no issues closed this session (every PR used Refs) · DoD: scanned 2, hits 1 (#4330 post-close comment from Session BF, advisory), blocking=none
**Backlog:** Now live; #4604 and #4607 filed to Now, #4595 in Next; no promotion made
**Alarms:** 1 flap cited — `site-api-p95-latency-high` → #4607; no uncited alarm red over 72 h
**CI warnings:** 5 — all `SKIPPED in CI — no playwright/chromium`, #3640's deliberate skip notice; no action
**Ledger:** none — no standing machinery shipped this session beyond the kit page gate, whose row landed in the previous wrap
