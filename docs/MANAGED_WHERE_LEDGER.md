# Managed-Where Ledger

> **Status:** canonical · **Owner:** Matthew · **Verified:** 2026-08-23 (per-row — see the
> Verified column; the dated re-verify log at the bottom is what the operating-calendar
> dead-man reads)

> Every production resource that lives **outside infrastructure-as-code**, with how
> each is verified. A wrong answer to "is this managed in code?" caused the 2026-06
> traffic-logging incident; this ledger makes the right answer scannable.
>
> **Why the re-verify cadence exists (2026-08-23):** this ledger sat self-stamped
> "Verified 2026-07-09" for ~7 weeks while three GitHub rows inverted underneath it
> (env protection restored, vulnerability alerts enabled, the bypass-actor design
> changed). An external acquisition-diligence review then read the stale rows as
> current truth and manufactured two P0 findings from them (DIL-004, DIL-006 —
> `docs/reviews/DILIGENCE_2026-08-23_RESPONSE.md`). A ledger whose whole job is
> "the right answer, scannable" is an attack surface when stale, so its re-verify
> is now a dated log line probed by `scripts/operating_calendar.py` (#2832) — going
> quiet turns the dead-man red instead of waiting for the next external audit.

---

## The out-of-IaC ring

| Resource | What it is | Why out-of-IaC | Where defined | How drift is detected | Verified |
|----------|------------|----------------|---------------|-----------------------|----------|
| **DynamoDB table `life-platform`** | Single-table store; billing PAY_PER_REQUEST | Imported via `Table.from_table_name()` — CDK would need ownership to manage it, risking accidental deletion on `cdk destroy` | AWS Console / initial setup | I4 (`test_i4_dynamodb_table_healthy`) — ACTIVE + deletion_protection + PITR checked post-deploy; GSI1/GSI2 asserted by same test | 2026-08-23 live: ACTIVE, deletion protection ON, PITR ENABLED, PAY_PER_REQUEST |
| **DynamoDB GSI1** (reading due-date sparse index) | `sk_due_date` GSI for reading domain | ADR-097 sparse index; CDK can't add GSIs to an imported table | AWS Console | I4 GSI assertion | 2026-08-23 live: present |
| **DynamoDB GSI2** (reading overview index) | `sk_overview` GSI for book overview queries | Same as GSI1 | AWS Console | I4 GSI assertion | 2026-08-23 live: present |
| **S3 bucket policy `matthew-life-platform`** | Denies `s3:DeleteObject` on `raw/*`, `config/*`, `uploads/*`, `generated/*` for `matthew-admin` role | Protects raw data; CDK would need to own the bucket to manage the policy | AWS Console / `deploy/bucket_policy.json` | `ProtectDataFromDeployScripts` statement; weekly drift sentinel checks critical bucket settings | 2026-08-23 live: `ProtectDataFromDeployScripts` statement present |
| **S3 lifecycle configuration `matthew-life-platform`** | Per-prefix retention/expiration rules (deploys/, raw/, uploads/, generated/, config/, cloudtrail/, remediation-log/dispatch-dedupe/, mcp-audit/) | Bucket is imported via `Bucket.from_bucket_name()` — CDK cannot attach lifecycle rules to an imported bucket | `deploy/apply_s3_lifecycle.sh` (declarative FULL config — a put replaces every rule; #886) | Retention table in `docs/DATA_GOVERNANCE.md` mirrors the script; no automated drift assertion yet (DIL-026 → D3 of #3042 — `imports/` is a known uncovered prefix) | 2026-08-23 live: lifecycle present (14 rules) |
| **S3 replication configuration `matthew-life-platform`** (DIL-027, #3042) | One rule: `raw/*` → `matthew-life-platform-raw-backup` (us-east-2), `Status: Enabled`, `DeleteMarkerReplication: Disabled` (a delete on the source must NOT propagate — the difference between a backup and a mirror) | Same imported-bucket constraint as the two rows above: `Bucket.from_bucket_name()` cannot carry a replication configuration. **Only this source-side leg is out-of-IaC** — the DESTINATION bucket, its delete-protection Deny, its lifecycle and the replication ROLE are all CDK-owned in `cdk/stacks/backup_stack.py` (`LifePlatformBackup`) | `deploy/s3_replication.json` (declarative FULL config — a put REPLACES every rule, same trap as the lifecycle script), applied by `deploy/apply_s3_replication.sh --apply` (dry-run by default; preflights source versioning, destination versioning and the role's existence before writing) | **`deploy/sentinel_replication.py`, weekly** (#3042) — asserts the live configuration against the JSON field-by-field (role, status, prefix, destination, delete-marker), asserts destination versioning, then probes REAL objects: a recent `raw/` key must be `COMPLETED` **and** head_object on the replica, and the zone's earliest key must have a replica at all (replication is not retroactive — this is what keeps the S3 Batch Replication backfill from being silently skipped). Reports `degraded`, never `clean`, when it could observe nothing. Identifier parity with `cdk/stacks/constants.py` is CI-guarded by `tests/test_raw_replication_dil027.py` | **NOT YET APPLIED** as of 2026-08-24 — this row documents the DESIRED posture (posture-file rule); applying it is the post-merge deploy sequence in the DIL-027 PR |
| **S3 lifecycle configuration `matthew-life-platform`** | Per-prefix retention/expiration rules (deploys/, site/, raw/, imports/, uploads/, generated/, claude-memory-backup/, datadrops-archive/, config/, cloudtrail/, remediation-log/dispatch-dedupe/, mcp-audit/) | Bucket is imported via `Bucket.from_bucket_name()` — CDK cannot attach lifecycle rules to an imported bucket | `deploy/apply_s3_lifecycle.sh`, reading `deploy/s3_lifecycle.json` (declarative FULL config — a put replaces every rule; #886) | Retention table in `docs/DATA_GOVERNANCE.md` mirrors the JSON; **automated drift assertion now live** (DIL-026/#2799, 2026-08-24): `deploy/drift_sentinel.py::check_s3_lifecycle` compares live `get-bucket-lifecycle-configuration` against `deploy/s3_lifecycle.json` rule-by-ID weekly, mutation-proved both directions (missing/extra/changed rule). `imports/` — the known uncovered prefix — is now covered (7d noncurrent, keep 1) | 2026-08-23 live: lifecycle present (14 rules); **pending post-merge `bash deploy/apply_s3_lifecycle.sh`** to apply the 15th (`imports/`) rule — CDK deploy alone does not touch this out-of-IaC surface |
| **SES sending identity** | Verified sender domain behind the daily brief and digest emails. **Corrected 2026-08-23:** the live identity is the DOMAIN `mattsusername.com` (plus `aws.mattsusername.com`), SESv2 domain verification — not an address-level identity as this row previously said | SES identity verification is repo-external account state; CDK manages configuration sets but not DKIM/SPF outside Route 53 | AWS Console (SESv2 verified identities) | Manual quarterly check; SES bounce/complaint metrics in CloudWatch | 2026-08-23 live: both domains VerificationStatus SUCCESS, sending enabled |
| **Route 53 / DNS** | `averagejoematt.com` → CloudFront; MX records for SES | DNS is the root of trust — CDK would need to import the hosted zone; deliberate choice to keep DNS outside automated teardown | AWS Console (Route 53 hosted zone) | Monthly manual check; CloudFront availability alarm fires if DNS is broken | 2026-08-23 live: zone present, apex resolving to CloudFront |
| **CloudFront function version pins** | `v4-redirects` function version pinned in CloudFront distribution | CloudFront function versions are immutable; the CDK stack references the distribution by ID (`E3S424OXQZ8NBE`) but doesn't manage function associations in the current config | AWS Console | `cdk diff` flags function-version drift; visual QA catches broken redirects | 2026-08-23 live: `v4-redirects` attached (viewer-request, default behavior) |
| **SSM control parameters** | `/life-platform/{budget-tier,experiment-cycle,pause-mode,remediation-mode,partner-email}` | Operational state that must survive a CDK re-deploy; SSM is the runtime config store | Set by Lambdas or operator commands | `deploy/session_postflight.py` reads budget-tier; remediation agent reads remediation-mode; no automated assertion for all 5 | 2026-08-23 live: all 5 present |
| **EventBridge Lambda-schedule rules** | Every `cron(...)`/`rate(...)` rule that triggers a life-platform Lambda | **None today — fully CDK-owned.** The only historical exceptions were two hand-created rules, `pipeline-health-check-daily` and `subscriber-onboarding-daily`, created by the pre-CDK setup scripts `deploy/setup_pipeline_health_check.sh` / `deploy/setup_subscriber_onboarding.sh` (now tombstoned — see `docs/_lint/tombstones.txt`) — each duplicated a schedule CDK already owned. Deleted 2026-07-18 (#1257); this row + I24 exist so the class doesn't quietly recur | `cdk/stacks/*.py` — either `create_platform_lambda(..., schedule=...)` (the shortcut, auto-creates + attaches the Rule) or a manual `events.Rule(...)` + `.add_target(targets.LambdaFunction(...))` (the documented "manual events.Rule escape hatch" in `operational_stack.py`, used when the shortcut's auto-enable isn't wanted, or for a second schedule on an already-scheduled Lambda) | I24 (`test_i24_eventbridge_rule_lambda_targets_are_cdk_managed`) — every ENABLED rule targeting a life-platform Lambda must resolve to a CDK declaration or an explicit entry in `EVENTBRIDGE_RULE_EXEMPTIONS` | CI-guarded (I24 post-deploy); prose re-read 2026-08-23 |
| **GitHub `main` branch ruleset** (`main-block-force-push-and-deletion`, id `19162901`) | Blocks non-fast-forward pushes + branch deletion on `main` only — no required checks, no PR rule | GitHub rulesets aren't CDK/IaC-managed (repo-config, not AWS); created directly via `gh api` (#1325) so the reconcile bot's normal pushes and squash-merges stay unaffected | GitHub repo settings (Rules → Rulesets); documented posture: `deploy/github_posture.json` `main_ruleset` (mirrors `docs/CONVENTIONS.md`'s drift-discovery table); one-command-ready payload in PR #1325's body | Weekly drift sentinel `check_github_config()` (#1320) — GET-only assert: enforcement `active`, rules exactly `[deletion, non_fast_forward]`, `refs/heads/main` included; a deleted/weakened ruleset is drift. NB: with only the workflow's `GITHUB_TOKEN` this surface may fail soft to a needs-owner line (fine-grained Administration:read via the optional `GH_POSTURE_TOKEN` secret unlocks it); manual fallback `gh api repos/<owner>/<repo>/rulesets/19162901` | 2026-08-23 live: active, rules exactly `[deletion, non_fast_forward]`, `refs/heads/main` |
| **GitHub `main` required-status-checks ruleset** (`main-required-fast-lane`, #1662) | The merge gate: one `required_status_checks` rule on `refs/heads/main` scoped to the FAST lane — `Collect + deploy-critical + format` (pr-checks.yml) + `gitleaks (PR commit range only, not full history)` (secret-scan.yml). `strict` off; one bypass actor — a **`User` actor for the repo owner** (`averagejoematt`, `always`), NOT the github-actions Integration this row previously described: #2198 measured that an Integration bypass actor 422s on a personal-account repo, so ci-cd.yml's `reconcile` job pushes with the `RECONCILE_PUSH_TOKEN` fine-grained PAT to match the User bypass (full rationale in `deploy/github_posture.json`) | Repo-config, not AWS/CDK. A **ruleset** rather than classic branch protection precisely because classic protection has no per-actor bypass and would reject the reconcile bot's push on every merge day (ADR-148) | `scripts/apply_branch_protection.py --apply` is the ONLY sanctioned writer (dry-run by default; never enables required reviews; refuses to touch ruleset `19162901`). Desired state: `deploy/github_posture.json` `main_required_checks_ruleset`. Never hand-edit in the GitHub UI | Two legs. LIVE: weekly drift sentinel `check_github_config()` — enforcement, ref, the exact context SET, the strict flag, the User bypass, and any out-of-band approval-shaped rule; same fail-soft needs-owner behaviour as the row above. OFFLINE: `tests/test_branch_protection_spec.py` runs the applier's `preflight_contexts()` against the real workflow YAML, so a `paths:` filter, an `if:` gate, or a job rename on a required context reds the suite instead of wedging PRs. On-demand: `python3 scripts/apply_branch_protection.py --check` | 2026-08-30 live: **APPLIED** — ruleset created by `--apply` after the owner issued `RECONCILE_PUSH_TOKEN` in-session (the #3207 blocker); `--check` clean the same minute, and the very next direct push to main exercised the User bypass live. Posture entry carries `"applied": true` + `applied_on`; `tests/test_posture_pending_marker.py` holds this prose and that marker in agreement |
| **GitHub repo merge settings** (`allow_auto_merge`) | Auto-merge on: the operator arms a PR once and GitHub lands it when the required checks go green — the reason fast-lane required checks cost no wall-clock (ADR-148) | Repo-config toggle, owner-only; not AWS/CDK | `scripts/apply_branch_protection.py --apply` (PATCH `/repos/{owner}/{repo}`). Desired state: `deploy/github_posture.json` `repo_settings` | Weekly drift sentinel `check_github_config()` — `repo_settings` surface; manual fallback `gh api repos/<owner>/<repo> --jq .allow_auto_merge` | 2026-08-30 live: **APPLIED** — `allow_auto_merge=true`, flipped in the same `--apply` as the row above; `"applied": true` + `applied_on` on the `repo_settings` entry, prose/marker agreement pinned by `tests/test_posture_pending_marker.py` |
| **GitHub `production` environment protection** | The deploy-approval control ci-cd.yml's Deploy job binds to (`environment: production`) | GitHub repo-config, not AWS/CDK; was silently DROPPED by the 2026-07-13 private flip (#1319, `reference_github_env_protection_private_flip`) and **RESTORED 2026-07-20** after the public flip (#1319 closed VERIFIED-DONE). A future private flip drops it again — flip the posture entry in the SAME PR that amends the claiming docs | GitHub repo settings (Environments → production); documented posture: `deploy/github_posture.json` `environment_production` (mirrors ADR-065 / CLAUDE.md / ci-cd.yml claims) | Weekly drift sentinel `check_github_config()` (#1320) — asserts a `required_reviewers` protection rule exists iff the posture says so; manual fallback `gh api repos/<owner>/<repo>/environments/production` | 2026-08-23 live: `required_reviewers` rule PRESENT (reviewer = owner) and actively gating deploy runs. **This row previously still described the dropped-gate state ("fires today by design") — that staleness is what manufactured diligence finding DIL-004** |
| **GitHub vulnerability/Dependabot alerts** | The CVE-remediation channel ADR-082 + ci-cd.yml's pip-audit step name ("Dependabot will open a bump PR") | GitHub repo-config toggle, owner-only | GitHub repo settings (Advanced Security); documented posture: `deploy/github_posture.json` `vulnerability_alerts` | Weekly drift sentinel `check_github_config()` (#1320) — asserts enablement matches posture. Needs fine-grained Administration:read (the `GH_POSTURE_TOKEN` secret) — fails soft to a needs-owner line with the workflow token; manual fallback `gh api repos/<owner>/<repo>/vulnerability-alerts` (204 = on, 404 "disabled" = off) | 2026-08-23 live: **ENABLED** (204; automated security fixes enabled, unpaused; 0 open alerts). Enabled by the owner 2026-07-20 after the public flip (SDLC P2-4 closed). **This row previously still said "alerts disabled live" — that staleness is what manufactured diligence finding DIL-006** |
| **GitHub Actions push-event run delivery** | Every trigger-matching merge to `main` must queue its push-event workflow runs (ci-cd / site-deploy / docs-ci / v4-gate) — the deploy pipeline's event supply | Not config at all — GitHub-side event delivery + Actions billing state; failed silently for ~3h / six merges on 2026-07-19 (#1544) | n/a (behavioral invariant); thresholds: `deploy/github_posture.json` `push_run_detector`; expected-trigger path filters: `PUSH_TRIGGER_GLOBS` in `deploy/sentinel_github.py` (re-exported by `deploy/drift_sentinel.py`) (parity-tested against the workflow YAMLs) | Weekly drift sentinel `check_github_push_runs()` (#1544) — compares `/commits?sha=main` vs `/actions/runs?event=push`: a trigger-matching merge past the 30-min grace with no run = drift (stalled); older uncovered commits are reported as `gap_commits` but never alarmed (#1782 — a multi-commit push only ever gets one run, at its HEAD, so N-1 uncovered predecessors is the normal shape, not a miss); path-filter aware so docs-/handover-only commits never false-alarm | Sentinel-owned (behavioral); prose re-read 2026-08-23 |

---

## Automated assertions (wired to CI)

| Check | What | Where |
|-------|------|-------|
| I4 `test_i4_dynamodb_table_healthy` | DynamoDB ACTIVE + deletion_protection + PITR + GSI1/GSI2 | `tests/test_integration_aws.py` — runs in `post-deploy-checks` CI job |
| I8 `test_i8_s3_bucket_and_config_files` | S3 bucket accessible + critical config files present | Same job |
| I24 `test_i24_eventbridge_rule_lambda_targets_are_cdk_managed` | Every ENABLED EventBridge rule targeting a life-platform Lambda resolves to a CDK-declared schedule (or an explicit `EVENTBRIDGE_RULE_EXEMPTIONS` entry) — catches the #1257 hand-created-rule class | Same job |
| Weekly drift sentinel | Compares live infra config vs CDK code for Lambda timeout/memory/env drift | `deploy/drift_sentinel.py` — Monday-gated step in `.github/workflows/remediation-agent.yml` (cron `45 14 * * 1,3,5`; self-skips unless Monday UTC or manual dispatch) |
| Weekly GitHub-side leg (#1320/#1544/#1662) | GET-only `gh api` asserts of the six GitHub rows above vs `deploy/github_posture.json` (`check_github_config`) + main-push run liveness (`check_github_push_runs`); divergence lands in the same drift-log → remediation-report channel, scope gaps as a needs-owner line | Same Monday-gated sentinel step; `PUSH_TRIGGER_GLOBS` parity guarded by `tests/test_drift_sentinel.py::test_push_trigger_globs_match_workflows` |
| Weekly `raw/` replication leg (#3042/DIL-027) | Live replication configuration vs `deploy/s3_replication.json` + destination versioning + a wire-real object probe (recent object `COMPLETED` AND present on the replica; earliest object present at all) | `deploy/sentinel_replication.py::check_raw_replication`, registered in the same Monday-gated sentinel sweep; offline parity + can-it-fail coverage in `tests/test_raw_replication_dil027.py` |
| Monthly ledger re-verify dead-man (#2832, 2026-08-23) | The `managed-where-reverify` entry in `scripts/operating_calendar.py` reads the newest dated `- Re-verified:` line below; a ledger quiet past its window turns the daily `operating-calendar.yml` run red — the 7-week silent-staleness class cannot recur unseen | `scripts/operating_calendar.py --due` (daily workflow) |

---

## Recovery runbook

### DynamoDB deletion protection accidentally disabled
```bash
aws dynamodb update-table \
  --table-name life-platform \
  --deletion-protection-enabled \
  --region us-west-2
```

### DynamoDB PITR disabled
```bash
aws dynamodb update-continuous-backups \
  --table-name life-platform \
  --point-in-time-recovery-specification PointInTimeRecoveryEnabled=true \
  --region us-west-2
```

### S3 bucket policy lost
```bash
aws s3api put-bucket-policy \
  --bucket matthew-life-platform \
  --policy file://deploy/bucket_policy.json
```

### SES identity verification lost
Re-verify via AWS Console → SES → Verified Identities (domain `mattsusername.com`).
Check DNS MX + DKIM records in Route 53 still point to SES endpoints.

---

## Maintenance convention

Update this ledger when a resource moves in or out of IaC, or when a new out-of-band
resource is deliberately created. Link this file in the PR body. If an automated
assertion is added, add a row to the "Automated assertions" table.

**Re-verify monthly** (the #2832 dead-man below enforces this): walk every row against
live state — `gh api` for the GitHub rows, read-only `aws` calls for the AWS rows —
and append a dated line to the log. Update the row's Verified cell for anything you
actually probed; never re-stamp a row you didn't.

## Re-verify log (newest first — the operating-calendar probe reads these lines)

- Re-verified: 2026-08-23 — every row probed live (gh api + read-only AWS). Three rows
  had inverted while stale and were corrected: production env protection (restored
  2026-07-20, row still said dropped → DIL-004), vulnerability alerts (enabled
  2026-07-20, row still said disabled → DIL-006), fast-lane bypass actor (User per
  #2198, row still said Integration). Also corrected: SES identity is domain-level;
  `main-required-fast-lane` + `allow_auto_merge` APPLIED 2026-08-30 (D0.6 done)
  (D0.6). Cadence entry added to `scripts/operating_calendar.py`.
