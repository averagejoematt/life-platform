# Handover — v6.8.7: PR 5 + PR 6 — TD-19 + TD-11 audits (doc-only)

**Date:** 2026-05-03
**Scope:** Audit-only PRs. PR 5 covers TD-19 Phase 1 (date partition convention per Lambda). PR 6 covers TD-11 Step 1 (Habitify API state taxonomy). Both gate their respective implementation phases on Matthew approval.
**Type:** Documentation. No Lambda code, no infra deploys.

## What deployed

| Item | Mechanism | Status |
|---|---|---|
| `docs/audits/TD-19_DATE_PARTITION_AUDIT.md` | git commit | ✅ |
| `docs/audits/TD-11_HABITIFY_API_AUDIT.md` | git commit | ✅ |

## TD-19 audit headlines (PR 5)

Audited 16 ingestion Lambdas + 1 backfill script for date-keying convention.

| Verdict | Count | Lambdas |
|---|---|---|
| ✅ UTC | 8 | whoop, garmin, withings, strava, todoist, weather, measurements, food-delivery |
| ❌ PT-local needs fix | 2 | **health-auto-export-webhook**, **apple-health-ingestion** |
| ⚪ Event-anchored (no fix needed) | 5 | eightsleep (wake-date semantic), habitify, macrofactor, dropbox-poll, function-health |
| ⚠️ Notion (explicit PT — intentional?) | 1 | notion-journal-ingestion |
| 🪞 Backfill drift | 1 | `backfill_apple_health_export_v16.py` (mirrors HAE; per TD-14, must fix in same PR as HAE) |

**Bug locator:** `lambdas/health_auto_export_lambda.py` `parse_date_str()` and `lambdas/apple_health_lambda.py` `parse_date()` both return `date_str[:10]` — strip the date part of a timestamp like `"2026-05-02 21:00:00 -0700"` → `"2026-05-02"` without TZ conversion. The 9pm PT case lands at `DATE#2026-05-02` while every other source lands at `DATE#2026-05-03` for the same instant.

**Phase 2 preview** (gated on Matthew):
- Modify `parse_date_str` in HAE + `parse_date` in apple_health Lambda to convert to UTC before extracting date.
- Same fix in `parse_dt` in `backfill_apple_health_export_v16.py` (TD-14 parity discipline).
- Phase 3 (historical migration) is its own dedicated PR — DDB cost + idempotency risk.

## TD-11 audit headlines (PR 6)

Captured raw `/journal` responses from Habitify API for 3 days (2026-05-01 final, 2026-05-02 final, 2026-05-03 mid-day) plus `/habits` registry. Auth via `life-platform/habitify` secret.

**Headline finding:** spec assumed 5-state taxonomy (`completed`, `skipped`, `not_scheduled`, `pending`, `failed`) but Matthew's current registry only exercises 3:

| Status | Observed? | Notes |
|---|---|---|
| `completed` | ✅ | habit done, current_value ≥ target_value |
| `in_progress` (= "pending") | ✅ | not yet completed; mid-day state |
| `failed` | ✅ | not completed past UTC end-of-day |
| `skipped` | ❌ NOT OBSERVED | Matthew doesn't actively skip habits in Habitify |
| `none` / `not_scheduled` | ❌ NOT OBSERVED | API returns all habits regardless of schedule |

**Status distribution snapshot:**
- 2026-05-01 (final): 0 completed / 1 in_progress / 64 failed
- 2026-05-02 (final): 0 completed / 2 in_progress / 63 failed
- 2026-05-03 (mid-day, ~10:30 AM PT): 1 completed / 64 in_progress / 0 failed

**The practical bug**: live Lambda maps both `in_progress` and `failed` to `0.0`, conflating "pending today" with "failed yesterday". Three-state enum (`completed | pending | failed`) sufficient for current registry; reserve slots for `skipped` + `not_scheduled` for future-proofing.

**Frequency patterns**: 65/65 daily, 0 BYDAY (no specific-weekdays habits), 1 monthly periodicity (Sauna — daily appearance + monthly aggregation; edge case requires special handling).

**Backfill feasibility**: `/journal?target_date=…` accepts arbitrary historical dates. **Spec's Option C (backfill via API) is feasible.** ~70s for 70 days. No need for the lossy hard-cutover Option A.

**Cutoff timing**: Habitify flips `in_progress` → `failed` at UTC end-of-day (reference_date is always `00:00:00.000Z`). Platform inherits this for free.

**TD-19 dependency check**: per PR 5 audit, Habitify Lambda is already UTC-clean. TD-11 can proceed independently of TD-19 fix-forward.

## All 7 PRs in this session — summary

| PR | Scope | Status |
|---|---|---|
| PR 0 (inserted) | TD-21/22/23 — MCP unbreak (timezone import + signature + IAM Todoist) | ✅ shipped + hotfix |
| Hotfix | `_decimal_to_float` → `decimal_to_float` (latent typo from de57c67 v6.6.0) | ✅ ~9.5h outage, recovered 3 min after canary |
| PR 1 | TD-15/16/18/20 — HAE source-priority dedup + platform_logger fix + layer v42 | ✅ shipped |
| PR 2 | TD-12/14/17 — Todoist daily cron + PR template + parity-debt label (TD-17 = Matthew action) | ✅ shipped |
| PR 3 | TD-13 — SECRETS_MAP reconciliation against AWS reality (15 secrets) | ✅ shipped |
| PR 4 (a + b + c) | FH v2 — MCP tools (get_lab_deltas, get_allergies, cadence) + private supplements page + labs v1.5 panels | ✅ shipped |
| PR 5 | TD-19 Phase 1 audit | ✅ shipped (audit only) |
| PR 6 | TD-11 Step 1 audit | ✅ shipped (audit only) |

## Carry-forward Matthew action items

| Item | Source PR | Notes |
|---|---|---|
| Run smoke tests on PR 0 (`create_experiment`, `create_todoist_task`, `get_todoist_projects`) | PR 0 | MCP was 502 during the deploy window; tests valid only after the hotfix landed |
| Fresh Apple Health export from iPhone → run v16.1 backfill for May 2 → May 3 interim window | PR 1 | ~5 min once exported; commands in HANDOVER_v6.8.3 |
| Disable Tier-2 feeds (HR/RHR/SpO2/respiratory) in Health Auto Export iOS app | PR 2 (TD-17) | Phone settings only |
| Decide on orphan `life-platform/anthropic-api-key` (delete or wire up) | PR 3 | Created 2026-03-18, no consumer in source |
| Decide on Todoist secret consolidation (ingestion still uses bundle, MCP uses dedicated) | PR 3 | Low priority |
| Approve TD-19 Phase 2 (HAE + apple_health Lambda fix-forward) | PR 5 | 4 questions in audit doc |
| Approve TD-11 Step 2 (schema design — 5 questions in audit doc) | PR 6 | Independent of TD-19 per audit |
| Spec: write merged FH v3 spec or archive both originals | PR 4 | I skipped the merged-spec ceremony per "complete all PRs" direction; both originals are now in `docs/archive/` |

## Commits this session (chronological)

```
852be19 v6.8.0-retroactive: COST-OPT-2 prompt caching + model tiering
1c2a9f5 docs: capture prior 2026-05-02/03 session design artifacts
d8a63a0 fix: restore deploy/sync_doc_metadata.py from archive
dc0ac14 docs: sync platform metadata across 7 docs (auto + HANDOVER fix)
b0306b0 PR 0: TD-21 + TD-22 + TD-23 — unbreak ~40 MCP write tools
9ac9630 docs: v6.8.2 handover + CHANGELOG for PR 0 (TD-21/22/23)
cf0fdcb docs: bump version stamps to v6.8.2 (auto, sync_doc_metadata)
4034dc8 hotfix: rename _decimal_to_float → decimal_to_float (MCP import error)
0695b39 PR 1: TD-15/16/18/20 — HAE source-priority dedup + platform_logger fix
5eaf6b1 PR 1 (Op B): bump SHARED_LAYER_VERSION 41 → 42
17801c6 docs: v6.8.3 handover + CHANGELOG for PR 1 + archive HAE batch spec
9d906f1 docs: bump version stamps to v6.8.3 (auto, sync_doc_metadata)
d354b39 PR 2: TD-12 + TD-14 — Todoist daily cron + parity-debt PR template
c54947f docs: bump version stamps to v6.8.4 (auto, sync_doc_metadata)
a7b1410 PR 3: SECRETS_MAP verification + KNOWN_SECRETS reconciliation (TD-13)
0339cdb docs: bump version stamps to v6.8.5 + ARCHITECTURE secrets table cell
57527ad PR 4a: get_lab_deltas + get_allergies + cadence_trackers (FH v2)
ca1425d PR 4 (b + c) + docs: supplements protocol page + labs v1.5 + v6.8.6 wrap
9775839 PR 5: TD-19 Phase 1 audit — date partition convention per Lambda
36ff21d PR 6: TD-11 Step 1 audit — Habitify API state taxonomy
TBD     v6.8.7 wrap: PR 5 + PR 6 handover + CHANGELOG
```

## State snapshot

| Metric | Value |
|--------|-------|
| Version | v6.8.7 |
| Lambda Layer | v42 (was v41) |
| Lambdas | 66 (unchanged) |
| MCP Tools | **125** (was 123) |
| Secrets in AWS | 15 (unchanged; now correctly cataloged) |
| New site pages | +1 (`/supplements/protocol/`) |
| Audit docs | +2 (TD-19, TD-11) |
| Specs archived | 4 (TD_BATCH_HAE_FIXES, TD_QUICK_DECISIONS, FUNCTION_HEALTH_V2_HANDOFF — both versions) |
| Specs remaining in `docs/specs/` | 2 (TD-19_DATE_PARTITION_FIX, TD-11_HABITIFY_PHANTOM_HABITS — kept until Phase 2 / Step 2 ship) |
