# CI `continue-on-error` registry — every swallowed step, with a verdict

**Owner:** whoever edits `.github/workflows/`.
**Guarded by:** `tests/test_continue_on_error_registry_3848.py` (CI, blocking).
**Opened:** 2026-09-17, by 3848.

## Why this file exists

`continue-on-error: true` converts a failing step into a **`success`** conclusion. That is
sometimes exactly right (a diagnostics upload must not red a healthy deploy) and sometimes a
silent hole (a provenance artifact that stops being produced while both steps report green).
The two are indistinguishable from the workflow file alone, so every site gets a written
verdict here and the guard refuses to let a new one land unrecorded.

Founding incident — 3848: `ci-lint.yml`'s "Generate SBOM (syft)" step swallowed
`curl: (35) Recv failure: Connection reset by peer` on 2026-09-16. `curl … | sh` without
`pipefail` takes its status from `sh`, and `sh` fed an empty script exits 0, so the install
"succeeded" with no binary; `continue-on-error: true` then converted the downstream exit-127
into `success`, and the upload's `if-no-files-found: warn` turned the missing artifact into a
warning. Two green steps, no SBOM, for one build.

**A note that matters when reading the verdicts below:** the `#1447`
`advisory-failure-issue` filer (present in `visual-qa.yml`, `webkit-mobile-qa.yml`,
`site-deploy.yml`, `golden-brief-eval.yml`, `cron-freshness.yml`, `fresh-eyes.yml`) keys on
`job.status`. A `continue-on-error: true` step leaves the job **green**, so the filer does
**not** see it. No row below may claim the filer as its covering instrument.

## Verdict vocabulary

| status | meaning |
|---|---|
| `COVERED` | the step's `outcome` is read by a later step/job, or its failure surfaces on a channel that is itself asserted. The swallow is a control-flow device, not a hole. |
| `ACCEPTED` | the failure genuinely is invisible, and that is acceptable for a stated, dated reason: the step gates nothing and produces nothing whose absence could be mistaken for presence. |
| `RESIDUAL` | not covered, and the gap is real. Named here rather than hidden. Carries an owner action. |
| `RESOLVED` | the swallow was removed. Kept for provenance; the guard asserts these have no live site. |

## The Set

Enumeration (2026-09-17, on the branch for 3848 **before** its own fix):

```
$ grep -n "continue-on-error: true" .github/workflows/*.yml
.github/workflows/ci-lint.yml:204
.github/workflows/ci-lint.yml:229
.github/workflows/site-deploy.yml:401
.github/workflows/deploy-wedge-watch.yml:114
.github/workflows/golden-brief-eval.yml:99
.github/workflows/golden-brief-eval.yml:109
.github/workflows/ci-cd.yml:1258      <- a COMMENT, not a step; not a member
.github/workflows/ci-cd.yml:1321
.github/workflows/webkit-mobile-qa.yml:154
.github/workflows/visual-qa.yml:219
.github/workflows/visual-qa.yml:247
.github/workflows/remediation-agent.yml:126
```

12 grep hits, **11 real step sites** (`ci-cd.yml:1258` is prose inside a comment block). The
guard below does not use grep — it parses the YAML, so it also catches `continue-on-error:
True`, an expression form, and a job-level swallow, none of which the grep would see. Today
the YAML walk and the grep agree on the same 11.

**Why two keys below look truncated.** `- name: Generate SBOM (syft — …, #1661)` is an
unquoted YAML scalar, so ` #1661)` is a **comment**: every YAML parser — this guard's and
GitHub's — drops it, and the step's real name ends at the comma. `tests/gate_census_unproven_residue.py`
independently records the same truncated names, which is how that was confirmed rather than
assumed. The keys match what GitHub actually calls the steps; the names were deliberately not
re-quoted, because doing so would change the census keys in that file.

<!-- registry:begin -->

| key | verdict | why (dated) |
|---|---|---|
| `ci-lint.yml :: Generate SBOM (syft — supply-chain provenance,` | `RESOLVED` | 2026-09-17, 3848. `continue-on-error` removed. The step now fetches the installer across two mirrors with retries and then asserts, each with its own `::error::` title: installer non-empty, binary present at `$RUNNER_TEMP/bin/syft` after `install.sh` exits (upstream's script does not `set -e` and its `install_asset()` returns 0 on an empty asset path, so exit 0 is not evidence of install), and both SBOM files non-empty after the scan. The upload moved from `if-no-files-found: warn` to `error`. |
| `ci-lint.yml :: License inventory (pip-licenses — ADVISORY,` | `ACCEPTED` | 2026-09-17. Writes **no artifact** — its only consumer is a human reading this same job log, so there is no absent-artifact that could read as present. The 3848 shape needs a *stored* output; this has none. Residual noted honestly: the step's own `pip install $PINS` on line 1 runs under `bash -e`, so a failure there exits before the `::warning::` on the last line and the inventory silently does not run. Bounded by `docs/LICENSES.md` §6 promising this is advisory, and by the fact that the licence decision it feeds is a human one. |
| `ci-cd.yml :: I5 — Required secrets exist in Secrets Manager` | `RESIDUAL` | 2026-09-17. This is a real post-deploy integration assert (required secrets exist) whose failure reads green and is read by nothing downstream — the step has no `id`, so no `steps.*.outcome` consumer exists. The in-file reason (ci-cd.yml:1256-1259) is that `github-actions-deploy-role` may lack `secretsmanager:DescribeSecret`, which would fail I5 for a permission reason rather than a real missing secret. **That reason may now be stale**: the action appears in `infra/iam/github-actions-deploy-role.permissions.json:135`. **Owner action:** confirm the grant is applied on the live role, then remove this `continue-on-error`. Deliberately NOT changed by 3848 — flipping it without live proof of the grant would red-wall every deploy. |
| `site-deploy.yml :: Upload screenshots + report` | `COVERED` | 2026-09-17 (reason dates to #1331, 2026-07-16/17). A diagnostics side-channel *after* the verdict: the gate steps above it already passed or failed, and `rollback-site-on-failure` keys on those, not on this. Removing the swallow is actively harmful — account-wide artifact-quota exhaustion has flipped this post-step to failure after "GATE PASSED" and fired a rollback on a healthy deploy. No output of this step is consumed. |
| `webkit-mobile-qa.yml :: Upload screenshots + report` | `COVERED` | 2026-09-17. Same #1331 class as the row above: diagnostics upload after the QA verdict, which the sweep step already decided. The sweep step itself is **not** swallowed, so a real QA red still reds the job and the #1447 filer still fires. |
| `deploy-wedge-watch.yml :: Classify the in-flight deploy state` | `COVERED` | 2026-09-17. This is the *good* pattern and the template for the others: the swallow exists so the classifier's non-zero exit can be read as data. The next step is literally `if: steps.classify.outcome == 'failure'` → `::error title=Deploy wedge or stranded gate::`. The outcome is asserted downstream by construction. |
| `golden-brief-eval.yml :: Configure AWS (judge/emit)` | `COVERED` | 2026-09-17. Outcome is consumed: the following step runs only `if: steps.judge-creds.outcome == 'success'`. Credential failure degrades to "the advisory judge did not run", which is the documented staged-role posture (`infra/iam/README.md`), not a hidden gate. |
| `golden-brief-eval.yml :: Advisory voice rubric + metric emit` | `RESIDUAL` | 2026-09-17. Advisory Haiku judge + CloudWatch emit. The binding verdicts in this workflow (`golden_brief_eval.py`, `golden_surface_eval.py`, the self-tests) are **not** swallowed, so nothing that gates is hidden. The real residual is a dead-man one: if the judge fails every week, the voice-trend metric goes dark and the green run looks identical. **Owner action:** a metric-absence alarm on the emitted voice-rubric metric would close it; out of scope for 3848, which is a CI-swallow fix, not a new alarm. |
| `visual-qa.yml :: Archive AI-surface screenshots (#1441)` | `ACCEPTED` | 2026-09-17. The S3 PutObject grant for the diagnosis role is staged but unapplied (`infra/iam/github-actions-diagnosis-role.permissions.json`), so the step is *expected* to fail today; the swallow is what keeps a known-unapplied grant from redding a sweep that gates a deploy path. Distinguished from 3848 by the consumer: the archive is a retrospective aid nothing reads at build time, and the screenshots it copies are also uploaded as a run artifact by the next step. Revisit when the grant is applied. |
| `visual-qa.yml :: Persist perf vitals + weekly trend (#1435)` | `ACCEPTED` | 2026-09-17. Same staged-grant posture as the row above, and the step is already internally fail-soft (`\|\| echo "::warning::"` on both branches) — the swallow is belt-and-braces. Gates nothing; `tests/perf_trend.py` output is a trend line read by humans. Same revisit trigger: when the diagnosis role's perf grant is applied, drop the swallow so a genuine persist failure is loud. |
| `remediation-agent.yml :: Infra drift sentinel` | `ACCEPTED` | 2026-09-17. The sentinel is a read-only diagnosis leg whose findings (`drift-log/latest.json`) are *ingested by the agent step that follows in the same job*; if the sentinel produced nothing, the curated report simply has no drift section. The agent is shadow-permanent and merges nothing (ADR-129 amendment 2026-08-30), so no swallowed output here can reach production. Multiple legs of the sentinel are already documented fail-soft on absent optional tokens (`GH_POSTURE_TOKEN`), i.e. non-execution is an expected state, not an anomaly. |

<!-- registry:end -->

## How to add a row

A new `continue-on-error` needs three things, in this order:

1. ask whether a later step can read `steps.<id>.outcome` instead — the
   `deploy-wedge-watch.yml` row is what that looks like, and it is strictly better than a
   swallow, because the failure becomes data rather than disappearing;
2. if it must be swallowed, say in the workflow file itself **what** would be lost and why
   that loss is tolerable;
3. add the row here with a dated reason. `tests/test_continue_on_error_registry_3848.py`
   fails the build on an unregistered site, and on a non-`RESOLVED` row with no live site.
