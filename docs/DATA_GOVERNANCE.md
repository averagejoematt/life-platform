# Data Governance — PII Classification + Retention Policy

> **Status:** canonical · **Owner:** Matthew · **Verified:** 2026-05-19

Phase 7 (2026-05-16, refreshed 2026-05-19 post-V2): single source of truth for what data exists, who can see it, and how long it's kept.

This document covers two cross-cutting concerns:
1. **PII Classification** (P7.4) — what's personally identifiable and what's safe to expose
2. **Retention Policy** (P7.2) — per-data-type retention rules

If a clinician, lawyer, or compliance reviewer asks "what data do you hold and for how long," this is the answer.

---

## Data Classification

Every field falls into one of these tiers:

### Tier 0 — Public (no auth required)
Visible at `averagejoematt.com` to anyone:
- Daily/weekly aggregate scores (sleep score, recovery, training load — rolled up, no granular timestamps)
- Habit completion percentages (no per-habit detail)
- Character sheet level + pillar tier (not raw component values)
- Public stats (`public_stats.json`): weight, day count, total achievements
- Blog/chronicle content (written deliberately for public consumption)

### Tier 1 — Subscriber-only (auth via subscriber token)
- Detailed per-metric trends and correlations
- Habit-specific completion data
- AI coaching responses (via `/api/ask`, `/api/board_ask`)

### Tier 2 — Owner-only (Matthew via MCP / dashboard)
- Raw biometrics: HRV, heart rate, sleep stages, CGM glucose readings
- Lab results (cholesterol, biomarkers, genome variants)
- Body composition (DEXA scan details, weight, body fat %)
- Nutrition logs (every meal, every calorie)
- Journal entries (full text)
- State of mind / mood entries
- Activity GPS traces, workout details
- Sick day records, supplement logs
- Reading retention/recall (ADR-097): `retentionScore`, all `RECALL#` spaced-retrieval prompts + performance, the cognitive-reserve/longevity framing, reading×biometric correlations, session `moodSnapshot`/`location`, and reading-calibration internals. **Private by default, owner's toggle, owner's eyes** — a bad retention week is never reachable from a public surface (spec §10, enforced server-side in `reading_visibility.project_public`). NB: the *public* reading projection (current/finished shelf, public takeaways, input streak) is Tier 1.

### Tier 3 — Never exposed (system internal)
- OAuth refresh tokens, API keys, secrets
- Internal coach state (preamble drafts, prediction confidence scores)
- Raw S3 archives of source API responses
- DLQ messages, validation errors
- CloudWatch logs
- Rate limit counters

### PII Definition (regulatory framing)
Per typical health-data definitions, the following fields are **PII** regardless of tier:
- Name (Matthew)
- Email addresses (subscribers, recipients)
- Any biometric data tied to identity
- Journal entries (contain personal narrative)
- Reading notes/reflections (contain personal narrative) + spaced-retrieval responses
- Location data (Strava GPS traces, weather queries by city, reading-session location)
- Body composition images / DEXA scans

**No PII is in Tier 0.** Public site exposes aggregates only; never raw values tied to identity at granular timestamp resolution.

**Enforced structurally (ER-06):** `deploy/pii_surface_guard.py` + `tests/test_public_surface_pii_guard.py` scan the published `site/` surface fail-closed (blocked-vice keywords, SSN / 16-digit / non-allowlisted email, and a non-committed personal-literal denylist) — in CI and again inside `sync_site_to_s3.sh` before the S3 sync. This policy is no longer convention-only. See `docs/TESTING.md` §12.

---

## Retention Policy

### Hot tier (DynamoDB single table)

| Data type | Partition pattern | Retention | Notes |
|-----------|-------------------|-----------|-------|
| Computed daily metrics | `USER#matthew#SOURCE#{computed_metrics,daily_insight,character_sheet,adaptive_mode}` | **Forever** | Trend analysis needs full history |
| Raw daily ingestion | `USER#matthew#SOURCE#{whoop,withings,strava,...}` | **Forever** | Source of truth for analysis |
| Journal entries | `USER#matthew#SOURCE#notion` | **Forever** | Long-term reflection value |
| CGM readings | `USER#matthew#SOURCE#apple_health` | **Forever** | Pattern detection across years |
| Habit scores | `USER#matthew#SOURCE#habit_scores` | **Forever** | Streak + correlation analysis |
| Coach threads | `COACH#{coach_id}` | **Forever** | Coaching memory |
| Reading library (ADR-097) | `BOOK#{bookId}`, `READING#{bookId\|REC\|PROFILE\|IDEA#…}` | **Forever** | Durable identity data (CROSS_PHASE); private fields gated server-side |
| Sick days | `USER#matthew#SOURCE#sick_days` | **Forever** | Analysis context |
| Rate limit counters | `RATE#{endpoint}#{ip_hash}` | **2 hours (DDB TTL)** | Auto-expire via `ttl` attribute (P1.7) |
| Auth failure markers | `USER#matthew#SOURCE#{src}` `sk=AUTH_FAILURE` | **24 hours (DDB TTL)** | Circuit breaker; auto-expire (P3.6) |
| Health check results | `USER#matthew#SOURCE#health_check` | **Forever** | Operational audit trail |

### Warm tier (S3)

| Prefix | Retention | Lifecycle rule |
|--------|-----------|----------------|
| `raw/` (per-source archives) | Current: forever; **non-current versions: 7 days** | P1.3 — `raw-expire-noncurrent-versions-7d` |
| `raw/` (incomplete uploads) | **Abort after 7 days** | P1.3 — `raw-abort-incomplete-multipart-7d` |
| `uploads/` (HAE webhooks etc.) | **Current: 30 days; non-current: 7 days** | P1.3 — `uploads-expire-30d` |
| `generated/` (Lambda-written: OG images, dashboard, journals) | **Current: forever; non-current: 7 days (keep 1)** | P1.3 — `generated-expire-noncurrent-7d` |
| `config/` (platform config: filters, schemas) | **Current: forever; non-current: 30 days (keep 3)** | P1.3 — `config-expire-noncurrent-30d` |
| `deploys/` (Lambda deploy artifacts) | **30 days** | Pre-existing |
| `cloudtrail/` (audit logs) | **90 days** | P2.5 / P7 — `cloudtrail-expire-90d` |
| `mcp-audit/` (MCP write-audit trail, #753) | **90 days** (classed with `cloudtrail/` audit logs); Infrequent Access at 30 days | #886 — `mcp-audit-ia-30d-expire-90d` |
| `remediation-log/` (automerge audit ledger, ADR-065) | **Forever**; only the `dispatch-dedupe/` sub-prefix (transient dedupe markers) expires at **1 day** | `remediation-dispatch-dedupe-expire-1d` |
| `dashboard/`, `site/`, `blog/` | **Forever** (static content) | None — long-lived public assets |

All lifecycle rules are declared in **`deploy/apply_s3_lifecycle.sh`** — the single source
of truth for the bucket's lifecycle configuration (the bucket is CDK-imported via
`Bucket.from_bucket_name`, so lifecycle lives outside IaC; see `docs/MANAGED_WHERE_LEDGER.md`).
Lifecycle expiration is executed by the S3 service itself — no IAM principal is evaluated
against the bucket policy — so it coexists with the `ProtectDataFromDeployScripts`
`s3:DeleteObject` Deny on `matthew-admin` (`deploy/bucket_policy.json`).

### Cold tier (none)
No Glacier or deep-archive tier is in use today. Could be added if compliance demands long-term retention with reduced costs.

### Logs

| Source | Retention |
|--------|-----------|
| Lambda CloudWatch Logs (most) | **30 days** (P1.1) |
| Lambda CloudWatch Logs (power-tuning) | **14 days** |
| Lambda CloudWatch Logs (security: canary, key-rotator, dlq-consumer, cf-auth) | **90 days** |
| CloudTrail events | **90 days** (S3 lifecycle) |
| DLQ messages | **14 days** (SQS retention) |
| Validation errors archive (S3) | Forever in `validation-errors/` prefix |

### Secrets
- **Auto-refreshed on use**: OAuth (Whoop, Withings, Strava, Garmin, Eight Sleep) — rewritten on every successful ingestion
- **Auto-rotated 90d**: `life-platform/mcp-api-key` via key-rotator Lambda
- **Manual rotation 90d**: `life-platform/ai-keys` (Anthropic), `life-platform/site-api-ai-key` (Anthropic)
- **Manual rotation 180d**: Notion, Habitify, Dropbox, Eight Sleep client
- **Manual rotation 365d**: Todoist
- Staleness alerts: OAuth >60d, manual-rotation >120d (freshness checker, P2.6)

---

## Data Subject Rights (if ever required)

### Export
- `lambdas/data_export_lambda.py` exists; on-demand only. Generates a snapshot of all DDB partitions + S3 archive references.
- **Audit P7.1 still outstanding** — verify output format covers all current source partitions (now 19, up from earlier estimates).

### Deletion
- `lambdas/delete_user_data_lambda.py` scaffolded; not yet wired to a request-driven trigger. The Phase 6 multi-user roll-out (formally deferred per ADR-057) is the gating context.
- Today: manual procedure documented below remains the operative process.

### Access
- Matthew accesses everything via MCP (Claude Desktop) or `dash.averagejoematt.com`.
- Subscribers see only Tier 0 + their interaction history (via subscriber token).

---

## Manual Delete Procedure (today, until P7.3 ships)

For a clean wipe of a user's data:

```bash
USER_ID=test_user_to_delete

# 1. Find every partition for this user
aws dynamodb scan --table-name life-platform \
  --filter-expression "begins_with(pk, :p)" \
  --expression-attribute-values "{\":p\":{\"S\":\"USER#${USER_ID}#\"}}" \
  --projection-expression "pk,sk" > /tmp/user_items.json

# 2. Delete each item (batches of 25)
# (script not yet written; tracked as P7.3)

# 3. S3 prefixes
aws s3 rm s3://matthew-life-platform/raw/${USER_ID}/ --recursive
aws s3 rm s3://matthew-life-platform/uploads/${USER_ID}/ --recursive
aws s3 rm s3://matthew-life-platform/dashboard/${USER_ID}/ --recursive
aws s3 rm s3://matthew-life-platform/generated/${USER_ID}/ --recursive

# 4. Secrets (per-user, only if Phase 6 multi-user shipped)
aws secretsmanager delete-secret --secret-id life-platform/${USER_ID}/whoop \
  --recovery-window-in-days 7
# repeat for each per-user OAuth secret

# 5. CloudTrail confirmation
# Wait ≤24h for CloudTrail to record the deletions; archive the trail entries
# as the audit trail of the deletion event.
```

---

## Compliance Posture (current state)

- **GDPR**: not a GDPR data subject (US-based, no EU users)
- **HIPAA**: not a covered entity (not a healthcare provider; data is self-tracked)
- **CCPA**: technically applicable if California user added; delete-account flow (P7.3) is the gap
- **SOC2 / ISO 27001**: not pursued; would require formal access-control + audit-trail processes

If any of these become relevant (e.g., onboarding a second user from CA, sale of the platform, clinician handoff), Phases 6 + 7 of the audit plan address the remaining gaps. Phase 6 (multi-user / Cognito) was formally deferred in ADR-057 — see that ADR for re-open triggers.

---

## Audit Trail

| Date | Change | Reference |
|------|--------|-----------|
| 2026-05-16 | Initial document; consolidates per-data-type retention scattered across P1.1, P1.3, P1.7, P2.6, P3.6 | This commit |
| 2026-05-16 | S3 KMS encryption activated for new objects | P2.4 changelog v7.2.0 |
| 2026-05-17 | S3 KMS rollback to AES256 (website endpoint incompatibility) | ADR-053 (v7.20.0) |
| 2026-05-16 | CloudTrail multi-region + delivery restored after 3-month outage | P2.5 changelog v7.2.0 |
| 2026-05-17 | Two-tier alerting (urgent + daily digest) reduces inbox noise | ADR-052 (v7.x) |
| 2026-05-17 | Phase 6 multi-user / delete-user-data flow formally deferred | ADR-057 |
| 2026-05-19 | Doc re-verified post V2 closure; data_export + delete_user_data lambdas confirmed present | This commit |
| 2026-07-08 | `mcp-audit/` retention set: IA at 30d, expire at 90d — classed with `cloudtrail/` audit logs; `apply_s3_lifecycle.sh` made the declarative full-config source of truth | #886 |

---

**Verified:** 2026-05-19


## Editorial guardrails (public surfaces) — canonical home

Migrated from the frozen BACKLOG archive (2026-07-10 — a live guardrail was buried in a
deprecated doc). On ANY public surface (site, OG images, RSS, podcasts, build beats):

- No employer / role / industry. Partner is never named.
- **Vices:** only *alcohol* and *food-delivery* categories are ever named publicly; all
  other vice categories are aggregate-only (streak counts, no labels). See
  `feedback_sensitive_content` policy — marijuana/porn content must never be public.
- Bereavement content is opt-in only.
- Correlative framing always ("associated with", never "caused").
- Down-weeks are always visible — absence of bad data is a lie of omission (ADR-104).
- Chronological age is never published (PhenoAge Option A — bio-age only).

## Scope note: the PII guard vs the repo itself

`deploy/pii_surface_guard.py` scans the **published site surface (`site/`) only**. The
repo's `docs/coaching/` files carry Tier-2 owner-only data (real biometrics, training
calibration) — their privacy control is **repo visibility** (private since 2026-07),
NOT the guard. Wiki-panel finding 2026-07-10: treat repo visibility as a load-bearing
privacy control; never flip this repo public again without first relocating or
redacting `docs/coaching/`.
