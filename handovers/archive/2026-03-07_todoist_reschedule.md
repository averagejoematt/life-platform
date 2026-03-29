# Handover — 2026-03-07 — Todoist Life OS Bulk Reschedule + Write Tools

## Version
v2.84.0 (from v2.83.0)

## What Was Done This Session

### 1. Todoist Write Tools (6 new MCP tools, tools 130–135)
Added to `mcp/tools_todoist.py` and registered in `mcp/registry.py`:

| Tool | Description |
|------|-------------|
| `get_todoist_projects()` | List all projects with IDs |
| `list_todoist_tasks(filter_str, limit)` | List active tasks with IDs, due dates, recurrence |
| `update_todoist_task(task_id, ...)` | Update due_string, due_date, content, priority, project |
| `create_todoist_task(content, ...)` | Create new task |
| `close_todoist_task(task_id)` | Mark complete |
| `delete_todoist_task(task_id)` | Permanently delete |

Key: `update_todoist_task` supports `every!` (completion-based) syntax in `due_string`.

**MCP Lambda deployed** (`deploy/deploy_todoist_integration.sh`).

### 2. Bug Fix: Stale `SECRET_NAME` on `todoist-data-ingestion`
Lambda had `SECRET_NAME=life-platform/todoist` hardcoded — old per-service secret deleted during v2.75.0 consolidation. Fixed to `life-platform/api-keys` via:
```bash
aws lambda update-function-configuration \
  --function-name todoist-data-ingestion \
  --environment "Variables={SECRET_NAME=life-platform/api-keys}" \
  --region us-west-2
```
Post-fix ingestion verified: 5 projects found, 7 completed tasks, 200 active tasks saved to S3 + DynamoDB.

### 3. Bulk Rescheduling Script — `patches/todoist_reschedule.py`

All ~292 tasks were imported with today's date during the Life OS setup session. This script rescheduled them properly.

**Usage:**
```bash
python3 patches/todoist_reschedule.py          # dry run
python3 patches/todoist_reschedule.py --apply  # commit
```

Token: reads from Secrets Manager `life-platform/api-keys` (`todoist_api_token`) or `TODOIST_TOKEN` env var.

**Core rules applied:**
1. **Completion-based recurrence:** All recurring tasks → `every!` (reschedules from completion, never piles up). EXCEPTION: hard-date tasks (birthdays, anniversaries, holidays, Christmas, etc.) keep date-anchored `every`.
2. **Smart first-fire scatter** — see logic below.
3. **Open items** (one-time tasks): spread Mon–Thu across Mar 9 – May 31, ~4/week by domain sequence.

**Scatter logic by cadence:**

| Cadence | Strategy |
|---------|----------|
| Weekly | Spread across 4 onboarding weeks (Finance+Health start Mar 8, Growth Mar 15, Home Mar 22). Day of week: Mon=Finance, Wed=Health, Thu=Growth, Sat=Home, Sun=Review tasks |
| Bi-weekly | Same day-of-week logic, each domain starts 1 week apart (Finance Mar 8, Health Mar 15, Growth Mar 22, Home Mar 29). Each subsequent task in a domain gets +2 weeks |
| Monthly | Staggered start months: Finance starts March (week 1), Health April (week 2), Growth April (week 3), Home May (week 4). Mon–Fri spread within week by counter; overflow to next month after 5 tasks |
| Quarterly | Q2: Finance → April (week 1), Health → May (week 1), Growth → June (week 1), Home → April (week 2) |
| Semi-annual | Two waves: Finance/Health/Growth in Apr/May/Jun + Oct/Nov/Dec |
| Annual | Keyword-to-month (tax=Jan, dental=Apr, eye=Jul, etc.) + week-within-month by domain. Defer tasks (DEXA, cognitive baseline, hearing test) → Aug–Dec explicitly |

**Domain sequencing everywhere:** Finance → Health → Growth → Home (most foundational first).

**Distribution achieved:** Smooth spread from Mar–Dec rather than 62 tasks all in March.

## Files Changed
- `mcp/tools_todoist.py` — 6 write tools added
- `mcp/registry.py` — tools 130–135 registered
- `patches/todoist_reschedule.py` — new bulk rescheduler
- `docs/CHANGELOG.md` — v2.84.0 entry added
- `docs/PROJECT_PLAN.md` — version + tool count updated

## Pending Items (carried forward)

- **[PENDING] daily-metrics-compute-errors alarm** — March 6 error likely caused by todoist stale-secret cascade; should self-clear now that ingestion is fixed. Verify in CloudWatch.
- **[PENDING] Stale SECRET_NAME audit** — same latent risk may exist in other Lambdas. Worth a sweep of all Lambda env vars to confirm all use `life-platform/api-keys`.
- **[PENDING] Decision fatigue signal (#34)** — deployed, needs ~2 weeks of new-format Todoist data (post-reschedule) before meaningful correlation output
- **[PENDING] Google Calendar integration** — Board rank #2, next major integration after Todoist is stable
- **[PENDING] Monarch Money** — Board rank #14
- **[PENDING] Brittany weekly accountability email** — next major feature, prerequisite: reward seeding
- **[PENDING] Reward seeding** — prerequisite for Character Sheet Phase 4
- **[PENDING] BRITTANY_EMAIL env var** — Lambda deployed with placeholder

## Platform State
- **Version:** v2.84.0
- **Tools:** 135 across 27 modules
- **Lambdas:** 32
- **Data sources:** 19
