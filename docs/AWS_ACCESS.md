# AWS Access — the authoritative human-access procedure

> **Status:** canonical · **Owner:** Matthew · **Verified:** 2026-07-10
> **Sources of truth:** `grep -h "role-to-assume" .github/workflows/*.yml | sort -u` (CI role inventory) · `aws sts get-caller-identity` (live auth check) · `docs/SECURITY.md` (policy stance) · `docs/OPERATOR_GUIDE.md` (day-1 checklist)

This file is the **single home** for how a human gets AWS access to the platform.
`docs/SECURITY.md` and `docs/OPERATOR_GUIDE.md` state the *policy* ("no long-lived
keys for daily work") and point here for the *procedure*. `docs/QUICKSTART.md` §1
points here too. If those documents ever disagree with this one, this one wins —
fix the other.

The platform runs in AWS account **205930651321**, region **us-west-2** (Oregon),
for everything (the only exceptions are us-east-1 resources CloudFront requires,
e.g. ACM certificates — you never authenticate "to" a region differently).

---

## 1. Access model overview

| Principal | Mechanism | Status / notes |
|---|---|---|
| **Humans** (Matthew + any successor engineer) | **IAM Identity Center (SSO)** — short-lived sessions via `aws sso login` | Primary path. **Being provisioned as of 2026-07-10** — see the callout in §2. |
| Humans — break-glass | Long-lived access keys on IAM user `matthew-admin` | Legacy path. Acceptable only for SSO outage or initial bootstrap (§3). Rotate every 90 days (`docs/SECURITY.md`). |
| **CI** (GitHub Actions) | **OIDC federation** — `aws-actions/configure-aws-credentials` with `role-to-assume`; no stored keys anywhere | Four roles, inventoried in §4. |
| **Remediation agent** (ADR-064/065) | OIDC → `github-actions-remediation-role` | Bedrock + read-only diagnosis + scoped audit-log writes; NO deploy, NO IAM mutate. |
| Lambdas (runtime) | Per-function execution roles, least-privilege (`cdk/stacks/role_policies.py`) | Not a human path — listed for completeness. |

Service credentials (Whoop, Garmin, etc.) are a different thing entirely: they live
in **Secrets Manager** under the `life-platform/` prefix (`docs/SECRETS_MAP.md`).
Human AWS credentials never go there — see the rule at the end of §3.

---

## 2. IAM Identity Center (SSO) — the primary path

> ⚠️ **Being provisioned as of 2026-07-10.** Until your admin (Matthew) confirms
> Identity Center is enabled and you have a user + permission set assigned, use
> the break-glass path in §3.

### 2a. One-time, account-owner side (Matthew)

All in the AWS Console, region **us-west-2**:

1. **Enable IAM Identity Center** — Console → IAM Identity Center → Enable
   (choose "Enable with AWS Organizations" if prompted; a single-account org is fine).
   Note the **AWS access portal URL** shown on the dashboard
   (`https://<subdomain>.awsapps.com/start`) — engineers need it below.
2. **Create a user** — Identity Center → Users → Add user (name + email; the user
   receives an activation email and sets a password + MFA).
3. **Create a permission set** — Identity Center → Permission sets → Create.
   For the operator role, a predefined `AdministratorAccess` permission set with
   session duration raised to **12 hours** is the pragmatic start; tighten later.
4. **Assign** — Identity Center → AWS accounts → select `205930651321` →
   Assign users → pick the user + permission set.

### 2b. Engineer side (one-time)

```bash
aws configure sso
# SSO session name:  life-platform
# SSO start URL:     https://<subdomain>.awsapps.com/start   ← from your admin (§2a step 1)
# SSO region:        us-west-2
# SSO registration scopes: (accept default: sso:account:access)
# → browser opens; sign in; pick account 205930651321 + your permission set
# CLI default client Region: us-west-2
# CLI default output format: json
# CLI profile name:  life-platform
```

That writes `~/.aws/config` roughly like this (you can also paste it by hand):

```ini
[profile life-platform]
sso_session = life-platform
sso_account_id = 205930651321
sso_role_name = AdministratorAccess   # your permission-set name
region = us-west-2
output = json

[sso-session life-platform]
sso_start_url = https://<subdomain>.awsapps.com/start
sso_region = us-west-2
sso_registration_scopes = sso:account:access
```

Make it the default so the repo's scripts (which don't pass `--profile`) work:

```bash
export AWS_PROFILE=life-platform      # put in your shell profile
aws configure set cli_pager ""        # per docs/OPERATOR_GUIDE.md — pager blocks scripts
```

### 2c. Daily flow

```bash
aws sso login --profile life-platform   # browser round-trip; sessions last up to 12h
aws sts get-caller-identity             # → Account: 205930651321
```

When any command starts failing with `ExpiredToken`/`Unable to locate credentials`,
just `aws sso login` again.

---

## 3. Break-glass: long-lived keys on `matthew-admin`

**When this is acceptable:** IAM Identity Center outage, or initial bootstrap
(no Identity Center provisioned yet — the state as of 2026-07-10). Not for daily
work once SSO is live.

**Create** (Console → IAM → Users → `matthew-admin` → Security credentials →
Create access key, or from an already-authenticated shell):

```bash
aws iam create-access-key --user-name matthew-admin
aws configure          # paste key ID + secret; region us-west-2; output json
aws sts get-caller-identity   # → Arn: ...user/matthew-admin
```

**Rotate** (90-day cadence per `docs/SECURITY.md`; IAM allows max 2 keys per user,
so rotation is create-new → switch → verify → retire-old):

```bash
aws iam create-access-key --user-name matthew-admin        # key B
aws configure                                              # switch local creds to key B
aws sts get-caller-identity                                # verify key B works
aws iam update-access-key --user-name matthew-admin --access-key-id <key-A-id> --status Inactive
# ...wait a day; if nothing broke:
aws iam delete-access-key --user-name matthew-admin --access-key-id <key-A-id>
```

**Park** (when SSO is healthy and the key is only kept for emergencies):

```bash
aws iam update-access-key --user-name matthew-admin --access-key-id <id> --status Inactive
```

**The rule:** human keys live **only** in `~/.aws/credentials` (or your OS
keychain via a tool like aws-vault). Never in `.env` files, never in the repo,
never in Secrets Manager — the `life-platform/` Secrets Manager convention is for
**service** credentials consumed by Lambdas, not for human identities. This repo
is public; a committed key is a full account compromise (threat #3 in
`docs/SECURITY.md`).

---

## 4. CI / OIDC roles inventory

GitHub Actions authenticates via OIDC federation — no stored AWS keys anywhere in
GitHub. Four roles are assumed across the workflows (verified 2026-07-10 by
grepping `role-to-assume`; re-derive with the command below, never from memory):

```bash
grep -h "role-to-assume" .github/workflows/*.yml | sort -u
```

| Role | Assumed by | Scope (one line) |
|---|---|---|
| `github-actions-deploy-role` | `ci-cd.yml` (plan/deploy/smoke/rollback/fleet), `site-deploy.yml` (site sync + rollback) | The deploy path — Lambda code updates, CDK deploys, S3 site sync; slimmed 2026-07-10 (#903/#906: shed `IAMReadOnly` + Bedrock vision-QA perms). |
| `github-actions-diagnosis-role` | `ci-cd.yml`, `site-deploy.yml`, `visual-qa.yml` (diagnosis/QA steps) | Read-only diagnosis: logs, metrics, alarm state — no mutation. |
| `github-actions-remediation-role` | `remediation-agent.yml`, `fresh-eyes.yml` | Self-healing agent (ADR-064/065): Bedrock invoke + read-only diagnosis + scoped audit-log S3 writes; NO deploy, NO IAM mutate. |
| `github-actions-golden-eval-role` | `golden-brief-eval.yml`, `eval-harvest.yml` | Golden-output eval harness (judge): read fixtures + Bedrock invoke for grading. |

CI's production deploy additionally requires manual approval via the GitHub
Environment `production` — the role alone doesn't deploy unattended.

---

## 5. Verification

After any auth setup (SSO or break-glass), confirm both identity and actual
permission with a harmless read:

```bash
# Who am I?
aws sts get-caller-identity
# → "Account": "205930651321"; Arn ends in your SSO role or ...user/matthew-admin

# Can I read? (harmless S3 list of the public site prefix)
aws s3 ls s3://matthew-life-platform/site/ --region us-west-2 | head
```

If both succeed, continue with `docs/QUICKSTART.md` §1 (toolchain + clone) and
you're on the path to a first deploy. Rebuilding a lost or replacement machine from
zero (this auth step is step 3 of it) is stitched into one ordered runbook:
`docs/NEW_MACHINE_BOOTSTRAP.md`.
