# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Documentation Index

Deep documentation lives in `docs/`. Start here when context is needed:
- `docs/ONBOARDING.md` — first-day mental model, key concepts
- `docs/QUICKSTART.md` — first-day commands (AWS auth, deploy, rollback)
- `docs/ARCHITECTURE.md` — full system design, 80 Lambdas (us-west-2) + 5 (us-east-1), 8 CDK stacks, data flows (updated v8.1.0)
- `docs/SCHEMA.md` — DynamoDB field reference (authoritative)
- `docs/RUNBOOK.md` — daily operations, troubleshooting
- `docs/DECISIONS.md` — ADRs (ADR-001 through ADR-057), why things are the way they are
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

**No external HTTP libraries** — all API calls use Python's `urllib.request` stdlib. No `requests`, no `httpx`.

**Decimal for DynamoDB** — boto3 rejects Python `float`; cast to `Decimal` before writing.

**Single-table DynamoDB** — no GSIs; all access via composite key. Don't add GSIs without an ADR.

**Secrets Manager only** — all credentials at `life-platform/` prefix. Never `.env` files or hardcoded values.

**S3 safety (ADR-032/033/046)** — never `aws s3 sync --delete` to bucket root. Use `deploy/lib/safe_sync.sh` wrapper. Bucket policy blocks `DeleteObject` on `raw/*`, `config/*`, `uploads/*`, `generated/*` for `matthew-admin`.

**S3 prefix separation (ADR-046)** — Lambda-generated files (public_stats.json, character_stats.json, OG images, journal posts) live in `generated/` prefix, NOT `site/`. CloudFront routes generated-file URLs to S3GeneratedOrigin. This makes `aws s3 sync site/ --delete` structurally safe — it cannot touch generated content.

**Site API is primarily read-only** — the site-api Lambda reads from DynamoDB/S3 for all data endpoints. Limited writes exist for interactive features only: experiment/challenge votes, follows, checkins, experiment suggestions, and user-submitted findings (S3). Core data queries must never write.

**Rate limiting is in-memory** — `ask` (5 anon/20 subscriber per hour), `board_ask` (5 per IP per hour). Vote/follow rate limits use DynamoDB atomic counters with TTL.

**EventBridge crons use fixed UTC** — no DST drift. All schedules in `cdk/stacks/` must be UTC-fixed.

**Lambda Layer** — shared modules (`ai_calls.py`, `retry_utils.py`, `board_loader.py`, `output_writers.py`, `scoring_engine.py`, `secret_cache.py`, `site_writer.py`, `character_engine.py`, `intelligence_common.py`, `auth_breaker.py`, `compute_metadata.py`, `http_retry.py`, `numeric.py`, `platform_logger.py`, `rate_limiter.py`, `request_validator.py`, + others) are deployed as a layer (currently **v51**, mirrored in `cdk/stacks/constants.py:SHARED_LAYER_VERSION`). Note: `email_framework.py` was deleted in V2 (replaced inline). Changes here require a layer rebuild (`bash deploy/build_layer.sh`) before deploying dependent functions. Source of truth: `aws lambda list-layer-versions --layer-name life-platform-shared-utils --query 'LayerVersions[0].Version'`.

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

---

**Verified:** 2026-05-19 (v8.0.0)
