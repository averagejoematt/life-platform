# Handover — 2026-08-18 (daytime, ~06:30 → ~12:00 PT): the failure that looked like health

**Session:** Opus, owner-directed (plan `opus-boxes-and-hardening`, model ceiling Opus — no
kernel builds; #2846/#2847 stay Fable-sequenced). Boot was **charter + model** (#2845) rather
than a prose re-read. The session started ~06:30 PT, so every Phase-0 box was still ahead of
the clock — Phase 1 and the fan-out ran first, and the boxes were taken as they fired.

**Build beat:** `2026-08-18-the-failure-that-looked-like-health` — on `main` and validated, but **NOT currently served**: the wrap deploy auto-rolled-back on the #2878 vitals-smoke gate (see Incidents). It publishes on the next successful site deploy, which is owner-gated on a Withings weigh-in.
**Docs:** CONVENTIONS §9 (gate registry row), INCIDENT_LOG (recurrence pointer + 1 new row),
ARCHITECTURE/INFRASTRUCTURE/MONITORING (alarm count 103→104), DATA_GOVERNANCE (retention table),
DEPENDENCY_GRAPH + `model/platform_model.json` (regenerated) — all landed inside their PRs; the
wrap's `sync_doc_metadata --apply` found everything already in sync.
**Decisions:** none needed — the session's judgement calls (emitter at the error envelope, alarm
in `serve_stack` not `monitoring_stack`, absence-marker opt-in scoped to non-behavioral
`DAILY_SOURCES`) are implementations of existing ADRs 104/125/050, and are recorded in
CONVENTIONS §9 and in-code rather than as new governance.
**Incidents:** 2 rows added — (1) the wrap-beat site auto-rollback: a TRUE positive about the
data and a FALSE positive about the deploy — the vitals smoke carve-out keys on `day_n <= 1`
rather than on whether a weigh-in happened, so **every `site/**` deploy auto-rolls-back until
one lands** (#2878, owner-gated); (2) a merge to `main` produced ZERO CI runs (swallowed-push
class, second documented occurrence; caught by a by-`head_sha` check, recovered by manual
dispatch).
**Main:** green (`9e3659a1`) — `check_main_green.py` exit 0.
**CI warnings:** 1 — Unit Tests 1297s vs the 1200s budget (fifth crossing). Triaged to the
existing #2692 with today's datapoint and an explicit **no-action call**: not raising the budget,
not filing a duplicate; #2692 owns the measure-first decision and its rationale is unchanged.
**Alarms:** clean — every alarm red >72h cites an incident row or issue; none red >14d uncited.
**Backlog:** Now live at 11 actionable; no stale `Later` issues.
**Closures:** #2819, #2642, #2866, #2643 commented (ADR-099 two-line contract).
**Stash/hooks:** clean — `git stash list` empty.

## What shipped — 4 PRs merged + deployed, 4 issues closed, 1 filed

- **#2874 (#2819, the headline) — the handled-5xx detector.** A handled 500 returns
  `_error(500, …)` instead of re-raising, so AWS/Lambda `Errors` stays 0 and `site-api-errors`
  never fires — `/api/fulfillment_ritual` served handled 500s for ~4h on 2026-07-19 with nothing
  to notice. `emit_handled_5xx()` in `site_api_common` now emits a `Handled5xx` EMF datapoint from
  **all three** response builders: `_error` (the 29-module chokepoint), `_envelope` (the #2221
  write doors), and `site_api_ai_lambda`'s own `_error` (that lambda does not share the common
  one, so `/api/ask` + `/api/board_ask` would otherwise have stayed blind). Alarm
  `site-api-handled-5xx` → digest, Sum ≥ 5/15min, `NOT_BREACHING`.
  **The load-bearing finding: `_emit_route_log` is NOT a chokepoint.** It sits on the
  `ROUTES.get(path)` tail, so 27 routes return before reaching it. Hanging the metric there would
  have covered a strict subset while reading as complete on a dashboard.
- **#2873 (#2642) — S3 noncurrent-version lifecycle.** The worker **corrected the brief**: the
  bucket is `Bucket.from_bucket_name` (imported), so CDK *cannot* own its lifecycle —
  `deploy/apply_s3_lifecycle.sh` is the source of truth — and the fix had already been applied
  live on 08-16 without ever being written back to the script, which
  `put-bucket-lifecycle-configuration` **replaces wholesale on every run**. One stale re-run from
  silent reversion. Measured 96.87 GB (08-15) → 37.72 GB (08-16).
- **#2875 (#2866) — cron map derives from the model.** `check_doc_facts._cdk_cron_map` now calls
  the #2845 generator's `extract_lambdas()`; whoop went from one wrong entry (its *recovery* cron)
  to its real three-schedule set. #1189 non-vacuity mutation re-proven.
- **#2877 (#2643) — Eight Sleep's 08-09 interior gap.** Settled by **direct live vendor probe**:
  the trends API queried on 08-18 for 08-05..08-12 returned every day except 08-09, nine days
  later — branch 2, a real night not in the pod. Plus the mechanism defect behind it: a date that
  ages out of the gap-fill window was simply forgotten. New opt-in
  `record_gap_exhausted_absence` writes an ADR-104 marker on a date's **last** retry.
- **Filed #2876** — the 27 routes that reach no route-metric at all, so per-route latency is
  **absent, not zero**. Both routes from the 2026-07-19 latency incident are on that list.

## Phase 0 boxes

- **#2668 — 2 of 3, NOT closed.** The plan expected today to close it; that premise was off by
  one. `[INFO] IC-3 analysis parsed clean` was added *by the fix itself*, so 08-13/15/16 were
  silent successes under the old code (which logged only on failure), and the fix — committed
  08-15 15:07Z — was not in the live bundle until 08-17. Runs with positive evidence: 08-17 = 1,
  08-18 = 2 (clean at 17:07:19 and 17:07:50), **08-19 = 3**. Honest count commented, not closed.
- **#2858 — box confirmed, not reopened.** The 18:30Z sweep: `FailCount 0`, 58 passes, no
  `recall:*` line. Because a pass is *silent* in that log, the box was confirmed against the
  underlying data instead: the recall partition holds 21 chronicle rows and **2026-08-16 is
  present**. The 07-21 link divergence is also resolved (`assess()` fails on either condition).
- **#2735 — on track, carried.** `coherence-overall` is a 24h-`Maximum` alarm whose last
  breaching datapoint is 08-17 21:00Z, so it ages out ~21:00–21:20Z 08-18, exactly as predicted.
  Session closed before that; the plan says comment only if it did NOT clear.
- **#2669 — not applicable.** Wednesday box; today is Tuesday.

## Analysis, deliberately not shipped

- **#1221** (client IP from the trusted hop). The plan said don't ship if uncertain about the
  CloudFront hop model. Verified live: all six `/api/*` behaviours have
  `OriginRequestPolicyId: None`. **New blocking fact:** they are all still on legacy
  `ForwardedValues`, and CloudFront rejects that alongside an origin-request-policy — so
  attaching the policy means migrating all six onto cache-policy pairs, with the public read
  surface's caching as blast radius. Also: the issue body is stale — the `site_api_ai_lambda`
  holdout is already fixed (`grep -c sourceIp` = 0). Owner call; analysis posted on the issue.

## Verified

- `pytest tests/` 19397 passed / 0 failed at the #2819 merge; every merged PR green on its exact
  head sha (`total>0 AND 0 not-green`).
- **#2819 proven three ways beyond unit tests:** emitter symbol-verified in *both* deployed
  bundles (and again after the cdk deploy re-shipped them); the EMF wire shape published to a
  throwaway namespace materialized **both** dimension sets (`[]` aggregate + `Route`) with
  `Sum = 1.0`, proving CloudWatch ingests it — a malformed `_aws` block yields no metric silently,
  which is the very class being fixed; alarm live, `OK`, routed to digest.
- **#2643:** DDB + CloudWatch cross-checked independently of the worker's report before merge;
  marker mechanism symbol-verified in the deployed bundle; backfill applied — series 08-05..08-12
  contiguous, `InteriorGapCount` **1.0 → 0.0 at 16:26Z**, the first emission after the write.
- **#2642:** all 14 live lifecycle rules diffed against the script field-by-field (identical), so
  the post-merge re-apply was a proven no-op rather than a hoped-one.

## Gotchas hit

- **Local `black` was 25.9.0 against the repo's pinned 26.3.1.** A bare `black` run reformatted
  **20 unrelated files** — committing them would have redded CI in both directions. This is the
  documented #2570 class and the fix already exists: `deploy/agent_commit.sh` resolves the pin.
  Reverted the collateral, verified the tree against a venv-installed 26.3.1, and briefed both
  workers after hitting it.
- **A watcher pointed at a log group that does not exist** (`/aws/lambda/qa-smoke`; the real name
  is `/aws/lambda/life-platform-qa-smoke`). It would have reported "nothing found" — an absence
  indistinguishable from a pass, on the very session about absence-vs-failure. Caught by
  verifying the group name before trusting the watcher.
- **A qa-smoke pass is silent.** The sweep logs only WARN/FAIL/PAUSE, so "no `recall:` line" cannot
  by itself distinguish passed from never-ran — hence verifying #2858 against the corpus data.
- **Both sonnet workers stopped mid-flight** waiting on background test runs, with real
  uncommitted work and no PR. Resumed via `SendMessage` (context intact) rather than restarted.
- **A 17:06Z watcher fired ~13s before the brief's IC-3 line** (17:07:19) and reported nothing —
  nearly recorded a clean run as a miss. The brief takes ~8 min; sample after ~17:10Z.

## Residual / next picks

- **#2668** — close on the 2026-08-19 17:00Z brief if it logs `parsed clean` with no truncation
  lines; that is run 3 of 3. Boxes 1/2/4 already met.
- **#2735** — confirm `coherence-overall` returned to OK on its own after ~21:20Z 08-18; comment
  only if it did NOT.
- **#2669** — the Wednesday chronicle box: on/after 08-19's 15:00Z cron, check
  `/aws/lambda/wednesday-chronicle` for ONE generation, <300s, persisted, no duplicates.
- **#2643 fast-follow** — whoop and habitify are the other non-behavioral `DAILY_SOURCES` and have
  not opted into `record_gap_exhausted_absence`; clean today, so left untested rather than shipped
  blind. Covered by #2643's own thread — file if it is to be worked standalone.
- **#2876** — the 27 unmeasured routes; note it is NOT free like #2819's sparse 5xx metric.
- **#2878** — the vitals smoke carve-out (`day_n <= 1` instead of "has a weigh-in happened").
  **This blocks every site deploy right now**; owner ask 3 (a weigh-in) also clears it, but the
  gate shape should be fixed so a content deploy is never reverted for a data condition again.
- **#1221** — owner call on the origin-request-policy migration (see analysis above).
- **#2692** — Unit Tests wall-clock, fifth crossing (1297s); measure-first still the standing call.
- **Owner asks (all three still open, batched below)** — `not-work — owner decisions/actions only`.

## Owner asks — one numbered list

1. **#2836, the September budget base — the sharp one (due 09-01).** Measured today: MTD
   **$107.40** (non-AI $37.29 + AI $70.11), projected month-end **$171.67** against August's
   temporary $200 ceiling, tier 1, surge off (773 uniques < 900). Trailing-7d burn is
   **~$4.71/day**. September auto-reverts to **$85 base / $100 surge** with no deploy — and 30
   days at that burn is **≈$141**, i.e. **166% of the base and 141% of the surge ceiling**. That
   is **tier 3, the hard cutoff**, from early in the month: website AI returns "paused", the daily
   brief skips AI, and both AI CI gates go dark. AI is 65% of spend. Decide the September base (or
   accept the tier-3 state deliberately); answering also largely resolves **#2734**.
2. **Whoop re-auth — still not done.** No rows since 2026-08-16; `ingest-auth-unhealthy-whoop` and
   `ingest-consecutive-failures-whoop` in ALARM since 08-17. After re-auth: #2085 latch-clear,
   verify the next hourly ingest, backfill 08-16→now (dry-run first), watch the vitals qa-smoke
   FAIL clear. The breaker re-latching on TTL until then is expected, not a new fault.
3. **A Withings weigh-in — now also blocking site deploys.** No reading since 08-16; the cycle-14
   genesis baseline still reads the **321.01 override**. Beyond the baseline, this is what the
   #2878 smoke gate is waiting on: until an in-cycle weigh-in exists, every `site/**` merge
   deploys, fails smoke on `/api/vitals: missing weight_lbs`, and auto-rolls-back — today's build
   beat is on `main` but not served because of it. Once you step on the scale, the documented supersede reflex in
   `project_monday_reset` runs (profile + `config/user_goals.json` + `sync_constants_from_config`
   + rebakes + CHARACTER.md stamp).
