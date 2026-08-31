---
name: cost-diligence
description: "Run full-P&L cost diligence: pull live AWS cost truth, decompose the drivers, and produce a ranked stop/reduce/redesign/merge portfolio with numbered owner asks. Use when asked about spend, the Bedrock budget ceiling, a cost spike, or where money is going."
user-invocable: true
argument-hint: "[focus area]"
allowed-tools: Read, Write, Edit, Glob, Grep, Bash, Task, Agent, TodoWrite, WebFetch, WebSearch
---

Run the full-P&L cost diligence: pull live cost truth, decompose the drivers, and turn
the numbers into a ranked stop/reduce/redesign/merge portfolio with numbered owner asks.

## Arguments: $ARGUMENTS

`$ARGUMENTS` may name a focus (`ai`, `floor`, `close`, or a service name) to run one
phase deep instead of the full sweep. `close` = just the COST_TRACKER monthly close
ritual (start from `python3 scripts/monthly_close.py` — Phase 5 item 3). Default with
no arguments: the full diligence.

## Posture

You are a diligence team, not a dashboard. The failure mode this command exists to fix:
analysis that never becomes a decision. Every phase ends in either a **sized finding**
(what to stop / reduce / redesign / merge, in $/mo with effort and risk) or an explicit
"at floor — no action". Numbers carry uncertainty and n (ADR-105). Never re-propose a
cut the Cost Decisions Log in `docs/COST_TRACKER.md` already shows executed or rejected,
and never trade silent-failure coverage for dollars (ADR-116's governing rule).

Read first: `docs/COST_TRACKER.md` (the ledger + close ritual + decisions log), epic
#2801 and its open stories (the live portfolio — extend it, don't duplicate it),
`docs/PROPORTIONALITY.md` (rent classes — honest categories, no invented dollars).

## Phase 1 — Pull (the standard query pack, all read-only)

Run these exactly; they are the reproducible instrument. CE queries cost $0.01 each —
run each once.

```bash
# 1. Monthly trajectory by service (extend Start back as history grows)
aws ce get-cost-and-usage --time-period Start=<year>-01-01,End=<next-month>-01 \
  --granularity MONTHLY --metrics UnblendedCost --group-by Type=DIMENSION,Key=SERVICE

# 2. Usage-type detail for the non-AI floor (what is the CloudWatch/Secrets money, exactly)
aws ce get-cost-and-usage --time-period Start=<prev-month>-01,End=<next-month>-01 \
  --granularity MONTHLY --metrics UnblendedCost UsageQuantity \
  --filter '{"Dimensions":{"Key":"SERVICE","Values":["AmazonCloudWatch","AWS Secrets Manager","AWS Key Management Service","AWS Cost Explorer"]}}' \
  --group-by Type=DIMENSION,Key=USAGE_TYPE

# 3. Bedrock daily by model (steady state vs spikes — compute mean/sd of the spike-free days)
aws ce get-cost-and-usage --time-period Start=<month>-01,End=<today+1> --granularity DAILY \
  --metrics UnblendedCost \
  --filter '{"Dimensions":{"Key":"SERVICE","Values":["Claude Haiku 4.5 (Amazon Bedrock Edition)","Claude Sonnet 4.6 (Amazon Bedrock Edition)"]}}' \
  --group-by Type=DIMENSION,Key=SERVICE
# NB: keep this Values list in sync with the models actually billing — check query 1's
# service names each run; a renamed/added model silently vanishes from a stale filter.

# 4. Bedrock by token class (cached vs uncached input — the input-diet gauge)
aws ce get-cost-and-usage --time-period Start=<month>-01,End=<today+1> --granularity MONTHLY \
  --metrics UnblendedCost \
  --filter '{"Dimensions":{"Key":"SERVICE","Values":[<same Bedrock model list>]}}' \
  --group-by Type=DIMENSION,Key=USAGE_TYPE

# 5. Live estates (the physical inventory behind the CloudWatch bill)
aws cloudwatch describe-alarms --query 'length(MetricAlarms)'          # alarm count
python3 deploy/emf_series_census.py --strict                          # EMF estate, graded (#2837)

# 6. The governor's own view (drift check: its numbers vs CE's)
aws ssm get-parameter --name /life-platform/budget-breakdown --query Parameter.Value --output text

# 7. CallerClass split — the platform running itself vs a human building it (#2892)
for c in prod-cron remediation ci dev-session; do
  printf '%-12s ' "$c"
  aws cloudwatch get-metric-statistics --namespace LifePlatform/AI \
    --metric-name EstimatedCostUSD --dimensions Name=CallerClass,Value="$c" \
    --start-time <window-start>T00:00:00Z --end-time <window-end>T00:00:00Z \
    --period <window-seconds> --statistics Sum --region us-west-2 \
    --query 'Datapoints[0].Sum' --output text
done
# WINDOW CAVEAT: the CallerClass dimension is live only from 2026-08-23, so any window
# reaching earlier reads a PARTIAL stamp — the 2026-08-31 panel's read covered only a
# ~7-day stamped window of August. Always print the effective stamped window next to the
# split, record the ci+dev SHARE of the stamped dollars, and never present the stamped
# dollars as the month's AI spend (the self-emitted metric under-counts regardless —
# the CostMetricDriftRatio caveat). An all-zero split is NO SIGNAL, not "100% prod".
```

Also pull: `scripts/ai_spend_attribution.py` for per-feature AI ranking — **run it
TWICE and diff** (`scripts/monthly_close.py` scripts the diff): its first invocation
returned partial data on 2026-08-31 (nondeterminism observed n=1, #3375); if the runs
diverge, trust neither and run a third, using the numbers two runs agree on. And the
AWS CE forecast (`aws ce get-cost-forecast`) **only to distrust it** — record it next
to the measured spike-free run-rate (mean ± CI of recent clean days); the measured
number is the forecast of record, the CE forecast is spike-contaminated.

## Phase 2 — Decompose

Build the driver tree and diff it against the last close in `docs/COST_TRACKER.md`:

- **Fixed floor** (runs at $0 usage): CloudWatch metric-months + alarm-months, Secrets
  Manager secret-months, KMS keys, Route 53, CE API self-cost. Name the physical count
  behind each dollar (secrets × $0.40, alarms × $0.10, metric series).
- **Variable** (scales with behavior): Bedrock by model, split **steady-state vs
  dev-spike** (the spike-free daily mean is the steady state; spikes are attributed to
  sessions/events by date). Tax rides everything at ~10% — apply it to every cut you size.
- **Committed**: RIs/Savings Plans (none expected at this scale — say so explicitly).
- **Contingent**: costs that appear on a state flip — GitHub Actions minutes if the repo
  goes private (~11.8k min/mo), vendor per-post billing invisible to the governor
  (#1631 class), the surge ceiling.
- **Drift check**: governor `mtd`/`projected` vs CE actual, and
  `CostMetricDriftRatio` — if the gauge disagrees with the bill, diagnosing the gauge is
  a finding (the #2883 lesson: the 2.44x ratio was mostly the gauge measuring itself).
- **The platform-vs-feature tree** (the 2026-08-31 panel's decisive cut): split the
  whole bill down a second axis before sizing anything — **the platform running itself**
  (the non-AI floor + `prod-cron` + `remediation` AI) vs **a human building it** (`ci` +
  `dev-session` AI, episodic by construction). August read 63% of stamped AI spend as
  episodic: the PRODUCT costs ~July money, BUILDING it is what surged. Then, inside the
  platform branch, attribute to named features (`scripts/ai_spend_attribution.py`
  per-Lambda, per-feature alarm/EMF rent from the ledger) — a cut proposal must name the
  feature and audience it degrades, not a vague service line. State the steady-state
  run-rate (platform branch, spike-free) separately from the headline bill in every
  report; conflating them is how a dev-heavy month reads as a run-rate change.

## Phase 3 — Full P&L (the consultant lens, owner-facing)

AWS is the actionable core, but report total cost of ownership honestly:

- AWS (above) + domain/registrar + GitHub (state the contingent overage) + the Claude
  subscription as the dev cost (owner-supplied; pull real spend via Monarch MCP when
  connected) + any metered vendors.
- Revenue side: currently $0 by design. Surface the standing question — self-sustaining
  (subscriptions / sponsorship / the fork-me template #2541) vs hobby-with-a-hard-ceiling
  — as an **owner ask, never an engineering task**.
- Scale note: state what 10x readers costs (historically ≈ pennies — CloudFront/S3/
  site-api are static-cheap, website_ai is rate-limited at ~$0.02/call). Scale anxiety
  must not drive cost decisions; verify this is still true each run.

## Phase 4 — Opportunity scan (six moves, each finding sized)

For each driver, ask all six; write down the "no" answers too:

1. **Eliminate** — is anything write-only/unread? (EMF series feeding no alarm or
   dashboard, orphan alarms, unused secrets.)
2. **Reduce rate** — cheaper tier for same behavior (model tiering Sonnet→Haiku,
   cadence trims like the CE-polling precedent).
3. **Reduce usage** — same capability, fewer units (input-token diet, change-gated
   regeneration, log retention).
4. **Redesign** — different shape, same outcome (the WAF→in-Lambda rate-limiter
   precedent; batch inference stays deferred per ADR-132 until
   `scripts/batch_feasibility.py` trips at ~120 calls/day).
5. **Merge** — consolidate paid units (domain-grouped secrets, SET-guarded alarms per
   #2824 — bounded by ADR-116).
6. **Renegotiate the envelope** — the ceiling/tier bands themselves (ADR-133 base,
   surge threshold): is the budget signaling anomaly, or encoding permanent degradation?

**Then inventory the levers** (the toggle menu — a lever nobody names is a lever the
next panel re-derives): enumerate every dial that trades capability for $/mo, each with
its switch (SSM param / env var / cadence constant), its measured band, and its CURRENT
state read live this run. The known set: the QA-depth dial (SSM
`/life-platform/qa-level`, #1452 — the ~$9–11/mo band in COST_TRACKER's rate card),
`/life-platform/remediation-mode`, the budget tier itself (`/life-platform/budget-tier`
— what ADR-125 has already paused is not also a finding), `AI_MODEL` tiering, the
governor's CE-polling cadence, and the #3373 named postures (full / lean / low-power /
hibernate) for the product-shape question. The 08-31 measurement to beat: the whole
toggle menu maxes ~$35/mo and only ~$10 of it had a switch — a proposed cut that has no
switch is a design story, not a dial flip.

Each finding: **$/mo (± range) · effort S/M/L · risk (what coverage or capability it
touches) · PROPORTIONALITY rent class**. Check every candidate against the Cost
Decisions Log and open #2801 stories before writing it down.

## Phase 5 — Output (the part that must not be skipped)

1. **Ranked portfolio table** — finding · $/mo · effort · risk · disposition
   (file / fold into existing issue / at-floor-no-action).
2. **Numbered owner asks** (the `feedback_prod_deploy_authorization` convention — ONE
   numbered list): decisions only the owner can make (ceiling changes, coverage
   tradeoffs, revenue posture).
3. **COST_TRACKER close entry** — run the monthly close ritual in
   `docs/COST_TRACKER.md` via `python3 scripts/monthly_close.py` (PRINT-ONLY: it runs
   the four ritual queries + the dial states + the run-twice attribution check and
   prints a candidate row; read its exit code unpiped — 1 means a query was unavailable
   or the attribution runs diverged). Review, then append the row **by hand** and update
   the Verified stamps **only for numbers actually re-read this run** (#2838: a fresh
   stamp on unverified prose is the defect, not diligence — which is why the assembler
   never writes).
3b. **Log the rejections too** — every move this run evaluated and REJECTED gets its
   own dated Cost Decisions Log row in `docs/COST_TRACKER.md` (decision, why, the facts
   that would have to change to re-propose). The 08-31 do-not-tag-Bedrock rejection
   originally had nowhere to land; an unrecorded rejection is a cut the next panel
   re-derives at full price. "At floor — no action" verdicts on a named driver belong
   here too.
4. **EMF series-count line** (#2837) — append this run's census line to the *EMF series
   census log* in `docs/PROPORTIONALITY.md`:
   `python3 deploy/emf_series_census.py --line`. That dated line is the only thing that
   advances the `emf-series-census` operating-calendar clock, and its exit code is the
   grade: **1 means a namespace went over its ledger budget or appeared unregistered** —
   fix the ledger row (or the cardinality) in the same close, do not append a line over
   a red. The retirement candidates are in `deploy/emf_namespace_ledger.py --retire`;
   acting on one is a code change with its own PR, and ADR-116 governs it — never trade
   silent-failure coverage for metric-months.
5. **File the net-new stories** under the cost epic via the issue-filer contract —
   plain `#N` references, never closing keywords (a negated closing keyword still
   closes).
6. If the ceiling or bands changed: `scripts/check_doc_facts.py`'s `BUDGET_OK` set and
   the AWS Budgets backstop amount (never the budget's name) move in the same PR.

## Reference run

The 2026-08-18 diligence (plan `nested-exploring-flurry`, memo on #2836, stories filed
under #2801) is the exemplar: baseline tables, the uncached-input finding ($30.81 of a
$61 Bedrock bill), and the two-step base recommendation all came from exactly this
sequence. A future run should reproduce its Phase-1 numbers from live CE before
proposing anything new.
