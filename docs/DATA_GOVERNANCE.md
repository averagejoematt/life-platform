# Data Governance — PII Classification + Retention Policy

> **Status:** canonical · **Owner:** Matthew · **Verified:** 2026-08-23

Phase 7 (2026-05-16, refreshed 2026-07-18 — #1351 current-truth pass: repo visibility,
delete-lambda status, current data classes, subscriber-retention readiness #1350):
single source of truth for what data exists, who can see it, and how long it's kept.

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
- The nightly public archive at `/archive/*` (#1400, `docs/PERMANENCE_CONTRACT.md`) — a repackaging of the Tier 0 surface and **nothing else**. It widens no tier: its API arm is fetched with no credentials, so the Tier 1/2/3 projections are unreachable by construction, and its admission registry is gated by `tests/test_public_archive_privacy_gate_1400.py`. The published continuity document alongside it carries a day count and a state, never a location or an identity.

### Tier 1 — Subscriber-only (auth via subscriber token)
- Detailed per-metric trends and correlations
- Habit-specific completion data
- AI coaching responses (via `/api/ask`, `/api/board_ask`)

### Tier 2 — Owner-only (Matthew via MCP / dashboard)

> **Publication carve-out (ADR-155, signed 2026-08-23, `gate:owner`).** Parts of this
> tier are **deliberately published** by recorded owner consent: everything `/api/vitals`
> serves (HRV raw ms + averages, RHR, recovery %, sleep hours, weight + deltas/trends),
> everything `/api/labs` serves (the full named-biomarker panel, genetic entries
> structurally stripped), the sleep-stage trio on `/api/sleep_detail`, lean mass on the
> nutrition surface, and the DEXA scan summary on the physical surface. The machine
> registry `lambdas/privacy/field_tiers.py` is the enforcement point: a published field
> carries an explicit `TIER_OWNER_PUBLISHED` stamp; everything else in this tier is
> `TIER_OWNER_ONLY` and **never** reaches a public payload — by stamp, never by omission
> (DIL-008/DIL-011). `tests/test_data_governance_tier_guard_3045.py` fails CI if this
> section and the registry ever disagree.

- Raw biometrics: HRV, heart rate, sleep stages, CGM glucose readings
- Lab results (cholesterol, biomarkers, genome variants)
- Body composition (DEXA scan details, weight, body fat %)
- Nutrition logs (every meal, every calorie)
- Journal entries (full text)
- State of mind / mood entries
- Activity GPS traces, workout details
- Sick day records, supplement logs
- Reading retention/recall (ADR-097): `retentionScore`, all `RECALL#` spaced-retrieval prompts + performance, the cognitive-reserve/longevity framing, reading×biometric correlations, session `moodSnapshot`/`location`, and reading-calibration internals. **Private by default, owner's toggle, owner's eyes** — a bad retention week is never reachable from a public surface (spec §10, enforced server-side in `reading_visibility.project_public`). NB: the *public* reading projection (current/finished shelf, public takeaways, input streak) is Tier 1.
- Private intake ledger (#1405): `USER#matthew#SOURCE#private_intake` — Matthew-private evening intake count, feeding `intake_response.py`'s dose-response analysis (n_eff / block-bootstrap CI). Classed `RAW_TIMESERIES` (ADR-077, never wiped); explicitly `NEVER public-served` (`lambdas/experiment/phase_taxonomy.py`) — MCP-only (`get_intake_response`), never a site endpoint.
- Flourishing PERMA projection (#1403): `USER#matthew#SOURCE#flourishing` — daily provenance-stamped PERMA projection over journal enrichment (`flourishing.py`). Raw daily row is owner-only; it feeds the Character Sheet's Relationships pillar component and the Mind pillar's `values_alignment` sub-score, both surfaced only as the Tier 0 aggregate pillar tier (never the raw daily score).
- Felt-reality calibration probe (#1409): `USER#matthew#SOURCE#felt_probe` — weekly Sunday one-tap self-report (0–4 × 3 axes). Raw taps are owner-only; `/api/character_calibration` serves only the deterministic r/CI/n_eff calibration aggregate (no item-level values, per `tests/test_felt_probe_1409.py`).

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
| Private intake / flourishing / felt-probe (2026-07 additions) | `USER#matthew#SOURCE#{private_intake,flourishing,felt_probe}` | **Forever** | RAW_TIMESERIES class (ADR-077, `phase_taxonomy.py`) — logged/derived owner facts; #1405, #1403, #1409 |
| **Inbound social posts** (#1668–#1677, #2603) | `USER#matthew#SOURCE#{youtube,bluesky,mastodon,x,instagram,tiktok}` `sk=DATE#{d}#{post_id}` (+ `sk=PASTE#{d}#{post_id}` staging on the closed three) | **Forever** | RAW_TIMESERIES (ADR-077). **Matthew's OWN public posts** — content he already published under his own name, captured back in (fetched where a free read path exists; **paste-only** for x/instagram/tiktok, which hold no token or client at all). Not third-party PII, so absent from `NON_OWNER_PII_PARTITIONS`, but **not therefore unguarded**: every row is stamped `origin` (`human`\|`platform`) by `lambdas/privacy/social_provenance.py`, and re-publication on any platform surface is **fail-closed** behind `lambdas/privacy/broadcast_sensitivity_gate.py` (#1673) — a row is displayable only on `sensitivity_status == "cleared"`, so a missing, unknown or errored verdict **holds** rather than publishes. Third parties named *inside* a post's `text` are governed by that gate + the editorial guardrails below, not by this row. |
| Rate limit counters | `RATE#{endpoint}#{ip_hash}` | **2 hours (DDB TTL)** | Auto-expire via `ttl` attribute (P1.7) |
| Auth failure markers | `USER#matthew#SOURCE#{src}` `sk=AUTH_FAILURE` | **24 hours (DDB TTL)** | Circuit breaker; auto-expire (P3.6) |
| Health check results | `USER#matthew#SOURCE#health_check` | **Forever** | Operational audit trail |
| **Subscriber emails** (#1350/#3044 — third-party PII) | `USER#matthew#SOURCE#subscribers` `sk=EMAIL#{sha256(email)}` | **Anonymize at unsubscribe — 0 days** (signed v2 2026-08-23, supersedes the 548-day window of 2026-07-25) | **SIGNED (#3044, 2026-08-23; supersedes #1350's 548-day window):** the unsubscribe handler (`web/email_subscriber_lambda.handle_unsubscribe`) anonymizes IN THE SAME WRITE that flips the status — plaintext `email` redacted to `[redacted]`, `ip_hash` dropped, `anonymized_at` stamped — while the sk (the sha256 hash), `status`, and timestamps are KEPT so the subscriber COUNT and confirmation state that public stats reference survive, and the hash is the suppression record that prevents re-mailing. Active (pending/confirmed) subscribers are never touched. The signed window + mode are a single constant: `lambdas/content/subscriber_retention.py::RETENTION_WINDOW_DAYS` (=0) / `RETENTION_MODE` (=`anonymize`). The weekly (Mon 08:00 UTC) `delete_user_data_lambda` `{"subscriber_retention_sweep": true, "apply": true}` EventBridge rule is now the BACKSTOP (legacy pre-v2 rows + any failed inline write — worst-case SLA ≤7 days); the attended equivalent is `python3 deploy/subscriber_retention_purge.py --mode anonymize --apply` (omit `--apply` for a dry run). A single subscriber can also be hard-deleted on request (including the hash) via `delete_user_data_lambda`'s `{"subscriber_email": "...", "confirm": "DELETE"}` shape — `/privacy/` states a 7-day SLA. `tests/test_data_governance_retention_coverage.py` requires this signed row to keep naming a day-count window; `tests/test_subscriber_retention_sweep.py` asserts the window is 0 days and that no eligible row survives un-anonymized. |

### Warm tier (S3)

| Prefix | Retention | Lifecycle rule |
|--------|-----------|----------------|
| `raw/` (per-source archives) | Current: forever; **non-current versions: 7 days** | P1.3 — `raw-expire-noncurrent-versions-7d` |
| `raw/` (incomplete uploads) | **Abort after 7 days** | P1.3 — `raw-abort-incomplete-multipart-7d` |
| `uploads/` (HAE webhooks etc.) | **Current: 30 days; non-current: 7 days** | P1.3 — `uploads-expire-30d` |
| `generated/` (Lambda-written: OG images, dashboard, journals) | **Current: forever; non-current: 7 days (keep 1)** | P1.3 — `generated-expire-noncurrent-7d` |
| `generated/qa_archive/` (generation-time AI-surface archive: text + screenshots, #1441) | **Listed 90 days; bytes fully purged ≈ day 97** (audit-log class — the D3 review-pack evidentiary window). Versioned-bucket mechanics: delete marker at 90d → the noncurrent data version expires 7d later (own rule, NO keep-newest carve-out — the `generated/` keep-1 rule must not shield these write-once keys) → expired delete marker swept | #1441 — `qa-archive-expire-90d` + `qa-archive-clean-delete-markers` |
| `generated/archive/` (the nightly public permanence archive, #1400) | **Current: forever; non-current: 7 days (keep 1)** — inherits the `generated/` rule unchanged, and needs no rule of its own: the run overwrites three fixed keys in place rather than accumulating dated ones. The single dated artefact (`final-YYYY-MM-DD.tar.gz`) is written only if the continuity switch trips, and is meant to be permanent. | P1.3 — `generated-expire-noncurrent-7d` (inherited) |
| `config/` (platform config: filters, schemas) | **Current: forever; non-current: 30 days (keep 3)** | P1.3 — `config-expire-noncurrent-30d` |
| `deploys/` (Lambda deploy artifacts) | **Current: 30 days; non-current: 7 days (keep 1)** | Pre-existing (Expiration) + #2642 — `expire-lambda-deploy-artifacts` (added `NoncurrentVersionExpiration`) |
| `cloudtrail/` (audit logs) | **90 days** | P2.5 / P7 — `cloudtrail-expire-90d` |
| `mcp-audit/` (MCP write-audit trail, #753) | **90 days** (classed with `cloudtrail/` audit logs); Infrequent Access at 30 days | #886 — `mcp-audit-ia-30d-expire-90d` |
| `remediation-log/` (automerge audit ledger, ADR-065) | **Forever**; only the `dispatch-dedupe/` sub-prefix (transient dedupe markers) expires at **1 day** | `remediation-dispatch-dedupe-expire-1d` |
| `site/` (published website) | **Current: forever; non-current: 7 days (keep 1)** — every content-hashed redeploy versions the whole tree; `rollback_site.sh` rebuilds from git and never reads noncurrent S3 versions, so this cannot break rollback | #2642 — `site-expire-noncurrent-7d` |
| `dashboard/`, `blog/` | **Forever** (static content) | None — long-lived public assets |

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
- Two distinct artefacts, and conflating them would be a privacy incident: `lambdas/operational/data_export_lambda.py` is the **owner's** full export (every partition, private `exports/` prefix, on demand); the #1400 nightly archive at `/archive/latest.tar.gz` is **public** and contains only the Tier 0 surface. The public archive makes no promise about the owner's export, and the owner's export never enters it — see `docs/PERMANENCE_CONTRACT.md` §6.
- `lambdas/data_export_lambda.py` exists; on-demand only. Generates a snapshot of all DDB partitions + S3 archive references.
- Census derives from `phase_taxonomy.SOURCE_CLASS` (#498/X-10), not a hand count — every non-`SYSTEM_STATE` source is covered automatically as new sources are added (86 sources as of 2026-07-18). The prior "audit P7.1 still outstanding" concern (a hand-maintained count that would silently drift) is resolved structurally by that dynamic derivation.

### Deletion
- `lambdas/delete_user_data_lambda.py` is **implemented, CDK-deployed** (`life-platform-delete-user-data`, `cdk/stacks/operational_stack.py`), **alarmed** (`life-platform-delete-user-data-errors`), and **unit-tested** (`tests/test_delete_user_data.py`). It wipes a user's DDB items + S3 objects + per-user Secrets Manager entries in one call, writes an audit record to `USER#admin#SOURCE#deletion_log`, and refuses protected users (`matthew`/`admin`/`system`) in code.
- **#1350 addition:** a second event shape (`{"subscriber_email": "...", "confirm": "DELETE"}`) deletes ONE subscriber row — the shape the generic `user_id` path structurally cannot reach, since subscriber rows live under the owner's pk namespace (`USER#matthew#SOURCE#subscribers`), not a per-user pk.
- **Trigger:** manual invocation only (`aws lambda invoke`, below) — there is no self-service request-driven web form. That gap (a public delete-my-data page) is real but distinct from "not yet wired"; the underlying capability exists, deployed, and tested. The Phase 6 multi-user roll-out (formally deferred per ADR-057) is the context for whether a self-service form is ever built.

### Access
- Matthew accesses everything via MCP (Claude Desktop) or `dash.averagejoematt.com`.
- Subscribers see only Tier 0 + their interaction history (via subscriber token).

---

## Delete Procedure (today — via the deployed Lambda)

For a clean wipe of a test user's data, or a single subscriber's data, invoke
`life-platform-delete-user-data` directly. It performs the DDB scan+batch-delete,
S3 prefix cleanup, and per-user Secrets Manager deletion in one call — no separate
manual steps.

```bash
# ── Generic user wipe (never matthew/admin/system — refused in code) ──
USER_ID=test_user_to_delete

# 1. Dry run — counts what WOULD be deleted, deletes nothing
aws lambda invoke --function-name life-platform-delete-user-data \
  --payload "{\"user_id\":\"${USER_ID}\",\"dry_run\":true}" \
  --cli-binary-format raw-in-base64-out /tmp/plan.json && cat /tmp/plan.json

# 2. Real delete — requires the explicit confirm string
aws lambda invoke --function-name life-platform-delete-user-data \
  --payload "{\"user_id\":\"${USER_ID}\",\"confirm\":\"DELETE\"}" \
  --cli-binary-format raw-in-base64-out /tmp/result.json && cat /tmp/result.json

# ── Single subscriber (#1350) — narrower: touches ONE EMAIL# row only ──
EMAIL=person@example.com

aws lambda invoke --function-name life-platform-delete-user-data \
  --payload "{\"subscriber_email\":\"${EMAIL}\",\"dry_run\":true}" \
  --cli-binary-format raw-in-base64-out /tmp/sub_plan.json && cat /tmp/sub_plan.json

aws lambda invoke --function-name life-platform-delete-user-data \
  --payload "{\"subscriber_email\":\"${EMAIL}\",\"confirm\":\"DELETE\"}" \
  --cli-binary-format raw-in-base64-out /tmp/sub_result.json && cat /tmp/sub_result.json

# ── CloudTrail confirmation ──
# Wait ≤24h for CloudTrail to record the deletions; archive the trail entries
# as the audit trail of the deletion event (in addition to the Lambda's own
# USER#admin#SOURCE#deletion_log audit record).
```

For the RETENTION-WINDOW bulk purge/anonymize of already-unsubscribed subscriber
rows (distinct from the single-subscriber delete above), see `deploy/subscriber_retention_purge.py`
and the "Subscriber emails" retention row (#1350) — gated on Matthew signing a window.

---

## Compliance Posture (current state)

- **GDPR**: not a GDPR data subject (US-based, no EU users)
- **HIPAA**: not a covered entity (not a healthcare provider; data is self-tracked)
- **CCPA**: technically applicable if California user added; delete-account flow (P7.3) is implemented (`delete_user_data_lambda`, both full-user and single-subscriber shapes, #1350) — the remaining gap is a self-service web form (manual `aws lambda invoke` only today)
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
| 2026-07-13 | Repo flipped PRIVATE (was public since inception) — closes the `docs/coaching/` exposure this doc's own scope note had flagged OPEN | [[project_repo_visibility]] |
| 2026-07-18 | #1351 current-truth pass: repo-visibility + delete-lambda claims corrected, data-export census note updated (dynamic, not a hand count), 2026-07 data classes (private_intake #1405, flourishing #1403, felt_probe #1409) added, Manual Delete Procedure rewritten around the deployed lambda; `scripts/check_doc_facts.py` now polices repo-visibility/delete-lambda-status/Verified-freshness claims on this doc | #1351 |
| 2026-07-18 | #1350 code half: "Raj directive" never-delete comment replaced with a pointer to this doc's (unsigned) retention row; `deploy/subscriber_retention_purge.py` purge/anonymize implementation + `delete_user_data_lambda` single-subscriber deletion shipped, one-command-ready pending Matthew's window sign-off | #1350 |
| 2026-07-19 | `generated/qa_archive/` added (90d, audit-log class): generation-time archive of every AI surface — text written by `lambdas/common/qa_archive.py` at each surface's publish point, screenshots by the daily standalone visual-qa sweep. No new PII class: archives the already-public reader-facing text plus rendered-page screenshots | #1441 |
| 2026-07-25 | #1350 [gate:owner] **SIGNED**: subscriber emails → anonymize 548 days (18 months) post-unsubscribe (was UNSIGNED). Signed window/mode centralized in `lambdas/content/subscriber_retention.py`; enacted weekly by `delete_user_data_lambda`'s `subscriber_retention_sweep` EventBridge rule (reuses existing IAM — no role change); guard test `tests/test_subscriber_retention_sweep.py` added | #1350 |
| 2026-08-18 | `deploys/` gained `NoncurrentVersionExpiration` (7d, keep 1) and `site/` gained a noncurrent-version rule (7d, keep 1) — closes 67 GB of unbounded noncurrent-version growth (`life-platform-s3-bucket-size-high` red 4.5 days). `imports/` found accumulating noncurrent versions under zero current bytes (2.23 GB) — flagged, not yet covered, out of scope for this pass | #2642 |
| 2026-08-23 | #3043 (DIL-001/DIL-012) containment: 5 PRIVATE-marked `docs/coaching/` files relocated to `s3://matthew-life-platform/config/coaching/`; scope note rewritten to the true PUBLIC posture (the pre-fix note still claimed PRIVATE, 34 days after the 07-20 public flip); `check_doc_facts.py` repo-visibility gate un-inverted (asserts LIVE visibility via `gh api`, was hardcoded "truth is PRIVATE"); structural marker guard `tests/test_no_private_markers_3043.py` added; dated risk acceptance for the historical exposure recorded in the diligence register | #3043 |
| 2026-08-23 | #3044 (DIL-003/DIL-013) **retention row re-signed v2**: subscriber emails → **anonymize AT unsubscribe (0 days)**; the handler scrubs inline, the weekly sweep demoted to backstop (≤7d worst case). Unsubscribe links tokenized fleet-wide (signed HMAC over the email hash — no plaintext email in URLs; legacy links sunset 2026-09-22); `/privacy/` copy rewritten to the implemented contract | #3044 |
| 2026-08-23 | #3045 (DIL-008/DIL-011, ADR-155, `gate:owner` signed): Tier-2 publication becomes a recorded decision — `TIER_OWNER_PUBLISHED` stamp added to `lambdas/privacy/field_tiers.py`; the full currently-served public surface (vitals set, labs panel, sleep-stage trio, lean mass, DEXA summary) stamped by explicit consent; every remaining Tier-2 prose row ported into the registry (field-level or source-level); this doc's Tier-2 section now GUARDED against the registry by `tests/test_data_governance_tier_guard_3045.py` — the twin-sources drift class is closed | #3045 |
| 2026-08-24 | DIL-026/#2799: `imports/` closed — gained `NoncurrentVersionExpiration` (7d, keep 1), same shape as `raw/`. Was the flagged-but-out-of-scope gap from #2642's pass (2.07 GB noncurrent measured under ~0 current bytes, unbounded age — confirmed again live). Lifecycle config externalized to `deploy/s3_lifecycle.json` (single writer for both `apply_s3_lifecycle.sh` and the new declared-vs-live drift assertion, `deploy/drift_sentinel.py::check_s3_lifecycle`, weekly). `life-platform-s3-bucket-size-high` re-derived 50GB → 65GiB from measured steady-state (deploys/ 7-day rolling churn dominates at ~41-44GB under the now-routine multi-agent deploy cadence, not a coverage gap — the existing #2642 rule is confirmed live and correctly configured) | #2799 |

---

**Verified:** 2026-07-25


## Editorial guardrails (public surfaces) — canonical home

Migrated from the frozen BACKLOG archive (2026-07-10 — a live guardrail was buried in a
deprecated doc). On ANY public surface (site, OG images, RSS, podcasts, build beats):

- No employer / role / industry. Partner is never named.
- **Vices:** only *alcohol* and *food-delivery* categories are ever named publicly; all
  other vice categories are aggregate-only (streak counts, no labels). See
  `feedback_sensitive_content` policy — the two never-public vice categories (vocabulary in the ER-06 non-committed channel, #2370) must never be public.
- Bereavement content is opt-in only.
- Correlative framing always ("associated with", never "caused").
- Down-weeks are always visible — absence of bad data is a lie of omission (ADR-104).
- Chronological age is never published (PhenoAge Option A — bio-age only).

## Scope note: the PII guard vs the repo itself

`deploy/pii_surface_guard.py` scans the **published site surface (`site/`) only** — it
has never scanned the repo tree. **The repo is PUBLIC** (deliberately, since the
2026-07-20 flip — [[project_repo_visibility]]), so repo visibility is **not** a privacy
control at all: anything tracked in the tree is world-readable by design. The real
controls for owner-private material are:

- **Relocation out of the tree.** Owner-private coaching material (Tier-2 owner
  biometrics/training calibration) lives at the S3 owner prefix
  `s3://matthew-life-platform/config/coaching/` (delete-protected `config/` prefix,
  owner credentials only) — relocated 2026-08-23 (#3043, DIL-001); see
  `docs/coaching/README.md` for the file list. What remains in `docs/coaching/` is
  deliberately public.
- **The structural marker guard.** `tests/test_no_private_markers_3043.py` fails CI if
  any tracked file declares itself PRIVATE — the in-band marker in a public tree is
  itself the defect.
- **The live-visibility fact gate.** `scripts/check_doc_facts.py` verifies this doc's
  repo-visibility claims against the LIVE GitHub API (not a hardcoded truth — the
  pre-#3043 gate hardcoded "PRIVATE" and would have redded the honest correction).

Historical exposure of the five relocated files (world-readable 2026-05→2026-07-13 and
2026-07-20→2026-08-23) is accepted as history: a git-history rewrite was priced out
(1,454 retained GitHub pull refs keep the content reachable regardless) — dated risk
acceptance in `docs/reviews/DILIGENCE_2026-08-23_RESPONSE.md` (DIL-001). The
containment is forward-looking.
