# Disaster Recovery

> **Status:** canonical · **Owner:** Matthew · **Verified:** 2026-07-11

**Last updated:** 2026-07-11 (Scenario 8 — stolen/lost laptop: RPO + rotation checklist, from the #1024 audit)

> What can go catastrophically wrong, and the recovery sequence for each. Not exhaustive — meant as a starter playbook.

---

## RTO / RPO summary

| Scenario | Recovery Time Objective | Recovery Point Objective |
|---|---|---|
| Single Lambda failure | 5 min (rollback) | Real-time |
| Lambda code corruption (all functions) | 1h (re-deploy from git HEAD) | Real-time |
| Single DDB item lost / overwritten | 5 min (PITR query) | 35 days |
| Full DDB table lost | 30 min (PITR full restore) | 35 days |
| S3 bucket corruption (specific path) | 5 min (versioned restore) | Versioning enabled — every put |
| S3 bucket deletion (catastrophic) | ⚠️ NOT RECOVERABLE — cross-region replication not enabled (ADR-057 W-03 deferred) | — |
| Account compromise | Hours (rotate all secrets + audit CloudTrail) | Depends on compromise window |
| Stolen / lost laptop | Hours (rotate device-resident creds + rebuild on a new machine) | Pushed git = last push; Claude memory + `datadrops/` ≤24h behind once #1026 lands (manual/unbounded until then) — see Scenario 8 |
| us-west-2 region outage | Hours-days (no DR region — ADR-057 W-03 deferred) | — |
| Anthropic API outage | Auto-degrade — see below | — |

---

## What IS protected

✅ **DynamoDB PITR** enabled (35-day point-in-time recovery)
✅ **S3 versioning** enabled on `matthew-life-platform` — every PUT keeps prior version
✅ **S3 lifecycle** — old versions expire (raw/* 7d, config/* 30d → Glacier IR, uploads/* 30d)
✅ **CloudTrail** management events + data events on `raw/*` and `uploads/*` (90-day S3 retention)
✅ **Git** — code in 2 places: local + GitHub. Multiple commits per session.
✅ **Lambda deploy artifacts** in S3: `deploys/<fn>/latest.zip` + `previous.zip` per Lambda
✅ **CDK source-of-truth** — entire infrastructure reproducible from `cdk/` + `cdk deploy --all`
✅ **Secrets Manager** versioning — 30-day soft-delete recovery window on every secret

## What is NOT protected (accepted risk per ADR-057)

❌ **Cross-region replication** — single-region (us-west-2 + us-east-1 for CloudFront/edge)
❌ **External secret backup** — if Secrets Manager region is wiped, OAuth tokens are gone (re-auth via setup scripts)
❌ **Anthropic API key backup** — stored only in Secrets Manager `life-platform/ai-keys`; user must keep a backup elsewhere
❌ **Multi-region DDB** — Global Tables not enabled
❌ **Cross-account backups** — single AWS account

---

## Scenario 1 — Single DDB item lost or overwritten

**Symptoms:** A user query returns wrong data; a record went missing after a buggy compute Lambda overwrite.

**Recovery:**
```bash
# 1. Identify the partition + sort key affected
PK="USER#matthew#SOURCE#whoop"; SK="DATE#2026-05-15"

# 2. Use PITR to query at a known-good timestamp
aws dynamodb restore-table-to-point-in-time \
    --source-table-name life-platform \
    --target-table-name life-platform-recovery \
    --restore-date-time 2026-05-19T08:00:00 \
    --region us-west-2

# 3. Query the recovery table for the lost item
aws dynamodb get-item \
    --table-name life-platform-recovery \
    --key "{\"pk\":{\"S\":\"$PK\"},\"sk\":{\"S\":\"$SK\"}}" \
    --region us-west-2

# 4. Copy back to main table (overwriting if needed)
aws dynamodb put-item --table-name life-platform --item <copied json> --region us-west-2

# 5. When done, delete the recovery table
aws dynamodb delete-table --table-name life-platform-recovery --region us-west-2
```

**Cost:** $0.02/GB/month for PITR; ~$3 for a brief recovery-table operation.

---

## Scenario 2 — Full DDB table corruption

**Symptoms:** Mass writes to wrong keys; bulk delete that shouldn't have happened.

**Recovery:**
```bash
# 1. STOP all writes — disable EventBridge schedules
aws events list-rules --region us-west-2 \
    --query 'Rules[?State==`ENABLED`].Name' --output text \
    | tr '\t' '\n' \
    | xargs -I{} aws events disable-rule --name {} --region us-west-2

# 2. PITR restore to a clean state (just BEFORE the bad writes)
aws dynamodb restore-table-to-point-in-time \
    --source-table-name life-platform \
    --target-table-name life-platform-restored \
    --restore-date-time 2026-05-19T07:00:00 \
    --region us-west-2

# 3. Verify the restored table has expected content
aws dynamodb scan --table-name life-platform-restored --max-items 5 --region us-west-2

# 4. Swap names (table renaming is not a thing in DDB — use one of two paths):
#    Path A: leave restored as life-platform-restored; redirect all Lambdas (env var TABLE_NAME)
#    Path B: delete corrupted + rename via boto3 export/import (slow)

# 5. Re-enable EventBridge schedules
# (manual: enable rules one-by-one to confirm each pipeline)
```

**Key insight:** Practice scenario 1 first (cheap, low-stakes); scenario 2 is rare and high-stakes.

---

## Scenario 3 — S3 path corruption

**Symptoms:** `aws s3 sync` ran with wrong path; specific objects overwritten.

**Recovery:**
```bash
# 1. List object versions
aws s3api list-object-versions --bucket matthew-life-platform \
    --prefix site/index.html --region us-west-2

# 2. Find the good version ID (one before the corruption)
# 3. Copy it back as current
aws s3api copy-object \
    --copy-source "matthew-life-platform/site/index.html?versionId=<good-id>" \
    --bucket matthew-life-platform --key "site/index.html" \
    --region us-west-2

# 4. Invalidate CloudFront
aws cloudfront create-invalidation --distribution-id E3S424OXQZ8NBE \
    --paths "/index.html" --region us-west-2
```

---

## Scenario 4 — Lambda code corruption (mass deploy went bad)

**Symptoms:** Multiple Lambdas failing after a CDK deploy.

**Recovery:**
```bash
# 1. STOP — don't keep pushing fixes
# 2. Identify the bad commit
git log --oneline -20

# 3. Revert source
git revert <bad-sha>  # or git reset --hard <good-sha> if you're sure

# 4. Re-deploy via CDK
cd cdk && npx cdk deploy --all

# 5. If individual Lambda needs rollback faster than CDK deploy:
bash deploy/rollback_lambda.sh <fn>
```

---

## Scenario 5 — Account compromise

**Symptoms:** Unexpected charges, foreign IPs in CloudTrail, secrets seen externally.

**Immediate response (within 1 hour):**
```bash
# 1. ROTATE the AWS account root password via Console
# 2. Rotate IAM access keys for matthew-admin
aws iam create-access-key --user-name matthew-admin
# Update local AWS config with new keys
aws iam delete-access-key --user-name matthew-admin --access-key-id <OLD>

# 3. Invalidate ALL platform credentials — rotate-secret alone is FALSE SECURITY here:
#    only mcp-api-key has a rotation Lambda; the other ~20 secrets would silently
#    NOT rotate (the || fallback swallows the failure) while the attacker's copies
#    stay valid. Do all three classes:
#    (a) the one auto-rotatable secret:
aws secretsmanager rotate-secret --secret-id life-platform/mcp-api-key --region us-west-2
#    (b) vendor API keys (Anthropic ai-keys + site-api-ai-key, Hevy, Todoist, Habitify,
#        google-tts, pexels, …): REVOKE at each provider console, reissue, put-secret-value —
#        per-secret procedures in docs/SECRETS_ROTATION.md.
#    (c) OAuth refresh tokens (whoop/withings/strava/garmin/eightsleep): revoke the app
#        grant at the provider, then redo each auth flow (setup/ scripts; Whoop is manual —
#        SECRETS_ROTATION §Whoop). Internal HMAC signing secrets (subscriber-token-secret,
#        ritual-token-secret, site-api-origin-secret): generate new random values and
#        put-secret-value (invalidates outstanding tokens — acceptable in a compromise).

# 4. Check CloudTrail for unauthorized API calls
aws cloudtrail lookup-events --region us-west-2 \
    --start-time $(date -u -v-1d '+%Y-%m-%dT%H:%M:%S') \
    --query 'Events[?ErrorCode!=null].[EventTime,UserIdentity.UserName,EventName,ErrorCode]' \
    --output table

# 5. Disable any IAM users/roles that look suspicious
```

**Follow-up (within 24 hours):**
- Audit S3 raw/ + uploads/ for data exfiltration (CloudTrail data events catch this)
- Rotate the Anthropic API key (manually via console.anthropic.com — no programmatic API)
- Reset Garmin / Whoop / etc. external service passwords (the platform's tokens were potentially compromised)
- Notify Partner / Matthew of potential email-recipient exposure if SES was used by attacker

---

## Scenario 6 — us-west-2 region outage

**Reality:** No DR region exists. AWS region outages have happened (the famous us-east-1 outages of 2017/2021). us-west-2 has had localized outages too.

**Response sequence:**

**Day 0 (during outage):**
- Site averagejoematt.com may be down (CloudFront → S3 in us-west-2)
- Daily-brief won't send (Lambda + DDB in us-west-2)
- Accept the gap — it's a personal-scale platform

**Day 1 (post-outage):**
- AWS will restore data; no action needed
- Re-run any failed scheduled Lambdas manually:
  ```bash
  aws lambda invoke --function-name daily-brief --payload '{}' --region us-west-2 /tmp/out.json
  ```

**Long-term mitigation (if outages become recurrent):**
- Enable DynamoDB Global Tables (us-west-2 + us-east-1)
- Replicate S3 bucket to us-east-1 (or different account)
- Lambda functions deployed to both regions, Route53 health-check failover

Per ADR-057 W-03, this is deferred — overkill for current scale.

---

## Scenario 7 — Anthropic API outage

**Symptoms:** Daily-brief logs Anthropic 429 / 500 / network errors; coach outputs empty.

**Auto-degradation (already in place):**
- `retry_utils.py` retries 4 attempts with exponential backoff (5s, 15s, 45s)
- After retry exhaustion, falls back to placeholder narratives
- `daily_brief_lambda.py` substitutes a stub for empty journal coach output (V2 P3.5)
- Daily-brief still sends an email even if 3 of 10 coaches fail — quality gate flags it but doesn't block

**Manual intervention (rare):**
- If Anthropic is fully down >1h: pause daily-brief schedule manually
  ```bash
  aws events disable-rule --name daily-brief-schedule --region us-west-2
  # Re-enable when Anthropic recovers
  aws events enable-rule --name daily-brief-schedule --region us-west-2
  ```
- Optional: switch model env var to a cheaper/different Claude model if specific model is degraded
  ```bash
  aws lambda update-function-configuration --function-name daily-brief \
    --environment 'Variables={...,AI_MODEL=claude-sonnet-4-5}' --region us-west-2
  ```

---

## Scenario 8 — Stolen / lost laptop

**Symptoms:** the development laptop is stolen, lost, or otherwise out of your physical
control. This is the consolidated device-loss playbook from the stolen-laptop resilience
audit (epic #1024, 2026-07-11). Audit verdict: **~90% of the platform is recoverable from
AWS + git** — nothing production-critical lives only on the laptop — but a small set of
device-resident credentials and un-pushed work needs deliberate handling.

**First decision — is this a breach or an inconvenience? (FileVault)**
The entire severity of this scenario hinges on macOS FileVault full-disk encryption:
- **FileVault ON and the machine was locked / powered off when lost** → the disk is
  unreadable without your login password. Theft is an *inconvenience*: buy a new machine,
  rebuild it (Scenario: rebuild via the from-zero bootstrap runbook, #1028), and treat the
  rotation checklist below as *precautionary*, not an emergency.
- **FileVault OFF, or the machine was awake / unlocked when taken** → assume **full
  compromise** of everything a logged-in shell could reach. Execute the rotation checklist
  **immediately** — this is Scenario 5 (account compromise) with a device-loss ordering.

FileVault being enabled is the single control that turns this from a breach into a
shrug. It is an owner-verifiable setting (`System Settings → Privacy & Security →
FileVault`); confirming it is tracked in the re-entry hardening story #1029.

### Recovery Point Objective (what could be lost)

**RPO line:** pushed git is safe to the last push; **Claude memory + `datadrops/`
originals will be ≤24h behind once the launchd backup job (#1026) is live** — until that
job lands the backup is manual and the window is unbounded (whatever was last copied by
hand); **un-pushed git WIP = whatever's on `origin`, everything else is gone.**

Grounded in what actually lives *only* on the laptop:

| Laptop-only asset | Backed by | RPO |
|---|---|---|
| Git-tracked code + docs | GitHub `origin` | Last push (near-zero if you push per session) |
| Un-pushed commits / working-tree edits / `git stash` entries | **nothing** | Total loss beyond `origin`; today's orphaned commits + stashes are being rescued under #1025 |
| Claude memory dir (`MEMORY.md` + topic files) | **manual today → S3 daily once #1026 lands** | ≤24h target (post-#1026); manual/unbounded until then |
| `datadrops/` originals (raw source drops) | same as memory (#1026) | ≤24h target (post-#1026); manual/unbounded until then |
| On-device break-glass AWS keys | Secrets/IAM (not a data-loss risk — a *compromise* risk) | n/a — see rotation checklist |

The practical takeaway: **push often, and land #1026** so the two laptop-only data
directories stop being a silent loss surface.

### Credential / secret rotation checklist (compromised laptop)

Priority order = blast radius first. The rotation *mechanics* live in Scenario 5 above
and in `docs/SECRETS_ROTATION.md`; this is the device-loss ordering. Do **not** enumerate
key file paths here (repo is public) — the device-resident credential inventory is in
`docs/AWS_ACCESS.md` and `docs/ACCOUNTS.md`.

1. **AWS break-glass keys — do this first (highest blast radius).** The long-lived
   access keys on IAM user `matthew-admin` (the break-glass path, `docs/AWS_ACCESS.md` §3)
   can be present on the laptop and grant admin to account 205930651321. Deactivate then
   delete them immediately (`aws iam update-access-key … --status Inactive`, then
   `delete-access-key`; procedure in Scenario 5 step 2). **Because IAM Identity Center
   (SSO) is currently OFF** (audit gap, tracked in #1029), these long-lived keys *are* the
   human-access path — killing them is the whole game. If/when SSO is enabled per
   `docs/AWS_ACCESS.md` §2, also revoke active SSO sessions.
2. **GitHub session + token revocation.** Revoke all other web sessions
   (github.com → Settings → Sessions → *Revoke all other sessions*), regenerate any `gh`
   CLI token / personal access token the laptop held, and audit registered SSH keys
   (remove the stolen machine's key). This stops an attacker pushing to `origin` or
   reading the repo.
3. **Secrets Manager `life-platform/` prefix.** A logged-in shell on the laptop could
   read and write every secret under the prefix. Rotate per the Scenario 5 three-class
   sequence and `docs/SECRETS_ROTATION.md` §"Compromise procedure", in this order:
   (a) internal HMAC signing secrets (`subscriber-token-secret`, `ritual-token-secret`,
   `site-api-origin-secret`) — generate new random values (invalidates outstanding
   tokens, acceptable here); (b) vendor API keys — Anthropic `ai-keys` +
   `site-api-ai-key` first (spend blast radius), then Hevy / Todoist / Habitify / etc.,
   revoked at each provider then `put-secret-value`; (c) OAuth refresh tokens — revoke the
   app grant at the provider, then re-run each `setup/` auth flow.
4. **The Whoop single-use-refresh-token trap.** Whoop rotates the refresh token on every
   use, so a *leaked refresh response permanently invalidates it* — if the attacker
   redeems it once, your ingestion 401s; if you re-auth, theirs dies. Either way the fix
   is a full browser re-auth via `deploy/setup_whoop_auth.py` (see `docs/SECRETS_ROTATION.md`
   §Whoop). Do this deliberately — a half-finished Whoop re-auth leaves ingestion broken.
5. **Everything else the browser/keychain held.** claude.ai / Claude Code session,
   third-party connector tokens (Notion, Dropbox, …), and any browser-saved provider
   logins. The successor-facing inventory of these accounts is `docs/ACCOUNTS.md`
   (see its estate / break-glass section).

### What's recoverable vs. what's truly lost

**Recoverable from AWS + git (the ~90%):**
- All Lambda code, the 9 CDK stacks, and the site — reproducible from git +
  `deploy/build_bundle.py` + `cdk deploy --all` (see "What IS protected").
- All production data — DynamoDB via 35-day PITR, S3 via versioning.
- All wiki/docs — in git.
- A brand-new machine is brought back online by re-authenticating per
  `docs/AWS_ACCESS.md` and following the from-zero rebuild runbook (#1028).

**Truly lost (the gap the RPO quantifies):**
- Un-pushed git commits, working-tree edits, and `git stash` entries beyond what's on
  `origin` (today's are being rescued under #1025).
- Claude memory + `datadrops/` changes since the last backup — bounded to ≤24h once #1026
  lands, otherwise back to the last manual copy.
- Any purely-local scratch that was never committed or uploaded.

**Cross-refs:** epic #1024 · git-WIP rescue #1025 · launchd backup that sets the RPO
#1026 · from-zero rebuild runbook #1028 · re-entry hardening (Identity Center, FileVault,
ACCOUNTS estate rows) #1029 · rotation mechanics: Scenario 5 above +
`docs/SECRETS_ROTATION.md`.

---

## Pre-emptive: Daily/weekly backups to keep

Although automatic backups handle most cases, periodically (e.g. monthly):

```bash
# 1. Export full DDB to S3 (one-time snapshot, ~$0.10)
aws dynamodb export-table-to-point-in-time \
    --table-arn arn:aws:dynamodb:us-west-2:205930651321:table/life-platform \
    --s3-bucket matthew-life-platform \
    --s3-prefix backups/ddb/$(date +%Y-%m-%d)/ \
    --export-time $(date -u '+%s') \
    --region us-west-2

# 2. Keep CloudWatch dashboards as JSON
aws cloudwatch list-dashboards --region us-west-2 --query 'DashboardEntries[].DashboardName' --output text \
    | tr '\t' '\n' \
    | xargs -I{} bash -c 'aws cloudwatch get-dashboard --dashboard-name "{}" --region us-west-2 > backups/dashboards/{}.json'

# 3. Lambda code recovery is already covered — no layer snapshot needed.
#    The shared layer (life-platform-shared-utils) was RETIRED 2026-07-06 (#781);
#    shared modules now ship inside every function's own bundle. Per-function code
#    is recoverable from s3://matthew-life-platform/deploys/<fn>/{latest,previous}.zip
#    (see "What IS protected"), and the whole tree rebuilds from git + build_bundle.py.
```

---

## Testing the playbook

Once per quarter, rehearse a scenario:
- **Easy:** Restore one DDB item from PITR
- **Medium:** Restore one S3 object from versioning
- **Hard:** Roll back a Lambda via the script + verify

Document outcomes in `docs/INCIDENT_LOG.md` as "DR drill" entries and in the log below.

### DR drills exercised

| Date | Scope | Result | Gaps found |
|---|---|---|---|
| 2026-07-10 | **DDB PITR restore** (Scenario 1/2) — `restore-table-to-point-in-time --use-latest-restorable-time` into isolated `life-platform-dr-drill`; **+ S3 versioned restore** (Scenario 3) — prior version of `generated/public_stats.json` copied into isolated `backups/dr-drill/` prefix | ✅ **Both paths work.** Restored table ACTIVE in ~10 min (32,152 items ≈ prod's 32,162); spot-checked partition `USER#matthew#SOURCE#whoop / DATE#2026-07-01` matched prod exactly (recovery 88, hrv 52.87, rhr 56). S3 prior version restored to the drill prefix; **live object untouched**. Both drill artifacts torn down after verification. First verifiably-exercised DDB PITR restore (#755). | (1) This doc's pre-emptive "Snapshot the layer" step referenced the retired `life-platform-shared-utils` layer (#781) — **fixed**. (2) `--use-latest-restorable-time` is simpler than the hardcoded `--restore-date-time` in the Scenario 1/2 examples for a drill; examples left as-is (a real incident restores to *before* the bad write). No functional gaps in the restore procedures themselves. | **Scope caveat:** the drill exercised restore-to-isolated-table only — the Scenario-2 swap-back (repoint prod `TABLE_NAME` / export-import) and its 30-min RTO remain UNEXERCISED; tracked in #936.

---

**Verified:** 2026-07-11 (Scenario 8 stolen/lost-laptop added from the #1024 audit; DR drill 2026-07-10 — first DDB PITR restore + S3 versioned restore)


## GitHub repo-configuration reconstruction

The repo's *settings* are reproducible state that lives only in GitHub (wiki-panel
finding, 2026-07-10). If the repo/org were lost, rebuild:

| Setting | Value / where defined |
|---|---|
| Default branch | `main`; squash-merge is the merge convention |
| `production` environment | Required reviewer: Matthew — this is CI's deploy approval gate (`ci-cd.yml` `environment: production`) |
| OIDC identity provider | `token.actions.githubusercontent.com` in IAM (account 205930651321); trust policies on the 4 CI roles (inventory: `AWS_ACCESS.md` §4) |
| Actions | Enabled; workflows in `.github/workflows/` (all in-repo — nothing console-only) |
| Repo visibility | Target: PRIVATE (⚠️ still PUBLIC as of 2026-07-10 — flip pending, owner action; `docs/coaching/` carries Tier-2 personal data and visibility is a load-bearing privacy control, see DATA_GOVERNANCE) |
| Webhooks / branch protection | None beyond the environment gate (verify: `gh api repos/{owner}/{repo}/branches/main/protection`) |

Re-derive current truth: `gh api repos/averagejoematt/life-platform` + `gh api repos/averagejoematt/life-platform/environments`.
