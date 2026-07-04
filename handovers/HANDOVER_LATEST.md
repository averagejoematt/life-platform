# HANDOVER — the Now-remainder batch: #473/#474/#477/#480/#481/#482/#497 + #518 — 2026-07-04 (session 7)

**The data-source health review's Now milestone is PAID DOWN TO ZERO.** The last
seven `area:data` Now stories + the #518 health-check misfire shipped in one batch:
PRs **#523** (the batch) + **#524** (layer **v101** pin). All eight issues
auto-closed; `gh issue list --label area:data --milestone Now --state open` returns
**empty**. Two of the seven were decision stories — both decided and recorded:
**#474 retire** (ADR-103 ledger row), **#497 disable** (ADR-074 updated).

---

## What shipped (PR #523, 22 new tests in `test_now_remainder_batch.py`)

- **#477 (E-2)** — habitify `refresh_trailing_days=1`: yesterday gets one
  post-midnight rewrite, so past-day `in_progress` resolves failed and
  late-evening checks land. **Live-verified on real data:** yesterday's record
  sat frozen at `pending_count=61` (the 23:05 UTC write); one invoke after
  deploy → `pending_count=0`, honestly finalized.
- **#480 (E-5/A-7)** — the supplement bridge now MERGES around manual
  `log_supplement` entries (bridge owns only `source=habitify_bridge` rows);
  validator specs repointed to written names (whoop `sleep_quality_score`,
  eightsleep `hr_avg`, todoist `completed/active/overdue_count`, supplements
  `supplements` list); whoop `#WORKOUT#` sub-records route to their own
  `whoop_workout` mini-schema (ends ~1,500 false warnings/fortnight).
- **#481 (A-1/A-9)** — eightsleep's 401-path re-login now persists the fresh
  token (`save_secret`'s first call site). **Live drill:** run 1 hit 401 →
  "fresh token persisted"; forced cold start; run 2 → **no 401** — the
  18-password-grants/day loop is dead. Framework secret writeback retries once
  and ERRORs "re-auth likely needed" on double failure (a lost Whoop writeback
  strands the rotated refresh token — never again a shrugged-off warning).
- **#482 (X-6)** — `ingestion_framework.phase_for_date()` is public; every
  standalone writer stamps phase: HAE (`if_not_exists` in the merge update),
  notion, macrofactor, food_delivery, measurements. PHASE_TAXONOMY.md §8 notes
  the closure. Live-proven by the measurements drill record (`phase=experiment`).
- **#473 (B-4/X-12)** — measurements re-armed end-to-end: S3 notification
  (merged into the bucket config — NEVER clobber it; backup in the session
  scratchpad) + CDK invoke permission; multi-row CSVs ingest every session;
  `session_number` = date rank (re-import-stable, replaces COUNT+1 drift).
  **Live drill:** uploaded a synthetic CSV → trigger fired → record landed with
  `session_number=2`, `phase=experiment`, derived ratios; drill record deleted
  after (the S3 drill file `imports/measurements/2026-07-04-drill.csv` remains —
  bucket policy explicit-denies DeleteObject on `imports/*`; it's inert).
- **#474 (D-5) — DECIDED: RETIRE** the apple_health XML path (ADR-103 ledger
  row added). The lambda was a latent full-replace clobber of HAE-merged
  records and its S3 trigger never existed. `apple-health-ingestion` function +
  role deleted from CDK and live (verified ResourceNotFound);
  `backfill/archive/backfill_apple_health.py` hard-guarded
  (`I_UNDERSTAND_THIS_CLOBBERS_HAE_RECORDS=yes` to override); `backfill.command`
  menu entry removed; `ci/lambda_map.json` + test lists pruned.
- **#497 (C-2) — DECIDED: DISABLE** the garmin cron (ADR-074 status updated).
  It fired 4×/day into a throttle it lost to on 06-16 (~73 consecutive
  failures), each hit prolonging the lockout. Live: `aws events list-rules`
  shows no Garmin rules. Revive = manual re-auth + restore `schedule=` in
  ingestion_stack (documented in both ADR-074 and the CDK comment).
- **#518** — REQUIRED_SECRETS audited against `list-secrets`: the never-existed
  `life-platform/dropbox` removed (red daily since 05-25), todoist + hevy
  added. **Live: pipeline-health-check now `passed:17 failed:0 paused:0` — the
  first fully-green run since May 25.**

## Deploy (all live 2026-07-04 ~16:45 UTC, session-scoped merge+deploy approval)

CONVENTIONS §1: build → Core published **v101** → pin merged (#524) → Ingestion
(diff read: Garmin schedule-rule destroy + AppleHealthIngestion function/role
destroy + Measurements S3 permission add — all intended), Compute, Email, Mcp,
Operational. Monitoring: zero diff. Bucket notification updated via
`put-bucket-notification-configuration` with the MERGED config (4 lambda configs).
No site/web changes in this batch — no site-api deploy or site sync needed.

## Gotchas for the next session

- **Bucket notifications are replace-not-merge**: always `get` → append → `put`
  the whole config (backup saved first). They live OUTSIDE CDK.
- `ci/lambda_map.json` + `test_lambda_handlers`/`test_wiring_coverage`/
  `test_ddb_patterns` lists must be pruned when deleting a lambda; the doc-sync
  hook re-counts lambdas (87→86) in PLATFORM_FACTS.
- `imports/*` has an explicit DeleteObject deny for matthew-admin (same class
  as raw/ config/ uploads/ generated/) — drill artifacts there are permanent.
- black rewraps a >140-char `X = N  # comment` into `X = (\n N #...\n)` — put
  the comment on its own line for constants the CI greps.

## Open / next

- **The area:data Now milestone is EMPTY.** Next-tier data work lives on the
  Next/Later milestones (journal remainder J-2/J-6/X-7/E-6 in epic #464, whoop
  webhooks A-8, unified-sleep A-2 fix-or-retire, TDEE chain B-1, etc.).
- Watch (carried): `slo-source-freshness` 7-day OK window from 07-04;
  #477's habitify AC includes honest percentages going forward — historical
  pending-frozen days (any date < 07-03 with pending_count > 0) self-heal only
  if re-invoked with `date_override`; they're annotated as unrecoverable-honest
  otherwise (Habitify's API journal is the same data either way).
- Eight Sleep: expect `Eight Sleep 401 — re-logging in` to appear ~once per
  token lifetime now instead of every run — worth a 7-day log check (#481's AC).
- 6 pre-existing env-dependent local test failures unchanged (coaches_api ×4,
  hevy_compiler_isolation, integration_aws) — green in CI.
