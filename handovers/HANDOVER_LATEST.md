# Handover — 2026-09-01/02 (Fable 5): Session R — the full drain + the A-Grade re-grade

**Session:** Claude Fable 5, executing the owner-approved Session R plan verbatim ("execute
the plan") — Phase 0 boot/probe, Phase 1 the full 8-lane drain, Phase 2 the #3042 A-Grade
closeout with the post-approval Phase 2 correction, Phase 3 the operator-staff filings,
Phase 4 this wrap. Fable's return lifted the bug-fix-only-on-Opus constraint; the owner's
posture (he USES the platform) is unchanged.

---

## What shipped (all merged; deploys via the pipeline's approved tip runs, verified by shipped CONTENT)

**9 issues closed**, each with an ADR-099 outcome verdict AND the canonical two-line
closure comment:

| PR | Issue | What |
|---|---|---|
| #3421 | **#3369** | The two prose-truth judges measured COMPLEMENTARY (union 30 claims over 10 paired days, 0/30 substantive overlap) — both kept, decision row in COST_TRACKER; the ≤$2–3/mo merge declined on evidence |
| #3427 | **#3374** | R1: `cost_surface` plane (schedules 88 · alarms 119 · emf 31 · secrets 28 · ai_features 18) exact-pinned in the #2845 drift gate, mutation-proven (a planted 29th secret reds it). R3: per-feature AI budget ledger, set-equality vs `_FEATURE_CUTOFF`, `unknown` DOWN-ONLY at $33.19, graded at close by `monthly_close.py` [5/5] — dogfooded, the founding month reds on a real $0.02 drift |
| #3425 | **#3395** | Smoke checks declare their surface; the site rollback declines by name on an `/api`/infra red. **Proven live post-merge**: dispatch run 33566710506 with `smoke_inject_failure=api` → `⛔ ROLLBACK DECLINED (api:1)`, `rollback_site.sh` never invoked, `/version.json` untouched, advisory #3433 auto-filed then auto-closed by the next green run. The #3352 class is now closed on BOTH gate legs |
| #3426 | **#3399** | The judge's `basis` field moved AFTER the note — autoregressive generation had committed the label before the retraction could be written, which is how a self-withdrawn finding gated as `impossibility`. Wire-fixture tests off the real run artifact; the field specimen below validated the fix within hours |
| #3428 | **#3414** | The board's ADR-108 voice verdict recovered on an async channel (Event-only observer; anti-reintroduction guard EXTENDED with a mutation-proved carve-out; brief wire asserted byte-unchanged). **Verified live end-to-end**: shipped zip carries the observer (build `9b602a37`), one real board ask → `BoardQualityGateVerdict{Surface=board_ask, Outcome=passed}` = 1.0 — the first verdict this surface has ever produced |
| #3432 | **#3417** | The "scale is weight-only" premise corrected everywhere (expired 2026-08-16); body-comp delta stays deleted by grounded decision (ADR-154 amendment); the lean-mass floor honestly recorded owner-monitored with a written revisit trigger (≥6 full scans / ≥6 weeks). Owner guidance recorded at the rail: **hold the handles** |
| #3434 | **#3376** | Per-door `PageViews7d{Door=…}` + `SyndicatedReferrals7d` from the CF-log parse the digest already runs — zero new collection, no client JS; both previously-unfalsifiable PROPORTIONALITY retire-triggers rewritten against series that exist |
| #3435 | **#3418** | The six `Pending owner cdk deploy` warnings were **unclearable by deploying, ever**: CloudFormation's GetTemplate API returns non-ASCII as literal `?` — all synths agree byte-for-byte, the live distribution holds the em-dash, the read-back does not. Gate taught the one-directional transcode (advisory non-IAM sites only; IAM stays strict, mutation-proved). H3 also true: #3365's "zero annotations" run carries all six (corrected on #3365). ONE real warning remains (Monitoring `Tags`) — owner ask below |
| — | **#3394** | Closed on tonight's run artifact: the cycle-14 stale-window findings are GONE (92 pass, 0 stale-cycle findings); the single remaining FAIL was the #3399 class's final pre-fix field specimen (judge note ends "Re-examined: this is CORRECT behavior" yet gated) — logged on #3399 as its acceptance checkpoint |

**Plus PR #3420 + #3431 (the #3042 flagship, below) and 10 issues filed:** #3419, #3422,
#3423, #3424, #3429, #3430, #3436, #3437 (+ #3433 auto-filed/auto-closed by design, and
#3373 folded into the staff frame by comment).

---

## Phase 2 — the #3042 A-Grade closeout (epic stays OPEN, honestly, on box 4 alone)

- **Box 1 was the program's own bug class applied to itself**: the epic said "20 of 52"
  while the register had held 52/52 since e619dd3d6. Ten pointer-only rows made terminal
  from closed-child evidence (#2890, #2578, #3050, #3046, #811, #3044, #1436, #3000);
  3 missing priced-table rows added (DIL-022 had claimed PRICED unbacked by the
  register's own bar); and the count is now ENFORCED: `diligence_verify.py::
  register_maps_all_52`, derived by parse, mutation-proved (removing DIL-041's row reds
  it), 13 PASS strict (PR #3420).
- **The fresh re-grade** (PR #3431, `docs/reviews/REGRADE_2026-09-01_FABLE.md`): three
  fresh-context Fable assessors + an adversarial finding-verifier pass — **4 of 9
  assessor findings confirmed (44% FP, the historical base rate; the pass stays
  load-bearing)**. Result: **3 of 9 domains ≥9** (Privacy 9.2 · Scientific validity 9.0 ·
  Governance 9.0) vs the corrected baseline of 2 of 9 (the 08-29 doc's own lead sentence
  miscounts its table). Grades moved BOTH directions — Reliability 8.5→8.0 and Data
  integrity 9.0→8.5 fell on real incidents — the instrument measuring, not drifting.
- **Verification reversed one grade-relevant claim**: the DIL-039/040 mechanical trigger
  (≥10 graded outcomes) FIRED on schedule 2026-08-31 — grades landed hours before the
  reset tombstoned the cohort. The register row now says trigger met, revisit DUE.
- 7 numbered owner asks posted on the epic (mirrored below). The "external" equivalence
  ruling is deliberately not needed today: the score doesn't clear the bar either way.

## The probe that grew (#3413's stated-unmeasured worst case)

The pre-agreed 7-persona probe answered structurally, not in latency: since #2930
(2026-08-20) the fan-out charge (unconditional `ADD` then `allowed = count <= limit`,
`rate_limiter.py:81-99`) makes a 7-persona panel charge 7 > 5 and 429 on a FRESH window
— live proof HTTP 429 in 1.6s, zero Bedrock calls. So the site's "convene the full board
(7)" checkbox has 429'd every reader who ticked it for 12 days including launch day, and
the doomed attempt burns their whole hour window. Filed **#3419** (P2); measurement
recorded on closed #3413; incident row added.

---

## Gotchas hit

1. **My own PR-checks waiter false-completed** — `awk '{print $2}'` split on spaces inside
   check NAMES (not the status column) and a transient empty `gh` read made grep see
   nothing: absence read as success, the exact class the memory warns about. Rewrote on
   `--json statusCheckRollup` requiring a NON-EMPTY rollup with zero pendings; used for
   every subsequent merge.
2. **The deploy pipeline outruns manual deploys** — `deploy_and_verify.sh` REFUSED to ship
   qa-smoke because live was already AHEAD (the ancestry preflight caught what would have
   been a rollback): the approved tip run had already fleet-deployed the change. Post-merge
   lambda ops in lane reports are usually already satisfied by the pipeline; verify by
   shipped content instead of re-deploying.
3. **A `[skip-reconcile]` tip mints no CI/CD run, and an ancestor-rejecting steward then
   rejects the last run-BEARING sha** — the train self-heals at the next run-minting
   commit (this wrap), but a steward built for #3422 must approve the newest RUN-BEARING
   sha, not require run.sha == tip. Recorded on #3422.
4. **A lane cannot mint a new ADR number** — the `adrs` literal in `platform_counts.py`
   is reconcile-bot-owned and not PR-exempt; #3417's lane proved it live and dodged via
   an ADR-154 amendment. Filed **#3437**.
5. **Session L's fan-out lesson held**: waves of ≤4 lanes + serial update-branch/re-green
   for census PRs — 8 lanes, 8 PRs, zero mid-flight deaths, 3 lanes self-recovered one
   CI iteration each.

---

## Gate lines

**Build beat:** 2026-09-02-the-rollback-that-learned-its-reach
**Docs:** updated in-PR by lanes (DECISIONS ADR-108/154/065 amendments, SCHEMA, PROPORTIONALITY ×4, INCIDENT_LOG fix note, SECRETS_MAP-adjacent register rows, engine docs re-verified) + this wrap: INCIDENT_LOG +1 row & Patterns regen, `docs/reviews/REGRADE_2026-09-01_FABLE.md` + register updates (PRs #3420/#3431)
**Decisions:** none needed — three dated amendments to existing ADRs landed inside lane PRs (ADR-108 async-observer scope on #3414; ADR-154 absence-semantics on #3417; ADR-065 GetTemplate-transcode residual on #3435); no new governance decision was made
**Main:** green (f38b7666)
**Incidents:** 1 row added — the full-board checkbox structurally 429-ing every reader 2026-08-20→open (#3419, found by probe not alarm; 12-day TTD is the row's own lesson)
**Stash/hooks:** clean
**Closures:** #3369, #3374, #3395, #3399, #3414, #3417, #3376, #3418, #3394 verdict-commented + canonical two-liners (plus #3433, the designed injection artifact) · DoD: scanned=4 window=closed>=2026-09-02 hits=0 findings=0 dispositioned=0 mode=warn
**Backlog:** Now live at 3+ actionable in-lane (promoted #3423, #3422, #3436 by stored rank via `backlog_next.py --refill-now --lane fable`, both edits each); Later sweep — `later_staleness` printed none, no calls owed
**Alarms:** all red >72h cited, all >14d cite filed issues (batch PASS); `ai-canary-overall` stayed OK all session
**CI warnings:** unverified at gather — the latest main run was still in progress at wrap (the wrap commit mints the next verdict); the standing seven from Session Q are now: six CURED by #3435 (the GetTemplate-`?` class, unclearable-by-deploy — one REAL Monitoring `Tags` warning remains, owner ask 6), duration budget = #3403 (its own acceptance waits for post-#3378 data, earliest ~09-08)
**Ledger:** rows added in-PR — #3374 (two ratchet rows), #3376 (traffic instrumentation row + two retire-triggers rewritten), #3395 (rollback-scope amendment on the Deploy-guardrails row), #3420 (DIL-050/051 priced acceptances)

---

## Numbered owner asks

1. **Pentest** — commission one or sign a dated declining row in the register's priced
   table (third consecutive assessment naming it; deliberately not self-signed).
2. **Signed artifacts** — same shape, can share ask 1's signing pass.
3. **#3429** — apply the four read-only grants to
   `infra/iam/github-actions-remediation-role.permissions.json` (JSON applied directly);
   four sentinel security checks have never once run under the scheduled role.
4. **The #1781 cleanup script** (`deploy/archive/onetime/cleanup_1781_redundant_iam_policies.sh`)
   was never run — the weekly IAM-drift noise is its residue.
5. **The two drills** — owner-present timed restore + D3 owner-handoff (Reliability's
   remaining criteria; also #3042 box 2's residual).
6. **`bash deploy/cdk_deploy.sh LifePlatformMonitoring`** — clears the ONE real
   `Pending owner cdk deploy` warning (dashboard `Tags`; the other six were the
   GetTemplate-`?` illusion, cured by #3435).
7. **#3424** — the coach-quality-gate 4% decision (accept/raise/speed-up/disclose).
8. **DIL-039/040 revisit is DUE** — the ≥10-graded-outcomes trigger fired 08-31; 21.6%
   lifetime forecast accuracy is in hand.
9. **#3042's "external" equivalence call** — needed only the day the numbers clear the bar.
10. **#2883 + #3390** — the standing gate:owner pair from the plan (weigh-in still
    pending upstream; per #3417, **hold the handles** for the full scan).

## Residuals / next picks

- **#3419** (Next·P2) — the full-board 429; decision + fix, natural next-session pick.
- **Now queue (fable lane): #3422** (the reject-only lease steward — carries this
  session's `[skip-reconcile]`-tip design note), **#3436** (the Engineering-leg pilot,
  sized with this drain's measured data: 8 lanes, ~150–225k tokens and 35–115 min each,
  3 self-recovered CI iterations, zero deaths), **#3423** (reader-audience canary
  escalation).
- **#3399's acceptance box 3** — measure `basis:"withdrawn"` emission on the next sweep
  (~09-02 23:42Z); tonight's pre-fix specimen predicts exactly one.
- **#3414's 30-day measurement** — read failure rate as failed/(passed+failed),
  `_fallback`=unjudged; then the keep-or-delete ADR-103 call (carried in its row).
- **#3403** — not-work — its own acceptance requires a week of post-#3378 duration data
  (earliest ~09-08).
- **#3430** (Later·P3) — the compute-pipeline flap root-cause.
- **#3437** — the `adrs` PR-exemption; unblocks the first lane that must mint a new ADR.
- **The 09-08 Architect-ritual first run** — not-work — #2849's reopen trigger; a no-report
  run reopens that epic by its own written dead-man.

**The through-line:** Session Q found instruments whose green came from being unable to
fail; Session R's counterpart is **affordances and warnings that could never succeed** —
a checkbox no reader could ever use (7 > 5 by arithmetic), six warnings no deploy could
ever clear (`?` ≠ `—` by API design), and a verdict no caller ever waited long enough to
receive (p50 > cap) — each cured not by retuning but by teaching the instrument what its
own wire actually carries.

---

## Plan for Session S (written 2026-09-02, post-wrap — owner-approved in-session)

Owner context: three shaping calls asked and answered — flagship = **all three, staged**;
#3419 decided **on evidence** in-session; **Monarch MCP is disabled**, so #1407's
finance-drop leg is ON HOLD (owner call) while the CFPB-5 half proceeds. A fourth call
(the advisor question) swapped the staff-legs phase for a **calculation-proof pass**:
#3422/#3423 stay in Now for a later session, and restore-drill prep was declined for now.
The full approved plan with file-level grounding lives at
`~/.claude/plans/quiet-exploring-music.md`; the phases:

1. **Phase 0 — boot + overnight reads:** steward armed with the run-bearing-sha fix;
   #3399 box-3 emission count from the 09-02 23:42Z artifact; #3414's verdict counter;
   swallow-check; headroom.
2. **Phase 1 — #3419 repair, decided on evidence:** measure the 5-persona wall time;
   raise-to-7 + parallelize if ~30s clears, else cap the UI at 5; the window-burn
   sub-fix (a doomed request must not consume the window) ships regardless, with a
   red-then-green regression on the exact 1+6>5 shape; live-verify + render-qa.
3. **Phase 2 — #1407's Monarch-free half:** the `financial_wellbeing` Tier-2 partition
   (EXTRA_QUERYABLE_PARTITIONS + SOURCE_CLASS + SOURCE_TIERS + DATA_GOVERNANCE bullet),
   the `log_financial_wellbeing` MCP tool with its OWN closed-set validator
   (`mcp/handler.py:204` allows extra args — the registry schema alone cannot meet
   acceptance box 2), the inverse-vocabulary privacy contract (amount/merchant/balance/
   account_id/transaction_id rejected, tested to fail once), CFPB-5 scoring with
   provenance, catalog regenerated. The Monarch aggregates whitelist ships NOW as the
   boundary contract; the drop + the buffer-months→sleep/HRV edge park with a written
   re-enable trigger — #1407 stays OPEN partial, box 3 blocked-on-Monarch dated.
4. **Phase 3 — the calculation-proof pass** (`/review accuracy`): fresh-context Fable
   agents re-derive each formula family behind a public claim (sleep math, readiness/
   ACWR, character engine vs the frozen 07-11 audit, calibration/Brier + the prediction
   evaluator incl. the #2219 `beats_null` class-check, flourishing EMA, time-affluence
   n_eff/FDR vs the methods-registry fingerprints, the new budget-ledger arithmetic) —
   adversarially verified, graded scorecard under `docs/reviews/`, findings filed;
   feeds the 09-08 Architect first run.
5. **Phase 4 — wrap**, owner asks re-surfaced (the standing 10 + the Monarch re-enable
   question when ready).
