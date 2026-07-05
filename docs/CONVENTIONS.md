# CONVENTIONS — the load-bearing reflexes

The single canonical home for the hard-won operational reflexes that keep a deploy
from silently regressing production. Each one was learned from a real incident. When
a rule here changes, it changes **here** — the project brief (`CLAUDE.md`) and the
memory index point at this page rather than restating it, so a rule can't rot in one
copy while another stays stale (the failure mode that motivated this page: a durable
fact — the shared-layer version — drifted because it was hand-written in prose in two
places instead of read from one source).

**The meta-rule:** a fact that drifts (a version, a count) never appears here as a
hand-typed literal — only as the command that discovers it, or a value a tool keeps in
sync. See [Facts that drift](#facts-that-drift-run-the-command-never-quote-a-number).

---

## 1. Shared-layer rebuild + deploy sequence

Publishing a shared-layer change (a `SHARED_LAYER_VERSION` bump in
`cdk/stacks/constants.py`) has a specific, non-obvious order. Getting it wrong fails
the deploy with `Layer version arn:...:N does not exist`.

- `bash deploy/build_layer.sh` **only builds** `cdk/layer-build/python/` — it does
  **not** publish to AWS. The live version is unchanged after it runs.
- `cdk deploy LifePlatformCore` is what **publishes** the new version (`core_stack.py`
  owns the `LayerVersion(Code.from_asset("layer-build"))` construct). Deploying any
  layer-*consuming* stack before Core fails.
- Run `cdk` from **inside `cdk/`** — `from_asset("layer-build")` resolves relative to
  the cwd; from the repo root it errors `CannotFindAsset`.

**Correct order:**
```bash
bash deploy/build_layer.sh
cd cdk && npx cdk deploy LifePlatformCore
# verify the new version is live BEFORE deploying consumers:
aws lambda list-layer-versions --layer-name life-platform-shared-utils \
  --region us-west-2 --query 'LayerVersions[0].Version'
npx cdk deploy <consuming stacks>
```
Deploys are run by Matthew in his terminal, never via MCP. Source: the ER-01 layer
deploy (`feedback_layer_deploy_sequence`).

## 2. Deploy from `main`, not the worktree branch

`cdk deploy` and the `deploy/*.sh` scripts package the **current working tree**, not
`origin/main`. In the worktree each PR is built on its own branch forked off main
*before* its siblings merged — so that branch's tree is missing every other PR's
changes.

- **The tell:** `cdk diff` shows **0 differences** (or a diff that doesn't mention the
  change you shipped) when you expected one → you're deploying the wrong tree.
- **The fix:** before deploying merged work,
  ```bash
  git fetch && git checkout origin/main   # detached HEAD is fine for deploying
  ```
  so the tree == what's on main, re-verify each fix is present (`grep` / `test -f`),
  then deploy.

Same reflex as §3: **read the diff; if it doesn't show what you shipped, stop.**
Source: 2026-06-30 audit Tier-0 (`reference_deploy_from_main_not_worktree_branch`).

**This reflex is now enforced, not just documented** — §6 automates exactly this
check (plus its mirror-image: live code that outran the last `cdk deploy`).

## 3. Squash-merge drops unpushed commits — verify before merge, `cdk diff` before deploy

A squash captures whatever is on the **remote PR branch** at merge time, not the local
worktree HEAD. Unpushed local commits vanish from history even though their built
output may already be live — leaving `main` both behind production and red.

- **Before squash-merging** a long-running branch (especially after deploying from the
  worktree): `git log --oneline origin/<branch>..HEAD` must be empty (nothing local
  unpushed). After merge, spot-check `git cat-file -e origin/main:<a-late-file>`.
- **`cdk diff` before EVERY deploy, and READ it.** A `[-]` / `destroy` of a resource
  you didn't touch means **main is behind live** — deploying would silently revert a
  working feature (this is how the dropped `ChronicleApproveSchedule` rule was caught,
  2026-06-29).
- **Never trust "main == live"** after a squash-heavy session. Verify the dangerous
  part: `git diff --stat origin/main..<live-branch> -- lambdas/ cdk/` (site/docs drift
  is cosmetic; lambda/cdk drift regresses on deploy).
- **Reconcile without replaying commits:**
  `git reset --hard origin/main && git checkout <localtip> -- . && git commit` (the net
  working-tree delta as one commit).

Source: #216, then the 2026-06-29 recurrence (`feedback_squash_merge_drops_unpushed_commits`).

## 4. CI gate ordering — a red gate masks the ones after it

CI's `Lint + Syntax Check` job runs its gates **sequentially**:
`flake8 (enforced subset) → black → ruff → mypy → py_compile`. A failure at one step
stops the job, so later gates never run and their violations accumulate silently. The
`Unit Tests` job `needs` Lint, so a **red Lint skips the entire test suite**. One
unformatted file can therefore mask weeks of ruff/mypy/test debt that surface in layers
as you fix upward — expect to peel several layers, re-checking the next gate after each
fix.

**Run the exact gates before pushing** (over `lambdas/ mcp/ cdk/ tests/ scripts/ deploy/`):
```bash
black --check .
python3 -m ruff check .
python3 -m pytest tests/test_mypy_clean_modules.py     # the mypy-clean module set
```
CI pins specific tool versions — read them from CI rather than quoting here
(`grep -E 'black==|ruff==|mypy==' .github/workflows/ci-cd.yml requirements-dev.txt`).
Note `requirements-dev.txt` can drift from the CI pin; match the **CI** version when
they disagree.

**CI-parity test runs need FAKE creds, not absent ones.** CI's runner has no valid AWS
credentials, but `env -u` alone lets boto3 fall back to the `[default]` profile and
silently query prod. Present-but-invalid beats absent:
```bash
env -u AWS_PROFILE -u AWS_SESSION_TOKEN AWS_ACCESS_KEY_ID=FAKEKEY AWS_SECRET_ACCESS_KEY=FAKESECRET \
  python3 -m pytest tests/ -q --ignore=tests/test_integration_aws.py
```
(Never set `AWS_PROFILE=` empty — boto3 raises `ProfileNotFound`; always `env -u`.)
Source: `reference_ci_masking_and_creds`.

## 5. The CDK asset-staging trap — a 200 invoke is not proof of a good deploy

A `cdk deploy` can publish a `Code.from_asset` Lambda zip that is **missing every
root-level `lambdas/*.py` module** (only subdirectory modules make it in). The function
then dies at cold start with `Runtime.ImportModuleError`, but **the invoke still returns
StatusCode 200** (a `FunctionError` payload with `errorMessage`, no `body`) — so it
looks healthy from the outside and can run "green" off a stale S3 artifact.

- **Tells:** invoke returns 200 but the payload has `errorMessage`/`errorType`, not
  `body`; the persisted artifact's S3 `LastModified` stops advancing; `unzip -l` of the
  downloaded `Code.Location` shows root `*.py` missing (a broken zip is ~7 KB / 2
  entries vs ~1.2 MB full).
- **It is reproducible.** The mechanism: CDK skips re-uploading an asset whose
  content-hash already exists in the assets bucket, so a corrupt `<hash>.zip` poisons
  every lambda referencing that hash. `cdk deploy` says "(no changes)"; `--force`
  doesn't fix it; `rm -rf cdk.out` alone may re-synth the same hash.
- **What fixes it:** overwrite the S3 object with a correct build, then point the
  function at it —
  `aws lambda update-function-code --function-name <fn> --s3-bucket cdk-hnb659fds-assets-<acct>-<region> --s3-key <hash>.zip`
  (bucket/key are in `cdk.out/<Stack>.assets.json`).
- **Detection is automated:** `deploy/session_postflight.py::check_asset_completeness()`
  downloads each bundled-asset canary's deployed zip and asserts its root modules import.

Source: 2026-06-28 Coherence-Sentinel breakage (`reference_cdk_asset_staging_glitch`).

## 6. Guard the dual deployment planes — checkout freshness + live-code drift (#382)

Some function code intentionally ships via `deploy/deploy_lambda.sh` (a direct
`update-function-code` push — see §5's "for speed" narrative-lambda note in
`docs/SITE_UPLEVEL_PLAYBOOK.md`), while the CDK stacks in `cdk/stacks/` still own
those same functions' full definition. That split bites in **both** directions:

- **Stale checkout (§2/§3's failure mode, now enforced):** deploying a stack from a
  checkout that's missing `lambdas/`/`cdk/`/`mcp/` commits already on `origin/main`
  reasserts OLD code over a live fix.
- **Live code drift (the mirror image):** a function was updated directly via
  `deploy_lambda.sh` (or a console edit) since the LAST `cdk deploy` of its owning
  stack. A blind `cdk deploy --all` would push the stack's older asset back over the
  newer, directly-pushed code.

**The guarded path (use this instead of a bare `cdk deploy`):**
```bash
bash deploy/cdk_deploy.sh <StackName> [<StackName> ...] [-- <extra cdk args>]
```
This runs `deploy/check_deploy_drift.py` first — a git-only checkout-freshness check
(mirrors `sync_site_to_s3.sh`'s clobber guard exactly: `git rev-list --count
HEAD..origin/main -- lambdas/ cdk/ mcp/`) plus, when stack names are given, a
read-only `detect_stack_drift` scoped to those stacks that flags any
`AWS::Lambda::Function` whose live `Code` property has diverged from the template —
then execs the real `npx cdk deploy`. Either check can be overridden for an
intentional case (same UX as `ALLOW_STALE_SITE=1`): `ALLOW_STALE_DEPLOY_CHECKOUT=1`
/ `ALLOW_LIVE_LAMBDA_DRIFT=1`, or `--allow-stale-checkout` / `--allow-live-drift`.

Run the guard standalone (no deploy) with `python3 deploy/check_deploy_drift.py
[StackName ...]`; omit stack names to run the checkout check only (git, offline,
no AWS creds needed). Both checks are fail-soft on transient errors (offline fetch,
a `DETECTION_FAILED` drift poll) — they report `unknown`/`error`, never crash or
false-block on infra flakiness. Tests (a real ephemeral git repo for the checkout
check, a fake CFN client for the drift check): `tests/test_check_deploy_drift.py`.

Source: #382 (epic #342, "live infra matches code").

---

## Facts that drift: run the command, never quote a number

These values change and must **never** be hand-written in docs or memory. Read them:

| Fact | Source of truth (run this) |
|---|---|
| Shared-layer version | `aws lambda list-layer-versions --layer-name life-platform-shared-utils --region us-west-2 --query 'LayerVersions[0].Version'` (and the `SHARED_LAYER_VERSION` constant in `cdk/stacks/constants.py`) |
| Lambda count | `python3 deploy/sync_doc_metadata.py` (AST-discovers; syncs `PLATFORM_STATS` + doc headers) |
| MCP tool count | `deploy/sync_doc_metadata.py::_auto_discover_tool_count` — the top-level keys in `TOOLS` in `mcp/registry.py`. **Do not** `grep -c '"name":'` — it over-counts nested schema fields |
| Test count | `PLATFORM_STATS["test_count"]` in `lambdas/web/site_api_common.py`, auto-bumped by the sync + the pre-commit hook |
| Live site build | `curl -s https://averagejoematt.com/version.json` → compare `build` to `git rev-parse --short HEAD`; a mismatch means the viewer's device is stale |

The pre-commit hook runs `deploy/sync_doc_metadata.py --apply`, which may leave files
unstaged — fold them into the commit (`git add … && git commit --amend --no-edit
--no-verify`) or `test_platform_stats_truth.py` reds CI.

---

*This page is the canonical home for these reflexes. If you find a rule stated
differently anywhere else, that copy is stale — fix it to a one-line pointer here.
The originating memory files (`reference_*` / `feedback_*`) carry the full incident
narrative; this page carries the rule.*
