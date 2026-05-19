# Handover — v6.8.3: PR 1 — HAE source-priority + platform_logger fix (TD-15/16/18/20) + MCP outage hotfix

**Date:** 2026-05-03
**Scope:** TD_BATCH_HAE_FIXES spec end-to-end (TD-15/16/18/20). Plus an unplanned MCP outage hotfix that fired during the deploy window.
**Type:** Production correctness fix + 9.5-hour MCP outage recovery.

## What deployed

| Item | Mechanism | Status |
|---|---|---|
| Shared layer v42 (with TD-20 platform_logger fix) | `cdk deploy LifePlatformCore` | ✅ live |
| `SHARED_LAYER_VERSION` 41 → 42 in `cdk/stacks/constants.py` | source commit `5eaf6b1` | ✅ |
| TD-15/16/18 (HAE SOURCE_PRIORITY + weight_body_mass alias) | `deploy/deploy_lambda.sh health-auto-export-webhook` (then re-bundled by CDK) | ✅ live |
| Layer v42 attached to all 65 layer-dependent Lambdas | `cdk deploy LifePlatformIngestion / Compute / Email / Operational / Web` (stack-by-stack) | ✅ live |
| MCP outage hotfix: rename `_decimal_to_float` → `decimal_to_float` | `aws lambda update-function-code` + `cdk deploy LifePlatformMcp` | ✅ live |

## TD detail

- **TD-15** [HIGH] — `lambdas/health_auto_export_lambda.py` v1.7.0 ports `SOURCE_PRIORITY` + `pick_source_or_all()` from `backfill/backfill_apple_health_export_v16.py`. Per-source per-day accumulators + priority-based dedup. Fixes iPhone+Garmin step double-count + My-Water+MacroFactor water double-count.
- **TD-16** [MED] — subsumed by TD-15.
- **TD-18** [LOW] — adds `weight_body_mass` / `Weight Body Mass` aliases to the Body Mass METRIC_MAP entry. iOS HAE export sends this name variant.
- **TD-20** [LOW] — `lambdas/platform_logger.py` v1.0.2 normalizes `exc_info=True` / `BaseException` to tuple before `makeRecord`. Pre-fix every error log line emitted a secondary `TypeError: bool object is not subscriptable` from `formatException`.

## Tests added

- `tests/test_health_auto_export.py` — 16 tests (8 priority resolver, 4 e2e dedup, 3 weight alias, 1 Tier-2 fallthrough)
- `tests/test_platform_logger.py` — 5 tests (exc_info=True / BaseException / tuple / None / False forms; all assert no secondary TypeError leak)
- All 21 pass; no regressions in the 1131 prior tests.

## The MCP outage (unplanned, mid-PR-0-deploy)

**Timeline:**
- 2026-05-03 05:51 UTC — PR 0 Op A (hand-zip MCP deploy) shipped commit `de57c67`'s latent typo (`_decimal_to_float` from `mcp.core` — no such name exists) for the first time. The Lambda was last deployed 2026-04-07 19:55 UTC, ~7 hours BEFORE that commit landed; bug was in source for ~3 weeks but never reached production until the PR-0 deploy.
- 06:00 UTC — PR 0 Op B (cdk deploy LifePlatformMcp) re-uploaded the same broken code.
- 15:19 UTC — canary detected MCP returning 502 Bad Gateway (`Runtime.ImportModuleError`).
- 15:20 UTC — full test suite caught it (`test_i14_canary_mcp_check_passes`).
- 15:23 UTC — hotfix deployed (`aws lambda update-function-code` + `cdk deploy LifePlatformMcp` for the warmer).
- **Total outage: ~9.5 hours**, all overnight while Matthew was off-platform. Caught by canary, not by an active user.

**Root cause:** `mcp/tools_data.py:493` and `mcp/tools_coach_intelligence.py:8` imported `_decimal_to_float` from `mcp.core` but the function is `decimal_to_float` (no underscore). Latent typo from `de57c67` (v6.6.0).

**Lesson learned (carried into the rest of PR 1):** before doing `cdk deploy --all` style broad pushes that re-upload Lambda code from source, run `python3 -m pytest tests/test_lambda_handlers.py` AND a spot-import check on the most-recently-modified Lambdas. The lambda_handlers AST tests pass even with `_decimal_to_float`-style import errors because they don't actually import the modules. The spot-import check would have caught this in <1s.

I added that spot-check before deploying the Compute / Email / Operational / Web stacks. All 5 stack deploys succeeded with no further latent bugs surfacing.

## Carry-forward — Matthew action item

**Re-run v16.1 backfill for the interim window.** The existing Apple Health export at `datadrops/apple_health_drop/apple_health_export_may2/export.xml` is from 2026-05-02 18:32 PT — it doesn't cover the interim window when the live HAE was still double-counting. To close the loop:

1. Export Apple Health data from iPhone (Settings → Health → profile picture → Export All Health Data)
2. Drop the new export.zip into `datadrops/apple_health_drop/` and unzip into a new `apple_health_export_may3/` folder
3. Run: `python3 backfill/backfill_apple_health_export_v16.py datadrops/apple_health_drop/apple_health_export_may3/export.xml --since 2026-05-02`
4. Verify expected step-count drop on May-2 and May-3 records (iPhone+Garmin overlap days)

~5 minutes once the export is in hand. The bug is now fixed in the live Lambda so going-forward webhook traffic is correct; this just cleans up the interim window.

## Behavioral change to expect

**Step counts will drop ~50% on iPhone+Garmin overlap days.** This is the bug fix making things correct, not a regression. RUNBOOK.md should pick this up under "Known surprising behaviors" — I'm flagging it for the docs sync but didn't write it tonight (separate cleanup commit if needed).

## Pre-PR housekeeping (already covered in v6.8.2 handover but recapped here)

- v6.8.0-retroactive COST-OPT-2 commit
- 6 untracked design docs from 2026-05-02 cowork session
- Restored `deploy/sync_doc_metadata.py` from archive
- Doc metadata sync across 8 docs

## What's next

- **PR 2** — TD-12 (Todoist daily cron) + TD-14 (PR template + parity-debt label). Small housekeeping.
- **PR 3** — SECRETS_MAP verification. Findings tonight that go in this PR:
  - AWS has 15 `life-platform/*` secrets; KNOWN_SECRETS in test had 13 + wildcard
  - PR 0 added `todoist`; still missing from KNOWN_SECRETS: `anthropic-api-key`, `eightsleep-client`
  - Stale entry in KNOWN_SECRETS: `webhook-key` (deleted 2026-03-14)
  - ARCHITECTURE.md heading says "9 active secrets" but the table lists 10 — header/table drift
- **PR 4** — write merged FH v2 spec first (reconciling Matthew's tonight version with the alternate Technical Board version), get approval, then code 4a/4b/4c.
- **PR 5** — TD-19 Phase 1 audit only.
- **PR 6** — TD-11 Step 1 audit only.

## State snapshot

| Metric | Value |
|--------|-------|
| Version | v6.8.3 |
| Lambda Layer | v42 (was v41) — TD-20 fix included |
| Lambdas | 66 (unchanged) |
| MCP Tools | 123 (unchanged) |
| Stacks deployed in this PR | 6 (Core + Mcp + Ingestion + Compute + Email + Operational + Web — 7 total, but Mcp + Web were minimal) |
| Spec moved to archive | docs/specs/TD_BATCH_HAE_FIXES.md → docs/archive/TD_BATCH_HAE_FIXES_2026-05-02.md |
