# CONVENTIONS — the load-bearing reflexes

> **Status:** canonical · **Owner:** Matthew · **Verified:** 2026-08-08

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

### 1a. Every bundle carries its commit — and deploys refuse to go backwards (#2377)

`build_bundle.py` stages **`build_info.json`** (`{git_sha, git_short_sha, built_at,
dirty, builder}`) at the root of every bundle, both shapes, every path. The sha
resolves `BUNDLE_GIT_SHA` → `GITHUB_SHA` → `git rev-parse HEAD`, and is `null`
(honest) rather than absent when there is no checkout.

Why: a `LastModified` timestamp only proves *a* deploy happened. On 2026-08-08 an
older CI run deployed **after** a newer merge, and nothing refused or even detected
it — `verify_deployed_symbol.sh` could only answer "is this symbol live?", which
requires already knowing which symbol to look for.

- **The gate:** `bash deploy/verify_bundle_ancestry.sh <fn> [preflight|postflight]`
  pulls the live bundle, reads its `build_info.json`, and classifies via
  `deploy/bundle_ancestry.py`: `same` / `fast_forward` → OK; **`stale`** (the tree
  you are shipping is an *ancestor* of what is live — the 08-08 race) and
  **`diverged`** → **exit 2, deploy refused**; `unknown` (no fingerprint on one
  side, or git can't resolve a sha) → loud warning, allowed.
- **Wired into** `deploy_lambda.sh` (preflight + postflight), `deploy_fleet.sh`
  (one probe preflight before the first update — the fleet ships one identical
  bundle, so one probe answers for all of them — plus a postflight) and
  `deploy_site_api.sh`.
- **Postflight is stricter than preflight:** what is live afterwards must *be* the
  sha you shipped, not merely a descendant. A descendant means someone else's
  deploy landed on top of yours.
- **Escape hatches:** `ALLOW_NON_FAST_FORWARD=1` (deliberate rollback — shipping
  older code on purpose), `SKIP_ANCESTRY_CHECK=1` (break-glass). AWS/network
  failure is fail-soft: it prints an unverified line and allows.
- **Cost:** the sha is in the bundle, so the **CDK asset hash now changes per
  commit** — a `cdk deploy` re-uploads code even when `lambdas/` is untouched.
  Deliberate: §2's "unexpected 0-diff" tell is replaced by a stronger one, an
  explicit sha comparison the deploy path performs for you.

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
content-policy` — but since #749 every gate after flake8 carries
`if: always()`, so **each gate runs and reports even when an earlier one is red**: one
push surfaces ALL violations at once. (Before #749 the steps were strictly sequential —
the first red stopped the job and MASKED every later gate, so debt surfaced in layers,
one push per layer. That masked-gate class bit twice on 2026-07-08 alone.) Gating is
unchanged: any red gate still fails the Lint job, and `test-critical` (→ `plan` →
`deploy`) `needs` Lint, so a **red Lint still blocks the deploy chain** — it just no
longer hides the other gates' findings. NB: `always()` steps also run after a
cancellation; with `cancel-in-progress: false` that only happens on a manual cancel.

**The doc/wiki gates are NOT in this job — they live in `Docs CI` (#1908).**
`sync_doc_metadata --check`, `check_doc_links`, `check_doc_tombstones`, `check_doc_facts`,
`check_doc_index --strict` and `generate_adr_index --check` used to run here *as well as*
in `docs-ci.yml`. That duplication was one-way-broken: a gate could fail inside CI/CD, but
the fix for any of them is a **docs edit**, and `docs/**` is not in `ci-cd.yml`'s path
filter — so the fix could not re-run the workflow it fixed. `check_main_green.py` reads the
**CI/CD workflow only**, so main kept reporting the stale failure until someone ran a manual
`workflow_dispatch`, which also runs Plan → Deploy and therefore charged a *documentation*
fix a production approval. It fired three times in three days (#1900, #1906, #1914).
`docs-ci.yml` now owns them outright and triggers on **both** halves of the doc↔source
coupling (`docs/**` plus `lambdas/** mcp/** config/** cdk/** tests/**`), so code-push
coverage is unchanged — the gate simply lives where its fix can clear it. Two traps to
respect there: `docs-ci.yml` must keep **`fetch-depth: 0`** (on a shallow clone
`check_doc_index.py` *silently skips* the #973 engine-doc drift gate and reports a green it
did not earn — that was live until #1908), and its `push`/`pull_request` path lists are
duplicated by hand because GitHub Actions has no YAML anchors.
`tests/test_docs_ci_owns_doc_gates.py` enforces all of it.

**Run the exact gates before pushing** (over `lambdas/ mcp/ cdk/ tests/ scripts/ deploy/`):
```bash
black --check .
python3 -m ruff check .
python3 -m pytest tests/test_mypy_clean_modules.py     # the mypy-clean module set
```
CI pins specific tool versions — read them from CI rather than quoting here
(`grep -E 'black==|ruff==|mypy==' .github/workflows/*.yml requirements-dev.txt`).
Grep the **whole workflows directory**, not one file: the #1655 extraction moved the
lint pins out of `ci-cd.yml` into `ci-lint.yml`, and a single-file grep silently shows
only the `requirements-dev.txt` half — exactly the half the next sentence tells you
not to trust. Note `requirements-dev.txt` can drift from the CI pin; match the **CI**
version when they disagree. (`tests/test_ci_pin_consistency.py` runs this command
verbatim from this page and reds if it stops surfacing the CI-side pins, so a future
workflow reshuffle can't blind it again.)

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

### 4a0. What gates the MERGE (#1662, ADR-148)

Distinct from §4a (which gates the *deploy*, on push to `main`). Two check-runs are
**required** on every PR to `main` by the `main-required-fast-lane` ruleset:
`Collect + deploy-critical + format` (`pr-checks.yml`) and
`gitleaks (PR commit range only, not full history)` (`secret-scan.yml`) — the only two
PR gates with no `paths:` filter and no job-level `if:`, so they report on every PR
class including docs-only. Everything else (full `Unit Tests`, `Lint + Syntax Check`,
CodeQL, visual QA, and the path-filtered gates) stays **advisory / post-merge**.
Auto-merge is on: arm the PR once, GitHub lands it when those two go green.

The trap to know: a required check matches by check-run *name*, and "never reported"
is not distinguishable from "failed". Adding a `paths:` filter to either workflow,
`if:`-gating its job, or renaming the job leaves PRs stuck on "Expected — Waiting for
status to be reported". `tests/test_branch_protection_spec.py` reds on exactly that.
Desired state: `deploy/github_posture.json`. Writer: `scripts/apply_branch_protection.py`
(`--check` to verify, `--apply` to fix). Never edit the ruleset in the GitHub UI.

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
   `main` is via **rulesets**, and there are two — check both before assuming a
   PR-gate problem:
   - `main-block-force-push-and-deletion` (id `19162901`, added 2026-07-18,
     #1325) blocks **non-fast-forward pushes and branch deletion only**: no
     required checks, no PR rule, `enforcement: active`, `bypass_actors: []`. A
     normal (fast-forward, non-deleting) push from `github-actions[bot]` —
     including the reconcile bot's commit and a squash-merge — is unaffected.
   - `main-required-fast-lane` (#1662, **ADR-148**, mechanism amended #2198)
     carries one `required_status_checks` rule scoped to the fast lane. A
     required-checks rule blocks **any** ref update whose head has no passing
     checks, including the reconcile bot's DIRECT push — which is why that
     ruleset carries a `bypass_actors` entry. **That entry is a `User` (the
     repo owner), not an `Integration`** — measured 2026-08-07 under two
     separate auths, a `github-actions` Integration bypass actor 422s on this
     personal-account-owned repo ("must be part of the ruleset source or owner
     organization"; `OrganizationAdmin` is documented as N/A off an org too). A
     `User` bypass only covers a push authenticated as that account, so
     `ci-cd.yml`'s reconcile job pushes with the `RECONCILE_PUSH_TOKEN` repo
     secret (a fine-grained PAT owned by the account, `Contents:
     read-and-write` on this repo only), falling back to `GITHUB_TOKEN` until
     that secret is provisioned. **If the reconcile push is rejected, check
     both first**: `gh api repos/<owner>/<repo>/rulesets --jq '.[] | {id,name}'`
     then read the full record for `bypass_actors`, and confirm
     `RECONCILE_PUSH_TOKEN` exists (`gh secret list`). Desired state is
     `deploy/github_posture.json`; re-assert with `python3
     scripts/apply_branch_protection.py --check` (and `--apply` to fix — it
     refuses to run until the secret is provisioned, so a stranding apply is
     structurally prevented). Full comparison of the rejected alternatives
     (classic protection, a fast-lane-PR reconcile) is in `docs/DECISIONS.md`'s
     ADR-148 amendment.
   Otherwise a rejected push means someone force-pushed.
3. **A generator crashed** — same failure the test suite would have shown; fix the
   generator like any red test. Reproduce locally: run the generators from repo root
   on a clean main checkout; `git status` must end clean (they are idempotent).

Two gotchas the design already absorbs — don't "fix" them back in: GITHUB_TOKEN pushes
never retrigger `push` workflows (that's the loop protection), so the job explicitly
dispatches `site-deploy.yml` when the reconcile commit touches `site/**` (otherwise the
regenerated page would be merged-but-not-deployed); and `plan` diffs from
`${GITHUB_SHA}~1` to the reconciled HEAD, so the merged PR's own changes stay in the
deploy plan even with a reconcile commit stacked on top.

### 4d. Stranded deploy states — the approval gate, the R8-ST6 Plan-red, the phantom wedge (#1901/#2052/#2590)

Three pipeline states leave main's deploy path wedged while nothing looks obviously
broken. `scripts/check_main_green.py` (the /wrap gate) classifies all three explicitly —
never re-diagnose them as ordinary red/green. States 4 and 5 are not wedges: they are the
two ways the *cure* for state 1 gets misread (#2590), and they belong here because that is
where an operator will be standing when they hit them.

1. **Stranded production approval.** A run that reaches the `production` approval gate
   and is never actioned sits at `status=waiting` indefinitely; because `ci-cd.yml`
   sets `concurrency: cancel-in-progress: false` (correct — a mid-flight deploy must
   complete), **every later run queues behind it** as `pending` with **0 jobs**. That
   presentation is byte-identical at a glance to the phantom-concurrency class
   (`reference_push_ci_silent_death`) — which has the OPPOSITE fix. **The
   distinguishing tell: phantom = 0 jobs AND no other run in the group; stranded
   gate = 0-job runs queued BEHIND an older run in `waiting`.** Check
   `gh run list --branch main` for a `waiting` run FIRST. Recovery splits on the
   holder's AGE (#2467): a **fresh** run (younger than ~24h,
   `STALE_GATE_REJECT_HOURS` in `check_deploy_wedge.py`) — action the gate,
   `bash deploy/approve_deployment.sh` (approve or reject, on Matthew's say-so). A
   **stale** one — **REJECT it immediately**: `bash deploy/reject_deployment.sh
   <run_id>` (`POST …/actions/runs/<id>/pending_deployments` with
   `state=rejected` — the run dies, nothing stale deploys, the slot frees). Never
   approve a stale run (it deploys the old sha it was minted from) and never leave
   one waiting: a Deploy parked at the gate OCCUPIES the job-level
   `ci-cd-deploy-<ref>` slot, so leave-waiting holds the whole fleet hostage (the
   2026-08-09 all-day wedge — and "GitHub expires them at 30d" was false at day 8).
   `deploy/watch_deploy_gate.sh` now enforces this posture automatically (stale →
   reject, logged; the old pin-exclude-and-leave-waiting zombie list is retired). Do
   NOT cancel the waiting run: a cancelled run strands its deploy → recover with a
   `deploy_all=true` workflow_dispatch of `ci-cd.yml`. (Observed 2026-07-28: run
   30324990970 held the gate ~15h; the #1653 merge queued behind it and never
   started; the mis-diagnosis as phantom cost a wrongly-cancelled run.)

2. **Stranded Plan — the R8-ST6 shape.** The run FAILS, but the only red job is
   `Plan deployments` (the IAM-review gate) with `Deploy` **skipped** and lint/tests
   green. This is by design after an IAM-touching merge: nothing deploys until the
   pending CDK change goes out from main (`bash deploy/cdk_deploy.sh <Stack>` — the
   classifier clears it only on Matthew's in-the-moment ask). Until then **every**
   subsequent merge's deploy strands too; after the CDK deploy, recover the stranded
   fleet half with a `deploy_all=true` dispatch. A run where any OTHER job also
   failed (e.g. Unit Tests) is an ordinary red — it owes a code fix; the CDK deploy
   alone will not clear it.

3. **Phantom deploy wedge — the #2052 shape.** The run's `Deploy` job is blocked in the
   `ci-cd-deploy-<ref>` concurrency group by an entry that corresponds to **no real
   run**. Since #2009 moved that group from the workflow onto the `deploy` job, this no
   longer presents as `0 jobs`: the run shows **five green jobs** and sits `pending`,
   which reads as "waiting for approval". It is not. `pending_deployments` is empty and
   **stays** empty, because GitHub evaluates a job's `concurrency` **before** its
   environment protection rule — the deploy never reaches the gate, so the gate never
   opens and there is nothing to approve. Waiting for it is waiting forever.

   **Every tell written for the older phantom class keys on "0 jobs" and is now blind**
   (`reference_push_ci_silent_death`, and state 1 above). Worse, state 1 and state 3 are
   **byte-identical when you look at one run**:

   | state | `run.status` | `Deploy` job `.status` | `pending_deployments` |
   |---|---|---|---|
   | awaiting/stranded approval | `waiting` | `waiting` | **non-empty** |
   | queued behind a real holder | `pending` | `pending` | `[]` |
   | **phantom wedge** | `pending` | `pending` | `[]` |

   The last two rows cannot be told apart from a single run — the discriminator is
   necessarily fleet-level and is exactly one question: **does any other in-flight run
   on this ref actually HOLD the deploy group?** (i.e. has a `Deploy` job that is
   `in_progress` or `waiting` — a job parked at the gate still occupies the slot). No
   holder + blocked past the threshold = phantom.

   Do not diagnose this by eye. Run **`python3 scripts/check_deploy_wedge.py`**, which
   fetches the per-run job state `gh run list` does not carry — and, since #2467,
   enumerates ALL non-completed runs on the workflow (each in-flight status queried
   explicitly, paginated, **no recency bound**), so a gate-parked `waiting` run of ANY
   age is named as the holder with its age before "phantom" can be concluded. Recovery:
   `--recover` (cancel the wedged run, re-dispatch `ci-cd.yml` with `deploy_all=true` —
   a dispatch has no push diff, so change detection would otherwise deploy nothing).
   **Do NOT salt the concurrency group** — see the ledger below.

   **Last-mile alerting (#2149).** #2052 proved detection but a red scheduled workflow
   is a passive channel — the 2026-08-05 stranded-approval recurrence (#5 in the
   session-status block, distinct from this ledger's #5) went red 6× over ~9h with no
   human paged until a manual run. `deploy-wedge-watch.yml`'s classify step now runs
   `--alert`: on a CONFIRMED wedge/stranded-approval it fires the same
   `repository_dispatch` `urgent_alarm` event `remediation_dispatcher_lambda.py`
   already fires for urgent CloudWatch alarms, so `remediation-agent.yml`'s existing
   curated-email path pages the operator — no new channel. Throttled to one alert per
   episode via a GitHub issue marker (label `deploy-wedge-alert`), not an AWS-written
   marker — this workflow holds no AWS credentials and gains none for this. Throttle/
   payload logic: `alert_candidate`/`should_fire_alert`/`build_dispatch_payload`/
   `maybe_alert` in `check_deploy_wedge.py`, tested in `tests/test_deploy_wedge_alert_2149.py`.

4. **Rejected-and-superseded — the #2590 shape (NOT a state to fix; a state to read
   correctly).** Rejecting a gated run is the *prescribed* action of state 1, and it
   lands the run as **`conclusion: failure` with `Deploy` as its sole red job** — the
   job never executed, so `gh run view <id> --log-failed` says "log not found". Read
   literally that is a red main, so for a while **obeying #2467 made the wrap's own
   (e2) green-main gate report a falsehood** (five times on 2026-08-11/12:
   `32734614d`, `b177805f6`, `aad9ae137`, `c78c93369`, `c16c75783`). It self-heals
   the moment a later run succeeds, so the false-red window is exactly the gap
   between the rejection and the next successful deploy — in a session that rejects
   a run per merge and defers the deploy to the end, that is the whole session.
   Nothing needs cleaning up afterwards; a later success at a newer sha supersedes it.

   `scripts/check_main_green.py` now skips these the way it already skips `cancelled`,
   but **reports** each one with its sha and the rejecting operator's own reason, so
   "the lease was actioned" never looks like "the gate is blind". **Derive it from the
   run's own approval record, never from the job shape**:

   ```bash
   gh api repos/averagejoematt/life-platform/actions/runs/<run_id>/approvals \
     --jq '.[] | {state, comment, envs: [.environments[].name]}'
   # → {"state":"rejected","comment":"Superseded: …","envs":["production"]}
   ```

   (`…/actions/runs/<id>/deployments` **404s** on this repo — `approvals` is the
   run-scoped source of truth and is the only thing that carries the reason.) The
   check is a **conjunction**: rejected AND `Deploy` is the sole failing job. A
   genuinely broken `Deploy` job has the identical job shape and must still read RED —
   and two of the five runs above were rejected *and* had a real `test / Unit Tests`
   failure, so keying on the rejection alone would have declared main green over a
   real red. Fixtures + both mutation directions: `tests/test_rejected_deployment_2590.py`.

5. **The empty `pending_deployments` ambiguity (#2590).** When a gate action finds
   nothing to action, that means one of two opposite things and **the run cannot tell
   you which**: the gate has not opened for it, or an *older* run owns the production
   lease and is silently queueing it behind (state 1's mechanism, seen from the
   *victim's* side). Live 2026-08-11: run `31528727429` sat `waiting` while the newer
   `31529270801` showed `Deploy: pending` with an empty `pending_deployments` — it read
   as "the gate never opened"; rejecting the holder released it instantly. Both
   `deploy/approve_deployment.sh` and `deploy/reject_deployment.sh` now call
   `surface_gate_lease_holder` (`deploy/lib/deploy_gate_lease.sh`) on that branch: it
   enumerates every `waiting` run with no recency bound and names the holder, or says
   plainly that nothing holds the lease and points at `check_deploy_wedge.py`.

#### The recurrence ledger — five wedges, four fixes, what each one bought

Kept here so the sixth is diagnosed in minutes instead of re-derived from scratch. Every
fix before #2052 was shipped **blind**: nothing measured the wedge while it was happening.

| # | Date | Presentation | Fix shipped | Outcome |
|---|---|---|---|---|
| 1 | 2026-07-24 | run `pending`, 0 jobs, workflow-level group | salt `-v2` | recurred in 3 days |
| 2 | 2026-07-27 | same, after 2 supersede-cancellations | salt `-v3` | recurred in 6 days |
| 3 | 2026-08-02 | same, group otherwise EMPTY | salt `-v4` | recurred same day |
| 4 | 2026-08-02 | same, sole member of its group | **#2009 redesign** — workflow group per-`run_id`; the real invariant moved to a job-level group on `deploy` | moved the wedge, did not remove it |
| 5 | 2026-08-02 | **5 green jobs**, `Deploy` blocked, gate never opens | **#2052** — detection + escape hatch (`check_deploy_wedge.py`, `deploy-wedge-watch.yml`) | measured for the first time |
| 6 | 2026-08-09 | all-day wedge; THREE `deploy_all` dispatches blocked in sequence; `--recover` looped | **root cause finally measured (#2467): not phantom** — two 8-day-old gated runs (08-01/02) sat `waiting` with Deploy parked at the gate, silently holding the job-level slot; the script's recent-run window couldn't see them, so it read "no holder = phantom". Cure: **REJECT the zombies' pending_deployments** (state=rejected — run dies, nothing stale ships, slot frees). The "pin-exclude and leave waiting" zombie posture is retired — leave-waiting = hold-the-fleet-hostage; and "GitHub expires them at 30d" was false at day 8. **Fix shipped (#2467): the holder scan enumerates ALL non-completed runs (paginated, no recency bound); stale gate holders get reject guidance (`deploy/reject_deployment.sh`), and `watch_deploy_gate.sh` auto-rejects them** | the sixth entry closes the ledger's question: entries 1–5's "phantom" may have been unseen gate-parked holders all along |

Two things the ledger settles. **Salting never worked** — three attempts, three
recurrences, median 3 days; a `-v5` is not a fix. And **#2009's consolation was wrong**:
it predicted a narrower phantom that would "at least be legible", but a wedged deploy
reading as "waiting for approval" is *less* legible than the old `0 jobs`, which at
least announced itself. #2009 was still right on the merits — validation jobs have no
business queueing — it just moved the blast radius rather than shrinking it.

**Why #2052 did not replace the concurrency group with an SSM/DDB lock** (issue #2052's
first acceptance bullet, deliberately deferred): `cancel-in-progress: false` on the
deploy group *is* the no-two-concurrent-deploys invariant, and the observed failure is a
GitHub-side queue-entry leak, not a consequence of those semantics. A self-managed lock
trades an opaque leak for one we can inspect — but introduces a strictly worse failure
mode: a deploy job cancelled mid-flight (which is exactly what happens in the
supersede-burst that triggers every one of these) leaves the lock **held**, and clearing
it then needs an AWS write from a runner that holds deploy credentials. Five recurrences
were "fixed" blind; the next structural change should be made against measurements from
the detector, not ahead of them.

All of these are surfaced at wrap time by `check_main_green.py` (a `waiting` run
older than ~2h is reported loudly with its run id + sha; younger ones ride along as a
notice; a phantom wedge outranks everything, including a green completed run — while it
holds, "main GREEN" is a stale fact; a rejected-and-superseded run is skipped as a
verdict but named with its sha and the operator's own reason). Fixture-pinned in
`tests/test_stranded_deploy_1901.py`, `tests/test_deploy_wedge_2052.py` (real captured
API payloads for all three live wedge states) and `tests/test_rejected_deployment_2590.py`.

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
- **There are THREE S3 deploy prefixes, not two (#2019)** — `site/` (sync_site_to_s3.sh)
  and `generated/` (Lambda-written, ADR-046) were known; **bucket-root `config/`** is the
  third and had NO deploy path until #2019. A merged change to a repo `config/` twin
  reached the CloudFront-served `site/config/` mirror but never the object the site-api
  Lambda actually reads, and three layers hid it: no sync step, a no-TTL warm-container
  cache, and a 3600s CloudFront TTL on `/api/*`. Measured 2026-08-02: `/api/supplements`
  served withdrawn citations for ~13h after the withdrawal merged, every gate green.
  The path is now `deploy/config_twin_sync.py`, run by `site-deploy.yml` on merge:
  - the twin set is **derived** (`deploy/config_twin_registry.py`), never enumerated — a
    new repo `config/` file joins the deploy path on its own;
  - it uploads **explicit files only** — never `aws s3 sync`, never `--delete`, never a
    prefix operation. Root `config/` also holds Lambda-written runtime state
    (`config/hevy_template_cache.json`), out-of-band objects (`config/requirements/*`)
    and an auth session pickle that a prefix sync would clobber or strip;
  - runtime-written keys are excluded by an AST scan, and a `config/` write whose key
    can't be resolved statically **reds a test** rather than being silently guessed at;
  - `.github/workflows/config-drift.yml` runs the read-only check daily, so
    "merged but not serving" alarms instead of printing green.
  Read-only check any time: `python3 deploy/config_twin_sync.py` (dry-run is the
  default; `--apply` is explicit).
- **A repo twin can be read from a SECOND key — check the alias, not just the path
  (#2057).** The twin map is `S3 key = repo path`, so any consumer that reads the same
  content through a different key is invisible to the drift check *by construction*.
  Three do: `character_engine`, `site_api_vitals` and `board_loader` read
  `config/{user}/character_sheet.json` and `config/{user}/board_of_directors.json`,
  which are byte-identical to the repo files at bucket root. That is not cosmetic —
  `restart_pipeline` rewrites `config/character_sheet.json` on **every experiment
  reset** and the merge syncs bucket-root only, so the serving path would have kept
  reading the outgoing cycle's baseline. Alias *patterns* are now derived from the
  reader AST and expanded to concrete keys against the live namespace, so both a new
  aliased read and a new user segment join the checked set on their own.
- **The twin check asks "does S3 match the repo?" — something must ask the inverse
  (#2057).** Walking repo files can only ever see objects the repo authors; a
  runtime-written or out-of-band `config/` object is not *clean* in that check, it is
  *absent from it*. `deploy/config_mirror_audit.py` walks **live S3** instead and
  requires every object a deployed module reads to have an owner — `repo_twin`,
  `alias`, `repo_source` (a repo file outside `config/`, hand-copied in once), or
  `writer` (AST-derived). Two rules worth keeping:
  - a writer-owned object's max-age is read from **the writer's own declared TTL
    constant**, never a number chosen in the checker (a freshness window encodes the
    *writer's* cadence). Undeclared ⇒ no freshness assertion, rather than a guess;
  - what gates is the **serving path, not the schedule**. A stale mirror is only a lie
    to readers when `lambdas/web/` reads it, which is why
    `config/hevy_template_cache.json` — a demand-driven cache legitimately weeks past
    its 24h TTL — warns instead of redding the build every day.
- **A registry published through two prefixes needs the two repo copies tied together
  (#2084).** Several catalogs ship twice: `config/x.json` is what the site-api Lambda
  reads from S3, `site/config/x.json` is the static asset the site sync publishes. Two
  deploy paths, and nothing structurally connects them. That is how `/api/challenges`
  and `/api/challenge_catalog` came to serve the *same* 82 challenges under two
  different casts for three weeks — the #1904 roster fix reached only the `site/` copy,
  and neither the twin check (which had no bucket-root repo file to compare) nor the
  cast guard (which only knew the `site/` path) could see it. `tests/
  test_config_site_mirror_parity.py` now asserts byte equality across **every** basename
  present in both trees, derived from the trees. **Never introduce a JSON registry a
  Lambda reads via a hand `aws s3 cp` from outside `config/`** — put it in `config/` and
  it joins the derived twin set with a real byte assertion. `seeds/` is generators only.

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
     so it is deliberately narrow (forward-only, glue-guarded, ledgers exempt).
     `scripts/doc_facts_ops.py` is its **operational-claim** half (#1957 — the classes a
     number/cron scan structurally cannot see, each ground-truthed by AST/source parse):
     the budget-tier ladder vs `budget_guard._FEATURE_CUTOFF`, every Lambda named in a
     doc table vs the CDK `function_name=` set, the alarm inventory, and the secret
     inventory (stamped count == live table rows · nothing documented as deleted while an
     IAM role is granted it · the `live-verified` stamp under 90d, refreshed read-only via
     `python3 deploy/sync_doc_metadata.py --refresh-secrets`). Adding a rule there means
     adding its planted-violation test in `tests/test_doc_facts_ops_1957.py`;
   - `scripts/check_doc_index.py` — every page is indexed from the wiki home, carries
     the status header, the >90d advisory freshness report, a **blocking 180d ceiling**
     (a canonical page unverified that long fails CI), and the #973 engine-doc
     source-drift gate — **strict by default** (#1965): the bare command fails exactly
     where Docs CI's `--strict` run fails, so a locally-green tree cannot red CI on
     drift (the 2026-07-27 double-red). `--advisory` demotes drift to a loud
     "would RED CI under --strict" report; on a shallow clone the drift half skips
     with a note (run it from a full clone for CI parity — Docs CI uses fetch-depth: 0).
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

## 9. Gate registry — defect class → owning gate (#1349)

The standing gates (wrap-time, CI, pre-commit) have grown one incident at a time —
each section above narrates its own origin story, but nothing answered "which gate
would catch THIS class of defect?" in one glance. This table is a routing index, not a
restatement: each row is a one-line pointer to the section/file that owns the rule —
read that section for the incident narrative and the exact mechanics.

**Wrap gates** (session-close, `.claude/commands/wrap.md` — run every `/wrap`):

| Defect class | Owning gate | Where |
|---|---|---|
| Session shipped+deployed work with no public dispatch | Build-beat gate (#736), step (d) | `.claude/commands/wrap.md` step (d) |
| A shipped change invalidated a wiki page and nobody updated it | Doc-impact sweep, step (e) | `.claude/commands/wrap.md` step (e); mechanics in §8 above |
| A governance-consequential decision landed with no ADR | Decisions gate (#1343), step (e) | `.claude/commands/wrap.md` step (e) |
| A status block claims "main GREEN" without reading the badge | Green-main gate (#1327), step (e2) | `scripts/check_main_green.py` |
| A deploy parks forever behind a phantom concurrency entry while its run reads "waiting for approval" | Deploy-wedge detector (#2052), folded into step (e2) | `scripts/check_deploy_wedge.py`; §4d above |
| An incident-class event (rollback, main red >1h, data gap, budget-tier event) went unlogged | Incident gate (#1332), step (e3) | `docs/INCIDENT_LOG.md` + `.claude/commands/wrap.md` step (e3) |
| A handover residual/next-picks bullet names real work with no issue number | Residual-queue gate (#1340), step (e4) | `scripts/check_residual_queue.py` |
| A stale `git stash` entry or a dead pre-commit hook survives across sessions | Stash + hook hygiene gate (#1326), step (e5) | `deploy/session_postflight.py` |
| A filed issue skips the ADR-099 contract (no milestone, score line, `## Outcome`, acceptance boxes, epic link, or a `model:*`/`type:*`/`area:*`/`prio:*` label) | Filing-contract linter (#1867/#1870), step (e7) — blocking by default since #1872, which absorbed and deleted the older #1349 `model:*`-only gate | `scripts/check_backlog_hygiene.py` |
| An issue closed this session leaves no outcome verdict (53 of the last 60 closures had zero comments) | Closure-comment gate (#1870), step (e8) | `.claude/commands/wrap.md` step (e8); contract in ADR-099's amendment ¶3 |
| `Now` sits at zero actionable stories, or a `Later` issue ages past 60d with nobody calling promote-or-close | Now-refill + `Later` sweep (#1870), step (e9) | `scripts/backlog_next.py`; `.claude/commands/wrap.md` step (e9) |
| A memory topic file exists un-indexed from `MEMORY.md`/`project_shipped_archive.md` | Orphan/broken-link gate (#1259), step (c) | inline bash loop, `.claude/commands/wrap.md` step (c) |
| A `MEMORY.md` index correction didn't carry through to the topic file's body | Body-follows-index gate (#1342), step (c) | `scripts/check_memory_body_facts.py` |
| A CloudWatch alarm sits in ALARM >72h with no citation, normalizing among the chronic reds | Alarm-citation gate (#1959), step (e10) | `scripts/check_alarm_citations.py`; `docs/alarm_citations.json` |
| A `::warning::` annotation on green main (e.g. the duration-budget warner below) goes untriaged | Standing-warning triage gate (#1966), step (e11) | `scripts/check_ci_warnings.py` |

**CI gates** (`.github/workflows/ci-cd.yml` unless noted — every push to `main` or a PR):

| Defect class | Owning gate | Where |
|---|---|---|
| Unformatted/unsorted Python, a stale-typed module, a syntax error | Lint job (`black`/`ruff`/`mypy`/`py_compile`) | §4 above |
| A Lambda/CDK deploy artifact or its wiring is broken (IAM, handler names, DDB patterns, MCP registry) | `test-critical` deploy-critical lane (ADR-117) | §4a above |
| A dependency/CDK toolchain version silently floats | Pinned-both-directions check | §4 above ("CDK toolchain is pinned both directions") |
| A deprecated secret name still referenced | "Deprecated secrets scan" step | `.github/workflows/ci-cd.yml`, job `test` |
| An upstream vendor API payload shape drifted | `test_upstream_contracts.py` (ER-02) | `.github/workflows/ci-cd.yml`, job `test` |
| Line coverage regresses below the enforced floor | Coverage gate (`--cov-fail-under=53`, ADR-080) | `.github/workflows/ci-test.yml`, job `test` |
| The coverage floor silently lags measured coverage | Coverage-gap drift warning (#1206) | `scripts/coverage_gap_warn.py` |
| Real coverage is deleted down into the floor's anti-flap headroom — every gate still green | Measured-coverage high-water ratchet, ENFORCING (#1658) | `scripts/coverage_gap_warn.py --high-water`; `RATCHET_HIGH_WATER` in `tests/test_coverage_floor_ratchet.py` |
| The Unit Tests job's own wall-clock silently climbs (157s→294s→688s avg→830s avg, budget raised 480→900→1200s by #1966/#2152) | Suite-duration budget warning (#1349/#1966/#2152) | `scripts/coverage_gap_warn.py --duration-seconds`; ratchet in `tests/test_duration_budget_ratchet.py` |
| A visible page/component regresses (layout break, blank data-bind, JS error) | Visual-QA (Playwright + Bedrock vision) | §4b above |
| A merged repo `config/` change never reaches the S3 object the API reads ("merged but not serving") | Config-twin sync on merge + daily drift check (#2019) | `deploy/config_twin_sync.py`; `.github/workflows/config-drift.yml`; §7 above |
| A live `config/` object a Lambda reads is stale or unowned — a writer class the repo-twin check cannot see | Config mirror ownership + freshness audit (#2057) | `deploy/config_mirror_audit.py`; `.github/workflows/config-drift.yml`; §7 above |
| A registry published through two prefixes drifts between its copies — two endpoints, two answers | `config/` ↔ `site/config/` byte parity (#2084) | `tests/test_config_site_mirror_parity.py`; §7 above |
| A generator-owned artifact (doc-sync literals, ADR index, chrome block) goes stale across a merge queue | Merge-day reconcile job | §4c above |
| A doc claims a stale count/version/cadence in any phrasing | `check_doc_facts.py` | §8 above |
| A page references a retired concept | `check_doc_tombstones.py` + `docs/_lint/tombstones.txt` | §8 above |
| A relative doc link/anchor is broken | `check_doc_links.py` | §8 above |
| A canonical page is unindexed or unverified >180d | `check_doc_index.py` | §8 above |
| A doc-sync literal (test/alarm/lambda count) drifts from ground truth | `deploy/sync_doc_metadata.py --check` | §8 above; literals excluded from this table's edits (see CLAUDE.md) |
| `health-auto-export-webhook` gains a second ingress (an out-of-IaC API Gateway) or a wider-than-declared invoke grant | HAE webhook single-ingress parity (#1946) | `deploy/check_hae_webhook_ingress_drift.py --strict` + its daily blocking workflow |

**Pre-commit hook** (`scripts/install_hooks.sh`, installed once per clone — runs on every local commit):

| Defect class | Owning gate | Where |
|---|---|---|
| A staged Python file isn't `black`/`ruff` clean | Format gate (#785/CLAUDE-02) | `scripts/install_hooks.sh` |
| The hook's `black`/`ruff` is a *different version* than CI pins — it blocks correct commits, and obeying it reds CI | Pinned-formatter resolution (#2570) | `deploy/lib/pinned_formatters.sh`, shared by the hook + `deploy/agent_commit.sh` + `make preflight` |
| A doc-sync literal is stale at commit time | `sync_doc_metadata.py --apply`, auto-staged | `scripts/install_hooks.sh` |

**The format gate resolves the pin, and fails closed (#2570).** It reads the version from
`requirements-dev.txt` (the CQ-01 source of truth, the file Dependabot bumps) and probes each
candidate — `.venv-black`/`.venv` in the worktree *and* in the primary clone via
`git rev-parse --git-common-dir` — accepting one **only at the exact pinned version**. It is
version-verified, not location-trusted. No match refuses the commit rather than falling back to
`PATH`; the measured incident was a `PATH` black 25.9.0 against CI's 26.3.1, which disagreed on a
real file in both directions. Two consequences worth knowing: **every clone must re-run
`bash scripts/install_hooks.sh`** (the hook is generated and untracked, so an old one keeps
resolving off `PATH` until it is regenerated — `deploy/session_postflight.py` reports it STALE),
and the pinned venv needs *both* tools installed
(`.venv-black/bin/pip install -q $(grep -E '^(black|ruff)==' requirements-dev.txt)`) or the
resolver falls through to whatever `PATH` happens to carry.

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
| Open CodeQL alerts | `gh api '/repos/{owner}/{repo}/code-scanning/alerts?state=open&per_page=100' --paginate --jq length` → steady state **0** since the #1902 triage (every alert is fixed or dismissed-with-reason; a just-merged fix stays open until CodeQL re-analyzes main). `drift_sentinel.check_codeql_alerts` alarms on regrowth — an open alert is un-triaged by definition, so triage it, never let the list re-accumulate |
| `main` classic branch protection | `gh api repos/<owner>/<repo>/branches/main/protection` → must 404 "Branch not protected" (removed 2026-07-13, #1173; a 200 here means protection was re-added out of band — reconcile the doc, don't assume this table is wrong) |
| `main` ruleset posture | `gh api repos/<owner>/<repo>/rulesets` → must show `main-block-force-push-and-deletion` (id `19162901`) with `rules: [deletion, non_fast_forward]` only, `enforcement: active`, no `pull_request`/`required_status_checks` rule (#1325), **and** `main-required-fast-lane` (#1662, ADR-148). Full record: `gh api repos/<owner>/<repo>/rulesets/<id>` |
| `main` required status checks + auto-merge | `python3 scripts/apply_branch_protection.py --check` → exit 0 and "clean" when live matches `deploy/github_posture.json` (ADR-148). It prints the required contexts, the `User` bypass actor (the repo owner, #2198) the reconcile bot depends on, and `allow_auto_merge`. Never hand-edit the ruleset in the GitHub UI — `--apply` is the only sanctioned writer, and the weekly drift sentinel reports any out-of-band edit |

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
