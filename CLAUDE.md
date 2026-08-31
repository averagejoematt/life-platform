# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Documentation Index

Deep documentation lives in `docs/`. Start here when context is needed:
- **`docs/CHARTER.md` — READ FIRST: the architecture constitution (#2843, epic #2842).** The five primitives (registry → derivation guard → ratchet → contract → dead-man) with their canonical exemplars, the paved roads (the ONLY sanctioned way to add a signal/lambda/page/coach/gate), and the standing rules. Session boot derives the architecture from the charter + the system model (`model/platform_model.json`, #2845/#3314 — the SessionStart hook prints `scripts/boot_brief.py`, the executable boot contract; every count below is a pointer, the model is the number), not from prose re-reads; `/uplevel` and the review skills grade against it.
- **Website redesign / uplevel? Read these four first (the v5 brief):**
  - `docs/PLATFORM_NORTH_STAR.md` — the durable **why**: purpose, the causal-loop thesis, the 4 audiences, the success bar
  - `docs/SITE_MAP_AND_INTENT.md` — **what each page is for** and why it matters to the platform (one scannable registry)
  - `docs/DESIGN_SYSTEM_V5.md` — the **standards**: type triad, tokens, `.prose`, the page kit, the motion/interaction layer, the "earned glow / no gloss" rule
  - `docs/SITE_UPLEVEL_PLAYBOOK.md` — **how to change it well**: render-sweep→fix→verify loop + the hard-won gotchas (stored-artifact regen, CloudFront viewer-path, CDK-bundled lambdas)
  - `/uplevel` (`.claude/skills/uplevel/SKILL.md`) — the **session driver**: fresh-eyes survey → rank against the north star → ship the flagship slice end-to-end (use `/uplevel <lane or idea>` to direct it)
- `docs/README.md` — **the full doc index** (everything in `docs/`, categorized)
- `docs/ONBOARDING.md` — first-day mental model, key concepts
- `docs/QUICKSTART.md` — first-day commands (AWS auth, deploy, rollback)
- `docs/ARCHITECTURE.md` — full system design, ~104 Lambdas (CDK-defined; canonical count via `sync_doc_metadata.py`), 10 CDK stacks, data flows
- `docs/SCHEMA.md` — DynamoDB field reference (authoritative)
- `docs/RUNBOOK.md` — daily operations, troubleshooting
- **The forward-work backlog is GitHub Issues (ADR-099)** — epics (`type:epic`) + ranked stories (`type:story`) on Now/Next/Later milestones (+ `Roadmap` for parked product vision — outside the debt count, one promotion per cycle; ADR-099 amendment 2026-08-22); seed sessions from `python3 scripts/backlog_next.py` (ranks the open corpus by each issue's own stored score, #1866); a shipping PR carries `Fixes #N`. `docs/BACKLOG.md` is a frozen archive.
- **`docs/CONVENTIONS.md` — the canonical home for the load-bearing deploy/CI reflexes** (the one-bundle rule #781, deploy-from-main, squash-drift checks, CI gate ordering, the asset-staging trap) + the drift-discovery commands. When one of those rules is stated below, it's a one-line pointer here, not a restatement — update the reflex in CONVENTIONS.md.
- `docs/DECISIONS.md` — ADRs (ADR-001 through ADR-155), why things are the way they are; **ADR-103/144 = the complexity-posture standard — the maintained ledger is `docs/PROPORTIONALITY.md`** (posture + rent + demote trigger per subsystem — consult it before adding or removing machinery); **ADR-104 = honest numbers everywhere** (behavioral-absence semantics in the character engine + the grounded-generation gate on every AI narrative surface); **ADR-105 = the rigor bar** (uncertainty + n on every statistical claim, every forecast graded, deterministic computation before any LLM verdict, thresholds from personal variance); **ADR-106 = coach portraits** (AI may sketch, only code ships, only Matthew approves — `docs/design/PORTRAIT_RUNBOOK.md`); **ADR-107 = the coverage floor + mypy tier-2** (story #419); **ADR-108 = coach quality gate promoted advisory → blocking** (N-06 #390 — measured 30d re-eval on real CloudWatch verdicts before flipping, regenerate-or-hold in `ai_calls._enforce_quality_gate`)
- `docs/PHASE_TAXONOMY.md` — experiment-restart data semantics (ADR-077): the 4-class registry for what resets vs. what's kept
- `docs/NEW_SIGNAL_PLAYBOOK.md` — **a new metric/device/source lands through one ordered checklist** (ADR-154): capture unfiltered → privacy tier BEFORE the first cron → absence semantics at birth → ingest-vs-park per consumer → SoT ruling per overlap → the consumer sweep
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

# CDK deploy (drift-guarded — runs check_deploy_drift.py first, see CONVENTIONS.md §6)
bash deploy/cdk_deploy.sh <StackName> [<StackName> ...]

# Bare CDK deploy — override path only, skips the drift guard
cd cdk && npx cdk deploy --all

# Start MCP bridge for Claude Desktop
python3 mcp_bridge.py
```

## Architecture Overview

**Ingest → Store → Serve** pipeline on AWS (us-west-2):

1. **Ingest**: scheduled ingestion Lambdas pull from APIs on EventBridge — most run through the shared SIMP-2 framework, a few are pattern-exempt (ADR-056/060), and Garmin is currently **paused** (vendor anti-automation crackdown, ADR-074 — no live EventBridge rule; the function stays deployed for manual re-auth invokes). **Per-source cadence, paused state, and staleness thresholds are the `method`/`paused`/`stale_hours` facets in `lambdas/ingestion/source_registry.py` — read the registry, don't hand-state a source's schedule here; it drifts (#2003, guarded by `scripts/check_doc_facts.py`).** The scheduled-Lambda count is likewise derived from `cdk/stacks/ingestion_stack.py`'s live `schedule=` definitions, not hand-typed. The standing `hevy-webhook` FunctionURL (parked since Hevy doesn't publish webhooks) was removed 2026-07-06 (#756, R21 kill list #8) — its handler source stays in git history for revival if Hevy ever ships webhooks. Gap-aware backfill — each ingestion Lambda detects missing `DATE#` records (including today) and only fetches what's absent. HAE webhook sources (CGM, water, BP, State of Mind) are near-real-time with reading-level dedup for cumulative fields.

2. **Store**: Raw JSON in S3 — the raw/ zone is **three-generation fractured** (X-9/#498): most sources write `raw/matthew/{source}/{YYYY}/{MM}/{filename}`, legacy todoist/weather write `raw/{source}/…` with no user segment, and hevy is flat UUID-keyed (`raw/hevy/{workout_id}.json`). **The leaf filename ALSO varies (#1256): framework/API sources write `YYYY-MM-DD.json` (the SIMP-2 migration flipped the old `DD.json` form to the full date mid-2026 — pre-2026 objects on the flipped sources todoist/garmin are still `DD.json`), while the HAE-webhook sources (cgm/blood_pressure/state_of_mind) write `DD.json`. Each source's actual layout — prefix, scheme, AND filename — is the `raw_layout` facet in `lambdas/ingestion/source_registry.py`; read it, don't construct keys (no mass-move — raw/* is delete-protected).** Normalized metrics in DynamoDB single-table (`life-platform`, PK `USER#matthew#SOURCE#{source}`, SK `DATE#{YYYY-MM-DD}`).

3. **Serve/Compute**:
   - **MCP Lambda** — ~76 tools across ~26 domain modules (`mcp/tools_*.py`, including `tools_hevy.py` per ADR-060 and `tools_benchmark.py` (BENCH-1 cut-benchmarking, PRIVATE, ADR-089)), accessed via Claude Desktop and claude.ai. Source of truth is the count of top-level keys in the `TOOLS` dict in `mcp/registry.py` — use `deploy/sync_doc_metadata.py::_auto_discover_tool_count` (AST parse) — do NOT trust a hardcoded number here, it drifts. NB: `grep -c '"name":' mcp/registry.py` **over-counts** because it also matches nested `"name"` fields inside tool input schemas — do not use it as the count. **Note:** pruned 143 → 60 on 2026-07-08 (#395, ER-04) against 30-day EMF telemetry — the audited removal ledger is `docs/MCP_TOOL_AUDIT.md`; removals go through its dated AUDITED_AT ratchet, never silently.
   - **Compute Lambdas** (5) — `character-sheet`, `adaptive-mode`, `daily-metrics-compute`, `daily-insight-compute` run daily before the 17:00 UTC brief; `hypothesis-engine` runs weekly (Sun 19:00 UTC); all store pre-computed results to DynamoDB
   - **Email Lambdas** (7) — daily brief at 17:00 UTC (10 AM PDT) reads pre-computed results
   - **OG Image Lambda** — generates 6 data-driven PNG share cards daily at 11:30 AM PT using Pillow
   - **Site API Lambda** (us-west-2, read-only) — serves averagejoematt.com with ~134 endpoints including `/api/vitals`, `/api/labs`, `/api/changes-since`, `/api/observatory_week`, `/api/vacation_fund`. **Multi-module package** (`web/*.py`): code deploys via `deploy_site_api.sh` (the full-tree bundle, never single-file); infra (role/env/alarms) is CDK-owned in `serve_stack.py` (`LifePlatformServe` — split from Operational by #793 via `cdk refactor` so ops holds can't freeze the serving path; ownership rules per #794 — see `.claude/skills/deploy/SKILL.md`).

## Key Technical Conventions

**No external HTTP libraries** — all API calls use Python's `urllib.request` stdlib. No `requests`, no `httpx`. **Exception (ADR-062):** Claude inference goes through AWS Bedrock via `boto3 bedrock-runtime` (`lambdas/ai/bedrock_client.py`), not urllib — Bedrock has no plain-HTTP endpoint and uses SigV4/IAM auth. All other HTTP (Whoop, Withings, Garmin, etc.) stays on urllib.

**Decimal for DynamoDB** — boto3 rejects Python `float`; cast to `Decimal` before writing.

**Single-table DynamoDB** — two sanctioned GSIs exist (GSI1 recall-due sparse index, GSI2 reading state/time — ADR-097, documented in `lambdas/reading/reading_keys.py`); all other access via the composite key. Adding another GSI still requires an ADR.

**Secrets Manager only** — all credentials at `life-platform/` prefix. Never `.env` files or hardcoded values.

**S3 safety (ADR-032/033/046)** — never `aws s3 sync --delete` to bucket root. Use `deploy/lib/safe_sync.sh` wrapper. Bucket policy blocks `DeleteObject` on `raw/*`, `config/*`, `uploads/*`, `generated/*` for `matthew-admin`.

**S3 prefix separation (ADR-046)** — Lambda-generated files (public_stats.json, character_stats.json, OG images, journal posts) live in `generated/` prefix, NOT `site/`. CloudFront routes generated-file URLs to S3GeneratedOrigin. This makes `aws s3 sync site/ --delete` structurally safe — it cannot touch generated content.

**Site API is primarily read-only** — the site-api Lambda reads from DynamoDB/S3 for all data endpoints. Limited writes exist for interactive features only: experiment/challenge votes, follows, checkins, experiment suggestions, and user-submitted findings (S3). Core data queries must never write.

**Rate limiting is DynamoDB-backed** (per-IP atomic counters, `rate_limiter.py`, since Phase 2.1 — survives warm-container distribution; an in-memory dict is the fail-open fallback only) — `ask` (5 anon/20 subscriber per hour), `board_ask` (5 per IP per hour), `subscribe` (60/5min/IP). Vote/follow rate limits also use DynamoDB atomic counters with TTL. (WAF removed 2026-06 — rate limiting is entirely in-Lambda now.)

**EventBridge crons use fixed UTC** — no DST drift. All schedules in `cdk/stacks/` must be UTC-fixed.

**Shared code — ONE bundle, no layer (#781)** — canonical in `docs/CONVENTIONS.md` §1 (retirement date, `build_bundle.py`, which deploy paths stage through it, the zero-references invariant). Don't restate it here.

**`lambdas/` is packaged by domain (ADR-146, #1653)** — there are **no loose modules at the `lambdas/` root**. Handlers live in `ingestion/ compute/ emails/ web/ operational/ intelligence/ reading/`; shared engine code in `common/` (constants, logging, retries, time, HTTP), `ai/` (inference, budget, guardrails), `experiment/` (phase, gates, calibration, stats), `coach/ health/ training/ content/ privacy/`. The bundle stages the tree at the zip root, so runtime imports read `from common import constants`. Two rules that bite: (a) `tests/mypy_clean_set.py`'s `CLEAN_DIRS` globs are **non-recursive** — a new package must be added there (or the file to `CLEAN_FILES`) or its modules silently leave the mypy gate; (b) never resolve a data file as `dirname(dirname(__file__))/config/...` — use `common.repo_config`, which searches upward. `tests/test_lambdas_packaging_guard.py` keeps the root packaged.

**Prompt caching (COST-OPT-2)** — `ai_calls.py` and `retry_utils.py` auto-wrap system messages as Anthropic cached content blocks (90% discount). **A `cache_control` block is NOT evidence of caching**: below the model's minimum cacheable prefix the marker is silently ignored — no error, `cache_read_input_tokens` just stays 0 (Haiku 4.5's floor is 4,096 tok, 4x Sonnet's). Read the floor + the per-caller engaged/declined record from `lambdas/ai/prompt_cache.py`, and the live proof from the `PromptCacheNoOp` metric — never from the presence of the wrapper. Model tiering: structured tasks use Haiku, narrative content uses Sonnet. All model assignments configurable via `AI_MODEL` env var. See ADR-049 (+ its 2026-08-27 #3085 amendment).

**Secret caching (COST-OPT-1)** — Lambdas cache Secrets Manager reads for 15 minutes via `secret_cache.py` (bundled shared module). Reduces Secrets Manager API calls ~90%.

**Flake8 config** — max 140 chars, ignores E501, W503, E402, E741. See `.flake8`.

**Format gate (ENFORCED)** — CI's "Lint + Syntax Check" job runs `black --check lambdas/ mcp/ cdk/ tests/ scripts/ deploy/` and **fails the build** if anything isn't black-formatted (line-length 140, `pyproject.toml`). **Run `black` before committing** — flake8 alone is not enough; an unformatted file reds main and emails a CI failure per push. `ruff` also runs. **The gates report independently (`if: always()`, #749 — one red no longer masks the rest) and the pinned tool versions can drift from `requirements-dev.txt`** — read the pins from CI and see the full gate ordering + the FAKE-creds parity run in `docs/CONVENTIONS.md` §4.

## MCP Tool Modules

Tools in `mcp/` are split by domain: `tools_health.py`, `tools_training.py`, `tools_nutrition.py`, `tools_cgm.py`, `tools_labs.py`, `tools_journal.py`, `tools_correlation.py`, `tools_lifestyle.py`, `tools_strength.py`, `tools_reading.py`, `tools_todoist.py`, plus shared helpers in `handler.py`, `config.py`, `core.py`, `helpers.py`, `utils.py`, `registry.py`. (#395 pruned 12 modules whose tools all went unused — see `docs/MCP_TOOL_AUDIT.md`.)

The tool registry in `mcp/registry.py` wires all tools. `tests/test_wiring_coverage.py` enforces that every tool is registered — run this after adding new tools.

## CDK Structure

10 stacks in `cdk/stacks/`: `ingestion`, `core`, `email`, `compute`, `mcp`, `operational`, `serve` (public serving path — site-api + site-api-ai, #793), `web`, `monitoring`, `backup` (DIL-027/#3042 — the `raw/` cross-region replica bucket + replication role, **us-east-2**, deliberately not us-east-1 where `web` already lives). Entry point: `cdk/app.py`. Each stack creates its own IAM roles (least-privilege, one role per Lambda). **A non-default-region stack must be added to BOTH region maps** (`drift_sentinel.STACKS`, `check_lambda_config_drift.STACK_FILE_REGION`) with a string-literal `region=` in `app.py` — `tests/test_drift_checker_stack_regions.py` enforces it (#1816/#1817).

## CI/CD

GitHub Actions (`.github/workflows/ci-cd.yml`): Lint → Test → Plan → Deploy (requires manual approval via GitHub Environment: `production`) → Smoke Test → Auto-rollback if smoke fails. Auth via OIDC federation (no long-lived AWS keys).

**Site QA (3 complementary layers, ADR-076):** (1) `deploy/smoke_test_site.sh` — HTTP/content smoke (v4 pages 200, legacy URLs 301, API freshness); (2) `lambdas/operational/qa_smoke_lambda.py` — data/output health (DDB freshness, score sanity), nightly; (3) **`tests/visual_qa.py`** — Playwright browser sweep (inline-SVG renders, the cockpit pillar interaction, responsive overflow) **+ `tests/visual_ai_qa.py`** — Claude/Bedrock semantic vision QA of each screenshot (`--ai-qa`; Haiku, robust to daily data changes where pixel-diff false-positives). The harness runs post-deploy as the `visual-qa` CI job (**gating** since 2026-06-05 — a deterministic FAIL or AI "high" verdict blocks the pipeline; rollback's `needs` excludes it). Run locally: `python3 tests/visual_qa.py --screenshot --ai-qa` (needs `playwright install chromium`). The `/qa` skill wraps these.

## AI Inference (Bedrock + Budget Guard)

**Single chokepoint:** all Claude calls route through `lambdas/bedrock_client.invoke()` (ADR-062). Auth is IAM (`bedrock:InvokeModel` + `InvokeModelWithResponseStream`), no API key. Cross-region inference profiles required: `us.anthropic.claude-sonnet-4-6` (narrative) and `us.anthropic.claude-haiku-4-5-20251001-v1:0` (structured). Prompt caching uses `cache_control` blocks on the system message (~2048+ tokens to engage).

**$215/month hard ceiling** (ADR-063; base $75→$85 2026-07-08, →$150 2026-08-18 #2836, →$215 by the ADR-133 amendment 2026-08-28 #2801 — the permanent September base, derived from measured steady state $5.74/day n=25 ≈ $172/mo, NOT from a projection, and chosen as the lowest base that never reaches tier 2 across three modelled September burn rates; **floats to $252 in reader-traffic surge mode** — ≥900 trailing-7d uniques, ADR-133). **August 2026 ONLY, a dated window set the base to $200 / surge $235** (ADR-133 amendments 2026-08-09 #2381 + 2026-08-16 #2734, `_TEMP_CEILING_WINDOW`) — it **auto-reverts 2026-09-01 with no deploy or manual step**, and because the new base is higher, that revert is now a RAISE rather than the cliff it used to be; the AWS Budgets backstop moves WITH the permanent base (#2801 — it was pinned low only while the raises were temporary; a permanent base above the backstop would page every month by construction). **The backstop amount is resolved at CDK synth time by parsing the governor source, so `cdk deploy LifePlatformCore` is required even when no CDK file changed**: one AWS budget covers ALL spend (`life-platform-monthly-75` — name is historical, deliberately not renamed). <!-- drift-ok: the $200/$235 pair above is named as the August window's own value, which becomes history on 2026-09-01; the CURRENT claim on this line is the $215/$252 base --> `cost_governor_lambda` (every 8h) projects month-end spend (non-AI from Cost Explorer + Bedrock token usage × current price) and writes a tier 0–3 to SSM `/life-platform/budget-tier`; tier bands are fixed fractions (≈73%/87%/97%) of the effective ceiling. `lambdas/ai/budget_guard.py` (bundled module) gates AI features by tier (audience-ordered per ADR-125):
- **0** (<73% of ceiling): all AI runs normally.
- **1** (73–87%): internal/dev AI paused (ensemble, chronicle editor, coherence-semantic).
- **2** (87–97%): + reader narratives paused (coach commentary, State of Matthew, chronicle).
- **3** (≥97%): hard cutoff — website AI returns "paused", daily brief skips AI, and the two AI **CI gates** (`reader_truth_qa`, `visual_ai_qa`) pause here and ONLY here (ADR-125 amendment 2026-08-03, #1927 — they were in band 1 and consequently dark 26 of 30 days while still reporting green); `bedrock_client.invoke()` raises `BudgetExceeded`.

Daily brief is "protect longest" by design. Manual reset for testing: `aws ssm put-parameter --name /life-platform/budget-tier --value 0 --type String --overwrite`.

## Self-healing Remediation Agent (ADR-064/065 — a triage instrument, shadow permanently)

Scheduled GitHub Actions workflow (`.github/workflows/remediation-agent.yml`, ~07:45 PT Mon/Wed/Fri — cron `45 14 * * 1,3,5`; urgent alarms still trigger it on-demand via `repository_dispatch`) triages CloudWatch alarms, failed CI runs, DLQ depth, QA-smoke results — opens PRs for what it can fix, reports needs-human items in one curated email. **It merges nothing, in any mode.**

**Auth:** AWS OIDC → `github-actions-remediation-role` (Bedrock + read-only diagnosis + scoped audit-log writes, NO deploy/IAM mutate). Model: Haiku-primary on Bedrock (Sonnet for escalation) — no Anthropic key.

**Kill-switch:** SSM `/life-platform/remediation-mode` = `off | shadow`. Tier-3 budget also no-ops the run. **`auto` is a retired value** (owner decision on #2833, 2026-08-29; ADR-129 amendment 2026-08-30): zero agent-authored safe-class PRs were ever merged in either mode, so the deterministic auto-merge gate (`remediation/automerge.py`), the `auto_earn_marker.json` streak machinery and the 10-consecutive-clean-run re-promotion bar (#1337) were all retired together. A stale `auto` in SSM is coerced to `shadow` by `agent.py::gate()` and surfaced as a needs-human line — it is never honoured. There is no re-promotion path; reopening one is a new ADR, not an SSM flip.

**What the agent still does:** classifies each signal per `docs/REMEDIATION_TAXONOMY.md` (A = safe-class template, B = fix-via-PR, C = needs-human, D = stale). Buckets A and B both land as PRs a human merges — the `auto-fix-safe` label is a triage class, not a grant; IAM (`cdk/stacks/role_policies*`) stays Bucket B (#2611). `gh pr merge` is in the agent's `disallowed_tools` and the workflow has no merge step (`tests/test_remediation_agent.py` + the public-claims registry hold that shape). **CI's production approval gate is untouched** — a merged PR is never a deployed one.

**Rent (measured, ADR-105):** `LifePlatform/AI::EstimatedCostUSD{LambdaFunction=remediation-agent}` summed **$1.60 over 2026-08-24→30 (n=9 emitting runs of 11; 3 scheduled)** ≈ $0.18/run — see the row in `docs/PROPORTIONALITY.md`. **Audit log:** every run → `s3://matthew-life-platform/remediation-log/YYYY/MM/DD/HHMMSS.json`; the `automerge/` sub-prefix is history (it holds zero objects).

---

## Experiment Restart Pipeline (ADR-058/059/077)

Experiment is anchored by `EXPERIMENT_START_DATE` in `lambdas/common/constants.py` (currently **2026-08-17**, cycle 14 — a future genesis is sanctioned: the site runs a pre-start countdown until Day 1, #931/#939). Re-anchoring is one idempotent command:

```bash
python3 deploy/restart_pipeline.py --genesis YYYY-MM-DD --apply
# Override Withings baseline when the genesis date has no weigh-in yet:
python3 deploy/restart_pipeline.py --genesis YYYY-MM-DD --override-weight-lbs <weight> --apply
# Carry forward selected chronicle issues as pre-genesis lead-ins (ADR-077):
python3 deploy/restart_pipeline.py --genesis YYYY-MM-DD --keep-chronicle DATE#... --apply
```

Regenerates constants, deploys Core/Compute/Email (constants ship in every bundle — #781), phase-tags DDB, wipes intelligence, rolls the accountability ledger into a durable `LIFETIME#` aggregate + zeroes `TOTALS#current` (`deploy/restart_ledger_reset.py` — ADR-072/077), rebuilds character, curates the chronicle, syncs site + docs, verifies the 96-URL v4 surface (89 pages + 7 JSON endpoints, #918). Rollback: `deploy/restart_rollback.py`.

**Phase taxonomy (ADR-077):** what resets vs. what's kept is decided by `lambdas/experiment/phase_taxonomy.py` — the single registry (`cross_phase` / `raw_timeseries` / `experiment_scoped` / `system_state`) that both the tagger and wipe derive from, with a coverage assertion so no scoped partition can silently survive a reset. Archived records are stamped `cycle=N` (SSM `/life-platform/experiment-cycle`) so the archive is navigable by reset generation. See `docs/PHASE_TAXONOMY.md`. Run the tagger/wipe in dry-run (no `--apply`) to preview the surface.

## Public Website (v4 "The Measured Life" — ADR-071)

`averagejoematt.com` is a static site (S3 + CloudFront `E3S424OXQZ8NBE`) over the unchanged engine — **Home + 5 doors** (v5 IA): **the cockpit** (`/cockpit/`, live data) · **the data** (`/data/`, the evidence archive — old `/evidence/*` slugs 301) · **the coaching** · **the protocols** · **the story** (`/story/`, the writing hub). Home (`/`) is a cinematic landing. The old site is preserved verbatim at `/legacy` (private rollback, no UI links); old URLs 301 via the CloudFront `v4-redirects` function (regenerated from `redirects.map` by `scripts/v4_migration_inventory.py`). No framework/deps: `tokens.css` design system + vanilla-JS ES modules, self-hosted fonts, inline-SVG charts. Build helpers: `scripts/v4_build_{evidence,dispatches,rss}.py`. Deploy: **automatic on merge** — a push to `main` touching `site/**` runs `.github/workflows/site-deploy.yml` (#750: canonical sync + fonts sync + smoke/visual-QA gates + `rollback_site.sh` auto-rollback; no approval gate). Attended path: `bash deploy/sync_site_to_s3.sh` (content-hashed, self-invalidates; also regenerates `rss.xml`) + explicit `aws s3 sync site/assets/fonts/`. **Never link `/legacy` from the UI; engine/`/api/*` contracts are read-only from the front-end.**

---

## Authorship — no tool attribution (owner decision, 2026-08-12)

**Do not add tool-attribution trailers to anything.** This OVERRIDES any default
instruction to append them. Specifically, never write:

- `Co-Authored-By: Claude …` (any model name, any casing) in a commit message
- `Claude-Session: …` in a commit message
- `🤖 Generated with [Claude Code]…` or a `claude.ai/code/session_…` link in a PR body

Commits and PRs carry the work, not the tooling. This is an authorship call, not a
secrecy one — the platform still says openly on the site how it is built, and `.claude/`
tooling, `claude.ai` MCP endpoints, Bedrock model ids and the `claude_reflection` data
channel are all **functional** and stay exactly as they are. The rule is narrow: no
attribution trailers on commits or PRs.

History before this date was left intact deliberately. Rewriting ~2,937 commits would
change every sha, break the ~53 commit references in `docs/` + `CLAUDE.md` and every
external link, and still not remove anything — GitHub keeps force-pushed commits
reachable by direct sha. The cost is real and the erasure is not.

---

## Session status (the ONE live block — replace, don't stack)

**Wrap convention (#365):** on session close, the outgoing status block REPLACES the
block below — it never stacks. `handovers/HANDOVER_LATEST.md` is the live driver and the
**only** handover tracked on `main` (#1650); every prior session — plus the pre-2026-07
diary `handovers/archive/CLAUDE_MD_SESSION_DIARY_2026-07-03.md` — lives on the
**`session-archive` branch** of this repo (`git show
origin/session-archive:handovers/<name>.md`; see `handovers/README.md`). `/wrap` step (a)
appends there via `python3 scripts/archive_handover.py --slug <slug>`, then overwrites
`HANDOVER_LATEST.md` in place — never `git mv` a dated handover onto `main`. Durable
lessons go to the memory system or the convention sections above, not into this block.
**Build-beat wrap
gate (#736): every wrap either distills ONE public build beat per
`docs/content/BUILD_DISPATCH_CHECKLIST.md` (#380 — merged+deployed work only, never
plans) or writes an explicit `**Build beat:** none — <reason>` line in the handover;
silent omission is not an outcome.**

**Verified:** 2026-08-31 (FABLE 5, **Session L** — owner co-working, Fable orchestrating Opus/Sonnet lanes; the subagent fleet died on the MONTHLY spend limit at ~00:20Z and the main session finished by hand). **Ask: close as many issues as possible without risking quality. Closed 10** (#3316 #3278 #2833 #3328 #3327 #3251 #3317 **#3314** — the boot proof pasted — + #2848 merged as Refs pending its cold-read proof); **filed 8 carriers** (#3324 #3327 #3328 #3329 #3336 #3337 #3340) because verification kept finding real residuals. **11 PRs merged**; main-tip deploy lease approved (union), 6 superseded leases rejected by ancestry. **#3314 landed the operator's model:** the alarm plane held 50 of 116 alarms — now 119 (#795 inventory + composites), 0 unresolved, routing traced; privacy + schedules planes; `scripts/boot_brief.py` is the executable boot contract and the SessionStart hook prints it — a real boot from main consumed the model (proof on the issue). **Owner decisions:** #2834 → (b) scoped additive IAM CI grant, CISO review verdict APPROVE-WITH-REQUIRED-CHANGES R1–R5 on PR #3335 (lane died before landing them; #3340 follow-up filed); #3251 → C1 (measured $0.239→$0.048/run, closed); telegram-webhook-errors → digest (live). **Incident:** the IAM shell twin widened the remediation role's trust to any-branch for ~6 min (#3336, P1, INCIDENT_LOG row). Governor 00:00Z: titan $5.77→$0.01, drift 1.29→1.21x — #3308 verified to the cent. **Open PRs for next session:** #3335 (R1–R5), #3341 + #3339 (both superseded twice — GitHub minted ZERO runs for their pushes for 40+ min; third rung), plus dead-lane worktrees for #3336 #3277. Gotchas: a lane branch must never carry `platform_counts.py` (the pre-commit stages it; every later merge conflicts); epic checklists are stale by construction — reconcile from live child state. Next: #3336 first (P1) · land #3335 R1–R5 · un-swallow #3341/#3339 · #2848 cold-read proof · #3277 · BotFather (owner) · 09-08 Architect ritual runs ITSELF. Full narrative: `handovers/HANDOVER_LATEST.md`.
