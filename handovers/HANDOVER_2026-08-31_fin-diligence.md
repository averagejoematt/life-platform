# Handover — 2026-08-31 (FABLE 5): The financial diligence — a CFO panel, the August close, and the honest answer to "$30–50/mo"

**Session:** Claude Fable 5, plan-mode entry. Driving ask: a full-platform financial
diligence "as if CTOs, AWS architects, engineers, PMs and consultants reviewed it" —
cost breakdown platform-vs-feature, permanent reductions AND temporary toggle options,
feature-flag evaluation, better artifacts/tagging for repeat exercises, MoM growth
governance. Owner scoped it live: **review + design, NO implementation code** (fixes
land as issues); TCO AWS-only. Ran as 5 parallel expert lanes (AWS architect · AI cost
engineer · CTO decomposition · product/PM · FinOps repeatability, waves ≤3) over a live
Phase-0 CE/CloudWatch/SSM pull, then 2 adversarial verification passes.

## What shipped (all merged to main, docs-only — no deploys needed)

- **The August COST_TRACKER close** (`31a246646`): CE actual **$175.85** (+79% MoM),
  26/31 days at tier ≥1 (tier 2 from 08-26), cost/reader-week **$0.044** (uniques mean
  897 n=5, peak 1,011 on 08-30 — first reading over the 900 surge bar), CallerClass
  split (partial-month, dimension live 08-23): **ci+dev = 63% of stamped AI spend**.
- **The tagging rejection logged** in the Cost Decisions Log (`bcf1d053f`): per-domain
  tags can slice only ~6–7% of spend — REJECTED so it's never re-proposed.
- **12 issues filed #3366–#3377** under epic #2801 (idempotency stamp
  `review:fin-diligence-2026-08-31`), + 2 scope comments: #3373 got the **named
  postures** design (full ≈$110–135 / lean ≈$95 / low-power ≈$60 / hibernate ≈$45 —
  the owner's "$30–50/mo" question answered as a posture choice, not an efficiency
  claim), #3367 got the brief's sub-feature decomposition + walk-back ladder +
  read-evidence precondition.
- **The diligence report artifact** "The Run-Rate Diligence" (private page: MoM stacked
  chart, Aug daily Bedrock with spike annotations, platform-vs-feature tree, verified
  portfolio, toggle menu, 5 numbered owner asks).
- Wrap-time backlog repairs: #3378 + #3365 brought up to the ADR-099 contract; #3368 +
  #3371 promoted → Now (two-edit promotions, score arrows retargeted).

## What was verified (the diligence's own bar)

Every actionable finding re-verified against live AWS/git evidence: **all 6 AI/product
findings CONFIRMED** (one date corrected: `unknown` $0/day since 08-28 not 08-27), 3 of
5 AWS findings CONFIRMED, **1 REFUTED as an already-decided duplicate** (the us-east-1
billing alarms — #2962/#2961 decided their retirement, closed, never executed → that
became #3377's real content), 1 corrected on arithmetic (trimming RegenDiscarded alone
leaves 127 > 120). Headline verified finds: **ai-expert-analyzer regenerates a weekly
product daily** — the "enforced in-handler" CDK comment describes a gate that was never
written, proven by full-history `git log -S` (#3366, ~$3.7/mo free); **72 GB of S3 is
noncurrent deploy-bundle versions**, not the DIL-027 replica (#3368); daily-brief runs
36 calls/day at 4.7% cache-hit (#3367). Ceiling revert verified via
`budget_ceilings.py`: tomorrow 09-01 the family is {215, 252}, AWS Budgets backstop 215.

## The numbers that matter going forward

Steady state ≈ **$110–135/mo** (floor ~$50, 48% of it deliberate coverage · spike-free
Bedrock $45–75 · ~10% tax). True waste found: **~$11–16/mo** (~10–12% — efficiently
run). August's extra ~$50 was build cadence (`ci` class ran ~$1.80/day in heavy weeks ≈
$54/mo run-rate). The toggle menu maxes at ~$35/mo and only ~$10 of it has a switch
today — that gap is #3373's business case.

## Gotchas hit

- **The piped-exit trap, personally:** `emf_series_census.py --strict | tail` read as
  exit 0; unpiped it exits **1** (LifePlatform/AI 151 > 120). The census is RED, so the
  PROPORTIONALITY census line was correctly NOT appended (#3370 owns the re-derivation).
- `ai_spend_attribution.py`'s first invocation returned partial data (ranks stable on
  runs 2–3 at $82.71); run-twice check now specced into #3375.
- Main moved mid-push (peer commit `8d031017b` landed 18s after `bcf1d053f`); my runs
  rendered `cancelled` via the concurrency group — the successor's green Docs CI
  validated the tree containing both my commits. Not a swallow; runs existed.

## Gate lines

**Build beat:** none — review+design session; what shipped is internal ledger truth +
filed issues, nothing reader-public.
**Docs:** docs/COST_TRACKER.md (August close + Cost Decisions Log row),
docs/INCIDENT_LOG.md (+1 row), docs/alarm_citations.json (+1 entry).
**Decisions:** none needed — the session's decisions are cost decisions and live in
COST_TRACKER's Cost Decisions Log (the tagging rejection), not architecture posture.
**Main:** green (8599a02a) — HEAD `8d031017b` (peer commit) has its CI/CD run in
flight; the green vouches for 8599a02a until it completes.
**Incidents:** 1 row added — compute-pipeline-stale 24h flap (fired 08-30 15:57Z,
cleared 08-31 15:57Z between wraps; caught by the #2912 flap detector, not observation;
not root-caused — review+design scope; cited in alarm_citations.json).
**Stash/hooks:** clean
**Closures:** none — no issues closed this session · DoD: scanned=28
window=closed>=2026-08-31 hits=2 findings=2 dispositioned=1 mode=warn — both hits
(#3317 post-close-comment, #3318 post-close-assertion) are prior sessions' closes from
earlier today, already carrying their own sessions' record; not this session's to
disposition.
**Backlog:** Now 3 actionable (promoted #3368, #3371 by printed rank, both
model:sonnet; contract repairs on #3378, #3365); Later sweep — no stale Later issues
printed.
**Alarms:** 0 red >72h uncited; 1 flap (compute-pipeline-stale) answered with an
INCIDENT_LOG row + registry entry — board otherwise clean per
`check_alarm_citations.py`.
**CI warnings:** 7 — six "Pending owner cdk deploy"
(Web/Serve/Monitoring/Ingestion/Email/Compute) are the standing owner batch already
filed as #3365 (cited, gate:owner); one Unit-Tests duration 1971s vs 1950s budget
(+1.1%) — deliberate no-action: a single reading inside the #3265-measured 88.5%
queue-noise spread; re-measure at the next wrap before any raise (`--decoded` run exit
0).
**Ledger:** none — no standing machinery shipped (review+design session; all machinery
landed as issue designs #3373/#3374/#3375).

## Residual / next picks

- Work the diligence Now queue: #3366 (expert-analyzer weekly gate), #3370 (AI-namespace
  budget re-derivation — also un-reds the census for future wraps), #3368 (deploys/
  lifecycle), #3371 (ARCHITECTURE stale table + sync-rule retirement, one PR).
- #3377 owner deletion batch (buddy-auth secret + 2 billing alarms) — gate:owner.
- #3365 seven pending owner cdk deploys — gate:owner (clean-window preconditions in its
  acceptance).
- Owner asks 1–5 in the diligence report (heartbeat cadence #2837-adjacent trim call,
  brief cache diet approval #3367, revenue posture) — not-work — owner decisions,
  enumerated in the report artifact.
- 09-01: verify the $215 revert in the governor log — not-work — calendar check, next
  session boot.
- #2883 drift-bar re-derivation on September clean data — standing, already scheduled.
- September close: use #3375's assembler spec if landed; the close ritual now has the
  Aug row as its template.
