# HANDOVER — Presence / "the quiet stretch": give a human logging-gap a voice — 2026-07-01

> **When Matthew falls off routine (stops logging food/workouts/habits), the platform now NOTICES — the coaches raise it in their own voice, and the site says so honestly — instead of staying silent.**
> BUILT + tests green on branch `feat/presence-quiet-stretch` (PR opening). **NOT yet deployed — deploy is gated on Matthew.**

## ⚠️ STATE
- Branch **`feat/presence-quiet-stretch`** off `origin/main` (`ef53d47f`), 1 feature commit `f3f926c8`. PR to open.
- **Full suite 2480 passed**; black/ruff green. The **5 failures are pre-existing live-AWS** (`test_coaches_api` needs S3 config → `InvalidBucketName`; `test_i16` needs real DynamoDB) — **confirmed failing identically on clean origin/main via `git stash`**, not caused by this work.
- **Nothing deployed.** The first `engagement_state STATE#current` record doesn't exist until `adaptive_mode` runs post-deploy, so `/api/presence` returns the honest `present`/`available:false` default and every surface stays hidden until then (safe to ship dark).

## WHAT & WHY (owner's trigger)
Matthew went to a friend's 50th Friday, came back Saturday, and — "as always when routine gets disrupted" — stopped logging food, stopped working out, stopped syncing habits, started DoorDashing + eating badly. **With minimal inputs, nothing on the site or in the coaches noticed.** He wanted it to feel like a real experiment where AI coaches act like real coaches: notice the lack of signal, flag "it's day X with no feeds," raise concern about falling off — and when he starts logging again, observe what changed (probably weight regain). Explicitly **NOT a big red PAUSED sign**.

**The reframe (4 Explore agents):** the platform ALREADY detects the gap — `freshness_checker`, `source_state`, `/api/source_freshness` (`behavioral-stale`), `adaptive_mode` — but **deliberately stays silent**: `BEHAVIORAL_SOURCES` are excluded from paging, `adaptive_mode` returns a neutral 50 for missing data ("don't penalise for missing data"). So the gap isn't *detection*, it's *narrative*. This gives the gap a voice.

**The lever:** manual channels (food/workouts/habits/journal) STOP when Matthew disengages; wearables (whoop/apple_health/eightsleep) keep syncing **passively**. So a lull = manual quiet WHILE the wearables keep talking — which lets a coach name the silence + its *measurable* consequences (rough sleep, elevated RHR) and observe the return (weight up) **without fabricating the cause** (the reason is never in the payload).

**Owner decisions (AskUserQuestion):** coaches react **in-character/varied** (tough one pushes, compassionate checks in, analyst reads the wearable fallout); public visibility = **cockpit line + Story "quiet stretch" beat** (no banner); scope = **full 3-phase arc**.

## BUILT (1 commit, 3 phases)
- **P1 — the spine (`lambdas/engagement_core.py`, NEW, pure):** `compute_presence(today, channel_dates, …)` — days-since-last-log per MANUAL channel (macrofactor/hevy/habitify/notion; **food is the primary anchor**), **lag-adjusted** (logged today OR yesterday counts as present, respecting the 24h nutrition lag), presence class **`present → light → quiet → dark`**, **return detection** (a fresh food log directly after a ≥3-day lull → `returned`, `resumed_after_days`) + **weight-regain-over-gap** (latest weigh-in − the one nearest the lull start), **sick/travel planned-pause suppression** (a gap mostly covered by logged sick/travel days is a *planned break*, held ≤ light). No I/O, no clock — trivially testable. Written by **`adaptive_mode_lambda`** (a NEW helper `compute_and_store_engagement`, fail-soft so it never aborts the adaptive_mode run; **its own instrument — the neutral `engagement_score` is untouched**) into `engagement_state` (`DATE#{day}` + **`STATE#current`** convenience record, like `STANCE#latest`), floats→Decimal via `numeric.floats_to_decimal`, tagged via `compute_metadata.tag_record`. Classified **`EXPERIMENT_SCOPED`** in `phase_taxonomy` (mandatory — `classify()` raises on unknown + a coverage test enforces it).
- **P2 — coaches notice it (`coach_narrative_orchestrator` + `ai_calls.py`):** injected at the **SAME deterministic seam** as `current_stance`/`site_protocols`: `_gather_all_state` reads `STATE#current` → `_engagement_for_brief` trimmer (**omits when `present`**, drops the cause, keeps only presence/gap_days/channels_quiet/passive_still_flowing/planned_pause/return/weight-delta) → deterministic inject into `brief["generation_brief"]["engagement_signal"]` at the ~887 seam + surfaced in `_build_user_message` so the showrunner plans the beat. An **ENGAGEMENT/PRESENCE** clause in `ai_calls.py` tells each coach to acknowledge it **in their own voice/character**, ground the day-count in the real number, **NEVER invent the cause** (name the silence + what the wearables caught, then invite the story), and note the return **supportively, never punitively**. Reaches BOTH the site coaching surfaces AND the daily email (both render the orchestrator brief).
- **P3 — honest public surfaces:** **`/api/presence`** (`site_api_data.handle_presence`) — a **fail-closed** projection built field-by-field from an explicit allowlist (never spreads the stored record → no per-channel detail, no `passive_read` internals, no retention/mood leak; honest `present`/`available:false` before the first compute). A **self-hiding cockpit presence line** (`site/now/index.html` + `cockpit.js::renderPresence` + calm `.presence` CSS — "Off the grid since Friday — 4 days without a log; the wearables are still reporting"; **no red**). A **Story/timeline "quiet stretch" beat** (`dispatches.js` + `.tl-quiet` in `story.css`), fed by `/api/presence`, below the recap.

## ⚠️ GOTCHAS HIT
- **f-string NameError caught by ruff (F821):** a literal `{gap_days}` in the `ai_calls.py` system-prompt f-string would have raised `NameError` at runtime → reworded braceless ("it's been four days since you logged a meal"). Any new literal braces in that prompt block must be doubled or avoided.
- The `test_coaches_api`/`test_i16` failures look scary but are **environmental** (no valid S3 bucket / live DynamoDB in this sandbox) — proven pre-existing via stash. Don't chase them.

## VERIFICATION DONE
- 25 new tests: `test_engagement_core` (13 — classification incl. the exact trigger scenario, lag grace, return + weight regain, sick/travel suppression, passive-flowing, no-internal-key-leak), `test_engagement_coach` (8 — trimmer omits-when-present/drops-cause, handler inject/omit), `test_presence_endpoint` (4 — **fail-closed privacy**: asserts `channel_detail`/`passive_read`/raw values never reach the body). All green.
- `node --check` on cockpit.js + dispatches.js; a node simulation confirmed the generated copy reads well for trigger/dark/planned-pause/return/present.

## DEPLOY SURFACE (all gated on Matthew — "I run deploys"; `cdk diff` every CDK step first)
1. **Layer dance** (⚠️ `ai_calls.py` is a layer module): `bash deploy/build_layer.sh` → `cdk deploy LifePlatformCore` (publishes the layer) → bump `SHARED_LAYER_VERSION` in `cdk/stacks/constants.py` → **redeploy ALL consumer stacks** (Compute + Ingestion + Email + MCP + Operational) for **fleet uniformity** (the v89/v92 lesson — a mixed fleet trips the Plan gate). **⚠️ the bump MUST land on `main`** or a later main deploy reverts the fleet (reverse squash-drift).
2. **`cdk deploy LifePlatformCompute`** — `adaptive_mode` + `phase_taxonomy` + orchestrator (bundled assets; `cdk diff` first — expect benign asset re-hash, **verify no destroy / no unexpected IAM**; `adaptive_mode`'s role needs table-wide PutItem for the new partition — confirm).
3. **`bash deploy/deploy_site_api.sh`** — `/api/presence` (full `web/` package — **NOT** `cdk LifePlatformWeb`).
4. **`bash deploy/sync_site_to_s3.sh`** — cockpit + Story front-end (clobber guard; self-invalidates + rolls SW).
5. **Bootstrap:** invoke `adaptive-mode` once (real fn name) to write the first `engagement_state STATE#current`, then verify `/api/presence` + that a fresh coach narrative references the gap.

## OUTSTANDING / FUTURE
- After deploy: watch the coach narratives to confirm the in-character/varied reactions land (and that the Coherence Sentinel's semantic pass doesn't false-fire on the new claims — everything is grounded, but verify).
- Tunable thresholds live as named constants in `engagement_core.py` (`CHANNEL_STALE_DAYS`, `LULL_MIN_DAYS`, the `_classify` bands) — adjust after seeing real behavior.
- Pre-existing carry-overs (unchanged): reading **auto-recommender-reason path**, `/mind/` CloudFront 301, "Mood & journal" tile rename; audit **DEVOPS-02** (OIDC) + **doc-truth batch** (CQ-02/CQ-03/PRIV-03).

Plan file: `/Users/matthewwalker/.claude/plans/soft-baking-toast.md`. Prior handover archived at `handovers/HANDOVER_2026-07-01_ReadingConsolidation.md`.
