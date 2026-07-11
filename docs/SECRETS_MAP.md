# Secrets Map — central reference for source → secret mapping

> **Status:** canonical · **Owner:** Matthew · **Verified:** 2026-07-10
> **Sources of truth:** `aws secretsmanager list-secrets --region us-west-2` (inventory) · `grep -rln "life-platform/<name>" lambdas/ mcp/ cdk/` (consumers) · `cdk/stacks/role_policies.py` (IAM grants)

**Reconciled against AWS Secrets Manager on 2026-07-10** (wiki-3 access/accounts pass).

**Current state (2026-07-10): 21 active secrets, 0 in deletion window.**
The 2026-05-19 state (12 active + 3 pending deletion) is history: `dropbox` and
`anthropic-api-key` completed deletion; `notion` was kept (restored 2026-05-24, the
day its deletion was due — it exists live, last accessed 2026-03-09; ingestion reads
the bundle, so it's a retire-candidate, see Cleanup below); and 9 secrets were added
since (site tokens, Hevy write, TTS, Pexels, GitHub dispatch, origin secret, …) — all
rows below.

---

## Why this exists

TD-13 surfaced when the Todoist API key was discovered to live at `life-platform/ingestion-keys` instead of the expected `life-platform/todoist`. (As of PR 0 / 2026-05-03 the MCP write tools moved to a dedicated `life-platform/todoist` secret, but the ingestion Lambda still reads from the bundle.) This kind of inconsistency forces code archaeology to find credentials. This doc is the single source of truth.

Related: human AWS credentials are NOT in Secrets Manager and never will be — see
`docs/AWS_ACCESS.md`. The external accounts these secrets authenticate against are
inventoried in `docs/ACCOUNTS.md`.

---

## Verification command

```bash
# Active only
aws secretsmanager list-secrets --region us-west-2 \
  --query 'SecretList[?starts_with(Name, `life-platform`)].[Name,Description,LastChangedDate]' \
  --output table

# Include deletion-window
aws secretsmanager list-secrets --include-planned-deletion --region us-west-2 \
  --query 'SecretList[].{Name:Name,DeletedDate:DeletedDate}' --output table
```

Last reconciled: **2026-07-10**. 21 active, 0 in deletion window, all under `life-platform/*`.

---

## Source → Secret map (data sources)

| Source | Secret name (AWS Secrets Manager) | Auth pattern | Re-auth cadence | Re-auth procedure | Verified |
|---|---|---|---|---|---|
| Garmin | `life-platform/garmin` | OAuth1 + OAuth2 | ~30 days (OAuth1 refresh) | `setup/setup_garmin_browser_auth.py` (Playwright/Chromium MFA) | ✅ 2026-07-10 |
| Withings | `life-platform/withings` | OAuth2 | similar to Garmin (manual refresh on rate-limit) | `setup/fix_withings_oauth.py` | ✅ 2026-07-10 |
| Strava | `life-platform/strava` | OAuth2 | similar pattern | manual refresh script | ✅ 2026-07-10 |
| Whoop | `life-platform/whoop` | OAuth2 | similar pattern | manual OAuth flow (see `SECRETS_ROTATION.md` §Whoop — no committed script) | ✅ 2026-07-10 |
| Eight Sleep | `life-platform/eightsleep` + `life-platform/eightsleep-client` | username/password + client credential | static | rotate manually if exposed | ✅ 2026-07-10 (two secrets — user creds + app client ID) |
| Habitify | `life-platform/habitify` | API key | static | rotate manually if exposed | ✅ 2026-07-10 (dedicated secret, ADR-014) |
| Hevy (read) | `life-platform/hevy` | API key | static | regenerate in Hevy app settings | ✅ 2026-07-10 — consumed by `lambdas/hevy_common.py` |
| Hevy (write — MCP routines) | `life-platform/hevy-write` | API key | static | regenerate in Hevy app settings | ✅ 2026-07-10 — `lambdas/hevy_write_client.py` + `mcp/tools_hevy_routine.py` |
| Todoist (ingestion) | `life-platform/ingestion-keys` (todoist field) | API key | static | rotate manually | ✅ 2026-07-10 — bundled with Notion / Dropbox / HAE webhook keys |
| Todoist (MCP write tools) | `life-platform/todoist` | API key | static | rotate manually | ✅ 2026-07-10 |
| Notion | `life-platform/ingestion-keys` (notion fields) — dedicated `life-platform/notion` also LIVE but idle (see Cleanup) | Integration token | static | rotate via Notion settings | ⚠️ Bundle path is authoritative for ingestion |
| Dropbox (MacroFactor poll) | `life-platform/ingestion-keys` (dropbox fields) — dedicated `life-platform/dropbox` **deleted** (window closed 2026-05) | OAuth2 | refresh on expiry | re-auth Dropbox if expired | ✅ 2026-07-10 bundle-only |
| Apple Health (HAE) webhook key | `life-platform/ingestion-keys` (`health_auto_export_api_key` field) | bearer | static | regenerate if exposed | ✅ 2026-07-10 |
| Function Health | n/a | n/a | n/a | manual PDF acquisition + ingest script | ✅ no secret needed (PDF-driven, no API) |
| MacroFactor | n/a (uses Dropbox) | n/a | n/a | re-auth Dropbox if expired | ✅ no MacroFactor-side secret; flows via Dropbox |
| Weather | **none** — Open-Meteo is a free, keyless API (`lambdas/ingestion/weather_lambda.py`) | n/a | n/a | n/a | ✅ 2026-07-10 — the old "env var API key" claim was stale; no key exists in the Lambda |

## Platform / serving secrets (not data sources)

| Purpose | Secret name | Auth pattern | Verified |
|---|---|---|---|
| Anthropic — legacy main pool | `life-platform/ai-keys` | API key. **Runtime inference is Bedrock/IAM (ADR-062)** — this is the direct-API fallback path (`AI_SECRET_NAME` default in `lambdas/intelligence_common.py`); still referenced by many Lambdas (`grep -lrn life-platform/ai-keys lambdas/`) | ✅ 2026-07-10 |
| Anthropic — site-api isolated | `life-platform/site-api-ai-key` | API key, isolated per R17-04 | ✅ 2026-07-10 |
| MCP bearer token | `life-platform/mcp-api-key` | HMAC-derived bearer; 90-day auto-rotation via `mcp-key-rotator` Lambda | ✅ 2026-07-10 |
| GitHub workflow dispatch | `life-platform/github-dispatch-token` | Repo-scoped GitHub PAT — lets `remediation_dispatcher_lambda` trigger GitHub Actions runs (ADR-064 self-healing loop) | ✅ 2026-07-10 |
| Subscriber link signing | `life-platform/subscriber-token-secret` | HMAC signing secret for subscriber tokens (`lambdas/web/site_api_social.py`, `site_api_ai_lambda.py`) | ✅ 2026-07-10 |
| Ritual check-in link signing | `life-platform/ritual-token-secret` | HMAC signing secret for evening-nudge ritual tokens (`lambdas/web/site_api_social.py`, `lambdas/emails/evening_nudge_lambda.py`) | ✅ 2026-07-10 |
| CloudFront → site-api origin verification | `life-platform/site-api-origin-secret` | Shared header secret so the site-api Function URL only serves CloudFront (`cdk/stacks/constants.py`; referenced by NAME — partial-ARN resolution breaks on `…-secret` suffixes) | ✅ 2026-07-10 |
| Google Cloud TTS (podcasts) | `life-platform/google-tts` | API key — Chirp/Gemini TTS (`lambdas/google_tts.py`, `lambdas/gemini_tts.py`, ADR-087) | ✅ 2026-07-10 |
| Pexels (editorial images) | `life-platform/pexels` | API key (`lambdas/editorial_image.py`) | ✅ 2026-07-10 |

---

## Naming convention

**Pattern:** all source-specific secrets follow `life-platform/<source-slug>`. Notable exceptions:

1. **`life-platform/ingestion-keys`** — bundled secret containing the Todoist / Notion / Dropbox / HAE-webhook keys. Created 2026-03-08 in the P0 security split that retired the original `life-platform/api-keys`. Migration to per-source secrets has been deferred indefinitely; it requires a Lambda code change AND a secret rename in lock-step. Habitify (ADR-014), Todoist-for-MCP, and Hevy got dedicated secrets, but the **ingestion** path still reads from the bundle for Todoist/Notion/Dropbox/HAE.

2. **`life-platform/eightsleep` + `life-platform/eightsleep-client`** — Eight Sleep needs a separate client credential alongside the user credentials. Two secrets is the cleanest representation.

3. **The `*-token-secret` trio** (`subscriber-`, `ritual-`, `site-api-origin-`) — HMAC signing/verification secrets minted by the platform itself, not external-service credentials. Rotating one invalidates all tokens it signed.

---

## Re-auth cadence quick reference

| Source | Pattern | Mitigation if platform silent |
|---|---|---|
| Garmin | OAuth1 expires ~30d | Disable EventBridge rule before silence; re-auth via Playwright |
| Withings | OAuth2 — rate-limit accumulation on cron retries during silence | Disable EventBridge rule before silence |
| Strava | similar to Withings | Disable rule |
| Whoop | OAuth2 — refresh tokens long-lived; less risky | Disable rule if silence > 30 days |
| Eight Sleep | static creds | n/a |
| Habitify | API key, no expiry | n/a |
| Hevy (both secrets) | API key, no expiry | n/a |
| Todoist (both secrets) | API key, no expiry | n/a |
| Notion | Integration token, no expiry | n/a |
| Dropbox | OAuth2; refresh tokens | Re-auth Dropbox if MacroFactor pull stops |
| HAE webhook | static URL + bearer | regenerate if exposed |
| Anthropic (legacy keys) | API key, no expiry | rotate manually periodically |
| MCP Bearer | auto-rotates every 90d | automated; `mcp-key-rotator` Lambda |
| Token-signing trio | platform-minted HMAC | rotate = mass token invalidation; plan it |
| GitHub dispatch PAT | GitHub PAT — expires per its GitHub setting | regenerate in GitHub → update secret |

---

## Where each secret is consumed

Use this section to answer "if I rotate secret X, which Lambdas need a redeploy or cache flush?"

Cache TTL note: COST-OPT-1 uses `secret_cache.py` (15-min in-memory TTL — a bundled shared module in every Lambda). On rotation, expect up to 15 min of stale reads from warm Lambda containers; cold-start clears it.

| Secret | Consumer Lambda(s) | Notes |
|---|---|---|
| `life-platform/whoop` | `whoop-data-ingestion`, `freshness-checker`, `pipeline-health-check` | OAuth tokens — Whoop Lambda refreshes on expiry |
| `life-platform/withings` | `withings-data-ingestion`, `freshness-checker`, `pipeline-health-check` | OAuth tokens |
| `life-platform/strava` | `strava-data-ingestion`, `freshness-checker`, `pipeline-health-check` | OAuth tokens |
| `life-platform/garmin` | `garmin-data-ingestion`, `freshness-checker`, `pipeline-health-check` | garth OAuth tokens |
| `life-platform/eightsleep` + `life-platform/eightsleep-client` | `eightsleep-data-ingestion`, `freshness-checker`, `pipeline-health-check` | creds + client ID |
| `life-platform/habitify` | `habitify-data-ingestion`, `pipeline-health-check` | API key |
| `life-platform/hevy` | `hevy-data-ingestion` (via `hevy_common.py`), `pipeline-health-check` | read API key |
| `life-platform/hevy-write` | `life-platform-mcp` (`tools_hevy_routine.py` via `hevy_write_client.py`) | routine/rest-seconds writes |
| `life-platform/notion` | referenced by `freshness-checker` + `pipeline-health-check` only; **last accessed 2026-03-09** | ingestion reads the bundle — retire-candidate (below) |
| `life-platform/todoist` | `life-platform-mcp` (via `mcp/tools_todoist.py`), `freshness-checker`, `pipeline-health-check` | MCP write tools |
| `life-platform/ingestion-keys` | `todoist-data-ingestion`, `notion-journal-ingestion`, `dropbox-poll`, `health-auto-export-webhook`, `freshness-checker`, `pipeline-health-check` | bundled — multiple keys per source |
| `life-platform/ai-keys` | legacy direct-API fallback (`AI_SECRET_NAME` in `intelligence_common.py`); referenced across intelligence/email Lambdas — `grep -lrn life-platform/ai-keys lambdas/ mcp/` for the live list | Bedrock/IAM is the primary inference path (ADR-062) |
| `life-platform/site-api-ai-key` | `life-platform-site-api`, `site-api-ai`, `site_api_social`, `freshness-checker`, `pipeline-health-check` | Isolated per R17-04 |
| `life-platform/mcp-api-key` | `life-platform-mcp` (config), `canary-lambda`, `qa-smoke`, `mcp-key-rotator` | HMAC bearer; auto-rotates 90d |
| `life-platform/github-dispatch-token` | `remediation-dispatcher` (`lambdas/operational/remediation_dispatcher_lambda.py`) | repo-scoped PAT |
| `life-platform/subscriber-token-secret` | `life-platform-site-api` (`site_api_social.py`), `site-api-ai` | HMAC signing |
| `life-platform/ritual-token-secret` | `life-platform-site-api` (`site_api_social.py`), `evening-nudge` | HMAC signing |
| `life-platform/site-api-origin-secret` | CDK-injected (CloudFront custom origin header ↔ site-api verification; `cdk/stacks/constants.py`) | reference by NAME, not partial ARN |
| `life-platform/google-tts` | podcast pipeline (`google_tts.py`, `gemini_tts.py`) | ADR-087 |
| `life-platform/pexels` | editorial image fetcher (`editorial_image.py`) | free-tier API key |

---

## Cleanup state (2026-07-10 reconciliation)

1. ✅ **`life-platform/anthropic-api-key`** — deleted (window closed 2026-05). Gone from live inventory.
2. ✅ **`life-platform/dropbox`** — deleted (window closed 2026-05). Bundle path authoritative.
3. ⚠️ **`life-platform/notion`** — was scheduled for deletion 2026-05-24 but is LIVE (LastChangedDate = 2026-05-24, i.e. restored the day deletion was due). Last accessed 2026-03-09; ingestion reads the bundle. **Retire-candidate**: confirm the freshness-checker/pipeline-health-check references are name-only, then re-schedule deletion — or adopt it as the authoritative Notion path. Either way, resolve the split.
4. The 2026-05-19 audit's other actions (test-list drift, ARCHITECTURE count, role_policies comment) were closed in V2 — see git history.

If a deletion-window secret is ever needed back, restore within the window:
```bash
aws secretsmanager restore-secret --secret-id <name>
```

---

## Maintenance

This doc must be updated whenever:
- A new source is added to the platform → add row + run reconciliation command above
- A secret is rotated → no entry change needed (secret name persists; auth value rotates within)
- A secret is renamed → update the row + add a redirect note for searchability
- Re-auth procedure changes → update the procedure cell

If this doc drifts from reality, it becomes worse than nothing. Treat divergences from the AWS reality as the doc being broken, not AWS.

---

**Verified:** 2026-07-10 (21 live secrets reconciled; consumers re-derived by grep — wiki-3 pass)
