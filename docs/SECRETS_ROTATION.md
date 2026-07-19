# Secrets Rotation Procedures

> **Status:** canonical · **Owner:** Matthew · **Verified:** 2026-07-19

Last updated: 2026-07-19 (#1329 — manual-rotation staleness routed to the remediation agent's curated needs-human email instead of raw daily SNS; one-command `deploy/rotate_ai_keys.sh` prep. Prior: #935 — Whoop re-auth script moved to `setup/setup_whoop_auth.py`, callback-server flow)

Phase 2.6 (2026-05-16): single source of truth for how each Life Platform secret is rotated. Used by both the operator (manual rotations) and the freshness checker (staleness alerts).

**Update (2026-07-10):** the 2026-05 deletion-window era is over — 21 active secrets, 0 deleting (live-verified; inventory: `SECRETS_MAP.md`). `notion` was restored 2026-05-24 and sits live-but-idle (retire-candidate, owner decision pending); `dropbox` + `anthropic-api-key` completed deletion. The `ingestion-keys` bundle remains authoritative for its members.

## Summary table

| Secret | Type | Rotation | Cadence | Alert threshold |
|--------|------|----------|---------|-----------------|
| `life-platform/mcp-api-key` | Generated | **Auto via key-rotator Lambda** | 90 days | — (managed by Secrets Manager rotation) |
| `life-platform/whoop` | OAuth refresh token | **Auto on use** (per-invocation refresh) | Hourly | 60 days |
| `life-platform/withings` | OAuth refresh token | **Auto on use** | Hourly | 60 days |
| `life-platform/strava` | OAuth refresh token | **Auto on use** | Hourly | 60 days |
| `life-platform/garmin` | OAuth refresh token (garth) | **Auto on use** | 4×/day | 60 days |
| `life-platform/eightsleep` | OAuth refresh token | **Auto on use** | Hourly | 60 days |
| `life-platform/ai-keys` | Anthropic API key | **Manual** | 90 days | 120 days |
| `life-platform/site-api-ai-key` | Anthropic API key (isolated) | **Manual** | 90 days | 120 days |
| ~~`life-platform/notion`~~ | ~~Notion integration token~~ | **Retired 2026-05-19** — bundle is authoritative (see `ingestion-keys` row). Secret scheduled for deletion 2026-05-24. |
| ~~`life-platform/dropbox`~~ | ~~Dropbox app key~~ | **Retired 2026-05-19** — bundle is authoritative (see `ingestion-keys` row). Secret scheduled for deletion 2026-05-24. |
| `life-platform/todoist` | Todoist personal token | **Manual** | 365 days | 120 days |
| `life-platform/habitify` | API key | **Manual** | 180 days | 120 days |
| `life-platform/ingestion-keys` | Bundle (Notion + Habitify + Todoist + Dropbox + HAE) | **Manual** | follow individual | 120 days |
| `life-platform/eightsleep-client` | OAuth client credentials | **Manual** (rare) | 365 days | 120 days |

## Auto-rotation: `mcp-api-key`

Implemented by `lambdas/key_rotator_lambda.py`. Secrets Manager triggers the Lambda 30 days before expiry (90-day rotation). 4-step protocol: `createSecret → setSecret → testSecret → finishSecret`. The MCP Lambda picks up the new key within ~5 min via the Bearer cache TTL.

**No manual action needed.** Verify enablement:
```bash
aws secretsmanager describe-secret --secret-id life-platform/mcp-api-key \
  --query '{Enabled:RotationEnabled,LastRotated:LastRotatedDate,NextRotation:NextRotationDate}'
```

## Auto-on-use: OAuth secrets

Whoop/Withings/Strava/Garmin/EightSleep ingestion Lambdas refresh tokens on every successful API call and write the new refresh token back via `save_secret()` (PR2 of the v7.0.0 alert work added writeback-safety so SM hiccups don't cascade into 401 spam).

**No manual action needed under normal operation.** If a source goes silent for >60 days (e.g., extended absence, source API change), the freshness checker fires an alert and the operator should re-auth manually.

### Manual OAuth re-auth procedures

**Whoop (dead refresh token — full re-auth):**
```bash
python3 setup/setup_whoop_auth.py
# Local callback server on http://localhost:3000/callback + browser OAuth consent
# (same shape as setup/fix_withings_oauth.py); exchanges the code, verifies the new
# token against /recovery, and updates life-platform/whoop in place, preserving
# client_id/client_secret. `--manual` = paste-the-URL fallback (headless / port busy);
# `--backfill` = also trigger whoop-data-ingestion after.
```
Tokens normally never die (auto-refresh + writeback every hourly run; a lost refresh
response = permanently dead token = the 2026-06 outage). Manual fallback if the
script can't run:
```bash
# 1. client_id/client_secret live in the secret:
aws secretsmanager get-secret-value --secret-id life-platform/whoop --query SecretString --output text
# 2. Authorize in a browser (redirect URI registered as http://localhost:3000/callback):
#    https://api.prod.whoop.com/oauth/oauth2/auth?client_id=<id>&redirect_uri=http://localhost:3000/callback&response_type=code&scope=read:recovery%20read:sleep%20read:workout%20read:profile%20read:body_measurement
# 3. Exchange the code at https://api.prod.whoop.com/oauth/oauth2/token (grant_type=authorization_code)
# 4. Write the updated JSON (with the new refresh_token) back:
aws secretsmanager put-secret-value --secret-id life-platform/whoop --secret-string '<updated JSON>'
```
(#935 closed the find-it trap: the script moved `deploy/` → `setup/setup_whoop_auth.py` so it sits with its siblings, and gained the withings-style local callback server.)

**Garmin (the most operationally fraught — 30-day OAuth1 lifetime + rate-limit traps):**
```bash
python3 setup/setup_garmin_browser_auth.py
# Walks through Garmin login + MFA in headed Chromium (Playwright)
# Writes garth tokens to life-platform/garmin
```
After re-auth, if the `auth_breaker` is tripped, clear the marker:
```bash
aws dynamodb delete-item --table-name life-platform \
  --key '{"pk":{"S":"AUTH_BREAKER#matthew#garmin"},"sk":{"S":"STATE"}}' --region us-west-2
```
Then smoke-test: `aws lambda invoke --function-name garmin-data-ingestion --payload '{}' --cli-binary-format raw-in-base64-out /tmp/garmin.json && cat /tmp/garmin.json`.

**Withings:**
```bash
python3 setup/fix_withings_oauth.py
# Local callback server + browser OAuth consent + writes to life-platform/withings
```

**Strava / Eight Sleep:** see `setup/` directory. Dropbox: `python3 setup/setup_dropbox_auth.py`. Eight Sleep: `python3 setup/setup_eightsleep_auth.py`.

## Manual rotation: Anthropic + 3rd-party API keys

These services don't expose a rotation API. Procedure:

### `ai-keys` (Anthropic — daily-brief, weekly digests, coaching)

**One-command prep (#1329):** `bash deploy/rotate_ai_keys.sh` wraps steps 3–4 below —
reads the current secret, merges in the new key (preserving any other fields),
`put-secret-value`s it, then re-reads it back the same way the consumer lambdas
parse it (`{"anthropic_api_key": "..."}`) to confirm it landed. It does NOT call the
Anthropic console (step 1–2, human) and does NOT revoke the old key (step 5, human,
irreversible) — the rotation act itself stays gate:owner. Usage:
```bash
bash deploy/rotate_ai_keys.sh              # prompts for the new key (hidden input)
bash deploy/rotate_ai_keys.sh sk-ant-...   # or pass it as an argument
bash deploy/rotate_ai_keys.sh --dry-run    # print the plan, touch nothing
```

Manual procedure (what the script automates):
1. Log into https://console.anthropic.com/settings/keys
2. Generate a new key — copy it once (it's only shown once)
3. Update Secrets Manager:
   ```bash
   aws secretsmanager put-secret-value \
     --secret-id life-platform/ai-keys \
     --secret-string "$(aws secretsmanager get-secret-value --secret-id life-platform/ai-keys \
                       --query SecretString --output text \
                       | jq --arg k 'sk-ant-...' '. + {anthropic_api_key: $k}')"
   ```
4. Verify next Anthropic call succeeds — check CloudWatch metric `LifePlatform/AI AnthropicAPISuccess` for daily-brief
5. **Revoke the old key** in the Anthropic console

**Who actually reads this secret (verified 2026-07-19, #1329):** most Claude inference
migrated to Bedrock/IAM auth (ADR-062) and never touches this secret at all
(`bedrock_client.py`). A handful of lambdas still call the Anthropic API directly and
read `life-platform/ai-keys` (cached per-container, not via the 15-min `secret_cache.py`
TTL): `field_notes_lambda.py`, `ai_expert_analyzer_lambda.py`,
`daily_insight_compute_lambda.py`, `partner_email_lambda.py`, `monday_compass_lambda.py`,
`data_reconciliation_lambda.py`, `pipeline_health_check_lambda.py`. Each caches the key
in a per-container global for the container's lifetime (NOT the 15-min `secret_cache.py`
TTL — these lambdas fetch raw via `secretsmanager.get_secret_value` directly), so a
rotation reaches a given warm container only at its next cold start. If you need it live
sooner, force a redeploy of the affected function(s) to bust the warm containers.

### `site-api-ai-key` (Anthropic — `/api/ask`, `/api/board_ask`)

Same as `ai-keys` above. Separate from main key so site-API abuse cannot exhaust the daily-brief budget.

### `todoist`, `habitify` (dedicated secrets)

1. Log into the source provider's developer settings
2. Generate a new token/key
3. Update Secrets Manager:
   ```bash
   aws secretsmanager put-secret-value --secret-id life-platform/<name> \
     --secret-string '{"<field>": "<new_value>"}'
   ```
4. Verify next ingestion run succeeds (check CloudWatch logs of the corresponding ingestion Lambda)
5. Revoke the old token

### `notion`, `dropbox`, HAE webhook key (bundle path — V2 update)

These three keys now live inside `life-platform/ingestion-keys`. Rotate by editing the bundle (see `ingestion-keys` procedure below).

### `ingestion-keys` (bundled)

This is a single secret containing keys for multiple sources (Notion + Habitify + Todoist + Dropbox + HAE webhook). When rotating any one of them:

1. Fetch current bundle:
   ```bash
   aws secretsmanager get-secret-value --secret-id life-platform/ingestion-keys \
     --query SecretString --output text > /tmp/keys.json
   ```
2. Edit the relevant field
3. Put back:
   ```bash
   aws secretsmanager put-secret-value --secret-id life-platform/ingestion-keys \
     --secret-string file:///tmp/keys.json
   rm /tmp/keys.json
   ```

## Monitoring

The `freshness-checker` Lambda (runs daily at 9:45 AM PT) checks the `LastChangedDate` of every monitored secret:
- **OAuth secrets** stale >60 days → urgent alert (single email, unchanged)
- **Manual-rotation secrets** stale >120 days → **routed to the self-healing remediation
  agent (#1329, 2026-07-19), NOT raw SNS.** Before #1329, freshness-checker SNS-published
  this straight to the daily digest on every run once a secret crossed the threshold —
  `life-platform/ai-keys` crossed it ~2026-07-06 and re-fired for 12+ consecutive days
  with zero action, training the channel into noise. Now the checker only logs +
  emits the `ManualRotationStaleCount` metric; `remediation/agent.py::stale_secret_signals`
  reads the same `DescribeSecret` data (read-only, `secretsmanager:DescribeSecret` only —
  the agent never sees key material) and `stale_secret_escalations` surfaces any secret
  whose *active* staleness (days past the SLA) exceeds 7 days as a NAMED, persistent line
  in the agent's Mon/Wed/Fri curated needs-human email — zero new cadence, deterministic
  (independent of the LLM triage), and it keeps recurring every run until the secret is
  actually rotated (`LastChangedDate` advances). See `remediation/agent.py` §"Manual-
  rotation secret staleness escalation (#1329)".

Metrics emitted to CloudWatch namespace `LifePlatform/Freshness`:
- `OAuthTokenStaleCount` — count of OAuth secrets past threshold
- `ManualRotationStaleCount` — count of manual-rotation secrets past threshold

## Compromise procedure

If a secret is leaked:

1. **Immediately** revoke at the source provider (Anthropic console, Whoop OAuth app, etc.)
2. Generate a new token; update Secrets Manager via the procedures above
3. Audit CloudTrail for any unauthorized use:
   ```bash
   aws cloudtrail lookup-events --lookup-attributes \
     AttributeKey=ResourceName,AttributeValue=life-platform/<name> \
     --start-time $(date -u -v-30d +%Y-%m-%dT%H:%M:%S)
   ```
4. Force a Lambda code redeploy if needed to bust the in-Lambda secret cache (or wait the 15-min cache TTL).

---

**Verified:** 2026-07-19 (#1329 — manual-rotation staleness routed to the remediation agent's curated email instead of raw SNS; `deploy/rotate_ai_keys.sh` one-command prep; prior: #935 Whoop re-auth procedure, full sweep 2026-05-19 V2 audit)
