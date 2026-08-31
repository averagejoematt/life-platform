# `infra/iam/` — the OIDC automation identities, codified (#401 / ADR-120)

> **Dated publication note (2026-08-23, #3043 DIL-012):** these policy documents —
> and the AWS account id inside their ARNs — are published **deliberately** in the
> public repo. The account id is not a secret by itself (it appears in every ARN
> across `cdk/`; AWS guidance treats it as an identifier, not a credential), and the
> policies contain no credentials: the security boundary is the OIDC trust
> conditions + STS, not obscurity. Publishing them is what makes every trust change
> a reviewable PR with `git revert` as the rollback.

This directory is the **reviewable, git-revertible source of truth** for the
hand-managed AWS identities that gate all automated access to the cloud:

| Identity | What it gates | Assumed by |
| --- | --- | --- |
| `github-actions-deploy-role` | ALL CI/CD deploys (lambda, layer, CDK, site, smoke, visual-QA, rollback, notify) | every job in `.github/workflows/ci-cd.yml` |
| `github-actions-remediation-role` | the self-healing agent's read-only diagnosis + Bedrock + scoped audit-log writes | `.github/workflows/remediation-agent.yml` |
| `github-actions-golden-eval-role` | the eval harness's advisory Haiku judge + `LifePlatform/GoldenBrief` metric emit + read-only `EVALRET#*` harvest reads (#812) | `.github/workflows/golden-brief-eval.yml`, `.github/workflows/eval-harvest.yml` |
| `token.actions.githubusercontent.com` OIDC provider | the GitHub → AWS identity federation the roles trust | AWS STS `AssumeRoleWithWebIdentity` |

Before #401 these existed **only** as live IAM config — no source of truth, no review
trail, and trusted from `repo:averagejoematt/life-platform:*` (assumable from ANY branch
of a public repo). Codifying them here is a **no-op to live behaviour** (the checked-in
JSON reflects live exactly — proven by `deploy/verify_oidc_iam.py`), but it turns every
future trust change into a reviewable PR with `git revert` as the rollback.

## Files

### Current live state (source of truth — reflects live exactly, today)
- `github-oidc-provider.json` — the OIDC provider (URL, client-id list, thumbprints)
- `github-actions-deploy-role.trust.json` — deploy role assume-role (trust) policy
- `github-actions-deploy-role.permissions.json` — deploy role inline policy `life-platform-cicd-permissions`
- `github-actions-remediation-role.trust.json` — remediation role assume-role (trust) policy
- `github-actions-remediation-role.permissions.json` — remediation role inline policy `remediation-permissions`

> **Apply path (#3336): `bash deploy/setup_remediation_role.sh` / `bash deploy/setup_github_oidc.sh`** —
> both scripts apply the files above VERBATIM (`--policy-document file://infra/iam/…`) and end with
> `verify_oidc_iam.py --strict`. They carry no policy text of their own: until 2026-08-30 each was a
> hand-maintained twin, and running the remediation one put a stale document (15 of 17 statements,
> any-ref trust) live for ≈6 minutes — `docs/INCIDENT_LOG.md`. `tests/test_iam_twin_free_3336.py`
> fails the suite if an inline policy document for any role listed here reappears under `deploy/`.

### Staged, NOT yet applied — the golden-eval role (#812)
- `github-actions-golden-eval-role.trust.json` — trust policy (main-only subject from day one; no
  repo-wide grant to tighten later)
- `github-actions-golden-eval-role.permissions.json` — inline policy `golden-eval-permissions`
  (least-privilege: `bedrock:InvokeModel` on the Haiku profile only, `cloudwatch:PutMetricData`
  namespace-conditioned to `LifePlatform/GoldenBrief`, `dynamodb:Query` LeadingKeys-scoped to
  `EVALRET#*`). Until applied, `verify_oidc_iam.py` reports it as `MISSING` (expected) and the
  two workflows that use it degrade gracefully (judge step is `continue-on-error`; the harvest
  run fails visibly). **Apply runbook below.**

### Proposed, NOT yet applied (the staged tighten — see the runbook below)
- `proposed/github-actions-deploy-role.trust.main-only.json`
- `proposed/github-actions-remediation-role.trust.main-only.json`

## Verify (read-only drift check)

```bash
python3 deploy/verify_oidc_iam.py            # print report
python3 deploy/verify_oidc_iam.py --strict   # exit 1 on any drift (CI/sentinel gate)
```

It calls only `iam:GetRole`, `iam:GetRolePolicy`, `iam:GetOpenIDConnectProvider` — never
mutates. A CLEAN run means the checked-in JSON matches live; DRIFT means either an
out-of-band change happened (investigate — these gate all deploys) or a staged change
here has not been applied yet.

---

## The trust-tighten — EXECUTED 2026-07-09 (#687)

> Applied attended 2026-07-09: both roles' live trust is now the main-only form and the
> canonical `*.trust.json` files below carry it (`proposed/` removed). Validated live:
> main-ref run assumed the deploy role (visual-qa dispatch green), a non-main branch
> dispatch failed with `Not authorized to perform sts:AssumeRoleWithWebIdentity`, and
> `verify_oidc_iam.py` reports CLEAN. A read-only `github-actions-diagnosis-role`
> (Bedrock vision-QA only, main-only trust) was split out in the same pass; the three
> vision-QA credential steps assume it instead of the deploy role. The weekly drift
> sentinel now runs the verifier (`check_oidc_iam`). Rollback: `git revert` + re-apply
> the reverted trust JSON via `aws iam update-assume-role-policy`.

---

## The read-only diagnosis shed — STAGED 2026-07-09 (#903), NOT yet applied

> **Status: the checked-in JSON is AHEAD of live.** This PR removes the pure
> read-only diagnosis surface from `github-actions-deploy-role.permissions.json`
> (the `life-platform-cicd-permissions` inline policy). Until the attended
> `aws iam put-role-policy` below runs, `python3 deploy/verify_oidc_iam.py --strict`
> reports exactly ONE expected DRIFT on
> `github-actions-deploy-role:life-platform-cicd-permissions`. This is the pending
> apply, not an out-of-band change. (The weekly `check_oidc_iam` sentinel calls the
> verifier without `--strict`, so it does not red on this staged gap.)

**What #903 sheds from the deploy role** (each was verified to have NO consumer among
the CI jobs that assume the deploy role — `plan`, `deploy`, `smoke-test`,
`post-deploy-checks`, `rollback-on-smoke-failure`, `notify-failure` in `ci-cd.yml`, and
the deploy-role steps of `site-deploy.yml`):

| Statement | Why it can go | Where it lives now |
| --- | --- | --- |
| `IAMReadOnly` (removed) | No deploy-role job calls `iam:*`. `cdk diff` diffs CloudFormation templates, not live IAM. The only reader is `verify_oidc_iam.py`, run by `drift_sentinel.py` under the **remediation** role. | remediation-role (its diagnosis surface) |
| `BedrockVisionQA` (removed) | The three vision-QA credential steps assume `github-actions-diagnosis-role` since #687; no deploy-role job invokes Bedrock. | diagnosis-role (its sole grant) |
| `CloudWatch` metric reads — `GetMetricStatistics`, `ListMetrics`, `GetMetricData` (removed; `DescribeAlarms` KEPT) | `post-deploy-checks` I7 needs `cloudwatch:DescribeAlarms`; nothing on the deploy role reads metric data. | remediation-role `Diagnose` (already holds the full metric-read set) |

**Kept (still consumed by a deploy-role job)** — `LambdaDeploy`/`LambdaListAccountLevel`
(deploy + I1/I2), `S3DeployArtifacts` (deploy + I8), `DynamoDB` (plan assert + I4), `SNS`
(notify/rollback), `SQS` (I9), `KMS DescribeKey` (plan assert), `EventBridge` (I6),
`CloudWatch DescribeAlarms` (I7), `SecretsManager` (I5), `CloudFormationDiff` (plan `cdk
diff`), `CDKBootstrapRoleAssume`, `CloudFrontInvalidate` (site-deploy).

---

## Remediation-role HAE webhook ingress-check read — STAGED (#1946), NOT yet applied

> **Status: the checked-in JSON is AHEAD of live.** #1946 adds ONE statement to
> `github-actions-remediation-role.permissions.json`: `HaeWebhookIngressCheck` —
> `lambda:GetPolicy` scoped to the single `health-auto-export-webhook` function
> ARN, so the new daily `hae-webhook-ingress-drift.yml` gate can read that
> Lambda's resource policy and assert it carries exactly one apigateway-invoke
> grant, scoped to the CDK-managed API's declared `/*/*/ingest` route (guards
> against a repeat of the pre-IaC orphan API class, #1946). Until applied, the
> new workflow's `AccessDenied` on `GetPolicy` reads as an `error` status (not
> `drift`) from `deploy/check_hae_webhook_ingress_drift.py --strict` — still a
> red run, distinguishable in the log from a real drift finding. Apply
> (attended):
>
> ```bash
> aws iam put-role-policy \
>   --role-name github-actions-remediation-role \
>   --policy-name remediation-permissions \
>   --policy-document file://infra/iam/github-actions-remediation-role.permissions.json
> python3 deploy/verify_oidc_iam.py --strict   # expect CLEAN (for this role)
> python3 deploy/check_hae_webhook_ingress_drift.py --strict   # expect a real clean/drift verdict, not AccessDenied
> ```

---

## Diagnosis-role qa_archive screenshot write — STAGED (#1441), NOT yet applied

> **Status: the checked-in JSON is AHEAD of live.** #1441 adds ONE statement to
> `github-actions-diagnosis-role.permissions.json`: `QaArchiveScreenshotWrite` —
> `s3:PutObject` scoped to `matthew-life-platform/generated/qa_archive/screenshots/*`,
> so the daily standalone visual-qa sweep can archive the AI-surface page screenshots
> (the screenshot leg of the generation-time AI archive; the workflow step is
> `continue-on-error` and only WARNs until this lands). Until applied,
> `verify_oidc_iam.py --strict` reports the pending drift on
> `github-actions-diagnosis-role:diagnosis-permissions` — this is the staged apply,
> not an out-of-band change. Apply (attended):
>
> ```bash
> aws iam put-role-policy \
>   --role-name github-actions-diagnosis-role \
>   --policy-name diagnosis-permissions \
>   --policy-document file://infra/iam/github-actions-diagnosis-role.permissions.json
> python3 deploy/verify_oidc_iam.py --strict   # expect CLEAN (for this role)
> ```

## Diagnosis-role qa_archive perf-trend read/write — STAGED (#1435), NOT yet applied

> **Status: the checked-in JSON is AHEAD of live.** #1435 adds two statements to
> `github-actions-diagnosis-role.permissions.json`: `QaArchivePerfReadWrite`
> (`s3:PutObject` + `s3:GetObject` scoped to
> `matthew-life-platform/generated/qa_archive/perf/*`) and `QaArchivePerfList`
> (`s3:ListBucket` prefix-conditioned to `generated/qa_archive/perf/*`), so the
> daily standalone visual-qa sweep can persist each run's per-page web-vitals
> (LCP/CLS/JS-bytes) and rebuild the weekly regression trend line
> (`generated/qa_archive/perf/trend.json`). The workflow step is
> `continue-on-error` and `tests/perf_trend.py` is fail-soft, so until this lands
> the perf trend simply does not accrue — it never reds the sweep. Applied by the
> **same** one-line `put-role-policy` as the #1441 screenshot grant above (both
> statements ship in the one file), so a single apply lands both. Until then,
> `verify_oidc_iam.py --strict` reports the pending drift on
> `github-actions-diagnosis-role:diagnosis-permissions`.

## Diagnosis-role AI cost telemetry — STAGED (#2974), NOT yet applied

> **Status: the checked-in JSON is AHEAD of live** (verified 2026-08-22: live policy ==
> pre-#2974 JSON, so the #1441/#1435 grants above ARE applied and this is the only
> pending statement). #2974 adds ONE statement to
> `github-actions-diagnosis-role.permissions.json`: `AiCostTelemetry` —
> `cloudwatch:PutMetricData` namespace-conditioned to `LifePlatform/AI` (same
> least-privilege pattern as the golden-eval role's `GoldenBriefMetrics`), so the
> visual-qa CI job's Bedrock calls can record their token/cost metrics at the
> `bedrock_client.invoke()` chokepoint (G1). Without it every CI Bedrock call bills
> but never records — the largest single AI consumer in CI silently missing from the
> AI-cost self-metric that #2883 measures. The emit stays fail-open (a telemetry
> error never reds the QA sweep) but logs at ERROR with the dropped metric names
> since #2974. Apply (attended):
>
> ```bash
> aws iam put-role-policy \
>   --role-name github-actions-diagnosis-role \
>   --policy-name diagnosis-permissions \
>   --policy-document file://infra/iam/github-actions-diagnosis-role.permissions.json
> python3 deploy/verify_oidc_iam.py --strict   # expect CLEAN (for this role)
> ```
>
> Post-apply proof: the next CI run's `Visual + AI-vision QA` job log shows **zero**
> `bedrock cost telemetry emit failed` lines, and `LifePlatform/AI EstimatedCostUSD`
> gains datapoints timestamped during the run.

## Remediation-role AI cost telemetry — APPLIED 2026-08-24 (#2883)

> **Status: APPLIED live 2026-08-24 (put-role-policy; `verify_oidc_iam.py` CLEAN).** #2883 adds ONE statement to
> `github-actions-remediation-role.permissions.json`: `AiCostTelemetry` —
> `cloudwatch:PutMetricData` namespace-conditioned to `LifePlatform/AI` (identical
> least-privilege shape to the diagnosis role's #2974 grant above), so
> `remediation/agent.py` can record the remediation agent's own Bedrock spend. The
> agent runs entirely inside the Agent SDK on Bedrock (`CLAUDE_CODE_USE_BEDROCK=1`)
> — it never calls `lambdas/ai/bedrock_client.py`'s ADR-062 chokepoint, so its spend
> bills AWS/Bedrock (and counts in `CostMetricDriftRatio`'s native-metric numerator)
> while contributing nothing to the self-reported `LifePlatform/AI::EstimatedCostUSD`
> denominator — one of the two out-of-repo residual sources named when the drift
> ratio stalled at ~1.4x against the <1.15 bar (#2883). The emit stays fail-open (a
> telemetry error never fails a remediation run) but logs at ERROR with the dropped
> dollar amount, same as the #2974 precedent. Apply (attended):
>
> ```bash
> aws iam put-role-policy \
>   --role-name github-actions-remediation-role \
>   --policy-name remediation-permissions \
>   --policy-document file://infra/iam/github-actions-remediation-role.permissions.json
> python3 deploy/verify_oidc_iam.py --strict   # expect CLEAN (for this role)
> ```
>
> Post-apply proof: the next scheduled/dispatched remediation run's log shows no
> `remediation cost telemetry emit failed` line, and `LifePlatform/AI EstimatedCostUSD`
> (dimension `LambdaFunction=remediation-agent`) gains a datapoint timestamped during
> the run. This alone will not land `CostMetricDriftRatio` under 1.15 — the other
> named residual (interactive dev-session Bedrock usage) is out of scope by design —
> but it closes the one attributable, in-repo-fixable gap.

## Golden-eval-role budget tier + eval config reads — APPLIED 2026-08-24 (#2824, #3099)

> **Status: APPLIED live 2026-08-24** (`put-role-policy`; `verify_oidc_iam.py --strict`
> CLEAN per #3099 — the `_PENDING_LIVE_APPLY` entries these grants used to hold in
> `tests/test_grant_enumeration_drift.py` were deleted the same day). #2824's grant-enumeration sweep
> (`tests/test_grant_enumeration_drift.py`) derived three fail-closed channels this role's
> entrypoints reach and its policy did not grant — all three confirmed against the **LIVE**
> inline policy, not just the checked-in doc. Two statements close them:
>
> - **`BudgetTierRead`** — `ssm:GetParameter` on `/life-platform/budget-tier`, the same
>   shape #3059 added to the diagnosis role. Consumer path:
>   `tests/golden_brief_eval.py::_run_voice_judge` → `bedrock_client.invoke` →
>   `budget_guard.current_tier`. `current_tier()` fails **open** to tier 0 without the read,
>   so the ADR-125 tier-3 hard stop cannot stop the weekly judge's Bedrock spend — this job
>   has been billing outside the ceiling by construction. Third member of the #2959
>   cycle-param class.
> - **`EvalConfigRead`** — `s3:GetObject` on `config/personas.json` and `config/coaches/*`.
>   Consumer paths: `tests/golden_surface_eval.py::_eval_generic` imports
>   `state_of_matthew_lambda`, whose module scope calls `persona_registry.short_id_names()`
>   (`config/personas.json`); `tests/golden_brief_eval.py` reads the coach dossier
>   (`config/coaches/{id}.json`). The role held **no `s3:GetObject` at all**, so both reads
>   fail AccessDenied and the eval grades a nameless, persona-free surface — the #2469 shape
>   inside the harness that is supposed to catch it. Object-scoped (plus the one coaches
>   prefix), not bucket- or `config/*`-wide.
>
> Both shipped in the one file, applied by the one command (attended):
>
> ```bash
> aws iam put-role-policy \
>   --role-name github-actions-golden-eval-role \
>   --policy-name golden-eval-permissions \
>   --policy-document file://infra/iam/github-actions-golden-eval-role.permissions.json
> python3 deploy/verify_oidc_iam.py --strict   # expect CLEAN (for this role)
> ```
>
> Post-apply proof (confirmed 2026-08-24): `tests/test_grant_enumeration_drift.py`'s
> live-parity half (`test_live_oidc_role_grants_cover_the_derived_consumer_set`,
> credentialed run) reds until the three `_PENDING_LIVE_APPLY` entries are deleted —
> they were deleted in #3099, the confirmation the apply landed and the ratchet shrink.

## Golden-eval-role AI cost telemetry — APPLIED 2026-08-24 (#2883)

> **Status: APPLIED live 2026-08-24** (`put-role-policy`). This statement adds
> `AiCostTelemetry` to `infra/iam/github-actions-golden-eval-role.permissions.json`:
> `cloudwatch:PutMetricData` namespace-conditioned to `LifePlatform/AI`, the identical
> least-privilege shape as the diagnosis-role (#2974) and remediation-role
> (#2883/#3070) grants above.
>
> **Re-verified live 2026-08-24/25** (re-measurement pass, read-only, no cost incurred):
> ```bash
> aws iam get-role-policy --role-name github-actions-golden-eval-role \
>   --policy-name golden-eval-permissions --query 'PolicyDocument.Statement[].Sid'
> # → [..., 'AiCostTelemetry']  -- statement present live
> aws iam simulate-principal-policy \
>   --policy-source-arn arn:aws:iam::205930651321:role/github-actions-golden-eval-role \
>   --action-names cloudwatch:PutMetricData \
>   --context-entries ContextKeyName=cloudwatch:namespace,ContextKeyValues=LifePlatform/AI,ContextKeyType=string
> # → EvalDecision: allowed
> python3 deploy/verify_oidc_iam.py   # no drift reported for this role — repo JSON == live
> ```
> Both checks confirm the grant is live and functional. It does **not yet show up** in
> `LifePlatform/AI::EstimatedCostUSD` — the 2026-08-24T15:54 UTC `golden-brief-eval.yml`
> run (`32747686536`, 8x AccessDenied on `PutMetricData`) **predates** the apply, and
> `golden-brief-eval.yml` only runs weekly (Mondays 15:17 UTC — next: 2026-08-31). The
> first run to actually prove the fix end-to-end (zero `bedrock cost telemetry emit
> failed` lines, a `CallerClass=ci` datapoint landing during the run) will be that one,
> or an attended `workflow_dispatch` with `run_judge: true` sooner — neither happened as
> part of this pass (`gh workflow run` would itself spend Bedrock $ and write
> CloudWatch metrics, outside this worktree's read-only-AWS mandate).
>
> This was the third instance of the #2974 class (a Bedrock-calling CI identity billing
> `AWS/Bedrock` natively while silently dropping every `LifePlatform/AI` self-report);
> diagnosis-role and remediation-role needed the same hand-found fix — a recurring blind
> spot in the grant-derivation tooling (#2824's sweep only derives
> `ssm`/`secret`/`s3config`/`ses` channels by design; #1196's lockstep test only walks
> CDK-wired Lambda source, never GitHub Actions OIDC roles). Dollar size is small
> (weekly cadence, ~8 Haiku judge calls/run) — closes an attribution gap, not a material
> share of #2883's box-4 residual (see the CE reconciliation re-measurement in
> `docs/audits/AI_COST_DRIFT_ATTRIBUTION_2026-08-18.md`'s addendum).

### ATTENDED APPLY runbook (#903 — execute under a watched CI run)

> Precondition: attended, matthew-admin, with rollback ready. Same discipline as #687 —
> validate that a NORMAL deploy still works after the perms are stripped.

1. **Snapshot the current live policy** (rollback source):
   ```bash
   aws iam get-role-policy --role-name github-actions-deploy-role \
     --policy-name life-platform-cicd-permissions \
     --query PolicyDocument > /tmp/deploy-perms.rollback.json
   ```
2. **Apply the reduced policy** from the checked-in JSON:
   ```bash
   aws iam put-role-policy --role-name github-actions-deploy-role \
     --policy-name life-platform-cicd-permissions \
     --policy-document file://infra/iam/github-actions-deploy-role.permissions.json
   ```
3. **Confirm the verifier goes CLEAN:** `python3 deploy/verify_oidc_iam.py --strict` (the
   one expected deploy-role DRIFT disappears).
4. **Validate with a real CI run** — push a trivial `lambdas/` change (or `workflow_dispatch`)
   and WATCH `plan → deploy (approve) → smoke → post-deploy-checks` complete. `post-deploy-checks`
   (I5/I6/I7) is the load-bearing check that the KEPT reads (Secrets/EventBridge/DescribeAlarms)
   still work; a stripped-too-much mistake surfaces there as an `AccessDenied`.
5. **Rollback (if anything breaks):**
   ```bash
   aws iam put-role-policy --role-name github-actions-deploy-role \
     --policy-name life-platform-cicd-permissions \
     --policy-document file:///tmp/deploy-perms.rollback.json
   # then git revert the #903 PR
   ```

### Original staging notes (kept for context)

`#401`'s acceptance criteria require the trust subject to be narrowed from repo-wide
(`repo:...:*`) to **main branch / production environment only**, and that the tighten be
**validated by watching a real CI run complete end-to-end (plan → deploy → smoke)**. That
validation is a precondition, so the flip is a **separate, watched, deliberate** step —
NOT part of the codify PR. It is tracked as its own follow-up issue: **#687**.

### Why the tightened deploy-role subject lists TWO patterns

GitHub's OIDC `sub` claim differs per job:
- A job that declares `environment: production` presents `repo:OWNER/REPO:environment:production`.
- A job with no environment presents `repo:OWNER/REPO:ref:refs/heads/<branch>`.

In `ci-cd.yml` **only the `deploy` job** declares `environment: production`; `plan`,
`smoke-test`, `visual-qa`, `post-deploy-checks`, `rollback-on-smoke-failure`, and
`notify-failure` present the branch ref (`refs/heads/main`). So the tightened deploy-role
trust MUST allow BOTH subjects or half the pipeline breaks:
- `repo:averagejoematt/life-platform:ref:refs/heads/main`
- `repo:averagejoematt/life-platform:environment:production`

The remediation role is only assumed by scheduled / `workflow_dispatch` runs on the
default branch (main), with no environment, so its tightened subject is just:
- `repo:averagejoematt/life-platform:ref:refs/heads/main`

### Runbook — applying the tighten (execute only under a watched CI run)

> Precondition: do this attended, with the ability to roll back immediately. A wrong
> subject locks the automation out of AWS entirely.

1. **Snapshot the current live trust** (rollback source), for both roles:
   ```bash
   aws iam get-role --role-name github-actions-deploy-role \
     --query Role.AssumeRolePolicyDocument > /tmp/deploy-trust.rollback.json
   aws iam get-role --role-name github-actions-remediation-role \
     --query Role.AssumeRolePolicyDocument > /tmp/remediation-trust.rollback.json
   ```
   (These already equal the checked-in `*.trust.json` files — `git revert` of the tighten
   PR is the durable rollback.)

2. **Apply the tightened trust** from the proposed files:
   ```bash
   aws iam update-assume-role-policy --role-name github-actions-deploy-role \
     --policy-document file://infra/iam/proposed/github-actions-deploy-role.trust.main-only.json
   aws iam update-assume-role-policy --role-name github-actions-remediation-role \
     --policy-document file://infra/iam/proposed/github-actions-remediation-role.trust.main-only.json
   ```

3. **Validate with a real CI run** — push a trivial commit to `main` (or `workflow_dispatch`)
   and WATCH the pipeline complete end-to-end: `lint → test → plan → deploy (approve) →
   smoke → visual-qa → post-deploy`. Every job must assume the role successfully. A trust
   mistake surfaces as `Not authorized to perform sts:AssumeRoleWithWebIdentity`.

4. **Confirm a non-main ref is now denied** (access simulation / negative test):
   ```bash
   # Expect DENY for a non-main ref subject:
   aws iam simulate-principal-policy ...   # or open a throwaway branch PR and confirm the
                                           # OIDC step fails to assume the deploy role.
   ```

5. **Promote the proposed files to current** — once validated, move
   `proposed/*.trust.main-only.json` content into the canonical `*.trust.json` files in a
   follow-up PR so `deploy/verify_oidc_iam.py` stays CLEAN against the new live state.

6. **Rollback (if anything breaks):**
   ```bash
   aws iam update-assume-role-policy --role-name github-actions-deploy-role \
     --policy-document file:///tmp/deploy-trust.rollback.json
   # …and the remediation role likewise. Then git revert the tighten PR.
   ```

### Also part of the full tighten (follow-up, not this codify PR)
- **Split a read-only diagnosis role out of the deploy role** (AC: "a read-only diagnosis
  role is split from the deploy role"). The `github-actions-diagnosis-role` was created in
  #687; **#903 completes the shed** — see the section below.
- **Wire these identities into the weekly drift sentinel (S-E6-01).** `deploy/verify_oidc_iam.py`
  is the drift detector; add a `--strict` call to it as a step in `deploy/drift_sentinel.py`
  (or the remediation workflow) so out-of-band trust changes are caught weekly.

---

## Runbook — creating the golden-eval role (#812, staged)

One-time, attended (matthew-admin). Creates a NEW role — nothing existing changes, so the
blast radius of a mistake is zero (the two consuming workflows are advisory/harvest only).

```bash
aws iam create-role --role-name github-actions-golden-eval-role \
  --assume-role-policy-document file://infra/iam/github-actions-golden-eval-role.trust.json \
  --description "Least-privilege eval-harness role: weekly Haiku voice judge + GoldenBrief metrics + EVALRET# harvest reads (#812)"

aws iam put-role-policy --role-name github-actions-golden-eval-role \
  --policy-name golden-eval-permissions \
  --policy-document file://infra/iam/github-actions-golden-eval-role.permissions.json

python3 deploy/verify_oidc_iam.py   # expect CLEAN (the MISSING finding disappears)
```

Validate by dispatching `.github/workflows/golden-brief-eval.yml` with `run_judge: true` and
watching the judge step emit `LifePlatform/GoldenBrief` metrics, then dispatching
`.github/workflows/eval-harvest.yml` and confirming the candidate artifact uploads.

---

## #2834 — CI's additive-IAM deploy needs NO new grant (2026-08-30; staged diff: EMPTY)

> **Status: nothing to apply.** The additive-IAM gate (`deploy/iam_additive_gate.py`,
> ADR-065 amendment 2026-08-30) lets the Deploy job run `cdk deploy <Stack> --exclusively`
> for a stack whose synthesized template diff is additive-only IAM. That deploy needs no
> change to `github-actions-deploy-role.permissions.json`, and this section exists so the
> reviewer can see *why* the staged diff is empty rather than assume it was forgotten.

**The permission chain `cdk deploy` actually uses** (CDK v2, bootstrap v6+, read live
2026-08-30 with `iam:GetRole` / `iam:GetRolePolicy` / `iam:ListAttachedRolePolicies` — no
mutation):

| Hop | Principal | What it needs | Held? |
| --- | --- | --- | --- |
| CI → CDK deploy role | `github-actions-deploy-role` | `sts:AssumeRole` on `arn:aws:iam::<acct>:role/cdk-*` (statement `CDKBootstrapRoleAssume`) | **yes**, since #401 |
| CDK deploy role → CloudFormation | `cdk-hnb659fds-deploy-role-<acct>-<region>` (trusts the account root) | `cloudformation:CreateChangeSet/ExecuteChangeSet/…`, `iam:PassRole` on the cfn-exec role, `ssm:GetParameter` on `/cdk-bootstrap/hnb659fds/version` — all in its bootstrap `default` policy | yes (bootstrap) |
| asset upload | `cdk-hnb659fds-file-publishing-role-*` (assumed, same `cdk-*` grant) | S3 put to the bootstrap assets bucket | yes (bootstrap) |
| CloudFormation → resources | `cdk-hnb659fds-cfn-exec-role-<acct>-<region>` | **`AdministratorAccess`** (the CDK bootstrap default) | yes (bootstrap) |
| the gate's read side | `github-actions-deploy-role` | `cloudformation:GetTemplate` (statement `CloudFormationDiff`) | yes |
| the ledger | `github-actions-deploy-role` | `s3:PutObject` on `matthew-life-platform/*` (statement `S3DeployArtifacts`) — writes `remediation-log/iam-additive-gate/YYYY/MM/DD/` | yes |

`tests/test_iam_additive_gate_guards_2834.py::test_deploy_role_needs_no_new_grant_for_the_additive_deploy`
pins the three deploy-role statements from the committed JSON, so a future shed of any of
them reds before it silently breaks the additive deploy.

**What this means for the threat model, stated plainly.** "CI cannot mutate IAM" was never a
permission property of this role: the bootstrap chain above has been assumable by the
deploy role since the role was codified, and `ci-cd.yml` simply never contained a `cdk
deploy` step. #2834 adds the step behind a fail-closed, statement-level gate — it changes
what CI *exercises*, not what CI *could* do. The proportionate next tightening (a separately
priced decision, not part of #2834) is to scope the bootstrap's execution policy
(`cdk bootstrap --cloudformation-execution-policies …`) or add a permissions boundary on
the CI path so that CFN-via-CI cannot exceed the namespace the gate's registry names.

**Verify (read-only), before and after the #2834 merge — expect NO change here:**

```bash
python3 deploy/verify_oidc_iam.py --strict     # deploy-role: CLEAN (or only the already-staged #903 shed)
```

---

## #3340 — the CDK cfn-exec permissions boundary (STAGED, owner-run; the braces under #2834's belt)

> **Status: the checked-in JSON is AHEAD of live, by design.** Until the apply below runs,
> `python3 deploy/verify_oidc_iam.py --strict` reports exactly **three** findings —
> `[BOUNDARY-MISSING]` on each of `cdk-hnb659fds-cfn-exec-role-205930651321-{us-west-2,us-east-1,us-east-2}`
> — and **nothing else** (measured 2026-08-31 in the implementing worktree: `12 target(s)
> compared`, 3 findings, every OIDC identity CLEAN). That is the pending apply, not an
> out-of-band change, and it is red on purpose: a boundary that reported green while absent
> would be the exact class of instrument this repo keeps finding (#3200, #3318).

**What it is.** One customer-managed policy, `cdk-cfn-exec-boundary`, attached as the
**permissions boundary** on the three regional CDK execution roles. Those roles carry
`AdministratorAccess` (CDK bootstrap default) and are what CloudFormation acts as; since
#2834 CI exercises that chain on every additive IAM grant, with the gate's parser as the
only line. The document is **derived** from `deploy/iam_additive_registry.py` — the same
registry the gate reads — by `deploy/derive_cfn_exec_boundary.py`, and committed as
`infra/iam/cdk-cfn-exec-boundary.boundary.json`. The full Deny inventory, the shape
argument, the non-goal and the ratchet baseline are in the **ADR-065 amendment of
2026-08-31** (`docs/DECISIONS.md`).

**Not a re-bootstrap.** `cdk bootstrap --custom-permissions-boundary` was considered and
rejected: it re-runs the bootstrap stack in every region, and its rollback is another
bootstrap. This is three `put-role-permissions-boundary` calls, and its rollback is three
`delete-role-permissions-boundary` calls.

### 0. ROLLBACK — read this first

If a deploy breaks, if `cdk diff` starts failing, if anything at all looks wrong: take the
fence off. It is three API calls and it restores the exact pre-2026-08-31 state.

```bash
for R in us-west-2 us-east-1 us-east-2; do
  aws iam delete-role-permissions-boundary \
    --role-name "cdk-hnb659fds-cfn-exec-role-205930651321-$R"
done

# Then (optional — the policy is inert once detached, and keeping it makes re-apply one call):
aws iam delete-policy --policy-arn arn:aws:iam::205930651321:policy/cdk-cfn-exec-boundary

# Confirm the roles are bare again (expect PermissionsBoundary: None x3):
for R in us-west-2 us-east-1 us-east-2; do
  aws iam get-role --role-name "cdk-hnb659fds-cfn-exec-role-205930651321-$R" \
    --query 'Role.PermissionsBoundary' --output text
done
```

`git revert` of the #3340 PR is the repo-side rollback; the two are independent, and either
alone is safe.

### 1. Pre-flight (read-only, no credentials needed for the first two)

```bash
python3 deploy/derive_cfn_exec_boundary.py --check      # committed JSON == derivation
python3 -m pytest tests/test_cfn_exec_boundary_3340.py -q
python3 deploy/derive_cfn_exec_boundary.py --simulate   # iam:SimulateCustomPolicy, read-only
```

`--simulate` is the pre-apply evidence: it evaluates the document AWS's own way against 35
probes — the escalation the mutation probe deploys, the fence protecting itself, the
irreplaceable data zones, the region pin in both directions, and 15 positive controls for
what an ordinary stack deploy does. Expect `35/35 simulator verdicts as expected`.

### 2. Apply (attended, `matthew-admin`)

```bash
aws iam create-policy \
  --policy-name cdk-cfn-exec-boundary \
  --description "#3340 permissions boundary for the CDK cfn-exec roles — derived, see infra/iam/README.md" \
  --policy-document file://infra/iam/cdk-cfn-exec-boundary.boundary.json

for R in us-west-2 us-east-1 us-east-2; do
  aws iam put-role-permissions-boundary \
    --role-name "cdk-hnb659fds-cfn-exec-role-205930651321-$R" \
    --permissions-boundary arn:aws:iam::205930651321:policy/cdk-cfn-exec-boundary
done
```

A later change to the document is `aws iam create-policy-version --policy-arn … \
--policy-document file://infra/iam/cdk-cfn-exec-boundary.boundary.json --set-as-default`
— **never** a hand-edited inline document (#3336: the shell twin that ran stale for six
minutes).

### 3. Verify

```bash
python3 deploy/verify_oidc_iam.py --strict   # expect CLEAN — the three BOUNDARY-MISSING findings disappear
```

`BOUNDARY-DRIFT` means a boundary is attached but is not this policy; `BOUNDARY-UNREADABLE`
means the calling identity cannot read the role or the policy version (run as
`matthew-admin` — the remediation role's `IAMRoleRead` is scoped to the four OIDC roles).

### 4. The no-op deploy — the real proof it did not break anything

```bash
bash deploy/cdk_deploy.sh LifePlatformCore     # expect: no changes, or only the changes cdk diff already showed
```

Then one stack that actually has resources to touch (`LifePlatformCompute` is the largest
IAM surface). A boundary problem surfaces as `AccessDenied … with an explicit deny in a
permissions boundary` in the stack events, never as a silent no-op.

### 5. The mutation proof (acceptance box 3) — run AFTER the apply

`infra/iam/boundary_probe/` holds two throwaway CloudFormation templates. Both are deployed
**as the cfn-exec role** (`--role-arn`), which is the whole point: a deploy under
`matthew-admin` would not exercise the boundary at all.

```bash
EXEC=arn:aws:iam::205930651321:role/cdk-hnb659fds-cfn-exec-role-205930651321-us-west-2

# (a) NEGATIVE control — a role outside the enrolled families with iam:* on Resource "*".
aws cloudformation create-stack --region us-west-2 \
  --stack-name boundary-probe-3340 \
  --template-body file://infra/iam/boundary_probe/escalation.template.json \
  --capabilities CAPABILITY_IAM --role-arn "$EXEC"

aws cloudformation wait stack-create-complete --region us-west-2 --stack-name boundary-probe-3340 \
  || echo "expected: the wait FAILS because the stack rolled back"

aws cloudformation describe-stack-events --region us-west-2 --stack-name boundary-probe-3340 \
  --query "StackEvents[?ResourceStatus=='CREATE_FAILED'].ResourceStatusReason" --output text
# EXPECTED, verbatim shape:
#   API: iam:CreateRole User: arn:aws:sts::205930651321:assumed-role/
#   cdk-hnb659fds-cfn-exec-role-205930651321-us-west-2/AWSCloudFormation is not authorized to
#   perform: iam:CreateRole on resource: arn:aws:iam::205930651321:role/boundary-probe-3340-EscalationRole-…
#   with an explicit deny in a permissions boundary

aws cloudformation delete-stack --region us-west-2 --stack-name boundary-probe-3340 --role-arn "$EXEC"

# (b) POSITIVE control — the last green additive grant's shape (an in-family role name plus
#     the 2026-08-14 P1 grant: s3:GetObject on one config object). This MUST reach
#     CREATE_COMPLETE, or the boundary is refusing the platform's own deploys.
aws cloudformation create-stack --region us-west-2 \
  --stack-name boundary-probe-3340-additive \
  --template-body file://infra/iam/boundary_probe/additive.template.json \
  --capabilities CAPABILITY_NAMED_IAM --role-arn "$EXEC"

aws cloudformation wait stack-create-complete --region us-west-2 --stack-name boundary-probe-3340-additive
aws cloudformation delete-stack --region us-west-2 --stack-name boundary-probe-3340-additive --role-arn "$EXEC"
```

Paste both verdicts — the `AccessDenied` line and the `CREATE_COMPLETE` — into the #3340
acceptance box. One without the other proves half of it: a fence that denies everything and
a fence that denies nothing look identical from one probe.
