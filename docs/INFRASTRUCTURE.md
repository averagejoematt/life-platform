# Life Platform — Infrastructure Reference

> **Status:** canonical · **Owner:** Matthew · **Verified:** 2026-10-17

> Quick-reference for all URLs, IDs, and configuration. No secrets stored here.
> Last updated: 2026-10-19 (v8.6.0 — 108 Lambdas, 26 active secrets, 88 MCP tools, ~135 alarms)

---

## AWS Account

| Field | Value |
|-------|-------|
| Account ID | `205930651321` |
| Region | `us-west-2` (Oregon) for everything except: `us-east-1` (`LifePlatformWeb` — CloudFront, Lambda@Edge, OG image, email-subscriber, progress-viewer) and `us-east-2` (`LifePlatformBackup` — the cross-region replica of `raw/`, #3042) |
| Budget | $215/month all-in, **enforced** (ADR-063 + ADR-133 amendments — was $75, then $85, then $150; floats to $252 on reader-traffic surge; alerts at 50/70/85/100%; cost-governor degrades AI by tier) |
| CloudTrail | `life-platform-trail` → S3 (data events enabled on `raw/` and `uploads/` S3 prefixes) |
| Account Lambda concurrency quota | **100** (`aws lambda get-account-settings`, us-west-2, read 2026-10-17; the old default of 10 was raised after the 2026-05-19 request) |

### CDK stacks

Entry point `cdk/app.py`; one file per stack in `cdk/stacks/`. Deploy with `bash deploy/cdk_deploy.sh <StackName>` (drift-guarded).

| Stack | Region | File | Owns |
|-------|--------|------|------|
| `LifePlatformCore` | us-west-2 | `core_stack.py` | SNS topics (alerts / digest / paging), ingestion DLQ, AWS Budget, Bedrock batch role. The DynamoDB table and S3 bucket are **looked up, not CDK-managed** |
| `LifePlatformIngestion` | us-west-2 | `ingestion_stack.py` | ingestion Lambdas, the Health Auto Export HTTP API |
| `LifePlatformCompute` | us-west-2 | `compute_stack.py` | compute / coach Lambdas |
| `LifePlatformEmail` | us-west-2 | `email_stack.py` | email / digest / chronicle Lambdas |
| `LifePlatformOperational` | us-west-2 | `operational_stack.py` | canary, freshness, key-rotator, digest queue, ops Lambdas |
| `LifePlatformServe` | us-west-2 | `serve_stack.py` | `life-platform-site-api`, `life-platform-site-api-ai`, Telegram Lambdas |
| `LifePlatformMcp` | us-west-2 | `mcp_stack.py` | `life-platform-mcp` + `life-platform-mcp-warmer` (768 MB, python3.12) |
| `LifePlatformMonitoring` | us-west-2 | `monitoring_stack.py` (+ `monitoring_*.py`) | alarms, dashboards |
| `LifePlatformWeb` | **us-east-1** | `web_stack.py` | the four CloudFront distributions, `email-subscriber`, `life-platform-og-image`, `progress-viewer` |
| `LifePlatformBackup` | **us-east-2** | `backup_stack.py` | `raw/` replica |

Per-stack Lambda membership is the `stack` field of each entry in `model/platform_model.json` (`lambdas` plane).

---

## Domain & DNS

| Field | Value |
|-------|-------|
| Domain | `averagejoematt.com` |
| Registrar | NameCheap, Inc. — whois-verified 2026-07-10 (not Route53; DNS is still served by Route53's hosted zone below). Full detail: `docs/ACCOUNTS.md` |
| Hosted Zone ID | `Z063312432BPXQH9PVXAI` |
| Nameservers | `ns-214.awsdns-26.com` · `ns-1161.awsdns-17.org` · `ns-858.awsdns-43.net` · `ns-1678.awsdns-17.co.uk` |

### DNS Records

| Subdomain | Type | Target |
|-----------|------|--------|
| `averagejoematt.com`, `www.averagejoematt.com` | A (alias) | `d2qlzq81ggequb.cloudfront.net` (public site, `E3S424OXQZ8NBE`) |
| `dash.averagejoematt.com` | A (alias) | `d14jnhrgfrte42.cloudfront.net` |
| `blog.averagejoematt.com` | A (alias) | `d1aufb59hb2r1q.cloudfront.net` |
| `buddy.averagejoematt.com` | A (alias) | `d1empeau04e0eg.cloudfront.net` |

---

## Web Properties

| Property | URL | Auth | CloudFront ID |
|----------|-----|------|---------------|
| Public Site | `https://averagejoematt.com/` | None (public) | `E3S424OXQZ8NBE` |
| Dashboard | `https://dash.averagejoematt.com/` | Lambda@Edge password (`life-platform-cf-auth`) | `EM5NPX6NJN095` |
| Blog | `https://blog.averagejoematt.com/` | None (public) | `E1JOC1V6E6DDYI` |
| Buddy Page | `https://buddy.averagejoematt.com/` | None (public — Tom's accountability page, no PII) | `ETTJ44FT0Z4GO` |

Dashboard and Buddy passwords are stored in **Secrets Manager** (not here).

---

## MCP Server

| Field | Value |
|-------|-------|
| Lambda | `life-platform-mcp` (768 MB, python3.12) |
| Function URL (remote) | `<not committed — SEC-02 #780; read live: aws lambda get-function-url-config --function-name life-platform-mcp --region us-west-2>` |
| Auth (remote) | OAuth 2.1 auto-approve + HMAC Bearer via `life-platform/mcp-api-key` secret (auto-rotates every 90 days) |
| Auth (local) | `mcp_bridge.py` → `.config.json` → Function URL |
| Tools | **88** across **37** tool modules (`mcp/tools_*.py`) |
| Cache warmer | `life-platform-mcp-warmer` pre-computes the `steps` list in `mcp/warmer.py` nightly into the DDB cache (count: read the list) |

---

## API Gateway

| Field | Value |
|-------|-------|
| Name | `health-auto-export-api` (HTTP API, `apigwv2`, declared in `ingestion_stack.py`) |
| ID | `p6clybdkkc` (read live 2026-10-17; the earlier `a76xwxt2wa` no longer exists) |
| Endpoint | `https://p6clybdkkc.execute-api.us-west-2.amazonaws.com` |
| Purpose | Webhook ingestion for Health Auto Export (Apple Health CGM, BP, State of Mind) |

---

## S3

| Field | Value |
|-------|-------|
| Bucket | `matthew-life-platform` |
| Default encryption | **AES256** (verified `get-bucket-encryption` 2026-10-17; the old S3 KMS CMK was retired, ADR-053/054/058 — `core_stack.py`. The `raw/` KMS-readability inventory is `docs/audits/RAW_KMS_UNREADABLE_INVENTORY_2026-10.md`) |
| Key prefixes | Top-level prefixes seen 2026-10-17: `raw/` (source data; layout per source = `raw_layout` in `lambdas/ingestion/source_registry.py`) · `site/` (public website) · `generated/` (Lambda-generated files, ADR-046; anonymously readable at the origin) · `config/` (authored config, mirror of `config/`) · `dashboard/` · `blog/` · `buddy/` · `uploads/` (MacroFactor CSVs) · `imports/` (Apple Health XML) · plus operational logs and archives (`deploys/`, `exports/`, `drift-log/`, `remediation-log/`, `mcp-audit/`, `pip-audit/`, `reconciliation/`, `coherence-log/`, `ai-canary-log/`, `dead-letter-archive/`, `datadrops-archive/`, `session-artifacts/`, `story-desk/`, `recap/`, `panelcast-holds/`, `claude-memory-backup/`, `design-sketches/`, `assets/`). A private artifact never goes under a public prefix. |

---

## DynamoDB

| Field | Value |
|-------|-------|
| Table | `life-platform` |
| Key schema | attributes `pk` / `sk`: `pk` = `USER#matthew#SOURCE#<source>` · `sk` = `DATE#YYYY-MM-DD` |
| Indexes | **Two sanctioned GSIs** (ADR-097): `GSI1`, `GSI2` — contract in `lambdas/reading/reading_keys.py`; a third requires an ADR |
| Protection | Deletion protection ON · PITR enabled (35-day rolling) — verified live 2026-10-17 |
| Encryption | KMS CMK `alias/life-platform-dynamodb` (key `444438d1-a5e0-43b8-9391-3cd2d70dde4d`) · annual auto-rotation ON |
| Partitions | The census is `lambdas/experiment/phase_taxonomy.SOURCE_CLASS` (ADR-077), surfaced in the `partitions` plane of `model/platform_model.json`; field-level contract in `docs/SCHEMA.md`. Never hand-list them here |

---

## SES (Email)

| Field | Value |
|-------|-------|
| Sender / Recipient | `awsdev@mattsusername.com` |
| Inbound rule set | `life-platform-inbound` (active) |
| Inbound rules | `insight-capture` (routes `insight@aws.mattsusername.com` → S3) and `insight-auth-gate` |
| Outbound configuration set | `life-platform-emails` — wired to `daily-brief`, `weekly-digest`, `monthly-digest`, `partner-weekly-email` |

---

## SNS

| Field | Value |
|-------|-------|
| Alert topics | `life-platform-alerts` (urgent → email to `awsdev@mattsusername.com`) · `life-platform-alerts-digest` (drained daily via the digest queue, ADR-050) · `life-platform-paging` (SMS, the named P1 set only, ADR-143) · `life-platform-ses-events` |
| CloudWatch alarms | **~135 metric alarms** (base + invocation-count + DDB item size + canary + duration + freshness + pipeline health) |

---

## SQS

| Field | Value |
|-------|-------|
| Dead-letter queue | `life-platform-ingestion-dlq` (Core) · `life-platform-subscriber-dlq` (Web) · `life-platform-alerts-digest-queue` (digest accumulator, Operational) |
| DLQ coverage | All ingestion Lambdas (MCP + webhook excluded — request/response pattern) |

---

## ACM Certificates (us-east-1, required by CloudFront)

| Domain | Purpose |
|--------|---------|
| `dash.averagejoematt.com` | Dashboard CloudFront |
| `blog.averagejoematt.com` | Blog CloudFront |
| `buddy.averagejoematt.com` | Buddy CloudFront |
| `averagejoematt.com` | Public-site CloudFront |

All DNS-validated via Route 53 CNAME records.

---

## Secrets Manager (26 active secrets)

All under prefix `life-platform/`. No values stored in this doc — access via AWS console or CLI. The table below is a subset of the long-lived ones; the authoritative name set is `KNOWN_SECRETS` in `tests/test_secret_references.py`.

| Secret | Type | Fields / Notes |
|--------|------|----------------|
| `whoop` | OAuth | Auto-refreshed by Lambda |
| `eightsleep` | OAuth | Auto-refreshed by Lambda |
| `eightsleep-client` | Client credential | Companion to `eightsleep`; required by Eight Sleep API |
| `strava` | OAuth | Auto-refreshed by Lambda |
| `withings` | OAuth | Auto-refreshed by Lambda |
| `garmin` | Session | garth OAuth tokens. Garmin is paused (ADR-074); AWS shows this secret in its deletion window since 2026-10-12, though `tests/test_secret_references.py` `KNOWN_SECRETS` still lists it — see the PR note on that drift |
| `ai-keys` | JSON bundle | `anthropic_api_key` + `mcp_api_key` (90-day auto-rotation) |
| `ingestion-keys` | JSON bundle | `notion_api_key` + `todoist_api_key` + `habitify_api_key` + `dropbox_app_key` + `health_auto_export_api_key`. COST-B pattern — single secret, per-service key fields. Now the **sole** source for Notion + Dropbox creds after the dedicated secrets were soft-deleted 2026-05-17. |
| `habitify` | API key | Dedicated Habitify API token. Also present in `ingestion-keys` — see ADR-014 for governing principle. |
| `todoist` | API key | Todoist API token used by MCP write tools (TD-23). |
| `mcp-api-key` | Rotation target | MCP server bearer token consumed by `ai-keys`. 90-day auto-rotation via `life-platform-key-rotator`. |
| `site-api-ai-key` | API key | Subscriber validation key for site-api-ai Lambda (ADR-041). |

**Soft-deleted (30-day recovery window):**
- `life-platform/notion` — deleted 2026-05-17 (consumer migrated to `ingestion-keys`)
- `life-platform/dropbox` — deleted 2026-05-17 (consumer migrated to `ingestion-keys`)
- `life-platform/anthropic-api-key` — deleted 2026-05-16 (orphan, no consumer)

**Hard-deleted (historical):** `api-keys` (2026-03-14), `webhook-key` (2026-03-14), `google-calendar` (2026-03-15, ADR-030).

---

## Lambdas

The census is the `lambdas` plane of `model/platform_model.json` (generated from the `function_name=` declarations in `cdk/stacks/`; count and per-stack membership are there, not here — the header literal above is sync-owned). Live `aws lambda list-functions` returns a few more than the model (log-retention helpers and similar CDK-internal functions). Domain grouping of the source is the `lambdas/` package tree (ADR-146); the function→source map is `ci/lambda_map.json` (rendered into `.claude/skills/deploy/SKILL.md`).

Named here only where an infrastructure reader needs the role: `life-platform-mcp` + `life-platform-mcp-warmer` (MCP), `life-platform-site-api` + `life-platform-site-api-ai` (website API), `life-platform-key-rotator`, `life-platform-cost-governor` (budget tier), `life-platform-canary` / `life-platform-qa-smoke` (probes), `life-platform-alert-digest`, `life-platform-dlq-consumer`, `life-platform-freshness-checker`.

### us-east-1 functions (`LifePlatformWeb` plus two standalone)
- `life-platform-cf-auth` (Lambda@Edge) — attached to dashboard CloudFront (`EM5NPX6NJN095`), password-gates `dash.averagejoematt.com`
- `life-platform-buddy-auth` (Lambda@Edge) — function exists; buddy CloudFront currently runs **without auth** (intentionally public; see Web Properties table). Source for the Edge auth functions: `lambdas/cf-auth/index.mjs`
- `life-platform-og-image` — OG image generation (handler `og_image_lambda.handler`, source `lambdas/og_image_lambda.mjs`)
- `email-subscriber` — Subscribe form intake (`/api/subscribe*`)
- `progress-viewer` — private progress-photo viewer (#3760)

### Shared-code distribution — the retired layer (#781/ADR-131)
Canonical in `docs/CONVENTIONS.md` §1. Old layer versions remain published in AWS (`RemovalPolicy.RETAIN`) but nothing references them. Dependency layers with real third-party packages remain (they are NOT the shared layer): Pillow (og-image-generator), garth (Garmin ingestion).

---

## EventBridge

Rules are declared as `schedule=` on each function in `cdk/stacks/` (CDK-managed); the schedule census is the `schedules` plane of `model/platform_model.json`. Never hand-state a cron here.

| Field | Value |
|-------|-------|
| Rule count | `aws events list-rules --region us-west-2` (the model's `schedules` plane is the declared set; the live list also includes CDK-internal rules) |
| Timezone | Fixed UTC cron (no DST drift; see CLAUDE.md convention) |
| Chronicle pipeline | `wednesday-chronicle` and `chronicle-email-sender` schedules: read their rows in the model |

---

## KMS

| Field | Value |
|-------|-------|
| Key alias | `alias/life-platform-dynamodb` |
| Key ID | `444438d1-a5e0-43b8-9391-3cd2d70dde4d` |
| Key ARN | `arn:aws:kms:us-west-2:205930651321:key/444438d1-a5e0-43b8-9391-3cd2d70dde4d` |
| Purpose | DynamoDB table `life-platform` SSE (server-side encryption) |
| Rotation | Auto-rotation ON (verified `get-key-rotation-status` 2026-10-17, period 365 days) |
| Key policy | Root admin + all Lambda execution roles + DynamoDB service principal |
| CloudTrail | Every Decrypt/GenerateDataKey call logged |

The key was created out-of-band (the `deploy/p1_kms_dynamodb.sh` script this section used to cite no longer exists); it is not declared in `cdk/stacks/`.

---

## Key Config Files (S3)

| Key | Purpose |
|-----|---------|
| `config/user_goals.json` (local source; generates `lambdas/common/constants.py`) | Genesis, baseline and personal targets. `config/profile.json` no longer exists locally or in S3 |
| `config/board_of_directors.json` | Expert personas for AI-generated content (members count: read the file) |
| `config/character_sheet.json` | 7 pillar weights, tier definitions, leveling thresholds |
| `config/project_pillar_map.json` | Todoist project → platform pillar mapping (Monday Compass) |

The full index of `config/` is `config/README.md`.

---

## Local Project Structure

```
~/dev/life-platform/
├── mcp_server.py          # MCP Lambda entry
├── mcp_bridge.py          # Local Claude Desktop bridge
├── mcp/                   # MCP tool modules (tools_*.py) + helpers; registry.py wires them
├── lambdas/               # Lambda source, packaged by domain (ADR-146)
├── cdk/                   # app.py + stacks/
├── deploy/                # Deploy scripts (run in terminal, never via MCP)
├── config/                # Authored runtime config (README.md indexes it)
├── model/                 # platform_model.json — the generated system model
├── site/                  # Static website (generator-owned shells, scripts/v4_build_*.py)
├── docs/                  # All documentation (.md)
├── handovers/             # Live session pointer only (history: session-archive branch)
├── scripts/ tests/ qa/ seeds/ setup/ infra/ ci/ remediation/ ledgers/
└── .config.json           # Local MCP bridge credentials (gitignored)
```

---

**Verified:** 2026-10-17 — re-checked against `cdk/app.py`, `cdk/stacks/*_stack.py`, `model/platform_model.json` and read-only AWS (names only): `dynamodb describe-table` / `describe-continuous-backups`, `s3api get-bucket-encryption` / `list-objects-v2 --delimiter /`, `cloudtrail get-event-selectors`, `cloudfront list-distributions`, `apigatewayv2 get-apis`, `sns list-topics`, `sqs list-queues`, `secretsmanager list-secrets`, `ses describe-active-receipt-rule-set`, `sesv2 list-configuration-sets`, `kms get-key-rotation-status`, `lambda get-account-settings`. DNS A records, nameservers, ACM certificate domains and CloudFront IDs were also re-read. Not re-verified: the CloudWatch alarm inventory (sync-owned literal), the Dashboard/Buddy password mechanics, and the Secrets table's per-secret field notes. (The shared layer was retired #781 — there is no "layer version" to verify for it anymore. `cdk/stacks/constants.py:37` is `GARTH_LAYER_VERSION`, the *dependency* layer for Garmin ingestion, not the retired shared layer.)
