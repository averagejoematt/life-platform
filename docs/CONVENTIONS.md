# CONVENTIONS — the load-bearing reflexes

> **Status:** canonical · **Owner:** Matthew · **Verified:** 2026-07-18

The single canonical home for the hard-won operational reflexes that keep a deploy
from silently regressing production. Each one was learned from a real incident. When
a rule here changes, it changes **here** — the project brief (`CLAUDE.md`) and the
memory index point at this page rather than restating it, so a rule can't rot in one
copy while another stays stale (the failure mode that motivated this page: a durable
fact — the version of the since-retired shared layer — drifted because it was
hand-written in prose in two places instead of read from one source).

**The meta-rule:** a fact that drifts (a version, a count) never appears here as a
hand-typed literal — only as the command that discovers it, or a value a tool keeps in
sync. See [Facts that drift](#facts-that-drift-run-the-command-never-quote-a-number).

---

## 1. The ONE code bundle — no shared layer (#781)

The shared layer (`life-platform-shared-utils`) was **retired 2026-07-06** (#781,
ended at v118). Shared modules ship **inside every function's code bundle**, staged
by the single implementation `deploy/build_bundle.py` (the whole `lambdas/` tree +
`config/food_vocabulary.json`; MCP additionally gets `mcp_server.py` + `mcp/`).
Every deploy path uses it — CDK (`lambda_helpers.staged_tree_asset()`),
`deploy_lambda.sh`, `deploy_fleet.sh`, `deploy_site_api.sh` — so what any path
ships is byte-identical by construction.

- **A shared-module change reaches the fleet** via `bash deploy/deploy_fleet.sh`
  (one bundle → S3 → every function) or `cd cdk && npx cdk deploy --all`. CI does
  this automatically: any changed `lambdas/` file that is not a mapped
  per-function source triggers the fleet-deploy step.
- **The invariant** (enforced by CI's plan job + `test_i2_shared_layer_retired` +
  `session_postflight`): **zero** functions reference `life-platform-shared-utils`.
  A function referencing it predates the collapse (redeploy its stack) or a
  regression re-attached it.
- Dependency layers with real third-party packages (**garth**, **pillow**) are
  NOT the shared layer — they stay.
- The retired incident classes this replaces (stale-layer P2, #697
  missing-from-allowlist, single-file-deploy-strips-siblings, MCP zip missing
  `reading/`): see git history of this section + `docs/DECISIONS.md`.

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

**The public site is now structurally exempt from this failure mode (#750):** a push
to `main` touching `site/**` deploys the MERGED main tree automatically via
`.github/workflows/site-deploy.yml` (OIDC deploy role → `deploy/deploy_site.sh` →
`sync_site_to_s3.sh` + the explicit fonts sync), then gates it with
`smoke_test_site.sh` + the visual/AI-QA sweep and auto-rolls-back via
`deploy/rollback_site.sh HEAD~1` on a red — with SNS alerts either way. There is
deliberately NO production-approval gate on that workflow (merged-but-not-deployed
was the drift class itself). Manual `sync_site_to_s3.sh` remains sanctioned for
attended work (its clobber guard still protects a stale checkout), but merge-to-main
is the default ship path for the site.

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

## 4. CI gate ordering — one job, independently-reporting gates

CI's `Lint + Syntax Check` job runs its gates in order —
`flake8 (enforced subset) → black → ruff → mypy → py_compile → lambda_map coverage →
content-policy → doc-drift` — but since #749 every gate after flake8 carries
`if: always()`, so **each gate runs and reports even when an earlier one is red**: one
push surfaces ALL violations at once. (Before #749 the steps were strictly sequential —
the first red stopped the job and MASKED every later gate, so debt surfaced in layers,
one push per layer. That masked-gate class bit twice on 2026-07-08 alone.) Gating is
unchanged: any red gate still fails the Lint job, and `test-critical` (→ `plan` →
`deploy`) `needs` Lint, so a **red Lint still blocks the deploy chain** — it just no
longer hides the other gates' findings. NB: `always()` steps also run after a
cancellation; with `cancel-in-progress: false` that only happens on a manual cancel.

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

**The CDK toolchain is pinned both directions too (#814, R22-MOD-01).** Before this
fix, `ci-cd.yml`'s `npm install -g aws-cdk` had no version (always latest CLI) and
`cdk/requirements.txt` was floor-only (`aws-cdk-lib>=X`), so a fresh CI install could
silently pick up an untested CDK release and red a routine push. Both are now exact
pins — `grep -E 'aws-cdk@|aws-cdk-lib==|constructs==' .github/workflows/ci-cd.yml
cdk/requirements.txt requirements-dev.txt`. Bump the CLI pin, `cdk/requirements.txt`,
and `requirements-dev.txt` together as one deliberate PR (Dependabot proposes the
`cdk/requirements.txt` half; the CLI pin in `ci-cd.yml` is manual).

**CI-parity test runs need FAKE creds, not absent ones.** CI's runner has no valid AWS
credentials, but `env -u` alone lets boto3 fall back to the `[default]` profile and
silently query prod. Present-but-invalid beats absent:
```bash
env -u AWS_PROFILE -u AWS_SESSION_TOKEN AWS_ACCESS_KEY_ID=FAKEKEY AWS_SECRET_ACCESS_KEY=FAKESECRET \
  python3 -m pytest tests/ -q --ignore=tests/test_integration_aws.py
```
(Never set `AWS_PROFILE=` empty — boto3 raises `ProfileNotFound`; always `env -u`.)
Source: `reference_ci_masking_and_creds`.

### 4a. The deploy-critical test lane — what gates the deploy (#416, ADR-117)

Since ADR-117, `plan` (and therefore `deploy` + the reader-facing visual-QA gate)
depends on the **`test-critical`** job — a fast, fully-offline pytest subset — **not**
the exhaustive `test` suite. The full suite still runs on every push (job `test`,
parallel), still reds main, and still fires `notify-failure`; it just no longer skips
the deploy chain. The subset is selected by the **`deploy_critical`** pytest marker
(registered in `pytest.ini`) and run as `pytest -m "deploy_critical and not integration"`.

**Inclusion criterion (apply it deliberately — don't let the lane rot):** a test is
`deploy_critical` **iff its failure means the deploy artifact or its wiring is broken,
or a core honesty/safety contract the running system depends on is violated** — i.e. it
validates the *deploy contract*, not product/data correctness or AI narrative quality.

**In the lane** (module-level `pytestmark = pytest.mark.deploy_critical`):

| File | What it guards |
|------|----------------|
| `test_wiring_coverage.py` | every Lambda wires the required safety modules; every MCP tool registered |
| `test_mcp_registry.py` | MCP registry integrity |
| `test_role_policies.py` | static IAM policy correctness (KMS/secret scoping, no wildcards) |
| `test_iam_secrets_consistency.py` | IAM secret ARNs ↔ known-secrets list |
| `test_secret_references.py` | Lambda secret-name literals (Todoist-style outage guard) |
| `test_cdk_handler_consistency.py` | CDK handler names match source modules |
| `test_cdk_s3_paths.py` | CDK S3 path correctness |
| `test_ddb_patterns.py` | DynamoDB single-table access-pattern rules |
| `test_lambda_handlers.py` | handler existence / syntax / signature (I1–I6) |
| `test_lambda_map_imports.py` | mapped handlers' imports resolve inside the real build_bundle.py bundle; `cdk_only` annotations correlate with a genuine sibling dependency (I7–I8, #799) |
| `test_ai_output_faithfulness.py` | deterministic AI-output honesty gate (anti-fabrication / er03_gate wiring) |

**Deliberately excluded** (still run in the full suite, still red main, must **not** gate
deploy): statistical-rigor tests, narrative/AI-quality judgement, doc-drift, and
content/data-correctness. Adding a file to the lane = add `pytestmark =
pytest.mark.deploy_critical` **and** a row here; keep the two in sync. Confirm the lane
after any change: `python3 -m pytest tests/ -m "deploy_critical and not integration" -q`.

### 4b. Visual-QA fires independently of the pipeline (#749)

The reader-facing regression net (Playwright sweep + Bedrock vision QA + the accuracy
gate) exists in **three** places, and the deterministic sweep always covers the full
page set in all three — only the AI-vision layer is tiered (#1428, see below):

- **Pipeline copy** (`ci-cd.yml` job `visual-qa`, `needs: deploy`) — GATES the pipeline
  post-deploy for lambda/CDK deploys.
- **Site-deploy copy** (`site-deploy.yml` job `visual-qa`, `needs: deploy-site`) — GATES
  the auto-deploy-on-merge path for `site/**` changes; the site auto-rollback keys off
  either gating copy's failure.
- **Standalone copy** (`.github/workflows/visual-qa.yml`) — `workflow_dispatch` + daily
  20:07 UTC cron against the LIVE site. Gates nothing, rolls back nothing; a failure
  reds the run + posts to the SNS digest. This is what keeps the net firing when a
  gating copy is skipped (red upstream job, or a push with nothing to deploy).

**Tiered AI-vision cadence (#1428, cost control):** the Claude/Bedrock vision pass is
the expensive part (Haiku, ~$0.001/image); the deterministic Playwright checks are free
(CI minutes only) and are NEVER restricted by this.
- Both gating copies pass `--ai-qa-max-tier 1` — AI-vision covers exactly the 6 tier-1
  flagship doors (`tests/qa_manifest.py`) on every deploy.
- The standalone copy's full, untiered AI-vision pass (`--ai-qa`, no tier filter) fires
  only on the Sunday occurrence of its existing daily cron, or on any manual
  `workflow_dispatch` — no second cron was added; the flag is computed at runtime from
  UTC day-of-week (see the workflow's "Determine cadence" step). Non-Sunday daily fires
  still run the deterministic sweep + `--reader-truth` (both full surface, unaffected).
- Budget-tier pauses on the AI-vision pass (`budget_guard` feature `"visual_ai_qa"`,
  internal-QA band, cutoff tier 1) render as an explicit SKIPPED-BY-BUDGET line + the
  `QAPausedByBudget` CloudWatch metric — never a silent skip (D1, mirrors #1440's
  `reader_truth_qa` pattern).

**The QA-depth dial (#1452):** SSM `/life-platform/qa-level` (`full|standard|lean|off`)
scales the NON-gating copies only — the standalone daily run and the weekly WebKit
advisory read it (fail-open to `standard` when unreadable, stated in the run log). The
gating copies (and the PR gates `v4-gate.yml`/`surface-drift.yml`) are **structurally
exempt**: they must never reference the parameter, so the deploy gate can never be
disabled by the dial (`tests/test_qa_level_dial.py` enforces both sides). Dial state
surfaces in the Monday green report and in `/qa` + `scripts/qa_audit.py --live`.
Full semantics: `docs/RUNBOOK.md` § QA Depth Dial.

All three step lists must stay in sync — change one, change all three. Run it on demand:
`gh workflow run visual-qa.yml` (or locally `python3 tests/visual_qa.py --screenshot --ai-qa`,
add `--ai-qa-max-tier 1` to reproduce exactly what the deploy-time gates run).

### 4c. Merge-day derived-artifact drift auto-reconciles on main (#1173)

Concurrent PRs each commit **generator output** (doc-sync literals in
`lambdas/web/site_api_common.py` + doc headers, `site/method/game/index.html`,
`site/assets/js/portrait_data.js`, `site/data/data_sources.json`, the ADR index in
`docs/DECISIONS.md`, the shared chrome block). A PR branched before a sibling's merge
regenerated one of those asserts staleness *after its own squash-merge* — that was the
last recurring red class on merge-queue days. Since #1173, `ci-cd.yml`'s **`reconcile`
job** (Job 0, main pushes only) reruns the enumerated generators on the merged tree
and, when dirty, pushes a `chore(reconcile): … [skip-reconcile]` bot commit; the whole
run then lints/tests/deploys that reconciled sha (`needs.reconcile.outputs.build_sha`).
Only the generator-output **whitelist** may be auto-committed — any other dirty path
fails the job with no commit. The manual `/reconcile-branch` merge-queue ritual is
still valid; the bot is the net under it, not a replacement for pre-merge hygiene.

**When the reconcile job itself reds, check in this order:**
1. **Non-whitelisted dirty path** — a generator wrote outside its declared output.
   Do NOT widen the whitelist reflexively; inspect the generator diff, fix main
   manually (`git pull` → run the generator → review → push).
2. **Push rejected** — as of 2026-07-13 (#1173) "Require a pull request before
   merging" was turned OFF on `main` entirely
   (`gh api -X DELETE repos/<owner>/<repo>/branches/main/protection/required_pull_request_reviews`),
   and classic branch protection on `main` is now **absent** —
   `gh api repos/<owner>/<repo>/branches/main/protection` returns 404
   "Branch not protected" (verified live, not residual). The only control on
   `main` is the minimal **ruleset** added 2026-07-18 (#1325,
   `main-block-force-push-and-deletion`, id `19162901`) — it blocks
   **non-fast-forward pushes and branch deletion only**: no required checks, no
   PR rule, `enforcement: active`, `bypass_actors: []`. A normal (fast-forward,
   non-deleting) push from `github-actions[bot]` — including the reconcile bot's
   commit and a squash-merge — is unaffected; only a force-push or a delete of
   `main` is rejected. If the reconcile push is ever rejected, it means someone
   force-pushed or the ruleset was misconfigured — check
   `gh api repos/<owner>/<repo>/rulesets/19162901` before assuming a PR-gate
   problem (there isn't one).
3. **A generator crashed** — same failure the test suite would have shown; fix the
   generator like any red test. Reproduce locally: run the generators from repo root
   on a clean main checkout; `git status` must end clean (they are idempotent).

Two gotchas the design already absorbs — don't "fix" them back in: GITHUB_TOKEN pushes
never retrigger `push` workflows (that's the loop protection), so the job explicitly
dispatches `site-deploy.yml` when the reconcile commit touches `site/**` (otherwise the
regenerated page would be merged-but-not-deployed); and `plan` diffs from
`${GITHUB_SHA}~1` to the reconciled HEAD, so the merged PR's own changes stay in the
deploy plan even with a reconcile commit stacked on top.

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

## 7. Hard-won repo gotchas (each one is a past incident)

- **Lambda Function URLs are payload format 2.0** — request cookies arrive in
  `event["cookies"]` (a top-level array), not in headers; responses set cookies via a
  top-level `cookies` array, not a `Set-Cookie` header.
- **`mcp/core.py`: the name `secrets` is a boto3 Secrets Manager client**, NOT the
  stdlib module — use `uuid.uuid4().hex` (the repo's opaque-token idiom) for token
  generation there.
- **ruff bandit S105 fires on token-prefix string constants** (a label, not a secret) —
  use a surgical `# noqa: S105` in `mcp/core.py`; `mcp/handler.py` is already exempt
  via pyproject config.
- **Never run `black` on `.json` files** — it "formats" valid JSON into a Python dict
  with trailing commas (= invalid JSON). Re-run tests after ANY post-test formatting.
- **A golden-test fixture date used in now-minus-date math is a time bomb** — it flips
  red as wall-clock time passes (the daily-brief golden flipped at n=30); pin fixture
  dates far in the past.
- **macOS paths are case-insensitive** — a lowercase path twin
  (`/Users/…/documents/claude/…`) can silently leak a parallel agent's edits into the
  shared main tree; always operate through the canonical-case worktree path.
- **`git stash` is ONE stack shared across all worktrees** — parallel agents have raced
  stash/pop and swapped each other's trees; never stash in concurrent sessions
  (recovery: the dropped-stash SHA).

---

## 8. The wiki stays true — the four-layer contract

The engineering wiki is `docs/` (home: `docs/README.md`). Its accuracy is machinery,
not diligence. The bar: **a human team could run the platform from these pages with the
AI powered down.** Four layers, each with a named owner-mechanism:

1. **Generated facts.** Counts/versions are never hand-typed in canonical pages —
   `deploy/sync_doc_metadata.py` AST-discovers them and `--check` fails CI on drift,
   including when a sync RULE itself stops matching (the silent-no-op class that let
   "133 tools" outlive the #395 prune). Fully generated pages: `MCP_TOOL_CATALOG.md`
   (`scripts/generate_mcp_tool_catalog.py`) and the ADR index in `DECISIONS.md`
   (`scripts/generate_adr_index.py --apply` after every new ADR).
2. **Mechanical CI lint** — `docs-ci.yml` on every docs push + the same gates in
   ci-cd.yml's Lint job for code pushes:
   - `scripts/check_doc_links.py` — every relative link/anchor resolves;
   - `scripts/check_doc_tombstones.py` + `docs/_lint/tombstones.txt` — no live page
     **or `lambdas/`+`mcp/` docstring** references a retired concept. **Retiring
     something = adding its tombstone rule in the same PR** (that's the generalized #781
     lesson — the source scan was added 2026-07-13 because #781 retired the layer yet
     left 35+ stale "part of the ... layer" claims in code the docs-only scan never opened);
   - `scripts/check_doc_facts.py` — the **generalized stale-number net**: it knows the
     ground-truth counts (imported from `sync_doc_metadata`'s discoverers) and fails on a
     stale count/budget stated in ANY phrasing, not just the exact ones the sync RULES
     target. This is what catches the un-ruled-phrasing class (`**Tools:** 127` drifting
     while the ruled header said 64). Precision-first: a false-positive gate gets disabled,
     so it is deliberately narrow (forward-only, glue-guarded, ledgers exempt);
   - `scripts/check_doc_index.py` — every page is indexed from the wiki home, carries
     the status header, the >90d advisory freshness report, and a **blocking 180d ceiling**
     (a canonical page unverified that long fails CI).
3. **Process gates.** The wrap skill's step (e) is a hard gate — every session ends
   with `**Docs:** <pages>` or `**Docs:** none needed — <reason>` in the handover,
   checkers green. The deploy skill prompts the same at deploy time. (A PR-time
   "Docs impact" checklist asking the same thing had lived in the retired PR
   template — 0/20 recent merged PRs used it, #1324 — but the wrap-skill gate above
   was already the mechanism actually enforcing this.)
4. **Periodic verification.** Each canonical page's `> **Status:** … · **Verified:**`
   header records when a human/agent last verified its content against reality; the
   freshness report is the re-verification worklist. `/accuracy-review` is the deep pass.

**Adding a page:** flat in `docs/` if canonical (`specs/` dated spec, `archive/`
superseded) → status header → one line in `docs/README.md` → checkers green. That is
the entire process; anything more wouldn't get followed.

### 8a. Eradicating a wrong fact — the corpus-wide ritual (#1347)

**The failure mode:** #1254 (2026-07-18) fixed the claim that the cost-governor "runs
hourly" <!-- drift-ok: quoting the #1254 incident this ritual generalizes from, not a live claim --> (true cadence: every 8h) on the 3 files its author happened to grep,
guarded by a test that hardcoded those 3 literal paths. The same wrong fact was live
in 2 more files (`docs/RUNBOOK.md`, `docs/ARCHITECTURE.md`) *the same day the fix
merged* — the enumerated-file test structurally cannot see a copy it didn't
enumerate, so "fixed" was true only at the 3 spots someone happened to look. #781 hit
the identical shape a month earlier: the retired shared layer's old name survived as
"shared-layer" (hyphen) and "Shared-layer" (capitalized, retired-concept name
unchanged) — spellings the fix's own regex never tried.

**The ritual, every time a wrong fact needs killing:**

1. **Grep every phrasing before you fix anything** — `docs/` + `site/` + `lambdas/` +
   `mcp/`, not just the file(s) where you first spotted it. Try the hyphen, the
   underscore, the space, and the capitalized-sentence-initial form; a compound term
   is not one string, it's a small family of strings. `grep -rniE` across all four
   trees, read every hit, decide fix-vs-legitimately-historical for each.
2. **Add (or harden) a GATE rule that matches the *pattern*, not the literal
   locations** — `docs/_lint/tombstones.txt` for a retired-concept claim,
   `scripts/check_doc_facts.py`'s proximity-scan shape (name-token + wrong-value-token
   co-occurring on one line, ground-truthed from the same discoverer the rest of the
   file uses, HISTORICAL-exempt) for a stale number/cadence/claim. **Never write a
   test that hardcodes the N files you found** — enumeration is exactly the shape that
   fails silently one file over. A rule earns its keep only by proof of two things:
   it FLAGS a planted instance of the wrong phrasing (the #1189 non-vacuous-scan
   lesson) and it stays QUIET on legitimate history (HISTORICAL framing, ledgers,
   archives) — every scan in `check_doc_facts.py` and `check_doc_tombstones.py`
   carries a paired `_is_not_vacuous` test proving both.
3. **Fix every real hit the hardened rule surfaces**, not just the ones you already
   knew about — the whole point is that the corpus-wide grep in step 1 and the
   generalized rule in step 2 usually find MORE than the triggering report did.
4. **Run the hardened gate on the pre-fix tree and show it RED** before committing
   the fix — that's the proof the rule would have caught the original defect, not
   just a plausible-looking regex.

---

## Facts that drift: run the command, never quote a number

These values change and must **never** be hand-written in docs or memory. Read them:

| Fact | Source of truth (run this) |
|---|---|
| Layer-retirement invariant (#781) | `aws lambda list-functions --region us-west-2 --query "Functions[?Layers[?contains(Arn, 'life-platform-shared-utils')]].FunctionName"` → must be `[]` (the layer is retired; there is no version to quote) |
| Lambda count | `python3 deploy/sync_doc_metadata.py` (AST-discovers; syncs `PLATFORM_STATS` + doc headers) |
| MCP tool count | `deploy/sync_doc_metadata.py::_auto_discover_tool_count` — the top-level keys in `TOOLS` in `mcp/registry.py`. **Do not** `grep -c '"name":'` — it over-counts nested schema fields |
| Test count | `PLATFORM_STATS["test_count"]` in `lambdas/web/site_api_common.py`, auto-bumped by the sync + the pre-commit hook |
| Live site build | `curl -s https://averagejoematt.com/version.json` → compare `build` to `git rev-parse --short HEAD`; a mismatch means the viewer's device is stale |
| `main` classic branch protection | `gh api repos/<owner>/<repo>/branches/main/protection` → must 404 "Branch not protected" (removed 2026-07-13, #1173; a 200 here means protection was re-added out of band — reconcile the doc, don't assume this table is wrong) |
| `main` ruleset posture | `gh api repos/<owner>/<repo>/rulesets` → must show exactly `main-block-force-push-and-deletion` (id `19162901`) with `rules: [deletion, non_fast_forward]` only, `enforcement: active`, no `pull_request`/`required_status_checks` rule (#1325). Full record: `gh api repos/<owner>/<repo>/rulesets/19162901` |

The pre-commit hook (`scripts/install_hooks.sh` — run once after cloning) runs
`deploy/sync_doc_metadata.py --apply` directly and auto-stages every target file it
touches (`docs/`, `CLAUDE.md`, `.claude/README.md`,
`lambdas/web/site_api_common.py`). If you run the script by hand outside a commit
(or add a new doc to its `RULES` table that falls outside that stage glob), fold
the changes into the commit yourself (`git add … && git commit --amend --no-edit
--no-verify`) or `test_platform_stats_truth.py` reds CI.

---

*This page is the canonical home for these reflexes. If you find a rule stated
differently anywhere else, that copy is stale — fix it to a one-line pointer here.
The originating memory files (`reference_*` / `feedback_*`) carry the full incident
narrative; this page carries the rule.*
