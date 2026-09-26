# Handover — Session AV: the site night — a site a friend can read (2026-09-25 21:30 PT → 2026-09-26 ~01:10 PT)

**Fable 5.1.** Booted as "planning only — a worktree, no merges" while AU landed #4179/#4181. At ~21:35 PT the owner re-scoped it in one message: *"I don't like averagejoematt.com. I have not used it in the 3 weeks of this experiment, and friends who go to it are overwhelmed with the layout, the content, what to do, and even some of the words … and 'AI coaches' isn't all making sense. I have 85% of Fable usage for the week and I want all of that power to evolve this website."* Then, before sleeping: merge authority on site PRs — yes; the pillars call — "you decide and red team"; the interview questions — "use board personas or pretend elite people". Standing rules kept: engine PRs open, never merged; no `aws s3` on `config/`; no `aws lambda invoke`; no CDK.

## What shipped (merged AND deployed — all under epic #4182)

| PR | slice | live proof |
|---|---|---|
| #4195 | **the front door** — the #789 "Is he okay this week?" read moves from ~2,250 px down to directly under the claim; one-sentence setup; the coaches defined once (software, not people); three doors as sentences; the loop dial retitled "How the pieces fit"; the "transformation you can watch happen in real time" suffix struck; the eating chip no longer claims "some days went unlogged" on a 20/20-logged week | deploy `0e83e4c` 06:12Z, smoke ✓ visual+AI QA ✓ no rollback; read back 06:16Z at 390 px: the read sits at char 504 under the claim, zero JS errors |
| #4197 | **the chronicle opens on its first sentence** — `chronicle_text.js` strips the re-embedded title + the `[Weight: … \| T0 Streak: …]` line at the entry boundary; the stat line renders as words | deploy `091d752d9`, all gates ✓; `/story/` and `/` carry zero `[Weight` (comment on #4191) |
| #4198 + #4201 | **the registries** — `site/data/glossary.json` (15 ruled terms) + the shrink-only vocabulary guard + the static-reach ratchet (39); #4201 excludes `<noscript>` bakes (served coach text is never builder vocabulary) and tightens the ledger | tests + one JSON; 15 registry gates PROVEN in the census (ceilings 748→763 / 197→212) |
| #4200 | **the cockpit** opens on "How's the week? / Last night? / Today?" from served fields; the level demoted to a collapsed, plain-keyed section (tier name + XP off the reader surface); the "NEW HERE?" cards on the cockpit and every `/data/*` page → a one-line strip with inline `<dfn>` glosses; the null readiness ring removed | deploy `a013d5e50` 06:35Z: live read 06:59Z — three questions rendered, `data-state=ready`, zero errors; the gate's own check red (see Incidents) |
| #4199 | **the coaching door** — today's read chosen by a stated chain (open ask → best checked record at n ≥ 10 → freshest; tonight Dr. Lisa Park, 7 of 16 held up, the reason printed), written-time in words, the weekly call labelled weekly, >48 h banner with engine deltas, "Third Wall" cut, `/method/board/` states its weekly cadence (the open half of #4163, comment there) | deploy `a19d915` 06:59Z: live read 07:05Z — Day 21, the read + the reason, "Third Wall" ×0, zero errors |
| #4203 + #4204 | **the gate fixes-forward** — a collapsed `<details>` element is not empty (`tests/visual_qa.py`); the record link gets a real underline (axe `link-in-text-block`) | #4204's deploy (`459aa84fc`) is the run recording green — see `**Main:**` and the Incidents row |

**Engine PRs opened, NOT merged (outside the grant — morning ask 7):** #4192 (`open_actions` from the dossier reader), #4193 (the genesis-bounded weight-trajectory window), #4194 (the #4180 trend classifier + coach-vs-coach / coach-vs-engine legs, 29 tests), #4196 (tool-call residue guard on every registry-classified write door + serve-time strip + sweep tokens). Each green-checked, each `Refs`.

## The method (it worked; reuse it)

Four read-only audit lanes in parallel (B1 newcomer/friend, 60 screenshots · B2 the subject's morning screen from served JSON · B3 vocabulary census + coach-vs-coach · B4 the #4163 triage) → the driver re-verified every truth claim live → a Fable red-team panel (Product Board personas + Matthew/a friend/his mother/an editor) produced the rulings, the final ≤120-word first screens, a nine-item "not tonight" list and a dissent register → Opus lanes for the two front-end slices, Sonnet for engine → every PR rendered with a local harness that routes `/api/*` + `posts.json` to saved live JSON (`scratchpad/harness/render.py`; `pr_render_gate.py` is empty-mock and structurally blind to data-driven layout). The end-to-end plan is `docs/SITE_TRANSFORMATION_V6.md`; the rule it sets is ADR-156.

## Truth defects found live (all verified by the driver)

- Two loss rates: `public_stats` −4.36 firm with a 2027-04-20 goal date vs `/api/journey` −4.58 provisional — daily-metrics-compute's flat 28-day window crosses the genesis (#4184, PR #4193).
- The nutrition coach's "six days without logs" against 20/20 days logged (139–186 g each); five protein figures on one page; "4:45 AM onset" is 04:45Z (#4185).
- `open_actions` `[]` with ≥9 commitments pending (#4187, PR #4192); no daily lead read (#4188); no morning-note ingest (#4189).
- A raw tool-call tag served in `/api/decisions` and rendered as prose (#4190, PR #4196); the chronicle's bracketed stat line (#4191, site side live).
- The QA leg compares coach-to-cockpit only (#4186, PR #4194); the vitals leg fails trend sentences (#4180, same PR — what keeps `qa-smoke-failures` red).
- 24 pre-genesis orphan drafts keep `qa-smoke-warnings` lit; the 09-21 citation expired 09-22 (#4183; the citation now cites it).
- #4163: NOT time-of-day (my first comment was wrong, corrected on the issue) — same-day judge fixes between the morning schedule and the evening dispatch.

## Gotchas

- **`safe_merge.sh` does not exist** (named in AU's handover; nowhere in the repo or its history). Merged via `scripts/assert_pr_green.py` + `closingIssuesReferences` + a trailer grep + squash.
- **`lane_worktree.py` resolves its parent from the invoked script's path** — run it by the main checkout's absolute path, or lanes nest under `worktrees/av-plan/` (two did; released and removed).
- **`gh pr checks` cannot see a queued workflow run** — a "nothing pending" watcher declared PRs terminal while `PR checks` was queued; the run-level watcher (`actions/runs?head_sha=`) is the honest one.
- **The gate census names a registry gate `BASELINE[<entry>]`** and refuses a proof whose `gate_name` differs; every new `BASELINE`/`*_EXEMPT` dict entry is a gate that must arrive PROVEN (`observed` must say "failed"); every `BASELINE_TOTAL_GATES` bump conflicts across concurrent PRs (three bumped it tonight; lanes merged `main` in, never rebased). A tree-sweeping test also needs a `tests/conftest.py` pre-merge classification (#2372) and a `MutationSpec`.
- **One lane force-pushed its own lane branch** (`--force-with-lease`, only its own commits) after I wrote "rebase" in a brief — my wording invited a breach of the no-force-push rule. Lanes merge `main` in; "rebase" is not a word for a lane brief.
- **The visual gate's `not_empty` read hidden text as empty** (fixed, #4203); **CodeQL flags a single-pass `<tag>` regex strip even in a test helper** (loop to a fixed point); **the doc-index gate accepts only `canonical|generated|log|superseded|archive`**; **the harness's `_main.txt` reads `<main>` only** — content promoted above it needs the body dump; **the vocabulary census must skip `<noscript>` bakes** (#4201). The memory backup `aws s3 sync` and any `config/` read were NOT run unattended (the AR stall class) — ask 8 below.

## Residual / next picks

- **Owner's morning list** (`docs/SITE_TRANSFORMATION_V6.md` §7, one numbered list): door labels · the home headline · the level name off reader pages (shipped in #4200; the one-line revert is named in its body) · the page cap number (24) · unlink glucose · the subscriber counter · merge + deploy the four engine PRs (#4192 #4193 #4194 #4196 — one fleet deploy + `deploy_site_api.sh`) · the 09-08 DDB record scrub (#4190) + the published chronicle bracket (#4191) · photos #3761 · run the memory backup sync (`not-work — an unattended aws write; the owner runs it`).
- **This week's site work — stories to file after the owner's review, under #4182:** the data and protocols door copy + one number in each fold; the story fold + the "next write-up Wednesday" return trigger; the vocabulary passes door by door against `site/data/glossary.json`; the nav labels once picked; `/subscribe/` field-in-fold + the "Measured Life" title; the glucose honest state (`not-work — filed as stories once the owner rules on §7; the epic carries the list`).
- **Live proofs to read:** #4180 + #4186 after the qa-smoke deploy (the next nightly); #4184 after the next daily-metrics-compute run; #4187 (`open_actions` carrying the 10-02 commitment); #4188 stays open on the daily lead read; #4191 write side; #4202 auto-resolves on #4204's green run; #4163 auto-closes on the next green scheduled visual-qa.
- Everything AU listed stays as AU left it: #4168's cardio-day read (#4158), #4177, #4178, #4172, #4174, #4171, #4170, #4166, #4065, #4076, #4149, Sunday's probes (#3552, #3712, #4111), #4034, #3607/#3593 (10-06), #2978 (10-19).

**Build beat:** 2026-09-26-a-site-a-friend-can-read
**Docs:** docs/SITE_TRANSFORMATION_V6.md (new, indexed) · docs/SITE_MAP_AND_INTENT.md (three doors' must-deliver amended, Verified bumped) · docs/CONVENTIONS.md §9 (+2 gate rows, in #4198) · docs/DECISIONS.md (ADR-156 + index) · docs/INCIDENT_LOG.md (+2 rows, Patterns regenerated) · docs/alarm_citations.json (qa-smoke-warnings → #4183) · docs/PROPORTIONALITY.md (+1 row) · docs/OPERATING_KNOWLEDGE_LEDGER.md (+3 rows, snapshot) · CLAUDE.md status block
**Decisions:** ADR-156 filed — the reader's three questions come before the loop on every door's first screen
**Main:** red — CI/CD at `459aa84fc` (#4204's merge) was still in progress at the wrap; the previous completed run's red is the #4199×#4200 census/sweeper collisions fixed forward in the same PRs; the site-deploy runs for `a013d5e50`, `a19d91567` and the `d0d07296e` dispatch are red on the two gate defects fixed by #4203/#4204 (rollback declined each time; live content correct throughout)
**Incidents:** 2 rows added — the visual gate's check-side false red on #4200's deploy (rollback declined, #4202); the real `link-in-text-block` a11y red on #4199's deploy (fixed forward #4204)
**Stash/hooks:** clean
**Closures:** none — no issues closed this session · DoD: scanned=10 window=closed>=2026-09-26 hits=0 findings=0 dispositioned=0 mode=warn blocking=none
**Backlog:** Now live at 15 stories; no stale Later issues; hygiene 0 violations after the three epics' `## Stories` rows (#4183 → #3493; #4184 #4185 → #3495; #4190 #4191 → #4182); 12 filed tonight (#4182–#4191, #4202 auto), 0 closed; open count 36 → 48 via REST
**Alarms:** 3 red >72h, all cited — `qa-smoke-failures` → #4180 (PR #4194 open), `qa-smoke-warnings` → #4183 (re-cited tonight; the 09-21 citation had expired), `freshness-interior-gap` → the dated self-clearing citation (expires 09-29)
**CI warnings:** unverified — the newest main CI/CD run was in progress at the wrap (#4204's merge), so there was no green run to read annotations from
**Ledger:** Site vocabulary registry + static-reach ratchet row added
