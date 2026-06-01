# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Documentation Index

Deep documentation lives in `docs/`. Start here when context is needed:
- `docs/ONBOARDING.md` — first-day mental model, key concepts
- `docs/QUICKSTART.md` — first-day commands (AWS auth, deploy, rollback)
- `docs/ARCHITECTURE.md` — full system design, 80 Lambdas (us-west-2) + 5 (us-east-1), 8 CDK stacks, data flows (updated v8.1.0)
- `docs/SCHEMA.md` — DynamoDB field reference (authoritative)
- `docs/RUNBOOK.md` — daily operations, troubleshooting
- `docs/DECISIONS.md` — ADRs (ADR-001 through ADR-069), why things are the way they are
- `docs/REMEDIATION_TAXONOMY.md` — classifier rubric for the self-healing agent (auto-fix-safe / fix-via-pr / needs-human / stale)
- `docs/DATA_GOVERNANCE.md` — PII classification + retention policy (added v7.2.0)
- `docs/BOARDS.md` — the three AI persona boards (Personal, Technical, Product)
- `docs/REVIEW_METHODOLOGY.md` — how to run architecture audits
- `docs/V2_AUDIT_PLAN.md` — V2 audit plan + outcomes (2026-05-17)

## Commands

```bash
# Run all tests + linters
python3 -m pytest tests/ -v

# Run a single test file
python3 -m pytest tests/test_shared_modules.py -v

# Lint
flake8 lambdas/ mcp/

# Syntax check all Python
find lambdas/ mcp/ -name '*.py' -exec python3 -m py_compile {} \;

# Deploy a single Lambda
bash deploy/deploy_lambda.sh <function-name>

# Deploy + run smoke test
bash deploy/deploy_and_verify.sh <function-name>

# CDK deploy all stacks
cd cdk && npx cdk deploy --all

# Start MCP bridge for Claude Desktop
python3 mcp_bridge.py
```

## Architecture Overview

**Ingest → Store → Serve** pipeline on AWS (us-west-2):

1. **Ingest**: 15 scheduled ingestion Lambda functions pull from APIs on EventBridge (8 SIMP-2 framework + 7 pattern-exempt per ADR-056/060; hourly 4am–10pm PST, except Garmin at 4x daily due to OAuth rate limits, Weather + Todoist at 2x daily, Hevy at hourly 12-23 UTC). Plus 1 webhook-driven FunctionURL Lambda (`hevy-webhook`, currently parked since Hevy doesn't publish webhooks). Gap-aware backfill — each ingestion Lambda detects missing `DATE#` records (including today) and only fetches what's absent. HAE webhook sources (CGM, water, BP, State of Mind) are near-real-time with reading-level dedup for cumulative fields.

2. **Store**: Raw JSON in S3 (`raw/{source}/{datatype}/{YYYY}/{MM}/{DD}.json`), normalized metrics in DynamoDB single-table (`life-platform`, PK `USER#matthew#SOURCE#{source}`, SK `DATE#{YYYY-MM-DD}`).

3. **Serve/Compute**:
   - **MCP Lambda** — 138 tools across 27 domain modules (`mcp/tools_*.py`, including `tools_hevy.py` added 2026-05-25 per ADR-060), accessed via Claude Desktop and claude.ai. `grep -c '"name":' mcp/registry.py` is source of truth. **Note (V2 P4.1):** only ~11 tools used in last 30 days per EMF telemetry; bulk pruning planned.
   - **Compute Lambdas** (5) — run before 11 AM daily: `character-sheet`, `adaptive-mode`, `daily-metrics-compute`, `daily-insight-compute`, `hypothesis-engine`; store pre-computed results to DynamoDB
   - **Email Lambdas** (7) — daily brief at 11 AM reads pre-computed results
   - **OG Image Lambda** — generates 6 data-driven PNG share cards daily at 11:30 AM PT using Pillow
   - **Site API Lambda** (us-west-2, read-only) — serves averagejoematt.com with 60+ endpoints including `/api/vitals`, `/api/labs`, `/api/changes-since`, `/api/observatory_week`

## Key Technical Conventions

**No external HTTP libraries** — all API calls use Python's `urllib.request` stdlib. No `requests`, no `httpx`. **Exception (ADR-062):** Claude inference goes through AWS Bedrock via `boto3 bedrock-runtime` (`lambdas/bedrock_client.py`), not urllib — Bedrock has no plain-HTTP endpoint and uses SigV4/IAM auth. All other HTTP (Whoop, Withings, Garmin, etc.) stays on urllib.

**Decimal for DynamoDB** — boto3 rejects Python `float`; cast to `Decimal` before writing.

**Single-table DynamoDB** — no GSIs; all access via composite key. Don't add GSIs without an ADR.

**Secrets Manager only** — all credentials at `life-platform/` prefix. Never `.env` files or hardcoded values.

**S3 safety (ADR-032/033/046)** — never `aws s3 sync --delete` to bucket root. Use `deploy/lib/safe_sync.sh` wrapper. Bucket policy blocks `DeleteObject` on `raw/*`, `config/*`, `uploads/*`, `generated/*` for `matthew-admin`.

**S3 prefix separation (ADR-046)** — Lambda-generated files (public_stats.json, character_stats.json, OG images, journal posts) live in `generated/` prefix, NOT `site/`. CloudFront routes generated-file URLs to S3GeneratedOrigin. This makes `aws s3 sync site/ --delete` structurally safe — it cannot touch generated content.

**Site API is primarily read-only** — the site-api Lambda reads from DynamoDB/S3 for all data endpoints. Limited writes exist for interactive features only: experiment/challenge votes, follows, checkins, experiment suggestions, and user-submitted findings (S3). Core data queries must never write.

**Rate limiting is in-memory** — `ask` (5 anon/20 subscriber per hour), `board_ask` (5 per IP per hour). Vote/follow rate limits use DynamoDB atomic counters with TTL.

**EventBridge crons use fixed UTC** — no DST drift. All schedules in `cdk/stacks/` must be UTC-fixed.

**Lambda Layer** — shared modules (`ai_calls.py`, `retry_utils.py`, `bedrock_client.py`, `budget_guard.py`, `board_loader.py`, `output_writers.py`, `scoring_engine.py`, `secret_cache.py`, `site_writer.py`, `character_engine.py`, `intelligence_common.py`, `auth_breaker.py`, `compute_metadata.py`, `http_retry.py`, `numeric.py`, `platform_logger.py`, `rate_limiter.py`, `request_validator.py`, + others) are deployed as a layer (currently **v62**, mirrored in `cdk/stacks/constants.py:SHARED_LAYER_VERSION`). Note: `email_framework.py` was deleted in V2 (replaced inline). Changes here require a layer rebuild (`bash deploy/build_layer.sh`) before deploying dependent functions. Source of truth: `aws lambda list-layer-versions --layer-name life-platform-shared-utils --query 'LayerVersions[0].Version'`.

**Prompt caching (COST-OPT-2)** — `ai_calls.py` and `retry_utils.py` auto-wrap system messages as Anthropic cached content blocks (90% discount). Model tiering: structured tasks use Haiku, narrative content uses Sonnet. All model assignments configurable via `AI_MODEL` env var. See ADR-049.

**Secret caching (COST-OPT-1)** — Lambdas cache Secrets Manager reads for 15 minutes via `secret_cache.py` in the shared layer. Reduces Secrets Manager API calls ~90%.

**Flake8 config** — max 140 chars, ignores E501, W503, E402, E741. See `.flake8`.

## MCP Tool Modules

Tools in `mcp/` are split by domain: `tools_sleep.py`, `tools_health.py`, `tools_training.py`, `tools_nutrition.py`, `tools_cgm.py`, `tools_labs.py`, `tools_journal.py`, `tools_correlation.py`, `tools_character.py`, `tools_board.py`, `tools_lifestyle.py`, `tools_strength.py`, plus shared helpers in `handler.py`, `config.py`, `core.py`, `helpers.py`, `utils.py`, `registry.py`.

The tool registry in `mcp/registry.py` wires all tools. `tests/test_wiring_coverage.py` enforces that every tool is registered — run this after adding new tools.

## CDK Structure

8 stacks in `cdk/stacks/`: `ingestion`, `core`, `email`, `compute`, `mcp`, `operational`, `web`, `monitoring`. Entry point: `cdk/app.py`. Each stack creates its own IAM roles (least-privilege, one role per Lambda).

## CI/CD

GitHub Actions (`.github/workflows/ci-cd.yml`): Lint → Test → Plan → Deploy (requires manual approval via GitHub Environment: `production`) → Smoke Test → Auto-rollback if smoke fails. Auth via OIDC federation (no long-lived AWS keys).

## AI Inference (Bedrock + Budget Guard)

**Single chokepoint:** all Claude calls route through `lambdas/bedrock_client.invoke()` (ADR-062). Auth is IAM (`bedrock:InvokeModel` + `InvokeModelWithResponseStream`), no API key. Cross-region inference profiles required: `us.anthropic.claude-sonnet-4-6` (narrative) and `us.anthropic.claude-haiku-4-5-20251001-v1:0` (structured). Prompt caching uses `cache_control` blocks on the system message (~2048+ tokens to engage).

**$75/month hard ceiling** (ADR-063): one AWS budget `life-platform-monthly-75` covers ALL spend. `cost_governor_lambda` (hourly) projects month-end spend (non-AI from Cost Explorer + Bedrock token usage × current price) and writes a tier 0–3 to SSM `/life-platform/budget-tier`. `lambdas/budget_guard.py` (layer module) gates AI features by tier:
- **0** (<70%): all AI runs normally.
- **1** (70–85%): coach narratives + ensemble paused.
- **2** (85–95%): website AI (`/api/ask`, `/api/board_ask`) returns a friendly "paused" response.
- **3** (≥95%): hard cutoff — even daily brief skips AI; `bedrock_client.invoke()` raises `BudgetExceeded`.

Daily brief is "protect longest" by design. Manual reset for testing: `aws ssm put-parameter --name /life-platform/budget-tier --value 0 --type String --overwrite`.

## Self-healing Remediation Agent (ADR-064/065)

Scheduled GitHub Actions workflow (`.github/workflows/remediation-agent.yml`, ~07:45 PT daily) triages CloudWatch alarms, failed CI runs, DLQ depth, QA-smoke results — auto-fixes the safe class, opens PRs for the rest, reports needs-human items in one curated email.

**Auth:** AWS OIDC → `github-actions-remediation-role` (Bedrock + read-only diagnosis + scoped audit-log writes, NO deploy/IAM mutate). Model: Sonnet 4.6 on Bedrock — no Anthropic key.

**Kill-switch:** SSM `/life-platform/remediation-mode` = `off | shadow | auto`. Tier-3 budget also no-ops the run.

**Auto-merge is a deterministic gate, not the agent** (ADR-065). The agent (read-only role) opens `auto-fix-safe` PRs; `remediation/automerge.py` runs after and merges only if ALL hold: every file on a narrow ALLOWLIST (role_policies, lambda_map, monitoring_stack, freshness_checker, qa_smoke, tests/), no file on the DENYLIST (bedrock_client, budget_guard, auth/secrets, deploy/, workflows/, core_stack), diff ≤ 60 lines, lint + offline unit-test subset pass, daily cap (3) not reached. **CI's production approval gate stays intact** — auto-merge does NOT auto-deploy. Infra merges that touch `cdk/` are flagged "needs cdk deploy."

**Audit log:** every gate decision → `s3://matthew-life-platform/remediation-log/automerge/`. Classifier rubric: `docs/REMEDIATION_TAXONOMY.md`.

## Experiment Restart Pipeline (ADR-058/059)

Experiment is anchored by `EXPERIMENT_START_DATE` in `lambdas/constants.py` (currently **2026-05-30**, baseline 304.62 lbs). Re-anchoring is one idempotent command:

```bash
python3 deploy/restart_pipeline.py --genesis YYYY-MM-DD --apply
# Override Withings baseline when the genesis date has no weigh-in yet:
python3 deploy/restart_pipeline.py --genesis YYYY-MM-DD --override-weight-lbs <weight> --apply
```

Regenerates constants, bumps the layer, deploys Core/Compute/Email, phase-tags DDB, wipes intelligence, rebuilds character, syncs site + docs, verifies 27 rendered pages. Rollback: `deploy/restart_rollback.py`.

---

**Verified:** 2026-05-29 (v8.2.0 — Bedrock + budget guard + remediation agent + auto-merge gate)
