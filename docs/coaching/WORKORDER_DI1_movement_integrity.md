# WORKORDER: DI-1 — Movement Data Integrity & Coach Honesty Guard

> **Status:** OPEN — DI-1.1 diagnosed (read-only) 2026-06-19; **DI-1.2 + DI-1.3 + DI-1.1 source-state + DI-1.4 built + tested (not deployed) 2026-06-19**; DI-1.5 (governance) + DI-1.6 (HAE failsafe — needs Matthew's Garmin→Apple/HAE config check) pending. (DI-1.1's remaining step is the Strava re-enable CDK deploy — Matthew.) **DI-1.1 Strava decision RESOLVED 2026-06-19: Matthew subscribed to Strava → re-enable ingestion (see DI-1.1).** **DI-1.6 (Apple HAE failsafe) added.** GARM-1 (official Garmin API) deferred — see Deferred decisions.
> **Author:** coaching session 2026-06-19. **Revised same day** to fold in Claude Code's confirmed
> DI-1.1 root cause, which **overturned** the original "OAuth refresh-token" hypothesis (see DI-1.1).
> **Pairs with:** `TRAINING_CALIBRATION.md` §4a (the data-pull mandate this enforces in code), `TRAINING_PROGRAM.md`.
> **Boards consulted:** Technical (Omar/Priya/Henning/Viktor/Dana). Personal (Maya/Henning) on the coach-honesty framing.
> **Privacy tier:** PRIVATE. Nothing in DI-1 may surface to Elena Voss or any public surface.
> **ID note:** renumber into ER-/DI- to fit the tracker as you like — kept standalone here.

---

## The bug, in one line

The platform stamps Matthew's hardest training days as **sedentary / under-training**, because the
movement/sedentary computation **does not join Hevy** and derives its only training signal from
**Strava — which is deliberately paused** (402 paywall) — so with Strava off and Garmin rate-limited,
daily-metrics has *no* training signal and collapses every day to movement-empty. The training coach
(Dr. Chen) has written six consecutive days of "you're under-training" off this, and the thread's
continuity loop keeps re-confirming it.

**Observed evidence (2026-06-19, use as fixtures — do not re-derive):**
- Freshness: `strava` last 2026-06-14, `garmin` last 2026-06-15; `whoop` + `apple_health` fresh.
- Hevy (real training): **Push 6/16 (27 sets, 104m), Pull 6/17 (22 sets, 106m), Legs 6/18 (17 sets, 108m), Engine 6/19 (30 sets, 151m)** — four straight 100–150m sessions, fresh through today.
- `get_daily_metrics(view="movement")`: `has_workout=false` on 6/16–6/19; **6/17 + 6/18 flagged `sedentary`**. Rule: `<5000 steps + no workout + <200 active cal`.
- Apple steps last 6 days: `402 / 5267 / 1538 / 444 / 5712`; only **6 of the last 15 days** have any step data (6/5–6/13 blank). Coach thread cites a **298** avg that reconciles with nothing (~3,415 actual).
- ACWR 1.02 safe/rising; HRV flat at baseline — systemic picture is fine; "sedentary" is purely a data-join + dead-source artifact.

---

## How Claude Code works this

Read first, in order: this file; `TRAINING_CALIBRATION.md` §4a; `lambdas/compute/daily_metrics_compute_lambda.py` (the join bug lives at the source list + TSB calc — anchors in DI-1.2); `mcp/tools_health.py` `tool_get_readiness_score` lines ~490–530 (**copy the `is_forward_dated` + `staleness_warning` block verbatim** — DI-1.3 reuses it); and the training-coach thread generator (grep for where `position_summary` / the `COACH#` partition is written nightly — confirm by reading).

Build DI-1.2 → DI-1.6 **in order**, committing each independently. DI-1.1's Strava decision is now RESOLVED (Matthew subscribed 2026-06-19 → re-enable); DI-1.6 adds the Apple HAE failsafe. Do **not** register any MCP tool whose implementing function isn't in the same commit; run `pytest tests/test_mcp_registry.py` before any MCP change is done. Tool functions go **before** `TOOLS = {}`. **Do not deploy** — write code + tests, show diffs; Matthew runs all deploys.

**Hard scope guardrails (acceptance criteria, not suggestions):**
- **Hevy is the primary "did he train" signal, everywhere.** Any code answering "did he work out / is this sedentary / what was the training stimulus" reads the normalized workout source (Hevy first, then MacroFactor) **before** steps/Strava/active-cal. A step count must never, alone, produce a sedentary or training-stimulus conclusion. Critically: the **training-stress signal (TSB) must be Hevy-aware**, not Strava-only — with Strava off it must fall back to Hevy-derived load, not emit zero.
- **Honesty over assertion (Henning standard).** When a source is stale, paused, or rate-limited, the output is "not assessable + which source + why," **not** a confident "sedentary / under-training." Mirror the readiness future-stamp guard.
- **`paused` ≠ `stale` ≠ `broken`.** A deliberately-off source must be legible as off-by-design, so guards and alarms don't false-fire on it (see DI-1.1).
- **No new activity/effort scoring model.** Plumbing + a join fix + a staleness guard. Correlational only; no causal language in output strings.

---

## DI-1.1 — Strava + Garmin: confirmed root cause (diagnosis-done; the OAuth hypothesis was WRONG)

**Diagnosed read-only by Claude Code 2026-06-19. Re-auth fixes nothing — do not pursue it.**

**Strava — deliberately paused, not broken.**
- `cdk/stacks/ingestion_stack.py:182` → `schedule=None  # PAUSED`. The `strava-daily-ingestion` EventBridge rule no longer exists (ResourceNotFound); only a stale Lambda resource-policy permission remains.
- Pause cause: 6/14 logs show `HTTP 402 Payment Required` on both the activities fetch and the zones call — Strava's app-tier API gate (post-2024 terms), not per-user auth. 6/14 was the last run before the pause deployed.
- The ~2ms 4-hourly invokes since 6/15 are a **liveness pinger** hitting the `event.get("healthcheck")` fast-path — no business logs, never calls Strava. **This masks the missing cron** (`run_ingestion` would log "Ingestion starting"; absent on every post-6/14 invoke).
- **RESOLVED 2026-06-19 — Matthew subscribed to Strava (clears the 402).** The fix is to **re-enable ingestion**, not re-architect. Verify the subscription is on the same Strava account that owns the API app (Client ID 204637, Standard Tier, 1 athlete — token auth was already healthy/refreshing). Then: restore the cron at `ingestion_stack.py:182` (un-pause `schedule=`), CDK deploy to **recreate the `strava-daily-ingestion` EventBridge rule** (it was deleted) and reconcile the stale Lambda permission. First run backfills 6/15→present (Strava API fetches historical activities). Confirm the 402 is gone in logs.

**Garmin — 429 refresh-ratelimit.** Still scheduled (cron 0,6,14,22) but a `REFRESH_RATELIMIT` marker sits in its partition — the known Garmin 429 OAuth-refresh block (datacenter-IP crackdown, documented in `CLAUDE.md`). Not durably re-auth-fixable here; full mitigation (residential/proxy egress, backoff) is a separate item.

**Hevy — fresh through today.** Even with Strava re-enabled, **Hevy stays the primary "did he train" signal** (DI-1.2/1.3) — Strava is the aerobic/NEAT layer, not the training-stimulus source. The whole point of this work order is that no single movement source going dark can blind the platform again; re-enabling Strava is necessary but not sufficient, which is why the Hevy join, the honesty guard, and the HAE failsafe (DI-1.6) all ship.

**What DI-1.1 requires (revised — Strava decision resolved):**
1. **Re-enable Strava** per the steps above (un-pause cron, recreate rule, backfill, verify 402 cleared). Matthew runs the CDK deploy.
2. **Make source-state legible.** Give every ingest source an explicit state — `live` / `paused` / `rate_limited` / `stale` — that `get_freshness_status` and the coach guard read, so an intentional pause (Strava, historically) or a 429 (Garmin) is never mistaken for silent breakage. **Kill the liveness-pinger masking:** a paused source must not emit healthcheck invokes that hide a missing cron. This is the durable anti-recurrence fix and stays even though Strava is back on.
3. **Garmin biometrics stay degraded for now** (429 `rate_limited`) — out of scope to fix here; the honesty guard (DI-1.3) covers it, and activity/walking data now comes via Strava with the HAE failsafe behind it (DI-1.6).

**Acceptance:** Strava re-ingests 6/15→present; freshness/coach output distinguishes `live`/`paused`/`rate_limited`/`stale`; no healthcheck-pinger masks a dead cron. Tests: `test_freshness_distinguishes_paused_from_stale`, `test_source_state_live_after_strava_reenable`.

---

## DI-1.2 — `daily-metrics` must join Hevy (boolean AND training signal)

**Anchors:** `lambdas/compute/daily_metrics_compute_lambda.py:688` — `sources = ["whoop","apple_health","macrofactor","strava","habitify","withings"]` omits Hevy. `:752` — TSB / training signal computed **purely from Strava**. So even after a boolean fix, the training-stress number zeroes out with Strava off.

- Add Hevy to the source join. `has_workout` for a day = **true if a normalized workout exists from any source that day, Hevy first** (reuse the `get_workouts` / workout-partition join — do not re-query Strava-only).
- `sedentary_flag` requires **no workout from any source incl. Hevy**. A Hevy day is never sedentary regardless of steps.
- **TSB / training-stress must be Hevy-aware:** when Strava is unavailable, derive load from Hevy (sets × duration, or session load) instead of emitting 0. Correlational; carry a `confidence` field.
- Recompute 6/15→present after the fix.

**Acceptance:** `test_has_workout_true_with_hevy_low_steps`; `test_no_sedentary_on_hevy_days_jun16_19` (re-running movement over 6/16–6/19 → 0 sedentary days); `test_tsb_nonzero_from_hevy_when_strava_off`.

---

## DI-1.3 — Coach generator: Hevy-first pull + staleness/paused honesty guard

**Anchor to mirror:** `mcp/tools_health.py:490–530` (`is_forward_dated` + `staleness_warning`).

1. **Pull order (enforce §4a):** Hevy `get_workouts` + `get_workout_detail` **first** as primary training-stimulus signal → Strava for aerobic/NEAT (when live) → steps tertiary. The "how much did he train" reasoning is built off Hevy, never steps.
2. **Honesty guard:** before emitting any "under-training / sedentary / low-stimulus" language, check movement-source state. If Strava/Garmin are stale **or paused/rate-limited** or the step field is missing, state e.g. **"movement sources unavailable (strava: paused; garmin: rate-limited); NEAT/aerobic volume not assessable"** and withhold the verdict — but still report the Hevy training that *did* happen.

**Acceptance:** `test_coach_guard_withholds_undertraining_when_strava_paused` — feed a day with a Hevy session + paused Strava; assert the generated `position_summary` contains no "under-training"/"sedentary," names the unavailable source + reason, and reflects the Hevy session. This is the regression test that keeps Dr. Chen from relapsing.

---

## DI-1.4 — Apple Health step gap + phantom 298

- **Field-level gap behind a "fresh" envelope:** `apple_health` reports `fresh` while the **step field is blank for 6/5–6/13** — false-clean like food_delivery. Freshness should check the **step field's** recency, not just the source envelope.
- **Phantom 298:** trace which field/window produced it (reconciles with neither the per-day values nor the ~3,415 avg) — likely a wrong-window average or a dedup/field-mapping bug keeping phone steps and dropping the watch contribution.
- **Fix:** explicit step precedence (watch/Garmin/Strava distance primary; Apple steps fallback only); a step-field completeness flag; ensure a low/blank Apple step day cannot drive a sedentary/under-training verdict (verify DI-1.2's join already closes this).

> **Note:** DI-1.4 is a **prerequisite for the DI-1.6 HAE failsafe** — HAE can't be a trustworthy backstop while its own feed has silent field-level gaps. Fix the completeness/precedence here first.

**Acceptance:** `test_step_completeness_flag_surfaces_jun5_13_gap`; resolved step source-of-truth documented in `DATA_DICTIONARY`.

---

## DI-1.5 — Thread correction, tests, governance

- **Thread correction (out-of-band):** the corrective stance for Dr. Chen's thread is written from the coaching session via the insight/decision log — Claude Code does **not** seed it. Content: *prior under-training reads were an artifact of a Hevy-blind sedentary join + a Strava-only training signal with Strava paused; corrected against four verified 100–150m Hevy sessions 6/16–6/19; walking-base vs proven floor is **unmeasurable** until Strava re-ingests (DI-1.1, now in progress) and the HAE failsafe (DI-1.6) is behind it.*
- **Tests:** all named above, green. Registry test green if any MCP tool is touched.
- **Doc update matrix (house trigger rules):**
  - `CHANGELOG` + `PROJECT_PLAN` — always.
  - `RUNBOOK` — Strava `paused` state + 402 context; Garmin 429; the `paused≠stale` semantics.
  - `ARCHITECTURE` + `DECISIONS` — the Hevy-aware TSB + source-state model (design change).
  - `DATA_DICTIONARY` — step source-of-truth + precedence; the new source-state field.
  - `MCP_TOOL_CATALOG` / `USER_GUIDE` / `FEATURES` — only if a tool signature/output changes.
  - **ADR recommended** — promote the staleness/paused honesty-guard to a cross-coach standard (same pattern as the readiness guard; will want to apply to every coach).
  - Run `python3 deploy/sync_doc_metadata.py --apply` if any count changes.

---

## DI-1.6 — Apple Health (HAE) activity failsafe + source precedence

**Goal (Matthew, 2026-06-19):** a secondary movement/activity source so a Strava stall can never again blind the platform. HAE is the **failsafe only** — Strava stays primary; HAE is a dormant backstop, explicitly accepted as brittle-but-acceptable for that role (it carries an iOS-app dependency — fine for a backstop, not for the primary path).

**Chain:** Garmin watch → Garmin Connect → Apple Health (workout sync) → Health Auto Export → platform ingestion. Verify two config preconditions before coding: (a) Garmin Connect → Apple Health **workout** sync is on (not just steps); (b) HAE is set to export **workouts/activities** (distance, duration, HR), not only the gapped step field (DI-1.4).

**Build:**
- Ingest HAE **activity/workout** records (distance, duration, HR, type), not just daily steps. Store alongside the other activity sources.
- **Source precedence for activities:** Strava primary → HAE fallback for any day Strava is missing/stale/paused. Dedupe so a single walk present in both counts once (match on date + approximate distance/duration; prefer Strava's copy). HAE-sourced days carry `source: "hae"` + `confidence` per the Henning standard.
- The failsafe is **passive**: inert while Strava is live, silently catching the gap when Strava isn't — gated by the same source-state field from DI-1.1.

**Depends on:** DI-1.4 (HAE feed must be gap-free + precedence-defined first).

**Acceptance:** `test_hae_activity_fallback_when_strava_missing` (Strava empty + HAE walk → walk counted, tagged `hae`); `test_strava_hae_dedupe_single_walk` (same walk in both → counted once, Strava preferred); HAE path stays inert when Strava is live.

---

## Deploy sequence (Matthew runs — reminders, do not execute)

1. Deploy `daily-metrics-compute` with the Hevy join + Hevy-aware TSB (DI-1.2); manually invoke to recompute 6/15→present.
2. Deploy the coach-generator change (DI-1.3); regenerate today's training thread so the corrected logic writes a clean entry.
3. Deploy the source-state / freshness changes (DI-1.1.2 + DI-1.4 step-field flag).
4. MCP package deploy **only if** a tool was touched (full `mcp/` dir; `deploy_lambda.sh` rejects `life-platform-mcp` — follow its printed build sequence). New script needs `chmod +x` or `bash deploy/<script>.sh`.
5. `pytest tests/test_mcp_registry.py` green before any MCP deploy.
6. Smoke-test: `get_daily_metrics(view="movement")` over 6/16–6/19 → 0 sedentary days, TSB nonzero from Hevy; `get_freshness_status` shows Strava `paused` (not `stale`); regenerated training thread names no "under-training" with Hevy present.
7. **Re-enable Strava (DI-1.1):** verify the new subscription is on the API-app account, un-pause the cron at `ingestion_stack.py:182`, CDK deploy to recreate the `strava-daily-ingestion` rule, then invoke once to backfill 6/15→present and confirm the 402 is gone.
8. **HAE failsafe (DI-1.6):** verify Garmin→Apple Health workout sync + HAE workout-export config, deploy the HAE activity ingestion + precedence, then confirm it stays inert while Strava is live.

---

## Deferred decisions (recorded 2026-06-19 — not building now)

- **GARM-1 — official Garmin Connect Activity API (push/webhook).** The robust long-term direct-Garmin spine (push-based, no polling, no rate-limit, no Strava). **Deferred** per Matthew: not pursuing Garmin B2B developer approval right now. Documented as the future option if Strava-as-router ever becomes unacceptable; re-open as its own work order when revisited.
- **Unofficial `garminconnect` library as an ingestion path — rejected.** Repeatedly dies on a ~48h cycle (token-refresh throttling + datacenter-IP flagging); unsuitable for set-and-forget automation.

## Out of scope (explicit — do not build)

Any new activity/effort scoring model or classifier; any public surface; rewriting the coaching generator beyond the pull-order + honesty guard; a separate analytical store; Garmin 429 egress mitigation (separate item); GARM-1 / official Garmin API (deferred, above); causal language anywhere in output strings. Re-propose separately if revisited.
