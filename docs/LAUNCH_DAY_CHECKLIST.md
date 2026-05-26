# Launch Day Checklist — 2026-05-25

The launchd watchdog (`~/Library/LaunchAgents/com.matthew.lifeplatform.may25-pivot.plist`) fires at **07:05 PT Monday 2026-05-25** and runs `deploy/restart_pivot_when_ready.py` → `deploy/restart_pipeline.py --genesis 2026-05-25 --apply` once Withings has posted today's reading.

## Before the watchdog fires (Sunday night / Monday before 7 AM)

- [ ] Step on the Withings scale before bed Sunday OR first thing Monday. Pipeline aborts cleanly if no reading is present — but you want one for genesis day.

## After the watchdog fires (Monday morning, 7:05–8:00 AM PT)

You'll get a `🟢 Pipeline complete` line in the launchd log if it succeeds. Then:

1. **Verify the pivot landed** — run from project root:
   ```bash
   python3 deploy/restart_verify.py            # 12-check backend probe
   python3 deploy/restart_verify_rendered.py   # 27-page rendered probe
   ```
   - Expect **12/12** backend (last night's pre-launch run was 9/12; the 3 failures all clear post-pivot).
   - Expect **27/27** pages clean (last night ended at 27/27 already).

2. **Spot-check the homepage** in a browser:
   - `https://averagejoematt.com/` should show `Day 1`, `297 lbs`, `Level 1 (Foundation)`.
   - `/api/journey` should return `started_date: "2026-05-25"` and `current_weight_lbs: ~297`.

3. **The 11 AM PT daily-brief is the real proof.** You'll receive a single `Morning Brief | Mon May 25 | Grade: X` email. If you get 2+, something looped — check `aws lambda list-event-source-mappings` and the EventBridge rule.

## Things that need your manual attention this week

- **Re-authenticate Garmin.** Garmin's OAuth refresh endpoint is rate-limiting us (HTTP 429) on every scheduled invocation. Until you re-auth, no Garmin data flows.
  ```bash
  # 1. Log into Garmin Connect on garmin.com
  # 2. Generate fresh OAuth credentials (developer portal)
  # 3. Update the secret:
  aws secretsmanager put-secret-value \
    --secret-id life-platform/garmin --region us-west-2 \
    --secret-string '{"email":"…","password":"…"}'
  ```
  See `lambdas/garmin_lambda.py:228` for the refresh path. The Lambda will pick up the new creds on its next scheduled invocation (hourly).

- **Start journaling in Notion.** The JOURNAL_COACH validator currently blocks every daily-brief journal section as "empty output" because there are no entries. Once you start writing entries, the validator will accept the coach output.

- **Log meals in MacroFactor.** Last logged date is 2026-04-11 (44 days ago). MacroFactor source will stay flagged stale until you resume tracking.

## What's quiet that should stay quiet

Tonight I:
- Routed **all 43 noisy alarms** to the digest topic (one batched email per day instead of immediate ping per alarm flip).
- Added a **2-consecutive-fail buffer** on the canary so transient blips don't email.
- Fixed the **canary subscribe bouncing** issue (`canary+TS@mattsusername.com` no longer triggers a confirmation email that bounces).
- Cleaned up **76 untagged DDB records** via `restart_phase_tag.py --apply`.
- Re-attached the **shared layer** to `life-platform-site-api`, `life-platform-site-api-ai`, and `site-stats-refresh` (was running `Layers: null`).
- Removed the **orphan S3 KMS grants** from 26 IAM policies (key is in PendingDeletion until 2026-06-16).

Expected emails per day:
- 1× Morning Brief (11:00 PT)
- 1× Daily alerts digest (8:00 PT — silent on healthy days, but consolidates anything noisy)
- 1× Wednesday Chronicle (Wednesdays only)

## If something goes wrong

- **Symptom: site shows pre-genesis data after the pivot.** Run `deploy/OPERATIONAL_RUNBOOK.md` § "Something looks wrong on the public site".
- **Symptom: daily-brief doesn't send at 11 AM.** Check `/aws/lambda/daily-brief` logs; rollback via `bash deploy/rollback_lambda.sh daily-brief` if the latest deploy is implicated.
- **Symptom: any other regression.** `python3 deploy/restart_rollback.py --to-genesis 2026-04-01 --apply` reverts the entire pipeline.

## What's tracked for post-launch

See `docs/BACKLOG.md` § "2026-05-25 launch-eve bug sweep" for the full list. Key items:
- ~~P1.1: split `site_api_lambda.py` (7,898 lines)~~ ✅ **DONE 2026-05-26** — 7,949 → 1,216 lines (85% reduction) across 7 sibling modules in `lambdas/web/`. See ARCHITECTURE.md "Site API Lambda" section.
- ~~P3.1: `lambdas/` package restructure~~ ✅ **DONE 2026-05-26** — 73 handler files moved into 7 subpackages (ingestion/, compute/, coach/, emails/, web/, operational/, intelligence/). Note: `email/` was renamed to `emails/` after a P0 incident — the original name shadowed Python's stdlib `email` package and broke every Lambda. See commits 0d566b0 + eecc44c + ADR follow-up.
- P3.2: coach loop validation — gated on 30 days of post-restart data (2026-06-20)
- Phase-filter sweep — was 245 remaining callsites; batch 1 (4 site-api callsites) wrapped 2026-05-26. ~241 remaining, mostly mcp/tools + email Lambdas + 192 unclear sites that need per-callsite judgment. Risk is low because DDB-level phase tags already exclude pilot data.
- Lighthouse-CI advisory in GitHub Actions — flagged, not wired yet
