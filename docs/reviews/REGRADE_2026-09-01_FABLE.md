# External Re-Assessment — §12 Non-Commercial Domains (2026-09-01, Fable, Session R)

**Instrument:** epic #3042 box 4 — *"an external re-assessment scores ≥9/10 on all
non-commercial domains."* Domain set: the source report's §12 acceptance matrix, 9
non-commercial domains, as reconstructed by `REGRADE_2026-08-29_FABLE.md` (whose criteria
columns were used verbatim). **Assessors:** three fresh-context Claude Fable 5 agents
(the model tier the standing rule requires), one per 3-domain slice, each instructed to
grade only from evidence it gathered live (`diligence_verify.py --strict` run per-agent,
live GitHub/CloudWatch/S3/DynamoDB reads, live site probes) — never from the register's
claims. A fourth adversarial pass (finding-verifier) reproduced every actionable claim
before disposition; its verdicts are in the table at the bottom. **Prior baseline:** the
08-29 re-grade's own lead sentence miscounted its table ("four of nine ≥9" over a table
holding two) — the corrected baseline is **2 of 9**.

**Verdict up front: box 4 is NOT met. Three of nine domains reach ≥9** (was 2 of 9).
Grades moved in both directions, which is evidence the instrument is measuring rather
than drifting upward: two domains fell on incidents that really happened (the ~34h
launch-day board outage; the unexplained #3396 served-stale window), and the two that
rose crossed on machinery that was verified adversarially in-run (the coach-prediction
cohort graded on schedule; the register coverage gate mutation-proved by the assessor's
own planted defect).

| §12 domain | 08-29 | **09-01** | Movement basis (observed, not narrated) |
|---|---|---|---|
| Privacy | 9.0 | **9.2** ✅ | 3/3 privacy playbooks PASS live (3,232 tracked files, 5/5 relocated docs 404, 33-field vocabulary absent from all 4 public endpoints); DIL-050 split-disposed with a dated priced row where "D-later" stood |
| Security | 8.0 | **8.5** | #3278 true on the wire (90d retention spot-checked n=2 of 17); #3340 boundary CLEAN via `verify_oidc_iam.py --strict` reproduced; CodeQL 0, Dependabot 0, secret-scanning + push protection on. Held under 9: pentest silence (3rd consecutive assessment), weekly CodeQL cadence vs steady-state-0 claim, 4 sentinel checks dark under the scheduled role (confirmed in verification, filed #3429); the live-vs-declared IAM finding was refuted as new — #1781 residue, its cleanup script simply never run (owner ask) |
| Release governance | 7.0 | **8.0** | The 08-29 blocker is closed and wire-verified: `main-required-fast-lane` ACTIVE with 2 named required checks, `apply_branch_protection.py --check` clean, and a real observed rejection in the 08-31 sentinel log. Held under 9: the owner bypass is the live majority path (9 of last 15 main-push evaluations, n=15), no signed artifacts and no declining row for them, site lane auto-deploys by design |
| AI safety | 8.5 | **8.5** | Hazard-before-model verified at all 3 doors; 124 safety-contract tests green; ADR-104 grounding survives #3415 (confirmed in source + live canary). The ADR-108 removal traded a false green (0 verdicts in 7d, n=8) for an honest unknown at zero measured capability change. Cap unchanged: clinician review (priced, DIL-031) |
| Data integrity | 9.0 | **8.5** | 229 tests green across the replay/census/manifest families and ADR-077 executed correctly through a real reset — but two served-stale events inside 72h (#3396 mechanism *unexplained*, closure's own words; compute-pipeline flap not root-caused) plus the instrument-less lean-mass floor (#3417) exceed what "earned by the catch-and-guard machinery" can absorb |
| Scientific validity | 7.5 | **9.0** ✅ | The 08-29 blocker cleared exactly as forecast: 10 cycle-14 coach predictions machine-graded 2026-08-31 the day their windows matured (4 confirmed/6 refuted + 8 expired, deterministic outcome notes), verified by direct DynamoDB read (2,806 rows); lifetime 37 graded at 21.6% accuracy served unflatteringly on `/api/predictions`; calibration ledger CROSS_PHASE and self-consistent through the reset (lifetime n=158 brier_skill 0.1715; cycle n=4 labeled insufficient_data) |
| Reliability | 8.5 | **8.0** | Replica at 37,880/37,905 objects (counted live — the backfill gap closed); operating calendar green; all 4 red alarms carry citations that survive scrutiny. Fell on the outcome half: a P1 reader outage ran ~34h across launch day with immediate detection and ~31h to escalation (the 72h citation bar), and both drills (restore, owner-handoff) remain open appointments |
| Product | 6.5 | **6.0** | The DIL-039/040 mechanical trigger FIRED on schedule (10 graded outcomes 2026-08-31, verified in the cross-phase ledger — the assessor's "trigger not fired" read was refuted in verification), but what it delivers is coach forecast skill (21.6% lifetime accuracy), not the criterion's first noun — independent evidence coaching changes behavior — which remains unevidenced; the priced row's revisit is now DUE. #3419 verified live (the full-board affordance structurally 429s and burns the reader's hour); #3376 unlanded at grade time; adverse-effects half documented-but-uninstrumented (#3417) |
| Governance | 8.5 | **9.0** ✅ | The 08-29 gap (register completeness had no derivation guard) is closed and was verified adversarially: the assessor's own planted defect (deleting DIL-041's row) flipped `register_maps_all_52` to FAIL; 13/13 strict PASS; three register spot-checks (016, 020, 050) found no over-claim; every documented exception carries an owner and a dated/named trigger |

## The through-line

The 08-29 through-line was *instruments and promises that hold only while a session is
looking.* This cycle's is narrower and better news: **the grades that moved, moved on
evidence, in both directions.** The platform's honesty machinery graded itself down where
incidents were real (Reliability, Data integrity, Product) at the same time as its
remediation machinery graded itself up where fixes were wire-verified (Release
governance, Security, Scientific validity, Governance). A re-grade where every number
rises is advocacy; this is not that.

## Gap list — what separates today from box 4 (owner-visible, per domain)

Six domains sit under 9. Every gap below is named, owned, and most are cheap:

1. **Product (6.0) — the epic's hard floor.** The DIL-039/040 revisit trigger is now MET
   (10 graded outcomes 2026-08-31): the row's revisit is due, with unflattering evidence
   in hand (21.6% lifetime forecast accuracy) — but forecast skill is not behavior-change
   evidence, so the domain's first criterion stays open and is an owner/product act, not
   a session's. The two buildable pieces are #3419 (the full-board 429, P2) and #3376
   (page-view instrumentation, lane in flight this session).
2. **Security (8.5):** (a) pentest — commission one or sign the dated declining row
   (owner act; third consecutive assessment naming it, and the verifier confirmed zero
   mentions outside the regrade docs); (b) the four dark sentinel checks under
   `github-actions-remediation-role` — CONFIRMED: the grants were never written to the
   permissions JSON, all four checks have never once succeeded under the scheduled role
   (filed this session as #3429, gate:owner — the JSON apply is a credentialed owner act); (c) the
   live-wider-than-declared IAM finding was REFUTED as new — it is #1781's bucket-3
   residue, triaged policy-by-policy in 2026-07 with ≈zero net privilege; the true
   residual is that the archived cleanup script was never run (owner ask); (d) CodeQL
   weekly cadence vs a zero-at-all-times claim — tighten or restate.
3. **Release governance (8.0):** signed artifacts need a dated declining row or the
   machinery (owner call); the owner-bypass majority path and the self-approvable gate
   are priced (#2834) and structural at this headcount — §12 read literally caps this
   domain until a second operator exists.
4. **Reliability (8.0):** reader-audience canary escalation (#3423, filed this session —
   the 31h gap's structural fix); the two owner-appointment drills (restore, handoff).
5. **Data integrity (8.5):** #3417 (re-point or retire the lean-mass floor — lane in
   flight); the #3396 class is detected-not-understood (Check 20 is the disposition;
   recurrence mints a class tracker); the compute-pipeline flap needs a carrier.
6. **AI safety (8.5):** clinician review — priced (DIL-031) with dated triggers; the
   honest cap stands until the owner elects to spend it. #3414 (async voice verdict —
   lane in flight) recovers the board's fidelity measurement.

## Documentation-truth findings (the brief's §4 requested attack)

1. Epic #3042's box-1 note said "20 of 52" for ~3 days over a 52/52 register —
   self-caught this session and converted into the derivation gate (b3e62b85a).
2. The full-board checkbox offered a panel the server structurally rejects since
   2026-08-20 (#3419).
3. `lean_mass_floor_lbs: 155` is a documented hard stop with no instrument (#3417).
4. #3365's "verified cleared" contradicted by production within a day (#3418).
5. The DIL-039/040 priced row is stale in the OPPOSITE direction from the assessor's
   read: the ≥10-graded-outcomes trigger was MET on 2026-08-31 (grades landed hours
   before the reset tombstoned the cohort), so the row's honest update is "trigger met —
   revisit due" (corrected in this PR).
6. Alarm-count fact appears with three values across surfaces (see disposition table).

## Adversarial verification of assessor findings (the ~50% rule)

The three assessors' actionable findings went through a finding-verifier pass before
any disposition. Verdicts and dispositions:

| # | Finding (assessor) | Verdict | Disposition |
|---|---|---|---|
| F1 | 4 sentinel security checks dark under the scheduled role | **CONFIRMED** — reproduced from the 08-31 drift-log; grants absent from the declared permissions JSON too (never written, not pending-apply); never once succeeded | Filed as **#3429** (grants → `infra/iam/github-actions-remediation-role.permissions.json`, gate:owner — the JSON is applied directly, never a shell twin) |
| F4 | Pentest: no evidence AND no dated declining row | **CONFIRMED** — the phrase exists only in the regrade docs; 3rd consecutive assessment | Owner ask (sign a dated declining/priced row, or commission one) — deliberately NOT self-added: a priced acceptance is an owner signature |
| F3 | No signed artifacts and no declining row | **CONFIRMED** (severity caveat: no bar names it — cheapest tier of real) | Owner ask, can share the F4 row-signing pass |
| F7 | compute-pipeline-stale flap: root cause deferred, no carrier | **CONFIRMED** — one episode, exactly 24h, not the #1962 class (ended before the reset ran) | Filed as **#3430** (root-cause or dated acceptance) |
| F2 | Live IAM wider than declared on ≥4 compute roles | **REFUTED** as new — #1781's bucket-3 residue, triaged statement-by-statement 2026-07, ≈zero net privilege | Residual = the archived cleanup script was never run: owner ask |
| F5 | 117 tombstoned predictions with no accounting mechanism | **REFUTED** — the mechanism is `prereg_voids` and it RAN: 118 `voided_at_reset` rows stamped 20:08:45Z, invariant-guarded | None |
| F6 | `beats_null: true` with NULL null-fields = vacuous | **REFUTED** — intentional per #2219; the numeric threshold/noise floor IS the null, documented in-code with the ADR-105 reasoning | None |
| F8 | DIL-039/040 "earliest 2026-08-31" made stale by the reset | **REFUTED, direction reversed** — the trigger was MET on 08-31 (10 graded outcomes; the reset voids OPEN bets only) | Register row updated in this PR: trigger met, revisit due |
| F9 | Alarm-count triple mismatch (113/115/117/119) | **REFUTED** — three instruments, three denominators; 117 is sync-owned and current, 119 = +2 composites, 113/115 was a pre-Session-O snapshot; the divergence is the sentinel's own job | None |

**Pass yield: 4 of 9 confirmed (44% false-positive rate — on the historical base rate; the pass remains load-bearing).**

**Box 4 stays OPEN.** The register is complete (52/52, gate-enforced), boxes 1–3 of the
epic are reconciled true, and this re-grade is the fresh per-domain measurement the epic
asked for — but the Outcome sentence requires ≥9 on ALL non-commercial domains and the
honest count is 3 of 9. Whether a self-run fresh-context re-assessment satisfies
"external" is the owner's call, recorded as an explicit ask on the epic; either way the
score does not yet clear the bar, so no equivalence ruling is needed to keep the epic
open today.
