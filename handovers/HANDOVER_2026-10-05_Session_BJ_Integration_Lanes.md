# Handover — Session BJ: seven lanes built and combined in one integration PR, red-team round 7, and a merge the permission check refused (2026-10-05 02:40Z → ~04:40Z, Fable 5.1, owner on hand at the start, then autonomous)

**Driving instruction:** `~/.claude/plans/next-session-prompt.md` — ask the owner nine questions first, check the laptop AI cap's deploy, then build #4647, #4650, #4618, #4648, #4649, #4607 and #4652 in that order, red-team before he sees anything, and wrap. Mid-session he asked for more parallel work (a second session took backlog items from a pasted prompt) and then said to keep going through the night autonomously.

## Shipped: nothing merged, nothing deployed — this handover rides the PR that carries the work
- **`gh pr merge 4656 --squash` was refused by the auto-mode permission check ("Merge Without Review")** with all ten checks green and `scripts/assert_pr_green.py` passing. It was not worked around. The owner was told at once with the two ways out (he merges, or he adds a permission rule).
- **PR #4669 is the one integration PR.** It merges the seven lane branches, reconciles them, and carries the round-7 fixes and this wrap. When it merges, lane PRs #4656, #4657, #4658, #4659, #4660, #4661 and #4665 are redundant and close as landed-through.

| Lane PR | Issue | What it does |
|---|---|---|
| #4656 | #4647 | every Right or Wrong prints the rule that decided it (`site/assets/js/ck_verdict.js`, the one place a verdict tag is written); the Coaches pair leads with a narrow hit and a clear miss |
| #4657 | #4650 | "How it's built" states an ordinary day and the high days separately; `/api/receipts` serves `typical_day`, `high_days` and `ai_scheduled_share_pct` |
| #4665 | #4618 | a number call's target day comes from its own sentence; a due date over a year out is refused; `scripts/regrade_tomorrow_calls_4618.py` (dry-run by default) |
| #4660 | #4648 | the day page shows that day's coach lines and settled calls; new `GET /api/coach_moves?date=` inside the existing site API |
| #4659 | #4649 | a deterministic plain-words check on a coach's watch list at write and at serve (`lambdas/coach/plain_words.py`); the ladder served beside the stance; `working_hypotheses` leaves the route's contract |
| #4658 | #4607 | `/api/edition`: a narrow record reader, the dashboard without its unread dossiers, four reads at a time, an 8 s deadline, a latency budget guard |
| #4661 | #4652 | a skipped AI check says so in four places and is never a pass; `ci` joins the cost governor's month-end projection |

- **On top of the lanes (commits on the integration branch):** the day page's settled calls use the shared verdict tag; the two forecast sentences on "How it's built" follow the served `projected_classes`; the round-7 fixes below.
- **Filed:** #4671 (the kit page captures disagree with each other), #4672 (the coach prompt drops the forecast's target date and coaches invent one), #4673 (a benched coach's settled-bet argument cites sensor data), #4674 (week 2's episode and chapter titles differ; "pace flag" in an excerpt), #4675 (deep pages do not link both ways), #4676 (gendered pronouns in two S3-held coach configs, owner-gated). Comments on #4649, #4617, #4646, #4607, #4650 and #4652 carry the round-7 findings and each lane's measured tables.
- **Published for the owner:** four drawings of the daily mark at phone size with real weigh-ins, a private page at https://claude.ai/artifact/QwqPrzXP8SxDkSuEbL2whP (#4646).

## Verified
- **The laptop AI cap (#4623):** the CI/CD run for a4149347 finished with its Deploy job green. Budget tier read 0; `/life-platform/remediation-mode` read `off`.
- **PR #4653 (another session's habits merge):** its main run failed at Plan; `habit-skip-review` showed `LastModified` 02:19Z, after the failure, so that session deployed it by hand. Not touched here.
- **Tests on the integration branch:** `node --test tests/js/*.test.mjs` 748 pass, 0 fail. `pytest tests/ -n 8`: 31,575 passed, 1 failed, 59 skipped, 36 xfailed — the failure (`test_branch_never_carries_platform_counts_3984.py::test_must_fail_a_deleted_field_off_main_is_still_a_red`) ran while a commit landed on the branch mid-suite, and the file passes alone (14 passed). The suite was not re-run after the last two commits; CI's full pre-merge suite on #4669 is the reading to trust. `tests/kit_page_gate.py` clean.
- **Not verified, because nothing deployed:** every live proof the seven issues ask for.

## Red-team round 7 (seven fresh reviewers, a local render of the integration branch; full text in the private red-team file)
- **Flat or down.** Design director: front page C+, daily mark D+, system B−, verdict tags C+, cost section D. Story editor: storytelling C, daily return C−, weekly return C+, the day page C, the cast C−. Product lead: 20-second read B, depth C, wayfinding C−, coherence C. Newcomer: first screen B, unique B−, back tomorrow D+, would send C−. Friend: ten-second read C, feel him D, coaches C−, open in a month D+. Skeptic: novelty B, honesty C+, more than a gimmick C, return C−. Senior leader: understand B, controls C+, honesty B+, meeting B−.
- **What the changes did:** the rule beside the verdict works on a tight call and exposed a loose one — "Right · within 22.5 either way" on the front page's lead call read as rigged to six of seven. The day page worked on a day with coach lines (October 2 was called the best unit on the site) and reads as a ledger on a day without. The plain-word watch list is plain and nearly empty; the jargon moved to the pending calls on the same page. The cost split landed in its first sentence and was buried by four paragraphs of tier arithmetic.
- **Fixed the same night:** the front page leads with the clearest miss and says the simple guess only when it has a result; the cost section is three plain figures and the laptop cap, with the high days, forecasts and tier sums behind one disclosure; step counts are off the day page; a measure recorded on fewer than five days is not filed under "Not going well"; a coach page accounts for every waiting call; an area held for thin coverage prints no score and the front page states the sheet's own count of areas; today's row reads "Today so far".
- **Not real, per a second-pass verifier against the live site:** the 41-of-96 against 45-of-106 record mismatch (the kit captures were taken on different days; live routes agree); the audio player at 0:00 (the files load); "The fix" as a broken sentence (it is link text); "no manual approval step" (accurate — only the IAM deploy is gated; the stale sentence is this repo's CLAUDE.md, which still says "Deploy (manual approval…)").
- **Still capped by owner-only items, all seven reviewers:** his dated note and question; the #4585 back-fill; the #4617 ruling.

## Gotchas
- **A merge can be refused outright in auto mode.** Try the first merge early in an unattended session, while the owner may still be there; if refused, the night's shape is lanes → one integration branch → red-team the local render → one PR.
- **The kit captures in `tests/fixtures/kit_pages_4586/` contradict each other** (`edition.json` and `coaches.json` are from October 3; `predictions.json` and `coach_*.json` from October 4). Every reviewer marked the mismatch against the live site, which does not have it. Re-capture them in one pass before the next render (#4671).
- **Printing a grading rule can lower a grade.** The tolerance on a recovery call is the metric's usual day-to-day swing (about 22 points of 100); shown beside "Right" it reads as soft grading. Lead with tight calls and clear misses.
- **`/api/edition` is CPU-bound, not I/O-bound.** About 46% of one read was botocore parsing DynamoDB JSON; a thread pool alone would have moved 4.8 s to about 4.3 s. Narrow readers did the work.
- **Only 37% of the two AI checks' cost scales with merges.** The daily prose pass and manual full-surface runs are the larger part, and the reader-surface skip had already shipped in #4598.
- **Only one of the eleven "tomorrow" calls in #4618 says "tomorrow".** Ten pending calls were due in 2029, 2032 and 2065 because an ISO date in a time hint was read as a number of days.
- **A PR-checks watch started before a push reports on the old head.** `assert_pr_green.py` said "not green" because the full suite had not attached to the new head yet; re-read the checks after every push.
- **A shell command that `cd`s into the memory directory resets the working directory to the main checkout.** The next relative command then runs outside the lane.

## Residual / next picks
- **#4580**: merge PR #4669 (the owner, or a session once `gh pr merge` is allowed); then close the seven lane PRs as landed-through, release their worktrees, confirm the CI/CD run deployed, and re-run `site-deploy.yml` once `/api/coach_moves` answers 200.
- **#4650**: after the site API deploys, recapture `/api/receipts`'s schema baseline (three new keys were baselined from the branch's own output).
- **#4648**: capture `/api/coach_moves`'s baseline live, drop its two exemptions, and rule on `ARCHIVE_ROUTES`; "a day with coach lines shows them" is held by a fixture only until a real day has lines.
- **#4649**: `python3 deploy/capture_api_schemas.py --only /api/coach/ --check-drift` after deploy; the next stance run is Sunday 2026-10-11 17:00 UTC; run the plain-words check on a call's sentence at generation (comment on the issue).
- **#4607**: post 20 cache-busted `/api/edition` timings and the `[edition] upstream_ms` table, re-pin `SOURCE_COST_MS`; the estimate is 1.4–1.8 s, so the 1.5 s bar may need narrow readers for training and nutrition or an owner-run memory bump.
- **#4652**: read `/life-platform/budget-breakdown` after a governor run; the first real SKIP's log line; seven days of per-day cost. The owner should confirm the forecast moving from about $222 to about $256 once `ci` is counted.
- **#4618**: `python3 scripts/regrade_tomorrow_calls_4618.py --apply` is the owner's write, after deploy (dry-run again first): 1 re-grade, 2 withdrawals, 11 re-specifications on October 4's data; the record moves 45 of 106 to 43 of 105.
- **#4647**: on a coach's own page the tolerance prints with no unit, and a bet row in the call list has no separate rule; both need the routes to serve more.
- **#4671**: re-capture the kit fixtures in one pass and add the cross-fixture test — before any further red-team render.
- **#4675**: wire the deep pages both ways and return the reader to where they came from.
- **#4672**: print the forecast's target date on the coach prompt line; confirm the summary row's item shape first.
- **#4673**, **#4674**, **#4676**: as filed; #4676 needs the owner's yes for an S3 upload.
- **#4646**: the owner's words on the four drawings; C (the year frame) needs a goal date from him.
- **#4584**: one real note from the owner; then re-capture the `/api/owner_words` baseline (#4615 holds the first capture and its archive ruling).
- **#4585**: the back-fill is still the owner's write; the skeptic's largest ask is the simple guess's score at the headline.
- **#4617**: the ruling on conditional and commentary-derived calls; a direction call that stays needs its window's start and end readings served (comment on the issue).
- **#4583**: read `MOVES#2026-10-05` after the 19:00 UTC run and judge the lines; round 7 says a day with coaches disagreeing is the site's best unit.
- **#4604**: nine pages held out of the appendix; the owner rules per page.
- **#4644**: the data-source sweep's rulings docket; **#4645** merges only on the owner's say-so and its locked worktree stays.
- **#4651**: the repair agent reads `off`; the owner confirms whether that is the ruling.
- **#4588**: the cut-over still waits on every screen's yes, five real readers and #4607.
- **#4257**: the refill plan names it for the Fable lane; its PR #4544 is owner-held, so no promotion was made.
- not-work — the front page does not yet lead with an open disagreement between coaches (the round-7 ask); it needs a day with real coach lines, which #4583 feeds.
- not-work — the draft first-person lines on the preview are still draft wording, each marked so; the owner keeps, rewrites or strikes each.
- not-work — a second session ran backlog paydown from a pasted prompt (#4259, #4191, #4411, #4635, #4637, #4631, #4538, #4250); its PRs #4664, #4666 and #4667 were open when last read and it was told to leave this handover alone.
- not-work — the repo CLAUDE.md's CI/CD line still says "Deploy (manual approval, GitHub Environment `production`)"; since ADR-158 only the additive-IAM deploy is gated. It is a one-clause fix for a session that is already editing that file.

**Build beat:** none — nothing this session built is merged or deployed
**Docs:** docs/OPERATING_KNOWLEDGE_LEDGER.md (two rows); docs/CONVENTIONS.md §9, docs/SCHEMA.md, docs/PROPORTIONALITY.md, docs/ONBOARDING.md, docs/engines/COACH_STANCE.md and docs/qa/SURFACE_DRIFT_EXEMPTIONS.md changed inside the lanes
**Decisions:** none needed — no governance rule moved; counting `ci` in the governor's projection is what #4652 asked for and is parked for the owner's confirmation on PR #4669
**Main:** green (6db5d7c5)
**Incidents:** none — the refused merge is a permission outcome, not a platform event; no reader surface changed
**Stash/hooks:** clean
**Closures:** none — no issues closed this session · DoD: scanned 0, hits 0
**Backlog:** Now live; this session filed #4671 to #4676 (#4671, #4672, #4674 and #4676 to Now); no promotion made — the refill plan's pick, #4257, has an owner-held PR
**Alarms:** every alarm red over 72 h is cited; no uncited flap in the window
**CI warnings:** none on the latest green main run (6db5d7c5)
**Ledger:** none — no standing machinery shipped (one test-held latency budget and one skip report ride existing gates; `docs/PROPORTIONALITY.md`'s reader-surface row was amended in the #4652 lane)
