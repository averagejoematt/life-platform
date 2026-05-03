# Secrets Map — central reference for source → secret mapping

**Status:** ✅ Reconciled against AWS Secrets Manager on 2026-05-03 (PR 3).
**Source TD:** TD-13 (LOW) from `handovers/HANDOVER_v6.8.1.md`
**Region:** us-west-2 (per memory: AWS Account 205930651321, primary region us-west-2)

---

## Why this exists

TD-13 surfaced when the Todoist API key was discovered to live at `life-platform/ingestion-keys` instead of the expected `life-platform/todoist`. (As of PR 0 / 2026-05-03 the MCP write tools moved to a dedicated `life-platform/todoist` secret, but the ingestion Lambda still reads from the bundle.) This kind of inconsistency forces code archaeology to find credentials. This doc is the single source of truth.

---

## Verification command

```bash
aws secretsmanager list-secrets --region us-west-2 \
  --query 'SecretList[?starts_with(Name, `life-platform`)].[Name,Description,LastChangedDate]' \
  --output table
```

Last reconciled: **2026-05-03** (PR 3). 15 secrets total under `life-platform/*`.

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
| Notion | `life-platform/notion` (and `life-platform/ingestion-keys`) | Integration token | static | rotate via Notion settings | ✅ — present in both the dedicated and bundled secrets |
| Dropbox (MacroFactor poll) | `life-platform/dropbox` (and `life-platform/ingestion-keys`) | OAuth2 | refresh on expiry | re-auth Dropbox if expired | ✅ |
| Apple Health (HAE) webhook key | `life-platform/ingestion-keys` (`health_auto_export_api_key` field) | bearer | static | regenerate from API Gateway if exposed | ✅ |
| Anthropic — main pool | `life-platform/ai-keys` | API key | rotate periodically | manage in Anthropic console | ✅ — 24 consumer Lambdas |
| Anthropic — site-api isolated | `life-platform/site-api-ai-key` | API key | rotate periodically | manage in Anthropic console | ✅ — R17-04, isolated for site Lambda |
| Anthropic — orphan? | `life-platform/anthropic-api-key` | API key | unknown | unknown | ⚠️ **Orphan: not referenced in any Lambda or MCP code as of PR 3.** Created 2026-03-18, last modified same day. Candidate for deletion if confirmed unused. |
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
| `life-platform/notion` | `notion-journal-ingestion`, `pipeline-health-check` | also in `ingestion-keys` bundle |
| `life-platform/dropbox` | `dropbox-poll`, `pipeline-health-check` | also in `ingestion-keys` bundle |
| `life-platform/todoist` | `life-platform-mcp` (via `mcp/tools_todoist.py`) | NEW (PR 0) — MCP write tools only |
| `life-platform/ingestion-keys` | `todoist-data-ingestion`, `notion-journal-ingestion`, `dropbox-poll`, `health-auto-export-webhook`, `pipeline-health-check` | bundled — multiple keys per source |
| `life-platform/ai-keys` | 24 Lambdas (ai-expert-analyzer, anomaly-detector, brittany-email, challenge-generator, all 5 coach_*, daily-brief, daily-insight-compute, hypothesis-engine, journal-enrichment, monday-compass, monthly-digest, nutrition-review, weekly-digest, weekly-plate, weekly-signal, wednesday-chronicle, ai_calls module, etc.) | Anthropic API key. Run `grep -lrn life-platform/ai-keys lambdas/ mcp/` for the full list. |
| `life-platform/site-api-ai-key` | `site-api-ai-lambda`, `life-platform-site-api`, `pipeline-health-check` | Isolated per R17-04 |
| `life-platform/mcp-api-key` | `life-platform-mcp` (config), `canary-lambda`, `qa-smoke`, `mcp-key-rotator` | HMAC bearer; auto-rotates 90d |
| `life-platform/anthropic-api-key` | **none — orphan** | **⚠️ See orphan note above. Candidate for deletion.** |

---

## Cleanup actions surfaced by this audit

1. **Orphan: `life-platform/anthropic-api-key`** — not referenced in source or IAM. Candidate for deletion. Decision deferred to Matthew.
2. **Stale: `life-platform/webhook-key`** — referenced in `cdk/stacks/role_policies.py:326` ("Dedicated life-platform/webhook-key also exists — migration deferred") but NOT in `aws secretsmanager list-secrets` output (deleted 2026-03-14 per HANDOVER_v3.7.84). Either:
   - Update the role_policies.py comment to note the deletion, OR
   - Restore the secret if the comment's "migration deferred" intent is still active.
3. **Test list drift** — `tests/test_iam_secrets_consistency.py KNOWN_SECRETS` was missing `anthropic-api-key` and `eightsleep-client`. PR 3 syncs the list.
4. **ARCHITECTURE.md secrets table** — heading says "9 active secrets" but body lists 10 active rows (PR 0 added the todoist row, count not updated). PR 3 syncs the count to 15 active.
5. **Orphan IAM `webhook-key` reference** — `cdk/stacks/role_policies.py` comment references a secret that no longer exists.

---

## Maintenance

This doc must be updated whenever:
- A new source is added to the platform → add row + run reconciliation command above
- A secret is rotated → no entry change needed (secret name persists; auth value rotates within)
- A secret is renamed → update the row + add a redirect note for searchability
- Re-auth procedure changes → update the procedure cell

If this doc drifts from reality, it becomes worse than nothing. Treat divergences from the AWS reality as the doc being broken, not AWS.
