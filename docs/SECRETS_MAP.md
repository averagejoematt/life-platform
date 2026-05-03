# Secrets Map — central reference for source → secret mapping

**Status:** Initial compilation, requires verification against AWS Secrets Manager
**Source TD:** TD-13 (LOW) from `handovers/HANDOVER_v6.8.1.md`
**Region:** us-west-2 (per memory: AWS Account 205930651321, primary region us-west-2)

---

## Why this exists

TD-13 surfaced when the Todoist API key was discovered to live at `life-platform/ingestion-keys` instead of the expected `life-platform/todoist`. This kind of inconsistency forces code archaeology to find credentials. This doc is the single source of truth.

---

## Verification action

Before treating this map as authoritative, run:

```bash
aws secretsmanager list-secrets --region us-west-2 \
  --query 'SecretList[?starts_with(Name, `life-platform`)].[Name, Description, LastChangedDate]' \
  --output table
```

Reconcile output against the table below. Update entries marked ⚠ unverified once confirmed. File a follow-up if any source isn't in either column (it might be using env vars or hardcoded — both are bugs).

---

## Source → Secret map

| Source | Secret name (AWS Secrets Manager) | Auth pattern | Re-auth cadence | Re-auth procedure | Verified |
|---|---|---|---|---|---|
| Garmin | `life-platform/garmin` | OAuth1 + OAuth2 | ~30 days (OAuth1 refresh) | `setup/setup_garmin_browser_auth.py` (Playwright/Chromium MFA) | ✅ confirmed in v6.8.1 session |
| Withings | `life-platform/withings` ⚠ | OAuth2 | ~similar to Garmin | `setup/fix_withings_oauth.py` | ⚠ unverified secret name |
| Strava | `life-platform/strava` ⚠ | OAuth2 | ~similar pattern | similar setup script ⚠ | ⚠ unverified |
| Habitify | `life-platform/habitify` | API key | static | rotate manually if exposed | ✅ memory: "EXISTS and active (own dedicated secret, not bundled)" |
| Todoist | `life-platform/ingestion-keys` | API key | static | rotate manually | ✅ confirmed in v6.8.1 session (the surprise that motivated this doc) |
| Whoop | `life-platform/whoop` ⚠ | OAuth2 | varies | ⚠ | ⚠ unverified |
| Eight Sleep | `life-platform/eight-sleep` ⚠ | API token | varies | ⚠ | ⚠ unverified |
| Notion | `life-platform/notion` ⚠ | Integration token | static | rotate via Notion settings | ⚠ unverified |
| Function Health | `life-platform/function-health` ⚠ | session/cookie? | manual download | manual PDF acquisition | ⚠ unverified — Function Health may not have an API; ingestion is PDF-driven |
| MacroFactor | `life-platform/macrofactor` ⚠ | Dropbox-based file sync | OAuth (Dropbox side) | re-auth Dropbox if expired | ⚠ unverified — secret may be on Dropbox side, not MF |
| Anthropic API | `life-platform/anthropic` ⚠ | API key | static, rotate periodically | manage in Anthropic console | ⚠ unverified |
| Apple Health (HAE) | n/a | Webhook URL | static | regenerate URL in iOS HAE app | ✅ no secret needed; Function URL is the secret-equivalent |
| Weather | likely env var | API key | static | depends on provider | ⚠ unverified |

---

## Naming convention going forward

**Decision (proposed):** all source-specific secrets follow the pattern `life-platform/<source-slug>`. The bundled `life-platform/ingestion-keys` Todoist secret is the outlier and should be migrated to `life-platform/todoist` at the next convenient Todoist Lambda deploy. Don't migrate ad-hoc — it requires a Lambda code change and a secret rename, which means downtime if not done in lock-step.

**Migration plan for Todoist:**
1. Create new secret `life-platform/todoist` containing the same value as the Todoist key field in `life-platform/ingestion-keys`
2. Update Todoist Lambda env var or code reference to point at new secret
3. Deploy Lambda
4. Verify a successful run from CloudWatch logs
5. Delete old secret OR remove the Todoist key from `life-platform/ingestion-keys` (depending on whether other sources also live in the bundled secret)

**Defer this migration until:** Claude Code is already touching the Todoist Lambda for another reason (e.g. TD-12 cron schedule fix). Don't ship a secret rename in isolation — the value is too low.

---

## Re-auth cadence quick reference

Per memory: "Garmin re-auth is a recurring ~30-day chore." Same pattern applies to Withings and Strava (per handover Operational Notes). Mitigation: disable EventBridge rule before any planned silence longer than 2 weeks to prevent rate-limit accumulation.

| Source | Pattern | Mitigation if silent |
|---|---|---|
| Garmin | OAuth1 expires ~30d | Disable EventBridge rule before silence |
| Withings | similar | Disable rule |
| Strava | similar | Disable rule |
| Whoop | TBD verify | TBD |
| Eight Sleep | TBD verify | TBD |
| Habitify | API key, no expiry | n/a |
| Todoist | API key, no expiry | n/a |
| Notion | Integration token, no expiry | n/a |
| HAE | Webhook URL, no expiry | n/a |

---

## Where each secret is consumed

Reference for "if this secret rotates, which Lambdas need to be redeployed or restart their cache?"

| Secret | Consumer Lambda(s) | Cache TTL |
|---|---|---|
| `life-platform/garmin` | `garmin-data-ingestion` | per-invocation refresh |
| `life-platform/habitify` | habitify ingestion Lambda(s) | per-invocation |
| `life-platform/ingestion-keys` | Todoist Lambda(s) | per-invocation |
| ⚠ rest | TBD audit | TBD |

---

## Action items

- [ ] **Run the AWS list-secrets command above and reconcile this table.** ~5 minutes.
- [ ] **For each ⚠ row, verify the actual secret name and auth pattern.** Update this doc inline.
- [ ] **Audit which Lambdas read which secrets** — enables impact analysis on rotation. ~30 minutes.
- [ ] **Plan Todoist secret rename** at next Todoist Lambda touch. (Don't ship in isolation.)
- [ ] **Add this doc to `docs/INDEX.md`** if a docs index exists.

---

## Maintenance

This doc must be updated whenever:
- A new source is added to the platform → add row
- A secret is rotated → update "Last rotated" if that column is added later
- A secret is renamed → update the row + add a redirect note for searchability
- Re-auth procedure changes → update the procedure cell

If this doc drifts from reality, it becomes worse than nothing. Treat divergences from the AWS reality as the doc being broken, not AWS.
