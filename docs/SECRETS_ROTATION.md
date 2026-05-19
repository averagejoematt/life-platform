# Secrets Rotation Procedures

Last updated: 2026-05-19 (V2 audit operational sweep)

Phase 2.6 (2026-05-16): single source of truth for how each Life Platform secret is rotated. Used by both the operator (manual rotations) and the freshness checker (staleness alerts).

**V2 update (2026-05-19):** `life-platform/notion` and `life-platform/dropbox` are now in the deletion window — bundle path (`life-platform/ingestion-keys`) is authoritative. Rotation procedure for these now operates on the bundle. `life-platform/anthropic-api-key` is an orphan in deletion window — no rotation needed.

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

**Whoop:**
```bash
# Run locally with browser interaction
python3 setup/setup_whoop_oauth.py
# Updates life-platform/whoop with fresh refresh_token
```

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
- **OAuth secrets** stale >60 days → urgent alert (single email)
- **Manual-rotation secrets** stale >120 days → digest alert (batched into daily 8 AM PT digest)

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

**Verified:** 2026-05-19 (V2 audit operational sweep)
