# External Accounts Inventory — what a successor needs to keep the platform alive

> **Status:** canonical · **Owner:** Matthew · **Verified:** 2026-07-10
> **Sources of truth:** `lambdas/source_registry.py` (data sources) · `docs/SECRETS_MAP.md` (credential locations) · `aws route53 list-hosted-zones` + `whois averagejoematt.com` (domain facts) · `aws ses list-identities` (email identities)

Every external account/service the platform depends on, what it's for, where its
credential lives, and how to recover access. **No secret values and no account
emails appear here — this repo is public.** "Password manager" means Matthew's
password manager; a successor needs estate access to it first.

Credential-location pointers reference `docs/SECRETS_MAP.md` (service creds in
AWS Secrets Manager, `life-platform/` prefix) or "human login — password manager".
Human AWS access procedure: `docs/AWS_ACCESS.md`.

---

## The inventory

| Account / service | What it's for | Credential location | How to recover access |
|---|---|---|---|
| **AWS account 205930651321** | Everything — the platform runs here (us-west-2) | Human access: `docs/AWS_ACCESS.md` (Identity Center SSO; break-glass `matthew-admin` keys). Root email: see password manager — root is MFA-locked, billing only (`docs/SECURITY.md`) | Root account recovery via the root email + MFA device; then re-provision Identity Center per `docs/AWS_ACCESS.md` §2a |
| **GitHub** (`github.com/averagejoematt/life-platform`) | Repo + Actions CI/CD + the OIDC trust that lets CI assume AWS roles (`docs/AWS_ACCESS.md` §4) | Human login — password manager. CI needs no stored AWS keys (OIDC). A repo-scoped PAT lives at `life-platform/github-dispatch-token` (Secrets Manager) for the remediation dispatcher | GitHub account recovery (password manager + 2FA recovery codes). If the OIDC provider/roles are lost, recreate per the CI workflows' `role-to-assume` ARNs |
| **NameCheap** — registrar for `averagejoematt.com` | Domain registration. **Verified 2026-07-10 via `whois`: registrar is NameCheap, Inc. — NOT Route53.** Registration expires **2026-08-20** | Human login — password manager | NameCheap account recovery. DNS itself is served by Route53 (hosted zone `Z063312432BPXQH9PVXAI` in the AWS account) — registrar only holds the NS delegation, so registrar recovery is only needed for renewal/transfer |
| **Whoop** (developer app) | Recovery/sleep/HRV ingestion (`whoop-data-ingestion`) | `life-platform/whoop` (OAuth tokens) — `docs/SECRETS_MAP.md` | Whoop account login (password manager) → re-auth via `setup/setup_whoop_auth.py` (redirect `localhost:3000/callback`) |
| **Withings** (developer app) | Weight/body-comp ingestion | `life-platform/withings` (OAuth) | Withings developer login (password manager) → `setup/fix_withings_oauth.py` |
| **Garmin Connect** (consumer account) | Steps/activity/sleep ingestion via `garth` | `life-platform/garmin` (OAuth1+2 tokens) | Garmin consumer login (password manager) → `setup/setup_garmin_browser_auth.py` (Playwright MFA flow); max 4x-daily pulls (rate limits) |
| **Hevy** (app account, API keys) | Workout ingestion + routine writes (MCP) | `life-platform/hevy` (read) + `life-platform/hevy-write` (write) | Hevy app login (password manager) → regenerate API keys in Hevy settings |
| **Todoist** | Task ingestion + MCP write tools | `life-platform/ingestion-keys` (todoist field, ingestion) + `life-platform/todoist` (MCP writes) | Todoist login (password manager) → regenerate API token in Todoist settings |
| **Health Auto Export** (iOS app) | Apple Health webhook push (CGM, water, BP, State of Mind) | Webhook bearer key: `life-platform/ingestion-keys` (`health_auto_export_api_key` field) | It's a paid iOS app on Matthew's phone (App Store account) — reconfigure the webhook URL + key in-app; regenerate key if exposed |
| **Strava** (developer app) | Activity ingestion | `life-platform/strava` (OAuth) | Strava login (password manager) → re-auth via the manual refresh script (`docs/SECRETS_MAP.md`) |
| **Eight Sleep** | Sleep/bed-temperature ingestion | `life-platform/eightsleep` (user creds) + `life-platform/eightsleep-client` (client credential) | Eight Sleep consumer login (password manager); rotate stored creds if exposed |
| **Habitify** | Habit ingestion | `life-platform/habitify` (API key, ADR-014) | Habitify login (password manager) → regenerate API key |
| **Notion** | Journal ingestion (integration token) | `life-platform/ingestion-keys` (notion fields) — a dedicated `life-platform/notion` also exists (see `docs/SECRETS_MAP.md` for its status) | Notion login (password manager) → Settings → Integrations → regenerate token |
| **Dropbox** (OAuth app) | MacroFactor nutrition export poll (`dropbox-poll`) | `life-platform/ingestion-keys` (dropbox fields) — the dedicated secret was deleted 2026-05 | Dropbox login (password manager) → re-auth the app if refresh token expires |
| **MacroFactor** (iOS app) | Nutrition logging — no API; data flows out via its Dropbox export | No credential platform-side (rides on Dropbox above) | App Store account on Matthew's phone; re-point its export at the Dropbox folder |
| **Anthropic** | **Runtime inference is AWS Bedrock via IAM (ADR-062) — no Anthropic account is needed to keep AI features alive.** Legacy direct-API keys still exist: `life-platform/ai-keys` (fallback path in `lambdas/intelligence_common.py`) + `life-platform/site-api-ai-key` (R17-04 isolated) | Secrets Manager (both) — `docs/SECRETS_MAP.md` | Anthropic Console login (password manager) — only needed to rotate/revoke the legacy keys |
| **Google Cloud** | Text-to-speech for podcasts (Chirp + Gemini TTS, `lambdas/google_tts.py` / `gemini_tts.py`) | `life-platform/google-tts` (API key) | GCP Console login (password manager) → regenerate the TTS API key in the project |
| **Email — AWS SES** | Daily brief + digests. Domain identities verified in SES us-west-2 (checked 2026-07-10): `mattsusername.com`, `aws.mattsusername.com` — note: **not** averagejoematt.com | No separate account — SES is IAM inside the AWS account. DNS records (DKIM etc.) live in the mattsusername.com zone — see `docs/MANAGED_WHERE_LEDGER.md` | Recover AWS (row 1). If identities are lost, re-verify the domain in SES + re-add DKIM records |
| **Pexels** | Stock editorial images (`lambdas/editorial_image.py`) | `life-platform/pexels` (API key) | Pexels account login (password manager) → regenerate API key (free tier) |
| **Open-Meteo** (weather) | Seattle daily weather ingestion (`lambdas/ingestion/weather_lambda.py`) | **None — free API, no key, no account** (verified in source 2026-07-10) | Nothing to recover |

Sources with **no external account at all** (for completeness, from
`lambdas/source_registry.py`): Function Health labs (manual PDF ingest), DEXA /
genome / measurements / supplements / food-delivery (manual entry paths).

---

## Notes for a successor

- **Order of operations on day 1:** password manager access → AWS root/Identity
  Center (`docs/AWS_ACCESS.md`) → GitHub → everything else can wait until an
  ingestion source goes stale (`get_freshness_status` via MCP, or
  `docs/RUNBOOK_REENTRY.md` for re-auth procedures).
- **The nearest hard deadline is the domain**: averagejoematt.com registration
  expires **2026-08-20** at NameCheap (as of the 2026-07-10 whois) — confirm
  auto-renew + a working payment method there.
- `mattsusername.com` (the SES sending domain) — registrar **NameCheap** (whois-verified 2026-07-10), same registrar account as averagejoematt.com. Check ITS expiry too when renewing.
- Rotation procedures live in `docs/SECRETS_ROTATION.md`; source re-auth walkthroughs
  in `docs/RUNBOOK_REENTRY.md`.

---

## Maintenance

Update this file whenever a new external service is added (new ingestion source,
new API dependency) or an account is retired. Re-verify the whois/SES/Route53
facts with the source-of-truth commands in the header — never from memory.


## The keyring itself — estate / break-glass (added 2026-07-10)

Every recovery path above terminates in "Matthew's password manager." That makes the
manager the **single root node of the entire access graph** (CTO-grader finding). What a
successor needs, recorded pointer-level only:

| Item | Status |
|---|---|
| Which password manager + where its emergency/estate access lives | ⚠️ **UNDOCUMENTED — owner action required.** Matthew: record (a) the manager, (b) the estate mechanism (e.g. 1Password Emergency Kit / family recovery, iCloud Legacy Contact, printed kit + physical location) here, pointer-level only. |
| MFA device + 2FA recovery-code locations (AWS root, GitHub, SSO) | ⚠️ **UNDOCUMENTED — owner action required.** If these live only on one phone, root+GitHub+SSO recovery all fail together. Record where backup codes live. |
| AWS root email | See password manager (deliberate — never in this repo). |

Until both ⚠️ rows are filled, treat bus-factor as **1** regardless of how good the rest
of this wiki is. This section exists so the gap is loud, not silent.
