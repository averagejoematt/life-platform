# Handover — v6.8.9: Phase A-D pre-Monday readiness sweep

**Date:** 2026-05-03
**Scope:** Verify + fix everything that would surface as friction when Matthew opens the platform Monday morning. Per the Phase A-D plan from `proud-humming-scone.md`.
**Type:** Mixed — investigation, latent-bug discovery, surgical fixes, deploy, re-baseline.

## Headlines

1. **TD-19 Phase 2 shipped.** `parse_date_str` (HAE), `parse_date` (apple_health), `parse_dt` (v16 backfill) all now convert source-tz timestamps to UTC before extracting partition keys. Eliminates the silent cross-source partition undercount happening in production NOW. 9pm PT events land at UTC date instead of PT-local date — every other source already used UTC. Phase 3 historical migration explicitly deferred to its own PR per spec.
2. **Layer drift bug fixed across 10 Lambdas.** Phase A discovered that `hypothesis-engine`, `ai-expert-analyzer`, `character-sheet-compute`, and 7 others were pinned to layer versions v22 / v25 / v40 — they never picked up TD-20 / COST-OPT-2 / get_freshness_status. Root cause: `compute_stack.py` and `operational_stack.py` didn't pass `shared_layer=` to `create_platform_lambda()`, so once the Lambda was created it stayed on whatever layer was attached at first deploy. CDK constructs updated; all 10 Lambdas now on v42. Most expensive consequence pre-fix: hypothesis-engine + ai-expert-analyzer were missing the COST-OPT-2 prompt caching benefit (~90% Anthropic discount) the entire time COST-OPT-2 has existed.
3. **MacroFactor pipeline unblocked.** dropbox-poll now converts XLSX → CSV in-memory (pure stdlib, no new layer dep). macrofactor-data-ingestion got a new `daily_summary` format detector + parser (handles MacroFactor's current XLSX export format with Excel serial dates). Pipeline ingests cleanly; the existing file in Dropbox writes 4 days (April 4-10). To get current MacroFactor data, Matthew needs to do a fresh export — but the platform is now ready when he does.
4. **WR-48 Enhancement 1 (daily brief stale-source banner) shipped.** Daily brief now prepends a "⚠️ Data Status — N source(s) stale" banner above the brief whenever any source is past its threshold. Tomorrow's brief will tell Matthew upfront if data is stale — if grade is low, the banner explains whether it's real (his data) or platform-induced (stale ingestion).
5. **Two latent Lambda bugs caught and fixed in Phase A.** `tool_get_health_trajectory` was failing nightly in warmer (tz naive/aware mix on Withings dates). `tool_capture_baseline` was failing with kwargs typing bug. Both fixed earlier in tonight's session.
6. **Site nav updated.** `/supplements/protocol/` is now linked from the global nav under "The Practice → The System." Matthew's private supplement protocol page is discoverable.
7. **Cycle 2 re-baseline captured.** `MEMORY#baseline_snapshot#2026-05-03` (label=`reentry_2026_05_03`) refreshed AFTER warming jobs ran. Three domains captured (weight/recovery/nutrition).

## Phase A findings (informational, no action needed beyond what was done)

- **Daily-brief Grade 39 (F) is REAL, not AI failure.** The `DataPresent` metrics show why: macrofactor=0, strava=0, supplements=0, others=1. 3 sources missing → grade pulled down. Once Matthew re-exports MacroFactor + opens Strava + logs supplements, grade recovers.
- **Anomaly-detector flags from Sat May 2 are real signal.** Whoop RHR 69 (Z=3.68 high) + Garmin Body Battery 23 (Z=-3.17 low). Coherent physiological stress, likely tied to the move stress + re-entry. Anomaly-detector working correctly.
- **public_stats.json is fresh** (refreshed 19:00 UTC by daily-brief Lambda). character_stats.json doesn't exist at expected path — out of scope tonight.
- **chronicling partition** still stale at 2025-10-29 (Habitify took over). Documented as deprecated artifact; no data deleted.
- **dropbox_poll Lambda was actually healthy all along** — the "null" was misleading; the file in Dropbox was just XLSX which we couldn't read. Now we can.
- **freshness-checker SNS:Publish IAM** restored earlier tonight in the WR-48 fix. Confirmed working.

## Cumulative state at end of Sun 2026-05-03 session (across all v6.8.x handovers)

| Item | State |
|---|---|
| Version | v6.8.9 |
| Lambda Layer | v42 |
| Lambdas on layer v42 | 100% (was missing on 10 before tonight's Phase B fix) |
| MCP Tools | **126** (added get_freshness_status earlier tonight) |
| New CloudWatch alarms | 2 (freshness-checker-not-emitting backstop + canary-anthropic-failure) |
| New IAM permissions | 3 sets (sns:Publish on freshness-checker, todoist secret on MCP, ai-keys on canary) |
| Bugs caught + fixed in passing | 5 (`_decimal_to_float` typo, `health_trajectory` tz-mix, `capture_baseline` kwargs, MCP timezone import, layer drift) |
| New site pages | 1 (`/supplements/protocol/`) — now linked in nav |
| New runbook | `docs/RUNBOOK_REENTRY.md` |
| Audit docs | 2 (TD-19, TD-11) |
| Specs archived | 4 (TD_BATCH_HAE_FIXES, TD_QUICK_DECISIONS, both FH handoffs) |
| Specs remaining | 2 (TD-19_DATE_PARTITION_FIX [Phase 3 still pending], TD-11_HABITIFY_PHANTOM_HABITS [Step 2+ still pending]) |

## Final freshness snapshot (per get_freshness_status)

```
OVERALL: red | stale=2 fresh=10
  STALE strava: 2026-04-18 (15d, threshold 2d) — Matthew needs to open Strava app to refresh OAuth
  STALE macrofactor: 2026-04-11 (22d, threshold 2d) — Matthew needs to re-export from MacroFactor (XLSX now supported)
```

All other 10 sources fresh as of today. The 2 remaining stale items are Matthew-action.

## Carry-forward Matthew action items (cumulative)

**Immediate (Monday morning):**
1. **Open Strava app on phone**, force a sync. Re-auth if OAuth expired.
2. **Re-export MacroFactor data** (XLSX is fine now — pipeline handles it). Drop into Dropbox `/life-platform/`. Will auto-ingest within 30 min.
3. **Run PR 0 MCP smoke tests** (`create_experiment`, `create_todoist_task`, `get_todoist_projects`) from claude.ai or Claude Desktop.
4. **Write the Phase 5 re-entry journal entry** in Notion. Pipeline ingests automatically; Elena Voss + Paul Conti get it for the next digest.
5. **Disable HAE Tier-2 feeds** in iOS Health Auto Export app (TD-17): Settings → Automations → untoggle HR/RHR/SpO2/respiratory.

**This week:**
6. Fresh iPhone Apple Health export → run `python3 backfill/backfill_apple_health_export_v16.py datadrops/apple_health_drop/<dropname>/export.xml --since 2026-05-02`
7. 278-overdue Todoist triage (~30 min)
8. Anniversary planning (per the original AJM re-entry plan)
9. Decide on orphan `life-platform/anthropic-api-key` (delete or wire up consumer)

**Decisions for next session (no immediate action):**
10. Approve TD-19 Phase 2 historical migration (Phase 2 fix-forward already shipped tonight; Phase 3 = backfill old partitions to UTC convention — DDB cost + idempotency risk)
11. Approve TD-11 Step 2 (Habitify schema design — audit done, design pending)
12. WR-47 Pause Mode build (specced; would close the loop on TD-11 + WR-50)
13. Decide on chronicling partition deprecation (data deletion needs explicit ok)
14. Decide RSS-while-gated (path exclusion in cf-auth)
15. Bedrock migration (deferred per HANDOVER_v6.8.1 "30 days cost data" gate)

## Commits this Phase A-D wave

```
TBD  PR re-entry Phase B: TD-19 Phase 2 + MacroFactor XLSX/summary + layer drift fix
TBD  PR re-entry Phase C: WR-48 Enh 1 daily brief banner + warming + re-baseline
TBD  feat: site nav link to /supplements/protocol/
TBD  docs: v6.8.9 handover + CHANGELOG + Matthew action list
```

## What's true tomorrow morning when Matthew opens the platform

✅ Daily brief lands at 10 AM PT with REAL grade and an explicit "Data Status" banner if anything is stale
✅ Labs page renders the FH 2026 v1.5 panels (verified by tonight's static analysis)
✅ Supplements protocol page is in the nav under "The Practice"
✅ All MCP tools work (canary armed for Anthropic disable + freshness backstop alarm armed)
✅ Cross-source data is correct (TD-19 Phase 2 fixed)
✅ 10/12 sources fresh; 2 stale items (Strava + MacroFactor) require Matthew to open the apps
✅ All Lambdas on shared layer v42 (prompt caching benefit reaches AI Lambdas)
✅ Cycle 2 baseline captured for "where am I now" measurement reference

## State snapshot

| Metric | Value |
|--------|-------|
| Version | v6.8.9 |
| Lambda Layer | v42 |
| Lambdas | 66 |
| MCP Tools | 126 |
| Stacks deployed in this wave | Compute + Operational + Ingestion + (S3 sync for site nav) |
| Layer drift Lambdas | 0 (was 10) |
| Stale sources | 2 (down from 5; the 2 require Matthew app interaction) |
| New CloudWatch alarms total | 2 (across whole session) |
| Cycle marker | Cycle 2: Re-Entry (started 2026-05-02) |
