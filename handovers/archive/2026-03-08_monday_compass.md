# Life Platform — Handover
**v2.91.0 | 2026-03-08**

## What Was Built This Session

### Monday Compass — Weekly Planning Email (v2.91.0)

**New Lambda:** `lambdas/monday_compass_lambda.py`
**New config:** `config/project_pillar_map.json`
**Deploy script:** `deploy/deploy_monday_compass.sh`

**What it does:** A forward-looking Monday 7 AM email that answers "what matters most this week and why" — the first email on the platform to connect health state to task load. Bridges the demand-side gap that all other emails ignore.

**6 sections:**
1. 🌅 State of the Week — recovery, HRV, Character Sheet tier, last week grade
2. 📋 On Deck This Week — tasks due this week grouped by pillar (project→pillar mapping via S3 config)
3. 🎯 Prioritization Intelligence — AI cross-pillar reasoning (health state × task load × pillar gaps)
4. 🗂️ The Overdue Pile — commit/defer/delete framing; cognitive debt reduction
5. 💡 Board Pro Tips — 3 context-selected Board members (always Rodriguez; +2 based on weakest pillar, recovery, overdue count)
6. 🔑 This Week's Keystone — single highest-leverage action of the week

**Technical notes:**
- Todoist: live API calls at send time (`due before: next Sunday` + `overdue` filters, both paginated)
- Project→pillar mapping: `s3://matthew-life-platform/config/project_pillar_map.json` — edit to match actual Todoist project names; file is in `config/` in the repo
- Board: always includes `rodriguez` (planning/willpower domain); second member keyed to weakest Character Sheet pillar; third member from recovery or overdue logic
- AI: `claude-sonnet-4-6`, temperature 0.4, max_tokens 3500, ~$0.05/week
- IC-15: persists to insights ledger post-send; IC-16: reads recent insights as context
- Schedule: Monday 15:00 UTC = 7:00 AM PT
- CloudWatch alarm: `monday-compass-errors`

## Deploy Steps (NOT YET DEPLOYED)

```bash
# From project root:
chmod +x deploy/deploy_monday_compass.sh
./deploy/deploy_monday_compass.sh
```

The script: creates Lambda (if needed), deploys code + board_loader + insight_writer, uploads S3 config, creates EventBridge rule, creates CloudWatch alarm, runs smoke test (sends real email).

**After deploy — important:**
1. Check inbox for the test email
2. Open `config/project_pillar_map.json`, update project names to match your actual Todoist project structure (run `list_todoist_tasks` via MCP or check Todoist web to see exact names)
3. Re-upload: `aws s3 cp config/project_pillar_map.json s3://matthew-life-platform/config/project_pillar_map.json`

## Platform State

- **Version:** v2.91.0
- **Lambdas:** 35 (was 34)
- **Emails/digests:** 6 (Daily Brief, Weekly Digest, Monthly Digest, Wednesday Chronicle, Weekly Plate, Monday Compass)
- **IC features built:** 14 of 30

## Current Email Schedule

| Email | Day | Time PT |
|-------|-----|---------|
| Daily Brief | Every day | ~6:00 AM |
| Monday Compass | Monday | 7:00 AM |
| Wednesday Chronicle | Wednesday | 6:00 AM |
| Weekly Plate | Friday | 6:00 PM |
| Weekly Digest | Sunday | 6:00 AM |
| Monthly Digest | 1st of month | 6:00 AM |

## Pending / Open

### Immediate
- [ ] Run `./deploy/deploy_monday_compass.sh`
- [ ] Update `config/project_pillar_map.json` with actual Todoist project names
- [ ] Verify test email looks good; adjust AI prompt sections if needed

### Next features (ranked by ROI, no data gating)
1. **#31 Light exposure tracking** — Habitify habit + MCP correlation tool (2–3 hr)
2. **#16 Grip strength tracking** — $15 dynamometer + Notion log + MCP tool (2 hr)
3. **#2 Google Calendar** — North Star gap #2, demand-side context for all pillars (6–8 hr)
4. **#1 Monarch Money** — setup script exists at `setup/setup_monarch_auth.py` (4–6 hr)

### Data-gated watch dates
- ~April 18: IC-4 failure patterns + IC-5 momentum warning become buildable
- ~May: IC-26 temporal mining + IC-27 multi-resolution handoff

## Known Issues / Notes

- The `_group_tasks_by_pillar` function does exact match first, then partial — if Todoist project names don't match the config, tasks fall to `general` pillar. Fix by editing `config/project_pillar_map.json`.
- Whoop recovery pulled for today (Monday); may be empty early Monday if Whoop hasn't synced yet. Lambda degrades gracefully — shows "—" in header and omits from prompt.
- The filter `"due before: next Sunday"` in Todoist's API includes today through end of Saturday (the "next Sunday" is the coming Sunday boundary). This is the correct behavior for a Monday-through-Sunday week view.
