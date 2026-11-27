# Handover — The Days 2026-11-26 → 27: the shared-timeline figure live on Start, Data and the chapter pages; the character release merged with its history NOT migrated; three other lanes' states carried

## Driving instruction
The owner asked for a substantially better visual experience and told the session to challenge his own heat-map idea rather than implement it, inside the existing Start / Story / Data / System architecture, with no new pages or navigation. Over three rounds he approved "The Days", reduced it on Start, kept the detail in Data, switched the placeholder walker off, removed staves for unmeasured dimensions, and authorised merge and deploy once the normal gates passed. On 27 Nov he accepted it as shipped and returned priority to the corrected character history and the personal-intelligence experience. This wrap also carries the closing states of the two sessions he cleared on 27 Nov and the still-open queue of the 25 Nov handover, so that nothing is lost between them.

## READ FIRST — the character history is in a mixed state from the next nightly compute
- The single character release (#6328, `0f0b574da`) is merged and deployed: `lambdas/health/character_engine.py` is at `ENGINE_VERSION = "1.10.0"`.
- **The historical recompute was NOT applied.** It was attempted under approval on 27 Nov, stopped and rolled back; the session that ran it reports every value restored exactly. A defect in the private tool (#6329) is why it cannot resume or re-apply after a write.
- `lambdas/compute/character_sheet_lambda.py` has no guard against a method change. So the next nightly compute writes the newest day under 1.10.0 on top of history still under 1.8.0. This is read from the code at this wrap, not observed on a run. The 27 Nov row was written before the release deployed.
- Public output is unaffected: the public character still serves "recalculating", Mind is not scored in public, and **#6224 stays OPEN with scores suppressed — it is not closed or corrected.**
- No approval is live. The identifiers approved on 27 Nov are void. A private pre-migration backup and the synthetic probe objects are kept; their locations are in the private register, not here.
- **Owner ruling, 27 Nov: leave the nightly compute running.** The mixed days are accepted until the recompute rewrites every day; no schedule is paused and nothing is reverted. A private reading that jumps on those days is expected, not a defect to chase.

## The Days — what is COMPLETE (merged, deployed, verified live)
- **The figure** (#6320; PRs #6321 `9a0ced07b`, #6325 `3b30c5e24`): `www/src/lib/thedays.js`, `www/src/components/TheDays.astro`, `www/src/islands/thedays.js`. Every day is one column on one time axis; each row keeps its own unit and is drawn by position, never by colour. `theline.js` exposes its geometry; its output is unchanged.
- **Start**: The Line with one stave under it (gym sessions above, whole-day steps below) and one counted observation; the six portrait tiles and the "three measured, three not yet" line are gone; the 8 November quotation and its provenance stay; the Life card reads "measured in part".
- **Data**: the full figure — every stave, lenses that only count days, a range with a pager (a phone opens on four weeks), the day readout with its links, the same days as a table. **Chapter pages**: the chapter's own days. **System**: a link to the figure, no second figure.
- **A partial food export is labelled on its day page** (Refs #6195): `DAY_PAGE_PARTIAL_LABELLED` is on. Read on the live record first: exactly one Day object changed (21 November); no other number moved. The other three computed switches are unchanged by owner ruling.
- **Verified**: root deploy run 45994128809 on `3b30c5e24` — sync, smoke, visual and AI-vision QA and the public-copies guard all succeeded, no rollback, recorded as the previous green build; the live pages were then read back by content (the evidence is on #6320).
- **The root smoke's page assertions are held before the publish** (PR #6327 `6e7ddc82a`, Refs #6320): `scripts/www_smoke_pins.py` reads the smoke script's rows and `check_www_build.py`'s scan holds the built pages to them. Proved both ways.

## The Days — NOT done, stated as such
- **Safari itself (Mac, iPhone) and Firefox are unverified** (WebKit through Playwright passed 81 of 81). By owner ruling no compatibility initiative is opened; an actual defect is fixed when found.
- Day, week and month views, a colour overview and the proper walker are not built and not scheduled: the owner will judge the live experience first. No further Days work or reports until real use and real readers say what it needs.

## The Days — gotchas learned
- **The first publish was rolled back** (run 45984492062): one row of `deploy/smoke_test_site.sh` still asserted the removed portrait tiles (301 of 302 passed). PR CI never ran that script.
- **Two more pins the www gates do not run**, both in the 35-minute unit suite: the front page's reach ceiling of 15 (`tests/test_site_nav_reach_ratchet.py`) and the page intents in `qa/qa_manifest.py` (30 words).
- **A `deploy/`- or `qa/`-only fix does not trigger the v9 deploy**: dispatch `web-preview-deploy.yml` with `target=root` and read that run.
- **Semantics checked before publishing**: the public `steps` series is the whole-day count, not walks; a "session" is a logged gym session, so a day without one is not a rest day; a heavier set at fewer reps is not a like-for-like gain, so the lift stave joins only sets of the same rep count.
- **The public Day object did not carry the partial flag the series already honoured**; the figure reads food from the series for that reason.
- **A release window is a reason to hold every other commit to `main`**: this wrap and #6327 waited behind the character release by owner decision.

## Personal-intelligence lane — closing state, 27 Nov (session cleared by the owner)
- **Shipped and verified live**: #6285 (PR #6297), #6286 (#6301), #6287 (#6300), #6288 and #6289 (#6296, #6309), #6292 (#6308), #6303 (#6306), #6294 (#6322, superseding the closed #6317); #6298 and #6318.
- **Deployed, never exercised — do not record as verified**: #6290 (PR #6295) evening and weekday-morning holds; #6302 (#6304) narrow event rules; #6291 (#6307) shared context, switch off; #6312 (#6313) corrections reach the absorbing coach and the brief reads the stored scan; #6303's distress safeguard, which must never be triggered live as a test. No complete real conversation ending in a reviewed save has been observed for ask, reflect, the profile or hypotheses.
- **Open PRs**: none. Its method and private-tool PRs went in through #6328.
- **Awaiting the owner**: whether the shared-context switch may be turned on, after he reads the private dry render; the two held Telegram texts. The skill re-upload is done.
- **Its own error, recorded by it**: #6313 merged without a re-run on #6307, one pinned test red on main, fixed by #6318.
- **Found, not fixed**: an owner ranking tool still counts profile disagreements; one page-speed overrun on a coaching index page (2.68 s against 2.5 s, run 45962069227).
- The AI budget tier was 1 at its last read: internal and development AI calls are paused at that tier.

## Privacy and recompute lane — closing state, 27 Nov (session cleared by the owner)
- **Shipped and verified live**: #6328 (`0f0b574da`) — the final scoring method, both recompute tools, the public v3 projection and event reconciliation; main's CI/CD run 46054157248 succeeded including smoke and visual QA, and the deployed bundles are stamped with that commit. Earlier (Refs #6224): #6277, #6278, #6279; #6282; #6281; latency and pagination #6276, #6305, #6310, #6316 (Refs #6271); #6273 (Refs #4531); #6324; docs #6280, #6298.
- **Merged, not verified live**: #6275 (Refs #6270) until the 29 November field-notes run; #6274 (Refs #6268), the qa-smoke alarms were still red.
- **Open PRs**: none. #6283, #6299, #6314, #6319 and #6323 are closed as superseded by #6328.
- **The attempt**: the recompute was attempted under approval, then stopped and rolled back. The private tool's replay depends on the field order of stored records, so it cannot resume or re-apply after a write (#6329). Values are restored exactly; the restored score records now carry their fields in alphabetical order, which is harmless to scores and is why the old plan no longer reproduces. The public plan identifier changes when a release deploys, so a final dry run must be taken after the deploy.
- **Next attempt, in order**: fix #6329 → one combined dry run after any deploy → the owner's fresh approval of both new identifiers → the private apply in a single pass → the public apply → the archive rebuild → the PR that lifts the suppression → the deferred site-API memory trial.
- **Awaiting the owner**: that fresh approval; the five-person reader test, which is his to run.
- **Found, not fixed**: `/api/edition` about 5.6 s and `/api/chapters` about 5.0 s uncached; `/api/habits` computed metrics will truncate around April 2027; empty restraint keys in `/api/mind_overview`; registry classification debt (#6315); a date-boundary fixture in `tests/test_site_api_derived_phase_4088.py` that failed once at 08:20Z on 27 Nov and has passed since.

## Backlog — a portfolio reset was applied on 27 Nov (another session, owner-approved)
- 49 issues and 13 epics were closed with ADR-099 verdicts; open issues went from 172 to 115; `Now` holds 11 stories and 3 epics. Five issues were filed: #6330–#6334. No code and no merges.
- Epic consolidation: the training epics #5050, #5051, #5067, #5770 and #5861 into #6014; #5925 and #5926 into #5946; #5134 into #5928; #5945 into #5539; #6206's outcome into #6158; #5529 closed (v9 live since 1 Nov), its open stories #6114 and #6135 now under #5946.
- Left open on request: #6195 (moved to `Next`), #6224, #6329, #6311, #6293, #6271, #6270, #6268, #6315, #6227, #6223. #4531 was to be checked before closing: the week-12 draft is still held and its alarm is red.
- **The 25 Nov queue carried below predates that reset.** A line citing a closed issue (#5067, #6206 and others) now belongs to the epic it was folded into; read each state fresh before acting.
- That session continues after this wrap; its own wrap must carry this handover forward, not overwrite it.

## Carried from the 25 Nov handover — awaiting the owner (verbatim; archived as `HANDOVER_2026-11-25_Editorial-Overhaul.md`)
- The five-person unprimed reader test (approved; who and when).
- Two optional questions put to him for the human centre of the new feature (why 30 September had no logged session; whether he knew of the wrong scoreboard grades at the time). Never inferred.
- Release or keep holding the between-chapters email, after reviewing its render.
- Corrected Episode 0 audio (his listen); Episode 4 stays held.
- Whether the pre-experiment weight series (back to January 2024) should stay publicly served.
- The private weekly recap card prints a count that includes private categories; three related outlets are unswept (a character-sheet effect, the temptation resist-rate, the challenge catalogs).
- Week 6's superseded interview correction text (hide it or not); Week 5's lab-reference sentence on its historical page.
- The Evening Ritual row in the nightly nudge, and whether two weekly probes that lost their only collection route should be collected another way.
- Activation of the recommendation pilot.
- His draft priority statement (never written into his record as his words).


## Residual / next picks
This session's lines first; then the 25 Nov queue, verbatim. Each line cites its issue or is tagged not-work.
- #6329 — the private recompute tool cannot resume or re-apply after a write; fix it before any further attempt.
- #6224 — OPEN on purpose: scores suppressed, the history not migrated; by owner ruling the nightly compute keeps running, so days from 28 Nov are under the new method on old-method history until the recompute rewrites them.
- #6311 — `swallowed-permission-denial` entered a new ALARM episode on 27 Nov and its citation is stale (written 31 Oct, pointing at closed #5220 and #5476); the live cause was not re-derived at this wrap. A denied private probe in the recompute lane that day is the likely cause, unverified.
- #6195 — three computed switches still off; each needs its before-and-after read first.
- #6271 — `site-api-p95-latency-sustained` fired and cleared inside the last 72 h; the uncached reads above are the standing cause.
- #6320 — `www/src/pages/index.astro` still computes the portrait dimensions for the Life card's count; the tile markup is gone. Cosmetic. `www/README.md` has no row for The Days yet: add it with the next `www/` change, since a commit there triggers a root deploy.
- #6291 — the shared-context switch is off; its activation is the owner's, after the private render.
- not-work — the date-boundary fixture in `tests/test_site_api_derived_phase_4088.py` has no tracker yet; file one if it reds again.
- not-work — the owner's own actions: approve two fresh plan identifiers once #6329 is fixed; run the reader test; judge The Days from real use.

- #6240 — confirm the compact brief over the observation period (reading burden, repetition, accuracy, quiet days); the homepage of the release measures 7.61 phone screens on live data against the 7.5 budget.
- #6245 — verify Saturday 28 Nov's short Nutrition Review: three-minute format, menu and shopping list intact, complete-day count in the subject; then the Monthly Coach's Letter.
- #6243 — keep open until the send log shows the Sunday "what changed" email and no Weekly Report on 29 Nov and again on 13 Dec; first real QA failure should land in the digest with no email.
- #6244 — the between-chapters note is held in code and its schedule is disabled; re-enable the schedule only after confirming the deployed code hold, release only on the owner's review; check the Weekly Signal's Sunday send.
- #6158 — the recommendation pilot is deployed dark; first real offer, response and outcome are unproven; activation is the owner's.
- #6237 — many roles can still write the recommendation-record partition; a separate, tested least-privilege change.
- #6149 — coach context stays off until the next pilot passes the known-answer cases (#6226); draft #6215 waits on it and its lane lock stays.
- #6223 — the public-copy manifest: images, CI artifact uploads (eight upload steps remain), generated public JSON; a bounded retry on the guard's anonymous fetches; quarantine ordering (repo change first).
- #6224 — remaining guard fixes: the stale 190 g example in the coach extraction prompt, the text rule on stored corrections, the spoken Episode 0 line, real-render tests; the publication gate treats a withheld row's frozen engine text as withheld words.
- #6227 — write-once forecast registration before forecasts are cited as a track record.
- #6225 — Experience Health scorecard weeks 2–4, by hand, from 30 Nov.
- #6258 — Chronicle reading experience: correction presentation, human-centred progression, chapter naming; any further chapter treatment needs the owner's approval.
- #6259 — reader journey: two page designs still coexist; `/story/moments/` has no in-site link; the three "What happens next" questions are collapsed on the homepage.
- #6260 — subscriber journey.
- #6211 — a recommendation carrying a finding link has never been recorded; #6209 and #6210 wait on a real experiment.
- #6206 — the research finding has had no coach review; two manual research reviews are approved and not started.
- #5067 — the tape and photo cadence change is deployed; a real entry has never exercised it.
- #5928 — `qa-smoke-warnings` is red on persisting warnings; read its `PERSISTENT` line before acting.
- #6256 — the token-rotation date PR is open, docs only; merge when green.
- #6271 — the site API's first uncached read of `/api/chapters` and `/api/edition` takes 6–9 s since the second editions went live (the latency alarm flaps 26–45 times a day); cause not established.
- #6268 — three QA checks lag sanctioned changes (legacy 301s read as a blackhole; a withdrawn chapter expected by the recall sensor; a month-rounded age against a 20% tolerance); they hold `qa-smoke-failures` red.
- #6269 — the census probe's 6 s cap times out on the same slow reads.
- #6270 — the weekly field notes were held by the grounding gate two Sundays running; the generator keeps producing ungrounded drafts.
- #4531 — `chronicle-delivery-heartbeat` is red correctly: the 25 Nov Wednesday draft awaits the owner's approval; with chapters no longer weekly, its seven-day expectation needs a ruling.
- #5515 — three guard gaps from this week's incidents: the fleet deploy script is not on the ask list, unquoted heredoc bodies are read as data, nothing checks the branch before a pull in the shared checkout.
- #6224 — the incident procedure calls for a focused privacy review after an exposure (three rows this week); not run, because the owner ruled out new broad audits — his call.
- #6216 — a docs-and-config patch for the narrator's configuration twins was not applied at this wrap (it changes `config/` files); it and four stale docs patches (#6176, #6194, #6199, #6158) need regenerating against main.
- not-work — five auto-maintained ADR-count figures update through the post-merge reconcile job after this wrap is pushed; confirm they read 172 / ADR-174.
- not-work — the owner's own actions: approve or decline the 25 Nov chapter draft; answer the two optional questions; choose reader-test participants; listen to Episode 0; send the coach question; book the scan; log a tape and photo entry.
- not-work — observation-period notes are due on 30 Nov and 7 Dec; routine progress otherwise on request.
- not-work — the reconcile token's scope has not been checked on its settings page (an owner look); its settings are recorded privately and are not restated in public text.

**Build beat:** none — the owner asked for no further reports on The Days; its feedback comes from readers.
**Docs:** `docs/INCIDENT_LOG.md` (one row + patterns) · `.claude/skills/land/SKILL.md` (the smoke-assertion rule) · `docs/OPERATING_DISCIPLINE.md` §3a.8 (times told to the owner are Seattle time) · `docs/OPERATING_KNOWLEDGE_LEDGER.md` (seven rows).
**Decisions:** none needed — a figure inside the existing site architecture, under ADR-104 and ADR-105 as they stand.
**Main:** green (a6a708a8) — the run on `6e7ddc82a` (#6327, gate code only) was still in progress at this wrap; read it before relying on it.
**Incidents:** 1 row added — the first root publish of The Days rolled back on a stale smoke assertion.
**Stash/hooks:** clean · worktree-reap removed 30 and released 24 merged locks; the recompute lanes' worktrees were left in place and are releasable.
**Closures:** #6320, #6290 commented · DoD: scanned 64, hits 1 after commenting — #6320's post-close comment is the release evidence and the owner's acceptance, not-work.
**Backlog:** not refilled here — an owner-approved portfolio reset the same day left `Now` at 11 stories and 3 epics (172 → 115 open); no Later sweep at this wrap.
**Alarms:** 2 uncited — named: swallowed-permission-denial (new episode 27 Nov, stale citation, cause not re-derived), site-api-p95-latency-sustained (a flap, #6271).
**CI warnings:** 6 — one identical annotation six times: a Playwright test skipped where the job has no Chromium (#3640, closed as designed); no action.
**Ledger:** none — a check added inside the existing build gate; no new standing subsystem.
