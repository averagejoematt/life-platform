# Handover — v6.8.8: PR re-entry sweep — operational fixes + WR-48 (Stale-Source Alerts) + Re-Entry Protocol

**Date:** 2026-05-03
**Scope:** Execute everything in `Downloads/ajm_reentry_plan.md` that doesn't require Matthew's hands-on input. Operational sweep + content scaffolding + Re-Entry Protocol runbook + WR-48 (Stale-Source Alerts) full ship.
**Type:** Mixed — bug fixes, new MCP tool, new alarm, new IAM policy, new runbook, new memory entries.

## Headlines

1. **WR-48 root cause found and fixed.** The freshness-checker Lambda was running daily through the entire 30-day silence and *correctly* detecting 4-5 stale sources every day. Every SNS publish failed silently with `AuthorizationError` because its IAM role was missing `sns:Publish` on `life-platform-alerts`. Adding the policy in `cdk/stacks/role_policies.py operational_freshness_checker()` immediately restored alerting — verified by manual invoke: "Alert sent for 3 stale source(s)" + "Partial completeness alert sent for 3 source(s)" published to the alerts topic.
2. **Backstop alarm shipped.** New `life-platform-freshness-checker-not-emitting` CloudWatch alarm fires if no `StaleSourceCount` metric is emitted in 26h. Closes the "what watches the watcher" gap. Deployed via `cdk deploy LifePlatformOperational`.
3. **`get_freshness_status` MCP tool live.** 126 total tools. Returns green/yellow/orange/red status + per-source last-date / age-days / threshold. Independent of the freshness-checker Lambda — queries DDB directly so it works even if the Lambda silently fails. Live test result: status `red` (Strava 15d stale, MacroFactor 22d stale).
4. **Two more latent bugs caught and fixed in passing:**
   - `tool_get_health_trajectory` was failing in nightly warmer with `can't compare offset-naive and offset-aware datetimes` — Withings weight dates were tz-naive while `today` was tz-aware. Fixed in `mcp/tools_health.py` with `.replace(tzinfo=timezone.utc)` on the parsed dates.
   - `tool_capture_baseline` was failing with `tool_write_platform_memory() got an unexpected keyword argument 'category'` — typing bug that's been latent since the function was written. Fixed by passing args as a dict.
5. **Re-Entry Protocol runbook written.** `docs/RUNBOOK_REENTRY.md` — Day 0 / Day 1 morning / Day 1 afternoon / Day 1 evening / Day 2 morning / Day 2 midday / Day 2 afternoon / Day 2 evening / Day 3+ structure. Synthesized from `Downloads/ajm_reentry_plan.md`. Reusable for any future gap > 7 days.
6. **WR-47 / WR-48 / WR-49 / WR-50 added to PROJECT_PLAN.md.** WR-48 marked ✅ Done (this PR). WR-47 (Pause Mode), WR-49 (One-Click Backfill UI), WR-50 (Re-Entry Day Template) remain as future workrolls.
7. **Cycle markers + capture_baseline + re-entry memory written to DDB.** `CYCLE#1#launch`, `CYCLE#1.5#gap_move`, `CYCLE#2#reentry`, `MEMORY#baseline_snapshot#2026-05-03 (label=reentry_2026_05_03)`, `MEMORY#re_entry#2026-05-03`.

## Operational sweep findings

| Plan item | Finding | Action |
|---|---|---|
| 50 — CloudWatch error sweep | ~50-66 errors/day across all Lambdas; only `life-platform-mcp` had real errors (56 in 3d), all from the `_decimal_to_float` outage window before the 2026-05-03 hotfix | No new action — already resolved |
| 52 — chronicling internal table | Last write 2025-10-29. Habitify Lambda took over the chronicling format role (its docstring says "matches chronicling DynamoDB format for MCP compatibility"). The `chronicling` partition itself is no longer being written to. | Documented as deprecated artifact — not deleting data without Matthew's call. Future TD: either kill the partition or formally retire it in `mcp/helpers.py query_chronicling`. |
| 53 — dropbox_poll | ✅ Lambda runs every 30 min, last 5 successful. The "null" snapshot was misleading — Lambda is working; it's just not finding new CSVs because Matthew exported XLSX (not CSV) from MacroFactor. | No action — pipeline healthy; user education |
| 54 — nightly warming jobs | ✅ Running. 13/14 steps succeed. `health_trajectory` was failing; fixed in this PR. | health_trajectory will pass on the next nightly run (10:10 AM PT) |
| 64 — RSS feed | Returns `cf-auth` password page (HTTP 200 with HTML) because PRIVACY_MODE=true. Expected behavior. | If Matthew wants RSS public while keeping the rest of the site gated, would need a cf-auth path exclusion. Out of scope tonight. |
| 38 — journal ingestion | ✅ Lambda ran 18:00:36 UTC today, successfully ingested 1 entry from Notion at `DATE#2026-05-02`. Journal pipeline is healthy and will pick up Matthew's re-entry entry whenever he writes it. | No action |

## What got deployed

| Op | Mechanism | Resource |
|---|---|---|
| Trajectory fix + capture_baseline fix + freshness MCP tool | `aws lambda update-function-code life-platform-mcp` + warmer | SHA256 `IAXvuS9nAozonw0qjDc8QMiJpvVh34BTVhStkNfhP78=` |
| IAM `SnsPublishAlerts` for freshness-checker + new backstop alarm | `cdk deploy LifePlatformOperational` (30s) | New alarm: `life-platform-freshness-checker-not-emitting` |
| Cycle markers + capture_baseline + re-entry memory | Direct DDB writes | 5 new items in `USER#matthew#MEMORY` partition |

## Verification

- ✅ Freshness checker SNS publish: invoked manually post-deploy → "Alert sent for 3 stale source(s)" in CloudWatch logs
- ✅ `get_freshness_status` MCP tool: returns `status=red, stale=2 (strava 15d, macrofactor 22d), fresh=10`
- ✅ `get_health view=trajectory`: no longer raises tz comparison error; returns weight trajectory dict
- ✅ `capture_baseline label=reentry_2026_05_03`: status=stored, 3 domains captured (weight/recovery/nutrition)
- ✅ MCP registry test: 7/7 pass
- ✅ IAM secrets test: 4/4 pass

## What I did NOT ship

Per scope discipline (all in WR-47/48 spec for future PRs):

- **WR-48 Enhancement 1 — daily brief banner.** Modifies `daily_brief_lambda.py` to read CloudWatch metrics on every run and prepend a "⚠️ DATA STATUS" block. The IAM fix already restored email alerts so the user-facing surface exists; the daily-brief banner is a nicer-to-have. Recommend ship in next sprint.
- **WR-48 Enhancement 2 — escalation tiers (yellow/orange/red).** Logic exists in the new `get_freshness_status` MCP tool; not yet in the freshness-checker Lambda (still single-threshold).
- **WR-48 Enhancement 3 — Pause Mode awareness.** Gated on WR-47 (Pause Mode) shipping.
- **WR-47 — Pause Mode.** Specced; not built. The whole user-declared-gap state machine.
- **WR-49 — One-Click Manual Backfill UI.** Not yet specced.
- **WR-50 — Re-Entry Day Template.** Gated on WR-47.
- **Backstop alarm sent to a separate email (e.g. partner's).** Spec recommended a partner-email subscription as belt-and-suspenders; I won't subscribe a partner email without explicit instruction. Topic + alarm exist; subscribe whoever you want.

## Carry-forward Matthew action items

In addition to the 8 already in `HANDOVER_v6.8.7.md` (PR 0 smoke, v16.1 backfill, TD-17 iOS, anthropic orphan, Todoist consolidation, TD-19 Phase 2, TD-11 Step 2, FH spec triage):

9. **Approve TD: deprecate the `chronicling` DDB partition.** Habitify took over the format. Either delete old data or formally retire `query_chronicling` in `mcp/helpers.py`.
10. **Decide RSS-while-gated.** If you want RSS public, need to exclude `/rss.xml` from cf-auth. Otherwise current behavior is intentional.
11. **Consider WR-47 Pause Mode** as the next sprint's anchor work — it's the precedent that unlocks both TD-11 (pending vs failed) and WR-50 (Re-Entry Day Template).

## Commits this re-entry session (chronological)

```
TBD docs: PROJECT_PLAN.md WR-47..50 + RUNBOOK_REENTRY.md + WR_47_48 spec rename
TBD PR-reentry: WR-48 SNS:Publish IAM fix + backstop alarm + get_freshness_status MCP + 2 latent-bug fixes
TBD docs: v6.8.8 wrap + CHANGELOG
```

## State snapshot

| Metric | Value |
|--------|-------|
| Version | v6.8.8 |
| Lambda Layer | v42 (unchanged) |
| Lambdas | 66 (unchanged) |
| MCP Tools | **126** (was 125; added get_freshness_status) |
| CloudWatch alarms | +1 (`life-platform-freshness-checker-not-emitting`) |
| New IAM permissions | +1 (`sns:Publish` on `life-platform-alerts` for freshness-checker role) |
| Latent bugs caught + fixed | 2 (health_trajectory tz-mixing, capture_baseline kwargs typing) |
| Memory writes | 5 (3 cycle markers + 1 baseline + 1 re_entry) |
| New runbook | `docs/RUNBOOK_REENTRY.md` |
