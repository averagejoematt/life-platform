# CloudWatch Alarm & Custom-Metric Audit — 2026-07

**Issue:** #411 (cost-05, epic #344 "The budget serves readers") · **ADR:** ADR-116
**Author:** infra/SRE pass, 2026-07-05 · **Region:** us-west-2 (§1–8) **+ us-east-1 (§9, #2829, 2026-08-21)** · **Account:** 205930651321

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

---

## 9. us-east-1 — the region this pass skipped (#2829, added 2026-08-21)

Everything above is **us-west-2 only** (the header says so, but nothing forced the next
pass to notice). us-east-1 exists because CloudFront/Lambda@Edge/ACM require it —
`LifePlatformWeb` is the only stack deployed there — and it was never run through the
§3 reconciliation. The elite review 2026-08-16 (WS-B) found it; #2829 closed it. This
section exists so **a region can never again be skipped silently: any future alarm
audit must either cover us-east-1 or extend this table.**

### The full us-east-1 estate (6 alarms, live-verified 2026-08-21)

| alarm | CDK-owned? | AlarmActions (live) | disposition |
|---|---|---|---|
| `email-subscriber-errors` | **YES** (`web_stack.py` → `web_alarms.py`) | `life-platform-alerts-us-east-1` | **ROUTED — fixed.** The #2829 title bug: OBS-07 defined it with `AlarmActions=[]`, so silent subscriber-conversion failures alerted no one. Routed by PR #2913 + the 2026-08-20 rescope; action live since 2026-08-20 19:09 PT |
| `life-platform-cf-auth-errors` | no (orphan) | **NONE — still silent** | **RETIRE → owner batch** (#2961 resolved 2026-08-27). Not adopted: the function is detached from every distribution, so this alarm's metric can never receive a datapoint. Routing it would ship a permanent false `OK`. Evidence + the exact delete command in §9a |
| `life-platform-dash-5xx-rate` | no (orphan) | `life-platform-alerts-us-east-1` | **DECIDED NOT TO ADOPT** (#2961 resolved 2026-08-27) — already routed; adoption buys a naming-only benefit at the price of a production CFN mutation on `LifePlatformWeb`. Reasoning in §9a |
| `life-platform-dash-total-errors` | no (orphan) | `life-platform-alerts-us-east-1` | **DECIDED NOT TO ADOPT** (#2961 resolved 2026-08-27). NB it watches the MAIN distribution (`E3S424OXQZ8NBE`), not dash's (`EM5NPX6NJN095`), despite its name → **#2963**, answered in §9a: the **name** is the lie, not the dimension — keep the dimension, rename recommended (not executed) |
| `life-platform-cost-alert` | no (orphan) | NONE | **RETIRE → #2962** (duplicate $5 AWS/Billing alarm, superseded by ADR-133 budget + cost_governor tiers; deletion is an owner AWS mutation) |
| `life-platform-ai-cost-soft-alarm` | no (orphan) | `life-platform-billing-alerts` | **RETIRE → #2962** (exact duplicate of cost-alert, routed to a second billing topic) |

Orphan provenance: `deploy/archive/onetime/create_cloudfront_5xx_alarm.sh` (both dash
alarms + the `life-platform-alerts-us-east-1` topic itself, which has a confirmed
email subscription — awsdev@), `create_lambda_edge_alarm.sh` (cf-auth-errors, created
action-less by its own comment because no us-east-1 topic existed yet), and
`deploy/archive/20260314/create_ai_cost_alarm.sh` (ai-cost-soft-alarm + the second
billing topic).

### 9a. #2961 resolved — the adoption was authorized, attempted, and stopped on a falsified premise (2026-08-27)

#2961 carried an explicit **owner authorization** (2026-08-27T02:15Z on the issue) to run
the `cdk import` non-interactively, overriding `docs/DECISIONS.md`'s ADR-081 "owner-run,
in-the-loop step" ruling — scoped to that issue and that operation only. Safeguard 3 made
`cf-auth-errors` the lead ("land it, verify, then decide whether the other two are worth
continuing"); safeguard 5 was **stop on the first surprise**.

Read-only pre-flight found the surprise. **No `cdk import` was run, no changeset created,
nothing in AWS mutated.** This subsection records the measurements and the three decisions
so no future session re-derives them.

#### The measurement that killed the lead item

`life-platform-cf-auth-errors` watches `AWS/Lambda` `Errors` on
`FunctionName=life-platform-cf-auth` (us-east-1). The function **exists and is `Active`**
(versions 1 and 2 published; `$LATEST` last modified 2026-04-24) — which is why a
describe-alarms-only pass reads it as healthy coverage. But it is **associated with zero
Lambda@Edge cache behaviours on every distribution in the account.** Counted across
`DefaultCacheBehavior.LambdaFunctionAssociations` **plus every entry in
`CacheBehaviors.Items`**, for all four distributions the account has:

| distribution | domain | Lambda@Edge associations |
|---|---|---:|
| `EM5NPX6NJN095` | dash.averagejoematt.com | **0** |
| `E1JOC1V6E6DDYI` | blog.averagejoematt.com | **0** |
| `ETTJ44FT0Z4GO` | buddy.averagejoematt.com | **0** |
| `E3S424OXQZ8NBE` | averagejoematt.com | **0** (default behaviour + all 22 ordered behaviours) |

Re-derive without redoing the reasoning — `list-distributions` first to confirm the account
still has exactly these four, then per id:

```bash
aws cloudfront list-distributions \
  --query "DistributionList.Items[].[Id,Aliases.Items[0]]" --output text
aws cloudfront get-distribution-config --id <ID> --query \
  "DistributionConfig.[DefaultCacheBehavior.LambdaFunctionAssociations.Quantity, \
   CacheBehaviors.Items[].LambdaFunctionAssociations.Quantity]" --output json
```

Two corroborations, both consistent: **no CloudWatch metric carrying a `cf-auth` dimension
exists** in us-east-1 or us-west-2 (full `AWS/Lambda` namespace listing, 26 metrics in
us-east-1), and the alarm's own `StateReasonData` is frozen at `2026-03-15T02:35:20Z` with
`recentDatapoints: []` — it has not re-evaluated in five months, because there is nothing
to evaluate. The function was detached at some point after version 2 (2026-05-09).

**So #2961's stated benefit — "Lambda@Edge auth failures lock dash/blog out with no alert"
— is false.** There is no Lambda@Edge in any request path.

#### Decision 1 — `cf-auth-errors`: RETIRE, do not adopt (owner batch)

Adopting *and routing* an alarm whose metric can never receive a datapoint produces a
permanent `OK` that reads as coverage and is not — and adoption would make that false green
**load-bearing IaC**. That is the #3200 class: a broken instrument looks exactly like a
working one. The acceptance as written would have made the estate worse, not better.

The real options were reattach the function (a product decision nobody has asked for) or
delete the alarm. Deletion is a production AWS mutation of the **same class as the #2962 leg
already folded into #2961 and already routed to the owner batch**, so it joins it there
rather than being executed unattended by a session:

```bash
aws cloudwatch delete-alarms --region us-east-1 --alarm-names life-platform-cf-auth-errors
```

#### Decision 2 — `dash-5xx-rate` / `dash-total-errors`: DECIDED NOT TO ADOPT

This is #2961 acceptance box 2's explicitly sanctioned branch ("or the decision not to adopt
them recorded in the §9 audit table"). Safeguard 3's gate never opened — the lead never
landed — so "then decide whether the other two are worth continuing" resolves to a decision,
not a continuation.

- Both **already route correctly** to `life-platform-alerts-us-east-1` (state OK,
  re-verified live 2026-08-27). `dash-5xx-rate` = `AWS/CloudFront 5xxErrorRate` on
  `EM5NPX6NJN095`; `dash-total-errors` = `AWS/CloudFront TotalErrorRate` on `E3S424OXQZ8NBE`.
- The benefit is, in #2961's own words, **"an import dance for a naming-only benefit."**
- The cost is a production CloudFormation mutation on `LifePlatformWeb` — the stack that
  already broke once (PR #2913) and whose breakage blocks the entire web deploy path.

Trading real risk to a shared deploy path for a naming-only benefit is not a good trade.
**Reopen this only if the payoff changes** — e.g. if one of these alarms needs a threshold or
action change, do the import then, when there is a functional reason to touch the stack.

#### Decision 3 — `dash-total-errors` naming (#2963, folded): keep the dimension, fix the name

Confirmed live: it carries `DistributionId=E3S424OXQZ8NBE` — the main site — despite the
"dash" name. Main-site total-error coverage is worth having, and dash already has
`dash-5xx-rate`. So the **name is the lie, not the dimension**: the recommendation is
`life-platform-site-total-errors` (or similar), keeping the dimension as-is.

**Recorded, not executed.** Renaming a CloudWatch alarm is a delete-and-recreate — it
discards alarm history and opens a coverage gap for the window. That cost is not worth
paying for a name alone, and it is the same owner-mutation class as decision 1, so it waits
for a batch where the alarm is being changed anyway.

#### What the authorization bought

The override was used as intended: it paid for a careful pre-flight that the previous "skip
it" recommendation would not have produced, and that pre-flight found the operation's
headline benefit did not exist. That is safeguard 5 working, not the authorization being
declined. The ruling it overrode is untouched and still stands — see `docs/DECISIONS.md`
ADR-081 "Adoption mechanics."

### Three lessons this region taught (the first two cost a blocked deploy to learn)

1. **Adoption needs `cdk import`, not a CREATE.** PR #2913 declared the three orphans
   in `web_alarms.py` with their existing physical names; CloudFormation pre-validates
   a CREATE against live names and failed early validation (`already exists`),
   blocking the entire `LifePlatformWeb` deploy on 2026-08-20. **A green `cdk synth`
   says the change is well-formed, not that it is deployable** — synth never consults
   live AWS state. Same family as "merged ≠ deployed" (#2806), one level earlier:
   *synth ≠ deployable*. `tests/test_web_alarms_2829.py` now pins the three names
   ABSENT from `web_alarms.py` until #2961 does the import properly.
2. **"IaC orphan" and "fires into the void" are different problems.** The issue title
   said 5 of 6 fire into the void; measured live, only 2 of 6 had no actions (the
   subscriber alarm, now fixed, and cf-auth-errors). Conflating the two inflates
   urgency and buries the genuinely silent alarm in hygiene work. Audit tables must
   carry the *measured* `AlarmActions` column, not infer it from IaC status.
3. **A routed alarm on a detached resource is worse than an unrouted one** (#2961,
   2026-08-27). `cf-auth-errors` looked like the highest-value item in the whole section —
   the one genuinely silent alarm — and it was the one that should never have been adopted.
   Neither `describe-alarms` nor `get-function` can tell you an alarm is dead: the alarm is
   well-formed and the function is `Active`. Only the *association* count is decisive.
   Generalised: **before routing or adopting any alarm, verify its metric has received a
   datapoint** (`list-metrics` for the dimension, and non-empty `recentDatapoints` in
   `StateReasonData`). An alarm that cannot fire, once routed, is a permanent `OK` that reads
   as coverage — the #3200 class, where a broken instrument is indistinguishable from a
   working one, and adoption into IaC makes the false green load-bearing.
