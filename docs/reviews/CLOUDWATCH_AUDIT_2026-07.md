# CloudWatch Alarm & Custom-Metric Audit — 2026-07

**Issue:** #411 (cost-05, epic #344 "The budget serves readers") · **ADR:** ADR-116
**Author:** infra/SRE pass, 2026-07-05 · **Region:** us-west-2 · **Account:** 205930651321

> Monitoring is the #2 cost line after AI (~$15/mo: `AlarmMonitorUsage` $10.46 +
> `MetricMonitorUsage` $4.41 in June). The mandate: every alarm and billable custom
> metric is **justified or retired**, WITHOUT reopening a silent-failure gap. Silent
> failure is this platform's most dangerous bug class, so this pass is surgical:
> **honesty over completeness — never trade a coverage gap for a few dollars.**

---

## 1. Headline numbers (live vs IaC reconciliation)

| Surface | Count | Note |
|---|---:|---|
| **Live metric alarms** (`describe-alarms`) | **136** | the issue's "~56 live" was a stale undercount |
| **Live composite alarms** | 0 | none exist |
| **Alarms DEFINED in CDK** (synth of all 8 stacks) | **107** | all 107 are live (0 code-not-live) |
| **Live-but-NOT-in-code (orphan drift)** | **29** | the reconciliation target |
| June billed alarm-months | ~108.65 | ≈ the 107 CDK-managed alarms averaged over the month |

**Explaining the "~56 live vs ~108 billed" gap in the issue:** the "~56" figure was
an undercount (likely a filtered console view). The real steady-state is **107
CDK-managed alarms** ≈ the 108 billed alarm-months. On top of those, **29 orphan
alarms** created outside CDK (legacy CLI-era `put-metric-alarm` remnants and
double-prefixed duplicates) drift the *current* live total to 136. The orphans are
the recoverable overhead; the 107 IaC alarms are the justified net.

**Alarm cost math:** standard alarm = **$0.10 / alarm-month**. 108 alarm-months ×
$0.10 = $10.87 ≈ the billed $10.46. Every alarm deleted saves $0.10/mo. (Note:
**composite alarms cost MORE** — $0.50/mo each — so "consolidate into a composite"
does *not* reduce the bill; only *deleting* alarms or replacing many with a single
**digest metric + one alarm** does. That shapes every recommendation below.)

---

## 2. What this PR changes (safe, reviewable, no coverage lost)

| Action | Count | $/mo |
|---|---:|---:|
| **RETIRE** orphan alarms — provably covered or dead metric | 18 | **−$1.80** |
| **ADOPT** unique orphans into IaC (rename, net-neutral count) | 2 | $0.00 |
| **KEEP** orphans left live (unique coverage, codify later) | 9 | $0.00 |
| **KEEP** all 107 CDK-defined alarms | 107 | $0.00 |

**Hard, safe saving this PR: ~$1.80/mo** (18 alarm-months). The full $4–6/mo target
is *reachable* but only via the 48-alarm compute/email consolidation, which is
**deliberately deferred** — see §5 for why it would reopen a silent-failure gap
today and the concrete follow-up that unlocks it safely.

Execution: the orphan deletes are in **`deploy/cloudwatch_retire_orphans.sh`** (a
reviewable, non-auto-run script the orchestrator runs). The 2 adopted alarms are
codified in `cdk/stacks/monitoring_stack.py` under IaC-owned names, so after the
orchestrator runs the script + `cdk deploy LifePlatformMonitoring`, live == IaC for
those two.

---

## 3. Orphan reconciliation table (the 29 live-not-in-code)

### 3a. RETIRE — delete forever (coverage provably preserved, or dead metric)

| Alarm | Justification |
|---|---|
| `challenge-generator-errors` | dup of code `ingestion-error-challenge-generator` (same fn Errors; code fires @1h vs this @24h) |
| `og-image-generator-errors` | dup of code `ingestion-error-og-image-generator` |
| `life-platform-subscriber-onboarding-errors` | dup of code `ingestion-error-subscriber-onboarding` |
| `life-platform-pipeline-health-check-errors` | dup of code `ingestion-error-pipeline-health-check` |
| `life-platform-life-platform-dlq-consumer-errors` | double-prefixed legacy dup of code `life-platform-dlq-consumer-errors` (300s, faster) |
| `life-platform-daily-brief-duration-p95` | daily-brief duration already covered by code `daily-brief-duration-high` (p99) + errors + no-invocations |
| `life-platform-mcp-duration-p95` | MCP duration covered by code `mcp-server-duration-high` + `slo-mcp-availability` |
| `life-platform-mcp-canary-failure-15min` | dup of code `life-platform-canary-mcp-failure` (SAME `CanaryMCPFail` metric) |
| `life-platform-ask-endpoint-errors` | **DEAD metric** — `AskEndpointErrors` is emitted nowhere in the codebase; the alarm is NB and can never fire. `/api/ask` errors are covered by `site-api-errors` + `life-platform-life-platform-site-api-ai-errors` |
| `food-delivery-ingestion-errors` | per-source ingest-error class **already retired by policy 2026-05-29**; freshness digest covers (see §4) |
| `life-platform-garmin-data-ingestion-errors` | **contradicts** the deliberate no-garmin-alarms decision (garmin is best-effort, excluded from fleet health); freshness covers |
| `life-platform-habitify-data-ingestion-errors` | per-source ingest-error class; freshness digest covers |
| `life-platform-measurements-ingestion-errors` | per-source ingest-error class; freshness digest covers |
| `life-platform-notion-journal-ingestion-errors` | per-source ingest-error class; freshness digest covers |
| `life-platform-weather-data-ingestion-errors` | per-source ingest-error class; freshness digest covers |
| `life-platform-dropbox-poll-errors` | per-source ingest-error class; freshness digest + `ingest-auth-unhealthy-24h` covers |
| `withings-oauth-consecutive-errors` | superseded by code `ingest-consecutive-failures-withings` + freshness |
| `life-platform-insight-email-parser-errors` | code creates this lambda with `alerts_topic=None` (**intentional no-alarm**); orphan contradicts current IaC intent |

### 3b. ADOPT — codify into IaC (unique coverage; renamed to IaC-owned names, net-neutral count)

| Live orphan (delete) | New IaC alarm (create) | Why |
|---|---|---|
| `life-platform-compute-pipeline-stale` | `compute-pipeline-stale` | UNIQUE: `LifePlatform/ComputePipelineStaleness` (Source=computed_metrics, Max≥1, NB) — emitted by `daily_brief_lambda`; watches the compute pipeline going stale behind the daily brief. No code equivalent. |
| `health-auto-export-no-invocations-24h` | `hae-webhook-no-invocations-24h` | UNIQUE: HAE webhook liveness (`AWS/Lambda Invocations < 1 / 24h`, **BREACHING**). The near-real-time CGM/water/BP webhook streams continuously, so <1 invocation/24h = a dead webhook. No code equivalent. |

Rename (not same-name reuse) is deliberate: it lets `cdk deploy` create the new
alarm with **no CloudFormation name collision** regardless of whether the delete
script has run yet — no deploy-ordering footgun. The script deletes the old names.

### 3c. KEEP orphan — unique coverage, deleting WOULD reopen a gap; defer codification

These 9 stay **live and untouched** (they work). Each is the *only* signal for its
failure; deleting to save $0.90/mo would reopen a silent-failure gap — forbidden.
They remain out-of-IaC drift, flagged for a future adopt-into-CDK PR (same rename
pattern as §3b). Left un-codified now to keep this PR's monitoring deploy small and
low-risk.

| Alarm | Unique coverage |
|---|---|
| `life-platform-recursive-loop` | MCP `RecursiveInvocationsDropped` failsafe (rare, real) |
| `life-platform-mcp-canary-latency-15min` | MCP synthetic latency (`CanaryLatencyMCP_ms`, soft) |
| `life-platform-life-platform-canary-errors` | watcher-of-watcher: the canary lambda's own Errors (the `Canary*Fail` alarms are NB → blind to a *dead* canary) |
| `life-platform-life-platform-qa-smoke-errors` | QA-smoke lambda self-health |
| `life-platform-life-platform-data-reconciliation-errors` | data-reconciliation lambda self-health |
| `life-platform-life-platform-site-api-ai-errors` | site-api-ai lambda self-health (also backstops `/api/ask`) |
| `life-platform-life-platform-pip-audit-errors` | pip-audit CVE-scan self-health (low value — prune candidate) |
| `life-platform-journal-enrichment-errors` | journal-enrichment lambda self-health |
| `life-platform-site-stats-refresh-errors` | site-stats-refresh lambda self-health |

---

## 4. Consolidation equivalence — per-source ingest errors → the freshness/liveness digest

The 8 `*-ingestion-errors` orphans in §3a are the **redundant per-source remnants**
of a consolidation the platform already implemented in code (monitoring_stack,
2026-05-29) but never finished cleaning up in live. Enumerating the covered failure
modes **before and after** deletion:

**Failure modes for a data source (whoop/withings/garmin/weather/…):**

| Failure mode | Before (per-source `*-errors` alarm) | After (delete it — remaining code coverage) |
|---|---|---|
| Source lambda throws on a run | ✅ per-source Errors≥1 | ⚠️ transient single throw not alarmed (this is the noise the 2026-05-29 removal targeted) |
| Source stops producing fresh data | ✅ (indirectly) | ✅ `slo-source-freshness` (StaleSourceCount≥1) + `ingest-liveness-unhealthy` (UnhealthySourceCount) |
| Source dies mid-window then resumes (interior gap) | ❌ blind | ✅ `freshness-interior-gap` (InteriorGapCount) |
| Auth/token silently suppresses a source | ❌ blind (returns healthy 200 "skip") | ✅ `ingest-auth-unhealthy-24h` (OAuth IngestAuthHealthy Min<1) + `ingest-consecutive-failures-*` |
| Source drops a record silently (API had it, we never stored) | ❌ blind | ✅ `ingest-reconciliation-strava` (Strava) |
| The detector itself stops running | ❌ blind | ✅ the 5 REL-01 heartbeats (BREACHING on N-day metric absence) |

**Conclusion:** the only failure mode the per-source `*-errors` alarm caught that the
digest does not is a *single transient throw that self-heals* — explicitly the noise
class the platform removed for the SIMP-2 sources. Deleting the 8 remnants makes
live consistent with the already-shipped digest design. **Net silent-failure
coverage: unchanged.** (The `withings-oauth-consecutive-errors` case is even
stronger — a purpose-built `ingest-consecutive-failures-withings` code alarm now
covers withings auth streaks directly.)

---

## 5. Deliberately NOT done (the honest gap to the $4–6 target)

The 48 `ingestion-error-*` alarms on the **compute (32) + email (16)** lambdas are
the bulk of the remaining bill (~$4.80/mo). They are **KEPT**, not consolidated,
because a merge would reopen a silent-failure gap **today**:

- **Composite alarms don't help** — they cost *more* ($0.50 each) and each child
  still bills.
- **A single metric-math alarm is impossible** — CloudWatch rejects `SEARCH` in
  alarms and caps metric-math at ~10 metrics; there are 48 functions.
- **The DLQ digest does NOT cover them.** Verified in CDK: **only 1 of 32 compute
  and 1 of 17 email lambdas pass `dlq=`** to `create_platform_lambda`. The other
  ~47 have **no dead-letter queue** — an async failure is retried twice and then
  **dropped silently**. So each per-lambda `ingestion-error-*` alarm is the *only*
  signal that lambda failed. Retiring them = a real silent-failure gap. Forbidden.

**Sanctioned follow-up to reach the target safely** (new story): wire `dlq=core.dlq`
to all compute/email lambdas (so terminal async failures land in the existing
`life-platform-ingestion-dlq`, already alarmed by `life-platform-ingestion-dlq-messages`
+ `life-platform-dlq-depth-warning`), **then** retire the ~47 per-lambda first-error
alarms in favor of the DLQ digest. That is a genuine per-N→digest consolidation with
provable equivalence — but it is a compute+email deploy with its own blast radius and
must not be rushed inside a monitoring-cost PR. Estimated additional saving: ~$4.70/mo,
which (with §2's $1.80) clears the $4–6 target. Recorded in ADR-116.

> **EXECUTED — 2026-07-07 (COST-01, #790).** Done. **Premise correction:** the
> "1 of 32 compute / 1 of 17 email pass `dlq=`" count above was a *live-AWS*
> undercount — in CDK, `dlq=local_dlq` has been in the `shared` dict of both
> `compute_stack.py` and `email_stack.py` since v3.2.9. `cdk synth --all` confirms
> **32/32 compute + 17/17 email app functions already carry a `DeadLetterConfig` →
> `life-platform-ingestion-dlq`** with a per-role `sqs:SendMessage` grant, so the DLQ
> path was already covering terminal async failures. The remaining step — retiring the
> now-redundant per-lambda alarms — shipped by setting `error_alarm=False` in both
> `shared` dicts, dropping all **48** `ingestion-error-*` alarms (32 compute + 16 email).
> Auto-discovered `alarm_count`: **113 → 65** (== synth grep of `AWS::CloudWatch::Alarm`).
> daily-brief unaffected (already `alerts_topic=None`, keeps its `MonitoringStack` alarms).
> Saving **~$4.80/mo**. Requires `cdk deploy` of Compute + Email.

---

## 6. Billable custom metrics (`MetricMonitorUsage` $4.41/mo)

Custom metrics bill $0.30/metric-month. The emitted namespaces:

| Namespace | Metrics | Role | Verdict |
|---|---|---|---|
| `LifePlatform/AI` | AnthropicInput/Output/CacheRead/CacheWriteTokens, EstimatedCostUSD, CoachQualityGateHeld | back `ai-*` cost alarms + ops dashboard (real cost governor) | KEEP |
| `LifePlatform/Budget` | BudgetTier, ProjectedMonthlySpend, AuthoritativeCostMTD, EstimatedMonthToDateSpend, CostMetricDriftRatio | back budget-tier alarms + governor | KEEP |
| `LifePlatform/Freshness` | Stale/Warning/Fresh/PartialCompleteness/InteriorGapCount, OAuthTokenStale, ManualRotationStale, AppleHealth* | back the freshness digest (the silent-failure net) | KEEP |
| `LifePlatform/IngestLiveness` | UnhealthySourceCount, ConsecutiveFailures, RunSuccess | back liveness alarms | KEEP |
| `LifePlatform/Canary` | Canary*Pass/Fail + Canary*Latency_ms | back canary alarms | KEEP |
| `LifePlatform/Coherence`, `/AICanary`, `/IngestReconciliation`, `/OAuth`, `/Podcast` | OverallAlarm / MissingActivityCount / IngestAuthHealthy / PanelcastPublished+Run | back the coherence/AI-canary/reconcile/auth/panelcast alarms | KEEP |
| `LifePlatform/SiteAPI` | DurationMs, ColdStart (× Route×Method dims) | feed the site-api dashboard only | KEEP (cheap, useful) |
| `LifePlatform` | ComputePipelineStaleness, **AskEndpointErrors** | ComputePipelineStaleness→adopted §3b; **AskEndpointErrors is dead** (never emitted) | dead metric ages out; no action needed beyond §3a alarm delete |
| `LifePlatform/Lambda` | DailyBriefMaxMemoryMB | backs `daily-brief-memory-high` (log-metric-filter) | KEEP |

**Verdict:** the custom-metric surface is load-bearing — every namespace backs an
alarm or the two ops dashboards. No custom metric is safely retirable without a code
change to *stop emitting* it (out of scope for a monitoring pass, and none is high
enough cost to justify the risk). `AskEndpointErrors` is the only dead one; it stops
billing once its last datapoint ages out of the 15-month retention (no action).

---

## 7. Incidental findings (not cost, noted for follow-up)

- **`panelcast-no-episode-7d`** watches `PanelcastPublished` with `treat_missing=BREACHING`.
  `list-metrics` shows `PanelcastRun` recently but not `PanelcastPublished` (no publish
  in the trailing 2 weeks) — confirm the panel is actually publishing, or this alarm is
  legitimately red. (`PanelcastPublished` *is* emitted by `coach_panel_podcast_lambda.py`;
  absence from list-metrics just means no publish recently.) Out of scope for #411.

---

## 8. Post-change ledger

- Live alarms: 136 → **118** after the script runs (20 deleted = 18 retired + 2
  renamed-away; 2 new IaC names created by `cdk deploy`; net −18).
- CDK-defined alarms: 107 → **109** (the 2 adopted).
- Remaining out-of-IaC drift: **9** (the §3c keep-orphans, each justified, flagged for a
  future adopt PR).
- Recovered: **~$1.80/mo** now; **~$4.80/mo more** by the §5 DLQ-digest follow-up
  (EXECUTED 2026-07-07, COST-01 #790 — 48 per-lambda `ingestion-error-*` alarms retired,
  CDK-defined alarm_count 113 → **65**).
