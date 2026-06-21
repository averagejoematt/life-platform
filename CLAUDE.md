# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Documentation Index

Deep documentation lives in `docs/`. Start here when context is needed:
- `docs/README.md` — **the full doc index** (everything in `docs/`, categorized)
- `docs/ONBOARDING.md` — first-day mental model, key concepts
- `docs/QUICKSTART.md` — first-day commands (AWS auth, deploy, rollback)
- `docs/ARCHITECTURE.md` — full system design, ~73 Lambdas (CDK-defined; canonical count via `sync_doc_metadata.py` — ~55 currently deployed across us-west-2 + us-east-1), 8 CDK stacks, data flows (updated v8.4.0)
- `docs/SCHEMA.md` — DynamoDB field reference (authoritative)
- `docs/RUNBOOK.md` — daily operations, troubleshooting
- `docs/DECISIONS.md` — ADRs (ADR-001 through ADR-081), why things are the way they are
- `docs/PHASE_TAXONOMY.md` — experiment-restart data semantics (ADR-077): the 4-class registry for what resets vs. what's kept
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
   - **MCP Lambda** — 134 tools across 30 domain modules (`mcp/tools_*.py`, including `tools_hevy.py` per ADR-060, `tools_vacation.py` (vacation-fund tracker, 2026-06-01), and `tools_benchmark.py` (BENCH-1 cut-benchmarking, PRIVATE, ADR-089)), accessed via Claude Desktop and claude.ai. Source of truth is the count of top-level keys in the `TOOLS` dict in `mcp/registry.py` (134) — use `deploy/sync_doc_metadata.py::_auto_discover_tool_count` (AST parse). NB: `grep -c '"name":' mcp/registry.py` **over-counts** because it also matches nested `"name"` fields inside tool input schemas — do not use it as the count. **Note (V2 P4.1):** only ~11 tools used in last 30 days per EMF telemetry; bulk pruning planned.
   - **Compute Lambdas** (5) — run before 11 AM daily: `character-sheet`, `adaptive-mode`, `daily-metrics-compute`, `daily-insight-compute`, `hypothesis-engine`; store pre-computed results to DynamoDB
   - **Email Lambdas** (7) — daily brief at 11 AM reads pre-computed results
   - **OG Image Lambda** — generates 6 data-driven PNG share cards daily at 11:30 AM PT using Pillow
   - **Site API Lambda** (us-west-2, read-only) — serves averagejoematt.com with 60+ endpoints including `/api/vitals`, `/api/labs`, `/api/changes-since`, `/api/observatory_week`, `/api/vacation_fund`. **Multi-module package** (`web/*.py`): deploy the full `web/` dir, never single-file (see `.claude/commands/deploy.md`).

## Key Technical Conventions

**No external HTTP libraries** — all API calls use Python's `urllib.request` stdlib. No `requests`, no `httpx`. **Exception (ADR-062):** Claude inference goes through AWS Bedrock via `boto3 bedrock-runtime` (`lambdas/bedrock_client.py`), not urllib — Bedrock has no plain-HTTP endpoint and uses SigV4/IAM auth. All other HTTP (Whoop, Withings, Garmin, etc.) stays on urllib.

**Decimal for DynamoDB** — boto3 rejects Python `float`; cast to `Decimal` before writing.

**Single-table DynamoDB** — no GSIs; all access via composite key. Don't add GSIs without an ADR.

**Secrets Manager only** — all credentials at `life-platform/` prefix. Never `.env` files or hardcoded values.

**S3 safety (ADR-032/033/046)** — never `aws s3 sync --delete` to bucket root. Use `deploy/lib/safe_sync.sh` wrapper. Bucket policy blocks `DeleteObject` on `raw/*`, `config/*`, `uploads/*`, `generated/*` for `matthew-admin`.

**S3 prefix separation (ADR-046)** — Lambda-generated files (public_stats.json, character_stats.json, OG images, journal posts) live in `generated/` prefix, NOT `site/`. CloudFront routes generated-file URLs to S3GeneratedOrigin. This makes `aws s3 sync site/ --delete` structurally safe — it cannot touch generated content.

**Site API is primarily read-only** — the site-api Lambda reads from DynamoDB/S3 for all data endpoints. Limited writes exist for interactive features only: experiment/challenge votes, follows, checkins, experiment suggestions, and user-submitted findings (S3). Core data queries must never write.

**Rate limiting is DynamoDB-backed** (per-IP atomic counters, `rate_limiter.py`, since Phase 2.1 — survives warm-container distribution; an in-memory dict is the fail-open fallback only) — `ask` (5 anon/20 subscriber per hour), `board_ask` (5 per IP per hour), `subscribe` (60/5min/IP). Vote/follow rate limits also use DynamoDB atomic counters with TTL. (WAF removed 2026-06 — rate limiting is entirely in-Lambda now.)

**EventBridge crons use fixed UTC** — no DST drift. All schedules in `cdk/stacks/` must be UTC-fixed.

**Lambda Layer** — shared modules (`ai_calls.py` + its split modules `ai_context.py`/`ai_summaries.py` (god-module split 2026-06-08; `ai_calls` re-exports both for backward compat), `retry_utils.py`, `bedrock_client.py`, `budget_guard.py`, `board_loader.py`, `output_writers.py`, `scoring_engine.py`, `secret_cache.py`, `site_writer.py`, `character_engine.py`, `intelligence_common.py`, `auth_breaker.py`, `compute_metadata.py`, `http_retry.py`, `numeric.py`, `platform_logger.py`, `rate_limiter.py`, `request_validator.py`, + others) are deployed as a layer (currently **v85**, mirrored in `cdk/stacks/constants.py:SHARED_LAYER_VERSION`). Note: `email_framework.py` was deleted in V2 (replaced inline). Changes here require a layer rebuild (`bash deploy/build_layer.sh`) before deploying dependent functions. Source of truth: `aws lambda list-layer-versions --layer-name life-platform-shared-utils --query 'LayerVersions[0].Version'`.

**Prompt caching (COST-OPT-2)** — `ai_calls.py` and `retry_utils.py` auto-wrap system messages as Anthropic cached content blocks (90% discount). Model tiering: structured tasks use Haiku, narrative content uses Sonnet. All model assignments configurable via `AI_MODEL` env var. See ADR-049.

**Secret caching (COST-OPT-1)** — Lambdas cache Secrets Manager reads for 15 minutes via `secret_cache.py` in the shared layer. Reduces Secrets Manager API calls ~90%.

**Flake8 config** — max 140 chars, ignores E501, W503, E402, E741. See `.flake8`.

**Format gate (ENFORCED)** — CI's "Lint + Syntax Check" job runs `black --check lambdas/ mcp/ cdk/ tests/ scripts/ deploy/` and **fails the build** if anything isn't black-formatted (line-length 140, `pyproject.toml`). **Run `black` before committing** — flake8 alone is not enough; an unformatted file reds main and emails a CI failure per push. CI pins `black==25.9.0` (note: `requirements-dev.txt` currently pins 26.5.1 — a mismatch that can let local formatting diverge from the gate; match 25.9.0 when in doubt). `ruff==0.14.0` also runs.

## MCP Tool Modules

Tools in `mcp/` are split by domain: `tools_sleep.py`, `tools_health.py`, `tools_training.py`, `tools_nutrition.py`, `tools_cgm.py`, `tools_labs.py`, `tools_journal.py`, `tools_correlation.py`, `tools_character.py`, `tools_board.py`, `tools_lifestyle.py`, `tools_strength.py`, plus shared helpers in `handler.py`, `config.py`, `core.py`, `helpers.py`, `utils.py`, `registry.py`.

The tool registry in `mcp/registry.py` wires all tools. `tests/test_wiring_coverage.py` enforces that every tool is registered — run this after adding new tools.

## CDK Structure

8 stacks in `cdk/stacks/`: `ingestion`, `core`, `email`, `compute`, `mcp`, `operational`, `web`, `monitoring`. Entry point: `cdk/app.py`. Each stack creates its own IAM roles (least-privilege, one role per Lambda).

## CI/CD

GitHub Actions (`.github/workflows/ci-cd.yml`): Lint → Test → Plan → Deploy (requires manual approval via GitHub Environment: `production`) → Smoke Test → Auto-rollback if smoke fails. Auth via OIDC federation (no long-lived AWS keys).

**Site QA (3 complementary layers, ADR-076):** (1) `deploy/smoke_test_site.sh` — HTTP/content smoke (v4 pages 200, legacy URLs 301, API freshness); (2) `lambdas/operational/qa_smoke_lambda.py` — data/output health (DDB freshness, score sanity), nightly; (3) **`tests/visual_qa.py`** — Playwright browser sweep (inline-SVG renders, the cockpit pillar interaction, responsive overflow) **+ `tests/visual_ai_qa.py`** — Claude/Bedrock semantic vision QA of each screenshot (`--ai-qa`; Haiku, robust to daily data changes where pixel-diff false-positives). The harness runs post-deploy as the `visual-qa` CI job (**gating** since 2026-06-05 — a deterministic FAIL or AI "high" verdict blocks the pipeline; rollback's `needs` excludes it). Run locally: `python3 tests/visual_qa.py --screenshot --ai-qa` (needs `playwright install chromium`). The `/qa` skill wraps these.

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

## Experiment Restart Pipeline (ADR-058/059/077)

Experiment is anchored by `EXPERIMENT_START_DATE` in `lambdas/constants.py` (currently **2026-06-01**; a reset to **2026-06-08** is staged — see `handovers/HANDOVER_LATEST.md`). Re-anchoring is one idempotent command:

```bash
python3 deploy/restart_pipeline.py --genesis YYYY-MM-DD --apply
# Override Withings baseline when the genesis date has no weigh-in yet:
python3 deploy/restart_pipeline.py --genesis YYYY-MM-DD --override-weight-lbs <weight> --apply
# Carry forward selected chronicle issues as pre-genesis lead-ins (ADR-077):
python3 deploy/restart_pipeline.py --genesis YYYY-MM-DD --keep-chronicle DATE#... --apply
```

Regenerates constants, bumps the layer, deploys Core/Compute/Email, phase-tags DDB, wipes intelligence, rolls the accountability ledger into a durable `LIFETIME#` aggregate + zeroes `TOTALS#current` (`deploy/restart_ledger_reset.py` — ADR-072/077), rebuilds character, curates the chronicle, syncs site + docs, verifies 27 rendered pages. Rollback: `deploy/restart_rollback.py`.

**Phase taxonomy (ADR-077):** what resets vs. what's kept is decided by `lambdas/phase_taxonomy.py` — the single registry (`cross_phase` / `raw_timeseries` / `experiment_scoped` / `system_state`) that both the tagger and wipe derive from, with a coverage assertion so no scoped partition can silently survive a reset. Archived records are stamped `cycle=N` (SSM `/life-platform/experiment-cycle`) so the archive is navigable by reset generation. See `docs/PHASE_TAXONOMY.md`. Run the tagger/wipe in dry-run (no `--apply`) to preview the surface.

## Public Website (v4 "The Measured Life" — ADR-071)

`averagejoematt.com` is a static site (S3 + CloudFront `E3S424OXQZ8NBE`) over the unchanged engine — **three doors:** **Cockpit** (`/now/`, live data), **Story** (`/story/`, the writing hub — chronicle · AI lab notes · journal · timeline · about), **Evidence** (`/evidence/`, the data archive). Home (`/`) is a cinematic landing. The old site is preserved verbatim at `/legacy` (private rollback, no UI links); old URLs 301 via the CloudFront `v4-redirects` function (regenerated from `redirects.map` by `scripts/v4_migration_inventory.py`). No framework/deps: `tokens.css` design system + vanilla-JS ES modules, self-hosted fonts, inline-SVG charts. Build helpers: `scripts/v4_build_{evidence,dispatches,rss}.py`. Deploy: `bash deploy/sync_site_to_s3.sh` (content-hashed, self-invalidates; also regenerates `rss.xml`) + explicit `aws s3 sync site/assets/fonts/`. **Never link `/legacy` from the UI; engine/`/api/*` contracts are read-only from the front-end.**

---

**Verified:** 2026-06-21 (long chronicle-truthfulness + podcast-quality session — PRs #166–#182 merged + deployed, `origin/main` reconciled. **Chronicle:** the 2 origin chapters are now a pre-genesis **Prologue** (Part I "The Body Votes First" June 7 / Part II "The Empty Journal" June 11), rewritten to drop the stale "Week 1 / platform went live / 302→301" framing while preserving the prose. Week numbering is **genesis-anchored** (June 14) so today's installment is **Week 1** ("The Week That Decided to Begin", published) — killing the "9 lbs in three weeks" error (it was one week). `publish_to_journal` labels by date-vs-genesis (Prologue vs Week N); URLs stay sequential (`week-NN`) so links don't break. New **SUBSTANCE & VICE PRIVACY (ABSOLUTE)** chronicle-prompt rule — never name marijuana/porn even from journal data (caught + deleted a draft that named marijuana) + nutrition-logging-integrity (low cals = real deficit, not "not logging") + cold-reader grade-context rules. **Privacy:** Layne Norton (real person) → fictional **Dr. Marcus Webb** across the board config, both `web/` board-ask lambdas, the measurements MCP tool, and the chronicle interview-routing prompt. ⚠️ the legacy `_FALLBACK_ELENA_PROMPT` still carries real surnames (Attia/Huberman/Walker/Norton) — only fires if the S3 board config fails to load; tracked follow-up. **Podcast (panelcast) — major refit to Matt's bar (the transcript must pass a read-aloud Turing test):** voice now sourced from the persona registry (`config/personas.json` `tts_voice`), fixing gender-flipped voices (Dr. Marcus Webb was on a female voice) — regression test `tests/test_panelcast_voice_gender.py`; new `_WEEKLY_RUBRIC` read-aloud QA gate + **self-correcting revision loop** (feed the judge's exact failures back to the writer, ≤2 revisions, then human HOLD) = the autonomy mechanism; sensitivity gate now **AI-adjudicates crisis-vs-backstory** (was auto-holding strong weeks that merely referenced past grief); editor judge robust (retry + fail-OPEN on bad JSON, not a hard HOLD); ER-03 digit-matching **removed from the weekly gate** (over-dropped spoken numbers → holey transcripts/unanswered questions — grounding is the LLM judge's job now); `_published_posts` reads the live `generated/journal/posts.json` (was the dead `site/chronicle/posts.json` → week-drift). **Episode 1 published** ("Week 1 — Monday was a 49…", 4:28, Elena + Dr. Sarah Chen) after clearing QA via the revision loop — proper guest intro, grounded, gender-correct voices; Episode 0 (intro) also live. **Still human-in-the-loop (E)** — review 2–3 clean episodes before podcast autonomy. **SW:** JSON feeds (`posts.json`/`episodes.json`) are now **fresh-first**, not cache-first (new chronicle/podcast content was hidden until the SW version rolled); version rolled to `88b99f29`. Docs auto-synced (Tools 135, Lambdas 81). One-off publish scripts `deploy/_prologue_rewrite.py` + `deploy/_publish_week1.py` are untracked local records. See `handovers/HANDOVER_LATEST.md`. Prior session below.)

**Prior verified:** 2026-06-19 (EOD — long multi-stream session, PRs #152–#158 all merged; BENCH-1 also deployed live. **BENCH-1 cut benchmarking & regain firewall (ADR-089, PRIVATE):** new `episode-detect` Lambda (weekly Sun, reads FULL withings/strava/hevy history bypassing the ADR-058 phase filter) writes two cross-phase computed sources `weight_episodes` + `training_reference` (keyed like `computed_metrics`, no `phase` attr → survive resets); new `get_benchmark` MCP tool (`pace`/`episodes`/`maintenance`, tool #134, module `tools_benchmark.py`). Backfilled (29 episodes, **0 ever held**). Smoke: `get_benchmark(view=pace)` → `behind`, walk_gap 11.59, run_gate_ok False. **The work order's pasted ZigZag `turning_points` was broken** (`direction=0` records 0 pivots — verified); replaced with the standard ZigZag, reproduces validated values exactly. Two follow-up pace fixes (#157/#158): curve-edge clamp in `_proven_rate_at` + cross-phase regression rate in `_current_weight_and_rate` (the phase filter had left only post-genesis water-weight days → bogus 12.75 lb/wk). **⚠️ `cdk deploy LifePlatformCompute` reconciled the whole compute backlog** — the deferred **precompute readiness sleep 30→25** change is now LIVE (page-by-page QA still pending). Also merged: **Hevy per-type folders** (#154, `commit()` files routines into Push/Pull/Legs/Engine), **coaching calibration §4a** (#156, continuity-over-calendar + night-before planning + all-source pull + ruck edge case, docs-only PRIVATE), readiness date-integrity + email-noise reduction (#152). Garmin alarms deleted earlier (known-dead); `ingest-liveness-unhealthy` now red on **Strava** alone (402-path doesn't record a liveness attempt — open decision). Docs all in sync (Tools 134, Lambdas 81, layer v85). See `handovers/HANDOVER_LATEST.md` + the two earlier 2026-06-19 dated handovers (ReadinessDateIntegrity, InboxTriage_NoiseReduction). Prior session below.)

**Prior verified:** 2026-06-18 (PM — Episode 0 voice-bleed RCA + CloudFront-path bug + git reconciliation. **Episode 0 "Eli ends as Elena Voss" actually fixed:** the live cut had been voiced `02:02` UTC, **28 min before** the deterministic Elena-sign-off fix (`fd5d69ed`) was committed (`02:30`) — so the morning handover's "live cut already meets it" was wrong. Fixed by deploying `LifePlatformEmail` (carries the fix + the `cloudfront:CreateInvalidation` grant) then re-voicing via `aws lambda invoke --payload '{"intro":true}'`; close is now `…Eli → Elena → Elena(INTRO_SIGNOFF)` so Gemini voice-bleed is Elena→Elena. **CloudFront-path bug (fixed in #151):** `_invalidate_cdn` invalidated `/generated/panelcast/*` (the S3 **key** prefix) but CF matches the **viewer path** `/panelcast/*` (the `generated/` prefix is stripped at the edge) → it never busted the edge cache. Now derives the public path; ships next `LifePlatformEmail` deploy. Manual unblock: `create-invalidation --paths "/panelcast/*"`. **Concurrent-invoke race:** the CLI's 60 s read-timeout retried the invoke 3× → 3 concurrent generations; last write won (`20:37:02`, a 5:46 cut, all artifacts consistent). New correct cut (5:46) ≈ old buggy cut (5:47) — **judge the ending by listening, not the duration timer**; next time use `--cli-read-timeout 0` / `--invocation-type Event`. **Git reconciliation:** **PR #151** = clean net-delta of all post-#150 live work off `origin/main` (57 files, 1 commit) — merge when CI green, then delete the old `feat/temporal-frame-honesty-2026-06-17` branch. Matt's coaching docs (accidentally on the reconcile branch) split to **`chore/coaching-docs-2026-06-18`** off main (his call: PR or keep in claude.ai). ⚠️ pre-commit hook bumps doc dates to 2026-06-19 and leaves them unstaged — cosmetic. Next: Matt's QA walkthrough. See `handovers/HANDOVER_LATEST.md`.)

**Prior verified:** 2026-06-18 (public-site overhaul + deep board profiles + build fingerprinting — all LIVE, driven by Matt's walkthrough. **Site fixes:** bio-age privacy (page + API — true age not derivable), lb/kg lb-first, workout "Set N", Evidence scroll-jump (desktop `scrollIntoView` fought manual scroll → mobile-only), nutrition panel (nested `d.nutrition` + field-name fix), challenges dedupe, vice-streak cards. **New panels:** discoveries surfaces REAL `ai_findings` (FDR correlations the API computed but never rendered); **Recent cardio** = merged Strava+Whoop `cardio_sessions` with mi·km; habits last-7-days color grid; supplement "evidence ↗" links; experiment source attribution. **Evidence IA:** split 19-topic "Credibility & the machine" → "How it holds up" (7) + "The machine" (12); cycles/post-mortems/survival → footer-tier "The Reset Log" (`scripts/v4_build_evidence.py` `_REGROUP`). **Architecture diagram** (inline-SVG) on `/evidence/build/`. **Deep board profiles** on `/story/coaches/`: `_character()` + `_working_hypotheses()` enrich `/api/coach` (config + DDB, zero new AI). **Build fingerprinting:** `sync_site_to_s3.sh` stamps git-SHA+UTC → `/version.json` (no-cache) + `<meta name=build>` + footer stamp (Cockpit/Evidence) + rolls SW `VERSION` (kills stale-cache "v451 vs v452"). Verified live: `/version.json`==HEAD. ⚠️ **PR #150 squash-MERGED (earlier batch); branch is 24 ahead — post-#150 site work `c16aa511..9850b1ad` is LIVE but needs a fresh PR off `origin/main` (cherry-pick, don't re-PR this branch).** Next: Matt's QA walkthrough → batch the feedback. Board-page intro font still flagged (needs visual pinpoint). See `handovers/HANDOVER_LATEST.md`.)

**Prior verified:** 2026-06-17 (cost-telemetry + Hevy-title + reliability/noise session. **Merged:** #137/#138 (cost-governor trailing-AI projection + CE cadence — deployed; budget tier was a phantom tier-2), **#142** (G1/G2: meter AI spend at the `bedrock_client.invoke()` chokepoint per-feature + `EstimatedCostUSD` + `ai-daily-spend-high` alarm), **#143** (Hevy `Phase-Type-N-Y` renderer is authoritative — performed-derived per-phase N + reset-epoch Y, dry-run truthful, `force_title` lockdown; **ADR-088** supersedes the 2026-05-31 ADR-067 amendment). **Open PRs:** **#144** (project non-AI from a trailing window too — finishes the governor honesty fix), **#145** (Hevy type via exact `hevy_routine_id` link), **#146** (`black`-format 9 files — CI's **ENFORCED black gate** was reddening main on every push = the bulk of the email noise), **#147** (ai-expert-analyzer 120s→600s timeout [was dumping failed scheduled-events into the DLQ → 3 alarms], **G1 PutMetricData IAM gap** fixed in `_compute_base`, Garmin auth alarm URGENT→digest). **Email-noise RCA:** CI-spam=black gate (#146); DLQ=ai-expert timeout (#147, DLQ purged live); budget alerts=expected June outlier. **Garmin RCA:** Garmin 429-blocks server-side OAuth2 refresh (datacenter-IP crackdown) → re-auth only holds ~48h → **best-effort degraded; do NOT re-auth expecting it to stick**; sleep/HRV/recovery covered by Whoop+Eight Sleep. **Secrets consolidation = NO-GO** (verified: easy wins already in `ingestion-keys`; rest is rotating-OAuth or actively-read; log-retention already 30d). Panelcast wk5 HELD = correct fail-closed on genesis Day-Zero thin data (self-resolves as cycle-4 data accrues); HOLD-path IAM grants exist in code but need `cdk deploy LifePlatformEmail`. Layer **v85**. Full suite 1884 (2 pre-existing live-AWS integration failures). See `handovers/HANDOVER_LATEST.md`.)

**Prior verified:** 2026-06-16 (AM — cockpit circadian tile + cost investigation. #136 **cockpit `/now/` "tonight's forecast" tile** (renders `/api/circadian`, fail-quiet, present-tense) — merged + live. An AWS ">$75 forecast" prompted a full cost dig: **the platform is NOT over budget** — true steady-state ≈ **$60/mo** (AI ~$29 = Haiku $22 + Sonnet $9 trailing-7d; CloudWatch $9; Secrets $7.6 = 18 secrets' storage; CE $4.6; tax). The real defect was the **cost-governor crying wolf** — it projected $115/mo off a lumpy MTD-average AI rate and auto-paused website AI at tier 2. **#137** fixes it (project AI from a trailing 7-day window; pure `_project_month_end` helper + 3 tests; safe — only reduces false escalation, actual-mtd cap/early-month guard/tier-3 hard-stop untouched); **#138** trims the governor's own CE polling 4h→8h. **Dropped on inspection:** Tier-3 AI cuts (unneeded), the alarm-prune (the 6 ingest-consecutive-failures alarms catch hard-failures, complementary to #131's graceful-skip coverage — not redundant), caching re-enable (D-01). ⚠️ **#137 + #138 OPEN, deploys pending** — `life-platform-cost-governor` + `LifePlatformOperational`; tier stays 2 (website AI paused) until #137 deploys. Secrets consolidation available (~$2-3/mo) but deferred — not urgent. Full suite 1860. See `handovers/HANDOVER_LATEST.md`.)

**Prior verified:** 2026-06-15 (PM — elite-review fix sprint: **6 PRs #129–#134** from the 89-finding review, each re-verified before edit. #129 **surfaced** two compute outputs never exposed — `/api/circadian` (predictive 0–100 score) + `/api/sleep_reconciliation` (Whoop+Eight+Apple merged) + Evidence→Sleep panels; #130 **public-write hardening** (vote `catalog_id` validation, checkin date-dedup, finding idempotency); #131 **fleet-wide ingestion auth-liveness** (`auth_breaker` emits `IngestAuthHealthy`, alarm `ingest-auth-unhealthy-24h` live+OK — closed the notion/dropbox silent-death gap); #132 **AI-endpoint hardening** (history-replay gating + zero-width/obfuscation scrub); #133 **circadian DST fix** (hardcoded UTC-8 → DST-aware `ZoneInfo`, was skewing the score #129 surfaces); #134 **nudge+finding rate limits → DDB**. **5 findings dropped/bounded** on re-verify (EventBridge-DLQ, weekly-correlation, ACWR-parse, SIMP-2-already-covered, short-term-scrub-residual). ⚠️ **#133 + #134 deploys pending** — `circadian-compliance` + full `web/` site-api. Full suite 1852. See `handovers/HANDOVER_LATEST.md`.)

**Prior verified:** 2026-06-15 (wearables reliability + privacy purge + deep elite review — PRs #124–#127. **Strava 402 graceful-degrade** + **Garmin auth-liveness alarm** (`GarminAuthHealthy`/`GarminTokenDaysLeft`, both live) closed a silent-ingestion-death gap (both pipes were dead ~2–5 weeks); Garmin re-authed; **Garmin→Strava auto-upload ON** as the durable activity backstop. A **multi-path vice-catalog privacy leak** was sealed across site + API + seed + a **git-history rewrite** (force-pushed `main`+tags; GitHub Support GC of the old SHA across all 123 PRs **in-flight — option B**); **ER-05/06** PII guard added (`deploy/pii_surface_guard.py`, fail-closed in `sync_site_to_s3.sh`). A **558-agent DEEP elite review** produced **89 verified findings** (`docs/reviews/ELITE_REVIEW_2026-06-15.md`); fix batch 1 = silent-failure `return 500`→`raise` (#126) + pipeline-health IAM describe-only (#127); the "cost-cache leak" was a **verified false positive** (D-01 intentional). Remaining findings = a re-verify-before-fixing backlog. See `handovers/HANDOVER_LATEST.md`.)

**Prior verified:** 2026-06-14 (genesis day, cycle 4 — baseline **re-anchored to the real genesis weigh-in (314.52)** via `restart_pipeline.py --genesis 2026-06-14 --apply`; the podcast is now an **autonomous, QA-gated weekly show** (`coach_panel_podcast_lambda`: deterministic gather → Sonnet write (bet/Split/scoreboard format) → Haiku editor → **fail-closed Compassion & Safety gate** → publish-or-HOLD; Fri 17:00 cron, 900s; `series_state` in DDB `PANELCAST#`; **ADR-087** records the audio-realism ceiling) + a **Panel bet-ledger** (`/api/panel_ledger`); **Episode 0** finalized (Elena interviews Dr. Eli Marsh, single-pass Gemini, deterministic cold-open, numberless); **installable Cockpit PWA** (`site/sw.js`, iOS meta, manifest) + a **mobile bottom door-bar**. PRs #110–#119. See `handovers/HANDOVER_LATEST.md`.)

**Prior verified:** 2026-06-13 (evening — Evidence-catalog restore after the cycle-4 reset purge (supplements/experiments/challenges/habits read from durable `config/`; habits sourced from Habitify + vice-filtered), PR #110; podcasts off Polly → Google **Chirp 3: HD** + new **"The Panel"** show (PR #109) and **Episode 0 as a single-pass two-person Gemini 2.5 interview** (`gemini_tts.py`); new **Dr. Eli Marsh — Principal Investigator** lead persona above the 8 coaches (non-operational, PR #111). Two Google keys in `life-platform/google-tts`: `api_key`=Cloud TTS (managed project), `gemini_key`=Gemini (personal account).)

**Prior verified:** 2026-06-08 (v8.5.0 — 2026-06-08 experiment reset run (genesis 2026-06-08, baseline 311.62, cycle 3); A-grade CI gates ADR-080 (mypy tier-1 + coverage floor + size gate); `ai_calls` god-module split; **all CLI Lambda orphans adopted into CDK — `list-functions ∖ CDK = ∅`, ADR-081**; `/og` handler bug + Whoop refresh-race + qa-smoke genesis-awareness fixed; CI now flags undeployed Lambda config changes)
