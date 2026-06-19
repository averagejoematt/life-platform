# HANDOVER — 2026-06-19 (PM) · Inbox triage → noise reduction + podcast root cause

> Companion to `HANDOVER_2026-06-19_ReadinessDateIntegrity.md` (AM session, separate work).
> Goal: kill recurring day-to-day platform email noise; make it self-healing/background.

---

## Deploy state — what's LIVE
| Change | State | How |
|---|---|---|
| #1 ai-expert-analyzer timeout 120→600s | ✅ LIVE | `aws lambda update-function-configuration` (matches committed CDK #150 that was never deployed) |
| #1 DLQ purge (2 stale ai-expert msgs) | ✅ LIVE | drained `life-platform-ingestion-dlq` → depth 0 |
| #2 remove urgent `ingest-consecutive-failures-garmin` | ✅ LIVE | `cdk deploy LifePlatformMonitoring` (alarm deleted) |
| #3 `panelcast-no-episode-7d` URGENT→DIGEST | ✅ LIVE | same deploy |
| (bonus) `garmin-auth-unhealthy-24h` URGENT→DIGEST | ✅ LIVE | same deploy — #147 intent that was never deployed |
| (bonus) `ai-daily-spend-high` alarm created | ✅ LIVE | same deploy — #142 alarm that was never deployed |
| Budget gate: chronicle survives tier 1 (pause at ≥2) | ✅ LIVE | `deploy/deploy_lambda.sh wednesday-chronicle` (call-site `current_tier()>=2`) |
| #4 `deploy/check_lambda_config_drift.py` + wired into `post_cdk_reconcile_smoke.sh` | ✅ in repo | no deploy (CI/manual tool) |

**Uncommitted (this + AM session):** `lambdas/budget_guard.py`, `lambdas/emails/wednesday_chronicle_lambda.py`,
`cdk/stacks/monitoring_stack.py`, `deploy/check_lambda_config_drift.py`, `deploy/post_cdk_reconcile_smoke.sh`,
+ the AM readiness files. **Open a sync PR** when ready.

## The triage (what the inbox noise actually was)
1. **Daily "DLQ permanent failure" email (#1 — THE big one):** `ai-expert-analyzer` hit its 120s timeout on
   EVERY run (`Status: timeout`, 115/256MB — time-bound on Bedrock, not memory), exhausted retries → ingestion
   DLQ → one email/day. **The fix existed in CDK (`timeout_seconds=600`, #150) but `cdk deploy` was never run.**
   Bumped live to 600 + purged DLQ. Dead now.
2. **Garmin alarms (#2):** 3 alarms, one accepted-dead root cause (datacenter-IP 429, server-side refresh can't
   recover). 2 already digest-routed; the 3rd (`ingest-consecutive-failures-garmin`) paged URGENT and was a
   duplicate → removed from the urgent loop (garmin excluded; covered by digest-routed auth alarm).
3. **`panelcast-no-episode-7d` (#3):** correct that the show is silent (root cause below) → rerouted to digest
   (a deliberate HOLD trips it identically to a real outage, so it's never an actionable page).
4. **CI "Run failed" / budget-tier 0→3 emails:** already-resolved (black gate #146/#150; cost double-count fix).
   Today's CI is green; tier is a legit 1 (June spend ~$71/mo projected, reset-inflated).
5. **AWS Budgets/Free-Tier/CloudShell:** external housekeeping, not bugs.

## Podcast root cause (the headline find)
You expected a Friday episode; it's been silent. Chain, fully traced:
- The Friday **Panel podcast**'s ONLY input is the **Wednesday weekly chronicle** (`site/chronicle/posts.json`,
  `week>0`, dated ≥ genesis). Panel dry-run returned `"no current-cycle weekly chronicle yet"`.
- `posts.json` has **nothing post-genesis** (newest weekly = week 5, 2026-05-03, pre-reset).
- `wednesday-chronicle` 06-17 log: **"Budget tier active — Wednesday chronicle paused this week"**. It gated on
  `budget_guard.allow("chronicle")`, cutoff **1** → paused at the mildest budget state. At 15:00 on 06-17 the
  tier was still the **phantom tier-3** (the cost double-count fix landed 18:19 that evening). Chronicle only
  runs Wednesdays → no retry until 06-24 → Panel starved → alarm fires (correctly).
- **So the blocker was the budget gate, not thin data and not the chronicle dependency.** Decoupling the podcast
  wouldn't have helped: coach reads (its fallback material) are ALSO paused at tier 1.

**Fix (durable, "B"):** weekly flagship content (chronicle + podcast, ~$1/wk Bedrock) now survives tier 1 and
only pauses at tier ≥ 2, in lockstep with the Panel's own `SKIP_TIER=2`.
- `budget_guard.py`: `_FEATURE_CUTOFF["chronicle"]` 1→2 (registry intent; takes effect for `allow("chronicle")`
  on the next layer deploy — it's a shared-layer module).
- `wednesday_chronicle_lambda.py`: call site changed from `allow("chronicle")` to `current_tier() >= 2` so the
  fix shipped as a **one-function deploy with no layer rebuild** (and without dragging in the deliberately-
  deferred precompute sleep-30→25 change). `allow("chronicle")` is called ONLY here, so no other consumer is
  affected by the temporarily-stale v85 layer cutoff. Revert to `allow("chronicle")` at the next layer bump.

**Next natural episode:** chronicle Wed **2026-06-24** → Panel Fri **2026-06-26** (assuming tier < 2). No
manual revival was done (you chose B/durable over A/revive-today). To force one this weekend: reset tier→0,
invoke `wednesday-chronicle`, then `coach-panel-podcast` — but 5 days into a fresh cycle is editorially thin.

## #4 — the systemic gap (why this kept happening)
The #1 noise wasn't a bug — it was a **merged-but-undeployed CDK change that no automated path applies**, failing
silently and emailing daily. `post_cdk_reconcile_smoke.sh` checked *handler* drift but not timeout/memory. New
`deploy/check_lambda_config_drift.py` AST-parses `create_platform_lambda(...)` (timeout/memory, incl. the 120/256
defaults) and compares to live; exits non-zero on drift; wired into `post_cdk_reconcile_smoke.sh`. It already
caught a 2nd drift: **`email-subscriber` CDK 15s vs live 30s** (benign — live has more headroom; reconcile or
bump CDK to 30 at leisure). **Follow-up:** wire it into the nightly qa-smoke so drift is caught without a deploy.

## Garmin alarms DELETED (2026-06-19, user call) + Strava surfaced
User: "delete garmin alarms — known brittle, don't want to focus on it, hope to stabilize the API later."
- Removed `garmin-auth-unhealthy-24h` + `garmin-token-expiring-7d` from `monitoring_stack.py` → `cdk deploy
  LifePlatformMonitoring` (both DELETE_COMPLETE). `ingest-consecutive-failures-garmin` already gone (earlier).
- Excluded garmin from the fleet `UnhealthySourceCount` via `BEST_EFFORT_SOURCES = {"garmin"}` in
  `pipeline_health_check_lambda.py` (still evaluated + logged, just not counted/alerted) so it can't keep
  `ingest-liveness-unhealthy` red or mask a real death. Deployed `pipeline-health-check`.
- **Left intact:** `life-platform-garmin-data-ingestion-errors` (generic Lambda-error alarm — catches code/IAM
  bugs, not API brittleness; not firing). Delete later if you want it gone too.
- ⚠️ **Layer gotcha:** `pipeline-health-check` had **no shared layer attached** (latent — worked on warm
  containers; my deploy forced a cold start that exposed it: `ingest_health module unavailable`). Re-attached
  `life-platform-shared-utils:85` via `update-function-configuration`. Now healthy. (NOT a deploy_lambda.sh bug —
  wednesday-chronicle/mcp kept their layers; the layer was already missing on this one.)
- 🟠 **Strava surfaced (the de-noise immediately earned its keep):** with garmin excluded, the count went 2→1 —
  `strava: no ingestion attempt in 113h`. The Strava **Lambda runs fine** (last run today 16:30 UTC) but isn't
  writing the liveness *attempt* sentinel — almost certainly the known **402-paywall graceful-degrade path**
  (#124) returning early before `record_attempt`. So `ingest-liveness-unhealthy` is now red on **Strava alone**.
  NOT touched — it's a separate known-degraded source; decide: (a) add strava to BEST_EFFORT_SOURCES, or
  (b) fix the 402 path to still record the attempt. **Top follow-up.**

## Residual alarm state (all digest-routed or self-clearing)
- `ingest-liveness-unhealthy` — now red on **Strava only** (see above); digest-routed.
- `ingestion-error-ai-expert-analyzer` — leftover from the pre-fix 120s timeouts; clears after the next
  successful 600s run (14:00 UTC daily).
- `life-platform-dlq-depth-warning` + `-ingestion-dlq-messages` — DLQ purged to 0; clear on next metric eval.
- `panelcast-no-episode-7d` — digest-routed; clears when 06-26 episode publishes.
- Garmin alarms: **gone.**

**Verified:** 2026-06-19 PM. Drift check clean except benign email-subscriber; black clean; 21 budget/panel tests pass.
