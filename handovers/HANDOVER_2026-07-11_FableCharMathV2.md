# HANDOVER — First Fable session: character math v2 epic closed + 10-PR backlog paydown, all merged & deployed — 2026-07-11

> Instruction: "read the memory and handover and plan an efficient session to try and get
> as much of the open issues paid down" → mid-session: **"i also approve all merges and
> deploys this session"** (explicit in-session unblock).

## What ran

First Fable 5 session, launch eve T−1 (genesis 2026-07-12 tomorrow). Two tracks in
parallel: **Track A** — two waves of `worktree-implementer` fan-out over the
self-contained tier (6 agents wave 1, 2 agents wave 2 after main settled); **Track B** —
the driver (Fable, main tree) took the character-math epic #956 whole, since its 8
children interlock in three files and 4 of them were explicitly design calls. Everything
merged serially via the /reconcile-branch ritual and deployed the same session.

## What shipped (10 PRs #1049–#1059, ALL merged + deployed + verified)

**The flagship — epic #956 Character math v2, CLOSED (engine v1.6.0, config v1.5.0, ADR-134):**
- **PR #1055** (#958/#959/#960/#961/#962/#963/#964): XP zero-point moved to "a decent day"
  (decay 2→1; slow improver 0 XP/700 debt → 1027 XP/0 debt); XP gated on
  coverage_hold/not_instrumented (phantom relationships −100 dead); food-delivery modifier
  + challenge XP became engine inputs with provenance + debt-first paydown; confirmed dark
  stretches persist the down-streak AND bypass the XP buffer (30-day silent month: ~2
  headline levels → **12 levels**, 36→24, recovery ~28d, 3-level scar at day 420 — the
  cycle-4 failure mode is dead); xp_buffer capped at 40; headline weighted-mean
  renormalizes over instrumented pillars (**Elite reachable at day 362** of sustained ~90,
  was mathematically impossible at 93-cap); vice_streaks wired + Vice Shield data-driven;
  streak/weekend consistency inputs derived from stored history; buddy_engagement removed
  (B-3 precedent); #963 DECIDED: effects stay on EMA scores, narrative reworded.
- **PR #1056** (#965): source wiring — hevy→movement `strength_sessions` (.20 behavioral),
  reading→mind `reading_practice` (.10 behavioral, GSI2), todoist→consistency
  `task_follow_through` (.15 measured) — all day-count metrics, volume-gaming resistant.
- Validation: all five 420-day sim scenarios monotone-honest (`scripts/character_sim_year.py`
  is the regression harness); oscillator-beats-steady inversion gone (b L67 < a L76);
  28 new tests in `tests/test_character_math_v2.py`; 135 char tests green. ADR-134 +
  amendment in DECISIONS.md; audit-doc verdict table fully resolved; CHARACTER.md rewritten.

**Track A (8 agent PRs):**
- **#1051** (#1021, Now): /story/timeline/ launch-eve self-contradictions — pre-start
  anchor from true `EXPERIMENT_START`, quiet-stretch cut pre-genesis, + a bonus UTC-midnight
  Day-N bug (hero now uses `genesisCount()`); verified both sides of tomorrow's boundary.
- **#1050** (#967): presence block injected into daily_debrief/monday_compass/weekly/monthly
  digests (same daily_brief seam; debrief allow-list moves with the block); 26 tests.
- **#1052** (#966): grounded-generation gate on the daily brief's 4 legacy AI calls via a
  `_ground_legacy_output` reuse of the existing harness; **quality-gate HOLD is now terminal**
  (new `CoachHold` sentinel distinguishes deliberate holds from infra Nones — only errors
  fall back to legacy).
- **#1053** (#1018): panelcast 16.6MB WAV → **3.3MB MP3 live** (80kbps mono LAME via new
  `lambdas/audio_encode.py`, fail-open to WAV); lameenc layer built + attached (CDK email
  stack deployed); wk0 republished + CDN invalidated. Deviation: MP3 not AAC (no
  lambda-sized AAC encoder; 250KB lameenc vs ~40MB PyAV). **Spot-listen still owed by Matthew.**
- **#1054** (#1039): render-gate realistic-data pass (fixtures for vitals/labs/experiments)
  — proven to catch the #1008 overflow class the empty-mock pass is structurally blind to.
- **#1049** (#972): 8 done-once/decision-contradicting deploy scripts archived with
  tombstones; `v4_cutover.sh` correctly KEPT (live redirect tooling per SITE_AUTHORING §6).
- **#1057** (#973): docs-ci source-newer-than-verify gate (advisory; `--strict` ready) —
  **caught 4 real drifts day one** (COACH_STANCE ×3, HYPOTHESIS ×1, both verified 07-10 vs
  sources committed 07-11); + 2 new discovered literals (restart 40-URL surface, hypothesis
  cadence).
- **#1058** (#970): d2f ×29 / safe_float ×12 / query_range ×8 consolidated onto
  digest_utils (+264/−562); fixed hypothesis_engine's unpaginated query_range (silent 1MB
  truncation) and challenge_generator's missing phase filter (real behavior change, next
  weekly run).

**Driver-attended:** **#1059** (#1026): daily launchd backup — memory dir →
`claude-memory-backup/` + datadrops → **top-level `datadrops-archive/`** (NOT uploads/ —
its 30d lifecycle EXPIRATION would have deleted the archive); lifecycle + delete-protection
applied; agent loaded, memory leg green FROM launchd; restore drill 0-diff; initial 4.4GB
sync done (167/167 files).

## Verification

Serial reconcile-merge queue (doc-sync `--apply` per PR, truth gate green at every step,
`--check` PASSED on final main). **Two fleet deploys (95/95 each)**, config v1.4.0 then
v1.5.0 pushed to `config/matthew/character_sheet.json`, site-api deployed immediately
after #1051, site auto-deploys green through smoke+visual-AI QA (2 runs), CDK
LifePlatformEmail deployed (clean diff read first: 18 `[~]` function updates, no
destroys). Post-deploy: canary all_pass ×2, MCP 401-boot ×2, character-sheet healthcheck
200, wk0.mp3 live (200, audio/mpeg, 3465600 bytes). Epic #956 closed with DoD evidence;
all 12 story issues auto-closed. Session branches + 13 clean worktrees removed; the 3
stashes + dangling tip (#1025 territory) verified untouched.

## Gotchas / new reflexes

- **Fetch before every reconcile leg:** the #1057 reconcile ran against a stale local
  `origin/main` (fetched before #1059 merged) — harmless here because the branch didn't
  touch #1059's files, but the same slip on overlapping files would silently revert a
  merged PR via the squash diff. `git fetch` is part of the ritual, per leg.
- **`git add -A` on a conflicted tree bakes conflict markers into the commit** (add marks
  conflicts resolved) — and `sync_doc_metadata --apply` will happily rewrite literals
  INSIDE both conflict sides first, making them look identical. Resolve markers BEFORE
  the doc-sync apply/commit.
- **macOS TCC breaks launchd agents under ~/Documents** — exit 126, "Operation not
  permitted". The **existing `life-platform-ingest` watcher is silently failing the same
  way** (predates this session). Fix pattern: stage the script to `~/.local/bin`, keep
  data legs degrading gracefully; the real cure is Matthew granting `/bin/bash` Full Disk
  Access (fixes both agents).
- **uploads/ has a 30-day EXPIRATION lifecycle** — never archive anything durable there.
- Under the v2 XP economy the uncapped demotion buffer pinned at 100 and silently blocked
  ALL level-downs for ~40 days — first sim run after the decay retune caught it (drop
  went −12 → −1 before the buffer cap + dark bypass). The sim harness earns its keep.

## Next picks / residual

- **Matthew (Sunday, unchanged):** weigh-in → pipeline re-run →
  `fix_prologue_cycle_and_subscribe_ttl.py --apply` → `seed_genesis_preregistration.py
  --apply` + `publish_genesis_preregistration.py --apply`. **New:** panelcast wk0
  spot-listen (quality knob `PANELCAST_MP3_KBPS=96`); grant `/bin/bash` Full Disk Access
  (enables datadrops backup leg + un-breaks the ingest watcher); **locate the genome
  original** (datadrops/genome/ is empty and no genome object exists in the bucket — flagged
  on #1026); decisions #1023 (privacy-vs-gear affiliate copy) / #1029 / #1017.
- **Next session:** re-verify COACH_STANCE.md + HYPOTHESIS.md (the 4 #1057 advisory
  drifts), then flip `check_doc_index --strict` in docs-ci; #1025 orphan-commit rescue
  (attended); #936 DR swap-back drill (attended); #935 whoop script; #741 career artifact
  (outward-facing); #916 MCP authorize (wait for real refresh cadence); mobile Later
  epics #1000/#1001 + #748.
- Post-genesis watch: first real character-sheet run on v1.6.0 (17:35 UTC Sunday) — check
  `headline_excluded_pillars`, strength/reading/task components score, and that the Day-1
  record is clean-slate (no pilot chaining).

**Build beat:** char-math-v2 (see `site/story/build/beats.json`) — epic #956 merged + fleet-deployed + config live.

**Docs:** ADR-134 + amendment (DECISIONS.md, index regenerated), CHARACTER.md rewritten
(v1.6.0, pins re-verified), CHARACTER_MATH_AUDIT verdict table resolved, CONTINUITY.md §4
(launchd backup + TCC caveat), apply_s3_lifecycle.sh header (2 new prefixes) — all shipped
IN the work PRs; docs-ci gates green at every merge and at wrap.
