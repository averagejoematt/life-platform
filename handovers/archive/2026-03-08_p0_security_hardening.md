# Life Platform — Session Handover
**Date:** 2026-03-08
**Version:** v2.92.0
**Session:** P0 Security Hardening

---

## What Was Done This Session

### P0 Security — IAM Role Decomposition (main deliverable)

Built `deploy/p0_iam_role_decomposition.sh` — decomposes the shared `lambda-weekly-digest-role` (used by 10+ Lambdas) into 3 least-privilege roles:

| Role | Lambdas | Permissions |
|------|---------|-------------|
| `life-platform-compute-role` | character-sheet-compute, adaptive-mode-compute, daily-metrics-compute, daily-insight-compute, hypothesis-engine | DDB read+write, S3 config read, ai-keys secret |
| `life-platform-email-role` | daily-brief, nutrition-review, wednesday-chronicle, weekly-plate, monday-compass, anomaly-detector | DDB read-only, SES, S3 dashboard/buddy read+write, ai-keys secret |
| `life-platform-digest-role` | weekly-digest, monthly-digest | DDB read-only, SES, S3 blog+dashboard+buddy read+write, ai-keys secret |

### P0 Quick Wins — Already Done (from prior sessions)
- `deploy/p0_split_secret.sh` already exists — creates `life-platform/ai-keys` with only the Anthropic key; updates `ANTHROPIC_SECRET` env var on all 10 AI Lambdas
- All AI Lambdas (`hypothesis_engine_lambda.py`, `daily_insight_compute_lambda.py`, `anomaly_detector_lambda.py`, `ai_calls.py`) already use `AI_MODEL` / `AI_MODEL_HAIKU` env-var constants — no hardcoded model strings

### Verification Script
Built `deploy/p0_verify.sh` — runs 14 automated checks across secret existence, env vars, and role assignments. Run after executing the P0 scripts to confirm.

---

## Execution Order (run these in terminal)

```bash
cd ~/Documents/Claude/life-platform

# Step 1: Split Anthropic key into dedicated secret (if not already done)
./deploy/p0_split_secret.sh

# Step 2: Decompose IAM roles
./deploy/p0_iam_role_decomposition.sh

# Step 3: Verify
./deploy/p0_verify.sh
```

**After 48h of clean Lambda runs:** Remove `anthropic_api_key` field from `life-platform/api-keys` to fully isolate the credential, then deprecate `lambda-weekly-digest-role`.

---

## P0 Item 3 (SAM) — Future Session

The third P0 item (IaC via AWS SAM) is scoped at 8–12 hours. Start with compute Lambdas since they're the simplest (no SES, no S3 write). Suggest as a dedicated session when you want to tackle infrastructure debt.

---

## Remaining Priorities (from prior sessions)

### Immediate
- **Verify Monday Compass** — first real run Mon 2026-03-09 8:00 AM PT. Check `/aws/lambda/monday-compass` CloudWatch logs.
- **Update `config/project_pillar_map.json`** — verify actual Todoist project names via `list_todoist_projects` MCP tool, then push to S3.

### Next Feature Build (ROI-ranked, no data gating)
1. **#31 Light exposure tracking** (2–3 hr) — Habitify habit + `get_light_exposure_correlation` MCP tool
2. **#16 Grip strength tracking** (2 hr) — $15 dynamometer, Notion log, MCP tool
3. **#2 Google Calendar** (6–8 hr) — North Star gap #2, demand-side cognitive load, needed for IC-4/5/34

### P1 Technical (from expert review)
- Migrate EventBridge rules to EventBridge Scheduler with IANA timezone (4-6hr) — DST-safe
- Add invocation-count alarms for critical Lambdas (2hr)
- Implement exponential backoff in `call_anthropic()` (2-3hr)
- Add token usage tracking from Anthropic API (2-3hr)

---

## Platform State

- **Version:** v2.92.0
- **Lambdas:** 35 | **MCP Tools:** 144 | **Modules:** 30
- **New scripts this session:** `deploy/p0_iam_role_decomposition.sh`, `deploy/p0_verify.sh`
