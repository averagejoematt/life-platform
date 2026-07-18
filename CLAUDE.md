# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Documentation Index

Deep documentation lives in `docs/`. Start here when context is needed:
- **Website redesign / uplevel? Read these four first (the v5 brief):**
  - `docs/PLATFORM_NORTH_STAR.md` — the durable **why**: purpose, the causal-loop thesis, the 4 audiences, the success bar
  - `docs/SITE_MAP_AND_INTENT.md` — **what each page is for** and why it matters to the platform (one scannable registry)
  - `docs/DESIGN_SYSTEM_V5.md` — the **standards**: type triad, tokens, `.prose`, the page kit, the motion/interaction layer, the "earned glow / no gloss" rule
  - `docs/SITE_UPLEVEL_PLAYBOOK.md` — **how to change it well**: render-sweep→fix→verify loop + the hard-won gotchas (stored-artifact regen, CloudFront viewer-path, CDK-bundled lambdas)
  - `/uplevel` (`.claude/commands/uplevel.md`) — the **session driver**: fresh-eyes survey → rank against the north star → ship the flagship slice end-to-end (use `/uplevel <lane or idea>` to direct it)
- `docs/README.md` — **the full doc index** (everything in `docs/`, categorized)
- `docs/ONBOARDING.md` — first-day mental model, key concepts
- `docs/QUICKSTART.md` — first-day commands (AWS auth, deploy, rollback)
- `docs/ARCHITECTURE.md` — full system design, ~94 Lambdas (CDK-defined; canonical count via `sync_doc_metadata.py`), 9 CDK stacks, data flows
- `docs/SCHEMA.md` — DynamoDB field reference (authoritative)
- `docs/RUNBOOK.md` — daily operations, troubleshooting
- **The forward-work backlog is GitHub Issues (ADR-099)** — epics (`type:epic`) + ranked stories (`type:story`) on Now/Next/Later milestones; seed sessions from `gh issue list --label type:story --milestone Now --state open`; a shipping PR carries `Fixes #N`. `docs/BACKLOG.md` is a frozen archive.
- **`docs/CONVENTIONS.md` — the canonical home for the load-bearing deploy/CI reflexes** (the one-bundle rule #781, deploy-from-main, squash-drift checks, CI gate ordering, the asset-staging trap) + the drift-discovery commands. When one of those rules is stated below, it's a one-line pointer here, not a restatement — update the reflex in CONVENTIONS.md.
- `docs/DECISIONS.md` — ADRs (ADR-001 through ADR-135), why things are the way they are; **ADR-103 = the complexity-posture ledger** (load-bearing / portfolio / retire-candidate per subsystem — consult it before adding or removing machinery); **ADR-104 = honest numbers everywhere** (behavioral-absence semantics in the character engine + the grounded-generation gate on every AI narrative surface); **ADR-105 = the rigor bar** (uncertainty + n on every statistical claim, every forecast graded, deterministic computation before any LLM verdict, thresholds from personal variance); **ADR-106 = coach portraits** (AI may sketch, only code ships, only Matthew approves — `docs/design/PORTRAIT_RUNBOOK.md`); **ADR-107 = the coverage floor + mypy tier-2** (story #419); **ADR-108 = coach quality gate promoted advisory → blocking** (N-06 #390 — measured 30d re-eval on real CloudWatch verdicts before flipping, regenerate-or-hold in `ai_calls._enforce_quality_gate`)
- `docs/PHASE_TAXONOMY.md` — experiment-restart data semantics (ADR-077): the 4-class registry for what resets vs. what's kept
- `docs/REMEDIATION_TAXONOMY.md` — classifier rubric for the self-healing agent (auto-fix-safe / fix-via-pr / needs-human / stale)
- `docs/DATA_GOVERNANCE.md` — PII classification + retention policy (added v7.2.0)
- `docs/BOARDS.md` — the three AI persona boards (Personal, Technical, Product)
- `docs/REVIEW_METHODOLOGY.md` — how to run architecture audits
- `docs/archive/V2_AUDIT_PLAN.md` — V2 audit plan + outcomes (2026-05-17)

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

# Deploy a single Lambda (both args required; see deploy.md's mapping table)
bash deploy/deploy_lambda.sh <function-name> <source-file>

# Deploy + run smoke test
bash deploy/deploy_and_verify.sh <function-name> <source-file>

# CDK deploy all stacks
cd cdk && npx cdk deploy --all

# Start MCP bridge for Claude Desktop
python3 mcp_bridge.py
```

## Architecture Overview

**Ingest → Store → Serve** pipeline on AWS (us-west-2):

1. **Ingest**: 15 scheduled ingestion Lambda functions pull from APIs on EventBridge (8 SIMP-2 framework + 7 pattern-exempt per ADR-056/060; hourly 4am–10pm PST, except Garmin at 4x daily due to OAuth rate limits, Weather at 2x daily, Todoist at 1x daily (14:00 UTC — its 72h staleness threshold in `source_registry.py` is derived from that cadence, #471), Hevy at hourly 12-23 UTC). The standing `hevy-webhook` FunctionURL (parked since Hevy doesn't publish webhooks) was removed 2026-07-06 (#756, R21 kill list #8) — its handler source stays in git history for revival if Hevy ever ships webhooks. Gap-aware backfill — each ingestion Lambda detects missing `DATE#` records (including today) and only fetches what's absent. HAE webhook sources (CGM, water, BP, State of Mind) are near-real-time with reading-level dedup for cumulative fields.

2. **Store**: Raw JSON in S3 — the raw/ zone is **three-generation fractured** (X-9/#498): most sources write `raw/matthew/{source}/{YYYY}/{MM}/{filename}`, legacy todoist/weather write `raw/{source}/…` with no user segment, and hevy is flat UUID-keyed (`raw/hevy/{workout_id}.json`). **The leaf filename ALSO varies (#1256): framework/API sources write `YYYY-MM-DD.json` (the SIMP-2 migration flipped the old `DD.json` form to the full date mid-2026 — pre-2026 objects on the flipped sources todoist/garmin are still `DD.json`), while the HAE-webhook sources (cgm/blood_pressure/state_of_mind) write `DD.json`. Each source's actual layout — prefix, scheme, AND filename — is the `raw_layout` facet in `lambdas/source_registry.py`; read it, don't construct keys (no mass-move — raw/* is delete-protected).** Normalized metrics in DynamoDB single-table (`life-platform`, PK `USER#matthew#SOURCE#{source}`, SK `DATE#{YYYY-MM-DD}`).

3. **Serve/Compute**:
   - **MCP Lambda** — ~64 tools across ~23 domain modules (`mcp/tools_*.py`, including `tools_hevy.py` per ADR-060 and `tools_benchmark.py` (BENCH-1 cut-benchmarking, PRIVATE, ADR-089)), accessed via Claude Desktop and claude.ai. Source of truth is the count of top-level keys in the `TOOLS` dict in `mcp/registry.py` — use `deploy/sync_doc_metadata.py::_auto_discover_tool_count` (AST parse) — do NOT trust a hardcoded number here, it drifts. NB: `grep -c '"name":' mcp/registry.py` **over-counts** because it also matches nested `"name"` fields inside tool input schemas — do not use it as the count. **Note:** pruned 143 → 60 on 2026-07-08 (#395, ER-04) against 30-day EMF telemetry — the audited removal ledger is `docs/MCP_TOOL_AUDIT.md`; removals go through its dated AUDITED_AT ratchet, never silently.
   - **Compute Lambdas** (5) — `character-sheet`, `adaptive-mode`, `daily-metrics-compute`, `daily-insight-compute` run daily before the 17:00 UTC brief; `hypothesis-engine` runs weekly (Sun 19:00 UTC); all store pre-computed results to DynamoDB
   - **Email Lambdas** (7) — daily brief at 17:00 UTC (10 AM PDT) reads pre-computed results
   - **OG Image Lambda** — generates 6 data-driven PNG share cards daily at 11:30 AM PT using Pillow
   - **Site API Lambda** (us-west-2, read-only) — serves averagejoematt.com with 60+ endpoints including `/api/vitals`, `/api/labs`, `/api/changes-since`, `/api/observatory_week`, `/api/vacation_fund`. **Multi-module package** (`web/*.py`): code deploys via `deploy_site_api.sh` (the full-tree bundle, never single-file); infra (role/env/alarms) is CDK-owned in `serve_stack.py` (`LifePlatformServe` — split from Operational by #793 via `cdk refactor` so ops holds can't freeze the serving path; ownership rules per #794 — see `.claude/commands/deploy.md`).

## Key Technical Conventions

**No external HTTP libraries** — all API calls use Python's `urllib.request` stdlib. No `requests`, no `httpx`. **Exception (ADR-062):** Claude inference goes through AWS Bedrock via `boto3 bedrock-runtime` (`lambdas/bedrock_client.py`), not urllib — Bedrock has no plain-HTTP endpoint and uses SigV4/IAM auth. All other HTTP (Whoop, Withings, Garmin, etc.) stays on urllib.

**Decimal for DynamoDB** — boto3 rejects Python `float`; cast to `Decimal` before writing.

**Single-table DynamoDB** — two sanctioned GSIs exist (GSI1 recall-due sparse index, GSI2 reading state/time — ADR-097, documented in `lambdas/reading/reading_keys.py`); all other access via the composite key. Adding another GSI still requires an ADR.

**Secrets Manager only** — all credentials at `life-platform/` prefix. Never `.env` files or hardcoded values.

**S3 safety (ADR-032/033/046)** — never `aws s3 sync --delete` to bucket root. Use `deploy/lib/safe_sync.sh` wrapper. Bucket policy blocks `DeleteObject` on `raw/*`, `config/*`, `uploads/*`, `generated/*` for `matthew-admin`.

**S3 prefix separation (ADR-046)** — Lambda-generated files (public_stats.json, character_stats.json, OG images, journal posts) live in `generated/` prefix, NOT `site/`. CloudFront routes generated-file URLs to S3GeneratedOrigin. This makes `aws s3 sync site/ --delete` structurally safe — it cannot touch generated content.

**Site API is primarily read-only** — the site-api Lambda reads from DynamoDB/S3 for all data endpoints. Limited writes exist for interactive features only: experiment/challenge votes, follows, checkins, experiment suggestions, and user-submitted findings (S3). Core data queries must never write.

**Rate limiting is DynamoDB-backed** (per-IP atomic counters, `rate_limiter.py`, since Phase 2.1 — survives warm-container distribution; an in-memory dict is the fail-open fallback only) — `ask` (5 anon/20 subscriber per hour), `board_ask` (5 per IP per hour), `subscribe` (60/5min/IP). Vote/follow rate limits also use DynamoDB atomic counters with TTL. (WAF removed 2026-06 — rate limiting is entirely in-Lambda now.)

**EventBridge crons use fixed UTC** — no DST drift. All schedules in `cdk/stacks/` must be UTC-fixed.

**Shared code — ONE bundle, no layer (#781, 2026-07-06)** — the shared layer (`life-platform-shared-utils`) is RETIRED. Shared modules (`ai_calls.py` + its split modules `ai_context.py`/`ai_summaries.py`, `retry_utils.py`, `bedrock_client.py`, `stats_core.py`, `personal_baselines.py`, + the rest of `lambdas/*.py`) ship **inside every function's code bundle**, staged by `deploy/build_bundle.py` (the whole `lambdas/` tree + `food_vocabulary.json`; MCP also gets `mcp_server.py` + `mcp/`). All deploy paths stage through it (CDK asset, `deploy_lambda.sh`, `deploy_fleet.sh`, `deploy_site_api.sh`), so layer-version drift and partial-zip import breaks are structurally impossible. A shared-module change reaches the fleet via `deploy_fleet.sh` or `cdk deploy --all` (CI fleet-deploys automatically on unmapped `lambdas/` changes). Invariant: zero functions reference the old layer (CI plan job + I2). Dependency layers (garth, pillow) remain. See `docs/CONVENTIONS.md` §1.

**Prompt caching (COST-OPT-2)** — `ai_calls.py` and `retry_utils.py` auto-wrap system messages as Anthropic cached content blocks (90% discount). Model tiering: structured tasks use Haiku, narrative content uses Sonnet. All model assignments configurable via `AI_MODEL` env var. See ADR-049.

**Secret caching (COST-OPT-1)** — Lambdas cache Secrets Manager reads for 15 minutes via `secret_cache.py` (bundled shared module). Reduces Secrets Manager API calls ~90%.

**Flake8 config** — max 140 chars, ignores E501, W503, E402, E741. See `.flake8`.

**Format gate (ENFORCED)** — CI's "Lint + Syntax Check" job runs `black --check lambdas/ mcp/ cdk/ tests/ scripts/ deploy/` and **fails the build** if anything isn't black-formatted (line-length 140, `pyproject.toml`). **Run `black` before committing** — flake8 alone is not enough; an unformatted file reds main and emails a CI failure per push. `ruff` also runs. **The gates report independently (`if: always()`, #749 — one red no longer masks the rest) and the pinned tool versions can drift from `requirements-dev.txt`** — read the pins from CI and see the full gate ordering + the FAKE-creds parity run in `docs/CONVENTIONS.md` §4.

## MCP Tool Modules

Tools in `mcp/` are split by domain: `tools_health.py`, `tools_training.py`, `tools_nutrition.py`, `tools_cgm.py`, `tools_labs.py`, `tools_journal.py`, `tools_correlation.py`, `tools_lifestyle.py`, `tools_strength.py`, `tools_reading.py`, `tools_todoist.py`, plus shared helpers in `handler.py`, `config.py`, `core.py`, `helpers.py`, `utils.py`, `registry.py`. (#395 pruned 12 modules whose tools all went unused — see `docs/MCP_TOOL_AUDIT.md`.)

The tool registry in `mcp/registry.py` wires all tools. `tests/test_wiring_coverage.py` enforces that every tool is registered — run this after adding new tools.

## CDK Structure

9 stacks in `cdk/stacks/`: `ingestion`, `core`, `email`, `compute`, `mcp`, `operational`, `serve` (public serving path — site-api + site-api-ai, #793), `web`, `monitoring`. Entry point: `cdk/app.py`. Each stack creates its own IAM roles (least-privilege, one role per Lambda).

## CI/CD

GitHub Actions (`.github/workflows/ci-cd.yml`): Lint → Test → Plan → Deploy (requires manual approval via GitHub Environment: `production`) → Smoke Test → Auto-rollback if smoke fails. Auth via OIDC federation (no long-lived AWS keys).

**Site QA (3 complementary layers, ADR-076):** (1) `deploy/smoke_test_site.sh` — HTTP/content smoke (v4 pages 200, legacy URLs 301, API freshness); (2) `lambdas/operational/qa_smoke_lambda.py` — data/output health (DDB freshness, score sanity), nightly; (3) **`tests/visual_qa.py`** — Playwright browser sweep (inline-SVG renders, the cockpit pillar interaction, responsive overflow) **+ `tests/visual_ai_qa.py`** — Claude/Bedrock semantic vision QA of each screenshot (`--ai-qa`; Haiku, robust to daily data changes where pixel-diff false-positives). The harness runs post-deploy as the `visual-qa` CI job (**gating** since 2026-06-05 — a deterministic FAIL or AI "high" verdict blocks the pipeline; rollback's `needs` excludes it). Run locally: `python3 tests/visual_qa.py --screenshot --ai-qa` (needs `playwright install chromium`). The `/qa` skill wraps these.

## AI Inference (Bedrock + Budget Guard)

**Single chokepoint:** all Claude calls route through `lambdas/bedrock_client.invoke()` (ADR-062). Auth is IAM (`bedrock:InvokeModel` + `InvokeModelWithResponseStream`), no API key. Cross-region inference profiles required: `us.anthropic.claude-sonnet-4-6` (narrative) and `us.anthropic.claude-haiku-4-5-20251001-v1:0` (structured). Prompt caching uses `cache_control` blocks on the system message (~2048+ tokens to engage).

**$85/month hard ceiling** (ADR-063, base raised $75→$85 by the ADR-133 amendment 2026-07-08; **floats to $100 in reader-traffic surge mode** — ≥900 trailing-7d uniques, ADR-133): one AWS budget covers ALL spend (`life-platform-monthly-75` — name is historical, deliberately not renamed). `cost_governor_lambda` (every 8h) projects month-end spend (non-AI from Cost Explorer + Bedrock token usage × current price) and writes a tier 0–3 to SSM `/life-platform/budget-tier`; tier bands are fixed fractions (≈73%/87%/97%) of the effective ceiling. `lambdas/budget_guard.py` (bundled module) gates AI features by tier (audience-ordered per ADR-125):
- **0** (<73% of ceiling): all AI runs normally.
- **1** (73–87%): internal/dev AI paused (ensemble, chronicle editor, coherence-semantic).
- **2** (87–97%): + reader narratives paused (coach commentary, State of Matthew, chronicle).
- **3** (≥97%): hard cutoff — website AI returns "paused", daily brief skips AI; `bedrock_client.invoke()` raises `BudgetExceeded`.

Daily brief is "protect longest" by design. Manual reset for testing: `aws ssm put-parameter --name /life-platform/budget-tier --value 0 --type String --overwrite`.

## Self-healing Remediation Agent (ADR-064/065)

Scheduled GitHub Actions workflow (`.github/workflows/remediation-agent.yml`, ~07:45 PT Mon/Wed/Fri — cron `45 14 * * 1,3,5`; urgent alarms still trigger it on-demand via `repository_dispatch`) triages CloudWatch alarms, failed CI runs, DLQ depth, QA-smoke results — auto-fixes the safe class, opens PRs for the rest, reports needs-human items in one curated email.

**Auth:** AWS OIDC → `github-actions-remediation-role` (Bedrock + read-only diagnosis + scoped audit-log writes, NO deploy/IAM mutate). Model: Sonnet 4.6 on Bedrock — no Anthropic key.

**Kill-switch:** SSM `/life-platform/remediation-mode` = `off | shadow | auto`. Tier-3 budget also no-ops the run.

**Auto-merge is a deterministic gate, not the agent** (ADR-065). The agent (read-only role) opens `auto-fix-safe` PRs; `remediation/automerge.py` runs after and merges only if ALL hold: every file on a narrow ALLOWLIST (role_policies, lambda_map, monitoring_stack, freshness_checker, qa_smoke, tests/), no file on the DENYLIST (bedrock_client, budget_guard, auth/secrets, deploy/, workflows/, core_stack), diff ≤ 60 lines, lint + offline unit-test subset pass, daily cap (3) not reached. **CI's production approval gate stays intact** — auto-merge does NOT auto-deploy. Infra merges that touch `cdk/` are flagged "needs cdk deploy."

**Audit log:** every gate decision → `s3://matthew-life-platform/remediation-log/automerge/`. Classifier rubric: `docs/REMEDIATION_TAXONOMY.md`.

## Experiment Restart Pipeline (ADR-058/059/077)

Experiment is anchored by `EXPERIMENT_START_DATE` in `lambdas/constants.py` (currently **2026-07-19**, cycle 8 — a future genesis is sanctioned: the site runs a pre-start countdown until Day 1, #931/#939). Re-anchoring is one idempotent command:

```bash
python3 deploy/restart_pipeline.py --genesis YYYY-MM-DD --apply
# Override Withings baseline when the genesis date has no weigh-in yet:
python3 deploy/restart_pipeline.py --genesis YYYY-MM-DD --override-weight-lbs <weight> --apply
# Carry forward selected chronicle issues as pre-genesis lead-ins (ADR-077):
python3 deploy/restart_pipeline.py --genesis YYYY-MM-DD --keep-chronicle DATE#... --apply
```

Regenerates constants, deploys Core/Compute/Email (constants ship in every bundle — #781), phase-tags DDB, wipes intelligence, rolls the accountability ledger into a durable `LIFETIME#` aggregate + zeroes `TOTALS#current` (`deploy/restart_ledger_reset.py` — ADR-072/077), rebuilds character, curates the chronicle, syncs site + docs, verifies the 40-URL v4 surface (33 pages + 7 JSON endpoints, #918). Rollback: `deploy/restart_rollback.py`.

**Phase taxonomy (ADR-077):** what resets vs. what's kept is decided by `lambdas/phase_taxonomy.py` — the single registry (`cross_phase` / `raw_timeseries` / `experiment_scoped` / `system_state`) that both the tagger and wipe derive from, with a coverage assertion so no scoped partition can silently survive a reset. Archived records are stamped `cycle=N` (SSM `/life-platform/experiment-cycle`) so the archive is navigable by reset generation. See `docs/PHASE_TAXONOMY.md`. Run the tagger/wipe in dry-run (no `--apply`) to preview the surface.

## Public Website (v4 "The Measured Life" — ADR-071)

`averagejoematt.com` is a static site (S3 + CloudFront `E3S424OXQZ8NBE`) over the unchanged engine — **Home + 5 doors** (v5 IA): **the cockpit** (`/cockpit/`, live data) · **the data** (`/data/`, the evidence archive — old `/evidence/*` slugs 301) · **the coaching** · **the protocols** · **the story** (`/story/`, the writing hub). Home (`/`) is a cinematic landing. The old site is preserved verbatim at `/legacy` (private rollback, no UI links); old URLs 301 via the CloudFront `v4-redirects` function (regenerated from `redirects.map` by `scripts/v4_migration_inventory.py`). No framework/deps: `tokens.css` design system + vanilla-JS ES modules, self-hosted fonts, inline-SVG charts. Build helpers: `scripts/v4_build_{evidence,dispatches,rss}.py`. Deploy: **automatic on merge** — a push to `main` touching `site/**` runs `.github/workflows/site-deploy.yml` (#750: canonical sync + fonts sync + smoke/visual-QA gates + `rollback_site.sh` auto-rollback; no approval gate). Attended path: `bash deploy/sync_site_to_s3.sh` (content-hashed, self-invalidates; also regenerates `rss.xml`) + explicit `aws s3 sync site/assets/fonts/`. **Never link `/legacy` from the UI; engine/`/api/*` contracts are read-only from the front-end.**

---

## Session status (the ONE live block — replace, don't stack)

**Wrap convention (#365):** on session close, the outgoing status block REPLACES the
block below — it never stacks. Full session history lives in `handovers/` (one file per
session, `HANDOVER_LATEST.md` = the live driver) and the pre-2026-07 diary is archived at
`handovers/archive/CLAUDE_MD_SESSION_DIARY_2026-07-03.md`. Durable lessons go to the
memory system or the convention sections above, not into this block. **Build-beat wrap
gate (#736): every wrap either distills ONE public build beat per
`docs/content/BUILD_DISPATCH_CHECKLIST.md` (#380 — merged+deployed work only, never
plans) or writes an explicit `**Build beat:** none — <reason>` line in the handover;
silent omission is not an outcome.**

**Verified:** 2026-07-18 (evening) — **/frontier-plan born + first run: the quantified-life strategy review** (companion to /fullreview + /sdlc-review — asks *what should this become next?*): 3-persona live walkthrough + flourishing-science coverage map + QS-market/AI-frontier sweeps + 8-lane ideation (10 agents, lean config) → 49 ideas → **5 epics #1363–#1367 + 47 stories under `review:frontier-2026-07-18` (9 Now/19 Next/19 Later, 0 missing milestones)** + upgrade comments on #718/#1080; research record `docs/reviews/FRONTIER_REVIEW_2026-07-18.md` (**PR #1368 merged** — first push redded the wiki-drift gate on doc-sync literal cross-PR drift; rebase + `sync_doc_metadata --apply` cleared it). Live-confirmed trust leaks drive the Now slice: snapshot 0%/red vs pulse 96%/8.4h same morning, brier_skill −0.0047 badged "authoritative/90", source counts 19-vs-26-vs-121, blank OG/no-JS crawler surface (#1369–#1371, #1395); plus Attempt-#7 framing (#1375/#1376), dark-PERMA daylighting (#1403), private intake ledger (#1405), felt-reality calibration (#1409 — start early, n accrues slowly). Matthew's mid-session channel ideas filed: #1383 Coach Line, #1388 avatar video diary, #1402 Broadcast, #1381 Theme River. Full slate ≈ +$6–11/mo (tier-0 safe, per-story flags). **Awaiting Matthew:** gate:owner decisions (nudge channel, avatar/anonymity, Meta setup, #1405 public form) + suggested closures #1251/#1252/#1244 (absorbed by #1369/#1371/#1375). All commits via isolated worktrees (shared tree was mid-flight on concurrent branches all session). Build beat: none (no deployed surface change). Full narrative: `handovers/HANDOVER_LATEST.md`; prior: `handovers/HANDOVER_2026-07-18_SdlcReview.md`.
