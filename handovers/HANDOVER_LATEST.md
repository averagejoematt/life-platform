# HANDOVER — Overnight full-platform sweep: 13-lens survey → 67/70 verified → 34 issues filed → 10-fix wave shipped live on launch eve — 2026-07-11

> Instruction: "plan our usual /uplevel and full sweep of the platform — bug bash, hackathon,
> missing features, code quality, doc drift, content/AI generation, the throughline, the purpose,
> the database. Also a deliberate session on the character gamification mathematics — every
> source's contribution, defensible growth AND retraction over a year+ across pillars. Also:
> how much does Claude fully understand the platform, and what SDLC/context/subagent changes
> would maximize efficacy. Full sweep → issues in the backlog, make no mistakes." Mid-session:
> "I approve all merges, edits, deploys this session — I'll be sleeping, wake me to it done."

## What ran (the machine)

Plan-mode recon (3 explorers) → 13-lens Workflow survey (~1.5M tokens, 70 raw findings, every
lens seeded with evidence rules + §13b + the open-issue list) → driver dedup (8 merge groups) →
12-batch finding-verifier pass (**67 CONFIRMED / 2 REFUTED / 1 PLAUSIBLE — vs the historical
~50% FP rate; the seeding is why**) → 34 issues filed per ADR-099 (#945–#978, labels+milestones+
score lines, char-math epic #956 with 9 linked stories) → 10 worktree-implementers in parallel →
serial reconcile-merge queue → fleet deploy 95/95 + site-api redeploy + 2 green site-deploys +
config sync/invalidations → live verification. The ritual is now reusable:
**`.claude/commands/platform-review.md`** (+ `.claude/agents/issue-filer.md`).

## What shipped (all merged + deployed + live-verified; main green 4607/0)

- **#944** un-red main: reset-aware proof-snapshot assertion (baseline was 1-red from the reset's honest refresh).
- **#945/PR983 privacy** — genome identifiers purged from repo test fixtures (synthetic sentinel), supplements registry (both mirrors + root S3 + CF invalidation + container recycle), build beats. Live-verified gene-free (the last "hit" was grep matching the empty `genome_snps` key itself).
- **#946/PR986 reset singletons** — `singleton_visible()` guard on every `get_item` reader (orchestrator, expert analyzer, character fallback, 4 site-api sites, chronicle/Elena); NARRATIVE#arc restarts `early_baseline` when `entered_date` < genesis (was: week 1 narrated under cycle-4 "setback" with no exit but "breakthrough"); Elena PERSONA + arc wipe coverage.
- **#947/PR980** — character `fetch_date`/`load_previous_state` phase-filtered; pilot records can't chain xp_debt/streaks/mood into Day-1 compute.
- **#948/PR988 pre-start contracts** — observatory_week (inverted-window fabrication), future `as_of` stamps, journey ghost weight, cycles degenerate copy, waveform day clamp, weekly_priority, forecast flag; all #939-pattern, self-disarming post-genesis. Playwright 12/12.
- **#949/PR989 countdown content** — coaching door cycle-4 board read, podcast bet ledger, home-hero 315-lbs hardcode (now live-bound), discovery ticker, story deks (+ render-parity twin in the Wednesday publisher), public_stats pre-start contract in site_writer, subscribe CTA + protocols banner riders. Mechanism-level (re-arms every reset). Render-QA 142 checks/0 fail.
- **#950/PR979** — habitify notes 412-since-ship fixed (from/to range params) — the #898 "why missed" channel actually ingests for cycle 5.
- **#951/PR987 (also closed #930)** — phase taxonomy made TOTAL (all 83 live pk families classify; protects Sunday's pipeline re-run from KeyError), SSM cycle-bump ordering, subscribe rate-limit TTL attr, prologue cycle re-stamp at resurrect.
- **#952/PR985 AI trio** — few-shot examples stripped from the ADR-104 fabrication allow-list; `[AI_UNAVAILABLE]` sentinel held (never gate-passed/cached/rendered); BoD intro derives identity/phase from the profile (dropped the stale age token + frozen Phase-1 targets).
- **#953/PR981** — repo-walk isolation test skips `.claude`/`cdk.out` (audited all 15 walkers); `scripts/validate_beats.py` wired into /wrap.
- **#954/PR984 character gates** — up-gate vs UNboosted EMA target (cross-pillar bonuses froze boosted pillars at L1 forever); XP demotion buffer monotone (was `%100`, wrapped upward on decline). ENGINE_VERSION 1.3.1. Re-sim: steady-good now L71 with metabolic climbing (was L49/frozen); the "oscillator out-levels steady" inversion is gone.
- **PR982 docs** — `docs/engines/CHARACTER_MATH_AUDIT_2026-07.md` (verdict table + 420-day sim `scripts/character_sim_year.py`), `docs/reviews/CLAUDE_PLATFORM_UNDERSTANDING_2026-07.md` (the self-assessment Matthew asked for), `/platform-review` skill, `issue-filer` agent, CLAUDE.md drift fixes, R22 charter EXECUTED stamp.
- **PR990** — #946×#951 PERSONA#elena semantic collision (elena = experiment_scoped per the verified bug; margaret stays cross_phase) + order-proofed the observatory test (dual module identity `web.site_api_common` vs `site_api_common`).
- **PR991** — §13b resolved rows + `docs/reviews/SWEEP_MANIFEST_2026-07-11.json` (anti-re-flag).

## The backlog Matthew wakes up to (24 open, all scored/labeled/milestoned)

**Now:** #955 (presence-across-genesis DECISION — the ack-gate will force the pre-genesis ~17-day
gap into week-1 narratives unless clamped or embraced; bites Monday), #957 (climb-during-darkness
CRITICAL — blend floor 15.6 re-opens the up-gate after ~15 dark days; a never-logging fresh
character reaches L16 in 60 days while mood=dormant; needs a model decision), #976 (cycle-5
pre-registration moment — decays fast after Day 1), #741, #942.
**Next:** char-math epic #956 stories (#958 XP zero-point at raw 80 / #959 30-day dark ≈ 2 levels /
#960 Elite unreachable / #961 post-engine bypasses / #962 dead inputs / #964 phantom debt /
#965 hevy-reading-todoist wiring — movement is blind to lifting), AI gates (#966 daily-brief
ADR-104 hole, #967 presence-block gaps, #968 quality-gate coverage), #969–#970 cleanups,
#973 doc-drift gate-gap class, #974–#975 cockpit levers + manual-input instrumentation,
#977 permissions kernel, #978 protocols tense. **Later:** #963, #971, #972, #748.

## Verified

Full suite green on main post-everything: **4607 passed, 74 skipped, 10 xfailed, 0 failed**
(creds-blanked). CI on main: green (deploy skipped where nothing to deploy). Fleet deploy
95 updated/0 skipped/0 failed @ 5f434c6d; site-api redeployed (handler-import verified);
site-deploy workflow green TWICE (privacy purge, countdown sweep) — smoke + visual-AI QA
passed, zero rollbacks. Live checks: /api/supplements + /config registry + beats.json
gene-free; /api/weekly_priority null+pre_start; /api/observatory_week honest null (no
inverted window); /api/journey current_weight null, pre_start true, days_until_start 1;
/api/character as_of clamped to today; home hero 315-free; version.json == HEAD-era build.

## Gotchas (durable ones also in memory)

- **Chaining `git rebase` in one command block** — a conflict mid-chain let `sync_doc_metadata
  --apply` + commit + push run against a half-rebased tree TWICE (#986, #988). Rebase must be
  its own command; resolve; only then continue.
- **`gh pr merge --delete-branch` from an agent worktree** tangled the PRIMARY checkout
  (HEAD file on the branch while worktree bookkeeping said main) → fixed with
  `git symbolic-ref HEAD refs/heads/main` + `update-ref`. Merge without `--delete-branch`
  from worktrees; prune branches separately.
- **Concurrent-PR semantic collisions are real** even with file boundaries: #946 (elena
  experiment_scoped) vs #951 (generic PERSONA# cross_phase + a test asserting it for elena);
  and the doc-sync literal needs re-`--apply` per merge, serially.
- **Green-solo/red-in-suite**: the observatory test failed only after tests a–g — dual module
  identity means patching a module global can miss the object the handler reads; patch the
  called symbol. (The wall-clock pre-start state was masking it — a time bomb defused.)
- **Warm-container config caches have no TTL** (`_supp_metadata_cache`) — an S3 config fix
  isn't live until containers recycle (deploy_site_api.sh) AND CF invalidates (+ note CF's
  cache key ignores query strings on /api/*, so cache-busting curls lie).
- **grep-based privacy scans false-positive on JSON key names** (`genome_snps` ≠ a leak);
  verify with exact term counts before alarming.
- Workflow tool: `args` must be real JSON (a placeholder string silently no-ops the fan-out —
  caught because the run finished in 30ms with 0 agents).

## Matthew's queue (numbered, everything blocked-on-you)

1. **Sunday morning (unchanged):** weigh in fasted → `python3 deploy/restart_pipeline.py
   --genesis 2026-07-12 --apply`. It now also: wipes the 23 pre-genesis singleton/derived
   rows (improved date-fallbacks), re-stamps prologue cycle stamps, republishes lead-in deks.
2. **One-liner after the pipeline:** `python3 deploy/fix_prologue_cycle_and_subscribe_ttl.py --apply`
   (553 stranded SUBSCRIBE#rate_limit rows get TTL; dry-run verified). The classifier blocked
   me from DDB mass-mutations — deliberate.
3. **Still yours from before:** eightsleep 3-row dupe delete; PRE-13; HN #741; /verify/ URLs.
4. **Decisions to make (filed):** #955 presence-across-genesis posture (before Monday's
   narratives if possible); #957 climb-during-darkness model fix (critical, fable-class);
   #976 pre-registration moment (value decays after Day 1); #977 permissions kernel.

## Watch items

First post-genesis crons Mon ~16:30/17:00 UTC (character compute now phase-filtered + gate-fixed;
brief's public_stats now pre-start-aware — today's 17:00 UTC run regenerates it honestly).
Coherence sentinel pre-start ALARM stays expected through Saturday (#942). EP0 podcast = week 1.

**Build beat:** 2026-07-11-launch-eve-sweep
**Docs:** CHARACTER_MATH_AUDIT_2026-07 + CLAUDE_PLATFORM_UNDERSTANDING_2026-07 (new), CLAUDE.md (cadence/verify-count), REVIEW_PROMPT_R22 (EXECUTED stamp), §13b + SWEEP_MANIFEST_2026-07-11.json, engines/CHARACTER.md verified-date + gate deltas, SCHEMA/PHASE_TAXONOMY (via #951), platform-review skill + issue-filer agent
