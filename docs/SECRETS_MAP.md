# Secrets Map — central reference for source → secret mapping

**Status:** ✅ Reconciled against AWS Secrets Manager on **2026-05-19** (V2 audit operational sweep).
**Source TD:** TD-13 (LOW) from `handovers/HANDOVER_v6.8.1.md`
**Region:** us-west-2 (AWS Account 205930651321)

**Current state (2026-05-19):**
- **12 active secrets** + **3 in deletion window** = 15 total in `aws secretsmanager list-secrets --include-planned-deletion`.
- Deletion window: `life-platform/notion` (delete 2026-05-24), `life-platform/dropbox` (delete 2026-05-24), `life-platform/anthropic-api-key` (delete 2026-05-23 — orphan, never adopted).
- `notion` and `dropbox` were retired in favor of fields inside `life-platform/ingestion-keys` (the keep-bundle pattern). Ingestion Lambdas already read from the bundle.

---

## Why this exists

TD-13 surfaced when the Todoist API key was discovered to live at `life-platform/ingestion-keys` instead of the expected `life-platform/todoist`. (As of PR 0 / 2026-05-03 the MCP write tools moved to a dedicated `life-platform/todoist` secret, but the ingestion Lambda still reads from the bundle.) This kind of inconsistency forces code archaeology to find credentials. This doc is the single source of truth.

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

Last reconciled: **2026-05-19** (V2 audit). 12 active + 3 in deletion window under `life-platform/*`.

---

## Source → Secret map

| Source | Secret name (AWS Secrets Manager) | Auth pattern | Re-auth cadence | Re-auth procedure | Verified |
|---|---|---|---|---|---|
| Garmin | `life-platform/garmin` | OAuth1 + OAuth2 | ~30 days (OAuth1 refresh) | `setup/setup_garmin_browser_auth.py` (Playwright/Chromium MFA) | ✅ |
| Withings | `life-platform/withings` | OAuth2 | similar to Garmin (manual refresh on rate-limit) | `setup/fix_withings_oauth.py` | ✅ |
| Strava | `life-platform/strava` | OAuth2 | similar pattern | manual refresh script | ✅ |
| Whoop | `life-platform/whoop` | OAuth2 | similar pattern | OAuth refresh | ✅ |
| Eight Sleep | `life-platform/eightsleep` + `life-platform/eightsleep-client` | username/password + client credential | static | rotate manually if exposed | ✅ (two secrets — `eightsleep` for user creds, `eightsleep-client` for app client ID) |
| Habitify | `life-platform/habitify` | API key | static | rotate manually if exposed | ✅ (own dedicated secret, ADR-014) |
| Todoist (ingestion) | `life-platform/ingestion-keys` (todoist field) | API key | static | rotate manually | ✅ — bundled with Notion / Dropbox / HAE webhook keys |
| Todoist (MCP write tools) | `life-platform/todoist` | API key | static | rotate manually | ✅ — added to MCP IAM in PR 0 (TD-23) |
| Notion | `life-platform/ingestion-keys` (notion fields) — **dedicated `life-platform/notion` SCHEDULED FOR DELETION 2026-05-24** | Integration token | static | rotate via Notion settings | ⚠️ Bundle-only path is now authoritative; dedicated secret retired in V2 P5 cleanup. |
| Dropbox (MacroFactor poll) | `life-platform/ingestion-keys` (dropbox fields) — **dedicated `life-platform/dropbox` SCHEDULED FOR DELETION 2026-05-24** | OAuth2 | refresh on expiry | re-auth Dropbox if expired | ⚠️ Bundle-only path is now authoritative; dedicated secret retired in V2 P5 cleanup. |
| Apple Health (HAE) webhook key | `life-platform/ingestion-keys` (`health_auto_export_api_key` field) | bearer | static | regenerate from API Gateway if exposed | ✅ |
| Anthropic — main pool | `life-platform/ai-keys` | API key | rotate periodically | manage in Anthropic console | ✅ — 24 consumer Lambdas |
| Anthropic — site-api isolated | `life-platform/site-api-ai-key` | API key | rotate periodically | manage in Anthropic console | ✅ — R17-04, isolated for site Lambda |
| Anthropic — orphan | `life-platform/anthropic-api-key` | API key | n/a | n/a | ❌ **SCHEDULED FOR DELETION 2026-05-23** — confirmed unused in V2 audit; scheduled for deletion 2026-05-16. |
| MCP Bearer token | `life-platform/mcp-api-key` | HMAC-derived bearer | 90-day auto-rotation via `mcp-key-rotator` Lambda | automated | ✅ |
| Function Health | n/a | n/a | n/a | manual PDF acquisition + ingest script | ✅ no secret needed (PDF-driven, no API) |
| MacroFactor | n/a (uses Dropbox) | n/a | n/a | re-auth Dropbox if expired | ✅ no MacroFactor-side secret; flows via Dropbox |
| Weather | env var | API key | static | depends on provider | ✅ env var on `weather-data-ingestion` Lambda — not in Secrets Manager |

---

## Naming convention

**Pattern:** all source-specific secrets follow `life-platform/<source-slug>`. Two notable exceptions:

1. **`life-platform/ingestion-keys`** — bundled secret containing the Todoist / Notion / Habitify / Dropbox / HAE-webhook keys. Created 2026-03-08 in the P0 security split that retired the original `life-platform/api-keys`. Migration to per-source secrets has been deferred indefinitely; it requires a Lambda code change AND a secret rename in lock-step. Habitify (ADR-014, 2026-03-10), Notion (2026-03-29), Dropbox (2026-03-29), and Todoist-for-MCP (2026-02-21) have since been migrated to dedicated secrets, but the **ingestion** path still reads from the bundle for those sources.

2. **`life-platform/eightsleep` + `life-platform/eightsleep-client`** — Eight Sleep needs a separate client credential alongside the user credentials. Two secrets is the cleanest representation.

**Carry-forward action:** if the orphan `life-platform/anthropic-api-key` is confirmed unused (no consumer in source, no IAM grant), delete it to keep AWS state clean. Currently NOT referenced in `cdk/stacks/role_policies.py` either — it's truly orphaned.

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
| Todoist (both secrets) | API key, no expiry | n/a |
| Notion | Integration token, no expiry | n/a |
| Dropbox | OAuth2; refresh tokens | Re-auth Dropbox if MacroFactor pull stops |
| HAE webhook | static URL + bearer | regenerate from API Gateway if exposed |
| Anthropic (any of the 3) | API key, no expiry | rotate manually periodically |
| MCP Bearer | auto-rotates every 90d | automated; `mcp-key-rotator` Lambda |

---

## Where each secret is consumed

Use this section to answer "if I rotate secret X, which Lambdas need a redeploy or cache flush?"

Cache TTL note: COST-OPT-1 uses `secret_cache.py` (15-min in-memory TTL across most Lambdas in the shared layer). On rotation, expect up to 15 min of stale reads from warm Lambda containers; cold-start clears it.

| Secret | Consumer Lambda(s) | Notes |
|---|---|---|
| `life-platform/whoop` | `whoop-data-ingestion`, `freshness-checker`, `pipeline-health-check` | OAuth tokens — Whoop Lambda refreshes on expiry |
| `life-platform/withings` | `withings-data-ingestion`, `freshness-checker`, `pipeline-health-check` | OAuth tokens |
| `life-platform/strava` | `strava-data-ingestion`, `freshness-checker`, `pipeline-health-check` | OAuth tokens |
| `life-platform/garmin` | `garmin-data-ingestion`, `freshness-checker`, `pipeline-health-check` | garth OAuth tokens |
| `life-platform/eightsleep` + `life-platform/eightsleep-client` | `eightsleep-data-ingestion`, `pipeline-health-check` | creds + client ID |
| `life-platform/habitify` | `habitify-data-ingestion`, `pipeline-health-check` | API key |
| `life-platform/notion` | **scheduled for deletion 2026-05-24** | Path migrated to `ingestion-keys` bundle. |
| `life-platform/dropbox` | **scheduled for deletion 2026-05-24** | Path migrated to `ingestion-keys` bundle. |
| `life-platform/todoist` | `life-platform-mcp` (via `mcp/tools_todoist.py`) | NEW (PR 0) — MCP write tools only |
| `life-platform/ingestion-keys` | `todoist-data-ingestion`, `notion-journal-ingestion`, `dropbox-poll`, `health-auto-export-webhook`, `pipeline-health-check` | bundled — multiple keys per source |
| `life-platform/ai-keys` | 24 Lambdas (ai-expert-analyzer, anomaly-detector, partner-email, challenge-generator, all 5 coach_*, daily-brief, daily-insight-compute, hypothesis-engine, journal-enrichment, monday-compass, monthly-digest, nutrition-review, weekly-digest, weekly-plate, weekly-signal, wednesday-chronicle, ai_calls module, etc.) | Anthropic API key. Run `grep -lrn life-platform/ai-keys lambdas/ mcp/` for the full list. |
| `life-platform/site-api-ai-key` | `site-api-ai-lambda`, `life-platform-site-api`, `pipeline-health-check` | Isolated per R17-04 |
| `life-platform/mcp-api-key` | `life-platform-mcp` (config), `canary-lambda`, `qa-smoke`, `mcp-key-rotator` | HMAC bearer; auto-rotates 90d |
| `life-platform/anthropic-api-key` | **none — scheduled for deletion 2026-05-23** | Orphan. V2 P5. |

---

## Cleanup actions surfaced by this audit

1. ✅ **Orphan `life-platform/anthropic-api-key` scheduled for deletion 2026-05-23** (V2 P5).
2. ✅ **Dedicated `life-platform/notion` retired** — bundle path is authoritative; secret scheduled for deletion 2026-05-24.
3. ✅ **Dedicated `life-platform/dropbox` retired** — bundle path is authoritative; secret scheduled for deletion 2026-05-24.
4. ✅ **Test list drift** — `tests/test_iam_secrets_consistency.py KNOWN_SECRETS` synced.
5. ⚠️ **ARCHITECTURE.md secrets table** — verify count says "12 active secrets" (was inconsistent; V2 P3 swept).
6. ⚠️ **role_policies.py stale comment about `webhook-key`** — confirm comment removed; `webhook-key` was deleted 2026-03-14.

If any deletion-window secret is needed back, restore via console within the 7-day window:
```bash
aws secretsmanager restore-secret --secret-id life-platform/notion
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

**Verified:** 2026-05-19 (V2 audit operational sweep)
