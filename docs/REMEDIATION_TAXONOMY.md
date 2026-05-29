# Remediation Taxonomy — how the self-healing agent classifies signals

This is the rubric the remediation agent (`remediation/agent.py`) uses to triage
each technical signal (CloudWatch alarm, QA-smoke failure, freshness alert, CI
failure, DLQ message). For each signal: diagnose root cause, then assign exactly
one **bucket**. Buckets decide what the agent does. Seeded from real incidents
fixed 2026-05-26→29; extend as new patterns recur.

**Modes** (SSM `/life-platform/remediation-mode`): `off` (no-op) · `shadow`
(diagnose + open PRs + email, never auto-merge) · `auto` (auto-merge the
AUTO-FIX-SAFE allowlist, PR the rest).

---

## Bucket A — AUTO-FIX-SAFE (auto-merge allowlist in `auto` mode)

Only these *specific change templates* may auto-merge. The diff must match the
template, touch only the named files, be ≤ ~40 lines, and pass full CI. Anything
broader → Bucket B (PR for review). If unsure, downgrade to B.

| Pattern | Detect | Fix template | File(s) |
|---|---|---|---|
| **Missing IAM grant** (a Lambda calls an AWS API its role lacks) | log `AccessDenied`/`not authorized to perform`; cross-ref boto3 call vs role | add the missing action/resource to the role's statement | `cdk/stacks/role_policies.py` (+ `cdk deploy` the stack) |
| **lambda_map drift** (unmapped `*_lambda.py`, wrong function name) | CI coverage check fails; `ResourceNotFoundException` in deploy | add/correct the `.lambdas` entry | `ci/lambda_map.json` |
| **Layer module list drift** (LV4 fails) | build_layer.sh vs lambda_map mismatch | sync `shared_layer.modules` to `build_layer.sh` MODULES | `ci/lambda_map.json` |
| **Alarm threshold miscalibration** (chronic false-fire at normal levels) | alarm fires daily at steady-state value | raise threshold above observed normal + comment | `cdk/stacks/monitoring_stack.py` |
| **Freshness/QA source miscalibration** (sporadic source flagged stale; dead source still required) | source event-driven (weigh-ins) or dead (last write ≫ threshold) | `SOURCE_STALE_HOURS` override, or move required→optional, or comment out a dead source | `lambdas/emails/freshness_checker_lambda.py`, `lambdas/operational/qa_smoke_lambda.py` |
| **Retry-amplification on a rotating-token source** (clustered async-retry failures) | 1 fire + 2 EventBridge retries within minutes | `retry_attempts=0` on that ingestion Lambda | `cdk/stacks/ingestion_stack.py` |
| **Swallowed-config crash** (`'str' has no attribute 'get'` on a mixed config) | traceback in logs, swallowed by outer handler | add `isinstance` guard | the offending Lambda |
| **CI dead glob / stale path** (a check matches 0 files post-restructure) | check passes vacuously; `ls` of the glob = 0 | switch to recursive `find`/`**` | `.github/workflows/ci-cd.yml`, `tests/*` |

## Bucket B — FIX-VIA-PR (open a PR; human merges, never auto)

Anything that changes **behavior**, not just config/permissions:
- Lambda business logic, retries, data transforms.
- AI/coach **prompts**, model choice, `max_tokens`, caching structure.
- DynamoDB schema / access patterns, new GSIs.
- New resources, new Lambdas, new IAM principals.
- Anything touching a **denylisted** file (see below) — always PR, always review.

## Bucket C — NEEDS-HUMAN (report only; no PR, no change)

The stable set the operator must handle — the agent gives the *specific* action:
- **OAuth re-auth**: Garmin (`setup_garmin_browser_auth.py`), Whoop/Withings/Eight Sleep 401/403 that isn't a transient rotation race. → "re-auth X."
- **Sporadic-data staleness**: a working source with no recent data because the operator hasn't acted (no weigh-in, no workout). → "log/sync X" (not a bug).
- **Paid-tier / vendor decision**: Strava HTTP 402, an API that now requires payment. → "decide: pay or retire."
- **AWS account-level**: Lambda concurrency quota, Service Quotas, Support cases. → "follow up on case N."
- **Budget**: projected spend high, or a genuine cost spike. → "review; the guardrails will pause AI at the ceiling."
- Anything needing a credential, a human judgment, or an external system.

## Bucket D — STALE / IGNORE (collapse in the report, no action)

- Alarm already in `OK` state (self-cleared).
- A migration/deploy-window artifact (e.g., warm-container errors right at a cutover, stale-token 400s that the next run recovers).
- Duplicate of an already-open PR or an already-reported needs-human item.

---

## Operational remediations (direct, not a code PR)

A few fixes are idempotent operational actions the agent does via its scoped role
(then logs to `s3://matthew-life-platform/remediation-log/`), because CI doesn't
`cdk deploy` and these need no code change:
- **Clear a stale alarm** that's stuck ALARM but whose metric is healthy.
- **Drain a confirmed-stale DLQ message** (after verifying the underlying data is present / the cause is fixed).
- **Re-run a failed gap-fill ingestion** (idempotent; the next scheduled run would anyway).

These NEVER include arbitrary AWS writes — only the three above.

---

## Hard denylist (never auto-merge, never auto-edit; always PR + review)

`lambdas/bedrock_client.py`, `lambdas/budget_guard.py`, anything under `auth`,
`deploy/setup_github_oidc.sh`, `deploy/*deploy*.sh`, `.github/workflows/remediation-agent.yml`
(the agent's own workflow), `cdk/app.py`, anything matching `*secret*`/`*credential*`,
and any change that adds/removes an IAM **principal** or widens a resource to `*`.

## Guardrails
- Auto-merge max 3/day; if exceeded, switch remaining to PR + flag in the report.
- Respect budget Tier 3 (`/life-platform/budget-tier` ≥ 3) → skip the run.
- Every action is a git commit/PR (revertable) + a line in the S3 remediation log.
- When confidence is low or a signal doesn't match a template → Bucket B or C, never A.
