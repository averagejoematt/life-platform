# AJM Re-Entry — Session Handoff to Cowork
**Date:** Sat May 2, 2026, ~6:15pm PDT
**Handoff from:** claude.ai web (Opus 4.7), no project, no repo access
**Handoff to:** Cowork session with `/Users/matthewwalker/Documents/Claude/life-platform/` filesystem access

---

## Situation (one paragraph)

Matthew did a house move in mid-March 2026 and effectively went silent on the AJM platform and his P40 framework for ~4 weeks (April 2 → May 1). One journal entry exists from April 1 ("Day 1") and nothing since. Most of the platform is still standing — Whoop, Eight Sleep, weather, Todoist, Apple Health webhook are flowing — but several OAuth-based integrations have died silently during the gap (known issue BUG-005 from Feb 22 docs: ingestion Lambdas don't auto-refresh tokens). New Function Health labs are pending upload. Today we built a 75-step weekend re-entry plan and started executing Phase 1 (connector sweep). Got blocked on Withings re-auth and the user is moving to Cowork so the new Claude can read the actual repo and debug the auth script directly.

The full re-entry plan is at `/Users/matthewwalker/Documents/Claude/life-platform/` — was generated as a markdown + PDF earlier today. If not saved there yet, the user has it as `ajm_reentry_plan.pdf` from the claude.ai web session.

---

## Phase 1 progress (checklist items 5-16)

- [x] **5. Whoop** — verified flowing on AJM side. Today's strain record present (5/3 partition).
- [x] **6. Eight Sleep** — verified, last night's sleep is in (sleep_start 12:52am PDT 5/2, sleep_end 7:37am PDT 5/2). Quality: 80 score, 6.68 hrs, REM 35.3% (excellent), Deep 17.5% (slightly low), HRV 28.7 (well below 30d avg of 44.5 — body still processing move stress).
- [ ] **7. Withings** — IN PROGRESS, BLOCKED. See "Active Blocker" below.
- [ ] 8. Strava — not started. Almost certainly hit by same BUG-005 OAuth issue.
- [ ] 9. MacroFactor — not started.
- [ ] 10. Garmin — not started. 27d gap, biggest on platform.
- [ ] 11. Habitify — verified live but at 0% completion (no habits logged).
- [ ] 12. Todoist — verified flowing. 278 overdue tasks parked for Sunday triage.
- [ ] 13. HAE pipeline — confirmed broken (`dropbox_poll: null`).
- [ ] 14. Notion journal pipeline — alive, just nothing to ingest.
- [ ] 15. Function Health — new draws downloaded, pending upload.
- [ ] 16. Verify all sources — gating step at end of Phase 1.

---

## Active blocker — Withings auth

User ran `setup/withings_auth.py` from the life-platform repo. Output:

```
Reading credentials from Secrets Manager...
Fetching nonce...
Got nonce: 0542ad04ec88b593606d1f8fd00a4190d78aa845
Exchanging authorization code for tokens...
Traceback (most recent call last):
  File "withings_auth.py", line 112, in <module>
    main()
  File "withings_auth.py", line 100, in main
    token_body = request_token(client_id, client_secret, nonce)
  File "withings_auth.py", line 70, in request_token
    raise RuntimeError(f"requesttoken failed: {resp}")
RuntimeError: requesttoken failed: {'status': 503, 'body': {}, 'error': 'Invalid Params: invalid code'}
```

**Hypothesis (unverified — need repo access):** The script is using the authorization-code OAuth flow but isn't actually obtaining a fresh code. The error "invalid code" from Withings typically means the code is missing, expired, reused, or never generated. Possibilities:
1. Script expects a code from a CLI arg / env var / stdin and is running without it
2. Script is using a stored code that expired (Withings codes expire in ~30s)
3. Script is reusing a code that was already exchanged once
4. Script is missing the user-interaction step (browser visit + paste code)

**First action in Cowork:** read `setup/withings_auth.py` and identify the actual flow. Then either fix the script or run the right flow. Withings has rate limits on auth attempts — don't blind-retry.

**The broader pattern (BUG-005):** Whoop, Withings, and Strava all use OAuth2 in their ingestion Lambdas. None of them auto-refresh tokens. The ingestion Lambdas 401 silently and skip the day. Strava (14d gap) and likely MacroFactor are going to need the same kind of re-auth. Garmin (27d gap) is a different auth model — investigate separately.

---

## Architecture context (from Feb 22 2026 docs, surfaced via past chat search)

- **Repo location:** `/Users/matthewwalker/Documents/Claude/life-platform/`
- **Auth scripts location:** `setup/` subdirectory
- **Withings is polling-based, not webhook-based.** Lambda `withings-data-ingestion` runs on cron `30 14 * * ? *` (14:30 UTC daily). Last successful run dated 2026-04-27.
- **Secrets:** AWS Secrets Manager. Withings token in `life-platform/withings`. Region us-west-2.
- **Memory:** Lambda right-sized to 512 MB after Feb 22 work (peak observed 155 MB; previous 1792 MB). Originally said 768MB elsewhere — verify.
- **Known bug BUG-005 (Feb 22):** "OAuth tokens require manual refresh — Whoop, Withings, and Strava use OAuth2 with refresh tokens. The ingestion Lambdas do not automatically refresh expired access tokens — they fail with 401 and require a human to run the auth script locally."
- **Other architecture nuggets** (read past convo for full doc): Lambda code in AWS only, no git remote at time of Feb 22 audit (BUG-001) — verify if still true.

---

## Tech debt running log (Sat 5/2)

| # | Item | Severity | Phase to fix |
|---|---|---|---|
| TD-1 | `list_protocols` MCP timeout (4+ min) | Med | Phase 8 |
| TD-2 | `get_field_notes` MCP timeout (4+ min) | Med | Phase 8 |
| TD-3 | Whoop & Eight Sleep date partition mismatch — Whoop dates by wake-date, Eight Sleep dates by UTC-midnight ingest-date. Same biological event, two different `sk` labels. Will silently break cross-source sleep correlation. | High | Phase 8 |
| TD-4 | All sleep sources use UTC midnight for `sk` date partition — Seattle 5pm-midnight events get dated to tomorrow. | High | Phase 8 |
| TD-5 | `dropbox_poll: null` — pipeline broken or never ran | Med | Phase 8 |
| TD-6 | `health_auto_export: null` — HAE pipeline broken | Med | Phase 2 (manual workaround) + Phase 8 (real fix) |
| TD-7 | `chronicling` internal table stale since 2025-11-09 — either deprecated artifact or silently broken | Low | Phase 8 |
| TD-8 | Withings OAuth token expired (instance of known BUG-005) | High | Active blocker — being worked now in Cowork |
| TD-9 | **Architectural:** OAuth auto-refresh missing on Whoop/Withings/Strava ingestion Lambdas (BUG-005, Feb 22 docs). Every 4+ week gap will repeat this exact failure across 3 sources. **Promote to WR-39, build in Sprint 7.** | Critical (architectural) | Sprint 7 |
| TD-10 | Process: AJM work like this should happen inside the dedicated AJM claude.ai Project OR in Claude Code/Cowork. The web-only thread without project knowledge or filesystem access is flying blind on repo specifics. | Process | Going forward |

---

## Net-new product/architecture recommendations (queued for PROJECT_PLAN.md)

These were generated during today's planning session and should be added to the WR backlog:

- **WR-35: "Pause Mode"** — explicit user-declared gap. Suppresses scoring, posts site banner, freezes streak punishment, marks data as gap-period in DDB. Trigger: user runs `pause_mode start` or similar.
- **WR-36: Stale-Source Alerts** — daily Lambda that checks last sync per source; if any > 48h stale, push notification or daily-brief alert. **Single highest-ROI feature for preventing this exact situation.** Build this sprint if possible.
- **WR-37: One-Click Manual Backfill UI** — admin page with "force re-sync" buttons per source.
- **WR-38: Re-Entry Day Template** — when Pause Mode ends, auto-load the re-entry checklist as an active challenge.
- **WR-39: OAuth Token Auto-Refresh** — fix BUG-005. Add token-refresh logic to Whoop, Withings, Strava ingestion Lambdas. On 401, attempt refresh using stored refresh_token, update secret, retry. One sprint, three sources fixed forever.

---

## Decisions already made (for context)

- **Don't reset data on May 4.** Preserve the gap. The gap IS the story; AJM's value is honest tracking.
- **Don't delete the April 1 "Day 1" journal entry.** It's the only entry and it's honest.
- **Frame the gap publicly** with a short "On Coming Back" post on averagejoematt.com — one paragraph, dated May 2.
- **Mark a Cycle 2 boundary** in platform_memory: `Cycle 1: Launch (Apr 1)` → `Gap: Move (Apr 2 – May 1)` → `Cycle 2: Re-Entry (May 2 →)`.
- **Soft re-launch Monday May 4** — narrative beat, not a data reset.
- **Tonight's re-entry journal entry is non-negotiable** (Phase 5 of the plan).

---

## Hand-off instructions for the new Cowork Claude

1. Read `setup/withings_auth.py` first thing. Diagnose what flow it implements and why it failed with "invalid code." Don't blind-retry.
2. After fixing Withings, anticipate the same OAuth issue on **Strava** (item 8) and possibly MacroFactor (item 9). Read those auth scripts before running.
3. **Garmin (item 10) is the 27d gap and likely uses a different auth model** (Garmin Connect IQ / OAuth1 historically) — handle separately.
4. Continue tracking tech debt in the running log above. Update items as discovered.
5. The user's North Star: by Monday 6am every source flows or has a known workaround, the new FH labs are loaded, the re-entry journal entry is written, and the daily_brief Lambda fires Cycle 2 Day 1.
6. Phase 1-3 (Saturday work) is highest priority. Phase 8 (Sunday tech debt — including TD-1 through TD-7) is the deeper code work. Phase 5 (re-entry journal entry) is non-negotiable Saturday.

---

## Things the user mentioned but I haven't dug into

- User typed `ls /Users/matthewwalker/Documents/Claude/life-platform/datadrops/functionhealth_drop` earlier — looks like the FH lab files are staged there or expected to be. Phase 3 will load these.
- User has `python@3.14` via Homebrew on Mac.
- Repo path confirmed: `/Users/matthewwalker/Documents/Claude/life-platform/`.

---

## What I'd do first in Cowork

```bash
cd /Users/matthewwalker/Documents/Claude/life-platform
cat setup/withings_auth.py
```

Then read it, identify the auth flow, fix the issue, finish item 7. Then look at `setup/strava_auth.py` (or similar) before running it for item 8 — anticipate the same class of bug.
