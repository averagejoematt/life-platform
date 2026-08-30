# External Re-Assessment — §12 Non-Commercial Domains (2026-08-29, Fable)

**Instrument:** epic #3042 box 4 — *"an external re-assessment scores ≥9/10 on all
non-commercial domains."* The domain set is the source report's §12 A-grade acceptance
matrix (10 domains; "Commercial readiness" excluded as the one commercial domain).
**Assessor:** Claude Fable 5 — the model tier the standing rule requires (a review
ritual's model is part of its validity; the grading precedent is the Fable week,
2026-08-16). **Method:** every grade below is grounded in evidence gathered LIVE this
session — `scripts/diligence_verify.py` (12/12 PASS after same-day DIL-018 re-triage),
live GitHub API state, live site API reads, and the register walk that found and fixed
the register's own gaps (3 missing DIL rows, 1 contradictory duplicate, 2 missing
priced rows). Nothing is graded from the register's own claims.

**Verdict up front: box 4 is NOT met.** Four of nine domains reach ≥9; five do not.
Per the epic's discipline this is the deliverable — a box-by-box verdict with the gap
list — not a miss dressed as one. The through-line of what keeps the platform under
9 is consistent with Session I's: *instruments and promises that hold only while a
session is looking* (CodeQL triage has no dead-man; the priced register's completeness
sentence was false within 5 days; main's required-checks posture was written and never
applied).

| §12 domain | Criterion (abbreviated) | Grade | Basis |
|---|---|---|---|
| Privacy | no owner-only exposure · machine-enforced tiers · accurate notices · tested deletion · audited downstream propagation | **9.0** | ✅ live: no-private-markers (3,154 tracked files, mutation-proved), relocated docs 404 on raw endpoint, ADR-155 consent stamps, full field_tiers port + both-direction drift guard (#3045), anonymize-at-unsubscribe + window-0 + deletion-evidence test (#3044), owner-only vocabulary (33 fields) absent from all 4 public endpoints (verify PASS). Gap held at 9.0, not above: DIL-050 downstream deletion map is D-later, and the historical-exposure acceptance is priced, not erased. |
| Security | trusted edge identity · WAF · no open critical/high findings · enabled alerts · least privilege · credential hygiene · pentest evidence | **8.0** | ✅ live: CodeQL 0 open (after this session's 6-alert re-triage), vulnerability alerts 204-enabled, edge identity fail-closed + AST-guarded + wire-proved, per-Lambda least-privilege roles, SECRETS_MAP rotation register. ❌ WAF deliberately absent (priced, compensating stack live — defensible); **no third-party penetration evidence at all** (§12 names it); **#3278 OPEN: security-log retention is 30d in two regions and NEVER-EXPIRE in five while docs say 90d**, cf-auth not CDK-owned; CodeQL regrowth sat untriaged 3–4 days because triage has no dead-man. A 9 here would be manufactured. |
| Release governance | required human production approval · no unrestricted automation bypass · signed artifacts · independent protected environments | **7.0** | ✅ live: production environment gate blocking (re-verified), automerge in shadow with deterministic ALLOWLIST + IAM held out (#2611), drift-guarded CDK deploys. ❌ **main has ZERO required status checks — live `gh api` today: branch not protected; the sole ruleset blocks force-push/deletion only.** `main-required-fast-lane` was authored and never applied (D0.6 pending, #3288 owner batch). No signed artifacts. Site lane auto-deploys with no approval by design (honestly documented, but §12 says "required human production approval" and one of two lanes has none). Approval gate is self-approvable (priced, #2834). |
| AI safety | grounding + temporal context · injection resistance · policy-based refusal · clinician-reviewed hazard scenarios | **8.5** | ✅ live: grounded-generation gate on every narrative surface (ADR-104), phase/temporal context coverage tests, #3050 adversarial goldens (grounding/temporal/injection/privacy/refusal) in the premerge lane, hazard-gate-before-model ordering contract proved both directions, single Bedrock chokepoint + fail-closed budget guard, and #3294 (this session) closing the last class of unlicensed absence claims with a derived surface enumeration. ❌ **clinician-reviewed hazard scenarios do not exist** — the clinical-LITE register is built, the clinician is not; priced (DIL-031) but §12 lists it in this domain, so the point is real. |
| Data integrity | typed source contracts · provenance · completeness · idempotent replay · timezone correctness · deterministic derived records | **9.0** | ✅ live: registry facets as the single source (raw_layout/evidence_for/behavioral/filename_legacy), DIL-028's 48-test replay proof against REAL S3 listings, replay census + send ledger with all five non-cheap classes closed (#3113–#3119), input-manifest completeness stamps on all 5 compute fleets (#3049, 3-way mutation-proved), PT-frame discipline enforced by gates that have caught live incidents, deterministic-before-LLM (ADR-105). Residual honestly noted: tz defects still OCCUR (the #3196 UTC-midnight class two weeks ago) — 9.0 is earned by the catch-and-guard machinery, not by defect absence. |
| Scientific validity | graded predictions · calibrated metrics · pre-registered experiments · uncertainty · no unsupported causal claims | **7.5** | ✅ live: calibration self-consistent and unflattering (n=60, brier_skill −0.013, labeled "not_yet_skillful" in public), emission contract makes ungradeable-by-construction unbuildable (#3046), GradableShare alarm OK, prereg + dry-run review live, causal overreach swept. ❌ **zero coach predictions have EVER been graded** — the earliest maturity window opens 2026-08-31. "Graded predictions" is §12's first noun and it is structurally, not negligently, unmet. This grade rises mechanically as windows mature; today it is 7.5. |
| Reliability | outcome-based SLOs · tested heartbeats · meaningful alerting · proven RTO/RPO · independent restore drills | **8.5** | ✅ live: operating calendar green today (every ritual has run ≥1, none outside window), dead-man estate + heartbeat completeness tests, 116 alarms with the emission-dimension gate, sentinel family mutation-proved to the two-half bar, raw/ cross-region replica with wire-probing weekly assertion, restart/rollback pipelines exercised repeatedly in anger. ❌ the owner-present timed restore drill is still an open appointment (DIL-027 register), the D3 owner-handoff drill has not run, and compute is single-region (priced). |
| Product | users complete useful actions from recommendations · engagement, retention, burden, adverse effects measured | **6.5** | ✅ live: reader engagement loop, coach track-record surfaces, honest labels, burden partially visible (checkin/queue telemetry). ❌ **no independent evidence coaching changes behavior** (DIL-039) — and until this session that acceptance was "PRICED" with no dated row anywhere, the exact unbacked-disposition shape the register bans; adverse-effect measurement absent; feature surface exceeds evidence visible to users (DIL-040). Now priced with a MECHANICAL revisit (first graded cohort), but a 6.5 is what the evidence supports today. |
| Governance | canonical facts match production · independent reviewers validate controls · documented exceptions have owners and expiry | **8.5** | ✅ live: the doc-truth machinery is the platform's genuine differentiator — doc-facts gates, managed-where per-row re-verify + monthly dead-man, the truth manifest (one ceiling source), public-claims registry with wire-real comparators both directions, 15 sentinel checks with recorded two-half proofs, priced register with dated triggers. ❌ graded against its own bar: this session's walk found the register itself had drifted within 5 days of its D5 finalization (3 missing DIL ids, a contradictory duplicate 028 row, a false completeness sentence over the priced table). The machinery caught none of that — a person did. Fixed today; the class question (register completeness has no derivation guard) is the gap. |

## Gap list — what separates today from box 4

Ordered by leverage, each with its owner:

1. **#3288 (owner batch): apply the authored `main-required-fast-lane` required-checks
   posture to main.** Release governance cannot pass 7 while a bare `git push` to main
   is structurally accepted. One owner action; the posture file already exists.
2. **First graded prediction cohort (mechanical, 2026-08-31+).** Scientific validity
   7.5→9 and Product's revisit trigger both hang on windows that begin maturing in two
   days. No work to do except not break the evaluator.
3. **#3278: security-log retention divergence** (30d vs NEVER-EXPIRE vs the documented
   90d) + cf-auth CDK ownership. Security stays ≤8 while the platform's own security
   telemetry contradicts its documented retention.
4. **Pentest evidence or its priced acceptance.** §12 names third-party penetration
   evidence; the platform has neither the evidence nor a dated row declining it. Either
   is acceptable; silence is not.
5. **CodeQL triage dead-man.** Steady-state-0 regrew to 6 open highs within 3 days of
   #3047 closing and no instrument said so. The class belongs to #2578's sentinel
   family (the declared-armed sentinel that did not fire).
6. **D3 owner-handoff + restore drills** (scheduled owner appointments; reliability's
   remaining criterion).
7. **Register completeness derivation guard** — the priced table's "every acceptance
   has a row" sentence should be checkable, not prose (the DIL-039/040 hole proves it).
8. **Clinician review of the hazard-LITE register** — or keep it priced and accept AI
   safety caps at 8.5.

## What this means for the epic

Boxes 1 (52/52 dispositions — after today's register fixes) and 3
(`diligence_verify.py` 12/12) are TRUE today. Box 2 is false on two named items
(D0.6 posture apply; D3 drills). Box 4 is false per this grade. The epic stays open,
its Outcome intact and achievable — items 1 and 2 above close the two largest gaps
essentially for free, and nothing on the list requires machinery the platform
doesn't already know how to build.
