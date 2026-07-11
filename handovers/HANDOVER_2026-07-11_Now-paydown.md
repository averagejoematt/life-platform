# HANDOVER — Now-milestone paydown: 4 of 5 open Now issues shipped live on T−1 (sentinel grace, presence clamp, dark-day up-gate, cycle-5 pre-registration) — 2026-07-11

> Instruction: "read the handover and memory etc. and let's plan to pay down as many of the
> now issues that are open as possible efficiently in this session, I approve all merges and
> deploys and edits."

## What ran

Three worktree-implementers in parallel (#942, #955, #957) + one Explore scout (#976
machinery map) → serial merge queue with `sync_doc_metadata --apply` per merge → fleet
deploy 95/95 → a fourth implementer for #976 → merge → **quality hold on the seeder's
first output** (see gotchas) → inline seeder hardening → seed + publish `--apply` → live
verification of all four surfaces. Today was Saturday T−1; genesis is Sunday 2026-07-12.

## What shipped (all merged + deployed + live-verified)

- **#942 / PR #993** — `check_experiment_continuity` gains `pre_start` status (rank-0,
  OK-with-note) when genesis is 1–7 days ahead; >7 days stays ALARM; invariant test pins
  both sides of the boundary. `PRE_START_GRACE_DAYS = 7` is the single knob. Live sentinel
  invoke now reads `pre_start: genesis 2026-07-12 is 1 day(s) ahead — sanctioned countdown
  window (#931)`. Remediation agent only surfaces warn/alarm, so pre_start is invisible to it.
- **#955 / PR #994** — **decision made and documented: option (a), clamp presence at
  genesis** (the #943 presentation rule already decided the fork). `compute_presence()`
  filters pre-genesis manual logs; a channel silent since before genesis gets its gap
  anchored AT genesis; `_detect_return` cannot fire across the boundary (no "JUST RETURNED
  after ~17 days" beat on Day 1); wearables/weight/travel deliberately stay cross-cycle;
  new `experiment_window_start` field on STATE#current; cockpit.js `renderPresence(pre)`
  gets the story.js-style pre-start guard. Live: `/api/presence` = present/gap 0/severity
  none — the ack-gate can no longer force the cycle-4 stall into week-1 narratives.
- **#957 / PR #995 (CRITICAL)** — the character up-gate now judges the **unblended** raw
  (`weighted_sum/total_weight`, exactly 0 in silence) instead of the 50-blend, so the
  confidence-blend floor (~15.6 movement) can never re-open the up-gate during darkness at
  ANY horizon. ENGINE_VERSION 1.3.1 → **1.4.0**. Sim: fresh character in 90-day total
  silence was L7 + 32 level_up celebrations → now **0 climbs, stays L1**; scenarios a–e
  byte-identical (steady-good L71@420d, oscillator L62 < 71 — #954 unregressed).
  `tests/test_character_neglect.py` extended to 60/75-day dark horizons. Also fixed:
  `scripts/character_sim_year.py` hardcoded the main-checkout path (a worktree run was
  silently simulating main's engine) — now repo-relative.
- **#976 / PR #996 + two --apply runs** — the cycle-5 pre-registration moment, shipped
  T−1 as required. (1) `deploy/seed_genesis_preregistration.py`: Bedrock generation
  (narrative-tier Sonnet) grounded ONLY in `config/user_goals.json`, deterministic
  validation + presentation-rule token ban + cross-coach Jaccard dedup + #813 liveness
  gate (allowlist was 0 → all claims honestly qualitative); freeze-file receipt at
  `deploy/generated/genesis_preregistration.json` (committed) so every re-run re-lands the
  IDENTICAL claims; wrote 15 PREDICTION# records across all 8 coaches + 2 HYPOTHESIS#
  pre-registered hypotheses via `store_hypothesis`. (2)
  `deploy/publish_genesis_preregistration.py`: "Prologue · Part IV: The Plan, On the
  Record" (Elena's voice, 1401 words) — one chronicle DDB record then
  `restart_leadin_pages.run()` rebuilds pages + posts.json + CF invalidation. Live:
  `/api/predictions` overall 15 pending, all 8 coaches on the record; week-04 page renders;
  0 banned-language hits.

## Verified

Full suite on final main: **4643 passed, 56 skipped, 10 xfailed, 0 failed**. Fleet deploy
95 updated/0 failed (shared modules coherence_invariants/engagement_core/character_engine).
site-deploy workflow green on the cockpit.js merge (smoke + visual-AI QA, no rollback).
Doc-sync re-applied serially after every merge. Live checks: sentinel invoke → pre_start;
/api/presence → present/gap 0; /api/predictions → 15 pending/8 coaches; /journal/posts.json
lists Part IV first; week-04 page live and clean.

## Gotchas

- **First-pass Haiku pre-registration output failed the rigor bar** — 6 of 8 coaches
  produced a near-identical off-domain RHR claim, several were incoherent ("RHR will
  decrease from the baseline 300.8 lbs starting point"), and one FABRICATED a number
  ("~70 bpm, typical for a 300.8 lb individual" — ADR-104/105 violation). Dry-run review
  before `--apply` is what caught it. Fixes that made it publishable: narrative-tier model
  (AI_MODEL/Sonnet, not AI_MODEL_HAIKU) for permanent public artifacts, per-coach domain
  enforcement in prompt + per-call reinforcement, "no numbers absent from the grounding
  facts / never estimate a typical baseline" rule, deterministic cross-coach token-Jaccard
  dedup (threshold 0.55). Lesson: **always dry-run-review a generation before freezing it
  as a pre-registration** — the freeze rule makes the first output permanent.
- The seeder froze its output even on dry-run — reviewing meant `rm` the frozen JSON and
  regenerate. By design (freeze-first), but surprising.
- `deploy/` is excluded from repo flake8 — passing a deploy/ path explicitly flags E203
  (black's slice style); not CI-gated, don't chase it.

## Residual / next picks

- **Now milestone is down to ONE open issue: #741** (publish the career artifact) —
  explicitly gated on Matthew choosing a venue; mechanics (traffic digest referrers,
  /method/build/ cross-link) can be prepped once he picks.
- **Matthew's Sunday queue grew one step**: after `restart_pipeline.py --apply`, the wipe
  takes PREDICTION#/HYPOTHESIS#/chronicle records with it — re-run
  `python3 deploy/seed_genesis_preregistration.py --apply` then
  `python3 deploy/publish_genesis_preregistration.py --apply` (claims frozen, re-lands
  verbatim). This is IN ADDITION to `fix_prologue_cycle_and_subscribe_ttl.py --apply`.
  Part IV is deliberately NOT in PRELAUNCH_CALENDAR (genesis-specific), hence manual.
- Next milestone (from the sweep backlog): char-math epic #956 stories (#958–#965), AI
  gates #966–#968, #969–#970 cleanups, #973–#975, #977 permissions kernel, #978.
- Watch: first post-genesis crons Mon ~16:30/17:00 UTC — character compute now gate-fixed
  AND phase-filtered; presence now genesis-clamped; prediction grading windows open from
  Day 7. Coherence sentinel pre-start note self-disarms at genesis.

**Build beat:** 2026-07-11-board-on-the-record
**Docs:** docs/engines/CHARACTER.md (up-gate → unblended raw, ENGINE_VERSION 1.4.0), docs/restart/RESET_PLAN_2026-07-12.md (Sunday re-seed step), docs/SCHEMA.md `experiment_window_start` via sync; none else needed — new scripts are deploy/ helpers documented in their own docstrings + this handover
