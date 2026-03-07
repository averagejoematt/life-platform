# Handover — 2026-03-07 — v2.83.0: Todoist Integration

## What Was Built

Full Todoist integration connecting the Life OS (recently set up in this session) to the platform.

### 1. Enhanced Ingestion Lambda (`lambdas/todoist_lambda.py`)
**New fields captured daily:**
- `overdue_count` — tasks past their due date (via Todoist filter API `overdue`)
- `due_today_count` — tasks due today (via Todoist filter API `today`)
- `priority_breakdown` — `{p1_urgent, p2_high, p3_medium, p4_normal}` counts from active task list
- `tasks_due_today[]` — lightweight list (capped 50) of today's due tasks with project names

New helper `get_filtered_tasks(api_token, filter_str)` — paginated, graceful fallback on failure (returns [] not crash).

### 2. New MCP Module (`mcp/tools_todoist.py`) — 5 tools
| Tool | Description |
|------|-------------|
| `get_task_completion_trend(days=30)` | Daily completion counts + 7d rolling avg + streak + zero-completion days |
| `get_task_load_summary(days=7)` | Snapshot: active/overdue/due-today, load signal (CLEAR/MODERATE/ELEVATED/HIGH), priority breakdown, by-project |
| `get_project_activity(days=30)` | Which life OS projects are getting completions — attention gap detection |
| `get_decision_fatigue_signal(days=30)` | Roadmap #34: Pearson r between task load and T0 habit compliance. Load threshold analysis. |
| `get_todoist_day(date=yesterday)` | Full day snapshot including completed tasks list |

### 3. Registry (`mcp/registry.py`)
- Added `from mcp.tools_todoist import *` import
- Added 5 tool definitions (tools 125-129)
- Total: **129 MCP tools**

### 4. Daily Brief Integration
- **`daily_brief_lambda.py`:** `gather_daily_data()` now fetches `todoist_yesterday = fetch_date("todoist", yesterday)` and includes in return dict as `"todoist"`
- **`html_builder.py`:** New TASK LOAD section (inserted after Blood Pressure, before Weight Phase):
  - 4 metrics: DONE YESTERDAY / OVERDUE / DUE TODAY / ACTIVE
  - Colour-coded LOAD SIGNAL: GREEN (CLEAR ≤5 overdue) / YELLOW (MODERATE) / ORANGE (ELEVATED) / RED (HIGH >30)
  - Top 3 projects by completions yesterday
  - Wrapped in try/except — won't crash brief if todoist data missing

---

## Context: Todoist Session Work

This session also covered a full Life OS review (Todoist setup):
- 4 project files audited (Finance & Admin, Growth & Relationships, Health & Body, Home & Car)
- 6 structural problems identified and fixed by Matthew
- Expert panel review (12 experts) generated 17 new tasks + 1 edit
- Operationalization strategy: ladder method for scheduling all recurring tasks
- Alarm investigation: `daily-metrics-compute-errors` alarm in ALARM state — March 6 error, Lambda running clean on March 7

---

## Deploy Instructions

```bash
bash deploy/deploy_todoist_integration.sh
```

Order: `todoist-data-ingestion` → 10s → `life-platform-mcp` → 10s → `daily-brief`

**Post-deploy verification:**
1. Manually invoke `todoist-data-ingestion` with `{"date": "2026-03-06"}` — check response includes `overdue_tasks` and `due_today` fields
2. Check CloudWatch logs for "Overdue: X, Due today: Y" log line
3. MCP: call `get_task_load_summary` — should return snapshot
4. Daily Brief tomorrow should show TASK LOAD tile

---

## Pending / Next

- **`daily-metrics-compute-errors` alarm** — investigate March 6 error (log stream from that day). Likely transient. Alarm will auto-clear once 24h window rolls past the error.
- **Google Calendar integration** — Board rank #2, North Star gap #2. Demand-side cognitive load data. Next logical step.
- **Monarch Money** — Board rank #14, North Star gap #5. Financial stress as health pillar input.
- **Decision fatigue signal** (#34) — `get_decision_fatigue_signal` is deployed. Will need ~2 weeks of Todoist data with the new fields before meaningful correlation output.

---

## Version
v2.83.0 | 32 Lambdas (unchanged) | 129 MCP tools (+5) | 1 new module (tools_todoist.py = 27th module)
