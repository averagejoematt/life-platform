# RUNBOOK deploy records — May–June 2026 (archived from RUNBOOK.md)

> **Status:** archive · **Owner:** Matthew · **Verified:** 2026-07-10
> One-time deploy records for ADR-067/068/088 + the 2026-06-01 reset, executed in the
> pre-#781 shared-layer era. Commands are NOT runnable today (the layer is retired).

## Historical deploy records (completed — pre-#781 layer era)

> The four sections below are **records of one-time deploys executed in May–June 2026**, kept
> for audit context. The shared layer they reference was retired 2026-07-06 (#781/ADR-131),
> so their `build_layer.sh` / `SHARED_LAYER_VERSION` commands are **no longer runnable as
> written** — a module change today is one fleet deploy (`docs/CONVENTIONS.md` §1).
> Config-only steps (S3 `config/*.json` syncs) remain valid.

## Hevy Routine Title Convention — Deploy Steps (ADR-067)

Code is on `main`; layer v69 not yet published. Run these in order from the repo root.

```bash
# 1. Sync the new phase config to S3 (read by Lambda at runtime).
aws s3 cp config/training_phases.json s3://matthew-life-platform/config/ --region us-west-2

# 2. Build the layer bundle locally (includes routine_title.py).
bash deploy/build_layer.sh
ls cdk/layer-build/python/routine_title.py   # sanity check

# 3. Publish the layer + propagate to all consumers. Core publishes v69;
#    the rest pick it up via SHARED_LAYER_VERSION=69 in cdk/stacks/constants.py.
cd cdk
npx cdk deploy LifePlatformCore --require-approval never
npx cdk deploy \
  LifePlatformMcp \
  LifePlatformOperational \
  LifePlatformIngestion \
  LifePlatformEmail \
  LifePlatformCompute \
  --require-approval never --concurrency 3
cd ..

# 4. Verify all 36 layer-using Lambdas are on v69.
aws lambda list-functions --output json --region us-west-2 --no-paginate | \
  python3 -c "import json,sys; d=json.load(sys.stdin); vs={}; \
    [vs.setdefault((l['Arn'].rsplit(':',1)[-1]), []).append(f['FunctionName']) \
     for f in d['Functions'] for l in (f.get('Layers') or []) if 'shared-utils' in l['Arn']]; \
    [print(f'v{v}: {len(fns)}') for v, fns in sorted(vs.items())]"

# 5. Smoke-test the new title via MCP. (Force a cold start so the in-memory
#    phase-config cache reloads from S3.)
CUR=$(aws lambda get-function-configuration --function-name life-platform-mcp \
        --query 'Environment.Variables' --output json --region us-west-2)
ENV_PAYLOAD=$(python3 -c "
import json
env = json.loads('''$CUR''')
env['DEPLOY_VERSION'] = '2.74.4'
print(json.dumps({'Variables': env}))")
aws lambda update-function-configuration --function-name life-platform-mcp \
  --environment "$ENV_PAYLOAD" --region us-west-2 --query LastModified --output text

# 6. Re-commit an existing routine to see the new title applied in Hevy.
# (Use any active routine_id from `manage_hevy_routine action=list` via claude.ai.)
```

### Advancing the phase later

```bash
# Edit config/training_phases.json — change `current` + `current_started`.
# Then push to S3:
aws s3 cp config/training_phases.json s3://matthew-life-platform/config/ --region us-west-2
# Force cold start so warm containers reload the config:
aws lambda update-function-configuration --function-name life-platform-mcp \
  --environment "$ENV_PAYLOAD_WITH_NEW_DEPLOY_VERSION" --region us-west-2
```

N resets to 1 for each archetype the first time it's committed in the new phase. Y keeps counting up.

### Rollback (if titles look wrong)

```bash
# Revert the caller edits — title_context=None falls back to ir.title.
git revert --no-commit <commit-sha-of-adr-067>
# Or just unset title_context in mcp/tools_hevy_routine.py + cron_lambda.py and
# redeploy the MCP Lambda. The layer itself stays — routine_title.py is dormant.
```

---

## Final Experiment Reset → 2026-06-01 (ADR-067 amendment)

Source code already reflects the new genesis date (`lambdas/constants.py:EXPERIMENT_START_DATE = "2026-06-01"`, `config/user_goals.json:timeline.start_date`, `config/training_phases.json:current_started`). Run the restart-pipeline to apply everything else (phase-tag DDB, wipe intelligence, rebuild character, sync site/docs, layer publish, cdk deploy chain):

```bash
python3 deploy/restart_pipeline.py \
  --genesis 2026-06-01 \
  --override-weight-lbs 304.3 \
  --apply
```

The `--override-weight-lbs` is needed because 2026-06-01 has no Withings weigh-in yet; 304.3 lbs is the locked baseline from 2026-05-30 we're preserving.

After it completes, verify:

```bash
aws lambda list-functions --output json --region us-west-2 --no-paginate | \
  python3 -c "import json,sys; d=json.load(sys.stdin); vs={}; \
    [vs.setdefault(l['Arn'].rsplit(':',1)[-1], []).append(f['FunctionName']) \
     for f in d['Functions'] for l in (f.get('Layers') or []) if 'shared-utils' in l['Arn']]; \
    [print(f'v{v}: {len(fns)}') for v,fns in sorted(vs.items())]"
# Expect: v70: 36
```

Then force MCP cold start so the new constants are picked up:

```bash
CUR=$(aws lambda get-function-configuration --function-name life-platform-mcp \
        --query 'Environment.Variables' --output json --region us-west-2)
ENV_PAYLOAD=$(python3 -c "
import json
env = json.loads('''$CUR''')
env['DEPLOY_VERSION'] = '2.74.5'
print(json.dumps({'Variables': env}))")
aws lambda update-function-configuration --function-name life-platform-mcp \
  --environment "$ENV_PAYLOAD" --region us-west-2 --query LastModified --output text
```

Then from claude.ai: `manage_hevy_routine action=draft target_date=2026-06-01` → `action=dry_run routine_id=<id>` to see the new title. Y will start at 1 (no performed workouts since experiment start yet); N starts at 1 for each archetype.

---

## Hevy Title Renderer — Deploy Steps (ADR-088)

Code is on `main`; **nothing is deployed by the author** (layer module + MCP tool + config). Run in order from the repo root. Changed artifacts: `lambdas/routine_title.py` + `lambdas/hevy_common.py` (shared layer), `mcp/registry.py` + `mcp/tools_hevy_routine.py` (MCP lambda), `config/training_phases.json` (S3).

```bash
# 1. Sync the phase/counter config to S3 (read by Lambda at runtime).
#    current_started + reset_epoch_date = 2026-06-16.
aws s3 cp config/training_phases.json s3://matthew-life-platform/config/ --region us-west-2

# 2. Rebuild the shared layer (routine_title.py + hevy_common.py).
bash deploy/build_layer.sh
grep -c "count_performed_of_type" cdk/layer-build/python/routine_title.py   # sanity → 1

# 3. Publish the layer (Core) + propagate to consumers. Bump SHARED_LAYER_VERSION
#    in cdk/stacks/constants.py to the new version first if the build incremented it.
cd cdk
npx cdk deploy LifePlatformCore --require-approval never
npx cdk deploy \
  LifePlatformMcp LifePlatformOperational LifePlatformIngestion LifePlatformEmail LifePlatformCompute \
  --require-approval never --concurrency 3
cd ..

# 4. Redeploy the MCP server (registry.py + tools_hevy_routine.py changed — these
#    live in the MCP package, NOT the layer). Special build (see .claude/commands/deploy.md):
ZIP=/tmp/mcp_deploy.zip; rm -f $ZIP
zip -j $ZIP mcp_server.py mcp_bridge.py
zip -r $ZIP mcp/ -x 'mcp/__pycache__/*' 'mcp/*.pyc'
aws lambda update-function-code --function-name life-platform-mcp --zip-file fileb://$ZIP --region us-west-2

# 5. Verify: draft a custom routine, then dry_run — the wire_body title must read
#    "Foundation - Push - 2 - 2" (or "... - Pull - 1 - 2"), NOT "Push — <date>".
#    A title passed without force_title must be ignored (warning in the response).
```

Phase advancement later is config-only: edit `config/training_phases.json` (flip `current`, bump `current_started`), re-run step 1. No code deploy.

## Per-Exercise Notes — Deploy Steps (ADR-068)

Bundled with the ADR-067-amendment reset; both ship under layer v70. After `restart_pipeline` lands the reset, propagate v70 to all consumers and force the MCP cold start so the new modules + configs are read fresh:

```bash
# (1) Configs (re-sync; harmless if already in S3 from prior steps)
aws s3 cp config/training_week.json s3://matthew-life-platform/config/ --region us-west-2

# (2) Layer + cdk are handled by restart_pipeline above. If you only want
#     to ship ADR-068 without re-running restart_pipeline:
bash deploy/build_layer.sh
cd cdk
npx cdk deploy LifePlatformCore --require-approval never
npx cdk deploy LifePlatformMcp LifePlatformOperational LifePlatformIngestion \
               LifePlatformEmail LifePlatformCompute \
               --require-approval never --concurrency 3
cd ..

# (3) MCP cold start (preserves env vars)
CUR=$(aws lambda get-function-configuration --function-name life-platform-mcp \
        --query 'Environment.Variables' --output json --region us-west-2)
ENV_PAYLOAD=$(python3 -c "
import json
env = json.loads('''$CUR''')
env['DEPLOY_VERSION'] = '2.74.6'
print(json.dumps({'Variables': env}))")
aws lambda update-function-configuration --function-name life-platform-mcp \
  --environment "$ENV_PAYLOAD" --region us-west-2 --query LastModified --output text

# (4) From claude.ai:
#       manage_hevy_routine action=draft target_date=2026-06-02
#       manage_hevy_routine action=dry_run routine_id=<id>
#     Inspect wire_body.routine.exercises[*].notes — populated lifts get
#     "Last: 60kg 8/8/7 (24 May)"-style cues; lifts with no SOURCE#hevy
#     history get empty notes.
```
