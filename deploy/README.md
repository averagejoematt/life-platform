# Deploy Scripts — Reference Guide

> **Status:** canonical · **Verified:** 2026-07-18 (#1322 — rewritten against the live scripts)
>
> Scripts in this directory are **run locally in Terminal** (or by CI) — never via Claude MCP tools.
>
> **The canonical deploy *rules* live in `docs/CONVENTIONS.md` §1–§2** (the #781 one-bundle
> invariant, deploy-from-main, squash-drift checks, site-deploy-on-merge). This file only
> describes what the scripts *are*; when a rule is stated here it's a pointer, not the truth.
> The session driver with the function-name → source-file mapping is `.claude/commands/deploy.md`.
>
> **Symptom-keyed operational runbook:** `deploy/OPERATIONAL_RUNBOOK.md` — read first when something looks wrong.
> **First time deploying?** Read `docs/QUICKSTART.md` — it has a deploy decision tree and gotchas.
>
> **Multi-step state changes** (anything touching multiple DDB partitions OR multiple S3 prefixes)
> MUST go through `deploy/restart_pipeline.py` — see ADR-059.

---

## The one rule that matters (#781)

**Every deploy path stages the SAME full-tree bundle via `deploy/build_bundle.py`** — the
whole `lambdas/` tree + `config/food_vocabulary.json`; the mcp shape adds `mcp_server.py` +
`mcp/`. CDK assets, `deploy_lambda.sh`, `deploy_fleet.sh`, and `deploy_site_api.sh` all go
through it, so a partial zip that strips sibling or shared modules is structurally
impossible, and there is no shared layer (retired by #781/ADR-131 — only the dependency
layers, garth/Pillow, remain). `tests/test_deploy_bundle_paths.py` enforces that every
channel stays on the staging module. Full rule: `docs/CONVENTIONS.md` §1.

---

## Deploy Decision Tree

**"I changed a file. Which script do I run?"** See `docs/QUICKSTART.md` for the full table. Key rules:

1. **Lambda code** → `bash deploy/deploy_and_verify.sh <function-name> <source-file>`
   (wraps `deploy_lambda.sh` with a post-deploy invoke + CloudWatch log check — preferred),
   or `bash deploy/deploy_lambda.sh <function-name> <source-file>` for the bare deploy.
2. **MCP Lambda** → `bash deploy/deploy_lambda.sh life-platform-mcp mcp_server.py` —
   the script detects `life-platform-mcp`/`life-platform-mcp-warmer` and builds the
   **mcp-shaped full bundle** automatically (`build_bundle.py --mcp`: whole `lambdas/` tree +
   `mcp_server.py` + `mcp/`, so `reading/` and every shared module are inside). See
   "MCP Lambda" below for the boot check. (The old ADR-031 hand-rolled zip recipe that used
   to live here is **retired** — it staged no `lambdas/` tree and boot-broke the function
   with `No module named 'reading'`; `docs/_lint/tombstones.txt` now bans it.)
3. **site-api** → `bash deploy/deploy_site_api.sh` (full bundle + invoke-verifies a real
   route; infra is CDK-owned in `cdk/stacks/serve_stack.py` — see `.claude/commands/deploy.md`).
4. **Shared module** (`ai_calls.py`, `stats_core.py`, …) → `bash deploy/deploy_fleet.sh`
   (one bundle → every function) or `cd cdk && npx cdk deploy --all`.
5. **CDK changes** (IAM, schedules, new Lambda) → `cd cdk && npx cdk deploy <StackName>`.
   The stack list lives in `cdk/app.py` / `docs/ARCHITECTURE.md` — don't trust a
   hand-maintained table here. After a CDK deploy: `bash deploy/post_cdk_smoke.sh`.
6. **Site content** → merge to `main`; a push touching `site/**` deploys automatically via
   `.github/workflows/site-deploy.yml` (#750). Attended fallback: `bash deploy/sync_site_to_s3.sh`
   (+ explicit fonts sync). Canonical rule: `docs/CONVENTIONS.md` §2.
7. **S3 data** → NEVER `aws s3 sync --delete` without `deploy/lib/safe_sync.sh` (ADR-032).

---

## The Golden Rule

**Run scripts from the project root**, not from inside `deploy/`:

```bash
# Correct
cd ~/Documents/Claude/life-platform
bash deploy/deploy_lambda.sh daily-brief lambdas/emails/daily_brief_lambda.py

# Wrong — relative paths will break
cd deploy
bash deploy_lambda.sh daily-brief lambdas/emails/daily_brief_lambda.py
```

Both arguments are required: `deploy_lambda.sh <function-name> <source-file>`. The source
file is a sanity check (the live handler must resolve inside the bundle) — the deploy
always ships the full tree regardless. Per-Lambda region overrides come from
`ci/lambda_map.json`.

---

## Core scripts

The full inventory is `ls deploy/*.sh deploy/*.py` — every script documents itself in its
header, and one-time scripts get moved to `archive/` (see Archive Policy). **This table is
deliberately not exhaustive and carries no count** — the previous "Active Scripts (20)"
claim had drifted to a fraction of reality. These are the ones you'll actually reach for:

| Script | Purpose |
|--------|---------|
| `build_bundle.py` | Stage/zip the ONE full-tree code bundle (#781) — used by every deploy path |
| `deploy_lambda.sh <fn> <src>` | Deploy one Lambda (full bundle; mcp shape auto-detected) |
| `deploy_and_verify.sh <fn> <src>` | `deploy_lambda.sh` + post-deploy invoke + log check — preferred |
| `rollback_lambda.sh <fn>` | Restore the previous zip (S3 rollback artifact) |
| `deploy_fleet.sh [--dry-run]` | Push the bundle to every function (shared-module change) |
| `deploy_site_api.sh [path]` | site-api full bundle + invoke-verify a real route |
| `sync_site_to_s3.sh` | Attended site sync (content-hashed, self-invalidating) |
| `smoke_test_site.sh` | HTTP/content smoke of the public site |
| `post_cdk_smoke.sh` | Full smoke after a CDK deploy |
| `restart_pipeline.py` | THE orchestrator for experiment re-anchoring (ADR-059/077) |
| `sync_doc_metadata.py` | Sync doc resource counts from CDK/registry sources of truth |
| `lib/safe_sync.sh` | S3 sync wrapper that can never `--delete` the bucket root |
| `maintenance_mode.sh enable\|disable\|status` | Pause non-essential Lambdas |
| `pitr_restore_drill.sh` | Quarterly DynamoDB PITR restore drill |
| `archive_onetime_scripts.sh` | Move completed one-time scripts to `archive/` |

CloudWatch alarms and dashboards are **CDK-owned** (`cdk/stacks/monitoring_stack.py` and
per-stack alarms) — the old `create_*_alarm.sh` / `create_operational_dashboard.sh`
one-shots were archived to `deploy/archive/onetime/` and are no longer the way alarms
are managed.

---

## MCP Lambda

`bash deploy/deploy_lambda.sh life-platform-mcp mcp_server.py` builds and ships the
mcp-shaped full bundle. Then **verify it boots** — a `statusCode: 401` from an
unauthenticated invoke is the auth gate answering, i.e. a healthy import:

```bash
sleep 7
aws lambda invoke --function-name life-platform-mcp --region us-west-2 --cli-binary-format raw-in-base64-out \
  --payload '{"method":"tools/list","params":{}}' /tmp/mcp.json >/dev/null
python3 -c "import json; d=json.load(open('/tmp/mcp.json')); assert 'errorType' not in d, d; print('mcp OK', d.get('statusCode'))"
```

---

## Native dependencies (Garmin, Pillow, …)

Third-party packages with compiled parts ship as **dependency layers** (garth, Pillow —
ARNs pinned in `cdk/stacks/constants.py`), never inside the code bundle. When rebuilding
such a layer, install for the Lambda platform — packages built on macOS silently fail
at runtime:

```bash
pip install \
  --platform manylinux2014_x86_64 \
  --only-binary=:all: \
  --python-version 3.12 \
  --implementation cp \
  --target ./pkg \
  garth garminconnect
```

---

## Archive Policy

The `archive/` directory holds one-time scripts that have been run and are no longer
needed. Do not delete them — they serve as a record of what was done and when.

```bash
bash deploy/archive_onetime_scripts.sh
```

---

## Lambda inventory

`deploy/MANIFEST.md` is **deprecated** (superseded 2026) — do not use it as a source of
truth. The live inventory is:

- `docs/ARCHITECTURE.md` — the system-level Lambda inventory (counts auto-synced by `sync_doc_metadata.py`)
- `ci/lambda_map.json` — source-file → function mapping (+ per-Lambda region overrides) used by the deploy scripts
- `.claude/commands/deploy.md` — the function-name → source-file mapping for attended deploys
